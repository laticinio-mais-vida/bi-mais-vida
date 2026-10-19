"""Página Gestão: campanhas de vendas num quadro (kanban), com o andamento de cada vendedor.

- Campanha: nome, período, o que ela mede (um dos tipos de bi/indicadores.py: positivação, mix médio, efetividade,
  frequência, preço médio por produto ou uma Personalizada montada por blocos), filtros de produto e de cliente,
  base de clientes, vendedores participantes e metas (uma padrão, com ajuste por vendedor; no preço médio, um
  preço-alvo por produto). Fica no PostgreSQL (bi/migracoes/007_gestao.sql e 008_indicadores.sql); o status (coluna
  do quadro) muda só quando alguém arrasta o card, e o quadro sugere a mudança quando as datas dizem que ela já
  devia ter acontecido.
- Quem vê: cada pessoa vê e mexe só nas campanhas que criou; o administrador vê as dele e, pedindo, as de todos (e
  mexe em qualquer uma). Os vendedores que a pessoa pode pôr numa campanha, e que vê no andamento, são os do acesso
  dela na página (Gestão › Configurar, como em Projeções e no Assistente).
- Andamento: calculado na hora (bi/indicadores.py) no recorte com todos os vendedores do Assistente, filtrando os
  vendedores no SQL. O quadro guarda as contas no próprio recorte, que é refeito quando os dados ou as regras mudam.
- Dias de atendimento das áreas comerciais (para a efetividade): tabela areas_atendimento, que o administrador
  ajusta em Gestão › Configurar.
- O Assistente usa as mesmas funções (ContextoGestao): propor_campanha confere um rascunho sem gravar (quem cria é a
  pessoa, no botão), e andamento_campanha dá os números da página.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
from collections import defaultdict

from .banco import hora
from .calendario import Calendario
from .configuracao import Regras
from .conversas import NaoEncontrada, id_valido, novo_id
from .indicadores import (ABERTURAS, BASES, BASES_COM_PRODUTO, COMBINACOES, COMPARAR, FILTROS, FILTROS_PRODUTO,
                          FORMAS, MAX_PRODUTOS_PRECO, MEDIDAS, TIPOS, _marcas, calcular,
                          calendario_periodo, descritor, filtros_aceitos, normalizar, periodo_base, unidades)
from .projecoes import NOME_EQUIPE

__all__ = ["Gestao", "ContextoGestao", "SemDados", "andamento", "calendario_periodo", "unidades", "validar",
           "sugestao", "status_inicial", "publica"]

STATUS = {"planejada": "Planejada", "andamento": "Em andamento", "concluida": "Concluída"}
GRUPOS = ("mussarela", "outras")
EQUIPES = ("ES", "BA", "EDIR")
MAX_NOME = 120
MAX_TEXTO = 2000
MAX_DIAS = 366
MAX_MEMO = 500
TRAVA_QUADRO = 7_240_103  # pg_advisory_xact_lock: duas pessoas arrastando cards não embaralham a ordem
DIAS_SEMANA = {"SEGUNDA": 1, "TERCA": 2, "QUARTA": 3, "QUINTA": 4, "SEXTA": 5, "SABADO": 6, "DOMINGO": 7}
_CAMPOS = ("c.id, c.nome, c.descricao, c.premiacao, c.status, c.ordem, c.inicio, c.fim, c.metrica, c.parametros, "
           "c.filtros, c.meta_padrao, c.arquivada, c.rascunho, c.criada_em, c.criada_por, c.criada_por_nome, "
           "c.atualizada_em, c.atualizada_por_nome")


class SemDados(RuntimeError):
    """Os dados de vendas ainda não estão prontos (o servidor responde 503)."""


def _data(texto, campo: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(texto or "")[:10])
    except ValueError:
        raise ValueError(f"a data de {campo} deve ser AAAA-MM-DD (veio {texto!r})") from None


def _numero(valor, campo: str) -> float:
    try:
        n = float(valor or 0)
    except (TypeError, ValueError):
        raise ValueError(f"{campo} deve ser um número (veio {valor!r})") from None
    if n != n or n < 0 or n > 1e12:
        raise ValueError(f"{campo} deve ser um número de 0 para cima")
    return n


def _texto(valor, campo: str, maximo: int = MAX_TEXTO) -> str:
    t = str(valor or "").strip()
    if len(t) > maximo:
        raise ValueError(f"{campo} pode ter até {maximo} caracteres")
    return t


def _dm(d: dt.date) -> str:
    return f"{d:%d/%m}"


# --- conferência ------------------------------------------------------------------------------
def _canonicos(cur, sql: str, valores: list[str], erro: str) -> list[str]:
    """Os valores como estão nos dados (sem diferenciar maiúsculas e acentos); levanta ValueError se algum não existe."""
    existentes = {}
    for (v,) in cur.execute(sql).fetchall():
        if v:
            existentes.setdefault(_chave(v), v)
    saida, faltam = [], []
    for v in valores:
        achado = existentes.get(_chave(v))
        (saida if achado else faltam).append(achado or v)
    if faltam:
        raise ValueError(f"{erro} nos dados: {', '.join(faltam)}")
    return list(dict.fromkeys(saida))


def _chave(texto) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


def _lista(valor, campo: str) -> list:
    if valor in (None, ""):
        return []
    if not isinstance(valor, (list, tuple)):
        raise ValueError(f"{campo} deve ser uma lista")
    return [v for v in valor if v not in (None, "")]


def _produtos_validos(cur, regras: Regras, brutos: list) -> list[int]:
    """Códigos de produto como as vendas os têm (o equivalente), sem repetir; levanta ValueError se algum não existe
    ou está marcado como "não conta"."""
    produtos = []
    for p in brutos:
        try:
            produtos.append(regras.produto(int(p)))  # as vendas já vêm com o produto equivalente
        except (TypeError, ValueError):
            raise ValueError(f"código de produto inválido: {p!r}") from None
    produtos = list(dict.fromkeys(produtos))
    if not produtos:
        return []
    achados = dict(cur.execute(f"SELECT id_produto, grupo FROM produtos WHERE id_produto IN ({_marcas(produtos)})",
                               produtos).fetchall())
    faltam = [str(p) for p in produtos if p not in achados]
    if faltam:
        raise ValueError(f"produto não encontrado: {', '.join(faltam)}")
    fora = [str(p) for p in produtos if achados[p] == "fora"]
    if fora:
        raise ValueError(f"produto marcado como \"não conta\" nas regras das metas: {', '.join(fora)}")
    return produtos


def _filtros(bruto: dict, cur, regras: Regras) -> dict:
    """Confere os filtros e devolve só os preenchidos, com os valores como estão nos dados."""
    if not isinstance(bruto, dict):
        raise ValueError("filtros inválidos")
    desconhecidos = set(bruto) - set(FILTROS)
    if desconhecidos:
        raise ValueError(f"filtro desconhecido: {', '.join(sorted(desconhecidos))}")
    saida = {}
    produtos = _produtos_validos(cur, regras, _lista(bruto.get("produtos"), "produtos"))
    if produtos:
        saida["produtos"] = produtos
    grupos = [str(g).strip().lower() for g in _lista(bruto.get("grupos"), "grupos")]
    if any(g not in GRUPOS for g in grupos):
        raise ValueError("grupo deve ser mussarela ou outras")
    if grupos:
        saida["grupos"] = list(dict.fromkeys(grupos))
    textos = {
        "linhas": ("SELECT DISTINCT linha FROM produtos", "linha não encontrada"),
        "ufs": ("SELECT DISTINCT uf FROM clientes", "UF não encontrada"),
        "segmentos": ("SELECT DISTINCT segmento FROM clientes", "segmento não encontrado"),
        "areas": ("SELECT DISTINCT area FROM clientes", "área comercial não encontrada"),
    }
    for chave, (sql, erro) in textos.items():
        valores = [str(v).strip() for v in _lista(bruto.get(chave), chave)]
        if valores:
            saida[chave] = _canonicos(cur, sql, valores, erro)
    categorias = [str(c).strip() for c in _lista(bruto.get("categorias"), "categorias")]
    if categorias:
        conhecidas = {_chave(c): c for c in regras.categorias}
        faltam = [c for c in categorias if _chave(c) not in conhecidas]
        if faltam:
            raise ValueError(f"categoria não existe nas regras das metas: {', '.join(faltam)} "
                             f"(as categorias são: {', '.join(regras.categorias) or 'nenhuma'})")
        saida["categorias"] = list(dict.fromkeys(conhecidas[_chave(c)] for c in categorias))
    return saida


def _metas_produto(bruto, cur, regras: Regras) -> list[dict]:
    """Preço médio: [{id, meta}] com o código equivalente, sem repetir (o último preço vale)."""
    itens = _lista(bruto, "metas_produto")
    if not itens:
        raise ValueError("no preço médio, escolha os produtos e o preço-alvo de cada um (metas_produto)")
    if len(itens) > MAX_PRODUTOS_PRECO:
        raise ValueError(f"o preço médio acompanha até {MAX_PRODUTOS_PRECO} produtos")
    alvos = {}
    for i in itens:
        if not isinstance(i, dict) or i.get("id") in (None, ""):
            raise ValueError("metas_produto: use uma lista de {id, meta}")
        pid, = _produtos_validos(cur, regras, [i["id"]])
        meta = _numero(i.get("meta"), f"o preço-alvo do produto {i['id']}")
        if not meta:
            raise ValueError(f"dê o preço-alvo do produto {i['id']} (R$ por unidade)")
        alvos[pid] = meta
    return [{"id": p, "meta": m} for p, m in alvos.items()]


def validar(dados: dict, cur, regras: Regras, permitidos: frozenset[int] | None, data_ref: dt.date,
            inicio_dados: dt.date | None = None) -> dict:
    """Confere uma campanha vinda da página ou do Assistente e devolve os dados normalizados. cur: cursor do recorte
    com todos os vendedores. inicio_dados: o começo do histórico do cache (para a base de clientes e o crescimento).
    Levanta ValueError com a explicação (a IA lê e corrige)."""
    if not isinstance(dados, dict):
        raise ValueError("campanha inválida")
    nome = " ".join(str(dados.get("nome") or "").split())
    if not nome:
        raise ValueError("dê um nome à campanha")
    if len(nome) > MAX_NOME:
        raise ValueError(f"o nome da campanha pode ter até {MAX_NOME} caracteres")
    inicio, fim = _data(dados.get("inicio"), "início"), _data(dados.get("fim"), "fim")
    if fim < inicio:
        raise ValueError("o fim da campanha é antes do início")
    if (fim - inicio).days >= MAX_DIAS:
        raise ValueError("a campanha pode durar até um ano")
    metrica, parametros = normalizar(dados.get("metrica"), dados.get("parametros"))
    filtros = _filtros(dados.get("filtros") or {}, cur, regras)
    fora = [k for k in filtros if k not in filtros_aceitos(metrica, parametros)]
    if fora:
        raise ValueError({"efetividade": "a efetividade conta pedidos e visitas, sem produto: use só filtros de "
                                         "cliente (UF, segmento, área)",
                          "preco_medio": "no preço médio os produtos vêm da lista de preços-alvo (metas_produto); "
                                         "os filtros são só de cliente (UF, segmento, área)"}[metrica])
    com_produto = any(filtros.get(k) for k in FILTROS_PRODUTO)
    if parametros.get("clientes") in BASES_COM_PRODUTO and not com_produto:
        raise ValueError(f"para contar {BASES[parametros['clientes']]}, escolha os produtos da campanha (produtos, "
                         "linhas, categorias ou grupo)")
    if parametros.get("medida") == "volume":
        if not com_produto:
            raise ValueError("campanha de volume precisa de um filtro de produto (produtos, linhas, categorias ou "
                             "grupo), para somar quantidades da mesma unidade")
        achadas = unidades(cur, filtros, data_ref)
        if len(achadas) > 1:
            raise ValueError(f"os produtos escolhidos têm unidades diferentes ({', '.join(u or 'sem unidade' for u in achadas)}); "
                             "numa campanha de volume use produtos da mesma unidade")
    if inicio_dados:
        if parametros.get("clientes") == "recuperados" and inicio - dt.timedelta(days=parametros["dias_sem_compra"]) <= inicio_dados:
            raise ValueError(f"o histórico de vendas começa em {inicio_dados:%d/%m/%Y}: com {parametros['dias_sem_compra']} "
                             "dias sem compra antes do início, nenhum cliente teria como ser recuperado")
        if parametros.get("forma") == "crescimento":
            de, a = periodo_base(inicio, fim, parametros["comparar"])
            if de < inicio_dados:
                raise ValueError(f"o período de comparação ({de:%d/%m/%Y} a {a:%d/%m/%Y}) começa antes do histórico "
                                 f"de vendas ({inicio_dados:%d/%m/%Y})")
    metas_produto = []
    if metrica == "preco_medio":
        metas_produto = _metas_produto(dados.get("metas_produto"), cur, regras)
        meta_padrao = 100.0  # 100% do preço-alvo
    else:
        meta_padrao = _numero(dados.get("meta_padrao"), "a meta padrão")

    vendedores: dict[int, float | None] = {}
    for v in _lista(dados.get("vendedores"), "vendedores"):
        bruto = v if isinstance(v, dict) else {"id": v}
        try:
            vid = int(bruto.get("id"))
        except (TypeError, ValueError):
            raise ValueError(f"código de vendedor inválido: {bruto.get('id')!r}") from None
        meta = bruto.get("meta")
        vendedores[vid] = (None if meta in (None, "") or metrica == "preco_medio"
                           else _numero(meta, f"a meta do vendedor {vid}"))
    if not vendedores:
        raise ValueError("escolha os vendedores da campanha")
    ids = sorted(vendedores)
    nomes = dict(cur.execute(f"SELECT id_vendedor, vendedor FROM vendedores WHERE id_vendedor IN ({_marcas(ids)})",
                             ids).fetchall())
    faltam = [str(v) for v in ids if v not in nomes]
    if faltam:
        raise ValueError(f"vendedor não encontrado: {', '.join(faltam)}")
    if permitidos is not None:
        fora = [f"{nomes[v]} ({v})" for v in ids if v not in permitidos]
        if fora:
            raise ValueError(f"fora do seu acesso na Gestão: {', '.join(fora)}")
    return {
        "nome": nome, "descricao": _texto(dados.get("descricao"), "a descrição"),
        "premiacao": _texto(dados.get("premiacao"), "a premiação"), "inicio": inicio, "fim": fim,
        "metrica": metrica, "parametros": parametros, "filtros": filtros, "meta_padrao": meta_padrao,
        "vendedores": [{"id": v, "meta": vendedores[v]} for v in ids], "metas_produto": metas_produto,
    }


# --- andamento --------------------------------------------------------------------------------
def andamento(cur, campanha: dict, regras: Regras, cal: Calendario, data_ref: dt.date,
              permitidos: frozenset[int] | None, areas: dict | None = None, abrir: str | None = None) -> dict:
    """Realizado, meta, % e situação de cada vendedor da campanha (só os do acesso de quem vê) e o total."""
    return calcular(cur, campanha, regras, cal, data_ref, permitidos, areas, abrir)


def sugestao(campanha: dict, hoje: dt.date) -> dict | None:
    """Quando as datas dizem que o card já devia estar em outra coluna."""
    st, inicio, fim = campanha["status"], campanha["inicio"], campanha["fim"]
    if st == "planejada" and hoje > fim:
        return {"status": "concluida", "texto": f"Terminou em {_dm(fim)}"}
    if st == "planejada" and hoje >= inicio:
        return {"status": "andamento", "texto": f"Começou em {_dm(inicio)}"}
    if st == "andamento" and hoje > fim:
        return {"status": "concluida", "texto": f"Terminou em {_dm(fim)}"}
    return None


def status_inicial(inicio: dt.date, fim: dt.date, hoje: dt.date) -> str:
    """Coluna de uma campanha nova: a das datas (depois disso, só muda arrastando)."""
    return "concluida" if hoje > fim else ("andamento" if hoje >= inicio else "planejada")


def _campanha(linha, vendedores: list[dict], produtos: list[dict]) -> dict:
    (id_, nome, descricao, premiacao, st, ordem, inicio, fim, metrica, parametros, filtros, meta_padrao, arquivada,
     rascunho, criada_em, criada_por, criada_por_nome, atualizada_em, atualizada_por_nome) = linha
    return {
        "id": id_, "nome": nome, "descricao": descricao, "premiacao": premiacao, "status": st, "ordem": ordem,
        "inicio": inicio, "fim": fim, "metrica": metrica, "parametros": parametros or {}, "filtros": filtros or {},
        "meta_padrao": float(meta_padrao), "arquivada": arquivada, "rascunho": str(rascunho) if rascunho else None,
        "criada_em": criada_em.isoformat(timespec="seconds"), "criada_por": criada_por, "criada_por_nome": criada_por_nome,
        "atualizada_em": atualizada_em.isoformat(timespec="seconds"), "atualizada_por_nome": atualizada_por_nome,
        "vendedores": vendedores, "metas_produto": produtos,
    }


def publica(c: dict) -> dict:
    """A campanha como a página e a IA recebem (datas em texto e o descritor do que ela mede)."""
    return {**c, "inicio": c["inicio"].isoformat(), "fim": c["fim"].isoformat(),
            "indicador": descritor(c["metrica"], c["parametros"])}


def dias_do_nome(nome: str) -> list[int]:
    """Dias de atendimento (ISO) que o nome da área diz: "TEIXEIRA (SEXTA)" = [5]; "LORENA CENTRAL (SEGUNDA A
    SEXTA)" = [1..5]; "EUNÁPOLIS CENTRAL (SEGUNDA E TERÇA)" = [1, 2]. Só uma sugestão: quem decide é o administrador."""
    t = _chave(nome).upper()
    dias = "|".join(DIAS_SEMANA)
    intervalo = re.search(rf"\b({dias})\s+(?:A|ATE)\s+({dias})\b", t)
    if intervalo:
        a, b = DIAS_SEMANA[intervalo.group(1)], DIAS_SEMANA[intervalo.group(2)]
        return list(range(a, b + 1)) if a <= b else []
    return sorted({DIAS_SEMANA[d] for d in re.findall(rf"\b({dias})\b", t)})


# --- campanhas no banco -----------------------------------------------------------------------
class Gestao:
    def __init__(self, banco, calc, assistente):
        """assistente: o bi/assistente.py, de onde vêm o recorte com todos os vendedores e o escopo em ids."""
        self.banco = banco
        self.calc = calc
        self.assistente = assistente

    # --- dados do ERP ------------------------------------------------------------------------
    def _conferir_dados(self) -> None:
        cache = self.calc.cache
        if not cache.pronto():
            raise SemDados("os dados de vendas ainda estão sendo preparados; o andamento aparece quando ficarem prontos")
        if cache.sem_detalhe:
            raise SemDados("os dados por cliente ainda não chegaram do computador da empresa; o andamento aparece "
                           "depois da próxima atualização")

    def _recorte(self):
        self._conferir_dados()
        return self.assistente.recorte(None)

    def _cursor(self):
        return self._recorte().cursor()

    def _data_ref(self) -> dt.date:
        return self.calc.cache.data_ref() or dt.date.today()

    def _inicio_dados(self) -> dt.date:
        return self.calc.cache.inicio

    def ids(self, escopo) -> frozenset[int] | None:
        """escopo: (vendedores, equipes) de bi/acesso.py escopo_gestao -> os ids (None = todos)."""
        vendedores, equipes = escopo
        if vendedores is None and equipes is None:
            return None
        self._conferir_dados()
        return self.assistente.ids_do_escopo(vendedores, equipes)

    def catalogo(self, escopo) -> dict:
        """O que o formulário oferece: vendedores do acesso (com venda nos últimos 12 meses), produtos vendidos nos
        últimos 12 meses (sem os "não conta", com o preço médio dos últimos 90 dias), linhas, categorias, UFs,
        segmentos e áreas comerciais, e os tipos de campanha."""
        cur = self._cursor()
        try:
            ids = self.ids(escopo)
            vendedores = [v for v in self.assistente.catalogo_vendedores() if ids is None or v["id"] in ids]
            data_ref = self._data_ref()
            desde = data_ref - dt.timedelta(days=365)
            precos = dict(cur.execute(
                "SELECT id_produto, SUM(valor_liquido) / NULLIF(SUM(quantidade), 0) FROM faturamento "
                "WHERE data > ? GROUP BY 1", [data_ref - dt.timedelta(days=90)]).fetchall())
            produtos = [{"id": p, "nome": n, "unidade": (u or "").strip().upper(), "linha": li, "grupo": g,
                         "categoria": c, "venda_12m": round(v or 0, 2),
                         "preco_90d": round(precos[p], 2) if precos.get(p) and precos[p] > 0 else None}
                        for p, n, u, li, g, c, v in cur.execute(
                "WITH v AS (SELECT id_produto, SUM(valor) AS venda FROM _vendas WHERE data > ? GROUP BY 1) "
                "SELECT p.id_produto, p.produto, p.unidade, p.linha, p.grupo, p.categoria, v.venda FROM produtos p "
                "JOIN v USING (id_produto) WHERE p.grupo <> 'fora' ORDER BY v.venda DESC", [desde]).fetchall()]
            linhas = sorted({p["linha"] for p in produtos if p["linha"]})
            clientes = cur.execute("SELECT DISTINCT uf, segmento, area FROM clientes WHERE ultima_compra > ?",
                                   [desde]).fetchall()
        finally:
            cur.close()
        regras = self.calc.regras()
        equipes = [{"id": e, "nome": NOME_EQUIPE[e]} for e in (*EQUIPES, "OCULTO") if any(v["equipe"] == e for v in vendedores)]
        return {
            "vendedores": vendedores, "equipes": equipes, "produtos": produtos, "linhas": linhas,
            "categorias": regras.categorias, "grupos": list(GRUPOS),
            "ufs": sorted({u for u, _, _ in clientes if u}), "segmentos": sorted({s for _, s, _ in clientes if s}),
            "areas": sorted({a for _, _, a in clientes if a}), "inicio_dados": self._inicio_dados().isoformat(),
            "tipos": tipos(),
        }

    def _areas(self) -> dict[int, list[int]]:
        """Dias de atendimento de cada área ({id_area: [dias ISO]}; [] = área não atendida)."""
        with self.banco.conexao() as con:
            return {a: list(d) for a, d in con.execute("SELECT id_area, dias FROM areas_atendimento")}

    def _andamento(self, cur, c: dict, ids, areas=None, abrir=None) -> dict:
        if c["metrica"] == "efetividade":
            if self.calc.cache.sem_pedidos:
                raise SemDados("os pedidos de venda ainda não chegaram do computador da empresa; a efetividade "
                               "aparece depois da próxima atualização")
            if areas is None:
                areas = self._areas()
        regras = self.calc.regras()
        return andamento(cur, c, regras, self.calc.calendario(regras), self._data_ref(), ids, areas, abrir)

    # --- leitura -----------------------------------------------------------------------------
    @staticmethod
    def _dono(usuario: dict) -> tuple[str, list]:
        """Quem mexe na campanha: o administrador em todas, os outros só nas que criaram."""
        if usuario["papel"] == "admin":
            return "TRUE", []
        return "c.criada_por = %s", [usuario["id"]]

    @staticmethod
    def _ler(con, onde: str, params: list, travar: bool = False) -> list[dict]:
        linhas = con.execute(f"SELECT {_CAMPOS} FROM campanhas c WHERE {onde} ORDER BY c.ordem, c.id"
                             + (" FOR UPDATE" if travar else ""), params).fetchall()
        vendedores, produtos = defaultdict(list), defaultdict(list)
        if linhas:
            ids = [[ln[0] for ln in linhas]]
            for camp, vid, meta in con.execute(
                    "SELECT campanha, id_vendedor, meta FROM campanha_vendedores WHERE campanha = ANY(%s) "
                    "ORDER BY campanha, id_vendedor", ids):
                vendedores[camp].append({"id": vid, "meta": None if meta is None else float(meta)})
            for camp, pid, meta in con.execute(
                    "SELECT campanha, id_produto, meta FROM campanha_produtos WHERE campanha = ANY(%s) "
                    "ORDER BY campanha, id_produto", ids):
                produtos[camp].append({"id": pid, "meta": float(meta)})
        return [_campanha(ln, vendedores[ln[0]], produtos[ln[0]]) for ln in linhas]

    def _uma(self, con, usuario: dict, id_, travar: bool = False) -> dict:
        try:
            id_ = int(id_)
        except (TypeError, ValueError):
            raise NaoEncontrada("campanha não encontrada") from None
        onde, params = self._dono(usuario)
        achadas = self._ler(con, f"c.id = %s AND {onde}", [id_, *params], travar)
        if not achadas:
            raise NaoEncontrada("campanha não encontrada; ela pode ter sido excluída")
        return achadas[0]

    def listar(self, usuario: dict, escopo, todas: bool = False, arquivadas: bool = False) -> dict:
        """As campanhas do quadro. As que já começaram trazem o total do andamento (para a barra do card); as contas
        ficam guardadas no recorte até os dados, as regras ou a campanha mudarem."""
        if usuario["papel"] == "admin" and todas:
            onde, params = "TRUE", []
        else:
            onde, params = "c.criada_por = %s", [usuario["id"]]
        if not arquivadas:
            onde += " AND NOT c.arquivada"
        with self.banco.conexao() as con:
            campanhas = self._ler(con, onde, params)
        hoje, aviso = dt.date.today(), None
        ativas = [c for c in campanhas if c["status"] != "planejada"]
        totais, avisos = {}, {}
        if ativas:
            try:
                recorte = self._recorte()
                ids = self.ids(escopo)
                areas = self._areas() if any(c["metrica"] == "efetividade" for c in ativas) else None
                versao_areas = json.dumps(sorted(areas.items())) if areas is not None else None
                cur = recorte.cursor()
                try:
                    for c in ativas:
                        chave = ("gestao", c["id"], c["atualizada_em"], ids,
                                 versao_areas if c["metrica"] == "efetividade" else None)
                        if chave not in recorte.memo:
                            try:
                                a = self._andamento(cur, c, ids, areas)
                            except SemDados as e:  # só esta campanha fica sem números (ex.: faltam os pedidos)
                                avisos[c["id"]] = str(e)
                                continue
                            if len(recorte.memo) > MAX_MEMO:
                                recorte.memo.clear()
                            recorte.memo[chave] = {**a["total"], "unidade": a["unidade"]}
                        totais[c["id"]] = recorte.memo[chave]
                finally:
                    cur.close()
            except SemDados as e:
                aviso = str(e)
        saida = []
        for c in campanhas:
            saida.append({**publica(c), "sugestao": sugestao(c, hoje), "resumo": totais.get(c["id"]),
                          "aviso": avisos.get(c["id"]), "minha": c["criada_por"] == usuario["id"]})
        return {"campanhas": saida, "aviso": aviso, "data_ref": self.calc.cache.info.get("data_ref"),
                "hoje": hoje.isoformat()}

    def obter(self, usuario: dict, id_, escopo, abrir: str | None = "padrao") -> dict:
        """A campanha com o andamento por vendedor (sem os dados de vendas: o andamento vem vazio, com o aviso).
        abrir: area, segmento ou produto ("padrao" = a abertura que o tipo mostra de saída)."""
        with self.banco.conexao() as con:
            c = self._uma(con, usuario, id_)
        aviso, a = None, None
        try:
            cur = self._cursor()
            try:
                a = self._andamento(cur, c, self.ids(escopo), abrir=abrir or None)
            finally:
                cur.close()
        except SemDados as e:
            aviso = str(e)
        return {"campanha": {**publica(c), "sugestao": sugestao(c, dt.date.today()),
                             "minha": c["criada_por"] == usuario["id"]},
                "andamento": a, "aviso": aviso}

    def criadas_por_rascunho(self, usuario: dict, rascunhos: list[str]) -> dict[str, dict]:
        """{uuid do rascunho: {id, nome}} dos rascunhos do Assistente que já viraram campanha desta pessoa."""
        uuids = [u for u in (id_valido(r) for r in rascunhos) if u]
        if not uuids:
            return {}
        with self.banco.conexao() as con:
            return {str(r): {"id": i, "nome": n} for r, i, n in con.execute(
                "SELECT rascunho, id, nome FROM campanhas WHERE rascunho = ANY(%s::uuid[]) AND criada_por = %s",
                [uuids, usuario["id"]])}

    # --- gravação ----------------------------------------------------------------------------
    def _validar(self, dados: dict, escopo) -> dict:
        cur = self._cursor()
        try:
            return validar(dados, cur, self.calc.regras(), self.ids(escopo), self._data_ref(), self._inicio_dados())
        finally:
            cur.close()

    @staticmethod
    def _gravar_detalhes(con, id_: int, d: dict) -> None:
        con.execute("DELETE FROM campanha_vendedores WHERE campanha = %s", [id_])
        con.execute("DELETE FROM campanha_produtos WHERE campanha = %s", [id_])
        with con.cursor() as cur:
            cur.executemany("INSERT INTO campanha_vendedores (campanha, id_vendedor, meta) VALUES (%s, %s, %s)",
                            [[id_, v["id"], v["meta"]] for v in d["vendedores"]])
            if d["metas_produto"]:
                cur.executemany("INSERT INTO campanha_produtos (campanha, id_produto, meta) VALUES (%s, %s, %s)",
                                [[id_, p["id"], p["meta"]] for p in d["metas_produto"]])

    def criar(self, usuario: dict, dados: dict, escopo, rascunho=None) -> dict:
        """Cria a campanha na coluna das datas, no topo. rascunho: o uuid do rascunho do Assistente; a mesma
        pessoa criando de novo o mesmo rascunho recebe a campanha que já existe."""
        if rascunho not in (None, "") and not id_valido(rascunho):
            raise ValueError("rascunho inválido")
        rascunho = id_valido(rascunho) if rascunho else None
        d = self._validar(dados, escopo)
        st = status_inicial(d["inicio"], d["fim"], dt.date.today())
        with self.banco.conexao() as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA_QUADRO])
            if rascunho:
                ja = con.execute("SELECT id, criada_por FROM campanhas WHERE rascunho = %s", [rascunho]).fetchone()
                if ja:
                    if ja[1] != usuario["id"]:
                        raise ValueError("este rascunho já virou campanha de outra pessoa")
                    return {"id": ja[0], "ja_existia": True}
            ordem = con.execute("SELECT COALESCE(MIN(ordem), 1) - 1 FROM campanhas WHERE status = %s", [st]).fetchone()[0]
            id_ = con.execute(
                "INSERT INTO campanhas (nome, descricao, premiacao, status, ordem, inicio, fim, metrica, parametros, "
                "filtros, meta_padrao, rascunho, criada_por, criada_por_nome, atualizada_por_nome) VALUES (%s, %s, %s, "
                "%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, (SELECT id FROM usuarios WHERE id = %s), %s, %s) "
                "RETURNING id",
                [d["nome"], d["descricao"], d["premiacao"], st, ordem, d["inicio"], d["fim"], d["metrica"],
                 json.dumps(d["parametros"], ensure_ascii=False), json.dumps(d["filtros"], ensure_ascii=False),
                 d["meta_padrao"], rascunho, usuario["id"], usuario["nome"], usuario["nome"]]).fetchone()[0]
            self._gravar_detalhes(con, id_, d)
        return {"id": id_, "ja_existia": False}

    def atualizar(self, usuario: dict, id_, dados: dict, escopo) -> None:
        """Muda os dados da campanha (o status e a posição no quadro ficam como estão)."""
        d = self._validar(dados, escopo)
        with self.banco.conexao() as con:
            c = self._uma(con, usuario, id_, travar=True)
            con.execute(
                "UPDATE campanhas SET nome = %s, descricao = %s, premiacao = %s, inicio = %s, fim = %s, metrica = %s, "
                "parametros = %s::jsonb, filtros = %s::jsonb, meta_padrao = %s, atualizada_em = now(), "
                "atualizada_por_nome = %s WHERE id = %s",
                [d["nome"], d["descricao"], d["premiacao"], d["inicio"], d["fim"], d["metrica"],
                 json.dumps(d["parametros"], ensure_ascii=False), json.dumps(d["filtros"], ensure_ascii=False),
                 d["meta_padrao"], usuario["nome"], c["id"]])
            self._gravar_detalhes(con, c["id"], d)

    def mover(self, usuario: dict, id_, novo_status: str, antes_de=None) -> None:
        """Põe o card na coluna, antes do card antes_de (sem ele, no fim). A ordem vale para o quadro todo: cada
        pessoa vê só uma parte, e a ordem relativa dos cards dela continua a mesma."""
        if novo_status not in STATUS:
            raise ValueError(f"coluna desconhecida: {novo_status!r}")
        with self.banco.conexao() as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA_QUADRO])
            c = self._uma(con, usuario, id_, travar=True)
            ordem = [r[0] for r in con.execute("SELECT id FROM campanhas WHERE status = %s AND id <> %s ORDER BY ordem, id",
                                               [novo_status, c["id"]])]
            try:
                pos = ordem.index(int(antes_de)) if antes_de not in (None, "") else len(ordem)
            except ValueError:
                pos = len(ordem)
            ordem.insert(pos, c["id"])
            if novo_status != c["status"]:
                con.execute("UPDATE campanhas SET status = %s, atualizada_em = now(), atualizada_por_nome = %s "
                            "WHERE id = %s", [novo_status, usuario["nome"], c["id"]])
            con.execute("UPDATE campanhas c SET ordem = v.n FROM unnest(%s::bigint[]) WITH ORDINALITY AS v(id, n) "
                        "WHERE c.id = v.id AND c.ordem IS DISTINCT FROM v.n", [ordem])

    def arquivar(self, usuario: dict, id_, arquivada: bool = True) -> None:
        with self.banco.conexao() as con:
            c = self._uma(con, usuario, id_, travar=True)
            con.execute("UPDATE campanhas SET arquivada = %s, atualizada_em = now(), atualizada_por_nome = %s "
                        "WHERE id = %s", [bool(arquivada), usuario["nome"], c["id"]])

    def excluir(self, usuario: dict, id_) -> None:
        with self.banco.conexao() as con:
            c = self._uma(con, usuario, id_, travar=True)
            con.execute("DELETE FROM campanhas WHERE id = %s", [c["id"]])

    # --- dias de atendimento das áreas (Gestão › Configurar) ---------------------------------
    def _areas_do_cache(self) -> dict[int, dict]:
        """Áreas comerciais dos clientes, com os ativos que contam nas visitas e os vendedores das carteiras."""
        cur = self._cursor()
        try:
            return {a: {"nome": n, "clientes": int(t), "ativos": int(at), "vendedores": [x for x in (vs or []) if x][:4]}
                    for a, n, t, at, vs in cur.execute(
                        "SELECT id_area, any_value(area), COUNT(*), COUNT(*) FILTER (WHERE NOT COALESCE(inativo, false) "
                        "AND NOT contains(upper(COALESCE(cliente, '')), 'PEDIDO BLOQUEADO')), "
                        "list(DISTINCT vendedor_carteira ORDER BY vendedor_carteira) FILTER (WHERE NOT COALESCE(inativo, false)) "
                        "FROM clientes WHERE id_area IS NOT NULL GROUP BY 1").fetchall()}
        finally:
            cur.close()

    def config_areas(self) -> dict:
        """As áreas para a configuração: as do cache e as da tabela, com os dias (None = pendente) e a sugestão
        tirada do nome."""
        aviso = None
        try:
            cache = self._areas_do_cache()
        except SemDados as e:
            cache, aviso = {}, str(e)
        with self.banco.conexao() as con:
            tabela = {a: (n, list(d), hora(t), q) for a, n, d, t, q in con.execute(
                "SELECT id_area, nome, dias, atualizada_em, atualizada_por_nome FROM areas_atendimento")}
        areas = []
        for a in sorted(set(cache) | set(tabela)):
            info = cache.get(a, {"nome": "", "clientes": 0, "ativos": 0, "vendedores": []})
            nome_t, dias, quando, quem = tabela.get(a, ("", None, None, None))
            nome = info["nome"] or nome_t or f"Área {a}"
            areas.append({"id": a, "nome": nome, "dias": dias, "sugestao": dias_do_nome(nome),
                          "clientes": info["clientes"], "ativos": info["ativos"], "vendedores": info["vendedores"],
                          "atualizada_em": quando, "atualizada_por_nome": quem})
        areas.sort(key=lambda x: _chave(x["nome"]))
        return {"areas": areas, "aviso_areas": aviso}

    def definir_areas(self, usuario: dict, mudancas: dict, con=None) -> None:
        """{id_area: [dias ISO] | None}: None volta a área para pendente; [] marca como não atendida. Confere tudo
        antes de gravar."""
        if not isinstance(mudancas, dict):
            raise ValueError("areas deve ser um objeto {código da área: dias}")
        novos = {}
        for k, dias in mudancas.items():
            try:
                id_area = int(k)
            except (TypeError, ValueError):
                raise ValueError(f"código de área inválido: {k!r}") from None
            if dias is None:
                novos[id_area] = None
                continue
            try:
                lista = sorted({int(d) for d in _lista(dias, "dias")})
            except (TypeError, ValueError):
                raise ValueError(f"dias da área {id_area}: use números de 1 (segunda) a 7 (domingo)") from None
            if any(not 1 <= d <= 7 for d in lista):
                raise ValueError(f"dias da área {id_area}: use números de 1 (segunda) a 7 (domingo)")
            novos[id_area] = lista
        if not novos:
            return
        try:
            nomes = {a: x["nome"] for a, x in self._areas_do_cache().items()}
        except SemDados:
            nomes = {}
        with (contextlib.nullcontext(con) if con is not None else self.banco.conexao()) as c:
            for id_area, dias in novos.items():
                if dias is None:
                    c.execute("DELETE FROM areas_atendimento WHERE id_area = %s", [id_area])
                else:
                    c.execute(
                        "INSERT INTO areas_atendimento (id_area, nome, dias, atualizada_por_nome) VALUES (%s, %s, "
                        "%s::smallint[], %s) ON CONFLICT (id_area) DO UPDATE SET dias = EXCLUDED.dias, "
                        "nome = CASE WHEN EXCLUDED.nome <> '' THEN EXCLUDED.nome ELSE areas_atendimento.nome END, "
                        "atualizada_em = now(), atualizada_por_nome = EXCLUDED.atualizada_por_nome",
                        [id_area, nomes.get(id_area) or "", dias, usuario["nome"]])

    # --- Assistente --------------------------------------------------------------------------
    def contexto(self, usuario: dict, escopo) -> "ContextoGestao":
        return ContextoGestao(self, usuario, escopo)


def tipos() -> list[dict]:
    """Os tipos de campanha e os blocos da Personalizada, para o formulário."""
    return [{
        "id": t, "nome": n,
        **({"descricao": descritor(t, normalizar(t)[1])["descricao"]} if t != "personalizada" else
           {"descricao": "monte o indicador: o que medir e como"}),
    } for t, n in TIPOS.items()] + [{
        "id": "_blocos", "medidas": [{"id": k, "nome": v, "formas": list(COMBINACOES[k])} for k, v in MEDIDAS.items()],
        "formas": FORMAS, "comparar": COMPARAR, "bases": BASES, "aberturas": ABERTURAS,
    }]


class ContextoGestao:
    """O que as ferramentas de campanha do Assistente podem fazer, já com quem pergunta e o acesso dela na Gestão."""

    def __init__(self, gestao: Gestao, usuario: dict, escopo):
        self.gestao, self.usuario, self.escopo = gestao, usuario, escopo

    def listar(self, texto: str = "", incluir_arquivadas: bool = False) -> list[dict]:
        """Campanhas de quem pergunta (o administrador: todas), da mais nova para a mais antiga."""
        admin = self.usuario["papel"] == "admin"
        onde, params = ("TRUE", []) if admin else ("c.criada_por = %s", [self.usuario["id"]])
        if not incluir_arquivadas:
            onde += " AND NOT c.arquivada"
        with self.gestao.banco.conexao() as con:
            campanhas = self.gestao._ler(con, onde, params)
        palavras = _chave(texto).split()
        if palavras:
            campanhas = [c for c in campanhas if all(p in _chave(f"{c['nome']} {c['descricao']} {c['id']}") for p in palavras)]
        campanhas.sort(key=lambda c: c["criada_em"], reverse=True)
        return [{"id": c["id"], "nome": c["nome"], "status": STATUS[c["status"]], "inicio": c["inicio"].isoformat(),
                 "fim": c["fim"].isoformat(), "metrica": descritor(c["metrica"], c["parametros"])["nome"],
                 "meta_padrao": c["meta_padrao"], "vendedores": len(c["vendedores"]), "criada_por": c["criada_por_nome"],
                 "criada_em": c["criada_em"][:10], "arquivada": c["arquivada"],
                 **({"do_rascunho": c["rascunho"]} if c["rascunho"] else {}),
                 **({"minha": c["criada_por"] == self.usuario["id"]} if admin else {})} for c in campanhas[:30]]

    def andamento(self, id_) -> dict:
        r = self.gestao.obter(self.usuario, id_, self.escopo)
        if r["andamento"] is None:
            raise SemDados(r["aviso"] or "sem dados de vendas")
        c, a = r["campanha"], r["andamento"]
        ind = a["indicador"]
        campos = ("id", "nome", "equipe", "realizado", "meta", "pct", "status", "projecao", "falta", "falta_por_dia",
                  "numerador", "denominador", "base")
        saida = {
            "campanha": {k: c[k] for k in ("id", "nome", "status", "inicio", "fim", "metrica", "parametros", "filtros",
                                           "meta_padrao", "premiacao")},
            "indicador": {k: ind[k] for k in ("nome", "descricao", "formato", "sufixo", "comportamento", "meta_em_pct",
                                              "numerador", "denominador", "base_texto") if ind.get(k)},
            "status_da_campanha": STATUS[c["status"]], "unidade": a["unidade"], "dados_ate": a["data_ref"],
            "situacao_do_periodo": a["situacao"],
            "dias_uteis": {k: {x: v[x] for x in ("dias_uteis", "dias_decorridos", "dias_restantes", "ritmo")}
                           for k, v in a["calendarios"].items()},
            "total": a["total"],
            "vendedores": [{k: r[k] for k in campos if r.get(k) is not None} for r in a["vendedores"]],
            **({"fora_do_acesso": a["ocultos"]} if a["ocultos"] else {}),
            **({"avisos": a["avisos"]} if a.get("avisos") else {}),
            **({"periodo_de_comparacao": a["periodo_base"]} if a.get("periodo_base") else {}),
        }
        if ind["formato"] == "pct":
            saida["leitura"] = "realizado, meta e pct de efetividade/índice estão em fração (0,8 = 80%)"
        if a.get("produtos"):
            saida["produtos"] = [{k: p[k] for k in ("id", "nome", "unidade", "meta", "preco", "pct", "quantidade")}
                                 for p in a["produtos"]]
        if a.get("abertura"):
            ab = a["abertura"]
            saida["abertura"] = {"por": ab["rotulo"], "linhas": ab["linhas"][:20], "mais": ab["mais"] + max(0, len(ab["linhas"]) - 20)}
        return saida

    def propor(self, dados: dict, equipes: list[str]) -> dict:
        """Confere um rascunho e devolve com os nomes; não grava (a pessoa cria pelo botão)."""
        dados = dict(dados)
        equipes = [str(e).strip().upper() for e in equipes or []]
        if any(e not in EQUIPES for e in equipes):
            raise ValueError(f"equipe deve ser {', '.join(EQUIPES)}")
        if equipes:  # "todos de BA": os vendedores da equipe com venda nos últimos 12 meses, dentro do acesso
            ids = self.gestao.ids(self.escopo)
            da_equipe = [v["id"] for v in self.gestao.assistente.catalogo_vendedores()
                         if v["equipe"] in equipes and not v["inativo"] and (ids is None or v["id"] in ids)]
            if not da_equipe:
                raise ValueError("nenhum vendedor dessas equipes no acesso de quem pergunta")
            ja = {int(v["id"]) if isinstance(v, dict) else int(v) for v in dados.get("vendedores") or []}
            dados["vendedores"] = [*(dados.get("vendedores") or []), *(v for v in da_equipe if v not in ja)]
        d = self.gestao._validar(dados, self.escopo)
        cur = self.gestao._cursor()
        try:
            ids_v = [v["id"] for v in d["vendedores"]]
            nomes_v = dict(cur.execute(f"SELECT id_vendedor, vendedor FROM vendedores WHERE id_vendedor IN "
                                       f"({_marcas(ids_v)})", ids_v).fetchall())
            prods = list(dict.fromkeys([*(d["filtros"].get("produtos") or []), *(p["id"] for p in d["metas_produto"])]))
            nomes_p = dict(cur.execute(f"SELECT id_produto, produto FROM produtos WHERE id_produto IN ({_marcas(prods)})",
                                       prods).fetchall()) if prods else {}
            unidade = ""
            if d["parametros"].get("medida") == "volume":
                unidade = (unidades(cur, d["filtros"], self.gestao._data_ref()) or [""])[0]
        finally:
            cur.close()
        ind = descritor(d["metrica"], d["parametros"], unidade)
        return {
            "id": novo_id(), **publica(d), "indicador": ind, "unidade": unidade, "nome_metrica": ind["nome"],
            "nomes": {"vendedores": {str(k): v for k, v in nomes_v.items()}, "produtos": {str(k): v for k, v in nomes_p.items()}},
        }

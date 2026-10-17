"""Página Gestão: campanhas de vendas num quadro (kanban), com o andamento de cada vendedor.

- Campanha: nome, período, métrica (faturamento, volume, positivação ou mix), filtros de produto e de cliente,
  vendedores participantes e metas (uma padrão, com ajuste por vendedor). Fica no PostgreSQL
  (bi/migracoes/007_gestao.sql); o status (coluna do quadro) muda só quando alguém arrasta o card, e o quadro
  sugere a mudança quando as datas dizem que ela já devia ter acontecido.
- Quem vê: cada pessoa vê e mexe só nas campanhas que criou; o administrador vê as dele e, pedindo, as de todos (e
  mexe em qualquer uma). Os vendedores que a pessoa pode pôr numa campanha, e que vê no andamento, são os do acesso
  dela na página (Gestão › Configurar, como em Projeções e no Assistente).
- Andamento: calculado na hora no recorte com todos os vendedores do Assistente (bi/assistente.py, view
  faturamento: as mesmas regras das metas), filtrando os vendedores no SQL. O ritmo esperado vem dos dias úteis da
  região de cada vendedor (bi/calendario.py) no período da campanha, e o status segue bi/metas.py.
- O Assistente usa as mesmas funções (ContextoGestao): propor_campanha confere um rascunho sem gravar (quem cria é a
  pessoa, no botão), e andamento_campanha dá os números da página.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from .calendario import Calendario
from .configuracao import Regras
from .conversas import NaoEncontrada, id_valido, novo_id
from .metas import indicador, status
from .projecoes import NOME_EQUIPE, Projetor

STATUS = {"planejada": "Planejada", "andamento": "Em andamento", "concluida": "Concluída"}
METRICAS = {
    "faturamento": {"nome": "Faturamento", "unidade": "R$", "expr": "SUM(valor_liquido)",
                    "descricao": "venda líquida (descontando as devoluções), em R$, como nas metas"},
    "volume": {"nome": "Volume", "unidade": None, "expr": "SUM(quantidade)",
               "descricao": "quantidade vendida, na unidade dos produtos (descontando as devoluções)"},
    "positivacao": {"nome": "Positivação", "unidade": "clientes",
                    "expr": "COUNT(DISTINCT id_cliente) FILTER (WHERE tipo = 'venda' AND tipo_cliente = 'CLIENTE')",
                    "descricao": "clientes distintos com venda no período"},
    "mix": {"nome": "Mix", "unidade": "produtos", "expr": "COUNT(DISTINCT id_produto) FILTER (WHERE tipo = 'venda')",
            "descricao": "produtos distintos vendidos no período"},
}
DISTINTAS = ("positivacao", "mix")  # o total da campanha não é a soma dos vendedores
# Filtro -> coluna da view faturamento (e da tabela produtos, nos filtros de produto).
FILTROS = {"produtos": "id_produto", "linhas": "linha", "categorias": "categoria", "grupos": "grupo",
           "ufs": "uf", "segmentos": "segmento"}
FILTROS_PRODUTO = ("produtos", "linhas", "categorias", "grupos")
GRUPOS = ("mussarela", "outras")
EQUIPES = ("ES", "BA", "EDIR")
MAX_NOME = 120
MAX_TEXTO = 2000
MAX_DIAS = 366
TRAVA_QUADRO = 7_240_103  # pg_advisory_xact_lock: duas pessoas arrastando cards não embaralham a ordem
_CAMPOS = ("c.id, c.nome, c.descricao, c.premiacao, c.status, c.ordem, c.inicio, c.fim, c.metrica, c.filtros, "
           "c.meta_padrao, c.arquivada, c.rascunho, c.criada_em, c.criada_por, c.criada_por_nome, c.atualizada_em, "
           "c.atualizada_por_nome")


class SemDados(RuntimeError):
    """Os dados de vendas ainda não estão prontos (o servidor responde 503)."""


def _marcas(valores) -> str:
    return ",".join("?" * len(valores))


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


def _redondo(v):
    if isinstance(v, float):
        return round(v, 2) if abs(v) >= 100 else round(v, 4)
    return v


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


def _filtros(bruto: dict, cur, regras: Regras) -> dict:
    """Confere os filtros e devolve só os preenchidos, com os valores como estão nos dados."""
    if not isinstance(bruto, dict):
        raise ValueError("filtros inválidos")
    desconhecidos = set(bruto) - set(FILTROS)
    if desconhecidos:
        raise ValueError(f"filtro desconhecido: {', '.join(sorted(desconhecidos))}")
    saida = {}
    produtos = []
    for p in _lista(bruto.get("produtos"), "produtos"):
        try:
            produtos.append(regras.produto(int(p)))  # as vendas já vêm com o produto equivalente
        except (TypeError, ValueError):
            raise ValueError(f"código de produto inválido: {p!r}") from None
    if produtos:
        produtos = list(dict.fromkeys(produtos))
        achados = dict(cur.execute(f"SELECT id_produto, grupo FROM produtos WHERE id_produto IN ({_marcas(produtos)})",
                                   produtos).fetchall())
        faltam = [str(p) for p in produtos if p not in achados]
        if faltam:
            raise ValueError(f"produto não encontrado: {', '.join(faltam)}")
        fora = [str(p) for p in produtos if achados[p] == "fora"]
        if fora:
            raise ValueError(f"produto marcado como \"não conta\" nas regras das metas: {', '.join(fora)}")
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


def _onde(filtros: dict, chaves=tuple(FILTROS), prefixo: str = "") -> tuple[list[str], list]:
    onde, params = [], []
    for chave in chaves:
        valores = filtros.get(chave)
        if valores:
            onde.append(f"{prefixo}{FILTROS[chave]} IN ({_marcas(valores)})")
            params += list(valores)
    return onde, params


def unidades(cur, filtros: dict, data_ref: dt.date) -> list[str]:
    """Unidades dos produtos que os filtros pegam (os escolhidos e os vendidos nos últimos 12 meses)."""
    onde, params = _onde(filtros, FILTROS_PRODUTO, "p.")
    escolhidos = filtros.get("produtos") or [-1]
    onde.append(f"(p.id_produto IN ({_marcas(escolhidos)}) OR p.id_produto IN "
                f"(SELECT DISTINCT id_produto FROM _vendas WHERE data > ?))")
    params += [*escolhidos, data_ref - dt.timedelta(days=365)]
    sql = (f"SELECT DISTINCT upper(trim(COALESCE(p.unidade, ''))) FROM produtos p "
           f"WHERE p.grupo <> 'fora' AND {' AND '.join(onde)} ORDER BY 1")
    return [u for (u,) in cur.execute(sql, params).fetchall()]


def validar(dados: dict, cur, regras: Regras, permitidos: frozenset[int] | None, data_ref: dt.date) -> dict:
    """Confere uma campanha vinda da página ou do Assistente e devolve os dados normalizados. cur: cursor do recorte
    com todos os vendedores. Levanta ValueError com a explicação (a IA lê e corrige)."""
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
    metrica = str(dados.get("metrica") or "").strip().lower()
    if metrica not in METRICAS:
        raise ValueError(f"métrica desconhecida: {metrica!r} (use {', '.join(METRICAS)})")
    filtros = _filtros(dados.get("filtros") or {}, cur, regras)
    if metrica == "volume":
        if not any(filtros.get(k) for k in FILTROS_PRODUTO):
            raise ValueError("campanha de volume precisa de um filtro de produto (produtos, linhas, categorias ou "
                             "grupo), para somar quantidades da mesma unidade")
        achadas = unidades(cur, filtros, data_ref)
        if len(achadas) > 1:
            raise ValueError(f"os produtos escolhidos têm unidades diferentes ({', '.join(u or 'sem unidade' for u in achadas)}); "
                             "numa campanha de volume use produtos da mesma unidade")
    meta_padrao = _numero(dados.get("meta_padrao"), "a meta padrão")

    vendedores: dict[int, float | None] = {}
    for v in _lista(dados.get("vendedores"), "vendedores"):
        bruto = v if isinstance(v, dict) else {"id": v}
        try:
            vid = int(bruto.get("id"))
        except (TypeError, ValueError):
            raise ValueError(f"código de vendedor inválido: {bruto.get('id')!r}") from None
        meta = bruto.get("meta")
        vendedores[vid] = None if meta in (None, "") else _numero(meta, f"a meta do vendedor {vid}")
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
        "metrica": metrica, "filtros": filtros, "meta_padrao": meta_padrao,
        "vendedores": [{"id": v, "meta": vendedores[v]} for v in ids],
    }


# --- andamento --------------------------------------------------------------------------------
def calendario_periodo(cal: Calendario, inicio: dt.date, fim: dt.date, regiao: str, data_ref: dt.date) -> dict:
    """Dias úteis da campanha na região, quantos já passaram até data_ref e o ritmo esperado (como
    Calendario.resumo, mas no período da campanha)."""
    total = decorridos = 0.0
    d = inicio
    while d <= fim:
        peso = cal.dia(d, regiao)["peso"]
        total += peso
        if d <= data_ref:
            decorridos += peso
        d += dt.timedelta(days=1)
    situacao = "fechado" if data_ref >= fim else ("futuro" if data_ref < inicio else "aberto")
    ritmo = decorridos / total if total else (1.0 if situacao == "fechado" else 0.0)
    return {"regiao": regiao, "dias_uteis": total, "dias_decorridos": decorridos, "dias_restantes": total - decorridos,
            "ritmo": ritmo, "situacao": situacao}


def andamento(cur, campanha: dict, regras: Regras, cal: Calendario, data_ref: dt.date,
              permitidos: frozenset[int] | None) -> dict:
    """Realizado, meta, % e situação de cada vendedor da campanha (só os do acesso de quem vê) e o total."""
    inicio, fim, metrica = campanha["inicio"], campanha["fim"], campanha["metrica"]
    participantes = campanha["vendedores"]
    visiveis = [p for p in participantes if permitidos is None or p["id"] in permitidos]
    ate = min(fim, data_ref)
    ids = [p["id"] for p in visiveis]
    expr = METRICAS[metrica]["expr"]
    realizado, distintos, unidade = {}, None, METRICAS[metrica]["unidade"]
    if ids and ate >= inicio:
        onde, params = _onde(campanha["filtros"])
        onde = ["data BETWEEN ? AND ?", f"id_vendedor IN ({_marcas(ids)})", *onde]
        params = [inicio, ate, *ids, *params]
        where = " AND ".join(onde)
        realizado = {v: float(x or 0) for v, x in
                     cur.execute(f"SELECT id_vendedor, {expr} FROM faturamento WHERE {where} GROUP BY 1", params).fetchall()}
        if metrica in DISTINTAS:
            distintos = int(cur.execute(f"SELECT {expr} FROM faturamento WHERE {where}", params).fetchone()[0] or 0)
    if metrica == "volume":
        achadas = unidades(cur, campanha["filtros"], data_ref)
        unidade = achadas[0] if len(achadas) == 1 else ("" if not achadas else "/".join(achadas))
    info = {}
    if ids:
        info = {v: (n, e) for v, n, e in cur.execute(
            f"SELECT id_vendedor, vendedor, equipe FROM vendedores WHERE id_vendedor IN ({_marcas(ids)})", ids).fetchall()}
    calendarios: dict[str, dict] = {}
    linhas = []
    for p in visiveis:
        vid = p["id"]
        grupo = regras.grupo_vendedor(vid)
        regiao = Projetor._regiao(regras, vid, grupo)
        c = calendarios.get(regiao) or calendarios.setdefault(regiao, calendario_periodo(cal, inicio, fim, regiao, data_ref))
        meta = campanha["meta_padrao"] if p["meta"] is None else p["meta"]
        ind = indicador(realizado.get(vid, 0.0), meta, c)
        nome, equipe = info.get(vid, (f"Vendedor {vid}", NOME_EQUIPE.get(grupo, grupo)))
        linhas.append({"id": vid, "nome": nome, "equipe": equipe, "regiao": regiao, "meta_individual": p["meta"] is not None,
                       **{k: _redondo(v) for k, v in ind.items()}})
    linhas.sort(key=lambda r: (r["pct"] is None, -(r["pct"] or 0), -r["realizado"], r["nome"]))
    com_meta = [r for r in linhas if r["meta"]]
    meta_total = sum(r["meta"] for r in com_meta)
    real_meta = sum(r["realizado"] for r in com_meta)
    ritmo = (sum(r["meta"] * calendarios[r["regiao"]]["ritmo"] for r in com_meta) / meta_total) if meta_total else 0.0
    situacao = next(iter(calendarios.values()))["situacao"] if calendarios else (
        "fechado" if data_ref >= fim else ("futuro" if data_ref < inicio else "aberto"))
    total = {
        "realizado": _redondo(sum(r["realizado"] for r in linhas)), "meta": _redondo(meta_total),
        "pct": real_meta / meta_total if meta_total else None, "status": status(real_meta, meta_total, ritmo, situacao),
        "esperado": _redondo(meta_total * (1.0 if situacao == "fechado" else ritmo)) if meta_total else None,
        "bateram": sum(1 for r in com_meta if r["realizado"] >= r["meta"]), "com_meta": len(com_meta),
        "vendedores": len(linhas), **({"distintos": distintos} if metrica in DISTINTAS else {}),
    }
    return {
        "metrica": metrica, "nome_metrica": METRICAS[metrica]["nome"], "unidade": unidade,
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat(), "ate": ate.isoformat() if ate >= inicio else None},
        "data_ref": data_ref.isoformat(), "situacao": situacao,
        "calendarios": {k: {**v, "ritmo": round(v["ritmo"], 4)} for k, v in calendarios.items()},
        "total": total, "vendedores": linhas, "ocultos": len(participantes) - len(visiveis),
    }


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


def _campanha(linha, vendedores: list[dict]) -> dict:
    (id_, nome, descricao, premiacao, st, ordem, inicio, fim, metrica, filtros, meta_padrao, arquivada, rascunho,
     criada_em, criada_por, criada_por_nome, atualizada_em, atualizada_por_nome) = linha
    return {
        "id": id_, "nome": nome, "descricao": descricao, "premiacao": premiacao, "status": st, "ordem": ordem,
        "inicio": inicio, "fim": fim, "metrica": metrica, "filtros": filtros or {}, "meta_padrao": float(meta_padrao),
        "arquivada": arquivada, "rascunho": str(rascunho) if rascunho else None,
        "criada_em": criada_em.isoformat(timespec="seconds"), "criada_por": criada_por, "criada_por_nome": criada_por_nome,
        "atualizada_em": atualizada_em.isoformat(timespec="seconds"), "atualizada_por_nome": atualizada_por_nome,
        "vendedores": vendedores,
    }


def publica(c: dict) -> dict:
    """A campanha como a página e a IA recebem (datas em texto)."""
    return {**c, "inicio": c["inicio"].isoformat(), "fim": c["fim"].isoformat()}


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

    def _cursor(self):
        self._conferir_dados()
        return self.assistente.recorte(None).cursor()

    def _data_ref(self) -> dt.date:
        return self.calc.cache.data_ref() or dt.date.today()

    def ids(self, escopo) -> frozenset[int] | None:
        """escopo: (vendedores, equipes) de bi/acesso.py escopo_gestao -> os ids (None = todos)."""
        vendedores, equipes = escopo
        if vendedores is None and equipes is None:
            return None
        self._conferir_dados()
        return self.assistente.ids_do_escopo(vendedores, equipes)

    def catalogo(self, escopo) -> dict:
        """O que o formulário oferece: vendedores do acesso (com venda nos últimos 12 meses), produtos vendidos nos
        últimos 12 meses (sem os "não conta"), linhas, categorias, UFs e segmentos."""
        cur = self._cursor()
        try:
            ids = self.ids(escopo)
            vendedores = [v for v in self.assistente.catalogo_vendedores() if ids is None or v["id"] in ids]
            desde = self._data_ref() - dt.timedelta(days=365)
            produtos = [{"id": p, "nome": n, "unidade": (u or "").strip().upper(), "linha": li, "grupo": g,
                         "categoria": c, "venda_12m": round(v or 0, 2)} for p, n, u, li, g, c, v in cur.execute(
                "WITH v AS (SELECT id_produto, SUM(valor) AS venda FROM _vendas WHERE data > ? GROUP BY 1) "
                "SELECT p.id_produto, p.produto, p.unidade, p.linha, p.grupo, p.categoria, v.venda FROM produtos p "
                "JOIN v USING (id_produto) WHERE p.grupo <> 'fora' ORDER BY v.venda DESC", [desde]).fetchall()]
            linhas = sorted({p["linha"] for p in produtos if p["linha"]})
            clientes = cur.execute("SELECT DISTINCT uf, segmento FROM clientes WHERE ultima_compra > ?", [desde]).fetchall()
        finally:
            cur.close()
        regras = self.calc.regras()
        equipes = [{"id": e, "nome": NOME_EQUIPE[e]} for e in (*EQUIPES, "OCULTO") if any(v["equipe"] == e for v in vendedores)]
        return {
            "vendedores": vendedores, "equipes": equipes, "produtos": produtos, "linhas": linhas,
            "categorias": regras.categorias, "grupos": list(GRUPOS),
            "ufs": sorted({u for u, _ in clientes if u}), "segmentos": sorted({s for _, s in clientes if s}),
            "metricas": [{"id": k, "nome": v["nome"], "descricao": v["descricao"]} for k, v in METRICAS.items()],
        }

    def _andamento(self, cur, campanha: dict, ids) -> dict:
        regras = self.calc.regras()
        return andamento(cur, campanha, regras, self.calc.calendario(regras), self._data_ref(), ids)

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
        vendedores = defaultdict(list)
        if linhas:
            for camp, vid, meta in con.execute(
                    "SELECT campanha, id_vendedor, meta FROM campanha_vendedores WHERE campanha = ANY(%s) "
                    "ORDER BY campanha, id_vendedor", [[ln[0] for ln in linhas]]):
                vendedores[camp].append({"id": vid, "meta": None if meta is None else float(meta)})
        return [_campanha(ln, vendedores[ln[0]]) for ln in linhas]

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
        """As campanhas do quadro. As que já começaram trazem o total do andamento (para a barra do card)."""
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
        totais = {}
        if ativas:
            try:
                cur = self._cursor()
                try:
                    ids = self.ids(escopo)
                    for c in ativas:
                        a = self._andamento(cur, c, ids)
                        totais[c["id"]] = {**a["total"], "unidade": a["unidade"]}
                finally:
                    cur.close()
            except SemDados as e:
                aviso = str(e)
        saida = []
        for c in campanhas:
            saida.append({**publica(c), "sugestao": sugestao(c, hoje), "resumo": totais.get(c["id"]),
                          "minha": c["criada_por"] == usuario["id"]})
        return {"campanhas": saida, "aviso": aviso, "data_ref": self.calc.cache.info.get("data_ref"),
                "hoje": hoje.isoformat()}

    def obter(self, usuario: dict, id_, escopo) -> dict:
        """A campanha com o andamento por vendedor (sem os dados de vendas: o andamento vem vazio, com o aviso)."""
        with self.banco.conexao() as con:
            c = self._uma(con, usuario, id_)
        aviso, a = None, None
        try:
            cur = self._cursor()
            try:
                a = self._andamento(cur, c, self.ids(escopo))
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
            return validar(dados, cur, self.calc.regras(), self.ids(escopo), self._data_ref())
        finally:
            cur.close()

    @staticmethod
    def _gravar_vendedores(con, id_: int, vendedores: list[dict]) -> None:
        con.execute("DELETE FROM campanha_vendedores WHERE campanha = %s", [id_])
        with con.cursor() as cur:
            cur.executemany("INSERT INTO campanha_vendedores (campanha, id_vendedor, meta) VALUES (%s, %s, %s)",
                            [[id_, v["id"], v["meta"]] for v in vendedores])

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
                "INSERT INTO campanhas (nome, descricao, premiacao, status, ordem, inicio, fim, metrica, filtros, "
                "meta_padrao, rascunho, criada_por, criada_por_nome, atualizada_por_nome) VALUES (%s, %s, %s, %s, %s, "
                "%s, %s, %s, %s::jsonb, %s, %s, (SELECT id FROM usuarios WHERE id = %s), %s, %s) RETURNING id",
                [d["nome"], d["descricao"], d["premiacao"], st, ordem, d["inicio"], d["fim"], d["metrica"],
                 json.dumps(d["filtros"], ensure_ascii=False), d["meta_padrao"], rascunho, usuario["id"],
                 usuario["nome"], usuario["nome"]]).fetchone()[0]
            self._gravar_vendedores(con, id_, d["vendedores"])
        return {"id": id_, "ja_existia": False}

    def atualizar(self, usuario: dict, id_, dados: dict, escopo) -> None:
        """Muda os dados da campanha (o status e a posição no quadro ficam como estão)."""
        d = self._validar(dados, escopo)
        with self.banco.conexao() as con:
            c = self._uma(con, usuario, id_, travar=True)
            con.execute(
                "UPDATE campanhas SET nome = %s, descricao = %s, premiacao = %s, inicio = %s, fim = %s, metrica = %s, "
                "filtros = %s::jsonb, meta_padrao = %s, atualizada_em = now(), atualizada_por_nome = %s WHERE id = %s",
                [d["nome"], d["descricao"], d["premiacao"], d["inicio"], d["fim"], d["metrica"],
                 json.dumps(d["filtros"], ensure_ascii=False), d["meta_padrao"], usuario["nome"], c["id"]])
            self._gravar_vendedores(con, c["id"], d["vendedores"])

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

    # --- Assistente --------------------------------------------------------------------------
    def contexto(self, usuario: dict, escopo) -> "ContextoGestao":
        return ContextoGestao(self, usuario, escopo)


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
                 "fim": c["fim"].isoformat(), "metrica": c["metrica"], "meta_padrao": c["meta_padrao"],
                 "vendedores": len(c["vendedores"]), "criada_por": c["criada_por_nome"],
                 "criada_em": c["criada_em"][:10], "arquivada": c["arquivada"],
                 **({"do_rascunho": c["rascunho"]} if c["rascunho"] else {}),
                 **({"minha": c["criada_por"] == self.usuario["id"]} if admin else {})} for c in campanhas[:30]]

    def andamento(self, id_) -> dict:
        r = self.gestao.obter(self.usuario, id_, self.escopo)
        if r["andamento"] is None:
            raise SemDados(r["aviso"] or "sem dados de vendas")
        c, a = r["campanha"], r["andamento"]
        return {
            "campanha": {k: c[k] for k in ("id", "nome", "status", "inicio", "fim", "metrica", "filtros", "meta_padrao",
                                           "premiacao")},
            "status_da_campanha": STATUS[c["status"]], "unidade": a["unidade"], "dados_ate": a["data_ref"],
            "situacao_do_periodo": a["situacao"],
            "dias_uteis": {k: {x: _redondo(v[x]) for x in ("dias_uteis", "dias_decorridos", "dias_restantes", "ritmo")}
                           for k, v in a["calendarios"].items()},
            "total": a["total"],
            "vendedores": [{k: r[k] for k in ("id", "nome", "equipe", "realizado", "meta", "pct", "status", "projecao",
                                              "falta", "falta_por_dia") if r.get(k) is not None}
                           for r in a["vendedores"]],
            **({"fora_do_acesso": a["ocultos"]} if a["ocultos"] else {}),
        }

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
            prods = d["filtros"].get("produtos") or []
            nomes_p = dict(cur.execute(f"SELECT id_produto, produto FROM produtos WHERE id_produto IN ({_marcas(prods)})",
                                       prods).fetchall()) if prods else {}
            unidade = METRICAS[d["metrica"]]["unidade"]
            if d["metrica"] == "volume":
                unidade = (unidades(cur, d["filtros"], self.gestao._data_ref()) or [""])[0]
        finally:
            cur.close()
        return {
            "id": novo_id(), **publica(d), "unidade": unidade, "nome_metrica": METRICAS[d["metrica"]]["nome"],
            "nomes": {"vendedores": {str(k): v for k, v in nomes_v.items()}, "produtos": {str(k): v for k, v in nomes_p.items()}},
        }

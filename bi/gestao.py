"""Página Gestão ("Gestão da equipe"): campanhas por vendedor e objetivos de cada região, com o histórico interno de cada
vendedor.

- Campanha: o que o administrador lança para um ou mais vendedores de uma região (ES ou BA; o Edir é da BA): um dos
  indicadores de bi/indicadores.py (positivação, mix médio, efetividade, frequência, preço médio por produto ou uma
  Personalizada montada por blocos), um prazo e uma meta. A base de cada vendedor é o mesmo indicador medido inteiro
  no período fechado que o administrador escolhe (semana, quinzena, mês, trimestre, semestre ou ano: o último que
  termina antes do início, indicadores.janela_fechada); nas campanhas de antes da 012 (base_periodo vazio), num
  período do mesmo tamanho, logo antes do início (indicadores.janela_base). Fica gravada e só é refeita quando muda a
  janela ou o que a campanha mede. A meta de cada um: Número (alvo_tipo fixo, o valor a atingir) ou Percentual (pct,
  a base + X%); "base + N" (mais) só nas campanhas de antes. Enquanto a campanha corre, o resultado e as parciais de
  cada semana são calculados na hora; quando os dados passam do fim (ou o administrador encerra), o resultado de cada
  vendedor fica congelado. O quadro mostra o % da meta de cada vendedor nas campanhas em vigor e o da campanha
  (pct_da_campanha); a prévia da base (previa_base) mede a base dos vendedores para o formulário, sem gravar.
- Objetivo: um indicador da equipe da região num período, contra uma meta da equipe (o total, sem repetir clientes
  entre os vendedores).
- Histórico (tabela gestao_eventos): as observações do administrador e o que aconteceu em cada campanha do vendedor
  (lançada, editada, prorrogada, encerrada, resultado). As parciais e o resultado de uma campanha em vigor entram na hora.
- Quem mexe: só o administrador. Quem tem a página vê as campanhas, os objetivos e as observações dos vendedores do
  acesso dela (Gestão › Configurar, como em Projeções e no Assistente).
- Tudo fica no PostgreSQL (migrações 007, 008, 009 e 012). As contas usam o recorte com todos os vendedores do
  Assistente, filtrando os vendedores no SQL, e ficam guardadas no próprio recorte (refeito quando os dados, as regras
  ou as metas mudam). Base pendente e resultado vencido são gravados na leitura seguinte (cálculo preguiçoso), com a
  coluna versao evitando gravar por cima de uma mudança feita no meio.
- Dias de atendimento das áreas comerciais (para a efetividade): tabela areas_atendimento, que o administrador
  ajusta em Gestão › Configurar.
- O Assistente usa as mesmas funções (ContextoGestao): propor_acao confere um rascunho sem gravar (quem lança é o
  administrador, no botão), e andamento_acao dá os números da página.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import math
import re
from collections import defaultdict

from .banco import hora
from .calendario import Calendario
from .configuracao import Regras
from .conversas import NaoEncontrada, id_valido, novo_id
from .indicadores import (ABERTURAS, BASES, BASES_COM_PRODUTO, COMBINACOES, COMPARAR, FILTROS, FILTROS_PRODUTO,
                          FORMAS, MAX_PRODUTOS_PRECO, MEDIDAS, PERIODOS_BASE, TIPOS, _marcas, _redondo, calcular,
                          calendario_periodo, descritor, filtros_aceitos, janela_base, janela_fechada, medir, normalizar,
                          periodo_base, total_equipe, unidades, valor_de)
from .metas import MESES
from .projecoes import NOME_EQUIPE

__all__ = ["Gestao", "ContextoGestao", "SemDados", "andamento", "calendario_periodo", "unidades", "validar",
           "situacao", "prazo", "alvo_de", "classe_resultado", "comparar", "rotulo_padrao", "texto_alvo", "publica"]

TIPOS_ITEM = {"acao": "campanha", "objetivo": "objetivo"}
REGIOES = ("ES", "BA")
EQUIPES_REGIAO = {"ES": ("ES",), "BA": ("BA", "EDIR")}  # o Edir segue o calendário da BA
EQUIPES = ("ES", "BA", "EDIR")
ALVOS = {"fixo": "o número a atingir", "pct": "a base + X%",
         "mais": "a base + N (só nas campanhas de antes)"}  # na tela: Número e Percentual
ANTIGA = "logo_antes"  # base_periodo das campanhas de antes da 012 (o mesmo tamanho, logo antes do início)
SITUACOES = {"planejada": "Planejada", "em_vigor": "Em vigor", "encerrada": "Encerrada"}
GRUPOS = ("mussarela", "outras")
MAX_NOME = 120
MAX_TEXTO = 2000
MAX_ROTULO = 20
MAX_DIAS = 366  # objetivo
MAX_DIAS_ACAO = 182  # 26 semanas
MAX_SEMANAS = 26
MAX_MEMO = 500
MAX_PREVIA = 300  # vendedores na prévia da base
FOLGA_CONGELAR = 1  # o resultado congela quando os dados passam um dia do fim (pega as notas do dia seguinte)
DIAS_ENCERRADAS = 30  # a campanha encerrada fica no quadro e nas etiquetas por mais 30 dias
DIAS_OBJETIVO = 7  # o objetivo que terminou fica no topo por mais uma semana
PRORROGAR = 14
TRAVA_ACOES = 7_240_103  # pg_advisory_xact_lock: o mesmo rascunho do Assistente lançado duas vezes vira uma campanha só
DIAS_SEMANA = {"SEGUNDA": 1, "TERCA": 2, "QUARTA": 3, "QUINTA": 4, "SEXTA": 5, "SABADO": 6, "DOMINGO": 7}
ROTULOS = {"positivacao": "Positivação", "mix_medio": "Mix", "efetividade": "Efetividade", "frequencia": "Frequência",
           "preco_medio": "Preço"}
ROTULOS_MEDIDA = {("faturamento", "total"): "Faturamento", ("faturamento", "por_cliente"): "Venda média",
                  ("volume", "total"): "Volume", ("volume", "por_cliente"): "Volume/cliente",
                  ("clientes", "pct_carteira"): "Carteira", ("produtos", "total"): "Produtos"}
ORDEM_EVENTO = {"lancada": 0, "nota": 1, "parcial": 2, "editada": 3, "prorrogada": 3, "encerrada": 3, "removido": 3,
                "resultado": 4}
_COLUNAS = ("id", "tipo", "nome", "rotulo", "descricao", "regiao", "status", "inicio", "fim", "metrica", "parametros",
            "filtros", "alvo_tipo", "meta_padrao", "base_periodo", "base_inicio", "base_fim", "arquivada", "rascunho",
            "encerrada_em",
            "encerrada_por_nome", "resultado_em", "versao", "criada_em", "criada_por", "criada_por_nome",
            "atualizada_em", "atualizada_por_nome")
_CAMPOS = ", ".join(f"c.{x}" for x in _COLUNAS)
_COLUNAS_V = ("id_vendedor", "meta", "base", "base_num", "base_den", "base_em", "resultado", "resultado_num",
              "resultado_den", "parciais", "entrou_em")


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


def _float(x):
    return None if x is None else float(x)


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


def regiao_do_grupo(grupo: str) -> str | None:
    """ES ou BA para a equipe do vendedor (o Edir é da BA); None para quem não é de nenhuma (oculto)."""
    return next((r for r, equipes in EQUIPES_REGIAO.items() if grupo in equipes), None)


def rotulo_padrao(metrica: str, p: dict) -> str:
    """O nome curto da etiqueta do vendedor ("Mix", "Positivação")."""
    if metrica != "personalizada":
        return ROTULOS[metrica]
    return ROTULOS_MEDIDA.get((p.get("medida"), p.get("forma")), "Crescimento" if p.get("forma") == "crescimento"
                              else MEDIDAS.get(p.get("medida"), "Campanha"))


def _conferir_historico(p: dict, corte: dt.date, inicio_dados: dt.date | None, texto: str) -> None:
    """A base de clientes precisa do histórico antes de corte (o começo da janela da base, numa campanha)."""
    if not inicio_dados:
        return
    if corte < inicio_dados:
        raise ValueError(f"{texto} começa antes do histórico de vendas ({inicio_dados:%d/%m/%Y})")
    if p.get("clientes") == "recuperados" and corte - dt.timedelta(days=p["dias_sem_compra"]) <= inicio_dados:
        raise ValueError(f"o histórico de vendas começa em {inicio_dados:%d/%m/%Y}: com {p['dias_sem_compra']} dias sem "
                         f"compra antes de {corte:%d/%m/%Y}, nenhum cliente teria como ser recuperado")


def validar(dados: dict, cur, regras: Regras, permitidos: frozenset[int] | None, data_ref: dt.date,
            inicio_dados: dt.date | None = None, tipo: str = "acao", hoje: dt.date | None = None,
            antes: dict | None = None) -> dict:
    """Confere uma campanha (ou um objetivo) vinda da página ou do Assistente e devolve os dados normalizados. cur:
    cursor do recorte com todos os vendedores. inicio_dados: o começo do histórico do cache (para a base e o
    crescimento). antes: a campanha que está sendo editada; se ela é de antes da 012, pode manter a base "logo
    antes" (base_periodo logo_antes) e a meta "base + N" (alvo_tipo mais). Levanta ValueError com a explicação (a IA
    lê e corrige)."""
    if tipo not in TIPOS_ITEM:
        raise ValueError(f"tipo desconhecido: {tipo!r}")
    acao = tipo == "acao"
    if not isinstance(dados, dict):
        raise ValueError(f"{'a campanha' if acao else 'o objetivo'} veio inválid{'a' if acao else 'o'}")
    nome = " ".join(str(dados.get("nome") or "").split())
    if not nome:
        raise ValueError(f"dê um nome {'à campanha' if acao else 'ao objetivo'}")
    if len(nome) > MAX_NOME:
        raise ValueError(f"o nome pode ter até {MAX_NOME} caracteres")
    m = _medida(dados, cur, regras, data_ref, inicio_dados, acao, hoje, bool(antes and antes["base_periodo"] is None))
    metrica, parametros = m["metrica"], m["parametros"]
    alvo_tipo = str(dados.get("alvo_tipo") or "fixo").strip().lower()
    if alvo_tipo not in ALVOS or (alvo_tipo == "mais" and not (antes and antes["alvo_tipo"] == "mais")):
        raise ValueError("alvo_tipo deve ser fixo (o número a atingir) ou pct (a base de cada um + X%)")
    if not acao and alvo_tipo != "fixo":
        raise ValueError("o objetivo tem uma meta fixa para a equipe (alvo_tipo fixo)")
    if metrica == "preco_medio":
        meta_padrao, alvo_tipo = 100.0, "fixo"  # 100% do preço-alvo
    else:
        meta_padrao = _numero(dados.get("meta_padrao"), "a meta")
        if not meta_padrao:
            raise ValueError("dê a meta" + (" (o percentual sobre a base)" if alvo_tipo == "pct" else ""))
    rotulo = " ".join(str(dados.get("rotulo") or "").split()) or rotulo_padrao(metrica, parametros)
    if len(rotulo) > MAX_ROTULO:
        raise ValueError(f"o rótulo (o nome curto da etiqueta) pode ter até {MAX_ROTULO} caracteres")

    vendedores: dict[int, float | None] = {}
    if acao:
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
        _conferir_regiao(ids, nomes, regras, m["regiao"])
        if permitidos is not None:
            fora = [f"{nomes[v]} ({v})" for v in ids if v not in permitidos]
            if fora:
                raise ValueError(f"fora do seu acesso na Gestão: {', '.join(fora)}")
    return {
        "tipo": tipo, "nome": nome, "rotulo": rotulo, "descricao": _texto(dados.get("descricao"), "a descrição"),
        **m, "alvo_tipo": alvo_tipo, "meta_padrao": meta_padrao,
        "vendedores": [{"id": v, "meta": vendedores[v]} for v in sorted(vendedores)],
    }


def _conferir_regiao(ids, nomes: dict, regras: Regras, regiao: str) -> None:
    outra = [f"{nomes[v]} ({v}) é da equipe {NOME_EQUIPE.get(g, g)}" for v in ids
             if (g := regras.grupo_vendedor(v)) not in EQUIPES_REGIAO[regiao]]
    if outra:
        raise ValueError(f"{'; '.join(outra)}: esta campanha é da região {regiao}")


def _medida(dados: dict, cur, regras: Regras, data_ref: dt.date, inicio_dados: dt.date | None, acao: bool,
            hoje: dt.date | None, antiga: bool = False) -> dict:
    """A região, o período, o que mede (com os filtros e os preços-alvo) e, na campanha, a janela da base: a parte de
    validar() que a prévia da base também usa."""
    regiao = str(dados.get("regiao") or "").strip().upper()
    if regiao not in REGIOES:
        raise ValueError("escolha a região: ES ou BA (o Edir é da BA)")
    hoje = hoje or dt.date.today()
    inicio = _data(dados.get("inicio"), "início") if dados.get("inicio") else hoje
    if dados.get("fim"):
        fim = _data(dados.get("fim"), "fim")
    elif dados.get("semanas") not in (None, ""):
        try:
            semanas = int(dados["semanas"])
        except (TypeError, ValueError):
            raise ValueError("semanas deve ser um número inteiro") from None
        if not 1 <= semanas <= MAX_SEMANAS:
            raise ValueError(f"o prazo vai de 1 a {MAX_SEMANAS} semanas")
        fim = inicio + dt.timedelta(days=7 * semanas - 1)
    else:
        raise ValueError("dê o prazo: o número de semanas ou a data do fim")
    if fim < inicio:
        raise ValueError(f"o fim {'da campanha' if acao else 'do objetivo'} é antes do início")
    if (fim - inicio).days >= (MAX_DIAS_ACAO if acao else MAX_DIAS):
        raise ValueError(f"a campanha pode durar até {MAX_SEMANAS} semanas" if acao else "o objetivo pode durar até um ano")
    metrica, parametros = normalizar(dados.get("metrica"), dados.get("parametros"))
    if acao and parametros.get("forma") == "crescimento":
        raise ValueError("numa campanha a meta já sai da base: em vez da forma crescimento, use o total com alvo_tipo "
                         "pct (+X% sobre a base)")
    filtros = _filtros(dados.get("filtros") or {}, cur, regras)
    fora = [k for k in filtros if k not in filtros_aceitos(metrica, parametros)]
    if fora:
        raise ValueError({"efetividade": "a efetividade conta pedidos e visitas, sem produto: use só filtros de "
                                         "cliente (UF, segmento, área)",
                          "preco_medio": "no preço médio os produtos vêm da lista de preços-alvo (metas_produto); "
                                         "os filtros são só de cliente (UF, segmento, área)"}[metrica])
    com_produto = any(filtros.get(k) for k in FILTROS_PRODUTO)
    if parametros.get("clientes") in BASES_COM_PRODUTO and not com_produto:
        raise ValueError(f"para contar {BASES[parametros['clientes']]}, escolha os produtos (produtos, linhas, "
                         "categorias ou grupo)")
    if parametros.get("medida") == "volume":
        if not com_produto:
            raise ValueError("volume precisa de um filtro de produto (produtos, linhas, categorias ou grupo), para "
                             "somar quantidades da mesma unidade")
        achadas = unidades(cur, filtros, data_ref)
        if len(achadas) > 1:
            raise ValueError(f"os produtos escolhidos têm unidades diferentes ({', '.join(u or 'sem unidade' for u in achadas)}); "
                             "no volume use produtos da mesma unidade")
    base_periodo = base_inicio = base_fim = None
    if acao:
        base_periodo = str(dados.get("base_periodo") or "mes").strip().lower()
        if base_periodo == ANTIGA:
            if not antiga:
                raise ValueError(f"escolha o período da base: {', '.join(PERIODOS_BASE)} (o mesmo tamanho logo antes "
                                 "do início é só das campanhas de antes)")
            base_periodo = None
            base_inicio, base_fim = janela_base(inicio, fim)
        elif base_periodo in PERIODOS_BASE:
            base_inicio, base_fim = janela_fechada(inicio, base_periodo)
        else:
            raise ValueError(f"o período da base (base_periodo) deve ser {', '.join(PERIODOS_BASE)}")
        _conferir_historico(parametros, base_inicio, inicio_dados,
                            f"a base desta campanha ({texto_janela(base_periodo, base_inicio, base_fim)})")
    else:
        _conferir_historico(parametros, inicio, inicio_dados, f"o objetivo ({inicio:%d/%m/%Y})")
        if parametros.get("forma") == "crescimento" and inicio_dados:
            de, a = periodo_base(inicio, fim, parametros["comparar"])
            if de < inicio_dados:
                raise ValueError(f"o período de comparação ({de:%d/%m/%Y} a {a:%d/%m/%Y}) começa antes do histórico "
                                 f"de vendas ({inicio_dados:%d/%m/%Y})")
    metas_produto = _metas_produto(dados.get("metas_produto"), cur, regras) if metrica == "preco_medio" else []
    return {"regiao": regiao, "inicio": inicio, "fim": fim, "metrica": metrica, "parametros": parametros,
            "filtros": filtros, "base_periodo": base_periodo, "base_inicio": base_inicio, "base_fim": base_fim,
            "metas_produto": metas_produto}


# --- base, alvo e resultado -------------------------------------------------------------------
def andamento(cur, campanha: dict, regras: Regras, cal: Calendario, data_ref: dt.date,
              permitidos: frozenset[int] | None, areas: dict | None = None, abrir: str | None = None) -> dict:
    """Realizado, meta, % e situação (pelo ritmo) de cada vendedor (só os do acesso de quem vê) e o total."""
    return calcular(cur, campanha, regras, cal, data_ref, permitidos, areas, abrir)


def situacao(c: dict, hoje: dt.date) -> str:
    """planejada, em_vigor ou encerrada (pelas datas; a campanha encerrada antes do fim também)."""
    if c["tipo"] == "acao" and (c.get("encerrada_em") or c.get("resultado_em")):
        return "encerrada"
    if hoje < c["inicio"]:
        return "planejada"
    return "encerrada" if hoje > c["fim"] else "em_vigor"


def prazo(c: dict, hoje: dt.date) -> dict:
    """Para a barra de tempo: dias da campanha, quantos faltam (0 = termina hoje) e a fração que já passou."""
    dias = (c["fim"] - c["inicio"]).days
    if hoje < c["inicio"]:
        decorrido = 0.0
    elif hoje >= c["fim"]:
        decorrido = 1.0
    else:
        decorrido = (hoje - c["inicio"]).days / dias
    return {"dias": dias + 1, "faltam": max((c["fim"] - hoje).days, 0), "comeca_em": max((c["inicio"] - hoje).days, 0),
            "decorrido": round(decorrido, 4)}


def alvo_de(alvo_tipo: str, desc: dict, base, meta) -> float | None:
    """O alvo de um vendedor, na unidade do valor (percentuais em fração). fixo: a meta; mais: a base + a meta (nos
    percentuais, em pontos); pct: a base + meta%. Sem base (ou base 0 no pct), não há alvo. Clientes e produtos
    arredondam para cima."""
    if desc["tipo"] == "preco_medio":
        return 1.0
    escala = 100 if desc["meta_em_pct"] else 1
    if alvo_tipo == "fixo":
        return meta / escala if meta else None
    if base is None or not meta:
        return None
    if alvo_tipo == "mais":
        alvo = base + meta / escala
    else:
        if not base:
            return None
        alvo = base * (1 + meta / 100)
    if desc["formato"] in ("clientes", "produtos"):
        alvo = math.ceil(alvo - 1e-9)
    return alvo


def classe_resultado(res, base, alvo) -> str:
    """ok = alvo batido; mid = melhorou sobre a base sem chegar ao alvo; bad = não passou da base; sem_alvo (sem base
    nem alvo para comparar); sem_dados (sem resultado: média sem divisor)."""
    if res is None:
        return "sem_dados"
    if alvo is not None and (res >= alvo or (alvo and round(res / alvo, 3) >= 1)):
        return "ok"
    if base is None:
        return "bad" if alvo is not None else "sem_alvo"
    return "mid" if res > base else "bad"


def _pct(res, alvo):
    return res / alvo if res is not None and alvo else None


def pct_da_campanha(desc: dict, pares) -> dict:
    """O andamento da campanha contra a meta, com os pares (resultado, meta) dos vendedores que têm os dois: nos
    indicadores de soma, a soma dos resultados ÷ a soma das metas; nas médias, a média do % de cada vendedor."""
    pares = [(r, a) for r, a in pares if r is not None and a]
    if not pares:
        return {"meta_pct": None, "com_meta": 0}
    if desc["comportamento"] == "soma":
        pct = sum(r for r, _ in pares) / sum(a for _, a in pares)
    else:
        pct = sum(r / a for r, a in pares) / len(pares)
    return {"meta_pct": _redondo(pct), "com_meta": len(pares)}


def comparar(res, base, alvo) -> dict:
    """A classe, quanto do caminho da base até o alvo já foi feito e a diferença sobre a base."""
    delta = res - base if res is not None and base is not None else None
    caminho = (res - base) / (alvo - base) if None not in (res, base, alvo) and alvo != base else None
    return {"classe": classe_resultado(res, base, alvo), "delta": _redondo(delta),
            "delta_pct": _redondo(delta / base) if delta is not None and base else None,
            "caminho": _redondo(caminho)}


def _em_ordem(itens: list[dict]) -> list[dict]:
    """Em vigor (pelo fim mais perto), depois as planejadas e por fim as encerradas, da mais recente para a mais
    antiga."""
    ordem = {"em_vigor": 0, "planejada": 1}
    correm = sorted((a for a in itens if a["situacao"] != "encerrada"),
                    key=lambda a: (ordem[a["situacao"]], a["fim"], a["id"]))
    acabaram = sorted((a for a in itens if a["situacao"] == "encerrada"), key=lambda a: (a["fim"], a["id"]), reverse=True)
    return correm + acabaram


def _num(v: float, desc: dict) -> str:
    casas = 0 if desc["formato"] in ("clientes", "produtos") else (2 if desc["formato"] in ("razao", "moeda") else 1)
    t = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return t.rstrip("0").rstrip(",") if "," in t else t


def texto_alvo(alvo_tipo: str, meta: float, desc: dict) -> str:
    """Como a meta aparece para a IA e no rascunho ("+10% sobre a base de cada um")."""
    if desc["tipo"] == "preco_medio":
        return "no preço-alvo de cada produto (100%)"
    if alvo_tipo == "pct":
        return f"+{_num(meta, {'formato': 'pct'})}% sobre a base de cada um"
    if alvo_tipo == "mais":
        sufixo = " p.p." if desc["meta_em_pct"] else ""
        return f"+{_num(meta, desc)}{sufixo} sobre a base de cada um"
    return f"{_num(meta, desc)}{'%' if desc['meta_em_pct'] else ''} ({desc.get('rotulo_meta') or 'para cada um'})"


def texto_janela(periodo: str | None, de: dt.date, ate: dt.date) -> str:
    """A janela da base em texto ("setembro/2026", "o trimestre de julho a setembro/2026"); None = a regra de antes."""
    if periodo is None:
        return f"{de:%d/%m/%Y} a {ate:%d/%m/%Y}, o mesmo tamanho logo antes do início"
    if periodo in ("semana", "quinzena"):
        return f"a {periodo} de {de:%d/%m} a {ate:%d/%m/%Y}"
    if periodo == "mes":
        return f"{MESES[de.month - 1]}/{de.year}"
    if periodo == "ano":
        return f"o ano de {de.year}"
    return f"o {periodo} de {MESES[de.month - 1]} a {MESES[ate.month - 1]}/{ate.year}"


# --- do banco para a página -------------------------------------------------------------------
def _vendedor(linha) -> dict:
    v = dict(zip(_COLUNAS_V, linha))
    return {"id": v["id_vendedor"], "meta": _float(v["meta"]), "base": _float(v["base"]),
            "base_num": _float(v["base_num"]), "base_den": _float(v["base_den"]), "base_em": hora(v["base_em"]),
            "resultado": _float(v["resultado"]), "resultado_num": _float(v["resultado_num"]),
            "resultado_den": _float(v["resultado_den"]), "parciais": v["parciais"], "entrou_em": hora(v["entrou_em"])}


def _campanha(linha, vendedores: list[dict], produtos: list[dict]) -> dict:
    c = dict(zip(_COLUNAS, linha))
    c.update(parametros=c["parametros"] or {}, filtros=c["filtros"] or {}, meta_padrao=float(c["meta_padrao"]),
             rascunho=str(c["rascunho"]) if c["rascunho"] else None, vendedores=vendedores, metas_produto=produtos)
    for k in ("criada_em", "atualizada_em", "encerrada_em", "resultado_em"):
        c[k] = hora(c[k])
    return c


def publica(c: dict) -> dict:
    """A campanha ou o objetivo como a página e a IA recebem (datas em texto e o descritor do que mede)."""
    datas = {k: c[k].isoformat() if c.get(k) else None for k in ("inicio", "fim", "base_inicio", "base_fim")}
    return {**c, **datas, "indicador": descritor(c["metrica"], c["parametros"])}


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


class _Contas:
    """O que uma leitura usa nas contas: o recorte com todos os vendedores (e as contas guardadas nele), um cursor,
    as regras, o calendário, a data dos dados e os dias de atendimento das áreas (lidos uma vez)."""

    def __init__(self, gestao: "Gestao"):
        self.gestao = gestao
        self.recorte = gestao._recorte()
        self.cur = self.recorte.cursor()
        self.regras = gestao.calc.regras()
        self.cal = gestao.calc.calendario(self.regras)
        self.data_ref = gestao._data_ref()
        self._areas = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cur.close()

    def memo(self, chave, fazer):
        memo = self.recorte.memo
        if chave not in memo:
            valor = fazer()
            if len(memo) > MAX_MEMO:
                memo.clear()
            memo[chave] = valor
        return memo[chave]

    def areas(self, c: dict) -> tuple[dict | None, str | None]:
        """Os dias de atendimento (e a versão deles, para as contas guardadas), só para a efetividade."""
        if c["metrica"] != "efetividade":
            return None, None
        if self.gestao.calc.cache.sem_pedidos:
            raise SemDados("os pedidos de venda ainda não chegaram do computador da empresa; a efetividade aparece "
                           "depois da próxima atualização")
        if self.gestao.calc.cache.sem_rede:  # sem ela, as bases gravadas sairiam com todos os clientes semanais
            raise SemDados("a frequência de compra dos clientes (rede) ainda não chegou do computador da empresa; a "
                           "efetividade aparece depois da próxima atualização")
        if self._areas is None:
            self._areas = self.gestao._areas()
        return self._areas, json.dumps(sorted(self._areas.items()))

    def unidade(self, c: dict) -> str:
        if c["parametros"].get("medida") != "volume":
            return ""
        achadas = self.memo(("unidade", json.dumps(c["filtros"], sort_keys=True)),
                            lambda: unidades(self.cur, c["filtros"], self.data_ref))
        return achadas[0] if len(achadas) == 1 else "/".join(achadas)

    def descritor(self, c: dict) -> dict:
        return descritor(c["metrica"], c["parametros"], self.unidade(c))

    def nomes(self, ids) -> dict[int, tuple[str, str]]:
        ids = sorted(set(ids))
        if not ids:
            return {}
        return {v: (n, e) for v, n, e in self.cur.execute(
            f"SELECT id_vendedor, vendedor, equipe FROM vendedores WHERE id_vendedor IN ({_marcas(ids)})", ids).fetchall()}


# --- campanhas e objetivos no banco ---------------------------------------------------------------
class Gestao:
    def __init__(self, banco, calc, assistente, hoje=None):
        """assistente: o bi/assistente.py, de onde vêm o recorte com todos os vendedores e o escopo em ids. hoje: a
        função que dá a data de hoje (os testes fixam)."""
        self.banco = banco
        self.calc = calc
        self.assistente = assistente
        self.hoje = hoje or dt.date.today

    # --- dados do ERP ------------------------------------------------------------------------
    def _conferir_dados(self) -> None:
        cache = self.calc.cache
        if not cache.pronto():
            raise SemDados("os dados de vendas ainda estão sendo preparados; os números aparecem quando ficarem prontos")
        if cache.sem_detalhe:
            raise SemDados("os dados por cliente ainda não chegaram do computador da empresa; os números aparecem "
                           "depois da próxima atualização")

    def _recorte(self):
        self._conferir_dados()
        # Só as consultas da Gestão rodam aqui; com o crédito, divide o recorte com o Assistente do administrador.
        return self.assistente.recorte(None, credito=True)

    def _cursor(self):
        return self._recorte().cursor()

    def _contas(self) -> _Contas:
        return _Contas(self)

    def _data_ref(self) -> dt.date:
        return self.calc.cache.data_ref() or self.hoje()

    def _inicio_dados(self) -> dt.date:
        return self.calc.cache.inicio

    def ids(self, escopo) -> frozenset[int] | None:
        """escopo: (vendedores, equipes) de bi/acesso.py escopo_gestao -> os ids (None = todos)."""
        vendedores, equipes = escopo
        if vendedores is None and equipes is None:
            return None
        self._conferir_dados()
        return self.assistente.ids_do_escopo(vendedores, equipes)

    def _catalogo(self, k: _Contas) -> list[dict]:
        return k.memo(("catalogo_vendedores",), self.assistente.catalogo_vendedores)

    def regioes(self, k: _Contas, ids) -> list[str]:
        """As regiões que a pessoa vê: as dos vendedores do acesso dela (o administrador, as duas)."""
        if ids is None:
            return list(REGIOES)
        tem = {regiao_do_grupo(v["equipe"]) for v in self._catalogo(k) if v["id"] in ids}
        return [r for r in REGIOES if r in tem]

    def catalogo(self, escopo) -> dict:
        """O que o formulário oferece: vendedores do acesso (com venda nos últimos 12 meses), produtos vendidos nos
        últimos 12 meses (sem os "não conta", com o preço médio dos últimos 90 dias), linhas, categorias, UFs,
        segmentos e áreas comerciais, os tipos de indicador e as regiões."""
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
            "tipos": tipos(), "regioes": [{"id": r, "equipes": list(EQUIPES_REGIAO[r])} for r in REGIOES],
            "alvos": ALVOS,
        }

    def _areas(self) -> dict[int, list[int]]:
        """Dias de atendimento de cada área ({id_area: [dias ISO]}; [] = área não atendida)."""
        with self.banco.conexao() as con:
            return {a: list(d) for a, d in con.execute("SELECT id_area, dias FROM areas_atendimento")}

    # --- contas ------------------------------------------------------------------------------
    def _valores(self, k: _Contas, c: dict, ids, inicio: dt.date, ate: dt.date) -> dict[int, tuple]:
        """{vendedor: (valor, numerador, denominador)} do indicador entre inicio e ate (guardado no recorte quando a
        campanha já está gravada: c["id"])."""
        ids = sorted(ids)
        if not ids or ate < inicio:
            return {}
        areas, versao_areas = k.areas(c)

        def fazer():
            m = medir(k.cur, c, ids, inicio, ate, areas)
            comportamento = descritor(c["metrica"], c["parametros"])["comportamento"]
            saida = {}
            for v in ids:
                x = m["vend"].get(v)
                saida[v] = (valor_de(comportamento, x), (x or {}).get("num", 0.0), (x or {}).get("den"))
            return saida
        if c.get("id") is None:
            return fazer()
        return k.memo(("valores", c["id"], c["versao"], tuple(ids), inicio, ate, versao_areas), fazer)

    def _bases(self, k: _Contas, c: dict, ids) -> dict[int, tuple]:
        """A base dos vendedores: o indicador na janela da base ({} se os dados ainda não cobrem a janela). A cópia com
        as datas da janela faz a base de clientes (novos, recuperados...) contar a partir do começo da janela."""
        if not ids or k.data_ref < c["base_fim"]:
            return {}
        janela = {**c, "inicio": c["base_inicio"], "fim": c["base_fim"]}
        return self._valores(k, janela, ids, c["base_inicio"], c["base_fim"])

    def _parciais(self, k: _Contas, c: dict, ids) -> list[dict]:
        """O valor acumulado ao fim de cada semana completa da campanha (antes da última), até onde os dados vão."""
        saida, i = [], 1
        limite = min(c["fim"], k.data_ref)
        while True:
            ate = c["inicio"] + dt.timedelta(days=7 * i - 1)
            if ate >= c["fim"] or ate > limite:
                return saida
            saida.append({"semana": i, "ate": ate, "valores": self._valores(k, c, ids, c["inicio"], ate)})
            i += 1

    def _resultado(self, k: _Contas, c: dict) -> dict:
        ids = [v["id"] for v in c["vendedores"]]
        parciais = self._parciais(k, c, ids)
        return {"valores": self._valores(k, c, ids, c["inicio"], c["fim"]),
                "parciais": {vid: [{"semana": p["semana"], "ate": p["ate"].isoformat(),
                                    "valor": _redondo(p["valores"].get(vid, (None,))[0])} for p in parciais]
                             for vid in ids}}

    @staticmethod
    def _meta_v(c: dict, v: dict) -> float:
        return c["meta_padrao"] if v.get("meta") is None else v["meta"]

    @staticmethod
    def _retrato(c: dict, base, alvo) -> dict:
        """O que o histórico guarda de uma campanha no momento do evento."""
        return {"nome": c["nome"], "rotulo": c["rotulo"], "inicio": c["inicio"].isoformat(), "fim": c["fim"].isoformat(),
                "base_periodo": c.get("base_periodo"), "base_inicio": c["base_inicio"].isoformat(),
                "base_fim": c["base_fim"].isoformat(), "alvo_tipo": c["alvo_tipo"], "base": _redondo(base),
                "alvo": _redondo(alvo),
                "vendedores": len(c["vendedores"])}

    @staticmethod
    def _evento(con, vid: int, campanha, tipo: str, dados: dict, usuario: dict | None, texto: str = "") -> None:
        con.execute("INSERT INTO gestao_eventos (id_vendedor, campanha, tipo, texto, dados, criada_por, criada_por_nome) "
                    "VALUES (%s, %s, %s, %s, %s::jsonb, (SELECT id FROM usuarios WHERE id = %s), %s)",
                    [vid, campanha, tipo, texto, json.dumps(dados, ensure_ascii=False),
                     usuario["id"] if usuario else None, usuario["nome"] if usuario else "painel"])

    def _gravar_bases(self, con, c: dict, desc: dict, bases: dict) -> None:
        """Grava as bases medidas e completa o retrato dos eventos que estavam com a base pendente."""
        por_id = {v["id"]: v for v in c["vendedores"]}
        for vid, (valor, num, den) in bases.items():
            con.execute("UPDATE campanha_vendedores SET base = %s, base_num = %s, base_den = %s, base_em = now() "
                        "WHERE campanha = %s AND id_vendedor = %s", [valor, num, den, c["id"], vid])
            alvo = alvo_de(c["alvo_tipo"], desc, valor, self._meta_v(c, por_id.get(vid, {})))
            con.execute("UPDATE gestao_eventos SET dados = dados || %s::jsonb WHERE campanha = %s AND id_vendedor = %s "
                        "AND dados->>'base_pendente' = 'true'",
                        [json.dumps({"base": _redondo(valor), "alvo": _redondo(alvo), "base_pendente": False}), c["id"], vid])

    def _congelar(self, con, c: dict, desc: dict, bases: dict, resultado: dict) -> None:
        """Congela o resultado de cada vendedor (com as parciais) e põe o evento no histórico de cada um."""
        for v in c["vendedores"]:
            vid = v["id"]
            base = bases[vid][0] if vid in bases else v["base"]
            res, num, den = resultado["valores"].get(vid, (None, None, None))
            alvo = alvo_de(c["alvo_tipo"], desc, base, self._meta_v(c, v))
            con.execute("UPDATE campanha_vendedores SET resultado = %s, resultado_num = %s, resultado_den = %s, "
                        "parciais = %s::jsonb WHERE campanha = %s AND id_vendedor = %s",
                        [res, num, den, json.dumps(resultado["parciais"].get(vid, [])), c["id"], vid])
            self._evento(con, vid, c["id"], "resultado",
                         {**self._retrato(c, base, alvo), "resultado": _redondo(res), **comparar(res, base, alvo)}, None)
        con.execute("UPDATE campanhas SET resultado_em = now(), status = 'concluida' WHERE id = %s", [c["id"]])

    @staticmethod
    def _travar_versao(con, c: dict) -> bool:
        atual = con.execute("SELECT versao FROM campanhas WHERE id = %s FOR UPDATE", [c["id"]]).fetchone()
        return bool(atual) and atual[0] == c["versao"]

    def _pendencias(self, k: _Contas, acoes: list[dict]) -> bool:
        """Mede as bases que os dados já cobrem e congela o resultado das campanhas vencidas (o DuckDB fora da transação;
        a gravação desiste se a campanha mudou no meio, e a próxima leitura refaz). True se gravou alguma coisa."""
        gravou = False
        for c in acoes:
            if c["tipo"] != "acao" or c["arquivada"]:
                continue
            pendentes = [v["id"] for v in c["vendedores"] if v["base_em"] is None]
            medir_base = bool(pendentes) and k.data_ref >= c["base_fim"]
            vence = c["resultado_em"] is None and c["inicio"] <= k.data_ref and (
                c["encerrada_em"] is not None or k.data_ref >= c["fim"] + dt.timedelta(days=FOLGA_CONGELAR))
            if not (medir_base or vence):
                continue
            try:
                bases = self._bases(k, c, pendentes) if medir_base else {}
                resultado = self._resultado(k, c) if vence else None
            except SemDados:
                continue
            desc = descritor(c["metrica"], c["parametros"])
            with self.banco.conexao() as con:
                if not self._travar_versao(con, c):
                    continue
                self._gravar_bases(con, c, desc, bases)
                if resultado is not None:
                    self._congelar(con, c, desc, bases, resultado)
                con.execute("UPDATE campanhas SET versao = versao + 1 WHERE id = %s", [c["id"]])
            gravou = True
        return gravou

    def _estado(self, k: _Contas, c: dict, hoje: dt.date, desc: dict) -> dict:
        """Base, alvo e (na campanha encerrada) o resultado de cada vendedor: o congelado, ou o provisório enquanto os
        dados não passam do fim."""
        sit = situacao(c, hoje)
        congelado = c["resultado_em"] is not None
        vivo, aviso = {}, None
        if sit == "encerrada" and not congelado and c["inicio"] <= k.data_ref:
            try:
                vivo = self._valores(k, c, [v["id"] for v in c["vendedores"]], c["inicio"], min(c["fim"], k.data_ref))
            except SemDados as e:
                aviso = str(e)
        vendedores = {}
        for v in c["vendedores"]:
            base = v["base"] if v["base_em"] else None
            alvo = alvo_de(c["alvo_tipo"], desc, base, self._meta_v(c, v))
            item = {"base": _redondo(base), "base_pendente": v["base_em"] is None, "alvo": _redondo(alvo),
                    "meta": self._meta_v(c, v), "resultado": None}
            if congelado or vivo:
                res = v["resultado"] if congelado else vivo.get(v["id"], (None,))[0]
                item.update(resultado=_redondo(res), **comparar(res, base, alvo))
            vendedores[v["id"]] = item
        return {"situacao": sit, "congelado": congelado, "provisorio": sit == "encerrada" and not congelado,
                "vendedores": vendedores, "aviso": aviso}

    # --- leitura -----------------------------------------------------------------------------
    @staticmethod
    def _ler(con, onde: str, params: list, travar: bool = False) -> list[dict]:
        linhas = con.execute(f"SELECT {_CAMPOS} FROM campanhas c WHERE {onde} ORDER BY c.fim, c.id"
                             + (" FOR UPDATE" if travar else ""), params).fetchall()
        vendedores, produtos = defaultdict(list), defaultdict(list)
        if linhas:
            ids = [[ln[0] for ln in linhas]]
            for ln in con.execute(f"SELECT campanha, {', '.join(_COLUNAS_V)} FROM campanha_vendedores "
                                  "WHERE campanha = ANY(%s) ORDER BY campanha, id_vendedor", ids):
                vendedores[ln[0]].append(_vendedor(ln[1:]))
            for camp, pid, meta in con.execute(
                    "SELECT campanha, id_produto, meta FROM campanha_produtos WHERE campanha = ANY(%s) "
                    "ORDER BY campanha, id_produto", ids):
                produtos[camp].append({"id": pid, "meta": float(meta)})
        return [_campanha(ln, vendedores[ln[0]], produtos[ln[0]]) for ln in linhas]

    def _uma(self, con, id_, tipo: str | None = None, travar: bool = False) -> dict:
        nome = TIPOS_ITEM.get(tipo, "item")
        try:
            id_ = int(id_)
        except (TypeError, ValueError):
            raise NaoEncontrada(f"{nome} não encontrad{'o' if tipo == 'objetivo' else 'a'}") from None
        onde, params = "c.id = %s", [id_]
        if tipo:
            onde, params = onde + " AND c.tipo = %s", [id_, tipo]
        achadas = self._ler(con, onde, params, travar)
        if not achadas:
            raise NaoEncontrada(f"{nome} não encontrad{'o' if tipo == 'objetivo' else 'a'}; pode ter sido excluíd"
                                f"{'o' if tipo == 'objetivo' else 'a'}")
        return achadas[0]

    @staticmethod
    def _visivel(c: dict, ids) -> bool:
        return ids is None or any(v["id"] in ids for v in c["vendedores"])

    def _ler_regiao(self, regiao: str, hoje: dt.date) -> list[dict]:
        """As campanhas e os objetivos que o quadro da região mostra (sem as arquivadas; as encerradas, por 30 dias)."""
        with self.banco.conexao() as con:
            return self._ler(con, "NOT c.arquivada AND c.regiao = %s AND ((c.tipo = 'objetivo' AND c.fim >= %s) OR "
                                  "(c.tipo = 'acao' AND (c.fim >= %s OR c.resultado_em IS NULL)))",
                             [regiao, hoje - dt.timedelta(days=DIAS_OBJETIVO), hoje - dt.timedelta(days=DIAS_ENCERRADAS)])

    def _time(self, k: _Contas, regiao: str, meses) -> set[int]:
        """A equipe da região: os vendedores com meta (planilha METAS) em algum dos meses, como na página Metas.
        Contas da casa (venda interna, funcionário, produtor) não têm meta e ficam fora."""
        equipes = EQUIPES_REGIAO[regiao]
        return {m["id_vendedor"] for m in self.calc.metas.dados()
                if m["mes"] in meses and k.regras.grupo_vendedor(m["id_vendedor"]) in equipes}

    def _time_padrao(self, k: _Contas, regiao: str) -> set[int]:
        """A equipe do mês das metas (o mesmo da página Metas); sem planilha, quem vendeu nos últimos 12 meses."""
        padrao = self.calc.opcoes()["padrao"]
        time = self._time(k, regiao, {dt.date(padrao["ano"], padrao["mes"], 1)}) if padrao else set()
        return time or {v["id"] for v in self._catalogo(k) if v["equipe"] in EQUIPES_REGIAO[regiao] and not v["inativo"]}

    def _objetivo(self, k: _Contas, o: dict, ids, time_padrao: set[int]) -> tuple[dict, dict | None]:
        """O andamento do objetivo, com a equipe dos meses dele (só os vendedores do acesso de quem vê), e quantos
        da equipe contaram quando a pessoa vê só parte dela."""
        meses, d = set(), o["inicio"].replace(day=1)
        while d <= o["fim"]:
            meses.add(d)
            d = (d + dt.timedelta(days=32)).replace(day=1)
        time = self._time(k, o["regiao"], meses) or time_padrao
        conta = sorted(time if ids is None else time & ids)
        parcial = None if ids is None or time <= ids else {"vendedores": len(conta), "total": len(time)}
        areas, versao_areas = k.areas(o)
        a = k.memo(("objetivo", o["id"], o["versao"], tuple(conta), versao_areas),
                   lambda: total_equipe(k.cur, o, conta, k.cal, k.data_ref, o["regiao"], areas))
        return a, parcial

    def _cartao_objetivo(self, k: _Contas, o: dict, ids, hoje: dt.date, time_padrao: set[int]) -> dict:
        item = {**publica(o), "situacao": situacao(o, hoje), "prazo": prazo(o, hoje), "parcial": None,
                "andamento": None, "aviso": None}
        try:
            item["andamento"], item["parcial"] = self._objetivo(k, o, ids, time_padrao)
            item["indicador"] = item["andamento"]["indicador"]
        except SemDados as e:
            item["aviso"] = str(e)
        item.pop("vendedores", None)
        return item

    def quadro(self, usuario: dict, escopo, regiao: str | None = None) -> dict:
        """A página de uma região: os objetivos, as campanhas (com o tempo e quantos ficaram no alvo) e um quadrado por
        vendedor do acesso (% da meta de faturamento do mês e uma etiqueta por campanha)."""
        admin = usuario["papel"] == "admin"
        hoje = self.hoje()
        saida = {"regiao": None, "regioes": [], "hoje": hoje.isoformat(), "data_ref": self.calc.cache.info.get("data_ref"),
                 "pode_editar": admin, "aviso": None, "objetivos": [], "acoes": [], "vendedores": []}
        try:
            k = self._contas()
        except SemDados as e:
            saida["aviso"] = str(e)
            return saida
        with k:
            ids = self.ids(escopo)
            regioes = self.regioes(k, ids)
            saida["regioes"] = regioes
            if not regioes:
                saida["aviso"] = "nenhum vendedor no seu acesso da Gestão; fale com o administrador"
                return saida
            regiao = str(regiao or "").strip().upper() or regioes[0]
            if regiao not in REGIOES:
                raise ValueError(f"região desconhecida: {regiao!r} (use ES ou BA)")
            if regiao not in regioes:
                raise PermissionError(f"seu acesso na Gestão não inclui vendedores da região {regiao}")
            saida["regiao"] = regiao
            itens = self._ler_regiao(regiao, hoje)
            if self._pendencias(k, itens):
                itens = self._ler_regiao(regiao, hoje)
            acoes = [c for c in itens if c["tipo"] == "acao" and self._visivel(c, ids)]
            catalogo = self._catalogo(k)
            time = self._time_padrao(k, regiao)
            saida["objetivos"] = [self._cartao_objetivo(k, o, ids, hoje, time)
                                  for o in sorted((c for c in itens if c["tipo"] == "objetivo"),
                                                  key=lambda o: (o["inicio"], o["id"]))]

            etiquetas: dict[int, list] = defaultdict(list)
            cartoes = []
            for c in acoes:
                desc = k.descritor(c)
                estado = self._estado(k, c, hoje, desc)
                visiveis = [vid for vid in estado["vendedores"] if ids is None or vid in ids]
                encerrada = estado["situacao"] == "encerrada"
                em_vigor = estado["situacao"] == "em_vigor"
                aviso = estado["aviso"]
                vivo = {}
                if em_vigor and c["inicio"] <= k.data_ref:
                    try:
                        vivo = self._valores(k, c, visiveis, c["inicio"], min(c["fim"], k.data_ref))
                    except SemDados as e:
                        aviso = str(e)
                pares = {}  # vendedor -> (resultado até agora ou final, meta)
                for vid in visiveis:
                    e = estado["vendedores"][vid]
                    res = vivo.get(vid, (None,))[0] if em_vigor else e["resultado"]
                    pares[vid] = (res, e["alvo"])
                classes = [estado["vendedores"][vid].get("classe") for vid in visiveis]
                cartoes.append({
                    "id": c["id"], "nome": c["nome"], "rotulo": c["rotulo"], "descricao": c["descricao"],
                    "inicio": c["inicio"].isoformat(), "fim": c["fim"].isoformat(), "situacao": estado["situacao"],
                    "prazo": prazo(c, hoje), "vendedores": len(visiveis), "total_vendedores": len(c["vendedores"]),
                    "no_alvo": sum(1 for x in classes if x == "ok") if encerrada else None,
                    "com_resultado": sum(1 for x in classes if x not in (None, "sem_dados")) if encerrada else None,
                    "indicador": desc, "unidade": desc["unidade"], "alvo_tipo": c["alvo_tipo"],
                    "meta_padrao": c["meta_padrao"], "base_periodo": c["base_periodo"], "provisorio": estado["provisorio"],
                    "encerrada_em": c["encerrada_em"], "aviso": aviso,
                    "base_pendente": any(estado["vendedores"][vid]["base_pendente"] for vid in visiveis),
                    "criada_por_nome": c["criada_por_nome"],
                    **(pct_da_campanha(desc, pares.values()) if estado["situacao"] != "planejada"
                       else {"meta_pct": None, "com_meta": 0}),
                })
                if not em_vigor:
                    continue
                for vid in visiveis:  # os cards dos vendedores mostram só as campanhas em vigor
                    res, alvo = pares[vid]
                    etiquetas[vid].append({"id": c["id"], "rotulo": c["rotulo"], "situacao": "em_vigor",
                                           "fim": c["fim"].isoformat(), "resultado": _redondo(res),
                                           "alvo": _redondo(alvo), "pct": _redondo(_pct(res, alvo)),
                                           "base_pendente": estado["vendedores"][vid]["base_pendente"]})
            saida["acoes"] = _em_ordem(cartoes)

            # os quadrados: a equipe do acesso e quem está numa campanha que ainda corre
            grade = sorted(vid for vid in time if ids is None or vid in ids)
            extras = {vid for c in acoes if situacao(c, hoje) != "encerrada" for vid in (v["id"] for v in c["vendedores"])
                      if vid not in time and (ids is None or vid in ids)}
            por_id = {v["id"]: v for v in catalogo}
            nomes = k.nomes([vid for vid in (*grade, *extras) if vid not in por_id])
            vendedores = []
            for vid in [*grade, *sorted(extras)]:
                info = por_id.get(vid)
                nome = info["nome"] if info else nomes.get(vid, (f"Vendedor {vid}",))[0]
                equipe = info["equipe"] if info else k.regras.grupo_vendedor(vid)
                lista = _em_ordem(etiquetas.get(vid, []))
                vendedores.append({"id": vid, "nome": nome, "equipe": equipe, "inativo": bool(info and info["inativo"]),
                                   "acoes": lista, "em_vigor": len(lista)})
            vendedores.sort(key=lambda v: _chave(v["nome"]))
            saida["vendedores"] = vendedores
        return saida

    def _info_vendedor(self, k: _Contas, vid: int) -> dict:
        por_id = {v["id"]: v for v in self._catalogo(k)}
        if vid in por_id:
            v = por_id[vid]
            return {"id": vid, "nome": v["nome"], "equipe": v["equipe"], "regiao": regiao_do_grupo(v["equipe"]),
                    "inativo": v["inativo"]}
        achado = k.nomes([vid]).get(vid)
        if not achado:
            raise NaoEncontrada("vendedor não encontrado")
        grupo = k.regras.grupo_vendedor(vid)
        return {"id": vid, "nome": achado[0], "equipe": grupo, "regiao": regiao_do_grupo(grupo), "inativo": True}

    def _acoes_do_vendedor(self, vid: int) -> list[dict]:
        with self.banco.conexao() as con:
            return self._ler(con, "c.tipo = 'acao' AND (c.id IN (SELECT campanha FROM campanha_vendedores WHERE "
                                  "id_vendedor = %s) OR c.id IN (SELECT campanha FROM gestao_eventos WHERE id_vendedor = %s "
                                  "AND campanha IS NOT NULL))", [vid, vid])

    def historico(self, usuario: dict, escopo, vid) -> dict:
        """O histórico interno do vendedor: as observações, cada campanha lançada (com a base e o alvo dele), as parciais
        de cada semana e o resultado (o congelado e, até os dados passarem do fim, o provisório)."""
        try:
            vid = int(vid)
        except (TypeError, ValueError):
            raise NaoEncontrada("vendedor não encontrado") from None
        hoje = self.hoje()
        with self._contas() as k:
            ids = self.ids(escopo)
            if ids is not None and vid not in ids:
                raise NaoEncontrada("vendedor fora do seu acesso na Gestão")
            vendedor = self._info_vendedor(k, vid)
            acoes = self._acoes_do_vendedor(vid)
            if self._pendencias(k, acoes):
                acoes = self._acoes_do_vendedor(vid)
            with self.banco.conexao() as con:
                guardados = con.execute(
                    "SELECT id, campanha, tipo, texto, dados, criada_em, criada_por_nome FROM gestao_eventos "
                    "WHERE id_vendedor = %s ORDER BY criada_em, id", [vid]).fetchall()
            eventos, info_acoes = [], {}
            ultimo_resultado: dict[int, dict] = {}
            for id_, camp, tipo, texto, dados, quando, autor in guardados:
                dados = dados or {}
                dia = quando.astimezone().date()
                if tipo == "lancada" and dados.get("inicio"):
                    dia = min(dia, dt.date.fromisoformat(dados["inicio"]))
                if tipo == "resultado" and dados.get("fim"):  # entra no dia seguinte ao fim (ou ao encerrar antes)
                    dia = min(dia, dt.date.fromisoformat(dados["fim"]) + dt.timedelta(days=1))
                e = {"id": id_, "tipo": tipo, "acao": camp, "data": dia.isoformat(), "texto": texto, "autor": autor,
                     "criada_em": hora(quando), "dados": dados}
                eventos.append(e)
                if tipo == "resultado":
                    e["atual"] = False  # só o último resultado de uma campanha que não voltou a correr leva os botões
                    ultimo_resultado[camp] = e
            for c in acoes:
                desc = k.descritor(c)
                estado = self._estado(k, c, hoje, desc)
                participa = next((v for v in c["vendedores"] if v["id"] == vid), None)
                info_acoes[c["id"]] = {
                    "id": c["id"], "nome": c["nome"], "rotulo": c["rotulo"], "indicador": desc, "unidade": desc["unidade"],
                    "situacao": estado["situacao"], "inicio": c["inicio"].isoformat(), "fim": c["fim"].isoformat(),
                    "base_periodo": c["base_periodo"],
                    "base_inicio": c["base_inicio"].isoformat() if c["base_inicio"] else None,
                    "base_fim": c["base_fim"].isoformat() if c["base_fim"] else None,
                    "vendedores": len(c["vendedores"]), "arquivada": c["arquivada"], "congelado": estado["congelado"],
                    "provisorio": estado["provisorio"], "alvo_tipo": c["alvo_tipo"], "meta_padrao": c["meta_padrao"],
                    "participa": participa is not None, "aviso": estado["aviso"],
                }
                if participa is None:
                    continue
                if estado["congelado"]:
                    semanas = [{"semana": p["semana"], "ate": p["ate"], "valor": p["valor"]} for p in participa["parciais"] or []]
                elif c["inicio"] <= k.data_ref and not c["arquivada"]:
                    try:
                        semanas = [{"semana": p["semana"], "ate": p["ate"].isoformat(),
                                    "valor": _redondo(p["valores"].get(vid, (None,))[0])}
                                   for p in self._parciais(k, c, [v["id"] for v in c["vendedores"]])]
                    except SemDados:
                        semanas = []
                else:
                    semanas = []
                for p in semanas:
                    dia = dt.date.fromisoformat(p["ate"]) + dt.timedelta(days=1)
                    eventos.append({"id": None, "tipo": "parcial", "acao": c["id"], "data": dia.isoformat(), "texto": "",
                                    "autor": None, "criada_em": None, "dados": p})
                if estado["provisorio"] and not c["arquivada"] and estado["vendedores"][vid]["resultado"] is not None:
                    e = estado["vendedores"][vid]
                    dia = min(hoje, c["fim"] + dt.timedelta(days=1))
                    item = {"id": None, "tipo": "resultado", "acao": c["id"], "data": dia.isoformat(), "texto": "",
                            "autor": None, "criada_em": None, "provisorio": True,
                            "dados": {**self._retrato(c, e["base"], e["alvo"]),
                                      **{x: e.get(x) for x in ("resultado", "classe", "delta", "delta_pct", "caminho")}}}
                    eventos.append(item)
                    ultimo_resultado[c["id"]] = item
            for camp, e in ultimo_resultado.items():
                c_info = info_acoes.get(camp)
                e["atual"] = bool(c_info and c_info["participa"] and not c_info["arquivada"]
                                  and (c_info["congelado"] or e.get("provisorio")))
            # no mesmo dia, pela hora (as parciais abrem o dia; o resultado provisório fecha); empate: lançada antes
            eventos.sort(key=lambda e: (e["data"], e["criada_em"] or ("~" if e["tipo"] == "resultado" else ""),
                                        ORDEM_EVENTO.get(e["tipo"], 9), e["id"] or 0))
        return {"vendedor": vendedor, "eventos": eventos, "acoes": {str(i): a for i, a in info_acoes.items()},
                "em_vigor": sum(1 for a in info_acoes.values() if a["participa"] and a["situacao"] == "em_vigor"),
                "pode_editar": usuario["papel"] == "admin", "data_ref": self.calc.cache.info.get("data_ref"),
                "hoje": hoje.isoformat()}

    def detalhe(self, usuario: dict, escopo, id_, abrir: str | None = "padrao") -> dict:
        """A campanha com cada vendedor do acesso (base, alvo, resultado e, enquanto corre, a situação pelo ritmo, a
        abertura e a grade de preços), ou o objetivo com o andamento da equipe."""
        hoje = self.hoje()
        with self.banco.conexao() as con:
            c = self._uma(con, id_)
        nome = TIPOS_ITEM[c["tipo"]]
        try:
            k = self._contas()
        except SemDados as e:
            return {"item": {**publica(c), "situacao": situacao(c, hoje), "prazo": prazo(c, hoje)}, "linhas": [],
                    "aviso": str(e), "pode_editar": usuario["papel"] == "admin"}
        with k:
            ids = self.ids(escopo)
            if c["tipo"] == "objetivo":
                if c["regiao"] not in self.regioes(k, ids):
                    raise NaoEncontrada("objetivo não encontrado")
                aviso, andamento_, parcial = None, None, None
                try:
                    andamento_, parcial = self._objetivo(k, c, ids, self._time_padrao(k, c["regiao"]))
                except SemDados as e:
                    aviso = str(e)
                return {"item": {**publica(c), "situacao": situacao(c, hoje), "prazo": prazo(c, hoje), "parcial": parcial},
                        "andamento": andamento_, "aviso": aviso, "pode_editar": usuario["papel"] == "admin",
                        "data_ref": k.data_ref.isoformat()}
            if not self._visivel(c, ids):
                raise NaoEncontrada(f"{nome} não encontrada")
            if self._pendencias(k, [c]):
                with self.banco.conexao() as con:
                    c = self._uma(con, c["id"])
            desc = k.descritor(c)
            estado = self._estado(k, c, hoje, desc)
            a, aviso = None, estado["aviso"]
            if not estado["congelado"] and c["inicio"] <= k.data_ref:
                escala = 100 if desc["meta_em_pct"] else 1
                camp = {**c, "meta_padrao": 0, "vendedores": [
                    {"id": vid, "meta": (e["alvo"] or 0) * escala} for vid, e in estado["vendedores"].items()]}
                try:
                    areas, _ = k.areas(c)
                    a = calcular(k.cur, camp, k.regras, k.cal, k.data_ref, ids, areas, abrir)
                except SemDados as e:
                    aviso = str(e)
            vivo = {r["id"]: r for r in (a or {}).get("vendedores", [])}
            visiveis = [vid for vid in estado["vendedores"] if ids is None or vid in ids]
            nomes = k.nomes(visiveis)
            linhas = []
            for vid in visiveis:
                e, r = estado["vendedores"][vid], vivo.get(vid, {})
                nome_v, equipe = nomes.get(vid, (f"Vendedor {vid}", ""))
                res = e["resultado"] if e["resultado"] is not None or estado["congelado"] else r.get("realizado")
                linha = {"id": vid, "nome": nome_v, "equipe": NOME_EQUIPE.get(equipe, equipe), "base": e["base"],
                         "base_pendente": e["base_pendente"], "alvo": e["alvo"], "resultado": res,
                         "pct": _redondo(res / e["alvo"]) if res is not None and e["alvo"] else None,
                         "status": r.get("status"), "projecao": r.get("projecao"),
                         "numerador": r.get("numerador"), "denominador": r.get("denominador"), "dias": r.get("dias"),
                         **({"produtos": r["produtos"]} if r.get("produtos") else {}),
                         **comparar(res, e["base"], e["alvo"])}
                linhas.append(linha)
            linhas.sort(key=lambda x: (x["pct"] is None, -(x["pct"] or 0), _chave(x["nome"])))
            encerrada = estado["situacao"] == "encerrada"
            total = {"vendedores": len(linhas), "no_alvo": sum(1 for x in linhas if x["classe"] == "ok"),
                     "acima_da_base": sum(1 for x in linhas if x["classe"] in ("ok", "mid")),
                     **({k_: a["total"][k_] for k_ in ("realizado", "numerador", "denominador", "dias", "distintos")
                         if a and k_ in a["total"]})}
            item = {**publica(c), "situacao": estado["situacao"], "prazo": prazo(c, hoje),
                    "congelado": estado["congelado"], "provisorio": estado["provisorio"], "encerrada": encerrada,
                    "vendedores": [{"id": v["id"], "meta": v["meta"]} for v in c["vendedores"]
                                   if ids is None or v["id"] in ids]}
            return {"item": item, "indicador": desc, "unidade": desc["unidade"], "linhas": linhas, "total": total,
                    "abertura": (a or {}).get("abertura"), "produtos": (a or {}).get("produtos"),
                    "calendarios": (a or {}).get("calendarios"), "avisos": (a or {}).get("avisos", []),
                    "aviso": aviso, "ocultos": len(estado["vendedores"]) - len(visiveis),
                    "pode_editar": usuario["papel"] == "admin", "data_ref": k.data_ref.isoformat()}

    def criadas_por_rascunho(self, usuario: dict, rascunhos: list[str]) -> dict[str, dict]:
        """{uuid do rascunho: {id, nome, regiao}} dos rascunhos do Assistente que já viraram campanha desta pessoa."""
        uuids = [u for u in (id_valido(r) for r in rascunhos) if u]
        if not uuids:
            return {}
        with self.banco.conexao() as con:
            return {str(r): {"id": i, "nome": n, "regiao": g} for r, i, n, g in con.execute(
                "SELECT rascunho, id, nome, regiao FROM campanhas WHERE rascunho = ANY(%s::uuid[]) AND criada_por = %s",
                [uuids, usuario["id"]])}

    # --- gravação (só o administrador) -------------------------------------------------------
    @staticmethod
    def _so_admin(usuario: dict) -> None:
        if usuario.get("papel") != "admin":
            raise PermissionError("só o administrador lança e muda campanhas, objetivos e observações; quem tem a página "
                                  "acompanha")

    def _validar(self, dados: dict, tipo: str = "acao", antes: dict | None = None) -> dict:
        cur = self._cursor()
        try:
            return validar(dados, cur, self.calc.regras(), None, self._data_ref(), self._inicio_dados(), tipo,
                           self.hoje(), antes)
        finally:
            cur.close()

    def _medir_novas(self, c: dict, ids) -> dict:
        """As bases de uma campanha ainda não gravada (ou que acabou de mudar): sem guardar no recorte."""
        with contextlib.suppress(SemDados), self._contas() as k:
            return self._bases(k, {**c, "id": None}, ids)
        return {}

    def previa_base(self, usuario: dict, dados: dict, ids) -> dict:
        """A base de cada vendedor dos cards e a média deles, para o formulário da campanha (nada é gravado). dados: o
        que a campanha mede, a região, o início, o prazo e o período da base (e o id, na edição); ids: os vendedores
        dos cards (os de outra região ficam fora). As contas ficam guardadas no recorte pela definição."""
        self._so_admin(usuario)
        if not isinstance(dados, dict):
            raise ValueError("a campanha veio inválida")
        try:
            ids = sorted({int(v) for v in _lista(ids, "ids")})
        except (TypeError, ValueError):
            raise ValueError("ids: use os códigos dos vendedores") from None
        if len(ids) > MAX_PREVIA:
            raise ValueError(f"a prévia mede até {MAX_PREVIA} vendedores")
        antes = None
        if dados.get("id") not in (None, ""):
            with self.banco.conexao() as con:
                antes = self._uma(con, dados["id"], "acao")
        with self._contas() as k:
            m = _medida(dados, k.cur, k.regras, k.data_ref, self._inicio_dados(), True, self.hoje(),
                        bool(antes and antes["base_periodo"] is None))
            ids = [v for v in ids if k.regras.grupo_vendedor(v) in EQUIPES_REGIAO[m["regiao"]]]
            desc = k.descritor(m)
            chave = json.dumps([m["metrica"], m["parametros"], m["filtros"], m["metas_produto"]], sort_keys=True,
                               default=str)
            c = {**m, "id": f"previa:{chave}", "versao": 0}
            pendente = k.data_ref < m["base_fim"]
            bases, aviso = {}, None
            if not pendente:
                try:
                    bases = self._bases(k, c, ids)
                except SemDados as e:
                    aviso = str(e)
            data_ref = k.data_ref
        com_valor = [b[0] for b in bases.values() if b[0] is not None]
        return {"base_periodo": m["base_periodo"], "base_inicio": m["base_inicio"].isoformat(),
                "base_fim": m["base_fim"].isoformat(), "texto": texto_janela(m["base_periodo"], m["base_inicio"],
                                                                             m["base_fim"]),
                "pendente": pendente, "data_ref": data_ref.isoformat(), "aviso": aviso, "indicador": desc,
                "unidade": desc["unidade"], "vendedores": {str(v): _redondo(b[0]) for v, b in bases.items()},
                "media": _redondo(sum(com_valor) / len(com_valor)) if com_valor else None}

    def criar(self, usuario: dict, dados: dict, tipo: str = "acao", rascunho=None) -> dict:
        """Lança a campanha (com a base de cada vendedor, se os dados já cobrem a janela) ou cria o objetivo. rascunho: o
        uuid do rascunho do Assistente; lançar de novo o mesmo rascunho devolve a campanha que já existe."""
        self._so_admin(usuario)
        if rascunho not in (None, "") and not id_valido(rascunho):
            raise ValueError("rascunho inválido")
        rascunho = id_valido(rascunho) if rascunho else None
        d = self._validar(dados, tipo)
        hoje = self.hoje()
        bases = self._medir_novas(d, [v["id"] for v in d["vendedores"]]) if tipo == "acao" else {}
        with self.banco.conexao() as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA_ACOES])
            if rascunho:
                ja = con.execute("SELECT id, criada_por, regiao FROM campanhas WHERE rascunho = %s", [rascunho]).fetchone()
                if ja:
                    if ja[1] != usuario["id"]:
                        raise ValueError("este rascunho já virou campanha de outra pessoa")
                    return {"id": ja[0], "ja_existia": True, "regiao": ja[2]}
            id_ = con.execute(
                "INSERT INTO campanhas (tipo, nome, rotulo, descricao, regiao, status, inicio, fim, metrica, parametros, "
                "filtros, alvo_tipo, meta_padrao, base_periodo, base_inicio, base_fim, rascunho, criada_por, "
                "criada_por_nome, atualizada_por_nome) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, "
                "%s, %s, %s, %s, %s, %s, (SELECT id FROM usuarios WHERE id = %s), %s, %s) RETURNING id",
                [tipo, d["nome"], d["rotulo"], d["descricao"], d["regiao"],
                 "planejada" if hoje < d["inicio"] else "andamento", d["inicio"], d["fim"], d["metrica"],
                 json.dumps(d["parametros"], ensure_ascii=False), json.dumps(d["filtros"], ensure_ascii=False),
                 d["alvo_tipo"], d["meta_padrao"], d["base_periodo"], d["base_inicio"], d["base_fim"], rascunho,
                 usuario["id"], usuario["nome"], usuario["nome"]]).fetchone()[0]
            self._gravar_produtos(con, id_, d["metas_produto"])
            if tipo == "acao":
                c = {**d, "id": id_}
                desc = descritor(d["metrica"], d["parametros"])
                for v in d["vendedores"]:
                    self._entrar(con, c, desc, v, bases.get(v["id"]), usuario)
        return {"id": id_, "ja_existia": False, "regiao": d["regiao"]}

    def _entrar(self, con, c: dict, desc: dict, v: dict, base: tuple | None, usuario: dict) -> None:
        """Põe o vendedor na campanha (com a base, se já medida) e o evento "campanha lançada" no histórico dele."""
        valor, num, den = base or (None, None, None)
        con.execute("INSERT INTO campanha_vendedores (campanha, id_vendedor, meta, base, base_num, base_den, base_em) "
                    "VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END)",
                    [c["id"], v["id"], v["meta"], valor, num, den, base is not None])
        meta = self._meta_v(c, v)
        alvo = alvo_de(c["alvo_tipo"], desc, valor if base else None, meta)
        self._evento(con, v["id"], c["id"], "lancada",
                     {**self._retrato(c, valor if base else None, alvo), "meta": meta, "base_pendente": base is None},
                     usuario)

    @staticmethod
    def _gravar_produtos(con, id_: int, metas_produto: list[dict]) -> None:
        con.execute("DELETE FROM campanha_produtos WHERE campanha = %s", [id_])
        if metas_produto:
            with con.cursor() as cur:
                cur.executemany("INSERT INTO campanha_produtos (campanha, id_produto, meta) VALUES (%s, %s, %s)",
                                [[id_, p["id"], p["meta"]] for p in metas_produto])

    def atualizar(self, usuario: dict, id_, dados: dict, tipo: str = "acao") -> None:
        """Muda a campanha ou o objetivo. Na campanha: o texto muda sem evento; a meta vira um evento no histórico; a
        janela da base (o início ou o período da base; nas de antes da 012, também o fim) ou o que ela mede refazem a
        base de todos; vendedor que entra ganha a base e o evento de lançamento, e o que sai fica com o evento de
        saída. Campanha com resultado só muda o texto (o prazo muda pelo Prorrogar)."""
        self._so_admin(usuario)
        if not isinstance(dados, dict):
            raise ValueError("dados inválidos")
        with self.banco.conexao() as con:
            c = self._uma(con, id_, tipo)
        d = self._validar({**dados, "regiao": dados.get("regiao") or c["regiao"]}, tipo, c)
        if d["regiao"] != c["regiao"]:
            raise ValueError("a região não muda: crie outra na outra região")

        def medida(x):  # o que faz a base mudar: a janela dela e o que a campanha mede
            return (x["base_inicio"], x["base_fim"], x["metrica"], x["parametros"], x["filtros"],
                    sorted((p["id"], p["meta"]) for p in x["metas_produto"]))
        mudou_medida = medida(c) != medida(d)
        campos = ("nome", "rotulo", "descricao", "inicio", "fim", "metrica", "parametros", "filtros", "alvo_tipo",
                  "meta_padrao", "base_periodo", "base_inicio", "base_fim")
        sql = ("UPDATE campanhas SET nome = %s, rotulo = %s, descricao = %s, inicio = %s, fim = %s, metrica = %s, "
               "parametros = %s::jsonb, filtros = %s::jsonb, alvo_tipo = %s, meta_padrao = %s, base_periodo = %s, "
               "base_inicio = %s, base_fim = %s, status = CASE WHEN resultado_em IS NOT NULL THEN status "
               "WHEN %s < inicio THEN 'planejada' ELSE 'andamento' END, versao = versao + 1, atualizada_em = now(), "
               "atualizada_por_nome = %s WHERE id = %s")
        valores = [json.dumps(d[x], ensure_ascii=False) if x in ("parametros", "filtros") else d[x] for x in campos]
        if tipo == "objetivo":
            with self.banco.conexao() as con:
                if not self._travar_versao(con, c):
                    raise ValueError("o objetivo acabou de mudar; abra de novo e repita")
                con.execute(sql, [*valores, self.hoje(), usuario["nome"], c["id"]])
                self._gravar_produtos(con, c["id"], d["metas_produto"])
            return
        antes = {v["id"]: v for v in c["vendedores"]}
        depois = {v["id"]: v["meta"] for v in d["vendedores"]}
        novos = [v for v in depois if v not in antes]
        saem = [v for v in antes if v not in depois]
        mudou_alvo = ((c["alvo_tipo"], c["meta_padrao"]) != (d["alvo_tipo"], d["meta_padrao"])
                      or any(antes[v]["meta"] != depois[v] for v in depois if v in antes))
        if c["resultado_em"] and (mudou_medida or mudou_alvo or novos or saem):
            raise ValueError("a campanha já tem resultado: só o nome, o rótulo e a descrição mudam (para mudar o prazo, "
                             "use Prorrogar)")
        nova = {**c, **{x: d[x] for x in (*campos, "metas_produto")},
                "vendedores": [{**antes.get(v, {"id": v, "base": None, "base_em": None}), "meta": depois[v]}
                               for v in sorted(depois)]}
        bases = self._medir_novas(nova, list(depois) if mudou_medida else novos)
        desc = descritor(d["metrica"], d["parametros"])
        mudou = [x for x, sim in (("prazo", (c["inicio"], c["fim"]) != (d["inicio"], d["fim"])),
                                  ("base", medida(c)[:2] != medida(d)[:2]),
                                  ("indicador", medida(c)[2:] != medida(d)[2:]), ("meta", mudou_alvo)) if sim]
        with self.banco.conexao() as con:
            if not self._travar_versao(con, c):
                raise ValueError("a campanha acabou de mudar; abra de novo e repita")
            con.execute(sql, [*valores, self.hoje(), usuario["nome"], c["id"]])
            self._gravar_produtos(con, c["id"], d["metas_produto"])
            if mudou_medida:
                con.execute("UPDATE campanha_vendedores SET base = NULL, base_num = NULL, base_den = NULL, base_em = NULL "
                            "WHERE campanha = %s", [c["id"]])
            for vid in saem:
                v = antes[vid]
                con.execute("DELETE FROM campanha_vendedores WHERE campanha = %s AND id_vendedor = %s", [c["id"], vid])
                base = v["base"] if v["base_em"] else None
                self._evento(con, vid, c["id"], "removido",
                             self._retrato(c, base, alvo_de(c["alvo_tipo"], desc, base, self._meta_v(c, v))), usuario)
            for v in nova["vendedores"]:
                vid = v["id"]
                if vid in novos:
                    self._entrar(con, nova, desc, v, bases.get(vid), usuario)
                    continue
                con.execute("UPDATE campanha_vendedores SET meta = %s WHERE campanha = %s AND id_vendedor = %s",
                            [v["meta"], c["id"], vid])
                if not mudou:
                    continue
                base_antes = antes[vid]["base"] if antes[vid]["base_em"] else None
                base = bases[vid][0] if vid in bases else (None if mudou_medida else base_antes)
                pendente = mudou_medida and vid not in bases
                self._evento(con, vid, c["id"], "editada", {
                    **self._retrato(nova, base, alvo_de(d["alvo_tipo"], desc, base, self._meta_v(nova, v))),
                    "mudou": mudou, "base_pendente": pendente, "fim_antes": c["fim"].isoformat(),
                    "base_antes": _redondo(base_antes),
                    "alvo_antes": _redondo(alvo_de(c["alvo_tipo"], descritor(c["metrica"], c["parametros"]), base_antes,
                                                   self._meta_v(c, antes[vid])))}, usuario)
            self._gravar_bases(con, {**nova, "vendedores": nova["vendedores"]}, desc,
                               {vid: b for vid, b in bases.items() if vid not in novos})

    def encerrar(self, usuario: dict, id_) -> None:
        """Encerra a campanha para todos os vendedores dela: o fim vira o último dia com dados e o resultado congela
        na hora. A base continua a mesma (nas de antes da 012, a janela acompanha o novo tamanho e a base é refeita)."""
        self._so_admin(usuario)
        with self.banco.conexao() as con:
            c = self._uma(con, id_, "acao")
        if c["resultado_em"]:
            raise ValueError("a campanha já está encerrada")
        ids = [v["id"] for v in c["vendedores"]]
        with self._contas() as k:
            if k.data_ref < c["inicio"]:
                raise ValueError(f"a campanha começa em {_dm(c['inicio'])} e ainda não tem vendas: para desistir "
                                 "dela, exclua")
            fim = min(c["fim"], k.data_ref)
            nova = {**c, "fim": fim, "id": None}
            refaz = fim != c["fim"] and c["base_periodo"] is None
            if refaz:
                nova["base_inicio"], nova["base_fim"] = janela_base(c["inicio"], fim)
                bases = self._bases(k, nova, ids)
            else:
                bases = self._bases(k, nova, [v["id"] for v in c["vendedores"] if v["base_em"] is None])
            resultado = self._resultado(k, nova)
        nova["id"] = c["id"]
        if refaz:
            nova["vendedores"] = [{**v, "base": None, "base_em": None} for v in c["vendedores"]]
        desc = descritor(c["metrica"], c["parametros"])
        with self.banco.conexao() as con:
            if not self._travar_versao(con, c):
                raise ValueError("a campanha acabou de mudar; abra de novo e repita")
            con.execute("UPDATE campanhas SET fim = %s, base_inicio = %s, base_fim = %s, encerrada_em = now(), "
                        "encerrada_por_nome = %s, versao = versao + 1, atualizada_em = now(), atualizada_por_nome = %s "
                        "WHERE id = %s", [fim, nova["base_inicio"], nova["base_fim"], usuario["nome"], usuario["nome"],
                                          c["id"]])
            for v in c["vendedores"]:
                base_antes = v["base"] if v["base_em"] else None
                base = bases[v["id"]][0] if v["id"] in bases else base_antes
                self._evento(con, v["id"], c["id"], "encerrada", {
                    **self._retrato(nova, base, alvo_de(c["alvo_tipo"], desc, base, self._meta_v(c, v))),
                    "fim_antes": c["fim"].isoformat(), "base_antes": _redondo(base_antes)}, usuario)
            self._gravar_bases(con, nova, desc, bases)
            self._congelar(con, nova, desc, bases, resultado)

    def prorrogar(self, usuario: dict, id_, dias=PRORROGAR) -> None:
        """Estende a campanha para todos os vendedores dela (o padrão: 2 semanas); o resultado volta a correr (e
        congela de novo no fim). A base continua a mesma (nas de antes da 012, a janela acompanha o novo tamanho e a
        base é refeita)."""
        self._so_admin(usuario)
        try:
            dias = int(dias)
        except (TypeError, ValueError):
            raise ValueError("dias deve ser um número inteiro") from None
        if not 1 <= dias <= MAX_DIAS_ACAO:
            raise ValueError(f"prorrogue de 1 a {MAX_DIAS_ACAO} dias")
        with self.banco.conexao() as con:
            c = self._uma(con, id_, "acao")
        fim = c["fim"] + dt.timedelta(days=dias)
        if (fim - c["inicio"]).days >= MAX_DIAS_ACAO:
            raise ValueError(f"a campanha pode durar até {MAX_SEMANAS} semanas")
        refaz = c["base_periodo"] is None  # nas de antes da 012 a janela da base acompanha o prazo
        bi, bf = c["base_inicio"], c["base_fim"]
        if refaz:
            bi, bf = janela_base(c["inicio"], fim)
            _conferir_historico(c["parametros"], bi, self._inicio_dados(),
                                f"a base da campanha prorrogada ({bi:%d/%m/%Y} a {bf:%d/%m/%Y})")
        nova = {**c, "fim": fim, "base_inicio": bi, "base_fim": bf, "resultado_em": None, "encerrada_em": None,
                "vendedores": [{**v, "base": None, "base_em": None} if refaz else v for v in c["vendedores"]]}
        bases = self._medir_novas(nova, [v["id"] for v in nova["vendedores"] if v["base_em"] is None])
        desc = descritor(c["metrica"], c["parametros"])
        with self.banco.conexao() as con:
            if not self._travar_versao(con, c):
                raise ValueError("a campanha acabou de mudar; abra de novo e repita")
            con.execute("UPDATE campanhas SET fim = %s, base_inicio = %s, base_fim = %s, encerrada_em = NULL, "
                        "encerrada_por_nome = NULL, resultado_em = NULL, status = CASE WHEN %s < inicio THEN 'planejada' "
                        "ELSE 'andamento' END, versao = versao + 1, atualizada_em = now(), atualizada_por_nome = %s "
                        "WHERE id = %s", [fim, bi, bf, self.hoje(), usuario["nome"], c["id"]])
            con.execute("UPDATE campanha_vendedores SET resultado = NULL, resultado_num = NULL, resultado_den = NULL, "
                        "parciais = NULL" + (", base = NULL, base_num = NULL, base_den = NULL, base_em = NULL"
                                             if refaz else "") + " WHERE campanha = %s", [c["id"]])
            for v in c["vendedores"]:
                base_antes = v["base"] if v["base_em"] else None
                base = bases[v["id"]][0] if v["id"] in bases else (None if refaz else base_antes)
                self._evento(con, v["id"], c["id"], "prorrogada", {
                    **self._retrato(nova, base, alvo_de(c["alvo_tipo"], desc, base, self._meta_v(c, v))),
                    "dias": dias, "fim_antes": c["fim"].isoformat(), "base_antes": _redondo(base_antes),
                    "alvo_antes": _redondo(alvo_de(c["alvo_tipo"], desc, base_antes, self._meta_v(c, v))),
                    "base_pendente": v["id"] not in bases and (refaz or v["base_em"] is None)}, usuario)
            self._gravar_bases(con, nova, desc, bases)

    def arquivar(self, usuario: dict, id_, arquivada: bool = True) -> None:
        """Tira do quadro (o histórico dos vendedores continua)."""
        self._so_admin(usuario)
        with self.banco.conexao() as con:
            c = self._uma(con, id_, travar=True)
            con.execute("UPDATE campanhas SET arquivada = %s, versao = versao + 1, atualizada_em = now(), "
                        "atualizada_por_nome = %s WHERE id = %s", [bool(arquivada), usuario["nome"], c["id"]])

    def excluir(self, usuario: dict, id_) -> None:
        """Apaga a campanha ou o objetivo (e os eventos da campanha no histórico; as observações ficam)."""
        self._so_admin(usuario)
        with self.banco.conexao() as con:
            c = self._uma(con, id_, travar=True)
            con.execute("DELETE FROM campanhas WHERE id = %s", [c["id"]])

    def anotar(self, usuario: dict, vid, texto) -> dict:
        """Uma observação (combinado, conversa) no histórico do vendedor."""
        self._so_admin(usuario)
        try:
            vid = int(vid)
        except (TypeError, ValueError):
            raise ValueError("código de vendedor inválido") from None
        texto = _texto(texto, "a observação")
        if not texto:
            raise ValueError("escreva a observação")
        with contextlib.suppress(SemDados), self._contas() as k:
            if not k.nomes([vid]):
                raise ValueError(f"vendedor não encontrado: {vid}")
        with self.banco.conexao() as con:
            id_, quando = con.execute(
                "INSERT INTO gestao_eventos (id_vendedor, tipo, texto, criada_por, criada_por_nome) VALUES (%s, 'nota', "
                "%s, (SELECT id FROM usuarios WHERE id = %s), %s) RETURNING id, criada_em",
                [vid, texto, usuario["id"], usuario["nome"]]).fetchone()
        return {"id": id_, "tipo": "nota", "acao": None, "data": quando.astimezone().date().isoformat(), "texto": texto,
                "autor": usuario["nome"], "criada_em": hora(quando), "dados": {}}

    def excluir_nota(self, usuario: dict, id_) -> None:
        self._so_admin(usuario)
        try:
            id_ = int(id_)
        except (TypeError, ValueError):
            raise NaoEncontrada("observação não encontrada") from None
        with self.banco.conexao() as con:
            if not con.execute("DELETE FROM gestao_eventos WHERE id = %s AND tipo = 'nota' RETURNING id", [id_]).fetchone():
                raise NaoEncontrada("observação não encontrada; ela pode ter sido apagada")

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
    """Os tipos de indicador e os blocos da Personalizada, para o formulário."""
    return [{
        "id": t, "nome": n, "rotulo": ROTULOS.get(t, ""),
        **({"descricao": descritor(t, normalizar(t)[1])["descricao"]} if t != "personalizada" else
           {"descricao": "monte o indicador: o que medir e como"}),
    } for t, n in TIPOS.items()] + [{
        "id": "_blocos", "medidas": [{"id": k, "nome": v, "formas": list(COMBINACOES[k])} for k, v in MEDIDAS.items()],
        "formas": FORMAS, "comparar": COMPARAR, "bases": BASES, "aberturas": ABERTURAS,
        "rotulos": {f"{m}:{f}": r for (m, f), r in ROTULOS_MEDIDA.items()},
    }]


class ContextoGestao:
    """O que as ferramentas de campanhas do Assistente podem fazer, já com quem pergunta e o acesso dela na Gestão."""

    def __init__(self, gestao: Gestao, usuario: dict, escopo):
        self.gestao, self.usuario, self.escopo = gestao, usuario, escopo

    @property
    def admin(self) -> bool:
        return self.usuario["papel"] == "admin"

    def listar(self, texto: str = "", incluir_encerradas: bool = False) -> list[dict]:
        """Campanhas e objetivos que quem pergunta vê (dos vendedores do acesso), das mais novas para as mais antigas."""
        hoje = self.gestao.hoje()
        ids = self.gestao.ids(self.escopo)
        with self.gestao.banco.conexao() as con:
            itens = self.gestao._ler(con, "NOT c.arquivada", [])
        regioes = list(REGIOES)
        if ids is not None:
            with self.gestao._contas() as k:
                regioes = self.gestao.regioes(k, ids)
        itens = [c for c in itens if (self.gestao._visivel(c, ids) if c["tipo"] == "acao" else c["regiao"] in regioes)]
        if not incluir_encerradas:
            itens = [c for c in itens if situacao(c, hoje) != "encerrada"]
        palavras = _chave(texto).split()
        if palavras:
            itens = [c for c in itens if all(p in _chave(f"{c['nome']} {c['rotulo']} {c['descricao']} {c['id']}")
                                             for p in palavras)]
        itens.sort(key=lambda c: c["criada_em"], reverse=True)
        saida = []
        for c in itens[:30]:
            desc = descritor(c["metrica"], c["parametros"])
            saida.append({"id": c["id"], "tipo": TIPOS_ITEM[c["tipo"]], "nome": c["nome"], "regiao": c["regiao"],
                          "situacao": SITUACOES[situacao(c, hoje)], "inicio": c["inicio"].isoformat(),
                          "fim": c["fim"].isoformat(), "indicador": desc["nome"],
                          "meta": texto_alvo(c["alvo_tipo"], c["meta_padrao"], desc) if c["tipo"] == "acao" else
                          f"{_num(c['meta_padrao'], desc)}{'%' if desc['meta_em_pct'] else ''} para a equipe",
                          **({"vendedores": sum(1 for v in c["vendedores"] if ids is None or v["id"] in ids)}
                             if c["tipo"] == "acao" else {}),
                          "lancada_por": c["criada_por_nome"], "lancada_em": (c["criada_em"] or "")[:10],
                          **({"do_rascunho": c["rascunho"]} if c["rascunho"] else {})})
        return saida

    def andamento(self, id_) -> dict:
        r = self.gestao.detalhe(self.usuario, self.escopo, id_, "padrao")
        item = r["item"]
        ind = r.get("indicador") or item["indicador"]
        base = {
            "item": {k: item[k] for k in ("id", "tipo", "nome", "regiao", "inicio", "fim", "metrica", "parametros",
                                          "filtros", "alvo_tipo", "meta_padrao", "descricao") if k in item},
            "indicador": {k: ind[k] for k in ("nome", "descricao", "formato", "sufixo", "comportamento", "meta_em_pct",
                                              "numerador", "denominador", "base_texto") if ind.get(k)},
            "situacao": SITUACOES[item["situacao"]], "dados_ate": r.get("data_ref"),
            **({"aviso": r["aviso"]} if r.get("aviso") else {}),
        }
        if ind.get("formato") == "pct":
            base["leitura"] = "valores de efetividade/índice/% em fração (0,8 = 80%)"
        if item["tipo"] == "objetivo":
            a = r.get("andamento")
            if a is None:
                raise SemDados(r.get("aviso") or "sem dados de vendas")
            return {**base, "andamento_da_equipe": {k: a.get(k) for k in (
                "realizado", "meta", "pct", "status", "esperado", "projecao", "numerador", "denominador", "dias", "base",
                "vendedores", "situacao") if a.get(k) is not None}}
        if r.get("aviso") and not r["linhas"]:
            raise SemDados(r["aviso"])
        base["janela_da_base"] = {"inicio": item["base_inicio"], "fim": item["base_fim"],
                                  "periodo": texto_janela(item["base_periodo"], dt.date.fromisoformat(item["base_inicio"]),
                                                          dt.date.fromisoformat(item["base_fim"]))}
        base["meta"] = texto_alvo(item["alvo_tipo"], item["meta_padrao"], ind)
        campos = ("id", "nome", "equipe", "base", "alvo", "resultado", "pct", "classe", "delta", "delta_pct", "status",
                  "numerador", "denominador", "dias")
        base["vendedores"] = [{("meta" if k == "alvo" else k): x[k] for k in campos if x.get(k) is not None}
                              for x in r["linhas"]]
        base["leitura_classe"] = "ok = meta batida; mid = melhorou sobre a base sem chegar à meta; bad = não passou da base"
        base["total"] = r["total"]
        if item.get("provisorio"):
            base["resultado_provisorio"] = "a campanha acabou, mas os dados ainda não passaram do fim: o resultado pode mudar"
        if r.get("ocultos"):
            base["fora_do_acesso"] = r["ocultos"]
        if r.get("avisos"):
            base["avisos"] = r["avisos"]
        if r.get("produtos"):
            base["produtos"] = [{k: p[k] for k in ("id", "nome", "unidade", "meta", "preco", "pct", "quantidade")}
                                for p in r["produtos"]]
        if r.get("abertura"):
            ab = r["abertura"]
            base["abertura"] = {"por": ab["rotulo"], "linhas": ab["linhas"][:20], "mais": ab["mais"] + max(0, len(ab["linhas"]) - 20)}
        return base

    def propor(self, dados: dict, equipes: list[str]) -> dict:
        """Confere um rascunho de campanha e devolve com os nomes; não grava (o administrador lança pelo botão)."""
        if not self.admin:
            raise ValueError("só o administrador lança campanhas; quem tem a página acompanha as campanhas dos vendedores do acesso")
        dados = dict(dados)
        equipes = [str(e).strip().upper() for e in equipes or []]
        if any(e not in EQUIPES for e in equipes):
            raise ValueError(f"equipe deve ser {', '.join(EQUIPES)}")
        regiao = str(dados.get("regiao") or "").strip().upper()
        if equipes:  # "todos de BA": os vendedores ativos da equipe (com venda nos últimos 12 meses)
            if regiao in EQUIPES_REGIAO and any(e not in EQUIPES_REGIAO[regiao] for e in equipes):
                raise ValueError(f"a região {regiao} tem as equipes {', '.join(EQUIPES_REGIAO[regiao])}")
            da_equipe = [v["id"] for v in self.gestao.assistente.catalogo_vendedores()
                         if v["equipe"] in equipes and not v["inativo"]]
            if not da_equipe:
                raise ValueError("nenhum vendedor ativo dessas equipes")
            ja = {int(v["id"]) if isinstance(v, dict) else int(v) for v in dados.get("vendedores") or []}
            dados["vendedores"] = [*(dados.get("vendedores") or []), *(v for v in da_equipe if v not in ja)]
        d = self.gestao._validar(dados, "acao")
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
        metas = {v["id"]: Gestao._meta_v(d, v) for v in d["vendedores"]}
        bases = self.gestao._medir_novas(d, ids_v)  # a prévia da base de cada um, se os dados já cobrem a janela
        return {
            "id": novo_id(), **publica(d), "indicador": ind, "unidade": unidade, "nome_metrica": ind["nome"],
            "texto_alvo": texto_alvo(d["alvo_tipo"], d["meta_padrao"], ind),
            "texto_base": texto_janela(d["base_periodo"], d["base_inicio"], d["base_fim"]),
            "bases": {str(v): {"base": _redondo(b[0]), "alvo": _redondo(alvo_de(d["alvo_tipo"], ind, b[0], metas[v]))}
                      for v, b in bases.items()},
            "nomes": {"vendedores": {str(k): v for k, v in nomes_v.items()}, "produtos": {str(k): v for k, v in nomes_p.items()}},
        }

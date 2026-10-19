"""Indicadores das campanhas da página Gestão (bi/gestao.py): o que cada tipo de campanha mede e a conta, feita no
recorte com todos os vendedores do Assistente (view faturamento: as mesmas regras das metas).

Tipos prontos, com as contas do Power BI da empresa (MAIS VIDAS-PBIT.pbit):
- positivacao: clientes distintos com venda no período.
- mix_medio: produtos da campanha que cada cliente levou, somados, ÷ clientes positivados (com qualquer produto).
- efetividade: pedidos de venda (PEDIDOVENDAS não cancelados, do tipo PEDIDOVENDA) ÷ visitas esperadas, pelo
  vendedor da carteira do cliente. Visitas esperadas: para cada dia do período, os clientes ativos (sem "PEDIDO
  BLOQUEADO" no nome) das áreas atendidas nesse dia da semana. Os dias de cada área ficam no PostgreSQL
  (areas_atendimento); cliente em área sem dia fica fora da conta (pedidos e visitas) e entra no aviso.
- frequencia: semanas com compra, somadas cliente a cliente, ÷ clientes positivados. A semana vai de domingo a
  sábado e é cortada na virada do mês, como o WEEKNUM do Power BI.
- preco_medio: preço médio (venda líquida ÷ quantidade líquida) de cada produto contra o preço-alvo dele. Cada
  vendedor tem um índice: o que vendeu ÷ o que teria vendido as mesmas quantidades nos preços-alvo (100% = no alvo).
- personalizada: medida (faturamento, volume, clientes ou produtos) × forma (total, por cliente, % da carteira ou
  crescimento sobre um período de comparação). Faturamento, volume e mix de antes são Personalizada com forma total.

Base de clientes (quem conta): todos, novos (nenhuma compra antes do início), recuperados (compraram antes, mas a
última compra foi há N dias ou mais antes do início), ou os que nunca/já tinham comprado os produtos da campanha
antes do início. O histórico começa no início do cache ([cache] inicio).

Comportamento (como a meta e a situação são lidas):
- soma: o valor acumula no período; usa o ritmo dos dias úteis, a projeção e quanto falta por dia (bi/metas.py).
- acumula_taxa: média que cresce com o período (a frequência): o ritmo entra na situação, sem projeção.
- taxa: média ou percentual: compara direto com a meta. Com o período aberto, quem está na meta fica "no ritmo";
  "batida" só quando o período fecha.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter

from .metas import indicador as bloco_soma, status as status_soma
from .projecoes import NOME_EQUIPE, Projetor

# Filtro -> coluna da view faturamento (e da tabela produtos ou clientes, conforme o filtro).
FILTROS = {"produtos": "id_produto", "linhas": "linha", "categorias": "categoria", "grupos": "grupo",
           "ufs": "uf", "segmentos": "segmento", "areas": "area"}
FILTROS_PRODUTO = ("produtos", "linhas", "categorias", "grupos")
FILTROS_CLIENTE = ("ufs", "segmentos", "areas")

TIPOS = {
    "positivacao": "Positivação", "mix_medio": "Mix médio", "efetividade": "Efetividade",
    "frequencia": "Frequência", "preco_medio": "Preço médio", "personalizada": "Personalizada",
}
LEGADOS = {"faturamento": ("faturamento", "total"), "volume": ("volume", "total"), "mix": ("produtos", "total")}
MEDIDAS = {"faturamento": "Faturamento", "volume": "Volume", "clientes": "Clientes", "produtos": "Produtos"}
FORMAS = {"total": "Total", "por_cliente": "Por cliente", "pct_carteira": "% da carteira", "crescimento": "Crescimento"}
COMBINACOES = {  # medida -> formas aceitas (clientes no total é a Positivação)
    "faturamento": ("total", "por_cliente", "crescimento"),
    "volume": ("total", "por_cliente", "crescimento"),
    "clientes": ("total", "pct_carteira", "crescimento"),
    "produtos": ("total",),
}
COMPARAR = {"periodo_anterior": "o período anterior", "ano_anterior": "o mesmo período do ano anterior"}
BASES = {
    "todos": "todos os clientes", "novos": "clientes novos (sem compra antes do início)",
    "recuperados": "clientes recuperados", "nunca_compraram": "quem nunca tinha comprado os produtos da campanha",
    "ja_compraram": "quem já comprava os produtos da campanha",
}
BASES_COM_PRODUTO = ("nunca_compraram", "ja_compraram")
DIAS_SEM_COMPRA = 90
MAX_DIAS_SEM_COMPRA = 730
MAX_PRODUTOS_PRECO = 30
ABERTURAS = {"area": "Área comercial", "segmento": "Segmento", "produto": "Produto"}
MAX_ABERTURA = 50
SEM_DIA = "ficaram fora da efetividade: estão em áreas sem dia de atendimento (veja Gestão › Configurar)"


def _marcas(valores) -> str:
    return ",".join("?" * len(valores))


def _onde(filtros: dict, chaves=tuple(FILTROS), prefixo: str = "") -> tuple[list[str], list]:
    onde, params = [], []
    for chave in chaves:
        valores = filtros.get(chave)
        if valores:
            onde.append(f"{prefixo}{FILTROS[chave]} IN ({_marcas(valores)})")
            params += list(valores)
    return onde, params


def _redondo(v):
    if isinstance(v, float):
        return round(v, 2) if abs(v) >= 100 else round(v, 4)
    return v


def _div(a, b):
    return a / b if b else None


# --- o que a campanha mede --------------------------------------------------------------------
def normalizar(metrica, parametros=None) -> tuple[str, dict]:
    """O tipo e os parâmetros como ficam gravados. Aceita as métricas de antes (faturamento, volume, mix), que viram
    Personalizada, e Personalizada de clientes no total, que é a Positivação. Levanta ValueError (a IA lê e corrige)."""
    metrica = str(metrica or "").strip().lower()
    p = dict(parametros or {}) if isinstance(parametros or {}, dict) else None
    if p is None:
        raise ValueError("parametros deve ser um objeto")
    if metrica in LEGADOS:
        medida, forma = LEGADOS[metrica]
        metrica, p = "personalizada", {**p, "medida": medida, "forma": forma}
    if metrica not in TIPOS:
        raise ValueError(f"métrica desconhecida: {metrica!r} (use {', '.join(TIPOS)})")
    saida: dict = {}
    forma = None
    if metrica == "personalizada":
        medida = str(p.get("medida") or "").strip().lower()
        if medida not in MEDIDAS:
            raise ValueError(f"na Personalizada, a medida deve ser {', '.join(MEDIDAS)} (veio {medida!r})")
        forma = str(p.get("forma") or "total").strip().lower()
        if forma not in COMBINACOES[medida]:
            dica = " (para produtos por cliente, use o tipo mix_medio)" if medida == "produtos" else ""
            raise ValueError(f"{MEDIDAS[medida].lower()} aceita as formas {', '.join(COMBINACOES[medida])}{dica}")
        if medida == "clientes" and forma == "total":
            metrica = "positivacao"
        else:
            saida = {"medida": medida, "forma": forma}
            if forma == "crescimento":
                comparar = str(p.get("comparar") or "periodo_anterior").strip().lower()
                if comparar not in COMPARAR:
                    raise ValueError(f"comparar deve ser {', '.join(COMPARAR)}")
                saida["comparar"] = comparar
    base = str(p.get("clientes") or "todos").strip().lower()
    if base not in BASES:
        raise ValueError(f"base de clientes desconhecida: {base!r} (use {', '.join(BASES)})")
    if base != "todos" and (metrica in ("efetividade", "preco_medio") or forma in ("pct_carteira", "crescimento")):
        raise ValueError(f"{nome_do(metrica, saida)} conta todos os clientes (sem base de clientes)")
    if metrica in ("positivacao", "mix_medio", "frequencia") or forma in ("total", "por_cliente"):
        saida["clientes"] = base
    if base == "recuperados":
        try:
            dias = int(p.get("dias_sem_compra") or DIAS_SEM_COMPRA)
        except (TypeError, ValueError):
            raise ValueError("dias_sem_compra deve ser um número inteiro de dias") from None
        if not 1 <= dias <= MAX_DIAS_SEM_COMPRA:
            raise ValueError(f"dias_sem_compra deve ficar entre 1 e {MAX_DIAS_SEM_COMPRA}")
        saida["dias_sem_compra"] = dias
    return metrica, saida


def nome_do(metrica: str, p: dict) -> str:
    if metrica != "personalizada":
        return TIPOS[metrica]
    medida, forma = p.get("medida"), p.get("forma")
    if forma == "por_cliente":
        return {"faturamento": "Venda média por cliente", "volume": "Volume por cliente"}[medida]
    if forma == "pct_carteira":
        return "Cobertura da carteira"
    if forma == "crescimento":
        return {"faturamento": "Crescimento do faturamento", "volume": "Crescimento do volume",
                "clientes": "Crescimento da positivação"}[medida]
    return {"faturamento": "Faturamento", "volume": "Volume", "produtos": "Mix de produtos"}[medida]


def texto_base(p: dict) -> str:
    base = p.get("clientes", "todos")
    if base == "recuperados":
        return f"clientes recuperados (sem compra há {p.get('dias_sem_compra', DIAS_SEM_COMPRA)} dias ou mais antes do início)"
    return BASES[base]


def descritor(metrica: str, p: dict, unidade: str | None = None) -> dict:
    """O que a página e a IA precisam para mostrar a campanha: nome, como formatar os valores e como ler a meta.
    formato: moeda, quantidade (com a unidade), clientes, produtos, pct (valor em fração) ou razao (com sufixo)."""
    medida, forma = p.get("medida"), p.get("forma")
    d = {"tipo": metrica, "medida": medida, "forma": forma, "nome": nome_do(metrica, p), "comportamento": "soma",
         "formato": "moeda", "sufixo": "", "casas": 0, "unidade": unidade or "", "sentido": 1, "meta_em_pct": False,
         "numerador": None, "denominador": None, "aberturas": ["area", "segmento", "produto"], "abrir_padrao": None,
         "base": p.get("clientes", "todos"), "base_texto": texto_base(p) if p.get("clientes") else "",
         "comparar": p.get("comparar")}
    if metrica == "positivacao":
        d.update(formato="clientes", descricao="clientes distintos com venda no período", rotulo_meta="clientes por vendedor")
    elif metrica == "mix_medio":
        d.update(formato="razao", casas=2, sufixo="produtos por cliente", comportamento="taxa",
                 descricao="produtos da campanha levados por cliente positivado (média, como no Power BI)",
                 rotulo_meta="produtos por cliente", numerador="Produtos levados (somando os clientes)",
                 denominador="Clientes positivados", aberturas=["area", "segmento"])
    elif metrica == "efetividade":
        d.update(formato="pct", casas=1, comportamento="taxa", meta_em_pct=True,
                 descricao="pedidos ÷ visitas esperadas pelos dias de atendimento das áreas, pela carteira do vendedor",
                 rotulo_meta="% de efetividade", numerador="Pedidos", denominador="Visitas esperadas",
                 aberturas=["area", "segmento"], abrir_padrao="area")
    elif metrica == "frequencia":
        d.update(formato="razao", casas=2, sufixo="semanas por cliente", comportamento="acumula_taxa",
                 descricao="semanas com compra por cliente positivado (média, como no Power BI)",
                 rotulo_meta="semanas com compra por cliente", numerador="Semanas com compra (somando os clientes)",
                 denominador="Clientes positivados", aberturas=["segmento", "area"], abrir_padrao="segmento")
    elif metrica == "preco_medio":
        d.update(formato="pct", casas=1, comportamento="taxa", meta_em_pct=True,
                 descricao="preço médio de cada produto contra o preço-alvo; o índice compara o vendido com o que "
                           "seria nos preços-alvo (100% = no alvo)",
                 rotulo_meta="100% = no preço-alvo", numerador="Vendido", denominador="Nos preços-alvo",
                 aberturas=[])
    elif forma == "pct_carteira":
        d.update(formato="pct", casas=1, comportamento="taxa", meta_em_pct=True,
                 descricao="clientes ativos da carteira do vendedor que compraram (de qualquer vendedor)",
                 rotulo_meta="% da carteira", numerador="Clientes da carteira que compraram",
                 denominador="Clientes ativos da carteira", aberturas=["area", "segmento"])
    else:
        formato = {"faturamento": "moeda", "volume": "quantidade", "clientes": "clientes", "produtos": "produtos"}[medida]
        d.update(formato=formato)
        if forma == "crescimento":
            d.update(meta_em_pct=True, aberturas=[], rotulo_meta=f"% de crescimento sobre {COMPARAR[p['comparar']]}",
                     descricao=f"{MEDIDAS[medida].lower()} no período, contra {COMPARAR[p['comparar']]}")
        elif forma == "por_cliente":
            d.update(comportamento="taxa", casas=2 if medida == "faturamento" else 1, sufixo="por cliente",
                     numerador=MEDIDAS[medida], denominador="Clientes positivados",
                     descricao=f"{MEDIDAS[medida].lower()} ÷ clientes positivados",
                     rotulo_meta="por cliente")
        else:
            d.update(descricao={"faturamento": "venda líquida (descontando as devoluções), em R$, como nas metas",
                                "volume": "quantidade vendida, na unidade dos produtos (descontando as devoluções)",
                                "produtos": "produtos distintos vendidos no período"}[medida],
                     rotulo_meta={"faturamento": "R$ por vendedor", "volume": "quantidade por vendedor",
                                  "produtos": "produtos por vendedor"}[medida])
    if d["base_texto"] and d["base"] != "todos":
        d["descricao"] += f"; conta {d['base_texto']}"
    return d


def filtros_aceitos(metrica: str, p: dict) -> tuple[str, ...]:
    if metrica in ("efetividade", "preco_medio"):
        return FILTROS_CLIENTE
    return tuple(FILTROS)


def periodo_base(inicio: dt.date, fim: dt.date, comparar: str) -> tuple[dt.date, dt.date]:
    """Período de comparação do crescimento. Período anterior: campanha de meses cheios compara com os mesmos meses
    logo antes; senão, com o mesmo número de dias logo antes do início."""
    if comparar == "ano_anterior":
        def antes(d):
            try:
                return d.replace(year=d.year - 1)
            except ValueError:  # 29 de fevereiro
                return d.replace(year=d.year - 1, day=28)
        return antes(inicio), antes(fim)
    if inicio.day == 1 and (fim + dt.timedelta(days=1)).day == 1:
        meses = (fim.year - inicio.year) * 12 + fim.month - inicio.month + 1
        n = inicio.year * 12 + inicio.month - 1 - meses
        return dt.date(n // 12, n % 12 + 1, 1), inicio - dt.timedelta(days=1)
    dias = (fim - inicio).days + 1
    return inicio - dt.timedelta(days=dias), inicio - dt.timedelta(days=1)


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


# --- situação ---------------------------------------------------------------------------------
def calendario_periodo(cal, inicio: dt.date, fim: dt.date, regiao: str, data_ref: dt.date) -> dict:
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


def bloco_taxa(valor, meta, situacao: str, sentido: int = 1) -> dict:
    """Média ou percentual contra a meta, sem ritmo nem projeção. sentido -1: menor é melhor."""
    if not meta:
        st = "sem_meta"
    elif valor is None:
        st = "no_ritmo" if situacao == "futuro" else "sem_dados"
    else:
        # com a precisão que a página mostra (0,1%): "100,0%" não fica em atenção por 99,997%
        alcance = round(valor / meta if sentido > 0 else (meta / valor if valor else float("inf")), 3)
        if situacao == "futuro":
            st = "no_ritmo"
        elif alcance >= 1:
            st = "batida" if situacao == "fechado" else "no_ritmo"
        else:
            st = "atencao" if alcance >= 0.9 else "abaixo"
    return {"meta": meta, "realizado": valor, "pct": _div(valor, meta) if valor is not None else None, "status": st,
            "projecao": None, "projecao_pct": None, "falta": None, "falta_por_dia": None, "esperado": None}


def bloco(comportamento: str, valor, meta, cal: dict, sentido: int = 1) -> dict:
    if comportamento == "soma":
        return bloco_soma(valor or 0.0, meta, cal)
    if valor is None or comportamento == "taxa":
        return bloco_taxa(valor, meta, cal["situacao"], sentido)
    b = bloco_soma(valor, meta, cal)  # acumula_taxa: o ritmo vale, a projeção linear não
    return {**b, "projecao": None, "projecao_pct": None, "falta": None, "falta_por_dia": None}


# --- medição ----------------------------------------------------------------------------------
_VENDA = "tipo = 'venda'"
_CLIENTE = "tipo_cliente = 'CLIENTE'"
_POSITIVADOS = f"COUNT(DISTINCT id_cliente) FILTER (WHERE {_VENDA})"
_SEMANA = "(day(data) - 1 + dayofweek(date_trunc('month', data))) // 7"  # dayofweek: domingo = 0


def _base(c: dict, inicio: dt.date) -> tuple[list[str], list]:
    """Trecho do WHERE (sobre a view faturamento) com a base de clientes da campanha."""
    p = c["parametros"]
    base = p.get("clientes", "todos")
    if base == "todos":
        return [], []
    if base == "novos":
        return [_CLIENTE, "id_cliente NOT IN (SELECT id_cliente FROM _vendas WHERE tipo_cliente = 'CLIENTE' "
                          "AND id_cliente IS NOT NULL AND data < ?)"], [inicio]
    if base == "recuperados":
        limite = inicio - dt.timedelta(days=p.get("dias_sem_compra", DIAS_SEM_COMPRA))
        return [_CLIENTE, "id_cliente IN (SELECT id_cliente FROM _vendas WHERE tipo_cliente = 'CLIENTE' AND data < ? "
                          "GROUP BY 1 HAVING MAX(data) <= ?)"], [inicio, limite]
    onde, params = _onde(c["filtros"], FILTROS_PRODUTO, "p.")
    sub = ("SELECT v.id_cliente FROM _vendas v JOIN produtos p USING (id_produto) WHERE v.tipo_cliente = 'CLIENTE' "
           "AND v.id_cliente IS NOT NULL AND v.data < ?" + "".join(f" AND {o}" for o in onde))
    return [_CLIENTE, f"id_cliente {'NOT IN' if base == 'nunca_compraram' else 'IN'} ({sub})"], [inicio, *params]


def _expressoes(c: dict) -> tuple[str, str | None, list, list[str], list]:
    """(numerador, denominador, parâmetros do SELECT, WHERE extra, parâmetros do WHERE extra) na view faturamento."""
    metrica, p, filtros = c["metrica"], c["parametros"], c["filtros"]
    if metrica == "positivacao":
        return f"COUNT(DISTINCT id_cliente) FILTER (WHERE {_VENDA} AND {_CLIENTE})", None, [], *_onde(filtros)
    if metrica == "mix_medio":  # os filtros de produto só no numerador: o denominador são todos os positivados
        onde_p, params_p = _onde(filtros, FILTROS_PRODUTO)
        filtro = "".join(f" AND {o}" for o in onde_p)
        onde_c, params_c = _onde(filtros, FILTROS_CLIENTE)
        return (f"COUNT(DISTINCT (id_cliente, id_produto)) FILTER (WHERE {_VENDA}{filtro})", _POSITIVADOS, params_p,
                [_CLIENTE, *onde_c], params_c)
    if metrica == "frequencia":
        onde, params = _onde(filtros)
        return (f"COUNT(DISTINCT (id_cliente, year(data), month(data), {_SEMANA})) FILTER (WHERE {_VENDA})",
                _POSITIVADOS, [], [_CLIENTE, *onde], params)
    medida, forma = p["medida"], p["forma"]
    soma = {"faturamento": "SUM(valor_liquido)", "volume": "SUM(quantidade)",
            "clientes": f"COUNT(DISTINCT id_cliente) FILTER (WHERE {_VENDA} AND {_CLIENTE})",
            "produtos": f"COUNT(DISTINCT id_produto) FILTER (WHERE {_VENDA})"}[medida]
    onde, params = _onde(filtros)
    if forma == "por_cliente":
        return soma, _POSITIVADOS, [], [_CLIENTE, *onde], params
    return soma, None, [], onde, params


def _numero(x) -> float:
    return float(x or 0)


def _fat(cur, c: dict, ids: list[int], inicio: dt.date, ate: dt.date, abrir: str | None = None) -> dict:
    """Os indicadores da view faturamento: por vendedor e o total (sem repetir clientes), e a abertura."""
    num, den, params_sel, onde_extra, params_extra = _expressoes(c)
    onde_b, params_b = _base(c, inicio)
    onde = ["data BETWEEN ? AND ?", f"id_vendedor IN ({_marcas(ids)})", *onde_extra, *onde_b]
    params = [inicio, ate, *ids, *params_extra, *params_b]
    where = " AND ".join(onde)
    den_sql = den or "NULL"
    linhas = cur.execute(f"SELECT GROUPING(id_vendedor), id_vendedor, {num}, {den_sql} FROM faturamento WHERE {where} "
                         f"GROUP BY GROUPING SETS ((id_vendedor), ())", [*params_sel, *params]).fetchall()
    r = {"vend": {}, "total": {"num": 0.0, "den": 0.0 if den else None}}
    for g, vid, n, d in linhas:
        valor = {"num": _numero(n), "den": _numero(d) if den else None}
        if g:
            r["total"] = valor
        else:
            r["vend"][vid] = valor
    if abrir:
        chave, nome = {"area": ("COALESCE(area, '(sem área)')",) * 2, "segmento": ("COALESCE(segmento, '(sem segmento)')",) * 2,
                       "produto": ("id_produto", "any_value(produto)")}[abrir]
        r["abertura"] = [{"chave": k, "nome": nm, "num": _numero(n), "den": _numero(d) if den else None}
                         for k, nm, n, d in cur.execute(
                             f"SELECT {chave}, {nome}, {num}, {den_sql} FROM faturamento WHERE {where} GROUP BY ALL",
                             [*params_sel, *params]).fetchall()]
    return r


def _carteira(c: dict, ids: list[int]) -> tuple[str, list]:
    onde, params = _onde(c["filtros"], FILTROS_CLIENTE, "k.")
    return " AND ".join([f"k.id_vendedor_carteira IN ({_marcas(ids)})", *onde]), [*ids, *params]


def _pct_carteira(cur, c: dict, ids: list[int], inicio: dt.date, ate: dt.date, abrir: str | None = None) -> dict:
    """Clientes ativos da carteira que compraram (de qualquer vendedor) ÷ clientes ativos da carteira."""
    onde_p, params_p = _onde(c["filtros"], FILTROS_PRODUTO)
    onde_k, params_k = _carteira(c, ids)
    comprou = (f"SELECT DISTINCT id_cliente FROM faturamento WHERE {_VENDA} AND {_CLIENTE} AND data BETWEEN ? AND ?"
               + "".join(f" AND {o}" for o in onde_p))
    params = [inicio, ate, *params_p, *params_k]
    base = (f"FROM clientes k LEFT JOIN ({comprou}) f ON f.id_cliente = k.id_cliente "
            f"WHERE NOT COALESCE(k.inativo, false) AND {onde_k}")
    r = {"vend": {}, "total": {"num": 0.0, "den": 0.0}}
    for g, vid, n, d in cur.execute(f"SELECT GROUPING(k.id_vendedor_carteira), k.id_vendedor_carteira, "
                                    f"COUNT(f.id_cliente), COUNT(*) {base} "
                                    f"GROUP BY GROUPING SETS ((k.id_vendedor_carteira), ())", params).fetchall():
        valor = {"num": _numero(n), "den": _numero(d)}
        if g:
            r["total"] = valor
        else:
            r["vend"][vid] = valor
    if abrir in ("area", "segmento"):
        col = f"COALESCE(k.{abrir}, '(sem {'área' if abrir == 'area' else 'segmento'})')"
        r["abertura"] = [{"chave": k, "nome": k, "num": _numero(n), "den": _numero(d)} for k, n, d in cur.execute(
            f"SELECT {col}, COUNT(f.id_cliente), COUNT(*) {base} GROUP BY 1", params).fetchall()]
    return r


def visitas_por_area(inicio: dt.date, ate: dt.date, areas: dict[int, list[int]]) -> dict[int, int]:
    """Quantas visitas cada cliente de cada área deveria receber no período (os dias de atendimento que caem nele)."""
    n = Counter()
    d = inicio
    while d <= ate:
        n[d.isoweekday()] += 1
        d += dt.timedelta(days=1)
    return {a: sum(n[x] for x in dias) for a, dias in areas.items() if dias}


def _efetividade(cur, c: dict, ids: list[int], inicio: dt.date, ate: dt.date, areas: dict[int, list[int]],
                 abrir: str | None = None) -> dict:
    """Pedidos ÷ visitas esperadas, pelo vendedor da carteira. Cliente em área sem linha em areas_atendimento
    (pendente) fica fora e entra no aviso; área com dias vazios (não atendida) fica fora sem aviso."""
    peso = visitas_por_area(inicio, ate, areas)
    onde_k, params_k = _carteira(c, ids)
    grupos = ("k.id_vendedor_carteira, k.id_area, COALESCE(k.area, '(sem área)'), "
              "COALESCE(k.segmento, '(sem segmento)')")
    clientes = [((v, a, ar, s), n) for v, a, ar, s, n in cur.execute(
        f"SELECT {grupos}, COUNT(*) FILTER (WHERE NOT COALESCE(k.inativo, false) AND NOT "
        f"contains(upper(COALESCE(k.cliente, '')), 'PEDIDO BLOQUEADO')) FROM clientes k WHERE {onde_k} "
        f"GROUP BY 1, 2, 3, 4", params_k).fetchall()]
    pedidos = {(v, a, ar, s): n for v, a, ar, s, n in cur.execute(
        f"SELECT {grupos}, SUM(p.pedidos) FROM _pedidos_venda p JOIN clientes k ON k.id_cliente = p.id_cliente "
        f"WHERE p.tipo_cliente = 'CLIENTE' AND p.data BETWEEN ? AND ? AND p.cancelada = 0 "
        f"AND p.tipopedido = 'PEDIDOVENDA' AND {onde_k} GROUP BY 1, 2, 3, 4", [inicio, ate, *params_k]).fetchall()}
    vend: dict = {}
    total = {"num": 0.0, "den": 0.0}
    por: dict = {}
    sem_dia = 0
    for (v, area_id, area, seg), visitaveis in clientes:
        if area_id not in areas:  # área pendente
            sem_dia += visitaveis
            continue
        if area_id not in peso:  # área marcada como não atendida
            continue
        n_ped = _numero(pedidos.get((v, area_id, area, seg)))
        n_vis = float(visitaveis * peso[area_id])
        alvos = [vend.setdefault(v, {"num": 0.0, "den": 0.0}), total]
        if abrir:
            alvos.append(por.setdefault(area if abrir == "area" else seg, {"num": 0.0, "den": 0.0}))
        for alvo in alvos:
            alvo["num"] += n_ped
            alvo["den"] += n_vis
    r = {"vend": vend, "total": total, "avisos": []}
    if sem_dia:
        r["avisos"].append(f"{sem_dia} cliente{'s' if sem_dia != 1 else ''} ativo{'s' if sem_dia != 1 else ''} da "
                           f"carteira {SEM_DIA}")
    if abrir in ("area", "segmento"):
        r["abertura"] = [{"chave": k, "nome": k, **v} for k, v in por.items()]
    return r


def _precos(cur, c: dict, ids: list[int], inicio: dt.date, ate: dt.date) -> dict:
    """Preço médio de cada produto por vendedor e no total, e o índice: vendido ÷ quantidades nos preços-alvo."""
    alvo = {m["id"]: m["meta"] for m in c["metas_produto"]}
    prods = sorted(alvo)
    onde_c, params_c = _onde(c["filtros"], FILTROS_CLIENTE)
    onde = ["data BETWEEN ? AND ?", f"id_vendedor IN ({_marcas(ids)})", f"id_produto IN ({_marcas(prods)})", *onde_c]
    linhas = cur.execute(
        f"SELECT GROUPING(id_vendedor), id_vendedor, id_produto, SUM(valor_liquido), SUM(quantidade) FROM faturamento "
        f"WHERE {' AND '.join(onde)} GROUP BY GROUPING SETS ((id_vendedor, id_produto), (id_produto))",
        [inicio, ate, *ids, *prods, *params_c]).fetchall()
    info = {p: (n, (u or "").strip().upper()) for p, n, u in cur.execute(
        f"SELECT id_produto, produto, unidade FROM produtos WHERE id_produto IN ({_marcas(prods)})", prods).fetchall()}

    def item(pid, valor, qtd):
        preco = valor / qtd if qtd > 0 else None
        return {"id": pid, "nome": info.get(pid, (f"Produto {pid}", ""))[0], "unidade": info.get(pid, ("", ""))[1],
                "meta": alvo[pid], "valor": _redondo(valor), "quantidade": _redondo(qtd),
                "preco": _redondo(preco) if preco is not None else None,
                "pct": preco / alvo[pid] if preco is not None else None}

    por_vend: dict = {}
    total: dict = {}
    for g, vid, pid, valor, qtd in linhas:
        (total if g else por_vend.setdefault(vid, {}))[pid] = item(pid, _numero(valor), _numero(qtd))

    def indice(itens: dict) -> dict:
        com = [i for i in itens.values() if i["preco"] is not None]
        return {"num": sum(i["valor"] for i in com), "den": sum(i["quantidade"] * i["meta"] for i in com),
                "produtos": [itens.get(p) or item(p, 0.0, 0.0) for p in prods]}

    return {"vend": {v: indice(por_vend.get(v, {})) for v in ids}, "total": indice(total)}


def medir(cur, c: dict, ids: list[int], inicio: dt.date, ate: dt.date, areas: dict | None = None,
          abrir: str | None = None) -> dict:
    """Numerador e denominador por vendedor e no total (e a abertura pedida, e os avisos)."""
    metrica, forma = c["metrica"], c["parametros"].get("forma")
    if metrica == "efetividade":
        return _efetividade(cur, c, ids, inicio, ate, areas or {}, abrir)
    if metrica == "preco_medio":
        return _precos(cur, c, ids, inicio, ate)
    if forma == "pct_carteira":
        return _pct_carteira(cur, c, ids, inicio, ate, abrir)
    r = _fat(cur, c, ids, inicio, ate, abrir if forma != "crescimento" else None)
    if forma == "crescimento":
        de, a = periodo_base(c["inicio"], c["fim"], c["parametros"]["comparar"])
        base = _fat(cur, c, ids, de, a)
        for vid, v in r["vend"].items():
            v["base"] = base["vend"].get(vid, {}).get("num", 0.0)
        r["base"] = {vid: v["num"] for vid, v in base["vend"].items()}
    return r


# --- o andamento ------------------------------------------------------------------------------
def _ordem(r: dict):
    return (r["pct"] is None, -(r["pct"] or 0), r["realizado"] is None, -(r["realizado"] or 0), r["nome"])


def calcular(cur, campanha: dict, regras, cal, data_ref: dt.date, permitidos: frozenset[int] | None,
             areas: dict | None = None, abrir: str | None = None) -> dict:
    """Realizado, meta, % e situação de cada vendedor da campanha (só os do acesso de quem vê) e o total. areas: os
    dias de atendimento ({id_area: [dias ISO]}), para a efetividade. abrir: area, segmento ou produto ("padrao" = a
    abertura que o tipo mostra de saída; None = nenhuma)."""
    metrica, p = normalizar(campanha["metrica"], campanha.get("parametros"))
    c = {**campanha, "metrica": metrica, "parametros": p, "metas_produto": campanha.get("metas_produto") or []}
    inicio, fim = c["inicio"], c["fim"]
    participantes = c["vendedores"]
    visiveis = [v for v in participantes if permitidos is None or v["id"] in permitidos]
    ate = min(fim, data_ref)
    ids = [v["id"] for v in visiveis]
    unidade = ""
    if p.get("medida") == "volume":
        achadas = unidades(cur, c["filtros"], data_ref)
        unidade = achadas[0] if len(achadas) == 1 else ("" if not achadas else "/".join(achadas))
    desc = descritor(metrica, p, unidade)
    if abrir == "padrao":
        abrir = desc["abrir_padrao"]
    abrir = abrir if abrir in desc["aberturas"] else None
    comportamento, pct_meta = desc["comportamento"], desc["meta_em_pct"]
    crescimento = p.get("forma") == "crescimento"
    m = {"vend": {}, "total": {"num": 0.0, "den": None}, "avisos": []}
    if ids:  # antes do início dá tudo zero, mas o crescimento já mostra a base e a meta
        m = medir(cur, c, ids, inicio, ate, areas, abrir)

    def valor(x: dict | None):
        if x is None:
            return 0.0 if comportamento == "soma" else None
        return x["num"] if comportamento == "soma" else _div(x["num"], x["den"])

    info = {}
    if ids:
        info = {v: (n, e) for v, n, e in cur.execute(
            f"SELECT id_vendedor, vendedor, equipe FROM vendedores WHERE id_vendedor IN ({_marcas(ids)})", ids).fetchall()}
    calendarios: dict[str, dict] = {}
    linhas = []
    for v in visiveis:
        vid = v["id"]
        grupo = regras.grupo_vendedor(vid)
        regiao = Projetor._regiao(regras, vid, grupo)
        cal_v = calendarios.get(regiao) or calendarios.setdefault(regiao, calendario_periodo(cal, inicio, fim, regiao, data_ref))
        meta = c["meta_padrao"] if v["meta"] is None else v["meta"]
        medido = m["vend"].get(vid)
        extra = {}
        if metrica == "preco_medio":
            meta_conta = 1.0
        elif crescimento:
            base = (medido or {}).get("base", m.get("base", {}).get(vid, 0.0))
            meta_conta = base * (1 + meta / 100) if base and meta else 0.0
            extra = {"base": _redondo(base), "crescimento": meta}
        else:
            meta_conta = meta / 100 if pct_meta else meta
        ind = bloco(comportamento, valor(medido), meta_conta, cal_v)
        nome, equipe = info.get(vid, (f"Vendedor {vid}", NOME_EQUIPE.get(grupo, grupo)))
        if desc["numerador"]:
            extra.update(numerador=_redondo((medido or {}).get("num", 0.0)), denominador=_redondo((medido or {}).get("den", 0.0)))
        if metrica == "preco_medio":
            extra["produtos"] = (medido or {}).get("produtos") or []
        linhas.append({"id": vid, "nome": nome, "equipe": equipe, "regiao": regiao, "meta_individual": v["meta"] is not None,
                       **{k: _redondo(x) for k, x in ind.items()}, **extra})
    linhas.sort(key=_ordem)
    situacao = next(iter(calendarios.values()))["situacao"] if calendarios else (
        "fechado" if data_ref >= fim else ("futuro" if data_ref < inicio else "aberto"))
    total = _total(desc, linhas, m, calendarios, situacao, valor)
    saida = {
        "metrica": metrica, "nome_metrica": desc["nome"], "unidade": unidade, "indicador": desc,
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat(), "ate": ate.isoformat() if ate >= inicio else None},
        "data_ref": data_ref.isoformat(), "situacao": situacao,
        "calendarios": {k: {**x, "ritmo": round(x["ritmo"], 4)} for k, x in calendarios.items()},
        "total": total, "vendedores": linhas, "ocultos": len(participantes) - len(visiveis),
        "avisos": m.get("avisos", []),
    }
    if metrica == "preco_medio":
        saida["produtos"] = m["total"].get("produtos") or []
    if crescimento:
        de, a = periodo_base(inicio, fim, p["comparar"])
        saida["periodo_base"] = {"inicio": de.isoformat(), "fim": a.isoformat()}
    if abrir and "abertura" in m:
        saida["abertura"] = _abertura(abrir, m["abertura"], valor)
    return saida


def _total(desc: dict, linhas: list[dict], m: dict, calendarios: dict, situacao: str, valor) -> dict:
    com_meta = [r for r in linhas if r["meta"]]
    if desc["comportamento"] == "soma":
        meta_total = sum(r["meta"] for r in com_meta)
        real_meta = sum(r["realizado"] for r in com_meta)
        ritmo = (sum(r["meta"] * calendarios[r["regiao"]]["ritmo"] for r in com_meta) / meta_total) if meta_total else 0.0
        t = {
            "realizado": _redondo(sum(r["realizado"] for r in linhas)), "meta": _redondo(meta_total),
            "pct": real_meta / meta_total if meta_total else None, "status": status_soma(real_meta, meta_total, ritmo, situacao),
            "esperado": _redondo(meta_total * (1.0 if situacao == "fechado" else ritmo)) if meta_total else None,
            "bateram": sum(1 for r in com_meta if r["realizado"] >= r["meta"]), "com_meta": len(com_meta),
            "vendedores": len(linhas),
        }
        if desc["formato"] in ("clientes", "produtos"):  # sem repetir entre vendedores
            t["distintos"] = int(m["total"]["num"] or 0)
        if desc["forma"] == "crescimento":
            t["base"] = _redondo(sum(r.get("base") or 0 for r in linhas))
        return t
    realizado = valor(m["total"]) if linhas else None
    pesos = [(r["meta"], (r.get("denominador") or 0)) for r in com_meta]
    soma_pesos = sum(d for _, d in pesos)
    if desc["tipo"] == "preco_medio":
        meta_total = 1.0 if com_meta else 0.0
    elif soma_pesos:
        meta_total = sum(mt * d for mt, d in pesos) / soma_pesos
    else:
        meta_total = sum(mt for mt, _ in pesos) / len(pesos) if pesos else 0.0
    if desc["comportamento"] == "acumula_taxa" and realizado is not None and meta_total:
        ritmo = sum(r["meta"] * calendarios[r["regiao"]]["ritmo"] for r in com_meta) / sum(r["meta"] for r in com_meta)
        st = status_soma(realizado, meta_total, ritmo, situacao)
        esperado = meta_total * (1.0 if situacao == "fechado" else ritmo)
    else:
        st, esperado = bloco_taxa(realizado, meta_total, situacao)["status"], None
    t = {
        "realizado": _redondo(realizado), "meta": _redondo(meta_total), "pct": _div(realizado, meta_total) if realizado is not None else None,
        "status": st, "esperado": _redondo(esperado), "com_meta": len(com_meta), "vendedores": len(linhas),
        "bateram": sum(1 for r in com_meta if r["pct"] is not None and round(r["pct"], 3) >= 1),
    }
    if desc["numerador"]:
        t.update(numerador=_redondo(m["total"].get("num", 0.0)), denominador=_redondo(m["total"].get("den") or 0.0))
    return t


def _abertura(por: str, linhas: list[dict], valor) -> dict:
    itens = [{"chave": x["chave"], "nome": x["nome"], "valor": _redondo(valor(x)), "numerador": _redondo(x["num"]),
              **({"denominador": _redondo(x["den"])} if x.get("den") is not None else {})} for x in linhas]
    itens.sort(key=lambda x: (x["valor"] is None, -(x["valor"] or 0), str(x["nome"])))
    return {"por": por, "rotulo": ABERTURAS[por], "linhas": itens[:MAX_ABERTURA], "mais": max(0, len(itens) - MAX_ABERTURA)}

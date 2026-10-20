"""Indicadores das campanhas da página Gestão (bi/gestao.py): o que cada tipo de campanha mede e a conta, feita no
recorte com todos os vendedores do Assistente (view faturamento: as mesmas regras das metas).

Tipos prontos, com as contas do Power BI da empresa (MAIS VIDAS-PBIT.pbit):
- positivacao: clientes distintos com venda no período.
- mix_medio: produtos da campanha que cada cliente levou, somados, ÷ clientes positivados (com qualquer produto).
- efetividade: a média da efetividade de cada dia do período, pelo vendedor da carteira do cliente. A de um dia:
  pedidos de venda do dia (PEDIDOVENDAS não cancelados, do tipo PEDIDOVENDA) ÷ visitas esperadas no dia, que são os
  clientes ativos (sem "PEDIDO BLOQUEADO" no nome) das áreas atendidas nesse dia da semana. Dia sem visita esperada
  (o fim de semana, por exemplo) fica fora da média, com os pedidos dele (decisão do usuário: o Power BI divide os
  pedidos do período pelas visitas do período). Os dias de cada área ficam no PostgreSQL (areas_atendimento);
  cliente em área sem dia fica fora da conta (pedidos e visitas) e entra no aviso.
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
        d.update(formato="pct", casas=1, comportamento="taxa", meta_em_pct=True, media_diaria=True,
                 descricao="média da efetividade de cada dia (pedidos do dia ÷ visitas esperadas no dia, pelos dias de "
                           "atendimento das áreas), pela carteira do vendedor; dias sem visita esperada ficam fora",
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


def janela_base(inicio: dt.date, fim: dt.date) -> tuple[dt.date, dt.date]:
    """Janela da base de uma ação (página Gestão): o mesmo número de dias, logo antes do início."""
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


def _media_dos_dias(pedidos: Counter, visitas: Counter) -> dict:
    """A efetividade de cada dia com visita esperada (pedidos do dia ÷ visitas do dia) e a média desses dias; num e
    den somam só esses dias (o que a página mostra ao lado)."""
    dias = sorted(d for d, n in visitas.items() if n)
    return {"num": float(sum(pedidos[d] for d in dias)), "den": float(sum(visitas[d] for d in dias)),
            "valor": sum(pedidos[d] / visitas[d] for d in dias) / len(dias) if dias else None, "dias": len(dias)}


def _efetividade(cur, c: dict, ids: list[int], inicio: dt.date, ate: dt.date, areas: dict[int, list[int]],
                 abrir: str | None = None) -> dict:
    """A média da efetividade de cada dia, pelo vendedor da carteira: em cada dia com visita esperada, os pedidos do
    dia ÷ as visitas esperadas no dia. Dia sem visita esperada (o fim de semana, o dia sem área) fica fora da média,
    com os pedidos dele. Cliente em área sem linha em areas_atendimento (pendente) fica fora e entra no aviso; área
    com dias vazios (não atendida) fica fora sem aviso."""
    dias_semana: dict[int, list[dt.date]] = {}
    d = inicio
    while d <= ate:
        dias_semana.setdefault(d.isoweekday(), []).append(d)
        d += dt.timedelta(days=1)
    onde_k, params_k = _carteira(c, ids)
    grupos = ("k.id_vendedor_carteira, k.id_area, COALESCE(k.area, '(sem área)'), "
              "COALESCE(k.segmento, '(sem segmento)')")
    clientes = [((v, a, ar, s), n) for v, a, ar, s, n in cur.execute(
        f"SELECT {grupos}, COUNT(*) FILTER (WHERE NOT COALESCE(k.inativo, false) AND NOT "
        f"contains(upper(COALESCE(k.cliente, '')), 'PEDIDO BLOQUEADO')) FROM clientes k WHERE {onde_k} "
        f"GROUP BY 1, 2, 3, 4", params_k).fetchall()]
    pedidos: dict = {}
    for v, a, ar, s, data, n in cur.execute(
            f"SELECT {grupos}, p.data, SUM(p.pedidos) FROM _pedidos_venda p JOIN clientes k ON k.id_cliente = p.id_cliente "
            f"WHERE p.tipo_cliente = 'CLIENTE' AND p.data BETWEEN ? AND ? AND p.cancelada = 0 "
            f"AND p.tipopedido = 'PEDIDOVENDA' AND {onde_k} GROUP BY 1, 2, 3, 4, 5", [inicio, ate, *params_k]).fetchall():
        pedidos.setdefault((v, a, ar, s), Counter())[data] += _numero(n)
    vend: dict = {}
    total = (Counter(), Counter())  # (pedidos, visitas) por dia
    por: dict = {}
    sem_dia = 0
    for (v, area_id, area, seg), visitaveis in clientes:
        if area_id not in areas:  # área pendente
            sem_dia += visitaveis
            continue
        if not areas[area_id]:  # área marcada como não atendida
            continue
        alvos = [vend.setdefault(v, (Counter(), Counter())), total]
        if abrir:
            alvos.append(por.setdefault(area if abrir == "area" else seg, (Counter(), Counter())))
        ped = pedidos.get((v, area_id, area, seg), Counter())
        for p_dia, v_dia in alvos:
            p_dia.update(ped)
            if visitaveis:
                for dia in areas[area_id]:
                    for data in dias_semana.get(dia, ()):
                        v_dia[data] += visitaveis
    r = {"vend": {v: _media_dos_dias(*x) for v, x in vend.items()}, "total": _media_dos_dias(*total), "avisos": []}
    if sem_dia:
        r["avisos"].append(f"{sem_dia} cliente{'s' if sem_dia != 1 else ''} ativo{'s' if sem_dia != 1 else ''} da "
                           f"carteira {SEM_DIA}")
    if abrir in ("area", "segmento"):
        r["abertura"] = [{"chave": k, "nome": k, **_media_dos_dias(*x)} for k, x in por.items()]
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
        r["base_total"] = base["total"]["num"]
    return r


def valor_de(comportamento: str, x: dict | None):
    """O valor do indicador a partir do numerador e do denominador de medir() (soma: o numerador; média: a razão,
    ou o valor que a conta já trouxe, como a média dos dias da efetividade)."""
    if x is None:
        return 0.0 if comportamento == "soma" else None
    if comportamento == "soma":
        return x["num"]
    return x["valor"] if "valor" in x else _div(x["num"], x["den"])


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
        return valor_de(comportamento, x)

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
        if desc.get("media_diaria"):
            extra["dias"] = (medido or {}).get("dias", 0)
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
    if desc.get("media_diaria"):
        t["dias"] = m["total"].get("dias", 0)
    return t


def total_equipe(cur, objetivo: dict, ids: list[int], cal, data_ref: dt.date, regiao: str,
                 areas: dict | None = None) -> dict:
    """Objetivo da região (página Gestão): o indicador da equipe (o total de medir(), sem repetir clientes entre os
    vendedores) contra o alvo da equipe (meta_padrao), com a situação pelo calendário da região. ids: os vendedores
    que contam."""
    metrica, p = normalizar(objetivo["metrica"], objetivo.get("parametros"))
    c = {**objetivo, "metrica": metrica, "parametros": p, "metas_produto": objetivo.get("metas_produto") or []}
    inicio, fim = c["inicio"], c["fim"]
    unidade = ""
    if p.get("medida") == "volume":
        achadas = unidades(cur, c["filtros"], data_ref)
        unidade = achadas[0] if len(achadas) == 1 else ("" if not achadas else "/".join(achadas))
    desc = descritor(metrica, p, unidade)
    m = {"total": {"num": 0.0, "den": None}, "avisos": []}
    if ids:
        m = medir(cur, c, ids, inicio, min(fim, data_ref), areas)
    realizado = valor_de(desc["comportamento"], m["total"])
    meta, extra = c["meta_padrao"], {}
    if metrica == "preco_medio":
        alvo = 1.0
    elif p.get("forma") == "crescimento":
        base = m.get("base_total") or 0.0
        alvo = base * (1 + meta / 100) if base and meta else 0.0
        extra["base"] = _redondo(base)
    else:
        alvo = meta / 100 if desc["meta_em_pct"] else meta
    cal_r = calendario_periodo(cal, inicio, fim, regiao, data_ref)
    ind = bloco(desc["comportamento"], realizado, alvo, cal_r)
    if desc["numerador"]:
        extra.update(numerador=_redondo(m["total"].get("num", 0.0)), denominador=_redondo(m["total"].get("den") or 0.0))
    if desc.get("media_diaria"):
        extra["dias"] = m["total"].get("dias", 0)
    return {"indicador": desc, "unidade": unidade, "situacao": cal_r["situacao"], "vendedores": len(ids),
            "calendario": {**cal_r, "ritmo": round(cal_r["ritmo"], 4)}, "avisos": m.get("avisos", []),
            **{k: _redondo(x) for k, x in ind.items()}, **extra}


def _abertura(por: str, linhas: list[dict], valor) -> dict:
    itens = [{"chave": x["chave"], "nome": x["nome"], "valor": _redondo(valor(x)), "numerador": _redondo(x["num"]),
              **({"denominador": _redondo(x["den"])} if x.get("den") is not None else {}),
              **({"dias": x["dias"]} if "dias" in x else {})} for x in linhas]
    itens.sort(key=lambda x: (x["valor"] is None, -(x["valor"] or 0), str(x["nome"])))
    return {"por": por, "rotulo": ABERTURAS[por], "linhas": itens[:MAX_ABERTURA], "mais": max(0, len(itens) - MAX_ABERTURA)}

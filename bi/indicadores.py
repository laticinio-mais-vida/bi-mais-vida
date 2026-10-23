"""Indicadores das campanhas da página Gestão (bi/gestao.py): o que cada tipo de campanha mede e a conta, feita no
recorte com todos os vendedores do Assistente (view faturamento: as mesmas regras das metas).

Tipos prontos, com as contas do Power BI da empresa (MAIS VIDAS-PBIT.pbit):
- positivacao: clientes distintos com venda no período. Com todos os clientes, também a cobertura: que % da base de
  clientes ativos o vendedor atendeu, mês a mês (_cobertura). A meta é em clientes ou, com meta_em pct_base, em % da
  base (a "Cobertura da carteira" de antes, pct_carteira, ficou só para as campanhas antigas).
- mix_medio: produtos da campanha que cada cliente levou, somados, ÷ clientes positivados (com qualquer produto).
- efetividade: a média da efetividade de cada dia do período, pelo vendedor da carteira do cliente. A de um dia:
  pedidos de venda na rota do dia (PEDIDOVENDAS não cancelados, do tipo PEDIDOVENDA, de clientes das áreas atendidas
  nesse dia da semana) ÷ visitas esperadas no dia, que são os clientes ativos (sem "PEDIDO BLOQUEADO" no nome) dessas
  áreas, pela frequência de compra (rede SEMANAL, QUINZENAL ou MENSAL no cadastro): o semanal sempre, o quinzenal sem
  compra nos 7 dias antes, o mensal sem compra nos 21 dias antes; o cliente fora da previsão que compra no dia entra
  nas visitas desse dia. Pedido de cliente de área de outro dia não conta (o "Pedidos Fora de Rota" do Power BI) e dia sem visita
  esperada (o fim de semana, por exemplo) fica fora da média (decisões do usuário: o Power BI divide todos os
  pedidos do período pelas visitas do período). Os dias de cada área ficam no PostgreSQL (areas_atendimento);
  cliente em área sem dia fica fora da conta (pedidos e visitas) e entra no aviso.
- frequencia: semanas com compra, somadas cliente a cliente, ÷ clientes positivados. A semana vai de domingo a
  sábado e é cortada na virada do mês, como o WEEKNUM do Power BI.
- preco_medio: preço médio (venda líquida ÷ quantidade líquida) de cada produto contra o preço-alvo dele. Na campanha,
  o % da meta de cada vendedor é o aumento de preço feito ÷ o aumento pedido (do preço dele na base até o preço-alvo),
  somados em R$ produto a produto nas quantidades vendidas agora (progresso_preco; decisão do usuário: a meta é o
  aumento, não o preço cheio). A meta própria de um vendedor troca o preço-alvo dele nos produtos que ela dá
  (alvos_do_vendedor). No objetivo, que não tem base, um índice: o que vendeu ÷ o que teria vendido as mesmas
  quantidades nos preços-alvo (100% = no alvo).
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
import unicodedata
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
PERIODOS_BASE = {"semana": "Semana", "quinzena": "Quinzena", "mes": "Mês", "trimestre": "Trimestre",
                 "semestre": "Semestre", "ano": "Ano"}  # a janela da base de uma campanha (janela_fechada)
BASES = {
    "todos": "todos os clientes", "novos": "clientes novos (sem compra antes do início)",
    "recuperados": "clientes recuperados", "nunca_compraram": "quem nunca tinha comprado os produtos da campanha",
    "ja_compraram": "quem já comprava os produtos da campanha",
}
BASES_COM_PRODUTO = ("nunca_compraram", "ja_compraram")
DIAS_SEM_COMPRA = 90
MAX_DIAS_SEM_COMPRA = 730
MAX_PRODUTOS_PRECO = 30
# A meta da positivação: em clientes ou em % da base (a cobertura).
META_EM = {"clientes": "clientes", "pct_base": "% da base"}
# Cobertura (_cobertura). A lista de clientes ativos de um dia vem do histórico da carteira (bi/carteira.py) desde o
# primeiro dia conferido (a semeadura de 15/09/2026); antes, da META CLIENTE da planilha de metas (os ativos do começo
# do mês). Sem o histórico no cache, as listas desde HISTORICO_DESDE esperam os dados (a base não é gravada com a planilha).
HISTORICO_DESDE = dt.date(2026, 9, 15)
MAX_DIAS_UM_MES = 31  # período de até 31 dias: uma cobertura só, com a lista do primeiro dia
FONTES = {"historico": "o histórico da carteira", "planilha": "a META CLIENTE da planilha de metas"}
ABERTURAS = {"area": "Área comercial", "segmento": "Segmento", "produto": "Produto"}
MAX_ABERTURA = 50
SEM_DIA = "ficaram fora da efetividade: estão em áreas sem dia de atendimento (veja Gestão › Configurar)"
# Frequência de compra do cliente (o campo REDE do cadastro) -> de quantas em quantas semanas ele compra. Na
# efetividade, o quinzenal só é visita esperada sem compra nos 7 dias antes; o mensal, sem compra nos 21 dias antes
# (ou, nos dois, se compra no próprio dia).
FREQUENCIAS = {"SEMANAL": 1, "QUINZENAL": 2, "MENSAL": 4}
MAX_SEMANAS = max(FREQUENCIAS.values())


def semanas_da_frequencia(texto) -> int | None:
    """"SEMANAL" -> 1, "Quinzenal" -> 2, "MENSAL" -> 4; o resto (vazio, outra coisa) -> None, que conta como semanal."""
    if not isinstance(texto, str):
        return None
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper().strip()
    return FREQUENCIAS.get(t)


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
    if metrica == "positivacao":
        meta_em = str(p.get("meta_em") or "clientes").strip().lower()
        if meta_em not in META_EM:
            raise ValueError(f"meta_em deve ser {' ou '.join(META_EM)} (veio {meta_em!r})")
        if meta_em == "pct_base":
            if base != "todos":
                raise ValueError("a positivação em % da base conta todos os clientes (sem base de clientes)")
            saida["meta_em"] = meta_em
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
    if metrica == "positivacao" and p.get("meta_em") == "pct_base":
        return "Positivação em % da base"
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
         "comparar": p.get("comparar"), "meta_em": None, "cobertura": False}
    if metrica == "positivacao":
        if p.get("meta_em") == "pct_base":
            d.update(formato="pct", casas=1, comportamento="acumula_taxa", meta_em_pct=True, media_mensal=True,
                     descricao="clientes que o vendedor atendeu ÷ os clientes ativos da carteira dele no início da "
                               "campanha (num período de mais de 31 dias, a média dos meses); antes do histórico da "
                               "carteira (15/09/2026), ÷ a META CLIENTE da planilha de metas",
                     rotulo_meta="% da base", numerador="Clientes atendidos",
                     denominador="Clientes ativos no início", aberturas=["area", "segmento"])
        else:
            d.update(formato="clientes", descricao="clientes distintos com venda no período",
                     rotulo_meta="clientes por vendedor")
        d.update(meta_em=p.get("meta_em", "clientes"), cobertura=p.get("clientes", "todos") == "todos")
    elif metrica == "mix_medio":
        d.update(formato="razao", casas=2, sufixo="produtos por cliente", comportamento="taxa",
                 descricao="produtos da campanha levados por cliente positivado (média, como no Power BI)",
                 rotulo_meta="produtos por cliente", numerador="Produtos levados (somando os clientes)",
                 denominador="Clientes positivados", aberturas=["area", "segmento"])
    elif metrica == "efetividade":
        d.update(formato="pct", casas=1, comportamento="taxa", meta_em_pct=True, media_diaria=True,
                 descricao="média da efetividade de cada dia (pedidos na rota do dia ÷ visitas esperadas no dia, pelos "
                           "dias de atendimento das áreas e pela frequência de compra de cada cliente), pela carteira "
                           "do vendedor; pedido de cliente de área de outro dia não conta, e dias sem visita esperada "
                           "ficam fora",
                 rotulo_meta="% de efetividade", numerador="Pedidos na rota", denominador="Visitas esperadas",
                 aberturas=["area", "segmento"], abrir_padrao="area")
    elif metrica == "frequencia":
        d.update(formato="razao", casas=2, sufixo="semanas por cliente", comportamento="acumula_taxa",
                 descricao="semanas com compra por cliente positivado (média, como no Power BI)",
                 rotulo_meta="semanas com compra por cliente", numerador="Semanas com compra (somando os clientes)",
                 denominador="Clientes positivados", aberturas=["segmento", "area"], abrir_padrao="segmento")
    elif metrica == "preco_medio":
        d.update(formato="pct", casas=1, comportamento="taxa", meta_em_pct=True,
                 descricao="preço médio (venda líquida ÷ quantidade) de cada produto contra o preço-alvo. Na campanha, "
                           "o % da meta é o aumento de preço feito sobre a base de cada vendedor ÷ o aumento até o "
                           "preço-alvo, somados em R$ nas quantidades vendidas agora; no objetivo, o índice compara o "
                           "vendido com o que seria nos preços-alvo (100% = no alvo)",
                 rotulo_meta="o preço-alvo de cada produto", aberturas=[])
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
    """Janela da base das campanhas de antes da 012 (base_periodo vazio): o mesmo número de dias, logo antes do
    início."""
    dias = (fim - inicio).days + 1
    return inicio - dt.timedelta(days=dias), inicio - dt.timedelta(days=1)


def janela_fechada(inicio: dt.date, periodo: str) -> tuple[dt.date, dt.date]:
    """Janela da base de uma campanha (página Gestão): o último período fechado que termina antes do início. Semana
    de segunda a domingo; quinzena de 1 a 15 ou de 16 ao fim do mês; trimestre e semestre do ano civil."""
    if periodo not in PERIODOS_BASE:
        raise ValueError(f"período da base desconhecido: {periodo!r} (use {', '.join(PERIODOS_BASE)})")
    ontem = inicio - dt.timedelta(days=1)
    if periodo == "semana":
        fim = ontem - dt.timedelta(days=ontem.isoweekday() % 7)  # o último domingo antes do início
        return fim - dt.timedelta(days=6), fim
    if periodo == "quinzena":
        if inicio.day > 15:
            return inicio.replace(day=1), inicio.replace(day=15)
        fim = inicio.replace(day=1) - dt.timedelta(days=1)
        return fim.replace(day=16), fim
    meses = {"mes": 1, "trimestre": 3, "semestre": 6, "ano": 12}[periodo]
    n = inicio.year * 12 + (inicio.month - 1) // meses * meses - meses  # o primeiro mês do período anterior
    de = dt.date(n // 12, n % 12 + 1, 1)
    return de, dt.date(inicio.year, (inicio.month - 1) // meses * meses + 1, 1) - dt.timedelta(days=1)


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


def meses_cobertura(inicio: dt.date, fim: dt.date, ate: dt.date,
                    por_mes: bool = False) -> list[tuple[dt.date, dt.date, dt.date]]:
    """As partes da cobertura: (o dia da lista de ativos, de, até). Período de até 31 dias (de inicio a fim): uma parte
    só, com a lista do primeiro dia; acima disso, uma por mês do calendário, com os dias do período que caem nele, e a
    média dos % dos meses. A lista é a do início do período em todas as partes (a campanha: decisão do usuário,
    2026-10-23) ou, com por_mes (a base de trimestre, semestre ou ano), a do primeiro dia de cada parte. ate: até onde
    os dados vão (o período em andamento)."""
    ate = min(ate, fim)
    if ate < inicio:
        return []
    if (fim - inicio).days + 1 <= MAX_DIAS_UM_MES:
        return [(inicio, inicio, ate)]
    partes, d = [], inicio
    while d <= ate:
        proximo = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        partes.append((d if por_mes else inicio, d, min(proximo - dt.timedelta(days=1), ate)))
        d = proximo
    return partes


def _fonte(dia: dt.date, inicio_hist: dt.date | None) -> str:
    """De onde vem a lista de ativos de um dia: o histórico da carteira (que já existia nesse dia), a planilha de metas
    (antes dele) ou pendente (o cache ainda sem o histórico, num dia desde HISTORICO_DESDE)."""
    if inicio_hist and inicio_hist <= dia:
        return "historico"
    return "pendente" if inicio_hist is None and dia >= HISTORICO_DESDE else "planilha"


def _cobertura(cur, c: dict, ids: list[int], inicio: dt.date, ate: dt.date, abrir: str | None = None) -> dict:
    """A cobertura da positivação (decisões do usuário, 2026-10-23): os clientes que o vendedor atendeu ÷ os clientes
    ativos da carteira dele no início (a lista não muda: quem entra ou volta depois do início não conta nos ativos, e
    quem sai continua). O numerador são todos os que ele atendeu, da lista ou não, e o % pode passar de 100%. Num
    período de mais de 31 dias, a média dos meses (meses_cobertura; na base, c["lista_por_mes"], cada mês com a sua
    lista). A lista vem:
    - do histórico da carteira (bi/carteira.py), desde o primeiro dia conferido: os clientes com um trecho no dia, sem
      "PEDIDO BLOQUEADO", na carteira do vendedor naquele dia. Os filtros de cliente (UF, segmento, área) valem pelo
      trecho nos ativos e pelo cadastro nos atendidos;
    - antes dele, da META CLIENTE do vendedor na planilha de metas no mês do dia, que acompanha os ativos da carteira
      no começo do mês (o "% Meta Clientes Realizada" do Power BI). Sem saber quais são os clientes, o filtro de
      cliente deixa a parte sem número.
    Os filtros de produto valem nos dois (só no numerador). Vendedor sem número numa parte (fora da planilha, sem
    ativos) fica sem cobertura no período; sem o histórico no cache, as listas desde HISTORICO_DESDE ficam pendentes.
    Devolve, por vendedor e no total, {atendidos, ativos, pct, meses: [{mes, fonte, atendidos, ativos, pct}], falta,
    pendente, lista (o dia da lista, se é um só)}, os avisos e, com abrir (área ou segmento, só com todas as partes do
    histórico), a abertura."""
    filtros = c["filtros"]
    partes = meses_cobertura(inicio, max(c.get("fim") or ate, inicio), ate, bool(c.get("lista_por_mes")))
    inicio_hist = cur.execute("SELECT min(data) FROM carteira_retratos").fetchone()[0]
    onde_p, params_p = _onde(filtros, FILTROS_PRODUTO)
    onde_c, params_c = _onde(filtros, FILTROS_CLIENTE)
    onde_t, _ = _onde(filtros, FILTROS_CLIENTE, "t.")
    sem = f"'(sem {'área' if abrir == 'area' else 'segmento'})'"

    def atendidos(de, a, vendedores, grupo, cliente):
        """{grupo: clientes distintos que cada vendedor atendeu entre de e a}, somados entre os vendedores."""
        onde = onde_p + (onde_c if cliente else [])
        sql = (f"SELECT g, COUNT(*) FROM (SELECT DISTINCT id_vendedor, id_cliente, {grupo} AS g FROM faturamento "
               f"WHERE {_VENDA} AND {_CLIENTE} AND data BETWEEN ? AND ? AND id_vendedor IN ({_marcas(vendedores)})"
               + "".join(f" AND {o}" for o in onde) + ") GROUP BY 1")
        params = [de, a, *vendedores, *params_p, *(params_c if cliente else [])]
        return {k: _numero(n) for k, n in cur.execute(sql, params).fetchall()}

    def lista(dia, grupo):
        """{grupo: clientes ativos da carteira no dia}, pelo trecho de cada cliente que cobre o dia."""
        sql = ("WITH t AS (SELECT * FROM clientes_vigencias WHERE de <= ? AND (ate IS NULL OR ate >= ?) "
               "QUALIFY row_number() OVER (PARTITION BY id_cliente ORDER BY de DESC) = 1) "
               f"SELECT {grupo}, COUNT(*) FROM t WHERE NOT t.bloqueado AND t.id_vendedor IN ({_marcas(ids)})"
               + "".join(f" AND {o}" for o in onde_t) + " GROUP BY 1")
        return {k: _numero(n) for k, n in cur.execute(sql, [dia, dia, *ids, *params_c]).fetchall()}

    vend = {v: {"meses": [], "falta": [], "pendente": False} for v in ids}
    total = {"meses": [], "falta": [], "pendente": False}
    avisos, abertura, sem_planilha, com_filtro = [], {}, set(), []
    for dia, de, a in partes:
        fonte = _fonte(dia, inicio_hist)
        chave = de.isoformat()[:7]
        if fonte == "pendente":
            for x in (*vend.values(), total):
                x["pendente"] = True
            continue
        por_v: dict[int, tuple[float, float]] = {}
        if fonte == "planilha":
            if onde_c:
                com_filtro.append(f"{dia:%m/%Y}")
            else:
                metas = dict(cur.execute(f"SELECT id_vendedor, meta_clientes FROM metas_vendedor WHERE ano = ? AND mes = ? "
                                         f"AND id_vendedor IN ({_marcas(ids)})", [dia.year, dia.month, *ids]).fetchall())
                feitos = atendidos(de, a, ids, "id_vendedor", False)
                por_v = {v: (feitos.get(v, 0.0), _numero(metas[v])) for v in ids if metas.get(v)}
                sem_planilha |= {v for v in ids if not metas.get(v)}
        else:
            ativos = lista(dia, "t.id_vendedor")
            feitos = atendidos(de, a, ids, "id_vendedor", True)
            por_v = {v: (feitos.get(v, 0.0), d) for v, d in ativos.items()}
            com_lista = [v for v in ids if ativos.get(v)]  # como no total: só os vendedores com o número
            if abrir in ("area", "segmento") and com_lista:
                ds = lista(dia, f"COALESCE(t.{abrir}, {sem})")
                ns = atendidos(de, a, com_lista, f"COALESCE({abrir}, {sem})", True)
                for k in ds.keys() | ns.keys():
                    abertura.setdefault(k, []).append((ns.get(k, 0.0), ds.get(k, 0.0)))
        soma_n = soma_d = 0.0
        for v in ids:
            n, d = por_v.get(v, (0.0, 0.0))
            if d:
                vend[v]["meses"].append({"mes": chave, "fonte": fonte, "atendidos": n, "ativos": d, "pct": n / d})
                soma_n, soma_d = soma_n + n, soma_d + d
            else:
                vend[v]["falta"].append(chave)
        if soma_d:
            total["meses"].append({"mes": chave, "fonte": fonte, "atendidos": soma_n, "ativos": soma_d,
                                   "pct": soma_n / soma_d})
        else:
            total["falta"].append(chave)
    dias = {dia for dia, _, _ in partes}
    um_dia = next(iter(dias)).isoformat() if len(dias) == 1 else None

    def fechar(x: dict) -> dict:
        meses = x["meses"]
        completo = bool(meses) and not x["pendente"] and not x["falta"]
        return {"atendidos": sum(m["atendidos"] for m in meses), "ativos": sum(m["ativos"] for m in meses),
                "pct": sum(m["pct"] for m in meses) / len(meses) if completo else None, "meses": meses,
                "falta": x["falta"], "pendente": x["pendente"], "lista": um_dia}

    if total["pendente"]:
        avisos.append("o histórico da carteira ainda não chegou do computador da empresa; a cobertura (% da base) "
                      "aparece depois da próxima atualização")
    if com_filtro:
        avisos.append("com filtro de cliente (UF, segmento ou área), a cobertura só sai com o histórico da carteira "
                      f"(desde 15/09/2026): {', '.join(com_filtro)} fica{'m' if len(com_filtro) > 1 else ''} sem o % "
                      "da base")
    if sem_planilha:
        n = len(sem_planilha)
        avisos.append(f"{n} vendedor{'es' if n != 1 else ''} sem a META CLIENTE na planilha de metas em algum mês "
                      f"fica{'m' if n != 1 else ''} sem a cobertura (% da base)")
    r = {"vend": {v: fechar(x) for v, x in vend.items()}, "total": fechar(total), "avisos": avisos}
    if abrir in ("area", "segmento") and partes and all(_fonte(dia, inicio_hist) == "historico" for dia, _, _ in partes):
        r["abertura"] = [{"chave": k, "nome": k, "num": sum(n for n, _ in xs), "den": sum(d for _, d in xs),
                          "valor": (sum(n / d for n, d in xs) / len(xs)
                                    if len(xs) == len(partes) and all(d for _, d in xs) else None)}
                         for k, xs in abertura.items()]
    return r


def _como_valor(x: dict) -> dict:
    """A cobertura como valor do indicador (na positivação em % da base): numerador, denominador e a média dos meses."""
    return {"num": x["atendidos"], "den": x["ativos"], "valor": x["pct"], "meses": len(x["meses"]),
            "pendente": x["pendente"]}


def da_base(x: dict | None) -> dict | None:
    """A cobertura de um vendedor (ou do total) como a página e a IA recebem: os meses em número, as fontes, os meses
    sem número (MM/AAAA) e o dia da lista de ativos (None: na base longa, o primeiro dia de cada mês)."""
    if not x:
        return None
    return {"atendidos": _redondo(x["atendidos"]), "ativos": _redondo(x["ativos"]), "pct": _redondo(x["pct"]),
            "meses": len(x["meses"]), "fontes": sorted({m["fonte"] for m in x["meses"]}),
            "falta": [f"{m[5:]}/{m[:4]}" for m in x["falta"]], "pendente": x["pendente"], "lista": x.get("lista")}


def _media_dos_dias(pedidos: Counter, visitas: Counter) -> dict:
    """A efetividade de cada dia com visita esperada (pedidos na rota do dia ÷ visitas do dia) e a média desses dias;
    num e den somam só esses dias (o que a página mostra ao lado)."""
    dias = sorted(d for d, n in visitas.items() if n)
    return {"num": float(sum(pedidos[d] for d in dias)), "den": float(sum(visitas[d] for d in dias)),
            "valor": sum(pedidos[d] / visitas[d] for d in dias) / len(dias) if dias else None, "dias": len(dias)}


_PEDIDO_VALIDO = "p.tipo_cliente = 'CLIENTE' AND p.cancelada = 0 AND p.tipopedido = 'PEDIDOVENDA'"
_VISITAVEL = "NOT COALESCE(k.inativo, false) AND NOT contains(upper(COALESCE(k.cliente, '')), 'PEDIDO BLOQUEADO')"


def _efetividade(cur, c: dict, ids: list[int], inicio: dt.date, ate: dt.date, areas: dict[int, list[int]],
                 abrir: str | None = None) -> dict:
    """A média da efetividade de cada dia, pelo vendedor da carteira: em cada dia com visita esperada, os pedidos na
    rota do dia (de clientes das áreas atendidas nesse dia da semana) ÷ as visitas esperadas no dia. Pedido de cliente
    de área de outro dia não conta (o "fora de rota" do Power BI). Dia sem visita esperada (o fim de semana, o dia sem
    área) fica fora da média. Cliente em área sem linha em areas_atendimento (pendente) fica fora e entra no aviso;
    área com dias vazios (não atendida) fica fora sem aviso.

    Visita esperada pela frequência de compra do cliente (frequencia_semanas, da rede do cadastro): o semanal é
    esperado em todo dia de atendimento da área dele; o quinzenal, se não comprou nos 7 dias antes; o mensal, se não
    comprou nos 21 dias antes (as três semanas anteriores). O cliente fora da previsão que compra no dia entra nas
    visitas desse dia (decisão do usuário: antes o pedido contava sem a visita, e o dia passava de 100%). Compra =
    pedido de venda (de qualquer vendedor e em qualquer dia). Cliente sem frequência no cadastro conta como semanal."""
    onde_k, params_k = _carteira(c, ids)
    grupos = ("k.id_vendedor_carteira AS v, k.id_area AS a, COALESCE(k.area, '(sem área)') AS ar, "
              "COALESCE(k.segmento, '(sem segmento)') AS s")
    rota = sorted((a, d) for a, dias in areas.items() for d in dias)
    com_rota = (f"WITH rota AS (SELECT unnest(?::INTEGER[]) AS id_area, unnest(?::INTEGER[]) AS dia_semana)",
                [[a for a, _ in rota], [d for _, d in rota]])
    sem_dia, sem_frequencia = cur.execute(
        f"SELECT COUNT(*) FILTER (WHERE k.id_area IS NULL OR k.id_area NOT IN (SELECT unnest(?::INTEGER[]))), "
        f"COUNT(*) FILTER (WHERE k.id_area IN (SELECT unnest(?::INTEGER[])) AND k.frequencia_semanas IS NULL) "
        f"FROM clientes k WHERE {onde_k} AND {_VISITAVEL}",
        [sorted(areas), sorted(a for a, d in areas.items() if d), *params_k]).fetchone()
    pedidos: dict = {}  # na rota: o dia do pedido é um dia de atendimento da área do cliente
    visitas: dict = {}
    if rota:
        for v, a, ar, s, data, n in cur.execute(
                f"{com_rota[0]} SELECT {grupos}, p.data, SUM(p.pedidos) FROM _pedidos_venda p "
                f"JOIN clientes k ON k.id_cliente = p.id_cliente "
                f"JOIN rota r ON r.id_area = k.id_area AND r.dia_semana = isodow(p.data) "
                f"WHERE {_PEDIDO_VALIDO} AND p.data BETWEEN ? AND ? AND {onde_k} GROUP BY 1, 2, 3, 4, 5",
                [*com_rota[1], inicio, ate, *params_k]).fetchall():
            pedidos.setdefault((v, a, ar, s), Counter())[data] += _numero(n)
        dias = [inicio + dt.timedelta(days=i) for i in range((ate - inicio).days + 1)]
        for v, a, ar, s, data, n in cur.execute(
                f"{com_rota[0]}, dias AS (SELECT unnest(?::DATE[]) AS dia), "
                f"esperados AS (SELECT k.id_cliente, {grupos}, x.dia, COALESCE(k.frequencia_semanas, 1) AS semanas "
                f"FROM clientes k JOIN rota r ON r.id_area = k.id_area JOIN dias x ON isodow(x.dia) = r.dia_semana "
                f"WHERE {onde_k} AND {_VISITAVEL}), "
                f"compras AS (SELECT DISTINCT p.id_cliente, p.data FROM _pedidos_venda p WHERE {_PEDIDO_VALIDO} "
                f"AND p.data BETWEEN ? AND ?) "
                f"SELECT v, a, ar, s, dia, COUNT(*) FROM esperados e WHERE semanas <= 1 OR NOT EXISTS ("
                f"SELECT 1 FROM compras p WHERE p.id_cliente = e.id_cliente "
                f"AND p.data BETWEEN e.dia - 7 * (e.semanas - 1) AND e.dia - 1) "
                f"OR EXISTS (SELECT 1 FROM compras p WHERE p.id_cliente = e.id_cliente AND p.data = e.dia) "
                f"GROUP BY 1, 2, 3, 4, 5",
                [*com_rota[1], dias, *params_k, inicio - dt.timedelta(days=7 * (MAX_SEMANAS - 1)), ate]).fetchall():
            visitas.setdefault((v, a, ar, s), Counter())[data] += n
    vend: dict = {}
    total = (Counter(), Counter())  # (pedidos, visitas) por dia
    por: dict = {}
    for chave in {*pedidos, *visitas}:
        v, _, area, seg = chave
        alvos = [vend.setdefault(v, (Counter(), Counter())), total]
        if abrir:
            alvos.append(por.setdefault(area if abrir == "area" else seg, (Counter(), Counter())))
        for p_dia, v_dia in alvos:
            p_dia.update(pedidos.get(chave, {}))
            v_dia.update(visitas.get(chave, {}))
    r = {"vend": {v: _media_dos_dias(*x) for v, x in vend.items()}, "total": _media_dos_dias(*total), "avisos": []}
    if sem_dia:
        r["avisos"].append(f"{sem_dia} cliente{'s' if sem_dia != 1 else ''} ativo{'s' if sem_dia != 1 else ''} da "
                           f"carteira {SEM_DIA}")
    if sem_frequencia:
        um = sem_frequencia == 1
        r["avisos"].append(f"{sem_frequencia} cliente{'' if um else 's'} ativo{'' if um else 's'} da carteira sem "
                           f"frequência de compra no cadastro (REDE) conta{'' if um else 'm'} como semana"
                           f"{'l' if um else 'is'}")
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

    def item(pid, valor, qtd):  # sem o preço-alvo (a prévia da base, antes de digitar), só o preço
        preco = valor / qtd if qtd > 0 else None
        return {"id": pid, "nome": info.get(pid, (f"Produto {pid}", ""))[0], "unidade": info.get(pid, ("", ""))[1],
                "meta": alvo[pid], "valor": _redondo(valor), "quantidade": _redondo(qtd),
                "preco": _redondo(preco) if preco is not None else None,
                "pct": preco / alvo[pid] if preco is not None and alvo[pid] else None}

    por_vend: dict = {}
    total: dict = {}
    for g, vid, pid, valor, qtd in linhas:
        (total if g else por_vend.setdefault(vid, {}))[pid] = item(pid, _numero(valor), _numero(qtd))

    def indice(itens: dict) -> dict:
        com = [i for i in itens.values() if i["preco"] is not None]
        return {"num": sum(i["valor"] for i in com), "den": sum(i["quantidade"] * i["meta"] for i in com if i["meta"]),
                "produtos": [itens.get(p) or item(p, 0.0, 0.0) for p in prods]}

    return {"vend": {v: indice(por_vend.get(v, {})) for v in ids}, "total": indice(total)}


def alvos_do_vendedor(alvos: dict, proprios: dict | None) -> dict:
    """Os preços-alvo de um vendedor no preço médio: os da campanha ({produto: R$}) e, por cima, a meta própria dele
    (proprios: {"<produto>": R$}, campanha_vendedores.alvos_precos; só valem os produtos da campanha)."""
    proprios = proprios or {}
    return {pid: float(proprios[str(pid)]) if proprios.get(str(pid)) is not None else alvo for pid, alvo in alvos.items()}


def precos_de(produtos) -> dict:
    """Os preços de um vendedor como ficam gravados: {"<produto>": {"preco", "quantidade"}}, só os vendidos."""
    return {str(p["id"]): {"preco": p["preco"], "quantidade": p["quantidade"]}
            for p in produtos or [] if p.get("preco") is not None}


def progresso_preco(base: dict | None, atual: dict | None, alvos: dict) -> dict | None:
    """O % da meta do preço médio na campanha: quanto do aumento de preço pedido o vendedor já fez (decisão do usuário:
    com base R$ 10, meta R$ 20 e preço de agora R$ 15, está em 50%). Com vários produtos, soma em R$ nas quantidades
    vendidas agora: o aumento feito ((preço de agora − o da base) × quantidade) ÷ o pedido ((preço-alvo − o da base) ×
    quantidade). Produto que já estava no alvo na base não pede aumento e só entra se cair abaixo dele (a perda
    desconta); se nenhum pede aumento, o % é o de manter o alvo. Produto sem preço na base ou sem venda agora fica fora.
    base e atual: precos_de(); alvos: {produto: preço-alvo}. None: sem base ou sem venda. produtos: o % de cada um
    (para a página: o caminho até o alvo, ou preço ÷ alvo, até 100%, no que já estava no alvo)."""
    feito = pedido = perda = manter = 0.0
    produtos = {}
    for pid, alvo in alvos.items():
        b = ((base or {}).get(str(pid)) or {}).get("preco")
        x = (atual or {}).get(str(pid)) or {}
        p, q = x.get("preco"), x.get("quantidade") or 0.0
        if b is None or p is None or q <= 0:
            continue
        if b < alvo:
            pedido += q * (alvo - b)
            feito += q * (p - b)
            produtos[str(pid)] = (p - b) / (alvo - b)
        else:
            perda += q * min(p - alvo, 0.0)
            manter += q * alvo
            produtos[str(pid)] = min(p, alvo) / alvo
    if not produtos:
        return None
    if pedido:
        return {"pct": (feito + perda) / pedido, "aumento": feito + perda, "aumento_pedido": pedido, "produtos": produtos}
    return {"pct": (manter + perda) / manter, "aumento": perda, "aumento_pedido": 0.0, "produtos": produtos}


def progresso_preco_juntos(itens) -> float | None:
    """O % da meta do preço médio de vários vendedores juntos (a barra da campanha), pela mesma regra: os aumentos
    feitos ÷ os pedidos, somados em R$. Na média do % de cada um, quem estava a centavos do alvo (e pulou para 700%)
    dominaria a campanha. Sem aumento pedido (todos já estavam no alvo), a média do % de manter. itens: (pct,
    aumento, aumento_pedido) de cada vendedor."""
    itens = [(p, a or 0.0, d or 0.0) for p, a, d in itens if p is not None]
    if not itens:
        return None
    pedido = sum(d for _, _, d in itens)
    return sum(a for _, a, _ in itens) / pedido if pedido else sum(p for p, _, _ in itens) / len(itens)


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
    pct_base = metrica == "positivacao" and c["parametros"].get("meta_em") == "pct_base"
    r = _fat(cur, c, ids, inicio, ate, abrir if forma != "crescimento" and not pct_base else None)
    if metrica == "positivacao" and c["parametros"].get("clientes", "todos") == "todos":
        cob = _cobertura(cur, c, ids, inicio, ate, abrir if pct_base else None)
        r.update(cobertura=cob["vend"], cobertura_total=cob["total"], avisos=cob["avisos"])
        if pct_base:  # o valor do indicador é a cobertura
            r["vend"] = {v: _como_valor(x) for v, x in cob["vend"].items()}
            r["total"] = _como_valor(cob["total"])
            if "abertura" in cob:
                r["abertura"] = cob["abertura"]
        return r
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
    abertura que o tipo mostra de saída; None = nenhuma). No preço médio, o realizado é o % da meta
    (progresso_preco), com os preços da base de cada vendedor em campanha["vendedores"][i]["base_precos"] e a meta
    própria dele em ["alvos_precos"]."""
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
    alvos = {x["id"]: x["meta"] for x in c["metas_produto"]}
    calendarios: dict[str, dict] = {}
    linhas = []
    for v in visiveis:
        vid = v["id"]
        grupo = regras.grupo_vendedor(vid)
        regiao = Projetor._regiao(regras, vid, grupo)
        cal_v = calendarios.get(regiao) or calendarios.setdefault(regiao, calendario_periodo(cal, inicio, fim, regiao, data_ref))
        meta = c["meta_padrao"] if v["meta"] is None else v["meta"]
        medido = m["vend"].get(vid)
        realizado, extra = valor(medido), {}
        if metrica == "preco_medio":
            base = v.get("base_precos") or {}
            alvos_v = alvos_do_vendedor(alvos, v.get("alvos_precos"))
            prog = progresso_preco(base, precos_de((medido or {}).get("produtos")), alvos_v)
            meta_conta, realizado = 1.0, prog and prog["pct"]
            extra = {"aumento": _redondo((prog or {}).get("aumento")), "aumento_pedido": _redondo((prog or {}).get("aumento_pedido")),
                     "produtos": [{**x, "meta": alvos_v.get(x["id"], x["meta"]), "base": (base.get(str(x["id"])) or {}).get("preco"),
                                   "pct": _redondo((prog or {}).get("produtos", {}).get(str(x["id"])))}
                                  for x in (medido or {}).get("produtos") or []]}
        elif crescimento:
            base = (medido or {}).get("base", m.get("base", {}).get(vid, 0.0))
            meta_conta = base * (1 + meta / 100) if base and meta else 0.0
            extra = {"base": _redondo(base), "crescimento": meta}
        else:
            meta_conta = meta / 100 if pct_meta else meta
        ind = bloco(comportamento, realizado, meta_conta, cal_v)
        nome, equipe = info.get(vid, (f"Vendedor {vid}", NOME_EQUIPE.get(grupo, grupo)))
        if desc["numerador"]:
            extra.update(numerador=_redondo((medido or {}).get("num", 0.0)), denominador=_redondo((medido or {}).get("den", 0.0)))
        if desc.get("media_diaria"):
            extra["dias"] = (medido or {}).get("dias", 0)
        if desc.get("media_mensal"):
            extra["meses"] = (medido or {}).get("meses", 0)
        if "cobertura" in m:
            extra["da_base"] = da_base(m["cobertura"].get(vid))
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
        if "cobertura_total" in m:
            t["da_base"] = da_base(m["cobertura_total"])
        return t
    realizado = valor(m["total"]) if linhas else None
    pesos = [(r["meta"], (r.get("denominador") or 0)) for r in com_meta]
    soma_pesos = sum(d for _, d in pesos)
    if desc["tipo"] == "preco_medio":  # os aumentos feitos ÷ os pedidos, somados, como a barra da campanha
        realizado = progresso_preco_juntos((r["realizado"], r.get("aumento"), r.get("aumento_pedido")) for r in linhas)
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
    if desc.get("media_mensal"):
        t["meses"] = m["total"].get("meses", 0)
    if "cobertura_total" in m:
        t["da_base"] = da_base(m["cobertura_total"])
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
    if desc.get("media_mensal"):
        extra["meses"] = m["total"].get("meses", 0)
    if "cobertura_total" in m:
        extra["da_base"] = da_base(m["cobertura_total"])
    return {"indicador": desc, "unidade": unidade, "situacao": cal_r["situacao"], "vendedores": len(ids),
            "calendario": {**cal_r, "ritmo": round(cal_r["ritmo"], 4)}, "avisos": m.get("avisos", []),
            **{k: _redondo(x) for k, x in ind.items()}, **extra}


def _abertura(por: str, linhas: list[dict], valor) -> dict:
    itens = [{"chave": x["chave"], "nome": x["nome"], "valor": _redondo(valor(x)), "numerador": _redondo(x["num"]),
              **({"denominador": _redondo(x["den"])} if x.get("den") is not None else {}),
              **({"dias": x["dias"]} if "dias" in x else {})} for x in linhas]
    itens.sort(key=lambda x: (x["valor"] is None, -(x["valor"] or 0), str(x["nome"])))
    return {"por": por, "rotulo": ABERTURAS[por], "linhas": itens[:MAX_ABERTURA], "mais": max(0, len(itens) - MAX_ABERTURA)}

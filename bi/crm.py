"""CRM (página CRM): uma nota de 0 a 100 para cada cliente, a soma de quatro indicadores.

Quem entra: os clientes ativos da carteira das equipes escolhidas (ES e BA, pelas regras de Metas), sem "PEDIDO
BLOQUEADO" no nome e com a primeira compra (pedido de venda não cancelado) há mais de 1 mês. Quem nunca comprou ou
comprou pela primeira vez há menos de 1 mês fica fora do CRM, sem nota (decisão do usuário).

"Hoje" é o dia da cópia do ERP (cache.dia_da_copia), como no Manejo da Base. O semestre são as 26 semanas fechadas
(de domingo a sábado) que terminam no último sábado antes de hoje; a conta de cada cliente começa na primeira compra
quando ela é mais recente.

1. Aderência à frequência (20 pontos). A frequência é a rede do cadastro: SEMANAL, QUINZENAL ou MENSAL; qualquer outra
   rede (ou nenhuma) vale semanal. Compra = pedido de venda não cancelado, de qualquer vendedor, uma só por semana (a
   primeira; as outras da mesma semana não contam). O semanal conta as semanas com compra; o quinzenal e o mensal, a
   parte do semestre em que o cliente esteve em dia, com um prazo entre compras (15 e 31 dias): cada compra deixa o
   cliente em dia pelo prazo, e cada dia além dele é atraso. Pontos: 100% = 20, a partir de 75% = 15, de 50% = 10.
2. Pontualidade (20 pontos). Títulos de venda que venceram desde 01/01/2024 até a tolerância (7 dias) antes de hoje:
   pontual é o pago até 7 dias depois do vencimento; atrasado, o pago depois ou ainda em aberto (os dias contam até
   hoje). Pontos pela % de pontuais: 96% = 20, 90% = 15, 80% = 10. O atraso médio dos atrasados desconta: de 16 dias,
   5; de 30, 10 (de quem atrasa em qualquer faixa); a nota não fica negativa. Cliente sem título no período fica com os
   20 pontos, sinalizado.
3. Mix ideal (20 pontos). O mix de cada segmento (a planilha MIX IDEAL SEGMENTOS do usuário, com os ajustes dele) é uma
   lista de itens; um item é um ou mais produtos (os da mesma cor na planilha: qualquer um deles atende o item) ou
   "qualquer mussarela" (os produtos da linha de mussarela do ERP). Pontos = 20 × itens atendidos ÷ itens do segmento,
   no mesmo semestre. Cliente sem segmento, ou de segmento que não está no mix, fica com 0 e sinalizado.
4. Rentabilidade (40 pontos). Lucro bruto = (preço médio vendido − custo industrial do mês) × volume, por produto e mês
   (= faturamento − custo × volume), das vendas faturadas a cliente desde 01/2026 até o último mês com custo. Os custos
   são digitados em Configurar (alguns produtos usam o custo de outro). Os clientes do CRM são divididos em quintis pelo
   lucro total (recalculados a cada mês novo de custo): 40, 30, 20, 10 e 0 pontos.

A nota é a soma dos quatro, guardada exata e arredondada só no fim. As regras (os números, o mix e os custos) ficam na
tabela regras (nome "crm", com versões), editadas em CRM › Configurar. O cálculo é do cache inteiro e fica na memória
até chegar uma cópia nova do ERP ou mudar uma regra; cada pedido só filtra os clientes dos vendedores do acesso.
"""
from __future__ import annotations

import copy
import datetime as dt
import decimal
import io
import json
import logging
import math
import re
import threading
import unicodedata
import zipfile

from .banco import hora
from .configuracao import RegrasNoBanco
from .conversas import NaoEncontrada
from .indicadores import semanas_da_frequencia
from .premiacoes import nome_cliente

log = logging.getLogger("bi.crm")

EQUIPES = ("ES", "BA", "EDIR")       # as que dá para escolher em Configurar
FREQUENCIAS = {1: "semanal", 2: "quinzenal", 4: "mensal"}
MAX_CUSTO = 100_000.0                  # R$ por unidade: acima disso é erro de digitação
MAX_PLANILHA = 5 * 1024 * 1024         # a planilha de custos importada
LINHA_MUSSARELA = "MUSSARELA"          # "qualquer mussarela": os produtos cuja linha no ERP tem esta palavra
ANTIGO = dt.date(1900, 1, 1)           # âncora de quem nunca comprou antes do semestre (a conta de atraso começa no início)

# --- o padrão: a planilha MIX IDEAL SEGMENTOS (com os ajustes do usuário) e a de custos industriais ---------------
# Mix: um item é uma lista de códigos (qualquer um atende) ou "M" (qualquer mussarela).
_MIX = {
    "ACOUGUE": [[9616, 5973], [25, 26, 27]],
    "ATACADO": [[8991], [26, 25, 27], [5973, 9616], [24], [11098, 9776], "M"],
    "BUFFET": [[24, 4046], [5973], [26, 27, 5754], [8991], [21], "M"],
    "CAFETERIA E LANCHONETE": [[8991], [26, 27, 25, 5754], [5973], [21], [24, 4046], [2270], "M"],
    "CHURRASCARIA": [[5973, 9616], [26, 27]],
    "FABRICA DE DOCE": [[5754, 26, 27], [8991]],
    "FABRICA DE SALGADO": [[8991], [27, 26, 5754], [24, 4046], "M"],
    "HAMBURGUERIA": [[8991], [5973], [21], [26, 27, 5754], "M"],
    "HOSPITAIS E PREFEITURAS": [[5417, 5413, 10352, 5416], [26], "M"],
    "HOTEL E POUSADA": [[2270], [2105], [27, 26, 5754], [21], [8991], [4835], "M"],
    "MERCADO (4 A 6 CAIXAS)": [[26], [25], [11469], [10352], [11098], [10354], [10353], [9776], [9616], [2105], [4046],
                               [21], [5417], [3790], [4835], [5416], [3791], [3788], [5413], "M"],
    "MERCEARIA (1 A 3 CAIXAS)": [[25], [26], [11098], [10352], [11469], [10354], [10353], [9616], [9776], [2105], [3790],
                                 [5417], [4046], [3791], [3788], [5416], [5413], [4835], [21], [2270], "M"],
    "PADARIA": [[25], [26], [11098], [10352], [8991], [10354], [3790], [10353], [27], [5417], [24], [4046], [21], [3791],
                [3788], [9776], [5416], [5413], [11469], [5754], "M"],
    "PASTELARIA": [[8991], "M"],
    "PIZZARIA": [[8991], [24, 4046], "M"],                       # ajuste: o parmesão cunha junto do parmesão peça
    "RESTAURANTE": [[5973, 9616], [26, 27, 5754], [24], [8991], "M"],  # ajustes: coalho palito e manteiga granel S
    "SUPERMERCADO": [[26], [25], [11469], [10352], [11098], [10354], [10353], [9616], [9776], [4046], [2105], [21],
                     [5417], [4835], [24], [5416], [3790], [5413], [3791], [3788], "M"],
}
# Custo industrial de jan a set de 2026 (planilha "Custos Industriais jan a set"); o prato de fevereiro e de junho repete
# o mês anterior (o da planilha era 0).
_CUSTOS = {
    5413: [0.784766, 0.772872, 0.798930, 0.798838, 0.934526, 0.853216, 0.863781, 0.846846, 0.879015],
    3788: [1.829525, 1.802464, 1.871845, 1.794945, 2.060476, 1.858330, 1.928675, 1.967606, 1.988112],
    10353: [2.581573, 2.538407, 2.665331, 2.570971, 3.068844, 2.752263, 2.784010, 2.842750, 2.790221],
    5417: [0.798959, 0.787925, 0.812732, 0.822311, 0.918984, 0.849325, 0.869086, 0.859884, 0.885087],
    3790: [1.834774, 1.805449, 1.881124, 1.881492, 2.194630, 1.996919, 1.987485, 1.981172, 1.993822],
    11469: [1.730285, 1.697583, 1.798212, 1.630645, 1.899448, 1.843532, 1.699517, 1.873217, 1.699261],
    10352: [2.636970, 2.602955, 2.727301, 2.636540, 3.057052, 2.794803, 2.818203, 2.897060, 2.845538],
    5416: [0.798880, 0.785754, 0.807722, 0.813630, 0.936748, 0.849572, 0.858688, 0.858059, 0.869128],
    3791: [1.856029, 1.827780, 1.896103, 1.878329, 2.147720, 1.999339, 1.999790, 2.003113, 2.017746],
    10354: [2.658457, 2.610847, 2.725675, 2.675910, 3.090743, 2.818742, 2.849771, 2.908104, 2.855972],
    4835: [1.914170, 1.860033, 1.934848, 1.838587, 2.281437, 2.010101, 1.884043, 2.261286, 1.908321],
    2105: [1.984216, 1.940546, 2.010684, 1.915232, 2.296766, 2.069119, 2.061228, 2.321473, 2.020175],
    8991: [13.561601, 14.668184, 14.944827, 15.178943, 16.522328, 16.306922, 15.742467, 14.371709, 17.157114],
    4046: [40.429567, 39.937125, 39.214379, 38.233840, 39.239282, 39.272237, 38.913831, 39.803327, 39.377705],
    24: [33.820579, 32.929853, 32.122499, 32.014654, 34.859416, 35.436950, 35.339741, 34.467720, 35.554501],
    25: [3.506870, 3.650292, 4.768210, 4.960396, 5.169017, 4.728866, 5.560694, 4.973637, 5.566719],
    26: [8.228645, 8.587472, 11.463232, 11.813078, 12.345967, 11.172709, 13.228248, 11.715371, 13.234234],
    27: [15.668686, 16.627913, 22.369485, 23.058095, 24.166297, 21.677478, 25.991783, 23.208141, 25.735139],
    11098: [3.257721, 3.253470, 3.508893, 3.377689, 3.785329, 3.755991, 3.943901, 3.717036, 4.080807],
    2270: [24.256813, 25.650921, 25.738353, 26.667061, 28.299578, 26.676142, 27.260602, 27.635491, 30.018797],
    9776: [2.428085, 2.383268, 2.667793, 2.621350, 2.823129, 2.785066, 2.844227, 2.525592, 3.244439],
    21: [29.135375, 29.135375, 31.425619, 31.697080, 33.869046, 33.869046, 34.996727, 32.977450, 37.162871],
    9616: [31.234237, 33.088685, 33.396531, 33.411185, 36.089412, 35.914130, 36.988534, 35.600721, 39.757510],
    5973: [27.570652, 28.305504, 28.577052, 28.972531, 30.630333, 30.960551, 32.759731, 31.252815, 35.643121],
    12552: [22.0, 27.0, 28.0, 35.0, 30.0, 30.0, 31.5, 25.67, 29.66],
    12551: [24.0, 25.0, 30.0, 37.0, 32.0, 32.0, 34.5, 28.0, 31.84],
    32: [27.308273, 28.020276, 28.802093, 29.625345, 31.654729, 31.826727, 32.857246, 32.117942, 35.679190],
}
_USA_CUSTO_DE = {5754: 27, 12175: 12552, 12189: 12552}  # decisão do usuário (20/11/2026)


def _item_padrao(item) -> dict:
    return {"mussarela": True} if item == "M" else {"produtos": list(item)}


PADRAO = {
    "versao": 1,
    "equipes": ["ES", "BA"],
    "meses_para_entrar": 1,
    "aderencia": {"semanas": 26, "prazo_quinzenal": 15, "prazo_mensal": 31,
                  "faixas": [{"de": 100, "pontos": 20}, {"de": 75, "pontos": 15}, {"de": 50, "pontos": 10}]},
    "pontualidade": {"desde": "2024-01-01", "tolerancia": 7, "sem_titulo": 20,
                     "faixas": [{"de": 96, "pontos": 20}, {"de": 90, "pontos": 15}, {"de": 80, "pontos": 10}],
                     "descontos": [{"de": 30, "pontos": 10}, {"de": 16, "pontos": 5}]},
    "mix": {"pontos": 20, "segmentos": {s: [_item_padrao(i) for i in itens] for s, itens in _MIX.items()}},
    "rentabilidade": {"desde": "2026-01", "pontos": [40, 30, 20, 10, 0],
                      "custos": {str(p): {f"2026-{m:02d}": c for m, c in enumerate(cs, start=1)}
                                 for p, cs in _CUSTOS.items()},
                      "usa_custo_de": {str(p): o for p, o in _USA_CUSTO_DE.items()}},
}


# --- a validação das regras ----------------------------------------------------------------
def normalizar(texto) -> str:
    """Maiúsculas, sem acento e sem espaço repetido: como o segmento do ERP é comparado com o do mix."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().upper()
    return " ".join(t.split())


def _numero(valor, nome: str, minimo: float, maximo: float, inteiro: bool = False) -> float | int:
    try:
        v = float(valor) if not isinstance(valor, bool) and valor not in (None, "") else math.nan
    except (TypeError, ValueError):
        v = math.nan
    if not math.isfinite(v) or (inteiro and v != int(v)):
        raise ValueError(f"{nome}: digite um número{' inteiro' if inteiro else ''}")
    if not minimo <= v <= maximo:
        raise ValueError(f"{nome}: de {minimo:g} a {maximo:g}")
    return int(v) if inteiro else v


def _data(valor, nome: str) -> str:
    try:
        return dt.date.fromisoformat(str(valor)).isoformat()
    except ValueError:
        raise ValueError(f"{nome}: data inválida (use AAAA-MM-DD)") from None


def _mes(valor, nome: str) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-\d{2}", valor) or not 1 <= int(valor[5:]) <= 12:
        raise ValueError(f"{nome}: mês inválido (use AAAA-MM)")
    return valor


def _faixas(lista, nome: str, maximo: float) -> list[dict]:
    """[{de, pontos}]: do maior "de" para o menor, os pontos caindo junto; abaixo do último "de", 0."""
    if not isinstance(lista, list) or not lista:
        raise ValueError(f"{nome}: informe ao menos uma faixa")
    saida = sorted(({"de": _numero(f.get("de") if isinstance(f, dict) else None, f"{nome}: a partir de", 0, maximo),
                     "pontos": _numero(f.get("pontos") if isinstance(f, dict) else None, f"{nome}: pontos", 0, 100)}
                    for f in lista), key=lambda f: -f["de"])
    for a, b in zip(saida, saida[1:]):
        if a["de"] == b["de"]:
            raise ValueError(f"{nome}: duas faixas começam no mesmo valor ({a['de']:g})")
        if b["pontos"] > a["pontos"]:
            raise ValueError(f"{nome}: a faixa de baixo não pode valer mais pontos que a de cima")
    return saida


def _codigo(v, nome: str) -> int:
    if isinstance(v, bool):
        raise ValueError(f"{nome}: código de produto inválido")
    try:
        c = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{nome}: código de produto inválido") from None
    if c <= 0 or str(c) != str(v).strip():
        raise ValueError(f"{nome}: código de produto inválido")
    return c


def _mix(segmentos) -> dict:
    if not isinstance(segmentos, dict):
        raise ValueError("mix ideal inválido")
    saida = {}
    for nome, itens in segmentos.items():
        seg = normalizar(nome)
        if not seg:
            raise ValueError("mix ideal: segmento sem nome")
        if seg in saida:
            raise ValueError(f"mix ideal: o segmento {seg} aparece duas vezes")
        if not isinstance(itens, list):
            raise ValueError(f"mix ideal de {seg}: lista de itens inválida")
        lista, vistos = [], set()
        for item in itens:
            if not isinstance(item, dict):
                raise ValueError(f"mix ideal de {seg}: item inválido")
            if item.get("mussarela") is True:
                if "M" in vistos:
                    raise ValueError(f"mix ideal de {seg}: a mussarela aparece duas vezes")
                vistos.add("M")
                lista.append({"mussarela": True})
                continue
            produtos = item.get("produtos")
            if not isinstance(produtos, list) or not produtos:
                raise ValueError(f"mix ideal de {seg}: item sem produto")
            codigos = []
            for p in produtos:
                c = _codigo(p, f"mix ideal de {seg}")
                if c in vistos:
                    raise ValueError(f"mix ideal de {seg}: o produto {c} está em dois itens")
                vistos.add(c)
                codigos.append(c)
            lista.append({"produtos": codigos})
        if lista:  # o segmento sem item não tem mix (o cliente dele fica sinalizado)
            saida[seg] = lista
    return saida


def _custos(custos, usa) -> tuple[dict, dict]:
    if not isinstance(custos, dict) or not isinstance(usa, dict):
        raise ValueError("tabela de custos inválida")
    saida = {}
    for p, meses in custos.items():
        c = _codigo(p, "custos")
        if not isinstance(meses, dict):
            raise ValueError(f"custos do produto {c}: inválidos")
        linha = {}
        for m, v in meses.items():
            mes = _mes(m, f"custos do produto {c}")
            if v in (None, ""):
                continue  # mês sem custo
            linha[mes] = _numero(v, f"custo do produto {c} em {mes}", 0.000001, MAX_CUSTO)
        if linha:
            saida[str(c)] = dict(sorted(linha.items()))
    aliases = {}
    for p, outro in usa.items():
        a, b = _codigo(p, "usa o custo de"), _codigo(outro, "usa o custo de")
        if a == b:
            raise ValueError(f"o produto {a} não pode usar o próprio custo")
        aliases[str(a)] = b
    for a, b in aliases.items():
        if str(b) in aliases:
            raise ValueError(f"o produto {a} usa o custo do {b}, que também usa o de outro: aponte direto para o original")
        if a in saida:
            raise ValueError(f"o produto {a} tem custo próprio e também usa o custo do {b}: escolha um dos dois")
    return dict(sorted(saida.items(), key=lambda x: int(x[0]))), dict(sorted(aliases.items(), key=lambda x: int(x[0])))


def _valida(cfg: dict) -> dict:
    """Confere e normaliza as regras do CRM; levanta ValueError com a explicação."""
    cfg = cfg if isinstance(cfg, dict) else {}
    base = PADRAO
    equipes = cfg.get("equipes", base["equipes"])
    if not isinstance(equipes, list) or not equipes or any(e not in EQUIPES for e in equipes):
        raise ValueError("escolha ao menos uma equipe (ES, BA ou Edir)")
    a = cfg.get("aderencia") if isinstance(cfg.get("aderencia"), dict) else base["aderencia"]
    p = cfg.get("pontualidade") if isinstance(cfg.get("pontualidade"), dict) else base["pontualidade"]
    m = cfg.get("mix") if isinstance(cfg.get("mix"), dict) else base["mix"]
    r = cfg.get("rentabilidade") if isinstance(cfg.get("rentabilidade"), dict) else base["rentabilidade"]
    pontos_r = r.get("pontos", base["rentabilidade"]["pontos"])
    if not isinstance(pontos_r, list) or len(pontos_r) != 5:
        raise ValueError("rentabilidade: informe os pontos das 5 faixas (quintis)")
    pontos_r = [_numero(x, "rentabilidade: pontos", 0, 100) for x in pontos_r]
    if any(b > a_ for a_, b in zip(pontos_r, pontos_r[1:])):
        raise ValueError("rentabilidade: os pontos caem do quintil de cima para o de baixo")
    custos, usa = _custos(r.get("custos", {}), r.get("usa_custo_de", {}))
    saida = {
        "versao": 1,
        "equipes": [e for e in EQUIPES if e in equipes],
        "meses_para_entrar": _numero(cfg.get("meses_para_entrar", base["meses_para_entrar"]),
                                     "meses desde a primeira compra para entrar", 0, 24, inteiro=True),
        "aderencia": {
            "semanas": _numero(a.get("semanas", 26), "aderência: semanas do período", 4, 104, inteiro=True),
            "prazo_quinzenal": _numero(a.get("prazo_quinzenal", 15), "aderência: prazo do quinzenal", 7, 60, inteiro=True),
            "prazo_mensal": _numero(a.get("prazo_mensal", 31), "aderência: prazo do mensal", 14, 120, inteiro=True),
            "faixas": _faixas(a.get("faixas"), "aderência", 100),
        },
        "pontualidade": {
            "desde": _data(p.get("desde", "2024-01-01"), "pontualidade: títulos desde"),
            "tolerancia": _numero(p.get("tolerancia", 7), "pontualidade: tolerância", 0, 60, inteiro=True),
            "sem_titulo": _numero(p.get("sem_titulo", 20), "pontualidade: pontos de quem não tem título", 0, 100),
            "faixas": _faixas(p.get("faixas"), "pontualidade", 100),
            "descontos": _faixas(p.get("descontos"), "desconto pelo atraso médio", 3650),
        },
        "mix": {"pontos": _numero(m.get("pontos", 20), "mix: pontos", 0, 100), "segmentos": _mix(m.get("segmentos", {}))},
        "rentabilidade": {"desde": _mes(r.get("desde", "2026-01"), "rentabilidade: desde"), "pontos": pontos_r,
                          "custos": custos, "usa_custo_de": usa},
    }
    maximo = (saida["aderencia"]["faixas"][0]["pontos"] + saida["pontualidade"]["faixas"][0]["pontos"]
              + saida["mix"]["pontos"] + pontos_r[0])
    if abs(maximo - 100) > 1e-6:
        raise ValueError(f"os pontos máximos dos quatro indicadores somam {maximo:g}: precisam dar 100")
    if saida["pontualidade"]["sem_titulo"] > saida["pontualidade"]["faixas"][0]["pontos"]:
        raise ValueError("pontualidade: quem não tem título não pode ganhar mais que a faixa de cima")
    return saida


class ConfigCrm(RegrasNoBanco):
    """Regras da página CRM (tabela regras, nome "crm"): os números de cada indicador, o mix ideal de cada segmento e a
    tabela de custos industriais (com os produtos que usam o custo de outro)."""

    nome = "crm"
    _valida = staticmethod(_valida)

    def _padrao(self) -> dict:
        return copy.deepcopy(PADRAO)


# --- contas sem banco ----------------------------------------------------------------------------
def ultimo_sabado(hoje: dt.date) -> dt.date:
    """O último sábado antes de hoje (a semana de hoje ainda não fechou)."""
    return hoje - dt.timedelta(days=hoje.isoweekday() % 7 + 1)


def menos_meses(d: dt.date, n: int) -> dt.date:
    ano, mes = divmod(d.year * 12 + d.month - 1 - n, 12)
    ultimo = [31, 29 if ano % 4 == 0 and (ano % 100 or ano % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return dt.date(ano, mes + 1, min(d.day, ultimo[mes]))


def pontos_da_faixa(pct: float, faixas: list[dict]) -> float:
    """pct de 0 a 100: os pontos da primeira faixa (de cima para baixo) cujo "a partir de" ele alcança; nenhuma = 0."""
    for f in faixas:
        if pct >= f["de"] - 1e-9:
            return f["pontos"]
    return 0.0


def arredondar(x: float) -> int:
    return int(decimal.Decimal(str(x)).quantize(decimal.Decimal(1), rounding=decimal.ROUND_HALF_UP))


def cortes_quintis(valores: list[float]) -> list[float]:
    """Os quatro cortes (20%, 40%, 60% e 80%) do lucro total, do menor para o maior: o valor que fica na posição do
    corte, como o quantile_disc do DuckDB."""
    v = sorted(valores)
    if not v:
        return []
    return [v[max(0, math.ceil(p * len(v)) - 1)] for p in (0.2, 0.4, 0.6, 0.8)]


def pontos_rentabilidade(lucro: float, cortes: list[float], pontos: list[float]) -> tuple[float, int]:
    """(pontos, quintil 1 a 5; 1 = os maiores). Acima do corte de 80% é o quintil de cima, e assim por diante, para
    cada quintil ficar com 1/5 dos clientes. Quem não deixou lucro fica no último."""
    if lucro <= 0 or not cortes:
        return pontos[4], 5
    for quintil, corte in zip((1, 2, 3, 4), reversed(cortes)):
        if lucro > corte:
            return pontos[quintil - 1], quintil
    return pontos[4], 5


def custos_efetivos(cfg: dict) -> dict[int, dict[str, float]]:
    """{produto: {AAAA-MM: custo}}: os da tabela mais os produtos que usam o custo de outro."""
    r = cfg["rentabilidade"]
    saida = {int(p): dict(meses) for p, meses in r["custos"].items()}
    for p, outro in r["usa_custo_de"].items():
        if int(outro) in saida:
            saida[int(p)] = dict(saida[int(outro)])
    return saida


def _mes_seguinte(mes: str) -> dt.date:
    a, m = int(mes[:4]), int(mes[5:])
    return dt.date(a + m // 12, m % 12 + 1, 1)


# --- a importação da planilha de custos (Configurar) -------------------------------------------
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xml(dados: bytes):
    try:
        from defusedxml.ElementTree import fromstring  # vem com o fpdf2; protege de entidades externas
    except ImportError:  # sem ela, o expat do Python não busca entidades externas
        from xml.etree.ElementTree import fromstring
    return fromstring(dados)


def ler_planilha_custos(conteudo: bytes) -> dict:
    """Lê a primeira aba de uma planilha de custos no formato da "Custos Industriais": uma linha de cabeçalho com os
    meses (datas do Excel ou "jan/26", "2026-01"...), o produto numa coluna à esquerda e o custo de cada mês embaixo.
    Devolve {meses: [AAAA-MM], linhas: [{produto, custos: {mes: valor}}]}; custo 0 ou vazio fica de fora."""
    if not conteudo:
        raise ValueError("a planilha veio vazia")
    if len(conteudo) > MAX_PLANILHA:
        raise ValueError("a planilha passou de 5 MB")
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
        nomes = set(z.namelist())
        textos = []
        if "xl/sharedStrings.xml" in nomes:
            for si in _xml(z.read("xl/sharedStrings.xml")).findall(f"{_NS}si"):
                textos.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
        folha = next((n for n in sorted(nomes) if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), None)
        if folha is None:
            raise ValueError("a planilha não tem nenhuma aba")
        grade: dict[int, dict[int, object]] = {}
        for c in _xml(z.read(folha)).iter(f"{_NS}c"):
            ref = re.fullmatch(r"([A-Z]+)(\d+)", c.get("r") or "")
            v = c.find(f"{_NS}v")
            if not ref:
                continue
            col = 0
            for letra in ref.group(1):
                col = col * 26 + ord(letra) - 64
            if c.get("t") == "s" and v is not None:
                valor = textos[int(v.text)]
            elif c.get("t") == "inlineStr":
                valor = "".join(t.text or "" for t in c.iter(f"{_NS}t"))
            elif v is not None and v.text is not None:
                try:
                    valor = float(v.text)
                except ValueError:
                    valor = v.text
            else:
                continue
            grade.setdefault(int(ref.group(2)), {})[col] = valor
    except (zipfile.BadZipFile, KeyError, IndexError):
        raise ValueError("não deu para ler o arquivo: mande a planilha em .xlsx") from None

    def como_mes(v) -> str | None:
        if isinstance(v, float) and 36526 <= v <= 73051:  # data do Excel entre 2000 e 2099
            d = dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
            return f"{d.year}-{d.month:02d}"
        if isinstance(v, str):
            t = normalizar(v).lower()
            m = re.fullmatch(r"(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?", t)
            if m and 1 <= int(m.group(2)) <= 12:
                return f"{m.group(1)}-{int(m.group(2)):02d}"
            nomes_mes = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
            m = re.fullmatch(r"([a-z]{3})[a-z]*[\s/.-]*(?:de\s*)?(\d{2}|\d{4})", t)
            if m and m.group(1) in nomes_mes:
                ano = int(m.group(2)) + (2000 if len(m.group(2)) == 2 else 0)
                return f"{ano}-{nomes_mes.index(m.group(1)) + 1:02d}"
        return None

    cabecalho = None
    for n in sorted(grade):  # a primeira linha com dois ou mais meses
        meses = {col: como_mes(v) for col, v in grade[n].items()}
        meses = {col: m for col, m in meses.items() if m}
        if len(meses) >= 2:
            cabecalho = (n, meses)
            break
    if not cabecalho:
        raise ValueError("não achei a linha dos meses: o cabeçalho precisa ter os meses lado a lado")
    n_cab, cols = cabecalho
    primeira_col = min(cols)
    linhas = []
    for n in sorted(grade):
        if n <= n_cab:
            continue
        nome = next((v for col, v in sorted(grade[n].items(), reverse=True)
                     if col < primeira_col and isinstance(v, str) and v.strip()), None)
        if not nome:
            continue
        custos = {}
        for col, mes in cols.items():
            v = grade[n].get(col)
            if isinstance(v, float) and math.isfinite(v) and 0 < v <= MAX_CUSTO:
                custos[mes] = round(v, 6)
        linhas.append({"produto": " ".join(nome.split()), "custos": custos})
    if not linhas:
        raise ValueError("a planilha não tem nenhum produto embaixo da linha dos meses")
    return {"meses": sorted(set(cols.values())), "linhas": linhas}


# --- a página --------------------------------------------------------------------------------
class Crm:
    def __init__(self, calc, config: ConfigCrm, nomes_vendedores):
        self.calc = calc
        self.config = config
        self.nomes_vendedores = nomes_vendedores  # função: {vendedor: nome} (o da planilha de metas)
        self._trava = threading.Lock()
        self._trava_conta = threading.Lock()  # uma conta por vez (ver _dados)
        self._memo: tuple = (None, None)

    # ---------- o cálculo (todos os clientes de uma vez) ----------
    def _conferir(self):
        cache = self.calc.cache
        if not cache.pronto():
            raise RuntimeError("os dados ainda estão sendo preparados")
        if cache.antigo or cache.sem_pedidos:
            raise RuntimeError("os pedidos de venda ainda não chegaram do computador da empresa; o CRM aparece depois "
                               "da próxima atualização")

    def periodo(self, cfg: dict) -> dict:
        hoje = self.calc.cache.dia_da_copia()
        fim = ultimo_sabado(hoje)
        ini = fim - dt.timedelta(days=7 * cfg["aderencia"]["semanas"] - 1)
        return {"hoje": hoje, "ini": ini, "fim": fim, "corte": menos_meses(fim, cfg["meses_para_entrar"])}

    def _vendedores_das_equipes(self, cfg: dict) -> list[int]:
        regras = self.calc.regras()
        todos = {r[0] for r in self.calc.cache.consulta(
            "SELECT id FROM vendedores UNION SELECT DISTINCT COALESCE(id_vendedor, 0) FROM clientes")}
        return sorted(v for v in todos if regras.grupo_conhecido(v) in cfg["equipes"])

    def _dados(self) -> dict:
        self._conferir()
        cache = self.calc.cache
        cfg = self.config.atual()
        chave = (cache.info.get("extraido_em"), cache.info.get("banco_copia"), cache.info.get("data_ref"),
                 json.dumps(cfg, sort_keys=True), json.dumps(self.calc.regras().equivalentes, sort_keys=True))
        with self._trava:
            if self._memo[0] == chave:
                return self._memo[1]
        # Uma conta por vez: quem chega enquanto ela roda (várias pessoas abrindo a página logo depois de uma cópia nova
        # do ERP) espera e usa o resultado, em vez de cada um refazer a conta inteira.
        with self._trava_conta:
            with self._trava:
                if self._memo[0] == chave:
                    return self._memo[1]
            dados = self._calcular(cfg)
            with self._trava:
                self._memo = (chave, dados)
        return dados

    def _calcular(self, cfg: dict) -> dict:
        cache = self.calc.cache
        per = self.periodo(cfg)
        vend = self._vendedores_das_equipes(cfg)
        nomes_v = self.nomes_vendedores()
        avisos = []
        rede = "r.rede" if not cache.sem_rede else "CAST(NULL AS VARCHAR)"
        junta_rede = "LEFT JOIN clientes_rede r ON r.id = c.id" if not cache.sem_rede else ""
        if cache.sem_rede:
            avisos.append("As redes dos clientes ainda não chegaram do computador da empresa: todos contam como semanais.")
        linhas = cache.consulta(f"""
            WITH clis AS (
              SELECT c.id, c.nome, COALESCE(c.id_vendedor, 0) AS id_vendedor, d.segmento, d.cidade, d.uf, {rede} AS rede
              FROM clientes c
              JOIN clientes_detalhes d ON d.id = c.id AND COALESCE(d.inativo, 0) = 0
              {junta_rede}
              WHERE COALESCE(c.id_vendedor, 0) IN (SELECT unnest(?::INTEGER[]))
                AND upper(COALESCE(c.nome, '')) NOT LIKE '%PEDIDO BLOQUEADO%'
            ),
            primeiras AS (
              SELECT p.id_cliente, min(p.data) AS primeira FROM pedidos_venda p
              WHERE p.tipocliente = 'CLIENTE' AND p.cancelada = 0 AND p.tipopedido = 'PEDIDOVENDA' AND p.data <= ?
                AND p.id_cliente IN (SELECT id FROM clis)
              GROUP BY 1
            )
            SELECT k.id, k.nome, k.id_vendedor, k.segmento, k.cidade, k.uf, k.rede, f.primeira
            FROM clis k LEFT JOIN primeiras f ON f.id_cliente = k.id""", [vend, per["fim"]])
        clientes, fora = {}, []
        for id_, nome, v, segmento, cidade, uf, rede_txt, primeira in linhas:
            semanas = semanas_da_frequencia(rede_txt) or 1
            freq = (FREQUENCIAS[semanas] if semanas_da_frequencia(rede_txt) else
                    ("outra rede" if rede_txt and str(rede_txt).strip() else "sem rede"))
            c = {"id": int(id_), "nome": nome_cliente(nome),
                 "vendedor": {"id": int(v), "nome": nomes_v.get(int(v), f"Vendedor {v}")},
                 "segmento": (segmento or "").strip() or None, "cidade": cidade, "uf": uf,
                 "rede": (rede_txt or "").strip() or None, "frequencia": freq, "semanas": semanas,
                 "primeira": primeira}
            if primeira is None:
                fora.append({"vendedor": int(v), "motivo": "sem_compra"})
            elif primeira >= per["corte"]:
                fora.append({"vendedor": int(v), "motivo": "recente"})
            else:
                clientes[c["id"]] = c
        ids = sorted(clientes)
        self._aderencia(cfg, per, clientes, ids)
        self._pontualidade(cfg, per, clientes, ids, avisos)
        self._mix(cfg, per, clientes, ids, avisos)
        rent = self._rentabilidade(cfg, per, clientes, ids, avisos)
        for c in clientes.values():
            exata = sum((c[k] or {}).get("pontos") or 0 for k in ("aderencia", "pontualidade", "mix", "rentabilidade"))
            c["nota_exata"] = round(exata, 4)
            c["nota"] = arredondar(exata)
            c["sinais"] = [s for s in ((c["mix"] or {}).get("sinal"), (c["pontualidade"] or {}).get("sinal")) if s]
        return {"clientes": clientes, "fora": fora, "periodo": per, "rentabilidade": rent, "avisos": avisos, "cfg": cfg}

    def _aderencia(self, cfg, per, clientes, ids):
        a = cfg["aderencia"]
        prazo = {1: 7, 2: a["prazo_quinzenal"], 4: a["prazo_mensal"]}
        lst = [clientes[i] for i in ids]
        linhas = self.calc.cache.consulta("""
            WITH par AS (SELECT CAST(? AS DATE) AS ini, CAST(? AS DATE) AS fim),
            base AS (SELECT unnest(?::INTEGER[]) AS id, unnest(?::INTEGER[]) AS prazo, unnest(?::DATE[]) AS primeira),
            b2 AS (
              SELECT b.*, CASE WHEN b.primeira > par.ini THEN date_diff('day', par.ini, b.primeira) // 7 ELSE 0 END AS s,
                     greatest(par.ini, b.primeira) AS inicio_cli
              FROM base b CROSS JOIN par
            ),
            pedidos AS (
              SELECT DISTINCT p.id_cliente, p.data FROM pedidos_venda p
              WHERE p.tipocliente = 'CLIENTE' AND p.cancelada = 0 AND p.tipopedido = 'PEDIDOVENDA'
                AND p.data <= (SELECT fim FROM par) AND p.id_cliente IN (SELECT id FROM base)
            ),
            -- uma compra por semana (domingo a sabado): a primeira; as outras da mesma semana nao contam
            contadas AS (
              SELECT id_cliente, min(data) AS dia FROM pedidos
              GROUP BY id_cliente, data - CAST(isodow(data) % 7 AS INTEGER)
            ),
            semanas_cc AS (
              SELECT b.id, count(*) AS com_compra
              FROM contadas x JOIN b2 b ON b.id = x.id_cliente CROSS JOIN par
              WHERE x.dia BETWEEN b.inicio_cli AND par.fim
              GROUP BY 1
            ),
            ancoras AS (
              SELECT id_cliente, dia AS data FROM contadas
              UNION ALL SELECT id, DATE '1900-01-01' FROM base
            ),
            -- cada compra deixa o cliente em dia pelo prazo; cada dia alem dele, dentro do periodo, e atraso
            atrasos AS (
              SELECT b.id,
                     sum(greatest(0, date_diff('day', greatest(z.data + b.prazo, b.inicio_cli),
                                               least(COALESCE(z.proxima, par.fim + 1) - 1, par.fim)) + 1)) AS atraso,
                     max(CASE WHEN z.data > DATE '1900-01-01' AND z.proxima BETWEEN b.inicio_cli AND par.fim
                              THEN date_diff('day', z.data, z.proxima) END) AS maior_distancia,
                     date_diff('day', b.inicio_cli, par.fim) + 1 AS dias
              FROM (SELECT id_cliente, data, lead(data) OVER (PARTITION BY id_cliente ORDER BY data) AS proxima
                    FROM ancoras) z
              JOIN b2 b ON b.id = z.id_cliente CROSS JOIN par
              GROUP BY b.id, b.inicio_cli, par.fim
            )
            SELECT b.id, b.s, b.inicio_cli, COALESCE(w.com_compra, 0), t.atraso, t.dias, t.maior_distancia
            FROM b2 b LEFT JOIN semanas_cc w ON w.id = b.id LEFT JOIN atrasos t ON t.id = b.id""",
            [per["ini"], per["fim"], ids, [prazo[c["semanas"]] for c in lst], [c["primeira"] for c in lst]])
        total = a["semanas"]
        for id_, s, inicio, com_compra, atraso, dias, maior in linhas:
            c = clientes[int(id_)]
            if c["semanas"] == 1:  # semanal: as semanas com compra desde a semana da primeira compra
                n = total - int(s)
                pct = 100.0 * com_compra / n if n > 0 else 0.0
                r = {"regra": "semanas", "com_compra": int(com_compra), "semanas": n}
            else:
                pct = 100.0 * (dias - atraso) / dias if dias else 0.0
                r = {"regra": "prazo", "prazo": prazo[c["semanas"]], "atraso": int(atraso or 0), "dias": int(dias or 0)}
            r.update(pct=round(pct, 2), inicio=inicio, maior_distancia=int(maior) if maior is not None else None,
                     pontos=float(pontos_da_faixa(pct, a["faixas"])))
            c["aderencia"] = r

    def _pontualidade(self, cfg, per, clientes, ids, avisos):
        p = cfg["pontualidade"]
        if self.calc.cache.sem_credito:
            avisos.append("Os títulos a receber ainda não chegaram do computador da empresa: a pontualidade fica sem nota.")
            for c in clientes.values():
                c["pontualidade"] = None
            return
        hoje, tol = per["hoje"], p["tolerancia"]
        linhas = {int(r[0]): r for r in self.calc.cache.consulta("""
            WITH base AS (SELECT unnest(?::INTEGER[]) AS id),
            tit AS (
              SELECT t.id_cliente, t.quitado,
                     COALESCE(t.quitado = 1 AND t.quitacao <= t.vencimento + CAST(? AS INTEGER), false) AS pontual,
                     CASE WHEN t.quitado = 1 THEN date_diff('day', t.vencimento, t.quitacao)
                          ELSE date_diff('day', t.vencimento, CAST(? AS DATE)) END AS dias
              FROM titulos_receber t
              WHERE t.id_cliente IN (SELECT id FROM base) AND t.vencimento >= CAST(? AS DATE)
                AND t.vencimento < CAST(? AS DATE)
            )
            SELECT id_cliente, count(*), count(*) FILTER (WHERE pontual), avg(dias) FILTER (WHERE NOT pontual),
                   count(*) FILTER (WHERE NOT pontual AND quitado = 0)
            FROM tit GROUP BY 1""",
            [ids, tol, hoje, dt.date.fromisoformat(p["desde"]), hoje - dt.timedelta(days=tol)])}
        for id_, c in clientes.items():
            r = linhas.get(id_)
            if not r or not r[1]:
                c["pontualidade"] = {"titulos": 0, "pontos": float(p["sem_titulo"]), "sinal": "sem título a receber desde "
                                     + dt.date.fromisoformat(p["desde"]).strftime("%d/%m/%Y")}
                continue
            titulos, pontuais, atraso_medio, em_aberto = int(r[1]), int(r[2]), r[3], int(r[4])
            pct = 100.0 * pontuais / titulos
            base = float(pontos_da_faixa(pct, p["faixas"]))
            desconto = float(pontos_da_faixa(atraso_medio, p["descontos"])) if atraso_medio is not None else 0.0
            c["pontualidade"] = {"titulos": titulos, "pontuais": pontuais, "pct": round(pct, 2),
                                 "atraso_medio": round(float(atraso_medio), 1) if atraso_medio is not None else None,
                                 "em_aberto": em_aberto, "base": base, "desconto": desconto,
                                 "pontos": max(0.0, base - desconto)}

    def _equivalentes(self) -> tuple[list[int], list[int]]:
        eq = self.calc.regras().equivalentes
        return [int(k) for k in eq], [int(v) for v in eq.values()]

    def _itens_mix(self, cfg) -> tuple[list[str], list[int], list[int]]:
        """As três listas paralelas (segmento, item, produto; produto 0 = qualquer mussarela) que a consulta usa."""
        segs, itens, prods = [], [], []
        for seg, lista in cfg["mix"]["segmentos"].items():
            for n, item in enumerate(lista):
                for p in ([0] if item.get("mussarela") else item["produtos"]):
                    segs.append(seg)
                    itens.append(n)
                    prods.append(int(p))
        return segs, itens, prods

    def _mix(self, cfg, per, clientes, ids, avisos):
        cache, m = self.calc.cache, cfg["mix"]
        segmentos = m["segmentos"]
        if cache.sem_pedidos_detalhe:
            avisos.append("Os pedidos um a um ainda não chegaram do computador da empresa: o mix fica sem nota.")
            for c in clientes.values():
                c["mix"] = None
            return
        atendidos = {}
        if ids and segmentos:
            de, para = self._equivalentes()
            segs, itens, prods = self._itens_mix(cfg)
            lst = [clientes[i] for i in ids]
            for id_, lista in cache.consulta("""
                WITH par AS (SELECT CAST(? AS DATE) AS fim),
                base AS (SELECT unnest(?::INTEGER[]) AS id, unnest(?::VARCHAR[]) AS seg, unnest(?::DATE[]) AS inicio_cli),
                cods AS (SELECT unnest(?::VARCHAR[]) AS seg, unnest(?::INTEGER[]) AS item, unnest(?::INTEGER[]) AS cod),
                eq AS (SELECT unnest(?::INTEGER[]) AS de, unnest(?::INTEGER[]) AS para),
                ideal AS (
                  SELECT seg, item, cod AS id_produto FROM cods WHERE cod > 0
                  UNION ALL
                  SELECT c.seg, c.item, p.id FROM cods c JOIN produtos p ON upper(COALESCE(p.linha, '')) LIKE ?
                  WHERE c.cod = 0
                ),
                compras AS (
                  SELECT DISTINCT d.id_cliente, COALESCE(e.para, i.id_produto) AS id_produto
                  FROM pedidos_venda_detalhe d
                  JOIN pedidos_venda_itens i ON i.id_pedido = d.id
                  JOIN base b ON b.id = d.id_cliente CROSS JOIN par
                  LEFT JOIN eq e ON e.de = i.id_produto
                  WHERE d.tipocliente = 'CLIENTE' AND NOT d.cancelada AND d.tipopedido = 'PEDIDOVENDA'
                    AND d.data BETWEEN b.inicio_cli AND par.fim AND i.quantidade > 0
                )
                SELECT b.id, list_sort(list(DISTINCT i.item))
                FROM base b JOIN ideal i ON i.seg = b.seg
                JOIN compras x ON x.id_cliente = b.id AND x.id_produto = i.id_produto
                GROUP BY 1""", [per["fim"], ids, [normalizar(c["segmento"]) for c in lst],
                                [c["aderencia"]["inicio"] for c in lst], segs, itens, prods, de, para,
                                f"%{LINHA_MUSSARELA}%"]):
                atendidos[int(id_)] = [int(x) for x in lista]
        for id_, c in clientes.items():
            seg = normalizar(c["segmento"])
            lista = segmentos.get(seg)
            if not lista:
                c["mix"] = {"itens": 0, "atendidos": 0, "pontos": 0.0,
                            "sinal": "sem segmento no cadastro" if not seg else f"segmento {c['segmento']} sem mix ideal"}
                continue
            feitos = atendidos.get(id_, [])
            c["mix"] = {"itens": len(lista), "atendidos": len(feitos), "atendidos_itens": feitos,
                        "pontos": round(m["pontos"] * len(feitos) / len(lista), 4)}

    def _rentabilidade(self, cfg, per, clientes, ids, avisos) -> dict:
        cache, r = self.calc.cache, cfg["rentabilidade"]
        custos = custos_efetivos(cfg)
        meses = sorted({m for linha in custos.values() for m in linha if m >= r["desde"]})
        info = {"desde": r["desde"], "ate": meses[-1] if meses else None, "cortes": [], "sem_custo": []}
        if cache.sem_detalhe or not meses:
            avisos.append("A rentabilidade fica sem nota: " + ("as vendas por cliente ainda não chegaram do computador "
                          "da empresa." if cache.sem_detalhe else "ainda não há custo industrial em Configurar."))
            for c in clientes.values():
                c["rentabilidade"] = None
            return info
        de, para = self._equivalentes()
        prods, mes_c, valores = [], [], []
        for p, linha in custos.items():
            for mes, v in linha.items():
                if r["desde"] <= mes <= meses[-1]:
                    prods.append(p)
                    mes_c.append(dt.date.fromisoformat(mes + "-01"))
                    valores.append(float(v))
        ini, fim = dt.date.fromisoformat(r["desde"] + "-01"), _mes_seguinte(meses[-1])
        params = [ids, prods, mes_c, valores, de, para, ini, fim]
        comum = """
            WITH base AS (SELECT unnest(?::INTEGER[]) AS id),
            custos AS (SELECT unnest(?::INTEGER[]) AS id_produto, unnest(?::DATE[]) AS mes, unnest(?::DOUBLE[]) AS custo),
            eq AS (SELECT unnest(?::INTEGER[]) AS de, unnest(?::INTEGER[]) AS para),
            vendas AS (
              SELECT CAST(date_trunc('month', v.data) AS DATE) AS mes, v.id_cliente,
                     COALESCE(e.para, v.id_produto) AS id_produto, sum(v.valor) AS valor, sum(v.quantidade) AS qtd
              FROM vendas_clientes_itens v LEFT JOIN eq e ON e.de = v.id_produto
              WHERE v.tipocliente = 'CLIENTE' AND v.data >= CAST(? AS DATE) AND v.data < CAST(? AS DATE)
                AND v.id_cliente IN (SELECT id FROM base)
              GROUP BY 1, 2, 3
            )"""
        por = {int(x[0]): x for x in cache.consulta(comum + """
            SELECT v.id_cliente, sum(v.valor), COALESCE(sum(v.valor) FILTER (WHERE c.custo IS NULL), 0),
                   COALESCE(sum(v.valor - c.custo * v.qtd) FILTER (WHERE c.custo IS NOT NULL), 0)
            FROM vendas v LEFT JOIN custos c ON c.id_produto = v.id_produto AND c.mes = v.mes
            GROUP BY 1""", params)}
        nomes = dict(cache.consulta("SELECT id, nome FROM produtos"))
        for p, lista, valor in cache.consulta(comum + """
            SELECT v.id_produto, list_sort(list(DISTINCT strftime(v.mes, '%Y-%m'))), sum(v.valor)
            FROM vendas v LEFT JOIN custos c ON c.id_produto = v.id_produto AND c.mes = v.mes
            WHERE c.custo IS NULL GROUP BY 1 ORDER BY 3 DESC""", params):
            info["sem_custo"].append({"id": int(p), "nome": nomes.get(p, f"Produto {p}"), "meses": list(lista),
                                      "faturamento": round(float(valor), 2)})
        if info["sem_custo"]:
            n = len(info["sem_custo"])
            total = f"{sum(x['faturamento'] for x in info['sem_custo']):,.2f}"
            total = total.replace(",", "#").replace(".", ",").replace("#", ".")  # 1.234,56
            avisos.append(f"{n} produto{'s' if n > 1 else ''} vendido{'s' if n > 1 else ''} sem custo industrial no "
                          f"período (R$ {total} de faturamento) fica{'m' if n > 1 else ''} fora do lucro bruto; os "
                          "custos ficam em CRM › Configurar.")
        lucros = {}
        for id_ in ids:
            x = por.get(id_)
            lucros[id_] = float(x[3]) if x else 0.0
        cortes = cortes_quintis(list(lucros.values()))
        info["cortes"] = [round(c, 2) for c in cortes]
        for id_, c in clientes.items():
            x = por.get(id_)
            fat, sem, lucro = (float(x[1]), float(x[2]), float(x[3])) if x else (0.0, 0.0, 0.0)
            pts, quintil = pontos_rentabilidade(lucro, cortes, r["pontos"])
            com_custo = fat - sem
            c["rentabilidade"] = {"faturamento": round(fat, 2), "sem_custo": round(sem, 2), "lucro": round(lucro, 2),
                                  "margem": round(100.0 * lucro / com_custo, 2) if com_custo > 0 else None,
                                  "quintil": quintil, "pontos": float(pts)}
        return info

    # ---------- a lista e o detalhe ----------
    @staticmethod
    def _visivel(c: dict, ids) -> bool:
        return ids is None or c["vendedor"]["id"] in ids

    @staticmethod
    def _iso(v):
        return v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v

    def _linha(self, c: dict) -> dict:
        r = {k: v for k, v in c.items() if k not in ("semanas",)}
        r["primeira"] = self._iso(c["primeira"])
        if r.get("aderencia"):
            r["aderencia"] = {**r["aderencia"], "inicio": self._iso(r["aderencia"]["inicio"])}
        if r.get("mix"):
            r["mix"] = {k: v for k, v in r["mix"].items() if k != "atendidos_itens"}
        return r

    def _regras_resumo(self, d: dict) -> dict:
        cfg, per = d["cfg"], d["periodo"]
        return {"aderencia": {k: cfg["aderencia"][k] for k in ("semanas", "prazo_quinzenal", "prazo_mensal", "faixas")},
                "pontualidade": {k: cfg["pontualidade"][k] for k in ("desde", "tolerancia", "faixas", "descontos",
                                                                     "sem_titulo")},
                "mix": {"pontos": cfg["mix"]["pontos"]},
                "rentabilidade": {"pontos": cfg["rentabilidade"]["pontos"], **{k: d["rentabilidade"][k]
                                                                               for k in ("desde", "ate", "cortes")}},
                "equipes": cfg["equipes"], "meses_para_entrar": cfg["meses_para_entrar"],
                "periodo": {k: self._iso(v) for k, v in per.items()}}

    def listar(self, ids) -> dict:
        """Os clientes do CRM dos vendedores do acesso (ids: os vendedores; None = todos), com a nota e os quatro
        indicadores, e quantos ficaram fora do CRM (sem compra ou com a primeira compra há menos de 1 mês)."""
        d = self._dados()
        itens = [self._linha(c) for c in d["clientes"].values() if self._visivel(c, ids)]
        itens.sort(key=lambda c: (-c["nota_exata"], c["nome"]))
        fora = [f for f in d["fora"] if ids is None or f["vendedor"] in ids]
        por_vendedor: dict[int, dict] = {}  # para o filtro de vendedores da página valer também em quem ficou fora
        for f in fora:
            v = por_vendedor.setdefault(f["vendedor"], {"sem_compra": 0, "recente": 0})
            v[f["motivo"]] += 1
        return {"itens": itens, "fora": {"sem_compra": sum(f["motivo"] == "sem_compra" for f in fora),
                                         "recente": sum(f["motivo"] == "recente" for f in fora)},
                "fora_vendedores": por_vendedor,
                "regras": self._regras_resumo(d), "avisos": d["avisos"], "sem_custo": d["rentabilidade"]["sem_custo"],
                "data_ref": self.calc.cache.info.get("data_ref"), "dados_ate": self.calc.cache.info.get("extraido_em")}

    def cliente(self, ids, id_cliente) -> dict:
        """O porquê da nota de um cliente: as compras do semestre, os itens do mix (atendidos e os que faltam) e o
        lucro bruto mês a mês e por produto."""
        try:
            id_ = int(id_cliente)
        except (TypeError, ValueError):
            raise ValueError("cliente inválido") from None
        d = self._dados()
        c = d["clientes"].get(id_)
        if c is None or not self._visivel(c, ids):
            raise NaoEncontrada("cliente fora do CRM ou do seu acesso")
        cache, cfg, per = self.calc.cache, d["cfg"], d["periodo"]
        r = self._linha(c)
        inicio = c["aderencia"]["inicio"]
        r["compras"] = [x[0].isoformat() for x in cache.consulta("""
            SELECT min(data) FROM (SELECT DISTINCT data FROM pedidos_venda WHERE id_cliente = ? AND tipocliente = 'CLIENTE'
                AND cancelada = 0 AND tipopedido = 'PEDIDOVENDA' AND data BETWEEN ? AND ?) x
            GROUP BY data - CAST(isodow(data) % 7 AS INTEGER) ORDER BY 1""", [id_, inicio, per["fim"]])]
        nomes = dict(cache.consulta("SELECT id, nome FROM produtos"))
        lista = cfg["mix"]["segmentos"].get(normalizar(c["segmento"])) or []
        if lista and c.get("mix") is not None:
            feitos = set(c["mix"].get("atendidos_itens") or [])
            r["mix_itens"] = [{"nome": "Qualquer mussarela" if it.get("mussarela")
                               else " ou ".join(nomes.get(p, f"Produto {p}") for p in it["produtos"]),
                               "atendido": n in feitos} for n, it in enumerate(lista)]
        if c.get("rentabilidade") is not None and d["rentabilidade"]["ate"]:
            custos = custos_efetivos(cfg)
            rr = cfg["rentabilidade"]
            de, para = self._equivalentes()
            prods, mes_c, valores = [], [], []
            for p, linha in custos.items():
                for mes, v in linha.items():
                    if rr["desde"] <= mes <= d["rentabilidade"]["ate"]:
                        prods.append(p)
                        mes_c.append(dt.date.fromisoformat(mes + "-01"))
                        valores.append(float(v))
            linhas = cache.consulta("""
                WITH custos AS (SELECT unnest(?::INTEGER[]) AS id_produto, unnest(?::DATE[]) AS mes,
                                       unnest(?::DOUBLE[]) AS custo),
                eq AS (SELECT unnest(?::INTEGER[]) AS de, unnest(?::INTEGER[]) AS para),
                vendas AS (
                  SELECT CAST(date_trunc('month', v.data) AS DATE) AS mes, COALESCE(e.para, v.id_produto) AS id_produto,
                         sum(v.valor) AS valor, sum(v.quantidade) AS qtd
                  FROM vendas_clientes_itens v LEFT JOIN eq e ON e.de = v.id_produto
                  WHERE v.id_cliente = ? AND v.tipocliente = 'CLIENTE' AND v.data >= CAST(? AS DATE)
                    AND v.data < CAST(? AS DATE)
                  GROUP BY 1, 2
                )
                SELECT v.mes, v.id_produto, v.valor, v.qtd, c.custo
                FROM vendas v LEFT JOIN custos c ON c.id_produto = v.id_produto AND c.mes = v.mes
                ORDER BY 1, 2""", [prods, mes_c, valores, de, para, id_,
                                   dt.date.fromisoformat(rr["desde"] + "-01"), _mes_seguinte(d["rentabilidade"]["ate"])])
            meses, produtos = {}, {}
            for mes, p, valor, qtd, custo in linhas:
                lucro = (float(valor) - float(custo) * float(qtd)) if custo is not None else None
                m = meses.setdefault(mes.isoformat()[:7], {"mes": mes.isoformat()[:7], "faturamento": 0.0, "lucro": 0.0,
                                                           "sem_custo": 0.0})
                pr = produtos.setdefault(int(p), {"id": int(p), "nome": nomes.get(p, f"Produto {p}"), "volume": 0.0,
                                                  "faturamento": 0.0, "lucro": 0.0, "sem_custo": 0.0})
                for alvo in (m, pr):
                    alvo["faturamento"] += float(valor)
                    if lucro is None:
                        alvo["sem_custo"] += float(valor)
                    else:
                        alvo["lucro"] += lucro
                pr["volume"] += float(qtd)
            arred = lambda x: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in x.items()}  # noqa: E731
            r["rent_meses"] = [arred(m) for m in meses.values()]
            r["rent_produtos"] = sorted((arred(p) for p in produtos.values()), key=lambda p: -p["lucro"])
        r["regras"] = self._regras_resumo(d)
        return r

    def excel(self, ids) -> tuple[bytes, str]:
        from . import arquivos
        d = self.listar(ids)
        per = d["regras"]["periodo"]
        colunas = ["Cliente", "Código", "Vendedor", "Segmento", "Cidade", "Frequência", "Nota", "Aderência",
                   "Pontualidade", "Mix", "Rentabilidade", "Lucro bruto (R$)", "Margem bruta %", "Sinalização"]
        linhas = []
        for c in d["itens"]:
            pts = lambda k: (c.get(k) or {}).get("pontos")  # noqa: E731
            rent = c.get("rentabilidade") or {}
            linhas.append([c["nome"], c["id"], c["vendedor"]["nome"], c["segmento"] or "", c["cidade"] or "",
                           c["frequencia"], c["nota"], pts("aderencia"), pts("pontualidade"), pts("mix"),
                           pts("rentabilidade"), rent.get("lucro"), rent.get("margem"), "; ".join(c["sinais"])])
        hoje = dt.date.fromisoformat(per["hoje"])
        info = (f"Semestre de {dt.date.fromisoformat(per['ini']):%d/%m/%Y} a {dt.date.fromisoformat(per['fim']):%d/%m/%Y}"
                f" · dados até {d['data_ref'] or '—'}")
        conteudo = arquivos.excel("CRM - nota dos clientes", "Nota de 0 a 100: aderência, pontualidade, mix e "
                                  "rentabilidade", info, colunas, linhas)
        return conteudo, arquivos.nome_arquivo("CRM - nota dos clientes", arquivos.EXCEL, hoje)

    # ---------- o Configurar ----------
    def config_dados(self) -> dict:
        """As regras em vigor, quem salvou por último e, para os editores, os produtos e os segmentos do ERP."""
        cfg = self.config.atual()
        ultima = None
        with self.config.banco.conexao() as con:
            linha = con.execute("SELECT salva_em, salva_por_nome FROM regras WHERE nome = %s ORDER BY id DESC LIMIT 1",
                                [self.config.nome]).fetchone()
            if linha:
                ultima = {"em": hora(linha[0]), "por": linha[1]}
        produtos, segmentos = [], []
        cache = self.calc.cache
        if cache.pronto():
            vendidos = {r[0] for r in cache.consulta(
                "SELECT DISTINCT id_produto FROM vendas_itens WHERE data >= ?",
                [dt.date.fromisoformat(cfg["rentabilidade"]["desde"] + "-01")])}
            produtos = [{"id": int(i), "nome": n, "linha": l, "unidade": u, "inativo": bool(ina),
                         "vendido": int(i) in vendidos, "mussarela": LINHA_MUSSARELA in (l or "").upper()}
                        for i, n, l, u, ina in cache.consulta(
                            "SELECT id, nome, linha, unidade, COALESCE(inativo, 0) FROM produtos ORDER BY nome")]
            if not cache.sem_detalhe:
                segmentos = [{"nome": s, "chave": normalizar(s), "clientes": int(n)} for s, n in cache.consulta(
                    "SELECT segmento, count(*) FROM clientes_detalhes WHERE COALESCE(inativo, 0) = 0 "
                    "AND segmento IS NOT NULL AND trim(segmento) <> '' GROUP BY 1 ORDER BY 1")]
        return {"config": cfg, "padrao": copy.deepcopy(PADRAO), "ultima": ultima, "produtos": produtos,
                "segmentos": segmentos, "equipes": list(EQUIPES)}

    def importar_custos(self, conteudo: bytes) -> dict:
        """A planilha de custos lida e ligada aos produtos do ERP pelo nome (sem acento e caixa). O que não achou volta
        com o nome da planilha, para a pessoa escolher o produto na tela; nada é gravado aqui."""
        lida = ler_planilha_custos(conteudo)
        por_nome = {}
        if self.calc.cache.pronto():
            for i, n in self.calc.cache.consulta("SELECT id, nome FROM produtos"):
                por_nome.setdefault(normalizar(n), int(i))
        for linha in lida["linhas"]:
            linha["id"] = por_nome.get(normalizar(linha["produto"]))
        return lida

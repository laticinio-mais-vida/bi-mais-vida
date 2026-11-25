"""A capa de análise de crédito (página Reavaliação de Crédito, botão "Capa de análise de crédito"): a "Capa de Análise
de Crédito" e a indicação de prazo e limite do quadro LIMITES da planilha "Classificação e Limites", as duas do usuário.
A mesma capa serve para um cadastro novo (o cliente ainda não está no ERP) e para uma reanálise (um cliente do ERP); a
reanálise de antes, pelo parecer da página de crédito (bi/reanalise.py), continua como estava.

- A capa tem 14 itens com peso (soma 100). Os do Serasa saem do PDF do Relato PJ (bi/serasa.py). Os do "histórico Mais
  Vida" saem do ERP: na reanálise, do próprio cliente; no cadastro novo, só quando o CNPJ já é cliente (senão valem 0).
  Os comerciais e o jurídico (Mosselo) são do analista. Quando há anotações negativas, ou o PDF não traz um item, quem
  escolhe é o analista.
- A pontuação dá a faixa (menos de 40 = sem faixa: venda à vista). O porte da empresa, escolhido pelo analista, dá o
  bloco do quadro: Pequena = 1º bloco, Pequena para média = 2º, Média = 3º, Média para grande = 4º; Grande = o 4º e,
  acima dele, a negociação com a diretoria (decisão do usuário, 2026-11-25: até então valiam os blocos de cima também,
  e a Pequena para média com 55 pontos saía com R$ 400 sugeridos, do 1º bloco, em vez de R$ 1.000).
  - O limite sugerido é o menor valor da coluna da faixa no bloco do porte, e o máximo é o maior.
  - O prazo tem as parcelas da faixa, até o máximo do porte. O sugerido usa os dias mais baixos de cada parcela (5, 12,
    19, 26) e o máximo, os mais altos (7, 14, 21, 29).
  - O prazo concedido está dentro do indicado quando não tem mais parcelas que ele e o último dia não passa do último
    dia do máximo: com "07 E 14 DIAS", 12 ou 14 dias estão dentro e 15 não.
  - À vista ou 01 dia é venda antecipada (o cliente paga antes de o pedido ser faturado): qualquer limite vale, e o
    prazo está sempre dentro, mesmo sem faixa.
- Cada capa é uma linha nova na tabela credito_capas (migração 046) e não muda depois. Quem registrou ou um
  administrador pode excluir (a linha fica guardada, com excluida_em) ou editar: a edição grava uma versão nova e a de
  antes fica guardada como substituída (migração 049). Na edição, os itens automáticos (Serasa e histórico Mais Vida)
  ficam como foram registrados; mudam as respostas do analista, o porte, o vendedor, o concedido e os textos. Só no
  site (ativo).
- A lista das capas busca pelo nome do cliente, pela razão social, pelo CNPJ ou pelo código do cliente.
- A capa de cadastro novo liga ao cliente pelo CNPJ quando ele entra no ERP (tabela clientes_cnpj do cache), na
  leitura, sem gravar. A página do cliente mostra as capas dele (reanálise e cadastro novo) com as reanálises, e o prazo
  mínimo entre reanálises conta a partir da última (bi/reanalise.py); um aumento na capa de reanálise esbarra nele
  como na reanálise.
- Os pesos e o quadro ficam aqui, fixos como a regra do parecer de bi/credito.py; REGRA_VERSAO sobe quando mudam.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import unicodedata

from .acesso import eh_admin
from .banco import hora
from .conversas import NaoEncontrada, id_valido, novo_id
from .credito import dias_prazo
from .reanalise import TRAVA, texto_bloqueio
from .serasa import CAMPOS as CAMPOS_SERASA

REGRA_VERSAO = 2  # 2 (2026-11-25): o limite sai só do bloco do porte; prazo pelo último dia; venda antecipada
AVISO_PC = ("As capas de análise de crédito ficam no site (bi.maisvida.cloud), junto com as reanálises: faça e consulte "
            "por lá.")
DADOS_NOVOS = ("os dados do ERP foram atualizados enquanto você analisava: confira a capa de novo antes de registrar")
MIN_JUSTIFICATIVA = 10
MAX_TEXTO = 2000
MAX_NOME = 200
MAX_LIMITE = 100_000_000  # R$: acima disso é engano de digitação
MAX_LISTA = 100
COMPRAS_RECENTES = 45  # dias da "última compra" do histórico Mais Vida
FREQUENCIA = 90        # dias da "frequência de compras" (os últimos 3 meses)


def _item(chave: str, grupo: str, eixo: str, peso: int, origem: str, *opcoes: tuple[str, str, int]) -> dict:
    return {"chave": chave, "grupo": grupo, "eixo": eixo, "peso": peso, "origem": origem,
            "opcoes": [{"chave": k, "rotulo": r, "pontos": p} for k, r, p in opcoes]}


_PONTUALIDADE = (("0_15", "0% a 15%", 0), ("16_30", "16% a 30%", 2), ("31_50", "31% a 50%", 4),
                 ("51_70", "51% a 70%", 6), ("71_95", "71% a 95%", 8), ("95_100", "95% a 100%", 10))
_NOTA = (("otimo", "Ótimo", 5), ("bom", "Bom", 3), ("medio", "Médio", 2), ("ruim", "Ruim", 0))
_SIM_NAO = (("sim", "Sim", 4), ("nao", "Não", 0))
# A capa, na ordem e com os rótulos da planilha. origem: "serasa" (do PDF; o analista escolhe quando ele não traz ou,
# nas anotações, quando há alguma), "erp" (o histórico Mais Vida: do ERP, ou 0 para cliente novo) ou "analista".
CAPA = (
    _item("score", "Serasa", "Valor do score Serasa", 5, "serasa",
          ("muito_bom", "Muito bom: 701 a 1000", 5), ("bom", "Bom: 501 a 700", 3), ("regular", "Regular: 301 a 500", 2),
          ("baixo", "Baixo: 0 a 300", 1)),
    _item("recomendacao", "Serasa", "Recomendações Serasa", 14, "serasa",
          ("a_prazo", "Vendas a prazo", 14), ("garantias", "Vendas com garantias adicionais", 7),
          ("a_vista", "Vendas à vista", 0)),
    _item("risco", "Serasa", "Risco de crédito Serasa", 14, "serasa",
          ("iminente", "Iminente", 0), ("relevante", "Relevante", 2), ("baixo_medio", "Baixo a médio", 8),
          ("muito_baixo", "Muito baixo", 11), ("minimo", "Risco mínimo", 14)),
    _item("fundacao", "Serasa", "Ano de fundação", 9, "serasa",
          ("novo", "Novo: 0 a 3 meses", 0), ("recente", "Recente: 4 meses a 1 ano", 1),
          ("jovem", "Jovem: 1 a 3 anos", 3), ("media", "Média: 3 a 5 anos", 6), ("madura", "Madura: 5 a 10 anos", 8),
          ("consolidada", "Consolidada: mais de 10 anos", 9)),
    _item("pontualidade_serasa", "Serasa", "Pontualidade 12 meses Serasa", 10, "serasa",
          *_PONTUALIDADE, ("sem_historico", "Sem histórico de pagamento no Serasa", 0)),
    _item("anotacoes", "Serasa", "Anotações negativas", 9, "serasa",
          ("alta", "Relevância alta", 0), ("media", "Relevância média", 3), ("baixa", "Relevância baixa", 5),
          ("sem", "Sem anotação", 9)),
    _item("pontualidade_mv", "Histórico Mais Vida", "Pontualidade Mais Vida, 12 meses", 10, "erp",
          *_PONTUALIDADE, ("sem_historico", "Sem histórico na Mais Vida", 0)),
    _item("ultimas_compras", "Histórico Mais Vida", "Últimas compras", 2, "erp",
          ("comprou", f"Comprou nos últimos {COMPRAS_RECENTES} dias", 2),
          ("nao_comprou", f"Não comprou nos últimos {COMPRAS_RECENTES} dias", 0)),
    _item("frequencia", "Histórico Mais Vida", "Frequência de compras (últimos 3 meses)", 5, "erp",
          ("nenhuma", "Nenhuma compra", 0), ("1", "Menos de 2 vezes", 1), ("2_3", "2 ou 3 vezes", 2),
          ("4_5", "4 ou 5 vezes", 3), ("6", "6 vezes ou mais", 5)),
    _item("infraestrutura", "Comercial", "Infraestrutura", 5, "analista", *_NOTA),
    _item("limpeza", "Comercial", "Limpeza e organização", 5, "analista", *_NOTA),
    _item("ponto_proprio", "Comercial", "Ponto próprio?", 4, "analista", *_SIM_NAO),
    _item("residencia", "Comercial", "Tempo de residência, sócio?", 4, "analista", *_SIM_NAO),
    _item("juridico", "Jurídico (Mosselo)", "N/C jurídico (Mosselo)", 4, "analista",
          ("nada_consta", "Nada consta", 4), ("consta", "Consta processo contra", 0)),
)
POR_CHAVE = {x["chave"]: x for x in CAPA}
assert sum(x["peso"] for x in CAPA) == 100
assert all(max(o["pontos"] for o in x["opcoes"]) == x["peso"] for x in CAPA)

# As faixas pela pontuação (a partir de "de" pontos) e as parcelas do prazo de cada uma (linha "Prazo" do quadro).
FAIXAS = (
    {"faixa": 0, "rotulo": "Sem faixa", "de": 0, "ate": 39, "parcelas": 0},
    {"faixa": 1, "rotulo": "Faixa 1", "de": 40, "ate": 54, "parcelas": 1},
    {"faixa": 2, "rotulo": "Faixa 2", "de": 55, "ate": 64, "parcelas": 2},
    {"faixa": 3, "rotulo": "Faixa 3", "de": 65, "ate": 74, "parcelas": 3},
    {"faixa": 4, "rotulo": "Faixas 4 e 5", "de": 75, "ate": 100, "parcelas": 4},
)
# O porte da empresa (a "classificação ABC" do quadro, com a letra dele): até quantas parcelas e o bloco do quadro (as
# barras da direita; o 5º, da Grande, é a negociação com a diretoria). Na tela, só o nome.
PORTES = {
    "E": {"nome": "Pequena", "descricao": "Pequenas empresas", "parcelas": 2, "blocos": 1},
    "D": {"nome": "Pequena para média", "descricao": "Pequenas para médias empresas", "parcelas": 2, "blocos": 2},
    "C": {"nome": "Média", "descricao": "Médias empresas", "parcelas": 3, "blocos": 3},
    "B": {"nome": "Média para grande", "descricao": "Médias para grandes empresas", "parcelas": 4, "blocos": 4},
    "A": {"nome": "Grande", "descricao": "Grandes empresas", "parcelas": 4, "blocos": 5},
}
ORDEM_PORTES = ("E", "D", "C", "B", "A")
_ = None
# Os blocos da aba LIMITES, de cima para baixo: até quantas parcelas ("Faixa predominante até N parcelas") e as 5 linhas,
# com o limite em R$ de cada coluna de faixa (1, 2, 3, "4 e 5"); _ = casa vazia. O último é a negociação com a diretoria.
QUADRO = (
    {"parcelas": 2, "linhas": ((400, 400, _, _), (_, 700, 700, _), (_, 1000, 1000, _), (_, _, _, _), (_, _, _, _))},
    {"parcelas": 2, "linhas": ((1000, 1000, 1000, _), (_, 1500, 1500, _), (_, _, 2000, 2000), (_, _, _, 2500),
                               (_, _, _, 3000))},
    {"parcelas": 3, "linhas": ((3000, 3000, 3000, 3000), (_, 3750, 3750, 3750), (_, _, 4500, 4500), (_, _, _, 5250),
                               (_, _, _, 6000))},
    {"parcelas": 4, "linhas": ((6000, 6000, 6000, 6000), (_, 8250, 8250, 8250), (_, _, 10500, 10500),
                               (_, _, _, 12750), (_, _, _, 15000))},
    {"parcelas": 4, "diretoria": True},
)
JANELAS = ((5, 7), (12, 14), (19, 21), (26, 29))  # os dias de cada parcela: (5-7) - (12-14) - (19-21) - (26-29)
# O risco do Serasa (sem acento) -> a opção da capa, na ordem: Iminente, Alto, Médio, Baixo, Mínimo.
RISCOS = {"IMINENTE": "iminente", "ALTO": "relevante", "RELEVANTE": "relevante", "MEDIO": "baixo_medio",
          "BAIXO A MEDIO": "baixo_medio", "BAIXO": "muito_baixo", "MUITO BAIXO": "muito_baixo", "MINIMO": "minimo"}
REGRA = {"versao": REGRA_VERSAO, "compras_recentes_dias": COMPRAS_RECENTES, "frequencia_dias": FREQUENCIA}


# --- as contas, sem banco -------------------------------------------------------------------
def _norm(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().upper()


def _reais(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _pct(v: float) -> str:
    """Em % (93.5 = 93,5%; 93.0 = 93%)."""
    t = f"{v:.1f}".replace(".", ",")
    return (t[:-2] if t.endswith(",0") else t) + "%"


def _meses(de: dt.date, ate: dt.date) -> int:
    """Meses completos de `de` até `ate` (negativo vira 0)."""
    return max(0, (ate.year - de.year) * 12 + ate.month - de.month - (ate.day < de.day))


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def _idade(meses: int) -> str:
    anos, resto = divmod(meses, 12)
    if not anos:
        return _plural(meses, "mês", "meses")
    return _plural(anos, "ano", "anos") + (f" e {_plural(resto, 'mês', 'meses')}" if resto else "")


def faixa_de_pontualidade(pct: float) -> str:
    """Em % (93 = 93%): a opção de pontualidade da capa. A faixa "71 a 95" vai até antes de 95; 95 já é "95 a 100"."""
    pct = round(pct, 4)
    for limite, chave in ((16, "0_15"), (31, "16_30"), (51, "31_50"), (71, "51_70"), (95, "71_95")):
        if pct < limite:
            return chave
    return "95_100"


def opcao_da_fundacao(meses: int) -> str:
    """Pelos meses completos desde a fundação: 0–3 Novo, 4–12 Recente, 13–36 Jovem, 37–60 Média, 61–120 Madura e
    acima de 120 Consolidada (decisão do usuário: passou de 12 meses já é Jovem)."""
    for ate, chave in ((3, "novo"), (12, "recente"), (36, "jovem"), (60, "media"), (120, "madura")):
        if meses <= ate:
            return chave
    return "consolidada"


def _auto(opcao: str, fonte: str) -> dict:
    return {"opcao": opcao, "auto": True, "fonte": fonte}


def _manual(fonte: str) -> dict:
    return {"opcao": None, "auto": False, "fonte": fonte}


def respostas_serasa(s: dict, hoje: dt.date) -> dict[str, dict]:
    """Os itens do Serasa a partir de um envio (DadosSerasa, formato da página): {item: {opcao, auto, fonte}}. opcao
    None = o analista escolhe (o PDF não trouxe, ou há anotações negativas)."""
    r: dict[str, dict] = {}
    sc = s.get("score") or {}
    v = sc.get("valor")
    if v is None:
        r["score"] = _manual("o relatório não trouxe o score: escolha olhando o PDF")
    else:
        opcao = "muito_bom" if v >= 701 else "bom" if v >= 501 else "regular" if v >= 301 else "baixo"
        r["score"] = _auto(opcao, f"score {v} de 1000")

    rec = sc.get("recomendacao") or {}
    if rec.get("chave") in {o["chave"] for o in POR_CHAVE["recomendacao"]["opcoes"]}:
        r["recomendacao"] = _auto(rec["chave"], f"“{rec.get('texto')}” nas práticas de mercado")
    elif sc and "recomendacao" not in sc:  # lido antes de o painel guardar a recomendação (antes da capa)
        r["recomendacao"] = _manual("este PDF foi lido antes de o painel guardar a recomendação: escolha olhando o "
                                    "PDF, ou envie o PDF de novo")
    else:
        r["recomendacao"] = _manual("o relatório não trouxe a recomendação: escolha olhando o PDF")

    risco = sc.get("risco")
    chave = RISCOS.get(re.sub(r"^RISCO ", "", _norm(risco))) if risco else None
    if chave:
        r["risco"] = _auto(chave, f"risco “{risco}” no Serasa")
    elif risco:
        r["risco"] = _manual(f"o risco “{risco}” não está na capa: escolha o mais parecido")
    else:
        r["risco"] = _manual("o relatório não trouxe o risco: escolha olhando o PDF")

    if s.get("fundacao"):
        fundacao = dt.date.fromisoformat(s["fundacao"])
        meses = _meses(fundacao, hoje)
        r["fundacao"] = _auto(opcao_da_fundacao(meses), f"fundada em {fundacao:%d/%m/%Y}, há {_idade(meses)}"
                              if meses else f"fundada em {fundacao:%d/%m/%Y}, há menos de um mês")
    else:
        r["fundacao"] = _manual("o relatório não trouxe a data de fundação: escolha olhando o PDF")

    lista = s.get("pontualidade") or []
    if not lista:
        r["pontualidade_serasa"] = _auto("sem_historico", "o Serasa não tem histórico de pagamento desta empresa")
    else:
        pontual = next((x for x in lista if x.get("chave") == "pontual"), None)
        pct = (pontual or {}).get("percentual") or {}
        if pct.get("de") is None:
            r["pontualidade_serasa"] = _manual("não deu para ler a pontualidade do Serasa: confira no PDF")
        else:
            de = round(pct["de"] * 100, 4)
            faixa = pct.get("texto") or _pct(de)
            r["pontualidade_serasa"] = _auto(faixa_de_pontualidade(de),
                                             f"pontual {faixa} em R$" + (f" (vale o menor, {_pct(de)})"
                                                                          if pct.get("ate") != pct.get("de") else ""))

    anotacoes = s.get("anotacoes") or []
    ocorrencias = [a for a in anotacoes if a.get("quantidade") != 0]
    if anotacoes and not ocorrencias:
        r["anotacoes"] = _auto("sem", "nada consta nas anotações negativas")
    elif not anotacoes:
        r["anotacoes"] = _manual("o relatório não trouxe as anotações negativas: escolha olhando o PDF")
    else:
        partes = []
        for a in ocorrencias:
            if a.get("quantidade") is None and a.get("valor") is None:
                partes.append(f"{a['rotulo']}: não deu para ler")
            else:
                q = "?" if a.get("quantidade") is None else str(a["quantidade"])
                partes.append(f"{a['rotulo']}: {q}" + (f" ({_reais(a['valor'])})" if a.get("valor") is not None else ""))
        r["anotacoes"] = _manual("; ".join(partes) + ". Escolha a relevância")
    return r


def respostas_historico(h: dict | None) -> dict[str, dict]:
    """Os itens do histórico Mais Vida. h None = cliente novo, sem histórico na Mais Vida (tudo 0). Senão, o
    Credito.historico_mais_vida do cliente (na reanálise) ou do código do ERP com o CNPJ (no cadastro novo)."""
    if h is None:
        fonte = "cliente novo: sem histórico na Mais Vida"
        return {"pontualidade_mv": _auto("sem_historico", fonte), "ultimas_compras": _auto("nao_comprou", fonte),
                "frequencia": _auto("nenhuma", fonte)}
    de = f" (código {h['id']})"
    q, p = h["quitados"], h["pontualidade"]
    if not q:
        pontualidade = _auto("sem_historico", "nenhum título pago nos últimos 12 meses" + de)
    else:
        pontualidade = _auto(faixa_de_pontualidade(p * 100),
                             f"{h['pontuais']} de {q} títulos pagos em dia nos últimos 12 meses "
                             f"({_pct(round(p * 100, 1))}){de}")
    ultima, dias = h["ultima_compra"], h["dias_sem_compra"]
    if ultima is None:
        compras = _auto("nao_comprou", "nenhuma compra registrada" + de)
    else:
        compras = _auto("comprou" if dias < COMPRAS_RECENTES else "nao_comprou",
                        f"última compra em {ultima:%d/%m/%Y}{de}")
    n = h["dias_com_compra_90"]
    opcao = "nenhuma" if n == 0 else "1" if n == 1 else "2_3" if n <= 3 else "4_5" if n <= 5 else "6"
    frequencia = _auto(opcao, f"{_plural(n, 'dia', 'dias')} com compra nos últimos {FREQUENCIA} dias{de}")
    return {"pontualidade_mv": pontualidade, "ultimas_compras": compras, "frequencia": frequencia}


def faixa(pontos: int) -> dict:
    return dict(next(f for f in reversed(FAIXAS) if pontos >= f["de"]))


def pontuar(respostas: dict[str, dict]) -> dict:
    """Os itens da capa com a resposta de cada um ({item: {opcao, auto, fonte}}; opção que falta = None): os pontos, o
    total e os itens que faltam responder."""
    itens, total, faltam = [], 0, []
    for x in CAPA:
        r = respostas.get(x["chave"]) or _manual("")
        opcao = next((o for o in x["opcoes"] if o["chave"] == r.get("opcao")), None)
        if opcao is None:
            faltam.append(x["eixo"])
        else:
            total += opcao["pontos"]
        itens.append({"chave": x["chave"], "grupo": x["grupo"], "eixo": x["eixo"], "peso": x["peso"],
                      "origem": x["origem"], "auto": bool(r.get("auto")) and opcao is not None,
                      "fonte": r.get("fonte") or "", "opcao": opcao["chave"] if opcao else None,
                      "rotulo": opcao["rotulo"] if opcao else None, "pontos": opcao["pontos"] if opcao else None})
    return {"itens": itens, "pontos": total, "faltam": faltam}


def nome_prazo(dias: list[int]) -> str:
    """No formato dos prazos do ERP: [5] -> "05 DIAS"; [5, 12] -> "05 E 12 DIAS"; [5, 12, 19] -> "05, 12 E 19 DIAS";
    [] -> "A VISTA"."""
    if not dias:
        return "A VISTA"
    t = [f"{d:02d}" for d in dias]
    return (t[0] if len(t) == 1 else f"{', '.join(t[:-1])} E {t[-1]}") + " DIAS"


def indicar(numero_faixa: int, porte: str) -> dict:
    """O prazo e o limite do quadro para a faixa e o porte: o sugerido (o menor) e até onde pode chegar (o maior).
    O limite sai da coluna da faixa no bloco do porte (bloco: 1 a 4; a Grande usa o 4º, com a diretoria acima dele);
    casa vazia nessa coluna do bloco (Pequena com 75+) -> vale a coluna da faixa anterior (faixa_vazia). Porte que não
    existe -> ValueError."""
    if porte not in PORTES:
        raise ValueError("escolha o porte da empresa")
    p, f = PORTES[porte], FAIXAS[numero_faixa]
    base = {"faixa": numero_faixa, "faixa_rotulo": f["rotulo"], "porte": porte, "porte_nome": p["nome"],
            "parcelas_da_faixa": f["parcelas"], "parcelas_do_porte": p["parcelas"], "blocos": p["blocos"]}
    if numero_faixa == 0:
        return {**base, "sem_prazo": True, "parcelas": 0, "coluna": None, "bloco": None, "faixa_vazia": False,
                "diretoria": False, "limite_sugerido": 0.0, "limite_maximo": 0.0, "dias_sugeridos": [],
                "dias_maximos": [], "prazo_sugerido": "A VISTA", "prazo_maximo": "A VISTA"}
    com_valores = [b for b in QUADRO[:p["blocos"]] if not b.get("diretoria")]
    linhas = com_valores[-1]["linhas"]
    valores, coluna = [], numero_faixa
    while coluna >= 1:
        valores = [linha[coluna - 1] for linha in linhas if linha[coluna - 1] is not None]
        if valores:
            break
        coluna -= 1
    n = min(f["parcelas"], p["parcelas"])
    sugeridos, maximos = [j[0] for j in JANELAS[:n]], [j[1] for j in JANELAS[:n]]
    return {**base, "sem_prazo": False, "parcelas": n, "coluna": coluna, "bloco": len(com_valores),
            "faixa_vazia": coluna != numero_faixa, "diretoria": p["blocos"] > len(com_valores),
            "limite_sugerido": float(min(valores)), "limite_maximo": float(max(valores)),
            "dias_sugeridos": sugeridos, "dias_maximos": maximos,
            "prazo_sugerido": nome_prazo(sugeridos), "prazo_maximo": nome_prazo(maximos)}


def antecipada(nome: str | None) -> bool:
    """À vista ou 01 dia: venda antecipada, em que o cliente paga antes de o pedido ser faturado. Nela qualquer limite
    vale (o concedido nunca fica acima do máximo indicado) e o prazo está sempre dentro, mesmo sem faixa (decisão do
    usuário, 2026-11-25)."""
    return dias_prazo(nome) in ([0], [1])


def prazo_dentro(nome: str | None, ind: dict) -> bool:
    """Um prazo do ERP cabe no indicado: não tem mais parcelas que ele e o último dia não passa do último dia do máximo
    (com "07 E 14 DIAS", "12 DIAS" e "10 E 14 DIAS" cabem; "15 DIAS" não). Venda antecipada (à vista ou 01 dia)
    sempre cabe; sem faixa, só ela. Prazo sem número -> False."""
    dias = dias_prazo(nome)
    if dias is None:
        return False
    if antecipada(nome):
        return True
    if ind["sem_prazo"]:
        return False
    return len(dias) <= ind["parcelas"] and max(dias) <= ind["dias_maximos"][-1]


def acima_do_maximo(limite: float, prazo: str | None, ind: dict) -> bool:
    """O limite concedido passa do máximo indicado: não na venda antecipada (qualquer limite vale) nem com a
    negociação da diretoria (Grande)."""
    return limite > ind["limite_maximo"] + 0.005 and not ind.get("diretoria") and not antecipada(prazo)


def cnpj_formatado(digitos: str) -> str:
    d = digitos or ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else d


def _texto(valor, nome: str, minimo: int, maximo: int) -> str:
    t = str(valor or "").strip() if not isinstance(valor, (dict, list)) else ""
    if len(t) < minimo:
        raise ValueError(f"escreva {nome}" + (f" (pelo menos {minimo} letras)" if minimo > 1 else ""))
    if len(t) > maximo:
        raise ValueError(f"{nome} passou de {maximo} letras")
    return t


def _reais_da_pagina(valor) -> float:
    try:
        v = float(valor) if not isinstance(valor, bool) else math.nan
    except (TypeError, ValueError):
        v = math.nan
    if not math.isfinite(v) or v < 0 or v > MAX_LIMITE:
        raise ValueError("digite o limite concedido em reais (0 = sem crédito, só à vista)")
    return round(v, 2)


TIPOS = {"cadastro": "Cadastro novo", "reanalise": "Reanálise"}
CAMPOS = ("id", "tipo", "id_cliente", "cnpj", "cliente", "razao_social", "id_vendedor", "vendedor", "serasa_id", "porte",
          "respostas", "pontos", "faixa", "indicacao", "limite_sugerido", "limite_maximo", "limite_antes", "prazo_antes",
          "limite_concedido", "prazo_concedido", "observacoes", "justificativa", "id_cliente_historico", "dados_ate",
          "regra_versao", "bloqueio", "feita_em", "feita_por", "feita_por_nome", "versao_anterior", "editada_em",
          "editada_por", "editada_por_nome")
MAX_BUSCA = 100  # letras da busca da lista
# Minúsculas e sem acento, no SQL, para a busca comparar o nome como _norm faz aqui.
_SEM_ACENTO_SQL = "translate(lower(coalesce({}, '')), 'áàâãäåéèêëíìîïóòôõöúùûüçñ', 'aaaaaaeeeeiiiiooooouuuucn')"
NAO_ENCONTRADA = ("capa não encontrada: ela pode ter sido excluída ou editada por outra pessoa; recarregue a "
                  "página")


def _busca(texto: str) -> tuple[str, list]:
    """A condição SQL (sobre a capa c) da busca da lista: o nome do cliente ou a razão social (sem caixa nem acento), os
    dígitos do CNPJ (3 ou mais) ou o código do cliente (só dígitos)."""
    t = _norm(texto).lower()
    parecido = "%" + re.sub(r"([%_\\])", r"\\\1", t) + "%"
    condicoes = [f"{_SEM_ACENTO_SQL.format('c.cliente')} LIKE %s ESCAPE '\\'",
                 f"{_SEM_ACENTO_SQL.format('c.razao_social')} LIKE %s ESCAPE '\\'"]
    params: list = [parecido, parecido]
    digitos = re.sub(r"\D", "", texto)
    if len(digitos) >= 3:
        condicoes.append("c.cnpj LIKE %s")
        params.append(f"%{digitos}%")
    if digitos and digitos == texto.strip() and len(digitos) <= 9:
        condicoes.append("c.id_cliente = %s")
        params.append(int(digitos))
    return " OR ".join(condicoes), params
_VALORES = ("limite_sugerido", "limite_maximo", "limite_antes", "limite_concedido")


def _tipo(valor) -> str:
    """O tipo da capa: "cadastro" (o padrão) ou "reanalise"."""
    if valor in (None, ""):
        return "cadastro"
    if valor not in TIPOS:
        raise ValueError("escolha se a capa é de um cadastro novo ou de uma reanálise")
    return valor


class CapasCredito:
    """As capas de análise de crédito (cadastro novo ou reanálise), na tabela credito_capas. ativo: o site, que grava e
    lê; no PC (False) a página só avisa que elas ficam no site. serasa: os dados do Serasa (bi/serasa.py), onde fica o
    PDF de cada capa. reanalises: as reanálises (bi/reanalise.py), para o prazo mínimo entre reanálises na capa de uma
    reanálise; é ligada depois de criar as duas (None = sem prazo mínimo)."""

    def __init__(self, banco, credito, serasa, ativo: bool, reanalises=None):
        self.banco = banco
        self.credito = credito
        self.serasa = serasa
        self.ativo = ativo
        self.reanalises = reanalises

    @staticmethod
    def hoje() -> dt.date:
        """O dia da análise (a idade da empresa conta até ele)."""
        return dt.date.today()

    # --- o formulário ---------------------------------------------------------------------
    def vendedores(self, permitidos) -> list[dict]:
        """Os vendedores ativos do acesso (None = todos), com o nome de sempre."""
        nomes = self.credito.nomes_vendedores()
        ids = [r[0] for r in self.credito.cache.consulta("SELECT id FROM vendedores WHERE COALESCE(inativo, 0) = 0")]
        return sorted(({"id": v, "nome": nomes.get(v) or f"Vendedor {v}"} for v in ids
                       if permitidos is None or v in permitidos), key=lambda x: x["nome"].lower())

    def opcoes(self, permitidos) -> dict:
        """O que o formulário usa: os tipos, os prazos do ERP, a chave do próximo registro, os vendedores, os portes, a
        capa, o quadro, as faixas e a validade do Serasa."""
        return {"tipos": [{"chave": k, "nome": v} for k, v in TIPOS.items()], "prazos": self.credito.prazos(),
                "chave": novo_id(), "vendedores": self.vendedores(permitidos),
                "portes": [{"chave": k, **PORTES[k]} for k in ORDEM_PORTES], "capa": CAPA, "faixas": FAIXAS,
                "quadro": QUADRO, "janelas": JANELAS, "validade_dias": self.serasa.validade(), "regra": REGRA,
                "dados_ate": self.credito.cache.info.get("extraido_em")}

    def _cliente(self, valor, permitidos) -> dict:
        """Reanálise: o cliente escolhido, com o limite e o prazo de hoje no ERP e o vendedor da carteira. Código
        inválido ou que não existe -> ValueError; cliente fora do acesso -> PermissionError."""
        try:
            cliente = int(valor)
        except (TypeError, ValueError):
            raise ValueError("escolha o cliente da reanálise") from None
        if cliente <= 0:
            raise ValueError("escolha o cliente da reanálise")
        cadastro = self.credito.cadastro(cliente)  # o cliente que não existe -> ValueError
        if permitidos is not None and not self.credito.no_acesso(cliente, permitidos):
            raise PermissionError(f"o cliente {cliente} não é dos vendedores do seu acesso")
        linhas = self.credito.cache.consulta("SELECT id_vendedor FROM clientes WHERE id = ?", [cliente])
        vendedor = (linhas[0][0] or None) if linhas else None
        return {**cadastro, "id_vendedor": vendedor,
                "carteira": self.credito.nomes_vendedores().get(vendedor) if vendedor else None}

    def _historico_do_cnpj(self, cnpj: str | None) -> tuple[list[dict] | None, dict | None]:
        """Cadastro novo: (os códigos do ERP com o CNPJ, o histórico Mais Vida do da compra mais recente). (None, None):
        o cache ainda não tem o CNPJ dos clientes; ([], None): cliente novo."""
        clientes = self.credito.clientes_do_cnpj(cnpj)
        if not clientes:
            return clientes, None
        return clientes, self.credito.historico_mais_vida(clientes[0]["id"])

    def _bloqueio(self, cliente: int, ate: dt.datetime | None = None, ignorar: int | None = None) -> dict | None:
        """O prazo mínimo entre reanálises que vale hoje para o cliente (Reanalises._bloqueio), para a página avisar. Na
        edição, o que valia na data em que a capa foi registrada (ate), sem contar a própria capa (ignorar)."""
        if self.reanalises is None:
            return None
        with self.banco.conexao() as con:
            return self.reanalises._bloqueio(con, cliente, ate=ate, ignorar_capa=ignorar)

    def enviar_serasa(self, usuario: dict, conteudo: bytes, permitidos=None) -> dict:
        """Cadastro novo: lê e grava o PDF (sem código) e devolve a capa dele como está (analisar, sem as respostas do
        analista)."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        r = self.serasa.enviar_cadastro(usuario, conteudo)
        return {"ja_existia": r["ja_existia"], **self.analisar({"tipo": "cadastro", "serasa_id": r["id"]}, usuario,
                                                               permitidos)}

    def analisar(self, dados: dict, usuario: dict, permitidos=None) -> dict:
        """A capa: {tipo, cliente (reanálise), serasa_id, porte, respostas: {item: opção}}.
        - Cadastro novo: o envio do Serasa sem código; o histórico Mais Vida vem do ERP só se o CNPJ já é cliente.
        - Reanálise: um envio do Serasa do cliente (do código dele ou ligado pelo CNPJ) e o histórico Mais Vida dele;
          junto, o limite e o prazo de hoje e o prazo mínimo entre reanálises.
        Os itens automáticos são calculados aqui (a página não manda pontos); as respostas da página valem só nos itens
        que o analista escolhe. Com todos respondidos e o porte, a faixa e a indicação. Não grava."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        tipo = _tipo(dados.get("tipo"))
        cliente = bloqueio = None
        if tipo == "reanalise":
            cliente = self._cliente(dados.get("cliente"), permitidos)
            s = self.serasa.envio(dados.get("serasa_id"), usuario, cliente["id"])
            clientes, historico = [], self.credito.historico_mais_vida(cliente["id"])
            bloqueio = self._bloqueio(cliente["id"])
        else:
            s = self.serasa.envio(dados.get("serasa_id"), usuario)
            clientes, historico = self._historico_do_cnpj(s["cnpj_digitos"])
        hoje = self.hoje()
        auto = {**respostas_serasa(s, hoje), **respostas_historico(historico)}
        da_pagina = dados.get("respostas") if isinstance(dados.get("respostas"), dict) else {}
        respostas = {}
        for x in CAPA:
            a = auto.get(x["chave"]) or _manual("")
            if x["origem"] == "analista" or a["opcao"] is None:
                escolha = da_pagina.get(x["chave"])
                validas = {o["chave"] for o in x["opcoes"]}
                respostas[x["chave"]] = {"opcao": escolha if escolha in validas else None, "auto": False,
                                         "fonte": a["fonte"]}
            else:
                respostas[x["chave"]] = a
        p = pontuar(respostas)
        porte = dados.get("porte") if dados.get("porte") in PORTES else None
        completa = not p["faltam"]
        ind = indicar(faixa(p["pontos"])["faixa"], porte) if completa and porte else None
        return {
            "tipo": tipo, "cliente": cliente, "bloqueio": bloqueio, "serasa": s, "ja_cliente": clientes,
            "historico_de": {"id": historico["id"], "nome": historico["nome"]} if historico else None,
            "dados_ate": self.credito.cache.info.get("extraido_em") if historico else None,
            **p, "completa": completa, "porte": porte,
            "faixa": faixa(p["pontos"]) if completa else None, "indicacao": ind,
            "prazos_dentro": [x for x in self.credito.prazos() if prazo_dentro(x, ind)] if ind else [],
        }

    # --- o registro ------------------------------------------------------------------------
    def registrar(self, usuario: dict, dados: dict, permitidos=None) -> dict:
        """Grava uma capa: {chave, tipo, cliente (reanálise), serasa_id, nome (cadastro novo), id_vendedor, porte,
        respostas, limite, prazo, observacoes, justificativa, dados_ate, passar_bloqueio}. A capa e a indicação são
        calculadas aqui (analisar). Na reanálise, guarda o limite e o prazo de antes, e um aumento esbarra no prazo
        mínimo entre reanálises como na reanálise (o administrador passa, e a capa fica marcada). A mesma chave de novo
        não grava outra vez (ja_existia). Dado inválido, capa incompleta, dados do ERP novos ou aumento no prazo mínimo
        -> ValueError; vendedor ou cliente fora do acesso -> PermissionError. Devolve o id e a lista nova (listar)."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        tipo = _tipo(dados.get("tipo"))
        chave = id_valido(dados.get("chave"))
        if not chave:
            raise ValueError("o formulário expirou; recarregue a página")
        cliente = self._cliente(dados.get("cliente"), permitidos) if tipo == "reanalise" else None
        nome = cliente["nome"] if cliente else _texto(dados.get("nome"), "o nome do cliente", 1, MAX_NOME)
        try:
            vendedor = int(dados.get("id_vendedor"))
        except (TypeError, ValueError):
            raise ValueError("escolha o vendedor do cliente") from None
        if permitidos is not None and vendedor not in permitidos:
            raise PermissionError("o vendedor escolhido não é do seu acesso")
        vendedores = {v["id"]: v["nome"] for v in self.vendedores(permitidos)}
        if vendedor not in vendedores:
            raise ValueError("escolha o vendedor do cliente (os vendedores ativos)")
        if dados.get("porte") not in PORTES:
            raise ValueError("escolha o porte da empresa")
        a = self.analisar({**dados, "tipo": tipo}, usuario, permitidos)
        if not a["completa"]:
            raise ValueError(f"responda todos os itens da capa (faltam: {', '.join(a['faltam'])})")
        if a["dados_ate"] and str(dados.get("dados_ate") or "") != a["dados_ate"]:
            raise ValueError(DADOS_NOVOS)
        limite = _reais_da_pagina(dados.get("limite"))
        prazo = dados.get("prazo")
        if not isinstance(prazo, str) or prazo not in self.credito.prazos():
            raise ValueError("escolha o prazo concedido na lista (os prazos do ERP)")
        observacoes = _texto(dados.get("observacoes"), "as observações", 0, MAX_TEXTO) or None
        justificativa = _texto(dados.get("justificativa"), "a justificativa", MIN_JUSTIFICATIVA, MAX_TEXTO)
        s, ind = a["serasa"], a["indicacao"]
        respostas = [{k: x[k] for k in ("chave", "grupo", "eixo", "peso", "opcao", "rotulo", "pontos", "auto", "fonte")}
                     for x in a["itens"]]
        aumento = cliente is not None and limite > (cliente["limite"] or 0) + 0.005
        with self.banco.conexao() as con:
            if cliente:  # uma decisão de cada vez por cliente: duas pessoas juntas não passam as duas pelo prazo mínimo
                con.execute("SELECT pg_advisory_xact_lock(%s::int, %s::int)", [TRAVA, cliente["id"]])
            antiga = con.execute("SELECT id, feita_por FROM credito_capas WHERE chave = %s", [chave]).fetchone()
            if antiga is not None:  # a mesma chave de novo: clique duplo, ou a rede repetiu o envio
                if antiga[1] != usuario["id"]:
                    raise ValueError("o formulário expirou; recarregue a página")
                id_, ja_existia = antiga[0], True
            else:
                marca = None
                b = self.reanalises._bloqueio(con, cliente["id"]) if aumento and self.reanalises else None
                if b:
                    texto = texto_bloqueio(b)
                    if not eh_admin(usuario):
                        raise ValueError(f"este cliente está no prazo mínimo entre reanálises: {texto}. Redução, corte "
                                         "ou manter o limite podem ser registrados")
                    if dados.get("passar_bloqueio") is not True:
                        raise ValueError(f"este cliente está no prazo mínimo entre reanálises: {texto}. Para registrar "
                                         "mesmo assim, marque “Registrar mesmo assim”")
                    marca = texto
                id_ = con.execute(
                    "INSERT INTO credito_capas (chave, tipo, id_cliente, cnpj, cliente, razao_social, id_vendedor, "
                    "vendedor, serasa_id, porte, respostas, pontos, faixa, indicacao, limite_sugerido, limite_maximo, "
                    "limite_antes, prazo_antes, limite_concedido, prazo_concedido, observacoes, justificativa, "
                    "id_cliente_historico, dados_ate, regra_versao, bloqueio, feita_por, feita_por_nome) VALUES (%s, %s, "
                    "%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, (SELECT id FROM usuarios WHERE id = %s), %s) RETURNING id",
                    [chave, tipo, cliente["id"] if cliente else None, s["cnpj_digitos"], nome, s["razao_social"],
                     vendedor, vendedores[vendedor], s["id"], dados["porte"], json.dumps(respostas, ensure_ascii=False),
                     a["pontos"], ind["faixa"], json.dumps(ind, ensure_ascii=False), ind["limite_sugerido"],
                     ind["limite_maximo"], cliente["limite"] if cliente else None, cliente["prazo"] if cliente else None,
                     limite, prazo, observacoes, justificativa, a["historico_de"]["id"] if a["historico_de"] else None,
                     dt.datetime.fromisoformat(a["dados_ate"]) if a["dados_ate"] else None, REGRA_VERSAO, marca,
                     usuario["id"], usuario["nome"]]).fetchone()[0]
                ja_existia = False
        return {"id": id_, "ja_existia": ja_existia, **self.listar(usuario, permitidos)}

    def excluir(self, usuario: dict, id_, permitidos=None) -> dict:
        """Tira uma capa da página (e da do cliente); a linha fica, com quem excluiu e quando. Só quem registrou ou um
        administrador. Não existe ou já saiu -> NaoEncontrada; de outra pessoa -> PermissionError."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        try:
            id_ = int(id_)
        except (TypeError, ValueError):
            raise NaoEncontrada("capa não encontrada") from None
        with self.banco.conexao() as con:
            linha = con.execute("SELECT feita_por FROM credito_capas WHERE id = %s AND excluida_em IS NULL "
                                "AND substituida_em IS NULL FOR UPDATE", [id_]).fetchone()
            if linha is None:
                raise NaoEncontrada(NAO_ENCONTRADA)
            if not eh_admin(usuario) and linha[0] != usuario["id"]:
                raise PermissionError("só quem registrou a capa ou um administrador pode excluí-la")
            con.execute("UPDATE credito_capas SET excluida_em = now(), excluida_por = "
                        "(SELECT id FROM usuarios WHERE id = %s), excluida_por_nome = %s WHERE id = %s",
                        [usuario["id"], usuario["nome"], id_])
        return self.listar(usuario, permitidos)

    # --- as listas -------------------------------------------------------------------------
    def _linhas(self, onde: str, params: list, limite: int = MAX_LISTA) -> list[dict]:
        """As capas e, de cada uma, o envio do Serasa dela inteiro (em "serasa_linha"; o envio não muda depois, mesmo
        excluído da página do cliente)."""
        with self.banco.conexao() as con:
            linhas = con.execute(
                f"SELECT {', '.join('c.' + x for x in CAMPOS)}, {', '.join('s.' + x for x in CAMPOS_SERASA)} "
                f"FROM credito_capas c "
                f"JOIN credito_serasa s ON s.id = c.serasa_id WHERE c.excluida_em IS NULL AND c.substituida_em IS NULL "
                f"AND {onde} "
                "ORDER BY c.id DESC LIMIT %s", [*params, limite]).fetchall()
        saida = []
        for r in linhas:
            d = dict(zip(CAMPOS, r[:len(CAMPOS)]))
            for k in _VALORES:
                d[k] = None if d[k] is None else float(d[k])
            d["serasa_linha"] = dict(zip(CAMPOS_SERASA, r[len(CAMPOS):]))
            saida.append(d)
        return saida

    def _serasa_da_capa(self, d: dict, usuario: dict, validade: int, hoje: dt.date) -> dict:
        """O Serasa de uma capa registrada, no formato da página do cliente (bi/serasa.py), para mostrar o histórico de
        pagamento e as anotações junto da capa (não muda os pontos). idade_na_capa: quantos dias a consulta tinha
        quando a capa foi registrada; desatualizado_na_capa: se ela já tinha passado da validade de hoje."""
        s = d["serasa_linha"]
        idade = (d["feita_em"].astimezone().date() - s["emitido_em"].date()).days
        return {**self.serasa._item(s, usuario, validade, hoje), "pode_excluir": False,
                "idade_na_capa": idade, "desatualizado_na_capa": idade > validade}

    def _item(self, d: dict, usuario: dict, validade: int, hoje: dt.date) -> dict:
        """Uma capa registrada para a página. validade: a dos dados do Serasa (dias); hoje: a data de hoje."""
        ind = d["indicacao"]
        return {
            "id": d["id"], "tipo": d["tipo"], "tipo_nome": TIPOS[d["tipo"]], "id_cliente": d["id_cliente"],
            "feita_em": hora(d["feita_em"]), "feita_por": d["feita_por_nome"] or "usuário excluído",
            "pode_excluir": eh_admin(usuario) or d["feita_por"] == usuario["id"],
            "pode_editar": eh_admin(usuario) or d["feita_por"] == usuario["id"],
            "editada_em": hora(d["editada_em"]), "editada_por": (d["editada_por_nome"] or "usuário excluído")
            if d["editada_em"] else None,
            "cliente": d["cliente"], "cnpj": cnpj_formatado(d["cnpj"]), "razao_social": d["razao_social"],
            "id_vendedor": d["id_vendedor"], "vendedor": d["vendedor"], "porte": d["porte"],
            "porte_nome": PORTES[d["porte"]]["nome"],
            "pontos": d["pontos"], "faixa": d["faixa"], "faixa_rotulo": FAIXAS[d["faixa"]]["rotulo"], "indicacao": ind,
            "limite_antes": d["limite_antes"], "prazo_antes": d["prazo_antes"],
            "limite_concedido": d["limite_concedido"], "prazo_concedido": d["prazo_concedido"],
            "acima_do_maximo": acima_do_maximo(d["limite_concedido"], d["prazo_concedido"], ind),
            "antecipada": antecipada(d["prazo_concedido"]),
            "prazo_dentro": prazo_dentro(d["prazo_concedido"], ind),
            "observacoes": d["observacoes"], "justificativa": d["justificativa"], "respostas": d["respostas"],
            "historico_de": d["id_cliente_historico"], "bloqueio": d["bloqueio"],
            "serasa": self._serasa_da_capa(d, usuario, validade, hoje),
        }

    @staticmethod
    def _erp(d: dict, cliente: dict) -> dict:
        """O cliente do ERP contra o concedido na capa: aplicado (limite e prazo iguais) ou diferente."""
        igual = abs((cliente["limite"] or 0) - d["limite_concedido"]) < 0.005 and cliente["prazo"] == d["prazo_concedido"]
        return {"situacao": "aplicado" if igual else "diferente", "id": cliente["id"], "nome": cliente["nome"],
                "carteira": cliente["carteira"], "limite": cliente["limite"], "prazo": cliente["prazo"]}

    def listar(self, usuario: dict, permitidos=None, busca: str | None = None, id_=None) -> dict:
        """As capas para a página do formulário, das mais novas para as mais antigas (sem as excluídas e as versões
        substituídas por uma edição), com a situação no ERP de cada uma: a reanálise pelo cliente dela; o cadastro novo
        pelo CNPJ. Com acesso só a alguns vendedores: as deles e as que a pessoa registrou. busca: o nome do cliente, a
        razão social, o CNPJ ou o código do cliente (_busca); id_: só essa capa. Junto, o que o formulário usa
        (opcoes)."""
        if not self.ativo:
            return {"ativo": False, "aviso": AVISO_PC, "capas": []}
        if permitidos is None:
            onde, params = "TRUE", []
        else:
            onde, params = "(c.id_vendedor = ANY(%s) OR c.feita_por = %s)", [sorted(permitidos), usuario["id"]]
        if id_ not in (None, ""):
            try:
                id_ = int(id_)
            except (TypeError, ValueError):
                raise ValueError("capa inválida") from None
            onde += " AND c.id = %s"
            params.append(id_)
        busca = (busca or "").strip()[:MAX_BUSCA]
        if busca:
            condicao, mais = _busca(busca)
            onde += f" AND ({condicao})"
            params += mais
        linhas = self._linhas(onde, params)
        por_cnpj = self.credito.clientes_dos_cnpjs([d["cnpj"] for d in linhas if d["tipo"] == "cadastro"])
        por_id = self.credito.clientes_por_id([d["id_cliente"] for d in linhas if d["id_cliente"]])
        itens, validade, hoje = [], self.serasa.validade(), dt.date.today()
        for d in linhas:
            x = self._item(d, usuario, validade, hoje)
            if d["tipo"] == "reanalise":
                c = por_id.get(d["id_cliente"])
                x["erp"] = self._erp(d, c) if c else {"situacao": "fora_do_erp"}
            elif por_cnpj is None:
                x["erp"] = {"situacao": "sem_cnpj"}  # o cache ainda não tem o CNPJ dos clientes
            elif not por_cnpj.get(d["cnpj"]):
                x["erp"] = {"situacao": "fora_do_erp"}
            else:
                clientes = por_cnpj[d["cnpj"]]
                x["erp"] = {**self._erp(d, clientes[0]), "outros": [c["id"] for c in clientes[1:]]}
            itens.append(x)
        return {"ativo": True, "aviso": None, "capas": itens, "busca": busca or None, **self.opcoes(permitidos)}

    def do_cliente(self, cliente: int, usuario: dict) -> list[dict]:
        """As capas do cliente (para a página dele), das mais novas para as mais antigas: as reanálises dele e as de
        cadastro novo com o CNPJ dele (quando o CNPJ já chegou do ERP), com a situação no ERP. [] no PC."""
        if not self.ativo:
            return []
        cliente = int(cliente)
        cnpj = self.credito.cnpj_de(cliente)
        onde, params = "c.id_cliente = %s", [cliente]
        if cnpj:
            onde, params = "(c.id_cliente = %s OR c.cnpj = %s)", [cliente, cnpj]
        linhas = self._linhas(onde, params)
        if not linhas:
            return []
        dele = self.credito.clientes_por_id([cliente]).get(cliente)
        validade, hoje = self.serasa.validade(), dt.date.today()
        return [{**self._item(d, usuario, validade, hoje), **({"erp": self._erp(d, dele)} if dele else {})}
                for d in linhas]

    def ultima_em(self, con, cliente: int, cnpj: str | None, antes: dt.datetime | None = None,
                  ignorar: int | None = None) -> dt.datetime | None:
        """Quando foi a última capa do cliente (sem as excluídas; a editada conta pela data em que foi registrada): as
        reanálises dele e as de cadastro novo com o CNPJ dele. Para o prazo mínimo entre reanálises (bi/reanalise.py).
        antes: só as registradas antes dessa hora; ignorar: uma capa que não conta (a que está sendo editada)."""
        onde, params = "id_cliente = %s", [cliente]
        if cnpj:
            onde, params = "id_cliente = %s OR cnpj = %s", [cliente, cnpj]
        extra = ""
        if antes is not None:
            extra += " AND feita_em < %s"
            params.append(antes)
        if ignorar is not None:
            extra += " AND id <> %s"
            params.append(ignorar)
        linha = con.execute(f"SELECT MAX(feita_em) FROM credito_capas WHERE excluida_em IS NULL "
                            f"AND substituida_em IS NULL AND ({onde}){extra}", params).fetchone()
        return linha[0] if linha else None

    # --- a edição ------------------------------------------------------------------------
    def _atual(self, con, id_, travar: bool = False) -> dict:
        """A versão em vigor de uma capa (sem as excluídas e as substituídas). Não existe -> NaoEncontrada."""
        try:
            id_ = int(id_)
        except (TypeError, ValueError):
            raise NaoEncontrada(NAO_ENCONTRADA) from None
        r = con.execute(f"SELECT {', '.join(CAMPOS)} FROM credito_capas WHERE id = %s AND excluida_em IS NULL "
                        f"AND substituida_em IS NULL{' FOR UPDATE' if travar else ''}", [id_]).fetchone()
        if r is None:
            raise NaoEncontrada(NAO_ENCONTRADA)
        d = dict(zip(CAMPOS, r))
        for k in _VALORES:
            d[k] = None if d[k] is None else float(d[k])
        return d

    @staticmethod
    def _pode_editar(usuario: dict, d: dict) -> None:
        if not eh_admin(usuario) and d["feita_por"] != usuario["id"]:
            raise PermissionError("só quem registrou a capa ou um administrador pode editá-la")

    def _capa_editada(self, d: dict, dados: dict, usuario: dict) -> dict:
        """A capa d com as respostas, o porte e o resto que a página mandou: os itens automáticos ficam como foram
        registrados; os do analista vêm da página. O mesmo formato de analisar, com "edicao"."""
        salvas = {r["chave"]: r for r in d["respostas"]}
        da_pagina = dados.get("respostas") if isinstance(dados.get("respostas"), dict) else {}
        respostas = {}
        for x in CAPA:
            r = salvas.get(x["chave"]) or {}
            if r.get("auto"):
                respostas[x["chave"]] = {"opcao": r.get("opcao"), "auto": True, "fonte": r.get("fonte") or ""}
            else:
                escolha = da_pagina.get(x["chave"])
                validas = {o["chave"] for o in x["opcoes"]}
                respostas[x["chave"]] = {"opcao": escolha if escolha in validas else None, "auto": False,
                                         "fonte": r.get("fonte") or ""}
        p = pontuar(respostas)
        porte = dados.get("porte") if dados.get("porte") in PORTES else None
        completa = not p["faltam"]
        ind = indicar(faixa(p["pontos"])["faixa"], porte) if completa and porte else None
        cliente = bloqueio = None
        if d["tipo"] == "reanalise":
            cliente = {"id": d["id_cliente"], "nome": d["cliente"], "limite": d["limite_antes"], "prazo": d["prazo_antes"],
                       "id_vendedor": d["id_vendedor"], "carteira": None}
            bloqueio = self._bloqueio(d["id_cliente"], ate=d["feita_em"], ignorar=d["id"])
        return {
            "tipo": d["tipo"], "cliente": cliente, "bloqueio": bloqueio,
            "serasa": self.serasa.por_id(d["serasa_id"], usuario), "ja_cliente": [],
            "historico_de": {"id": d["id_cliente_historico"], "nome": None} if d["id_cliente_historico"] else None,
            "dados_ate": None, **p, "completa": completa, "porte": porte,
            "faixa": faixa(p["pontos"]) if completa else None, "indicacao": ind,
            "prazos_dentro": [x for x in self.credito.prazos() if prazo_dentro(x, ind)] if ind else [],
            "edicao": {"id": d["id"], "tipo_nome": TIPOS[d["tipo"]], "cliente": d["cliente"],
                       "feita_em": hora(d["feita_em"]), "feita_por": d["feita_por_nome"] or "usuário excluído"},
        }

    def analisar_edicao(self, dados: dict, usuario: dict, permitidos=None) -> dict:
        """A capa em edição: {editar (o id da capa), porte, respostas}, como analisar. Só quem registrou ou um
        administrador (senão PermissionError). Não grava."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        with self.banco.conexao() as con:
            d = self._atual(con, dados.get("editar"))
        self._pode_editar(usuario, d)
        return self._capa_editada(d, dados, usuario)

    def editar(self, usuario: dict, dados: dict, permitidos=None) -> dict:
        """Grava a edição de uma capa: {id, chave, nome (cadastro novo), id_vendedor, porte, respostas, limite, prazo,
        observacoes, justificativa, passar_bloqueio}. A versão nova repete quando e por quem a capa foi registrada e o
        que não muda (o tipo, o cliente, o Serasa, os itens automáticos, o limite e o prazo de antes); a de antes fica
        guardada como substituída. Na reanálise, um aumento esbarra no prazo mínimo que valia quando a capa foi
        registrada, como no registro. Só quem registrou ou um administrador. A mesma chave de novo não grava outra vez
        (ja_existia). Devolve o id da versão nova e a lista nova (listar)."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        chave = id_valido(dados.get("chave"))
        if not chave:
            raise ValueError("o formulário expirou; recarregue a página")
        with self.banco.conexao() as con:
            antiga = con.execute("SELECT id, editada_por FROM credito_capas WHERE chave = %s", [chave]).fetchone()
            if antiga is not None:  # a mesma chave de novo: clique duplo, ou a rede repetiu o envio
                if antiga[1] != usuario["id"]:
                    raise ValueError("o formulário expirou; recarregue a página")
                return {"id": antiga[0], "ja_existia": True, **self.listar(usuario, permitidos)}
            d = self._atual(con, dados.get("id"))
        self._pode_editar(usuario, d)
        nome = d["cliente"] if d["tipo"] == "reanalise" else _texto(dados.get("nome"), "o nome do cliente", 1, MAX_NOME)
        try:
            vendedor = int(dados.get("id_vendedor"))
        except (TypeError, ValueError):
            raise ValueError("escolha o vendedor do cliente") from None
        vendedores = {v["id"]: v["nome"] for v in self.vendedores(permitidos)}
        vendedores.setdefault(d["id_vendedor"], d["vendedor"])  # o de antes vale, mesmo inativo ou fora do acesso
        if vendedor not in vendedores:
            if permitidos is not None and vendedor not in permitidos:
                raise PermissionError("o vendedor escolhido não é do seu acesso")
            raise ValueError("escolha o vendedor do cliente (os vendedores ativos)")
        if dados.get("porte") not in PORTES:
            raise ValueError("escolha o porte da empresa")
        a = self._capa_editada(d, dados, usuario)
        if not a["completa"]:
            raise ValueError(f"responda todos os itens da capa (faltam: {', '.join(a['faltam'])})")
        limite = _reais_da_pagina(dados.get("limite"))
        prazo = dados.get("prazo")
        if not isinstance(prazo, str) or (prazo not in self.credito.prazos() and prazo != d["prazo_concedido"]):
            raise ValueError("escolha o prazo concedido na lista (os prazos do ERP)")
        observacoes = _texto(dados.get("observacoes"), "as observações", 0, MAX_TEXTO) or None
        justificativa = _texto(dados.get("justificativa"), "a justificativa", MIN_JUSTIFICATIVA, MAX_TEXTO)
        ind = a["indicacao"]
        respostas = [{k: x[k] for k in ("chave", "grupo", "eixo", "peso", "opcao", "rotulo", "pontos", "auto", "fonte")}
                     for x in a["itens"]]
        reanalise = d["tipo"] == "reanalise"
        aumento = reanalise and limite > (d["limite_antes"] or 0) + 0.005
        with self.banco.conexao() as con:
            if reanalise:  # uma decisão de cada vez por cliente
                con.execute("SELECT pg_advisory_xact_lock(%s::int, %s::int)", [TRAVA, d["id_cliente"]])
            d = self._atual(con, d["id"], travar=True)  # ninguém editou ou excluiu no meio
            marca = None
            b = (self.reanalises._bloqueio(con, d["id_cliente"], ate=d["feita_em"], ignorar_capa=d["id"])
                 if aumento and self.reanalises else None)
            if b:
                texto = texto_bloqueio(b)
                if not eh_admin(usuario):
                    raise ValueError(f"este cliente estava no prazo mínimo entre reanálises quando a capa foi registrada: "
                                     f"{texto}. Redução, corte ou manter o limite podem ser registrados")
                if dados.get("passar_bloqueio") is not True:
                    raise ValueError(f"este cliente estava no prazo mínimo entre reanálises quando a capa foi registrada: "
                                     f"{texto}. Para registrar mesmo assim, marque “Registrar mesmo assim”")
                marca = texto
            id_ = con.execute(
                "INSERT INTO credito_capas (chave, tipo, id_cliente, cnpj, cliente, razao_social, id_vendedor, vendedor, "
                "serasa_id, porte, respostas, pontos, faixa, indicacao, limite_sugerido, limite_maximo, limite_antes, "
                "prazo_antes, limite_concedido, prazo_concedido, observacoes, justificativa, id_cliente_historico, "
                "dados_ate, regra_versao, bloqueio, feita_em, feita_por, feita_por_nome, versao_anterior, editada_em, "
                "editada_por, editada_por_nome) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, "
                "%s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, (SELECT id FROM usuarios WHERE id = %s), "
                "%s, %s, now(), (SELECT id FROM usuarios WHERE id = %s), %s) RETURNING id",
                [chave, d["tipo"], d["id_cliente"], d["cnpj"], nome, d["razao_social"], vendedor, vendedores[vendedor],
                 d["serasa_id"], dados["porte"], json.dumps(respostas, ensure_ascii=False), a["pontos"], ind["faixa"],
                 json.dumps(ind, ensure_ascii=False), ind["limite_sugerido"], ind["limite_maximo"], d["limite_antes"],
                 d["prazo_antes"], limite, prazo, observacoes, justificativa, d["id_cliente_historico"], d["dados_ate"],
                 REGRA_VERSAO, marca, d["feita_em"], d["feita_por"], d["feita_por_nome"], d["id"], usuario["id"],
                 usuario["nome"]]).fetchone()[0]
            con.execute("UPDATE credito_capas SET substituida_em = now() WHERE id = %s", [d["id"]])
        return {"id": id_, "ja_existia": False, **self.listar(usuario, permitidos)}

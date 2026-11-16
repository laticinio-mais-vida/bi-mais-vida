"""Premiações (página Premiações): quanto cada vendedor e cada supervisor ganha no mês. As regras ficam na tabela regras
(nome "premiacoes"), editáveis em Premiações › Configurar, e valem para todos os meses (mudar uma regra recalcula o
histórico).

Vendedores (como a página "Premiacao Vendedores" do Power BI; uma linha por vendedor com META CLIENTE > 0 no mês, da
METAS.xlsx ou aprovada no painel):
- atendidos = clientes distintos com venda válida no mês, pelo vendedor da venda (a mesma conta da página de Metas);
- % = atendidos ÷ META CLIENTE; o prêmio é o da maior faixa atingida (padrão do Power BI: 91% → R$ 200, 96% → R$ 250,
  100% → R$ 350; abaixo de 91%, nada). O total é a soma dos prêmios (o Power BI aplicava a faixa ao % do total).

Supervisores (os regulamentos de nov/2026): Marcos (BA) e Ronaldo (ES) pela "segunda versão", com variável de R$ 6.000;
Valdirene (ES, a mesma carteira do Ronaldo) pela "nova estrutura", com R$ 9.000 e um adicional pela inadimplência. A
carteira é a de HOJE: os clientes cujo vendedor no cadastro é do estado pelas Configurações das metas ou, sem
configuração, pelo supervisor do ERP; terceiros, o Edir e contas internas ficam fora. Só vendas, devoluções e brindes
de tipo CLIENTE, sem os produtos que ficam fora das metas. Os números são do estado: os dois supervisores do ES usam os
mesmos. Cada indicador tem um peso (a parcela de referência = peso × variável) e paga um % dela pela faixa atingida,
sem interpolação:
- faturamento líquido: vendas − devoluções dos motivos que descontam na meta (Metas › Configurar, com as canceladas como
  lá); brindes não descontam, porque a meta também não desconta. Meta: a soma das METAS FATURAMENTO dos vendedores do
  estado no mês (ou o ajuste do mês);
- mix (exceto mussarela): o líquido sem os produtos de fora do mix ÷ o líquido, sobre a meta (55%);
- positivação: clientes distintos da carteira com venda no mês, sobre a soma das METAS CLIENTE (ou o ajuste);
- ativação de clientes novos: clientes da carteira cadastrados no ERP no mês que compraram no mesmo mês (meta 40);
- reativação: clientes da carteira com uma compra no mês feita depois de 60 dias ou mais sem comprar, contados da compra
  anterior até essa (meta 20). Só conta quem já tinha comprado: a compra anterior é a última venda do cache ou, sem
  nenhuma, o último título de venda do ERP de antes do início das vendas do cache (os títulos vão até 2012).
Faturamento e mix (as mesmas faixas): 90% da meta → 30% da parcela, 100% → 100%. Positivação, novos e reativação têm cada
um as suas faixas (padrão igual para os três: 80% → 40%, 100% → 100%, 120% → 150%; até 12/11/2026 eram uma escala só,
"escala_clientes", que as regras salvas antes copiam para os três ao abrir). Sobre a soma das parcelas, nesta ordem: a trava pelo % da meta de faturamento (abaixo de 90%, nada; de 90% a 95%, metade), o
bônus de superação (acima de 100%: +2%; 110%: +5%; 120%: +7%; 150%: +10%) e o desconto pelo vencido (devoluções não
canceladas e brindes de motivo vencido ÷ vendas: até 0,5%, nada; até 1%, 5%; acima, 10%). Só a Valdirene: mais R$ 450
com a inadimplência em até 0,45% (títulos de venda a cliente emitidos de 7 a 2 meses antes do mês, vencidos há 30 dias
ou mais na data dos dados e ainda em aberto, ÷ o faturamento líquido desses 6 meses), fora da trava, do bônus e do
desconto; não é pago quando a trava zera. A inadimplência é a de hoje: o mês fechado muda quando um cliente paga depois.
As regras salvas antes desses regulamentos (versão 1: cinco indicadores × um prêmio máximo) são convertidas ao abrir.

Comissão (não vem do Power BI; só as equipes BA e ES, que no ERP ganham comissão sobre a venda; o Edir e os terceiros
ganham sobre o recebimento e ficam fora). O % é do vendedor para cada produto (CONFIGCOMISSAOVENDEDOR no ERP):
- comissão das vendas: a que o ERP gravou em cada item de venda a cliente (o % do dia da venda × o valor do item), então
  mudar a tabela não muda o passado;
- menos as devoluções não canceladas de todos os motivos (pela data de entrada) e os brindes dos motivos escolhidos
  (padrão: danificado e vencido), cada um × o % de hoje da tabela para o vendedor e o produto (a devolução não traz o
  valor da comissão e às vezes vem com 0%; o brinde não tem %). Produto sem % na tabela não desconta.

Quem vê o quê: as abas e os quadros de supervisor de cada visualizador ficam em Premiações › Configurar › Acesso por
usuário (bi/acesso.py, coluna premiacoes); os vendedores dentro deles, na tela Usuários. O quadro de um supervisor só
aparece para quem vê a carteira inteira do estado dele. O PDF de cada aba (bi/premiacoes_pdf.py) sai com o mesmo acesso.
"""
from __future__ import annotations

import calendar
import datetime as dt
import math
import re
from collections import Counter

from . import premiacoes_pdf
from .configuracao import RegrasNoBanco
from .metas import Calculadora, nome_bonito
from .sugestao import curto_mes, indice, ler_mes, rotulo_mes, texto_mes

ESTADOS = ("BA", "ES")
ABAS = ("vendedores", "supervisores", "comissao")
TITULOS_ABAS = {"vendedores": "Vendedores", "supervisores": "Supervisores", "comissao": "Comissão"}
SUPERVISORES = ("marcos", "ronaldo", "valdirene")
INDICADORES = ("faturamento", "mix", "positivacao", "novos", "reativacao")
TITULOS = {"faturamento": "Faturamento líquido", "mix": "Mix (exceto mussarela)", "positivacao": "Positivação",
           "novos": "Ativação de clientes novos", "reativacao": "Reativação de clientes"}
ESCALA = {"faturamento": "escala_faturamento", "mix": "escala_faturamento", "positivacao": "escala_positivacao",
          "novos": "escala_novos", "reativacao": "escala_reativacao"}
# As escalas próprias de cada indicador de clientes e o nome delas nas mensagens de erro.
ESCALAS_CLIENTES = {"escala_positivacao": "da escala da positivação", "escala_novos": "da escala dos clientes novos",
                    "escala_reativacao": "da escala da reativação"}
METAS_MES = ("fat", "cli", "novos", "reativacao")  # as metas de um supervisor que dá para trocar num mês
META_DO_INDICADOR = {"faturamento": "fat", "positivacao": "cli", "novos": "novos", "reativacao": "reativacao"}
ROTULOS_META = {"fat": "faturamento", "cli": "clientes (positivação)", "novos": "clientes novos",
                "reativacao": "reativação"}
MAX_FAIXAS = 10
JANELA_DE, JANELA_ATE = 7, 2  # inadimplência: meses de emissão, contados para trás a partir do mês escolhido
_EPS = 1e-9


# --- regras da página -----------------------------------------------------------------------
def _supervisor_padrao(id_: str, nome: str, estado: str, variavel: float, pesos: dict,
                       inadimplencia: dict | None = None) -> dict:
    return {"id": id_, "nome": nome, "estado": estado, "variavel": variavel, "pesos": pesos, "meta_mix": 0.55,
            "inadimplencia": inadimplencia, "metas_padrao": {"novos": 40, "reativacao": 20}}


def padrao() -> dict:
    """Vendedores e comissão como no Power BI; supervisores como nos regulamentos de nov/2026."""
    segunda_versao = {"faturamento": 0.30, "mix": 0.0, "positivacao": 0.25, "novos": 0.25, "reativacao": 0.20}
    return {
        "versao": 2,
        "vendedores": {"faixas": [{"min": 0.91, "valor": 200.0}, {"min": 0.96, "valor": 250.0},
                                  {"min": 1.0, "valor": 350.0}]},
        "supervisores": {
            "lista": [
                _supervisor_padrao("marcos", "Marcos", "BA", 6000.0, dict(segunda_versao)),
                _supervisor_padrao("ronaldo", "Ronaldo", "ES", 6000.0, dict(segunda_versao)),
                _supervisor_padrao("valdirene", "Valdirene", "ES", 9000.0,
                                   {"faturamento": 0.35, "mix": 0.20, "positivacao": 0.15, "novos": 0.15,
                                    "reativacao": 0.15},
                                   {"valor": 450.0, "limite": 0.0045}),
            ],
            # % da meta a partir do qual a faixa vale -> % da parcela pago (não há interpolação). O faturamento e o mix
            # usam a mesma; positivação, novos e reativação, cada um a sua (o padrão é igual nas três).
            "escala_faturamento": [{"min": 0.90, "pct": 0.30}, {"min": 1.0, "pct": 1.0}],
            **{k: [{"min": 0.80, "pct": 0.40}, {"min": 1.0, "pct": 1.0}, {"min": 1.20, "pct": 1.50}]
               for k in ESCALAS_CLIENTES},
            "trava": [{"min": 0.90, "pct": 0.50}, {"min": 0.95, "pct": 1.0}],
            "bonus": [{"min": 1.0, "pct": 0.02}, {"min": 1.10, "pct": 0.05}, {"min": 1.20, "pct": 0.07},
                      {"min": 1.50, "pct": 0.10}],
            # vencido ÷ vendas até "ate" -> % do variável mantido; acima da última faixa, "acima"
            "devolucao": {"faixas": [{"ate": 0.005, "pct": 1.0}, {"ate": 0.01, "pct": 0.95}], "acima": 0.90},
            "motivos_vencido": [3, 16],  # "DEVOLUÇÃO IMPRÓPRIA - VENCIDO" e "BRINDE - VENCIDO"
            "produtos_fora_mix": [32, 12551, 12552],  # a mussarela
            "dias_sem_compra": 60,
            "dias_inadimplencia": 30,
            "metas_mes": {},
        },
        # Os brindes que descontam da comissão: "BRINDE - DANIFICADO, PROBLEMA NA PRODUÇÃO", "... NA LOGÍSTICA",
        # "... NO CLIENTE" e "BRINDE - VENCIDO". As devoluções descontam todas.
        "comissao": {"motivos_brindes": [10, 11, 12, 16]},
    }


def _numero(valor, nome: str, minimo: float = 0.0, maximo: float | None = None) -> float:
    try:
        x = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nome}: use um número") from None
    if math.isnan(x) or x < minimo or (maximo is not None and x > maximo):
        faixa_ = f"de {minimo:g} a {maximo:g}" if maximo is not None else f"a partir de {minimo:g}"
        raise ValueError(f"{nome}: use um valor {faixa_}")
    return x


def _inteiro(valor, nome: str, minimo: float = 0.0, maximo: float | None = None) -> int:
    n = _numero(valor, nome, minimo, maximo)
    if n != int(n):
        raise ValueError(f"{nome}: use um número inteiro")
    return int(n)


def _fracao(valor, nome: str, maximo: float = 1.0) -> float:
    try:
        x = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nome}: use um número") from None
    if math.isnan(x) or not 0 <= x <= maximo:
        raise ValueError(f"{nome}: use um valor entre 0% e {maximo * 100:g}%")
    return round(x, 6)


def _inteiros(valores, nome: str) -> list[int]:
    try:
        return sorted({int(v) for v in valores or []})
    except (TypeError, ValueError):
        raise ValueError(f"{nome}: use códigos inteiros") from None


def _faixas(lista, nome: str, pct_max: float, menor: float = 0.0) -> list[dict]:
    """Uma escala {min, pct}: o % da meta a partir do qual a faixa vale e o % pago. Devolve em ordem."""
    saida = []
    for f in lista or []:
        f = f or {}
        saida.append({"min": _fracao(f.get("min"), f"% da meta de uma faixa {nome}", 5.0),
                      "pct": _fracao(f.get("pct"), f"% pago numa faixa {nome}", pct_max)})
    if not saida:
        raise ValueError(f"use ao menos uma faixa {nome}")
    if len(saida) > MAX_FAIXAS:
        raise ValueError(f"use no máximo {MAX_FAIXAS} faixas {nome}")
    saida.sort(key=lambda f: f["min"])
    if len({f["min"] for f in saida}) != len(saida):
        raise ValueError(f"há duas faixas {nome} com o mesmo % da meta")
    if any(f["min"] <= 0 for f in saida):
        raise ValueError(f"o % da meta de cada faixa {nome} precisa ser maior que 0%")
    if any(f["min"] + _EPS < menor for f in saida):
        raise ValueError(f"o % da meta de cada faixa {nome} precisa ser de pelo menos {menor * 100:g}%")
    return saida


def _regra_devolucao(d: dict | None, base: dict) -> dict:
    d = d or {}
    faixas = []
    for f in d.get("faixas", base["faixas"]) or []:
        f = f or {}
        faixas.append({"ate": _fracao(f.get("ate"), "% de vencido de uma faixa do desconto"),
                       "pct": _fracao(f.get("pct"), "% mantido numa faixa do desconto")})
    if len(faixas) > MAX_FAIXAS:
        raise ValueError(f"use no máximo {MAX_FAIXAS} faixas no desconto pelo vencido")
    faixas.sort(key=lambda f: f["ate"])
    if len({f["ate"] for f in faixas}) != len(faixas):
        raise ValueError("há duas faixas do desconto pelo vencido com o mesmo %")
    if any(f["ate"] <= 0 for f in faixas):
        raise ValueError("o % de vencido de cada faixa do desconto precisa ser maior que 0%")
    return {"faixas": faixas,
            "acima": _fracao(d.get("acima", base["acima"]), "% mantido acima da última faixa do desconto")}


def _supervisor(entrada: dict, base: dict) -> dict:
    """Um supervisor da lista; o que não veio fica com o padrão. O estado é sempre o do padrão."""
    nome = " ".join(str(entrada.get("nome", base["nome"]) or "").split())
    if not nome or len(nome) > 60:
        raise ValueError(f"nome do supervisor ({base['nome']}): use de 1 a 60 letras")
    s = {"id": base["id"], "nome": nome, "estado": base["estado"],
         "variavel": round(_numero(entrada.get("variavel", base["variavel"]), f"variável de {nome}", 0, 1e6), 2)}
    pesos = entrada.get("pesos") or {}
    s["pesos"] = {k: _fracao(pesos.get(k, base["pesos"][k]), f"peso de {TITULOS[k].lower()} de {nome}")
                  for k in INDICADORES}
    soma = sum(s["pesos"].values())
    if abs(soma - 1) > 1e-6:
        raise ValueError(f"os pesos de {nome} somam {soma * 100:.4g}%; precisam somar 100%")
    s["meta_mix"] = _fracao(entrada.get("meta_mix", base["meta_mix"]), f"meta do mix de {nome}")
    inad = entrada["inadimplencia"] if "inadimplencia" in entrada else base["inadimplencia"]
    s["inadimplencia"] = None if not inad else {
        "valor": round(_numero(inad.get("valor"), f"prêmio da inadimplência de {nome}", 0, 1e6), 2),
        "limite": _fracao(inad.get("limite"), f"limite da inadimplência de {nome}")}
    metas = entrada.get("metas_padrao") or {}
    s["metas_padrao"] = {}
    for k in ("novos", "reativacao"):
        v = metas.get(k, base["metas_padrao"][k]) if isinstance(metas, dict) else base["metas_padrao"][k]
        s["metas_padrao"][k] = None if v in (None, "") else _inteiro(v, f"meta de {ROTULOS_META[k]} de {nome}")
    return s


def _metas_mes(dados: dict | None, nomes: dict[str, str]) -> dict:
    """{AAAA-MM: {supervisor: {fat, cli, novos, reativacao}}}: as metas trocadas à mão num mês (0 = sem meta)."""
    saida = {}
    for mes, por_sup in (dados or {}).items():
        m = texto_mes(ler_mes(mes))
        lista = {}
        for sid, v in (por_sup or {}).items():
            if sid not in nomes:
                raise ValueError(f"supervisor desconhecido nas metas de {m}: {sid}")
            x = {}
            for k in METAS_MES:
                valor = (v or {}).get(k)
                if valor in (None, ""):
                    continue
                rotulo = f"meta de {ROTULOS_META[k]} de {nomes[sid]} em {m}"
                x[k] = round(_numero(valor, rotulo), 2) if k == "fat" else _inteiro(valor, rotulo)
            if x:
                lista[sid] = x
        if lista:
            saida[m] = lista
    return dict(sorted(saida.items()))


def _de_v1(antigo: dict) -> dict:
    """As regras dos supervisores salvas antes dos regulamentos de nov/2026 (versão 1: um supervisor por estado, cinco
    indicadores × um prêmio máximo) no formato novo. Ficam os nomes (BA → Marcos, ES → Ronaldo), a meta do mix, os
    produtos fora do mix, os dias de atraso da inadimplência e as metas trocadas em cada mês (as do ES valem para os
    dois supervisores do estado); o resto vem do padrão."""
    novo = padrao()["supervisores"]
    antigo = antigo if isinstance(antigo, dict) else {}
    nomes = antigo.get("nomes") or {}
    meta_mix = (antigo.get("mix") or {}).get("meta") or {}
    for s in novo["lista"]:
        if s["id"] != "valdirene" and str(nomes.get(s["estado"]) or "").strip():
            s["nome"] = nomes[s["estado"]]
        if meta_mix.get(s["estado"]) is not None:
            s["meta_mix"] = meta_mix[s["estado"]]
    if antigo.get("produtos_fora_mix") is not None:
        novo["produtos_fora_mix"] = antigo["produtos_fora_mix"]
    dias = (antigo.get("inadimplencia") or {}).get("dias")
    if dias is not None:
        novo["dias_inadimplencia"] = dias
    for mes, por_estado in (antigo.get("ajustes") or {}).items():
        for estado, v in (por_estado or {}).items():
            metas = {k: v[k] for k in ("fat", "cli") if isinstance(v, dict) and v.get(k) not in (None, "")}
            for s in novo["lista"]:
                if s["estado"] == estado and metas:
                    novo["metas_mes"].setdefault(mes, {})[s["id"]] = dict(metas)
    return novo


def _valida(cfg: dict) -> dict:
    """Confere e normaliza as regras vindas da página; levanta ValueError com a explicação."""
    base = padrao()
    ven = cfg.get("vendedores") or base["vendedores"]
    faixas = []
    for f in ven.get("faixas") or []:
        faixas.append({"min": _fracao(f.get("min"), "% mínimo de uma faixa dos vendedores", 5.0),
                       "valor": round(_numero(f.get("valor"), "prêmio de uma faixa dos vendedores"), 2)})
    if not faixas:
        raise ValueError("os vendedores precisam de ao menos uma faixa de premiação")
    if len(faixas) > MAX_FAIXAS:
        raise ValueError(f"use no máximo {MAX_FAIXAS} faixas para os vendedores")
    faixas.sort(key=lambda f: f["min"])
    if len({f["min"] for f in faixas}) != len(faixas):
        raise ValueError("há duas faixas dos vendedores com o mesmo % mínimo")
    if any(f["min"] <= 0 for f in faixas):
        raise ValueError("o % mínimo de cada faixa dos vendedores precisa ser maior que 0%")

    sup_in = cfg.get("supervisores") or {}
    if "lista" not in sup_in:  # salvas antes dos regulamentos de nov/2026 (ou sem a seção)
        sup_in = _de_v1(sup_in)
    sb = base["supervisores"]
    entradas = {}
    for s in sup_in.get("lista") or []:
        sid = (s or {}).get("id")
        if sid not in SUPERVISORES:
            raise ValueError(f"supervisor desconhecido: {sid}")
        if sid in entradas:
            raise ValueError(f"supervisor repetido: {sid}")
        entradas[sid] = s
    lista = [_supervisor(entradas.get(b["id"]) or {}, b) for b in sb["lista"]]
    # Até 12/11/2026 positivação, novos e reativação usavam uma escala só ("escala_clientes"): quem não traz a
    # escala própria fica com uma cópia dela, ou com o padrão.
    antiga = sup_in.get("escala_clientes")
    sup = {
        "lista": lista,
        "escala_faturamento": _faixas(sup_in.get("escala_faturamento", sb["escala_faturamento"]),
                                      "da escala do faturamento e do mix", 5.0),
        **{k: _faixas(sup_in[k] if k in sup_in else antiga if antiga is not None else sb[k], nome, 5.0)
           for k, nome in ESCALAS_CLIENTES.items()},
        "trava": _faixas(sup_in.get("trava", sb["trava"]), "da trava", 1.0),
        "bonus": _faixas(sup_in.get("bonus", sb["bonus"]), "do bônus", 1.0, menor=1.0),
        "devolucao": _regra_devolucao(sup_in.get("devolucao"), sb["devolucao"]),
        "motivos_vencido": _inteiros(sup_in.get("motivos_vencido", sb["motivos_vencido"]), "motivos do vencido"),
        "produtos_fora_mix": _inteiros(sup_in.get("produtos_fora_mix", sb["produtos_fora_mix"]), "produtos fora do mix"),
        "dias_sem_compra": _inteiro(sup_in.get("dias_sem_compra", sb["dias_sem_compra"]),
                                    "dias sem comprar da reativação", 1, 730),
        "dias_inadimplencia": _inteiro(sup_in.get("dias_inadimplencia", sb["dias_inadimplencia"]),
                                       "dias de atraso da inadimplência", 0, 365),
        "metas_mes": _metas_mes(sup_in.get("metas_mes"), {s["id"]: s["nome"] for s in lista}),
    }
    # As versões salvas antes da aba Comissão não têm a seção: ficam com o padrão.
    com_in = cfg.get("comissao") or {}
    comissao = {"motivos_brindes": _inteiros(com_in.get("motivos_brindes", base["comissao"]["motivos_brindes"]),
                                             "motivos dos brindes da comissão")}
    return {"versao": 2, "vendedores": {"faixas": faixas}, "supervisores": sup, "comissao": comissao}


class ConfigPremiacoes(RegrasNoBanco):
    """Regras da página Premiações (tabela regras, nome "premiacoes")."""

    nome = "premiacoes"
    _valida = staticmethod(_valida)

    def _padrao(self) -> dict:
        return padrao()


# --- a conta (funções puras) ---------------------------------------------------------------
def _div(a: float, b: float) -> float | None:
    return a / b if b else None


def faixa(pct: float | None, faixas: list[dict]) -> dict | None:
    """A maior faixa atingida (pct ≥ min; as faixas não se somam); None = nenhuma."""
    atingidas = [f for f in faixas if pct is not None and pct + _EPS >= f["min"]]
    return max(atingidas, key=lambda f: f["min"]) if atingidas else None


faixa_vendedor = faixa


def proxima_faixa(pct: float | None, faixas: list[dict]) -> dict | None:
    acima = [f for f in faixas if pct is None or pct + _EPS < f["min"]]
    return min(acima, key=lambda f: f["min"]) if acima else None


def clientes_para(meta: float, minimo: float) -> int:
    """Quantos clientes atendidos chegam a `minimo` da meta."""
    return math.ceil(meta * minimo - _EPS)


def alcance(realizado: float | None, meta: float | None) -> float | None:
    """Realizado ÷ meta; None sem meta (ou meta zero)."""
    if realizado is None or not meta or meta <= 0:
        return None
    return realizado / meta


def pct_faixa(alcance_: float | None, faixas: list[dict]) -> float:
    """O % pago pela faixa atingida (escalas e trava); abaixo da primeira, 0."""
    f = faixa(alcance_, faixas)
    return f["pct"] if f else 0.0


def pct_bonus(alcance_fat: float | None, faixas: list[dict]) -> float:
    """O bônus de superação: só com o faturamento ACIMA de 100% da meta (100% exato não tem)."""
    if alcance_fat is None or alcance_fat <= 1 + _EPS:
        return 0.0
    return pct_faixa(alcance_fat, faixas)


def pct_devolucao(indice_: float | None, regra: dict) -> float:
    """O % do variável mantido pelo índice de vencido: o da primeira faixa com o índice até o limite dela (0,5% exato
    fica na faixa de até 0,5%); acima de todas, "acima". Sem índice (vencido sem vendas), "acima"."""
    if indice_ is None:
        return regra["acima"]
    for f in sorted(regra["faixas"], key=lambda f: f["ate"]):
        if indice_ <= f["ate"] + _EPS:
            return f["pct"]
    return regra["acima"]


def adicional_inadimplencia(regra: dict | None, indice_: float | None, trava: float) -> float:
    """O prêmio extra da inadimplência: pago com o índice até o limite, desde que a trava não tenha zerado o variável."""
    if not regra or trava <= 0 or indice_ is None:
        return 0.0
    return regra["valor"] if indice_ <= regra["limite"] + _EPS else 0.0


def conta_supervisor(parcelas: list[float], alcance_fat: float | None, indice_vencido: float | None, regras: dict,
                     adicional: dict | None = None, indice_inad: float | None = None) -> dict:
    """Do conquistado (a soma das parcelas) ao prêmio, na ordem dos regulamentos: trava, bônus, desconto pelo vencido e,
    por fora, o adicional da inadimplência. Cada passo é arredondado ao centavo e o seguinte usa o valor arredondado,
    para a conta mostrada fechar. regras: a seção "supervisores" das regras."""
    conquistado = round(sum(parcelas), 2)
    trava = pct_faixa(alcance_fat, regras["trava"])
    apos_trava = round(conquistado * trava, 2)
    bonus = pct_bonus(alcance_fat, regras["bonus"]) if trava > 0 else 0.0
    apos_bonus = round(apos_trava * (1 + bonus), 2)
    mantido = pct_devolucao(indice_vencido, regras["devolucao"])
    variavel = round(apos_bonus * mantido, 2)
    extra = adicional_inadimplencia(adicional, indice_inad, trava)
    ad = None
    if adicional:
        motivo = ("pago" if extra else "trava" if trava <= 0 else "sem_dados" if indice_inad is None else "acima")
        ad = {"valor_regra": adicional["valor"], "limite": adicional["limite"], "indice": indice_inad,
              "pago": bool(extra), "valor": round(extra, 2), "motivo": motivo}
    return {
        "conquistado": conquistado,
        "trava": {"alcance": alcance_fat, "pct": trava, "valor": apos_trava},
        "bonus": {"pct": bonus, "valor": round(apos_bonus - apos_trava, 2), "total": apos_bonus},
        "devolucao": {"indice": indice_vencido, "pct": mantido, "valor": round(variavel - apos_bonus, 2),
                      "total": variavel},
        "adicional": ad,
        "premio": round(variavel + extra, 2),
    }


def proxima(realizado: float | None, meta: float | None, faixas: list[dict], inteiro: bool) -> dict | None:
    """A faixa seguinte da escala e quanto falta para ela (clientes inteiros ou R$); None na última ou sem meta."""
    a = alcance(realizado, meta)
    if a is None:
        return None
    f = proxima_faixa(a, faixas)
    if not f:
        return None
    falta = clientes_para(meta, f["min"]) - realizado if inteiro else round(meta * f["min"] - realizado, 2)
    return {**f, "falta": max(falta, 1) if inteiro else max(falta, 0.01)}


def janela(i: int) -> tuple[int, int]:
    """Meses (índices) da inadimplência do mês i: de 7 a 2 meses antes (EOMONTH(-8)+1 a EOMONTH(-2) no Power BI)."""
    return i - JANELA_DE, i - JANELA_ATE


def _inicio(i: int) -> dt.date:
    return dt.date(i // 12, i % 12 + 1, 1)


def _fim(i: int) -> dt.date:
    a, m = i // 12, i % 12 + 1
    return dt.date(a, m, calendar.monthrange(a, m)[1])


def _mes(i: int) -> dict:
    return {"valor": texto_mes(i), "rotulo": rotulo_mes(i), "curto": curto_mes(i)}


def _limpar(texto) -> str:
    return " ".join(str(texto or "").replace("\xa0", " ").split())


_CODIGO_CLIENTE = re.compile(r"\s*\(\s*CLIENTE\s+[\d.,/-]+\s*\)", re.I)


def nome_cliente(nome) -> str:
    """O nome do cadastro sem o código que o ERP põe nele ("BAR DO ZE (CLIENTE 5959)" -> "BAR DO ZE"): quem vê a página
    não usa o código."""
    return _limpar(_CODIGO_CLIENTE.sub(" ", str(nome or ""))) or "Cliente sem nome"


# --- a página -----------------------------------------------------------------------------
class Premiacoes:
    def __init__(self, calc: Calculadora, config: ConfigPremiacoes, nomes_vendedores):
        """nomes_vendedores: função que devolve {id: nome} (a mesma das Projeções e do Assistente)."""
        self.calc = calc
        self.config = config
        self.nomes = nomes_vendedores

    def hoje(self) -> dt.date:
        """O dia da extração dos dados (o "hoje" da inadimplência, como na Reavaliação de Crédito)."""
        v = self.calc.cache.info.get("extraido_em")
        return dt.datetime.fromisoformat(v).date() if v else dt.date.today()

    def _conferir(self, detalhe: bool = False) -> None:
        cache = self.calc.cache
        if not cache.pronto():
            raise RuntimeError("os dados ainda estão sendo preparados")
        if detalhe and (cache.antigo or cache.sem_detalhe):
            raise RuntimeError("os dados por cliente ainda não chegaram do computador da empresa; esta aba aparece "
                               "depois da próxima atualização")

    @staticmethod
    def estados_supervisor(permitidos: set[int] | None, equipes: set[str] | None) -> list[str]:
        """Os estados cuja premiação dos supervisores o usuário vê: ela soma a carteira inteira do estado, então só quem
        vê todos os vendedores (sem lista de vendedores) e tem a equipe do estado."""
        if permitidos is not None:
            return []
        return [e for e in ESTADOS if equipes is None or e in equipes]

    def supervisores_do_acesso(self, permitidos: set[int] | None, equipes: set[str] | None,
                               supervisores: list[str] | None = None, cfg: dict | None = None) -> list[dict]:
        """Os supervisores (das regras, na ordem delas) cujo quadro o usuário vê: os liberados para ele na configuração da
        página (None = todos) que são de um estado cuja carteira inteira ele vê (estados_supervisor)."""
        estados = self.estados_supervisor(permitidos, equipes)
        lista = (cfg or self.config.atual())["supervisores"]["lista"]
        return [s for s in lista if s["estado"] in estados and (supervisores is None or s["id"] in supervisores)]

    def abas_do_acesso(self, permitidos: set[int] | None, equipes: set[str] | None, abas: list[str] | None = None,
                       supervisores: list[str] | None = None, cfg: dict | None = None) -> list[str]:
        """As abas que o usuário vê, na ordem da página: as liberadas para ele na configuração da página (None = todas);
        a dos supervisores, só com o quadro de algum supervisor que ele possa ver."""
        return [a for a in ABAS if (abas is None or a in abas)
                and (a != "supervisores" or self.supervisores_do_acesso(permitidos, equipes, supervisores, cfg))]

    def meses(self) -> list[int]:
        """Os meses com meta de clientes até o mês dos dados (do mais novo ao mais velho)."""
        cache = self.calc.cache
        ultimo = indice(cache.data_ref())
        primeiro = indice(dt.date.fromisoformat(cache.info.get("inicio") or "2024-01-01"))
        com_meta = {indice(m["mes"]) for m in self.calc.metas.dados() if (m.get("meta_cli") or 0) > 0}
        return sorted((i for i in com_meta if primeiro <= i <= ultimo), reverse=True)

    def meses_dados(self) -> list[int]:
        """Todos os meses com dados, do mês dos dados ao início do cache (a aba Comissão não depende de meta)."""
        cache = self.calc.cache
        primeiro = indice(dt.date.fromisoformat(cache.info.get("inicio") or "2024-01-01"))
        return list(range(indice(cache.data_ref()), primeiro - 1, -1))

    def _escolher_mes(self, mes: str | None, meses: list[int] | None = None,
                      quais: str = "com meta de clientes") -> tuple[int, list[int]]:
        meses = self.meses() if meses is None else meses
        if not meses:
            raise ValueError("não há meses com meta de clientes na planilha de metas")
        if not mes:
            atual = indice(self.calc.cache.data_ref())
            return (atual if atual in meses else meses[0]), meses
        i = ler_mes(mes)
        if i not in meses:
            raise ValueError(f"escolha um mês {quais} entre {curto_mes(meses[-1])} e {curto_mes(meses[0])}")
        return i, meses

    def _base(self, aba: str, i: int, meses: list[int], abas: list[str]) -> dict:
        """O que toda aba devolve. abas: as que o usuário vê (abas_do_acesso)."""
        hoje = self.hoje()
        return {
            "aba": aba,
            "abas": abas,
            "mes": _mes(i),
            "meses": [_mes(m) for m in meses],
            "situacao": "final" if hoje > _fim(i) else "prevista",
            "data_ref": self.calc.cache.data_ref().isoformat(),
            "hoje": hoje.isoformat(),
            "avisos": self.calc.avisos(),
        }

    def calcular(self, aba: str | None = None, mes: str | None = None, permitidos: set[int] | None = None,
                 equipes: set[str] | None = None, abas: list[str] | None = None,
                 supervisores: list[str] | None = None) -> dict:
        """aba: vendedores, supervisores ou comissao (vazio = a primeira que o usuário vê); mes: AAAA-MM (vazio = o mês
        dos dados). permitidos/equipes: os vendedores do acesso (tela Usuários; None = sem limite). abas/supervisores: o
        que a configuração da página libera para o usuário (bi/acesso.py premiacoes_permitidas; None = tudo). Aba fora do
        acesso -> PermissionError."""
        if aba and aba not in ABAS:
            raise ValueError(f"aba desconhecida: {aba}")
        vistas = self.abas_do_acesso(permitidos, equipes, abas, supervisores)
        if not vistas:
            raise PermissionError("seu acesso ainda não tem nenhuma aba das Premiações liberada; fale com o "
                                  "administrador")
        aba = aba or vistas[0]
        if aba not in vistas:
            if aba == "supervisores" and (abas is None or aba in abas) and not self.estados_supervisor(permitidos,
                                                                                                        equipes):
                raise PermissionError("a premiação dos supervisores soma a carteira inteira do estado: seu acesso, "
                                      "limitado a alguns vendedores ou equipes, não a inclui")
            raise PermissionError(f"seu acesso não inclui a aba {TITULOS_ABAS[aba]} das Premiações")
        if aba == "supervisores":
            return self.supervisores(mes, permitidos, equipes, supervisores, vistas)
        if aba == "comissao":
            return self.comissao(mes, permitidos, equipes, vistas)
        return self.vendedores(mes, permitidos, equipes, vistas)

    def pdf(self, aba: str | None = None, mes: str | None = None, permitidos: set[int] | None = None,
            equipes: set[str] | None = None, abas: list[str] | None = None,
            supervisores: list[str] | None = None) -> tuple[bytes, str]:
        """A tabela de uma aba em PDF (bi/premiacoes_pdf.py), com o mesmo acesso de calcular: (conteúdo, nome do
        arquivo). Aba sem nada para mostrar no mês -> ValueError."""
        d = self.calcular(aba, mes, permitidos, equipes, abas, supervisores)
        return premiacoes_pdf.documento(d), premiacoes_pdf.nome_arquivo(d)

    # --- vendedores --------------------------------------------------------------------------
    def vendedores(self, mes: str | None = None, permitidos: set[int] | None = None,
                   equipes: set[str] | None = None, abas: list[str] | None = None) -> dict:
        """abas: as que o usuário vê (None = abas_do_acesso só pelos vendedores do acesso)."""
        self._conferir()
        i, meses = self._escolher_mes(mes)
        regras = self.calc.regras()
        faixas = self.config.atual()["vendedores"]["faixas"]
        m = _inicio(i)
        metas: dict[int, dict] = {}
        for r in self.calc.metas.dados():
            vid, meta = r["id_vendedor"], r.get("meta_cli") or 0
            if r["mes"] != m or meta <= 0:
                continue
            grupo = regras.grupo_vendedor(vid)
            if grupo == "OCULTO" or (equipes is not None and grupo not in equipes) \
                    or (permitidos is not None and vid not in permitidos):
                continue
            x = metas.setdefault(vid, {"meta": 0.0, "grupo": grupo, "nome": r["vendedor"], "aprovada": False})
            x["meta"] += meta
            x["aprovada"] = x["aprovada"] or bool(r.get("aprovada"))
        atendidos, total_atendidos = self.calc._clientes(sorted(metas), [m])
        linhas = []
        for vid, x in metas.items():
            real = atendidos.get(vid, 0)
            pct = _div(real, x["meta"])
            f = faixa_vendedor(pct, faixas)
            prox = proxima_faixa(pct, faixas)
            linhas.append({
                "id": vid, "nome": nome_bonito(x["nome"]), "equipe": x["grupo"],
                "estado": "ES" if x["grupo"] == "ES" else "BA", "aprovada": x["aprovada"],
                "meta": x["meta"], "atendidos": real, "pct": pct,
                "faixa": f, "premio": f["valor"] if f else 0.0,
                "proxima": {**prox, "faltam": max(clientes_para(x["meta"], prox["min"]) - real, 1)} if prox else None,
            })
        linhas.sort(key=lambda v: v["nome"].upper())
        meta_total = sum(v["meta"] for v in linhas)
        return {
            **self._base("vendedores", i, meses, abas if abas is not None else self.abas_do_acesso(permitidos, equipes)),
            "faixas": faixas,
            "vendedores": linhas,
            "total": {"meta": meta_total, "atendidos": total_atendidos, "pct": _div(total_atendidos, meta_total),
                      "premio": round(sum(v["premio"] for v in linhas), 2), "vendedores": len(linhas),
                      "premiados": sum(1 for v in linhas if v["premio"] > 0)},
        }

    # --- supervisores ------------------------------------------------------------------------
    def _carteiras(self, regras) -> dict[int, str]:
        """{vendedor: estado} dos vendedores que têm clientes na carteira e são de um estado (sem o "ES" de quem não é
        configurado: terceiros e contas internas ficam fora, como nas listas fixas do Power BI)."""
        saida = {}
        for (vid,) in self.calc.cache.consulta("SELECT DISTINCT id_vendedor FROM clientes"):
            estado = regras.grupo_conhecido(vid)
            if estado in ESTADOS:
                saida[vid] = estado
        return saida

    def _por_vendedor(self, sql: str, ids: list[int], params: list) -> list[tuple]:
        """Roda `sql` (com {ids} no lugar da lista de vendedores da carteira, depois dos outros parâmetros) e devolve as
        linhas."""
        if not ids:
            return []
        return self.calc.cache.consulta(sql.format(ids=",".join("?" * len(ids))), [*params, *ids])

    def _movimento(self, regras, ids: list[int], de: dt.date, ate: dt.date, fora_mix: set[int],
                   vencido: set[int], com_brindes: bool = True) -> dict[int, dict]:
        """Por vendedor da carteira, só de cliente e sem os produtos que ficam fora das metas: as vendas, as devoluções
        que descontam na meta (os motivos e as canceladas de Metas › Configurar), a parte de cada uma que fica fora do
        mix (com as equivalências) e o vencido (devoluções não canceladas e brindes com os motivos de `vencido`)."""
        cache = self.calc.cache
        mov: dict[int, dict] = {}

        def x(vid):
            return mov.setdefault(vid, {"vendas": 0.0, "vendas_fora_mix": 0.0, "dev": 0.0, "dev_fora_mix": 0.0,
                                        "dev_vencido": 0.0, "brindes_vencido": 0.0})

        junta = ("FROM {tabela} x JOIN clientes c ON c.id = x.id_cliente WHERE x.tipocliente = 'CLIENTE' "
                 "AND x.data BETWEEN ? AND ? AND c.id_vendedor IN ({{ids}})")
        for vid, pid, valor in self._por_vendedor(
                "SELECT c.id_vendedor, x.id_produto, SUM(x.valor) " + junta.format(tabela="vendas_clientes_itens")
                + " GROUP BY 1, 2", ids, [de, ate]):
            p = regras.produto(pid)
            if regras.grupo_produto(p) == "fora":
                continue
            x(vid)["vendas"] += valor
            if p in fora_mix:
                x(vid)["vendas_fora_mix"] += valor
        for vid, pid, motivo, cancelada, valor in self._por_vendedor(
                "SELECT c.id_vendedor, x.id_produto, x.id_motivo, x.cancelada, SUM(x.valor) "
                + junta.format(tabela="devolucoes_clientes_itens") + " GROUP BY 1, 2, 3, 4", ids, [de, ate]):
            p = regras.produto(pid)
            if regras.grupo_produto(p) == "fora":
                continue
            if motivo in regras.motivos and not (cancelada and regras.ignorar_canceladas):
                x(vid)["dev"] += valor
                if p in fora_mix:
                    x(vid)["dev_fora_mix"] += valor
            if motivo in vencido and not cancelada:
                x(vid)["dev_vencido"] += valor
        if com_brindes and vencido and not cache.sem_brindes:
            for vid, pid, motivo, valor in self._por_vendedor(
                    "SELECT c.id_vendedor, x.id_produto, x.id_motivo, SUM(x.valor) "
                    + junta.format(tabela="brindes_clientes_itens") + " GROUP BY 1, 2, 3", ids, [de, ate]):
                if motivo in vencido and regras.grupo_produto(regras.produto(pid)) != "fora":
                    x(vid)["brindes_vencido"] += valor
        return mov

    def _novos(self, ids: list[int], de: dt.date, ate: dt.date) -> list[tuple]:
        """Os clientes da carteira (pelo vendedor de hoje) cadastrados no ERP no período que compraram no mesmo
        período: (vendedor, cliente, nome, cidade, cadastro, primeira compra, inativo hoje)."""
        return self._por_vendedor(
            "SELECT c.id_vendedor, c.id, c.nome, d.cidade, d.data_cadastro, MIN(v.data), MAX(d.inativo) "
            "FROM clientes c JOIN clientes_detalhes d ON d.id = c.id "
            "JOIN vendas_clientes v ON v.id_cliente = c.id AND v.tipocliente = 'CLIENTE' AND v.data BETWEEN ? AND ? "
            "WHERE d.data_cadastro BETWEEN ? AND ? AND c.id_vendedor IN ({ids}) GROUP BY 1, 2, 3, 4, 5",
            ids, [de, ate, de, ate])

    def _reativacoes(self, ids: list[int], de: dt.date, ate: dt.date, dias: int) -> list[tuple]:
        """Os clientes da carteira (pelo vendedor de hoje) com uma compra no período feita depois de `dias` dias ou mais
        sem comprar, contados da compra anterior até essa. Só conta quem já tinha comprado: a compra anterior é a última
        venda do cache ou, sem nenhuma, o último título de venda do ERP de antes do início das vendas do cache (os
        títulos vão até 2012). Quem nunca comprou não é reativação. (vendedor, cliente, nome, cidade, data da compra,
        dias sem comprar, data da compra anterior)."""
        cache = self.calc.cache
        inicio = dt.date.fromisoformat(cache.info.get("inicio") or "2024-01-01")
        # Sem os títulos no cache (código anterior no computador da empresa), só as vendas do cache contam.
        com_titulos = not cache.sem_credito
        anterior = "COALESCE(g.anterior, a.ultima)" if com_titulos else "g.anterior"
        titulos = ("LEFT JOIN (SELECT id_cliente, MAX(emissao) AS ultima FROM titulos_receber WHERE emissao < ? "
                   "GROUP BY 1) a ON a.id_cliente = g.id_cliente " if com_titulos else "")
        sql = ("WITH v AS (SELECT DISTINCT id_cliente, data FROM vendas_clientes WHERE tipocliente = 'CLIENTE' "
               "AND data <= ? AND id_cliente IN (SELECT id_cliente FROM vendas_clientes "
               "WHERE tipocliente = 'CLIENTE' AND data BETWEEN ? AND ?)), "
               "g AS (SELECT id_cliente, data, lag(data) OVER (PARTITION BY id_cliente ORDER BY data) AS anterior "
               "FROM v) "
               f"SELECT c.id_vendedor, c.id, c.nome, d.cidade, MIN(g.data), MAX(g.data - {anterior}), MAX({anterior}) "
               "FROM g JOIN clientes c ON c.id = g.id_cliente LEFT JOIN clientes_detalhes d ON d.id = c.id "
               + titulos +
               f"WHERE g.data BETWEEN ? AND ? AND g.data - {anterior} >= ? "
               "AND c.id_vendedor IN ({ids}) GROUP BY 1, 2, 3, 4")
        return self._por_vendedor(sql, ids, [ate, de, ate, *([inicio] if com_titulos else []), de, ate, dias])

    def metas_supervisores(self, regras, i: int, cfg: dict | None = None) -> dict[str, dict]:
        """{supervisor: {fat, cli, novos, reativacao, "auto": {...}, "ajustada": {...}}}: faturamento e clientes pela
        soma das metas dos vendedores do estado no mês (o Edir é outro grupo: fica fora do BA), novos e reativação pela
        meta padrão do supervisor, e o ajuste à mão do mês por cima (0 = sem meta)."""
        cfg = cfg or self.config.atual()
        m = _inicio(i)
        soma = {e: {"fat": 0.0, "cli": 0.0} for e in ESTADOS}
        for r in self.calc.metas.dados():
            if r["mes"] != m:
                continue
            estado = regras.grupo_vendedor(r["id_vendedor"])
            if estado in soma:
                soma[estado]["fat"] += r.get("meta_fat") or 0
                soma[estado]["cli"] += r.get("meta_cli") or 0
        sup = cfg["supervisores"]
        ajustes = sup["metas_mes"].get(texto_mes(i), {})
        saida = {}
        for s in sup["lista"]:
            auto = {**soma[s["estado"]], **s["metas_padrao"]}
            aj = ajustes.get(s["id"], {})
            saida[s["id"]] = {**{k: aj.get(k, auto[k]) for k in METAS_MES}, "auto": auto,
                              "ajustada": {k: k in aj for k in METAS_MES}}
        return saida

    def _numeros_estado(self, vids: list[int], dados: dict, nomes: dict[int, str]) -> dict:
        """Os números de um estado (a soma dos vendedores da carteira dele): os mesmos para os supervisores do estado."""
        mov, positivados = dados["mov"], dados["positivados"]
        inadimplente, liquido_6m = dados["inadimplente"], dados["liquido_6m"]
        doestado = set(vids)
        novos = [n for n in dados["novos"] if n[0] in doestado]
        reativados = [r for r in dados["reativados"] if r[0] in doestado]
        soma = lambda k: sum(mov.get(v, {}).get(k, 0.0) for v in vids)  # noqa: E731
        vendas, dev = soma("vendas"), soma("dev")
        liquido = vendas - dev
        liquido_mix = (vendas - soma("vendas_fora_mix")) - (dev - soma("dev_fora_mix"))
        dev_vencido, brindes_vencido = soma("dev_vencido"), soma("brindes_vencido")
        vencido = dev_vencido + brindes_vencido
        liq6 = sum(liquido_6m.get(v, 0.0) for v in vids)
        inad = sum(inadimplente.get(v, 0.0) for v in vids)
        n_novos, n_reat = Counter(n[0] for n in novos), Counter(r[0] for r in reativados)
        por_vendedor = []
        for v in vids:
            mv = mov.get(v, {})
            if not (mv or positivados.get(v) or n_novos[v] or n_reat[v] or inadimplente.get(v)):
                continue
            liq_v = mv.get("vendas", 0.0) - mv.get("dev", 0.0)
            liq_mix_v = liq_v - (mv.get("vendas_fora_mix", 0.0) - mv.get("dev_fora_mix", 0.0))
            por_vendedor.append({
                "id": v, "nome": nomes.get(v) or f"Vendedor {v}", "liquido": liq_v, "pct_mix": _div(liq_mix_v, liq_v),
                "positivacao": positivados.get(v, 0), "novos": n_novos[v], "reativacoes": n_reat[v],
                "vencido": mv.get("dev_vencido", 0.0) + mv.get("brindes_vencido", 0.0),
                "inadimplente": inadimplente.get(v, 0.0),
            })
        por_vendedor.sort(key=lambda r: -r["liquido"])
        lista_novos = sorted(({"nome": nome_cliente(nome), "cidade": _limpar(cidade) or None,
                               "vendedor": nomes.get(vid) or f"Vendedor {vid}", "cadastro": cad.isoformat(),
                               "compra": compra.isoformat(), "inativo": bool(inativo)}
                              for vid, _, nome, cidade, cad, compra, inativo in novos),
                             key=lambda c: (c["cadastro"], c["nome"]))
        lista_reat = sorted(({"nome": nome_cliente(nome), "cidade": _limpar(cidade) or None,
                              "vendedor": nomes.get(vid) or f"Vendedor {vid}", "data": compra.isoformat(),
                              "dias": int(dias), "anterior": anterior.isoformat(),
                              "antes_das_vendas": anterior < dados["inicio"]}
                             for vid, _, nome, cidade, compra, dias, anterior in reativados),
                            key=lambda c: (c["data"], c["nome"]))
        return {
            "vendas": vendas, "devolucoes": dev, "liquido": liquido, "liquido_mix": liquido_mix,
            "pct_mix": _div(liquido_mix, liquido) if liquido > 0 else None,
            "dev_vencido": dev_vencido, "brindes_vencido": brindes_vencido, "vencido": vencido,
            "indice_vencido": _div(vencido, vendas) if vendas > 0 else (0.0 if not vencido else None),
            "positivacao": sum(positivados.get(v, 0) for v in vids),
            "novos": len(lista_novos), "reativacoes": len(lista_reat),
            "liquido_6m": liq6, "inadimplente": inad,
            "indice_inadimplencia": (None if dados["sem_credito"]
                                     else _div(inad, liq6) if liq6 > 0 else (0.0 if not inad else None)),
            "por_vendedor": por_vendedor, "lista_novos": lista_novos, "lista_reativacoes": lista_reat,
        }

    @staticmethod
    def _cartao(s: dict, n: dict, metas: dict, cfg: dict) -> dict:
        """O quadro de um supervisor: as parcelas de cada indicador que ele usa (o faturamento sempre, porque move a
        trava e o bônus) e a conta até o prêmio."""
        realizado = {"faturamento": n["liquido"], "mix": n["pct_mix"], "positivacao": n["positivacao"],
                     "novos": n["novos"], "reativacao": n["reativacoes"]}
        alvo = {"faturamento": metas["fat"], "mix": s["meta_mix"], "positivacao": metas["cli"],
                "novos": metas["novos"], "reativacao": metas["reativacao"]}
        indicadores, parcelas = [], []
        for k in INDICADORES:
            peso = s["pesos"][k]
            if peso <= 0 and k != "faturamento":
                continue
            escala = cfg[ESCALA[k]]
            a = alcance(realizado[k], alvo[k])
            f = faixa(a, escala)
            referencia = round(s["variavel"] * peso, 2)
            parcela = round(referencia * (f["pct"] if f else 0.0), 2)
            parcelas.append(parcela)
            ind = {"id": k, "titulo": TITULOS[k], "peso": peso, "referencia": referencia, "realizado": realizado[k],
                   "meta": alvo[k], "alcance": a, "faixa": f, "pct": f["pct"] if f else 0.0, "parcela": parcela,
                   "sem_meta": not alvo[k], "so_trava": peso <= 0,
                   "proxima": None if k == "mix" else proxima(realizado[k], alvo[k], escala, k != "faturamento")}
            if k in META_DO_INDICADOR:
                chave = META_DO_INDICADOR[k]
                ind.update(meta_auto=metas["auto"][chave], ajustada=metas["ajustada"][chave])
            indicadores.append(ind)
        conta = conta_supervisor(parcelas, indicadores[0]["alcance"], n["indice_vencido"], cfg, s["inadimplencia"],
                                 n["indice_inadimplencia"])
        usa_mix, usa_inad = s["pesos"]["mix"] > 0, bool(s["inadimplencia"])
        contas = {k: n[k] for k in ("vendas", "devolucoes", "liquido", "dev_vencido", "brindes_vencido", "vencido",
                                    "indice_vencido", "positivacao", "novos", "reativacoes")}
        if usa_mix:
            contas.update(liquido_mix=n["liquido_mix"], pct_mix=n["pct_mix"])
        if usa_inad:
            contas.update(liquido_6m=n["liquido_6m"], inadimplente=n["inadimplente"],
                          indice_inadimplencia=n["indice_inadimplencia"])
        return {
            "id": s["id"], "nome": s["nome"], "estado": s["estado"], "variavel": s["variavel"],
            "usa_mix": usa_mix, "usa_inadimplencia": usa_inad,
            "indicadores": indicadores, **conta, "contas": contas,
            "vendedores": n["por_vendedor"],
            "clientes": {"novos": n["lista_novos"], "reativacoes": n["lista_reativacoes"]},
        }

    def supervisores(self, mes: str | None = None, permitidos: set[int] | None = None,
                     equipes: set[str] | None = None, quais: list[str] | None = None,
                     abas: list[str] | None = None) -> dict:
        """quais: os supervisores liberados para o usuário na configuração da página (None = todos); só aparecem os de
        um estado cuja carteira inteira ele vê. abas: as que ele vê (None = abas_do_acesso só pelos vendedores)."""
        if not self.estados_supervisor(permitidos, equipes):
            raise PermissionError("a premiação dos supervisores soma a carteira inteira do estado: seu acesso, limitado "
                                  "a alguns vendedores ou equipes, não a inclui")
        cfg_total = self.config.atual()
        lista = self.supervisores_do_acesso(permitidos, equipes, quais, cfg_total)
        if not lista:
            raise PermissionError("seu acesso não inclui o quadro de nenhum supervisor")
        estados = [e for e in ESTADOS if any(s["estado"] == e for s in lista)]
        self._conferir(detalhe=True)
        cache = self.calc.cache
        i, meses = self._escolher_mes(mes)
        regras = self.calc.regras()
        cfg = cfg_total["supervisores"]
        fora_mix = set(cfg["produtos_fora_mix"]) | {regras.produto(p) for p in cfg["produtos_fora_mix"]}
        vencido = set(cfg["motivos_vencido"])
        carteiras = self._carteiras(regras)
        ids = sorted(v for v, e in carteiras.items() if e in estados)
        de, ate = _inicio(i), _fim(i)
        j_de, j_ate = janela(i)
        corte = self.hoje() - dt.timedelta(days=cfg["dias_inadimplencia"])
        inicio = dt.date.fromisoformat(cache.info.get("inicio") or "2024-01-01")  # das vendas do cache

        # A inadimplência só é calculada para os estados de quem tem o adicional.
        estados_inad = {s["estado"] for s in lista if s["inadimplencia"]}
        ids_inad = [v for v in ids if carteiras[v] in estados_inad]
        inadimplente = {} if cache.sem_credito else dict(self._por_vendedor(
            "SELECT c.id_vendedor, SUM(t.total) FROM titulos_receber t JOIN clientes c ON c.id = t.id_cliente "
            "WHERE t.quitado = 0 AND t.vencimento <= ? AND t.emissao BETWEEN ? AND ? AND c.id_vendedor IN ({ids}) "
            "GROUP BY 1", ids_inad, [corte, _inicio(j_de), _fim(j_ate)]))
        liquido_6m = {vid: m["vendas"] - m["dev"] for vid, m in self._movimento(
            regras, ids_inad, _inicio(j_de), _fim(j_ate), set(), set(), com_brindes=False).items()}
        dados = {
            "mov": self._movimento(regras, ids, de, ate, fora_mix, vencido),
            "positivados": dict(self._por_vendedor(
                "SELECT c.id_vendedor, COUNT(DISTINCT x.id_cliente) FROM vendas_clientes x JOIN clientes c "
                "ON c.id = x.id_cliente WHERE x.tipocliente = 'CLIENTE' AND x.data BETWEEN ? AND ? "
                "AND c.id_vendedor IN ({ids}) GROUP BY 1", ids, [de, ate])),
            "novos": self._novos(ids, de, ate),
            "reativados": self._reativacoes(ids, de, ate, cfg["dias_sem_compra"]),
            "inadimplente": inadimplente, "liquido_6m": liquido_6m, "sem_credito": bool(cache.sem_credito),
            "inicio": inicio,
        }
        nomes = self.nomes()
        numeros = {e: self._numeros_estado([v for v in ids if carteiras[v] == e], dados, nomes) for e in estados}
        metas = self.metas_supervisores(regras, i, cfg_total)
        cartoes = [self._cartao(s, numeros[s["estado"]], metas[s["id"]], cfg) for s in lista]

        avisos = []
        for c in cartoes:
            if c["indicadores"][0]["sem_meta"]:
                avisos.append(f"{c['nome']}: sem meta de faturamento em {curto_mes(i)}; sem ela, a trava zera o prêmio.")
            outros = [x["titulo"].lower() for x in c["indicadores"][1:] if x["sem_meta"]]
            if outros:
                quais = outros[0] if len(outros) == 1 else f"{', '.join(outros[:-1])} e {outros[-1]}"
                avisos.append(f"{c['nome']}: sem meta de {quais} em {curto_mes(i)}; a parcela fica em R$ 0 (as metas "
                              "ficam em Premiações › Configurar).")
        if cache.sem_brindes:
            avisos.append("Os brindes ainda não chegaram do computador da empresa: o vencido conta só as devoluções até a "
                          "próxima atualização.")
        if estados_inad and cache.sem_credito:
            avisos.append("Os títulos a receber ainda não chegaram do computador da empresa: o prêmio da inadimplência "
                          "não é pago até a próxima atualização.")
        if cache.sem_credito and any(s["pesos"]["reativacao"] > 0 for s in lista):
            avisos.append("Os títulos a receber ainda não chegaram do computador da empresa: na reativação, quem não "
                          f"compra desde antes de {inicio.strftime('%m/%Y')} não aparece até a próxima atualização.")
        if estados_inad and _inicio(j_de) < inicio:
            avisos.append(f"A janela da inadimplência começa em {curto_mes(j_de)}, antes do início dos dados "
                          f"({inicio.strftime('%m/%Y')}): o faturamento dos 6 meses fica menor que o real.")
        return {
            **self._base("supervisores", i, meses,
                         abas if abas is not None else self.abas_do_acesso(permitidos, equipes, cfg=cfg_total)),
            "supervisores": cartoes,
            "escalas": {k: cfg[k] for k in ("escala_faturamento", *ESCALAS_CLIENTES, "trava", "bonus", "devolucao")},
            "janela": {"de": texto_mes(j_de), "ate": texto_mes(j_ate), "rotulo": f"{curto_mes(j_de)} a {curto_mes(j_ate)}"},
            "corte_vencimento": corte.isoformat(),
            "dias_atraso": cfg["dias_inadimplencia"],
            "dias_sem_compra": cfg["dias_sem_compra"],
            "inicio_dados": inicio.isoformat(),
            "produtos_fora_mix": self._nomes_produtos(cfg["produtos_fora_mix"]),
            "motivos_vencido": self._nomes_motivos(cfg["motivos_vencido"]),
            "motivos_meta": self._nomes_motivos(sorted(regras.motivos)),
            "canceladas_descontam": not regras.ignorar_canceladas,
            "sem_brindes": bool(cache.sem_brindes),
            "sem_credito": bool(cache.sem_credito),
            "avisos": self.calc.avisos() + avisos,
        }

    # --- comissão ----------------------------------------------------------------------------
    def _movimento_comissao(self, de: dt.date, ate: dt.date, motivos: list[int]) -> dict[int, dict[int, dict]]:
        """{vendedor: {produto: vendido, comissão gravada, devolvido, brindes}} do mês, só de tipo CLIENTE."""
        cache = self.calc.cache
        mov: dict[int, dict[int, dict]] = {}

        def x(vid, pid):
            return mov.setdefault(vid, {}).setdefault(
                pid, {"vendido": 0.0, "comissao": 0.0, "devolvido": 0.0, "brindes": 0.0})

        for vid, pid, valor, com in cache.consulta(
                "SELECT id_vendedor, id_produto, SUM(valor), SUM(comissao) FROM comissoes_vendas "
                "WHERE tipocliente = 'CLIENTE' AND data BETWEEN ? AND ? GROUP BY 1, 2", [de, ate]):
            x(vid, pid)["vendido"] += valor
            x(vid, pid)["comissao"] += com
        for vid, pid, valor in cache.consulta(
                "SELECT id_vendedor, id_produto, SUM(valor) FROM devolucoes_clientes_itens WHERE tipocliente = 'CLIENTE' "
                "AND NOT cancelada AND data BETWEEN ? AND ? GROUP BY 1, 2", [de, ate]):
            x(vid, pid)["devolvido"] += valor
        if motivos and not cache.sem_brindes:
            for vid, pid, valor in cache.consulta(
                    "SELECT id_vendedor, id_produto, SUM(valor) FROM brindes_clientes_itens WHERE tipocliente = "
                    f"'CLIENTE' AND data BETWEEN ? AND ? AND id_motivo IN ({','.join('?' * len(motivos))}) GROUP BY 1, 2",
                    [de, ate, *motivos]):
                x(vid, pid)["brindes"] += valor
        return mov

    def comissao(self, mes: str | None = None, permitidos: set[int] | None = None,
                 equipes: set[str] | None = None, abas: list[str] | None = None) -> dict:
        """A comissão de cada vendedor das equipes BA e ES no mês: a das vendas (gravada pelo ERP) menos as devoluções e
        os brindes escolhidos × o % de hoje da tabela do vendedor para o produto. abas: as que o usuário vê (None =
        abas_do_acesso só pelos vendedores)."""
        self._conferir(detalhe=True)
        cache = self.calc.cache
        if cache.sem_comissao:
            raise RuntimeError("a comissão das vendas ainda não chegou do computador da empresa; a aba aparece depois "
                               "da próxima atualização")
        i, meses = self._escolher_mes(mes, self.meses_dados(), "com dados")
        regras = self.calc.regras()
        motivos = self.config.atual()["comissao"]["motivos_brindes"]
        pcts = {(v, p): pct for v, p, pct in cache.consulta(
            "SELECT id_vendedor, id_produto, MAX(pct) FROM comissoes_percentuais GROUP BY 1, 2")}
        mov = self._movimento_comissao(_inicio(i), _fim(i), motivos)

        estados = {}
        for vid in mov:
            estado = regras.grupo_conhecido(vid)
            if estado in ESTADOS and (equipes is None or estado in equipes) \
                    and (permitidos is None or vid in permitidos):
                estados[vid] = estado
        nomes_produtos = {p["id"]: p["nome"] for p in self._nomes_produtos(
            sorted({pid for vid in estados for pid in mov[vid]}))}
        nomes = self.nomes()
        linhas = []
        for vid, estado in estados.items():
            produtos = []
            for pid, r in mov[vid].items():
                pct_tabela = pcts.get((vid, pid))
                taxa = (pct_tabela or 0.0) / 100
                produtos.append({
                    "id": pid, "nome": nomes_produtos.get(pid) or f"Produto {pid}",
                    "vendido": r["vendido"], "comissao": r["comissao"], "pct": _div(r["comissao"], r["vendido"]),
                    "devolvido": r["devolvido"], "brindes": r["brindes"],
                    "pct_tabela": None if pct_tabela is None else pct_tabela / 100,
                    "desc_devolucoes": r["devolvido"] * taxa, "desc_brindes": r["brindes"] * taxa,
                    "liquido": r["comissao"] - (r["devolvido"] + r["brindes"]) * taxa,
                    "sem_pct": pct_tabela is None and bool(r["devolvido"] or r["brindes"]),
                })
            soma = lambda k: sum(p[k] for p in produtos)  # noqa: E731
            vendido, com_bruta = soma("vendido"), soma("comissao")
            if not (vendido or soma("devolvido") or soma("brindes")):
                continue
            produtos.sort(key=lambda p: (-p["comissao"], -p["devolvido"] - p["brindes"], p["nome"]))
            c, d, b = round(com_bruta, 2), round(soma("desc_devolucoes"), 2), round(soma("desc_brindes"), 2)
            linhas.append({
                "id": vid, "nome": nomes.get(vid) or f"Vendedor {vid}", "estado": estado,
                "vendido": round(vendido, 2), "comissao_vendas": c, "pct": _div(com_bruta, vendido),
                "devolvido": round(soma("devolvido"), 2), "desc_devolucoes": d,
                "brindes": round(soma("brindes"), 2), "desc_brindes": b, "a_pagar": round(c - d - b, 2),
                "sem_pct": round(sum(p["devolvido"] + p["brindes"] for p in produtos if p["sem_pct"]), 2),
                "produtos": produtos,
            })
        linhas.sort(key=lambda v: v["nome"].upper())

        chaves = ("vendido", "comissao_vendas", "devolvido", "desc_devolucoes", "brindes", "desc_brindes", "a_pagar",
                  "sem_pct")
        total = {k: round(sum(v[k] for v in linhas), 2) for k in chaves}
        total.update(pct=_div(total["comissao_vendas"], total["vendido"]), vendedores=len(linhas))
        por_estado = [{"estado": e, "vendedores": sum(1 for v in linhas if v["estado"] == e),
                       "a_pagar": round(sum(v["a_pagar"] for v in linhas if v["estado"] == e), 2)}
                      for e in ESTADOS if any(v["estado"] == e for v in linhas)]
        avisos = []
        if cache.sem_brindes:
            avisos.append("Os brindes ainda não chegaram do computador da empresa: a comissão está sem o desconto deles "
                          "até a próxima atualização.")
        sem_pct = [p for v in linhas for p in v["produtos"] if p["sem_pct"]]
        if sem_pct:
            valor = f"{total['sem_pct']:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
            avisos.append(f"R$ {valor} em devoluções e brindes ({len(sem_pct)} produto{'s' if len(sem_pct) != 1 else ''} "
                          "de algum vendedor) não descontam: o vendedor não tem % de comissão para o produto na tabela "
                          "do ERP. Veja em Comissão por produto.")
        return {
            **self._base("comissao", i, meses, abas if abas is not None else self.abas_do_acesso(permitidos, equipes)),
            "vendedores": linhas,
            "total": total,
            "por_estado": por_estado,
            "motivos_brindes": self._nomes_motivos(motivos),
            "sem_brindes": bool(cache.sem_brindes),
            "avisos": self.calc.avisos() + avisos,
        }

    # --- nomes e Configurar -----------------------------------------------------------------
    def _nomes_produtos(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        nomes = dict(self.calc.cache.consulta(
            f"SELECT id, nome FROM produtos WHERE id IN ({','.join('?' * len(ids))})", list(ids)))
        return [{"id": p, "nome": nomes.get(p) or f"Produto {p}"} for p in ids]

    def _nomes_motivos(self, ids: list[int]) -> list[dict]:
        nomes = dict(self.calc.cache.consulta("SELECT id, nome FROM motivos"))
        return [{"id": m, "nome": nomes.get(m) or f"Motivo {m}"} for m in ids]

    def config_dados(self, mes: str | None = None) -> dict:
        """Para Configurar: as regras, o padrão, os motivos de devolução, os produtos vendidos no último ano (para
        escolher os de fora do mix) e as metas automáticas de faturamento e clientes de cada supervisor no mês."""
        self._conferir()
        i, meses = self._escolher_mes(mes)
        regras = self.calc.regras()
        cfg = self.config.atual()
        cache = self.calc.cache
        desde = (cache.data_ref().replace(day=1) - dt.timedelta(days=365)).replace(day=1)
        produtos = [{"id": p, "nome": n, "linha": li or "", "vendido_12m": round(v or 0, 2)}
                    for p, n, li, v in cache.consulta(
                        "SELECT p.id, p.nome, p.linha, SUM(v.valor) FROM vendas_itens v JOIN produtos p "
                        "ON p.id = v.id_produto WHERE v.data >= ? GROUP BY 1, 2, 3 ORDER BY 4 DESC", [desde])]
        citados = {p["id"] for p in produtos}
        produtos += [x for x in self._nomes_produtos(cfg["supervisores"]["produtos_fora_mix"]) if x["id"] not in citados]
        metas = self.metas_supervisores(regras, i, cfg)
        return {
            "config": cfg, "padrao": padrao(), "mes": _mes(i), "meses": [_mes(m) for m in meses],
            "motivos": [{"id": m, "nome": n} for m, n in sorted(cache.consulta("SELECT id, nome FROM motivos"))],
            "produtos": produtos,
            "automatico": {sid: {"fat": m["auto"]["fat"], "cli": m["auto"]["cli"]} for sid, m in metas.items()},
        }

"""Premiações (página Premiações): quanto cada vendedor e cada supervisor ganha no mês, como nas páginas "Premiacao
Vendedores" e "Premiacao Supervisores" do Power BI (ocultas lá). As regras ficam na tabela regras (nome "premiacoes"),
editáveis em Premiações › Configurar, e valem para todos os meses (mudar uma regra recalcula o histórico).

Vendedores (uma linha por vendedor com META CLIENTE > 0 no mês, da METAS.xlsx ou aprovada no painel):
- atendidos = clientes distintos com venda válida no mês, pelo vendedor da venda (a mesma conta da página de Metas);
- % = atendidos ÷ META CLIENTE; o prêmio é o da maior faixa atingida (padrão do Power BI: 91% → R$ 200, 96% → R$ 250,
  100% → R$ 350; abaixo de 91%, nada). O total é a soma dos prêmios (o Power BI aplicava a faixa ao % do total).

Supervisores (um por estado; a carteira é a de HOJE: os clientes cujo vendedor no cadastro é do estado pelas
Configurações das metas ou, sem configuração, pelo supervisor do ERP; terceiros, o Edir e contas internas ficam fora,
como nas listas fixas de nomes do Power BI). Só vendas, devoluções e brindes de tipo CLIENTE (o Power BI ligava venda a
funcionário ou fornecedor pelo código, que pode coincidir com o de um cliente). Cinco indicadores, com peso:
- receita: faturamento líquido do mês (vendas − devoluções não canceladas de todos os motivos − brindes) ÷ meta. Abaixo
  do mínimo (80%), nada; senão peso × alcance, no máximo o peso;
- mix: líquido sem os produtos "fora do mix" (32, 12551, 12552) ÷ líquido, sobre a meta (55%). Mínimo 85% de alcance;
- inadimplência: títulos de venda a cliente emitidos de 7 a 2 meses antes do mês (para outubro, março a agosto),
  vencidos há 30 dias ou mais na data dos dados e ainda em aberto, ÷ o faturamento líquido desses 6 meses. Dentro da
  meta (0,42% BA, 0,5% ES), o peso inteiro; acima, nada. A data é a de hoje, como no Power BI: o mês fechado muda quando
  um cliente paga depois;
- positivação: clientes distintos da carteira com venda no mês ÷ meta. Mínimo 80%;
- devoluções impróprias: devoluções e brindes com motivo impróprio (3, 4, 10 a 16) ÷ faturamento bruto. Dentro da meta
  (1,5%), o peso inteiro.
Prêmio = soma dos pontos × o máximo (R$ 5.000). As metas de faturamento e de clientes são a soma das metas dos
vendedores do estado no mês (no Power BI ficavam fixas, as de setembro/26); o administrador pode trocá-las num mês.
"""
from __future__ import annotations

import calendar
import datetime as dt
import math

from .configuracao import RegrasNoBanco
from .metas import Calculadora, nome_bonito
from .sugestao import curto_mes, indice, ler_mes, rotulo_mes, texto_mes

ESTADOS = ("BA", "ES")
ABAS = ("vendedores", "supervisores")
INDICADORES = ("receita", "mix", "inadimplencia", "positivacao", "devolucoes")
TITULOS = {"receita": "Faturamento líquido", "mix": "Mix", "inadimplencia": "Inadimplência",
           "positivacao": "Positivação", "devolucoes": "Devoluções impróprias"}
COM_MINIMO = ("receita", "mix", "positivacao")      # peso × alcance, a partir do mínimo
COM_TETO = ("inadimplencia", "devolucoes")           # o peso inteiro dentro da meta (% abaixo dela)
MAX_FAIXAS = 10
JANELA_DE, JANELA_ATE = 7, 2  # inadimplência: meses de emissão, contados para trás a partir do mês escolhido
_EPS = 1e-9


# --- regras da página -----------------------------------------------------------------------
def padrao() -> dict:
    """O que o Power BI fazia (medidas das páginas de premiação e da tabela "Medidas Premiacao Supervisor")."""
    return {
        "versao": 1,
        "vendedores": {"faixas": [{"min": 0.91, "valor": 200.0}, {"min": 0.96, "valor": 250.0},
                                  {"min": 1.0, "valor": 350.0}]},
        "supervisores": {
            "maximo": 5000.0,
            "nomes": {"BA": "Marcos", "ES": "Ronaldo"},
            "produtos_fora_mix": [32, 12551, 12552],
            "motivos_improprios": [3, 4, 10, 11, 12, 13, 14, 15, 16],
            "receita": {"peso": 0.25, "minimo": 0.80},
            "mix": {"peso": 0.15, "minimo": 0.85, "meta": {"BA": 0.55, "ES": 0.55}},
            "inadimplencia": {"peso": 0.10, "meta": {"BA": 0.0042, "ES": 0.005}, "dias": 30},
            "positivacao": {"peso": 0.25, "minimo": 0.80},
            "devolucoes": {"peso": 0.25, "meta": {"BA": 0.015, "ES": 0.015}},
            "ajustes": {},
        },
    }


def _numero(valor, nome: str, minimo: float = 0.0, maximo: float | None = None) -> float:
    try:
        x = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nome}: use um número") from None
    if math.isnan(x) or x < minimo or (maximo is not None and x > maximo):
        faixa = f"de {minimo:g} a {maximo:g}" if maximo is not None else f"a partir de {minimo:g}"
        raise ValueError(f"{nome}: use um valor {faixa}")
    return x


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
    sb = base["supervisores"]
    sup = {"maximo": round(_numero(sup_in.get("maximo", sb["maximo"]), "prêmio máximo do supervisor"), 2)}
    nomes = {}
    for e in ESTADOS:
        nome = " ".join(str((sup_in.get("nomes") or {}).get(e, sb["nomes"][e]) or "").split())
        if not nome or len(nome) > 60:
            raise ValueError(f"nome do supervisor do {e}: use de 1 a 60 letras")
        nomes[e] = nome
    sup["nomes"] = nomes
    sup["produtos_fora_mix"] = _inteiros(sup_in.get("produtos_fora_mix", sb["produtos_fora_mix"]), "produtos fora do mix")
    sup["motivos_improprios"] = _inteiros(sup_in.get("motivos_improprios", sb["motivos_improprios"]),
                                          "motivos das devoluções impróprias")
    for k in INDICADORES:
        ind_in, ind_b = sup_in.get(k) or {}, sb[k]
        ind = {"peso": _fracao(ind_in.get("peso", ind_b["peso"]), f"peso de {TITULOS[k].lower()}")}
        if "minimo" in ind_b:
            ind["minimo"] = _fracao(ind_in.get("minimo", ind_b["minimo"]), f"mínimo de {TITULOS[k].lower()}")
        if "meta" in ind_b:
            metas = ind_in.get("meta") or {}
            ind["meta"] = {e: _fracao(metas.get(e, ind_b["meta"][e]), f"meta de {TITULOS[k].lower()} do {e}")
                           for e in ESTADOS}
        if "dias" in ind_b:
            ind["dias"] = int(_numero(ind_in.get("dias", ind_b["dias"]), "dias de atraso da inadimplência", 0, 365))
        sup[k] = ind
    soma = sum(sup[k]["peso"] for k in INDICADORES)
    if abs(soma - 1) > 1e-6:
        raise ValueError(f"os pesos dos indicadores do supervisor somam {soma * 100:.4g}%; precisam somar 100%")
    ajustes = {}
    for mes, por_estado in (sup_in.get("ajustes") or {}).items():
        m = texto_mes(ler_mes(mes))
        lista = {}
        for e, v in (por_estado or {}).items():
            if e not in ESTADOS:
                raise ValueError(f"estado inválido nos ajustes de {m}: {e}")
            x = {}
            if (v or {}).get("fat") not in (None, ""):
                x["fat"] = round(_numero(v["fat"], f"meta de faturamento do {e} em {m}"), 2)
            if (v or {}).get("cli") not in (None, ""):
                n = _numero(v["cli"], f"meta de clientes do {e} em {m}")
                if n != int(n):
                    raise ValueError(f"meta de clientes do {e} em {m}: use um número inteiro")
                x["cli"] = int(n)
            if x:
                lista[e] = x
        if lista:
            ajustes[m] = lista
    sup["ajustes"] = dict(sorted(ajustes.items()))
    return {"versao": 1, "vendedores": {"faixas": faixas}, "supervisores": sup}


class ConfigPremiacoes(RegrasNoBanco):
    """Regras da página Premiações (tabela regras, nome "premiacoes")."""

    nome = "premiacoes"
    _valida = staticmethod(_valida)

    def _padrao(self) -> dict:
        return padrao()


# --- a conta (funções puras) ---------------------------------------------------------------
def _div(a: float, b: float) -> float | None:
    return a / b if b else None


def faixa_vendedor(pct: float | None, faixas: list[dict]) -> dict | None:
    """A maior faixa atingida (as faixas não se somam); None = nenhuma."""
    atingidas = [f for f in faixas if pct is not None and pct + _EPS >= f["min"]]
    return max(atingidas, key=lambda f: f["min"]) if atingidas else None


def proxima_faixa(pct: float | None, faixas: list[dict]) -> dict | None:
    acima = [f for f in faixas if pct is None or pct + _EPS < f["min"]]
    return min(acima, key=lambda f: f["min"]) if acima else None


def clientes_para(meta: float, minimo: float) -> int:
    """Quantos clientes atendidos chegam a `minimo` da meta."""
    return math.ceil(meta * minimo - _EPS)


def pontos_alcance(alcance: float | None, peso: float, minimo: float) -> float:
    """Receita, mix e positivação: abaixo do mínimo, nada; senão o peso × o alcance, no máximo o peso."""
    if alcance is None or alcance + _EPS < minimo:
        return 0.0
    return peso * min(alcance, 1.0)


def pontos_teto(pct: float | None, meta: float, peso: float) -> float:
    """Inadimplência e devoluções: o % até a meta ganha o peso inteiro; acima, nada (no Power BI, 2 − % ÷ meta ≥ 1)."""
    return peso if pct is not None and pct <= meta + _EPS else 0.0


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
            raise RuntimeError("os dados por cliente ainda não chegaram do computador da empresa; a premiação dos "
                               "supervisores aparece depois da próxima atualização")

    @staticmethod
    def estados_supervisor(permitidos: set[int] | None, equipes: set[str] | None) -> list[str]:
        """Os estados cuja premiação do supervisor o usuário vê: ela soma a carteira inteira do estado, então só quem
        vê todos os vendedores (sem lista de vendedores) e tem a equipe do estado."""
        if permitidos is not None:
            return []
        return [e for e in ESTADOS if equipes is None or e in equipes]

    def meses(self) -> list[int]:
        """Os meses com meta de clientes até o mês dos dados (do mais novo ao mais velho)."""
        cache = self.calc.cache
        ultimo = indice(cache.data_ref())
        primeiro = indice(dt.date.fromisoformat(cache.info.get("inicio") or "2024-01-01"))
        com_meta = {indice(m["mes"]) for m in self.calc.metas.dados() if (m.get("meta_cli") or 0) > 0}
        return sorted((i for i in com_meta if primeiro <= i <= ultimo), reverse=True)

    def _escolher_mes(self, mes: str | None) -> tuple[int, list[int]]:
        meses = self.meses()
        if not meses:
            raise ValueError("não há meses com meta de clientes na planilha de metas")
        if not mes:
            atual = indice(self.calc.cache.data_ref())
            return (atual if atual in meses else meses[0]), meses
        i = ler_mes(mes)
        if i not in meses:
            raise ValueError(f"escolha um mês com meta de clientes entre {curto_mes(meses[-1])} e {curto_mes(meses[0])}")
        return i, meses

    def _base(self, aba: str, i: int, meses: list[int], permitidos, equipes) -> dict:
        hoje = self.hoje()
        return {
            "aba": aba,
            "abas": ["vendedores", *(["supervisores"] if self.estados_supervisor(permitidos, equipes) else [])],
            "mes": _mes(i),
            "meses": [_mes(m) for m in meses],
            "situacao": "final" if hoje > _fim(i) else "prevista",
            "data_ref": self.calc.cache.data_ref().isoformat(),
            "hoje": hoje.isoformat(),
            "avisos": self.calc.avisos(),
        }

    def calcular(self, aba: str | None = None, mes: str | None = None, permitidos: set[int] | None = None,
                 equipes: set[str] | None = None) -> dict:
        """aba: vendedores ou supervisores (vazio = vendedores); mes: AAAA-MM (vazio = o mês dos dados).
        permitidos/equipes: o que o usuário vê (None = sem limite), como na página de Metas."""
        aba = aba or "vendedores"
        if aba not in ABAS:
            raise ValueError(f"aba desconhecida: {aba}")
        if aba == "supervisores":
            return self.supervisores(mes, permitidos, equipes)
        return self.vendedores(mes, permitidos, equipes)

    # --- vendedores --------------------------------------------------------------------------
    def vendedores(self, mes: str | None = None, permitidos: set[int] | None = None,
                   equipes: set[str] | None = None) -> dict:
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
            faixa = faixa_vendedor(pct, faixas)
            prox = proxima_faixa(pct, faixas)
            linhas.append({
                "id": vid, "nome": nome_bonito(x["nome"]), "equipe": x["grupo"],
                "estado": "ES" if x["grupo"] == "ES" else "BA", "aprovada": x["aprovada"],
                "meta": x["meta"], "atendidos": real, "pct": pct,
                "faixa": faixa, "premio": faixa["valor"] if faixa else 0.0,
                "proxima": {**prox, "faltam": max(clientes_para(x["meta"], prox["min"]) - real, 1)} if prox else None,
            })
        linhas.sort(key=lambda v: v["nome"].upper())
        meta_total = sum(v["meta"] for v in linhas)
        return {
            **self._base("vendedores", i, meses, permitidos, equipes),
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
        """Roda `sql` (com {ids} no lugar da lista de vendedores da carteira) e devolve as linhas."""
        if not ids:
            return []
        return self.calc.cache.consulta(sql.format(ids=",".join("?" * len(ids))), [*params, *ids])

    def _movimento(self, regras, ids: list[int], de: dt.date, ate: dt.date, fora_mix: set[int],
                   improprios: set[int]) -> dict[int, dict]:
        """Por vendedor da carteira: bruto, devoluções e brindes (o total, o que fica fora do mix e os impróprios)."""
        cache = self.calc.cache
        mov: dict[int, dict] = {}

        def x(vid):
            return mov.setdefault(vid, {"bruto": 0.0, "bruto_fora": 0.0, "dev": 0.0, "dev_fora": 0.0, "dev_imp": 0.0,
                                        "brindes": 0.0, "brindes_fora": 0.0, "brindes_imp": 0.0})

        junta = ("FROM {tabela} x JOIN clientes c ON c.id = x.id_cliente WHERE x.tipocliente = 'CLIENTE' "
                 "AND x.data BETWEEN ? AND ? AND c.id_vendedor IN ({{ids}})")
        for vid, pid, valor in self._por_vendedor(
                "SELECT c.id_vendedor, x.id_produto, SUM(x.valor) " + junta.format(tabela="vendas_clientes_itens")
                + " GROUP BY 1, 2", ids, [de, ate]):
            x(vid)["bruto"] += valor
            if regras.produto(pid) in fora_mix:
                x(vid)["bruto_fora"] += valor
        tabelas = [("dev", "devolucoes_clientes_itens", " AND NOT x.cancelada")]
        if not cache.sem_brindes:
            tabelas.append(("brindes", "brindes_clientes_itens", ""))
        for chave, tabela, extra in tabelas:
            for vid, pid, motivo, valor in self._por_vendedor(
                    "SELECT c.id_vendedor, x.id_produto, x.id_motivo, SUM(x.valor) " + junta.format(tabela=tabela)
                    + extra + " GROUP BY 1, 2, 3", ids, [de, ate]):
                x(vid)[chave] += valor
                if regras.produto(pid) in fora_mix:
                    x(vid)[chave + "_fora"] += valor
                if motivo in improprios:
                    x(vid)[chave + "_imp"] += valor
        return mov

    def _liquido(self, ids: list[int], de: dt.date, ate: dt.date) -> dict[int, float]:
        """Faturamento líquido por vendedor da carteira num período (a base da inadimplência)."""
        cache = self.calc.cache
        saida: dict[int, float] = {}
        junta = ("FROM {tabela} x JOIN clientes c ON c.id = x.id_cliente WHERE x.tipocliente = 'CLIENTE' "
                 "AND x.data BETWEEN ? AND ? AND c.id_vendedor IN ({{ids}})")
        partes = [("vendas_clientes_itens", "", 1), ("devolucoes_clientes_itens", " AND NOT x.cancelada", -1)]
        if not cache.sem_brindes:
            partes.append(("brindes_clientes_itens", "", -1))
        for tabela, extra, sinal in partes:
            for vid, valor in self._por_vendedor("SELECT c.id_vendedor, SUM(x.valor) " + junta.format(tabela=tabela)
                                                 + extra + " GROUP BY 1", ids, [de, ate]):
                saida[vid] = saida.get(vid, 0.0) + sinal * valor
        return saida

    def metas_supervisor(self, regras, i: int, cfg: dict | None = None) -> dict[str, dict]:
        """{estado: {"fat", "cli", "fat_auto", "cli_auto", "ajustada"}}: a soma das metas dos vendedores do estado no mês
        (o Edir é outro grupo: fica fora do BA) e o ajuste à mão do mês, se houver."""
        cfg = cfg or self.config.atual()
        m = _inicio(i)
        auto = {e: {"fat": 0.0, "cli": 0.0} for e in ESTADOS}
        for r in self.calc.metas.dados():
            if r["mes"] != m:
                continue
            estado = regras.grupo_vendedor(r["id_vendedor"])
            if estado in auto:
                auto[estado]["fat"] += r.get("meta_fat") or 0
                auto[estado]["cli"] += r.get("meta_cli") or 0
        ajustes = cfg["supervisores"]["ajustes"].get(texto_mes(i), {})
        saida = {}
        for e in ESTADOS:
            aj = ajustes.get(e, {})
            saida[e] = {"fat": aj.get("fat", auto[e]["fat"]), "cli": aj.get("cli", auto[e]["cli"]),
                        "fat_auto": auto[e]["fat"], "cli_auto": auto[e]["cli"],
                        "ajustada": {k: k in aj for k in ("fat", "cli")}}
        return saida

    def supervisores(self, mes: str | None = None, permitidos: set[int] | None = None,
                     equipes: set[str] | None = None) -> dict:
        estados = self.estados_supervisor(permitidos, equipes)
        if not estados:
            raise PermissionError("a premiação dos supervisores soma a carteira inteira do estado: seu acesso, limitado "
                                  "a alguns vendedores ou equipes, não a inclui")
        self._conferir(detalhe=True)
        cache = self.calc.cache
        i, meses = self._escolher_mes(mes)
        regras = self.calc.regras()
        cfg_total = self.config.atual()
        cfg = cfg_total["supervisores"]
        fora_mix = set(cfg["produtos_fora_mix"])
        fora_mix |= {antigo for antigo, novo in regras.equivalentes.items() if novo in fora_mix}
        improprios = set(cfg["motivos_improprios"])
        carteiras = self._carteiras(regras)
        ids = sorted(v for v, e in carteiras.items() if e in estados)
        de, ate = _inicio(i), _fim(i)
        j_de, j_ate = janela(i)
        hoje = self.hoje()
        corte = hoje - dt.timedelta(days=cfg["inadimplencia"]["dias"])

        mov = self._movimento(regras, ids, de, ate, fora_mix, improprios)
        positivados = dict(self._por_vendedor(
            "SELECT c.id_vendedor, COUNT(DISTINCT x.id_cliente) FROM vendas_clientes x JOIN clientes c "
            "ON c.id = x.id_cliente WHERE x.tipocliente = 'CLIENTE' AND x.data BETWEEN ? AND ? "
            "AND c.id_vendedor IN ({ids}) GROUP BY 1", ids, [de, ate]))
        liquido_6m = self._liquido(ids, _inicio(j_de), _fim(j_ate))
        inadimplente = {} if cache.sem_credito else dict(self._por_vendedor(
            "SELECT c.id_vendedor, SUM(t.total) FROM titulos_receber t JOIN clientes c ON c.id = t.id_cliente "
            "WHERE t.quitado = 0 AND t.vencimento <= ? AND t.emissao BETWEEN ? AND ? AND c.id_vendedor IN ({ids}) "
            "GROUP BY 1", ids, [corte, _inicio(j_de), _fim(j_ate)]))
        metas = self.metas_supervisor(regras, i, cfg_total)
        nomes = self.nomes()

        cartoes = []
        for e in estados:
            vids = [v for v in ids if carteiras[v] == e]
            soma = lambda k: sum(mov.get(v, {}).get(k, 0.0) for v in vids)  # noqa: E731
            bruto, dev, brindes = soma("bruto"), soma("dev"), soma("brindes")
            liquido = bruto - dev - brindes
            liquido_mix = (bruto - soma("bruto_fora")) - (dev - soma("dev_fora")) - (brindes - soma("brindes_fora"))
            improprias = soma("dev_imp") + soma("brindes_imp")
            liq6 = sum(liquido_6m.get(v, 0.0) for v in vids)
            inad = sum(inadimplente.get(v, 0.0) for v in vids)
            positivacao = sum(positivados.get(v, 0) for v in vids)
            meta = metas[e]
            pct_mix = _div(liquido_mix, liquido)
            pct_inad = None if cache.sem_credito else (_div(inad, liq6) if liq6 else (0.0 if not inad else None))
            pct_dev = _div(improprias, bruto) if bruto else (0.0 if not improprias else None)

            def alcance(k, realizado, alvo):
                ind = cfg[k]
                a = _div(realizado, alvo) if realizado is not None else None
                return {"id": k, "titulo": TITULOS[k], "realizado": realizado, "meta": alvo, "alcance": a,
                        "peso": ind["peso"], "minimo": ind["minimo"],
                        "pontos": pontos_alcance(a, ind["peso"], ind["minimo"])}

            def teto(k, realizado, alvo):
                ind = cfg[k]
                return {"id": k, "titulo": TITULOS[k], "realizado": realizado, "meta": alvo,
                        "dentro": realizado is not None and realizado <= alvo + _EPS, "peso": ind["peso"],
                        "pontos": pontos_teto(realizado, alvo, ind["peso"])}

            indicadores = [
                {**alcance("receita", liquido, meta["fat"]), "ajustada": meta["ajustada"]["fat"],
                 "meta_auto": meta["fat_auto"]},
                alcance("mix", pct_mix, cfg["mix"]["meta"][e]),
                {**teto("inadimplencia", pct_inad, cfg["inadimplencia"]["meta"][e]),
                 "sem_dados": bool(cache.sem_credito)},
                {**alcance("positivacao", positivacao, meta["cli"]), "ajustada": meta["ajustada"]["cli"],
                 "meta_auto": meta["cli_auto"]},
                teto("devolucoes", pct_dev, cfg["devolucoes"]["meta"][e]),
            ]
            pct = sum(x["pontos"] for x in indicadores)
            por_vendedor = []
            for v in vids:
                mv = mov.get(v, {})
                liq_v = mv.get("bruto", 0.0) - mv.get("dev", 0.0) - mv.get("brindes", 0.0)
                liq_mix_v = liq_v - (mv.get("bruto_fora", 0.0) - mv.get("dev_fora", 0.0) - mv.get("brindes_fora", 0.0))
                if not (mv or positivados.get(v) or inadimplente.get(v)):
                    continue
                por_vendedor.append({
                    "id": v, "nome": nomes.get(v) or f"Vendedor {v}", "liquido": liq_v, "pct_mix": _div(liq_mix_v, liq_v),
                    "positivacao": positivados.get(v, 0), "inadimplente": inadimplente.get(v, 0.0),
                    "liquido_6m": liquido_6m.get(v, 0.0), "improprias": mv.get("dev_imp", 0.0) + mv.get("brindes_imp", 0.0),
                    "bruto": mv.get("bruto", 0.0),
                })
            por_vendedor.sort(key=lambda r: -r["liquido"])
            cartoes.append({
                "estado": e, "nome": cfg["nomes"][e], "indicadores": indicadores,
                "pct": pct, "premio": round(pct * cfg["maximo"], 2),
                "contas": {"bruto": bruto, "devolucoes": dev, "brindes": brindes, "liquido": liquido,
                           "liquido_mix": liquido_mix, "improprias": improprias,
                           "improprias_devolucoes": soma("dev_imp"), "improprias_brindes": soma("brindes_imp"),
                           "liquido_6m": liq6, "inadimplente": inad},
                "vendedores": por_vendedor,
            })
        avisos = []
        if cache.sem_brindes:
            avisos.append("Os brindes ainda não chegaram do computador da empresa: o faturamento líquido e as devoluções "
                          "impróprias estão sem eles até a próxima atualização.")
        if cache.sem_credito:
            avisos.append("Os títulos a receber ainda não chegaram do computador da empresa: a inadimplência fica sem "
                          "dados (sem os pontos dela).")
        inicio = dt.date.fromisoformat(cache.info.get("inicio") or "2024-01-01")
        if _inicio(j_de) < inicio:
            avisos.append(f"A janela da inadimplência começa em {curto_mes(j_de)}, antes do início dos dados "
                          f"({inicio.strftime('%m/%Y')}): o faturamento dos 6 meses fica menor que o real.")
        return {
            **self._base("supervisores", i, meses, permitidos, equipes),
            "supervisores": cartoes,
            "maximo": cfg["maximo"],
            "janela": {"de": texto_mes(j_de), "ate": texto_mes(j_ate), "rotulo": f"{curto_mes(j_de)} a {curto_mes(j_ate)}"},
            "corte_vencimento": corte.isoformat(),
            "dias_atraso": cfg["inadimplencia"]["dias"],
            "produtos_fora_mix": self._nomes_produtos(cfg["produtos_fora_mix"]),
            "motivos_improprios": self._nomes_motivos(cfg["motivos_improprios"]),
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
        escolher os de fora do mix) e as metas automáticas dos supervisores no mês escolhido."""
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
        metas = self.metas_supervisor(regras, i, cfg)
        return {
            "config": cfg, "padrao": padrao(), "mes": _mes(i), "meses": [_mes(m) for m in meses],
            "motivos": [{"id": m, "nome": n} for m, n in sorted(cache.consulta("SELECT id, nome FROM motivos"))],
            "produtos": produtos,
            "automatico": {e: {"fat": metas[e]["fat_auto"], "cli": metas[e]["cli_auto"]} for e in ESTADOS},
        }

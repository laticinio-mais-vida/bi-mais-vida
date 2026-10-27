"""Sugestão de Metas (página Sugestão de Metas): a meta do mês seguinte de cada vendedor, por produto, como nas páginas
"Sugestão de Meta BA", "Sugestão de Meta ES" e "Duplicata de Sugestão de Meta BA" do Power BI.

A conta, por linha (BA: vendedor × área × produto; ES: vendedor × produto, como no Power BI):
- volume do mês base = vendas válidas − devoluções que descontam (regras de Metas: motivos, canceladas e equivalências),
  dos clientes que estão HOJE na carteira do vendedor: o cliente repassado leva o histórico para o vendedor novo, como
  nas Projeções; a área é a área atual do cliente. Venda a funcionário, fornecedor ou produtor fica fora (não tem
  carteira), e os produtos marcados como "não conta" também;
- por faturamento = volume do mês base ÷ faturamentos do mês base (BA: os da área; ES: os dias úteis do ES);
- sazonalidade = (volume do mês da meta no ano passado ÷ faturamentos dele) ÷ (volume do mês base no ano passado ÷
  faturamentos dele). Sem venda (ou ≤ 0) = 1; teto de +20%; abaixo de 1 fica (reduz a meta);
- crescimento proposto = 1 + 12% − (acumulado do ano até o mês base ÷ mesmo período do ano passado − 1), entre 0% e
  +20%. Sem venda no acumulado do ano passado = 0%;
- meta (volume) = por faturamento × sazonalidade × faturamentos do mês da meta × crescimento proposto;
- preço médio = faturamento bruto do mês base ÷ volume vendido nele, sem descontar devoluções (decisão de 27/10/2026;
  o Power BI usava o líquido de todas as devoluções e dos brindes);
- meta (R$) = meta (volume) × preço médio. O total de um vendedor é a soma das linhas, e "todos" é a soma dos vendedores.

Faturamentos do BA: cada dia de atendimento da área (Gestão › Configurar) é faturado no dia útil seguinte do calendário do
BA (sexta e sábado → segunda; feriado empurra para o próximo; atendimento em feriado conta, como nas vendas de set/26),
e conta quantos caem no mês. Algumas áreas faturam mais tarde (Eunápolis: atendida na segunda, faturada na quarta): o
prazo, em dias úteis, é por área. Bate com a planilha "Quantidades Faturamentos.xlsx" do Power BI em 120 de 140
células; o resto eram ajustes à mão dela, que as vendas mostraram errados em parte. As áreas quinzenais têm número
fixo e qualquer área pode ser ajustada num mês (regras da página, tabela regras com nome "sugestao"). Área sem dia (e
sem número fixo) fica fora, como no Power BI (que deixava fora as áreas ausentes da planilha), e a página avisa quanto
ficou fora.

Vendedores: os do estado (grupos das Configurações das metas; o BA inclui o Edir) que têm meta na METAS.xlsx no mês da
meta ou nos dois anteriores e clientes na carteira, como as listas fixas de nomes das páginas do Power BI (sem isso, as
contas internas ainda não configuradas, que caem no ES, entravam).

O acumulado do ano vai até o mês base (no Power BI ia até o último mês fechado pela data de hoje, o mesmo resultado no
uso normal; em janeiro o Power BI dava +20% para todos, porque o ano atual vinha vazio).
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import re
import threading
from collections import defaultdict

from .configuracao import RegrasNoBanco
from .metas import MESES, Calculadora

ESTADOS = ("ES", "BA")
GRUPOS = {"ES": ("ES",), "BA": ("BA", "EDIR")}
# Quinzenais da planilha "Quantidades Faturamentos.xlsx" do Power BI (2 em todo mês): Itamaraju, Teixeira, Itabatã e
# Posto da Mata.
FIXOS_PBI = {"45": 2, "69": 2, "219": 2, "237": 2, "261": 2, "283": 2, "291": 2, "387": 2, "389": 2}
# Áreas que faturam mais de um dia útil depois do atendimento, pelas vendas de abr–out/2026: Eunápolis (segunda) e
# Eunápolis (terça), atendidas na segunda (dias de Gestão › Configurar) e faturadas na quarta em 93% dos clientes.
PRAZOS_VENDAS = {"207": 2, "209": 2}
MAX_PRAZO = 5
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MAX_FATURAMENTOS = 31
MAX_PRODUTOS_IA = 40
_MES = re.compile(r"^(\d{4})-(\d{2})$")


# --- meses (índice = ano × 12 + mês − 1) ---------------------------------------------------
def indice(d: dt.date) -> int:
    return d.year * 12 + d.month - 1


def ler_mes(texto: str) -> int:
    """'2026-11' -> índice do mês."""
    m = _MES.match(str(texto or "").strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"mês inválido: {texto!r} (use AAAA-MM)")
    return int(m.group(1)) * 12 + int(m.group(2)) - 1


def texto_mes(i: int) -> str:
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def rotulo_mes(i: int) -> str:
    return f"{MESES[i % 12]} de {i // 12}"


def curto_mes(i: int) -> str:
    return f"{MESES[i % 12][:3]}/{str(i // 12)[2:]}"


def _fim(i: int) -> dt.date:
    a, m = i // 12, i % 12 + 1
    return dt.date(a, m, calendar.monthrange(a, m)[1])


# --- regras da página -----------------------------------------------------------------------
def padrao() -> dict:
    """O que o Power BI fazia: 12% de crescimento no ano, tetos de 20% e as áreas quinzenais da planilha; e os prazos de
    faturamento que as vendas mostram."""
    return {"versao": 1, "crescimento": {"ES": 0.12, "BA": 0.12}, "teto_sazonalidade": 0.2, "teto_crescimento": 0.2,
            "fixos": dict(FIXOS_PBI), "prazos": dict(PRAZOS_VENDAS), "ajustes": {}}


def _fracao(valor, nome: str) -> float:
    try:
        x = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nome}: use um número") from None
    if not 0 <= x <= 1:
        raise ValueError(f"{nome}: use um valor entre 0% e 100%")
    return round(x, 6)


def _area(valor) -> str:
    try:
        return str(int(valor))
    except (TypeError, ValueError):
        raise ValueError(f"código de área inválido: {valor!r}") from None


def _quantidade(valor, nome: str, minimo: int) -> int:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nome}: use um número inteiro") from None
    if n != int(n) or not minimo <= n <= MAX_FATURAMENTOS:
        raise ValueError(f"{nome}: use um número inteiro de {minimo} a {MAX_FATURAMENTOS}")
    return int(n)


def _por_area(d: dict) -> dict:
    return dict(sorted(d.items(), key=lambda kv: int(kv[0])))


def _valida(cfg: dict) -> dict:
    """Confere e normaliza as regras vindas da página; levanta ValueError com a explicação."""
    base = padrao()
    cre = cfg.get("crescimento") or {}
    saida = {
        "versao": 1,
        "crescimento": {e: _fracao(cre.get(e, base["crescimento"][e]), f"crescimento desejado do {e}") for e in ESTADOS},
        "teto_sazonalidade": _fracao(cfg.get("teto_sazonalidade", base["teto_sazonalidade"]), "teto da sazonalidade"),
        "teto_crescimento": _fracao(cfg.get("teto_crescimento", base["teto_crescimento"]),
                                    "teto do crescimento proposto"),
    }
    fixos = {}
    for a, n in (cfg.get("fixos") or {}).items():
        fixos[_area(a)] = _quantidade(n, f"faturamentos fixos da área {a}", 1)
    saida["fixos"] = _por_area(fixos)
    prazos = {}
    for a, n in (cfg.get("prazos") or {}).items():
        try:
            dias = int(n)
        except (TypeError, ValueError):
            raise ValueError(f"prazo do faturamento da área {a}: use um número inteiro") from None
        if dias != float(n) or not 1 <= dias <= MAX_PRAZO:
            raise ValueError(f"prazo do faturamento da área {a}: use de 1 a {MAX_PRAZO} dias úteis")
        if dias != 1:  # 1 é o padrão: não precisa guardar
            prazos[_area(a)] = dias
    saida["prazos"] = _por_area(prazos)
    ajustes = {}
    for mes, por_area in (cfg.get("ajustes") or {}).items():
        m = texto_mes(ler_mes(mes))
        lista = {_area(a): _quantidade(n, f"faturamentos da área {a} em {m}", 0) for a, n in (por_area or {}).items()}
        if lista:
            ajustes[m] = _por_area(lista)
    saida["ajustes"] = dict(sorted(ajustes.items()))
    return saida


class ConfigSugestao(RegrasNoBanco):
    """Regras da página Sugestão de Metas (tabela regras, nome "sugestao"): crescimento desejado por estado, tetos,
    áreas com número fixo de faturamentos e os ajustes à mão por área e mês ({"2026-09": {"166": 4}})."""

    nome = "sugestao"
    _valida = staticmethod(_valida)

    def _padrao(self) -> dict:
        return padrao()


# --- a conta (funções puras) ---------------------------------------------------------------
def dia_do_faturamento(cal, dia: dt.date, regiao: str, prazo: int = 1) -> dt.date:
    """O prazo-ésimo dia útil depois do atendimento (1 = o dia útil seguinte)."""
    x = dia
    for _ in range(prazo):
        x += dt.timedelta(days=1)
        for _ in range(15):
            if cal.dia(x, regiao)["peso"] > 0:
                break
            x += dt.timedelta(days=1)
    return x


def faturamentos_do_mes(cal, dias: list[int], ano: int, mes: int, regiao: str = "BA", prazo: int = 1) -> int:
    """Quantos faturamentos de uma área caem no mês: cada dia de atendimento (dias ISO, 1 = segunda) é faturado `prazo`
    dias úteis depois, no calendário (prazo 1: sexta e sábado → segunda; feriado empurra para o próximo)."""
    inicio = dt.date(ano, mes, 1)
    fim = inicio.replace(day=calendar.monthrange(ano, mes)[1])
    n, d = 0, inicio - dt.timedelta(days=7 + 3 * prazo)
    while d <= fim:
        if d.isoweekday() in dias and inicio <= dia_do_faturamento(cal, d, regiao, prazo) <= fim:
            n += 1
        d += dt.timedelta(days=1)
    return n


def sazonalidade(vol_base_ly: float, vol_meta_ly: float, fat_base_ly, fat_meta_ly, teto: float) -> tuple:
    """(variação calculada, fator usado): o ritmo do mês da meta sobre o do mês base, no ano passado, por faturamento.
    Sem venda (ou sem faturamento) no ano passado, ou variação ≤ 0: 1. Teto de 1 + teto; abaixo de 1 fica."""
    if not fat_base_ly or not fat_meta_ly:
        return None, 1.0
    ritmo_base = vol_base_ly / fat_base_ly
    if ritmo_base <= 0:
        return None, 1.0
    bruta = (vol_meta_ly / fat_meta_ly) / ritmo_base
    return bruta, (1.0 if bruta <= 0 else min(bruta, 1 + teto))


def crescimento_proposto(acum: float, acum_ly: float, alvo: float, teto: float) -> tuple:
    """(acumulado do ano ÷ mesmo período do ano passado, fator usado): o que falta para o crescimento desejado no ano,
    entre 1 e 1 + teto. Sem venda no acumulado do ano passado: 1."""
    if acum_ly <= 0:
        return None, 1.0
    razao = acum / acum_ly
    return razao, min(max(1 + alvo - (razao - 1), 1.0), 1 + teto)


class _Soma:
    """Junta linhas da conta (produto de vários vendedores, área, vendedor, total) para a tela."""

    def __init__(self, peso: str):
        self.peso_por = peso  # "vb" (mesmo produto: pelo volume) ou "base_rs" (produtos diferentes: pelo valor)
        self.vb = self.meta = self.base_rs = self.meta_rs = self.bruto = self.qv = self.ya = self.yp = 0.0
        self.p_saz = self.p_cre = self.p_fat = self.peso = 0.0
        self.n = 0
        self.ultima = None
        self.fats: set = set()

    def somar(self, ln: dict) -> None:
        for k in ("vb", "meta", "base_rs", "meta_rs", "bruto", "qv", "ya", "yp"):
            setattr(self, k, getattr(self, k) + ln[k])
        w = max(ln[self.peso_por], 0.0)
        self.p_saz += w * ln["saz"]
        self.p_cre += w * ln["cre"]
        self.p_fat += w * (ln["ft"] / ln["fb"])
        self.peso += w
        self.n += 1
        self.ultima = ln
        self.fats.add((ln["fb"], ln["ft"]))

    def saida(self) -> dict:
        ln, exata = self.ultima, self.n == 1
        media = (lambda x: x / self.peso - 1) if self.peso else (lambda x: None)
        fb, ft = next(iter(self.fats)) if len(self.fats) == 1 else (None, None)
        return {
            "volume_base": self.vb, "meta_volume": self.meta, "base_rs": self.base_rs, "meta_rs": self.meta_rs,
            "preco": self.bruto / self.qv if self.qv > 0 else None,
            "variacao": self.meta / self.vb - 1 if self.vb > 0 else None,
            "crescimento_total": self.meta_rs / self.base_rs - 1 if self.base_rs > 0 else None,
            "sazonalidade": ln["saz"] - 1 if exata else media(self.p_saz),
            "sazonalidade_calculada": ln["saz_bruta"] - 1 if exata and ln["saz_bruta"] is not None else None,
            "acumulado": self.ya / self.yp - 1 if self.yp > 0 else None,
            "crescimento": ln["cre"] - 1 if exata else media(self.p_cre),
            "efeito_faturamentos": media(self.p_fat),
            "faturamentos": {"base": fb, "meta": ft} if fb is not None else None,
            "exata": exata,
        }


# --- a página --------------------------------------------------------------------------------
class Sugestao:
    def __init__(self, calc: Calculadora, config, areas, nomes):
        """config: ConfigSugestao (ou algo com atual()). areas: função que devolve os dias de atendimento das áreas
        ({id_area: [dias ISO]}, bi/gestao.py). nomes: função com {id_vendedor: nome} (o da planilha de metas mais
        recente, senão o do ERP)."""
        self.calc = calc
        self.config = config
        self.areas = areas
        self.nomes = nomes
        self._trava = threading.Lock()
        self._memo: tuple = (None, None)

    # --- dados -----------------------------------------------------------------------------
    def _conferir(self) -> None:
        cache = self.calc.cache
        if not cache.pronto():
            raise RuntimeError("os dados ainda estão sendo preparados")
        if cache.antigo or cache.sem_detalhe:
            raise RuntimeError("os dados por cliente ainda não chegaram do computador da empresa; a sugestão aparece "
                               "depois da próxima atualização")

    def _dados(self, regras) -> dict:
        """O movimento do cache inteiro ({vendedor do cliente: {(área, produto): {mês: [volume líquido, faturamento
        bruto, volume vendido]}}}), as carteiras e os nomes; guardado até o cache ou as regras mudarem."""
        cache = self.calc.cache
        chave = (cache.info.get("extraido_em"), cache.info.get("data_ref"), json.dumps(regras.cfg, sort_keys=True))
        with self._trava:
            if self._memo[0] == chave:
                return self._memo[1]
        motivos = sorted(regras.motivos) or [-1]
        canceladas = " AND NOT cancelada" if regras.ignorar_canceladas else ""
        linhas = cache.consulta(f"""
            SELECT c.id_vendedor, COALESCE(d.id_area, 0), m.id_produto, year(m.data) * 12 + month(m.data) - 1,
                   SUM(m.q), SUM(m.bruto), SUM(m.qv)
            FROM (SELECT data, id_cliente, id_produto, quantidade AS q, valor AS bruto, quantidade AS qv
                  FROM vendas_clientes_itens WHERE tipocliente = 'CLIENTE'
                  UNION ALL
                  SELECT data, id_cliente, id_produto, -quantidade, 0, 0 FROM devolucoes_clientes_itens
                  WHERE tipocliente = 'CLIENTE' AND id_motivo IN ({",".join("?" * len(motivos))}){canceladas}) m
            JOIN clientes c ON c.id = m.id_cliente AND c.id_vendedor > 0
            LEFT JOIN clientes_detalhes d ON d.id = c.id
            GROUP BY ALL""", motivos)
        mov: dict = {}
        for v, a, p, i, q, b, qv in linhas:
            p = regras.produto(p)
            if regras.grupo_produto(p) == "fora":
                continue
            x = mov.setdefault(v, {}).setdefault((a, p), {}).setdefault(i, [0.0, 0.0, 0.0])
            x[0] += q
            x[1] += b
            x[2] += qv
        dados = {
            "mov": mov,
            "carteira": dict(cache.consulta("SELECT id_vendedor, COUNT(*) FROM clientes WHERE id_vendedor > 0 GROUP BY 1")),
            "clientes_area": {(v, a): n for v, a, n in cache.consulta(
                "SELECT c.id_vendedor, d.id_area, COUNT(*) FROM clientes c JOIN clientes_detalhes d ON d.id = c.id "
                "WHERE c.id_vendedor > 0 AND d.id_area IS NOT NULL GROUP BY 1, 2")},
            "nomes_areas": dict(cache.consulta(
                "SELECT id_area, any_value(area) FROM clientes_detalhes WHERE id_area IS NOT NULL GROUP BY 1")),
            "produtos": {p: (n, u) for p, n, u in cache.consulta("SELECT id, nome, unidade FROM produtos")},
        }
        with self._trava:
            self._memo = (chave, dados)
        return dados

    def _vendedores(self, d: dict, regras, estado: str, permitidos, equipes, i_meta: int) -> list[int]:
        """Vendedores do estado com meta na METAS.xlsx no mês da meta ou nos dois anteriores e clientes na carteira,
        dentro do acesso."""
        com_meta = {m["id_vendedor"] for m in self.calc.metas.dados() if i_meta - 2 <= indice(m["mes"]) <= i_meta}
        return sorted(v for v in d["carteira"]
                      if v in com_meta and regras.grupo_vendedor(v) in GRUPOS[estado]
                      and (equipes is None or regras.grupo_vendedor(v) in equipes)
                      and (permitidos is None or v in permitidos))

    def _contexto(self, regras, estado: str) -> dict:
        """O que uma conta usa: as regras da página, o calendário, os dias das áreas e as contagens já feitas."""
        cfg = self.config.atual()
        return {"cfg": cfg, "cal": self.calc.calendario(regras), "estado": estado,
                "dias": self.areas() if estado == "BA" else {}, "memo": {},
                "alvo": cfg["crescimento"][estado], "teto_saz": cfg["teto_sazonalidade"],
                "teto_cre": cfg["teto_crescimento"]}

    @staticmethod
    def _faturamentos(k: dict, area: int | None, i: int) -> tuple[int | None, str | None]:
        """(faturamentos, origem) de uma área num mês: o ajuste do mês, o número fixo, ou a conta pelos dias de
        atendimento; (None, None) = área sem dia. No ES (area None), os dias úteis do mês."""
        chave = (area, i)
        if chave in k["memo"]:
            return k["memo"][chave]
        if area is None:
            dias = sum(x["peso"] for x in k["cal"].dias_do_mes(i // 12, i % 12 + 1, k["estado"]))
            r = (dias, "dias_uteis")
        else:
            cfg = k["cfg"]
            ajuste = cfg["ajustes"].get(texto_mes(i), {}).get(str(area))
            if ajuste is not None:
                r = (ajuste, "ajuste")
            elif str(area) in cfg["fixos"]:
                r = (cfg["fixos"][str(area)], "fixo")
            elif k["dias"].get(area):
                r = (faturamentos_do_mes(k["cal"], k["dias"][area], i // 12, i % 12 + 1, "BA",
                                         cfg["prazos"].get(str(area), 1)), "automatico")
            else:
                r = (None, None)
        k["memo"][chave] = r
        return r

    def _linhas(self, d: dict, k: dict, vendedores: list[int], area: int | None, i_meta: int) -> tuple[list, dict]:
        """As linhas no grão da conta (BA: vendedor × área × produto; ES: vendedor × produto) com volume no mês base, e
        o que ficou fora no BA por área sem faturamento ({área: R$ do mês base})."""
        ib, iml = i_meta - 1, i_meta - 12
        ibl = ib - 12
        jan = ib - ib % 12
        es = k["estado"] == "ES"
        linhas, fora = [], defaultdict(float)
        for v in vendedores:
            grupos = d["mov"].get(v, {})
            if es:  # no ES a conta é por produto: junta as áreas (só a escolhida, com filtro)
                juntos: dict = {}
                for (a, p), meses in grupos.items():
                    if area is not None and a != area:
                        continue
                    alvo = juntos.setdefault((None, p), {})
                    for i, x in meses.items():
                        y = alvo.setdefault(i, [0.0, 0.0, 0.0])
                        y[0] += x[0]
                        y[1] += x[1]
                        y[2] += x[2]
                itens = juntos.items()
            else:
                itens = [(ap, m) for ap, m in grupos.items() if area is None or ap[0] == area]
            for (a, p), meses in itens:
                base = meses.get(ib)
                if not base or base[0] <= 0:
                    continue
                vb, bruto, qv = base
                preco = bruto / qv if qv > 0 else 0.0
                fb, ft, fbl, ftl = (self._faturamentos(k, a, i)[0] for i in (ib, i_meta, ibl, iml))
                if not fb:  # área sem dia de atendimento (ou sem faturamento no mês base): fica fora
                    fora[a] += vb * preco
                    continue
                vol = lambda i: meses[i][0] if i in meses else 0.0  # noqa: E731
                vly, vly1 = vol(ibl), vol(iml)
                ya = sum(vol(i) for i in range(jan, ib + 1))
                yp = sum(vol(i) for i in range(jan - 12, ibl + 1))
                saz_bruta, saz = sazonalidade(vly, vly1, fbl, ftl, k["teto_saz"])
                acum, cre = crescimento_proposto(ya, yp, k["alvo"], k["teto_cre"])
                meta = vb / fb * saz * (ft or 0) * cre
                linhas.append({"v": v, "a": a, "p": p, "vb": vb, "vly": vly, "vly1": vly1, "ya": ya, "yp": yp,
                               "bruto": bruto, "qv": qv, "fb": fb, "ft": ft or 0, "fbl": fbl, "ftl": ftl,
                               "saz_bruta": saz_bruta, "saz": saz, "acum": acum, "cre": cre, "meta": meta,
                               "preco": preco, "base_rs": vb * preco, "meta_rs": meta * preco})
        return linhas, dict(fora)

    # --- a página -----------------------------------------------------------------------------
    def meses_possiveis(self) -> tuple[int, int]:
        """(primeiro, último) mês da meta: o mês base precisa do mesmo mês no ano anterior dentro do cache, e o último
        é o mês seguinte ao dos dados."""
        cache = self.calc.cache
        inicio = dt.date.fromisoformat(cache.info.get("inicio") or "2024-01-01")
        return indice(inicio) + 13, indice(cache.data_ref()) + 1

    def calcular(self, estado: str | None = None, mes: str | None = None, vendedor=None, area=None,
                 permitidos: set[int] | None = None, equipes: set[str] | None = None) -> dict:
        """estado: ES ou BA (vazio = o primeiro do acesso); mes: o mês da meta, AAAA-MM (vazio = o mês dos dados);
        vendedor/area: filtros (vazio = todos). permitidos/equipes: o que o usuário vê (None = sem limite)."""
        self._conferir()
        regras = self.calc.regras()
        d = self._dados(regras)
        cache = self.calc.cache
        data_ref = cache.data_ref()
        primeiro, ultimo = self.meses_possiveis()
        i_meta = ler_mes(mes) if mes else indice(data_ref)
        if not primeiro <= i_meta <= ultimo:
            raise ValueError(f"escolha um mês da meta entre {curto_mes(primeiro)} e {curto_mes(ultimo)}")
        ib = i_meta - 1
        estados = [e for e in ESTADOS if self._vendedores(d, regras, e, permitidos, equipes, i_meta)]
        if not estados:
            raise PermissionError("seu acesso não inclui vendedores do ES nem do BA com meta na planilha; fale com o "
                                  "administrador")
        estado = (estado or estados[0]).upper()
        if estado not in ESTADOS:
            raise ValueError(f"estado inválido: {estado}")
        if estado not in estados:
            raise PermissionError(f"seu acesso não inclui vendedores do {estado}")
        todos = self._vendedores(d, regras, estado, permitidos, equipes, i_meta)
        nomes = self.nomes()
        nome = lambda v: nomes.get(v) or f"Vendedor {v}"  # noqa: E731
        vendedor = int(vendedor) if vendedor not in (None, "") else None
        if vendedor is not None and vendedor not in todos:
            raise ValueError(f"o vendedor {vendedor} não está entre os vendedores do {estado} do seu acesso")
        area = int(area) if area not in (None, "") else None
        escolhidos = [vendedor] if vendedor is not None else todos
        k = self._contexto(regras, estado)
        linhas, fora = self._linhas(d, k, escolhidos, area, i_meta)

        total = _Soma("base_rs")
        produtos: dict[int, _Soma] = defaultdict(lambda: _Soma("vb"))
        por_area: dict[int, _Soma] = defaultdict(lambda: _Soma("base_rs"))
        area_prod: dict[tuple, _Soma] = defaultdict(lambda: _Soma("vb"))
        for ln in linhas:
            total.somar(ln)
            produtos[ln["p"]].somar(ln)
            if estado == "BA":
                por_area[ln["a"]].somar(ln)
                area_prod[(ln["a"], ln["p"])].somar(ln)
        produto = lambda p: {"id": p, "nome": d["produtos"].get(p, (f"Produto {p}", ""))[0],  # noqa: E731
                             "unidade": d["produtos"].get(p, ("", ""))[1] or ""}
        nome_area = lambda a: d["nomes_areas"].get(a) or ("Sem área" if not a else f"Área {a}")  # noqa: E731
        ordem = lambda s: -s.meta_rs  # noqa: E731
        tabela = [{**produto(p), **s.saida()} for p, s in sorted(produtos.items(), key=lambda x: ordem(x[1]))]
        areas = []
        if estado == "BA":
            for a, s in sorted(por_area.items(), key=lambda x: ordem(x[1])):
                filhos = sorted(((p, x) for (aa, p), x in area_prod.items() if aa == a), key=lambda x: ordem(x[1]))
                origem = {texto_mes(i): self._faturamentos(k, a, i)[1] for i in (ib, i_meta)}
                areas.append({"id": a, "nome": nome_area(a), **s.saida(), "origem": origem,
                              "produtos": [{**produto(p), **x.saida()} for p, x in filhos]})

        # Resumo: todos os vendedores do estado do acesso, sem os filtros de vendedor e área, com a meta da METAS.xlsx.
        linhas_resumo = linhas if (vendedor is None and area is None) else self._linhas(d, k, todos, None, i_meta)[0]
        por_vendedor: dict[int, _Soma] = defaultdict(lambda: _Soma("base_rs"))
        for ln in linhas_resumo:
            por_vendedor[ln["v"]].somar(ln)
        mes_meta = dt.date(i_meta // 12, i_meta % 12 + 1, 1)
        lancadas: dict[int, float] = defaultdict(float)
        for m in self.calc.metas.dados():
            if m["mes"] == mes_meta and m["id_vendedor"] in todos:
                lancadas[m["id_vendedor"]] += m["meta_fat"]
        resumo = []
        for v in todos:
            s = por_vendedor.get(v)
            meta_rs = s.meta_rs if s else 0.0
            resumo.append({"id": v, "nome": nome(v), "equipe": regras.grupo_vendedor(v),
                           "base_rs": s.base_rs if s else 0.0, "meta_rs": meta_rs,
                           "crescimento": (meta_rs / s.base_rs - 1) if s and s.base_rs > 0 else None,
                           "meta_lancada": lancadas.get(v), "diferenca": (lancadas[v] - meta_rs) if v in lancadas else None})
        resumo.sort(key=lambda r: (-r["meta_rs"], r["nome"]))

        avisos = list(self.calc.avisos())
        if data_ref < _fim(ib):
            avisos.append(f"O mês base ({rotulo_mes(ib)}) ainda não fechou: a sugestão usa só as vendas até "
                          f"{data_ref:%d/%m/%Y} e fica abaixo do que seria com o mês inteiro.")
        fora_info = None
        if fora:
            clientes = sum(d["clientes_area"].get((v, a), 0) for v in escolhidos for a in fora)
            nomes_fora = sorted(nome_area(a) for a in fora)
            fora_info = {"base_rs": sum(fora.values()), "clientes": clientes,
                         "areas": [{"id": a, "nome": nome_area(a), "base_rs": r} for a, r in
                                   sorted(fora.items(), key=lambda x: -x[1])]}
            lista = ", ".join(nomes_fora[:3]) + (f" e mais {len(nomes_fora) - 3}" if len(nomes_fora) > 3 else "")
            valor = f"{sum(fora.values()):,.0f}".replace(",", ".")
            avisos.append(f"{len(fora)} área{'s' if len(fora) > 1 else ''} sem dia de atendimento "
                          f"{'ficaram' if len(fora) > 1 else 'ficou'} fora da sugestão ({lista}): {clientes} "
                          f"cliente{'s' if clientes != 1 else ''} da carteira e R$ {valor} no mês base. Marque os dias "
                          "em Gestão › Configurar.")

        areas_opcao = sorted({a for (v, a) in d["clientes_area"] if v in escolhidos}, key=nome_area)
        return {
            "estado": estado,
            "estados": estados,
            "data_ref": data_ref.isoformat(),
            "mes": {"meta": texto_mes(i_meta), "base": texto_mes(ib), "rotulo_meta": rotulo_mes(i_meta),
                    "rotulo_base": rotulo_mes(ib), "curto_meta": curto_mes(i_meta), "curto_base": curto_mes(ib),
                    "base_fechado": data_ref >= _fim(ib)},
            "filtros": {"vendedor": vendedor, "area": area},
            "opcoes": {
                "vendedores": [{"id": v, "nome": nome(v), "equipe": regras.grupo_vendedor(v)} for v in todos],
                "areas": [{"id": a, "nome": nome_area(a)} for a in areas_opcao],
                "meses": [{"valor": texto_mes(i), "rotulo": rotulo_mes(i)} for i in range(ultimo, primeiro - 1, -1)],
            },
            "cartoes": total.saida() if linhas else None,
            "dias": ({"base": self._faturamentos(k, None, ib)[0], "meta": self._faturamentos(k, None, i_meta)[0]}
                     if estado == "ES" else None),
            "produtos": tabela,
            "areas": areas,
            "grafico": self._grafico(d, k, escolhidos, area, ib, {r["id"] for r in tabela}),
            "resumo": resumo,
            "fora": fora_info,
            "avisos": avisos,
            "parametros": self._parametros(k, i_meta),
        }

    def _grafico(self, d: dict, k: dict, vendedores: list[int], area, ib: int, produtos: set[int]) -> dict:
        """Volume de cada mês do ano do mês base e do ano anterior (total e por produto da tabela) e a sazonalidade de
        cada mês para o seguinte, no ano anterior, por dia útil do estado (sem o teto)."""
        jan = ib - ib % 12
        inicio, ultimo = jan - 12, indice(self.calc.cache.data_ref())
        series: dict = defaultdict(lambda: [0.0] * 25)  # jan do ano anterior até jan do ano seguinte
        for v in vendedores:
            for (a, p), meses in d["mov"].get(v, {}).items():
                if area is not None and a != area:
                    continue
                for i, x in meses.items():
                    if inicio <= i <= inicio + 24:
                        series["total"][i - inicio] += x[0]
                        if p in produtos:
                            series[p][i - inicio] += x[0]
        regiao = k["estado"]
        dias = [sum(x["peso"] for x in k["cal"].dias_do_mes(i // 12, i % 12 + 1, regiao)) for i in range(inicio, inicio + 13)]

        def serie(s: list) -> dict:
            saz = []
            for m in range(12):
                a, b = s[m], s[m + 1]
                saz.append((b / dias[m + 1]) / (a / dias[m]) - 1 if a > 0 and b > 0 and dias[m] and dias[m + 1] else None)
            return {"atual": [s[12 + m] if jan + m <= ultimo else None for m in range(12)],
                    "anterior": s[:12], "sazonalidade": saz}

        return {"ano": jan // 12, "base": ib % 12, "meta": (ib + 1) % 12 if (ib + 1) // 12 == jan // 12 else None,
                "total": serie(series["total"]),
                "produtos": {str(p): serie(series[p]) for p in produtos if p in series}}

    def _parametros(self, k: dict, i_meta: int) -> dict:
        ib = i_meta - 1
        jan = ib - ib % 12
        return {"crescimento": k["alvo"], "teto_sazonalidade": k["teto_saz"], "teto_crescimento": k["teto_cre"],
                "acumulado": {"de": curto_mes(jan), "ate": curto_mes(ib), "de_ly": curto_mes(jan - 12),
                              "ate_ly": curto_mes(ib - 12)},
                "base_ly": curto_mes(ib - 12), "meta_ly": curto_mes(i_meta - 12),
                "grao": "vendedor × área × produto" if k["estado"] == "BA" else "vendedor × produto",
                "faturamentos": "da área" if k["estado"] == "BA" else "dias úteis do ES"}

    # --- Assistente ------------------------------------------------------------------------------
    def para_ia(self, estado: str, mes: str | None = None, vendedor: int | None = None, produtos: bool = False,
                permitidos: set[int] | None = None, equipes: set[str] | None = None) -> dict:
        """A sugestão enxuta para a ferramenta sugestao_metas: o resumo dos vendedores do estado ou, com vendedor, os
        números dele (e os produtos, com produtos=True ou com vendedor)."""
        r = self.calcular(estado, mes, vendedor, None, permitidos, equipes)
        p = r["parametros"]
        saida = {
            "estado": r["estado"], "mes_da_meta": r["mes"]["rotulo_meta"], "mes_base": r["mes"]["rotulo_base"],
            "regra": (f"meta por {p['grao']}: volume do mês base ÷ faturamentos ({p['faturamentos']}) × sazonalidade "
                      f"(ano passado, teto de +{p['teto_sazonalidade']:.0%}) × faturamentos do mês da meta × crescimento "
                      f"proposto ({p['crescimento']:.0%} no ano menos o acumulado de {p['acumulado']['de']} a "
                      f"{p['acumulado']['ate']}, entre 0% e +{p['teto_crescimento']:.0%}); R$ = volume × preço médio "
                      "bruto do mês base. Carteira atual de cada vendedor."),
        }
        enxuto = lambda x: round(x, 4) if isinstance(x, float) else x  # noqa: E731
        if vendedor is None:
            saida["vendedores"] = [{"id": v["id"], "vendedor": v["nome"], "base_rs": enxuto(v["base_rs"]),
                                    "meta_sugerida_rs": enxuto(v["meta_rs"]), "crescimento": enxuto(v["crescimento"]),
                                    "meta_lancada_na_planilha": enxuto(v["meta_lancada"])} for v in r["resumo"]]
            saida["total_meta_sugerida_rs"] = enxuto(sum(v["meta_rs"] for v in r["resumo"]))
        else:
            c = r["cartoes"] or {}
            v = next((x for x in r["resumo"] if x["id"] == vendedor), {})
            saida["vendedor"] = {"id": vendedor, "nome": v.get("nome"), "meta_sugerida_rs": enxuto(c.get("meta_rs")),
                                 "base_rs": enxuto(c.get("base_rs")), "crescimento_total": enxuto(c.get("crescimento_total")),
                                 "sazonalidade_media": enxuto(c.get("sazonalidade")),
                                 "crescimento_proposto_medio": enxuto(c.get("crescimento")),
                                 "efeito_dos_faturamentos": enxuto(c.get("efeito_faturamentos")),
                                 "meta_lancada_na_planilha": enxuto(v.get("meta_lancada"))}
        if produtos or vendedor is not None:
            saida["produtos"] = [{"id": x["id"], "produto": x["nome"], "unidade": x["unidade"],
                                  "volume_base": enxuto(x["volume_base"]), "meta_volume": enxuto(x["meta_volume"]),
                                  "preco_medio": enxuto(x["preco"]), "meta_rs": enxuto(x["meta_rs"]),
                                  "sazonalidade": enxuto(x["sazonalidade"]), "crescimento_proposto": enxuto(x["crescimento"])}
                                 for x in r["produtos"][:MAX_PRODUTOS_IA]]
            if len(r["produtos"]) > MAX_PRODUTOS_IA:
                saida["aviso_produtos"] = f"{len(r['produtos'])} produtos; mostrando os {MAX_PRODUTOS_IA} de maior meta"
        if r["avisos"]:
            saida["avisos"] = r["avisos"]
        return saida

    # --- configuração ----------------------------------------------------------------------------
    def _dias_de_faturamento(self, areas: list[int]) -> dict[int, list[dict]]:
        """Em que dias da semana cada área faturou nos últimos 6 meses (os 3 mais comuns, pela soma dos clientes
        atendidos em cada dia): para quem configura ver quando o prazo não bate com as vendas."""
        if not areas:
            return {}
        data_ref = self.calc.cache.data_ref()
        linhas = self.calc.cache.consulta(
            f"SELECT d.id_area, isodow(v.data), COUNT(*) FROM vendas_clientes v JOIN clientes_detalhes d ON d.id = v.id_cliente "
            f"WHERE v.tipocliente = 'CLIENTE' AND v.data BETWEEN ? AND ? AND d.id_area IN ({','.join('?' * len(areas))}) "
            "GROUP BY 1, 2", [data_ref - dt.timedelta(days=183), data_ref, *areas])
        por_area: dict[int, dict[int, int]] = defaultdict(dict)
        for a, dia, n in linhas:
            por_area[a][dia] = n
        saida = {}
        for a, contagem in por_area.items():
            total = sum(contagem.values())
            saida[a] = [{"dia": DIAS_SEMANA[d - 1], "pct": n / total}
                        for d, n in sorted(contagem.items(), key=lambda x: -x[1])[:3]]
        return saida

    def config_dados(self, mes: str | None = None) -> dict:
        """Para Configurar: as regras, o padrão e as áreas dos vendedores do BA com a contagem dos 4 meses da conta do
        mês da meta escolhido (automática, fixa e ajustada)."""
        self._conferir()
        regras = self.calc.regras()
        d = self._dados(regras)
        primeiro, ultimo = self.meses_possiveis()
        i_meta = ler_mes(mes) if mes else indice(self.calc.cache.data_ref())
        if not primeiro <= i_meta <= ultimo:
            raise ValueError(f"escolha um mês da meta entre {curto_mes(primeiro)} e {curto_mes(ultimo)}")
        meses = [i_meta - 1, i_meta, i_meta - 13, i_meta - 12]  # base, meta, base e meta do ano passado
        ba = set(self._vendedores(d, regras, "BA", None, None, i_meta))
        cfg = self.config.atual()
        nomes = self.nomes()
        dias = self.areas()
        cal = self.calc.calendario(regras)
        por_area: dict[int, dict] = {}
        for (v, a), n in d["clientes_area"].items():
            if v in ba:
                x = por_area.setdefault(a, {"clientes": 0, "vendedores": set()})
                x["clientes"] += n
                x["vendedores"].add(nomes.get(v) or f"Vendedor {v}")
        citadas = ({int(a) for a in cfg["fixos"]} | {int(a) for a in cfg["prazos"]}
                   | {int(a) for m in cfg["ajustes"].values() for a in m})
        observado = self._dias_de_faturamento(sorted(set(por_area) | citadas))
        areas = []
        for a in sorted(set(por_area) | citadas, key=lambda x: (d["nomes_areas"].get(x) or "").upper()):
            info = por_area.get(a, {"clientes": 0, "vendedores": set()})
            dd = dias.get(a)  # None = pendente; [] = área não atendida
            areas.append({
                "id": a, "nome": d["nomes_areas"].get(a) or f"Área {a}", "dias": dd,
                "clientes": info["clientes"], "vendedores": sorted(info["vendedores"])[:4],
                # a contagem automática com o prazo de 1 a MAX_PRAZO dias (a tela mostra a do prazo do rascunho)
                "automatico": {str(pz): {texto_mes(i): (faturamentos_do_mes(cal, dd, i // 12, i % 12 + 1, "BA", pz)
                                                        if dd else None) for i in meses}
                               for pz in range(1, MAX_PRAZO + 1)},
                "faturamento_observado": observado.get(a, []),
            })
        return {"config": cfg, "padrao": padrao(), "areas": areas,
                "mes": texto_mes(i_meta), "meses": [{"valor": texto_mes(i), "rotulo": curto_mes(i)} for i in meses],
                "papeis": ["base", "meta", "base_ly", "meta_ly"],
                "opcoes_meses": [{"valor": texto_mes(i), "rotulo": rotulo_mes(i)} for i in range(ultimo, primeiro - 1, -1)]}

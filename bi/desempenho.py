"""Painel de desempenho da equipe (página Gestão, abaixo da Equipe): o período (um dia ou uma semana) e o mês de cada
vendedor da região contra as metas. Veio do Painel Comercial (painel-mais-vida), com as contas do bi-mais-vida.

Período (filtro com atalhos):
- ultimo_dia: o último dia útil antes de hoje, pelo calendário da região (o padrão);
- semana: a semana anterior já fechada, de segunda a domingo;
- hoje: até a última cópia do banco (primeiro horário, 10h, 12h e 15h).
Os números do período somam os dias dele; os do mês vão do dia 1º até o fim do período (o mês do fim).

Indicadores de cada vendedor:
- faturamento, mussarela e outras linhas: o realizado da página Metas (Calculadora.movimento_diario), pelo vendedor
  da nota. A meta do período é a soma da expectativa de cada dia (abaixo); a de mussarela e a de outras, a expectativa
  × a parte delas na meta do mês. No BA (meta por volume, sem mussarela e outras em R$ na planilha), a meta de cada uma
  é o volume da METAS PRODUTOS × o preço médio do próprio vendedor no mês anterior (faturamento bruto ÷ volume; sem
  venda dele do produto nesse mês, o preço da região), ajustada para as duas somarem a meta de faturamento.
- atendimentos: clientes com pedido na rota do dia ÷ visitas esperadas no dia, com a regra da efetividade (semanal
  sempre; quinzenal sem compra nos 7 dias antes; mensal sem compra nos 21 dias antes), pelo vendedor da carteira.
- efetividade acumulada do mês: a das campanhas (indicadores._efetividade: a média da efetividade de cada dia), meta
  de 100%.
- frequência: a das campanhas (semanas com compra ÷ clientes positivados, pelo vendedor da nota). A meta: as compras
  esperadas de cada um desses clientes no mês inteiro, atendido dentro da periodicidade (compras_esperadas), em média.
- positivação: clientes distintos com nota no mês, pelo vendedor da nota (a da página Metas) × META CLIENTE.
- ticket médio: a venda média da página Metas (faturamento ÷ clientes) × meta de faturamento ÷ META CLIENTE.
- % troca: devoluções e brindes de vencido e danificado ÷ faturamento bruto da carteira (pelo dono do cliente), com
  teto de 1,5% (atenção acima de 1,0%). Vencido e danificado saem do nome do motivo (motivos_de_troca).

Expectativa diária (a meta do dia, expectativa()):
1. Potencial do cliente: a média do que ele comprou nos 2 meses fechados antes do mês (a venda menos a devolução que
   desconta, de qualquer vendedor). Entram os clientes ativos da carteira atual do vendedor (sem "PEDIDO BLOQUEADO").
2. O potencial de cada cliente é dividido igualmente entre os dias de atendimento dele no mês (os dias da área em
   areas_atendimento, menos os feriados). O potencial do dia é a soma do que cai nele.
3. Saldo = meta do mês − faturado no mês até a véspera − pedidos de venda em aberto (feitos no mês, há menos de 8
   dias, sem nota e não cancelados).
4. Com saldo: a parte do dia no saldo (pelo potencial dele entre os dias que restam), nunca abaixo do potencial normal
   do dia. Meta batida (sem saldo): o potencial normal do dia. Sem dia de atendimento pela frente e ainda com saldo: o
   saldo dividido pelos dias úteis que restam.
"""
from __future__ import annotations

import datetime as dt
import unicodedata
from collections import defaultdict

from .indicadores import _efetividade, _marcas, medir

UM_DIA = dt.timedelta(days=1)
PERIODOS = {"ultimo_dia": "Último dia fechado", "semana": "Última semana", "hoje": "Hoje"}
PERIODO_PADRAO = "ultimo_dia"
FAIXAS = {"verde": 1.0, "amarelo": 0.9}         # % da meta: verde a partir de 100%, amarelo a partir de 90%
TROCA = {"teto": 0.015, "atencao": 0.010}       # % de troca: verde até 1,0%, amarelo até 1,5%
META_EFETIVIDADE = 1.0                          # 100%
DIAS_PEDIDO_ABERTO = 8                          # o pedido em aberto feito há menos de 8 dias desconta do saldo
MESES_POTENCIAL = 2                             # o potencial do cliente: a média dos 2 meses fechados antes do mês
TETO_NOTA = 1.5                                 # na nota geral, um indicador conta no máximo 150%
MAX_VOLTA = 31                                  # dias para trás à procura do último dia útil
# As linhas do quadro, na ordem (e as que entram na nota geral): (onde, indicador).
LINHAS = (("mes", "positivacao"), ("dia", "atendimentos"), ("dia", "faturamento"), ("dia", "mussarela"),
          ("dia", "outras"), ("mes", "ticket"), ("mes", "frequencia"), ("mes", "efetividade"), ("mes", "troca"))
_FREQUENCIA = {"metrica": "frequencia", "parametros": {"clientes": "todos"}, "filtros": {}}


def _mes(d: dt.date) -> dt.date:
    return d.replace(day=1)


def _fim_do_mes(d: dt.date) -> dt.date:
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - UM_DIA


def _mes_anterior(mes: dt.date) -> dt.date:
    return _mes(mes - UM_DIA)


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().upper()


def motivos_de_troca(motivos) -> set[int]:
    """Os motivos de vencido e danificado, pelo nome (como no Painel Comercial): contém VENCIDO ou DANIFICADO e não
    começa com PERDA (quebra na fábrica ou na câmara não é troca no cliente). Motivo novo entra sozinho."""
    saida = set()
    for mid, nome in motivos:
        n = _sem_acento(nome).strip()
        if not n.startswith("PERDA") and ("VENCID" in n or "DANIFICAD" in n):
            saida.add(int(mid))
    return saida


def periodo(chave: str | None, hoje: dt.date, cal, regiao: str) -> dict:
    """O período do filtro: {chave, rotulo, inicio, fim}. ultimo_dia: o último dia útil antes de hoje no calendário
    da região; semana: de segunda a domingo da semana anterior; hoje: hoje."""
    chave = str(chave or PERIODO_PADRAO).strip().lower()
    if chave not in PERIODOS:
        raise ValueError(f"período desconhecido: {chave!r} (use {', '.join(PERIODOS)})")
    if chave == "hoje":
        inicio = fim = hoje
    elif chave == "semana":
        inicio = hoje - dt.timedelta(days=hoje.weekday() + 7)
        fim = inicio + dt.timedelta(days=6)
    else:
        d = hoje - UM_DIA
        for _ in range(MAX_VOLTA):
            if cal.dia(d, regiao)["peso"] > 0:
                break
            d -= UM_DIA
        inicio = fim = d
    return {"chave": chave, "rotulo": PERIODOS[chave], "inicio": inicio, "fim": fim}


def compras_esperadas(dias: list[dt.date], semanas: int, ultima: dt.date | None) -> int:
    """Quantas compras se esperam nos dias de atendimento (em ordem) se o vendedor atende o cliente dentro da
    periodicidade, partindo da última compra antes deles. Semanal (semanas = 1): uma por semana, de domingo a sábado;
    se ele já comprou no pedaço da semana que ficou no mês anterior, a primeira semana não espera. Quinzenal (2) e
    mensal (4): espera no dia de atendimento sem compra nos 7 ou 21 dias antes (a regra da efetividade). Cada compra
    esperada conta como feita, e a próxima parte dela."""
    n = 0
    for d in dias:
        if semanas <= 1:
            inicio_semana = d - dt.timedelta(days=d.isoweekday() % 7)  # o domingo
            espera = ultima is None or ultima < inicio_semana
        else:
            espera = ultima is None or ultima < d - dt.timedelta(days=7 * (semanas - 1))
        if espera:
            n += 1
            ultima = d
    return n


def expectativa(meta: float | None, faturado: float, abertos: float, potencial: dict[dt.date, float],
                uteis: dict[dt.date, float], dia: dt.date) -> dict:
    """A meta do dia (veja o topo do arquivo). potencial: o potencial de cada dia de atendimento do mês; uteis: o peso
    de cada dia útil do mês (para quando não sobra dia de atendimento). modo: saldo (a parte do dia no saldo),
    potencial (a parte ficou abaixo do potencial normal, que vale), meta_batida, sem_rota (o saldo pelos dias úteis)
    ou sem_meta."""
    pot = potencial.get(dia, 0.0)
    base = {"potencial": pot, "faturado": faturado, "abertos": abertos}
    if not meta:
        return {**base, "meta": None, "saldo": None, "modo": "sem_meta"}
    saldo = meta - faturado - abertos
    if saldo <= 0:
        return {**base, "meta": pot, "saldo": saldo, "modo": "meta_batida"}
    restante = sum(v for d, v in potencial.items() if d >= dia)
    if restante > 0:
        parte = saldo * pot / restante
        return {**base, "meta": max(parte, pot), "saldo": saldo, "parte": parte,
                "modo": "potencial" if pot > parte else "saldo"}
    resto = sum(p for d, p in uteis.items() if d >= dia)
    return {**base, "meta": saldo * uteis.get(dia, 0.0) / resto if resto else 0.0, "saldo": saldo, "modo": "sem_rota"}


def bloco(real, meta, invertido: bool = False, **extra) -> dict:
    """Um indicador: o realizado, a meta, o % (no invertido, o quanto do teto foi usado) e a situação pelas faixas
    (batida, atencao, abaixo; sem_meta sem meta; sem_dados sem o realizado)."""
    if real is None:
        return {"real": None, "meta": meta or None, "pct": None, "status": "sem_dados", **extra}
    if not meta:
        return {"real": real, "meta": None, "pct": None, "status": "sem_meta", **extra}
    pct = real / meta
    if invertido:
        status = "batida" if real <= TROCA["atencao"] else "atencao" if real <= TROCA["teto"] else "abaixo"
    else:
        status = "batida" if pct >= FAIXAS["verde"] else "atencao" if pct >= FAIXAS["amarelo"] else "abaixo"
    return {"real": real, "meta": meta, "pct": pct, "status": status, **extra}


def nota_geral(v: dict) -> float | None:
    """A média dos atingimentos das linhas do quadro (cada uma no máximo 150%); na troca, o quanto do teto sobrou (um
    teto estourado não vira bônus). Linha sem meta ou sem dados fica fora."""
    partes = []
    for onde, k in LINHAS:
        b = v[onde][k]
        if b["pct"] is None:
            continue
        partes.append(max(0.0, 1 - b["pct"]) if k == "troca" else min(b["pct"], TETO_NOTA))
    return sum(partes) / len(partes) if partes else None


def _r(x, casas=2):
    return None if x is None else round(x, casas)


def _int(x) -> int | None:
    """O código vindo do recorte (vazio pode chegar como None ou NaN)."""
    try:
        return None if x is None or x != x else int(x)
    except (TypeError, ValueError):
        return None


class Painel:
    """As contas de uma leitura do painel: o recorte da Gestão (k), os dias de atendimento das áreas e a região."""

    def __init__(self, calc, k, areas: dict[int, list[int]], regiao: str, equipes: tuple[str, ...]):
        self.calc, self.cache = calc, calc.cache
        self.cur, self.regras, self.cal = k.cur, k.regras, k.cal
        self.areas, self.regiao, self.equipes = areas, regiao, equipes
        self.avisos: list[str] = []
        self._dias_area: dict = {}
        self._potenciais: dict = {}
        self._precos: dict = {}
        self._carteira: dict | None = None
        self._planos: dict = {}

    def _aviso(self, texto: str) -> None:
        if texto not in self.avisos:
            self.avisos.append(texto)

    # --- programação e potencial -----------------------------------------------------------
    def dias_da_area(self, id_area, mes: dt.date) -> list[dt.date]:
        """Os dias de atendimento da área no mês: os dias da semana dela em areas_atendimento, menos os feriados da
        região. Área sem linha (pendente) ou sem dias: nenhum."""
        chave = (id_area, mes)
        if chave not in self._dias_area:
            dias = set(self.areas.get(id_area) or []) if id_area is not None else set()
            self._dias_area[chave] = [x["data"] for x in self.cal.dias_do_mes(mes.year, mes.month, self.regiao)
                                      if x["data"].isoweekday() in dias and x["tipo"] != "feriado"]
        return self._dias_area[chave]

    def potenciais(self, mes: dt.date) -> dict[int, float]:
        """O potencial mensal de cada cliente: a média dos 2 meses fechados antes do mês (venda − devolução que
        desconta, sem os produtos "não conta", de qualquer vendedor). Lido do cache, com as regras da página Metas
        (a página Metas usa sem montar o recorte da Gestão)."""
        if mes not in self._potenciais:
            ini = mes
            for _ in range(MESES_POTENCIAL):
                ini = _mes_anterior(ini)
            fim = mes - UM_DIA
            somas: dict[int, float] = defaultdict(float)

            def conta(pid) -> bool:
                return self.regras.grupo_produto(self.regras.produto(pid)) != "fora"

            for c, pid, valor in self.cache.consulta(
                    "SELECT id_cliente, id_produto, SUM(valor) FROM vendas_clientes_itens WHERE tipocliente = 'CLIENTE' "
                    "AND data BETWEEN ? AND ? GROUP BY 1, 2", [ini, fim]):
                if conta(pid):
                    somas[int(c)] += float(valor or 0)
            for c, pid, motivo, cancelada, valor in self.cache.consulta(
                    "SELECT id_cliente, id_produto, id_motivo, cancelada, SUM(valor) FROM devolucoes_clientes_itens "
                    "WHERE tipocliente = 'CLIENTE' AND data BETWEEN ? AND ? GROUP BY 1, 2, 3, 4", [ini, fim]):
                if motivo in self.regras.motivos and not (cancelada and self.regras.ignorar_canceladas) and conta(pid):
                    somas[int(c)] -= float(valor or 0)
            self._potenciais[mes] = {c: max(0.0, s) / MESES_POTENCIAL for c, s in somas.items()}
        return self._potenciais[mes]

    def carteira(self) -> dict[int, list[tuple[int, int | None]]]:
        """Os clientes visitáveis da carteira de hoje de cada vendedor (ativos, sem "PEDIDO BLOQUEADO" no nome, como
        na efetividade): {vendedor: [(cliente, área)]}."""
        if self._carteira is None:
            saida = defaultdict(list)
            for v, c, a in self.cache.consulta(
                    "SELECT c.id_vendedor, c.id, d.id_area FROM clientes c LEFT JOIN clientes_detalhes d ON d.id = c.id "
                    "WHERE COALESCE(c.id_vendedor, 0) <> 0 AND COALESCE(d.inativo, 0) = 0 "
                    "AND NOT contains(upper(COALESCE(c.nome, '')), 'PEDIDO BLOQUEADO')"):
                saida[int(v)].append((int(c), _int(a)))
            self._carteira = dict(saida)
        return self._carteira

    def plano(self, vid: int, mes: dt.date) -> dict:
        """O potencial de cada dia de atendimento do mês do vendedor e o peso dos dias úteis."""
        chave = (vid, mes)
        if chave not in self._planos:
            pots = self.potenciais(mes)
            por_dia: dict[dt.date, float] = defaultdict(float)
            com = sem = 0
            total = 0.0
            for cli, area in self.carteira().get(vid, []):
                dias = self.dias_da_area(area, mes)
                if not dias:
                    sem += 1
                    continue
                com += 1
                p = pots.get(cli, 0.0)
                if p <= 0:
                    continue
                total += p
                for d in dias:
                    por_dia[d] += p / len(dias)
            uteis = {x["data"]: x["peso"] for x in self.cal.dias_do_mes(mes.year, mes.month, self.regiao) if x["peso"] > 0}
            self._planos[chave] = {"potencial": dict(por_dia), "uteis": uteis, "clientes": com,
                                   "sem_programacao": sem, "potencial_mes": total}
        return self._planos[chave]

    def abertos(self, ids: list[int], inicio: dt.date, fim: dt.date) -> dict[int, dict[dt.date, float]]:
        """Os pedidos de venda em aberto (sem nota, não cancelados) de cada vendedor por dia do pedido."""
        if self.cache.sem_pedidos_detalhe:
            self._aviso("os pedidos um a um ainda não chegaram do computador da empresa: o saldo da meta do dia conta "
                        "só o faturado (sem os pedidos em aberto)")
            return {}
        saida: dict = defaultdict(lambda: defaultdict(float))
        for vid, d, total in self.cache.consulta(
                f"SELECT id_vendedor, data, SUM(total) FROM pedidos_venda_detalhe WHERE data BETWEEN ? AND ? "
                f"AND id_vendedor IN ({_marcas(ids)}) AND tipopedido = 'PEDIDOVENDA' AND NOT COALESCE(cancelada, false) "
                f"AND id_venda IS NULL AND COALESCE(status, '') <> 'V' GROUP BY 1, 2", [inicio, fim, *ids]):
            saida[vid][d] += float(total or 0)
        return saida

    # --- metas -----------------------------------------------------------------------------
    def precos(self, mes: dt.date) -> tuple[dict, dict]:
        """O preço médio de cada produto no mês (faturamento bruto ÷ volume): (por vendedor, da região)."""
        if mes not in self._precos:
            por_v: dict = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
            reg: dict = defaultdict(lambda: [0.0, 0.0])
            for vid, pid, valor, qtd in self.cache.consulta(
                    "SELECT id_vendedor, id_produto, SUM(valor), SUM(quantidade) FROM vendas_itens "
                    "WHERE data BETWEEN ? AND ? GROUP BY 1, 2", [mes, _fim_do_mes(mes)]):
                p = self.regras.produto(pid)
                x = por_v[vid][p]
                x[0] += valor
                x[1] += qtd
                if self.regras.grupo_vendedor(vid) in self.equipes:
                    r = reg[p]
                    r[0] += valor
                    r[1] += qtd

            def preco(x):
                return x[0] / x[1] if x[0] > 0 and x[1] > 0 else None

            self._precos[mes] = ({v: {p: preco(x) for p, x in ps.items()} for v, ps in por_v.items()},
                                 {p: preco(x) for p, x in reg.items()})
        return self._precos[mes]

    def metas_linhas(self, mes: dt.date, vid: int, m: dict) -> tuple[float, float, str]:
        """(meta de mussarela, meta de outras, regime) do vendedor no mês. Valor: as da planilha (ou da aprovada). Volume
        (as duas vazias, como no BA): volume da meta × preço médio do vendedor no mês anterior (o da região quando ele
        não vendeu o produto), ajustadas para somar a meta de faturamento."""
        if m["mus"] or m["out"]:
            return m["mus"], m["out"], "valor"
        volumes: dict[int, float] = defaultdict(float)
        for x in self.calc.metas_produtos.dados():
            if x["mes"] == mes and x["id_vendedor"] == vid:
                volumes[self.regras.produto(x["id_produto"])] += x["meta_volume"]
        if not volumes or not m["fat"]:
            return 0.0, 0.0, "sem_separacao"
        do_vendedor, da_regiao = self.precos(_mes_anterior(mes))
        meus = do_vendedor.get(vid, {})
        mus = out = 0.0
        sem_preco = 0
        for p, q in volumes.items():
            grupo = self.regras.grupo_produto(p)
            preco = meus.get(p) or da_regiao.get(p)
            if grupo == "fora":
                continue
            if not preco:
                sem_preco += 1
                continue
            if grupo == "mussarela":
                mus += q * preco
            else:
                out += q * preco
        if sem_preco:
            self._aviso("produtos da meta de volume sem venda no mês anterior ficaram fora da divisão entre mussarela "
                        "e outras linhas")
        if mus + out <= 0:
            return 0.0, 0.0, "sem_separacao"
        fator = m["fat"] / (mus + out)
        return mus * fator, out * fator, "volume"

    # --- indicadores -----------------------------------------------------------------------
    def _efetividade(self, ids: list[int], inicio: dt.date, fim: dt.date, distintos: bool) -> dict | None:
        if self.cache.sem_pedidos or self.cache.sem_rede:
            self._aviso("os pedidos de venda ou a frequência de compra dos clientes ainda não chegaram do computador "
                        "da empresa: atendimentos e efetividade aparecem depois da próxima atualização")
            return None
        r = _efetividade(self.cur, {"filtros": {}}, ids, inicio, fim, self.areas, distintos=distintos)
        for a in r["avisos"]:
            self._aviso(a)
        return r["vend"]

    def frequencia(self, ids: list[int], mes: dt.date, fim: dt.date) -> dict[int, dict]:
        """Realizado (semanas com compra ÷ clientes positivados, as campanhas) e a meta: a média das compras esperadas
        no mês inteiro dos mesmos clientes (os que têm dia de atendimento)."""
        r = medir(self.cur, _FREQUENCIA, ids, mes, fim)
        pares = self.cur.execute(
            f"SELECT DISTINCT id_vendedor, id_cliente FROM faturamento WHERE tipo = 'venda' AND tipo_cliente = 'CLIENTE' "
            f"AND data BETWEEN ? AND ? AND id_vendedor IN ({_marcas(ids)})", [mes, fim, *ids]).fetchall()
        clientes = sorted({int(c) for _, c in pares})
        info, ultima = {}, {}
        if clientes:
            marcas = _marcas(clientes)
            info = {int(c): (a, s) for c, a, s in self.cur.execute(
                f"SELECT id_cliente, id_area, frequencia_semanas FROM clientes WHERE id_cliente IN ({marcas})",
                clientes).fetchall()}
            ultima = {int(c): d for c, d in self.cur.execute(
                f"SELECT id_cadastro, MAX(data) FROM _vendas WHERE data < ? AND id_cadastro IN ({marcas}) GROUP BY 1",
                [mes, *clientes]).fetchall()}
        esperadas: dict[int, int | None] = {}
        for c in clientes:
            area, semanas = info.get(c, (None, None))
            dias = self.dias_da_area(_int(area), mes)
            esperadas[c] = compras_esperadas(dias, _int(semanas) or 1, ultima.get(c)) if dias else None
        por_v: dict[int, list[int]] = defaultdict(list)
        for v, c in pares:
            if esperadas.get(int(c)) is not None:
                por_v[int(v)].append(esperadas[int(c)])
        saida = {}
        for vid in ids:
            x = r["vend"].get(vid) or {"num": 0.0, "den": 0.0}
            meus = por_v.get(vid, [])
            saida[vid] = {"semanas": x["num"], "clientes": x["den"],
                          "real": x["num"] / x["den"] if x["den"] else None,
                          "meta": sum(meus) / len(meus) if meus else None,
                          "esperadas": sum(meus), "clientes_meta": len(meus)}
        return saida

    def positivacao(self, ids: list[int], inicio: dt.date, fim: dt.date) -> dict[int, int]:
        """Clientes distintos com nota, pelo vendedor da nota (a da página Metas)."""
        return {int(v): int(n) for v, n in self.cur.execute(
            f"SELECT id_vendedor, COUNT(DISTINCT id_cliente) FROM _pedidos WHERE data BETWEEN ? AND ? "
            f"AND id_vendedor IN ({_marcas(ids)}) GROUP BY 1", [inicio, fim, *ids]).fetchall()}

    def troca(self, ids: list[int], inicio: dt.date, fim: dt.date) -> dict[int, tuple[float, float]]:
        """{vendedor: (vencido + danificado, faturamento bruto da carteira)}, pelo dono do cliente (sem dono, quem
        emitiu): as devoluções não canceladas pela data de entrada e os brindes."""
        motivos = motivos_de_troca(self.cache.consulta("SELECT id, nome FROM motivos"))
        dono = "COALESCE(c.id_vendedor_carteira, x.id_vendedor)"
        junta = "LEFT JOIN clientes c ON c.id_cliente = x.id_cadastro"
        bruto = dict(self.cur.execute(
            f"SELECT {dono}, SUM(x.valor) FROM _vendas x {junta} WHERE x.data BETWEEN ? AND ? GROUP BY 1",
            [inicio, fim]).fetchall())
        trocas: dict = defaultdict(float)
        if motivos:
            for v, s in self.cur.execute(
                    f"SELECT {dono}, SUM(x.valor) FROM _devolucoes x {junta} WHERE x.data BETWEEN ? AND ? "
                    f"AND NOT x.cancelada AND x.id_motivo IN ({_marcas(motivos)}) GROUP BY 1",
                    [inicio, fim, *sorted(motivos)]).fetchall():
                trocas[v] += float(s or 0)
            if self.cache.sem_brindes:
                self._aviso("os brindes ainda não chegaram do computador da empresa: o % de troca conta só as "
                            "devoluções")
            else:
                for v, s in self.cache.consulta(
                        f"SELECT COALESCE(NULLIF(c.id_vendedor, 0), b.id_vendedor), SUM(b.valor) "
                        f"FROM brindes_clientes_itens b LEFT JOIN clientes c ON c.id = b.id_cliente "
                        f"AND b.tipocliente = 'CLIENTE' WHERE b.data BETWEEN ? AND ? "
                        f"AND b.id_motivo IN ({_marcas(motivos)}) GROUP BY 1", [inicio, fim, *sorted(motivos)]):
                    trocas[v] += float(s or 0)
        return {vid: (trocas.get(vid, 0.0), float(bruto.get(vid) or 0)) for vid in ids}

    # --- a expectativa de um dia -------------------------------------------------------------
    def _abertos_em(self, abertos: dict, vid: int, d: dt.date) -> float:
        """Os pedidos em aberto do vendedor no começo do dia d: feitos no mês, há menos de 8 dias."""
        desde = max(_mes(d), d - dt.timedelta(days=DIAS_PEDIDO_ABERTO - 1))
        return sum(t for dd, t in abertos.get(vid, {}).items() if desde <= dd < d)

    def _dia(self, vid: int, d: dt.date, mov: dict, abertos: dict, metas: dict, linhas: dict,
             faturado: float | None = None, em_aberto: float | None = None) -> dict:
        """A expectativa do vendedor no dia d (expectativa()), com a parte de mussarela e de outras e o realizado do
        dia. mov: o realizado de cada dia (movimento_diario) desde o 1º do mês de d; abertos: os pedidos em aberto por
        dia; metas: {mês: metas do mês}; linhas: {mês: (meta de mussarela, meta de outras, regime)} do vendedor.
        faturado e em_aberto: no lugar dos reais (a projeção da simulação)."""
        md = _mes(d)
        mt = metas[md].get(vid)
        plano = self.plano(vid, md)
        meu = mov.get(vid, {})
        if faturado is None:
            faturado = sum(x["fat"] for dd, x in meu.items() if md <= dd < d)
        if em_aberto is None:
            em_aberto = self._abertos_em(abertos, vid, d)
        fat_m = mt["fat"] if mt else 0.0
        e = expectativa(fat_m, faturado, em_aberto, plano["potencial"], plano["uteis"], d)
        mus_m, out_m, _ = linhas.get(md, (0.0, 0.0, "sem_meta"))
        separa = e["meta"] is not None and fat_m and (mus_m or out_m)
        e["meta_mus"] = e["meta"] * mus_m / fat_m if separa else None
        e["meta_out"] = e["meta"] * out_m / fat_m if separa else None
        e["real"] = meu.get(d, {"fat": 0.0, "mus": 0.0, "out": 0.0})
        return e

    def expectativa_do_dia(self, ids: list[int], dia: dt.date) -> dict[int, dict]:
        """A meta de venda do dia (a expectativa) de cada vendedor com meta no mês: a página Metas mostra no lugar do
        "necessário por dia útil". {vendedor: {"dia", "meta", "meta_mus", "meta_out", "saldo", "potencial",
        "faturado", "abertos", "modo"}}."""
        mes = _mes(dia)
        metas = {mes: self.calc._metas(self.regras, {mes}, list(self.equipes))}
        ids = sorted(v for v in ids if v in metas[mes])
        if not ids:
            return {}
        mov = self.calc.movimento_diario(self.regras, ids, mes, dia)
        abertos = self.abertos(ids, mes, dia)
        saida = {}
        for vid in ids:
            e = self._dia(vid, dia, mov, abertos, metas, {mes: self.metas_linhas(mes, vid, metas[mes][vid])})
            saida[vid] = {"dia": dia.isoformat(), **{k: e.get(k) for k in (
                "meta", "meta_mus", "meta_out", "saldo", "potencial", "faturado", "abertos", "modo")}}
        return saida

    def simular(self, vid: int, mes: dt.date, hoje: dt.date, meta: float | None = None,
                faturado: float | None = None) -> dict:
        """A expectativa de cada dia do mês de um vendedor, para conferir a conta à mão (python app.py --simular).
        Antes de hoje, com o realizado de verdade. De hoje em diante, a projeção: o vendedor vende exatamente a
        expectativa de cada dia, então o saldo de hoje se distribui pelos dias que restam (pelo potencial; com o caminho
        B, nunca abaixo do potencial normal). meta: no lugar da meta do mês (a de mussarela e de outras da planilha
        acompanham a proporção); faturado: no lugar do faturado no mês até ontem (os cenários "e se ele tivesse vendido
        X"). Os pedidos em aberto da projeção são os de hoje."""
        planilha = self.calc._metas(self.regras, {mes}, list(self.equipes)).get(vid)
        base = dict(planilha) if planilha else {"nome": "", "fat": 0.0, "mus": 0.0, "out": 0.0, "cli": 0.0}
        if meta is not None:
            fator = meta / base["fat"] if base["fat"] else 0.0
            base.update(fat=float(meta), mus=base["mus"] * fator, out=base["out"] * fator)
        metas = {mes: {vid: base}}
        mus_meta, out_meta, regime = self.metas_linhas(mes, vid, base)
        linhas = {mes: (mus_meta, out_meta, regime)}
        fim = _fim_do_mes(mes)
        mov = self.calc.movimento_diario(self.regras, [vid], mes, fim)
        abertos = self.abertos([vid], mes, fim)
        plano = self.plano(vid, mes)
        pots = self.potenciais(mes)
        info = {int(c): (n, a) for c, n, a in self.cache.consulta(
            "SELECT c.id, c.nome, d.area FROM clientes c LEFT JOIN clientes_detalhes d ON d.id = c.id "
            "WHERE c.id_vendedor = ?", [vid])}
        clientes = []
        for cli, area in self.carteira().get(vid, []):
            dias = self.dias_da_area(area, mes)
            p = pots.get(cli, 0.0)
            nome, nome_area = info.get(cli, ("", None))
            clientes.append({"id": cli, "nome": nome or "", "area": nome_area or "", "dias": [d.isoformat() for d in dias],
                             "potencial": _r(p), "por_dia": _r(p / len(dias)) if dias and p > 0 else 0.0})
        total = sum(c["potencial"] for c in clientes if c["dias"])
        for c in clientes:
            c["representatividade"] = _r(c["potencial"] / total, 6) if total and c["dias"] else None
        clientes.sort(key=lambda c: (-(c["potencial"] or 0), c["nome"]))
        por_data: dict[str, int] = defaultdict(int)  # clientes programados em cada dia (com ou sem potencial)
        for c in clientes:
            for d in c["dias"]:
                por_data[d] += 1

        data_ref = self.cache.data_ref()
        meu = mov.get(vid, {})
        real_ate_hoje = sum(x["fat"] for dd, x in meu.items() if mes <= dd < hoje)
        base_hoje = real_ate_hoje if faturado is None else float(faturado)
        abertos_hoje = self._abertos_em(abertos, vid, hoje) if mes <= hoje <= fim else 0.0
        dias, projetado = [], 0.0
        for i in range((fim - mes).days + 1):
            d = mes + i * UM_DIA
            futuro = d >= hoje
            e = (self._dia(vid, d, mov, abertos, metas, linhas, faturado=base_hoje + projetado, em_aberto=abertos_hoje)
                 if futuro else self._dia(vid, d, mov, abertos, metas, linhas))
            if futuro:
                projetado += e["meta"] or 0.0
            tem_real = data_ref is not None and d <= data_ref
            dias.append({"data": d.isoformat(), "dia_semana": d.isoweekday(), "util": plano["uteis"].get(d, 0.0),
                         "clientes": por_data.get(d.isoformat(), 0), "potencial": _r(e["potencial"]),
                         "faturado": _r(e["faturado"]), "abertos": _r(e["abertos"]), "saldo": _r(e["saldo"]),
                         "meta": _r(e["meta"]), "meta_mus": _r(e["meta_mus"]), "meta_out": _r(e["meta_out"]),
                         "modo": e["modo"], "projecao": futuro,
                         "real": _r(e["real"]["fat"]) if tem_real else None})
        return {
            "vendedor": {"id": vid, "nome": base.get("nome") or "", "regime": regime},
            "mes": mes.isoformat(), "hoje": hoje.isoformat(), "data_ref": data_ref.isoformat() if data_ref else None,
            "meta": _r(base["fat"]), "meta_planilha": _r(planilha["fat"]) if planilha else None,
            "meta_mus": _r(mus_meta), "meta_out": _r(out_meta),
            "faturado_ate_hoje": _r(base_hoje), "faturado_real": _r(real_ate_hoje), "abertos_hoje": _r(abertos_hoje),
            "saldo_hoje": _r(base["fat"] - base_hoje - abertos_hoje) if base["fat"] else None,
            "potencial_mes": _r(plano["potencial_mes"]), "clientes_programados": plano["clientes"],
            "sem_programacao": plano["sem_programacao"], "clientes": clientes, "dias": dias, "avisos": self.avisos,
        }

    # --- o painel --------------------------------------------------------------------------
    def montar(self, per: dict, time: list[int], nomes: dict[int, str]) -> dict:
        inicio, fim = per["inicio"], per["fim"]
        mes = _mes(fim)
        dias = [inicio + i * UM_DIA for i in range((fim - inicio).days + 1)]
        meses = sorted({_mes(d) for d in dias} | {mes})
        ids = sorted(time)
        cal_mes = self.cal.resumo(mes.year, mes.month, self.regiao, fim)
        saida = {
            "periodo": {**per, "inicio": inicio.isoformat(), "fim": fim.isoformat()},
            "mes": mes.isoformat(), "faixas": FAIXAS, "troca": TROCA, "meta_efetividade": META_EFETIVIDADE,
            "dias_uteis": {"total": cal_mes["dias_uteis"], "decorridos": cal_mes["dias_decorridos"],
                           "restantes": cal_mes["dias_restantes"]},
            "totais": None, "vendedores": [], "avisos": self.avisos,
        }
        if not ids:
            return saida
        mov = self.calc.movimento_diario(self.regras, ids, min(meses), fim)
        abertos = self.abertos(ids, min(meses), fim)
        metas = {m: self.calc._metas(self.regras, {m}, list(self.equipes)) for m in meses}
        atend = self._efetividade(ids, inicio, fim, distintos=True)
        efet = self._efetividade(ids, mes, fim, distintos=False)
        freq = self.frequencia(ids, mes, fim)
        pos = self.positivacao(ids, mes, fim)
        pos_periodo = self.positivacao(ids, inicio, fim)
        troca = self.troca(ids, mes, fim)
        totais = {"faturamento_periodo": 0.0, "meta_periodo": 0.0, "faturamento_mes": 0.0, "meta_mes": 0.0}

        for vid in ids:
            meu = mov.get(vid, {})
            linhas = {m: self.metas_linhas(m, vid, metas[m][vid]) for m in meses if vid in metas[m]}
            m_mes = metas[mes].get(vid)
            meta_fat = m_mes["fat"] if m_mes else 0.0
            # o período, dia a dia
            exp, soma = [], {"fat": 0.0, "mus": 0.0, "out": 0.0, "meta": 0.0, "meta_mus": 0.0, "meta_out": 0.0}
            tem_meta = False
            for d in dias:
                e = self._dia(vid, d, mov, abertos, metas, linhas)
                real = e["real"]
                for chave in ("fat", "mus", "out"):
                    soma[chave] += real[chave]
                if e["meta"] is not None:
                    tem_meta = True
                    soma["meta"] += e["meta"]
                    soma["meta_mus"] += e["meta_mus"] or 0.0
                    soma["meta_out"] += e["meta_out"] or 0.0
                exp.append({"data": d.isoformat(), "real": _r(real["fat"]), "meta": _r(e["meta"]),
                            "saldo": _r(e["saldo"]), "potencial": _r(e["potencial"]), "faturado": _r(e["faturado"]),
                            "abertos": _r(e["abertos"]), "modo": e["modo"], "parte": _r(e.get("parte")),
                            "meta_mus": _r(e["meta_mus"]), "meta_out": _r(e["meta_out"])})
            separa = tem_meta and any(x["meta_mus"] is not None for x in exp)
            a = (atend or {}).get(vid) if atend is not None else None
            clientes_periodo = pos_periodo.get(vid, 0)
            esperados = int(a["den"]) if a else 0
            dia = {
                "faturamento": bloco(_r(soma["fat"]), _r(soma["meta"]) if tem_meta else None),
                "mussarela": bloco(_r(soma["mus"]), _r(soma["meta_mus"]) if separa else None),
                "outras": bloco(_r(soma["out"]), _r(soma["meta_out"]) if separa else None),
                "atendimentos": (bloco(None, None) if atend is None else
                                 bloco(int(a["num"]) if a else 0, esperados)),
                # ticket do período (a venda média da página Metas no período) × meta do período ÷ clientes esperados
                "ticket": bloco(_r(soma["fat"] / clientes_periodo) if clientes_periodo else None,
                                _r(soma["meta"] / esperados) if tem_meta and esperados else None,
                                clientes=clientes_periodo, esperados=esperados),
            }
            # o mês, do dia 1º até o fim do período
            no_mes = [x for dd, x in meu.items() if mes <= dd <= fim]
            fat_mes = sum(x["fat"] for x in no_mes)
            mus_mes = sum(x["mus"] for x in no_mes)
            out_mes = sum(x["out"] for x in no_mes)
            mus_meta, out_meta, regime = linhas.get(mes, (0.0, 0.0, "sem_meta"))
            clientes = pos.get(vid, 0)
            meta_cli = m_mes["cli"] if m_mes else 0.0
            ef = (efet or {}).get(vid) if efet is not None else None
            fr = freq[vid]
            tr, base_tr = troca[vid]
            mes_bloco = {
                "faturamento": bloco(_r(fat_mes), _r(meta_fat)),
                "mussarela": bloco(_r(mus_mes), _r(mus_meta)),
                "outras": bloco(_r(out_mes), _r(out_meta)),
                "positivacao": bloco(clientes, meta_cli),
                "ticket": bloco(_r(fat_mes / clientes) if clientes else None,
                                _r(meta_fat / meta_cli) if meta_cli else None),
                "efetividade": (bloco(None, META_EFETIVIDADE) if efet is None else
                                bloco(_r(ef["valor"], 4) if ef and ef["valor"] is not None else None, META_EFETIVIDADE,
                                      pedidos=ef["num"] if ef else 0, visitas=ef["den"] if ef else 0,
                                      dias=ef["dias"] if ef else 0)),
                "frequencia": bloco(_r(fr["real"], 3), _r(fr["meta"], 3), semanas=fr["semanas"],
                                    clientes=fr["clientes"], esperadas=fr["esperadas"],
                                    clientes_meta=fr["clientes_meta"]),
                "troca": bloco(_r(tr / base_tr, 5) if base_tr else None, TROCA["teto"], invertido=True,
                               valor=_r(tr), base=_r(base_tr)),
            }
            plano = self.plano(vid, mes)
            v = {"id": vid, "nome": nomes.get(vid, f"Vendedor {vid}"), "regime": regime, "dia": dia, "mes": mes_bloco,
                 "expectativa": exp,
                 "programacao": {"clientes": plano["clientes"], "sem_programacao": plano["sem_programacao"],
                                 "potencial_mes": _r(plano["potencial_mes"])}}
            v["nota"] = _r(nota_geral(v), 4)
            saida["vendedores"].append(v)
            totais["faturamento_periodo"] += soma["fat"]
            totais["meta_periodo"] += soma["meta"]
            totais["faturamento_mes"] += fat_mes
            totais["meta_mes"] += meta_fat
        saida["totais"] = {k: _r(x) for k, x in totais.items()}
        saida["totais"]["periodo"] = bloco(_r(totais["faturamento_periodo"]), _r(totais["meta_periodo"]))
        saida["totais"]["mes"] = bloco(_r(totais["faturamento_mes"]), _r(totais["meta_mes"]))
        return saida

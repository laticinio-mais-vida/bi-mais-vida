"""Manejo da Base (página Manejo da Base): a campanha de cuidar da base de clientes de cada vendedor.

O painel sugere, pelos dados do ERP no cache:
- passar para a central o cliente de um vendedor das equipes do ES e da BA que parou de comprar: 30 dias o semanal, o
  quinzenal e quem não tem frequência no cadastro (o campo REDE com o nome de uma rede de lojas, ou vazio), 50 o mensal;
- inativar o inadimplente (título em aberto vencido há 120 dias ou mais) e o cliente da central que ficou 30 dias sem
  comprar, contados do que for mais recente: a entrada na central ou a última compra.
Os números são os da campanha e mudam em Manejo da Base › Configurar (ConfigManejo), junto com os vendedores da central.

Como funciona:
- Cada mês tem a sua lista (manejo_rodadas), com o prazo no penúltimo dia útil. O cliente entra na lista aberta assim
  que cai numa regra e sai sozinho se deixar de cair antes do veredito (voltou a comprar, pagou). Quem cair depois do
  prazo já entra na lista do mês seguinte.
- Quem tem a página e a marca "pode justificar" (bi/acesso.py pode_justificar) responde, até o fim do dia do prazo, se
  o cliente pode seguir a sugestão ou deve continuar como está. Depois o administrador dá o veredito: "seguir" espera o
  ERP mostrar a mudança (o painel não mexe no ERP); "manter" encerra, e o cliente só volta na lista de outro mês.
- Cada justificativa e cada veredito é uma linha nova (manejo_eventos), com os números do dia: nada é apagado.
- Um cliente tem no máximo uma sugestão em andamento, e a inativação tem prioridade sobre a central.
- A lista é atualizada (sincronizar) quando uma cópia nova do ERP chega ao site e, por garantia, quando a página é
  lida. Os dias contam até o dia da cópia (cache.dia_da_copia); o mês da lista é o do relógio.
- Uma regra cujo dado não veio no cache (a frequência, os títulos ou o histórico da carteira) fica parada: não inclui
  nem tira ninguém, e a página avisa.
- Só no site (ativo): o banco do PC é outro, e as justificativas ficam num lugar só. No PC a página avisa.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import math
import threading

from .acesso import eh_admin, pode_justificar
from .banco import hora
from .calendario import REGIOES, Calendario
from .configuracao import RegrasNoBanco
from .conversas import NaoEncontrada
from .indicadores import semanas_da_frequencia
from .premiacoes import nome_cliente

log = logging.getLogger("bi.manejo")

AVISO_PC = ("O Manejo da Base fica no site (bi.maisvida.cloud), para as justificativas e os vereditos ficarem num lugar "
            "só: abra por lá.")
EQUIPES = ("ES", "BA")  # as equipes da campanha, pelas regras de Metas (terceiros, Edir e contas internas ficam fora)
SUGESTOES = ("central", "inativar")
DECISOES = ("seguir", "manter")  # seguir: fazer o que a lista sugere; manter: o cliente continua como está
# O cliente saiu da regra antes do veredito (a linha reabre se ele voltar a cair nela no mesmo mês).
SAIDAS = {"comprou": "voltou a comprar", "pagou": "pagou os títulos vencidos", "na_central": "já está na central",
          "inativado": "já foi inativado no ERP", "fora_da_regra": "saiu da regra",
          "outra_sugestao": "passou para a lista de inativação"}
REGRAS = {"central": ("sem_compra",), "inativar": ("inadimplente", "central_sem_compra")}  # as regras de cada lista
FREQUENCIAS = {1: "semanal", 2: "quinzenal", 4: "mensal"}  # semanas_da_frequencia -> o nome
NOME_DIAS = {"semanal": "dias sem compra do cliente semanal", "quinzenal": "dias sem compra do cliente quinzenal",
             "mensal": "dias sem compra do cliente mensal", "inadimplencia": "dias de atraso do inadimplente",
             "central": "dias sem compra do cliente da central"}
PADRAO = {"versao": 1, "ligada": False,
          "dias": {"semanal": 30, "quinzenal": 30, "mensal": 50, "inadimplencia": 120, "central": 30},
          "prazo_dia_util": 2,  # contando do fim do mês: 1 = o último dia útil, 2 = o penúltimo
          "central": []}        # os vendedores da central
MIN_TEXTO = 10      # letras de quem justifica que o cliente deve continuar
MAX_TEXTO = 2000
MAX_ITENS = 500     # clientes respondidos de uma vez
TRAVA = 7_240_144   # pg_advisory_xact_lock: a atualização da lista e as respostas, uma de cada vez
FATOS_VERSAO = 1
CADASTRO_NOVO = 7   # dias: entrar na carteira até aqui depois do cadastro é o próprio cadastro, não uma reativação
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")
_ULTIMO = ("LEFT JOIN LATERAL (SELECT id, decisao, texto, criado_em, criado_por_nome FROM manejo_eventos e "
           "WHERE e.sugestao = s.id AND e.tipo = '{tipo}' ORDER BY e.id DESC LIMIT 1) {apelido} ON true ")


# --- as regras da página ------------------------------------------------------------------
def _inteiro(valor, nome: str, minimo: int, maximo: int) -> int:
    try:
        v = float(valor) if not isinstance(valor, bool) and valor not in (None, "") else math.nan
    except (TypeError, ValueError):
        v = math.nan
    if not math.isfinite(v) or v != int(v):
        raise ValueError(f"{nome}: digite um número inteiro")
    if not minimo <= v <= maximo:
        raise ValueError(f"{nome}: de {minimo} a {maximo}")
    return int(v)


def _valida(cfg: dict) -> dict:
    """Confere e normaliza o que veio da página; levanta ValueError com a explicação."""
    cfg = cfg if isinstance(cfg, dict) else {}
    dias = cfg.get("dias") if isinstance(cfg.get("dias"), dict) else {}
    central = cfg.get("central") or []
    if not isinstance(central, list):
        raise ValueError("vendedor da central inválido")
    try:
        central = sorted({int(v) for v in central if not isinstance(v, bool)})
    except (TypeError, ValueError):
        raise ValueError("vendedor da central inválido") from None
    ligada = cfg.get("ligada", False)
    if not isinstance(ligada, bool):
        raise ValueError("diga se a campanha está ligada: sim ou não")
    if ligada and not central:
        raise ValueError("para ligar a campanha, marque ao menos um vendedor da central")
    return {"versao": 1, "ligada": ligada,
            "dias": {k: _inteiro(dias.get(k, v), NOME_DIAS[k], 1, 365) for k, v in PADRAO["dias"].items()},
            "prazo_dia_util": _inteiro(cfg.get("prazo_dia_util", PADRAO["prazo_dia_util"]), "dia do prazo", 1, 10),
            "central": central}


class ConfigManejo(RegrasNoBanco):
    """Regras da página Manejo da Base (tabela regras, nome "manejo"), salvas pelo administrador: a campanha ligada ou
    não, os dias de cada regra, o dia do prazo e os vendedores da central."""

    nome = "manejo"
    _valida = staticmethod(_valida)

    def _padrao(self) -> dict:
        return json.loads(json.dumps(PADRAO))


# --- contas sem banco ---------------------------------------------------------------------
def rotulo_mes(mes: dt.date) -> str:
    return f"{MESES[mes.month - 1]} de {mes.year}"


def _iso(d: dt.date | None) -> str | None:
    return d.isoformat() if d else None


def _mes_seguinte(mes: dt.date) -> dt.date:
    return (mes.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def _mes(texto) -> dt.date:
    try:
        ano, mes = str(texto).strip().split("-")[:2]
        return dt.date(int(ano), int(mes), 1)
    except (TypeError, ValueError):
        raise ValueError(f"mes deve ser AAAA-MM (veio {texto!r})") from None


def prazo_do_mes(cal: Calendario, ano: int, mes: int, n: int) -> dt.date:
    """O último dia para justificar na lista do mês: o n-ésimo dia útil contando do fim (1 = o último, 2 = o penúltimo),
    só de segunda a sexta (o sábado com peso das regras de Metas não conta). ES e BA têm feriados diferentes: vale o
    mais cedo dos dois, um prazo só para todos. O mês com menos dias úteis que isso usa o primeiro."""
    datas = []
    for regiao in REGIOES:
        uteis = [d for d in cal.dias_uteis(ano, mes, regiao) if d.weekday() < 5]
        if uteis:
            datas.append(uteis[max(len(uteis) - n, 0)])
    return min(datas) if datas else dt.date(ano, mes, calendar.monthrange(ano, mes)[1])


def avaliar(f: dict, ctx: dict) -> tuple[str | None, dict]:
    """A sugestão para um cliente ("central", "inativar" ou None) e os fatos que a página mostra e o banco guarda.

    f: os fatos crus do cliente (Manejo._fatos). ctx: {dia (o da cópia do ERP), dias (os da configuração),
    participantes (os vendedores das equipes), central (os da central), regras ({regra: deu para conferir com este
    cache}), primeiro_retrato (o primeiro dia do histórico da carteira)}.

    - Sem compra: vendedor da campanha fora da central e dias desde a base >= o limite da frequência. A base é o mais
      recente entre a última compra (a venda; sem venda no cache, o último título), o cadastro e a reativação.
    - Inadimplente: tem título em aberto vencido há mais que os dias da regra (o corte está na consulta).
    - Central sem compra: vendedor da central e dias >= o limite, contados do mais recente entre a entrada na central
      e a última compra.
    A inativação tem prioridade: quem cai nela não é sugerido para a central."""
    dia, dias, central = ctx["dia"], ctx["dias"], ctx["central"]
    vendedor = f["id_vendedor"]
    na_central = vendedor in central
    da_campanha = vendedor in ctx["participantes"] or na_central
    primeiro = ctx.get("primeiro_retrato")
    frequencia = FREQUENCIAS.get(semanas_da_frequencia(f["rede"]), "sem_frequencia")
    ultima, origem = ((f["ultima_venda"], "venda") if f["ultima_venda"] else
                      (f["ultimo_titulo"], "titulo") if f["ultimo_titulo"] else (None, None))
    cadastro = f["data_cadastro"]
    reativado = f["na_base_desde"] if f["na_base_desde"] and primeiro and f["na_base_desde"] > primeiro else None
    if reativado and cadastro and reativado <= cadastro + dt.timedelta(days=CADASTRO_NOVO):
        reativado = None  # cliente novo: entrou na carteira ao ser cadastrado
    if na_central:
        limite = dias["central"]
        entrada = f["na_central_desde"] or dia  # na central sem o trecho no histórico: acabou de entrar
        conta, origem_conta = (ultima, "compra") if ultima and ultima > entrada else (entrada, "central")
    else:
        limite = dias[frequencia if frequencia in dias else "semanal"]
        entrada = None
        datas = [(d, o) for d, o in ((ultima, "compra"), (cadastro, "cadastro"), (reativado, "reativacao"))
                 if d and d <= dia]
        conta, origem_conta = max(datas, key=lambda x: x[0]) if datas else (None, None)
    dias_sem = (dia - conta).days if conta else None
    ativo = not f["inativo"] and not f["ficticio"]
    pode = ctx["regras"]
    passou = dias_sem is not None and dias_sem >= limite
    sem_compra = bool(ativo and pode["sem_compra"] and da_campanha and not na_central and passou)
    inadimplente = bool(ativo and pode["inadimplente"] and da_campanha and (f["inad_titulos"] or 0) > 0)
    central_sem_compra = bool(ativo and pode["central_sem_compra"] and na_central and passou)
    motivos = [m for m, vale in (("inadimplente", inadimplente), ("central_sem_compra", central_sem_compra),
                                 ("sem_compra", sem_compra)) if vale]
    sugestao = "inativar" if inadimplente or central_sem_compra else "central" if sem_compra else None
    inadimplencia = None
    if (f["inad_titulos"] or 0) > 0:
        inadimplencia = {"titulos": int(f["inad_titulos"]), "total": round(float(f["inad_total"] or 0), 2),
                         "saldo": round(float(f["inad_saldo"] or 0), 2),
                         "vencimento_mais_antigo": _iso(f["inad_desde"]),
                         "dias": (dia - f["inad_desde"]).days if f["inad_desde"] else None}
    com_vendedor = f["com_vendedor_desde"]
    return sugestao, {
        "versao": FATOS_VERSAO, "dia": dia.isoformat(), "id_vendedor": vendedor, "inativo": bool(f["inativo"]),
        "cidade": f["cidade"], "uf": f["uf"], "area": f["area"],
        "frequencia": frequencia, "rede": " ".join(str(f["rede"] or "").split()) or None,
        "ultima_compra": _iso(ultima), "origem_ultima_compra": origem,
        "conta_desde": _iso(conta), "origem_conta": origem_conta, "dias_sem_compra": dias_sem, "limite": limite,
        "motivos": motivos,
        "na_central_desde": _iso(entrada) if na_central else None,
        "na_central_desde_antes": bool(na_central and primeiro and entrada <= primeiro),
        "com_vendedor_desde": _iso(com_vendedor),
        "com_vendedor_desde_antes": bool(com_vendedor and primeiro and com_vendedor <= primeiro),
        "inadimplencia": inadimplencia,
        "bloqueado_no_erp": None if f["bloqueado"] is None else bool(f["bloqueado"]),
        "compras_12_meses": {"valor": round(float(f["compras_valor"] or 0), 2), "meses": int(f["compras_meses"] or 0)},
    }


def _motivo_saida(sugestao: str, antes: dict, f: dict, nova: str | None, agora: dict, central: set[int],
                  escopo: set[int]) -> str:
    """Por que o cliente saiu da regra da linha (uma das SAIDAS). antes: os fatos da linha; agora: os de hoje."""
    comprou = bool(agora["ultima_compra"] and agora["ultima_compra"] > (antes.get("ultima_compra") or ""))
    if sugestao == "central":
        if nova == "inativar":
            return "outra_sugestao"
        if f["id_vendedor"] in central:
            return "na_central"
        return "comprou" if comprou and f["id_vendedor"] in escopo else "fora_da_regra"
    if f["id_vendedor"] not in escopo:
        return "fora_da_regra"
    motivos = antes.get("motivos") or []
    if "central_sem_compra" in motivos and comprou:
        return "comprou"
    if "inadimplente" in motivos and not agora["inadimplencia"]:
        return "pagou"
    return "comprou" if comprou else "fora_da_regra"


def _evento(e) -> dict | None:
    """(id, decisao, texto, criado_em, criado_por_nome) -> o que a página mostra."""
    if e[0] is None:
        return None
    return {"id": e[0], "decisao": e[1], "texto": e[2], "por": e[4] or "usuário excluído", "em": hora(e[3])}


def _entrada(retrato: dict) -> dict:
    """Os números do dia em que o cliente entrou na lista."""
    return {"dias_sem_compra": retrato.get("dias_sem_compra"), "ultima_compra": retrato.get("ultima_compra"),
            "dias_inadimplencia": (retrato.get("inadimplencia") or {}).get("dias")}


# --- a página -----------------------------------------------------------------------------
class Manejo:
    """As listas do Manejo da Base, nas tabelas manejo_rodadas, manejo_sugestoes e manejo_eventos. ativo: o site, que
    monta as listas e grava; no PC (False) a página só avisa que elas ficam no site."""

    def __init__(self, banco, calc, config: ConfigManejo, nomes_vendedores, ativo: bool, *, hoje=None):
        """calc: a Calculadora (o cache, as equipes dos vendedores e o calendário, pelas regras de Metas).
        nomes_vendedores: função -> {vendedor: nome}. hoje: o relógio (os testes fixam)."""
        self.banco = banco
        self.calc = calc
        self.config = config
        self.nomes = nomes_vendedores
        self.ativo = ativo
        self.hoje = hoje or dt.date.today
        self._trava = threading.Lock()
        self._chave: str | None = None   # a última atualização da lista: os dados, as regras e o dia
        self._avisos: list[str] = []

    # --- apoio ----------------------------------------------------------------------------
    def _hoje(self) -> dt.date:
        """O dia de hoje para o prazo e para o mês da lista (nunca antes do dia dos dados)."""
        cache = self.calc.cache
        return max(self.hoje(), cache.dia_da_copia()) if cache.pronto() else self.hoje()

    def _equipes(self, regras) -> dict[int, str]:
        """{vendedor: equipe} dos vendedores da campanha: os das equipes do ES e da BA pelas regras de Metas (quem não
        está configurado nem tem supervisor do ES ou da BA no ERP fica fora)."""
        ids = {r[0] for r in self.calc.cache.consulta(
            "SELECT id FROM vendedores UNION SELECT DISTINCT id_vendedor FROM clientes")} | set(regras.vendedores)
        return {v: g for v in ids if (g := regras.grupo_conhecido(v)) in EQUIPES}

    def _nome(self, nomes: dict, vendedor: int, guardado: str | None = None) -> str:
        return nomes.get(vendedor) or guardado or f"Vendedor {vendedor}"

    def _fatos(self, dia: dt.date, cfg: dict, escopo: set[int], central: set[int], vivos: list[int]):
        """Os fatos crus de cada cliente ativo dos vendedores do escopo e dos clientes com sugestão em andamento
        (vivos), numa consulta só ao cache: ({cliente: fato}, {regra: deu para conferir}, avisos, o primeiro dia do
        histórico da carteira). Sem o cadastro dos clientes no cache, os fatos vêm None (nada a conferir)."""
        cache = self.calc.cache
        if cache.antigo or cache.sem_detalhe:
            return None, dict.fromkeys(("sem_compra", "inadimplente", "central_sem_compra"), False), [
                "O cadastro dos clientes não veio no último envio dos dados: as listas ficam como estavam até o "
                "próximo."], None
        com_rede = not cache.sem_rede and any(
            semanas_da_frequencia(r[0]) for r in cache.consulta("SELECT DISTINCT rede FROM clientes_rede"))
        com_titulos, com_carteira = not cache.sem_credito, not cache.sem_carteira
        avisos = []
        if not com_rede:
            avisos.append("A frequência de compra dos clientes não veio no último envio dos dados: a lista de passar "
                          "para a central fica como estava até o próximo.")
        if not com_titulos:
            avisos.append("Os títulos a receber não vieram no último envio dos dados: os inadimplentes ficam como "
                          "estavam até o próximo.")
        if not com_carteira:
            avisos.append("O histórico da carteira não veio no último envio dos dados: os clientes da central ficam "
                          "como estavam até o próximo.")
        chaves = ["id", "nome", "id_vendedor", "cidade", "uf", "area", "data_cadastro", "inativo", "ficticio",
                  "ultima_venda", "compras_valor", "compras_meses"]
        colunas = ["a.id", "a.nome", "a.id_vendedor", "a.cidade", "a.uf", "a.area", "a.data_cadastro", "a.inativo",
                   "a.ficticio", "k.ultima", "z.valor", "z.meses"]
        ctes = [
            # Quem não tem o detalhe do cadastro conta como inativo (não dá para saber).
            "alvo AS (SELECT c.id, c.nome, c.id_vendedor, d.cidade, d.uf, d.area, d.data_cadastro, "
            "COALESCE(d.inativo, 1) <> 0 AS inativo, "
            "contains(upper(COALESCE(c.nome, '')), 'PEDIDO BLOQUE') AS ficticio "
            "FROM clientes c LEFT JOIN clientes_detalhes d ON d.id = c.id "
            "WHERE (list_contains(?::INTEGER[], c.id_vendedor) AND COALESCE(d.inativo, 1) = 0) "
            "OR list_contains(?::INTEGER[], c.id))",
            "compras AS (SELECT id_cliente, MAX(data) AS ultima FROM vendas_clientes WHERE tipocliente = 'CLIENTE' "
            "AND data <= ? AND id_cliente IN (SELECT id FROM alvo) GROUP BY 1)",
            "doze AS (SELECT id_cliente, SUM(valor) AS valor, COUNT(DISTINCT mes) AS meses FROM vendas_clientes_mes "
            "WHERE tipocliente = 'CLIENTE' AND mes > ? AND id_cliente IN (SELECT id FROM alvo) GROUP BY 1)",
        ]
        params: list = [sorted(escopo), sorted(vivos), dia, dia - dt.timedelta(days=365)]
        juntas = ["LEFT JOIN compras k ON k.id_cliente = a.id", "LEFT JOIN doze z ON z.id_cliente = a.id"]
        chaves.append("rede")
        if cache.sem_rede:
            colunas.append("NULL")
        else:
            colunas.append("r.rede")
            juntas.append("LEFT JOIN clientes_rede r ON r.id = a.id")
        chaves += ["ultimo_titulo", "inad_titulos", "inad_total", "inad_saldo", "inad_desde"]
        if com_titulos:
            # Há datas digitadas erradas no ERP (ano 7190): a emissão só vale até o dia dos dados. O saldo desconta o
            # que já foi pago das parcelas; o vencimento do título é o da última parcela, como na Reavaliação de Crédito.
            junta, pago = ("", "0") if cache.sem_parcelas else (" LEFT JOIN titulos_parcelas p ON p.id = t.id",
                                                                "COALESCE(p.pago, 0)")
            vencido = "t.quitado = 0 AND t.vencimento <= ?"
            ctes.append(
                "titulos AS (SELECT t.id_cliente, MAX(t.emissao) FILTER (WHERE t.emissao <= ?) AS ultimo, "
                f"COUNT(*) FILTER (WHERE {vencido}) AS n, SUM(t.total) FILTER (WHERE {vencido}) AS total, "
                f"SUM(t.total - {pago}) FILTER (WHERE {vencido}) AS saldo, "
                f"MIN(t.vencimento) FILTER (WHERE {vencido}) AS desde "
                f"FROM titulos_receber t{junta} WHERE t.id_cliente IN (SELECT id FROM alvo) GROUP BY 1)")
            corte = dia - dt.timedelta(days=cfg["dias"]["inadimplencia"])
            params += [dia, corte, corte, corte, corte]
            colunas += ["t.ultimo", "t.n", "t.total", "t.saldo", "t.desde"]
            juntas.append("LEFT JOIN titulos t ON t.id_cliente = a.id")
        else:
            colunas += ["NULL"] * 5
        chaves += ["na_base_desde", "com_vendedor_desde", "vendedor_do_trecho", "na_central_desde"]
        primeiro = None
        if com_carteira:
            # Os trechos seguidos (de = ate anterior + 1) formam um bloco: o cliente na base (qualquer mudança no
            # cadastro abre outro trecho; inativar deixa um buraco), com o mesmo vendedor e na central (de um vendedor
            # da central para outro, o bloco continua). Só vale o bloco do trecho aberto.
            ctes += [
                "trechos AS (SELECT id_cliente, de, ate, id_vendedor, "
                "list_contains(?::INTEGER[], COALESCE(id_vendedor, 0)) AS central, lag(ate) OVER w AS ate_antes, "
                "lag(id_vendedor) OVER w AS vendedor_antes, "
                "lag(list_contains(?::INTEGER[], COALESCE(id_vendedor, 0))) OVER w AS central_antes "
                "FROM clientes_vigencias WHERE id_cliente IN (SELECT id FROM alvo) "
                "WINDOW w AS (PARTITION BY id_cliente ORDER BY de))",
                "ilhas AS (SELECT id_cliente, de, ate, id_vendedor, central, "
                "SUM(CASE WHEN de = ate_antes + 1 THEN 0 ELSE 1 END) OVER w AS base, "
                "SUM(CASE WHEN de = ate_antes + 1 AND id_vendedor IS NOT DISTINCT FROM vendedor_antes THEN 0 ELSE 1 "
                "END) OVER w AS vendedor, "
                "SUM(CASE WHEN de = ate_antes + 1 AND central AND central_antes THEN 0 ELSE 1 END) OVER w AS bloco "
                "FROM trechos WINDOW w AS (PARTITION BY id_cliente ORDER BY de))",
                "na_base AS (SELECT id_cliente, MIN(de) AS desde FROM ilhas GROUP BY id_cliente, base "
                "HAVING bool_or(ate IS NULL))",
                "com_vendedor AS (SELECT id_cliente, MIN(de) AS desde, MAX(id_vendedor) AS id_vendedor FROM ilhas "
                "GROUP BY id_cliente, vendedor HAVING bool_or(ate IS NULL))",
                "na_central AS (SELECT id_cliente, MIN(de) AS desde FROM ilhas GROUP BY id_cliente, bloco "
                "HAVING bool_or(ate IS NULL) AND bool_and(central))",
            ]
            params += [sorted(central), sorted(central)]
            colunas += ["b.desde", "cv.desde", "cv.id_vendedor", "nc.desde"]
            juntas += ["LEFT JOIN na_base b ON b.id_cliente = a.id", "LEFT JOIN com_vendedor cv ON cv.id_cliente = a.id",
                       "LEFT JOIN na_central nc ON nc.id_cliente = a.id"]
            primeiro = (cache.consulta("SELECT MIN(data) FROM carteira_retratos")[0][0]
                        or cache.consulta("SELECT MIN(de) FROM clientes_vigencias")[0][0])
        else:
            colunas += ["NULL"] * 4
        chaves.append("bloqueado")
        if cache.sem_bloqueio:
            colunas.append("NULL")
        else:
            colunas.append("COALESCE(q.bloqueado, false)")
            juntas.append("LEFT JOIN clientes_bloqueio q ON q.id = a.id")
        sql = f"WITH {', '.join(ctes)} SELECT {', '.join(colunas)} FROM alvo a {' '.join(juntas)}"
        fatos = {}
        for linha in cache.consulta(sql, params):
            f = dict(zip(chaves, linha))
            # O histórico pode estar atrasado em relação ao cadastro (a cópia em que não deu para registrar a carteira).
            if f.pop("vendedor_do_trecho") != f["id_vendedor"]:
                f["com_vendedor_desde"] = None
            if f["id_vendedor"] not in central:
                f["na_central_desde"] = None
            fatos[f["id"]] = f
        return fatos, {"sem_compra": com_rede, "inadimplente": com_titulos, "central_sem_compra": com_carteira}, \
            avisos, primeiro

    # --- a lista do mês -------------------------------------------------------------------
    def _abrir_rodada(self, con, hoje: dt.date, cal: Calendario, n: int) -> tuple[dt.date, dt.date]:
        """O mês e o prazo da lista aberta hoje: o primeiro mês, a partir do de hoje, com prazo de hoje em diante.
        Enquanto a lista está aberta, o prazo acompanha o calendário (um feriado novo, o dia do prazo trocado na
        configuração), sem ficar antes de hoje; depois que passa, fica como foi gravado."""
        mes = hoje.replace(day=1)
        for _ in range(3):
            calculado = prazo_do_mes(cal, mes.year, mes.month, n)
            linha = con.execute("SELECT prazo FROM manejo_rodadas WHERE mes = %s FOR UPDATE", [mes]).fetchone()
            if linha is None:
                if calculado >= hoje:
                    con.execute("INSERT INTO manejo_rodadas (mes, prazo) VALUES (%s, %s)", [mes, calculado])
                    return mes, calculado
            elif linha[0] >= hoje:
                prazo = max(calculado, hoje)
                if prazo != linha[0]:
                    con.execute("UPDATE manejo_rodadas SET prazo = %s WHERE mes = %s", [prazo, mes])
                return mes, prazo
            mes = _mes_seguinte(mes)
        raise RuntimeError("não deu para achar o prazo da lista do mês")

    def sincronizar(self, forcar: bool = False) -> list[str]:
        """Atualiza a lista aberta com os dados do cache: inclui quem caiu numa regra, tira quem saiu dela antes do
        veredito, acompanha a troca de vendedor e marca como feito o veredito que o ERP já mostra. Não faz nada no PC,
        com a campanha desligada ou sem os dados prontos; repetir com os mesmos dados, as mesmas regras e no mesmo dia
        não muda nada. Devolve os avisos (a regra que ficou parada por falta de dado no cache)."""
        cache = self.calc.cache
        if not self.ativo or not cache.pronto():
            return []
        cfg = self.config.atual()
        if not cfg["ligada"]:
            return []
        with self._trava:
            regras = self.calc.regras()
            equipes = self._equipes(regras)
            extraido = cache.info.get("extraido_em")
            dia = cache.dia_da_copia()
            hoje = max(self.hoje(), dia)
            chave = json.dumps([extraido, hoje.isoformat(), cfg, sorted(equipes.items()), regras.cfg["calendario"]],
                               sort_keys=True)
            if chave == self._chave and not forcar:
                return list(self._avisos)
            central = set(cfg["central"])
            escopo = set(equipes) | central
            # O cache e as regras são lidos antes de abrir a transação da lista (as conexões do banco são poucas).
            with self.banco.conexao() as con:
                vivos = [r[0] for r in con.execute(
                    "SELECT id_cliente FROM manejo_sugestoes WHERE encerrada_em IS NULL")]
            fatos, disponivel, avisos, primeiro = self._fatos(dia, cfg, escopo, central, vivos)
            if cache.info.get("extraido_em") != extraido:
                return list(self._avisos)  # chegou outra cópia no meio: a próxima atualização já usa a nova
            if fatos is not None:
                ctx = {"dia": dia, "dias": cfg["dias"], "participantes": set(equipes), "central": central,
                       "regras": disponivel, "primeiro_retrato": primeiro}
                avaliados = {c: avaliar(f, ctx) for c, f in fatos.items()}
                cal = self.calc.calendario(regras)
                nomes = self.nomes()
                dados_ate = dt.datetime.fromisoformat(extraido) if extraido else dt.datetime.combine(dia, dt.time())
                with self.banco.conexao() as con:
                    con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA])
                    mes, _ = self._abrir_rodada(con, hoje, cal, cfg["prazo_dia_util"])
                    n = self._conferir(con, mes, dia, dados_ate, fatos, avaliados, set(vivos), disponivel, central,
                                       escopo, nomes)
                if any(n.values()):
                    log.info("manejo: lista de %s com os dados de %s: %s", rotulo_mes(mes), extraido,
                             ", ".join(f"{v} {k}" for k, v in n.items() if v))
            self._chave, self._avisos = chave, avisos
            return list(avisos)

    def _conferir(self, con, mes: dt.date, dia: dt.date, dados_ate: dt.datetime, fatos: dict, avaliados: dict,
                  vivos: set[int], disponivel: dict, central: set[int], escopo: set[int], nomes: dict) -> dict:
        """As linhas em andamento contra os fatos de hoje e, depois, quem caiu numa regra sem ter linha em andamento."""
        n = {"novas": 0, "reabertas": 0, "encerradas": 0, "feitas no ERP": 0}

        def encerrar(id_, motivo, publicos=None):
            con.execute("UPDATE manejo_sugestoes SET encerrada_em = %s, encerrada_motivo = %s, "
                        "fatos = COALESCE(%s::jsonb, fatos), dados_ate = %s WHERE id = %s",
                        [dia, motivo, publicos and json.dumps(publicos, ensure_ascii=False), dados_ate, id_])
            n["feitas no ERP" if motivo == "aplicado" else "encerradas"] += 1

        linhas = con.execute(
            "SELECT s.id, s.id_cliente, s.sugestao, s.id_vendedor, s.fatos, (SELECT e.decisao FROM manejo_eventos e "
            "WHERE e.sugestao = s.id AND e.tipo = 'veredito' ORDER BY e.id DESC LIMIT 1) "
            "FROM manejo_sugestoes s WHERE s.encerrada_em IS NULL ORDER BY s.id FOR UPDATE OF s").fetchall()
        em_andamento = set()
        for id_, cliente, sugestao, vendedor, antes, veredito in linhas:
            if cliente not in vivos:  # ficou em andamento agora há pouco (um veredito trocado): na próxima atualização
                em_andamento.add(cliente)
                continue
            f = fatos.get(cliente)
            if f is None:  # o cadastro do cliente sumiu do ERP
                encerrar(id_, "fora_da_regra")
                continue
            nova, publicos = avaliados[cliente]
            atualizar = ("UPDATE manejo_sugestoes SET fatos = %s::jsonb, dados_ate = %s{vendedor} WHERE id = %s",
                         [json.dumps(publicos, ensure_ascii=False), dados_ate])
            if veredito == "seguir":  # esperando o ERP: feito quando o cadastro mostra a mudança
                if f["inativo"]:
                    encerrar(id_, "aplicado" if sugestao == "inativar" else "inativado", publicos)
                elif sugestao == "central" and f["id_vendedor"] in central:
                    encerrar(id_, "aplicado", publicos)
                else:
                    con.execute(atualizar[0].format(vendedor=""), [*atualizar[1], id_])
                    em_andamento.add(cliente)
            elif f["inativo"]:
                encerrar(id_, "inativado", publicos)
            elif nova == sugestao:  # continua na regra: os números de hoje e o vendedor de hoje
                con.execute(atualizar[0].format(vendedor=", id_vendedor = %s, vendedor = %s"),
                            [*atualizar[1], f["id_vendedor"], self._nome(nomes, f["id_vendedor"]), id_])
                em_andamento.add(cliente)
            elif nova is None and not all(disponivel[r] for r in REGRAS[sugestao]):
                em_andamento.add(cliente)  # a regra da linha não deu para conferir com este envio dos dados
            else:
                encerrar(id_, _motivo_saida(sugestao, antes, f, nova, publicos, central, escopo), publicos)
        do_mes = {(c, s): (i, m) for i, c, s, m in con.execute(
            "SELECT id, id_cliente, sugestao, encerrada_motivo FROM manejo_sugestoes WHERE mes = %s", [mes])}
        for cliente, (nova, publicos) in avaliados.items():
            if nova is None or cliente in em_andamento:
                continue
            f = fatos[cliente]
            vendedor = [f["id_vendedor"], self._nome(nomes, f["id_vendedor"])]
            dados = json.dumps(publicos, ensure_ascii=False)
            existente = do_mes.get((cliente, nova))
            if existente is None:
                con.execute(
                    "INSERT INTO manejo_sugestoes (mes, id_cliente, cliente, sugestao, id_vendedor, vendedor, "
                    "id_vendedor_entrada, entrou_em, retrato, fatos, dados_ate) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)",
                    [mes, cliente, nome_cliente(f["nome"]), nova, *vendedor, vendedor[0], dia, dados, dados, dados_ate])
                n["novas"] += 1
            elif existente[1] in SAIDAS:  # tinha saído da regra neste mês e voltou: a mesma linha, com o histórico
                con.execute("UPDATE manejo_sugestoes SET encerrada_em = NULL, encerrada_motivo = NULL, "
                            "fatos = %s::jsonb, dados_ate = %s, id_vendedor = %s, vendedor = %s WHERE id = %s",
                            [dados, dados_ate, *vendedor, existente[0]])
                n["reabertas"] += 1
            # com veredito neste mês (mantido ou feito no ERP): o cliente só volta na lista de outro mês
        return n

    # --- leitura --------------------------------------------------------------------------
    @staticmethod
    def _linhas(con, onde: str, params: list, ids) -> list[tuple]:
        """As sugestões do filtro, com o prazo da lista, a última justificativa e o último veredito. ids: os vendedores
        do acesso (None = todos)."""
        if ids is not None:
            onde += " AND s.id_vendedor = ANY(%s)"
            params = [*params, sorted(ids)]
        return con.execute(
            "SELECT s.id, s.mes, s.id_cliente, s.cliente, s.sugestao, s.id_vendedor, s.vendedor, s.id_vendedor_entrada, "
            "s.entrou_em, s.retrato, s.fatos, s.encerrada_em, s.encerrada_motivo, r.prazo, "
            "j.id, j.decisao, j.texto, j.criado_em, j.criado_por_nome, "
            "v.id, v.decisao, v.texto, v.criado_em, v.criado_por_nome "
            "FROM manejo_sugestoes s JOIN manejo_rodadas r ON r.mes = s.mes "
            + _ULTIMO.format(tipo="justificativa", apelido="j") + _ULTIMO.format(tipo="veredito", apelido="v")
            + f"WHERE {onde} ORDER BY s.id", params).fetchall()

    @staticmethod
    def _situacao(motivo: str | None, justificativa, veredito, hoje: dt.date, prazo: dt.date) -> str:
        if motivo:
            return {"aplicado": "feita", "mantido": "mantida"}.get(motivo, "saiu")
        if veredito:
            return "aguardando_erp"
        if justificativa:
            return "justificada"
        return "sem_justificativa" if hoje > prazo else "a_justificar"

    def listar(self, usuario: dict, ids, mes=None) -> dict:
        """A lista de um mês para a página (mes "AAAA-MM"; vazio ou desconhecido = a aberta, ou a mais recente), só com
        os clientes dos vendedores do acesso (ids; None = todos). Cada item diz o que a pessoa pode fazer nele."""
        cache = self.calc.cache
        data_ref = cache.info.get("data_ref")
        if not self.ativo:
            return {"ativo": False, "aviso": AVISO_PC, "data_ref": data_ref, "itens": []}
        if not cache.pronto():
            raise RuntimeError("os dados ainda estão sendo preparados")
        pedido = _mes(mes) if mes else None
        cfg = self.config.atual()
        avisos = self.sincronizar()
        hoje, admin, justifica = self._hoje(), eh_admin(usuario), pode_justificar(usuario)
        nomes = self.nomes()
        equipes = self._equipes(self.calc.regras())
        filtro = "" if ids is None else " AND s.id_vendedor = ANY(%s)"
        acesso = [] if ids is None else [sorted(ids)]
        with self.banco.conexao() as con:
            rodadas = con.execute("SELECT mes, prazo FROM manejo_rodadas ORDER BY mes DESC").fetchall()
            aberta = next((m for m, p in rodadas if p >= hoje), None)
            meses = {m: p for m, p in rodadas}
            escolhido = pedido if pedido in meses else aberta or (rodadas[0][0] if rodadas else None)
            linhas, anteriores, pendencias = [], {}, []
            if escolhido:
                linhas = self._linhas(con, "s.mes = %s", [escolhido], ids)
                anteriores = dict(con.execute(
                    "SELECT s.id_cliente, COUNT(*) FROM manejo_sugestoes s WHERE s.mes <> %s AND s.id_cliente = ANY(%s)"
                    f"{filtro} GROUP BY 1", [escolhido, [x[2] for x in linhas], *acesso]).fetchall())
                # Os outros meses com cliente esperando: o veredito (a lista já fechou) ou o ERP.
                pendencias = con.execute(
                    "SELECT s.mes, COUNT(*) FILTER (WHERE v.decisao IS NULL AND r.prazo < %s), "
                    "COUNT(*) FILTER (WHERE v.decisao = 'seguir') "
                    "FROM manejo_sugestoes s JOIN manejo_rodadas r ON r.mes = s.mes "
                    "LEFT JOIN LATERAL (SELECT decisao FROM manejo_eventos e WHERE e.sugestao = s.id "
                    "AND e.tipo = 'veredito' ORDER BY e.id DESC LIMIT 1) v ON true "
                    f"WHERE s.encerrada_em IS NULL AND s.mes <> %s{filtro} GROUP BY 1 ORDER BY 1",
                    [hoje, escolhido, *acesso]).fetchall()

        def rodada(m: dt.date) -> dict:
            return {"mes": f"{m:%Y-%m}", "rotulo": rotulo_mes(m), "prazo": meses[m].isoformat(),
                    "aberta": meses[m] >= hoje, "atual": m == aberta}

        itens, vendedores = [], {}
        for x in linhas:
            (id_, _mes_linha, id_cliente, cliente, sugestao, id_vendedor, vendedor, entrada, entrou_em, retrato, fatos,
             encerrada_em, motivo, prazo) = x[:14]
            justificativa, veredito = _evento(x[14:19]), _evento(x[19:24])
            em_andamento = motivo is None
            vendedores[id_vendedor] = {"id": id_vendedor, "nome": self._nome(nomes, id_vendedor, vendedor),
                                       "equipe": equipes.get(id_vendedor)}
            itens.append({
                "id": id_, "versao": max(justificativa["id"] if justificativa else 0, veredito["id"] if veredito else 0),
                "sugestao": sugestao, "situacao": self._situacao(motivo, justificativa, veredito, hoje, prazo),
                "cliente": {"id": id_cliente, "nome": cliente, "cidade": fatos.get("cidade"), "uf": fatos.get("uf"),
                            "area": fatos.get("area")},
                "vendedor": vendedores[id_vendedor],
                "vendedor_entrada": self._nome(nomes, entrada) if entrada != id_vendedor else None,
                "entrou_em": entrou_em.isoformat(), "fatos": fatos, "entrada": _entrada(retrato),
                "justificativa": justificativa, "veredito": veredito,
                "encerrada": None if em_andamento else {"em": encerrada_em.isoformat(), "motivo": motivo},
                "pode": {"justificar": justifica and em_andamento and not veredito and hoje <= prazo,
                         "veredito": admin and (motivo == "mantido" or (em_andamento and bool(
                             justificativa or veredito or hoje > prazo)))},
                "anteriores": anteriores.get(id_cliente, 0),
            })
        return {
            "ativo": True, "aviso": None, "ligada": cfg["ligada"], "data_ref": data_ref,
            "dia": cache.dia_da_copia().isoformat(), "hoje": hoje.isoformat(), "admin": admin,
            "pode_justificar": justifica,
            "rodada": None if not escolhido else {**rodada(escolhido), "dias_para_o_prazo": (
                (meses[escolhido] - hoje).days if meses[escolhido] >= hoje else None)},
            "rodadas": [rodada(m) for m, _ in rodadas],
            "pendencias": [{"mes": f"{m:%Y-%m}", "rotulo": rotulo_mes(m), "sem_veredito": sem, "aguardando_erp": erp}
                           for m, sem, erp in pendencias if sem or erp],
            "regras": {"dias": cfg["dias"], "prazo_dia_util": cfg["prazo_dia_util"],
                       "central": [self._nome(nomes, v) for v in cfg["central"]]},
            "vendedores": sorted(vendedores.values(), key=lambda v: (v["equipe"] or "", v["nome"].lower())),
            "itens": itens, "avisos": avisos,
        }

    def historico(self, usuario: dict, ids, cliente) -> dict:
        """Todas as sugestões de um cliente (dos meses mais novos para os mais antigos), com cada justificativa e cada
        veredito em ordem. Só as dos vendedores do acesso (ids; None = todos); sem nenhuma -> NaoEncontrada."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        try:
            cliente = int(cliente)
        except (TypeError, ValueError):
            raise ValueError("escolha um cliente") from None
        nomes = self.nomes()
        with self.banco.conexao() as con:
            linhas = self._linhas(con, "s.id_cliente = %s", [cliente], ids)
            if not linhas:
                raise NaoEncontrada("este cliente não tem sugestões nos vendedores do seu acesso")
            eventos: dict[int, list] = {}
            for id_, sugestao, tipo, decisao, texto, retrato, em, por in con.execute(
                    "SELECT id, sugestao, tipo, decisao, texto, retrato, criado_em, criado_por_nome FROM manejo_eventos "
                    "WHERE sugestao = ANY(%s) ORDER BY id", [[x[0] for x in linhas]]):
                eventos.setdefault(sugestao, []).append({
                    "id": id_, "tipo": tipo, "decisao": decisao, "texto": texto, "por": por or "usuário excluído",
                    "em": hora(em), "dias_sem_compra": retrato.get("dias_sem_compra"),
                    "ultima_compra": retrato.get("ultima_compra")})
        return {
            "cliente": {"id": cliente, "nome": linhas[-1][3]},
            "sugestoes": [{
                "id": x[0], "mes": f"{x[1]:%Y-%m}", "rotulo": rotulo_mes(x[1]), "sugestao": x[4],
                "entrou_em": x[8].isoformat(), "vendedor": self._nome(nomes, x[5], x[6]), "entrada": _entrada(x[9]),
                "encerrada": None if x[12] is None else {"em": x[11].isoformat(), "motivo": x[12]},
                "eventos": eventos.get(x[0], []),
            } for x in sorted(linhas, key=lambda x: (x[1], x[0]), reverse=True)],
        }

    # --- respostas ------------------------------------------------------------------------
    @staticmethod
    def _corpo(corpo: dict, justificativa: bool) -> tuple[str, str, list[tuple[int, int]]]:
        """{itens: [{id, versao}], decisao, texto} -> (decisao, texto, [(id, versao)]); ValueError com a explicação."""
        corpo = corpo if isinstance(corpo, dict) else {}
        decisao = corpo.get("decisao")
        if decisao not in DECISOES:
            raise ValueError("escolha a resposta")
        texto = str(corpo.get("texto") or "").strip()
        if len(texto) > MAX_TEXTO:
            raise ValueError(f"o texto passou de {MAX_TEXTO} letras")
        if justificativa and decisao == "manter" and len(texto) < MIN_TEXTO:
            raise ValueError(f"escreva por que o cliente deve continuar (pelo menos {MIN_TEXTO} letras)")
        itens = corpo.get("itens")
        if not isinstance(itens, list) or not itens:
            raise ValueError("marque ao menos um cliente")
        if len(itens) > MAX_ITENS:
            raise ValueError(f"marque até {MAX_ITENS} clientes de cada vez")
        try:
            saida = [(int(i["id"]), int(i.get("versao") or 0)) for i in itens]
        except (TypeError, ValueError, KeyError, AttributeError):
            raise ValueError("a lista mudou; atualize a página") from None
        if len({i for i, _ in saida}) != len(saida):
            raise ValueError("há cliente repetido na lista; atualize a página")
        return decisao, texto, saida

    @staticmethod
    def _para_mudar(con, ids: list[int]) -> dict[int, dict]:
        """As sugestões que vão receber uma resposta, travadas, com a última justificativa, o último veredito e a
        versão (o último evento)."""
        campos = ("id", "id_cliente", "cliente", "sugestao", "id_vendedor", "fatos", "motivo", "prazo")
        linhas = {r[0]: {**dict(zip(campos, r)), "versao": 0, "justificativa": None, "veredito": None}
                  for r in con.execute(
                      "SELECT s.id, s.id_cliente, s.cliente, s.sugestao, s.id_vendedor, s.fatos, s.encerrada_motivo, "
                      "r.prazo FROM manejo_sugestoes s JOIN manejo_rodadas r ON r.mes = s.mes WHERE s.id = ANY(%s) "
                      "FOR UPDATE OF s", [ids])}
        for sugestao, tipo, id_, decisao, texto, por in con.execute(
                "SELECT DISTINCT ON (sugestao, tipo) sugestao, tipo, id, decisao, texto, criado_por FROM manejo_eventos "
                "WHERE sugestao = ANY(%s) ORDER BY sugestao, tipo, id DESC", [ids]):
            linhas[sugestao][tipo] = {"id": id_, "decisao": decisao, "texto": texto, "por": por}
            linhas[sugestao]["versao"] = max(linhas[sugestao]["versao"], id_)
        return linhas

    @staticmethod
    def _gravar(con, sugestao: int, tipo: str, decisao: str, texto: str, fatos: dict, usuario: dict) -> None:
        con.execute(
            "INSERT INTO manejo_eventos (sugestao, tipo, decisao, texto, retrato, criado_por, criado_por_nome) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, (SELECT id FROM usuarios WHERE id = %s), %s)",
            [sugestao, tipo, decisao, texto, json.dumps(fatos, ensure_ascii=False), usuario["id"], usuario["nome"]])

    def justificar(self, usuario: dict, ids, corpo: dict) -> dict:
        """A resposta de quem pode justificar para um ou vários clientes: {itens: [{id, versao}], decisao, texto}.
        Quem mudou de situação enquanto a pessoa olhava (saiu da lista, ganhou veredito, o prazo passou, outra pessoa
        respondeu) é pulado e volta em recusados; um cliente de vendedor fora do acesso recusa o pedido inteiro
        (PermissionError). A mesma resposta de novo não grava outra linha. Devolve {gravados, recusados}."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        if not pode_justificar(usuario):
            raise PermissionError("seu acesso não está marcado para justificar no Manejo da Base")
        decisao, texto, itens = self._corpo(corpo, justificativa=True)
        hoje = self._hoje()
        gravados, recusados = 0, []
        with self.banco.conexao() as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA])
            linhas = self._para_mudar(con, [i for i, _ in itens])
            if ids is not None and any(x["id_vendedor"] not in ids for x in linhas.values()):
                raise PermissionError("há clientes de vendedores fora do seu acesso; atualize a página")
            for id_, versao in itens:
                x = linhas.get(id_)
                if x is None:
                    recusa = "não está mais na lista; atualize a página"
                elif x["versao"] != versao:
                    recusa = "mudou enquanto você olhava; confira de novo"
                elif x["motivo"] in SAIDAS:
                    recusa = f"saiu da lista: {SAIDAS[x['motivo']]}"
                elif x["motivo"] or x["veredito"]:
                    recusa = "já tem veredito"
                elif hoje > x["prazo"]:
                    recusa = f"o prazo terminou em {x['prazo']:%d/%m}"
                else:
                    recusa = None
                if recusa:
                    recusados.append({"id": id_, "cliente": x and x["cliente"], "motivo": recusa})
                    continue
                j = x["justificativa"]
                if not (j and (j["decisao"], j["texto"], j["por"]) == (decisao, texto, usuario["id"])):
                    self._gravar(con, id_, "justificativa", decisao, texto, x["fatos"], usuario)
                gravados += 1
        return {"gravados": gravados, "recusados": recusados}

    def veredito(self, usuario: dict, corpo: dict) -> dict:
        """O veredito do administrador para um ou vários clientes: {itens: [{id, versao}], decisao, texto}. Precisa
        haver justificativa ou o prazo ter passado. "manter" encerra a sugestão; "seguir" a deixa esperando o ERP.
        Dá para trocar depois (uma linha nova no histórico), menos o que o ERP já mostra como feito; trocar "manter" por
        "seguir" reabre a sugestão, salvo se o cliente já tem outra em andamento. Devolve {gravados, recusados}."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        if not eh_admin(usuario):
            raise PermissionError("só administradores dão o veredito")
        decisao, texto, itens = self._corpo(corpo, justificativa=False)
        hoje = self._hoje()
        gravados, recusados = 0, []
        with self.banco.conexao() as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA])
            linhas = self._para_mudar(con, [i for i, _ in itens])
            for id_, versao in itens:
                x = linhas.get(id_)
                reabrir = bool(x) and x["motivo"] == "mantido" and decisao == "seguir"
                if x is None:
                    recusa = "não está mais na lista; atualize a página"
                elif x["versao"] != versao:
                    recusa = "mudou enquanto você olhava; confira de novo"
                elif x["motivo"] == "aplicado":
                    recusa = "o ERP já mostra como feito"
                elif x["motivo"] in SAIDAS:
                    recusa = f"saiu da lista: {SAIDAS[x['motivo']]}"
                elif x["motivo"] is None and not x["justificativa"] and not x["veredito"] and hoje <= x["prazo"]:
                    recusa = f"ainda sem justificativa: dá para justificar até {x['prazo']:%d/%m}"
                elif reabrir and con.execute(
                        "SELECT 1 FROM manejo_sugestoes WHERE id_cliente = %s AND encerrada_em IS NULL AND id <> %s",
                        [x["id_cliente"], id_]).fetchone():
                    recusa = "o cliente já está em outra lista em andamento"
                else:
                    recusa = None
                if recusa:
                    recusados.append({"id": id_, "cliente": x and x["cliente"], "motivo": recusa})
                    continue
                v = x["veredito"]
                if not (v and (v["decisao"], v["texto"]) == (decisao, texto)):
                    self._gravar(con, id_, "veredito", decisao, texto, x["fatos"], usuario)
                    if decisao == "manter" and x["motivo"] is None:
                        con.execute("UPDATE manejo_sugestoes SET encerrada_em = %s, encerrada_motivo = 'mantido' "
                                    "WHERE id = %s", [hoje, id_])
                    elif reabrir:
                        con.execute("UPDATE manejo_sugestoes SET encerrada_em = NULL, encerrada_motivo = NULL "
                                    "WHERE id = %s", [id_])
                gravados += 1
        self._chave = None  # um veredito muda quem está em andamento: a próxima leitura atualiza a lista
        return {"gravados": gravados, "recusados": recusados}

    # --- a configuração -------------------------------------------------------------------
    def config_dados(self) -> dict:
        """Para Manejo da Base › Configurar: as regras, o padrão, os vendedores da campanha (os das equipes, com os
        clientes ativos de cada um e se o nome do ERP diz que é da central) e o prazo da lista aberta agora."""
        cfg = self.config.atual()
        cache = self.calc.cache
        vendedores, prazo = [], None
        if cache.pronto():
            regras = self.calc.regras()
            nomes = self.nomes()
            erp = dict(cache.consulta("SELECT id, nome FROM vendedores"))
            ativos = {} if cache.antigo or cache.sem_detalhe else dict(cache.consulta(
                "SELECT c.id_vendedor, COUNT(*) FROM clientes c JOIN clientes_detalhes d ON d.id = c.id "
                "WHERE COALESCE(d.inativo, 1) = 0 GROUP BY 1"))
            for v, equipe in self._equipes(regras).items():
                if ativos.get(v) or v in cfg["central"]:
                    vendedores.append({"id": v, "nome": self._nome(nomes, v, erp.get(v)), "equipe": equipe,
                                       "clientes": ativos.get(v, 0),
                                       "nome_central": "CENTRAL" in str(erp.get(v) or "").upper()})
            vendedores.sort(key=lambda v: (v["equipe"], v["nome"].lower()))
            hoje, cal = self._hoje(), self.calc.calendario(regras)
            mes = hoje.replace(day=1)
            data = prazo_do_mes(cal, mes.year, mes.month, cfg["prazo_dia_util"])
            if data < hoje:
                mes = _mes_seguinte(mes)
                data = prazo_do_mes(cal, mes.year, mes.month, cfg["prazo_dia_util"])
            prazo = {"mes": f"{mes:%Y-%m}", "rotulo": rotulo_mes(mes), "data": data.isoformat()}
        return {"ativo": self.ativo, "config": cfg, "padrao": _valida(PADRAO), "vendedores": vendedores, "prazo": prazo,
                "data_ref": cache.info.get("data_ref")}

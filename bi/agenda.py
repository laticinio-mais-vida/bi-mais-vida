"""Agenda de cada pessoa, no topo da página Gestão: atividades únicas ou repetidas e o que foi feito em cada dia.
As tarefas com prazo, divididas com outras pessoas, ficam em bi/tarefas.py (a mesma agenda mostra as duas).

- Quem vê: quem criou a atividade e quem faz (agenda_atividade_pessoas, migração 048), como as pessoas da tarefa.
  Todo método recebe o id do usuário e filtra por ele; para as outras pessoas, a atividade não existe (NaoEncontrada),
  e quem vê mas não pode fazer algo recebe PermissionError, com o motivo.
- Quem faz: quem cria escolhe as pessoas (quem tem a página Gestão), com ou sem autonomia, e se ele mesmo faz (sem
  outras pessoas, faz). Cada pessoa tem o próprio check e o próprio feedback em cada dia, e todos veem os de todos.
  Quem criou edita, muda as pessoas, encerra, exclui e marca (ou desfaz) o dia no lugar de quem faz; o feedback de
  quem concluiu, só ela muda. Com autonomia, a pessoa edita a atividade (o título, a descrição, os dias e o horário,
  para todos). Quem entra numa atividade que já começou faz dali em diante (desde): os dias de antes não são dela.
- Nos dias: quem faz vê a atividade nos dias dele, com o andamento dos outros; quem criou, em todo dia em que alguém
  faz, contando um por pessoa (como as subtarefas dos outros na agenda dele).
- Sino (bi/notificacoes.py): quem entra ou ganha a autonomia, todos quando os dias ou o horário mudam ou a atividade é
  encerrada, e quem criou quando alguém conclui o próprio dia.
- Repetição (ocorre): única (só no dia do início ou, com o último dia, todos os dias do início ao fim: a de vários
  dias, migração 026), diária (todo dia, ou só os dias úteis de uma região, com os feriados e os extras de
  Configurações, bi/calendario.py), semanal (dias da semana escolhidos), mensal (um dia fixo, e o mês sem esse dia usa o
  último; ou um dia útil do mês, migração 043: o N-ésimo do começo ou, contando do fim, o último ou o dia em que faltam
  N dias úteis, ele incluído, no calendário de uma região) ou a cada N dias desde o início. A repetida pode ter um último dia (fim). O horário é opcional (migração
  019), com o fim também opcional (migração 026): no dia, as com horário vêm primeiro, em ordem.
- Horário ocupado (migração 026): a atividade com começo e fim marcada como ocupada trava o horário de cada pessoa que
  faz, nos dias em que acontece, de hoje em diante. Ninguém marca para ela outra atividade que cruze esse horário, nem
  quem cria tarefas põe a pessoa numa tarefa ou subtarefa com horário dentro dele (conferir_atividade e
  conferir_pontos, que bi/tarefas.py também usa); marcar como ocupado é recusado se a pessoa já tem algo com horário
  ali. A mensagem sobre o horário de outra pessoa não diz o título.
- Concluir grava o registro do dia (agenda_registros, migração 018) com o feedback, obrigatório quando a atividade
  exige feedback. Só até hoje; concluir de novo troca o feedback. A repetida junta um registro por dia: o histórico.
- Editar a atividade não apaga o que já foi feito: o registro de um dia que deixou de ocorrer continua aparecendo.
- Assistente (ContextoAgenda): lê a agenda de quem pergunta (periodo, historico; com as atividades que outra pessoa
  criou para ele) e monta propostas (propor: criar, só para ele; editar, encerrar, excluir ou concluir, com as mesmas
  permissões da página), sem gravar. Quem grava é o botão da resposta (aplicar), uma vez só por proposta
  (agenda_propostas, migração 019).
- Google Agenda (bi/google_agenda.py, migração 031): o evento ocupado no Google da pessoa trava o horário dela para as
  tarefas e subtarefas dos outros (conferir_pontos) e só avisa a própria pessoa (avisos, nas atividades e nas tarefas
  dela). Na atividade que outra pessoa marca para ela, só avisa quem grava, sem o título (avisos_google): a que se
  repete esbarraria quase sempre em algum evento. O Assistente lê os eventos do Google de quem pergunta junto com a
  agenda (periodo), só para ver.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import unicodedata
import uuid

from .banco import Banco, hora
from .calendario import REGIOES, UM_DIA, Calendario
from .conversas import NaoEncontrada, id_valido
from .notificacoes import avisar

REPETICOES = ("nenhuma", "diaria", "semanal", "mensal", "intervalo")
ACOES = ("criar", "editar", "encerrar", "excluir", "concluir")
MAX_TITULO = 120
MAX_TEXTO = 2000
MAX_PESSOAS = 30  # quem faz a atividade, sem quem criou (como os participantes da tarefa)
# Quem pode fazer uma atividade ou participar de uma tarefa: os usuários ativos com a página Gestão, onde fica a agenda
# (o administrador tem todas).
COM_GESTAO = "ativo AND (papel = 'admin' OR 'gestao' = ANY(coalesce(paginas, '{}')))"
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro",
         "Novembro", "Dezembro"]
MAX_DIA_UTIL = 23  # o dia útil do mês da mensal vai até o 23º (do começo ou do fim); o mês com menos usa o mais perto
MAX_FALTAS = 30   # dias sem conclusão que o histórico lista (os mais recentes)
MAX_PERIODO = 93  # dias que o Assistente lê de uma vez
HORIZONTE = 366   # dias à frente que o horário ocupado confere entre duas atividades que se repetem sem fim
TRAVA_HORARIOS = 7_240_102  # pg_advisory_xact_lock(TRAVA_HORARIOS, pessoa): uma gravação com horário por pessoa por vez
MAX_AVISOS = 3  # eventos do Google citados no aviso de uma atividade (os outros, "e mais N")
MAX_GOOGLE_IA = 200  # eventos do Google que o Assistente lê de uma vez (cada um custa tokens)
NOME_DIA = ["", "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]  # date.isoweekday()
_GRAVAR = ("titulo", "descricao", "inicio", "hora", "hora_fim", "ocupado", "repeticao", "dias_semana", "dia_mes",
           "dia_util", "intervalo", "so_dias_uteis", "regiao", "fim", "exige_feedback")
# O que decide os dias e os horários da atividade: editar só confere o horário ocupado se algo disso mudou.
_QUANDO = ("inicio", "fim", "hora", "hora_fim", "ocupado", "repeticao", "dias_semana", "dia_mes", "dia_util", "intervalo",
           "so_dias_uteis", "regiao")
_CAMPOS = ("id", *_GRAVAR)
_VALORES = ", ".join(f"%({c})s::smallint[]" if c == "dias_semana" else f"%({c})s" for c in _GRAVAR)
_HORA = re.compile(r"^(\d{1,2})(?::|h)(\d{2})?(?::00)?$")
_TOTAL = {"feita": "feitas", "atrasada": "atrasadas", "hoje": "hoje", "prevista": "previstas"}
_NAO_ACHOU = "atividade não encontrada; ela pode ter sido excluída ou você não faz mais parte dela"
# A atividade com quem criou e quem faz (_carregar).
_A = ", ".join(f"a.{c}" for c in _CAMPOS)
# As atividades que a pessoa vê (criou ou faz) com algo entre de e ate: acontecem no período ou têm um dia feito nele.
_VISIVEIS = """SELECT a.id FROM agenda_atividades a
WHERE (a.usuario = %(u)s OR EXISTS (SELECT 1 FROM agenda_atividade_pessoas p WHERE p.atividade = a.id AND p.usuario = %(u)s))
  AND ((a.inicio <= %(ate)s AND (a.fim IS NULL OR a.fim >= %(de)s))
       OR EXISTS (SELECT 1 FROM agenda_registros r WHERE r.atividade = a.id AND r.dia BETWEEN %(de)s AND %(ate)s))
ORDER BY a.id"""


def _texto(valor, campo: str, maximo: int = MAX_TEXTO) -> str:
    t = str(valor or "").strip()
    if len(t) > maximo:
        raise ValueError(f"{campo} pode ter até {maximo} caracteres")
    return t


def _data(valor, campo: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(valor or "")[:10])
    except ValueError:
        raise ValueError(f"a data {campo} deve ser AAAA-MM-DD (veio {valor!r})") from None


def _hora(valor) -> dt.time | None:
    """'09:00', '9:30' ou '14h' em hora; vazio = sem horário."""
    if valor in (None, ""):
        return None
    if isinstance(valor, dt.time):
        return valor
    m = _HORA.match(str(valor).strip().lower())
    if not m or int(m[1]) > 23 or int(m[2] or 0) > 59:
        raise ValueError(f"o horário deve ser HH:MM (veio {valor!r})")
    return dt.time(int(m[1]), int(m[2] or 0))


def _hhmm(h: dt.time | None) -> str | None:
    return h.strftime("%H:%M") if h else None


def _faixa(h: dt.time, fim: dt.time | None) -> str:
    """'14:00–15:00' ou, sem o fim, '14:00'."""
    return f"{_hhmm(h)}–{_hhmm(fim)}" if fim else _hhmm(h)


def _inteiro(valor, campo: str, minimo: int, maximo: int) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"informe {campo}") from None
    if not minimo <= n <= maximo:
        raise ValueError(f"{campo} vai de {minimo} a {maximo}")
    return n


def _id(valor, nao_achou: str = _NAO_ACHOU) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise NaoEncontrada(nao_achou) from None
    if not 0 < n < 2 ** 63:
        raise NaoEncontrada(nao_achou)
    return n


def _mes(texto, hoje: dt.date) -> tuple[int, int]:
    """'2026-10' em (ano, mês); vazio = o mês de hoje."""
    if not texto:
        return hoje.year, hoje.month
    try:
        ano, mes = (int(p) for p in str(texto).split("-"))
    except ValueError:
        raise ValueError(f"o mês deve ser AAAA-MM (veio {texto!r})") from None
    if not (2000 <= ano <= 2100 and 1 <= mes <= 12):
        raise ValueError(f"mês inválido: {texto!r}")
    return ano, mes


def _chave(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(c if c.isalnum() else " " for c in t).split())


def _titulo(valor, de: str = "da atividade", maximo: int = MAX_TITULO) -> str:
    """O título sem espaços sobrando; obrigatório."""
    titulo = " ".join(str(valor or "").split())
    if not titulo:
        raise ValueError(f"escreva o título {de}")
    if len(titulo) > maximo:
        raise ValueError(f"o título pode ter até {maximo} caracteres")
    return titulo


def _curto(texto: str, maximo: int = MAX_TITULO) -> str:
    """O texto numa mensagem ou num aviso do sino: o que passa de maximo (o título longo de uma subtarefa) é cortado,
    com “…”."""
    return texto if len(texto) <= maximo else texto[:maximo - 1].rstrip() + "…"


def _valida(dados: dict) -> dict:
    """A atividade como vai para o banco, com só os campos da repetição escolhida."""
    titulo = _titulo(dados.get("titulo"))
    repeticao = dados.get("repeticao") or "nenhuma"
    if repeticao not in REPETICOES:
        raise ValueError(f"repetição desconhecida: {repeticao!r}")
    a = {"titulo": titulo, "descricao": _texto(dados.get("descricao"), "a descrição"),
         "inicio": _data(dados.get("inicio"), "da atividade"), "hora": _hora(dados.get("hora")),
         "hora_fim": _hora(dados.get("hora_fim")), "ocupado": bool(dados.get("ocupado")),
         "repeticao": repeticao, "dias_semana": None, "dia_mes": None, "dia_util": None, "intervalo": None,
         "so_dias_uteis": False,
         "regiao": None, "fim": None, "exige_feedback": bool(dados.get("exige_feedback"))}
    if a["hora_fim"] and not a["hora"]:
        raise ValueError("diga a que horas a atividade começa, antes do fim do horário")
    if a["hora_fim"] and a["hora_fim"] <= a["hora"]:
        raise ValueError("o fim do horário tem de ser depois do começo (a atividade não passa da meia-noite)")
    if a["ocupado"] and not a["hora_fim"]:
        raise ValueError("para marcar o horário como ocupado, diga a que horas ele começa e termina")
    if repeticao == "semanal":
        try:
            dias = sorted({int(d) for d in dados.get("dias_semana") or []})
        except (TypeError, ValueError):
            raise ValueError("dias da semana inválidos") from None
        if not dias:
            raise ValueError("escolha ao menos um dia da semana")
        if dias[0] < 1 or dias[-1] > 7:
            raise ValueError("os dias da semana vão de 1 (segunda) a 7 (domingo)")
        a["dias_semana"] = dias
    elif repeticao == "mensal" and dados.get("dia_util") not in (None, ""):
        n = _inteiro(dados.get("dia_util"), "o dia útil do mês", -MAX_DIA_UTIL, MAX_DIA_UTIL)
        if n == 0:
            raise ValueError("o dia útil do mês conta a partir de 1 (do começo ou do fim do mês)")
        if dados.get("regiao") not in REGIOES:
            raise ValueError("escolha o calendário dos dias úteis: ES ou BA")
        a["dia_util"], a["so_dias_uteis"], a["regiao"] = n, True, dados["regiao"]
    elif repeticao == "mensal":
        a["dia_mes"] = _inteiro(dados.get("dia_mes"), "o dia do mês", 1, 31)
    elif repeticao == "intervalo":
        a["intervalo"] = _inteiro(dados.get("intervalo"), "o intervalo em dias", 2, 365)
    elif repeticao == "diaria" and dados.get("so_dias_uteis"):
        if dados.get("regiao") not in REGIOES:
            raise ValueError("escolha o calendário dos dias úteis: ES ou BA")
        a["so_dias_uteis"], a["regiao"] = True, dados["regiao"]
    if dados.get("fim"):  # na única, o último dia de uma atividade de vários dias
        a["fim"] = _data(dados["fim"], "do último dia")
        if a["fim"] < a["inicio"]:
            raise ValueError("o último dia não pode ser antes do início")
        if repeticao == "nenhuma" and a["fim"] == a["inicio"]:
            a["fim"] = None
    return a


def ocorre(a: dict, dia: dt.date, cal: Calendario | None = None) -> bool:
    """A atividade acontece neste dia? cal: o calendário dos dias úteis (só as com so_dias_uteis usam: a diária e a
    mensal num dia útil)."""
    if dia < a["inicio"] or (a["fim"] and dia > a["fim"]):
        return False
    repeticao = a["repeticao"]
    if repeticao == "nenhuma":  # com o último dia, todos os dias do início ao fim
        return a["fim"] is not None or dia == a["inicio"]
    if repeticao == "diaria":
        return not a["so_dias_uteis"] or cal.dia(dia, a["regiao"])["peso"] > 0
    if repeticao == "semanal":
        return dia.isoweekday() in a["dias_semana"]
    if repeticao == "mensal" and a.get("dia_util"):
        return dia == dia_util_do_mes(cal, dia.year, dia.month, a["regiao"], a["dia_util"])
    if repeticao == "mensal":
        return dia.day == min(a["dia_mes"], calendar.monthrange(dia.year, dia.month)[1])
    return (dia - a["inicio"]).days % a["intervalo"] == 0


def dia_util_do_mes(cal: Calendario, ano: int, mes: int, regiao: str, n: int) -> dt.date | None:
    """O n-ésimo dia útil do mês (n > 0, do começo) ou, com n < 0, contando do fim (-1 = o último). O mês com menos
    dias úteis que isso usa o último (do começo) ou o primeiro (do fim); o mês sem nenhum, nenhum dia."""
    uteis = cal.dias_uteis(ano, mes, regiao)
    if not uteis:
        return None
    return uteis[min(n, len(uteis)) - 1] if n > 0 else uteis[max(len(uteis) + n, 0)]


def ajuste_dia_util(a: dict, dia: dt.date, cal: Calendario | None) -> str | None:
    """O aviso do mês com menos dias úteis que o pedido, no dia para onde a mensal num dia útil foi (None: sem
    ajuste): 'Novembro tem só 19 dias úteis (ES): o 22º dia útil passou para o último, 30/11'."""
    n = a.get("dia_util") if a["repeticao"] == "mensal" else None
    if not n or cal is None:
        return None
    uteis = cal.dias_uteis(dia.year, dia.month, a["regiao"])
    if len(uteis) >= abs(n) or dia not in (uteis[-1:] if n > 0 else uteis[:1]):
        return None
    pedido = f"o {n}º dia útil passou para o último" if n > 0 else \
        f"faltando {-n} dias úteis passou para o primeiro dia útil"
    return f"{MESES[dia.month - 1]} tem só {len(uteis)} dias úteis ({a['regiao']}): {pedido}, {dia:%d/%m}"


def texto_dia_util(n: int) -> str:
    """'3º dia útil do mês', 'Último dia útil do mês', 'Faltando 5 dias úteis para acabar o mês'."""
    if n > 0:
        return f"{n}º dia útil do mês"
    return "Último dia útil do mês" if n == -1 else f"Faltando {-n} dias úteis para acabar o mês"


def _dm(dia: dt.date, hoje: dt.date) -> str:
    return f"{dia:%d/%m}" if dia.year == hoje.year else f"{dia:%d/%m/%Y}"


def _lista_e(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else f"{', '.join(itens[:-1])} e {itens[-1]}"


def texto_repeticao(a: dict, hoje: dt.date) -> str:
    """'Só neste dia', 'De 10/11 a 14/11', 'Todo dia útil (ES)', 'Toda segunda e quinta', 'Todo dia 5', 'Todo mês:
    3º dia útil (ES)', 'A cada 15 dias' (e 'até 30/11')."""
    repeticao = a["repeticao"]
    if repeticao == "nenhuma":
        if a["fim"] and a["fim"] > a["inicio"]:
            return f"De {_dm(a['inicio'], hoje)} a {_dm(a['fim'], hoje)}"
        t = "Só neste dia"
    elif repeticao == "diaria":
        t = f"Todo dia útil ({a['regiao']})" if a["so_dias_uteis"] else "Todo dia"
    elif repeticao == "semanal":
        dias, nomes = a["dias_semana"], _lista_e([NOME_DIA[d] for d in a["dias_semana"]])
        t = ("Todo dia da semana" if len(dias) == 7 else f"Toda {nomes}" if max(dias) <= 5
             else f"Todo {nomes}" if min(dias) >= 6 else f"Semanal: {nomes}")
    elif repeticao == "mensal" and a.get("dia_util"):
        n = a["dia_util"]
        t = (f"Todo mês: {n}º dia útil" if n > 0 else "Todo mês: último dia útil" if n == -1
             else f"Todo mês: faltando {-n} dias úteis para acabar") + f" ({a['regiao']})"
    elif repeticao == "mensal":
        t = f"Todo dia {a['dia_mes']}" + (" (ou o último do mês)" if a["dia_mes"] > 28 else "")
    else:
        t = f"A cada {a['intervalo']} dias"
    return f"{t}, até {_dm(a['fim'], hoje)}" if a["fim"] else t


def _publica(a: dict, hoje: dt.date) -> dict:
    """Os campos da atividade (sem as pessoas), como a página e o Assistente veem."""
    return {**{c: a[c] for c in _CAMPOS if c in a}, "inicio": a["inicio"].isoformat(),
            "fim": a["fim"].isoformat() if a["fim"] else None, "hora": _hhmm(a["hora"]),
            "hora_fim": _hhmm(a["hora_fim"]), "quando": texto_repeticao(a, hoje)}


# --- quem faz ---------------------------------------------------------------------------------------------------------
def _pessoa(valor) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"pessoa inválida: {valor!r}") from None


def _valida_pessoas(dados: dict, criador: int) -> tuple[dict[int, bool], bool] | None:
    """Quem faz a atividade, como no formulário: os participantes {id: autonomia}, sem quem criou, e se quem criou
    também faz (eu_faz; sem dizer, faz). None: os dados não falam das pessoas (a edição deixa como estão)."""
    if "participantes" not in dados and "eu_faz" not in dados:
        return None
    participantes = {}
    for p in dados.get("participantes") or []:
        id_ = _pessoa(p.get("id") if isinstance(p, dict) else p)
        if id_ != criador:
            participantes[id_] = isinstance(p, dict) and bool(p.get("autonomia"))
    if len(participantes) > MAX_PESSOAS:
        raise ValueError(f"a atividade pode ter até {MAX_PESSOAS} pessoas, além de você")
    eu_faz = dados.get("eu_faz") is not False
    if not eu_faz and not participantes:
        raise ValueError("escolha quem faz a atividade: você ou outra pessoa")
    return participantes, eu_faz


def conferir_pessoas(con, ids, o_que: str = "entrar na atividade") -> None:
    """Quem entra precisa estar ativo e ter a página Gestão (onde fica a agenda)."""
    ids = sorted(set(ids))
    if not ids:
        return
    achados = {r[0] for r in con.execute(f"SELECT id FROM usuarios WHERE id = ANY(%s::bigint[]) AND {COM_GESTAO}",
                                         [ids])}
    if any(i not in achados for i in ids):
        raise ValueError(f"pessoa não encontrada, inativa ou sem a página Gestão (onde fica a agenda) não pode "
                         f"{o_que}")


def _carregar(con, ids, travar: bool = False) -> list[dict]:
    """As atividades (pelo id), cada uma com quem criou (criador, criador_nome) e quem faz (pessoas, pelo nome: id,
    nome, autonomia e desde). travar: trava as atividades até o fim da transação."""
    ids = list(ids)
    if not ids:
        return []
    atividades = {r[0]: {**dict(zip(_CAMPOS, r)), "criador": r[-2], "criador_nome": r[-1], "pessoas": []}
                  for r in con.execute(
                      f"SELECT {_A}, a.usuario, u.nome FROM agenda_atividades a JOIN usuarios u ON u.id = a.usuario "
                      "WHERE a.id = ANY(%s::bigint[]) ORDER BY a.id" + (" FOR UPDATE OF a" if travar else ""), [ids])}
    for atividade, usuario, nome, autonomia, desde in con.execute(
            "SELECT p.atividade, p.usuario, u.nome, p.autonomia, p.desde FROM agenda_atividade_pessoas p "
            "JOIN usuarios u ON u.id = p.usuario WHERE p.atividade = ANY(%s::bigint[]) ORDER BY lower(u.nome), u.id",
            [list(atividades)]):
        atividades[atividade]["pessoas"].append({"id": usuario, "nome": nome, "autonomia": autonomia, "desde": desde})
    return list(atividades.values())


def _papel(a: dict, eu: int) -> dict:
    """O que eu sou na atividade: quem criou, quem faz, com autonomia (só quem não criou) e se vê (um dos dois)."""
    minha = next((p for p in a["pessoas"] if p["id"] == eu), None)
    criador = a["criador"] == eu
    return {"criador": criador, "faz": minha is not None, "autonomia": not criador and bool(minha and minha["autonomia"]),
            "ve": criador or minha is not None}


def _entrou(p: dict, dia: dt.date) -> bool:
    """O dia é da pessoa p? Quem entrou depois do começo faz a partir do dia em que entrou."""
    return p["desde"] is None or dia >= p["desde"]


def _publica_para(a: dict, eu: int, hoje: dt.date) -> dict:
    """A atividade como a agenda de `eu` vê: os campos, quem criou, quem faz e o que ele pode fazer nela."""
    papel = _papel(a, eu)
    return {**_publica(a, hoje), "criador": {"id": a["criador"], "nome": a["criador_nome"]},
            "eu_criador": papel["criador"], "faz": papel["faz"], "minha_autonomia": papel["autonomia"],
            "pessoas": [{"id": p["id"], "nome": p["nome"], "autonomia": p["autonomia"],
                         "desde": p["desde"] and p["desde"].isoformat()} for p in a["pessoas"]],
            "pode": {"editar": papel["criador"] or papel["autonomia"], "pessoas": papel["criador"],
                     "encerrar": papel["criador"], "excluir": papel["criador"], "concluir_outros": papel["criador"]}}


def _registro(r: dict | None, pessoa: int) -> dict:
    """O dia de uma pessoa (r: o registro, ou None se ela não concluiu); concluida_por: quem marcou, se foi outra."""
    if r is None:
        return {"feita": False, "feedback": None, "concluida_em": None, "concluida_por": None}
    return {"feita": True, "feedback": r["feedback"], "concluida_em": hora(r["concluida_em"]),
            "concluida_por": ({"id": r["por"], "nome": r["por_nome"]} if r["por"] not in (None, pessoa) else None)}


def _item(i: dict, eu: int) -> dict:
    """Um item do dia (de Agenda._dias) como a agenda de `eu` vê: feita, feedback e concluida_em são os dele (eu_faz:
    o dia é dele; de quem criou e não faz, feita quando todos fizeram); pessoas, o dia de cada pessoa; conta e feitas,
    quanto ele conta no dia (quem criou, um por pessoa; quem faz, só o dele)."""
    quem, feitos = i["quem"], i["feitos"]
    criador = i["a"]["criador"] == eu
    meu = (_registro(feitos.get(eu), eu) if i["eu_faz"]
           else {**_registro(None, eu), "feita": len(feitos) == len(quem)})
    return {"atividade": i["a"]["id"], **meu, "eu_faz": i["eu_faz"], "conta": len(quem) if criador else 1,
            "feitas": len(feitos) if criador else int(eu in feitos),
            "pessoas": [{"id": p, **_registro(feitos.get(p), p)} for p in quem],
            **({"ajuste": i["ajuste"]} if i["ajuste"] else {})}


def _google_ia(g: dict) -> dict:
    """Um evento do Google (um pedaço de bi/google_agenda.py) para o Assistente, que só lê: o título, o horário (hora
    vazia: vem da meia-noite; hora_fim vazia: vai até ela) e se está ocupado."""
    quando = {"dia_todo": True} if g["dia_todo"] else {"hora": g["hora"], "hora_fim": g["hora_fim"]}
    return {"titulo": g["titulo"], **quando, "ocupado": g["ocupado"]}


def _ordem(a: dict):
    """No dia: as com horário primeiro, pela hora; depois as sem horário, na ordem em que foram criadas."""
    return (a["hora"] is None, a["hora"] or dt.time(), a.get("id") or 0)


def calendario(configuracao) -> Calendario:
    """O calendário dos dias úteis com os feriados extras e os sábados das regras (sem regras, só os automáticos).
    Monte antes de abrir a transação: a primeira leitura das regras usa outra conexão."""
    if configuracao is None:
        return Calendario()
    cal = configuracao.atual()["calendario"]
    return Calendario(cal["extras"], cal["sabado"])


# --- horário ocupado --------------------------------------------------------------------------------------------------
_HORARIOS = ("id", "usuario", "nome", "titulo", "inicio", "fim", "hora", "hora_fim", "ocupado", "repeticao",
             "dias_semana", "dia_mes", "dia_util", "intervalo", "so_dias_uteis", "regiao")


def travar_horarios(con, pessoas) -> None:
    """Uma gravação com horário por pessoa de cada vez, até o fim da transação (em ordem: duas gravações não ficam
    esperando uma pela outra em cruz)."""
    for p in sorted(set(pessoas)):
        con.execute("SELECT pg_advisory_xact_lock(%s::int, %s::int)", [TRAVA_HORARIOS, p])


def _cruzam(h1: dt.time, f1: dt.time | None, h2: dt.time, f2: dt.time | None) -> bool:
    """Os dois horários se cruzam? Sem o fim, o horário é um ponto, que cruza o outro se cai dentro dele (no fim, já
    não). Dois pontos não se cruzam."""
    if f1 and f2:
        return h1 < f2 and h2 < f1
    if f1:
        return h1 <= h2 < f1
    return bool(f2) and h2 <= h1 < f2


def _ultimo_dia(a: dict) -> dt.date | None:
    """O último dia em que a atividade acontece (None: a repetida sem fim)."""
    return a["fim"] or (a["inicio"] if a["repeticao"] == "nenhuma" else None)


def _dia_em_comum(a: dict, b: dict, cal: Calendario, desde: dt.date) -> dt.date | None:
    """O primeiro dia, de desde em diante, em que as duas atividades acontecem (sem fim, até HORIZONTE dias)."""
    dia = max(desde, a["inicio"], b["inicio"])
    ate = min([f for f in (_ultimo_dia(a), _ultimo_dia(b)) if f] + [dia + dt.timedelta(HORIZONTE)])
    while dia <= ate:
        if ocorre(a, dia, cal) and ocorre(b, dia, cal):
            return dia
        dia += UM_DIA
    return None


def _com_horario(con, pessoas, desde: dt.date, so_ocupadas: bool, ignorar: int | None = None) -> list[dict]:
    """As atividades com horário que as pessoas fazem e ainda acontecem de desde em diante (só as ocupadas, se pedido),
    uma linha por pessoa: usuario e nome são de quem faz."""
    return [dict(zip(_HORARIOS, r)) for r in con.execute(
        "SELECT a.id, p.usuario, u.nome, a.titulo, a.inicio, a.fim, a.hora, a.hora_fim, a.ocupado, a.repeticao, "
        "a.dias_semana, a.dia_mes, a.dia_util, a.intervalo, a.so_dias_uteis, a.regiao FROM agenda_atividades a "
        "JOIN agenda_atividade_pessoas p ON p.atividade = a.id JOIN usuarios u ON u.id = p.usuario "
        "WHERE p.usuario = ANY(%(p)s::bigint[]) AND a.hora IS NOT NULL "
        "AND coalesce(a.fim, CASE a.repeticao WHEN 'nenhuma' THEN a.inicio ELSE 'infinity' END) >= %(desde)s "
        "AND a.id <> %(ignorar)s" + (" AND a.ocupado" if so_ocupadas else "") + " ORDER BY a.inicio, a.hora, a.id",
        {"p": sorted(set(pessoas)), "desde": desde, "ignorar": ignorar or 0})]


def _ocupado_por(b: dict, dia: dt.date, eu: int, hoje: dt.date) -> str:
    """O horário ocupado b em dia: com o título, se é de quem grava; de outra pessoa, sem (a agenda é dela)."""
    if b["usuario"] == eu:
        return f"esse horário está ocupado por “{b['titulo']}” ({_dm(dia, hoje)}, {_faixa(b['hora'], b['hora_fim'])})"
    return (f"{b['nome']} está com o horário ocupado em {_dm(dia, hoje)}, das {_hhmm(b['hora'])} às "
            f"{_hhmm(b['hora_fim'])}")


def conferir_pontos(con, cal: Calendario, hoje: dt.date, pontos: list[tuple], eu: int, google=None) -> list[str]:
    """Os horários de tarefa e subtarefa que entram ou mudam, [(pessoa, dia, hora, o_que)], com o_que como "a
    subtarefa “Estande”": recusa o que cai no horário ocupado da pessoa (de hoje em diante). eu: quem grava.
    google (bi/google_agenda.py): o evento ocupado no Google da pessoa também recusa, se ela é outra pessoa; o de quem
    grava só avisa (devolve os avisos)."""
    pontos = [p for p in pontos if p[2] is not None and p[1] >= hoje]
    if not pontos:
        return []
    ocupadas = _com_horario(con, {p[0] for p in pontos}, hoje, so_ocupadas=True)
    for pessoa, dia, h, o_que in pontos:
        for b in ocupadas:
            if b["usuario"] == pessoa and b["hora"] <= h < b["hora_fim"] and ocorre(b, dia, cal):
                raise ValueError(f"{_ocupado_por(b, dia, eu, hoje)}: mude o horário d{o_que}")
    if google is None:
        return []
    eventos = google.ocupados(con, {p[0] for p in pontos}, min(p[1] for p in pontos), max(p[1] for p in pontos))
    avisos = []
    for pessoa, dia, h, o_que in pontos:
        instante = dt.datetime.combine(dia, h)
        e = next((e for e in eventos if e["usuario"] == pessoa and e["inicio"] <= instante < e["fim"]), None)
        if e is None:
            continue
        p = pedacos(e["inicio"], e["fim"], e["dia_inteiro"], dia, dia)[0]
        if pessoa != eu:
            raise ValueError(f"{_ocupado_google(e['nome'], p, hoje)}: mude o horário d{o_que}")
        aviso = _aviso_google(e["titulo"], p, hoje)
        if aviso not in avisos:
            avisos.append(aviso)
    return avisos


# --- o Google Agenda (bi/google_agenda.py) ----------------------------------------------------------------------------
def pedacos(inicio: dt.datetime, fim: dt.datetime, dia_inteiro: bool, de: dt.date, ate: dt.date) -> list[dict]:
    """Um evento do Google (início e fim locais, sem fuso) cortado nos dias de de a ate: [{dia, hora, hora_fim,
    dia_todo, antes, depois}]. hora None: vem da meia-noite (começou antes); hora_fim None: vai até a meia-noite (ou
    depois). O dia inteiro tem o fim na meia-noite seguinte ao último dia; o de duração zero fica num dia só."""
    primeiro = inicio.date()
    ultimo = (fim - dt.timedelta(microseconds=1)).date() if fim > inicio else primeiro
    saida, dia = [], max(primeiro, de)
    while dia <= min(ultimo, ate):
        if dia_inteiro:
            h = h_fim = None
        else:
            h = inicio.time() if inicio.date() == dia else None
            h_fim = fim.time() if fim < dt.datetime.combine(dia + UM_DIA, dt.time()) else None
        saida.append({"dia": dia, "hora": h, "hora_fim": h_fim, "dia_todo": h is None and h_fim is None,
                      "antes": dia > primeiro, "depois": dia < ultimo})
        dia += UM_DIA
    return saida


def faixa_pedaco(p: dict) -> str:
    """'das 14:00 às 15:00', 'às 14:00' (sem duração), 'das 22:00 à meia-noite', 'da meia-noite às 02:00' ou 'o dia
    todo'."""
    h, f = p["hora"], p["hora_fim"]
    if h is None and f is None:
        return "o dia todo"
    if h == f:
        return f"às {_hhmm(h)}"
    return f"{f'das {_hhmm(h)}' if h else 'da meia-noite'} {f'às {_hhmm(f)}' if f else 'à meia-noite'}"


def _ocupado_google(nome: str, p: dict, hoje: dt.date) -> str:
    """O horário ocupado no Google de outra pessoa: sem o título nem dizer de onde vem, como _ocupado_por."""
    if p["dia_todo"]:
        return f"{nome} está com o dia {_dm(p['dia'], hoje)} ocupado"
    return f"{nome} está com o horário ocupado em {_dm(p['dia'], hoje)}, {faixa_pedaco(p)}"


def _aviso_google(titulo: str, p: dict, hoje: dt.date) -> str:
    return f"você tem “{_curto(titulo)}” no Google em {_dm(p['dia'], hoje)}, {faixa_pedaco(p)}"


def avisos_google(con, cal: Calendario | None, hoje: dt.date, a: dict, pessoa: int, google,
                  eu: int | None = None) -> list[str]:
    """A atividade a (com horário) da pessoa em cima de um evento ocupado no Google dela: grava, mas avisa quem grava
    (eu; sem ele, a própria pessoa), até MAX_AVISOS e 'e mais N'. O de outra pessoa vai sem o título nem dizer de onde
    vem, como _ocupado_google. O pedaço com exatamente o mesmo horário fica de fora: é a atividade trazida do evento."""
    if google is None or a["hora"] is None:
        return []
    desde = max(hoje, a["inicio"])
    ate = min(_ultimo_dia(a) or desde + dt.timedelta(HORIZONTE), hoje + dt.timedelta(HORIZONTE))
    if ate < desde:
        return []
    outra = eu is not None and eu != pessoa
    achados = []
    for e in google.ocupados(con, [pessoa], desde, ate):
        for p in pedacos(e["inicio"], e["fim"], e["dia_inteiro"], desde, ate):
            if (p["hora"], p["hora_fim"]) == (a["hora"], a["hora_fim"]) or not ocorre(a, p["dia"], cal):
                continue
            if _cruzam(a["hora"], a["hora_fim"], p["hora"] or dt.time(), p["hora_fim"] or dt.time.max):
                achados.append(_ocupado_google(e["nome"], p, hoje) if outra else _aviso_google(e["titulo"], p, hoje))
                break  # um aviso por evento
    if len(achados) > MAX_AVISOS:
        return [*achados[:MAX_AVISOS], f"e mais {len(achados) - MAX_AVISOS} " +
                ("horários ocupados" if outra else "no Google")]
    return achados


def _tarefas_com_horario(con, pessoa: int, desde: dt.date) -> list[tuple]:
    """As tarefas abertas de que a pessoa participa e as subtarefas abertas dela, com horário, de desde em diante:
    [(o_que, dia, hora, quem criou a tarefa, o nome de quem criou)]."""
    linhas = con.execute(
        "SELECT 'a tarefa', t.titulo, t.prazo, t.hora, t.criador, c.nome FROM agenda_tarefas t "
        "JOIN agenda_tarefa_pessoas p ON p.tarefa = t.id AND p.usuario = %(u)s JOIN usuarios c ON c.id = t.criador "
        "WHERE t.concluida_em IS NULL AND t.hora IS NOT NULL AND t.prazo >= %(desde)s "
        "UNION ALL SELECT 'a subtarefa', s.titulo, s.prazo, s.hora, t.criador, c.nome "
        "FROM agenda_subtarefas s JOIN agenda_tarefas t ON t.id = s.tarefa JOIN usuarios c ON c.id = t.criador "
        "WHERE s.responsavel = %(u)s AND s.concluida_em IS NULL AND t.concluida_em IS NULL AND s.hora IS NOT NULL "
        "AND s.prazo >= %(desde)s ORDER BY 3, 4", {"u": pessoa, "desde": desde}).fetchall()
    return [(f"{tipo} “{_curto(titulo)}”", *resto) for tipo, titulo, *resto in linhas]


def conferir_atividade(con, cal: Calendario, hoje: dt.date, a: dict, pessoa: int, eu: int | None = None) -> None:
    """A atividade a como vai ficar (com o id, se já existe), para uma pessoa que faz: recusa se ela cruza um horário
    ocupado da pessoa ou, marcada como ocupada, se a pessoa já tem algo com horário nela (de hoje em diante). eu:
    quem grava (sem ele, a própria pessoa); o que é de outra pessoa vai sem o título."""
    if a["hora"] is None:
        return
    eu = pessoa if eu is None else eu
    nome = None if eu == pessoa else con.execute("SELECT nome FROM usuarios WHERE id = %s", [pessoa]).fetchone()[0]
    for b in _com_horario(con, [pessoa], hoje, so_ocupadas=not a["ocupado"], ignorar=a.get("id")):
        if not _cruzam(a["hora"], a["hora_fim"], b["hora"], b["hora_fim"]):
            continue
        dia = _dia_em_comum(a, b, cal, hoje)
        if dia and b["ocupado"]:
            raise ValueError(_ocupado_por(b, dia, eu, hoje))
        if dia and nome:
            raise ValueError(f"{nome} já tem algo nesse horário em {_dm(dia, hoje)} "
                             f"({_faixa(b['hora'], b['hora_fim'])}). Mude o horário ou desmarque o ocupado")
        if dia:
            raise ValueError(f"já há algo nesse horário em {_dm(dia, hoje)}: “{b['titulo']}” "
                             f"({_faixa(b['hora'], b['hora_fim'])}). Mude o horário dela ou desmarque o ocupado")
    if not a["ocupado"]:
        return
    for o_que, dia, h, criador, quem_criou in _tarefas_com_horario(con, pessoa, hoje):
        if a["hora"] <= h < a["hora_fim"] and ocorre(a, dia, cal):
            if nome:
                raise ValueError(f"{nome} já tem algo nesse horário em {_dm(dia, hoje)} (às {_hhmm(h)}). Escolha "
                                 "outro horário ou desmarque o ocupado")
            pedir = ("Mude o prazo dela" if criador == pessoa
                     else f"Peça a {quem_criou}, que criou a tarefa, para mudar o prazo")
            raise ValueError(f"já há algo nesse horário em {_dm(dia, hoje)}: {o_que} (até {_hhmm(h)}). {pedir}, ou "
                             "escolha outro horário")


class Agenda:
    def __init__(self, banco: Banco, configuracao, hoje=dt.date.today, google=None):
        """configuracao: as regras de Metas (bi/configuracao.py), de onde vêm os feriados extras e os sábados.
        hoje: função que dá o dia de hoje (os testes fixam um dia). google: o Google Agenda da pessoa
        (bi/google_agenda.py), que avisa quando a atividade cai num horário ocupado de lá e aparece para o
        Assistente."""
        self.banco = banco
        self.configuracao = configuracao
        self.hoje = hoje
        self.google = google

    def contexto(self, usuario: int) -> "ContextoAgenda":
        return ContextoAgenda(self, usuario)

    def _calendario(self, atividades: list[dict]) -> Calendario | None:
        return calendario(self.configuracao) if any(a["so_dias_uteis"] for a in atividades) else None

    def _conferir_horario(self, usuario: int, a: dict, pessoas=None) -> list[str]:
        """Para a proposta do Assistente: a mesma conferência do horário ocupado da gravação (para cada pessoa que faz;
        sem pessoas, quem pergunta), sem gravar, com os avisos do Google."""
        if a["hora"] is None:
            return []
        cal = calendario(self.configuracao)
        avisos = []
        with self.banco.conexao() as con:
            for p in sorted(pessoas or [usuario]):
                conferir_atividade(con, cal, self.hoje(), a, p, usuario)
                avisos += avisos_google(con, cal, self.hoje(), a, p, self.google, usuario)
        return avisos

    @staticmethod
    def _ver(con, usuario: int, id_: int, travar: bool = False) -> dict:
        """A atividade que a pessoa vê (criou ou faz), com o papel dela (papel); a das outras pessoas não existe."""
        achadas = _carregar(con, [id_], travar)
        papel = _papel(achadas[0], usuario) if achadas else None
        if not papel or not papel["ve"]:
            raise NaoEncontrada(_NAO_ACHOU)
        return {**achadas[0], "papel": papel}

    def _obter(self, usuario: int, id_: int) -> dict:
        with self.banco.conexao() as con:
            return self._ver(con, usuario, id_)

    def _proximo(self, a: dict, desde: dt.date) -> dt.date:
        """O primeiro dia da atividade a partir de desde (ou do início), para abrir a agenda nele."""
        cal, dia = self._calendario([a]), max(desde, a["inicio"])
        for _ in range(400):
            if a["fim"] and dia > a["fim"]:
                break
            if ocorre(a, dia, cal):
                return dia
            dia += UM_DIA
        return a["inicio"]

    @staticmethod
    def _nome(con, usuario: int) -> str:
        linha = con.execute("SELECT nome FROM usuarios WHERE id = %s", [usuario]).fetchone()
        return linha[0] if linha else "Alguém"

    @staticmethod
    def _quando(a: dict, hoje: dt.date) -> str:
        """'Toda segunda e quarta, 08:00–09:00': a repetição e o horário, para os avisos do sino."""
        return texto_repeticao(a, hoje) + (f", {_faixa(a['hora'], a['hora_fim'])}" if a["hora"] else "")

    # --- leitura ---------------------------------------------------------------------------
    def _dias(self, usuario: int, de: dt.date, ate: dt.date) -> tuple[list[dict], list[tuple[dt.date, list[dict]]]]:
        """As atividades que a pessoa vê com algo entre de e ate e, dia a dia, os itens de cada dia: {a, quem (quem faz
        nesse dia: quem já tinha entrado, se ela acontece, e quem concluiu, mesmo se não), feitos ({pessoa: o
        registro}), eu_faz (a pessoa está em quem), ajuste (o aviso da mensal num dia útil que o mês não tem,
        ajuste_dia_util)}. Quem faz vê o item nos dias dele; quem criou, nos dias em que alguém faz."""
        with self.banco.conexao() as con:
            ids = [r[0] for r in con.execute(_VISIVEIS, {"u": usuario, "de": de, "ate": ate})]
            atividades = _carregar(con, ids)
            feitos = {}
            for at, pessoa, dia, fb, em, por, por_nome in con.execute(
                    "SELECT r.atividade, r.usuario, r.dia, r.feedback, r.concluida_em, r.concluida_por, c.nome "
                    "FROM agenda_registros r LEFT JOIN usuarios c ON c.id = r.concluida_por "
                    "WHERE r.atividade = ANY(%s::bigint[]) AND r.dia BETWEEN %s AND %s", [ids, de, ate]):
                feitos.setdefault((at, dia), {})[pessoa] = {"feedback": fb, "concluida_em": em, "por": por,
                                                            "por_nome": por_nome}
        cal = self._calendario(atividades)
        ordenadas = sorted(atividades, key=_ordem)
        dias, dia = [], de
        while dia <= ate:
            itens = []
            for a in ordenadas:
                do_dia = feitos.get((a["id"], dia), {})
                acontece = ocorre(a, dia, cal)
                quem = [p["id"] for p in a["pessoas"] if p["id"] in do_dia or (acontece and _entrou(p, dia))]
                if usuario in quem or (quem and a["criador"] == usuario):
                    itens.append({"a": a, "quem": quem, "feitos": {p: do_dia[p] for p in quem if p in do_dia},
                                  "eu_faz": usuario in quem, "ajuste": ajuste_dia_util(a, dia, cal)})
            dias.append((dia, itens))
            dia += UM_DIA
        return atividades, dias

    def mes(self, usuario: int, mes: str | None = None) -> dict:
        """Os dias do mês ('2026-10'; vazio = o mês de hoje) com as atividades de cada um e o que já foi concluído
        (_item: o de quem vê e o de cada pessoa)."""
        hoje = self.hoje()
        ano, n = _mes(mes, hoje)
        atividades, dias = self._dias(usuario, dt.date(ano, n, 1), dt.date(ano, n, calendar.monthrange(ano, n)[1]))
        return {"hoje": hoje.isoformat(), "mes": f"{ano:04d}-{n:02d}", "eu": usuario,
                "atividades": [_publica_para(a, usuario, hoje) for a in atividades],
                "dias": [{"data": dia.isoformat(), "itens": [_item(i, usuario) for i in itens]} for dia, itens in dias]}

    def periodo(self, usuario: int, de, ate, texto: str = "") -> dict:
        """Para o Assistente: os dias com atividade entre de e ate (até MAX_PERIODO dias), cada item com a situação
        (feita, atrasada, hoje ou prevista) e o feedback de quem pergunta (na que ele criou e não faz, feita quando
        todos fizeram) e, na que tem outras pessoas, a de cada uma; texto filtra pelo título e pela descrição."""
        hoje = self.hoje()
        de, ate = _data(de, "de início do período"), _data(ate, "de fim do período")
        if ate < de:
            raise ValueError("o fim do período vem antes do início")
        if (ate - de).days >= MAX_PERIODO:
            raise ValueError(f"leia até {MAX_PERIODO} dias por vez")
        atividades, dias = self._dias(usuario, de, ate)
        palavras = _chave(texto).split()
        if palavras:
            atividades = [a for a in atividades
                          if all(p in _chave(f"{a['titulo']} {a['descricao']}") for p in palavras)]
        ids = {a["id"] for a in atividades}
        totais = {"ocorrencias": 0, "feitas": 0, "atrasadas": 0, "hoje": 0, "previstas": 0}
        google = self.google.no_periodo(usuario, de, ate) if self.google else {}
        n_google, desatualizada = 0, False
        situacao = lambda feita, dia: ("feita" if feita else "atrasada" if dia < hoje  # noqa: E731
                                       else "hoje" if dia == hoje else "prevista")
        saida = []
        for dia, itens in dias:
            linhas = []
            for i in itens:
                a = i["a"]
                if a["id"] not in ids:
                    continue
                meu = i["feitos"].get(usuario) if i["eu_faz"] else None
                s = situacao(meu is not None if i["eu_faz"] else len(i["feitos"]) == len(i["quem"]), dia)
                totais["ocorrencias"] += 1
                totais[_TOTAL[s]] += 1
                linha = {"atividade": a["id"], "titulo": a["titulo"], "hora": _hhmm(a["hora"]),
                         "hora_fim": _hhmm(a["hora_fim"]), "situacao": s,
                         **({"feedback": meu["feedback"]} if meu else {}),
                         **({"ajuste": i["ajuste"]} if i["ajuste"] else {})}
                if i["quem"] != [usuario]:  # com outras pessoas: o dia de cada uma
                    nomes = {p["id"]: p["nome"] for p in a["pessoas"]}
                    linha["pessoas"] = [{"nome": nomes[p], "situacao": situacao(p in i["feitos"], dia),
                                         **({"feedback": i["feitos"][p]["feedback"]} if p in i["feitos"] else {})}
                                        for p in i["quem"]]
                linhas.append(linha)
            eventos = [g for g in google.get(dia.isoformat(), []) if all(p in _chave(g["titulo"]) for p in palavras)]
            desatualizada |= any(g["desatualizada"] for g in eventos)
            vao = eventos[:max(0, MAX_GOOGLE_IA - n_google)]
            n_google += len(eventos)
            if linhas or vao:
                saida.append({"data": dia.isoformat(), "dia_semana": NOME_DIA[dia.isoweekday()], "itens": linhas,
                              **({"google": [_google_ia(g) for g in vao]} if vao else {})})
        r = {"hoje": hoje.isoformat(), "de": de.isoformat(), "ate": ate.isoformat(), "totais": totais,
             "atividades": [self._para_ia(a, usuario, hoje) for a in atividades], "dias": saida}
        if n_google:
            totais["google"] = n_google
            avisos = ([f"só os primeiros {MAX_GOOGLE_IA} eventos do Google, de {n_google}"]
                      if n_google > MAX_GOOGLE_IA else [])
            avisos += ["há agenda do Google sem leitura há mais de um dia: os eventos dela podem estar desatualizados"
                       ] if desatualizada else []
            if avisos:
                r["google_aviso"] = "; ".join(avisos)
        return r

    @staticmethod
    def _para_ia(a: dict, eu: int, hoje: dt.date) -> dict:
        """A atividade para o Assistente: os campos e, se ela não é só de quem pergunta, quem criou e quem faz."""
        r = {k: v for k, v in _publica(a, hoje).items() if k not in ("dias_semana", "dia_mes", "dia_util",
                                                                       "intervalo", "so_dias_uteis", "regiao")}
        papel = _papel(a, eu)
        if not papel["criador"]:
            r["criada_por"] = a["criador_nome"]
            r["pode_editar"] = papel["autonomia"]
        if [p["id"] for p in a["pessoas"]] != [eu]:
            r["pessoas"] = [p["nome"] for p in a["pessoas"]]
            r["voce_faz"] = papel["faz"]
        return r

    def historico(self, usuario: int, id_) -> dict:
        """Tudo o que foi feito na atividade (do mais recente para o mais antigo), por todos; e, para cada pessoa que
        faz, quantas vezes ela aconteceu para ela até hoje (desde que entrou), quantas ela concluiu e os dias que
        ficaram sem concluir (antes de hoje). Os totais somam as pessoas; faltas: os dias em que alguém ficou sem
        concluir (com uma pessoa só, os dela)."""
        a = self._obter(usuario, _id(id_))
        with self.banco.conexao() as con:
            registros = con.execute(
                "SELECT r.dia, r.feedback, r.concluida_em, r.editada_em, r.usuario, u.nome, r.concluida_por, c.nome "
                "FROM agenda_registros r JOIN usuarios u ON u.id = r.usuario "
                "LEFT JOIN usuarios c ON c.id = r.concluida_por WHERE r.atividade = %s "
                "ORDER BY r.dia DESC, lower(u.nome), u.id", [a["id"]]).fetchall()
        cal = self._calendario([a])
        hoje = self.hoje()
        ate = min(hoje, a["fim"] or hoje)
        previstos, dia = [], a["inicio"]
        while dia <= ate:
            if ocorre(a, dia, cal):
                previstos.append(dia)
            dia += UM_DIA
        pessoas, todas_faltas = [], set()
        for p in a["pessoas"]:
            dias = {d for d in previstos if _entrou(p, d)}
            feitos = {r[0] for r in registros if r[4] == p["id"]}
            faltas = sorted((d for d in dias - feitos if d < hoje), reverse=True)  # hoje ainda dá tempo
            todas_faltas.update(faltas)
            pessoas.append({"id": p["id"], "nome": p["nome"], "desde": p["desde"] and p["desde"].isoformat(),
                            "ocorrencias": len(dias | feitos), "feitas": len(feitos), "faltas_total": len(faltas),
                            "faltas": [d.isoformat() for d in faltas[:MAX_FALTAS]]})
        faltas = sorted(todas_faltas, reverse=True)
        return {"atividade": _publica_para(a, usuario, hoje), "hoje": hoje.isoformat(),
                "ocorrencias": sum(p["ocorrencias"] for p in pessoas), "feitas": sum(p["feitas"] for p in pessoas),
                "faltas": [d.isoformat() for d in faltas[:MAX_FALTAS]],
                "faltas_total": sum(p["faltas_total"] for p in pessoas), "pessoas": pessoas,
                "registros": [{"dia": d.isoformat(), "feedback": fb, "concluida_em": hora(c), "editada_em": hora(e),
                               "pessoa": {"id": u, "nome": nome},
                               "concluida_por": {"id": por, "nome": por_nome} if por not in (None, u) else None}
                              for d, fb, c, e, u, nome, por, por_nome in registros]}

    # --- atividades ------------------------------------------------------------------------
    def _conferir(self, con, cal, a: dict, pessoas, eu: int) -> list[str]:
        """O horário ocupado de cada pessoa que faz (com a trava delas) e os avisos do Google (gravam assim mesmo)."""
        if a["hora"] is None or not pessoas:
            return []
        travar_horarios(con, pessoas)
        avisos = []
        for p in sorted(pessoas):
            conferir_atividade(con, cal, self.hoje(), a, p, eu)
            avisos += avisos_google(con, cal, self.hoje(), a, p, self.google, eu)
        return avisos

    @staticmethod
    def _gravar_pessoas(con, atividade: int, pessoas: dict[int, bool], desde: dt.date | None) -> None:
        """Quem faz: as que já estavam ficam com o desde delas (a autonomia muda); as novas entram com desde."""
        with con.cursor() as cur:
            cur.executemany("INSERT INTO agenda_atividade_pessoas (atividade, usuario, autonomia, desde) "
                            "VALUES (%s, %s, %s, %s) ON CONFLICT (atividade, usuario) "
                            "DO UPDATE SET autonomia = EXCLUDED.autonomia",
                            [[atividade, p, a, desde] for p, a in pessoas.items()])

    def _avisar_incluido(self, con, para: dict[int, bool], nome: str, eu: int, id_: int, a: dict) -> None:
        """Quem entrou (para: {pessoa: autonomia}): um aviso para cada, no próximo dia da atividade."""
        hoje = self.hoje()
        for p, autonomia in para.items():
            avisar(con, [p], "incluido", f"{nome} incluiu você na atividade “{a['titulo']}” ({self._quando(a, hoje)})"
                   + (", com autonomia para editá-la" if autonomia else ""), eu, None,
                   atividade=id_, dia=self._proximo(a, hoje))

    def criar(self, usuario: int, dados: dict) -> dict:
        """A atividade nova, de quem cria e (participantes) de outras pessoas; eu_faz falso: só das outras. avisos: os
        horários ocupados no Google de quem faz (grava assim mesmo)."""
        a = _valida(dados)
        participantes, eu_faz = _valida_pessoas(dados, usuario) or ({}, True)
        pessoas = {**({usuario: False} if eu_faz else {}), **participantes}
        cal = calendario(self.configuracao) if a["hora"] else None
        with self.banco.conexao() as con:
            conferir_pessoas(con, participantes)
            avisos = self._conferir(con, cal, a, pessoas, usuario)
            linha = con.execute(f"INSERT INTO agenda_atividades (usuario, {', '.join(_GRAVAR)}) SELECT id, {_VALORES} "
                                "FROM usuarios WHERE id = %(usuario)s RETURNING id",
                                {**a, "usuario": usuario}).fetchone()
            if not linha:
                raise NaoEncontrada("seu usuário não existe mais")
            self._gravar_pessoas(con, linha[0], pessoas, None)
            self._avisar_incluido(con, participantes, self._nome(con, usuario), usuario, linha[0], a)
        return {"id": linha[0], **_publica(a, self.hoje()), "avisos": avisos}

    def editar(self, usuario: int, id_, dados: dict) -> dict:
        """Troca a atividade: quem criou, tudo (e as pessoas, se os dados falam delas: participantes e eu_faz); quem
        faz com autonomia, só a atividade (as pessoas ficam). O horário ocupado (e o aviso do Google) é conferido para
        todos se os dias ou os horários mudaram; senão, só para quem entrou. Quem entra numa atividade que já começou
        faz de hoje em diante; quem sai deixa o que fez (volta se ele voltar)."""
        id_, a = _id(id_), _valida(dados)
        pedidas = _valida_pessoas(dados, usuario)
        cal = calendario(self.configuracao) if a["hora"] else None
        sets = ", ".join(f"{c} = {v}" for c, v in zip(_GRAVAR, _VALORES.split(", ")))
        hoje = self.hoje()
        with self.banco.conexao() as con:
            antes = self._ver(con, usuario, id_, travar=True)
            papel = antes["papel"]
            if not (papel["criador"] or papel["autonomia"]):
                raise PermissionError("só quem criou a atividade (ou quem tem autonomia nela) pode editá-la")
            tinha = {p["id"]: p["autonomia"] for p in antes["pessoas"]}
            if papel["criador"] and pedidas is not None:
                participantes, eu_faz = pedidas
                pessoas = {**({usuario: False} if eu_faz else {}), **participantes}
            else:
                pessoas = tinha
            entraram = [p for p in pessoas if p not in tinha]
            conferir_pessoas(con, [p for p in entraram if p != usuario])
            mudou = any(antes[c] != a[c] for c in _QUANDO)
            avisos = self._conferir(con, cal, {**a, "id": id_}, pessoas if mudou else entraram, usuario)
            con.execute(f"UPDATE agenda_atividades SET {sets}, atualizada_em = now() WHERE id = %(id)s",
                        {**a, "id": id_})
            if pessoas is not tinha:
                self._gravar_pessoas(con, id_, pessoas, hoje if a["inicio"] < hoje else None)
                con.execute("DELETE FROM agenda_atividade_pessoas WHERE atividade = %s "
                            "AND NOT (usuario = ANY(%s::bigint[]))", [id_, list(pessoas)])
            # o sino: quem entrou; quem ganhou a autonomia; e, se os dias ou o horário mudaram, quem criou e quem faz
            nome = self._nome(con, usuario)
            self._avisar_incluido(con, {p: pessoas[p] for p in entraram if p != usuario}, nome, usuario, id_, a)
            ganharam = [p for p, aut in pessoas.items() if aut and p in tinha and not tinha[p]]
            avisar(con, ganharam, "incluido", f"{nome} deu autonomia a você na atividade “{a['titulo']}”: agora "
                   "você pode editá-la", usuario, None, atividade=id_, dia=self._proximo(a, hoje))
            if mudou:
                avisar(con, ({antes["criador"], *pessoas} - set(entraram)), "prazo_mudou",
                       f"{nome} mudou os dias ou o horário da atividade “{a['titulo']}”: {self._quando(a, hoje)}",
                       usuario, None, atividade=id_, dia=self._proximo(a, hoje))
        return {"id": id_, **_publica(a, hoje), "avisos": avisos}

    @staticmethod
    def _pode_encerrar(a: dict, hoje: dt.date) -> None:
        if a["repeticao"] == "nenhuma" and not a["fim"]:
            raise ValueError("só a atividade que se repete (ou que dura vários dias) pode ser encerrada")
        if a["inicio"] > hoje:
            raise ValueError("a atividade ainda não começou; exclua se ela não vai mais acontecer")

    @staticmethod
    def _so_quem_criou(a: dict, o_que: str) -> None:
        if not a["papel"]["criador"]:
            raise PermissionError(f"só quem criou a atividade ({a['criador_nome']}) pode {o_que}")

    def encerrar(self, usuario: int, id_) -> dict:
        """A repetida (ou a de vários dias) para de acontecer depois de hoje, para todos; o que já foi feito fica."""
        id_, hoje = _id(id_), self.hoje()
        with self.banco.conexao() as con:
            a = self._ver(con, usuario, id_, travar=True)
            self._so_quem_criou(a, "encerrá-la")
            self._pode_encerrar(a, hoje)
            fim = a["fim"]
            if fim is None or fim > hoje:
                con.execute("UPDATE agenda_atividades SET fim = %s, atualizada_em = now() WHERE id = %s", [hoje, id_])
                fim = hoje
                avisar(con, [p["id"] for p in a["pessoas"]], "prazo_mudou",
                       f"{self._nome(con, usuario)} encerrou a atividade “{a['titulo']}”: o último dia é "
                       f"{_dm(hoje, hoje)}", usuario, None, atividade=id_, dia=hoje)
        return {"id": id_, "fim": fim.isoformat()}

    def excluir(self, usuario: int, id_) -> None:
        """Apaga a atividade e todo o histórico dela, de todos."""
        with self.banco.conexao() as con:
            a = self._ver(con, usuario, _id(id_), travar=True)
            self._so_quem_criou(a, "excluí-la")
            con.execute("DELETE FROM agenda_atividades WHERE id = %s", [a["id"]])

    # --- o que foi feito -------------------------------------------------------------------
    def _de_quem(self, a: dict, usuario: int, pessoa) -> dict:
        """A pessoa cujo dia muda (sem ela, quem pede): o próprio, quem faz; o de outra pessoa, só quem criou."""
        pessoa = usuario if pessoa in (None, "") else _pessoa(pessoa)
        if pessoa != usuario:
            self._so_quem_criou(a, "marcar o dia de outra pessoa")
        p = next((p for p in a["pessoas"] if p["id"] == pessoa), None)
        if p is None:
            raise ValueError("você não faz esta atividade: ela é de quem está marcado nela" if pessoa == usuario
                             else "essa pessoa não faz esta atividade")
        return p

    def _conferir_conclusao(self, con, a: dict, p: dict, dia: dt.date, feedback: str) -> tuple | None:
        """Confere o dia e devolve o registro que já havia (feedback, concluida_por) ou None."""
        if dia > self.hoje():
            raise ValueError("só dá para concluir até hoje")
        if a["exige_feedback"] and not feedback:
            raise ValueError("esta atividade pede um feedback para ser concluída")
        ja = con.execute("SELECT feedback, concluida_por FROM agenda_registros WHERE atividade = %s AND usuario = %s "
                         "AND dia = %s", [a["id"], p["id"], dia]).fetchone()
        if not ja and not ocorre(a, dia, self._calendario([a])):
            raise ValueError("a atividade não acontece neste dia")
        if not ja and not _entrou(p, dia):
            raise ValueError(f"{p['nome']} entrou na atividade em {_dm(p['desde'], self.hoje())}: os dias de antes "
                             "não são dele")
        return ja

    def concluir(self, usuario: int, id_, dia, feedback, pessoa=None) -> dict:
        """Marca o dia como feito, com o feedback; se já estava feito, troca o feedback (o de quem concluiu, só ela
        troca). pessoa: de quem é o dia (sem ela, de quem pede; o de outra pessoa, só quem criou marca)."""
        id_, dia = _id(id_), _data(dia, "da conclusão")
        feedback = _texto(feedback, "o feedback")
        with self.banco.conexao() as con:
            a = self._ver(con, usuario, id_)
            p = self._de_quem(a, usuario, pessoa)
            ja = self._conferir_conclusao(con, a, p, dia, feedback)
            if ja and p["id"] != usuario and ja[1] != usuario and ja[0] != feedback:
                raise PermissionError(f"o feedback é de quem concluiu: só {p['nome']} muda")
            linha = con.execute(
                "INSERT INTO agenda_registros (atividade, usuario, dia, feedback, concluida_por) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (atividade, usuario, dia) "
                "DO UPDATE SET feedback = EXCLUDED.feedback, editada_em = now() RETURNING concluida_em, editada_em",
                [id_, p["id"], dia, feedback, usuario]).fetchone()
            if not ja and usuario == p["id"]:
                avisar(con, [a["criador"]], "concluida", f"{self._nome(con, usuario)} concluiu a atividade "
                       f"“{a['titulo']}” ({_dm(dia, self.hoje())})", usuario, None, atividade=id_, dia=dia)
        return {"atividade": id_, "pessoa": p["id"], "dia": dia.isoformat(), "feita": True, "feedback": feedback,
                "concluida_em": hora(linha[0]), "editada_em": hora(linha[1])}

    def desfazer(self, usuario: int, id_, dia, pessoa=None) -> None:
        """Volta o dia para não feito (o feedback dele sai junto). pessoa: como em concluir."""
        id_, dia = _id(id_), _data(dia, "da conclusão")
        with self.banco.conexao() as con:
            a = self._ver(con, usuario, id_)
            p = self._de_quem(a, usuario, pessoa)
            apagou = con.execute("DELETE FROM agenda_registros WHERE atividade = %s AND usuario = %s AND dia = %s",
                                 [id_, p["id"], dia]).rowcount
        if not apagou:
            raise NaoEncontrada("a atividade não estava concluída neste dia")

    # --- propostas do Assistente -----------------------------------------------------------
    def propor(self, usuario: int, acao: str, atividade=None, dados: dict | None = None, dia=None,
               feedback=None) -> dict:
        """Confere e monta uma proposta, sem gravar: criar (dados; só para quem pergunta), editar (atividade e só os
        campos que mudam, em dados; quem criou ou quem tem autonomia), encerrar e excluir (só quem criou) ou concluir
        (o dia de quem pergunta: atividade, dia, padrão hoje, e feedback). A resposta do Assistente guarda a proposta
        e mostra o botão que a aplica (aplicar)."""
        if acao not in ACOES:
            raise ValueError(f"ação desconhecida: {acao!r} (use {', '.join(ACOES)})")
        hoje = self.hoje()
        p = {"id": str(uuid.uuid4()), "acao": acao, "atividade": None}
        if acao == "criar":
            a = _valida(dados or {})
            avisos = self._conferir_horario(usuario, a)
            return {**p, "titulo": a["titulo"], "dados": _publica(a, hoje), "dia": self._proximo(a, hoje).isoformat(),
                    **({"avisos": avisos} if avisos else {})}
        atual = self._obter(usuario, _id(atividade))
        p.update(atividade=atual["id"], titulo=atual["titulo"])
        if acao == "editar":
            if not (atual["papel"]["criador"] or atual["papel"]["autonomia"]):
                raise PermissionError("só quem criou a atividade (ou quem tem autonomia nela) pode editá-la")
            antes = _publica(atual, hoje)
            mudados = {k: v for k, v in (dados or {}).items() if k in _GRAVAR}
            if not mudados:
                raise ValueError("diga o que muda na atividade")
            if "dia_mes" in mudados and "dia_util" not in mudados:  # passou do dia útil para o dia fixo
                mudados["dia_util"] = None
            a = _valida({**antes, **mudados})
            depois = _publica(a, hoje)
            rotulos = {"titulo": "Título", "descricao": "Descrição", "inicio": "Início", "hora": "Horário",
                       "hora_fim": "Fim do horário", "ocupado": "Horário ocupado", "quando": "Repetição",
                       "exige_feedback": "Feedback ao concluir"}
            mudancas = [{"campo": r, "de": antes[k], "para": depois[k]} for k, r in rotulos.items()
                        if antes[k] != depois[k]]
            if not mudancas:
                raise ValueError("a atividade já está assim; nada muda")
            avisos = (self._conferir_horario(usuario, {**a, "id": atual["id"]}, [x["id"] for x in atual["pessoas"]])
                      if any(atual[c] != a[c] for c in _QUANDO) else [])
            return {**p, "dados": depois, "mudancas": mudancas, "dia": self._proximo(a, hoje).isoformat(),
                    **({"avisos": avisos} if avisos else {})}
        if acao == "encerrar":
            self._so_quem_criou(atual, "encerrá-la")
            self._pode_encerrar(atual, hoje)
            if atual["fim"] and atual["fim"] <= hoje:
                raise ValueError(f"a atividade já terminou em {_dm(atual['fim'], hoje)}")
            return {**p, "fim": hoje.isoformat(), "quando": texto_repeticao(atual, hoje)}
        if acao == "excluir":
            self._so_quem_criou(atual, "excluí-la")
            with self.banco.conexao() as con:
                n = con.execute("SELECT count(*) FROM agenda_registros WHERE atividade = %s",
                                [atual["id"]]).fetchone()[0]
            return {**p, "quando": texto_repeticao(atual, hoje), "registros": n}
        dia = _data(dia, "da conclusão") if dia else hoje
        feedback = _texto(feedback, "o feedback")
        with self.banco.conexao() as con:
            self._conferir_conclusao(con, atual, self._de_quem(atual, usuario, None), dia, feedback)
        return {**p, "dia": dia.isoformat(), "feedback": feedback, "exige_feedback": atual["exige_feedback"]}

    def aplicar(self, usuario: int, p: dict) -> dict:
        """Aplica uma proposta (o botão da resposta do Assistente), uma vez só: a segunda vez só diz que já foi."""
        pid, acao = id_valido(p.get("id")), p.get("acao")
        if not pid or acao not in ACOES:
            raise NaoEncontrada("proposta não encontrada")
        with self.banco.conexao() as con:
            reservou = con.execute(
                "INSERT INTO agenda_propostas (id, usuario, acao, atividade) SELECT %s, id, %s, %s FROM usuarios "
                "WHERE id = %s ON CONFLICT (id) DO NOTHING RETURNING id",
                [pid, acao, p.get("atividade"), usuario]).fetchone()
            if not reservou:
                ja = con.execute("SELECT atividade FROM agenda_propostas WHERE id = %s AND usuario = %s",
                                 [pid, usuario]).fetchone()
                if not ja:
                    raise NaoEncontrada("proposta não encontrada")
                return {"ja_aplicada": True, "acao": acao, "atividade": ja[0], "dia": p.get("dia")}
        try:
            atividade = p.get("atividade")
            if acao == "criar":
                atividade = self.criar(usuario, p["dados"])["id"]
            elif acao == "editar":  # a proposta de antes da migração 026 não traz hora_fim e ocupado: ficam os de agora
                atual = _publica(self._obter(usuario, _id(atividade)), self.hoje())
                self.editar(usuario, atividade, {**atual, **p["dados"]})  # sem as pessoas: elas ficam
            elif acao == "encerrar":
                self.encerrar(usuario, atividade)
            elif acao == "excluir":
                self.excluir(usuario, atividade)
            else:
                self.concluir(usuario, atividade, p["dia"], p.get("feedback"))
        except Exception:
            with self.banco.conexao() as con:  # não aplicou: o botão pode tentar de novo
                con.execute("DELETE FROM agenda_propostas WHERE id = %s", [pid])
            raise
        if acao == "criar":
            with self.banco.conexao() as con:
                con.execute("UPDATE agenda_propostas SET atividade = %s WHERE id = %s", [atividade, pid])
        return {"ja_aplicada": False, "acao": acao, "atividade": atividade, "dia": p.get("dia")}

    def aplicadas(self, usuario: int, ids: list[str]) -> dict[str, dict]:
        """As propostas (de uma conversa) que a pessoa já aplicou: {id: {atividade, aplicada_em}}."""
        ids = [i for i in (id_valido(x) for x in ids) if i]
        if not ids:
            return {}
        with self.banco.conexao() as con:
            return {str(i): {"atividade": at, "aplicada_em": hora(em)} for i, at, em in con.execute(
                "SELECT id, atividade, aplicada_em FROM agenda_propostas WHERE usuario = %s AND id = ANY(%s::uuid[])",
                [usuario, ids])}


class ContextoAgenda:
    """A agenda de quem pergunta ao Assistente: as ferramentas leem e montam propostas; quem grava é o botão."""

    def __init__(self, agenda: Agenda, usuario: int):
        self.agenda, self.usuario = agenda, usuario

    def hoje(self) -> dt.date:
        return self.agenda.hoje()

    def periodo(self, de, ate, texto: str = "") -> dict:
        return self.agenda.periodo(self.usuario, de, ate, texto)

    def historico(self, atividade) -> dict:
        return self.agenda.historico(self.usuario, atividade)

    def propor(self, acao: str, **campos) -> dict:
        return self.agenda.propor(self.usuario, acao, **campos)

"""Agenda de cada pessoa, no topo da página Gestão: atividades únicas ou repetidas e o que foi feito em cada dia.
As tarefas com prazo, divididas com outras pessoas, ficam em bi/tarefas.py (a mesma agenda mostra as duas).

- Cada pessoa vê só a própria agenda, como as conversas do Assistente (bi/conversas.py): todo método recebe o id do
  usuário e filtra por ele, e a atividade de outra pessoa é tratada como se não existisse.
- Repetição (ocorre): única (só no dia do início ou, com o último dia, todos os dias do início ao fim: a de vários
  dias, migração 026), diária (todo dia, ou só os dias úteis de uma região, com os feriados e os extras de
  Configurações, bi/calendario.py), semanal (dias da semana escolhidos), mensal (um dia fixo; o mês sem esse dia usa o
  último) ou a cada N dias desde o início. A repetida pode ter um último dia (fim). O horário é opcional (migração
  019), com o fim também opcional (migração 026): no dia, as com horário vêm primeiro, em ordem.
- Horário ocupado (migração 026): a atividade com começo e fim marcada como ocupada trava o horário da pessoa nos dias
  em que acontece, de hoje em diante. Nem a pessoa marca outra atividade que cruze esse horário, nem quem cria tarefas
  põe a pessoa numa tarefa ou subtarefa com horário dentro dele (conferir_atividade e conferir_pontos, que
  bi/tarefas.py também usa); marcar como ocupado é recusado se a pessoa já tem algo com horário ali. A mensagem sobre
  o horário de outra pessoa não diz o título, que só ela vê.
- Concluir grava o registro do dia (agenda_registros, migração 018) com o feedback, obrigatório quando a atividade
  exige feedback. Só até hoje; concluir de novo troca o feedback. A repetida junta um registro por dia: o histórico.
- Editar a atividade não apaga o que já foi feito: o registro de um dia que deixou de ocorrer continua aparecendo.
- Assistente (ContextoAgenda): lê a agenda de quem pergunta (periodo, historico) e monta propostas (propor: criar,
  editar, encerrar, excluir ou concluir), sem gravar. Quem grava é o botão da resposta (aplicar), uma vez só por
  proposta (agenda_propostas, migração 019).
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

REPETICOES = ("nenhuma", "diaria", "semanal", "mensal", "intervalo")
ACOES = ("criar", "editar", "encerrar", "excluir", "concluir")
MAX_TITULO = 120
MAX_TEXTO = 2000
MAX_FALTAS = 30   # dias sem conclusão que o histórico lista (os mais recentes)
MAX_PERIODO = 93  # dias que o Assistente lê de uma vez
HORIZONTE = 366   # dias à frente que o horário ocupado confere entre duas atividades que se repetem sem fim
TRAVA_HORARIOS = 7_240_102  # pg_advisory_xact_lock(TRAVA_HORARIOS, pessoa): uma gravação com horário por pessoa por vez
NOME_DIA = ["", "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]  # date.isoweekday()
_GRAVAR = ("titulo", "descricao", "inicio", "hora", "hora_fim", "ocupado", "repeticao", "dias_semana", "dia_mes",
           "intervalo", "so_dias_uteis", "regiao", "fim", "exige_feedback")
# O que decide os dias e os horários da atividade: editar só confere o horário ocupado se algo disso mudou.
_QUANDO = ("inicio", "fim", "hora", "hora_fim", "ocupado", "repeticao", "dias_semana", "dia_mes", "intervalo",
           "so_dias_uteis", "regiao")
_CAMPOS = ("id", *_GRAVAR)
_COLUNAS = ", ".join(_CAMPOS)
_VALORES = ", ".join(f"%({c})s::smallint[]" if c == "dias_semana" else f"%({c})s" for c in _GRAVAR)
_HORA = re.compile(r"^(\d{1,2})(?::|h)(\d{2})?(?::00)?$")
_TOTAL = {"feita": "feitas", "atrasada": "atrasadas", "hoje": "hoje", "prevista": "previstas"}
_NAO_ACHOU = "atividade não encontrada; ela pode ter sido excluída"


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


def _titulo(valor, de: str = "da atividade") -> str:
    """O título sem espaços sobrando; obrigatório."""
    titulo = " ".join(str(valor or "").split())
    if not titulo:
        raise ValueError(f"escreva o título {de}")
    if len(titulo) > MAX_TITULO:
        raise ValueError(f"o título pode ter até {MAX_TITULO} caracteres")
    return titulo


def _valida(dados: dict) -> dict:
    """A atividade como vai para o banco, com só os campos da repetição escolhida."""
    titulo = _titulo(dados.get("titulo"))
    repeticao = dados.get("repeticao") or "nenhuma"
    if repeticao not in REPETICOES:
        raise ValueError(f"repetição desconhecida: {repeticao!r}")
    a = {"titulo": titulo, "descricao": _texto(dados.get("descricao"), "a descrição"),
         "inicio": _data(dados.get("inicio"), "da atividade"), "hora": _hora(dados.get("hora")),
         "hora_fim": _hora(dados.get("hora_fim")), "ocupado": bool(dados.get("ocupado")),
         "repeticao": repeticao, "dias_semana": None, "dia_mes": None, "intervalo": None, "so_dias_uteis": False,
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
    """A atividade acontece neste dia? cal: o calendário dos dias úteis (só a diária com so_dias_uteis usa)."""
    if dia < a["inicio"] or (a["fim"] and dia > a["fim"]):
        return False
    repeticao = a["repeticao"]
    if repeticao == "nenhuma":  # com o último dia, todos os dias do início ao fim
        return a["fim"] is not None or dia == a["inicio"]
    if repeticao == "diaria":
        return not a["so_dias_uteis"] or cal.dia(dia, a["regiao"])["peso"] > 0
    if repeticao == "semanal":
        return dia.isoweekday() in a["dias_semana"]
    if repeticao == "mensal":
        return dia.day == min(a["dia_mes"], calendar.monthrange(dia.year, dia.month)[1])
    return (dia - a["inicio"]).days % a["intervalo"] == 0


def _dm(dia: dt.date, hoje: dt.date) -> str:
    return f"{dia:%d/%m}" if dia.year == hoje.year else f"{dia:%d/%m/%Y}"


def _lista_e(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else f"{', '.join(itens[:-1])} e {itens[-1]}"


def texto_repeticao(a: dict, hoje: dt.date) -> str:
    """'Só neste dia', 'De 10/11 a 14/11', 'Todo dia útil (ES)', 'Toda segunda e quinta', 'Todo dia 5', 'A cada 15
    dias' (e 'até 30/11')."""
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
    elif repeticao == "mensal":
        t = f"Todo dia {a['dia_mes']}" + (" (ou o último do mês)" if a["dia_mes"] > 28 else "")
    else:
        t = f"A cada {a['intervalo']} dias"
    return f"{t}, até {_dm(a['fim'], hoje)}" if a["fim"] else t


def _publica(a: dict, hoje: dt.date) -> dict:
    return {**a, "inicio": a["inicio"].isoformat(), "fim": a["fim"].isoformat() if a["fim"] else None,
            "hora": _hhmm(a["hora"]), "hora_fim": _hhmm(a["hora_fim"]), "quando": texto_repeticao(a, hoje)}


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
             "dias_semana", "dia_mes", "intervalo", "so_dias_uteis", "regiao")


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
    """As atividades com horário das pessoas que ainda acontecem de desde em diante (só as ocupadas, se pedido)."""
    return [dict(zip(_HORARIOS, r)) for r in con.execute(
        "SELECT a.id, a.usuario, u.nome, a.titulo, a.inicio, a.fim, a.hora, a.hora_fim, a.ocupado, a.repeticao, "
        "a.dias_semana, a.dia_mes, a.intervalo, a.so_dias_uteis, a.regiao FROM agenda_atividades a "
        "JOIN usuarios u ON u.id = a.usuario WHERE a.usuario = ANY(%(p)s::bigint[]) AND a.hora IS NOT NULL "
        "AND coalesce(a.fim, CASE a.repeticao WHEN 'nenhuma' THEN a.inicio ELSE 'infinity' END) >= %(desde)s "
        "AND a.id <> %(ignorar)s" + (" AND a.ocupado" if so_ocupadas else "") + " ORDER BY a.inicio, a.hora, a.id",
        {"p": sorted(set(pessoas)), "desde": desde, "ignorar": ignorar or 0})]


def _ocupado_por(b: dict, dia: dt.date, eu: int, hoje: dt.date) -> str:
    """O horário ocupado b em dia: com o título, se é de quem grava; de outra pessoa, sem (só ela vê a agenda dela)."""
    if b["usuario"] == eu:
        return f"esse horário está ocupado por “{b['titulo']}” ({_dm(dia, hoje)}, {_faixa(b['hora'], b['hora_fim'])})"
    return (f"{b['nome']} está com o horário ocupado em {_dm(dia, hoje)}, das {_hhmm(b['hora'])} às "
            f"{_hhmm(b['hora_fim'])}")


def conferir_pontos(con, cal: Calendario, hoje: dt.date, pontos: list[tuple], eu: int) -> None:
    """Os horários de tarefa e subtarefa que entram ou mudam, [(pessoa, dia, hora, o_que)], com o_que como "a
    subtarefa “Estande”": recusa o que cai no horário ocupado da pessoa (de hoje em diante). eu: quem grava."""
    pontos = [p for p in pontos if p[2] is not None and p[1] >= hoje]
    if not pontos:
        return
    ocupadas = _com_horario(con, {p[0] for p in pontos}, hoje, so_ocupadas=True)
    for pessoa, dia, h, o_que in pontos:
        for b in ocupadas:
            if b["usuario"] == pessoa and b["hora"] <= h < b["hora_fim"] and ocorre(b, dia, cal):
                raise ValueError(f"{_ocupado_por(b, dia, eu, hoje)}: mude o horário d{o_que}")


def _tarefas_com_horario(con, pessoa: int, desde: dt.date) -> list[tuple]:
    """As tarefas abertas de que a pessoa participa e as subtarefas abertas dela, com horário, de desde em diante:
    [(o_que, dia, hora, quem criou a tarefa, o nome de quem criou)]."""
    linhas = con.execute(
        "SELECT 'a tarefa “' || t.titulo || '”', t.prazo, t.hora, t.criador, c.nome FROM agenda_tarefas t "
        "JOIN agenda_tarefa_pessoas p ON p.tarefa = t.id AND p.usuario = %(u)s JOIN usuarios c ON c.id = t.criador "
        "WHERE t.concluida_em IS NULL AND t.hora IS NOT NULL AND t.prazo >= %(desde)s "
        "UNION ALL SELECT 'a subtarefa “' || s.titulo || '”', s.prazo, s.hora, t.criador, c.nome "
        "FROM agenda_subtarefas s JOIN agenda_tarefas t ON t.id = s.tarefa JOIN usuarios c ON c.id = t.criador "
        "WHERE s.responsavel = %(u)s AND s.concluida_em IS NULL AND t.concluida_em IS NULL AND s.hora IS NOT NULL "
        "AND s.prazo >= %(desde)s ORDER BY 2, 3", {"u": pessoa, "desde": desde}).fetchall()
    return [tuple(r) for r in linhas]


def conferir_atividade(con, cal: Calendario, hoje: dt.date, a: dict, pessoa: int) -> None:
    """A atividade a da pessoa como vai ficar (com o id, se já existe): recusa se ela cruza um horário ocupado da
    pessoa ou, marcada como ocupada, se a pessoa já tem algo com horário nela (de hoje em diante)."""
    if a["hora"] is None:
        return
    for b in _com_horario(con, [pessoa], hoje, so_ocupadas=not a["ocupado"], ignorar=a.get("id")):
        if not _cruzam(a["hora"], a["hora_fim"], b["hora"], b["hora_fim"]):
            continue
        dia = _dia_em_comum(a, b, cal, hoje)
        if dia and b["ocupado"]:
            raise ValueError(_ocupado_por(b, dia, pessoa, hoje))
        if dia:
            raise ValueError(f"já há algo nesse horário em {_dm(dia, hoje)}: “{b['titulo']}” "
                             f"({_faixa(b['hora'], b['hora_fim'])}). Mude o horário dela ou desmarque o ocupado")
    if not a["ocupado"]:
        return
    for o_que, dia, h, criador, nome in _tarefas_com_horario(con, pessoa, hoje):
        if a["hora"] <= h < a["hora_fim"] and ocorre(a, dia, cal):
            pedir = ("Mude o prazo dela" if criador == pessoa
                     else f"Peça a {nome}, que criou a tarefa, para mudar o prazo")
            raise ValueError(f"já há algo nesse horário em {_dm(dia, hoje)}: {o_que} (até {_hhmm(h)}). {pedir}, ou "
                             "escolha outro horário")


class Agenda:
    def __init__(self, banco: Banco, configuracao, hoje=dt.date.today):
        """configuracao: as regras de Metas (bi/configuracao.py), de onde vêm os feriados extras e os sábados.
        hoje: função que dá o dia de hoje (os testes fixam um dia)."""
        self.banco = banco
        self.configuracao = configuracao
        self.hoje = hoje

    def contexto(self, usuario: int) -> "ContextoAgenda":
        return ContextoAgenda(self, usuario)

    def _calendario(self, atividades: list[dict]) -> Calendario | None:
        return calendario(self.configuracao) if any(a["so_dias_uteis"] for a in atividades) else None

    def _conferir_horario(self, usuario: int, a: dict) -> None:
        """Para a proposta do Assistente: a mesma conferência do horário ocupado da gravação, sem gravar."""
        if a["hora"] is None:
            return
        cal = calendario(self.configuracao)
        with self.banco.conexao() as con:
            conferir_atividade(con, cal, self.hoje(), a, usuario)

    def _obter(self, usuario: int, id_: int) -> dict:
        with self.banco.conexao() as con:
            linha = con.execute(f"SELECT {_COLUNAS} FROM agenda_atividades WHERE id = %s AND usuario = %s",
                                [id_, usuario]).fetchone()
        if not linha:
            raise NaoEncontrada(_NAO_ACHOU)
        return dict(zip(_CAMPOS, linha))

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

    # --- leitura ---------------------------------------------------------------------------
    def _dias(self, usuario: int, de: dt.date, ate: dt.date) -> tuple[list[dict], list[tuple[dt.date, list[dict]]]]:
        """As atividades que aparecem entre de e ate e, dia a dia, os itens de cada dia ({a, feito})."""
        with self.banco.conexao() as con:
            atividades = [dict(zip(_CAMPOS, r)) for r in con.execute(
                f"SELECT {_COLUNAS} FROM agenda_atividades WHERE usuario = %(u)s AND ((inicio <= %(ate)s AND "
                "(fim IS NULL OR fim >= %(de)s)) OR id IN (SELECT atividade FROM agenda_registros "
                "WHERE dia BETWEEN %(de)s AND %(ate)s)) ORDER BY id", {"u": usuario, "de": de, "ate": ate})]
            feitos = {(at, dia): (feedback, quando) for at, dia, feedback, quando in con.execute(
                "SELECT r.atividade, r.dia, r.feedback, r.concluida_em FROM agenda_registros r "
                "JOIN agenda_atividades a ON a.id = r.atividade "
                "WHERE a.usuario = %s AND r.dia BETWEEN %s AND %s", [usuario, de, ate])}
        cal = self._calendario(atividades)
        ordenadas = sorted(atividades, key=_ordem)
        dias, dia = [], de
        while dia <= ate:
            dias.append((dia, [{"a": a, "feito": feitos.get((a["id"], dia))} for a in ordenadas
                               if (a["id"], dia) in feitos or ocorre(a, dia, cal)]))
            dia += UM_DIA
        return atividades, dias

    def mes(self, usuario: int, mes: str | None = None) -> dict:
        """Os dias do mês ('2026-10'; vazio = o mês de hoje) com as atividades de cada um e o que já foi concluído."""
        hoje = self.hoje()
        ano, n = _mes(mes, hoje)
        atividades, dias = self._dias(usuario, dt.date(ano, n, 1), dt.date(ano, n, calendar.monthrange(ano, n)[1]))
        return {"hoje": hoje.isoformat(), "mes": f"{ano:04d}-{n:02d}",
                "atividades": [_publica(a, hoje) for a in atividades],
                "dias": [{"data": dia.isoformat(),
                          "itens": [{"atividade": i["a"]["id"], "feita": i["feito"] is not None,
                                     "feedback": i["feito"][0] if i["feito"] else None,
                                     "concluida_em": hora(i["feito"][1]) if i["feito"] else None} for i in itens]}
                         for dia, itens in dias]}

    def periodo(self, usuario: int, de, ate, texto: str = "") -> dict:
        """Para o Assistente: os dias com atividade entre de e ate (até MAX_PERIODO dias), cada item com a situação
        (feita, atrasada, hoje ou prevista) e o feedback; texto filtra pelo título e pela descrição."""
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
        saida = []
        for dia, itens in dias:
            linhas = []
            for i in itens:
                if i["a"]["id"] not in ids:
                    continue
                situacao = ("feita" if i["feito"] else "atrasada" if dia < hoje else "hoje" if dia == hoje
                            else "prevista")
                totais["ocorrencias"] += 1
                totais[_TOTAL[situacao]] += 1
                linhas.append({"atividade": i["a"]["id"], "titulo": i["a"]["titulo"], "hora": _hhmm(i["a"]["hora"]),
                               "hora_fim": _hhmm(i["a"]["hora_fim"]), "situacao": situacao,
                               **({"feedback": i["feito"][0]} if i["feito"] else {})})
            if linhas:
                saida.append({"data": dia.isoformat(), "dia_semana": NOME_DIA[dia.isoweekday()], "itens": linhas})
        return {"hoje": hoje.isoformat(), "de": de.isoformat(), "ate": ate.isoformat(), "totais": totais,
                "atividades": [{k: v for k, v in _publica(a, hoje).items() if k not in ("dias_semana", "dia_mes",
                                "intervalo", "so_dias_uteis", "regiao")} for a in atividades],
                "dias": saida}

    def historico(self, usuario: int, id_) -> dict:
        """Tudo o que foi feito na atividade (do mais recente para o mais antigo), quantas vezes ela aconteceu até hoje
        e os dias que ficaram sem conclusão (antes de hoje)."""
        a = self._obter(usuario, _id(id_))
        with self.banco.conexao() as con:
            registros = con.execute("SELECT dia, feedback, concluida_em, editada_em FROM agenda_registros "
                                    "WHERE atividade = %s ORDER BY dia DESC", [a["id"]]).fetchall()
        cal = self._calendario([a])
        hoje = self.hoje()
        ate = min(hoje, a["fim"] or hoje)
        previstos, dia = set(), a["inicio"]
        while dia <= ate:
            if ocorre(a, dia, cal):
                previstos.add(dia)
            dia += UM_DIA
        feitos = {r[0] for r in registros}
        faltas = sorted((d for d in previstos - feitos if d < hoje), reverse=True)  # hoje ainda dá tempo
        return {"atividade": _publica(a, hoje), "hoje": hoje.isoformat(), "ocorrencias": len(previstos | feitos),
                "feitas": len(registros), "faltas": [d.isoformat() for d in faltas[:MAX_FALTAS]],
                "faltas_total": len(faltas),
                "registros": [{"dia": d.isoformat(), "feedback": fb, "concluida_em": hora(c), "editada_em": hora(e)}
                              for d, fb, c, e in registros]}

    # --- atividades ------------------------------------------------------------------------
    def criar(self, usuario: int, dados: dict) -> dict:
        a = _valida(dados)
        cal = calendario(self.configuracao) if a["hora"] else None
        with self.banco.conexao() as con:
            if a["hora"]:
                travar_horarios(con, [usuario])
                conferir_atividade(con, cal, self.hoje(), a, usuario)
            linha = con.execute(f"INSERT INTO agenda_atividades (usuario, {', '.join(_GRAVAR)}) SELECT id, {_VALORES} "
                                "FROM usuarios WHERE id = %(usuario)s RETURNING id",
                                {**a, "usuario": usuario}).fetchone()
        if not linha:
            raise NaoEncontrada("seu usuário não existe mais")
        return {"id": linha[0], **_publica(a, self.hoje())}

    def editar(self, usuario: int, id_, dados: dict) -> dict:
        """Troca a atividade; o horário ocupado só é conferido se os dias ou os horários mudaram."""
        id_, a = _id(id_), _valida(dados)
        cal = calendario(self.configuracao) if a["hora"] else None
        sets = ", ".join(f"{c} = {v}" for c, v in zip(_GRAVAR, _VALORES.split(", ")))
        with self.banco.conexao() as con:
            linha = con.execute(f"SELECT {_COLUNAS} FROM agenda_atividades WHERE id = %s AND usuario = %s FOR UPDATE",
                                [id_, usuario]).fetchone()
            if not linha:
                raise NaoEncontrada(_NAO_ACHOU)
            antes = dict(zip(_CAMPOS, linha))
            if a["hora"] and any(antes[c] != a[c] for c in _QUANDO):
                travar_horarios(con, [usuario])
                conferir_atividade(con, cal, self.hoje(), {**a, "id": id_}, usuario)
            con.execute(f"UPDATE agenda_atividades SET {sets}, atualizada_em = now() WHERE id = %(id)s",
                        {**a, "id": id_})
        return {"id": id_, **_publica(a, self.hoje())}

    @staticmethod
    def _pode_encerrar(a: dict, hoje: dt.date) -> None:
        if a["repeticao"] == "nenhuma" and not a["fim"]:
            raise ValueError("só a atividade que se repete (ou que dura vários dias) pode ser encerrada")
        if a["inicio"] > hoje:
            raise ValueError("a atividade ainda não começou; exclua se ela não vai mais acontecer")

    def encerrar(self, usuario: int, id_) -> dict:
        """A repetida (ou a de vários dias) para de acontecer depois de hoje; o que já foi feito fica."""
        id_, hoje = _id(id_), self.hoje()
        with self.banco.conexao() as con:
            linha = con.execute("SELECT repeticao, inicio, fim FROM agenda_atividades WHERE id = %s AND usuario = %s "
                                "FOR UPDATE", [id_, usuario]).fetchone()
            if not linha:
                raise NaoEncontrada(_NAO_ACHOU)
            repeticao, inicio, fim = linha
            self._pode_encerrar({"repeticao": repeticao, "inicio": inicio, "fim": fim}, hoje)
            if fim is None or fim > hoje:
                con.execute("UPDATE agenda_atividades SET fim = %s, atualizada_em = now() WHERE id = %s", [hoje, id_])
                fim = hoje
        return {"id": id_, "fim": fim.isoformat()}

    def excluir(self, usuario: int, id_) -> None:
        """Apaga a atividade e todo o histórico dela."""
        with self.banco.conexao() as con:
            apagou = con.execute("DELETE FROM agenda_atividades WHERE id = %s AND usuario = %s",
                                 [_id(id_), usuario]).rowcount
        if not apagou:
            raise NaoEncontrada(_NAO_ACHOU)

    # --- o que foi feito -------------------------------------------------------------------
    def _conferir_conclusao(self, a: dict, dia: dt.date, feedback: str) -> None:
        if dia > self.hoje():
            raise ValueError("só dá para concluir até hoje")
        if a["exige_feedback"] and not feedback:
            raise ValueError("esta atividade pede um feedback para ser concluída")
        with self.banco.conexao() as con:
            ja_feita = con.execute("SELECT 1 FROM agenda_registros WHERE atividade = %s AND dia = %s",
                                   [a["id"], dia]).fetchone()
        if not ja_feita and not ocorre(a, dia, self._calendario([a])):
            raise ValueError("a atividade não acontece neste dia")

    def concluir(self, usuario: int, id_, dia, feedback) -> dict:
        """Marca o dia como feito, com o feedback; se já estava feito, troca o feedback."""
        id_, dia = _id(id_), _data(dia, "da conclusão")
        feedback = _texto(feedback, "o feedback")
        self._conferir_conclusao(self._obter(usuario, id_), dia, feedback)
        with self.banco.conexao() as con:
            linha = con.execute(
                "INSERT INTO agenda_registros (atividade, dia, feedback) SELECT id, %s, %s FROM agenda_atividades "
                "WHERE id = %s AND usuario = %s ON CONFLICT (atividade, dia) "
                "DO UPDATE SET feedback = EXCLUDED.feedback, editada_em = now() RETURNING concluida_em, editada_em",
                [dia, feedback, id_, usuario]).fetchone()
        if not linha:
            raise NaoEncontrada(_NAO_ACHOU)
        return {"atividade": id_, "dia": dia.isoformat(), "feita": True, "feedback": feedback,
                "concluida_em": hora(linha[0]), "editada_em": hora(linha[1])}

    def desfazer(self, usuario: int, id_, dia) -> None:
        """Volta o dia para não feito (o feedback dele sai junto)."""
        id_, dia = _id(id_), _data(dia, "da conclusão")
        with self.banco.conexao() as con:
            apagou = con.execute("DELETE FROM agenda_registros r USING agenda_atividades a WHERE r.atividade = a.id "
                                 "AND a.id = %s AND a.usuario = %s AND r.dia = %s", [id_, usuario, dia]).rowcount
        if not apagou:
            raise NaoEncontrada("a atividade não estava concluída neste dia")

    # --- propostas do Assistente -----------------------------------------------------------
    def propor(self, usuario: int, acao: str, atividade=None, dados: dict | None = None, dia=None,
               feedback=None) -> dict:
        """Confere e monta uma proposta, sem gravar: criar (dados), editar (atividade e só os campos que mudam, em
        dados), encerrar, excluir ou concluir (atividade, dia, padrão hoje, e feedback). A resposta do Assistente
        guarda a proposta e mostra o botão que a aplica (aplicar)."""
        if acao not in ACOES:
            raise ValueError(f"ação desconhecida: {acao!r} (use {', '.join(ACOES)})")
        hoje = self.hoje()
        p = {"id": str(uuid.uuid4()), "acao": acao, "atividade": None}
        if acao == "criar":
            a = _valida(dados or {})
            self._conferir_horario(usuario, a)
            return {**p, "titulo": a["titulo"], "dados": _publica(a, hoje), "dia": self._proximo(a, hoje).isoformat()}
        atual = self._obter(usuario, _id(atividade))
        p.update(atividade=atual["id"], titulo=atual["titulo"])
        if acao == "editar":
            antes = _publica(atual, hoje)
            mudados = {k: v for k, v in (dados or {}).items() if k in _GRAVAR}
            if not mudados:
                raise ValueError("diga o que muda na atividade")
            a = _valida({**antes, **mudados})
            depois = _publica(a, hoje)
            rotulos = {"titulo": "Título", "descricao": "Descrição", "inicio": "Início", "hora": "Horário",
                       "hora_fim": "Fim do horário", "ocupado": "Horário ocupado", "quando": "Repetição",
                       "exige_feedback": "Feedback ao concluir"}
            mudancas = [{"campo": r, "de": antes[k], "para": depois[k]} for k, r in rotulos.items()
                        if antes[k] != depois[k]]
            if not mudancas:
                raise ValueError("a atividade já está assim; nada muda")
            if any(atual[c] != a[c] for c in _QUANDO):
                self._conferir_horario(usuario, {**a, "id": atual["id"]})
            return {**p, "dados": depois, "mudancas": mudancas, "dia": self._proximo(a, hoje).isoformat()}
        if acao == "encerrar":
            self._pode_encerrar(atual, hoje)
            if atual["fim"] and atual["fim"] <= hoje:
                raise ValueError(f"a atividade já terminou em {_dm(atual['fim'], hoje)}")
            return {**p, "fim": hoje.isoformat(), "quando": texto_repeticao(atual, hoje)}
        if acao == "excluir":
            with self.banco.conexao() as con:
                n = con.execute("SELECT count(*) FROM agenda_registros WHERE atividade = %s",
                                [atual["id"]]).fetchone()[0]
            return {**p, "quando": texto_repeticao(atual, hoje), "registros": n}
        dia = _data(dia, "da conclusão") if dia else hoje
        feedback = _texto(feedback, "o feedback")
        self._conferir_conclusao(atual, dia, feedback)
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
                self.editar(usuario, atividade, {**atual, **p["dados"]})
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

"""Tarefas da agenda (topo da página Gestão): um prazo (dia e horário opcional), as pessoas que participam e as
subtarefas de cada uma, cada uma com o próprio prazo. As atividades, só de cada pessoa, ficam em bi/agenda.py.

- Quem vê: quem criou e os participantes (agenda_tarefa_pessoas, migração 020; quem criou também está lá). Para quem
  não participa, a tarefa não existe (NaoEncontrada); quem participa mas não pode fazer algo recebe PermissionError,
  com o motivo.
- Na agenda (no_mes): a tarefa no dia do prazo, para todos; cada subtarefa no dia do prazo dela, todas para quem
  criou e só as próprias para o participante. Aberta (obter), a tarefa mostra todas as subtarefas a todos.
- Só quem criou edita e exclui a tarefa e muda prazos. A situação da tarefa (concluir e reabrir também), qualquer
  pessoa dela muda (migração 023: concluida_por guarda quem concluiu). Com autonomia, o participante edita o título e
  a descrição das próprias subtarefas e cria subtarefas para si, com o prazo da tarefa.
- A subtarefa vence até o prazo da tarefa. Conclui o responsável (ou quem criou), em qualquer dia. Concluir a tarefa
  faz as subtarefas abertas contarem como feitas (pela_tarefa) enquanto ela estiver concluída.
- Atrasada: passou do prazo sem concluir; com horário, logo depois dele; sem horário, quando o dia acaba (_vence_em).
  Fica no dia do prazo e, no mês de hoje, a dos dias anteriores também na lista atrasadas.
- Justificativa do atraso (migrações 022 e 027): passado o prazo sem concluir, ou concluída depois dele (venceu), quem
  responde por ela conta por que atrasou: na tarefa, quem criou (justificar); na subtarefa, o responsável
  (justificar_subtarefa). Cada justificativa entra num histórico (agenda_justificativas), com o prazo que tinha
  vencido; não se edita nem se apaga. Todos da tarefa veem; a tarefa continua atrasada até ser concluída.
- Pendências (pendencias): aberta e vencida, sem justificativa do prazo de agora nas últimas 24 horas, a tarefa ou a
  subtarefa bloqueia o painel de quem responde por ela até ele justificar (web/js/avisos.js).
- Quadro (kanban, quadro): as tarefas em três colunas pela situação, a fazer, fazendo (iniciada_em, migração 021) ou
  concluída (concluida_em manda). Qualquer pessoa da tarefa muda ela de coluna (mover); a subtarefa
  (mover_subtarefa), o responsável ou quem criou. As concluídas ficam no quadro por DIAS_NO_QUADRO dias.
- versao: sobe a cada mudança na tarefa, nas pessoas ou nas subtarefas (concluir não conta). Editar confere, para o
  Salvar de quem criou não apagar uma subtarefa que um participante acabou de criar.
- Horário ocupado (migração 026, bi/agenda.py): o horário da tarefa vale para todas as pessoas dela; o da subtarefa,
  para o responsável. Um horário que entra ou muda (tarefa nova, prazo mudado, pessoa nova numa tarefa com horário,
  subtarefa nova ou passada para outro) não pode cair no horário ocupado da pessoa, nem num evento ocupado do Google
  dela (bi/google_agenda.py); o do Google de quem grava só avisa (avisos, na resposta).
- Avisos (o sino, bi/notificacoes.py, migração 028): cada gravação avisa, na mesma transação, quem precisa saber:
  quem entrou na tarefa, o responsável pela subtarefa nova, passada para ele ou com o prazo mudado, os participantes
  quando o prazo da tarefa muda, quem criou a tarefa quando uma subtarefa é concluída ou justificada e todos da
  tarefa quando ela é concluída. Os avisos de prazo (vence em breve, venceu) nascem em gerar_avisos.
"""
from __future__ import annotations

import datetime as dt

from .agenda import (MAX_TEXTO, _curto, _data, _dm, _hhmm, _hora, _id, _texto, _titulo, calendario, conferir_pontos,
                     travar_horarios)
from .banco import Banco, hora
from .conversas import NaoEncontrada
from .notificacoes import avisar, limpar

MAX_PESSOAS = 30      # participantes de uma tarefa, sem quem criou
MAX_SUBTAREFAS = 50
# O título da subtarefa aceita um texto longo (migração 030): no formulário da tarefa, é o único texto dela. Nas
# mensagens e nos avisos do sino, vai cortado (_curto).
MAX_TITULO_SUB = MAX_TEXTO
DIAS_NO_QUADRO = 30   # a tarefa concluída fica na coluna Concluída do quadro por estes dias
_NAO_ACHOU = "tarefa não encontrada; ela pode ter sido excluída ou você não participa mais dela"
_NAO_ACHOU_SUB = "subtarefa não encontrada; ela pode ter sido excluída"
_MUDOU = "a tarefa acabou de mudar; abra de novo e repita"
_NAO_ATRASOU = "{} não atrasou: a justificativa é para depois do prazo"
RENOVAR = dt.timedelta(hours=24)  # vencida e aberta, a justificativa do prazo é pedida de novo depois disto
DIAS_VENCEU = 7  # o aviso "venceu" (para quem criou a tarefa) sai só para os prazos vencidos nestes últimos dias
# Quem pode participar: os usuários ativos com a página Gestão, onde fica a agenda (o administrador tem todas).
_COM_GESTAO = "ativo AND (papel = 'admin' OR 'gestao' = ANY(coalesce(paginas, '{}')))"
_T = ("id", "criador", "criador_nome", "titulo", "descricao", "prazo", "hora", "iniciada_em", "concluida_em", "versao",
      "concluida_por", "concluida_por_nome")
_S = ("id", "titulo", "descricao", "prazo", "hora", "responsavel", "responsavel_nome", "iniciada_em", "concluida_em",
      "concluida_por", "concluida_por_nome")
_J = ("texto", "prazo", "hora", "criada_em", "usuario", "usuario_nome")  # uma justificativa do histórico
# A situação (a coluna do quadro) e o que ela grava; o começo fica de quando começou, mesmo indo e voltando. A hora
# vem do relógio da classe (%(agora)s), que os testes fixam.
_SITUACOES = {"a_fazer": "iniciada_em = NULL, concluida_em = NULL",
              "fazendo": "iniciada_em = coalesce(iniciada_em, %(agora)s), concluida_em = NULL",
              "concluida": "concluida_em = coalesce(concluida_em, %(agora)s)"}


def _mudar_situacao(situacao: str | None) -> str:
    """O SET de uma mudança de situação da tarefa ou da subtarefa (None: desfaz a conclusão, e ela volta para onde
    estava). concluida_por fica com quem concluiu primeiro (%(eu)s); concluir de novo não muda nada. Os parâmetros:
    eu, agora e o id."""
    if situacao is None:
        return "concluida_em = NULL, concluida_por = NULL"
    if situacao == "concluida":
        return ("concluida_por = CASE WHEN concluida_em IS NULL THEN %(eu)s ELSE concluida_por END, "
                + _SITUACOES[situacao])
    return f"{_SITUACOES[situacao]}, concluida_por = NULL"
# As tarefas de quem vê com algo no mês: a tarefa ou uma subtarefa que ele vê vencendo nele ou, no mês de hoje,
# atrasada (de qualquer mês).
_DO_MES = """SELECT t.id FROM agenda_tarefas t
JOIN agenda_tarefa_pessoas eu ON eu.tarefa = t.id AND eu.usuario = %(eu)s
WHERE t.prazo BETWEEN %(de)s AND %(ate)s
   OR (%(atrasadas)s AND t.concluida_em IS NULL AND t.prazo < %(hoje)s)
   OR EXISTS (SELECT 1 FROM agenda_subtarefas s WHERE s.tarefa = t.id
              AND (t.criador = %(eu)s OR s.responsavel = %(eu)s)
              AND (s.prazo BETWEEN %(de)s AND %(ate)s
                   OR (%(atrasadas)s AND t.concluida_em IS NULL AND s.concluida_em IS NULL AND s.prazo < %(hoje)s)))"""


def _situacao(valor) -> str:
    if not isinstance(valor, str) or valor not in _SITUACOES:
        raise ValueError(f"situação inválida: {valor!r} (a_fazer, fazendo ou concluida)")
    return valor


def _na_coluna(concluida: bool, iniciada_em) -> str:
    return "concluida" if concluida else "fazendo" if iniciada_em else "a_fazer"


def _vence_em(prazo: dt.date, h: dt.time | None) -> dt.datetime:
    """Quando o prazo vence (hora local, sem fuso): no horário dele ou, sem horário, quando o dia acaba."""
    return dt.datetime.combine(prazo, h) if h else dt.datetime.combine(prazo + dt.timedelta(days=1), dt.time())


def _local(momento: dt.datetime) -> dt.datetime:
    """Um timestamptz do banco na hora local, sem fuso (para comparar com o relógio da classe)."""
    return momento.astimezone().replace(tzinfo=None)


def _venceu(prazo: dt.date, h: dt.time | None, concluida_em: dt.datetime | None, agora: dt.datetime) -> bool:
    """Passou do prazo sem concluir, ou foi concluída depois dele: o atraso pode ser justificado."""
    return (_local(concluida_em) if concluida_em else agora) > _vence_em(prazo, h)


def _pessoa(valor) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"pessoa inválida: {valor!r}") from None


def _ate_o_prazo(prazo: dt.date, h: dt.time | None, prazo_tarefa: dt.date, h_tarefa: dt.time | None) -> bool:
    """A subtarefa vence até o prazo da tarefa? No mesmo dia, o horário só conta quando os dois têm."""
    if prazo != prazo_tarefa:
        return prazo < prazo_tarefa
    return h is None or h_tarefa is None or h <= h_tarefa


def _texto_prazo(prazo: dt.date, h: dt.time | None, hoje: dt.date) -> str:
    """'30/10' ou '30/10 às 14:00'."""
    return f"{_dm(prazo, hoje)} às {_hhmm(h)}" if h else _dm(prazo, hoje)


def _valida_sub(s: dict, t: dict, pessoas: set[int], responsavel: int) -> dict:
    """Uma subtarefa da tarefa t (prazo e hora já conferidos). Sem prazo, vence com a tarefa (e no horário dela); sem
    responsável, fica com `responsavel`. pessoas: quem participa da tarefa (com quem criou)."""
    titulo = _titulo(s.get("titulo"), "da subtarefa", MAX_TITULO_SUB)
    resp = responsavel if s.get("responsavel") in (None, "") else _pessoa(s["responsavel"])
    if resp not in pessoas:
        raise ValueError(f"o responsável pela subtarefa “{_curto(titulo)}” não participa da tarefa: escolha outra "
                         "pessoa ou tire a subtarefa")
    if s.get("prazo"):
        prazo, h = _data(s["prazo"], f"da subtarefa “{_curto(titulo)}”"), _hora(s.get("hora"))
    else:
        prazo, h = t["prazo"], _hora(s["hora"]) if s.get("hora") else t["hora"]
    if not _ate_o_prazo(prazo, h, t["prazo"], t["hora"]):
        limite = _texto_prazo(t["prazo"], t["hora"], t["prazo"])
        raise ValueError(f"a subtarefa “{_curto(titulo)}” vence depois da tarefa ({limite}): o prazo dela vai até o "
                         "da tarefa")
    return {"id": _id(s["id"], _NAO_ACHOU_SUB) if s.get("id") else None, "titulo": titulo,
            "descricao": _texto(s.get("descricao"), "a descrição"), "responsavel": resp, "prazo": prazo, "hora": h}


def _valida_tarefa(dados: dict, criador: int) -> dict:
    """A tarefa como vai para o banco: participantes {id: autonomia}, sem quem criou, e as subtarefas (_valida_sub)."""
    if not dados.get("prazo"):
        raise ValueError("escolha o prazo da tarefa")
    t = {"titulo": _titulo(dados.get("titulo"), "da tarefa"),
         "descricao": _texto(dados.get("descricao"), "a descrição"), "prazo": _data(dados["prazo"], "do prazo"),
         "hora": _hora(dados.get("hora")), "participantes": {}}
    for p in dados.get("participantes") or []:
        id_ = _pessoa(p.get("id") if isinstance(p, dict) else p)
        if id_ != criador:
            t["participantes"][id_] = isinstance(p, dict) and bool(p.get("autonomia"))
    if len(t["participantes"]) > MAX_PESSOAS:
        raise ValueError(f"a tarefa pode ter até {MAX_PESSOAS} participantes")
    subtarefas = dados.get("subtarefas") or []
    if len(subtarefas) > MAX_SUBTAREFAS:
        raise ValueError(f"a tarefa pode ter até {MAX_SUBTAREFAS} subtarefas")
    pessoas = {criador, *t["participantes"]}
    t["subtarefas"] = [_valida_sub(s, t, pessoas, criador) for s in subtarefas]
    return t


def _proibido_mudar(dados: dict, s: dict) -> str | None:
    """O que o participante pediu para mudar na subtarefa e só quem criou muda (o mesmo valor de antes não conta)."""
    if "prazo" in dados and str(dados["prazo"] or "")[:10] != s["prazo"].isoformat():
        return "o prazo"
    if "hora" in dados and _hora(dados["hora"]) != s["hora"]:
        return "o prazo"
    if "responsavel" in dados and str(dados["responsavel"]) != str(s["responsavel"]):
        return "o responsável"
    return None


class Tarefas:
    def __init__(self, banco: Banco, configuracao=None, *, hoje=None, agora=None, google=None):
        """configuracao: as regras, de onde vem o calendário dos dias úteis (o horário ocupado que pula feriados).
        hoje e agora: o relógio (os testes fixam; só com hoje, agora é a meia-noite dele). google: o Google Agenda de
        cada pessoa (bi/google_agenda.py), que também ocupa horários."""
        self.banco = banco
        self.configuracao = configuracao
        self.google = google
        if agora is None:
            agora = (lambda: dt.datetime.combine(hoje(), dt.time())) if hoje else dt.datetime.now
        self.agora = agora
        self.hoje = hoje or (lambda: self.agora().date())

    def _parametros(self, usuario: int, id_: int) -> dict:
        """Os parâmetros de _mudar_situacao (agora com o fuso, para o timestamptz)."""
        return {"eu": usuario, "id": id_, "agora": self.agora().astimezone()}

    @staticmethod
    def _ponto_tarefa(t: dict, pessoas) -> list[tuple]:
        """O horário da tarefa, para cada pessoa (o que conferir_pontos recebe)."""
        return [(p, t["prazo"], t["hora"], f"a tarefa “{t['titulo']}”") for p in sorted(pessoas)] if t["hora"] else []

    @staticmethod
    def _ponto_sub(s: dict) -> list[tuple]:
        return [(s["responsavel"], s["prazo"], s["hora"], f"a subtarefa “{_curto(s['titulo'])}”")] if s["hora"] else []

    def _conferir_horarios(self, con, cal, pontos: list[tuple], eu: int) -> list[str]:
        """Os horários que entram ou mudam contra o horário ocupado de cada pessoa (bi/agenda.py), com a trava delas
        (depois da trava da tarefa). Devolve os avisos de quem grava (o Google dele: grava assim mesmo)."""
        pontos = [p for p in pontos if p[1] >= self.hoje()]
        if not pontos:
            return []
        travar_horarios(con, {p[0] for p in pontos})
        return conferir_pontos(con, cal, self.hoje(), pontos, eu, self.google)

    # --- leitura ---------------------------------------------------------------------------
    def pessoas(self, usuario: int) -> dict:
        """Quem pode participar de uma tarefa (sem quem pergunta) e quem pergunta (eu: o formulário põe como
        responsável)."""
        with self.banco.conexao() as con:
            eu = con.execute("SELECT id, nome FROM usuarios WHERE id = %s", [usuario]).fetchone()
            linhas = con.execute(f"SELECT id, nome FROM usuarios WHERE {_COM_GESTAO} AND id <> %s "
                                 "ORDER BY lower(nome), id", [usuario]).fetchall()
        if not eu:
            raise NaoEncontrada("seu usuário não existe mais")
        return {"eu": {"id": eu[0], "nome": eu[1]}, "pessoas": [{"id": i, "nome": n} for i, n in linhas]}

    @staticmethod
    def _carregar(con, ids: list[int]) -> list[dict]:
        """As tarefas (pelo prazo), cada uma com as pessoas (pelo nome), as subtarefas (pelo prazo) e as justificativas
        da tarefa e de cada subtarefa (da mais nova para a mais antiga)."""
        if not ids:
            return []
        linhas = con.execute(
            "SELECT t.id, t.criador, u.nome, t.titulo, t.descricao, t.prazo, t.hora, t.iniciada_em, t.concluida_em, "
            "t.versao, t.concluida_por, c.nome "
            "FROM agenda_tarefas t JOIN usuarios u ON u.id = t.criador LEFT JOIN usuarios c ON c.id = t.concluida_por "
            "WHERE t.id = ANY(%s::bigint[]) "
            "ORDER BY t.prazo, t.hora NULLS LAST, t.id", [ids])
        tarefas = {r[0]: {**dict(zip(_T, r)), "pessoas": [], "subtarefas": [], "justificativas": []} for r in linhas}
        for tarefa, usuario, nome, autonomia in con.execute(
                "SELECT p.tarefa, p.usuario, u.nome, p.autonomia FROM agenda_tarefa_pessoas p "
                "JOIN usuarios u ON u.id = p.usuario WHERE p.tarefa = ANY(%s::bigint[]) ORDER BY lower(u.nome), u.id",
                [ids]):
            tarefas[tarefa]["pessoas"].append({"id": usuario, "nome": nome, "autonomia": autonomia})
        subs = {}
        for r in con.execute(
                "SELECT s.tarefa, s.id, s.titulo, s.descricao, s.prazo, s.hora, s.responsavel, u.nome, s.iniciada_em, "
                "s.concluida_em, s.concluida_por, c.nome FROM agenda_subtarefas s "
                "JOIN usuarios u ON u.id = s.responsavel LEFT JOIN usuarios c ON c.id = s.concluida_por "
                "WHERE s.tarefa = ANY(%s::bigint[]) "
                "ORDER BY s.prazo, s.hora NULLS LAST, s.id", [ids]):
            subs[r[1]] = {**dict(zip(_S, r[1:])), "justificativas": []}
            tarefas[r[0]]["subtarefas"].append(subs[r[1]])
        for tarefa, sub, *j in con.execute(
                "SELECT j.tarefa, j.subtarefa, j.texto, j.prazo, j.hora, j.criada_em, j.usuario, u.nome "
                "FROM agenda_justificativas j LEFT JOIN usuarios u ON u.id = j.usuario "
                "WHERE j.tarefa = ANY(%s::bigint[]) ORDER BY j.criada_em DESC, j.id DESC", [ids]):
            (subs[sub] if sub else tarefas[tarefa])["justificativas"].append(dict(zip(_J, j)))
        return list(tarefas.values())

    @staticmethod
    def _justificativas(x: dict) -> list[dict]:
        """O histórico de justificativas de x (a tarefa ou a subtarefa) como a página vê: do_prazo diz se ela é do
        prazo de agora (a de um prazo de antes, que foi prorrogado, não vale para o novo)."""
        return [{"texto": j["texto"], "criada_em": hora(j["criada_em"]),
                 "por": {"id": j["usuario"], "nome": j["usuario_nome"]} if j["usuario"] else None,
                 "prazo": j["prazo"].isoformat(), "hora": _hhmm(j["hora"]),
                 "do_prazo": (j["prazo"], j["hora"]) == (x["prazo"], x["hora"])} for j in x["justificativas"]]

    @classmethod
    def _publica(cls, t: dict, eu: int, agora: dt.datetime) -> dict:
        """A tarefa como a página e a agenda de `eu` veem, com o que ele pode fazer nela (pode; concluir vale também
        para mudar de coluna no quadro). venceu: passou do prazo sem concluir ou foi concluída depois dele (a
        subtarefa aberta de uma tarefa concluída, pela conclusão da tarefa)."""
        criador = t["criador"] == eu
        autonomia = not criador and any(p["id"] == eu and p["autonomia"] for p in t["pessoas"])
        concluida = t["concluida_em"] is not None
        subtarefas = []
        for s in t["subtarefas"]:
            minha, feita = s["responsavel"] == eu, concluida or s["concluida_em"] is not None
            venceu = _venceu(s["prazo"], s["hora"], s["concluida_em"] or t["concluida_em"], agora)
            subtarefas.append({
                "id": s["id"], "titulo": s["titulo"], "descricao": s["descricao"], "prazo": s["prazo"].isoformat(),
                "hora": _hhmm(s["hora"]), "responsavel": {"id": s["responsavel"], "nome": s["responsavel_nome"]},
                "minha": minha, "feita": feita, "pela_tarefa": concluida and s["concluida_em"] is None,
                "situacao": _na_coluna(feita, s["iniciada_em"]), "iniciada_em": hora(s["iniciada_em"]),
                "concluida_em": hora(s["concluida_em"]),
                "concluida_por": ({"id": s["concluida_por"], "nome": s["concluida_por_nome"]}
                                  if s["concluida_por"] else None),
                "atrasada": not feita and agora > _vence_em(s["prazo"], s["hora"]), "venceu": venceu,
                "justificativas": cls._justificativas(s),
                "pode": {"concluir": (criador or minha) and not concluida,
                         "editar_texto": criador or (minha and autonomia), "editar_prazo": criador,
                         "justificar": minha and venceu}})
        venceu = _venceu(t["prazo"], t["hora"], t["concluida_em"], agora)
        return {"id": t["id"], "titulo": t["titulo"], "descricao": t["descricao"], "prazo": t["prazo"].isoformat(),
                "hora": _hhmm(t["hora"]), "versao": t["versao"],
                "criador": {"id": t["criador"], "nome": t["criador_nome"]}, "eu": eu, "eu_criador": criador,
                "minha_autonomia": autonomia,
                "participantes": [p for p in t["pessoas"] if p["id"] != t["criador"]],
                "feita": concluida, "situacao": _na_coluna(concluida, t["iniciada_em"]),
                "iniciada_em": hora(t["iniciada_em"]), "concluida_em": hora(t["concluida_em"]),
                "concluida_por": ({"id": t["concluida_por"], "nome": t["concluida_por_nome"]}
                                  if t["concluida_por"] else None),
                "atrasada": not concluida and agora > _vence_em(t["prazo"], t["hora"]), "venceu": venceu,
                "justificativas": cls._justificativas(t),
                "feitas": sum(s["feita"] for s in subtarefas), "total": len(subtarefas),
                "pode": {"editar": criador, "concluir": True,  # a situação da tarefa, qualquer pessoa dela muda
                         "criar_subtarefa": (criador or autonomia) and not concluida,
                         "justificar": criador and venceu},
                "subtarefas": subtarefas}

    def obter(self, usuario: int, id_) -> dict:
        """A tarefa aberta: todas as subtarefas, de todos, para quem participa."""
        id_ = _id(id_, _NAO_ACHOU)
        with self.banco.conexao() as con:
            if not con.execute("SELECT 1 FROM agenda_tarefa_pessoas WHERE tarefa = %s AND usuario = %s",
                               [id_, usuario]).fetchone():
                raise NaoEncontrada(_NAO_ACHOU)
            t, = self._carregar(con, [id_])
        return self._publica(t, usuario, self.agora())

    def no_mes(self, usuario: int, m: dict) -> dict:
        """Acrescenta ao mês da agenda (Agenda.mes, que dá o dia de hoje) as tarefas de quem vê: em cada dia, a tarefa e
        as subtarefas que vencem nele (dias[].tarefas: {tarefa, subtarefa, feita}, as com horário primeiro); no mês de
        hoje, as atrasadas dos dias anteriores, de qualquer mês (atrasadas, as mais antigas primeiro; a que venceu hoje
        fica só no dia de hoje); e as tarefas citadas (tarefas)."""
        hoje, agora = dt.date.fromisoformat(m["hoje"]), self.agora()
        dias = [dt.date.fromisoformat(d["data"]) for d in m["dias"]]
        com_atrasadas = (dias[0].year, dias[0].month) == (hoje.year, hoje.month)
        with self.banco.conexao() as con:
            ids = [r[0] for r in con.execute(_DO_MES, {"eu": usuario, "de": dias[0], "ate": dias[-1], "hoje": hoje,
                                                       "atrasadas": com_atrasadas})]
            tarefas = self._carregar(con, ids)
        por_dia, atrasadas, publicadas = {d: [] for d in dias}, [], []
        for t in tarefas:
            p = self._publica(t, usuario, agora)
            publicadas.append(p)
            itens = [(t["prazo"], t["hora"], {"tarefa": t["id"], "subtarefa": None, "feita": p["feita"]},
                      p["atrasada"])]
            itens += [(s["prazo"], s["hora"], {"tarefa": t["id"], "subtarefa": s["id"], "feita": sp["feita"]},
                       sp["atrasada"])
                      for s, sp in zip(t["subtarefas"], p["subtarefas"]) if p["eu_criador"] or sp["minha"]]
            for prazo, h, ref, atrasada in itens:
                if prazo in por_dia:
                    por_dia[prazo].append((h, ref))
                if com_atrasadas and atrasada and prazo < hoje:
                    atrasadas.append((prazo, h, ref))

        def ordem(h, ref):  # as com horário primeiro; a tarefa antes das subtarefas dela
            return h is None, h or dt.time(), ref["tarefa"], ref["subtarefa"] or 0

        return {**m, "dias": [{**d, "tarefas": [r for _, r in sorted(por_dia[dia], key=lambda x: ordem(*x))]}
                              for d, dia in zip(m["dias"], dias)],
                "atrasadas": [r for _, _, r in sorted(atrasadas, key=lambda x: (x[0], *ordem(x[1], x[2])))],
                "tarefas": publicadas}

    def quadro(self, usuario: int) -> dict:
        """O quadro (kanban) de quem vê: as tarefas de que participa, abertas e as concluídas nos últimos
        DIAS_NO_QUADRO dias, cada uma com a situação (a coluna) e as subtarefas de todos (o card mostra o andamento)."""
        hoje = self.hoje()
        with self.banco.conexao() as con:
            ids = [r[0] for r in con.execute(
                "SELECT t.id FROM agenda_tarefas t "
                "JOIN agenda_tarefa_pessoas eu ON eu.tarefa = t.id AND eu.usuario = %s "
                "WHERE t.concluida_em IS NULL OR t.concluida_em >= %s",
                [usuario, hoje - dt.timedelta(days=DIAS_NO_QUADRO)])]
            tarefas = self._carregar(con, ids)
        agora = self.agora()
        return {"hoje": hoje.isoformat(), "dias_concluidas": DIAS_NO_QUADRO,
                "tarefas": [self._publica(t, usuario, agora) for t in tarefas]}

    def pendencias(self, usuario: int) -> list[dict]:
        """O que a pessoa precisa justificar agora (o painel fica bloqueado até ela justificar): as tarefas que ela
        criou e as subtarefas dela, abertas e vencidas, sem justificativa do prazo de agora nas últimas RENOVAR horas.
        Cada uma com a última justificativa (mesmo de um prazo de antes), quem criou a tarefa e, na tarefa, quantas
        subtarefas ainda faltam (concluir leva todas)."""
        agora = self.agora()
        with self.banco.conexao() as con:
            itens = [i for i in con.execute(
                "SELECT t.id, NULL::bigint, t.titulo, t.prazo, t.hora, t.titulo, t.criador, c.nome, "
                "(SELECT count(*) FROM agenda_subtarefas s WHERE s.tarefa = t.id AND s.concluida_em IS NULL) "
                "FROM agenda_tarefas t JOIN usuarios c ON c.id = t.criador "
                "WHERE t.criador = %(eu)s AND t.concluida_em IS NULL "
                "UNION ALL SELECT t.id, s.id, s.titulo, s.prazo, s.hora, t.titulo, t.criador, c.nome, 0 "
                "FROM agenda_subtarefas s JOIN agenda_tarefas t ON t.id = s.tarefa JOIN usuarios c ON c.id = t.criador "
                "WHERE s.responsavel = %(eu)s AND s.concluida_em IS NULL AND t.concluida_em IS NULL "
                "ORDER BY 4, 5 NULLS LAST, 1, 2 NULLS FIRST", {"eu": usuario}) if agora > _vence_em(i[3], i[4])]
            historico = {}
            if itens:
                for tarefa, sub, *j in con.execute(
                        "SELECT j.tarefa, j.subtarefa, j.texto, j.prazo, j.hora, j.criada_em, j.usuario, u.nome "
                        "FROM agenda_justificativas j LEFT JOIN usuarios u ON u.id = j.usuario "
                        "WHERE j.tarefa = ANY(%s::bigint[]) ORDER BY j.criada_em DESC, j.id DESC",
                        [sorted({i[0] for i in itens})]):
                    historico.setdefault((tarefa, sub), []).append(dict(zip(_J, j)))
        saida = []
        for tarefa, sub, titulo, prazo, h, titulo_tarefa, criador, nome_criador, abertas in itens:
            js = historico.get((tarefa, sub), [])
            if any((j["prazo"], j["hora"]) == (prazo, h) and _local(j["criada_em"]) > agora - RENOVAR for j in js):
                continue
            ultima = js[0] if js else None
            saida.append({
                "tarefa": tarefa, "subtarefa": sub, "titulo": titulo, "tarefa_titulo": titulo_tarefa,
                "prazo": prazo.isoformat(), "hora": _hhmm(h), "vence_em": _vence_em(prazo, h).isoformat(),
                "criador": {"id": criador, "nome": nome_criador}, "eu_criador": criador == usuario,
                "abertas": abertas,
                "ultima": ultima and {"texto": ultima["texto"], "criada_em": hora(ultima["criada_em"]),
                                      "por": ultima["usuario_nome"], "minha": ultima["usuario"] == usuario,
                                      "do_prazo": (ultima["prazo"], ultima["hora"]) == (prazo, h)}})
        return saida

    # --- apoio das gravações ---------------------------------------------------------------
    @staticmethod
    def _travar(con, usuario: int, id_: int, nao_achou: str = _NAO_ACHOU) -> dict:
        """A tarefa, travada até o fim da transação, e o papel de quem mexe (eu_criador, autonomia)."""
        linha = con.execute(
            "SELECT t.id, t.criador, t.titulo, t.prazo, t.hora, t.versao, t.concluida_em, p.autonomia "
            "FROM agenda_tarefas t JOIN agenda_tarefa_pessoas p ON p.tarefa = t.id AND p.usuario = %s "
            "WHERE t.id = %s FOR UPDATE OF t", [usuario, id_]).fetchone()
        if not linha:
            raise NaoEncontrada(nao_achou)
        t = dict(zip(("id", "criador", "titulo", "prazo", "hora", "versao", "concluida_em", "autonomia"), linha))
        return {**t, "eu_criador": t["criador"] == usuario}

    def _travar_sub(self, con, usuario: int, id_) -> tuple[dict, dict]:
        """A subtarefa e a tarefa dela (travada: as gravações numa tarefa vão uma de cada vez)."""
        id_ = _id(id_, _NAO_ACHOU_SUB)
        linha = con.execute("SELECT tarefa FROM agenda_subtarefas WHERE id = %s", [id_]).fetchone()
        if not linha:
            raise NaoEncontrada(_NAO_ACHOU_SUB)
        t = self._travar(con, usuario, linha[0], _NAO_ACHOU_SUB)
        linha = con.execute("SELECT id, titulo, descricao, prazo, hora, responsavel, concluida_em "
                            "FROM agenda_subtarefas WHERE id = %s AND tarefa = %s", [id_, t["id"]]).fetchone()
        if not linha:  # saiu enquanto esperava a trava
            raise NaoEncontrada(_NAO_ACHOU_SUB)
        return t, dict(zip(("id", "titulo", "descricao", "prazo", "hora", "responsavel", "concluida_em"), linha))

    # --- avisos (o sino, bi/notificacoes.py) ---------------------------------------------------
    @staticmethod
    def _nome(con, usuario: int) -> str:
        linha = con.execute("SELECT nome FROM usuarios WHERE id = %s", [usuario]).fetchone()
        return linha[0] if linha else "Alguém"

    def _prazo(self, prazo: dt.date, h: dt.time | None) -> str:
        return _texto_prazo(prazo, h, self.hoje())

    def _avisar_incluido(self, con, pessoa: int, nome: str, eu: int, tarefa: int, t: dict) -> None:
        """Quem entrou na tarefa: um aviso só, com quantas subtarefas são dele."""
        n = sum(s["responsavel"] == pessoa for s in t["subtarefas"])
        subs = f", com {n} subtarefa{'s' if n > 1 else ''} para você" if n else ""
        avisar(con, [pessoa], "incluido", f"{nome} incluiu você na tarefa “{t['titulo']}” (prazo "
               f"{self._prazo(t['prazo'], t['hora'])}){subs}", eu, tarefa)

    def _avisar_sub(self, con, s: dict, antes: tuple | None, nome: str, eu: int, tarefa: int) -> None:
        """A subtarefa nova ou mudada, para o responsável: criada ou passada para ele, ou com o prazo mudado. antes:
        (responsavel, prazo, hora) de antes da mudança (None: nova)."""
        prazo, titulo = self._prazo(s["prazo"], s["hora"]), _curto(s["titulo"])
        if antes is None:
            avisar(con, [s["responsavel"]], "subtarefa_nova", f"{nome} criou a subtarefa “{titulo}” para você "
                   f"(até {prazo})", eu, tarefa)
        elif s["responsavel"] != antes[0]:
            avisar(con, [s["responsavel"]], "subtarefa_nova", f"{nome} passou a subtarefa “{titulo}” para você "
                   f"(até {prazo})", eu, tarefa, s["id"])
        elif (s["prazo"], s["hora"]) != tuple(antes[1:]):
            avisar(con, [s["responsavel"]], "prazo_mudou", f"{nome} mudou o prazo de “{titulo}” para {prazo}", eu,
                   tarefa, s["id"])

    def _avisar_conclusao(self, con, t: dict, s: dict | None, eu: int) -> None:
        """Concluída agora: a subtarefa, para quem criou a tarefa; a tarefa, para todos dela (menos quem concluiu)."""
        nome = self._nome(con, eu)
        if s:
            avisar(con, [t["criador"]], "concluida", f"{nome} concluiu a subtarefa “{_curto(s['titulo'])}” (tarefa "
                   f"“{t['titulo']}”)", eu, t["id"], s["id"])
        else:
            avisar(con, self._pessoas_da(con, t["id"]), "concluida", f"{nome} concluiu a tarefa “{t['titulo']}”", eu,
                   t["id"])

    def gerar_avisos(self, usuario: int) -> None:
        """Os avisos de prazo de quem pergunta (o painel pergunta a cada minuto), cada um uma vez só por item e por
        prazo, e a limpeza dos antigos. Vence em breve: no dia de antes e no do prazo, até vencer (a subtarefa para o
        responsável, a tarefa para todos dela). Venceu: para quem criou, a subtarefa de outra pessoa que venceu nos
        últimos DIAS_VENCEU dias (a de antes disso não avisa, para não chegar uma enxurrada de atrasos antigos)."""
        agora = self.agora()
        hoje = agora.date()
        with self.banco.conexao() as con:
            limpar(con, usuario)
            perto = con.execute(
                "SELECT t.id, NULL::bigint, t.titulo, t.prazo, t.hora FROM agenda_tarefas t "
                "JOIN agenda_tarefa_pessoas p ON p.tarefa = t.id AND p.usuario = %(eu)s "
                "WHERE t.concluida_em IS NULL AND t.prazo BETWEEN %(hoje)s AND %(amanha)s "
                "UNION ALL SELECT s.tarefa, s.id, s.titulo, s.prazo, s.hora FROM agenda_subtarefas s "
                "JOIN agenda_tarefas t ON t.id = s.tarefa WHERE s.responsavel = %(eu)s AND s.concluida_em IS NULL "
                "AND t.concluida_em IS NULL AND s.prazo BETWEEN %(hoje)s AND %(amanha)s",
                {"eu": usuario, "hoje": hoje, "amanha": hoje + dt.timedelta(days=1)}).fetchall()
            for tarefa, sub, titulo, prazo, h in perto:
                if agora > _vence_em(prazo, h):
                    continue  # venceu: aí é a justificativa
                quando = (f"hoje{f' às {_hhmm(h)}' if h else ''}" if prazo == hoje
                          else f"amanhã ({self._prazo(prazo, h)})")
                avisar(con, [usuario], "vence_em_breve", f"“{_curto(titulo)}” vence {quando}", None, tarefa, sub,
                       chave=f"vence:{'s' if sub else 't'}{sub or tarefa}:{prazo}:{_hhmm(h) or ''}")
            vencidas = con.execute(
                "SELECT s.tarefa, s.id, s.titulo, s.prazo, s.hora, u.nome FROM agenda_subtarefas s "
                "JOIN agenda_tarefas t ON t.id = s.tarefa JOIN usuarios u ON u.id = s.responsavel "
                "WHERE t.criador = %(eu)s AND s.responsavel <> %(eu)s AND s.concluida_em IS NULL "
                "AND t.concluida_em IS NULL AND s.prazo BETWEEN %(desde)s AND %(hoje)s",
                {"eu": usuario, "desde": hoje - dt.timedelta(days=DIAS_VENCEU), "hoje": hoje}).fetchall()
            for tarefa, sub, titulo, prazo, h, nome in vencidas:
                if agora - dt.timedelta(days=DIAS_VENCEU) < _vence_em(prazo, h) < agora:
                    avisar(con, [usuario], "venceu", f"A subtarefa “{_curto(titulo)}”, de {nome}, venceu sem ser "
                           f"concluída ({self._prazo(prazo, h)})", None, tarefa, sub,
                           chave=f"venceu:s{sub}:{prazo}:{_hhmm(h) or ''}")

    @staticmethod
    def _so_quem_criou(t: dict, o_que: str) -> None:
        if not t["eu_criador"]:
            raise PermissionError(f"só quem criou a tarefa pode {o_que}")

    @staticmethod
    def _aberta(t: dict) -> None:
        if t["concluida_em"]:
            raise ValueError("a tarefa já foi concluída; quem criou precisa reabrir para mexer nas subtarefas")

    @staticmethod
    def _conferir_pessoas(con, ids) -> None:
        """Quem entra na tarefa precisa estar ativo e ter a página Gestão (onde fica a agenda)."""
        ids = list(ids)
        if not ids:
            return
        achados = {r[0] for r in con.execute(f"SELECT id FROM usuarios WHERE id = ANY(%s::bigint[]) AND {_COM_GESTAO}",
                                             [ids])}
        if any(i not in achados for i in ids):
            raise ValueError("pessoa não encontrada, inativa ou sem a página Gestão (onde fica a agenda)")

    @staticmethod
    def _pessoas_da(con, tarefa: int) -> dict[int, bool]:
        return dict(con.execute("SELECT usuario, autonomia FROM agenda_tarefa_pessoas WHERE tarefa = %s", [tarefa]))

    @staticmethod
    def _gravar_pessoas(con, tarefa: int, pessoas: dict[int, bool]) -> None:
        with con.cursor() as cur:
            cur.executemany("INSERT INTO agenda_tarefa_pessoas (tarefa, usuario, autonomia) VALUES (%s, %s, %s) "
                            "ON CONFLICT (tarefa, usuario) DO UPDATE SET autonomia = EXCLUDED.autonomia",
                            [[tarefa, p, a] for p, a in pessoas.items()])

    @staticmethod
    def _inserir_subs(con, tarefa: int, subtarefas: list[dict], criada_por: int) -> None:
        if subtarefas:
            with con.cursor() as cur:
                cur.executemany("INSERT INTO agenda_subtarefas (tarefa, responsavel, titulo, descricao, prazo, hora, "
                                "criada_por) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                                [[tarefa, s["responsavel"], s["titulo"], s["descricao"], s["prazo"], s["hora"],
                                  criada_por] for s in subtarefas])

    @staticmethod
    def _nova_versao(con, tarefa: int) -> None:
        con.execute("UPDATE agenda_tarefas SET versao = versao + 1, atualizada_em = now() WHERE id = %s", [tarefa])

    # --- tarefas (só quem criou) -----------------------------------------------------------
    def criar(self, usuario: int, dados: dict) -> dict:
        """A tarefa, as pessoas e as subtarefas, numa transação só. A resposta traz os avisos do Google de quem criou
        (avisos)."""
        t = _valida_tarefa(dados, usuario)
        cal = calendario(self.configuracao)
        pontos = self._ponto_tarefa(t, {usuario, *t["participantes"]})
        pontos += [p for s in t["subtarefas"] for p in self._ponto_sub(s)]
        with self.banco.conexao() as con:
            self._conferir_pessoas(con, t["participantes"])
            avisos = self._conferir_horarios(con, cal, pontos, usuario)
            linha = con.execute("INSERT INTO agenda_tarefas (criador, titulo, descricao, prazo, hora) "
                                "SELECT id, %(titulo)s, %(descricao)s, %(prazo)s, %(hora)s FROM usuarios "
                                "WHERE id = %(usuario)s RETURNING id", {**t, "usuario": usuario}).fetchone()
            if not linha:
                raise NaoEncontrada("seu usuário não existe mais")
            self._gravar_pessoas(con, linha[0], {usuario: False, **t["participantes"]})
            self._inserir_subs(con, linha[0], t["subtarefas"], usuario)
            nome = self._nome(con, usuario)
            for p in t["participantes"]:  # um aviso por pessoa, com as subtarefas dela
                self._avisar_incluido(con, p, nome, usuario, linha[0], t)
        return {**self.obter(usuario, linha[0]), "avisos": avisos}

    def editar(self, usuario: int, id_, dados: dict, versao) -> dict:
        """Troca tudo: os campos, as pessoas e as subtarefas (as com id mudam, as sem id entram, as que faltam saem; a
        conclusão de cada uma fica). versao: a da tarefa que o formulário abriu (mudou desde então: recusa).
        Só quem entra agora precisa ter a página Gestão; quem já participava fica mesmo sem ela. O horário ocupado é
        conferido só no que entra ou muda: o prazo, as pessoas novas e as subtarefas novas ou mudadas."""
        cal = calendario(self.configuracao)
        with self.banco.conexao() as con:
            t = self._travar(con, usuario, _id(id_, _NAO_ACHOU))
            self._so_quem_criou(t, "editá-la")
            if str(versao) != str(t["versao"]):
                raise ValueError(_MUDOU)
            novo = _valida_tarefa(dados, usuario)
            antes = self._pessoas_da(con, t["id"])
            self._conferir_pessoas(con, [p for p in novo["participantes"] if p not in antes])
            subs_antes = {r[0]: tuple(r[1:]) for r in con.execute(
                "SELECT id, responsavel, prazo, hora FROM agenda_subtarefas WHERE tarefa = %s", [t["id"]])}
            ficam = [s["id"] for s in novo["subtarefas"] if s["id"]]
            if len(set(ficam)) != len(ficam) or any(i not in subs_antes for i in ficam):
                raise ValueError("subtarefa não encontrada nesta tarefa; abra de novo e repita")
            pessoas = {usuario, *novo["participantes"]}
            mudou = (novo["prazo"], novo["hora"]) != (t["prazo"], t["hora"])
            pontos = self._ponto_tarefa(novo, pessoas if mudou else pessoas - set(antes))
            pontos += [p for s in novo["subtarefas"]
                       if not s["id"] or subs_antes[s["id"]] != (s["responsavel"], s["prazo"], s["hora"])
                       for p in self._ponto_sub(s)]
            avisos = self._conferir_horarios(con, cal, pontos, usuario)
            # A ordem importa (o responsável precisa estar na tarefa): primeiro quem entra, depois as subtarefas e só
            # no fim quem sai.
            con.execute("UPDATE agenda_tarefas SET titulo = %(titulo)s, descricao = %(descricao)s, prazo = %(prazo)s, "
                        "hora = %(hora)s, versao = versao + 1, atualizada_em = now() WHERE id = %(id)s",
                        {**novo, "id": t["id"]})
            self._gravar_pessoas(con, t["id"], {usuario: False, **novo["participantes"]})
            con.execute("DELETE FROM agenda_subtarefas WHERE tarefa = %s AND NOT (id = ANY(%s::bigint[]))",
                        [t["id"], ficam])
            if ficam:
                with con.cursor() as cur:
                    cur.executemany("UPDATE agenda_subtarefas SET titulo = %(titulo)s, descricao = %(descricao)s, "
                                    "responsavel = %(responsavel)s, prazo = %(prazo)s, hora = %(hora)s, "
                                    "atualizada_em = now() WHERE id = %(id)s",
                                    [s for s in novo["subtarefas"] if s["id"]])
            self._inserir_subs(con, t["id"], [s for s in novo["subtarefas"] if not s["id"]], usuario)
            con.execute("DELETE FROM agenda_tarefa_pessoas WHERE tarefa = %s AND usuario <> %s "
                        "AND NOT (usuario = ANY(%s::bigint[]))", [t["id"], usuario, list(novo["participantes"])])
            # os avisos: quem entrou (um só, com as subtarefas dele); para quem já estava, o prazo da tarefa mudado e
            # as subtarefas novas, passadas para ele ou com o prazo mudado
            nome = self._nome(con, usuario)
            entraram = [p for p in novo["participantes"] if p not in antes]
            for p in entraram:
                self._avisar_incluido(con, p, nome, usuario, t["id"], novo)
            if mudou:
                prazo = self._prazo(novo["prazo"], novo["hora"])
                avisar(con, [p for p in novo["participantes"] if p in antes], "prazo_mudou",
                       f"{nome} mudou o prazo da tarefa “{novo['titulo']}” para {prazo}", usuario, t["id"])
            for s in novo["subtarefas"]:
                if s["responsavel"] not in entraram:
                    self._avisar_sub(con, s, subs_antes[s["id"]] if s["id"] else None, nome, usuario, t["id"])
        return {**self.obter(usuario, t["id"]), "avisos": avisos}

    def excluir(self, usuario: int, id_) -> None:
        """Apaga a tarefa e as subtarefas, para todos."""
        with self.banco.conexao() as con:
            t = self._travar(con, usuario, _id(id_, _NAO_ACHOU))
            self._so_quem_criou(t, "excluí-la")
            con.execute("DELETE FROM agenda_tarefas WHERE id = %s", [t["id"]])

    def _situar_tarefa(self, usuario: int, id_, situacao: str | None) -> dict:
        """Muda a situação da tarefa (None: desfaz a conclusão); qualquer pessoa da tarefa pode."""
        with self.banco.conexao() as con:
            t = self._travar(con, usuario, _id(id_, _NAO_ACHOU))
            if situacao is None and not t["concluida_em"]:
                raise ValueError("a tarefa não estava concluída")
            con.execute(f"UPDATE agenda_tarefas SET {_mudar_situacao(situacao)} WHERE id = %(id)s",
                        self._parametros(usuario, t["id"]))
            if situacao == "concluida" and not t["concluida_em"]:
                self._avisar_conclusao(con, t, None, usuario)
        return self.obter(usuario, t["id"])

    def concluir(self, usuario: int, id_) -> dict:
        """Conclui a tarefa (as subtarefas abertas passam a contar como feitas); concluir de novo não muda nada."""
        return self._situar_tarefa(usuario, id_, "concluida")

    def desfazer(self, usuario: int, id_) -> dict:
        """Reabre a tarefa: as subtarefas que não tinham sido concluídas voltam a ficar abertas."""
        return self._situar_tarefa(usuario, id_, None)

    def mover(self, usuario: int, id_, situacao) -> dict:
        """Leva a tarefa para outra coluna do quadro: a_fazer, fazendo ou concluida (concluir e reabrir, como
        concluir e desfazer)."""
        return self._situar_tarefa(usuario, id_, _situacao(situacao))

    def _justificar(self, con, tarefa: int, subtarefa: int | None, usuario: int, prazo: dt.date, h: dt.time | None,
                    texto: str) -> None:
        """Acrescenta uma justificativa ao histórico, com o prazo que tinha vencido e a hora do relógio da classe."""
        con.execute("INSERT INTO agenda_justificativas (tarefa, subtarefa, usuario, prazo, hora, texto, criada_em) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [tarefa, subtarefa, usuario, prazo, h, texto, self.agora().astimezone()])

    @staticmethod
    def _texto_justificativa(texto) -> str:
        texto = _texto(texto, "a justificativa")
        if not texto:
            raise ValueError("escreva por que atrasou")
        return texto

    def justificar(self, usuario: int, id_, texto, concluir: bool = False) -> dict:
        """Quem criou conta por que a tarefa atrasou; só depois que ela venceu. A justificativa entra no histórico (não
        se edita nem se apaga). concluir: conclui a tarefa na mesma gravação (para quem já terminou)."""
        texto = self._texto_justificativa(texto)
        with self.banco.conexao() as con:
            t = self._travar(con, usuario, _id(id_, _NAO_ACHOU))
            self._so_quem_criou(t, "justificar o atraso dela")
            if not _venceu(t["prazo"], t["hora"], t["concluida_em"], self.agora()):
                raise ValueError(_NAO_ATRASOU.format("a tarefa ainda"))
            self._justificar(con, t["id"], None, usuario, t["prazo"], t["hora"], texto)
            if concluir and not t["concluida_em"]:
                con.execute(f"UPDATE agenda_tarefas SET {_mudar_situacao('concluida')} WHERE id = %(id)s",
                            self._parametros(usuario, t["id"]))
                self._avisar_conclusao(con, t, None, usuario)
        return self.obter(usuario, t["id"])

    # --- subtarefas ------------------------------------------------------------------------
    def nova_subtarefa(self, usuario: int, tarefa, dados: dict) -> dict:
        """Quem criou acrescenta uma subtarefa para qualquer pessoa da tarefa, com o prazo que quiser (até o da tarefa);
        o participante com autonomia, só para si e com o prazo da tarefa."""
        cal = calendario(self.configuracao)
        with self.banco.conexao() as con:
            t = self._travar(con, usuario, _id(tarefa, _NAO_ACHOU))
            if not t["eu_criador"]:
                if not t["autonomia"]:
                    raise PermissionError("só quem criou a tarefa (ou quem tem autonomia nela) cria subtarefas")
                if dados.get("responsavel") not in (None, "") and str(dados["responsavel"]) != str(usuario):
                    raise PermissionError("com autonomia, você cria subtarefas só para você")
                if dados.get("prazo") or dados.get("hora"):
                    raise PermissionError("só quem criou a tarefa define o prazo; a sua vence com a tarefa")
                dados = {"titulo": dados.get("titulo"), "descricao": dados.get("descricao")}
            self._aberta(t)
            s = _valida_sub(dados, t, set(self._pessoas_da(con, t["id"])), usuario)
            avisos = self._conferir_horarios(con, cal, self._ponto_sub(s), usuario)
            self._inserir_subs(con, t["id"], [s], usuario)
            self._nova_versao(con, t["id"])
            self._avisar_sub(con, s, None, self._nome(con, usuario), usuario, t["id"])
        return {**self.obter(usuario, t["id"]), "avisos": avisos}

    def editar_subtarefa(self, usuario: int, id_, dados: dict) -> dict:
        """Muda só os campos enviados. Quem criou muda tudo; o responsável com autonomia, só o título e a descrição."""
        cal = calendario(self.configuracao)
        with self.banco.conexao() as con:
            t, s = self._travar_sub(con, usuario, id_)
            if not t["eu_criador"]:
                if s["responsavel"] != usuario or not t["autonomia"]:
                    raise PermissionError("só quem criou a tarefa (ou o responsável, com autonomia) edita esta "
                                          "subtarefa")
                if campo := _proibido_mudar(dados, s):
                    raise PermissionError(f"só quem criou a tarefa muda {campo} da subtarefa")
                dados = {k: v for k, v in dados.items() if k in ("titulo", "descricao")}
            atual = {"titulo": s["titulo"], "descricao": s["descricao"], "responsavel": s["responsavel"],
                     "prazo": s["prazo"].isoformat(), "hora": _hhmm(s["hora"])}
            novo = _valida_sub({**atual, **{k: v for k, v in dados.items() if k in atual}}, t,
                               set(self._pessoas_da(con, t["id"])), usuario)
            avisos = []
            if (novo["responsavel"], novo["prazo"], novo["hora"]) != (s["responsavel"], s["prazo"], s["hora"]):
                avisos = self._conferir_horarios(con, cal, self._ponto_sub(novo), usuario)
            con.execute("UPDATE agenda_subtarefas SET titulo = %(titulo)s, descricao = %(descricao)s, "
                        "responsavel = %(responsavel)s, prazo = %(prazo)s, hora = %(hora)s, atualizada_em = now() "
                        "WHERE id = %(id)s", {**novo, "id": s["id"]})
            self._nova_versao(con, t["id"])
            self._avisar_sub(con, {**novo, "id": s["id"]}, (s["responsavel"], s["prazo"], s["hora"]),
                             self._nome(con, usuario), usuario, t["id"])
        return {**self.obter(usuario, t["id"]), "avisos": avisos}

    def _situar(self, usuario: int, id_, situacao: str | None) -> dict:
        """Muda a situação da subtarefa (None: desfaz a conclusão): o responsável ou quem criou a tarefa."""
        with self.banco.conexao() as con:
            t, s = self._travar_sub(con, usuario, id_)
            if not t["eu_criador"] and s["responsavel"] != usuario:
                raise PermissionError("só o responsável pela subtarefa (ou quem criou a tarefa) muda a situação dela")
            self._aberta(t)
            if situacao is None and not s["concluida_em"]:
                raise ValueError("a subtarefa não estava concluída")
            con.execute(f"UPDATE agenda_subtarefas SET {_mudar_situacao(situacao)} WHERE id = %(id)s",
                        self._parametros(usuario, s["id"]))
            if situacao == "concluida" and not s["concluida_em"]:
                self._avisar_conclusao(con, t, s, usuario)
        return self.obter(usuario, t["id"])

    def mover_subtarefa(self, usuario: int, id_, situacao) -> dict:
        """A subtarefa a fazer, fazendo ou concluída (em qualquer dia)."""
        return self._situar(usuario, id_, _situacao(situacao))

    def justificar_subtarefa(self, usuario: int, id_, texto, concluir: bool = False) -> dict:
        """O responsável conta por que a subtarefa atrasou; só depois que ela venceu. Vale também com a tarefa
        concluída: é uma explicação, não uma mudança no trabalho. concluir: conclui a subtarefa na mesma gravação."""
        texto = self._texto_justificativa(texto)
        with self.banco.conexao() as con:
            t, s = self._travar_sub(con, usuario, id_)
            if s["responsavel"] != usuario:
                raise PermissionError("só o responsável pela subtarefa justifica o atraso dela")
            if not _venceu(s["prazo"], s["hora"], s["concluida_em"] or t["concluida_em"], self.agora()):
                raise ValueError(_NAO_ATRASOU.format("a subtarefa ainda"))
            self._justificar(con, t["id"], s["id"], usuario, s["prazo"], s["hora"], texto)
            avisar(con, [t["criador"]], "justificativa", f"{self._nome(con, usuario)} justificou o atraso de "
                   f"“{_curto(s['titulo'])}”: “{_curto(texto, 140)}”", usuario, t["id"], s["id"])
            if concluir and not s["concluida_em"]:
                self._aberta(t)
                con.execute(f"UPDATE agenda_subtarefas SET {_mudar_situacao('concluida')} WHERE id = %(id)s",
                            self._parametros(usuario, s["id"]))
                self._avisar_conclusao(con, t, s, usuario)
        return self.obter(usuario, t["id"])

    def concluir_subtarefa(self, usuario: int, id_) -> dict:
        """Marca a subtarefa como feita (em qualquer dia); concluir de novo não muda nada."""
        return self._situar(usuario, id_, "concluida")

    def desfazer_subtarefa(self, usuario: int, id_) -> dict:
        return self._situar(usuario, id_, None)

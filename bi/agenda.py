"""Página Agenda: as atividades de cada pessoa, únicas ou repetidas, e o que foi feito em cada dia.

- Cada pessoa vê só a própria agenda, como as conversas do Assistente (bi/conversas.py): todo método recebe o id do
  usuário e filtra por ele, e a atividade de outra pessoa é tratada como se não existisse.
- Repetição (ocorre): única (só no dia do início), diária (todo dia, ou só os dias úteis de uma região, com os
  feriados e os extras de Configurações, bi/calendario.py), semanal (dias da semana escolhidos), mensal (um dia fixo;
  o mês sem esse dia usa o último) ou a cada N dias desde o início. A repetida pode ter um último dia (fim).
- Concluir grava o registro do dia (agenda_registros, migração 018) com o feedback, obrigatório quando a atividade
  exige feedback. Só até hoje; concluir de novo troca o feedback. A repetida junta um registro por dia: o histórico.
- Editar a atividade não apaga o que já foi feito: o registro de um dia que deixou de ocorrer continua aparecendo.
"""
from __future__ import annotations

import calendar
import datetime as dt

from .banco import Banco, hora
from .calendario import REGIOES, UM_DIA, Calendario
from .conversas import NaoEncontrada

REPETICOES = ("nenhuma", "diaria", "semanal", "mensal", "intervalo")
MAX_TITULO = 120
MAX_TEXTO = 2000
MAX_FALTAS = 30  # dias sem conclusão que o histórico lista (os mais recentes)
_GRAVAR = ("titulo", "descricao", "inicio", "repeticao", "dias_semana", "dia_mes", "intervalo", "so_dias_uteis",
           "regiao", "fim", "exige_feedback")
_CAMPOS = ("id", *_GRAVAR)
_COLUNAS = ", ".join(_CAMPOS)
_VALORES = ", ".join(f"%({c})s::smallint[]" if c == "dias_semana" else f"%({c})s" for c in _GRAVAR)
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


def _inteiro(valor, campo: str, minimo: int, maximo: int) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"informe {campo}") from None
    if not minimo <= n <= maximo:
        raise ValueError(f"{campo} vai de {minimo} a {maximo}")
    return n


def _id(valor) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise NaoEncontrada(_NAO_ACHOU) from None
    if not 0 < n < 2 ** 63:
        raise NaoEncontrada(_NAO_ACHOU)
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


def _valida(dados: dict) -> dict:
    """A atividade como vai para o banco, com só os campos da repetição escolhida."""
    titulo = " ".join(str(dados.get("titulo") or "").split())
    if not titulo:
        raise ValueError("escreva o título da atividade")
    if len(titulo) > MAX_TITULO:
        raise ValueError(f"o título pode ter até {MAX_TITULO} caracteres")
    repeticao = dados.get("repeticao") or "nenhuma"
    if repeticao not in REPETICOES:
        raise ValueError(f"repetição desconhecida: {repeticao!r}")
    a = {"titulo": titulo, "descricao": _texto(dados.get("descricao"), "a descrição"),
         "inicio": _data(dados.get("inicio"), "da atividade"), "repeticao": repeticao, "dias_semana": None,
         "dia_mes": None, "intervalo": None, "so_dias_uteis": False, "regiao": None, "fim": None,
         "exige_feedback": bool(dados.get("exige_feedback"))}
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
    if repeticao != "nenhuma" and dados.get("fim"):
        a["fim"] = _data(dados["fim"], "do último dia")
        if a["fim"] < a["inicio"]:
            raise ValueError("o último dia não pode ser antes do início")
    return a


def ocorre(a: dict, dia: dt.date, cal: Calendario | None = None) -> bool:
    """A atividade acontece neste dia? cal: o calendário dos dias úteis (só a diária com so_dias_uteis usa)."""
    if dia < a["inicio"] or (a["fim"] and dia > a["fim"]):
        return False
    repeticao = a["repeticao"]
    if repeticao == "nenhuma":
        return dia == a["inicio"]
    if repeticao == "diaria":
        return not a["so_dias_uteis"] or cal.dia(dia, a["regiao"])["peso"] > 0
    if repeticao == "semanal":
        return dia.isoweekday() in a["dias_semana"]
    if repeticao == "mensal":
        return dia.day == min(a["dia_mes"], calendar.monthrange(dia.year, dia.month)[1])
    return (dia - a["inicio"]).days % a["intervalo"] == 0


def _publica(a: dict) -> dict:
    return {**a, "inicio": a["inicio"].isoformat(), "fim": a["fim"].isoformat() if a["fim"] else None}


class Agenda:
    def __init__(self, banco: Banco, configuracao, hoje=dt.date.today):
        """configuracao: as regras de Metas (bi/configuracao.py), de onde vêm os feriados extras e os sábados.
        hoje: função que dá o dia de hoje (os testes fixam um dia)."""
        self.banco = banco
        self.configuracao = configuracao
        self.hoje = hoje

    def _calendario(self, atividades: list[dict]) -> Calendario | None:
        if not any(a["so_dias_uteis"] for a in atividades):
            return None
        cal = self.configuracao.atual()["calendario"]
        return Calendario(cal["extras"], cal["sabado"])

    def _obter(self, usuario: int, id_: int) -> dict:
        with self.banco.conexao() as con:
            linha = con.execute(f"SELECT {_COLUNAS} FROM agenda_atividades WHERE id = %s AND usuario = %s",
                                [id_, usuario]).fetchone()
        if not linha:
            raise NaoEncontrada(_NAO_ACHOU)
        return dict(zip(_CAMPOS, linha))

    # --- leitura ---------------------------------------------------------------------------
    def mes(self, usuario: int, mes: str | None = None) -> dict:
        """Os dias do mês ('2026-10'; vazio = o mês de hoje) com as atividades de cada um e o que já foi concluído."""
        hoje = self.hoje()
        ano, n = _mes(mes, hoje)
        primeiro, ultimo = dt.date(ano, n, 1), dt.date(ano, n, calendar.monthrange(ano, n)[1])
        with self.banco.conexao() as con:
            atividades = [dict(zip(_CAMPOS, r)) for r in con.execute(
                f"SELECT {_COLUNAS} FROM agenda_atividades WHERE usuario = %(u)s AND ((inicio <= %(ate)s AND "
                "(fim IS NULL OR fim >= %(de)s)) OR id IN (SELECT atividade FROM agenda_registros "
                "WHERE dia BETWEEN %(de)s AND %(ate)s)) ORDER BY id", {"u": usuario, "de": primeiro, "ate": ultimo})]
            feitos = {(at, dia): (feedback, quando) for at, dia, feedback, quando in con.execute(
                "SELECT r.atividade, r.dia, r.feedback, r.concluida_em FROM agenda_registros r "
                "JOIN agenda_atividades a ON a.id = r.atividade "
                "WHERE a.usuario = %s AND r.dia BETWEEN %s AND %s", [usuario, primeiro, ultimo])}
        cal = self._calendario(atividades)
        dias, dia = [], primeiro
        while dia <= ultimo:
            itens = []
            for a in atividades:
                feito = feitos.get((a["id"], dia))
                if feito:
                    itens.append({"atividade": a["id"], "feita": True, "feedback": feito[0],
                                  "concluida_em": hora(feito[1])})
                elif ocorre(a, dia, cal):
                    itens.append({"atividade": a["id"], "feita": False, "feedback": None, "concluida_em": None})
            dias.append({"data": dia.isoformat(), "itens": itens})
            dia += UM_DIA
        return {"hoje": hoje.isoformat(), "mes": f"{ano:04d}-{n:02d}",
                "atividades": [_publica(a) for a in atividades], "dias": dias}

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
        return {"atividade": _publica(a), "hoje": hoje.isoformat(), "ocorrencias": len(previstos | feitos),
                "feitas": len(registros), "faltas": [d.isoformat() for d in faltas[:MAX_FALTAS]],
                "faltas_total": len(faltas),
                "registros": [{"dia": d.isoformat(), "feedback": fb, "concluida_em": hora(c), "editada_em": hora(e)}
                              for d, fb, c, e in registros]}

    # --- atividades ------------------------------------------------------------------------
    def criar(self, usuario: int, dados: dict) -> dict:
        a = _valida(dados)
        with self.banco.conexao() as con:
            linha = con.execute(f"INSERT INTO agenda_atividades (usuario, {', '.join(_GRAVAR)}) SELECT id, {_VALORES} "
                                "FROM usuarios WHERE id = %(usuario)s RETURNING id",
                                {**a, "usuario": usuario}).fetchone()
        if not linha:
            raise NaoEncontrada("seu usuário não existe mais")
        return {"id": linha[0], **_publica(a)}

    def editar(self, usuario: int, id_, dados: dict) -> dict:
        id_, a = _id(id_), _valida(dados)
        sets = ", ".join(f"{c} = {v}" for c, v in zip(_GRAVAR, _VALORES.split(", ")))
        with self.banco.conexao() as con:
            linha = con.execute(f"UPDATE agenda_atividades SET {sets}, atualizada_em = now() "
                                "WHERE id = %(id)s AND usuario = %(usuario)s RETURNING id",
                                {**a, "id": id_, "usuario": usuario}).fetchone()
        if not linha:
            raise NaoEncontrada(_NAO_ACHOU)
        return {"id": id_, **_publica(a)}

    def encerrar(self, usuario: int, id_) -> dict:
        """A repetida para de acontecer depois de hoje; o que já foi feito fica."""
        id_, hoje = _id(id_), self.hoje()
        with self.banco.conexao() as con:
            linha = con.execute("SELECT repeticao, inicio, fim FROM agenda_atividades WHERE id = %s AND usuario = %s "
                                "FOR UPDATE", [id_, usuario]).fetchone()
            if not linha:
                raise NaoEncontrada(_NAO_ACHOU)
            repeticao, inicio, fim = linha
            if repeticao == "nenhuma":
                raise ValueError("só a atividade que se repete pode ser encerrada")
            if inicio > hoje:
                raise ValueError("a atividade ainda não começou; exclua se ela não vai mais acontecer")
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
    def concluir(self, usuario: int, id_, dia, feedback) -> dict:
        """Marca o dia como feito, com o feedback; se já estava feito, troca o feedback."""
        id_, dia = _id(id_), _data(dia, "da conclusão")
        if dia > self.hoje():
            raise ValueError("só dá para concluir até hoje")
        feedback = _texto(feedback, "o feedback")
        a = self._obter(usuario, id_)
        if a["exige_feedback"] and not feedback:
            raise ValueError("esta atividade pede um feedback para ser concluída")
        with self.banco.conexao() as con:
            ja_feita = con.execute("SELECT 1 FROM agenda_registros WHERE atividade = %s AND dia = %s",
                                   [id_, dia]).fetchone()
        if not ja_feita and not ocorre(a, dia, self._calendario([a])):
            raise ValueError("a atividade não acontece neste dia")
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

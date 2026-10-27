"""Agenda (bi/agenda.py): em que dias cada repetição acontece, a conferência do formulário e, no PostgreSQL, as
atividades de cada pessoa, a conclusão com feedback, o histórico e as propostas do Assistente (ferramentas e botão).

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from bi.agenda import Agenda, _hora, _valida, ocorre, texto_repeticao
from bi.assistente import Ferramentas
from bi.calendario import Calendario
from bi.configuracao import padrao
from bi.conversas import Conversas, NaoEncontrada
from bi.tarefas import Tarefas
from tests.apoio import (BaseBanco, ClienteFalso, ConfiguracaoFixa, bloco_ferramenta, bloco_texto, criar_assistente,
                         criar_calc, resposta)

D = dt.date
HOJE = D(2026, 10, 26)  # segunda-feira


def atividade(**campos) -> dict:
    return _valida({"titulo": "Visitar a loja", "inicio": "2026-10-01", **campos})


def dias_de(a: dict, de: dt.date, ate: dt.date, cal: Calendario | None = None) -> list[dt.date]:
    return [de + dt.timedelta(n) for n in range((ate - de).days + 1) if ocorre(a, de + dt.timedelta(n), cal)]


class TestOcorre(unittest.TestCase):
    def test_unica(self):
        a = atividade(inicio="2026-10-15")
        self.assertEqual(dias_de(a, D(2026, 10, 1), D(2026, 11, 30)), [D(2026, 10, 15)])

    def test_unica_de_varios_dias(self):
        a = atividade(inicio="2026-11-10", fim="2026-11-14")  # a feira: todos os dias do início ao fim
        self.assertEqual(dias_de(a, D(2026, 11, 1), D(2026, 11, 30)),
                         [D(2026, 11, 10), D(2026, 11, 11), D(2026, 11, 12), D(2026, 11, 13), D(2026, 11, 14)])
        semanal = atividade(repeticao="semanal", dias_semana=[1], inicio="2026-10-26", fim="2026-10-30")
        self.assertEqual(dias_de(semanal, D(2026, 10, 1), D(2026, 11, 30)), [D(2026, 10, 26)])  # a repetida não muda

    def test_diaria_com_fim(self):
        a = atividade(repeticao="diaria", inicio="2026-10-28", fim="2026-11-02")
        self.assertEqual(dias_de(a, D(2026, 10, 1), D(2026, 11, 30)),
                         [D(2026, 10, 28), D(2026, 10, 29), D(2026, 10, 30), D(2026, 10, 31), D(2026, 11, 1),
                          D(2026, 11, 2)])

    def test_diaria_so_dias_uteis(self):
        # 31/10 sábado sem expediente, 01/11 domingo, 02/11 Finados e 03/11 feriado extra do ES (não vale na BA)
        cal = Calendario([{"data": "2026-11-03", "regiao": "ES", "peso": 0, "descricao": "Feriado local"}])
        es = atividade(repeticao="diaria", inicio="2026-10-29", so_dias_uteis=True, regiao="ES")
        ba = atividade(repeticao="diaria", inicio="2026-10-29", so_dias_uteis=True, regiao="BA")
        self.assertEqual(dias_de(es, D(2026, 10, 29), D(2026, 11, 4), cal), [D(2026, 10, 29), D(2026, 10, 30), D(2026, 11, 4)])
        self.assertEqual(dias_de(ba, D(2026, 10, 29), D(2026, 11, 4), cal),
                         [D(2026, 10, 29), D(2026, 10, 30), D(2026, 11, 3), D(2026, 11, 4)])

    def test_semanal(self):
        a = atividade(repeticao="semanal", dias_semana=[4, 1, 1])  # segunda e quinta (repetido some)
        self.assertEqual(a["dias_semana"], [1, 4])
        self.assertEqual(dias_de(a, D(2026, 10, 1), D(2026, 10, 15)),
                         [D(2026, 10, 1), D(2026, 10, 5), D(2026, 10, 8), D(2026, 10, 12), D(2026, 10, 15)])

    def test_mensal_cai_no_ultimo_dia(self):
        a = atividade(repeticao="mensal", dia_mes=31, inicio="2027-01-01")
        self.assertEqual(dias_de(a, D(2027, 1, 1), D(2027, 4, 30)),
                         [D(2027, 1, 31), D(2027, 2, 28), D(2027, 3, 31), D(2027, 4, 30)])
        dia5 = atividade(repeticao="mensal", dia_mes=5, inicio="2026-10-26")  # o primeiro é em novembro
        self.assertEqual(dias_de(dia5, D(2026, 10, 1), D(2026, 12, 31)), [D(2026, 11, 5), D(2026, 12, 5)])

    def test_a_cada_n_dias(self):
        a = atividade(repeticao="intervalo", intervalo=15, inicio="2026-10-01")
        self.assertEqual(dias_de(a, D(2026, 9, 1), D(2026, 11, 30)),
                         [D(2026, 10, 1), D(2026, 10, 16), D(2026, 10, 31), D(2026, 11, 15), D(2026, 11, 30)])


class TestValida(unittest.TestCase):
    def test_limpa_e_guarda_so_o_da_repeticao(self):
        a = _valida({"titulo": "  Ligar   para o Rubens ", "inicio": "2026-10-26", "repeticao": "semanal",
                     "dias_semana": [2], "dia_mes": 5, "intervalo": 7, "so_dias_uteis": True, "regiao": "ES",
                     "exige_feedback": True, "descricao": " pedido da semana "})
        self.assertEqual((a["titulo"], a["descricao"], a["dias_semana"], a["dia_mes"], a["intervalo"]),
                         ("Ligar para o Rubens", "pedido da semana", [2], None, None))
        self.assertEqual((a["so_dias_uteis"], a["regiao"], a["exige_feedback"]), (False, None, True))
        # a única com o último dia dura vários dias; com o mesmo dia, é de um dia só
        self.assertEqual(_valida({"titulo": "x", "inicio": "2026-10-26", "fim": "2026-12-01"})["fim"], D(2026, 12, 1))
        self.assertIsNone(_valida({"titulo": "x", "inicio": "2026-10-26", "fim": "2026-10-26"})["fim"])
        h = _valida({"titulo": "x", "inicio": "2026-10-26", "hora": "14h", "hora_fim": "15:30", "ocupado": True})
        self.assertEqual((h["hora"], h["hora_fim"], h["ocupado"]), (dt.time(14), dt.time(15, 30), True))

    def test_recusa(self):
        casos = {
            "título": {"titulo": "  ", "inicio": "2026-10-26"},
            "AAAA-MM-DD": {"titulo": "x", "inicio": "26/10/2026"},
            "repetição": {"titulo": "x", "inicio": "2026-10-26", "repeticao": "anual"},
            "um dia da semana": {"titulo": "x", "inicio": "2026-10-26", "repeticao": "semanal", "dias_semana": []},
            "1 (segunda)": {"titulo": "x", "inicio": "2026-10-26", "repeticao": "semanal", "dias_semana": [0]},
            "o dia do mês": {"titulo": "x", "inicio": "2026-10-26", "repeticao": "mensal", "dia_mes": 32},
            "o intervalo": {"titulo": "x", "inicio": "2026-10-26", "repeticao": "intervalo", "intervalo": 1},
            "ES ou BA": {"titulo": "x", "inicio": "2026-10-26", "repeticao": "diaria", "so_dias_uteis": True},
            "antes do início": {"titulo": "x", "inicio": "2026-10-26", "repeticao": "diaria", "fim": "2026-10-01"},
            "120 caracteres": {"titulo": "x" * 121, "inicio": "2026-10-26"},
            "a que horas a atividade começa": {"titulo": "x", "inicio": "2026-10-26", "hora_fim": "15:00"},
            "depois do começo": {"titulo": "x", "inicio": "2026-10-26", "hora": "15:00", "hora_fim": "15:00"},
            "como ocupado": {"titulo": "x", "inicio": "2026-10-26", "hora": "15:00", "ocupado": True},
        }
        for trecho, dados in casos.items():
            with self.subTest(trecho), self.assertRaises(ValueError) as e:
                _valida(dados)
            self.assertIn(trecho, str(e.exception))


class TestAgendaNoBanco(BaseBanco):
    """Hoje é segunda, 26/10/2026."""

    def setUp(self):
        super().setUp()
        cfg = padrao()
        cfg["calendario"]["extras"] = [{"data": "2026-10-27", "regiao": "ES", "peso": 0, "descricao": "Feriado local"}]
        self.agenda = Agenda(self.banco, ConfiguracaoFixa(cfg), hoje=lambda: HOJE)
        self.ana = self.criar_usuario("ana")
        self.beto = self.criar_usuario("beto")

    def criar(self, dono=None, **campos) -> int:
        return self.agenda.criar(dono or self.ana, {"titulo": "Visitar a loja", "inicio": "2026-10-01", **campos})["id"]

    def itens(self, mes: dict, dia: str) -> list[dict]:
        return next(d["itens"] for d in mes["dias"] if d["data"] == dia)

    def test_mes(self):
        unica = self.criar(titulo="Reunião", inicio="2026-10-26")
        semanal = self.criar(repeticao="semanal", dias_semana=[1])
        uteis = self.criar(repeticao="diaria", inicio="2026-10-26", so_dias_uteis=True, regiao="ES")
        self.criar(titulo="Outro mês", inicio="2026-11-03")
        self.criar(self.beto, titulo="Do Beto", inicio="2026-10-26")
        m = self.agenda.mes(self.ana, "2026-10")
        self.assertEqual((m["hoje"], m["mes"], len(m["dias"])), ("2026-10-26", "2026-10", 31))
        self.assertEqual([a["id"] for a in m["atividades"]], [unica, semanal, uteis])
        self.assertEqual([i["atividade"] for i in self.itens(m, "2026-10-26")], [unica, semanal, uteis])
        self.assertEqual(self.itens(m, "2026-10-27"), [])  # feriado extra do ES
        self.assertEqual([i["atividade"] for i in self.itens(m, "2026-10-28")], [uteis])
        self.assertEqual([i["atividade"] for i in self.itens(m, "2026-10-05")], [semanal])
        self.assertEqual(self.agenda.mes(self.ana)["mes"], "2026-10")  # sem mês: o de hoje
        with self.assertRaises(ValueError):
            self.agenda.mes(self.ana, "outubro")

    def test_concluir_com_feedback(self):
        livre = self.criar(repeticao="semanal", dias_semana=[1])
        pede = self.criar(titulo="Relatório", repeticao="diaria", exige_feedback=True)
        r = self.agenda.concluir(self.ana, livre, "2026-10-19", "")
        self.assertEqual((r["feita"], r["feedback"], r["editada_em"]), (True, "", None))
        with self.assertRaises(ValueError) as e:
            self.agenda.concluir(self.ana, pede, "2026-10-26", "   ")
        self.assertIn("pede um feedback", str(e.exception))
        with self.assertRaises(ValueError) as e:
            self.agenda.concluir(self.ana, pede, "2026-10-27", "amanhã")
        self.assertIn("até hoje", str(e.exception))
        with self.assertRaises(ValueError) as e:
            self.agenda.concluir(self.ana, livre, "2026-10-20", "terça")  # só às segundas
        self.assertIn("não acontece", str(e.exception))
        self.agenda.concluir(self.ana, pede, "2026-10-26", "Feito com o Rubens")
        r = self.agenda.concluir(self.ana, pede, "2026-10-26", "Feito com o Rubens e a Thais")  # troca o feedback
        self.assertIsNotNone(r["editada_em"])
        self.assertEqual(self.contar("agenda_registros"), 2)
        item = self.itens(self.agenda.mes(self.ana, "2026-10"), "2026-10-26")[1]
        self.assertEqual((item["atividade"], item["feita"], item["feedback"]), (pede, True, "Feito com o Rubens e a Thais"))
        self.agenda.desfazer(self.ana, pede, "2026-10-26")
        self.assertFalse(self.itens(self.agenda.mes(self.ana, "2026-10"), "2026-10-26")[1]["feita"])
        with self.assertRaises(NaoEncontrada):
            self.agenda.desfazer(self.ana, pede, "2026-10-26")

    def test_historico(self):
        a = self.criar(repeticao="semanal", dias_semana=[1], inicio="2026-09-28")  # 28/09 e 5, 12, 19 e 26/10
        for dia, fb in (("2026-10-05", "primeira"), ("2026-10-19", "terceira"), ("2026-10-26", "hoje")):
            self.agenda.concluir(self.ana, a, dia, fb)
        h = self.agenda.historico(self.ana, a)
        self.assertEqual((h["ocorrencias"], h["feitas"], h["faltas_total"]), (5, 3, 2))
        self.assertEqual(h["faltas"], ["2026-10-12", "2026-09-28"])
        self.assertEqual([r["feedback"] for r in h["registros"]], ["hoje", "terceira", "primeira"])
        hoje = self.agenda.historico(self.ana, self.criar(repeticao="diaria", inicio="2026-10-26"))
        self.assertEqual((hoje["ocorrencias"], hoje["faltas_total"]), (1, 0))  # hoje ainda dá tempo
        # editar a repetição não apaga o que já foi feito: o registro de segunda continua no mês e no histórico
        self.agenda.editar(self.ana, a, {"titulo": "Visitar a loja", "inicio": "2026-09-28", "repeticao": "semanal",
                                         "dias_semana": [3]})
        self.assertTrue(self.itens(self.agenda.mes(self.ana, "2026-10"), "2026-10-19")[0]["feita"])
        self.assertEqual(self.agenda.historico(self.ana, a)["feitas"], 3)

    def test_encerrar_e_excluir(self):
        a = self.criar(repeticao="diaria")
        self.agenda.concluir(self.ana, a, "2026-10-25", "domingo")
        self.assertEqual(self.agenda.encerrar(self.ana, a)["fim"], "2026-10-26")
        m = self.agenda.mes(self.ana, "2026-10")
        self.assertEqual(len(self.itens(m, "2026-10-26")), 1)
        self.assertEqual(self.itens(m, "2026-10-27"), [])
        with self.assertRaises(ValueError):
            self.agenda.encerrar(self.ana, self.criar(inicio="2026-10-26"))  # única de um dia
        with self.assertRaises(ValueError):
            self.agenda.encerrar(self.ana, self.criar(repeticao="diaria", inicio="2026-11-01"))  # não começou
        feira = self.criar(titulo="Feira", inicio="2026-10-24", fim="2026-10-30")  # a de vários dias também encerra
        self.assertEqual(self.agenda.encerrar(self.ana, feira)["fim"], "2026-10-26")
        self.assertEqual(self.agenda.historico(self.ana, feira)["atividade"]["quando"], "De 24/10 a 26/10")
        self.agenda.excluir(self.ana, a)
        self.assertEqual(self.contar("agenda_registros"), 0)

    def test_cada_um_ve_so_a_sua(self):
        a = self.criar(repeticao="diaria")
        for chamada in (lambda: self.agenda.historico(self.beto, a),
                        lambda: self.agenda.concluir(self.beto, a, "2026-10-26", "intruso"),
                        lambda: self.agenda.editar(self.beto, a, {"titulo": "x", "inicio": "2026-10-26"}),
                        lambda: self.agenda.encerrar(self.beto, a),
                        lambda: self.agenda.excluir(self.beto, a),
                        lambda: self.agenda.historico(self.ana, "abc")):
            with self.assertRaises(NaoEncontrada):
                chamada()
        self.assertEqual(self.agenda.mes(self.beto, "2026-10")["atividades"], [])
        self.assertEqual(self.contar("agenda_atividades"), 1)

    def test_usuario_excluido_leva_a_agenda(self):
        a = self.criar(repeticao="diaria")
        self.agenda.concluir(self.ana, a, "2026-10-26", "")
        with self.banco.conexao() as con:
            con.execute("DELETE FROM usuarios WHERE id = %s", [self.ana])
        self.assertEqual((self.contar("agenda_atividades"), self.contar("agenda_registros")), (0, 0))
        with self.assertRaises(NaoEncontrada):
            self.criar()

    def test_o_banco_confere_a_repeticao(self):
        from psycopg.errors import CheckViolation
        with self.assertRaises(CheckViolation), self.banco.conexao() as con:
            con.execute("INSERT INTO agenda_atividades (usuario, titulo, inicio, repeticao) "
                        "VALUES (%s, 'x', '2026-10-26', 'semanal')", [self.ana])  # semanal sem os dias


class TestHorarioOcupado(BaseBanco):
    """Horário ocupado (migração 026). Hoje é segunda, 26/10/2026; a Ana tem "Reunião com fornecedor" em 30/10,
    14:00–15:00, ocupado. Beto cria as tarefas."""

    def setUp(self):
        super().setUp()
        cfg = padrao()
        self.agenda = Agenda(self.banco, ConfiguracaoFixa(cfg), hoje=lambda: HOJE)
        self.tarefas = Tarefas(self.banco, ConfiguracaoFixa(cfg), hoje=lambda: HOJE)
        self.ana, self.beto = (self.criar_usuario(n, paginas=["metas", "gestao"]) for n in ("ana", "beto"))
        self.reuniao = self.atividade(self.ana, titulo="Reunião com fornecedor", hora="14:00", hora_fim="15:00",
                                      ocupado=True)

    def atividade(self, dono, **campos) -> int:
        return self.agenda.criar(dono, {"titulo": "Ligar para o João", "inicio": "2026-10-30", **campos})["id"]

    def tarefa(self, **campos) -> dict:
        return self.tarefas.criar(self.beto, {"titulo": "Feira", "prazo": "2026-10-31",
                                              "participantes": [{"id": self.ana}], **campos})

    def recusa(self, trecho: str, chamada) -> str:
        with self.assertRaises(ValueError) as e:
            chamada()
        self.assertIn(trecho, str(e.exception))
        return str(e.exception)

    def test_a_tabela_do_plano(self):
        self.recusa("esse horário está ocupado por “Reunião com fornecedor” (30/10, 14:00–15:00)",
                    lambda: self.atividade(self.ana, hora="14:30"))
        self.atividade(self.ana, hora="15:00", hora_fim="16:00")  # começa quando a outra termina
        self.atividade(self.ana)  # sem horário
        msg = self.recusa("Ana está com o horário ocupado em 30/10, das 14:00 às 15:00: mude o horário da tarefa "
                          "“Feira”", lambda: self.tarefa(prazo="2026-10-30", hora="14:30"))
        self.assertNotIn("Reunião", msg)  # a agenda da Ana é só dela
        self.recusa("mude o horário da subtarefa “Estande”", lambda: self.tarefa(subtarefas=[
            {"titulo": "Estande", "responsavel": self.ana, "prazo": "2026-10-30", "hora": "14:00"}]))
        self.tarefa(subtarefas=[{"titulo": "Estande", "responsavel": self.ana, "prazo": "2026-10-30", "hora": "15:00"}])
        self.atividade(self.beto, hora="14:00", hora_fim="15:00", ocupado=True)  # é outra pessoa
        # marcar como ocupado com algo já no horário: recusa; concluída, a subtarefa não conta mais
        t = self.tarefa(prazo="2026-11-06", subtarefas=[{"titulo": "Enviar relatório", "responsavel": self.ana,
                                                         "prazo": "2026-11-02", "hora": "08:30"}])
        equipe = {"titulo": "Reunião de equipe", "inicio": "2026-10-26", "repeticao": "semanal", "dias_semana": [1],
                  "hora": "08:00", "hora_fim": "09:00", "ocupado": True}
        self.recusa("já há algo nesse horário em 02/11: a subtarefa “Enviar relatório” (até 08:30). Peça a Beto, "
                    "que criou a tarefa, para mudar o prazo, ou escolha outro horário",
                    lambda: self.agenda.criar(self.ana, equipe))
        self.tarefas.concluir_subtarefa(self.ana, t["subtarefas"][0]["id"])
        self.agenda.criar(self.ana, equipe)

    def test_repetidas_e_dias_uteis(self):
        self.atividade(self.ana, titulo="Reunião de equipe", inicio="2026-10-26", repeticao="semanal",
                       dias_semana=[1], hora="08:00", hora_fim="09:00", ocupado=True)
        # a diária das 08:30 cruza na primeira segunda depois de começar
        self.recusa("ocupado por “Reunião de equipe” (02/11, 08:00–09:00)",
                    lambda: self.atividade(self.ana, inicio="2026-10-27", repeticao="diaria", hora="08:30"))
        self.atividade(self.ana, inicio="2026-10-27", fim="2026-10-31", repeticao="diaria", hora="08:30")  # sem segunda
        # ocupado só nos dias úteis do ES: Finados (02/11) fica livre
        self.atividade(self.ana, titulo="Rota", inicio="2026-10-27", repeticao="diaria", so_dias_uteis=True,
                       regiao="ES", hora="10:00", hora_fim="11:00", ocupado=True)
        self.tarefa(prazo="2026-11-02", hora="10:30")
        self.recusa("Ana está com o horário ocupado em 03/11, das 10:00 às 11:00",
                    lambda: self.tarefa(prazo="2026-11-03", hora="10:30"))
        # o que já passou não conta
        self.atividade(self.ana, titulo="Antiga", inicio="2026-10-20", hora="14:00", hora_fim="15:00", ocupado=True)
        self.tarefa(prazo="2026-10-20", hora="14:30")

    def test_editar_so_confere_o_que_mudou(self):
        # um conflito antigo: a tarefa entrou antes de a reunião ficar ocupada
        with self.banco.conexao() as con:
            con.execute("UPDATE agenda_atividades SET ocupado = false WHERE id = %s", [self.reuniao])
        t = self.tarefa(prazo="2026-10-30", hora="14:30")
        with self.banco.conexao() as con:
            con.execute("UPDATE agenda_atividades SET ocupado = true WHERE id = %s", [self.reuniao])
        dados = {"titulo": "Feira de novembro", "prazo": t["prazo"], "hora": t["hora"],
                 "participantes": [{"id": self.ana}], "subtarefas": []}
        t = self.tarefas.editar(self.beto, t["id"], dados, t["versao"])  # só o título: passa
        self.recusa("mude o horário da tarefa “Feira de novembro”",
                    lambda: self.tarefas.editar(self.beto, t["id"], {**dados, "hora": "14:45"}, t["versao"]))
        t = self.tarefas.nova_subtarefa(self.beto, t["id"], {"titulo": "Estande", "responsavel": self.ana,
                                                             "prazo": "2026-10-30", "hora": "13:00"})
        sub = t["subtarefas"][0]["id"]
        self.recusa("ocupado em 30/10", lambda: self.tarefas.editar_subtarefa(self.beto, sub, {"hora": "14:10"}))
        self.tarefas.editar_subtarefa(self.beto, sub, {"titulo": "Montar o estande"})
        # a atividade: o título passa; aumentar o horário esbarra na tarefa das 14:30
        reuniao = {"titulo": "Reunião com o fornecedor", "inicio": "2026-10-30", "hora": "14:00", "hora_fim": "15:00",
                   "ocupado": True}
        self.agenda.editar(self.ana, self.reuniao, reuniao)
        self.recusa("já há algo nesse horário em 30/10: a tarefa “Feira de novembro” (até 14:30). Peça a Beto",
                    lambda: self.agenda.editar(self.ana, self.reuniao, {**reuniao, "hora": "14:20"}))

    def test_propostas_do_assistente(self):
        self.recusa("ocupado por “Reunião com fornecedor”", lambda: self.agenda.propor(
            self.ana, "criar", dados={"titulo": "Ligar", "inicio": "2026-10-30", "hora": "14:30"}))
        p = self.agenda.propor(self.ana, "editar", atividade=self.reuniao, dados={"titulo": "Reunião com o fornecedor"})
        for chave in ("hora_fim", "ocupado"):  # como uma proposta guardada antes da migração 026
            del p["dados"][chave]
        self.agenda.aplicar(self.ana, p)
        a = self.agenda.mes(self.ana, "2026-10")["atividades"][0]
        self.assertEqual((a["titulo"], a["hora"], a["hora_fim"], a["ocupado"]),
                         ("Reunião com o fornecedor", "14:00", "15:00", True))


class TestHorarioETexto(unittest.TestCase):
    def test_horario(self):
        self.assertEqual([_hora(h) for h in ("09:00", "9:30", "14h", "14h15", "07:05:00", "", None)],
                         [dt.time(9), dt.time(9, 30), dt.time(14), dt.time(14, 15), dt.time(7, 5), None, None])
        for ruim in ("25:00", "9:60", "nove", "1430"):
            with self.subTest(ruim), self.assertRaises(ValueError):
                _hora(ruim)
        self.assertEqual(atividade(hora="8:00")["hora"], dt.time(8))

    def test_texto_da_repeticao(self):
        casos = [
            ({}, "Só neste dia"),
            ({"repeticao": "diaria"}, "Todo dia"),
            ({"repeticao": "diaria", "so_dias_uteis": True, "regiao": "BA"}, "Todo dia útil (BA)"),
            ({"repeticao": "semanal", "dias_semana": [4, 1]}, "Toda segunda e quinta"),
            ({"repeticao": "semanal", "dias_semana": [6, 7]}, "Todo sábado e domingo"),
            ({"repeticao": "semanal", "dias_semana": [1, 3, 6]}, "Semanal: segunda, quarta e sábado"),
            ({"repeticao": "mensal", "dia_mes": 31}, "Todo dia 31 (ou o último do mês)"),
            ({"repeticao": "intervalo", "intervalo": 15, "fim": "2026-11-30"}, "A cada 15 dias, até 30/11"),
            ({"repeticao": "diaria", "fim": "2027-01-05"}, "Todo dia, até 05/01/2027"),
            ({"inicio": "2026-11-10", "fim": "2026-11-14"}, "De 10/11 a 14/11"),
            ({"inicio": "2026-12-30", "fim": "2027-01-02"}, "De 30/12 a 02/01/2027"),
        ]
        for campos, esperado in casos:
            with self.subTest(esperado):
                self.assertEqual(texto_repeticao(atividade(**campos), HOJE), esperado)


class TestPropostasNoBanco(BaseBanco):
    """Horário, o período que o Assistente lê, as propostas e o botão que as aplica. Hoje é segunda, 26/10/2026."""

    def setUp(self):
        super().setUp()
        self.agenda = Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE)
        self.ana = self.criar_usuario("ana")
        self.beto = self.criar_usuario("beto")

    def criar(self, dono=None, **campos) -> int:
        return self.agenda.criar(dono or self.ana, {"titulo": "Visitar a loja", "inicio": "2026-10-01", **campos})["id"]

    def test_no_dia_as_com_horario_vem_primeiro(self):
        sem = self.criar(titulo="Sem horário", inicio="2026-10-26")
        tarde = self.criar(titulo="Tarde", inicio="2026-10-26", hora="15:30")
        manha = self.criar(titulo="Manhã", inicio="2026-10-26", hora="08:00")
        m = self.agenda.mes(self.ana, "2026-10")
        dia = next(d for d in m["dias"] if d["data"] == "2026-10-26")
        self.assertEqual([i["atividade"] for i in dia["itens"]], [manha, tarde, sem])
        horas = {a["id"]: (a["hora"], a["quando"]) for a in m["atividades"]}
        self.assertEqual(horas[tarde], ("15:30", "Só neste dia"))
        self.assertEqual(horas[sem], (None, "Só neste dia"))

    def test_periodo(self):
        visita = self.criar(titulo="Visita ao Mercado", repeticao="semanal", dias_semana=[1, 4], hora="09:00")
        self.criar(titulo="Relatório", inicio="2026-10-30")
        self.criar(self.beto, titulo="Do Beto", inicio="2026-10-26")
        self.agenda.concluir(self.ana, visita, "2026-10-19", "pedido de 40 kg")
        r = self.agenda.periodo(self.ana, "2026-10-19", "2026-10-30")
        # visita: 19 (feita), 22 (atrasada), 26 (hoje), 29 (prevista); relatório: 30 (prevista)
        self.assertEqual(r["totais"], {"ocorrencias": 5, "feitas": 1, "atrasadas": 1, "hoje": 1, "previstas": 2})
        self.assertEqual([(d["data"], d["dia_semana"]) for d in r["dias"]][:2], [("2026-10-19", "segunda"),
                                                                                 ("2026-10-22", "quinta")])
        primeiro = r["dias"][0]["itens"][0]
        self.assertEqual((primeiro["hora"], primeiro["situacao"], primeiro["feedback"]),
                         ("09:00", "feita", "pedido de 40 kg"))
        self.assertEqual({a["titulo"] for a in r["atividades"]}, {"Visita ao Mercado", "Relatório"})
        so_visita = self.agenda.periodo(self.ana, "2026-10-19", "2026-10-30", "mercado")
        self.assertEqual(so_visita["totais"]["ocorrencias"], 4)
        with self.assertRaises(ValueError):
            self.agenda.periodo(self.ana, "2026-01-01", "2026-12-31")  # mais de 93 dias
        with self.assertRaises(ValueError):
            self.agenda.periodo(self.ana, "2026-10-30", "2026-10-01")

    def test_propor_nao_grava(self):
        p = self.agenda.propor(self.ana, "criar", dados={"titulo": "Ligar para o gerente", "inicio": "2026-10-28",
                                                         "hora": "14h", "repeticao": "semanal", "dias_semana": [3]})
        self.assertEqual((p["acao"], p["titulo"], p["dados"]["hora"], p["dados"]["quando"], p["dia"]),
                         ("criar", "Ligar para o gerente", "14:00", "Toda quarta", "2026-10-28"))
        self.assertEqual(self.contar("agenda_atividades"), 0)
        a = self.criar(repeticao="semanal", dias_semana=[1], exige_feedback=True)
        e = self.agenda.propor(self.ana, "editar", atividade=a, dados={"hora": "09:00", "dias_semana": [1, 4]})
        self.assertEqual([m["campo"] for m in e["mudancas"]], ["Horário", "Repetição"])
        self.assertEqual((e["mudancas"][0]["de"], e["mudancas"][0]["para"]), (None, "09:00"))
        self.assertEqual(e["mudancas"][1]["para"], "Toda segunda e quinta")
        with self.assertRaises(ValueError):
            self.agenda.propor(self.ana, "editar", atividade=a, dados={"titulo": "Visitar a loja"})  # nada muda
        with self.assertRaises(ValueError):
            self.agenda.propor(self.ana, "concluir", atividade=a, dia="2026-10-26", feedback="")  # exige feedback
        with self.assertRaises(ValueError):
            self.agenda.propor(self.ana, "concluir", atividade=a, dia="2026-11-02", feedback="x")  # ainda não chegou
        c = self.agenda.propor(self.ana, "concluir", atividade=a, feedback="feito")  # sem dia: hoje
        self.assertEqual(c["dia"], "2026-10-26")
        with self.assertRaises(ValueError):
            self.agenda.propor(self.ana, "encerrar", atividade=self.criar(inicio="2026-10-26"))  # única
        self.assertEqual(self.agenda.propor(self.ana, "encerrar", atividade=a)["fim"], "2026-10-26")
        self.agenda.concluir(self.ana, a, "2026-10-19", "ok")
        self.assertEqual(self.agenda.propor(self.ana, "excluir", atividade=a)["registros"], 1)
        with self.assertRaises(NaoEncontrada):
            self.agenda.propor(self.beto, "excluir", atividade=a)  # a atividade é da Ana
        with self.assertRaises(ValueError):
            self.agenda.propor(self.ana, "apagar_tudo", atividade=a)
        self.assertEqual(self.contar("agenda_registros"), 1)  # só o concluir feito direto

    def test_aplicar_uma_vez_so(self):
        p = self.agenda.propor(self.ana, "criar", dados={"titulo": "Reunião", "inicio": "2026-10-27", "hora": "10:00"})
        r = self.agenda.aplicar(self.ana, p)
        self.assertFalse(r["ja_aplicada"])
        de_novo = self.agenda.aplicar(self.ana, p)
        self.assertEqual((de_novo["ja_aplicada"], de_novo["atividade"]), (True, r["atividade"]))
        self.assertEqual(self.contar("agenda_atividades"), 1)
        self.assertEqual(set(self.agenda.aplicadas(self.ana, [p["id"], "nao-e-uuid"])), {p["id"]})
        self.assertEqual(self.agenda.aplicadas(self.beto, [p["id"]]), {})
        with self.assertRaises(NaoEncontrada):
            self.agenda.aplicar(self.beto, p)  # a proposta é da Ana
        a = r["atividade"]
        self.agenda.aplicar(self.ana, self.agenda.propor(self.ana, "editar", atividade=a, dados={"hora": "11:00"}))
        self.assertEqual(self.agenda.mes(self.ana, "2026-10")["atividades"][0]["hora"], "11:00")
        diaria = self.criar(titulo="Pedidos", repeticao="diaria")
        self.agenda.aplicar(self.ana, self.agenda.propor(self.ana, "concluir", atividade=diaria, dia="2026-10-25",
                                                         feedback="domingo"))
        self.agenda.aplicar(self.ana, self.agenda.propor(self.ana, "encerrar", atividade=diaria))
        self.assertEqual(self.agenda.historico(self.ana, diaria)["atividade"]["fim"], "2026-10-26")
        self.assertEqual(self.agenda.historico(self.ana, diaria)["registros"][0]["feedback"], "domingo")
        # a atividade some antes do clique: não aplica e o botão pode tentar de novo (sem reserva presa)
        excluir = self.agenda.propor(self.ana, "excluir", atividade=diaria)
        self.agenda.excluir(self.ana, diaria)
        with self.assertRaises(NaoEncontrada):
            self.agenda.aplicar(self.ana, excluir)
        self.assertEqual(self.agenda.aplicadas(self.ana, [excluir["id"]]), {})


class TestAgendaNoAssistente(BaseBanco):
    """As ferramentas da agenda no Assistente (cliente falso da API): lê, propõe sem gravar, a conversa guarda a
    proposta e o botão (Agenda.aplicar, pela proposta achada na conversa) grava uma vez só."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.calc = criar_calc(self.pasta, fora=(999,))
        self.agenda = Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE)
        self.conversas = Conversas(self.banco)
        self.id_ana = self.criar_usuario("ana")
        self.ana = {"id": self.id_ana, "login": "ana", "nome": "Ana", "papel": "visualizador"}

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()
        super().tearDown()

    def ferramentas(self, agenda=True) -> Ferramentas:
        a = criar_assistente(self.pasta, self.calc)
        return Ferramentas(a.recorte(None), self.calc, a.cfg, None,
                           agenda=self.agenda.contexto(self.id_ana) if agenda else None)

    def test_ferramentas(self):
        visita = self.agenda.criar(self.id_ana, {"titulo": "Visita ao Mercado", "inicio": "2026-10-01",
                                                 "repeticao": "semanal", "dias_semana": [1]})["id"]
        self.agenda.concluir(self.id_ana, visita, "2026-10-19", "pedido de 40 kg")
        f = self.ferramentas()
        r, passo = f.executar("ver_agenda", {"de": "2026-10-19", "ate": "2026-10-26"})
        self.assertIsNone(passo["erro"])
        self.assertEqual(r["totais"]["feitas"], 1)
        self.assertIn(f"#{visita} Visita ao Mercado", passo["resumo"])
        r, passo = f.executar("historico_atividade", {"atividade": visita})
        self.assertEqual(r["registros"][0]["feedback"], "pedido de 40 kg")
        r, passo = f.executar("propor_agenda", {"acao": "concluir", "atividade": visita, "feedback": "pedido de 50 kg"})
        self.assertIn("AINDA NÃO APLICADA", r["situacao"])
        self.assertEqual((r["proposta"]["dia"], r["proposta"]["feedback"]), ("2026-10-26", "pedido de 50 kg"))
        self.assertEqual(len(f.agenda_propostas), 1)
        self.assertEqual(self.contar("agenda_registros"), 1)  # nada gravado
        r, passo = f.executar("propor_agenda", {"acao": "criar", "titulo": "", "inicio": "2026-10-27"})
        self.assertIn("título", passo["erro"])  # o erro volta para a IA corrigir
        r, passo = f.executar("propor_agenda", {"acao": "criar", "titulo": "Reunião", "inicio": "2026-10-27",
                                                "hora": "9h", "hora_fim": "10:00", "ocupado": True})
        self.assertIsNone(passo["erro"])
        self.assertEqual({k: r["proposta"]["dados"][k] for k in ("hora", "hora_fim", "ocupado", "quando")},
                         {"hora": "09:00", "hora_fim": "10:00", "ocupado": True, "quando": "Só neste dia"})
        r, passo = f.executar("propor_agenda", {"acao": "criar", "titulo": "Ligar", "inicio": "2026-10-27",
                                                "hora": "09:30"})
        self.assertIsNone(passo["erro"])  # a reunião ainda é só proposta: não ocupa nada
        r, passo = self.ferramentas(agenda=False).executar("ver_agenda", {"de": "2026-10-19", "ate": "2026-10-26"})
        self.assertIn("Gestão", passo["erro"])

    def test_da_conversa_ao_botao(self):
        api = ClienteFalso([
            resposta(bloco_ferramenta("t1", "propor_agenda", {
                "acao": "criar", "titulo": "Visitar o Mercado do João", "inicio": "2026-10-26", "hora": "9:00",
                "repeticao": "semanal", "dias_semana": [1, 4], "exige_feedback": True}), parada="tool_use"),
            resposta(bloco_texto("A proposta está pronta: confirme no botão abaixo.")),
        ])
        a = criar_assistente(self.pasta, self.calc, cliente=api, conversas=self.conversas)
        r = a.perguntar(self.ana, None, "põe na minha agenda visitar o Mercado do João toda segunda e quinta às 9h",
                        None, None, agenda=self.agenda.contexto(self.id_ana))
        p = r["agenda"][0]
        self.assertEqual((p["acao"], p["dados"]["hora"], p["dados"]["quando"], p["dados"]["exige_feedback"]),
                         ("criar", "09:00", "Toda segunda e quinta", True))
        resultado = json.loads(api.pedidos[1]["messages"][-1]["content"][0]["content"])
        self.assertIn("AINDA NÃO APLICADA", resultado["situacao"])
        self.assertIn("Agenda (topo da página Gestão): tem a própria agenda", api.pedidos[0]["system"][1]["text"])
        self.assertEqual(self.contar("agenda_atividades"), 0)
        # o botão: a proposta é achada na conversa da pessoa e aplicada uma vez só
        guardada = self.conversas.proposta_agenda(self.id_ana, p["id"])
        self.assertEqual(guardada["dados"]["titulo"], "Visitar o Mercado do João")
        self.assertIsNone(self.conversas.proposta_agenda(self.criar_usuario("beto"), p["id"]))
        self.assertFalse(self.agenda.aplicar(self.id_ana, guardada)["ja_aplicada"])
        self.assertTrue(self.agenda.aplicar(self.id_ana, guardada)["ja_aplicada"])
        self.assertEqual(self.contar("agenda_atividades"), 1)

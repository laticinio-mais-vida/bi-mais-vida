"""Página Agenda (bi/agenda.py): em que dias cada repetição acontece, a conferência do formulário e, no PostgreSQL, as
atividades de cada pessoa, a conclusão com feedback e o histórico.

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import unittest

from bi.agenda import Agenda, _valida, ocorre
from bi.calendario import Calendario
from bi.configuracao import padrao
from bi.conversas import NaoEncontrada
from tests.apoio import BaseBanco, ConfiguracaoFixa

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
        self.assertIsNone(_valida({"titulo": "x", "inicio": "2026-10-26", "fim": "2026-12-01"})["fim"])  # única

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
            self.agenda.encerrar(self.ana, self.criar(inicio="2026-10-26"))  # única
        with self.assertRaises(ValueError):
            self.agenda.encerrar(self.ana, self.criar(repeticao="diaria", inicio="2026-11-01"))  # não começou
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

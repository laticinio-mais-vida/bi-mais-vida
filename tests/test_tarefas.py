"""Tarefas da agenda (bi/tarefas.py): a conferência do formulário e, no PostgreSQL, quem vê o quê, quem pode o quê, a
conclusão, as colunas do quadro (kanban), as atrasadas, a edição (com a versão) e o que acontece quando um usuário é
excluído.

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import unittest

from bi.agenda import Agenda
from bi.conversas import NaoEncontrada
from bi.tarefas import (MAX_SUBTAREFAS, MAX_TITULO_SUB, TITULO_PLANEJAR, Tarefas, _ate_o_prazo, _dias_planejar,
                         _valida_tarefa)
from tests.apoio import BaseBanco, ConfiguracaoFixa

D = dt.date
T = dt.time
HOJE = D(2026, 10, 26)  # segunda-feira
GESTAO = ["metas", "gestao"]


class TestValidaTarefa(unittest.TestCase):
    def test_limpa_e_herda_o_prazo(self):
        t = _valida_tarefa({"titulo": "  Feira   de outubro ", "prazo": "2026-10-30", "hora": "14h",
                            "participantes": [{"id": 5, "autonomia": True}, 6, {"id": 1}, {"id": 5}],
                            "subtarefas": [{"titulo": "Montar o estande", "responsavel": 5, "prazo": "2026-10-28"},
                                           {"titulo": "Levar o material"}]}, criador=1)
        self.assertEqual((t["titulo"], t["prazo"], t["hora"]), ("Feira de outubro", D(2026, 10, 30), T(14)))
        self.assertEqual(t["participantes"], {5: False, 6: False})  # quem criou sai; o último 5 vale
        a, b = t["subtarefas"]
        self.assertEqual((a["responsavel"], a["prazo"], a["hora"], a["id"]), (5, D(2026, 10, 28), None, None))
        self.assertEqual((b["responsavel"], b["prazo"], b["hora"]), (1, D(2026, 10, 30), T(14)))  # a da tarefa

    def test_ate_o_prazo(self):
        self.assertTrue(_ate_o_prazo(D(2026, 10, 29), T(18), D(2026, 10, 30), T(9)))
        self.assertFalse(_ate_o_prazo(D(2026, 10, 31), None, D(2026, 10, 30), None))
        self.assertTrue(_ate_o_prazo(D(2026, 10, 30), None, D(2026, 10, 30), T(9)))  # sem horário: o dia
        self.assertTrue(_ate_o_prazo(D(2026, 10, 30), T(18), D(2026, 10, 30), None))
        self.assertFalse(_ate_o_prazo(D(2026, 10, 30), T(10), D(2026, 10, 30), T(9)))

    def test_recusa(self):
        base = {"titulo": "Feira", "prazo": "2026-10-30", "hora": "09:00"}
        casos = {
            "título da tarefa": {**base, "titulo": "  "},
            "prazo da tarefa": {**base, "prazo": ""},
            "120 caracteres": {**base, "titulo": "x" * 121},
            "vence depois da tarefa (30/10 às 09:00)": {**base, "subtarefas": [{"titulo": "A", "prazo": "2026-10-31"}]},
            "vence depois": {**base, "subtarefas": [{"titulo": "A", "prazo": "2026-10-30", "hora": "10:00"}]},
            "não participa": {**base, "subtarefas": [{"titulo": "A", "responsavel": 9}]},
            "título da subtarefa": {**base, "subtarefas": [{"titulo": ""}]},
            f"{MAX_TITULO_SUB} caracteres": {**base, "subtarefas": [{"titulo": "x" * (MAX_TITULO_SUB + 1)}]},
            "pessoa inválida": {**base, "participantes": ["ana"]},
            f"até {MAX_SUBTAREFAS} subtarefas": {**base, "subtarefas": [{"titulo": "A"}] * (MAX_SUBTAREFAS + 1)},
        }
        for trecho, dados in casos.items():
            with self.subTest(trecho), self.assertRaises(ValueError) as e:
                _valida_tarefa(dados, criador=1)
            self.assertIn(trecho, str(e.exception))

    def test_dias_planejar(self):
        """A automática: no dia em que a pessoa entrou e no seguinte de segunda a sexta; nenhuma, se a tarefa vence
        nesse dia; só o primeiro, se ela vence até o dia seguinte."""
        ter, sex, sab = D(2026, 11, 3), D(2026, 11, 6), D(2026, 11, 7)
        casos = [(ter, D(2026, 11, 2), None), (ter, ter, None), (ter, D(2026, 11, 4), (ter, ter)),
                 (ter, D(2026, 11, 6), (ter, D(2026, 11, 4))),
                 (sex, D(2026, 11, 9), (sex, sex)),            # na sexta, o seguinte é a segunda
                 (sex, D(2026, 11, 7), (sex, sex)),            # vence no sábado: só a sexta
                 (sex, D(2026, 11, 10), (sex, D(2026, 11, 9))),
                 (sab, D(2026, 11, 9), (sab, sab)), (sab, D(2026, 11, 10), (sab, D(2026, 11, 9)))]
        for entrou, prazo, dias in casos:
            with self.subTest(entrou=entrou, prazo=prazo):
                self.assertEqual(_dias_planejar(entrou, prazo), dias)

    def test_subtarefa_com_titulo_longo(self):
        """O título da subtarefa aceita um texto longo (o da tarefa, não); nas mensagens, ele vai cortado."""
        longo = "Ligar para o Mercado do João e combinar a entrega " * 40  # 2000 caracteres, com o espaço do fim
        t = _valida_tarefa({"titulo": "Feira", "prazo": "2026-10-30", "subtarefas": [{"titulo": longo}]}, criador=1)
        self.assertEqual(t["subtarefas"][0]["titulo"], longo.strip())
        with self.assertRaises(ValueError) as e:
            _valida_tarefa({"titulo": "Feira", "prazo": "2026-10-30",
                            "subtarefas": [{"titulo": longo, "prazo": "2026-10-31"}]}, criador=1)
        msg = str(e.exception)
        self.assertTrue(msg.startswith("a subtarefa “Ligar para o Mercado do João") and
                        "…” vence depois da tarefa (30/10)" in msg and len(msg) < 200, msg)


class TestTarefasNoBanco(BaseBanco):
    """Hoje é segunda, 26/10/2026. Ana cria; Beto participa com autonomia (e ganha a subtarefa automática, em 26 e
    27/10), Caio sem; Dani não participa."""

    def setUp(self):
        super().setUp()
        self.tarefas = Tarefas(self.banco, hoje=lambda: HOJE)
        self.agenda = Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE)
        self.ana, self.beto, self.caio, self.dani = (self.criar_usuario(n, paginas=GESTAO)
                                                     for n in ("ana", "beto", "caio", "dani"))

    def criar(self, **campos) -> dict:
        """A feira: prazo 30/10 às 14:00, uma subtarefa de cada um (Beto 28/10, Caio 29/10, Ana no prazo)."""
        return self.tarefas.criar(self.ana, {
            "titulo": "Feira", "prazo": "2026-10-30", "hora": "14:00",
            "participantes": [{"id": self.beto, "autonomia": True}, {"id": self.caio}],
            "subtarefas": [{"titulo": "Estande", "responsavel": self.beto, "prazo": "2026-10-28"},
                           {"titulo": "Material", "responsavel": self.caio, "prazo": "2026-10-29", "hora": "09:00"},
                           {"titulo": "Convites"}],
            **campos})

    def mes(self, usuario: int, mes: str = "2026-10") -> dict:
        return self.tarefas.no_mes(usuario, self.agenda.mes(usuario, mes))

    @staticmethod
    def no_dia(m: dict, dia: str) -> list[tuple]:
        return [(r["tarefa"], r["subtarefa"]) for d in m["dias"] if d["data"] == dia for r in d["tarefas"]]

    @staticmethod
    def sub(t: dict, titulo: str) -> dict:
        return next(s for s in t["subtarefas"] if s["titulo"] == titulo)

    def editar(self, t: dict, usuario=None, **campos) -> dict:
        """Salva o formulário de quem criou com a tarefa como está, trocando só `campos`."""
        dados = {"titulo": t["titulo"], "descricao": t["descricao"], "prazo": t["prazo"], "hora": t["hora"],
                 "participantes": t["participantes"],
                 "subtarefas": [{**s, "responsavel": s["responsavel"]["id"]} for s in t["subtarefas"]], **campos}
        return self.tarefas.editar(usuario or self.ana, t["id"], dados, campos.pop("versao", t["versao"]))

    def test_quem_ve_o_que(self):
        t = self.criar()
        estande, material, convites = (self.sub(t, n)["id"] for n in ("Estande", "Material", "Convites"))
        ana = self.mes(self.ana)
        self.assertEqual(self.no_dia(ana, "2026-10-28"), [(t["id"], estande)])
        self.assertEqual(self.no_dia(ana, "2026-10-29"), [(t["id"], material)])
        # no dia do prazo, as duas às 14:00: a tarefa antes da subtarefa
        self.assertEqual(self.no_dia(ana, "2026-10-30"), [(t["id"], None), (t["id"], convites)])
        beto = self.mes(self.beto)
        self.assertEqual(self.no_dia(beto, "2026-10-28"), [(t["id"], estande)])
        self.assertEqual(self.no_dia(beto, "2026-10-29"), [])  # a do Caio não aparece para ele
        self.assertEqual(self.no_dia(beto, "2026-10-30"), [(t["id"], None)])
        planejar = self.sub(t, TITULO_PLANEJAR)["id"]  # a automática do Beto: para ele, nos dois dias; para a Ana, não
        self.assertEqual([self.no_dia(m, d) for m in (beto, ana) for d in ("2026-10-26", "2026-10-27")],
                         [[(t["id"], planejar)], [(t["id"], planejar)], [], []])
        self.assertEqual(self.mes(self.dani)["tarefas"], [])
        self.assertEqual(self.mes(self.ana, "2026-11")["tarefas"], [])
        aberta = self.tarefas.obter(self.beto, t["id"])  # aberta, todas as subtarefas para todos
        self.assertEqual(len(aberta["subtarefas"]), 4)
        self.assertEqual((aberta["eu"], aberta["eu_criador"], aberta["minha_autonomia"], aberta["pode"]),
                         (self.beto, False, True, {"editar": False, "concluir": True, "criar_subtarefa": True,
                                                   "justificar": False}))
        self.assertEqual(self.sub(aberta, "Estande")["pode"], {"concluir": True, "editar_texto": True,
                                                               "editar_prazo": False, "justificar": False})
        self.assertEqual(self.sub(aberta, "Material")["pode"], {"concluir": False, "editar_texto": False,
                                                                "editar_prazo": False, "justificar": False})
        self.assertEqual([p["nome"] for p in aberta["participantes"]], ["Beto", "Caio"])  # sem quem criou
        self.assertEqual((aberta["criador"]["nome"], aberta["hora"], aberta["feitas"], aberta["total"]),
                         ("Ana", "14:00", 0, 4))
        with self.assertRaises(NaoEncontrada):
            self.tarefas.obter(self.dani, t["id"])
        with self.assertRaises(NaoEncontrada):
            self.tarefas.obter(self.ana, "abc")

    def test_no_mes_junta_com_as_atividades(self):
        a = self.agenda.criar(self.ana, {"titulo": "Visitar a loja", "inicio": "2026-10-28", "hora": "08:00"})["id"]
        t = self.criar()
        m = self.mes(self.ana)
        dia = next(d for d in m["dias"] if d["data"] == "2026-10-28")
        self.assertEqual([i["atividade"] for i in dia["itens"]], [a])
        self.assertEqual([r["tarefa"] for r in dia["tarefas"]], [t["id"]])
        self.assertEqual([a_["id"] for a_ in m["atividades"]], [a])
        self.assertTrue(all("tarefas" in d for d in m["dias"]))
        self.assertEqual(m["atrasadas"], [])

    def test_permissoes(self):
        t = self.criar()
        estande, material = self.sub(t, "Estande")["id"], self.sub(t, "Material")["id"]
        # Beto (autonomia) muda o texto da dele, mas nem o prazo, nem o responsável, nem a do Caio
        r = self.tarefas.editar_subtarefa(self.beto, estande, {"titulo": "Montar o estande", "prazo": "2026-10-28"})
        self.assertEqual(self.sub(r, "Montar o estande")["prazo"], "2026-10-28")
        for dados in ({"prazo": "2026-10-27"}, {"hora": "10:00"}, {"responsavel": self.caio}):
            with self.subTest(dados), self.assertRaises(PermissionError):
                self.tarefas.editar_subtarefa(self.beto, estande, dados)
        with self.assertRaises(PermissionError):
            self.tarefas.editar_subtarefa(self.beto, material, {"titulo": "do Caio"})
        with self.assertRaises(PermissionError):  # Caio não tem autonomia
            self.tarefas.editar_subtarefa(self.caio, material, {"titulo": "Material novo"})
        with self.assertRaises(NaoEncontrada):
            self.tarefas.editar_subtarefa(self.dani, material, {"titulo": "intrusa"})
        # Beto cria uma para si (sem o dia, com o prazo da tarefa); para outra pessoa, não
        r = self.tarefas.nova_subtarefa(self.beto, t["id"], {"titulo": "Fotos"})
        fotos = self.sub(r, "Fotos")
        self.assertEqual((fotos["responsavel"]["id"], fotos["prazo"], fotos["hora"]), (self.beto, "2026-10-30", "14:00"))
        with self.assertRaises(PermissionError):
            self.tarefas.nova_subtarefa(self.beto, t["id"], {"titulo": "x", "responsavel": self.caio})
        with self.assertRaises(PermissionError):
            self.tarefas.nova_subtarefa(self.caio, t["id"], {"titulo": "Caio sem autonomia"})
        # editar e excluir a tarefa, só quem criou (a situação dela, todos: test_mover)
        for chamada in (lambda u: self.editar(t, u, titulo="Outra"), lambda u: self.tarefas.excluir(u, t["id"])):
            for u in (self.beto, self.caio):
                with self.assertRaises(PermissionError):
                    chamada(u)
            with self.assertRaises(NaoEncontrada):
                chamada(self.dani)
        # quem criou muda tudo da subtarefa, até o prazo e o responsável
        r = self.tarefas.editar_subtarefa(self.ana, material, {"prazo": "2026-10-27", "responsavel": self.beto})
        self.assertEqual((self.sub(r, "Material")["prazo"], self.sub(r, "Material")["responsavel"]["nome"]),
                         ("2026-10-27", "Beto"))
        with self.assertRaises(ValueError):
            self.tarefas.editar_subtarefa(self.ana, material, {"prazo": "2026-10-31"})  # depois da tarefa
        with self.assertRaises(ValueError):
            self.tarefas.editar_subtarefa(self.ana, material, {"responsavel": self.dani})  # não participa

    def test_concluir(self):
        t = self.criar()
        estande, material = self.sub(t, "Estande")["id"], self.sub(t, "Material")["id"]
        r = self.tarefas.concluir_subtarefa(self.beto, estande)  # antes do prazo
        self.assertEqual((self.sub(r, "Estande")["feita"], self.sub(r, "Estande")["concluida_por"]["nome"]),
                         (True, "Beto"))
        with self.assertRaises(PermissionError):
            self.tarefas.concluir_subtarefa(self.caio, estande)
        r = self.tarefas.concluir_subtarefa(self.ana, material)  # quem criou também conclui
        self.assertEqual((r["feitas"], r["total"], self.sub(r, "Material")["concluida_por"]["nome"]), (2, 4, "Ana"))
        self.tarefas.desfazer_subtarefa(self.caio, material)
        with self.assertRaises(ValueError):
            self.tarefas.desfazer_subtarefa(self.caio, material)  # não estava concluída
        # a tarefa concluída leva junto as abertas; reaberta, elas voltam
        r = self.tarefas.concluir(self.ana, t["id"])
        self.assertEqual((r["feita"], r["feitas"]), (True, 4))
        self.assertEqual([(s["feita"], s["pela_tarefa"]) for s in r["subtarefas"]],  # a automática primeiro (27/10)
                         [(True, True), (True, False), (True, True), (True, True)])
        self.assertTrue(all(d["feita"] for x in self.mes(self.ana)["dias"] for d in x["tarefas"]))
        with self.assertRaises(ValueError):
            self.tarefas.concluir_subtarefa(self.caio, material)  # concluída: quem criou precisa reabrir
        with self.assertRaises(ValueError):
            self.tarefas.nova_subtarefa(self.ana, t["id"], {"titulo": "Mais uma"})
        r = self.tarefas.desfazer(self.ana, t["id"])
        self.assertEqual((r["feita"], r["feitas"], r["concluida_por"]), (False, 1, None))
        with self.assertRaises(ValueError):
            self.tarefas.desfazer(self.ana, t["id"])
        # qualquer pessoa da tarefa conclui e reabre; fica quem concluiu primeiro
        r = self.tarefas.concluir(self.caio, t["id"])
        self.assertEqual((r["feita"], r["concluida_por"]["nome"]), (True, "Caio"))
        r = self.tarefas.concluir(self.ana, t["id"])
        self.assertEqual(r["concluida_por"]["nome"], "Caio")
        self.assertEqual(self.tarefas.desfazer(self.beto, t["id"])["feita"], False)
        with self.assertRaises(NaoEncontrada):
            self.tarefas.concluir(self.dani, t["id"])

    def test_mover(self):
        t = self.criar()
        estande, material = self.sub(t, "Estande")["id"], self.sub(t, "Material")["id"]
        self.assertEqual((t["situacao"], self.sub(t, "Estande")["situacao"]), ("a_fazer", "a_fazer"))
        # a tarefa, qualquer pessoa dela muda de coluna; ir e voltar de Fazendo guarda quando começou
        r = self.tarefas.mover(self.ana, t["id"], "fazendo")
        comecou = r["iniciada_em"]
        self.assertEqual((r["situacao"], r["feita"], bool(comecou)), ("fazendo", False, True))
        r = self.tarefas.mover(self.ana, t["id"], "concluida")
        self.assertEqual((r["situacao"], r["feita"], r["feitas"]), ("concluida", True, 4))
        r = self.tarefas.desfazer(self.ana, t["id"])  # reabrir volta para Fazendo
        self.assertEqual((r["situacao"], r["iniciada_em"]), ("fazendo", comecou))
        r = self.tarefas.mover(self.ana, t["id"], "a_fazer")
        self.assertEqual((r["situacao"], r["iniciada_em"]), ("a_fazer", None))
        self.assertEqual(self.tarefas.mover(self.caio, t["id"], "fazendo")["situacao"], "fazendo")  # sem autonomia
        r = self.tarefas.mover(self.beto, t["id"], "concluida")
        self.assertEqual((r["situacao"], r["concluida_por"]["nome"]), ("concluida", "Beto"))
        r = self.tarefas.mover(self.caio, t["id"], "a_fazer")
        self.assertEqual((r["situacao"], r["concluida_por"]), ("a_fazer", None))
        with self.assertRaises(NaoEncontrada):
            self.tarefas.mover(self.dani, t["id"], "fazendo")
        for errada in ("feita", None, ["fazendo"]):
            with self.subTest(errada), self.assertRaises(ValueError):
                self.tarefas.mover(self.ana, t["id"], errada)
        # a subtarefa: o responsável (com ou sem autonomia) e quem criou
        r = self.tarefas.mover_subtarefa(self.caio, material, "fazendo")
        self.assertEqual(self.sub(r, "Material")["situacao"], "fazendo")
        r = self.tarefas.mover_subtarefa(self.caio, material, "concluida")
        self.assertEqual((self.sub(r, "Material")["feita"], self.sub(r, "Material")["concluida_por"]["nome"]),
                         (True, "Caio"))
        r = self.tarefas.mover_subtarefa(self.ana, material, "concluida")  # de novo: continua do Caio
        self.assertEqual(self.sub(r, "Material")["concluida_por"]["nome"], "Caio")
        r = self.tarefas.desfazer_subtarefa(self.caio, material)  # desfeita, volta para Fazendo
        self.assertEqual((self.sub(r, "Material")["situacao"], self.sub(r, "Material")["concluida_por"]), ("fazendo", None))
        r = self.tarefas.mover_subtarefa(self.ana, material, "a_fazer")
        self.assertEqual((self.sub(r, "Material")["situacao"], self.sub(r, "Material")["iniciada_em"]), ("a_fazer", None))
        with self.assertRaises(PermissionError):
            self.tarefas.mover_subtarefa(self.beto, material, "fazendo")  # não é dele
        with self.assertRaises(NaoEncontrada):
            self.tarefas.mover_subtarefa(self.dani, material, "fazendo")
        self.tarefas.mover_subtarefa(self.beto, estande, "fazendo")
        r = self.tarefas.concluir(self.ana, t["id"])  # com a tarefa concluída, todas contam como concluídas
        self.assertEqual({s["situacao"] for s in r["subtarefas"]}, {"concluida"})
        with self.assertRaises(ValueError):
            self.tarefas.mover_subtarefa(self.beto, estande, "a_fazer")
        r = self.tarefas.desfazer(self.ana, t["id"])
        self.assertEqual(self.sub(r, "Estande")["situacao"], "fazendo")
        self.assertEqual(r["versao"], t["versao"])  # mudar de coluna não é edição

    def test_relogio(self):
        """O começo e a conclusão gravam a hora do relógio da classe, que os testes fixam, e não a hora do banco."""
        tarefas = Tarefas(self.banco, agora=lambda: dt.datetime(2026, 10, 26, 9, 15))
        self.assertEqual(tarefas.hoje(), HOJE)
        t = tarefas.criar(self.ana, {"titulo": "Feira", "prazo": "2026-10-30"})
        self.assertEqual(tarefas.mover(self.ana, t["id"], "fazendo")["iniciada_em"], "2026-10-26T09:15:00")
        self.assertEqual(tarefas.concluir(self.ana, t["id"])["concluida_em"], "2026-10-26T09:15:00")
        self.assertEqual(self.tarefas.agora(), dt.datetime(2026, 10, 26))  # só com hoje: a meia-noite dele

    def test_quadro(self):
        t = self.criar()
        recente = self.tarefas.criar(self.ana, {"titulo": "Recente", "prazo": "2026-10-20"})
        antiga = self.tarefas.criar(self.ana, {"titulo": "Antiga", "prazo": "2026-09-01"})
        for x in (recente, antiga):
            self.tarefas.concluir(self.ana, x["id"])
        with self.banco.conexao() as con:  # a antiga foi concluída antes dos 30 dias do quadro
            con.execute("UPDATE agenda_tarefas SET concluida_em = '2026-09-02 10:00-03' WHERE id = %s", [antiga["id"]])
        q = self.tarefas.quadro(self.ana)
        self.assertEqual((q["hoje"], q["dias_concluidas"]), ("2026-10-26", 30))
        self.assertEqual([(x["titulo"], x["situacao"]) for x in q["tarefas"]],
                         [("Recente", "concluida"), ("Feira", "a_fazer")])  # pelo prazo
        beto = self.tarefas.quadro(self.beto)["tarefas"]  # participa só da feira; vê todas as subtarefas
        self.assertEqual(([x["id"] for x in beto], beto[0]["total"], beto[0]["pode"]["concluir"]), ([t["id"]], 4, True))
        self.assertEqual(self.tarefas.quadro(self.dani)["tarefas"], [])

    def test_atrasadas(self):
        t = self.criar(prazo="2026-10-23", hora=None, subtarefas=[
            {"titulo": "Estande", "responsavel": self.beto, "prazo": "2026-10-20"},
            {"titulo": "Material", "responsavel": self.caio, "prazo": "2026-10-23"}])
        antiga = self.tarefas.criar(self.ana, {"titulo": "De setembro", "prazo": "2026-09-15"})
        estande = self.sub(t, "Estande")["id"]
        ana = self.mes(self.ana)
        self.assertEqual([(r["tarefa"], r["subtarefa"]) for r in ana["atrasadas"]],
                         [(antiga["id"], None), (t["id"], estande), (t["id"], None),
                          (t["id"], self.sub(t, "Material")["id"])])
        self.assertEqual([(r["tarefa"], r["subtarefa"]) for r in self.mes(self.beto)["atrasadas"]],
                         [(t["id"], estande), (t["id"], None)])
        self.assertEqual(self.mes(self.ana, "2026-11")["atrasadas"], [])  # só no mês de hoje
        self.assertTrue(self.tarefas.obter(self.ana, t["id"])["atrasada"])
        self.tarefas.concluir_subtarefa(self.beto, estande)
        self.assertEqual([(r["tarefa"], r["subtarefa"]) for r in self.mes(self.beto)["atrasadas"]], [(t["id"], None)])
        self.tarefas.concluir(self.ana, t["id"])
        self.assertEqual([r["tarefa"] for r in self.mes(self.ana)["atrasadas"]], [antiga["id"]])
        # o prazo de hoje ainda não atrasou
        self.tarefas.criar(self.ana, {"titulo": "Hoje", "prazo": "2026-10-26"})
        self.assertEqual(len(self.mes(self.ana)["atrasadas"]), 1)

    def test_justificar(self):
        # no prazo ainda: não há o que justificar
        noprazo = self.criar()
        with self.assertRaises(ValueError) as e:
            self.tarefas.justificar(self.ana, noprazo["id"], "x")
        self.assertIn("não atrasou", str(e.exception))
        r = self.tarefas.concluir_subtarefa(self.beto, self.sub(noprazo, "Estande")["id"])  # concluída antes do prazo
        self.assertFalse(self.sub(r, "Estande")["venceu"])
        with self.assertRaises(ValueError):
            self.tarefas.justificar_subtarefa(self.beto, self.sub(r, "Estande")["id"], "x")
        # venceu em 23/10: quem criou justifica a tarefa; o responsável, a subtarefa
        t = self.criar(prazo="2026-10-23", hora=None, subtarefas=[
            {"titulo": "Estande", "responsavel": self.beto, "prazo": "2026-10-20"},
            {"titulo": "Material", "responsavel": self.caio, "prazo": "2026-10-23"}])
        estande, material = self.sub(t, "Estande")["id"], self.sub(t, "Material")["id"]
        self.assertEqual((t["venceu"], t["pode"]["justificar"], t["justificativas"]), (True, True, []))
        r = self.tarefas.justificar(self.ana, t["id"], "  Faltou o caminhão  ")
        self.assertEqual(r["justificativas"], [{"texto": "Faltou o caminhão", "criada_em": "2026-10-26T00:00:00",
                                                "por": {"id": self.ana, "nome": "Ana"}, "prazo": "2026-10-23",
                                                "hora": None, "do_prazo": True}])
        self.assertEqual(r["versao"], t["versao"])  # justificar não é edição
        r = self.tarefas.justificar_subtarefa(self.beto, estande, "Choveu no dia da montagem")
        estande_j = self.sub(r, "Estande")["justificativas"]
        self.assertEqual([(j["texto"], j["por"]["nome"]) for j in estande_j], [("Choveu no dia da montagem", "Beto")])
        caio = self.tarefas.obter(self.caio, t["id"])  # todos da tarefa veem; cada um justifica só a sua
        self.assertEqual((caio["justificativas"][0]["texto"], caio["pode"]["justificar"]), ("Faltou o caminhão", False))
        self.assertEqual([(s["titulo"], s["pode"]["justificar"]) for s in caio["subtarefas"]],
                         [("Estande", False), ("Material", True)])
        for u, chamada in ((self.beto, lambda u: self.tarefas.justificar(u, t["id"], "x")),
                           (self.caio, lambda u: self.tarefas.justificar_subtarefa(u, estande, "x")),
                           (self.ana, lambda u: self.tarefas.justificar_subtarefa(u, material, "x"))):
            with self.subTest(u), self.assertRaises(PermissionError):
                chamada(u)
        with self.assertRaises(NaoEncontrada):
            self.tarefas.justificar(self.dani, t["id"], "x")
        with self.assertRaises(ValueError):
            self.tarefas.justificar(self.ana, t["id"], "x" * 2001)
        # é um histórico: vazia não vale (não apaga), e outra se acrescenta, a mais nova primeiro
        with self.assertRaises(ValueError) as e:
            self.tarefas.justificar_subtarefa(self.beto, estande, "   ")
        self.assertIn("por que atrasou", str(e.exception))
        r = self.tarefas.justificar_subtarefa(self.beto, estande, "Faltou a lona")
        self.assertEqual([j["texto"] for j in self.sub(r, "Estande")["justificativas"]],
                         ["Faltou a lona", "Choveu no dia da montagem"])
        # concluída depois do prazo continua podendo justificar (também com a tarefa concluída)
        self.tarefas.concluir(self.ana, t["id"])
        r = self.tarefas.justificar_subtarefa(self.caio, material, "Esperei o fornecedor")
        self.assertEqual((r["atrasada"], r["venceu"], self.sub(r, "Material")["venceu"]), (False, True, True))
        # a tarefa concluída no prazo não venceu
        with self.banco.conexao() as con:
            con.execute("UPDATE agenda_tarefas SET concluida_em = '2026-10-22 18:00-03' WHERE id = %s", [t["id"]])
        r = self.tarefas.obter(self.ana, t["id"])
        self.assertEqual((r["venceu"], self.sub(r, "Material")["venceu"], self.sub(r, "Estande")["venceu"]),
                         (False, False, True))  # a do Beto vencia em 20/10

    def test_vence_no_horario(self):
        """Com horário, a tarefa vence logo depois dele; sem horário, quando o dia acaba. A que venceu hoje fica no dia
        de hoje, sem repetir no bloco das atrasadas (que é dos dias anteriores)."""
        relogio = {"agora": dt.datetime(2026, 10, 26, 9, 0)}
        tarefas = Tarefas(self.banco, agora=lambda: relogio["agora"])
        t = tarefas.criar(self.ana, {"titulo": "Ligar", "prazo": "2026-10-26", "hora": "09:00",
                                     "subtarefas": [{"titulo": "Sem horário", "prazo": "2026-10-26", "hora": None}]})
        self.assertEqual((t["atrasada"], t["venceu"], t["subtarefas"][0]["atrasada"]), (False, False, False))
        relogio["agora"] = dt.datetime(2026, 10, 26, 9, 1)
        t = tarefas.obter(self.ana, t["id"])
        self.assertEqual((t["atrasada"], t["venceu"], t["subtarefas"][0]["atrasada"]), (True, True, False))
        m = tarefas.no_mes(self.ana, self.agenda.mes(self.ana, "2026-10"))
        self.assertEqual((self.no_dia(m, "2026-10-26")[0], m["atrasadas"]), ((t["id"], None), []))
        relogio["agora"] = dt.datetime(2026, 10, 27, 0, 0, 1)  # o dia da subtarefa sem horário acabou
        self.assertTrue(tarefas.obter(self.ana, t["id"])["subtarefas"][0]["atrasada"])

    def test_pendencias_e_as_24_horas(self):
        """A linha do tempo do plano: subtarefa do Beto até 27/10 às 10:00, numa tarefa da Ana até 31/10."""
        relogio = {"agora": dt.datetime(2026, 10, 27, 10, 0)}
        tarefas = Tarefas(self.banco, agora=lambda: relogio["agora"])
        t = tarefas.criar(self.ana, {"titulo": "Feira", "prazo": "2026-10-31", "participantes": [{"id": self.beto}],
                                     "subtarefas": [{"titulo": "Preços", "responsavel": self.beto,
                                                     "prazo": "2026-10-27", "hora": "10:00"}]})
        sub = t["subtarefas"][0]["id"]

        def em(*quando):
            relogio["agora"] = dt.datetime(2026, *quando)
            return [(p["titulo"], p["ultima"] and p["ultima"]["texto"]) for p in tarefas.pendencias(self.beto)]

        self.assertEqual(em(10, 27, 10, 0), [])  # no horário do prazo ainda não venceu
        self.assertEqual(em(10, 27, 10, 1), [("Preços", None)])
        p, = tarefas.pendencias(self.beto)
        self.assertEqual({k: p[k] for k in ("tarefa", "subtarefa", "tarefa_titulo", "prazo", "hora", "vence_em",
                                            "eu_criador")},
                         {"tarefa": t["id"], "subtarefa": sub, "tarefa_titulo": "Feira", "prazo": "2026-10-27",
                          "hora": "10:00", "vence_em": "2026-10-27T10:00:00", "eu_criador": False})
        self.assertEqual((p["criador"]["nome"], tarefas.pendencias(self.ana)), ("Ana", []))  # é só do responsável
        em(10, 27, 10, 15)
        tarefas.justificar_subtarefa(self.beto, sub, "o fornecedor não respondeu")
        self.assertEqual(em(10, 28, 10, 14), [])
        self.assertEqual(em(10, 28, 10, 16), [("Preços", "o fornecedor não respondeu")])  # 24 h depois, de novo
        tarefas.justificar_subtarefa(self.beto, sub, "liguei de novo")
        self.assertEqual(em(10, 28, 11, 0), [])
        t = tarefas.obter(self.ana, t["id"])  # a Ana prorroga para 31/10, sem horário
        prorrogada = {"titulo": "Feira", "prazo": "2026-10-31", "participantes": [{"id": self.beto}],
                      "subtarefas": [{"id": sub, "titulo": "Preços", "responsavel": self.beto, "prazo": "2026-10-31"}]}
        tarefas.editar(self.ana, t["id"], prorrogada, t["versao"])
        self.assertEqual(em(10, 31, 23, 59), [])
        self.assertEqual(em(11, 1, 0, 0, 1), [("Preços", "liguei de novo")])  # a de antes era de outro prazo
        r = tarefas.justificar_subtarefa(self.beto, sub, "terminei ontem", concluir=True)
        self.assertEqual((r["subtarefas"][0]["feita"], em(11, 1, 8, 0)), (True, []))
        js = r["subtarefas"][0]["justificativas"]
        self.assertEqual([(j["texto"], j["prazo"], j["do_prazo"]) for j in js],
                         [("terminei ontem", "2026-10-31", True), ("liguei de novo", "2026-10-27", False),
                          ("o fornecedor não respondeu", "2026-10-27", False)])
        # a tarefa vencida pede a justificativa a quem criou; concluída, não pede nada
        self.assertEqual([p["titulo"] for p in tarefas.pendencias(self.ana)], ["Feira"])
        self.assertEqual(tarefas.pendencias(self.ana)[0]["eu_criador"], True)
        tarefas.justificar(self.ana, t["id"], "a gráfica atrasou", concluir=True)
        self.assertEqual(tarefas.pendencias(self.ana), [])

    def test_editar(self):
        t = self.criar()
        with self.assertRaises(ValueError) as e:
            self.editar(t, versao=t["versao"] + 1)
        self.assertIn("acabou de mudar", str(e.exception))
        # troca: muda a do Beto, tira a do Caio, entra uma nova; quem é concluída continua concluída
        self.tarefas.concluir_subtarefa(self.beto, self.sub(t, "Estande")["id"])
        t = self.tarefas.obter(self.ana, t["id"])
        subs = [{**self.sub(t, "Estande"), "titulo": "Estande grande", "responsavel": self.beto},
                {**self.sub(t, "Convites"), "responsavel": self.ana},
                {"titulo": "Som", "responsavel": self.caio, "prazo": "2026-10-29"}]
        r = self.editar(t, titulo="Feira de novembro", subtarefas=subs)
        self.assertEqual(r["titulo"], "Feira de novembro")
        self.assertEqual([(s["titulo"], s["feita"]) for s in r["subtarefas"]],  # a automática fica (não vem do formulário)
                         [(TITULO_PLANEJAR, False), ("Estande grande", True), ("Som", False), ("Convites", False)])
        self.assertEqual(r["versao"], t["versao"] + 1)
        # tirar o Caio com a subtarefa dele não dá; passando para a Ana na mesma edição, dá
        sem_caio = [p for p in r["participantes"] if p["id"] != self.caio]
        with self.assertRaises(ValueError) as e:
            self.editar(r, participantes=sem_caio)
        self.assertIn("não participa", str(e.exception))
        subs = [{**s, "responsavel": self.ana if s["responsavel"]["id"] == self.caio else s["responsavel"]["id"]}
                for s in r["subtarefas"]]
        r = self.editar(r, participantes=sem_caio, subtarefas=subs)
        self.assertEqual([p["nome"] for p in r["participantes"]], ["Beto"])
        with self.assertRaises(NaoEncontrada):
            self.tarefas.obter(self.caio, t["id"])
        # o prazo da tarefa não fica antes das subtarefas
        with self.assertRaises(ValueError):
            self.editar(r, prazo="2026-10-27")
        # participante novo: ativo e com a Gestão; quem já estava fica mesmo sem ela
        sem_gestao = self.criar_usuario("eva")
        with self.banco.conexao() as con:
            con.execute("UPDATE usuarios SET ativo = false WHERE id = %s", [self.dani])
            con.execute("UPDATE usuarios SET paginas = '{metas}' WHERE id = %s", [self.beto])
        for pessoa in (self.dani, sem_gestao):
            with self.subTest(pessoa), self.assertRaises(ValueError) as e:
                self.editar(r, participantes=[*r["participantes"], {"id": pessoa}])
            self.assertIn("sem a página Gestão", str(e.exception))
        r = self.editar(r, descricao="Beto continua")
        self.assertEqual(r["descricao"], "Beto continua")
        # subtarefa de outra tarefa
        outra = self.tarefas.criar(self.ana, {"titulo": "Outra", "prazo": "2026-10-30", "subtarefas": [{"titulo": "x"}]})
        with self.assertRaises(ValueError):
            self.editar(r, subtarefas=[{"id": outra["subtarefas"][0]["id"], "titulo": "x"}])
        # Beto acrescenta uma subtarefa: o formulário que a Ana tinha aberto fica velho
        self.tarefas.nova_subtarefa(self.beto, r["id"], {"titulo": "Fotos"})
        with self.assertRaises(ValueError):
            self.editar(r, titulo="Por cima")
        self.assertIn("Fotos", [s["titulo"] for s in self.tarefas.obter(self.ana, r["id"])["subtarefas"]])

    def avisos(self, usuario: int, tipo: str) -> list[str]:
        with self.banco.conexao() as con:
            return [r[0] for r in con.execute("SELECT texto FROM notificacoes WHERE usuario = %s AND tipo = %s "
                                              "ORDER BY id", [usuario, tipo])]

    def test_subtarefa_automatica(self):
        """Beto entra com autonomia: a automática aparece para ele em 26 e 27/10 e é uma só (concluída, fica feita nos
        dois dias); ninguém a edita; o aviso de quem entrou já pede para programar, sem o "vence em breve"."""
        t = self.criar()
        auto = self.sub(t, TITULO_PLANEJAR)
        self.assertEqual([s["responsavel"]["nome"] for s in t["subtarefas"] if s["automatica"]], ["Beto"])  # Caio não
        self.assertEqual((auto["inicio"], auto["prazo"], auto["hora"], auto["pode"]),
                         ("2026-10-26", "2026-10-27", None,  # quem criou a vê de Ana: conclui, mas não edita
                          {"concluir": True, "editar_texto": False, "editar_prazo": False, "justificar": False}))
        for u, pode in ((self.beto, True), (self.caio, False)):
            self.assertEqual(self.sub(self.tarefas.obter(u, t["id"]), TITULO_PLANEJAR)["pode"],
                             {"concluir": pode, "editar_texto": False, "editar_prazo": False, "justificar": False})
        r = self.tarefas.concluir_subtarefa(self.beto, auto["id"])
        self.assertEqual((r["feitas"], r["total"]), (1, 4))
        beto = self.mes(self.beto)
        self.assertEqual([r_["feita"] for d in beto["dias"] if d["data"] in ("2026-10-26", "2026-10-27")
                          for r_ in d["tarefas"]], [True, True])
        for u in (self.beto, self.ana):
            with self.subTest(u), self.assertRaises(PermissionError):
                self.tarefas.editar_subtarefa(u, auto["id"], {"titulo": "Outra coisa"})
        self.assertEqual(self.avisos(self.beto, "incluido"),
                         ["Ana incluiu você na tarefa “Feira” (prazo 30/10 às 14:00), com 1 subtarefa para você. Crie "
                          "as suas subtarefas para programar a execução (até 27/10)"])
        self.assertNotIn("Crie", self.avisos(self.caio, "incluido")[0])
        self.tarefas.desfazer_subtarefa(self.beto, auto["id"])
        self.tarefas.gerar_avisos(self.beto)
        self.assertEqual(self.avisos(self.beto, "vence_em_breve"), [])
        # o formulário de quem criou não traz a automática; se trouxer, ela fica como está
        r = self.editar(self.tarefas.obter(self.ana, t["id"]), subtarefas=[
            {"id": auto["id"], "titulo": "Por cima", "responsavel": self.beto, "prazo": "2026-10-30"},
            *[{**s, "responsavel": s["responsavel"]["id"]} for s in t["subtarefas"] if not s["automatica"]]])
        self.assertEqual((self.sub(r, TITULO_PLANEJAR)["prazo"], len(r["subtarefas"])), ("2026-10-27", 4))
        # sem tempo: a tarefa que vence hoje não tem; a que vence amanhã, só hoje
        hoje = self.tarefas.criar(self.ana, {"titulo": "Hoje", "prazo": "2026-10-26",
                                             "participantes": [{"id": self.beto, "autonomia": True}]})
        amanha = self.tarefas.criar(self.ana, {"titulo": "Amanhã", "prazo": "2026-10-27",
                                               "participantes": [{"id": self.beto, "autonomia": True}]})
        self.assertEqual(hoje["subtarefas"], [])
        self.assertEqual([(s["inicio"], s["prazo"]) for s in amanha["subtarefas"]], [("2026-10-26", "2026-10-26")])

    def test_automatica_pula_o_fim_de_semana(self):
        """Criada na sexta (30/10), a automática fica na sexta e na segunda (02/11), sem o sábado e o domingo; atrasa
        só depois da segunda."""
        sexta = D(2026, 10, 30)
        tarefas = Tarefas(self.banco, hoje=lambda: sexta)
        agenda = Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: sexta)
        t = tarefas.criar(self.ana, {"titulo": "Feira", "prazo": "2026-11-05",
                                     "participantes": [{"id": self.beto, "autonomia": True}]})
        auto = t["subtarefas"][0]
        self.assertEqual((auto["inicio"], auto["prazo"]), ("2026-10-30", "2026-11-02"))
        outubro, novembro = (tarefas.no_mes(self.beto, agenda.mes(self.beto, m)) for m in ("2026-10", "2026-11"))
        dias = [d for m, ds in ((outubro, ("2026-10-30", "2026-10-31")), (novembro, ("2026-11-01", "2026-11-02")))
                for d in ds if self.no_dia(m, d)]
        self.assertEqual(dias, ["2026-10-30", "2026-11-02"])
        self.assertEqual(outubro["atrasadas"], [])

    def test_automatica_segue_a_autonomia(self):
        """Tirar a autonomia (ou a pessoa) tira a automática, mesmo feita; ganhar a autonomia, ou entrar com ela, cria
        uma a partir do dia de hoje; o prazo da tarefa encurtado encurta a automática."""
        relogio = {"hoje": HOJE}
        tarefas = Tarefas(self.banco, hoje=lambda: relogio["hoje"])
        t = tarefas.criar(self.ana, {"titulo": "Feira", "prazo": "2026-10-30",
                                     "participantes": [{"id": self.beto, "autonomia": True}, {"id": self.caio}]})
        auto_beto = t["subtarefas"][0]["id"]
        tarefas.concluir_subtarefa(self.beto, auto_beto)

        def salvar(participantes, **campos):
            atual = tarefas.obter(self.ana, t["id"])
            return tarefas.editar(self.ana, t["id"], {"titulo": "Feira", "prazo": atual["prazo"],
                                                      "participantes": participantes, **campos}, atual["versao"])

        def automaticas(r):
            return [(s["responsavel"]["nome"], s["inicio"], s["prazo"], s["feita"]) for s in r["subtarefas"]
                    if s["automatica"]]

        relogio["hoje"] = D(2026, 10, 27)  # terça: Beto perde a autonomia, Caio ganha, Dani entra com ela
        r = salvar([{"id": self.beto}, {"id": self.caio, "autonomia": True}, {"id": self.dani, "autonomia": True}])
        self.assertEqual(automaticas(r), [("Caio", "2026-10-27", "2026-10-28", False),
                                          ("Dani", "2026-10-27", "2026-10-28", False)])
        self.assertEqual(self.avisos(self.caio, "subtarefa_nova"),
                         ["Ana deu autonomia a você na tarefa “Feira”. Crie as suas subtarefas para programar a "
                          "execução (até 28/10)"])
        self.assertIn("(até 28/10)", self.avisos(self.dani, "incluido")[0])
        self.assertEqual(self.avisos(self.dani, "subtarefa_nova"), [])  # um aviso só para quem entrou
        relogio["hoje"] = D(2026, 10, 29)  # quinta: Beto ganha de novo a autonomia; a tarefa vence amanhã, só hoje
        r = salvar([{"id": p, "autonomia": True} for p in (self.beto, self.caio, self.dani)])
        self.assertEqual(automaticas(r)[-1], ("Beto", "2026-10-29", "2026-10-29", False))  # a nova, pelo prazo
        # salvar de novo, com todos com autonomia, não cria nem mexe em nada
        self.assertEqual(automaticas(salvar([{"id": p, "autonomia": True} for p in (self.beto, self.caio, self.dani)])),
                         automaticas(r))
        # o prazo da tarefa vai para 27/10: as automáticas encurtam junto
        r = salvar([{"id": p, "autonomia": True} for p in (self.beto, self.caio, self.dani)], prazo="2026-10-27")
        self.assertEqual(automaticas(r), [("Caio", "2026-10-27", "2026-10-27", False),
                                          ("Dani", "2026-10-27", "2026-10-27", False),
                                          ("Beto", "2026-10-27", "2026-10-27", False)])
        # quem sai leva a automática junto
        r = salvar([{"id": self.caio, "autonomia": True}])
        self.assertEqual(([p["nome"] for p in r["participantes"]], [x[0] for x in automaticas(r)]), (["Caio"], ["Caio"]))

    def test_automatica_vencida_cobra_a_justificativa(self):
        """Não concluída até o fim do segundo dia, a automática atrasa como as outras: bloqueia o painel do
        responsável até ele justificar, e quem criou recebe o aviso "venceu" (mas não a vê nos dias da agenda)."""
        relogio = {"agora": dt.datetime(2026, 10, 26, 9, 0)}
        tarefas = Tarefas(self.banco, agora=lambda: relogio["agora"])
        t = tarefas.criar(self.ana, {"titulo": "Feira", "prazo": "2026-10-30",
                                     "participantes": [{"id": self.beto, "autonomia": True}]})
        auto = t["subtarefas"][0]["id"]
        relogio["agora"] = dt.datetime(2026, 10, 27, 23, 59)
        self.assertEqual(tarefas.pendencias(self.beto), [])
        relogio["agora"] = dt.datetime(2026, 10, 28, 0, 0, 1)
        self.assertEqual([p["subtarefa"] for p in tarefas.pendencias(self.beto)], [auto])
        agenda = Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: relogio["agora"].date())
        m = tarefas.no_mes(self.beto, agenda.mes(self.beto, "2026-10"))
        self.assertEqual([(r["tarefa"], r["subtarefa"]) for r in m["atrasadas"]], [(t["id"], auto)])
        self.assertEqual(tarefas.no_mes(self.ana, agenda.mes(self.ana, "2026-10"))["atrasadas"], [])
        tarefas.gerar_avisos(self.ana)
        self.assertEqual(len(self.avisos(self.ana, "venceu")), 1)
        tarefas.justificar_subtarefa(self.beto, auto, "estava na rua", concluir=True)
        self.assertEqual(tarefas.pendencias(self.beto), [])

    def test_participante_escolhe_o_dia(self):
        """Com autonomia, o participante escolhe o dia das subtarefas que cria para si (até o prazo da tarefa) e muda o
        dia delas depois; o das que quem criou passou para ele, não."""
        t = self.criar()
        r = self.tarefas.nova_subtarefa(self.beto, t["id"], {"titulo": "Fotos", "prazo": "2026-10-28", "hora": "16:00"})
        fotos = self.sub(r, "Fotos")
        self.assertEqual((fotos["prazo"], fotos["hora"], fotos["pode"]["editar_prazo"]), ("2026-10-28", "16:00", True))
        self.assertFalse(self.sub(r, "Estande")["pode"]["editar_prazo"])
        r = self.tarefas.editar_subtarefa(self.beto, fotos["id"], {"prazo": "2026-10-29", "hora": None})
        self.assertEqual((self.sub(r, "Fotos")["prazo"], self.sub(r, "Fotos")["hora"]), ("2026-10-29", None))
        with self.assertRaises(ValueError):  # depois da tarefa
            self.tarefas.nova_subtarefa(self.beto, t["id"], {"titulo": "Tarde", "prazo": "2026-10-31"})
        with self.assertRaises(ValueError):
            self.tarefas.editar_subtarefa(self.beto, fotos["id"], {"prazo": "2026-10-31"})
        with self.assertRaises(PermissionError):
            self.tarefas.editar_subtarefa(self.beto, fotos["id"], {"responsavel": self.caio})
        with self.assertRaises(PermissionError):
            self.tarefas.editar_subtarefa(self.beto, self.sub(r, "Estande")["id"], {"prazo": "2026-10-27"})
        # sem a autonomia, nem o dia da que ele criou
        self.editar(self.tarefas.obter(self.ana, t["id"]),
                    participantes=[{"id": self.beto}, {"id": self.caio}])
        with self.assertRaises(PermissionError):
            self.tarefas.editar_subtarefa(self.beto, fotos["id"], {"prazo": "2026-10-28"})

    def test_pessoas(self):
        admin = self.criar_usuario("zeca", papel="admin")
        self.criar_usuario("eva")  # sem a Gestão
        with self.banco.conexao() as con:
            con.execute("UPDATE usuarios SET ativo = false WHERE id = %s", [self.dani])
            sem_paginas = con.execute("INSERT INTO usuarios (login, nome, papel, senha) "
                                      "VALUES ('fabio', 'Fabio', 'visualizador', 'x') RETURNING id").fetchone()[0]
        p = self.tarefas.pessoas(self.ana)
        self.assertEqual(p["eu"], {"id": self.ana, "nome": "Ana"})
        self.assertEqual([x["id"] for x in p["pessoas"]], [self.beto, self.caio, admin])
        self.assertNotIn(sem_paginas, [x["id"] for x in p["pessoas"]])  # sem páginas: só Metas
        with self.assertRaises(ValueError):
            self.tarefas.criar(self.ana, {"titulo": "x", "prazo": "2026-10-30", "participantes": [sem_paginas]})

    def test_excluir_e_usuario_excluido(self):
        t = self.criar()
        self.tarefas.concluir_subtarefa(self.beto, self.sub(t, "Estande")["id"])
        with self.banco.conexao() as con:  # Beto sai: leva a subtarefa e a participação
            con.execute("DELETE FROM usuarios WHERE id = %s", [self.beto])
        r = self.tarefas.obter(self.ana, t["id"])
        self.assertEqual(([p["nome"] for p in r["participantes"]], r["total"]), (["Caio"], 2))
        self.tarefas.excluir(self.ana, t["id"])
        self.assertEqual((self.contar("agenda_tarefas"), self.contar("agenda_tarefa_pessoas"),
                          self.contar("agenda_subtarefas")), (0, 0, 0))
        self.tarefas.criar(self.ana, {"titulo": "Outra", "prazo": "2026-10-30", "participantes": [self.caio],
                                      "subtarefas": [{"titulo": "x", "responsavel": self.caio}]})
        with self.banco.conexao() as con:  # Ana sai: a tarefa que ela criou vai junto
            con.execute("DELETE FROM usuarios WHERE id = %s", [self.ana])
        self.assertEqual((self.contar("agenda_tarefas"), self.contar("agenda_tarefa_pessoas"),
                          self.contar("agenda_subtarefas")), (0, 0, 0))
        with self.assertRaises(NaoEncontrada):
            self.tarefas.criar(self.ana, {"titulo": "x", "prazo": "2026-10-30"})

    def test_o_banco_confere(self):
        from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
        t = self.criar()
        with self.assertRaises(ForeignKeyViolation), self.banco.conexao() as con:
            con.execute("INSERT INTO agenda_subtarefas (tarefa, responsavel, titulo, prazo) "
                        "VALUES (%s, %s, 'x', '2026-10-30')", [t["id"], self.dani])  # não participa
        with self.assertRaises(ForeignKeyViolation), self.banco.conexao() as con:
            con.execute("DELETE FROM agenda_tarefa_pessoas WHERE tarefa = %s AND usuario = %s", [t["id"], self.caio])
        with self.assertRaises(CheckViolation), self.banco.conexao() as con:
            con.execute("UPDATE agenda_tarefas SET titulo = '  ' WHERE id = %s", [t["id"]])
        with self.assertRaises(CheckViolation), self.banco.conexao() as con:  # quem concluiu, sem estar concluída
            con.execute("UPDATE agenda_tarefas SET concluida_por = %s WHERE id = %s", [self.ana, t["id"]])
        with self.banco.conexao() as con:  # o título da subtarefa vai até 2000 caracteres (migração 030)
            con.execute("UPDATE agenda_subtarefas SET titulo = repeat('x', 2000) WHERE tarefa = %s", [t["id"]])
        with self.assertRaises(CheckViolation), self.banco.conexao() as con:
            con.execute("UPDATE agenda_subtarefas SET titulo = repeat('x', 2001) WHERE tarefa = %s", [t["id"]])
        with self.assertRaises(CheckViolation), self.banco.conexao() as con:  # o da tarefa, até 120
            con.execute("UPDATE agenda_tarefas SET titulo = repeat('x', 121) WHERE id = %s", [t["id"]])
        with self.assertRaises(CheckViolation), self.banco.conexao() as con:  # o início não passa do prazo (035)
            con.execute("UPDATE agenda_subtarefas SET inicio = prazo + 1 WHERE tarefa = %s", [t["id"]])
        with self.assertRaises(UniqueViolation), self.banco.conexao() as con:  # uma automática por pessoa
            con.execute("INSERT INTO agenda_subtarefas (tarefa, responsavel, titulo, prazo, inicio, automatica) "
                        "VALUES (%s, %s, 'x', '2026-10-27', '2026-10-26', true)", [t["id"], self.beto])


class TestMigracao027(BaseBanco):
    def test_justificativas_viram_historico(self):
        """As justificativas de antes (colunas da 022) entram no histórico com o prazo de agora; as colunas saem."""
        from unittest import mock
        from bi.banco import Banco
        todas = Banco._arquivos_migracao()
        with mock.patch.object(Banco, "_arquivos_migracao", staticmethod(lambda: [a for a in todas if a.stem < "027"])):
            self.banco.migrar()
        ana, beto = self.criar_usuario("ana", paginas=GESTAO), self.criar_usuario("beto", paginas=GESTAO)
        with self.banco.conexao() as con:
            t = con.execute("INSERT INTO agenda_tarefas (criador, titulo, prazo, hora, justificativa, justificada_em) "
                            "VALUES (%s, 'Feira', '2026-10-23', '14:00', 'Faltou o caminhão', '2026-10-24 09:00-03') "
                            "RETURNING id", [ana]).fetchone()[0]
            con.execute("INSERT INTO agenda_tarefa_pessoas (tarefa, usuario) VALUES (%s, %s), (%s, %s)",
                        [t, ana, t, beto])
            con.execute("INSERT INTO agenda_subtarefas (tarefa, responsavel, titulo, prazo, justificativa, "
                        "justificada_em, justificada_por) VALUES "
                        "(%s, %s, 'Estande', '2026-10-20', 'Choveu', '2026-10-21 10:00-03', %s), "
                        "(%s, %s, 'Sem atraso', '2026-10-20', '', NULL, NULL)", [t, beto, beto, t, beto])
        self.assertIn("027_agenda_justificativas", self.banco.migrar())
        with self.banco.conexao() as con:
            linhas = con.execute("SELECT j.subtarefa IS NULL, u.nome, j.prazo, j.hora, j.texto, j.criada_em "
                                 "FROM agenda_justificativas j JOIN usuarios u ON u.id = j.usuario "
                                 "ORDER BY j.criada_em").fetchall()
            colunas = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns "
                                                 "WHERE table_schema = current_schema() "
                                                 "AND table_name IN ('agenda_tarefas', 'agenda_subtarefas')")}
        self.assertEqual([(tarefa, nome, str(prazo), hora, texto) for tarefa, nome, prazo, hora, texto, _ in linhas],
                         [(False, "Beto", "2026-10-20", None, "Choveu"),
                          (True, "Ana", "2026-10-23", T(14), "Faltou o caminhão")])
        utc = dt.timezone.utc  # o dia em que foram escritas (10:00 e 09:00 em Brasília)
        self.assertEqual([c for *_, c in linhas], [dt.datetime(2026, 10, 21, 13, tzinfo=utc),
                                                   dt.datetime(2026, 10, 24, 12, tzinfo=utc)])
        self.assertFalse(colunas & {"justificativa", "justificada_em", "justificada_por"})


if __name__ == "__main__":
    unittest.main()

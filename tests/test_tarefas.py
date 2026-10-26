"""Tarefas da agenda (bi/tarefas.py): a conferência do formulário e, no PostgreSQL, quem vê o quê, quem pode o quê, a
conclusão, as atrasadas, a edição (com a versão) e o que acontece quando um usuário é excluído.

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import unittest

from bi.agenda import Agenda
from bi.conversas import NaoEncontrada
from bi.tarefas import MAX_SUBTAREFAS, Tarefas, _ate_o_prazo, _valida_tarefa
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
            "pessoa inválida": {**base, "participantes": ["ana"]},
            f"até {MAX_SUBTAREFAS} subtarefas": {**base, "subtarefas": [{"titulo": "A"}] * (MAX_SUBTAREFAS + 1)},
        }
        for trecho, dados in casos.items():
            with self.subTest(trecho), self.assertRaises(ValueError) as e:
                _valida_tarefa(dados, criador=1)
            self.assertIn(trecho, str(e.exception))


class TestTarefasNoBanco(BaseBanco):
    """Hoje é segunda, 26/10/2026. Ana cria; Beto participa com autonomia, Caio sem; Dani não participa."""

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
        self.assertEqual(self.mes(self.dani)["tarefas"], [])
        self.assertEqual(self.mes(self.ana, "2026-11")["tarefas"], [])
        aberta = self.tarefas.obter(self.beto, t["id"])  # aberta, todas as subtarefas para todos
        self.assertEqual(len(aberta["subtarefas"]), 3)
        self.assertEqual((aberta["eu_criador"], aberta["minha_autonomia"], aberta["pode"]),
                         (False, True, {"editar": False, "concluir": False, "criar_subtarefa": True}))
        self.assertEqual(self.sub(aberta, "Estande")["pode"], {"concluir": True, "editar_texto": True,
                                                               "editar_prazo": False})
        self.assertEqual(self.sub(aberta, "Material")["pode"], {"concluir": False, "editar_texto": False,
                                                                "editar_prazo": False})
        self.assertEqual([p["nome"] for p in aberta["participantes"]], ["Beto", "Caio"])  # sem quem criou
        self.assertEqual((aberta["criador"]["nome"], aberta["hora"], aberta["feitas"], aberta["total"]),
                         ("Ana", "14:00", 0, 3))
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
        # Beto cria uma para si, com o prazo da tarefa; para outra pessoa ou com outro prazo, não
        r = self.tarefas.nova_subtarefa(self.beto, t["id"], {"titulo": "Fotos"})
        fotos = self.sub(r, "Fotos")
        self.assertEqual((fotos["responsavel"]["id"], fotos["prazo"], fotos["hora"]), (self.beto, "2026-10-30", "14:00"))
        for dados in ({"titulo": "x", "responsavel": self.caio}, {"titulo": "x", "prazo": "2026-10-29"}):
            with self.subTest(dados), self.assertRaises(PermissionError):
                self.tarefas.nova_subtarefa(self.beto, t["id"], dados)
        with self.assertRaises(PermissionError):
            self.tarefas.nova_subtarefa(self.caio, t["id"], {"titulo": "Caio sem autonomia"})
        # a tarefa, só quem criou
        for chamada in (lambda u: self.editar(t, u, titulo="Outra"), lambda u: self.tarefas.excluir(u, t["id"]),
                        lambda u: self.tarefas.concluir(u, t["id"])):
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
        self.assertEqual((r["feitas"], r["total"], self.sub(r, "Material")["concluida_por"]["nome"]), (2, 3, "Ana"))
        self.tarefas.desfazer_subtarefa(self.caio, material)
        with self.assertRaises(ValueError):
            self.tarefas.desfazer_subtarefa(self.caio, material)  # não estava concluída
        # a tarefa concluída leva junto as abertas; reaberta, elas voltam
        r = self.tarefas.concluir(self.ana, t["id"])
        self.assertEqual((r["feita"], r["feitas"]), (True, 3))
        self.assertEqual([(s["feita"], s["pela_tarefa"]) for s in r["subtarefas"]],
                         [(True, False), (True, True), (True, True)])
        self.assertTrue(all(d["feita"] for x in self.mes(self.ana)["dias"] for d in x["tarefas"]))
        with self.assertRaises(ValueError):
            self.tarefas.concluir_subtarefa(self.caio, material)  # concluída: quem criou precisa reabrir
        with self.assertRaises(ValueError):
            self.tarefas.nova_subtarefa(self.ana, t["id"], {"titulo": "Mais uma"})
        r = self.tarefas.desfazer(self.ana, t["id"])
        self.assertEqual((r["feita"], r["feitas"]), (False, 1))
        with self.assertRaises(ValueError):
            self.tarefas.desfazer(self.ana, t["id"])

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
        self.assertEqual([(s["titulo"], s["feita"]) for s in r["subtarefas"]],
                         [("Estande grande", True), ("Som", False), ("Convites", False)])
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
        from psycopg.errors import CheckViolation, ForeignKeyViolation
        t = self.criar()
        with self.assertRaises(ForeignKeyViolation), self.banco.conexao() as con:
            con.execute("INSERT INTO agenda_subtarefas (tarefa, responsavel, titulo, prazo) "
                        "VALUES (%s, %s, 'x', '2026-10-30')", [t["id"], self.dani])  # não participa
        with self.assertRaises(ForeignKeyViolation), self.banco.conexao() as con:
            con.execute("DELETE FROM agenda_tarefa_pessoas WHERE tarefa = %s AND usuario = %s", [t["id"], self.caio])
        with self.assertRaises(CheckViolation), self.banco.conexao() as con:
            con.execute("UPDATE agenda_tarefas SET titulo = '  ' WHERE id = %s", [t["id"]])


if __name__ == "__main__":
    unittest.main()

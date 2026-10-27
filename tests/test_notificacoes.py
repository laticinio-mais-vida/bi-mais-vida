"""Notificações (bi/notificacoes.py e os avisos de bi/tarefas.py): quem recebe cada aviso, a lista do sino, marcar
como lida e os avisos de prazo, gerados uma vez só por item e por prazo.

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import unittest

from bi.notificacoes import Notificacoes, avisar
from bi.tarefas import Tarefas
from tests.apoio import BaseBanco

GESTAO = ["metas", "gestao"]


class TestNotificacoes(BaseBanco):
    """Ana cria a tarefa; Beto e Caio participam. O relógio anda (self.relogio)."""

    def setUp(self):
        super().setUp()
        self.relogio = {"agora": dt.datetime(2026, 10, 26, 9, 0)}
        self.tarefas = Tarefas(self.banco, agora=lambda: self.relogio["agora"])
        self.notificacoes = Notificacoes(self.banco)
        self.ana, self.beto, self.caio = (self.criar_usuario(n, paginas=GESTAO) for n in ("ana", "beto", "caio"))

    def criar(self) -> dict:
        """A feira: até 30/10 às 14:00; o Beto com o Estande (28/10) e o Material (29/10)."""
        return self.tarefas.criar(self.ana, {
            "titulo": "Feira", "prazo": "2026-10-30", "hora": "14:00",
            "participantes": [{"id": self.beto}, {"id": self.caio}],
            "subtarefas": [{"titulo": "Estande", "responsavel": self.beto, "prazo": "2026-10-28"},
                           {"titulo": "Material", "responsavel": self.beto, "prazo": "2026-10-29"}]})

    def textos(self, usuario: int) -> list[tuple[str, str]]:
        return [(n["tipo"], n["texto"]) for n in self.notificacoes.listar(usuario)["itens"]]

    def limpar(self) -> None:
        with self.banco.conexao() as con:
            con.execute("DELETE FROM notificacoes")

    @staticmethod
    def sub(t: dict, titulo: str) -> int:
        return next(s["id"] for s in t["subtarefas"] if s["titulo"] == titulo)

    def test_o_sino(self):
        with self.banco.conexao() as con:
            self.assertEqual(avisar(con, [self.ana, self.beto], "concluida", "x", self.ana, None), 1)  # o autor, não
            chave = "vence:t1:2026-10-30:"
            avisar(con, [self.beto], "vence_em_breve", "y", None, None, chave=chave)
            self.assertEqual(avisar(con, [self.beto], "vence_em_breve", "y", None, None, chave=chave), 0)  # uma vez só
            with self.assertRaises(ValueError):
                avisar(con, [self.beto], "parabens", "z", None, None)
        lista = self.notificacoes.listar(self.beto)
        self.assertEqual((lista["nao_lidas"], [n["texto"] for n in lista["itens"]]), (2, ["y", "x"]))
        self.assertEqual(lista["itens"][1]["autor"], {"id": self.ana, "nome": "Ana"})
        ids = [n["id"] for n in lista["itens"]]
        self.assertEqual(self.notificacoes.marcar_lidas(self.ana, ids), 0)  # as do Beto não são da Ana
        self.assertEqual(self.notificacoes.contar(self.beto), 2)
        self.assertEqual(self.notificacoes.marcar_lidas(self.beto, ids[:1]), 1)
        self.assertEqual(self.notificacoes.marcar_lidas(self.beto, todas=True), 0)
        self.assertTrue(all(n["lida"] for n in self.notificacoes.listar(self.beto)["itens"]))
        with self.assertRaises(ValueError):
            self.notificacoes.marcar_lidas(self.beto, ["um"])

    def test_avisos_das_acoes(self):
        t = self.criar()
        self.assertEqual(self.textos(self.beto), [("incluido", "Ana incluiu você na tarefa “Feira” (prazo 30/10 às "
                                                               "14:00), com 2 subtarefas para você")])
        self.assertEqual(self.textos(self.caio), [("incluido", "Ana incluiu você na tarefa “Feira” (prazo 30/10 às "
                                                               "14:00)")])
        self.assertEqual(self.textos(self.ana), [])  # ninguém é avisado do que fez
        self.limpar()
        # editar: a Dani entra; o prazo da tarefa muda; o Estande passa para o Caio; o Material muda de prazo; o Som
        # é novo, do Beto
        dani = self.criar_usuario("dani", paginas=GESTAO)
        t = self.tarefas.editar(self.ana, t["id"], {
            "titulo": "Feira", "prazo": "2026-10-31", "hora": None,
            "participantes": [{"id": self.beto}, {"id": self.caio}, {"id": dani}],
            "subtarefas": [{"id": self.sub(t, "Estande"), "titulo": "Estande", "responsavel": self.caio,
                            "prazo": "2026-10-28"},
                           {"id": self.sub(t, "Material"), "titulo": "Material", "responsavel": self.beto,
                            "prazo": "2026-10-30"},
                           {"titulo": "Som", "responsavel": self.beto, "prazo": "2026-10-29"},
                           {"titulo": "Fotos", "responsavel": dani}]}, t["versao"])
        self.assertEqual(self.textos(dani), [("incluido", "Ana incluiu você na tarefa “Feira” (prazo 31/10), com 1 "
                                                          "subtarefa para você")])
        self.assertEqual(sorted(self.textos(self.beto)), [
            ("prazo_mudou", "Ana mudou o prazo da tarefa “Feira” para 31/10"),
            ("prazo_mudou", "Ana mudou o prazo de “Material” para 30/10"),
            ("subtarefa_nova", "Ana criou a subtarefa “Som” para você (até 29/10)")])
        self.assertEqual(sorted(self.textos(self.caio)), [
            ("prazo_mudou", "Ana mudou o prazo da tarefa “Feira” para 31/10"),
            ("subtarefa_nova", "Ana passou a subtarefa “Estande” para você (até 28/10)")])
        self.limpar()
        # pela janela: uma subtarefa nova e, depois, o prazo dela mudado
        t = self.tarefas.nova_subtarefa(self.ana, t["id"], {"titulo": "Banner", "responsavel": self.caio,
                                                            "prazo": "2026-10-30"})
        self.tarefas.editar_subtarefa(self.ana, self.sub(t, "Banner"), {"prazo": "2026-10-29"})
        self.assertEqual(self.textos(self.caio), [("prazo_mudou", "Ana mudou o prazo de “Banner” para 29/10"),
                                                  ("subtarefa_nova", "Ana criou a subtarefa “Banner” para você (até "
                                                                     "30/10)")])
        self.limpar()
        # concluir: a subtarefa avisa quem criou (uma vez só); a tarefa, todos dela, menos quem concluiu
        self.tarefas.concluir_subtarefa(self.beto, self.sub(t, "Som"))
        self.tarefas.concluir_subtarefa(self.beto, self.sub(t, "Som"))
        self.assertEqual(self.textos(self.ana), [("concluida", "Beto concluiu a subtarefa “Som” (tarefa “Feira”)")])
        self.tarefas.concluir(self.caio, t["id"])
        self.assertEqual(self.textos(self.ana)[0], ("concluida", "Caio concluiu a tarefa “Feira”"))
        self.assertEqual((self.textos(self.beto), self.textos(dani), self.textos(self.caio)),
                         ([("concluida", "Caio concluiu a tarefa “Feira”")],
                          [("concluida", "Caio concluiu a tarefa “Feira”")], []))
        self.tarefas.excluir(self.ana, t["id"])  # excluída a tarefa, os avisos dela saem
        self.assertEqual(self.notificacoes.listar(self.beto)["itens"], [])

    def test_justificativa(self):
        self.relogio["agora"] = dt.datetime(2026, 10, 29, 9, 0)  # o Estande (28/10) venceu
        t = self.criar()
        self.limpar()
        self.tarefas.justificar_subtarefa(self.beto, self.sub(t, "Estande"), "Choveu muito. " * 15, concluir=True)
        (tipo1, texto1), (tipo2, texto2) = self.textos(self.ana)
        self.assertEqual((tipo1, texto1), ("concluida", "Beto concluiu a subtarefa “Estande” (tarefa “Feira”)"))
        self.assertEqual(tipo2, "justificativa")
        self.assertTrue(texto2.startswith("Beto justificou o atraso de “Estande”: “Choveu muito.") and
                        texto2.endswith("…”") and len(texto2) < 200)

    def test_avisos_de_prazo(self):
        t = self.criar()
        self.limpar()
        self.relogio["agora"] = dt.datetime(2026, 10, 27, 8, 0)  # véspera do Estande
        self.tarefas.gerar_avisos(self.beto)
        self.tarefas.gerar_avisos(self.beto)  # de novo: não repete
        self.assertEqual(self.textos(self.beto), [("vence_em_breve", "“Estande” vence amanhã (28/10)")])
        self.relogio["agora"] = dt.datetime(2026, 10, 28, 8, 0)  # no dia do Estande (já avisado); véspera do Material
        self.tarefas.gerar_avisos(self.beto)
        self.assertEqual(self.textos(self.beto), [("vence_em_breve", "“Material” vence amanhã (29/10)"),
                                                  ("vence_em_breve", "“Estande” vence amanhã (28/10)")])
        # a tarefa avisa todos dela, inclusive quem criou; quem criou recebe também as subtarefas vencidas dos outros
        self.relogio["agora"] = dt.datetime(2026, 10, 30, 13, 0)
        self.tarefas.gerar_avisos(self.ana)
        self.assertEqual(sorted(self.textos(self.ana)), [
            ("vence_em_breve", "“Feira” vence hoje às 14:00"),
            ("venceu", "A subtarefa “Estande”, de Beto, venceu sem ser concluída (28/10)"),
            ("venceu", "A subtarefa “Material”, de Beto, venceu sem ser concluída (29/10)")])
        # prorrogado, o prazo novo avisa de novo
        t = self.tarefas.obter(self.ana, t["id"])
        self.tarefas.editar(self.ana, t["id"], {
            "titulo": "Feira", "prazo": "2026-10-31", "participantes": [{"id": self.beto}, {"id": self.caio}],
            "subtarefas": [{"id": self.sub(t, "Estande"), "titulo": "Estande", "responsavel": self.beto,
                            "prazo": "2026-10-31"}]}, t["versao"])
        self.tarefas.gerar_avisos(self.beto)
        self.assertIn(("vence_em_breve", "“Estande” vence amanhã (31/10)"), self.textos(self.beto))
        # o "venceu" de mais de 7 dias não avisa (nem depois de a lista ser limpa); os de mais de 90 dias saem
        self.relogio["agora"] = dt.datetime(2026, 11, 10, 9, 0)
        self.limpar()
        with self.banco.conexao() as con:
            con.execute("INSERT INTO notificacoes (usuario, tipo, texto, criada_em) "
                        "VALUES (%s, 'concluida', 'antiga', now() - interval '91 days')", [self.ana])
        self.tarefas.gerar_avisos(self.ana)
        self.assertEqual(self.textos(self.ana), [])


if __name__ == "__main__":
    unittest.main()

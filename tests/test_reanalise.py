"""Reanálises de crédito (bi/reanalise.py): registrar (o retrato calculado no servidor, as conferências, a chave que não
grava duas vezes, a extração que mudou entre analisar e registrar), listar com o cadastro de hoje, excluir (quem pode, e
a linha fica guardada), o painel do PC que só avisa e o que o Assistente lê (por cliente, parecidas e o resumo).

Usa o cache sintético de tests/apoio.py (hoje = 01/10/2026) e o banco de teste (BI_TESTE_POSTGRES).
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from bi import assistente as modulo_assistente
from bi.assistente import Ferramentas
from bi.conversas import NaoEncontrada, novo_id
from bi.credito import Credito, perfil_do_retrato
from bi.reanalise import AVISO_PC, Reanalises, decisao, distancia
from tests.apoio import NOMES, BaseBanco, criar_assistente, criar_calc


class Base(BaseBanco):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.calc = criar_calc(self.pasta)
        self.credito = Credito(self.calc.cache, lambda: dict(NOMES))
        self.reanalises = Reanalises(self.banco, self.credito, ativo=True)
        self.admin = self.usuario("chefe", "admin")
        self.ana = self.usuario("ana")
        self.bia = self.usuario("bia")

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()
        super().tearDown()

    def usuario(self, login: str, papel: str = "visualizador") -> dict:
        id_ = self.criar_usuario(login, papel, None if papel == "admin" else ["credito"])
        return {"id": id_, "login": login, "nome": login.title(), "papel": papel}

    @staticmethod
    def dados(**mudar) -> dict:
        """O que a página manda: o pedido analisado, o liberado, o prazo, a justificativa e a extração que ela mostrava."""
        return {"chave": novo_id(), "cliente": 1, "pedido": 6000, "liberado": 5000, "prazo": "07 DIAS",
                "justificativa": "Cliente antigo; o vendedor pediu prazo menor.", "dados_ate": "2026-10-01T08:00:00",
                **mudar}


class TestRegistrar(Base):
    def test_grava_o_retrato_calculado_no_servidor(self):
        r = self.reanalises.registrar(self.ana, self.dados(liberado="5000", justificativa="  Cliente antigo; paga.  "))
        self.assertFalse(r["ja_existia"])
        with self.banco.conexao() as con:
            linha = con.execute(
                "SELECT id, id_cliente, cliente, limite_antes, prazo_antes, limite_pedido, limite_liberado, "
                "prazo_liberado, justificativa, parecer, parecer_liberado, limite_sugerido, dados_ate, feita_por, "
                "feita_por_nome, excluida_em, retrato FROM credito_reanalises").fetchone()
        self.assertEqual(linha[:-1], (
            r["id"], 1, "MERCADO DO JOAO", Decimal("5000.00"), "28 DIAS", Decimal("6000.00"), Decimal("5000.00"),
            "07 DIAS", "Cliente antigo; paga.", "nao_indicado", "nao_indicado", None,
            dt.datetime(2026, 10, 1, 8, 0), self.ana["id"], "Ana", None))
        self.assertEqual(linha[-1], self.credito.retrato(1, 6000, 5000))
        # a resposta já traz a lista nova do cliente
        x = r["reanalises"][0]
        self.assertEqual((len(r["reanalises"]), x["id"], x["feita_por"], x["pode_excluir"], x["dados_ate"]),
                         (1, r["id"], "Ana", True, "2026-10-01T08:00:00"))
        self.assertEqual(x["decisao"], {"limite": "manteve", "prazo": "diminuiu", "variacao_limite": 0.0})
        self.assertEqual((x["numeros"]["pontualidade_12m"], x["numeros"]["em_aberto"]), (0.5, 1150.0))
        # registrada com os dados de agora: o ERP (28 DIAS) aparece na próxima atualização
        self.assertEqual(x["erp"], {"situacao": "aguardando", "limite": 5000.0, "prazo": "28 DIAS"})

    def test_conferencias(self):
        casos = [
            ({"justificativa": "curta    "}, "justificativa"), ({"justificativa": "x" * 2001}, "passou de 2000"),
            ({"liberado": -1}, "limite liberado"), ({"liberado": "nan"}, "limite liberado"),
            ({"liberado": None}, "limite liberado"), ({"liberado": True}, "limite liberado"),
            ({"liberado": 1e9}, "limite liberado"), ({"pedido": 0}, "analise o limite"),
            ({"pedido": "abc"}, "analise o limite"), ({"prazo": "99 DIAS"}, "prazo"), ({"prazo": None}, "prazo"),
            ({"cliente": 999}, "cliente não encontrado"), ({"cliente": "x"}, "escolha um cliente"),
            ({"chave": "nao-e-uuid"}, "expirou"), ({"dados_ate": "2026-09-30T08:00:00"}, "foram atualizados"),
            ({"dados_ate": None}, "foram atualizados"),
        ]
        for mudar, texto in casos:
            with self.assertRaises(ValueError, msg=mudar) as e:
                self.reanalises.registrar(self.ana, self.dados(**mudar))
            self.assertIn(texto, str(e.exception), mudar)
        self.assertEqual(self.contar("credito_reanalises"), 0)

    def test_cortar_o_credito(self):
        r = self.reanalises.registrar(self.ana, self.dados(liberado=0, prazo="A VISTA"))
        x = r["reanalises"][0]
        self.assertEqual((x["limite_liberado"], x["parecer_liberado"], x["decisao"]["limite"], x["decisao"]["prazo"]),
                         (0.0, None, "cortou", "diminuiu"))

    def test_a_mesma_chave_grava_uma_vez(self):
        d = self.dados()
        a = self.reanalises.registrar(self.ana, d)
        b = self.reanalises.registrar(self.ana, d)  # clique duplo, ou a rede repetiu o envio
        self.assertEqual((a["ja_existia"], b["ja_existia"], b["id"]), (False, True, a["id"]))
        self.assertEqual(self.contar("credito_reanalises"), 1)
        self.assertNotEqual(a["chave"], b["chave"])  # cada lista traz a chave do próximo registro
        with self.assertRaises(ValueError):  # a chave de outra pessoa
            self.reanalises.registrar(self.bia, d)

    def test_dados_de_credito_ainda_nao_chegaram(self):
        self.calc.cache.sem_credito = True
        with self.assertRaises(RuntimeError):
            self.reanalises.registrar(self.ana, self.dados())
        with self.assertRaises(RuntimeError):
            self.reanalises.listar(1, self.ana)


class TestListarEExcluir(Base):
    def test_da_mais_nova_para_a_mais_antiga_e_quem_exclui(self):
        primeira = self.reanalises.registrar(self.ana, self.dados(liberado=5500))
        segunda = self.reanalises.registrar(self.bia, self.dados(liberado=0, justificativa="Inadimplente: cortei."))
        lista = self.reanalises.listar(1, self.ana)
        self.assertEqual([x["id"] for x in lista["reanalises"]], [segunda["id"], primeira["id"]])
        self.assertEqual([x["pode_excluir"] for x in lista["reanalises"]], [False, True])
        self.assertEqual([x["pode_excluir"] for x in self.reanalises.listar(1, self.admin)["reanalises"]], [True, True])
        self.assertNotIn("erp", lista["reanalises"][1])  # só a última é comparada com o cadastro
        self.assertEqual((lista["ativo"], lista["prazos"], lista["dados_ate"]),
                         (True, ["A VISTA", "07 DIAS", "28 DIAS"], "2026-10-01T08:00:00"))
        self.assertEqual(lista["cadastro"], {"id": 1, "nome": "MERCADO DO JOAO", "limite": 5000.0, "prazo": "28 DIAS"})
        self.assertEqual(self.reanalises.listar(2, self.ana)["reanalises"], [])

        with self.assertRaises(PermissionError):
            self.reanalises.excluir(self.ana, segunda["id"])  # de outra pessoa
        r = self.reanalises.excluir(self.admin, segunda["id"])
        self.assertEqual([x["id"] for x in r["reanalises"]], [primeira["id"]])
        with self.assertRaises(NaoEncontrada):
            self.reanalises.excluir(self.admin, segunda["id"])  # já saiu
        self.reanalises.excluir(self.ana, primeira["id"])  # a própria
        self.assertEqual(self.reanalises.listar(1, self.ana)["reanalises"], [])
        # as excluídas ficam guardadas, com quem excluiu
        self.assertEqual(self.contar("credito_reanalises", "excluida_em IS NOT NULL"), 2)
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT excluida_por_nome FROM credito_reanalises WHERE id = %s",
                                         [segunda["id"]]).fetchone()[0], "Chefe")
        for id_ in ("x", None, 999):
            with self.assertRaises(NaoEncontrada):
                self.reanalises.excluir(self.admin, id_)

    def test_cadastro_do_erp_contra_a_ultima(self):
        self.reanalises.registrar(self.ana, self.dados(liberado=5000, prazo="28 DIAS"))
        x = self.reanalises.listar(1, self.ana)["reanalises"][0]
        self.assertEqual(x["erp"]["situacao"], "aplicado")  # o mesmo limite e prazo de hoje
        self.reanalises.registrar(self.ana, self.dados(liberado=8000))
        self.calc.cache.info["extraido_em"] = "2026-10-02T08:00:00"  # chegou uma extração nova
        x = self.reanalises.listar(1, self.ana)["reanalises"][0]
        self.assertEqual(x["erp"], {"situacao": "diferente", "limite": 5000.0, "prazo": "28 DIAS"})

    def test_usuario_excluido_continua_com_o_nome(self):
        self.reanalises.registrar(self.ana, self.dados())
        with self.banco.conexao() as con:
            con.execute("DELETE FROM usuarios WHERE id = %s", [self.ana["id"]])
        x = self.reanalises.listar(1, self.admin)["reanalises"][0]
        self.assertEqual((x["feita_por"], x["pode_excluir"]), ("Ana", True))
        self.assertEqual(self.contar("credito_reanalises", "feita_por IS NULL"), 1)

    def test_no_pc_so_avisa(self):
        pc = Reanalises(self.banco, self.credito, ativo=False)
        self.assertEqual(pc.listar(1, self.ana), {"ativo": False, "aviso": AVISO_PC, "reanalises": []})
        for conta in (lambda: pc.registrar(self.ana, self.dados()), lambda: pc.excluir(self.ana, 1),
                      lambda: pc.para_ia(1, False)):
            with self.assertRaises(ValueError):
                conta()
        self.assertEqual(self.contar("credito_reanalises"), 0)


class TestDecisao(unittest.TestCase):
    def test_tipos(self):
        self.assertEqual(decisao(0, 1000, None, "07 DIAS"), {"limite": "primeiro_limite", "prazo": "definiu",
                                                             "variacao_limite": None})
        self.assertEqual(decisao(5000, 0, "28 DIAS", "A VISTA")["limite"], "cortou")
        self.assertEqual(decisao(5000, 6000, "07 DIAS", "07 E 14 DIAS"),
                         {"limite": "aumentou", "prazo": "aumentou", "variacao_limite": 0.19999999999999996})
        self.assertEqual(decisao(5000, 4000, "7 DIAS", "07 DIAS")["prazo"], "mudou")  # os mesmos dias, outro nome
        self.assertEqual(decisao(0, 0, "A VISTA", "A VISTA")["limite"], "manteve")

    def test_distancia(self):
        perto = {"pontualidade_12m": 0.95, "compras_mes_12m": 3000, "maior_saldo_12m": 2000, "meses_cliente": 60,
                 "inadimplencia": 0, "pedido_vezes_maior_saldo": 3}
        self.assertEqual(distancia(perto, dict(perto)), 0)
        # 10 vezes mais compras por mês pesa igual em qualquer faixa (uns 2)
        dez = distancia(perto, {**perto, "compras_mes_12m": 30000})
        self.assertAlmostEqual(dez, 2, places=2)
        self.assertAlmostEqual(dez, distancia({**perto, "compras_mes_12m": 300}, perto), places=2)
        # um inadimplente e outro não pesa mais que 3 vezes mais compras
        self.assertGreater(distancia(perto, {**perto, "inadimplencia": 100}),
                           distancia(perto, {**perto, "compras_mes_12m": 9000}))
        # o pedido ÷ maior saldo só conta quando os dois têm; o resto que falta em um só conta 1
        self.assertEqual(distancia(perto, {**perto, "pedido_vezes_maior_saldo": None}), 0)
        self.assertEqual(distancia(perto, {**perto, "pontualidade_12m": None}), 1)
        # acima de 10 anos de cliente, tanto faz
        self.assertEqual(distancia({**perto, "meses_cliente": 120}, {**perto, "meses_cliente": 300}), 0)
        self.assertAlmostEqual(distancia(perto, {**perto, "meses_cliente": 12}), 2)


class TestAssistente(Base):
    def registrar_varios(self):
        """Uma reanálise do cliente 1 (inadimplente), uma do 2 (inadimplente, sem nada quitado) e uma do 4 (paga em dia)."""
        um = self.reanalises.registrar(self.ana, self.dados())
        dois = self.reanalises.registrar(self.ana, self.dados(cliente=2, pedido=3000, liberado=2500, prazo="A VISTA",
                                                              justificativa="Deve mais que o limite; só à vista."))
        quatro = self.reanalises.registrar(self.bia, self.dados(cliente=4, pedido=1500, liberado=1500,
                                                                justificativa="Cliente novo, pagou adiantado."))
        return um["id"], dois["id"], quatro["id"]

    def test_por_cliente_todas_e_por_mes(self):
        um, dois, quatro = self.registrar_varios()
        r = self.reanalises.para_ia(1, False)
        self.assertEqual((r["total"], r["mostrando"], len(r["reanalises"])), (1, 1, 1))
        x = r["reanalises"][0]
        self.assertEqual((x["cliente"]["id"], x["quem"], x["limite"], x["prazo"]),
                         (1, "Ana", {"antes": 5000.0, "pedido": 6000.0, "liberado": 5000.0, "sugerido_pela_regra": None},
                          {"antes": "28 DIAS", "liberado": "07 DIAS"}))
        self.assertEqual(x["parecer_da_regra"], {"para_o_pedido": "Não indicado", "para_o_liberado": "Não indicado"})
        self.assertEqual((x["numeros_no_dia"]["pontualidade_12m"], x["cliente"]["segmento"]), (0.5, "MERCADO"))
        self.assertIn("titulos_emitidos", x["depois"])
        self.assertNotIn("distancia", x)
        todas = self.reanalises.para_ia(0, False)
        self.assertEqual([y["cliente"]["id"] for y in todas["reanalises"]], [4, 2, 1])
        self.assertEqual(todas["resumo"], {"reanalises": 3, "por_parecer_da_regra": {
            "Não indicado": {"reanalises": 2, "liberou_mais_que_o_pedido": 0, "liberou_o_pedido": 0,
                             "liberou_menos_que_o_pedido": 2},
            "Indicado com ressalvas": {"reanalises": 1, "liberou_mais_que_o_pedido": 0, "liberou_o_pedido": 1,
                                       "liberou_menos_que_o_pedido": 0}}})
        self.assertEqual(self.reanalises.para_ia(0, False, mes=dt.date.today().strftime("%Y-%m"))["total"], 3)
        self.assertEqual(self.reanalises.para_ia(0, False, mes="2020-01")["total"], 0)
        with self.assertRaises(ValueError):
            self.reanalises.para_ia(0, False, mes="outubro")
        self.reanalises.excluir(self.ana, um)
        self.assertEqual(self.reanalises.para_ia(1, False)["total"], 0)  # a excluída não vai para a IA

    def test_parecidas_sem_o_proprio_cliente(self):
        self.registrar_varios()
        r = self.reanalises.para_ia(1, True, 6000)
        self.assertEqual([x["cliente"]["id"] for x in r["reanalises"]], [2, 4])  # inadimplente como ele, primeiro
        alvo = self.credito.perfil(1, 6000)
        with self.banco.conexao() as con:
            retratos = dict(con.execute("SELECT id_cliente, retrato FROM credito_reanalises").fetchall())
        self.assertEqual([x["distancia"] for x in r["reanalises"]],
                         [round(distancia(alvo, perfil_do_retrato(retratos[c])), 2) for c in (2, 4)])
        self.assertEqual((r["comparado_com"]["cliente"]["id"], r["comparado_com"]["novo_limite"]), (1, 6000))
        self.assertEqual(r["resumo"]["reanalises"], 2)
        with self.assertRaises(ValueError):
            self.reanalises.para_ia(0, True)  # parecidas com quem?

    def test_ferramenta(self):
        self.registrar_varios()
        a = criar_assistente(self.pasta, self.calc)
        sem = Ferramentas(a.recorte(None), self.calc, a.cfg, None)
        _, p = sem.executar("reanalises_credito", {"id_cliente": 1, "parecidos": False})
        self.assertIn("Reavaliação de Crédito", p["erro"])
        com = Ferramentas(a.recorte(None, credito=True), self.calc, a.cfg, None, credito=a.credito,
                          reanalises=self.reanalises)
        r, p = com.executar("reanalises_credito", {"id_cliente": 0, "parecidos": False})
        self.assertIsNone(p["erro"])
        self.assertEqual((r["mostrando"], p["linhas"], p["amostra"][0][1]), (3, 3, "MERCEARIA DO EDIR"))
        with mock.patch.object(modulo_assistente, "MAX_RESULTADO", 2000):  # o resultado tem limite de tamanho
            r, _ = com.executar("reanalises_credito", {"id_cliente": 0, "parecidos": False})
        self.assertLess(r["mostrando"], 3)
        self.assertEqual((r["total"], r["resumo"]["reanalises"]), (3, 3))
        self.assertIn("limite de tamanho", r["aviso"])
        _, p = com.executar("reanalises_credito", {"id_cliente": 0, "parecidos": True})
        self.assertIn("informe o cliente", p["erro"])
        # a ferramenta não é strict: os argumentos podem vir como texto
        r, p = com.executar("reanalises_credito", {"id_cliente": "1", "parecidos": "false", "mes": ""})
        self.assertEqual((p["erro"], [x["cliente"]["id"] for x in r["reanalises"]]), (None, [1]))
        r, p = com.executar("reanalises_credito", {"id_cliente": "1", "parecidos": "true", "novo_limite": "6000"})
        self.assertEqual((p["erro"], [x["cliente"]["id"] for x in r["reanalises"]]), (None, [2, 4]))
        _, p = com.executar("reanalises_credito", {"id_cliente": "Mercado", "parecidos": False})
        self.assertIn("código de cliente", p["erro"])

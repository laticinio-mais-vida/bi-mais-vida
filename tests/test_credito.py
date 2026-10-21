"""Reavaliação de Crédito (bi/credito.py): os cartões da página do Power BI contra as contas feitas à mão nos títulos
de tests/apoio.py (TITULOS e LIMITES), com as diferenças aprovadas (pontualidade em fração, restante sem o período,
limite só com cliente). E os dados de crédito no Assistente, só para quem tem a página.

Rodar na raiz do projeto: python -m unittest discover -s tests
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import duckdb

from bi import credito as modulo
from bi.assistente import Ferramentas
from bi.credito import Credito
from tests.apoio import BA, EDIR, ES, NOMES, criar_assistente, criar_calc

D = dt.date


class Base(unittest.TestCase):
    credito_no_cache = True

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.calc = criar_calc(self.pasta, credito=self.credito_no_cache)
        self.credito = Credito(self.calc.cache, lambda: dict(NOMES))

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()


class TestCartoes(Base):
    def test_cliente_sem_periodo(self):
        d = self.credito.calcular(1)
        self.assertEqual(d["hoje"], D(2026, 10, 1))  # o dia da extração
        k = d["cartoes"]
        self.assertEqual((k["valor"], k["quantidade"]), (4000.0, 6))
        self.assertAlmostEqual(k["ticket"], 4000 / 6)
        # quitados 101, 102 e 106; só o 102 (8 dias) passou dos 7 dias
        self.assertEqual((k["quitados"], k["quitados_atrasados"]), (3, 1))
        self.assertAlmostEqual(k["pontualidade"], 2 / 3)
        # em aberto vencido antes de 24/09: só o 103 (o 104 vence em 24/09, 7 dias)
        self.assertEqual(k["inadimplencia"], 1300.0)
        c = d["cliente"]
        self.assertEqual((c["nome"], c["carteira"], c["prazo"], c["limite"]), ("MERCADO DO JOAO", "Rubens", "28 DIAS", 5000.0))
        self.assertEqual((c["em_aberto"], c["restante"]), (1900.0, 3100.0))
        self.assertAlmostEqual(c["usado"], 0.38)

    def test_mes_sem_ano_vale_para_todos_os_anos(self):
        k = self.credito.calcular(1, mes=9)["cartoes"]
        self.assertEqual((k["valor"], k["quantidade"]), (2500.0, 4))  # 103, 104, 105 e o 106 de setembro de 2025
        self.assertEqual(k["pontualidade"], 1.0)  # o 106 foi pago 7 dias depois: ainda pontual
        k = self.credito.calcular(1, mes=9, ano=2026)["cartoes"]
        self.assertEqual((k["valor"], k["quantidade"], k["pontualidade"]), (1900.0, 3, None))
        self.assertEqual(self.credito.calcular(1, ano=2025)["cartoes"]["valor"], 600.0)

    def test_restante_ignora_o_periodo_e_o_vendedor(self):
        d = self.credito.calcular(1, mes=8, ano=2026, vendedor=BA)
        self.assertEqual(d["cartoes"]["quantidade"], 0)
        self.assertEqual((d["cliente"]["em_aberto"], d["cliente"]["restante"]), (1900.0, 3100.0))

    def test_vendedor_do_titulo(self):
        d = self.credito.calcular(1, vendedor=BA)
        self.assertEqual((d["cartoes"]["valor"], [t["id"] for t in d["titulos"]["linhas"]]), (200.0, [104]))
        self.assertEqual(self.credito.calcular(vendedor=EDIR)["cartoes"]["valor"], 710.0)

    def test_passou_do_limite_e_sem_limite(self):
        c = self.credito.calcular(2)["cliente"]
        self.assertEqual((c["restante"], c["prazo"]), (-500.0, "A VISTA"))
        self.assertAlmostEqual(c["usado"], 1.25)
        c = self.credito.calcular(4)["cliente"]
        self.assertEqual((c["limite"], c["usado"], c["prazo"], c["restante"]), (0.0, None, None, 0.0))
        c = self.credito.calcular(3)  # cliente sem título nenhum
        self.assertEqual((c["cliente"]["restante"], c["cartoes"]["quantidade"], c["cartoes"]["ticket"]), (1000.0, 0, None))

    def test_sem_cliente_soma_o_filtro_sem_limite(self):
        d = self.credito.calcular()
        self.assertIsNone(d["cliente"])
        self.assertEqual((d["cartoes"]["valor"], d["cartoes"]["quantidade"]), (7210.0, 9))
        self.assertEqual(d["cartoes"]["inadimplencia"], 3800.0)  # 103 + 201

    def test_permitidos_do_assistente(self):
        d = self.credito.calcular(1, permitidos={BA})
        self.assertEqual(d["cartoes"]["valor"], 200.0)
        self.assertEqual(d["cliente"]["restante"], 3100.0)  # o limite é do cliente inteiro
        self.assertEqual([v["id"] for v in d["opcoes"]["vendedores"]], [BA])
        d = self.credito.calcular(1, permitidos=set())
        self.assertEqual((d["cartoes"]["quantidade"], d["cartoes"]["ticket"], d["titulos"]["linhas"]), (0, None, []))


class TestTitulos(Base):
    def test_dias_e_situacao(self):
        linhas = {t["id"]: t for t in self.credito.calcular(1)["titulos"]["linhas"]}
        esperado = {101: (1, "quitado"), 102: (8, "quitado_atraso"), 103: (8, "inadimplente"), 104: (7, "vencido"),
                    105: (-25, "a_vencer"), 106: (7, "quitado")}
        self.assertEqual({i: (t["dias_atraso"], t["situacao"]) for i, t in linhas.items()}, esperado)
        self.assertEqual(linhas[104]["vendedor"], "Thais")

    def test_ordem_e_limite_de_linhas(self):
        d = self.credito.calcular(1)
        self.assertEqual([t["id"] for t in d["titulos"]["linhas"]], [105, 104, 103, 102, 101, 106])
        with mock.patch.object(modulo, "MAX_TITULOS", 2):
            t = self.credito.calcular()["titulos"]
        self.assertEqual((t["total"], t["mostrando"], t["linhas"][0]["id"]), (9, 2, 402))  # a data errada vem antes

    def test_opcoes(self):
        op = self.credito.calcular()["opcoes"]
        self.assertEqual([v["nome"] for v in op["vendedores"]], ["Edir", "Rubens", "Thais"])
        self.assertEqual(op["anos"], [2026, 2025])  # o ano 7190 (data errada) não vira opção

    def test_parametros_invalidos(self):
        for args in ({"mes": 13}, {"mes": 0}, {"ano": 7190}, {"cliente": 999}):
            with self.assertRaises(ValueError, msg=args):
                self.credito.calcular(**args)


class TestBusca(Base):
    def test_busca_por_nome_e_codigo(self):
        self.assertEqual([c["id"] for c in self.credito.buscar("merc")], [1, 4])
        self.assertEqual([c["id"] for c in self.credito.buscar("Açougue")], [3])  # sem acento nem caixa
        self.assertEqual(self.credito.buscar("4")[0]["id"], 4)
        self.assertEqual([c["id"] for c in self.credito.buscar("o")], [1, 4, 3])  # quem tem títulos antes
        self.assertEqual(self.credito.buscar("  "), [])
        c = self.credito.buscar("joao")[0]
        self.assertEqual((c["nome"], c["carteira"], c["titulos"]), ("MERCADO DO JOAO", "Rubens", 6))


class TestSemCredito(Base):
    credito_no_cache = False

    def test_cache_sem_as_tabelas(self):
        self.assertTrue(self.calc.cache.sem_credito)
        with self.assertRaises(RuntimeError) as e:
            self.credito.calcular(1)
        self.assertIn("ainda não chegaram", str(e.exception))
        self.calc.cache.info["credito_erro"] = "Table unknown CONTASRECEBER"
        with self.assertRaises(RuntimeError) as e:
            self.credito.buscar("merc")
        self.assertIn("não deu para ler", str(e.exception))

    def test_assistente_com_credito_sem_os_dados(self):
        a = criar_assistente(self.pasta, self.calc)
        c = a.recorte(None, credito=True).cursor()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM titulos_receber").fetchone()[0], 0)
        self.assertIsNone(c.execute("SELECT limite_credito FROM clientes WHERE id_cliente = 1").fetchone()[0])


class TestAssistente(Base):
    def test_sem_a_pagina_nao_existe(self):
        a = criar_assistente(self.pasta, self.calc)
        c = a.recorte(None).cursor()
        with self.assertRaises(duckdb.CatalogException):
            c.execute("SELECT * FROM titulos_receber")
        colunas = {r[0] for r in c.execute("DESCRIBE clientes").fetchall()}
        self.assertFalse({"limite_credito", "prazo"} & colunas)
        f = Ferramentas(a.recorte(None), self.calc, a.cfg, None)
        r, p = f.executar("credito_cliente", {"id_cliente": 1})
        self.assertIn("Reavaliação de Crédito", p["erro"])

    def test_com_a_pagina(self):
        a = criar_assistente(self.pasta, self.calc)
        r = a.recorte(None, credito=True)
        self.assertIsNot(r, a.recorte(None))  # recortes diferentes com e sem crédito
        c = r.cursor()
        self.assertEqual(c.execute("SELECT limite_credito, prazo FROM clientes WHERE id_cliente = 1").fetchone(),
                         (5000.0, "28 DIAS"))
        linhas = dict(c.execute("SELECT id_titulo, situacao FROM titulos_receber WHERE id_cliente = 1").fetchall())
        self.assertEqual(linhas, {101: "quitado", 102: "quitado com atraso", 103: "inadimplente", 104: "vencido",
                                  105: "a vencer", 106: "quitado"})
        self.assertEqual(c.execute("SELECT SUM(valor) FROM titulos_receber WHERE NOT quitado AND situacao = "
                                   "'inadimplente'").fetchone()[0], 3800.0)
        f = Ferramentas(r, self.calc, a.cfg, None, credito=a.credito)
        res, p = f.executar("credito_cliente", {"id_cliente": 1, "mes": 9})
        self.assertIsNone(p["erro"])
        pagina = self.credito.calcular(1, mes=9)
        self.assertEqual(res["compras"]["valor"], pagina["cartoes"]["valor"])
        self.assertEqual(res["cliente"]["limite_restante"], pagina["cliente"]["restante"])
        self.assertEqual([t["titulo"] for t in res["titulos_em_aberto"]], [105, 104, 103])

    def test_acesso_restrito_so_ve_os_titulos_dos_seus(self):
        a = criar_assistente(self.pasta, self.calc)
        ids = a.ids_do_escopo(None, {"BA"})
        r = a.recorte(ids, credito=True)
        vistos = {x[0] for x in r.cursor().execute("SELECT DISTINCT id_vendedor FROM titulos_receber").fetchall()}
        self.assertEqual(vistos, {BA})
        nomes = dict(r.cursor().execute("SELECT id_titulo, cliente FROM titulos_receber").fetchall())
        self.assertEqual(nomes[104], "MERCADO DO JOAO")  # cliente da carteira do ES, com título vendido pela BA
        f = Ferramentas(r, self.calc, a.cfg, {"BA"}, credito=a.credito)
        res, _ = f.executar("credito_cliente", {"id_cliente": 1})
        self.assertEqual((res["compras"]["valor"], res["cliente"]["limite_restante"]), (200.0, 3100.0))
        self.assertIn("aviso", res)

    def test_gestao_divide_o_recorte_com_credito(self):
        a = criar_assistente(self.pasta, self.calc)
        self.assertIs(a.recorte(None, credito=True), a.recorte(None, credito=True))
        self.assertIs(a._completo[1], a.recorte(None, credito=True))


if __name__ == "__main__":
    unittest.main()

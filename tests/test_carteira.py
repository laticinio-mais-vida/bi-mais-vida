"""Histórico da carteira (bi/carteira.py): os trechos de cada cliente ativo, gravados só quando algo muda, e o passo da
extração do cache (bi/cache.py) que registra o dia e leva as tabelas ao cache novo (ou as do anterior, sem o banco).

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from bi.carteira import Carteira, estado, ler, registrar, restaurar
from tests.apoio import BA, EDIR, ES, BaseBanco, criar_calc

D = dt.date


def ativo(vendedor, area="ROTA 1", segmento="MERCADO", uf="ES", bloqueado=False, id_area=1):
    return (vendedor, bloqueado, uf, id_area, area, segmento)


class TestEstado(unittest.TestCase):
    def test_ativos_do_cadastro(self):
        clientes = [(1, "MERCADO DO JOAO", ES), (2, "PEDIDO BLOQUEADO - BAR", BA), (3, "INATIVO", ES), (4, "SEM VENDEDOR", 0)]
        detalhes = [(1, "JOAO", "SERRA", "ES", 1, "ROTA 1", 1, "MERCADO", 0, D(2020, 1, 1)),
                    (2, "BAR", "PORTO", "BA", 2, "ROTA 2", 5, "BAR", 0, dt.datetime(2026, 10, 2, 8, 30)),
                    (3, "X", "SERRA", "ES", 1, "ROTA 1", 1, "MERCADO", 1, D(2020, 1, 1)),
                    (4, "Y", "SERRA", "ES", None, None, None, None, 0, None)]
        ativos, cadastro = estado(clientes, detalhes)
        self.assertEqual(ativos, {1: (ES, False, "ES", 1, "ROTA 1", "MERCADO"), 2: (BA, True, "BA", 2, "ROTA 2", "BAR"),
                                  4: (None, False, "ES", None, None, None)})  # o inativo fica fora; vendedor 0 = nenhum
        self.assertEqual(cadastro, {1: D(2020, 1, 1), 2: D(2026, 10, 2)})


class TestRegistrar(BaseBanco):
    def setUp(self):
        super().setUp()
        self.banco.migrar()

    def registrar(self, ativos, data, cadastro=None):
        with self.banco.conexao() as con:
            return registrar(con, ativos, cadastro or {}, data)

    def trechos(self):
        with self.banco.conexao() as con:
            return [(c, de, ate, v) for c, de, ate, v, *_ in ler(con)["clientes_vigencias"]]

    def retratos(self):
        with self.banco.conexao() as con:
            return ler(con)["carteira_retratos"]

    def test_entra_sai_troca_e_volta(self):
        r = self.registrar({1: ativo(ES), 2: ativo(BA), 3: ativo(ES)}, D(2026, 9, 15), {1: D(2026, 9, 1)})
        self.assertEqual((r["ativos"], r["entradas"], r["saidas"], r["trocas"]), (3, 3, 0, 0))
        # o primeiro dia: todos desde ele (a data de cadastro só vale depois do primeiro retrato)
        self.assertEqual(self.trechos(), [(1, D(2026, 9, 15), None, ES), (2, D(2026, 9, 15), None, BA),
                                          (3, D(2026, 9, 15), None, ES)])
        # 19/10: o 2 foi inativado, o 3 passou para a BA e o 4 é cadastro novo (de 01/10)
        r = self.registrar({1: ativo(ES), 3: ativo(BA), 4: ativo(EDIR)}, D(2026, 10, 19), {4: D(2026, 10, 1)})
        self.assertEqual((r["entradas"], r["saidas"], r["trocas"]), (1, 1, 1))
        self.assertEqual(self.trechos(), [
            (1, D(2026, 9, 15), None, ES), (2, D(2026, 9, 15), D(2026, 10, 18), BA),
            (3, D(2026, 9, 15), D(2026, 10, 18), ES), (3, D(2026, 10, 19), None, BA), (4, D(2026, 10, 1), None, EDIR)])
        # 23/10: o 2 é reativado (trecho novo, desde o dia) e o 1 muda de área (fecha um trecho e abre outro)
        self.registrar({1: ativo(ES, area="ROTA 9"), 2: ativo(BA), 3: ativo(BA), 4: ativo(EDIR)}, D(2026, 10, 23))
        self.assertEqual([t for t in self.trechos() if t[0] in (1, 2)], [
            (1, D(2026, 9, 15), D(2026, 10, 22), ES), (1, D(2026, 10, 23), None, ES),
            (2, D(2026, 9, 15), D(2026, 10, 18), BA), (2, D(2026, 10, 23), None, BA)])
        antes = self.trechos()
        # a mesma extração de novo no dia: nada muda, nem as contas do retrato
        r = self.registrar({1: ativo(ES, area="ROTA 9"), 2: ativo(BA), 3: ativo(BA), 4: ativo(EDIR)}, D(2026, 10, 23))
        self.assertEqual((self.trechos(), r["entradas"], r["saidas"], r["trocas"]), (antes, 0, 0, 0))
        # na mesma tarde, o 2 some de novo e o 1 troca de vendedor: o que abriu hoje não deixa rastro (some ou muda
        # no lugar); o resto do histórico fica como estava
        self.registrar({1: ativo(BA, area="ROTA 9"), 3: ativo(BA), 4: ativo(EDIR)}, D(2026, 10, 23))
        self.assertEqual([t for t in self.trechos() if t[0] in (1, 2)], [
            (1, D(2026, 9, 15), D(2026, 10, 22), ES), (1, D(2026, 10, 23), None, BA),
            (2, D(2026, 9, 15), D(2026, 10, 18), BA)])
        self.assertEqual(self.retratos(), [(D(2026, 9, 15), 3, 3, 0, 0), (D(2026, 10, 19), 3, 1, 1, 1),
                                           (D(2026, 10, 23), 3, 1, 1, 1)])
        with self.assertRaises(ValueError):  # a semeadura vem antes da primeira extração
            self.registrar({1: ativo(ES)}, D(2026, 10, 20))

    def test_bloqueado_abre_trecho(self):
        self.registrar({7: ativo(BA)}, D(2026, 9, 15))
        self.registrar({7: ativo(BA, bloqueado=True)}, D(2026, 9, 20))
        with self.banco.conexao() as con:
            self.assertEqual([(de, ate, b) for _, de, ate, _, b, *_ in ler(con)["clientes_vigencias"]],
                             [(D(2026, 9, 15), D(2026, 9, 19), False), (D(2026, 9, 20), None, True)])

    def test_restaura_do_cache(self):
        tabelas = {"clientes_vigencias": [(1, D(2026, 9, 15), None, ES, False, "ES", 1, "ROTA 1", "MERCADO")],
                   "carteira_retratos": [(D(2026, 9, 15), 1, 1, 0, 0)]}
        with self.banco.conexao() as con:
            self.assertTrue(restaurar(con, tabelas))
            self.assertFalse(restaurar(con, tabelas))  # com histórico no banco, o cache não manda
        # o banco voltou e a extração segue: o 1 continua, o 2 entra
        tabelas_novas = Carteira(self.banco)({1: ativo(ES), 2: ativo(BA)}, {}, D(2026, 10, 1))
        self.assertEqual([t[:4] for t in tabelas_novas["clientes_vigencias"]],
                         [(1, D(2026, 9, 15), None, ES), (2, D(2026, 10, 1), None, BA)])
        self.assertEqual([r[0] for r in tabelas_novas["carteira_retratos"]], [D(2026, 9, 15), D(2026, 10, 1)])


class TestCarteiraNaExtracao(unittest.TestCase):
    """O passo da extração (Cache._carteira) sem o Firebird: os dados como _extrair devolve."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.anterior = [(1, D(2026, 9, 15), None, ES, False, "ES", 1, "ROTA 1", "MERCADO")]
        self.calc = criar_calc(self.pasta, vigencias=self.anterior, retratos=[(D(2026, 9, 15), 1, 1, 0, 0)])
        self.cache = self.calc.cache

    def tearDown(self):
        self.cache._con.close()
        self._tmp.cleanup()

    def dados(self):
        return {"clientes": [(1, "MERCADO DO JOAO", ES), (2, "PADARIA", BA)],
                "clientes_detalhes": [(1, "J", "SERRA", "ES", 1, "ROTA 1", 1, "MERCADO", 0, D(2020, 1, 1)),
                                      (2, "P", "PORTO", "BA", 2, "ROTA 2", 2, "PADARIA", 0, D(2026, 10, 20))],
                "info": [("data_ref", "2026-10-22"), ("banco_copia", "2026-10-23T08:56")]}

    def test_registra_com_a_data_da_copia(self):
        chamadas = []

        def carteira(ativos, cadastro, data, anterior):
            chamadas.append((ativos, cadastro, data, anterior))
            return {"clientes_vigencias": ["novas"], "carteira_retratos": ["dias"]}
        self.cache.carteira = carteira
        dados = self.dados()
        self.cache._carteira(dados)
        (ativos, cadastro, data, anterior), = chamadas
        self.assertEqual((sorted(ativos), cadastro[2], data), ([1, 2], D(2026, 10, 20), D(2026, 10, 23)))
        self.assertEqual(anterior["clientes_vigencias"], self.anterior)
        self.assertEqual((dados["clientes_vigencias"], dados["carteira_retratos"]), (["novas"], ["dias"]))
        self.assertNotIn("carteira_erro", dict(dados["info"]))

    def test_sem_o_banco_leva_a_do_cache_anterior(self):
        self.cache.carteira = None  # ou o banco fora do ar: a extração segue com o histórico que já tinha
        dados = self.dados()
        self.cache._carteira(dados)
        self.assertEqual(dados["clientes_vigencias"], self.anterior)
        self.assertEqual(dados["carteira_retratos"], [(D(2026, 9, 15), 1, 1, 0, 0)])
        self.assertIn("carteira_erro", dict(dados["info"]))


if __name__ == "__main__":
    unittest.main()

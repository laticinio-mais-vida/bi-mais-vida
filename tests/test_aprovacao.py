"""Aprovação de metas (bi/aprovacao.py e Sugestao.aprovacao/aprovar): a distribuição do volume pelo R$ aprovado, as
planilhas com as aprovadas por cima, a aba, a gravação no banco (versões, edição sobre o retrato, retirada, conflito) e o
painel de Metas com a meta aprovada.

Usa o cache sintético da Sugestão (tests/test_sugestao.py) com o histórico da carteira: em 01/10/2026 a Jamille tem os
clientes 1 e 2 (o 5 está com pedido bloqueado e não conta), o Edir o 4 e o Rubens o 3; em 10/10 o cliente 2 passa para o
Edir. O Rubens (ES) também vende Bebida Láctea, para a mussarela e as outras linhas terem produtos.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import duckdb

from bi.aprovacao import MetasAprovadas, MetasComAprovadas, distribuir, juntar
from bi.assistente import _metas_produto, _metas_vendedor
from bi.banco import BancoForaDoAr
from bi.metas import Calculadora
from bi.sugestao import Sugestao
from tests.apoio import BaseBanco, PlanilhaFalsa
from tests.test_sugestao import BEBIDA, EDIR, JAMILLE, MUSSARELA, ORLA, RUBENS, ConfigFixa, criar_cache

D = dt.date
NOVO = 160  # vendedor do ES sem meta em nenhuma planilha


def produto(pid, volume, preco, grupo):
    return {"id": pid, "produto": f"P{pid}", "unidade": "UN", "grupo": grupo, "volume_sugerido": volume, "preco": preco}


class TestDistribuir(unittest.TestCase):
    def test_ba_um_fator(self):
        produtos = [produto(1, 100, 2.0, "outras"), produto(2, 10, 30.0, "mussarela")]  # R$ 200 + R$ 300
        lista, sobra = distribuir(produtos, 600.0, 0.0, False)
        self.assertEqual([p["meta_volume"] for p in lista], [120.0, 12.0])  # +20% nos dois
        self.assertAlmostEqual(sum(p["meta_volume"] * p["preco"] for p in lista), 600.0)
        self.assertEqual(sobra, 0.0)

    def test_es_mussarela_e_outras(self):
        produtos = [produto(1, 100, 2.0, "outras"), produto(2, 10, 30.0, "mussarela")]
        lista, sobra = distribuir(produtos, 600.0, 150.0, True)
        self.assertEqual([p["meta_volume"] for p in lista], [225.0, 5.0])  # outras 450/200; mussarela 150/300
        self.assertEqual(sobra, 0.0)

    def test_sem_produto_do_grupo(self):
        lista, sobra = distribuir([produto(2, 10, 30.0, "mussarela")], 600.0, 400.0, True)
        self.assertAlmostEqual(lista[0]["meta_volume"] * 30.0, 400.0, places=2)
        self.assertEqual(sobra, 200.0)  # as outras linhas não têm produto
        self.assertEqual(distribuir([], 500.0, 0.0, False), ([], 500.0))


class TestJuntar(unittest.TestCase):
    APROVADA = {"mes": D(2026, 10, 1), "id_vendedor": JAMILLE, "vendedor": "Jamille", "meta_fat": 500000.0,
                "meta_mus": 0.0, "meta_out": 0.0, "meta_cli": 118, "aprovada": True,
                "produtos": [{"id": MUSSARELA, "produto": "MUSSARELA", "meta_volume": 5431.0},
                             {"id": BEBIDA, "produto": "BEBIDA", "meta_volume": 0.0}]}

    def test_substitui_so_o_vendedor_e_mes(self):
        meta = lambda mes, v, fat: {"mes": mes, "id_vendedor": v, "vendedor": "X", "meta_fat": fat,  # noqa: E731
                                    "meta_mus": 0.0, "meta_out": 0.0, "meta_cli": 10.0}
        base = [meta(D(2026, 10, 1), JAMILLE, 1.0), meta(D(2026, 10, 1), JAMILLE, 2.0),  # o id repetido sai todo
                meta(D(2026, 9, 1), JAMILLE, 3.0), meta(D(2026, 10, 1), EDIR, 4.0)]
        r = juntar(base, [self.APROVADA], "metas")
        self.assertEqual(sorted((m["mes"].month, m["id_vendedor"], m["meta_fat"]) for m in r),
                         [(9, JAMILLE, 3.0), (10, EDIR, 4.0), (10, JAMILLE, 500000.0)])
        nova = next(m for m in r if m.get("aprovada"))
        self.assertEqual((nova["meta_cli"], nova["vendedor"]), (118.0, "Jamille"))
        self.assertIs(juntar(base, [], "metas"), base)

    def test_produtos(self):
        base = [{"mes": D(2026, 10, 1), "id_vendedor": JAMILLE, "vendedor": "X", "id_produto": 7, "produto": "Y",
                 "meta_volume": 9.0}]
        r = juntar(base, [self.APROVADA], "produtos")
        self.assertEqual([(m["id_produto"], m["meta_volume"]) for m in r], [(MUSSARELA, 5431.0)])  # sem volume: fora

    def test_versao_aviso_e_banco_fora_do_ar(self):
        class BancoFora:
            chamadas = 0

            def conexao(self):
                BancoFora.chamadas += 1
                raise BancoForaDoAr("fora")

        planilha = PlanilhaFalsa([{"mes": D(2026, 10, 1), "id_vendedor": JAMILLE, "vendedor": "X", "meta_fat": 1.0,
                                   "meta_mus": 0.0, "meta_out": 0.0, "meta_cli": 1.0}])
        ap = MetasAprovadas(BancoFora())
        metas, prods = MetasComAprovadas(planilha, ap, "metas"), MetasComAprovadas(PlanilhaFalsa([]), ap, "produtos")
        self.assertEqual(metas.dados(), planilha.dados())  # vale só a planilha
        self.assertIn("banco de dados fora do ar", metas.aviso)
        self.assertIsNone(prods.aviso)  # o aviso aparece uma vez só
        metas.dados()
        self.assertEqual(BancoFora.chamadas, 1)  # não tenta de novo a cada pedido
        self.assertEqual(metas.versao, (1, 0))


class TestAprovacao(BaseBanco):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        calc = criar_cache(Path(self.tmp.name))
        cache = calc.cache
        cache._con.close()
        con = duckdb.connect(str(cache.arquivo))
        vig = lambda c, de, ate, v, bloq=False: (c, de, ate, v, bloq, "BA", ORLA, "PS - ORLA", "MERCADO")  # noqa: E731
        con.executemany("INSERT INTO clientes_vigencias VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            vig(1, D(2026, 9, 15), None, JAMILLE), vig(2, D(2026, 9, 15), D(2026, 10, 9), JAMILLE),
            vig(2, D(2026, 10, 10), None, EDIR), vig(5, D(2026, 9, 15), None, JAMILLE, True),
            vig(4, D(2026, 9, 15), None, EDIR), vig(3, D(2026, 9, 15), None, RUBENS), vig(6, D(2026, 9, 15), None, NOVO)])
        con.execute("INSERT INTO carteira_retratos VALUES ('2026-09-15', 5, 0, 0, 0)")
        con.executemany("INSERT INTO vendas_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?)", [
            (D(2026, 9, 2), RUBENS, 3, "CLIENTE", BEBIDA, 1000.0, 250.0),
            (D(2026, 9, 2), NOVO, 6, "CLIENTE", BEBIDA, 400.0, 100.0)])
        con.execute("INSERT INTO clientes VALUES (6, 'PADARIA NOVA', ?)", [NOVO])
        con.execute("INSERT INTO vendedores VALUES (?, 'NOVO - ES', 3, 'VALDIRENE', 0)", [NOVO])
        con.close()
        cache._abrir()
        self.aprovadas = MetasAprovadas(self.banco)
        self.calc = Calculadora(cache, MetasComAprovadas(calc.metas, self.aprovadas, "metas"),
                                MetasComAprovadas(calc.metas_produtos, self.aprovadas, "produtos"), calc.configuracao)
        self.cfg = ConfigFixa()
        self.sug = Sugestao(self.calc, self.cfg, lambda: {ORLA: [3]},
                            lambda: {JAMILLE: "Jamille", EDIR: "Edir", RUBENS: "Rubens"}, self.aprovadas)
        self.admin = {"id": self.criar_usuario("admin2", "admin"), "nome": "Admin2"}

    def tearDown(self):
        self.calc.cache._con.close()
        self.tmp.cleanup()
        super().tearDown()

    def linha(self, aba, v):
        return next(x for x in aba["vendedores"] + aba["outros"] + aba["fora"] if x["id"] == v)

    def aprovar(self, estado, mes, v, **campos):
        aba = self.sug.aprovacao(estado, mes)
        item = {"id_vendedor": v, "aprovada": True, "versao": self.linha(aba, v)["versao"], **campos}
        return self.sug.aprovar(estado, mes, [item], self.admin)

    def test_aba(self):
        aba = self.sug.aprovacao("BA", "2026-10")
        self.assertEqual([v["id"] for v in aba["vendedores"]], [JAMILLE, EDIR])  # pela sugerida
        self.assertEqual(aba["clientes"], {"dia": "2026-10-01", "fonte": "carteira"})
        jam = self.linha(aba, JAMILLE)
        self.assertEqual(jam["clientes"], 2)  # o 5, com pedido bloqueado, não conta
        self.assertAlmostEqual(jam["sugerida"]["fat"], self.sug.calcular("BA", "2026-10", JAMILLE)["cartoes"]["meta_rs"],
                               places=2)
        self.assertEqual(jam["planilha"]["fat"], 25000.0)
        self.assertEqual((jam["versao"], jam["aprovada"], jam["retirada"]), (None, None, None))
        self.assertEqual({p["id"] for p in jam["sugerida"]["produtos"]}, {BEBIDA, MUSSARELA})
        # o dia 1º de novembro ainda não chegou: a carteira da data dos dados (o cliente 2 já é do Edir)
        nov = self.sug.aprovacao("BA", "2026-11")
        self.assertEqual(nov["clientes"], {"dia": "2026-10-26", "fonte": "carteira_hoje"})
        self.assertEqual(self.linha(nov, JAMILLE)["clientes"], 1)
        # o Edir (meta só em ago/26) fica fora da lista de nov/26 e, sem venda em out/26, também dos sem meta recente
        self.assertNotIn(EDIR, [v["id"] for v in nov["vendedores"] + nov["outros"]])
        # antes do histórico da carteira: a META CLIENTE da planilha (sem ela, sem número)
        set26 = self.sug.aprovacao("BA", "2026-09")
        self.assertEqual(set26["clientes"]["fonte"], "planilha")
        self.assertEqual(self.linha(set26, JAMILLE)["clientes"], 10)
        self.assertIsNone(self.linha(set26, EDIR)["clientes"])

    def test_aprovar_vale_no_painel_de_metas(self):
        sug = self.linha(self.sug.aprovacao("BA", "2026-10"), JAMILLE)["sugerida"]
        aba = self.aprovar("BA", "2026-10", JAMILLE, meta_fat=30000, meta_cli=12)
        a = self.linha(aba, JAMILLE)["aprovada"]
        self.assertEqual((a["meta_fat"], a["meta_cli"], a["clientes_carteira"], a["clientes_dia"]), (30000.0, 12, 2, "2026-10-01"))
        self.assertEqual(a["aprovada_por"], "Admin2")
        fator = 30000 / sug["fat"]
        bebida = next(p for p in a["produtos"] if p["id"] == BEBIDA)
        self.assertAlmostEqual(bebida["meta_volume"], bebida["volume_sugerido"] * fator, places=3)
        self.assertAlmostEqual(sum(p["meta_volume"] * p["preco"] for p in a["produtos"]), 30000, places=0)
        # painel de Metas: a aprovada no lugar da planilha (25.000 e 10 clientes)
        v = next(x for x in self.calc.visao("ba", [(2026, 10)])["linhas"] if x["id"] == JAMILLE)
        self.assertEqual((v["faturamento"]["meta"], v["clientes"]["meta"]), (30000.0, 12.0))
        p = next(x for x in self.calc.visao("produtos_ba", [(2026, 10)])["produtos"] if x["id"] == BEBIDA)
        self.assertAlmostEqual(p["por_vendedor"][str(JAMILLE)]["meta"], bebida["meta_volume"], places=3)
        # a página da sugestão mostra a lançada como aprovada; o Assistente também
        r = next(x for x in self.sug.calcular("BA", "2026-10")["resumo"] if x["id"] == JAMILLE)
        self.assertEqual((r["meta_lancada"], r["aprovada"]), (30000.0, True))
        self.assertTrue(self.sug.para_ia("BA", "2026-10", JAMILLE)["vendedor"]["aprovada_no_painel"])
        mv = _metas_vendedor(self.calc, None).set_index(["ano", "mes", "id_vendedor"])
        self.assertEqual(mv.loc[(2026, 10, JAMILLE), "meta_faturamento"], 30000.0)
        self.assertTrue(mv.loc[(2026, 10, JAMILLE), "aprovada_no_painel"])
        self.assertFalse(mv.loc[(2026, 9, JAMILLE), "aprovada_no_painel"])  # set/26 continua da planilha
        mp = _metas_produto(self.calc, self.calc.regras(), None)
        self.assertTrue(mp[(mp["id_vendedor"] == JAMILLE) & (mp["mes"] == 10)]["aprovada_no_painel"].all())
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT estado, aprovada, salva_por_nome FROM metas_aprovadas").fetchall(),
                             [("BA", True, "Admin2")])

    def test_editar_sobre_o_retrato_e_retirar(self):
        primeira = self.linha(self.aprovar("BA", "2026-10", JAMILLE, meta_fat=30000, meta_cli=12), JAMILLE)["aprovada"]
        self.cfg.cfg = {**self.cfg.cfg, "crescimento": {"ES": 0.12, "BA": 0.5}, "teto_crescimento": 1.0}  # a conta muda
        aba = self.aprovar("BA", "2026-10", JAMILLE, meta_fat=33000, meta_cli=13)
        jam = self.linha(aba, JAMILLE)
        a = jam["aprovada"]
        self.assertNotAlmostEqual(jam["sugerida"]["fat"], a["sugerida_fat"], places=0)  # "hoje a fórmula dá"
        self.assertEqual(a["sugerida_fat"], primeira["sugerida_fat"])  # a edição parte do retrato
        bebida = next(p for p in a["produtos"] if p["id"] == BEBIDA)
        self.assertAlmostEqual(bebida["meta_volume"], bebida["volume_sugerido"] * 33000 / a["sugerida_fat"], places=2)
        self.assertEqual((a["aprovada_por"], a["alterada_por"]), ("Admin2", "Admin2"))
        self.assertIsNotNone(a["alterada_em"])
        # retirar: volta a valer a planilha
        aba = self.sug.aprovar("BA", "2026-10", [{"id_vendedor": JAMILLE, "aprovada": False, "versao": jam["versao"]}],
                               self.admin)
        jam = self.linha(aba, JAMILLE)
        self.assertIsNone(jam["aprovada"])
        self.assertEqual(jam["retirada"]["por"], "Admin2")
        v = next(x for x in self.calc.visao("ba", [(2026, 10)])["linhas"] if x["id"] == JAMILLE)
        self.assertEqual(v["faturamento"]["meta"], 25000.0)
        # aprovar de novo: retrato novo, pela conta de hoje
        a = self.linha(self.aprovar("BA", "2026-10", JAMILLE, meta_fat=40000, meta_cli=12), JAMILLE)["aprovada"]
        self.assertAlmostEqual(a["sugerida_fat"], jam["sugerida"]["fat"], places=2)
        self.assertIsNone(a["alterada_em"])
        self.assertEqual(self.contar("metas_aprovadas"), 4)

    def test_conflito_de_versao(self):
        aba = self.sug.aprovacao("BA", "2026-10")
        item = {"id_vendedor": JAMILLE, "aprovada": True, "meta_fat": 30000, "meta_cli": 12,
                "versao": self.linha(aba, JAMILLE)["versao"]}
        self.sug.aprovar("BA", "2026-10", [item], self.admin)
        with self.assertRaises(ValueError) as e:  # a mesma versão de antes: outro administrador já gravou
            self.sug.aprovar("BA", "2026-10", [{**item, "meta_fat": 31000}, {"id_vendedor": EDIR, "aprovada": True,
                                                                           "meta_fat": 900, "meta_cli": 1, "versao": None}],
                             {"id": None, "nome": "Outro"})
        self.assertIn("alterada por Admin2", str(e.exception))
        self.assertEqual(self.contar("metas_aprovadas"), 1)  # nem o Edir entrou

    def test_es_com_mussarela_editada(self):
        aba = self.sug.aprovacao("ES", "2026-10")
        rub = self.linha(aba, RUBENS)
        self.assertGreater(rub["sugerida"]["mus"], 0)
        self.assertGreater(rub["sugerida"]["fat"], rub["sugerida"]["mus"])  # com a Bebida Láctea
        a = self.linha(self.aprovar("ES", "2026-10", RUBENS, meta_fat=10000, meta_mus=3000, meta_cli=1), RUBENS)["aprovada"]
        self.assertEqual((a["meta_fat"], a["meta_mus"], a["meta_out"]), (10000.0, 3000.0, 7000.0))
        rs = lambda grupo: sum(p["meta_volume"] * p["preco"] for p in a["produtos"] if p["grupo"] == grupo)  # noqa: E731
        self.assertAlmostEqual(rs("mussarela"), 3000, places=0)
        self.assertAlmostEqual(rs("outras"), 7000, places=0)
        v = next(x for x in self.calc.visao("es", [(2026, 10)])["linhas"] if x["id"] == RUBENS)
        self.assertEqual((v["faturamento"]["meta"], v["mussarela"]["meta"], v["outras"]["meta"]), (10000.0, 3000.0, 7000.0))

    def test_vendedor_sem_meta_recente(self):
        aba = self.sug.aprovacao("ES", "2026-10")
        self.assertNotIn(NOVO, [v["id"] for v in aba["vendedores"]])
        self.assertEqual([v["id"] for v in aba["outros"]], [NOVO])  # recolhido, mas dá para aprovar
        aba = self.aprovar("ES", "2026-10", NOVO, meta_fat=500, meta_mus=0, meta_cli=1)
        self.assertIn(NOVO, [v["id"] for v in aba["vendedores"]])  # com a meta aprovada, entra na lista
        self.assertIn(NOVO, [v["id"] for v in self.sug.calcular("ES", "2026-10")["opcoes"]["vendedores"]])

    def test_validacoes(self):
        casos = [({"meta_fat": 0, "meta_cli": 1}, "maior que zero"),
                 ({"meta_fat": "x", "meta_cli": 1}, "valor em reais"),
                 ({"meta_fat": 100, "meta_cli": None}, "preencha os clientes"),
                 ({"meta_fat": 100, "meta_cli": 1.5}, "número inteiro"),
                 ({"meta_fat": 100, "meta_cli": -1}, "número inteiro")]
        for campos, texto in casos:
            with self.assertRaises(ValueError) as e:
                self.aprovar("BA", "2026-10", JAMILLE, **campos)
            self.assertIn(texto, str(e.exception))
        with self.assertRaises(ValueError) as e:
            self.aprovar("ES", "2026-10", RUBENS, meta_fat=100, meta_mus=200, meta_cli=1)
        self.assertIn("passa da meta total", str(e.exception))
        with self.assertRaises(ValueError) as e:
            self.sug.aprovar("BA", "2026-10", [{"id_vendedor": RUBENS, "aprovada": True, "meta_fat": 100, "meta_cli": 1,
                                                "versao": None}], self.admin)  # é do ES
        self.assertIn("não está entre os vendedores do BA", str(e.exception))
        with self.assertRaises(ValueError):
            self.sug.aprovar("BA", "2026-10", [], self.admin)
        with self.assertRaises(ValueError):
            self.sug.aprovar("BA", "2026-12", [{"id_vendedor": JAMILLE}], self.admin)  # fora dos meses possíveis
        self.assertEqual(self.contar("metas_aprovadas"), 0)
        # retirar o que não está aprovado não grava nada
        self.sug.aprovar("BA", "2026-10", [{"id_vendedor": JAMILLE, "aprovada": False, "versao": None}], self.admin)
        self.assertEqual(self.contar("metas_aprovadas"), 0)


if __name__ == "__main__":
    unittest.main()

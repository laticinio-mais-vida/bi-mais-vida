"""Ajustes da meta de volume na página Sugestão de Metas (bi/ajustes.py, Sugestao.ajustar e aprovacao.somar_ajustes): a
sugestão com o número do administrador, a volta para a fórmula, a meta aprovada que ganha a mesma diferença e as
recusas.

Usa o cache sintético da aprovação (tests/test_aprovacao.py): no BA, a Jamille vende Bebida Láctea e Mussarela na
PS - ORLA, e o Edir Bebida Láctea na mesma área (a linha da Bebida na área soma os dois); no ES, o Rubens vende
Mussarela e Bebida Láctea.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bi.ajustes import AjustesVolume
from bi.aprovacao import somar_ajustes
from bi.banco import BancoForaDoAr
from bi.sugestao import Sugestao
from tests.test_aprovacao import BaseAprovacao, produto
from tests.test_sugestao import BEBIDA, EDIR, JAMILLE, MUSSARELA, ORLA, RUBENS, SEM_DIA, ConfigFixa, criar_cache


def aprovada(produtos, meta_fat, meta_mus=0.0, estado="BA"):
    lista = [{**p, "meta_volume": 0.0} for p in produtos]
    sug = sum(p["volume_sugerido"] * p["preco"] for p in produtos)
    mus = sum(p["volume_sugerido"] * p["preco"] for p in produtos if p["grupo"] == "mussarela")
    return {"estado": estado, "vendedor": "Jamille", "meta_fat": meta_fat, "meta_mus": meta_mus,
            "meta_out": meta_fat - meta_mus if estado == "ES" else 0.0, "sugerida_fat": sug, "sugerida_mus": mus,
            "produtos": lista}


def delta(volume, preco, grupo="outras", nome="P"):
    return {"volume": volume, "rs": volume * preco, "produto": nome, "unidade": "UN", "grupo": grupo}


class TestSomarAjustes(unittest.TestCase):
    PRODUTOS = [produto(1, 100, 2.0, "outras"), produto(2, 10, 30.0, "mussarela")]  # R$ 200 + R$ 300

    def volumes(self, r):
        return {p["id"]: round(p["meta_volume"], 4) for p in r["produtos"]}

    def test_ba_a_mesma_diferenca_e_o_fator_fica(self):
        r = somar_ajustes(aprovada(self.PRODUTOS, 600.0), {1: delta(10, 2.0)})  # aprovada com +20%
        self.assertEqual(self.volumes(r), {1: 130.0, 2: 12.0})  # 120 + 10; o outro não muda
        self.assertEqual(r["meta_fat"], 620.0)
        self.assertAlmostEqual(r["meta_fat"] / r["sugerida_fat"], 1.2, places=4)  # o +20% continua
        self.assertAlmostEqual(r["sugerida_mus"], 300.0)

    def test_ba_produto_zerado_e_produto_novo(self):
        r = somar_ajustes(aprovada(self.PRODUTOS, 600.0), {2: delta(-50, 30.0, "mussarela")})  # mais do que tinha
        self.assertEqual(self.volumes(r), {1: 120.0, 2: 0.0})
        self.assertEqual(r["meta_fat"], 240.0)  # sai só o que a mussarela tinha (12 × 30)
        r = somar_ajustes(aprovada(self.PRODUTOS, 600.0), {3: delta(5, 10.0)})
        self.assertEqual(self.volumes(r), {1: 120.0, 2: 12.0, 3: 5.0})
        self.assertEqual(r["meta_fat"], 650.0)
        self.assertEqual(r["produtos"][-1]["preco"], 10.0)
        r = somar_ajustes(aprovada(self.PRODUTOS, 600.0), {3: delta(-5, 10.0)})  # tirar de quem não tem: nada
        self.assertEqual((r["meta_fat"], len(r["produtos"])), (600.0, 2))

    def test_ba_meta_zerada(self):
        with self.assertRaises(ValueError) as e:
            somar_ajustes(aprovada([produto(1, 100, 2.0, "outras")], 200.0), {1: delta(-100, 2.0)})
        self.assertIn("ficaria zerada", str(e.exception))

    def test_es_pelo_grupo(self):
        a = aprovada(self.PRODUTOS, 600.0, 150.0, "ES")  # mussarela 150/300 = 0,5; outras 450/200 = 2,25
        r = somar_ajustes(a, {2: delta(2, 30.0, "mussarela")})
        self.assertEqual(self.volumes(r), {1: 225.0, 2: 7.0})  # 5 + 2
        self.assertEqual((r["meta_fat"], r["meta_mus"], r["meta_out"]), (660.0, 210.0, 450.0))
        r = somar_ajustes(a, {1: delta(-25, 2.0)})
        self.assertEqual(self.volumes(r), {1: 200.0, 2: 5.0})
        self.assertEqual((r["meta_fat"], r["meta_mus"], r["meta_out"]), (550.0, 150.0, 400.0))

    def test_es_grupo_sem_produto_ou_zerado(self):
        so_outras = aprovada([produto(1, 100, 2.0, "outras")], 300.0, 0.0, "ES")
        r = somar_ajustes(so_outras, {2: delta(4, 30.0, "mussarela")})  # mussarela nova: o volume do ajuste
        self.assertEqual(self.volumes(r), {1: 150.0, 2: 4.0})
        self.assertEqual((r["meta_fat"], r["meta_mus"], r["meta_out"]), (420.0, 120.0, 300.0))
        with self.assertRaises(ValueError) as e:  # mussarela aprovada em zero, com produto de mussarela
            somar_ajustes(aprovada(self.PRODUTOS, 600.0, 0.0, "ES"), {2: delta(1, 30.0, "mussarela")})
        self.assertIn("mussarela", str(e.exception))


class TestBancoForaDoAr(unittest.TestCase):
    def test_vale_a_formula_com_aviso(self):
        class BancoFora:
            def conexao(self):
                raise BancoForaDoAr("fora")

        with tempfile.TemporaryDirectory() as pasta:
            calc = criar_cache(Path(pasta))
            try:
                sug = Sugestao(calc, ConfigFixa(), lambda: {ORLA: [3]}, lambda: {}, None, AjustesVolume(BancoFora()))
                r = sug.calcular("BA", "2026-10", JAMILLE)
                self.assertFalse(r["ajustes"]["disponivel"])
                self.assertTrue(any("ajustes de volume" in a for a in r["avisos"]))
                self.assertEqual(r["produtos"][0]["ajustes"], 0)
            finally:
                calc.cache._con.close()


class TestAjustes(BaseAprovacao):
    def linha_ba(self, r, area, p):
        return next(x for a in r["areas"] if a["id"] == area for x in a["produtos"] if x["id"] == p)

    def ajustar(self, estado, mes, *itens):
        return self.sug.ajustar(estado, mes, [dict(zip(("id_vendedor", "id_area", "id_produto", "meta_volume"), i))
                                              for i in itens], self.admin)

    def test_ajuste_na_sugestao_e_volta_para_a_formula(self):
        antes = self.sug.calcular("BA", "2026-10", JAMILLE)
        bebida = self.linha_ba(antes, ORLA, BEBIDA)
        self.assertEqual((bebida["linha"]["vendedor"], bebida["linha"]["area"]), (JAMILLE, ORLA))
        self.assertIsNone(bebida["linha"]["ajuste"])
        formula, preco = bebida["meta_volume"], bebida["linha"]["preco"]
        r = self.ajustar("BA", "2026-10", (JAMILLE, ORLA, BEBIDA, 6000))
        self.assertEqual((r["gravados"], r["aprovadas"]), (1, []))
        depois = self.sug.calcular("BA", "2026-10", JAMILLE)
        b = self.linha_ba(depois, ORLA, BEBIDA)
        self.assertEqual((b["meta_volume"], b["ajustes"]), (6000.0, 1))
        self.assertAlmostEqual(b["meta_formula"], formula)
        self.assertAlmostEqual(b["meta_rs"], 6000 * preco)
        self.assertEqual(b["linha"]["ajuste"]["salva_por"], "Admin2")
        self.assertAlmostEqual(depois["cartoes"]["meta_rs"], antes["cartoes"]["meta_rs"] + (6000 - formula) * preco)
        # todos os vendedores: a Bebida na Orla soma a Jamille (ajustada) e o Edir (fórmula), e não é uma linha só
        todos = self.sug.calcular("BA", "2026-10")
        soma = self.linha_ba(todos, ORLA, BEBIDA)
        self.assertIsNone(soma["linha"])
        edir = self.linha_ba(self.sug.calcular("BA", "2026-10", EDIR), ORLA, BEBIDA)
        self.assertAlmostEqual(soma["meta_volume"], 6000 + edir["meta_volume"])
        jam = next(x for x in todos["resumo"] if x["id"] == JAMILLE)
        self.assertAlmostEqual(jam["meta_rs"], depois["cartoes"]["meta_rs"])
        # a aprovação parte da sugestão ajustada; o Assistente vê o ajuste
        aba = self.linha(self.sug.aprovacao("BA", "2026-10"), JAMILLE)
        self.assertAlmostEqual(aba["sugerida"]["fat"], depois["cartoes"]["meta_rs"], places=2)
        ia = next(p for p in self.sug.para_ia("BA", "2026-10", JAMILLE)["produtos"] if p["id"] == BEBIDA)
        self.assertEqual((ia["meta_volume"], ia["ajustada"]), (6000.0, True))
        # vazio: volta para a fórmula
        self.ajustar("BA", "2026-10", (JAMILLE, ORLA, BEBIDA, None))
        b = self.linha_ba(self.sug.calcular("BA", "2026-10", JAMILLE), ORLA, BEBIDA)
        self.assertEqual((round(b["meta_volume"], 6), b["ajustes"]), (round(formula, 6), 0))
        self.assertEqual(self.contar("sugestao_ajustes"), 0)

    def test_aprovada_ganha_a_mesma_diferenca(self):
        aprov = self.linha(self.aprovar("BA", "2026-10", JAMILLE, meta_fat=30000, meta_cli=12), JAMILLE)["aprovada"]
        vol = lambda a, p: next(x["meta_volume"] for x in a["produtos"] if x["id"] == p)  # noqa: E731
        bebida = self.linha_ba(self.sug.calcular("BA", "2026-10", JAMILLE), ORLA, BEBIDA)
        formula, preco = bebida["meta_volume"], bebida["linha"]["preco"]
        r = self.ajustar("BA", "2026-10", (JAMILLE, ORLA, BEBIDA, formula + 500))
        self.assertEqual(r["aprovadas"], ["Jamille"])
        nova = self.linha(self.sug.aprovacao("BA", "2026-10"), JAMILLE)["aprovada"]
        self.assertAlmostEqual(vol(nova, BEBIDA), vol(aprov, BEBIDA) + 500, places=2)
        self.assertAlmostEqual(vol(nova, MUSSARELA), vol(aprov, MUSSARELA), places=3)  # o outro produto não muda
        self.assertAlmostEqual(nova["meta_fat"], 30000 + 500 * preco, places=1)
        self.assertAlmostEqual(nova["meta_fat"] / nova["sugerida_fat"], 30000 / aprov["sugerida_fat"], places=4)
        self.assertEqual((nova["aprovada_por"], nova["alterada_por"], nova["meta_cli"]), ("Admin2", "Admin2", 12))
        # o painel de Metas já vê a meta nova
        v = next(x for x in self.calc.visao("ba", [(2026, 10)])["linhas"] if x["id"] == JAMILLE)
        self.assertAlmostEqual(v["faturamento"]["meta"], nova["meta_fat"], places=2)
        p = next(x for x in self.calc.visao("produtos_ba", [(2026, 10)])["produtos"] if x["id"] == BEBIDA)
        self.assertAlmostEqual(p["por_vendedor"][str(JAMILLE)]["meta"], vol(nova, BEBIDA), places=3)
        # gravar o mesmo número de novo não muda a aprovada (a diferença é contra o ajuste gravado)
        self.assertEqual(self.ajustar("BA", "2026-10", (JAMILLE, ORLA, BEBIDA, formula + 500))["aprovadas"], [])
        self.assertEqual(self.contar("metas_aprovadas"), 2)
        # o R$ editado em Configurar continua movendo todos os produtos no mesmo %
        r = self.linha(self.aprovar("BA", "2026-10", JAMILLE, meta_fat=nova["meta_fat"] * 1.1, meta_cli=12), JAMILLE)
        self.assertAlmostEqual(vol(r["aprovada"], BEBIDA), vol(nova, BEBIDA) * 1.1, places=1)
        self.assertAlmostEqual(vol(r["aprovada"], MUSSARELA), vol(nova, MUSSARELA) * 1.1, places=2)
        # voltar para a fórmula devolve a diferença
        self.ajustar("BA", "2026-10", (JAMILLE, ORLA, BEBIDA, None))
        volta = self.linha(self.sug.aprovacao("BA", "2026-10"), JAMILLE)["aprovada"]
        self.assertAlmostEqual(vol(volta, BEBIDA), vol(r["aprovada"], BEBIDA) - 500, places=2)

    def test_es_mussarela_e_filtro_de_area(self):
        aprov = self.linha(self.aprovar("ES", "2026-10", RUBENS, meta_fat=10000, meta_mus=3000, meta_cli=1),
                           RUBENS)["aprovada"]
        antes = self.sug.calcular("ES", "2026-10", RUBENS)
        mus = next(x for x in antes["produtos"] if x["id"] == MUSSARELA)
        self.assertEqual(mus["linha"]["area"], 0)
        r = self.ajustar("ES", "2026-10", (RUBENS, None, MUSSARELA, mus["meta_volume"] + 10))
        self.assertEqual(r["aprovadas"], ["Rubens"])
        nova = self.linha(self.sug.aprovacao("ES", "2026-10"), RUBENS)["aprovada"]
        ganho = 10 * mus["linha"]["preco"]
        self.assertAlmostEqual(nova["meta_mus"], 3000 + ganho, places=1)
        self.assertAlmostEqual(nova["meta_out"], 7000, places=1)  # as outras linhas não mudam
        self.assertAlmostEqual(nova["meta_fat"], 10000 + ganho, places=1)
        # com o filtro de área, a parte da área acompanha o ajuste (o Rubens só tem a área da rota)
        area = antes["opcoes"]["areas"][0]["id"]
        filtrada = self.sug.calcular("ES", "2026-10", RUBENS, area)
        self.assertAlmostEqual(next(x for x in filtrada["produtos"] if x["id"] == MUSSARELA)["meta_volume"],
                               mus["meta_volume"] + 10, places=4)
        self.assertNotEqual(aprov["meta_mus"], nova["meta_mus"])

    def test_recusas(self):
        casos = [((JAMILLE, SEM_DIA, BEBIDA, 10), "não está na sugestão"),  # área sem faturamento: fica fora
                 ((RUBENS, ORLA, MUSSARELA, 10), "não está entre os vendedores do BA"),
                 ((JAMILLE, ORLA, BEBIDA, -1), "a partir de zero"),
                 ((JAMILLE, ORLA, BEBIDA, "x"), "use um número"),
                 ((JAMILLE, None, BEBIDA, 10), "área ou produto válidos")]
        for item, texto in casos:
            with self.assertRaises(ValueError) as e:
                self.ajustar("BA", "2026-10", item)
            self.assertIn(texto, str(e.exception))
        with self.assertRaises(ValueError) as e:
            self.ajustar("BA", "2026-10", (JAMILLE, ORLA, BEBIDA, 1), (JAMILLE, ORLA, BEBIDA, 2))
        self.assertIn("duas vezes", str(e.exception))
        with self.assertRaises(ValueError):
            self.sug.ajustar("BA", "2026-10", [], self.admin)
        with self.assertRaises(ValueError):
            self.ajustar("BA", "2026-12", (JAMILLE, ORLA, BEBIDA, 1))  # fora dos meses possíveis
        self.assertEqual(self.contar("sugestao_ajustes"), 0)

    def test_ajuste_que_saiu_da_conta(self):
        with self.banco.conexao() as con:  # gravado quando a linha existia
            con.execute("INSERT INTO sugestao_ajustes (mes, id_vendedor, id_area, id_produto, meta_volume) "
                        "VALUES ('2026-10-01', %s, %s, %s, 50)", [JAMILLE, SEM_DIA, BEBIDA])
        r = self.sug.calcular("BA", "2026-10")
        self.assertTrue(any("1 ajuste de volume" in a for a in r["avisos"]))
        self.assertTrue(r["ajustes"]["disponivel"])
        vendedor = self.sug.calcular("BA", "2026-10", permitidos={JAMILLE})  # quem não é administrador não vê o aviso
        self.assertFalse(any("ajuste de volume" in a for a in vendedor["avisos"]))


if __name__ == "__main__":
    unittest.main()

"""Reavaliação de Crédito (bi/credito.py): os cartões da página do Power BI contra as contas feitas à mão nos títulos
de tests/apoio.py (TITULOS, LIMITES e PARCELAS), com as diferenças aprovadas (pontualidade em fração, restante sem o
período, limite só com cliente, vários clientes somados, parcelas pagas descontadas do que está em aberto), a
ordenação da tabela e os dados de crédito no Assistente, só para quem tem a página.

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
    parcelas_no_cache = True

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.calc = criar_calc(self.pasta, credito=self.credito_no_cache, parcelas=self.parcelas_no_cache)
        self.credito = Credito(self.calc.cache, lambda: dict(NOMES))

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()

    def ids(self, **args) -> list[int]:
        return [t["id"] for t in self.credito.calcular(**args)["titulos"]["linhas"]]


class TestCartoes(Base):
    def test_cliente_sem_periodo(self):
        d = self.credito.calcular([1])
        self.assertEqual(d["hoje"], D(2026, 10, 1))  # o dia da extração
        k = d["cartoes"]
        self.assertEqual((k["valor"], k["quantidade"]), (4000.0, 6))
        self.assertAlmostEqual(k["ticket"], 4000 / 6)
        # quitados 101, 102 e 106; só o 102 (8 dias) passou dos 7 dias
        self.assertEqual((k["quitados"], k["quitados_atrasados"]), (3, 1))
        self.assertAlmostEqual(k["pontualidade"], 2 / 3)
        # em aberto vencido antes de 24/09: só o 103 (o 104 vence em 24/09, 7 dias); pelo valor do título
        self.assertEqual(k["inadimplencia"], 1300.0)
        c = d["clientes"][0]
        self.assertEqual((c["nome"], c["carteira"], c["prazo"], c["limite"]), ("MERCADO DO JOAO", "Rubens", "28 DIAS", 5000.0))
        # em aberto: 103 + 104 + 105 = 1.900, menos as parcelas pagas do 103 (650) e do 105 (100)
        self.assertEqual((c["qtd_abertos"], c["titulos_abertos"], c["pago_parcelas"], c["em_aberto"], c["restante"]),
                         (3, 1900.0, 750.0, 1150.0, 3850.0))
        self.assertAlmostEqual(c["usado"], 0.23)
        self.assertEqual(d["credito"]["restante"], 3850.0)
        self.assertEqual(d["avisos"], [])

    def test_mes_sem_ano_vale_para_todos_os_anos(self):
        k = self.credito.calcular([1], mes=9)["cartoes"]
        self.assertEqual((k["valor"], k["quantidade"]), (2500.0, 4))  # 103, 104, 105 e o 106 de setembro de 2025
        self.assertEqual(k["pontualidade"], 1.0)  # o 106 foi pago 7 dias depois: ainda pontual
        k = self.credito.calcular([1], mes=9, ano=2026)["cartoes"]
        self.assertEqual((k["valor"], k["quantidade"], k["pontualidade"]), (1900.0, 3, None))
        self.assertEqual(self.credito.calcular([1], ano=2025)["cartoes"]["valor"], 600.0)

    def test_restante_ignora_o_periodo_e_o_vendedor(self):
        d = self.credito.calcular([1], mes=8, ano=2026, vendedor=BA)
        self.assertEqual(d["cartoes"]["quantidade"], 0)
        self.assertEqual((d["clientes"][0]["em_aberto"], d["clientes"][0]["restante"]), (1150.0, 3850.0))

    def test_vendedor_do_titulo(self):
        d = self.credito.calcular([1], vendedor=BA)
        self.assertEqual((d["cartoes"]["valor"], [t["id"] for t in d["titulos"]["linhas"]]), (200.0, [104]))
        self.assertEqual(self.credito.calcular(vendedor=EDIR)["cartoes"]["valor"], 710.0)

    def test_passou_do_limite_e_sem_limite(self):
        c = self.credito.calcular([2])["clientes"][0]
        self.assertEqual((c["restante"], c["prazo"]), (-500.0, "A VISTA"))
        self.assertAlmostEqual(c["usado"], 1.25)
        c = self.credito.calcular([4])["clientes"][0]
        self.assertEqual((c["limite"], c["usado"], c["prazo"], c["restante"]), (0.0, None, None, 0.0))
        d = self.credito.calcular([3])  # cliente sem título nenhum
        self.assertEqual((d["clientes"][0]["restante"], d["cartoes"]["quantidade"], d["cartoes"]["ticket"]),
                         (1000.0, 0, None))

    def test_varios_clientes_somam(self):
        d = self.credito.calcular([2, 1, 2])  # repetido conta uma vez, na ordem da escolha
        self.assertEqual([c["id"] for c in d["clientes"]], [2, 1])
        self.assertEqual(d["filtros"]["clientes"], [2, 1])
        s = d["credito"]
        self.assertEqual((s["limite"], s["qtd_abertos"], s["em_aberto"], s["pago_parcelas"], s["restante"]),
                         (7000.0, 4, 3650.0, 750.0, 3350.0))
        self.assertAlmostEqual(s["usado"], 3650 / 7000)
        self.assertEqual((s["prazos"], s["carteiras"]), (["28 DIAS", "A VISTA"], ["Rubens", "Thais"]))
        self.assertEqual((d["cartoes"]["valor"], d["cartoes"]["quantidade"]), (6500.0, 7))
        self.assertEqual(d["cartoes"]["inadimplencia"], 3800.0)  # 103 + 201

    def test_sem_cliente_soma_o_filtro_sem_limite(self):
        d = self.credito.calcular()
        self.assertEqual((d["clientes"], d["credito"]), ([], None))
        self.assertEqual((d["cartoes"]["valor"], d["cartoes"]["quantidade"]), (7210.0, 9))
        self.assertEqual(d["cartoes"]["inadimplencia"], 3800.0)  # 103 + 201

    def test_permitidos_do_assistente(self):
        d = self.credito.calcular([1], permitidos={BA})
        self.assertEqual(d["cartoes"]["valor"], 200.0)
        self.assertEqual(d["clientes"][0]["restante"], 3850.0)  # o limite é do cliente inteiro
        self.assertEqual([v["id"] for v in d["opcoes"]["vendedores"]], [BA])
        d = self.credito.calcular([1], permitidos=set())
        self.assertEqual((d["cartoes"]["quantidade"], d["cartoes"]["ticket"], d["titulos"]["linhas"]), (0, None, []))


class TestTitulos(Base):
    def test_dias_situacao_e_pago(self):
        linhas = {t["id"]: t for t in self.credito.calcular([1])["titulos"]["linhas"]}
        esperado = {101: (1, "quitado"), 102: (8, "quitado_atraso"), 103: (8, "inadimplente"), 104: (7, "vencido"),
                    105: (-25, "a_vencer"), 106: (7, "quitado")}
        self.assertEqual({i: (t["dias_atraso"], t["situacao"]) for i, t in linhas.items()}, esperado)
        self.assertEqual(linhas[104]["vendedor"], "Thais")
        pago = {i: (t["pago"], t["saldo"], t["pagas"], t["parcelas"]) for i, t in linhas.items()}
        self.assertEqual(pago, {101: (1000.0, 0.0, 1, 1), 102: (500.0, 0.0, 2, 2), 103: (650.0, 650.0, 1, 2),
                                104: (0.0, 200.0, 0, 1), 105: (100.0, 300.0, 0, 1), 106: (600.0, 0.0, 1, 1)})

    def test_ordem_padrao_e_limite_de_linhas(self):
        d = self.credito.calcular([1])
        self.assertEqual([t["id"] for t in d["titulos"]["linhas"]], [105, 104, 103, 102, 101, 106])
        self.assertEqual(d["ordem"], {"coluna": "emissao", "sentido": "desc"})
        with mock.patch.object(modulo, "MAX_TITULOS", 2):
            t = self.credito.calcular()["titulos"]
        self.assertEqual((t["total"], t["mostrando"], t["linhas"][0]["id"]), (9, 2, 402))  # a data errada vem antes

    def test_ordenar_por_qualquer_coluna(self):
        self.assertEqual(self.ids(clientes=[1], ordem="valor", sentido="desc"), [103, 101, 106, 102, 105, 104])
        self.assertEqual(self.ids(clientes=[1], ordem="valor", sentido="asc"), [104, 105, 102, 106, 101, 103])
        self.assertEqual(self.ids(clientes=[1], ordem="pago", sentido="desc"), [101, 103, 106, 102, 105, 104])
        # da pior para a melhor; empate (101 e 106, quitados) pela emissão mais recente
        self.assertEqual(self.ids(clientes=[1], ordem="situacao", sentido="desc"), [103, 104, 102, 105, 101, 106])
        self.assertEqual(self.ids(clientes=[1], ordem="dias", sentido="asc"), [105, 101, 104, 106, 103, 102])
        self.assertEqual(self.ids(clientes=[1], ordem="quitacao", sentido="asc")[:4], [106, 101, 102, 105])  # vazias no fim
        self.assertEqual(self.ids(ordem="vendedor", sentido="asc")[:2], [402, 401])  # Edir, pelo nome mostrado
        self.assertEqual(self.ids(ordem="titulo", sentido="asc")[0], 101)
        d = self.credito.calcular(ordem="cliente", sentido="desc")
        self.assertEqual(d["titulos"]["linhas"][0]["cliente"], "PADARIA DA MARIA")
        self.assertEqual(d["ordem"], {"coluna": "cliente", "sentido": "desc"})
        with mock.patch.object(modulo, "MAX_TITULOS", 1):  # a ordem vale para o filtro inteiro, antes de cortar
            self.assertEqual(self.ids(ordem="valor", sentido="desc"), [201])

    def test_opcoes(self):
        op = self.credito.calcular()["opcoes"]
        self.assertEqual([v["nome"] for v in op["vendedores"]], ["Edir", "Rubens", "Thais"])
        self.assertEqual(op["anos"], [2026, 2025])  # o ano 7190 (data errada) não vira opção

    def test_parametros_invalidos(self):
        for args in ({"mes": 13}, {"mes": 0}, {"ano": 7190}, {"clientes": [999]}, {"clientes": [1, 999]},
                     {"ordem": "nome; DROP"}, {"ordem": "valor", "sentido": "lado"},
                     {"clientes": list(range(1, modulo.MAX_CLIENTES + 2))}):
            with self.assertRaises(ValueError, msg=args):
                self.credito.calcular(**args)


class TestParecer(Base):
    """O parecer de um limite novo (Credito.analisar). Hoje = 01/10/2026; a janela de 12 meses começa em 02/10/2025."""

    def inserir(self, titulos=(), clientes=(), limites=()):
        """Mais linhas no cache do teste (aberto só para leitura): fecha, grava e abre de novo."""
        cache = self.calc.cache
        cache._con.close()
        con = duckdb.connect(str(cache.arquivo))
        for tabela, linhas in (("titulos_receber", titulos), ("clientes", clientes), ("clientes_credito", limites)):
            if linhas:
                con.executemany(f"INSERT INTO {tabela} VALUES ({','.join('?' * len(linhas[0]))})", linhas)
        con.close()
        cache._abrir()

    def emporio(self, atrasados: int = 0, ultimo_mes: int = 9, limite: float = 3000.0):
        """Cliente 50, desde 2024, com 2 títulos de R$ 1.000 por mês na janela (dias 5 e 12, de nov/2025 até o
        ultimo_mes de 2026, ou até set/2026), a 14 dias, pagos no vencimento. Os dois se cruzam uma semana: o maior
        saldo em aberto é R$ 2.000. atrasados: quantos dos últimos foram pagos 10 dias depois do vencimento."""
        meses = [(2025, 11), (2025, 12)] + [(2026, m) for m in range(1, ultimo_mes + 1)]
        titulos = [(5000, 50, ES, D(2024, 1, 5), D(2024, 1, 19), D(2024, 1, 19), 1, 800.0)]  # fora da janela
        for n, (a, m) in enumerate((a, m) for a, m in meses for _ in (0, 1)):
            emissao = D(a, m, 5 if n % 2 == 0 else 12)
            vencimento = emissao + dt.timedelta(days=14)
            atraso = 10 if n >= 2 * len(meses) - atrasados else 0
            titulos.append((5001 + n, 50, ES, emissao, vencimento, vencimento + dt.timedelta(days=atraso), 1, 1000.0))
        self.inserir(titulos, [(50, "EMPORIO BOM", ES)], [(50, limite, "14 DIAS")])
        return len(titulos) - 1  # títulos na janela

    def status(self, a) -> dict:
        return {c["chave"]: c["status"] for c in a["criterios"]}

    def test_indicado(self):
        n = self.emporio()
        a = self.credito.analisar(50, 4000)  # 2x o maior saldo: ainda passa
        self.assertEqual(a["parecer"], "indicado")
        self.assertEqual(set(self.status(a).values()), {"ok"})
        self.assertEqual([c["chave"] for c in a["criterios"]], list(modulo.CRITERIOS))
        x = a["numeros"]
        self.assertEqual((x["maior_saldo"], x["maior_saldo_em"], x["pedido_vezes_maior_saldo"]),
                         (2000.0, D(2026, 9, 12), 2.0))  # empate: o dia mais recente
        self.assertEqual((x["quitados"], x["quitados_pontuais"], x["pontualidade"], x["atraso_medio"]), (n, n, 1.0, None))
        self.assertEqual((x["primeiro_titulo"], x["ultimo_titulo"], x["meses_cliente"]),
                         (D(2024, 1, 5), D(2026, 9, 12), 32))
        self.assertAlmostEqual(x["compras_mes"], n * 1000 / 12)
        self.assertEqual((x["prazo_real"], x["em_aberto"], x["limite_atual"]), (14, 0.0, 3000.0))
        self.assertEqual((a["limite_sugerido"], a["pedido"], a["hoje"]), (4000, 4000.0, D(2026, 10, 1)))
        self.assertEqual(a["cliente"], {"id": 50, "nome": "EMPORIO BOM", "carteira": "Rubens", "prazo": "14 DIAS"})
        self.assertEqual((a["avisos"], a["regra"]), ([], modulo.REGRA))
        self.assertIn("2 anos e 8 meses", a["criterios"][2]["detalhe"])

    def test_limite_pedido_contra_o_maior_saldo(self):
        self.emporio()
        a = self.credito.analisar(50, 5000)  # 2,5x
        self.assertEqual((a["parecer"], self.status(a)["folga"]), ("ressalvas", "atencao"))
        self.assertIn("2,5 vezes o maior saldo em aberto", a["criterios"][3]["detalhe"])
        self.assertIn("R$ 2.000,00 em 12/09/2026", a["criterios"][3]["detalhe"])
        a = self.credito.analisar(50, 6000.01)  # acima de 3x: não indicado, mas o sugerido aparece
        self.assertEqual((a["parecer"], self.status(a)["folga"], a["limite_sugerido"]), ("nao_indicado", "bloqueio", 4000))
        a = self.credito.analisar(50, 3000)  # o mesmo de hoje: não é aumento
        self.assertEqual((a["parecer"], a["criterios"][3]["detalhe"]),
                         ("indicado", "Não é aumento: o limite de hoje é R$ 3.000,00."))

    def test_maior_saldo_conta_o_que_vinha_de_antes_da_janela(self):
        self.emporio()
        # emitido antes da janela e pago só em dezembro: no 1º dia dela (02/10/2025) o saldo já era R$ 9.000
        self.inserir([(5900, 50, ES, D(2025, 9, 1), D(2025, 9, 15), D(2025, 12, 1), 1, 9000.0)])
        x = self.credito.analisar(50, 4000)["numeros"]
        self.assertEqual((x["maior_saldo"], x["maior_saldo_em"]), (11000.0, D(2025, 11, 12)))

    def test_pontualidade_media(self):
        n = self.emporio(atrasados=3)
        a = self.credito.analisar(50, 4000)
        self.assertEqual((a["parecer"], self.status(a)["pontualidade"]), ("ressalvas", "atencao"))
        self.assertEqual((a["numeros"]["quitados_pontuais"], a["numeros"]["atraso_medio"]), (n - 3, 10))
        self.assertIn(f"({n - 3} de {n}); os atrasados foram pagos, em média, 10 dias", a["criterios"][1]["detalhe"])

    def test_pontualidade_baixa_tira_o_sugerido(self):
        self.emporio(atrasados=7)  # 15 de 22: abaixo de 70%
        a = self.credito.analisar(50, 4000)
        self.assertEqual((a["parecer"], self.status(a)["pontualidade"], a["limite_sugerido"]),
                         ("nao_indicado", "bloqueio", None))

    def test_sem_compra_recente_e_vencido_ha_poucos_dias(self):
        self.emporio(ultimo_mes=5)  # última compra em 12/05/2026
        self.inserir([(5950, 50, BA, D(2026, 5, 20), D(2026, 9, 27), None, 0, 300.0)])  # vencido há 4 dias
        a = self.credito.analisar(50, 4000)
        s = self.status(a)
        self.assertEqual((a["parecer"], s["recente"], s["inadimplencia"]), ("ressalvas", "atencao", "atencao"))
        self.assertIn("Última compra em 20/05/2026, há 134 dias", a["criterios"][5]["detalhe"])
        self.assertEqual(a["criterios"][0]["detalhe"],
                         "1 título vencido há até 7 dias (R$ 300,00): ainda dentro da tolerância.")

    def test_cliente_inadimplente(self):
        a = self.credito.analisar(1, 6000)
        s = self.status(a)
        self.assertEqual(a["parecer"], "nao_indicado")
        self.assertEqual((s["inadimplencia"], s["pontualidade"], s["tempo"], s["folga"], s["em_aberto"], s["recente"]),
                         ("bloqueio", "atencao", "ok", "bloqueio", "ok", "ok"))
        self.assertEqual(a["criterios"][0]["detalhe"], "1 título em aberto vencido há mais de 7 dias: R$ 1.300,00.")
        self.assertEqual(a["criterios"][1]["detalhe"], "Só 2 títulos quitados: pouco para medir.")  # o 106 é de antes
        x = a["numeros"]
        # 28/09: 103, 104 e 105 em aberto (o vencido e o inadimplente pelo valor do título)
        self.assertEqual((x["maior_saldo"], x["maior_saldo_em"], x["em_aberto"]), (1900.0, D(2026, 9, 28), 1150.0))
        self.assertEqual((x["inadimplencia"], x["titulos_inadimplentes"], a["limite_sugerido"]), (1300.0, 1, None))
        self.assertEqual(self.credito.analisar(1, 5000)["criterios"][3]["status"], "ok")  # o mesmo limite de hoje

    def test_ja_deve_mais_que_o_pedido(self):
        a = self.credito.analisar(2, 2000)  # deve 2.500 com limite de 2.000
        self.assertEqual(self.status(a)["em_aberto"], "atencao")
        self.assertIn("R$ 2.500,00, mais que o limite pedido", a["criterios"][4]["detalhe"])

    def test_sem_historico(self):
        a = self.credito.analisar(3, 2000)  # nenhum título
        s = self.status(a)
        self.assertEqual((a["parecer"], s["tempo"], s["folga"], s["recente"], s["pontualidade"]),
                         ("nao_indicado", "atencao", "bloqueio", "atencao", "atencao"))
        self.assertEqual((a["numeros"]["maior_saldo"], a["numeros"]["pedido_vezes_maior_saldo"], a["limite_sugerido"]),
                         (0.0, None, None))
        self.assertEqual(self.credito.analisar(3, 500)["parecer"], "ressalvas")  # abaixo do limite de hoje

    def test_data_digitada_errada_fica_fora(self):
        a = self.credito.analisar(4, 1000)  # o 402 (ano 7190) não é o primeiro nem o último título
        x = a["numeros"]
        self.assertEqual((x["primeiro_titulo"], x["ultimo_titulo"], x["meses_cliente"], x["quitados"]),
                         (D(2026, 9, 5), D(2026, 9, 5), 0, 1))
        self.assertIn("há menos de um mês: cliente novo", a["criterios"][2]["detalhe"])
        self.assertEqual((x["maior_saldo"], a["limite_sugerido"], a["parecer"]), (700.0, 1500, "ressalvas"))
        # o teto de 2x é arredondado para cima (1.400 -> 1.500): o sugerido sempre passa, mesmo acima de 2x
        a = self.credito.analisar(4, 1500)
        self.assertEqual((self.status(a)["folga"], a["numeros"]["pedido_vezes_maior_saldo"] > 2), ("ok", True))
        self.assertIn("o histórico sustenta até R$ 1.500,00", a["criterios"][3]["detalhe"])
        self.assertEqual(self.status(self.credito.analisar(4, 1500.01))["folga"], "atencao")

    def test_parametros_invalidos(self):
        for cliente, limite in ((1, 0), (1, -10), (1, "abc"), (1, "nan"), (1, "inf"), (1, None), (999, 1000),
                                ("x", 1000), (None, 1000)):
            with self.assertRaises(ValueError, msg=(cliente, limite)):
                self.credito.analisar(cliente, limite)
        self.assertEqual(self.credito.analisar("1", "6000.5")["pedido"], 6000.5)  # do endereço da página

    def test_a_pagina_leva_a_regra(self):
        self.assertEqual(self.credito.calcular([1])["regra_parecer"], modulo.REGRA)


class TestBusca(Base):
    def test_busca_por_nome_e_codigo(self):
        self.assertEqual([c["id"] for c in self.credito.buscar("merc")], [1, 4])
        self.assertEqual([c["id"] for c in self.credito.buscar("Açougue")], [3])  # sem acento nem caixa
        self.assertEqual(self.credito.buscar("4")[0]["id"], 4)
        self.assertEqual([c["id"] for c in self.credito.buscar("o")], [1, 4, 3])  # quem tem títulos antes
        self.assertEqual(self.credito.buscar("  "), [])
        c = self.credito.buscar("joao")[0]
        self.assertEqual((c["nome"], c["carteira"], c["titulos"]), ("MERCADO DO JOAO", "Rubens", 6))


class TestSemParcelas(Base):
    parcelas_no_cache = False

    def test_conta_tudo_como_nao_pago_e_avisa(self):
        d = self.credito.calcular([1])
        self.assertTrue(self.calc.cache.sem_parcelas)
        self.assertEqual((d["clientes"][0]["em_aberto"], d["clientes"][0]["restante"]), (1900.0, 3100.0))
        self.assertEqual(len(d["avisos"]), 1)
        pago = {t["id"]: (t["pago"], t["parcelas"]) for t in d["titulos"]["linhas"]}
        self.assertEqual((pago[102], pago[103], pago[105]), ((500.0, 1), (0.0, 1), (0.0, 1)))
        self.assertEqual(self.ids(clientes=[1], ordem="pago", sentido="desc")[:2], [101, 106])
        p = self.credito.analisar(1, 6000)
        self.assertEqual((p["numeros"]["em_aberto"], len(p["avisos"])), (1900.0, 1))
        a = criar_assistente(self.pasta, self.calc)
        saldo = a.recorte(None, credito=True).cursor().execute(
            "SELECT saldo FROM titulos_receber WHERE id_titulo = 103").fetchone()[0]
        self.assertEqual(saldo, 1300.0)


class TestSemCredito(Base):
    credito_no_cache = False

    def test_cache_sem_as_tabelas(self):
        self.assertTrue(self.calc.cache.sem_credito)
        for conta in (lambda: self.credito.calcular([1]), lambda: self.credito.analisar(1, 6000)):
            with self.assertRaises(RuntimeError) as e:
                conta()
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
        self.assertEqual(c.execute("SELECT parcelas, parcelas_pagas, valor_pago, saldo FROM titulos_receber "
                                   "WHERE id_titulo = 103").fetchone(), (2, 1, 650.0, 650.0))
        self.assertEqual(c.execute("SELECT SUM(saldo) FROM titulos_receber WHERE id_cliente = 1").fetchone()[0], 1150.0)
        f = Ferramentas(r, self.calc, a.cfg, None, credito=a.credito)
        res, p = f.executar("credito_cliente", {"id_cliente": 1, "mes": 9})
        self.assertIsNone(p["erro"])
        pagina = self.credito.calcular([1], mes=9)
        self.assertEqual(res["compras"]["valor"], pagina["cartoes"]["valor"])
        self.assertEqual(res["cliente"]["limite_restante"], pagina["clientes"][0]["restante"])
        self.assertEqual(res["cliente"]["ja_pago_em_parcelas"], 750.0)
        abertos = {t["titulo"]: t for t in res["titulos_em_aberto"]}
        self.assertEqual(list(abertos), [105, 104, 103])
        self.assertEqual((abertos[103]["valor_ja_pago"], abertos[103]["parcelas_pagas"]), (650.0, "1 de 2"))
        self.assertNotIn("parcelas_pagas", abertos[104])
        self.assertNotIn("parecer_novo_limite", res)

    def test_parecer_de_um_limite_novo(self):
        a = criar_assistente(self.pasta, self.calc)
        # acesso só da BA: o parecer é o da página, com o histórico inteiro do cliente
        f = Ferramentas(a.recorte(a.ids_do_escopo(None, {"BA"}), credito=True), self.calc, a.cfg, {"BA"},
                        credito=a.credito)
        res, p = f.executar("credito_cliente", {"id_cliente": 1, "novo_limite": 6000})
        self.assertIsNone(p["erro"])
        x, pagina = res["parecer_novo_limite"], self.credito.analisar(1, 6000)
        self.assertEqual((x["parecer"], x["limite_pedido"], x["limite_sugerido"]), ("Não indicado", 6000.0, None))
        self.assertEqual([c["detalhe"] for c in x["criterios"]], [c["detalhe"] for c in pagina["criterios"]])
        self.assertEqual((x["criterios"][0]["criterio"], x["criterios"][0]["resultado"]), ("Inadimplência", "bloqueio"))
        self.assertEqual(x["maior_saldo_em_aberto_12_meses"], 1900.0)
        _, p = f.executar("credito_cliente", {"id_cliente": 1, "novo_limite": -5})
        self.assertIn("maior que zero", p["erro"])

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
        self.assertEqual((res["compras"]["valor"], res["cliente"]["limite_restante"]), (200.0, 3850.0))
        self.assertIn("aviso", res)

    def test_gestao_divide_o_recorte_com_credito(self):
        a = criar_assistente(self.pasta, self.calc)
        self.assertIs(a.recorte(None, credito=True), a.recorte(None, credito=True))
        self.assertIs(a._completo[1], a.recorte(None, credito=True))


if __name__ == "__main__":
    unittest.main()

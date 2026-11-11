"""Painel de desempenho da Gestão (bi/desempenho.py): as contas puras (período, expectativa diária, compras esperadas,
faixas e nota geral) e o painel sobre o cache sintético de tests/apoio.py, com os dias de atendimento no PostgreSQL.

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import unittest

from bi.calendario import Calendario
from bi.desempenho import (FAIXAS, bloco, compras_esperadas, expectativa, motivos_de_troca, nota_geral, periodo,
                           segmento_do_painel)
from bi.gestao import Gestao
from tests.apoio import BA, ES, BaseBanco
from tests.test_gestao import ComCache

D = dt.date
HOJE = D(2026, 10, 1)  # quinta: o último dia fechado é a quarta 30/09 e a semana anterior vai de 21 a 27/09


def semanas(*datas):
    return [D(2026, 12, d) for d in datas]


class TestContas(unittest.TestCase):
    def test_periodo(self):
        cal = Calendario()
        self.assertEqual(periodo(None, HOJE, cal, "ES"), {"chave": "ultimo_dia", "rotulo": "Último dia fechado",
                                                          "inicio": D(2026, 9, 30), "fim": D(2026, 9, 30)})
        # segunda: o último dia útil é a sexta; depois de um feriado (Finados, segunda 2/11), a sexta 30/10
        self.assertEqual(periodo("ultimo_dia", D(2026, 10, 5), cal, "ES")["fim"], D(2026, 10, 2))
        self.assertEqual(periodo("ultimo_dia", D(2026, 11, 3), cal, "BA")["fim"], D(2026, 10, 30))
        p = periodo("semana", HOJE, cal, "ES")
        self.assertEqual((p["inicio"], p["fim"]), (D(2026, 9, 21), D(2026, 9, 27)))
        self.assertEqual(periodo("semana", D(2026, 9, 28), cal, "ES")["inicio"], D(2026, 9, 21))  # numa segunda
        self.assertEqual(periodo(" HOJE ", HOJE, cal, "ES")["fim"], HOJE)
        with self.assertRaises(ValueError):
            periodo("mes", HOJE, cal, "ES")

    def test_compras_esperadas(self):
        segundas = semanas(7, 14, 21, 28)
        # semanal: uma por semana; o cliente de terça que comprou na segunda 30/11 não espera na terça 1º/12
        self.assertEqual(compras_esperadas(segundas, 1, None), 4)
        self.assertEqual(compras_esperadas(semanas(1, 8, 15, 22, 29), 1, D(2026, 11, 30)), 4)
        self.assertEqual(compras_esperadas(semanas(1, 8, 15, 22, 29), 1, D(2026, 11, 27)), 5)  # sexta: outra semana
        # área de dois dias (segunda e terça): uma visita por semana
        self.assertEqual(compras_esperadas(semanas(7, 8, 14, 15), 1, None), 2)
        # quinzenal numa área de terça e quarta, com a última compra na terça 24/11: 8 e 22/12 (com um dia de cada
        # vez, a quarta voltava oito dias depois: 2, 15 e 23/12)
        self.assertEqual(compras_esperadas(semanas(1, 2, 8, 9, 15, 16, 22, 23, 29, 30), 2, D(2026, 11, 24)), 2)
        # quinzenal: comprou em 30/11 -> 14 e 28/12; em 16/11 -> 7 e 21/12; sem compra -> 7 e 21/12
        self.assertEqual(compras_esperadas(segundas, 2, D(2026, 11, 30)), 2)
        self.assertEqual(compras_esperadas(segundas, 2, D(2026, 11, 16)), 2)
        self.assertEqual(compras_esperadas(segundas, 2, None), 2)
        nov = [D(2026, 11, d) for d in (2, 9, 16, 23, 30)]  # 5 segundas: 2 ou 3, conforme onde parou
        self.assertEqual(compras_esperadas(nov, 2, D(2026, 10, 19)), 3)  # 2, 16 e 30
        self.assertEqual(compras_esperadas(nov, 2, D(2026, 10, 26)), 2)  # 9 e 23
        # mensal: a cada 4 semanas (sem compra nos 21 dias antes); atendido no dia 2, volta no dia 30
        self.assertEqual(compras_esperadas(segundas, 4, D(2026, 11, 16)), 1)  # 14/12
        self.assertEqual(compras_esperadas(nov, 4, None), 2)
        self.assertEqual(compras_esperadas([], 1, None), 0)

    def test_expectativa(self):
        pot = {D(2026, 9, 4): 100.0, D(2026, 9, 11): 100.0, D(2026, 9, 18): 300.0}
        uteis = {D(2026, 9, d): 1.0 for d in (4, 10, 11, 18, 21)}
        # saldo 1000 em 3 sextas pelo potencial delas (100, 100, 300): a primeira leva 1000 × 100/500
        e = expectativa(1000, 0.0, 0.0, pot, uteis, D(2026, 9, 4))
        self.assertEqual((e["meta"], e["modo"], e["saldo"]), (200.0, "saldo", 1000.0))
        # quem está atrasado tem a meta do dia maior; os pedidos em aberto entram no saldo
        e = expectativa(1000, 100.0, 300.0, pot, uteis, D(2026, 9, 18))
        self.assertEqual((e["meta"], e["saldo"]), (600.0, 600.0))
        # caminho B: a parte do saldo abaixo do potencial normal vale o potencial
        e = expectativa(1000, 950.0, 0.0, pot, uteis, D(2026, 9, 11))
        self.assertEqual((e["meta"], e["modo"], e["parte"]), (100.0, "potencial", 12.5))
        # meta batida: o potencial normal; dia sem cliente programado: zero
        self.assertEqual(expectativa(1000, 1200.0, 0.0, pot, uteis, D(2026, 9, 18))["meta"], 300.0)
        self.assertEqual(expectativa(1000, 0.0, 0.0, pot, uteis, D(2026, 9, 10))["meta"], 0.0)
        # sem dia de atendimento pela frente: o saldo pelos dias úteis que restam
        e = expectativa(1000, 0.0, 0.0, pot, uteis, D(2026, 9, 21))
        self.assertEqual((e["meta"], e["modo"]), (1000.0, "sem_rota"))
        self.assertEqual(expectativa(0, 0.0, 0.0, pot, uteis, D(2026, 9, 4))["modo"], "sem_meta")

    def test_faixas_e_nota(self):
        self.assertEqual(bloco(100, 100)["status"], "batida")
        self.assertEqual(bloco(90, 100)["status"], "atencao")
        self.assertEqual(bloco(89.9, 100)["status"], "abaixo")
        self.assertEqual(bloco(10, 0)["status"], "sem_meta")
        self.assertEqual(bloco(None, 10)["status"], "sem_dados")
        # troca: verde até 1,0%, amarelo até 1,5%; o % é quanto do teto foi usado
        self.assertEqual(bloco(0.010, 0.015, invertido=True)["status"], "batida")
        self.assertEqual(bloco(0.012, 0.015, invertido=True)["status"], "atencao")
        t = bloco(0.03, 0.015, invertido=True)
        self.assertEqual(t["status"], "abaixo")
        self.assertAlmostEqual(t["pct"], 2.0)
        v = {"dia": {k: bloco(None, None) for k in ("atendimentos", "faturamento", "mussarela", "outras")},
             "mes": {k: bloco(None, None) for k in ("positivacao", "ticket", "frequencia", "efetividade", "troca")}}
        self.assertIsNone(nota_geral(v))
        v["dia"]["faturamento"] = bloco(300, 100)                         # conta no máximo 150%
        v["mes"]["positivacao"] = bloco(50, 100)
        v["mes"]["troca"] = bloco(0.03, 0.015, invertido=True)            # teto estourado: zero, não negativo
        self.assertAlmostEqual(nota_geral(v), (1.5 + 0.5 + 0.0) / 3)
        self.assertEqual(FAIXAS, {"verde": 1.0, "amarelo": 0.9})

    def test_segmento_do_painel(self):
        casos = {"SUPERMERCADO": "REDES", "MERCADO (4 A 6 CAIXAS)": "MERCADO", "MERCEARIA (1 A 3 CAIXAS)": "MERCADO",
                 "AÇOUGUE": "MERCADO", "ATACADO": "MERCADO", "PADARIA": "PADARIAS", "RESTAURANTE": "FOOD",
                 "CAFETERIA E LANCHONETE": "FOOD", "HOTEL E POUSADA": "FOOD", "HOSPITAIS E PREFEITURAS": "FOOD",
                 "FÁBRICA DE SALGADO": "FOOD", "CHURRASCARIA": "FOOD", "OUTROS": "OUTROS", "": "OUTROS", None: "OUTROS"}
        for segmento, esperado in casos.items():
            self.assertEqual(segmento_do_painel(segmento), esperado, segmento)

    def test_motivos_de_troca(self):
        motivos = [(1, "ERRO DE LANÇAMENTO"), (3, "VENCIDO"), (4, "DANIFICADO NO CLIENTE"), (16, "BRINDE - VENCIDO"),
                   (22, "PERDA - VENCIDO NA CÂMARA"), (10, "Brinde – danificado, problema na produção")]
        self.assertEqual(motivos_de_troca(motivos), {3, 4, 10, 16})


# Pedidos um a um (id, data, criado, entrega, cliente, tipo, vendedor, tipo do pedido, status, nome do status, cancelado,
# origem, venda, brinde, nota, total, desconto, peso)
def pedido(id_, dia, total, status="L", tipo="PEDIDOVENDA", cancelado=False, venda=None):
    return (id_, D(2026, 9, dia), None, None, 1, "CLIENTE", ES, tipo, status, "", cancelado, "APP", venda, None, None,
            total, 0.0, 0.0)


PEDIDOS = [
    pedido(1, 29, 200.0),                        # em aberto, há 1 dia: desconta do saldo de 30/09
    pedido(2, 28, 300.0, status="V", venda=77),  # virou nota: já está no faturado
    pedido(3, 28, 100.0, cancelado=True),
    pedido(4, 21, 400.0),                        # 9 dias antes de 30/09: fica fora; na semana, conta na sexta 25/09
    pedido(5, 29, 50.0, status="B", tipo="PEDIDOBRINDE"),
    pedido(6, 30, 60.0),                         # do próprio dia: não é saldo da véspera
]


class TestPainel(ComCache, BaseBanco):
    def setUp(self):
        super().setUp()
        self.chefe = {"id": self.criar_usuario("chefe", "admin"), "login": "chefe", "nome": "Chefe", "papel": "admin"}

    def tearDown(self):
        self.desmontar_cache()
        super().tearDown()

    def montar(self, **opcoes):
        self.montar_cache(extras=True, **opcoes)
        self.gestao = Gestao(self.banco, self.calc, self.assistente, hoje=lambda: HOJE)
        self.gestao.definir_areas(self.chefe, {1: [3], 2: [4], 3: [5]})

    def painel(self, regiao="ES", periodo="ultimo_dia", escopo=(None, None)):
        return self.gestao.desempenho(self.chefe, escopo, regiao, periodo)

    def test_ultimo_dia_fechado(self):
        self.montar(linhas_brindes=[(D(2026, 9, 5), 0, 1, "CLIENTE", 32, 3, 30.0, 1.0)])
        d = self.painel()
        self.assertEqual((d["regiao"], d["periodo"]["inicio"], d["periodo"]["fim"]), ("ES", "2026-09-30", "2026-09-30"))
        self.assertEqual([p["chave"] for p in d["periodos"]], ["ultimo_dia", "semana", "hoje"])
        rubens, = d["vendedores"]
        dia, mes = rubens["dia"], rubens["mes"]
        # a quarta 30/09 não é dia das sextas de potencial: o saldo (2000 − 1480) vai para o único dia útil que resta
        self.assertEqual((dia["faturamento"]["real"], dia["faturamento"]["meta"]), (0.0, 520.0))
        self.assertEqual(rubens["expectativa"][0]["modo"], "sem_rota")
        self.assertEqual((dia["mussarela"]["meta"], dia["outras"]["meta"]), (208.0, 312.0))  # 800 e 1200 de 2000
        self.assertEqual((dia["atendimentos"]["real"], dia["atendimentos"]["meta"]), (0, 2))  # clientes 1 e 3, quarta
        # o mês: o realizado da página Metas
        self.assertEqual((mes["faturamento"]["real"], mes["faturamento"]["meta"]), (1480.0, 2000.0))
        self.assertEqual((mes["mussarela"]["real"], mes["outras"]["real"]), (980.0, 500.0))
        self.assertEqual((mes["positivacao"]["real"], mes["positivacao"]["meta"], mes["positivacao"]["status"]),
                         (3, 3.0, "batida"))
        self.assertEqual((mes["ticket"]["real"], mes["ticket"]["meta"]), (493.33, 666.67))
        # efetividade das campanhas (1 pedido em 9 dias com 2 visitas), meta de 100%
        self.assertEqual((mes["efetividade"]["real"], mes["efetividade"]["meta"], mes["efetividade"]["dias"]),
                         (round(0.5 / 9, 4), 1.0, 9))
        # frequência: 2 semanas com compra de 2 clientes; a meta, as 5 quartas de setembro de cada um
        self.assertEqual((mes["frequencia"]["real"], mes["frequencia"]["meta"]), (1.0, 5.0))
        # troca: R$ 50 de devolução vencida + R$ 30 de brinde vencido sobre o bruto da carteira (1300 + 200 + 80)
        self.assertEqual((mes["troca"]["valor"], mes["troca"]["base"]), (80.0, 1580.0))
        self.assertAlmostEqual(mes["troca"]["real"], 80 / 1580, places=5)
        self.assertEqual(mes["troca"]["status"], "abaixo")
        self.assertEqual(rubens["programacao"], {"clientes": 4, "sem_programacao": 0, "potencial_mes": 655.0})
        self.assertIsNotNone(rubens["nota"])
        self.assertEqual(d["totais"]["periodo"]["meta"], 520.0)
        self.assertEqual(d["totais"]["mes"]["real"], 1480.0)

    def test_semana_e_pedidos_em_aberto(self):
        self.montar(linhas_pedidos_detalhe=PEDIDOS)
        rubens, = self.painel()["vendedores"]
        e = rubens["expectativa"][0]
        self.assertEqual((e["abertos"], e["saldo"], e["meta"]), (200.0, 320.0, 320.0))  # só o pedido 1
        semana = self.painel(periodo="semana")
        rubens, = semana["vendedores"]
        por_dia = {x["data"]: x for x in rubens["expectativa"]}
        self.assertEqual(len(por_dia), 7)
        self.assertEqual(sum(1 for x in por_dia.values() if x["meta"]), 1)  # só a sexta tem cliente programado
        # sexta 25/09: saldo 520 − 400 do pedido de 21/09 = 120, abaixo do potencial da sexta (655 ÷ 4): vale ele
        sexta = por_dia["2026-09-25"]
        self.assertEqual((sexta["saldo"], sexta["modo"], sexta["meta"]), (120.0, "potencial", 163.75))
        self.assertEqual(rubens["dia"]["faturamento"]["meta"], 163.75)

    def test_meta_por_volume_no_ba(self):
        self.montar()
        thais, = self.painel("BA")["vendedores"]
        # 300 kg da meta × o preço de agosto dela (4000 ÷ 200), ajustado à meta de faturamento: toda em mussarela
        self.assertEqual(thais["regime"], "volume")
        self.assertEqual((thais["mes"]["mussarela"]["meta"], thais["mes"]["outras"]["meta"]), (6000.0, None))
        self.assertEqual(thais["mes"]["mussarela"]["real"], 4750.0)  # 5000 − 250 (o 999 é "não conta")

    def test_hoje_e_sem_meta_no_mes(self):
        self.montar()
        d = self.painel(periodo="hoje")
        rubens, = d["vendedores"]  # sem meta em outubro: a equipe do mês das metas, sem comparação
        self.assertEqual(d["periodo"]["fim"], "2026-10-01")
        self.assertEqual((rubens["dia"]["faturamento"]["status"], rubens["mes"]["faturamento"]["status"]),
                         ("sem_meta", "sem_meta"))
        self.assertEqual(d["copia"], "2026-10-01T07:00")

    def test_atendimento_conta_o_cliente_uma_vez(self):
        from bi.indicadores import _efetividade
        # o cliente 1 faz dois pedidos na quarta 2/9: a efetividade conta 2 pedidos; o atendimento, 1 cliente
        self.montar(pedidos_extras=[(D(2026, 9, 2), ES, 1, "CLIENTE", "PEDIDOVENDA", 0, 1, 40.0)])
        areas = {1: [3], 2: [4], 3: [5]}
        dia = D(2026, 9, 2)
        pedidos = _efetividade(self.cur, {"filtros": {}}, [ES], dia, dia, areas)["vend"][ES]
        clientes = _efetividade(self.cur, {"filtros": {}}, [ES], dia, dia, areas, distintos=True)["vend"][ES]
        self.assertEqual((pedidos["num"], pedidos["den"]), (2.0, 2.0))
        self.assertEqual((clientes["num"], clientes["den"]), (1.0, 2.0))

    def test_ticket_do_periodo(self):
        self.montar()
        self.gestao.hoje = lambda: D(2026, 9, 4)  # o último dia fechado é a quinta 3/9, dia da rota da Thais
        thais, = self.painel("BA")["vendedores"]
        dia = thais["dia"]
        # meta do dia: saldo 6000 × o potencial da quinta (2185 ÷ 4) ÷ o potencial do mês (2185) = 1500
        self.assertEqual((dia["faturamento"]["real"], dia["faturamento"]["meta"]), (5000.0, 1500.0))
        self.assertEqual((dia["atendimentos"]["real"], dia["atendimentos"]["meta"]), (1, 2))
        # ticket: 5000 ÷ 1 cliente com nota, contra a meta do dia ÷ os 2 clientes esperados
        t = dia["ticket"]
        self.assertEqual((t["real"], t["meta"], t["clientes"], t["esperados"]), (5000.0, 750.0, 1, 2))
        self.assertEqual(t["status"], "batida")

    def test_meta_do_dia_na_pagina_metas(self):
        self.montar()
        self.calc.expectativa = self.gestao.expectativa_do_dia
        self.calc.cache.info["data_ref"] = "2026-09-16"  # setembro ainda aberto
        self.gestao.hoje = lambda: D(2026, 9, 17)        # quinta: dia da rota da Thais
        ba = self.calc.visao("ba", [(2026, 9)])
        thais, = ba["linhas"]
        # saldo 6000 − 4750 = 1250 pelas duas quintas que restam (546,25 cada): 625 em 17/9
        self.assertEqual((thais["faturamento"]["meta_dia"], thais["faturamento"]["meta_dia_data"]), (625.0, "2026-09-17"))
        self.assertIsNone(thais["faturamento"]["falta_por_dia"])
        self.assertEqual((thais["mussarela"]["meta_dia"], thais["outras"]["meta_dia"]), (625.0, 0.0))
        self.assertEqual((ba["indicadores"]["faturamento"]["meta_dia"], ba["indicadores"]["faturamento"]["meta_dia_data"]),
                         (625.0, "2026-09-17"))
        self.assertIsNotNone(ba["indicadores"]["clientes"]["falta_por_dia"])  # clientes seguem com a conta de antes
        self.assertNotIn("meta_dia", ba["indicadores"]["clientes"])
        # o Rubens não atende na quinta: meta do dia zero
        es = self.calc.visao("es", [(2026, 9)])
        self.assertEqual(es["linhas"][0]["faturamento"]["meta_dia"], 0.0)
        # outro mês (ou sem dar para calcular): a conta de antes
        self.assertNotIn("meta_dia", self.calc.visao("ba", [(2026, 8)])["indicadores"]["faturamento"])
        self.calc.expectativa = lambda ids, meses: None
        self.assertIsNotNone(self.calc.visao("ba", [(2026, 9)])["indicadores"]["faturamento"]["falta_por_dia"])

    def test_simulacao(self):
        import tempfile
        from pathlib import Path
        from bi.simulacao import gravar_planilha, texto
        self.montar()
        r = self.gestao.simular("thais", 10000, None, D(2026, 9, 17))
        self.assertEqual((r["vendedor"]["id"], r["vendedor"]["regiao"], r["vendedor"]["regime"]), (BA, "BA", "volume"))
        self.assertEqual((r["meta"], r["meta_planilha"], r["faturado_ate_hoje"], r["saldo_hoje"]),
                         (10000.0, 6000.0, 4750.0, 5250.0))
        dias = {d["data"]: d for d in r["dias"]}
        # antes de hoje, com o realizado: 10000 × 546,25 ÷ 2185 = 2500 em 3/9; em 10/9, 5000 pelas 3 quintas
        self.assertEqual((dias["2026-09-03"]["meta"], dias["2026-09-03"]["projecao"]), (2500.0, False))
        self.assertEqual(dias["2026-09-10"]["meta"], 1666.67)
        # de hoje em diante, a projeção distribui o saldo de hoje pelas quintas que restam
        self.assertEqual((dias["2026-09-17"]["meta"], dias["2026-09-24"]["meta"]), (2625.0, 2625.0))
        self.assertTrue(dias["2026-09-24"]["projecao"])
        self.assertEqual(dias["2026-09-17"]["clientes"], 2)
        clientes = {c["id"]: c for c in r["clientes"]}
        self.assertEqual((clientes[2]["potencial"], clientes[2]["representatividade"]), (2000.0, round(2000 / 2185, 6)))
        self.assertEqual(len(clientes[2]["dias"]), 4)
        self.assertIsNone(clientes[7]["representatividade"])  # sem área: fora da conta
        # cenário: e se ela tivesse faturado 8000 até ontem?
        r = self.gestao.simular("141", 10000, None, D(2026, 9, 17), faturado=8000)
        dias = {d["data"]: d for d in r["dias"]}
        self.assertEqual((r["saldo_hoje"], dias["2026-09-17"]["meta"], dias["2026-09-24"]["meta"]),
                         (2000.0, 1000.0, 1000.0))
        self.assertIn("Soma da projeção de hoje em diante: R$ 2.000,00", texto(r))
        with tempfile.TemporaryDirectory() as pasta:
            self.assertTrue(gravar_planilha(r, Path(pasta) / "sim.xlsx").exists())
        with self.assertRaises(ValueError):
            self.gestao.simular("ninguem")

    def test_evolucao_mensal(self):
        self.montar()
        d = self.gestao.evolucao(self.chefe, (None, None), "ES")
        self.assertEqual((d["regiao"], d["vendedor"], [v["id"] for v in d["vendedores"]]), ("ES", None, [ES]))
        meses = {m["mes"]: m for m in d["meses"]}
        self.assertEqual((len(d["meses"]), d["meses"][0]["mes"], d["meses"][-1]["mes"]), (12, "2025-11-01", "2026-10-01"))
        s = meses["2026-09-01"]
        self.assertEqual((s["faturamento"], s["meta"], s["atingimento"], s["vendedores"]), (1480.0, 2000.0, 0.74, 1))
        self.assertEqual((s["clientes"], s["meta_clientes"], s["positivacao"], s["ticket"]), (3, 3.0, 1.0, 493.33))
        self.assertEqual((s["frequencia"], s["troca_valor"], s["bruto"]), (1.0, 50.0, 1580.0))
        # a pizza: mercado e açougue em MERCADO; a venda ao funcionário em OUTROS; soma o faturamento
        self.assertEqual(s["segmentos"], {"FOOD": 0.0, "PADARIAS": 0.0, "REDES": 0.0, "MERCADO": 1400.0, "OUTROS": 80.0})
        self.assertAlmostEqual(sum(s["segmentos"].values()), s["faturamento"])
        self.assertTrue(meses["2026-10-01"]["futuro"])           # sem dados ainda
        self.assertEqual(meses["2026-08-01"]["vendedores"], 0)   # ninguém com meta em agosto
        # um vendedor: todos os meses dele, com ou sem meta
        d = self.gestao.evolucao(self.chefe, (None, None), "BA", BA)
        meses = {m["mes"]: m for m in d["meses"]}
        self.assertEqual(d["vendedor"], {"id": BA, "nome": "Thais"})
        self.assertEqual((meses["2026-07-01"]["faturamento"], meses["2026-07-01"]["meta"]), (370.0, None))
        self.assertEqual(meses["2026-09-01"]["segmentos"]["PADARIAS"], 4750.0)
        with self.assertRaises(ValueError):  # o Rubens é do ES
            self.gestao.evolucao(self.chefe, (None, None), "BA", ES)
        with self.assertRaises(PermissionError):
            self.gestao.evolucao(self.chefe, ({BA}, None), "BA", 85)

    def test_evolucao_projeta_o_mes_em_andamento(self):
        self.montar()
        self.calc.cache.info["data_ref"] = "2026-09-15"
        self.gestao.hoje = lambda: D(2026, 9, 16)
        s = self.gestao.evolucao(self.chefe, (None, None), "ES")["meses"][-1]
        # 10 dos 21 dias úteis de setembro no ES: 1480 ÷ 10 × 21 = 3108
        self.assertEqual((s["mes"], s["parcial"], s["projecao"], s["atingimento_projetado"]),
                         ("2026-09-01", True, 3108.0, 1.554))

    def test_acesso_e_dados_que_faltam(self):
        self.montar()
        d = self.painel(escopo=({ES}, None))
        self.assertEqual(d["regioes"], ["ES"])
        with self.assertRaises(PermissionError):
            self.painel("BA", escopo=({ES}, None))
        with self.assertRaises(ValueError):
            self.painel(periodo="ontem")
        self.calc.cache.sem_pedidos = True
        self.calc.cache.sem_pedidos_detalhe = True
        d = self.painel("BA", periodo="semana")
        thais, = d["vendedores"]
        self.assertEqual((thais["dia"]["atendimentos"]["status"], thais["mes"]["efetividade"]["status"]),
                         ("sem_dados", "sem_dados"))
        self.assertTrue(any("pedidos de venda" in a for a in d["avisos"]))
        self.assertTrue(any("pedidos um a um" in a for a in d["avisos"]))


if __name__ == "__main__":
    unittest.main()

"""Página Gestão (bi/gestao.py): os indicadores sobre o cache sintético, a conferência do que vem da página ou do
Assistente, a base, o alvo e o resultado das ações, as ações e os objetivos no PostgreSQL e as ferramentas de ações
do Assistente.

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from bi.assistente import FERRAMENTAS, Ferramentas
from bi.conversas import Conversas, NaoEncontrada
from bi.gestao import (Gestao, alvo_de, andamento, calendario_periodo, classe_resultado, comparar, prazo,
                       rotulo_padrao, situacao, texto_alvo, validar)
from bi.indicadores import descritor
from tests.apoio import (BA, EDIR, ES, USUARIO_ADMIN, USUARIO_VIS, BaseBanco, ClienteFalso, ConversasFalsas,
                         bloco_ferramenta, bloco_texto, criar_assistente, criar_calc, resposta)

D = dt.date
SETEMBRO = {"inicio": D(2026, 9, 1), "fim": D(2026, 9, 30)}


class ComCache:
    """O cache sintético de tests/apoio.py (setembro de 2026 fechado) e o recorte com todos os vendedores."""

    def montar_cache(self, extras=False):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.calc = criar_calc(self.pasta, fora=(999,), extras=extras)
        self.assistente = criar_assistente(self.pasta, self.calc)
        self.cur = self.assistente.recorte(None).cursor()
        self.regras = self.calc.regras()
        self.cal = self.calc.calendario(self.regras)

    def desmontar_cache(self):
        self.cur.close()
        self.calc.cache._con.close()
        self._tmp.cleanup()

    def campanha(self, metrica="faturamento", filtros=None, meta=0.0, vendedores=None, **datas):
        return {**SETEMBRO, **datas, "metrica": metrica, "filtros": filtros or {}, "meta_padrao": meta,
                "vendedores": vendedores or [{"id": ES, "meta": None}, {"id": BA, "meta": None}, {"id": EDIR, "meta": None}]}

    def realizado(self, campanha, permitidos=None, data_ref=D(2026, 9, 30)):
        a = andamento(self.cur, campanha, self.regras, self.cal, data_ref, permitidos)
        return {v["id"]: v["realizado"] for v in a["vendedores"]}, a


class TestAndamento(ComCache, unittest.TestCase):
    def setUp(self):
        self.montar_cache()

    def tearDown(self):
        self.desmontar_cache()

    def test_metricas(self):
        # faturamento líquido como nas metas (ES: 1000+300+200+80−100; BA: 5000−250; o produto 999 fica fora)
        self.assertEqual(self.realizado(self.campanha())[0], {ES: 1480, BA: 4750, EDIR: 700})
        # positivação: clientes do cadastro (a venda ao funcionário 7 não conta)
        r, a = self.realizado(self.campanha("positivacao"))
        self.assertEqual(r, {ES: 2, BA: 1, EDIR: 1})
        self.assertEqual(a["total"]["distintos"], 4)
        r, a = self.realizado(self.campanha("mix"))
        self.assertEqual(r, {ES: 3, BA: 1, EDIR: 1})  # ES: 32, 27 e 11469 (o 3643 equivalente)
        self.assertEqual(a["total"]["distintos"], 3)
        r, a = self.realizado(self.campanha("volume", {"produtos": [32]}))
        self.assertEqual(r, {ES: 49, BA: 238, EDIR: 35})  # devolução que desconta sai da quantidade
        self.assertEqual(a["unidade"], "KG")
        self.assertEqual(self.realizado(self.campanha(filtros={"ufs": ["ES"]}))[0], {ES: 1400, BA: 0, EDIR: 0})
        self.assertEqual(self.realizado(self.campanha(filtros={"grupos": ["outras"]}))[0][ES], 500)

    def test_metas_status_e_total(self):
        c = self.campanha(meta=1000, vendedores=[{"id": ES, "meta": None}, {"id": BA, "meta": 5000},
                                                 {"id": EDIR, "meta": 0}])
        _, a = self.realizado(c)
        por = {v["id"]: v for v in a["vendedores"]}
        self.assertEqual((por[ES]["meta"], por[ES]["status"], por[ES]["meta_individual"]), (1000, "batida", False))
        self.assertEqual((por[BA]["meta"], por[BA]["status"], por[BA]["meta_individual"]), (5000, "atencao", True))
        self.assertEqual(por[EDIR]["status"], "sem_meta")  # meta 0 = só ranking para esse vendedor
        self.assertEqual([v["id"] for v in a["vendedores"]], [ES, BA, EDIR])  # pelo % atingido
        t = a["total"]
        self.assertEqual((t["meta"], t["realizado"], t["bateram"], t["com_meta"]), (6000, 6930, 1, 2))
        self.assertAlmostEqual(t["pct"], (1480 + 4750) / 6000)
        self.assertEqual(a["situacao"], "fechado")

    def test_ritmo_no_meio_da_campanha(self):
        c = self.campanha(meta=3000, fim=D(2026, 10, 31))
        _, a = self.realizado(c)
        self.assertEqual(a["situacao"], "aberto")
        self.assertEqual(set(a["calendarios"]), {"ES", "BA"})  # Edir segue o calendário da BA
        self.assertAlmostEqual(a["calendarios"]["ES"]["ritmo"], 0.5, places=2)
        self.assertEqual(a["total"]["status"], "no_ritmo")
        self.assertEqual(a["periodo"]["ate"], "2026-09-30")
        # campanha que ainda não começou: tudo zero, sem período apurado
        r, a = self.realizado(self.campanha(inicio=D(2026, 11, 1), fim=D(2026, 11, 30), meta=10))
        self.assertEqual(r, {ES: 0, BA: 0, EDIR: 0})
        self.assertEqual((a["situacao"], a["periodo"]["ate"]), ("futuro", None))

    def test_so_os_vendedores_do_acesso(self):
        r, a = self.realizado(self.campanha(), permitidos=frozenset({ES}))
        self.assertEqual(r, {ES: 1480})
        self.assertEqual(a["ocultos"], 2)

    def test_calendario(self):
        c = calendario_periodo(self.cal, D(2026, 9, 1), D(2026, 9, 30), "ES", D(2026, 9, 15))
        self.assertEqual(c["situacao"], "aberto")
        self.assertEqual(c["dias_uteis"], 21)  # setembro de 2026 no ES: 22 dias de semana menos o 7 de setembro
        self.assertLess(c["dias_decorridos"], c["dias_uteis"])


class TestFuncoes(unittest.TestCase):
    """Base, alvo, resultado e prazo das ações (sem cache nem banco)."""

    MIX = descritor("mix_medio", {"clientes": "todos"})
    FAT = descritor("personalizada", {"medida": "faturamento", "forma": "total"})
    POS = descritor("positivacao", {"clientes": "todos"})
    EFE = descritor("efetividade", {})

    def test_alvo(self):
        self.assertAlmostEqual(alvo_de("mais", self.MIX, 4.4, 1), 5.4)
        self.assertAlmostEqual(alvo_de("pct", self.FAT, 4000, 10), 4400)
        self.assertIsNone(alvo_de("pct", self.FAT, 0, 10))  # +10% sobre nada não é alvo
        self.assertIsNone(alvo_de("mais", self.MIX, None, 1))  # base pendente ou sem divisor
        self.assertEqual(alvo_de("pct", self.POS, 7, 10), 8)  # 7,7 clientes: arredonda para cima
        self.assertEqual(alvo_de("mais", self.POS, 2, 1), 3)
        self.assertAlmostEqual(alvo_de("mais", self.EFE, 0.2, 5), 0.25)  # nos percentuais, +N é em pontos
        self.assertAlmostEqual(alvo_de("fixo", self.EFE, 0.2, 80), 0.8)
        self.assertEqual(alvo_de("fixo", self.FAT, None, 5000), 5000)  # fixo não depende da base
        self.assertEqual(alvo_de("fixo", descritor("preco_medio", {}), 0.9, 100), 1.0)

    def test_resultado(self):
        self.assertEqual(comparar(4750, 4000, 5000), {"classe": "mid", "delta": 750, "delta_pct": 0.1875, "caminho": 0.75})
        self.assertEqual(classe_resultado(5000, 4000, 5000), "ok")
        self.assertEqual(classe_resultado(4999.99, 4000, 5000), "ok")  # com a precisão da página
        self.assertEqual(classe_resultado(3900, 4000, 5000), "bad")
        self.assertEqual(classe_resultado(4000, 4000, 5000), "bad")  # ficar na base não é melhorar
        self.assertEqual(classe_resultado(None, 4000, 5000), "sem_dados")
        self.assertEqual(classe_resultado(2, None, None), "sem_alvo")
        self.assertEqual(comparar(2, 0, 1)["delta_pct"], None)  # sem % sobre base zero

    def test_situacao_e_prazo(self):
        acao = {"tipo": "acao", "inicio": D(2026, 9, 1), "fim": D(2026, 9, 21)}
        self.assertEqual([situacao(acao, D(2026, 9, d)) for d in (1, 21, 22)], ["em_vigor", "em_vigor", "encerrada"])
        self.assertEqual(situacao(acao, D(2026, 8, 31)), "planejada")
        self.assertEqual(situacao({**acao, "encerrada_em": "2026-09-10T10:00:00"}, D(2026, 9, 10)), "encerrada")
        self.assertEqual(prazo(acao, D(2026, 9, 16)), {"dias": 21, "faltam": 5, "comeca_em": 0, "decorrido": 0.75})
        self.assertEqual(prazo(acao, D(2026, 8, 29))["comeca_em"], 3)
        self.assertEqual(prazo(acao, D(2026, 10, 1))["faltam"], 0)

    def test_textos(self):
        self.assertEqual(texto_alvo("mais", 1, self.MIX), "+1 sobre a base de cada um")
        self.assertEqual(texto_alvo("mais", 0.5, self.MIX), "+0,5 sobre a base de cada um")
        self.assertEqual(texto_alvo("pct", 10, self.FAT), "+10% sobre a base de cada um")
        self.assertEqual(texto_alvo("mais", 5, self.EFE), "+5 p.p. sobre a base de cada um")
        self.assertEqual(rotulo_padrao("mix_medio", {}), "Mix")
        self.assertEqual(rotulo_padrao("personalizada", {"medida": "faturamento", "forma": "por_cliente"}), "Venda média")


class TestIndicadores(ComCache, unittest.TestCase):
    """Os tipos de campanha de bi/indicadores.py com o cache de tests/apoio.py mais os extras (julho e pedidos)."""

    AREAS = {1: [3], 2: [4]}  # ROTA 1 na quarta, ROTA 2 na quinta; ROTA 3 pendente

    def setUp(self):
        self.montar_cache(extras=True)

    def tearDown(self):
        self.desmontar_cache()

    def medir(self, metrica, parametros=None, filtros=None, meta=0.0, data_ref=D(2026, 9, 30), abrir=None, **extra):
        c = {**self.campanha(metrica, filtros, meta, **{k: v for k, v in extra.items() if k in ("inicio", "fim")}),
             "parametros": parametros or {}, "metas_produto": extra.get("metas_produto")}
        a = andamento(self.cur, c, self.regras, self.cal, data_ref, None, extra.get("areas", self.AREAS), abrir)
        return {v["id"]: v for v in a["vendedores"]}, a

    def test_efetividade(self):
        por, a = self.medir("efetividade", meta=30, abrir="padrao")
        # a média da efetividade de cada dia com visita. ES: 2 clientes da ROTA 1 em cada uma das 5 quartas, com 1
        # pedido na 1ª (2/9): 0,5 ÷ 5 dias. O pedido da terça (15/9) fica fora (dia sem visita), e o cancelado, o
        # orçamento, o da área sem dia e o de funcionário não contam. BA: 2 visitas em cada uma das 4 quintas, com
        # pedido em 3 delas (um do bloqueado e um feito pelo ES na carteira dela): 1,5 ÷ 4 dias
        self.assertEqual({v: (x["numerador"], x["denominador"], x["dias"], x["realizado"]) for v, x in por.items()},
                         {ES: (1, 10, 5, 0.1), BA: (3, 8, 4, 0.375), EDIR: (0, 0, 0, None)})
        self.assertEqual((por[ES]["meta"], por[ES]["status"], por[BA]["status"], por[EDIR]["status"]),
                         (0.3, "abaixo", "batida", "sem_dados"))
        self.assertAlmostEqual(a["total"]["realizado"], 2 / 9, places=4)  # 9 dias com visita: 0,5 + 3 × 0,5
        self.assertEqual((a["total"]["numerador"], a["total"]["denominador"], a["total"]["dias"]), (4, 18, 9))
        self.assertEqual({x["nome"]: (x["valor"], x["dias"]) for x in a["abertura"]["linhas"]},
                         {"ROTA 1": (0.1, 5), "ROTA 2": (0.375, 4)})
        self.assertIn("4 clientes ativos da carteira ficaram fora", a["avisos"][0])  # ROTA 3 (2) e sem área (2)
        self.assertEqual((a["indicador"]["formato"], a["indicador"]["media_diaria"]), ("pct", True))
        por, _ = self.medir("efetividade", meta=30, data_ref=D(2026, 9, 15))
        self.assertEqual({v: por[v]["realizado"] for v in (ES, BA)}, {ES: 0.25, BA: 0.5})  # 2 quartas e 2 quintas
        self.assertEqual(por[BA]["status"], "no_ritmo")  # aberto: na meta é "no ritmo", não "batida"

    def test_efetividade_media_dos_dias(self):
        # ROTA 1 na terça e na quarta, ROTA 3 (os 2 hotéis do ES) na quarta: 2 visitas nas terças e 4 nas quartas
        por, _ = self.medir("efetividade", meta=30, areas={1: [2, 3], 2: [4], 3: [3]})
        es = por[ES]
        # 15/9 (terça): 1 ÷ 2; 2/9 (quarta): 1 ÷ 4; os outros 8 dias, zero: (0,5 + 0,25) ÷ 10 dias = 7,5%. Pedidos do
        # período ÷ visitas do período dariam 2 ÷ 30; com o pedido do sábado (5/9, dia sem visita), 3 ÷ 30
        self.assertEqual((es["numerador"], es["denominador"], es["dias"]), (2, 30, 10))
        self.assertAlmostEqual(es["realizado"], 0.075, places=4)
        # só os pedidos na rota do dia: com a ROTA 3 (os hotéis) na terça e a ROTA 1 na quarta, o pedido de terça
        # 15/9 é de um cliente da ROTA 1 (fora da rota) e não conta; fica só o da quarta 2/9: 0,5 ÷ 10 dias
        por, a = self.medir("efetividade", meta=30, areas={1: [3], 2: [4], 3: [2]}, abrir="area")
        self.assertEqual((por[ES]["numerador"], por[ES]["denominador"], por[ES]["dias"]), (1, 20, 10))
        self.assertAlmostEqual(por[ES]["realizado"], 0.05, places=4)
        self.assertEqual(por[BA]["realizado"], 0.375)  # os pedidos da BA são todos de quinta, da ROTA 2
        self.assertEqual({x["nome"]: x["valor"] for x in a["abertura"]["linhas"]},
                         {"ROTA 1": 0.1, "ROTA 2": 0.375, "ROTA 3 (SEXTA)": 0.0})
        # semana sem nenhum dia de visita (sábado e domingo): sem efetividade, mesmo com pedido
        por, _ = self.medir("efetividade", meta=30, inicio=D(2026, 9, 5), fim=D(2026, 9, 6), areas={3: [3]})
        self.assertEqual((por[ES]["realizado"], por[ES]["dias"], por[ES]["status"]), (None, 0, "sem_dados"))

    def test_mix_medio(self):
        por, a = self.medir("mix_medio")
        self.assertEqual({v: x["realizado"] for v, x in por.items()}, {ES: 1.5, BA: 1, EDIR: 1})
        self.assertEqual(a["total"]["realizado"], 1.25)  # 5 pares cliente-produto ÷ 4 clientes
        # filtro de produto só no numerador: o denominador são todos os positivados
        por, a = self.medir("mix_medio", filtros={"produtos": [32]})
        self.assertEqual(({v: x["realizado"] for v, x in por.items()}, a["total"]["realizado"]),
                         ({ES: 0.5, BA: 1, EDIR: 1}, 0.75))
        por, a = self.medir("mix_medio", {"clientes": "nunca_compraram"}, {"produtos": [32]})
        self.assertEqual({v: x["realizado"] for v, x in por.items()}, {ES: 0.5, EDIR: 1, BA: None})
        self.assertAlmostEqual(a["total"]["realizado"], 2 / 3, places=4)
        por, _ = self.medir("mix_medio", {"clientes": "ja_compraram"}, {"produtos": [32]})
        self.assertEqual({v: x["realizado"] for v, x in por.items()}, {BA: 1, ES: None, EDIR: None})

    def test_positivacao_com_base_e_abertura(self):
        por, a = self.medir("positivacao", {"clientes": "recuperados", "dias_sem_compra": 22})
        self.assertEqual({v: x["realizado"] for v, x in por.items()}, {ES: 0, BA: 1, EDIR: 0})  # última compra 10/08
        por, _ = self.medir("positivacao", {"clientes": "recuperados", "dias_sem_compra": 23})
        self.assertEqual(por[BA]["realizado"], 0)
        por, _ = self.medir("positivacao", {"clientes": "novos"})
        self.assertEqual({v: x["realizado"] for v, x in por.items()}, {ES: 2, BA: 0, EDIR: 1})
        _, a = self.medir("positivacao", abrir="area")
        self.assertEqual({x["nome"]: x["valor"] for x in a["abertura"]["linhas"]},
                         {"ROTA 1": 2, "ROTA 2": 1, "(sem área)": 1})
        self.assertNotIn("abertura", self.medir("positivacao", abrir="padrao")[1])  # positivação não abre sozinha

    def test_frequencia(self):
        julho = {"inicio": D(2026, 7, 1), "fim": D(2026, 7, 31)}
        por, a = self.medir("frequencia", meta=2, abrir="padrao", **julho)
        # ES: cliente 10 em 2 semanas (01 e 03/07 na mesma) e o 11 em 1; BA: cliente 12 em 2
        self.assertEqual({v: x["realizado"] for v, x in por.items()}, {ES: 1.5, BA: 2.0, EDIR: None})
        self.assertEqual((por[ES]["status"], por[BA]["status"]), ("abaixo", "batida"))
        self.assertIsNone(por[ES]["projecao"])
        self.assertAlmostEqual(a["total"]["realizado"], 5 / 3, places=4)
        self.assertEqual({x["nome"]: x["valor"] for x in a["abertura"]["linhas"]}, {"HOTEL E POUSADA": 1.5, "PADARIA": 2.0})

    def test_preco_medio(self):
        julho = {"inicio": D(2026, 7, 1), "fim": D(2026, 7, 31)}
        alvos = [{"id": 32, "meta": 30.0}, {"id": 27, "meta": 10.0}, {"id": 11469, "meta": 9.0}]
        por, a = self.medir("preco_medio", meta=100, metas_produto=alvos, **julho)
        es = {p["id"]: (p["preco"], p["pct"]) for p in por[ES]["produtos"]}
        self.assertEqual(es, {32: (31.5, 1.05), 27: (10.0, 1.0), 11469: (None, None)})
        self.assertAlmostEqual(por[ES]["realizado"], 1310 / 1250, places=4)  # vendido ÷ quantidades nos preços-alvo
        self.assertEqual(por[ES]["status"], "batida")
        self.assertAlmostEqual(por[BA]["realizado"], 370 / 400, places=4)
        self.assertEqual(por[BA]["status"], "atencao")
        self.assertIsNone(por[EDIR]["realizado"])
        self.assertAlmostEqual(a["total"]["realizado"], 1680 / 1650, places=4)
        self.assertEqual({p["id"]: p["preco"] for p in a["produtos"]}, {32: 30.8, 27: 9.3333, 11469: None})

    def test_personalizada(self):
        por, a = self.medir("personalizada", {"medida": "faturamento", "forma": "por_cliente"})
        self.assertEqual({v: x["realizado"] for v, x in por.items()}, {ES: 700, BA: 4750, EDIR: 700})
        self.assertEqual(a["total"]["realizado"], 1712.5)
        # crescimento sobre agosto: meta = base × 1,1
        por, a = self.medir("personalizada", {"medida": "faturamento", "forma": "crescimento"}, meta=10)
        self.assertEqual((por[BA]["base"], por[BA]["meta"], por[BA]["status"]), (4000, 4400, "batida"))
        self.assertEqual((por[ES]["base"], por[ES]["status"]), (0, "sem_meta"))
        self.assertEqual(a["periodo_base"], {"inicio": "2026-08-01", "fim": "2026-08-31"})
        por, a = self.medir("personalizada", {"medida": "clientes", "forma": "pct_carteira"}, meta=80)
        # ES: 2 de 4 ativos da carteira (o 14 está inativo); BA: 1 de 4 (7, 12 e 13 não compraram); Edir: 1 de 1
        self.assertEqual({v: (x["numerador"], x["denominador"]) for v, x in por.items()}, {ES: (2, 4), BA: (1, 4), EDIR: (1, 1)})
        self.assertEqual((por[EDIR]["realizado"], por[EDIR]["status"]), (1.0, "batida"))

    def test_periodo_base(self):
        from bi.indicadores import periodo_base
        self.assertEqual(periodo_base(D(2026, 9, 1), D(2026, 9, 30), "periodo_anterior"), (D(2026, 8, 1), D(2026, 8, 31)))
        self.assertEqual(periodo_base(D(2026, 1, 1), D(2026, 2, 28), "periodo_anterior"), (D(2025, 11, 1), D(2025, 12, 31)))
        self.assertEqual(periodo_base(D(2026, 9, 10), D(2026, 9, 19), "periodo_anterior"), (D(2026, 8, 31), D(2026, 9, 9)))
        self.assertEqual(periodo_base(D(2028, 2, 29), D(2028, 3, 5), "ano_anterior"), (D(2027, 2, 28), D(2027, 3, 5)))

    def test_dias_do_nome(self):
        from bi.gestao import dias_do_nome
        self.assertEqual(dias_do_nome("TEIXEIRA (SEXTA)"), [5])
        self.assertEqual(dias_do_nome("EUNÁPOLIS CENTRAL (SEGUNDA E TERÇA)"), [1, 2])
        self.assertEqual(dias_do_nome("LORENA CENTRAL (SEGUNDA a SEXTA)"), [1, 2, 3, 4, 5])
        self.assertEqual(dias_do_nome("ITAMARAJU REDES (SABADO)"), [6])
        self.assertEqual(dias_do_nome("SALVADOR"), [])


class TestObjetivo(ComCache, unittest.TestCase):
    """O total da equipe dos objetivos da região (indicadores.total_equipe) e a janela da base das ações."""

    def setUp(self):
        self.montar_cache()

    def tearDown(self):
        self.desmontar_cache()

    def total(self, metrica, ids, meta, regiao="ES", parametros=None, data_ref=D(2026, 9, 30), **datas):
        from bi.indicadores import total_equipe
        objetivo = {**SETEMBRO, **datas, "metrica": metrica, "parametros": parametros or {}, "filtros": {},
                    "meta_padrao": meta}
        return total_equipe(self.cur, objetivo, ids, self.cal, data_ref, regiao)

    def test_janela_base(self):
        from bi.indicadores import janela_base
        self.assertEqual(janela_base(D(2026, 9, 1), D(2026, 9, 28)), (D(2026, 8, 4), D(2026, 8, 31)))
        self.assertEqual(janela_base(D(2026, 9, 1), D(2026, 9, 21)), (D(2026, 8, 11), D(2026, 8, 31)))
        self.assertEqual(janela_base(D(2026, 9, 1), D(2026, 9, 1)), (D(2026, 8, 31), D(2026, 8, 31)))

    def test_total_da_equipe(self):
        t = self.total("positivacao", [ES], 3)  # clientes 1 e 3 (o funcionário 7 não conta)
        self.assertEqual((t["realizado"], t["meta"], t["status"], t["situacao"]), (2, 3, "abaixo", "fechado"))
        self.assertAlmostEqual(t["pct"], 2 / 3, places=4)
        fat = {"medida": "faturamento", "forma": "total"}
        t = self.total("personalizada", [BA, EDIR], 6000, "BA", fat)
        self.assertEqual((t["realizado"], t["status"], t["vendedores"]), (5450, "atencao", 2))
        self.assertEqual(self.total("personalizada", [BA], 6000, "BA", fat)["realizado"], 4750)  # só os do acesso
        # sem vendedores no acesso: zero na soma, sem dados na média
        self.assertEqual(self.total("positivacao", [], 3)["realizado"], 0)
        self.assertIsNone(self.total("mix_medio", [], 2)["realizado"])
        # no meio do período, a soma usa o ritmo da região
        t = self.total("personalizada", [BA, EDIR], 6000, "BA", fat, fim=D(2026, 10, 31))
        self.assertEqual((t["situacao"], t["status"]), ("aberto", "no_ritmo"))
        self.assertEqual(t["calendario"]["regiao"], "BA")


class TestValidar(ComCache, unittest.TestCase):
    def setUp(self):
        self.montar_cache()

    def tearDown(self):
        self.desmontar_cache()

    def validar(self, permitidos=None, tipo="acao", inicio_dados=None, **mudancas):
        dados = {"nome": "  Mussarela   de setembro ", "regiao": "BA", "inicio": "2026-09-01", "fim": "2026-09-30",
                 "metrica": "faturamento", "meta_padrao": 1000, "vendedores": [EDIR, {"id": BA, "meta": 500}], **mudancas}
        return validar(dados, self.cur, self.regras, permitidos, D(2026, 9, 30), inicio_dados, tipo, D(2026, 9, 1))

    def erro(self, texto, **mudancas):
        with self.assertRaises(ValueError) as e:
            self.validar(**mudancas)
        self.assertIn(texto, str(e.exception))

    def test_normaliza(self):
        d = self.validar(filtros={"produtos": [3643, 32], "ufs": ["es"], "linhas": ["mussarela"], "grupos": ["OUTRAS"]})
        self.assertEqual(d["nome"], "Mussarela de setembro")
        self.assertEqual(d["filtros"], {"produtos": [11469, 32], "grupos": ["outras"], "linhas": ["MUSSARELA"],
                                        "ufs": ["ES"]})
        self.assertEqual(d["vendedores"], [{"id": EDIR, "meta": None}, {"id": BA, "meta": 500.0}])  # o Edir é da BA
        self.assertEqual((d["inicio"], d["fim"]), (D(2026, 9, 1), D(2026, 9, 30)))
        self.assertEqual((d["base_inicio"], d["base_fim"]), (D(2026, 8, 2), D(2026, 8, 31)))  # 30 dias logo antes
        self.assertEqual((d["tipo"], d["regiao"], d["alvo_tipo"], d["rotulo"]), ("acao", "BA", "fixo", "Faturamento"))
        self.assertNotIn("categorias", d["filtros"])  # filtro vazio não fica

    def test_prazo_e_regiao(self):
        d = self.validar(fim=None, semanas=3)
        self.assertEqual((d["fim"], d["base_inicio"], d["base_fim"]), (D(2026, 9, 21), D(2026, 8, 11), D(2026, 8, 31)))
        d = self.validar(inicio=None, fim=None, semanas="1")  # sem início: começa hoje
        self.assertEqual((d["inicio"], d["fim"]), (D(2026, 9, 1), D(2026, 9, 7)))
        self.erro("prazo", fim=None)
        self.erro("1 a 26 semanas", fim=None, semanas=30)
        self.erro("até 26 semanas", fim="2027-03-31")
        self.erro("região", regiao="")
        self.erro("Edir (85) é da equipe Edir; Thais (141) é da equipe BA: esta ação é da região ES", regiao="ES")
        self.assertEqual(self.validar(regiao="es", vendedores=[ES])["regiao"], "ES")

    def test_erros(self):
        self.erro("nome", nome=" ")
        self.erro("antes do início", fim="2026-08-01")
        self.erro("métrica", metrica="lucro")
        self.erro("vendedores", vendedores=[])
        self.erro("não encontrado: 777", vendedores=[777])
        self.erro("produto não encontrado", filtros={"produtos": [123456]})
        self.erro("não conta", filtros={"produtos": [999]})
        self.erro("linha não encontrada", filtros={"linhas": ["chocolate"]})
        self.erro("categoria", filtros={"categorias": ["Sorvete"]})
        self.erro("filtro desconhecido", filtros={"cidades": ["Serra"]})
        self.erro("alvo", meta_padrao=-1)
        self.erro("dê o alvo", meta_padrao=0)
        self.erro("quanto a mais", meta_padrao=0, alvo_tipo="mais")
        self.erro("alvo_tipo", alvo_tipo="dobro")
        self.erro("rótulo", rotulo="x" * 21)
        self.assertEqual(self.validar(rotulo="  Mussa  ")["rotulo"], "Mussa")

    def test_volume_precisa_da_mesma_unidade(self):
        self.erro("filtro de produto", metrica="volume")
        self.erro("unidades diferentes (KG, UN)", metrica="volume", filtros={"produtos": [32, 27]})
        d = self.validar(metrica="volume", filtros={"produtos": [32]})  # a métrica de antes vira Personalizada
        self.assertEqual((d["metrica"], d["parametros"]), ("personalizada", {"medida": "volume", "forma": "total",
                                                                             "clientes": "todos"}))
        d = self.validar(metrica="personalizada", parametros={"medida": "volume", "forma": "por_cliente"},
                         filtros={"produtos": [32]})
        self.assertEqual((d["parametros"]["forma"], d["rotulo"]), ("por_cliente", "Volume/cliente"))

    def test_tipos_e_blocos(self):
        self.assertEqual(self.validar(metrica="mix")["parametros"], {"medida": "produtos", "forma": "total",
                                                                    "clientes": "todos"})
        # clientes no total é a Positivação
        d = self.validar(metrica="personalizada", parametros={"medida": "clientes", "clientes": "recuperados"})
        self.assertEqual((d["metrica"], d["parametros"]), ("positivacao", {"clientes": "recuperados",
                                                                           "dias_sem_compra": 90}))
        self.erro("formas", metrica="personalizada", parametros={"medida": "produtos", "forma": "por_cliente"})
        self.erro("medida", metrica="personalizada", parametros={"medida": "lucro"})
        self.erro("base de clientes", metrica="positivacao", parametros={"clientes": "vips"})
        self.erro("todos os clientes", metrica="efetividade", parametros={"clientes": "novos"})
        self.erro("escolha os produtos", metrica="mix_medio", parametros={"clientes": "nunca_compraram"})
        self.erro("sem produto", metrica="efetividade", filtros={"produtos": [32]})
        self.erro("lista de preços-alvo", metrica="preco_medio", filtros={"linhas": ["mussarela"]},
                  metas_produto=[{"id": 32, "meta": 30}])
        self.erro("preço-alvo", metrica="preco_medio")
        self.erro("preço-alvo do produto 27", metrica="preco_medio", metas_produto=[{"id": 27, "meta": 0}])
        d = self.validar(metrica="preco_medio", alvo_tipo="mais",
                         metas_produto=[{"id": 3643, "meta": 9.5}, {"id": 32, "meta": 30}])
        self.assertEqual(d["metas_produto"], [{"id": 11469, "meta": 9.5}, {"id": 32, "meta": 30.0}])
        self.assertEqual((d["meta_padrao"], d["alvo_tipo"], d["vendedores"][1]["meta"]), (100.0, "fixo", None))
        d = self.validar(metrica="positivacao", filtros={"areas": ["rota 1"], "segmentos": ["padaria"]})
        self.assertEqual(d["filtros"], {"segmentos": ["PADARIA"], "areas": ["ROTA 1"]})
        self.erro("área comercial não encontrada", metrica="positivacao", filtros={"areas": ["ROTA 9"]})
        # numa ação o alvo já sai da base: crescimento só no objetivo
        crescer = {"medida": "faturamento", "forma": "crescimento"}
        self.erro("alvo_tipo pct", metrica="personalizada", parametros=crescer)
        o = self.validar(tipo="objetivo", metrica="personalizada", parametros=crescer, meta_padrao=10, vendedores=[])
        self.assertEqual((o["tipo"], o["vendedores"], o["base_inicio"], o["rotulo"]), ("objetivo", [], None, "Crescimento"))
        with self.assertRaises(ValueError) as e:
            self.validar(tipo="objetivo", alvo_tipo="mais")
        self.assertIn("alvo fixo para a equipe", str(e.exception))

    def test_historico_da_base_e_do_crescimento(self):
        inicio = D(2026, 1, 1)
        recuperados = {"clientes": "recuperados", "dias_sem_compra": 200}
        self.validar(inicio_dados=inicio, metrica="positivacao", parametros=recuperados)  # corte: 02/08, a janela
        with self.assertRaises(ValueError) as e:
            self.validar(inicio_dados=inicio, metrica="positivacao", parametros={**recuperados, "dias_sem_compra": 250})
        self.assertIn("histórico", str(e.exception))
        with self.assertRaises(ValueError) as e:  # a base de janeiro cai antes do histórico
            self.validar(inicio_dados=inicio, inicio="2026-01-10", fim=None, semanas=4)
        self.assertIn("a base desta ação (13/12/2025 a 09/01/2026", str(e.exception))
        crescer = {"medida": "faturamento", "forma": "crescimento", "comparar": "ano_anterior"}
        with self.assertRaises(ValueError) as e:
            self.validar(tipo="objetivo", inicio_dados=inicio, metrica="personalizada", parametros=crescer,
                         meta_padrao=10)
        self.assertIn("período de comparação (01/09/2025 a 30/09/2025)", str(e.exception))

    def test_fora_do_acesso(self):
        with self.assertRaises(ValueError) as e:
            self.validar(permitidos=frozenset({BA}))
        self.assertIn("Edir (85)", str(e.exception))
        self.assertEqual(len(self.validar(permitidos=frozenset({BA}), vendedores=[BA])["vendedores"]), 1)


class TestFerramentasDeAcao(ComCache, unittest.TestCase):
    """As ferramentas do Assistente que não precisam do banco: propor (não grava, só o administrador) e a recusa sem
    a página."""

    def setUp(self):
        self.montar_cache()
        self.gestao = Gestao(None, self.calc, self.assistente, hoje=lambda: D(2026, 10, 1))  # propor não grava

    def tearDown(self):
        self.desmontar_cache()

    ARGS = {"nome": "Bebidas BA", "descricao": "", "regiao": "BA", "inicio": "2026-09-01", "fim": "2026-09-30",
            "metrica": "VOLUME", "alvo_tipo": "fixo", "meta": 30, "metas": [{"id_vendedor": BA, "meta": 50}],
            "vendedores": [EDIR], "equipes": [], "produtos": [3643], "linhas": [], "categorias": [], "grupos": [],
            "ufs": [], "segmentos": []}

    def ferramentas(self, usuario=USUARIO_ADMIN, escopo=(None, None)):
        return Ferramentas(self.assistente.recorte(None), self.calc, self.assistente.cfg, None,
                           gestao=self.gestao.contexto(usuario, escopo))

    def test_propor_nao_grava_e_devolve_o_rascunho(self):
        f = self.ferramentas()
        r, p = f.executar("propor_acao", dict(self.ARGS))
        self.assertIsNone(p["erro"])
        self.assertIn("AINDA NÃO LANÇADO", r["situacao"])
        self.assertEqual([(v["id"], v["meta"]) for v in r["rascunho"]["vendedores"]], [(EDIR, 30), (BA, 50)])
        self.assertEqual(r["rascunho"]["vendedores"][0]["base"], 0)  # nenhuma bebida láctea em agosto
        self.assertEqual(r["rascunho"]["filtros"]["produtos"], ["11469 BEBIDA LACTEA 500G"])
        self.assertEqual((r["rascunho"]["unidade"], r["rascunho"]["regiao"]), ("UN", "BA"))
        self.assertIn("2026-08-02 a 2026-08-31", r["rascunho"]["periodo_da_base"])
        rascunho, = f.rascunhos
        self.assertEqual((rascunho["metrica"], rascunho["parametros"]["medida"], rascunho["inicio"]),
                         ("personalizada", "volume", "2026-09-01"))
        self.assertEqual((rascunho["indicador"]["nome"], rascunho["indicador"]["unidade"]), ("Volume", "UN"))
        self.assertIn(f"rascunho {rascunho['id']}", p["resumo"])
        # erro de conferência volta para a IA corrigir
        _, p = f.executar("propor_acao", {**self.ARGS, "produtos": [32, 27]})
        self.assertIn("unidades diferentes", p["erro"])
        self.assertEqual(len(f.rascunhos), 1)

    def test_so_o_administrador_propoe(self):
        f = self.ferramentas(USUARIO_VIS)
        _, p = f.executar("propor_acao", dict(self.ARGS))
        self.assertIn("só o administrador", p["erro"])
        self.assertEqual(f.rascunhos, [])

    def test_propor_tipos_e_alvos(self):
        f = self.ferramentas()
        base = {"nome": "Teste", "regiao": "ES", "inicio": "2026-09-01", "semanas": 3, "vendedores": [ES]}
        r, p = f.executar("propor_acao", {**base, "metrica": "preco_medio", "alvo_tipo": "fixo", "meta": 0,
                                          "metas_produto": [{"id_produto": 32, "meta": 31}]})
        self.assertIsNone(p["erro"])
        self.assertEqual((r["rascunho"]["indicador"], r["rascunho"]["meta_em_percentual"]), ("Preço médio", True))
        self.assertEqual(r["rascunho"]["precos_alvo"], [{"produto": "32 QUEIJO MUSSARELA 4KG", "meta": 31.0}])
        self.assertEqual(f.rascunhos[-1]["metas_produto"], [{"id": 32, "meta": 31.0}])
        r, p = f.executar("propor_acao", {**base, "metrica": "positivacao", "alvo_tipo": "mais", "meta": 1,
                                          "clientes_base": "recuperados", "dias_sem_compra": 60, "areas": ["rota 1"]})
        self.assertIsNone(p["erro"])
        self.assertEqual((f.rascunhos[-1]["parametros"], f.rascunhos[-1]["filtros"], f.rascunhos[-1]["fim"]),
                         ({"clientes": "recuperados", "dias_sem_compra": 60}, {"areas": ["ROTA 1"]}, "2026-09-21"))
        self.assertEqual(r["rascunho"]["alvo"], "+1 sobre a base de cada um")
        self.assertEqual(r["rascunho"]["vendedores"][0]["alvo"], 1)  # base 0 em agosto
        _, p = f.executar("propor_acao", {**base, "metrica": "personalizada", "medida": "faturamento",
                                          "forma": "crescimento", "alvo_tipo": "pct", "meta": 10})
        self.assertIn("alvo_tipo pct", p["erro"])
        # o enum da ferramenta acompanha os tipos de bi/indicadores.py
        from bi.indicadores import TIPOS
        propor = next(t for t in FERRAMENTAS if t["name"] == "propor_acao")["input_schema"]["properties"]
        self.assertEqual(propor["metrica"]["enum"], list(TIPOS))

    def test_equipes(self):
        f = self.ferramentas()
        r, p = f.executar("propor_acao", {**self.ARGS, "metas": [], "vendedores": [], "equipes": ["BA", "EDIR"]})
        self.assertIsNone(p["erro"])
        self.assertEqual({v["id"] for v in r["rascunho"]["vendedores"]}, {BA, EDIR})
        _, p = f.executar("propor_acao", {**self.ARGS, "equipes": ["ES"]})
        self.assertIn("a região BA tem as equipes", p["erro"])
        _, p = f.executar("propor_acao", {**self.ARGS, "vendedores": [ES]})
        self.assertIn("Rubens (124) é da equipe ES", p["erro"])

    def test_sem_a_pagina_gestao(self):
        f = Ferramentas(self.assistente.recorte(None), self.calc, self.assistente.cfg, None)
        for nome, args in (("listar_acoes", {"texto": "", "incluir_encerradas": False}),
                           ("andamento_acao", {"acao": 1}), ("propor_acao", dict(self.ARGS))):
            _, p = f.executar(nome, args)
            self.assertIn("não inclui a página Gestão", p["erro"], nome)

    def test_esquemas_strict(self):
        """Ferramentas strict: a API aceita no máximo 24 parâmetros opcionais no pedido inteiro e recusa uma gramática
        grande demais (a do rascunho de ação passava)."""
        def opcionais(esquema):
            n = len(set(esquema.get("properties", {})) - set(esquema.get("required", [])))
            for prop in esquema.get("properties", {}).values():
                if prop.get("type") == "object":
                    n += opcionais(prop)
                if prop.get("type") == "array" and prop["items"].get("type") == "object":
                    n += opcionais(prop["items"])
            return n
        estritas = [t for t in FERRAMENTAS if t.get("strict")]
        self.assertLessEqual(sum(opcionais(t["input_schema"]) for t in estritas), 24)
        self.assertLessEqual(len(estritas), 20)
        # o rascunho de ação fica fora do strict: com ele a gramática passa do limite da API
        self.assertEqual([t["name"] for t in FERRAMENTAS if not t.get("strict")], ["propor_acao"])

    def test_laco_guarda_os_rascunhos(self):
        api = ClienteFalso([
            resposta(bloco_ferramenta("t1", "propor_acao", dict(self.ARGS)), parada="tool_use"),
            resposta(bloco_texto("O rascunho está pronto para conferir.")),
        ])
        conversas = ConversasFalsas()
        a = criar_assistente(self.pasta, self.calc, cliente=api, conversas=conversas)
        ctx = Gestao(None, self.calc, a).contexto(USUARIO_ADMIN, (None, None))
        r = a.perguntar(USUARIO_ADMIN, None, "crie uma ação de bebida láctea em setembro", None, None, ctx)
        rascunho, = r["rascunhos"]
        self.assertEqual(rascunho["nome"], "Bebidas BA")
        self.assertIn(f"propor_acao -> rascunho {rascunho['id']}", r["consultas"])
        self.assertIn("Ações (página Gestão): pode lançar e acompanhar", api.pedidos[0]["system"][1]["text"])
        gravada, = conversas.dados.values()
        self.assertEqual(gravada["mensagens"][1]["rascunhos"][0]["id"], rascunho["id"])
        # quem não é administrador acompanha
        api = ClienteFalso([resposta(bloco_texto("Só o administrador lança."))])
        b = criar_assistente(self.pasta, self.calc, cliente=api, conversas=ConversasFalsas())
        b.perguntar(USUARIO_VIS, None, "crie", None, None, Gestao(None, self.calc, b).contexto(USUARIO_VIS, (None, None)))
        self.assertIn("pode acompanhar (só o administrador lança)", api.pedidos[0]["system"][1]["text"])
        # sem a página: a ferramenta recusa e a resposta não tem rascunho
        api = ClienteFalso([
            resposta(bloco_ferramenta("t1", "propor_acao", dict(self.ARGS)), parada="tool_use"),
            resposta(bloco_texto("Seu acesso não inclui a Gestão.")),
        ])
        b = criar_assistente(self.pasta, self.calc, cliente=api)
        r = b.responder(USUARIO_VIS, [{"papel": "usuario", "texto": "crie"}], None, None)
        self.assertEqual(r["rascunhos"], [])
        self.assertIn("o acesso não inclui", api.pedidos[0]["system"][1]["text"])


HOJE = D(2026, 10, 1)


class TestAcoesNoBanco(ComCache, BaseBanco):
    """Ações e objetivos no PostgreSQL: base, alvo, resultado congelado, parciais, prorrogar, encerrar, histórico,
    observações e quem pode o quê. O cache vai até 30/09/2026; hoje é 01/10/2026."""

    def setUp(self):
        super().setUp()
        self.montar_cache()
        self.gestao = Gestao(self.banco, self.calc, self.assistente, hoje=lambda: HOJE)
        ids = {login: self.criar_usuario(login, papel) for login, papel in (("chefe", "admin"), ("ana", "visualizador"))}
        self.chefe = {"id": ids["chefe"], "login": "chefe", "nome": "Chefe", "papel": "admin"}
        self.ana = {"id": ids["ana"], "login": "ana", "nome": "Ana", "papel": "visualizador"}

    def tearDown(self):
        self.desmontar_cache()
        super().tearDown()

    def dados(self, nome="Mussarela BA", **mudancas):
        # 01 a 28/09 (4 semanas): base de 04 a 31/08 (a BA vendeu 4.000 em 10/08); alvo = base + 1.000
        return {"nome": nome, "regiao": "BA", "inicio": "2026-09-01", "fim": "2026-09-28", "metrica": "faturamento",
                "alvo_tipo": "mais", "meta_padrao": 1000, "vendedores": [BA, EDIR], **mudancas}

    def criar(self, nome="Mussarela BA", tipo="acao", **mudancas):
        return self.gestao.criar(self.chefe, self.dados(nome, **mudancas), tipo)["id"]

    def quadro(self, usuario=None, escopo=(None, None), regiao="BA"):
        return self.gestao.quadro(usuario or self.chefe, escopo, regiao)

    def historico(self, vid, usuario=None, escopo=(None, None)):
        return self.gestao.historico(usuario or self.chefe, escopo, vid)

    def eventos(self, vid, campanha=None):
        with self.banco.conexao() as con:
            return [t for (t,) in con.execute("SELECT tipo FROM gestao_eventos WHERE id_vendedor = %s AND "
                                              "(%s::bigint IS NULL OR campanha = %s) ORDER BY id", [vid, campanha, campanha])]

    def vendedores(self, id_):
        with self.banco.conexao() as con:
            return {v: (None if b is None else float(b), e is not None, None if r is None else float(r))
                    for v, b, e, r in con.execute("SELECT id_vendedor, base, base_em, resultado FROM campanha_vendedores "
                                                  "WHERE campanha = %s", [id_])}

    def test_base_resultado_congelado_e_historico(self):
        id_ = self.criar()
        self.assertEqual(self.vendedores(id_), {BA: (4000, True, None), EDIR: (0, True, None)})  # base já no lançamento
        acao, = self.quadro()["acoes"]
        # 01 a 28/09: BA 5.000 − 250 de devolução (o 999 fica fora); Edir 700. Os dados passam do fim: congela.
        self.assertEqual((acao["situacao"], acao["no_alvo"], acao["com_resultado"], acao["provisorio"]),
                         ("encerrada", 0, 2, False))
        self.assertEqual(self.vendedores(id_), {BA: (4000, True, 4750), EDIR: (0, True, 700)})
        self.quadro()  # ler de novo não congela outra vez
        self.assertEqual(self.contar("gestao_eventos", "tipo = 'resultado'"), 2)
        thais = next(v for v in self.quadro()["vendedores"] if v["id"] == BA)
        self.assertEqual([(e["rotulo"], e["classe"], e["delta"]) for e in thais["acoes"]], [("Faturamento", "mid", 750)])
        h = self.historico(BA)
        self.assertEqual([e["tipo"] for e in h["eventos"]], ["lancada", "parcial", "parcial", "parcial", "resultado"])
        lancada, *parciais, resultado = h["eventos"]
        self.assertEqual((lancada["data"], lancada["dados"]["base"], lancada["dados"]["alvo"], lancada["dados"]["vendedores"]),
                         ("2026-09-01", 4000, 5000, 2))
        self.assertEqual([(p["data"], p["dados"]["valor"]) for p in parciais],
                         [("2026-09-08", 5000), ("2026-09-15", 4750), ("2026-09-22", 4750)])
        self.assertEqual((resultado["data"], resultado["dados"]["classe"], resultado["dados"]["caminho"], resultado["atual"]),
                         ("2026-09-29", "mid", 0.75, True))  # entra no dia seguinte ao fim
        self.assertEqual((h["vendedor"]["nome"], h["vendedor"]["regiao"], h["em_vigor"]), ("Thais", "BA", 0))
        d = self.gestao.detalhe(self.chefe, (None, None), id_)
        self.assertEqual({x["id"]: (x["base"], x["alvo"], x["resultado"], x["classe"]) for x in d["linhas"]},
                         {BA: (4000, 5000, 4750, "mid"), EDIR: (0, 1000, 700, "mid")})

    def test_parciais_e_alvo_batido(self):
        # ES, positivação, 3 semanas: base de 11 a 31/08 = 0; clientes 1 (02/09) e 3 (15/09); o funcionário não conta
        id_ = self.criar("Positivar ES", regiao="ES", metrica="positivacao", fim=None, semanas=3, meta_padrao=1,
                         vendedores=[ES])
        rubens, = self.quadro(regiao="ES")["vendedores"]
        self.assertEqual([(e["classe"], e["delta"]) for e in rubens["acoes"]], [("ok", 2)])
        h = self.historico(ES)
        self.assertEqual([e["dados"]["valor"] for e in h["eventos"] if e["tipo"] == "parcial"], [1, 1])
        with self.banco.conexao() as con:
            parciais, = con.execute("SELECT parciais FROM campanha_vendedores WHERE campanha = %s", [id_]).fetchone()
        self.assertEqual([p["valor"] for p in parciais], [1, 1])

    def test_base_pendente(self):
        # começa em 05/10: a janela (28/09 a 04/10) ainda não tem dados
        id_ = self.criar("Futura", inicio="2026-10-05", fim=None, semanas=1, vendedores=[BA])
        self.assertEqual(self.vendedores(id_), {BA: (None, False, None)})
        acao, = self.quadro()["acoes"]
        self.assertEqual((acao["situacao"], acao["base_pendente"], acao["prazo"]["comeca_em"]), ("planejada", True, 4))
        lancada, = self.historico(BA)["eventos"]
        self.assertTrue(lancada["dados"]["base_pendente"])
        self.assertLessEqual(lancada["data"], "2026-10-05")  # o dia do lançamento (ou o início, se já começou)
        self.calc.cache.info["data_ref"] = "2026-10-05"  # os dados chegam
        self.quadro()
        self.assertEqual(self.vendedores(id_), {BA: (0, True, None)})
        lancada, = self.historico(BA)["eventos"]
        self.assertEqual((lancada["dados"]["base"], lancada["dados"]["alvo"], lancada["dados"]["base_pendente"]),
                         (0, 1000, False))

    def test_prorrogar_refaz_a_base(self):
        # 2 semanas: base de 18 a 31/08 = 0, alvo 1.000; resultado 4.750 (alvo batido)
        id_ = self.criar("Curta", fim="2026-09-14", vendedores=[BA])
        self.quadro()
        self.assertEqual(self.vendedores(id_), {BA: (0, True, 4750)})
        self.gestao.prorrogar(self.chefe, id_)
        # 4 semanas: base de 04 a 31/08 = 4.000, alvo 5.000; o resultado volta a correr e congela de novo
        self.assertEqual(self.vendedores(id_), {BA: (4000, True, None)})
        acao, = self.quadro()["acoes"]
        self.assertEqual((acao["fim"], acao["no_alvo"]), ("2026-09-28", 0))
        self.assertEqual(self.eventos(BA, id_), ["lancada", "resultado", "prorrogada", "resultado"])
        h = self.historico(BA)
        prorrogada = next(e for e in h["eventos"] if e["tipo"] == "prorrogada")
        self.assertEqual({k: prorrogada["dados"][k] for k in ("fim_antes", "fim", "base_antes", "base", "alvo_antes", "alvo")},
                         {"fim_antes": "2026-09-14", "fim": "2026-09-28", "base_antes": 0, "base": 4000,
                          "alvo_antes": 1000, "alvo": 5000})
        resultados = [e for e in h["eventos"] if e["tipo"] == "resultado"]
        self.assertEqual([(e["dados"]["classe"], e["atual"]) for e in resultados], [("ok", False), ("mid", True)])
        with self.assertRaises(ValueError):
            self.gestao.prorrogar(self.chefe, id_, 200)

    def test_encerrar(self):
        id_ = self.criar("Longa", fim="2026-10-31", vendedores=[BA])
        self.assertEqual(self.quadro()["acoes"][0]["situacao"], "em_vigor")
        self.gestao.encerrar(self.chefe, id_)  # o fim vira 30/09 (os dados); a base, 02 a 31/08
        acao, = self.quadro()["acoes"]
        self.assertEqual((acao["situacao"], acao["fim"], acao["no_alvo"]), ("encerrada", "2026-09-30", 0))
        self.assertEqual(self.vendedores(id_), {BA: (4000, True, 4750)})
        self.assertEqual(self.eventos(BA, id_), ["lancada", "encerrada", "resultado"])
        with self.assertRaises(ValueError):
            self.gestao.encerrar(self.chefe, id_)
        futura = self.criar("Futura", inicio="2026-10-05", fim=None, semanas=2, vendedores=[BA])
        with self.assertRaises(ValueError) as e:
            self.gestao.encerrar(self.chefe, futura)
        self.assertIn("exclua", str(e.exception))

    def test_versao_antiga_nao_grava(self):
        id_ = self.criar()
        with self.banco.conexao() as con:
            velha = self.gestao._uma(con, id_)
            con.execute("UPDATE campanhas SET versao = versao + 1 WHERE id = %s", [id_])
        with self.gestao._contas() as k:
            self.assertFalse(self.gestao._pendencias(k, [velha]))
        self.assertEqual(self.contar("gestao_eventos", "tipo = 'resultado'"), 0)

    def test_editar(self):
        id_ = self.criar(vendedores=[BA])
        self.gestao.atualizar(self.chefe, id_, self.dados(vendedores=[BA, EDIR], meta_padrao=500))
        self.assertEqual(self.eventos(EDIR, id_), ["lancada"])
        self.assertEqual(self.eventos(BA, id_), ["lancada", "editada"])
        with self.banco.conexao() as con:  # (sem ler o histórico, que congelaria a ação já vencida)
            editada, = con.execute("SELECT dados FROM gestao_eventos WHERE tipo = 'editada'").fetchone()
        self.assertEqual((editada["mudou"], editada["alvo_antes"], editada["alvo"]), (["alvo"], 5000, 4500))
        self.gestao.atualizar(self.chefe, id_, self.dados(vendedores=[BA], fim="2026-09-14", meta_padrao=500))
        self.assertEqual(self.vendedores(id_), {BA: (0, True, None)})  # a base acompanha o prazo (18 a 31/08)
        self.assertEqual(self.eventos(EDIR, id_), ["lancada", "removido"])
        self.quadro()  # congela
        with self.assertRaises(ValueError) as e:
            self.gestao.atualizar(self.chefe, id_, self.dados(vendedores=[BA], fim="2026-09-14", meta_padrao=900))
        self.assertIn("já tem resultado", str(e.exception))
        self.gestao.atualizar(self.chefe, id_, self.dados("Novo nome", vendedores=[BA], fim="2026-09-14", meta_padrao=500))
        self.assertEqual(self.quadro()["acoes"][0]["nome"], "Novo nome")
        with self.assertRaises(ValueError):
            self.gestao.atualizar(self.chefe, id_, self.dados(regiao="ES", vendedores=[ES]))

    def test_quadro_vendedores_e_faturamento(self):
        es = self.quadro(regiao="ES")
        self.assertEqual((es["regioes"], es["regiao"], es["pode_editar"], es["mes_faturamento"]),
                         (["ES", "BA"], "ES", True, {"ano": 2026, "mes": 9}))
        self.assertEqual([(v["id"], v["nome"], v["faturamento_pct"]) for v in es["vendedores"]], [(ES, "Rubens", 0.74)])
        ba = self.quadro()  # a equipe é quem tem meta no mês (planilha METAS): o Edir não tem em setembro
        self.assertEqual({v["id"]: v["faturamento_pct"] for v in ba["vendedores"]}, {BA: 0.7917})
        self.criar("Do Edir", vendedores=[EDIR], fim="2026-10-31")  # numa ação em vigor ele aparece, sem meta
        self.assertEqual({v["id"]: (v["faturamento_pct"], v["em_vigor"]) for v in self.quadro()["vendedores"]},
                         {BA: (0.7917, 0), EDIR: (None, 1)})
        with self.assertRaises(ValueError):
            self.quadro(regiao="SP")

    def test_quem_pode_o_que(self):
        so_rubens = ({ES}, None)
        id_es = self.criar("Do Rubens", regiao="ES", metrica="positivacao", meta_padrao=1, vendedores=[ES])
        self.criar("Da Thais", vendedores=[BA])
        for fazer in (lambda: self.gestao.criar(self.ana, self.dados(), "acao"),
                      lambda: self.gestao.atualizar(self.ana, id_es, self.dados()),
                      lambda: self.gestao.encerrar(self.ana, id_es), lambda: self.gestao.prorrogar(self.ana, id_es),
                      lambda: self.gestao.arquivar(self.ana, id_es), lambda: self.gestao.excluir(self.ana, id_es),
                      lambda: self.gestao.anotar(self.ana, ES, "oi")):
            with self.assertRaises(PermissionError):
                fazer()
        q = self.gestao.quadro(self.ana, so_rubens)  # sem região: a primeira do acesso
        self.assertEqual((q["regiao"], q["regioes"], q["pode_editar"]), ("ES", ["ES"], False))
        self.assertEqual([a["nome"] for a in q["acoes"]], ["Do Rubens"])
        with self.assertRaises(PermissionError):
            self.gestao.quadro(self.ana, so_rubens, "BA")
        with self.assertRaises(NaoEncontrada):
            self.gestao.historico(self.ana, so_rubens, BA)
        nota = self.gestao.anotar(self.chefe, ES, "Combinado: oferecer requeijão nas padarias de terça.")
        h = self.gestao.historico(self.ana, so_rubens, ES)
        self.assertIn(("nota", "Combinado: oferecer requeijão nas padarias de terça.", "Chefe"),
                      [(e["tipo"], e["texto"], e["autor"]) for e in h["eventos"]])
        self.assertFalse(h["pode_editar"])
        with self.assertRaises(ValueError):
            self.gestao.anotar(self.chefe, ES, "   ")
        self.gestao.excluir_nota(self.chefe, nota["id"])
        self.assertEqual(self.contar("gestao_eventos", "tipo = 'nota'"), 0)

    def test_arquivar_e_excluir(self):
        id_ = self.criar(vendedores=[BA])
        self.gestao.anotar(self.chefe, BA, "Conversei sobre a meta.")
        self.gestao.arquivar(self.chefe, id_)
        self.assertEqual(self.quadro()["acoes"], [])
        self.assertIn("lancada", [e["tipo"] for e in self.historico(BA)["eventos"]])  # o histórico continua
        self.gestao.arquivar(self.chefe, id_, False)
        self.assertEqual(len(self.quadro()["acoes"]), 1)
        self.gestao.excluir(self.chefe, id_)
        self.assertEqual((self.contar("campanhas"), self.contar("campanha_vendedores")), (0, 0))
        self.assertEqual(self.eventos(BA), ["nota"])  # os eventos da ação saem; a observação fica

    def test_objetivo_da_regiao(self):
        self.calc.metas.dados().append({"mes": D(2026, 9, 1), "id_vendedor": EDIR, "vendedor": "EDIR", "meta_fat": 1000.0,
                                        "meta_mus": 0.0, "meta_out": 0.0, "meta_cli": 1.0})  # a equipe BA: Thais e Edir
        id_ = self.gestao.criar(self.chefe, {"nome": "Faturamento da equipe", "regiao": "BA", "inicio": "2026-09-01",
                                             "fim": "2026-09-30", "metrica": "faturamento", "meta_padrao": 6000},
                                "objetivo")["id"]
        o, = self.quadro()["objetivos"]
        self.assertEqual((o["nome"], o["andamento"]["realizado"], o["andamento"]["status"], o["parcial"]),
                         ("Faturamento da equipe", 5450, "atencao", None))
        o, = self.gestao.quadro(self.ana, ({BA}, None), "BA")["objetivos"]  # só a Thais no acesso
        self.assertEqual((o["andamento"]["realizado"], o["parcial"]), (4750, {"vendedores": 1, "total": 2}))
        d = self.gestao.detalhe(self.chefe, (None, None), id_)
        self.assertEqual(d["andamento"]["meta"], 6000)
        self.assertEqual(self.quadro(regiao="ES")["objetivos"], [])
        self.gestao.atualizar(self.chefe, id_, {"nome": "Faturamento", "inicio": "2026-09-01", "fim": "2026-09-30",
                                               "metrica": "faturamento", "meta_padrao": 5000}, "objetivo")
        self.assertEqual(self.quadro()["objetivos"][0]["andamento"]["status"], "batida")

    def test_rascunho_lanca_uma_vez_so(self):
        rascunho = "6f1c2a0e-58d4-4c47-9b1f-0d3a5e7b9c21"
        primeira = self.gestao.criar(self.chefe, self.dados(), "acao", rascunho)
        segunda = self.gestao.criar(self.chefe, self.dados("Outro nome"), "acao", rascunho)
        self.assertEqual((segunda["id"], segunda["ja_existia"], segunda["regiao"]), (primeira["id"], True, "BA"))
        self.assertEqual(self.contar("campanhas"), 1)
        self.assertEqual(self.gestao.criadas_por_rascunho(self.chefe, [rascunho, "lixo"]),
                         {rascunho: {"id": primeira["id"], "nome": "Mussarela BA", "regiao": "BA"}})

    def test_ferramentas_listar_e_andamento(self):
        id_ = self.criar("Mussarela de setembro")
        objetivo = self.gestao.criar(self.chefe, {"nome": "Equipe BA", "regiao": "BA", "inicio": "2026-09-01",
                                                  "fim": "2026-09-30", "metrica": "faturamento", "meta_padrao": 6000},
                                     "objetivo")["id"]
        f = Ferramentas(self.assistente.recorte(None), self.calc, self.assistente.cfg, None,
                        gestao=self.gestao.contexto(self.ana, ({BA}, None)))
        r, p = f.executar("listar_acoes", {"texto": "mussarela", "incluir_encerradas": True})
        self.assertEqual([c["id"] for c in r["acoes"]], [id_])
        self.assertEqual((r["acoes"][0]["vendedores"], r["acoes"][0]["alvo"]), (1, "+1.000 sobre a base de cada um"))
        r, _ = f.executar("listar_acoes", {"texto": "", "incluir_encerradas": False})
        self.assertEqual(r["acoes"], [])  # as duas já terminaram
        r, p = f.executar("andamento_acao", {"acao": id_})
        self.assertIsNone(p["erro"])
        self.assertEqual([(v["id"], v["base"], v["alvo"], v["resultado"], v["classe"]) for v in r["vendedores"]],
                         [(BA, 4000, 5000, 4750, "mid")])  # só a Thais no acesso
        self.assertEqual((r["fora_do_acesso"], p["resumo"]), (1, f"#{id_} Mussarela de setembro"))
        r, p = f.executar("andamento_acao", {"acao": objetivo})
        self.assertEqual(r["andamento_da_equipe"]["realizado"], 4750)
        _, p = f.executar("andamento_acao", {"acao": 9999})
        self.assertIn("não encontrad", p["erro"])

    def test_rascunho_na_conversa(self):
        conversas = Conversas(self.banco)
        rascunho = {"id": "0b6f6a1e-2f0c-4a57-8a43-6d2b3f1e9a10", "nome": "Bebidas"}
        conversa = "2c9e5d0b-7a1f-4f3e-9d6c-1b2a3c4d5e6f"
        conversas.acrescentar(self.ana["id"], conversa, "crie", {"texto": "pronto", "rascunhos": [rascunho]})
        conversas.acrescentar(self.ana["id"], conversa, "e agora?", {"texto": "nada", "rascunhos": None})
        self.assertEqual(conversas.rascunho(self.ana["id"], rascunho["id"]), rascunho)
        self.assertIsNone(conversas.rascunho(self.chefe["id"], rascunho["id"]))  # conversa de outra pessoa
        self.assertIsNone(conversas.rascunho(self.ana["id"], "nao-e-uuid"))
        mensagem = conversas.obter(self.ana["id"], conversa)["mensagens"][1]
        self.assertEqual(json.loads(json.dumps(mensagem["rascunhos"])), [rascunho])


class TestIndicadoresNoBanco(ComCache, BaseBanco):
    """Os tipos de indicador gravados no PostgreSQL e os dias de atendimento das áreas."""

    def setUp(self):
        super().setUp()
        self.montar_cache(extras=True)
        self.gestao = Gestao(self.banco, self.calc, self.assistente, hoje=lambda: HOJE)
        self.chefe = {"id": self.criar_usuario("chefe", "admin"), "login": "chefe", "nome": "Chefe", "papel": "admin"}

    def tearDown(self):
        self.desmontar_cache()
        super().tearDown()

    def criar(self, metrica, nome="Ação", regiao="BA", vendedores=(BA, EDIR), **mudancas):
        dados = {"nome": nome, "regiao": regiao, "inicio": "2026-09-01", "fim": "2026-09-30", "metrica": metrica,
                 "meta_padrao": 30, "vendedores": list(vendedores), **mudancas}
        return self.gestao.criar(self.chefe, dados)["id"]

    def detalhe(self, id_):
        return self.gestao.detalhe(self.chefe, (None, None), id_)

    def test_parametros_e_precos_gravados(self):
        id_ = self.criar("preco_medio", regiao="ES", vendedores=[ES], metas_produto=[{"id": 32, "meta": 30},
                                                                                     {"id": 27, "meta": 10}],
                         inicio="2026-07-01", fim="2026-07-31")
        d = self.detalhe(id_)
        self.assertEqual(d["item"]["metas_produto"], [{"id": 27, "meta": 10.0}, {"id": 32, "meta": 30.0}])
        self.assertEqual(d["indicador"]["nome"], "Preço médio")
        rubens, = d["linhas"]  # julho congelado: índice 1310 ÷ 1250; em junho, sem venda (sem base)
        self.assertAlmostEqual(rubens["resultado"], 1310 / 1250, places=4)
        self.assertEqual((rubens["base"], rubens["alvo"], rubens["classe"]), (None, 1.0, "ok"))
        id_ = self.criar("positivacao", parametros={"clientes": "recuperados", "dias_sem_compra": 22}, alvo_tipo="mais",
                         meta_padrao=1)
        d = self.detalhe(id_)
        self.assertEqual(d["item"]["parametros"], {"clientes": "recuperados", "dias_sem_compra": 22})
        # setembro ainda sem folga nos dados: o resultado é provisório
        self.assertEqual((d["item"]["provisorio"], {x["id"]: x["resultado"] for x in d["linhas"]}), (True, {BA: 1, EDIR: 0}))
        self.gestao.atualizar(self.chefe, id_, {"nome": "Agora mix", "inicio": "2026-09-01", "fim": "2026-09-30",
                                                "metrica": "mix_medio", "meta_padrao": 1.2, "vendedores": [BA]})
        c = self.detalhe(id_)["item"]
        self.assertEqual((c["metrica"], c["parametros"], c["metas_produto"], c["rotulo"]),
                         ("mix_medio", {"clientes": "todos"}, [], "Mix"))  # sem rótulo, o do indicador

    def test_dias_de_atendimento(self):
        cfg = {a["id"]: a for a in self.gestao.config_areas()["areas"]}
        self.assertEqual(cfg[209]["dias"], [1])  # da planilha (migração 008), mesmo sem clientes no cache
        self.assertEqual((cfg[3]["nome"], cfg[3]["dias"], cfg[3]["sugestao"], cfg[3]["ativos"]),
                         ("ROTA 3 (SEXTA)", None, [5], 2))
        self.gestao.definir_areas(self.chefe, {"1": [3, 3], 2: [4], 3: []})
        cfg = {a["id"]: a for a in self.gestao.config_areas()["areas"]}
        self.assertEqual((cfg[1]["dias"], cfg[2]["dias"], cfg[3]["dias"]), ([3], [4], []))
        self.assertEqual((cfg[1]["nome"], cfg[1]["atualizada_por_nome"]), ("ROTA 1", "Chefe"))
        self.gestao.definir_areas(self.chefe, {3: None})
        self.assertIsNone({a["id"]: a for a in self.gestao.config_areas()["areas"]}[3]["dias"])
        for errado in ({1: [8]}, {"x": [1]}, {1: "segunda"}):
            with self.assertRaises(ValueError):
                self.gestao.definir_areas(self.chefe, errado)

    def test_efetividade(self):
        self.gestao.definir_areas(self.chefe, {1: [3], 2: [4]})
        id_ = self.criar("efetividade", regiao="ES", vendedores=[ES])
        fat = self.criar("faturamento", "Faturamento", regiao="ES", vendedores=[ES], alvo_tipo="mais", meta_padrao=100)
        d = self.detalhe(id_)
        rubens, = d["linhas"]  # 1 pedido em 5 quartas com 2 visitas: 0,5 ÷ 5 dias; em agosto, nenhum pedido
        self.assertEqual((rubens["resultado"], rubens["base"], rubens["alvo"], rubens["dias"]), (0.1, 0, 0.3, 5))
        self.assertEqual(d["abertura"]["por"], "area")  # a efetividade já abre por área
        self.assertIn("2 clientes", d["avisos"][0])  # a ROTA 3, pendente
        # a ROTA 3 ganha a sexta: a conta é refeita (as contas guardadas dependem dos dias das áreas). Entram 4 sextas
        # sem pedido; o pedido do hotel foi num sábado (5/9) e continua fora
        self.gestao.definir_areas(self.chefe, {3: [5]})
        self.assertAlmostEqual(self.detalhe(id_)["linhas"][0]["resultado"], 0.5 / 9, places=4)
        # sem os pedidos no cache, só a efetividade fica sem números
        self.calc.cache.sem_pedidos = True
        d = self.detalhe(id_)
        self.assertIn("pedidos de venda ainda não chegaram", d["aviso"])
        cartoes = {a["id"]: a for a in self.gestao.quadro(self.chefe, (None, None), "ES")["acoes"]}
        self.assertIn("pedidos de venda", cartoes[id_]["aviso"])
        self.assertIsNone(cartoes[fat]["aviso"])
        self.assertEqual(self.detalhe(fat)["linhas"][0]["resultado"], 1480)

    def test_migracao_010_mede_de_novo_a_base_da_efetividade(self):
        from bi.banco import MIGRACOES
        self.gestao.definir_areas(self.chefe, {1: [3], 2: [4]})
        # base de 1 a 15/9: quartas 2/9 (1 pedido ÷ 2 visitas) e 9/9 (nenhum) = 25%; a conta antiga contava também
        # o pedido da terça 15/9 e dava 2 ÷ 4 = 50%
        id_ = self.criar("efetividade", regiao="ES", vendedores=[ES], inicio="2026-09-16", fim="2026-09-30")
        self.assertEqual(self.detalhe(id_)["linhas"][0]["base"], 0.25)
        with self.banco.conexao() as con:  # como a conta antiga tinha gravado
            con.execute("UPDATE campanha_vendedores SET base = 0.5, base_num = 2, base_den = 4 WHERE campanha = %s", [id_])
            con.execute("UPDATE gestao_eventos SET dados = dados || '{\"base\": 0.5}'::jsonb WHERE campanha = %s", [id_])
            con.execute((MIGRACOES / "010_efetividade_media_diaria.sql").read_text(encoding="utf-8"))
        self.assertEqual(self.detalhe(id_)["linhas"][0]["base"], 0.25)
        with self.banco.conexao() as con:
            dados, = con.execute("SELECT dados FROM gestao_eventos WHERE campanha = %s AND tipo = 'lancada'", [id_]).fetchone()
            base_num, = con.execute("SELECT base_num FROM campanha_vendedores WHERE campanha = %s", [id_]).fetchone()
        self.assertEqual((dados["base"], dados["base_pendente"], float(base_num)), (0.25, False, 1.0))


class TestMigracao008(BaseBanco):
    def test_converte_as_campanhas_antigas(self):
        from unittest import mock
        from bi.banco import Banco
        todas = Banco._arquivos_migracao()
        with mock.patch.object(Banco, "_arquivos_migracao", staticmethod(lambda: [a for a in todas if a.stem < "008"])):
            self.banco.migrar()
        dono = self.criar_usuario("ana")
        with self.banco.conexao() as con:
            for nome, metrica in (("F", "faturamento"), ("V", "volume"), ("M", "mix"), ("P", "positivacao")):
                con.execute("INSERT INTO campanhas (nome, inicio, fim, metrica, criada_por, criada_por_nome) VALUES "
                            "(%s, '2026-09-01', '2026-09-30', %s, %s, 'Ana')", [nome, metrica, dono])
        self.assertEqual(self.banco.migrar(), ["008_indicadores", "009_gestao_equipe", "010_efetividade_media_diaria"])
        with self.banco.conexao() as con:
            campanhas = {n: (m, p) for n, m, p in con.execute("SELECT nome, metrica, parametros FROM campanhas")}
            dias = {a: list(d) for a, d in con.execute("SELECT id_area, dias FROM areas_atendimento")}
        self.assertEqual(campanhas, {
            "F": ("personalizada", {"medida": "faturamento", "forma": "total"}),
            "V": ("personalizada", {"medida": "volume", "forma": "total"}),
            "M": ("personalizada", {"medida": "produtos", "forma": "total"}),
            "P": ("positivacao", {"clientes": "todos"}),
        })
        self.assertEqual((len(dias), dias[209], dias[343], dias[349], dias[261]), (84, [1], [2], [2], [6]))
        with self.assertRaises(Exception) as e:
            with self.banco.conexao() as con:
                con.execute("UPDATE campanhas SET metrica = 'faturamento'")
        self.assertIn("campanhas_metrica_check", str(e.exception))


class TestMigracao009(BaseBanco):
    def test_arquiva_as_campanhas_antigas_e_confere(self):
        from unittest import mock
        from bi.banco import Banco
        todas = Banco._arquivos_migracao()
        with mock.patch.object(Banco, "_arquivos_migracao", staticmethod(lambda: [a for a in todas if a.stem < "009"])):
            self.banco.migrar()
        dono = self.criar_usuario("ana")
        with self.banco.conexao() as con:
            id_ = con.execute("INSERT INTO campanhas (nome, inicio, fim, metrica, criada_por, criada_por_nome) VALUES "
                              "('Antiga', '2026-09-01', '2026-09-30', 'positivacao', %s, 'Ana') RETURNING id",
                              [dono]).fetchone()[0]
            con.execute("INSERT INTO campanha_vendedores (campanha, id_vendedor) VALUES (%s, 124)", [id_])
        self.assertEqual(self.banco.migrar(), ["009_gestao_equipe", "010_efetividade_media_diaria"])
        with self.banco.conexao() as con:
            linha = con.execute("SELECT tipo, regiao, arquivada, versao, alvo_tipo, rotulo FROM campanhas").fetchone()
            entrou, = con.execute("SELECT entrou_em IS NOT NULL FROM campanha_vendedores").fetchone()
        self.assertEqual((*linha, entrou), ("acao", None, True, 1, "fixo", "", True))
        recusas = {
            "campanhas_regiao_check": "UPDATE campanhas SET arquivada = false, base_inicio = '2026-08-02', "
                                      "base_fim = '2026-08-31'",
            "campanhas_objetivo_check": "INSERT INTO campanhas (tipo, nome, regiao, inicio, fim, metrica, alvo_tipo, "
                                        "criada_por_nome) VALUES ('objetivo', 'O', 'BA', '2026-09-01', '2026-09-30', "
                                        "'positivacao', 'mais', 'Ana')",
            "campanhas_base_check": "INSERT INTO campanhas (nome, regiao, inicio, fim, metrica, base_inicio, "
                                    "criada_por_nome) VALUES ('A', 'BA', '2026-09-01', '2026-09-30', 'positivacao', "
                                    "'2026-08-01', 'Ana')",
            "campanhas_janela_check": "INSERT INTO campanhas (nome, regiao, inicio, fim, metrica, criada_por_nome) "
                                      "VALUES ('A', 'BA', '2026-09-01', '2026-09-30', 'positivacao', 'Ana')",
            "gestao_eventos_nota_check": "INSERT INTO gestao_eventos (id_vendedor, tipo, texto, criada_por_nome) "
                                         "VALUES (124, 'nota', '  ', 'Ana')",
            "gestao_eventos_acao_check": "INSERT INTO gestao_eventos (id_vendedor, tipo, criada_por_nome) "
                                         "VALUES (124, 'lancada', 'Ana')",
        }
        for nome, sql in recusas.items():
            with self.assertRaises(Exception, msg=nome) as e:
                with self.banco.conexao() as con:
                    con.execute(sql)
            self.assertIn(nome, str(e.exception))


if __name__ == "__main__":
    unittest.main()

"""Página Gestão (bi/gestao.py): o andamento das campanhas sobre o cache sintético, a conferência do que vem da página
ou do Assistente, as campanhas no PostgreSQL e as ferramentas de campanha do Assistente.

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from bi.assistente import FERRAMENTAS, Ferramentas
from bi.conversas import Conversas, NaoEncontrada
from bi.gestao import Gestao, andamento, calendario_periodo, status_inicial, sugestao, validar
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

    def test_calendario_e_sugestao(self):
        c = calendario_periodo(self.cal, D(2026, 9, 1), D(2026, 9, 30), "ES", D(2026, 9, 15))
        self.assertEqual(c["situacao"], "aberto")
        self.assertEqual(c["dias_uteis"], 21)  # setembro de 2026 no ES: 22 dias de semana menos o 7 de setembro
        self.assertLess(c["dias_decorridos"], c["dias_uteis"])
        camp = {"status": "planejada", **SETEMBRO}
        self.assertIsNone(sugestao(camp, D(2026, 8, 31)))
        self.assertEqual(sugestao(camp, D(2026, 9, 1))["status"], "andamento")
        self.assertEqual(sugestao(camp, D(2026, 10, 1))["status"], "concluida")
        self.assertIsNone(sugestao({**camp, "status": "andamento"}, D(2026, 9, 30)))
        self.assertEqual(sugestao({**camp, "status": "andamento"}, D(2026, 10, 1))["texto"], "Terminou em 30/09")
        self.assertEqual(status_inicial(D(2026, 9, 1), D(2026, 9, 30), D(2026, 8, 1)), "planejada")
        self.assertEqual(status_inicial(D(2026, 9, 1), D(2026, 9, 30), D(2026, 9, 10)), "andamento")
        self.assertEqual(status_inicial(D(2026, 9, 1), D(2026, 9, 30), D(2026, 10, 10)), "concluida")


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
        a = andamento(self.cur, c, self.regras, self.cal, data_ref, None, self.AREAS, abrir)
        return {v["id"]: v for v in a["vendedores"]}, a

    def test_efetividade(self):
        por, a = self.medir("efetividade", meta=30, abrir="padrao")
        # ES: 2 pedidos (o cancelado, o orçamento, o da área sem dia e o de funcionário não contam) ÷ 2 clientes da
        # ROTA 1 × 5 quartas; BA: 3 pedidos (um do bloqueado e um feito pelo ES na carteira dela) ÷ 2 × 4 quintas
        self.assertEqual({v: (x["numerador"], x["denominador"], x["realizado"]) for v, x in por.items()},
                         {ES: (2, 10, 0.2), BA: (3, 8, 0.375), EDIR: (0, 0, None)})
        self.assertEqual((por[ES]["meta"], por[ES]["status"], por[BA]["status"], por[EDIR]["status"]),
                         (0.3, "abaixo", "batida", "sem_dados"))
        self.assertAlmostEqual(a["total"]["realizado"], 5 / 18, places=4)
        self.assertEqual((a["total"]["numerador"], a["total"]["denominador"]), (5, 18))
        self.assertEqual({x["nome"]: x["valor"] for x in a["abertura"]["linhas"]}, {"ROTA 1": 0.2, "ROTA 2": 0.375})
        self.assertIn("4 clientes ativos da carteira ficaram fora", a["avisos"][0])  # ROTA 3 (2) e sem área (2)
        self.assertEqual(a["indicador"]["formato"], "pct")
        por, _ = self.medir("efetividade", meta=30, data_ref=D(2026, 9, 15))
        self.assertEqual({v: por[v]["realizado"] for v in (ES, BA)}, {ES: 0.5, BA: 0.5})  # 2 quartas e 2 quintas
        self.assertEqual(por[BA]["status"], "no_ritmo")  # aberto: na meta é "no ritmo", não "batida"

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


class TestValidar(ComCache, unittest.TestCase):
    def setUp(self):
        self.montar_cache()

    def tearDown(self):
        self.desmontar_cache()

    def validar(self, permitidos=None, **mudancas):
        dados = {"nome": "  Mussarela   de setembro ", "inicio": "2026-09-01", "fim": "2026-09-30",
                 "metrica": "faturamento", "meta_padrao": 1000, "vendedores": [ES, {"id": BA, "meta": 500}], **mudancas}
        return validar(dados, self.cur, self.regras, permitidos, D(2026, 9, 30))

    def erro(self, texto, **mudancas):
        with self.assertRaises(ValueError) as e:
            self.validar(**mudancas)
        self.assertIn(texto, str(e.exception))

    def test_normaliza(self):
        d = self.validar(filtros={"produtos": [3643, 32], "ufs": ["es"], "linhas": ["mussarela"], "grupos": ["OUTRAS"]})
        self.assertEqual(d["nome"], "Mussarela de setembro")
        self.assertEqual(d["filtros"], {"produtos": [11469, 32], "grupos": ["outras"], "linhas": ["MUSSARELA"],
                                        "ufs": ["ES"]})
        self.assertEqual(d["vendedores"], [{"id": ES, "meta": None}, {"id": BA, "meta": 500.0}])
        self.assertEqual((d["inicio"], d["fim"]), (D(2026, 9, 1), D(2026, 9, 30)))
        self.assertNotIn("categorias", d["filtros"])  # filtro vazio não fica

    def test_erros(self):
        self.erro("nome", nome=" ")
        self.erro("antes do início", fim="2026-08-01")
        self.erro("até um ano", fim="2027-12-31")
        self.erro("métrica", metrica="lucro")
        self.erro("vendedores", vendedores=[])
        self.erro("não encontrado: 777", vendedores=[777])
        self.erro("produto não encontrado", filtros={"produtos": [123456]})
        self.erro("não conta", filtros={"produtos": [999]})
        self.erro("linha não encontrada", filtros={"linhas": ["chocolate"]})
        self.erro("categoria", filtros={"categorias": ["Sorvete"]})
        self.erro("filtro desconhecido", filtros={"cidades": ["Serra"]})
        self.erro("meta", meta_padrao=-1)

    def test_volume_precisa_da_mesma_unidade(self):
        self.erro("filtro de produto", metrica="volume")
        self.erro("unidades diferentes (KG, UN)", metrica="volume", filtros={"produtos": [32, 27]})
        d = self.validar(metrica="volume", filtros={"produtos": [32]})  # a métrica de antes vira Personalizada
        self.assertEqual((d["metrica"], d["parametros"]), ("personalizada", {"medida": "volume", "forma": "total",
                                                                             "clientes": "todos"}))
        d = self.validar(metrica="personalizada", parametros={"medida": "volume", "forma": "por_cliente"},
                         filtros={"produtos": [32]})
        self.assertEqual(d["parametros"]["forma"], "por_cliente")

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
        d = self.validar(metrica="preco_medio", metas_produto=[{"id": 3643, "meta": 9.5}, {"id": 32, "meta": 30}])
        self.assertEqual(d["metas_produto"], [{"id": 11469, "meta": 9.5}, {"id": 32, "meta": 30.0}])
        self.assertEqual((d["meta_padrao"], d["vendedores"][1]["meta"]), (100.0, None))  # meta = 100% do alvo
        d = self.validar(metrica="positivacao", filtros={"areas": ["rota 1"], "segmentos": ["padaria"]})
        self.assertEqual(d["filtros"], {"segmentos": ["PADARIA"], "areas": ["ROTA 1"]})
        self.erro("área comercial não encontrada", metrica="positivacao", filtros={"areas": ["ROTA 9"]})

    def test_historico_da_base_e_do_crescimento(self):
        inicio = D(2026, 1, 1)
        validar_ = lambda **m: validar({"nome": "x", "inicio": "2026-09-01", "fim": "2026-09-30", "metrica": "positivacao",
                                        "vendedores": [ES], **m}, self.cur, self.regras, None, D(2026, 9, 30), inicio)
        validar_(parametros={"clientes": "recuperados", "dias_sem_compra": 200})
        with self.assertRaises(ValueError) as e:
            validar_(parametros={"clientes": "recuperados", "dias_sem_compra": 250})
        self.assertIn("histórico", str(e.exception))
        crescer = {"medida": "faturamento", "forma": "crescimento"}
        self.assertEqual(validar_(metrica="personalizada", parametros=crescer)["parametros"]["comparar"], "periodo_anterior")
        with self.assertRaises(ValueError) as e:
            validar_(metrica="personalizada", parametros={**crescer, "comparar": "ano_anterior"})
        self.assertIn("período de comparação (01/09/2025 a 30/09/2025)", str(e.exception))

    def test_fora_do_acesso(self):
        with self.assertRaises(ValueError) as e:
            self.validar(permitidos=frozenset({ES}))
        self.assertIn("Thais (141)", str(e.exception))
        self.assertEqual(len(self.validar(permitidos=frozenset({ES}), vendedores=[ES])["vendedores"]), 1)


class TestFerramentasDeCampanha(ComCache, unittest.TestCase):
    """As ferramentas do Assistente que não precisam do banco: propor (não grava) e a recusa sem a página."""

    def setUp(self):
        self.montar_cache()
        self.gestao = Gestao(None, self.calc, self.assistente)  # propor não toca no banco

    def tearDown(self):
        self.desmontar_cache()

    ARGS = {"nome": "Bebidas BA", "descricao": "", "premiacao": "Vale-compras", "inicio": "2026-09-01",
            "fim": "2026-09-30", "metrica": "VOLUME", "meta_padrao": 30, "metas": [{"id_vendedor": BA, "meta": 50}],
            "vendedores": [ES], "equipes": [], "produtos": [3643], "linhas": [], "categorias": [], "grupos": [],
            "ufs": [], "segmentos": []}

    def test_propor_nao_grava_e_devolve_o_rascunho(self):
        f = Ferramentas(self.assistente.recorte(None), self.calc, self.assistente.cfg, None,
                        gestao=self.gestao.contexto(USUARIO_VIS, (None, None)))
        r, p = f.executar("propor_campanha", dict(self.ARGS))
        self.assertIsNone(p["erro"])
        self.assertIn("AINDA NÃO CRIADO", r["situacao"])
        self.assertEqual([(v["id"], v["meta"]) for v in r["rascunho"]["vendedores"]], [(ES, 30), (BA, 50)])
        self.assertEqual(r["rascunho"]["filtros"]["produtos"], ["11469 BEBIDA LACTEA 500G"])
        self.assertEqual(r["rascunho"]["unidade"], "UN")
        rascunho, = f.rascunhos
        self.assertEqual((rascunho["metrica"], rascunho["parametros"]["medida"], rascunho["inicio"]),
                         ("personalizada", "volume", "2026-09-01"))
        self.assertEqual((rascunho["indicador"]["nome"], rascunho["indicador"]["unidade"]), ("Volume", "UN"))
        self.assertIn(f"rascunho {rascunho['id']}", p["resumo"])
        # erro de conferência volta para a IA corrigir
        _, p = f.executar("propor_campanha", {**self.ARGS, "produtos": [32, 27]})
        self.assertIn("unidades diferentes", p["erro"])
        self.assertEqual(len(f.rascunhos), 1)

    def test_propor_tipos_novos(self):
        f = Ferramentas(self.assistente.recorte(None), self.calc, self.assistente.cfg, None,
                        gestao=self.gestao.contexto(USUARIO_VIS, (None, None)))
        base = {"nome": "Teste", "inicio": "2026-09-01", "fim": "2026-09-30", "meta_padrao": 0, "vendedores": [ES]}
        r, p = f.executar("propor_campanha", {**base, "metrica": "preco_medio",
                                              "metas_produto": [{"id_produto": 32, "meta": 31}]})
        self.assertIsNone(p["erro"])
        self.assertEqual((r["rascunho"]["indicador"], r["rascunho"]["meta_em_percentual"]), ("Preço médio", True))
        self.assertEqual(r["rascunho"]["precos_alvo"], [{"produto": "32 QUEIJO MUSSARELA 4KG", "meta": 31.0}])
        self.assertEqual(f.rascunhos[-1]["metas_produto"], [{"id": 32, "meta": 31.0}])
        r, p = f.executar("propor_campanha", {**base, "metrica": "positivacao", "clientes_base": "recuperados",
                                              "dias_sem_compra": 60, "areas": ["rota 1"]})
        self.assertIsNone(p["erro"])
        self.assertEqual((f.rascunhos[-1]["parametros"], f.rascunhos[-1]["filtros"]),
                         ({"clientes": "recuperados", "dias_sem_compra": 60}, {"areas": ["ROTA 1"]}))
        _, p = f.executar("propor_campanha", {**base, "metrica": "personalizada", "medida": "faturamento",
                                              "forma": "crescimento", "comparar": "ano_anterior", "meta_padrao": 10})
        self.assertIn("período de comparação", p["erro"])  # o histórico dos testes começa em 2026
        # o enum da ferramenta acompanha os tipos de bi/indicadores.py
        from bi.indicadores import TIPOS
        propor = next(t for t in FERRAMENTAS if t["name"] == "propor_campanha")["input_schema"]["properties"]
        self.assertEqual(propor["metrica"]["enum"], list(TIPOS))

    def test_equipes_e_acesso(self):
        ctx = self.gestao.contexto(USUARIO_VIS, ({ES, BA}, None))
        f = Ferramentas(self.assistente.recorte(None), self.calc, self.assistente.cfg, None, gestao=ctx)
        r, p = f.executar("propor_campanha", {**self.ARGS, "metas": [], "vendedores": [], "equipes": ["BA", "ES"]})
        self.assertIsNone(p["erro"])
        self.assertEqual({v["id"] for v in r["rascunho"]["vendedores"]}, {ES, BA})  # Edir fora do acesso
        _, p = f.executar("propor_campanha", {**self.ARGS, "vendedores": [EDIR]})
        self.assertIn("fora do seu acesso", p["erro"])

    def test_sem_a_pagina_gestao(self):
        f = Ferramentas(self.assistente.recorte(None), self.calc, self.assistente.cfg, None)
        for nome, args in (("listar_campanhas", {"texto": "", "incluir_arquivadas": False}),
                           ("andamento_campanha", {"campanha": 1}), ("propor_campanha", dict(self.ARGS))):
            _, p = f.executar(nome, args)
            self.assertIn("não inclui a página Gestão", p["erro"], nome)

    def test_esquemas_strict(self):
        """Ferramentas strict: a API aceita no máximo 24 parâmetros opcionais no pedido inteiro e recusa uma gramática
        grande demais (a do rascunho de campanha passava)."""
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
        # o rascunho de campanha fica fora do strict: com ele a gramática passa do limite da API
        self.assertEqual([t["name"] for t in FERRAMENTAS if not t.get("strict")], ["propor_campanha"])

    def test_laco_guarda_os_rascunhos(self):
        api = ClienteFalso([
            resposta(bloco_ferramenta("t1", "propor_campanha", dict(self.ARGS)), parada="tool_use"),
            resposta(bloco_texto("O rascunho está pronto para conferir.")),
        ])
        conversas = ConversasFalsas()
        a = criar_assistente(self.pasta, self.calc, cliente=api, conversas=conversas)
        ctx = Gestao(None, self.calc, a).contexto(USUARIO_VIS, (None, None))
        r = a.perguntar(USUARIO_VIS, None, "crie uma campanha de bebida láctea em setembro", None, None, ctx)
        rascunho, = r["rascunhos"]
        self.assertEqual(rascunho["nome"], "Bebidas BA")
        self.assertIn(f"propor_campanha -> rascunho {rascunho['id']}", r["consultas"])
        self.assertIn("Campanhas (página Gestão): pode criar", api.pedidos[0]["system"][1]["text"])
        gravada, = conversas.dados.values()
        self.assertEqual(gravada["mensagens"][1]["rascunhos"][0]["id"], rascunho["id"])
        # sem a página: a ferramenta recusa e a resposta não tem rascunho
        api = ClienteFalso([
            resposta(bloco_ferramenta("t1", "propor_campanha", dict(self.ARGS)), parada="tool_use"),
            resposta(bloco_texto("Seu acesso não inclui a Gestão.")),
        ])
        b = criar_assistente(self.pasta, self.calc, cliente=api)
        r = b.responder(USUARIO_VIS, [{"papel": "usuario", "texto": "crie"}], None, None)
        self.assertEqual(r["rascunhos"], [])
        self.assertIn("o acesso não inclui", api.pedidos[0]["system"][1]["text"])


class TestCampanhasNoBanco(ComCache, BaseBanco):
    def setUp(self):
        super().setUp()
        self.montar_cache()
        self.gestao = Gestao(self.banco, self.calc, self.assistente)
        ids = {login: self.criar_usuario(login, papel) for login, papel in
               (("chefe", "admin"), ("ana", "visualizador"), ("bia", "visualizador"))}
        self.chefe = {"id": ids["chefe"], "login": "chefe", "nome": "Chefe", "papel": "admin"}
        self.ana = {"id": ids["ana"], "login": "ana", "nome": "Ana", "papel": "visualizador"}
        self.bia = {"id": ids["bia"], "login": "bia", "nome": "Bia", "papel": "visualizador"}

    def tearDown(self):
        self.desmontar_cache()
        super().tearDown()

    def dados(self, nome="Mussarela", **mudancas):
        return {"nome": nome, "inicio": "2026-09-01", "fim": "2026-09-30", "metrica": "faturamento",
                "meta_padrao": 1000, "vendedores": [ES, BA], **mudancas}

    def criar(self, usuario, nome="Mussarela", escopo=(None, None), rascunho=None, **mudancas):
        return self.gestao.criar(usuario, self.dados(nome, **mudancas), escopo, rascunho)["id"]

    def quadro(self, usuario, **kw):
        return [c["nome"] for c in self.gestao.listar(usuario, (None, None), **kw)["campanhas"]]

    def test_criar_obter_e_andamento(self):
        id_ = self.criar(self.ana, descricao="Foco em mussarela", vendedores=[ES, {"id": BA, "meta": 5000}])
        r = self.gestao.obter(self.ana, id_, (None, None))
        c, a = r["campanha"], r["andamento"]
        self.assertEqual((c["nome"], c["status"], c["criada_por_nome"], c["minha"]), ("Mussarela", "concluida", "Ana", True))
        self.assertEqual(c["vendedores"], [{"id": ES, "meta": None}, {"id": BA, "meta": 5000.0}])
        self.assertEqual({v["id"]: (v["realizado"], v["meta"]) for v in a["vendedores"]}, {ES: (1480, 1000), BA: (4750, 5000)})
        cartao, = self.gestao.listar(self.ana, (None, None))["campanhas"]
        self.assertEqual(cartao["resumo"]["realizado"], 6230)  # o card concluído traz o total para a barra
        # só os vendedores do acesso de quem vê
        a = self.gestao.obter(self.ana, id_, ({ES}, None))["andamento"]
        self.assertEqual(([v["id"] for v in a["vendedores"]], a["ocultos"]), ([ES], 1))
        with self.assertRaises(ValueError):  # e só eles entram numa campanha nova
            self.criar(self.ana, escopo=({ES}, None))

    def test_cada_um_ve_as_suas(self):
        self.criar(self.ana, "Da Ana")
        self.criar(self.bia, "Da Bia")
        self.assertEqual(self.quadro(self.ana), ["Da Ana"])
        self.assertEqual(self.quadro(self.bia, todas=True), ["Da Bia"])  # "todas" é só do administrador
        self.assertEqual(self.quadro(self.chefe), [])
        self.assertEqual(sorted(self.quadro(self.chefe, todas=True)), ["Da Ana", "Da Bia"])
        da_bia = self.gestao.listar(self.bia, (None, None))["campanhas"][0]["id"]
        for acao in (lambda: self.gestao.obter(self.ana, da_bia, (None, None)),
                     lambda: self.gestao.mover(self.ana, da_bia, "planejada"),
                     lambda: self.gestao.excluir(self.ana, da_bia),
                     lambda: self.gestao.atualizar(self.ana, da_bia, self.dados("Roubada"), (None, None))):
            with self.assertRaises(NaoEncontrada):
                acao()
        self.gestao.atualizar(self.chefe, da_bia, self.dados("Da Bia, revista"), (None, None))  # o admin mexe em todas
        c = self.gestao.obter(self.bia, da_bia, (None, None))["campanha"]
        self.assertEqual((c["nome"], c["atualizada_por_nome"]), ("Da Bia, revista", "Chefe"))

    def test_rascunho_cria_uma_vez_so(self):
        rascunho = "6f1c2a0e-58d4-4c47-9b1f-0d3a5e7b9c21"
        primeira = self.gestao.criar(self.ana, self.dados(), (None, None), rascunho)
        segunda = self.gestao.criar(self.ana, self.dados("Outro nome"), (None, None), rascunho)
        self.assertEqual((segunda["id"], segunda["ja_existia"]), (primeira["id"], True))
        self.assertEqual(self.contar("campanhas"), 1)
        with self.assertRaises(ValueError):
            self.gestao.criar(self.bia, self.dados(), (None, None), rascunho)
        self.assertEqual(self.gestao.criadas_por_rascunho(self.ana, [rascunho, "lixo"]),
                         {rascunho: {"id": primeira["id"], "nome": "Mussarela"}})
        self.assertEqual(self.gestao.criadas_por_rascunho(self.bia, [rascunho]), {})

    def test_mover_e_ordem(self):
        futuro = {"inicio": "2030-01-01", "fim": "2030-01-31"}
        a, b, c = (self.criar(self.ana, n, **futuro) for n in "ABC")
        self.assertEqual(self.quadro(self.ana), ["C", "B", "A"])  # a nova entra no topo de Planejada
        self.gestao.mover(self.ana, a, "planejada", antes_de=c)
        self.assertEqual(self.quadro(self.ana), ["A", "C", "B"])
        self.gestao.mover(self.ana, c, "andamento")
        cards = {x["nome"]: x for x in self.gestao.listar(self.ana, (None, None))["campanhas"]}
        self.assertEqual(cards["C"]["status"], "andamento")
        self.assertEqual(cards["C"]["atualizada_por_nome"], "Ana")
        with self.assertRaises(ValueError):
            self.gestao.mover(self.ana, b, "lixeira")

    def test_arquivar_e_excluir(self):
        id_ = self.criar(self.ana)
        self.gestao.arquivar(self.ana, id_)
        self.assertEqual(self.quadro(self.ana), [])
        self.assertEqual(self.quadro(self.ana, arquivadas=True), ["Mussarela"])
        self.gestao.arquivar(self.ana, id_, False)
        self.assertEqual(self.quadro(self.ana), ["Mussarela"])
        self.gestao.excluir(self.ana, id_)
        self.assertEqual((self.contar("campanhas"), self.contar("campanha_vendedores")), (0, 0))

    def test_usuario_excluido_deixa_a_campanha_sem_dono(self):
        self.criar(self.ana, "Da Ana")
        with self.banco.conexao() as con:
            con.execute("DELETE FROM usuarios WHERE id = %s", [self.ana["id"]])
        c, = self.gestao.listar(self.chefe, (None, None), todas=True)["campanhas"]
        self.assertEqual((c["criada_por"], c["criada_por_nome"]), (None, "Ana"))

    def test_ferramentas_listar_e_andamento(self):
        id_ = self.criar(self.ana, "Mussarela de setembro")
        self.criar(self.bia, "Da Bia")
        f = Ferramentas(self.assistente.recorte(None), self.calc, self.assistente.cfg, None,
                        gestao=self.gestao.contexto(self.ana, (None, None)))
        r, p = f.executar("listar_campanhas", {"texto": "mussarela", "incluir_arquivadas": False})
        self.assertEqual([c["id"] for c in r["campanhas"]], [id_])
        r, p = f.executar("andamento_campanha", {"campanha": id_})
        self.assertIsNone(p["erro"])
        self.assertEqual({v["id"]: v["realizado"] for v in r["vendedores"]}, {ES: 1480, BA: 4750})
        pagina = self.gestao.obter(self.ana, id_, (None, None))["andamento"]
        self.assertEqual(r["total"], pagina["total"])  # os mesmos números da página
        self.assertEqual(p["resumo"], f"#{id_} Mussarela de setembro")
        da_bia = self.gestao.listar(self.bia, (None, None))["campanhas"][0]["id"]
        _, p = f.executar("andamento_campanha", {"campanha": da_bia})
        self.assertIn("não encontrada", p["erro"])

    def test_rascunho_na_conversa(self):
        conversas = Conversas(self.banco)
        rascunho = {"id": "0b6f6a1e-2f0c-4a57-8a43-6d2b3f1e9a10", "nome": "Bebidas"}
        conversa = "2c9e5d0b-7a1f-4f3e-9d6c-1b2a3c4d5e6f"
        conversas.acrescentar(self.ana["id"], conversa, "crie", {"texto": "pronto", "rascunhos": [rascunho]})
        conversas.acrescentar(self.ana["id"], conversa, "e agora?", {"texto": "nada", "rascunhos": None})
        self.assertEqual(conversas.rascunho(self.ana["id"], rascunho["id"]), rascunho)
        self.assertIsNone(conversas.rascunho(self.bia["id"], rascunho["id"]))  # conversa de outra pessoa
        self.assertIsNone(conversas.rascunho(self.ana["id"], "nao-e-uuid"))
        mensagem = conversas.obter(self.ana["id"], conversa)["mensagens"][1]
        self.assertEqual(json.loads(json.dumps(mensagem["rascunhos"])), [rascunho])


class TestIndicadoresNoBanco(ComCache, BaseBanco):
    """Os tipos novos gravados no PostgreSQL, os dias de atendimento das áreas e o quadro guardando as contas."""

    def setUp(self):
        super().setUp()
        self.montar_cache(extras=True)
        self.gestao = Gestao(self.banco, self.calc, self.assistente)
        self.ana = {"id": self.criar_usuario("ana"), "login": "ana", "nome": "Ana", "papel": "visualizador"}

    def tearDown(self):
        self.desmontar_cache()
        super().tearDown()

    def criar(self, metrica, nome="Campanha", **mudancas):
        dados = {"nome": nome, "inicio": "2026-09-01", "fim": "2026-09-30", "metrica": metrica, "meta_padrao": 30,
                 "vendedores": [ES, BA, EDIR], **mudancas}
        return self.gestao.criar(self.ana, dados, (None, None))["id"]

    def resumo(self, id_):
        return next(c for c in self.gestao.listar(self.ana, (None, None))["campanhas"] if c["id"] == id_)

    def test_parametros_e_precos_gravados(self):
        id_ = self.criar("preco_medio", metas_produto=[{"id": 32, "meta": 30}, {"id": 27, "meta": 10}],
                         inicio="2026-07-01", fim="2026-07-31")
        c = self.gestao.obter(self.ana, id_, (None, None))
        self.assertEqual(c["campanha"]["metas_produto"], [{"id": 27, "meta": 10.0}, {"id": 32, "meta": 30.0}])
        self.assertEqual(c["campanha"]["indicador"]["nome"], "Preço médio")
        self.assertAlmostEqual(c["andamento"]["total"]["realizado"], 1680 / 1650, places=4)
        id_ = self.criar("positivacao", parametros={"clientes": "recuperados", "dias_sem_compra": 22})
        c = self.gestao.obter(self.ana, id_, (None, None))
        self.assertEqual(c["campanha"]["parametros"], {"clientes": "recuperados", "dias_sem_compra": 22})
        self.assertEqual({v["id"]: v["realizado"] for v in c["andamento"]["vendedores"]}, {ES: 0, BA: 1, EDIR: 0})
        self.gestao.atualizar(self.ana, id_, {"nome": "Agora mix", "inicio": "2026-09-01", "fim": "2026-09-30",
                                              "metrica": "mix_medio", "meta_padrao": 1.2, "vendedores": [ES]}, (None, None))
        c = self.gestao.obter(self.ana, id_, (None, None))["campanha"]
        self.assertEqual((c["metrica"], c["parametros"], c["metas_produto"]), ("mix_medio", {"clientes": "todos"}, []))

    def test_dias_de_atendimento(self):
        cfg = {a["id"]: a for a in self.gestao.config_areas()["areas"]}
        self.assertEqual(cfg[209]["dias"], [1])  # da planilha (migração 008), mesmo sem clientes no cache
        self.assertEqual((cfg[3]["nome"], cfg[3]["dias"], cfg[3]["sugestao"], cfg[3]["ativos"]),
                         ("ROTA 3 (SEXTA)", None, [5], 2))
        self.gestao.definir_areas(self.chefe(), {"1": [3, 3], 2: [4], 3: []})
        cfg = {a["id"]: a for a in self.gestao.config_areas()["areas"]}
        self.assertEqual((cfg[1]["dias"], cfg[2]["dias"], cfg[3]["dias"]), ([3], [4], []))
        self.assertEqual((cfg[1]["nome"], cfg[1]["atualizada_por_nome"]), ("ROTA 1", "Chefe"))
        self.gestao.definir_areas(self.chefe(), {3: None})
        self.assertIsNone({a["id"]: a for a in self.gestao.config_areas()["areas"]}[3]["dias"])
        for errado in ({1: [8]}, {"x": [1]}, {1: "segunda"}):
            with self.assertRaises(ValueError):
                self.gestao.definir_areas(self.chefe(), errado)

    def chefe(self):
        return {"id": None, "login": "chefe", "nome": "Chefe", "papel": "admin"}

    def test_efetividade_no_quadro(self):
        self.gestao.definir_areas(self.chefe(), {1: [3], 2: [4]})
        id_ = self.criar("efetividade")
        fat = self.criar("faturamento", "Faturamento")
        r = self.resumo(id_)["resumo"]
        self.assertAlmostEqual(r["realizado"], 5 / 18, places=4)
        a = self.gestao.obter(self.ana, id_, (None, None))["andamento"]
        self.assertEqual(a["abertura"]["por"], "area")  # a efetividade já abre por área
        self.assertIn("4 clientes", a["avisos"][0])
        # a ROTA 3 ganha a sexta: o quadro refaz a conta (as contas guardadas dependem dos dias das áreas)
        self.gestao.definir_areas(self.chefe(), {3: [5]})
        self.assertAlmostEqual(self.resumo(id_)["resumo"]["realizado"], 6 / 26, places=4)  # +1 pedido, +2 × 4 sextas
        # sem os pedidos no cache, só a efetividade fica sem números
        self.calc.cache.sem_pedidos = True
        self.assistente.recorte(None).memo.clear()
        card = self.resumo(id_)
        self.assertIsNone(card["resumo"])
        self.assertIn("pedidos de venda ainda não chegaram", card["aviso"])
        self.assertEqual(self.resumo(fat)["resumo"]["realizado"], 6930)
        r = self.gestao.obter(self.ana, id_, (None, None))
        self.assertIsNone(r["andamento"])
        self.assertIn("pedidos de venda", r["aviso"])


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
        self.assertEqual(self.banco.migrar(), ["008_indicadores"])
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


if __name__ == "__main__":
    unittest.main()

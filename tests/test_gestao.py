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

    def montar_cache(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.calc = criar_calc(self.pasta, fora=(999,))
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
        self.assertEqual(self.validar(metrica="volume", filtros={"produtos": [32]})["metrica"], "volume")

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
        self.assertEqual((rascunho["metrica"], rascunho["inicio"]), ("volume", "2026-09-01"))
        self.assertIn(f"rascunho {rascunho['id']}", p["resumo"])
        # erro de conferência volta para a IA corrigir
        _, p = f.executar("propor_campanha", {**self.ARGS, "produtos": [32, 27]})
        self.assertIn("unidades diferentes", p["erro"])
        self.assertEqual(len(f.rascunhos), 1)

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


if __name__ == "__main__":
    unittest.main()

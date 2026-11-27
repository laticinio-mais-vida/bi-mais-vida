"""As listas de clientes do painel de desempenho da Gestão (Gestao.desempenho_clientes, bi/metas_clientes.py do_painel):
Positivação, Atendimentos, Mussarela e Outras linhas, sobre o cache sintético de tests/apoio.py, com os dias de
atendimento no PostgreSQL (ROTA 1 na quarta, ROTA 2 na quinta, ROTA 3 na sexta). Cada lista bate com a linha do painel.

Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import http.client
import json
import logging
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import app
from bi.gestao import Gestao
from bi.metas_clientes import ClientesDaMeta
from tests.apoio import BA, EDIR, ES, BaseBanco
from tests.test_gestao import ComCache
from tests.test_metas_clientes import MIX, ConfigCrmFixa, UsuariosFalsos

D = dt.date
AREAS = {1: [3], 2: [4], 3: [5]}
TODOS = (None, None)


class Base(ComCache, BaseBanco):
    def setUp(self):
        super().setUp()
        self.chefe = {"id": self.criar_usuario("chefe", "admin"), "login": "chefe", "nome": "Chefe", "papel": "admin"}

    def tearDown(self):
        self.desmontar_cache()
        super().tearDown()

    def montar(self, hoje=D(2026, 10, 1), mix=MIX, **opcoes):
        self.montar_cache(extras=True, **opcoes)
        self.gestao = Gestao(self.banco, self.calc, self.assistente, hoje=lambda: hoje)
        self.gestao.definir_areas(self.chefe, AREAS)
        self.gestao.listas_clientes = ClientesDaMeta(self.calc, ConfigCrmFixa(mix),
                                                     lambda: {ES: "Rubens", BA: "Thais", EDIR: "Edir"})

    def lista(self, lista, regiao="ES", periodo="ultimo_dia", vendedor=None, escopo=TODOS):
        return self.gestao.desempenho_clientes(self.chefe, escopo, regiao, periodo, lista, vendedor)

    def linha(self, indicador, onde="dia", regiao="ES", periodo="ultimo_dia"):
        v, = self.gestao.desempenho(self.chefe, TODOS, regiao, periodo)["vendedores"]
        return v[onde][indicador]


class TestAtendimentos(Base):
    def test_ultimo_dia_bate_com_o_painel(self):
        # quarta 30/9: o 1 e o 3 (ROTA 1) esperados, nenhum com pedido; o painel mostra 0 de 2
        self.montar()
        d = self.lista("atendimentos")
        self.assertEqual(d["resumo"], {"esperados": 2, "atendidos": 0, "nao_atendidos": 2, "fora_do_dia": 0})
        self.assertEqual(sorted((c["id"], c["dia"], c["frequencia"]) for c in d["itens"]),
                         [(1, "2026-09-30", "semanal"), (3, "2026-09-30", "semanal")])
        b = self.linha("atendimentos")
        self.assertEqual((b["real"], b["meta"]), (d["resumo"]["atendidos"], d["resumo"]["esperados"]))
        nome = self.gestao.desempenho(self.chefe, TODOS, "ES", "ultimo_dia")["vendedores"][0]["nome"]  # o do painel
        self.assertEqual((d["regiao"], d["periodo"]["inicio"], d["vendedores"]), ("ES", "2026-09-30",
                                                                                  [{"id": ES, "nome": nome}]))
        um = next(c for c in d["itens"] if c["id"] == 3)
        self.assertEqual((um["nome"], um["ultimo_pedido"], um["area"]), ("ACOUGUE SAO JOSE", "2026-09-15", "ROTA 1"))

    def test_atendido_sai_e_o_pedido_fora_do_dia_aparece(self):
        # quinta 3/9 da Thais (ROTA 2): o 2 com pedido no dia (atendido); o 12 sem, mas com pedido do Rubens na quinta
        # 10/9 (outra semana: não aparece). O bloqueado (13) não é esperado. O painel mostra 1 de 2.
        self.montar(hoje=D(2026, 9, 4))
        d = self.lista("atendimentos", "BA")
        self.assertEqual((d["resumo"]["esperados"], d["resumo"]["atendidos"]), (2, 1))
        self.assertEqual([(c["id"], c["fora_do_dia"]) for c in d["itens"]], [(12, [])])
        b = self.linha("atendimentos", regiao="BA")
        self.assertEqual((b["real"], b["meta"]), (1, 2))

    def test_semana_com_pedido_fora_do_dia_da_rota(self):
        # semana de 21 a 27/9: o 1 e o 3 na quarta 23/9, o 10 e o 11 na sexta 25/9; o 1 pede na terça 22/9 (fora do dia
        # da rota): continua não atendido, com a data do pedido
        self.montar(pedidos_extras=[(D(2026, 9, 22), ES, 1, "CLIENTE", "PEDIDOVENDA", 0, 1, 90.0)])
        d = self.lista("atendimentos", periodo="semana")
        self.assertEqual(d["resumo"], {"esperados": 4, "atendidos": 0, "nao_atendidos": 4, "fora_do_dia": 1})
        por_id = {c["id"]: c for c in d["itens"]}
        self.assertEqual(por_id[1]["fora_do_dia"], ["2026-09-22"])
        self.assertEqual((por_id[10]["dia"], por_id[10]["fora_do_dia"]), ("2026-09-25", []))
        self.assertEqual([c["id"] for c in d["itens"]][:2], [10, 11])  # o maior potencial primeiro (julho)
        self.assertEqual(self.linha("atendimentos", periodo="semana")["meta"], 4)


class TestPositivacao(Base):
    def test_mes_ate_o_fim_do_periodo(self):
        # setembro até 30/9: o 1 e o 3 compraram com o Rubens; o 10 e o 11 não; o 14 está inativo
        self.montar()
        d = self.lista("positivacao")
        self.assertEqual(d["resumo"], {"carteira": 4, "nao_atendidos": 2, "com_outro": 0, "atendidos": 2,
                                       "de": "2026-09-01", "ate": "2026-09-30"})
        self.assertEqual([(c["id"], c["potencial"]) for c in d["itens"]], [(10, 335.0), (11, 320.0)])  # (300+50+320)÷2
        self.assertNotIn("meses_sem", d["itens"][0])
        # a semana de 21 a 27/9 conta de 1º a 27/9 (a nota do 3 é de 15/9)
        self.assertEqual(self.lista("positivacao", periodo="semana")["resumo"]["ate"], "2026-09-27")

    def test_comprou_com_outro_vendedor(self):
        self.montar(vendas_extras=[(D(2026, 9, 8), ES, 12, "CLIENTE", 27, 90.0, 3.0)])
        d = self.lista("positivacao", "BA")
        self.assertEqual({c["id"]: c["outros"] for c in d["itens"]}, {7: [], 12: ["Rubens"]})


class TestMix(Base):
    def test_mussarela_e_outras_com_quem_comprou(self):
        # quarta 2/9: o 1 compra (mussarela 32 e manteiga 27) e é esperado; o 3 é esperado e não compra nada
        self.montar(hoje=D(2026, 9, 3))
        d = self.lista("mussarela")
        r = d["resumo"]
        # o 1 levou mussarela; o açougue não tem mussarela no mix
        self.assertEqual((r["base"], r["atendidos"], r["esperados_sem_compra"], r["completos"], r["sem_parte"], d["itens"]),
                         (2, 1, 1, 1, 1, []))
        d = self.lista("outras")
        por_id = {c["id"]: c for c in d["itens"]}
        self.assertEqual((por_id[1]["faltou"], por_id[1]["levados"], por_id[1]["itens"], por_id[1]["comprou"]),
                         (["BEBIDA LACTEA 500G"], 1, 2, True))  # sem o item da mussarela no mix
        self.assertEqual((por_id[3]["faltou"], por_id[3]["comprou"], por_id[3]["outros"]),
                         (["BEBIDA LACTEA 500G", "MANTEIGA 200G"], False, []))

    def test_esperado_sem_compra_entra_na_mussarela(self):
        # quarta 30/9: ninguém compra; o mercado (1) tem mussarela no mix e entra; o açougue (3) fica fora
        self.montar()
        d = self.lista("mussarela")
        self.assertEqual([(c["id"], c["comprou"], c["comprado"]) for c in d["itens"]], [(1, False, 0.0)])
        self.assertEqual((d["resumo"]["sem_parte"], d["resumo"]["segmentos_sem_parte"]), (1, ["AÇOUGUE"]))
        self.assertNotIn("faltou", d["itens"][0])

    def test_pedido_sem_nota_fica_marcado(self):
        # quarta 30/9: o 1 faz pedido no dia da rota (atendido), mas a nota ainda não entrou: segue na lista, marcado
        self.montar(pedidos_extras=[(D(2026, 9, 30), ES, 1, "CLIENTE", "PEDIDOVENDA", 0, 1, 90.0)])
        self.assertEqual(self.lista("atendimentos")["resumo"]["atendidos"], 1)
        d = self.lista("mussarela")
        self.assertEqual([(c["id"], c["comprou"], c["pedido_sem_nota"]) for c in d["itens"]], [(1, False, True)])
        self.assertEqual(d["resumo"]["pedido_sem_nota"], 1)
        self.assertFalse(any(c["pedido_sem_nota"] for c in self.lista("outras")["itens"] if c["id"] == 3))

    def test_grupo_mussarela_da_pagina_metas(self):
        # um produto da linha mussarela no ERP que a página Metas não põe no grupo mussarela (ele cai em outras linhas)
        # não conta como mussarela: a lista segue a linha Mussarela do painel
        self.montar(hoje=D(2026, 9, 3), vendas_extras=[(D(2026, 9, 2), ES, 3, "CLIENTE", 32, 10.0, 1.0)],
                    mix={**MIX, "ACOUGUE": [{"mussarela": True}]})
        self.assertEqual(self.lista("mussarela")["itens"], [])  # o 32 é do grupo mussarela: o 3 levou
        self.calc.configuracao._cfg["produtos"]["32"] = {"grupo": "outras", "categoria": None}
        self.assertEqual({c["id"] for c in self.lista("mussarela")["itens"]}, {1, 3})


class TestAcesso(Base):
    def test_vendedor_regiao_e_lista(self):
        self.montar()
        d = self.lista("positivacao", "BA", vendedor=BA)
        self.assertEqual((d["vendedor"], [v["id"] for v in d["vendedores"]], [v["id"] for v in d["equipe"]]),
                         (BA, [BA], [BA]))
        with self.assertRaises(PermissionError):
            self.lista("positivacao", "ES", vendedor=BA)  # a Thais não está na equipe do ES
        with self.assertRaises(PermissionError):
            self.lista("positivacao", "ES", escopo=(None, {"BA"}))  # região fora do acesso
        with self.assertRaises(ValueError):
            self.lista("nada")
        with self.assertRaises(ValueError):
            self.lista("positivacao", vendedor="abc")


class TestRota(Base):
    def test_rota(self):
        self.montar()
        nulo = logging.NullHandler()
        logging.getLogger("bi").addHandler(nulo)
        self.addCleanup(logging.getLogger("bi").removeHandler, nulo)
        pessoa = lambda id_, paginas, escopo: {"id": id_, "login": f"p{id_}", "nome": f"P{id_}",  # noqa: E731
                                              "papel": "visualizador", "paginas": paginas, "visoes": [],
                                              "escopo": escopo}
        pessoas = {"chefe": self.chefe, "ba": pessoa(2, ["gestao"], {"modo": "equipes", "equipes": ["BA"]}),
                   "metas": pessoa(3, ["metas"], {"modo": "todos"})}
        self.app = SimpleNamespace(usuarios=UsuariosFalsos(pessoas), gestao=self.gestao, vps=False)
        manipulador = type("ManipuladorDoTeste", (app.Manipulador,), {"app": self.app})
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)

        def pedir(caminho, quem):
            con = http.client.HTTPConnection("127.0.0.1", servidor.server_address[1], timeout=60)
            try:
                con.request("GET", caminho, headers={"Cookie": f"{app.COOKIE}={quem}"})
                r = con.getresponse()
                return r.status, json.loads(r.read() or b"null")
            finally:
                con.close()

        rota = "/api/gestao/desempenho/clientes"
        status, d = pedir(f"{rota}?lista=atendimentos&regiao=ES&periodo=ultimo_dia", "chefe")
        self.assertEqual((status, d["resumo"]["esperados"]), (200, 2))
        status, d = pedir(f"{rota}?lista=positivacao&regiao=BA&periodo=ultimo_dia&vendedor={BA}", "ba")
        self.assertEqual((status, d["vendedor"]), (200, BA))
        self.assertEqual(pedir(f"{rota}?lista=positivacao&regiao=ES", "ba")[0], 403)    # região fora do acesso
        self.assertEqual(pedir(f"{rota}?lista=positivacao&regiao=BA", "metas")[0], 403)  # sem a página Gestão
        self.assertEqual(pedir(f"{rota}?lista=nada&regiao=BA", "ba")[0], 400)
        self.assertEqual(pedir(f"{rota}?lista=positivacao&regiao=BA", "ninguem")[0], 401)


if __name__ == "__main__":
    import unittest
    unittest.main()

"""As listas de clientes dos cards da página Metas (bi/metas_clientes.py): os não atendidos da carteira e os que não
levaram o mix ideal do segmento (CRM › Configurar), com o cache sintético de tests/apoio.py (setembro de 2026; cópia do
banco em 01/10/2026) e a rota /api/metas/clientes."""
from __future__ import annotations

import copy
import http.client
import json
import logging
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import app
from bi.crm import PADRAO, _valida
from bi.metas_clientes import ClientesDaMeta, nome_item
from tests.apoio import BA, D, EDIR, ES, criar_calc

SET = [(2026, 9)]
# Mix ideal de teste: o mercado (cliente 1) leva manteiga e mussarela e não leva a bebida láctea; o açougue (3) leva a
# bebida láctea pelo código antigo (3643 conta como 11469) e não leva a manteiga. A padaria fica sem mix.
MIX = {
    "MERCADO": [{"produtos": [27, 26]}, {"produtos": [11469]}, {"mussarela": True}],  # 26: fora do cache
    "ACOUGUE": [{"produtos": [11469]}, {"produtos": [27]}],
}


class ConfigCrmFixa:
    def __init__(self, segmentos):
        cfg = copy.deepcopy(PADRAO)
        cfg["mix"]["segmentos"] = segmentos
        self._cfg = _valida(cfg)

    def atual(self):
        return copy.deepcopy(self._cfg)


class Base(unittest.TestCase):
    mix = MIX

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def listas(self, **kw) -> ClientesDaMeta:
        pasta = Path(tempfile.mkdtemp(dir=self._tmp.name))  # um cache por chamada
        self.calc = criar_calc(pasta, fora=(999,), extras=True, **kw)
        return ClientesDaMeta(self.calc, ConfigCrmFixa(self.mix), lambda: {ES: "Rubens", BA: "Thais", EDIR: "Edir"})


class TestNaoAtendidos(Base):
    def test_carteira_de_hoje_sem_inativo_nem_bloqueado(self):
        # ES: 1 e 3 compraram em setembro; 10 e 11 só em julho; o 14 está inativo no ERP
        d = self.listas().nao_atendidos("es", SET)
        self.assertEqual(d["resumo"], {"carteira": 4, "nao_atendidos": 2, "com_outro": 0, "atendidos": 2})
        self.assertEqual([c["nome"] for c in d["itens"]], ["POUSADA DO SOL", "HOTEL MAR"])  # maior compra média antes
        # BA: o "PEDIDO BLOQUEADO - BAR DO ZE" fica fora; o 7 só tem venda de outro cadastro (FUNCIONARIO)
        d = self.listas().nao_atendidos("ba", SET)
        self.assertEqual(d["resumo"]["carteira"], 3)
        self.assertEqual({c["id"] for c in d["itens"]}, {7, 12})

    def test_quem_comprou_com_outro_vendedor_aparece_marcado(self):
        d = self.listas(vendas_extras=[(D(2026, 9, 8), ES, 12, "CLIENTE", 27, 90.0, 3.0)]).nao_atendidos("ba", SET)
        por_id = {c["id"]: c for c in d["itens"]}
        self.assertEqual(por_id[12]["outros"], ["Rubens"])
        self.assertEqual(por_id[12]["vendedor"], {"id": BA, "nome": "Thais"})
        self.assertEqual(por_id[7]["outros"], [])
        self.assertEqual(d["resumo"]["com_outro"], 1)

    def test_ultima_compra_e_media_dos_seis_meses(self):
        # julho: o 10 comprou 300 + 50 + 320 (o produto 999 está "fora" e não conta); a média vai de mar a ago (÷ 6)
        d = self.listas(vendas_extras=[(D(2026, 7, 9), ES, 10, "CLIENTE", 999, 5000.0, 1.0)]).nao_atendidos("es", SET)
        c = next(c for c in d["itens"] if c["id"] == 10)
        self.assertAlmostEqual(c["media"], 670.0 / 6, places=2)
        self.assertEqual((c["ultima"], c["dias"]), ("2026-07-09", 84))  # até a cópia do banco, 01/10
        self.assertEqual(d["media"], {"de": "mar/26", "ate": "ago/26", "meses": 6})
        self.assertEqual(c["meses_sem"], ["set/26"])

    def test_varios_meses_entra_quem_ficou_um_mes_sem_comprar(self):
        # a Thais tem meta só em setembro; agosto também entra no período. O 2 comprou nos dois meses.
        m = self.listas(vendas_extras=[(D(2026, 8, 20), BA, 12, "CLIENTE", 32, 100.0, 5.0)])
        d = m.nao_atendidos("ba", [(2026, 8), (2026, 9)])
        por_id = {c["id"]: c for c in d["itens"]}
        self.assertNotIn(2, por_id)
        self.assertEqual(por_id[12]["meses_sem"], ["set/26"])
        self.assertEqual(por_id[7]["meses_sem"], ["ago/26", "set/26"])

    def test_edir_e_o_vendedor_sem_meta(self):
        d = self.listas(metas_cli={(D(2026, 9, 1), EDIR): 1.0}).nao_atendidos("edir", SET)
        self.assertEqual((d["resumo"]["carteira"], d["resumo"]["atendidos"], d["itens"]), (1, 1, []))
        d = self.listas().nao_atendidos("edir", SET)  # sem meta em setembro: a aba não tem vendedor
        self.assertEqual((d["vendedores"], d["resumo"]["carteira"]), ([], 0))


class TestForaDoMix(Base):
    def test_o_que_faltou_de_cada_cliente(self):
        d = self.listas().fora_do_mix("es", SET)
        self.assertEqual([(c["nome"], c["faltou"], c["levados"], c["itens"]) for c in d["itens"]], [
            ("MERCADO DO JOAO", ["BEBIDA LACTEA 500G"], 2, 3),     # comprou mais: vem antes no empate
            ("ACOUGUE SAO JOSE", ["MANTEIGA 200G"], 1, 2),        # 3643 conta como 11469
        ])
        self.assertEqual(d["itens"][0]["comprado"], 1300.0)
        self.assertEqual(d["resumo"]["atendidos"], 2)
        self.assertEqual(d["resumo"]["nao_atendidos"], 2)

    def test_quem_levou_tudo_e_quem_fica_fora(self):
        self.mix = {**MIX, "MERCADO": [{"mussarela": True}]}
        # BA: a padaria (2) não tem mix; o 7 não tem segmento no cadastro
        d = self.listas(vendas_extras=[(D(2026, 9, 9), BA, 7, "CLIENTE", 32, 50.0, 2.0)]).fora_do_mix("ba", SET)
        r = d["resumo"]
        self.assertEqual((r["atendidos"], r["sem_mix"], r["sem_segmento"], r["segmentos_sem_mix"], d["itens"]),
                         (2, 1, 1, ["PADARIA"], []))
        d = self.listas().fora_do_mix("es", SET)
        self.assertEqual((d["resumo"]["completos"], [c["id"] for c in d["itens"]]), (1, [3]))

    def test_quem_nao_comprou_com_o_vendedor_fica_fora(self):
        # o 10 (carteira do ES) comprou com a Thais em setembro: não foi atendido pelo vendedor da carteira
        d = self.listas(vendas_extras=[(D(2026, 9, 9), BA, 10, "CLIENTE", 32, 50.0, 2.0)]).fora_do_mix("es", SET)
        self.assertNotIn(10, [c["id"] for c in d["itens"]])

    def test_nome_do_item(self):
        nomes = {27: "MANTEIGA 200G", 11469: "BEBIDA LACTEA 500G"}
        self.assertEqual(nome_item({"produtos": [27, 11469]}, nomes), "MANTEIGA 200G ou BEBIDA LACTEA 500G")
        self.assertEqual(nome_item({"mussarela": True}, nomes), "Qualquer mussarela")
        self.assertEqual(nome_item({"produtos": [5]}, nomes), "Produto sem cadastro")


class TestAcesso(Base):
    def test_vendedores_do_acesso_e_do_filtro(self):
        m = self.listas()
        self.assertEqual(m.nao_atendidos("es", SET, permitidos={BA})["resumo"]["carteira"], 0)
        self.assertEqual(m.nao_atendidos("es", SET, vendedores=[BA])["resumo"]["carteira"], 0)
        self.assertEqual(m.nao_atendidos("es", SET, vendedores=[ES], permitidos={ES})["resumo"]["carteira"], 4)

    def test_so_as_abas_de_vendedores(self):
        m = self.listas()
        with self.assertRaises(ValueError):
            m.nao_atendidos("produtos_ba", SET)
        with self.assertRaises(ValueError):
            m.fora_do_mix("outras_es", SET)
        with self.assertRaises(ValueError):
            m.nao_atendidos("es", [])


class UsuariosFalsos:
    def __init__(self, pessoas):
        self.pessoas = pessoas

    def da_sessao(self, valor):
        return self.pessoas.get(valor)


class TestRota(Base):
    def setUp(self):
        super().setUp()
        nulo = logging.NullHandler()
        logging.getLogger("bi").addHandler(nulo)
        self.addCleanup(logging.getLogger("bi").removeHandler, nulo)
        m = self.listas()
        calc = self.calc
        pessoa = lambda id_, papel, paginas, escopo: {"id": id_, "login": f"p{id_}", "nome": f"P{id_}",  # noqa: E731
                                                     "papel": papel, "paginas": paginas, "visoes": ["es", "ba", "edir"],
                                                     "escopo": escopo}
        pessoas = {"chefe": pessoa(1, "admin", [], None),
                   "ba": pessoa(2, "visualizador", ["metas"], {"modo": "equipes", "equipes": ["BA"]}),
                   "crm": pessoa(3, "visualizador", ["crm"], {"modo": "todos"})}
        ids = lambda vendedores, equipes: frozenset(  # noqa: E731
            v for v in (ES, BA, EDIR) if (equipes is None or calc.regras().grupo_vendedor(v) in equipes)
            and (vendedores is None or v in vendedores))
        self.app = SimpleNamespace(usuarios=UsuariosFalsos(pessoas), calc=calc, metas_clientes=m, vps=False,
                                   assistente=SimpleNamespace(ids_do_escopo=ids))
        manipulador = type("ManipuladorDoTeste", (app.Manipulador,), {"app": self.app})
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)

    def pedir(self, caminho: str, quem: str):
        con = http.client.HTTPConnection("127.0.0.1", self.servidor.server_address[1], timeout=30)
        try:
            con.request("GET", caminho, headers={"Cookie": f"{app.COOKIE}={quem}"})
            r = con.getresponse()
            return r.status, json.loads(r.read() or b"null")
        finally:
            con.close()

    def test_rota(self):
        status, d = self.pedir("/api/metas/clientes?lista=nao_atendidos&visao=ba&meses=2026-9", "ba")
        self.assertEqual((status, d["lista"], {c["id"] for c in d["itens"]}), (200, "nao_atendidos", {7, 12}))
        status, d = self.pedir("/api/metas/clientes?lista=mix&visao=es&meses=2026-9&vendedores=124", "chefe")
        self.assertEqual((status, [c["id"] for c in d["itens"]]), (200, [1, 3]))
        self.assertEqual(self.pedir("/api/metas/clientes?lista=mix&visao=es&meses=2026-9", "ba")[0], 403)  # aba
        self.assertEqual(self.pedir("/api/metas/clientes?lista=mix&visao=ba&meses=2026-9", "crm")[0], 403)  # página
        self.assertEqual(self.pedir("/api/metas/clientes?lista=nada&visao=ba&meses=2026-9", "ba")[0], 400)
        self.assertEqual(self.pedir("/api/metas/clientes?lista=mix&visao=produtos_ba&meses=2026-9", "chefe")[0], 400)
        self.assertEqual(self.pedir("/api/metas/clientes?lista=mix&visao=ba&meses=2026-9", "ninguem")[0], 401)


if __name__ == "__main__":
    unittest.main()

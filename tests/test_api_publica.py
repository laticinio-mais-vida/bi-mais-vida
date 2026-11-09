"""API pública da Gestão (app.py, rotas /api/v1; docs/api_publica.md).

- Por HTTP, os primeiros testes do painel com o servidor de verdade: numa porta livre de 127.0.0.1, com os usuários e as
  chaves no banco de teste e uma Gestão falsa que anota as chamadas.
- O contrato: as chaves que docs/api_publica.md descreve existem no que a Gestão de verdade devolve (o cache sintético
  de tests/apoio.py).

Precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import http.client
import json
import logging
import threading
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

import app
from bi.acesso import COOKIE, LimiteApi, LimiteTentativas, Usuarios, escopo_vendedores
from bi.conversas import NaoEncontrada
from bi.gestao import Gestao, SemDados
from tests.apoio import BA, EDIR, BaseBanco
from tests.test_gestao import HOJE, ComCache


class GestaoFalsa:
    """Anota as chamadas e devolve o que a página receberia (com pode_editar, que a API tira). erro: levantado na
    próxima chamada."""

    def __init__(self):
        self.chamadas = []
        self.erro = None

    def _anotar(self, *chamada):
        self.chamadas.append(chamada)
        if self.erro:
            raise self.erro

    def quadro(self, usuario, escopo, regiao):
        self._anotar("quadro", usuario["login"], escopo, regiao)
        return {"regiao": regiao or "BA", "acoes": [], "pode_editar": usuario["papel"] == "admin"}

    def historico(self, usuario, escopo, vid):
        self._anotar("historico", usuario["login"], escopo, vid)
        return {"vendedor": {"id": vid}, "pode_editar": False}

    def detalhe(self, usuario, escopo, id_, abrir, tipo):
        self._anotar("detalhe", usuario["login"], escopo, id_, abrir, tipo)
        return {"item": {"id": id_, "tipo": tipo}, "pode_editar": False}


class TestApiPorHttp(BaseBanco):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch("bi.acesso.ITERACOES", 1000))  # a conta da senha de verdade é lenta de propósito
        nulo = logging.NullHandler()  # os avisos esperados (senha errada, chave recusada) não sujam a saída dos testes
        logging.getLogger("bi").addHandler(nulo)
        self.addCleanup(logging.getLogger("bi").removeHandler, nulo)
        self.usuarios = Usuarios(self.banco)
        for login, papel, paginas in (("chefe", "admin", None), ("bia", "visualizador", ["gestao"]),
                                      ("ana", "visualizador", ["metas"])):
            self.usuarios.salvar({"login": login, "nome": login.title(), "papel": papel, "senha": "segredo1",
                                  "paginas": paginas})
        self.usuarios.salvar({"login": "bia", "nome": "Bia", "papel": "visualizador", "paginas": ["gestao"],
                              "escopo": {"modo": "equipes", "equipes": ["BA"]}}, "bia")
        self.gestao = GestaoFalsa()
        # O que o Manipulador usa da Aplicacao nas rotas /api/v1 (e nas do site que os testes chamam).
        self.app = SimpleNamespace(usuarios=self.usuarios, gestao=self.gestao, tentativas=LimiteTentativas(),
                                   limite_api=LimiteApi(), api_ativa=True, validade_chave=90, vps=False)
        manipulador = type("ManipuladorDoTeste", (app.Manipulador,), {"app": self.app})  # sem mexer no global
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        super().tearDown()

    def pedir(self, metodo: str, caminho: str, corpo=None, chave: str | None = None, cabecalhos: dict | None = None,
              bruto: bytes | None = None):
        """(status, JSON da resposta, a resposta) de um pedido ao servidor do teste."""
        con = http.client.HTTPConnection("127.0.0.1", self.servidor.server_address[1], timeout=10)
        h = dict(cabecalhos or {})
        if chave:
            h["Authorization"] = f"Bearer {chave}"
        if corpo is not None:
            bruto = json.dumps(corpo).encode()
            h.setdefault("Content-Type", "application/json")
        try:
            con.request(metodo, caminho, body=bruto, headers=h)
            r = con.getresponse()
            texto = r.read()
        finally:
            con.close()
        return r.status, json.loads(texto) if texto else None, r

    def so_cabecalhos(self, caminho: str, cabecalhos: dict):
        """Um POST só com os cabeçalhos: o servidor recusa sem ler o corpo, e não fica nada por ler na conexão."""
        con = http.client.HTTPConnection("127.0.0.1", self.servidor.server_address[1], timeout=10)
        try:
            con.putrequest("POST", caminho)
            for nome, valor in cabecalhos.items():
                con.putheader(nome, valor)
            con.endheaders()
            r = con.getresponse()
            return r.status, json.loads(r.read())
        finally:
            con.close()

    def entrar(self, login="bia", senha="segredo1", aplicativo="App de Testes", **extra):
        return self.pedir("POST", "/api/v1/entrar", {"login": login, "senha": senha, "aplicativo": aplicativo}, **extra)

    def chave(self, login="bia") -> str:
        status, r, _ = self.entrar(login)
        self.assertEqual(status, 200, r)
        return r["chave"]

    def test_entrar_usar_e_sair(self):
        status, r, _ = self.entrar()
        self.assertEqual((status, r["usuario"]["login"], sorted(r)), (200, "bia", ["chave", "expira_em", "usuario"]))
        chave = r["chave"]
        status, eu, _ = self.pedir("GET", "/api/v1/eu", chave=chave)
        self.assertEqual((status, eu["usuario"]["nome"], eu["gestao"], eu["chave"]["aplicativo"]),
                         (200, "Bia", True, "App de Testes"))
        status, q, _ = self.pedir("GET", "/api/v1/gestao/quadro?regiao=BA", chave=chave)
        self.assertEqual((status, q), (200, {"regiao": "BA", "acoes": []}))  # sem pode_editar
        escopo = escopo_vendedores(self.usuarios.obter("bia"))  # o acesso da tela Usuários, como na página
        self.assertEqual(escopo, (None, {"BA"}))
        self.assertEqual(self.gestao.chamadas, [("quadro", "bia", escopo, "BA")])
        status, r, _ = self.pedir("POST", "/api/v1/sair", chave=chave)
        self.assertEqual((status, r), (200, {"ok": True}))
        status, _, resposta = self.pedir("GET", "/api/v1/eu", chave=chave)
        self.assertEqual((status, resposta.getheader("WWW-Authenticate")), (401, 'Bearer realm="bi", error="invalid_token"'))

    def test_campanha_objetivo_e_vendedor(self):
        chave = self.chave("chefe")
        status, d, _ = self.pedir("GET", "/api/v1/gestao/campanha?id=12", chave=chave)
        self.assertEqual((status, d), (200, {"item": {"id": "12", "tipo": "acao"}}))
        self.pedir("GET", "/api/v1/gestao/campanha?id=12&abrir=", chave=chave)  # vazio: sem abertura
        self.pedir("GET", "/api/v1/gestao/objetivo?id=7&abrir=area", chave=chave)
        self.pedir("GET", "/api/v1/gestao/vendedor?id=98", chave=chave)
        self.assertEqual(self.gestao.chamadas, [("detalhe", "chefe", (None, None), "12", "padrao", "acao"),
                                                ("detalhe", "chefe", (None, None), "12", "", "acao"),
                                                ("detalhe", "chefe", (None, None), "7", "area", "objetivo"),
                                                ("historico", "chefe", (None, None), "98")])

    def test_rota_e_metodo(self):
        self.assertEqual(self.pedir("GET", "/api/v1/nada")[:2], (404, {"erro": "rota desconhecida"}))
        status, _, r = self.pedir("POST", "/api/v1/gestao/quadro", chave=self.chave())
        self.assertEqual((status, r.getheader("Allow")), (405, "GET"))
        status, _, r = self.pedir("GET", "/api/v1/entrar")
        self.assertEqual((status, r.getheader("Allow")), (405, "POST"))

    def test_sem_chave_ou_chave_errada(self):
        chave = self.chave()
        for cabecalhos in ({}, {"Authorization": "Bearer"}, {"Authorization": f"Basic {chave}"},
                           {"Authorization": "Bearer bimv_" + "a" * 43}, {"Authorization": f"Bearer {chave}x"}):
            status, r, resposta = self.pedir("GET", "/api/v1/gestao/quadro", cabecalhos=cabecalhos)
            self.assertEqual(status, 401, cabecalhos)
            self.assertTrue(resposta.getheader("WWW-Authenticate").startswith('Bearer realm="bi"'))
        self.assertEqual(self.pedir("GET", f"/api/v1/eu?chave={chave}")[0], 401)  # nunca no endereço
        self.assertEqual(self.gestao.chamadas, [])

    def test_cookie_nao_vale_na_api_e_chave_nao_vale_no_site(self):
        cookie, _ = self.usuarios.criar_sessao(self.usuarios.obter("bia")["id"])
        self.assertEqual(self.pedir("GET", "/api/v1/eu", cabecalhos={"Cookie": f"{COOKIE}={cookie}"})[0], 401)
        self.assertEqual(self.pedir("GET", "/api/gestao?regiao=BA", chave=self.chave())[0], 401)  # o site: só cookie

    def test_navegador_recusado(self):
        chave = self.chave()
        origem = {"Origin": "https://outro.site"}
        self.assertEqual(self.pedir("GET", "/api/v1/eu", chave=chave, cabecalhos=origem)[0], 403)
        status, _, _ = self.entrar("chefe", cabecalhos=origem)
        self.assertEqual(status, 403)
        self.assertEqual(self.contar("chaves_api"), 1)  # só a da Bia

    def test_login_errado_conta_tentativa_e_mal_formado_nao(self):
        for corpo, cabecalhos in (({"login": "bia", "senha": "segredo1"}, None),  # sem aplicativo
                                  ([1, 2], None),
                                  ({"login": "bia", "senha": 1, "aplicativo": "App"}, None),
                                  ({"login": "bia", "senha": "segredo1", "aplicativo": "App"},
                                   {"Content-Type": "text/plain"}),
                                  ({"login": "bia", "senha": "segredo1", "aplicativo": "App\x07"}, None)):
            for _ in range(3):
                status, r, _ = self.pedir("POST", "/api/v1/entrar", corpo, cabecalhos=cabecalhos)
                self.assertEqual(status, 400, (corpo, r))
        json_ = {"Content-Type": "application/json"}
        status, r, _ = self.pedir("POST", "/api/v1/entrar", bruto=b"{quebrado", cabecalhos=json_)
        self.assertEqual((status, r["erro"]), (400, "o corpo não é um JSON válido"))
        self.assertEqual(self.pedir("POST", "/api/v1/entrar", cabecalhos=json_)[0], 400)  # sem corpo
        self.assertEqual(self.so_cabecalhos("/api/v1/entrar", {**json_, "Content-Length": str(16 * 1024 + 1)}),
                         (400, {"erro": "o corpo do pedido passa de 16384 bytes"}))
        self.assertEqual(self.so_cabecalhos("/api/v1/entrar", {**json_, "Transfer-Encoding": "chunked"})[0], 400)
        self.assertEqual(self.entrar()[0], 200)  # nada disso contou como senha errada
        for _ in range(5):
            self.assertEqual(self.entrar(senha="errada")[:2], (401, {"erro": "usuário ou senha incorretos"}))
        status, _, r = self.entrar()  # agora nem a senha certa: espera
        self.assertEqual(status, 429)
        self.assertGreater(int(r.getheader("Retry-After")), 0)

    def test_sem_a_gestao(self):
        status, r, _ = self.entrar("ana")
        self.assertEqual((status, r["erro"]), (403, "seu acesso não inclui a página Gestão"))
        self.assertEqual(self.contar("chaves_api"), 0)
        chave = self.chave()
        self.usuarios.salvar({"login": "bia", "nome": "Bia", "papel": "visualizador", "paginas": ["metas"]}, "bia")
        status, eu, _ = self.pedir("GET", "/api/v1/eu", chave=chave)
        self.assertEqual((status, eu["gestao"]), (200, False))
        self.assertEqual(self.pedir("GET", "/api/v1/gestao/quadro", chave=chave)[0], 403)
        self.assertEqual(self.gestao.chamadas, [])

    def test_limite_por_chave(self):
        self.app.limite_api = LimiteApi(por_minuto=2)
        chave = self.chave()
        self.assertEqual([self.pedir("GET", "/api/v1/eu", chave=chave)[0] for _ in range(2)], [200, 200])
        status, _, r = self.pedir("GET", "/api/v1/gestao/quadro", chave=chave)
        self.assertEqual(status, 429)
        self.assertGreater(int(r.getheader("Retry-After")), 0)
        self.assertEqual(self.pedir("POST", "/api/v1/sair", chave=chave)[0], 200)  # sair sempre funciona

    def test_todas_as_vagas_ocupadas(self):
        self.app.limite_api = LimiteApi(simultaneos=1, espera_vaga=0.05)
        chave = self.chave()
        with self.app.limite_api.vaga():  # outro pedido da API correndo
            status, r, resposta = self.pedir("GET", "/api/v1/eu", chave=chave)
        self.assertEqual((status, resposta.getheader("Retry-After")), (503, "5"))
        self.assertEqual(self.pedir("GET", "/api/v1/eu", chave=chave)[0], 200)

    def test_api_desligada(self):
        chave = self.chave()
        self.app.api_ativa = False
        self.assertEqual(self.pedir("GET", "/api/v1/eu", chave=chave)[0], 503)
        self.assertEqual(self.entrar()[0], 503)

    def test_erros_da_gestao(self):
        chave = self.chave()
        for erro, status in ((SemDados("os dados de vendas ainda estão sendo preparados"), 503),
                             (NaoEncontrada("campanha não encontrada"), 404),
                             (PermissionError("seu acesso na Gestão não inclui vendedores da região ES"), 403),
                             (ValueError("região desconhecida: 'XX' (use ES ou BA)"), 400)):
            self.gestao.erro = erro
            self.assertEqual(self.pedir("GET", "/api/v1/gestao/quadro", chave=chave)[:2], (status, {"erro": str(erro)}))
        self.gestao.erro = RuntimeError("os dados de vendas ainda estão sendo preparados")
        self.assertEqual(self.pedir("GET", "/api/v1/gestao/quadro", chave=chave)[2].getheader("Retry-After"), "60")
        self.gestao.erro = Exception("detalhe interno: senha do banco xyz")
        with self.assertLogs("bi", "ERROR"):
            status, r, _ = self.pedir("GET", "/api/v1/gestao/quadro", chave=chave)
        self.assertEqual((status, r), (500, {"erro": "erro interno; tente de novo mais tarde"}))  # o detalhe só no log

    def test_chave_e_senha_nunca_no_log(self):
        with self.assertLogs("bi", "DEBUG") as logs:
            chave = self.chave()
            self.entrar(senha="errada-123")
            self.pedir("GET", "/api/v1/gestao/quadro?regiao=BA", chave=chave)
            self.pedir("GET", "/api/v1/eu", chave=chave + "x")
            self.pedir("POST", "/api/v1/sair", chave=chave)
        texto = "\n".join(logs.output)
        self.assertIn("bia entrou pela API pelo aplicativo 'App de Testes'", texto)
        for segredo in (chave, chave[5:], "segredo1", "errada-123"):
            self.assertNotIn(segredo, texto)

    def test_aplicativos_conectados_no_site(self):
        chave = self.chave()
        self.chave("chefe")
        bia = self.usuarios.obter("bia")
        cookie = {"Cookie": f"{COOKIE}={self.usuarios.criar_sessao(bia['id'])[0]}"}
        status, r, _ = self.pedir("GET", "/api/aplicativos", cabecalhos=cookie)
        self.assertEqual((status, [a["aplicativo"] for a in r["aplicativos"]]), (200, ["App de Testes"]))  # só os dela
        id_ = r["aplicativos"][0]["id"]
        do_chefe = self.usuarios.chaves(self.usuarios.obter("chefe")["id"])[0]["id"]
        self.assertEqual(self.pedir("POST", "/api/aplicativos/desconectar", {"id": do_chefe}, cabecalhos=cookie)[0], 404)
        status, r, _ = self.pedir("POST", "/api/aplicativos/desconectar", {"id": id_}, cabecalhos=cookie)
        self.assertEqual((status, r["aplicativos"]), (200, []))
        self.assertEqual(self.pedir("GET", "/api/v1/eu", chave=chave)[0], 401)

    def test_catalogo_so_do_administrador(self):
        bia = self.usuarios.obter("bia")
        cookie = {"Cookie": f"{COOKIE}={self.usuarios.criar_sessao(bia['id'])[0]}"}
        status, r, _ = self.pedir("GET", "/api/gestao/catalogo", cabecalhos=cookie)
        self.assertEqual((status, r["erro"]), (403, "só administradores podem fazer isso"))


class TestContratoGestao(ComCache, BaseBanco):
    """As chaves que docs/api_publica.md descreve, no que a Gestão de verdade devolve: se uma sumir ou mudar de nome,
    o outro aplicativo quebra, e o documento precisa avisar antes. O cache vai até 30/09/2026; hoje é 01/10/2026."""

    QUADRO = {"regiao", "regioes", "hoje", "data_ref", "aviso", "objetivos", "acoes", "vendedores"}
    OBJETIVO_NO_QUADRO = {"id", "nome", "inicio", "fim", "situacao", "prazo", "indicador", "meta_padrao", "andamento",
                          "aviso"}
    CAMPANHA_NO_QUADRO = {"id", "nome", "rotulo", "inicio", "fim", "situacao", "prazo", "vendedores", "total_vendedores",
                          "meta_pct", "com_meta", "indicador", "alvo_tipo", "meta_padrao", "premiacoes", "aviso"}
    CARD = {"id", "nome", "equipe", "inativo", "em_vigor", "acoes"}
    ETIQUETA = {"id", "rotulo", "situacao", "fim", "resultado", "alvo", "pct"}
    PRAZO = {"dias", "faltam", "comeca_em", "decorrido"}
    INDICADOR = {"tipo", "nome", "formato", "casas", "unidade", "sufixo", "descricao"}
    CAMPANHA = {"item", "indicador", "linhas", "total", "aviso", "ocultos", "data_ref"}
    ITEM = {"id", "tipo", "nome", "regiao", "inicio", "fim", "situacao", "congelado", "provisorio", "encerrada",
            "alvo_tipo", "meta_padrao", "base_inicio", "base_fim"}
    LINHA = {"id", "nome", "equipe", "base", "alvo", "resultado", "pct", "status", "projecao", "classe", "delta",
             "delta_pct", "caminho"}
    TOTAL = {"vendedores", "no_alvo", "acima_da_base"}
    OBJETIVO = {"item", "andamento", "aviso", "data_ref"}
    HISTORICO = {"vendedor", "eventos", "acoes", "em_vigor", "data_ref", "hoje"}
    VENDEDOR = {"id", "nome", "equipe", "regiao", "inativo"}
    EVENTO = {"id", "tipo", "acao", "data", "texto", "autor", "criada_em", "dados"}
    CAMPANHA_NO_HISTORICO = {"id", "nome", "situacao", "participa"}

    def setUp(self):
        super().setUp()
        self.montar_cache()
        self.gestao = Gestao(self.banco, self.calc, self.assistente, hoje=lambda: HOJE)
        with self.banco.conexao() as con:
            id_ = con.execute("INSERT INTO usuarios (login, nome, papel, senha) VALUES ('chefe', 'Chefe', 'admin', 'x') "
                              "RETURNING id").fetchone()[0]
        self.chefe = {"id": id_, "login": "chefe", "nome": "Chefe", "papel": "admin"}

    def tearDown(self):
        self.desmontar_cache()
        super().tearDown()

    def faltam(self, esperadas: set, d: dict, onde: str):
        self.assertEqual(esperadas - set(d), set(), onde)

    def test_chaves_documentadas(self):
        dados = {"regiao": "BA", "inicio": "2026-09-01", "metrica": "faturamento", "base_periodo": "mes",
                 "alvo_tipo": "pct", "meta_padrao": 25}
        encerrada = self.gestao.criar(self.chefe, {**dados, "nome": "Mussarela BA", "fim": "2026-09-28",
                                                   "vendedores": [BA, EDIR]})["id"]
        self.gestao.criar(self.chefe, {**dados, "nome": "Longa", "fim": "2026-10-31", "vendedores": [BA]})  # em vigor
        objetivo = self.gestao.criar(self.chefe, {"nome": "Equipe BA", "regiao": "BA", "inicio": "2026-09-01",
                                                  "fim": "2026-09-30", "metrica": "faturamento", "meta_padrao": 6000},
                                     "objetivo")["id"]
        self.gestao.anotar(self.chefe, BA, "Visitar a rede X")
        tudo = (None, None)

        q = self.gestao.quadro(self.chefe, tudo, "BA")
        self.faltam(self.QUADRO, q, "quadro")
        self.faltam(self.OBJETIVO_NO_QUADRO, q["objetivos"][0], "objetivo no quadro")
        for c in q["acoes"]:
            self.faltam(self.CAMPANHA_NO_QUADRO, c, "campanha no quadro")
            self.faltam(self.PRAZO, c["prazo"], "prazo")
            self.faltam(self.INDICADOR, c["indicador"], "indicador")
        card = next(v for v in q["vendedores"] if v["id"] == BA)
        self.faltam(self.CARD, card, "card do vendedor")
        self.faltam(self.ETIQUETA, card["acoes"][0], "campanha em vigor no card")

        d = self.gestao.detalhe(self.chefe, tudo, encerrada, tipo="acao")
        self.faltam(self.CAMPANHA, d, "campanha")
        self.faltam(self.ITEM, d["item"], "item da campanha")
        self.faltam(self.LINHA, d["linhas"][0], "linha da campanha")
        self.faltam(self.TOTAL, d["total"], "total da campanha")
        o = self.gestao.detalhe(self.chefe, tudo, objetivo, tipo="objetivo")
        self.faltam(self.OBJETIVO, o, "objetivo")
        self.assertIn("parcial", o["item"])

        h = self.gestao.historico(self.chefe, tudo, BA)
        self.faltam(self.HISTORICO, h, "histórico")
        self.faltam(self.VENDEDOR, h["vendedor"], "vendedor do histórico")
        self.assertLessEqual({"lancada", "nota", "parcial", "resultado"}, {e["tipo"] for e in h["eventos"]})
        for e in h["eventos"]:
            self.faltam(self.EVENTO, e, f"evento {e['tipo']}")
        self.faltam(self.CAMPANHA_NO_HISTORICO, h["acoes"][str(encerrada)], "campanha no histórico")


if __name__ == "__main__":
    unittest.main()

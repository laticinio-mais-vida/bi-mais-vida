"""Usuários no PostgreSQL (bi/acesso.py): cadastro, sessões, as chaves da API pública, os vendedores do acesso (um só
para todas as páginas, na tela Usuários) e as abas de Metas. Precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem
ele, são pulados (menos os limites da API e as contas do escopo, que não usam o banco)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import unittest
from unittest import mock

from bi.acesso import ApiOcupada, LimiteApi, Usuarios, escopo_vendedores, premiacoes_permitidas
from bi.banco import Banco
from tests.apoio import BaseBanco


class Base(BaseBanco):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch("bi.acesso.ITERACOES", 1000))  # a conta da senha de verdade é lenta de propósito
        self.u = Usuarios(self.banco)
        self.u.salvar({"login": "chefe", "nome": "Chefe", "papel": "admin", "senha": "segredo1"})
        self.u.salvar({"login": "ana", "nome": "Ana", "papel": "visualizador", "senha": "segredo1",
                       "paginas": ["metas", "assistente"]})

    def ana(self):
        return self.u.obter("ana")


class TestEscopoDaPessoa(unittest.TestCase):
    """escopo_vendedores: o acesso da tela Usuários na dupla (vendedores, equipes) que as contas de todas as páginas
    recebem. Sem banco."""

    def test_cada_modo(self):
        vis = lambda e: {"papel": "visualizador", "escopo": e}  # noqa: E731
        self.assertEqual(escopo_vendedores(vis({"modo": "todos"})), (None, None))
        self.assertEqual(escopo_vendedores(vis({"modo": "equipes", "equipes": ["BA", "EDIR"]})), (None, {"BA", "EDIR"}))
        self.assertEqual(escopo_vendedores(vis({"modo": "alguns", "vendedores": [124, 141]})), ({124, 141}, None))
        self.assertEqual(escopo_vendedores(vis(None)), (set(), None))  # ainda sem escolha: nenhum vendedor
        self.assertEqual(escopo_vendedores({"papel": "visualizador"}), (set(), None))
        self.assertEqual(escopo_vendedores({"papel": "admin", "escopo": {"modo": "alguns", "vendedores": [1]}}),
                         (None, None))  # o administrador vê tudo


class TestVendedoresDoAcesso(Base):
    def salvar_ana(self, escopo, **mudancas):
        return self.u.salvar({"login": "ana", "nome": "Ana", "papel": "visualizador",
                              "paginas": ["metas", "assistente"], "escopo": escopo, **mudancas}, "ana")

    def test_novo_sem_escolha_nao_ve_ninguem(self):
        self.assertIsNone(self.ana()["escopo"])
        self.assertEqual(escopo_vendedores(self.ana()), (set(), None))
        self.assertIsNone(self.u.obter("chefe")["escopo"])
        self.assertEqual(escopo_vendedores(self.u.obter("chefe")), (None, None))

    def test_grava_cada_modo(self):
        self.assertEqual(self.salvar_ana({"modo": "equipes", "equipes": ["EDIR", "BA", "BA"]})["escopo"],
                         {"modo": "equipes", "equipes": ["BA", "EDIR"]})  # sem repetir, na ordem das equipes
        self.assertEqual(escopo_vendedores(self.ana()), (None, {"BA", "EDIR"}))
        self.salvar_ana({"modo": "alguns", "vendedores": [141, 124, "124"], "equipes": ["BA"]})
        self.assertEqual(self.ana()["escopo"], {"modo": "alguns", "vendedores": [124, 141]})
        self.assertEqual(escopo_vendedores(self.ana()), ({124, 141}, None))
        self.salvar_ana({"modo": "todos", "vendedores": [1]})
        self.assertEqual(self.ana()["escopo"], {"modo": "todos"})
        # Sem a chave "escopo" (ex.: outro caminho que salva o cadastro), os vendedores ficam como estavam.
        self.u.salvar({"login": "ana", "nome": "Ana Maria", "papel": "visualizador", "paginas": ["metas"]}, "ana")
        self.assertEqual((self.ana()["nome"], self.ana()["escopo"]), ("Ana Maria", {"modo": "todos"}))

    def test_validacao(self):
        self.salvar_ana({"modo": "equipes", "equipes": ["ES"]})
        for errado in (None, {}, {"modo": "metas"}, {"modo": "qualquer"}, {"modo": "equipes", "equipes": []},
                       {"modo": "equipes", "equipes": ["OCULTO"]}, {"modo": "equipes", "equipes": "BA"},
                       {"modo": "alguns", "vendedores": []}, {"modo": "alguns", "vendedores": ["x"]},
                       {"modo": "alguns", "vendedores": [True]}, {"modo": "alguns", "vendedores": [-3]}, "todos"):
            with self.subTest(errado=errado), self.assertRaises(ValueError):
                self.salvar_ana(errado)
        self.assertEqual(self.ana()["escopo"], {"modo": "equipes", "equipes": ["ES"]})  # nada gravou

    def test_administrador_nao_guarda_e_quem_vira_visualizador_escolhe(self):
        self.salvar_ana({"modo": "todos"})
        self.u.salvar({"login": "ana", "nome": "Ana", "papel": "admin", "escopo": {"modo": "alguns",
                                                                                    "vendedores": [1]}}, "ana")
        with self.banco.conexao() as con:
            self.assertIsNone(con.execute("SELECT escopo FROM usuarios WHERE login = 'ana'").fetchone()[0])
        self.assertIsNone(self.ana()["escopo"])
        # De volta a visualizador sem escolher: fica sem vendedores (a tela Usuários pede a escolha antes).
        self.u.salvar({"login": "ana", "nome": "Ana", "papel": "visualizador", "paginas": ["metas"]}, "ana")
        self.assertEqual(escopo_vendedores(self.ana()), (set(), None))
        with self.assertRaises(ValueError):  # a tela manda escopo None quando a pessoa ainda não escolheu
            self.salvar_ana(None)

    def test_criar_ja_com_os_vendedores(self):
        bia = self.u.salvar({"login": "bia", "nome": "Bia", "papel": "visualizador", "senha": "segredo1",
                             "paginas": ["gestao"], "escopo": {"modo": "alguns", "vendedores": [85]}})
        self.assertEqual(bia["escopo"], {"modo": "alguns", "vendedores": [85]})
        with self.assertRaises(ValueError):
            self.u.salvar({"login": "caio", "nome": "Caio", "papel": "visualizador", "senha": "segredo1",
                           "paginas": ["gestao"], "escopo": None})
        self.assertIsNone(self.u.obter("caio"))

    def test_metas_so_as_abas_e_tudo_ou_nada(self):
        self.salvar_ana({"modo": "alguns", "vendedores": [124]})
        self.u.definir_metas({"ana": {"visoes": ["es", "ba"], "vendedores": [999]}})  # vendedores: não é mais daqui
        self.assertEqual((self.ana()["visoes"], self.ana()["escopo"]),
                         (["es", "ba"], {"modo": "alguns", "vendedores": [124]}))
        with self.assertRaises(ValueError):  # o segundo está errado: o primeiro também não grava
            self.u.definir_metas({"ana": {"visoes": ["es"]}, "ninguem": {"visoes": ["es"]}})
        self.assertEqual(self.ana()["visoes"], ["es", "ba"])
        with self.assertRaises(ValueError):  # com a página, ao menos uma aba
            self.u.definir_metas({"ana": {"visoes": []}})
        self.u.definir_metas({"ana": {"ve": False, "visoes": []}})
        self.assertEqual(self.ana()["paginas"], ["assistente"])
        self.u.definir_metas({"ana": {"ve": True, "visoes": ["edir"]}})
        self.assertEqual((self.ana()["paginas"], self.ana()["visoes"]), (["metas", "assistente"], ["edir"]))


class TestPremiacoesDaPessoa(Base):
    """As abas e os quadros de supervisor das Premiações (coluna premiacoes, Premiações › Configurar › Acesso por
    usuário). Os vendedores dentro deles continuam os do escopo."""

    def test_sem_escolha_nao_ve_nenhuma_aba(self):
        self.assertIsNone(self.ana()["premiacoes"])
        self.assertEqual(premiacoes_permitidas(self.ana()), ([], []))
        self.assertEqual(premiacoes_permitidas(self.u.obter("chefe")), (None, None))  # o administrador vê tudo
        self.assertIsNone(self.u.obter("chefe")["premiacoes"])

    def test_grava_na_ordem_e_liga_a_pagina(self):
        self.u.definir_premiacoes({"ana": {"ve": True, "abas": ["comissao", "supervisores", "comissao"],
                                           "supervisores": ["valdirene", "ronaldo"]}})
        ana = self.ana()
        self.assertEqual(ana["premiacoes"], {"abas": ["supervisores", "comissao"], "supervisores": ["ronaldo", "valdirene"]})
        self.assertEqual(ana["paginas"], ["metas", "premiacoes", "assistente"])
        self.assertEqual(premiacoes_permitidas(ana), (["supervisores", "comissao"], ["ronaldo", "valdirene"]))
        # sem a aba Supervisores, a lista dos quadros fica vazia; sem "ve", a página fica como está
        self.u.definir_premiacoes({"ana": {"abas": ["vendedores"], "supervisores": ["marcos"]}})
        self.assertEqual((self.ana()["premiacoes"], self.ana()["paginas"]),
                         ({"abas": ["vendedores"], "supervisores": []}, ["metas", "premiacoes", "assistente"]))
        # desligar a página guarda o que estava marcado (vale de novo se ligar)
        self.u.definir_premiacoes({"ana": {"ve": False, "abas": [], "supervisores": []}})
        self.assertEqual((self.ana()["paginas"], self.ana()["premiacoes"]),
                         (["metas", "assistente"], {"abas": [], "supervisores": []}))
        # o cadastro em Usuários não mexe no que é da página
        self.u.salvar({"login": "ana", "nome": "Ana", "papel": "visualizador", "paginas": ["premiacoes"]}, "ana")
        self.assertEqual(self.ana()["premiacoes"], {"abas": [], "supervisores": []})

    def test_validacao_e_tudo_ou_nada(self):
        self.u.definir_premiacoes({"ana": {"ve": True, "abas": ["vendedores"]}})
        for errado in ({"abas": []}, {"abas": ["gerentes"]}, {"abas": "vendedores"},
                       {"abas": ["supervisores"], "supervisores": []}, {"abas": ["supervisores"], "supervisores": ["joao"]},
                       {"abas": ["vendedores"], "supervisores": "marcos"}):
            with self.subTest(errado=errado), self.assertRaises(ValueError):
                self.u.definir_premiacoes({"ana": errado})
        with self.assertRaises(ValueError):  # o segundo está errado: o primeiro também não grava
            self.u.definir_premiacoes({"ana": {"abas": ["comissao"]}, "ninguem": {"abas": ["comissao"]}})
        self.assertEqual(self.ana()["premiacoes"], {"abas": ["vendedores"], "supervisores": []})
        # é a única página: não dá para tirar
        self.u.salvar({"login": "ana", "nome": "Ana", "papel": "visualizador", "paginas": ["premiacoes"]}, "ana")
        with self.assertRaises(ValueError):
            self.u.definir_premiacoes({"ana": {"ve": False, "abas": []}})
        # o administrador não guarda nada (vê tudo)
        self.u.definir_premiacoes({"chefe": {"abas": ["comissao"]}})
        self.assertIsNone(self.u.obter("chefe")["premiacoes"])


class TestMigracao041(BaseBanco):
    """bi/migracoes/041_premiacoes_acesso.sql: quem já tinha a página Premiações continua vendo as três abas e os três
    supervisores (o acesso de vendedores continua limitando, como antes); os outros ficam sem nada escolhido."""

    def setUp(self):
        super().setUp()
        todas = Banco._arquivos_migracao()
        with mock.patch.object(Banco, "_arquivos_migracao", staticmethod(lambda: [a for a in todas if a.stem < "041"])):
            self.banco.migrar()

    def test_cada_caso(self):
        with self.banco.conexao() as con:
            for login, papel, paginas in (("chefe", "admin", None), ("com", "visualizador", ["metas", "premiacoes"]),
                                          ("sem", "visualizador", ["metas"]), ("antigo", "visualizador", None)):
                con.execute("INSERT INTO usuarios (login, nome, papel, senha, paginas) VALUES (%s, %s, %s, 'x', "
                            "%s::text[])", [login, login.title(), papel, paginas])
        self.assertEqual(self.banco.migrar(), ["041_premiacoes_acesso"])
        with self.banco.conexao() as con:
            acessos = dict(con.execute("SELECT login, premiacoes FROM usuarios").fetchall())
        tudo = {"abas": ["vendedores", "supervisores", "comissao"], "supervisores": ["marcos", "ronaldo", "valdirene"]}
        self.assertEqual(acessos, {"chefe": None, "com": tudo, "sem": None, "antigo": None})
        u = Usuarios(self.banco)
        self.assertEqual(premiacoes_permitidas(u.obter("com")), (tudo["abas"], tudo["supervisores"]))
        self.assertEqual(premiacoes_permitidas(u.obter("sem")), ([], []))

    def test_o_banco_recusa_acesso_mal_formado(self):
        import psycopg  # só aqui: sem o psycopg, a classe inteira é pulada
        self.banco.migrar()
        self.criar_usuario("ana")
        for errado in ('[1]', '{"abas": "vendedores", "supervisores": []}', '{"abas": []}', '"x"'):
            with self.subTest(errado=errado), self.assertRaises(psycopg.errors.CheckViolation):
                with self.banco.conexao() as con:
                    con.execute("UPDATE usuarios SET premiacoes = %s::jsonb WHERE login = 'ana'", [errado])


class TestCadastroESessao(Base):
    def cookie_de(self, corpo: dict) -> str:
        """Um cookie assinado com o segredo do painel, com o conteúdo que o teste quiser."""
        texto = base64.urlsafe_b64encode(json.dumps(corpo).encode()).rstrip(b"=").decode()
        assinatura = hmac.new(self.u._segredo(), texto.encode(), hashlib.sha256).digest()
        return f"{texto}.{base64.urlsafe_b64encode(assinatura).rstrip(b'=').decode()}"

    def test_login_e_sessao(self):
        self.assertIsNone(self.u.autenticar("ana", "errada"))
        self.assertIsNone(self.u.autenticar("ninguem", "segredo1"))
        ana = self.u.autenticar(" ANA ", "segredo1")
        self.assertEqual(ana["login"], "ana")
        self.assertIsNotNone(self.ana()["ultimo_acesso"])
        self.assertNotIn("+", self.ana()["ultimo_acesso"])  # hora local sem fuso, como a página mostra
        cookie, _ = self.u.criar_sessao(ana["id"], lembrar=True)
        sessao = self.u.da_sessao(cookie)
        self.assertEqual((sessao["login"], sessao["lembrar"]), ("ana", True))
        self.assertNotIn("senha", sessao)
        self.assertIsNone(self.u.da_sessao(cookie[:-2] + "xx"))  # assinatura errada
        self.assertIsNone(self.u.da_sessao("ç.ç"))

    def test_cookie_antigo_com_login_e_vencido(self):
        ana = self.ana()
        self.assertIsNone(self.u.da_sessao(self.cookie_de({"u": "ana", "s": 0, "e": time.time() + 99, "l": False})))
        self.assertIsNone(self.u.da_sessao(self.cookie_de({"u": ana["id"], "s": 0, "e": time.time() - 1})))
        self.assertIsNotNone(self.u.da_sessao(self.cookie_de({"u": ana["id"], "s": 0, "e": time.time() + 99})))

    def test_login_recriado_nao_herda_a_sessao(self):
        cookie, _ = self.u.criar_sessao(self.ana()["id"])
        self.u.excluir("ana")
        self.assertIsNone(self.u.da_sessao(cookie))
        self.u.salvar({"login": "ana", "nome": "Outra Ana", "papel": "visualizador", "senha": "segredo2",
                       "paginas": ["metas"]})
        self.assertIsNone(self.u.da_sessao(cookie))  # mesmo login e contador 0, mas outro id

    def test_trocar_login_mantem_e_trocar_senha_derruba(self):
        cookie, _ = self.u.criar_sessao(self.ana()["id"])
        ana = self.u.salvar({"login": "ana.paula", "nome": "Ana Paula", "papel": "visualizador",
                             "paginas": ["metas"]}, "ana")
        self.assertEqual(self.u.da_sessao(cookie)["login"], "ana.paula")
        self.assertIsNone(self.u.obter("ana"))
        self.u.trocar_senha("ana.paula", "segredo1", "nova-senha")
        self.assertIsNone(self.u.da_sessao(cookie))
        self.assertIsNotNone(self.u.autenticar("ana.paula", "nova-senha"))
        with self.assertRaises(ValueError):
            self.u.trocar_senha("ana.paula", "errada", "outra-senha")
        self.assertEqual(ana["paginas"], ["metas"])

    def test_regras_do_cadastro(self):
        with self.assertRaises(ValueError):
            self.u.salvar({"login": "ana", "nome": "Repetida", "papel": "admin", "senha": "segredo1"})
        with self.assertRaises(ValueError):
            self.u.salvar({"login": "Com Espaço", "nome": "X", "papel": "admin", "senha": "segredo1"})
        with self.assertRaises(ValueError):  # o único administrador ativo
            self.u.salvar({"login": "chefe", "nome": "Chefe", "papel": "admin", "ativo": False}, "chefe")
        with self.assertRaises(ValueError):
            self.u.excluir("chefe")
        self.u.excluir("ana")
        self.assertEqual([u["login"] for u in self.u.listar()], ["chefe"])

    def test_primeiro_acesso_so_uma_vez(self):
        self.assertFalse(self.u.vazio())
        with self.assertRaises(ValueError):
            self.u.salvar({"login": "outro", "nome": "Outro", "papel": "admin", "senha": "segredo1"}, primeiro=True)

    def test_primeiro_acesso_ao_mesmo_tempo(self):
        with self.banco.conexao() as con:
            con.execute("DELETE FROM usuarios")
        self.assertTrue(self.u.vazio())
        criados, erros = [], []

        def criar(login):
            try:
                criados.append(self.u.salvar({"login": login, "nome": login, "papel": "admin", "senha": "segredo1"},
                                             primeiro=True))
            except ValueError as e:
                erros.append(e)
        tarefas = [threading.Thread(target=criar, args=(f"admin{i}",)) for i in range(4)]
        for t in tarefas:
            t.start()
        for t in tarefas:
            t.join()
        self.assertEqual((len(criados), len(erros)), (1, 3))
        self.assertEqual(len(self.u.listar()), 1)

    def test_definir_senha_pelo_terminal(self):
        self.u.definir_senha("chefe", "nova-senha")
        self.assertIsNotNone(self.u.autenticar("chefe", "nova-senha"))
        self.u.definir_senha("socorro", "nova-senha", "Socorro")  # não existe: vira administrador
        self.assertEqual(self.u.obter("socorro")["papel"], "admin")
        with self.assertRaises(ValueError):
            self.u.definir_senha("Inválido", "nova-senha")


class TestMigracao040(BaseBanco):
    """bi/migracoes/040_acesso_vendedores.sql: os acessos de antes (Metas com abas e lista, e o modo próprio de
    Projeções, Assistente e Gestão) viram um só, o da tela Usuários."""

    def setUp(self):
        super().setUp()
        todas = Banco._arquivos_migracao()
        with mock.patch.object(Banco, "_arquivos_migracao", staticmethod(lambda: [a for a in todas if a.stem < "040"])):
            self.banco.migrar()

    def criar(self, login, papel="visualizador", paginas=("metas",), visoes=(), vendedores=None, **escopos):
        with self.banco.conexao() as con:
            con.execute("INSERT INTO usuarios (login, nome, papel, senha, paginas, visoes, vendedores, escopo_projecoes, "
                        "escopo_assistente, escopo_gestao) VALUES (%s, %s, %s, 'x', %s::text[], %s::text[], %s::int[], "
                        "%s::jsonb, %s::jsonb, %s::jsonb)",
                        [login, login.title(), papel, None if paginas is None else list(paginas),
                         None if visoes is None else list(visoes), vendedores,
                         *(None if escopos.get(p) is None else json.dumps(escopos[p])
                           for p in ("projecoes", "assistente", "gestao"))])

    def test_cada_caso(self):
        todos, so = {"modo": "todos", "vendedores": None}, lambda *v: {"modo": "alguns", "vendedores": list(v)}  # noqa: E731
        self.criar("chefe", "admin", paginas=None, visoes=None)
        self.criar("sup.es", visoes=["es", "outras_es"])  # como o supervisor.es do PC
        self.criar("sup.ba", paginas=["metas", "gestao"], visoes=["ba", "produtos_ba"], gestao=todos)  # vale Metas
        self.criar("lista", visoes=["es"], vendedores=[141, 124, 124])
        self.criar("vazia", visoes=["es"], vendedores=[])  # hoje não vê ninguém
        self.criar("gestor", paginas=["gestao", "assistente"], gestao=todos, assistente=so(85))
        self.criar("somas", paginas=["assistente", "projecoes"], assistente=so(85), projecoes=so(98, 85))
        self.criar("sem.pagina", paginas=["metas"], gestao=todos)  # o "todos" de uma página que ela não tem
        self.criar("igual.metas", paginas=["gestao"], gestao={"modo": "metas", "vendedores": None})
        self.criar("aba.velha", paginas=["projecoes"], visoes=["geral"], projecoes=todos)  # aba que não existe mais
        self.criar("antigo", paginas=None, visoes=None)  # de antes da escolha de páginas: só Metas
        self.assertEqual(self.banco.migrar()[:1], ["040_acesso_vendedores"])  # e as que vieram depois
        with self.banco.conexao() as con:
            escopos = dict(con.execute("SELECT login, escopo FROM usuarios").fetchall())
            colunas = {c for (c,) in con.execute("SELECT column_name FROM information_schema.columns "
                                                  "WHERE table_schema = %s AND table_name = 'usuarios'", [self.schema])}
        self.assertEqual(escopos, {
            "chefe": None,
            "sup.es": {"modo": "equipes", "equipes": ["ES"]},
            "sup.ba": {"modo": "equipes", "equipes": ["BA", "EDIR"]},
            "lista": {"modo": "alguns", "vendedores": [124, 141]},
            "vazia": None,
            "gestor": {"modo": "todos"},
            "somas": {"modo": "alguns", "vendedores": [85, 98]},
            "sem.pagina": None,
            "igual.metas": None,
            "aba.velha": {"modo": "todos"},
            "antigo": None,
        })
        self.assertFalse({"vendedores", "escopo_projecoes", "escopo_assistente", "escopo_gestao"} & colunas)
        self.assertIn("visoes", colunas)  # as abas de Metas ficam
        # O que a migração deixou é o que o painel lê.
        u = Usuarios(self.banco)
        self.assertEqual(escopo_vendedores(u.obter("sup.ba")), (None, {"BA", "EDIR"}))
        self.assertEqual(escopo_vendedores(u.obter("vazia")), (set(), None))

    def test_o_banco_recusa_escopo_mal_formado(self):
        import psycopg  # só aqui: sem o psycopg, a classe inteira é pulada
        self.banco.migrar()
        self.criar_usuario("ana")
        for errado in ('{"modo": "alguns", "vendedores": []}', '{"modo": "equipes"}', '{"modo": "metas"}', '[1]',
                       '{"modo": "alguns", "vendedores": 85}'):
            with self.subTest(errado=errado), self.assertRaises(psycopg.errors.CheckViolation):
                with self.banco.conexao() as con:
                    con.execute("UPDATE usuarios SET escopo = %s::jsonb WHERE login = 'ana'", [errado])


class TestChavesApi(Base):
    """As chaves da API pública (tabela chaves_api): o login de outro aplicativo, uma chave por pessoa e aplicativo."""

    def setUp(self):
        super().setUp()
        self.u.salvar({"login": "bia", "nome": "Bia", "papel": "visualizador", "senha": "segredo1",
                       "paginas": ["gestao"]})
        self.bia = self.u.obter("bia")["id"]

    def entrar(self, login="bia", senha="segredo1", aplicativo="App de Visitas"):
        return self.u.criar_chave(login, senha, aplicativo, 90)

    def mudar_bia(self, **mudancas):
        self.u.salvar({"login": "bia", "nome": "Bia", "papel": "visualizador", "paginas": ["gestao"], **mudancas}, "bia")

    def test_login_devolve_a_chave_e_o_banco_guarda_so_o_hash(self):
        r = self.entrar(" BIA ")
        self.assertRegex(r["chave"], r"^bimv_[A-Za-z0-9_-]{43}$")
        self.assertEqual((r["usuario"], r["aplicativo"]),
                         ({"id": self.bia, "login": "bia", "nome": "Bia", "papel": "visualizador"}, "App de Visitas"))
        with self.banco.conexao() as con:
            guardado = con.execute("SELECT hash FROM chaves_api").fetchall()
        self.assertEqual(guardado, [(hashlib.sha256(r["chave"].encode()).hexdigest(),)])
        usuario, info = self.u.da_chave(r["chave"])
        self.assertEqual((usuario["login"], usuario["paginas"], info["id"], info["aplicativo"]),
                         ("bia", ["gestao"], r["id"], "App de Visitas"))
        self.assertNotIn("senha", usuario)
        self.assertIsNotNone(self.u.obter("bia")["ultimo_acesso"])

    def test_senha_errada_inativo_e_sem_gestao(self):
        self.assertIsNone(self.entrar(senha="errada"))
        self.assertIsNone(self.entrar("ninguem"))
        with self.assertRaises(PermissionError):
            self.entrar("ana")  # só Metas e Assistente
        self.assertIsNotNone(self.entrar("chefe"))  # o administrador tem todas as páginas
        self.mudar_bia(ativo=False)
        self.assertIsNone(self.entrar())
        self.assertEqual(self.contar("chaves_api"), 1)  # só a do chefe

    def test_nome_do_aplicativo(self):
        for ruim in ("", "   ", "x" * 61, "App\x00", "App‮", None, 5):
            with self.assertRaises(ValueError, msg=repr(ruim)):
                self.entrar(aplicativo=ruim)
        self.assertEqual(self.entrar(aplicativo="  App   de\tVisitas ")["aplicativo"], "App de Visitas")

    def test_entrar_de_novo_troca_a_chave_do_mesmo_aplicativo(self):
        a = self.entrar()
        b = self.entrar()
        self.assertEqual(a["id"], b["id"])  # a mesma linha, com a chave nova
        self.assertIsNone(self.u.da_chave(a["chave"]))
        self.assertIsNotNone(self.u.da_chave(b["chave"]))
        c = self.entrar(aplicativo="App de Testes")
        self.assertNotEqual(c["id"], b["id"])
        self.assertIsNotNone(self.u.da_chave(b["chave"]))  # outro aplicativo: as duas valem
        self.assertEqual([x["aplicativo"] for x in self.u.chaves(self.bia)], ["App de Testes", "App de Visitas"])

    def test_vencida_senha_trocada_desativada_e_excluida(self):
        r = self.entrar()
        with self.banco.conexao() as con:
            con.execute("UPDATE chaves_api SET expira_em = now() - interval '1 second'")
        self.assertIsNone(self.u.da_chave(r["chave"]))
        self.assertEqual(self.u.chaves(self.bia), [])
        r = self.entrar()
        self.u.trocar_senha("bia", "segredo1", "nova-senha")  # como o cookie: a troca de senha derruba a chave
        self.assertIsNone(self.u.da_chave(r["chave"]))
        self.assertEqual(self.u.chaves(self.bia), [])
        r = self.entrar(senha="nova-senha")
        self.assertIsNotNone(self.u.da_chave(r["chave"]))
        self.assertEqual(self.contar("chaves_api"), 1)  # as mortas saíram no login
        self.mudar_bia(ativo=False)
        self.assertIsNone(self.u.da_chave(r["chave"]))
        self.mudar_bia(ativo=True)
        self.assertIsNone(self.u.da_chave(r["chave"]))  # reativar não ressuscita a chave
        self.entrar(senha="nova-senha")
        self.u.excluir("bia")
        self.assertEqual(self.contar("chaves_api"), 0)

    def test_tirar_a_gestao_nao_apaga_a_chave(self):
        r = self.entrar()
        self.mudar_bia(paginas=["metas"])
        usuario, _ = self.u.da_chave(r["chave"])
        self.assertEqual(usuario["paginas"], ["metas"])  # quem confere a página é a rota (403)

    def test_senha_trocada_durante_a_conferencia(self):
        conferir = self.u._conferir

        def conferir_e_trocar(login, senha):  # a troca chega entre a conta demorada e a gravação
            u = conferir(login, senha)
            with self.banco.conexao() as con:
                con.execute("UPDATE usuarios SET sessao = sessao + 1 WHERE login = 'bia'")
            return u
        with mock.patch.object(self.u, "_conferir", conferir_e_trocar):
            self.assertIsNone(self.entrar())
        self.assertEqual(self.contar("chaves_api"), 0)

    def test_no_maximo_dez_aplicativos(self):
        for i in range(12):
            self.entrar(aplicativo=f"App {i}")
        nomes = [c["aplicativo"] for c in self.u.chaves(self.bia)]
        self.assertEqual(nomes, [f"App {i}" for i in range(11, 1, -1)])  # os dois mais antigos saíram

    def test_formato_errado_nem_vai_ao_banco(self):
        with mock.patch.object(self.banco, "conexao", side_effect=AssertionError("foi ao banco")):
            for chave in (None, "", 5, "bimv_curta", "x" * 48, "bimv_" + "!" * 43, "bimv_" + "a" * 44):
                self.assertIsNone(self.u.da_chave(chave), repr(chave))
        self.assertIsNone(self.u.da_chave("bimv_" + "a" * 43))  # no formato, mas inventada

    def test_desconectar(self):
        r = self.entrar()
        chefe = self.u.obter("chefe")["id"]
        self.assertFalse(self.u.revogar_chave(chefe, r["id"]))  # de outra pessoa
        self.assertFalse(self.u.revogar_chave(self.bia, "abc"))
        self.assertTrue(self.u.revogar_chave(self.bia, r["id"]))
        self.assertIsNone(self.u.da_chave(r["chave"]))
        self.assertFalse(self.u.revogar_chave(self.bia, r["id"]))

    def test_ultimo_uso_de_tempos_em_tempos(self):
        r = self.entrar()
        self.assertIsNone(self.u.chaves(self.bia)[0]["usada_em"])
        self.u.da_chave(r["chave"])
        self.assertIsNotNone(self.u.chaves(self.bia)[0]["usada_em"])

        def usada(definir: str | None = None):
            with self.banco.conexao() as con:
                if definir:
                    con.execute(f"UPDATE chaves_api SET usada_em = {definir}")
                return con.execute("SELECT usada_em FROM chaves_api").fetchone()[0]
        antiga = usada("now() - interval '6 minutes'")
        self.u.da_chave(r["chave"])  # passou de 5 minutos: grava de novo
        self.assertGreater(usada(), antiga)
        recente = usada("now() - interval '1 minute'")
        self.u.da_chave(r["chave"])  # há 1 minuto: não grava
        self.assertEqual(usada(), recente)


class TestLimiteApi(unittest.TestCase):
    """Os limites da API pública, na memória: pedidos por minuto de cada chave e as vagas ao mesmo tempo."""

    def test_pedidos_por_minuto_de_cada_chave(self):
        limite = LimiteApi(por_minuto=2)
        with mock.patch("bi.acesso.time.monotonic", return_value=1000.0):
            self.assertEqual([limite.espera(1), limite.espera(1)], [0, 0])
            self.assertEqual(limite.espera(1), 61)  # o primeiro pedido sai da janela daqui a 60 s
            self.assertEqual(limite.espera(2), 0)  # outra chave não espera
        with mock.patch("bi.acesso.time.monotonic", return_value=1060.5):
            self.assertEqual(limite.espera(1), 0)

    def test_vagas(self):
        limite = LimiteApi(simultaneos=1, espera_vaga=0.05)
        with limite.vaga():
            with self.assertRaises(ApiOcupada):
                with limite.vaga():
                    pass
        with limite.vaga():  # devolvida depois do pedido
            pass


if __name__ == "__main__":
    unittest.main()

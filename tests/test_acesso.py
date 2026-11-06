"""Usuários no PostgreSQL (bi/acesso.py): cadastro, sessões, as chaves da API pública e o acesso por página (o modo de
vendedores do Assistente e de Projeções). Precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados
(menos os limites da API, que ficam na memória)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import unittest
from unittest import mock

from bi.acesso import ApiOcupada, LimiteApi, Usuarios, escopo_assistente, escopo_gestao, escopo_projecoes
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


class TestEscopoAssistente(Base):
    def setUp(self):
        super().setUp()
        self.u.definir_metas({"ana": {"visoes": ["es"], "vendedores": None}})

    def test_padrao_igual_a_metas(self):
        self.assertEqual(self.ana()["assistente"], {"modo": "metas", "vendedores": None})
        self.assertEqual(escopo_assistente(self.ana()), (None, {"ES"}))
        self.assertEqual(escopo_assistente(self.u.obter("chefe")), (None, None))

    def test_todos_e_alguns(self):
        self.u.definir_assistente({"ana": {"modo": "todos"}})
        self.assertEqual(escopo_assistente(self.ana()), (None, None))
        self.u.definir_assistente({"ana": {"modo": "alguns", "vendedores": [141, 124, 124]}})
        self.assertEqual(escopo_assistente(self.ana()), ({124, 141}, None))
        self.assertEqual(self.ana()["assistente"]["vendedores"], [124, 141])
        # Projeções continua com o seu próprio modo
        self.assertEqual(escopo_projecoes(self.ana()), (None, {"ES"}))

    def test_validacao_e_pagina(self):
        with self.assertRaises(ValueError):
            self.u.definir_assistente({"ana": {"modo": "alguns", "vendedores": []}})
        with self.assertRaises(ValueError):
            self.u.definir_assistente({"ana": {"modo": "qualquer"}})
        self.u.definir_assistente({"ana": {"ve": False, "modo": "metas"}})
        self.assertEqual(self.ana()["paginas"], ["metas"])
        self.u.definir_assistente({"ana": {"ve": True, "modo": "todos"}})
        self.assertEqual(self.ana()["paginas"], ["metas", "assistente"])

    def test_gestao_com_modo_proprio(self):
        self.assertEqual(self.ana()["gestao"], {"modo": "metas", "vendedores": None})
        self.assertEqual(escopo_gestao(self.ana()), (None, {"ES"}))
        self.u.definir_gestao({"ana": {"ve": True, "modo": "alguns", "vendedores": [141]}})
        self.assertEqual(escopo_gestao(self.ana()), ({141}, None))
        self.assertEqual(self.ana()["paginas"], ["metas", "assistente", "gestao"])
        self.assertEqual(escopo_assistente(self.ana()), (None, {"ES"}))  # o Assistente continua com o dele
        self.assertIsNone(self.u.obter("chefe")["gestao"])

    def test_metas_vendedores_e_tudo_ou_nada(self):
        self.u.definir_metas({"ana": {"visoes": ["es", "ba"], "vendedores": [124, 141]}})
        self.assertEqual((self.ana()["visoes"], self.ana()["vendedores"]), (["es", "ba"], [124, 141]))
        with self.assertRaises(ValueError):  # o segundo está errado: o primeiro também não grava
            self.u.definir_metas({"ana": {"visoes": ["es"], "vendedores": None}, "ninguem": {"visoes": ["es"]}})
        self.assertEqual(self.ana()["visoes"], ["es", "ba"])


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

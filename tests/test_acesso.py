"""Usuários no PostgreSQL (bi/acesso.py): cadastro, sessões e o acesso por página (o modo de vendedores do
Assistente e de Projeções). Precisam de BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import unittest
from unittest import mock

from bi.acesso import Usuarios, escopo_assistente, escopo_gestao, escopo_projecoes
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


if __name__ == "__main__":
    unittest.main()

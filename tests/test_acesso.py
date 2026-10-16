"""Acesso por página: o modo de vendedores do Assistente (igual a Metas, todos ou só alguns)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bi.acesso import Usuarios, escopo_assistente, escopo_projecoes


class TestEscopoAssistente(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.u = Usuarios(Path(self._tmp.name) / "usuarios.json")
        self.u.salvar({"login": "chefe", "nome": "Chefe", "papel": "admin", "senha": "segredo1"})
        self.u.salvar({"login": "ana", "nome": "Ana", "papel": "visualizador", "senha": "segredo1",
                       "paginas": ["metas", "assistente"]})
        self.u.definir_metas({"ana": {"visoes": ["es"], "vendedores": None}})

    def tearDown(self):
        self._tmp.cleanup()

    def ana(self):
        return self.u.obter("ana")

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


if __name__ == "__main__":
    unittest.main()

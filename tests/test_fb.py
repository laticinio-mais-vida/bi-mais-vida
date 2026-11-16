"""Shim do fbclient 2.1 (bi/fb.py): o fdb 2.x pede fb_shutdown e fb_shutdown_callback, que a DLL do Firebird 2.1 não
tem, e o shim troca a classe com que o fdb abre a DLL por uma que devolve funções vazias para essas duas. No Windows o
fdb abre com ctypes.WinDLL; no Linux, com o CDLL que o fdb.ibase importou ao ser carregado, então é esse que precisa ser
trocado (trocar ctypes.CDLL não chega no fdb). O teste do Linux também roda no Windows, sem o WinDLL.

Não precisa do Firebird: abre uma biblioteca do sistema, que também não tem essas funções.
"""
from __future__ import annotations

import ctypes
import sys
import unittest
from unittest import mock

from fdb import ibase

from bi import fb

SISTEMA = "kernel32" if sys.platform == "win32" else None  # None: o próprio programa, no Linux


class TestShimClienteLegado(unittest.TestCase):
    def setUp(self):
        # o shim troca classes do ctypes e do fdb.ibase para o processo todo: cada teste devolve as originais no fim
        self.originais = {}
        for modulo, nome in ((ctypes, "WinDLL"), (ctypes, "CDLL"), (ibase, "CDLL")):
            if hasattr(modulo, nome):
                self.originais[modulo.__name__, nome] = getattr(modulo, nome)
                troca = mock.patch.object(modulo, nome, getattr(modulo, nome))
                troca.start()
                self.addCleanup(troca.stop)

    def conferir(self, classe, base):
        self.assertTrue(issubclass(classe, base))
        dll = classe(SISTEMA)
        for nome in ("fb_shutdown", "fb_shutdown_callback"):
            self.assertEqual(getattr(dll, nome)(), 0)
        with self.assertRaises(AttributeError):  # as outras funções que faltam continuam dando erro
            dll.funcao_que_nao_existe

    @unittest.skipUnless(hasattr(ctypes, "WinDLL"), "só no Windows")
    def test_windows_troca_o_windll(self):
        fb._instalar_shim_cliente_legado()
        self.conferir(ctypes.WinDLL, self.originais["ctypes", "WinDLL"])
        self.assertIs(ctypes.CDLL, self.originais["ctypes", "CDLL"])
        self.assertIs(ibase.CDLL, self.originais["fdb.ibase", "CDLL"])

    def test_linux_troca_o_cdll_do_fdb(self):
        if hasattr(ctypes, "WinDLL"):
            del ctypes.WinDLL  # como no Linux; o setUp devolve no fim
        fb._instalar_shim_cliente_legado()
        self.conferir(ibase.CDLL, self.originais["ctypes", "CDLL"])
        self.assertIs(ctypes.CDLL, self.originais["ctypes", "CDLL"])  # não mexe no CDLL do resto do programa

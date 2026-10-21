"""Cache (bi/cache.py): a tabela de pedidos de venda é opcional, como o detalhe por cliente. Um pacote sem ela (PC com
o código anterior) continua valendo; com ela, tem de estar no formato atual. O PC extrai de novo uma vez para trazer
os pedidos, mas não fica tentando a cada minuto se a leitura deles falhou."""
from __future__ import annotations

import configparser
import os
import tempfile
import time
import unittest
from pathlib import Path

import duckdb

from bi.cache import Cache
from tests.apoio import criar_calc


class TestPedidosNoCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def cache(self, pedidos=True, extras=False, rede=True, credito=True) -> Path:
        calc = criar_calc(self.pasta, pedidos=pedidos, extras=extras, rede=rede, credito=credito)
        calc.cache._con.close()
        return self.pasta / "cache.duckdb"

    def test_redes_opcionais(self):
        # sem a tabela das redes (frequência dos clientes): vale, e o PC extrai de novo uma vez para trazê-la
        arquivo = self.cache(rede=False)
        Cache.conferir(arquivo)
        banco = self.pasta / "copia.gdb"
        banco.write_bytes(b"x")
        os.utime(banco, (time.time() - 3600, time.time() - 3600))
        ini = configparser.ConfigParser()
        ini.read_dict({"cache": {"arquivo": arquivo.name}, "banco": {"arquivo": str(banco)}})
        con = duckdb.connect(str(arquivo))
        con.execute("UPDATE info SET valor = ? WHERE chave = 'banco_mtime'", [str(time.time())])
        con.close()
        c = Cache(ini, self.pasta)
        self.assertEqual((c.sem_rede, c.sem_pedidos, c.desatualizado()), (True, False, True))
        c.info["rede_erro"] = "Table unknown REDES"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE clientes_rede (id INTEGER)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("clientes_rede", str(e.exception))

    def test_credito_opcional(self):
        # sem os títulos e os limites (PC com o código anterior): vale, e o PC extrai de novo uma vez para trazê-los
        arquivo = self.cache(credito=False)
        Cache.conferir(arquivo)
        banco = self.pasta / "copia.gdb"
        banco.write_bytes(b"x")
        os.utime(banco, (time.time() - 3600, time.time() - 3600))
        ini = configparser.ConfigParser()
        ini.read_dict({"cache": {"arquivo": arquivo.name}, "banco": {"arquivo": str(banco)}})
        con = duckdb.connect(str(arquivo))
        con.execute("UPDATE info SET valor = ? WHERE chave = 'banco_mtime'", [str(time.time())])
        con.close()
        c = Cache(ini, self.pasta)
        self.assertEqual((c.sem_credito, c.sem_rede, c.desatualizado()), (True, False, True))
        c.info["credito_erro"] = "Table unknown CONTASRECEBER"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE titulos_receber (id INTEGER, total DOUBLE)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("titulos_receber", str(e.exception))

    def test_conferir_aceita_sem_pedidos_mas_nao_errados(self):
        Cache.conferir(self.cache(pedidos=True))
        (self.pasta / "cache.duckdb").unlink()
        Cache.conferir(self.cache(pedidos=False))  # pacote do PC com o código anterior
        con = duckdb.connect(str(self.pasta / "cache.duckdb"))
        con.execute("CREATE TABLE pedidos_venda (data DATE, id_vendedor INTEGER)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(self.pasta / "cache.duckdb")
        self.assertIn("pedidos_venda", str(e.exception))

    def test_sem_pedidos_e_desatualizado(self):
        arquivo = self.cache(pedidos=False)
        banco = self.pasta / "copia.gdb"
        banco.write_bytes(b"x")
        os.utime(banco, (time.time() - 3600, time.time() - 3600))  # cópia mais velha que a extração
        ini = configparser.ConfigParser()
        ini.read_dict({"cache": {"arquivo": arquivo.name}, "banco": {"arquivo": str(banco)}})
        con = duckdb.connect(str(arquivo))
        con.execute("UPDATE info SET valor = ? WHERE chave = 'banco_mtime'", [str(time.time())])
        con.close()
        c = Cache(ini, self.pasta)
        self.assertTrue(c.sem_pedidos)
        self.assertTrue(c.desatualizado())  # falta a tabela nova: extrai de novo uma vez
        c.info["pedidos_erro"] = "Table unknown PEDIDOVENDAS"
        self.assertFalse(c.desatualizado())  # a leitura falhou: espera a próxima cópia do banco
        c._con.close()
        arquivo.unlink()
        arquivo = self.cache(pedidos=True)
        c = Cache(ini, self.pasta)
        self.assertFalse(c.sem_pedidos)
        c._con.close()


if __name__ == "__main__":
    unittest.main()

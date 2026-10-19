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

    def cache(self, pedidos=True, extras=False) -> Path:
        calc = criar_calc(self.pasta, pedidos=pedidos, extras=extras)
        calc.cache._con.close()
        return self.pasta / "cache.duckdb"

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

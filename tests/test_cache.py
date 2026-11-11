"""Cache (bi/cache.py): a tabela de pedidos de venda é opcional, como o detalhe por cliente. Um pacote sem ela (PC com
o código anterior) continua valendo; com ela, tem de estar no formato atual. O PC extrai de novo uma vez para trazer
os pedidos, mas não fica tentando a cada minuto se a leitura deles falhou."""
from __future__ import annotations

import configparser
import datetime as dt
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import duckdb

from bi.cache import Cache
from tests.apoio import criar_calc


class TestPedidosNoCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def cache(self, pedidos=True, extras=False, rede=True, credito=True, parcelas=True, carteira=True,
              brindes=True, comissao=True, pedidos_detalhe=True, devolucoes_notas=True, bloqueios=True) -> Path:
        calc = criar_calc(self.pasta, pedidos=pedidos, extras=extras, rede=rede, credito=credito, parcelas=parcelas,
                          carteira=carteira, brindes=brindes, comissao=comissao, pedidos_detalhe=pedidos_detalhe,
                          devolucoes_notas=devolucoes_notas, bloqueios=bloqueios)
        calc.cache._con.close()
        return self.pasta / "cache.duckdb"

    def test_pedidos_detalhe_opcionais(self):
        # sem os pedidos um a um (PC com o código anterior): vale, e o PC extrai de novo uma vez para trazê-los; se a
        # leitura falhou, espera a próxima cópia
        arquivo = self.cache(pedidos_detalhe=False)
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
        self.assertEqual((c.sem_pedidos_detalhe, c.sem_pedidos, c.desatualizado()), (True, False, True))
        c.info["pedidos_detalhe_erro"] = "Table unknown LISTAPEDIDOVENDA"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE pedidos_venda_itens (id_pedido INTEGER, total DOUBLE)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("pedidos_venda_itens", str(e.exception))
        arquivo.unlink()
        self.cache()
        c = Cache(ini, self.pasta)
        self.assertFalse(c.sem_pedidos_detalhe)
        c._con.close()

    def test_brindes_opcionais(self):
        # sem os brindes (PC com o código anterior): vale, e o PC extrai de novo uma vez para trazê-los; se a leitura
        # falhou, espera a próxima cópia
        arquivo = self.cache(brindes=False)
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
        self.assertEqual((c.sem_brindes, c.sem_credito, c.desatualizado()), (True, False, True))
        c.info["brindes_erro"] = "Table unknown BRINDES"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE brindes_clientes_itens (data DATE, valor DOUBLE)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("brindes_clientes_itens", str(e.exception))

    def test_comissao_opcional(self):
        # sem a comissão (PC com o código anterior): vale, e o PC extrai de novo uma vez para trazê-la; se a leitura
        # falhou, espera a próxima cópia
        arquivo = self.cache(comissao=False)
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
        self.assertEqual((c.sem_comissao, c.sem_brindes, c.desatualizado()), (True, False, True))
        c.info["comissao_erro"] = "Table unknown CONFIGCOMISSAOVENDEDOR"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE comissoes_percentuais (id_vendedor INTEGER, pct DOUBLE)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("comissoes_percentuais", str(e.exception))

    def test_devolucoes_notas_opcionais(self):
        # sem as devoluções nota a nota (PC com o código anterior): vale, e o PC extrai de novo uma vez para trazê-las;
        # se a leitura falhou, espera a próxima cópia
        arquivo = self.cache(devolucoes_notas=False)
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
        self.assertEqual((c.sem_devolucoes_notas, c.sem_brindes, c.desatualizado()), (True, False, True))
        c.info["devolucoes_notas_erro"] = "Column unknown NUMDOCUMENTO"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE devolucoes_notas (id_devolucao INTEGER, valor DOUBLE)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("devolucoes_notas", str(e.exception))
        arquivo.unlink()
        self.cache()
        c = Cache(ini, self.pasta)
        self.assertFalse(c.sem_devolucoes_notas)
        c._con.close()

    def test_bloqueio_opcional(self):
        # sem o bloqueio dos clientes (PC com o código anterior): vale, e o PC extrai de novo uma vez para trazê-lo; se a
        # leitura falhou, espera a próxima cópia. O site com o código anterior aceita o pacote com a tabela nova.
        arquivo = self.cache(bloqueios=False)
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
        self.assertEqual((c.sem_bloqueio, c.sem_credito, c.desatualizado()), (True, False, True))
        c.info["bloqueio_erro"] = "Column unknown OBSBLOQUEADO"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE clientes_bloqueio (id INTEGER, bloqueado BOOLEAN)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("clientes_bloqueio", str(e.exception))
        arquivo.unlink()
        self.cache()
        c = Cache(ini, self.pasta)
        self.assertFalse(c.sem_bloqueio)
        c._con.close()

    def test_carteira_opcional(self):
        # sem o histórico da carteira (PC com o código anterior): vale, e o PC extrai de novo uma vez para registrá-la;
        # se o registro falhou (banco fora do ar), espera a próxima cópia
        arquivo = self.cache(carteira=False)
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
        self.assertEqual((c.sem_carteira, c.sem_rede, c.desatualizado()), (True, False, True))
        c.info["carteira_erro"] = "o banco de dados está fora do ar"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE clientes_vigencias (id_cliente INTEGER)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("clientes_vigencias", str(e.exception))

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
        self.assertTrue(c.desatualizado())  # as parcelas também faltam e não têm erro registrado
        c.info["parcelas_erro"] = "Table unknown CONTASRECEBER"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE titulos_receber (id INTEGER, total DOUBLE)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("titulos_receber", str(e.exception))

    def test_parcelas_opcionais(self):
        # cache do PC com o código anterior (crédito sem as parcelas): vale, o crédito funciona e o PC extrai de novo
        # uma vez para trazê-las
        arquivo = self.cache(parcelas=False)
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
        self.assertEqual((c.sem_parcelas, c.sem_credito, c.desatualizado()), (True, False, True))
        c.info["parcelas_erro"] = "Table unknown PARCELASCONTASRECEBER"
        self.assertFalse(c.desatualizado())
        c._con.close()
        con = duckdb.connect(str(arquivo))
        con.execute("CREATE TABLE titulos_parcelas (id INTEGER)")
        con.close()
        with self.assertRaises(ValueError) as e:
            Cache.conferir(arquivo)
        self.assertIn("titulos_parcelas", str(e.exception))

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


class _ErpFalso:
    """No lugar de bi.fb.BancoSomenteLeitura: responde vazio a tudo, menos aos pedidos um a um e aos itens deles, às
    devoluções nota a nota e ao bloqueio dos clientes."""
    falhar_itens = False
    falhar_notas = False
    falhar_bloqueio = False
    chamadas: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def consulta(self, sql, params=()):
        type(self).chamadas.append((sql, params))
        if "FROM STATUSPEDIDO" in sql:
            return [("V", "Venda"), ("C", "Cancelado"), ("L", "Liberado")]
        if sql.startswith("SELECT p.ID_PEDIDOVENDA,"):
            # (id, data, criado em, entrega, cliente, tipo, vendedor, tipo do pedido, status, cancelada, origem,
            #  ID_VENDA, nota fiscal, total, desconto, peso líquido)
            return [
                (13, dt.date(2026, 11, 9), dt.datetime(2026, 11, 6, 8, 0), None, 7, "FUNCIONARIO", 134, "PEDIDOVENDA",
                 "A", 0, "F", None, None, 0.0, 0.0, 0.0),                                  # status fora da tabela
                (10, dt.date(2026, 11, 5), dt.datetime(2026, 11, 3, 15, 38), dt.date(2026, 11, 5), 12892, "CLIENTE",
                 134, "PEDIDOVENDA", "V", 0, "F", 749743, "055770", 176.5, 0.0, 13.84),
                (11, dt.date(2026, 11, 5), dt.datetime(2026, 11, 5, 9, 0), None, 500, "CLIENTE", 0, "PEDIDOBRINDE",
                 "B", 0, "F", 5555, "645271", 60.0, None, None),                           # brinde: ID_VENDA é BRINDES
                (12, dt.date(2026, 11, 6), dt.datetime(2026, 11, 6, 8, 0), None, 12892, "CLIENTE", 134, "PEDIDOVENDA",
                 "C", 1, "C", None, "", 90.0, 0.0, 1.0),                                   # cancelado, sem nota
            ]
        if sql.startswith("SELECT d.ID_DEVOLUCAO,"):
            if type(self).falhar_notas:
                raise RuntimeError("Column unknown NUMDOCUMENTO")
            # (id, número, série, emissão, entrada, vendedor, cliente, tipo, cancelada, produto, motivo, valor, qtd)
            return [
                (15790, "643997", "013", dt.datetime(2026, 10, 27), dt.datetime(2026, 10, 27), 120, 12270, "CLIENTE", 0,
                 32, 1, 12992.79, 300.0),
                (15741, " 001329 ", "3", dt.date(2026, 9, 25), dt.date(2026, 10, 15), 98, 500, "CLIENTE", 0, 11469, 3,
                 1239.25, 400.0),                                                          # nota do cliente, mais antiga
                (15700, "", "013", dt.date(2026, 10, 2), dt.date(2026, 10, 2), 98, 500, "CLIENTE", 1, 27, 2, 50.0, 2.0),
            ]
        if sql.startswith("SELECT ID_CLIENTE, BLOQUEADO, DATABLOQUEADO, OBSBLOQUEADO"):
            if type(self).falhar_bloqueio:
                raise RuntimeError("Column unknown OBSBLOQUEADO")
            # (cliente, bloqueado, data, observação), como o ERP guarda
            return [
                (11734, 1, dt.datetime(2026, 11, 4), "BLOQUEADO POR PERDA DE RECEBIMENTO\r\n\r\n\r\nDA NF  617569.  "),
                (9300, 1, dt.datetime(1899, 12, 30), None),                   # bloqueado sem data nem observação
                (10908, 0, dt.datetime(2024, 4, 19), "RETIRADO O PRAZO."),   # desbloqueado: a observação fica
                (5754, 0, None, "   \r\n  "),                               # só espaços: fica de fora
                (4765, None, None, b"AUTORIZA\xc7\xc3O DO FINANCEIRO"),       # texto em bytes (cp1252)
            ]
        if "FROM LISTAPEDIDOVENDA" in sql:
            if type(self).falhar_itens:
                raise RuntimeError("Table unknown LISTAPEDIDOVENDA")
            return [(11, 32, 2.0, 30.0, 30.0, 0.0, 60.0), (10, 32, 4.04, 37.5, 38.0, 0.0, 151.5),
                    (10, 27, 1.0, 25.0, 25.0, None, 25.0)]  # fora de ordem: o cache grava por pedido
        return []


class TestPedidosUmAUm(unittest.TestCase):
    """A extração dos pedidos um a um (Cache._extrair), sem o Firebird."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        banco = self.pasta / "copia.gdb"
        banco.write_bytes(b"x")
        self.ini = configparser.ConfigParser()
        self.ini.read_dict({"cache": {"arquivo": "cache.duckdb", "inicio": "2024-01-01"},
                            "banco": {"arquivo": str(banco), "usuario": "SYSDBA", "senha": "x"}})
        _ErpFalso.falhar_itens, _ErpFalso.falhar_notas, _ErpFalso.falhar_bloqueio = False, False, False
        _ErpFalso.chamadas = []

    def tearDown(self):
        self._tmp.cleanup()

    def atualizar(self) -> Cache:
        c = Cache(self.ini, self.pasta)
        with mock.patch("bi.fb.BancoSomenteLeitura", _ErpFalso):
            c.atualizar()
        self.assertIsNone(c.estado["erro"])
        return c

    def test_pedidos_e_itens_no_cache(self):
        c = self.atualizar()
        self.assertFalse(c.sem_pedidos_detalhe)
        pedidos = {r[0]: r for r in c.consulta(
            "SELECT id, data, entrega, tipopedido, status, status_nome, cancelada, id_venda, id_brinde, nota_fiscal, "
            "total, desconto, peso_liquido FROM pedidos_venda_detalhe")}
        self.assertEqual(pedidos[10], (10, dt.date(2026, 11, 5), dt.date(2026, 11, 5), "PEDIDOVENDA", "V", "Venda",
                                       False, 749743, None, "055770", 176.5, 0.0, 13.84))
        # pedido de brinde: o código do ERP vai para id_brinde (a nota é a do brinde), e o status B ganha nome mesmo
        # fora da STATUSPEDIDO; a nota fica em texto, com o zero da frente
        self.assertEqual(pedidos[11][3:13], ("PEDIDOBRINDE", "B", "Brinde", False, None, 5555, "645271", 60.0, 0.0, 0.0))
        self.assertEqual(pedidos[12][4:10], ("C", "Cancelado", True, None, None, None))  # sem nota: vazio vira nulo
        self.assertEqual(pedidos[13][4:6], ("A", None))
        itens = c.consulta("SELECT id_pedido, COUNT(*), SUM(total) FROM pedidos_venda_itens GROUP BY 1 ORDER BY 1")
        self.assertEqual(itens, [(10, 2, 176.5), (11, 1, 60.0)])
        # gravados em ordem (sem índice, a consulta de um pedido ou período pula o resto)
        self.assertEqual([r[0] for r in c.consulta("SELECT id_pedido FROM pedidos_venda_itens")], [10, 10, 11])
        self.assertEqual([r[0] for r in c.consulta("SELECT id FROM pedidos_venda_detalhe")], [10, 11, 12, 13])
        # pedido para entregar nos próximos dias entra; mais longe, não
        params = next(p for s, p in _ErpFalso.chamadas if s.startswith("SELECT p.ID_PEDIDOVENDA,"))
        self.assertEqual(params[1].date(), dt.date.today() + dt.timedelta(days=31))
        self.assertNotIn("pedidos_detalhe_erro", c.info)
        c._con.close()

    def test_falha_nos_itens_deixa_os_dois_de_fora(self):
        _ErpFalso.falhar_itens = True
        c = self.atualizar()
        self.assertTrue(c.sem_pedidos_detalhe)
        self.assertIn("LISTAPEDIDOVENDA", c.info["pedidos_detalhe_erro"])
        nomes = {r[0] for r in c.consulta("SELECT table_name FROM information_schema.tables")}
        self.assertFalse(nomes & {"pedidos_venda_detalhe", "pedidos_venda_itens"})
        self.assertIn("pedidos_venda", nomes)  # o resto da extração segue
        self.assertFalse(c.desatualizado())  # espera a próxima cópia
        c._con.close()


    def test_devolucoes_nota_a_nota(self):
        c = self.atualizar()
        self.assertFalse(c.sem_devolucoes_notas)
        notas = {r[0]: r for r in c.consulta(
            "SELECT id_devolucao, nota, serie, emissao, data, id_vendedor, id_cliente, tipocliente, cancelada, id_produto, "
            "id_motivo, valor, quantidade FROM devolucoes_notas")}
        # o número fica em texto, com o zero da frente e sem espaços; a emissão pode ser bem antes da entrada
        self.assertEqual(notas[15741][1:5], ("001329", "3", dt.date(2026, 9, 25), dt.date(2026, 10, 15)))
        self.assertEqual(notas[15790][1:3] + notas[15790][4:5], ("643997", "013", dt.date(2026, 10, 27)))
        self.assertEqual(notas[15700][1], None)  # sem número: vazio vira nulo
        self.assertEqual(notas[15700][8], True)  # cancelada, com a marca
        # gravadas por entrada (sem índice, como os pedidos)
        self.assertEqual([r[0] for r in c.consulta("SELECT id_devolucao FROM devolucoes_notas")], [15700, 15741, 15790])
        self.assertNotIn("devolucoes_notas_erro", c.info)
        c._con.close()

    def test_falha_nas_notas_de_devolucao(self):
        _ErpFalso.falhar_notas = True
        c = self.atualizar()
        self.assertTrue(c.sem_devolucoes_notas)
        self.assertIn("NUMDOCUMENTO", c.info["devolucoes_notas_erro"])
        nomes = {r[0] for r in c.consulta("SELECT table_name FROM information_schema.tables")}
        self.assertNotIn("devolucoes_notas", nomes)
        self.assertIn("devolucoes_clientes_itens", nomes)  # o resto da extração segue
        self.assertFalse(c.desatualizado())  # espera a próxima cópia
        c._con.close()

    def test_bloqueio_dos_clientes(self):
        c = self.atualizar()
        self.assertFalse(c.sem_bloqueio)
        linhas = {r[0]: r[1:] for r in c.consulta("SELECT id, bloqueado, data, observacao FROM clientes_bloqueio")}
        self.assertEqual(linhas, {
            11734: (True, dt.date(2026, 11, 4), "BLOQUEADO POR PERDA DE RECEBIMENTO\n\nDA NF 617569."),
            9300: (True, None, None),  # o "zero" do ERP (30/12/1899) vira nulo
            10908: (False, dt.date(2024, 4, 19), "RETIRADO O PRAZO."),
            4765: (False, None, "AUTORIZAÇÃO DO FINANCEIRO"),
        })  # o 5754 (só espaços, sem bloqueio) fica de fora
        self.assertNotIn("bloqueio_erro", c.info)
        c._con.close()

    def test_falha_no_bloqueio(self):
        _ErpFalso.falhar_bloqueio = True
        c = self.atualizar()
        self.assertTrue(c.sem_bloqueio)
        self.assertIn("OBSBLOQUEADO", c.info["bloqueio_erro"])
        nomes = {r[0] for r in c.consulta("SELECT table_name FROM information_schema.tables")}
        self.assertNotIn("clientes_bloqueio", nomes)
        self.assertIn("clientes_detalhes", nomes)  # o resto da extração segue
        self.assertFalse(c.desatualizado())  # espera a próxima cópia
        c._con.close()


if __name__ == "__main__":
    unittest.main()

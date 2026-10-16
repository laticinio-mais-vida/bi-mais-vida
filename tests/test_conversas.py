"""Histórico de conversas no PostgreSQL (bi/banco.py e bi/conversas.py).

Os testes com o banco precisam de um PostgreSQL de teste; sem ele, são pulados. Por exemplo:
    docker run --rm -e POSTGRES_PASSWORD=teste -p 5433:5432 postgres:18-alpine
    $env:BI_TESTE_POSTGRES = "postgresql://postgres:teste@localhost:5433/postgres"   (PowerShell)
    python -m unittest discover -s tests -t .
Cada teste usa um schema temporário, apagado no fim.
"""
from __future__ import annotations

import configparser
import importlib.util
import os
import time
import unittest
import uuid

from bi.banco import Banco, BancoForaDoAr
from bi.conversas import Conversas, NaoEncontrada, titulo_de

DSN = os.environ.get("BI_TESTE_POSTGRES")
TEM_PSYCOPG = importlib.util.find_spec("psycopg") is not None and importlib.util.find_spec("psycopg_pool") is not None


def config_postgres(dsn: str) -> configparser.ConfigParser:
    from psycopg.conninfo import conninfo_to_dict
    p = conninfo_to_dict(dsn)
    ini = configparser.ConfigParser()
    ini.read_dict({"postgres": {"host": p.get("host") or "localhost", "porta": p.get("port") or "5432",
                                "banco": p.get("dbname") or "postgres", "usuario": p.get("user") or "postgres",
                                "senha": p.get("password") or ""}})
    return ini


def resposta(texto: str, consultas: str = "") -> dict:
    return {"texto": texto, "consultas": consultas, "passos": [{"ferramenta": "resumo_vendas", "linhas": 3}],
            "data_ref": "2026-10-15", "aviso": None, "uso": {"segundos": 4.2}}


class TestTitulo(unittest.TestCase):
    def test_titulo(self):
        self.assertEqual(titulo_de("  Quanto   vendemos\neste mês?"), "Quanto vendemos")
        self.assertEqual(titulo_de("\n\n  "), "Nova conversa")
        longo = titulo_de("Quais clientes compraram no mês passado e ainda não compraram este mês, por vendedor?")
        self.assertEqual(longo, "Quais clientes compraram no mês passado e ainda não…")
        self.assertLessEqual(len(longo), 61)
        self.assertEqual(titulo_de("x" * 100), "x" * 60 + "…")


@unittest.skipUnless(TEM_PSYCOPG, "sem o pacote psycopg")
class TestForaDoAr(unittest.TestCase):
    def test_banco_que_nao_responde(self):
        ini = configparser.ConfigParser()
        ini.read_dict({"postgres": {"host": "127.0.0.1", "porta": "9"}})  # porta fechada
        banco = Banco(ini)
        try:
            inicio = time.time()
            with self.assertRaises(BancoForaDoAr):
                Conversas(banco).listar("ana")
            self.assertLess(time.time() - inicio, 15)
            banco.iniciar()  # na subida do painel só avisa, não derruba
        finally:
            banco.fechar()

    def test_sem_host_nao_esta_configurado(self):
        self.assertFalse(Banco(configparser.ConfigParser()).configurado)


@unittest.skipUnless(DSN and TEM_PSYCOPG, "defina BI_TESTE_POSTGRES para testar com um PostgreSQL")
class TestConversas(unittest.TestCase):
    def setUp(self):
        self.schema = "teste_" + uuid.uuid4().hex[:10]
        self.banco = Banco(config_postgres(DSN), schema=self.schema)
        self.c = Conversas(self.banco)

    def tearDown(self):
        with self.banco._conexao() as con:
            con.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        self.banco.fechar()

    def nova(self, login="ana", pergunta="Quanto vendemos este mês?", texto="R$ 10.000,00.", consultas="") -> str:
        id_ = str(uuid.uuid4())
        self.c.acrescentar(login, id_, pergunta, resposta(texto, consultas))
        return id_

    def contar_mensagens(self) -> int:
        with self.banco.conexao() as con:
            return con.execute("SELECT count(*) FROM mensagens").fetchone()[0]

    def test_migracoes_uma_vez_so(self):
        self.assertEqual(self.banco.migrar(), ["001_conversas"])
        self.assertEqual(self.banco.migrar(), [])
        self.banco.iniciar()

    def test_acrescentar_obter_e_historico(self):
        id_ = self.nova(pergunta="Quais os 10 clientes que mais compraram no mês passado, por faturamento líquido?",
                        consultas='resumo_vendas{"de":"2026-09-01"}')
        meta = self.c.acrescentar("ana", id_, "e em agosto?", resposta("Em agosto, R$ 8.000,00."))
        self.assertEqual(meta["id"], id_)
        self.assertEqual(meta["titulo"], "Quais os 10 clientes que mais compraram no mês passado, por…")
        conversa = self.c.obter("ana", id_)
        self.assertEqual([m["papel"] for m in conversa["mensagens"]], ["usuario", "assistente"] * 2)
        ia = conversa["mensagens"][1]
        self.assertEqual(ia["texto"], "R$ 10.000,00.")
        self.assertEqual(ia["passos"], [{"ferramenta": "resumo_vendas", "linhas": 3}])
        self.assertEqual((ia["data_ref"], ia["uso"]), ("2026-10-15", {"segundos": 4.2}))
        self.assertEqual(self.c.historico("ana", id_), [
            {"papel": "usuario", "texto": "Quais os 10 clientes que mais compraram no mês passado, por faturamento líquido?"},
            {"papel": "assistente", "texto": "R$ 10.000,00.", "consultas": 'resumo_vendas{"de":"2026-09-01"}'},
            {"papel": "usuario", "texto": "e em agosto?"},
            {"papel": "assistente", "texto": "Em agosto, R$ 8.000,00."},
        ])

    def test_cada_pessoa_ve_so_as_suas(self):
        id_ = self.nova("ana")
        self.assertEqual([c["id"] for c in self.c.listar("ana")], [id_])
        self.assertEqual(self.c.listar("bia"), [])
        self.assertIsNone(self.c.obter("bia", id_))
        self.assertIsNone(self.c.historico("bia", id_))
        with self.assertRaises(NaoEncontrada):
            self.c.renomear("bia", id_, "minha")
        with self.assertRaises(NaoEncontrada):
            self.c.excluir("bia", id_)
        with self.assertRaises(NaoEncontrada):
            self.c.acrescentar("bia", id_, "e agora?", resposta("ok"))
        self.assertEqual(len(self.c.obter("ana", id_)["mensagens"]), 2)

    def test_ids_invalidos(self):
        for id_ in ("", None, "abc", "1; DROP TABLE conversas"):
            self.assertIsNone(self.c.obter("ana", id_))
            self.assertIsNone(self.c.historico("ana", id_))
            with self.assertRaises(NaoEncontrada):
                self.c.excluir("ana", id_)

    def test_ordem_e_busca(self):
        primeira = self.nova(pergunta="Vendas de Açaí em setembro", texto="R$ 1.000,00.")
        segunda = self.nova(pergunta="Metas do mês", texto="A produção ficou em 50% da meta.")
        self.assertEqual([c["id"] for c in self.c.listar("ana")], [segunda, primeira])
        self.c.acrescentar("ana", primeira, "e em outubro?", resposta("R$ 2.000,00."))  # sobe para o topo
        self.assertEqual([c["id"] for c in self.c.listar("ana")], [primeira, segunda])
        self.assertEqual([c["id"] for c in self.c.listar("ana", "acai")], [primeira])        # no título, sem acento
        self.assertEqual([c["id"] for c in self.c.listar("ana", "PRODUÇAO")], [segunda])   # nas mensagens
        self.assertEqual([c["id"] for c in self.c.listar("ana", "50%")], [segunda])
        self.assertEqual([c["id"] for c in self.c.listar("ana", "%")], [segunda])  # % e _ são procurados como texto
        self.assertEqual(self.c.listar("ana", "_"), [])
        self.assertEqual(self.c.listar("bia", "acai"), [])

    def test_renomear(self):
        id_ = self.nova()
        antes = self.c.listar("ana")[0]
        meta = self.c.renomear("ana", id_, "  Vendas   do mês ")
        self.assertEqual(meta["titulo"], "Vendas do mês")
        self.assertEqual(meta["atualizada_em"], antes["atualizada_em"])  # renomear não muda a ordem
        for titulo in ("", "   ", "x" * 81):
            with self.assertRaises(ValueError):
                self.c.renomear("ana", id_, titulo)
        with self.assertRaises(NaoEncontrada):
            self.c.renomear("ana", str(uuid.uuid4()), "outra")

    def test_excluir_apaga_as_mensagens(self):
        id_ = self.nova()
        outra = self.nova()
        self.c.excluir("ana", id_)
        self.assertEqual([c["id"] for c in self.c.listar("ana")], [outra])
        self.assertEqual(self.contar_mensagens(), 2)
        with self.assertRaises(NaoEncontrada):
            self.c.excluir("ana", id_)

    def test_mudar_e_apagar_login_junto_do_cadastro(self):
        id_ = self.nova("ana")
        with self.assertRaises(ValueError):
            with self.c.mudar_login("ana", "ana.paula"):
                raise ValueError("o cadastro recusou")
        self.assertEqual(len(self.c.listar("ana")), 1)  # voltou atrás
        with self.c.mudar_login("ana", "ana.paula"):
            pass
        self.assertEqual(self.c.listar("ana"), [])
        self.assertEqual([c["id"] for c in self.c.listar("ana.paula")], [id_])
        self.nova("bia")
        with self.assertRaises(ValueError):
            with self.c.apagar_login("ana.paula"):
                raise ValueError("o cadastro recusou")
        self.assertEqual(len(self.c.listar("ana.paula")), 1)
        with self.c.apagar_login("ana.paula"):
            pass
        self.assertEqual(self.c.listar("ana.paula"), [])
        self.assertEqual(len(self.c.listar("bia")), 1)
        self.assertEqual(self.contar_mensagens(), 2)


if __name__ == "__main__":
    unittest.main()

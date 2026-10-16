"""Cache sintético, cliente falso da API e o banco de teste (nada aqui lê o ERP ou chama a internet).

Os testes com o banco precisam de um PostgreSQL de teste; sem ele, são pulados. Por exemplo:
    docker run --rm -e POSTGRES_PASSWORD=teste -p 5433:5432 postgres:18-alpine
    $env:BI_TESTE_POSTGRES = "postgresql://postgres:teste@localhost:5433/postgres"   (PowerShell)
    python -m unittest discover -s tests -t .
No PC, serve o PostgreSQL instalado (um banco só para os testes, ex.: createdb -U postgres bi_teste). Cada teste usa
um schema temporário, apagado no fim.
"""
from __future__ import annotations

import collections
import configparser
import copy
import datetime as dt
import importlib.util
import os
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

import duckdb

from bi.assistente import Assistente
from bi.banco import Banco, BancoForaDoAr
from bi.cache import TABELAS, TABELAS_DETALHE, Cache
from bi.configuracao import _valida, padrao
from bi.conversas import DETALHES, id_valido, titulo_de
from bi.metas import Calculadora

DSN = os.environ.get("BI_TESTE_POSTGRES")
TEM_PSYCOPG = importlib.util.find_spec("psycopg") is not None and importlib.util.find_spec("psycopg_pool") is not None

# Vendedores do padrão das metas: 124 = ES, 141 = BA, 85 = Edir.
ES, BA, EDIR = 124, 141, 85
NOMES = {ES: "Rubens", BA: "Thais", EDIR: "Edir"}
D = dt.date


class ConfiguracaoFixa:
    """As regras de Metas em memória, com a mesma interface de bi/configuracao.py (sem o banco)."""

    def __init__(self, cfg: dict | None = None):
        self._cfg = _valida(cfg or padrao())

    def atual(self) -> dict:
        return copy.deepcopy(self._cfg)

    def validar(self, novo: dict) -> dict:
        return _valida(novo)

    def salvar(self, novo: dict, autor=None) -> dict:
        self._cfg = _valida(novo)
        return self.atual()


class PlanilhaFalsa:
    def __init__(self, linhas):
        self._linhas, self.versao, self.aviso = linhas, 1, None

    def dados(self):
        return self._linhas


def criar_calc(pasta: Path, fora: tuple[int, ...] = ()) -> Calculadora:
    con = duckdb.connect(str(pasta / "cache.duckdb"))
    for nome, colunas in {**TABELAS, **TABELAS_DETALHE}.items():
        con.execute(f"CREATE TABLE {nome} ({colunas})")
    # (data, vendedor, cliente, tipo, produto, valor, quantidade)
    vendas = [
        (D(2026, 9, 2), ES, 1, "CLIENTE", 32, 1000.0, 50.0),
        (D(2026, 9, 2), ES, 1, "CLIENTE", 27, 300.0, 10.0),
        (D(2026, 9, 15), ES, 3, "CLIENTE", 3643, 200.0, 20.0),   # 3643 vira 11469 (equivalência)
        (D(2026, 9, 20), ES, 7, "FUNCIONARIO", 32, 80.0, 4.0),   # código 7 de outro cadastro
        (D(2026, 9, 3), BA, 2, "CLIENTE", 32, 5000.0, 250.0),
        (D(2026, 9, 3), BA, 2, "CLIENTE", 999, 400.0, 1.0),      # produto que pode ficar "fora"
        (D(2026, 8, 10), BA, 2, "CLIENTE", 32, 4000.0, 200.0),
        (D(2026, 9, 5), EDIR, 4, "CLIENTE", 32, 700.0, 35.0),
    ]
    con.executemany("INSERT INTO vendas_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?)", vendas)
    con.execute("INSERT INTO vendas_itens SELECT data, id_vendedor, id_produto, SUM(valor), SUM(quantidade) "
                "FROM vendas_clientes_itens GROUP BY ALL")
    con.execute("INSERT INTO vendas_clientes SELECT data, id_vendedor, id_cliente, tipocliente, 1 "
                "FROM vendas_clientes_itens GROUP BY ALL")
    con.execute("INSERT INTO vendas_clientes_mes SELECT date_trunc('month', data), id_cliente, tipocliente, id_produto, "
                "SUM(valor) FROM vendas_clientes_itens GROUP BY ALL")
    # (data, vendedor, cliente, tipo, produto, motivo, cancelada, valor, quantidade)
    devolucoes = [
        (D(2026, 9, 10), ES, 1, "CLIENTE", 32, 1, False, 100.0, 5.0),   # motivo 1 desconta
        (D(2026, 9, 11), ES, 1, "CLIENTE", 27, 3, False, 50.0, 2.0),    # motivo 3 não desconta
        (D(2026, 9, 12), BA, 2, "CLIENTE", 32, 2, True, 500.0, 25.0),   # cancelada não desconta
        (D(2026, 9, 13), BA, 2, "CLIENTE", 32, 2, False, 250.0, 12.0),
    ]
    con.executemany("INSERT INTO devolucoes_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", devolucoes)
    con.execute("INSERT INTO devolucoes_itens SELECT data, id_vendedor, id_produto, id_motivo, cancelada, SUM(valor), "
                "SUM(quantidade) FROM devolucoes_clientes_itens GROUP BY ALL")
    con.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?)", [
        (32, "QUEIJO MUSSARELA 4KG", 1, "MUSSARELA", "KG", 0), (27, "MANTEIGA 200G", 2, "MANTEIGA", "UN", 0),
        (11469, "BEBIDA LACTEA 500G", 3, "BEBIDAS", "UN", 0), (3643, "BEBIDA LACTEA 540G", 3, "BEBIDAS", "UN", 1),
        (999, "CARROCERIA USADA", 9, "IMOBILIZADO", "UN", 0)])
    con.executemany("INSERT INTO vendedores VALUES (?, ?, ?, ?, ?)", [
        (ES, "RUBENS - ES", 3, "VALDIRENE", 0), (BA, "THAIS - CENTRAL", 7, "MARCOS", 0), (EDIR, "EDIR - PS", 8, "TERC", 0)])
    con.executemany("INSERT INTO clientes VALUES (?, ?, ?)", [
        (1, "MERCADO DO JOAO", ES), (2, "PADARIA DA MARIA", BA), (3, "ACOUGUE SAO JOSE", ES), (4, "MERCEARIA DO EDIR", EDIR),
        (7, "CLIENTE SETE", BA)])
    con.executemany("INSERT INTO clientes_detalhes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, "JOAO COMERCIO LTDA", "VILA VELHA", "ES", 1, "ROTA 1", 1, "MERCADO", 0, D(2020, 1, 1)),
        (2, "MARIA PAES LTDA", "PORTO SEGURO", "BA", 2, "ROTA 2", 2, "PADARIA", 0, D(2021, 1, 1)),
        (3, "SAO JOSE CARNES", "SERRA", "ES", 1, "ROTA 1", 3, "AÇOUGUE", 0, D(2022, 1, 1))])
    con.executemany("INSERT INTO motivos VALUES (?, ?)", [(1, "ERRO DE LANÇAMENTO"), (2, "RECUSA"), (3, "VENCIDO")])
    con.executemany("INSERT INTO info VALUES (?, ?)", [
        ("data_ref", "2026-09-30"), ("extraido_em", "2026-10-01T08:00:00"), ("banco_mtime", "0"),
        ("banco_copia", "2026-10-01T07:00"), ("inicio", "2026-01-01")])
    con.close()

    ini = configparser.ConfigParser()
    ini.read_dict({"cache": {"arquivo": "cache.duckdb", "inicio": "2026-01-01"},
                   "banco": {"arquivo": str(pasta / "nao-existe.gdb")}})
    cache = Cache(ini, pasta)
    cfg = padrao()
    for pid in fora:
        cfg["produtos"][str(pid)] = {"grupo": "fora", "categoria": None}
    configuracao = ConfiguracaoFixa(cfg)
    metas = PlanilhaFalsa([
        {"mes": D(2026, 9, 1), "id_vendedor": ES, "vendedor": "RUBENS", "meta_fat": 2000.0, "meta_mus": 800.0,
         "meta_out": 1200.0, "meta_cli": 3.0},
        {"mes": D(2026, 9, 1), "id_vendedor": BA, "vendedor": "THAIS", "meta_fat": 6000.0, "meta_mus": 0.0,
         "meta_out": 0.0, "meta_cli": 2.0},
    ])
    metas_prod = PlanilhaFalsa([
        {"mes": D(2026, 9, 1), "id_vendedor": BA, "vendedor": "THAIS", "id_produto": 32, "produto": "MUSSARELA",
         "meta_volume": 300.0}])
    return Calculadora(cache, metas, metas_prod, configuracao)


def config_ia(**valores) -> configparser.ConfigParser:
    ini = configparser.ConfigParser()
    ini.read_dict({"ia": {"chave": "sk-ant-teste", **{k: str(v) for k, v in valores.items()}}})
    return ini


def criar_assistente(pasta: Path, calc: Calculadora, cliente=None, conversas=None, registro=None, **ia) -> Assistente:
    return Assistente(config_ia(**ia), calc, lambda: dict(NOMES), registro or RegistroFalso(), cliente=cliente,
                      conversas=conversas)


class RegistroFalso:
    """Imita o registro de uso de bi/uso.py em memória."""

    def __init__(self):
        self.registros = []
        self.fora_do_ar = False

    def gravar(self, r):
        if self.fora_do_ar:
            raise BancoForaDoAr("banco de teste fora do ar")
        self.registros.append({**r, "quando": dt.datetime.now()})

    def do_dia(self, usuario):
        hoje = [r for r in self.registros if r["quando"].date() == dt.date.today()]
        return sum(r["usuario"] == usuario for r in hoje), sum(r["uso"]["custo"] for r in hoje)

    def resumo(self, dias):
        por = collections.Counter(r["login"] for r in self.registros)
        return {"hoje": {"perguntas": len(self.registros), "custo": sum(r["uso"]["custo"] for r in self.registros)},
                "por_usuario": [{"login": k, "perguntas": n} for k, n in por.most_common()], "ultimas": []}


class ConversasFalsas:
    """Imita o histórico de bi/conversas.py em memória (os testes do Assistente não precisam do PostgreSQL)."""

    def __init__(self):
        self.dados = {}  # id -> {"usuario", "titulo", "mensagens"}
        self.fora_do_ar = False

    def _banco(self):
        if self.fora_do_ar:
            raise BancoForaDoAr("banco de teste fora do ar")

    def verificar(self):
        self._banco()

    def historico(self, usuario, id_):
        self._banco()
        c = self.dados.get(id_valido(id_))
        if not c or c["usuario"] != usuario:
            return None
        return [{"papel": m["papel"], "texto": m["texto"], **({"consultas": m["consultas"]} if m.get("consultas") else {})}
                for m in c["mensagens"]]

    def acrescentar(self, usuario, id_, pergunta, resposta):
        self._banco()
        c = self.dados.setdefault(id_, {"usuario": usuario, "titulo": titulo_de(pergunta), "mensagens": []})
        c["mensagens"] += [{"papel": "usuario", "texto": pergunta},
                           {"papel": "assistente", "texto": resposta["texto"], **{k: resposta.get(k) for k in DETALHES}}]
        return {"id": id_, "titulo": c["titulo"]}


# --- cliente falso da API ---------------------------------------------------------------
def bloco_texto(texto):
    return SimpleNamespace(type="text", text=texto)


def bloco_pensamento():
    return SimpleNamespace(type="thinking", thinking="", signature="assinatura")


def bloco_ferramenta(id_, nome, entrada):
    return SimpleNamespace(type="tool_use", id=id_, name=nome, input=entrada)


def resposta(*blocos, parada="end_turn", entrada=1000, saida=100, cache_leitura=0, cache_escrita=0):
    uso = SimpleNamespace(input_tokens=entrada, output_tokens=saida, cache_read_input_tokens=cache_leitura,
                          cache_creation_input_tokens=cache_escrita)
    return SimpleNamespace(content=list(blocos), stop_reason=parada, usage=uso, model="claude-opus-5-5",
                           id="msg_teste", _request_id="req_teste")


class ClienteFalso:
    """Imita client.beta.messages.create: devolve as respostas do roteiro e guarda cada pedido."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.pedidos = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **pedido):
        # guarda uma cópia rasa da lista de mensagens: o assistente continua acrescentando nela depois
        self.pedidos.append({**pedido, "messages": list(pedido["messages"])})
        if not self.roteiro:
            raise AssertionError("o roteiro acabou")
        r = self.roteiro.pop(0)
        return r(pedido) if callable(r) else r


USUARIO_ADMIN = {"id": 1, "login": "admin", "nome": "Admin", "papel": "admin"}
USUARIO_VIS = {"id": 2, "login": "vis", "nome": "Visualizador", "papel": "visualizador"}


# --- banco de teste ---------------------------------------------------------------------
def config_postgres(dsn: str) -> configparser.ConfigParser:
    from psycopg.conninfo import conninfo_to_dict
    p = conninfo_to_dict(dsn)
    ini = configparser.ConfigParser()
    ini.read_dict({"postgres": {"host": p.get("host") or "localhost", "porta": p.get("port") or "5432",
                                "banco": p.get("dbname") or "postgres", "usuario": p.get("user") or "postgres",
                                "senha": p.get("password") or ""}})
    return ini


@unittest.skipUnless(DSN and TEM_PSYCOPG, "defina BI_TESTE_POSTGRES para testar com um PostgreSQL")
class BaseBanco(unittest.TestCase):
    """Cada teste num schema temporário. raiz: pasta de onde a migração 005 importa os arquivos (None = nada)."""

    raiz = None

    def setUp(self):
        self.schema = "teste_" + uuid.uuid4().hex[:10]
        self.banco = self.novo_banco(self.raiz)

    def novo_banco(self, raiz=None) -> Banco:
        return Banco(config_postgres(DSN), schema=self.schema, raiz=raiz)

    def tearDown(self):
        with self.banco._conexao() as con:
            con.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        self.banco.fechar()

    def criar_usuario(self, login: str, papel: str = "visualizador") -> int:
        """Direto na tabela (sem a conta demorada da senha): para testes que só precisam de um dono."""
        with self.banco.conexao() as con:
            return con.execute("INSERT INTO usuarios (login, nome, papel, senha, paginas) VALUES (%s, %s, %s, 'x', "
                               "%s::text[]) RETURNING id", [login, login.title(), papel,
                                                            None if papel == "admin" else ["metas", "assistente"]]
                               ).fetchone()[0]

    def contar(self, tabela: str, onde: str = "true") -> int:
        with self.banco.conexao() as con:
            return con.execute(f"SELECT count(*) FROM {tabela} WHERE {onde}").fetchone()[0]

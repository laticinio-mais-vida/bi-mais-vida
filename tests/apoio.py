"""Cache sintético e cliente falso da API para os testes (nada aqui lê o ERP ou chama a internet)."""
from __future__ import annotations

import configparser
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import duckdb

from bi.assistente import Assistente
from bi.cache import TABELAS, TABELAS_DETALHE, Cache
from bi.configuracao import Configuracao, padrao
from bi.metas import Calculadora

# Vendedores do padrão das metas: 124 = ES, 141 = BA, 85 = Edir.
ES, BA, EDIR = 124, 141, 85
NOMES = {ES: "Rubens", BA: "Thais", EDIR: "Edir"}
D = dt.date


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
    configuracao = Configuracao(pasta / "config_metas.json")
    configuracao.salvar(cfg)
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


def criar_assistente(pasta: Path, calc: Calculadora, cliente=None, **ia) -> Assistente:
    return Assistente(config_ia(**ia), calc, lambda: dict(NOMES), pasta / "logs", cliente=cliente)


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


USUARIO_ADMIN = {"login": "admin", "nome": "Admin", "papel": "admin"}
USUARIO_VIS = {"login": "vis", "nome": "Visualizador", "papel": "visualizador"}

"""CRM (bi/crm.py): as regras padrão, a validação, os quatro indicadores, a nota, o acesso, o detalhe, o Excel e a
leitura da planilha de custos. Tudo com um cache sintético (sem o ERP e sem o banco)."""
from __future__ import annotations

import configparser
import copy
import datetime as dt
import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import duckdb

from bi.cache import (TABELAS, TABELAS_CREDITO, TABELAS_DETALHE, TABELAS_PEDIDOS, TABELAS_PEDIDOS_DETALHE, TABELAS_REDE,
                      Cache)
from bi.configuracao import Regras, padrao
from bi.conversas import NaoEncontrada
from bi.crm import (PADRAO, ConfigCrm, Crm, _valida, arredondar, cortes_quintis, custos_efetivos, ler_planilha_custos,
                    menos_meses, pontos_rentabilidade, ultimo_sabado)
from tests.apoio import BaseBanco

D = dt.date
ES, BA, EDIR, FUNC = 124, 141, 85, 84
COPIA = D(2026, 11, 19)              # quinta-feira: o semestre vai de 17/05 a 14/11/2026
INI, FIM = D(2026, 5, 17), D(2026, 11, 14)
MUSSARELA_LINHA = "A - LINHA DE QUEIJO MUSSARELA"
PRODUTOS = [(32, "QUEIJO MUSSARELA MAIS VIDA 4KG", 1, MUSSARELA_LINHA, "KG", 0),
            (25, "MANTEIGA 200G", 2, "A - LINHA DE MANTEIGA", "UND", 0),
            (26, "MANTEIGA 500G", 2, "A - LINHA DE MANTEIGA", "UND", 0),
            (27, "MANTEIGA A GRANEL 1 KG", 2, "A - LINHA DE MANTEIGA", "KG", 0),
            (5754, "MANTEIGA A GRANEL 1 KG S", 2, "A - LINHA DE MANTEIGA", "KG", 0),
            (9616, "QUEIJO DE COALHO 370G PALITO", 3, "A - LINHA DE QUEIJO COALHO", "KG", 0),
            (5973, "QUEIJO COALHO 4KG", 3, "A - LINHA DE QUEIJO COALHO", "KG", 0),
            (24, "QUEIJO PARMESAO PECA C 5KG", 4, "A - LINHA DE QUEIJO PARMESAO", "KG", 0),
            (11469, "BEB. LACTEA MORANGO 500G BANDEJA", 5, "A - LINHA DE BEBIDA LACTEA", "UN", 0),
            (3643, "BEB. LACTEA MORANGO 540G BANDEJA", 9, "XXX PRODUTOS INATIVOS", "UN", 0),
            (11098, "REQUEIJAO CREMOSO 180G", 6, "A - LINHA REQUEIJAO CREMOSO", "UND", 0),
            (10352, "BEB. LACTEA MORANGO 800 G", 5, "A - LINHA DE BEBIDA LACTEA", "UN", 0),
            (999, "OUTRO PRODUTO", 7, "OUTRAS", "UN", 0),
            (9999, "PRODUTO SEM CUSTO", 7, "OUTRAS", "UN", 0)]
# (id, nome, vendedor, segmento, rede, inativo)
CLIENTES = [
    (1, "SEMANAL PERFEITO (CLIENTE 1)", ES, "PADARIA", "SEMANAL", 0),
    (2, "SEMANAL VINTE SEMANAS", ES, "PADARIA", "SEMANAL", 0),
    (3, "SEMANAL TREZE SEMANAS", ES, "PADARIA", "SEMANAL", 0),
    (4, "SEMANAL DOZE SEMANAS", ES, "PADARIA", "SEMANAL", 0),
    (5, "QUINZENAL EM DIA", BA, "RESTAURANTE", "QUINZENAL", 0),
    (6, "QUINZENAL ATRASO", BA, "RESTAURANTE", "Quinzenal", 0),
    (7, "MENSAL TRINTA DIAS", BA, "SUPERMERCADO", "MENSAL", 0),
    (8, "NOVO SEMANAL", ES, "PADARIA", "SEMANAL", 0),
    (9, "RECENTE", ES, "PADARIA", "SEMANAL", 0),
    (10, "NUNCA COMPROU", ES, "PADARIA", "SEMANAL", 0),
    (11, "MERCADO PEDIDO BLOQUEADO", ES, "PADARIA", "SEMANAL", 0),
    (12, "OUTRA REDE", ES, "OUTROS", "REDE NOSSA REDE", 0),
    (13, "CLIENTE DO EDIR", EDIR, "PADARIA", "SEMANAL", 0),
    (14, "INATIVO", ES, "PADARIA", "SEMANAL", 1),
    (15, "SEM SEGMENTO", ES, None, None, 0),
]


def semana(k: int, dia: int = 1) -> dt.date:
    """O dia da semana k do semestre (0 = a que começa em 17/05); dia: 0 = domingo, 1 = segunda..."""
    return INI + dt.timedelta(days=7 * k + dia)


def a_cada(inicio: dt.date, passo: int, ate: dt.date = FIM, pula: tuple[int, ...] = ()) -> list[dt.date]:
    datas, d, n = [], inicio, 0
    while d <= ate:
        if n not in pula:
            datas.append(d)
        d += dt.timedelta(days=passo)
        n += 1
    return datas


# As compras (pedidos de venda) de cada cliente; os itens do pedido entram no mix. (cliente, data, produtos, cancelado)
def pedidos():
    lista = []

    def add(c, datas, produtos=(999,), cancelado=False):
        lista.extend((c, d, produtos, cancelado) for d in datas)

    add(1, [D(2026, 1, 5)] + [semana(k) for k in range(26)])
    add(1, [semana(k, 5) for k in range(6)])                         # 2ª compra na semana: não conta
    add(1, [semana(3)], (25, 26, 32))                                # manteigas e a mussarela pela linha
    add(1, [D(2026, 4, 1)], (11098,))                                # antes do semestre: fora do mix
    add(1, [semana(4)], (10352,), True)                              # cancelado: fora
    add(2, [D(2026, 1, 5)] + [semana(k) for k in range(20)])
    add(3, [D(2026, 1, 5)] + [semana(k) for k in range(13)])
    add(4, [D(2026, 1, 5)] + [semana(k) for k in range(12)])
    add(5, a_cada(D(2026, 5, 4), 14))
    add(5, [semana(2)], (9616, 5754, 24))                            # coalho palito, manteiga granel S e parmesão
    add(6, a_cada(D(2026, 5, 4), 14, pula=(6,)))                      # uma quinzena sem compra: 28 dias, 13 de atraso
    add(7, a_cada(D(2026, 4, 20), 30))
    add(7, [semana(5)], (3643,))                                     # 3643 conta como 11469
    add(8, a_cada(D(2026, 9, 2), 7))                                 # primeira compra em setembro
    add(9, [D(2026, 11, 2)])                                         # primeira compra há menos de 1 mês
    add(11, [semana(1)])
    add(12, [D(2026, 1, 5)] + [semana(k) for k in range(26)])
    add(12, [semana(1)], (25,))
    add(13, [semana(k) for k in range(26)])
    add(14, [semana(k) for k in range(26)])
    add(15, [D(2026, 1, 5)] + [semana(k) for k in range(26)])
    return lista


def titulos():
    """(id, cliente, vendedor, emissão, vencimento, quitação, quitado, total)."""
    t, n = [], [0]

    def add(cliente, venc, dias_atraso=None, aberto=False):
        n[0] += 1
        quit = None if aberto else venc + dt.timedelta(days=dias_atraso)
        t.append((n[0], cliente, ES, venc - dt.timedelta(days=14), venc, quit, 0 if aberto else 1, 100.0))

    base = D(2025, 1, 10)
    for k in range(25):
        add(1, base + dt.timedelta(days=10 * k), 2)                   # pontual (2 dias depois)
    add(1, D(2023, 12, 20), 40)                                       # antes de 2024: fora
    add(1, D(2026, 11, 15), aberto=True)                              # ainda na tolerância: fora
    for k in range(9):
        add(2, base + dt.timedelta(days=10 * k), 0)
    add(2, D(2026, 3, 1), 8)                                          # 90% e atraso médio de 8 dias: 15
    for k in range(9):
        add(3, base + dt.timedelta(days=10 * k), 7)                   # 7 dias ainda é pontual
    add(3, D(2026, 10, 10), aberto=True)                              # em aberto há 40 dias: 15 - 10 = 5
    for k in range(5):
        add(4, base + dt.timedelta(days=10 * k), 1)
        add(4, base + dt.timedelta(days=10 * k + 5), 50)              # 50% e 50 dias: 0 - 10, fica em 0
    for k in range(24):
        add(5, base + dt.timedelta(days=10 * k), 0)
    add(5, D(2026, 6, 1), 20)                                         # 96% e 20 dias de atraso: 20 - 5 = 15
    return t


# Vendas faturadas (data, vendedor, cliente, tipo, produto, valor, quantidade): o lucro bruto da rentabilidade.
VENDAS = [
    (D(2026, 3, 10), ES, 1, "CLIENTE", 32, 3000.0, 100.0),            # 100 kg a 30: lucro (30 - 20) x 100 = 1.000
    (D(2026, 4, 10), ES, 2, "CLIENTE", 26, 150.0, 10.0),              # 10 a 15: (15 - 10) x 10 = 50
    (D(2026, 6, 10), ES, 3, "CLIENTE", 32, 1250.0, 50.0),             # 50 a 25: 250
    (D(2026, 10, 10), ES, 3, "CLIENTE", 32, 5000.0, 100.0),           # outubro: sem custo ainda, fora do período
    (D(2026, 7, 10), ES, 4, "CLIENTE", 5754, 280.0, 20.0),            # usa o custo da 26 (10): 80
    (D(2026, 8, 10), BA, 5, "CLIENTE", 32, 5600.0, 200.0),            # 1.600
    (D(2026, 8, 12), BA, 5, "CLIENTE", 9999, 500.0, 5.0),             # sem custo: fica fora do lucro
    (D(2026, 9, 10), BA, 6, "CLIENTE", 32, 220.0, 10.0),              # 20
    (D(2026, 9, 10), BA, 6, "FUNCIONARIO", 32, 9999.0, 1.0),          # não é cliente: fora
    (D(2026, 5, 10), EDIR, 13, "CLIENTE", 26, 300.0, 20.0),           # fora do CRM (outra equipe): 100 na página de Crédito
    (D(2026, 9, 20), EDIR, 13, "CLIENTE", 3643, 90.0, 10.0),          # 3643 conta como 11469, que não tem custo
]


def regras_teste() -> dict:
    cfg = copy.deepcopy(PADRAO)
    meses = [f"2026-{m:02d}" for m in range(1, 10)]
    cfg["rentabilidade"]["custos"] = {"32": {m: 20.0 for m in meses}, "26": {m: 10.0 for m in meses}}
    cfg["rentabilidade"]["usa_custo_de"] = {"5754": 26}
    return _valida(cfg)


class ConfigFixa:
    nome = "crm"

    def __init__(self, cfg):
        self._cfg = _valida(cfg)
        self.banco = SimpleNamespace(conexao=lambda: _SemBanco())

    def atual(self):
        return copy.deepcopy(self._cfg)


class _SemBanco:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a):
        return SimpleNamespace(fetchone=lambda: None)


def criar_cache(pasta: Path) -> Cache:
    con = duckdb.connect(str(pasta / "cache.duckdb"))
    for nome, colunas in {**TABELAS, **TABELAS_DETALHE, **TABELAS_PEDIDOS, **TABELAS_PEDIDOS_DETALHE, **TABELAS_REDE,
                          **TABELAS_CREDITO}.items():
        con.execute(f"CREATE TABLE {nome} ({colunas})")
    con.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?)", PRODUTOS)
    con.executemany("INSERT INTO vendedores VALUES (?, ?, ?, ?, ?)", [
        (ES, "RUBENS - ES", 3, "VALDIRENE", 0), (BA, "THAIS - CENTRAL", 7, "MARCOS", 0),
        (EDIR, "EDIR - PS", 8, "TERCEIROS", 0), (FUNC, "FUNCIONARIO", None, None, 0)])
    con.executemany("INSERT INTO clientes VALUES (?, ?, ?)", [(c, n, v) for c, n, v, *_ in CLIENTES])
    con.executemany("INSERT INTO clientes_detalhes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(c, n, "SERRA", "ES", 1, "AREA", 1, s, ina, D(2020, 1, 1)) for c, n, v, s, r, ina in CLIENTES])
    con.executemany("INSERT INTO clientes_rede VALUES (?, ?)", [(c, r) for c, n, v, s, r, ina in CLIENTES if r])
    vend = {c: v for c, n, v, *_ in CLIENTES}
    resumo, detalhe, itens = {}, [], []
    for n, (c, d, produtos, cancelado) in enumerate(pedidos(), start=1):
        if not cancelado:
            resumo[(d, c)] = resumo.get((d, c), 0) + 1
        detalhe.append((n, d, dt.datetime.combine(d, dt.time(9)), d, c, "CLIENTE", vend[c], "PEDIDOVENDA", "V", "Venda",
                        cancelado, "FV", n, None, None, 100.0, 0.0, 1.0))
        itens.extend((n, p, 1.0, 10.0, 10.0, 0.0, 10.0) for p in produtos)
    con.executemany("INSERT INTO pedidos_venda VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(d, vend[c], c, "CLIENTE", "PEDIDOVENDA", 0, k, 100.0 * k) for (d, c), k in resumo.items()])
    con.executemany("INSERT INTO pedidos_venda_detalhe VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    detalhe)
    con.executemany("INSERT INTO pedidos_venda_itens VALUES (?, ?, ?, ?, ?, ?, ?)", itens)
    con.executemany("INSERT INTO titulos_receber VALUES (?, ?, ?, ?, ?, ?, ?, ?)", titulos())
    con.executemany("INSERT INTO vendas_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?)", VENDAS)
    con.executemany("INSERT INTO vendas_itens VALUES (?, ?, ?, ?, ?)",
                    [(d, v, p, val, q) for d, v, c, t, p, val, q in VENDAS])
    con.executemany("INSERT INTO info VALUES (?, ?)", [
        ("data_ref", "2026-11-18"), ("extraido_em", "2026-11-19T08:00:00"), ("banco_mtime", "0"),
        ("banco_copia", "2026-11-19T07:00"), ("inicio", "2024-01-01")])
    con.close()
    ini = configparser.ConfigParser()
    ini.read_dict({"cache": {"arquivo": "cache.duckdb", "inicio": "2024-01-01"},
                   "banco": {"arquivo": str(pasta / "nao-existe.gdb")}})
    return Cache(ini, pasta)


class TestRegras(unittest.TestCase):
    def test_padrao_valido_e_soma_cem(self):
        cfg = _valida(PADRAO)
        self.assertEqual(cfg["equipes"], ["ES", "BA"])
        self.assertEqual(len(cfg["mix"]["segmentos"]), 17)
        self.assertEqual(cfg["mix"]["segmentos"]["RESTAURANTE"],
                         [{"produtos": [5973, 9616]}, {"produtos": [26, 27, 5754]}, {"produtos": [24]},
                          {"produtos": [8991]}, {"mussarela": True}])
        self.assertEqual(cfg["mix"]["segmentos"]["PIZZARIA"][1], {"produtos": [24, 4046]})
        self.assertNotIn({"mussarela": True}, cfg["mix"]["segmentos"]["ACOUGUE"])
        efetivos = custos_efetivos(cfg)
        self.assertEqual(efetivos[5754], efetivos[27])
        self.assertEqual(efetivos[12175], efetivos[12552])
        self.assertEqual(efetivos[21]["2026-02"], efetivos[21]["2026-01"])  # o prato de fevereiro = janeiro
        self.assertEqual(efetivos[21]["2026-06"], efetivos[21]["2026-05"])

    def test_recusa_o_que_nao_fecha(self):
        def com(**mudar):
            cfg = copy.deepcopy(PADRAO)
            for caminho, valor in mudar.items():
                alvo = cfg
                *partes, ultima = caminho.split("__")
                for p in partes:
                    alvo = alvo[p]
                alvo[ultima] = valor
            return cfg
        casos = {
            "precisam dar 100": com(mix__pontos=30),
            "mais pontos": com(aderencia__faixas=[{"de": 100, "pontos": 10}, {"de": 75, "pontos": 15}]),
            "mesmo valor": com(pontualidade__faixas=[{"de": 90, "pontos": 20}, {"de": 90, "pontos": 15}]),
            "próprio custo": com(rentabilidade__usa_custo_de={"27": 27}),
            "também usa": com(rentabilidade__usa_custo_de={"5754": 27, "27": 26}),
            "custo próprio": com(rentabilidade__usa_custo_de={"26": 27}),
            "dois itens": com(mix__segmentos={"PADARIA": [{"produtos": [25]}, {"produtos": [25, 26]}]}),
            "mês inválido": com(rentabilidade__custos={"32": {"2026-13": 10}}),
            "equipe": com(equipes=["SP"]),
            "5 faixas": com(rentabilidade__pontos=[40, 30, 20]),
        }
        for trecho, cfg in casos.items():
            with self.subTest(trecho):
                with self.assertRaises(ValueError) as e:
                    _valida(cfg)
                self.assertIn(trecho, str(e.exception))

    def test_mix_normaliza_o_segmento_e_tira_o_vazio(self):
        cfg = copy.deepcopy(PADRAO)
        cfg["mix"]["segmentos"] = {"Açougue": [{"produtos": ["25"]}], "PADARIA": []}
        self.assertEqual(_valida(cfg)["mix"]["segmentos"], {"ACOUGUE": [{"produtos": [25]}]})

    def test_contas(self):
        self.assertEqual(ultimo_sabado(COPIA), FIM)
        self.assertEqual(ultimo_sabado(D(2026, 11, 22)), D(2026, 11, 21))  # domingo: o sábado de ontem fechou
        self.assertEqual(ultimo_sabado(D(2026, 11, 21)), FIM)              # sábado: a semana ainda não fechou
        self.assertEqual(menos_meses(D(2026, 3, 31), 1), D(2026, 2, 28))
        self.assertEqual(arredondar(82.5), 83)
        self.assertEqual(arredondar(2.4999), 2)
        cortes = cortes_quintis([float(x) for x in range(1, 11)])
        self.assertEqual(cortes, [2.0, 4.0, 6.0, 8.0])
        self.assertEqual([pontos_rentabilidade(x, cortes, [40, 30, 20, 10, 0])[0] for x in range(10, 0, -1)],
                         [40, 40, 30, 30, 20, 20, 10, 10, 0, 0])


class TestCalculo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cache = criar_cache(Path(cls.tmp.name))
        sup = {ES: 3, BA: 7, EDIR: 8, FUNC: None}
        calc = SimpleNamespace(cache=cache, regras=lambda: Regras(padrao(), sup))
        cls.crm = Crm(calc, ConfigFixa(regras_teste()), lambda: {ES: "Rubens", BA: "Thais", EDIR: "Edir"})
        cls.d = cls.crm.listar(None)
        cls.c = {x["id"]: x for x in cls.d["itens"]}

    @classmethod
    def tearDownClass(cls):
        cls.crm.calc.cache._con.close()
        cls.tmp.cleanup()

    def test_quem_entra(self):
        self.assertEqual(sorted(self.c), [1, 2, 3, 4, 5, 6, 7, 8, 12, 15])
        self.assertEqual(self.d["fora"], {"sem_compra": 1, "recente": 1})  # 10 nunca comprou; 9 é de novembro
        self.assertEqual(self.c[1]["nome"], "SEMANAL PERFEITO")             # sem o código que o ERP põe no nome
        self.assertEqual(self.d["regras"]["periodo"]["ini"], INI.isoformat())
        self.assertEqual(self.d["regras"]["periodo"]["fim"], FIM.isoformat())

    def test_aderencia(self):
        pts = {i: self.c[i]["aderencia"]["pontos"] for i in self.c}
        self.assertEqual(pts, {1: 20, 2: 15, 3: 10, 4: 0, 5: 20, 6: 15, 7: 20, 8: 20, 12: 20, 15: 20})
        self.assertEqual(self.c[1]["aderencia"]["com_compra"], 26)          # a 2ª compra da semana não conta
        self.assertEqual(self.c[6]["aderencia"]["atraso"], 13)              # 28 dias entre compras, prazo de 15
        self.assertEqual(self.c[6]["aderencia"]["maior_distancia"], 28)
        self.assertEqual(self.c[8]["aderencia"]["semanas"], 11)             # desde a semana da primeira compra
        self.assertEqual(self.c[12]["frequencia"], "outra rede")
        self.assertEqual(self.c[15]["frequencia"], "sem rede")
        self.assertEqual(self.c[6]["frequencia"], "quinzenal")              # "Quinzenal" no cadastro

    def test_pontualidade(self):
        p = {i: self.c[i]["pontualidade"] for i in (1, 2, 3, 4, 5, 6)}
        self.assertEqual(p[1]["titulos"], 25)                                # sem o de 2023 e o da tolerância
        self.assertEqual(p[1]["pontos"], 20)
        self.assertEqual((p[2]["base"], p[2]["desconto"], p[2]["pontos"]), (15, 0, 15))
        self.assertEqual((p[3]["base"], p[3]["desconto"], p[3]["pontos"]), (15, 10, 5))
        self.assertEqual(p[3]["atraso_medio"], 40)
        self.assertEqual(p[3]["em_aberto"], 1)
        self.assertEqual((p[4]["base"], p[4]["pontos"]), (0, 0))             # não fica negativo
        self.assertEqual((p[5]["base"], p[5]["desconto"], p[5]["pontos"]), (20, 5, 15))  # desconta também em 96%
        self.assertEqual((p[6]["titulos"], p[6]["pontos"]), (0, 20))
        self.assertIn("sem título", p[6]["sinal"])

    def test_mix(self):
        self.assertEqual((self.c[1]["mix"]["atendidos"], self.c[1]["mix"]["itens"]), (3, 21))
        self.assertAlmostEqual(self.c[1]["mix"]["pontos"], 20 * 3 / 21, places=4)
        self.assertEqual((self.c[5]["mix"]["atendidos"], self.c[5]["mix"]["pontos"]), (3, 12))  # palito, granel S, peça
        self.assertEqual(self.c[7]["mix"]["atendidos"], 1)                   # 3643 conta como 11469
        self.assertEqual(self.c[12]["mix"]["pontos"], 0)
        self.assertIn("sem mix ideal", self.c[12]["mix"]["sinal"])
        self.assertIn("sem segmento", self.c[15]["mix"]["sinal"])
        self.assertEqual(self.c[2]["mix"]["atendidos"], 0)

    def test_rentabilidade(self):
        r = {i: self.c[i]["rentabilidade"] for i in self.c}
        self.assertEqual(r[1]["lucro"], 1000.0)
        self.assertEqual(r[3]["lucro"], 250.0)                               # a venda de outubro fica fora
        self.assertEqual(r[4]["lucro"], 80.0)                                # 5754 com o custo da 26
        self.assertEqual((r[5]["lucro"], r[5]["sem_custo"]), (1600.0, 500.0))
        self.assertEqual(r[6]["lucro"], 20.0)                                # sem a venda a funcionário
        self.assertEqual(self.d["regras"]["rentabilidade"]["ate"], "2026-09")
        self.assertEqual(self.d["regras"]["rentabilidade"]["cortes"], [0.0, 0.0, 50.0, 250.0])
        self.assertEqual({i: r[i]["pontos"] for i in r},
                         {1: 40, 5: 40, 3: 30, 4: 30, 2: 20, 6: 20, 7: 0, 8: 0, 12: 0, 15: 0})
        self.assertEqual([x["id"] for x in self.d["sem_custo"]], [9999])
        self.assertTrue(any("sem custo industrial" in a for a in self.d["avisos"]))

    def test_nota(self):
        self.assertAlmostEqual(self.c[1]["nota_exata"], 20 + 20 + 20 * 3 / 21 + 40, places=3)
        self.assertEqual(self.c[1]["nota"], 83)
        self.assertEqual(self.c[5]["nota"], 20 + 15 + 12 + 40)
        self.assertEqual(self.c[3]["nota"], 10 + 5 + 0 + 30)
        self.assertEqual(self.d["itens"][0]["id"], 5)                       # da maior nota para a menor
        self.assertEqual(self.c[12]["sinais"][0], "segmento OUTROS sem mix ideal")

    def test_acesso_por_vendedor(self):
        d = self.crm.listar(frozenset({ES}))
        self.assertEqual(sorted(x["id"] for x in d["itens"]), [1, 2, 3, 4, 8, 12, 15])
        self.assertEqual(d["fora"], {"sem_compra": 1, "recente": 1})
        self.assertEqual(sum(v["sem_compra"] + v["recente"] for v in d["fora_vendedores"].values()), 2)
        self.assertEqual(self.crm.listar(frozenset({BA}))["fora"], {"sem_compra": 0, "recente": 0})
        self.assertEqual(self.crm.listar(frozenset({BA}))["fora_vendedores"], {})
        # a rentabilidade continua pelos quintis do CRM inteiro: o acesso não muda os pontos
        self.assertEqual({x["id"]: x["rentabilidade"]["pontos"] for x in d["itens"]}[1], 40)
        with self.assertRaises(NaoEncontrada):
            self.crm.cliente(frozenset({BA}), 1)

    def test_detalhe(self):
        r = self.crm.cliente(None, 1)
        self.assertEqual(len(r["compras"]), 26)
        self.assertEqual(r["compras"][0], semana(0).isoformat())
        feitos = [x["nome"] for x in r["mix_itens"] if x["atendido"]]
        self.assertEqual(feitos, ["MANTEIGA 200G", "MANTEIGA 500G", "Qualquer mussarela"])
        self.assertEqual(len(r["mix_itens"]), 21)
        self.assertEqual(r["rent_meses"], [{"mes": "2026-03", "faturamento": 3000.0, "lucro": 1000.0,
                                            "sem_custo": 0.0}])
        r5 = self.crm.cliente(None, "5")
        self.assertEqual([x["nome"] for x in r5["mix_itens"] if x["atendido"]],
                         ["QUEIJO COALHO 4KG ou QUEIJO DE COALHO 370G PALITO",
                          "MANTEIGA 500G ou MANTEIGA A GRANEL 1 KG ou MANTEIGA A GRANEL 1 KG S",
                          "QUEIJO PARMESAO PECA C 5KG"])
        self.assertEqual(r5["rent_produtos"][0]["nome"], "QUEIJO MUSSARELA MAIS VIDA 4KG")
        self.assertEqual(r5["rent_produtos"][1]["sem_custo"], 500.0)
        with self.assertRaises(NaoEncontrada):
            self.crm.cliente(None, 10)                                       # fora do CRM
        with self.assertRaises(ValueError):
            self.crm.cliente(None, "x")

    def test_rentabilidade_para_o_credito(self):
        r = self.crm.rentabilidade([5])
        self.assertEqual((r["desde"], r["ate"]), ("2026-01", "2026-09"))
        self.assertEqual(r["cortes"], [0.0, 0.0, 50.0, 250.0])
        c = r["clientes"][0]
        # as mesmas contas do CRM: 1.600 de lucro, 500 sem custo fora do lucro e da margem
        self.assertEqual((c["faturamento"], c["sem_custo"], c["lucro"]), (6100.0, 500.0, 1600.0))
        self.assertEqual(c["lucro"], self.c[5]["rentabilidade"]["lucro"])
        self.assertEqual(c["margem"], self.c[5]["rentabilidade"]["margem"])
        self.assertAlmostEqual(c["margem"], 100 * 1600 / 5600, places=2)
        self.assertEqual(c["crm"], {"quintil": 1, "pontos": 40})
        self.assertIsNone(c["fora"])
        self.assertEqual([m["mes"] for m in r["meses"]], [f"2026-{m:02d}" for m in range(1, 10)])  # os 9, com zero
        self.assertEqual(r["meses"][7], {"mes": "2026-08", "faturamento": 6100.0, "sem_custo": 500.0, "lucro": 1600.0,
                                         "margem": c["margem"]})
        self.assertEqual(r["meses"][0]["faturamento"], 0.0)
        self.assertIsNone(r["meses"][0]["margem"])
        self.assertEqual([p["nome"] for p in r["produtos"]], ["QUEIJO MUSSARELA MAIS VIDA 4KG", "PRODUTO SEM CUSTO"])
        self.assertEqual((r["produtos"][1]["sem_custo"], r["produtos"][1]["volume"]), (500.0, 5.0))

    def test_rentabilidade_de_quem_esta_fora_do_crm(self):
        r = self.crm.rentabilidade(["13", 10, 9, 14, 13])  # repetido conta uma vez
        c = {x["id"]: x for x in r["clientes"]}
        self.assertEqual(list(c), [13, 10, 9, 14])
        self.assertEqual((c[13]["lucro"], c[13]["sem_custo"], c[13]["faturamento"]), (100.0, 90.0, 390.0))
        self.assertIsNone(c[13]["crm"])
        self.assertEqual(c[13]["fora"], "o CRM tem só os clientes ativos da carteira das equipes ES e BA")
        self.assertEqual(c[14]["fora"], "o CRM tem só os clientes ativos da carteira das equipes ES e BA")  # inativo
        self.assertEqual(c[10]["fora"], "nunca fez pedido de venda")
        self.assertEqual(c[9]["fora"], "a primeira compra foi há menos de 1 mês")
        self.assertEqual((c[10]["faturamento"], c[10]["lucro"], c[10]["margem"]), (0.0, 0.0, None))
        self.assertEqual(r["produtos"][-1]["nome"], "BEB. LACTEA MORANGO 500G BANDEJA")  # o 3643 pelo 11469

    def test_rentabilidade_de_varios_clientes_soma(self):
        r = self.crm.rentabilidade([1, 3, 5])
        self.assertEqual(r["total"]["lucro"], 1000.0 + 250.0 + 1600.0)                   # a venda de outubro fica fora
        self.assertEqual(r["total"]["faturamento"], 3000.0 + 1250.0 + 6100.0)
        self.assertAlmostEqual(r["total"]["margem"], 100 * 2850 / 9850, places=2)
        self.assertEqual([x["crm"]["quintil"] for x in r["clientes"]], [1, 2, 1])
        self.assertEqual(r["produtos"][0], {"nome": "QUEIJO MUSSARELA MAIS VIDA 4KG", "volume": 350.0,
                                            "faturamento": 9850.0, "sem_custo": 0.0, "lucro": 2850.0,
                                            "margem": round(100 * 2850 / 9850, 2)})
        with self.assertRaises(ValueError):
            self.crm.rentabilidade([])
        with self.assertRaises(ValueError):
            self.crm.rentabilidade(["x"])
        with self.assertRaises(ValueError):
            self.crm.rentabilidade(list(range(1, 102)))

    def test_rentabilidade_sem_custo_ou_sem_crm(self):
        cfg = regras_teste()
        cfg["rentabilidade"]["custos"], cfg["rentabilidade"]["usa_custo_de"] = {}, {}
        sem_custo = Crm(self.crm.calc, ConfigFixa(cfg), self.crm.nomes_vendedores)
        r = sem_custo.rentabilidade([5])
        self.assertIn("custo industrial", r["indisponivel"])
        self.assertNotIn("clientes", r)
        # o CRM não fecha (ex.: os pedidos ainda não chegaram): o lucro aparece, sem a faixa
        quebrado = Crm(self.crm.calc, self.crm.config, self.crm.nomes_vendedores)

        def falha():
            raise RuntimeError("os pedidos de venda ainda não chegaram")

        quebrado._dados = falha
        r = quebrado.rentabilidade([5])
        self.assertEqual(r["clientes"][0]["lucro"], 1600.0)
        self.assertEqual((r["clientes"][0]["crm"], r["clientes"][0]["fora"], r["cortes"]), (None, None, []))
        self.assertIn("os pedidos de venda ainda não chegaram", r["avisos"][0])

    def test_excel(self):
        conteudo, nome = self.crm.excel(frozenset({ES}))
        self.assertTrue(conteudo.startswith(b"PK"))
        self.assertTrue(nome.startswith("CRM - nota dos clientes - ") and nome.endswith(".xlsx"))

    def test_guarda_o_calculo(self):
        self.assertIs(self.crm._dados(), self.crm._dados())

    def test_uma_conta_so_para_quem_chega_junto(self):
        # quatro pedidos ao mesmo tempo, sem nada guardado: o primeiro calcula, os outros esperam e usam o resultado
        crm = Crm(self.crm.calc, self.crm.config, self.crm.nomes_vendedores)
        contas, calcular = [], crm._calcular

        def devagar(cfg):
            contas.append(1)
            time.sleep(0.2)
            return calcular(cfg)

        crm._calcular = devagar
        saidas, erros = [], []

        def pedir():
            try:
                saidas.append(crm._dados())
            except Exception as e:  # noqa: BLE001
                erros.append(e)

        pedidos_juntos = [threading.Thread(target=pedir) for _ in range(4)]
        for t in pedidos_juntos:
            t.start()
        for t in pedidos_juntos:
            t.join(30)
        self.assertEqual(erros, [])
        self.assertEqual(len(contas), 1)
        self.assertEqual(len(saidas), 4)
        self.assertTrue(all(s is saidas[0] for s in saidas))
        self.assertEqual(sorted(saidas[0]["clientes"]), sorted(self.c))

    def test_a_conta_que_falha_nao_trava_a_seguinte(self):
        crm = Crm(self.crm.calc, self.crm.config, self.crm.nomes_vendedores)
        calcular = crm._calcular

        def quebra(cfg):
            raise RuntimeError("falhou")

        crm._calcular = quebra
        with self.assertRaises(RuntimeError):
            crm._dados()
        crm._calcular = calcular
        self.assertEqual(sorted(crm._dados()["clientes"]), sorted(self.c))


class TestPlanilhaCustos(unittest.TestCase):
    def planilha(self) -> bytes:
        import xlsxwriter
        saida = io.BytesIO()
        wb = xlsxwriter.Workbook(saida)
        ws = wb.add_worksheet()
        data = wb.add_format({"num_format": "mmm-yy"})
        ws.write(1, 2, "CUSTO INDUSTRIAL")
        ws.write(2, 0, "MARGEM MINIMA")
        ws.write(2, 1, "Produto")
        for j, m in enumerate((1, 2, 3)):
            ws.write_datetime(2, 2 + j, dt.datetime(2026, m, 1), data)
        ws.write(3, 0, 0.3)
        ws.write(3, 1, "MANTEIGA  200G")
        ws.write_row(3, 2, [3.5, 0, 4.76])
        ws.write(4, 1, "QUEIJO PARMESÃO PEÇA N 5KG")
        ws.write_row(4, 2, [33.8, 32.9, 32.1])
        wb.close()
        return saida.getvalue()

    def test_le_a_planilha(self):
        lida = ler_planilha_custos(self.planilha())
        self.assertEqual(lida["meses"], ["2026-01", "2026-02", "2026-03"])
        self.assertEqual(lida["linhas"][0], {"produto": "MANTEIGA 200G", "custos": {"2026-01": 3.5, "2026-03": 4.76}})
        self.assertEqual(lida["linhas"][1]["produto"], "QUEIJO PARMESÃO PEÇA N 5KG")

    def test_liga_pelo_nome(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cache = criar_cache(Path(tmp.name))
        self.addCleanup(lambda: cache._con.close())
        crm = Crm(SimpleNamespace(cache=cache, regras=lambda: Regras(padrao(), {})), ConfigFixa(PADRAO), dict)
        lida = crm.importar_custos(self.planilha())
        self.assertEqual([x["id"] for x in lida["linhas"]], [25, None])     # o "N 5KG" a pessoa escolhe na tela

    def test_recusa_o_que_nao_e_planilha(self):
        for conteudo, trecho in ((b"", "vazia"), (b"nao sou zip", ".xlsx")):
            with self.subTest(trecho):
                with self.assertRaises(ValueError) as e:
                    ler_planilha_custos(conteudo)
                self.assertIn(trecho, str(e.exception))


class TestMigracao045(BaseBanco):
    """bi/migracoes/045_crm.sql: a tabela regras aceita as do CRM (versões novas, lidas de volta do banco) e continua
    recusando um nome desconhecido."""

    def test_regras_do_crm_no_banco(self):
        import psycopg  # só aqui: sem o psycopg, a classe inteira é pulada
        self.assertEqual(ConfigCrm(self.banco).atual()["equipes"], ["ES", "BA"])  # sem versão gravada: o padrão
        cfg = copy.deepcopy(PADRAO)
        cfg["aderencia"]["prazo_quinzenal"] = 14
        ConfigCrm(self.banco).salvar(cfg)
        lido = ConfigCrm(self.banco).atual()                                      # outra instância: vem do banco
        self.assertEqual(lido["aderencia"]["prazo_quinzenal"], 14)
        self.assertEqual(lido["rentabilidade"]["usa_custo_de"], {"5754": 27, "12175": 12552, "12189": 12552})
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.banco.conexao() as con:
                con.execute("INSERT INTO regras (nome, dados) VALUES ('nao_existe', '{}'::jsonb)")


if __name__ == "__main__":
    unittest.main()

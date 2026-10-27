"""Página Sugestão de Metas (bi/sugestao.py): a conta das páginas de sugestão do Power BI, os faturamentos das áreas, as
regras da página, o acesso e a ferramenta do Assistente.

O cache sintético reproduz o exemplo do plano: Jamille (98, BA), área PS - ORLA (170, atendida na quarta e faturada na
quinta), Bebida Láctea 900G (2105), mês base set/26 e meta de out/26 -> 5.974 de volume e R$ 21.414,66.
"""
from __future__ import annotations

import configparser
import datetime as dt
import tempfile
import unittest
from pathlib import Path

import duckdb

from bi.assistente import FERRAMENTAS, Ferramentas
from bi.cache import (TABELAS, TABELAS_CARTEIRA, TABELAS_CREDITO, TABELAS_DETALHE, TABELAS_PARCELAS, TABELAS_PEDIDOS,
                      TABELAS_REDE, Cache)
from bi.calendario import Calendario
from bi.configuracao import padrao as padrao_metas
from bi.metas import Calculadora
from bi.sugestao import (Sugestao, _valida, crescimento_proposto, faturamentos_do_mes, ler_mes, padrao,
                         sazonalidade, texto_mes)
from tests.apoio import BaseBanco, ConfiguracaoFixa, PlanilhaFalsa, criar_assistente

D = dt.date
JAMILLE, EDIR, RUBENS = 98, 85, 124
ORLA, SEM_DIA, ROTA_ES = 170, 999, 1
BEBIDA, MUSSARELA = 2105, 32


class ConfigFixa:
    """As regras da página em memória (sem o banco)."""

    def __init__(self, **mudar):
        self.cfg = _valida({**padrao(), **mudar})

    def atual(self) -> dict:
        return dict(self.cfg)


def criar_cache(pasta: Path) -> Calculadora:
    con = duckdb.connect(str(pasta / "cache.duckdb"))
    for nome, colunas in {**TABELAS, **TABELAS_DETALHE, **TABELAS_PEDIDOS, **TABELAS_REDE, **TABELAS_CREDITO,
                          **TABELAS_PARCELAS, **TABELAS_CARTEIRA}.items():
        con.execute(f"CREATE TABLE {nome} ({colunas})")
    # (data, vendedor da venda, cliente, tipo, produto, valor, quantidade)
    vendas = [
        # Jamille, cliente 1 na PS - ORLA: o exemplo do plano
        (D(2026, 9, 10), JAMILLE, 1, "CLIENTE", BEBIDA, 15862.0, 4425.0),
        (D(2026, 3, 5), JAMILLE, 1, "CLIENTE", BEBIDA, 120000.0, 34715.0),   # jan–ago/26: 39.080 com setembro
        (D(2025, 9, 10), JAMILLE, 1, "CLIENTE", BEBIDA, 17000.0, 5398.0),
        (D(2025, 10, 10), JAMILLE, 1, "CLIENTE", BEBIDA, 20000.0, 6268.0),
        (D(2025, 4, 5), JAMILLE, 1, "CLIENTE", BEBIDA, 110000.0, 36117.0),   # jan–ago/25: 41.515 com setembro
        # vendido por outro vendedor, mas o cliente é da Jamille hoje: conta para ela (carteira)
        (D(2026, 9, 12), 111, 1, "CLIENTE", MUSSARELA, 3900.0, 100.0),
        # cliente 2 da Jamille numa área sem dia de atendimento: fica fora, com aviso
        (D(2026, 9, 11), JAMILLE, 2, "CLIENTE", BEBIDA, 700.0, 200.0),
        # Edir, cliente 4 na mesma área
        (D(2026, 9, 3), EDIR, 4, "CLIENTE", BEBIDA, 1000.0, 300.0),
        # funcionário: código de outro cadastro, fica fora
        (D(2026, 9, 3), JAMILLE, 1, "FUNCIONARIO", BEBIDA, 50.0, 20.0),
        # Rubens (ES), cliente 3
        (D(2026, 9, 2), RUBENS, 3, "CLIENTE", MUSSARELA, 4200.0, 105.0),
        (D(2025, 9, 2), RUBENS, 3, "CLIENTE", MUSSARELA, 4000.0, 110.0),
        (D(2025, 10, 2), RUBENS, 3, "CLIENTE", MUSSARELA, 4600.0, 115.0),
        (D(2026, 2, 2), RUBENS, 3, "CLIENTE", MUSSARELA, 40000.0, 1000.0),
        (D(2025, 2, 2), RUBENS, 3, "CLIENTE", MUSSARELA, 30000.0, 900.0),
    ]
    con.executemany("INSERT INTO vendas_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?)", vendas)
    con.execute("INSERT INTO vendas_itens SELECT data, id_vendedor, id_produto, SUM(valor), SUM(quantidade) "
                "FROM vendas_clientes_itens GROUP BY ALL")
    con.execute("INSERT INTO vendas_clientes SELECT data, id_vendedor, id_cliente, tipocliente, 1 "
                "FROM vendas_clientes_itens GROUP BY ALL")
    con.execute("INSERT INTO vendas_clientes_mes SELECT date_trunc('month', data), id_cliente, tipocliente, id_produto, "
                "SUM(valor) FROM vendas_clientes_itens GROUP BY ALL")
    # (data de entrada, vendedor, cliente, tipo, produto, motivo, cancelada, valor, quantidade)
    con.executemany("INSERT INTO devolucoes_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (D(2026, 9, 15), JAMILLE, 1, "CLIENTE", BEBIDA, 1, False, 215.0, 60.0),   # desconta: 4425 − 60 = 4365
        (D(2026, 9, 16), JAMILLE, 1, "CLIENTE", BEBIDA, 1, True, 300.0, 100.0),   # cancelada: não desconta
        (D(2026, 9, 17), JAMILLE, 1, "CLIENTE", BEBIDA, 3, False, 30.0, 10.0),    # motivo 3: não desconta
    ])
    con.execute("INSERT INTO devolucoes_itens SELECT data, id_vendedor, id_produto, id_motivo, cancelada, SUM(valor), "
                "SUM(quantidade) FROM devolucoes_clientes_itens GROUP BY ALL")
    con.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?)", [
        (BEBIDA, "BEBIDA LACTEA MORANGO 900G", 3, "BEBIDAS", "UN", 0),
        (MUSSARELA, "QUEIJO MUSSARELA 4KG", 1, "MUSSARELA", "KG", 0)])
    con.executemany("INSERT INTO vendedores VALUES (?, ?, ?, ?, ?)", [
        (JAMILLE, "JAMILLE - PS", 7, "MARCOS", 0), (EDIR, "EDIR - PS", 8, "TERC", 0),
        (RUBENS, "RUBENS - ES", 3, "VALDIRENE", 0), (111, "EWERTON - PS", 7, "MARCOS", 0)])
    con.executemany("INSERT INTO clientes VALUES (?, ?, ?)", [
        (1, "MERCADO DA ORLA", JAMILLE), (2, "BAR DO CENTRO", JAMILLE), (3, "ACOUGUE SAO JOSE", RUBENS),
        (4, "MERCEARIA DO EDIR", EDIR)])
    con.executemany("INSERT INTO clientes_detalhes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, "ORLA LTDA", "PORTO SEGURO", "BA", ORLA, "PS - ORLA (QUARTA)", 1, "MERCADO", 0, D(2020, 1, 1)),
        (2, "CENTRO LTDA", "PORTO SEGURO", "BA", SEM_DIA, "CENTRAL DE COMPRAS", 1, "BAR", 0, D(2020, 1, 1)),
        (3, "SAO JOSE", "SERRA", "ES", ROTA_ES, "ROTA 1", 2, "AÇOUGUE", 0, D(2020, 1, 1)),
        (4, "EDIR LTDA", "PORTO SEGURO", "BA", ORLA, "PS - ORLA (QUARTA)", 1, "MERCADO", 0, D(2020, 1, 1))])
    con.executemany("INSERT INTO motivos VALUES (?, ?)", [(1, "ERRO DE LANÇAMENTO"), (3, "VENCIDO")])
    con.executemany("INSERT INTO info VALUES (?, ?)", [
        ("data_ref", "2026-10-26"), ("extraido_em", "2026-10-27T08:00:00"), ("banco_mtime", "0"),
        ("banco_copia", "2026-10-27T07:00"), ("inicio", "2024-01-01")])
    con.close()
    ini = configparser.ConfigParser()
    ini.read_dict({"cache": {"arquivo": "cache.duckdb", "inicio": "2024-01-01"},
                   "banco": {"arquivo": str(pasta / "nao-existe.gdb")}})
    meta = lambda mes, v, valor: {"mes": mes, "id_vendedor": v, "vendedor": str(v), "meta_fat": valor,  # noqa: E731
                                  "meta_mus": 0.0, "meta_out": 0.0, "meta_cli": 10.0}
    # quem tem meta na planilha no mês da meta ou nos dois anteriores entra; o 111 (Ewerton) não tem clientes
    metas = PlanilhaFalsa([meta(D(2026, 10, 1), JAMILLE, 25000.0), meta(D(2026, 9, 1), JAMILLE, 20000.0),
                           meta(D(2026, 8, 1), EDIR, 1000.0), meta(D(2026, 9, 1), RUBENS, 3000.0),
                           meta(D(2026, 9, 1), 111, 9000.0), meta(D(2025, 9, 1), JAMILLE, 1.0)])
    return Calculadora(Cache(ini, pasta), metas, PlanilhaFalsa([]), ConfiguracaoFixa(padrao_metas()))


class TestFuncoes(unittest.TestCase):
    def test_exemplo_do_plano(self):
        bruta, saz = sazonalidade(5398, 6268, 4, 5, 0.2)
        self.assertAlmostEqual(saz, (6268 / 5) / (5398 / 4))
        self.assertAlmostEqual(saz, 0.92894, places=4)  # queda no ano passado fica (reduz a meta)
        razao, cre = crescimento_proposto(39080, 41515, 0.12, 0.2)
        self.assertAlmostEqual(razao, 39080 / 41515)
        self.assertAlmostEqual(cre, 2.12 - 39080 / 41515)
        self.assertAlmostEqual(4365 / 4 * saz * 5 * cre, 5974.03, places=1)

    def test_tetos_e_bordas(self):
        self.assertEqual(sazonalidade(100, 200, 4, 4, 0.2)[1], 1.2)        # +100%: teto
        self.assertEqual(sazonalidade(0, 200, 4, 4, 0.2), (None, 1.0))     # sem venda no mês base do ano passado
        self.assertEqual(sazonalidade(100, 0, 4, 4, 0.2), (0.0, 1.0))      # sem venda no mês da meta: sem ajuste
        self.assertEqual(sazonalidade(100, 50, None, 4, 0.2), (None, 1.0))  # sem faturamentos
        self.assertEqual(crescimento_proposto(100, 0, 0.12, 0.2), (None, 1.0))  # produto novo: 0%
        self.assertEqual(crescimento_proposto(130, 100, 0.12, 0.2)[1], 1.0)    # já cresceu 30%: 0%
        self.assertEqual(crescimento_proposto(70, 100, 0.12, 0.2)[1], 1.2)     # caiu 30%: teto
        self.assertAlmostEqual(crescimento_proposto(105, 100, 0.12, 0.2)[1], 1.07)

    def test_faturamentos_do_mes(self):
        cal = Calendario()
        quarta = [3]
        self.assertEqual([faturamentos_do_mes(cal, quarta, a, m) for a, m in ((2026, 9), (2026, 10), (2025, 9), (2025, 10))],
                         [4, 5, 4, 5])  # quintas: a planilha do Power BI tinha os mesmos números
        # sexta: fatura na segunda; 12/10/2026 é feriado (fatura no dia 13) e o de 30/10 cai em 03/11 (Finados no dia 2),
        # que soma com os de 09, 16, 23 e 30/11 (o atendimento de 20/11, feriado, conta)
        self.assertEqual(faturamentos_do_mes(cal, [5], 2026, 10), 4)
        self.assertEqual(faturamentos_do_mes(cal, [5], 2026, 11), 5)
        # segunda: o atendimento de 07/09/2026 (feriado) conta, faturado na terça
        self.assertEqual(faturamentos_do_mes(cal, [1], 2026, 9), 5)
        # dois dias de atendimento: o dobro (só a razão entre os meses importa)
        self.assertEqual(faturamentos_do_mes(cal, [1, 2], 2026, 10), 8)
        # Eunápolis: atendida na segunda e faturada na quarta (2 dias úteis), como nas vendas: set/25 tem 4 quartas e
        # out/25, 5; set/26 tem 5 (o atendimento de 07/09 é faturado no dia 9) e out/26, 4 (o de 12/10 vai para o dia 14)
        self.assertEqual([faturamentos_do_mes(cal, [1], a, m, prazo=2) for a, m in ((2025, 9), (2025, 10), (2026, 9), (2026, 10))],
                         [4, 5, 5, 4])
        self.assertEqual([faturamentos_do_mes(cal, [1], a, m) for a, m in ((2025, 9), (2025, 10))], [5, 4])  # com 1 dia

    def test_meses(self):
        self.assertEqual(texto_mes(ler_mes("2026-11")), "2026-11")
        for ruim in ("2026-13", "11/2026", ""):
            with self.assertRaises(ValueError):
                ler_mes(ruim)


class TestRegras(unittest.TestCase):
    def test_padrao_do_power_bi(self):
        cfg = _valida({})
        self.assertEqual(cfg["crescimento"], {"ES": 0.12, "BA": 0.12})
        self.assertEqual((cfg["teto_sazonalidade"], cfg["teto_crescimento"]), (0.2, 0.2))
        self.assertEqual(_valida(padrao())["fixos"]["291"], 2)

    def test_prazos(self):
        self.assertEqual(_valida(padrao())["prazos"], {"207": 2, "209": 2})
        self.assertEqual(_valida({**padrao(), "prazos": {"170": 1, "24": "3"}})["prazos"], {"24": 3})  # 1 é o padrão
        for ruim in (0, 6, 1.5, "x"):
            with self.assertRaises(ValueError) as e:
                _valida({**padrao(), "prazos": {"170": ruim}})
            self.assertIn("prazo do faturamento da área 170", str(e.exception))

    def test_normaliza(self):
        cfg = _valida({**padrao(), "ajustes": {"2026-09": {"166": "4", 24: 5}, "2026-10": {}}})
        self.assertEqual(cfg["ajustes"], {"2026-09": {"24": 5, "166": 4}})

    def test_recusa(self):
        for ruim, texto in (({"crescimento": {"ES": 1.5}}, "crescimento desejado do ES"),
                            ({"teto_sazonalidade": "x"}, "teto da sazonalidade"),
                            ({"fixos": {"45": 0}}, "faturamentos fixos da área 45"),
                            ({"ajustes": {"2026-09": {"166": 2.5}}}, "faturamentos da área 166"),
                            ({"ajustes": {"setembro": {"166": 2}}}, "mês inválido"),
                            ({"fixos": {"abc": 2}}, "código de área")):
            with self.assertRaises(ValueError) as e:
                _valida({**padrao(), **ruim})
            self.assertIn(texto, str(e.exception))


class TestSugestao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calc = criar_cache(Path(self.tmp.name))
        self.areas = {ORLA: [3]}
        self.cfg = ConfigFixa()
        self.sug = Sugestao(self.calc, self.cfg, lambda: dict(self.areas),
                            lambda: {JAMILLE: "Jamille", EDIR: "Edir", RUBENS: "Rubens"})

    def tearDown(self):
        self.calc.cache._con.close()
        self.tmp.cleanup()

    def linha(self, r, produto=BEBIDA):
        return next(p for p in r["produtos"] if p["id"] == produto)

    def test_exemplo_do_plano(self):
        r = self.sug.calcular("BA", "2026-10", JAMILLE)
        p = self.linha(r)
        self.assertAlmostEqual(p["volume_base"], 4365)  # sem a devolução cancelada e a do motivo 3
        self.assertEqual(p["faturamentos"], {"base": 4, "meta": 5})
        self.assertAlmostEqual(p["sazonalidade"], 0.92894 - 1, places=4)
        self.assertAlmostEqual(p["acumulado"], 39080 / 41515 - 1)
        self.assertAlmostEqual(p["crescimento"], 1.12 - 39080 / 41515)
        self.assertAlmostEqual(p["meta_volume"], 5974.03, places=1)
        self.assertAlmostEqual(p["preco"], 15862 / 4425)                  # bruto ÷ vendido
        self.assertAlmostEqual(p["meta_rs"], 21414.66, places=1)
        self.assertEqual(r["mes"]["base"], "2026-09")
        self.assertTrue(r["mes"]["base_fechado"])

    def test_carteira_e_quem_fica_fora(self):
        r = self.sug.calcular("BA", "2026-10", JAMILLE)
        # a mussarela vendida pelo Ewerton ao cliente da Jamille conta para ela
        self.assertIn(MUSSARELA, {p["id"] for p in r["produtos"]})
        # a área sem dia fica fora, com aviso
        self.assertEqual(r["fora"]["areas"][0]["id"], SEM_DIA)
        self.assertEqual(r["fora"]["clientes"], 1)
        self.assertTrue(any("CENTRAL DE COMPRAS" in a for a in r["avisos"]))
        # o funcionário (código de outro cadastro) não entra: 4365 continua sendo o volume
        self.assertAlmostEqual(self.linha(r)["volume_base"], 4365)

    def test_todos_e_a_soma_dos_vendedores(self):
        todos = self.sug.calcular("BA", "2026-10")
        um = [self.sug.calcular("BA", "2026-10", v)["cartoes"]["meta_rs"] for v in (JAMILLE, EDIR)]
        self.assertAlmostEqual(todos["cartoes"]["meta_rs"], sum(um))
        self.assertEqual([v["id"] for v in todos["opcoes"]["vendedores"]], [EDIR, JAMILLE])
        resumo = {v["id"]: v for v in todos["resumo"]}
        self.assertAlmostEqual(resumo[JAMILLE]["meta_rs"], um[0])
        self.assertEqual(resumo[JAMILLE]["meta_lancada"], 25000.0)
        self.assertAlmostEqual(resumo[JAMILLE]["diferenca"], 25000.0 - um[0])
        self.assertIsNone(resumo[EDIR]["meta_lancada"])

    def test_por_area(self):
        r = self.sug.calcular("BA", "2026-10")
        orla = next(a for a in r["areas"] if a["id"] == ORLA)
        self.assertEqual(orla["faturamentos"], {"base": 4, "meta": 5})
        self.assertEqual(orla["origem"], {"2026-09": "automatico", "2026-10": "automatico"})
        self.assertAlmostEqual(sum(p["meta_rs"] for p in orla["produtos"]), orla["meta_rs"])
        so_area = self.sug.calcular("BA", "2026-10", JAMILLE, ORLA)
        self.assertIsNone(so_area["fora"])  # com o filtro da área, a sem dia nem entra

    def test_ajuste_e_numero_fixo(self):
        base = self.linha(self.sug.calcular("BA", "2026-10", JAMILLE))["meta_volume"]
        self.cfg.cfg = _valida({**padrao(), "ajustes": {"2026-09": {str(ORLA): 5}}})
        r = self.sug.calcular("BA", "2026-10", JAMILLE)
        self.assertAlmostEqual(self.linha(r)["meta_volume"], base * 4 / 5)
        self.assertEqual(next(a for a in r["areas"] if a["id"] == ORLA)["origem"]["2026-09"], "ajuste")
        # número fixo (quinzenal): 2 em todo mês, também no ano passado
        self.cfg.cfg = _valida({**padrao(), "fixos": {str(ORLA): 2}})
        p = self.linha(self.sug.calcular("BA", "2026-10", JAMILLE))
        self.assertEqual(p["faturamentos"], {"base": 2, "meta": 2})
        self.assertAlmostEqual(p["sazonalidade"], 6268 / 5398 - 1)
        # prazo de 2 dias úteis: quinta -> sexta; set/26 4 -> out/26 5 continua (as quintas e sextas caem iguais)
        self.cfg.cfg = _valida({**padrao(), "prazos": {str(ORLA): 2}})
        self.assertEqual(self.linha(self.sug.calcular("BA", "2026-10", JAMILLE))["faturamentos"], {"base": 4, "meta": 5})
        self.cfg.cfg = _valida({**padrao(), "prazos": {str(ORLA): 3}})  # segunda: set/26 4, out/26 4
        self.assertEqual(self.linha(self.sug.calcular("BA", "2026-10", JAMILLE))["faturamentos"], {"base": 4, "meta": 4})
        # a área que passa a ter número fixo entra, mesmo sem dia
        self.cfg.cfg = _valida({**padrao(), "fixos": {str(SEM_DIA): 2}})
        self.assertIsNone(self.sug.calcular("BA", "2026-10", JAMILLE)["fora"])

    def test_regras_da_pagina(self):
        self.cfg.cfg = _valida({**padrao(), "crescimento": {"ES": 0.12, "BA": 0.30}, "teto_crescimento": 0.5})
        p = self.linha(self.sug.calcular("BA", "2026-10", JAMILLE))
        self.assertAlmostEqual(p["crescimento"], 0.30 - (39080 / 41515 - 1))

    def test_es_por_produto_com_dias_uteis(self):
        r = self.sug.calcular("ES", "2026-10")
        self.assertEqual(r["dias"], {"base": 21, "meta": 21})
        p = self.linha(r, MUSSARELA)
        self.assertEqual(p["faturamentos"], {"base": 21, "meta": 21})
        self.assertAlmostEqual(p["sazonalidade"], (115 / 23) / (110 / 22) - 1)
        self.assertEqual(r["areas"], [])
        self.assertIsNone(r["fora"])

    def test_acesso(self):
        self.assertEqual(self.sug.calcular()["estados"], ["ES", "BA"])
        r = self.sug.calcular(None, None, None, None, None, {"ES"})
        self.assertEqual((r["estado"], r["estados"]), ("ES", ["ES"]))
        with self.assertRaises(PermissionError):
            self.sug.calcular("BA", None, None, None, None, {"ES"})
        r = self.sug.calcular("BA", "2026-10", None, None, {JAMILLE}, {"BA", "EDIR"})
        self.assertEqual([v["id"] for v in r["resumo"]], [JAMILLE])  # o resumo também respeita o acesso
        with self.assertRaises(PermissionError):
            self.sug.calcular(None, None, None, None, {12345}, None)
        with self.assertRaises(ValueError):
            self.sug.calcular("BA", "2026-10", RUBENS)  # do ES

    def test_vendedores_com_meta_na_planilha(self):
        # o Edir tem meta só em ago/26: entra na meta de out/26 (dois meses antes), não na de nov/26
        self.assertIn(EDIR, [v["id"] for v in self.sug.calcular("BA", "2026-10")["opcoes"]["vendedores"]])
        self.assertNotIn(EDIR, [v["id"] for v in self.sug.calcular("BA", "2026-11")["opcoes"]["vendedores"]])
        # meta de jan/26: ninguém tinha meta em nov/25 a jan/26 na planilha de teste
        with self.assertRaises(PermissionError):
            self.sug.calcular("BA", "2026-01")

    def test_meses_possiveis_e_mes_aberto(self):
        self.assertEqual(self.sug.calcular("BA")["mes"]["meta"], "2026-10")  # padrão: o mês dos dados
        with self.assertRaises(ValueError):
            self.sug.calcular("BA", "2026-12")  # depois do mês seguinte ao dos dados
        with self.assertRaises(ValueError):
            self.sug.calcular("BA", "2025-01")  # o mês base do ano anterior não está no cache
        r = self.sug.calcular("BA", "2026-11", JAMILLE)
        self.assertFalse(r["mes"]["base_fechado"])
        self.assertTrue(any("ainda não fechou" in a for a in r["avisos"]))

    def test_grafico(self):
        g = self.sug.calcular("BA", "2026-10", JAMILLE)["grafico"]
        self.assertEqual((g["ano"], g["base"], g["meta"]), (2026, 8, 9))
        total, bebida = g["total"], g["produtos"][str(BEBIDA)]
        # o gráfico mostra a carteira inteira, como no Power BI: com a área sem dia (200), que fica fora só da meta
        self.assertAlmostEqual(bebida["atual"][8], 4365 + 200)
        self.assertAlmostEqual(bebida["anterior"][9], 6268)
        self.assertIsNone(total["atual"][10])  # novembro ainda não chegou
        cal = Calendario()
        du = lambda m: sum(x["peso"] for x in cal.dias_do_mes(2025, m, "BA"))  # noqa: E731
        self.assertAlmostEqual(bebida["sazonalidade"][8], (6268 / du(10)) / (5398 / du(9)) - 1)

    def test_sem_venda_no_mes_base(self):
        r = self.sug.calcular("BA", "2026-09", JAMILLE)  # base ago/26: a Jamille não vendeu
        self.assertIsNone(r["cartoes"])
        self.assertEqual(r["produtos"], [])

    def test_assistente(self):
        r = self.sug.para_ia("BA", "2026-10")
        self.assertEqual({v["id"] for v in r["vendedores"]}, {JAMILLE, EDIR})
        self.assertNotIn("produtos", r)
        r = self.sug.para_ia("BA", "2026-10", JAMILLE)
        self.assertAlmostEqual(next(p for p in r["produtos"] if p["id"] == BEBIDA)["meta_rs"], 21414.66, places=1)
        self.assertEqual(r["vendedor"]["meta_lancada_na_planilha"], 25000.0)

    def test_ferramenta_do_assistente(self):
        self.assertTrue(next(t for t in FERRAMENTAS if t["name"] == "sugestao_metas")["strict"])
        assistente = criar_assistente(Path(self.tmp.name), self.calc)
        sem = Ferramentas(assistente.recorte(None), self.calc, assistente.cfg, None)
        _, passo = sem.executar("sugestao_metas", {"estado": "BA"})
        self.assertIn("não inclui a página Sugestão de Metas", passo["erro"])
        com = Ferramentas(assistente.recorte(None), self.calc, assistente.cfg, None, sugestao=(self.sug, None, {"ES"}))
        r, passo = com.executar("sugestao_metas", {"estado": "ES", "mes": "2026-10"})
        self.assertIsNone(passo["erro"])
        self.assertEqual(r["vendedores"][0]["id"], RUBENS)
        _, passo = com.executar("sugestao_metas", {"estado": "BA"})
        self.assertIn("não inclui vendedores do BA", passo["erro"])

    def test_configuracao(self):
        self.cfg.cfg = _valida({**padrao(), "ajustes": {"2026-09": {"777": 3}}})
        c = self.sug.config_dados("2026-10")
        self.assertEqual([m["valor"] for m in c["meses"]], ["2026-09", "2026-10", "2025-09", "2025-10"])
        orla = next(a for a in c["areas"] if a["id"] == ORLA)
        self.assertEqual(orla["automatico"]["1"], {"2026-09": 4, "2026-10": 5, "2025-09": 4, "2025-10": 5})
        self.assertEqual(orla["faturamento_observado"][0]["dia"], "qui")  # nas vendas de abr–out
        self.assertEqual(c["config"]["prazos"], {"207": 2, "209": 2})
        self.assertEqual(orla["dias"], [3])
        self.assertEqual(sorted(orla["vendedores"]), ["Edir", "Jamille"])
        sem_dia = next(a for a in c["areas"] if a["id"] == SEM_DIA)
        self.assertIsNone(sem_dia["dias"])
        self.assertEqual(set(sem_dia["automatico"]["1"].values()), {None})
        self.assertIn(777, {a["id"] for a in c["areas"]})  # área citada num ajuste aparece, mesmo sem clientes
        self.assertNotIn(ROTA_ES, {a["id"] for a in c["areas"]})  # só as áreas dos vendedores do BA


class TestConfigNoBanco(BaseBanco):
    def test_grava_versoes(self):
        from bi.sugestao import ConfigSugestao
        cfg = ConfigSugestao(self.banco)
        self.assertEqual(cfg.atual(), _valida(padrao()))
        uid = self.criar_usuario("admin2", "admin")
        cfg.salvar({**padrao(), "ajustes": {"2026-09": {"166": 4}}}, {"id": uid, "nome": "Admin2"})
        self.assertEqual(ConfigSugestao(self.banco).atual()["ajustes"], {"2026-09": {"166": 4}})
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT nome, salva_por_nome FROM regras").fetchall(), [("sugestao", "Admin2")])
        with self.assertRaises(ValueError):
            cfg.salvar({**padrao(), "teto_crescimento": 2})


if __name__ == "__main__":
    unittest.main()

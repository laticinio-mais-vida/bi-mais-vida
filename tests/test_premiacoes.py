"""Página Premiações (bi/premiacoes.py): as páginas "Premiacao Vendedores" e "Premiacao Supervisores" do Power BI.

Usa o cache sintético de tests/apoio.py (setembro/26; carteira: clientes 1 e 3 do ES, 2 e 7 do BA, 4 do Edir; hoje, para
a inadimplência, é 01/10/2026), mais os brindes de BRINDES e algumas vendas e títulos na janela de março a agosto.
"""
from __future__ import annotations

import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path

import duckdb

from bi.configuracao import Regras, padrao as padrao_metas
from bi.premiacoes import (ConfigPremiacoes, Premiacoes, _valida, clientes_para, faixa_vendedor, janela, padrao,
                           pontos_alcance, pontos_teto, proxima_faixa)
from bi.sugestao import ler_mes, texto_mes
from tests.apoio import BA, EDIR, ES, BaseBanco, criar_calc

D = dt.date
SET = D(2026, 9, 1)
FAIXAS = padrao()["vendedores"]["faixas"]
# (data, vendedor, cliente, tipo, produto, motivo, valor, quantidade)
BRINDES = [
    (D(2026, 9, 8), ES, 1, "CLIENTE", 27, 16, 30.0, 1.0),          # brinde vencido: impróprio
    (D(2026, 9, 9), ES, 3, "CLIENTE", 32, 26, 20.0, 1.0),          # degustação, mussarela (fora do mix)
    (D(2026, 9, 9), BA, 2, "FUNCIONARIO", 27, 16, 999.0, 1.0),     # código de outro cadastro: fica fora
    (D(2026, 8, 9), ES, 1, "CLIENTE", 27, 16, 70.0, 1.0),          # outro mês
]


class ConfigFixa:
    """As regras da página em memória (sem o banco)."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = _valida(cfg or padrao())

    def atual(self) -> dict:
        return copy.deepcopy(self.cfg)


class TestFuncoes(unittest.TestCase):
    def test_faixas(self):
        self.assertIsNone(faixa_vendedor(None, FAIXAS))
        self.assertIsNone(faixa_vendedor(0.9099, FAIXAS))
        self.assertEqual(faixa_vendedor(91 / 100, FAIXAS)["valor"], 200)
        self.assertEqual(faixa_vendedor(0.9599, FAIXAS)["valor"], 200)
        self.assertEqual(faixa_vendedor(24 / 25, FAIXAS)["valor"], 250)
        self.assertEqual(faixa_vendedor(1.0, FAIXAS)["valor"], 350)
        self.assertEqual(faixa_vendedor(1.3, FAIXAS)["valor"], 350)  # as faixas não se somam
        self.assertEqual(proxima_faixa(0.5, FAIXAS)["valor"], 200)
        self.assertEqual(proxima_faixa(0.96, FAIXAS)["valor"], 350)
        self.assertIsNone(proxima_faixa(1.0, FAIXAS))
        self.assertEqual(clientes_para(100, 0.91), 91)
        self.assertEqual(clientes_para(54, 0.96), 52)  # 51,84

    def test_pontos(self):
        self.assertEqual(pontos_alcance(None, 0.25, 0.8), 0)
        self.assertEqual(pontos_alcance(0.7999, 0.25, 0.8), 0)
        self.assertAlmostEqual(pontos_alcance(0.8, 0.25, 0.8), 0.2)
        self.assertAlmostEqual(pontos_alcance(0.9, 0.15, 0.85), 0.135)
        self.assertEqual(pontos_alcance(1.3, 0.25, 0.8), 0.25)  # no máximo o peso
        self.assertEqual(pontos_teto(0.015, 0.015, 0.25), 0.25)
        self.assertEqual(pontos_teto(0.0151, 0.015, 0.25), 0)
        self.assertEqual(pontos_teto(None, 0.015, 0.25), 0)

    def test_janela_da_inadimplencia(self):
        self.assertEqual([texto_mes(i) for i in janela(ler_mes("2026-10"))], ["2026-03", "2026-08"])
        self.assertEqual([texto_mes(i) for i in janela(ler_mes("2026-01"))], ["2025-06", "2025-11"])

    def test_grupo_conhecido(self):
        regras = Regras(padrao_metas(), {500: 7, 501: 8, 502: None})
        self.assertEqual(regras.grupo_conhecido(124), "ES")       # nas Configurações das metas
        self.assertEqual(regras.grupo_conhecido(500), "BA")       # pelo supervisor do ERP
        self.assertIsNone(regras.grupo_conhecido(501))            # terceiros
        self.assertIsNone(regras.grupo_conhecido(502))            # sem supervisor
        self.assertEqual(regras.grupo_vendedor(502), "ES")        # Metas continua mandando para o ES


class TestRegras(unittest.TestCase):
    def test_padrao_do_power_bi(self):
        cfg = _valida(padrao())
        s = cfg["supervisores"]
        self.assertEqual([(f["min"], f["valor"]) for f in cfg["vendedores"]["faixas"]], [(0.91, 200), (0.96, 250), (1.0, 350)])
        self.assertEqual((s["maximo"], s["nomes"], s["produtos_fora_mix"]), (5000, {"BA": "Marcos", "ES": "Ronaldo"},
                                                                          [32, 12551, 12552]))
        self.assertEqual(s["inadimplencia"], {"peso": 0.1, "meta": {"BA": 0.0042, "ES": 0.005}, "dias": 30})
        self.assertAlmostEqual(sum(s[k]["peso"] for k in ("receita", "mix", "inadimplencia", "positivacao", "devolucoes")), 1)

    def test_validacao(self):
        cfg = padrao()
        cfg["vendedores"]["faixas"] = [{"min": "1", "valor": "350"}, {"min": 0.9, "valor": 100}]
        cfg["supervisores"]["ajustes"] = {"2026-09": {"BA": {"fat": "2000000", "cli": ""}, "ES": {}}}
        cfg["supervisores"]["motivos_improprios"] = [16, "3", 3]
        v = _valida(cfg)
        self.assertEqual(v["vendedores"]["faixas"], [{"min": 0.9, "valor": 100}, {"min": 1.0, "valor": 350}])  # em ordem
        self.assertEqual(v["supervisores"]["ajustes"], {"2026-09": {"BA": {"fat": 2000000}}})
        self.assertEqual(v["supervisores"]["motivos_improprios"], [3, 16])
        erros = {
            "pesos": lambda c: c["supervisores"]["mix"].update(peso=0.2),
            "faixa repetida": lambda c: c["vendedores"].update(faixas=[{"min": 1, "valor": 1}, {"min": 1, "valor": 2}]),
            "sem faixa": lambda c: c["vendedores"].update(faixas=[]),
            "valor negativo": lambda c: c["vendedores"].update(faixas=[{"min": 1, "valor": -1}]),
            "nome vazio": lambda c: c["supervisores"]["nomes"].update(BA="  "),
            "meta acima de 100%": lambda c: c["supervisores"]["devolucoes"]["meta"].update(ES=2),
            "clientes quebrados": lambda c: c["supervisores"].update(ajustes={"2026-09": {"ES": {"cli": 10.5}}}),
            "mês inválido": lambda c: c["supervisores"].update(ajustes={"set/26": {"ES": {"cli": 10}}}),
        }
        for nome, mudar in erros.items():
            c = padrao()
            mudar(c)
            with self.subTest(nome), self.assertRaises(ValueError):
                _valida(c)


class TestPremiacoes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()

    def montar(self, cfg=None, brindes=True, **kw):
        # Edir com meta de 1 cliente; o 150 com meta 0 fica fora
        self.calc = criar_calc(self.pasta, metas_cli={(SET, EDIR): 1, (SET, 150): 0}, brindes=brindes,
                               linhas_brindes=BRINDES if brindes else (), **kw)
        self.config = ConfigFixa(cfg)
        self.p = Premiacoes(self.calc, self.config, lambda: {ES: "Rubens", BA: "Thais", EDIR: "Edir"})
        return self.p

    def acrescentar(self, *comandos):
        """Grava no cache já aberto (fecha, grava e reabre)."""
        cache = self.calc.cache
        cache._con.close()
        con = duckdb.connect(str(cache.arquivo))
        for sql, linhas in comandos:
            con.executemany(sql, linhas)
        con.close()
        cache._abrir()

    # --- vendedores --------------------------------------------------------------------------
    def test_vendedores(self):
        r = self.montar().calcular("vendedores")
        self.assertEqual((r["mes"]["valor"], r["situacao"], r["abas"]), ("2026-09", "final", ["vendedores", "supervisores"]))
        linhas = {v["id"]: v for v in r["vendedores"]}
        self.assertEqual(set(linhas), {ES, BA, EDIR})  # o 150 tem meta 0
        es, ba, edir = linhas[ES], linhas[BA], linhas[EDIR]
        # ES: clientes 1, 3 e o funcionário 7 (como em Metas, qualquer tipo de cliente conta) = 3 de 3
        self.assertEqual((es["meta"], es["atendidos"], es["pct"], es["premio"], es["proxima"]), (3, 3, 1.0, 350, None))
        self.assertEqual((ba["atendidos"], ba["pct"], ba["premio"], ba["faixa"]), (1, 0.5, 0, None))
        self.assertEqual(ba["proxima"], {"min": 0.91, "valor": 200, "faltam": 1})  # 91% de 2 = 1,82 -> 2 clientes
        self.assertEqual((edir["estado"], edir["equipe"], edir["premio"]), ("BA", "EDIR", 350))
        self.assertEqual(r["total"], {"meta": 6, "atendidos": 5, "pct": 5 / 6, "premio": 700, "vendedores": 3, "premiados": 2})

    def test_vendedores_do_acesso(self):
        p = self.montar()
        self.assertEqual([v["id"] for v in p.vendedores(permitidos={BA})["vendedores"]], [BA])
        r = p.calcular("vendedores", "2026-09", None, {"ES"})
        self.assertEqual([v["id"] for v in r["vendedores"]], [ES])
        self.assertEqual(r["abas"], ["vendedores", "supervisores"])
        self.assertEqual(p.calcular("vendedores", None, {BA}, {"BA"})["abas"], ["vendedores"])  # só alguns vendedores

    def test_meses(self):
        p = self.montar()
        self.assertEqual(p.meses(), [ler_mes("2026-09")])
        with self.assertRaises(ValueError):
            p.calcular("vendedores", "2026-08")
        with self.assertRaises(ValueError):
            p.calcular("gerentes")

    def test_faixas_editadas(self):
        cfg = padrao()
        cfg["vendedores"]["faixas"] = [{"min": 0.5, "valor": 80}]
        r = self.montar(cfg).vendedores()
        self.assertEqual({v["id"]: v["premio"] for v in r["vendedores"]}, {ES: 80, BA: 80, EDIR: 80})

    # --- supervisores ------------------------------------------------------------------------
    def test_supervisores(self):
        r = self.montar().calcular("supervisores", "2026-09")
        self.assertEqual((r["janela"]["rotulo"], r["corte_vencimento"], r["sem_brindes"]), ("fev/26 a jul/26", "2026-09-01", False))
        es, ba = (next(c for c in r["supervisores"] if c["estado"] == e) for e in ("ES", "BA"))
        ind = lambda c, k: next(x for x in c["indicadores"] if x["id"] == k)  # noqa: E731
        # ES: vendas 1.500 (1.000 de mussarela 32), devoluções 150 (o motivo 3 é impróprio: 50), brindes 50 (30
        # impróprios; 20 de mussarela). O funcionário 7 e a devolução cancelada ficam fora.
        self.assertEqual(es["contas"]["bruto"], 1500)
        self.assertEqual((es["contas"]["devolucoes"], es["contas"]["brindes"], es["contas"]["liquido"]), (150, 50, 1300))
        self.assertEqual((es["contas"]["liquido_mix"], es["contas"]["improprias"]), (420, 80))
        self.assertAlmostEqual(ind(es, "mix")["realizado"], 420 / 1300)
        self.assertAlmostEqual(ind(es, "devolucoes")["realizado"], 80 / 1500)
        self.assertEqual((ind(es, "receita")["meta"], ind(es, "positivacao")["meta"]), (2000, 3))
        self.assertEqual((ind(es, "receita")["alcance"], ind(es, "positivacao")["realizado"]), (0.65, 2))
        # sem faturamento nem títulos na janela: inadimplência zero, dentro da meta
        self.assertEqual((ind(es, "inadimplencia")["realizado"], ind(es, "inadimplencia")["dentro"]), (0.0, True))
        self.assertEqual({x["id"]: x["pontos"] for x in es["indicadores"]},
                         {"receita": 0, "mix": 0, "inadimplencia": 0.1, "positivacao": 0, "devolucoes": 0})
        self.assertEqual((es["pct"], es["premio"]), (0.1, 500))
        # BA: 5.400 de vendas, 250 de devolução (a cancelada fica fora), o brinde do funcionário fica fora
        self.assertEqual((ba["contas"]["liquido"], ba["contas"]["brindes"]), (5150, 0))
        self.assertAlmostEqual(ind(ba, "receita")["pontos"], 0.25 * 5150 / 6000)
        self.assertEqual((ind(ba, "positivacao")["realizado"], ind(ba, "positivacao")["pontos"]), (1, 0))
        self.assertEqual(ind(ba, "devolucoes")["pontos"], 0.25)
        self.assertAlmostEqual(ba["pct"], 0.25 * 5150 / 6000 + 0.1 + 0.25)
        self.assertEqual(ba["premio"], round(ba["pct"] * 5000, 2))
        self.assertEqual([v["id"] for v in ba["vendedores"]], [BA])  # o Edir (terceiros) fica fora

    def test_inadimplencia(self):
        p = self.montar()
        titulo = "INSERT INTO titulos_receber VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        self.acrescentar(
            ("INSERT INTO vendas_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?)",
             [(D(2026, 3, 10), ES, 1, "CLIENTE", 27, 10000.0, 10.0)]),
            (titulo, [
                (901, 1, ES, D(2026, 3, 10), D(2026, 4, 10), None, 0, 40.0),     # em aberto e vencido: conta
                (902, 1, ES, D(2026, 7, 25), D(2026, 9, 5), None, 0, 500.0),     # vence depois de 01/09: fora
                (903, 1, ES, D(2026, 8, 2), D(2026, 8, 10), None, 0, 500.0),     # emitido fora da janela
                (904, 1, ES, D(2026, 3, 1), D(2026, 3, 5), D(2026, 3, 20), 1, 800.0),  # pago
                (905, 2, BA, D(2026, 2, 1), D(2026, 9, 1), None, 0, 25.0),       # vence no dia do corte: conta
            ]))
        r = p.supervisores("2026-09")
        es, ba = (next(c for c in r["supervisores"] if c["estado"] == e) for e in ("ES", "BA"))
        inad = lambda c: next(x for x in c["indicadores"] if x["id"] == "inadimplencia")  # noqa: E731
        self.assertEqual((es["contas"]["inadimplente"], es["contas"]["liquido_6m"]), (40, 10000))
        self.assertEqual((inad(es)["realizado"], inad(es)["dentro"], inad(es)["pontos"]), (0.004, True, 0.1))
        # BA: inadimplente sem faturamento na janela, sem base
        self.assertEqual((ba["contas"]["inadimplente"], inad(ba)["realizado"], inad(ba)["pontos"]), (25, None, 0))
        cfg = padrao()
        cfg["supervisores"]["inadimplencia"]["meta"]["ES"] = 0.003
        self.config.cfg = _valida(cfg)
        es = next(c for c in p.supervisores("2026-09")["supervisores"] if c["estado"] == "ES")
        self.assertEqual((inad(es)["dentro"], inad(es)["pontos"]), (False, 0))

    def test_meta_ajustada(self):
        cfg = padrao()
        cfg["supervisores"]["ajustes"] = {"2026-09": {"BA": {"fat": 5150}}}
        r = self.montar(cfg).supervisores("2026-09")
        ba = next(c for c in r["supervisores"] if c["estado"] == "BA")
        receita = ba["indicadores"][0]
        self.assertEqual((receita["meta"], receita["meta_auto"], receita["ajustada"], receita["pontos"]), (5150, 6000, True, 0.25))
        positivacao = next(x for x in ba["indicadores"] if x["id"] == "positivacao")
        self.assertEqual((positivacao["meta"], positivacao["ajustada"]), (2, False))
        self.assertEqual(self.p.config_dados("2026-09")["automatico"], {"BA": {"fat": 6000, "cli": 2}, "ES": {"fat": 2000, "cli": 3}})

    def test_sem_brindes(self):
        r = self.montar(brindes=False).supervisores("2026-09")
        es = next(c for c in r["supervisores"] if c["estado"] == "ES")
        self.assertTrue(r["sem_brindes"])
        self.assertEqual((es["contas"]["brindes"], es["contas"]["liquido"]), (0, 1350))
        self.assertTrue(any("brindes" in a for a in r["avisos"]))

    def test_supervisores_do_acesso(self):
        p = self.montar()
        self.assertEqual(p.estados_supervisor(None, None), ["BA", "ES"])
        self.assertEqual(p.estados_supervisor(None, {"ES", "EDIR"}), ["ES"])
        self.assertEqual(p.estados_supervisor({ES}, None), [])
        self.assertEqual([c["estado"] for c in p.calcular("supervisores", None, None, {"BA", "EDIR"})["supervisores"]], ["BA"])
        with self.assertRaises(PermissionError):
            p.calcular("supervisores", None, {ES}, {"ES"})
        with self.assertRaises(PermissionError):
            p.calcular("supervisores", None, None, {"EDIR"})

    def test_config_dados(self):
        c = self.montar().config_dados()
        self.assertEqual((c["mes"]["valor"], c["config"], c["padrao"]), ("2026-09", _valida(padrao()), padrao()))
        self.assertIn({"id": 3, "nome": "VENCIDO"}, c["motivos"])
        produtos = {p["id"]: p["nome"] for p in c["produtos"]}
        self.assertEqual(produtos[32], "QUEIJO MUSSARELA 4KG")
        self.assertIn(12551, produtos)  # na lista, mesmo sem venda


class TestConfigNoBanco(BaseBanco):
    def test_grava_versoes(self):
        cfg = ConfigPremiacoes(self.banco)
        self.assertEqual(cfg.atual(), _valida(padrao()))
        uid = self.criar_usuario("admin2", "admin")
        novo = padrao()
        novo["supervisores"]["ajustes"] = {"2026-10": {"ES": {"cli": 990}}}
        cfg.salvar(novo, {"id": uid, "nome": "Admin2"})
        self.assertEqual(ConfigPremiacoes(self.banco).atual()["supervisores"]["ajustes"], {"2026-10": {"ES": {"cli": 990}}})
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT nome, salva_por_nome FROM regras").fetchall(), [("premiacoes", "Admin2")])
        ruim = padrao()
        ruim["supervisores"]["receita"]["peso"] = 0.5
        with self.assertRaises(ValueError):
            cfg.salvar(ruim)


if __name__ == "__main__":
    unittest.main()

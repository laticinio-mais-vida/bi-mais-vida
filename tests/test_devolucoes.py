"""Página Devoluções (bi/devolucoes.py) e o Parecer de Devoluções em PDF (bi/parecer_pdf.py).

Usa o cache sintético de tests/apoio.py (setembro/26; cada devolução de lá é uma nota, de 1 a 4) com as notas e os
brindes abaixo. Em setembro, sem filtro:
- voltou na entrega 565 em 6 notas: erro de lançamento 215 (notas 1, 10, 11 e a parte de 40 da 17), recusa 280 (a 4 e a
  parte de 30 da 17; a de 500 está cancelada) e erro da logística 70 (a 13, de um terceiro sem equipe). A 17 tem as duas
  causas e conta uma vez no total;
- perda no cliente 235: vencido 170 (a nota 2, de 50, a 12, de 90 do código antigo da bandeja, e o brinde vencido de
  30), danificado no cliente 40 (o brinde 12) e danificado na produção 25 (a 19);
- outros motivos 10 (o 99, que a página não conhece); total 810.
Ficam fora: a conta OCULTO (139), a nota e os brindes de funcionário e o brinde de degustação.
Venda bruta a cliente: ES 1.500, BA 5.400 e Edir 700 = 7.600 em 4 notas de venda (o terceiro não vendeu). Agosto: a BA
vendeu 4.000 numa nota e teve a recusa 18, de 100; o ES teve o brinde vencido de 70.
"""
from __future__ import annotations

import datetime as dt
import http.client
import importlib.util
import io
import json
import logging
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import duckdb

import app
from bi import parecer_pdf
from bi.devolucoes import (MOTIVOS_TROCA, Devolucoes, Mov, _somar, causa, em_alerta, familia, frequencia, nome_de_arquivo,
                           nome_linha, nome_produto, nome_segmento, regiao_do_grupo)
from tests.apoio import BA, EDIR, ES, criar_calc

D = dt.date
SET = "2026-09"
TEM_PDF = importlib.util.find_spec("fpdf") is not None
TEM_PYPDF = importlib.util.find_spec("pypdf") is not None
TERC, OCULTO = 501, 139
NOMES = {ES: "Rubens", BA: "Thais", EDIR: "Edir"}
# (data, vendedor, cliente, tipo, produto, motivo, valor, quantidade)
BRINDES = [
    (D(2026, 9, 8), ES, 1, "CLIENTE", 27, 16, 30.0, 1.0),         # brinde vencido: troca
    (D(2026, 9, 9), ES, 3, "CLIENTE", 32, 26, 20.0, 1.0),         # degustação: não é troca
    (D(2026, 9, 9), BA, 2, "FUNCIONARIO", 27, 16, 999.0, 1.0),    # funcionário: fora
    (D(2026, 8, 9), ES, 1, "CLIENTE", 27, 16, 70.0, 1.0),         # agosto
    (D(2026, 9, 14), BA, 2, "CLIENTE", 11469, 12, 40.0, 20.0),    # brinde danificado no cliente
]
# As notas de devolução, além das de tests/apoio.py: (nota, data, vendedor, cliente, tipo, produto, motivo, valor, qtd)
NOTAS = [
    (10, D(2026, 9, 20), ES, 1, "CLIENTE", 32, 1, 60.0, 3.0),        # erro de lançamento em outro dia
    (11, D(2026, 9, 10), ES, 1, "CLIENTE", 27, 1, 15.0, 1.0),        # outra nota no mesmo dia e cliente da nota 1
    (12, D(2026, 9, 15), BA, 2, "CLIENTE", 3643, 3, 90.0, 16.0),     # vencido do código antigo da bandeja
    (13, D(2026, 9, 16), TERC, 8, "CLIENTE", 32, 8, 70.0, 2.0),      # erro da logística de um terceiro
    (14, D(2026, 9, 17), OCULTO, 1, "CLIENTE", 32, 1, 999.0, 9.0),   # conta oculta: fora
    (15, D(2026, 9, 18), ES, 3, "CLIENTE", 32, 99, 10.0, 1.0),       # motivo que a página não conhece
    (16, D(2026, 9, 19), ES, 7, "FUNCIONARIO", 32, 1, 500.0, 5.0),   # funcionário: fora
    (17, D(2026, 9, 22), ES, 3, "CLIENTE", 27, 2, 30.0, 1.0),        # uma nota com duas causas:
    (17, D(2026, 9, 22), ES, 3, "CLIENTE", 32, 1, 40.0, 2.0),        #   recusa e erro de lançamento
    (18, D(2026, 8, 20), BA, 2, "CLIENTE", 32, 2, 100.0, 5.0),       # recusa de agosto
    (19, D(2026, 9, 23), BA, 2, "CLIENTE", 32, 15, 25.0, 1.0),       # danificado na produção
]
# a nota 13 é da série 017 e foi emitida dois dias antes da entrada
EMISSAO = {13: (D(2026, 9, 14), "055098", "017")}


def linhas_notas(notas):
    saida = []
    for n, d, v, c, t, p, m, val, q in notas:
        emissao, numero, serie = EMISSAO.get(n, (d, f"{640000 + n:06d}", "013"))
        saida.append((n, numero, serie, emissao, d, v, c, t, False, p, m, val, q))
    return saida


def linhas_clientes_itens(notas):
    """As mesmas notas no formato de devolucoes_clientes_itens (o cache sem as notas)."""
    return [(d, v, c, t, p, m, False, val, q) for _, d, v, c, t, p, m, val, q in notas]


INSERIR_NOTAS = f"INSERT INTO devolucoes_notas VALUES ({', '.join('?' * 13)})"
INSERIR_CLIENTES_ITENS = "INSERT INTO devolucoes_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
EXTRAS = (("INSERT INTO clientes VALUES (?, ?, ?)", [(8, "LOJA DO TERCEIRO", TERC)]),
          ("INSERT INTO vendedores VALUES (?, ?, ?, ?, ?)",
           [(TERC, "GEORGE", None, None, 0), (OCULTO, "GESSIMAR - ES", None, None, 0)]))


def mov(data, cliente, motivo, valor, nota=None, origem="devolucao", vendedor=ES, produto=32, qtd=1.0):
    return Mov(data, vendedor, cliente, produto, motivo, origem, valor, qtd, nota, None, None, None)


class TestFuncoes(unittest.TestCase):
    def test_causas(self):
        self.assertEqual([causa(m) for m in (1, 2, 7, 9, 5, 8, 6, 3, 16, 12, 14, 11, 13, 10, 15, 4, 99, 0)],
                         ["lancamento", "recusa", "faturamento", "expedicao", "falta", "logistica", "ausente", "vencido",
                          "vencido", "danificado_cliente", "danificado_cliente", "danificado_logistica",
                          "danificado_logistica", "danificado_producao", "danificado_producao", "danificado_sem_origem",
                          "outros", "outros"])
        self.assertEqual([familia(m) for m in (1, 6, 9, 3, 4, 99)],
                         ["entrega", "entrega", "entrega", "cliente", "cliente", "outros"])
        self.assertEqual(MOTIVOS_TROCA, (3, 4, 10, 11, 12, 13, 14, 15, 16))  # os brindes que entram

    def test_nomes(self):
        self.assertEqual(nome_linha("A - LINHA DE QUEIJO MUSSARELA"), "Queijo Mussarela")
        self.assertEqual(nome_linha("A - REQUEIJÃO CULINÁRIO BISNAGA"), "Requeijão Culinário Bisnaga")
        self.assertEqual(nome_linha("A - LINHA REQUEIJÃO CREMOSO C/ AMIDO"), "Requeijão Cremoso c/ Amido")
        self.assertEqual(nome_linha(None), "Sem linha")
        self.assertEqual(nome_produto("QUEIJO DE COALHO 370G PALITO"), "Queijo de Coalho 370g Palito")
        self.assertEqual((nome_segmento("MERCEARIA (1 A 3 CAIXAS)"), nome_segmento(None)),
                         ("Mercearia (1 a 3 caixas)", "Sem segmento"))
        self.assertEqual([frequencia(r) for r in ("QUINZENAL", " mensal ", "REDE A PADRÃO", None)],
                         ["Quinzenal", "Mensal", "Outra rede", "Outra rede"])

    def test_somar(self):
        ms = [mov(D(2026, 9, 1), 1, 1, 100.0, nota=7), mov(D(2026, 9, 1), 1, 2, 50.0, nota=7),   # uma nota, 2 causas
              mov(D(2026, 9, 2), 2, 6, 30.0, nota=8),
              mov(D(2026, 9, 3), 1, 16, 20.0, origem="brinde"),                                   # brinde: sem nota
              mov(D(2026, 8, 3), 1, 3, 10.0, nota=9)]                                             # o mesmo cliente
        r = _somar(ms, venda=1000.0, entregas=20, compradores=6, n=2)
        self.assertEqual((r["total"], r["entrega"]["valor"], r["entrega"]["notas"], r["entrega"]["clientes"]),
                         (105.0, 90.0, 1.0, 1.0))  # a média por mês dos 2 meses
        self.assertEqual((r["entrega"]["por_100"], r["entrega"]["valor_medio"], r["pct"]), (10.0, 90.0, 0.21))
        self.assertEqual((r["causas"]["lancamento"]["notas"], r["causas"]["recusa"]["notas"]), (0.5, 0.5))
        self.assertEqual((r["cliente"]["valor"], r["cliente"]["clientes"], r["cliente"]["brinde"]), (15.0, 1.0, 10.0))
        self.assertEqual(r["cliente"]["pct_clientes"], 2 / 6)  # o cliente 1 em agosto e em setembro

    def test_sem_nota_conta_cliente_e_dia(self):
        ms = [mov(D(2026, 9, 1), 1, 1, 10.0), mov(D(2026, 9, 1), 1, 2, 5.0), mov(D(2026, 9, 2), 1, 1, 1.0)]
        self.assertEqual(_somar(ms, 100.0, 1, 1)["entrega"]["notas"], 2.0)

    def test_regiao(self):
        self.assertEqual([regiao_do_grupo(g) for g in ("BA", "EDIR", "ES", None)], ["BA", "BA", "ES", "TERC"])
        self.assertEqual(Devolucoes.regioes(None), ["BA", "ES", "TERC"])
        self.assertEqual(Devolucoes.regioes({"BA", "EDIR"}), ["BA"])
        self.assertEqual(Devolucoes.regioes({"OCULTO"}), [])

    def test_alerta(self):
        self.assertTrue(em_alerta(30, 20, 100))       # 20% e volume 30: no limite, entra
        self.assertFalse(em_alerta(29.9, 20, 100))    # volume abaixo de 30 (e de 100)
        self.assertFalse(em_alerta(50, 19.9, 100))    # % abaixo de 20
        self.assertTrue(em_alerta(100, 1, 10000))     # volume 100 entra com qualquer %
        self.assertTrue(em_alerta(100, 1, None))      # sem compra no mês, só o volume conta
        self.assertFalse(em_alerta(99, 50, None))

    def test_nome_de_arquivo(self):
        self.assertEqual(nome_de_arquivo('Jose: "Carlos"/ES'), "Jose Carlos ES")

    def test_formatos_do_pdf(self):
        self.assertEqual((parecer_pdf.qtd(80), parecer_pdf.qtd(33.56), parecer_pdf.qtd(1234.5)), ("80", "33,56", "1.234,50"))
        self.assertEqual((parecer_pdf.moeda(17090.42), parecer_pdf.pct(0.0028), parecer_pdf.pct(None)),
                         ("17.090,42", "0,28%", "—"))

    def test_limite_do_produto(self):
        ms = [mov(D(2026, 9, 1), 1, 3, 10.0, produto=5413, qtd=15.0),                 # bebida 170g: 15 = o limite
              mov(D(2026, 9, 1), 2, 16, 5.0, origem="brinde", produto=5416, qtd=14.99),  # outro sabor: abaixo, sai
              mov(D(2026, 9, 2), 2, 3, 1.0, produto=777, qtd=1.0)]                    # fora da lista: limite 1, no fim
        s = Devolucoes._secao("vencido", "Vencido", (3, 16), "produtos", ms, {1: 100.0, 2: 200.0}, {1: "A", 2: "B"},
                              {777: "Queijo X"})
        self.assertEqual([(p["nome"], [r["cliente"] for r in p["linhas"]], p["abaixo"]) for p in s["produtos"]],
                         [("Bebida Láctea 170g", ["A"], 1), ("Queijo X", ["B"], 0)])
        self.assertEqual(s["produtos"][0]["linhas"][0]["pct"], 0.1)
        self.assertEqual(s["alerta"], [])


class Base(unittest.TestCase):
    notas = True  # False = o cache sem as notas de devolução (PC com o código anterior)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.calc = criar_calc(self.pasta, linhas_brindes=BRINDES, devolucoes_notas=self.notas)
        self.acrescentar(*self.devolucoes(NOTAS), *EXTRAS)
        self.d = Devolucoes(self.calc, lambda: dict(NOMES))

    def devolucoes(self, notas):
        comandos = [(INSERIR_CLIENTES_ITENS, linhas_clientes_itens(notas))]
        if self.notas:
            comandos.append((INSERIR_NOTAS, linhas_notas(notas)))
        return comandos

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()

    def acrescentar(self, *comandos):
        """Grava no cache já aberto (fecha, grava e reabre)."""
        cache = self.calc.cache
        cache._con.close()
        con = duckdb.connect(str(cache.arquivo))
        for sql, linhas in comandos:
            con.executemany(sql, linhas)
        con.close()
        cache._abrir()


class TestResumo(Base):
    def test_cartoes(self):
        r = self.d.calcular("resumo", SET)
        a = r["cartoes"]["atual"]
        self.assertEqual((r["mes"]["valor"], r["situacao"], r["aba"], r["notas_reais"]), (SET, "final", "resumo", True))
        self.assertEqual((a["total"], a["venda"], a["entregas"], a["compradores"]), (810.0, 7600.0, 4, 4))
        self.assertEqual((a["entrega"]["valor"], a["entrega"]["notas"], a["entrega"]["por_100"], a["entrega"]["clientes"]),
                         (565.0, 6, 150.0, 4))
        self.assertEqual((a["cliente"]["valor"], a["cliente"]["vencido"], a["cliente"]["danificado"], a["cliente"]["brinde"],
                          a["cliente"]["clientes"], a["cliente"]["clientes_vencido"]), (235.0, 170.0, 65.0, 70.0, 2, 2))
        self.assertEqual((a["outros"]["valor"], a["lancamento"]), (10.0, {"notas": 4, "valor": 215.0}))
        self.assertEqual((a["pct"], a["entrega"]["pct"]), (round(810 / 7600, 4), round(565 / 7600, 4)))

    def test_media_dos_6_meses(self):
        r = self.d.calcular("resumo", SET)
        m = r["cartoes"]["media"]
        self.assertEqual((r["janela_cmp"]["rotulo"], r["janela6"]["rotulo"]), ("mar/26 a ago/26", "abr/26 a set/26"))
        # só agosto teve movimento: a média por mês divide por 6, o % é o total sobre a venda dos 6 meses
        self.assertEqual((m["venda"], m["total"], m["entrega"]["notas"]), (round(4000 / 6, 4), round(170 / 6, 4),
                                                                          round(1 / 6, 4)))
        self.assertEqual((m["pct"], m["entrega"]["pct"], m["cliente"]["pct"]), (0.0425, 0.025, 0.0175))

    def test_evolucao(self):
        ev = self.d.calcular("resumo", SET)["evolucao"]
        self.assertEqual((ev[0]["mes"]["valor"], len(ev)), ("2026-01", 9))  # do início do cache até setembro
        self.assertEqual({k: ev[-1][k] for k in ("entrega", "cliente", "outros", "brinde", "notas", "entregas", "venda")},
                         {"entrega": 565.0, "cliente": 235.0, "outros": 10.0, "brinde": 70.0, "notas": 6, "entregas": 4,
                          "venda": 7600.0})
        self.assertEqual((ev[-2]["entrega"], ev[-2]["cliente"], ev[-2]["notas"]), (100.0, 70.0, 1))

    def test_por_responsavel(self):
        g = self.d.calcular("resumo", SET)["responsaveis_mes"]
        self.assertEqual([(x["id"], x["valor"]) for x in g],
                         [("comercial", 495.0), ("pdv", 210.0), ("logistica", 70.0), ("fabrica", 25.0), ("outros", 10.0)])
        self.assertEqual([(c["id"], c["valor"], c["notas"]) for c in g[0]["causas"]],
                         [("recusa", 280.0, 2), ("lancamento", 215.0, 4)])
        self.assertEqual((g[0]["causas"][0]["media_valor"], g[1]["causas"][0]["clientes"]), (round(100 / 6, 4), 2))

    def test_regioes(self):
        rs = self.d.calcular("resumo", SET)["regioes_tabela"]
        self.assertEqual([(x["id"], x["atual"]["total"], x["atual"]["venda"]) for x in rs],
                         [("BA", 405.0, 6100.0), ("ES", 335.0, 1500.0), ("TERC", 70.0, 0.0)])  # o Edir na BA
        self.assertEqual((rs[0]["media"]["pct"], rs[2]["atual"]["pct"]), (0.025, None))  # o brinde de agosto é do ES
        self.assertEqual(self.d.calcular("resumo", SET, regiao="ES")["regioes_tabela"], [])  # uma região só: sem tabela

    def test_avisos(self):
        avisos = self.d.calcular("resumo", SET)["avisos"]
        outros = [a for a in avisos if "Outros motivos" in a]                          # motivo novo: em Outros motivos
        self.assertEqual(len(outros), 1)
        self.assertIn("um motivo sem nome no ERP", outros[0])
        self.assertNotIn("99", outros[0])  # sem o código do motivo: quem usa o painel não conhece
        self.assertTrue(any("troca por brinde só é registrada desde ago/26" in a for a in avisos))
        self.assertFalse(any("brinde" in a for a in self.d.calcular("entrega", SET)["avisos"]))

    def test_nao_depende_das_configuracoes(self):
        cfg = self.calc.configuracao.atual()
        cfg["devolucoes"] = {"motivos": [], "ignorar_canceladas": False}  # o que vale em Metas não vale aqui
        cfg["produtos_equivalentes"] = {}
        self.calc.configuracao.salvar(cfg)
        a = self.d.calcular("resumo", SET)["cartoes"]["atual"]
        self.assertEqual((a["total"], a["entrega"]["valor"]), (810.0, 565.0))  # a recusa cancelada continua fora


    def test_sem_codigos_do_erp(self):
        r = self.d.calcular("resumo", SET)
        self.assertTrue(all("motivos" not in c and c["descricao"] for c in r["causas"]))
        self.assertEqual({c["id"]: c["nome"] for c in r["causas"] if c["familia"] == "cliente"},
                         {"vencido": "Vencido", "danificado_cliente": "Danificado no cliente",
                          "danificado_logistica": "Danificado na logística", "danificado_producao": "Danificado na produção",
                          "danificado_sem_origem": "Danificado, sem origem informada"})
        cliente = next(f for f in r["familias"] if f["id"] == "cliente")
        self.assertEqual(cliente["nome"], "Vencido e danificado no cliente")
        self.assertIn("voltou vencido ou danificado", cliente["descricao"])


class TestEntrega(Base):
    def test_causas(self):
        r = self.d.calcular("entrega", SET)
        self.assertEqual([(c["id"], c["notas"], c["valor"]) for c in r["causas_entrega"]],
                         [("recusa", 2, 280.0), ("lancamento", 4, 215.0), ("logistica", 1, 70.0)])
        self.assertEqual((r["causas_entrega"][0]["media_notas"], r["causas_entrega"][1]["valor_medio"]),
                         (round(1 / 6, 4), 53.75))

    def test_notas_do_mes(self):
        ns = self.d.calcular("entrega", SET)["notas"]
        self.assertEqual([(n["numero"], n["valor"]) for n in ns],
                         [("640004", 250.0), ("640001", 100.0), ("055098", 70.0), ("640017", 70.0), ("640010", 60.0),
                          ("640011", 15.0)])  # a 1 e a 11 são do mesmo dia e cliente, mas são duas notas
        n13, n17 = ns[2], ns[3]
        self.assertEqual((n13["serie"], n13["emissao"], n13["data"], n13["regiao"], n13["cliente"]["nome"]),
                         ("017", D(2026, 9, 14), D(2026, 9, 16), "TERC", "LOJA DO TERCEIRO"))
        self.assertEqual((n17["causas"], n17["itens"], n17["vendedor"]), (["lancamento", "recusa"], 2, "Rubens"))

    def test_vendedores(self):
        r = self.d.calcular("entrega", SET)
        self.assertEqual([(v["id"], v["notas"], v["entregas"], v["por_100"], v["valor"]) for v in r["vendedores_entrega"]],
                         [(BA, 1, 1, 100.0, 250.0), (ES, 4, 2, 200.0, 245.0), (TERC, 1, 0, None, 70.0)])
        es = r["vendedores_entrega"][1]
        self.assertEqual((es["lancamento_notas"], es["lancamento_valor"]), (4, 215.0))
        self.assertEqual(r["sem_nota"], 1)  # o Edir vendeu sem nenhuma nota devolvida

    def test_clientes_que_repetem(self):
        rs = self.d.calcular("entrega", SET)["repetem"]
        self.assertEqual([(c["id"], c["notas"], c["valor"]) for c in rs], [(1, 3, 175.0), (2, 2, 350.0)])
        self.assertEqual((rs[0]["causas"], rs[1]["meses"], rs[1]["ultima"]),
                         ([{"id": "lancamento", "notas": 3}], [False, False, False, False, True, True], D(2026, 9, 13)))


class TestCliente(Base):
    def test_cartoes_e_seis_meses(self):
        r = self.d.calcular("cliente", SET)
        s = r["seis_meses"]
        self.assertEqual((s["venda"], s["perda"], s["vencido"], s["clientes"], s["metade"], s["oitenta"], s["reincidentes"]),
                         (11600.0, 305.0, 240.0, 2, 1, 2, 0))
        self.assertTrue(any("Outros motivos" in a for a in r["avisos"]))
        # a média (mar a ago/26) começa antes da troca por brinde: avisa
        self.assertTrue(any("troca por brinde só é registrada desde ago/26" in a for a in r["avisos"]))

    def test_produtos(self):
        ls = self.d.calcular("cliente", SET)["produtos"]
        self.assertEqual([(x["linha"], x["perda6"], x["venda6"]) for x in ls],
                         [("Manteiga", 150.0, 300.0), ("Bebidas", 130.0, 200.0), ("Mussarela", 25.0, 10700.0)])
        manteiga = ls[0]["produtos"][0]
        self.assertEqual((manteiga["venc_qtd"], manteiga["pct_venc_qtd"], manteiga["venc_qtd6"], manteiga["pct_venc_qtd6"],
                          manteiga["pct_perda6"]), (3.0, 0.3, 4.0, 0.4, 0.5))
        # sem a equivalência das Configurações: o código antigo da bandeja aparece com o nome dele
        self.assertEqual([(p["id"], p["venc6"], p["danificado6"], p["danificado6_origem"]) for p in ls[1]["produtos"]],
                         [(3643, 90.0, 0.0, {}), (11469, 0.0, 40.0, {"danificado_cliente": 40.0})])
        self.assertIsNone(ls[1]["produtos"][1]["pct_perda6"])  # a bandeja nova não vendeu

    def test_segmentos_e_frequencias(self):
        r = self.d.calcular("cliente", SET)
        self.assertEqual([(s["nome"], s["venda"], s["vencido"], s["clientes_vencido"], s["compradores"])
                          for s in r["segmentos"]],
                         [("Padaria", 9400.0, 90.0, 1, 1), ("Mercado", 1300.0, 150.0, 1, 1), ("Açougue", 200.0, 0.0, 0, 1),
                          ("Sem segmento", 700.0, 0.0, 0, 1)])
        self.assertEqual([(f["nome"], f["venda"], f["vencido"]) for f in r["frequencias"]],
                         [("Semanal", 11600.0, 240.0)])

    def test_danificado_por_origem(self):
        a = {x["id"]: x for x in self.d.calcular("cliente", SET)["danificados"]}
        self.assertEqual((a["danificado_producao"]["valor"], a["danificado_producao"]["valor6"],
                          a["danificado_producao"]["produtos"]),
                         (25.0, 25.0, [{"nome": "Queijo Mussarela 4kg", "valor": 25.0}]))
        self.assertEqual((a["danificado_cliente"]["valor6"], a["danificado_logistica"]["valor6"]), (40.0, 0.0))

    def test_clientes_e_reincidencia(self):
        self.acrescentar(*self.devolucoes([(20, D(2026, 6, 5), ES, 1, "CLIENTE", 27, 3, 5.0, 1.0),
                                           (21, D(2026, 7, 5), ES, 1, "CLIENTE", 27, 3, 5.0, 1.0)]))
        r = self.d.calcular("cliente", SET)
        cs = r["clientes_perda"]
        self.assertEqual([(c["id"], c["perda6"], c["compra6"], c["n_meses"]) for c in cs],
                         [(1, 160.0, 1300.0, 4), (2, 155.0, 9400.0, 1)])
        self.assertEqual((cs[0]["meses"], cs[0]["produto"], cs[0]["perda_mes"], cs[0]["vendedor"]),
                         ([False, False, True, True, True, True], "Manteiga 200g", 80.0, "Rubens"))
        self.assertEqual((r["seis_meses"]["reincidentes"], r["clientes_fora"]), (1, {"n": 0, "perda6": 0}))


class TestVendedores(Base):
    def test_tabela(self):
        t = self.d.calcular("vendedores", SET)["tabela"]
        self.assertEqual([(v["id"], v["regiao"]) for v in t["vendedores"]],
                         [(BA, "BA"), (EDIR, "BA"), (ES, "ES"), (TERC, "TERC")])  # o OCULTO fica fora
        v = {x["id"]: x for x in t["vendedores"]}
        self.assertEqual((v[ES]["nome"], v[ES]["total"], v[ES]["entrega"], v[ES]["cliente"], v[ES]["notas"],
                          v[ES]["lancamento_notas"], v[ES]["compradores"]), ("Rubens", 335.0, 245.0, 80.0, 4, 4, 2))
        self.assertEqual((v[BA]["total"], v[BA]["vencido"], v[BA]["media_pct"]), (405.0 - 0, 90.0, 0.025))
        self.assertEqual((v[EDIR]["total"], v[EDIR]["venda"]), (0.0, 700.0))  # vendeu sem devolução: entra
        self.assertEqual((v[TERC]["nome"], v[TERC]["total"], v[TERC]["pct"]), ("George", 70.0, None))
        self.assertIsNone(v[ES]["media_pct"])  # nos 6 meses o ES só teve o brinde, sem venda
        self.assertEqual([(x["id"], x["vendedores"], x["total"]) for x in t["regioes"]],
                         [("BA", 2, 405.0), ("ES", 1, 335.0), ("TERC", 1, 70.0)])
        self.assertEqual((t["total"]["total"], t["total"]["venda"], t["total"]["vendedores"]), (810.0, 7600.0, 4))

    def test_reincidentes_do_vendedor(self):
        self.acrescentar(*self.devolucoes([(20, D(2026, 6, 5), ES, 1, "CLIENTE", 27, 3, 5.0, 1.0),
                                           (21, D(2026, 7, 5), ES, 1, "CLIENTE", 27, 3, 5.0, 1.0)]))
        t = self.d.calcular("vendedores", SET)["tabela"]
        self.assertEqual(({v["id"]: v["reincidentes"] for v in t["vendedores"]}[ES], t["total"]["reincidentes"]), (1, 1))

    def test_terceirizados_sem_devolucao(self):
        self.acrescentar(("INSERT INTO vendedores VALUES (?, ?, ?, ?, ?)",
                          [(601, "FUNCIONARIO", None, None, 0), (602, "VENDA INTERNA", None, None, 0)]),
                         ("INSERT INTO vendas_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?)",
                          [(D(2026, 9, 3), 601, 1, "CLIENTE", 32, 100.0, 5.0),
                           (D(2026, 9, 4), 602, 2, "CLIENTE", 32, 50.0, 2.0)]))
        t = self.d.calcular("vendedores", SET)["tabela"]
        ultimo = t["vendedores"][-1]  # os dois viram uma linha só, no fim dos terceirizados
        self.assertEqual((ultimo["id"], ultimo["nome"], ultimo["agrupados"], ultimo["venda"], ultimo["pct"]),
                         (None, "Outros 2 sem devolução", ["Funcionario", "Venda Interna"], 150.0, 0.0))
        self.assertEqual([v["id"] for v in t["vendedores"]], [BA, EDIR, ES, TERC, None])
        self.assertEqual((t["regioes"][-1]["vendedores"], t["total"]["venda"]), (3, 7750.0))  # a venda deles continua

    def test_parecer(self):
        p = self.d.calcular("vendedores", SET)["parecer"]
        self.assertEqual([(r["id"], [v["nome"] for v in r["vendedores"]]) for r in p["regioes"]],
                         [("BA", ["THAIS - CENTRAL"]), ("ES", ["RUBENS - ES"])])  # o terceiro só tem erro da logística
        es = p["regioes"][1]["vendedores"][0]
        self.assertEqual([s["chave"] for s in es["secoes"]], ["lancamento", "recusa"])  # o vencido da manteiga < limite
        lanc = es["secoes"][0]
        # como no documento de sempre: cada data e cliente é um erro (as notas 1 e 11 contam um)
        self.assertEqual((lanc["erros"], lanc["linhas"][0]["cliente"], lanc["total"]),
                         (3, "MERCADO DO JOAO", {"qtd": 11.0, "valor": 215.0}))
        ba = p["regioes"][0]["vendedores"][0]
        self.assertEqual([s["chave"] for s in ba["secoes"]], ["recusa", "vencido", "dan_producao", "brinde_cliente"])
        bandeja = ba["secoes"][1]["produtos"][0]  # o código antigo da bandeja continua no produto do Parecer
        self.assertEqual((bandeja["nome"], bandeja["linhas"][0]["qtd"], bandeja["linhas"][0]["fat"]),
                         ("Bebida Láctea 500g Bandeja", 16.0, 5400.0))
        self.assertEqual(bandeja["linhas"][0]["pct"], round(90 / 5400, 4))  # a página recebe 4 casas (1,67%)
        self.assertEqual([r["chave"] for r in p["rankings"]],
                         ["lancamento", "vencido", "dan_producao", "brinde_cliente", "recusa"])
        self.assertEqual(p["rankings"][0]["linhas"],
                         [{"vendedor": "RUBENS - ES", "regiao": "ES", "volume": 11.0, "valor": 215.0, "erros": 3}])
        self.assertEqual([(x["vendedor"], x["regiao"], x["valor"]) for x in p["rankings"][1]["linhas"]],
                         [("THAIS - CENTRAL", "BA", 90.0), ("RUBENS - ES", "ES", 80.0)])  # todo o vencido, sem limite
        self.assertEqual([(x["cliente"], x["valor"]) for x in p["rankings"][4]["linhas"]],
                         [("PADARIA DA MARIA", 250.0), ("ACOUGUE SAO JOSE", 30.0)])

    def test_cliente_em_alerta(self):
        self.acrescentar(*self.devolucoes([(22, D(2026, 9, 21), ES, 3, "CLIENTE", 11469, 3, 100.0, 35.0)]))
        es = self.d.calcular("vendedores", SET)["parecer"]["regioes"][1]["vendedores"][0]
        vencido = next(s for s in es["secoes"] if s["chave"] == "vencido")  # 35 un. e R$ 100 sobre R$ 200: 50%
        self.assertEqual([(x["cliente"], x["volume"], x["fat"], x["pct"]) for x in vencido["alerta"]],
                         [("ACOUGUE SAO JOSE", 35.0, 200.0, 0.5)])


class TestAcessoEFiltros(Base):
    def test_acesso(self):
        r = self.d.calcular("resumo", SET, permitidos={BA}, equipes={"BA", "EDIR"})
        self.assertEqual((r["cartoes"]["atual"]["total"], [x["id"] for x in r["regioes"]]), (405.0, ["BA"]))
        r = self.d.calcular("vendedores", SET, equipes={"ES"})
        self.assertEqual([v["id"] for v in r["tabela"]["vendedores"]], [ES])  # sem a BA e sem o terceiro
        self.assertEqual([x["id"] for x in r["parecer"]["regioes"]], ["ES"])
        with self.assertRaises(PermissionError):
            self.d.calcular("resumo", SET, regiao="TERC", equipes={"ES"})

    def test_acesso_so_com_lista(self):
        """O "só alguns" da tela Usuários chega só com os vendedores (sem equipes): as regiões são as deles."""
        r = self.d.calcular("resumo", SET, permitidos={ES})
        self.assertEqual((r["cartoes"]["atual"]["total"], [x["id"] for x in r["regioes"]]), (335.0, ["ES"]))
        with self.assertRaises(PermissionError):  # sem terceirizado na lista, a região não aparece
            self.d.calcular("resumo", SET, regiao="TERC", permitidos={ES})
        r = self.d.calcular("resumo", SET, permitidos={ES, TERC})
        self.assertEqual([x["id"] for x in r["regioes"]], ["ES", "TERC"])
        r = self.d.calcular("resumo", SET, permitidos=set())  # sem vendedores escolhidos: nada
        self.assertEqual((r["regioes"], r["cartoes"]["atual"]["total"]), ([], 0.0))

    def test_filtros(self):
        r = self.d.calcular("entrega", SET, regiao="TERC")
        self.assertEqual(([n["numero"] for n in r["notas"]], [v["id"] for v in r["vendedores_filtro"]]),
                         (["055098"], [TERC]))
        r = self.d.calcular("resumo", SET, vendedores=[ES])
        self.assertEqual((r["cartoes"]["atual"]["total"], r["vendedores"]), (335.0, [ES]))
        self.assertEqual({v["id"] for v in r["vendedores_filtro"]}, {BA, EDIR, ES, TERC})  # a lista não encolhe
        with self.assertRaises(ValueError):
            self.d.calcular("resumo", "2025-12")  # antes do início do cache
        with self.assertRaises(ValueError):
            self.d.calcular("geral")  # a aba antiga


class TestSemNotas(Base):
    """O cache do PC com o código anterior (sem as notas): cada cliente num dia conta como uma nota."""
    notas = False

    def test_conta_por_cliente_e_dia(self):
        r = self.d.calcular("entrega", SET)
        self.assertFalse(r["notas_reais"])
        self.assertTrue(any("número das notas de devolução ainda não chegou" in a for a in r["avisos"]))
        a = r["cartoes"]["atual"]["entrega"]
        self.assertEqual((a["valor"], a["notas"]), (565.0, 5))  # as notas 1 e 11 (mesmo dia e cliente) viram uma
        self.assertEqual([n["numero"] for n in r["notas"]], [None] * 5)


class TestSemBrindes(unittest.TestCase):
    def test_cache_sem_brindes(self):
        with tempfile.TemporaryDirectory() as pasta:
            calc = criar_calc(Path(pasta), brindes=False)
            try:
                r = Devolucoes(calc, lambda: {}).calcular("resumo", SET)
                self.assertEqual((r["cartoes"]["atual"]["cliente"]["brinde"], r["cartoes"]["atual"]["total"]), (0, 400.0))
                self.assertTrue(any("brindes ainda não chegaram" in a for a in r["avisos"]))
            finally:
                calc.cache._con.close()


@unittest.skipUnless(TEM_PDF, "sem o pacote fpdf2")
class TestParecerPdf(Base):
    def test_pdf_do_vendedor(self):
        corpo, nome, tipo = self.d.arquivo(SET, "vendedor", str(BA))
        self.assertTrue(corpo.startswith(b"%PDF"))
        self.assertEqual((nome, tipo), ("Parecer Devoluções Setembro-2026 Thais.pdf", "application/pdf"))

    def test_regiao_e_geral(self):
        self.assertEqual(self.d.arquivo(SET, "regiao", regiao="ES")[1], "Parecer Devoluções Setembro-2026 ES.pdf")
        corpo, nome, _ = self.d.arquivo(SET)  # o documento geral: BA + ES
        self.assertEqual(nome, "Parecer Devoluções Setembro-2026.pdf")
        self.assertTrue(corpo.startswith(b"%PDF"))

    def test_todos_no_zip(self):
        corpo, nome, tipo = self.d.arquivo(SET, "todos")
        self.assertEqual((nome, tipo), ("Parecer Devoluções Setembro-2026.zip", "application/zip"))
        with zipfile.ZipFile(io.BytesIO(corpo)) as z:
            self.assertEqual(z.namelist(), ["Parecer Devoluções Setembro-2026.pdf",
                                            "BA/Parecer Devoluções Setembro-2026 BA.pdf",
                                            "BA/Parecer Devoluções Setembro-2026 Thais.pdf",
                                            "ES/Parecer Devoluções Setembro-2026 ES.pdf",
                                            "ES/Parecer Devoluções Setembro-2026 Rubens.pdf"])
            self.assertTrue(all(z.read(n).startswith(b"%PDF") for n in z.namelist()))

    def test_acesso_e_erros(self):
        corpo, _, _ = self.d.arquivo(SET, "todos", equipes={"ES"})
        with zipfile.ZipFile(io.BytesIO(corpo)) as z:
            self.assertEqual([n for n in z.namelist() if "/" in n], ["ES/Parecer Devoluções Setembro-2026 ES.pdf",
                                                                     "ES/Parecer Devoluções Setembro-2026 Rubens.pdf"])
        with self.assertRaises(ValueError):
            self.d.arquivo(SET, "vendedor", str(BA), equipes={"ES"})  # vendedor fora do acesso
        with self.assertRaises(ValueError):
            self.d.arquivo(SET, "vendedor", str(EDIR))  # o Edir não teve devolução no mês
        with self.assertRaises(ValueError):
            self.d.arquivo(SET, "regiao", regiao="TERC")  # o terceiro só tem erro da logística, fora do Parecer
        with self.assertRaises(ValueError):
            self.d.arquivo(SET, "planilha")

    @unittest.skipUnless(TEM_PYPDF, "sem o pacote pypdf")
    def test_texto_do_pdf(self):
        import pypdf
        corpo, _, _ = self.d.arquivo(SET, "vendedor", str(ES))
        texto = " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(corpo)).pages)
        for trecho in ("PARECER DE DEVOLUÇÕES", "Competência: Setembro de 2026", "Vendedor: RUBENS - ES (Região ES)",
                       "Erros de lançamento cometidos no mês: 3", "MERCADO DO JOAO", "RANKINGS POR TIPO DE DEVOLUÇÃO",
                       "Ranking – Recusa do Cliente", "PADARIA DA MARIA"):
            self.assertIn(trecho, texto)


class UsuariosFalsos:
    """Só o que o Manipulador usa para saber quem pede: a sessão (o valor do cookie) -> o usuário."""

    def __init__(self, pessoas: dict):
        self.pessoas = pessoas

    def da_sessao(self, valor):
        return self.pessoas.get(valor)


class TestRotas(Base):
    def setUp(self):
        super().setUp()
        nulo = logging.NullHandler()  # o registro de quem baixou o PDF não suja a saída dos testes
        logging.getLogger("bi").addHandler(nulo)
        self.addCleanup(logging.getLogger("bi").removeHandler, nulo)
        pessoa = lambda id_, papel, paginas, escopo: {"id": id_, "login": f"p{id_}", "nome": f"P{id_}",  # noqa: E731
                                                     "papel": papel, "paginas": paginas, "visoes": [],
                                                     "escopo": escopo}
        pessoas = {"chefe": pessoa(1, "admin", [], None),
                   "es": pessoa(2, "visualizador", ["devolucoes"], {"modo": "equipes", "equipes": ["ES"]}),
                   "ana": pessoa(3, "visualizador", ["metas"], {"modo": "todos"})}
        self.app = SimpleNamespace(usuarios=UsuariosFalsos(pessoas), devolucoes=self.d, vps=False)
        manipulador = type("ManipuladorDoTeste", (app.Manipulador,), {"app": self.app})  # sem mexer no global
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)

    def pedir(self, caminho: str, quem: str):
        con = http.client.HTTPConnection("127.0.0.1", self.servidor.server_address[1], timeout=30)
        try:
            con.request("GET", caminho, headers={"Cookie": f"{app.COOKIE}={quem}"})
            r = con.getresponse()
            return r.status, r.read(), r
        finally:
            con.close()

    def test_sem_a_pagina(self):
        self.assertEqual(self.pedir("/api/devolucoes", "ana")[0], 403)
        self.assertEqual(self.pedir("/api/devolucoes/parecer?mes=2026-09", "ana")[0], 403)
        self.assertEqual(self.pedir("/api/devolucoes", "ninguem")[0], 401)

    def test_com_a_pagina(self):
        status, corpo, _ = self.pedir("/api/devolucoes?aba=resumo&mes=2026-09", "es")
        self.assertEqual(status, 200)
        d = json.loads(corpo)
        self.assertEqual((d["cartoes"]["atual"]["total"], [r["id"] for r in d["regioes"]]), (335.0, ["ES"]))
        status, corpo, _ = self.pedir("/api/devolucoes?aba=entrega&mes=2026-09", "es")
        self.assertEqual((status, json.loads(corpo)["notas"][0]["data"]), (200, "2026-09-10"))  # a data em texto
        self.assertEqual(self.pedir("/api/devolucoes?regiao=BA", "es")[0], 403)  # região fora do acesso
        self.assertEqual(self.pedir("/api/devolucoes?aba=nada", "es")[0], 400)

    @unittest.skipUnless(TEM_PDF, "sem o pacote fpdf2")
    def test_baixar_o_parecer(self):
        status, corpo, r = self.pedir("/api/devolucoes/parecer?mes=2026-09&tipo=vendedor&vendedor=141", "chefe")
        self.assertEqual((status, r.getheader("Content-Type")), (200, "application/pdf"))
        self.assertTrue(corpo.startswith(b"%PDF"))
        self.assertIn("filename*=UTF-8''Parecer%20Devolu%C3%A7%C3%B5es%20Setembro-2026%20Thais.pdf",
                      r.getheader("Content-Disposition"))
        status, corpo, _ = self.pedir("/api/devolucoes/parecer?mes=2026-09&tipo=vendedor&vendedor=141", "es")
        self.assertEqual(status, 400)  # o vendedor da BA não é do acesso do ES
        self.assertIn("não tem devolução", json.loads(corpo)["erro"])


if __name__ == "__main__":
    unittest.main()

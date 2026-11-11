"""Página Premiações (bi/premiacoes.py): vendedores (a página "Premiacao Vendedores" do Power BI), supervisores (os
regulamentos de nov/2026) e comissão.

Usa o cache sintético de tests/apoio.py (setembro/26; carteira: clientes 1 e 3 do ES, 2 e 7 do BA, 4 do Edir; hoje, para
a inadimplência, é 01/10/2026; o início dos dados é 01/01/2026), mais os brindes de BRINDES e o que cada teste acrescenta.
"""
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from bi import premiacoes_pdf
from bi.configuracao import Regras, padrao as padrao_metas
from bi.premiacoes import (ConfigPremiacoes, Premiacoes, _valida, adicional_inadimplencia, alcance, clientes_para,
                           conta_supervisor, faixa_vendedor, janela, nome_cliente, padrao, pct_bonus, pct_devolucao,
                           pct_faixa, proxima, proxima_faixa)
from bi.sugestao import ler_mes, texto_mes
from tests.apoio import BA, EDIR, ES, BaseBanco, ConfiguracaoFixa, criar_calc

D = dt.date
SET = D(2026, 9, 1)
FAIXAS = padrao()["vendedores"]["faixas"]
REGRAS = padrao()["supervisores"]
# (data, vendedor, cliente, tipo, produto, motivo, valor, quantidade)
BRINDES = [
    (D(2026, 9, 8), ES, 1, "CLIENTE", 27, 16, 30.0, 1.0),          # brinde vencido
    (D(2026, 9, 9), ES, 3, "CLIENTE", 32, 26, 20.0, 1.0),          # degustação, mussarela
    (D(2026, 9, 9), BA, 2, "FUNCIONARIO", 27, 16, 999.0, 1.0),     # código de outro cadastro: fica fora
    (D(2026, 8, 9), ES, 1, "CLIENTE", 27, 16, 70.0, 1.0),          # outro mês
]
# Comissão. Vendas com a comissão que o ERP gravou (data, vendedor, tipo, produto, valor, comissão) e a tabela de hoje
# (vendedor, produto, %). O Rubens (ES) tinha 1% na mussarela no dia da venda e hoje tem 2%; a manteiga saiu com 0%.
COMISSAO_VENDAS = [
    (D(2026, 9, 2), ES, "CLIENTE", 32, 1000.0, 10.0),
    (D(2026, 9, 2), ES, "CLIENTE", 27, 300.0, 0.0),        # vendida antes de a manteiga ter % na tabela
    (D(2026, 9, 15), ES, "CLIENTE", 3643, 200.0, 4.0),     # sem % na tabela hoje (o gravado vale)
    (D(2026, 9, 20), ES, "FUNCIONARIO", 32, 80.0, 0.0),    # funcionário: fora
    (D(2026, 9, 3), BA, "CLIENTE", 32, 5000.0, 75.0),
    (D(2026, 9, 3), BA, "CLIENTE", 999, 400.0, 0.0),
    (D(2026, 8, 10), BA, "CLIENTE", 32, 4000.0, 60.0),     # agosto
    (D(2026, 9, 5), EDIR, "CLIENTE", 32, 700.0, 70.0),     # Edir: comissão sobre o recebimento, fica fora
    (D(2026, 9, 6), 501, "CLIENTE", 32, 100.0, 15.0),      # terceiro, sem equipe: fora
]
PERCENTUAIS = [(ES, 32, 2.0), (ES, 27, 3.0), (BA, 32, 1.5), (EDIR, 32, 10.0)]
BRINDE_SEM_PCT = (D(2026, 9, 10), BA, 2, "CLIENTE", 999, 12, 40.0, 1.0)  # danificado no cliente; sem % na tabela

# As regras salvas antes dos regulamentos de nov/2026 (versão 1, como o painel gravava), com alguns valores mudados.
V1 = {
    "versao": 1,
    "vendedores": {"faixas": [{"min": 0.91, "valor": 200.0}, {"min": 0.96, "valor": 250.0}, {"min": 1.0, "valor": 350.0}]},
    "supervisores": {
        "maximo": 5000.0,
        "nomes": {"BA": "Marcos Vinicius", "ES": "Ronaldo"},
        "produtos_fora_mix": [32, 12551],
        "motivos_improprios": [3, 4, 10, 11, 12, 13, 14, 15, 16],
        "receita": {"peso": 0.25, "minimo": 0.8},
        "mix": {"peso": 0.15, "minimo": 0.85, "meta": {"BA": 0.5, "ES": 0.6}},
        "inadimplencia": {"peso": 0.1, "meta": {"BA": 0.0042, "ES": 0.005}, "dias": 45},
        "positivacao": {"peso": 0.25, "minimo": 0.8},
        "devolucoes": {"peso": 0.25, "meta": {"BA": 0.015, "ES": 0.015}},
        "ajustes": {"2026-09": {"BA": {"fat": 2000000.0}, "ES": {"cli": 990}}},
    },
    "comissao": {"motivos_brindes": [10, 16]},
}
CHAVES_V1 = {"ajustes", "nomes", "maximo", "motivos_improprios", "receita", "mix", "inadimplencia", "positivacao",
             "devolucoes"}

# Para acrescentar ao cache: clientes, cadastros e compras.
CLIENTE = "INSERT INTO clientes VALUES (?, ?, ?)"
DETALHE = "INSERT INTO clientes_detalhes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
VENDA = "INSERT INTO vendas_clientes VALUES (?, ?, ?, ?, ?)"
ITEM = "INSERT INTO vendas_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?)"


def cliente(cid: int, vendedor: int, cadastro: dt.date | None, compras=(), inativo: int = 0, valor: float = 100.0,
            vendedor_da_venda: int | None = None) -> list:
    """Um cliente na carteira de `vendedor`, cadastrado em `cadastro`, com compras de R$ `valor` em manteiga."""
    linhas = [(CLIENTE, [(cid, f"CLIENTE {cid}", vendedor)])]
    if cadastro:
        linhas.append((DETALHE, [(cid, f"CLIENTE {cid} LTDA", "SERRA", "ES", 1, "ROTA 1", 1, "MERCADO", inativo,
                                  cadastro)]))
    v = vendedor_da_venda or vendedor
    if compras:
        linhas += [(VENDA, [(d, v, cid, "CLIENTE", 1) for d in compras]),
                   (ITEM, [(d, v, cid, "CLIENTE", 27, valor, 1.0) for d in compras])]
    return linhas


class ConfigFixa:
    """As regras da página em memória (sem o banco)."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = _valida(cfg or padrao())

    def atual(self) -> dict:
        return copy.deepcopy(self.cfg)


def ind(cartao: dict, k: str) -> dict | None:
    return next((x for x in cartao["indicadores"] if x["id"] == k), None)


TEM_PYPDF = importlib.util.find_spec("pypdf") is not None
TEM_FPDF = importlib.util.find_spec("fpdf") is not None


def texto_pdf(conteudo: bytes) -> str:
    """O texto de um PDF (o pypdf é o mesmo que lê o Serasa na página de crédito)."""
    from pypdf import PdfReader
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(conteudo)).pages)


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

    def test_escalas(self):
        fat, cli = REGRAS["escala_faturamento"], REGRAS["escala_clientes"]
        for a, esperado in ((None, 0), (0.8999, 0), (0.9, 0.3), (1800 / 2000, 0.3), (0.9999, 0.3), (1.0, 1.0),
                            (1.5, 1.0)):
            with self.subTest(faturamento=a):
                self.assertEqual(pct_faixa(a, fat), esperado)
        for a, esperado in ((0.7999, 0), (0.8, 0.4), (32 / 40, 0.4), (0.9999, 0.4), (1.0, 1.0), (1.1999, 1.0),
                            (1.2, 1.5), (24 / 20, 1.5), (3.0, 1.5)):
            with self.subTest(clientes=a):
                self.assertEqual(pct_faixa(a, cli), esperado)

    def test_trava_bonus_e_devolucao(self):
        for a, esperado in ((None, 0), (0.8999, 0), (0.9, 0.5), (0.9499, 0.5), (0.95, 1.0), (1.3, 1.0)):
            with self.subTest(trava=a):
                self.assertEqual(pct_faixa(a, REGRAS["trava"]), esperado)
        for a, esperado in ((None, 0), (0.9, 0), (1.0, 0), (1.00001, 0.02), (1.0999, 0.02), (1.1, 0.05),
                            (1.2, 0.07), (1.4999, 0.07), (1.5, 0.10), (2.0, 0.10)):
            with self.subTest(bonus=a):
                self.assertEqual(pct_bonus(a, REGRAS["bonus"]), esperado)  # 100% exato não tem bônus
        for i, esperado in ((0.0, 1.0), (0.005, 1.0), (0.0050001, 0.95), (0.007, 0.95), (0.01, 0.95),
                            (0.0100001, 0.90), (0.2, 0.90), (None, 0.90)):
            with self.subTest(devolucao=i):
                self.assertEqual(pct_devolucao(i, REGRAS["devolucao"]), esperado)

    def test_adicional_da_inadimplencia(self):
        regra = {"valor": 450.0, "limite": 0.0045}
        self.assertEqual(adicional_inadimplencia(regra, 0.004, 1.0), 450)
        self.assertEqual(adicional_inadimplencia(regra, 0.0045, 0.5), 450)  # no limite; trava de 50% não reduz
        self.assertEqual(adicional_inadimplencia(regra, 0.0046, 1.0), 0)
        self.assertEqual(adicional_inadimplencia(regra, 0.0, 0.0), 0)  # a trava zerou: não recebe nada
        self.assertEqual(adicional_inadimplencia(regra, None, 1.0), 0)
        self.assertEqual(adicional_inadimplencia(None, 0.0, 1.0), 0)

    def test_exemplos_dos_regulamentos(self):
        # Ronaldo: 100% das quatro parcelas, faturamento a 105% e devolução imprópria de 0,7%
        c = conta_supervisor([1800, 1500, 1500, 1200], 1.05, 0.007, REGRAS)
        self.assertEqual((c["conquistado"], c["trava"]["valor"], c["bonus"]["total"], c["devolucao"]["total"],
                          c["premio"]), (6000, 6000, 6120, 5814, 5814))
        self.assertEqual((c["bonus"]["valor"], c["devolucao"]["valor"], c["adicional"]), (120, -306, None))
        # Valdirene: as cinco parcelas, e o critério de inadimplência atendido
        c = conta_supervisor([3150, 1800, 1350, 1350, 1350], 1.05, 0.007, REGRAS, {"valor": 450.0, "limite": 0.0045},
                             0.0045)
        self.assertEqual((c["conquistado"], c["bonus"]["total"], c["devolucao"]["total"], c["premio"]),
                         (9000, 9180, 8721, 9171))
        self.assertEqual((c["adicional"]["pago"], c["adicional"]["valor"]), (True, 450))

    def test_trava(self):
        # outubro/26 do Ronaldo: faturamento a 94% (trava de 50%) e vencido de 0,8% (mantém 95%)
        c = conta_supervisor([540, 600, 0, 1800], 2012630.37 / 2140000, 0.008, REGRAS)
        self.assertEqual((c["conquistado"], c["trava"]["pct"], c["trava"]["valor"], c["bonus"]["pct"], c["premio"]),
                         (2940, 0.5, 1470, 0, 1396.5))
        c = conta_supervisor([0, 1350, 1350, 1350], 0.85, 0.0, REGRAS, {"valor": 450.0, "limite": 0.0045}, 0.001)
        self.assertEqual((c["premio"], c["adicional"]["motivo"]), (0, "trava"))  # nem o adicional
        c = conta_supervisor([945], 0.94, 0.0, REGRAS, {"valor": 450.0, "limite": 0.0045}, 0.001)
        self.assertEqual((c["premio"], c["adicional"]["valor"]), (472.5 + 450, 450))  # inteiro com a trava de 50%

    def test_proxima_e_alcance(self):
        self.assertIsNone(alcance(10, 0))
        self.assertIsNone(alcance(None, 10))
        self.assertEqual(proxima(29, 40, REGRAS["escala_clientes"], True), {"min": 0.8, "pct": 0.4, "falta": 3})
        self.assertEqual(proxima(894, 972, REGRAS["escala_clientes"], True)["falta"], 78)
        self.assertEqual(proxima(2012630.37, 2140000, REGRAS["escala_faturamento"], False)["falta"], 127369.63)
        self.assertIsNone(proxima(25, 20, REGRAS["escala_clientes"], True))  # 125%: já na última faixa
        self.assertIsNone(proxima(10, None, REGRAS["escala_clientes"], True))

    def test_nome_do_cliente_sem_o_codigo(self):
        self.assertEqual(nome_cliente("HOJE HAMBURGUERIA (CLIENTE 5959)"), "HOJE HAMBURGUERIA")
        self.assertEqual(nome_cliente("MAHAI (CARIACICA) (CLIENTE 5153.6)"), "MAHAI (CARIACICA)")
        self.assertEqual(nome_cliente("CLIENTE 20"), "CLIENTE 20")
        self.assertEqual(nome_cliente("  "), "Cliente sem nome")

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
    def test_padrao(self):
        cfg = _valida(padrao())
        self.assertEqual(cfg, padrao())
        self.assertEqual(_valida(cfg), cfg)  # idempotente
        s = cfg["supervisores"]
        self.assertEqual(cfg["versao"], 2)
        self.assertEqual([(f["min"], f["valor"]) for f in cfg["vendedores"]["faixas"]], [(0.91, 200), (0.96, 250), (1.0, 350)])
        self.assertEqual([(x["id"], x["nome"], x["estado"], x["variavel"]) for x in s["lista"]],
                         [("marcos", "Marcos", "BA", 6000), ("ronaldo", "Ronaldo", "ES", 6000),
                          ("valdirene", "Valdirene", "ES", 9000)])
        for x in s["lista"]:
            self.assertAlmostEqual(sum(x["pesos"].values()), 1)
            self.assertEqual(x["metas_padrao"], {"novos": 40, "reativacao": 20})
        self.assertEqual(s["lista"][0]["pesos"], {"faturamento": 0.3, "mix": 0, "positivacao": 0.25, "novos": 0.25,
                                                  "reativacao": 0.2})
        self.assertEqual([x["inadimplencia"] for x in s["lista"]], [None, None, {"valor": 450, "limite": 0.0045}])
        self.assertEqual((s["motivos_vencido"], s["produtos_fora_mix"], s["dias_sem_compra"], s["dias_inadimplencia"]),
                         ([3, 16], [32, 12551, 12552], 60, 30))
        self.assertFalse(CHAVES_V1 & set(s))  # o código antigo ainda abre uma versão nova, se precisar voltar

    def test_validacao(self):
        cfg = padrao()
        cfg["vendedores"]["faixas"] = [{"min": "1", "valor": "350"}, {"min": 0.9, "valor": 100}]
        s = cfg["supervisores"]
        s["lista"][0].update(estado="ES", nome="  Marcos   Vinicius ")  # o estado não muda
        s["lista"][1]["metas_padrao"] = {"novos": "35", "reativacao": None}
        del s["lista"][2]  # quem não vem fica com o padrão
        s["trava"] = [{"min": 0.95, "pct": 1}, {"min": "0.9", "pct": "0.5"}]
        s["motivos_vencido"] = [16, "3", 3]
        s["metas_mes"] = {"2026-09": {"marcos": {"fat": "2000000", "cli": "", "novos": 0}, "ronaldo": {}}}
        v = _valida(cfg)
        sv = v["supervisores"]
        self.assertEqual(v["vendedores"]["faixas"], [{"min": 0.9, "valor": 100}, {"min": 1.0, "valor": 350}])  # em ordem
        self.assertEqual([(x["id"], x["estado"]) for x in sv["lista"]], [("marcos", "BA"), ("ronaldo", "ES"),
                                                                         ("valdirene", "ES")])
        self.assertEqual(sv["lista"][0]["nome"], "Marcos Vinicius")
        self.assertEqual(sv["lista"][1]["metas_padrao"], {"novos": 35, "reativacao": None})
        self.assertEqual(sv["lista"][2], padrao()["supervisores"]["lista"][2])
        self.assertEqual(sv["trava"], [{"min": 0.9, "pct": 0.5}, {"min": 0.95, "pct": 1.0}])
        self.assertEqual(sv["motivos_vencido"], [3, 16])
        self.assertEqual(sv["metas_mes"], {"2026-09": {"marcos": {"fat": 2000000, "novos": 0}}})  # 0 = sem meta
        erros = {
            "pesos": lambda c: c["supervisores"]["lista"][0]["pesos"].update(faturamento=0.5),
            "faixa repetida": lambda c: c["vendedores"].update(faixas=[{"min": 1, "valor": 1}, {"min": 1, "valor": 2}]),
            "sem faixa": lambda c: c["vendedores"].update(faixas=[]),
            "valor negativo": lambda c: c["vendedores"].update(faixas=[{"min": 1, "valor": -1}]),
            "nome vazio": lambda c: c["supervisores"]["lista"][0].update(nome="  "),
            "supervisor desconhecido": lambda c: c["supervisores"]["lista"].append({"id": "fulano"}),
            "supervisor repetido": lambda c: c["supervisores"]["lista"].append({"id": "marcos"}),
            "variável negativa": lambda c: c["supervisores"]["lista"][2].update(variavel=-1),
            "bônus abaixo de 100%": lambda c: c["supervisores"].update(bonus=[{"min": 0.95, "pct": 0.02}]),
            "trava acima de 100%": lambda c: c["supervisores"].update(trava=[{"min": 0.9, "pct": 1.5}]),
            "escala vazia": lambda c: c["supervisores"].update(escala_clientes=[]),
            "escala repetida": lambda c: c["supervisores"].update(
                escala_faturamento=[{"min": 1, "pct": 1}, {"min": 1, "pct": 0.5}]),
            "devolução repetida": lambda c: c["supervisores"]["devolucao"].update(
                faixas=[{"ate": 0.01, "pct": 1}, {"ate": 0.01, "pct": 0.9}]),
            "clientes quebrados": lambda c: c["supervisores"].update(metas_mes={"2026-09": {"ronaldo": {"cli": 10.5}}}),
            "mês inválido": lambda c: c["supervisores"].update(metas_mes={"set/26": {"ronaldo": {"cli": 10}}}),
            "supervisor das metas": lambda c: c["supervisores"].update(metas_mes={"2026-09": {"fulano": {"cli": 1}}}),
            "dias sem compra": lambda c: c["supervisores"].update(dias_sem_compra=0),
            "meta padrão negativa": lambda c: c["supervisores"]["lista"][0]["metas_padrao"].update(novos=-1),
            "limite da inadimplência": lambda c: c["supervisores"]["lista"][2]["inadimplencia"].update(limite=2),
        }
        for nome, mudar in erros.items():
            c = padrao()
            mudar(c)
            with self.subTest(nome), self.assertRaises(ValueError):
                _valida(c)

    def test_inadimplencia_desligada(self):
        cfg = padrao()
        cfg["supervisores"]["lista"][2]["inadimplencia"] = None
        cfg["supervisores"]["lista"][0]["inadimplencia"] = {"valor": "300", "limite": "0.004"}
        lista = _valida(cfg)["supervisores"]["lista"]
        self.assertEqual((lista[0]["inadimplencia"], lista[2]["inadimplencia"]), ({"valor": 300, "limite": 0.004}, None))

    def test_versao_1(self):
        v = _valida(V1)
        s = v["supervisores"]
        self.assertEqual(v["versao"], 2)
        self.assertEqual([(x["nome"], x["meta_mix"]) for x in s["lista"]],
                         [("Marcos Vinicius", 0.5), ("Ronaldo", 0.6), ("Valdirene", 0.6)])
        self.assertEqual((s["produtos_fora_mix"], s["dias_inadimplencia"], s["motivos_vencido"]), ([32, 12551], 45, [3, 16]))
        # as metas trocadas do ES valem para os dois supervisores do estado
        self.assertEqual(s["metas_mes"], {"2026-09": {"marcos": {"fat": 2000000}, "ronaldo": {"cli": 990},
                                                      "valdirene": {"cli": 990}}})
        self.assertEqual((v["vendedores"], v["comissao"]), (V1["vendedores"], {"motivos_brindes": [10, 16]}))
        self.assertEqual([x["variavel"] for x in s["lista"]], [6000, 6000, 9000])  # o resto vem do padrão
        sem_supervisores = {k: x for k, x in V1.items() if k != "supervisores"}
        self.assertEqual(_valida(sem_supervisores)["supervisores"], padrao()["supervisores"])
        sem_comissao = {k: x for k, x in V1.items() if k != "comissao"}
        self.assertEqual(_valida(sem_comissao)["comissao"], {"motivos_brindes": [10, 11, 12, 16]})

    def test_comissao_nas_regras(self):
        self.assertEqual(_valida(padrao())["comissao"], {"motivos_brindes": [10, 11, 12, 16]})
        antiga = padrao()
        del antiga["comissao"]  # versão salva antes da aba Comissão
        self.assertEqual(_valida(antiga)["comissao"], {"motivos_brindes": [10, 11, 12, 16]})
        cfg = padrao()
        cfg["comissao"]["motivos_brindes"] = ["16", 12, 16]
        self.assertEqual(_valida(cfg)["comissao"]["motivos_brindes"], [12, 16])
        cfg["comissao"]["motivos_brindes"] = []
        self.assertEqual(_valida(cfg)["comissao"]["motivos_brindes"], [])  # nenhum brinde desconta
        cfg["comissao"]["motivos_brindes"] = ["vencido"]
        with self.assertRaises(ValueError):
            _valida(cfg)


class TestPremiacoes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()

    def montar(self, cfg=None, brindes=True, **kw):
        # Edir com meta de 1 cliente; o 150 com meta 0 fica fora. Um cache novo a cada montagem.
        pasta = Path(tempfile.mkdtemp(dir=self.pasta))
        self.calc = criar_calc(pasta, metas_cli={(SET, EDIR): 1, (SET, 150): 0}, brindes=brindes,
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

    def regras(self, mudar):
        """Troca as regras da página (mudar recebe o padrão e o altera)."""
        cfg = padrao()
        mudar(cfg["supervisores"])
        self.config.cfg = _valida(cfg)

    def cartoes(self, **kw) -> dict:
        return {c["id"]: c for c in self.p.supervisores("2026-09", **kw)["supervisores"]}

    # --- vendedores --------------------------------------------------------------------------
    def test_vendedores(self):
        r = self.montar().calcular("vendedores")
        self.assertEqual((r["mes"]["valor"], r["situacao"], r["abas"]),
                         ("2026-09", "final", ["vendedores", "supervisores", "comissao"]))
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
        self.assertEqual(r["abas"], ["vendedores", "supervisores", "comissao"])
        self.assertEqual(p.calcular("vendedores", None, {BA}, {"BA"})["abas"], ["vendedores", "comissao"])  # só alguns

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
        self.assertEqual([(c["id"], c["estado"]) for c in r["supervisores"]],
                         [("marcos", "BA"), ("ronaldo", "ES"), ("valdirene", "ES")])
        self.assertEqual((r["janela"]["rotulo"], r["corte_vencimento"], r["dias_sem_compra"], r["sem_brindes"]),
                         ("fev/26 a jul/26", "2026-09-01", 60, False))
        self.assertEqual([m["id"] for m in r["motivos_vencido"]], [3, 16])
        marcos, ronaldo, valdirene = r["supervisores"]
        self.assertEqual([x["id"] for x in marcos["indicadores"]], ["faturamento", "positivacao", "novos", "reativacao"])
        self.assertEqual([x["id"] for x in valdirene["indicadores"]],
                         ["faturamento", "mix", "positivacao", "novos", "reativacao"])
        # ES: vendas 1.500 (o funcionário 7 fica fora); desconta só a devolução de motivo 1 (100): a de vencido (50) e
        # os brindes não descontam. Vencido = 50 da devolução + 30 do brinde (a degustação e agosto ficam fora).
        k = ronaldo["contas"]
        self.assertEqual((k["vendas"], k["devolucoes"], k["liquido"]), (1500, 100, 1400))
        self.assertEqual((k["dev_vencido"], k["brindes_vencido"], k["vencido"]), (50, 30, 80))
        self.assertAlmostEqual(k["indice_vencido"], 80 / 1500)
        self.assertNotIn("pct_mix", k)  # o Ronaldo não tem mix
        self.assertEqual((valdirene["contas"]["liquido_mix"], valdirene["contas"]["liquido"]), (500, 1400))
        self.assertAlmostEqual(ind(valdirene, "mix")["realizado"], 500 / 1400)
        # positivação: clientes 1 e 3. Reativação: só o 1, que já tinha comprado antes das vendas do cache (o título de
        # venda de 05/09/2025; as vendas do cache começam em jan/26; os títulos de depois não contam); o 3 nunca tinha
        # comprado. Nenhum cadastro novo.
        self.assertEqual((k["positivacao"], k["novos"], k["reativacoes"]), (2, 0, 1))
        self.assertEqual([(c["nome"], c["anterior"], c["dias"], c["antes_das_vendas"])
                          for c in ronaldo["clientes"]["reativacoes"]], [("MERCADO DO JOAO", "2025-09-05", 362, True)])
        # metas: faturamento e clientes da soma dos vendedores, novos e reativação do padrão
        self.assertEqual([(x["id"], x["meta"]) for x in ronaldo["indicadores"]],
                         [("faturamento", 2000), ("positivacao", 3), ("novos", 40), ("reativacao", 20)])
        self.assertEqual((ind(ronaldo, "faturamento")["alcance"], ronaldo["trava"]["pct"], ronaldo["premio"]), (0.7, 0, 0))
        # BA: 5.400 de vendas − 250 de devolução (a cancelada fica fora); o cliente 2 voltou depois de 24 dias
        k = marcos["contas"]
        self.assertEqual((k["vendas"], k["liquido"], k["vencido"], k["indice_vencido"], k["reativacoes"]),
                         (5400, 5150, 0, 0, 0))
        self.assertAlmostEqual(ind(marcos, "faturamento")["alcance"], 5150 / 6000)
        self.assertEqual([v["id"] for v in marcos["vendedores"]], [BA])  # o Edir (terceiros) fica fora
        self.assertFalse(any("sem meta" in a for a in r["avisos"]))

    def test_conta_completa(self):
        p = self.montar()
        # um cliente novo no ES: cadastrado em 20/09, comprou R$ 100 em 21/09
        self.acrescentar(*cliente(20, ES, D(2026, 9, 20), [D(2026, 9, 21)]))
        self.regras(lambda s: s.update(metas_mes={"2026-09": {
            "valdirene": {"fat": 1500, "cli": 3, "novos": 1, "reativacao": 1},
            "marcos": {"fat": 5000, "cli": 1, "novos": 1, "reativacao": 1}}}))
        c = self.cartoes()
        v, ronaldo, marcos = c["valdirene"], c["ronaldo"], c["marcos"]
        # ES: vendas 1.600, líquido 1.500 (100%), mix 600 ÷ 1.500 = 40% (73% de 55%: nada), positivação 3,
        # 1 novo, 1 reativação; vencido 80 ÷ 1.600 = 5%: mantém 90%; inadimplência zero: + R$ 450
        self.assertEqual([(x["id"], x["pct"], x["parcela"]) for x in v["indicadores"]],
                         [("faturamento", 1.0, 3150), ("mix", 0, 0), ("positivacao", 1.0, 1350), ("novos", 1.0, 1350),
                          ("reativacao", 1.0, 1350)])
        self.assertEqual((v["conquistado"], v["trava"]["valor"], v["bonus"]["pct"], v["devolucao"]["pct"],
                          v["devolucao"]["total"], v["adicional"]["valor"], v["premio"]),
                         (7200, 7200, 0, 0.9, 6480, 450, 6930))  # 100% exato: sem bônus
        self.assertEqual((ind(v, "novos")["meta"], ind(v, "novos")["meta_auto"], ind(v, "novos")["ajustada"]), (1, 40, True))
        self.assertEqual([c["nome"] for c in v["clientes"]["novos"]], ["CLIENTE 20"])
        # o Ronaldo, na mesma carteira, fica com as metas automáticas: 1.500 de 2.000 = 75%, a trava zera
        self.assertEqual((ind(ronaldo, "faturamento")["meta"], ronaldo["premio"]), (2000, 0))
        # BA: 5.150 de 5.000 = 103% (100% e bônus de 2%), positivação 1 de 1, sem novos nem reativações
        self.assertEqual([(x["id"], x["parcela"]) for x in marcos["indicadores"]],
                         [("faturamento", 1800), ("positivacao", 1500), ("novos", 0), ("reativacao", 0)])
        self.assertEqual((marcos["conquistado"], marcos["bonus"]["pct"], marcos["devolucao"]["pct"], marcos["premio"]),
                         (3300, 0.02, 1.0, 3366))
        self.assertIsNone(marcos["adicional"])

    def test_liquido_pelas_regras_da_meta(self):
        p = self.montar(fora=(999,))
        c = self.cartoes()
        # o produto 999 marcado "fora" das metas sai das vendas e do líquido
        self.assertEqual((c["marcos"]["contas"]["vendas"], c["marcos"]["contas"]["liquido"]), (5000, 4750))
        metas = padrao_metas()
        metas["produtos"]["999"] = {"grupo": "fora", "categoria": None}
        metas["devolucoes"] = {"motivos": [1, 2, 3, 5, 6, 7, 8, 9], "ignorar_canceladas": False}
        self.calc.configuracao = ConfiguracaoFixa(metas)
        c = self.cartoes()
        self.assertEqual(c["ronaldo"]["contas"]["liquido"], 1350)  # com o motivo 3 nas regras da meta
        self.assertEqual(c["marcos"]["contas"]["liquido"], 5000 - 250 - 500)  # a cancelada desconta, como na meta
        self.assertTrue(p.supervisores("2026-09")["canceladas_descontam"])

    def test_mix_com_equivalencia(self):
        self.montar()
        self.regras(lambda s: s.update(produtos_fora_mix=[11469]))  # a venda do 3643 vira 11469
        k = self.cartoes()["valdirene"]["contas"]
        self.assertEqual(k["liquido_mix"], (1500 - 200) - 100)
        self.assertAlmostEqual(k["pct_mix"], 1200 / 1400)

    def test_vencido(self):
        self.montar()
        self.regras(lambda s: s.update(motivos_vencido=[3]))
        k = self.cartoes()["ronaldo"]["contas"]
        self.assertEqual((k["vencido"], k["brindes_vencido"]), (50, 0))
        self.calc.cache._con.close()
        r = self.montar(brindes=False).supervisores("2026-09")
        k = r["supervisores"][1]["contas"]
        self.assertEqual((r["sem_brindes"], k["vencido"]), (True, 50))
        self.assertTrue(any("brindes" in a for a in r["avisos"]))

    def test_novos(self):
        self.montar()
        self.acrescentar(
            *cliente(20, ES, D(2026, 9, 20), [D(2026, 9, 21)]),                 # conta
            *cliente(21, ES, D(2026, 9, 25), [D(2026, 9, 26)], inativo=1),      # conta, mesmo inativo hoje
            *cliente(22, ES, D(2026, 9, 28)),                                   # sem compra no mês
            *cliente(23, ES, D(2026, 8, 30), [D(2026, 9, 2)]),                  # cadastrado no mês anterior
            *cliente(24, EDIR, D(2026, 9, 10), [D(2026, 9, 11)]),               # carteira do Edir
            *cliente(25, 0, D(2026, 9, 10), [D(2026, 9, 11)], vendedor_da_venda=ES),  # sem vendedor na carteira
            *cliente(26, BA, D(2026, 9, 3), [D(2026, 9, 3)]),                   # BA, no mesmo dia
        )
        c = self.cartoes()
        novos = c["ronaldo"]["clientes"]["novos"]
        self.assertEqual([(x["nome"], x["cadastro"], x["compra"], x["inativo"]) for x in novos],
                         [("CLIENTE 20", "2026-09-20", "2026-09-21", False), ("CLIENTE 21", "2026-09-25", "2026-09-26", True)])
        self.assertEqual((c["ronaldo"]["contas"]["novos"], c["marcos"]["contas"]["novos"]), (2, 1))
        self.assertEqual(c["valdirene"]["contas"]["novos"], 2)  # o mesmo número para os dois do ES
        # o 23 não conta como reativação: cadastrado depois do início dos dados, comprou pela primeira vez
        self.assertNotIn("CLIENTE 23", [x["nome"] for x in c["ronaldo"]["clientes"]["reativacoes"]])

    def test_reativacao(self):
        self.montar()
        titulo = "INSERT INTO titulos_receber VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        self.acrescentar(
            (VENDA, [(D(2026, 7, 4), ES, 1, "CLIENTE", 1), (D(2026, 7, 18), ES, 3, "CLIENTE", 1)]),
            *cliente(30, BA, D(2025, 3, 1), [D(2026, 6, 1), D(2026, 9, 5), D(2026, 9, 20)]),  # 96 dias; conta uma vez
            *cliente(31, BA, D(2025, 3, 1), [D(2026, 7, 20), D(2026, 9, 25)]),  # 67 dias até a compra (43 até o dia 1º)
            *cliente(32, BA, D(2015, 5, 5), [D(2026, 9, 10)]),  # nunca tinha comprado (sem venda nem título): não conta
            *cliente(33, BA, D(2026, 3, 1), [D(2026, 9, 12)]),  # cadastrado depois do início: 1ª compra, não conta
            *cliente(34, BA, D(2015, 5, 5), [D(2026, 9, 15)]),  # comprou antes das vendas do cache (o título de 2025)
            *cliente(35, BA, D(2025, 3, 1), [D(2026, 9, 18)]),  # só um título de depois do início: não é compra anterior
            (titulo, [(950, 34, BA, D(2025, 6, 1), D(2025, 6, 29), D(2025, 6, 29), 1, 300.0),
                      (951, 35, BA, D(2026, 3, 1), D(2026, 3, 29), D(2026, 3, 29), 1, 300.0)]),
        )
        c = self.cartoes()
        # ES: o cliente 1 voltou depois de exatamente 60 dias (04/07 a 02/09); o 3, de 59 (18/07 a 15/09): não conta
        self.assertEqual([(x["nome"], x["data"], x["dias"]) for x in c["ronaldo"]["clientes"]["reativacoes"]],
                         [("MERCADO DO JOAO", "2026-09-02", 60)])
        self.assertEqual([(x["nome"], x["anterior"], x["data"], x["dias"], x["antes_das_vendas"])
                          for x in c["marcos"]["clientes"]["reativacoes"]],
                         [("CLIENTE 30", "2026-06-01", "2026-09-05", 96, False),
                          ("CLIENTE 34", "2025-06-01", "2026-09-15", 471, True),
                          ("CLIENTE 31", "2026-07-20", "2026-09-25", 67, False)])
        self.assertEqual((c["marcos"]["contas"]["reativacoes"], c["valdirene"]["contas"]["reativacoes"]), (3, 1))
        self.regras(lambda s: s.update(dias_sem_compra=59))
        self.assertEqual(self.cartoes()["ronaldo"]["contas"]["reativacoes"], 2)
        # Sem os títulos no cache, só as vendas: o 1 do cache sintético, que só tinha o título de 2025, não aparece.
        self.calc.cache._con.close()
        r = self.montar(credito=False).supervisores("2026-09")
        self.assertEqual(r["supervisores"][1]["contas"]["reativacoes"], 0)
        self.assertTrue(any("na reativação" in a for a in r["avisos"]))

    def test_inadimplencia(self):
        p = self.montar()
        titulo = "INSERT INTO titulos_receber VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        self.acrescentar(
            ("INSERT INTO vendas_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?)",
             [(D(2026, 3, 10), ES, 1, "CLIENTE", 27, 10000.0, 10.0)]),
            ("INSERT INTO devolucoes_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
             [(D(2026, 3, 12), ES, 1, "CLIENTE", 27, 3, False, 500.0, 1.0)]),  # vencido: não desconta da base
            (titulo, [
                (901, 1, ES, D(2026, 3, 10), D(2026, 4, 10), None, 0, 40.0),     # em aberto e vencido: conta
                (902, 1, ES, D(2026, 7, 25), D(2026, 9, 5), None, 0, 500.0),     # vence depois de 01/09: fora
                (903, 1, ES, D(2026, 8, 2), D(2026, 8, 10), None, 0, 500.0),     # emitido fora da janela
                (904, 1, ES, D(2026, 3, 1), D(2026, 3, 5), D(2026, 3, 20), 1, 800.0),  # pago
            ]))
        self.regras(lambda s: s.update(metas_mes={"2026-09": {"valdirene": {"fat": 1400}}}))
        v = self.cartoes()["valdirene"]
        self.assertEqual((v["contas"]["inadimplente"], v["contas"]["liquido_6m"]), (40, 10000))
        self.assertAlmostEqual(v["contas"]["indice_inadimplencia"], 0.004)
        self.assertEqual((v["adicional"]["pago"], v["adicional"]["valor"], v["trava"]["pct"]), (True, 450, 1.0))
        self.assertNotIn("inadimplente", self.cartoes()["ronaldo"]["contas"])
        self.regras(lambda s: (s.update(metas_mes={"2026-09": {"valdirene": {"fat": 1400}}}),
                               s["lista"][2]["inadimplencia"].update(limite=0.003)))
        v = self.cartoes()["valdirene"]
        self.assertEqual((v["adicional"]["pago"], v["adicional"]["motivo"]), (False, "acima"))
        self.regras(lambda s: None)  # sem o ajuste: 1.400 de 2.000, a trava zera e o adicional não é pago
        v = self.cartoes()["valdirene"]
        self.assertEqual((v["adicional"]["motivo"], v["premio"]), ("trava", 0))
        self.calc.cache._con.close()
        r = self.montar(credito=False).supervisores("2026-09")
        v = r["supervisores"][2]
        self.assertEqual((v["contas"]["indice_inadimplencia"], v["adicional"]["motivo"]), (None, "trava"))
        self.assertTrue(any("títulos a receber" in a for a in r["avisos"]))

    def test_metas(self):
        p = self.montar()
        self.regras(lambda s: (s.update(metas_mes={"2026-09": {"ronaldo": {"novos": 5, "reativacao": 0, "cli": 2}}}),
                               s["lista"][0]["metas_padrao"].update(novos=None)))
        r = p.supervisores("2026-09")
        c = {x["id"]: x for x in r["supervisores"]}
        novos = ind(c["ronaldo"], "novos")
        self.assertEqual((novos["meta"], novos["meta_auto"], novos["ajustada"]), (5, 40, True))
        reat = ind(c["ronaldo"], "reativacao")
        self.assertEqual((reat["meta"], reat["sem_meta"], reat["alcance"], reat["parcela"]), (0, True, None, 0))  # 0 = sem meta
        self.assertEqual((ind(c["ronaldo"], "positivacao")["meta"], ind(c["valdirene"], "positivacao")["meta"]), (2, 3))
        self.assertTrue(ind(c["marcos"], "novos")["sem_meta"])
        self.assertTrue(any(a.startswith("Ronaldo: sem meta de reativação de clientes") for a in r["avisos"]))
        self.assertTrue(any(a.startswith("Marcos: sem meta de ativação de clientes novos") for a in r["avisos"]))
        self.assertEqual(p.config_dados("2026-09")["automatico"],
                         {"marcos": {"fat": 6000, "cli": 2}, "ronaldo": {"fat": 2000, "cli": 3},
                          "valdirene": {"fat": 2000, "cli": 3}})

    def test_supervisores_do_acesso(self):
        p = self.montar()
        self.assertEqual(p.estados_supervisor(None, None), ["BA", "ES"])
        self.assertEqual(p.estados_supervisor(None, {"ES", "EDIR"}), ["ES"])
        self.assertEqual(p.estados_supervisor({ES}, None), [])
        self.assertEqual([c["id"] for c in p.calcular("supervisores", None, None, {"BA", "EDIR"})["supervisores"]],
                         ["marcos"])
        self.assertEqual([c["id"] for c in p.calcular("supervisores", None, None, {"ES"})["supervisores"]],
                         ["ronaldo", "valdirene"])
        with self.assertRaises(PermissionError):
            p.calcular("supervisores", None, {ES}, {"ES"})
        with self.assertRaises(PermissionError):
            p.calcular("supervisores", None, None, {"EDIR"})

    def test_abas_e_supervisores_liberados_para_a_pessoa(self):
        p = self.montar()
        # só o quadro liberado (o Ronaldo), com os mesmos números de quando todos aparecem
        r = p.calcular("supervisores", "2026-09", None, None, ["vendedores", "supervisores"], ["ronaldo"])
        self.assertEqual(([c["id"] for c in r["supervisores"]], r["abas"]), (["ronaldo"], ["vendedores", "supervisores"]))
        todos = self.cartoes()
        self.assertEqual((r["supervisores"][0]["premio"], r["supervisores"][0]["contas"]),
                         (todos["ronaldo"]["premio"], todos["ronaldo"]["contas"]))
        self.assertEqual([c["id"] for c in p.calcular("supervisores", "2026-09", None, None, None,
                                                      ["valdirene", "marcos"])["supervisores"]], ["marcos", "valdirene"])
        # sem aba no pedido: a primeira do acesso
        self.assertEqual(p.calcular(None, "2026-09", None, None, ["supervisores"], ["valdirene"])["aba"], "supervisores")
        self.assertEqual(p.calcular(None, "2026-09")["aba"], "vendedores")
        # aba fora do acesso (a comissão nem chega a ser calculada)
        for aba in ("supervisores", "comissao"):
            with self.subTest(aba=aba), self.assertRaises(PermissionError):
                p.calcular(aba, "2026-09", None, None, ["vendedores"], [])
        with self.assertRaises(PermissionError) as e:  # nada escolhido ainda
            p.calcular(None, "2026-09", None, None, [], [])
        self.assertIn("nenhuma aba", str(e.exception))
        # o Marcos é da BA: com só a equipe do ES, o quadro dele não aparece, e a aba some
        r = p.calcular("vendedores", "2026-09", None, {"ES"}, ["vendedores", "supervisores"], ["marcos"])
        self.assertEqual(r["abas"], ["vendedores"])
        with self.assertRaises(PermissionError) as e:
            p.calcular("supervisores", "2026-09", None, {"ES"}, ["vendedores", "supervisores"], ["marcos"])
        self.assertIn("aba Supervisores", str(e.exception))
        # com só alguns vendedores, a aba dos supervisores não aparece mesmo liberada
        with self.assertRaises(PermissionError) as e:
            p.calcular("supervisores", "2026-09", {ES}, None, ["vendedores", "supervisores"], ["ronaldo"])
        self.assertIn("carteira inteira do estado", str(e.exception))

    @unittest.skipUnless(TEM_FPDF and TEM_PYPDF, "precisa do fpdf2 e do pypdf")
    def test_pdf_das_tabelas(self):
        p = self.montar()
        conteudo, nome = p.pdf("vendedores", "2026-09")
        self.assertEqual((conteudo[:5], nome), (b"%PDF-", "Premiação dos vendedores - Setembro de 2026.pdf"))
        texto = texto_pdf(conteudo)
        for trecho in ("Premiação dos vendedores · Setembro de 2026", "Mês fechado", "Rubens", "Thais", "R$ 700,00",
                       "faixa máxima", "falta 1 cliente para R$ 200,00", "a partir de 91% da meta: R$ 200,00", "2 de 3"):
            self.assertIn(trecho, texto)
        # os supervisores: só os quadros liberados, com a tabela dos indicadores
        conteudo, nome = p.pdf("supervisores", "2026-09", None, None, ["supervisores"], ["ronaldo", "marcos"])
        texto = texto_pdf(conteudo)
        self.assertEqual(nome, "Premiação dos supervisores - Setembro de 2026.pdf")
        for trecho in ("Marcos · BA", "Ronaldo · ES", "Faturamento líquido", "Parcelas conquistadas", "A receber"):
            self.assertIn(trecho, texto)
        self.assertNotIn("Valdirene", texto)
        # o mesmo acesso da página: aba fora dele não sai em PDF
        with self.assertRaises(PermissionError):
            p.pdf("supervisores", "2026-09", None, None, ["vendedores"], [])
        # sem ninguém na tabela, o PDF diz isso
        self.assertIn("Nenhum vendedor do seu acesso", texto_pdf(p.pdf("vendedores", "2026-09", {999})[0]))

    def test_regras_da_versao_1(self):
        p = self.montar(V1)  # salvas antes dos regulamentos novos: as três abas abrem
        self.assertEqual(len(p.vendedores()["vendedores"]), 3)
        c = self.cartoes()
        self.assertEqual((c["marcos"]["nome"], ind(c["marcos"], "faturamento")["meta"]), ("Marcos Vinicius", 2000000))
        self.assertEqual((ind(c["ronaldo"], "positivacao")["meta"], ind(c["valdirene"], "positivacao")["meta"]), (990, 990))

    def test_config_dados(self):
        c = self.montar().config_dados()
        self.assertEqual((c["mes"]["valor"], c["config"], c["padrao"]), ("2026-09", _valida(padrao()), padrao()))
        self.assertIn({"id": 3, "nome": "VENCIDO"}, c["motivos"])
        produtos = {p["id"]: p["nome"] for p in c["produtos"]}
        self.assertEqual(produtos[32], "QUEIJO MUSSARELA 4KG")
        self.assertIn(12551, produtos)  # na lista, mesmo sem venda


class TestComissao(unittest.TestCase):
    """Setembro/26: o Rubens (ES) e a Thais (BA). Devoluções do cache sintético: ES 100 de mussarela (motivo 1) e 50 de
    manteiga (motivo 3), BA 250 de mussarela (e 500 cancelada)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()

    def montar(self, cfg=None, comissao=True, brindes=True):
        pasta = Path(tempfile.mkdtemp(dir=self.pasta))  # um cache novo a cada montagem
        self.calc = criar_calc(pasta, brindes=brindes, linhas_brindes=[*BRINDES, BRINDE_SEM_PCT] if brindes else (),
                               comissao=comissao, linhas_comissao=COMISSAO_VENDAS, percentuais=PERCENTUAIS)
        self.p = Premiacoes(self.calc, ConfigFixa(cfg), lambda: {ES: "Rubens", BA: "Thais", EDIR: "Edir"})
        return self.p

    def test_comissao(self):
        r = self.montar().calcular("comissao", "2026-09")
        self.assertEqual((r["aba"], r["situacao"], r["abas"]), ("comissao", "final", ["vendedores", "supervisores", "comissao"]))
        linhas = {v["id"]: v for v in r["vendedores"]}
        self.assertEqual(set(linhas), {ES, BA})  # o Edir e o terceiro ficam fora
        es, ba = linhas[ES], linhas[BA]
        # ES: a comissão gravada (10 + 0 + 4), não a tabela de hoje; o funcionário fica fora
        self.assertEqual((es["estado"], es["vendido"], es["comissao_vendas"]), ("ES", 1500, 14))
        self.assertAlmostEqual(es["pct"], 14 / 1500)
        # devoluções de todos os motivos × % de hoje: 100 × 2% + 50 × 3%; brinde vencido 30 × 3% (a degustação não conta)
        self.assertEqual((es["devolvido"], es["desc_devolucoes"], es["brindes"], es["desc_brindes"], es["a_pagar"]),
                         (150, 3.5, 30, 0.9, 9.6))
        prod = {p["id"]: p for p in es["produtos"]}
        self.assertEqual([p["id"] for p in es["produtos"]], [32, 3643, 27])  # pela comissão
        self.assertEqual((prod[32]["pct"], prod[32]["pct_tabela"], prod[32]["liquido"]), (0.01, 0.02, 8))
        self.assertAlmostEqual(prod[27]["liquido"], -2.4)  # vendida sem comissão e devolvida a 3%
        self.assertEqual((prod[3643]["pct_tabela"], prod[3643]["sem_pct"]), (None, False))  # sem desconto a fazer
        # BA: a devolução cancelada não conta; o brinde do produto sem % na tabela não desconta
        self.assertEqual((ba["vendido"], ba["comissao_vendas"], ba["desc_devolucoes"], ba["brindes"], ba["desc_brindes"],
                          ba["a_pagar"], ba["sem_pct"]), (5400, 75, 3.75, 40, 0, 71.25, 40))
        self.assertTrue(next(p for p in ba["produtos"] if p["id"] == 999)["sem_pct"])
        t = r["total"]
        self.assertEqual((t["vendido"], t["comissao_vendas"], t["desc_devolucoes"], t["desc_brindes"], t["a_pagar"],
                          t["vendedores"]), (6900, 89, 7.25, 0.9, 80.85, 2))
        self.assertEqual(r["por_estado"], [{"estado": "BA", "vendedores": 1, "a_pagar": 71.25},
                                           {"estado": "ES", "vendedores": 1, "a_pagar": 9.6}])
        self.assertEqual([m["id"] for m in r["motivos_brindes"]], [10, 11, 12, 16])
        self.assertTrue(any("R$ 40,00" in a and "não descontam" in a for a in r["avisos"]))

    def test_motivos_dos_brindes(self):
        cfg = padrao()
        cfg["comissao"]["motivos_brindes"] = [16, 26]  # vencido e degustação
        es = next(v for v in self.montar(cfg).comissao("2026-09")["vendedores"] if v["id"] == ES)
        self.assertEqual((es["brindes"], es["desc_brindes"]), (50, 1.3))  # 30 × 3% + 20 × 2%
        self.calc.cache._con.close()
        cfg["comissao"]["motivos_brindes"] = []
        es = next(v for v in self.montar(cfg).comissao("2026-09")["vendedores"] if v["id"] == ES)
        self.assertEqual((es["brindes"], es["desc_brindes"], es["a_pagar"]), (0, 0, 10.5))

    def test_comissao_do_acesso(self):
        p = self.montar()
        self.assertEqual([v["id"] for v in p.comissao("2026-09", {BA})["vendedores"]], [BA])
        self.assertEqual([v["id"] for v in p.comissao("2026-09", None, {"ES", "EDIR"})["vendedores"]], [ES])
        self.assertEqual(p.comissao("2026-09", None, {"EDIR"})["vendedores"], [])
        self.assertEqual(p.calcular("comissao", "2026-09", {ES}, {"ES"})["abas"], ["vendedores", "comissao"])

    def test_meses(self):
        p = self.montar()
        r = p.comissao("2026-08")  # sem META CLIENTE em agosto: a comissão vale assim mesmo
        # o Rubens não vendeu em agosto, mas o brinde vencido de 70 × 3% desconta
        self.assertEqual([(v["id"], v["comissao_vendas"], v["a_pagar"]) for v in r["vendedores"]],
                         [(ES, 0, -2.1), (BA, 60, 60)])
        self.assertEqual(r["meses"][0]["valor"], "2026-09")
        self.assertEqual(r["meses"][-1]["valor"], "2026-01")  # do início dos dados
        self.assertEqual(p.comissao()["mes"]["valor"], "2026-09")  # o mês dos dados
        with self.assertRaises(ValueError):
            p.comissao("2026-10")
        with self.assertRaises(ValueError):
            p.vendedores("2026-08")  # a aba Vendedores segue só com os meses com meta

    def test_a_pagar_negativo(self):
        p = self.montar()
        cache = self.calc.cache
        cache._con.close()
        con = duckdb.connect(str(cache.arquivo))
        con.execute("INSERT INTO devolucoes_clientes_itens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [D(2026, 9, 25), ES, 1, "CLIENTE", 32, 2, False, 1000.0, 1.0])
        con.close()
        cache._abrir()
        es = next(v for v in p.comissao("2026-09")["vendedores"] if v["id"] == ES)
        self.assertEqual((es["desc_devolucoes"], es["a_pagar"]), (23.5, -10.4))  # 3,5 + 1000 × 2%; 14 − 23,5 − 0,9

    @unittest.skipUnless(TEM_FPDF and TEM_PYPDF, "precisa do fpdf2 e do pypdf")
    def test_pdf_da_comissao(self):
        conteudo, nome = self.montar().pdf("comissao", "2026-09")
        self.assertEqual(nome, "Comissão dos vendedores - Setembro de 2026.pdf")
        texto = texto_pdf(conteudo)
        for trecho in ("Comissão dos vendedores · Setembro de 2026", "Rubens", "Thais", "R$ 80,85", "R$ 71,25",
                       "BA: 1 vendedor, R$ 71,25", "Observações", "não descontam"):
            self.assertIn(trecho, texto)
        self.assertNotIn("3643", texto)  # nada de código de produto
        # os brindes que descontam, pelo nome (como na página), nunca pelo código do motivo
        self.assertEqual(premiacoes_pdf.rotulo_brindes([{"id": 10, "nome": "BRINDE - DANIFICADO, PROBLEMA NA PRODUÇÃO"},
                                                        {"id": 16, "nome": "BRINDE - VENCIDO"}]), "danificados e vencidos")
        self.assertEqual(premiacoes_pdf.rotulo_brindes([{"id": 16, "nome": "BRINDE - VENCIDO"},
                                                        {"id": 26, "nome": "BRINDE - DEGUSTAÇÃO"}]),
                         "dos motivos vencido e degustação")

    def test_sem_comissao_ou_sem_brindes(self):
        with self.assertRaises(RuntimeError):
            self.montar(comissao=False).comissao("2026-09")
        self.calc.cache._con.close()
        r = self.montar(brindes=False).comissao("2026-09")
        es = next(v for v in r["vendedores"] if v["id"] == ES)
        self.assertTrue(r["sem_brindes"])
        self.assertEqual((es["desc_brindes"], es["a_pagar"]), (0, 10.5))
        self.assertTrue(any("brindes ainda não chegaram" in a for a in r["avisos"]))


class TestConfigNoBanco(BaseBanco):
    def test_grava_versoes(self):
        cfg = ConfigPremiacoes(self.banco)
        self.assertEqual(cfg.atual(), _valida(padrao()))
        uid = self.criar_usuario("admin2", "admin")
        novo = padrao()
        novo["supervisores"]["metas_mes"] = {"2026-10": {"ronaldo": {"cli": 990, "novos": 35}}}
        cfg.salvar(novo, {"id": uid, "nome": "Admin2"})
        self.assertEqual(ConfigPremiacoes(self.banco).atual()["supervisores"]["metas_mes"],
                         {"2026-10": {"ronaldo": {"cli": 990, "novos": 35}}})
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT nome, salva_por_nome, dados->>'versao' FROM regras").fetchall(),
                             [("premiacoes", "Admin2", "2")])
        ruim = padrao()
        ruim["supervisores"]["lista"][1]["pesos"]["faturamento"] = 0.5
        with self.assertRaises(ValueError):
            cfg.salvar(ruim)

    def test_versao_1_salva(self):
        antiga = copy.deepcopy(V1)
        del antiga["comissao"]  # e de antes da aba Comissão
        with self.banco.conexao() as con:
            con.execute("INSERT INTO regras (nome, dados) VALUES ('premiacoes', %s::jsonb)", [json.dumps(antiga)])
        cfg = ConfigPremiacoes(self.banco)
        atual = cfg.atual()
        self.assertEqual((atual["versao"], atual["comissao"], atual["supervisores"]["lista"][0]["nome"]),
                         (2, {"motivos_brindes": [10, 11, 12, 16]}, "Marcos Vinicius"))
        self.assertEqual(atual["supervisores"]["metas_mes"]["2026-09"]["valdirene"], {"cli": 990})
        cfg.salvar(atual)  # salvar grava no formato novo
        with self.banco.conexao() as con:
            versoes = [r[0] for r in con.execute("SELECT dados->>'versao' FROM regras ORDER BY id").fetchall()]
        self.assertEqual(versoes, ["1", "2"])


if __name__ == "__main__":
    unittest.main()

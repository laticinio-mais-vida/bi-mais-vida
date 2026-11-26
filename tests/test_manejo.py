"""Manejo da Base (bi/manejo.py): as regras da campanha, o prazo, os fatos lidos do cache, a atualização da lista do
mês, as justificativas, os vereditos e as rotas."""
from __future__ import annotations

import http.client
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
try:
    import pypdf
except ImportError:  # o PDF é lido de volta só onde o pacote existe
    pypdf = None

import app
from bi.banco import BancoForaDoAr
from bi.calendario import Calendario
from bi.conversas import NaoEncontrada
from bi.manejo import PADRAO, ConfigManejo, Manejo, _valida, avaliar, prazo_do_mes
from tests.apoio import BA, ES, BaseBanco, D, criar_calc
from tests.test_arquivos import TEM_PDF, TEM_XLSX, ler_excel

DIA = D(2026, 10, 1)              # o dia da cópia do ERP no cache de teste
INICIO = D(2026, 8, 1)            # o primeiro dia do histórico da carteira no teste
CENTRAL_BA, CENTRAL_ES = BA, 140  # 141 "THAIS - CENTRAL" e a Lorena
JAMILLE, TERCEIRO = 98, 61        # vendedora da BA fora da central; um terceiro (fora das equipes do ES e da BA)
NOMES = {ES: "Rubens", BA: "Thais", JAMILLE: "Jamille", CENTRAL_ES: "Lorena", TERCEIRO: "Franquelin"}
DO_ES, DA_BA = frozenset({ES, CENTRAL_ES}), frozenset({JAMILLE, CENTRAL_BA})  # os vendedores do acesso de cada supervisor
VENDEDORES = [(JAMILLE, "JAMILLE - PS", 7, "MARCOS", 0), (CENTRAL_ES, "LORENA - CENTRAL - ES", 3, "VALDIRENE", 0),
              (TERCEIRO, "FRANQUELIN - ITABELA", 8, "TERC", 0)]
# (id, nome, vendedor, cidade, UF, inativo, cadastro). No dia 01/10/2026:
CLIENTES = [
    (20, "MERCADO TRINTA (CLIENTE 20)", ES, "SERRA", "ES", 0, D(2020, 1, 1)),        # semanal, 30 dias: central
    (21, "MERCADO VINTE E NOVE", ES, "SERRA", "ES", 0, D(2020, 1, 1)),               # semanal, 29 dias: ainda não
    (22, "MENSAL QUARENTA E NOVE", ES, "SERRA", "ES", 0, D(2020, 1, 1)),             # mensal, 49 dias: ainda não
    (23, "MENSAL CINQUENTA", ES, "SERRA", "ES", 0, D(2020, 1, 1)),                   # mensal, 50 dias: central
    (24, "LOJA DA REDE", JAMILLE, "PORTO SEGURO", "BA", 0, D(2020, 1, 1)),           # rede com nome = semanal: central
    (25, "NUNCA COMPROU", JAMILLE, "PORTO SEGURO", "BA", 0, D(2026, 3, 1)),          # conta do cadastro: central
    (26, "COMPROU ANTES DO CACHE", ES, "SERRA", "ES", 0, D(2019, 1, 1)),             # conta do último título: central
    (27, "CLIENTE DO TERCEIRO", TERCEIRO, "ITABELA", "BA", 0, D(2020, 1, 1)),        # vendedor fora da campanha
    (28, "INADIMPLENTE CENTO E VINTE", JAMILLE, "PORTO SEGURO", "BA", 0, D(2020, 1, 1)),   # 120 dias: inativar
    (29, "INADIMPLENTE CENTO E DEZENOVE", JAMILLE, "PORTO SEGURO", "BA", 0, D(2020, 1, 1)),  # 119 dias: ainda não
    (30, "SEM COMPRA E INADIMPLENTE", ES, "SERRA", "ES", 0, D(2020, 1, 1)),          # os dois: só inativar
    (31, "DA CENTRAL HA TEMPO", CENTRAL_BA, "EUNAPOLIS", "BA", 0, D(2020, 1, 1)),    # 61 dias na central: inativar
    (32, "CHEGOU NA CENTRAL AGORA", CENTRAL_BA, "EUNAPOLIS", "BA", 0, D(2020, 1, 1)),  # 21 dias na central: ainda não
    (33, "DA CENTRAL QUE COMPROU", CENTRAL_ES, "VITORIA", "ES", 0, D(2020, 1, 1)),   # comprou há 26 dias: ainda não
    (34, "TROCOU DENTRO DA CENTRAL", CENTRAL_ES, "VITORIA", "ES", 0, D(2020, 1, 1)),  # o bloco da central continua
    (35, "REATIVADO", ES, "SERRA", "ES", 0, D(2020, 1, 1)),                          # reativado há 6 dias: ainda não
    (36, "PEDIDO BLOQUEDO (RUBENS)", ES, "SERRA", "ES", 0, D(2020, 1, 1)),           # fictício, com o erro de digitação
    (37, "INATIVO", ES, "SERRA", "ES", 1, D(2020, 1, 1)),
]
CENTRAL, INATIVAR = {20, 23, 24, 25, 26}, {28, 30, 31, 34}  # quem cai em cada lista no dia 01/10


def venda(dia, cliente, vendedor=ES, tipo="CLIENTE"):
    return (dia, vendedor, cliente, tipo, 32, 100.0, 5.0)


VENDAS = [venda(D(2026, 9, 1), 20), venda(D(2026, 9, 2), 21), venda(D(2026, 8, 13), 22), venda(D(2026, 8, 12), 23),
          venda(D(2026, 8, 20), 24, JAMILLE), venda(D(2026, 7, 1), 27, TERCEIRO), venda(D(2026, 9, 25), 28, JAMILLE),
          venda(D(2026, 9, 25), 29, JAMILLE), venda(D(2026, 8, 1), 30), venda(D(2026, 7, 20), 31, CENTRAL_BA),
          venda(D(2026, 7, 20), 32), venda(D(2026, 9, 5), 33, CENTRAL_ES), venda(D(2026, 7, 10), 34, CENTRAL_BA),
          venda(D(2026, 3, 1), 35), venda(D(2026, 6, 1), 37),
          venda(D(2026, 9, 30), 25, ES, "FUNCIONARIO")]  # o código 25 de outro cadastro: não é compra do cliente 25
# (id, cliente, vendedor do título, emissão, vencimento, quitação, quitado, total)
TITULOS = [
    (901, 26, ES, D(2025, 12, 10), D(2025, 12, 30), D(2025, 12, 30), 1, 300.0),  # a última compra, antes do cache
    (902, 26, ES, D(7190, 1, 1), D(7190, 1, 30), D(2025, 12, 30), 1, 10.0),      # data digitada errada no ERP
    (903, 28, JAMILLE, D(2026, 5, 4), D(2026, 6, 3), None, 0, 1000.0),           # vencido há 120 dias
    (904, 28, JAMILLE, D(2026, 9, 25), D(2026, 10, 25), None, 0, 200.0),         # a vencer
    (905, 29, JAMILLE, D(2026, 5, 5), D(2026, 6, 4), None, 0, 500.0),            # vencido há 119 dias
    (906, 30, ES, D(2026, 4, 1), D(2026, 5, 1), None, 0, 800.0),                 # vencido há 153 dias
]
PARCELAS = [(903, 2, 1, 400.0)]  # a primeira parcela do 903 foi paga
REDES = {**{c: "SEMANAL" for c in (1, 2, 3, 20, 21, 27, 28, 29, 30, 33, 34, 35, 36, 37)}, 22: "MENSAL", 23: "Mensal",
         24: "REDE CASAGRANDE ES", 25: "QUINZENAL", 26: "QUINZENAL", 31: "QUINZENAL", 32: "QUINZENAL"}


def trecho(cliente, de, ate, vendedor, area="ROTA 1"):
    return (cliente, de, ate, vendedor, False, "ES", 1, area, "MERCADO")


VIGENCIAS = [
    *(trecho(c, INICIO, None, v) for c, v in ((20, ES), (21, ES), (22, ES), (23, ES), (24, JAMILLE), (25, JAMILLE),
                                               (26, ES), (28, JAMILLE), (29, JAMILLE), (30, ES), (31, CENTRAL_BA),
                                               (33, CENTRAL_ES))),
    trecho(32, INICIO, D(2026, 9, 9), ES), trecho(32, D(2026, 9, 10), None, CENTRAL_BA),  # passado para a central
    # na central desde o começo: mudou de área e depois de vendedor da central, e o bloco continua
    trecho(34, INICIO, D(2026, 8, 31), CENTRAL_BA), trecho(34, D(2026, 9, 1), D(2026, 9, 19), CENTRAL_BA, "ROTA 2"),
    trecho(34, D(2026, 9, 20), None, CENTRAL_ES),
    trecho(35, INICIO, D(2026, 8, 31), ES), trecho(35, D(2026, 9, 25), None, ES),  # inativado e reativado
]
RETRATOS = [(INICIO, 15, 15, 0, 0), (DIA, 16, 1, 0, 0)]


def criar(pasta: Path, **mais):
    opcoes = {"redes": REDES, "vigencias": VIGENCIAS, "retratos": RETRATOS, "vendas_extras": VENDAS,
              "titulos_extras": TITULOS, "parcelas_extras": PARCELAS, "clientes_extras": CLIENTES,
              "vendedores_extras": VENDEDORES, **mais}
    return criar_calc(pasta, **opcoes)


def contexto(**mudar) -> dict:
    return {"dia": DIA, "dias": dict(PADRAO["dias"]), "participantes": {ES, JAMILLE, CENTRAL_BA, CENTRAL_ES},
            "central": {CENTRAL_BA, CENTRAL_ES}, "primeiro_retrato": INICIO,
            "regras": {"sem_compra": True, "inadimplente": True, "central_sem_compra": True}, **mudar}


def fato(**mudar) -> dict:
    return {"id": 1, "nome": "CLIENTE", "id_vendedor": ES, "cidade": "SERRA", "uf": "ES", "area": "ROTA 1",
            "data_cadastro": D(2020, 1, 1), "inativo": False, "ficticio": False, "rede": "SEMANAL",
            "ultima_venda": None, "ultimo_titulo": None, "inad_titulos": 0, "inad_total": None, "inad_saldo": None,
            "inad_desde": None, "atraso_titulos": 0, "atraso_total": None, "atraso_saldo": None, "atraso_desde": None,
            "na_base_desde": INICIO, "com_vendedor_desde": INICIO, "na_central_desde": None,
            "bloqueado": False, "compras_valor": None, "compras_meses": None, **mudar}


class TestConfig(unittest.TestCase):
    def test_valida(self):
        self.assertEqual(_valida({}), PADRAO)
        cfg = _valida({"ligada": True, "dias": {"mensal": "45"}, "prazo_dia_util": 3, "central": [141, "140", 141]})
        self.assertEqual((cfg["ligada"], cfg["dias"]["mensal"], cfg["dias"]["semanal"], cfg["prazo_dia_util"]),
                         (True, 45, 30, 3))
        self.assertEqual(cfg["central"], [140, 141])
        for errado in ({"ligada": True}, {"ligada": "sim"}, {"dias": {"semanal": 0}}, {"dias": {"central": 1.5}},
                       {"dias": {"mensal": "muitos"}}, {"prazo_dia_util": 11}, {"central": ["x"]}, {"central": 141}):
            with self.subTest(errado=errado), self.assertRaises(ValueError):
                _valida(errado)


class TestPrazo(unittest.TestCase):
    def test_penultimo_dia_util(self):
        cal = Calendario()
        self.assertEqual(prazo_do_mes(cal, 2026, 11, 2), D(2026, 11, 27))  # 30/11 é segunda: o penúltimo é a sexta
        self.assertEqual(prazo_do_mes(cal, 2026, 11, 1), D(2026, 11, 30))
        self.assertEqual(prazo_do_mes(cal, 2026, 11, 3), D(2026, 11, 26))
        self.assertEqual(prazo_do_mes(cal, 2026, 10, 2), D(2026, 10, 29))
        self.assertEqual(prazo_do_mes(cal, 2026, 12, 2), D(2026, 12, 30))

    def test_feriado_de_um_estado_vale_o_mais_cedo(self):
        cal = Calendario([{"data": "2026-11-27", "regiao": "ES", "peso": 0}])
        self.assertEqual(prazo_do_mes(cal, 2026, 11, 2), D(2026, 11, 26))  # no ES sobram 26 e 30; na BA seria 27

    def test_sabado_com_peso_nao_e_prazo(self):
        cal = Calendario(peso_sabado={"ES": 0.5, "BA": 0.5})
        self.assertEqual(prazo_do_mes(cal, 2026, 11, 2), D(2026, 11, 27))  # e não o sábado 28/11


class TestAvaliar(unittest.TestCase):
    def sugestao(self, ctx=None, **f):
        return avaliar(fato(**f), ctx or contexto())

    def test_limites_por_frequencia(self):
        for rede, ultima, esperado in (("SEMANAL", D(2026, 9, 1), "central"), ("SEMANAL", D(2026, 9, 2), None),
                                       ("Quinzenal", D(2026, 9, 1), "central"), ("QUINZENAL", D(2026, 9, 2), None),
                                       ("MENSAL", D(2026, 8, 12), "central"), ("MENSAL", D(2026, 8, 13), None),
                                       ("REDE CASAGRANDE ES", D(2026, 9, 1), "central"), (None, D(2026, 9, 1), "central"),
                                       ("REDE CASAGRANDE ES", D(2026, 9, 2), None)):
            with self.subTest(rede=rede, ultima=ultima):
                self.assertEqual(self.sugestao(rede=rede, ultima_venda=ultima)[0], esperado)
        _, fatos = self.sugestao(rede="Mensal", ultima_venda=D(2026, 8, 12))
        self.assertEqual((fatos["frequencia"], fatos["limite"], fatos["dias_sem_compra"], fatos["motivos"]),
                         ("mensal", 50, 50, ["sem_compra"]))
        self.assertEqual(self.sugestao(rede="REDE X", ultima_venda=D(2026, 9, 1))[1]["frequencia"], "sem_frequencia")

    def test_de_onde_conta(self):
        # sem venda no cache: o último título; sem título: o cadastro
        s, f = self.sugestao(ultimo_titulo=D(2025, 12, 10))
        self.assertEqual((s, f["ultima_compra"], f["origem_ultima_compra"], f["origem_conta"]),
                         ("central", "2025-12-10", "titulo", "compra"))
        s, f = self.sugestao(data_cadastro=D(2026, 9, 10))
        self.assertEqual((s, f["ultima_compra"], f["origem_conta"], f["dias_sem_compra"]), (None, None, "cadastro", 21))
        self.assertEqual(self.sugestao(data_cadastro=D(2026, 3, 1))[0], "central")
        # reativado: conta da reativação, não da compra antiga; o cliente novo, do cadastro
        s, f = self.sugestao(ultima_venda=D(2026, 3, 1), na_base_desde=D(2026, 9, 25))
        self.assertEqual((s, f["origem_conta"], f["conta_desde"], f["dias_sem_compra"]),
                         (None, "reativacao", "2026-09-25", 6))
        s, f = self.sugestao(data_cadastro=D(2026, 9, 20), na_base_desde=D(2026, 9, 22))
        self.assertEqual(f["origem_conta"], "cadastro")
        # sem histórico da carteira (ou do primeiro dia dele), vale a compra
        self.assertEqual(self.sugestao(ultima_venda=D(2026, 3, 1), na_base_desde=INICIO)[0], "central")
        self.assertEqual(self.sugestao(ultima_venda=D(2026, 3, 1), na_base_desde=None)[0], "central")

    def test_quem_fica_fora(self):
        velho = {"ultima_venda": D(2026, 3, 1)}
        self.assertEqual(self.sugestao(**velho)[0], "central")
        for fora in ({"inativo": True}, {"ficticio": True}, {"id_vendedor": TERCEIRO}):
            with self.subTest(fora=fora):
                self.assertIsNone(self.sugestao(**velho, **fora)[0])
        sem_dado = contexto(regras={"sem_compra": False, "inadimplente": True, "central_sem_compra": True})
        self.assertIsNone(self.sugestao(sem_dado, **velho)[0])  # a frequência não veio: a regra fica parada

    def test_central(self):
        central = {"id_vendedor": CENTRAL_BA}
        # conta do mais recente entre a entrada e a última compra
        s, f = self.sugestao(**central, ultima_venda=D(2026, 7, 20), na_central_desde=D(2026, 9, 1))
        self.assertEqual((s, f["motivos"], f["origem_conta"], f["dias_sem_compra"], f["limite"]),
                         ("inativar", ["central_sem_compra"], "central", 30, 30))
        self.assertIsNone(self.sugestao(**central, ultima_venda=D(2026, 7, 20), na_central_desde=D(2026, 9, 2))[0])
        s, f = self.sugestao(**central, ultima_venda=D(2026, 9, 5), na_central_desde=INICIO)
        self.assertEqual((s, f["origem_conta"], f["dias_sem_compra"], f["na_central_desde_antes"]),
                         (None, "compra", 26, True))
        self.assertEqual(self.sugestao(**central, ultima_venda=D(2026, 9, 1), na_central_desde=INICIO)[0], "inativar")
        # na central sem o trecho no histórico: acabou de entrar
        s, f = self.sugestao(**central, ultima_venda=D(2026, 3, 1))
        self.assertEqual((s, f["na_central_desde"], f["dias_sem_compra"]), (None, "2026-10-01", 0))
        # a frequência não muda o limite da central, e ela nunca é sugerida para a central
        self.assertIsNone(self.sugestao(**central, rede="MENSAL", ultima_venda=D(2026, 9, 5), na_central_desde=INICIO)[0])

    def test_inadimplente_tem_prioridade(self):
        titulos = {"inad_titulos": 2, "inad_total": 1500.0, "inad_saldo": 1100.0, "inad_desde": D(2026, 5, 1)}
        s, f = self.sugestao(ultima_venda=D(2026, 9, 25), **titulos)
        self.assertEqual((s, f["motivos"]), ("inativar", ["inadimplente"]))
        self.assertEqual(f["inadimplencia"], {"titulos": 2, "total": 1500.0, "saldo": 1100.0,
                                              "vencimento_mais_antigo": "2026-05-01", "dias": 153})
        s, f = self.sugestao(ultima_venda=D(2026, 8, 1), **titulos)
        self.assertEqual((s, f["motivos"]), ("inativar", ["inadimplente", "sem_compra"]))
        s, f = self.sugestao(id_vendedor=CENTRAL_ES, ultima_venda=D(2026, 7, 1), na_central_desde=INICIO, **titulos)
        self.assertEqual((s, f["motivos"]), ("inativar", ["inadimplente", "central_sem_compra"]))
        self.assertIsNone(self.sugestao(id_vendedor=TERCEIRO, ultima_venda=D(2026, 9, 25), **titulos)[0])

    def test_titulos_em_atraso_so_mostrados(self):
        # vencido há 30 dias: aparece na linha aberta, sem pôr o cliente na lista de inativar
        atraso = {"atraso_titulos": 2, "atraso_total": 900.0, "atraso_saldo": 700.0, "atraso_desde": D(2026, 9, 1)}
        s, f = self.sugestao(ultima_venda=D(2026, 9, 25), **atraso)
        self.assertEqual((s, f["motivos"], f["inadimplencia"]), (None, [], None))
        self.assertEqual(f["em_atraso"], {"a_partir_de": 8, "titulos": 2, "total": 900.0, "saldo": 700.0,
                                          "vencimento_mais_antigo": "2026-09-01", "dias": 30})
        self.assertEqual(self.sugestao(ultima_venda=D(2026, 3, 1), **atraso)[0], "central")  # a lista segue a regra
        # sem nenhum: diz que não há; sem os títulos no cache: não diz nada
        self.assertEqual(self.sugestao()[1]["em_atraso"], {"a_partir_de": 8, "titulos": 0})
        self.assertEqual(self.sugestao(atraso_titulos=None)[1]["em_atraso"], {"a_partir_de": 8, "titulos": 0})
        sem_titulos = contexto(regras={"sem_compra": True, "inadimplente": False, "central_sem_compra": True})
        self.assertIsNone(self.sugestao(sem_titulos, **atraso)[1]["em_atraso"])


class TestFatos(unittest.TestCase):
    def setUp(self):
        self._pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self._pasta.cleanup)

    def fatos(self, **mais):
        calc = criar(Path(self._pasta.name), **mais)
        self.addCleanup(calc.cache._con.close)
        manejo = Manejo(None, calc, None, lambda: dict(NOMES), True)
        central = {CENTRAL_BA, CENTRAL_ES}
        return manejo._fatos(DIA, PADRAO, {ES, JAMILLE} | central, central, [37])

    def test_cada_fato(self):
        fatos, disponivel, avisos, primeiro = self.fatos()
        self.assertEqual((disponivel, avisos, primeiro),
                         ({"sem_compra": True, "inadimplente": True, "central_sem_compra": True}, [], INICIO))
        # só os ativos dos vendedores do escopo, mais quem tem sugestão em andamento (o 37, inativo)
        self.assertEqual(set(fatos), {1, 2, 3, *range(20, 27), *range(28, 38)})
        self.assertTrue(fatos[37]["inativo"])
        self.assertTrue(fatos[36]["ficticio"])
        self.assertEqual(fatos[20]["ultima_venda"], D(2026, 9, 1))
        self.assertIsNone(fatos[25]["ultima_venda"])  # a venda a FUNCIONARIO com o código 25 não é dele
        self.assertEqual((fatos[26]["ultima_venda"], fatos[26]["ultimo_titulo"]), (None, D(2025, 12, 10)))
        t = fatos[28]  # um título vencido há 120 dias, com uma parcela paga; o que vence depois não conta
        self.assertEqual((t["inad_titulos"], t["inad_total"], t["inad_saldo"], t["inad_desde"]),
                         (1, 1000.0, 600.0, D(2026, 6, 3)))
        self.assertEqual(fatos[29]["inad_titulos"], 0)
        # em atraso (8 dias ou mais): o de 120 dias também conta; o de 119 dias conta só aqui
        atraso = lambda c: tuple(fatos[c][f"atraso_{k}"] for k in ("titulos", "total", "saldo", "desde"))  # noqa: E731
        self.assertEqual(atraso(28), (1, 1000.0, 600.0, D(2026, 6, 3)))
        self.assertEqual(atraso(29), (1, 500.0, 500.0, D(2026, 6, 4)))
        # o mercado (1): vencido há 8 dias exatos entra (o 103, com metade paga); há 7 dias (o 104), ainda não
        self.assertEqual(atraso(1), (1, 1300.0, 650.0, D(2026, 9, 23)))
        self.assertEqual(atraso(2), (1, 2500.0, 2500.0, D(2026, 9, 3)))
        self.assertEqual(fatos[20]["atraso_titulos"], None)  # sem nenhum título
        self.assertEqual((fatos[20]["compras_valor"], fatos[20]["compras_meses"]), (100.0, 1))
        self.assertTrue(fatos[2]["bloqueado"])
        self.assertFalse(fatos[20]["bloqueado"])

    def test_blocos_da_carteira(self):
        fatos = self.fatos()[0]
        self.assertEqual((fatos[31]["na_central_desde"], fatos[32]["na_central_desde"]), (INICIO, D(2026, 9, 10)))
        # trocou de área e de vendedor da central: o bloco da central continua, o do vendedor recomeça
        self.assertEqual((fatos[34]["na_central_desde"], fatos[34]["com_vendedor_desde"]), (INICIO, D(2026, 9, 20)))
        self.assertEqual((fatos[35]["na_base_desde"], fatos[20]["na_base_desde"]), (D(2026, 9, 25), INICIO))
        self.assertIsNone(fatos[20]["na_central_desde"])  # não é da central
        self.assertIsNone(fatos[2]["na_central_desde"])   # da central, sem trecho no histórico

    def test_cache_sem_alguma_tabela(self):
        _, disponivel, avisos, _ = self.fatos(rede=False)
        self.assertEqual(disponivel, {"sem_compra": False, "inadimplente": True, "central_sem_compra": True})
        self.assertIn("frequência", avisos[0])

    def test_sem_frequencia_nenhuma_e_sem_credito(self):
        fatos, disponivel, avisos, _ = self.fatos(redes={20: "REDE X"}, credito=False)
        self.assertEqual(disponivel, {"sem_compra": False, "inadimplente": False, "central_sem_compra": True})
        self.assertEqual(len(avisos), 2)
        self.assertIsNone(fatos[28]["inad_titulos"])
        self.assertIsNone(fatos[28]["atraso_titulos"])

    def test_sem_parcelas_e_sem_carteira(self):
        fatos, disponivel, _, primeiro = self.fatos(parcelas=False, carteira=False, bloqueios=False)
        self.assertEqual(fatos[28]["inad_saldo"], 1000.0)
        self.assertEqual((disponivel["central_sem_compra"], primeiro), (False, None))
        self.assertIsNone(fatos[31]["na_central_desde"])
        self.assertIsNone(fatos[20]["bloqueado"])


class Base(BaseBanco):
    def setUp(self):
        super().setUp()
        self._pasta = tempfile.TemporaryDirectory()
        self.calc = criar(Path(self._pasta.name))
        self.hoje = DIA
        self.config = ConfigManejo(self.banco)
        self.config.salvar({**PADRAO, "ligada": True, "central": [CENTRAL_BA, CENTRAL_ES]})
        self.manejo = Manejo(self.banco, self.calc, self.config, lambda: dict(NOMES), True, hoje=lambda: self.hoje)
        self.chefe = self.pessoa("chefe", "admin")
        self.val = self.pessoa("valdirene", justifica=True)   # vê o ES
        self.marcos = self.pessoa("marcos", justifica=True)   # vê a BA
        self.leitor = self.pessoa("leitor")                   # tem a página, sem a marca

    def tearDown(self):
        self.calc.cache._con.close()
        self._pasta.cleanup()
        super().tearDown()

    def pessoa(self, login: str, papel: str = "visualizador", justifica: bool = False) -> dict:
        id_ = self.criar_usuario(login, papel, ["manejo"])
        manejo = {"justifica": True} if justifica else None
        if justifica:
            with self.banco.conexao() as con:
                con.execute("UPDATE usuarios SET manejo = %s::jsonb WHERE id = %s", [json.dumps(manejo), id_])
        return {"id": id_, "login": login, "nome": login.title(), "papel": papel, "manejo": manejo,
                "paginas": None if papel == "admin" else ["manejo"]}

    def copia(self, dia, *comandos: str) -> None:
        """Uma cópia nova do ERP no cache: roda os comandos no arquivo do cache e muda o dia dos dados."""
        cache = self.calc.cache
        cache._con.close()
        con = duckdb.connect(str(cache.arquivo))
        for sql in comandos:
            con.execute(sql)
        con.execute("UPDATE info SET valor = ? WHERE chave = 'banco_copia'", [f"{dia}T07:00"])
        con.execute("UPDATE info SET valor = ? WHERE chave = 'extraido_em'", [f"{dia}T08:00:00"])
        con.close()
        cache._abrir()
        self.hoje = max(self.hoje, dia)

    def linhas(self) -> dict:
        with self.banco.conexao() as con:
            return {(c, s): (m, v) for c, s, m, v in con.execute(
                "SELECT id_cliente, sugestao, encerrada_motivo, id_vendedor FROM manejo_sugestoes "
                "WHERE mes = (SELECT max(mes) FROM manejo_sugestoes x WHERE x.id_cliente = manejo_sugestoes.id_cliente "
                "AND x.sugestao = manejo_sugestoes.sugestao)")}

    def item(self, cliente: int, mes: str | None = None) -> dict:
        """O cliente como a página o vê (sem o mês: na lista mais nova em que ele está)."""
        d = self.manejo.listar(self.chefe, None, mes)
        for m in [None] if mes else [None, *(r["mes"] for r in d["rodadas"])]:
            achado = [i for i in (self.manejo.listar(self.chefe, None, m) if m else d)["itens"]
                      if i["cliente"]["id"] == cliente]
            if achado:
                return achado[-1]
        raise AssertionError(f"o cliente {cliente} não está em nenhuma lista")

    def marcar(self, cliente: int, mes: str | None = None) -> dict:
        i = self.item(cliente, mes)
        return {"id": i["id"], "versao": i["versao"]}


class TestLista(Base):
    def test_nome_do_erp(self):
        self.manejo.sincronizar()
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT cliente FROM manejo_sugestoes WHERE id_cliente = 20").fetchone()[0],
                             "MERCADO TRINTA (CLIENTE 20)")
            # a linha gravada antes, sem o código no nome: a página mostra o nome do cadastro do ERP
            con.execute("UPDATE manejo_sugestoes SET cliente = 'MERCADO TRINTA' WHERE id_cliente = 20")
        self.assertEqual(self.item(20)["cliente"]["nome"], "MERCADO TRINTA (CLIENTE 20)")
        self.copia(DIA, "UPDATE clientes SET nome = '  MERCADO  TRINTA E UM (CLIENTE 20)' WHERE id = 20")
        self.assertEqual(self.item(20)["cliente"]["nome"], "MERCADO TRINTA E UM (CLIENTE 20)")  # o nome de hoje
        self.assertEqual(self.manejo.historico(self.chefe, None, 20)["cliente"]["nome"],
                         "MERCADO TRINTA E UM (CLIENTE 20)")
        self.assertEqual(self.manejo._nomes_erp([20, 999999]), {20: "MERCADO TRINTA E UM (CLIENTE 20)"})  # fora do cache:
        self.assertEqual(self.manejo._nomes_erp([]), {})                       # fica o nome guardado na linha

    def test_primeira_lista(self):
        self.assertEqual(self.manejo.sincronizar(), [])
        self.assertEqual(self.linhas(), {**{(c, "central"): (None, v) for c, v in (
            (20, ES), (23, ES), (24, JAMILLE), (25, JAMILLE), (26, ES))}, **{(c, "inativar"): (None, v) for c, v in (
                (28, JAMILLE), (30, ES), (31, CENTRAL_BA), (34, CENTRAL_ES))}})
        d = self.manejo.listar(self.chefe, None)
        self.assertEqual(d["rodada"], {"mes": "2026-10", "rotulo": "outubro de 2026", "prazo": "2026-10-29",
                                      "aberta": True, "atual": True, "dias_para_o_prazo": 28})
        self.assertEqual((d["ativo"], d["ligada"], d["admin"], d["pode_justificar"], d["dia"], d["data_ref"]),
                         (True, True, True, False, "2026-10-01", "2026-09-30"))
        self.assertEqual(d["regras"]["central"], ["Lorena", "Thais"])
        self.assertEqual(d["pendencias"], [])
        itens = {i["cliente"]["id"]: i for i in d["itens"]}
        i = itens[20]
        self.assertEqual((i["cliente"]["nome"], i["sugestao"], i["situacao"], i["entrou_em"], i["versao"]),
                         ("MERCADO TRINTA (CLIENTE 20)", "central", "a_justificar", "2026-10-01", 0))  # o nome do ERP
        self.assertEqual(i["vendedor"], {"id": ES, "nome": "Rubens", "equipe": "ES"})
        self.assertEqual(i["entrada"], {"dias_sem_compra": 30, "ultima_compra": "2026-09-01", "dias_inadimplencia": None})
        self.assertEqual(i["pode"], {"justificar": False, "veredito": False})  # o administrador espera a justificativa
        self.assertEqual((itens[24]["fatos"]["frequencia"], itens[24]["fatos"]["rede"]),
                         ("sem_frequencia", "REDE CASAGRANDE ES"))
        self.assertEqual((itens[25]["fatos"]["ultima_compra"], itens[25]["fatos"]["origem_conta"]), (None, "cadastro"))
        self.assertEqual(itens[26]["fatos"]["origem_ultima_compra"], "titulo")
        self.assertEqual(itens[30]["fatos"]["motivos"], ["inadimplente", "sem_compra"])
        self.assertEqual(itens[28]["fatos"]["inadimplencia"]["saldo"], 600.0)
        self.assertEqual((itens[28]["fatos"]["em_atraso"]["titulos"], itens[28]["fatos"]["em_atraso"]["dias"]), (1, 120))
        self.assertEqual(itens[20]["fatos"]["em_atraso"], {"a_partir_de": 8, "titulos": 0})
        f = itens[31]["fatos"]
        self.assertEqual((f["motivos"], f["na_central_desde"], f["na_central_desde_antes"], f["dias_sem_compra"]),
                         (["central_sem_compra"], "2026-08-01", True, 61))
        # repetir com os mesmos dados não muda nada
        with self.banco.conexao() as con:
            antes = con.execute("SELECT id, fatos, dados_ate FROM manejo_sugestoes ORDER BY id").fetchall()
        self.manejo.sincronizar(forcar=True)
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT id, fatos, dados_ate FROM manejo_sugestoes ORDER BY id").fetchall(),
                             antes)
        self.assertEqual(self.contar("manejo_rodadas"), 1)

    def test_no_pc_so_avisa(self):
        pc = Manejo(self.banco, self.calc, self.config, lambda: dict(NOMES), False)
        self.assertEqual(pc.sincronizar(), [])
        d = pc.listar(self.chefe, None)
        self.assertEqual((d["ativo"], d["itens"], d["data_ref"]), (False, [], "2026-09-30"))
        self.assertIn("site", d["aviso"])
        corpo = {"itens": [{"id": 1, "versao": 0}], "decisao": "seguir"}
        for chamada in (lambda: pc.justificar(self.val, DO_ES, corpo), lambda: pc.veredito(self.chefe, corpo),
                        lambda: pc.historico(self.chefe, None, 20)):
            with self.assertRaises(ValueError):
                chamada()
        self.assertEqual(self.contar("manejo_sugestoes"), 0)
        self.assertFalse(pc.config_dados()["ativo"])

    def test_campanha_desligada_nao_cria(self):
        self.config.salvar({**PADRAO, "central": [CENTRAL_BA]})
        self.assertEqual(self.manejo.sincronizar(), [])
        d = self.manejo.listar(self.chefe, None)
        self.assertEqual((d["ligada"], d["rodada"], d["rodadas"], d["itens"]), (False, None, [], []))
        self.assertEqual(self.contar("manejo_rodadas"), 0)

    def test_quem_compra_ou_paga_sai_e_quem_volta_reabre(self):
        self.manejo.sincronizar()
        self.manejo.justificar(self.marcos, DA_BA, {"itens": [self.marcar(28)], "decisao": "seguir"})
        self.copia(D(2026, 10, 2), "INSERT INTO vendas_clientes VALUES (DATE '2026-10-01', 124, 20, 'CLIENTE', 1)",
                   "UPDATE titulos_receber SET quitado = 1, quitacao = DATE '2026-10-01' WHERE id = 903")
        self.manejo.sincronizar()
        linhas = self.linhas()
        self.assertEqual((linhas[(20, "central")][0], linhas[(28, "inativar")][0]), ("comprou", "pagou"))
        # quem saiu sozinho some da lista da página e fica só no histórico do cliente
        self.assertFalse({20, 28} & {i["cliente"]["id"] for i in self.manejo.listar(self.chefe, None)["itens"]})
        with self.assertRaises(AssertionError):
            self.item(20)
        (s,) = self.manejo.historico(self.chefe, None, 20)["sugestoes"]
        self.assertEqual(s["encerrada"], {"em": "2026-10-02", "motivo": "comprou"})
        self.assertIn((21, "central"), linhas)   # completou 30 dias em 02/10
        self.assertIn((29, "inativar"), linhas)  # e este, 120 dias de atraso
        # outro título do 28 passa dos 120 dias no mesmo mês: a mesma linha reabre, com a justificativa de antes
        self.copia(D(2026, 10, 5),
                   "INSERT INTO titulos_receber VALUES (907, 28, 98, DATE '2026-05-01', DATE '2026-06-05', NULL, 0, 300)")
        self.manejo.sincronizar()
        self.assertEqual(self.contar("manejo_sugestoes", "id_cliente = 28"), 1)
        i = self.item(28)
        self.assertEqual((i["situacao"], i["encerrada"], i["justificativa"]["decisao"]), ("justificada", None, "seguir"))

    def test_troca_de_vendedor_central_e_inativo(self):
        self.manejo.sincronizar()
        self.copia(D(2026, 10, 2), "UPDATE clientes SET id_vendedor = 98 WHERE id = 20",   # passou para a Jamille
                   "UPDATE clientes SET id_vendedor = 141 WHERE id = 23",                  # já foi para a central
                   "UPDATE clientes_detalhes SET inativo = 1 WHERE id = 24",               # já foi inativado
                   "UPDATE clientes SET id_vendedor = 61 WHERE id = 26",                   # foi para um terceiro
                   "DELETE FROM clientes WHERE id = 25")                                   # sumiu do cadastro
        self.manejo.sincronizar()
        linhas = self.linhas()
        self.assertEqual(linhas[(20, "central")], (None, JAMILLE))  # a sugestão acompanha o vendedor novo
        self.assertEqual(linhas[(23, "central")], ("na_central", ES))
        self.assertEqual(linhas[(24, "central")], ("inativado", JAMILLE))
        self.assertEqual(linhas[(26, "central")], ("fora_da_regra", ES))
        self.assertEqual(linhas[(25, "central")], ("fora_da_regra", JAMILLE))
        i = self.item(20)
        self.assertEqual((i["vendedor"]["nome"], i["vendedor_entrada"]), ("Jamille", "Rubens"))
        # os que saíram (já na central, inativado, fora da regra) não aparecem mais na lista
        na_lista = {x["cliente"]["id"] for x in self.manejo.listar(self.chefe, None)["itens"]}
        self.assertIn(20, na_lista)
        self.assertFalse({23, 24, 25, 26} & na_lista)
        # quem vê a BA passa a ver o 20; quem vê o ES, não mais
        self.assertIn(20, {x["cliente"]["id"] for x in self.manejo.listar(self.marcos, DA_BA)["itens"]})
        self.assertNotIn(20, {x["cliente"]["id"] for x in self.manejo.listar(self.val, DO_ES)["itens"]})

    def test_inativacao_tem_prioridade(self):
        self.manejo.sincronizar()
        self.copia(D(2026, 10, 2),
                   "INSERT INTO titulos_receber VALUES (908, 20, 124, DATE '2026-04-01', DATE '2026-05-01', NULL, 0, 100)")
        self.manejo.sincronizar()
        linhas = self.linhas()
        self.assertEqual((linhas[(20, "central")][0], linhas[(20, "inativar")][0]), ("outra_sugestao", None))
        # pagou: sai da inativação e, ainda sem comprar, volta para a lista da central (a mesma linha do mês)
        self.copia(D(2026, 10, 3), "UPDATE titulos_receber SET quitado = 1 WHERE id = 908")
        self.manejo.sincronizar()
        linhas = self.linhas()
        self.assertEqual((linhas[(20, "central")][0], linhas[(20, "inativar")][0]), (None, "pagou"))
        self.assertEqual(self.contar("manejo_sugestoes", "id_cliente = 20"), 2)

    def test_depois_do_prazo_entra_na_lista_do_mes_seguinte(self):
        self.manejo.sincronizar()
        self.copia(D(2026, 10, 30))  # o prazo de outubro (29/10) passou
        self.manejo.sincronizar()
        with self.banco.conexao() as con:
            meses = dict(con.execute("SELECT id_cliente, array_agg(mes ORDER BY mes) FROM manejo_sugestoes "
                                     "WHERE id_cliente IN (20, 21) GROUP BY 1").fetchall())
        # o 20 continua na lista de outubro, esperando o veredito; o 21 completou os dias depois: lista de novembro
        self.assertEqual(meses, {20: [D(2026, 10, 1)], 21: [D(2026, 11, 1)]})
        d = self.manejo.listar(self.chefe, None)
        self.assertEqual((d["rodada"]["mes"], d["rodada"]["prazo"]), ("2026-11", "2026-11-27"))
        self.assertEqual([(r["mes"], r["aberta"], r["atual"]) for r in d["rodadas"]],
                         [("2026-11", True, True), ("2026-10", False, False)])
        self.assertEqual([(p["mes"], p["aguardando_erp"]) for p in d["pendencias"]], [("2026-10", 0)])
        self.assertGreaterEqual(d["pendencias"][0]["sem_veredito"], 5)
        i = self.item(20)
        self.assertEqual((i["situacao"], i["pode"]), ("sem_justificativa", {"justificar": False, "veredito": True}))
        r = self.manejo.justificar(self.val, DO_ES, {"itens": [self.marcar(20)], "decisao": "seguir"})
        self.assertEqual((r["gravados"], r["recusados"][0]["motivo"]), (0, "o prazo terminou em 29/10"))
        # sem justificativa, o veredito já pode sair
        self.assertEqual(self.manejo.veredito(self.chefe, {"itens": [self.marcar(20)], "decisao": "seguir"})["gravados"], 1)
        self.assertEqual(self.item(20)["situacao"], "aguardando_erp")

    def test_cache_sem_a_frequencia_nao_mexe_na_lista_da_central(self):
        self.manejo.sincronizar()
        self.copia(D(2026, 10, 2), "DELETE FROM clientes_rede",
                   "INSERT INTO vendas_clientes VALUES (DATE '2026-10-01', 124, 20, 'CLIENTE', 1)")
        avisos = self.manejo.sincronizar()
        self.assertEqual(len(avisos), 1)
        self.assertIn("frequência", avisos[0])
        linhas = self.linhas()
        self.assertEqual(linhas[(20, "central")], (None, ES))  # comprou, mas a regra ficou parada: ninguém sai
        self.assertNotIn((21, "central"), linhas)              # nem entra
        self.assertIn((29, "inativar"), linhas)                # a regra dos inadimplentes segue
        self.assertEqual(self.manejo.listar(self.chefe, None)["avisos"], avisos)

    def test_o_prazo_acompanha_o_calendario_enquanto_aberto(self):
        self.manejo.sincronizar()
        self.config.salvar({**self.config.atual(), "prazo_dia_util": 1})
        self.assertEqual(self.manejo.listar(self.chefe, None)["rodada"]["prazo"], "2026-10-30")
        self.assertEqual(self.manejo.config_dados()["prazo"],
                         {"mes": "2026-10", "rotulo": "outubro de 2026", "data": "2026-10-30"})


class TestRespostas(Base):
    def setUp(self):
        super().setUp()
        self.manejo.sincronizar()

    def eventos(self, cliente: int) -> list:
        with self.banco.conexao() as con:
            return con.execute("SELECT e.tipo, e.decisao, e.texto, e.criado_por_nome FROM manejo_eventos e "
                               "JOIN manejo_sugestoes s ON s.id = e.sugestao WHERE s.id_cliente = %s ORDER BY e.id",
                               [cliente]).fetchall()

    def test_quem_pode_justificar(self):
        m = self.marcar(20)
        corpo = {"itens": [m], "decisao": "seguir"}
        for quem, ids in ((self.leitor, DO_ES), (self.chefe, None), (self.marcos, DA_BA)):  # sem a marca; fora do acesso
            with self.subTest(quem=quem["login"]), self.assertRaises(PermissionError):
                self.manejo.justificar(quem, ids, corpo)
        with self.assertRaises(PermissionError):  # um cliente de fora recusa o pedido inteiro
            self.manejo.justificar(self.marcos, DA_BA, {"itens": [self.marcar(24), m], "decisao": "seguir"})
        self.assertEqual(self.contar("manejo_eventos"), 0)
        for errado in ({"itens": [m], "decisao": "talvez"}, {"itens": [m], "decisao": "manter", "texto": "curto"},
                       {"itens": [], "decisao": "seguir"}, {"itens": [m, m], "decisao": "seguir"},
                       {"itens": [m], "decisao": "seguir", "texto": "x" * 2001}, {"itens": [{"id": "a"}], "decisao": "seguir"},
                       {"itens": [m] * 501, "decisao": "seguir"}):
            with self.subTest(errado=str(errado)[:60]), self.assertRaises(ValueError):
                self.manejo.justificar(self.val, DO_ES, errado)

    def test_justificar_e_o_historico(self):
        m = self.marcar(20)
        texto = "Em reforma, reabre dia 25."
        r = self.manejo.justificar(self.val, DO_ES, {"itens": [m], "decisao": "manter", "texto": f"  {texto} "})
        self.assertEqual(r, {"gravados": 1, "recusados": []})
        i = self.item(20)
        self.assertEqual((i["situacao"], i["justificativa"]["decisao"], i["justificativa"]["texto"],
                          i["justificativa"]["por"]), ("justificada", "manter", texto, "Valdirene"))
        self.assertEqual(i["pode"], {"justificar": False, "veredito": True})  # para o administrador
        # com a versão que a pessoa via antes da resposta, recusa: a lista mudou
        r = self.manejo.justificar(self.val, DO_ES, {"itens": [m], "decisao": "seguir"})
        self.assertEqual((r["gravados"], r["recusados"]), (0, [{"id": m["id"], "cliente": "MERCADO TRINTA (CLIENTE 20)",
                                                               "motivo": "mudou enquanto você olhava; confira de novo"}]))
        m = self.marcar(20)
        self.manejo.justificar(self.val, DO_ES, {"itens": [m], "decisao": "manter", "texto": texto})  # a mesma de novo
        self.assertEqual(len(self.eventos(20)), 1)
        self.manejo.justificar(self.val, DO_ES, {"itens": [m], "decisao": "seguir"})  # mudou de ideia: outra linha
        self.assertEqual(self.eventos(20), [("justificativa", "manter", texto, "Valdirene"),
                                            ("justificativa", "seguir", "", "Valdirene")])
        h = self.manejo.historico(self.val, DO_ES, 20)
        self.assertEqual(h["cliente"], {"id": 20, "nome": "MERCADO TRINTA (CLIENTE 20)"})
        (s,) = h["sugestoes"]
        self.assertEqual((s["mes"], s["sugestao"], s["vendedor"], s["encerrada"]), ("2026-10", "central", "Rubens", None))
        self.assertEqual([(e["tipo"], e["decisao"], e["dias_sem_compra"], e["ultima_compra"]) for e in s["eventos"]],
                         [("justificativa", "manter", 30, "2026-09-01"), ("justificativa", "seguir", 30, "2026-09-01")])
        with self.assertRaises(NaoEncontrada):
            self.manejo.historico(self.marcos, DA_BA, 20)
        with self.assertRaises(ValueError):
            self.manejo.historico(self.val, DO_ES, "x")

    def test_varios_de_uma_vez(self):
        itens = [self.marcar(c) for c in (20, 23, 26)]
        self.copia(D(2026, 10, 2), "INSERT INTO vendas_clientes VALUES (DATE '2026-10-01', 124, 23, 'CLIENTE', 1)")
        self.manejo.sincronizar()  # o 23 voltou a comprar enquanto ela respondia
        r = self.manejo.justificar(self.val, DO_ES, {"itens": [*itens, {"id": 999999, "versao": 0}], "decisao": "seguir"})
        self.assertEqual(r["gravados"], 2)
        self.assertEqual([(x["id"], x["cliente"], x["motivo"]) for x in r["recusados"]],
                         [(itens[1]["id"], "MENSAL CINQUENTA", "saiu da lista: voltou a comprar"),
                          (999999, None, "não está mais na lista; atualize a página")])
        self.assertEqual({self.item(c)["situacao"] for c in (20, 26)}, {"justificada"})

    def test_veredito(self):
        with self.assertRaises(PermissionError):
            self.manejo.veredito(self.val, {"itens": [self.marcar(20)], "decisao": "seguir"})
        r = self.manejo.veredito(self.chefe, {"itens": [self.marcar(20)], "decisao": "seguir"})
        self.assertEqual((r["gravados"], r["recusados"][0]["motivo"]),
                         (0, "ainda sem justificativa: dá para justificar até 29/10"))
        self.manejo.justificar(self.val, DO_ES, {"itens": [self.marcar(20), self.marcar(23)], "decisao": "manter",
                                                "texto": "Voltam a comprar em outubro."})
        # continua: encerra, e o cliente não volta para a lista no mesmo mês
        r = self.manejo.veredito(self.chefe, {"itens": [self.marcar(20)], "decisao": "manter", "texto": "Combinado."})
        self.assertEqual(r, {"gravados": 1, "recusados": []})
        i = self.item(20)
        self.assertEqual((i["situacao"], i["encerrada"], i["veredito"]["decisao"], i["veredito"]["por"]),
                         ("mantida", {"em": "2026-10-01", "motivo": "mantido"}, "manter", "Chefe"))
        self.assertEqual(i["pode"], {"justificar": False, "veredito": True})
        self.manejo.sincronizar()
        self.assertEqual(self.contar("manejo_sugestoes", "id_cliente = 20"), 1)
        # seguir: espera o ERP, e a justificativa não muda mais
        self.manejo.veredito(self.chefe, {"itens": [self.marcar(23)], "decisao": "seguir"})
        self.assertEqual(self.item(23)["situacao"], "aguardando_erp")
        r = self.manejo.justificar(self.val, DO_ES, {"itens": [self.marcar(23)], "decisao": "seguir"})
        self.assertEqual(r["recusados"][0]["motivo"], "já tem veredito")
        r = self.manejo.justificar(self.val, DO_ES, {"itens": [self.marcar(20)], "decisao": "seguir"})
        self.assertEqual(r["recusados"][0]["motivo"], "já tem veredito")
        # o cliente comprou depois do veredito: a sugestão continua esperando o ERP, com os números novos
        self.copia(D(2026, 10, 2), "INSERT INTO vendas_clientes VALUES (DATE '2026-10-01', 124, 23, 'CLIENTE', 1)")
        self.manejo.sincronizar()
        i = self.item(23)
        self.assertEqual((i["situacao"], i["fatos"]["ultima_compra"]), ("aguardando_erp", "2026-10-01"))
        # o ERP mostra o cliente com a central: feito, e não dá mais para trocar
        self.copia(D(2026, 10, 5), "UPDATE clientes SET id_vendedor = 141 WHERE id = 23")
        self.manejo.sincronizar()
        i = self.item(23)
        self.assertEqual((i["situacao"], i["encerrada"], i["pode"]["veredito"]),
                         ("feita", {"em": "2026-10-05", "motivo": "aplicado"}, False))
        r = self.manejo.veredito(self.chefe, {"itens": [self.marcar(23)], "decisao": "manter"})
        self.assertEqual(r["recusados"][0]["motivo"], "o ERP já mostra como feito")
        self.assertEqual([e[:2] for e in self.eventos(23)], [("justificativa", "manter"), ("veredito", "seguir")])

    def test_inativar_feito_no_erp(self):
        self.manejo.justificar(self.marcos, DA_BA, {"itens": [self.marcar(28)], "decisao": "seguir"})
        self.manejo.veredito(self.chefe, {"itens": [self.marcar(28)], "decisao": "seguir"})
        self.copia(D(2026, 10, 2), "UPDATE clientes_detalhes SET inativo = 1 WHERE id = 28",
                   "UPDATE clientes SET id_vendedor = 144 WHERE id = 28")  # no ERP ele vai para "CLIENTES INATIVOS"
        self.manejo.sincronizar()
        i = self.item(28)
        self.assertEqual((i["situacao"], i["encerrada"]["motivo"], i["vendedor"]["nome"]), ("feita", "aplicado", "Jamille"))

    def test_continua_volta_no_mes_seguinte_e_a_troca_de_veredito(self):
        self.manejo.justificar(self.val, DO_ES, {"itens": [self.marcar(20)], "decisao": "manter",
                                                "texto": "Volta a comprar em novembro."})
        self.manejo.veredito(self.chefe, {"itens": [self.marcar(20)], "decisao": "manter"})
        self.manejo.veredito(self.chefe, {"itens": [self.marcar(20)], "decisao": "manter"})  # o mesmo de novo: nada
        self.assertEqual(len(self.eventos(20)), 2)
        self.manejo.veredito(self.chefe, {"itens": [self.marcar(20)], "decisao": "seguir"})  # trocou: reabre
        self.assertEqual((self.item(20)["situacao"], self.item(20)["encerrada"]), ("aguardando_erp", None))
        self.manejo.veredito(self.chefe, {"itens": [self.marcar(20)], "decisao": "manter", "texto": "Fica."})
        self.assertEqual(self.item(20)["situacao"], "mantida")
        self.assertEqual([e[:2] for e in self.eventos(20)], [("justificativa", "manter"), ("veredito", "manter"),
                                                             ("veredito", "seguir"), ("veredito", "manter")])
        # o prazo passou e ele continua sem comprar: entra na lista de novembro, com o histórico à vista
        self.copia(D(2026, 10, 30))
        self.manejo.sincronizar()
        novembro, outubro = self.item(20), self.item(20, "2026-10")
        self.assertEqual((novembro["situacao"], novembro["anteriores"], novembro["entrou_em"]),
                         ("a_justificar", 1, "2026-10-30"))
        self.assertEqual([s["mes"] for s in self.manejo.historico(self.chefe, None, 20)["sugestoes"]],
                         ["2026-11", "2026-10"])
        # a de outubro não volta a "seguir": o cliente já está na lista de novembro
        r = self.manejo.veredito(self.chefe, {"itens": [{"id": outubro["id"], "versao": outubro["versao"]}],
                                             "decisao": "seguir"})
        self.assertEqual(r["recusados"][0]["motivo"], "o cliente já está em outra lista em andamento")

    def test_veredito_logo_depois_do_prazo_ja_poe_na_lista_seguinte(self):
        self.manejo.justificar(self.val, DO_ES, {"itens": [self.marcar(20)], "decisao": "manter",
                                                "texto": "Volta a comprar em novembro."})
        self.copia(D(2026, 10, 30))
        self.manejo.sincronizar()
        self.assertEqual(self.contar("manejo_sugestoes", "id_cliente = 20"), 1)  # esperando o veredito: não repete
        self.manejo.veredito(self.chefe, {"itens": [self.marcar(20)], "decisao": "manter"})
        d = self.manejo.listar(self.chefe, None)  # a leitura seguinte já atualiza a lista
        self.assertIn(20, {i["cliente"]["id"] for i in d["itens"]})
        self.assertEqual(d["rodada"]["mes"], "2026-11")

    def test_cada_um_ve_os_seus(self):
        d = self.manejo.listar(self.val, DO_ES)
        self.assertEqual({i["cliente"]["id"] for i in d["itens"]}, {20, 23, 26, 30, 34})
        self.assertTrue(all(i["pode"] == {"justificar": True, "veredito": False} for i in d["itens"]))
        self.assertEqual((d["admin"], d["pode_justificar"]), (False, True))
        self.assertEqual([(v["nome"], v["equipe"]) for v in d["vendedores"]], [("Lorena", "ES"), ("Rubens", "ES")])
        d = self.manejo.listar(self.leitor, DA_BA)
        self.assertEqual({i["cliente"]["id"] for i in d["itens"]}, {24, 25, 28, 31})
        self.assertFalse(d["pode_justificar"])
        self.assertFalse(any(i["pode"]["justificar"] or i["pode"]["veredito"] for i in d["itens"]))
        self.assertEqual(self.manejo.listar(self.leitor, frozenset())["itens"], [])
        self.assertEqual(len(self.manejo.listar(self.chefe, None)["itens"]), 9)
        with self.assertRaises(ValueError):
            self.manejo.listar(self.chefe, None, "outubro")
        # um mês que não existe cai na lista aberta
        self.assertEqual(self.manejo.listar(self.chefe, None, "2025-01")["rodada"]["mes"], "2026-10")

    def test_config_dados(self):
        d = self.manejo.config_dados()
        self.assertEqual([(v["nome"], v["equipe"], v["nome_central"]) for v in d["vendedores"]],
                         [("Jamille", "BA", False), ("Thais", "BA", True), ("Lorena", "ES", True), ("Rubens", "ES", False)])
        self.assertEqual(d["prazo"], {"mes": "2026-10", "rotulo": "outubro de 2026", "data": "2026-10-29"})
        self.assertEqual((d["ativo"], d["config"]["central"], d["padrao"]), (True, [CENTRAL_ES, CENTRAL_BA], PADRAO))

    def test_duas_atualizacoes_juntas(self):
        with self.banco.conexao() as con:
            con.execute("DELETE FROM manejo_sugestoes")
        outro = Manejo(self.banco, self.calc, self.config, lambda: dict(NOMES), True, hoje=lambda: self.hoje)
        erros = []

        def rodar(m):
            try:
                m.sincronizar(forcar=True)
            except Exception as e:  # noqa: BLE001
                erros.append(e)

        threads = [threading.Thread(target=rodar, args=(m,)) for m in (self.manejo, outro)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(erros, [])
        self.assertEqual(self.contar("manejo_sugestoes"), 9)


@unittest.skipUnless(TEM_XLSX and TEM_PDF and pypdf, "sem os pacotes XlsxWriter, fpdf2 e pypdf")
class TestArquivo(Base):
    """O Excel e o PDF da tabela, como está na tela (bi/manejo.py exportar)."""

    def setUp(self):
        super().setUp()
        self.manejo.sincronizar()

    def ids(self, quem, acesso, aba: str) -> dict[int, int]:
        """{cliente: id da linha} da aba, como a pessoa vê."""
        return {x["cliente"]["id"]: x["id"] for x in self.manejo.listar(quem, acesso)["itens"] if x["sugestao"] == aba}

    def test_excel_na_ordem_da_tela_e_so_com_o_que_a_pessoa_ve(self):
        self.manejo.justificar(self.val, DO_ES, {"itens": [self.marcar(20)], "decisao": "manter",
                                                "texto": "=Em reforma, reabre dia 25."})
        central = self.ids(self.val, DO_ES, "central")
        self.assertEqual(set(central), {20, 23, 26})
        da_ba = self.ids(self.chefe, None, "central")[24]          # de um vendedor que ela não vê
        de_outra_aba = self.ids(self.chefe, None, "inativar")[30]  # da lista de inativação
        corpo = {"mes": "2026-10", "aba": "central", "formato": "excel", "filtros": "Busca: “mercado”",
                 "itens": [central[26], central[20], da_ba, de_outra_aba, central[20], 999999]}
        conteudo, nome, formato = self.manejo.exportar(self.val, DO_ES, corpo)
        self.assertEqual(formato, "excel")
        self.assertRegex(nome, r"^Manejo da Base - Passar para a central - outubro de 2026 - \d{4}-\d{2}-\d{2}\.xlsx$")
        linhas = ler_excel(conteudo, {"cliente": "Cliente", "codigo": "Código do cliente", "vendedor": "Vendedor",
                                      "dias": "Dias sem compra", "contagem": "Contagem dos dias",
                                      "situacao": "Situação", "resposta": "Resposta do supervisor",
                                      "texto": "Texto da resposta"})
        self.assertEqual([(int(x["codigo"]), x["cliente"]) for x in linhas],
                         [(26, "COMPROU ANTES DO CACHE"), (20, "MERCADO TRINTA (CLIENTE 20)")])  # a ordem da tela, sem repetir
        x = linhas[1]
        self.assertEqual((x["vendedor"], int(x["dias"]), x["contagem"], x["situacao"], x["resposta"], x["texto"]),
                         ("Rubens", 30, "desde a última compra", "Justificado", "Deve continuar com o vendedor",
                          "=Em reforma, reabre dia 25."))  # o texto fica texto, não vira fórmula
        self.assertEqual(linhas[0]["contagem"], "desde o último título de venda (antes de 2024)")
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            folha = z.read("xl/worksheets/sheet1.xml").decode()
            textos = z.read("xl/sharedStrings.xml").decode() if "xl/sharedStrings.xml" in z.namelist() else folha
        self.assertNotIn("<f>", folha)
        self.assertIn("Manejo da Base · Passar para a central · outubro de 2026", textos)
        self.assertIn("Busca: “mercado” · 2 clientes", textos)

    def test_pdf_da_inativacao_com_o_motivo(self):
        inativar = self.ids(self.chefe, None, "inativar")
        corpo = {"mes": "2026-10", "aba": "inativar", "formato": "pdf", "itens": [inativar[28], inativar[31]]}
        conteudo, nome, formato = self.manejo.exportar(self.chefe, None, corpo)
        self.assertTrue(conteudo.startswith(b"%PDF"))
        self.assertTrue(nome.startswith("Manejo da Base - Inativar - outubro de 2026 - ") and nome.endswith(".pdf"))
        texto = " ".join(" ".join(p.extract_text().split()) for p in pypdf.PdfReader(io.BytesIO(conteudo)).pages)
        self.assertIn("Inadimplente há", texto)
        self.assertIn("Na central, 61 dias sem compra", texto)
        self.assertNotIn("Código do cliente", texto)  # o código só vai no Excel

    def test_pedidos_errados(self):
        central = list(self.ids(self.val, DO_ES, "central").values())
        certo = {"mes": "2026-10", "aba": "central", "formato": "excel", "itens": central}
        for errado, msg in (({"formato": "csv"}, "Excel ou PDF"), ({"aba": "todas"}, "escolha a lista"),
                            ({"itens": []}, "nenhum cliente"), ({"itens": "1,2"}, "nenhum cliente"),
                            ({"itens": ["a"]}, "cliente inválido"), ({"itens": [999999]}, "atualize a página"),
                            ({"formato": "pdf", "itens": list(range(2001))}, "até 2000 clientes")):
            with self.subTest(errado=str(errado)[:40]), self.assertRaisesRegex(ValueError, msg):
                self.manejo.exportar(self.val, DO_ES, {**certo, **errado})
        pc = Manejo(self.banco, self.calc, self.config, lambda: dict(NOMES), False)
        with self.assertRaisesRegex(ValueError, "site"):
            pc.exportar(self.val, DO_ES, certo)


class UsuariosFalsos:
    """Só o que o Manipulador usa para saber quem pede: a sessão (o valor do cookie) -> o usuário."""

    def __init__(self, pessoas: dict):
        self.pessoas = pessoas

    def da_sessao(self, valor):
        return self.pessoas.get(valor)


class TestRotas(Base):
    def setUp(self):
        super().setUp()
        nulo = logging.NullHandler()  # o registro de quem respondeu não suja a saída dos testes
        logging.getLogger("bi").addHandler(nulo)
        self.addCleanup(logging.getLogger("bi").removeHandler, nulo)
        todos = {"modo": "todos"}
        pessoas = {"chefe": {**self.chefe, "escopo": None}, "val": {**self.val, "escopo": todos},
                   "leitor": {**self.leitor, "escopo": todos},
                   "ana": {**self.leitor, "id": 999, "paginas": ["metas"], "escopo": todos}}
        self.app = SimpleNamespace(usuarios=UsuariosFalsos(pessoas), manejo=self.manejo, vps=True)
        manipulador = type("ManipuladorDoTeste", (app.Manipulador,), {"app": self.app})  # sem mexer no global
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), manipulador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)

    def pedir(self, caminho: str, quem: str, corpo: dict | None = None):
        con = http.client.HTTPConnection("127.0.0.1", self.servidor.server_address[1], timeout=30)
        try:
            con.request("GET" if corpo is None else "POST", caminho, headers={"Cookie": f"{app.COOKIE}={quem}"},
                        body=None if corpo is None else json.dumps(corpo))
            r = con.getresponse()
            return r.status, json.loads(r.read())
        finally:
            con.close()

    def test_quem_entra(self):
        self.assertEqual(self.pedir("/api/manejo", "ninguem")[0], 401)
        self.assertEqual(self.pedir("/api/manejo", "ana"), (403, {"erro": "seu acesso não inclui a página Manejo da Base"}))
        self.assertEqual(self.pedir("/api/manejo/historico?cliente=20", "ana")[0], 403)
        corpo = {"itens": [{"id": 1, "versao": 0}], "decisao": "seguir"}
        self.assertEqual(self.pedir("/api/manejo/justificar", "ana", corpo)[0], 403)
        for quem in ("val", "leitor", "ana"):  # o veredito e a configuração são do administrador
            with self.subTest(quem=quem):
                self.assertEqual(self.pedir("/api/manejo/veredito", quem, corpo)[0], 403)
                self.assertEqual(self.pedir("/api/manejo/config", quem)[0], 403)
                self.assertEqual(self.pedir("/api/manejo/config", quem, {"config": PADRAO})[0], 403)
        self.assertEqual(self.pedir("/api/manejo/justificar", "leitor", corpo)[0], 403)  # sem a marca
        self.assertEqual(self.contar("manejo_eventos"), 0)

    def test_ler_e_responder(self):
        status, d = self.pedir("/api/manejo", "val")
        self.assertEqual((status, len(d["itens"]), d["pode_justificar"]), (200, 9, True))
        i = next(x for x in d["itens"] if x["cliente"]["id"] == 20)
        corpo = {"mes": "2026-10", "itens": [{"id": i["id"], "versao": i["versao"]}], "decisao": "manter",
                 "texto": "Em reforma, reabre dia 25."}
        status, d = self.pedir("/api/manejo/justificar", "val", corpo)
        self.assertEqual((status, d["ok"], d["gravados"], d["recusados"]), (200, True, 1, []))
        i = next(x for x in d["itens"] if x["cliente"]["id"] == 20)  # a resposta já traz a lista como ficou
        self.assertEqual(i["situacao"], "justificada")
        status, d = self.pedir("/api/manejo/justificar", "val", {**corpo, "texto": "curto"})
        self.assertEqual((status, d), (400, {"erro": "escreva por que o cliente deve continuar (pelo menos 10 letras)"}))
        status, d = self.pedir("/api/manejo/veredito", "chefe", {"mes": "2026-10", "decisao": "seguir",
                                                                 "itens": [{"id": i["id"], "versao": i["versao"]}]})
        self.assertEqual((status, d["gravados"]), (200, 1))
        status, d = self.pedir("/api/manejo/historico?cliente=20", "leitor")
        self.assertEqual((status, [e["tipo"] for e in d["sugestoes"][0]["eventos"]]), (200, ["justificativa", "veredito"]))
        self.assertEqual(self.pedir("/api/manejo/historico?cliente=5", "val")[0], 404)
        self.assertEqual(self.pedir("/api/manejo?mes=outubro", "val")[0], 400)

    @unittest.skipUnless(TEM_XLSX, "sem o pacote XlsxWriter")
    def test_baixar_a_tabela(self):
        _, d = self.pedir("/api/manejo", "val")
        corpo = {"mes": "2026-10", "aba": "central", "formato": "excel",
                 "itens": [x["id"] for x in d["itens"] if x["sugestao"] == "central"]}
        self.assertEqual(self.pedir("/api/manejo/exportar", "ana", corpo)[0], 403)
        con = http.client.HTTPConnection("127.0.0.1", self.servidor.server_address[1], timeout=30)
        try:
            con.request("POST", "/api/manejo/exportar", headers={"Cookie": f"{app.COOKIE}=leitor"},  # quem só consulta
                        body=json.dumps(corpo))
            r = con.getresponse()
            conteudo = r.read()
            self.assertEqual((r.status, r.getheader("Content-Type")),
                             (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
            self.assertIn("filename*=UTF-8''Manejo%20da%20Base%20-%20Passar", r.getheader("Content-Disposition"))
        finally:
            con.close()
        self.assertTrue(conteudo.startswith(b"PK"))
        self.assertEqual(self.pedir("/api/manejo/exportar", "val", {**corpo, "formato": "csv"}),
                         (400, {"erro": "escolha o formato: Excel ou PDF"}))


class TestDepoisDeReceber(unittest.TestCase):
    """Aplicacao.depois_de_receber: a atualização da lista roda à parte e nenhum erro dela chega ao recebimento."""

    def rodar(self, sincronizar) -> None:
        feito = threading.Event()

        def chamada():
            try:
                sincronizar()
            finally:
                feito.set()

        falso = SimpleNamespace(manejo=SimpleNamespace(sincronizar=chamada))
        nulo = logging.NullHandler()
        logging.getLogger("bi").addHandler(nulo)
        self.addCleanup(logging.getLogger("bi").removeHandler, nulo)
        propagar = logging.getLogger("bi").propagate
        logging.getLogger("bi").propagate = False  # o erro esperado não vai para a saída dos testes
        self.addCleanup(setattr, logging.getLogger("bi"), "propagate", propagar)
        app.Aplicacao.depois_de_receber(falso)
        self.assertTrue(feito.wait(5))

    def test_erros_nao_escapam(self):
        def banco_fora():
            raise BancoForaDoAr("fora")

        def quebrou():
            raise RuntimeError("quebrou")

        for sincronizar in (lambda: None, banco_fora, quebrou):
            self.rodar(sincronizar)


if __name__ == "__main__":
    unittest.main()

"""A cobertura da positivação (bi/indicadores.py _cobertura): que % da base de clientes ativos cada vendedor atendeu, mês
a mês, pelo histórico da carteira (bi/carteira.py) ou, antes dele, pela META CLIENTE da planilha de metas; a positivação
com a meta em % da base; e a cobertura gravada na base das campanhas (bi/gestao.py).

O cache sintético é o de tests/apoio.py: em setembro de 2026, o ES (Rubens) vendeu aos clientes 1 e 3 (e ao funcionário
7, que não conta), a BA (Thais) ao 2 e o Edir ao 4; em agosto, só a BA, ao 2. Na planilha, a META CLIENTE de setembro é 3
para o ES e 2 para a BA; o Edir não está nela."""
from __future__ import annotations

import datetime as dt
import unittest

from bi.gestao import Gestao, validar
from bi.indicadores import descritor, meses_cobertura, normalizar
from tests.apoio import BA, EDIR, ES, BaseBanco
from tests.test_gestao import ComCache

D = dt.date
AGOSTO, SETEMBRO = D(2026, 8, 1), D(2026, 9, 1)
# O histórico da carteira desde 01/08: o 4 é da carteira do ES (mas quem vende para ele é o Edir); o 10 foi inativado em
# 11/09 (ativo em setembro); o 11 saiu antes de setembro; o 12 passou do ES para a BA em 15/09; o 13 é "PEDIDO
# BLOQUEADO" (fica fora da base).
VIGENCIAS = [
    (1, AGOSTO, None, ES, False, "ES", 1, "ROTA 1", "MERCADO"),
    (3, AGOSTO, None, ES, False, "ES", 1, "ROTA 1", "AÇOUGUE"),
    (4, AGOSTO, None, ES, False, "BA", 9, "ROTA 9", "MERCEARIA"),
    (10, AGOSTO, D(2026, 9, 10), ES, False, "ES", 3, "ROTA 3 (SEXTA)", "HOTEL E POUSADA"),
    (11, AGOSTO, D(2026, 8, 31), ES, False, "ES", 3, "ROTA 3 (SEXTA)", "HOTEL E POUSADA"),
    (12, AGOSTO, D(2026, 9, 14), ES, False, "BA", 2, "ROTA 2", "PADARIA"),
    (12, D(2026, 9, 15), None, BA, False, "BA", 2, "ROTA 2", "PADARIA"),
    (2, AGOSTO, None, BA, False, "BA", 2, "ROTA 2", "PADARIA"),
    (13, AGOSTO, None, BA, True, "BA", 2, "ROTA 2", "RESTAURANTE"),
]


class Base(ComCache):
    def medir(self, parametros=None, filtros=None, meta=0.0, abrir=None, inicio=SETEMBRO, fim=D(2026, 9, 30)):
        from bi.gestao import andamento
        c = {**self.campanha("positivacao", filtros, meta, inicio=inicio, fim=fim), "parametros": parametros or {}}
        a = andamento(self.cur, c, self.regras, self.cal, D(2026, 9, 30), None, None, abrir)
        return {v["id"]: v for v in a["vendedores"]}, a

    @staticmethod
    def pct(por):
        return {v: (x["da_base"] or {}).get("pct") for v, x in por.items()}


class TestPelaPlanilha(Base, unittest.TestCase):
    def setUp(self):
        self.montar_cache(extras=True)

    def tearDown(self):
        self.desmontar_cache()

    def test_atendidos_sobre_a_meta_cliente(self):
        # sem o histórico, setembro sai da planilha: todos os clientes que o vendedor atendeu ÷ a META CLIENTE
        por, a = self.medir()
        self.assertEqual({v: x["realizado"] for v, x in por.items()}, {ES: 2, BA: 1, EDIR: 1})  # a positivação igual
        self.assertEqual({v: (x["da_base"]["atendidos"], x["da_base"]["ativos"]) for v, x in por.items()},
                         {ES: (2, 3), BA: (1, 2), EDIR: (0, 0)})
        self.assertEqual(self.pct(por), {ES: 0.6667, BA: 0.5, EDIR: None})
        self.assertEqual((por[ES]["da_base"]["fontes"], por[EDIR]["da_base"]["falta"]), (["planilha"], ["09/2026"]))
        self.assertEqual((a["total"]["da_base"]["pct"], a["total"]["da_base"]["ativos"]), (0.6, 5))
        self.assertIn("1 vendedor sem a META CLIENTE", a["avisos"][0])
        # o filtro de produto vale no numerador; o de cliente, sem saber quais são os clientes, deixa sem %
        por, _ = self.medir(filtros={"produtos": [32]})
        self.assertEqual(self.pct(por), {ES: 0.3333, BA: 0.5, EDIR: None})
        por, a = self.medir(filtros={"ufs": ["ES"]})
        self.assertEqual(self.pct(por), {ES: None, BA: None, EDIR: None})
        self.assertIn("com filtro de cliente", a["avisos"][0])
        # com outra base de clientes (novos, recuperados...) não há %
        por, _ = self.medir({"clientes": "novos"})
        self.assertNotIn("da_base", por[ES])

    def test_positivacao_em_pct_da_base(self):
        por, a = self.medir({"meta_em": "pct_base"}, meta=60)
        self.assertEqual({v: (x["realizado"], x["meta"], x["status"]) for v, x in por.items()},
                         {ES: (0.6667, 0.6, "batida"), BA: (0.5, 0.6, "abaixo"), EDIR: (None, 0.6, "sem_dados")})
        self.assertEqual((por[ES]["numerador"], por[ES]["denominador"], por[ES]["meses"]), (2, 3, 1))
        self.assertEqual((a["total"]["realizado"], a["total"]["numerador"], a["total"]["denominador"]), (0.6, 3, 5))
        d = descritor("positivacao", {"clientes": "todos", "meta_em": "pct_base"})
        self.assertEqual((d["nome"], d["formato"], d["comportamento"], d["meta_em_pct"], d["cobertura"]),
                         ("Positivação em % da base", "pct", "acumula_taxa", True, True))

    def test_normalizar(self):
        self.assertEqual(normalizar("positivacao", {"meta_em": "pct_base"}),
                         ("positivacao", {"clientes": "todos", "meta_em": "pct_base"}))
        self.assertEqual(normalizar("positivacao", {"meta_em": "clientes"}), ("positivacao", {"clientes": "todos"}))
        with self.assertRaises(ValueError):
            normalizar("positivacao", {"meta_em": "pct_base", "clientes": "novos"})
        with self.assertRaises(ValueError):
            normalizar("positivacao", {"meta_em": "vendedores"})
        # a cobertura da carteira de antes só nas campanhas que já eram dela
        dados = {"nome": "Carteira", "regiao": "BA", "inicio": "2026-10-01", "fim": "2026-10-31", "metrica": "personalizada",
                 "parametros": {"medida": "clientes", "forma": "pct_carteira"}, "meta_padrao": 60, "vendedores": [BA]}
        with self.assertRaises(ValueError) as e:
            validar(dados, self.cur, self.regras, None, D(2026, 9, 30))
        self.assertIn("meta_em pct_base", str(e.exception))
        antes = {"base_periodo": "mes", "alvo_tipo": "fixo", "parametros": {"medida": "clientes", "forma": "pct_carteira"}}
        self.assertEqual(validar(dados, self.cur, self.regras, None, D(2026, 9, 30), antes=antes)["parametros"]["forma"],
                         "pct_carteira")

    def test_meses_da_cobertura(self):
        # até 31 dias: uma parte, com os ativos do mês em que o período termina
        self.assertEqual(meses_cobertura(D(2026, 9, 15), D(2026, 10, 14), D(2026, 10, 14)),
                         [(D(2026, 10, 1), D(2026, 9, 15), D(2026, 10, 14))])
        self.assertEqual(meses_cobertura(D(2026, 9, 15), D(2026, 10, 14), D(2026, 9, 30)),  # ainda correndo
                         [(D(2026, 10, 1), D(2026, 9, 15), D(2026, 9, 30))])
        # acima disso: um por mês do calendário, com os dias do período em cada um
        self.assertEqual(meses_cobertura(D(2026, 9, 15), D(2026, 10, 16), D(2026, 10, 16)),
                         [(D(2026, 9, 1), D(2026, 9, 15), D(2026, 9, 30)), (D(2026, 10, 1), D(2026, 10, 1), D(2026, 10, 16))])
        self.assertEqual(meses_cobertura(D(2026, 7, 1), D(2026, 9, 30), D(2026, 8, 15)),
                         [(D(2026, 7, 1), D(2026, 7, 1), D(2026, 7, 31)), (D(2026, 8, 1), D(2026, 8, 1), D(2026, 8, 15))])
        self.assertEqual(meses_cobertura(D(2026, 10, 1), D(2026, 10, 31), D(2026, 9, 30)), [])

    def test_sem_o_historico_espera(self):
        # outubro é do histórico (HISTORICO_DESDE); o cache ainda sem nenhum dia conferido: a cobertura espera
        por, a = self.medir(inicio=D(2026, 9, 20), fim=D(2026, 10, 19))
        self.assertEqual({v: (x["da_base"]["pct"], x["da_base"]["pendente"]) for v, x in por.items()},
                         {ES: (None, True), BA: (None, True), EDIR: (None, True)})
        self.assertIn("histórico da carteira ainda não chegou", a["avisos"][0])


class TestPeloHistorico(Base, unittest.TestCase):
    def setUp(self):
        self.montar_cache(extras=True, vigencias=VIGENCIAS, retratos=[(AGOSTO, 9, 9, 0, 0)],
                          metas_cli={(AGOSTO, ES): 4, (AGOSTO, BA): 2})

    def tearDown(self):
        self.desmontar_cache()

    def test_carteira_atendida_pelo_vendedor(self):
        # setembro: a carteira do ES é 1, 3, 4 e 10 (o 11 saiu em agosto; o 12 foi para a BA); ele atendeu o 1 e o 3 (o
        # 4 comprou do Edir: não conta). A BA: 2 e 12 (o 13 está bloqueado); atendeu o 2. O Edir não tem carteira
        por, a = self.medir()
        self.assertEqual({v: (x["da_base"]["atendidos"], x["da_base"]["ativos"]) for v, x in por.items()},
                         {ES: (2, 4), BA: (1, 2), EDIR: (0, 0)})
        self.assertEqual(self.pct(por), {ES: 0.5, BA: 0.5, EDIR: None})
        self.assertEqual((por[ES]["da_base"]["fontes"], a["total"]["da_base"]["pct"]), (["historico"], 0.5))
        # o filtro de cliente vale pelo trecho: as padarias da carteira da BA são o 2 e o 12
        por, _ = self.medir(filtros={"segmentos": ["PADARIA"]})
        self.assertEqual(self.pct(por), {ES: None, BA: 0.5, EDIR: None})
        # a positivação em % da base aberta por área
        _, a = self.medir({"meta_em": "pct_base"}, meta=50, abrir="area")
        self.assertEqual({x["nome"]: (x["valor"], x["numerador"], x["denominador"]) for x in a["abertura"]["linhas"]},
                         {"ROTA 1": (1.0, 2, 2), "ROTA 2": (0.5, 1, 2), "ROTA 9": (0.0, 0, 1),
                          "ROTA 3 (SEXTA)": (0.0, 0, 1)})

    def test_media_dos_meses(self):
        # agosto e setembro (61 dias): a média dos dois meses. Agosto: a carteira do ES é 1, 3, 4, 10, 11 e 12, sem
        # venda (0%); a da BA é só o 2, que comprou (100%)
        por, a = self.medir(inicio=AGOSTO, fim=D(2026, 9, 30))
        self.assertEqual(self.pct(por), {ES: 0.25, BA: 0.75, EDIR: None})
        self.assertEqual((por[ES]["da_base"]["meses"], por[ES]["da_base"]["atendidos"], por[ES]["da_base"]["ativos"]),
                         (2, 2, 10))
        self.assertAlmostEqual(a["total"]["da_base"]["pct"], (1 / 7 + 3 / 6) / 2, places=4)

    def test_planilha_antes_do_historico(self):
        # o histórico começando em 01/09: agosto sai da planilha (META CLIENTE 4 e 2) e setembro do histórico
        self.desmontar_cache()
        self.montar_cache(extras=True, vigencias=VIGENCIAS, retratos=[(SETEMBRO, 9, 9, 0, 0)],
                          metas_cli={(AGOSTO, ES): 4, (AGOSTO, BA): 2})
        por, _ = self.medir(inicio=AGOSTO, fim=D(2026, 9, 30))
        self.assertEqual(self.pct(por), {ES: 0.25, BA: 0.5, EDIR: None})  # ES: (0/4 + 2/4) ÷ 2; BA: (1/2 + 1/2) ÷ 2
        self.assertEqual(por[ES]["da_base"]["fontes"], ["historico", "planilha"])
        # com o histórico começando no meio de setembro (como a semeadura de 15/09), setembro ainda é da planilha
        self.desmontar_cache()
        self.montar_cache(extras=True, vigencias=VIGENCIAS, retratos=[(D(2026, 9, 15), 9, 9, 0, 0)])
        por, _ = self.medir()
        self.assertEqual((self.pct(por), por[ES]["da_base"]["fontes"]), ({ES: 0.6667, BA: 0.5, EDIR: None}, ["planilha"]))


HOJE = D(2026, 10, 1)


class TestCoberturaNoBanco(ComCache, BaseBanco):
    """A cobertura gravada na base das campanhas de positivação (base_cobertura, migração 016)."""

    def setUp(self):
        super().setUp()
        self.montar_cache(extras=True)
        self.gestao = Gestao(self.banco, self.calc, self.assistente, hoje=lambda: HOJE)
        self.chefe = {"id": self.criar_usuario("chefe", "admin"), "login": "chefe", "nome": "Chefe", "papel": "admin"}

    def tearDown(self):
        self.desmontar_cache()
        super().tearDown()

    def criar(self, **mudancas):
        dados = {"nome": "Positivar", "regiao": "BA", "inicio": "2026-10-01", "fim": "2026-10-31", "metrica": "positivacao",
                 "base_periodo": "mes", "alvo_tipo": "fixo", "meta_padrao": 2, "vendedores": [BA, EDIR], **mudancas}
        return self.gestao.criar(self.chefe, dados)["id"]

    def gravado(self, id_):
        with self.banco.conexao() as con:
            return {v: (b, n, d, c) for v, b, n, d, c in con.execute(
                "SELECT id_vendedor, base, base_num, base_den, base_cobertura FROM campanha_vendedores WHERE campanha = %s",
                [id_])}

    def test_base_com_a_cobertura(self):
        id_ = self.criar()
        g = self.gravado(id_)
        self.assertEqual(g[BA][0], 1)  # a base é o número de clientes; a cobertura vai ao lado
        self.assertEqual((g[BA][3]["atendidos"], g[BA][3]["ativos"], g[BA][3]["pct"]), (1, 2, 0.5))
        self.assertEqual((g[EDIR][3]["pct"], g[EDIR][3]["falta"]), (None, ["2026-09"]))
        linhas = {x["id"]: x for x in self.gestao.detalhe(self.chefe, (None, None), id_)["linhas"]}
        self.assertEqual((linhas[BA]["base_da_base"]["pct"], linhas[EDIR]["base_da_base"]["falta"]), (0.5, ["09/2026"]))
        # a base de antes da 016 (sem a cobertura) mede só ela na próxima leitura, sem mexer na base nem no alvo
        with self.banco.conexao() as con:
            con.execute("UPDATE campanha_vendedores SET base_cobertura = NULL, base = 7 WHERE campanha = %s", [id_])
        self.gestao.quadro(self.chefe, (None, None), "BA")
        g = self.gravado(id_)
        self.assertEqual((g[BA][0], g[BA][3]["pct"]), (7, 0.5))
        # a prévia da base do formulário também traz a cobertura
        previa = self.gestao.previa_base(self.chefe, {"regiao": "BA", "inicio": "2026-10-01", "fim": "2026-10-31",
                                                      "base_periodo": "mes", "metrica": "positivacao"}, [BA, EDIR])
        self.assertEqual((previa["vendedores"][str(BA)], previa["coberturas"][str(BA)]["pct"]), (1, 0.5))

    def test_meta_em_pct_da_base(self):
        id_ = self.criar(parametros={"meta_em": "pct_base"}, alvo_tipo="pct", meta_padrao=10)
        g = self.gravado(id_)
        self.assertEqual(g[BA][:3], (0.5, 1, 2))  # a base é a cobertura; a meta, a base + 10%
        d = self.gestao.detalhe(self.chefe, (None, None), id_)
        ba = next(x for x in d["linhas"] if x["id"] == BA)
        self.assertEqual((ba["base"], ba["alvo"], d["item"]["rotulo"]), (0.5, 0.55, "Cobertura"))
        self.assertEqual(d["indicador"]["meta_em"], "pct_base")


if __name__ == "__main__":
    unittest.main()

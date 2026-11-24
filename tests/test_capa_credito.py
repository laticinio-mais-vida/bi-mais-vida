"""A capa de análise de crédito (bi/capa_credito.py), de um cadastro novo ou de uma reanálise.

Sem banco:
- a capa (pesos e opções da planilha);
- os itens do Serasa e do histórico Mais Vida, nas bordas;
- a faixa pela pontuação;
- o quadro inteiro (porte × faixa, em escada, como no desenho da planilha);
- o prazo "dentro do indicado";
- o exemplo da capa de 30/09.

Com o banco:
- enviar o PDF (gravado sem código) e analisar (os itens automáticos calculados no servidor);
- o CNPJ que já é cliente (o histórico Mais Vida do ERP; dois códigos com o mesmo CNPJ);
- registrar (as conferências, a mesma chave, os dados do ERP que mudaram), listar com a situação no ERP, excluir e o
  acesso por vendedor;
- a página do cliente (o Serasa e a capa ligados pelo CNPJ, e o prazo mínimo entre reanálises contando dela);
- a capa de reanálise (o cliente escolhido, o Serasa dele, o histórico Mais Vida dele, o limite e o prazo de antes, o
  acesso e o prazo mínimo entre reanálises);
- o cache sem o CNPJ dos clientes;
- o PC que só avisa.

Usa o cache sintético de tests/apoio.py (hoje do crédito = 01/10/2026) e o banco de teste (BI_TESTE_POSTGRES).
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from bi.capa_credito import (AVISO_PC, CAPA, DADOS_NOVOS, PORTES, CapasCredito, faixa, faixa_de_pontualidade,
                             indicar, nome_prazo, opcao_da_fundacao, pontuar, prazo_dentro, respostas_historico,
                             respostas_serasa)
from bi.conversas import NaoEncontrada, novo_id
from bi.credito import Credito
from bi.reanalise import ConfigCredito, Reanalises
from bi.serasa import DadosSerasa
from tests.apoio import BA, ES, NOMES, BaseBanco, criar_calc
from tests.test_serasa import pdf, relato

# O que o analista responde na capa de 30/09 (comercial e jurídico).
ANALISTA = {"infraestrutura": "otimo", "limpeza": "otimo", "ponto_proprio": "sim", "residencia": "sim",
            "juridico": "nada_consta"}
NOVO_CNPJ = "62.237.700/0001-51"


def serasa_de_30_09() -> dict:
    """O envio do Serasa da capa de 30/09 (o PDF de 29/09/2026), no formato da página (DadosSerasa)."""
    anotacoes = [{"chave": k, "rotulo": k, "quantidade": 0, "valor": 0.0} for k in ("pefin", "refin", "protestos")]
    return {"score": {"valor": 214, "probabilidade": 0.0373, "risco": "Médio", "alerta": None,
                      "recomendacao": {"texto": "Venda com garantias adicionais", "chave": "garantias"}},
            "fundacao": "2025-08-14", "pontualidade": [], "faixas": [], "anotacoes": anotacoes}


def texto_30_09(cnpj: str = NOVO_CNPJ, **outros) -> str:
    """O Relato no formato de tests/test_serasa.py com os números da capa de 30/09: score 214, sem histórico de
    pagamento, fundada em 14/08/2025."""
    return (relato(cnpj=cnpj, historico=False, **outros).replace("\n376\n", "\n214\n")
            .replace("25/11/2020", "14/08/2025"))


class TestRegra(unittest.TestCase):
    def test_a_capa_da_planilha(self):
        self.assertEqual(len(CAPA), 14)
        self.assertEqual(sum(x["peso"] for x in CAPA), 100)
        pesos = {x["chave"]: x["peso"] for x in CAPA}
        self.assertEqual(pesos, {"score": 5, "recomendacao": 14, "risco": 14, "fundacao": 9, "pontualidade_serasa": 10,
                                 "anotacoes": 9, "pontualidade_mv": 10, "ultimas_compras": 2, "frequencia": 5,
                                 "infraestrutura": 5, "limpeza": 5, "ponto_proprio": 4, "residencia": 4, "juridico": 4})

    def test_o_exemplo_de_30_09(self):
        r = {**respostas_serasa(serasa_de_30_09(), dt.date(2026, 9, 30)), **respostas_historico(None),
             **{k: {"opcao": v} for k, v in ANALISTA.items()}}
        p = pontuar(r)
        pontos = {x["chave"]: x["pontos"] for x in p["itens"]}
        self.assertEqual(pontos, {"score": 1, "recomendacao": 7, "risco": 8, "fundacao": 3, "pontualidade_serasa": 0,
                                  "anotacoes": 9, "pontualidade_mv": 0, "ultimas_compras": 0, "frequencia": 0,
                                  "infraestrutura": 5, "limpeza": 5, "ponto_proprio": 4, "residencia": 4, "juridico": 4})
        self.assertEqual((p["pontos"], p["faltam"]), (50, []))
        self.assertEqual(r["fundacao"]["fonte"], "fundada em 14/08/2025, há 1 ano e 1 mês")
        self.assertEqual(faixa(50)["faixa"], 1)
        i = indicar(1, "C")
        self.assertEqual((i["limite_sugerido"], i["limite_maximo"], i["prazo_sugerido"], i["prazo_maximo"], i["parcelas"]),
                         (400.0, 3000.0, "05 DIAS", "07 DIAS", 1))

    def test_bordas(self):
        def score(v):
            return respostas_serasa({"score": {"valor": v}}, dt.date(2026, 1, 1))["score"]["opcao"]
        self.assertEqual([score(v) for v in (0, 300, 301, 500, 501, 700, 701, 1000)],
                         ["baixo", "baixo", "regular", "regular", "bom", "bom", "muito_bom", "muito_bom"])
        self.assertEqual([opcao_da_fundacao(m) for m in (0, 3, 4, 12, 13, 36, 37, 60, 61, 120, 121)],
                         ["novo", "novo", "recente", "recente", "jovem", "jovem", "media", "media", "madura", "madura",
                          "consolidada"])
        self.assertEqual([faixa_de_pontualidade(p) for p in (0, 15.9, 16, 30, 31, 50, 51, 70, 71, 94.9, 95, 100)],
                         ["0_15", "0_15", "16_30", "16_30", "31_50", "31_50", "51_70", "51_70", "71_95", "71_95",
                          "95_100", "95_100"])
        self.assertEqual(faixa_de_pontualidade(0.29 * 100), "16_30")  # 28,999… do float não cai na faixa de baixo
        self.assertEqual([faixa(p)["faixa"] for p in (0, 39, 40, 54, 55, 64, 65, 74, 75, 100)],
                         [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
        # 12 meses e alguns dias ainda é Recente; 13 meses completos já é Jovem (decisão: pelos meses)
        self.assertEqual(respostas_serasa({"fundacao": "2025-08-14"}, dt.date(2026, 9, 13))["fundacao"]["opcao"],
                         "recente")
        self.assertEqual(respostas_serasa({"fundacao": "2025-08-14"}, dt.date(2026, 9, 14))["fundacao"]["opcao"],
                         "jovem")

    def test_o_quadro_inteiro(self):
        # (sugerido, máximo) de cada porte em cada faixa, a tabela do plano aprovado
        esperado = {
            "E": [(400, 400), (400, 1000), (700, 1000), (700, 1000)],
            "D": [(400, 1000), (400, 1500), (700, 2000), (2000, 3000)],
            "C": [(400, 3000), (400, 3750), (700, 4500), (2000, 6000)],
            "B": [(400, 6000), (400, 8250), (700, 10500), (2000, 15000)],
            "A": [(400, 6000), (400, 8250), (700, 10500), (2000, 15000)],
        }
        parcelas = {"E": [1, 2, 2, 2], "D": [1, 2, 2, 2], "C": [1, 2, 3, 3], "B": [1, 2, 3, 4], "A": [1, 2, 3, 4]}
        for porte, linhas in esperado.items():
            for f, (sug, maxi) in enumerate(linhas, 1):
                i = indicar(f, porte)
                self.assertEqual((i["limite_sugerido"], i["limite_maximo"], i["parcelas"]),
                                 (sug, maxi, parcelas[porte][f - 1]), (porte, f))
                self.assertEqual(i["diretoria"], porte == "A", (porte, f))
                self.assertEqual(i["faixa_vazia"], (porte, f) == ("E", 4), (porte, f))
        i = indicar(4, "B")
        self.assertEqual((i["prazo_sugerido"], i["prazo_maximo"], i["dias_maximos"]),
                         ("05, 12, 19 E 26 DIAS", "07, 14, 21 E 29 DIAS", [7, 14, 21, 29]))
        self.assertEqual(indicar(3, "C")["prazo_sugerido"], "05, 12 E 19 DIAS")
        self.assertEqual(indicar(3, "D")["prazo_maximo"], "07 E 14 DIAS")  # a faixa daria 3, mas o porte vai até 2
        sem = indicar(0, "A")
        self.assertEqual((sem["sem_prazo"], sem["limite_maximo"], sem["prazo_sugerido"], sem["diretoria"]),
                         (True, 0.0, "A VISTA", False))
        with self.assertRaises(ValueError):
            indicar(2, "X")
        self.assertEqual(set(PORTES), {"A", "B", "C", "D", "E"})

    def test_prazo_dentro_do_indicado(self):
        tres = indicar(3, "C")  # 3 parcelas: até 7, 14 e 21
        dentro = ["A VISTA", "04 DIAS", "07 DIAS", "07 E 14 DIAS", "05, 12 E 19 DIAS", "07, 14 E 21 DIAS"]
        fora = ["10 DIAS", "14 E 21 DIAS", "07, 14, 21 E 28 DIAS", "01, 30, 60 DIAS", "SEM NUMERO"]
        self.assertEqual([prazo_dentro(x, tres) for x in dentro], [True] * len(dentro))
        self.assertEqual([prazo_dentro(x, tres) for x in fora], [False] * len(fora))
        self.assertTrue(prazo_dentro("07, 14, 21 E 28 DIAS", indicar(4, "B")))  # a 4ª parcela vai até 29
        sem = indicar(0, "C")
        self.assertEqual((prazo_dentro("A VISTA", sem), prazo_dentro("07 DIAS", sem)), (True, False))
        self.assertEqual((nome_prazo([]), nome_prazo([7]), nome_prazo([7, 14])), ("A VISTA", "07 DIAS", "07 E 14 DIAS"))

    def test_o_que_o_pdf_nao_traz_o_analista_escolhe(self):
        r = respostas_serasa({"score": {"valor": 500, "risco": "Moderado"}, "pontualidade": [{"chave": "8_15"}],
                              "anotacoes": []}, dt.date(2026, 1, 1))
        self.assertEqual({k: x["opcao"] for k, x in r.items()},
                         {"score": "regular", "recomendacao": None, "risco": None, "fundacao": None,
                          "pontualidade_serasa": None, "anotacoes": None})
        self.assertIn("“Moderado” não está na capa", r["risco"]["fonte"])
        # o envio lido antes da capa não tem a chave da recomendação (o relatório tinha, o painel não guardava)
        self.assertIn("lido antes de o painel guardar a recomendação", r["recomendacao"]["fonte"])
        novo = respostas_serasa({"score": {"valor": 500, "recomendacao": None}}, dt.date(2026, 1, 1))
        self.assertEqual(novo["recomendacao"]["fonte"], "o relatório não trouxe a recomendação: escolha olhando o PDF")
        # anotações: nenhuma = automático; alguma (ou ilegível) = o analista escolhe, vendo a lista
        a = respostas_serasa({"anotacoes": [{"rotulo": "Pendências comerciais (PEFIN)", "quantidade": 1, "valor": 195.23},
                                            {"rotulo": "Protestos", "quantidade": None, "valor": None},
                                            {"rotulo": "Cheques", "quantidade": 0, "valor": 0.0}]},
                             dt.date(2026, 1, 1))["anotacoes"]
        self.assertEqual(a["opcao"], None)
        self.assertEqual(a["fonte"], "Pendências comerciais (PEFIN): 1 (R$ 195,23); Protestos: não deu para ler. "
                                     "Escolha a relevância")
        # a pontualidade em R$ vale o menor valor da faixa
        p = respostas_serasa({"pontualidade": [{"chave": "pontual", "percentual": {"texto": "93% - 95%", "de": 0.93,
                                                                                    "ate": 0.95}}]},
                             dt.date(2026, 1, 1))["pontualidade_serasa"]
        self.assertEqual((p["opcao"], p["fonte"]), ("71_95", "pontual 93% - 95% em R$ (vale o menor, 93%)"))
        riscos = {x: respostas_serasa({"score": {"valor": 1, "risco": x}}, dt.date(2026, 1, 1))["risco"]["opcao"]
                  for x in ("Iminente", "Alto", "Médio", "Baixo", "Mínimo")}
        self.assertEqual(riscos, {"Iminente": "iminente", "Alto": "relevante", "Médio": "baixo_medio",
                                  "Baixo": "muito_baixo", "Mínimo": "minimo"})

    def test_historico_mais_vida_de_quem_ja_e_cliente(self):
        r = respostas_historico({"id": 9, "nome": "X", "quitados": 20, "pontuais": 19, "pontualidade": 0.95,
                              "ultima_compra": dt.date(2026, 9, 1), "dias_sem_compra": 44, "dias_com_compra_90": 6})
        self.assertEqual({k: x["opcao"] for k, x in r.items()},
                         {"pontualidade_mv": "95_100", "ultimas_compras": "comprou", "frequencia": "6"})
        r = respostas_historico({"id": 9, "nome": "X", "quitados": 0, "pontuais": 0, "pontualidade": None,
                              "ultima_compra": dt.date(2026, 8, 1), "dias_sem_compra": 45, "dias_com_compra_90": 3})
        self.assertEqual({k: x["opcao"] for k, x in r.items()},
                         {"pontualidade_mv": "sem_historico", "ultimas_compras": "nao_comprou", "frequencia": "2_3"})


class Base(BaseBanco):
    cnpj = True
    linhas_cnpj = None

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        extra = {} if self.linhas_cnpj is None else {"linhas_cnpj": self.linhas_cnpj}
        self.calc = criar_calc(Path(self._tmp.name), cnpj=self.cnpj, **extra)
        self.credito = Credito(self.calc.cache, lambda: dict(NOMES))
        self.config = ConfigCredito(self.banco)
        self.serasa = DadosSerasa(self.banco, self.credito, ativo=True, config=self.config)
        self.cad = CapasCredito(self.banco, self.credito, self.serasa, ativo=True)
        self.cad.hoje = lambda: dt.date(2026, 9, 30)
        self.admin = self.usuario("chefe", "admin")
        self.ana = self.usuario("ana")
        self.bia = self.usuario("bia")

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()
        super().tearDown()

    def usuario(self, login: str, papel: str = "visualizador") -> dict:
        id_ = self.criar_usuario(login, papel, None if papel == "admin" else ["credito"])
        return {"id": id_, "login": login, "nome": login.title(), "papel": papel}

    def enviar(self, texto: str | None = None, quem=None) -> dict:
        return self.cad.enviar_serasa(quem or self.ana, pdf(texto or texto_30_09()))

    def dados(self, serasa_id: int, **mudar) -> dict:
        """O que a página manda para registrar."""
        return {"chave": novo_id(), "serasa_id": serasa_id, "nome": "MERCADO NOVO", "id_vendedor": ES, "porte": "C",
                "respostas": dict(ANALISTA), "limite": 400, "prazo": "07 DIAS", "observacoes": "",
                "justificativa": "Cliente novo indicado pelo Rubens; loja bem montada.", "dados_ate": None, **mudar}


class TestAnalise(Base):
    def test_cliente_novo_a_capa_de_30_09(self):
        r = self.enviar()
        self.assertFalse(r["ja_existia"])
        self.assertEqual((r["serasa"]["cnpj"], r["serasa"]["cnpj_digitos"], r["serasa"]["do_cadastro"]),
                         (NOVO_CNPJ, "62237700000151", True))
        self.assertEqual((r["ja_cliente"], r["historico_de"], r["dados_ate"]), ([], None, None))
        auto = {x["chave"]: (x["opcao"], x["auto"]) for x in r["itens"] if x["origem"] != "analista"}
        self.assertEqual(auto, {"score": ("baixo", True), "recomendacao": ("garantias", True),
                                "risco": ("baixo_medio", True), "fundacao": ("jovem", True),
                                "pontualidade_serasa": ("sem_historico", True), "anotacoes": ("sem", True),
                                "pontualidade_mv": ("sem_historico", True), "ultimas_compras": ("nao_comprou", True),
                                "frequencia": ("nenhuma", True)})
        self.assertEqual((r["pontos"], r["completa"], r["indicacao"]), (28, False, None))
        self.assertEqual((len(r["faltam"]), r["tipo"], r["cliente"]), (5, "cadastro", None))
        # o analista responde o resto: 50 pontos, faixa 1; com o porte, a indicação
        a = self.cad.analisar({"serasa_id": r["serasa"]["id"], "respostas": ANALISTA}, self.ana)
        self.assertEqual((a["pontos"], a["completa"], a["faixa"]["faixa"], a["indicacao"]), (50, True, 1, None))
        a = self.cad.analisar({"serasa_id": r["serasa"]["id"], "respostas": ANALISTA, "porte": "C"}, self.ana)
        i = a["indicacao"]
        self.assertEqual((i["limite_sugerido"], i["limite_maximo"], i["prazo_sugerido"], i["prazo_maximo"]),
                         (400.0, 3000.0, "05 DIAS", "07 DIAS"))
        self.assertEqual(a["prazos_dentro"], ["A VISTA", "07 DIAS"])  # dos prazos do ERP (o 28 DIAS passa)
        # o mesmo PDF de novo não grava outra vez (os mesmos bytes: o PDF de teste leva a hora em que foi feito)
        conteudo = pdf(texto_30_09())
        self.cad.enviar_serasa(self.ana, conteudo)
        n = self.contar("credito_serasa")
        self.assertEqual((self.cad.enviar_serasa(self.bia, conteudo)["ja_existia"], self.contar("credito_serasa")),
                         (True, n))

    def test_a_pagina_nao_muda_os_itens_automaticos(self):
        r = self.enviar()
        a = self.cad.analisar({"serasa_id": r["serasa"]["id"], "porte": "C",
                               "respostas": {**ANALISTA, "score": "muito_bom", "frequencia": "6", "limpeza": "nada"}},
                              self.ana)
        x = {i["chave"]: i["opcao"] for i in a["itens"]}
        self.assertEqual((x["score"], x["frequencia"], x["limpeza"]), ("baixo", "nenhuma", None))  # opção que não existe
        self.assertFalse(a["completa"])

    def test_anotacoes_o_analista_escolhe(self):
        r = self.enviar(texto_30_09(anotacoes={"pefin": "1 05/2026 R$ 195,23"}))
        x = next(i for i in r["itens"] if i["chave"] == "anotacoes")
        self.assertEqual((x["opcao"], x["auto"]), (None, False))
        self.assertIn("(R$ 195,23)", x["fonte"])
        a = self.cad.analisar({"serasa_id": r["serasa"]["id"], "porte": "C",
                               "respostas": {**ANALISTA, "anotacoes": "baixa"}}, self.ana)
        self.assertEqual((a["pontos"], a["completa"]), (46, True))  # baixa = 5 no lugar de 9

    def test_cnpj_que_ja_e_cliente_usa_o_historico_do_erp(self):
        r = self.enviar(texto_30_09(cnpj="11.222.333/0001-81"))
        self.assertEqual([c["id"] for c in r["ja_cliente"]], [1])
        self.assertEqual((r["historico_de"], r["dados_ate"]), ({"id": 1, "nome": "MERCADO DO JOAO"}, "2026-10-01T08:00:00"))
        x = {i["chave"]: (i["opcao"], i["fonte"]) for i in r["itens"]}
        # cliente 1: 1 de 2 títulos pagos em dia nos 12 meses; última compra em 02/09 (29 dias antes da extração)
        self.assertEqual(x["pontualidade_mv"], ("31_50", "1 de 2 títulos pagos em dia nos últimos 12 meses (50%) "
                                                         "(código 1)"))
        self.assertEqual(x["ultimas_compras"][0], "comprou")
        self.assertEqual(x["frequencia"][0], "1")

    def test_pdf_que_nao_e_o_relato(self):
        with self.assertRaises(ValueError):
            self.cad.enviar_serasa(self.ana, b"nada")
        with self.assertRaises(NaoEncontrada):
            self.cad.analisar({"serasa_id": 999}, self.ana)
        self.assertEqual(self.contar("credito_serasa"), 0)


class TestRegistrar(Base):
    def test_grava_e_lista(self):
        r = self.enviar()
        novo = self.cad.registrar(self.ana, self.dados(r["serasa"]["id"], observacoes="  Visitado em 29/09.  "))
        self.assertFalse(novo["ja_existia"])
        with self.banco.conexao() as con:
            linha = con.execute(
                "SELECT cnpj, cliente, razao_social, id_vendedor, vendedor, serasa_id, porte, pontos, faixa, "
                "limite_sugerido, limite_maximo, limite_concedido, prazo_concedido, observacoes, id_cliente_historico, "
                "dados_ate, regra_versao, feita_por_nome, respostas, indicacao FROM credito_capas").fetchone()
        self.assertEqual(linha[:18], ("62237700000151", "MERCADO NOVO", "JOAO COMERCIO LTDA EPP", ES, "Rubens",
                                      r["serasa"]["id"], "C", 50, 1, Decimal("400.00"), Decimal("3000.00"),
                                      Decimal("400.00"), "07 DIAS", "Visitado em 29/09.", None, None, 1, "Ana"))
        self.assertEqual(len(linha[18]), 14)
        self.assertEqual(linha[18][3], {"chave": "fundacao", "grupo": "Serasa", "eixo": "Ano de fundação", "peso": 9,
                                        "opcao": "jovem", "rotulo": "Jovem: 1 a 3 anos", "pontos": 3, "auto": True,
                                        "fonte": "fundada em 14/08/2025, há 1 ano e 1 mês"})
        self.assertEqual((linha[19]["parcelas"], linha[19]["prazo_maximo"]), (1, "07 DIAS"))
        x = novo["capas"][0]
        self.assertEqual((x["cliente"], x["cnpj"], x["porte_nome"], x["faixa_rotulo"], x["vendedor"], x["pode_excluir"],
                          x["prazo_dentro"], x["acima_do_maximo"], x["erp"]),
                         ("MERCADO NOVO", NOVO_CNPJ, "Média", "Faixa 1", "Rubens", True, True, False,
                          {"situacao": "fora_do_erp"}))
        # a mesma chave de novo (clique duplo) não grava outra vez
        d = self.dados(r["serasa"]["id"], limite=5000)
        self.cad.registrar(self.ana, d)
        self.assertTrue(self.cad.registrar(self.ana, d)["ja_existia"])
        self.assertEqual(self.contar("credito_capas"), 2)
        self.assertTrue(self.cad.listar(self.ana)["capas"][0]["acima_do_maximo"])  # 5.000 passa dos 3.000

    def test_conferencias(self):
        sid = self.enviar()["serasa"]["id"]
        casos = [
            ({"chave": "x"}, "expirou"), ({"nome": "  "}, "nome do cliente"), ({"id_vendedor": None}, "vendedor"),
            ({"id_vendedor": 999}, "vendedores ativos"), ({"porte": "Z"}, "porte"),
            ({"respostas": {}}, "responda todos os itens"), ({"limite": -1}, "limite concedido"),
            ({"limite": "abc"}, "limite concedido"), ({"prazo": "15 DIAS"}, "prazo concedido"),
            ({"justificativa": "curta"}, "justificativa"), ({"justificativa": "x" * 2001}, "passou de 2000"),
            ({"observacoes": "x" * 2001}, "observações"),
        ]
        for mudar, erro in casos:
            with self.assertRaises(ValueError, msg=erro) as e:
                self.cad.registrar(self.ana, self.dados(sid, **mudar))
            self.assertIn(erro, str(e.exception))
        with self.assertRaises(PermissionError):  # o vendedor tem de ser do acesso de quem registra
            self.cad.registrar(self.ana, self.dados(sid, id_vendedor=ES), permitidos=frozenset({BA}))
        self.assertEqual(self.contar("credito_capas"), 0)

    def test_dados_do_erp_novos_entre_analisar_e_registrar(self):
        sid = self.enviar(texto_30_09(cnpj="11.222.333/0001-81"))["serasa"]["id"]
        with self.assertRaises(ValueError) as e:
            self.cad.registrar(self.ana, self.dados(sid, dados_ate="2026-09-30T08:00:00"))
        self.assertEqual(str(e.exception), DADOS_NOVOS)
        r = self.cad.registrar(self.ana, self.dados(sid, dados_ate="2026-10-01T08:00:00"))
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT id_cliente_historico, dados_ate FROM credito_capas").fetchone(),
                             (1, dt.datetime(2026, 10, 1, 8, 0)))
        self.assertEqual(r["capas"][0]["historico_de"], 1)

    def test_situacao_no_erp(self):
        sid = self.enviar(texto_30_09(cnpj="11.222.333/0001-81"))["serasa"]["id"]
        d = {"dados_ate": "2026-10-01T08:00:00"}
        r = self.cad.registrar(self.ana, self.dados(sid, limite=1000, **d))
        erp = r["capas"][0]["erp"]
        self.assertEqual((erp["situacao"], erp["id"], erp["limite"], erp["prazo"]), ("diferente", 1, 5000.0, "28 DIAS"))
        r = self.cad.registrar(self.ana, self.dados(sid, limite=5000, prazo="28 DIAS", **d))
        self.assertEqual(r["capas"][0]["erp"]["situacao"], "aplicado")
        self.assertFalse(r["capas"][0]["prazo_dentro"])  # 28 dias passa do indicado (7)

    def test_excluir(self):
        r = self.cad.registrar(self.ana, self.dados(self.enviar()["serasa"]["id"]))
        with self.assertRaises(PermissionError):
            self.cad.excluir(self.bia, r["id"])
        self.assertFalse(self.cad.listar(self.bia)["capas"][0]["pode_excluir"])
        self.assertEqual(self.cad.excluir(self.ana, r["id"])["capas"], [])
        with self.assertRaises(NaoEncontrada):
            self.cad.excluir(self.admin, r["id"])
        self.assertEqual(self.contar("credito_capas", "excluida_em IS NOT NULL AND excluida_por_nome = 'Ana'"), 1)
        r = self.cad.registrar(self.bia, self.dados(self.enviar()["serasa"]["id"]))
        self.assertEqual(self.cad.excluir(self.admin, r["id"])["capas"], [])  # o administrador exclui qualquer uma

    def test_acesso_por_vendedor(self):
        sid = self.enviar()["serasa"]["id"]
        self.cad.registrar(self.ana, self.dados(sid, id_vendedor=ES))
        self.cad.registrar(self.admin, self.dados(sid, id_vendedor=BA))
        self.cad.registrar(self.admin, self.dados(sid, id_vendedor=ES))
        so_ba = frozenset({BA})
        # só os do acesso e as que a pessoa registrou; a lista de vendedores do formulário também
        r = self.cad.listar(self.ana, so_ba)
        self.assertEqual([x["vendedor"] for x in r["capas"]], ["Thais", "Rubens"])
        self.assertEqual([v["id"] for v in r["vendedores"]], [BA])
        self.assertEqual(len(self.cad.listar(self.admin)["capas"]), 3)
        self.assertEqual([v["nome"] for v in self.cad.listar(self.admin)["vendedores"]], ["Edir", "Rubens", "Thais"])


class TestPaginaDoCliente(Base):
    def test_o_serasa_e_a_analise_aparecem_no_cliente_pelo_cnpj(self):
        sid = self.enviar(texto_30_09(cnpj="11.222.333/0001-81"))["serasa"]["id"]
        self.cad.registrar(self.ana, self.dados(sid, dados_ate="2026-10-01T08:00:00"))
        s = self.serasa.listar(1, self.ana)
        self.assertEqual((s["atual"]["id"], s["atual"]["do_cadastro"]), (sid, True))
        self.assertIsNone(self.serasa.listar(2, self.ana)["atual"])  # outro CNPJ
        self.assertEqual(self.serasa.ultimo(1)["id"], sid)  # e entra no retrato da próxima reanálise
        reanalises = Reanalises(self.banco, self.credito, ativo=True, config=self.config, serasa=self.serasa,
                                capas=self.cad)
        c = reanalises.listar(1, self.ana)["capas"]
        self.assertEqual((len(c), c[0]["cliente"], c[0]["erp"]["situacao"]), (1, "MERCADO NOVO", "diferente"))
        self.assertEqual(reanalises.listar(2, self.ana)["capas"], [])
        # excluir o Serasa pela página do cliente devolve a lista dele
        self.assertIsNone(self.serasa.excluir(self.ana, sid, 1)["atual"])

    def test_o_prazo_minimo_conta_a_partir_da_capa(self):
        self.config.salvar({"intervalo_reanalise_dias": 30, "serasa_validade_dias": 90}, self.admin)
        reanalises = Reanalises(self.banco, self.credito, ativo=True, config=self.config, serasa=self.serasa,
                                capas=self.cad)
        self.assertIsNone(reanalises.listar(1, self.ana)["bloqueio"])
        sid = self.enviar(texto_30_09(cnpj="11.222.333/0001-81"))["serasa"]["id"]
        self.cad.registrar(self.ana, self.dados(sid, dados_ate="2026-10-01T08:00:00"))
        b = reanalises.listar(1, self.ana)["bloqueio"]
        self.assertEqual((b["origem"], b["ultima_id"], b["dias"]), ("capa", None, 30))
        with self.assertRaises(ValueError) as e:
            reanalises.registrar(self.ana, {"chave": novo_id(), "cliente": 1, "pedido": 6000, "liberado": 6000,
                                            "prazo": "07 DIAS", "justificativa": "Pediu mais limite agora.",
                                            "dados_ate": "2026-10-01T08:00:00"})
        self.assertIn("desde a capa de análise de crédito de", str(e.exception))


class TestReanalise(Base):
    """A capa de um cliente que já está no ERP: o cliente 1 (limite 5.000, 28 DIAS, carteira do Rubens)."""

    def setUp(self):
        super().setUp()
        # o Serasa do cliente, enviado pela página de crédito (com o código dele)
        self.sid = self.serasa.enviar(self.ana, 1, pdf(texto_30_09(cnpj="99.888.777/0001-66")), confirmar=True)["id"]

    def reanalise(self, **mudar) -> dict:
        d = {"tipo": "reanalise", "cliente": 1, "nome": "ignorado", "limite": 5000, "prazo": "28 DIAS",
             "dados_ate": "2026-10-01T08:00:00", **mudar}
        return self.dados(d.pop("serasa_id", self.sid), **d)

    def test_a_capa_do_cliente(self):
        a = self.cad.analisar({"tipo": "reanalise", "cliente": 1, "serasa_id": self.sid, "respostas": ANALISTA,
                               "porte": "C"}, self.ana)
        self.assertEqual((a["tipo"], a["cliente"]["nome"], a["cliente"]["limite"], a["cliente"]["prazo"],
                          a["cliente"]["id_vendedor"], a["cliente"]["carteira"], a["ja_cliente"], a["historico_de"],
                          a["dados_ate"], a["bloqueio"]),
                         ("reanalise", "MERCADO DO JOAO", 5000.0, "28 DIAS", ES, "Rubens", [],
                          {"id": 1, "nome": "MERCADO DO JOAO"}, "2026-10-01T08:00:00", None))
        x = {i["chave"]: i["opcao"] for i in a["itens"]}
        # o histórico Mais Vida do próprio cliente (mesmo com o CNPJ do PDF de outra empresa)
        self.assertEqual((x["pontualidade_mv"], x["ultimas_compras"], x["frequencia"]), ("31_50", "comprou", "1"))
        self.assertEqual((a["pontos"], a["faixa"]["faixa"]), (57, 2))  # 50 da capa de 30/09 + 4 + 2 + 1

    def test_grava_com_o_limite_e_o_prazo_de_antes(self):
        r = self.cad.registrar(self.ana, self.reanalise(limite=4000))
        with self.banco.conexao() as con:
            linha = con.execute("SELECT tipo, id_cliente, cliente, cnpj, limite_antes, prazo_antes, limite_concedido, "
                                "id_cliente_historico, bloqueio FROM credito_capas").fetchone()
        self.assertEqual(linha, ("reanalise", 1, "MERCADO DO JOAO", "99888777000166", Decimal("5000.00"), "28 DIAS",
                                 Decimal("4000.00"), 1, None))  # o nome vem do ERP, não da página
        x = r["capas"][0]
        self.assertEqual((x["tipo"], x["tipo_nome"], x["id_cliente"], x["limite_antes"], x["prazo_antes"],
                          x["erp"]["situacao"], x["erp"]["id"]),
                         ("reanalise", "Reanálise", 1, 5000.0, "28 DIAS", "diferente", 1))
        self.cad.registrar(self.ana, self.reanalise())  # 5.000 e 28 DIAS: o que o ERP já tem
        self.assertEqual(self.cad.listar(self.ana)["capas"][0]["erp"]["situacao"], "aplicado")
        # na página do cliente, com as reanálises
        reanalises = Reanalises(self.banco, self.credito, ativo=True, config=self.config, serasa=self.serasa,
                                capas=self.cad)
        self.assertEqual([c["tipo"] for c in reanalises.listar(1, self.ana)["capas"]], ["reanalise", "reanalise"])
        self.assertEqual(reanalises.listar(2, self.ana)["capas"], [])

    def test_conferencias(self):
        casos = [({"cliente": None}, ValueError, "escolha o cliente"), ({"cliente": 999}, ValueError, "não encontrado"),
                 ({"tipo": "outro"}, ValueError, "cadastro novo ou de uma reanálise"),
                 ({"dados_ate": "2026-09-30T08:00:00"}, ValueError, "atualizados")]
        for mudar, erro, texto in casos:
            with self.assertRaises(erro, msg=texto) as e:
                self.cad.registrar(self.ana, self.reanalise(**mudar))
            self.assertIn(texto, str(e.exception))
        # o Serasa de outro cliente não vale
        outro = self.serasa.enviar(self.ana, 2, pdf(relato(cnpj="55.444.333/0001-22")), confirmar=True)["id"]
        with self.assertRaises(NaoEncontrada):
            self.cad.registrar(self.ana, self.reanalise(serasa_id=outro))
        # o cliente 3 (só da carteira do Rubens) não é do acesso de quem vê só a BA
        sid3 = self.serasa.enviar(self.ana, 3, pdf(relato(cnpj="44.333.222/0001-11")), confirmar=True)["id"]
        with self.assertRaises(PermissionError):
            self.cad.analisar({"tipo": "reanalise", "cliente": 3, "serasa_id": sid3}, self.ana,
                              permitidos=frozenset({BA}))
        self.assertEqual(self.contar("credito_capas"), 0)

    def test_o_serasa_de_cadastro_novo_ligado_pelo_cnpj_vale(self):
        # o PDF de uma capa de cadastro novo com o CNPJ do cliente 1 vale na reanálise dele
        sid = self.enviar(texto_30_09(cnpj="11.222.333/0001-81"))["serasa"]["id"]
        a = self.cad.analisar({"tipo": "reanalise", "cliente": 1, "serasa_id": sid}, self.ana)
        self.assertEqual(a["serasa"]["id"], sid)

    def test_o_prazo_minimo_vale_na_capa(self):
        self.config.salvar({"intervalo_reanalise_dias": 30, "serasa_validade_dias": 90}, self.admin)
        reanalises = Reanalises(self.banco, self.credito, ativo=True, config=self.config, serasa=self.serasa,
                                capas=self.cad)
        self.cad.reanalises = reanalises
        self.cad.registrar(self.ana, self.reanalise())  # manteve: passa e começa o prazo
        a = self.cad.analisar({"tipo": "reanalise", "cliente": 1, "serasa_id": self.sid}, self.ana)
        self.assertEqual((a["bloqueio"]["origem"], a["bloqueio"]["dias"]), ("capa", 30))
        with self.assertRaises(ValueError) as e:  # aumento: quem não é administrador não passa
            self.cad.registrar(self.bia, self.reanalise(limite=6000))
        self.assertIn("desde a capa de análise de crédito de", str(e.exception))
        with self.assertRaises(ValueError) as e:
            self.cad.registrar(self.admin, self.reanalise(limite=6000))
        self.assertIn("Registrar mesmo assim", str(e.exception))
        r = self.cad.registrar(self.admin, self.reanalise(limite=6000, passar_bloqueio=True))
        self.assertTrue(r["capas"][0]["bloqueio"].startswith("aumento só a partir de"))
        self.cad.registrar(self.bia, self.reanalise(limite=3000))  # redução passa
        # e a reanálise da página de crédito também esbarra na capa
        with self.assertRaises(ValueError):
            reanalises.registrar(self.bia, {"chave": novo_id(), "cliente": 1, "pedido": 8000, "liberado": 8000,
                                            "prazo": "07 DIAS", "justificativa": "Pediu mais limite agora.",
                                            "dados_ate": "2026-10-01T08:00:00"})


class TestEditar(Base):
    """A edição grava uma versão nova; a de antes fica guardada como substituída."""

    def edicao(self, id_, **mudar) -> dict:
        return {"id": id_, "chave": novo_id(), "nome": "MERCADO NOVO", "id_vendedor": ES, "porte": "C",
                "respostas": dict(ANALISTA), "limite": 400, "prazo": "07 DIAS", "observacoes": "",
                "justificativa": "Cliente novo indicado pelo Rubens; loja bem montada.", **mudar}

    def test_versao_nova_e_a_antiga_guardada(self):
        r = self.cad.registrar(self.ana, self.dados(self.enviar()["serasa"]["id"]))
        original = r["capas"][0]
        self.assertTrue(original["pode_editar"])
        self.assertIsNone(original["editada_em"])
        # a capa em edição: os itens automáticos ficam como foram registrados; o porte e as respostas vêm da página
        a = self.cad.analisar_edicao({"editar": r["id"], "porte": "B", "respostas": {**ANALISTA, "limpeza": "ruim"}},
                                     self.ana)
        self.assertEqual((a["edicao"]["id"], a["edicao"]["cliente"], a["pontos"], a["indicacao"]["limite_maximo"]),
                         (r["id"], "MERCADO NOVO", 45, 6000.0))
        self.assertEqual({x["chave"]: x["opcao"] for x in a["itens"] if x["auto"]}["fundacao"], "jovem")
        self.cad.hoje = lambda: dt.date(2030, 1, 1)  # a idade da empresa mudaria hoje: na edição, fica a registrada
        e = self.cad.editar(self.admin, self.edicao(r["id"], nome="MERCADO NOVO LTDA", porte="B", id_vendedor=BA,
                                                    respostas={**ANALISTA, "limpeza": "ruim"}, limite=1500,
                                                    prazo="28 DIAS", observacoes="Corrigido o porte.",
                                                    justificativa="O porte era Média para grande; o limite subiu."))
        self.assertFalse(e["ja_existia"])
        self.assertEqual(len(e["capas"]), 1)
        x = e["capas"][0]
        self.assertEqual((x["id"], x["cliente"], x["porte"], x["vendedor"], x["pontos"], x["limite_concedido"],
                          x["prazo_concedido"], x["observacoes"], x["feita_em"], x["feita_por"], x["editada_por"]),
                         (e["id"], "MERCADO NOVO LTDA", "B", "Thais", 45, 1500.0, "28 DIAS", "Corrigido o porte.",
                          original["feita_em"], "Ana", "Chefe"))
        self.assertIsNotNone(x["editada_em"])
        self.assertEqual(next(i for i in x["respostas"] if i["chave"] == "fundacao")["opcao"], "jovem")
        with self.banco.conexao() as con:
            linhas = con.execute("SELECT id, versao_anterior, substituida_em IS NOT NULL, cnpj, serasa_id "
                                 "FROM credito_capas ORDER BY id").fetchall()
        self.assertEqual([(l[0], l[1], l[2]) for l in linhas], [(r["id"], None, True), (e["id"], r["id"], False)])
        self.assertEqual(linhas[0][3:], linhas[1][3:])  # o CNPJ e o Serasa não mudam
        # a versão de antes não se edita nem se exclui mais; a nova sim
        with self.assertRaises(NaoEncontrada):
            self.cad.editar(self.ana, self.edicao(r["id"]))
        with self.assertRaises(NaoEncontrada):
            self.cad.excluir(self.ana, r["id"])
        self.assertEqual(self.cad.excluir(self.ana, e["id"])["capas"], [])

    def test_quem_pode_e_a_mesma_chave(self):
        r = self.cad.registrar(self.ana, self.dados(self.enviar()["serasa"]["id"]))
        with self.assertRaises(PermissionError):
            self.cad.editar(self.bia, self.edicao(r["id"]))
        with self.assertRaises(PermissionError):
            self.cad.analisar_edicao({"editar": r["id"]}, self.bia)
        self.assertFalse(self.cad.listar(self.bia)["capas"][0]["pode_editar"])
        d = self.edicao(r["id"], limite=500)
        primeira = self.cad.editar(self.ana, d)
        segunda = self.cad.editar(self.ana, d)  # clique duplo
        self.assertEqual((segunda["ja_existia"], segunda["id"]), (True, primeira["id"]))
        self.assertEqual(self.contar("credito_capas"), 2)
        for mudar, erro in (({"respostas": {}}, "responda todos os itens"), ({"porte": "Z"}, "porte"),
                            ({"justificativa": "curta"}, "justificativa"), ({"prazo": "15 DIAS"}, "prazo concedido"),
                            ({"nome": " "}, "nome do cliente"), ({"id_vendedor": 999}, "vendedores ativos")):
            with self.assertRaises(ValueError, msg=erro) as e:
                self.cad.editar(self.ana, self.edicao(primeira["id"], **mudar))
            self.assertIn(erro, str(e.exception))

    def test_reanalise_e_o_prazo_minimo_da_data_da_capa(self):
        sid = self.serasa.enviar(self.ana, 1, pdf(texto_30_09(cnpj="99.888.777/0001-66")), confirmar=True)["id"]
        self.config.salvar({"intervalo_reanalise_dias": 30, "serasa_validade_dias": 90}, self.admin)
        reanalises = Reanalises(self.banco, self.credito, ativo=True, config=self.config, serasa=self.serasa,
                                capas=self.cad)
        self.cad.reanalises = reanalises
        base = {"tipo": "reanalise", "cliente": 1, "limite": 5000, "prazo": "28 DIAS", "dados_ate": "2026-10-01T08:00:00"}
        r = self.cad.registrar(self.ana, self.dados(sid, **base))  # manteve: a primeira decisão do cliente
        # editar para aumentar: antes da capa não havia decisão, então passa (a própria capa não conta)
        e = self.cad.editar(self.ana, self.edicao(r["id"], limite=7000, prazo="28 DIAS",
                                                                         nome="ignorado"))
        x = e["capas"][0]
        self.assertEqual((x["cliente"], x["limite_antes"], x["limite_concedido"], x["bloqueio"]),
                         ("MERCADO DO JOAO", 5000.0, 7000.0, None))
        a = self.cad.analisar_edicao({"editar": e["id"], "porte": "C", "respostas": ANALISTA}, self.ana)
        self.assertEqual((a["cliente"]["limite"], a["cliente"]["prazo"], a["bloqueio"]), (5000.0, "28 DIAS", None))
        # editar não reabre o prazo mínimo: ele conta da data em que a capa foi registrada
        self.assertEqual(reanalises.listar(1, self.ana)["bloqueio"]["origem"], "capa")
        # uma capa registrada depois, dentro do prazo, esbarra na primeira; e a edição dela também
        with self.assertRaises(ValueError):
            self.cad.registrar(self.ana, self.dados(sid, **{**base, "limite": 8000}))
        s = self.cad.registrar(self.ana, self.dados(sid, **{**base, "limite": 4000}))  # redução passa
        with self.assertRaises(ValueError) as erro:
            self.cad.editar(self.ana, self.edicao(s["id"], limite=9000, prazo="28 DIAS", nome="x"))
        self.assertIn("quando a capa foi registrada", str(erro.exception))
        with self.assertRaises(ValueError):
            self.cad.editar(self.admin, self.edicao(s["id"], limite=9000, prazo="28 DIAS", nome="x"))
        f = self.cad.editar(self.admin, self.edicao(s["id"], limite=9000, prazo="28 DIAS", nome="x",
                                                    passar_bloqueio=True))
        self.assertTrue(f["capas"][0]["bloqueio"].startswith("aumento só a partir de"))
        # na página do cliente, só as versões em vigor
        self.assertEqual(len(reanalises.listar(1, self.ana)["capas"]), 2)


class TestBusca(Base):
    def test_pelo_nome_cnpj_e_codigo(self):
        sid = self.enviar()["serasa"]["id"]
        self.cad.registrar(self.ana, self.dados(sid, nome="Padaria São João"))
        self.cad.registrar(self.ana, self.dados(sid, nome="MERCEARIA BOA VISTA"))
        sid1 = self.serasa.enviar(self.ana, 1, pdf(texto_30_09(cnpj="99.888.777/0001-66")), confirmar=True)["id"]
        self.cad.registrar(self.ana, self.dados(sid1, tipo="reanalise", cliente=1, limite=5000, prazo="28 DIAS",
                                                dados_ate="2026-10-01T08:00:00"))

        def achou(busca):
            return [x["cliente"] for x in self.cad.listar(self.ana, busca=busca)["capas"]]

        self.assertEqual(achou("sao joao"), ["Padaria São João"])  # sem acento e sem caixa
        self.assertEqual(achou("PADARIA SÃO"), ["Padaria São João"])
        self.assertEqual(achou("comercio"), ["MERCADO DO JOAO", "MERCEARIA BOA VISTA", "Padaria São João"])  # razão social
        self.assertEqual(achou("62.237.700/0001-51"), ["MERCEARIA BOA VISTA", "Padaria São João"])  # CNPJ com pontos
        self.assertEqual(achou("99888777"), ["MERCADO DO JOAO"])  # só os dígitos
        self.assertEqual(achou("1"), ["MERCADO DO JOAO"])  # o código do cliente
        self.assertEqual(achou("100%"), [])  # o % não vira curinga
        self.assertEqual(len(achou("")), 3)
        r = self.cad.listar(self.ana, busca="  boa vista ")
        self.assertEqual((r["busca"], len(r["capas"])), ("boa vista", 1))
        um = self.cad.listar(self.ana, id_=r["capas"][0]["id"])["capas"]
        self.assertEqual([x["cliente"] for x in um], ["MERCEARIA BOA VISTA"])


class TestDoisCodigos(Base):
    linhas_cnpj = [(1, "11222333000181"), (3, "11222333000181")]

    def test_vale_o_da_compra_mais_recente_e_aparece_nos_dois(self):
        r = self.enviar(texto_30_09(cnpj="11.222.333/0001-81"))
        self.assertEqual([c["id"] for c in r["ja_cliente"]], [3, 1])  # o 3 comprou em 15/09; o 1, em 02/09
        self.assertEqual(r["historico_de"]["id"], 3)
        self.cad.registrar(self.ana, self.dados(r["serasa"]["id"], dados_ate="2026-10-01T08:00:00"))
        erp = self.cad.listar(self.ana)["capas"][0]["erp"]
        self.assertEqual((erp["id"], erp["outros"]), (3, [1]))
        self.assertEqual(len(self.cad.do_cliente(1, self.ana)), 1)
        self.assertEqual(len(self.cad.do_cliente(3, self.ana)), 1)


class TestSemCnpjNoCache(Base):
    cnpj = False

    def test_nao_liga_e_avisa(self):
        r = self.enviar(texto_30_09(cnpj="11.222.333/0001-81"))
        self.assertEqual((r["ja_cliente"], r["historico_de"]), (None, None))
        self.cad.registrar(self.ana, self.dados(r["serasa"]["id"]))
        self.assertEqual(self.cad.listar(self.ana)["capas"][0]["erp"], {"situacao": "sem_cnpj"})
        self.assertEqual(self.cad.do_cliente(1, self.ana), [])
        self.assertIsNone(self.serasa.listar(1, self.ana)["atual"])


class TestNoPc(Base):
    def test_so_avisa(self):
        pc = CapasCredito(self.banco, self.credito, DadosSerasa(self.banco, self.credito, ativo=False), ativo=False)
        self.assertEqual(pc.listar(self.ana), {"ativo": False, "aviso": AVISO_PC, "capas": []})
        with self.assertRaises(ValueError):
            pc.analisar({"tipo": "reanalise", "cliente": 1}, self.ana)
        for chamar in (lambda: pc.enviar_serasa(self.ana, pdf(texto_30_09())), lambda: pc.analisar({}, self.ana),
                       lambda: pc.registrar(self.ana, {}), lambda: pc.excluir(self.ana, 1)):
            with self.assertRaises(ValueError):
                chamar()
        self.assertEqual(pc.do_cliente(1, self.ana), [])


if __name__ == "__main__":
    unittest.main()

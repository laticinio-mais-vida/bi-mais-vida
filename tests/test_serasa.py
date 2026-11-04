"""Dados do Serasa (bi/serasa.py): a leitura do Relato PJ (o texto que a pypdf tira do PDF, as faixas "200 A 250" e "6 MIL
A 6,5 MIL", os percentuais, as anotações com e sem ocorrência, as partes que podem faltar e o que não é o relatório), o
PDF de verdade passando pela pypdf, o nome do relatório contra o do cadastro, a gravação (o mesmo PDF uma vez só, a
confirmação quando o nome não bate, a ordem pela emissão, a idade contra a validade, quem exclui, o PC que só avisa) e o
último envio no retrato da reanálise.

O texto segue o formato do relatório real (as linhas na ordem da pypdf), com uma empresa e números inventados. Usa o
cache sintético de tests/apoio.py e o banco de teste (BI_TESTE_POSTGRES).
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from fpdf import FPDF

from bi.conversas import NaoEncontrada, novo_id
from bi.credito import Credito
from bi.reanalise import ConfigCredito, Reanalises
from bi.serasa import AVISO_PC, DadosSerasa, intervalo, ler_relato, ler_texto, mesma_empresa, percentual
from tests.apoio import NOMES, BaseBanco, criar_calc

NADA = "NÃO CONSTAM OCORRÊNCIAS - -"


def relato(emitido: dt.datetime = dt.datetime(2026, 11, 4, 9, 25), razao: str = "JOAO COMERCIO LTDA EPP",
           fantasia: str = "MERCADO DO JOAO", cnpj: str = "11.222.333/0001-81", score: bool = True,
           historico: bool = True, anotacoes: dict | None = None) -> str:
    """O texto do Relato PJ como a pypdf tira do PDF (a mesma ordem das linhas do relatório real)."""
    a = {"pefin": NADA, "refin": NADA, "dividas": NADA, "protestos": NADA, "cheques": NADA, "acoes": NADA,
         "falencias": NADA, **(anotacoes or {})}
    partes = [f""" Identificação  CNPJ: ATIVO
 Outras Informações
CONTATO
Endereço Bairro Cidade UF CEP
R DAS FLORES 10 CENTRO SERRA ES 29.000-000
 Relato - Pessoa Jurídica
Emitido em: {emitido:%d/%m/%Y %H:%M}
CNPJ
{cnpj}
RAZÃO SOCIAL
{razao}
DATA DE FUNDAÇÃO
25/11/2020
NOME FANTASIA
{fantasia}
TOTAL DE EMPREGADOS
0
CAPITAL SOCIAL
R$ 104.500,00"""]
    if score:
        partes.append("""Serasa Score 2.0
376
de 1000
PROBABILIDADE DE INADIMPLENCIA: 2,12%
Práticas de mercado
Probabilidade de Inadimplência
2,12%
Risco de Crédito
Médio
Venda à prazo
Venda com garantias
adicionais""")
    if historico:
        partes.append("""HISTÓRICO DE PAGAMENTO COMERCIAL - VISÃO MERCADO (TÍTULOS POR FAIXA)
0%
33%
67%
100%
Percentual (%)
PONTUAL
200 A 250
91.0% e 93.0%
8-15
1 A 3
0.4% e 1.0%
16-30
10 A 15
5.0% e 7.0%
31-60
1 A 3
1.0% e 3.0%
+60
-
0.0% e 0.0%
A VISTA
1 A 3
0.0% e 0.0%
HISTÓRICO DE PAGAMENTO COMERCIAL - PONTUALIDADE (RESUMO)
0%
33%
67%
100%
Percentual (%)
PONTUAL
Total: 100 MIL A 200 MIL
Médio: 10 MIL A 13 MIL
93% - 95%
8-15
Total: 300 A 350
Médio: 10 A 30
0% - 0%
16-30
Total: 6 MIL A 6,5 MIL
Médio: 400 A 450
3% - 5%
31-60
Total: 2 MIL A 2,5 MIL
Médio: 150 A 200
1% - 3%
+60
Total: -
Médio: -
0% - 0%
A VISTA
Total: 70 MIL A 100 MIL
Médio: 5,5 MIL A 6 MIL
0% - 0%
TOTAL MES
Total: 200 MIL A 300 MIL
Médio: 17 MIL A 20 MIL
0% - 0%
HISTÓRICO DE PAGAMENTO COMERCIAL - INDICADORES DE PRAZO (MÉDIO DE ATRASO)
Período OUT/25 NOV/25 DEZ/25
Dias (De/Até) 1 a 3 1 a 3 0 a 0
RESUMO ATUAL 1 a 3 dias
HISTÓRICO DE PAGAMENTO COMERCIAL - PRINCIPAIS FORNECEDORES
FORNECEDOR UM LTDA 99.888.777/0001-66""")
    partes.append(f"""QUADRO SOCIAL ADMINISTRATIVO (SÓCIOS)
CPF/CNPJ Sócio/Acionista % Capital Total Está Negativado?
000.000.000-00 FULANA DE TAL 100,0% NÃO
ANOTAÇÕES NEGATIVAS
Ocorrências Quantidade Período Valor Total
Pendências Comerciais (PEFIN) {a['pefin']}
Pendências Bancárias (REFIN) {a['refin']}
Dívidas Vencidas {a['dividas']}
Protestos   {a['protestos']}
Cheques Sem Fundos {a['cheques']}
Ações Judiciais {a['acoes']}
Falências, Concordatas e Recuperações Judiciais {a['falencias']}
PENDÊNCIAS COMERCIAIS (PEFIN)
NÃO CONSTAM OCORRÊNCIAS
PROTESTOS
NÃO CONSTAM OCORRÊNCIAS
Este relatório é estritamente confidencial.""")
    return "\n".join(partes)


# Uma empresa em default, no formato do relatório real (dados inventados).
NEGATIVADA = """ Relato - Pessoa Jurídica
Emitido em: 30/10/2026 14:01
CNPJ
12.345.678/0001-90
RAZÃO SOCIAL
12 345 678 FULANO DE TAL ME
DATA DE FUNDAÇÃO
06/02/2015
NOME FANTASIA
FULANO FORROS
Serasa Score 2.0
2
de 1000
DEFAULT - DIVIDA VENCIDA COM INSTITUICAO
FINANCEIRA HA MAIS DE 90 DIAS
Práticas de mercado
Probabilidade de Inadimplência
100,00%
Risco de Crédito
Iminente
Venda à prazo
Venda à vista
Interpretação
Score Crítico (Risco Iminente): a chance de conseguir crédito é praticamente zero.
HISTÓRICO DE PAGAMENTO COMERCIAL - VISÃO MERCADO (TÍTULOS POR FAIXA)
HISTÓRICO DE PAGAMENTO COMERCIAL - PONTUALIDADE (RESUMO)
HISTÓRICO DE PAGAMENTO COMERCIAL - INDICADORES DE PRAZO (MÉDIO DE ATRASO)
Período
Dias (De/Até)
RESUMO ATUAL 0 a 0 dias
HISTÓRICO DE PAGAMENTO COMERCIAL - PRINCIPAIS FORNECEDORES
QUADRO SOCIAL ADMINISTRATIVO (SÓCIOS)
CPF/CNPJ Sócio/Acionista % Capital Total Está Negativado?
000.000.000-00 FULANO DE TAL 100,0% SIM
ANOTAÇÕES NEGATIVAS
Ocorrências Quantidade Período Valor Total
Pendências Comerciais (PEFIN) 4 02/07/2023 - 10/07/2025 R$ 2.538,20
Pendências Bancárias (REFIN) 1 05/03/2025 - 05/03/2025 R$ 7.452,15
Dívidas Vencidas NÃO CONSTAM OCORRÊNCIAS - -
Protestos   NÃO CONSTAM OCORRÊNCIAS - -
Cheques Sem Fundos NÃO CONSTAM OCORRÊNCIAS - -
Ações Judiciais NÃO CONSTAM OCORRÊNCIAS - -
Falências, Concordatas e Recuperações Judiciais NÃO CONSTAM OCORRÊNCIAS - -
PENDÊNCIAS COMERCIAIS (PEFIN)
Contrato Modalidade Credor Data Valor (R$) Avalista?
111 CRED CARTAO CREDORA UM S/A 10/07/2025 R$ 1.198,80 NÃO
222 DUPLICATA CREDORA DOIS 09/07/2023 R$ 458,00 NÃO
333 DUPLICATA CREDORA DOIS 04/07/2023 R$ 423,40 NÃO
444 DUPLICATA CREDORA DOIS 02/07/2023 R$ 458,00 NÃO
Total de Ocorrências: 4
PENDÊNCIAS BANCÁRIAS (REFIN)
Contrato Modalidade Credor Data Valor (R$) Avalista?
555 EMPRES CONTA BANCO TRES 05/03/2025 R$ 7.452,15 NÃO
Total de Ocorrências: 1
DÍVIDAS VENCIDAS
NÃO CONSTAM OCORRÊNCIAS
PROTESTOS
NÃO CONSTAM OCORRÊNCIAS"""


def pdf(texto: str) -> bytes:
    """Um PDF de verdade com as linhas do texto (para passar pela pypdf)."""
    doc = FPDF()
    doc.add_page()
    doc.set_font("Helvetica", size=9)
    for linha in texto.splitlines():
        doc.cell(0, 4.5, linha.strip() or " ", new_x="LMARGIN", new_y="NEXT")
    return bytes(doc.output())


class TestLeitura(unittest.TestCase):
    def test_o_relatorio_inteiro(self):
        d = ler_texto(relato())
        self.assertEqual((d["cnpj"], d["razao_social"], d["nome_fantasia"], d["emitido_em"], d["fundacao"]),
                         ("11.222.333/0001-81", "JOAO COMERCIO LTDA EPP", "MERCADO DO JOAO",
                          dt.datetime(2026, 11, 4, 9, 25), dt.date(2020, 11, 25)))
        self.assertEqual(d["score"], {"valor": 376, "probabilidade": 0.0212, "risco": "Médio", "alerta": None})
        self.assertEqual([(f["chave"], f["quantidade"]["de"], f["quantidade"]["ate"], f["percentual"]["de"],
                           f["percentual"]["ate"]) for f in d["faixas"]],
                         [("pontual", 200, 250, 0.91, 0.93), ("8_15", 1, 3, 0.004, 0.01), ("16_30", 10, 15, 0.05, 0.07),
                          ("31_60", 1, 3, 0.01, 0.03), ("mais_60", None, None, 0.0, 0.0), ("a_vista", 1, 3, 0.0, 0.0)])
        p = {x["chave"]: x for x in d["pontualidade"]}
        self.assertEqual(list(p), ["pontual", "8_15", "16_30", "31_60", "mais_60", "a_vista", "total_mes"])
        self.assertEqual(p["pontual"]["total"], {"texto": "100 MIL A 200 MIL", "de": 100000, "ate": 200000})
        self.assertEqual((p["16_30"]["total"]["de"], p["16_30"]["total"]["ate"]), (6000, 6500))
        self.assertEqual((p["a_vista"]["medio"]["de"], p["a_vista"]["medio"]["ate"]), (5500, 6000))
        self.assertEqual((p["mais_60"]["total"]["de"], p["mais_60"]["medio"]["texto"]), (None, "-"))
        self.assertEqual((p["pontual"]["percentual"]["de"], p["pontual"]["percentual"]["ate"]), (0.93, 0.95))
        self.assertEqual(p["total_mes"]["medio"]["ate"], 20000)
        self.assertEqual([(x["chave"], x["quantidade"], x["valor"]) for x in d["anotacoes"]],
                         [(k, 0, 0.0) for k in ("pefin", "refin", "dividas_vencidas", "protestos", "cheques",
                                                "acoes_judiciais", "falencias")])
        self.assertEqual(d["anotacoes"][0]["texto"], NADA)
        self.assertEqual(d["faltou"], [])
        self.assertNotIn("000.000.000-00", str(d))  # o CPF dos sócios não sai da leitura

    def test_anotacoes_com_ocorrencia(self):
        d = ler_texto(relato(anotacoes={"protestos": "2 03/2025 A 08/2026 R$ 1.234,56", "pefin": "1 05/2026 350,00",
                                        "dividas": "CONSULTE O DETALHE"}))
        a = {x["chave"]: x for x in d["anotacoes"]}
        self.assertEqual((a["protestos"]["quantidade"], a["protestos"]["valor"], a["protestos"]["texto"]),
                         (2, 1234.56, "2 03/2025 A 08/2026 R$ 1.234,56"))
        self.assertEqual((a["pefin"]["quantidade"], a["pefin"]["valor"]), (1, 350.0))
        # o que não dá para ler fica sem número, com o texto que veio (a página manda conferir no PDF)
        self.assertEqual((a["dividas_vencidas"]["quantidade"], a["dividas_vencidas"]["valor"],
                          a["dividas_vencidas"]["texto"]), (None, None, "CONSULTE O DETALHE"))

    def test_empresa_negativada(self):
        """O formato do relatório de uma empresa em default: o aviso no lugar da probabilidade, o histórico vazio e as
        anotações com quantidade, período e valor, seguidas do quadro de cada contrato."""
        d = ler_texto(NEGATIVADA)
        self.assertEqual(d["score"], {"valor": 2, "probabilidade": 1.0, "risco": "Iminente",
                                      "alerta": "DEFAULT - DIVIDA VENCIDA COM INSTITUICAO FINANCEIRA HA MAIS DE 90 DIAS"})
        self.assertEqual((d["faixas"], d["pontualidade"], d["faltou"]),
                         ([], [], ["títulos por faixa", "pontualidade em R$"]))
        self.assertEqual((d["razao_social"], d["fundacao"]), ("12 345 678 FULANO DE TAL ME", dt.date(2015, 2, 6)))
        a = {x["chave"]: (x["quantidade"], x["valor"]) for x in d["anotacoes"]}
        self.assertEqual(a, {"pefin": (4, 2538.2), "refin": (1, 7452.15), "dividas_vencidas": (0, 0.0),
                             "protestos": (0, 0.0), "cheques": (0, 0.0), "acoes_judiciais": (0, 0.0),
                             "falencias": (0, 0.0)})
        self.assertEqual(d["anotacoes"][0]["texto"], "4 02/07/2023 - 10/07/2025 R$ 2.538,20")
        self.assertNotIn("000.000.000-00", str(d))
        self.assertEqual(ler_relato(pdf(NEGATIVADA))["anotacoes"][1]["valor"], 7452.15)

    def test_sem_a_linha_da_tabela_vale_o_quadro_de_detalhe(self):
        texto = relato().replace(f"Pendências Comerciais (PEFIN) {NADA}\n", "")
        a = {x["chave"]: x for x in ler_texto(texto)["anotacoes"]}
        self.assertEqual((a["pefin"]["quantidade"], a["pefin"]["valor"]), (0, 0.0))
        texto = texto.replace("PENDÊNCIAS COMERCIAIS (PEFIN)\nNÃO CONSTAM OCORRÊNCIAS\n", "")
        a = {x["chave"]: x for x in ler_texto(texto)["anotacoes"]}
        self.assertEqual((a["pefin"]["quantidade"], a["pefin"]["texto"]), (None, None))  # nada sobre ele

    def test_partes_que_podem_faltar(self):
        d = ler_texto(relato(score=False, historico=False).replace("DATA DE FUNDAÇÃO\n25/11/2020\n", ""))
        self.assertEqual((d["score"], d["faixas"], d["pontualidade"], d["fundacao"]), (None, [], [], None))
        self.assertEqual(d["faltou"], ["data de fundação", "score", "títulos por faixa", "pontualidade em R$"])

    def test_o_que_nao_e_o_relatorio(self):
        casos = [
            (relato().replace("11.222.333/0001-81", "sem cnpj"), "o CNPJ"),
            (relato().replace("Emitido em", "Gerado"), "a data de emissão"),
            (relato().replace("ANOTAÇÕES NEGATIVAS", "OUTRA COISA"), "as anotações negativas"),
            ("Nota fiscal\nTotal R$ 10,00", "o CNPJ e a data de emissão e as anotações negativas"),
            ("   \n  ", "escaneado"),
        ]
        for texto, erro in casos:
            with self.assertRaises(ValueError, msg=erro) as e:
                ler_texto(texto)
            self.assertIn(erro, str(e.exception))

    def test_faixas_e_percentuais(self):
        self.assertEqual(intervalo("200 A 250"), {"texto": "200 A 250", "de": 200, "ate": 250})
        self.assertEqual(intervalo(" 6 MIL A 6,5 MIL"), {"texto": "6 MIL A 6,5 MIL", "de": 6000, "ate": 6500})
        self.assertEqual(intervalo("1,5 MI A 2 MI")["ate"], 2_000_000)
        self.assertEqual(intervalo("300"), {"texto": "300", "de": 300, "ate": 300})
        self.assertEqual(intervalo("-"), {"texto": "-", "de": None, "ate": None})
        self.assertIsNone(intervalo("91.0% e 93.0%"))
        self.assertEqual(percentual("91.0% e 93.0%"), {"texto": "91.0% e 93.0%", "de": 0.91, "ate": 0.93})
        self.assertEqual(percentual("93% - 95%")["ate"], 0.95)
        self.assertEqual(percentual("2,12%"), {"texto": "2,12%", "de": 0.0212, "ate": 0.0212})
        self.assertIsNone(percentual("200 A 250"))

    def test_o_pdf_passa_pela_pypdf(self):
        d = ler_relato(pdf(relato()))
        self.assertEqual((d["cnpj"], d["fundacao"], d["score"]["valor"], len(d["faixas"]), len(d["pontualidade"]),
                          [x["quantidade"] for x in d["anotacoes"]]),
                         ("11.222.333/0001-81", dt.date(2020, 11, 25), 376, 6, 7, [0] * 7))

    def test_arquivos_recusados(self):
        for conteudo, erro in ((b"", "escolha o PDF"), (b"PK\x03\x04 planilha", "não é um PDF"),
                               (b"%PDF-1.7 quebrado", "não deu para abrir"), (b"%PDF" + b"0" * (11 * 1024 * 1024), "10 MB")):
            with self.assertRaises(ValueError, msg=erro) as e:
                ler_relato(conteudo)
            self.assertIn(erro, str(e.exception))

    def test_o_nome_do_relatorio_contra_o_do_cadastro(self):
        self.assertTrue(mesma_empresa(["MR PAO LTDA EPP", "MR PAO"], ["PADARIA MR PÃO - SERRA"]))
        self.assertTrue(mesma_empresa(["JOAO COMERCIO LTDA EPP", None], ["MERCADO DO JOAO", "JOAO COMERCIO LTDA"]))
        self.assertTrue(mesma_empresa(["SUPERMERCADO BOM PRECO EIRELI", "BOM PRECO"], ["BOM PREÇO"]))
        self.assertFalse(mesma_empresa(["MR PAO LTDA EPP", "MR PAO"], ["MERCADO DO JOAO", "JOAO COMERCIO LTDA"]))
        self.assertFalse(mesma_empresa([None, "LTDA"], ["MERCADO DO JOAO"]))


class Base(BaseBanco):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.calc = criar_calc(Path(self._tmp.name))
        self.credito = Credito(self.calc.cache, lambda: dict(NOMES))
        self.config = ConfigCredito(self.banco)
        self.serasa = DadosSerasa(self.banco, self.credito, ativo=True, config=self.config)
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

    @staticmethod
    def ha(dias: int) -> dt.datetime:
        return dt.datetime.combine(dt.date.today() - dt.timedelta(days=dias), dt.time(9, 25))


class TestGravar(Base):
    def test_grava_so_os_campos_e_mostra_a_idade(self):
        r = self.serasa.enviar(self.ana, 1, pdf(relato(emitido=self.ha(10))))
        self.assertFalse(r["ja_existia"])
        with self.banco.conexao() as con:
            linha = con.execute("SELECT id_cliente, cliente, cnpj, razao_social, fundacao, score, enviado_por_nome, "
                                "dados FROM credito_serasa").fetchone()
        self.assertEqual(linha[:7], (1, "MERCADO DO JOAO", "11.222.333/0001-81", "JOAO COMERCIO LTDA EPP",
                                     dt.date(2020, 11, 25), 376, "Ana"))
        self.assertEqual(set(linha[7]), {"versao", "nome_fantasia", "score", "faixas", "pontualidade", "anotacoes",
                                         "faltou"})
        self.assertNotIn("000.000.000-00", str(linha))
        x = r["atual"]
        self.assertEqual((x["id"], x["idade_dias"], x["desatualizado"], x["enviado_por"], x["pode_excluir"],
                          x["fundacao"], x["score"]["valor"], r["validade_dias"], r["anteriores"]),
                         (r["id"], 10, False, "Ana", True, "2020-11-25", 376, 90, []))

    def test_o_mesmo_pdf_grava_uma_vez(self):
        conteudo = pdf(relato())
        a = self.serasa.enviar(self.ana, 1, conteudo)
        b = self.serasa.enviar(self.bia, 1, conteudo)
        self.assertEqual((a["ja_existia"], b["ja_existia"], b["id"]), (False, True, a["id"]))
        self.assertEqual(self.contar("credito_serasa"), 1)
        # para outro cliente, é outro envio
        self.serasa.enviar(self.ana, 2, conteudo, confirmar=True)
        self.assertEqual(self.contar("credito_serasa"), 2)

    def test_nome_diferente_pede_confirmacao(self):
        conteudo = pdf(relato(razao="MR PAO LTDA EPP", fantasia="MR PAO"))
        r = self.serasa.enviar(self.ana, 1, conteudo)
        self.assertIn("O PDF é de MR PAO LTDA EPP", r["confirmar"])
        self.assertIn("MERCADO DO JOAO (código 1)", r["confirmar"])
        self.assertEqual(self.contar("credito_serasa"), 0)
        r = self.serasa.enviar(self.ana, 1, conteudo, confirmar=True)
        self.assertEqual(r["atual"]["razao_social"], "MR PAO LTDA EPP")

    def test_o_mais_recente_pela_emissao_e_a_validade(self):
        self.serasa.enviar(self.ana, 1, pdf(relato(emitido=self.ha(30))))
        r = self.serasa.enviar(self.ana, 1, pdf(relato(emitido=self.ha(120))))  # um PDF antigo enviado depois
        self.assertEqual((r["atual"]["idade_dias"], [x["idade_dias"] for x in r["anteriores"]]), (30, [120]))
        self.assertEqual([x["desatualizado"] for x in (r["atual"], *r["anteriores"])], [False, True])
        self.config.salvar({"intervalo_reanalise_dias": 0, "serasa_validade_dias": 30})
        r = self.serasa.listar(1, self.ana)
        self.assertFalse(r["atual"]["desatualizado"])  # 30 dias com validade de 30: ainda vale
        self.config.salvar({"intervalo_reanalise_dias": 0, "serasa_validade_dias": 29})
        self.assertTrue(self.serasa.listar(1, self.ana)["atual"]["desatualizado"])

    def test_conferencias(self):
        for cliente, conteudo, erro in ((999, pdf(relato()), "cliente não encontrado"), ("x", b"", "escolha um cliente"),
                                        (1, b"nada", "não é um PDF")):
            with self.assertRaises(ValueError, msg=erro) as e:
                self.serasa.enviar(self.ana, cliente, conteudo)
            self.assertIn(erro, str(e.exception))
        self.assertEqual(self.contar("credito_serasa"), 0)

    def test_excluir(self):
        r = self.serasa.enviar(self.ana, 1, pdf(relato()))
        with self.assertRaises(PermissionError):
            self.serasa.excluir(self.bia, r["id"])
        self.assertIsNone(self.serasa.excluir(self.ana, r["id"])["atual"])
        with self.assertRaises(NaoEncontrada):
            self.serasa.excluir(self.admin, r["id"])
        self.assertEqual(self.contar("credito_serasa", "excluido_em IS NOT NULL AND excluido_por_nome = 'Ana'"), 1)
        # excluído, o mesmo PDF pode ser enviado de novo; o administrador exclui o de qualquer um
        r = self.serasa.enviar(self.bia, 1, pdf(relato()))
        self.assertFalse(r["ja_existia"])
        self.assertFalse(self.serasa.listar(1, self.ana)["atual"]["pode_excluir"])
        self.assertIsNone(self.serasa.excluir(self.admin, r["id"])["atual"])

    def test_no_pc_so_avisa(self):
        pc = DadosSerasa(self.banco, self.credito, ativo=False)
        self.assertEqual(pc.listar(1, self.ana), {"ativo": False, "aviso": AVISO_PC, "atual": None, "anteriores": []})
        with self.assertRaises(ValueError):
            pc.enviar(self.ana, 1, pdf(relato()))
        self.assertIsNone(pc.ultimo(1))

    def test_o_ultimo_vai_para_o_retrato_da_reanalise(self):
        reanalises = Reanalises(self.banco, self.credito, ativo=True, config=self.config, serasa=self.serasa)
        dados = {"chave": novo_id(), "cliente": 1, "pedido": 6000, "liberado": 5000, "prazo": "07 DIAS",
                 "justificativa": "Cliente antigo; paga em dia.", "dados_ate": "2026-10-01T08:00:00"}
        reanalises.registrar(self.ana, dados)
        self.serasa.enviar(self.ana, 1, pdf(relato(emitido=self.ha(5))))
        reanalises.registrar(self.ana, {**dados, "chave": novo_id()})
        with self.banco.conexao() as con:
            retratos = [r[0] for r in con.execute("SELECT retrato FROM credito_reanalises ORDER BY id").fetchall()]
        self.assertIsNone(retratos[0]["serasa"])
        s = retratos[1]["serasa"]
        self.assertEqual((s["idade_dias"], s["desatualizado"], s["fundacao"], s["score"]["valor"]),
                         (5, False, "2020-11-25", 376))
        self.assertEqual(s["faixas"][0], {"faixa": "pontual", "quantidade": {"de": 200, "ate": 250},
                                          "percentual": {"de": 0.91, "ate": 0.93}})
        self.assertEqual(s["anotacoes"][3], {"tipo": "protestos", "quantidade": 0, "valor": 0.0})


if __name__ == "__main__":
    unittest.main()

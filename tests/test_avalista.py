"""O contrato de avalista (bi/avalista.py e bi/avalista_pdf.py), o botão "Avalista" da página de crédito.

Sem banco:
- CNPJ (com letras, desde julho de 2026) e CPF: os dígitos verificadores e a pontuação;
- o que vem da página (normalizar) e o que falta (pendencias), nos dois modelos;
- os dados da Mais Vida (o padrão e o que o modelo Pessoa Física pede a mais);
- o texto do contrato (as correções combinadas, os campos, as linhas para preencher à mão) e o PDF (6 páginas com os
  dados dos modelos, o texto inteiro, o que a pessoa digita nunca vira marca de negrito).

Com o banco:
- salvar pela metade, a mesma chave, abrir, editar por cima (a versão, o dono), excluir, buscar;
- o cliente do ERP (a razão social e o CNPJ; o acesso);
- os dados da Mais Vida (só o administrador) no PDF;
- o PC, que só avisa.

Usa o cache sintético de tests/apoio.py e o banco de teste (BI_TESTE_POSTGRES).
"""
from __future__ import annotations

import copy
import io
import tempfile
import unittest
from pathlib import Path

from bi.avalista import (AVISO_PC, MAX_REPRESENTANTES, MUDOU, PADRAO_FORNECEDOR, Avalistas, ConfigAvalista,
                         _valida_fornecedor, cnpj_valido, cpf_valido, faltas_do_fornecedor, formatar_cep, formatar_cnpj,
                         formatar_cpf, normalizar, pendencias)
from bi.avalista_pdf import LACUNA, data_por_extenso, documento, nome_arquivo, paragrafos, trechos
from bi.avalista_texto import PF_CLAUSULAS, PJ_CLAUSULAS
from bi.conversas import NaoEncontrada, novo_id
from bi.credito import Credito
from tests.apoio import BA, ES, NOMES, BaseBanco, criar_calc

SOCIO = {"tratamento": "Sra.", "nome": "MARIA DA SILVA", "nacionalidade": "Brasileira", "estado_civil": "Casada",
         "profissao": "Empresária", "rg": "1234567890", "cpf": "529.982.247-25",
         "endereco": "Rua das Flores, 100, Centro, Eunápolis - BA", "cep": "45820-000"}
SOCIO_2 = {**SOCIO, "tratamento": "Sr.", "nome": "JOSE DE SOUZA", "nacionalidade": "Brasileiro", "estado_civil": "Casado",
           "profissao": "Empresário", "rg": "9876543210", "cpf": "111.444.777-35"}
EMPRESA = {"razao_social": "MERCADO NOVO LTDA", "cnpj": "11.222.333/0001-81", "ie": "078.420.714",
           "endereco": "Rua B, 220, Zabelê, Vitória da Conquista - BA", "cep": "45077-014",
           "qualificacao": "sócio administrador", "representantes": [SOCIO]}
GARANTIDORA = {**EMPRESA, "razao_social": "SUPERMERCADO FORTE LTDA", "cnpj": "22.333.444/0001-81", "ie": "",
               "representantes": [SOCIO_2, SOCIO]}
PJ = {"tipo": "pj", "data": "2026-02-04", "compradora": EMPRESA, "garantidor": GARANTIDORA}
PF = {"tipo": "pf", "data": "2026-02-01", "compradora": EMPRESA,
      "garantidor": {k: v for k, v in SOCIO_2.items() if k != "tratamento"}}
MAIS_VIDA = {**PADRAO_FORNECEDOR, "ie": "012.345.678", "nacionalidade": "brasileiro", "estado_civil": "casado",
             "profissao": "empresário", "rg": "0102030405", "cpf": "111.444.777-35"}


def texto_de(paragrafo) -> str:
    return "".join(t for t, _ in paragrafo.trechos)


def texto_do_contrato(dados: dict, fornecedor: dict = PADRAO_FORNECEDOR) -> str:
    return "\n".join(texto_de(p) for p in paragrafos(normalizar(dados), fornecedor))


class TestDocumentos(unittest.TestCase):
    def test_cnpj(self):
        self.assertEqual(cnpj_valido("96.845.748/0001-64"), "96845748000164")  # o da Mais Vida, do modelo
        self.assertEqual(cnpj_valido("11222333000181"), "11222333000181")
        self.assertEqual(cnpj_valido(" 11.222.333 / 0001-81 "), "11222333000181")
        self.assertIsNone(cnpj_valido("11.222.333/0001-82"))  # o último dígito errado
        self.assertIsNone(cnpj_valido("00.000.000/0000-00"))
        self.assertIsNone(cnpj_valido("1122233300018"))
        self.assertIsNone(cnpj_valido(None))
        # com letras (o exemplo da Receita Federal para o CNPJ novo)
        self.assertEqual(cnpj_valido("12.abc.345/01de-35"), "12ABC34501DE35")
        self.assertIsNone(cnpj_valido("12.ABC.345/01DE-36"))
        self.assertEqual(formatar_cnpj("11222333000181"), "11.222.333/0001-81")
        self.assertEqual(formatar_cnpj("12abc34501de35"), "12.ABC.345/01DE-35")
        self.assertEqual(formatar_cnpj("1122233300"), "1122233300")  # incompleto: como foi digitado

    def test_cpf_e_cep(self):
        self.assertEqual(cpf_valido("529.982.247-25"), "52998224725")
        self.assertEqual(cpf_valido("11144477735"), "11144477735")
        self.assertIsNone(cpf_valido("529.982.247-26"))
        self.assertIsNone(cpf_valido("111.111.111-11"))
        self.assertIsNone(cpf_valido("5299822472"))
        self.assertEqual(formatar_cpf("52998224725"), "529.982.247-25")
        self.assertEqual(formatar_cpf("529982"), "529982")
        self.assertEqual(formatar_cep("45.077-014"), "45077-014")
        self.assertEqual(formatar_cep("45077"), "45077")


class TestDados(unittest.TestCase):
    def test_arruma_o_que_foi_digitado(self):
        d = normalizar({"tipo": "pj", "data": "2026-02-04",
                        "compradora": {"razao_social": "  MERCADO \t NOVO\nLTDA\x00 ", "cnpj": "11222333000181",
                                       "cep": "45.077-014", "poderes": " Sra. FULANA ",
                                       "representantes": [{"tratamento": "Sra.", "cpf": "52998224725", "cep": "45820000"}]},
                        "garantidor": {"cnpj": "22.333.444/0001-81"}})
        c = d["compradora"]
        self.assertEqual((c["razao_social"], c["cnpj"], c["cep"], c["poderes"]),
                         ("MERCADO NOVO LTDA", "11.222.333/0001-81", "45077-014", "Sra. FULANA"))
        self.assertEqual((c["representantes"][0]["cpf"], c["representantes"][0]["cep"]), ("529.982.247-25", "45820-000"))
        # quem não veio fica vazio, e toda empresa tem pelo menos um representante para preencher
        self.assertEqual(d["garantidor"]["razao_social"], "")
        self.assertEqual(len(d["garantidor"]["representantes"]), 1)
        self.assertNotIn("poderes", d["garantidor"])
        self.assertEqual(normalizar({"tipo": "pf"})["data"], None)

    def test_o_modelo_pessoa_fisica(self):
        d = normalizar(PF)
        # o representante da compradora sai sem "Sr./Sra." e sem o endereço de casa; quem garante é uma pessoa
        self.assertEqual(sorted(d["compradora"]["representantes"][0]),
                         ["cpf", "estado_civil", "nacionalidade", "nome", "profissao", "rg"])
        self.assertNotIn("poderes", d["compradora"])
        self.assertEqual(sorted(d["garantidor"]),
                         ["cep", "cpf", "endereco", "estado_civil", "nacionalidade", "nome", "profissao", "rg"])

    def test_recusa(self):
        for dados, erro in (({}, "escolha quem garante"), ({"tipo": "outro"}, "escolha quem garante"),
                            ({"tipo": "pj", "data": "04/02/2026"}, "data"), ({"tipo": "pj", "data": "0026-02-04"}, "ano"),
                            ({"tipo": "pj", "compradora": {"razao_social": "x" * 201}}, "passou de 200"),
                            ({"tipo": "pj", "compradora": {"razao_social": ["x"]}}, "valor inválido"),
                            ({"tipo": "pj", "compradora": {"representantes": [{}] * (MAX_REPRESENTANTES + 1)}}, "no máximo"),
                            ({"tipo": "pj", "garantidor": {"representantes": [{"tratamento": "Dr."}]}}, "Sr. ou Sra.")):
            with self.assertRaisesRegex(ValueError, erro):
                normalizar(dados)
        # o que não tem o formato esperado vale como vazio
        self.assertEqual(normalizar({"tipo": "pf", "garantidor": "x", "compradora": 3})["garantidor"]["nome"], "")

    def test_o_que_falta(self):
        self.assertEqual(pendencias(normalizar(PJ)), [])
        self.assertEqual(pendencias(normalizar(PF)), [])
        vazio = [p["texto"] for p in pendencias(normalizar({"tipo": "pj"}))]
        self.assertEqual(len(vazio), 29)  # 5 + 9 da compradora, 5 + 9 da garantidora e a data
        self.assertEqual((vazio[0], vazio[5], vazio[-1]),
                         ("Compradora: razão social", "Compradora, representante: Sr. ou Sra.", "Data do contrato"))
        self.assertNotIn("Compradora: inscrição estadual", vazio)  # "se houver"
        vazio = [p["campo"] for p in pendencias(normalizar({"tipo": "pf"}))]
        self.assertEqual(len(vazio), 5 + 6 + 8 + 1)
        self.assertIn("garantidor.endereco", vazio)
        self.assertNotIn("compradora.representantes.0.endereco", vazio)

    def test_o_que_nao_confere(self):
        d = copy.deepcopy(PJ)
        d["compradora"]["cnpj"] = "11.222.333/0001-82"
        d["compradora"]["cep"] = "45077"
        d["garantidor"]["representantes"][0]["cpf"] = "111.444.777-36"
        self.assertEqual(pendencias(normalizar(d)), [
            {"campo": "compradora.cnpj", "texto": "Compradora: o CNPJ não confere (dígitos verificadores)"},
            {"campo": "compradora.cep", "texto": "Compradora: o CEP tem 8 números"},
            {"campo": "garantidor.representantes.0.cpf",
             "texto": "Garantidora, representante 1: o CPF não confere (dígitos verificadores)"}])
        d = copy.deepcopy(PJ)
        d["garantidor"]["cnpj"] = "11222333000181"  # quem garante não pode ser a própria compradora
        self.assertEqual(pendencias(normalizar(d)),
                         [{"campo": "garantidor.cnpj", "texto": "Garantidora: o CNPJ é o mesmo da compradora"}])

    def test_os_dados_da_mais_vida(self):
        self.assertEqual(_valida_fornecedor(PADRAO_FORNECEDOR), PADRAO_FORNECEDOR)
        self.assertEqual(faltas_do_fornecedor(PADRAO_FORNECEDOR, "pj"), [])
        self.assertEqual(faltas_do_fornecedor(PADRAO_FORNECEDOR, "pf"),
                         ["nacionalidade", "estado civil", "profissão", "RG", "CPF"])
        self.assertEqual(faltas_do_fornecedor(MAIS_VIDA, "pf"), [])
        self.assertEqual(_valida_fornecedor({**MAIS_VIDA, "cnpj": "96845748000164"})["cnpj"], "96.845.748/0001-64")
        for mudar, erro in (({"razao_social": " "}, "preencha razão social"), ({"cnpj": "96.845.748/0001-65"}, "CNPJ"),
                            ({"cpf": "111.444.777-36"}, "CPF"), ({"tratamento": "Dr."}, "Sr. ou Sra."),
                            ({"representante": ""}, "preencha nome de quem representa")):
            with self.assertRaisesRegex(ValueError, erro):
                _valida_fornecedor({**MAIS_VIDA, **mudar})


class TestTexto(unittest.TestCase):
    def test_as_clausulas_fixas(self):
        pj = "\n".join(t for _, t in PJ_CLAUSULAS)
        pf = "\n".join(t for _, t in PF_CLAUSULAS)
        self.assertEqual((sum(1 for e, _ in PJ_CLAUSULAS if e == "T"), sum(1 for e, _ in PF_CLAUSULAS if e == "T")),
                         (11, 14))  # as 11 cláusulas do Pessoa Jurídica; da 2 à 15 no Pessoa Física
        # as correções combinadas com o usuário
        self.assertIn("que não será inferior a 5 (cinco) dias úteis", pj)
        self.assertIn("1% ao mês (conforme Art. 406 do Código Civil c/c Art. 161, §1º do CTN), calculados //pro rata die//", pf)
        self.assertIn("Foro da Comarca de Itabela - BA,", pf)
        # nada do caso que estava nos modelos, nem colchete por preencher
        for texto in (pj, pf):
            for resto in ("DAMIANA", "TRENTO", "VITSUKO", "[", "  "):
                self.assertNotIn(resto, texto)
        self.assertEqual(pj.count("{"), 3)
        self.assertEqual(pf.count("{"), 0)

    def test_marcas(self):
        self.assertEqual(trechos("a **b** c //d// e"), [("a ", ""), ("b", "B"), (" c ", ""), ("d", "I"), (" e", "")])
        # o que a pessoa digita entra depois de separar as marcas: nunca vira negrito nem campo
        self.assertEqual(trechos("**{nome}**, de {onde}", {"nome": "**X** {onde}", "onde": "//Y//"}),
                         [("**X** {onde}", "B"), (", de //Y//", "")])

    def test_a_data(self):
        self.assertEqual(data_por_extenso("2026-02-04"), "4 de fevereiro de 2026")
        self.assertEqual(data_por_extenso("2026-03-01"), "1º de março de 2026")
        self.assertIn("____", data_por_extenso(None))

    def test_pessoa_juridica(self):
        t = texto_do_contrato(PJ)
        linhas = t.split("\n")
        self.assertEqual(linhas[0], "CONTRATO DE GARANTIA FIDEJUSSÓRIA E OUTRAS AVENÇAS")
        self.assertIn("FORNECEDOR: LATICINIO MAIS VIDA LTDA, pessoa jurídica de direito privado, inscrita no CNPJ sob o nº "
                      "96.845.748/0001-64, com sede na Av. Guaratinga, km 02, Zona Rural, Itabela - BA, CEP 45848-000, neste "
                      "ato representada por seu sócio administrador, Sr. MAURO SERGIO PIMENTEL QUEIROZ, doravante denominada "
                      "simplesmente FORNECEDOR;", linhas)
        self.assertIn("COMPRADORA: MERCADO NOVO LTDA, com sede em Rua B, 220, Zabelê, Vitória da Conquista - BA, CEP "
                      "45077-014, inscrita no CNPJ sob o nº 11.222.333/0001-81, e Inscrição Estadual nº 078.420.714, neste ato "
                      "representada por seu(s) sócio administrador, Sra. MARIA DA SILVA, Brasileira, Casada, Empresária, "
                      "portador(a) da Cédula de Identidade RG nº 1234567890 e inscrito(a) no CPF sob o nº 529.982.247-25, "
                      "residente e domiciliado(a) em Rua das Flores, 100, Centro, Eunápolis - BA, CEP 45820-000, BRASIL. "
                      "Doravante denominada simplesmente COMPRADORA;", linhas)
        self.assertIn("E, como interveniente garantidora:", linhas)  # em parágrafo próprio
        # a garantidora sem inscrição estadual e com dois sócios
        self.assertIn("inscrita no CNPJ sob o nº 22.333.444/0001-81, neste ato representada por seu(s) sócio administrador, "
                      "Sr. JOSE DE SOUZA, Brasileiro, Casado, Empresário, portador(a) da Cédula de Identidade RG nº 9876543210", t)
        self.assertIn(", BRASIL, e Sra. MARIA DA SILVA, ", t)
        self.assertIn("a) FORNECEDOR: A empresa LATICINIO MAIS VIDA LTDA, responsável", t)
        self.assertIn("b) COMPRADORA: A empresa MERCADO NOVO LTDA, responsável", t)
        self.assertIn("c) GARANTIDORA: A empresa SUPERMERCADO FORTE LTDA, que assume", t)
        self.assertIn("Itabela – BA, 4 de fevereiro de 2026.", linhas)
        self.assertIn("LATICINIO MAIS VIDA LTDA CNPJ nº 96.845.748/0001-64", linhas)  # o modelo trazia "[Número do CNPJ]"
        self.assertIn("Representada por: Sr. JOSE DE SOUZA e Sra. MARIA DA SILVA", linhas)
        self.assertEqual(linhas.count("Sócio administrador"), 3)
        self.assertNotIn("conforme poderes", t)
        self.assertNotIn(LACUNA, t)
        self.assertNotIn("[", t)

    def test_poderes_so_quando_preenchido(self):
        d = copy.deepcopy(PJ)
        d["compradora"]["poderes"] = "Sr. FULANO DE TAL, portador do CPF nº 111.444.777-35"
        self.assertIn(", BRASIL, conforme poderes conferidos por Sr. FULANO DE TAL, portador do CPF nº 111.444.777-35. "
                      "Doravante denominada simplesmente COMPRADORA;", texto_do_contrato(d))

    def test_pessoa_fisica(self):
        t = texto_do_contrato(PF, MAIS_VIDA)
        linhas = t.split("\n")
        self.assertEqual(linhas[0], "CONTRATO DE COMPRA E VENDA DE PRODUTOS LÁCTEOS POR PRAZO INDETERMINADO E OUTRAS AVENÇAS")
        self.assertIn("1.1. COMPRADORA: MERCADO NOVO LTDA, pessoa jurídica de direito privado, inscrita no CNPJ sob o nº "
                      "11.222.333/0001-81, com Inscrição Estadual nº 078.420.714, com sede e foro na Rua B, 220, Zabelê, "
                      "Vitória da Conquista - BA, CEP 45077-014, neste ato representada por seu(s) sócio administrador, MARIA "
                      "DA SILVA, Brasileira, Casada, Empresária, portador(a) da Cédula de Identidade RG nº 1234567890 e "
                      "inscrito(a) no CPF sob o nº 529.982.247-25, doravante denominada simplesmente \"COMPRADORA\".", linhas)
        self.assertIn("1.2. FORNECEDOR: LATICINIO MAIS VIDA LTDA, pessoa jurídica de direito privado, inscrita no CNPJ sob o "
                      "nº 96.845.748/0001-64, com Inscrição Estadual nº 012.345.678, com sede e foro na Av. Guaratinga, km 02, "
                      "Zona Rural, Itabela - BA, CEP 45848-000, neste ato representada por seu(s) sócio administrador, MAURO "
                      "SERGIO PIMENTEL QUEIROZ, brasileiro, casado, empresário, portador(a) da Cédula de Identidade RG nº "
                      "0102030405 e inscrito(a) no CPF sob o nº 111.444.777-35, doravante denominado simplesmente "
                      "\"FORNECEDOR\".", linhas)
        self.assertIn("1.3. GARANTIDORA: JOSE DE SOUZA, Brasileiro, Casado, Empresário, portador(a) da Cédula de Identidade RG "
                      "nº 9876543210 e inscrito(a) no CPF sob o nº 111.444.777-35, residente e domiciliado(a) na Rua das "
                      "Flores, 100, Centro, Eunápolis - BA, CEP 45820-000, doravante denominada simplesmente "
                      "\"GARANTIDORA\".", linhas)
        self.assertIn("Itabela – BA, 1º de fevereiro de 2026.", linhas)
        self.assertIn("MERCADO NOVO LTDA CNPJ: 11.222.333/0001-81", linhas)
        self.assertIn("Representada por: MARIA DA SILVA", linhas)
        self.assertIn("JOSE DE SOUZA CPF: 111.444.777-35", linhas)
        self.assertNotIn(LACUNA, t)

    def test_o_que_falta_vira_linha(self):
        t = texto_do_contrato({"tipo": "pf", "compradora": {"razao_social": "MERCADO NOVO LTDA"}})
        self.assertIn(f"1.1. COMPRADORA: MERCADO NOVO LTDA, pessoa jurídica de direito privado, inscrita no CNPJ sob o nº "
                      f"{LACUNA}, com sede e foro na {LACUNA}, CEP {LACUNA}, neste ato representada por seu(s) {LACUNA}, "
                      f"{LACUNA}, {LACUNA}, {LACUNA}, {LACUNA}, portador(a) da Cédula de Identidade RG nº {LACUNA} e "
                      f"inscrito(a) no CPF sob o nº {LACUNA}, doravante", t)
        self.assertIn(f"1.3. GARANTIDORA: {LACUNA}, {LACUNA}", t)
        self.assertIn(f"Itabela – BA, {data_por_extenso(None)}.", t)
        # a Mais Vida sem a qualificação de quem representa (o padrão): também em linha
        self.assertIn(f"MAURO SERGIO PIMENTEL QUEIROZ, {LACUNA}, {LACUNA}, {LACUNA}, portador(a) da Cédula de Identidade RG nº "
                      f"{LACUNA} e inscrito(a) no CPF sob o nº {LACUNA}, doravante", t)
        self.assertNotIn("Inscrição Estadual", t)

    def test_nome_do_arquivo(self):
        self.assertEqual(nome_arquivo(normalizar(PJ)), "Contrato de avalista PJ - MERCADO NOVO LTDA.pdf")
        d = normalizar({"tipo": "pf", "compradora": {"razao_social": 'A/B: "C" <D> | E? *F*.'}})
        self.assertEqual(nome_arquivo(d), "Contrato de avalista PF - A B C D E F.pdf")
        self.assertEqual(nome_arquivo(normalizar({"tipo": "pf"})), "Contrato de avalista PF.pdf")


class TestPdf(unittest.TestCase):
    def ler(self, conteudo: bytes):
        from pypdf import PdfReader
        return PdfReader(io.BytesIO(conteudo))

    def texto(self, pdf) -> str:
        return " ".join(" ".join(p.extract_text() for p in pdf.pages).split())

    def test_pessoa_juridica(self):
        conteudo = documento(normalizar(PJ), PADRAO_FORNECEDOR)
        self.assertTrue(conteudo.startswith(b"%PDF"))
        pdf = self.ler(conteudo)
        self.assertEqual(len(pdf.pages), 6)  # como o modelo em Word
        caixa = pdf.pages[0].mediabox
        self.assertEqual((round(float(caixa.width)), round(float(caixa.height))), (595, 842))  # A4
        t = self.texto(pdf)
        self.assertIn("CONTRATO DE GARANTIA FIDEJUSSÓRIA E OUTRAS AVENÇAS", t)
        self.assertIn("CLÁUSULA DÉCIMA PRIMEIRA – DA LEI APLICÁVEL E FORO", t)
        self.assertIn("que não será inferior a 5 (cinco) dias úteis", t)
        self.assertIn("MERCADO NOVO LTDA CNPJ nº 11.222.333/0001-81", t)
        self.assertIn("TESTEMUNHAS:", t)
        # o cabeçalho da Mais Vida em todas as páginas
        self.assertEqual([p.extract_text().count("Av. Guaratinga, km 02, Zona Rural, Itabela - BA.") for p in pdf.pages],
                         [1] * 6)
        self.assertEqual(pdf.metadata.title, "Contrato de Garantia Fidejussória e Outras Avenças – MERCADO NOVO LTDA")

    def test_pessoa_fisica(self):
        pdf = self.ler(documento(normalizar(PF), MAIS_VIDA))
        self.assertEqual(len(pdf.pages), 6)
        t = self.texto(pdf)
        self.assertIn("15.2. Fica eleito o Foro da Comarca de Itabela - BA, para dirimir", t)
        self.assertIn("calculados pro rata die, sem prejuízo", t)
        self.assertIn("GARANTIDOR:", t)
        self.assertNotIn("Av. Guaratinga, km 02, Zona Rural, Itabela - BA.", t)  # este modelo não tem cabeçalho

    def test_pela_metade_e_com_texto_estranho(self):
        # nada preenchido: sai o contrato com as linhas para completar à mão
        pdf = self.ler(documento(normalizar({"tipo": "pj"}), PADRAO_FORNECEDOR))
        self.assertGreaterEqual(len(pdf.pages), 5)
        # quatro representantes de cada lado, nomes compridos e sinais que não são marcas do contrato
        d = copy.deepcopy(PJ)
        d["compradora"]["razao_social"] = "**EMPRESA** {x} //DE// TESTE & FILHOS – COMÉRCIO DE ALIMENTOS E BEBIDAS LTDA " * 2
        d["compradora"]["representantes"] = [SOCIO] * MAX_REPRESENTANTES
        d["garantidor"]["representantes"] = [SOCIO_2] * MAX_REPRESENTANTES
        d["compradora"]["endereco"] = "Rua " + "muito-comprida-" * 15 + "sem espaço, 1"
        t = self.texto(self.ler(documento(normalizar(d), PADRAO_FORNECEDOR)))
        self.assertIn("**EMPRESA** {x} //DE// TESTE & FILHOS", t)
        self.assertIn("TESTEMUNHAS:", t)


class Base(BaseBanco):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.calc = criar_calc(Path(self._tmp.name))
        self.credito = Credito(self.calc.cache, lambda: dict(NOMES))
        self.config = ConfigAvalista(self.banco)
        self.av = Avalistas(self.banco, self.credito, self.config, ativo=True)
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

    def salvar(self, dados: dict = PJ, quem=None, **mais) -> dict:
        return self.av.salvar(quem or self.ana, {"chave": novo_id(), "dados": dados, **mais})


class TestContratos(Base):
    def test_salva_pela_metade_e_lista(self):
        vazia = self.av.listar(self.ana)
        self.assertEqual((vazia["ativo"], vazia["contratos"], vazia["pode_fornecedor"], vazia["fornecedor"]),
                         (True, [], False, PADRAO_FORNECEDOR))
        self.assertEqual(vazia["fornecedor_falta"]["pj"], [])
        r = self.salvar({"tipo": "pf", "compradora": {"razao_social": "mercado novo ltda"}})
        c = r["contrato"]
        self.assertEqual((r["ja_existia"], c["tipo"], c["compradora"], c["garantidor"], c["compradora_cnpj"], c["versao"],
                          c["feito_por"], c["editado_em"], c["pode_editar"], c["faltam"], len(c["pendencias"])),
                         (False, "pf", "mercado novo ltda", None, None, 1, "Ana", None, True, 19, 19))
        self.assertEqual([x["id"] for x in r["contratos"]], [c["id"]])
        self.assertNotIn("dados", r["contratos"][0])  # a lista leva só a linha; o contrato inteiro vem ao abrir
        with self.assertRaisesRegex(ValueError, "razão social da compradora"):
            self.salvar({"tipo": "pf"})
        with self.assertRaisesRegex(ValueError, "expirou"):
            self.av.salvar(self.ana, {"chave": "x", "dados": PJ})

    def test_a_mesma_chave_grava_uma_vez(self):
        corpo = {"chave": novo_id(), "dados": PJ}
        a, b = self.av.salvar(self.ana, corpo), self.av.salvar(self.ana, corpo)
        self.assertEqual((b["ja_existia"], b["id"], self.contar("credito_avalistas")), (True, a["id"], 1))
        with self.assertRaisesRegex(ValueError, "expirou"):  # a chave de outra pessoa
            self.av.salvar(self.bia, corpo)

    def test_guarda_e_abre(self):
        id_ = self.salvar()["id"]
        with self.banco.conexao() as con:
            linha = con.execute("SELECT tipo, compradora, compradora_cnpj, garantidor, garantidor_doc, versao, "
                                "feito_por_nome FROM credito_avalistas WHERE id = %s", [id_]).fetchone()
        self.assertEqual(linha, ("pj", "MERCADO NOVO LTDA", "11222333000181", "SUPERMERCADO FORTE LTDA", "22333444000181",
                                 1, "Ana"))
        c = self.av.listar(self.bia, id_=id_)["contrato"]  # todos com a página de crédito veem; só o dono muda
        self.assertEqual((c["dados"], c["pendencias"], c["pode_editar"], c["pode_excluir"], c["compradora_cnpj"],
                          c["garantidor_doc"], c["data"]),
                         (normalizar(PJ), [], False, False, "11.222.333/0001-81", "22.333.444/0001-81", "2026-02-04"))
        with self.assertRaises(NaoEncontrada):
            self.av.listar(self.ana, id_=id_ + 1)
        with self.assertRaises(NaoEncontrada):
            self.av.listar(self.ana, id_="x")

    def test_editar_grava_por_cima(self):
        r = self.salvar()
        id_ = r["id"]
        novo = copy.deepcopy(PJ)
        novo["compradora"]["razao_social"] = "MERCADO NOVO COMERCIO LTDA"
        with self.assertRaisesRegex(PermissionError, "quem fez"):
            self.av.salvar(self.bia, {"id": id_, "versao": 1, "dados": novo})
        e = self.av.salvar(self.ana, {"id": id_, "versao": 1, "dados": novo})
        c = e["contrato"]
        self.assertEqual((e["id"], c["compradora"], c["versao"], c["feito_por"], c["editado_por"], self.contar("credito_avalistas")),
                         (id_, "MERCADO NOVO COMERCIO LTDA", 2, "Ana", "Ana", 1))
        self.assertIsNotNone(c["editado_em"])
        with self.assertRaisesRegex(ValueError, "alterado por outra pessoa"):  # com a versão de antes
            self.av.salvar(self.ana, {"id": id_, "versao": 1, "dados": PJ})
        self.assertEqual(MUDOU[:13], "este contrato")
        # o administrador edita o de qualquer um, e pode trocar o tipo
        e = self.av.salvar(self.admin, {"id": id_, "versao": 2, "dados": PF})["contrato"]
        self.assertEqual((e["tipo"], e["garantidor"], e["garantidor_doc"], e["versao"], e["editado_por"], e["feito_por"]),
                         ("pf", "JOSE DE SOUZA", "111.444.777-35", 3, "Chefe", "Ana"))

    def test_excluir(self):
        a, b = self.salvar()["id"], self.salvar(PF)["id"]
        with self.assertRaisesRegex(PermissionError, "quem fez"):
            self.av.excluir(self.bia, a)
        r = self.av.excluir(self.ana, a)
        self.assertEqual([x["id"] for x in r["contratos"]], [b])
        self.assertEqual((self.contar("credito_avalistas"), self.contar("credito_avalistas", "excluido_em IS NOT NULL "
                          "AND excluido_por_nome = 'Ana'")), (2, 1))  # a linha fica
        for acao in (lambda: self.av.excluir(self.ana, a), lambda: self.av.pdf(a),
                     lambda: self.av.salvar(self.ana, {"id": a, "versao": 1, "dados": PJ})):
            with self.assertRaises(NaoEncontrada):
                acao()
        self.assertEqual(self.av.excluir(self.admin, b)["contratos"], [])

    def test_busca(self):
        a = self.salvar()["id"]
        b = self.salvar({"tipo": "pf", "compradora": {"razao_social": "Açougue São José Ltda", "cnpj": "12ABC34501DE35"},
                         "garantidor": {"nome": "João da Conceição", "cpf": "529.982.247-25"}})["id"]

        def achados(texto):
            r = self.av.listar(self.ana, texto)
            return [x["id"] for x in r["contratos"]]
        self.assertEqual(achados(None), [b, a])
        self.assertEqual(achados("acougue sao"), [b])
        self.assertEqual(achados("SUPERMERCADO  forte"), [a])       # quem garante
        self.assertEqual(achados("joao da conceicao"), [b])
        self.assertEqual(achados("11.222.333"), [a])                # o CNPJ da compradora
        self.assertEqual(achados("22333444"), [a])                  # o de quem garante
        self.assertEqual(achados("529.982"), [b])                   # o CPF
        self.assertEqual(achados("12.abc.345"), [b])                # CNPJ com letras
        self.assertEqual(achados("100%"), [])
        self.assertEqual(self.av.listar(self.ana, "  forte ")["busca"], "forte")

    def test_o_pdf_do_contrato_guardado(self):
        id_ = self.salvar()["id"]
        conteudo, nome = self.av.pdf(id_)
        self.assertTrue(conteudo.startswith(b"%PDF"))
        self.assertEqual(nome, "Contrato de avalista PJ - MERCADO NOVO LTDA.pdf")
        self.assertEqual(self.av.conferir({"dados": PJ}), {"dados": normalizar(PJ), "pendencias": []})


class TestClienteDoErp(Base):
    def test_puxa_a_razao_social_e_o_cnpj(self):
        self.assertEqual(self.av.cliente(1), {"id": 1, "nome": "MERCADO DO JOAO", "razao_social": "JOAO COMERCIO LTDA",
                                             "cnpj": "11.222.333/0001-81", "cidade": "VILA VELHA", "uf": "ES"})
        self.assertEqual(self.av.cliente("3")["cnpj"], None)  # sem CNPJ no ERP: a pessoa digita
        self.assertEqual(self.av.cliente(4)["razao_social"], "MERCEARIA DO EDIR")  # sem o detalhe: o nome
        for valor in ("x", None, 999):
            with self.assertRaises(ValueError):
                self.av.cliente(valor)

    def test_o_acesso(self):
        self.assertEqual(self.av.cliente(1, frozenset({ES}))["id"], 1)
        with self.assertRaisesRegex(PermissionError, "não é dos vendedores"):
            self.av.cliente(2, frozenset({ES}))
        # o contrato ligado a um cliente: só dos vendedores do acesso
        r = self.salvar(id_cliente=1)
        self.assertEqual(r["contrato"]["id_cliente"], 1)
        with self.assertRaisesRegex(PermissionError, "não é dos vendedores"):
            self.av.salvar(self.ana, {"chave": novo_id(), "dados": PJ, "id_cliente": 2}, frozenset({ES}))
        self.assertEqual(self.av.salvar(self.ana, {"chave": novo_id(), "dados": PJ, "id_cliente": 2},
                                        frozenset({BA}))["contrato"]["id_cliente"], 2)
        for valor in ("x", 0, -3):
            with self.assertRaisesRegex(ValueError, "cliente inválido"):
                self.salvar(id_cliente=valor)


class TestMaisVida(Base):
    def test_so_o_administrador_muda(self):
        with self.assertRaisesRegex(PermissionError, "só o administrador"):
            self.av.salvar_fornecedor(self.ana, MAIS_VIDA)
        with self.assertRaisesRegex(ValueError, "CNPJ"):
            self.av.salvar_fornecedor(self.admin, {**MAIS_VIDA, "cnpj": "1"})
        r = self.av.salvar_fornecedor(self.admin, {**MAIS_VIDA, "endereco": "  Av. Nova,   10, Itabela - BA "})
        self.assertEqual((r["fornecedor"]["endereco"], r["fornecedor_falta"], r["pode_fornecedor"]),
                         ("Av. Nova, 10, Itabela - BA", {"pj": [], "pf": []}, True))
        self.assertEqual(self.contar("regras", "nome = 'avalista' AND salva_por_nome = 'Chefe'"), 1)
        # vale para o contrato que já estava guardado: o PDF sai com os dados de agora
        id_ = self.salvar(PF)["id"]
        from pypdf import PdfReader
        texto = " ".join(" ".join(p.extract_text() for p in PdfReader(io.BytesIO(self.av.pdf(id_)[0])).pages).split())
        self.assertIn("com sede e foro na Av. Nova, 10, Itabela - BA, CEP 45848-000", texto)
        self.assertIn("MAURO SERGIO PIMENTEL QUEIROZ, brasileiro, casado, empresário", texto)
        # outra instância (o painel reiniciado) lê o que foi salvo
        self.assertEqual(ConfigAvalista(self.banco).atual()["rg"], "0102030405")


class TestNoPc(Base):
    def test_so_avisa(self):
        pc = Avalistas(self.banco, self.credito, self.config, ativo=False)
        self.assertEqual(pc.listar(self.ana), {"ativo": False, "aviso": AVISO_PC, "contratos": []})
        for acao in (lambda: pc.salvar(self.ana, {"chave": novo_id(), "dados": PJ}), lambda: pc.excluir(self.ana, 1),
                     lambda: pc.pdf(1), lambda: pc.salvar_fornecedor(self.admin, MAIS_VIDA)):
            with self.assertRaisesRegex(ValueError, "ficam no site"):
                acao()
        self.assertEqual(self.contar("credito_avalistas"), 0)


if __name__ == "__main__":
    unittest.main()

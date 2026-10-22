"""Arquivos Excel e PDF do Assistente (bi/arquivos.py): formatos das colunas, o Excel lido de volta e o PDF.

Os testes do Excel e do PDF precisam dos pacotes XlsxWriter e fpdf2; sem eles, são pulados.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from bi import arquivos
from bi.planilhas import ler_tabela

TEM_XLSX = importlib.util.find_spec("xlsxwriter") is not None
TEM_PDF = importlib.util.find_spec("fpdf") is not None

COLUNAS = ["Código", "Cliente", "Última compra", "Venda líquida (R$)", "Clientes", "% da meta", "Quantidade (kg)",
           "Ativo"]
LINHAS = [(10 + i, "=SOMA(A1:A2)" if i == 0 else f"MERCADO SÃO JOÃO {i}", dt.date(2026, 9, 1 + i), 1234.5 * i - 300,
           3 + i, 87.46, 12.5 * i, i % 2 == 0) for i in range(5)]


def ler_excel(conteudo: bytes, colunas: dict[str, str]) -> list[dict]:
    with tempfile.TemporaryDirectory() as pasta:
        caminho = Path(pasta) / "arquivo.xlsx"
        caminho.write_bytes(conteudo)
        return ler_tabela(caminho, colunas)


def paginas(conteudo: bytes) -> int:
    return int(re.search(rb"/Count (\d+)", conteudo).group(1))


class TestFormatos(unittest.TestCase):
    def test_pelo_tipo_e_pelo_nome(self):
        self.assertEqual(arquivos.formatos(COLUNAS, LINHAS),
                         ["codigo", "texto", "data", "reais", "inteiro", "percentual", "numero", "logico"])
        colunas = ["id_cliente", "valor_liquido", "ano", "mes", "venda_media", "pct_limite_usado", "quantidade",
                   "vazia", "dias_atraso", "data_hora"]
        linhas = [(1, 10.5, 2026, 9, 3.2, 50.0, 12, None, 3, dt.datetime(2026, 9, 1, 14, 30))]
        self.assertEqual(arquivos.formatos(colunas, linhas),
                         ["codigo", "reais", "codigo", "codigo", "reais", "percentual", "inteiro", "texto", "inteiro",
                          "data_hora"])

    def test_texto_brasileiro(self):
        t = arquivos.texto
        self.assertEqual(t(1234.5, "reais"), "R$ 1.234,50")
        self.assertEqual(t(-300, "reais"), "-R$ 300,00")
        self.assertEqual(t(87.46, "percentual"), "87,5%")
        self.assertEqual(t(1234567, "inteiro"), "1.234.567")
        self.assertEqual(t(2026, "codigo"), "2026")
        self.assertEqual(t(dt.date(2026, 9, 1), "data"), "01/09/2026")
        self.assertEqual(t(dt.datetime(2026, 9, 1, 14, 30), "data_hora"), "01/09/2026 14:30")
        self.assertEqual(t(float("nan"), "numero"), "")
        self.assertEqual(t(None, "texto"), "")
        self.assertEqual(t(True, "logico"), "Sim")

    def test_nome_do_arquivo(self):
        self.assertEqual(arquivos.nome_arquivo('Clientes: "top" / ES?', "excel", dt.date(2026, 10, 22)),
                         "Clientes top ES - 2026-10-22.xlsx")
        self.assertEqual(arquivos.nome_arquivo("  ", "pdf", dt.date(2026, 10, 22)), "Assistente - 2026-10-22.pdf")


@unittest.skipUnless(TEM_XLSX, "sem o pacote XlsxWriter")
class TestExcel(unittest.TestCase):
    def test_lido_de_volta(self):
        conteudo = arquivos.excel("Clientes de setembro", "Valor líquido", "Pedido por Admin", COLUNAS, LINHAS)
        linhas = ler_excel(conteudo, {"cod": "Código", "cliente": "Cliente", "valor": "Venda líquida (R$)",
                                      "data": "Última compra", "ativo": "Ativo"})
        self.assertEqual([int(ln["cod"]) for ln in linhas], [10, 11, 12, 13, 14])
        self.assertEqual(linhas[0]["cliente"], "=SOMA(A1:A2)")  # texto, não fórmula
        self.assertEqual(linhas[1]["cliente"], "MERCADO SÃO JOÃO 1")
        self.assertEqual(float(linhas[1]["valor"]), 934.5)  # o número continua número
        self.assertEqual(int(linhas[0]["data"]), (dt.date(2026, 9, 1) - dt.date(1899, 12, 30)).days)
        self.assertEqual((linhas[0]["ativo"], linhas[1]["ativo"]), ("Sim", "Não"))
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            folha = z.read("xl/worksheets/sheet1.xml").decode()
            estilos = z.read("xl/styles.xml").decode()
        self.assertNotIn("<f>", folha)
        self.assertIn('ySplit="5"', folha)                 # título, descrição e informação em cima; cabeçalho congelado
        self.assertIn('<autoFilter ref="A5:H10"/>', folha)
        self.assertIn('formatCode="&quot;R$&quot; #,##0.00"', estilos)
        self.assertIn('formatCode="0.0&quot;%&quot;"', estilos)
        self.assertIn('formatCode="dd/mm/yyyy"', estilos)

    def test_sem_linhas(self):
        conteudo = arquivos.excel("Vazio", "", "", ["Cliente"], [])
        self.assertEqual(ler_excel(conteudo, {"c": "Cliente"}), [])


@unittest.skipUnless(TEM_PDF, "sem o pacote fpdf2")
class TestPdf(unittest.TestCase):
    def test_com_a_resposta(self):
        resposta = ("Em **setembro**, 5 clientes − veja ≈ tudo 😀.\n\n## Destaques\n- um item\n1. primeiro\n\n"
                    "| Equipe | Venda (R$) |\n|---|--:|\n| ES | R$ 1.234,56 |")
        conteudo = arquivos.pdf("Clientes de setembro", "Valor líquido", "Pedido por Admin", resposta, COLUNAS, LINHAS)
        self.assertTrue(conteudo.startswith(b"%PDF"))
        self.assertEqual(paginas(conteudo), 1)

    def test_colunas_que_nao_cabem_em_pe_deitam_a_pagina(self):
        colunas = [f"Coluna {k}" for k in range(8)]
        linhas = [tuple(f"um texto mais comprido {i}-{k}" for k in range(8)) for i in range(20)]
        self.assertIn(b"/MediaBox [0 0 841.89 595.28]", arquivos.pdf("Largo", "", "", "", colunas, linhas))

    def test_muitas_linhas_quebram_a_pagina(self):
        linhas = [(i, f"CLIENTE {i} " + "NOME COMPRIDO " * (i % 4)) for i in range(400)]
        conteudo = arquivos.pdf("Lista", "", "", "", ["Código", "Cliente"], linhas)
        self.assertGreater(paginas(conteudo), 5)
        self.assertNotIn(b"/MediaBox [0 0 841.89 595.28]", conteudo)  # duas colunas: em pé

    def test_sem_linhas(self):
        conteudo = arquivos.pdf("Vazio", "", "", "", ["Cliente"], [])
        self.assertEqual(paginas(conteudo), 1)


if __name__ == "__main__":
    unittest.main()

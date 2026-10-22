"""Arquivos que o Assistente prepara para baixar: Excel e PDF.

- A IA escolhe a consulta, o título e o formato (ferramenta gerar_arquivo, bi/assistente.py). O arquivo é montado
  quando a pessoa clica em Baixar: a consulta roda de novo no recorte de quem baixa, e o resultado vem para cá.
- O formato de cada coluna sai do tipo e do nome: "(R$)" ou nome de valor (valor, venda, faturamento, ticket…) =
  reais; "%" = percentual (12,3 = 12,3%); código, ano e mês sem separador de milhar; datas em dd/mm/aaaa.
- Excel: título, descrição e a linha de informação em cima, o cabeçalho com filtro e congelado e uma linha por linha
  da consulta (XlsxWriter em modo de memória constante: 50.000 linhas usam poucos MB). PDF (fpdf2): o mesmo
  cabeçalho, o texto da resposta do Assistente e a tabela; a página deita quando as colunas não cabem em pé.
- XlsxWriter e fpdf2 só são importados na hora de montar: sem eles o painel abre, e só o download avisa o que falta.
"""
from __future__ import annotations

import datetime as dt
import decimal
import importlib
import io
import math
import re
import unicodedata

EXCEL, PDF = "excel", "pdf"
TIPOS = {EXCEL: (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
         PDF: (".pdf", "application/pdf")}
MAX_LINHAS = {EXCEL: 50000, PDF: 2000}
PACOTES = {EXCEL: ("xlsxwriter", "XlsxWriter"), PDF: ("fpdf", "fpdf2")}

NUM_EXCEL = {"reais": '"R$" #,##0.00', "numero": "#,##0.00", "inteiro": "#,##0", "codigo": "0",
             "percentual": '0.0"%"', "data": "dd/mm/yyyy", "data_hora": "dd/mm/yyyy hh:mm"}
NUMERICOS = ("reais", "numero", "inteiro", "codigo", "percentual")
_REAIS = re.compile(r"(^|\W)(r\$|valor|valores|venda|vendas|vendido|faturamento|faturado|bruto|bruta|liquido|liquida|"
                    r"devolvido|ticket|limite|saldo|preco|pago|receita|custo)(\W|$)")
_PERCENTUAL = re.compile(r"%|(^|\W)(pct|percent|percentual|porcentagem)(\W|$)")
_CODIGO = {"id", "cod", "codigo", "ano", "mes", "titulo", "nf"}

# Cores do painel (as mesmas do CSS).
MARINHO, LARANJA, TINTA, CINZA = (0, 46, 93), (245, 130, 32), (35, 45, 60), (100, 112, 130)
LINHA, ZEBRA = (215, 222, 230), (244, 246, 249)


class FaltaPacote(RuntimeError):
    """O pacote do formato não está instalado no servidor."""


def _importar(formato: str):
    modulo, pacote = PACOTES[formato]
    try:
        return importlib.import_module(modulo)
    except ImportError:
        raise FaltaPacote(f"falta instalar o pacote {pacote} no servidor (pip install {pacote})") from None


# ============================================================================================
# Formatos das colunas
# ============================================================================================
def _palavras(nome: str) -> str:
    t = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode().lower()
    return t.replace("_", " ")


def formatos(colunas: list[str], linhas: list) -> list[str]:
    """Um formato por coluna: reais, numero, inteiro, codigo, percentual, data, data_hora, logico ou texto."""
    saida = []
    for j, nome in enumerate(colunas):
        valores = [ln[j] for ln in linhas if ln[j] is not None]
        tipos = {type(v) for v in valores}
        nome = _palavras(nome)
        if not valores:
            saida.append("texto")
        elif tipos <= {bool}:
            saida.append("logico")
        elif tipos <= {dt.date, dt.datetime}:
            saida.append("data_hora" if any(isinstance(v, dt.datetime) and v.time() != dt.time() for v in valores)
                         else "data")
        elif all(isinstance(v, (int, float, decimal.Decimal)) and not isinstance(v, bool) for v in valores):
            if _PERCENTUAL.search(nome):
                saida.append("percentual")
            elif _REAIS.search(nome):
                saida.append("reais")
            elif all(isinstance(v, int) for v in valores):
                saida.append("codigo" if set(nome.replace("(", " ").replace(")", " ").split()) & _CODIGO else "inteiro")
            else:
                saida.append("numero")
        else:
            saida.append("texto")
    return saida


def _br(numero: float, casas: int) -> str:
    return f"{numero:,.{casas}f}".replace(",", "#").replace(".", ",").replace("#", ".")


def texto(valor, formato: str) -> str:
    """O valor como aparece no PDF (formato brasileiro)."""
    if valor is None:
        return ""
    if formato in NUMERICOS and isinstance(valor, (int, float, decimal.Decimal)) and not isinstance(valor, bool):
        x = float(valor)
        if not math.isfinite(x):
            return ""
        if formato == "reais":
            return ("-" if x < 0 else "") + "R$ " + _br(abs(x), 2)
        if formato == "percentual":
            return _br(x, 1) + "%"
        if formato == "codigo":
            return str(int(x))
        return _br(x, 0 if formato == "inteiro" else 2)
    if isinstance(valor, dt.datetime):
        return valor.strftime("%d/%m/%Y %H:%M" if formato == "data_hora" else "%d/%m/%Y")
    if isinstance(valor, dt.date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    return str(valor)


def nome_arquivo(titulo: str, formato: str, data: dt.date) -> str:
    """Nome do arquivo baixado: o título (sem os caracteres que o Windows não aceita) e a data."""
    base = " ".join(re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(titulo)).split()).strip(" .")[:80]
    return f"{base or 'Assistente'} - {data:%Y-%m-%d}{TIPOS[formato][0]}"


# ============================================================================================
# Excel
# ============================================================================================
def excel(titulo: str, descricao: str, info: str, colunas: list[str], linhas: list) -> bytes:
    xlsxwriter = _importar(EXCEL)
    fmts = formatos(colunas, linhas)
    saida = io.BytesIO()
    wb = xlsxwriter.Workbook(saida, {"constant_memory": True, "remove_timezone": True})
    wb.set_properties({"title": titulo, "comments": descricao, "author": "Painel Mais Vida"})
    ws = wb.add_worksheet("Dados")
    estilo = {
        "titulo": wb.add_format({"bold": True, "font_size": 14, "font_color": "#002E5D"}),
        "info": wb.add_format({"font_color": "#5A6B80"}),
        "cabecalho": wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#002E5D", "text_wrap": True,
                                    "valign": "vcenter", "border": 1, "border_color": "#002E5D"}),
        **{k: wb.add_format({"num_format": v}) for k, v in NUM_EXCEL.items()},
    }
    ws.write_string(0, 0, titulo, estilo["titulo"])
    n = 1
    for t in (descricao, info):
        if t:
            ws.write_string(n, 0, t, estilo["info"])
            n += 1
    cab = n + 1
    for j, nome in enumerate(colunas):
        ws.write_string(cab, j, str(nome), estilo["cabecalho"])
    for i, ln in enumerate(linhas, cab + 1):
        for j, (valor, f) in enumerate(zip(ln, fmts)):
            _celula(ws, i, j, valor, f, estilo)
    if colunas:
        ws.autofilter(cab, 0, cab + max(len(linhas), 1), len(colunas) - 1)
        ws.freeze_panes(cab + 1, 0)
    for j, largura in enumerate(_larguras_excel(colunas, linhas, fmts)):
        ws.set_column(j, j, largura)
    wb.close()
    return saida.getvalue()


def _celula(ws, i: int, j: int, valor, formato: str, estilo: dict) -> None:
    # Texto sempre como texto: um nome que comece com "=" não vira fórmula.
    if valor is None:
        return
    if formato in ("data", "data_hora") and isinstance(valor, dt.date):
        ws.write_datetime(i, j, valor, estilo[formato])
    elif formato in NUMERICOS and isinstance(valor, (int, float, decimal.Decimal)) and not isinstance(valor, bool):
        if math.isfinite(float(valor)):
            ws.write_number(i, j, float(valor), estilo[formato])
    else:
        ws.write_string(i, j, texto(valor, formato))


def _larguras_excel(colunas, linhas, fmts) -> list[float]:
    larguras = []
    for j, nome in enumerate(colunas):
        maior = max((len(texto(ln[j], fmts[j])) for ln in linhas[:1000]), default=0)
        larguras.append(min(max(maior, len(str(nome)), 6) + 2, 60))
    return larguras


# ============================================================================================
# PDF
# ============================================================================================
# As fontes padrão do PDF só têm os caracteres do Windows-1252: o resto vira o equivalente (ou some).
_TROCAS = str.maketrans({"−": "-", "≈": "~", "≥": ">=", "≤": "<=", "→": "->", "←": "<-", "✓": "v", "✔": "v",
                         " ": " ", " ": " ", " ": " "})


def _pdf(s) -> str:
    return str(s).translate(_TROCAS).encode("cp1252", "ignore").decode("cp1252")


def pdf(titulo: str, descricao: str, info: str, resposta: str, colunas: list[str], linhas: list) -> bytes:
    fpdf = _importar(PDF)

    class Documento(fpdf.FPDF):
        def footer(self):
            self.set_y(-10)
            self.set_font("helvetica", size=7.5)
            self.set_text_color(*CINZA)
            self.cell(0, 5, _pdf(f"Painel Mais Vida · {titulo}")[:110], align="L")
            self.set_x(self.l_margin)
            self.cell(0, 5, f"Página {self.page_no()} de {{nb}}", align="R")

    doc = Documento(unit="mm", format="A4")
    doc.core_fonts_encoding = "windows-1252"
    doc.set_margins(12, 12, 12)
    doc.set_auto_page_break(True, margin=14)
    doc.set_title(titulo)
    doc.set_author("Painel Mais Vida")
    doc.set_creator("Painel Mais Vida")

    fmts = formatos(colunas, linhas)
    cabecalho = [_pdf(c) for c in colunas]
    corpo = [[_pdf(texto(v, f)) for v, f in zip(ln, fmts)] for ln in linhas]
    tamanho = 8 if len(colunas) <= 8 else 7 if len(colunas) <= 12 else 6
    larguras = _larguras_pdf(doc, cabecalho, corpo, tamanho)
    doc.add_page(orientation="L" if sum(larguras) > 210 - 24 else "P")

    doc.set_font("helvetica", "B", 8)
    doc.set_text_color(*LARANJA)
    doc.cell(0, 4, "PAINEL MAIS VIDA", new_x="LMARGIN", new_y="NEXT")
    doc.set_font("helvetica", "B", 16)
    doc.set_text_color(*MARINHO)
    doc.multi_cell(0, 7.5, _pdf(titulo), align="L", new_x="LMARGIN", new_y="NEXT")
    if descricao:
        doc.set_font("helvetica", size=10)
        doc.set_text_color(*TINTA)
        doc.multi_cell(0, 5, _pdf(descricao), align="L", new_x="LMARGIN", new_y="NEXT")
    if info:
        doc.set_font("helvetica", size=8)
        doc.set_text_color(*CINZA)
        doc.multi_cell(0, 4.5, _pdf(info), align="L", new_x="LMARGIN", new_y="NEXT")
    doc.ln(2)
    doc.set_draw_color(*LINHA)
    doc.line(doc.l_margin, doc.get_y(), doc.w - doc.r_margin, doc.get_y())
    doc.ln(4)

    if (resposta or "").strip():
        _markdown(doc, resposta)
        doc.ln(3)
        doc.set_font("helvetica", "B", 10)
        doc.set_text_color(*MARINHO)
        doc.cell(0, 6, "Dados", new_x="LMARGIN", new_y="NEXT")
        doc.ln(1)
    if corpo:
        alinhar = tuple("RIGHT" if f in NUMERICOS else "LEFT" for f in fmts)
        _tabela(doc, cabecalho, corpo, alinhar, tamanho, larguras)
    else:
        doc.set_font("helvetica", size=10)
        doc.set_text_color(*TINTA)
        doc.cell(0, 6, "Nenhuma linha encontrada.", new_x="LMARGIN", new_y="NEXT")
    return bytes(doc.output())


def _larguras_pdf(doc, cabecalho, corpo, tamanho) -> list[float]:
    """Largura natural de cada coluna (mm): o maior conteúdo das primeiras linhas; o cabeçalho quebra em linhas."""
    doc.set_font("helvetica", "B", tamanho)
    cab = [doc.get_string_width(c) for c in cabecalho]
    doc.set_font("helvetica", "", tamanho)
    larguras = []
    for j in range(len(cabecalho)):
        conteudo = max((doc.get_string_width(ln[j]) for ln in corpo[:300] if j < len(ln)), default=0)
        larguras.append(min(max(conteudo, min(cab[j], 28), 8), 70) + 4)
    return larguras


def _quebrar(doc, texto: str, largura: float, max_linhas: int = 6) -> list[str]:
    """As linhas de uma célula, quebrando nos espaços (e no meio da palavra que não cabe sozinha)."""
    if doc.get_string_width(texto) <= largura:
        return [texto]
    linhas, atual = [], ""
    for palavra in texto.split(" "):
        tentativa = f"{atual} {palavra}" if atual else palavra
        if doc.get_string_width(tentativa) <= largura:
            atual = tentativa
            continue
        if atual:
            linhas.append(atual)
        while len(palavra) > 1 and doc.get_string_width(palavra) > largura:
            k = len(palavra) - 1
            while k > 1 and doc.get_string_width(palavra[:k]) > largura:
                k -= 1
            linhas.append(palavra[:k])
            palavra = palavra[k:]
        atual = palavra
    linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        linhas[-1] = linhas[-1][:-1] + "…"
    return linhas


def _tabela(doc, cabecalho, corpo, alinhar, tamanho, larguras=None) -> None:
    """Tabela desenhada direto (a do fpdf2 mede cada célula duas vezes e leva segundos em milhares de linhas): cabeçalho
    repetido em cada página, linhas zebradas e o texto quebrado dentro da coluna."""
    larguras = larguras or _larguras_pdf(doc, cabecalho, corpo, tamanho)
    if sum(larguras) > doc.epw:
        larguras = [w * doc.epw / sum(larguras) for w in larguras]
    altura, folga = tamanho * 0.42, 1.2  # mm por linha de texto; espaço em volta do texto

    def linha(celulas, negrito: bool, fundo) -> None:
        doc.set_font("helvetica", "B" if negrito else "", tamanho)
        partes = [_quebrar(doc, c, w - 2 * folga) for c, w in zip(celulas, larguras)]
        h = max(len(p) for p in partes) * altura + 2 * folga
        if doc.get_y() + h > doc.page_break_trigger and not negrito:
            doc.add_page(same=True)
            linha(cabecalho, True, MARINHO)
            doc.set_font("helvetica", "", tamanho)
        x, y = doc.l_margin, doc.get_y()
        if fundo:
            doc.set_fill_color(*fundo)
            doc.rect(x, y, sum(larguras), h, style="F")
        doc.set_text_color(*((255, 255, 255) if negrito else TINTA))
        for p, w, a in zip(partes, larguras, alinhar):
            for k, t in enumerate(p):
                dx = w - folga - doc.get_string_width(t) if a == "RIGHT" else folga
                doc.text(x + dx, y + folga + altura * (k + 0.78), t)
            x += w
        doc.set_draw_color(*LINHA)
        doc.line(doc.l_margin, y + h, doc.l_margin + sum(larguras), y + h)
        doc.set_y(y + h)

    if doc.get_y() + 3 * altura + 4 * folga > doc.page_break_trigger:  # o cabeçalho não fica sozinho no pé da página
        doc.add_page(same=True)
    linha(cabecalho, True, MARINHO)
    for i, ln in enumerate(corpo):
        linha([ln[j] if j < len(ln) else "" for j in range(len(cabecalho))], False, ZEBRA if i % 2 else None)
    doc.set_text_color(*TINTA)


# Markdown da resposta: o mesmo subconjunto que a página desenha (web/js/assistente.js): negrito, títulos, listas e
# tabelas com |; itálico e código viram texto simples.
_TABELA = re.compile(r"^\s*\|.*\|\s*$")
_SEPARADOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_ITEM = re.compile(r"^\s*[-*•]\s+")
_NUMERADO = re.compile(r"^\s*(\d+)[.)]\s+")
_TITULO = re.compile(r"^\s*#{1,4}\s+")
_ITALICO = re.compile(r"(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)")
_NUMERO = re.compile(r"^[−-]?\s*(R\$\s*)?[−-]?[\d.,]+\s*(%|mi|mil|kg|un)?$", re.I)  # alinha à direita


def _partes(linha: str) -> list[str]:
    return [c.strip().replace("**", "") for c in linha.strip().strip("|").split("|")]


def _escrever(doc, linha: str, tamanho: float = 10, altura: float = 5, negrito: bool = False) -> None:
    """Uma linha com **negrito**, quebrando sozinha no fim da página."""
    linha = _ITALICO.sub(r"\1\2", linha).replace("`", "")
    for k, parte in enumerate(linha.split("**")):
        if parte:
            doc.set_font("helvetica", "B" if negrito or k % 2 else "", tamanho)
            doc.write(altura, _pdf(parte))
    doc.ln(altura)


def _markdown(doc, resposta: str) -> None:
    linhas = resposta.replace("\r", "").split("\n")
    margem = doc.l_margin
    i = 0
    while i < len(linhas):
        ln = linhas[i]
        doc.set_text_color(*TINTA)
        if _TABELA.match(ln) and i + 1 < len(linhas) and _SEPARADOR.match(linhas[i + 1]):
            cab = _partes(ln)
            i += 2
            corpo = []
            while i < len(linhas) and _TABELA.match(linhas[i]):
                corpo.append(_partes(linhas[i]))
                i += 1
            alinhar = tuple("RIGHT" if corpo and all(_NUMERO.match(r[j]) for r in corpo if j < len(r) and r[j])
                            and any(j < len(r) and r[j] for r in corpo) else "LEFT" for j in range(len(cab)))
            doc.ln(1)
            _tabela(doc, [_pdf(c) for c in cab], [[_pdf(c) for c in r] for r in corpo], alinhar, 8)
            doc.ln(3)
            continue
        if _TITULO.match(ln):
            doc.ln(1.5)
            doc.set_text_color(*MARINHO)
            _escrever(doc, _TITULO.sub("", ln), 11, 6, negrito=True)
        elif _ITEM.match(ln) or _NUMERADO.match(ln):
            m = _NUMERADO.match(ln)
            marca = f"{m.group(1)}." if m else "•"
            doc.set_font("helvetica", "", 10)
            doc.set_x(margem + 1.5)
            doc.cell(5.5, 5, marca)
            doc.set_left_margin(margem + 7)
            _escrever(doc, (_NUMERADO if m else _ITEM).sub("", ln))
            doc.set_left_margin(margem)
        elif ln.strip():
            _escrever(doc, ln.strip())
        else:
            doc.ln(2)
        i += 1

"""O Parecer de Devoluções em PDF (fpdf2), no formato do documento que era montado à mão a partir das planilhas do ERP:
- capa com a competência e o vendedor ou a região;
- cada região numa página nova (BA, ES, Terceirizados), com o bloco de cada vendedor: cliente ausente, erro de lançamento
  (o nº de erros em vermelho), recusa, vencido (por produto e, no fim, os clientes em alerta), danificado e os tipos
  adicionais;
- os rankings por tipo de devolução numa página nova, no fim.
Cores do Parecer: títulos em laranja #FF9D1D; subtítulos e cabeçalho das tabelas em azul #004AAD; linhas de total em
verde claro #E2EFDA; clientes em alerta em laranja claro #FCE4D6. Helvetica (a mesma métrica da Arial). Os dados vêm
prontos de bi/devolucoes.py (Devolucoes._parecer).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .arquivos import PDF, _br, _importar, _pdf, _quebrar

LARANJA, AZUL, PRETO, BRANCO = (255, 157, 29), (0, 74, 173), (0, 0, 0), (255, 255, 255)
VERMELHO, CINZA, BORDA = (200, 0, 0), (110, 110, 110), (190, 198, 210)
VERDE_CLARO, LARANJA_CLARO = (226, 239, 218), (252, 228, 214)
LOGO = Path(__file__).resolve().parent.parent / "web" / "img" / "logo-maisvida.png"
TAMANHO = 9  # pontos, nas tabelas
TIPO, TIPO_ZIP = "application/pdf", "application/zip"
# Colunas (largura em mm, numa página A4 em pé com margens de 15 mm: 180 mm úteis) e alinhamento (L, R ou C).
SIMPLES = (["Cliente", "Qtd", "Valor (R$)"], (120, 25, 35), "LRR")
PRODUTO = (["Cliente", "Qtd", "Valor (R$)", "Fat. Bruto (R$)", "% Devol."], (85, 18, 25, 30, 22), "LRRRR")
ALERTA = (["Cliente", "Volume", "Valor (R$)", "Fat. Bruto (R$)", "% Devol."], (85, 18, 25, 30, 22), "LRRRR")
RANK_ERROS = (["#", "Vendedor", "Região", "Erros", "Volume", "Valor (R$)"], (10, 66, 30, 16, 26, 32), "CLLRRR")
RANK_VENDEDOR = (["#", "Vendedor", "Região", "Volume", "Valor (R$)"], (10, 82, 32, 26, 30), "CLLRR")
RANK_CLIENTE = (["#", "Cliente", "Vendedor", "Volume", "Valor (R$)"], (10, 88, 42, 18, 22), "CLLRR")


def qtd(v: float | None) -> str:
    """80 -> '80'; 33,56 -> '33,56' (como no Parecer: número inteiro sem casas)."""
    if v is None:
        return "—"
    return _br(v, 0) if abs(v - round(v)) < 0.005 else _br(v, 2)


def moeda(v: float | None) -> str:
    return "—" if v is None else _br(v, 2)


def pct(v: float | None) -> str:
    return "—" if v is None else _br(v * 100, 2) + "%"


def documento(competencia: str, capa: str | None, regioes: list[dict], rankings: list[dict]) -> bytes:
    """O PDF: a capa (capa = "Vendedor: …" ou "Região …"; None no documento geral), as regiões e os rankings."""
    fpdf = _importar(PDF)

    class Documento(fpdf.FPDF):
        def footer(self):
            if self.page_no() == 1:  # a capa fica limpa
                return
            self.set_y(-12)
            self.set_font("helvetica", size=7.5)
            self.set_text_color(*CINZA)
            self.cell(0, 5, _pdf(f"Parecer de Devoluções · Competência: {competencia}"), align="L")
            self.set_x(self.l_margin)
            self.cell(0, 5, f"Página {self.page_no()} de {{nb}}", align="R")

    doc = Documento(unit="mm", format="A4")
    doc.core_fonts_encoding = "windows-1252"
    doc.set_margins(15, 15, 15)
    doc.set_auto_page_break(True, margin=16)
    doc.set_title(_pdf(f"Parecer de Devoluções - {competencia}"))
    doc.set_author("Painel Mais Vida")
    doc.set_creator("Painel Mais Vida")
    _capa(doc, competencia, capa)
    for r in regioes:
        doc.add_page()
        _texto(doc, r["titulo"], 16, LARANJA, negrito=True, depois=3)
        for v in r["vendedores"]:
            _vendedor(doc, v)
    if rankings:
        doc.add_page()
        _texto(doc, "RANKINGS POR TIPO DE DEVOLUÇÃO", 16, LARANJA, negrito=True, depois=2)
        for rk in rankings:
            _ranking(doc, rk)
    return bytes(doc.output())


def zip_arquivos(arquivos: list[tuple[str, bytes]]) -> bytes:
    """[(caminho dentro do zip, conteúdo)] -> o zip (os nomes com acento vão em UTF-8)."""
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, corpo in arquivos:
            z.writestr(nome, corpo)
    return saida.getvalue()


# --- partes do documento -----------------------------------------------------------------------
def _texto(doc, texto: str, tamanho: float, cor, negrito: bool = False, antes: float = 0, depois: float = 1.5,
           alinhar: str = "L") -> None:
    if antes:
        doc.ln(antes)
    doc.set_font("helvetica", "B" if negrito else "", tamanho)
    doc.set_text_color(*cor)
    doc.multi_cell(0, tamanho * 0.5, _pdf(texto), align=alinhar, new_x="LMARGIN", new_y="NEXT")
    if depois:
        doc.ln(depois)


def _garantir(doc, altura: float) -> None:
    """O título não fica sozinho no pé da página: sem espaço para ele, o cabeçalho e uma linha, vai para a próxima."""
    if doc.get_y() + altura > doc.page_break_trigger:
        doc.add_page()


def _capa(doc, competencia: str, capa: str | None) -> None:
    doc.add_page()
    if LOGO.exists():
        try:
            doc.image(str(LOGO), x=(doc.w - 60) / 2, y=45, w=60)
        except Exception:  # noqa: BLE001 — sem o logo, a capa sai só com o texto
            pass
    doc.set_y(105)
    _texto(doc, "PARECER DE DEVOLUÇÕES", 26, LARANJA, negrito=True, alinhar="C", depois=6)
    _texto(doc, f"Competência: {competencia}", 14, PRETO, alinhar="C", depois=3)
    if capa:
        _texto(doc, capa, 13, PRETO, negrito=True, alinhar="C", depois=3)
    _texto(doc, "Análise por vendedor, produto e tipo de devolução", 11, CINZA, alinhar="C")


def _vendedor(doc, v: dict) -> None:
    _garantir(doc, 42)
    _texto(doc, f"Vendedor: {v['nome']}", 13, LARANJA, negrito=True, antes=3, depois=1.5)
    for s in v["secoes"]:
        _garantir(doc, 32)
        _texto(doc, s["titulo"], 11, AZUL, negrito=True, antes=1, depois=1)
        if s["tipo"] == "simples":
            if s["chave"] == "lancamento":
                _texto(doc, f"Erros de lançamento cometidos no mês: {s['erros']}", 10, VERMELHO, negrito=True, depois=1)
            linhas = [([r["cliente"], qtd(r["qtd"]), moeda(r["valor"])], None) for r in s["linhas"]]
            linhas.append((["TOTAL", qtd(s["total"]["qtd"]), moeda(s["total"]["valor"])], "total"))
            _tabela(doc, *SIMPLES, linhas)
            continue
        for p in s["produtos"]:
            _garantir(doc, 26)
            _texto(doc, p["nome"], 10, AZUL, negrito=True, depois=0.8)
            linhas = [([r["cliente"], qtd(r["qtd"]), moeda(r["valor"]), moeda(r["fat"]), pct(r["pct"])], None)
                      for r in p["linhas"]]
            linhas.append((["Total do produto", qtd(p["total"]["qtd"]), moeda(p["total"]["valor"]), "—", "—"], "total"))
            _tabela(doc, *PRODUTO, linhas)
        if s.get("alerta"):
            _garantir(doc, 26)
            _texto(doc, "Clientes em Alerta (Vencimento)", 10, AZUL, negrito=True, depois=0.8)
            _tabela(doc, *ALERTA, [([r["cliente"], qtd(r["volume"]), moeda(r["valor"]), moeda(r["fat"]), pct(r["pct"])],
                                    "alerta") for r in s["alerta"]])


def _ranking(doc, rk: dict) -> None:
    _garantir(doc, 30)
    _texto(doc, rk["titulo"], 11, AZUL, negrito=True, antes=2, depois=1)
    if rk["por"] == "cliente":
        linhas = [([str(k), r["cliente"], r["vendedor"], qtd(r["volume"]), moeda(r["valor"])], None)
                  for k, r in enumerate(rk["linhas"], 1)]
        _tabela(doc, *RANK_CLIENTE, linhas)
    elif rk["erros"]:
        linhas = [([str(k), r["vendedor"], r["regiao"], str(r["erros"]), qtd(r["volume"]), moeda(r["valor"])], None)
                  for k, r in enumerate(rk["linhas"], 1)]
        _tabela(doc, *RANK_ERROS, linhas)
    else:
        linhas = [([str(k), r["vendedor"], r["regiao"], qtd(r["volume"]), moeda(r["valor"])], None)
                  for k, r in enumerate(rk["linhas"], 1)]
        _tabela(doc, *RANK_VENDEDOR, linhas)


def _tabela(doc, cabecalho: list[str], larguras: tuple, alinhar: str, linhas: list[tuple[list[str], str | None]],
            tamanho: float = TAMANHO) -> None:
    """Tabela com grade: cabeçalho azul (repetido quando a tabela passa de página), linhas de total em verde claro e de
    alerta em laranja claro. O texto quebra dentro da coluna."""
    altura, folga = tamanho * 0.42, 1.3  # mm por linha de texto; espaço em volta do texto

    def desenhar(celulas: list[str], estilo: str | None) -> None:
        negrito = estilo in ("cab", "total")
        doc.set_font("helvetica", "B" if negrito else "", tamanho)
        partes = [_quebrar(doc, _pdf(c), w - 2 * folga) for c, w in zip(celulas, larguras)]
        h = max(len(p) for p in partes) * altura + 2 * folga
        if estilo != "cab" and doc.get_y() + h > doc.page_break_trigger:
            doc.add_page()
            desenhar(cabecalho, "cab")
            doc.set_font("helvetica", "B" if negrito else "", tamanho)
        x, y = doc.l_margin, doc.get_y()
        fundo = {"cab": AZUL, "total": VERDE_CLARO, "alerta": LARANJA_CLARO}.get(estilo)
        if fundo:
            doc.set_fill_color(*fundo)
            doc.rect(x, y, sum(larguras), h, style="F")
        doc.set_text_color(*(BRANCO if estilo == "cab" else PRETO))
        doc.set_draw_color(*BORDA)
        doc.set_line_width(0.2)
        for p, w, a in zip(partes, larguras, alinhar):
            for k, t in enumerate(p):
                lt = doc.get_string_width(t)
                dx = w - folga - lt if a == "R" else (w - lt) / 2 if a == "C" else folga
                doc.text(x + dx, y + folga + altura * (k + 0.78), t)
            doc.line(x, y, x, y + h)
            x += w
        doc.line(x, y, x, y + h)
        doc.line(doc.l_margin, y, x, y)
        doc.line(doc.l_margin, y + h, x, y + h)
        doc.set_y(y + h)

    desenhar(cabecalho, "cab")
    for celulas, estilo in linhas:
        desenhar(celulas, estilo)
    doc.ln(3)

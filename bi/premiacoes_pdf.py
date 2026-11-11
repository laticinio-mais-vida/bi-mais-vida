"""A tabela de cada aba da página Premiações em PDF (fpdf2), em A4 deitado:
- Vendedores: a tabela da premiação (a mesma que vira imagem para o WhatsApp), com as faixas no cabeçalho;
- Supervisores: a tabela dos indicadores de cada quadro, com as parcelas e o valor a receber;
- Comissão: a tabela da comissão de cada vendedor, com os totais por estado no cabeçalho.
Só as tabelas (decisão do usuário): sem a conta passo a passo dos supervisores, as listas de clientes ou o detalhe por
produto da comissão. As observações da página vão no fim. Os dados vêm prontos de bi/premiacoes.py
(Premiacoes.calcular), já com o acesso de quem baixa; o PDF não mostra códigos internos do ERP, só nomes.
"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

from .arquivos import PDF, _br, _importar, _pdf, _quebrar

# As cores do painel (as mesmas do PDF do Assistente, bi/arquivos.py).
MARINHO, LARANJA, TINTA, CINZA = (0, 46, 93), (245, 130, 32), (35, 45, 60), (100, 112, 130)
LINHA, ZEBRA, TOTAL, BRANCO = (215, 222, 230), (244, 246, 249), (226, 232, 240), (255, 255, 255)
LOGO = Path(__file__).resolve().parent.parent / "web" / "img" / "logo-maisvida.png"
TIPO = "application/pdf"
TAMANHO = 8.5  # pontos, nas tabelas
TITULOS = {"vendedores": "Premiação dos vendedores", "supervisores": "Premiação dos supervisores",
           "comissao": "Comissão dos vendedores"}
SEMANA = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
# Colunas: (título, largura em mm, alinhamento L, R ou C). A4 deitado com margens de 12 mm: 273 mm úteis.
COL_VENDEDORES = [("Vendedor", 70, "L"), ("Estado", 16, "C"), ("Meta clientes", 26, "R"), ("Atendidos", 24, "R"),
                  ("% da meta", 24, "R"), ("Faixa", 18, "C"), ("Prêmio", 30, "R"), ("Próxima faixa", 65, "L")]
COL_SUPERVISOR = [("Indicador", 92, "L"), ("Realizado", 36, "R"), ("Meta", 40, "R"), ("Alcance", 36, "R"),
                  ("Faixa", 30, "C"), ("Parcela", 39, "R")]
COL_COMISSAO = [("Vendedor", 58, "L"), ("Estado", 14, "C"), ("Vendido", 28, "R"), ("Comissão das vendas", 28, "R"),
                ("% médio", 18, "R"), ("Devolvido", 26, "R"), ("- Comissão", 22, "R"), ("Brindes", 24, "R"),
                ("- Comissão", 22, "R"), ("A pagar", 33, "R")]


# --- formatos (os mesmos da página: web/js/util.js fmt) --------------------------------------------
def moeda(v: float | None, casas: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return ("-" if v < -0.004 else "") + "R$ " + _br(abs(v), casas)


def num(v: float | None) -> str:
    return "—" if v is None else _br(v, 0)


def pct(v: float | None, casas: int = 1) -> str:
    return "—" if v is None else _br(v * 100, casas) + "%"


def pct_faixa(v: float) -> str:
    """91% sem casa decimal; 92,5% com uma."""
    return pct(v, 0 if abs(v * 100 - round(v * 100)) < 1e-6 else 1)


def pct_baixo(v: float | None) -> str:
    """O alcance arredondado para baixo, como na página: 89,96% aparece como 89,9%."""
    return "—" if v is None else pct(math.floor(v * 1000 + 1e-6) / 1000)


def mes_titulo(d: dict) -> str:
    r = d["mes"]["rotulo"]
    return r[:1].upper() + r[1:]


def nome_arquivo(d: dict) -> str:
    return f"{TITULOS[d['aba']]} - {mes_titulo(d)}.pdf"


def _plural(n: int, um: str, varios: str) -> str:
    return f"{num(n)} {um if n == 1 else varios}"


def _em_lista(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else f"{', '.join(itens[:-1])} e {itens[-1]}" if itens else ""


# --- o documento ---------------------------------------------------------------------------------
def documento(d: dict) -> bytes:
    """O PDF da aba de d (a resposta de Premiacoes.calcular)."""
    fpdf = _importar(PDF)
    titulo = f"{TITULOS[d['aba']]} · {mes_titulo(d)}"
    gerado = dt.datetime.now()

    class Documento(fpdf.FPDF):
        def footer(self):
            self.set_y(-10)
            self.set_font("helvetica", size=7.5)
            self.set_text_color(*CINZA)
            self.cell(0, 5, _pdf(f"Painel Mais Vida · {titulo} · gerado em {gerado:%d/%m/%Y} às {gerado:%H:%M}"),
                      align="L")
            self.set_x(self.l_margin)
            self.cell(0, 5, f"Página {self.page_no()} de {{nb}}", align="R")

    doc = Documento(orientation="L", unit="mm", format="A4")
    doc.core_fonts_encoding = "windows-1252"
    doc.set_margins(12, 12, 12)
    doc.set_auto_page_break(True, margin=14)
    doc.set_title(_pdf(titulo))
    doc.set_author("Painel Mais Vida")
    doc.set_creator("Painel Mais Vida")
    doc.add_page()
    {"vendedores": _vendedores, "supervisores": _supervisores, "comissao": _comissao}[d["aba"]](doc, d)
    _observacoes(doc, d.get("avisos") or [])
    return bytes(doc.output())


def _situacao(d: dict) -> str:
    ref = dt.date.fromisoformat(d["data_ref"])
    estado = "Mês fechado" if d["situacao"] == "final" else "Prevista (mês em andamento)"
    return f"{estado} · dados até {SEMANA[ref.weekday()]}, {ref:%d/%m/%Y}"


def _cabecalho(doc, titulo: str, linhas: list[str], direita: list[str]) -> None:
    """O logo, o título com as linhas de baixo e, à direita, a legenda (faixas, regras)."""
    y = doc.get_y()
    x = doc.l_margin
    if LOGO.exists():
        try:
            doc.image(str(LOGO), x=x, y=y, h=11)
            x += 33
        except Exception:  # noqa: BLE001 — sem o logo, o cabeçalho sai só com o texto
            pass
    largura_direita = 88 if direita else 0
    largura = doc.w - doc.r_margin - x - largura_direita - 4
    doc.set_xy(x, y)
    doc.set_font("helvetica", "B", 15)
    doc.set_text_color(*MARINHO)
    doc.multi_cell(largura, 7, _pdf(titulo), align="L", new_x="LEFT", new_y="NEXT")
    doc.set_font("helvetica", size=9)
    doc.set_text_color(*CINZA)
    for t in linhas:
        doc.multi_cell(largura, 4.6, _pdf(t), align="L", new_x="LEFT", new_y="NEXT")
    fim = doc.get_y()
    if direita:
        doc.set_xy(doc.w - doc.r_margin - largura_direita, y)
        doc.set_font("helvetica", size=8.5)
        doc.set_text_color(*TINTA)
        for t in direita:
            doc.multi_cell(largura_direita, 4.4, _pdf(t), align="R", new_x="LEFT", new_y="NEXT")
        fim = max(fim, doc.get_y())
    doc.set_y(max(fim, y + 12) + 3)
    doc.set_draw_color(*LARANJA)
    doc.set_line_width(0.6)
    doc.line(doc.l_margin, doc.get_y(), doc.w - doc.r_margin, doc.get_y())
    doc.set_line_width(0.2)
    doc.ln(4)


def _vazio(doc, texto: str) -> None:
    doc.set_font("helvetica", size=11)
    doc.set_text_color(*TINTA)
    doc.multi_cell(0, 6, _pdf(texto), align="L", new_x="LMARGIN", new_y="NEXT")


def _observacoes(doc, avisos: list[str]) -> None:
    if not avisos:
        return
    if doc.get_y() + 14 > doc.page_break_trigger:
        doc.add_page()
    doc.ln(3)
    doc.set_font("helvetica", "B", 8.5)
    doc.set_text_color(*TINTA)
    doc.cell(0, 5, "Observações", new_x="LMARGIN", new_y="NEXT")
    doc.set_font("helvetica", size=8)
    doc.set_text_color(*CINZA)
    for a in avisos:
        doc.multi_cell(0, 4.2, _pdf(f"• {a}"), align="L", new_x="LMARGIN", new_y="NEXT")


def _tabela(doc, colunas: list[tuple[str, float, str]], linhas: list[list[str]], rodape: list[list[str]] = (),
            tamanho: float = TAMANHO) -> None:
    """Tabela desenhada direto, como a do PDF do Assistente: cabeçalho azul-marinho repetido em cada página, linhas
    zebradas e o rodapé (totais) em negrito. Uma célula pode ter mais de uma linha (\\n) e quebra dentro da coluna."""
    larguras = [w for _, w, _ in colunas]
    alinhar = [a for _, _, a in colunas]
    altura, folga = tamanho * 0.42, 1.3  # mm por linha de texto; espaço em volta do texto

    def partes(celulas: list[str]) -> list[list[str]]:
        saida = []
        for c, w in zip(celulas, larguras):
            p = []
            for trecho in _pdf(c).split("\n"):
                p += _quebrar(doc, trecho, w - 2 * folga)
            saida.append(p)
        return saida

    def linha(celulas: list[str], estilo: str, k: int = 0) -> None:
        negrito = estilo in ("cab", "total")
        doc.set_font("helvetica", "B" if negrito else "", tamanho)
        p = partes(celulas)
        h = max(len(x) for x in p) * altura + 2 * folga
        if estilo != "cab" and doc.get_y() + h > doc.page_break_trigger:
            doc.add_page()
            linha([t for t, _, _ in colunas], "cab")
            doc.set_font("helvetica", "B" if negrito else "", tamanho)
        x, y = doc.l_margin, doc.get_y()
        fundo = MARINHO if estilo == "cab" else TOTAL if estilo == "total" else ZEBRA if k % 2 else None
        if fundo:
            doc.set_fill_color(*fundo)
            doc.rect(x, y, sum(larguras), h, style="F")
        doc.set_text_color(*(BRANCO if estilo == "cab" else TINTA))
        for textos, w, a in zip(p, larguras, alinhar):
            for j, t in enumerate(textos):
                lt = doc.get_string_width(t)
                dx = w - folga - lt if a == "R" else (w - lt) / 2 if a == "C" else folga
                doc.text(x + dx, y + folga + altura * (j + 0.78), t)
            x += w
        doc.set_draw_color(*LINHA)
        doc.line(doc.l_margin, y + h, doc.l_margin + sum(larguras), y + h)
        doc.set_y(y + h)

    if doc.get_y() + 4 * altura + 4 * folga > doc.page_break_trigger:  # o cabeçalho não fica sozinho no pé da página
        doc.add_page()
    linha([t for t, _, _ in colunas], "cab")
    for k, celulas in enumerate(linhas):
        linha(celulas, "linha", k)
    for celulas in rodape:
        linha(celulas, "total")
    doc.set_text_color(*TINTA)


# --- vendedores ----------------------------------------------------------------------------------
def _vendedores(doc, d: dict) -> None:
    faixas = d["faixas"]
    _cabecalho(doc, f"Premiação dos vendedores · {mes_titulo(d)}",
               [_situacao(d), "Clientes atendidos no mês sobre a META CLIENTE (planilha de metas ou aprovada no "
                "painel). Vale a maior faixa atingida; elas não se somam."],
               ["Faixas"] + [f"a partir de {pct_faixa(f['min'])} da meta: {moeda(f['valor'])}" for f in faixas])
    if not d["vendedores"]:
        _vazio(doc, f"Nenhum vendedor do seu acesso tem meta de clientes em {d['mes']['rotulo']}.")
        return
    aprovadas = any(v["aprovada"] for v in d["vendedores"])
    linhas = []
    for v in d["vendedores"]:
        nome = v["nome"] + (" (Edir)" if v["equipe"] == "EDIR" and "edir" not in v["nome"].lower() else "")
        prox = v["proxima"]
        linhas.append([
            nome + (" *" if v["aprovada"] else ""), v["estado"], num(v["meta"]), num(v["atendidos"]), pct(v["pct"]),
            pct_faixa(v["faixa"]["min"]) if v["faixa"] else "—", moeda(v["premio"]) if v["premio"] else "—",
            (f"{'falta' if prox['faltam'] == 1 else 'faltam'} {_plural(prox['faltam'], 'cliente', 'clientes')} para "
             f"{moeda(prox['valor'])}" if prox else "faixa máxima"),
        ])
    t = d["total"]
    _tabela(doc, COL_VENDEDORES, linhas,
            [["Total", "", num(t["meta"]), num(t["atendidos"]), pct(t["pct"]), f"{t['premiados']} de {t['vendedores']}",
              moeda(t["premio"]), ""]])
    if aprovadas:
        doc.set_font("helvetica", size=8)
        doc.set_text_color(*CINZA)
        doc.ln(1.5)
        doc.cell(0, 4.5, "* meta aprovada no painel (substitui a da planilha)", new_x="LMARGIN", new_y="NEXT")


# --- supervisores --------------------------------------------------------------------------------
_FORMATO = {"faturamento": lambda v: moeda(v, 0), "mix": pct, "positivacao": num, "novos": num, "reativacao": num}


def _supervisores(doc, d: dict) -> None:
    _cabecalho(doc, f"Premiação dos supervisores · {mes_titulo(d)}",
               [_situacao(d), "Os números são da carteira de hoje de cada estado: os supervisores do mesmo estado usam "
                "os mesmos. Cada indicador paga um % da parcela pela faixa atingida."], [])
    for k, s in enumerate(d["supervisores"]):
        _supervisor(doc, s, primeiro=k == 0)


def _supervisor(doc, s: dict, primeiro: bool) -> None:
    linhas_tabela = len(s["indicadores"]) + 3
    if doc.get_y() + 12 + linhas_tabela * 9 > doc.page_break_trigger:  # o quadro inteiro numa página
        doc.add_page()
    elif not primeiro:
        doc.ln(5)
    fracao = s["premio"] / s["variavel"] if s["variavel"] else 0
    y = doc.get_y()
    doc.set_font("helvetica", "B", 12)
    doc.set_text_color(*MARINHO)
    doc.cell(0, 6, _pdf(f"{s['nome']} · {s['estado']}"), new_x="LMARGIN", new_y="NEXT")
    doc.set_font("helvetica", size=8.5)
    doc.set_text_color(*CINZA)
    doc.cell(0, 4.5, _pdf(f"Variável de {moeda(s['variavel'])}"), new_x="LMARGIN", new_y="NEXT")
    doc.set_xy(doc.l_margin, y)
    doc.set_font("helvetica", "B", 12)
    doc.set_text_color(*TINTA)
    doc.cell(0, 6, _pdf(f"A receber: {moeda(s['premio'])}"), align="R", new_x="LMARGIN", new_y="NEXT")
    doc.set_font("helvetica", size=8.5)
    doc.set_text_color(*CINZA)
    doc.cell(0, 4.5, _pdf(f"{pct(fracao)} do variável"), align="R", new_x="LMARGIN", new_y="NEXT")
    doc.ln(1.5)
    linhas = []
    for x in s["indicadores"]:
        f = _FORMATO[x["id"]]
        if x["sem_meta"]:
            meta = "sem meta"
        else:
            meta = f(x["meta"]) + (" (ajustada)" if x.get("ajustada") else "")
        sub = "sem peso: só move a trava e o bônus" if x["so_trava"] else \
            f"peso {pct_faixa(x['peso'])} · {moeda(x['referencia'])}"
        linhas.append([
            f"{x['titulo']}\n{sub}", f(x["realizado"]), meta, pct_baixo(x["alcance"]),
            "—" if x["so_trava"] else (pct_faixa(x["pct"]) if x["pct"] else "0%"),
            "—" if x["so_trava"] else moeda(x["parcela"]),
        ])
    extras = []
    if s.get("adicional") and s["adicional"]["pago"]:
        extras.append("com o prêmio da inadimplência")
    rotulo = "A receber (depois da trava, do bônus e do desconto pelo vencido" + \
        (f", {extras[0]}" if extras else "") + ")"
    _tabela(doc, COL_SUPERVISOR, linhas,
            [["Parcelas conquistadas", "", "", "", "", moeda(s["conquistado"])],
             [rotulo, "", "", "", "", moeda(s["premio"])]])


# --- comissão ------------------------------------------------------------------------------------
def _motivo_curto(nome: str) -> str:
    """"BRINDE - DANIFICADO NO CLIENTE" -> "danificado no cliente"."""
    s = str(nome or "")
    if s.upper().startswith("BRINDE"):
        s = s.split("-", 1)[-1]
    return " ".join(s.split()).lower()


def rotulo_brindes(motivos: list[dict]) -> str:
    """Os brindes que descontam, como na página: "danificados e vencidos" no padrão; com outros motivos, os nomes."""
    if not motivos:
        return "(nenhum motivo)"

    def tipo(nome: str) -> str:
        n = str(nome or "").upper()
        return ("outros" if not n.startswith("BRINDE") else "danificados" if "DANIFICADO" in n
                else "vencidos" if "VENCIDO" in n else "outros")

    tipos = list(dict.fromkeys(tipo(m["nome"]) for m in motivos))
    if "outros" in tipos:
        return "dos motivos " + _em_lista([_motivo_curto(m["nome"]) for m in motivos])
    return " e ".join(tipos)


def _comissao(doc, d: dict) -> None:
    brindes = rotulo_brindes(d["motivos_brindes"])
    estados = " · ".join(f"{e['estado']}: {_plural(e['vendedores'], 'vendedor', 'vendedores')}, {moeda(e['a_pagar'])}"
                         for e in d.get("por_estado") or [])
    _cabecalho(doc, f"Comissão dos vendedores · {mes_titulo(d)}",
               [_situacao(d), f"A comissão das vendas a clientes, menos as devoluções e os brindes {brindes}. Só as "
                "equipes BA e ES.", *([estados] if estados else [])],
               ["Vendas: comissão gravada no ERP", f"Descontos: devoluções e brindes {brindes}",
                "× o % de hoje da tabela do ERP"])
    if not d["vendedores"]:
        _vazio(doc, f"Nenhum vendedor das equipes BA e ES do seu acesso vendeu em {d['mes']['rotulo']}.")
        return
    traco = lambda v: moeda(v) if v else "—"  # noqa: E731
    desconto = lambda v: f"- {moeda(v)}" if v else "—"  # noqa: E731
    sem_brindes = d.get("sem_brindes")
    linhas = [[v["nome"], v["estado"], moeda(v["vendido"]), moeda(v["comissao_vendas"]), pct(v["pct"], 2),
               traco(v["devolvido"]), desconto(v["desc_devolucoes"]), "…" if sem_brindes else traco(v["brindes"]),
               desconto(v["desc_brindes"]), moeda(v["a_pagar"])] for v in d["vendedores"]]
    t = d["total"]
    _tabela(doc, COL_COMISSAO, linhas,
            [["Total", str(t["vendedores"]), moeda(t["vendido"]), moeda(t["comissao_vendas"]), pct(t["pct"], 2),
              traco(t["devolvido"]), desconto(t["desc_devolucoes"]), "…" if sem_brindes else traco(t["brindes"]),
              desconto(t["desc_brindes"]), moeda(t["a_pagar"])]])

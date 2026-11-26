"""O contrato de avalista em PDF (página Reavaliação de Crédito, botão "Avalista"; os dados vêm de bi/avalista.py).

Dois modelos, os do usuário em Word (fevereiro de 2026), que saem aqui com o mesmo texto e a mesma página:
- "pj": Contrato de Garantia Fidejussória e Outras Avenças (quem garante é uma empresa), com o cabeçalho da Mais Vida;
- "pf": Contrato de Compra e Venda de Produtos Lácteos por Prazo Indeterminado e Outras Avenças (quem garante é uma
  pessoa), sem cabeçalho.
As cláusulas fixas ficam em bi/avalista_texto.py; aqui são montadas as partes, a data, as assinaturas e a página.

A página é a do Word: A4, 3 cm dos lados, 2,5 cm em cima e embaixo, texto justificado, 8 pt depois de cada parágrafo
e linha de 1,16. A letra dos modelos é a Aptos 12, que é da Microsoft e só pode ser usada dentro do Office (não vai
para o servidor). No lugar dela entra a Liberation Sans (livre, com as medidas da Arial; bi/fontes) em 11,4: as
maiúsculas ficam da mesma altura e o texto dos contratos ocupa a mesma largura (medido: 11,42 a 11,46). A altura das linhas é a que o Word dá à Aptos,
então cada página leva o mesmo número de linhas do modelo.

Como no Word: um parágrafo não deixa uma linha sozinha no fim nem no começo da página. A mais que o Word: o título de
uma cláusula não fica sozinho no fim da página, um bloco de assinatura não se divide e um parágrafo em branco não abre
página. O que ficou sem preencher sai como uma linha (LACUNA), para completar à mão.

O que mudou no texto das partes em relação aos modelos (combinado com o usuário em 2026-11-25): o CNPJ da Mais Vida na
assinatura (o modelo trazia "[Número do CNPJ]"); "E, como interveniente garantidora:" em parágrafo próprio (estava
colado no fim do parágrafo da compradora); a vírgula antes de "CEP"; a data como "Itabela – BA, 4 de fevereiro de
2026."; e "conforme poderes conferidos por ..." só quando o campo é preenchido. Em 2026-11-26, a pedido dele, saiu o
RG: onde os modelos diziam "portador(a) da Cédula de Identidade RG nº ... e inscrito(a) no CPF sob o nº ...", fica só
"inscrito(a) no CPF sob o nº ...".
"""
from __future__ import annotations

import datetime as dt
import itertools
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .arquivos import PDF, _importar
from .avalista_texto import PF_CLAUSULAS, PJ_CLAUSULAS

TIPO = "application/pdf"
FONTES = Path(__file__).resolve().parent / "fontes"
LOGO = Path(__file__).resolve().parent.parent / "web" / "img" / "logo-maisvida.png"
FONTE = "contrato"
ARQUIVOS_FONTE = {"": "LiberationSans-Regular.ttf", "B": "LiberationSans-Bold.ttf", "I": "LiberationSans-Italic.ttf"}

# A página, em pontos.
LARGURA_PAGINA, ALTURA_PAGINA = 595.28, 841.89  # A4
MARGEM_LADO, MARGEM_VERTICAL = 85.05, 70.85     # 3 cm e 2,5 cm
LARGURA = LARGURA_PAGINA - 2 * MARGEM_LADO
ESCALA = 11.4 / 12           # o tamanho da Liberation Sans para cada ponto da Aptos (medido no texto dos contratos)
ASCENSAO = 1923 / 2048       # da Aptos: onde fica a linha de base dentro da linha (× o tamanho)
ALTURA_LINHA = 2500 / 2048   # da Aptos: a linha "simples" do Word (× o tamanho)
MULTIPLO = 278 / 240         # o espaçamento entre linhas do parágrafo normal dos modelos
DEPOIS = 8.0                 # o espaço depois de cada parágrafo normal
# O cabeçalho do modelo Pessoa Jurídica: o logotipo e a caixa com o nome e o endereço.
LOGO_X, LOGO_Y, LOGO_LARGURA = 90.0, 20.6, 73.0
CAIXA = (195.9, 8.5, 224.6, 49.2)  # x, y, largura, altura
CAIXA_TEXTO_X, CAIXA_BASES, CAIXA_TRACO = 203.4, (22.0, 36.1), 0.75
# As linhas de assinatura e das testemunhas: até onde vai o sublinhado e os recuos, em pontos desde a margem.
ASSINATURA_ATE = {"pj": 382.0, "pf": LARGURA}
RECUO_NUMERO, RECUO_LISTA = 18.0, 36.0

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")
LACUNA = "_" * 14
LOCAL = "Itabela – BA"  # onde o contrato é assinado (o foro das cláusulas é o mesmo)
TITULOS = {"pj": "Contrato de Garantia Fidejussória e Outras Avenças",
           "pf": "Contrato de Compra e Venda de Produtos Lácteos por Prazo Indeterminado e Outras Avenças"}


@dataclass
class Paragrafo:
    trechos: list[tuple[str, str]]  # (texto, "" | "B" negrito | "I" itálico); vazio = parágrafo em branco
    alinhar: str = "J"              # J justificado, L esquerda, C centro, R direita
    tamanho: float = 12.0           # o do Word (a letra sai em tamanho × ESCALA)
    simples: bool = False           # linha simples e sem espaço depois (as assinaturas)
    junto: bool = False             # não fica sozinho no fim da página (título de cláusula)
    grupo: int | None = None        # parágrafos seguidos do mesmo grupo ficam na mesma página
    recuo: float = 0.0              # da margem esquerda, em pontos
    numero: str | None = None       # "1." antes do texto (as testemunhas)
    linha_ate: float | None = None  # completa com sublinhados até este ponto, em pontos desde a margem
    linha_negrito: bool = False

    @property
    def passo(self) -> float:
        return self.tamanho * ALTURA_LINHA * (1.0 if self.simples else MULTIPLO)

    @property
    def depois(self) -> float:
        return 0.0 if self.simples else DEPOIS


@dataclass
class _Palavra:
    pecas: list[tuple[str, str]]  # (texto, estilo): uma palavra pode ter um pedaço em negrito
    largura: float
    espaco: bool                  # tem espaço depois (False: só pode quebrar a linha, depois de um hífen)


# ---------- o texto ----------
_MARCA = re.compile(r"(\*\*|//)")


def trechos(texto: str, campos: dict | None = None) -> list[tuple[str, str]]:
    """O texto com marcas (**negrito**, //itálico//) em trechos (texto, estilo). Os {campos} são trocados depois de
    separar as marcas: o que a pessoa digitou nunca é lido como marca."""
    saida, negrito, italico = [], False, False
    for parte in _MARCA.split(texto):
        if parte == "**":
            negrito = not negrito
        elif parte == "//":
            italico = not italico
        elif parte:
            if campos and "{" in parte:
                parte = parte.format_map(campos)
            saida.append((parte, "B" if negrito else "I" if italico else ""))
    return saida


def _v(d: dict | None, chave: str) -> str:
    """O valor de um campo, ou a linha para preencher à mão."""
    return str((d or {}).get(chave) or "").strip() or LACUNA


def _maiuscula(texto: str) -> str:
    return texto[:1].upper() + texto[1:]


def data_por_extenso(iso: str | None) -> str:
    """"2026-02-04" -> "4 de fevereiro de 2026" (dia 1 = "1º"); sem data, as linhas para preencher."""
    try:
        d = dt.date.fromisoformat(str(iso))
    except ValueError:
        return "____ de ______________ de ________"
    return f"{'1º' if d.day == 1 else d.day} de {MESES[d.month - 1]} de {d.year}"


def nome_arquivo(dados: dict) -> str:
    """"Contrato de avalista PJ - NOME DA COMPRADORA.pdf", sem os caracteres que o Windows não aceita em nome."""
    nome = str((dados.get("compradora") or {}).get("razao_social") or "").strip()
    nome = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", unicodedata.normalize("NFC", nome))
    nome = re.sub(r"\s+", " ", nome).strip(" .")[:80].strip(" .")
    return f"Contrato de avalista {dados['tipo'].upper()}{' - ' + nome if nome else ''}.pdf"


def _p(texto: str, campos: dict | None = None, **k) -> Paragrafo:
    return Paragrafo(trechos(texto, campos), **k)


def _fixos(clausulas, campos: dict | None = None) -> list[Paragrafo]:
    return [Paragrafo(trechos(t, campos), junto=e == "T") for e, t in clausulas]


def _representantes(empresa: dict, modelo: str) -> str:
    """Os representantes da empresa como saem no começo do contrato; nenhum = a linha para preencher."""
    partes = []
    for r in empresa.get("representantes") or [{}]:
        pessoa = (f"{_v(r, 'nome')}, {_v(r, 'nacionalidade')}, {_v(r, 'estado_civil')}, {_v(r, 'profissao')}, "
                  f"inscrito(a) no CPF sob o nº {_v(r, 'cpf')}")
        if modelo == "pj":  # o modelo Pessoa Jurídica traz o tratamento e onde a pessoa mora
            tratamento = str(r.get("tratamento") or "").strip()
            pessoa = (f"{tratamento + ' ' if tratamento else ''}{pessoa}, residente e domiciliado(a) em "
                      f"{_v(r, 'endereco')}, CEP {_v(r, 'cep')}, BRASIL")
        partes.append(pessoa)
    return ", e ".join(partes)


def _quem_assina(empresa: dict, modelo: str) -> str:
    """Quem assina pela empresa: "Sr. FULANO e Sra. BELTRANA" (no modelo Pessoa Física, só os nomes). Como nos
    modelos, cada empresa tem uma linha de assinatura só, mesmo com mais de um representante."""
    nomes = []
    for r in empresa.get("representantes") or [{}]:
        tratamento = str(r.get("tratamento") or "").strip() if modelo == "pj" else ""
        nomes.append(f"{tratamento + ' ' if tratamento else ''}{_v(r, 'nome')}")
    return " e ".join(nomes)


def _empresa_pj(rotulo: str, termo: str, e: dict) -> Paragrafo:
    ie = str(e.get("ie") or "").strip()
    poderes = str(e.get("poderes") or "").strip()
    return _p(f"**{rotulo}:** **{{razao}}**, com sede em {{endereco}}, CEP {{cep}}, inscrita no CNPJ sob o nº {{cnpj}}"
              "{ie}, neste ato representada por seu(s) {qualificacao}, {representantes}{poderes}. Doravante denominada "
              f"simplesmente **{termo}**;",
              {"razao": _v(e, "razao_social"), "endereco": _v(e, "endereco"), "cep": _v(e, "cep"), "cnpj": _v(e, "cnpj"),
               "ie": f", e Inscrição Estadual nº {ie}" if ie else "", "qualificacao": _v(e, "qualificacao"),
               "representantes": _representantes(e, "pj"),
               "poderes": f", conforme poderes conferidos por {poderes}" if poderes else ""})


def _assinatura(rotulo: str, linhas: list[str], campos: dict, grupos, modelo: str) -> list[Paragrafo]:
    """O bloco de quem assina: o rótulo com a linha da assinatura e, embaixo, o nome e quem representa."""
    negrito = modelo == "pf"  # no modelo Pessoa Física a linha da assinatura também é em negrito
    k = {"alinhar": "L", "simples": True, "grupo": next(grupos)}
    return [_p(f"**{rotulo}:**", linha_ate=ASSINATURA_ATE[modelo], linha_negrito=negrito, **k),
            *(_p(t, campos, **k) for t in linhas)]


def _assinatura_da_empresa(rotulo: str, empresa: dict, grupos, modelo: str) -> list[Paragrafo]:
    linhas = ["**{razao}** CNPJ nº {cnpj}", "Representada por: {quem}", "{cargo}"] if modelo == "pj" else         ["**{razao}** CNPJ: {cnpj}", "Representada por: {quem}"]
    return _assinatura(rotulo, linhas, {"razao": _v(empresa, "razao_social"), "cnpj": _v(empresa, "cnpj"),
                                        "quem": _quem_assina(empresa, modelo),
                                        "cargo": _maiuscula(_v(empresa, "qualificacao"))}, grupos, modelo)


def _testemunhas(modelo: str, grupos) -> list[Paragrafo]:
    """O título e as duas testemunhas, num grupo só (não se dividem entre duas páginas)."""
    grupo = next(grupos)
    saida = [_p("**TESTEMUNHAS:**", grupo=grupo)]
    for n in (1, 2):
        if modelo == "pj":  # letra 10, "Nome.", "CPF:" e "Ass."
            k = {"alinhar": "L", "tamanho": 10.0, "grupo": grupo}
            saida += [_p("Nome.", recuo=RECUO_LISTA, numero=f"{n}.", linha_ate=352.0, **k),
                      _p("CPF:", recuo=28.65, linha_ate=239.0, **k), _p("Ass.", recuo=28.65, linha_ate=239.0, **k)]
            if n == 1:
                saida.append(Paragrafo([], tamanho=10.0, grupo=grupo))
        else:
            k = {"alinhar": "L", "simples": True, "grupo": grupo}
            saida += [_p("Testemunha", recuo=RECUO_LISTA, numero=f"{n}.", linha_ate=278.6, **k),
                      _p("Nome:", recuo=65.25, linha_ate=279.4, **k), _p("CPF:", recuo=65.25, linha_ate=279.4, **k)]
            if n == 1:
                saida += [Paragrafo([], simples=True, grupo=grupo), Paragrafo([], simples=True, grupo=grupo)]
    return saida


def paragrafos(dados: dict, fornecedor: dict) -> list[Paragrafo]:
    """O contrato inteiro, parágrafo a parágrafo, na ordem do modelo. dados: o contrato já conferido
    (bi/avalista.py: normalizar); fornecedor: os dados da Mais Vida (ConfigAvalista)."""
    modelo, c, g, f = dados["tipo"], dados.get("compradora") or {}, dados.get("garantidor") or {}, fornecedor
    grupos = itertools.count(1)  # cada bloco de assinatura é um grupo: não se divide entre duas páginas
    data = _p(f"{LOCAL}, {{data}}.", {"data": data_por_extenso(dados.get("data"))}, alinhar="R")
    if modelo == "pj":
        campos_f = {"razao": _v(f, "razao_social"), "cnpj": _v(f, "cnpj"), "endereco": _v(f, "endereco"),
                    "cep": _v(f, "cep"), "qualificacao": _v(f, "qualificacao"),
                    "representante": f"{str(f.get('tratamento') or '').strip()} {_v(f, 'representante')}".strip()}
        nomes = {"fornecedor": _v(f, "razao_social"), "compradora": _v(c, "razao_social"),
                 "garantidora": _v(g, "razao_social")}
        return [
            _p("**CONTRATO DE GARANTIA FIDEJUSSÓRIA E OUTRAS AVENÇAS**", alinhar="C"),
            Paragrafo([], alinhar="C"),
            _p("Pelo presente instrumento particular, de um lado:"),
            _p("**FORNECEDOR:** **{razao}**, pessoa jurídica de direito privado, inscrita no CNPJ sob o nº {cnpj}, com "
               "sede na {endereco}, CEP {cep}, neste ato representada por seu {qualificacao}, {representante}, doravante "
               "denominada simplesmente **FORNECEDOR**;", campos_f),
            _p("De outro lado:"),
            _empresa_pj("COMPRADORA", "COMPRADORA", c),
            _p("E, como interveniente garantidora:"),
            _empresa_pj("GARANTIDORA/AVALISTA", "GARANTIDORA", g),
            *_fixos(PJ_CLAUSULAS, nomes),
            data,
            Paragrafo([], simples=True),
            *_assinatura("FORNECEDOR", ["**{razao}** CNPJ nº {cnpj}", "Representada por: {representante}", "{cargo}"],
                         {**campos_f, "cargo": _maiuscula(_v(f, "qualificacao"))}, grupos, modelo),
            Paragrafo([]),
            *_assinatura_da_empresa("COMPRADORA", c, grupos, modelo),
            Paragrafo([]),
            *_assinatura_da_empresa("GARANTIDORA/AVALISTA", g, grupos, modelo),
            Paragrafo([], simples=True),
            Paragrafo([], simples=True),
            *_testemunhas(modelo, grupos),
        ]
    ie_c, ie_f = str(c.get("ie") or "").strip(), str(f.get("ie") or "").strip()
    return [
        _p("**CONTRATO DE COMPRA E VENDA DE PRODUTOS LÁCTEOS POR PRAZO INDETERMINADO E OUTRAS AVENÇAS**"),
        _p("Pelo presente instrumento particular de Contrato de Compra e Venda de Produtos Lácteos, as partes "
           "qualificadas abaixo, de um lado, como COMPRADORA, e de outro, como FORNECEDOR, e como GARANTIDORA, têm entre "
           "si, justo e contratado o que segue, mediante as cláusulas e condições adiante estabelecidas:"),
        _p("**1. DAS PARTES**", junto=True),
        _p("**1.1. COMPRADORA:** **{razao}**, pessoa jurídica de direito privado, inscrita no CNPJ sob o nº **{cnpj}**"
           "{ie}, com sede e foro na {endereco}, CEP {cep}, neste ato representada por seu(s) {qualificacao}, "
           "{representantes}, doravante denominada simplesmente **\"COMPRADORA\"**.",
           {"razao": _v(c, "razao_social"), "cnpj": _v(c, "cnpj"), "endereco": _v(c, "endereco"), "cep": _v(c, "cep"),
            "ie": f", com Inscrição Estadual nº {ie_c}" if ie_c else "", "qualificacao": _v(c, "qualificacao"),
            "representantes": _representantes(c, "pf")}),
        _p("**1.2. FORNECEDOR:** **{razao}**, pessoa jurídica de direito privado, inscrita no CNPJ sob o nº **{cnpj}**"
           "{ie}, com sede e foro na {endereco}, CEP {cep}, neste ato representada por seu(s) {qualificacao}, "
           "{representante}, {nacionalidade}, {estado_civil}, {profissao}, inscrito(a) no CPF sob o nº {cpf}, doravante "
           "denominado simplesmente **\"FORNECEDOR\"**.",
           {"razao": _v(f, "razao_social"), "cnpj": _v(f, "cnpj"), "endereco": _v(f, "endereco"), "cep": _v(f, "cep"),
            "ie": f", com Inscrição Estadual nº {ie_f}" if ie_f else "", "qualificacao": _v(f, "qualificacao"),
            "representante": _v(f, "representante"), "nacionalidade": _v(f, "nacionalidade"),
            "estado_civil": _v(f, "estado_civil"), "profissao": _v(f, "profissao"), "cpf": _v(f, "cpf")}),
        _p("**1.3. GARANTIDORA:** **{nome}**, {nacionalidade}, {estado_civil}, {profissao}, inscrito(a) no CPF sob o nº "
           "**{cpf}**, residente e domiciliado(a) na {endereco}, CEP {cep}, doravante denominada simplesmente "
           "**\"GARANTIDORA\"**.",
           {k: _v(g, k) for k in ("nome", "nacionalidade", "estado_civil", "profissao", "cpf", "endereco", "cep")}),
        *_fixos(PF_CLAUSULAS),
        data,
        Paragrafo([]),
        *_assinatura_da_empresa("COMPRADORA", c, grupos, modelo),
        Paragrafo([]),
        Paragrafo([]),
        *_assinatura("FORNECEDOR", ["**{razao}** CNPJ: {cnpj}", "Representada por: {quem}"],
                     {"razao": _v(f, "razao_social"), "cnpj": _v(f, "cnpj"), "quem": _v(f, "representante")}, grupos,
                     modelo),
        Paragrafo([]),
        Paragrafo([]),
        *_assinatura("GARANTIDOR", ["**{nome}** CPF: {cpf}"], {"nome": _v(g, "nome"), "cpf": _v(g, "cpf")}, grupos,
                     modelo),
        Paragrafo([]),
        *_testemunhas(modelo, grupos),
    ]


# ---------- a página ----------
_PEDACOS = re.compile(r" +|[^ ]+")
_HIFEN = re.compile(r"(?<=[^\W\d_]-)(?=[^\W\d_])")  # depois de um hífen entre letras a linha pode quebrar, como no Word


class _Pagina:
    """O PDF em montagem: mede as palavras, quebra e justifica as linhas e passa de página."""

    def __init__(self, fpdf, cabecalho: tuple[str, str] | None):
        self.doc = fpdf.FPDF(unit="pt", format="A4")
        self.doc.set_auto_page_break(False)
        for estilo, arquivo in ARQUIVOS_FONTE.items():
            self.doc.add_font(FONTE, estilo, str(FONTES / arquivo))
        self.cabecalho = cabecalho
        self._larguras: dict[tuple[str, str, float], float] = {}
        self.y, self.vazia = MARGEM_VERTICAL, True
        self.nova()

    def largura(self, texto: str, estilo: str, tamanho: float) -> float:
        chave = (texto, estilo, tamanho)
        valor = self._larguras.get(chave)
        if valor is None:
            self.doc.set_font(FONTE, estilo, tamanho * ESCALA)
            valor = self._larguras[chave] = self.doc.get_string_width(texto)
        return valor

    def nova(self) -> None:
        self.doc.add_page()
        if self.cabecalho:
            self.doc.image(str(LOGO), x=LOGO_X, y=LOGO_Y, w=LOGO_LARGURA)
            self.doc.set_draw_color(0)
            self.doc.set_line_width(CAIXA_TRACO)
            self.doc.rect(*CAIXA)
            for texto, base in zip(self.cabecalho, CAIXA_BASES):
                tamanho = 10.0
                while tamanho > 6 and self.largura(texto, "", tamanho) > CAIXA[2] - 15:  # endereço comprido: encolhe
                    tamanho -= 0.5
                self.doc.set_font(FONTE, "", tamanho * ESCALA)
                self.doc.text(CAIXA_TEXTO_X, base, texto)
        self.y, self.vazia = MARGEM_VERTICAL, True

    def _palavras(self, partes: list[tuple[str, str]], tamanho: float) -> list[_Palavra]:
        palavras: list[_Palavra] = []
        pecas: list[tuple[str, str]] = []

        def fechar(espaco: bool) -> None:
            nonlocal pecas
            if pecas:
                palavras.append(_Palavra(pecas, sum(self.largura(t, e, tamanho) for t, e in pecas), espaco))
                pecas = []
            elif espaco and palavras:
                palavras[-1].espaco = True

        for texto, estilo in partes:
            for pedaco in _PEDACOS.findall(texto):
                if pedaco[0] == " ":
                    fechar(True)
                    continue
                for k, parte in enumerate(_HIFEN.split(pedaco)):
                    if k:
                        fechar(False)
                    pecas.append((parte, estilo))
        fechar(False)
        return palavras

    def medir(self, p: Paragrafo) -> list[list[_Palavra]]:
        """As linhas do parágrafo (cada uma, as palavras dela); parágrafo em branco = nenhuma."""
        partes = list(p.trechos)
        if p.linha_ate is not None:
            usado = p.recuo + sum(self.largura(t, e, p.tamanho) for t, e in partes)
            estilo = "B" if p.linha_negrito else ""
            partes.append(("_" * max(3, int((p.linha_ate - usado) / self.largura("_", estilo, p.tamanho))), estilo))
        cabe, espaco = LARGURA - p.recuo, self.largura(" ", "", p.tamanho)
        linhas, atual, usado = [], [], 0.0
        for w in self._palavras(partes, p.tamanho):
            vao = espaco if atual and atual[-1].espaco else 0.0
            if atual and usado + vao + w.largura > cabe + 0.01:
                linhas.append(atual)
                atual, usado, vao = [], 0.0, 0.0
            atual.append(w)
            usado += vao + w.largura
        if atual:
            linhas.append(atual)
        return linhas

    def _escrever(self, palavras: list[_Palavra], p: Paragrafo, justificar: bool, primeira: bool) -> None:
        espaco = self.largura(" ", "", p.tamanho)
        vaos = sum(1 for w in palavras[:-1] if w.espaco)
        livre = LARGURA - p.recuo - sum(w.largura for w in palavras) - espaco * vaos
        x, vao = MARGEM_LADO + p.recuo, espaco
        if p.alinhar == "C":
            x += livre / 2
        elif p.alinhar == "R":
            x += livre
        elif justificar and vaos and livre > 0:
            vao += livre / vaos
        base = self.y + ASCENSAO * p.tamanho
        if primeira and p.numero:
            self.doc.set_font(FONTE, "", p.tamanho * ESCALA)
            self.doc.text(MARGEM_LADO + p.recuo - RECUO_NUMERO, base, p.numero)
        for i, w in enumerate(palavras):
            for k, (texto, estilo) in enumerate(w.pecas):
                self.doc.set_font(FONTE, estilo, p.tamanho * ESCALA)
                # o espaço vai junto da palavra (a posição da seguinte é dada): quem copia o texto do PDF leva os espaços
                fim = k == len(w.pecas) - 1 and w.espaco and i < len(palavras) - 1
                self.doc.text(x, base, texto + " " if fim else texto)
                x += self.largura(texto, estilo, p.tamanho)
            if w.espaco:
                x += vao
        self.y += p.passo
        self.vazia = False

    def compor(self, lista: list[Paragrafo]) -> None:
        blocos = [(p, self.medir(p) if p.trechos or p.linha_ate is not None else []) for p in lista]
        limite = ALTURA_PAGINA - MARGEM_VERTICAL + 0.01
        for i, (p, linhas) in enumerate(blocos):
            if not linhas:  # em branco: ocupa uma linha; não abre página nem fica no alto de uma página nova
                if self.y + p.passo > limite:
                    self.nova()
                elif not (self.vazia and self.doc.page_no() > 1):
                    self.y += p.passo + p.depois
                continue
            if p.grupo is not None and (i == 0 or blocos[i - 1][0].grupo != p.grupo):  # o bloco inteiro na mesma página
                altura, j = 0.0, i
                while j < len(blocos) and blocos[j][0].grupo == p.grupo:
                    altura += max(1, len(blocos[j][1])) * blocos[j][0].passo + blocos[j][0].depois
                    j += 1
                if self.y + altura - blocos[j - 1][0].depois > limite and not self.vazia:
                    self.nova()
            elif p.junto and i + 1 < len(blocos) and blocos[i + 1][1]:  # o título com o começo do parágrafo seguinte
                q, seguintes = blocos[i + 1]
                precisa = len(linhas) * p.passo + p.depois + (len(seguintes) if len(seguintes) <= 3 else 2) * q.passo
                if self.y + precisa > limite and not self.vazia:
                    self.nova()
            feitas = 0
            while feitas < len(linhas):
                faltam, cabem = len(linhas) - feitas, max(0, int((limite - self.y) / p.passo))
                if cabem >= faltam:
                    k = faltam
                elif p.grupo is not None:
                    k = 0
                else:
                    k = cabem - 1 if faltam - cabem == 1 else cabem  # a última linha não vai sozinha para a outra página
                    if k < 2 and not feitas:  # nem a primeira fica sozinha nesta
                        k = 0
                if k <= 0 and self.vazia:  # página nova e ainda não cabe (bloco maior que a página): segue como der
                    k = max(1, min(cabem, faltam))
                if k <= 0:
                    self.nova()
                    continue
                for n in range(feitas, feitas + k):
                    self._escrever(linhas[n], p, p.alinhar == "J" and n < len(linhas) - 1, n == 0)
                feitas += k
                if feitas < len(linhas):
                    self.nova()
            self.y += p.depois


def documento(dados: dict, fornecedor: dict) -> bytes:
    """O PDF do contrato. dados: o contrato já conferido (bi/avalista.py); fornecedor: os dados da Mais Vida. Sem o
    pacote do PDF no servidor -> FaltaPacote."""
    fpdf = _importar(PDF)
    modelo = dados["tipo"]
    cabecalho = (_v(fornecedor, "razao_social"), f"{_v(fornecedor, 'endereco')}.") if modelo == "pj" else None
    pagina = _Pagina(fpdf, cabecalho)
    doc = pagina.doc
    compradora = str((dados.get("compradora") or {}).get("razao_social") or "").strip()
    doc.set_title(f"{TITULOS[modelo]}{' – ' + compradora if compradora else ''}")
    doc.set_author(str(fornecedor.get("razao_social") or ""))
    doc.set_creator("BI Mais Vida")
    doc.set_lang("pt-BR")
    pagina.compor(paragrafos(dados, fornecedor))
    return bytes(doc.output())

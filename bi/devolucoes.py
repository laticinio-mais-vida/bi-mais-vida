"""Devoluções (página Devoluções): o que voltou dos clientes, separado em dois problemas de natureza diferente, e o
Parecer de Devoluções do mês em PDF (bi/parecer_pdf.py), no formato do documento que era montado à mão.

- Voltou na entrega: o pedido não ficou no cliente (erro de lançamento, recusa, cliente ausente, erro de faturamento,
  da expedição ou da logística, falta de mercadoria). Poucas notas, de valor alto, quase sempre a nota inteira: a página
  lista nota a nota.
- Vencido e danificado no cliente: o produto foi entregue, ficou na loja e voltou vencido ou danificado, pela devolução
  imprópria ou pela troca feita por brinde. Muitos casos pequenos, todo mês: a página mede o índice sobre a venda por
  produto, segmento, frequência de visita e cliente. No código, "perda" é este total (vencido + danificado).

A tela não mostra os códigos do ERP (motivo, produto, série): quem usa o painel conhece as causas pelo nome e pela
descrição de cada uma (DESCRICOES).

A página não depende das outras nem das Configurações das metas: os motivos são fixos aqui, a devolução cancelada nunca
conta e cada produto fica com o código do ERP. De fora vem só a equipe de cada vendedor, para a região (a mesma do
Parecer), e o nome curto dele.

O que entra:
- devoluções de cliente do cadastro (tipocliente CLIENTE), pela data de entrada e pelo vendedor da devolução, nota a
  nota (devolucoes_notas). Sem as notas no cache (PC com o código anterior), cada cliente num dia conta como uma nota;
- brindes de troca: só os de motivo vencido ou danificado (3, 4 e 10 a 16). Brinde de outro motivo (transferência,
  degustação, doação, pagamento de contrato, perda) não é devolução e fica fora;
- venda bruta: as vendas não canceladas a cliente do mesmo recorte (vendedor da venda), sem descontar nada; entregas:
  as notas de venda (vendas_clientes).

Causas (pelo id do motivo no ERP) e responsáveis: CAUSAS. Devolução de um motivo fora da lista vai para "Outros
motivos", com aviso, como a regra "motivo novo → perguntar" do Parecer.

Comparação: a média dos 6 meses anteriores ao escolhido. O % é o total dos 6 meses sobre a venda dos 6 meses; valores,
notas e clientes são a média por mês. Os cortes que precisam de volume (produto, segmento, frequência de visita, clientes
e reincidência) usam os 6 meses até o escolhido.

Região do vendedor: a equipe das Configurações das metas ou do supervisor no ERP (Regras.grupo_conhecido): BA e Edir =
BA, ES = ES, sem equipe = Terceirizados; o OCULTO fica fora. Quem tem lista de vendedores ou de equipes no acesso vê só
os dele (Terceirizados, só quem não tem limite), como nas Premiações.

O Parecer (bloco de cada vendedor e rankings) segue as regras do documento antigo: só vendedores com devolução; seções na
ordem cliente ausente, erro de lançamento (com o nº de erros = datas + clientes distintos, como no documento), recusa,
vencido (devolução + brinde), danificado e os tipos adicionais; nas seções por produto, os produtos na ordem e com o
limite de volume do Parecer (cliente abaixo do limite não aparece no bloco, mas conta nos totais e nos rankings), com o
faturamento bruto do cliente no mês (de todos os vendedores) e o %; no fim do vencido, os clientes em alerta (% ≥ 20% e
volume ≥ 30, ou volume ≥ 100). Os erros internos e os outros motivos não entram no Parecer.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
from collections import defaultdict, namedtuple

from . import parecer_pdf
from .metas import MESES, Calculadora, nome_bonito
from .sugestao import curto_mes, indice, ler_mes, rotulo_mes, texto_mes

ABAS = ("resumo", "entrega", "cliente", "vendedores")
REGIOES = ("BA", "ES", "TERC")
NOME_REGIAO = {"BA": "BA", "ES": "ES", "TERC": "Terceirizados"}
TITULO_REGIAO = {"BA": "REGIÃO BA – BAHIA", "ES": "REGIÃO ES – ESPÍRITO SANTO", "TERC": "TERCEIRIZADOS"}
CAPA_REGIAO = {"BA": "Região BA – Bahia", "ES": "Região ES – Espírito Santo", "TERC": "Terceirizados"}
PASTA_REGIAO = {"BA": "BA", "ES": "ES", "TERC": "TERCEIRIZADOS"}
TIPOS_ARQUIVO = ("vendedor", "regiao", "geral", "todos")

FAMILIAS = {"entrega": "Voltou na entrega", "cliente": "Vencido e danificado no cliente", "outros": "Outros motivos"}
DESCRICAO_FAMILIA = {
    "entrega": "O pedido não ficou no cliente: a mercadoria voltou na hora da entrega.",
    "cliente": "O produto foi entregue, ficou na loja e voltou vencido ou danificado, por devolução ou trocado por brinde. "
               "É mercadoria que não volta para a venda.",
    "outros": "Devoluções de um motivo que a página ainda não separa.",
}
RESPONSAVEIS = {"comercial": "Comercial", "operacao": "Operação interna", "logistica": "Logística",
                "fabrica": "Fábrica", "pdv": "Ponto de venda", "sem_origem": "Origem não informada",
                "outros": "Sem causa definida"}
# (id, nome, família, responsável, motivos do ERP). O responsável é a etapa onde a devolução nasceu: o pedido
# (comercial), a separação e o faturamento (operação interna), o transporte e a entrega (logística), a produção
# (fábrica) ou a gôndola do cliente (ponto de venda: validade e manuseio).
CAUSAS = (
    ("lancamento", "Erro de lançamento", "entrega", "comercial", (1,)),
    ("recusa", "Recusa do cliente", "entrega", "comercial", (2,)),
    ("faturamento", "Erro de faturamento", "entrega", "operacao", (7,)),
    ("expedicao", "Erro da expedição", "entrega", "operacao", (9,)),
    ("falta", "Falta de mercadoria", "entrega", "operacao", (5,)),
    ("logistica", "Erro da logística", "entrega", "logistica", (8,)),
    ("ausente", "Cliente ausente", "entrega", "logistica", (6,)),
    ("vencido", "Vencido", "cliente", "pdv", (3, 16)),
    ("danificado_cliente", "Danificado no cliente", "cliente", "pdv", (12, 14)),
    ("danificado_logistica", "Danificado na logística", "cliente", "logistica", (11, 13)),
    ("danificado_producao", "Danificado na produção", "cliente", "fabrica", (10, 15)),
    ("danificado_sem_origem", "Danificado, sem origem informada", "cliente", "sem_origem", (4,)),
)
OUTROS = "outros"
# O que cada causa quer dizer, para quem usa o painel (aparece ao passar o mouse e no "Como é calculado").
DESCRICOES = {
    "lancamento": "O pedido foi lançado errado (produto, quantidade, preço ou cliente) e a mercadoria voltou na entrega.",
    "recusa": "O cliente não aceitou a mercadoria na hora da entrega.",
    "faturamento": "A nota saiu com erro e a mercadoria voltou.",
    "expedicao": "A carga foi separada errada no depósito.",
    "falta": "Faltou mercadoria na hora da entrega e o item da nota voltou.",
    "logistica": "Erro no transporte ou na entrega da mercadoria.",
    "ausente": "O cliente estava fechado ou ausente na hora da entrega.",
    "vencido": "O produto passou da validade na loja do cliente e voltou ou foi trocado por brinde.",
    "danificado_cliente": "O produto se estragou na loja do cliente: no manuseio, na armazenagem ou na exposição.",
    "danificado_logistica": "O produto chegou danificado por causa do transporte ou do manuseio na entrega.",
    "danificado_producao": "Defeito de fábrica: na embalagem, na vedação ou no próprio produto.",
    "danificado_sem_origem": "Voltou danificado, mas a devolução não diz onde o dano aconteceu.",
    OUTROS: "Devolução de um motivo que a página ainda não separa numa causa.",
}
_INFO_CAUSA = {c: {"id": c, "nome": n, "familia": f, "responsavel": r, "motivos": list(ms), "descricao": DESCRICOES[c]}
               for c, n, f, r, ms in CAUSAS}
_INFO_CAUSA[OUTROS] = {"id": OUTROS, "nome": "Outros motivos", "familia": "outros", "responsavel": "outros",
                       "motivos": [], "descricao": DESCRICOES[OUTROS]}
_CAUSA_DO_MOTIVO = {m: c for c, _, _, _, ms in CAUSAS for m in ms}
CAUSAS_ENTREGA = tuple(c for c, _, f, _, _ in CAUSAS if f == "entrega")
DANIFICADOS = ("danificado_producao", "danificado_logistica", "danificado_cliente", "danificado_sem_origem")
MOTIVOS_TROCA = tuple(sorted(m for _, _, f, _, ms in CAUSAS if f == "cliente" for m in ms))  # os brindes que entram
JANELA = 6  # meses: a comparação (os 6 anteriores) e os cortes de volume (os 6 até o escolhido)
REINCIDENCIA_MINIMO = 3  # vencido em 3 ou mais dos 6 meses
REPETE_MINIMO = 2  # 2 ou mais notas devolvidas na entrega nos 6 meses
FREQUENCIAS = {"SEMANAL": "Semanal", "QUINZENAL": "Quinzenal", "MENSAL": "Mensal"}
OUTRA_REDE = "Outra rede"
SEM_SEGMENTO = "Sem segmento"
LIMITE_CLIENTES = 250  # na aba No cliente, a lista dos clientes com mais vencido e danificado em 6 meses (as contas usam todos)

# O Parecer: (chave, título, motivos, tipo). "simples" = cliente, qtd e valor; "produtos" = por produto, só os clientes
# com volume a partir do limite do produto, com o faturamento bruto do cliente e o %.
SECOES = (
    ("ausente", "Devolução – Cliente Ausente", (6,), "simples"),
    ("lancamento", "Devolução – Erro de Lançamento", (1,), "simples"),
    ("recusa", "Devolução – Recusa do Cliente", (2,), "simples"),
    ("vencido", "Vencido", (3, 16), "produtos"),
    ("danificado", "Danificado", (4,), "produtos"),
    ("dan_producao", "Danificado – Problema na Produção", (15,), "produtos"),
    ("brinde_cliente", "Brinde – Danificado no Cliente", (12,), "produtos"),
    ("brinde_logistica", "Brinde – Danificado na Logística", (11,), "produtos"),
    ("brinde_producao", "Brinde – Danificado, Problema na Produção", (10,), "produtos"),
    ("imp_cliente", "Devolução Imprópria – Danificado no Cliente", (14,), "produtos"),
    ("imp_logistica", "Devolução Imprópria – Danificado na Logística", (13,), "produtos"),
)
SECAO_DO_MOTIVO = {m: s[0] for s in SECOES for m in s[2]}
# Os rankings do fim do Parecer, nesta ordem: por vendedor (o erro de lançamento com o nº de erros) e, os dois últimos,
# por cliente.
ORDEM_RANKINGS = ("lancamento", "vencido", "danificado", "dan_producao", "brinde_cliente", "brinde_logistica",
                  "brinde_producao", "imp_cliente", "imp_logistica", "recusa", "ausente")
RANKINGS_CLIENTE = ("recusa", "ausente")

# Ordem e limite de volume dos produtos no Parecer (cliente com volume abaixo do limite não aparece na tabela do produto).
# Os sabores de bebida láctea somam por tamanho; a bandeja inclui o código antigo dela (3643). Produto fora da lista vem
# no fim, com o nome do ERP e limite 1.
PRODUTOS_PARECER = (
    ("Bebida Láctea 170g", 15, (5413, 5416, 5417)),
    ("Bebida Láctea 450fr", 15, (3788, 3790, 3791)),
    ("Bebida Láctea 800g", 15, (10352, 10353, 10354)),
    ("Bebida Láctea 500g Bandeja", 15, (11469, 3643)),
    ("Bebida Láctea 900g", 15, (2105, 4835)),
    ("Manteiga 200g", 15, (25,)),
    ("Manteiga 500g", 15, (26,)),
    ("Manteiga a Granel 1kg", 10, (27,)),
    ("Queijo de Coalho 4kg", 4, (5973,)),
    ("Queijo de Coalho 370g Palito", 4, (9616,)),
    ("Queijo Minas Frescal Pote 340g", 4, (2270,)),
    ("Queijo Mussarela Mais Vida 4kg", 1, (32,)),
    ("Queijo Mussarela Muller 4kg", 1, (12175,)),
    ("Queijo Mussarela Muller (Fatiado)", 1, (12189,)),
    ("Queijo Mussarela Mais Natural 4kg", 1, (12552,)),
    ("Queijo Mussarela Mais Natural (Fatiado)", 1, (12551,)),
    ("Queijo Parmesão Peça C 5kg", 5, (24,)),
    ("Queijo Parmesão Cunha", 4, (4046,)),
    ("Queijo Prato 3kg", 3, (21,)),
    ("Requeijão Cremoso 180g", 15, (11098,)),
    ("Requeijão Cremoso Mais Natural 200g", 15, (9776,)),
    ("Requeijão Culinário Bisnaga 1,8kg", 15, (8991,)),
)
_PRODUTO_PARECER = {pid: (k, nome, limite) for k, (nome, limite, ids) in enumerate(PRODUTOS_PARECER) for pid in ids}
LIMITE_FORA_DA_LISTA = 1.0
# Clientes em alerta (vencimento), regra do Parecer: % do faturamento ≥ 20% e volume ≥ 30, ou volume ≥ 100.
ALERTA_PCT, ALERTA_VOLUME_COM_PCT, ALERTA_VOLUME = 0.20, 30.0, 100.0
_EPS = 1e-9

# Uma linha das devoluções ou dos brindes de troca (origem "devolucao" ou "brinde"). nota: o id da nota de devolução
# (None no brinde e no cache sem as notas); numero, serie e emissao: o número, a série e a data da nota.
Mov = namedtuple("Mov", "data vendedor cliente produto motivo origem valor qtd nota numero serie emissao")


# --- funções puras ---------------------------------------------------------------------------
def _div(a: float, b: float | None) -> float | None:
    return a / b if b else None


def _inicio(i: int) -> dt.date:
    return dt.date(i // 12, i % 12 + 1, 1)


def _fim(i: int) -> dt.date:
    a, m = i // 12, i % 12 + 1
    return dt.date(a, m, calendar.monthrange(a, m)[1])


def _mes(i: int) -> dict:
    return {"valor": texto_mes(i), "rotulo": rotulo_mes(i), "curto": curto_mes(i)}


def _janela(meses: list[int]) -> dict | None:
    if not meses:
        return None
    return {"de": _mes(meses[0]), "ate": _mes(meses[-1]), "meses": len(meses),
            "rotulo": curto_mes(meses[0]) if len(meses) == 1 else f"{curto_mes(meses[0])} a {curto_mes(meses[-1])}"}


def causa(motivo: int) -> str:
    return _CAUSA_DO_MOTIVO.get(motivo, OUTROS)


def familia(motivo: int) -> str:
    return _INFO_CAUSA[causa(motivo)]["familia"]


def chave_nota(m: Mov):
    """A nota de devolução da linha: o id do ERP; sem as notas no cache, o cliente e o dia."""
    return m.nota if m.nota is not None else (m.cliente, m.data)


def regiao_do_grupo(grupo_vendedor: str | None) -> str:
    """BA e Edir = BA; ES = ES; sem equipe (terceiros, contas internas) = Terceirizados."""
    return "BA" if grupo_vendedor in ("BA", "EDIR") else "ES" if grupo_vendedor == "ES" else "TERC"


def em_alerta(volume: float, valor: float, fat: float | None) -> bool:
    """Regra dos clientes em alerta do Parecer. Sem faturamento no mês, só o volume conta."""
    pct = _div(valor, fat)
    return volume + _EPS >= ALERTA_VOLUME or (pct is not None and pct + _EPS >= ALERTA_PCT
                                              and volume + _EPS >= ALERTA_VOLUME_COM_PCT)


def competencia(i: int) -> str:
    """'Setembro de 2026'."""
    return f"{MESES[i % 12].capitalize()} de {i // 12}"


def nome_de_arquivo(texto: str) -> str:
    """Sem os caracteres que o Windows não aceita num nome de arquivo."""
    return " ".join(re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(texto)).split()).strip(" .") or "Vendedor"


def _limpar(nome: str | None) -> str:
    return " ".join(str(nome or "").replace("\xa0", " ").split())


_MINUSCULAS = {"De", "Da", "Do", "Das", "Dos", "E", "Com", "C/", "Em"}


def nome_produto(nome: str | None) -> str:
    """'QUEIJO DE COALHO 370G PALITO' -> 'Queijo de Coalho 370g Palito'."""
    partes = nome_bonito(_limpar(nome)).split(" ")
    return " ".join(p.lower() if k and p in _MINUSCULAS else p for k, p in enumerate(partes))


def nome_linha(linha: str | None) -> str:
    """'A - LINHA DE QUEIJO MUSSARELA' -> 'Queijo Mussarela'; 'A - REQUEIJÃO CULINÁRIO BISNAGA' -> 'Requeijão
    Culinário Bisnaga'."""
    t = re.sub(r"^[A-Z]{1,3}\s*-\s*", "", _limpar(linha).upper())
    t = re.sub(r"^LINHA\s+(DE\s+)?", "", t)
    return nome_produto(t) if t else "Sem linha"


def nome_segmento(segmento: str | None) -> str:
    """'MERCEARIA (1 A 3 CAIXAS)' -> 'Mercearia (1 a 3 caixas)'; vazio -> 'Sem segmento'."""
    t = _limpar(segmento).lower()
    return t[:1].upper() + t[1:] if t else SEM_SEGMENTO


def frequencia(rede: str | None) -> str:
    """A frequência de visita da rede do cliente (Semanal, Quinzenal, Mensal); as redes de outro tipo, Outra rede."""
    return FREQUENCIAS.get(_limpar(rede).upper(), OUTRA_REDE)


def _somar(movs: list[Mov], venda: float, entregas: float, compradores: float, n: int = 1) -> dict:
    """Os números de um recorte de n meses (as somas dos n meses em venda, entregas e compradores). Valores, notas e
    clientes saem como a média por mês; os %, como o total dos meses sobre a venda dos meses."""
    n = max(n, 1)
    cs = {c: {"valor": 0.0, "notas": set(), "clientes": set()} for c in _INFO_CAUSA}
    fs = {f: {"valor": 0.0, "notas": set(), "clientes": set()} for f in FAMILIAS}
    brinde = 0.0
    for m in movs:
        c = causa(m.motivo)
        k = indice(m.data)
        for x in (cs[c], fs[_INFO_CAUSA[c]["familia"]]):
            x["valor"] += m.valor
            x["clientes"].add((k, m.cliente))  # o cliente de cada mês: a média de clientes por mês
            if m.origem == "devolucao":
                x["notas"].add(chave_nota(m))
        if m.origem == "brinde":
            brinde += m.valor
    e, cl, o = fs["entrega"], fs["cliente"], fs["outros"]
    total = e["valor"] + cl["valor"] + o["valor"]
    ne = len(e["notas"])
    venc, lanc = cs["vencido"], cs["lancamento"]
    danificado = sum(cs[a]["valor"] for a in DANIFICADOS)
    return {
        "meses": n, "venda": venda / n, "entregas": entregas / n, "compradores": compradores / n,
        "total": total / n, "pct": _div(total, venda),
        "entrega": {"valor": e["valor"] / n, "pct": _div(e["valor"], venda), "notas": ne / n,
                    "por_100": _div(ne * 100.0, entregas), "clientes": len(e["clientes"]) / n,
                    "valor_medio": _div(e["valor"], ne)},
        "cliente": {"valor": cl["valor"] / n, "pct": _div(cl["valor"], venda), "clientes": len(cl["clientes"]) / n,
                    "pct_clientes": _div(len(cl["clientes"]), compradores),
                    "vencido": venc["valor"] / n, "pct_vencido": _div(venc["valor"], venda),
                    "clientes_vencido": len(venc["clientes"]) / n, "danificado": danificado / n,
                    "pct_danificado": _div(danificado, venda), "brinde": brinde / n},
        "outros": {"valor": o["valor"] / n, "pct": _div(o["valor"], venda)},
        "lancamento": {"notas": len(lanc["notas"]) / n, "valor": lanc["valor"] / n},
        "causas": {c: {"valor": x["valor"] / n, "pct": _div(x["valor"], venda), "notas": len(x["notas"]) / n,
                       "clientes": len(x["clientes"]) / n} for c, x in cs.items()},
    }


def _arredondar(x):
    """Os números com 4 casas (centavos e o % com duas casas sobram): a resposta fica menor."""
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, dict):
        return {k: _arredondar(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_arredondar(v) for v in x]
    return x


def _sem_causas(r: dict | None) -> dict | None:
    """O resumo sem o detalhe por causa (o que os cartões e as tabelas usam)."""
    return None if r is None else {k: v for k, v in r.items() if k != "causas"}


def _principal(valores: dict) -> int | None:
    """A chave de maior valor (empate: a menor chave)."""
    return max(valores, key=lambda k: (valores[k], -k if isinstance(k, int) else 0), default=None)


# --- a página -------------------------------------------------------------------------------
class Devolucoes:
    def __init__(self, calc: Calculadora, nomes_vendedores):
        """nomes_vendedores: função que devolve {id: nome curto} (o da planilha de metas; a mesma das Premiações)."""
        self.calc = calc
        self.nomes = nomes_vendedores

    # --- apoio --------------------------------------------------------------------------------
    def _conferir(self) -> None:
        cache = self.calc.cache
        if not cache.pronto():
            raise RuntimeError("os dados ainda estão sendo preparados")
        if cache.antigo or cache.sem_detalhe:
            raise RuntimeError("as devoluções por cliente ainda não chegaram do computador da empresa; a página aparece "
                               "depois da próxima atualização")

    def hoje(self) -> dt.date:
        v = self.calc.cache.info.get("extraido_em")
        return dt.datetime.fromisoformat(v).date() if v else dt.date.today()

    def _primeiro(self) -> int:
        return indice(dt.date.fromisoformat(self.calc.cache.info.get("inicio") or "2024-01-01"))

    def meses(self) -> list[int]:
        """Os meses com dados, do mês dos dados ao início do cache."""
        return list(range(indice(self.calc.cache.data_ref()), self._primeiro() - 1, -1))

    def _escolher_mes(self, mes: str | None) -> tuple[int, list[int]]:
        meses = self.meses()
        if not mes:
            return meses[0], meses
        i = ler_mes(mes)
        if i not in meses:
            raise ValueError(f"escolha um mês com dados entre {curto_mes(meses[-1])} e {curto_mes(meses[0])}")
        return i, meses

    def _meses_cmp(self, i: int) -> list[int]:
        """Os 6 meses antes do escolhido (menos, no começo do cache)."""
        return [k for k in range(i - JANELA, i) if k >= self._primeiro()]

    def _janela6(self, i: int) -> list[int]:
        """Os 6 meses até o escolhido, inclusive (menos, no começo do cache)."""
        return [k for k in range(i - JANELA + 1, i + 1) if k >= self._primeiro()]

    @staticmethod
    def regioes(equipes: set[str] | None) -> list[str]:
        """As regiões que o usuário pode escolher: Terceirizados só sem limite de equipes."""
        if equipes is None:
            return list(REGIOES)
        return [r for r in ("BA", "ES") if any(g != "OCULTO" and regiao_do_grupo(g) == r for g in equipes)]

    @staticmethod
    def _filtro(regras, permitidos: set[int] | None, equipes: set[str] | None, regiao: str | None = None,
                escolhidos: set[int] | None = None):
        """Função vendedor -> região (None = fora do recorte: OCULTO, fora do acesso, outra região ou não escolhido)."""
        memo: dict[int, str | None] = {}

        def regiao_de(vid: int) -> str | None:
            if vid not in memo:
                g = regras.grupo_conhecido(vid)
                r = None
                if g != "OCULTO" and (equipes is None or g in equipes) and (permitidos is None or vid in permitidos):
                    r = regiao_do_grupo(g)
                    if (regiao and r != regiao) or (escolhidos and vid not in escolhidos):
                        r = None
                memo[vid] = r
            return memo[vid]
        return regiao_de

    def _linhas(self, de: dt.date, ate: dt.date, filtro) -> list[Mov]:
        """As devoluções (não canceladas, nota a nota) e os brindes de troca do período, dos vendedores do recorte."""
        cache = self.calc.cache
        if cache.sem_devolucoes_notas:
            saida = [Mov(d, v, c, p, m, "devolucao", val, q, None, None, None, None)
                     for d, v, c, p, m, val, q in cache.consulta(
                         "SELECT data, id_vendedor, id_cliente, id_produto, id_motivo, SUM(valor), SUM(quantidade) "
                         "FROM devolucoes_clientes_itens WHERE tipocliente = 'CLIENTE' AND NOT cancelada "
                         "AND data BETWEEN ? AND ? GROUP BY 1, 2, 3, 4, 5", [de, ate]) if filtro(v)]
        else:
            saida = [Mov(d, v, c, p, m, "devolucao", val, q, i, n, s, em)
                     for i, n, s, em, d, v, c, p, m, val, q in cache.consulta(
                         "SELECT id_devolucao, nota, serie, emissao, data, id_vendedor, id_cliente, id_produto, id_motivo, "
                         "SUM(valor), SUM(quantidade) FROM devolucoes_notas WHERE tipocliente = 'CLIENTE' "
                         "AND NOT cancelada AND data BETWEEN ? AND ? GROUP BY ALL", [de, ate]) if filtro(v)]
        if not cache.sem_brindes:
            marcas = ",".join("?" * len(MOTIVOS_TROCA))
            saida += [Mov(d, v, c, p, m, "brinde", val, q, None, None, None, None)
                      for d, v, c, p, m, val, q in cache.consulta(
                          "SELECT data, id_vendedor, id_cliente, id_produto, id_motivo, SUM(valor), SUM(quantidade) "
                          "FROM brindes_clientes_itens WHERE tipocliente = 'CLIENTE' AND data BETWEEN ? AND ? "
                          f"AND id_motivo IN ({marcas}) GROUP BY 1, 2, 3, 4, 5", [de, ate, *MOTIVOS_TROCA]) if filtro(v)]
        return saida

    def _base(self, k0: int, k1: int, filtro) -> dict:
        """Os meses de k0 a k1 no recorte: as linhas (por mês) e, por mês e vendedor, a venda bruta, as notas de venda
        (entregas) e os clientes que compraram."""
        cache = self.calc.cache
        de, ate = _inicio(k0), _fim(k1)
        mov = self._linhas(de, ate, filtro)
        por_mes: dict[int, list[Mov]] = defaultdict(list)
        for m in mov:
            por_mes[indice(m.data)].append(m)
        k_sql = "CAST(year(data) * 12 + month(data) - 1 AS INTEGER)"
        venda: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for k, vid, valor in cache.consulta(
                f"SELECT {k_sql}, id_vendedor, SUM(valor) FROM vendas_clientes_itens WHERE tipocliente = 'CLIENTE' "
                "AND data BETWEEN ? AND ? GROUP BY 1, 2", [de, ate]):
            if filtro(vid):
                venda[k][vid] += valor
        entregas: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        compradores: dict[int, dict[int, set]] = defaultdict(lambda: defaultdict(set))
        for k, vid, cli, n in cache.consulta(
                f"SELECT {k_sql}, id_vendedor, id_cliente, SUM(vendas) FROM vendas_clientes "
                "WHERE tipocliente = 'CLIENTE' AND data BETWEEN ? AND ? GROUP BY 1, 2, 3", [de, ate]):
            if filtro(vid):
                entregas[k][vid] += int(n or 0)
                compradores[k][vid].add(cli)
        return {"k0": k0, "k1": k1, "por_mes": por_mes, "venda": venda, "entregas": entregas,
                "compradores": compradores}

    @staticmethod
    def _recorte(base: dict, meses: list[int], ok=None) -> dict:
        """_somar dos meses, só dos vendedores em que ok(vendedor) é verdade (None = todos do recorte)."""
        ok = ok or (lambda vid: True)
        movs = [m for k in meses for m in base["por_mes"].get(k, ()) if ok(m.vendedor)]
        venda = sum(v for k in meses for vid, v in base["venda"].get(k, {}).items() if ok(vid))
        entregas = sum(n for k in meses for vid, n in base["entregas"].get(k, {}).items() if ok(vid))
        compradores = 0
        for k in meses:
            clientes: set = set()
            for vid, cs in base["compradores"].get(k, {}).items():
                if ok(vid):
                    clientes |= cs
            compradores += len(clientes)
        return _somar(movs, venda, entregas, compradores, len(meses))

    def _fat_clientes(self, de: dt.date, ate: dt.date, clientes) -> dict[int, float]:
        """O faturamento bruto de cada cliente no período, de todos os vendedores (como a planilha de faturamento)."""
        if not clientes:
            return {}
        ids = sorted(clientes)
        return dict(self.calc.cache.consulta(
            "SELECT id_cliente, SUM(valor) FROM vendas_clientes_itens WHERE tipocliente = 'CLIENTE' AND data BETWEEN ? "
            f"AND ? AND id_cliente IN ({','.join('?' * len(ids))}) GROUP BY 1", [de, ate, *ids]))

    def _nomes_motivos(self) -> dict[int, str]:
        return {m: _limpar(n) for m, n in self.calc.cache.consulta("SELECT id, nome FROM motivos")}

    def _info_clientes(self, ids) -> dict[int, dict]:
        if not ids:
            return {}
        ids = sorted(ids)
        return {c: {"nome": _limpar(n) or f"Cliente {c}", "cidade": cid, "uf": uf, "segmento": nome_segmento(seg)}
                for c, n, cid, uf, seg in self.calc.cache.consulta(
                    "SELECT c.id, c.nome, d.cidade, d.uf, d.segmento FROM clientes c LEFT JOIN clientes_detalhes d "
                    f"ON d.id = c.id WHERE c.id IN ({','.join('?' * len(ids))})", ids)}

    @staticmethod
    def _cliente(info: dict, c: int) -> dict:
        return {"id": c, **(info.get(c) or {"nome": f"Cliente {c}", "cidade": None, "uf": None,
                                             "segmento": SEM_SEGMENTO})}

    def _info_produtos(self, ids) -> dict[int, dict]:
        if not ids:
            return {}
        ids = sorted(ids)
        return {p: {"nome": _limpar(n) or f"Produto {p}", "linha": _limpar(lin) or "Sem linha", "unidade": un}
                for p, n, lin, un in self.calc.cache.consulta(
                    f"SELECT id, nome, linha, unidade FROM produtos WHERE id IN ({','.join('?' * len(ids))})", ids)}

    def _nomes_curtos(self) -> dict[int, str]:
        """O nome de cada vendedor na página e no nome do arquivo: o da planilha de metas; sem ele, o do ERP."""
        nomes = {vid: nome_bonito(n) for vid, n in self.calc.nomes_erp().items() if n}
        nomes.update(self.nomes() or {})
        return nomes

    def _nome_vendedor(self, nomes: dict, vid: int) -> str:
        return nomes.get(vid) or ("Sem vendedor" if not vid else f"Vendedor {vid}")

    def _nome_erp(self, nomes_erp: dict, vid: int) -> str:
        return _limpar(nomes_erp.get(vid)) or ("SEM VENDEDOR" if not vid else f"VENDEDOR {vid}")

    def _primeira_troca_por_brinde(self) -> int | None:
        """O primeiro mês com brinde de troca no cache (o ERP passou a ter o motivo no brinde em abr/26)."""
        if self.calc.cache.sem_brindes:
            return None
        marcas = ",".join("?" * len(MOTIVOS_TROCA))
        (d,), = self.calc.cache.consulta(
            f"SELECT MIN(data) FROM brindes_clientes_itens WHERE id_motivo IN ({marcas})", list(MOTIVOS_TROCA))
        return indice(d) if d else None

    # --- a página -------------------------------------------------------------------------------
    def calcular(self, aba: str | None = None, mes: str | None = None, regiao: str | None = None,
                 vendedores: list[int] | None = None, permitidos: set[int] | None = None,
                 equipes: set[str] | None = None) -> dict:
        """aba: resumo, entrega, cliente ou vendedores (vazio = resumo); mes: AAAA-MM (vazio = o mês dos dados); regiao:
        BA, ES ou TERC (vazio = todas); vendedores: ids (vazio = todos). permitidos/equipes: o que o usuário vê (None =
        sem limite), como nas Premiações."""
        aba = aba or "resumo"
        if aba not in ABAS:
            raise ValueError(f"aba desconhecida: {aba}")
        regiao = regiao or None
        if regiao and regiao not in REGIOES:
            raise ValueError(f"região desconhecida: {regiao}")
        regioes = self.regioes(equipes)
        if regiao and regiao not in regioes:
            raise PermissionError("seu acesso não inclui esta região")
        self._conferir()
        i, meses = self._escolher_mes(mes)
        regras = self.calc.regras()
        escolhidos = set(vendedores) if vendedores else None
        da_regiao = self._filtro(regras, permitidos, equipes, regiao)
        filtro = self._filtro(regras, permitidos, equipes, regiao, escolhidos)
        base = self._base(max(i - 12, self._primeiro()), i, filtro)
        if aba == "resumo":
            corpo = self._aba_resumo(i, base, filtro, regioes if not regiao else [regiao])
        elif aba == "entrega":
            corpo = self._aba_entrega(i, base, filtro)
        elif aba == "cliente":
            corpo = self._aba_cliente(i, base, filtro)
        else:
            corpo = self._aba_vendedores(i, base, filtro)
        return _arredondar({
            "aba": aba,
            "mes": _mes(i),
            "meses": [_mes(m) for m in meses],
            "regiao": regiao,
            "regioes": [{"id": r, "nome": NOME_REGIAO[r]} for r in regioes],
            "vendedores": sorted(escolhidos) if escolhidos else [],
            "vendedores_filtro": self._vendedores_do_mes(i, da_regiao),
            "familias": [{"id": f, "nome": n, "descricao": DESCRICAO_FAMILIA[f]} for f, n in FAMILIAS.items()],
            "responsaveis": [{"id": r, "nome": n} for r, n in RESPONSAVEIS.items()],
            # sem os códigos do ERP: a tela mostra o nome e a descrição de cada causa
            "causas": [{k: v for k, v in _INFO_CAUSA[c].items() if k != "motivos"}
                       for c in (*(c[0] for c in CAUSAS), OUTROS)],
            "janela_cmp": _janela(self._meses_cmp(i)),
            "janela6": _janela(self._janela6(i)),
            "notas_reais": not self.calc.cache.sem_devolucoes_notas,
            "situacao": "final" if self.hoje() > _fim(i) else "andamento",
            "data_ref": self.calc.cache.data_ref().isoformat(),
            "avisos": self._avisos(i, base, aba),
            **corpo,
        })

    def _avisos(self, i: int, base: dict, aba: str) -> list[str]:
        cache = self.calc.cache
        avisos = []
        if cache.sem_devolucoes_notas:
            avisos.append("O número das notas de devolução ainda não chegou do computador da empresa: até a próxima "
                          "atualização, cada cliente num dia conta como uma nota.")
        if cache.sem_brindes:
            avisos.append("Os brindes ainda não chegaram do computador da empresa: as trocas por brinde ficam de fora "
                          "até a próxima atualização.")
        outros = sorted({m.motivo for m in base["por_mes"].get(i, ()) if causa(m.motivo) == OUTROS})
        if outros:  # pelo nome que aparece no ERP, sem o código
            nomes = self._nomes_motivos()
            lista = sorted({f'"{nome_segmento(nomes[m])}"' if nomes.get(m) else "um motivo sem nome no ERP" for m in outros})
            avisos.append(f"Há devoluções de um motivo que a página ainda não separa ({', '.join(lista)}): elas aparecem em "
                          "Outros motivos. Se for um motivo novo no ERP, avise para ele ganhar uma causa.")
        primeira = self._primeira_troca_por_brinde()
        if aba in ("resumo", "cliente", "vendedores") and primeira is not None:
            # o primeiro mês que a aba mostra: o gráfico de 13 meses no Resumo; a média dos 6 meses nas outras
            olhados = base["k0"] if aba == "resumo" else min(self._meses_cmp(i) or [i])
            if olhados < primeira <= i:
                avisos.append(f"A troca por brinde só é registrada desde {curto_mes(primeira)}: antes disso, o vencido e "
                              "danificado no cliente aparece menor do que foi.")
        return avisos

    def _vendedores_do_mes(self, i: int, filtro) -> list[dict]:
        """Os vendedores do recorte (sem a escolha de vendedores) com venda ou devolução no mês, para o filtro."""
        de, ate = _inicio(i), _fim(i)
        ids = {vid for (vid,) in self.calc.cache.consulta(
            "SELECT DISTINCT id_vendedor FROM vendas_clientes_itens WHERE tipocliente = 'CLIENTE' AND data BETWEEN ? "
            "AND ?", [de, ate]) if filtro(vid)}
        ids |= {m.vendedor for m in self._linhas(de, ate, filtro)}
        nomes = self._nomes_curtos()
        ordem = {r: k for k, r in enumerate(REGIOES)}
        saida = [{"id": v, "nome": self._nome_vendedor(nomes, v), "regiao": filtro(v)} for v in ids]
        return sorted(saida, key=lambda v: (ordem[v["regiao"]], v["nome"].upper()))

    # --- aba Resumo ----------------------------------------------------------------------------
    def _aba_resumo(self, i: int, base: dict, filtro, regioes: list[str]) -> dict:
        cmp = self._meses_cmp(i)
        atual = self._recorte(base, [i])
        media = self._recorte(base, cmp) if cmp else None
        evolucao = []
        for k in range(base["k0"], i + 1):
            r = self._recorte(base, [k])
            evolucao.append({"mes": _mes(k), "venda": r["venda"], "total": r["total"], "pct": r["pct"],
                             "entrega": r["entrega"]["valor"], "cliente": r["cliente"]["valor"],
                             "outros": r["outros"]["valor"], "brinde": r["cliente"]["brinde"],
                             "notas": r["entrega"]["notas"], "entregas": r["entregas"]})
        tabela = []
        if len(regioes) > 1:
            for rg in regioes:
                def ok(vid, rg=rg):
                    return filtro(vid) == rg
                a = self._recorte(base, [i], ok)
                if a["venda"] <= _EPS and a["total"] <= _EPS:
                    continue
                tabela.append({"id": rg, "nome": NOME_REGIAO[rg], "atual": _sem_causas(a),
                               "media": _sem_causas(self._recorte(base, cmp, ok)) if cmp else None})
        return {"cartoes": {"atual": _sem_causas(atual), "media": _sem_causas(media)}, "evolucao": evolucao,
                "responsaveis_mes": self._por_responsavel(atual, media), "regioes_tabela": tabela}

    @staticmethod
    def _por_responsavel(atual: dict, media: dict | None) -> list[dict]:
        """As causas com valor no mês ou na média, agrupadas pelo responsável (o de maior valor primeiro)."""
        grupos: dict[str, dict] = {}
        for c in (*(x[0] for x in CAUSAS), OUTROS):
            a = atual["causas"][c]
            m = media["causas"][c] if media else None
            if a["valor"] <= _EPS and (m is None or m["valor"] <= _EPS):
                continue
            r = _INFO_CAUSA[c]["responsavel"]
            g = grupos.setdefault(r, {"id": r, "nome": RESPONSAVEIS[r], "valor": 0.0, "media_valor": 0.0,
                                      "causas": []})
            g["valor"] += a["valor"]
            g["media_valor"] += m["valor"] if m else 0.0
            g["causas"].append({"id": c, "valor": a["valor"], "pct": a["pct"], "notas": a["notas"],
                                "clientes": a["clientes"], "media_valor": m["valor"] if m else None,
                                "media_pct": m["pct"] if m else None})
        for g in grupos.values():
            g["pct"] = _div(g["valor"], atual["venda"])
            g["media_pct"] = _div(g["media_valor"], media["venda"]) if media else None
            if not media:
                g["media_valor"] = None
            g["causas"].sort(key=lambda x: (-x["valor"], -(x["media_valor"] or 0.0)))
        return sorted(grupos.values(), key=lambda g: (-g["valor"], -(g["media_valor"] or 0.0)))

    # --- aba Na entrega ------------------------------------------------------------------------
    def _aba_entrega(self, i: int, base: dict, filtro) -> dict:
        cmp = self._meses_cmp(i)
        atual = self._recorte(base, [i])
        media = self._recorte(base, cmp) if cmp else None
        causas = []
        for c in CAUSAS_ENTREGA:
            a = atual["causas"][c]
            m = media["causas"][c] if media else None
            if a["valor"] <= _EPS and (m is None or m["valor"] <= _EPS):
                continue
            causas.append({"id": c, "notas": a["notas"], "valor": a["valor"], "pct": a["pct"], "clientes": a["clientes"],
                           "valor_medio": _div(a["valor"], a["notas"]),
                           "media_notas": m["notas"] if m else None, "media_valor": m["valor"] if m else None,
                           "media_pct": m["pct"] if m else None})
        causas.sort(key=lambda x: (-x["valor"], -(x["media_valor"] or 0.0)))
        nomes = self._nomes_curtos()

        # as notas do mês
        movs = [m for m in base["por_mes"].get(i, ()) if m.origem == "devolucao" and familia(m.motivo) == "entrega"]
        por_nota: dict = {}
        for m in movs:
            x = por_nota.setdefault(chave_nota(m), {"m": m, "causas": defaultdict(float), "produtos": set(),
                                                    "valor": 0.0})
            x["causas"][causa(m.motivo)] += m.valor
            x["produtos"].add(m.produto)
            x["valor"] += m.valor
        w6 = self._janela6(i)
        movs6 = [m for k in w6 for m in base["por_mes"].get(k, ())
                 if m.origem == "devolucao" and familia(m.motivo) == "entrega"]
        info = self._info_clientes({m.cliente for m in movs6})
        notas = []
        for x in por_nota.values():
            m = x["m"]
            notas.append({"numero": m.numero, "serie": m.serie, "emissao": m.emissao, "data": m.data,
                          "cliente": self._cliente(info, m.cliente), "vendedor": self._nome_vendedor(nomes, m.vendedor),
                          "id_vendedor": m.vendedor, "regiao": filtro(m.vendedor),
                          "causas": sorted(x["causas"], key=lambda c: -x["causas"][c]), "itens": len(x["produtos"]),
                          "valor": x["valor"]})
        notas.sort(key=lambda n: (-n["valor"], n["data"], n["cliente"]["nome"]))

        # por vendedor: só quem teve nota devolvida na entrega no mês
        com_nota = {m.vendedor for m in movs}
        com_venda = {vid for vid, v in base["venda"].get(i, {}).items() if v > _EPS}
        vendedores = []
        for vid in com_nota:
            a = self._recorte(base, [i], lambda v, vid=vid: v == vid)
            vendedores.append({"id": vid, "nome": self._nome_vendedor(nomes, vid), "regiao": filtro(vid),
                               "venda": a["venda"], "entregas": a["entregas"], "notas": a["entrega"]["notas"],
                               "por_100": a["entrega"]["por_100"], "valor": a["entrega"]["valor"],
                               "pct": a["entrega"]["pct"], "lancamento_notas": a["lancamento"]["notas"],
                               "lancamento_valor": a["lancamento"]["valor"]})
        vendedores.sort(key=lambda v: (-v["valor"], v["nome"].upper()))

        # clientes com 2 ou mais notas nos 6 meses até o escolhido
        por_cli: dict[int, dict] = {}
        for m in movs6:
            x = por_cli.setdefault(m.cliente, {"notas": set(), "valor": 0.0, "causas": defaultdict(set),
                                               "meses": set(), "ultima": m.data, "vendedores": defaultdict(float)})
            nota = chave_nota(m)
            x["notas"].add(nota)
            x["valor"] += m.valor
            x["causas"][causa(m.motivo)].add(nota)
            x["meses"].add(indice(m.data))
            x["ultima"] = max(x["ultima"], m.data)
            x["vendedores"][m.vendedor] += m.valor
        repetem = []
        for c, x in por_cli.items():
            if len(x["notas"]) < REPETE_MINIMO:
                continue
            vid = _principal(x["vendedores"])
            repetem.append({**self._cliente(info, c), "vendedor": self._nome_vendedor(nomes, vid), "id_vendedor": vid,
                            "notas": len(x["notas"]), "valor": x["valor"],
                            "causas": sorted(({"id": k, "notas": len(v)} for k, v in x["causas"].items()),
                                             key=lambda y: (-y["notas"], y["id"])),
                            "meses": [k in x["meses"] for k in w6], "ultima": x["ultima"]})
        repetem.sort(key=lambda r: (-r["notas"], -r["valor"], r["nome"]))
        return {"cartoes": {"atual": _sem_causas(atual), "media": _sem_causas(media)}, "causas_entrega": causas,
                "notas": notas, "vendedores_entrega": vendedores,
                "sem_nota": len(com_venda - com_nota), "repetem": repetem, "meses6": [_mes(k) for k in w6]}

    # --- aba No cliente ------------------------------------------------------------------------
    def _aba_cliente(self, i: int, base: dict, filtro) -> dict:
        cache = self.calc.cache
        cmp = self._meses_cmp(i)
        atual = self._recorte(base, [i])
        media = self._recorte(base, cmp) if cmp else None
        w6 = self._janela6(i)
        de6, ate = _inicio(w6[0]), _fim(i)
        movs6 = [m for k in w6 for m in base["por_mes"].get(k, ()) if familia(m.motivo) == "cliente"]
        k_sql = "CAST(year(data) * 12 + month(data) - 1 AS INTEGER)"
        # a venda de cada produto (mês e 6 meses) e a de cada cliente (6 meses), do recorte
        vprod: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # valor e qtd no mês; nos 6 meses
        for k, vid, pid, valor, qtd in cache.consulta(
                f"SELECT {k_sql}, id_vendedor, id_produto, SUM(valor), SUM(quantidade) FROM vendas_clientes_itens "
                "WHERE tipocliente = 'CLIENTE' AND data BETWEEN ? AND ? GROUP BY 1, 2, 3", [de6, ate]):
            if filtro(vid):
                x = vprod[pid]
                x[2] += valor
                x[3] += qtd
                if k == i:
                    x[0] += valor
                    x[1] += qtd
        vcli: dict[int, float] = defaultdict(float)
        for vid, cli, valor in cache.consulta(
                "SELECT id_vendedor, id_cliente, SUM(valor) FROM vendas_clientes_itens WHERE tipocliente = 'CLIENTE' "
                "AND data BETWEEN ? AND ? GROUP BY 1, 2", [de6, ate]):
            if filtro(vid):
                vcli[cli] += valor
        venda6 = sum(v[2] for v in vprod.values())

        # produtos
        pprod: dict[int, dict] = {}
        for m in movs6:
            x = pprod.setdefault(m.produto, {"venc_qtd": 0.0, "venc": 0.0, "venc_qtd6": 0.0, "venc6": 0.0,
                                             "dan": 0.0, "dan6": defaultdict(float), "clientes6": set()})
            c = causa(m.motivo)
            no_mes = indice(m.data) == i
            if c == "vencido":
                x["venc_qtd6"] += m.qtd
                x["venc6"] += m.valor
                if no_mes:
                    x["venc_qtd"] += m.qtd
                    x["venc"] += m.valor
            else:
                x["dan6"][c] += m.valor
                if no_mes:
                    x["dan"] += m.valor
            x["clientes6"].add(m.cliente)
        iprod = self._info_produtos(set(pprod) | set(vprod))
        linhas: dict[str, dict] = {}

        def linha(pid):
            nome = nome_linha((iprod.get(pid) or {}).get("linha"))
            return linhas.setdefault(nome, {"linha": nome, "venda": 0.0, "venda6": 0.0, "perda": 0.0, "perda6": 0.0,
                                            "venc6": 0.0, "produtos": []})

        for pid, (v, _, v6, _) in vprod.items():  # a venda da linha inteira, mesmo dos produtos sem vencido nem danificado
            lin = linha(pid)
            lin["venda"] += v
            lin["venda6"] += v6
        for pid, x in pprod.items():
            p = iprod.get(pid) or {"nome": f"Produto {pid}", "unidade": None}
            v, q, v6, q6 = vprod.get(pid, [0.0, 0.0, 0.0, 0.0])
            dan6 = sum(x["dan6"].values())
            perda, perda6 = x["venc"] + x["dan"], x["venc6"] + dan6
            lin = linha(pid)
            lin["perda"] += perda
            lin["perda6"] += perda6
            lin["venc6"] += x["venc6"]
            lin["produtos"].append({
                "id": pid, "nome": nome_produto(p["nome"]), "unidade": p.get("unidade"),
                "venda": v, "venda_qtd": q, "venda6": v6, "venda_qtd6": q6,
                "venc_qtd": x["venc_qtd"], "venc": x["venc"], "pct_venc_qtd": _div(x["venc_qtd"], q),
                "venc_qtd6": x["venc_qtd6"], "venc6": x["venc6"], "pct_venc_qtd6": _div(x["venc_qtd6"], q6),
                "danificado": x["dan"], "danificado6": dan6,
                "danificado6_origem": {c: val for c, val in x["dan6"].items() if val > _EPS},
                "perda": perda, "perda6": perda6, "pct_perda6": _div(perda6, v6), "clientes6": len(x["clientes6"]),
            })
        produtos = []
        for lin in linhas.values():
            if not lin["produtos"]:
                continue
            lin["produtos"].sort(key=lambda p: (-p["perda6"], p["nome"]))
            lin.update(pct_perda=_div(lin["perda"], lin["venda"]), pct_perda6=_div(lin["perda6"], lin["venda6"]),
                       pct_venc6=_div(lin["venc6"], lin["venda6"]))
            produtos.append(lin)
        produtos.sort(key=lambda lin: (-lin["perda6"], lin["linha"]))

        # segmento e frequência de visita (6 meses)
        info = self._info_clientes(set(vcli) | {m.cliente for m in movs6})
        redes = {} if cache.sem_rede else dict(cache.consulta("SELECT id, rede FROM clientes_rede"))

        def cortes(chave_de) -> list[dict]:
            por: dict[str, dict] = {}
            for cli, valor in vcli.items():
                x = por.setdefault(chave_de(cli), {"venda": 0.0, "vencido": 0.0, "perda": 0.0, "compradores": 0,
                                                   "clientes_vencido": set()})
                x["venda"] += valor
                x["compradores"] += 1 if valor > _EPS else 0
            for m in movs6:
                x = por.setdefault(chave_de(m.cliente), {"venda": 0.0, "vencido": 0.0, "perda": 0.0, "compradores": 0,
                                                         "clientes_vencido": set()})
                x["perda"] += m.valor
                if causa(m.motivo) == "vencido":
                    x["vencido"] += m.valor
                    x["clientes_vencido"].add(m.cliente)
            return [{"nome": k, "venda": x["venda"], "vencido": x["vencido"], "pct_vencido": _div(x["vencido"], x["venda"]),
                     "perda": x["perda"], "pct_perda": _div(x["perda"], x["venda"]), "compradores": x["compradores"],
                     "clientes_vencido": len(x["clientes_vencido"])} for k, x in por.items()]

        segmentos = cortes(lambda c: (info.get(c) or {}).get("segmento") or SEM_SEGMENTO)
        segmentos.sort(key=lambda s: (s["nome"] == SEM_SEGMENTO, -s["venda"], s["nome"]))
        ordem_freq = {n: k for k, n in enumerate((*FREQUENCIAS.values(), OUTRA_REDE))}
        frequencias = sorted(cortes(lambda c: frequencia(redes.get(c))), key=lambda f: ordem_freq[f["nome"]])

        # danificado por origem
        danificados = []
        for c in DANIFICADOS:
            ms = [m for m in movs6 if causa(m.motivo) == c]
            por_prod: dict[int, float] = defaultdict(float)
            for m in ms:
                por_prod[m.produto] += m.valor
            top = sorted(por_prod.items(), key=lambda kv: -kv[1])[:3]
            danificados.append({"id": c, "valor": atual["causas"][c]["valor"], "valor6": sum(m.valor for m in ms),
                            "clientes6": len({m.cliente for m in ms}),
                            "produtos": [{"nome": nome_produto((iprod.get(p) or {}).get("nome") or f"Produto {p}"),
                                          "valor": v} for p, v in top]})

        # clientes (6 meses)
        nomes = self._nomes_curtos()
        por_cli: dict[int, dict] = {}
        for m in movs6:
            x = por_cli.setdefault(m.cliente, {"perda": 0.0, "vencido": 0.0, "mes": 0.0, "meses": set(),
                                               "produtos": defaultdict(float), "vendedores": defaultdict(float)})
            x["perda"] += m.valor
            if causa(m.motivo) == "vencido":
                x["vencido"] += m.valor
                x["meses"].add(indice(m.data))
            if indice(m.data) == i:
                x["mes"] += m.valor
            x["produtos"][m.produto] += m.valor
            x["vendedores"][m.vendedor] += m.valor
        clientes = []
        for c, x in por_cli.items():
            vid, pid = _principal(x["vendedores"]), _principal(x["produtos"])
            compra = vcli.get(c)
            clientes.append({**self._cliente(info, c), "vendedor": self._nome_vendedor(nomes, vid), "id_vendedor": vid,
                             "compra6": compra, "perda6": x["perda"], "vencido6": x["vencido"],
                             "danificado6": x["perda"] - x["vencido"], "pct6": _div(x["perda"], compra),
                             "meses": [k in x["meses"] for k in w6], "n_meses": len(x["meses"]),
                             "produto": nome_produto((iprod.get(pid) or {}).get("nome") or f"Produto {pid}"),
                             "perda_mes": x["mes"]})
        clientes.sort(key=lambda r: (-r["perda6"], r["nome"]))
        total6 = sum(r["perda6"] for r in clientes)
        metade = oitenta = None
        acumulado = 0.0
        for n, r in enumerate(clientes, 1):
            acumulado += r["perda6"]
            if metade is None and acumulado + _EPS >= total6 * 0.5:
                metade = n
            if oitenta is None and acumulado + _EPS >= total6 * 0.8:
                oitenta = n
        reincidentes = sum(1 for r in clientes if r["n_meses"] >= REINCIDENCIA_MINIMO)
        perda6_total = sum(m.valor for m in movs6)
        venc6_total = sum(m.valor for m in movs6 if causa(m.motivo) == "vencido")
        return {"cartoes": {"atual": _sem_causas(atual), "media": _sem_causas(media)},
                "seis_meses": {"venda": venda6, "perda": perda6_total, "pct_perda": _div(perda6_total, venda6),
                               "vencido": venc6_total, "pct_vencido": _div(venc6_total, venda6),
                               "clientes": len(clientes), "metade": metade, "oitenta": oitenta,
                               "reincidentes": reincidentes, "minimo_reincidencia": REINCIDENCIA_MINIMO},
                "produtos": produtos, "segmentos": segmentos, "frequencias": frequencias,
                "sem_rede": bool(cache.sem_rede), "danificados": danificados,
                "clientes_perda": clientes[:LIMITE_CLIENTES],
                "clientes_fora": {"n": max(len(clientes) - LIMITE_CLIENTES, 0),
                                  "perda6": sum(r["perda6"] for r in clientes[LIMITE_CLIENTES:])},
                "meses6": [_mes(k) for k in w6]}

    # --- aba Vendedores ------------------------------------------------------------------------
    def _aba_vendedores(self, i: int, base: dict, filtro) -> dict:
        cmp = self._meses_cmp(i)
        w6 = self._janela6(i)
        nomes = self._nomes_curtos()
        # reincidentes de vencido (3 ou mais dos 6 meses), pelo vendedor com mais vencido no cliente
        venc: dict[int, dict] = {}
        for k in w6:
            for m in base["por_mes"].get(k, ()):
                if causa(m.motivo) == "vencido":
                    x = venc.setdefault(m.cliente, {"meses": set(), "vendedores": defaultdict(float)})
                    x["meses"].add(k)
                    x["vendedores"][m.vendedor] += m.valor
        reinc: dict[int, int] = defaultdict(int)
        for x in venc.values():
            if len(x["meses"]) >= REINCIDENCIA_MINIMO:
                reinc[_principal(x["vendedores"])] += 1

        def linha(nome: str, a: dict, m: dict | None, n_reinc: int, **extra) -> dict:
            return {"nome": nome, **extra, "venda": a["venda"], "entregas": a["entregas"], "total": a["total"],
                    "pct": a["pct"], "entrega": a["entrega"]["valor"], "pct_entrega": a["entrega"]["pct"],
                    "notas": a["entrega"]["notas"], "lancamento_notas": a["lancamento"]["notas"],
                    "cliente": a["cliente"]["valor"], "pct_cliente": a["cliente"]["pct"],
                    "vencido": a["cliente"]["vencido"], "pct_vencido": a["cliente"]["pct_vencido"],
                    "clientes_vencido": a["cliente"]["clientes_vencido"], "compradores": a["compradores"],
                    "reincidentes": n_reinc, "media_pct": m["pct"] if m else None}

        ids = set(base["venda"].get(i, {})) | {m.vendedor for m in base["por_mes"].get(i, ())}
        vendedores = []
        for vid in ids:
            def ok(v, vid=vid):
                return v == vid
            a = self._recorte(base, [i], ok)
            if a["venda"] <= _EPS and a["total"] <= _EPS:
                continue
            vendedores.append(linha(self._nome_vendedor(nomes, vid), a, self._recorte(base, cmp, ok) if cmp else None,
                                    reinc.get(vid, 0), id=vid, regiao=filtro(vid)))
        # Nos terceirizados, quem vendeu sem nenhuma devolução (contas internas, venda a funcionário…) vira uma linha
        # só: os totais continuam com a venda deles.
        zeros = [v for v in vendedores if v["regiao"] == "TERC" and v["total"] <= _EPS]
        if len(zeros) > 1:
            ids_zeros = {v["id"] for v in zeros}
            vendedores = [v for v in vendedores if v["id"] not in ids_zeros]

            def ok_z(v):
                return v in ids_zeros
            vendedores.append(linha(f"Outros {len(zeros)} sem devolução", self._recorte(base, [i], ok_z),
                                    self._recorte(base, cmp, ok_z) if cmp else None, 0, id=None, regiao="TERC",
                                    agrupados=sorted(v["nome"] for v in zeros)))
        ordem = {r: k for k, r in enumerate(REGIOES)}
        vendedores.sort(key=lambda v: (ordem[v["regiao"]], v["id"] is None, -v["total"], v["nome"].upper()))
        regioes = []
        for rg in REGIOES:
            doa = [v for v in vendedores if v["regiao"] == rg]
            if not doa:
                continue

            def ok_r(v, rg=rg):
                return filtro(v) == rg
            n = sum(len(v["agrupados"]) if v.get("agrupados") else 1 for v in doa)
            regioes.append(linha(NOME_REGIAO[rg], self._recorte(base, [i], ok_r),
                                 self._recorte(base, cmp, ok_r) if cmp else None, sum(v["reincidentes"] for v in doa),
                                 id=rg, vendedores=n))
        total = linha("Total", self._recorte(base, [i]), self._recorte(base, cmp) if cmp else None,
                      sum(v["reincidentes"] for v in vendedores),
                      vendedores=sum(len(v["agrupados"]) if v.get("agrupados") else 1 for v in vendedores))
        return {"tabela": {"vendedores": vendedores, "regioes": regioes, "total": total},
                "parecer": self._parecer(i, filtro)}

    # --- o Parecer -----------------------------------------------------------------------------
    def _parecer(self, i: int, filtro) -> dict:
        """O bloco de cada vendedor com devolução no mês (regiões BA, ES e Terceirizados) e os rankings por tipo."""
        de, ate = _inicio(i), _fim(i)
        mov = [m for m in self._linhas(de, ate, filtro) if m.motivo in SECAO_DO_MOTIVO]
        clientes = {m.cliente for m in mov}
        fat_cli = self._fat_clientes(de, ate, clientes)
        info_cli = self._info_clientes(clientes)
        nomes_cli = {c: info_cli.get(c, {}).get("nome") or f"Cliente {c}" for c in clientes}
        fora = {m.produto for m in mov if m.produto not in _PRODUTO_PARECER}
        nomes_prod = {p: nome_bonito(x["nome"]) for p, x in self._info_produtos(fora).items()}
        nomes_erp = self.calc.nomes_erp()
        nomes = self._nomes_curtos()
        por_vendedor: dict[int, list[Mov]] = defaultdict(list)
        for m in mov:
            por_vendedor[m.vendedor].append(m)
        blocos = []
        for vid, ms in por_vendedor.items():
            secoes = [s for s in (self._secao(chave, titulo, motivos, tipo, ms, fat_cli, nomes_cli, nomes_prod)
                                  for chave, titulo, motivos, tipo in SECOES) if s]
            if secoes:
                blocos.append({"id": vid, "nome": self._nome_erp(nomes_erp, vid),
                               "curto": self._nome_vendedor(nomes, vid), "regiao": filtro(vid), "secoes": secoes})
        blocos.sort(key=lambda b: b["nome"].upper())
        regioes = [{"id": r, "nome": NOME_REGIAO[r], "titulo": TITULO_REGIAO[r], "capa": CAPA_REGIAO[r],
                    "vendedores": [b for b in blocos if b["regiao"] == r]} for r in REGIOES]
        return {"mes": _mes(i), "competencia": competencia(i), "regioes": [r for r in regioes if r["vendedores"]],
                "rankings": self._rankings(mov, nomes_erp, nomes_cli, filtro)}

    @staticmethod
    def _secao(chave: str, titulo: str, motivos: tuple, tipo: str, ms: list[Mov], fat_cli: dict, nomes_cli: dict,
               nomes_prod: dict) -> dict | None:
        linhas = [m for m in ms if m.motivo in motivos]
        if not linhas:
            return None
        if tipo == "simples":
            por: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
            for m in linhas:
                por[m.cliente][0] += m.qtd
                por[m.cliente][1] += m.valor
            itens = sorted(({"id_cliente": c, "cliente": nomes_cli[c], "qtd": q, "valor": v}
                            for c, (q, v) in por.items()), key=lambda r: (-r["valor"], r["cliente"]))
            secao = {"chave": chave, "titulo": titulo, "tipo": tipo, "linhas": itens,
                     "total": {"qtd": sum(r["qtd"] for r in itens), "valor": sum(r["valor"] for r in itens)}}
            if chave == "lancamento":
                secao["erros"] = len({(m.data, m.cliente) for m in linhas})
            return secao
        grupos: dict[tuple, dict[int, list[float]]] = {}
        for m in linhas:
            k = _PRODUTO_PARECER.get(m.produto) or (len(PRODUTOS_PARECER), nomes_prod.get(m.produto)
                                                     or f"Produto {m.produto}", LIMITE_FORA_DA_LISTA)
            x = grupos.setdefault(k, {}).setdefault(m.cliente, [0.0, 0.0])
            x[0] += m.qtd
            x[1] += m.valor
        produtos = []
        for (_, nome, limite), clis in sorted(grupos.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            itens = [{"id_cliente": c, "cliente": nomes_cli[c], "qtd": q, "valor": v, "fat": fat_cli.get(c),
                      "pct": _div(v, fat_cli.get(c))} for c, (q, v) in clis.items() if q + _EPS >= limite]
            if not itens:
                continue
            itens.sort(key=lambda r: (-r["qtd"], -r["valor"], r["cliente"]))
            produtos.append({"nome": nome, "limite": limite, "linhas": itens, "abaixo": len(clis) - len(itens),
                             "total": {"qtd": sum(r["qtd"] for r in itens), "valor": sum(r["valor"] for r in itens)}})
        alerta = []
        if chave == "vencido":
            por_cli: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
            for m in linhas:
                por_cli[m.cliente][0] += m.qtd
                por_cli[m.cliente][1] += m.valor
            for c, (vol, val) in por_cli.items():
                fat = fat_cli.get(c)
                if em_alerta(vol, val, fat):
                    alerta.append({"id_cliente": c, "cliente": nomes_cli[c], "volume": vol, "valor": val, "fat": fat,
                                   "pct": _div(val, fat)})
            alerta.sort(key=lambda r: (r["pct"] is None, -(r["pct"] or 0.0), -r["volume"], r["cliente"]))
        if not produtos and not alerta:
            return None
        return {"chave": chave, "titulo": titulo, "tipo": tipo, "produtos": produtos, "alerta": alerta}

    def _rankings(self, mov: list[Mov], nomes_erp: dict, nomes_cli: dict, filtro) -> list[dict]:
        """Os rankings do fim do Parecer, sobre todas as linhas do mês (sem o limite de volume dos produtos)."""
        secoes = {s[0]: s for s in SECOES}
        saida = []
        for chave in ORDEM_RANKINGS:
            _, titulo, motivos, _ = secoes[chave]
            linhas = [m for m in mov if m.motivo in motivos]
            if not linhas:
                continue
            nome = titulo.replace("Devolução – ", "")
            if chave in RANKINGS_CLIENTE:
                por: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0.0])
                for m in linhas:
                    por[(m.cliente, m.vendedor)][0] += m.qtd
                    por[(m.cliente, m.vendedor)][1] += m.valor
                itens = [{"cliente": nomes_cli[c], "vendedor": self._nome_erp(nomes_erp, v), "volume": q, "valor": val}
                         for (c, v), (q, val) in por.items()]
            else:
                pv: dict[int, dict] = defaultdict(lambda: {"volume": 0.0, "valor": 0.0, "erros": set()})
                for m in linhas:
                    pv[m.vendedor]["volume"] += m.qtd
                    pv[m.vendedor]["valor"] += m.valor
                    pv[m.vendedor]["erros"].add((m.data, m.cliente))
                itens = [{"vendedor": self._nome_erp(nomes_erp, v), "regiao": NOME_REGIAO[filtro(v)],
                          "volume": x["volume"], "valor": x["valor"], "erros": len(x["erros"])} for v, x in pv.items()]
            itens.sort(key=lambda r: (-r["valor"], r.get("cliente") or r["vendedor"]))
            saida.append({"chave": chave, "titulo": f"Ranking – {nome}",
                          "por": "cliente" if chave in RANKINGS_CLIENTE else "vendedor",
                          "erros": chave == "lancamento", "linhas": itens})
        return saida

    # --- o Parecer em PDF ----------------------------------------------------------------------
    def arquivo(self, mes: str | None = None, tipo: str | None = None, vendedor=None, regiao: str | None = None,
                permitidos: set[int] | None = None, equipes: set[str] | None = None) -> tuple[bytes, str, str]:
        """O Parecer do mês com o acesso de quem baixa: tipo vendedor (um vendedor), regiao (BA, ES ou TERC), geral (BA e
        ES num documento) ou todos (um zip com as pastas de sempre). Devolve (conteúdo, nome do arquivo, tipo)."""
        tipo = tipo or "geral"
        if tipo not in TIPOS_ARQUIVO:
            raise ValueError(f"tipo de arquivo desconhecido: {tipo}")
        self._conferir()
        i, _ = self._escolher_mes(mes)
        regras = self.calc.regras()
        dados = self._parecer(i, self._filtro(regras, permitidos, equipes))
        if not dados["regioes"]:
            raise ValueError(f"não há devoluções para o Parecer de {rotulo_mes(i)} no seu acesso")
        comp = competencia(i)
        sufixo = f"{MESES[i % 12].capitalize()}-{i // 12}"
        rankings = dados["rankings"]
        regioes = {r["id"]: r for r in dados["regioes"]}

        def doc_vendedor(r: dict, b: dict) -> bytes:
            onde = "Terceirizados" if r["id"] == "TERC" else f"Região {r['nome']}"
            return parecer_pdf.documento(comp, f"Vendedor: {b['nome']} ({onde})", [{**r, "vendedores": [b]}], rankings)

        if tipo == "vendedor":
            try:
                vid = int(vendedor)
            except (TypeError, ValueError):
                raise ValueError("escolha o vendedor do Parecer") from None
            for r in dados["regioes"]:
                for b in r["vendedores"]:
                    if b["id"] == vid:
                        return (doc_vendedor(r, b), f"Parecer Devoluções {sufixo} {nome_de_arquivo(b['curto'])}.pdf",
                                parecer_pdf.TIPO)
            raise ValueError(f"este vendedor não tem devolução no Parecer de {rotulo_mes(i)} (ou não é do seu acesso)")
        if tipo == "regiao":
            if regiao not in REGIOES:
                raise ValueError("escolha a região do Parecer: BA, ES ou TERC")
            if regiao not in regioes:
                raise ValueError(f"não há devoluções de {NOME_REGIAO[regiao]} no Parecer de {rotulo_mes(i)} "
                                 "(ou a região não é do seu acesso)")
            r = regioes[regiao]
            return (parecer_pdf.documento(comp, r["capa"], [r], rankings),
                    f"Parecer Devoluções {sufixo} {r['nome']}.pdf", parecer_pdf.TIPO)
        principais = [regioes[r] for r in ("BA", "ES") if r in regioes] or list(regioes.values())
        geral = (f"Parecer Devoluções {sufixo}.pdf", parecer_pdf.documento(comp, None, principais, rankings))
        if tipo == "geral":
            return geral[1], geral[0], parecer_pdf.TIPO
        arquivos = [geral]
        for r in dados["regioes"]:
            pasta = PASTA_REGIAO[r["id"]]
            arquivos.append((f"{pasta}/Parecer Devoluções {sufixo} {r['nome']}.pdf",
                             parecer_pdf.documento(comp, r["capa"], [r], rankings)))
            if r["id"] == "TERC":  # os terceirizados têm só o documento da região, como antes
                continue
            usados: set[str] = set()
            for b in r["vendedores"]:
                base = nome_de_arquivo(b["curto"])
                nome, n = base, 2
                while nome.upper() in usados:
                    nome, n = f"{base} ({n})", n + 1
                usados.add(nome.upper())
                arquivos.append((f"{pasta}/Parecer Devoluções {sufixo} {nome}.pdf", doc_vendedor(r, b)))
        return parecer_pdf.zip_arquivos(arquivos), f"Parecer Devoluções {sufixo}.zip", parecer_pdf.TIPO_ZIP

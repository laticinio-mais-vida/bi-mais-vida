"""Dados do Serasa (página Reavaliação de Crédito): quem analisa o crédito de um cliente sobe o PDF do "Relato – Pessoa
Jurídica" e o painel grava só o que interessa ao crédito: a data de fundação, o score (com a probabilidade de
inadimplência e o risco), o histórico de pagamento comercial (títulos por faixa de atraso e a pontualidade em R$) e as
anotações negativas (tipo, quantidade e valor). O PDF é lido na memória e descartado: o CPF dos sócios e o resto do
relatório não ficam no painel.

- ler_relato: o PDF -> os campos, sem banco. O relatório vem do Chrome, com texto de verdade (sem OCR nem IA). A ordem
  das linhas é a que a pypdf tira dele; os testes usam um texto do mesmo formato.
- Cada envio é uma linha nova na tabela credito_serasa (migração 038) e não muda depois. Um engano se corrige excluindo
  (quem enviou ou um administrador); a linha fica guardada (excluido_em). O mesmo PDF de novo para o cliente não grava
  outra vez.
- A idade dos dados conta da data em que o Serasa emitiu o relatório (pode chegar hoje um PDF antigo); passando da
  validade das regras do crédito (ConfigCredito, bi/reanalise.py), a página avisa que está desatualizado.
- Só no site (ativo), como as reanálises. O último envio entra no retrato de cada reanálise registrada.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import logging
import re
import unicodedata

from .acesso import eh_admin
from .banco import hora
from .conversas import NaoEncontrada

log = logging.getLogger("bi")

AVISO_PC = ("Os dados do Serasa ficam no site (bi.maisvida.cloud), junto com as reanálises: envie e consulte por lá.")
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGINAS = 20
MAX_LISTA = 50
VALIDADE_PADRAO = 90  # dias (as regras do crédito mudam)
VERSAO = 1  # o formato de `dados`; sobe quando uma chave muda de sentido ou sai

# As faixas do histórico de pagamento: chave, o rótulo no PDF (sem acento) e o nome na página.
FAIXAS = (("pontual", "PONTUAL", "Pontual"), ("8_15", "8-15", "8 a 15 dias"), ("16_30", "16-30", "16 a 30 dias"),
          ("31_60", "31-60", "31 a 60 dias"), ("mais_60", "+60", "Mais de 60 dias"), ("a_vista", "A VISTA", "À vista"))
TOTAL_MES = ("total_mes", "TOTAL MES", "Total do mês")  # só na pontualidade em R$
# As anotações negativas: chave, o rótulo no PDF (expressão sem acento) e o nome na página.
ANOTACOES = (
    ("pefin", r"PENDENCIAS COMERCIAIS(?: \(PEFIN\))?", "Pendências comerciais (PEFIN)"),
    ("refin", r"PENDENCIAS BANCARIAS(?: \(REFIN\))?", "Pendências bancárias (REFIN)"),
    ("dividas_vencidas", r"DIVIDAS VENCIDAS", "Dívidas vencidas"),
    ("protestos", r"PROTESTOS", "Protestos"),
    ("cheques", r"CHEQUES SEM FUNDOS(?: \(BACEN\))?", "Cheques sem fundos"),
    ("acoes_judiciais", r"ACOES JUDICIAIS", "Ações judiciais"),
    ("falencias", r"FALENCIAS(?:,? CONCORDATAS E RECUPERACOES JUDICIAIS)?", "Falências e recuperações judiciais"),
)
_ESCALA = {"MIL": 1e3, "MI": 1e6, "MILHAO": 1e6, "MILHOES": 1e6, "BI": 1e9, "BILHAO": 1e9, "BILHOES": 1e9}
_NUMERO = r"(\d+(?:[.,]\d+)*)\s*(MIL|MILHAO|MILHOES|MI|BILHAO|BILHOES|BI)?"
_CNPJ = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
_REAIS = re.compile(r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})")
# Palavras que não ajudam a reconhecer a empresa pelo nome (tipo da sociedade, preposições).
_SEM_PESO = {"LTDA", "EPP", "ME", "MEI", "EIRELI", "SA", "S", "A", "CIA", "E", "DE", "DA", "DO", "DAS", "DOS", "EM"}


# --- leitura do PDF ----------------------------------------------------------------------
def _sem_acento(texto: str) -> str:
    """Maiúsculas sem acento e com os espaços juntos: para achar os rótulos do relatório."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().upper()


def _limpar(texto: str) -> str:
    """Tira os ícones (caracteres de uso privado das fontes de ícones) e os espaços das pontas."""
    return re.sub(r"[-]", "", unicodedata.normalize("NFKC", texto)).strip()


def _numero(texto: str, decimal_virgula: bool = True) -> float:
    """"6,5" -> 6.5; "1.000" -> 1000; "91.0" -> 91.0 (decimal_virgula=False: o ponto é o decimal)."""
    if decimal_virgula and "," in texto:
        return float(texto.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", texto) and decimal_virgula:
        return float(texto.replace(".", ""))
    return float(texto.replace(",", "."))


def intervalo(texto: str | None) -> dict | None:
    """Uma faixa do Serasa em quantidade ou R$: "200 A 250" -> 200 a 250; "6 MIL A 6,5 MIL" -> 6000 a 6500; "300" ->
    300 a 300; "-" -> sem valor (de e ate None). None se não for um intervalo."""
    if texto is None:
        return None
    bruto = texto.strip()
    t = _sem_acento(bruto)
    if t in ("", "-", "—", "–"):
        return {"texto": "-", "de": None, "ate": None}
    m = re.fullmatch(rf"{_NUMERO}(?:\s*A\s*{_NUMERO})?", t)
    if not m:
        return None
    de = _numero(m.group(1)) * _ESCALA.get(m.group(2) or "", 1)
    ate = _numero(m.group(3)) * _ESCALA.get(m.group(4) or "", 1) if m.group(3) else de
    return {"texto": bruto, "de": de, "ate": ate}


def percentual(texto: str | None) -> dict | None:
    """"91.0% e 93.0%" ou "93% - 95%" -> 0,91 a 0,93; "2,12%" -> 0,0212 a 0,0212. None se não for percentual."""
    if texto is None:
        return None
    t = _sem_acento(texto)
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*%(?:\s*(?:E|-|–|A)\s*(\d+(?:[.,]\d+)?)\s*%)?", t)
    if not m:
        return None
    de = float(m.group(1).replace(",", ".")) / 100
    ate = float(m.group(2).replace(",", ".")) / 100 if m.group(2) else de
    return {"texto": texto.strip(), "de": round(de, 6), "ate": round(ate, 6)}


def _data(texto: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(texto, "%d/%m/%Y").date()
    except ValueError:
        return None


def texto_do_pdf(conteudo: bytes) -> str:
    """O texto das páginas do PDF. Arquivo que não é PDF, grande demais ou que não abre -> ValueError."""
    if not conteudo:
        raise ValueError("escolha o PDF do Serasa")
    if len(conteudo) > MAX_BYTES:
        raise ValueError(f"o arquivo passou de {MAX_BYTES // (1024 * 1024)} MB")
    if not conteudo.lstrip()[:5].startswith(b"%PDF"):
        raise ValueError("o arquivo não é um PDF")
    from pypdf import PdfReader  # só aqui: o resto do painel não precisa dela
    from pypdf.errors import PdfReadError
    try:
        leitor = PdfReader(io.BytesIO(conteudo))
        if leitor.is_encrypted:
            raise ValueError("o PDF tem senha; baixe de novo sem senha")
        if len(leitor.pages) > MAX_PAGINAS:
            raise ValueError(f"o PDF tem mais de {MAX_PAGINAS} páginas: não parece o Relato do Serasa")
        return "\n".join(p.extract_text() or "" for p in leitor.pages)
    except (PdfReadError, KeyError, TypeError, AttributeError, IndexError, OSError) as e:
        log.info("PDF do Serasa que não abriu: %s", e)
        raise ValueError("não deu para abrir o PDF; baixe o relatório de novo") from None


def ler_relato(conteudo: bytes) -> dict:
    """Os campos do Relato PJ do Serasa a partir do PDF (ler_texto)."""
    return ler_texto(texto_do_pdf(conteudo))


def ler_texto(texto: str) -> dict:
    """Os campos do Relato PJ a partir do texto do PDF. Sem o CNPJ, a data de emissão ou a tabela das anotações
    negativas -> ValueError (não é o relatório). A fundação, o score e o histórico de pagamento podem faltar (empresa
    sem histórico): ficam None ou vazios, e a parte entra em "faltou"."""
    linhas = [x for x in (_limpar(l) for l in (texto or "").splitlines()) if x]
    if not linhas:
        raise ValueError("o PDF não tem texto (parece escaneado): baixe o relatório do Serasa em PDF de novo")
    norm = [_sem_acento(x) for x in linhas]
    tudo = "\n".join(norm)

    def depois(rotulo: str) -> str | None:
        """A linha logo depois da linha que é só o rótulo."""
        for i, x in enumerate(norm[:-1]):
            if x == rotulo:
                return linhas[i + 1]
        return None

    cnpj = None
    for i, x in enumerate(norm[:-1]):
        if x == "CNPJ" and _CNPJ.fullmatch(linhas[i + 1].strip()):
            cnpj = linhas[i + 1].strip()
            break
    m = re.search(r"EMITIDO EM:?\s*(\d{2}/\d{2}/\d{4})(?:\s*(?:AS\s*)?(\d{1,2}:\d{2}))?", tudo)
    emitido = None
    if m:
        dia = _data(m.group(1))
        if dia:
            hh, mm = (int(v) for v in (m.group(2) or "0:00").split(":"))
            emitido = dt.datetime.combine(dia, dt.time(min(hh, 23), min(mm, 59)))
    inicio_anotacoes = next((i for i, x in enumerate(norm) if x.startswith("ANOTACOES NEGATIVAS")), None)
    faltando = [nome for nome, v in (("o CNPJ", cnpj), ("a data de emissão", emitido),
                                     ("as anotações negativas", inicio_anotacoes)) if v is None]
    if faltando:
        raise ValueError(f"não parece o Relato PJ do Serasa: faltou {' e '.join(faltando)}")

    fundacao_txt = depois("DATA DE FUNDACAO")
    fundacao = _data(fundacao_txt.strip()) if fundacao_txt else None
    saida = {
        "versao": VERSAO, "cnpj": cnpj, "razao_social": depois("RAZAO SOCIAL"),
        "nome_fantasia": depois("NOME FANTASIA"), "emitido_em": emitido, "fundacao": fundacao,
        "score": _score(norm, linhas, tudo), "faixas": _faixas(norm, linhas), "pontualidade": _pontualidade(norm, linhas),
        "anotacoes": _anotacoes(norm, linhas, inicio_anotacoes),
    }
    saida["faltou"] = [nome for nome, v in (("data de fundação", fundacao), ("score", saida["score"]),
                                            ("títulos por faixa", saida["faixas"]),
                                            ("pontualidade em R$", saida["pontualidade"])) if not v]
    return saida


_FIM_DO_AVISO = ("PRATICAS DE MERCADO", "PROBABILIDADE DE INADIMPLENCIA", "RISCO DE CREDITO", "INTERPRETACAO",
                 "LEGENDA", "HISTORICO DE PAGAMENTO")


def _score(norm: list[str], linhas: list[str], tudo: str) -> dict | None:
    """O score, a probabilidade de inadimplência, o risco e o aviso da caixa vermelha abaixo do número, quando ela não
    traz a probabilidade (ex.: "DEFAULT - DIVIDA VENCIDA COM INSTITUICAO FINANCEIRA HA MAIS DE 90 DIAS")."""
    m = re.search(r"SERASA SCORE[^\n]*\n(?:[^\n]*\n){0,3}?\s*(\d{1,4})\s*(?:\n\s*)?DE\s*1\.?000\b", tudo)
    if not m or int(m.group(1)) > 1000:
        return None
    p = re.search(r"PROBABILIDADE DE INADIMPLENCIA:?\s*\n?\s*(\d+(?:[.,]\d+)?)\s*%", tudo)
    risco = None
    for i, x in enumerate(norm[:-1]):
        if x == "RISCO DE CREDITO":
            risco = linhas[i + 1]
            break
    # A caixa vermelha: as linhas entre "de 1000" e o quadro das práticas de mercado (no máximo 4).
    aviso = []
    inicio = next((i for i, x in enumerate(norm) if x.startswith("SERASA SCORE")), None)
    fim_numero = next((i for i in range(inicio, min(inicio + 6, len(norm))) if re.search(r"DE\s*1\.?000$", norm[i])),
                      None) if inicio is not None else None
    if fim_numero is not None:
        for i in range(fim_numero + 1, min(fim_numero + 5, len(norm))):
            if norm[i].startswith(_FIM_DO_AVISO):
                break
            aviso.append(linhas[i])
    alerta = " ".join(aviso)[:300] or None
    return {"valor": int(m.group(1)), "probabilidade": round(float(p.group(1).replace(",", ".")) / 100, 6) if p else None,
            "risco": risco, "alerta": alerta}


def _secao(norm: list[str], titulo: str) -> range | None:
    """As linhas de uma parte do histórico de pagamento: do título até o próximo título."""
    inicio = next((i for i, x in enumerate(norm) if titulo in x), None)
    if inicio is None:
        return None
    fim = next((i for i in range(inicio + 1, len(norm))
                if norm[i].startswith(("HISTORICO DE PAGAMENTO", "ANOTACOES NEGATIVAS", "QUADRO SOCIAL", "CONSULTAS"))),
               len(norm))
    return range(inicio + 1, fim)


def _por_faixa(norm: list[str], linhas: list[str], trecho: range, rotulos: dict[str, tuple]) -> dict[str, list[str]]:
    """As linhas que vêm depois do rótulo de cada faixa, até o rótulo seguinte (as de antes do primeiro, como os números
    do eixo do gráfico, ficam fora)."""
    grupos, atual = {}, None
    for i in trecho:
        if norm[i] in rotulos:
            atual = rotulos[norm[i]][0]
            grupos[atual] = []
        elif atual:
            grupos[atual].append(linhas[i])
    return grupos


def _faixas(norm: list[str], linhas: list[str]) -> list[dict]:
    """Títulos por faixa: a quantidade e o % dos títulos de cada faixa de atraso."""
    trecho = _secao(norm, "TITULOS POR FAIXA")
    if trecho is None:
        return []
    grupos = _por_faixa(norm, linhas, trecho, {r: (k, n) for k, r, n in FAIXAS})
    saida = []
    for chave, _, nome in FAIXAS:
        valores = grupos.get(chave)
        if valores is None:
            continue
        pct = next((p for p in map(percentual, valores) if p), None)
        qtd = next((q for v in valores if not percentual(v) and (q := intervalo(v))), None)
        saida.append({"chave": chave, "rotulo": nome, "quantidade": qtd, "percentual": pct})
    return saida


def _pontualidade(norm: list[str], linhas: list[str]) -> list[dict]:
    """Pontualidade (resumo): o total e o médio em R$ e o % de cada faixa, e o total do mês."""
    trecho = _secao(norm, "PONTUALIDADE (RESUMO)")
    if trecho is None:
        return []
    todas = (*FAIXAS, TOTAL_MES)
    grupos = _por_faixa(norm, linhas, trecho, {r: (k, n) for k, r, n in todas})
    saida = []
    for chave, _, nome in todas:
        valores = grupos.get(chave)
        if valores is None:
            continue
        x = {"chave": chave, "rotulo": nome, "total": None, "medio": None, "percentual": None}
        for v in valores:
            m = re.match(r"\s*(TOTAL|MEDIO)\s*:\s*(.*)$", _sem_acento(v))
            if m:
                bruto = v.split(":", 1)[1]
                x["total" if m.group(1) == "TOTAL" else "medio"] = intervalo(bruto)
            elif x["percentual"] is None:
                x["percentual"] = percentual(v)
        saida.append(x)
    return saida


def _anotacoes(norm: list[str], linhas: list[str], inicio: int) -> list[dict]:
    """A tabela das anotações negativas: cada tipo com a quantidade e o valor total ("NÃO CONSTAM OCORRÊNCIAS" = 0 e
    R$ 0). Sem a linha do tipo na tabela, vale o quadro de detalhe dele ("NÃO CONSTAM" logo abaixo do título); sem
    nada que dê para ler, quantidade e valor None (a página manda conferir no PDF), com o texto que veio."""
    saida = []
    for chave, rotulo, nome in ANOTACOES:
        x = {"chave": chave, "rotulo": nome, "quantidade": None, "valor": None, "texto": None}
        for i in range(inicio + 1, len(norm)):
            m = re.fullmatch(rf"{rotulo}\s+(?!\()(.+)", norm[i])  # "(PEFIN)" sozinho é o título do quadro
            if not m:
                continue
            resto = m.group(1).strip()
            # a mesma parte da linha original, sem o rótulo (tirar acento não muda a quantidade de palavras)
            x["texto"] = " ".join(linhas[i].split()[len(norm[i][:m.start(1)].split()):]) or resto
            if "NAO CONSTA" in resto:
                x["quantidade"], x["valor"] = 0, 0.0
            else:
                q = re.match(r"(\d+)\b", resto)
                valores = _REAIS.findall(resto)
                if q:
                    x["quantidade"] = int(q.group(1))
                if valores:
                    x["valor"] = _numero(valores[-1])
            break
        else:  # o quadro de detalhe do tipo
            for i in range(inicio + 1, len(norm) - 1):
                if re.fullmatch(rotulo, norm[i]) and "NAO CONSTA" in norm[i + 1]:
                    x["quantidade"], x["valor"], x["texto"] = 0, 0.0, linhas[i + 1]
                    break
        saida.append(x)
    return saida


# --- o nome do PDF contra o do cadastro ------------------------------------------------------
def _palavras(nome: str | None) -> frozenset:
    return frozenset(p for p in re.split(r"[^A-Z0-9]+", _sem_acento(nome or "")) if p and p not in _SEM_PESO)


def mesma_empresa(do_pdf: list[str | None], do_cadastro: list[str | None]) -> bool:
    """O relatório parece ser do cliente: as palavras de um nome do PDF (razão social ou fantasia, sem LTDA, EPP…) estão
    todas num nome do cadastro, ou o contrário."""
    a = [p for p in map(_palavras, do_pdf) if p]
    b = [p for p in map(_palavras, do_cadastro) if p]
    return any(x <= y or y <= x for x in a for y in b)


# --- a gravação ------------------------------------------------------------------------------
def _cliente(valor) -> int:
    try:
        cliente = int(valor)
    except (TypeError, ValueError):
        raise ValueError("escolha um cliente") from None
    if cliente <= 0:
        raise ValueError("escolha um cliente")
    return cliente


def _json(d: dict) -> dict:
    """Os campos de ler_relato que vão para a coluna dados (as datas e o CNPJ ficam em colunas próprias)."""
    return {k: d[k] for k in ("versao", "nome_fantasia", "score", "faixas", "pontualidade", "anotacoes", "faltou")}


CAMPOS = ("id", "id_cliente", "cliente", "cnpj", "razao_social", "emitido_em", "fundacao", "score", "dados",
          "enviado_em", "enviado_por", "enviado_por_nome")


class DadosSerasa:
    """Os dados do Serasa de cada cliente, na tabela credito_serasa. ativo: o site, que grava e lê; no PC (False) a
    página só avisa que eles ficam no site. config: as regras do crédito (a validade dos dados)."""

    def __init__(self, banco, credito, ativo: bool, config=None):
        self.banco = banco
        self.credito = credito
        self.ativo = ativo
        self.config = config

    def validade(self) -> int:
        return self.config.atual()["serasa_validade_dias"] if self.config else VALIDADE_PADRAO

    def _linhas(self, con, cliente: int, limite: int = MAX_LISTA) -> list[dict]:
        """Os envios do cliente (sem os excluídos), da emissão mais recente para a mais antiga."""
        return [dict(zip(CAMPOS, r)) for r in con.execute(
            f"SELECT {', '.join(CAMPOS)} FROM credito_serasa WHERE id_cliente = %s AND excluido_em IS NULL "
            "ORDER BY emitido_em DESC, id DESC LIMIT %s", [cliente, limite]).fetchall()]

    @staticmethod
    def _item(r: dict, usuario: dict, validade: int, hoje: dt.date) -> dict:
        d = r["dados"]
        idade = (hoje - r["emitido_em"].date()).days
        return {
            "id": r["id"], "cnpj": r["cnpj"], "razao_social": r["razao_social"], "nome_fantasia": d.get("nome_fantasia"),
            "emitido_em": r["emitido_em"].isoformat(timespec="minutes"), "enviado_em": hora(r["enviado_em"]),
            "enviado_por": r["enviado_por_nome"] or "usuário excluído",
            "pode_excluir": eh_admin(usuario) or r["enviado_por"] == usuario["id"],
            "idade_dias": idade, "desatualizado": idade > validade,
            "fundacao": r["fundacao"].isoformat() if r["fundacao"] else None,
            "score": d.get("score"), "faixas": d.get("faixas") or [], "pontualidade": d.get("pontualidade") or [],
            "anotacoes": d.get("anotacoes") or [], "faltou": d.get("faltou") or [],
        }

    def listar(self, cliente, usuario: dict) -> dict:
        """O envio mais recente do cliente (pela data de emissão) e os anteriores, para a página."""
        cliente = _cliente(cliente)
        if not self.ativo:
            return {"ativo": False, "aviso": AVISO_PC, "atual": None, "anteriores": []}
        validade, hoje = self.validade(), dt.date.today()
        with self.banco.conexao() as con:
            itens = [self._item(r, usuario, validade, hoje) for r in self._linhas(con, cliente)]
        return {"ativo": True, "aviso": None, "validade_dias": validade, "atual": itens[0] if itens else None,
                "anteriores": itens[1:]}

    def _nomes_do_cadastro(self, cliente: int) -> list[str | None]:
        nomes = [self.credito.cadastro(cliente)["nome"]]  # cliente que não existe -> ValueError
        cache = self.credito.cache
        if not cache.sem_detalhe:
            linhas = cache.consulta("SELECT razao_social FROM clientes_detalhes WHERE id = ?", [cliente])
            nomes += [linhas[0][0]] if linhas else []
        return nomes

    def enviar(self, usuario: dict, cliente, conteudo: bytes, confirmar: bool = False) -> dict:
        """Lê o PDF e grava os dados do Serasa do cliente. Se o nome do relatório não bate com o do cadastro, não grava e
        devolve {"confirmar": a pergunta} (a página pergunta e manda de novo com confirmar). O mesmo PDF de novo não
        grava outra vez (ja_existia). PDF que não é o Relato, ou cliente inválido -> ValueError. Devolve o id e a lista
        nova do cliente (listar)."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        cliente = _cliente(cliente)
        nomes = self._nomes_do_cadastro(cliente)
        d = ler_relato(conteudo)
        if not confirmar and not mesma_empresa([d["razao_social"], d["nome_fantasia"]], nomes):
            return {"confirmar": f"O PDF é de {d['razao_social'] or d['nome_fantasia'] or 'outra empresa'} "
                                 f"(CNPJ {d['cnpj']}); o cliente escolhido é {nomes[0]} (código {cliente}). "
                                 "Gravar mesmo assim?"}
        sha = hashlib.sha256(conteudo).hexdigest()
        score = (d["score"] or {}).get("valor")
        with self.banco.conexao() as con:
            linha = con.execute(
                "INSERT INTO credito_serasa (id_cliente, cliente, cnpj, razao_social, emitido_em, arquivo_sha256, "
                "fundacao, score, dados, enviado_por, enviado_por_nome) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
                "%s::jsonb, (SELECT id FROM usuarios WHERE id = %s), %s) "
                "ON CONFLICT (id_cliente, arquivo_sha256) WHERE excluido_em IS NULL DO NOTHING RETURNING id",
                [cliente, nomes[0], d["cnpj"], d["razao_social"], d["emitido_em"], sha, d["fundacao"], score,
                 json.dumps(_json(d), ensure_ascii=False), usuario["id"], usuario["nome"]]).fetchone()
            if linha is None:  # o mesmo PDF para o mesmo cliente
                id_ = con.execute("SELECT id FROM credito_serasa WHERE id_cliente = %s AND arquivo_sha256 = %s "
                                  "AND excluido_em IS NULL", [cliente, sha]).fetchone()[0]
                ja_existia = True
            else:
                id_, ja_existia = linha[0], False
        return {"id": id_, "ja_existia": ja_existia, **self.listar(cliente, usuario)}

    def excluir(self, usuario: dict, id_) -> dict:
        """Tira um envio da página e do retrato das próximas reanálises; a linha fica, com quem excluiu e quando. Só quem
        enviou ou um administrador. Não existe ou já saiu -> NaoEncontrada; de outra pessoa -> PermissionError."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        try:
            id_ = int(id_)
        except (TypeError, ValueError):
            raise NaoEncontrada("dados do Serasa não encontrados") from None
        with self.banco.conexao() as con:
            linha = con.execute("SELECT id_cliente, enviado_por FROM credito_serasa WHERE id = %s "
                                "AND excluido_em IS NULL FOR UPDATE", [id_]).fetchone()
            if linha is None:
                raise NaoEncontrada("dados do Serasa não encontrados; eles podem ter sido excluídos")
            if not eh_admin(usuario) and linha[1] != usuario["id"]:
                raise PermissionError("só quem enviou o PDF ou um administrador pode excluir estes dados do Serasa")
            con.execute("UPDATE credito_serasa SET excluido_em = now(), excluido_por = "
                        "(SELECT id FROM usuarios WHERE id = %s), excluido_por_nome = %s WHERE id = %s",
                        [usuario["id"], usuario["nome"], id_])
        return self.listar(linha[0], usuario)

    def ultimo(self, cliente: int) -> dict | None:
        """O envio mais recente do cliente, para o retrato de uma reanálise (None = nenhum, ou no PC)."""
        if not self.ativo:
            return None
        with self.banco.conexao() as con:
            linhas = self._linhas(con, int(cliente), 1)
        if not linhas:
            return None
        r, validade = linhas[0], self.validade()
        d, idade = r["dados"], (dt.date.today() - r["emitido_em"].date()).days

        def faixa(x: dict | None) -> dict | None:
            return None if x is None else {"de": x.get("de"), "ate": x.get("ate")}

        return {
            "id": r["id"], "emitido_em": r["emitido_em"].isoformat(timespec="minutes"),
            "enviado_em": hora(r["enviado_em"]), "idade_dias": idade, "desatualizado": idade > validade,
            "fundacao": r["fundacao"].isoformat() if r["fundacao"] else None, "score": d.get("score"),
            "faixas": [{"faixa": x["chave"], "quantidade": faixa(x.get("quantidade")),
                        "percentual": faixa(x.get("percentual"))} for x in d.get("faixas") or []],
            "pontualidade": [{"faixa": x["chave"], "total": faixa(x.get("total")), "medio": faixa(x.get("medio")),
                              "percentual": faixa(x.get("percentual"))} for x in d.get("pontualidade") or []],
            "anotacoes": [{"tipo": x["chave"], "quantidade": x.get("quantidade"), "valor": x.get("valor")}
                          for x in d.get("anotacoes") or []],
        }

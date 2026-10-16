"""Leitura das planilhas de metas (.xlsx) só com a biblioteca padrão.

Procura, em qualquer aba, a linha de cabeçalho com as colunas pedidas e lê as linhas seguintes pelo nome
da coluna. Células com fórmula usam o último valor calculado pelo Excel. Se a planilha estiver aberta ou
bloqueada, a última leitura boa (guardada em memória) continua valendo.
"""
from __future__ import annotations

import datetime as dt
import threading
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

COLUNAS_METAS = {
    "id_vendedor": "ID_VENDEDOR",
    "vendedor": "VENDEDOR",
    "meta_fat": "META FATURAMENTO",
    "meta_mus": "META MUSSARELA",
    "meta_out": "META OUTRAS LINHAS",
    "meta_cli": "META CLIENTE",
    "data": "DATA",
}

COLUNAS_METAS_PRODUTOS = {
    "data": "DATA",
    "id_vendedor": "ID_VENDEDOR",
    "vendedor": "VENDEDOR",
    "id_produto": "ID_PRODUTO",
    "produto": "PRODUTO",
    "meta_volume": "META VOLUME",
}


def _normaliza(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(texto.upper().replace("_", " ").split())


def _indice_coluna(ref: str) -> int:
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def _abas(z: zipfile.ZipFile):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    alvo = {r.get("Id"): r.get("Target") for r in rels.findall(f"{NS_PR}Relationship")}
    for aba in wb.find(f"{NS_M}sheets"):
        destino = alvo[aba.get(f"{NS_R}id")].lstrip("/")
        if not destino.startswith("xl/"):
            destino = "xl/" + destino
        yield aba.get("name"), destino


def _strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{NS_M}t")) for si in raiz.findall(f"{NS_M}si")]


def _linhas(z: zipfile.ZipFile, caminho: str, strings: list[str]):
    for linha in ET.fromstring(z.read(caminho)).find(f"{NS_M}sheetData"):
        celulas = {}
        for c in linha:
            tipo, v = c.get("t"), c.find(f"{NS_M}v")
            if tipo == "s" and v is not None:
                valor = strings[int(v.text)]
            elif tipo == "inlineStr":
                valor = "".join(t.text or "" for t in c.iter(f"{NS_M}t"))
            else:
                valor = v.text if v is not None else None
            if valor not in (None, ""):
                celulas[_indice_coluna(c.get("r"))] = valor
        yield celulas


def numero(valor) -> float:
    if valor in (None, ""):
        return 0.0
    try:
        return float(valor)
    except ValueError:
        return float(str(valor).replace(".", "").replace(",", "."))


def primeiro_dia_mes(valor) -> dt.date:
    """O Excel guarda datas como dias desde 30/12/1899; aceita também texto dd/mm/aaaa ou aaaa-mm-dd."""
    try:
        data = dt.date(1899, 12, 30) + dt.timedelta(days=int(float(valor)))
    except ValueError:
        texto = str(valor).strip()
        for formato in ("%d/%m/%Y", "%Y-%m-%d", "%m/%Y"):
            try:
                data = dt.datetime.strptime(texto[:10], formato).date()
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"data não reconhecida: {valor!r}")
    return data.replace(day=1)


def ler_tabela(arquivo: str | Path, colunas: dict[str, str]) -> list[dict]:
    """Devolve as linhas da primeira aba que tem todas as `colunas`, com as chaves do dicionário."""
    with zipfile.ZipFile(arquivo) as z:
        strings = _strings(z)
        for nome_aba, caminho in _abas(z):
            linhas = _linhas(z, caminho, strings)
            for celulas in linhas:
                cabecalho = {_normaliza(v): col for col, v in celulas.items()}
                if all(_normaliza(t) in cabecalho for t in colunas.values()):
                    break
            else:
                continue
            idx = {chave: cabecalho[_normaliza(titulo)] for chave, titulo in colunas.items()}
            return [{chave: celulas.get(i) for chave, i in idx.items()} for celulas in linhas]
    raise ValueError(f"nenhuma aba de {Path(arquivo).name} tem as colunas {', '.join(colunas.values())}")


def ler_metas(arquivo: str | Path) -> list[dict]:
    metas = []
    for r in ler_tabela(arquivo, COLUNAS_METAS):
        if not r["id_vendedor"] or not r["data"]:
            continue
        # O Power BI converte estas colunas para número inteiro (Int64) ao importar; arredondamos igual
        # (round do Python arredonda empates para o par, como o Power Query).
        metas.append({
            "mes": primeiro_dia_mes(r["data"]),
            "id_vendedor": int(numero(r["id_vendedor"])),
            "vendedor": str(r["vendedor"] or "").strip(),
            "meta_fat": float(round(numero(r["meta_fat"]))),
            "meta_mus": float(round(numero(r["meta_mus"]))),
            "meta_out": float(round(numero(r["meta_out"]))),
            "meta_cli": float(round(numero(r["meta_cli"]))),
        })
    return metas


def ler_metas_produtos(arquivo: str | Path) -> list[dict]:
    metas = []
    for r in ler_tabela(arquivo, COLUNAS_METAS_PRODUTOS):
        if not r["id_vendedor"] or not r["data"] or not r["id_produto"]:
            continue
        metas.append({
            "mes": primeiro_dia_mes(r["data"]),
            "id_vendedor": int(numero(r["id_vendedor"])),
            "vendedor": str(r["vendedor"] or "").strip(),
            "id_produto": int(numero(r["id_produto"])),
            "produto": str(r["produto"] or "").strip(),
            "meta_volume": numero(r["meta_volume"]),
        })
    return metas


class PlanilhaMonitorada:
    """Relê a planilha quando o arquivo muda; se a leitura falhar, mantém a última leitura boa."""

    def __init__(self, arquivo: str | Path, leitor):
        self.arquivo = Path(arquivo)
        self.leitor = leitor
        self._assinatura = None
        self._dados: list[dict] | None = None
        self.aviso: str | None = None
        self.versao = 0  # sobe a cada leitura nova (o Assistente refaz os dados dele quando muda)
        self._trava = threading.Lock()

    def dados(self) -> list[dict]:
        with self._trava:
            try:
                st = self.arquivo.stat()
                assinatura = (st.st_mtime_ns, st.st_size)
            except OSError as e:
                if self._dados is None:
                    raise RuntimeError(f"planilha não encontrada: {self.arquivo}") from e
                self.aviso = f"{self.arquivo.name} não foi encontrada; usando a última leitura."
                return self._dados
            if assinatura != self._assinatura or self._dados is None:
                try:
                    self._dados = self.leitor(self.arquivo)
                    self._assinatura = assinatura
                    self.versao += 1
                    self.aviso = None
                except (PermissionError, zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as e:
                    if self._dados is None:
                        raise RuntimeError(f"não foi possível ler {self.arquivo.name}: {e}") from e
                    self.aviso = f"{self.arquivo.name} está bloqueada ou com erro ({e}); usando a última leitura."
            return self._dados

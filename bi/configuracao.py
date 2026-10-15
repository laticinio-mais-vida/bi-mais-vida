"""Regras de negócio editáveis na página Configurações (gravadas em config_metas.json).

Os valores padrão reproduzem as fórmulas DAX do Power BI, para os números baterem com ele até alguém mudar.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import threading
from pathlib import Path

GRUPOS_PRODUTO = ("mussarela", "outras", "fora")
GRUPOS_VENDEDOR = ("ES", "BA", "EDIR", "OCULTO")

VISOES = {
    "es": {"titulo": "Metas ES", "grupos": ["ES"], "regiao": "ES", "tipo": "completa"},
    "ba": {"titulo": "Metas BA", "grupos": ["BA"], "regiao": "BA", "tipo": "faturamento"},
    "edir": {"titulo": "Metas Edir", "grupos": ["EDIR"], "regiao": "BA", "tipo": "faturamento"},
    "outras_es": {"titulo": "Outras Linhas ES", "grupos": ["ES"], "regiao": "ES", "tipo": "outras"},
    "produtos_ba": {"titulo": "Produtos BA", "grupos": ["BA", "EDIR"], "regiao": "BA", "tipo": "produtos"},
}

# --- Padrões vindos do Power BI -------------------------------------------------------------
_MUSSARELA_PBI = [32, 12175, 11989, 11928, 11988, 12189, 12548, 12552]
_CATEGORIAS_PBI = {
    "Bebida Láctea": [11469, 10354, 541, 5416, 5413, 10353, 3790, 3788, 3791, 10352, 4835, 2105],
    "Manteiga": [5754, 27, 26, 25],
    "Queijo Coalho": [9616, 5973],
    "Queijo Parmesão": [24, 4046],
    "Queijo Prato": [21],
    "Requeijão Cremoso": [11098, 9776],
    "Requeijão Bisnaga": [8991],
}
# Coluna ESTADO de dMetas: estes vendedores são BA, o resto é ES. EDIR tem página própria
# e GESSIMAR ficava de fora das duas páginas.
_VENDEDORES_PBI = {
    141: "BA", 111: "BA", 98: "BA", 145: "BA", 115: "BA", 109: "BA", 113: "BA", 143: "BA",
    147: "BA", 150: "BA", 152: "BA", 85: "EDIR", 139: "OCULTO",
    119: "ES", 153: "ES", 156: "ES", 151: "ES", 140: "ES", 126: "ES", 134: "ES", 124: "ES",
    149: "ES", 154: "ES", 157: "ES", 132: "ES", 128: "ES", 138: "ES", 146: "ES",
}
# Supervisor no ERP -> grupo, para vendedores novos que ainda não foram configurados.
SUPERVISOR_GRUPO = {7: "BA", 3: "ES"}


def padrao() -> dict:
    produtos = {str(p): {"grupo": "mussarela", "categoria": None} for p in _MUSSARELA_PBI}
    for categoria, ids in _CATEGORIAS_PBI.items():
        for p in ids:
            produtos[str(p)] = {"grupo": "outras", "categoria": categoria}
    return {
        "versao": 1,
        "produtos": produtos,
        "categorias": list(_CATEGORIAS_PBI),
        "vendedores": {str(k): v for k, v in _VENDEDORES_PBI.items()},
        "devolucoes": {"motivos": [1, 2, 5, 6, 7, 8, 9], "ignorar_canceladas": True},
        "produtos_equivalentes": {"3643": 11469},
        "calendario": {"sabado": {"ES": 0, "BA": 0}, "extras": []},
    }


def _valida(cfg: dict) -> dict:
    """Confere e normaliza o que veio da página; levanta ValueError com a explicação."""
    base = padrao()
    saida = {"versao": 1}

    categorias = [str(c).strip() for c in cfg.get("categorias", base["categorias"]) if str(c).strip()]
    if len(set(c.lower() for c in categorias)) != len(categorias):
        raise ValueError("há categorias repetidas")
    saida["categorias"] = categorias

    produtos = {}
    for pid, regra in (cfg.get("produtos") or {}).items():
        grupo = regra.get("grupo", "outras")
        if grupo not in GRUPOS_PRODUTO:
            raise ValueError(f"grupo inválido para o produto {pid}: {grupo}")
        categoria = regra.get("categoria") or None
        if categoria and categoria not in categorias:
            raise ValueError(f"categoria '{categoria}' do produto {pid} não existe")
        if grupo != "outras":
            categoria = None
        produtos[str(int(pid))] = {"grupo": grupo, "categoria": categoria}
    saida["produtos"] = produtos

    vendedores = {}
    for vid, grupo in (cfg.get("vendedores") or {}).items():
        if grupo not in GRUPOS_VENDEDOR:
            raise ValueError(f"grupo inválido para o vendedor {vid}: {grupo}")
        vendedores[str(int(vid))] = grupo
    saida["vendedores"] = vendedores

    dev = cfg.get("devolucoes") or base["devolucoes"]
    saida["devolucoes"] = {
        "motivos": sorted({int(m) for m in dev.get("motivos", [])}),
        "ignorar_canceladas": bool(dev.get("ignorar_canceladas", True)),
    }

    saida["produtos_equivalentes"] = {
        str(int(k)): int(v) for k, v in (cfg.get("produtos_equivalentes") or {}).items()
    }

    cal = cfg.get("calendario") or base["calendario"]
    sabado = {r: float((cal.get("sabado") or {}).get(r, 0)) for r in ("ES", "BA")}
    if any(not 0 <= v <= 1 for v in sabado.values()):
        raise ValueError("o peso do sábado deve ficar entre 0 e 1")
    extras = []
    for e in cal.get("extras") or []:
        data = dt.date.fromisoformat(str(e["data"])).isoformat()
        regiao = e.get("regiao", "TODAS")
        if regiao not in ("TODAS", "ES", "BA"):
            raise ValueError(f"região inválida no feriado {data}: {regiao}")
        peso = float(e.get("peso", 0))
        if not 0 <= peso <= 1:
            raise ValueError(f"peso inválido no feriado {data}")
        extras.append({"data": data, "regiao": regiao, "peso": peso,
                       "descricao": str(e.get("descricao") or "").strip() or "Feriado local"})
    saida["calendario"] = {"sabado": sabado, "extras": sorted(extras, key=lambda e: (e["data"], e["regiao"]))}
    return saida


class Configuracao:
    def __init__(self, arquivo: str | Path):
        self.arquivo = Path(arquivo)
        self._trava = threading.Lock()
        if not self.arquivo.exists():
            self._grava(padrao())
        self._cfg = _valida(json.loads(self.arquivo.read_text(encoding="utf-8")))

    def atual(self) -> dict:
        with self._trava:
            return copy.deepcopy(self._cfg)

    def salvar(self, novo: dict) -> dict:
        cfg = _valida(novo)
        with self._trava:
            if self.arquivo.exists():
                anterior = self.arquivo.with_name(self.arquivo.stem + ".anterior.json")
                anterior.write_text(self.arquivo.read_text(encoding="utf-8"), encoding="utf-8")
            self._grava(cfg)
            self._cfg = cfg
        return copy.deepcopy(cfg)

    def restaurar_padrao(self) -> dict:
        return self.salvar(padrao())

    def _grava(self, cfg: dict) -> None:
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.arquivo)


class Regras:
    """Visão de leitura rápida da configuração usada nos cálculos."""

    def __init__(self, cfg: dict, supervisores: dict[int, int | None] | None = None):
        self.cfg = cfg
        self.equivalentes = {int(k): int(v) for k, v in cfg["produtos_equivalentes"].items()}
        self.produtos = {int(k): v for k, v in cfg["produtos"].items()}
        self.vendedores = {int(k): v for k, v in cfg["vendedores"].items()}
        self.motivos = set(cfg["devolucoes"]["motivos"])
        self.ignorar_canceladas = cfg["devolucoes"]["ignorar_canceladas"]
        self.categorias = cfg["categorias"]
        self.supervisores = supervisores or {}

    def produto(self, pid: int) -> int:
        return self.equivalentes.get(pid, pid)

    def grupo_produto(self, pid: int) -> str:
        return self.produtos.get(pid, {}).get("grupo", "outras")

    def categoria(self, pid: int) -> str | None:
        regra = self.produtos.get(pid)
        return regra.get("categoria") if regra and regra.get("grupo") == "outras" else None

    def grupo_vendedor(self, vid: int) -> str:
        if vid in self.vendedores:
            return self.vendedores[vid]
        return SUPERVISOR_GRUPO.get(self.supervisores.get(vid), "ES")

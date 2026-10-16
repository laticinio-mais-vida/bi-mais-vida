"""Regras de negócio editáveis na página Metas › Configurar (gravadas na tabela regras do banco).

Os valores padrão reproduzem as fórmulas DAX do Power BI, para os números baterem com ele até alguém mudar.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import threading

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


class RegrasNoBanco:
    """Uma configuração salva pelos administradores, na tabela regras (bi/migracoes/003_regras.sql). Cada gravação é
    uma versão nova, com quem salvou e quando, e vale a mais recente; sem nenhuma, vale o padrão.

    Fica uma cópia em memória, porque ela é lida em todo cálculo: lida do banco no primeiro uso e trocada só depois
    do commit de uma gravação, e só por uma versão mais nova. Se o banco cair depois, os cálculos seguem com ela.
    """

    nome = ""

    def __init__(self, banco):
        self.banco = banco
        self._trava = threading.Lock()
        self._versao: int | None = None  # id da versão na memória (0 = o padrão); None = ainda não leu
        self._cfg: dict | None = None

    @staticmethod
    def _valida(cfg: dict) -> dict:
        raise NotImplementedError

    def _padrao(self) -> dict:
        raise NotImplementedError

    def atual(self) -> dict:
        with self._trava:
            if self._versao is None:
                with self.banco.conexao() as con:
                    linha = con.execute("SELECT id, dados FROM regras WHERE nome = %s ORDER BY id DESC LIMIT 1",
                                        [self.nome]).fetchone()
                self._versao, self._cfg = (linha[0], self._valida(linha[1])) if linha else (0, self._valida(self._padrao()))
            return copy.deepcopy(self._cfg)

    def validar(self, novo: dict) -> dict:
        """Confere sem gravar (levanta ValueError com a explicação)."""
        return self._valida(novo)

    def gravar(self, novo: dict, autor: dict | None, con) -> tuple[int, dict]:
        """Grava uma versão nova na transação de quem chama. A cópia em memória só muda com usar(), depois do
        commit. autor: o usuário que salvou ({"id", "nome"}); None = o próprio painel."""
        cfg = self._valida(novo)
        versao = con.execute(
            "INSERT INTO regras (nome, dados, salva_por, salva_por_nome) "
            "VALUES (%s, %s::jsonb, (SELECT id FROM usuarios WHERE id = %s), %s) RETURNING id",
            [self.nome, json.dumps(cfg, ensure_ascii=False), autor and autor["id"], autor and autor["nome"]]).fetchone()[0]
        return versao, cfg

    def usar(self, versao: int, cfg: dict) -> dict:
        """Passa a usar uma versão já gravada (depois do commit)."""
        with self._trava:
            if self._versao is None or versao > self._versao:
                self._versao, self._cfg = versao, copy.deepcopy(cfg)
        return copy.deepcopy(cfg)

    def salvar(self, novo: dict, autor: dict | None = None) -> dict:
        with self.banco.conexao() as con:
            versao, cfg = self.gravar(novo, autor, con)
        return self.usar(versao, cfg)


class Configuracao(RegrasNoBanco):
    """Regras de cálculo das metas (página Metas › Configurar)."""

    nome = "metas"
    _valida = staticmethod(_valida)

    def _padrao(self) -> dict:
        return padrao()

    def restaurar_padrao(self, autor: dict | None = None) -> dict:
        return self.salvar(padrao(), autor)


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

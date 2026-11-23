"""Registro das perguntas ao Assistente (tabela assistente_perguntas, bi/migracoes/004_assistente_perguntas.sql):
quem perguntou, o quê, as consultas, os tokens e o custo estimado. Os limites e a tela "Uso e custo" da configuração
da página saem daqui.

Limites (LimitesAssistente: tabela regras, nome "assistente", com versões), salvos pelo administrador em Configurações
do assistente › Limites:
- gasto total de todo mundo por dia e por mês (US$);
- por pessoa: perguntas por dia, gasto por dia e gasto por mês (US$). Vale o limite próprio da pessoa, se ela tiver;
  senão, o padrão. O administrador sem limite próprio não tem limite por pessoa (só o total).
Vazio (None) é sem limite; 0 barra tudo. O limite barra a pergunta seguinte: a que já começou termina, mesmo que passe
dele. Enquanto o administrador não salva, valem os de [ia] no config.ini (limite_diario e limite_custo_dia).

"Hoje" e "o mês" começam à meia-noite (do dia e do dia 1º) no fuso deste computador (o do painel), calculada aqui e
não no banco.
"""
from __future__ import annotations

import configparser
import copy
import datetime as dt
import json
import math

from .banco import Banco, hora, inicio_do_dia
from .configuracao import RegrasNoBanco

TOKENS = ("entrada", "saida", "cache_leitura", "cache_escrita", "chamadas")
PESSOA = ("perguntas_dia", "custo_dia", "custo_mes")  # os limites de cada pessoa
TOTAL = ("total_dia", "total_mes")                    # os de todo mundo somado
MAX_PERGUNTAS = 10000
MAX_DOLARES = 100000.0
SEM_LIMITE = {k: None for k in PESSOA}

ROTULO = {"perguntas_dia": "perguntas por dia", "custo_dia": "gasto por dia", "custo_mes": "gasto por mês",
          "total_dia": "gasto total por dia", "total_mes": "gasto total por mês"}


def _perguntas(valor, nome: str) -> int | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        v = float(str(valor).replace(",", ".")) if not isinstance(valor, bool) else math.nan
    except (TypeError, ValueError):
        v = math.nan
    if not math.isfinite(v) or v != int(v) or not 0 <= v <= MAX_PERGUNTAS:
        raise ValueError(f"{nome}: um número inteiro de 0 a {MAX_PERGUNTAS}, ou vazio para não ter limite")
    return int(v)


def _dolares(valor, nome: str) -> float | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        v = float(str(valor).replace(",", ".")) if not isinstance(valor, bool) else math.nan
    except (TypeError, ValueError):
        v = math.nan
    if not math.isfinite(v) or not 0 <= v <= MAX_DOLARES:
        maximo = f"{MAX_DOLARES:,.0f}".replace(",", ".")
        raise ValueError(f"{nome}: um valor em US$ de 0 a {maximo}, ou vazio para não ter limite")
    return round(v, 4)


def _pessoa(d, onde: str) -> dict:
    d = d if isinstance(d, dict) else {}
    return {"perguntas_dia": _perguntas(d.get("perguntas_dia"), f"{onde}, {ROTULO['perguntas_dia']}"),
            "custo_dia": _dolares(d.get("custo_dia"), f"{onde}, {ROTULO['custo_dia']}"),
            "custo_mes": _dolares(d.get("custo_mes"), f"{onde}, {ROTULO['custo_mes']}")}


def valida_limites(cfg: dict) -> dict:
    """{"total_dia", "total_mes", "padrao": {perguntas_dia, custo_dia, custo_mes}, "usuarios": {"<id>": {os 3}}}."""
    cfg = cfg if isinstance(cfg, dict) else {}
    usuarios = {}
    for chave, d in (cfg.get("usuarios") or {}).items():
        try:
            uid = int(chave)
        except (TypeError, ValueError):
            uid = 0
        if uid <= 0:
            raise ValueError(f"limite próprio: usuário {chave!r} inválido")
        usuarios[str(uid)] = _pessoa(d, f"limite próprio do usuário {uid}")
    return {"versao": 1,
            "total_dia": _dolares(cfg.get("total_dia"), ROTULO["total_dia"]),
            "total_mes": _dolares(cfg.get("total_mes"), ROTULO["total_mes"]),
            "padrao": _pessoa(cfg.get("padrao"), "padrão"),
            "usuarios": dict(sorted(usuarios.items(), key=lambda kv: int(kv[0])))}


def limites_do_ini(ini: configparser.ConfigParser) -> dict:
    """Os limites de antes desta configuração, do [ia] do config.ini: valem até o administrador salvar."""
    return valida_limites({"total_dia": ini.getfloat("ia", "limite_custo_dia", fallback=2.0),
                           "padrao": {"perguntas_dia": ini.getint("ia", "limite_diario", fallback=50)}})


def da_pessoa(cfg: dict, usuario: dict) -> tuple[dict, bool]:
    """(os limites que valem para a pessoa, se são os próprios dela). O administrador sem limite próprio: sem limite."""
    proprio = cfg["usuarios"].get(str(usuario["id"]))
    if proprio is not None:
        return dict(proprio), True
    return dict(SEM_LIMITE if usuario["papel"] == "admin" else cfg["padrao"]), False


class LimitesAssistente(RegrasNoBanco):
    """Os limites do Assistente salvos pelo administrador (tabela regras, nome "assistente")."""

    nome = "assistente"
    _valida = staticmethod(valida_limites)

    def __init__(self, banco: Banco, padrao: dict):
        super().__init__(banco)
        self.padrao = valida_limites(padrao)

    def _padrao(self) -> dict:
        return copy.deepcopy(self.padrao)

    def ultima(self) -> dict | None:
        """Quem salvou por último e quando (None: ainda valem os do config.ini)."""
        with self.banco.conexao() as con:
            linha = con.execute("SELECT salva_em, salva_por_nome FROM regras WHERE nome = %s ORDER BY id DESC LIMIT 1",
                                [self.nome]).fetchone()
        return {"em": hora(linha[0]), "por": linha[1]} if linha else None


class LimitesFixos:
    """Os limites só em memória, sem banco (os testes do Assistente)."""

    def __init__(self, padrao: dict):
        self.padrao = valida_limites(padrao)
        self._cfg = copy.deepcopy(self.padrao)

    def atual(self) -> dict:
        return copy.deepcopy(self._cfg)

    def salvar(self, novo: dict, autor: dict | None = None) -> dict:
        self._cfg = valida_limites(novo)
        return self.atual()

    def ultima(self) -> dict | None:
        return None


class RegistroUso:
    def __init__(self, banco: Banco):
        self.banco = banco

    def gravar(self, r: dict) -> None:
        """r: o registro que o Assistente monta para cada pergunta (bi/assistente.py, Assistente._responder)."""
        uso = r.get("uso") or {}
        with self.banco.conexao() as con:
            # O usuário pode ter sido excluído enquanto a pergunta era respondida: o registro fica, sem o vínculo.
            con.execute(
                "INSERT INTO assistente_perguntas (usuario, login, nome, conversa, escopo, pergunta, resposta, aviso, "
                "erro, parada, modelo, entrada, saida, cache_leitura, cache_escrita, chamadas, custo, segundos, passos, "
                "data_ref, pedidos_api) VALUES ((SELECT id FROM usuarios WHERE id = %s), %s, %s, %s::uuid, %s, %s, %s, "
                "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::date, %s::text[])",
                [r.get("usuario"), r["login"], r["nome"], r.get("conversa"), r.get("escopo"), r["pergunta"],
                 r.get("resposta"), r.get("aviso"), r.get("erro"), r.get("parada"), uso.get("modelo"),
                 *(int(uso.get(k) or 0) for k in TOKENS), float(uso.get("custo") or 0), uso.get("segundos"),
                 json.dumps(r.get("passos") or [], ensure_ascii=False, default=str), r.get("data_ref"),
                 [str(p) for p in r.get("pedidos_api") or [] if p]])

    def contagem(self, usuario: int) -> dict:
        """O que os limites contam antes de cada pergunta: as perguntas e o gasto da pessoa hoje, o gasto dela no mês
        e o gasto de todo mundo hoje e no mês."""
        hoje = dt.date.today()
        dia, mes = inicio_do_dia(hoje), inicio_do_dia(hoje.replace(day=1))
        with self.banco.conexao() as con:
            linha = con.execute(
                "SELECT (count(*) FILTER (WHERE usuario = %s AND quando >= %s))::int, "
                "coalesce(sum(custo) FILTER (WHERE usuario = %s AND quando >= %s), 0)::float8, "
                "coalesce(sum(custo) FILTER (WHERE usuario = %s), 0)::float8, "
                "coalesce(sum(custo) FILTER (WHERE quando >= %s), 0)::float8, coalesce(sum(custo), 0)::float8 "
                "FROM assistente_perguntas WHERE quando >= %s",
                [usuario, dia, usuario, dia, usuario, dia, mes]).fetchone()
        return dict(zip(("perguntas_dia", "custo_dia", "custo_mes", "total_dia", "total_mes"), linha))

    def por_pessoa(self) -> dict[int, dict]:
        """{id do usuário: perguntas e gasto de hoje e do mês}, para a tela dos limites."""
        hoje = dt.date.today()
        dia, mes = inicio_do_dia(hoje), inicio_do_dia(hoje.replace(day=1))
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT usuario, (count(*) FILTER (WHERE quando >= %s))::int, "
                "coalesce(sum(custo) FILTER (WHERE quando >= %s), 0)::float8, count(*)::int, "
                "coalesce(sum(custo), 0)::float8 FROM assistente_perguntas WHERE quando >= %s AND usuario IS NOT NULL "
                "GROUP BY usuario", [dia, dia, mes]).fetchall()
        return {u: {"perguntas_dia": a, "custo_dia": round(b, 4), "perguntas_mes": c, "custo_mes": round(d, 4)}
                for u, a, b, c, d in linhas}

    def resumo(self, dias: int) -> dict:
        """Uso para a configuração da página: o de hoje e do mês, o de cada pessoa nos últimos `dias` e as últimas
        perguntas."""
        hoje = dt.date.today()
        desde = inicio_do_dia(hoje - dt.timedelta(days=dias))
        with self.banco.conexao() as con:
            n, custo, n_mes, custo_mes = con.execute(
                "SELECT (count(*) FILTER (WHERE quando >= %s))::int, "
                "coalesce(sum(custo) FILTER (WHERE quando >= %s), 0)::float8, count(*)::int, "
                "coalesce(sum(custo), 0)::float8 FROM assistente_perguntas WHERE quando >= %s",
                [inicio_do_dia(hoje), inicio_do_dia(hoje), inicio_do_dia(hoje.replace(day=1))]).fetchone()
            por_usuario = con.execute(
                "SELECT login, (array_agg(nome ORDER BY quando DESC))[1], count(*)::int, sum(custo)::float8, "
                "max(quando) FROM assistente_perguntas WHERE quando >= %s GROUP BY login "
                "ORDER BY count(*) DESC, login", [desde]).fetchall()
            ultimas = con.execute(
                "SELECT quando, login, nome, pergunta, custo::float8, erro, jsonb_array_length(passos) "
                "FROM assistente_perguntas WHERE quando >= %s ORDER BY quando DESC, id DESC LIMIT 30", [desde]).fetchall()
        return {
            "hoje": {"perguntas": n, "custo": round(custo, 4)},
            "mes": {"perguntas": n_mes, "custo": round(custo_mes, 4)},
            "por_usuario": [{"login": login, "nome": nome, "perguntas": q, "custo": round(c, 4), "ultima": hora(u)}
                            for login, nome, q, c, u in por_usuario],
            "ultimas": [{"quando": hora(q), "login": login, "nome": nome, "pergunta": p, "custo": c, "erro": e,
                         "passos": passos} for q, login, nome, p, c, e, passos in ultimas],
        }

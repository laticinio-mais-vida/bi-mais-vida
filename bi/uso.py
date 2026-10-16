"""Registro das perguntas ao Assistente (tabela assistente_perguntas, bi/migracoes/004_assistente_perguntas.sql):
quem perguntou, o quê, as consultas, os tokens e o custo estimado. Os limites do dia e a tela "Uso e custo" da
configuração da página saem daqui.

"Hoje" e "desde" são a meia-noite no fuso deste computador (o do painel), calculada aqui e não no banco.
"""
from __future__ import annotations

import datetime as dt
import json

from .banco import Banco, hora, inicio_do_dia

TOKENS = ("entrada", "saida", "cache_leitura", "cache_escrita", "chamadas")


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

    def do_dia(self, usuario: int) -> tuple[int, float]:
        """(perguntas da pessoa hoje, custo de hoje somando todo mundo), para os limites do dia."""
        with self.banco.conexao() as con:
            n, custo = con.execute(
                "SELECT (count(*) FILTER (WHERE usuario = %s))::int, coalesce(sum(custo), 0)::float8 "
                "FROM assistente_perguntas WHERE quando >= %s", [usuario, inicio_do_dia(dt.date.today())]).fetchone()
        return n, custo

    def resumo(self, dias: int) -> dict:
        """Uso para a configuração da página: o de hoje, o de cada pessoa nos últimos `dias` e as últimas perguntas."""
        hoje = dt.date.today()
        desde = inicio_do_dia(hoje - dt.timedelta(days=dias))
        with self.banco.conexao() as con:
            n, custo = con.execute(
                "SELECT count(*)::int, coalesce(sum(custo), 0)::float8 FROM assistente_perguntas WHERE quando >= %s",
                [inicio_do_dia(hoje)]).fetchone()
            por_usuario = con.execute(
                "SELECT login, (array_agg(nome ORDER BY quando DESC))[1], count(*)::int, sum(custo)::float8, "
                "max(quando) FROM assistente_perguntas WHERE quando >= %s GROUP BY login "
                "ORDER BY count(*) DESC, login", [desde]).fetchall()
            ultimas = con.execute(
                "SELECT quando, login, nome, pergunta, custo::float8, erro, jsonb_array_length(passos) "
                "FROM assistente_perguntas WHERE quando >= %s ORDER BY quando DESC, id DESC LIMIT 30", [desde]).fetchall()
        return {
            "hoje": {"perguntas": n, "custo": round(custo, 4)},
            "por_usuario": [{"login": login, "nome": nome, "perguntas": q, "custo": round(c, 4), "ultima": hora(u)}
                            for login, nome, q, c, u in por_usuario],
            "ultimas": [{"quando": hora(q), "login": login, "nome": nome, "pergunta": p, "custo": c, "erro": e,
                         "passos": passos} for q, login, nome, p, c, e, passos in ultimas],
        }

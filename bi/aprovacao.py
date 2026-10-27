"""Metas aprovadas no painel (Sugestão de Metas › Configurar › Aprovação de metas).

O administrador aprova a meta que a sugestão gerou para cada vendedor num mês e pode editar o total em R$, a mussarela
(no ES) e os clientes. A aprovada passa a valer no painel de Metas (e no Assistente, na Gestão e nas Projeções, que
leem as mesmas metas) no lugar das linhas da METAS.xlsx e da METAS PRODUTOS.xlsx desse vendedor e mês; os outros seguem
a planilha. Fica no banco de onde foi aprovada (o site): o painel do PC continua só com as planilhas.

- A aprovação guarda o retrato da sugestão do momento (total, mussarela, clientes da carteira e, por produto, o volume
  sugerido e o preço): a meta não muda quando a conta muda depois (devolução lançada tarde, troca de carteira). Editar
  parte desse retrato; retirar e aprovar de novo refaz pela sugestão do dia.
- A meta de volume de cada produto acompanha o R$: no BA, volume sugerido × (meta ÷ sugerida); no ES, os produtos de
  mussarela pelo fator da mussarela e os outros pelo das outras linhas. Volume × preço soma o total aprovado.
- Cada gravação é uma linha nova na tabela metas_aprovadas (migração 025), com quem salvou; vale a última de cada
  vendedor × mês, e aprovada = false é a aprovação retirada.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time

from .banco import BancoForaDoAr, hora

TRAVA = 7_240_125  # pg_advisory_xact_lock: duas gravações não conferem as versões ao mesmo tempo
REPETIR_BANCO = 60  # segundos até tentar ler de novo, se o banco estava fora do ar
CAMPOS = ("id", "mes", "id_vendedor", "estado", "aprovada", "vendedor", "meta_fat", "meta_mus", "meta_out", "meta_cli",
          "sugerida_fat", "sugerida_mus", "clientes_carteira", "clientes_dia", "produtos", "salva_em", "salva_por_nome")
_VALORES = ("meta_fat", "meta_mus", "meta_out", "sugerida_fat", "sugerida_mus")


def distribuir(produtos: list[dict], meta_fat: float, meta_mus: float, es: bool) -> tuple[list[dict], float]:
    """A meta de volume de cada produto do retrato ({volume_sugerido, preco, grupo}) para a meta em R$ aprovada, e o R$
    que não tem produto para ir (ex.: mussarela no ES de quem não tem produto de mussarela na sugestão). No BA, um fator
    só (meta ÷ sugerida); no ES, o da mussarela e o das outras linhas."""
    soma = lambda mus: sum(p["volume_sugerido"] * p["preco"] for p in produtos  # noqa: E731
                           if (p["grupo"] == "mussarela") == mus)
    sm, so = soma(True), soma(False)
    if es:
        alvo_m, alvo_o = meta_mus, meta_fat - meta_mus
        fm, fo = (alvo_m / sm if sm > 0 else 0.0), (alvo_o / so if so > 0 else 0.0)
        sobra = (alvo_m if sm <= 0 else 0.0) + (alvo_o if so <= 0 else 0.0)
    else:
        fm = fo = meta_fat / (sm + so) if sm + so > 0 else 0.0
        sobra = meta_fat if sm + so <= 0 else 0.0
    saida = [{**p, "meta_volume": round(p["volume_sugerido"] * (fm if p["grupo"] == "mussarela" else fo), 4)}
             for p in produtos]
    return saida, sobra


def juntar(base: list[dict], vigentes: list[dict], tipo: str) -> list[dict]:
    """As linhas da planilha sem as dos vendedor × mês aprovados, mais as aprovadas, no formato da planilha (ler_metas
    ou ler_metas_produtos, com "aprovada": True)."""
    if not vigentes:
        return base
    aprovados = {(a["mes"], a["id_vendedor"]) for a in vigentes}
    saida = [m for m in base if (m["mes"], m["id_vendedor"]) not in aprovados]
    for a in vigentes:
        chave = {"mes": a["mes"], "id_vendedor": a["id_vendedor"], "vendedor": a["vendedor"]}
        if tipo == "metas":
            saida.append({**chave, "meta_fat": a["meta_fat"], "meta_mus": a["meta_mus"], "meta_out": a["meta_out"],
                          "meta_cli": float(a["meta_cli"]), "aprovada": True})
        else:
            saida.extend({**chave, "id_produto": p["id"], "produto": p["produto"], "meta_volume": p["meta_volume"],
                          "aprovada": True} for p in a["produtos"] if p["meta_volume"])
    return saida


def _linha(r) -> dict:
    d = dict(zip(CAMPOS, r))
    for k in _VALORES:
        d[k] = float(d[k])
    return d


def _quando(valor) -> str:
    return dt.datetime.fromisoformat(hora(valor)).strftime("%d/%m às %H:%M") if valor else ""


class MetasAprovadas:
    """As metas aprovadas, na tabela metas_aprovadas. As em vigor (de todos os meses) ficam em memória, porque o painel
    de Metas as lê em todo pedido: lidas no primeiro uso e de novo depois de cada gravação. versao sobe a cada leitura."""

    def __init__(self, banco):
        self.banco = banco
        self._trava = threading.Lock()
        self._vigentes: list[dict] | None = None
        self._falhou_em: float | None = None
        self.versao = 0
        self.aviso: str | None = None

    def vigentes(self) -> list[dict]:
        """As aprovadas em vigor (a última linha de cada vendedor × mês, se for aprovação). Banco fora do ar antes da
        primeira leitura: nenhuma, com aviso, e tenta de novo depois de REPETIR_BANCO segundos."""
        with self._trava:
            if self._vigentes is None and (self._falhou_em is None
                                           or time.monotonic() - self._falhou_em >= REPETIR_BANCO):
                try:
                    with self.banco.conexao() as con:
                        linhas = con.execute(
                            f"SELECT DISTINCT ON (mes, id_vendedor) {', '.join(CAMPOS)} FROM metas_aprovadas "
                            "ORDER BY mes, id_vendedor, id DESC").fetchall()
                    self._vigentes = [x for x in map(_linha, linhas) if x["aprovada"]]
                    self._falhou_em, self.aviso = None, None
                    self.versao += 1
                except BancoForaDoAr:
                    self._falhou_em = time.monotonic()
                    self.aviso = ("As metas aprovadas no painel não puderam ser lidas (banco de dados fora do ar): por "
                                  "enquanto valem só as planilhas.")
            return self._vigentes or []

    def do_mes(self, mes: dt.date) -> dict[int, dict]:
        """Para a aba: {vendedor: {"ultima": a última linha (aprovada ou retirada), "aprovada_em"/"aprovada_por" (o
        começo da aprovação em vigor), "alterada_em"/"alterada_por" (a última edição dela, se houve)}}."""
        with self.banco.conexao() as con:
            linhas = con.execute(f"SELECT {', '.join(CAMPOS)} FROM metas_aprovadas WHERE mes = %s ORDER BY id",
                                 [mes]).fetchall()
        saida: dict[int, dict] = {}
        for x in map(_linha, linhas):
            r = saida.get(x["id_vendedor"])
            if x["aprovada"] and not (r and r["ultima"]["aprovada"]):  # aprovação nova (a primeira ou depois de retirar)
                r = saida[x["id_vendedor"]] = {"aprovada_em": hora(x["salva_em"]), "aprovada_por": x["salva_por_nome"],
                                               "alterada_em": None, "alterada_por": None}
            elif x["aprovada"]:
                r.update(alterada_em=hora(x["salva_em"]), alterada_por=x["salva_por_nome"])
            elif r is None:
                r = saida[x["id_vendedor"]] = {"aprovada_em": None, "aprovada_por": None, "alterada_em": None,
                                               "alterada_por": None}
            r["ultima"] = x
        return saida

    def gravar(self, mes: dt.date, registros: list[dict], autor: dict | None) -> None:
        """Grava uma linha nova por registro, numa transação. Cada registro diz a versão que o administrador viu (o id da
        última linha do vendedor no mês, ou None): se alguém gravou depois, nada é gravado."""
        with self.banco.conexao() as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA])
            ultimas = {v: (i, quem, em) for v, i, quem, em in con.execute(
                "SELECT DISTINCT ON (id_vendedor) id_vendedor, id, salva_por_nome, salva_em FROM metas_aprovadas "
                "WHERE mes = %s ORDER BY id_vendedor, id DESC", [mes]).fetchall()}
            for r in registros:
                atual = ultimas.get(r["id_vendedor"])
                if (atual[0] if atual else None) != r["versao"]:
                    quem = f" por {atual[1]}" if atual and atual[1] else ""
                    raise ValueError(f"a meta de {r['vendedor']} foi alterada{quem} em {_quando(atual and atual[2])} "
                                     "enquanto você editava; recarregue a aba para ver a versão nova")
            for r in registros:
                con.execute(
                    "INSERT INTO metas_aprovadas (mes, id_vendedor, estado, aprovada, vendedor, meta_fat, meta_mus, "
                    "meta_out, meta_cli, sugerida_fat, sugerida_mus, clientes_carteira, clientes_dia, produtos, salva_por, "
                    "salva_por_nome) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
                    "(SELECT id FROM usuarios WHERE id = %s), %s)",
                    [mes, r["id_vendedor"], r["estado"], r["aprovada"], r["vendedor"], r["meta_fat"], r["meta_mus"],
                     r["meta_out"], r["meta_cli"], r["sugerida_fat"], r["sugerida_mus"], r["clientes_carteira"],
                     r["clientes_dia"], json.dumps(r["produtos"], ensure_ascii=False), autor and autor["id"],
                     autor and autor["nome"]])
        with self._trava:  # relê no próximo uso
            self._vigentes, self._falhou_em = None, None


class MetasComAprovadas:
    """Uma planilha de metas (PlanilhaMonitorada) com as metas aprovadas por cima, com a mesma cara (dados(), versao,
    aviso) para a Calculadora e quem lê dela. tipo: "metas" (METAS.xlsx) ou "produtos" (METAS PRODUTOS.xlsx). A
    planilha crua fica em .planilha (a aba de aprovação compara com ela)."""

    def __init__(self, planilha, aprovadas: MetasAprovadas, tipo: str):
        self.planilha = planilha
        self.aprovadas = aprovadas
        self.tipo = tipo
        self._trava = threading.Lock()
        self._chave = None
        self._dados: list[dict] = []

    @property
    def versao(self):
        return (self.planilha.versao, self.aprovadas.versao)

    @property
    def aviso(self) -> str | None:
        return self.planilha.aviso or (self.aprovadas.aviso if self.tipo == "metas" else None)

    def dados(self) -> list[dict]:
        base = self.planilha.dados()
        vigentes = self.aprovadas.vigentes()
        chave = (id(base), len(base), self.planilha.versao, self.aprovadas.versao, id(vigentes))
        with self._trava:
            if chave != self._chave:
                self._dados, self._chave = juntar(base, vigentes, self.tipo), chave
            return self._dados

"""Ajustes da meta de volume na página Sugestão de Metas (só administrador; tabela sugestao_ajustes, migração 037).

O administrador troca a meta de volume que a fórmula deu numa linha da conta (BA: vendedor × área × produto, na tabela
por área; ES: vendedor × produto) e a sugestão passa a usar o número dele: a meta em R$ da linha é o volume × o preço
médio dela, e o total do vendedor, o resumo, a aprovação e o Assistente somam com o ajuste. Apagar o ajuste volta para
a fórmula. O número digitado não muda quando a conta muda depois (devolução lançada tarde, mês base ainda aberto).

Vendedor com a meta aprovada no mês: a mesma gravação acrescenta a aprovação com a diferença (bi/aprovacao.py
somar_ajustes): o produto ganha (ou perde) no volume aprovado o que a linha ganhou (ou perdeu) na página, a meta em R$
muda a diferença × o preço da linha, e os outros produtos não mudam. A diferença é contra o que vale agora na linha
(o ajuste gravado ou, sem ele, a fórmula), lido na mesma transação: dois administradores ao mesmo tempo não somam a
mesma diferença duas vezes.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from collections import defaultdict

from .aprovacao import TRAVA, inserir, somar_ajustes, ultimas
from .banco import BancoForaDoAr, hora

REPETIR_BANCO = 60  # segundos até tentar ler de novo, se o banco estava fora do ar


class AjustesVolume:
    """Os ajustes em vigor (de todos os meses) ficam em memória, porque a página os lê em todo pedido: lidos no
    primeiro uso e de novo depois de cada gravação."""

    def __init__(self, banco):
        self.banco = banco
        self._trava = threading.Lock()
        self._todos: dict | None = None
        self._falhou_em: float | None = None
        self.aviso: str | None = None

    def do_mes(self, mes: dt.date) -> dict[tuple, dict]:
        """{(vendedor, área, produto): {"volume", "salva_em", "salva_por"}} do mês da meta (área 0 no ES). Banco fora
        do ar antes da primeira leitura: nenhum, com aviso, e tenta de novo depois de REPETIR_BANCO segundos."""
        with self._trava:
            if self._todos is None and (self._falhou_em is None
                                        or time.monotonic() - self._falhou_em >= REPETIR_BANCO):
                try:
                    with self.banco.conexao() as con:
                        linhas = con.execute("SELECT mes, id_vendedor, id_area, id_produto, meta_volume, salva_em, "
                                             "salva_por_nome FROM sugestao_ajustes").fetchall()
                    todos: dict = defaultdict(dict)
                    for m, v, a, p, vol, em, quem in linhas:
                        todos[m][(v, a, p)] = {"volume": float(vol), "salva_em": hora(em), "salva_por": quem}
                    self._todos, self._falhou_em, self.aviso = dict(todos), None, None
                except BancoForaDoAr:
                    self._falhou_em = time.monotonic()
                    self.aviso = ("Os ajustes de volume da sugestão não puderam ser lidos (banco de dados fora do ar): "
                                  "por enquanto vale só a fórmula.")
            return dict((self._todos or {}).get(mes, {}))

    def gravar(self, mes: dt.date, mudancas: list[dict], autor: dict | None, aprovadas=None) -> list[str]:
        """Grava os ajustes de um mês, numa transação: mudancas = [{"v", "a", "p", "volume" (None = volta à fórmula),
        "formula", "preco", "produto", "unidade", "grupo"}]. Quem tem a meta aprovada no mês ganha uma aprovação nova
        com as diferenças (aprovadas: MetasAprovadas). Devolve o nome dos vendedores com a aprovada alterada."""
        alteradas = []
        with self.banco.conexao() as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA])  # a mesma trava da aprovação
            atuais = {(v, a, p): float(vol) for v, a, p, vol in con.execute(
                "SELECT id_vendedor, id_area, id_produto, meta_volume FROM sugestao_ajustes WHERE mes = %s",
                [mes]).fetchall()}
            deltas: dict[int, dict[int, dict]] = defaultdict(dict)
            for m in mudancas:
                chave = (m["v"], m["a"], m["p"])
                antes = atuais.get(chave, m["formula"])
                depois = m["formula"] if m["volume"] is None else m["volume"]
                if m["volume"] is None:
                    con.execute("DELETE FROM sugestao_ajustes WHERE mes = %s AND id_vendedor = %s AND id_area = %s "
                                "AND id_produto = %s", [mes, *chave])
                else:
                    con.execute(
                        "INSERT INTO sugestao_ajustes (mes, id_vendedor, id_area, id_produto, meta_volume, salva_por, "
                        "salva_por_nome) VALUES (%s, %s, %s, %s, %s, (SELECT id FROM usuarios WHERE id = %s), %s) "
                        "ON CONFLICT (mes, id_vendedor, id_area, id_produto) DO UPDATE SET "
                        "meta_volume = excluded.meta_volume, salva_em = now(), salva_por = excluded.salva_por, "
                        "salva_por_nome = excluded.salva_por_nome",
                        [mes, *chave, m["volume"], autor and autor["id"], autor and autor["nome"]])
                dv = depois - antes
                if abs(dv) > 1e-9:
                    d = deltas[m["v"]].setdefault(m["p"], {"volume": 0.0, "rs": 0.0, "produto": m["produto"],
                                                           "unidade": m["unidade"], "grupo": m["grupo"]})
                    d["volume"] += dv
                    d["rs"] += dv * m["preco"]
            if aprovadas is not None and deltas:
                for v, r in sorted(ultimas(con, mes, deltas).items()):
                    if r["aprovada"]:
                        inserir(con, mes, {**somar_ajustes(r, deltas[v]), "aprovada": True}, autor)
                        alteradas.append(r["vendedor"])
        with self._trava:  # relê no próximo uso
            self._todos, self._falhou_em = None, None
        if alteradas:
            aprovadas.esquecer()
        return alteradas

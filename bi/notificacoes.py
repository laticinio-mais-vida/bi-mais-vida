"""Notificações do painel: o sino no topo (web/js/avisos.js), para quem tem a página Gestão, com o que acontece nas
tarefas da agenda (bi/tarefas.py). Uma linha por aviso e por pessoa (notificacoes, migração 028).

- Avisos de ação, gravados por bi/tarefas.py na transação da própria ação (avisar): incluído numa tarefa, subtarefa
  nova (ou passada) para você, prazo mudado, concluída e justificativa enviada. Ninguém recebe aviso do que ele mesmo
  fez.
- Avisos de prazo (vence em breve, venceu): o servidor do site não tem nada rodando de tempos em tempos, então eles
  nascem quando o painel de quem recebe pergunta (Tarefas.gerar_avisos), uma vez só por item e por prazo (chave).
- Ficam DIAS_GUARDAR dias (limpar). A lista traz os MAX_LISTA mais recentes; ler um aviso (ou todos) marca como lido.
"""
from __future__ import annotations

from .banco import Banco, hora

TIPOS = ("incluido", "subtarefa_nova", "prazo_mudou", "vence_em_breve", "venceu", "concluida", "justificativa")
MAX_LISTA = 50
DIAS_GUARDAR = 90


def avisar(con, para, tipo: str, texto: str, autor: int | None, tarefa: int | None, subtarefa: int | None = None,
           chave: str | None = None) -> int:
    """Grava o aviso para cada pessoa de `para` (menos o autor), na transação de quem chama. Com a chave, o aviso que
    a pessoa já recebeu não se repete. Devolve quantos entraram."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo de aviso desconhecido: {tipo!r}")
    para = sorted(set(para) - {autor})
    entraram = 0
    for p in para:
        entraram += con.execute(
            "INSERT INTO notificacoes (usuario, tipo, tarefa, subtarefa, autor, texto, chave) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (usuario, chave) DO NOTHING",
            [p, tipo, tarefa, subtarefa, autor, texto, chave]).rowcount
    return entraram


class Notificacoes:
    def __init__(self, banco: Banco):
        self.banco = banco

    def contar(self, usuario: int) -> int:
        """Quantas a pessoa ainda não leu (o número no sino)."""
        with self.banco.conexao() as con:
            return con.execute("SELECT count(*) FROM notificacoes WHERE usuario = %s AND lida_em IS NULL",
                               [usuario]).fetchone()[0]

    def listar(self, usuario: int) -> dict:
        """As MAX_LISTA mais recentes, da mais nova para a mais antiga, e quantas não foram lidas."""
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT n.id, n.tipo, n.texto, n.tarefa, n.subtarefa, n.autor, u.nome, n.criada_em, n.lida_em "
                "FROM notificacoes n LEFT JOIN usuarios u ON u.id = n.autor WHERE n.usuario = %s "
                "ORDER BY n.criada_em DESC, n.id DESC LIMIT %s", [usuario, MAX_LISTA]).fetchall()
            nao_lidas = con.execute("SELECT count(*) FROM notificacoes WHERE usuario = %s AND lida_em IS NULL",
                                    [usuario]).fetchone()[0]
        return {"nao_lidas": nao_lidas,
                "itens": [{"id": i, "tipo": tipo, "texto": texto, "tarefa": tarefa, "subtarefa": sub,
                           "autor": {"id": autor, "nome": nome} if autor else None, "criada_em": hora(criada),
                           "lida": lida is not None}
                          for i, tipo, texto, tarefa, sub, autor, nome, criada, lida in linhas]}

    def marcar_lidas(self, usuario: int, ids=None, todas: bool = False) -> int:
        """Marca como lidas as notificações ids da pessoa (as de outra pessoa ficam como estão), ou todas; devolve
        quantas ainda não foram lidas."""
        if not todas:
            try:
                ids = sorted({int(i) for i in ids or []})
            except (TypeError, ValueError):
                raise ValueError("notificações inválidas") from None
        with self.banco.conexao() as con:
            if todas:
                con.execute("UPDATE notificacoes SET lida_em = now() WHERE usuario = %s AND lida_em IS NULL", [usuario])
            elif ids:
                con.execute("UPDATE notificacoes SET lida_em = now() WHERE usuario = %s AND lida_em IS NULL "
                            "AND id = ANY(%s::bigint[])", [usuario, ids])
            return con.execute("SELECT count(*) FROM notificacoes WHERE usuario = %s AND lida_em IS NULL",
                               [usuario]).fetchone()[0]


def limpar(con, usuario: int) -> None:
    """Apaga as notificações da pessoa com mais de DIAS_GUARDAR dias."""
    con.execute("DELETE FROM notificacoes WHERE usuario = %s AND criada_em < now() - make_interval(days => %s)",
                [usuario, DIAS_GUARDAR])

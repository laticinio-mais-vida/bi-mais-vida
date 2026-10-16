"""Histórico de conversas do Assistente, no PostgreSQL (bi/banco.py).

- Cada pessoa vê só as próprias conversas: todo método recebe o login e filtra por ele, e a conversa de outra
  pessoa é tratada como se não existisse.
- Uma conversa só é gravada depois da primeira resposta. Cada pergunta acrescenta a pergunta e a resposta (com as
  consultas feitas, para "Como cheguei nesse número"), sem regravar o que já estava lá.
- O título é o começo da primeira pergunta; a pessoa pode renomear.
"""
from __future__ import annotations

import contextlib
import json
import uuid

from .banco import Banco

MAX_MENSAGENS_CONVERSA = 200  # 100 perguntas; a IA vê só as últimas (MAX_MENSAGENS em bi/assistente.py)
TAM_TITULO = 60
MAX_TITULO = 80
DETALHES = ("consultas", "passos", "data_ref", "aviso", "uso")  # o que a página mostra junto da resposta
_META = "id, titulo, criada_em, atualizada_em"


class NaoEncontrada(Exception):
    """A conversa não existe ou é de outra pessoa (o servidor responde 404)."""


def novo_id() -> str:
    return str(uuid.uuid4())


def id_valido(id_) -> str | None:
    try:
        return str(uuid.UUID(str(id_)))
    except ValueError:
        return None


def titulo_de(pergunta: str) -> str:
    """Primeira linha da pergunta, cortada no fim de uma palavra."""
    linha = " ".join(next((l for l in str(pergunta).splitlines() if l.strip()), "").split())
    if len(linha) <= TAM_TITULO:
        return linha or "Nova conversa"
    corte = linha[:TAM_TITULO + 1]
    corte = corte.rsplit(" ", 1)[0] if " " in corte else corte[:TAM_TITULO]
    return corte.rstrip(" ,.;:-") + "…"


def _meta(linha) -> dict:
    id_, titulo, criada, atualizada = linha
    return {"id": str(id_), "titulo": titulo, "criada_em": criada.isoformat(timespec="seconds"),
            "atualizada_em": atualizada.isoformat(timespec="seconds")}


def _padrao_busca(texto: str) -> str:
    texto = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{texto}%"


class Conversas:
    def __init__(self, banco: Banco):
        self.banco = banco

    def verificar(self) -> None:
        """Levanta BancoForaDoAr se o banco não responde (antes de pagar por uma resposta que não seria gravada)."""
        with self.banco.conexao() as con:
            con.execute("SELECT 1")

    def listar(self, login: str, busca: str | None = None) -> list[dict]:
        """Conversas da pessoa, da mais recente para a mais antiga. A busca olha o título e as mensagens."""
        sql, params = f"SELECT {_META} FROM conversas c WHERE login = %s", [login]
        busca = " ".join(str(busca or "").split())[:100]
        if busca:
            sql += (" AND (sem_acento(titulo) ILIKE sem_acento(%s) OR EXISTS (SELECT 1 FROM mensagens m"
                    " WHERE m.conversa = c.id AND sem_acento(m.texto) ILIKE sem_acento(%s)))")
            params += [_padrao_busca(busca)] * 2
        with self.banco.conexao() as con:
            return [_meta(r) for r in con.execute(sql + " ORDER BY atualizada_em DESC", params)]

    def obter(self, login: str, id_) -> dict | None:
        """A conversa com as mensagens, no formato que a página desenha."""
        id_ = id_valido(id_)
        if not id_:
            return None
        with self.banco.conexao() as con:
            linha = con.execute(f"SELECT {_META} FROM conversas WHERE id = %s AND login = %s", [id_, login]).fetchone()
            if not linha:
                return None
            mensagens = con.execute("SELECT papel, texto, detalhes FROM mensagens WHERE conversa = %s ORDER BY id",
                                    [id_]).fetchall()
        return {**_meta(linha), "mensagens": [{"papel": p, "texto": t, **(d or {})} for p, t, d in mensagens]}

    def historico(self, login: str, id_) -> list[dict] | None:
        """As mensagens no formato que o Assistente manda à IA: só o texto e o resumo das consultas."""
        id_ = id_valido(id_)
        if not id_:
            return None
        with self.banco.conexao() as con:
            if not con.execute("SELECT 1 FROM conversas WHERE id = %s AND login = %s", [id_, login]).fetchone():
                return None
            linhas = con.execute("SELECT papel, texto, detalhes->>'consultas' FROM mensagens WHERE conversa = %s "
                                 "ORDER BY id", [id_]).fetchall()
        return [{"papel": p, "texto": t, **({"consultas": c} if c else {})} for p, t, c in linhas]

    def acrescentar(self, login: str, id_, pergunta: str, resposta: dict) -> dict:
        """Grava uma pergunta e a resposta ({"texto", e os DETALHES}); cria a conversa se ela ainda não existe."""
        id_ = id_valido(id_)
        if not id_:
            raise NaoEncontrada("conversa inválida")
        detalhes = json.dumps({k: resposta.get(k) for k in DETALHES}, ensure_ascii=False, default=str)
        with self.banco.conexao() as con:
            dono = con.execute("SELECT login FROM conversas WHERE id = %s FOR UPDATE", [id_]).fetchone()
            if dono and dono[0] != login:
                raise NaoEncontrada("conversa não encontrada")
            if not dono:
                con.execute("INSERT INTO conversas (id, login, titulo) VALUES (%s, %s, %s)",
                            [id_, login, titulo_de(pergunta)])
            con.execute("INSERT INTO mensagens (conversa, papel, texto) VALUES (%s, 'usuario', %s)", [id_, pergunta])
            con.execute("INSERT INTO mensagens (conversa, papel, texto, detalhes) VALUES (%s, 'assistente', %s, "
                        "%s::jsonb)", [id_, resposta["texto"], detalhes])
            linha = con.execute(f"UPDATE conversas SET atualizada_em = now() WHERE id = %s RETURNING {_META}",
                                [id_]).fetchone()
        return _meta(linha)

    def renomear(self, login: str, id_, titulo) -> dict:
        titulo = " ".join(str(titulo or "").split())
        if not titulo:
            raise ValueError("escreva o nome da conversa")
        if len(titulo) > MAX_TITULO:
            raise ValueError(f"o nome da conversa pode ter até {MAX_TITULO} caracteres")
        id_ = id_valido(id_)
        with self.banco.conexao() as con:
            linha = id_ and con.execute(f"UPDATE conversas SET titulo = %s WHERE id = %s AND login = %s "
                                        f"RETURNING {_META}", [titulo, id_, login]).fetchone()
        if not linha:
            raise NaoEncontrada("conversa não encontrada; ela pode ter sido excluída")
        return _meta(linha)

    def excluir(self, login: str, id_) -> None:
        id_ = id_valido(id_)
        with self.banco.conexao() as con:
            apagou = id_ and con.execute("DELETE FROM conversas WHERE id = %s AND login = %s", [id_, login]).rowcount
        if not apagou:
            raise NaoEncontrada("conversa não encontrada; ela pode ter sido excluída")

    # --- acompanham o cadastro de usuários -------------------------------------------------
    # As conversas mudam na mesma hora que usuarios.json: o commit só acontece se o bloco (a gravação do cadastro)
    # der certo. Assim, um login reaproveitado depois nunca herda as conversas de outra pessoa.
    @contextlib.contextmanager
    def mudar_login(self, antigo: str, novo: str):
        with self.banco.conexao() as con:
            con.execute("UPDATE conversas SET login = %s WHERE login = %s", [novo, antigo])
            yield

    @contextlib.contextmanager
    def apagar_login(self, login: str):
        with self.banco.conexao() as con:
            con.execute("DELETE FROM conversas WHERE login = %s", [login])
            yield

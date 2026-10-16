"""Banco PostgreSQL com os dados que o próprio painel cria (por enquanto, o histórico de conversas do Assistente).

- Só no site (VPS): a seção [postgres] do config.ini diz onde ele está. Sem host, o painel funciona sem banco (é o
  caso do PC da empresa) e o que depende dele não aparece.
- O DuckDB continua sendo o cache dos dados do ERP; aqui fica só o que as pessoas criam no painel.
- Migrações: arquivos bi/migracoes/NNN_nome.sql, aplicados em ordem, uma vez cada (tabela migracoes), na subida
  do painel. Se o banco estava fora do ar, são aplicadas no primeiro uso depois que ele voltar.
- Fora do ar: quem usa recebe BancoForaDoAr (o servidor responde 503) e o resto do painel segue funcionando.
"""
from __future__ import annotations

import configparser
import contextlib
import logging
import threading
from pathlib import Path

log = logging.getLogger("bi.banco")

MIGRACOES = Path(__file__).resolve().parent / "migracoes"
TRAVA_MIGRACOES = 7_240_101  # pg_advisory_xact_lock: duas subidas ao mesmo tempo não migram juntas
ESPERA = 5  # segundos para conectar ou conseguir uma conexão livre


class BancoForaDoAr(Exception):
    """O banco está configurado, mas não respondeu."""


class Banco:
    def __init__(self, ini: configparser.ConfigParser, schema: str | None = None):
        """schema: tudo dentro desse schema (os testes usam um temporário)."""
        g = lambda k, d="": ini.get("postgres", k, fallback=d).strip()  # noqa: E731
        self.host = g("host")
        self.schema = schema
        self._parametros = {
            "host": self.host, "port": ini.getint("postgres", "porta", fallback=5432), "dbname": g("banco", "bi"),
            "user": g("usuario", "bi"), "password": g("senha"), "connect_timeout": ESPERA,
            "application_name": "bi-mais-vida",
            **({"options": f"-c search_path={schema},public"} if schema else {}),
        }
        self._pool = None
        self._erros: tuple = ()
        self._trava = threading.Lock()
        self._migrado = False

    @property
    def configurado(self) -> bool:
        return bool(self.host)

    def descricao(self) -> str:
        p = self._parametros
        return f"{p['user']}@{p['host']}:{p['port']}/{p['dbname']}"

    # --- conexões --------------------------------------------------------------------------
    def _abrir_pool(self):
        with self._trava:
            if self._pool is None:
                import psycopg  # só aqui: sem o banco configurado, o painel abre sem o pacote
                from psycopg_pool import ConnectionPool, PoolTimeout
                self._erros = (psycopg.OperationalError, PoolTimeout)
                self._pool = ConnectionPool(kwargs=self._parametros, min_size=1, max_size=5, timeout=ESPERA,
                                            check=ConnectionPool.check_connection, name="bi", open=False)
                self._pool.open(wait=False)  # conecta em segundo plano; fora do ar, continua tentando
            return self._pool

    @contextlib.contextmanager
    def _conexao(self):
        pool = self._abrir_pool()
        try:
            with pool.connection() as con:
                yield con
        except self._erros as e:
            raise BancoForaDoAr(f"o banco de dados não respondeu ({e})") from e

    @contextlib.contextmanager
    def conexao(self):
        """Uma conexão numa transação: commit no fim do bloco, rollback se der erro."""
        if not self._migrado:
            self.migrar()
        with self._conexao() as con:
            yield con

    def fechar(self) -> None:
        with self._trava:
            if self._pool is not None:
                self._pool.close()
                self._pool = None

    # --- migrações -------------------------------------------------------------------------
    def migrar(self) -> list[str]:
        """Aplica as migrações que faltam, todas numa transação. Devolve as que foram aplicadas agora."""
        feitas = []
        with self._conexao() as con:
            if self.schema:
                con.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA_MIGRACOES])
            con.execute("CREATE TABLE IF NOT EXISTS migracoes ("
                        "versao text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now())")
            aplicadas = {r[0] for r in con.execute("SELECT versao FROM migracoes")}
            for arquivo in sorted(MIGRACOES.glob("[0-9][0-9][0-9]_*.sql")):
                if arquivo.stem not in aplicadas:
                    con.execute(arquivo.read_text(encoding="utf-8"))  # sem parâmetros: aceita vários comandos
                    con.execute("INSERT INTO migracoes (versao) VALUES (%s)", [arquivo.stem])
                    feitas.append(arquivo.stem)
        self._migrado = True
        return feitas

    def iniciar(self) -> None:
        """Na subida do painel: conecta e aplica as migrações. Se não der, só avisa; tenta de novo no uso."""
        try:
            feitas = self.migrar()
        except BancoForaDoAr as e:
            log.error("banco de dados %s fora do ar: o histórico do Assistente volta quando ele responder (%s)",
                      self.descricao(), e.__cause__)
        except Exception:
            log.exception("falha ao preparar o banco de dados %s", self.descricao())
        else:
            log.info("banco de dados %s pronto%s", self.descricao(),
                     f" (migrações aplicadas agora: {', '.join(feitas)})" if feitas else "")

"""Banco PostgreSQL com os dados que o próprio painel cria: usuários, regras salvas pelos administradores, histórico
de conversas e registro de uso do Assistente.

- No site e no PC: a seção [postgres] do config.ini diz onde ele está (no PC, o PostgreSQL instalado no Windows).
- O DuckDB continua sendo o cache dos dados do ERP; aqui fica só o que as pessoas criam no painel.
- Migrações: arquivos bi/migracoes/NNN_nome.sql (ou NNN_nome.py, com uma função aplicar(con, raiz), para trazer
  dados de arquivos), aplicados em ordem, uma vez cada (tabela migracoes), todos numa transação, na subida do painel.
  Se o banco estava fora do ar, são aplicadas no primeiro uso depois que ele voltar.
- Fora do ar ou sem configurar: quem usa recebe BancoForaDoAr (o servidor responde 503). A extração e o envio dos
  dados ao site não dependem do banco e seguem funcionando.
"""
from __future__ import annotations

import configparser
import contextlib
import datetime as dt
import importlib.util
import logging
import threading
from pathlib import Path

log = logging.getLogger("bi.banco")

MIGRACOES = Path(__file__).resolve().parent / "migracoes"
TRAVA_MIGRACOES = 7_240_101  # pg_advisory_xact_lock: duas subidas ao mesmo tempo não migram juntas
ESPERA = 5  # segundos para conectar ou conseguir uma conexão livre


class BancoForaDoAr(Exception):
    """O banco está configurado, mas não respondeu."""

    aviso = "o banco de dados está fora do ar agora; tente de novo em instantes"


class BancoNaoPreparado(BancoForaDoAr):
    """Falta configurar [postgres], falta o pacote psycopg ou a atualização das tabelas falhou: não adianta tentar
    de novo em instantes, alguém precisa resolver (a mensagem diz o quê)."""

    @property
    def aviso(self) -> str:
        return str(self)


def hora(valor: dt.datetime | None) -> str | None:
    """Data e hora no fuso deste computador, sem o fuso no texto (o formato que as páginas mostram)."""
    return valor.astimezone().replace(tzinfo=None).isoformat(timespec="seconds") if valor else None


def inicio_do_dia(dia: dt.date) -> dt.datetime:
    """Meia-noite de `dia` no fuso deste computador (com o fuso, para o banco comparar com timestamptz)."""
    return dt.datetime.combine(dia, dt.time()).astimezone()


class Banco:
    def __init__(self, ini: configparser.ConfigParser, schema: str | None = None, raiz: str | Path | None = None):
        """schema: tudo dentro desse schema (os testes usam um temporário).
        raiz: pasta do painel, de onde as migrações em Python importam os arquivos antigos (None = não importa)."""
        g = lambda k, d="": ini.get("postgres", k, fallback=d).strip()  # noqa: E731
        self.host = g("host")
        self.schema = schema
        self.raiz = Path(raiz) if raiz else None
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
        self._falha: str | None = None  # a migração falhou nesta subida: não tenta de novo a cada pedido

    @property
    def configurado(self) -> bool:
        return bool(self.host)

    def descricao(self) -> str:
        p = self._parametros
        return f"{p['user']}@{p['host']}:{p['port']}/{p['dbname']}"

    # --- conexões --------------------------------------------------------------------------
    def _abrir_pool(self):
        if not self.configurado:
            raise BancoNaoPreparado("o banco de dados não está configurado: preencha [postgres] no config.ini do painel")
        with self._trava:
            if self._pool is None:
                try:
                    import psycopg  # só aqui: o painel abre (e envia os dados ao site) mesmo sem o pacote
                    from psycopg_pool import ConnectionPool, PoolTimeout
                except ImportError:
                    raise BancoNaoPreparado('falta instalar o pacote do banco de dados: pip install "psycopg[binary]" '
                                            "psycopg-pool") from None
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
            self._preparar()
        with self._conexao() as con:
            yield con

    def fechar(self) -> None:
        with self._trava:
            if self._pool is not None:
                self._pool.close()
                self._pool = None

    # --- migrações -------------------------------------------------------------------------
    @staticmethod
    def _arquivos_migracao() -> list[Path]:
        arquivos = sorted([*MIGRACOES.glob("[0-9][0-9][0-9]_*.sql"), *MIGRACOES.glob("[0-9][0-9][0-9]_*.py")],
                          key=lambda a: a.stem)
        repetidas = {a.stem for a in arquivos if [b.stem for b in arquivos].count(a.stem) > 1}
        if repetidas:
            raise RuntimeError(f"migrações com o mesmo nome: {', '.join(sorted(repetidas))}")
        return arquivos

    def _aplicar(self, con, arquivo: Path) -> None:
        if arquivo.suffix == ".sql":
            con.execute(arquivo.read_text(encoding="utf-8"))  # sem parâmetros: aceita vários comandos
            return
        spec = importlib.util.spec_from_file_location(f"bi_migracao_{arquivo.stem}", arquivo)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        modulo.aplicar(con, self.raiz)

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
            avisos = lambda n: log.warning("migração: %s", n.message_primary)  # noqa: E731  (RAISE NOTICE)
            con.add_notice_handler(avisos)
            try:
                for arquivo in self._arquivos_migracao():
                    if arquivo.stem not in aplicadas:
                        self._aplicar(con, arquivo)
                        con.execute("INSERT INTO migracoes (versao) VALUES (%s)", [arquivo.stem])
                        feitas.append(arquivo.stem)
            finally:
                con.remove_notice_handler(avisos)
        self._migrado = True
        return feitas

    def _preparar(self) -> list[str]:
        """migrar(), mas uma migração que falha (erro nos dados, não o banco fora do ar) vira BancoNaoPreparado e
        não é repetida a cada pedido: fica no log e espera alguém resolver e reiniciar o painel."""
        if self._falha:
            raise BancoNaoPreparado(self._falha)
        try:
            return self.migrar()
        except BancoForaDoAr:
            raise
        except Exception as e:
            log.exception("falha ao atualizar as tabelas do banco de dados %s", self.descricao())
            self._falha = ("a atualização das tabelas do banco de dados falhou; o administrador precisa ver o "
                           "logs/bi.log do painel")
            raise BancoNaoPreparado(self._falha) from e

    def iniciar(self) -> None:
        """Na subida do painel: conecta e aplica as migrações. Se não der, só avisa; tenta de novo no uso."""
        try:
            feitas = self._preparar()
        except BancoNaoPreparado as e:
            if self._falha is None:  # a falha da migração já foi para o log, com os detalhes
                log.error("%s: ninguém consegue entrar no painel até resolver (o envio dos dados ao site continua)", e)
        except BancoForaDoAr as e:
            log.error("banco de dados %s fora do ar: o login e as páginas voltam quando ele responder (%s)",
                      self.descricao(), e.__cause__)
        else:
            log.info("banco de dados %s pronto%s", self.descricao(),
                     f" (migrações aplicadas agora: {', '.join(feitas)})" if feitas else "")

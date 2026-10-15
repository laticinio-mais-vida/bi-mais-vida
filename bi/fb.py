"""Conexão somente leitura com a cópia do banco Firebird 2.1.

Adaptado de Desktop\\RAG\\gdb2sql\\gdb2sql\\firebird.py:
- o fdb 2.x exige fb_shutdown/fb_shutdown_callback, que só existem no fbclient a partir
  do Firebird 2.5; devolvemos funções vazias quando a DLL 2.1 não as tem;
- conectamos com charset NONE e decodificamos o texto em cp1252 sem nunca falhar;
- todas as consultas rodam numa única transação somente leitura (snapshot).
"""
from __future__ import annotations

import codecs
import ctypes

import fdb
from fdb import ibase

_api_carregada = False


def _instalar_shim_cliente_legado() -> None:
    class _LegacyDLL(ctypes.WinDLL):
        _stubbed = ("fb_shutdown", "fb_shutdown_callback")

        def __getattr__(self, name):
            try:
                return super().__getattr__(name)
            except AttributeError:
                if name in self._stubbed:
                    stub = ctypes.CFUNCTYPE(ctypes.c_int)(lambda *a: 0)
                    setattr(self, name, stub)
                    return stub
                raise

    ctypes.WinDLL = _LegacyDLL


def _codec_tolerante(encoding: str) -> str:
    """Registra (uma vez) um codec que decodifica com `encoding` trocando bytes inválidos por U+FFFD."""
    base = codecs.lookup(encoding)
    nome = f"painel_{base.name}_tolerante".replace("-", "_")
    try:
        codecs.lookup(nome)
        return nome
    except LookupError:
        pass
    info = codecs.CodecInfo(
        name=nome,
        encode=lambda text, errors="strict": base.encode(text, "replace"),
        decode=lambda data, errors="replace": base.decode(data, "replace"),
    )
    codecs.register(lambda n: info if n == nome else None)
    return nome


class BancoSomenteLeitura:
    """Uso: `with BancoSomenteLeitura(...) as bd: linhas = bd.consulta(sql, params)`."""

    def __init__(self, arquivo: str, usuario: str, senha: str, host: str = "localhost",
                 fbclient: str | None = None, codificacao: str = "cp1252"):
        global _api_carregada
        if not _api_carregada:
            if fbclient:
                _instalar_shim_cliente_legado()
                fdb.load_api(fbclient)
            _api_carregada = True
        self.codificacao = codificacao
        dsn = f"{host}:{arquivo}" if host else arquivo
        self.con = fdb.connect(dsn=dsn, user=usuario, password=senha, charset="NONE", sql_dialect=3)
        self.con._python_charset = _codec_tolerante(codificacao)
        tpb = fdb.TPB()
        tpb.access_mode = ibase.isc_tpb_read
        tpb.isolation_level = ibase.isc_tpb_concurrency
        tpb.lock_resolution = ibase.isc_tpb_nowait
        self.tr = self.con.trans(default_tpb=tpb)
        self.cur = self.tr.cursor()

    def consulta(self, sql: str, params=()) -> list[tuple]:
        self.cur.execute(sql, params)
        return [tuple(self._texto(v) for v in linha) for linha in self.cur.fetchall()]

    def _texto(self, v):
        if isinstance(v, bytes):
            v = v.decode(self.codificacao, errors="replace")
        return v.strip() if isinstance(v, str) else v

    def fechar(self) -> None:
        for passo in (self.cur.close, self.tr.commit, self.con.close):
            try:
                passo()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechar()

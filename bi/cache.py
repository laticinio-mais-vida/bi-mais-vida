"""Cache local (DuckDB) com os dados do ERP que as páginas de metas usam.

A extração lê a cópia do Firebird numa transação somente leitura, agrega por dia/vendedor/produto e grava
um arquivo novo; só depois troca o cache em uso. Enquanto atualiza, o painel continua respondendo com o
cache anterior. As regras (grupos de produto, motivos de devolução, equivalências) NÃO são aplicadas aqui:
ficam para a hora do cálculo, então mudar a configuração não exige extrair de novo.
"""
from __future__ import annotations

import configparser
import datetime as dt
import logging
import os
import threading
import time
from pathlib import Path

import duckdb
import pandas as pd

from .fb import BancoSomenteLeitura

log = logging.getLogger("bi.cache")

TABELAS = {
    "vendas_itens": "data DATE, id_vendedor INTEGER, id_produto INTEGER, valor DOUBLE, quantidade DOUBLE",
    "vendas_clientes": "data DATE, id_vendedor INTEGER, id_cliente INTEGER, tipocliente VARCHAR, vendas INTEGER",
    "devolucoes_itens": ("data DATE, id_vendedor INTEGER, id_produto INTEGER, id_motivo INTEGER, "
                         "cancelada BOOLEAN, valor DOUBLE, quantidade DOUBLE"),
    "produtos": "id INTEGER, nome VARCHAR, id_linha INTEGER, linha VARCHAR, unidade VARCHAR, inativo INTEGER",
    "vendedores": "id INTEGER, nome VARCHAR, id_supervisor INTEGER, supervisor VARCHAR, inativo INTEGER",
    "motivos": "id INTEGER, nome VARCHAR",
    "info": "chave VARCHAR, valor VARCHAR",
}


def _data(v):
    if isinstance(v, dt.datetime):
        return v.date()
    return v


class Cache:
    def __init__(self, ini: configparser.ConfigParser, raiz: Path):
        self.ini = ini
        self.arquivo = raiz / ini.get("cache", "arquivo", fallback=r"dados\cache.duckdb")
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.inicio = dt.date.fromisoformat(ini.get("cache", "inicio", fallback="2024-01-01"))
        self.banco = Path(ini.get("banco", "arquivo"))
        self._con: duckdb.DuckDBPyConnection | None = None
        self._trava = threading.RLock()
        self._trava_extracao = threading.Lock()
        self.estado = {"atualizando": False, "etapa": None, "erro": None, "inicio": None, "duracao": None}
        self.info: dict[str, str] = {}
        if self.arquivo.exists():
            try:
                self._abrir()
            except Exception as e:  # cache corrompido: será recriado
                log.warning("cache ilegível (%s); será recriado", e)
                self._con = None

    # --- leitura -------------------------------------------------------------------------
    def pronto(self) -> bool:
        return self._con is not None

    def consulta(self, sql: str, params: list | tuple = ()) -> list[tuple]:
        with self._trava:
            if self._con is None:
                raise RuntimeError("os dados ainda estão sendo preparados")
            return self._con.execute(sql, list(params)).fetchall()

    def _abrir(self) -> None:
        con = duckdb.connect(str(self.arquivo), read_only=True)
        info = dict(con.execute("SELECT chave, valor FROM info").fetchall())
        with self._trava:
            if self._con is not None:
                self._con.close()
            self._con = con
            self.info = info

    def data_ref(self) -> dt.date | None:
        v = self.info.get("data_ref")
        return dt.date.fromisoformat(v) if v else None

    def desatualizado(self) -> bool:
        """True se a cópia do banco é mais nova que a usada no cache."""
        try:
            mtime = self.banco.stat().st_mtime
        except OSError:
            return False
        return self._con is None or float(self.info.get("banco_mtime", 0)) < mtime - 1

    # --- extração ------------------------------------------------------------------------
    def atualizar_em_segundo_plano(self) -> bool:
        if self.estado["atualizando"]:
            return False
        threading.Thread(target=self.atualizar, name="extracao", daemon=True).start()
        return True

    def atualizar(self) -> None:
        if not self._trava_extracao.acquire(blocking=False):
            return
        t0 = time.time()
        self.estado.update(atualizando=True, etapa="Conectando ao banco", erro=None, inicio=dt.datetime.now().isoformat(timespec="seconds"))
        novo = self.arquivo.with_name(self.arquivo.stem + ".novo.duckdb")
        try:
            dados = self._extrair()
            self.estado["etapa"] = "Gravando cache local"
            if novo.exists():
                novo.unlink()
            con = duckdb.connect(str(novo))
            for nome, colunas in TABELAS.items():
                con.execute(f"CREATE TABLE {nome} ({colunas})")
                linhas = dados[nome]
                if linhas:
                    nomes = [c.split()[0] for c in colunas.split(", ")]
                    df = pd.DataFrame(linhas, columns=nomes)
                    con.register("df_tmp", df)
                    con.execute(f"INSERT INTO {nome} SELECT * FROM df_tmp")
                    con.unregister("df_tmp")
            con.execute("CREATE INDEX ix_vi ON vendas_itens (data)")
            con.execute("CREATE INDEX ix_vc ON vendas_clientes (data)")
            con.execute("CREATE INDEX ix_di ON devolucoes_itens (data)")
            con.close()
            with self._trava:
                if self._con is not None:
                    self._con.close()
                    self._con = None
                os.replace(novo, self.arquivo)
                self._abrir()
            self.estado["duracao"] = round(time.time() - t0, 1)
            log.info("cache atualizado em %.1f s (dados até %s)", time.time() - t0, self.info.get("data_ref"))
        except Exception as e:
            log.exception("falha ao atualizar o cache")
            self.estado["erro"] = str(e)
            if self._con is None and self.arquivo.exists():
                try:
                    self._abrir()
                except Exception:
                    pass
        finally:
            self.estado.update(atualizando=False, etapa=None)
            self._trava_extracao.release()

    def _extrair(self) -> dict[str, list]:
        b = self.ini["banco"]
        hoje = dt.date.today()
        de = dt.datetime.combine(self.inicio, dt.time())
        ate = dt.datetime.combine(hoje + dt.timedelta(days=1), dt.time())  # descarta datas digitadas erradas no futuro
        banco_mtime = self.banco.stat().st_mtime
        dados: dict[str, list] = {}
        with BancoSomenteLeitura(b["arquivo"], b["usuario"], b["senha"], b.get("host", "localhost"),
                                 b.get("fbclient"), b.get("codificacao", "cp1252")) as bd:
            self.estado["etapa"] = "Lendo itens vendidos"
            dados["vendas_itens"] = [
                (_data(d), v, p, float(val or 0), float(q or 0)) for d, v, p, val, q in bd.consulta(
                    "SELECT v.DATA, COALESCE(v.ID_VENDEDOR, 0), COALESCE(l.ID_ITEM, 0), "
                    "SUM(l.VALORTOTALITEM), SUM(l.QUANTIDADE) "
                    "FROM VENDAS v JOIN LISTAVENDA l ON l.ID_VENDA = v.ID_VENDA "
                    "WHERE v.DATA >= ? AND v.DATA < ? AND v.DATACANCELAMENTO IS NULL "
                    "GROUP BY 1, 2, 3", (de, ate))]
            self.estado["etapa"] = "Lendo clientes atendidos"
            dados["vendas_clientes"] = [
                (_data(d), v, c, t, n) for d, v, c, t, n in bd.consulta(
                    "SELECT v.DATA, COALESCE(v.ID_VENDEDOR, 0), v.ID_CLIENTE, MAX(v.TIPOCLIENTE), COUNT(*) "
                    "FROM VENDAS v WHERE v.DATA >= ? AND v.DATA < ? AND v.DATACANCELAMENTO IS NULL "
                    "GROUP BY 1, 2, 3", (de, ate))]
            self.estado["etapa"] = "Lendo devoluções"
            dados["devolucoes_itens"] = [
                (_data(d), v, p, m, bool(c), float(val or 0), float(q or 0)) for d, v, p, m, c, val, q in bd.consulta(
                    "SELECT CAST(d.ENTRADA AS DATE), COALESCE(d.ID_VENDEDOR, 0), COALESCE(l.ID_ITEM, 0), "
                    "COALESCE(l.ID_MOTIVODEVOLUCAO, 0), "
                    "CASE WHEN d.DATACANCELAMENTO IS NULL THEN 0 ELSE 1 END, "
                    "SUM(l.VALORTOTALITEM), SUM(l.QUANTIDADE) "
                    "FROM DEVOLUCOESVENDA d JOIN LISTADEVOLUCAOVENDA l ON l.ID_DEVOLUCAO = d.ID_DEVOLUCAO "
                    "WHERE d.ENTRADA >= ? AND d.ENTRADA < ? GROUP BY 1, 2, 3, 4, 5", (de, ate))]
            self.estado["etapa"] = "Lendo cadastros"
            dados["produtos"] = bd.consulta(
                "SELECT p.ID_PRODUTO, p.NOME, p.ID_LINHA, l.NOME, p.UNIDADE, COALESCE(p.INATIVO, 0) "
                "FROM PRODUTOS p LEFT JOIN LINHASPRODUCAO l ON l.ID_LINHA = p.ID_LINHA")
            dados["vendedores"] = bd.consulta(
                "SELECT v.ID_VENDEDOR, v.NOME, v.ID_SUPERVISOR, s.NOME, COALESCE(v.INATIVO, 0) "
                "FROM VENDEDORES v LEFT JOIN SUPERVISOR s ON s.ID_SUPERVISOR = v.ID_SUPERVISOR")
            dados["motivos"] = bd.consulta("SELECT ID_MOTIVODEVOLUCAO, NOME FROM MOTIVODEVOLUCAO")
        datas = [r[0] for r in dados["vendas_itens"] if r[0] <= hoje]
        dados["info"] = [
            ("data_ref", max(datas).isoformat() if datas else hoje.isoformat()),
            ("extraido_em", dt.datetime.now().isoformat(timespec="seconds")),
            ("banco_mtime", str(banco_mtime)),
            ("banco_copia", dt.datetime.fromtimestamp(banco_mtime).isoformat(timespec="minutes")),
            ("inicio", self.inicio.isoformat()),
        ]
        return dados

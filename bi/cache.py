"""Cache local (DuckDB) com os dados do ERP que as páginas do painel usam.

A extração lê a cópia do Firebird numa transação somente leitura, agrega por dia/vendedor/produto (e, para o
Assistente, também por cliente) e grava um arquivo novo; só depois troca o cache em uso. Enquanto atualiza, o painel continua respondendo com o
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

log = logging.getLogger("bi.cache")
SENHA_EXEMPLO = "COLOQUE_A_SENHA_AQUI"  # a de config.exemplo.ini


class SemSenhaDoBanco(RuntimeError):
    pass

TABELAS = {
    "vendas_itens": "data DATE, id_vendedor INTEGER, id_produto INTEGER, valor DOUBLE, quantidade DOUBLE",
    "vendas_clientes": "data DATE, id_vendedor INTEGER, id_cliente INTEGER, tipocliente VARCHAR, vendas INTEGER",
    # venda bruta por mês, cliente e produto: as Projeções somam pelo vendedor do cliente (a carteira). Venda a
    # funcionário, fornecedor ou produtor (tipocliente) usa o código do cadastro deles, não o de CLIENTES.
    "vendas_clientes_mes": "mes DATE, id_cliente INTEGER, tipocliente VARCHAR, id_produto INTEGER, valor DOUBLE",
    "devolucoes_itens": ("data DATE, id_vendedor INTEGER, id_produto INTEGER, id_motivo INTEGER, "
                         "cancelada BOOLEAN, valor DOUBLE, quantidade DOUBLE"),
    "produtos": "id INTEGER, nome VARCHAR, id_linha INTEGER, linha VARCHAR, unidade VARCHAR, inativo INTEGER",
    "vendedores": "id INTEGER, nome VARCHAR, id_supervisor INTEGER, supervisor VARCHAR, inativo INTEGER",
    "clientes": "id INTEGER, nome VARCHAR, id_vendedor INTEGER",
    "motivos": "id INTEGER, nome VARCHAR",
    "info": "chave VARCHAR, valor VARCHAR",
}
# Detalhe por cliente e por dia, para a página Assistente (venda líquida de cada cliente). Fica fora de TABELAS: um
# cache sem estas tabelas continua valendo para Metas e Projeções, e o VPS com o código anterior aceita o pacote
# novo (só confere as tabelas que conhece). Os totais batem com vendas_itens e devolucoes_itens.
TABELAS_DETALHE = {
    "vendas_clientes_itens": ("data DATE, id_vendedor INTEGER, id_cliente INTEGER, tipocliente VARCHAR, "
                              "id_produto INTEGER, valor DOUBLE, quantidade DOUBLE"),
    "devolucoes_clientes_itens": ("data DATE, id_vendedor INTEGER, id_cliente INTEGER, tipocliente VARCHAR, "
                                  "id_produto INTEGER, id_motivo INTEGER, cancelada BOOLEAN, valor DOUBLE, "
                                  "quantidade DOUBLE"),
    # Sem CPF/CNPJ, telefone, endereço ou limite de crédito: estes dados vão para a IA do Assistente.
    "clientes_detalhes": ("id INTEGER, razao_social VARCHAR, cidade VARCHAR, uf VARCHAR, id_area INTEGER, "
                          "area VARCHAR, id_segmento INTEGER, segmento VARCHAR, inativo INTEGER, data_cadastro DATE"),
}
# Pedidos de venda (PEDIDOVENDAS), para a efetividade das campanhas da Gestão (pedidos ÷ visitas esperadas, como no
# Power BI). Também opcional, como o detalhe: um cache sem ela vale para o resto, e a efetividade avisa que falta.
TABELAS_PEDIDOS = {
    "pedidos_venda": ("data DATE, id_vendedor INTEGER, id_cliente INTEGER, tipocliente VARCHAR, tipopedido VARCHAR, "
                      "cancelada INTEGER, pedidos INTEGER, total DOUBLE"),
}


def _data(v):
    if isinstance(v, dt.datetime):
        return v.date()
    return v


def _colunas(colunas: str) -> list[str]:
    return [c.split()[0] for c in colunas.split(", ")]


def _tabela_diferente(con: duckdb.DuckDBPyConnection, tabelas: dict[str, str] = TABELAS,
                      faltar_pode: bool = False) -> str | None:
    """A primeira tabela de `tabelas` que falta no cache ou tem outras colunas (None = formato atual).
    Com faltar_pode, só as que existem com outras colunas contam."""
    existentes = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    for nome, colunas in tabelas.items():
        if nome not in existentes:
            if faltar_pode:
                continue
            return nome
        if [r[0] for r in con.execute(f"DESCRIBE {nome}").fetchall()] != _colunas(colunas):
            return nome
    return None


class Cache:
    def __init__(self, ini: configparser.ConfigParser, raiz: Path):
        self.ini = ini
        # "dados\cache.duckdb" no config: a barra invertida do Windows viraria parte do nome no Linux (VPS).
        self.arquivo = raiz / ini.get("cache", "arquivo", fallback="dados/cache.duckdb").replace("\\", "/")
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.inicio = dt.date.fromisoformat(ini.get("cache", "inicio", fallback="2024-01-01"))
        self.banco = Path(ini.get("banco", "arquivo"))
        self._con: duckdb.DuckDBPyConnection | None = None
        self._trava = threading.RLock()
        self._trava_extracao = threading.Lock()
        self.estado = {"atualizando": False, "etapa": None, "erro": None, "inicio": None, "duracao": None}
        self.info: dict[str, str] = {}
        self.antigo = False  # cache de uma versão anterior do painel (falta tabela): precisa extrair de novo
        self.sem_detalhe = False  # falta o detalhe por cliente do Assistente (Metas e Projeções funcionam)
        self.sem_pedidos = False  # faltam os pedidos de venda (só a efetividade das campanhas precisa)
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

    def df(self, sql: str, params: list | tuple = ()) -> pd.DataFrame:
        """Como consulta(), mas em DataFrame (para copiar muitas linhas de uma vez)."""
        with self._trava:
            if self._con is None:
                raise RuntimeError("os dados ainda estão sendo preparados")
            return self._con.execute(sql, list(params)).df()

    def _abrir(self) -> None:
        con = duckdb.connect(str(self.arquivo), read_only=True)
        info = dict(con.execute("SELECT chave, valor FROM info").fetchall())
        antigo = _tabela_diferente(con) is not None
        sem_detalhe = _tabela_diferente(con, TABELAS_DETALHE) is not None
        sem_pedidos = _tabela_diferente(con, TABELAS_PEDIDOS) is not None
        with self._trava:
            if self._con is not None:
                self._con.close()
            self._con = con
            self.info = info
            self.antigo = antigo
            self.sem_detalhe = sem_detalhe
            self.sem_pedidos = sem_pedidos

    def data_ref(self) -> dt.date | None:
        v = self.info.get("data_ref")
        return dt.date.fromisoformat(v) if v else None

    def conteudo(self) -> bytes:
        """O arquivo do cache inteiro (para enviar ao VPS), lido sem deixar uma troca acontecer no meio."""
        with self._trava:
            return self.arquivo.read_bytes()

    @staticmethod
    def conferir(arquivo: Path) -> dict[str, str]:
        """Abre um cache vindo de fora e confere se tem todas as tabelas; devolve a tabela info. O detalhe por
        cliente e os pedidos podem faltar (pacote do PC com o código anterior), mas, se vierem, têm de estar no
        formato atual."""
        con = duckdb.connect(str(arquivo), read_only=True)
        try:
            nome = (_tabela_diferente(con) or _tabela_diferente(con, TABELAS_DETALHE, faltar_pode=True)
                    or _tabela_diferente(con, TABELAS_PEDIDOS, faltar_pode=True))
            if nome:
                raise ValueError(f"a tabela {nome} do cache recebido não tem as colunas esperadas")
            info = dict(con.execute("SELECT chave, valor FROM info").fetchall())
        finally:
            con.close()
        if not info.get("data_ref") or not info.get("extraido_em"):
            raise ValueError("o cache recebido não diz de quando são os dados")
        return info

    def trocar(self, novo: Path) -> None:
        """Põe `novo` no lugar do cache em uso. As consultas esperam a troca terminar."""
        with self._trava:
            if self._con is not None:
                self._con.close()
                self._con = None
            os.replace(novo, self.arquivo)
            self._abrir()

    def desatualizado(self) -> bool:
        """True se a cópia do banco é mais nova que a usada no cache, ou se o cache é de uma versão anterior. Pedidos
        que não deu para ler (pedidos_erro) esperam a próxima cópia, em vez de extrair tudo de novo a cada minuto."""
        try:
            mtime = self.banco.stat().st_mtime
        except OSError:
            return False
        return (self._con is None or self.antigo or self.sem_detalhe
                or (self.sem_pedidos and not self.info.get("pedidos_erro"))
                or float(self.info.get("banco_mtime", 0)) < mtime - 1)

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
            pedidos = {k: v for k, v in TABELAS_PEDIDOS.items() if k in dados}  # a leitura pode ter falhado
            for nome, colunas in {**TABELAS, **TABELAS_DETALHE, **pedidos}.items():
                con.execute(f"CREATE TABLE {nome} ({colunas})")
                linhas = dados.pop(nome)  # solta a lista assim que gravar (o detalhe tem ~1 milhão de linhas)
                if linhas:
                    df = pd.DataFrame(linhas, columns=_colunas(colunas))
                    del linhas
                    con.register("df_tmp", df)
                    con.execute(f"INSERT INTO {nome} SELECT * FROM df_tmp")
                    con.unregister("df_tmp")
                    del df
            con.execute("CREATE INDEX ix_vi ON vendas_itens (data)")
            con.execute("CREATE INDEX ix_vc ON vendas_clientes (data)")
            con.execute("CREATE INDEX ix_di ON devolucoes_itens (data)")
            con.execute("CREATE INDEX ix_vci ON vendas_clientes_itens (data)")
            con.execute("CREATE INDEX ix_dci ON devolucoes_clientes_itens (data)")
            if pedidos:
                con.execute("CREATE INDEX ix_pv ON pedidos_venda (data)")
            self._conferir_detalhe(con)
            con.close()
            self.trocar(novo)
            self.estado["duracao"] = round(time.time() - t0, 1)
            log.info("cache atualizado em %.1f s (dados até %s)", time.time() - t0, self.info.get("data_ref"))
        except Exception as e:
            if isinstance(e, SemSenhaDoBanco):
                log.warning("%s", e)
            else:
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

    @staticmethod
    def _conferir_detalhe(con: duckdb.DuckDBPyConnection) -> None:
        """O detalhe por cliente agrupa as mesmas linhas do ERP de outro jeito: os totais têm de bater."""
        for detalhe, base in (("vendas_clientes_itens", "vendas_itens"), ("devolucoes_clientes_itens", "devolucoes_itens")):
            a, b = (con.execute(f"SELECT COALESCE(SUM(valor), 0) FROM {t}").fetchone()[0] for t in (detalhe, base))
            if abs(a - b) > 1:
                log.warning("o total de %s (%.2f) não bate com o de %s (%.2f)", detalhe, a, base, b)

    def _extrair(self) -> dict[str, list]:
        from .fb import BancoSomenteLeitura  # só aqui: o VPS não tem Firebird (nem Windows)

        b = self.ini["banco"]
        if b.get("senha", SENHA_EXEMPLO) in ("", SENHA_EXEMPLO):
            raise SemSenhaDoBanco("falta a senha do banco: copie config.exemplo.ini para config.ini e "
                                  "preencha a senha em [banco]")
        hoje = dt.date.today()
        de = dt.datetime.combine(self.inicio, dt.time())
        ate = dt.datetime.combine(hoje + dt.timedelta(days=1), dt.time())  # descarta datas digitadas erradas no futuro
        copia_mtime = self.banco.stat().st_mtime  # quando a cópia chegou (antes do Firebird mexer no arquivo)
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
            self.estado["etapa"] = "Lendo vendas por cliente"
            dados["vendas_clientes_mes"] = [
                (dt.date(int(a), int(m), 1), c, t, p, float(val or 0)) for a, m, c, t, p, val in bd.consulta(
                    "SELECT EXTRACT(YEAR FROM v.DATA), EXTRACT(MONTH FROM v.DATA), v.ID_CLIENTE, v.TIPOCLIENTE, "
                    "COALESCE(l.ID_ITEM, 0), SUM(l.VALORTOTALITEM) "
                    "FROM VENDAS v JOIN LISTAVENDA l ON l.ID_VENDA = v.ID_VENDA "
                    "WHERE v.DATA >= ? AND v.DATA < ? AND v.DATACANCELAMENTO IS NULL "
                    "GROUP BY 1, 2, 3, 4, 5", (de, ate))]
            self.estado["etapa"] = "Lendo devoluções"
            dados["devolucoes_itens"] = [
                (_data(d), v, p, m, bool(c), float(val or 0), float(q or 0)) for d, v, p, m, c, val, q in bd.consulta(
                    "SELECT CAST(d.ENTRADA AS DATE), COALESCE(d.ID_VENDEDOR, 0), COALESCE(l.ID_ITEM, 0), "
                    "COALESCE(l.ID_MOTIVODEVOLUCAO, 0), "
                    "CASE WHEN d.DATACANCELAMENTO IS NULL THEN 0 ELSE 1 END, "
                    "SUM(l.VALORTOTALITEM), SUM(l.QUANTIDADE) "
                    "FROM DEVOLUCOESVENDA d JOIN LISTADEVOLUCAOVENDA l ON l.ID_DEVOLUCAO = d.ID_DEVOLUCAO "
                    "WHERE d.ENTRADA >= ? AND d.ENTRADA < ? GROUP BY 1, 2, 3, 4, 5", (de, ate))]
            self.estado["etapa"] = "Lendo vendas por cliente e dia"
            dados["vendas_clientes_itens"] = [
                (_data(d), v, c, t, p, float(val or 0), float(q or 0)) for d, v, c, t, p, val, q in bd.consulta(
                    "SELECT CAST(v.DATA AS DATE), COALESCE(v.ID_VENDEDOR, 0), v.ID_CLIENTE, v.TIPOCLIENTE, "
                    "COALESCE(l.ID_ITEM, 0), SUM(l.VALORTOTALITEM), SUM(l.QUANTIDADE) "
                    "FROM VENDAS v JOIN LISTAVENDA l ON l.ID_VENDA = v.ID_VENDA "
                    "WHERE v.DATA >= ? AND v.DATA < ? AND v.DATACANCELAMENTO IS NULL "
                    "GROUP BY 1, 2, 3, 4, 5", (de, ate))]
            self.estado["etapa"] = "Lendo devoluções por cliente"
            dados["devolucoes_clientes_itens"] = [
                (_data(d), v, c, t, p, m, bool(cc), float(val or 0), float(q or 0))
                for d, v, c, t, p, m, cc, val, q in bd.consulta(
                    "SELECT CAST(d.ENTRADA AS DATE), COALESCE(d.ID_VENDEDOR, 0), d.ID_CLIENTE, d.TIPOCLIENTE, "
                    "COALESCE(l.ID_ITEM, 0), COALESCE(l.ID_MOTIVODEVOLUCAO, 0), "
                    "CASE WHEN d.DATACANCELAMENTO IS NULL THEN 0 ELSE 1 END, "
                    "SUM(l.VALORTOTALITEM), SUM(l.QUANTIDADE) "
                    "FROM DEVOLUCOESVENDA d JOIN LISTADEVOLUCAOVENDA l ON l.ID_DEVOLUCAO = d.ID_DEVOLUCAO "
                    "WHERE d.ENTRADA >= ? AND d.ENTRADA < ? GROUP BY 1, 2, 3, 4, 5, 6, 7", (de, ate))]
            self.estado["etapa"] = "Lendo cadastros"
            dados["clientes_detalhes"] = [
                (i, rs, cid, uf, ar, nar, sg, nsg, int(ina or 0), _data(dc))
                for i, rs, cid, uf, ar, nar, sg, nsg, ina, dc in bd.consulta(
                    "SELECT c.ID_CLIENTE, c.RAZAOSOCIAL, c.CIDADE, c.ESTADO, c.ID_AREA, a.NOME, c.ID_SEGMENTO, s.NOME, "
                    "c.INATIVO, c.DATACADASTRO FROM CLIENTES c "
                    "LEFT JOIN AREASCOMERCIAIS a ON a.ID_AREA = c.ID_AREA "
                    "LEFT JOIN SEGMENTO s ON s.ID_SEGMENTO = c.ID_SEGMENTO")]
            dados["produtos"] = bd.consulta(
                "SELECT p.ID_PRODUTO, p.NOME, p.ID_LINHA, l.NOME, p.UNIDADE, COALESCE(p.INATIVO, 0) "
                "FROM PRODUTOS p LEFT JOIN LINHASPRODUCAO l ON l.ID_LINHA = p.ID_LINHA")
            dados["vendedores"] = bd.consulta(
                "SELECT v.ID_VENDEDOR, v.NOME, v.ID_SUPERVISOR, s.NOME, COALESCE(v.INATIVO, 0) "
                "FROM VENDEDORES v LEFT JOIN SUPERVISOR s ON s.ID_SUPERVISOR = v.ID_SUPERVISOR")
            dados["clientes"] = bd.consulta("SELECT ID_CLIENTE, NOME, COALESCE(ID_VENDEDOR, 0) FROM CLIENTES")
            dados["motivos"] = bd.consulta("SELECT ID_MOTIVODEVOLUCAO, NOME FROM MOTIVODEVOLUCAO")
            # Por último e à parte: se a tabela de pedidos mudar no ERP, o resto do painel não para.
            self.estado["etapa"] = "Lendo pedidos de venda"
            pedidos_erro = None
            try:
                dados["pedidos_venda"] = [
                    (_data(d), v, c, t, tp, None if ca is None else int(ca), n, float(tot or 0))
                    for d, v, c, t, tp, ca, n, tot in bd.consulta(
                        "SELECT CAST(p.DATA AS DATE), COALESCE(p.ID_VENDEDOR, 0), p.ID_CLIENTE, p.TIPOCLIENTE, "
                        "p.TIPOPEDIDO, p.CANCELADA, COUNT(*), SUM(p.TOTAL) FROM PEDIDOVENDAS p "
                        "WHERE p.DATA >= ? AND p.DATA < ? GROUP BY 1, 2, 3, 4, 5, 6", (de, ate))]
            except Exception as e:
                log.warning("não deu para ler os pedidos de venda (a efetividade das campanhas fica sem dados): %s", e)
                pedidos_erro = str(e)[:300]
        # Conectar regrava o cabeçalho do .GDB e muda a data do arquivo. Guardar a data de antes fazia cada
        # extração parecer uma cópia nova (e o painel extraía de novo a cada minuto); a de depois fica parada.
        banco_mtime = self.banco.stat().st_mtime
        datas =[r[0] for r in dados["vendas_itens"] if r[0] <= hoje]
        dados["info"] = [
            ("data_ref", max(datas).isoformat() if datas else hoje.isoformat()),
            ("extraido_em", dt.datetime.now().isoformat(timespec="seconds")),
            ("banco_mtime", str(banco_mtime)),
            ("banco_copia", dt.datetime.fromtimestamp(copia_mtime).isoformat(timespec="minutes")),
            ("inicio", self.inicio.isoformat()),
            *([("pedidos_erro", pedidos_erro)] if pedidos_erro else []),
        ]
        return dados

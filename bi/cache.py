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
    # Sem CPF/CNPJ, telefone ou endereço: estes dados vão para a IA do Assistente. O limite de crédito fica à parte,
    # em TABELAS_CREDITO.
    "clientes_detalhes": ("id INTEGER, razao_social VARCHAR, cidade VARCHAR, uf VARCHAR, id_area INTEGER, "
                          "area VARCHAR, id_segmento INTEGER, segmento VARCHAR, inativo INTEGER, data_cadastro DATE"),
}
# Pedidos de venda (PEDIDOVENDAS), para a efetividade das campanhas da Gestão (pedidos ÷ visitas esperadas, como no
# Power BI). Também opcional, como o detalhe: um cache sem ela vale para o resto, e a efetividade avisa que falta.
TABELAS_PEDIDOS = {
    "pedidos_venda": ("data DATE, id_vendedor INTEGER, id_cliente INTEGER, tipocliente VARCHAR, tipopedido VARCHAR, "
                      "cancelada INTEGER, pedidos INTEGER, total DOUBLE"),
}
# A rede de cada cliente (CLIENTES.ID_REDE -> REDES.NOME). As redes SEMANAL, QUINZENAL e MENSAL são a frequência de
# compra, para as visitas esperadas da efetividade. Opcional como os pedidos: sem ela, todo cliente conta como semanal.
TABELAS_REDE = {
    "clientes_rede": "id INTEGER, rede VARCHAR",
}
# Crédito, para a página Reavaliação de Crédito (e o Assistente de quem tem a página). Os títulos a receber de venda
# a cliente que não foram cancelados (o filtro de todas as medidas da página no Power BI), desde o primeiro, e o
# limite e o prazo (OPCAOPAGAMENTO) de cada cliente. Opcional como os pedidos.
TABELAS_CREDITO = {
    "titulos_receber": ("id INTEGER, id_cliente INTEGER, id_vendedor INTEGER, emissao DATE, vencimento DATE, "
                        "quitacao DATE, quitado INTEGER, total DOUBLE"),
    "clientes_credito": "id INTEGER, limite DOUBLE, prazo VARCHAR",
}
# As parcelas de cada título (PARCELASCONTASRECEBER): quantas são, quantas já foram quitadas e quanto do título já foi
# pago (o valor das parcelas quitadas mais o que entrou numa parcela paga em parte; juros e abatimento ficam fora).
# Grupo à parte do crédito: um cache sem ela (PC com o código anterior) vale, e a página conta tudo como não pago.
TABELAS_PARCELAS = {
    "titulos_parcelas": "id INTEGER, parcelas INTEGER, pagas INTEGER, pago DOUBLE",
}
# O histórico da carteira (bi/carteira.py): os trechos de cada cliente ativo e os dias conferidos. Não vem do ERP: o PC
# registra no PostgreSQL a cada extração e copia para o cache, que leva ao VPS. Opcional como os pedidos: sem ela, a
# cobertura da positivação dos meses do histórico espera os dados.
TABELAS_CARTEIRA = {
    "clientes_vigencias": ("id_cliente INTEGER, de DATE, ate DATE, id_vendedor INTEGER, bloqueado BOOLEAN, uf VARCHAR, "
                           "id_area INTEGER, area VARCHAR, segmento VARCHAR"),
    "carteira_retratos": "data DATE, ativos INTEGER, entradas INTEGER, saidas INTEGER, trocas INTEGER",
}
# Brindes (BRINDES + LISTABRINDE) não cancelados, por dia, cliente, produto e motivo, para a premiação dos supervisores
# (página Premiações): o Power BI desconta os brindes do faturamento líquido e conta os de motivo impróprio (ex.:
# "Brinde - vencido") nas devoluções impróprias. Opcional como os pedidos: sem ela, a página avisa e conta sem brindes.
TABELAS_BRINDES = {
    "brindes_clientes_itens": ("data DATE, id_vendedor INTEGER, id_cliente INTEGER, tipocliente VARCHAR, "
                               "id_produto INTEGER, id_motivo INTEGER, valor DOUBLE, quantidade DOUBLE"),
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
        self.sem_rede = False  # falta a rede (frequência) dos clientes: a efetividade conta todos como semanais
        self.sem_credito = False  # faltam os títulos a receber e os limites (só a Reavaliação de Crédito precisa)
        self.sem_parcelas = False  # faltam as parcelas dos títulos: o crédito conta tudo como não pago
        self.sem_carteira = False  # falta o histórico da carteira (só a cobertura da positivação precisa)
        self.sem_brindes = False  # faltam os brindes: a premiação dos supervisores conta sem eles
        # O registro da carteira na extração (bi/carteira.py Carteira, que o painel do PC entrega depois de criar o
        # banco): (ativos, cadastro, data, tabelas do cache anterior) -> as tabelas para o cache novo. None: leva as do
        # cache anterior.
        self.carteira = None
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
        sem_rede = _tabela_diferente(con, TABELAS_REDE) is not None
        sem_credito = _tabela_diferente(con, TABELAS_CREDITO) is not None
        sem_parcelas = _tabela_diferente(con, TABELAS_PARCELAS) is not None
        sem_carteira = _tabela_diferente(con, TABELAS_CARTEIRA) is not None
        sem_brindes = _tabela_diferente(con, TABELAS_BRINDES) is not None
        with self._trava:
            if self._con is not None:
                self._con.close()
            self._con = con
            self.info = info
            self.antigo = antigo
            self.sem_detalhe = sem_detalhe
            self.sem_pedidos = sem_pedidos
            self.sem_rede = sem_rede
            self.sem_credito = sem_credito
            self.sem_parcelas = sem_parcelas
            self.sem_carteira = sem_carteira
            self.sem_brindes = sem_brindes

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
        cliente, os pedidos, a rede, o crédito, a carteira e os brindes podem faltar (pacote do PC com o código
        anterior), mas, se vierem, têm de estar no formato atual."""
        con = duckdb.connect(str(arquivo), read_only=True)
        try:
            nome = (_tabela_diferente(con) or _tabela_diferente(con, TABELAS_DETALHE, faltar_pode=True)
                    or _tabela_diferente(con, TABELAS_PEDIDOS, faltar_pode=True)
                    or _tabela_diferente(con, TABELAS_REDE, faltar_pode=True)
                    or _tabela_diferente(con, TABELAS_CREDITO, faltar_pode=True)
                    or _tabela_diferente(con, TABELAS_PARCELAS, faltar_pode=True)
                    or _tabela_diferente(con, TABELAS_CARTEIRA, faltar_pode=True)
                    or _tabela_diferente(con, TABELAS_BRINDES, faltar_pode=True))
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
        """True se a cópia do banco é mais nova que a usada no cache, ou se o cache é de uma versão anterior. Pedidos,
        redes, crédito, parcelas, a carteira ou os brindes que não deu para ler ou registrar (pedidos_erro, rede_erro,
        credito_erro, parcelas_erro, carteira_erro, brindes_erro) esperam a próxima cópia, em vez de extrair tudo de
        novo a cada minuto."""
        try:
            mtime = self.banco.stat().st_mtime
        except OSError:
            return False
        return (self._con is None or self.antigo or self.sem_detalhe
                or (self.sem_pedidos and not self.info.get("pedidos_erro"))
                or (self.sem_rede and not self.info.get("rede_erro"))
                or (self.sem_credito and not self.info.get("credito_erro"))
                or (self.sem_parcelas and not self.info.get("parcelas_erro"))
                or (self.sem_carteira and not self.info.get("carteira_erro"))
                or (self.sem_brindes and not self.info.get("brindes_erro"))
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
            self.estado["etapa"] = "Registrando a carteira"
            self._carteira(dados)
            self.estado["etapa"] = "Gravando cache local"
            if novo.exists():
                novo.unlink()
            con = duckdb.connect(str(novo))
            # pedidos, rede, crédito, parcelas, carteira e brindes: a leitura (ou o registro) pode ter falhado
            opcionais = {k: v for k, v in {**TABELAS_PEDIDOS, **TABELAS_REDE, **TABELAS_CREDITO,
                                           **TABELAS_PARCELAS, **TABELAS_CARTEIRA, **TABELAS_BRINDES}.items()
                         if k in dados}
            pedidos = "pedidos_venda" in opcionais
            for nome, colunas in {**TABELAS, **TABELAS_DETALHE, **opcionais}.items():
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
            if "titulos_receber" in opcionais:
                con.execute("CREATE INDEX ix_tr ON titulos_receber (id_cliente)")
            if "titulos_parcelas" in opcionais:
                con.execute("CREATE INDEX ix_tp ON titulos_parcelas (id)")
            if "brindes_clientes_itens" in opcionais:
                con.execute("CREATE INDEX ix_bci ON brindes_clientes_itens (data)")
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

    def _carteira_anterior(self) -> dict[str, list] | None:
        """As tabelas da carteira do cache em uso (None se ele não tem)."""
        if self._con is None or self.sem_carteira:
            return None
        try:
            return {nome: self.consulta(f"SELECT {', '.join(_colunas(colunas))} FROM {nome}")
                    for nome, colunas in TABELAS_CARTEIRA.items()}
        except Exception as e:  # o cache mudou no meio: a carteira fica para a próxima
            log.warning("não deu para ler a carteira do cache em uso: %s", e)
            return None

    def _carteira(self, dados: dict[str, list]) -> None:
        """Registra a carteira do dia da cópia (bi/carteira.py) e põe as tabelas dela nos dados do cache novo. Sem o
        banco (fora do ar ou sem o registro), leva as do cache em uso e marca carteira_erro: a extração e o envio ao
        VPS não dependem do banco."""
        from .carteira import estado

        anterior = self._carteira_anterior()
        try:
            if self.carteira is None:
                raise RuntimeError("o registro da carteira não foi ligado ao banco de dados")
            ativos, cadastro = estado(dados["clientes"], dados["clientes_detalhes"])
            data = dt.date.fromisoformat(dict(dados["info"])["banco_copia"][:10])
            dados.update(self.carteira(ativos, cadastro, data, anterior))
        except Exception as e:
            log.warning("não deu para registrar a carteira (o cache leva a do anterior): %s", e)
            dados["info"].append(("carteira_erro", str(e)[:300]))
            if anterior:
                dados.update(anterior)

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
            # A rede de cada cliente (frequência de compra da efetividade), também à parte.
            self.estado["etapa"] = "Lendo as redes dos clientes"
            rede_erro = None
            try:
                dados["clientes_rede"] = bd.consulta(
                    "SELECT c.ID_CLIENTE, r.NOME FROM CLIENTES c JOIN REDES r ON r.ID_REDE = c.ID_REDE")
            except Exception as e:
                log.warning("não deu para ler as redes dos clientes (a efetividade conta todos como semanais): %s", e)
                rede_erro = str(e)[:300]
            # Títulos a receber e limites (Reavaliação de Crédito), também à parte. Todo o histórico, como no Power
            # BI; a data de emissão vem com hora zero, e as datas digitadas erradas (ano 7190) ficam como estão.
            self.estado["etapa"] = "Lendo os títulos a receber"
            credito_erro = None
            try:
                titulos = [
                    (i, c, v, _data(e), _data(ve), _data(q), int(qt or 0), float(t or 0))
                    for i, c, v, e, ve, q, qt, t in bd.consulta(
                        "SELECT ID_CONTARECEBER, ID_CLIENTE, COALESCE(ID_VENDEDOR, 0), CAST(DATAEMISSAO AS DATE), "
                        "CAST(VENCIMENTO AS DATE), CAST(DATAQUITACAO AS DATE), QUITADO, TOTAL FROM CONTASRECEBER "
                        "WHERE DATACANCELAMENTO IS NULL AND TIPOCLIENTE = 'CLIENTE' AND ORIGEM = 'VENDA'")]
                limites = [(i, float(lim or 0), p) for i, lim, p in bd.consulta(
                    "SELECT c.ID_CLIENTE, c.LIMITECREDITO, o.NOME FROM CLIENTES c "
                    "LEFT JOIN OPCAOPAGAMENTO o ON o.ID_OPCAO = c.ID_OPCAOPAGAMENTO")]
                dados["titulos_receber"], dados["clientes_credito"] = titulos, limites
            except Exception as e:
                log.warning("não deu para ler os títulos a receber (a Reavaliação de Crédito fica sem dados): %s", e)
                credito_erro = str(e)[:300]
            # As parcelas dos mesmos títulos (boleto dividido em 7, 14, 21 dias...), também à parte.
            self.estado["etapa"] = "Lendo as parcelas dos títulos"
            parcelas_erro = None
            try:
                dados["titulos_parcelas"] = [
                    (i, int(n or 0), int(pg or 0), float(v or 0)) for i, n, pg, v in bd.consulta(
                        "SELECT p.ID_CONTARECEBER, COUNT(*), SUM(CASE WHEN p.QUITADO = 1 THEN 1 ELSE 0 END), "
                        "SUM(CASE WHEN p.QUITADO = 1 THEN p.VALORRECEBER "
                        "WHEN COALESCE(p.VALORRECEBIDO, 0) < p.VALORRECEBER THEN COALESCE(p.VALORRECEBIDO, 0) "
                        "ELSE p.VALORRECEBER END) "
                        "FROM PARCELASCONTASRECEBER p JOIN CONTASRECEBER c ON c.ID_CONTARECEBER = p.ID_CONTARECEBER "
                        "WHERE c.DATACANCELAMENTO IS NULL AND c.TIPOCLIENTE = 'CLIENTE' AND c.ORIGEM = 'VENDA' "
                        "GROUP BY p.ID_CONTARECEBER")]
            except Exception as e:
                log.warning("não deu para ler as parcelas dos títulos (o crédito conta tudo como não pago): %s", e)
                parcelas_erro = str(e)[:300]
            # Os brindes (premiação dos supervisores), também à parte. Os sem cliente (transferências, consumo
            # interno) não entram em nenhuma carteira.
            self.estado["etapa"] = "Lendo os brindes"
            brindes_erro = None
            try:
                dados["brindes_clientes_itens"] = [
                    (_data(d), v, c, t, p, m, float(val or 0), float(q or 0))
                    for d, v, c, t, p, m, val, q in bd.consulta(
                        "SELECT CAST(b.DATA AS DATE), COALESCE(b.ID_VENDEDOR, 0), b.ID_CLIENTE, b.TIPOCLIENTE, "
                        "COALESCE(l.ID_ITEM, 0), COALESCE(b.ID_MOTIVO, 0), SUM(l.VALORTOTALITEM), SUM(l.QUANTIDADE) "
                        "FROM BRINDES b JOIN LISTABRINDE l ON l.ID_BRINDE = b.ID_BRINDE "
                        "WHERE b.DATA >= ? AND b.DATA < ? AND b.DATACANCELAMENTO IS NULL AND b.ID_CLIENTE IS NOT NULL "
                        "GROUP BY 1, 2, 3, 4, 5, 6", (de, ate))]
            except Exception as e:
                log.warning("não deu para ler os brindes (a premiação dos supervisores conta sem eles): %s", e)
                brindes_erro = str(e)[:300]
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
            *([("rede_erro", rede_erro)] if rede_erro else []),
            *([("credito_erro", credito_erro)] if credito_erro else []),
            *([("parcelas_erro", parcelas_erro)] if parcelas_erro else []),
            *([("brindes_erro", brindes_erro)] if brindes_erro else []),
        ]
        return dados

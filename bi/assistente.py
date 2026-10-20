"""Assistente: perguntas em português sobre vendas, devoluções, clientes, produtos e metas, respondidas pelo Claude
(API da Anthropic) com consultas ao cache.

Como funciona:
- Recorte: cada acesso (os vendedores que a pessoa pode ver) ganha um DuckDB em memória só com as linhas desses
  vendedores e com as regras das metas já aplicadas (equivalência de produto, grupos, categorias, motivos de
  devolução que descontam). A IA só consulta esse recorte: o que está fora dele não existe para ela, seja qual for
  o SQL. Arquivos, extensões e configurações ficam travados, e cada consulta tem tempo e linhas limitados.
  Exceção: as ferramentas de ações (listar, andamento e propor) usam bi/gestao.py, com o acesso da pessoa na
  página Gestão, para darem os mesmos números da página; quem não tem a Gestão recebe um erro dentro delas (e só o
  administrador propõe ações).
- Ferramentas: a IA pede as consultas (buscar cliente/produto/vendedor, resumo de vendas, metas e realizado, SQL
  somente leitura), o servidor executa no recorte e devolve o resultado; a resposta final vem em texto.
- Histórico: entre uma pergunta e outra só volta texto (pergunta, resposta e o resumo das consultas feitas). As
  conversas ficam no PostgreSQL (bi/conversas.py) e o servidor as lê de lá. Dentro de uma pergunta, cada resposta da
  API volta inteira e sem mudança (com os blocos de raciocínio), como a API exige.
- Registro: cada pergunta vai para a tabela assistente_perguntas (bi/uso.py: quem, o quê, consultas, tokens e
  custo); os limites do dia (perguntas por pessoa e custo total) são contados nela antes de cada pergunta.
"""
from __future__ import annotations

import collections
import configparser
import datetime as dt
import decimal
import hashlib
import inspect
import json
import logging
import threading
import time

import duckdb
import pandas as pd

from .banco import BancoForaDoAr
from .configuracao import VISOES
from .conversas import MAX_MENSAGENS_CONVERSA, NaoEncontrada, id_valido, novo_id
from .indicadores import (BASES as BASES_CAMPANHA, FORMAS as FORMAS_CAMPANHA, MEDIDAS as MEDIDAS_CAMPANHA,
                          TIPOS as TIPOS_CAMPANHA, semanas_da_frequencia)
from .metas import MESES, Calculadora, nome_bonito
from .projecoes import NOME_EQUIPE

log = logging.getLogger("bi.assistente")

BETA_FALLBACK = "server-side-fallback-2026-07-01"  # outro modelo refaz a resposta se o classificador recusar
ESFORCOS = ("low", "medium", "high", "xhigh", "max")
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
NOME_TIPO = {"FUNCIONARIO": "Funcionário", "FORNECEDOR": "Fornecedor", "PRODUTOR": "Produtor"}
MAX_MENSAGENS = 20
MAX_TEXTO = {"usuario": 4000, "assistente": 16000}
MAX_RESULTADO = 12000  # caracteres de um resultado de ferramenta devolvido à IA
MAX_SQL = 8000


class ErroAssistente(Exception):
    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.status = status


class ConfigIA:
    """Seção [ia] do config.ini (a chave fica só no config.ini, fora do repositório)."""

    def __init__(self, ini: configparser.ConfigParser):
        g = lambda k, d: ini.get("ia", k, fallback=d).strip()  # noqa: E731
        self.chave = g("chave", "")
        self.modelo = g("modelo", "claude-opus-5-5")
        self.esforco = g("esforco", "medium")
        if self.esforco not in ESFORCOS:
            raise SystemExit(f"[ia] esforco = {self.esforco!r} no config.ini: use {', '.join(ESFORCOS)}")
        self.max_tokens = ini.getint("ia", "max_tokens", fallback=16000)
        self.max_passos = ini.getint("ia", "max_passos", fallback=8)
        self.timeout = ini.getfloat("ia", "timeout", fallback=60)
        self.tempo_total = ini.getfloat("ia", "tempo_total", fallback=100)
        self.tempo_sql = ini.getfloat("ia", "tempo_sql", fallback=10)
        self.max_linhas = ini.getint("ia", "max_linhas", fallback=200)
        self.limite_diario = ini.getint("ia", "limite_diario", fallback=50)
        self.limite_custo_dia = ini.getfloat("ia", "limite_custo_dia", fallback=2.0)
        self.simultaneos = ini.getint("ia", "simultaneos", fallback=2)
        self.recortes = max(1, ini.getint("ia", "recortes", fallback=2))
        self.precos = {k: ini.getfloat("ia", f"preco_{k}", fallback=v) for k, v in
                       {"entrada": 4.0, "saida": 20.0, "cache_leitura": 0.20, "cache_escrita": 5.0}.items()}

    @property
    def configurado(self) -> bool:
        return bool(self.chave)


# ============================================================================================
# Recorte: os dados que um acesso enxerga
# ============================================================================================
def _marcas(ids) -> str:
    return ",".join("?" * len(ids))


class Recorte:
    """DuckDB em memória com as linhas dos vendedores do acesso (ids None = todos), montado uma vez e travado."""

    def __init__(self, calc: Calculadora, nomes: dict[int, str], ids: frozenset[int] | None):
        self.ids = ids
        self.memo: dict = {}  # contas guardadas por quem usa o recorte (o quadro da Gestão); some com ele
        t0 = time.time()
        self.con = self._montar(calc, nomes, ids)
        self.segundos = round(time.time() - t0, 2)

    def cursor(self) -> duckdb.DuckDBPyConnection:
        return self.con.cursor()

    @staticmethod
    def _montar(calc: Calculadora, nomes: dict[int, str], ids: frozenset[int] | None) -> duckdb.DuckDBPyConnection:
        cache, regras = calc.cache, calc.regras()
        filtro, params = ("", []) if ids is None else (f" WHERE id_vendedor IN ({_marcas(ids)})", sorted(ids))
        vendas = cache.df("SELECT data, id_vendedor, id_cliente, tipocliente AS tipo_cliente, id_produto, valor, "
                          "quantidade FROM vendas_clientes_itens" + filtro, params)
        devol = cache.df("SELECT data, id_vendedor, id_cliente, tipocliente AS tipo_cliente, id_produto, id_motivo, "
                         "cancelada, valor, quantidade FROM devolucoes_clientes_itens" + filtro, params)
        pedidos = cache.df("SELECT data, id_vendedor, id_cliente, tipocliente AS tipo_cliente, vendas AS pedidos "
                           "FROM vendas_clientes" + filtro, params)
        # Pedidos de venda do ERP (efetividade das campanhas da Gestão); vazia se o cache ainda não tem.
        pedidos_venda = (pd.DataFrame({"data": pd.Series(dtype="datetime64[ns]"), "id_vendedor": pd.Series(dtype="int32"),
                                       "id_cliente": pd.Series(dtype="int32"), "tipo_cliente": pd.Series(dtype="object"),
                                       "tipopedido": pd.Series(dtype="object"), "cancelada": pd.Series(dtype="Int32"),
                                       "pedidos": pd.Series(dtype="int32")})
                         if cache.sem_pedidos else
                         cache.df("SELECT data, id_vendedor, id_cliente, tipocliente AS tipo_cliente, tipopedido, cancelada, "
                                  "pedidos FROM pedidos_venda" + filtro, params))
        if regras.equivalentes:
            vendas["id_produto"] = vendas["id_produto"].replace(regras.equivalentes)
            devol["id_produto"] = devol["id_produto"].replace(regras.equivalentes)
        devol["desconta"] = devol["id_motivo"].isin(sorted(regras.motivos)) & ~(
            devol["cancelada"] & regras.ignorar_canceladas)

        produtos = cache.df("SELECT id AS id_produto, nome AS produto, linha, unidade, inativo::BOOLEAN AS inativo "
                            "FROM produtos")
        produtos["grupo"] = produtos["id_produto"].map(regras.grupo_produto)
        produtos["categoria"] = produtos["id_produto"].map(regras.categoria)

        vendedores = cache.df("SELECT id AS id_vendedor, nome AS nome_erp, supervisor, inativo::BOOLEAN AS inativo "
                              "FROM vendedores")
        nos_dados = set(vendas["id_vendedor"]) | set(devol["id_vendedor"]) | set(pedidos["id_vendedor"])
        faltam = sorted(nos_dados - set(vendedores["id_vendedor"]))
        if faltam:  # código 0 (venda sem vendedor) e vendedores apagados do cadastro
            extras = pd.DataFrame([{"id_vendedor": v, "nome_erp": "", "supervisor": "", "inativo": True} for v in faltam])
            vendedores = pd.concat([vendedores, extras.astype(vendedores.dtypes.to_dict())], ignore_index=True)
        vendedores["vendedor"] = vendedores["id_vendedor"].map(
            lambda v: nomes.get(v) or ("Sem vendedor" if v == 0 else f"Vendedor {v}"))
        vendedores["equipe"] = vendedores["id_vendedor"].map(lambda v: NOME_EQUIPE[regras.grupo_vendedor(v)])
        if ids is not None:
            vendedores = vendedores[vendedores["id_vendedor"].isin(sorted(ids))]

        # A rede (e a frequência de compra que ela diz, para a efetividade da Gestão) é opcional no cache: sem ela, fica
        # vazia (conta como semanal).
        rede = ("CAST(NULL AS VARCHAR)", "") if cache.sem_rede else ("r.rede", " LEFT JOIN clientes_rede r ON r.id = c.id")
        clientes = cache.df(
            "SELECT c.id AS id_cliente, c.nome AS cliente, d.razao_social, d.cidade, d.uf, d.id_area, d.area, d.segmento, "
            "d.inativo::BOOLEAN AS inativo, d.data_cadastro, NULLIF(c.id_vendedor, 0) AS id_vendedor_carteira, "
            f"{rede[0]} AS rede FROM clientes c LEFT JOIN clientes_detalhes d ON d.id = c.id{rede[1]}")
        clientes["vendedor_carteira"] = clientes["id_vendedor_carteira"].map(
            lambda v: None if pd.isna(v) else nomes.get(int(v), f"Vendedor {int(v)}"))
        clientes["frequencia_semanas"] = clientes["rede"].map(semanas_da_frequencia).astype("Int32")

        metas = _metas_vendedor(calc, ids)
        metas_prod = _metas_produto(calc, regras, ids)
        motivos = cache.df("SELECT id AS id_motivo, nome AS motivo FROM motivos")
        motivos["desconta"] = motivos["id_motivo"].isin(sorted(regras.motivos))

        con = duckdb.connect(":memory:", config={
            "threads": 1, "memory_limit": "192MB", "temp_directory": "",
            "autoinstall_known_extensions": False, "autoload_known_extensions": False})
        # id_cadastro: o código no cadastro de clientes (só para tipo CLIENTE). Juntar por ele é uma igualdade
        # simples; com "AND tipo_cliente = 'CLIENTE'" na junção o DuckDB compara linha a linha (segundos).
        # Ordenadas por data, as consultas de um período pulam os blocos de fora dele.
        fatos = ("CAST(data AS DATE) AS data, * EXCLUDE (data), "
                 "CASE WHEN tipo_cliente = 'CLIENTE' THEN id_cliente END AS id_cadastro")
        tabelas = {
            "_vendas": (vendas, fatos),
            "_devolucoes": (devol, fatos),
            "_pedidos": (pedidos, fatos),
            "_pedidos_venda": (pedidos_venda, "CAST(data AS DATE) AS data, * EXCLUDE (data)"),
            "produtos": (produtos, "*"),
            "vendedores": (vendedores, "id_vendedor, vendedor, nome_erp, equipe, supervisor, inativo"),
            "_clientes": (clientes, "* EXCLUDE (data_cadastro), CAST(data_cadastro AS DATE) AS data_cadastro"),
            "motivos": (motivos, "*"),
            "metas_vendedor": (metas, "*"),
            "metas_produto": (metas_prod, "*"),
        }
        for nome, (df, colunas) in tabelas.items():
            con.register("df_tmp", df)
            ordem = " ORDER BY data" if nome.startswith("_") and "data" in df.columns else ""
            con.execute(f"CREATE TABLE {nome} AS SELECT {colunas} FROM df_tmp{ordem}")
            con.unregister("df_tmp")
        data_ref = cache.data_ref() or dt.date.today()
        desde_12m = data_ref - dt.timedelta(days=365)
        # Quem tem acesso restrito só encontra os clientes que aparecem nas linhas dele ou na carteira dos vendedores dele.
        so_do_acesso = "" if ids is None else (
            f"WHERE k.id_cliente IS NOT NULL OR c.id_vendedor_carteira IN ({','.join(str(int(i)) for i in sorted(ids))}) "
            "OR c.id_cliente IN (SELECT id_cliente FROM _devolucoes WHERE tipo_cliente = 'CLIENTE' "
            "UNION SELECT id_cliente FROM _pedidos WHERE tipo_cliente = 'CLIENTE')")
        con.execute(f"""
            CREATE TABLE clientes AS
            WITH compras AS (
                SELECT id_cliente, MIN(data) AS primeira_compra, MAX(data) AS ultima_compra,
                       SUM(CASE WHEN data > ? THEN valor ELSE 0 END) AS venda_bruta_12m
                FROM _vendas WHERE tipo_cliente = 'CLIENTE' GROUP BY 1)
            SELECT c.id_cliente, c.cliente, c.razao_social, c.cidade, c.uf, c.id_area, c.area, c.segmento, c.inativo,
                   c.data_cadastro, c.id_vendedor_carteira, c.vendedor_carteira, k.primeira_compra, k.ultima_compra,
                   COALESCE(k.venda_bruta_12m, 0) AS venda_bruta_12m, c.rede, c.frequencia_semanas
            FROM _clientes c LEFT JOIN compras k USING (id_cliente) {so_do_acesso}""", [desde_12m])
        con.execute("DROP TABLE _clientes")
        nome_cliente = ("CASE m.tipo_cliente WHEN 'CLIENTE' THEN COALESCE(c.cliente, 'Cliente cód. ' || m.id_cliente) "
                        + " ".join(f"WHEN '{k}' THEN '{v} cód. ' || m.id_cliente" for k, v in NOME_TIPO.items())
                        + " ELSE m.tipo_cliente || ' cód. ' || m.id_cliente END")
        juntar = ("LEFT JOIN vendedores v ON v.id_vendedor = m.id_vendedor "
                  "LEFT JOIN clientes c ON c.id_cliente = m.id_cadastro "
                  "LEFT JOIN produtos p ON p.id_produto = m.id_produto")
        datas = "m.data, year(m.data) AS ano, month(m.data) AS mes"
        con.execute(f"""
            CREATE VIEW faturamento AS
            WITH m AS (
                SELECT data, 'venda' AS tipo, id_vendedor, id_cliente, tipo_cliente, id_cadastro, id_produto,
                       valor AS valor_bruto, 0.0 AS valor_devolvido, quantidade FROM _vendas
                UNION ALL
                SELECT data, 'devolucao', id_vendedor, id_cliente, tipo_cliente, id_cadastro, id_produto,
                       0.0, valor, -quantidade FROM _devolucoes WHERE desconta)
            SELECT {datas}, m.tipo, m.id_vendedor, COALESCE(v.vendedor, 'Vendedor ' || m.id_vendedor) AS vendedor,
                   v.equipe, m.id_cliente, {nome_cliente} AS cliente, m.tipo_cliente, c.cidade, c.uf, c.segmento,
                   c.area, c.id_vendedor_carteira, c.vendedor_carteira, m.id_produto,
                   COALESCE(p.produto, 'Produto ' || m.id_produto) AS produto, COALESCE(p.grupo, 'outras') AS grupo,
                   p.categoria, p.linha, p.unidade, m.valor_bruto, m.valor_devolvido,
                   m.valor_bruto - m.valor_devolvido AS valor_liquido, m.quantidade
            FROM m {juntar}
            WHERE COALESCE(p.grupo, 'outras') <> 'fora'""")
        con.execute(f"""
            CREATE VIEW devolucoes AS
            SELECT {datas}, m.id_vendedor, COALESCE(v.vendedor, 'Vendedor ' || m.id_vendedor) AS vendedor,
                   m.id_cliente, {nome_cliente} AS cliente, m.tipo_cliente, c.vendedor_carteira, m.id_produto,
                   COALESCE(p.produto, 'Produto ' || m.id_produto) AS produto, COALESCE(p.grupo, 'outras') AS grupo,
                   m.id_motivo, COALESCE(mo.motivo, 'Motivo ' || m.id_motivo) AS motivo, m.cancelada, m.desconta,
                   m.valor, m.quantidade
            FROM _devolucoes m {juntar} LEFT JOIN motivos mo ON mo.id_motivo = m.id_motivo""")
        con.execute(f"""
            CREATE VIEW pedidos AS
            SELECT {datas}, m.id_vendedor, COALESCE(v.vendedor, 'Vendedor ' || m.id_vendedor) AS vendedor,
                   m.id_cliente, {nome_cliente} AS cliente, m.tipo_cliente, m.pedidos
            FROM _pedidos m LEFT JOIN vendedores v ON v.id_vendedor = m.id_vendedor
            LEFT JOIN clientes c ON c.id_cliente = m.id_cadastro""")
        # Daqui em diante: nada de arquivo, extensão nova ou mudança de configuração.
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        return con


def _metas_vendedor(calc: Calculadora, ids):
    linhas = [m for m in calc.metas.dados() if ids is None or m["id_vendedor"] in ids]
    df = pd.DataFrame(linhas, columns=["mes", "id_vendedor", "vendedor", "meta_fat", "meta_mus", "meta_out", "meta_cli"])
    df = df.groupby(["mes", "id_vendedor"], as_index=False).agg(
        vendedor=("vendedor", "last"), meta_faturamento=("meta_fat", "sum"), meta_mussarela=("meta_mus", "sum"),
        meta_outras=("meta_out", "sum"), meta_clientes=("meta_cli", "sum"))
    df["vendedor"] = df["vendedor"].map(nome_bonito)
    df.insert(0, "ano", [m.year for m in df["mes"]])
    df["mes"] = [m.month for m in df["mes"]]
    return df


def _metas_produto(calc: Calculadora, regras, ids):
    linhas = [{**m, "id_produto": regras.produto(m["id_produto"])} for m in calc.metas_produtos.dados()
              if ids is None or m["id_vendedor"] in ids]
    df = pd.DataFrame(linhas, columns=["mes", "id_vendedor", "vendedor", "id_produto", "produto", "meta_volume"])
    df = df.groupby(["mes", "id_vendedor", "id_produto"], as_index=False).agg(
        vendedor=("vendedor", "last"), produto=("produto", "last"), meta_volume=("meta_volume", "sum"))
    df["vendedor"] = df["vendedor"].map(nome_bonito)
    df.insert(0, "ano", [m.year for m in df["mes"]])
    df["mes"] = [m.month for m in df["mes"]]
    return df


# ============================================================================================
# Ferramentas
# ============================================================================================
def _objeto(propriedades: dict, obrigatorias: list[str]) -> dict:
    return {"type": "object", "properties": propriedades, "required": obrigatorias, "additionalProperties": False}


_INTEIROS = {"type": "array", "items": {"type": "integer"}}
DIMENSOES = {  # agrupar_por do resumo_vendas -> colunas do SELECT
    "ano": ["ano"], "mes": ["strftime(data, '%Y-%m') AS mes"], "dia": ["data AS dia"],
    "cliente": ["id_cliente", "cliente", "tipo_cliente"], "vendedor": ["id_vendedor", "vendedor"],
    "vendedor_carteira": ["id_vendedor_carteira", "vendedor_carteira"], "equipe": ["equipe"],
    "produto": ["id_produto", "produto", "unidade"], "grupo": ["grupo"], "categoria": ["categoria"],
    "cidade": ["cidade", "uf"], "uf": ["uf"], "segmento": ["segmento"], "area": ["area"],
}
TEMPO = ("ano", "mes", "dia")
ORDENS = ("valor_liquido", "valor_bruto", "valor_devolvido", "quantidade", "clientes", "periodo")

FERRAMENTAS = [
    {
        "name": "buscar_cliente",
        "description": ("Encontra clientes pelo nome, razão social, cidade ou código. Devolve código, nome, cidade, "
                        "segmento, vendedor da carteira, última compra e venda bruta dos últimos 12 meses. Use "
                        "antes de filtrar por um cliente citado pelo nome."),
        "input_schema": _objeto({
            "texto": {"type": "string", "description": "nome ou parte dele, razão social, cidade ou código"},
            "limite": {"type": "integer", "description": "máximo de clientes (padrão 10, até 25)"},
        }, ["texto"]),
        "strict": True,
    },
    {
        "name": "buscar_produto",
        "description": ("Encontra produtos pelo nome, linha ou código. Devolve código, nome, unidade, grupo "
                        "(mussarela, outras ou fora), categoria e venda bruta dos últimos 12 meses."),
        "input_schema": _objeto({
            "texto": {"type": "string", "description": "nome ou parte dele, linha ou código"},
            "limite": {"type": "integer", "description": "máximo de produtos (padrão 10, até 25)"},
        }, ["texto"]),
        "strict": True,
    },
    {
        "name": "buscar_vendedor",
        "description": ("Encontra vendedores do acesso pelo nome ou código. Devolve código, nome, nome no ERP, "
                        "equipe e venda bruta dos últimos 12 meses. Texto vazio lista todos."),
        "input_schema": _objeto({
            "texto": {"type": "string", "description": "nome ou parte dele, ou código; vazio lista todos"},
        }, ["texto"]),
        "strict": True,
    },
    {
        "name": "resumo_vendas",
        "description": ("Totais de faturamento (bruto, devolvido, líquido), quantidade e clientes atendidos num "
                        "período, com filtros e até 2 agrupamentos (ex.: por mês, por cliente, por produto). "
                        "Serve para quase tudo: quanto um cliente comprou, ranking de clientes ou produtos, "
                        "evolução mês a mês. Os números já seguem as regras das metas."),
        "input_schema": _objeto({
            "de": {"type": "string", "format": "date", "description": "primeiro dia (AAAA-MM-DD)"},
            "ate": {"type": "string", "format": "date", "description": "último dia, inclusive (AAAA-MM-DD)"},
            "clientes": {**_INTEIROS, "description": "códigos de cliente (de buscar_cliente)"},
            "vendedores": {**_INTEIROS, "description": "códigos do vendedor da venda"},
            "vendedores_carteira": {**_INTEIROS, "description": "códigos do vendedor da carteira do cliente"},
            "produtos": {**_INTEIROS, "description": "códigos de produto (de buscar_produto)"},
            "grupos": {"type": "array", "items": {"type": "string", "enum": ["mussarela", "outras"]}},
            "categorias": {"type": "array", "items": {"type": "string"}, "description": "categorias das outras linhas"},
            "ufs": {"type": "array", "items": {"type": "string"}, "description": "UF do cliente (ES, BA...)"},
            "agrupar_por": {"type": "array", "items": {"type": "string", "enum": list(DIMENSOES)},
                            "description": "até 2 agrupamentos; vazio = só o total"},
            "ordenar_por": {"type": "string", "enum": list(ORDENS),
                            "description": "padrão: período quando agrupa por tempo, senão valor_liquido (maior primeiro)"},
            "limite": {"type": "integer", "description": "máximo de linhas (padrão 50, até 200)"},
        }, ["de", "ate"]),
        "strict": True,
    },
    {
        "name": "metas_e_realizado",
        "description": ("Metas e realizado por vendedor, exatamente como na página Metas: meta, realizado, % "
                        "atingido, situação (batida, no ritmo, atenção, abaixo), projeção do mês e quanto falta "
                        "por dia útil. Visões: es (Metas ES: faturamento, mussarela, outras linhas e clientes), ba "
                        "(Metas BA), edir (Metas Edir), outras_es (Outras Linhas ES, com as categorias), "
                        "produtos_ba (metas de volume por produto do BA)."),
        "input_schema": _objeto({
            "visao": {"type": "string", "enum": list(VISOES)},
            "meses": {"type": "array", "items": {"type": "string"},
                      "description": "meses AAAA-MM; vários meses somam metas e realizados, como na página"},
            "vendedores": {**_INTEIROS, "description": "só estes vendedores (vazio = todos da visão)"},
        }, ["visao", "meses"]),
        "strict": True,
    },
    {
        "name": "listar_acoes",
        "description": ("Ações e objetivos da página Gestão que quem pergunta vê (dos vendedores do acesso), dos mais "
                        "novos para os mais antigos: código, tipo (ação ou objetivo), nome, região, situação, período, "
                        "indicador, alvo e nº de vendedores. Use para achar a ação citada (pelo nome)."),
        "input_schema": _objeto({
            "texto": {"type": "string", "description": "parte do nome ou o código; vazio lista todas"},
            "incluir_encerradas": {"type": "boolean", "description": "true para incluir as já encerradas"},
        }, ["texto", "incluir_encerradas"]),
        "strict": True,
    },
    {
        "name": "andamento_acao",
        "description": ("Andamento de uma ação por vendedor, exatamente como na página Gestão: a base (o mesmo "
                        "indicador no período do mesmo tamanho logo antes do início), o alvo de cada um, o resultado "
                        "(ao vivo enquanto a ação corre; congelado depois do fim), a classe (ok = alvo batido; mid = "
                        "melhorou sem chegar ao alvo; bad = não passou da base), a situação pelo ritmo e o total. Num "
                        "objetivo, o andamento da equipe da região contra o alvo da equipe."),
        "input_schema": _objeto({
            "acao": {"type": "integer", "description": "código da ação ou do objetivo (de listar_acoes)"},
        }, ["acao"]),
        "strict": True,
    },
    {
        "name": "propor_acao",
        "description": ("Só para o administrador. Confere e monta o RASCUNHO de uma ação nova para vendedores de uma "
                        "região, sem gravar: o administrador lança pelo botão que aparece abaixo da resposta. Devolve "
                        "o rascunho com os nomes (e a base de cada vendedor, quando os dados já cobrem o período), ou o "
                        "erro para corrigir. Filtros que não vierem (ou vierem vazios) não limitam nada."),
        "input_schema": _objeto({
            "nome": {"type": "string", "description": "nome curto da ação"},
            "rotulo": {"type": "string", "description": "nome da etiqueta do vendedor, até 20 letras (ex.: Mix); vazio = o padrão"},
            "descricao": {"type": "string", "description": "objetivo e combinados, em poucas linhas (pode ser vazio)"},
            "regiao": {"type": "string", "enum": ["ES", "BA"], "description": "região da ação (o Edir é da BA)"},
            "inicio": {"type": "string", "format": "date", "description": "primeiro dia (AAAA-MM-DD; padrão hoje)"},
            "semanas": {"type": "integer", "description": "prazo em semanas (1 a 26); ou use fim"},
            "fim": {"type": "string", "format": "date", "description": "último dia, inclusive (no lugar de semanas)"},
            "metrica": {"type": "string", "enum": list(TIPOS_CAMPANHA),
                        "description": "o indicador (veja as instruções); personalizada usa medida e forma"},
            "medida": {"type": "string", "enum": list(MEDIDAS_CAMPANHA), "description": "só na personalizada"},
            "forma": {"type": "string", "enum": [f for f in FORMAS_CAMPANHA if f != "crescimento"],
                      "description": "só na personalizada (padrão total)"},
            "clientes_base": {"type": "string", "enum": list(BASES_CAMPANHA),
                              "description": "quem conta (padrão todos); nunca_compraram e ja_compraram exigem produtos"},
            "dias_sem_compra": {"type": "integer", "description": "com clientes_base recuperados (padrão 90)"},
            "alvo_tipo": {"type": "string", "enum": ["fixo", "mais", "pct"],
                          "description": ("mais = a base de cada vendedor + meta (nos percentuais, em pontos); pct = "
                                          "a base + meta%; fixo = a meta para todos")},
            "meta": {"type": "number", "description": ("o número do alvo, na unidade do indicador; percentual como "
                                                       "número (80 = 80%); no preço médio não se usa")},
            "metas": {"type": "array", "description": "alvo diferente do padrão, por vendedor (mesmo alvo_tipo)",
                      "items": _objeto({"id_vendedor": {"type": "integer"}, "meta": {"type": "number"}},
                                       ["id_vendedor", "meta"])},
            "metas_produto": {"type": "array", "description": "preço médio: o preço-alvo (R$ por unidade) de cada produto",
                              "items": _objeto({"id_produto": {"type": "integer"}, "meta": {"type": "number"}},
                                               ["id_produto", "meta"])},
            "vendedores": {**_INTEIROS, "description": "códigos dos vendedores da ação (de buscar_vendedor)"},
            "equipes": {"type": "array", "items": {"type": "string", "enum": ["ES", "BA", "EDIR"]},
                        "description": "inclui todos os vendedores ativos dessas equipes (da região da ação)"},
            "produtos": {**_INTEIROS, "description": "códigos de produto (de buscar_produto)"},
            "linhas": {"type": "array", "items": {"type": "string"}, "description": "linhas de produto, como nos dados"},
            "categorias": {"type": "array", "items": {"type": "string"}, "description": "categorias das outras linhas"},
            "grupos": {"type": "array", "items": {"type": "string", "enum": ["mussarela", "outras"]}},
            "ufs": {"type": "array", "items": {"type": "string"}, "description": "UF do cliente (ES, BA...)"},
            "segmentos": {"type": "array", "items": {"type": "string"}, "description": "segmentos do cliente"},
            "areas": {"type": "array", "items": {"type": "string"}, "description": "áreas comerciais (rotas) do cliente"},
        }, ["nome", "regiao", "metrica", "alvo_tipo", "meta"]),
        # Sem strict: com este esquema (o maior de todos) a API recusa o pedido inteiro ("compiled grammar is too
        # large"). A conferência é do servidor (bi/gestao.py validar), que devolve o erro para a IA corrigir.
        "strict": False,
    },
    {
        "name": "consultar_sql",
        "description": ("Executa UMA consulta SELECT (DuckDB) nas tabelas descritas nas instruções, para o que as "
                        "outras ferramentas não resolvem. Somente leitura; devolve até 200 linhas."),
        "input_schema": _objeto({
            "sql": {"type": "string", "description": "uma única instrução SELECT (ou WITH ... SELECT)"},
            "objetivo": {"type": "string", "description": "em poucas palavras, o que a consulta responde"},
        }, ["sql", "objetivo"]),
        "strict": True,
    },
]


def _valor(v):
    if isinstance(v, float):
        if v != v:
            return None
        return round(v, 2) if abs(v) >= 100 else round(v, 4)
    if isinstance(v, decimal.Decimal):
        return _valor(float(v))
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def _data_iso(texto, campo: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(texto)[:10])
    except ValueError:
        raise ValueError(f"{campo} deve ser uma data AAAA-MM-DD (veio {texto!r})") from None


def _palavras(texto: str) -> list[str]:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return [p for p in "".join(c if c.isalnum() else " " for c in t).split() if p]


class Ferramentas:
    """Executa as ferramentas de uma pergunta no recorte do acesso. Cada chamada devolve (resultado, passo)."""

    def __init__(self, recorte: Recorte, calc: Calculadora, cfg: ConfigIA, equipes: set[str] | None, gestao=None):
        """gestao: bi/gestao.py ContextoGestao de quem pergunta (None = o acesso não inclui a página Gestão)."""
        self.cur = recorte.cursor()
        self.ids = recorte.ids
        self.calc = calc
        self.cfg = cfg
        self.equipes = equipes
        self.gestao = gestao
        self.rascunhos: list[dict] = []  # ações propostas nesta pergunta (a página mostra o botão de lançar)
        self.data_ref = calc.cache.data_ref() or dt.date.today()

    def executar(self, nome: str, args: dict) -> tuple[dict, dict]:
        t0 = time.time()
        passo = {"ferramenta": nome, "args": args, "sql": None, "colunas": [], "amostra": [], "linhas": 0, "erro": None}
        try:
            metodo = getattr(self, "f_" + nome, None)
            if metodo is None:
                raise ValueError(f"ferramenta desconhecida: {nome}")
            extras = set(args) - set(inspect.signature(metodo).parameters)
            if extras:
                raise ValueError(f"argumento desconhecido: {', '.join(sorted(extras))}")
            resultado = metodo(passo, **args)
        except (ValueError, RuntimeError, duckdb.Error, NaoEncontrada) as e:
            passo["erro"] = str(e).split("\n")[0][:500] if isinstance(e, duckdb.Error) else str(e)
            resultado = {"erro": passo["erro"]}
        except BancoForaDoAr as e:  # as ações ficam no PostgreSQL
            passo["erro"] = f"as ações não puderam ser lidas: {e.aviso}"
            resultado = {"erro": passo["erro"]}
        except Exception as e:  # argumento que a ferramenta não tem, ou defeito: a IA fica sabendo e segue
            log.exception("falha na ferramenta %s %s", nome, args)
            passo["erro"] = f"falha ao executar a ferramenta ({type(e).__name__}: {e})"
            resultado = {"erro": passo["erro"]}
        passo["ms"] = int((time.time() - t0) * 1000)
        return resultado, passo

    # --- consultas ---------------------------------------------------------------------
    def _consultar(self, passo: dict, sql: str, params: list, max_linhas: int | None = None) -> dict:
        """Roda no recorte com tempo limite; guarda no passo o SQL, as colunas e uma amostra para a tela."""
        max_linhas = min(max_linhas or self.cfg.max_linhas, self.cfg.max_linhas)
        relogio = threading.Timer(self.cfg.tempo_sql, self.cur.interrupt)
        relogio.start()
        try:
            self.cur.execute(sql, params)
            colunas = [d[0] for d in self.cur.description]
            linhas = self.cur.fetchmany(max_linhas + 1)
        except duckdb.InterruptException:
            raise ValueError(f"a consulta passou de {self.cfg.tempo_sql:.0f} s e foi interrompida; simplifique ou "
                             "filtre mais") from None
        finally:
            relogio.cancel()
        truncado = len(linhas) > max_linhas
        linhas = [[_valor(v) for v in r] for r in linhas[:max_linhas]]
        # O texto da IA tem limite: corta linhas até caber.
        while linhas and len(json.dumps(linhas, ensure_ascii=False)) > MAX_RESULTADO:
            linhas = linhas[: max(1, len(linhas) * 3 // 4)] if len(linhas) > 1 else []
            truncado = True
        passo.update(sql=_sql_legivel(sql, params), colunas=colunas, amostra=linhas[:10], linhas=len(linhas))
        saida = {"colunas": colunas, "linhas": linhas}
        if truncado:
            saida["aviso"] = f"resultado cortado em {len(linhas)} linhas; agrupe ou filtre mais para ver tudo"
        return saida

    def f_consultar_sql(self, passo: dict, sql: str, objetivo: str = "") -> dict:
        sql = str(sql or "").strip().rstrip(";")
        if not sql:
            raise ValueError("SQL vazio")
        if len(sql) > MAX_SQL:
            raise ValueError("SQL longo demais")
        instrucoes = self.cur.extract_statements(sql)
        if len(instrucoes) != 1:
            raise ValueError("mande uma única instrução SELECT por vez")
        if instrucoes[0].type != duckdb.StatementType.SELECT:
            raise ValueError("só consultas SELECT são permitidas")
        passo["objetivo"] = str(objetivo or "")[:200]
        return self._consultar(passo, sql, [])

    def f_buscar_cliente(self, passo: dict, texto: str, limite: int = 10) -> dict:
        limite = max(1, min(int(limite or 10), 25))
        palavras = _palavras(texto)
        if not palavras:
            raise ValueError("diga o nome, a cidade ou o código do cliente")
        codigo = int(palavras[0]) if len(palavras) == 1 and palavras[0].isdigit() else None
        alvo = ("strip_accents(lower(concat_ws(' ', cliente, razao_social, cidade, segmento, "
                "CAST(id_cliente AS VARCHAR))))")
        contem = " AND ".join([f"{alvo} LIKE ?"] * len(palavras))
        nome = "strip_accents(lower(cliente))"
        sql = (f"SELECT id_cliente, cliente, razao_social, cidade, uf, segmento, vendedor_carteira, inativo, "
               f"ultima_compra, venda_bruta_12m FROM clientes "
               f"WHERE ({contem}) OR id_cliente = ? "
               f"ORDER BY id_cliente = ? DESC, jaro_winkler_similarity({nome}, ?) DESC, venda_bruta_12m DESC "
               f"LIMIT ?")
        termo = " ".join(palavras)
        params = [f"%{p}%" for p in palavras] + [codigo or -1, codigo or -1, termo, limite]
        r = self._consultar(passo, sql, params, limite)
        if not r["linhas"]:  # nome digitado diferente do cadastro: os mais parecidos
            sql = (f"SELECT id_cliente, cliente, razao_social, cidade, uf, segmento, vendedor_carteira, inativo, "
                   f"ultima_compra, venda_bruta_12m, round(jaro_winkler_similarity({nome}, ?), 2) AS semelhanca "
                   f"FROM clientes WHERE jaro_winkler_similarity({nome}, ?) >= 0.75 "
                   f"ORDER BY semelhanca DESC, venda_bruta_12m DESC LIMIT ?")
            r = self._consultar(passo, sql, [termo, termo, limite], limite)
            r["aviso"] = ("nenhum nome contém o texto; estes são os mais parecidos" if r["linhas"] else
                          "nenhum cliente encontrado no acesso de quem pergunta")
        return r

    def f_buscar_produto(self, passo: dict, texto: str, limite: int = 10) -> dict:
        limite = max(1, min(int(limite or 10), 25))
        palavras = _palavras(texto)
        if not palavras:
            raise ValueError("diga o nome, a linha ou o código do produto")
        alvo = "strip_accents(lower(concat_ws(' ', p.produto, p.linha, CAST(p.id_produto AS VARCHAR))))"
        contem = " AND ".join([f"{alvo} LIKE ?"] * len(palavras))
        sql = (f"WITH v AS (SELECT id_produto, SUM(valor) AS venda_bruta_12m FROM _vendas WHERE data > ? GROUP BY 1) "
               f"SELECT p.id_produto, p.produto, p.unidade, p.linha, p.grupo, p.categoria, p.inativo, "
               f"COALESCE(v.venda_bruta_12m, 0) AS venda_bruta_12m FROM produtos p LEFT JOIN v USING (id_produto) "
               f"WHERE {contem} ORDER BY venda_bruta_12m DESC, p.inativo, p.produto LIMIT ?")
        params = [self.data_ref - dt.timedelta(days=365), *[f"%{p}%" for p in palavras], limite]
        r = self._consultar(passo, sql, params, limite)
        if not r["linhas"]:
            r["aviso"] = "nenhum produto encontrado com esse texto"
        return r

    def f_buscar_vendedor(self, passo: dict, texto: str = "") -> dict:
        palavras = _palavras(texto)
        alvo = "strip_accents(lower(concat_ws(' ', vd.vendedor, vd.nome_erp, CAST(vd.id_vendedor AS VARCHAR))))"
        contem = " AND ".join([f"{alvo} LIKE ?"] * len(palavras)) or "TRUE"
        sql = (f"WITH v AS (SELECT id_vendedor, SUM(valor) AS venda_bruta_12m FROM _vendas WHERE data > ? GROUP BY 1) "
               f"SELECT vd.id_vendedor, vd.vendedor, vd.nome_erp, vd.equipe, vd.supervisor, vd.inativo, "
               f"COALESCE(v.venda_bruta_12m, 0) AS venda_bruta_12m FROM vendedores vd LEFT JOIN v USING (id_vendedor) "
               f"WHERE {contem} ORDER BY venda_bruta_12m DESC LIMIT 60")
        params = [self.data_ref - dt.timedelta(days=365), *[f"%{p}%" for p in palavras]]
        r = self._consultar(passo, sql, params, 60)
        if not r["linhas"]:
            r["aviso"] = "nenhum vendedor com esse texto no acesso de quem pergunta"
        return r

    def f_resumo_vendas(self, passo: dict, de: str, ate: str, clientes=None, vendedores=None, vendedores_carteira=None,
                        produtos=None, grupos=None, categorias=None, ufs=None, agrupar_por=None, ordenar_por=None,
                        limite: int = 50) -> dict:
        d0, d1 = _data_iso(de, "de"), _data_iso(ate, "ate")
        if d1 < d0:
            raise ValueError("'ate' é antes de 'de'")
        dims = list(dict.fromkeys(agrupar_por or []))
        if len(dims) > 2:
            raise ValueError("agrupe por no máximo 2 dimensões")
        for d in dims:
            if d not in DIMENSOES:
                raise ValueError(f"agrupamento desconhecido: {d}")
        onde, params = ["data BETWEEN ? AND ?"], [d0, d1]
        for coluna, valores, conv in (("id_cliente", clientes, int), ("id_vendedor", vendedores, int),
                                      ("id_vendedor_carteira", vendedores_carteira, int), ("id_produto", produtos, int),
                                      ("grupo", grupos, str), ("categoria", categorias, str), ("uf", ufs, str)):
            if valores:
                valores = [conv(v) for v in valores][:500]
                onde.append(f"{coluna} IN ({_marcas(valores)})")
                params += valores
        if clientes:
            onde.append("tipo_cliente = 'CLIENTE'")  # códigos de buscar_cliente são do cadastro de clientes
        medidas = ("round(COALESCE(SUM(valor_bruto), 0), 2) AS valor_bruto, "
                   "round(COALESCE(SUM(valor_devolvido), 0), 2) AS valor_devolvido, "
                   "round(COALESCE(SUM(valor_liquido), 0), 2) AS valor_liquido, "
                   "round(COALESCE(SUM(quantidade), 0), 3) AS quantidade, "
                   "COUNT(DISTINCT CASE WHEN tipo = 'venda' THEN tipo_cliente || id_cliente END) AS clientes")
        where = " AND ".join(onde)
        total = self._consultar({}, f"SELECT {medidas} FROM faturamento WHERE {where}", params)
        resultado = {"periodo": f"{d0.isoformat()} a {d1.isoformat()}",
                     "total": dict(zip(total["colunas"], total["linhas"][0])) if total["linhas"] else {}}
        if not dims:
            passo.update(sql=_sql_legivel(f"SELECT {medidas} FROM faturamento WHERE {where}", params),
                         colunas=total["colunas"], amostra=total["linhas"], linhas=len(total["linhas"]))
            return resultado
        colunas = [c for d in dims for c in DIMENSOES[d]]
        ordem = ordenar_por or ("periodo" if any(d in TEMPO for d in dims) else "valor_liquido")
        if ordem not in ORDENS:
            raise ValueError(f"ordenação desconhecida: {ordem}")
        if ordem == "periodo":
            por_tempo = [c.split(" AS ")[-1] for d in dims if d in TEMPO for c in DIMENSOES[d]]
            ordem_sql = ", ".join(por_tempo + ["valor_liquido DESC"])
        else:
            ordem_sql = f"{ordem} DESC"
        limite = max(1, min(int(limite or 50), 200))
        sql = (f"SELECT {', '.join(colunas)}, {medidas} FROM faturamento WHERE {where} GROUP BY ALL "
               f"ORDER BY {ordem_sql} LIMIT {limite + 1}")
        r = self._consultar(passo, sql, params, limite)
        resultado.update(r)
        return resultado

    def f_metas_e_realizado(self, passo: dict, visao: str, meses: list, vendedores=None) -> dict:
        if visao not in VISOES:
            raise ValueError(f"visão desconhecida: {visao}")
        if self.equipes is not None and not set(VISOES[visao]["grupos"]) & self.equipes:
            raise ValueError("essa visão não faz parte do acesso de quem pergunta")
        periodos = []
        for m in meses or []:
            try:
                a, mm = str(m).split("-")[:2]
                periodos.append((int(a), int(mm)))
            except ValueError:
                raise ValueError(f"mês inválido: {m!r} (use AAAA-MM)") from None
        if not periodos:
            raise ValueError("diga ao menos um mês (AAAA-MM)")
        permitidos = set(self.ids) if self.ids is not None else None
        d = self.calc.visao(visao, periodos[:24], [int(v) for v in vendedores or []] or None, permitidos)
        cal = d["calendario"]
        resultado = {
            "visao": d["visao"]["titulo"], "periodo": d["periodo"]["rotulo"], "dados_ate": d["data_ref"],
            "calendario": {k: _valor(cal.get(k)) for k in ("situacao", "dias_uteis", "dias_decorridos",
                                                            "dias_restantes", "ritmo")},
        }
        enxuto = lambda ind: {k: _valor(ind.get(k)) for k in ("meta", "realizado", "pct", "status", "projecao",  # noqa: E731
                                                               "falta", "falta_por_dia") if ind.get(k) is not None}
        if "linhas" in d:
            chaves = ("faturamento", "mussarela", "outras", "clientes")
            resultado["total"] = {k: enxuto(d["indicadores"][k]) for k in chaves}
            resultado["vendedores"] = [{
                "id": ln["id"], "nome": ln["nome"], **{k: enxuto(ln[k]) for k in chaves},
                "venda_media": {k: _valor(v) for k, v in ln["venda_media"].items()},
                **({"categorias": {k: _valor(v) for k, v in ln["categorias"].items()}} if visao == "outras_es" else {}),
            } for ln in d["linhas"]]
            linhas = resultado["vendedores"]
        else:
            resultado["total"] = {k: _valor(v) for k, v in d["indicadores"].items()}
            nomes = {str(v["id"]): v["nome"] for v in d["colunas"]}
            resultado["produtos"] = [{
                "id": p["id"], "produto": p["nome"], "unidade": p["unidade"], "total": enxuto(p["total"]),
                "por_vendedor": {nomes.get(k, k): enxuto(v) for k, v in p["por_vendedor"].items()},
            } for p in d["produtos"][:40]]
            linhas = resultado["produtos"]
        passo.update(sql=None, colunas=["visão", "período"], amostra=[[resultado["visao"], resultado["periodo"]]],
                     linhas=len(linhas))
        return resultado

    # --- ações e objetivos (página Gestão) ---------------------------------------------
    def _acoes(self):
        if self.gestao is None:
            raise ValueError("o acesso de quem pergunta não inclui a página Gestão, onde ficam as ações")
        return self.gestao

    def f_listar_acoes(self, passo: dict, texto: str = "", incluir_encerradas: bool = False) -> dict:
        lista = self._acoes().listar(texto, bool(incluir_encerradas))
        passo.update(colunas=["código", "nome", "tipo", "região", "situação", "início", "fim", "indicador"],
                     amostra=[[c["id"], c["nome"], c["tipo"], c["regiao"], c["situacao"], c["inicio"], c["fim"],
                               c["indicador"]] for c in lista[:10]],
                     linhas=len(lista))
        if not lista:
            return {"acoes": [], "aviso": "nenhuma ação ou objetivo encontrado" + (" com esse texto" if texto else "")}
        return {"acoes": lista}

    def f_andamento_acao(self, passo: dict, acao: int) -> dict:
        r = self._acoes().andamento(int(acao))
        item = r["item"]
        if "vendedores" in r:
            passo.update(colunas=["vendedor", "base", "alvo", "resultado", "classe"],
                         amostra=[[v["nome"], v.get("base"), v.get("alvo"), v.get("resultado"), v.get("classe")]
                                  for v in r["vendedores"][:10]], linhas=len(r["vendedores"]))
        else:
            a = r["andamento_da_equipe"]
            passo.update(colunas=["realizado", "alvo", "%", "situação"],
                         amostra=[[a.get("realizado"), a.get("meta"), a.get("pct"), a.get("status")]], linhas=1)
        passo["resumo"] = f"#{item['id']} {item['nome']}"
        return r

    def f_propor_acao(self, passo: dict, nome: str, regiao: str, metrica: str, alvo_tipo: str = "fixo",
                      meta: float = 0, rotulo: str = "", descricao: str = "", inicio=None, semanas=None, fim=None,
                      medida=None, forma=None, clientes_base=None, dias_sem_compra=None, metas=None,
                      metas_produto=None, vendedores=None, equipes=None, produtos=None, linhas=None, categorias=None,
                      grupos=None, ufs=None, segmentos=None, areas=None) -> dict:
        individuais = {}
        for m in metas or []:
            try:
                individuais[int(m["id_vendedor"])] = m["meta"]
            except (KeyError, TypeError, ValueError):
                raise ValueError("metas: use uma lista de {id_vendedor, meta}") from None
        participantes = [{"id": int(v), "meta": individuais.get(int(v))} for v in vendedores or []]
        ja = {p["id"] for p in participantes}
        participantes += [{"id": v, "meta": m} for v, m in individuais.items() if v not in ja]
        try:
            precos = [{"id": int(m["id_produto"]), "meta": m["meta"]} for m in metas_produto or []]
        except (KeyError, TypeError, ValueError):
            raise ValueError("metas_produto: use uma lista de {id_produto, meta}") from None
        parametros = {k: v for k, v in {"medida": medida, "forma": forma, "clientes": clientes_base,
                                        "dias_sem_compra": dias_sem_compra}.items() if v not in (None, "")}
        dados = {"nome": nome, "rotulo": rotulo, "descricao": descricao, "regiao": regiao, "inicio": inicio,
                 "semanas": semanas, "fim": fim, "metrica": metrica, "parametros": parametros, "alvo_tipo": alvo_tipo,
                 "meta_padrao": meta, "vendedores": participantes, "metas_produto": precos,
                 "filtros": {"produtos": produtos, "linhas": linhas, "categorias": categorias, "grupos": grupos,
                             "ufs": ufs, "segmentos": segmentos, "areas": areas}}
        r = self._acoes().propor(dados, equipes or [])
        self.rascunhos.append(r)
        n = len(r["vendedores"])
        ind = r["indicador"]
        passo.update(colunas=["rascunho", "região", "período", "indicador", "alvo", "vendedores"],
                     amostra=[[r["nome"], r["regiao"], f"{r['inicio']} a {r['fim']}", ind["nome"], r["texto_alvo"], n]],
                     linhas=1, resumo=(f"rascunho {r['id']} (ainda não lançado): {r['nome']}, {r['regiao']}, "
                                       f"{ind['nome']}, {r['inicio']} a {r['fim']}, alvo {r['texto_alvo']}, "
                                       f"{n} vendedores"))
        nomes = r["nomes"]
        filtros = dict(r["filtros"])
        if filtros.get("produtos"):
            filtros["produtos"] = [f"{p} {nomes['produtos'].get(str(p), '')}".strip() for p in filtros["produtos"]]
        return {
            "situacao": ("RASCUNHO, AINDA NÃO LANÇADO. O administrador confere e lança no botão 'Lançar ação' que "
                         "aparece abaixo da sua resposta (ou ajusta em 'Revisar no painel')."),
            "rascunho": {
                "nome": r["nome"], "rotulo": r["rotulo"], "regiao": r["regiao"],
                "periodo": f"{r['inicio']} a {r['fim']}",
                "periodo_da_base": f"{r['base_inicio']} a {r['base_fim']} (o mesmo tamanho, logo antes do início)",
                "indicador": ind["nome"], "o_que_mede": ind["descricao"], "unidade": r["unidade"],
                "alvo": r["texto_alvo"], **({"meta_em_percentual": True} if ind["meta_em_pct"] else {}),
                "descricao": r["descricao"], "filtros": filtros,
                **({"precos_alvo": [{"produto": f"{p['id']} {nomes['produtos'].get(str(p['id']), '')}".strip(),
                                     "meta": p["meta"]} for p in r["metas_produto"]]} if r["metas_produto"] else {}),
                "vendedores": [{"id": v["id"], "nome": nomes["vendedores"].get(str(v["id"])),
                                "meta": r["meta_padrao"] if v["meta"] is None else v["meta"],
                                **(r["bases"].get(str(v["id"])) or {"base": "ainda sem dados do período da base"})}
                               for v in r["vendedores"]],
            },
        }


def _sql_legivel(sql: str, params: list) -> str:
    """SQL com os parâmetros no lugar (só para mostrar na tela e no registro; a consulta usa parâmetros)."""
    partes = sql.split("?")
    if len(partes) - 1 != len(params):
        return sql
    texto = partes[0]
    for p, resto in zip(params, partes[1:]):
        if isinstance(p, str):
            texto += "'" + p.replace("'", "''") + "'"
        elif isinstance(p, dt.date):
            texto += f"DATE '{p.isoformat()}'"
        else:
            texto += str(p)
        texto += resto
    return " ".join(texto.split())


# ============================================================================================
# Instruções
# ============================================================================================
ESQUEMA = """\
faturamento — a venda oficial (a mesma das metas): uma linha por dia, vendedor, cliente e produto; vendas
  (tipo = 'venda') e devoluções que descontam (tipo = 'devolucao'). Sem os produtos do grupo 'fora'.
  data, ano, mes, tipo, id_vendedor, vendedor, equipe, id_cliente, cliente, tipo_cliente, cidade, uf, segmento,
  area, id_vendedor_carteira, vendedor_carteira, id_produto, produto, grupo, categoria, linha, unidade,
  valor_bruto (venda), valor_devolvido (devolução que desconta), valor_liquido (= bruto − devolvido), quantidade
  (na unidade do produto; devolução entra negativa)
devolucoes — todas as devoluções (inclusive as que não descontam): data (de ENTRADA), ano, mes, id_vendedor,
  vendedor, id_cliente, cliente, tipo_cliente, vendedor_carteira, id_produto, produto, grupo, id_motivo, motivo,
  cancelada, desconta, valor, quantidade
pedidos — notas de venda por dia, vendedor e cliente: data, ano, mes, id_vendedor, vendedor, id_cliente, cliente,
  tipo_cliente, pedidos (quantidade de notas)
clientes — cadastro (só tipo CLIENTE): id_cliente, cliente, razao_social, cidade, uf, id_area, area (rota
  comercial), segmento, inativo, data_cadastro, id_vendedor_carteira, vendedor_carteira, primeira_compra,
  ultima_compra, venda_bruta_12m, rede (do cadastro; as redes SEMANAL, QUINZENAL e MENSAL são a frequência de
  compra), frequencia_semanas (1, 2 ou 4, pela rede; vazio = a rede não é uma frequência)
produtos — id_produto, produto, linha, unidade, inativo, grupo ('mussarela', 'outras' ou 'fora'), categoria
vendedores — id_vendedor, vendedor, nome_erp, equipe ('ES', 'BA', 'Edir', 'Outros'), supervisor, inativo
motivos — id_motivo, motivo, desconta (se a devolução por esse motivo desconta das vendas)
metas_vendedor — metas mensais (planilha METAS.xlsx): ano, mes, id_vendedor, vendedor, meta_faturamento,
  meta_mussarela, meta_outras, meta_clientes
metas_produto — metas de volume (planilha METAS PRODUTOS.xlsx): ano, mes, id_vendedor, vendedor, id_produto,
  produto, meta_volume

Exemplos:
-- venda líquida de um cliente por mês em 2026
SELECT ano, mes, SUM(valor_liquido) AS liquido FROM faturamento
WHERE id_cliente = 4521 AND tipo_cliente = 'CLIENTE' AND ano = 2026 GROUP BY ALL ORDER BY ano, mes
-- clientes de um vendedor que compraram em agosto e não em setembro de 2026
SELECT id_cliente, cliente, SUM(valor_liquido) AS agosto FROM faturamento
WHERE id_vendedor = 126 AND tipo = 'venda' AND ano = 2026 AND mes = 8
  AND id_cliente NOT IN (SELECT id_cliente FROM faturamento WHERE id_vendedor = 126 AND tipo = 'venda'
                         AND ano = 2026 AND mes = 9)
GROUP BY ALL ORDER BY agosto DESC
-- devoluções de setembro por motivo
SELECT motivo, desconta, SUM(valor) AS valor FROM devolucoes
WHERE data BETWEEN DATE '2026-09-01' AND DATE '2026-09-30' GROUP BY ALL ORDER BY valor DESC"""

INSTRUCOES = f"""\
Você é o Assistente do Painel Mais Vida, o painel de indicadores do Laticínio Mais Vida (vendas no Espírito Santo \
e na Bahia). Responde a vendedores, supervisores e à diretoria sobre vendas, devoluções, clientes, produtos e \
metas, consultando os dados com as ferramentas.

# Regras
- Todo número da resposta sai de uma ferramenta. Nunca estime nem complete de cabeça; se os dados não respondem, \
diga isso e o que daria para responder.
- Cliente, produto ou vendedor citado pelo nome: encontre o código com buscar_cliente, buscar_produto ou \
buscar_vendedor antes de filtrar. Se houver mais de um candidato plausível, use o mais provável e diga qual \
(nome e código); se a diferença mudar a resposta, pergunte.
- Prefira resumo_vendas para totais, rankings e evolução, e metas_e_realizado para metas, % atingido e ritmo \
(são os números da página Metas). Use consultar_sql só quando essas não resolverem.
- Você só enxerga os vendedores do acesso de quem pergunta. Se um cliente ou vendedor não aparece, pode estar fora \
desse acesso: diga isso, sem supor valores.
- A data de hoje e a data dos dados estão no fim destas instruções. Mês sem ano é o mais recente até a data dos \
dados. O mês em andamento vai até a data dos dados: deixe isso claro.

# Definições (as mesmas das páginas do painel)
- Faturamento ou venda líquida = vendas válidas (não canceladas) − devoluções que descontam. É o número oficial, \
o das metas. Venda bruta = sem descontar devoluções. Sem outra indicação, responda com o líquido e diga isso.
- Devolução conta pela data de ENTRADA e só desconta se o motivo estiver marcado nas Configurações das metas \
(coluna desconta); devolução cancelada não desconta. A tabela devolucoes tem todas, com o motivo.
- Produtos do grupo 'fora' (marcados como "não conta") ficam fora do faturamento. Grupos: 'mussarela' e 'outras' \
(outras linhas); as categorias detalham as outras linhas.
- Vendedor, nas vendas e devoluções, é o vendedor da venda (como na página Metas). vendedor_carteira é o vendedor \
atual do cliente no cadastro do ERP (como na página Projeções): se a pergunta for sobre a carteira, use ele e diga.
- tipo_cliente: CLIENTE, FUNCIONARIO, FORNECEDOR ou PRODUTOR. Só CLIENTE tem cadastro (nome, cidade, segmento); \
o código dos outros é de outro cadastro e pode coincidir com o de um cliente, por isso filtre tipo_cliente = \
'CLIENTE' ao usar um código de cliente.
- Clientes atendidos (positivação) = clientes distintos com venda no período. Venda média = faturamento ÷ clientes.
- Quantidade só soma com sentido dentro do mesmo produto (unidades diferentes).

# Ações e objetivos (página Gestão)
- Uma ação mede um indicador por vendedor, numa região (ES ou BA; o Edir é da BA), num prazo (semanas, ou até uma \
data). A base de cada vendedor é o mesmo indicador no período do mesmo tamanho logo antes do início, e o alvo de \
cada um sai dela: alvo_tipo mais = base + meta (nos percentuais, em pontos); pct = base + meta%; fixo = a meta para \
todos. Enquanto a ação corre entram as parciais de cada semana; no fim, o resultado de cada um contra a base e o \
alvo. Um objetivo é o indicador da equipe da região num período, contra um alvo da equipe. Tipos (metrica):
  - positivacao: clientes distintos com venda. Recuperação de clientes = clientes_base recuperados, com \
dias_sem_compra (padrão 90).
  - mix_medio: produtos da campanha levados por cliente positivado (média). "Clientes que nunca compraram X" = \
clientes_base nunca_compraram, e "que já compram X" = ja_compraram, sempre com os produtos.
  - efetividade: a média da efetividade de cada dia (pedidos na rota do dia ÷ visitas esperadas no dia, pelos dias \
de atendimento das áreas), pela carteira do vendedor. Só contam os pedidos de clientes das áreas atendidas naquele \
dia: pedido de cliente de área de outro dia fica fora. As visitas esperadas seguem a frequência de compra (a rede \
SEMANAL, QUINZENAL ou MENSAL do cliente): o semanal sempre, o quinzenal sem compra nos 7 dias antes, o mensal sem \
compra nos 21 dias antes; o pedido de quem não estava previsto conta, mas ele não entra nas visitas (o dia pode \
passar de 100%); sem frequência conta como semanal. \
Dias sem visita esperada (fim de semana) ficam fora da média. \
O numerador e o denominador que vêm junto (pedidos na rota e visitas desses dias) não dão a média se divididos: use \
o valor que vem pronto. A meta \
é em % (80 = 80%); só aceita filtros de cliente (UF, segmento, área).
  - frequencia: semanas com compra por cliente positivado (média).
  - preco_medio: preço-alvo de cada produto em metas_produto (R$ por unidade); a meta é estar no preço-alvo.
  - personalizada: para o resto, monte com medida (faturamento, volume, clientes ou produtos) e forma: total; \
por_cliente (faturamento ou volume ÷ clientes positivados); pct_carteira (clientes da carteira que compraram; meta \
em %). Numa ação não existe a forma crescimento: "crescer X%" é alvo_tipo pct. Volume exige produtos de uma \
unidade só.
- Filtros de produto: produtos, linhas, categorias, grupos. Filtros de cliente: ufs, segmentos, areas (rotas). \
Segmentos e áreas vão como estão nos dados: confira com consultar_sql (SELECT DISTINCT segmento FROM clientes) \
se não tiver certeza.
- Como traduzir o pedido, por exemplo:
  - "+1 no mix em 3 semanas para Rubens e Isaque" = mix_medio, alvo_tipo mais, meta 1, semanas 3;
  - "subir a venda média em 10%" = personalizada, faturamento, por_cliente, alvo_tipo pct, meta 10;
  - "positivar mais 5 padarias" = positivacao, segmentos ["PADARIA"], alvo_tipo mais, meta 5;
  - "recuperar clientes sem compra há 60 dias" = positivacao, clientes_base recuperados, dias_sem_compra 60;
  - "colocar o requeijão em quem nunca comprou" = mix_medio ou positivacao, produtos [requeijão], clientes_base \
nunca_compraram;
  - "efetividade de 80%" = efetividade, alvo_tipo fixo, meta 80; "+5 pontos de efetividade" = alvo_tipo mais, meta 5;
  - "mussarela a R$ 32/kg e manteiga a R$ 9,50" = preco_medio, metas_produto;
  - "vender 10% a mais" = personalizada, faturamento, total, alvo_tipo pct, meta 10;
  - "atender 60% da carteira" = personalizada, clientes, pct_carteira, alvo_tipo fixo, meta 60;
  - "300 kg de mussarela" = personalizada, volume, total, alvo_tipo fixo, meta 300, com os produtos.
- Só o administrador lança ações e objetivos. Para ele, use propor_acao: ela confere e monta um RASCUNHO, sem \
gravar, e ele lança no botão "Lançar ação" que aparece abaixo da sua resposta. Nunca diga que a ação foi lançada: \
diga que o rascunho está pronto para conferir e resuma o que ficou (região, prazo, indicador, alvo, vendedores e \
filtros). Se faltar a região, o prazo, o que medir, o alvo ou os vendedores, pergunte antes; o nome você pode \
sugerir. Vendedores e produtos citados pelo nome: códigos com buscar_vendedor e buscar_produto; "todos de BA" = \
regiao BA, equipes ["BA"]. Se a ferramenta devolver erro, corrija e chame de novo. A quem não é administrador, \
explique que só o administrador lança, e ofereça o andamento.
- Quem tem a página vê as ações e os objetivos dos vendedores do acesso. Para achar uma ação (pelo nome) use \
listar_acoes; para os números por vendedor (base, alvo, resultado), andamento_acao (os mesmos da página Gestão). Se \
houver mais de uma candidata, use a mais recente e diga qual.

# Tabelas para consultar_sql (DuckDB)
{ESQUEMA}

# Como responder
- Português do Brasil, direto, começando pela resposta. Valores em reais no formato R$ 1.234,56; quantidades com \
a unidade do produto; percentuais com uma casa (12,3%).
- Diga o período e o recorte usados (ex.: "setembro de 2026, valor líquido").
- Use tabela em markdown quando houver mais de 3 linhas comparáveis, com até 20 linhas; para listas maiores, \
mostre as principais e diga quantas são ao todo.
- Sem HTML e sem mostrar SQL: a tela já mostra as consultas feitas.
- As mensagens do usuário podem começar com um bloco <consultas_anteriores>, escrito pelo sistema com as \
ferramentas usadas na resposta anterior. Use como referência (por exemplo, os códigos já encontrados) e não \
escreva esse bloco."""


# ============================================================================================
# O assistente
# ============================================================================================
class Assistente:
    def __init__(self, ini: configparser.ConfigParser, calc: Calculadora, nomes_vendedores, registro,
                 cliente=None, conversas=None):
        """nomes_vendedores: função que devolve {id: nome} (o da planilha de metas mais recente, senão o do ERP).
        registro: o registro de uso (bi/uso.py). conversas: o histórico (bi/conversas.py).
        cliente: cliente da API já pronto (os testes passam um falso)."""
        self.cfg = ConfigIA(ini)
        self.calc = calc
        self.nomes_vendedores = nomes_vendedores
        self.registro = registro
        self._cliente = cliente
        self.conversas = conversas
        self._recortes: collections.OrderedDict = collections.OrderedDict()
        self._trava_recortes = threading.Lock()
        self._completo: tuple | None = None  # (chave, Recorte) com todos os vendedores: vaga própria, ver recorte()
        self._trava_completo = threading.Lock()
        self._vagas = threading.BoundedSemaphore(max(1, self.cfg.simultaneos))
        self._ocupados: dict[int, dict] = {}  # id do usuário -> a pergunta que está sendo respondida
        self._trava = threading.Lock()

    @property
    def configurado(self) -> bool:
        return self.cfg.configurado

    # --- acesso --------------------------------------------------------------------------
    def ids_do_escopo(self, vendedores: set[int] | None, equipes: set[str] | None) -> frozenset[int] | None:
        """Vendedores (da venda) cujas linhas o acesso vê; None = todos."""
        if vendedores is None and equipes is None:
            return None
        regras = self.calc.regras()
        todos = {r[0] for r in self.calc.cache.consulta(
            "SELECT id FROM vendedores UNION SELECT DISTINCT id_vendedor FROM vendas_itens")}
        todos |= {m["id_vendedor"] for m in self.calc.metas.dados()} | set(vendedores or ())
        return frozenset(v for v in todos if (equipes is None or regras.grupo_vendedor(v) in equipes)
                         and (vendedores is None or v in vendedores))

    def descrever_escopo(self, ids: frozenset[int] | None, vendedores, equipes) -> str:
        if ids is None:
            return "todos os vendedores"
        if vendedores is None and equipes:
            nomes = sorted(NOME_EQUIPE.get(e, e) for e in equipes)
            return ("vendedores da equipe " if len(nomes) == 1 else "vendedores das equipes ") + " e ".join(nomes)
        nomes = self.nomes_vendedores()
        lista = sorted(nomes.get(v, f"Vendedor {v}") for v in ids)
        mais = f" e mais {len(lista) - 6}" if len(lista) > 6 else ""
        return f"{len(lista)} vendedor{'es' if len(lista) != 1 else ''}: {', '.join(lista[:6])}{mais}"

    def recorte(self, ids: frozenset[int] | None) -> Recorte:
        """O recorte do acesso, guardado enquanto os dados e as regras não mudam. O de todos os vendedores (ids
        None) tem vaga própria, fora do limite [ia] recortes: a página Gestão usa ele o tempo todo (filtrando os
        vendedores no SQL), e assim não derruba o recorte de quem está perguntando ao Assistente."""
        cache = self.calc.cache
        cfg = json.dumps(self.calc.configuracao.atual(), sort_keys=True)
        chave = (cache.info.get("extraido_em"), hashlib.sha1(cfg.encode()).hexdigest(),
                 self.calc.metas.versao, self.calc.metas_produtos.versao, ids)
        if ids is None:
            with self._trava_completo:  # dois pedidos juntos montam uma vez só
                if self._completo is None or self._completo[0] != chave:
                    r = Recorte(self.calc, self.nomes_vendedores(), None)
                    log.info("recorte com todos os vendedores montado em %.1f s", r.segundos)
                    self._completo = (chave, r)
                return self._completo[1]
        with self._trava_recortes:
            if chave in self._recortes:
                self._recortes.move_to_end(chave)
                return self._recortes[chave]
        r = Recorte(self.calc, self.nomes_vendedores(), ids)
        log.info("recorte do Assistente montado em %.1f s (%d vendedores)", r.segundos, len(ids))
        with self._trava_recortes:
            self._recortes[chave] = r
            for antiga in [k for k in self._recortes if k[:4] != chave[:4]]:
                del self._recortes[antiga]  # dados ou regras mudaram: o recorte velho não serve mais
            while len(self._recortes) > self.cfg.recortes:
                self._recortes.popitem(last=False)
        return r

    def info(self, usuario: dict, vendedores: set[int] | None, equipes: set[str] | None) -> dict:
        """O que a página mostra antes da primeira pergunta."""
        cache = self.calc.cache
        pronto = cache.pronto() and not cache.sem_detalhe
        escopo = None
        if cache.pronto():
            escopo = self.descrever_escopo(self.ids_do_escopo(vendedores, equipes), vendedores, equipes)
        admin = usuario["papel"] == "admin"
        return {
            "configurado": self.configurado, "pronto": pronto, "data_ref": cache.info.get("data_ref"),
            "escopo": escopo, "restantes": self.restantes(usuario), "limite_diario": self.cfg.limite_diario,
            **({"modelo": self.cfg.modelo, "esforco": self.cfg.esforco} if admin else {}),
        }

    def catalogo_vendedores(self) -> list[dict]:
        """Vendedores (da venda) com venda nos últimos 12 meses, para a configuração escolher "só alguns"."""
        cache = self.calc.cache
        regras = self.calc.regras()
        data_ref = cache.data_ref() or dt.date.today()
        nomes = self.nomes_vendedores()
        erp = {r[0]: r[1:] for r in cache.consulta("SELECT id, nome, inativo FROM vendedores")}
        lista = []
        for vid, venda, ultima in cache.consulta(
                "SELECT id_vendedor, SUM(valor), MAX(data) FROM vendas_itens WHERE data > ? GROUP BY 1",
                [data_ref - dt.timedelta(days=365)]):
            equipe = regras.grupo_vendedor(vid)
            nome_erp, inativo = erp.get(vid, ("", 1))
            lista.append({"id": vid, "nome": nomes.get(vid) or ("Sem vendedor" if vid == 0 else f"Vendedor {vid}"),
                          "nome_erp": nome_erp or "", "equipe": equipe, "rotulo_equipe": NOME_EQUIPE.get(equipe, equipe),
                          "inativo": bool(inativo), "venda_12m": round(venda or 0.0, 2),
                          "ultima_venda": ultima.isoformat() if ultima else None})
        ordem = {e: i for i, e in enumerate(NOME_EQUIPE)}
        lista.sort(key=lambda v: (ordem.get(v["equipe"], 9), -v["venda_12m"]))
        return lista

    # --- limites e registro ------------------------------------------------------------
    def restantes(self, usuario: dict) -> int | None:
        if usuario["papel"] == "admin":
            return None
        perguntas, _custo = self.registro.do_dia(usuario["id"])
        return max(0, self.cfg.limite_diario - perguntas)

    def _registrar(self, registro: dict) -> None:
        """Grava o registro da pergunta. A resposta já foi paga: se o banco falhar aqui, ela segue para a pessoa e o
        registro fica inteiro no log, em vez de se perder."""
        try:
            self.registro.gravar(registro)
        except Exception:
            log.exception("não deu para gravar o registro da pergunta no banco; ele fica aqui: %s",
                          json.dumps(registro, ensure_ascii=False, default=str))

    def uso(self, dias: int = 30) -> dict:
        """Resumo do uso para a configuração da página: por pessoa nos últimos dias e as últimas perguntas."""
        return {"dias": dias, "limite_diario": self.cfg.limite_diario, "limite_custo_dia": self.cfg.limite_custo_dia,
                **self.registro.resumo(dias)}

    # --- pergunta ------------------------------------------------------------------------
    def _api(self):
        if self._cliente is None:
            import anthropic  # só aqui: sem o Assistente configurado, o painel abre sem o pacote
            self._cliente = anthropic.Anthropic(api_key=self.cfg.chave, max_retries=2, timeout=self.cfg.timeout)
        return self._cliente

    def _contexto(self, usuario: dict, escopo: str, gestao=None) -> str:
        """Parte das instruções que muda com o dia, os dados e quem pergunta (fica depois da parte fixa). gestao: o
        ContextoGestao de quem pergunta (None = o acesso não inclui a página Gestão)."""
        cache, hoje = self.calc.cache, dt.date.today()
        data_ref = cache.data_ref()
        regras = self.calc.regras()
        motivos = dict(cache.consulta("SELECT id, nome FROM motivos"))
        descontam = ", ".join(f"{motivos.get(m, m)} ({m})" for m in sorted(regras.motivos)) or "nenhum"
        return (f"# Situação\n"
                f"- Hoje: {DIAS_SEMANA[hoje.weekday()]}, {hoje:%d/%m/%Y}.\n"
                f"- Dados de vendas até {DIAS_SEMANA[data_ref.weekday()]}, {data_ref:%d/%m/%Y} (cópia do ERP de "
                f"{cache.info.get('banco_copia', '?').replace('T', ' ')}); histórico desde "
                f"{cache.info.get('inicio', '2024-01-01')}. Mês de {MESES[data_ref.month - 1]} de {data_ref.year} "
                f"em andamento até essa data.\n"
                f"- Quem pergunta: {usuario['nome']} ({'administrador' if usuario['papel'] == 'admin' else 'visualizador'}); "
                f"vê {escopo}.\n"
                f"- Ações (página Gestão): "
                f"{('pode lançar e acompanhar' if gestao.admin else 'pode acompanhar (só o administrador lança)') if gestao else 'o acesso não inclui'}.\n"
                f"- Categorias das outras linhas: {', '.join(regras.categorias) or 'nenhuma'}.\n"
                f"- Motivos de devolução que descontam: {descontam}.")

    @staticmethod
    def _historico(mensagens: list) -> list[dict]:
        """Confere o que veio do navegador e monta as mensagens da API (só texto; ver o início do módulo)."""
        if not isinstance(mensagens, list) or not mensagens:
            raise ErroAssistente("escreva uma pergunta")
        mensagens = mensagens[-MAX_MENSAGENS:]
        while mensagens and mensagens[0].get("papel") != "usuario":
            mensagens = mensagens[1:]
        saida, esperado, consultas = [], "usuario", ""
        for m in mensagens:
            papel, texto = m.get("papel"), str(m.get("texto") or "").strip()
            if papel != esperado:
                raise ErroAssistente("conversa fora de ordem; comece uma nova conversa")
            if not texto:
                raise ErroAssistente("escreva uma pergunta")
            if len(texto) > MAX_TEXTO[papel]:
                raise ErroAssistente("mensagem longa demais" if papel == "usuario" else "conversa longa demais; comece uma nova")
            if papel == "usuario":
                prefixo = f"<consultas_anteriores>\n{consultas}\n</consultas_anteriores>\n\n" if consultas else ""
                saida.append({"role": "user", "content": prefixo + texto})
                esperado = "assistente"
            else:
                saida.append({"role": "assistant", "content": texto})
                consultas = str(m.get("consultas") or "")[:2000]
                esperado = "usuario"
        if esperado != "assistente":
            raise ErroAssistente("a última mensagem tem de ser a pergunta")
        return saida

    def perguntar(self, usuario: dict, conversa_id, pergunta, vendedores: set[int] | None,
                  equipes: set[str] | None, gestao=None) -> dict:
        """Pergunta numa conversa do histórico (sem conversa_id, começa uma nova). A pergunta e a resposta são
        gravadas antes de a pessoa ser liberada para a próxima, para quem acompanha ver as duas juntas.
        gestao: bi/gestao.py ContextoGestao de quem pergunta, para as ferramentas de campanha (None = sem a página)."""
        pergunta = str(pergunta or "").strip()
        if not pergunta:
            raise ErroAssistente("escreva uma pergunta")
        if len(pergunta) > MAX_TEXTO["usuario"]:
            raise ErroAssistente("mensagem longa demais")
        dono = usuario["id"]
        try:
            if conversa_id:
                anteriores = self.conversas.historico(dono, conversa_id)
            else:
                self.conversas.verificar()
                anteriores = []
        except BancoForaDoAr as e:  # sem o banco a resposta não seria gravada: nem chama a IA
            raise ErroAssistente("o histórico de conversas está fora do ar agora; tente de novo em instantes", 503) from e
        if anteriores is None:
            raise ErroAssistente("conversa não encontrada; ela pode ter sido excluída", 404)
        if len(anteriores) >= MAX_MENSAGENS_CONVERSA:
            raise ErroAssistente(f"esta conversa chegou ao limite de {MAX_MENSAGENS_CONVERSA // 2} perguntas; "
                                 "comece uma nova")
        conversa_id = id_valido(conversa_id) if conversa_id else novo_id()

        def guardar(r: dict) -> dict:
            try:
                return self.conversas.acrescentar(dono, conversa_id, pergunta, {**r, "texto": r["resposta"]})
            except BancoForaDoAr as e:
                raise ErroAssistente("a resposta ficou pronta, mas não deu para gravar a conversa; tente de novo",
                                     503) from e

        return self.responder(usuario, anteriores + [{"papel": "usuario", "texto": pergunta}], vendedores, equipes,
                              pendente={"conversa": conversa_id, "nova": not anteriores, "pergunta": pergunta},
                              guardar=guardar, gestao=gestao)

    def pendente(self, usuario: int) -> dict | None:
        """A pergunta que ainda está sendo respondida para esta pessoa (de outra aba ou de antes de recarregar a
        página): {conversa, nova, pergunta, segundos}."""
        with self._trava:
            p = self._ocupados.get(usuario)
            if not p or "conversa" not in p:
                return None
            return {**{k: p[k] for k in ("conversa", "nova", "pergunta")}, "segundos": round(time.time() - p["inicio"])}

    def responder(self, usuario: dict, mensagens: list, vendedores: set[int] | None, equipes: set[str] | None,
                  pendente: dict | None = None, guardar=None, gestao=None) -> dict:
        """mensagens: a conversa inteira, terminando na pergunta (perguntar() monta a partir do histórico).
        pendente: o que pendente() mostra enquanto a pergunta roda. guardar(resultado): grava a resposta antes de
        liberar a pessoa; devolve o "conversa"."""
        if not self.configurado:
            raise ErroAssistente("o Assistente ainda não foi configurado: falta a chave da API em [ia] no config.ini", 503)
        cache = self.calc.cache
        if not cache.pronto():
            raise ErroAssistente("os dados ainda estão sendo preparados", 503)
        if cache.sem_detalhe:
            raise ErroAssistente("os dados por cliente ainda não chegaram do computador da empresa; tente depois da "
                                 "próxima atualização", 503)
        api_mensagens = self._historico(mensagens)
        dono, admin = usuario["id"], usuario["papel"] == "admin"
        with self._trava:  # só a reserva: a contagem no banco fica fora, para um banco lento não segurar ninguém
            if dono in self._ocupados:
                raise ErroAssistente("espere a resposta da pergunta anterior", 429)
            self._ocupados[dono] = {**(pendente or {}), "inicio": time.time()}
        try:
            perguntas, custo = self.registro.do_dia(dono)
            if not admin and perguntas >= self.cfg.limite_diario:
                raise ErroAssistente(f"você chegou ao limite de {self.cfg.limite_diario} perguntas por dia; "
                                     "amanhã libera de novo", 429)
            if custo >= self.cfg.limite_custo_dia:
                raise ErroAssistente("o Assistente chegou ao limite de gasto do dia; fale com o administrador", 429)
            if not self._vagas.acquire(timeout=20):
                raise ErroAssistente("o Assistente está atendendo outras pessoas; tente de novo em instantes", 429)
            try:
                r = self._responder(usuario, api_mensagens, vendedores, equipes, (pendente or {}).get("conversa"),
                                    gestao)
            finally:
                self._vagas.release()
            r["restantes"] = None if admin else max(0, self.cfg.limite_diario - perguntas - 1)
            if guardar:
                r["conversa"] = guardar(r)
            return r
        finally:
            with self._trava:
                self._ocupados.pop(dono, None)

    def _responder(self, usuario, api_mensagens, vendedores, equipes, conversa: str | None = None,
                   gestao=None) -> dict:
        t0 = time.time()
        pergunta = _sem_prefixo(api_mensagens[-1]["content"])
        ids = self.ids_do_escopo(vendedores, equipes)
        if ids is not None and not ids:
            raise ErroAssistente("seu acesso ainda não tem vendedores no Assistente; fale com o administrador", 403)
        escopo = self.descrever_escopo(ids, vendedores, equipes)
        ferramentas = Ferramentas(self.recorte(ids), self.calc, self.cfg, equipes, gestao=gestao)
        system = [{"type": "text", "text": INSTRUCOES, "cache_control": {"type": "ephemeral"}},
                  {"type": "text", "text": self._contexto(usuario, escopo, gestao)}]
        uso = {"entrada": 0, "saida": 0, "cache_leitura": 0, "cache_escrita": 0, "chamadas": 0}
        passos: list[dict] = []
        texto, aviso, erro, modelo, parada, ids_req = "", None, None, self.cfg.modelo, None, []
        try:
            for n in range(self.cfg.max_passos + 1):
                ultimo = n == self.cfg.max_passos or time.time() - t0 > self.cfg.tempo_total
                resp = self._chamar(system, api_mensagens, ultimo)
                uso["chamadas"] += 1
                for k, campo in (("entrada", "input_tokens"), ("saida", "output_tokens"),
                                 ("cache_leitura", "cache_read_input_tokens"),
                                 ("cache_escrita", "cache_creation_input_tokens")):
                    uso[k] += getattr(resp.usage, campo, 0) or 0
                modelo, parada = getattr(resp, "model", modelo), resp.stop_reason
                ids_req.append(getattr(resp, "_request_id", None) or getattr(resp, "id", None))
                if parada == "refusal":
                    texto = "Não consegui responder a esta pergunta."
                    aviso = "A IA recusou a pergunta. Tente reformular, perguntando só sobre os dados de vendas."
                    break
                usos = [b for b in resp.content if b.type == "tool_use"]
                if parada == "pause_turn":
                    api_mensagens.append({"role": "assistant", "content": resp.content})
                    continue
                if parada == "tool_use" and usos and not ultimo:
                    api_mensagens.append({"role": "assistant", "content": resp.content})
                    resultados = []
                    for b in usos:
                        resultado, passo = ferramentas.executar(b.name, dict(b.input or {}))
                        passos.append(passo)
                        resultados.append({"type": "tool_result", "tool_use_id": b.id,
                                           "content": json.dumps(resultado, ensure_ascii=False, default=str),
                                           **({"is_error": True} if passo["erro"] else {})})
                    api_mensagens.append({"role": "user", "content": resultados})
                    continue
                texto = "".join(b.text for b in resp.content if b.type == "text").strip()
                if parada == "max_tokens":
                    aviso = "A resposta ficou longa demais e foi cortada. Peça um recorte menor."
                elif ultimo and n == self.cfg.max_passos:
                    aviso = "A pergunta precisou de muitas consultas; a resposta pode estar incompleta."
                break
            if not texto:
                texto = "Não consegui chegar a uma resposta. Tente perguntar de outro jeito."
        except Exception as e:
            erro = str(e) if isinstance(e, ErroAssistente) else f"{type(e).__name__}: {e}"
            raise
        finally:
            custo = sum(uso[k] * self.cfg.precos[k] for k in ("entrada", "saida", "cache_leitura", "cache_escrita")) / 1e6
            uso.update(custo=round(custo, 5), modelo=modelo, segundos=round(time.time() - t0, 1))
            self._registrar({
                "usuario": usuario["id"], "login": usuario["login"], "nome": usuario["nome"], "conversa": conversa,
                "escopo": escopo, "pergunta": pergunta[:4000],
                "resposta": texto[:4000], "aviso": aviso, "erro": erro, "parada": parada, "uso": uso,
                "passos": [{k: p.get(k) for k in ("ferramenta", "args", "sql", "linhas", "ms", "erro")} for p in passos],
                "data_ref": self.calc.cache.info.get("data_ref"), "pedidos_api": ids_req,
            })
        admin = usuario["papel"] == "admin"
        return {
            "resposta": texto, "aviso": aviso, "consultas": _resumo_consultas(passos), "passos": passos,
            "rascunhos": ferramentas.rascunhos, "data_ref": self.calc.cache.info.get("data_ref"), "escopo": escopo,
            "uso": uso if admin else {"segundos": uso["segundos"]},
        }

    def _chamar(self, system, mensagens, ultimo: bool):
        pedido = dict(
            model=self.cfg.modelo, max_tokens=self.cfg.max_tokens, system=system, tools=FERRAMENTAS,
            messages=mensagens, output_config={"effort": self.cfg.esforco}, cache_control={"type": "ephemeral"},
            betas=[BETA_FALLBACK], fallbacks="default",
        )
        if ultimo:
            pedido["tool_choice"] = {"type": "none"}  # fim do orçamento de passos: responde com o que tem
        try:
            return self._api().beta.messages.create(**pedido)
        except Exception as e:
            raise _traduzir_erro(e, self.cfg.modelo) from e


def _sem_prefixo(texto: str) -> str:
    if texto.startswith("<consultas_anteriores>"):
        return texto.split("</consultas_anteriores>", 1)[-1].strip()
    return texto


# Ferramentas cujo resumo leva os primeiros achados (código e nome), para a próxima pergunta usar os códigos.
ACHADOS = {"buscar_cliente": 3, "buscar_produto": 3, "buscar_vendedor": 3, "listar_acoes": 5}


def _resumo_consultas(passos: list[dict]) -> str:
    """Linha por ferramenta usada, para a próxima pergunta saber o que já foi consultado (códigos achados etc.)."""
    linhas = []
    for p in passos:
        # O rascunho de ação leva todos os campos: no resumo vai só o que ficou (cabe no limite).
        args = "" if p["ferramenta"] == "propor_acao" else json.dumps(p["args"], ensure_ascii=False,
                                                                       separators=(",", ":"))
        if p.get("resumo") and not p["erro"]:
            linhas.append(f"{p['ferramenta']}{args} -> {p['resumo']}")
        elif p["ferramenta"] in ACHADOS and p["amostra"] and not p["erro"]:
            achados = "; ".join(f"{r[0]} {r[1]}" for r in p["amostra"][:ACHADOS[p['ferramenta']]])
            linhas.append(f"{p['ferramenta']}{args} -> {achados}")
        else:
            linhas.append(f"{p['ferramenta']}{args}" + (" -> erro" if p["erro"] else ""))
    texto = "\n".join(linhas)
    return texto if len(texto) <= 2000 else texto[:1990] + "\n…"


def _traduzir_erro(e: Exception, modelo: str) -> Exception:
    try:
        import anthropic
    except ImportError:
        return ErroAssistente("falta instalar o pacote anthropic (pip install anthropic)", 503)
    if isinstance(e, anthropic.AuthenticationError):
        return ErroAssistente("a chave da API em [ia] no config.ini não foi aceita pela Anthropic", 502)
    if isinstance(e, anthropic.PermissionDeniedError):
        return ErroAssistente("a chave da API não tem permissão para usar este modelo", 502)
    if isinstance(e, anthropic.NotFoundError):
        return ErroAssistente(f"o modelo {modelo} não foi encontrado na API (confira [ia] modelo)", 502)
    if isinstance(e, anthropic.RateLimitError):
        return ErroAssistente("a API está no limite de uso por minuto; tente de novo daqui a pouco", 429)
    if isinstance(e, anthropic.BadRequestError):
        return ErroAssistente(f"a API recusou o pedido: {e.message}", 502)
    if isinstance(e, anthropic.APIStatusError):
        if e.status_code >= 500:
            return ErroAssistente("a API da Anthropic está instável agora; tente de novo em instantes", 503)
        return ErroAssistente(f"erro da API ({e.status_code}): {e.message}", 502)
    if isinstance(e, anthropic.APIConnectionError):
        return ErroAssistente("sem conexão com a API da Anthropic; tente de novo em instantes", 503)
    return e

"""Histórico da carteira: quem estava ativo, e com que vendedor, em cada dia (a cobertura da positivação nas campanhas
da Gestão, bi/indicadores.py).

O ERP não guarda quando um cliente foi inativado nem quando trocou de vendedor: só o estado de agora. Por isso, a cada
extração (bi/cache.py), o painel compara os clientes ativos do cadastro (INATIVO = 0) com os trechos abertos no
PostgreSQL e grava só o que mudou (decisão do usuário):
- cada trecho (clientes_vigencias) diz o vendedor da carteira, se o nome tem "PEDIDO BLOQUEADO", a UF, a área e o
  segmento, e de quando (de) até quando (ate) valeu; ate vazio = ainda vale;
- o cliente que entra (cadastro novo ou reativado) abre um trecho: o cadastro novo, desde a DATACADASTRO (se ela é
  depois do retrato anterior); o reativado, desde o dia da cópia;
- o cliente que sai (inativado ou apagado) tem o trecho fechado no dia anterior ao da cópia em que sumiu;
- o cliente que muda (vendedor, bloqueado, UF, área ou segmento) fecha um trecho e abre outro;
- um trecho aberto no dia (desde o retrato anterior) que some ou muda de novo no mesmo dia não deixa rastro; nada mais
  é apagado nem sobrescrito.
A data de uma mudança é a da cópia do ERP em que ela apareceu (as cópias chegam de 1 a 4 vezes por dia útil). Cada dia
conferido vira uma linha em carteira_retratos: desde quando há histórico, e quantos entraram, saíram e trocaram de
vendedor.

As duas tabelas vão também no cache (o VPS lê de lá). Se o banco do PC se perder, voltam do cache na extração seguinte.
"""
from __future__ import annotations

import datetime as dt
import logging

log = logging.getLogger("bi.carteira")

TRAVA = 7_240_104  # pg_advisory_xact_lock: duas extrações (ou a semeadura) não registram juntas
# O que um trecho guarda além das datas (e a ordem das colunas em estado()).
CAMPOS = ("id_vendedor", "bloqueado", "uf", "id_area", "area", "segmento")
VIGENCIAS = ("id_cliente", "de", "ate", *CAMPOS)
RETRATOS = ("data", "ativos", "entradas", "saidas", "trocas")
BLOQUEADO = "PEDIDO BLOQUEADO"


def estado(clientes, detalhes) -> tuple[dict[int, tuple], dict[int, dt.date]]:
    """Os ativos de agora: ({cliente: (vendedor, bloqueado, uf, id_area, area, segmento)}, {cliente: data de cadastro}).
    clientes: (id, nome, id_vendedor) do cadastro (vendedor 0 = sem vendedor); detalhes: as linhas de clientes_detalhes
    do cache (id, razao_social, cidade, uf, id_area, area, id_segmento, segmento, inativo, data_cadastro)."""
    por_id = {d[0]: d for d in detalhes}
    ativos, cadastro = {}, {}
    for id_, nome, vendedor in clientes:
        d = por_id.get(id_)
        if d is None or int(d[8] or 0) != 0:
            continue
        ativos[id_] = (vendedor or None, BLOQUEADO in str(nome or "").upper(), d[3], d[4], d[5], d[7])
        if d[9]:
            cadastro[id_] = d[9].date() if isinstance(d[9], dt.datetime) else d[9]
    return ativos, cadastro


def registrar(con, ativos: dict[int, tuple], cadastro: dict[int, dt.date], data: dt.date,
              origem: str = "extracao") -> dict:
    """Compara os ativos (estado()) com os trechos abertos e grava o que mudou, como retrato do dia `data` (o da cópia
    do ERP). Rodar de novo no mesmo dia com o mesmo estado não muda nada. Devolve o resumo da conferência. Levanta
    ValueError para um dia antes do último retrato (a semeadura vem antes da primeira extração)."""
    con.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA])
    ultimo = con.execute("SELECT max(data) FROM carteira_retratos").fetchone()[0]
    if ultimo and data < ultimo:
        raise ValueError(f"o retrato de {data:%d/%m/%Y} é de antes do último ({ultimo:%d/%m/%Y})")
    anterior = con.execute("SELECT max(data) FROM carteira_retratos WHERE data < %s", [data]).fetchone()[0]
    abertos = {r[0]: (r[1], tuple(r[2:])) for r in con.execute(
        f"SELECT id_cliente, de, {', '.join(CAMPOS)} FROM clientes_vigencias WHERE ate IS NULL")}
    apagar, mudar, fechar, abrir = [], [], [], []
    entradas = saidas = trocas = 0
    for id_, (de, atual) in abertos.items():
        novo = ativos.get(id_)
        if novo == atual:
            continue
        if novo is None:
            saidas += 1
        elif novo[0] != atual[0]:
            trocas += 1
        if anterior is None or de > anterior:  # aberto desde o retrato anterior: some ou muda no lugar
            (apagar.append([id_, de]) if novo is None else mudar.append([*novo, id_, de]))
        else:
            fechar.append([data - dt.timedelta(days=1), id_, de])
            if novo is not None:
                abrir.append([id_, data, *novo])
    for id_, novo in ativos.items():
        if id_ in abertos:
            continue
        entradas += 1
        c = cadastro.get(id_)
        abrir.append([id_, c if anterior and c and anterior < c < data else data, *novo])
    with con.cursor() as cur:
        if apagar:
            cur.executemany("DELETE FROM clientes_vigencias WHERE id_cliente = %s AND de = %s", apagar)
        if mudar:
            cur.executemany(f"UPDATE clientes_vigencias SET {', '.join(f'{k} = %s' for k in CAMPOS)} "
                            "WHERE id_cliente = %s AND de = %s", mudar)
        if fechar:
            cur.executemany("UPDATE clientes_vigencias SET ate = %s WHERE id_cliente = %s AND de = %s", fechar)
        if abrir:
            cur.executemany(f"INSERT INTO clientes_vigencias (id_cliente, de, {', '.join(CAMPOS)}) "
                            f"VALUES (%s, %s, {', '.join(['%s'] * len(CAMPOS))}) ON CONFLICT (id_cliente, de) DO UPDATE "
                            f"SET ate = NULL, {', '.join(f'{k} = EXCLUDED.{k}' for k in CAMPOS)}", abrir)
    con.execute("INSERT INTO carteira_retratos (data, ativos, entradas, saidas, trocas, origem) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (data) DO UPDATE SET ativos = EXCLUDED.ativos, "
                "entradas = carteira_retratos.entradas + EXCLUDED.entradas, "
                "saidas = carteira_retratos.saidas + EXCLUDED.saidas, "
                "trocas = carteira_retratos.trocas + EXCLUDED.trocas, em = now()",
                [data, len(ativos), entradas, saidas, trocas, origem])
    return {"data": data, "ativos": len(ativos), "entradas": entradas, "saidas": saidas, "trocas": trocas}


def ler(con) -> dict[str, list]:
    """As duas tabelas, como vão para o cache (colunas de VIGENCIAS e RETRATOS)."""
    return {"clientes_vigencias": [tuple(r) for r in con.execute(
                f"SELECT {', '.join(VIGENCIAS)} FROM clientes_vigencias ORDER BY id_cliente, de")],
            "carteira_retratos": [tuple(r) for r in con.execute(
                f"SELECT {', '.join(RETRATOS)} FROM carteira_retratos ORDER BY data")]}


def restaurar(con, tabelas: dict[str, list]) -> bool:
    """Banco sem nenhum retrato (o do PC se perdeu) e o cache com o histórico: põe o do cache de volta no banco."""
    if con.execute("SELECT EXISTS (SELECT 1 FROM carteira_retratos)").fetchone()[0]:
        return False
    vigencias, retratos = tabelas.get("clientes_vigencias") or [], tabelas.get("carteira_retratos") or []
    if not retratos:
        return False
    with con.cursor() as cur:
        cur.executemany(f"INSERT INTO clientes_vigencias ({', '.join(VIGENCIAS)}) "
                        f"VALUES ({', '.join(['%s'] * len(VIGENCIAS))})", [list(r) for r in vigencias])
        cur.executemany(f"INSERT INTO carteira_retratos ({', '.join(RETRATOS)}, origem) "
                        f"VALUES ({', '.join(['%s'] * len(RETRATOS))}, 'cache')", [list(r) for r in retratos])
    log.warning("o histórico da carteira voltou do cache para o banco (%d trechos, %d dias)", len(vigencias), len(retratos))
    return True


class Carteira:
    """O registro da carteira que a extração do cache chama (só no PC: o VPS lê as tabelas do cache recebido)."""

    def __init__(self, banco):
        self.banco = banco

    def __call__(self, ativos: dict, cadastro: dict, data: dt.date, anterior: dict | None = None) -> dict[str, list]:
        """Registra o retrato do dia e devolve as tabelas para o cache. anterior: as do cache em uso (para restaurar
        um banco vazio)."""
        with self.banco.conexao() as con:
            if anterior:
                restaurar(con, anterior)
            r = registrar(con, ativos, cadastro, data)
            log.info("carteira em %s: %d ativos, %d entradas, %d saídas, %d trocas de vendedor", data.isoformat(),
                     r["ativos"], r["entradas"], r["saidas"], r["trocas"])
            return ler(con)

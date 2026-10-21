"""Página Reavaliação de Crédito: os números da página "Reavaliação Credito" do Power BI, por cliente.

A base são os títulos a receber de venda a cliente que não foram cancelados (o filtro de todas as medidas da página
no Power BI, já aplicado na extração: tabela titulos_receber do cache), mais o limite e o prazo do cadastro
(clientes_credito). Mês e ano filtram pela emissão; vendedor é o do título, como no Power BI.

Diferenças aprovadas em relação ao Power BI:
- a pontualidade sai em % (lá, o formato inteiro mostra 0 ou 1);
- o limite restante desconta todos os títulos em aberto do cliente, sem o filtro de mês e ano (lá, só os emitidos
  no período, e o restante parece maior do que é);
- limite, restante e prazo só com cliente escolhido (sem cliente, o Power BI soma o limite de todos e ignora o
  vendedor); com vários clientes, os limites e os títulos em aberto deles somam;
- um título por linha na tabela, que dá para ordenar por qualquer coluna; a de preço médio por produto ficou de fora
  (a medida dela não existe mais lá).

Além do Power BI: o valor já pago de cada título (boleto dividido em parcelas, tabela titulos_parcelas do cache).
As parcelas pagas saem do que está em aberto e voltam para o limite restante.

"Hoje" é o dia da extração, para os dias de atraso baterem com a foto dos dados.
"""
from __future__ import annotations

import datetime as dt

from .cache import Cache

TOLERANCIA = 7  # dias depois do vencimento em que o pagamento ainda é pontual e o atraso ainda não é inadimplência
MAX_TITULOS = 500
MAX_BUSCA = 30
MAX_CLIENTES = 100
# Colunas da tabela de títulos que dá para ordenar: chave da página -> expressão sobre a subconsulta x.
ORDENS = {
    "emissao": "x.emissao", "titulo": "x.id", "cliente": "x.cliente",
    "vendedor": "list_position(CAST(? AS INTEGER[]), x.id_vendedor)",  # pelo nome que a página mostra
    "vencimento": "x.vencimento", "quitacao": "x.quitacao", "valor": "x.total", "pago": "x.pago", "dias": "x.dias",
    "situacao": "gravidade",  # calculada no SELECT de fora (GRAVIDADE)
}
# A situação ordenada da melhor para a pior (a mesma conta de situacao() abaixo, em SQL).
GRAVIDADE = (f"CASE WHEN x.quitado = 1 THEN CASE WHEN x.dias > {TOLERANCIA} THEN 2 ELSE 0 END "
             f"WHEN x.dias > {TOLERANCIA} THEN 4 WHEN x.dias > 0 THEN 3 ELSE 1 END")


def _marcas(ids) -> str:
    return ",".join("?" * len(ids))


def situacao(quitado: bool, dias: int) -> str:
    if quitado:
        return "quitado_atraso" if dias > TOLERANCIA else "quitado"
    if dias > TOLERANCIA:
        return "inadimplente"
    return "vencido" if dias > 0 else "a_vencer"


class Credito:
    def __init__(self, cache: Cache, nomes_vendedores):
        """nomes_vendedores: função que devolve {id: nome} (a mesma das Projeções e do Assistente)."""
        self.cache = cache
        self.nomes_vendedores = nomes_vendedores

    def hoje(self) -> dt.date:
        v = self.cache.info.get("extraido_em")
        return dt.datetime.fromisoformat(v).date() if v else dt.date.today()

    def _conferir(self) -> None:
        if not self.cache.pronto():
            raise RuntimeError("os dados ainda estão sendo preparados")
        if self.cache.sem_credito:
            if self.cache.info.get("credito_erro"):
                raise RuntimeError("não deu para ler os títulos a receber no banco do ERP; o computador da empresa "
                                   "tenta de novo na próxima cópia do banco")
            raise RuntimeError("os dados de crédito ainda não chegaram do computador da empresa; aparecem depois da "
                               "próxima atualização")

    def _parcelas(self) -> tuple[str, str, str, str]:
        """(junção, pago, parcelas, pagas) sobre o título t: sem a tabela das parcelas no cache, conta só o título
        quitado como pago."""
        if self.cache.sem_parcelas:
            return "", "CASE WHEN t.quitado = 1 THEN t.total ELSE 0 END", "1", "t.quitado"
        return (" LEFT JOIN titulos_parcelas p ON p.id = t.id",
                "COALESCE(p.pago, CASE WHEN t.quitado = 1 THEN t.total ELSE 0 END)", "COALESCE(p.parcelas, 1)",
                "COALESCE(p.pagas, t.quitado)")

    # --- busca de cliente ---------------------------------------------------------------
    def buscar(self, texto: str, limite: int = MAX_BUSCA) -> list[dict]:
        """Clientes pelo nome (sem acento nem caixa) ou pelo código: o código exato primeiro, depois quem começa com o
        texto e, entre esses, quem tem títulos."""
        self._conferir()
        texto = (texto or "").strip()
        if not texto:
            return []
        codigo = int(texto) if texto.isdigit() else -1
        nomes = self.nomes_vendedores()
        linhas = self.cache.consulta(
            "WITH b AS (SELECT strip_accents(lower(?)) AS q), "
            "achados AS (SELECT c.id, c.nome, c.id_vendedor, starts_with(strip_accents(lower(c.nome)), b.q) AS comeca "
            "  FROM clientes c, b WHERE c.id = ? OR strip_accents(lower(c.nome)) LIKE '%' || b.q || '%') "
            "SELECT a.id, a.nome, a.id_vendedor, COUNT(t.id) AS n FROM achados a "
            "LEFT JOIN titulos_receber t ON t.id_cliente = a.id GROUP BY a.id, a.nome, a.id_vendedor, a.comeca "
            "ORDER BY a.id <> ?, NOT a.comeca, n = 0, a.nome LIMIT ?",
            [texto, codigo, codigo, max(1, min(limite, MAX_BUSCA))])
        return [{"id": i, "nome": n, "carteira": nomes.get(v) if v else None, "titulos": t} for i, n, v, t in linhas]

    # --- a página -----------------------------------------------------------------------
    def calcular(self, clientes: list[int] | None = None, mes: int | None = None, ano: int | None = None,
                 vendedor: int | None = None, permitidos: set[int] | None = None, ordem: str | None = None,
                 sentido: str | None = None) -> dict:
        """Cartões e títulos do filtro. clientes: um ou mais códigos (os limites somam); None ou vazio = todos.
        permitidos: vendedores cujos títulos contam (o acesso do Assistente); None = todos. ordem e sentido: a coluna
        da tabela de títulos (ORDENS) e "asc" ou "desc"; sem ordem, da emissão mais recente para a mais antiga.
        Parâmetro inválido -> ValueError."""
        self._conferir()
        hoje = self.hoje()
        clientes = list(dict.fromkeys(clientes or []))  # sem repetir, na ordem em que foram escolhidos
        if len(clientes) > MAX_CLIENTES:
            raise ValueError(f"escolha no máximo {MAX_CLIENTES} clientes")
        if mes is not None and not 1 <= mes <= 12:
            raise ValueError(f"mês inválido: {mes}")
        if ano is not None and not 1900 <= ano <= hoje.year + 1:
            raise ValueError(f"ano inválido: {ano}")
        if ordem is not None and ordem not in ORDENS:
            raise ValueError(f"coluna inválida para ordenar: {ordem}")
        if sentido not in (None, "asc", "desc"):
            raise ValueError(f"sentido inválido: {sentido}")
        nomes = self.nomes_vendedores()
        junta, pago, parcelas, pagas = self._parcelas()
        dados_clientes = self._clientes(clientes, nomes, junta, pago) if clientes else []

        onde, params = [], []
        if clientes:
            onde.append(f"t.id_cliente IN ({_marcas(clientes)})")
            params += clientes
        if vendedor is not None:
            onde.append("t.id_vendedor = ?")
            params.append(vendedor)
        if permitidos is not None:
            onde.append(f"t.id_vendedor IN ({_marcas(permitidos)})" if permitidos else "FALSE")
            params += sorted(permitidos)
        if mes is not None:
            onde.append("month(t.emissao) = ?")
            params.append(mes)
        if ano is not None:
            onde.append("year(t.emissao) = ?")
            params.append(ano)
        where = f" WHERE {' AND '.join(onde)}" if onde else ""

        valor, quantidade, quitados, atrasados, inadimplencia = self.cache.consulta(
            "SELECT COALESCE(SUM(total), 0), COUNT(*), COUNT(*) FILTER (WHERE quitado = 1), "
            f"COUNT(*) FILTER (WHERE quitado = 1 AND quitacao > vencimento + {TOLERANCIA}), "
            "COALESCE(SUM(total) FILTER (WHERE quitado = 0 AND vencimento < ?), 0) "
            f"FROM titulos_receber t{where}", [hoje - dt.timedelta(days=TOLERANCIA), *params])[0]

        # A tabela: ordenada aqui (e não na página), para valer para o filtro inteiro e não só para as linhas mostradas.
        sentido = sentido or ("desc" if ordem is None else "asc")
        ordem = ordem or "emissao"
        por_nome = [sorted(nomes, key=lambda v: nomes[v].lower())] if ordem == "vendedor" else []
        linhas = self.cache.consulta(
            f"SELECT x.*, {GRAVIDADE} AS gravidade FROM ("
            "SELECT t.id, t.id_cliente, c.nome AS cliente, t.id_vendedor, t.emissao, t.vencimento, t.quitacao, "
            f"t.quitado, t.total, {pago} AS pago, {parcelas} AS parcelas, {pagas} AS pagas, "
            "datediff('day', t.vencimento, CASE WHEN t.quitado = 1 THEN t.quitacao ELSE ? END) AS dias "
            f"FROM titulos_receber t LEFT JOIN clientes c ON c.id = t.id_cliente{junta}{where}) x "
            f"ORDER BY {ORDENS[ordem]} {sentido.upper()} NULLS LAST, x.emissao DESC, x.id DESC LIMIT ?",
            [hoje, *params, *por_nome, MAX_TITULOS])
        titulos = [{
            "id": i, "id_cliente": idc, "cliente": nomec, "vendedor": nomes.get(v) or f"Vendedor {v}",
            "emissao": emissao, "vencimento": venc, "quitacao": quit, "quitado": bool(quitado), "valor": total,
            "pago": pg, "saldo": 0.0 if quitado else total - pg, "parcelas": n, "pagas": npg,
            "dias_atraso": dias, "situacao": situacao(bool(quitado), dias or 0),
        } for i, idc, nomec, v, emissao, venc, quit, quitado, total, pg, n, npg, dias, _g in linhas]

        avisos = []
        if self.cache.sem_parcelas:
            avisos.append("As parcelas dos títulos ainda não chegaram do computador da empresa: o valor já pago e o "
                          "limite restante ainda não descontam as parcelas pagas.")
        return {
            "data_ref": self.cache.data_ref(),
            "extraido_em": self.cache.info.get("extraido_em"),
            "hoje": hoje,
            "filtros": {"clientes": clientes, "mes": mes, "ano": ano, "vendedor": vendedor},
            "ordem": {"coluna": ordem, "sentido": sentido},
            "opcoes": self._opcoes(hoje, nomes, permitidos),
            "clientes": dados_clientes,
            "credito": self._soma(dados_clientes) if dados_clientes else None,
            "cartoes": {
                "valor": valor, "quantidade": quantidade, "ticket": valor / quantidade if quantidade else None,
                "pontualidade": (quitados - atrasados) / quitados if quitados else None,
                "quitados": quitados, "quitados_atrasados": atrasados, "inadimplencia": inadimplencia,
            },
            "titulos": {"linhas": titulos, "total": quantidade, "mostrando": len(titulos)},
            "avisos": avisos,
        }

    def _clientes(self, clientes: list[int], nomes: dict[int, str], junta: str, pago: str) -> list[dict]:
        """Limite, prazo e o que cada cliente tem em aberto. O limite é do cliente: todos os títulos em aberto dele o
        consomem, de qualquer vendedor e emissão, menos as parcelas já pagas."""
        cadastro = {i: r for i, *r in self.cache.consulta(
            "SELECT c.id, c.nome, c.id_vendedor, k.limite, k.prazo FROM clientes c "
            f"LEFT JOIN clientes_credito k ON k.id = c.id WHERE c.id IN ({_marcas(clientes)})", clientes)}
        faltam = [c for c in clientes if c not in cadastro]
        if faltam:
            raise ValueError(f"cliente não encontrado: {', '.join(map(str, faltam))}")
        abertos = {i: (total, pg) for i, total, pg in self.cache.consulta(
            f"SELECT t.id_cliente, SUM(t.total), SUM({pago}) FROM titulos_receber t{junta} "
            f"WHERE t.id_cliente IN ({_marcas(clientes)}) AND t.quitacao IS NULL GROUP BY 1", clientes)}
        saida = []
        for c in clientes:
            nome, carteira, limite, prazo = cadastro[c]
            total, pg = abertos.get(c, (0.0, 0.0))
            limite = float(limite or 0)
            saida.append({
                "id": c, "nome": nome, "carteira": nomes.get(carteira) if carteira else None, "prazo": prazo,
                "limite": limite, "titulos_abertos": total, "pago_parcelas": pg, "em_aberto": total - pg,
                "restante": limite - (total - pg), "usado": (total - pg) / limite if limite > 0 else None,
            })
        return saida

    @staticmethod
    def _soma(clientes: list[dict]) -> dict:
        soma = {k: sum(c[k] for c in clientes) for k in ("limite", "titulos_abertos", "pago_parcelas", "em_aberto",
                                                          "restante")}
        prazos = sorted({c["prazo"] or "não informado" for c in clientes})
        carteiras = sorted({c["carteira"] or "sem vendedor" for c in clientes})
        return {**soma, "usado": soma["em_aberto"] / soma["limite"] if soma["limite"] > 0 else None,
                "prazos": prazos, "carteiras": carteiras}

    def _opcoes(self, hoje: dt.date, nomes: dict[int, str], permitidos: set[int] | None) -> dict:
        filtro, params = ("", []) if permitidos is None else (
            f" WHERE id_vendedor IN ({_marcas(permitidos)})" if permitidos else " WHERE FALSE", sorted(permitidos))
        ids = [r[0] for r in self.cache.consulta(f"SELECT DISTINCT id_vendedor FROM titulos_receber{filtro}", params)]
        vendedores = sorted(({"id": v, "nome": nomes.get(v) or ("Sem vendedor" if v == 0 else f"Vendedor {v}")}
                             for v in ids), key=lambda x: x["nome"].lower())
        # Datas de emissão digitadas erradas (ano 7190) não viram opção.
        anos = [r[0] for r in self.cache.consulta(
            "SELECT DISTINCT year(emissao) AS a FROM titulos_receber WHERE year(emissao) <= ? ORDER BY a DESC",
            [hoje.year])]
        return {"vendedores": vendedores, "anos": anos}

"""Página Reavaliação de Crédito: os números da página "Reavaliação Credito" do Power BI, por cliente.

A base são os títulos a receber de venda a cliente que não foram cancelados (o filtro de todas as medidas da página
no Power BI, já aplicado na extração: tabela titulos_receber do cache), mais o limite e o prazo do cadastro
(clientes_credito). Mês e ano filtram pela emissão; vendedor é o do título, como no Power BI.

Diferenças aprovadas em relação ao Power BI:
- a pontualidade sai em % (lá, o formato inteiro mostra 0 ou 1);
- o limite restante desconta todos os títulos em aberto do cliente, sem o filtro de mês e ano (lá, só os emitidos
  no período, e o restante parece maior do que é);
- limite, restante e prazo só com um cliente escolhido (sem cliente, o Power BI soma o limite de todos e ignora o
  vendedor);
- um título por linha na tabela; a de preço médio por produto ficou de fora (a medida dela não existe mais lá).

"Hoje" é o dia da extração, para os dias de atraso baterem com a foto dos dados.
"""
from __future__ import annotations

import datetime as dt

from .cache import Cache

TOLERANCIA = 7  # dias depois do vencimento em que o pagamento ainda é pontual e o atraso ainda não é inadimplência
MAX_TITULOS = 500
MAX_BUSCA = 30


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
    def calcular(self, cliente: int | None = None, mes: int | None = None, ano: int | None = None,
                 vendedor: int | None = None, permitidos: set[int] | None = None) -> dict:
        """Cartões e títulos do filtro. permitidos: vendedores cujos títulos contam (o acesso do Assistente);
        None = todos. Parâmetro inválido -> ValueError."""
        self._conferir()
        hoje = self.hoje()
        if mes is not None and not 1 <= mes <= 12:
            raise ValueError(f"mês inválido: {mes}")
        if ano is not None and not 1900 <= ano <= hoje.year + 1:
            raise ValueError(f"ano inválido: {ano}")
        nomes = self.nomes_vendedores()

        dados_cliente = None
        if cliente is not None:
            linha = self.cache.consulta(
                "SELECT c.nome, c.id_vendedor, k.limite, k.prazo FROM clientes c "
                "LEFT JOIN clientes_credito k ON k.id = c.id WHERE c.id = ?", [cliente])
            if not linha:
                raise ValueError(f"cliente não encontrado: {cliente}")
            nome, carteira, limite, prazo = linha[0]
            # O limite é do cliente: todos os títulos em aberto dele o consomem, de qualquer vendedor e emissão.
            em_aberto = self.cache.consulta("SELECT COALESCE(SUM(total), 0) FROM titulos_receber "
                                            "WHERE id_cliente = ? AND quitacao IS NULL", [cliente])[0][0]
            limite = float(limite or 0)
            dados_cliente = {
                "id": cliente, "nome": nome, "carteira": nomes.get(carteira) if carteira else None,
                "prazo": prazo, "limite": limite, "em_aberto": em_aberto, "restante": limite - em_aberto,
                "usado": em_aberto / limite if limite > 0 else None,
            }

        onde, params = [], []
        if cliente is not None:
            onde.append("t.id_cliente = ?")
            params.append(cliente)
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

        linhas = self.cache.consulta(
            "SELECT t.id, t.id_cliente, c.nome, t.id_vendedor, t.emissao, t.vencimento, t.quitacao, t.quitado, t.total "
            f"FROM titulos_receber t LEFT JOIN clientes c ON c.id = t.id_cliente{where} "
            "ORDER BY t.emissao DESC, t.id DESC LIMIT ?", [*params, MAX_TITULOS])
        titulos = []
        for i, idc, nomec, v, emissao, venc, quit, quitado, total in linhas:
            dias = ((quit if quitado else hoje) - venc).days if venc and (quit or not quitado) else None
            titulos.append({
                "id": i, "id_cliente": idc, "cliente": nomec, "vendedor": nomes.get(v) or f"Vendedor {v}",
                "emissao": emissao, "vencimento": venc, "quitacao": quit, "quitado": bool(quitado), "valor": total,
                "dias_atraso": dias, "situacao": situacao(bool(quitado), dias or 0),
            })

        return {
            "data_ref": self.cache.data_ref(),
            "extraido_em": self.cache.info.get("extraido_em"),
            "hoje": hoje,
            "filtros": {"cliente": cliente, "mes": mes, "ano": ano, "vendedor": vendedor},
            "opcoes": self._opcoes(hoje, nomes, permitidos),
            "cliente": dados_cliente,
            "cartoes": {
                "valor": valor, "quantidade": quantidade, "ticket": valor / quantidade if quantidade else None,
                "pontualidade": (quitados - atrasados) / quitados if quitados else None,
                "quitados": quitados, "quitados_atrasados": atrasados, "inadimplencia": inadimplencia,
            },
            "titulos": {"linhas": titulos, "total": quantidade, "mostrando": len(titulos)},
        }

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

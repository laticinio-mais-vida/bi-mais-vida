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

O parecer de um limite novo (analisar): quem digita o limite total que o cliente vai ter recebe Indicado, Indicado com
ressalvas ou Não indicado, com os motivos. É uma regra fixa (sem IA: a mesma resposta para os mesmos dados) sobre o
histórico inteiro do cliente, de qualquer vendedor e sem os filtros da página; os limites dela estão logo abaixo.

O retrato (retrato): o que se sabia do cliente na hora de uma reanálise, que bi/reanalise.py grava com o limite e o
prazo liberados. depois(): o que aconteceu com o cliente depois de uma reanálise, pelos títulos de hoje.

"Hoje" é o dia da extração, para os dias de atraso baterem com a foto dos dados.
"""
from __future__ import annotations

import datetime as dt
import math
import re

from .cache import Cache

TOLERANCIA = 7  # dias depois do vencimento em que o pagamento ainda é pontual e o atraso ainda não é inadimplência
# A regra do parecer (analisar). Inadimplência hoje sempre bloqueia.
JANELA = 365         # dias de histórico para a pontualidade, o maior saldo em aberto e as compras
PONTUAL_OK = 0.9     # pontualidade a partir da qual o critério passa (as mesmas faixas de cor do cartão)
PONTUAL_MIN = 0.7    # abaixo disso, não indicado
MIN_QUITADOS = 5     # menos títulos quitados na janela que isso: pouco para medir a pontualidade
MESES_CLIENTE = 6    # tempo de cliente (pelo primeiro título) abaixo do qual fica a ressalva
DIAS_SEM_COMPRA = 90
FOLGA_OK = 2         # limite pedido até 2x o maior saldo em aberto da janela (arredondado): passa; é o sugerido
FOLGA_MAX = 3        # acima de 3x: não indicado
ARREDONDAR = 500     # o teto de 2x (e o limite sugerido) sobe para o múltiplo de R$ 500 seguinte
# Os mesmos limites para a página (o "como calcula" e o texto do limite sugerido).
REGRA = {"janela_dias": JANELA, "pontual_ok": PONTUAL_OK, "pontual_min": PONTUAL_MIN, "min_quitados": MIN_QUITADOS,
         "meses_cliente": MESES_CLIENTE, "dias_sem_compra": DIAS_SEM_COMPRA, "folga_ok": FOLGA_OK,
         "folga_max": FOLGA_MAX, "arredondar": ARREDONDAR, "tolerancia": TOLERANCIA}
CRITERIOS = {  # chave -> nome na página, na ordem em que aparecem
    "inadimplencia": "Inadimplência", "pontualidade": "Pontualidade nos últimos 12 meses",
    "tempo": "Tempo de cliente", "folga": "Limite pedido × o que já usou", "em_aberto": "Em aberto hoje",
    "recente": "Compras recentes",
}
# O retrato de uma reanálise. A versão sobe quando uma chave muda de sentido ou sai (chave nova não muda a versão).
RETRATO_VERSAO = 1
JANELA_CURTA = 90  # dias dos "últimos 3 meses" do retrato
ATRASO_GRAVE = 30  # dias depois do vencimento: o retrato conta os títulos pagos com mais atraso que isso
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


def _reais(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _pct(v: float) -> str:
    return f"{v * 100:.1f}".replace(".", ",") + "%"


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def _meses(de: dt.date, ate: dt.date) -> int:
    """Meses completos de `de` até `ate`."""
    return (ate.year - de.year) * 12 + ate.month - de.month - (ate.day < de.day)


def _ha(meses: int) -> str:
    if meses < 1:
        return "há menos de um mês"
    anos, resto = divmod(meses, 12)
    if not anos:
        return f"há {_plural(meses, 'mês', 'meses')}"
    return f"há {_plural(anos, 'ano', 'anos')}" + (f" e {_plural(resto, 'mês', 'meses')}" if resto else "")


def _arred(v, casas: int = 2) -> float | None:
    """Número para o retrato (JSON): arredondado; None, NaN e infinito viram None."""
    if v is None:
        return None
    v = float(v)
    return round(v, casas) if math.isfinite(v) else None


def _iso(d: dt.date | None) -> str | None:
    return d.isoformat() if d else None


def _ultimos_meses(hoje: dt.date, n: int = 12) -> list[dt.date]:
    """Os n meses completos antes do mês de hoje (dia 1º), do mais antigo para o mais recente."""
    atual = hoje.year * 12 + hoje.month - 1
    return [dt.date(m // 12, m % 12 + 1, 1) for m in range(atual - n, atual)]


def dias_prazo(nome: str | None) -> list[int] | None:
    """Os dias de um prazo do ERP (o nome da opção de pagamento): "14, 21 E 28 DIAS" -> [14, 21, 28], "01 DIA" -> [1],
    "A VISTA" -> [0]. Sem prazo ou sem número -> None."""
    if not nome:
        return None
    dias = [int(n) for n in re.findall(r"\d+", nome)]
    if dias:
        return dias
    return [0] if "VISTA" in nome.upper() else None


def perfil_do_retrato(r: dict) -> dict:
    """Os números com que as reanálises parecidas são comparadas (bi/reanalise.py), tirados de um retrato gravado; os
    de hoje saem de Credito.perfil, com as mesmas chaves."""
    doze, parecer = r.get("ultimos_12_meses") or {}, (r.get("parecer") or {}).get("pedido") or {}
    return {"pontualidade_12m": doze.get("pontualidade"), "compras_mes_12m": doze.get("compras_mes"),
            "maior_saldo_12m": doze.get("maior_saldo"), "meses_cliente": (r.get("historico") or {}).get("meses_cliente"),
            "inadimplencia": (r.get("aberto_hoje") or {}).get("inadimplencia"),
            "pedido_vezes_maior_saldo": parecer.get("vezes_maior_saldo")}


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
            "regra_parecer": REGRA,
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
        abertos = {i: (qtd, total, pg) for i, qtd, total, pg in self.cache.consulta(
            f"SELECT t.id_cliente, COUNT(*), SUM(t.total), SUM({pago}) FROM titulos_receber t{junta} "
            f"WHERE t.id_cliente IN ({_marcas(clientes)}) AND t.quitacao IS NULL GROUP BY 1", clientes)}
        saida = []
        for c in clientes:
            nome, carteira, limite, prazo = cadastro[c]
            qtd, total, pg = abertos.get(c, (0, 0.0, 0.0))
            limite = float(limite or 0)
            saida.append({
                "id": c, "nome": nome, "carteira": nomes.get(carteira) if carteira else None, "prazo": prazo,
                "limite": limite, "qtd_abertos": qtd, "titulos_abertos": total, "pago_parcelas": pg,
                "em_aberto": total - pg, "restante": limite - (total - pg),
                "usado": (total - pg) / limite if limite > 0 else None,
            })
        return saida

    @staticmethod
    def _soma(clientes: list[dict]) -> dict:
        soma = {k: sum(c[k] for c in clientes) for k in ("limite", "qtd_abertos", "titulos_abertos", "pago_parcelas",
                                                          "em_aberto", "restante")}
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

    # --- prazos do ERP ----------------------------------------------------------------------
    def prazos(self) -> list[str]:
        """Os prazos (nomes das opções de pagamento do ERP) que algum cliente tem no cadastro, na ordem dos dias: A VISTA,
        01 DIA, 02 DIAS…; os parcelados pelo primeiro dia e depois pelos outros. Uma opção que nenhum cliente usa não
        chega ao cache."""
        self._conferir()
        nomes = [r[0] for r in self.cache.consulta(
            "SELECT DISTINCT prazo FROM clientes_credito WHERE prazo IS NOT NULL AND trim(prazo) <> ''")]
        return sorted(nomes, key=lambda n: (dias_prazo(n) or [math.inf], n))

    def cadastro(self, cliente: int) -> dict:
        """O nome e o limite e o prazo de hoje no cadastro do cliente (o ERP). Cliente que não existe -> ValueError."""
        self._conferir()
        linhas = self.cache.consulta("SELECT c.nome, k.limite, k.prazo FROM clientes c LEFT JOIN clientes_credito k "
                                     "ON k.id = c.id WHERE c.id = ?", [cliente])
        if not linhas:
            raise ValueError(f"cliente não encontrado: {cliente}")
        nome, limite, prazo = linhas[0]
        return {"id": cliente, "nome": nome, "limite": float(limite or 0), "prazo": prazo}

    # --- parecer de um limite novo ---------------------------------------------------------
    def _historico(self, cliente: int) -> dict:
        """O que a regra do parecer olha no cliente: o cadastro e o que ele tem em aberto hoje (_clientes) e os títulos
        da janela de JANELA dias que termina hoje, de qualquer vendedor. Cliente que não existe -> ValueError."""
        hoje = self.hoje()
        inicio = hoje - dt.timedelta(days=JANELA)  # a janela começa no dia seguinte
        inadimplente = hoje - dt.timedelta(days=TOLERANCIA)
        junta, pago, _, _ = self._parcelas()
        c = self._clientes([cliente], self.nomes_vendedores(), junta, pago)[0]

        # Datas de emissão digitadas no futuro (ano 7190) ficam fora do histórico; a inadimplência é de todo título
        # em aberto, como no cartão.
        na_janela = "emissao > ? AND emissao <= ?"
        (primeiro, ultimo, inad_qtd, inad_valor, venc_qtd, venc_valor, quitados, pontuais, atraso_medio, compras,
         prazo_real) = self.cache.consulta(
            "SELECT MIN(emissao) FILTER (WHERE emissao <= ?), MAX(emissao) FILTER (WHERE emissao <= ?), "
            "COUNT(*) FILTER (WHERE quitado = 0 AND vencimento < ?), "
            "COALESCE(SUM(total) FILTER (WHERE quitado = 0 AND vencimento < ?), 0), "
            "COUNT(*) FILTER (WHERE quitado = 0 AND vencimento < ? AND vencimento >= ?), "
            "COALESCE(SUM(total) FILTER (WHERE quitado = 0 AND vencimento < ? AND vencimento >= ?), 0), "
            f"COUNT(*) FILTER (WHERE quitado = 1 AND {na_janela}), "
            f"COUNT(*) FILTER (WHERE quitado = 1 AND {na_janela} AND quitacao <= vencimento + {TOLERANCIA}), "
            "AVG(datediff('day', vencimento, quitacao)) "
            f"  FILTER (WHERE quitado = 1 AND {na_janela} AND quitacao > vencimento + {TOLERANCIA}), "
            f"COALESCE(SUM(total) FILTER (WHERE {na_janela}), 0), "
            f"MEDIAN(datediff('day', emissao, vencimento)) FILTER (WHERE {na_janela}) "
            "FROM titulos_receber WHERE id_cliente = ?",
            [hoje, hoje, inadimplente, inadimplente, hoje, inadimplente, hoje, inadimplente,
             *[inicio, hoje] * 5, c["id"]])[0]
        pico_em, pico = self._pico(c["id"], inicio, hoje)
        return {"hoje": hoje, "inicio": inicio, "cliente": c, "primeiro": primeiro, "ultimo": ultimo,
                "meses_cliente": _meses(primeiro, hoje) if primeiro else None,
                "inad_qtd": inad_qtd, "inad_valor": inad_valor, "venc_qtd": venc_qtd, "venc_valor": venc_valor,
                "quitados": quitados, "pontuais": pontuais, "pontualidade": pontuais / quitados if quitados else None,
                "atraso_medio": atraso_medio, "compras": compras, "prazo_real": prazo_real,
                "pico": pico, "pico_em": pico_em}

    def _pico(self, cliente: int, inicio: dt.date, hoje: dt.date) -> tuple[dt.date | None, float]:
        """O maior saldo em aberto do cliente depois de inicio até hoje, e o dia (no empate, o mais recente). O saldo só
        sobe nos dias de emissão, então basta olhar esses dias e o dia seguinte a inicio (o que já vinha de antes).
        Pelo valor do título: o cache não tem a data das parcelas."""
        linhas = self.cache.consulta(
            "WITH t AS (SELECT emissao, quitacao, total FROM titulos_receber WHERE id_cliente = ? AND emissao <= ?), "
            "d AS (SELECT CAST(? AS DATE) AS dia UNION SELECT DISTINCT emissao FROM t WHERE emissao > ?) "
            "SELECT d.dia, SUM(t.total) AS saldo FROM d JOIN t ON t.emissao <= d.dia "
            "  AND (t.quitacao IS NULL OR t.quitacao > d.dia) "
            "GROUP BY d.dia ORDER BY saldo DESC, d.dia DESC LIMIT 1",
            [cliente, hoje, inicio + dt.timedelta(days=1), inicio])
        return linhas[0] if linhas else (None, 0.0)

    @staticmethod
    def _parecer(h: dict, pedido: float) -> dict:
        """A regra do topo do módulo sobre os números de _historico e o limite total pedido: os critérios (cada um "ok",
        "atencao" ou "bloqueio"; qualquer bloqueio dá "nao_indicado", qualquer atenção, "ressalvas"), o limite sugerido
        e o pedido ÷ o maior saldo. Não lê o cache."""
        hoje, c, pico = h["hoje"], h["cliente"], h["pico"]
        criterios = []

        def criterio(chave: str, status: str, detalhe: str) -> None:
            criterios.append({"chave": chave, "status": status, "titulo": CRITERIOS[chave], "detalhe": detalhe})

        if h["inad_qtd"]:
            criterio("inadimplencia", "bloqueio",
                     f"{_plural(h['inad_qtd'], 'título em aberto vencido', 'títulos em aberto vencidos')} há mais de "
                     f"{TOLERANCIA} dias: {_reais(h['inad_valor'])}.")
        elif h["venc_qtd"]:
            criterio("inadimplencia", "atencao",
                     f"{_plural(h['venc_qtd'], 'título vencido', 'títulos vencidos')} há até {TOLERANCIA} dias "
                     f"({_reais(h['venc_valor'])}): ainda dentro da tolerância.")
        else:
            criterio("inadimplencia", "ok", "Nenhum título vencido em aberto.")

        quitados, pontualidade = h["quitados"], h["pontualidade"]
        if quitados < MIN_QUITADOS:
            criterio("pontualidade", "atencao",
                     "Nenhum título quitado: não dá para medir." if not quitados else
                     f"Só {_plural(quitados, 'título quitado', 'títulos quitados')}: pouco para medir.")
        else:
            atraso = (f"; os atrasados foram pagos, em média, {h['atraso_medio']:.0f} dias depois do vencimento"
                      if h["atraso_medio"] is not None else "")
            texto = (f"{_pct(pontualidade)} dos títulos pagos até {TOLERANCIA} dias depois do vencimento "
                     f"({h['pontuais']} de {quitados}){atraso}.")
            if pontualidade < PONTUAL_MIN:
                criterio("pontualidade", "bloqueio", texto)
            elif pontualidade < PONTUAL_OK:
                criterio("pontualidade", "atencao", texto)
            else:
                criterio("pontualidade", "ok", texto)

        primeiro, meses = h["primeiro"], h["meses_cliente"]
        if primeiro is None:
            criterio("tempo", "atencao", "Nenhum título a receber: cliente sem compras a prazo.")
        elif meses < MESES_CLIENTE:
            criterio("tempo", "atencao", f"Primeiro título em {primeiro:%d/%m/%Y}, {_ha(meses)}: cliente novo.")
        else:
            criterio("tempo", "ok", f"Primeiro título em {primeiro:%d/%m/%Y}, {_ha(meses)}.")

        # O que o histórico sustenta: FOLGA_OK x o maior saldo, arredondado para cima. É também o limite sugerido,
        # que assim sempre passa neste critério.
        teto = math.ceil(round(FOLGA_OK * pico / ARREDONDAR, 6)) * ARREDONDAR if pico > 0 else 0
        vezes = pedido / pico if pico > 0 else None
        if pedido <= c["limite"]:
            criterio("folga", "ok", f"Não é aumento: o limite de hoje é {_reais(c['limite'])}.")
        elif vezes is None:
            criterio("folga", "bloqueio", "O cliente não teve nada em aberto nos últimos 12 meses.")
        else:
            texto = (f"O limite pedido é {f'{vezes:.1f}'.replace('.', ',')} vezes o maior saldo em aberto dos últimos "
                     f"12 meses ({_reais(pico)} em {h['pico_em']:%d/%m/%Y}); o histórico sustenta até {_reais(teto)}.")
            if pedido <= teto:
                criterio("folga", "ok", texto)
            elif vezes > FOLGA_MAX:
                criterio("folga", "bloqueio", texto)
            else:
                criterio("folga", "atencao", texto)

        if c["em_aberto"] > pedido:
            criterio("em_aberto", "atencao", f"{_reais(c['em_aberto'])}, mais que o limite pedido: o limite novo já "
                     "começaria estourado.")
        else:
            criterio("em_aberto", "ok", f"{_reais(c['em_aberto'])}, {_pct(c['em_aberto'] / pedido)} do limite pedido.")

        ultimo = h["ultimo"]
        if ultimo is None:
            criterio("recente", "atencao", "Nenhum título a receber de venda.")
        elif (hoje - ultimo).days > DIAS_SEM_COMPRA:
            criterio("recente", "atencao", f"Última compra em {ultimo:%d/%m/%Y}, há {(hoje - ultimo).days} dias: o "
                     "histórico pode não mostrar a situação de hoje.")
        else:
            criterio("recente", "ok", f"Última compra em {ultimo:%d/%m/%Y}.")

        status = {x["status"] for x in criterios}
        bloqueios = {x["chave"] for x in criterios if x["status"] == "bloqueio"}
        # Sugere o que o histórico sustenta, menos quando o problema é como o cliente paga.
        sugerido = teto if teto and not bloqueios & {"inadimplencia", "pontualidade"} else None
        return {"parecer": "nao_indicado" if "bloqueio" in status else "ressalvas" if "atencao" in status else "indicado",
                "criterios": criterios, "limite_sugerido": sugerido, "vezes": vezes}

    def analisar(self, cliente: int | str, limite_pedido: float | str) -> dict:
        """Parecer sobre o limite total novo de um cliente, pela regra do topo do módulo. Cada critério sai "ok",
        "atencao" ou "bloqueio": qualquer bloqueio dá "nao_indicado"; qualquer atenção, "ressalvas". Vale o histórico
        inteiro do cliente (de qualquer vendedor, sem mês nem ano); a janela de JANELA dias termina hoje (a extração).
        Cliente ou limite pedido que não são números (vêm do endereço), limite sem valor positivo ou cliente que não
        existe -> ValueError."""
        self._conferir()
        try:
            cliente = int(cliente)
        except (TypeError, ValueError):
            raise ValueError("escolha um cliente para analisar") from None
        try:
            pedido = float(limite_pedido)
        except (TypeError, ValueError):
            raise ValueError("informe o limite pedido, maior que zero") from None
        if not math.isfinite(pedido) or pedido <= 0:
            raise ValueError("informe o limite pedido, maior que zero")
        h = self._historico(cliente)
        p = self._parecer(h, pedido)
        c = h["cliente"]
        avisos = []
        if self.cache.sem_parcelas:
            avisos.append("As parcelas dos títulos ainda não chegaram do computador da empresa: o que está em aberto "
                          "ainda não desconta as parcelas pagas.")
        return {
            "hoje": h["hoje"],
            "cliente": {"id": c["id"], "nome": c["nome"], "carteira": c["carteira"], "prazo": c["prazo"]},
            "pedido": pedido,
            "parecer": p["parecer"],
            "criterios": p["criterios"],
            "limite_sugerido": p["limite_sugerido"],
            "numeros": {
                "limite_atual": c["limite"], "em_aberto": c["em_aberto"], "qtd_abertos": c["qtd_abertos"],
                "maior_saldo": h["pico"], "maior_saldo_em": h["pico_em"], "pedido_vezes_maior_saldo": p["vezes"],
                "inadimplencia": h["inad_valor"], "titulos_inadimplentes": h["inad_qtd"],
                "pontualidade": h["pontualidade"], "quitados": h["quitados"], "quitados_pontuais": h["pontuais"],
                "atraso_medio": h["atraso_medio"], "compras_mes": h["compras"] / 12, "prazo_real": h["prazo_real"],
                "primeiro_titulo": h["primeiro"], "ultimo_titulo": h["ultimo"], "meses_cliente": h["meses_cliente"],
            },
            "regra": REGRA,
            "avisos": avisos,
        }

    # --- reanálises (bi/reanalise.py) ----------------------------------------------------------
    def retrato(self, cliente: int, pedido: float, liberado: float) -> dict:
        """O que se sabia do cliente agora, para gravar com uma reanálise: o cadastro, os cartões da página (todos os
        títulos), o que está em aberto, os 12 meses da regra e os últimos JANELA_CURTA dias, o mês a mês (os 12 meses
        completos antes do mês de hoje), as vendas e devoluções de 12 meses e o parecer do pedido e do liberado (sem o
        do liberado quando ele é 0). Tudo do cache, calculado aqui. Datas em texto (AAAA-MM-DD) e valores
        arredondados, no formato RETRATO_VERSAO. Cliente que não existe -> ValueError."""
        self._conferir()
        h = self._historico(int(cliente))
        c, hoje, inicio = h["cliente"], h["hoje"], h["inicio"]
        k = self.calcular([c["id"]])["cartoes"]
        curto = hoje - dt.timedelta(days=JANELA_CURTA)
        na_janela = "emissao > ? AND emissao <= ?"
        quitado = f"quitado = 1 AND {na_janela}"
        (titulos, maior_atraso, graves, ponderado, meses_compra, quitados_curto, pontuais_curto, compras_curto,
         a_vencer, maior_atraso_aberto) = self.cache.consulta(
            f"SELECT COUNT(*) FILTER (WHERE {na_janela}), "
            f"MAX(datediff('day', vencimento, quitacao)) FILTER (WHERE {quitado}), "
            f"COUNT(*) FILTER (WHERE {quitado} AND quitacao > vencimento + {ATRASO_GRAVE}), "
            f"SUM(total * datediff('day', vencimento, quitacao)) FILTER (WHERE {quitado}) "
            f"  / NULLIF(SUM(total) FILTER (WHERE {quitado}), 0), "
            f"COUNT(DISTINCT strftime(emissao, '%Y-%m')) FILTER (WHERE {na_janela}), "
            f"COUNT(*) FILTER (WHERE {quitado}), "
            f"COUNT(*) FILTER (WHERE {quitado} AND quitacao <= vencimento + {TOLERANCIA}), "
            f"COALESCE(SUM(total) FILTER (WHERE {na_janela}), 0), "
            "COALESCE(SUM(total) FILTER (WHERE quitado = 0 AND vencimento >= ?), 0), "
            "MAX(datediff('day', vencimento, ?)) FILTER (WHERE quitado = 0 AND vencimento < ?) "
            "FROM titulos_receber WHERE id_cliente = ?",
            [*[inicio, hoje] * 6, *[curto, hoje] * 3, hoje, hoje, hoje, c["id"]])[0]
        meses = _ultimos_meses(hoje)
        por_mes = {m: r for m, *r in self.cache.consulta(
            "SELECT strftime(emissao, '%Y-%m'), SUM(total), COUNT(*), COUNT(*) FILTER (WHERE quitado = 1), "
            f"COUNT(*) FILTER (WHERE quitado = 1 AND quitacao > vencimento + {TOLERANCIA}) "
            "FROM titulos_receber WHERE id_cliente = ? AND emissao >= ? AND emissao < ? GROUP BY 1",
            [c["id"], meses[0], hoje.replace(day=1)])}
        mes_a_mes = []
        for m in meses:
            valor, n, quitados, atrasados = por_mes.get(f"{m:%Y-%m}", (0.0, 0, 0, 0))
            mes_a_mes.append({"mes": f"{m:%Y-%m}", "compras_valor": _arred(valor), "titulos": n, "quitados": quitados,
                              "quitados_com_atraso": atrasados})

        # O cadastro: a rede e o detalhe podem faltar num cache de versão anterior.
        cidade = uf = area = segmento = inativo = cadastro = rede = None
        if not self.cache.sem_detalhe:
            linhas = self.cache.consulta("SELECT cidade, uf, area, segmento, inativo, data_cadastro FROM clientes_detalhes "
                                         "WHERE id = ?", [c["id"]])
            if linhas:
                cidade, uf, area, segmento, inativo, cadastro = linhas[0]
        if not self.cache.sem_rede:
            linhas = self.cache.consulta("SELECT rede FROM clientes_rede WHERE id = ?", [c["id"]])
            rede = linhas[0][0] if linhas else None
        carteira = self.cache.consulta("SELECT id_vendedor FROM clientes WHERE id = ?", [c["id"]])[0][0]
        # Vendas a prazo e à vista; só as do cadastro de clientes (o código de um funcionário pode ser o de um cliente).
        venda, dias_venda, produtos = self.cache.consulta(
            "SELECT COALESCE(SUM(valor), 0), COUNT(DISTINCT data), COUNT(DISTINCT id_produto) FROM vendas_clientes_itens "
            "WHERE id_cliente = ? AND tipocliente = 'CLIENTE' AND data > ? AND data <= ?", [c["id"], inicio, hoje])[0]
        devolvido = self.cache.consulta(
            "SELECT COALESCE(SUM(valor), 0) FROM devolucoes_clientes_itens WHERE id_cliente = ? AND tipocliente = 'CLIENTE' "
            "AND NOT COALESCE(cancelada, FALSE) AND data > ? AND data <= ?", [c["id"], inicio, hoje])[0][0]

        pp = self._parecer(h, pedido)
        pl = self._parecer(h, liberado) if liberado > 0 else None
        return {
            "versao": RETRATO_VERSAO,
            "cliente": {"id": c["id"], "nome": c["nome"]},
            "dados_ate": self.cache.info.get("extraido_em"),
            "hoje": _iso(hoje),
            "sem_parcelas": bool(self.cache.sem_parcelas),
            "cadastro": {
                "limite": _arred(c["limite"]), "prazo": c["prazo"], "prazo_dias": dias_prazo(c["prazo"]),
                "id_vendedor_carteira": carteira or None, "carteira": c["carteira"], "cidade": cidade, "uf": uf,
                "area": area, "segmento": segmento, "rede": rede, "inativo": None if inativo is None else bool(inativo),
                "data_cadastro": _iso(cadastro), "meses_cadastro": _meses(cadastro, hoje) if cadastro else None,
            },
            "historico": {  # os cartões da página, com todos os títulos do cliente
                "compras_valor": _arred(k["valor"]), "compras_qtd": k["quantidade"], "ticket_medio": _arred(k["ticket"]),
                "quitados": k["quitados"], "quitados_com_atraso": k["quitados_atrasados"],
                "pontualidade": _arred(k["pontualidade"], 4), "inadimplencia": _arred(k["inadimplencia"]),
                "primeiro_titulo": _iso(h["primeiro"]), "ultimo_titulo": _iso(h["ultimo"]),
                "meses_cliente": h["meses_cliente"], "dias_sem_compra": (hoje - h["ultimo"]).days if h["ultimo"] else None,
            },
            "aberto_hoje": {
                "titulos": c["qtd_abertos"], "valor_dos_titulos": _arred(c["titulos_abertos"]),
                "pago_em_parcelas": _arred(c["pago_parcelas"]), "em_aberto": _arred(c["em_aberto"]),
                "limite_restante": _arred(c["restante"]), "uso_do_limite": _arred(c["usado"], 4),
                "a_vencer": _arred(a_vencer), "vencidos_ate_7_dias": h["venc_qtd"],
                "vencidos_ate_7_dias_valor": _arred(h["venc_valor"]), "inadimplentes": h["inad_qtd"],
                "inadimplencia": _arred(h["inad_valor"]), "maior_atraso_dias": maior_atraso_aberto,
            },
            "ultimos_12_meses": {
                "titulos": titulos, "compras_valor": _arred(h["compras"]), "compras_mes": _arred(h["compras"] / 12),
                "ticket_medio": _arred(h["compras"] / titulos) if titulos else None, "meses_com_compra": meses_compra,
                "quitados": h["quitados"], "quitados_pontuais": h["pontuais"],
                "pontualidade": _arred(h["pontualidade"], 4), "atraso_medio_dos_atrasados": _arred(h["atraso_medio"], 1),
                "atraso_ponderado_dias": _arred(ponderado, 1), "maior_atraso_dias": maior_atraso,
                "atraso_grave_dias": ATRASO_GRAVE, "quitados_com_atraso_grave": graves,
                "prazo_real_dias": _arred(h["prazo_real"], 1), "maior_saldo": _arred(h["pico"]),
                "maior_saldo_em": _iso(h["pico_em"]),
            },
            "ultimos_3_meses": {
                "dias": JANELA_CURTA, "compras_valor": _arred(compras_curto), "quitados": quitados_curto,
                "quitados_pontuais": pontuais_curto,
                "pontualidade": _arred(pontuais_curto / quitados_curto, 4) if quitados_curto else None,
            },
            "mes_a_mes": mes_a_mes,
            "vendas_12_meses": {
                "venda_bruta": _arred(venda), "devolucoes": _arred(devolvido),
                "taxa_devolucao": _arred(devolvido / venda, 4) if venda else None, "dias_com_venda": dias_venda,
                "produtos": produtos,
            },
            "parecer": {"regra": dict(REGRA), "pedido": _resumo_parecer(pp, pedido),
                        "liberado": _resumo_parecer(pl, liberado) if pl else None},
        }

    def perfil(self, cliente: int, novo_limite: float | None = None) -> dict:
        """Os números de hoje do cliente, com as chaves de perfil_do_retrato, para achar as reanálises parecidas.
        novo_limite: o limite pedido agora (entra como pedido ÷ maior saldo)."""
        self._conferir()
        h = self._historico(int(cliente))
        c = h["cliente"]
        return {"cliente": {"id": c["id"], "nome": c["nome"]}, "pontualidade_12m": h["pontualidade"],
                "compras_mes_12m": h["compras"] / 12, "maior_saldo_12m": h["pico"], "meses_cliente": h["meses_cliente"],
                "inadimplencia": h["inad_valor"],
                "pedido_vezes_maior_saldo": novo_limite / h["pico"] if novo_limite and h["pico"] > 0 else None}

    def depois(self, itens: list[tuple[int, dt.date, float]]) -> list[dict]:
        """O que aconteceu com o cliente depois de cada reanálise (cliente, dia do registro, limite liberado), pelos
        títulos de hoje: os emitidos depois do dia (quantos e quanto) e, dos que venceram há mais de TOLERANCIA dias,
        quantos foram pagos em dia (quem não pagou continua na conta); a inadimplência de hoje (todos os títulos); o
        maior saldo em aberto depois do dia contra o liberado; e o limite e o prazo do cadastro de hoje."""
        self._conferir()
        hoje = self.hoje()
        vencido = hoje - dt.timedelta(days=TOLERANCIA)
        ids = sorted({i for i, _, _ in itens})
        cadastro = {i: (limite, prazo) for i, limite, prazo in self.cache.consulta(
            f"SELECT id, limite, prazo FROM clientes_credito WHERE id IN ({_marcas(ids)})", ids)} if ids else {}
        depois_de = "emissao > ? AND emissao <= ?"
        saida = []
        for cliente, dia, liberado in itens:
            n, valor, vencidos, em_dia, inad_qtd, inad_valor = self.cache.consulta(
                f"SELECT COUNT(*) FILTER (WHERE {depois_de}), COALESCE(SUM(total) FILTER (WHERE {depois_de}), 0), "
                f"COUNT(*) FILTER (WHERE {depois_de} AND vencimento < ?), "
                f"COUNT(*) FILTER (WHERE {depois_de} AND vencimento < ? AND quitado = 1 "
                f"  AND quitacao <= vencimento + {TOLERANCIA}), "
                "COUNT(*) FILTER (WHERE quitado = 0 AND vencimento < ?), "
                "COALESCE(SUM(total) FILTER (WHERE quitado = 0 AND vencimento < ?), 0) "
                "FROM titulos_receber WHERE id_cliente = ?",
                [dia, hoje, dia, hoje, dia, hoje, vencido, dia, hoje, vencido, vencido, vencido, cliente])[0]
            pico_em, pico = self._pico(cliente, dia, hoje) if dia < hoje else (None, 0.0)
            limite, prazo = cadastro.get(cliente, (None, None))
            saida.append({
                "dias_desde": max(0, (hoje - dia).days), "titulos_emitidos": n, "valor_emitido": _arred(valor),
                "vencidos_ha_mais_de_7_dias": vencidos, "pagos_em_dia": em_dia,
                "pontualidade": _arred(em_dia / vencidos, 4) if vencidos else None,
                "titulos_inadimplentes_hoje": inad_qtd, "inadimplencia_hoje": _arred(inad_valor),
                "maior_saldo": _arred(pico), "maior_saldo_em": _iso(pico_em),
                "uso_maximo_do_liberado": _arred(pico / liberado, 4) if liberado > 0 and pico_em else None,
                "limite_no_cadastro_hoje": _arred(limite), "prazo_no_cadastro_hoje": prazo,
            })
        return saida


def _resumo_parecer(p: dict, valor: float) -> dict:
    """O parecer de um valor, para o retrato: o resultado, o sugerido, o valor ÷ o maior saldo e os critérios."""
    return {"valor": _arred(valor), "parecer": p["parecer"], "limite_sugerido": _arred(p["limite_sugerido"]),
            "vezes_maior_saldo": _arred(p["vezes"], 3),
            "criterios": [{"chave": x["chave"], "status": x["status"], "detalhe": x["detalhe"]} for x in p["criterios"]]}

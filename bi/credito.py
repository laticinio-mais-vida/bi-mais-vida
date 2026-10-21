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

"Hoje" é o dia da extração, para os dias de atraso baterem com a foto dos dados.
"""
from __future__ import annotations

import datetime as dt
import math

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

    # --- parecer de um limite novo ---------------------------------------------------------
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
        hoje = self.hoje()
        inicio = hoje - dt.timedelta(days=JANELA)  # a janela começa no dia seguinte
        inadimplente = hoje - dt.timedelta(days=TOLERANCIA)
        nomes = self.nomes_vendedores()
        junta, pago, _, _ = self._parcelas()
        c = self._clientes([cliente], nomes, junta, pago)[0]

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

        # O maior saldo em aberto da janela: o saldo só sobe nos dias de emissão, então basta olhar esses dias e o
        # primeiro dia da janela (o que já vinha de antes). Pelo valor do título: o cache não tem a data das parcelas.
        pico = self.cache.consulta(
            "WITH t AS (SELECT emissao, quitacao, total FROM titulos_receber WHERE id_cliente = ? AND emissao <= ?), "
            "d AS (SELECT CAST(? AS DATE) AS dia UNION SELECT DISTINCT emissao FROM t WHERE emissao > ?) "
            "SELECT d.dia, SUM(t.total) AS saldo FROM d JOIN t ON t.emissao <= d.dia "
            "  AND (t.quitacao IS NULL OR t.quitacao > d.dia) "
            "GROUP BY d.dia ORDER BY saldo DESC, d.dia DESC LIMIT 1",
            [c["id"], hoje, inicio + dt.timedelta(days=1), inicio])
        pico_em, pico = pico[0] if pico else (None, 0.0)

        criterios = []

        def criterio(chave: str, status: str, detalhe: str) -> None:
            criterios.append({"chave": chave, "status": status, "titulo": CRITERIOS[chave], "detalhe": detalhe})

        if inad_qtd:
            criterio("inadimplencia", "bloqueio",
                     f"{_plural(inad_qtd, 'título em aberto vencido', 'títulos em aberto vencidos')} há mais de "
                     f"{TOLERANCIA} dias: {_reais(inad_valor)}.")
        elif venc_qtd:
            criterio("inadimplencia", "atencao",
                     f"{_plural(venc_qtd, 'título vencido', 'títulos vencidos')} há até {TOLERANCIA} dias "
                     f"({_reais(venc_valor)}): ainda dentro da tolerância.")
        else:
            criterio("inadimplencia", "ok", "Nenhum título vencido em aberto.")

        pontualidade = pontuais / quitados if quitados else None
        if quitados < MIN_QUITADOS:
            criterio("pontualidade", "atencao",
                     "Nenhum título quitado: não dá para medir." if not quitados else
                     f"Só {_plural(quitados, 'título quitado', 'títulos quitados')}: pouco para medir.")
        else:
            atraso = (f"; os atrasados foram pagos, em média, {atraso_medio:.0f} dias depois do vencimento"
                      if atraso_medio is not None else "")
            texto = (f"{_pct(pontualidade)} dos títulos pagos até {TOLERANCIA} dias depois do vencimento "
                     f"({pontuais} de {quitados}){atraso}.")
            if pontualidade < PONTUAL_MIN:
                criterio("pontualidade", "bloqueio", texto)
            elif pontualidade < PONTUAL_OK:
                criterio("pontualidade", "atencao", texto)
            else:
                criterio("pontualidade", "ok", texto)

        meses = _meses(primeiro, hoje) if primeiro else None
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
                     f"12 meses ({_reais(pico)} em {pico_em:%d/%m/%Y}); o histórico sustenta até {_reais(teto)}.")
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
        avisos = []
        if self.cache.sem_parcelas:
            avisos.append("As parcelas dos títulos ainda não chegaram do computador da empresa: o que está em aberto "
                          "ainda não desconta as parcelas pagas.")
        return {
            "hoje": hoje,
            "cliente": {"id": c["id"], "nome": c["nome"], "carteira": c["carteira"], "prazo": c["prazo"]},
            "pedido": pedido,
            "parecer": "nao_indicado" if "bloqueio" in status else "ressalvas" if "atencao" in status else "indicado",
            "criterios": criterios,
            "limite_sugerido": sugerido,
            "numeros": {
                "limite_atual": c["limite"], "em_aberto": c["em_aberto"], "qtd_abertos": c["qtd_abertos"],
                "maior_saldo": pico, "maior_saldo_em": pico_em, "pedido_vezes_maior_saldo": vezes,
                "inadimplencia": inad_valor, "titulos_inadimplentes": inad_qtd,
                "pontualidade": pontualidade, "quitados": quitados, "quitados_pontuais": pontuais,
                "atraso_medio": atraso_medio, "compras_mes": compras / 12, "prazo_real": prazo_real,
                "primeiro_titulo": primeiro, "ultimo_titulo": ultimo, "meses_cliente": meses,
            },
            "regra": REGRA,
            "avisos": avisos,
        }

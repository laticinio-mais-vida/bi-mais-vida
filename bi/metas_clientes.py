"""As listas de clientes dos cards das abas Metas ES, Metas BA e Metas Edir: o que dá para fazer para melhorar os números.

- Clientes não atendidos (card "Clientes atendidos"): os clientes da carteira de hoje de cada vendedor da aba (ativos,
  sem "PEDIDO BLOQUEADO" no nome, como no painel de desempenho) com quem o próprio vendedor não teve nota no mês. É a
  regra do card, que conta o cliente para o vendedor que fez a venda: quem comprou com outro vendedor aparece, marcado
  com o nome dele. Com vários meses, entra quem passou pelo menos um deles sem comprar com o vendedor (o card soma mês a
  mês).
- Clientes que não compraram produtos indicados (card "Composição do faturamento"): os clientes da carteira com quem o
  vendedor teve nota no período, com o que levaram (notas de qualquer vendedor) comparado ao mix ideal do segmento
  (CRM › Configurar › Mix ideal, a mesma regra do CRM: um item vale com qualquer um dos seus produtos, "qualquer
  mussarela" com qualquer produto da linha mussarela, e a equivalência de produtos das Metas vale). Só entra quem
  deixou de levar algum item. Devolução não tira o item.

Os vendedores são os que a página mostra com os mesmos filtros (Calculadora.vendedores_da_visao): os da aba com meta
nos meses, do acesso da pessoa e do filtro.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .crm import LINHA_MUSSARELA, normalizar
from .manejo import nome_erp
from .metas import MESES, filtro_meses

MESES_DA_MEDIA = 6  # a compra média por mês da lista de não atendidos: os meses fechados antes do período
BLOQUEADO = "PEDIDO BLOQUEADO"


def _menos_meses(mes: dt.date, n: int) -> dt.date:
    k = mes.year * 12 + mes.month - 1 - n
    return dt.date(k // 12, k % 12 + 1, 1)


def rotulo_mes(mes: dt.date) -> str:
    """'out/26'."""
    return f"{MESES[mes.month - 1][:3]}/{mes.year % 100:02d}"


def nome_item(item: dict, nomes: dict[int, str]) -> str:
    """O nome de um item do mix ideal, como no CRM: 'MANTEIGA 200G ou MANTEIGA 500G' ou 'Qualquer mussarela'."""
    if item.get("mussarela"):
        return "Qualquer mussarela"
    conhecidos = [nomes[int(p)] for p in item["produtos"] if nomes.get(int(p))]
    return " ou ".join(conhecidos) or "Produto sem cadastro"


class ClientesDaMeta:
    def __init__(self, calc, config_crm, nomes_vendedores):
        self.calc = calc
        self.config_crm = config_crm              # o mix ideal de cada segmento (CRM › Configurar)
        self.nomes_vendedores = nomes_vendedores  # () -> {vendedor: nome}: o nome de quem vendeu fora da carteira

    # ---------- apoio ----------
    def _carteira(self, vendedores: list[int]) -> list[dict]:
        """Os clientes visitáveis da carteira de hoje destes vendedores (ativos, sem "PEDIDO BLOQUEADO" no nome)."""
        if not vendedores:
            return []
        cache = self.calc.cache
        if cache.sem_detalhe:  # sem o cadastro detalhado: sem área, cidade, segmento e sem saber quem está inativo
            sql = ("SELECT c.id, c.nome, c.id_vendedor, NULL, NULL, NULL, NULL FROM clientes c "
                   "WHERE c.id_vendedor IN (SELECT unnest(?::INTEGER[])) "
                   f"AND NOT contains(upper(COALESCE(c.nome, '')), '{BLOQUEADO}')")
        else:
            sql = ("SELECT c.id, c.nome, c.id_vendedor, d.area, d.cidade, d.uf, d.segmento FROM clientes c "
                   "LEFT JOIN clientes_detalhes d ON d.id = c.id "
                   "WHERE c.id_vendedor IN (SELECT unnest(?::INTEGER[])) AND COALESCE(d.inativo, 0) = 0 "
                   f"AND NOT contains(upper(COALESCE(c.nome, '')), '{BLOQUEADO}')")
        return [{"id": int(i), "nome": nome_erp(n), "vendedor": int(v), "area": a, "cidade": cid, "uf": uf,
                 "segmento": (s or "").strip() or None}
                for i, n, v, a, cid, uf, s in cache.consulta(sql, [vendedores])]

    def _compras(self, ids: list[int], meses: list[dt.date]) -> dict[int, dict[dt.date, set[int]]]:
        """{cliente: {mês: vendedores com nota para ele no mês}} (notas não canceladas, como no card)."""
        saida: dict[int, dict[dt.date, set[int]]] = defaultdict(lambda: defaultdict(set))
        if not ids:
            return saida
        periodo, params = filtro_meses(meses)
        for cli, mes, v in self.calc.cache.consulta(
                f"SELECT id_cliente, CAST(date_trunc('month', data) AS DATE), COALESCE(id_vendedor, 0) "
                f"FROM vendas_clientes WHERE tipocliente = 'CLIENTE' AND {periodo} "
                f"AND id_cliente IN (SELECT unnest(?::INTEGER[])) GROUP BY 1, 2, 3", [*params, ids]):
            saida[int(cli)][mes].add(int(v))
        return saida

    def _inicio(self, visao, periodos, vendedores, permitidos) -> tuple[dict, list[dict], dict]:
        escolha = self.calc.vendedores_da_visao(visao, periodos, vendedores, permitidos)
        carteira = self._carteira(sorted(escolha["vendedores"]))
        compras = self._compras([c["id"] for c in carteira], escolha["meses"])
        return escolha, carteira, compras

    def _cabecalho(self, lista: str, escolha: dict) -> dict:
        cache = self.calc.cache
        return {"lista": lista,
                "periodo": {"rotulo": escolha["rotulo"], "meses": [m.strftime("%Y-%m") for m in escolha["meses"]]},
                "vendedores": sorted(({"id": v, "nome": n} for v, n in escolha["vendedores"].items()),
                                     key=lambda x: x["nome"]),
                "data_ref": cache.info.get("data_ref"), "dados_ate": cache.info.get("extraido_em")}

    # ---------- as listas ----------
    def nao_atendidos(self, visao: str, periodos: list[tuple[int, int]], vendedores: list[int] | None = None,
                      permitidos: set[int] | None = None) -> dict:
        escolha, carteira, compras = self._inicio(visao, periodos, vendedores, permitidos)
        meses, nomes = escolha["meses"], escolha["vendedores"]
        cache = self.calc.cache
        regras = self.calc.regras()
        ids = [c["id"] for c in carteira]
        ultima, media = {}, defaultdict(float)
        ini_media = _menos_meses(meses[0], MESES_DA_MEDIA)
        if ids:
            ultima = {int(c): d for c, d in cache.consulta(
                "SELECT id_cliente, max(data) FROM vendas_clientes WHERE tipocliente = 'CLIENTE' "
                "AND id_cliente IN (SELECT unnest(?::INTEGER[])) GROUP BY 1", [ids])}
            for cli, pid, valor in cache.consulta(
                    "SELECT id_cliente, id_produto, sum(valor) FROM vendas_clientes_mes WHERE tipocliente = 'CLIENTE' "
                    "AND mes >= ? AND mes < ? AND id_cliente IN (SELECT unnest(?::INTEGER[])) GROUP BY 1, 2",
                    [ini_media, meses[0], ids]):
                if regras.grupo_produto(regras.produto(int(pid))) != "fora":
                    media[int(cli)] += float(valor or 0) / MESES_DA_MEDIA
        todos = None
        hoje = cache.dia_da_copia()
        itens, com_outro = [], 0
        for c in carteira:
            v, por_mes = c["vendedor"], compras.get(c["id"], {})
            sem = [m for m in meses if v not in por_mes.get(m, ())]
            if not sem:
                continue
            outros = sorted({o for m in sem for o in por_mes.get(m, ()) if o != v})
            if outros:
                com_outro += 1
                todos = todos if todos is not None else self.nomes_vendedores()
            u = ultima.get(c["id"])
            itens.append({
                "id": c["id"], "nome": c["nome"], "vendedor": {"id": v, "nome": nomes[v]},
                "area": c["area"], "cidade": c["cidade"], "uf": c["uf"], "segmento": c["segmento"],
                "ultima": u.isoformat() if u else None, "dias": max(0, (hoje - u).days) if u else None,
                "media": round(media.get(c["id"], 0.0), 2),
                "meses_sem": [rotulo_mes(m) for m in sem],
                "outros": [todos.get(o) or "outro vendedor" for o in outros],
            })
        itens.sort(key=lambda x: (-x["media"], x["nome"]))
        avisos = []
        if cache.sem_detalhe:
            avisos.append("O cadastro detalhado dos clientes ainda não chegou do computador da empresa: a lista fica sem "
                          "área, cidade e segmento, e clientes inativos podem aparecer.")
        return {**self._cabecalho("nao_atendidos", escolha),
                "resumo": {"carteira": len(carteira), "nao_atendidos": len(itens), "com_outro": com_outro,
                           "atendidos": len(carteira) - len(itens)},
                "media": {"de": rotulo_mes(ini_media), "ate": rotulo_mes(_menos_meses(meses[0], 1)),
                          "meses": MESES_DA_MEDIA},
                "itens": itens, "avisos": avisos}

    def fora_do_mix(self, visao: str, periodos: list[tuple[int, int]], vendedores: list[int] | None = None,
                    permitidos: set[int] | None = None) -> dict:
        cache = self.calc.cache
        if cache.pronto() and cache.sem_detalhe:
            raise RuntimeError("as vendas por cliente ainda não chegaram do computador da empresa; a lista aparece "
                               "depois da próxima atualização")
        escolha, carteira, compras = self._inicio(visao, periodos, vendedores, permitidos)
        meses, nomes = escolha["meses"], escolha["vendedores"]
        regras = self.calc.regras()
        atendidos = [c for c in carteira if any(c["vendedor"] in vs for vs in compras.get(c["id"], {}).values())]
        ids = [c["id"] for c in atendidos]
        levados: dict[int, set[int]] = defaultdict(set)
        comprado: dict[int, float] = defaultdict(float)
        if ids:
            periodo, params = filtro_meses(meses)
            for cli, pid, valor, qtd in cache.consulta(
                    f"SELECT id_cliente, id_produto, sum(valor), sum(quantidade) FROM vendas_clientes_itens "
                    f"WHERE tipocliente = 'CLIENTE' AND {periodo} AND id_cliente IN (SELECT unnest(?::INTEGER[])) "
                    f"GROUP BY 1, 2", [*params, ids]):
                p = regras.produto(int(pid))
                if regras.grupo_produto(p) != "fora":
                    comprado[int(cli)] += float(valor or 0)
                if (qtd or 0) > 0:
                    levados[int(cli)].add(p)
        mussarela = {int(r[0]) for r in cache.consulta(
            "SELECT id FROM produtos WHERE upper(COALESCE(linha, '')) LIKE ?", [f"%{LINHA_MUSSARELA}%"])}
        nomes_p = {int(i): n for i, n in cache.consulta("SELECT id, nome FROM produtos") if n}
        segmentos = self.config_crm.atual()["mix"]["segmentos"]
        itens, completos, sem_mix, sem_segmento, segs_sem_mix = [], 0, 0, 0, set()
        for c in atendidos:
            chave = normalizar(c["segmento"])
            lista = segmentos.get(chave) if chave else None
            if not chave:
                sem_segmento += 1
                continue
            if not lista:
                sem_mix += 1
                segs_sem_mix.add(c["segmento"])
                continue
            feitos = levados.get(c["id"], set())
            faltou = [nome_item(it, nomes_p) for it in lista
                      if not (feitos & mussarela if it.get("mussarela") else feitos & {int(p) for p in it["produtos"]})]
            if not faltou:
                completos += 1
                continue
            itens.append({
                "id": c["id"], "nome": c["nome"], "vendedor": {"id": c["vendedor"], "nome": nomes[c["vendedor"]]},
                "area": c["area"], "cidade": c["cidade"], "uf": c["uf"], "segmento": c["segmento"],
                "comprado": round(comprado.get(c["id"], 0.0), 2),
                "itens": len(lista), "levados": len(lista) - len(faltou), "faltou": faltou,
            })
        itens.sort(key=lambda x: (-len(x["faltou"]), -x["comprado"], x["nome"]))
        return {**self._cabecalho("mix", escolha),
                "resumo": {"carteira": len(carteira), "atendidos": len(atendidos),
                           "nao_atendidos": len(carteira) - len(atendidos), "com_falta": len(itens),
                           "completos": completos, "sem_mix": sem_mix, "sem_segmento": sem_segmento,
                           "segmentos_sem_mix": sorted(segs_sem_mix)},
                "itens": itens, "avisos": []}

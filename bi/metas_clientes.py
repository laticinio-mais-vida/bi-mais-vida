"""As listas de clientes que mostram o que dá para fazer para melhorar os números: nos cards das abas Metas ES, Metas BA e
Metas Edir e no painel de desempenho da Gestão (Positivação, Atendimentos, Mussarela e Outras linhas).

A base é sempre a carteira de hoje de cada vendedor: os clientes ativos, sem "PEDIDO BLOQUEADO" no nome (como no
painel de desempenho).

Página Metas (os vendedores e os meses da página: Calculadora.vendedores_da_visao):
- Clientes não atendidos (card "Clientes atendidos"): os clientes da carteira com quem o próprio vendedor não teve nota
  no mês. É a regra do card, que conta o cliente para o vendedor que fez a venda: quem comprou com outro vendedor
  aparece, marcado com o nome dele. Com vários meses, entra quem passou pelo menos um deles sem comprar com o vendedor
  (o card soma mês a mês).
- Clientes que não compraram produtos indicados (card "Composição do faturamento"): os clientes da carteira com quem o
  vendedor teve nota no período, com o que levaram (notas de qualquer vendedor) comparado ao mix ideal do segmento
  (CRM › Configurar › Mix ideal, a mesma regra do CRM: um item vale com qualquer um dos seus produtos, "qualquer
  mussarela" com qualquer produto da linha mussarela, e a equivalência de produtos das Metas vale). Só entra quem
  deixou de levar algum item. Devolução não tira o item.

Painel de desempenho (os vendedores do quadro, o período e o mês dele: do_painel), cada lista com a conta da linha:
- Positivação: a lista de não atendidos da página Metas, do dia 1º do mês até o fim do período.
- Atendimentos: as visitas esperadas no período sem pedido no dia da rota, cliente a cliente, da mesma conta da linha
  (Painel.atendimentos_clientes), com os pedidos que o cliente fez fora do dia da rota naquela semana.
- Mussarela: os clientes do período (os que compraram com o vendedor e os esperados na rota, mesmo sem compra) cujo
  segmento tem "Qualquer mussarela" no mix ideal e que não levaram mussarela. Levar mussarela é comprar um produto do
  grupo mussarela da página Metas, o mesmo da linha Mussarela do painel.
- Outras linhas: os mesmos clientes, com o mix ideal sem o item da mussarela (a lista do card da página Metas).
Cada cliente traz o potencial do mês (a média do que comprou nos 2 meses fechados antes, a conta da meta do dia).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .crm import LINHA_MUSSARELA, normalizar
from .indicadores import _PEDIDO_VALIDO
from .manejo import nome_erp
from .metas import MESES, _fim_do_mes

MESES_DA_MEDIA = 6  # a compra média por mês da lista de não atendidos: os meses fechados antes do período
BLOQUEADO = "PEDIDO BLOQUEADO"
LISTAS_PAINEL = ("positivacao", "atendimentos", "mussarela", "outras")
FREQUENCIA = {1: "semanal", 2: "quinzenal", 4: "mensal"}  # frequencia_semanas (a rede do cadastro)
SEM_DETALHE = ("as vendas por cliente ainda não chegaram do computador da empresa; a lista aparece depois da próxima "
               "atualização")


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


def _faixas_dos_meses(meses: list[dt.date]) -> list[tuple[dt.date, dt.date]]:
    return [(m, _fim_do_mes(m)) for m in meses]


def _filtro_faixas(faixas: list[tuple[dt.date, dt.date]]) -> tuple[str, list]:
    """Trecho SQL "data em alguma das faixas" (de, até: as duas pontas entram)."""
    return "(" + " OR ".join("data BETWEEN ? AND ?" for _ in faixas) + ")", [d for f in faixas for d in f]


def _iso(d) -> str | None:
    return d.isoformat() if d else None


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

    def _compras(self, ids: list[int], faixas: list[tuple[dt.date, dt.date]]) -> dict[int, dict[dt.date, set[int]]]:
        """{cliente: {mês: vendedores com nota para ele nas faixas, naquele mês}} (notas não canceladas, como no card)."""
        saida: dict[int, dict[dt.date, set[int]]] = defaultdict(lambda: defaultdict(set))
        if not ids:
            return saida
        periodo, params = _filtro_faixas(faixas)
        for cli, mes, v in self.calc.cache.consulta(
                f"SELECT id_cliente, CAST(date_trunc('month', data) AS DATE), COALESCE(id_vendedor, 0) "
                f"FROM vendas_clientes WHERE tipocliente = 'CLIENTE' AND {periodo} "
                f"AND id_cliente IN (SELECT unnest(?::INTEGER[])) GROUP BY 1, 2, 3", [*params, ids]):
            saida[int(cli)][mes].add(int(v))
        return saida

    def _nome_de(self):
        """O nome de um vendedor de fora da lista ("comprou com"), lido uma vez só por lista."""
        guardado = {}

        def nome(v: int) -> str:
            if "nomes" not in guardado:
                guardado["nomes"] = self.nomes_vendedores()
            return guardado["nomes"].get(v) or "outro vendedor"
        return nome

    def _nao_atendidos(self, nomes: dict[int, str], faixas: list[tuple[dt.date, dt.date]]):
        """(carteira, itens, com_outro): os clientes da carteira destes vendedores que passaram pelo menos um dos meses
        das faixas (cada faixa dentro de um mês) sem nota do próprio vendedor, sem a ordem e sem o valor de cada um."""
        cache = self.calc.cache
        carteira = self._carteira(sorted(nomes))
        compras = self._compras([c["id"] for c in carteira], faixas)
        meses = [de.replace(day=1) for de, _ in faixas]
        sem_compra = []
        for c in carteira:
            por_mes = compras.get(c["id"], {})
            sem = [m for m in meses if c["vendedor"] not in por_mes.get(m, ())]
            if sem:
                sem_compra.append((c, por_mes, sem))
        ids = [c["id"] for c, _, _ in sem_compra]
        ultima = {int(cli): d for cli, d in cache.consulta(
            "SELECT id_cliente, max(data) FROM vendas_clientes WHERE tipocliente = 'CLIENTE' "
            "AND id_cliente IN (SELECT unnest(?::INTEGER[])) GROUP BY 1", [ids])} if ids else {}
        nome_de = self._nome_de()
        hoje = cache.dia_da_copia()
        itens, com_outro = [], 0
        for c, por_mes, sem in sem_compra:
            v = c["vendedor"]
            outros = sorted({o for m in sem for o in por_mes.get(m, ()) if o != v})
            com_outro += bool(outros)
            u = ultima.get(c["id"])
            itens.append({
                "id": c["id"], "nome": c["nome"], "vendedor": {"id": v, "nome": nomes[v]},
                "area": c["area"], "cidade": c["cidade"], "uf": c["uf"], "segmento": c["segmento"],
                "ultima": _iso(u), "dias": max(0, (hoje - u).days) if u else None,
                "meses_sem": [rotulo_mes(m) for m in sem], "outros": [nome_de(o) for o in outros],
            })
        return carteira, itens, com_outro

    def _mix(self, nomes: dict[int, str], faixas: list[tuple[dt.date, dt.date]], parte: str = "tudo",
             esperados: set[int] | None = None) -> dict:
        """Os clientes que não levaram o mix ideal do segmento nas faixas: os da carteira com nota do próprio vendedor
        e, com esperados (o painel), também esses clientes da carteira, mesmo sem compra. parte: "tudo" (a página
        Metas: o mix inteiro), "outras" (o mix sem o item da mussarela) ou "mussarela" (só ele, pelo grupo mussarela
        da página Metas). O que o cliente levou vale de qualquer vendedor."""
        cache = self.calc.cache
        if cache.pronto() and cache.sem_detalhe:
            raise RuntimeError(SEM_DETALHE)
        regras = self.calc.regras()
        carteira = self._carteira(sorted(nomes))
        compras = self._compras([c["id"] for c in carteira], faixas)
        comprou = {c["id"] for c in carteira if any(c["vendedor"] in vs for vs in compras.get(c["id"], {}).values())}
        painel = esperados is not None
        base = [c for c in carteira if c["id"] in comprou or (painel and c["id"] in esperados)]
        ids = [c["id"] for c in base]
        levados: dict[int, set[int]] = defaultdict(set)
        comprado: dict[int, float] = defaultdict(float)
        if ids:
            periodo, params = _filtro_faixas(faixas)
            for cli, pid, valor, qtd in cache.consulta(
                    f"SELECT id_cliente, id_produto, sum(valor), sum(quantidade) FROM vendas_clientes_itens "
                    f"WHERE tipocliente = 'CLIENTE' AND {periodo} AND id_cliente IN (SELECT unnest(?::INTEGER[])) "
                    f"GROUP BY 1, 2", [*params, ids]):
                p = regras.produto(int(pid))
                if regras.grupo_produto(p) != "fora":
                    comprado[int(cli)] += float(valor or 0)
                if (qtd or 0) > 0:
                    levados[int(cli)].add(p)
        linha_mussarela = {int(r[0]) for r in cache.consulta(
            "SELECT id FROM produtos WHERE upper(COALESCE(linha, '')) LIKE ?", [f"%{LINHA_MUSSARELA}%"])}
        nomes_p = {int(i): n for i, n in cache.consulta("SELECT id, nome FROM produtos") if n}
        segmentos = self.config_crm.atual()["mix"]["segmentos"]
        nome_de = self._nome_de()
        itens, completos, sem_mix, sem_segmento, sem_parte = [], 0, 0, 0, 0
        segs_sem_mix, segs_sem_parte = set(), set()
        for c in base:
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
            if parte == "mussarela":
                alvo = [it for it in lista if it.get("mussarela")]
            elif parte == "outras":
                alvo = [it for it in lista if not it.get("mussarela")]
            else:
                alvo = lista
            if not alvo:  # o mix do segmento não tem mussarela (ou só tem ela, nas outras linhas)
                sem_parte += 1
                segs_sem_parte.add(c["segmento"])
                continue
            if parte == "mussarela":
                faltou = [] if any(regras.grupo_produto(p) == "mussarela" for p in feitos) else ["Mussarela"]
            else:
                faltou = [nome_item(it, nomes_p) for it in alvo
                          if not (feitos & linha_mussarela if it.get("mussarela")
                                  else feitos & {int(p) for p in it["produtos"]})]
            if not faltou:
                completos += 1
                continue
            item = {"id": c["id"], "nome": c["nome"], "vendedor": {"id": c["vendedor"], "nome": nomes[c["vendedor"]]},
                    "area": c["area"], "cidade": c["cidade"], "uf": c["uf"], "segmento": c["segmento"],
                    "comprado": round(comprado.get(c["id"], 0.0), 2)}
            if parte != "mussarela":
                item.update(itens=len(alvo), levados=len(alvo) - len(faltou), faltou=faltou)
            if painel:
                outros = sorted({o for vs in compras.get(c["id"], {}).values() for o in vs if o != c["vendedor"]})
                item.update(comprou=c["id"] in comprou,
                            outros=[] if c["id"] in comprou else [nome_de(o) for o in outros])
            itens.append(item)
        resumo = {"carteira": len(carteira), "atendidos": len(comprou), "nao_atendidos": len(carteira) - len(comprou),
                  "com_falta": len(itens), "completos": completos, "sem_mix": sem_mix, "sem_segmento": sem_segmento,
                  "segmentos_sem_mix": sorted(segs_sem_mix)}
        if painel:
            resumo.update(base=len(base), esperados_sem_compra=len(base) - len(comprou & set(ids)),
                          sem_parte=sem_parte, segmentos_sem_parte=sorted(segs_sem_parte))
        return {"itens": itens, "resumo": resumo}

    # ---------- a página Metas ----------
    def _cabecalho(self, lista: str, escolha: dict) -> dict:
        cache = self.calc.cache
        return {"lista": lista,
                "periodo": {"rotulo": escolha["rotulo"], "meses": [m.strftime("%Y-%m") for m in escolha["meses"]]},
                "vendedores": sorted(({"id": v, "nome": n} for v, n in escolha["vendedores"].items()),
                                     key=lambda x: x["nome"]),
                "data_ref": cache.info.get("data_ref"), "dados_ate": cache.info.get("extraido_em")}

    def nao_atendidos(self, visao: str, periodos: list[tuple[int, int]], vendedores: list[int] | None = None,
                      permitidos: set[int] | None = None) -> dict:
        escolha = self.calc.vendedores_da_visao(visao, periodos, vendedores, permitidos)
        meses = escolha["meses"]
        cache = self.calc.cache
        regras = self.calc.regras()
        carteira, itens, com_outro = self._nao_atendidos(escolha["vendedores"], _faixas_dos_meses(meses))
        ini_media = _menos_meses(meses[0], MESES_DA_MEDIA)
        media: dict[int, float] = defaultdict(float)
        ids = [c["id"] for c in itens]
        if ids:
            for cli, pid, valor in cache.consulta(
                    "SELECT id_cliente, id_produto, sum(valor) FROM vendas_clientes_mes WHERE tipocliente = 'CLIENTE' "
                    "AND mes >= ? AND mes < ? AND id_cliente IN (SELECT unnest(?::INTEGER[])) GROUP BY 1, 2",
                    [ini_media, meses[0], ids]):
                if regras.grupo_produto(regras.produto(int(pid))) != "fora":
                    media[int(cli)] += float(valor or 0) / MESES_DA_MEDIA
        for c in itens:
            c["media"] = round(media.get(c["id"], 0.0), 2)
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
            raise RuntimeError(SEM_DETALHE)
        escolha = self.calc.vendedores_da_visao(visao, periodos, vendedores, permitidos)
        r = self._mix(escolha["vendedores"], _faixas_dos_meses(escolha["meses"]))
        itens = sorted(r["itens"], key=lambda x: (-len(x["faltou"]), -x["comprado"], x["nome"]))
        return {**self._cabecalho("mix", escolha), "resumo": r["resumo"], "itens": itens, "avisos": []}

    # ---------- o painel de desempenho da Gestão ----------
    def do_painel(self, lista: str, painel, per: dict, nomes: dict[int, str]) -> dict:
        """A lista de uma linha do painel (LISTAS_PAINEL) para estes vendedores (nomes: {vendedor: nome}), no período
        do painel (per: inicio e fim; a positivação, do dia 1º do mês do fim até ele). painel: o Painel da leitura (a
        conta dos atendimentos, o potencial dos clientes e o recorte da Gestão)."""
        if lista not in LISTAS_PAINEL:
            raise ValueError(f"lista desconhecida: {lista!r} (use {', '.join(LISTAS_PAINEL)})")
        if not nomes:  # a equipe do painel sem ninguém do acesso
            return {"lista": lista, "resumo": None, "itens": [], "avisos": []}
        inicio, fim = per["inicio"], per["fim"]
        mes = fim.replace(day=1)
        avisos: list[str] = []
        if lista == "positivacao":
            carteira, itens, com_outro = self._nao_atendidos(nomes, [(mes, fim)])
            for c in itens:
                del c["meses_sem"]  # um mês só
            resumo = {"carteira": len(carteira), "nao_atendidos": len(itens), "com_outro": com_outro,
                      "atendidos": len(carteira) - len(itens), "de": mes.isoformat(), "ate": fim.isoformat()}
        elif lista == "atendimentos":
            itens, resumo = self._atendimentos(painel, nomes, inicio, fim)
        else:
            linhas = painel.atendimentos_clientes(sorted(nomes), inicio, fim)
            if linhas is None:
                avisos.append("Sem os pedidos de venda ou a frequência dos clientes, a lista tem só quem comprou com o "
                              "vendedor no período (os esperados na rota que não compraram ficam de fora).")
            esperados = {x["id"] for x in linhas or [] if x["visitas"]}
            r = self._mix(nomes, [(inicio, fim)], lista, esperados)
            itens, resumo = r["itens"], r["resumo"]
            # Sem nota do vendedor, mas com pedido de venda no período (a nota ainda não entrou na cópia): marcado, para
            # não parecer que o cliente não comprou nada.
            sem_nota = [c["id"] for c in itens if not c["comprou"]]
            com_pedido = set()
            if sem_nota and not self.calc.cache.sem_pedidos:
                com_pedido = {int(i) for (i,) in painel.cur.execute(
                    f"SELECT DISTINCT p.id_cliente FROM _pedidos_venda p WHERE {_PEDIDO_VALIDO} "
                    f"AND p.data BETWEEN ? AND ? AND p.id_cliente IN ({','.join('?' * len(sem_nota))})",
                    [inicio, fim, *sem_nota]).fetchall()}
            for c in itens:
                c["pedido_sem_nota"] = not c["comprou"] and c["id"] in com_pedido
            resumo["pedido_sem_nota"] = sum(c["pedido_sem_nota"] for c in itens)
        pots = painel.potenciais(mes)
        for c in itens:
            c["potencial"] = round(pots.get(c["id"], 0.0), 2)
        itens.sort(key=lambda x: (-x["potencial"], x["nome"], x.get("dia") or ""))
        return {"lista": lista, "resumo": resumo, "itens": itens, "avisos": avisos}

    def _atendimentos(self, painel, nomes: dict[int, str], inicio: dt.date, fim: dt.date) -> tuple[list[dict], dict]:
        """As visitas esperadas sem pedido no dia da rota (a linha Atendimentos, cliente a cliente), com a frequência, o
        último pedido e os pedidos da semana fora do dia da rota."""
        linhas = painel.atendimentos_clientes(sorted(nomes), inicio, fim)
        if linhas is None:
            raise RuntimeError("os pedidos de venda ou a frequência de compra dos clientes ainda não chegaram do "
                               "computador da empresa: os atendimentos aparecem depois da próxima atualização")
        visitas = [x for x in linhas if x["visitas"]]
        sem = [x for x in visitas if not x["pedidos"]]
        ids = sorted({x["id"] for x in sem})
        info, ultimo, na_semana = {}, {}, defaultdict(list)
        if ids:
            marcas = ",".join("?" * len(ids))
            info = {int(r[0]): r[1:] for r in painel.cur.execute(
                f"SELECT id_cliente, cliente, area, cidade, uf, segmento, frequencia_semanas FROM clientes "
                f"WHERE id_cliente IN ({marcas})", ids).fetchall()}
            ultimo = {int(c): d for c, d in painel.cur.execute(
                f"SELECT p.id_cliente, max(p.data) FROM _pedidos_venda p WHERE {_PEDIDO_VALIDO} "
                f"AND p.id_cliente IN ({marcas}) GROUP BY 1", ids).fetchall()}
            domingo = lambda d: d - dt.timedelta(days=d.isoweekday() % 7)  # noqa: E731
            de = min(domingo(x["dia"]) for x in sem)
            ate = max(domingo(x["dia"]) for x in sem) + dt.timedelta(days=6)
            for c, d in painel.cur.execute(
                    f"SELECT DISTINCT p.id_cliente, p.data FROM _pedidos_venda p WHERE {_PEDIDO_VALIDO} "
                    f"AND p.data BETWEEN ? AND ? AND p.id_cliente IN ({marcas}) ORDER BY 2", [de, ate, *ids]).fetchall():
                na_semana[int(c)].append(d)
        itens, fora_do_dia = [], 0
        for x in sem:
            nome, area, cidade, uf, segmento, semanas = info.get(x["id"], (None,) * 6)
            semana = x["dia"] - dt.timedelta(days=x["dia"].isoweekday() % 7)
            fora = [d for d in na_semana.get(x["id"], []) if semana <= d <= semana + dt.timedelta(days=6)]
            fora_do_dia += bool(fora)
            u = ultimo.get(x["id"])
            itens.append({
                "id": x["id"], "nome": nome_erp(nome), "vendedor": {"id": x["vendedor"], "nome": nomes[x["vendedor"]]},
                "area": area or x["area"], "cidade": cidade, "uf": uf, "segmento": (segmento or "").strip() or None,
                "dia": x["dia"].isoformat(), "frequencia": FREQUENCIA.get(int(semanas)) if semanas else None,
                "ultimo_pedido": _iso(u), "fora_do_dia": [d.isoformat() for d in fora],
            })
        resumo = {"esperados": len(visitas), "atendidos": len(visitas) - len(sem), "nao_atendidos": len(sem),
                  "fora_do_dia": fora_do_dia}
        return itens, resumo

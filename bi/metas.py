"""Cálculo das visões de metas (equivalentes às páginas Metas ES, BA, Edir, Outras Linhas ES e Produtos BA).

Regras (as mesmas do Power BI, com os parâmetros vindos da página Configurações):
- venda válida: VENDAS.DATACANCELAMENTO nula; conta pelo vendedor e pela data da venda;
- devolução que desconta: item com motivo marcado em Configurações; conta pelo vendedor e pela data de
  ENTRADA da devolução;
- faturamento = mussarela + outras linhas (produtos marcados como "não conta" ficam fora de tudo);
- clientes = clientes distintos com venda válida no mês (o total não repete cliente atendido por dois vendedores);
- ritmo esperado = dias úteis já passados / dias úteis do mês, até o último dia com venda na cópia do banco.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
from collections import defaultdict

from .cache import Cache
from .calendario import Calendario, feriados_do_ano
from .configuracao import VISOES, Configuracao, Regras
from .planilhas import PlanilhaMonitorada

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]
_SIGLAS = {"ES", "BA", "PS", "TX", "EU", "ITM", "R13"}


def nome_bonito(nome: str) -> str:
    """'RICARDO - EU' -> 'Ricardo - EU'; 'JOSE CARLOS' -> 'Jose Carlos'."""
    partes = re.split(r"(\s+|-|\(|\))", nome.strip())
    return "".join(p if p.upper() in _SIGLAS else p.capitalize() for p in partes)


def _div(a: float, b: float) -> float | None:
    return a / b if b else None


def status(realizado: float, meta: float, ritmo: float, situacao: str) -> str:
    if not meta:
        return "sem_meta"
    pct = realizado / meta
    if pct >= 1:
        return "batida"
    alvo = 1.0 if situacao == "fechado" else ritmo
    if situacao == "futuro" or pct >= alvo:
        return "no_ritmo"
    if pct >= alvo * 0.9:
        return "atencao"
    return "abaixo"


def indicador(realizado: float, meta: float, cal: dict) -> dict:
    """Bloco padrão de um indicador: meta, realizado, %, status, projeção e quanto falta por dia útil."""
    situacao, ritmo = cal["situacao"], cal["ritmo"]
    projecao = None
    if situacao == "aberto" and cal["dias_decorridos"] > 0:
        projecao = realizado / cal["dias_decorridos"] * cal["dias_uteis"]
    elif situacao == "fechado":
        projecao = realizado
    falta = max(meta - realizado, 0.0) if meta else None
    por_dia = (falta / cal["dias_restantes"]) if (falta and situacao != "fechado" and cal["dias_restantes"] > 0) else None
    return {
        "meta": meta,
        "realizado": realizado,
        "pct": _div(realizado, meta),
        "status": status(realizado, meta, ritmo, situacao),
        "projecao": projecao,
        "projecao_pct": _div(projecao, meta) if projecao is not None else None,
        "falta": falta,
        "falta_por_dia": por_dia,
        "esperado": meta * (1.0 if situacao == "fechado" else ritmo) if meta else None,
    }


class Calculadora:
    def __init__(self, cache: Cache, metas: PlanilhaMonitorada, metas_produtos: PlanilhaMonitorada,
                 configuracao: Configuracao):
        self.cache = cache
        self.metas = metas
        self.metas_produtos = metas_produtos
        self.configuracao = configuracao

    # --- apoio ---------------------------------------------------------------------------
    def regras(self) -> Regras:
        sup = {}
        if self.cache.pronto():
            sup = {v: s for v, s in self.cache.consulta("SELECT id, id_supervisor FROM vendedores")}
        return Regras(self.configuracao.atual(), sup)

    def calendario(self, regras: Regras) -> Calendario:
        cal = regras.cfg["calendario"]
        return Calendario(cal["extras"], cal["sabado"])

    def nomes_erp(self) -> dict[int, str]:
        return dict(self.cache.consulta("SELECT id, nome FROM vendedores"))

    def avisos(self) -> list[str]:
        return [a for a in (self.metas.aviso, self.metas_produtos.aviso) if a]

    def opcoes(self) -> dict:
        meses = sorted({m["mes"] for m in self.metas.dados()} | {m["mes"] for m in self.metas_produtos.dados()})
        data_ref = self.cache.data_ref() if self.cache.pronto() else None
        padrao = None
        if data_ref and data_ref.replace(day=1) in meses:
            padrao = data_ref.replace(day=1)
        elif meses:
            padrao = meses[-1]
        meses_produtos = sorted({m["mes"] for m in self.metas_produtos.dados()})
        return {
            "visoes": [{"id": k, "titulo": v["titulo"], "tipo": v["tipo"], "regiao": v["regiao"]} for k, v in VISOES.items()],
            "meses": [{"ano": m.year, "mes": m.month} for m in meses],
            "meses_produtos": [{"ano": m.year, "mes": m.month} for m in meses_produtos],
            "padrao": {"ano": padrao.year, "mes": padrao.month} if padrao else None,
            "nomes_meses": MESES,
        }

    def _metas_do_mes(self, regras: Regras, mes: dt.date, grupos: list[str]) -> dict[int, dict]:
        """Metas por vendedor no mês, para os grupos da visão (soma se o ID aparecer duas vezes)."""
        saida: dict[int, dict] = {}
        for m in self.metas.dados():
            if m["mes"] != mes or regras.grupo_vendedor(m["id_vendedor"]) not in grupos:
                continue
            atual = saida.setdefault(m["id_vendedor"], {"nome": m["vendedor"], "fat": 0.0, "mus": 0.0, "out": 0.0, "cli": 0.0})
            atual["fat"] += m["meta_fat"]
            atual["mus"] += m["meta_mus"]
            atual["out"] += m["meta_out"]
            atual["cli"] += m["meta_cli"]
        return saida

    def _movimento(self, regras: Regras, ids: list[int], inicio: dt.date, fim: dt.date):
        """Vendas e devoluções (que descontam) por vendedor/produto e por dia/produto, já com equivalências."""
        por_vendedor = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # vid -> pid -> [valor, qtd]
        por_dia = defaultdict(lambda: defaultdict(float))                     # data -> pid -> valor
        if not ids:
            return por_vendedor, por_dia
        marcas = ",".join("?" * len(ids))
        for d, vid, pid, valor, qtd in self.cache.consulta(
                f"SELECT data, id_vendedor, id_produto, SUM(valor), SUM(quantidade) FROM vendas_itens "
                f"WHERE data BETWEEN ? AND ? AND id_vendedor IN ({marcas}) GROUP BY 1, 2, 3",
                [inicio, fim, *ids]):
            p = regras.produto(pid)
            por_vendedor[vid][p][0] += valor
            por_vendedor[vid][p][1] += qtd
            por_dia[d][p] += valor
        for d, vid, pid, motivo, cancelada, valor, qtd in self.cache.consulta(
                f"SELECT data, id_vendedor, id_produto, id_motivo, cancelada, SUM(valor), SUM(quantidade) "
                f"FROM devolucoes_itens WHERE data BETWEEN ? AND ? AND id_vendedor IN ({marcas}) "
                f"GROUP BY 1, 2, 3, 4, 5", [inicio, fim, *ids]):
            if motivo not in regras.motivos or (cancelada and regras.ignorar_canceladas):
                continue
            p = regras.produto(pid)
            por_vendedor[vid][p][0] -= valor
            por_vendedor[vid][p][1] -= qtd
            por_dia[d][p] -= valor
        return por_vendedor, por_dia

    def _clientes(self, ids: list[int], inicio: dt.date, fim: dt.date) -> tuple[dict[int, int], int]:
        if not ids:
            return {}, 0
        marcas = ",".join("?" * len(ids))
        por_vendedor = dict(self.cache.consulta(
            f"SELECT id_vendedor, COUNT(DISTINCT id_cliente) FROM vendas_clientes "
            f"WHERE data BETWEEN ? AND ? AND id_vendedor IN ({marcas}) GROUP BY 1", [inicio, fim, *ids]))
        total = self.cache.consulta(
            f"SELECT COUNT(DISTINCT id_cliente) FROM vendas_clientes "
            f"WHERE data BETWEEN ? AND ? AND id_vendedor IN ({marcas})", [inicio, fim, *ids])[0][0]
        return por_vendedor, total

    # --- visões --------------------------------------------------------------------------
    def visao(self, visao: str, ano: int, mes: int, vendedor: int | None = None,
              permitidos: set[int] | None = None) -> dict:
        """permitidos: vendedores que o usuário pode ver (None = todos); os totais somam só esses."""
        if visao not in VISOES:
            raise ValueError(f"visão desconhecida: {visao}")
        if not self.cache.pronto():
            raise RuntimeError("os dados ainda estão sendo preparados")
        info = VISOES[visao]
        regras = self.regras()
        cal_obj = self.calendario(regras)
        data_ref = self.cache.data_ref()
        inicio = dt.date(ano, mes, 1)
        fim = dt.date(ano, mes, calendar.monthrange(ano, mes)[1])
        cal = cal_obj.resumo(ano, mes, info["regiao"], data_ref)
        base = {
            "visao": {"id": visao, **info},
            "periodo": {"ano": ano, "mes": mes, "inicio": inicio.isoformat(), "fim": fim.isoformat(),
                        "rotulo": f"{MESES[mes - 1].capitalize()} de {ano}"},
            "data_ref": data_ref.isoformat(),
            "calendario": cal,
            "avisos": self.avisos(),
        }
        if info["tipo"] == "produtos":
            return {**base, **self._visao_produtos(regras, info, inicio, fim, cal, vendedor, permitidos)}
        return {**base, **self._visao_vendedores(regras, info, inicio, fim, cal, cal_obj, vendedor, permitidos)}

    def _visao_vendedores(self, regras, info, inicio, fim, cal, cal_obj, vendedor, permitidos):
        metas = self._metas_do_mes(regras, inicio, info["grupos"])
        if permitidos is not None:
            metas = {k: v for k, v in metas.items() if k in permitidos}
        nomes_erp = self.nomes_erp()
        lista = sorted(({"id": vid, "nome": nome_bonito(m["nome"]), "nome_erp": nomes_erp.get(vid, "")}
                        for vid, m in metas.items()), key=lambda x: x["nome"])
        if vendedor is not None:
            metas = {k: v for k, v in metas.items() if k == vendedor}
        ids = sorted(metas)
        mov, por_dia = self._movimento(regras, ids, inicio, fim)
        cli_vend, cli_total = self._clientes(ids, inicio, fim)
        categorias = regras.categorias

        def soma(produtos: dict) -> dict:
            r = {"fat": 0.0, "mus": 0.0, "out": 0.0, "cat": {c: 0.0 for c in categorias}, "demais": 0.0}
            for pid, (valor, _qtd) in produtos.items():
                grupo = regras.grupo_produto(pid)
                if grupo == "fora":
                    continue
                r["fat"] += valor
                if grupo == "mussarela":
                    r["mus"] += valor
                else:
                    r["out"] += valor
                    cat = regras.categoria(pid)
                    if cat in r["cat"]:
                        r["cat"][cat] += valor
                    else:
                        r["demais"] += valor
            return r

        linhas = []
        tot_meta = {"fat": 0.0, "mus": 0.0, "out": 0.0, "cli": 0.0}
        tot = {"fat": 0.0, "mus": 0.0, "out": 0.0, "cat": {c: 0.0 for c in categorias}, "demais": 0.0}
        for vid in ids:
            m = metas[vid]
            s = soma(mov.get(vid, {}))
            clientes = cli_vend.get(vid, 0)
            for k in ("fat", "mus", "out", "cli"):
                tot_meta[k] += m[k]
            for k in ("fat", "mus", "out", "demais"):
                tot[k] += s[k]
            for c in categorias:
                tot["cat"][c] += s["cat"][c]
            linhas.append({
                "id": vid,
                "nome": nome_bonito(m["nome"]),
                "nome_planilha": m["nome"].upper(),
                "nome_erp": nomes_erp.get(vid, ""),
                "faturamento": indicador(s["fat"], m["fat"], cal),
                "mussarela": indicador(s["mus"], m["mus"], cal),
                "outras": indicador(s["out"], m["out"], cal),
                "clientes": indicador(clientes, m["cli"], cal),
                "venda_media": {"meta": _div(m["fat"], m["cli"]), "realizado": _div(s["fat"], clientes),
                                "pct": _div(_div(s["fat"], clientes) or 0, _div(m["fat"], m["cli"]) or 0)},
                "categorias": s["cat"],
                "demais": s["demais"],
            })
        indicadores = {
            "faturamento": indicador(tot["fat"], tot_meta["fat"], cal),
            "mussarela": indicador(tot["mus"], tot_meta["mus"], cal),
            "outras": indicador(tot["out"], tot_meta["out"], cal),
            "clientes": indicador(cli_total, tot_meta["cli"], cal),
            "venda_media": {"meta": _div(tot_meta["fat"], tot_meta["cli"]), "realizado": _div(tot["fat"], cli_total),
                            "pct": _div(_div(tot["fat"], cli_total) or 0, _div(tot_meta["fat"], tot_meta["cli"]) or 0)},
        }
        contagem = defaultdict(int)
        chave = "outras" if info["tipo"] == "outras" else "faturamento"
        for linha in linhas:
            contagem[linha[chave]["status"]] += 1

        # Série diária acumulada para a "corrida da meta"
        ritmo = dict(cal_obj.ritmo_ate(inicio.year, inicio.month, info["regiao"]))
        data_ref = self.cache.data_ref()
        diario, acum = [], {"fat": 0.0, "mus": 0.0, "out": 0.0}
        d = inicio
        while d <= fim:
            dia = {"fat": 0.0, "mus": 0.0, "out": 0.0}
            for pid, valor in por_dia.get(d, {}).items():
                grupo = regras.grupo_produto(pid)
                if grupo == "fora":
                    continue
                dia["fat"] += valor
                dia["mus" if grupo == "mussarela" else "out"] += valor
            for k in acum:
                acum[k] += dia[k]
            passou = d <= data_ref
            diario.append({
                "data": d.isoformat(),
                "ritmo": ritmo[d],
                "fat": round(dia["fat"], 2) if passou else None,
                "fat_acum": round(acum["fat"], 2) if passou else None,
                "mus_acum": round(acum["mus"], 2) if passou else None,
                "out_acum": round(acum["out"], 2) if passou else None,
            })
            d += dt.timedelta(days=1)

        return {
            "vendedores": lista,
            "vendedor": vendedor,
            "indicadores": indicadores,
            "linhas": linhas,
            "contagem_status": dict(contagem),
            "categorias": {"lista": categorias, "total": tot["cat"], "demais": tot["demais"]},
            "diario": diario,
        }

    def _visao_produtos(self, regras, info, inicio, fim, cal, vendedor, permitidos):
        nomes_erp = self.nomes_erp()
        metas_prod = defaultdict(lambda: defaultdict(float))  # pid -> vid -> meta
        nomes_planilha: dict[int, str] = {}
        for m in self.metas_produtos.dados():
            if m["mes"] != inicio or regras.grupo_vendedor(m["id_vendedor"]) not in info["grupos"]:
                continue
            metas_prod[regras.produto(m["id_produto"])][m["id_vendedor"]] += m["meta_volume"]
            nomes_planilha[m["id_vendedor"]] = m["vendedor"]
        todos_ids = sorted({vid for por_v in metas_prod.values() for vid in por_v
                            if permitidos is None or vid in permitidos})
        lista = sorted(({"id": vid, "nome": nome_bonito(nomes_planilha.get(vid) or nomes_erp.get(vid, str(vid))),
                         "nome_erp": nomes_erp.get(vid, "")} for vid in todos_ids), key=lambda x: x["nome"])
        ids = [v for v in todos_ids if vendedor is None or v == vendedor]
        mov, _ = self._movimento(regras, ids, inicio, fim)
        produtos_info = {}
        pids = set(metas_prod)
        for vid in ids:
            pids |= {p for p, (_v, q) in mov.get(vid, {}).items() if abs(q) > 1e-9 and regras.grupo_produto(p) != "fora"}
        if pids:
            marcas = ",".join("?" * len(pids))
            produtos_info = {r[0]: r[1:] for r in self.cache.consulta(
                f"SELECT id, nome, unidade, linha FROM produtos WHERE id IN ({marcas})", sorted(pids))}

        linhas = []
        for pid in pids:
            por_vendedor = {}
            meta_t = real_t = 0.0
            tem_meta = False
            for vid in ids:
                meta = metas_prod.get(pid, {}).get(vid)
                real = mov.get(vid, {}).get(pid, [0.0, 0.0])[1]
                if meta is None and abs(real) < 1e-9:
                    continue
                tem_meta = tem_meta or meta is not None
                ind = indicador(real, meta or 0.0, cal)
                por_vendedor[str(vid)] = ind
                meta_t += meta or 0.0
                real_t += real
            if not por_vendedor:
                continue
            nome, unidade, linha = produtos_info.get(pid, (f"Produto {pid}", "", ""))
            linhas.append({
                "id": pid, "nome": nome, "unidade": unidade or "", "linha": linha or "",
                "grupo": regras.grupo_produto(pid), "categoria": regras.categoria(pid),
                "tem_meta": tem_meta, "total": indicador(real_t, meta_t, cal), "por_vendedor": por_vendedor,
            })
        linhas.sort(key=lambda r: (not r["tem_meta"], -(r["total"]["meta"] or 0), r["nome"]))
        com_meta = [r for r in linhas if r["tem_meta"] and r["total"]["meta"]]
        contagem = defaultdict(int)
        for r in com_meta:
            contagem[r["total"]["status"]] += 1
        resumo_vend = []
        for v in lista:
            if v["id"] not in ids:
                continue
            celulas = [r["por_vendedor"].get(str(v["id"])) for r in com_meta]
            celulas = [c for c in celulas if c and c["meta"]]
            resumo_vend.append({
                **v,
                "produtos": len(celulas),
                "batidas": sum(1 for c in celulas if c["status"] == "batida"),
                "no_ritmo": sum(1 for c in celulas if c["status"] in ("batida", "no_ritmo")),
                "atencao": sum(1 for c in celulas if c["status"] == "atencao"),
                "atingimento": _div(sum(min(c["pct"] or 0, 1.5) for c in celulas), len(celulas)),
            })
        return {
            "vendedores": lista,
            "vendedor": vendedor,
            "colunas": [v for v in lista if v["id"] in ids],
            "produtos": linhas,
            "resumo_vendedores": resumo_vend,
            "indicadores": {
                "produtos": len(com_meta),
                "batidas": contagem.get("batida", 0),
                "no_ritmo": contagem.get("batida", 0) + contagem.get("no_ritmo", 0),
                "atencao": contagem.get("atencao", 0),
                "abaixo": contagem.get("abaixo", 0),
                "sem_meta": sum(1 for r in linhas if not r["tem_meta"]),
                "atingimento": _div(sum(min(r["total"]["pct"] or 0, 1.5) for r in com_meta), len(com_meta)),
            },
        }

    # --- catálogos para a página Configurações ---------------------------------------------
    def catalogo(self) -> dict:
        regras = self.regras()
        hoje = self.cache.data_ref() or dt.date.today()
        desde = (hoje.replace(day=1) - dt.timedelta(days=365)).replace(day=1)
        vendidos = {pid: (v, q) for pid, v, q in self.cache.consulta(
            "SELECT id_produto, SUM(valor), SUM(quantidade) FROM vendas_itens WHERE data >= ? GROUP BY 1", [desde])}
        ids = set(vendidos) | {int(k) for k in regras.cfg["produtos"]} | {m["id_produto"] for m in self.metas_produtos.dados()}
        ids -= set(regras.equivalentes)  # produtos substituídos aparecem pelo equivalente
        produtos = []
        if ids:
            marcas = ",".join("?" * len(ids))
            for pid, nome, id_linha, linha, unidade, inativo in self.cache.consulta(
                    f"SELECT id, nome, id_linha, linha, unidade, inativo FROM produtos WHERE id IN ({marcas})", sorted(ids)):
                v, q = vendidos.get(pid, (0.0, 0.0))
                for antigo, novo in regras.equivalentes.items():
                    if novo == pid and antigo in vendidos:
                        v += vendidos[antigo][0]
                        q += vendidos[antigo][1]
                regra = regras.cfg["produtos"].get(str(pid))
                produtos.append({
                    "id": pid, "nome": nome, "id_linha": id_linha, "linha": linha or "", "unidade": unidade or "",
                    "inativo": bool(inativo), "vendido_12m": round(v, 2), "quantidade_12m": round(q, 2),
                    "grupo": regras.grupo_produto(pid), "categoria": regras.categoria(pid),
                    "configurado": regra is not None,
                })
        produtos.sort(key=lambda p: -p["vendido_12m"])

        valores_motivo = {m: (v, n) for m, v, n in self.cache.consulta(
            "SELECT id_motivo, SUM(valor), COUNT(*) FROM devolucoes_itens WHERE data >= ? AND NOT cancelada GROUP BY 1", [desde])}
        motivos = [{"id": mid, "nome": nome, "valor_12m": round(valores_motivo.get(mid, (0, 0))[0], 2)}
                   for mid, nome in sorted(self.cache.consulta("SELECT id, nome FROM motivos"))]
        return {"produtos": produtos, "vendedores": self.vendedores_catalogo(regras), "motivos": motivos,
                "desde": desde.isoformat()}

    def vendedores_catalogo(self, regras: Regras | None = None) -> list[dict]:
        """Vendedores das planilhas de metas com o cadastro do ERP; os sem meta há mais de 2 meses vão para o fim."""
        regras = regras or self.regras()
        hoje = self.cache.data_ref() or dt.date.today()
        nomes_erp = {r[0]: r[1:] for r in self.cache.consulta("SELECT id, nome, id_supervisor, supervisor, inativo FROM vendedores")}
        ultimos: dict[int, tuple[dt.date, str]] = {}
        for m in self.metas.dados() + self.metas_produtos.dados():
            if m["id_vendedor"] not in ultimos or m["mes"] >= ultimos[m["id_vendedor"]][0]:
                ultimos[m["id_vendedor"]] = (m["mes"], m["vendedor"])
        vendedores = []
        for vid, (mes, nome) in ultimos.items():
            erp = nomes_erp.get(vid, ("", None, "", 0))
            vendedores.append({
                "id": vid, "nome": nome_bonito(nome), "nome_erp": erp[0], "supervisor": erp[2] or "",
                "inativo": bool(erp[3]), "ultimo_mes": mes.isoformat(), "grupo": regras.grupo_vendedor(vid),
                "configurado": vid in regras.vendedores,
            })
        vendedores.sort(key=lambda v: (v["ultimo_mes"] < (hoje.replace(day=1) - dt.timedelta(days=62)).isoformat(), v["nome"]))
        return vendedores

    def calendario_ano(self, ano: int, cfg: dict | None = None) -> dict:
        regras_cfg = cfg or self.configuracao.atual()
        cal = Calendario(regras_cfg["calendario"]["extras"], regras_cfg["calendario"]["sabado"])
        meses = []
        for mes in range(1, 13):
            meses.append({"mes": mes, **{r: sum(d["peso"] for d in cal.dias_do_mes(ano, mes, r)) for r in ("ES", "BA")}})
        return {"ano": ano, "feriados": feriados_do_ano(ano), "meses": meses}

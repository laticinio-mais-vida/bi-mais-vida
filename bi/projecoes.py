"""Projeção do faturamento bruto dos próximos meses (página Projeções).

Base: vendas válidas (vendas_itens, sem as canceladas) SEM descontar devoluções, com as equivalências de produto,
sem os produtos marcados como "não conta" e só com os vendedores da página (config_projecoes.json: as equipes
ES, BA e Edir, menos os desmarcados, mais os incluídos à mão). Cada mês vira R$ por dia útil
(calendário de ES e BA, com os feriados e extras das Configurações), para meses curtos ou com feriado não
parecerem queda de venda.

Método (escolhido por backtest com o histórico de 2024 a 2026; os números estão no README):
- modelo = média de dois métodos simples, em R$ por dia útil:
  (a) mesmo mês do ano anterior × crescimento (média dos últimos 12 meses ÷ média dos 12 anteriores);
  (b) tendência dos últimos 12 meses sem a sazonalidade, amortecida, × fator sazonal do mês;
- com filtro de vendedor ou produto: média entre o modelo aplicado à série filtrada e a projeção do total ×
  participação do filtro nos últimos 6 meses (só a participação quando o filtro não tem 24 meses de vendas);
- faixa: erro médio que o próprio método teve, para o mesmo filtro, refazendo as projeções dos últimos 12 meses
  só com o que se sabia antes de cada um (por distância: 1 mês à frente, 2 meses à frente...);
- mês em andamento: realizado + fechamento pelo ritmo (realizado ÷ dias úteis passados × dias úteis do mês).
"""
from __future__ import annotations

import calendar
import copy
import datetime as dt
import json
import os
import threading
from collections import defaultdict
from pathlib import Path

import numpy as np

from .calendario import REGIOES
from .configuracao import SUPERVISOR_GRUPO
from .metas import MESES, Calculadora, nome_bonito

HORIZONTE = 6            # meses projetados depois do mês em andamento
JANELA_TENDENCIA = 12    # meses da reta de tendência
AMORTECIMENTO = 0.8      # a inclinação da tendência perde 20% a cada mês à frente
JANELA_PARTICIPACAO = 6  # meses usados na participação do filtro no total
MESES_MODELO = 24        # meses seguidos com venda para o filtro ter o modelo próprio
ORIGENS_TESTE = 12       # quantos meses passados são refeitos para medir o erro
SERIES = ("mus", "mix")
EQUIPES = ("ES", "BA", "EDIR")       # entram na página sozinhas (vendedor novo também)
ORDEM_EQUIPES = (*EQUIPES, "OCULTO")
REGIAO_EQUIPE = {"ES": "ES", "BA": "BA", "EDIR": "BA"}
NOME_EQUIPE = {"ES": "ES", "BA": "BA", "EDIR": "Edir", "OCULTO": "Outros"}


class SemVendedores(Exception):
    """O acesso do usuário não tem nenhum vendedor da página."""


class ConfigProjecoes:
    """Vendedores da página Projeções, gravados em config_projecoes.json pela configuração da página.

    Sem o arquivo, entram os vendedores das equipes ES, BA e Edir (as de Configurações das metas). `excluir` tira
    vendedores dessas equipes (ex.: contas internas) e `incluir` traz vendedores de fora delas. Vendedor novo das
    equipes entra sozinho, para a projeção não perder faturamento sem ninguém perceber.
    """

    def __init__(self, arquivo: str | Path):
        self.arquivo = Path(arquivo)
        self._trava = threading.Lock()
        self._cfg = {"versao": 1, "incluir": [], "excluir": []}
        if self.arquivo.exists():
            self._cfg = self._valida(json.loads(self.arquivo.read_text(encoding="utf-8")))

    @staticmethod
    def _valida(cfg: dict) -> dict:
        incluir = sorted({int(v) for v in cfg.get("incluir") or []})
        excluir = sorted({int(v) for v in cfg.get("excluir") or []})
        if set(incluir) & set(excluir):
            raise ValueError("um vendedor não pode estar ao mesmo tempo incluído e excluído")
        return {"versao": 1, "incluir": incluir, "excluir": excluir}

    def atual(self) -> dict:
        with self._trava:
            return copy.deepcopy(self._cfg)

    def salvar(self, novo: dict) -> dict:
        cfg = self._valida(novo)
        with self._trava:
            if self.arquivo.exists():
                anterior = self.arquivo.with_name(self.arquivo.stem + ".anterior.json")
                anterior.write_text(self.arquivo.read_text(encoding="utf-8"), encoding="utf-8")
            tmp = self.arquivo.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.arquivo)
            self._cfg = cfg
        return copy.deepcopy(cfg)

    @staticmethod
    def na_pagina(cfg: dict, vid: int, equipe: str) -> bool:
        return vid in cfg["incluir"] or (equipe in EQUIPES and vid not in cfg["excluir"])


# --- modelo (funções puras sobre séries mensais) --------------------------------------------
def fatores_sazonais(r: np.ndarray, mes_cal: np.ndarray) -> np.ndarray:
    """Quanto cada mês do ano (índice 0 = janeiro) costuma ficar acima ou abaixo da tendência; média 1."""
    if len(r) < 12:
        return np.ones(12)
    t = np.arange(len(r))
    tendencia = np.polyval(np.polyfit(t, r, 1), t)
    razao = np.full(len(r), np.nan)
    ok = tendencia > 0
    razao[ok] = r[ok] / tendencia[ok]
    fatores = np.ones(12)
    for m in range(1, 13):
        valores = razao[(mes_cal == m) & np.isfinite(razao)]
        if len(valores):
            fatores[m - 1] = valores.mean()
    fatores = np.where(fatores > 0, fatores, 1.0)
    return fatores / fatores.mean()


def por_tendencia(r: np.ndarray, mes_cal: np.ndarray, mes_fut: np.ndarray) -> np.ndarray:
    """R$/dia útil futuro = reta dos últimos meses (sem sazonalidade, amortecida) × fator do mês."""
    fatores = fatores_sazonais(r, mes_cal)
    sem_sazonal = r / fatores[mes_cal - 1]
    janela = sem_sazonal[-JANELA_TENDENCIA:]
    if len(janela) >= 3:
        t = np.arange(len(janela))
        inclinacao, intercepto = np.polyfit(t, janela, 1)
        nivel = intercepto + inclinacao * t[-1]
    else:
        nivel, inclinacao = float(janela.mean()), 0.0
    saida, passos = [], 0.0
    for h, m in enumerate(mes_fut, 1):
        passos += AMORTECIMENTO ** h
        saida.append((nivel + inclinacao * passos) * fatores[m - 1])
    return np.array(saida)


def por_ano_anterior(r: np.ndarray, n_fut: int) -> np.ndarray:
    """R$/dia útil futuro = mesmo mês do ano anterior × crescimento dos últimos 12 meses (n_fut <= 12)."""
    crescimento = r[-12:].mean() / r[-24:-12].mean()
    return np.array([r[len(r) - 12 + h] * crescimento for h in range(n_fut)])


def modelo(y: np.ndarray, dias: np.ndarray, mes_cal: np.ndarray, dias_fut: np.ndarray,
           mes_fut: np.ndarray) -> np.ndarray:
    """Projeção em R$ dos meses seguintes à série mensal fechada `y`."""
    if len(y) == 0:
        return np.zeros(len(mes_fut))
    r = y / dias
    if len(r) >= 24 and r[-24:-12].mean() > 0:
        rf = (por_ano_anterior(r, len(mes_fut)) + por_tendencia(r, mes_cal, mes_fut)) / 2
    elif len(r) >= 3:
        rf = por_tendencia(r, mes_cal, mes_fut)
    else:
        rf = np.full(len(mes_fut), r.mean())
    return np.maximum(rf, 0.0) * dias_fut


# --- página ---------------------------------------------------------------------------------
def _rotulo(ano: int, mes: int) -> str:
    return f"{MESES[mes - 1][:3]}/{str(ano)[2:]}"


class Projetor:
    def __init__(self, calc: Calculadora, config: ConfigProjecoes):
        self.calc = calc
        self.config = config
        self._trava = threading.Lock()
        self._linhas_cache: tuple = (None, [])

    def _linhas(self) -> list[tuple]:
        """(ano, mês, vendedor, produto, valor) do cache inteiro; só consulta de novo quando o cache muda."""
        cache = self.calc.cache
        carimbo = (cache.info.get("extraido_em"), cache.info.get("data_ref"))
        with self._trava:
            if self._linhas_cache[0] == carimbo:
                return self._linhas_cache[1]
        linhas = cache.consulta(
            "SELECT year(data), month(data), id_vendedor, id_produto, SUM(valor) FROM vendas_itens GROUP BY ALL")
        with self._trava:
            self._linhas_cache = (carimbo, linhas)
        return linhas

    def _nomes_vendedores(self) -> dict[int, str]:
        """Nome da planilha de metas mais recente; quem não está nela fica com o nome do ERP."""
        nomes = {vid: nome_bonito(n) for vid, n in self.calc.nomes_erp().items() if n}
        ultimo: dict[int, dt.date] = {}
        for m in self.calc.metas.dados() + self.calc.metas_produtos.dados():
            if m["id_vendedor"] not in ultimo or m["mes"] >= ultimo[m["id_vendedor"]]:
                ultimo[m["id_vendedor"]] = m["mes"]
                nomes[m["id_vendedor"]] = nome_bonito(m["vendedor"])
        return nomes

    def calcular(self, vendedores: list[int] | None = None, produtos: list[int] | None = None,
                 permitidos: set[int] | None = None, equipes: set[str] | None = None) -> dict:
        """vendedores/produtos: filtros (None = todos). permitidos/equipes: o que o usuário pode ver
        (None = sem limite além dos vendedores da página)."""
        if not self.calc.cache.pronto():
            raise RuntimeError("os dados ainda estão sendo preparados")
        regras = self.calc.regras()
        cfg = self.config.atual()
        cal = self.calc.calendario(regras)
        data_ref = self.calc.cache.data_ref()
        linhas = self._linhas()
        if not linhas:
            raise RuntimeError("o cache ainda não tem vendas")

        # --- linha do tempo: meses fechados, mês em andamento (se houver) e os meses projetados ---
        primeiro = min((a, m) for a, m, *_ in linhas)
        ultimo_dia = calendar.monthrange(data_ref.year, data_ref.month)[1]
        resta_dia_util = any(d["peso"] > 0 and d["data"] > data_ref
                             for r in REGIOES for d in cal.dias_do_mes(data_ref.year, data_ref.month, r))
        aberto = data_ref.day < ultimo_dia and resta_dia_util
        meses: list[tuple[int, int]] = []
        a, m = primeiro
        while (a, m) <= (data_ref.year, data_ref.month):
            meses.append((a, m))
            a, m = (a + 1, 1) if m == 12 else (a, m + 1)
        n_fechados = len(meses) - (1 if aberto else 0)
        n_dados = len(meses)
        for _ in range(HORIZONTE):
            meses.append((a, m))
            a, m = (a + 1, 1) if m == 12 else (a, m + 1)
        indice = {mes: i for i, mes in enumerate(meses[:n_dados])}
        mes_cal = np.array([m for _, m in meses])
        dias_regiao = {r: np.array([sum(d["peso"] for d in cal.dias_do_mes(a, m, r)) for a, m in meses]) for r in REGIOES}

        # --- vendas por vendedor e produto, só dos vendedores da página ---
        # O total da página é só a referência da participação. Para quem vê parte dos vendedores, o acesso
        # funciona como um filtro: a projeção de um vendedor é a mesma para ele e para o administrador.
        equipe_de: dict[int, str] = {}
        celulas: dict[tuple[int, int], np.ndarray] = defaultdict(lambda: np.zeros(n_dados))
        for a, m, vid, pid, valor in linhas:
            if vid not in equipe_de:
                equipe_de[vid] = regras.grupo_vendedor(vid)
            if not ConfigProjecoes.na_pagina(cfg, vid, equipe_de[vid]):
                continue
            p = regras.produto(pid)
            if regras.grupo_produto(p) == "fora":
                continue
            celulas[(vid, p)][indice[(a, m)]] += valor
        chaves = list(celulas)
        valores = np.array([celulas[k] for k in chaves]) if chaves else np.zeros((0, n_dados))
        vid_k = np.array([v for v, _ in chaves], dtype=int)
        pid_k = np.array([p for _, p in chaves], dtype=int)
        serie_k = np.array(["mus" if regras.grupo_produto(p) == "mussarela" else "mix" for p in pid_k])
        es_k = np.array([self._regiao(regras, v, equipe_de[v]) == "ES" for v in vid_k], dtype=bool)
        escopo_k = np.array([(equipes is None or equipe_de[v] in equipes) and (permitidos is None or v in permitidos)
                             for v in vid_k], dtype=bool)
        if not escopo_k.any():
            raise SemVendedores("Seu acesso ainda não tem vendedores nas Projeções. Fale com o administrador.")

        escopo_v = set(vid_k[escopo_k].tolist())
        sel_v = sorted(set(vendedores) & escopo_v) if vendedores else None
        if vendedores and not sel_v:
            raise ValueError("nenhum dos vendedores escolhidos está no seu acesso")
        sel_p = sorted(set(produtos)) if produtos else None
        filtrado = bool(sel_v or sel_p or not escopo_k.all())
        no_filtro = escopo_k.copy()
        if sel_v:
            no_filtro &= np.isin(vid_k, sel_v)
        if sel_p:
            no_filtro &= np.isin(pid_k, sel_p)

        ultimos12 = slice(max(0, n_fechados - 12), n_fechados)

        def dias_da(mascara: np.ndarray) -> np.ndarray:
            """Dias úteis ponderados pela venda de cada região na série (últimos 12 meses)."""
            tot = valores[mascara][:, ultimos12].sum()
            w = valores[mascara & es_k][:, ultimos12].sum() / tot if tot > 0 else 0.5
            return w * dias_regiao["ES"] + (1 - w) * dias_regiao["BA"]

        total = {s: valores[serie_k == s].sum(axis=0) for s in SERIES}
        fil = {s: valores[(serie_k == s) & no_filtro].sum(axis=0) for s in SERIES}
        dias_tot = {s: dias_da(serie_k == s) for s in SERIES}
        dias_fil = {s: dias_da((serie_k == s) & no_filtro) for s in SERIES}
        tem = {s: bool(((serie_k == s) & no_filtro).any() and fil[s][:n_dados].sum() > 0) for s in SERIES}

        def projetar(T: int, s: str, H: int) -> tuple[np.ndarray, np.ndarray, str]:
            """Com os T primeiros meses fechados: projeção do total e do filtro para os H meses seguintes."""
            fut = slice(T, T + H)
            pt = modelo(total[s][:T], dias_tot[s][:T], mes_cal[:T], dias_tot[s][fut], mes_cal[fut])
            if not filtrado:
                return pt, pt, "modelo"
            y = fil[s][:T]
            base = total[s][max(0, T - JANELA_PARTICIPACAO):T].sum()
            pp = pt * (y[-JANELA_PARTICIPACAO:].sum() / base if base > 0 else 0.0)
            if T >= MESES_MODELO and (y[-MESES_MODELO:] > 0).all():
                pm = modelo(y, dias_fil[s][:T], mes_cal[:T], dias_fil[s][fut], mes_cal[fut])
                return pt, (pm + pp) / 2, "combinado"
            return pt, pp, "participacao"

        # --- erro típico: refaz as projeções dos últimos meses só com o que se sabia antes ---
        h_total = (1 if aberto else 0) + HORIZONTE
        erros = {k: [[] for _ in range(h_total)] for k in (*SERIES, "fat")}
        erros_tot = {k: [[] for _ in range(h_total)] for k in (*SERIES, "fat")}
        for T in range(max(3, n_fechados - ORIGENS_TESTE), n_fechados):
            H = min(h_total, n_fechados - T)
            p = {s: projetar(T, s, H) for s in SERIES}
            for h in range(H):
                for alvo, pos, serie in ((erros, 1, fil), (erros_tot, 0, total)):
                    for s in SERIES:
                        real = serie[s][T + h]
                        if real > 0:
                            alvo[s][h].append(abs(p[s][pos][h] - real) / real)
                    real = serie["mus"][T + h] + serie["mix"][T + h]
                    if real > 0:
                        alvo["fat"][h].append(abs(p["mus"][pos][h] + p["mix"][pos][h] - real) / real)

        def erro_por_distancia(k: str) -> list[float]:
            saida, anterior = [], 0.0
            for h in range(h_total):
                if len(erros[k][h]) >= 3:
                    e = float(np.mean(erros[k][h]))
                elif erros_tot[k][h]:
                    e = 2 * float(np.mean(erros_tot[k][h]))  # sem histórico para medir: faixa mais larga
                else:
                    e = 0.25
                anterior = max(anterior, e)  # mais longe nunca fica mais certo que mais perto
                saida.append(anterior)
            return saida

        erro = {k: erro_por_distancia(k) for k in (*SERIES, "fat")}

        # --- projeção atual (com todos os meses fechados) ---
        atual = {s: projetar(n_fechados, s, h_total) for s in SERIES}
        proj = {s: atual[s][1] for s in SERIES}
        metodo = {s: (atual[s][2] if tem[s] else "vazio") for s in SERIES}
        avisos = []
        if any(metodo[s] == "participacao" for s in SERIES):
            avisos.append("Parte do filtro tem menos de 24 meses seguidos de vendas: a projeção dele usa a "
                          "participação nos últimos 6 meses sobre a projeção do total, e a faixa fica mais larga.")

        def faixa(valor: float, e: float) -> dict:
            return {"valor": round(valor, 2), "min": round(max(0.0, valor * (1 - e)), 2), "max": round(valor * (1 + e), 2)}

        def ano_anterior(i: int) -> dict:
            j = i - 12
            if j < 0 or j >= n_fechados:
                return {"mus": None, "mix": None, "fat": None}
            mus, mix = float(fil["mus"][j]), float(fil["mix"][j])
            return {"mus": round(mus, 2), "mix": round(mix, 2), "fat": round(mus + mix, 2)}

        dias_fat = dias_da(no_filtro)
        historico = [{
            "ano": a, "mes": m, "rotulo": _rotulo(a, m), "dias_uteis": round(float(dias_fat[i]), 1),
            "mus": round(float(fil["mus"][i]), 2), "mix": round(float(fil["mix"][i]), 2),
            "fat": round(float(fil["mus"][i] + fil["mix"][i]), 2), "ano_anterior": ano_anterior(i),
        } for i, (a, m) in enumerate(meses[:n_fechados])]

        mes_atual = None
        if aberto:
            i = n_fechados
            a, m = meses[i]
            decorridos = {r: cal.resumo(a, m, r, data_ref)["dias_decorridos"] for r in REGIOES}
            bloco = {"ano": a, "mes": m, "rotulo": _rotulo(a, m), "dias_uteis": round(float(dias_fat[i]), 1),
                     "ano_anterior": ano_anterior(i)}
            soma_fech = soma_min = soma_max = soma_real = 0.0
            for s in SERIES:
                real = float(fil[s][i])
                w_dias = float(dias_fil[s][i])
                tot_es = valores[(serie_k == s) & no_filtro & es_k][:, ultimos12].sum()
                tot_s = valores[(serie_k == s) & no_filtro][:, ultimos12].sum()
                w = float(tot_es / tot_s) if tot_s > 0 else 0.5
                passados = w * decorridos["ES"] + (1 - w) * decorridos["BA"]
                fech = real / passados * w_dias if passados > 0 else float(proj[s][0])
                fech = max(fech, real)
                resto = float((fech - real) * erro[s][0])  # só o que falta vender é incerto
                bloco[s] = {"realizado": round(real, 2), "valor": round(fech, 2), "min": round(fech - resto, 2),
                            "max": round(fech + resto, 2), "modelo": round(float(proj[s][0]), 2)}
                soma_fech += fech
                soma_real += real
                soma_min += fech - resto
                soma_max += fech + resto
            bloco["fat"] = {"realizado": round(soma_real, 2), "valor": round(soma_fech, 2),
                            "min": round(soma_min, 2), "max": round(soma_max, 2),
                            "modelo": round(float(proj["mus"][0] + proj["mix"][0]), 2)}
            bloco["dias_decorridos"] = round(float(sum(decorridos[r] for r in REGIOES) / len(REGIOES)), 1)
            mes_atual = bloco

        inicio_fut = 1 if aberto else 0
        projecao = []
        for k in range(HORIZONTE):
            i = n_dados + k
            h = inicio_fut + k
            a, m = meses[i]
            item = {"ano": a, "mes": m, "rotulo": _rotulo(a, m), "distancia": h + 1,
                    "dias_uteis": round(float(dias_fat[i]), 1), "ano_anterior": ano_anterior(i)}
            for s in SERIES:
                item[s] = faixa(float(proj[s][h]), erro[s][h])
            fat = float(proj["mus"][h] + proj["mix"][h])
            item["fat"] = faixa(fat, erro["fat"][h])
            projecao.append(item)

        resumo = {}
        for s in (*SERIES, "fat"):
            soma = sum(p[s]["valor"] for p in projecao)
            anterior = [p["ano_anterior"][s] for p in projecao]
            soma_ant = sum(anterior) if all(v is not None for v in anterior) else None
            resumo[s] = {
                "total": round(soma, 2),
                "min": round(sum(p[s]["min"] for p in projecao), 2),
                "max": round(sum(p[s]["max"] for p in projecao), 2),
                "media": round(soma / HORIZONTE, 2),
                "ano_anterior": round(soma_ant, 2) if soma_ant is not None else None,
                "variacao": (soma / soma_ant - 1) if soma_ant else None,
                "erro": float(np.mean(erro[s][inicio_fut:])),
                "erro_por_distancia": [round(e, 4) for e in erro[s]],
            }

        return {
            "data_ref": data_ref.isoformat(),
            "periodo": {"de": projecao[0]["rotulo"], "ate": projecao[-1]["rotulo"], "meses": HORIZONTE},
            "filtros": {"vendedores": sel_v or [], "produtos": sel_p or []},
            "opcoes": self._opcoes(regras, valores[escopo_k], vid_k[escopo_k], pid_k[escopo_k], equipe_de, n_dados,
                                   sel_v, sel_p),
            "historico": historico,
            "mes_atual": mes_atual,
            "projecao": projecao,
            "resumo": resumo,
            "metodo": metodo,
            "tem": tem,
            "avisos": avisos,
            "parametros": {"horizonte": HORIZONTE, "janela_tendencia": JANELA_TENDENCIA,
                           "amortecimento": AMORTECIMENTO, "janela_participacao": JANELA_PARTICIPACAO,
                           "meses_modelo": MESES_MODELO, "origens_teste": ORIGENS_TESTE,
                           "inicio": historico[0]["rotulo"] if historico else None},
        }

    def _opcoes(self, regras, valores, vid_k, pid_k, equipe_de, n_dados, sel_v, sel_p) -> dict:
        """Vendedores com venda nos últimos 6 meses e produtos com venda nos últimos 12 (mais os já marcados)."""
        recente_v = valores[:, max(0, n_dados - 6):].sum(axis=1)
        recente_p = valores[:, max(0, n_dados - 12):].sum(axis=1)
        vendidos_v = {int(v) for v, x in zip(vid_k, recente_v) if x > 0} | set(sel_v or [])
        venda_p: dict[int, float] = defaultdict(float)
        for p, x in zip(pid_k, recente_p):
            venda_p[int(p)] += float(x)
        vendidos_p = {p for p, x in venda_p.items() if x > 0} | (set(sel_p or []) & set(venda_p))

        nomes = self._nomes_vendedores()
        ordem = {e: i for i, e in enumerate(ORDEM_EQUIPES)}
        lista_v = sorted(({"id": v, "nome": nomes.get(v, f"Vendedor {v}"), "equipe": equipe_de[v],
                           "rotulo_equipe": NOME_EQUIPE[equipe_de[v]]} for v in vendidos_v),
                         key=lambda x: (ordem.get(x["equipe"], 9), x["nome"]))

        produtos_info = {}
        if vendidos_p:
            marcas = ",".join("?" * len(vendidos_p))
            produtos_info = {r[0]: r[1:] for r in self.calc.cache.consulta(
                f"SELECT id, nome, unidade FROM produtos WHERE id IN ({marcas})", sorted(vendidos_p))}
        categorias = regras.categorias
        lista_p = []
        for p in vendidos_p:
            nome, unidade = produtos_info.get(p, (f"Produto {p}", ""))
            grupo = "mussarela" if regras.grupo_produto(p) == "mussarela" else "mix"
            lista_p.append({"id": p, "nome": nome, "unidade": unidade or "", "grupo": grupo,
                            "categoria": regras.categoria(p) if grupo == "mix" else None,
                            "venda_12m": round(venda_p[p], 2)})
        ordem_cat = {c: i for i, c in enumerate(categorias)}
        lista_p.sort(key=lambda x: (x["grupo"] != "mussarela", ordem_cat.get(x["categoria"], len(categorias)),
                                    -x["venda_12m"]))
        return {"vendedores": lista_v, "produtos": lista_p, "categorias": categorias,
                "equipes": [{"id": e, "nome": NOME_EQUIPE[e]} for e in ORDEM_EQUIPES if any(v["equipe"] == e for v in lista_v)]}

    @staticmethod
    def _regiao(regras, vid: int, equipe: str) -> str:
        """Calendário do vendedor: o da equipe; vendedor de fora das equipes segue o supervisor do ERP."""
        return REGIAO_EQUIPE.get(equipe) or ("BA" if SUPERVISOR_GRUPO.get(regras.supervisores.get(vid)) == "BA" else "ES")

    # --- configuração da página ------------------------------------------------------------
    def catalogo(self) -> dict:
        """Todos os vendedores com venda no cache, para a configuração da página escolher quem entra."""
        if not self.calc.cache.pronto():
            raise RuntimeError("os dados ainda estão sendo preparados")
        regras = self.calc.regras()
        cfg = self.config.atual()
        cache = self.calc.cache
        data_ref = cache.data_ref()
        desde = (data_ref.replace(day=1) - dt.timedelta(days=365)).replace(day=1)
        fora = [pid for pid, r in regras.produtos.items() if r.get("grupo") == "fora"]
        sem_fora = f"AND id_produto NOT IN ({','.join('?' * len(fora))})" if fora else ""
        vendas = cache.consulta(
            f"SELECT id_vendedor, SUM(CASE WHEN data >= ? THEN valor ELSE 0 END), MAX(data) FROM vendas_itens "
            f"WHERE TRUE {sem_fora} GROUP BY 1", [desde, *fora])
        erp = {r[0]: r[1:] for r in cache.consulta("SELECT id, nome, supervisor, inativo FROM vendedores")}
        nomes = self._nomes_vendedores()
        ordem = {e: i for i, e in enumerate(ORDEM_EQUIPES)}
        lista = []
        for vid, venda, ultima in vendas:
            equipe = regras.grupo_vendedor(vid)
            nome_erp, supervisor, inativo = erp.get(vid, ("", "", 0))
            lista.append({
                "id": vid, "nome": nomes.get(vid, f"Vendedor {vid}"), "nome_erp": nome_erp or "",
                "equipe": equipe, "rotulo_equipe": NOME_EQUIPE.get(equipe, equipe), "supervisor": supervisor or "",
                "inativo": bool(inativo), "venda_12m": round(venda or 0.0, 2),
                "ultima_venda": ultima.isoformat() if ultima else None,
                "padrao": equipe in EQUIPES, "na_pagina": ConfigProjecoes.na_pagina(cfg, vid, equipe),
            })
        lista.sort(key=lambda v: (ordem.get(v["equipe"], 9), -v["venda_12m"], v["nome"]))
        return {"config": cfg, "vendedores": lista, "desde": desde.isoformat(), "data_ref": data_ref.isoformat(),
                "equipes": [{"id": e, "nome": NOME_EQUIPE[e], "padrao": e in EQUIPES} for e in ORDEM_EQUIPES]}

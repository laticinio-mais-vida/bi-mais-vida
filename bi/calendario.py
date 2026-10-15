"""Dias úteis por região (ES e BA), descontando feriados.

Os feriados automáticos foram conferidos com as vendas de 2025 e 2026 (dias sem venda na região):
- os dois estados param no Carnaval (terça), na Sexta-feira Santa e nos feriados nacionais;
- só o ES para na segunda de Carnaval, na Segunda da Penha e em Corpus Christi;
- só a BA para no 2 de Julho.
Feriados locais, pontos facultativos e exceções entram como "extras" na página Configurações
(peso 0 = sem expediente, 0,5 = meio expediente, 1 = dia normal mesmo sendo feriado).
"""
from __future__ import annotations

import calendar
import datetime as dt
from functools import lru_cache

REGIOES = ("ES", "BA")
UM_DIA = dt.timedelta(days=1)


def pascoa(ano: int) -> dt.date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(ano, mes, dia)


@lru_cache(maxsize=None)
def feriados_automaticos(ano: int) -> tuple[tuple[dt.date, str, frozenset], ...]:
    """(data, nome, regiões que param) de cada feriado automático do ano."""
    p = pascoa(ano)
    ambos = frozenset(REGIOES)
    lista = [
        (dt.date(ano, 1, 1), "Confraternização Universal", ambos),
        (p - dt.timedelta(days=48), "Carnaval (segunda)", frozenset({"ES"})),
        (p - dt.timedelta(days=47), "Carnaval (terça)", ambos),
        (p - dt.timedelta(days=2), "Sexta-feira Santa", ambos),
        (p + dt.timedelta(days=8), "Nossa Senhora da Penha", frozenset({"ES"})),
        (dt.date(ano, 4, 21), "Tiradentes", ambos),
        (dt.date(ano, 5, 1), "Dia do Trabalho", ambos),
        (p + dt.timedelta(days=60), "Corpus Christi", frozenset({"ES"})),
        (dt.date(ano, 7, 2), "Independência da Bahia", frozenset({"BA"})),
        (dt.date(ano, 9, 7), "Independência do Brasil", ambos),
        (dt.date(ano, 10, 12), "Nossa Senhora Aparecida", ambos),
        (dt.date(ano, 11, 2), "Finados", ambos),
        (dt.date(ano, 11, 15), "Proclamação da República", ambos),
        (dt.date(ano, 12, 25), "Natal", ambos),
    ]
    if ano >= 2024:
        lista.append((dt.date(ano, 11, 20), "Consciência Negra", ambos))
    return tuple(sorted(lista))


class Calendario:
    def __init__(self, extras: list[dict] | None = None, peso_sabado: dict[str, float] | None = None):
        # extras: [{"data": "2026-12-24", "regiao": "TODAS"|"ES"|"BA", "peso": 0.5, "descricao": "..."}]
        self.extras: dict[tuple[dt.date, str], tuple[float, str]] = {}
        for e in extras or []:
            data = dt.date.fromisoformat(str(e["data"]))
            regioes = REGIOES if e.get("regiao", "TODAS") == "TODAS" else (e["regiao"],)
            for r in regioes:
                self.extras[(data, r)] = (float(e.get("peso", 0)), e.get("descricao") or "Feriado local")
        self.peso_sabado = {r: float((peso_sabado or {}).get(r, 0)) for r in REGIOES}

    def _feriado(self, dia: dt.date, regiao: str) -> str | None:
        for data, nome, regioes in feriados_automaticos(dia.year):
            if data == dia and regiao in regioes:
                return nome
        return None

    def dia(self, dia: dt.date, regiao: str) -> dict:
        """Peso do dia (0 a 1) e o motivo, para a região."""
        if (dia, regiao) in self.extras:
            peso, descricao = self.extras[(dia, regiao)]
            tipo = "util" if peso >= 1 else ("meio" if peso > 0 else "feriado")
            return {"peso": peso, "tipo": tipo, "motivo": descricao}
        if dia.weekday() == 6:
            return {"peso": 0.0, "tipo": "fds", "motivo": "Domingo"}
        nome = self._feriado(dia, regiao)
        if nome:
            return {"peso": 0.0, "tipo": "feriado", "motivo": nome}
        if dia.weekday() == 5:
            peso = self.peso_sabado[regiao]
            return {"peso": peso, "tipo": "sabado" if peso else "fds", "motivo": "Sábado"}
        return {"peso": 1.0, "tipo": "util", "motivo": None}

    def dias_do_mes(self, ano: int, mes: int, regiao: str) -> list[dict]:
        _, n = calendar.monthrange(ano, mes)
        return [{"data": dt.date(ano, mes, d), **self.dia(dt.date(ano, mes, d), regiao)} for d in range(1, n + 1)]

    def resumo(self, ano: int, mes: int, regiao: str, data_ref: dt.date) -> dict:
        """Dias úteis do mês, quantos já passaram até `data_ref` (inclusive) e o ritmo esperado."""
        dias = self.dias_do_mes(ano, mes, regiao)
        total = sum(d["peso"] for d in dias)
        decorridos = sum(d["peso"] for d in dias if d["data"] <= data_ref)
        inicio, fim = dias[0]["data"], dias[-1]["data"]
        situacao = "fechado" if data_ref >= fim else ("futuro" if data_ref < inicio else "aberto")
        return {
            "regiao": regiao,
            "dias_uteis": total,
            "dias_decorridos": decorridos,
            "dias_restantes": total - decorridos,
            "ritmo": (decorridos / total) if total else 0.0,
            "situacao": situacao,
            "dias": [{**d, "data": d["data"].isoformat(), "passou": d["data"] <= data_ref} for d in dias],
        }

    def ritmo_ate(self, ano: int, mes: int, regiao: str) -> list[tuple[dt.date, float]]:
        """Fração acumulada de dias úteis em cada dia do mês (para a linha de ritmo ideal)."""
        dias = self.dias_do_mes(ano, mes, regiao)
        total = sum(d["peso"] for d in dias) or 1.0
        acumulado, saida = 0.0, []
        for d in dias:
            acumulado += d["peso"]
            saida.append((d["data"], acumulado / total))
        return saida


def feriados_do_ano(ano: int) -> list[dict]:
    return [{"data": d.isoformat(), "nome": n, "regioes": sorted(r)} for d, n, r in feriados_automaticos(ano)]

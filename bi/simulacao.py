"""A simulação da expectativa diária de um vendedor (python app.py --simular VENDEDOR --meta 100000): o texto que
sai no terminal e a planilha .xlsx para conferir a conta à mão. As contas são de bi/desempenho.py (Painel.simular)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

SEMANA = {1: "seg", 2: "ter", 3: "qua", 4: "qui", 5: "sex", 6: "sáb", 7: "dom"}
MODO = {"saldo": "parte do saldo", "nao_atende": "não atende neste dia", "potencial": "potencial normal (caminho B)", "meta_batida": "meta batida: potencial",
        "sem_rota": "sem rota pela frente: saldo pelos dias úteis", "sem_meta": "sem meta"}


def _reais(v) -> str:
    if v is None:
        return "—"
    return ("R$ " + f"{v:,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")


def _como(d: dict) -> str:
    modo = "nao_atende" if d["modo"] == "saldo" and not d["meta"] else d["modo"]
    return MODO.get(modo, modo)


def _data(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day:02d}/{d.month:02d} {SEMANA[d.isoweekday()]}"


def texto(r: dict) -> str:
    """O resumo, os dias com movimento ou meta e os 10 clientes de maior potencial."""
    v = r["vendedor"]
    linhas = [
        f"Simulação da meta de venda diária — {v['nome']} (código {v['id']}, {v['regiao']}), {r['mes'][5:7]}/{r['mes'][:4]}",
        f"Hoje: {dt.date.fromisoformat(r['hoje']):%d/%m/%Y} · dados até {r['data_ref'] or '—'}",
        f"Meta do mês: {_reais(r['meta'])}" + (f" (na planilha: {_reais(r['meta_planilha'])})"
                                                if r["meta_planilha"] not in (None, r["meta"]) else ""),
        f"  mussarela {_reais(r['meta_mus'])} · outras linhas {_reais(r['meta_out'])} · regime {v['regime']}",
        f"Faturado no mês até ontem: {_reais(r['faturado_ate_hoje'])}"
        + (f" (real: {_reais(r['faturado_real'])})" if r["faturado_real"] != r["faturado_ate_hoje"] else ""),
        f"Pedidos em aberto hoje (menos de 8 dias): {_reais(r['abertos_hoje'])}",
        f"Saldo hoje: {_reais(r['saldo_hoje'])}",
        f"Potencial do mês: {_reais(r['potencial_mes'])} · {r['clientes_programados']} clientes com dia de atendimento"
        + (f" · {r['sem_programacao']} sem dia" if r["sem_programacao"] else ""),
        "",
        f"{'Dia':<11}{'Clientes':>9}{'Potencial':>15}{'Faturado antes':>17}{'Em aberto':>14}{'Saldo':>15}"
        f"{'Meta do dia':>15}{'Realizado':>15}  Como",
    ]
    passado = projecao = real = 0.0
    for d in r["dias"]:
        if d["projecao"]:
            projecao += d["meta"] or 0.0
        else:
            passado += d["meta"] or 0.0
        real += d["real"] or 0.0
        if not (d["meta"] or d["potencial"] or d["real"] or d["util"]):
            continue
        marca = "*" if d["projecao"] else " "
        linhas.append(f"{_data(d['data']):<10}{marca}{d['clientes']:>9}{_reais(d['potencial']):>15}"
                      f"{_reais(d['faturado']):>17}{_reais(d['abertos']):>14}{_reais(d['saldo']):>15}"
                      f"{_reais(d['meta']):>15}{_reais(d['real']):>15}  {_como(d)}")
    linhas += ["* projeção: de hoje em diante, supondo que ele venda exatamente a meta de cada dia",
               f"Soma das metas dos dias que passaram: {_reais(passado)} · realizado no mês: {_reais(real)}",
               f"Soma da projeção de hoje em diante: {_reais(projecao)} (com saldo, é o saldo de hoje; mais que ele "
               "quando o potencial normal de algum dia passa da parte dele)", "",
               "Clientes de maior potencial (média dos 2 meses fechados antes do mês):"]
    for c in r["clientes"][:10]:
        rep = (f"{c['representatividade'] * 100:.2f}%".replace(".", ",") if c["representatividade"] is not None
               else "sem dia")
        linhas.append(f"  {c['id']:>7} {c['nome'][:38]:<38} {_reais(c['potencial']):>14} {rep:>8} "
                      f"{len(c['dias']):>2} dias · {_reais(c['por_dia'])} por dia")
    for a in r["avisos"]:
        linhas.append(f"Aviso: {a}")
    return "\n".join(linhas)


def gravar_planilha(r: dict, caminho: str | Path) -> Path:
    """A planilha com três abas: Resumo, Dias (cada dia do mês) e Clientes (o potencial e a representatividade)."""
    import xlsxwriter

    caminho = Path(caminho)
    wb = xlsxwriter.Workbook(str(caminho))
    neg = wb.add_format({"bold": True})
    rs = wb.add_format({"num_format": "R$ #,##0.00"})
    pct = wb.add_format({"num_format": "0.00%"})
    data = wb.add_format({"num_format": "dd/mm/yyyy"})
    cinza = wb.add_format({"font_color": "#77839A", "italic": True})
    v = r["vendedor"]

    ws = wb.add_worksheet("Resumo")
    resumo = [("Vendedor", f"{v['nome']} (código {v['id']}, {v['regiao']})"), ("Mês", r["mes"][:7]),
              ("Hoje", r["hoje"]), ("Dados até", r["data_ref"] or ""), ("Meta do mês", r["meta"]),
              ("Meta na planilha", r["meta_planilha"]), ("Meta de mussarela", r["meta_mus"]),
              ("Meta de outras linhas", r["meta_out"]), ("Regime", v["regime"]),
              ("Faturado no mês até ontem", r["faturado_ate_hoje"]), ("Faturado real até ontem", r["faturado_real"]),
              ("Pedidos em aberto hoje", r["abertos_hoje"]), ("Saldo hoje", r["saldo_hoje"]),
              ("Potencial do mês", r["potencial_mes"]), ("Clientes com dia de atendimento", r["clientes_programados"]),
              ("Clientes sem dia", r["sem_programacao"])]
    for i, (rotulo, valor) in enumerate(resumo):
        ws.write(i, 0, rotulo, neg)
        ws.write(i, 1, valor, rs if isinstance(valor, float) else None)
    ws.write(len(resumo) + 1, 0, "Expectativa do dia: saldo = meta − faturado até a véspera − pedidos em aberto de menos "
             "de 8 dias; com saldo, a parte do dia pelo potencial dele entre os dias que restam, nunca abaixo do "
             "potencial normal; com a meta batida, o potencial normal.", cinza)
    ws.set_column(0, 0, 32)
    ws.set_column(1, 1, 40)

    ws = wb.add_worksheet("Dias")
    cab = ["Dia", "Semana", "Dia útil", "Clientes programados", "Potencial do dia", "Faturado antes", "Pedidos em aberto",
           "Saldo", "Meta do dia", "Meta mussarela", "Meta outras", "Realizado", "Projeção", "Como"]
    ws.write_row(0, 0, cab, neg)
    for i, d in enumerate(r["dias"], start=1):
        ws.write_datetime(i, 0, dt.datetime.fromisoformat(d["data"]), data)
        ws.write(i, 1, SEMANA[d["dia_semana"]])
        ws.write(i, 2, d["util"])
        ws.write(i, 3, d["clientes"])
        for j, k in enumerate(("potencial", "faturado", "abertos", "saldo", "meta", "meta_mus", "meta_out", "real"), 4):
            if d[k] is not None:
                ws.write_number(i, j, d[k], rs)
        ws.write(i, 12, "sim" if d["projecao"] else "não")
        ws.write(i, 13, _como(d))
    fim = len(r["dias"]) + 1
    ws.write(fim, 0, "Metas dos dias que passaram", neg)
    ws.write_formula(fim, 8, f'=SUMIF(M2:M{fim},"não",I2:I{fim})', rs)
    ws.write(fim + 1, 0, "Projeção de hoje em diante", neg)
    ws.write_formula(fim + 1, 8, f'=SUMIF(M2:M{fim},"sim",I2:I{fim})', rs)
    ws.write(fim + 2, 0, "Realizado no mês", neg)
    ws.write_formula(fim + 2, 11, f"=SUM(L2:L{fim})", rs)
    ws.set_column(0, 0, 12)
    ws.set_column(1, 12, 15)
    ws.set_column(13, 13, 40)
    ws.freeze_panes(1, 1)

    ws = wb.add_worksheet("Clientes")
    ws.write_row(0, 0, ["Código", "Cliente", "Área", "Potencial do mês", "Representatividade", "Dias de atendimento",
                        "Potencial por dia", "Dias"], neg)
    for i, c in enumerate(r["clientes"], start=1):
        ws.write(i, 0, c["id"])
        ws.write(i, 1, c["nome"])
        ws.write(i, 2, c["area"])
        ws.write_number(i, 3, c["potencial"] or 0.0, rs)
        if c["representatividade"] is not None:
            ws.write_number(i, 4, c["representatividade"], pct)
        ws.write(i, 5, len(c["dias"]))
        ws.write_number(i, 6, c["por_dia"] or 0.0, rs)
        ws.write(i, 7, ", ".join(_data(x)[:5] for x in c["dias"]))
    ws.set_column(1, 2, 34)
    ws.set_column(3, 7, 16)
    ws.freeze_panes(1, 0)
    wb.close()
    return caminho

"""Reanálises de crédito (página Reavaliação de Crédito): quem analisa o crédito de um cliente registra o limite e o
prazo que liberou e a justificativa, e o painel grava junto o retrato do cliente naquele momento (Credito.retrato,
calculado aqui a partir do cache: a página não manda números). Com algumas centenas de registros, vira a base para uma
IA ajudar nas decisões; o Assistente já lê, com a ferramenta reanalises_credito (para_ia).

- Cada registro é uma linha nova na tabela credito_reanalises (migração 029) e não muda depois. Um engano se corrige
  excluindo (quem registrou ou um administrador) e registrando de novo: a excluída sai da página e do Assistente, mas
  fica guardada (excluida_em).
- Só no site (ativo): o banco do PC é outro, e as reanálises ficam num lugar só. No PC a página avisa e não grava.
- O retrato tem de ser o que a pessoa viu: se chegou uma extração nova entre analisar e registrar, o registro é
  recusado e a página refaz o parecer.
- O que aconteceu depois não é gravado: sai dos títulos emitidos depois do registro (Credito.depois), na hora.
"""
from __future__ import annotations

import datetime as dt
import json
import math

from .acesso import eh_admin
from .banco import hora, inicio_do_dia
from .conversas import NaoEncontrada, id_valido, novo_id
from .credito import Credito, dias_prazo, perfil_do_retrato

AVISO_PC = ("As reanálises ficam no site (bi.maisvida.cloud), para ficarem todas num lugar só: registre e consulte "
            "por lá.")
DADOS_NOVOS = ("os dados do cliente foram atualizados enquanto você analisava: confira o parecer de novo antes de "
               "registrar")
MIN_JUSTIFICATIVA = 10
MAX_JUSTIFICATIVA = 2000
MAX_LIMITE = 100_000_000  # R$: acima disso é engano de digitação
MAX_LISTA = 100  # reanálises de um cliente na página
MAX_IA = 15  # reanálises que a ferramenta do Assistente devolve de uma vez
JUSTIFICATIVA_IA = 400  # caracteres da justificativa que vão para a IA
PARECERES = {"indicado": "Indicado", "ressalvas": "Indicado com ressalvas", "nao_indicado": "Não indicado"}
# As reanálises parecidas: chave do perfil (perfil_do_retrato) -> (como comparar, a diferença que conta 1).
COMPARAR = {
    "pontualidade_12m": ("fracao", 0.15),        # 15 pontos percentuais
    "compras_mes_12m": ("reais", 0.5),           # em log10: uns 3 vezes mais
    "maior_saldo_12m": ("reais", 0.5),
    "meses_cliente": ("meses", 24),              # 2 anos (acima de 10 anos de cliente, tanto faz)
    "pedido_vezes_maior_saldo": ("razao", 0.3),  # em log10: 2 vezes mais; só quando os dois têm
}
INADIMPLENTE = 2  # a diferença entre um inadimplente e quem não é
CAMPOS = ("id", "id_cliente", "cliente", "limite_antes", "prazo_antes", "limite_pedido", "limite_liberado",
          "prazo_liberado", "justificativa", "parecer", "parecer_liberado", "limite_sugerido", "dados_ate", "retrato",
          "feita_em", "feita_por", "feita_por_nome")
_VALORES = ("limite_antes", "limite_pedido", "limite_liberado", "limite_sugerido")


def _cliente(valor) -> int:
    try:
        cliente = int(valor)
    except (TypeError, ValueError):
        raise ValueError("escolha um cliente") from None
    if cliente <= 0:
        raise ValueError("escolha um cliente")
    return cliente


def _reais(valor, erro: str, zero: bool) -> float:
    """Um valor em R$ que veio da página: número, sem passar de MAX_LIMITE; zero só se zero (o limite liberado)."""
    try:
        v = float(valor) if not isinstance(valor, bool) else math.nan
    except (TypeError, ValueError):
        v = math.nan
    if not math.isfinite(v) or v < 0 or (v == 0 and not zero) or v > MAX_LIMITE:
        raise ValueError(erro)
    return round(v, 2)


def _mes(texto) -> dt.date:
    try:
        ano, mes = str(texto).strip().split("-")[:2]
        return dt.date(int(ano), int(mes), 1)
    except (TypeError, ValueError):
        raise ValueError(f"mes deve ser AAAA-MM (veio {texto!r})") from None


def _linha(r) -> dict:
    d = dict(zip(CAMPOS, r))
    for k in _VALORES:
        d[k] = None if d[k] is None else float(d[k])
    return d


def decisao(antes: float, liberado: float, prazo_antes: str | None, prazo_liberado: str) -> dict:
    """O tipo da decisão: o limite (primeiro_limite, aumentou, manteve, reduziu, cortou) e o prazo (definiu, aumentou,
    manteve, diminuiu ou mudou, pelo maior dia dele: "07 E 14 DIAS" vale 14)."""
    if antes <= 0 < liberado:
        limite = "primeiro_limite"
    elif liberado <= 0 < antes:
        limite = "cortou"
    else:
        limite = "aumentou" if liberado > antes else "reduziu" if liberado < antes else "manteve"
    if prazo_antes == prazo_liberado:
        prazo = "manteve"
    elif not prazo_antes:
        prazo = "definiu"
    else:
        a, b = max(dias_prazo(prazo_antes) or [0]), max(dias_prazo(prazo_liberado) or [0])
        prazo = "aumentou" if b > a else "diminuiu" if b < a else "mudou"
    return {"limite": limite, "prazo": prazo, "variacao_limite": liberado / antes - 1 if antes > 0 else None}


def distancia(a: dict, b: dict) -> float:
    """Quão diferentes são dois perfis (Credito.perfil de hoje e perfil_do_retrato de uma reanálise): a diferença de
    cada número de COMPARAR na sua escala (R$ e razões em log10: 10 vezes mais pesa igual em qualquer faixa), mais
    INADIMPLENTE quando só um dos dois deve título vencido há mais de 7 dias. Número que falta em um só conta 1 (o
    pedido ÷ maior saldo, nada: ele só entra quando os dois têm)."""
    soma = 0.0
    for chave, (tipo, escala) in COMPARAR.items():
        x, y = a.get(chave), b.get(chave)
        if x is None or y is None:
            soma += 0.0 if (x is None and y is None) or tipo == "razao" else 1.0
            continue
        if tipo == "reais":
            x, y = math.log10(max(x, 0) + 1), math.log10(max(y, 0) + 1)
        elif tipo == "razao":
            x, y = math.log10(max(x, 0.01)), math.log10(max(y, 0.01))
        elif tipo == "meses":
            x, y = min(x, 120), min(y, 120)
        soma += ((x - y) / escala) ** 2
    if ((a.get("inadimplencia") or 0) > 0) != ((b.get("inadimplencia") or 0) > 0):
        soma += INADIMPLENTE ** 2
    return math.sqrt(soma)


def _resumo(lista: list[dict]) -> dict:
    """Quantas reanálises, por parecer da regra para o pedido, e quantas liberaram mais, o mesmo ou menos que o pedido."""
    por: dict[str, dict] = {}
    for d in lista:
        x = por.setdefault(PARECERES[d["parecer"]], {"reanalises": 0, "liberou_mais_que_o_pedido": 0,
                                                     "liberou_o_pedido": 0, "liberou_menos_que_o_pedido": 0})
        x["reanalises"] += 1
        diferenca = d["limite_liberado"] - d["limite_pedido"]
        x["liberou_mais_que_o_pedido" if diferenca > 0.005 else "liberou_menos_que_o_pedido" if diferenca < -0.005
          else "liberou_o_pedido"] += 1
    return {"reanalises": len(lista), "por_parecer_da_regra": por}


def _cortar(texto: str, n: int) -> str:
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


class Reanalises:
    """As reanálises de crédito, na tabela credito_reanalises. ativo: o site, que grava e lê; no PC (False) a página só
    avisa que elas ficam no site."""

    def __init__(self, banco, credito: Credito, ativo: bool):
        self.banco = banco
        self.credito = credito
        self.ativo = ativo

    # --- a página ------------------------------------------------------------------------
    def listar(self, cliente, usuario: dict) -> dict:
        """As reanálises de um cliente para a página, da mais nova para a mais antiga (sem as excluídas), com os prazos
        da caixa, a chave do próximo registro, o cadastro de hoje e, na última, se o ERP já está com o liberado."""
        cliente = _cliente(cliente)
        if not self.ativo:
            return {"ativo": False, "aviso": AVISO_PC, "reanalises": []}
        cadastro = self.credito.cadastro(cliente)
        extraido = self.credito.cache.info.get("extraido_em")
        with self.banco.conexao() as con:
            linhas = con.execute(
                f"SELECT {', '.join(CAMPOS)} FROM credito_reanalises WHERE id_cliente = %s AND excluida_em IS NULL "
                "ORDER BY id DESC LIMIT %s", [cliente, MAX_LISTA]).fetchall()
        itens = [self._item(_linha(r), usuario) for r in linhas]
        if itens:
            itens[0]["erp"] = self._erp(itens[0], cadastro, extraido)
        return {"ativo": True, "aviso": None, "reanalises": itens, "prazos": self.credito.prazos(),
                "chave": novo_id(), "cadastro": cadastro, "dados_ate": extraido}

    @staticmethod
    def _item(d: dict, usuario: dict) -> dict:
        r = d["retrato"]
        doze, hist, aberto = r.get("ultimos_12_meses") or {}, r.get("historico") or {}, r.get("aberto_hoje") or {}
        return {
            "id": d["id"], "feita_em": hora(d["feita_em"]), "feita_por": d["feita_por_nome"] or "usuário excluído",
            "pode_excluir": eh_admin(usuario) or d["feita_por"] == usuario["id"],
            **{k: d[k] for k in ("limite_antes", "prazo_antes", "limite_pedido", "limite_liberado", "prazo_liberado",
                                 "justificativa", "parecer", "parecer_liberado", "limite_sugerido")},
            "dados_ate": d["dados_ate"].isoformat(timespec="seconds"),
            "decisao": decisao(d["limite_antes"], d["limite_liberado"], d["prazo_antes"], d["prazo_liberado"]),
            # O que a página mostra em "Ver os números do dia"
            "numeros": {
                "compras_valor": hist.get("compras_valor"), "compras_qtd": hist.get("compras_qtd"),
                "pontualidade": hist.get("pontualidade"), "meses_cliente": hist.get("meses_cliente"),
                "pontualidade_12m": doze.get("pontualidade"), "compras_mes_12m": doze.get("compras_mes"),
                "maior_saldo_12m": doze.get("maior_saldo"), "prazo_real_12m": doze.get("prazo_real_dias"),
                "em_aberto": aberto.get("em_aberto"), "uso_do_limite": aberto.get("uso_do_limite"),
                "inadimplencia": aberto.get("inadimplencia"),
            },
        }

    @staticmethod
    def _erp(item: dict, cadastro: dict, extraido: str | None) -> dict:
        """A última reanálise contra o cadastro de hoje: aplicado (o ERP já tem o limite e o prazo liberados), aguardando
        (registrada com os dados de agora: o ERP aparece na próxima atualização) ou diferente."""
        igual = abs(cadastro["limite"] - item["limite_liberado"]) < 0.005 and cadastro["prazo"] == item["prazo_liberado"]
        mesma = extraido and dt.datetime.fromisoformat(extraido).isoformat(timespec="seconds") == item["dados_ate"]
        return {"situacao": "aplicado" if igual else "aguardando" if mesma else "diferente",
                "limite": cadastro["limite"], "prazo": cadastro["prazo"]}

    def registrar(self, usuario: dict, dados: dict) -> dict:
        """Grava uma reanálise: {chave, cliente, pedido (o valor analisado no parecer), liberado, prazo, justificativa,
        dados_ate (a extração que a página mostrava)}. O retrato e os pareceres são calculados aqui. A mesma chave de
        novo não grava outra vez (ja_existia). Dado inválido ou extração nova -> ValueError; dados de crédito ainda não
        chegaram -> RuntimeError. Devolve o id e a lista nova do cliente (listar)."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        chave = id_valido(dados.get("chave"))
        if not chave:
            raise ValueError("o formulário expirou; recarregue a página")
        cliente = _cliente(dados.get("cliente"))
        pedido = _reais(dados.get("pedido"), "analise o limite pedido antes de registrar", zero=False)
        liberado = _reais(dados.get("liberado"), "digite o limite liberado em reais (0 corta o crédito)", zero=True)
        prazo = dados.get("prazo")
        if not isinstance(prazo, str) or prazo not in self.credito.prazos():
            raise ValueError("escolha o prazo liberado na lista (os prazos do ERP)")
        justificativa = str(dados.get("justificativa") or "").strip()
        if len(justificativa) < MIN_JUSTIFICATIVA:
            raise ValueError(f"escreva a justificativa (pelo menos {MIN_JUSTIFICATIVA} letras)")
        if len(justificativa) > MAX_JUSTIFICATIVA:
            raise ValueError(f"a justificativa passou de {MAX_JUSTIFICATIVA} letras")
        retrato = self.credito.retrato(cliente, pedido, liberado)
        if not retrato["dados_ate"]:
            raise RuntimeError("os dados ainda estão sendo preparados")
        if str(dados.get("dados_ate") or "") != retrato["dados_ate"]:
            raise ValueError(DADOS_NOVOS)
        parecer, cadastro = retrato["parecer"], retrato["cadastro"]
        with self.banco.conexao() as con:
            linha = con.execute(
                "INSERT INTO credito_reanalises (chave, id_cliente, cliente, limite_antes, prazo_antes, limite_pedido, "
                "limite_liberado, prazo_liberado, justificativa, parecer, parecer_liberado, limite_sugerido, dados_ate, "
                "retrato, feita_por, feita_por_nome) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s::jsonb, (SELECT id FROM usuarios WHERE id = %s), %s) ON CONFLICT (chave) DO NOTHING RETURNING id",
                [chave, cliente, retrato["cliente"]["nome"], cadastro["limite"], cadastro["prazo"], pedido, liberado,
                 prazo, justificativa, parecer["pedido"]["parecer"],
                 parecer["liberado"]["parecer"] if parecer["liberado"] else None, parecer["pedido"]["limite_sugerido"],
                 dt.datetime.fromisoformat(retrato["dados_ate"]), json.dumps(retrato, ensure_ascii=False),
                 usuario["id"], usuario["nome"]]).fetchone()
            if linha is None:  # a mesma chave de novo: clique duplo, ou a rede repetiu o envio
                antiga = con.execute("SELECT id, id_cliente, feita_por FROM credito_reanalises WHERE chave = %s",
                                     [chave]).fetchone()
                if (antiga[1], antiga[2]) != (cliente, usuario["id"]):
                    raise ValueError("o formulário expirou; recarregue a página")
                id_, ja_existia = antiga[0], True
            else:
                id_, ja_existia = linha[0], False
        return {"id": id_, "ja_existia": ja_existia, **self.listar(cliente, usuario)}

    def excluir(self, usuario: dict, id_) -> dict:
        """Tira uma reanálise da página e do Assistente; a linha fica, com quem excluiu e quando. Só quem registrou ou
        um administrador. Não existe ou já saiu -> NaoEncontrada; de outra pessoa -> PermissionError. Devolve a lista
        nova do cliente (listar)."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        try:
            id_ = int(id_)
        except (TypeError, ValueError):
            raise NaoEncontrada("reanálise não encontrada") from None
        with self.banco.conexao() as con:
            linha = con.execute("SELECT id_cliente, feita_por FROM credito_reanalises WHERE id = %s "
                                "AND excluida_em IS NULL FOR UPDATE", [id_]).fetchone()
            if linha is None:
                raise NaoEncontrada("reanálise não encontrada; ela pode ter sido excluída")
            if not eh_admin(usuario) and linha[1] != usuario["id"]:
                raise PermissionError("só quem registrou a reanálise ou um administrador pode excluí-la")
            con.execute("UPDATE credito_reanalises SET excluida_em = now(), excluida_por = "
                        "(SELECT id FROM usuarios WHERE id = %s), excluida_por_nome = %s WHERE id = %s",
                        [usuario["id"], usuario["nome"], id_])
        return self.listar(linha[0], usuario)

    # --- o Assistente ----------------------------------------------------------------------
    def para_ia(self, id_cliente: int, parecidos: bool, novo_limite: float | None = None, mes: str | None = None,
                maximo: int = MAX_IA) -> dict:
        """Para a ferramenta reanalises_credito. id_cliente 0 = todas, das mais novas para as mais antigas; parecidos:
        as de outros clientes com o perfil mais parecido com o de hoje de id_cliente (com novo_limite, o pedido ÷ o maior
        saldo também conta); mes (AAAA-MM): só as registradas nele. Cada uma com o que aconteceu depois
        (Credito.depois) e, junto, um resumo de todas as do filtro (nas parecidas, das devolvidas)."""
        if not self.ativo:
            raise ValueError("as reanálises de crédito ficam no site (bi.maisvida.cloud); neste painel não há nenhuma")
        id_cliente = int(id_cliente or 0)
        onde, params, alvo = ["excluida_em IS NULL"], [], None
        if mes:
            inicio = _mes(mes)
            fim = (inicio.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            onde.append("feita_em >= %s AND feita_em < %s")
            params += [inicio_do_dia(inicio), inicio_do_dia(fim)]
        if parecidos:
            if not id_cliente:
                raise ValueError("para achar reanálises parecidas, informe o cliente (id_cliente)")
            limite = float(novo_limite) if novo_limite and math.isfinite(float(novo_limite)) else None
            alvo = self.credito.perfil(id_cliente, limite if limite and limite > 0 else None)
            onde.append("id_cliente <> %s")
            params.append(id_cliente)
        elif id_cliente:
            onde.append("id_cliente = %s")
            params.append(id_cliente)
        colunas = ", ".join("retrato - 'mes_a_mes'" if c == "retrato" else c for c in CAMPOS)  # o mês a mês fica fora
        with self.banco.conexao() as con:
            todas = [_linha(r) for r in con.execute(
                f"SELECT {colunas} FROM credito_reanalises WHERE {' AND '.join(onde)} ORDER BY id DESC",
                params).fetchall()]
        if alvo:
            for d in todas:
                d["distancia"] = distancia(alvo, perfil_do_retrato(d["retrato"]))
            todas.sort(key=lambda d: (d["distancia"], -d["id"]))
        escolhidas = todas[:maximo]
        depois = self.credito.depois([(d["id_cliente"], d["feita_em"].astimezone().date(), d["limite_liberado"])
                                      for d in escolhidas])
        saida = {"total": len(todas), "mostrando": len(escolhidas), "resumo": _resumo(escolhidas if alvo else todas),
                 "reanalises": [self._para_ia(d, x) for d, x in zip(escolhidas, depois)]}
        if alvo:
            saida["comparado_com"] = {**alvo, "novo_limite": novo_limite or None}
        return saida

    @staticmethod
    def _para_ia(d: dict, depois: dict) -> dict:
        r = d["retrato"]
        doze, hist, aberto, cad = (r.get(k) or {} for k in ("ultimos_12_meses", "historico", "aberto_hoje", "cadastro"))
        saida = {
            "quando": hora(d["feita_em"]), "quem": d["feita_por_nome"],
            "cliente": {"id": d["id_cliente"], "nome": d["cliente"], "segmento": cad.get("segmento"),
                        "cidade": cad.get("cidade"), "uf": cad.get("uf")},
            "limite": {"antes": d["limite_antes"], "pedido": d["limite_pedido"], "liberado": d["limite_liberado"],
                       "sugerido_pela_regra": d["limite_sugerido"]},
            "prazo": {"antes": d["prazo_antes"], "liberado": d["prazo_liberado"]},
            "decisao": decisao(d["limite_antes"], d["limite_liberado"], d["prazo_antes"], d["prazo_liberado"]),
            "parecer_da_regra": {"para_o_pedido": PARECERES[d["parecer"]],
                                 "para_o_liberado": PARECERES.get(d["parecer_liberado"])},
            "numeros_no_dia": {
                "pontualidade_12m": doze.get("pontualidade"), "compras_por_mes_12m": doze.get("compras_mes"),
                "maior_saldo_12m": doze.get("maior_saldo"),
                "atraso_medio_dos_atrasados_12m": doze.get("atraso_medio_dos_atrasados"),
                "em_aberto": aberto.get("em_aberto"), "inadimplencia": aberto.get("inadimplencia"),
                "meses_de_cliente": hist.get("meses_cliente"), "compras_total": hist.get("compras_valor"),
                "pontualidade_total": hist.get("pontualidade"),
            },
            "justificativa": _cortar(d["justificativa"], JUSTIFICATIVA_IA),
            "depois": depois,
        }
        if "distancia" in d:
            saida["distancia"] = round(d["distancia"], 2)
        return saida

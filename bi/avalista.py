"""Contratos de avalista (página Reavaliação de Crédito, botão "Avalista"): o contrato usado quando o cliente compra
num CNPJ que não está no nome dele e outra empresa ou pessoa garante o pagamento. A página preenche os dados da
compradora e de quem garante, guarda o contrato e baixa o PDF igual ao modelo em Word (bi/avalista_pdf.py).

- Dois modelos, pelo tipo de quem garante: "pj" (uma empresa: Contrato de Garantia Fidejussória) e "pf" (uma pessoa:
  Contrato de Compra e Venda de Produtos Lácteos, com a garantia na cláusula 8). A compradora é sempre uma empresa.
- Cada contrato é uma linha da tabela credito_avalistas (migração 050), com tudo o que foi digitado em "dados". Pode
  ser salvo pela metade: basta a razão social da compradora. O que falta (pendencias) aparece na lista e na tela, e
  no PDF sai como uma linha para preencher à mão. CNPJ ou CPF que não confere também é pendência, e não impede salvar.
- Editar grava por cima (não guarda as versões antigas) e anota quem editou e quando; "versao" sobe a cada gravação,
  para duas pessoas com o mesmo contrato aberto não apagarem o trabalho uma da outra. Só quem fez ou um administrador
  edita ou exclui; excluir tira da página e a linha fica guardada (excluido_em).
- Todos que têm a página de crédito veem todos os contratos e baixam o PDF.
- Os dados da Mais Vida (o fornecedor) são uma configuração só, salva pelo administrador (tabela regras, nome
  "avalista"), e valem para todos os contratos: o PDF sai sempre com os de agora. O modelo Pessoa Física pede mais
  dados dela (inscrição estadual e a qualificação de quem representa) que o Pessoa Jurídica.
- Cada pessoa entra só com o CPF: o RG que os modelos traziam saiu do contrato (pedido do usuário em 2026-11-26). O
  "rg" de um contrato guardado antes disso é ignorado.
- Só o site grava (ativo), como as capas de análise e as reanálises.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata

from .acesso import eh_admin
from .avalista_pdf import documento, nome_arquivo
from .banco import hora
from .configuracao import RegrasNoBanco
from .conversas import NaoEncontrada, id_valido, novo_id

TIPOS = {"pj": "Pessoa jurídica", "pf": "Pessoa física"}
AVISO_PC = ("Os contratos de avalista ficam no site (bi.maisvida.cloud), junto com as capas de análise de crédito: "
            "preencha e baixe por lá.")
NAO_ENCONTRADO = "contrato não encontrado: ele pode ter sido excluído; recarregue a página"
MUDOU = "este contrato foi alterado por outra pessoa enquanto você editava: recarregue a página e refaça a alteração"
TRATAMENTOS = ("Sr.", "Sra.")
MAX_REPRESENTANTES = 4
MAX_LISTA = 100
MAX_BUSCA = 100
# Cada campo: (chave, como aparece na lista do que falta, máximo de letras). CNPJ, CPF e CEP têm folga para o que vem
# colado com espaço ou pontuação a mais (um dos modelos trazia "033.376.305- 02"); saem arrumados.
CAMPOS_EMPRESA = (("razao_social", "razão social", 200), ("cnpj", "CNPJ", 24), ("ie", "inscrição estadual", 30),
                  ("endereco", "endereço", 300), ("cep", "CEP", 12),
                  ("qualificacao", "qualificação de quem representa", 80))
CAMPOS_PESSOA = (("nome", "nome", 200), ("nacionalidade", "nacionalidade", 40), ("estado_civil", "estado civil", 40),
                 ("profissao", "profissão", 80), ("cpf", "CPF", 20), ("endereco", "endereço", 300), ("cep", "CEP", 12))
MAX_PODERES = 300
SO_NO_PJ = ("endereco", "cep")  # do representante: só o modelo Pessoa Jurídica diz onde ele mora
OPCIONAIS = ("ie",)             # "se houver"
PARTES = {"compradora": "Compradora", "garantidor": {"pj": "Garantidora", "pf": "Garantidor"}}
# Os dados da Mais Vida que saem no contrato. O padrão é o que está no modelo Pessoa Jurídica; o resto (o modelo Pessoa
# Física pede) o administrador preenche na página, sem ficar escrito no código.
CAMPOS_FORNECEDOR = (("razao_social", "razão social", 200), ("cnpj", "CNPJ", 24), ("ie", "inscrição estadual", 30),
                     ("endereco", "endereço", 300), ("cep", "CEP", 12),
                     ("qualificacao", "qualificação de quem representa", 80), ("tratamento", "tratamento", 4),
                     ("representante", "nome de quem representa", 200), ("nacionalidade", "nacionalidade", 40),
                     ("estado_civil", "estado civil", 40), ("profissao", "profissão", 80), ("cpf", "CPF", 20))
PADRAO_FORNECEDOR = {"razao_social": "LATICINIO MAIS VIDA LTDA", "cnpj": "96.845.748/0001-64", "ie": "",
                     "endereco": "Av. Guaratinga, km 02, Zona Rural, Itabela - BA", "cep": "45848-000",
                     "qualificacao": "sócio administrador", "tratamento": "Sr.",
                     "representante": "MAURO SERGIO PIMENTEL QUEIROZ", "nacionalidade": "", "estado_civil": "",
                     "profissao": "", "cpf": ""}
FORNECEDOR_OBRIGATORIOS = ("razao_social", "cnpj", "endereco", "cep", "qualificacao", "representante")
FORNECEDOR_SO_NO_PF = ("nacionalidade", "estado_civil", "profissao", "cpf")


# ---------- CNPJ, CPF e CEP ----------
def _limpo(texto) -> str:
    return re.sub(r"[.\-/\s]", "", str(texto or "")).upper()


def _digito(valores: list[int]) -> int:
    resto = sum(v * (2 + i % 8) for i, v in enumerate(reversed(valores))) % 11
    return 0 if resto < 2 else 11 - resto


def cnpj_valido(texto) -> str | None:
    """Os 14 caracteres do CNPJ quando os dígitos verificadores conferem; senão None. Desde julho de 2026 os 12
    primeiros podem ter letras (cada caractere vale o código dele menos 48, na mesma conta)."""
    c = _limpo(texto)
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", c) or len(set(c)) == 1:
        return None
    valores = [ord(x) - 48 for x in c[:12]]
    d1 = _digito(valores)
    return c if c[12:] == f"{d1}{_digito([*valores, d1])}" else None


def cpf_valido(texto) -> str | None:
    """Os 11 dígitos do CPF quando os verificadores conferem; senão None."""
    c = _limpo(texto)
    if not re.fullmatch(r"[0-9]{11}", c) or len(set(c)) == 1:
        return None
    n = [int(x) for x in c]
    for fim in (9, 10):
        resto = sum(v * (fim + 1 - i) for i, v in enumerate(n[:fim])) * 10 % 11
        if resto % 10 != n[fim]:
            return None
    return c


def formatar_cnpj(texto: str) -> str:
    """"12345678000190" -> "12.345.678/0001-90"; o que não tem o formato de um CNPJ fica como foi digitado."""
    c = _limpo(texto)
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", c) else texto


def formatar_cpf(texto: str) -> str:
    c = _limpo(texto)
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}" if re.fullmatch(r"[0-9]{11}", c) else texto


def formatar_cep(texto: str) -> str:
    c = _limpo(texto)
    return f"{c[:5]}-{c[5:]}" if re.fullmatch(r"[0-9]{8}", c) else texto


_FORMATOS = {"cnpj": formatar_cnpj, "cpf": formatar_cpf, "cep": formatar_cep}


# ---------- o que veio da página ----------
def _txt(valor, maximo: int, nome: str) -> str:
    """Um texto digitado: sem caracteres de controle, com um espaço só entre as palavras. Comprido demais ou que não é
    texto -> ValueError."""
    if valor is None:
        return ""
    if isinstance(valor, (dict, list, bool)):
        raise ValueError(f"{nome}: valor inválido")
    t = unicodedata.normalize("NFC", str(valor))
    t = re.sub(r"\s+", " ", "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in t)).strip()
    if len(t) > maximo:
        raise ValueError(f"{nome} passou de {maximo} letras")
    return t


def _campos(bruto, campos, parte: str) -> dict:
    bruto = bruto if isinstance(bruto, dict) else {}
    saida = {}
    for chave, rotulo, maximo in campos:
        t = _txt(bruto.get(chave), maximo, f"{parte}: {rotulo}")
        saida[chave] = _FORMATOS[chave](t) if chave in _FORMATOS else t
    return saida


def _representantes(bruto, modelo: str, parte: str) -> list[dict]:
    lista = bruto if isinstance(bruto, list) else []
    if len(lista) > MAX_REPRESENTANTES:
        raise ValueError(f"{parte}: no máximo {MAX_REPRESENTANTES} representantes")
    saida = []
    for n, r in enumerate(lista, 1):
        r = r if isinstance(r, dict) else {}
        nome = f"{parte}, representante {n}"
        pessoa = _campos(r, [c for c in CAMPOS_PESSOA if modelo == "pj" or c[0] not in SO_NO_PJ], nome)
        if modelo == "pj":  # só o modelo Pessoa Jurídica traz "Sr." ou "Sra." antes do nome
            tratamento = _txt(r.get("tratamento"), 4, f"{nome}: tratamento")
            if tratamento and tratamento not in TRATAMENTOS:
                raise ValueError(f"{nome}: escolha Sr. ou Sra.")
            pessoa = {"tratamento": tratamento, **pessoa}
        saida.append(pessoa)
    return saida or [_representantes([{}], modelo, parte)[0]]


def _empresa(bruto, modelo: str, parte: str, poderes: bool = False) -> dict:
    bruto = bruto if isinstance(bruto, dict) else {}
    e = _campos(bruto, CAMPOS_EMPRESA, parte)
    if poderes:  # modelo Pessoa Jurídica, compradora: "conforme poderes conferidos por ..." (só quando preenchido)
        e["poderes"] = _txt(bruto.get("poderes"), MAX_PODERES, f"{parte}: poderes conferidos por")
    e["representantes"] = _representantes(bruto.get("representantes"), modelo, parte)
    return e


def _data(valor) -> str | None:
    if valor in (None, ""):
        return None
    try:
        d = dt.date.fromisoformat(str(valor))
    except ValueError:
        raise ValueError("a data do contrato não é uma data válida") from None
    if not 2000 <= d.year <= 2100:
        raise ValueError("confira o ano da data do contrato")
    return d.isoformat()


def normalizar(bruto) -> dict:
    """O contrato como veio da página, conferido e arrumado (CNPJ, CPF e CEP com a pontuação): {tipo, data, compradora,
    garantidor}. Campo vazio não é erro (o contrato pode ser salvo pela metade; ver pendencias). Tipo inválido, texto
    comprido demais ou data impossível -> ValueError."""
    bruto = bruto if isinstance(bruto, dict) else {}
    tipo = bruto.get("tipo")
    if tipo not in TIPOS:
        raise ValueError("escolha quem garante: uma empresa (pessoa jurídica) ou uma pessoa (pessoa física)")
    garantidor = (_empresa(bruto.get("garantidor"), tipo, "Garantidora") if tipo == "pj"
                  else _campos(bruto.get("garantidor"), CAMPOS_PESSOA, "Garantidor"))
    return {"tipo": tipo, "data": _data(bruto.get("data")),
            "compradora": _empresa(bruto.get("compradora"), tipo, "Compradora", poderes=tipo == "pj"),
            "garantidor": garantidor}


def _falta(saida: list, campo: str, parte: str, rotulo: str, valor: str, chave: str) -> None:
    """Acrescenta a pendência de um campo: vazio, ou um CNPJ, CPF ou CEP que não confere."""
    if not valor:
        saida.append({"campo": campo, "texto": f"{parte}: {rotulo}"})
    elif chave == "cnpj" and not cnpj_valido(valor):
        saida.append({"campo": campo, "texto": f"{parte}: o CNPJ não confere (dígitos verificadores)"})
    elif chave == "cpf" and not cpf_valido(valor):
        saida.append({"campo": campo, "texto": f"{parte}: o CPF não confere (dígitos verificadores)"})
    elif chave == "cep" and not re.fullmatch(r"[0-9]{5}-[0-9]{3}", valor):
        saida.append({"campo": campo, "texto": f"{parte}: o CEP tem 8 números"})


def _pendencias_empresa(e: dict, caminho: str, parte: str, modelo: str, saida: list) -> None:
    for chave, rotulo, _ in CAMPOS_EMPRESA:
        if chave not in OPCIONAIS:
            _falta(saida, f"{caminho}.{chave}", parte, rotulo, e.get(chave, ""), chave)
    for n, r in enumerate(e.get("representantes") or [{}]):
        nome = f"{parte}, representante {n + 1}" if len(e.get("representantes") or []) > 1 else f"{parte}, representante"
        if modelo == "pj" and not r.get("tratamento"):
            saida.append({"campo": f"{caminho}.representantes.{n}.tratamento", "texto": f"{nome}: Sr. ou Sra."})
        for chave, rotulo, _ in CAMPOS_PESSOA:
            if modelo == "pj" or chave not in SO_NO_PJ:
                _falta(saida, f"{caminho}.representantes.{n}.{chave}", nome, rotulo, r.get(chave, ""), chave)


def pendencias(dados: dict) -> list[dict]:
    """O que falta preencher ou não confere no contrato (normalizar), na ordem da tela: [{campo: "compradora.cnpj",
    texto: "Compradora: CNPJ"}]. A inscrição estadual e "poderes conferidos por" são opcionais."""
    modelo, c, g = dados["tipo"], dados["compradora"], dados["garantidor"]
    saida: list[dict] = []
    _pendencias_empresa(c, "compradora", PARTES["compradora"], modelo, saida)
    parte = PARTES["garantidor"][modelo]
    if modelo == "pj":
        _pendencias_empresa(g, "garantidor", parte, modelo, saida)
        mesmo = cnpj_valido(c.get("cnpj"))
        if mesmo and mesmo == cnpj_valido(g.get("cnpj")):
            saida.append({"campo": "garantidor.cnpj", "texto": "Garantidora: o CNPJ é o mesmo da compradora"})
    else:
        for chave, rotulo, _ in CAMPOS_PESSOA:
            _falta(saida, f"garantidor.{chave}", parte, rotulo, g.get(chave, ""), chave)
    if not dados.get("data"):
        saida.append({"campo": "data", "texto": "Data do contrato"})
    return saida


# ---------- os dados da Mais Vida ----------
def _valida_fornecedor(cfg) -> dict:
    """Os dados da Mais Vida conferidos. Sem o que os dois modelos usam (FORNECEDOR_OBRIGATORIOS), ou com CNPJ ou CPF
    que não confere -> ValueError. O resto pode ficar vazio (o modelo Pessoa Física avisa o que falta)."""
    f = _campos(cfg, CAMPOS_FORNECEDOR, "Mais Vida")
    rotulos = {c[0]: c[1] for c in CAMPOS_FORNECEDOR}
    for chave in FORNECEDOR_OBRIGATORIOS:
        if not f[chave]:
            raise ValueError(f"Mais Vida: preencha {rotulos[chave]}")
    if not cnpj_valido(f["cnpj"]):
        raise ValueError("Mais Vida: o CNPJ não confere (dígitos verificadores)")
    if f["cpf"] and not cpf_valido(f["cpf"]):
        raise ValueError("Mais Vida: o CPF de quem representa não confere (dígitos verificadores)")
    if f["tratamento"] and f["tratamento"] not in TRATAMENTOS:
        raise ValueError("Mais Vida: escolha Sr. ou Sra.")
    return f


def faltas_do_fornecedor(f: dict, modelo: str) -> list[str]:
    """O que falta nos dados da Mais Vida para o modelo: o Pessoa Física pede a qualificação de quem representa."""
    rotulos = {c[0]: c[1] for c in CAMPOS_FORNECEDOR}
    pede = FORNECEDOR_OBRIGATORIOS + (FORNECEDOR_SO_NO_PF if modelo == "pf" else ())
    return [rotulos[k] for k in pede if not f.get(k)]


class ConfigAvalista(RegrasNoBanco):
    """Os dados da Mais Vida que saem nos contratos de avalista (tabela regras, nome "avalista"), salvos pelo
    administrador."""

    nome = "avalista"
    _valida = staticmethod(_valida_fornecedor)

    def _padrao(self) -> dict:
        return dict(PADRAO_FORNECEDOR)


# ---------- os contratos guardados ----------
CAMPOS = ("id", "tipo", "id_cliente", "compradora", "compradora_cnpj", "garantidor", "garantidor_doc", "dados", "versao",
          "feito_em", "feito_por", "feito_por_nome", "editado_em", "editado_por", "editado_por_nome")
# Minúsculas e sem acento, no SQL, para a busca comparar o nome sem caixa nem acento.
_SEM_ACENTO_SQL = "translate(lower(coalesce({}, '')), 'áàâãäåéèêëíìîïóòôõöúùûüçñ', 'aaaaaaeeeeiiiiooooouuuucn')"


def _sem_acento(texto: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(ch) != "Mn")


def _busca(texto: str) -> tuple[str, list]:
    """A condição SQL (sobre o contrato a) da busca da lista: o nome da compradora ou de quem garante (sem caixa nem
    acento) ou os números do CNPJ ou do CPF (3 ou mais)."""
    parecido = "%" + re.sub(r"([%_\\])", r"\\\1", _sem_acento(" ".join(texto.split()))) + "%"
    condicoes = [f"{_SEM_ACENTO_SQL.format('a.compradora')} LIKE %s ESCAPE '\\'",
                 f"{_SEM_ACENTO_SQL.format('a.garantidor')} LIKE %s ESCAPE '\\'"]
    params: list = [parecido, parecido]
    numeros = _limpo(texto)
    if len(numeros) >= 3 and re.fullmatch(r"[0-9A-Z]+", numeros) and re.search(r"[0-9]", numeros):
        condicoes += ["a.compradora_cnpj LIKE %s", "a.garantidor_doc LIKE %s"]
        params += [f"%{numeros}%", f"%{numeros}%"]
    return " OR ".join(condicoes), params


def _documento_de(dados: dict) -> str | None:
    """O CNPJ (ou o CPF) de quem garante, só os caracteres, quando confere."""
    g = dados["garantidor"]
    return cnpj_valido(g.get("cnpj")) if dados["tipo"] == "pj" else cpf_valido(g.get("cpf"))


class Avalistas:
    """Os contratos de avalista, na tabela credito_avalistas. credito: o Crédito (bi/credito.py), para puxar a razão
    social e o CNPJ de um cliente do ERP; config: os dados da Mais Vida (ConfigAvalista); ativo: o site, que grava e
    lê (no PC, False, a página só avisa que os contratos ficam no site)."""

    def __init__(self, banco, credito, config: ConfigAvalista, ativo: bool):
        self.banco = banco
        self.credito = credito
        self.config = config
        self.ativo = ativo

    # --- o formulário ---------------------------------------------------------------------
    def opcoes(self, usuario: dict) -> dict:
        """O que o formulário usa: os tipos, a chave do próximo contrato, os dados da Mais Vida (e o que falta neles
        para cada modelo) e a data de hoje."""
        f = self.config.atual()
        return {"tipos": [{"chave": k, "nome": v} for k, v in TIPOS.items()], "chave": novo_id(),
                "tratamentos": list(TRATAMENTOS), "max_representantes": MAX_REPRESENTANTES,
                "hoje": dt.date.today().isoformat(), "fornecedor": f,
                "fornecedor_falta": {k: faltas_do_fornecedor(f, k) for k in TIPOS},
                "pode_fornecedor": eh_admin(usuario)}

    def cliente(self, valor, permitidos=None) -> dict:
        """Um cliente do ERP para começar a compradora: a razão social, o CNPJ e a cidade (o endereço, a inscrição
        estadual e os sócios não vêm do ERP para o painel). Código inválido ou que não existe -> ValueError; cliente
        fora do acesso -> PermissionError."""
        try:
            cliente = int(valor)
        except (TypeError, ValueError):
            raise ValueError("escolha o cliente") from None
        cadastro = self.credito.cadastro(cliente)  # o cliente que não existe -> ValueError
        if permitidos is not None and not self.credito.no_acesso(cliente, permitidos):
            raise PermissionError(f"o cliente {cliente} não é dos vendedores do seu acesso")
        cache, razao, cidade, uf = self.credito.cache, None, None, None
        if not cache.sem_detalhe:
            linhas = cache.consulta("SELECT razao_social, cidade, uf FROM clientes_detalhes WHERE id = ?", [cliente])
            razao, cidade, uf = linhas[0] if linhas else (None, None, None)
        cnpj = self.credito.cnpj_de(cliente)
        return {"id": cliente, "nome": cadastro["nome"], "razao_social": (razao or "").strip() or cadastro["nome"],
                "cnpj": formatar_cnpj(cnpj) if cnpj else None, "cidade": (cidade or "").strip() or None,
                "uf": (uf or "").strip() or None}

    # --- gravar ---------------------------------------------------------------------------
    def salvar(self, usuario: dict, corpo: dict, permitidos=None) -> dict:
        """Grava um contrato: {chave, dados, id_cliente} para um novo; {id, versao, dados, id_cliente} para gravar por
        cima de um que existe (quem fez ou um administrador). Basta a razão social da compradora: o resto pode ficar
        para depois. A mesma chave de novo não grava outra vez (ja_existia). Devolve o contrato gravado e a lista
        nova. Dado inválido ou contrato alterado por outra pessoa -> ValueError; cliente fora do acesso ou contrato de
        outra pessoa -> PermissionError; contrato excluído -> NaoEncontrada."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        corpo = corpo if isinstance(corpo, dict) else {}
        dados = normalizar(corpo.get("dados"))
        if not dados["compradora"]["razao_social"]:
            raise ValueError("escreva a razão social da compradora para salvar o contrato")
        cliente = corpo.get("id_cliente")
        if cliente in (None, ""):
            cliente = None
        else:
            try:
                cliente = int(cliente)
            except (TypeError, ValueError):
                raise ValueError("cliente inválido") from None
            if cliente <= 0:
                raise ValueError("cliente inválido")
            self.credito.conferir_cliente(cliente, permitidos)
        g = dados["garantidor"]
        valores = [dados["tipo"], cliente, dados["compradora"]["razao_social"], cnpj_valido(dados["compradora"]["cnpj"]),
                   (g.get("razao_social") if dados["tipo"] == "pj" else g.get("nome")) or None, _documento_de(dados),
                   json.dumps(dados, ensure_ascii=False)]
        with self.banco.conexao() as con:
            if corpo.get("id") not in (None, ""):
                atual = self._ler(con, corpo.get("id"), travar=True)
                self._pode_mudar(usuario, atual, "editá-lo")
                if corpo.get("versao") != atual["versao"]:
                    raise ValueError(MUDOU)
                con.execute(
                    "UPDATE credito_avalistas SET tipo = %s, id_cliente = %s, compradora = %s, compradora_cnpj = %s, "
                    "garantidor = %s, garantidor_doc = %s, dados = %s::jsonb, versao = versao + 1, editado_em = now(), "
                    "editado_por = (SELECT id FROM usuarios WHERE id = %s), editado_por_nome = %s WHERE id = %s",
                    [*valores, usuario["id"], usuario["nome"], atual["id"]])
                id_, ja_existia = atual["id"], False
            else:
                chave = id_valido(corpo.get("chave"))
                if not chave:
                    raise ValueError("o formulário expirou; recarregue a página")
                antigo = con.execute("SELECT id, feito_por FROM credito_avalistas WHERE chave = %s", [chave]).fetchone()
                if antigo is not None:  # a mesma chave de novo: clique duplo, ou a rede repetiu o envio
                    if antigo[1] != usuario["id"]:
                        raise ValueError("o formulário expirou; recarregue a página")
                    id_, ja_existia = antigo[0], True
                else:
                    id_ = con.execute(
                        "INSERT INTO credito_avalistas (chave, tipo, id_cliente, compradora, compradora_cnpj, garantidor, "
                        "garantidor_doc, dados, feito_por, feito_por_nome) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, "
                        "(SELECT id FROM usuarios WHERE id = %s), %s) RETURNING id",
                        [chave, *valores, usuario["id"], usuario["nome"]]).fetchone()[0]
                    ja_existia = False
            contrato = self._item(self._ler(con, id_), usuario, completo=True)
        return {"id": id_, "ja_existia": ja_existia, "contrato": contrato, **self.listar(usuario)}

    def excluir(self, usuario: dict, id_) -> dict:
        """Tira um contrato da página; a linha fica, com quem excluiu e quando. Só quem fez ou um administrador."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        with self.banco.conexao() as con:
            atual = self._ler(con, id_, travar=True)
            self._pode_mudar(usuario, atual, "excluí-lo")
            con.execute("UPDATE credito_avalistas SET excluido_em = now(), excluido_por = "
                        "(SELECT id FROM usuarios WHERE id = %s), excluido_por_nome = %s WHERE id = %s",
                        [usuario["id"], usuario["nome"], atual["id"]])
        return self.listar(usuario)

    def salvar_fornecedor(self, usuario: dict, dados) -> dict:
        """Grava os dados da Mais Vida (só o administrador) e devolve o que o formulário usa."""
        if not eh_admin(usuario):
            raise PermissionError("só o administrador altera os dados da Mais Vida no contrato")
        if not self.ativo:
            raise ValueError(AVISO_PC)
        self.config.salvar(dados, usuario)
        return self.opcoes(usuario)

    # --- ler ------------------------------------------------------------------------------
    @staticmethod
    def _pode_mudar(usuario: dict, d: dict, verbo: str) -> None:
        if not eh_admin(usuario) and d["feito_por"] != usuario["id"]:
            raise PermissionError(f"só quem fez o contrato ou um administrador pode {verbo}")

    def _ler(self, con, id_, travar: bool = False) -> dict:
        """Um contrato que está na página (sem os excluídos). Não existe -> NaoEncontrada."""
        try:
            id_ = int(id_)
        except (TypeError, ValueError):
            raise NaoEncontrada(NAO_ENCONTRADO) from None
        r = con.execute(f"SELECT {', '.join(CAMPOS)} FROM credito_avalistas WHERE id = %s AND excluido_em IS NULL"
                        f"{' FOR UPDATE' if travar else ''}", [id_]).fetchone()
        if r is None:
            raise NaoEncontrada(NAO_ENCONTRADO)
        return dict(zip(CAMPOS, r))

    @staticmethod
    def _item(d: dict, usuario: dict, completo: bool = False) -> dict:
        """Um contrato para a página. completo: com tudo o que foi digitado e a lista do que falta (para abrir o
        formulário); sem ele, só a linha da lista."""
        dados = normalizar(d["dados"])  # o que está no banco já passou por aqui; de novo, para as regras de hoje
        faltam = pendencias(dados)
        dono = eh_admin(usuario) or d["feito_por"] == usuario["id"]
        g = dados["garantidor"]
        item = {"id": d["id"], "tipo": d["tipo"], "tipo_nome": TIPOS[d["tipo"]], "versao": d["versao"],
                "id_cliente": d["id_cliente"], "compradora": d["compradora"],
                "compradora_cnpj": dados["compradora"]["cnpj"] or None, "garantidor": d["garantidor"],
                "garantidor_doc": (g.get("cnpj") if d["tipo"] == "pj" else g.get("cpf")) or None,
                "data": dados["data"], "faltam": len(faltam),
                "feito_em": hora(d["feito_em"]), "feito_por": d["feito_por_nome"] or "usuário excluído",
                "editado_em": hora(d["editado_em"]),
                "editado_por": (d["editado_por_nome"] or "usuário excluído") if d["editado_em"] else None,
                "pode_editar": dono, "pode_excluir": dono}
        if completo:
            item.update(dados=dados, pendencias=faltam)
        return item

    def listar(self, usuario: dict, busca: str | None = None, id_=None) -> dict:
        """Os contratos, dos mais novos para os mais antigos (sem os excluídos; até MAX_LISTA), e o que o formulário usa
        (opcoes). busca: o nome da compradora ou de quem garante, o CNPJ ou o CPF. id_: só esse contrato, completo (em
        "contrato"), para abrir no formulário; se não existe -> NaoEncontrada."""
        if not self.ativo:
            return {"ativo": False, "aviso": AVISO_PC, "contratos": []}
        busca = (busca or "").strip()[:MAX_BUSCA]
        onde, params = "TRUE", []
        if busca:
            condicao, params = _busca(busca)
            onde = f"({condicao})"
        with self.banco.conexao() as con:
            linhas = con.execute(f"SELECT {', '.join('a.' + c for c in CAMPOS)} FROM credito_avalistas a "
                                 f"WHERE a.excluido_em IS NULL AND {onde} ORDER BY a.id DESC LIMIT %s",
                                 [*params, MAX_LISTA]).fetchall()
            contrato = None if id_ in (None, "") else self._item(self._ler(con, id_), usuario, completo=True)
        saida = {"ativo": True, "aviso": None, "busca": busca or None,
                 "contratos": [self._item(dict(zip(CAMPOS, r)), usuario) for r in linhas], **self.opcoes(usuario)}
        if contrato is not None:
            saida["contrato"] = contrato
        return saida

    def conferir(self, corpo) -> dict:
        """O contrato da tela conferido sem gravar: os dados arrumados e o que falta (a página chama enquanto a pessoa
        preenche)."""
        dados = normalizar(corpo.get("dados") if isinstance(corpo, dict) else None)
        return {"dados": dados, "pendencias": pendencias(dados)}

    def pdf(self, id_) -> tuple[bytes, str]:
        """(o PDF de um contrato guardado, o nome do arquivo), com os dados da Mais Vida de agora."""
        if not self.ativo:
            raise ValueError(AVISO_PC)
        with self.banco.conexao() as con:
            d = self._ler(con, id_)
        dados = normalizar(d["dados"])
        return documento(dados, self.config.atual()), nome_arquivo(dados)

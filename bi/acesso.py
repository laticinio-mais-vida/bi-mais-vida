"""Usuários, senhas e sessões do painel (tabela usuarios no PostgreSQL, bi/migracoes/002_usuarios.sql).

- Senha: PBKDF2-SHA256 com sal próprio; o banco nunca guarda a senha em si.
- Sessão: cookie assinado (HMAC, com o segredo da tabela parametros) com o id do usuário, a validade e o contador de
  sessão do usuário. Trocar a senha, desativar ou excluir o usuário muda o contador (ou apaga o id) e derruba as
  sessões abertas em outros aparelhos. Um login excluído e recriado ganha outro id: os cookies antigos não servem.
- Permissões: o administrador vê tudo e mexe nas configurações e em Usuários; o visualizador vê só as páginas
  liberadas em Usuários. O que ele vê dentro de cada página fica na configuração da página: em Metas, as visões
  (abas) marcadas e, se a lista de vendedores estiver preenchida, só esses vendedores (os totais também); em
  Projeções e no Assistente, igual a Metas (padrão), todos os vendedores ou só alguns.
- Gravações: uma de cada vez (trava no banco), conferindo tudo antes de gravar. As da configuração de uma página
  podem entrar na transação de quem chama (con), para gravar junto com as regras da página.
"""
from __future__ import annotations

import base64
import collections
import contextlib
import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from .banco import Banco, hora
from .configuracao import VISOES

PAPEIS = ("admin", "visualizador")
PAGINAS = {"metas": "Metas", "projecoes": "Projeções", "sugestao": "Sugestão de Metas", "premiacoes": "Premiações",
           "assistente": "Assistente", "gestao": "Gestão", "credito": "Reavaliação de Crédito"}
# Crédito: sem escolha de vendedores (quem tem a página vê todos). Sugestão de Metas e Premiações: os vendedores de Metas.
PAGINAS_PADRAO = ["metas"]  # quem foi cadastrado antes de existir a escolha de páginas
MODOS_ESCOPO = ("metas", "todos", "alguns")  # igual ao acesso de Metas / todos os da página / só alguns
PAGINAS_COM_ESCOPO = ("projecoes", "assistente", "gestao")  # páginas com essa escolha de vendedores na configuração
ESCOPO_PADRAO = {"modo": "metas", "vendedores": None}
COOKIE = "mv_sessao"
DURACAO_SESSAO = 12 * 3600            # sem "manter conectado"
DURACAO_LEMBRAR = 30 * 24 * 3600      # com "manter conectado"
ITERACOES = 600_000
SENHA_MINIMA = 6
TRAVA_CADASTRO = 7_240_102  # pg_advisory_xact_lock: duas gravações no cadastro não se misturam
_LOGIN_VALIDO = re.compile(r"^[a-z0-9._-]{3,40}$")
_COLUNAS = ("id, login, nome, papel, ativo, senha, sessao, paginas, visoes, vendedores, escopo_projecoes, "
            "escopo_assistente, escopo_gestao, criado_em, ultimo_acesso")


# --- senhas ---------------------------------------------------------------------------------
def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, ITERACOES)
    return f"pbkdf2_sha256${ITERACOES}${base64.b64encode(sal).decode()}${base64.b64encode(h).decode()}"


def confere_senha(senha: str, guardado: str) -> bool:
    try:
        _alg, n, sal, h = guardado.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), base64.b64decode(sal), int(n))
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


# Usado quando o login não existe, para a resposta demorar o mesmo e não revelar quais logins existem.
_HASH_FALSO = gerar_hash(secrets.token_hex(8))


def _valida_senha(senha: str) -> str:
    if not isinstance(senha, str) or len(senha) < SENHA_MINIMA:
        raise ValueError(f"a senha precisa ter pelo menos {SENHA_MINIMA} caracteres")
    return senha


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def _de_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


# --- usuários -------------------------------------------------------------------------------
def _usuario(linha) -> dict:
    """Linha da tabela usuarios -> o dicionário que o resto do código usa (com a senha; para a página, publico())."""
    (id_, login, nome, papel, ativo, senha, sessao, paginas, visoes, vendedores, projecoes, assistente, gestao,
     criado, ultimo) = linha
    return {"id": id_, "login": login, "nome": nome, "papel": papel, "ativo": ativo, "senha": senha, "sessao": sessao,
            "paginas": paginas, "visoes": visoes, "vendedores": vendedores, "projecoes": projecoes,
            "assistente": assistente, "gestao": gestao, "criado_em": hora(criado), "ultimo_acesso": hora(ultimo)}


def _paginas_de(u: dict) -> list[str]:
    return [p for p in PAGINAS if p in (u.get("paginas") or PAGINAS_PADRAO)]


def _com_pagina(u: dict, pagina: str, ve: bool) -> list[str]:
    """Páginas do usuário depois de ligar ou desligar uma delas na configuração da página."""
    paginas = [p for p in PAGINAS if (p in _paginas_de(u) and p != pagina) or (p == pagina and ve)]
    if not paginas:
        raise ValueError(f"{u['nome']} ficaria sem nenhuma página; libere outra em Usuários antes")
    return paginas


def publico(u: dict) -> dict:
    """O que a página pode ver de um usuário (sem a senha nem o contador de sessão)."""
    admin = u["papel"] == "admin"
    return {
        "id": u["id"], "login": u["login"], "nome": u["nome"], "papel": u["papel"], "ativo": u["ativo"],
        "visoes": None if admin else list(u.get("visoes") or []),
        "vendedores": None if admin else u.get("vendedores"),
        "paginas": None if admin else _paginas_de(u),
        **{p: None if admin else (u.get(p) or dict(ESCOPO_PADRAO)) for p in PAGINAS_COM_ESCOPO},
        "criado_em": u.get("criado_em"), "ultimo_acesso": u.get("ultimo_acesso"),
    }


class Usuarios:
    def __init__(self, banco: Banco):
        self.banco = banco
        self._segredo_lido: bytes | None = None

    def _segredo(self) -> bytes:
        """Chave que assina os cookies de sessão; criada no primeiro uso do banco."""
        if self._segredo_lido is None:
            with self.banco.conexao() as con:
                con.execute("INSERT INTO parametros (chave, valor) VALUES ('segredo_sessao', %s) ON CONFLICT DO NOTHING",
                            [secrets.token_hex(32)])
                valor = con.execute("SELECT valor FROM parametros WHERE chave = 'segredo_sessao'").fetchone()[0]
            self._segredo_lido = bytes.fromhex(valor)
        return self._segredo_lido

    @staticmethod
    def _buscar(con, onde: str = "", parametros=()) -> list[dict]:
        return [_usuario(r) for r in con.execute(f"SELECT {_COLUNAS} FROM usuarios {onde}", parametros)]

    def _um(self, onde: str, parametros) -> dict | None:
        with self.banco.conexao() as con:
            achados = self._buscar(con, onde, parametros)
        return achados[0] if achados else None

    # --- leitura ---------------------------------------------------------------------------
    def vazio(self) -> bool:
        with self.banco.conexao() as con:
            return not con.execute("SELECT EXISTS (SELECT 1 FROM usuarios)").fetchone()[0]

    def listar(self) -> list[dict]:
        with self.banco.conexao() as con:
            usuarios = self._buscar(con)
        return sorted((publico(u) for u in usuarios), key=lambda u: (u["papel"] != "admin", u["nome"].lower()))

    def obter(self, login: str) -> dict | None:
        u = self._um("WHERE login = %s", [login])
        return publico(u) if u else None

    # --- login e sessão --------------------------------------------------------------------
    def autenticar(self, login: str, senha: str) -> dict | None:
        login = (login or "").strip().lower()
        u = self._um("WHERE login = %s", [login])
        # A conta da senha é demorada de propósito: fica fora da transação.
        if not confere_senha(senha or "", u["senha"] if u else _HASH_FALSO) or not u or not u["ativo"]:
            return None
        with self.banco.conexao() as con:
            linha = con.execute("UPDATE usuarios SET ultimo_acesso = now() WHERE id = %s RETURNING ultimo_acesso",
                                [u["id"]]).fetchone()
        return publico({**u, "ultimo_acesso": hora(linha[0]) if linha else u["ultimo_acesso"]})

    def criar_sessao(self, id_: int, lembrar: bool = False) -> tuple[str, int]:
        """Devolve o valor do cookie e a validade em segundos."""
        duracao = DURACAO_LEMBRAR if lembrar else DURACAO_SESSAO
        u = self._um("WHERE id = %s", [id_])
        if not u:
            raise ValueError("usuário não encontrado")
        corpo = _b64(json.dumps({"u": id_, "s": u["sessao"], "e": int(time.time()) + duracao, "l": lembrar}).encode())
        assinatura = _b64(hmac.new(self._segredo(), corpo.encode(), hashlib.sha256).digest())
        return f"{corpo}.{assinatura}", duracao

    def da_sessao(self, cookie: str | None) -> dict | None:
        """Usuário dono do cookie, se a assinatura confere, não venceu e o usuário segue ativo."""
        if not cookie or "." not in cookie or not cookie.isascii():
            return None
        corpo, assinatura = cookie.rsplit(".", 1)
        esperado = _b64(hmac.new(self._segredo(), corpo.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(assinatura, esperado):
            return None
        try:
            d = json.loads(_de_b64(corpo))
        except ValueError:
            return None
        id_ = d.get("u")
        if d.get("e", 0) < time.time() or type(id_) is not int:  # os cookies de antes do banco levavam o login
            return None
        u = self._um("WHERE id = %s", [id_])
        if not u or not u["ativo"] or u["sessao"] != d.get("s"):
            return None
        return {**publico(u), "lembrar": bool(d.get("l"))}

    # --- cadastro --------------------------------------------------------------------------
    @contextlib.contextmanager
    def _cadastro(self, con=None):
        """Transação para mudar o cadastro, com a trava (uma gravação de cada vez). Usa a de quem chamou, se vier:
        aí o commit é dela."""
        with (contextlib.nullcontext(con) if con is not None else self.banco.conexao()) as c:
            c.execute("SELECT pg_advisory_xact_lock(%s)", [TRAVA_CADASTRO])
            yield c

    def salvar(self, dados: dict, login_original: str | None = None, primeiro: bool = False) -> dict:
        """Cria (login_original vazio) ou altera um usuário: nome, login, senha, papel e páginas. O que a pessoa
        vê dentro de cada página fica como está (muda na configuração da página). primeiro: só cria se ainda não
        existe nenhum usuário (o primeiro acesso). Levanta ValueError."""
        login = str(dados.get("login") or "").strip().lower()
        if not _LOGIN_VALIDO.match(login):
            raise ValueError("o usuário deve ter de 3 a 40 letras minúsculas, números, ponto, hífen ou sublinhado, sem espaço nem acento")
        nome = str(dados.get("nome") or "").strip()
        if not nome:
            raise ValueError("informe o nome")
        papel = dados.get("papel")
        if papel not in PAPEIS:
            raise ValueError("papel inválido")
        ativo = bool(dados.get("ativo", True))
        paginas = None
        if papel != "admin":
            paginas = [p for p in PAGINAS if p in (dados.get("paginas") or [])]
            if not paginas:
                raise ValueError("escolha ao menos uma página para o visualizador")
        senha = dados.get("senha") or None
        hash_senha = gerar_hash(_valida_senha(senha)) if senha else None  # demorado: antes da trava

        with self._cadastro() as con:
            usuarios = {u["login"]: u for u in self._buscar(con)}
            if primeiro and usuarios:
                raise ValueError("o administrador já foi criado; entre com usuário e senha")
            if login_original:
                if login_original not in usuarios:
                    raise ValueError("usuário não encontrado")
                if login != login_original and login in usuarios:
                    raise ValueError(f"já existe o usuário {login}")
                u = usuarios[login_original]
            else:
                if login in usuarios:
                    raise ValueError(f"já existe o usuário {login}")
                if not senha:
                    raise ValueError("informe a senha do novo usuário")
                u = {"sessao": 0}
            novo = {**u, "login": login, "nome": nome, "papel": papel, "ativo": ativo, "paginas": paginas}
            if hash_senha:
                novo["senha"] = hash_senha
            if login_original and (senha or (u["ativo"] and not ativo)):
                novo["sessao"] = u["sessao"] + 1  # derruba as sessões abertas
            outros = [v for k, v in usuarios.items() if k != login_original] + [novo]
            if usuarios and not any(v["papel"] == "admin" and v["ativo"] for v in outros):
                raise ValueError("precisa ficar pelo menos um administrador ativo")
            if login_original:
                linha = con.execute(
                    f"UPDATE usuarios SET login = %s, nome = %s, papel = %s, ativo = %s, paginas = %s::text[], "
                    f"senha = %s, sessao = %s WHERE id = %s RETURNING {_COLUNAS}",
                    [login, nome, papel, ativo, paginas, novo["senha"], novo["sessao"], u["id"]]).fetchone()
            else:
                # Sem abas de Metas até o administrador escolher em Metas › Configurar.
                linha = con.execute(
                    f"INSERT INTO usuarios (login, nome, papel, ativo, senha, paginas, visoes) "
                    f"VALUES (%s, %s, %s, %s, %s, %s::text[], '{{}}') RETURNING {_COLUNAS}",
                    [login, nome, papel, ativo, novo["senha"], paginas]).fetchone()
        return publico(_usuario(linha))

    def definir_metas(self, mudancas: dict, con=None) -> None:
        """Pela configuração da página Metas: {login: {"ve": bool, "visoes": [ids], "vendedores": [ids] | None}}
        (vendedores None = todos os das abas). Confere tudo antes de gravar, para não salvar só metade."""
        with self._cadastro(con) as c:
            usuarios = {u["login"]: u for u in self._buscar(c)}
            novos = {}
            for login, m in (mudancas or {}).items():
                u = usuarios.get(login)
                if not u:
                    raise ValueError(f"usuário não encontrado: {login}")
                if u["papel"] == "admin":
                    continue  # administrador vê tudo
                visoes = [v for v in VISOES if v in (m.get("visoes") or [])]
                vendedores = m.get("vendedores")
                if vendedores is not None:
                    vendedores = sorted({int(v) for v in vendedores})
                paginas = _com_pagina(u, "metas", bool(m["ve"])) if "ve" in m else _paginas_de(u)
                if "metas" in paginas:
                    if not visoes:
                        raise ValueError(f"marque ao menos uma aba para {u['nome']}, ou desligue a página")
                    if vendedores is not None and not vendedores:
                        raise ValueError(f"marque ao menos um vendedor para {u['nome']}, ou escolha todos das abas")
                novos[u["id"]] = [visoes, vendedores, paginas]
            for id_, (visoes, vendedores, paginas) in novos.items():
                c.execute("UPDATE usuarios SET visoes = %s::text[], vendedores = %s::int[], paginas = %s::text[] "
                          "WHERE id = %s", [visoes, vendedores, paginas, id_])

    def definir_projecoes(self, mudancas: dict, con=None) -> None:
        """Pela configuração da página Projeções: {login: {"ve": bool, "modo": ..., "vendedores": [ids]}}."""
        self._definir_escopo("projecoes", mudancas, con)

    def definir_assistente(self, mudancas: dict, con=None) -> None:
        """Pela configuração da página Assistente, no mesmo formato de definir_projecoes."""
        self._definir_escopo("assistente", mudancas, con)

    def definir_gestao(self, mudancas: dict, con=None) -> None:
        """Pela configuração da página Gestão (os vendedores que a pessoa pode pôr nas campanhas), no mesmo formato."""
        self._definir_escopo("gestao", mudancas, con)

    def _definir_escopo(self, pagina: str, mudancas: dict, con=None) -> None:
        """Vendedores que cada usuário vê numa página de PAGINAS_COM_ESCOPO. Confere tudo antes de gravar, para
        não salvar só metade."""
        with self._cadastro(con) as c:
            usuarios = {u["login"]: u for u in self._buscar(c)}
            novos = {}
            for login, m in (mudancas or {}).items():
                u = usuarios.get(login)
                if not u:
                    raise ValueError(f"usuário não encontrado: {login}")
                if u["papel"] == "admin":
                    continue  # administrador vê tudo
                modo = m.get("modo", "metas")
                if modo not in MODOS_ESCOPO:
                    raise ValueError(f"modo inválido para {login}: {modo}")
                vendedores = sorted({int(v) for v in m.get("vendedores") or []}) if modo == "alguns" else None
                if modo == "alguns" and not vendedores:
                    raise ValueError(f"escolha ao menos um vendedor para {u['nome']}, ou outra opção")
                paginas = _com_pagina(u, pagina, bool(m["ve"])) if "ve" in m else _paginas_de(u)
                novos[u["id"]] = [json.dumps({"modo": modo, "vendedores": vendedores}), paginas]
            for id_, (escopo, paginas) in novos.items():
                c.execute(f"UPDATE usuarios SET escopo_{pagina} = %s::jsonb, paginas = %s::text[] WHERE id = %s",
                          [escopo, paginas, id_])

    def excluir(self, login: str) -> None:
        """Apaga o usuário; as conversas dele no Assistente vão junto (o registro de uso fica, sem o vínculo). As
        campanhas que ele criou na Gestão ficam, sem dono: só os administradores passam a vê-las."""
        with self._cadastro() as con:
            usuarios = {u["login"]: u for u in self._buscar(con)}
            if login not in usuarios:
                raise ValueError("usuário não encontrado")
            if not any(v["papel"] == "admin" and v["ativo"] for k, v in usuarios.items() if k != login):
                raise ValueError("precisa ficar pelo menos um administrador ativo")
            con.execute("DELETE FROM usuarios WHERE id = %s", [usuarios[login]["id"]])

    def trocar_senha(self, login: str, atual: str, nova: str) -> None:
        u = self._um("WHERE login = %s", [login])
        if not u or not confere_senha(atual or "", u["senha"]):
            raise ValueError("a senha atual não confere")
        self.definir_senha(login, nova)

    def definir_senha(self, login: str, nova: str, nome: str | None = None) -> None:
        """Troca a senha (e reativa o usuário). Se o login não existe, cria um administrador."""
        h = gerar_hash(_valida_senha(nova))
        with self._cadastro() as con:
            if con.execute("UPDATE usuarios SET senha = %s, ativo = true, sessao = sessao + 1 WHERE login = %s "
                           "RETURNING id", [h, login]).fetchone():
                return
            if not _LOGIN_VALIDO.match(login):
                raise ValueError("usuário inválido: use de 3 a 40 letras minúsculas, números, ponto, hífen ou sublinhado")
            con.execute("INSERT INTO usuarios (login, nome, papel, senha) VALUES (%s, %s, 'admin', %s)",
                        [login, nome or login, h])


# --- permissões -----------------------------------------------------------------------------
def eh_admin(usuario: dict | None) -> bool:
    return bool(usuario) and usuario["papel"] == "admin"


def paginas_permitidas(usuario: dict) -> list[str]:
    return list(PAGINAS) if eh_admin(usuario) else list(usuario["paginas"])


def equipes_permitidas(usuario: dict) -> set[str]:
    """Equipes (grupos de vendedor) das visões liberadas: o modo "igual a Metas" de Projeções usa isto."""
    return {g for v in visoes_permitidas(usuario) for g in VISOES[v]["grupos"]}


def escopo_projecoes(usuario: dict) -> tuple[set[int] | None, set[str] | None]:
    """(vendedores, equipes) que o usuário vê em Projeções; None = sem limite além dos vendedores da página."""
    return _escopo(usuario, "projecoes")


def escopo_assistente(usuario: dict) -> tuple[set[int] | None, set[str] | None]:
    """(vendedores, equipes) cujas vendas o usuário consulta no Assistente; None = sem limite."""
    return _escopo(usuario, "assistente")


def escopo_gestao(usuario: dict) -> tuple[set[int] | None, set[str] | None]:
    """(vendedores, equipes) que o usuário pode pôr nas campanhas da Gestão e ver no andamento; None = sem limite."""
    return _escopo(usuario, "gestao")


def escopo_sugestao(usuario: dict) -> tuple[set[int] | None, set[str] | None]:
    """(vendedores, equipes) que o usuário vê na Sugestão de Metas: os mesmos de Metas (as equipes das abas liberadas
    e os vendedores liberados); None = sem limite."""
    if eh_admin(usuario):
        return None, None
    return vendedores_permitidos(usuario), equipes_permitidas(usuario)


def escopo_premiacoes(usuario: dict) -> tuple[set[int] | None, set[str] | None]:
    """(vendedores, equipes) que o usuário vê em Premiações: os mesmos de Metas, como na Sugestão. A aba dos
    supervisores só aparece sem lista de vendedores (ela soma a carteira inteira do estado). None = sem limite."""
    if eh_admin(usuario):
        return None, None
    return vendedores_permitidos(usuario), equipes_permitidas(usuario)


def _escopo(usuario: dict, pagina: str) -> tuple[set[int] | None, set[str] | None]:
    if eh_admin(usuario):
        return None, None
    p = usuario.get(pagina) or ESCOPO_PADRAO
    if p["modo"] == "todos":
        return None, None
    if p["modo"] == "alguns":
        return set(p.get("vendedores") or []), None
    return vendedores_permitidos(usuario), equipes_permitidas(usuario)


def visoes_permitidas(usuario: dict) -> list[str]:
    return list(VISOES) if eh_admin(usuario) else [v for v in VISOES if v in (usuario["visoes"] or [])]


def vendedores_permitidos(usuario: dict) -> set[int] | None:
    """None = todos os vendedores das visões liberadas."""
    if eh_admin(usuario) or usuario["vendedores"] is None:
        return None
    return set(usuario["vendedores"])


# --- tentativas de login --------------------------------------------------------------------
class LimiteTentativas:
    """Depois de muitas senhas erradas seguidas, faz esperar alguns minutos (por login e por endereço)."""

    JANELA = 15 * 60
    LIMITES = {"login": 5, "ip": 20}

    def __init__(self):
        self._falhas: dict[str, collections.deque] = collections.defaultdict(collections.deque)
        self._trava = threading.Lock()

    def _limpa(self, chave: str, agora: float) -> collections.deque:
        fila = self._falhas[chave]
        while fila and fila[0] < agora - self.JANELA:
            fila.popleft()
        return fila

    def espera(self, login: str, ip: str) -> int:
        """Segundos que faltam para poder tentar de novo (0 = pode tentar)."""
        agora = time.time()
        with self._trava:
            maior = 0.0
            for tipo, chave in (("login", f"login:{login}"), ("ip", f"ip:{ip}")):
                fila = self._limpa(chave, agora)
                if len(fila) >= self.LIMITES[tipo]:
                    maior = max(maior, fila[0] + self.JANELA - agora)
            return int(maior) + (1 if maior else 0)

    def falhou(self, login: str, ip: str) -> None:
        agora = time.time()
        with self._trava:
            self._falhas[f"login:{login}"].append(agora)
            self._falhas[f"ip:{ip}"].append(agora)

    def acertou(self, login: str) -> None:
        with self._trava:
            self._falhas.pop(f"login:{login}", None)

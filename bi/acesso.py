"""Usuários, senhas e sessões do painel (gravados em usuarios.json, fora do repositório).

- Senha: PBKDF2-SHA256 com sal próprio; o arquivo nunca guarda a senha em si.
- Sessão: cookie assinado (HMAC) com o login, a validade e o contador de sessão do usuário. Trocar a senha,
  desativar ou excluir o usuário muda o contador e derruba as sessões abertas em outros aparelhos.
- Permissões: o administrador vê tudo e mexe nas configurações e em Usuários; o visualizador vê só as páginas
  liberadas em Usuários. O que ele vê dentro de cada página fica na configuração da página: em Metas, as visões
  (abas) marcadas e, se a lista de vendedores estiver preenchida, só esses vendedores (os totais também); em
  Projeções, igual a Metas (padrão), todos os vendedores da página ou só alguns.
"""
from __future__ import annotations

import base64
import collections
import copy
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from .configuracao import VISOES

PAPEIS = ("admin", "visualizador")
PAGINAS = {"metas": "Metas", "projecoes": "Projeções"}
PAGINAS_PADRAO = ["metas"]  # quem foi cadastrado antes de existir a escolha de páginas
MODOS_PROJECOES = ("metas", "todos", "alguns")  # igual ao acesso de Metas / todos os da página / só alguns
COOKIE = "mv_sessao"
DURACAO_SESSAO = 12 * 3600            # sem "manter conectado"
DURACAO_LEMBRAR = 30 * 24 * 3600      # com "manter conectado"
ITERACOES = 600_000
SENHA_MINIMA = 6
_LOGIN_VALIDO = re.compile(r"^[a-z0-9._-]{3,40}$")


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
def _paginas_de(u: dict) -> list[str]:
    return [p for p in PAGINAS if p in (u.get("paginas") or PAGINAS_PADRAO)]


def _com_pagina(u: dict, pagina: str, ve: bool) -> list[str]:
    """Páginas do usuário depois de ligar ou desligar uma delas na configuração da página."""
    paginas = [p for p in PAGINAS if (p in _paginas_de(u) and p != pagina) or (p == pagina and ve)]
    if not paginas:
        raise ValueError(f"{u['nome']} ficaria sem nenhuma página; libere outra em Usuários antes")
    return paginas


def publico(login: str, u: dict) -> dict:
    """O que a página pode ver de um usuário (sem a senha)."""
    admin = u["papel"] == "admin"
    return {
        "login": login, "nome": u["nome"], "papel": u["papel"], "ativo": u["ativo"],
        "visoes": None if admin else list(u.get("visoes") or []),
        "vendedores": None if admin else u.get("vendedores"),
        "paginas": None if admin else _paginas_de(u),
        "projecoes": None if u["papel"] == "admin" else (u.get("projecoes") or {"modo": "metas", "vendedores": None}),
        "criado_em": u.get("criado_em"), "ultimo_acesso": u.get("ultimo_acesso"),
    }


class Usuarios:
    def __init__(self, arquivo: str | Path):
        self.arquivo = Path(arquivo)
        self._trava = threading.Lock()
        if self.arquivo.exists():
            self._dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        else:
            self._dados = {"versao": 1, "segredo": secrets.token_hex(32), "usuarios": {}}
        self._segredo = bytes.fromhex(self._dados["segredo"])

    # --- leitura ---------------------------------------------------------------------------
    def vazio(self) -> bool:
        with self._trava:
            return not self._dados["usuarios"]

    def listar(self) -> list[dict]:
        with self._trava:
            return sorted((publico(k, u) for k, u in self._dados["usuarios"].items()),
                          key=lambda u: (u["papel"] != "admin", u["nome"].lower()))

    def obter(self, login: str) -> dict | None:
        with self._trava:
            u = self._dados["usuarios"].get(login)
            return publico(login, u) if u else None

    # --- login e sessão --------------------------------------------------------------------
    def autenticar(self, login: str, senha: str) -> dict | None:
        login = (login or "").strip().lower()
        with self._trava:
            u = copy.deepcopy(self._dados["usuarios"].get(login))
        if not confere_senha(senha or "", u["senha"] if u else _HASH_FALSO) or not u or not u["ativo"]:
            return None
        with self._trava:
            atual = self._dados["usuarios"].get(login)
            if atual:
                atual["ultimo_acesso"] = dt.datetime.now().isoformat(timespec="seconds")
                self._grava()
        return publico(login, u)

    def criar_sessao(self, login: str, lembrar: bool = False) -> tuple[str, int]:
        """Devolve o valor do cookie e a validade em segundos."""
        duracao = DURACAO_LEMBRAR if lembrar else DURACAO_SESSAO
        with self._trava:
            sessao = self._dados["usuarios"][login]["sessao"]
        corpo = _b64(json.dumps({"u": login, "s": sessao, "e": int(time.time()) + duracao, "l": lembrar}).encode())
        assinatura = _b64(hmac.new(self._segredo, corpo.encode(), hashlib.sha256).digest())
        return f"{corpo}.{assinatura}", duracao

    def da_sessao(self, cookie: str | None) -> dict | None:
        """Usuário dono do cookie, se a assinatura confere, não venceu e o usuário segue ativo."""
        if not cookie or "." not in cookie:
            return None
        corpo, assinatura = cookie.rsplit(".", 1)
        esperado = _b64(hmac.new(self._segredo, corpo.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(assinatura, esperado):
            return None
        try:
            d = json.loads(_de_b64(corpo))
        except ValueError:
            return None
        if d.get("e", 0) < time.time():
            return None
        with self._trava:
            u = self._dados["usuarios"].get(d.get("u"))
            if not u or not u["ativo"] or u["sessao"] != d.get("s"):
                return None
            return {**publico(d["u"], u), "lembrar": bool(d.get("l"))}

    # --- cadastro --------------------------------------------------------------------------
    def salvar(self, dados: dict, login_original: str | None = None) -> dict:
        """Cria (login_original vazio) ou altera um usuário: nome, login, senha, papel e páginas. O que a pessoa
        vê dentro de cada página fica como está (muda na configuração da página). Levanta ValueError."""
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

        with self._trava:
            usuarios = self._dados["usuarios"]
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
                # Sem abas de Metas até o administrador escolher em Metas › Configurar.
                u = {"sessao": 0, "criado_em": dt.datetime.now().isoformat(timespec="seconds"), "ultimo_acesso": None,
                     "visoes": [], "vendedores": None}
            novo = {**u, "nome": nome, "papel": papel, "ativo": ativo, "paginas": paginas}
            if senha:
                novo["senha"] = gerar_hash(_valida_senha(senha))
            if login_original and (senha or (u["ativo"] and not ativo)):
                novo["sessao"] = u["sessao"] + 1  # derruba as sessões abertas
            outros = {k: v for k, v in usuarios.items() if k != login_original}
            outros[login] = novo
            if usuarios and not any(v["papel"] == "admin" and v["ativo"] for v in outros.values()):
                raise ValueError("precisa ficar pelo menos um administrador ativo")
            if login_original and login != login_original:
                del usuarios[login_original]
            usuarios[login] = novo
            self._grava()
            return publico(login, novo)

    def definir_metas(self, mudancas: dict) -> None:
        """Pela configuração da página Metas: {login: {"ve": bool, "visoes": [ids], "vendedores": [ids] | None}}
        (vendedores None = todos os das abas). Confere tudo antes de gravar, para não salvar só metade."""
        with self._trava:
            usuarios = self._dados["usuarios"]
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
                novos[login] = {"visoes": visoes, "vendedores": vendedores, "paginas": paginas}
            for login, n in novos.items():
                usuarios[login].update(n)
            if novos:
                self._grava()

    def definir_projecoes(self, mudancas: dict) -> None:
        """Pela configuração da página Projeções: {login: {"ve": bool, "modo": ..., "vendedores": [ids]}}.
        Confere tudo antes de gravar, para não salvar só metade."""
        with self._trava:
            usuarios = self._dados["usuarios"]
            novos = {}
            for login, m in (mudancas or {}).items():
                u = usuarios.get(login)
                if not u:
                    raise ValueError(f"usuário não encontrado: {login}")
                if u["papel"] == "admin":
                    continue  # administrador vê tudo
                modo = m.get("modo", "metas")
                if modo not in MODOS_PROJECOES:
                    raise ValueError(f"modo inválido para {login}: {modo}")
                vendedores = sorted({int(v) for v in m.get("vendedores") or []}) if modo == "alguns" else None
                if modo == "alguns" and not vendedores:
                    raise ValueError(f"escolha ao menos um vendedor para {u['nome']}, ou outra opção")
                paginas = _com_pagina(u, "projecoes", bool(m["ve"])) if "ve" in m else _paginas_de(u)
                novos[login] = {"projecoes": {"modo": modo, "vendedores": vendedores}, "paginas": paginas}
            for login, n in novos.items():
                usuarios[login].update(n)
            if novos:
                self._grava()

    def excluir(self, login: str) -> None:
        with self._trava:
            usuarios = self._dados["usuarios"]
            if login not in usuarios:
                raise ValueError("usuário não encontrado")
            if not any(v["papel"] == "admin" and v["ativo"] for k, v in usuarios.items() if k != login):
                raise ValueError("precisa ficar pelo menos um administrador ativo")
            del usuarios[login]
            self._grava()

    def trocar_senha(self, login: str, atual: str, nova: str) -> None:
        with self._trava:
            u = self._dados["usuarios"].get(login)
        if not u or not confere_senha(atual or "", u["senha"]):
            raise ValueError("a senha atual não confere")
        self.definir_senha(login, nova)

    def definir_senha(self, login: str, nova: str, nome: str | None = None) -> None:
        """Troca a senha (e reativa o usuário). Se o login não existe, cria um administrador."""
        h = gerar_hash(_valida_senha(nova))
        with self._trava:
            u = self._dados["usuarios"].get(login)
            if u is None:
                if not _LOGIN_VALIDO.match(login):
                    raise ValueError("usuário inválido: use de 3 a 40 letras minúsculas, números, ponto, hífen ou sublinhado")
                self._dados["usuarios"][login] = {
                    "nome": nome or login, "papel": "admin", "ativo": True, "visoes": None, "vendedores": None,
                    "paginas": None,
                    "senha": h, "sessao": 0, "criado_em": dt.datetime.now().isoformat(timespec="seconds"),
                    "ultimo_acesso": None,
                }
            else:
                u.update(senha=h, ativo=True, sessao=u["sessao"] + 1)
            self._grava()

    def _grava(self) -> None:
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._dados, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.arquivo)


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
    if eh_admin(usuario):
        return None, None
    p = usuario.get("projecoes") or {"modo": "metas"}
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

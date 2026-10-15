"""BI de Metas Mais Vida — servidor local.

Uso:
    python app.py                 # abre o painel no navegador
    python app.py --sem-navegador # só sobe o servidor
    python app.py --porta 8051
    python app.py --senha LOGIN   # define a senha de um usuário (cria um administrador se não existir)

O painel fica em http://127.0.0.1:<porta>. Por padrão só aceita conexões desta máquina; com
`endereco = 0.0.0.0` no config.ini, outros computadores da rede entram com login e senha.
"""
from __future__ import annotations

import argparse
import configparser
import datetime as dt
import getpass
import json
import logging
import math
import mimetypes
import socket
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"

from bi.acesso import (COOKIE, LimiteTentativas, Usuarios, eh_admin, vendedores_permitidos,  # noqa: E402
                       visoes_permitidas)
from bi.cache import Cache  # noqa: E402
from bi.configuracao import VISOES, Configuracao  # noqa: E402
from bi.metas import Calculadora  # noqa: E402
from bi.planilhas import PlanilhaMonitorada, ler_metas, ler_metas_produtos  # noqa: E402

log = logging.getLogger("bi")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
# O navegador fechou a conexão (recarregou a página no meio da resposta): não é erro do painel.
CONEXAO_PERDIDA = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)
# Só o administrador usa: regras de cálculo, atualização forçada e cadastro de acessos.
ROTAS_ADMIN = {"/api/config", "/api/config/padrao", "/api/calendario", "/api/atualizar",
               "/api/usuarios", "/api/usuarios/excluir"}
# Cabeçalhos de proxy/túnel: com eles, a conexão não vem desta máquina mesmo chegando por 127.0.0.1.
CABECALHOS_PROXY = ("X-Forwarded-For", "Forwarded", "X-Real-IP", "CF-Connecting-IP")


def _json_padrao(o):
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"não serializável: {type(o)}")


class Aplicacao:
    def __init__(self, ini: configparser.ConfigParser):
        self.ini = ini
        self.cache = Cache(ini, RAIZ)
        self.metas = PlanilhaMonitorada(ini.get("planilhas", "metas"), ler_metas)
        self.metas_produtos = PlanilhaMonitorada(ini.get("planilhas", "metas_produtos"), ler_metas_produtos)
        self.configuracao = Configuracao(RAIZ / "config_metas.json")
        self.calc = Calculadora(self.cache, self.metas, self.metas_produtos, self.configuracao)
        self.usuarios = Usuarios(RAIZ / "usuarios.json")
        self.tentativas = LimiteTentativas()
        self._ultima_verificacao = 0.0

    def verificar_copia_nova(self) -> None:
        """Se a cópia do banco mudou desde a última extração, atualiza sozinho (no máximo a cada 60 s)."""
        agora = time.time()
        if agora - self._ultima_verificacao < 60:
            return
        self._ultima_verificacao = agora
        if self.cache.desatualizado() and not self.cache.estado["atualizando"]:
            log.info("cópia do banco mais nova encontrada; atualizando o cache")
            self.cache.atualizar_em_segundo_plano()

    def estado(self) -> dict:
        self.verificar_copia_nova()
        return {
            "pronto": self.cache.pronto(),
            "atualizacao": self.cache.estado,
            "data_ref": self.cache.info.get("data_ref"),
            "extraido_em": self.cache.info.get("extraido_em"),
            "banco_copia": self.cache.info.get("banco_copia"),
            "avisos": self.calc.avisos() if self.cache.pronto() else [],
        }


class Manipulador(BaseHTTPRequestHandler):
    app: Aplicacao = None  # definido em main()
    server_version = "BIMetasMaisVida/1.0"

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    # --- respostas -----------------------------------------------------------------------
    def _json(self, dados, status=HTTPStatus.OK, cookie: str | None = None):
        corpo = json.dumps(dados, ensure_ascii=False, default=_json_padrao).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _redireciona(self, destino: str):
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", destino)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _erro(self, mensagem, status=HTTPStatus.BAD_REQUEST):
        self._json({"erro": mensagem}, status)

    def _arquivo(self, caminho: Path):
        try:
            caminho = caminho.resolve()
            caminho.relative_to(WEB.resolve())
        except ValueError:
            return self._erro("não encontrado", HTTPStatus.NOT_FOUND)
        if not caminho.is_file():
            return self._erro("não encontrado", HTTPStatus.NOT_FOUND)
        corpo = caminho.read_bytes()
        tipo = mimetypes.guess_type(caminho.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo == "application/javascript":
            tipo += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo_json(self) -> dict:
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > 5_000_000:
            raise ValueError("requisição grande demais")
        return json.loads(self.rfile.read(tamanho) or b"{}")

    # --- acesso --------------------------------------------------------------------------
    def _usuario(self) -> dict | None:
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie") or "")
        except CookieError:
            return None
        sessao = cookies.get(COOKIE)
        return self.app.usuarios.da_sessao(sessao.value if sessao else None)

    def _local(self) -> bool:
        """Conexão feita nesta máquina (e não repassada por um proxy ou túnel)."""
        return (self.client_address[0] in ("127.0.0.1", "::1")
                and not any(self.headers.get(c) for c in CABECALHOS_PROXY))

    def _mesma_origem(self) -> bool:
        """Barra POST vindo de outro site (o navegador manda Origin nesses pedidos)."""
        origem = self.headers.get("Origin")
        return not origem or urlparse(origem).netloc == self.headers.get("Host")

    def _cookie_login(self, login: str, lembrar: bool) -> str:
        valor, duracao = self.app.usuarios.criar_sessao(login, lembrar)
        return f"{COOKIE}={valor}; Path=/; HttpOnly; SameSite=Lax" + (f"; Max-Age={duracao}" if lembrar else "")

    def _autorizado(self, usuario: dict | None, caminho: str) -> bool:
        if usuario is None:
            self._erro("faça login para continuar", HTTPStatus.UNAUTHORIZED)
            return False
        if caminho in ROTAS_ADMIN and not eh_admin(usuario):
            self._erro("só administradores podem fazer isso", HTTPStatus.FORBIDDEN)
            return False
        return True

    def _sessao(self, usuario: dict | None) -> dict:
        if usuario:
            usuario = {**usuario, "visoes": visoes_permitidas(usuario)}
        return {"usuario": usuario, "primeiro_acesso": self.app.usuarios.vazio(), "local": self._local()}

    def _login(self, corpo: dict):
        login = str(corpo.get("login") or "").strip().lower()
        ip = self.client_address[0]
        espera = self.app.tentativas.espera(login, ip)
        if espera:
            return self._erro(f"muitas tentativas erradas; tente de novo em {math.ceil(espera / 60)} min",
                              HTTPStatus.TOO_MANY_REQUESTS)
        usuario = self.app.usuarios.autenticar(login, str(corpo.get("senha") or ""))
        if not usuario:
            self.app.tentativas.falhou(login, ip)
            log.warning("login recusado para %r (%s)", login, ip)
            return self._erro("usuário ou senha incorretos", HTTPStatus.UNAUTHORIZED)
        self.app.tentativas.acertou(login)
        log.info("login de %s (%s)", login, ip)
        return self._json({"ok": True}, cookie=self._cookie_login(login, bool(corpo.get("lembrar"))))

    def _primeiro_acesso(self, corpo: dict):
        if not self.app.usuarios.vazio():
            return self._erro("o administrador já foi criado; entre com usuário e senha", HTTPStatus.CONFLICT)
        if not self._local():
            return self._erro("o primeiro acesso só pode ser criado no computador onde o painel está instalado",
                              HTTPStatus.FORBIDDEN)
        u = self.app.usuarios.salvar({**corpo, "papel": "admin", "ativo": True})
        log.info("administrador %s criado no primeiro acesso", u["login"])
        return self._json({"ok": True}, cookie=self._cookie_login(u["login"], False))

    def _salvar_usuario(self, eu: dict, corpo: dict):
        original = corpo.get("login_original") or None
        dados = corpo.get("usuario") or {}
        if original == eu["login"] and (dados.get("papel") != "admin" or not dados.get("ativo", True)):
            raise ValueError("você não pode tirar o próprio acesso de administrador; peça a outro administrador")
        u = self.app.usuarios.salvar(dados, original)
        log.info("%s %s o acesso de %s", eu["login"], "alterou" if original else "criou", u["login"])
        # Quem altera o próprio usuário (nome, login ou senha) continua conectado.
        cookie = self._cookie_login(u["login"], eu["lembrar"]) if original == eu["login"] else None
        return self._json({"ok": True, "usuario": u, "usuarios": self.app.usuarios.listar()}, cookie=cookie)

    # --- rotas ---------------------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            usuario = self._usuario()
            if url.path == "/api/sessao":
                return self._json(self._sessao(usuario))
            if url.path in ("/login", "/login.html"):
                return self._redireciona("/") if usuario else self._arquivo(WEB / "login.html")
            if url.path in ("/", "/index.html"):
                return self._arquivo(WEB / "index.html") if usuario else self._redireciona("/login")
            if not url.path.startswith("/api/"):
                return self._arquivo(WEB / url.path.lstrip("/"))  # CSS, JS e imagens: sem dados
            if not self._autorizado(usuario, url.path):
                return
            if url.path == "/api/estado":
                return self._json(self.app.estado())
            if url.path == "/api/opcoes":
                opcoes = self.app.calc.opcoes()
                permitidas = visoes_permitidas(usuario)
                opcoes["visoes"] = [v for v in opcoes["visoes"] if v["id"] in permitidas]
                return self._json(opcoes)
            if url.path == "/api/visao":
                visao = q.get("visao", "es")
                if visao not in visoes_permitidas(usuario):
                    return self._erro("seu acesso não inclui esta visão", HTTPStatus.FORBIDDEN)
                vendedor = int(q["vendedor"]) if q.get("vendedor") else None
                return self._json(self.app.calc.visao(visao, int(q["ano"]), int(q["mes"]), vendedor,
                                                      vendedores_permitidos(usuario)))
            if url.path == "/api/config":
                return self._json({"config": self.app.configuracao.atual(), "catalogo": self.app.calc.catalogo()})
            if url.path == "/api/calendario":
                return self._json(self.app.calc.calendario_ano(int(q.get("ano", dt.date.today().year))))
            if url.path == "/api/usuarios":
                return self._json({
                    "usuarios": self.app.usuarios.listar(),
                    "visoes": [{"id": k, "titulo": v["titulo"], "grupos": v["grupos"]} for k, v in VISOES.items()],
                    "vendedores": self.app.calc.vendedores_catalogo() if self.app.cache.pronto() else [],
                })
            return self._erro("rota desconhecida", HTTPStatus.NOT_FOUND)
        except CONEXAO_PERDIDA:
            return
        except RuntimeError as e:
            return self._erro(str(e), HTTPStatus.SERVICE_UNAVAILABLE)
        except (ValueError, KeyError) as e:
            return self._erro(f"parâmetro inválido: {e}")
        except Exception as e:
            log.error("erro em %s\n%s", self.path, traceback.format_exc())
            return self._erro(f"erro interno: {e}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            if not self._mesma_origem():
                return self._erro("pedido de outro site recusado", HTTPStatus.FORBIDDEN)
            if url.path == "/api/login":
                return self._login(self._corpo_json())
            if url.path == "/api/primeiro-acesso":
                return self._primeiro_acesso(self._corpo_json())
            if url.path == "/api/sair":
                return self._json({"ok": True}, cookie=f"{COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
            usuario = self._usuario()
            if not self._autorizado(usuario, url.path):
                return
            if url.path == "/api/minha-senha":
                corpo = self._corpo_json()
                self.app.usuarios.trocar_senha(usuario["login"], corpo.get("atual"), corpo.get("nova"))
                log.info("%s trocou a própria senha", usuario["login"])
                return self._json({"ok": True}, cookie=self._cookie_login(usuario["login"], usuario["lembrar"]))
            if url.path == "/api/usuarios":
                return self._salvar_usuario(usuario, self._corpo_json())
            if url.path == "/api/usuarios/excluir":
                login = str(self._corpo_json().get("login") or "")
                if login == usuario["login"]:
                    raise ValueError("você não pode excluir o próprio acesso")
                self.app.usuarios.excluir(login)
                log.info("%s excluiu o acesso de %s", usuario["login"], login)
                return self._json({"ok": True, "usuarios": self.app.usuarios.listar()})
            if url.path == "/api/config":
                cfg = self.app.configuracao.salvar(self._corpo_json())
                return self._json({"ok": True, "config": cfg})
            if url.path == "/api/config/padrao":
                return self._json({"ok": True, "config": self.app.configuracao.restaurar_padrao()})
            if url.path == "/api/calendario":
                corpo = self._corpo_json()
                return self._json(self.app.calc.calendario_ano(int(corpo["ano"]), corpo.get("config")))
            if url.path == "/api/atualizar":
                iniciou = self.app.cache.atualizar_em_segundo_plano()
                return self._json({"ok": True, "iniciou": iniciou})
            return self._erro("rota desconhecida", HTTPStatus.NOT_FOUND)
        except CONEXAO_PERDIDA:
            return
        except (ValueError, KeyError) as e:
            return self._erro(str(e))
        except Exception as e:
            log.error("erro em %s\n%s", self.path, traceback.format_exc())
            return self._erro(f"erro interno: {e}", HTTPStatus.INTERNAL_SERVER_ERROR)


def definir_senha(login: str) -> None:
    """Uso pelo terminal: recupera o acesso quando ninguém lembra a senha de administrador."""
    login = login.strip().lower()
    usuarios = Usuarios(RAIZ / "usuarios.json")
    existe = usuarios.obter(login) is not None
    print(f"{'Nova senha para' if existe else 'Criando o administrador'} {login}")
    senha = getpass.getpass("Senha: ")
    if senha != getpass.getpass("Repita a senha: "):
        sys.exit("As senhas não conferem.")
    try:
        usuarios.definir_senha(login, senha)
    except ValueError as e:
        sys.exit(f"Não foi possível: {e}.")
    print("Pronto. As sessões abertas desse usuário foram encerradas." if existe else "Administrador criado.")


def enderecos_na_rede() -> list[str]:
    try:
        return sorted({ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127.")})
    except OSError:
        return []


def main() -> None:
    ap = argparse.ArgumentParser(description="BI de Metas Mais Vida")
    ap.add_argument("--porta", type=int)
    ap.add_argument("--endereco", help="127.0.0.1 = só esta máquina; 0.0.0.0 = toda a rede")
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--senha", metavar="LOGIN", help="define a senha do usuário (cria um administrador se não existir)")
    args = ap.parse_args()
    if args.senha:
        return definir_senha(args.senha)

    # config.exemplo.ini traz os caminhos padrão; o config.ini (opcional, fora do repositório) sobrepõe o que
    # tiver, como a senha do banco. Sem ele o painel abre do mesmo jeito e avisa que falta a senha.
    ini = configparser.ConfigParser()
    ini.read([RAIZ / "config.exemplo.ini", RAIZ / "config.ini"], encoding="utf-8")
    porta = args.porta or ini.getint("servidor", "porta", fallback=8050)
    endereco = args.endereco or ini.get("servidor", "endereco", fallback="127.0.0.1")

    (RAIZ / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(RAIZ / "logs" / "bi.log", encoding="utf-8")])

    if not (RAIZ / "config.ini").exists():
        log.warning("sem config.ini: usando os caminhos de config.exemplo.ini; o ERP só é lido depois que "
                    "config.ini tiver a senha do banco")
    app = Aplicacao(ini)
    Manipulador.app = app
    if app.cache.desatualizado():
        log.info("preparando os dados a partir da cópia do banco…")
        app.cache.atualizar_em_segundo_plano()

    servidor = ThreadingHTTPServer((endereco, porta), Manipulador)
    local = f"http://127.0.0.1:{porta}"
    log.info("BI de Metas no ar em %s (Ctrl+C para encerrar)", local)
    if endereco not in ("127.0.0.1", "localhost"):
        for ip in enderecos_na_rede():
            log.info("outros computadores da rede: http://%s:%s", ip, porta)
    if app.usuarios.vazio():
        log.info("nenhum usuário cadastrado: abra %s neste computador para criar o administrador", local)
    if not args.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(local)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()

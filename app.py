"""BI de Metas Mais Vida — servidor local.

Uso:
    python app.py                 # abre o painel no navegador
    python app.py --sem-navegador # só sobe o servidor
    python app.py --porta 8051

O painel fica em http://127.0.0.1:<porta>. Só aceita conexões desta máquina.
"""
from __future__ import annotations

import argparse
import configparser
import datetime as dt
import json
import logging
import mimetypes
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"

from bi.cache import Cache  # noqa: E402
from bi.configuracao import Configuracao  # noqa: E402
from bi.metas import Calculadora  # noqa: E402
from bi.planilhas import PlanilhaMonitorada, ler_metas, ler_metas_produtos  # noqa: E402

log = logging.getLogger("bi")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
# O navegador fechou a conexão (recarregou a página no meio da resposta): não é erro do painel.
CONEXAO_PERDIDA = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)


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
    def _json(self, dados, status=HTTPStatus.OK):
        corpo = json.dumps(dados, ensure_ascii=False, default=_json_padrao).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

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

    # --- rotas ---------------------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/estado":
                return self._json(self.app.estado())
            if url.path == "/api/opcoes":
                return self._json(self.app.calc.opcoes())
            if url.path == "/api/visao":
                vendedor = int(q["vendedor"]) if q.get("vendedor") else None
                return self._json(self.app.calc.visao(q.get("visao", "es"), int(q["ano"]), int(q["mes"]), vendedor))
            if url.path == "/api/config":
                return self._json({"config": self.app.configuracao.atual(), "catalogo": self.app.calc.catalogo()})
            if url.path == "/api/calendario":
                return self._json(self.app.calc.calendario_ano(int(q.get("ano", dt.date.today().year))))
            if url.path.startswith("/api/"):
                return self._erro("rota desconhecida", HTTPStatus.NOT_FOUND)
            if url.path in ("/", "/index.html"):
                return self._arquivo(WEB / "index.html")
            return self._arquivo(WEB / url.path.lstrip("/"))
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


def main() -> None:
    if not (RAIZ / "config.ini").exists():
        sys.exit("Falta o config.ini: copie config.exemplo.ini para config.ini e preencha a senha do banco.")
    ini = configparser.ConfigParser()
    ini.read(RAIZ / "config.ini", encoding="utf-8")
    ap = argparse.ArgumentParser(description="BI de Metas Mais Vida")
    ap.add_argument("--porta", type=int, default=ini.getint("servidor", "porta", fallback=8050))
    ap.add_argument("--sem-navegador", action="store_true")
    args = ap.parse_args()

    (RAIZ / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(RAIZ / "logs" / "bi.log", encoding="utf-8")])

    app = Aplicacao(ini)
    Manipulador.app = app
    if app.cache.desatualizado():
        log.info("preparando os dados a partir da cópia do banco…")
        app.cache.atualizar_em_segundo_plano()

    servidor = ThreadingHTTPServer(("127.0.0.1", args.porta), Manipulador)
    endereco = f"http://127.0.0.1:{args.porta}"
    log.info("BI de Metas no ar em %s (Ctrl+C para encerrar)", endereco)
    if not args.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(endereco)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()

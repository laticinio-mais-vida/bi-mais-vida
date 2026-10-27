"""BI de Metas Mais Vida — servidor local.

Uso:
    python app.py                 # abre o painel no navegador
    python app.py --sem-navegador # só sobe o servidor
    python app.py --porta 8051
    python app.py --senha LOGIN   # define a senha de um usuário (cria um administrador se não existir); no
                                  # VPS: docker compose exec bi python app.py --senha LOGIN
    python app.py --gerar-chave   # gera a chave de [publicacao], a mesma no PC e no VPS

O painel fica em http://127.0.0.1:<porta>. Por padrão só aceita conexões desta máquina; com
`endereco = 0.0.0.0` no config.ini, outros computadores da rede entram com login e senha.
Com `modo = vps` em [publicacao], não lê o banco do ERP: recebe os dados do computador da empresa (bi/publicacao.py).
Usuários, regras, conversas, o uso do Assistente, as campanhas da Gestão e a Agenda ficam no PostgreSQL de [postgres]
(bi/banco.py), no PC e no VPS.
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
import unicodedata
import webbrowser
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"

from bi.acesso import (COOKIE, PAGINAS, LimiteTentativas, Usuarios, eh_admin, escopo_assistente,  # noqa: E402
                       escopo_gestao, escopo_projecoes, escopo_sugestao, paginas_permitidas, vendedores_permitidos,
                       visoes_permitidas)
from bi.agenda import Agenda  # noqa: E402
from bi.aprovacao import MetasAprovadas, MetasComAprovadas  # noqa: E402
from bi.assistente import Assistente, ErroAssistente  # noqa: E402
from bi.banco import Banco, BancoForaDoAr  # noqa: E402
from bi.cache import Cache  # noqa: E402
from bi.carteira import Carteira  # noqa: E402
from bi.configuracao import VISOES, Configuracao  # noqa: E402
from bi.credito import Credito  # noqa: E402
from bi.conversas import Conversas, NaoEncontrada, id_valido  # noqa: E402
from bi.gestao import PRORROGAR, Gestao  # noqa: E402
from bi.metas import Calculadora  # noqa: E402
from bi.planilhas import PlanilhaMonitorada, ler_metas, ler_metas_produtos  # noqa: E402
from bi.projecoes import ConfigProjecoes, Projetor, SemVendedores  # noqa: E402
from bi.publicacao import ROTA as ROTA_RECEBER, Envio, Recebimento, Recusado, gerar_chave  # noqa: E402
from bi.sugestao import ConfigSugestao, Sugestao  # noqa: E402
from bi.tarefas import Tarefas  # noqa: E402
from bi.uso import RegistroUso  # noqa: E402

log = logging.getLogger("bi")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
# O navegador fechou a conexão (recarregou a página no meio da resposta): não é erro do painel.
CONEXAO_PERDIDA = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)
# Página Gestão: quem tem a página lê; só o administrador lança e muda campanhas, objetivos e observações.
ROTAS_GESTAO_LER = ("/api/gestao", "/api/gestao/vendedor", "/api/gestao/acao", "/api/gestao/catalogo",
                    "/api/gestao/rascunho")
ROTAS_GESTAO_MUDAR = {"/api/gestao/acoes", "/api/gestao/acao/editar", "/api/gestao/acao/encerrar",
                      "/api/gestao/acao/prorrogar", "/api/gestao/acao/arquivar", "/api/gestao/acao/excluir",
                      "/api/gestao/objetivos", "/api/gestao/objetivo/editar", "/api/gestao/objetivo/excluir",
                      "/api/gestao/notas", "/api/gestao/nota/excluir", "/api/gestao/base"}
# Agenda, no topo da página Gestão: quem tem a Gestão lê e muda só a própria agenda (bi/agenda.py filtra pelo
# usuário) e as tarefas de que participa (bi/tarefas.py confere quem pode o quê). Por isso não entra em ROTAS_ADMIN,
# como as rotas que mudam a Gestão.
ROTAS_AGENDA_LER = ("/api/agenda", "/api/agenda/historico", "/api/agenda/pessoas", "/api/agenda/tarefa",
                    "/api/agenda/quadro")
ROTAS_AGENDA_MUDAR = {"/api/agenda/atividades", "/api/agenda/atividade/editar", "/api/agenda/atividade/encerrar",
                      "/api/agenda/atividade/excluir", "/api/agenda/concluir", "/api/agenda/desfazer",
                      "/api/agenda/proposta", "/api/agenda/tarefas", "/api/agenda/tarefa/editar",
                      "/api/agenda/tarefa/excluir", "/api/agenda/tarefa/concluir", "/api/agenda/tarefa/desfazer",
                      "/api/agenda/tarefa/mover", "/api/agenda/tarefa/justificar", "/api/agenda/subtarefas",
                      "/api/agenda/subtarefa/editar", "/api/agenda/subtarefa/concluir",
                      "/api/agenda/subtarefa/desfazer", "/api/agenda/subtarefa/mover", "/api/agenda/subtarefa/justificar"}
# Só o administrador usa: regras de cálculo, atualização forçada, cadastro de acessos e o que muda na Gestão.
ROTAS_ADMIN = {"/api/config", "/api/config/padrao", "/api/calendario", "/api/atualizar",
               "/api/usuarios", "/api/usuarios/excluir", "/api/projecoes/config", "/api/sugestao/config",
               "/api/sugestao/aprovacao", "/api/assistente/config",
               "/api/gestao/config", *ROTAS_GESTAO_MUDAR}
# Cabeçalhos de proxy/túnel: com eles, a conexão não vem desta máquina mesmo chegando por 127.0.0.1.
CABECALHOS_PROXY = ("X-Forwarded-For", "Forwarded", "X-Real-IP", "CF-Connecting-IP")
PAGINAS_HTML = ("/", "/index.html", "/login", "/login.html")


def _json_padrao(o):
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"não serializável: {type(o)}")


class Aplicacao:
    def __init__(self, ini: configparser.ConfigParser):
        self.ini = ini
        self.modo = ini.get("publicacao", "modo", fallback="local").strip().lower()
        if self.modo not in ("local", "vps"):
            raise SystemExit(f"[publicacao] modo = {self.modo!r} no config.ini: use local ou vps")
        self.vps = self.modo == "vps"
        self.cache = Cache(ini, RAIZ)
        if self.vps:  # as planilhas chegam junto com o cache e ficam ao lado dele
            planilhas = {"metas": self.cache.arquivo.parent / "METAS.xlsx",
                         "metas_produtos": self.cache.arquivo.parent / "METAS PRODUTOS.xlsx"}
        else:
            planilhas = {"metas": Path(ini.get("planilhas", "metas")),
                         "metas_produtos": Path(ini.get("planilhas", "metas_produtos"))}
        self.metas = PlanilhaMonitorada(planilhas["metas"], ler_metas)
        self.metas_produtos = PlanilhaMonitorada(planilhas["metas_produtos"], ler_metas_produtos)
        # Banco PostgreSQL ([postgres] no config.ini): usuários, regras, conversas e uso do Assistente. Nada aqui
        # conecta: a extração e o envio ao VPS (vigiar_em_segundo_plano) seguem mesmo com o banco fora do ar.
        self.banco = Banco(ini, raiz=RAIZ)
        if not self.vps:  # o PC registra a carteira a cada extração; o VPS recebe o histórico pronto no cache
            self.cache.carteira = Carteira(self.banco)
        self.usuarios = Usuarios(self.banco)
        self.configuracao = Configuracao(self.banco)
        # As metas aprovadas na Sugestão de Metas valem por cima das planilhas (do mesmo vendedor e mês) para tudo que
        # lê as metas pela Calculadora; o envio e o recebimento das planilhas continuam com os arquivos.
        self.metas_aprovadas = MetasAprovadas(self.banco)
        self.calc = Calculadora(self.cache, MetasComAprovadas(self.metas, self.metas_aprovadas, "metas"),
                                MetasComAprovadas(self.metas_produtos, self.metas_aprovadas, "produtos"),
                                self.configuracao)
        self.config_projecoes = ConfigProjecoes(self.banco)
        self.projetor = Projetor(self.calc, self.config_projecoes)
        self.credito = Credito(self.cache, self.projetor._nomes_vendedores)
        self.conversas = Conversas(self.banco)
        self.assistente = Assistente(ini, self.calc, self.projetor._nomes_vendedores, RegistroUso(self.banco),
                                     conversas=self.conversas)
        self.gestao = Gestao(self.banco, self.calc, self.assistente)
        self.config_sugestao = ConfigSugestao(self.banco)
        # Os faturamentos das áreas do BA saem dos dias de atendimento que a Gestão guarda.
        self.sugestao = Sugestao(self.calc, self.config_sugestao, self.gestao._areas, self.projetor._nomes_vendedores,
                                 self.metas_aprovadas)
        self.agenda = Agenda(self.banco, self.configuracao)
        self.tarefas = Tarefas(self.banco)
        self.tentativas = LimiteTentativas()
        self.envio = None if self.vps else Envio(ini, self.cache, planilhas)
        self.recebimento = (Recebimento(ini, self.cache, {"metas": self.metas, "metas_produtos": self.metas_produtos})
                            if self.vps else None)
        self._ultima_verificacao = 0.0

    def vigiar_em_segundo_plano(self) -> None:
        """No PC: percebe a cópia nova do banco e envia ao VPS mesmo sem nenhum navegador aberto."""
        if self.vps:
            return

        def laco():
            while True:
                try:
                    self.verificar_copia_nova()
                    self.envio.verificar()
                except Exception:
                    log.exception("falha na verificação em segundo plano")
                time.sleep(30)

        threading.Thread(target=laco, name="vigia", daemon=True).start()

    def recebido_em(self) -> str | None:
        try:
            return dt.datetime.fromtimestamp(self.cache.arquivo.stat().st_mtime).isoformat(timespec="minutes")
        except OSError:
            return None

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
        atualizacao = self.cache.estado
        if self.vps:
            if not self.cache.pronto():
                atualizacao = {**atualizacao, "etapa": "Aguardando o primeiro envio do computador da empresa"}
        else:
            self.verificar_copia_nova()
        return {
            "modo": self.modo,
            "pronto": self.cache.pronto(),
            "atualizacao": atualizacao,
            "data_ref": self.cache.info.get("data_ref"),
            "extraido_em": self.cache.info.get("extraido_em"),
            "banco_copia": self.cache.info.get("banco_copia"),
            "recebido_em": self.recebido_em() if self.vps else None,
            "envio": self.envio.estado if self.envio and self.envio.ativo else None,
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

    def _banco_fora_do_ar(self, e: BancoForaDoAr):
        log.warning("banco de dados fora do ar em %s: %s", self.path, e)
        return self._erro(e.aviso, HTTPStatus.SERVICE_UNAVAILABLE)

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

    def _baixavel(self, corpo: bytes, tipo: str, nome: str):
        """Arquivo para baixar. O nome com acentos vai em filename* (RFC 6266); filename leva a versão sem acento."""
        simples = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().replace('"', "")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Disposition", f"attachment; filename=\"{simples}\"; filename*=UTF-8''{quote(nome)}")
        self.send_header("Cache-Control", "no-store")
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

    def _ip(self) -> str:
        """IP de quem pediu. No VPS tudo chega pelo Caddy; sem isto, 20 senhas erradas de qualquer pessoa
        bloqueariam o login de todo mundo (todos teriam o IP do Caddy)."""
        if self.app.vps and self.headers.get("X-Forwarded-For"):
            return self.headers["X-Forwarded-For"].split(",")[-1].strip()
        return self.client_address[0]

    def _mesma_origem(self) -> bool:
        """Barra POST vindo de outro site (o navegador manda Origin nesses pedidos)."""
        origem = self.headers.get("Origin")
        return not origem or urlparse(origem).netloc == self.headers.get("Host")

    def _cookie_login(self, id_: int, lembrar: bool) -> str:
        valor, duracao = self.app.usuarios.criar_sessao(id_, lembrar)
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
            usuario = {**usuario, "visoes": visoes_permitidas(usuario), "paginas": paginas_permitidas(usuario)}
        return {"usuario": usuario, "primeiro_acesso": self.app.usuarios.vazio(), "local": self._local(),
                "modo": self.app.modo}

    def _login(self, corpo: dict):
        login = str(corpo.get("login") or "").strip().lower()
        ip = self._ip()
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
        return self._json({"ok": True}, cookie=self._cookie_login(usuario["id"], bool(corpo.get("lembrar"))))

    def _primeiro_acesso(self, corpo: dict):
        if not self.app.usuarios.vazio():
            return self._erro("o administrador já foi criado; entre com usuário e senha", HTTPStatus.CONFLICT)
        if not self._local():
            return self._erro("o primeiro acesso só pode ser criado no computador onde o painel está instalado",
                              HTTPStatus.FORBIDDEN)
        u = self.app.usuarios.salvar({**corpo, "papel": "admin", "ativo": True}, primeiro=True)
        log.info("administrador %s criado no primeiro acesso", u["login"])
        return self._json({"ok": True}, cookie=self._cookie_login(u["id"], False))

    def _salvar_usuario(self, eu: dict, corpo: dict):
        original = corpo.get("login_original") or None
        dados = corpo.get("usuario") or {}
        if original == eu["login"] and (dados.get("papel") != "admin" or not dados.get("ativo", True)):
            raise ValueError("você não pode tirar o próprio acesso de administrador; peça a outro administrador")
        u = self.app.usuarios.salvar(dados, original)
        log.info("%s %s o acesso de %s", eu["login"], "alterou" if original else "criou", u["login"])
        # Quem altera o próprio usuário (nome, login ou senha) continua conectado.
        cookie = self._cookie_login(u["id"], eu["lembrar"]) if original == eu["login"] else None
        return self._json({"ok": True, "usuario": u, "usuarios": self.app.usuarios.listar()}, cookie=cookie)

    def _visualizadores(self) -> dict:
        """Quem a configuração de uma página lista em "Acesso por usuário" (administrador vê tudo)."""
        return {
            "usuarios": [u for u in self.app.usuarios.listar() if u["papel"] != "admin"],
            "visoes": [{"id": k, "titulo": v["titulo"], "grupos": v["grupos"]} for k, v in VISOES.items()],
        }

    def _config_projecoes(self) -> dict:
        """Configuração da página Projeções: vendedores da página e o que cada visualizador vê nela."""
        return {**self.app.projetor.catalogo(), **self._visualizadores()}

    def _config_assistente(self) -> dict:
        """Configuração da página Assistente: o que cada visualizador consulta e o uso dos últimos 30 dias."""
        return {"vendedores": self.app.assistente.catalogo_vendedores(), "uso": self.app.assistente.uso(),
                "data_ref": self.app.cache.info.get("data_ref"), **self._visualizadores()}

    def _config_gestao(self) -> dict:
        """Configuração da página Gestão: os vendedores que cada visualizador acompanha (as campanhas, os objetivos e o
        histórico deles) e os dias de atendimento das áreas comerciais (efetividade)."""
        return {"vendedores": self.app.assistente.catalogo_vendedores(),
                "data_ref": self.app.cache.info.get("data_ref"), **self._visualizadores(),
                **self.app.gestao.config_areas()}

    def _salvar_config_gestao(self, usuario: dict, corpo: dict):
        """Acessos e dias de atendimento numa transação só: ou grava tudo, ou nada."""
        with self.app.banco.conexao() as con:
            self.app.usuarios.definir_gestao(corpo.get("usuarios") or {}, con)
            self.app.gestao.definir_areas(usuario, corpo.get("areas") or {}, con)
        log.info("%s salvou a configuração da Gestão", usuario["login"])
        return self._json({"ok": True, **self._config_gestao()})

    def _pode_gestao(self, usuario: dict) -> bool:
        if "gestao" in paginas_permitidas(usuario):
            return True
        self._erro("seu acesso não inclui a página Gestão", HTTPStatus.FORBIDDEN)
        return False

    def _ler_gestao(self, usuario: dict, caminho: str, q: dict):
        if not self._pode_gestao(usuario):
            return
        gestao, escopo = self.app.gestao, escopo_gestao(usuario)
        if caminho == "/api/gestao":  # o quadro de uma região (sem região: a primeira do acesso)
            return self._json(gestao.quadro(usuario, escopo, q.get("regiao")))
        if caminho == "/api/gestao/vendedor":  # o histórico interno de um vendedor
            return self._json(gestao.historico(usuario, escopo, q.get("id")))
        if caminho == "/api/gestao/acao":  # campanha ou objetivo; abrir: area, segmento ou produto (vazio = nenhuma)
            return self._json(gestao.detalhe(usuario, escopo, q.get("id"), q.get("abrir", "padrao")))
        if caminho == "/api/gestao/catalogo":
            return self._json(gestao.catalogo(escopo))
        # /api/gestao/rascunho: o rascunho que o Assistente montou numa conversa da pessoa, para revisar na página
        rascunho = self.app.conversas.rascunho(usuario["id"], q.get("id"))
        if rascunho is None:
            raise NaoEncontrada("rascunho não encontrado; peça de novo ao Assistente")
        lancada = gestao.criadas_por_rascunho(usuario, [rascunho["id"]]).get(rascunho["id"])
        return self._json({"rascunho": rascunho, "acao": lancada})

    def _mudar_gestao(self, usuario: dict, caminho: str, corpo: dict):
        if not self._pode_gestao(usuario):
            return
        gestao = self.app.gestao
        if caminho in ("/api/gestao/acoes", "/api/gestao/objetivos"):
            tipo = "acao" if caminho == "/api/gestao/acoes" else "objetivo"
            r = gestao.criar(usuario, corpo.get(tipo) or {}, tipo, corpo.get("rascunho"))
            if not r["ja_existia"]:
                log.info("%s lançou %s %s%s", usuario["login"], "a campanha" if tipo == "acao" else "o objetivo", r["id"],
                         " (rascunho do Assistente)" if corpo.get("rascunho") else "")
            return self._json({"ok": True, **r})
        if caminho == "/api/gestao/base":  # a prévia da base dos vendedores no formulário da campanha (não grava)
            return self._json(gestao.previa_base(usuario, corpo.get("campanha") or {}, corpo.get("ids")))
        if caminho == "/api/gestao/notas":
            return self._json({"ok": True, "evento": gestao.anotar(usuario, corpo.get("id_vendedor"), corpo.get("texto"))})
        if caminho == "/api/gestao/nota/excluir":
            gestao.excluir_nota(usuario, corpo.get("id"))
            return self._json({"ok": True})
        id_ = corpo.get("id")
        tipo = "objetivo" if caminho.startswith("/api/gestao/objetivo/") else "acao"
        oque = caminho.rsplit("/", 1)[-1]
        if oque == "editar":
            gestao.atualizar(usuario, id_, corpo.get(tipo) or {}, tipo)
        elif oque == "encerrar":
            gestao.encerrar(usuario, id_)
            log.info("%s encerrou a campanha %s", usuario["login"], id_)
        elif oque == "prorrogar":
            gestao.prorrogar(usuario, id_, corpo.get("dias", PRORROGAR))
            log.info("%s prorrogou a campanha %s", usuario["login"], id_)
        elif oque == "arquivar":
            gestao.arquivar(usuario, id_, corpo.get("arquivada", True) is not False)
        else:  # excluir
            gestao.excluir(usuario, id_)
            log.info("%s excluiu %s %s", usuario["login"], "a campanha" if tipo == "acao" else "o objetivo", id_)
        return self._json({"ok": True})

    def _pode_assistente(self, usuario: dict) -> bool:
        if "assistente" in paginas_permitidas(usuario):
            return True
        self._erro("seu acesso não inclui o Assistente", HTTPStatus.FORBIDDEN)
        return False

    def _perguntar(self, usuario: dict, corpo: dict):
        """Uma pergunta ao Assistente, {conversa, pergunta} (espera a resposta inteira: costuma levar de 10 s a
        1 min). O servidor lê a conversa do banco; sem conversa, começa uma nova."""
        if not self._pode_assistente(usuario):
            return
        vendedores, equipes = escopo_assistente(usuario)
        tem_gestao = "gestao" in paginas_permitidas(usuario)
        gestao = self.app.gestao.contexto(usuario, escopo_gestao(usuario)) if tem_gestao else None
        agenda = self.app.agenda.contexto(usuario["id"]) if tem_gestao else None  # a agenda fica na Gestão
        sugestao = ((self.app.sugestao, *escopo_sugestao(usuario)) if "sugestao" in paginas_permitidas(usuario)
                    else None)
        try:
            return self._json(self.app.assistente.perguntar(usuario, corpo.get("conversa"), corpo.get("pergunta"),
                                                            vendedores, equipes, gestao,
                                                            "credito" in paginas_permitidas(usuario), agenda=agenda,
                                                            sugestao=sugestao))
        except ErroAssistente as e:
            log.warning("Assistente (%s): %s", usuario["login"], e)
            return self._erro(str(e), e.status)

    def _ler_historico(self, usuario: dict, caminho: str, q: dict):
        if not self._pode_assistente(usuario):
            return
        conversas, dono = self.app.conversas, usuario["id"]
        # A pergunta em andamento é lida antes da conversa: ela só sai daqui depois de a resposta estar gravada.
        pendente = self.app.assistente.pendente(dono)
        if caminho == "/api/assistente/conversas":
            return self._json({"conversas": conversas.listar(dono, q.get("busca")), "pendente": pendente})
        id_ = id_valido(q.get("id"))
        pendente = pendente if pendente and pendente["conversa"] == id_ else None
        conversa = conversas.obter(dono, id_) if id_ else None
        if conversa is None and pendente is None:
            raise NaoEncontrada("conversa não encontrada; ela pode ter sido excluída")
        rascunhos = [r for m in (conversa or {}).get("mensagens", []) for r in m.get("rascunhos") or []]
        if rascunhos and "gestao" in paginas_permitidas(usuario):  # os que já viraram campanha mostram o link
            lancadas = self.app.gestao.criadas_por_rascunho(usuario, [r["id"] for r in rascunhos])
            for r in rascunhos:
                r["acao"] = lancadas.get(r["id"])
        propostas = [p for m in (conversa or {}).get("mensagens", []) for p in m.get("agenda") or []]
        if propostas and "gestao" in paginas_permitidas(usuario):  # as que já foram aplicadas mostram o link
            aplicadas = self.app.agenda.aplicadas(usuario["id"], [p.get("id") for p in propostas])
            for p in propostas:
                p["aplicada"] = aplicadas.get(p.get("id"))
        return self._json({"conversa": conversa, "pendente": pendente})

    def _baixar_arquivo(self, usuario: dict, q: dict):
        """Um arquivo (Excel ou PDF) que o Assistente preparou numa conversa da pessoa, montado agora com o acesso de
        agora (só o dono da conversa encontra o arquivo)."""
        if not self._pode_assistente(usuario):
            return
        achado = self.app.conversas.arquivo(usuario["id"], q.get("id"))
        if achado is None:
            raise NaoEncontrada("arquivo não encontrado; a conversa pode ter sido excluída")
        arquivo, texto = achado
        vendedores, equipes = escopo_assistente(usuario)
        try:
            conteudo, nome, tipo = self.app.assistente.arquivo(usuario, arquivo, texto, vendedores, equipes,
                                                               "credito" in paginas_permitidas(usuario))
        except ErroAssistente as e:
            log.warning("arquivo do Assistente (%s): %s", usuario["login"], e)
            return self._erro(str(e), e.status)
        log.info("%s baixou %s (%s KB)", usuario["login"], nome, len(conteudo) // 1024)
        return self._baixavel(conteudo, tipo, nome)

    def _mudar_historico(self, usuario: dict, caminho: str, corpo: dict):
        if not self._pode_assistente(usuario):
            return
        conversas, dono = self.app.conversas, usuario["id"]
        if caminho == "/api/assistente/conversa/renomear":
            return self._json({"ok": True, "conversa": conversas.renomear(dono, corpo.get("id"), corpo.get("titulo"))})
        pendente = self.app.assistente.pendente(dono)
        if pendente and pendente["conversa"] == id_valido(corpo.get("id")):
            raise ValueError("espere a resposta antes de excluir esta conversa")
        conversas.excluir(dono, corpo.get("id"))
        return self._json({"ok": True})

    def _salvar_config_metas(self, eu: dict, corpo: dict):
        """Configuração da página Metas: as regras de cálculo e, em "usuarios", as abas e os vendedores que cada
        visualizador vê. As duas partes vão numa transação só: ou grava tudo, ou nada."""
        acessos = corpo.pop("usuarios", None)
        configuracao = self.app.configuracao
        if corpo:
            configuracao.validar(corpo)  # antes de abrir a transação
        versao = None
        with self.app.banco.conexao() as con:
            if acessos:
                self.app.usuarios.definir_metas(acessos, con)
            if corpo:
                versao = configuracao.gravar(corpo, eu, con)
        if versao:
            configuracao.usar(*versao)
            log.info("%s salvou as regras de Metas (versão %s)", eu["login"], versao[0])
        if acessos:
            log.info("%s alterou o acesso de Metas de %s", eu["login"], ", ".join(acessos))
        return self._json({"ok": True, "config": configuracao.atual(), **self._visualizadores()})

    def _salvar_config_projecoes(self, eu: dict, corpo: dict):
        """Configuração da página Projeções: os vendedores da página e o que cada visualizador vê, juntos."""
        config = self.app.config_projecoes
        with self.app.banco.conexao() as con:
            self.app.usuarios.definir_projecoes(corpo.get("usuarios") or {}, con)
            versao = config.gravar(corpo.get("vendedores") or {}, eu, con)
        config.usar(*versao)
        log.info("%s salvou a configuração das projeções (versão %s)", eu["login"], versao[0])
        return self._json({"ok": True, **self._config_projecoes()})

    def _receber(self):
        """VPS: pacote com o cache e as planilhas, assinado pelo computador da empresa (sem login)."""
        if not self.app.recebimento:
            return self._erro("rota desconhecida", HTTPStatus.NOT_FOUND)
        try:
            r = self.app.recebimento.receber(self.rfile, int(self.headers.get("Content-Length") or 0),
                                             self.headers.get("X-BI-Data"), self.headers.get("X-BI-Assinatura"))
        except Recusado as e:
            log.warning("pacote recusado de %s: %s", self._ip(), e)
            return self._erro(str(e), HTTPStatus.FORBIDDEN)
        return self._json(r)

    def _pagina(self, caminho: str):
        """index.html para quem está conectado, login.html para os outros. Com o banco fora do ar, a tela de login
        abre e mostra o aviso que /api/sessao devolve."""
        try:
            usuario = self._usuario()
        except BancoForaDoAr:
            usuario = None
        if caminho in ("/login", "/login.html"):
            return self._redireciona("/") if usuario else self._arquivo(WEB / "login.html")
        return self._arquivo(WEB / "index.html") if usuario else self._redireciona("/login")

    def _ler_agenda(self, usuario: dict, caminho: str, q: dict):
        if not self._pode_gestao(usuario):
            return
        eu = usuario["id"]
        if caminho == "/api/agenda":  # mes=2026-10 (vazio = o mês de hoje): as atividades e as tarefas
            return self._json(self.app.tarefas.no_mes(eu, self.app.agenda.mes(eu, q.get("mes"))))
        if caminho == "/api/agenda/pessoas":  # quem pode participar de uma tarefa
            return self._json(self.app.tarefas.pessoas(eu))
        if caminho == "/api/agenda/tarefa":  # id=…: a tarefa aberta, com as subtarefas de todos
            return self._json(self.app.tarefas.obter(eu, q.get("id")))
        if caminho == "/api/agenda/quadro":  # o kanban: as tarefas por situação (a fazer, fazendo, concluída)
            return self._json(self.app.tarefas.quadro(eu))
        return self._json(self.app.agenda.historico(eu, q.get("id")))

    def _mudar_agenda(self, usuario: dict, caminho: str, corpo: dict):
        if not self._pode_gestao(usuario):
            return
        if caminho.startswith(("/api/agenda/tarefa", "/api/agenda/subtarefa")):
            return self._mudar_tarefa(usuario, caminho, corpo)
        agenda, eu, id_ = self.app.agenda, usuario["id"], corpo.get("id")
        if caminho == "/api/agenda/atividades":
            a = agenda.criar(eu, corpo.get("atividade") or {})
            log.info("%s criou a atividade %s na agenda", usuario["login"], a["id"])
            return self._json({"ok": True, "atividade": a})
        if caminho == "/api/agenda/atividade/editar":
            return self._json({"ok": True, "atividade": agenda.editar(eu, id_, corpo.get("atividade") or {})})
        if caminho == "/api/agenda/atividade/encerrar":
            return self._json({"ok": True, **agenda.encerrar(eu, id_)})
        if caminho == "/api/agenda/atividade/excluir":
            agenda.excluir(eu, id_)
            log.info("%s excluiu a atividade %s da agenda", usuario["login"], id_)
            return self._json({"ok": True})
        if caminho == "/api/agenda/concluir":
            return self._json({"ok": True, "item": agenda.concluir(eu, id_, corpo.get("dia"), corpo.get("feedback"))})
        if caminho == "/api/agenda/proposta":  # o botão de uma proposta do Assistente (criar, editar, concluir…)
            proposta = self.app.conversas.proposta_agenda(eu, id_)
            if proposta is None:
                raise NaoEncontrada("proposta não encontrada; a conversa pode ter sido excluída")
            r = agenda.aplicar(eu, proposta)
            if not r["ja_aplicada"]:
                log.info("%s aplicou na agenda uma proposta do Assistente (%s, atividade %s)", usuario["login"],
                         r["acao"], r["atividade"])
            return self._json({"ok": True, **r})
        agenda.desfazer(eu, id_, corpo.get("dia"))  # /api/agenda/desfazer
        return self._json({"ok": True})

    def _mudar_tarefa(self, usuario: dict, caminho: str, corpo: dict):
        """Tarefas e subtarefas da agenda; a resposta traz a tarefa como ficou (menos ao excluir)."""
        tarefas, eu, id_ = self.app.tarefas, usuario["id"], corpo.get("id")
        if caminho == "/api/agenda/tarefas":
            t = tarefas.criar(eu, corpo.get("tarefa") or {})
            log.info("%s criou a tarefa %s na agenda", usuario["login"], t["id"])
        elif caminho == "/api/agenda/tarefa/editar":
            t = tarefas.editar(eu, id_, corpo.get("tarefa") or {}, corpo.get("versao"))
        elif caminho == "/api/agenda/tarefa/excluir":
            tarefas.excluir(eu, id_)
            log.info("%s excluiu a tarefa %s da agenda", usuario["login"], id_)
            return self._json({"ok": True})
        elif caminho == "/api/agenda/tarefa/concluir":
            t = tarefas.concluir(eu, id_)
        elif caminho == "/api/agenda/tarefa/desfazer":
            t = tarefas.desfazer(eu, id_)
        elif caminho == "/api/agenda/tarefa/mover":  # situacao: a_fazer, fazendo ou concluida (a coluna do quadro)
            t = tarefas.mover(eu, id_, corpo.get("situacao"))
        elif caminho == "/api/agenda/tarefa/justificar":  # justificativa: o porquê do atraso (vazia apaga)
            t = tarefas.justificar(eu, id_, corpo.get("justificativa"))
        elif caminho == "/api/agenda/subtarefas":  # id: a tarefa
            t = tarefas.nova_subtarefa(eu, id_, corpo.get("subtarefa") or {})
        elif caminho == "/api/agenda/subtarefa/editar":
            t = tarefas.editar_subtarefa(eu, id_, corpo.get("subtarefa") or {})
        elif caminho == "/api/agenda/subtarefa/concluir":
            t = tarefas.concluir_subtarefa(eu, id_)
        elif caminho == "/api/agenda/subtarefa/mover":
            t = tarefas.mover_subtarefa(eu, id_, corpo.get("situacao"))
        elif caminho == "/api/agenda/subtarefa/justificar":
            t = tarefas.justificar_subtarefa(eu, id_, corpo.get("justificativa"))
        else:  # /api/agenda/subtarefa/desfazer
            t = tarefas.desfazer_subtarefa(eu, id_)
        return self._json({"ok": True, "tarefa": t})

    # --- rotas ---------------------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if not url.path.startswith("/api/") and url.path not in PAGINAS_HTML:
                return self._arquivo(WEB / url.path.lstrip("/"))  # CSS, JS e imagens: sem dados nem banco
            if url.path in PAGINAS_HTML:
                return self._pagina(url.path)
            usuario = self._usuario()
            if url.path == "/api/sessao":
                return self._json(self._sessao(usuario))
            if not self._autorizado(usuario, url.path):
                return
            if url.path == "/api/estado":
                return self._json(self.app.estado())
            if url.path == "/api/opcoes":
                opcoes = self.app.calc.opcoes()
                permitidas = visoes_permitidas(usuario)
                opcoes["visoes"] = [v for v in opcoes["visoes"] if v["id"] in permitidas]
                return self._json(opcoes)
            lista = lambda k: [int(x) for x in q[k].split(",") if x.strip()] if q.get(k) else None  # noqa: E731
            if url.path == "/api/visao":
                if "metas" not in paginas_permitidas(usuario):
                    return self._erro("seu acesso não inclui a página de Metas", HTTPStatus.FORBIDDEN)
                visao = q.get("visao", "es")
                if visao not in visoes_permitidas(usuario):
                    return self._erro("seu acesso não inclui esta visão", HTTPStatus.FORBIDDEN)
                # meses=2026-09,2026-10 (vários meses somados); vendedores=12,15 (vazio = todos do acesso)
                meses = [tuple(int(p) for p in m.split("-")) for m in (q.get("meses") or "").split(",") if m.strip()]
                return self._json(self.app.calc.visao(visao, meses, lista("vendedores"), vendedores_permitidos(usuario)))
            if url.path == "/api/projecoes":
                if "projecoes" not in paginas_permitidas(usuario):
                    return self._erro("seu acesso não inclui a página de Projeções", HTTPStatus.FORBIDDEN)
                permitidos, equipes = escopo_projecoes(usuario)
                try:
                    return self._json(self.app.projetor.calcular(lista("vendedores"), lista("produtos"),
                                                                 permitidos, equipes))
                except SemVendedores as e:
                    return self._erro(str(e), HTTPStatus.FORBIDDEN)
            if url.path == "/api/sugestao":
                if "sugestao" not in paginas_permitidas(usuario):
                    return self._erro("seu acesso não inclui a página Sugestão de Metas", HTTPStatus.FORBIDDEN)
                # estado=BA&mes=2026-11 (o mês da meta; o base é o anterior)&vendedor=98&area=170 (vazios = todos)
                return self._json(self.app.sugestao.calcular(q.get("estado"), q.get("mes"), q.get("vendedor"),
                                                             q.get("area"), *escopo_sugestao(usuario)))
            if url.path == "/api/sugestao/config":
                return self._json(self.app.sugestao.config_dados(q.get("mes")))
            if url.path == "/api/sugestao/aprovacao":  # estado=BA&mes=2026-11
                return self._json(self.app.sugestao.aprovacao(q.get("estado"), q.get("mes")))
            if url.path in ("/api/credito", "/api/credito/busca", "/api/credito/analise"):
                if "credito" not in paginas_permitidas(usuario):
                    return self._erro("seu acesso não inclui a página Reavaliação de Crédito", HTTPStatus.FORBIDDEN)
                if url.path == "/api/credito/busca":
                    return self._json({"clientes": self.app.credito.buscar(q.get("texto", ""))})
                if url.path == "/api/credito/analise":  # cliente=12&limite=80000: o parecer de um limite total novo
                    return self._json(self.app.credito.analisar(q.get("cliente"), q.get("limite")))
                # clientes=12,15 (os limites somam); ordem=valor&sentido=desc ordena a tabela de títulos
                inteiro = lambda k: int(q[k]) if q.get(k, "").strip() else None  # noqa: E731
                return self._json(self.app.credito.calcular(lista("clientes"), inteiro("mes"), inteiro("ano"),
                                                            inteiro("vendedor"), ordem=q.get("ordem") or None,
                                                            sentido=q.get("sentido") or None))
            if url.path == "/api/projecoes/config":
                return self._json(self._config_projecoes())
            if url.path == "/api/assistente/info":
                if not self._pode_assistente(usuario):
                    return
                return self._json({**self.app.assistente.info(usuario, *escopo_assistente(usuario)),
                                   "gestao": "gestao" in paginas_permitidas(usuario)})
            if url.path in ("/api/assistente/conversas", "/api/assistente/conversa"):
                return self._ler_historico(usuario, url.path, q)
            if url.path == "/api/assistente/arquivo":  # id=…: o Excel ou o PDF que o Assistente preparou
                return self._baixar_arquivo(usuario, q)
            if url.path == "/api/assistente/config":
                return self._json(self._config_assistente())
            if url.path in ROTAS_GESTAO_LER:
                return self._ler_gestao(usuario, url.path, q)
            if url.path == "/api/gestao/config":
                return self._json(self._config_gestao())
            if url.path in ROTAS_AGENDA_LER:
                return self._ler_agenda(usuario, url.path, q)
            if url.path == "/api/config":
                return self._json({"config": self.app.configuracao.atual(), "catalogo": self.app.calc.catalogo(),
                                   **self._visualizadores()})
            if url.path == "/api/calendario":
                return self._json(self.app.calc.calendario_ano(int(q.get("ano", dt.date.today().year))))
            if url.path == "/api/usuarios":
                return self._json({
                    "usuarios": self.app.usuarios.listar(),
                    "paginas": [{"id": k, "titulo": v} for k, v in PAGINAS.items()],
                })
            return self._erro("rota desconhecida", HTTPStatus.NOT_FOUND)
        except CONEXAO_PERDIDA:
            return
        except BancoForaDoAr as e:
            return self._banco_fora_do_ar(e)
        except NaoEncontrada as e:
            return self._erro(str(e), HTTPStatus.NOT_FOUND)
        except PermissionError as e:  # ex.: região fora do acesso na Gestão
            return self._erro(str(e), HTTPStatus.FORBIDDEN)
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
            if url.path == ROTA_RECEBER:
                return self._receber()
            usuario = self._usuario()
            if not self._autorizado(usuario, url.path):
                return
            if url.path == "/api/minha-senha":
                corpo = self._corpo_json()
                self.app.usuarios.trocar_senha(usuario["login"], corpo.get("atual"), corpo.get("nova"))
                log.info("%s trocou a própria senha", usuario["login"])
                return self._json({"ok": True}, cookie=self._cookie_login(usuario["id"], usuario["lembrar"]))
            if url.path == "/api/usuarios":
                return self._salvar_usuario(usuario, self._corpo_json())
            if url.path == "/api/usuarios/excluir":
                login = str(self._corpo_json().get("login") or "")
                if login == usuario["login"]:
                    raise ValueError("você não pode excluir o próprio acesso")
                self.app.usuarios.excluir(login)  # as conversas do Assistente saem junto
                log.info("%s excluiu o acesso de %s", usuario["login"], login)
                return self._json({"ok": True, "usuarios": self.app.usuarios.listar()})
            if url.path == "/api/config":
                return self._salvar_config_metas(usuario, self._corpo_json())
            if url.path == "/api/projecoes/config":
                return self._salvar_config_projecoes(usuario, self._corpo_json())
            if url.path == "/api/sugestao/config":
                corpo = self._corpo_json()
                self.app.config_sugestao.salvar(corpo.get("config") or {}, usuario)
                log.info("%s salvou as regras da Sugestão de Metas", usuario["login"])
                return self._json({"ok": True, **self.app.sugestao.config_dados(corpo.get("mes"))})
            if url.path == "/api/sugestao/aprovacao":
                corpo = self._corpo_json()
                itens = corpo.get("itens")
                r = self.app.sugestao.aprovar(corpo.get("estado"), corpo.get("mes"), itens, usuario)
                log.info("%s gravou a aprovação de metas do %s em %s (%s vendedor(es))", usuario["login"], r["estado"],
                         r["mes"]["meta"], len(itens))
                return self._json({"ok": True, **r})
            if url.path == "/api/assistente":
                return self._perguntar(usuario, self._corpo_json())
            if url.path in ("/api/assistente/conversa/renomear", "/api/assistente/conversa/excluir"):
                return self._mudar_historico(usuario, url.path, self._corpo_json())
            if url.path == "/api/assistente/config":
                self.app.usuarios.definir_assistente(self._corpo_json().get("usuarios") or {})
                log.info("%s salvou o acesso do Assistente", usuario["login"])
                return self._json({"ok": True, **self._config_assistente()})
            if url.path in ROTAS_GESTAO_MUDAR:
                return self._mudar_gestao(usuario, url.path, self._corpo_json())
            if url.path == "/api/gestao/config":
                return self._salvar_config_gestao(usuario, self._corpo_json())
            if url.path in ROTAS_AGENDA_MUDAR:
                return self._mudar_agenda(usuario, url.path, self._corpo_json())
            if url.path == "/api/config/padrao":
                log.info("%s restaurou o padrão das regras de Metas", usuario["login"])
                return self._json({"ok": True, "config": self.app.configuracao.restaurar_padrao(usuario)})
            if url.path == "/api/calendario":
                corpo = self._corpo_json()
                return self._json(self.app.calc.calendario_ano(int(corpo["ano"]), corpo.get("config")))
            if url.path == "/api/atualizar":
                if self.app.vps:
                    raise ValueError("neste servidor os dados chegam do computador da empresa, depois de cada "
                                     "cópia nova do banco")
                iniciou = self.app.cache.atualizar_em_segundo_plano()
                return self._json({"ok": True, "iniciou": iniciou})
            return self._erro("rota desconhecida", HTTPStatus.NOT_FOUND)
        except CONEXAO_PERDIDA:
            return
        except BancoForaDoAr as e:
            return self._banco_fora_do_ar(e)
        except NaoEncontrada as e:
            return self._erro(str(e), HTTPStatus.NOT_FOUND)
        except PermissionError as e:  # ex.: só o administrador lança campanhas
            return self._erro(str(e), HTTPStatus.FORBIDDEN)
        except RuntimeError as e:  # dados ainda não prontos (ex.: lançar uma campanha antes da primeira extração)
            return self._erro(str(e), HTTPStatus.SERVICE_UNAVAILABLE)
        except (ValueError, KeyError) as e:
            return self._erro(str(e))
        except Exception as e:
            log.error("erro em %s\n%s", self.path, traceback.format_exc())
            return self._erro(f"erro interno: {e}", HTTPStatus.INTERNAL_SERVER_ERROR)


def definir_senha(ini: configparser.ConfigParser, login: str) -> None:
    """Uso pelo terminal: recupera o acesso quando ninguém lembra a senha de administrador. No VPS o banco só é
    visto de dentro do Docker: docker compose exec bi python app.py --senha LOGIN."""
    login = login.strip().lower()
    banco = Banco(ini, raiz=RAIZ)
    try:
        usuarios = Usuarios(banco)
        existe = usuarios.obter(login) is not None
        print(f"{'Nova senha para' if existe else 'Criando o administrador'} {login}")
        senha = getpass.getpass("Senha: ")
        if senha != getpass.getpass("Repita a senha: "):
            sys.exit("As senhas não conferem.")
        usuarios.definir_senha(login, senha)
    except BancoForaDoAr as e:
        sys.exit(f"Não foi possível: {e.aviso}.")
    except ValueError as e:
        sys.exit(f"Não foi possível: {e}.")
    finally:
        banco.fechar()
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
    ap.add_argument("--gerar-chave", action="store_true", help="gera uma chave para [publicacao] no config.ini")
    args = ap.parse_args()
    if args.gerar_chave:
        return print(f"Coloque esta linha em [publicacao] no config.ini do PC e do VPS:\nchave = {gerar_chave()}")

    # config.exemplo.ini traz os caminhos padrão; o config.ini (opcional, fora do repositório) sobrepõe o que
    # tiver, como a senha do banco. Sem ele o painel abre do mesmo jeito e avisa que falta a senha.
    ini = configparser.ConfigParser()
    ini.read([RAIZ / "config.exemplo.ini", RAIZ / "config.ini"], encoding="utf-8")
    if args.senha:
        return definir_senha(ini, args.senha)
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
    if app.vps:
        log.info("modo VPS: os dados chegam do computador da empresa (%s)",
                 f"dados até {app.cache.info.get('data_ref')}" if app.cache.pronto() else "nenhum envio recebido ainda")
    elif app.cache.desatualizado():
        log.info("preparando os dados a partir da cópia do banco…")
        app.cache.atualizar_em_segundo_plano()
    if app.envio and app.envio.ativo:
        log.info("depois de cada atualização, os dados vão para %s", app.envio.destino)
    app.banco.iniciar()  # se não der, só avisa no log: o envio ao VPS (logo abaixo) não depende do banco
    app.vigiar_em_segundo_plano()

    servidor = ThreadingHTTPServer((endereco, porta), Manipulador)
    local = f"http://127.0.0.1:{porta}"
    log.info("BI de Metas no ar em %s (Ctrl+C para encerrar)", local)
    if endereco not in ("127.0.0.1", "localhost"):
        for ip in enderecos_na_rede():
            log.info("outros computadores da rede: http://%s:%s", ip, porta)
    try:
        if app.usuarios.vazio():
            log.info("nenhum usuário cadastrado: abra %s neste computador para criar o administrador", local)
    except BancoForaDoAr:
        pass  # banco.iniciar() já avisou
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

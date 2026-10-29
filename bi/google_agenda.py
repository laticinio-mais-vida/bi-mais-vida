"""Google Agenda, só leitura (migrações 031 e 032): cada pessoa entra com a conta Google dela (o login do Google, numa
janelinha), escolhe quais agendas da conta aparecem no BI, e o BI relê os eventos delas de tempos em tempos pela API do
Google Agenda. Nada é escrito no Google: a permissão pedida é só a de ver as agendas (ESCOPO).

- Login (endereco_login, retorno): o login do Google para sites (OAuth com código, PKCE e state). O state vale
  PEDIDO_VALE, uma vez só, e só para quem começou o login (a sessão do BI tem de ser a mesma na volta): o link do login de
  outra pessoa não liga a agenda dela à sua conta do BI. O Google devolve a autorização duradoura (refresh token), que
  fica cifrada no banco (cifrar, com a chave de [google] no config.ini, fora do banco e das cópias de segurança dele),
  não volta para a página e não vai para o log. Os erros (ErroGoogle) têm texto fixo, sem a autorização nem os eventos.
- Contas e agendas (google_contas, google_agendas): a conta guarda a autorização; as agendas dela vêm da lista do Google
  (relida ao entrar e no Atualizar agora) e só as ligadas são lidas. A principal já entra ligada.
- Leitura (ler): reserva a vez (tentativa_em), pede os eventos ao Google sem segurar conexão do banco (uma leitura por
  vez no processo) e só grava se a conta não foi reconectada nem a agenda desligada nesse meio-tempo. Os mesmos eventos
  da última leitura (assinatura) só atualizam lida_em.
- Eventos (google_eventos): uma linha por ocorrência (o Google já abre as repetições), na janela (do 1º dia de
  MESES_ANTES meses atrás até HORIZONTE dias à frente). Ficam de fora as ocorrências canceladas, os convites que a pessoa
  recusou e os avisos de local de trabalho. Ocupado é o "Mostrar como: Ocupado" do Google (o Google põe o dia inteiro
  como Disponível).
- De tempos em tempos (vigiar): a cada INTERVALO, as agendas ligadas das pessoas ativas com a Gestão. Falhas seguidas
  espaçam as tentativas (até ESPERA_MAX). Quando a autorização cai (a pessoa tirou o acesso no Google, ou a chave do
  servidor mudou), a conta para de ser lida até a pessoa entrar com o Google de novo.
- Horário ocupado (ocupados, que bi/agenda.py usa): o evento ocupado de uma agenda lida há menos de VALIDADE trava a
  pessoa para as tarefas e subtarefas dos outros e só avisa a própria pessoa.
- Sem a chave e o cliente do Google em [google] (no PC), nada daqui aparece nem trava: a página avisa que a leitura fica
  no site.
"""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import hashlib
import http.client
import importlib.util
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

from .agenda import HORIZONTE, _hhmm, _id, pedacos
from .banco import Banco, BancoForaDoAr, hora, inicio_do_dia
from .calendario import UM_DIA
from .conversas import NaoEncontrada
from .tarefas import _COM_GESTAO

log = logging.getLogger("bi.google")

PACOTES = ("cryptography",)
ESCOPO = "https://www.googleapis.com/auth/calendar.readonly"  # ver as agendas e os eventos; nada de escrever
AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
REVOGAR = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
RETORNO = "https://bi.maisvida.cloud/api/agenda/google/retorno"  # o cadastrado no cliente OAuth do Google Cloud
MAX_CONTAS = 3                            # contas Google por pessoa
MAX_AGENDAS = 5                           # agendas ligadas por pessoa
MAX_LISTA = 100                           # agendas de uma conta que o BI guarda da lista do Google
PEDIDO_VALE = 600                         # segundos para voltar do login do Google
INTERVALO = dt.timedelta(minutes=10)      # o vigia relê cada agenda
MANUAL = dt.timedelta(minutes=1)          # "Atualizar agora": no máximo uma vez por minuto em cada agenda
ESPERA_MAX = dt.timedelta(hours=2)        # as falhas seguidas espaçam as tentativas até isto
VALIDADE = dt.timedelta(hours=24)         # leitura mais velha: os eventos aparecem, mas não travam ninguém
ATRASO_AVISO = dt.timedelta(hours=1)      # erro passageiro (o Google fora do ar): a página só avisa depois disto
VOLTA = 60                                # segundos entre as voltas do vigia
TEMPO = 30                                # segundos para o Google responder cada pedido
MAX_BYTES = 10 * 1024 * 1024              # por resposta do Google (uma página tem até 2.500 eventos)
MAX_OCORRENCIAS = 20_000                  # por agenda, na janela
MESES_ANTES = 3                           # a janela começa no 1º dia de 3 meses atrás
MAX_TITULO = 120
VERSAO = 2                                # do leitor: mudar faz todas as agendas serem regravadas
SEM_TITULO = "(sem título)"
SITE = "A leitura do Google Agenda fica no site (bi.maisvida.cloud): conecte a sua agenda por lá."
SEM_CLIENTE = ("Falta configurar no servidor o login com o Google ([google] cliente_id e cliente_segredo no "
               "config.ini).")
_NAO_ACHOU = "agenda do Google não encontrada; ela pode ter sido removida"
_CONTA_NAO_ACHOU = "conta Google não encontrada; ela pode ter sido desconectada"
_CAIU = "o Google cancelou a autorização do BI (ou ela venceu): entre com o Google de novo"
_ESPERAR = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}


class ErroGoogle(ValueError):
    """Falha da leitura ou do login, com texto fixo (nunca a autorização nem os eventos). conta: a autorização da conta
    caiu e a pessoa precisa entrar com o Google de novo. trocar: a agenda não abre mais (saiu da conta no Google). Nas
    outras, o BI tenta de novo sozinho."""

    def __init__(self, mensagem: str, trocar: bool = False, conta: bool = False):
        super().__init__(mensagem)
        self.trocar = trocar
        self.conta = conta


# --- a autorização guardada -------------------------------------------------------------------------------------------
def _fernet(chave: str):
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"bi-google-agenda\n" + chave.encode()).digest()))


def cifrar(chave: str, texto: str) -> str:
    return _fernet(chave).encrypt(texto.encode()).decode()


def decifrar(chave: str, cifrado: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        return _fernet(chave).decrypt(cifrado.encode()).decode()
    except (InvalidToken, ValueError):
        raise ErroGoogle("a autorização guardada não abre mais (a chave do servidor mudou): entre com o Google de "
                         "novo", conta=True) from None


# --- os pedidos ao Google ---------------------------------------------------------------------------------------------
def pedir(metodo: str, url: str, dados: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    """Um pedido ao Google (só aos endereços fixos daqui), em até TEMPO segundos: (status, resposta em JSON). Sem
    resposta: ErroGoogle."""
    cabecalhos = {"User-Agent": "BIMetasMaisVida-agenda/2.0", "Accept": "application/json"}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    corpo = urlencode(dados).encode() if dados is not None else None
    if corpo is not None:
        cabecalhos["Content-Type"] = "application/x-www-form-urlencoded"
    pedido = urllib.request.Request(url, data=corpo, headers=cabecalhos, method=metodo)
    try:
        with urllib.request.urlopen(pedido, timeout=TEMPO) as r:
            return r.status, _json(r.read(MAX_BYTES + 1))
    except urllib.error.HTTPError as e:
        return e.code, _json(e.read(65536))
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise ErroGoogle("sem resposta do Google agora; o BI tenta de novo sozinho") from None


def _json(corpo: bytes) -> dict:
    if len(corpo) > MAX_BYTES:
        raise ErroGoogle("a resposta do Google veio grande demais; o BI tenta de novo mais tarde")
    try:
        r = json.loads(corpo or b"{}")
    except ValueError:
        return {}
    return r if isinstance(r, dict) else {}


def _motivos(r: dict) -> set[str]:
    erro = r.get("error")
    erros = erro.get("errors") if isinstance(erro, dict) else None
    return {str(e.get("reason")) for e in erros or [] if isinstance(e, dict)}


def conferir(status: int, r: dict) -> None:
    """A resposta da API do Google Agenda, em ErroGoogle quando não deu certo."""
    if status == 200:
        return
    motivos = _motivos(r)
    log.warning("o Google respondeu %s (%s)", status, ", ".join(sorted(motivos)) or "sem motivo")
    if status == 404:
        raise ErroGoogle("essa agenda não está mais na sua conta Google: desligue-a aqui ou clique em Atualizar agora",
                         trocar=True)
    if status == 403 and not motivos & _ESPERAR:
        raise ErroGoogle("o Google não deixa mais o BI ler esta agenda", trocar=True)
    if status in (403, 429):
        raise ErroGoogle("o Google pediu para esperar um pouco; o BI tenta de novo sozinho")
    raise ErroGoogle(f"o Google não respondeu direito agora (erro {status}); o BI tenta de novo sozinho")


def _erro_token(status: int, r: dict, renovando: bool) -> ErroGoogle:
    """O que deu errado no pedido de autorização (TOKEN)."""
    codigo = str(r.get("error") or "")
    if codigo == "invalid_grant":
        return (ErroGoogle(_CAIU, conta=True) if renovando
                else ErroGoogle("o login com o Google venceu antes de terminar: tente de novo"))
    if codigo in ("invalid_client", "unauthorized_client"):
        log.error("o Google recusou o cliente OAuth do servidor ([google] cliente_id e cliente_segredo): %s", codigo)
        return ErroGoogle("o login com o Google está mal configurado no servidor: avise o administrador")
    return ErroGoogle(f"o Google não respondeu direito agora (erro {status}); tente de novo em instantes")


# --- os eventos -------------------------------------------------------------------------------------------------------
def janela(hoje: dt.date) -> tuple[dt.date, dt.date]:
    """Os dias que a leitura guarda: do 1º dia de MESES_ANTES meses atrás a HORIZONTE dias à frente (o fim,
    exclusive)."""
    mes = hoje.year * 12 + hoje.month - 1 - MESES_ANTES
    return dt.date(mes // 12, mes % 12 + 1, 1), hoje + dt.timedelta(HORIZONTE + 1)


def _rfc(dia: dt.date) -> str:
    return dt.datetime.combine(dia, dt.time()).astimezone().isoformat()


def interpretar(itens: list[dict]) -> list[tuple]:
    """Os eventos da API (singleEvents: uma ocorrência por item) em [(título, início, fim, dia inteiro, ocupado)], com
    início e fim em hora local com fuso, em ordem. Ficam de fora os cancelados, os que a pessoa recusou e os avisos de
    local de trabalho."""
    eventos = []
    for ev in itens:
        if not isinstance(ev, dict) or ev.get("status") == "cancelled" or ev.get("eventType") == "workingLocation":
            continue
        if any(isinstance(c, dict) and c.get("self") and c.get("responseStatus") == "declined"
               for c in ev.get("attendees") or []):
            continue
        comeco, final = ev.get("start") or {}, ev.get("end") or {}
        try:
            inicio = _quando(comeco)
            fim = _quando(final) if final else inicio
        except (KeyError, ValueError, TypeError, AttributeError):
            continue  # sem uma data que o BI entenda
        titulo = " ".join(str(ev.get("summary") or "").split())[:MAX_TITULO] or SEM_TITULO
        eventos.append((titulo, inicio, max(inicio, fim), "date" in comeco, ev.get("transparency") != "transparent"))
    return sorted(eventos, key=lambda e: (e[1], e[2], e[0]))


def _quando(x: dict) -> dt.datetime:
    """A hora do evento (com fuso, "2026-10-30T14:00:00-03:00" ou "…Z") ou a data do dia inteiro (a meia-noite), em
    hora local com fuso."""
    if "dateTime" in x:
        texto = str(x["dateTime"])
        return dt.datetime.fromisoformat(texto[:-1] + "+00:00" if texto.endswith("Z") else texto).astimezone()
    return dt.datetime.combine(dt.date.fromisoformat(str(x["date"])), dt.time()).astimezone()


def assinatura(eventos: list[tuple]) -> str:
    """O que distingue uma leitura da outra (com a versão do leitor). Igual à última: não há o que regravar."""
    linhas = (f"{t}\t{i.isoformat()}\t{f.isoformat()}\t{d:d}\t{o:d}" for t, i, f, d, o in eventos)
    return hashlib.sha256(f"{VERSAO}\n".encode() + "\n".join(linhas).encode()).hexdigest()


def espera(falhas: int, trocar: bool) -> dt.timedelta:
    """Quanto o vigia espera desde a última tentativa: INTERVALO, dobrando a cada falha seguida, até ESPERA_MAX; a
    agenda que não abre mais espera o máximo."""
    return ESPERA_MAX if trocar else min(INTERVALO * 2 ** min(falhas, 8), ESPERA_MAX)


def _sem_fuso(x: dt.datetime) -> dt.datetime:
    return x.astimezone().replace(tzinfo=None)


def _nome(item: dict) -> str:
    nome = " ".join(str(item.get("summaryOverride") or item.get("summary") or "").split())
    return nome[:MAX_TITULO] or str(item["id"])[:MAX_TITULO]


class GoogleAgenda:
    def __init__(self, banco: Banco, ini=None, *, agora=None, pedidor=None):
        """ini: o config.ini ([google] chave, cliente_id, cliente_segredo e retorno). agora: o relógio, hora local sem
        fuso (os testes fixam). pedidor: troca o pedir (os testes não vão à internet)."""
        self.banco = banco
        g = (lambda k: ini.get("google", k, fallback="").strip()) if ini is not None else (lambda k: "")
        self.chave, self.cliente_id, self.cliente_segredo = g("chave"), g("cliente_id"), g("cliente_segredo")
        self.retorno_url = g("retorno") or RETORNO
        self.agora = agora or dt.datetime.now
        self._pedir = pedidor or pedir
        self.falta = [p for p in PACOTES if importlib.util.find_spec(p) is None]
        self.pausa = 1.0  # segundos entre uma agenda e outra numa volta do vigia
        self._vez_trava = threading.Lock()
        self._pedidos: dict[str, tuple[int, str, float]] = {}  # state: (usuário, verificador do PKCE, quando)
        self._acessos: dict[int, tuple[str, str, float]] = {}  # conta: (autorização cifrada, acesso, até quando)
        self._trava = threading.Lock()  # dos dois dicionários acima
        self._sem_banco_em = None

    @property
    def ativo(self) -> bool:
        return bool(self.chave and self.cliente_id and self.cliente_segredo) and not self.falta

    @property
    def aviso(self) -> str | None:
        if not self.chave:
            return SITE
        if not (self.cliente_id and self.cliente_segredo):
            return SEM_CLIENTE
        if self.falta:
            return f"Falta instalar no servidor os pacotes da leitura do Google Agenda: {', '.join(self.falta)}."
        return None

    def _exigir(self) -> None:
        if not self.ativo:
            raise ValueError(self.aviso)

    @contextlib.contextmanager
    def _vez(self, manual: bool):
        """Uma leitura por vez no processo; quem clicou espera um pouco, o vigia espera o quanto for."""
        if not self._vez_trava.acquire(timeout=45 if manual else -1):
            raise ErroGoogle("outra agenda do Google está sendo lida agora; tente de novo em instantes")
        try:
            yield
        finally:
            self._vez_trava.release()

    # --- o login com o Google --------------------------------------------------------------
    def endereco_login(self, usuario: int) -> str:
        """Para onde a janelinha vai: o login do Google, pedindo só a permissão de ver as agendas, com um state novo
        (vale PEDIDO_VALE, uma vez, para este usuário) e o desafio do PKCE."""
        self._exigir()
        state, verificador = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
        with self._trava:
            agora = time.monotonic()
            for k in [k for k, p in self._pedidos.items() if agora - p[2] > PEDIDO_VALE]:
                del self._pedidos[k]
            if len(self._pedidos) >= 500:  # muitos logins abertos: o mais antigo cai
                del self._pedidos[min(self._pedidos, key=lambda k: self._pedidos[k][2])]
            self._pedidos[state] = (usuario, verificador, agora)
        return AUTORIZAR + "?" + urlencode({
            "client_id": self.cliente_id, "redirect_uri": self.retorno_url, "response_type": "code", "scope": ESCOPO,
            "access_type": "offline", "prompt": "select_account consent", "include_granted_scopes": "false",
            "state": state, "code_challenge": desafio, "code_challenge_method": "S256"})

    def retorno(self, usuario: int, q: dict) -> dict:
        """A volta do login do Google: confere o state, troca o código pela autorização, guarda a conta e a lista das
        agendas dela (a principal já ligada) e lê a principal. {id, email, nova}."""
        self._exigir()
        with self._trava:
            pedido = self._pedidos.pop(str(q.get("state") or ""), None)
        if pedido is None or time.monotonic() - pedido[2] > PEDIDO_VALE:
            raise ErroGoogle("o login com o Google venceu ou já foi usado: tente de novo")
        dono, verificador, _ = pedido
        if usuario != dono:
            raise ErroGoogle("a sessão do BI mudou durante o login com o Google: tente de novo")
        if q.get("error"):
            raise ErroGoogle("você não autorizou o BI no Google; nada foi conectado" if q["error"] == "access_denied"
                             else "o Google não completou o login: tente de novo")
        if not q.get("code"):
            raise ErroGoogle("o Google não completou o login: tente de novo")
        status, r = self._pedir("POST", TOKEN, {
            "code": q["code"], "client_id": self.cliente_id, "client_secret": self.cliente_segredo,
            "redirect_uri": self.retorno_url, "grant_type": "authorization_code", "code_verifier": verificador})
        if status != 200 or not r.get("access_token"):
            raise _erro_token(status, r, renovando=False)
        renovar, acesso = r.get("refresh_token"), str(r["access_token"])
        if ESCOPO not in str(r.get("scope") or "").split():
            self._revogar(renovar or acesso)
            raise ErroGoogle("o Google não deu ao BI a permissão de ver a agenda: entre de novo e deixe marcada a "
                             "permissão do Google Agenda")
        if not renovar:
            raise ErroGoogle("o Google não mandou a autorização para o BI continuar lendo: tente de novo")
        lista = self._lista(acesso)
        email = next((cal for cal, _, principal in lista if principal), None)
        if not email:
            self._revogar(renovar)
            raise ErroGoogle("a conta Google não tem uma agenda principal para o BI ler")
        with self.banco.conexao() as con:
            ja = con.execute("SELECT 1 FROM google_contas WHERE usuario = %s AND email = %s",
                             [usuario, email.lower()]).fetchone()
            if not ja and con.execute("SELECT count(*) FROM google_contas WHERE usuario = %s",
                                      [usuario]).fetchone()[0] >= MAX_CONTAS:
                self._revogar(renovar)
                raise ValueError(f"cada pessoa conecta até {MAX_CONTAS} contas Google: desconecte uma antes")
            cifrado = cifrar(self.chave, renovar)
            linha = con.execute(
                "INSERT INTO google_contas (usuario, email, token) SELECT id, %(email)s, %(token)s FROM usuarios "
                "WHERE id = %(u)s ON CONFLICT (usuario, email) DO UPDATE SET token = EXCLUDED.token, erro = NULL, "
                "trocar = false RETURNING id, xmax = 0",
                {"email": email.lower(), "token": cifrado, "u": usuario}).fetchone()
            if not linha:
                raise NaoEncontrada("seu usuário não existe mais")
            conta, nova = linha
            self._sincronizar(con, usuario, conta, lista)
            principal = con.execute("SELECT id FROM google_agendas WHERE conta = %s AND principal AND ligada",
                                    [conta]).fetchone()
        with self._trava:
            self._acessos[conta] = (cifrado, acesso, time.monotonic() + int(r.get("expires_in") or 0) - 120)
        if principal:
            self.ler(principal[0], dt.timedelta(0))
        return {"id": conta, "email": email.lower(), "nova": nova}

    def _lista(self, acesso: str) -> list[tuple[str, str, bool]]:
        """As agendas que a conta vê (pelo menos para ler os eventos): [(id, nome, principal)]."""
        itens, pagina = [], None
        while True:
            q = {"minAccessRole": "reader", "maxResults": 250, "showDeleted": "false",
                 "fields": "items(id,summary,summaryOverride,primary),nextPageToken",
                 **({"pageToken": pagina} if pagina else {})}
            status, r = self._pedir("GET", f"{API}/users/me/calendarList?{urlencode(q)}", token=acesso)
            conferir(status, r)
            itens += [i for i in r.get("items") or [] if isinstance(i, dict) and i.get("id")]
            pagina = r.get("nextPageToken")
            if not pagina or len(itens) >= MAX_LISTA:
                return [(str(i["id"]), _nome(i), bool(i.get("primary"))) for i in itens[:MAX_LISTA]]

    def _revogar(self, token: str | None) -> None:
        """Avisa o Google que o BI largou a autorização (sai da lista de apps da conta). Falhou: fica no log."""
        if not token:
            return
        try:
            status, _ = self._pedir("POST", REVOGAR, {"token": token})
        except ErroGoogle:
            status = None
        if status != 200:
            log.warning("não deu para avisar o Google que a autorização foi largada (%s)", status)

    # --- as contas e as agendas da pessoa --------------------------------------------------
    def _sincronizar(self, con, usuario: int, conta: int, lista: list[tuple[str, str, bool]]) -> None:
        """Guarda a lista de agendas da conta como está no Google: as novas entram desligadas (a principal, ligada, se
        couber), as que saíram da conta saem do BI com os eventos delas."""
        ligadas = con.execute("SELECT calendario FROM google_agendas WHERE usuario = %s AND ligada",
                              [usuario]).fetchall()
        ja_ligadas = {c for (c,) in ligadas}
        for calendario, nome, principal in lista:
            ligar = principal and calendario not in ja_ligadas and len(ja_ligadas) < MAX_AGENDAS
            con.execute(
                "INSERT INTO google_agendas (usuario, conta, calendario, nome, principal, ligada) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (conta, calendario) DO UPDATE SET nome = EXCLUDED.nome, "
                "principal = EXCLUDED.principal", [usuario, conta, calendario, nome, principal, ligar])
        con.execute("DELETE FROM google_agendas WHERE conta = %s AND NOT (calendario = ANY(%s))",
                    [conta, [c for c, _, _ in lista]])

    def listar(self, usuario: int) -> dict:
        """As contas conectadas (sem a autorização), com as agendas de cada uma e como foi a última leitura."""
        if not self.ativo:
            return {"ativo": False, "aviso": self.aviso, "contas": []}
        with self.banco.conexao() as con:
            contas = con.execute("SELECT id, email, erro, trocar FROM google_contas WHERE usuario = %s "
                                 "ORDER BY criada_em, id", [usuario]).fetchall()
            agendas = con.execute(
                "SELECT a.conta, a.id, a.nome, a.calendario, a.principal, a.ligada, a.lida_em, a.tentativa_em, a.erro, "
                "a.trocar, (SELECT count(*) FROM google_eventos e WHERE e.agenda = a.id) FROM google_agendas a "
                "WHERE a.usuario = %s ORDER BY a.principal DESC, lower(a.nome), a.id", [usuario]).fetchall()
        agora = self.agora().astimezone()
        return {"ativo": True, "aviso": None, "contas": [
            {"id": c, "email": email, "erro": erro, "trocar": trocar, "atencao": trocar,
             "agendas": [self._publica(a[1:], agora) for a in agendas if a[0] == c]}
            for c, email, erro, trocar in contas]}

    @staticmethod
    def _publica(linha, agora: dt.datetime) -> dict:
        """desatualizada: ligada e sem leitura boa há mais de VALIDADE (não trava). atencao: a página avisa (a agenda
        não abre mais, ou o erro passageiro já dura mais de ATRASO_AVISO)."""
        id_, nome, calendario, principal, ligada, lida_em, tentativa_em, erro, trocar, eventos = linha
        sem_ler = lida_em is None or agora - lida_em > ATRASO_AVISO
        return {"id": id_, "nome": nome, "calendario": calendario, "principal": principal, "ligada": ligada,
                "lida_em": hora(lida_em), "tentativa_em": hora(tentativa_em), "erro": erro, "trocar": trocar,
                "eventos": eventos, "desatualizada": ligada and (lida_em is None or agora - lida_em > VALIDADE),
                "atencao": ligada and bool(trocar or (erro and sem_ler))}

    def ligar(self, usuario: int, id_, ligada: bool) -> None:
        """Liga (e lê na hora) ou desliga uma agenda da pessoa. Desligada, os eventos dela saem do BI."""
        self._exigir()
        id_ = _id(id_, _NAO_ACHOU)
        with self.banco.conexao() as con:
            linha = con.execute("SELECT a.ligada, a.calendario, a.conta FROM google_agendas a WHERE a.id = %s "
                                "AND a.usuario = %s FOR UPDATE", [id_, usuario]).fetchone()
            if not linha:
                raise NaoEncontrada(_NAO_ACHOU)
            if linha[0] == ligada:
                return
            if ligada:
                outras = con.execute("SELECT a.calendario, c.email FROM google_agendas a JOIN google_contas c ON "
                                     "c.id = a.conta WHERE a.usuario = %s AND a.ligada", [usuario]).fetchall()
                if len(outras) >= MAX_AGENDAS:
                    raise ValueError(f"cada pessoa liga até {MAX_AGENDAS} agendas do Google: desligue uma antes")
                pela = next((email for cal, email in outras if cal == linha[1]), None)
                if pela:
                    raise ValueError(f"essa agenda já aparece no BI pela conta {pela}")
            else:
                con.execute("DELETE FROM google_eventos WHERE agenda = %s", [id_])
            con.execute("UPDATE google_agendas SET ligada = %s, lida_em = NULL, tentativa_em = NULL, conteudo = NULL, "
                        "erro = NULL, trocar = false, falhas = 0 WHERE id = %s", [ligada, id_])
        if ligada:
            self.ler(id_, dt.timedelta(0))

    def desconectar(self, usuario: int, conta) -> None:
        """Tira a conta do BI (com as agendas e os eventos dela) e avisa o Google, que tira o BI da lista de apps com
        acesso à conta."""
        conta = _id(conta, _CONTA_NAO_ACHOU)
        with self.banco.conexao() as con:
            linha = con.execute("DELETE FROM google_contas WHERE id = %s AND usuario = %s RETURNING token",
                                [conta, usuario]).fetchone()
        if not linha:
            raise NaoEncontrada(_CONTA_NAO_ACHOU)
        self._esquecer(conta)
        try:
            self._revogar(decifrar(self.chave, linha[0]))
        except ErroGoogle:
            pass  # a chave mudou: a autorização já não abria

    def atualizar(self, usuario: int, conta=None) -> int:
        """O botão Atualizar agora: relê a lista de agendas das contas da pessoa (ou só da conta) e as agendas ligadas
        que não foram tentadas no último minuto. Devolve quantas leu."""
        self._exigir()
        uma = conta is not None and conta != ""
        with self.banco.conexao() as con:
            contas = con.execute(
                "SELECT id, token FROM google_contas WHERE usuario = %s" + (" AND id = %s" if uma else "") +
                " ORDER BY id", [usuario, *([_id(conta, _CONTA_NAO_ACHOU)] if uma else [])]).fetchall()
        if uma and not contas:
            raise NaoEncontrada(_CONTA_NAO_ACHOU)
        for id_, cifrado in contas:
            self._esquecer(id_)  # renova o acesso: confere na hora se a autorização ainda vale
            try:
                lista = self._lista(self._acesso(id_, cifrado))
            except ErroGoogle as e:
                self._falhou_conta(id_, cifrado, e)
                continue
            with self.banco.conexao() as con:
                if con.execute("SELECT 1 FROM google_contas WHERE id = %s AND token = %s FOR UPDATE",
                               [id_, cifrado]).fetchone():
                    self._sincronizar(con, usuario, id_, lista)
                    con.execute("UPDATE google_contas SET erro = NULL, trocar = false WHERE id = %s", [id_])
        with self.banco.conexao() as con:
            ids = [r[0] for r in con.execute(
                "SELECT a.id FROM google_agendas a JOIN google_contas c ON c.id = a.conta WHERE a.usuario = %s "
                "AND a.ligada AND NOT c.trocar AND a.conta = ANY(%s) ORDER BY a.id", [usuario, [c for c, _ in contas]])]
        lidas = sum(self.ler(i, MANUAL) for i in ids)
        if ids and not lidas:
            raise ValueError("a agenda acabou de ser lida: tente de novo daqui a um minuto")
        return lidas

    # --- a leitura -------------------------------------------------------------------------
    def _acesso(self, conta: int, cifrado: str) -> str:
        """O acesso de agora (vale uma hora) da conta, renovado com a autorização guardada quando venceu."""
        with self._trava:
            guardado = self._acessos.get(conta)
            if guardado and guardado[0] == cifrado and guardado[2] > time.monotonic():
                return guardado[1]
        status, r = self._pedir("POST", TOKEN, {
            "client_id": self.cliente_id, "client_secret": self.cliente_segredo,
            "refresh_token": decifrar(self.chave, cifrado), "grant_type": "refresh_token"})
        if status != 200 or not r.get("access_token"):
            raise _erro_token(status, r, renovando=True)
        with self._trava:
            self._acessos[conta] = (cifrado, str(r["access_token"]),
                                    time.monotonic() + int(r.get("expires_in") or 0) - 120)
        return str(r["access_token"])

    def _esquecer(self, conta: int) -> None:
        with self._trava:
            self._acessos.pop(conta, None)

    def _eventos(self, conta: int, cifrado: str, calendario: str, hoje: dt.date) -> list[tuple]:
        """Os eventos de uma agenda na janela, página por página. O acesso recusado (vencido antes da hora) é renovado
        uma vez."""
        desde, ate = janela(hoje)
        acesso, renovou, itens, pagina = self._acesso(conta, cifrado), False, [], None
        while True:
            q = {"singleEvents": "true", "orderBy": "startTime", "timeMin": _rfc(desde), "timeMax": _rfc(ate),
                 "maxResults": 2500, "maxAttendees": 1, "showDeleted": "false",
                 "fields": "items(status,summary,start,end,transparency,eventType,attendees(self,responseStatus)),"
                           "nextPageToken", **({"pageToken": pagina} if pagina else {})}
            status, r = self._pedir("GET", f"{API}/calendars/{quote(calendario, safe='')}/events?{urlencode(q)}",
                                    token=acesso)
            if status == 401 and not renovou:
                self._esquecer(conta)
                acesso, renovou = self._acesso(conta, cifrado), True
                continue
            conferir(status, r)
            itens += r.get("items") or []
            if len(itens) > MAX_OCORRENCIAS:
                teto = f"{MAX_OCORRENCIAS:_}".replace("_", ".")
                raise ErroGoogle(f"a agenda tem mais de {teto} eventos nos próximos meses; o BI não lê agendas desse "
                                 "tamanho")
            pagina = r.get("nextPageToken")
            if not pagina:
                return interpretar(itens)

    def ler(self, id_: int, espera_min: dt.timedelta = INTERVALO) -> bool:
        """Lê uma agenda ligada se a última tentativa tem mais de espera_min (False: não era a vez, a agenda foi
        desligada ou a autorização da conta caiu). A vez fica reservada em tentativa_em antes de pedir ao Google; o
        pedido não segura conexão do banco, e o resultado só é gravado se a conta não foi reconectada nem a agenda
        desligada enquanto isso."""
        with self._vez(manual=espera_min <= MANUAL):
            agora = self.agora().astimezone()
            with self.banco.conexao() as con:
                linha = con.execute(
                    "UPDATE google_agendas a SET tentativa_em = %s FROM google_contas c WHERE c.id = a.conta "
                    "AND a.id = %s AND a.ligada AND NOT c.trocar AND (a.tentativa_em IS NULL OR a.tentativa_em <= %s) "
                    "RETURNING a.conta, c.token, a.calendario, a.conteudo", [agora, id_, agora - espera_min]).fetchone()
            if not linha:
                return False
            conta, cifrado, calendario, conteudo = linha
            try:
                eventos = self._eventos(conta, cifrado, calendario, agora.date())
            except ErroGoogle as e:
                self._falhou(id_, conta, cifrado, e)
                return True
            except Exception as e:  # o texto pode ter um evento: no log, só o tipo
                log.error("agenda do Google %s: falha inesperada na leitura (%s)", id_, type(e).__name__)
                self._falhou(id_, conta, cifrado, ErroGoogle("falha inesperada na leitura; o BI tenta de novo sozinho"))
                return True
        assinado = assinatura(eventos)
        with self.banco.conexao() as con:
            if not con.execute("SELECT 1 FROM google_agendas a JOIN google_contas c ON c.id = a.conta WHERE a.id = %s "
                               "AND a.ligada AND c.token = %s FOR UPDATE OF a", [id_, cifrado]).fetchone():
                return True  # desligada, desconectada ou reconectada enquanto lia: vale a de agora
            if assinado != conteudo:
                self._gravar_eventos(con, id_, eventos)
            con.execute("UPDATE google_agendas SET lida_em = %s, conteudo = %s, erro = NULL, trocar = false, "
                        "falhas = 0 WHERE id = %s", [agora, assinado, id_])
            con.execute("UPDATE google_contas SET erro = NULL WHERE id = %s AND NOT trocar", [conta])
        return True

    def _falhou(self, id_: int, conta: int, cifrado: str, e: ErroGoogle) -> None:
        if e.conta:
            return self._falhou_conta(conta, cifrado, e)
        log.warning("agenda do Google %s: %s", id_, e)
        with self.banco.conexao() as con:
            con.execute("UPDATE google_agendas SET erro = %s, trocar = %s, falhas = least(falhas + 1, 30) "
                        "WHERE id = %s AND conta IN (SELECT id FROM google_contas WHERE token = %s)",
                        [str(e), e.trocar, id_, cifrado])

    def _falhou_conta(self, conta: int, cifrado: str, e: ErroGoogle) -> None:
        """A autorização caiu (conta): a conta para de ser lida até a pessoa entrar de novo. Nas outras falhas da lista
        de agendas, só o erro fica anotado."""
        log.warning("conta Google %s: %s", conta, e)
        self._esquecer(conta)
        with self.banco.conexao() as con:
            con.execute("UPDATE google_contas SET erro = %s, trocar = trocar OR %s WHERE id = %s AND token = %s",
                        [str(e), e.conta, conta, cifrado])

    @staticmethod
    def _gravar_eventos(con, agenda: int, eventos: list[tuple]) -> None:
        con.execute("DELETE FROM google_eventos WHERE agenda = %s", [agenda])
        with con.cursor() as cur:
            cur.executemany("INSERT INTO google_eventos (agenda, titulo, inicio, fim, dia_inteiro, ocupado) "
                            "VALUES (%s, %s, %s, %s, %s, %s)", [(agenda, *e) for e in eventos])

    def rodada(self) -> int:
        """Uma volta do vigia: lê as agendas ligadas que estão na hora, das pessoas ativas com a Gestão (quem saiu deixa
        de ser lido) e das contas com a autorização valendo. Uma agenda com erro não para as outras. Devolve quantas
        leu."""
        agora = self.agora().astimezone()
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT a.id, a.tentativa_em, a.falhas, a.trocar FROM google_agendas a JOIN google_contas c ON "
                "c.id = a.conta JOIN usuarios u ON u.id = a.usuario WHERE a.ligada AND NOT c.trocar AND "
                f"{_COM_GESTAO} ORDER BY a.tentativa_em NULLS FIRST, a.id").fetchall()
        lidas = 0
        for id_, tentativa, falhas, trocar in linhas:
            minimo = espera(falhas, trocar)
            if tentativa is not None and agora - tentativa < minimo:
                continue
            if lidas and self.pausa:
                time.sleep(self.pausa)
            lidas += self.ler(id_, minimo)
        return lidas

    def vigiar(self) -> None:
        """A leitura de tempos em tempos (thread "google"), onde a leitura está ligada (no site)."""
        if not self.ativo:
            return

        def laco():
            while True:
                time.sleep(VOLTA)
                try:
                    self.rodada()
                    self._sem_banco_em = None
                except BancoForaDoAr:
                    if self._sem_banco_em is None or time.monotonic() - self._sem_banco_em > 3600:
                        log.warning("leitura do Google Agenda parada: o banco de dados está fora do ar")
                        self._sem_banco_em = time.monotonic()
                except Exception:
                    log.exception("falha na volta da leitura do Google Agenda")

        threading.Thread(target=laco, name="google", daemon=True).start()
        log.info("leitura do Google Agenda ligada (cada agenda a cada %d min)", INTERVALO.seconds // 60)

    # --- o que a agenda mostra e o horário ocupado -----------------------------------------
    def no_mes(self, usuario: int, m: dict) -> dict:
        """A resposta de /api/agenda (Agenda.mes e Tarefas.no_mes) com o Google: em cada dia, os pedaços dos eventos
        (google), que não contam nas contas do dia; no topo, as contas (para a página avisar)."""
        info = self.listar(usuario)
        por_dia = self.no_periodo(usuario, dt.date.fromisoformat(m["dias"][0]["data"]),
                                  dt.date.fromisoformat(m["dias"][-1]["data"])) if info["ativo"] else {}
        return {**m, "dias": [{**x, "google": por_dia.get(x["data"], [])} for x in m["dias"]], "google": info}

    def no_periodo(self, usuario: int, de: dt.date, ate: dt.date) -> dict[str, list[dict]]:
        """Os eventos do Google da pessoa, dia a dia, de de a ate: {AAAA-MM-DD: [pedaços]}, os do dia todo primeiro,
        depois pela hora. O que passa da meia-noite aparece nos dois dias (antes, depois); de e ate: o primeiro e o
        último dia do evento."""
        if not self.ativo:
            return {}
        agora = self.agora().astimezone()
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT e.titulo, e.inicio, e.fim, e.dia_inteiro, e.ocupado, a.nome, a.lida_em FROM google_eventos e "
                "JOIN google_agendas a ON a.id = e.agenda WHERE a.usuario = %(u)s AND a.ligada AND e.inicio < %(ate)s "
                "AND (e.fim > %(de)s OR e.inicio >= %(de)s) ORDER BY e.inicio, e.fim, e.titulo",
                {"u": usuario, "de": inicio_do_dia(de), "ate": inicio_do_dia(ate + UM_DIA)}).fetchall()
        dias: dict[str, list[dict]] = {}
        for titulo, inicio, fim, dia_inteiro, ocupado, nome, lida_em in linhas:
            inicio, fim = _sem_fuso(inicio), _sem_fuso(fim)
            ultimo = (fim - dt.timedelta(microseconds=1)).date() if fim > inicio else inicio.date()
            for p in pedacos(inicio, fim, dia_inteiro, de, ate):
                dias.setdefault(p["dia"].isoformat(), []).append({
                    "titulo": titulo, "agenda": nome, "hora": _hhmm(p["hora"]), "hora_fim": _hhmm(p["hora_fim"]),
                    "dia_todo": p["dia_todo"], "dia_inteiro": dia_inteiro, "ocupado": ocupado, "antes": p["antes"],
                    "depois": p["depois"], "de": inicio.date().isoformat(), "ate": ultimo.isoformat(),
                    "desatualizada": lida_em is None or agora - lida_em > VALIDADE})
        for lista in dias.values():
            lista.sort(key=lambda g: (not g["dia_todo"], g["hora"] or "", g["titulo"]))
        return dias

    def ocupados(self, con, pessoas, de: dt.date, ate: dt.date) -> list[dict]:
        """Os eventos ocupados das pessoas que tocam os dias de de a ate, só das agendas ligadas e lidas há menos de
        VALIDADE, com o nome da pessoa, em hora local sem fuso (o horário ocupado, bi/agenda.py). Sem a leitura ligada,
        nenhum."""
        if not self.ativo or not pessoas:
            return []
        linhas = con.execute(
            "SELECT a.usuario, u.nome, e.titulo, e.inicio, e.fim, e.dia_inteiro FROM google_eventos e "
            "JOIN google_agendas a ON a.id = e.agenda JOIN usuarios u ON u.id = a.usuario "
            "WHERE a.usuario = ANY(%(p)s::bigint[]) AND a.ligada AND e.ocupado AND e.fim > e.inicio "
            "AND a.lida_em >= %(validade)s AND e.fim > %(de)s AND e.inicio < %(ate)s ORDER BY e.inicio, e.fim",
            {"p": sorted(set(pessoas)), "validade": self.agora().astimezone() - VALIDADE, "de": inicio_do_dia(de),
             "ate": inicio_do_dia(ate + UM_DIA)}).fetchall()
        return [{"usuario": u, "nome": n, "titulo": t, "inicio": _sem_fuso(i), "fim": _sem_fuso(f), "dia_inteiro": d}
                for u, n, t, i, f, d in linhas]

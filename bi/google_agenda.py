"""Google Agenda, só leitura (migração 031): cada pessoa conecta as próprias agendas do Google pelo endereço secreto no
formato iCal, e o BI relê os eventos delas de tempos em tempos. Nada é escrito no Google.

- Endereço (endereco_valido): só https://calendar.google.com/calendar/ical/<agenda>/private-<chave>/basic.ics. O BI
  remonta o endereço com as partes conferidas e nunca baixa o texto colado: o servidor não pode virar um jeito de
  acessar outra coisa (a rede interna do VPS). O endereço é uma senha (quem tem lê a agenda inteira): fica cifrado no
  banco (cifrar, com a chave de [google] no config.ini, fora do banco e das cópias de segurança dele), não volta para a
  página e não vai para o log. Os erros (ErroGoogle) têm texto fixo, sem o endereço nem os eventos.
- A agenda é identificada pelo id dela no Google (calendario, tirado do endereço; na principal, o e-mail): colar o
  endereço novo da mesma agenda, depois de "Redefinir" no Google, troca o antigo na mesma linha.
- Leitura (ler): reserva a vez (tentativa_em), baixa e interpreta sem segurar conexão do banco (uma leitura por vez no
  processo: o arquivo traz o histórico inteiro e o painel tem pouca memória) e só grava se o endereço não mudou nesse
  meio-tempo. O arquivo igual ao da última leitura (assinatura, sem as linhas DTSTAMP) só atualiza lida_em.
- Eventos (google_eventos): uma linha por ocorrência, com as repetições abertas, na janela (do 1º dia de MESES_ANTES
  meses atrás até HORIZONTE dias à frente). Ficam de fora as ocorrências canceladas e os convites que o dono recusou.
  Ocupado é o "Mostrar como: Ocupado" do Google (TRANSP diferente de TRANSPARENT; o Google põe o dia inteiro como
  Disponível).
- De tempos em tempos (vigiar): a cada INTERVALO, as agendas das pessoas ativas com a Gestão. Falhas seguidas espaçam
  as tentativas (até ESPERA_MAX); o endereço que morreu (trocar) espera o máximo até a pessoa colar outro.
- Horário ocupado (ocupados, que bi/agenda.py usa): o evento ocupado de uma agenda lida há menos de VALIDADE trava a
  pessoa para as tarefas e subtarefas dos outros e só avisa a própria pessoa.
- Sem a chave em [google] (no PC), nada daqui aparece nem trava: a página avisa que a leitura fica no site.
"""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import hashlib
import http.client
import importlib.util
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote, unquote, urlsplit

from .agenda import HORIZONTE, _hhmm, _id, pedacos
from .banco import Banco, BancoForaDoAr, hora, inicio_do_dia
from .calendario import UM_DIA
from .conversas import NaoEncontrada
from .tarefas import _COM_GESTAO

log = logging.getLogger("bi.google")

PACOTES = ("icalendar", "recurring_ical_events", "cryptography")
MAX_AGENDAS = 5                           # agendas do Google por pessoa
INTERVALO = dt.timedelta(minutes=10)      # o vigia relê cada agenda
MANUAL = dt.timedelta(minutes=1)          # "Atualizar agora": no máximo uma vez por minuto em cada agenda
ESPERA_MAX = dt.timedelta(hours=2)        # as falhas seguidas espaçam as tentativas até isto
VALIDADE = dt.timedelta(hours=24)         # leitura mais velha: os eventos aparecem, mas não travam ninguém
ATRASO_AVISO = dt.timedelta(hours=1)      # erro passageiro (o Google fora do ar): a página só avisa depois disto
VOLTA = 60                                # segundos entre as voltas do vigia
TEMPO = 30                                # segundos para o Google responder e para baixar o arquivo inteiro
MAX_BYTES = 15 * 1024 * 1024              # o arquivo traz o histórico inteiro; o painel roda com 512 MB
MAX_OCORRENCIAS = 20_000                  # por agenda, na janela
MESES_ANTES = 3                           # a janela começa no 1º dia de 3 meses atrás
MAX_TITULO = 120
VERSAO = 1                                # do leitor: mudar faz todas as agendas serem interpretadas de novo
SEM_TITULO = "(sem título)"
SITE = "A leitura do Google Agenda fica no site (bi.maisvida.cloud): conecte a sua agenda por lá."
COMO_COPIAR = ("copie o “Endereço secreto no formato iCal”: no Google Agenda, no computador, Configurações › clique na "
               "agenda › Integrar agenda")
_NAO_ACHOU = "agenda do Google não encontrada; ela pode ter sido removida"
_CAMINHO = re.compile(r"/calendar/ical/([^/]+)/private-([0-9a-fA-F]{16,64})/basic\.ics")
_ID = re.compile(r"[A-Za-z0-9._%+#-]+@[A-Za-z0-9.-]+")
_DTSTAMP = re.compile(rb"^DTSTAMP[;:][^\r\n]*(?:\r?\n)?", re.M)
_FREQ_ALTA = re.compile(rb"FREQ=(?:SECONDLY|MINUTELY|HOURLY)", re.I)
_REPETE = {b"RRULE", b"RDATE", b"EXDATE", b"RECURRENCE-ID", b"DURATION"}


class ErroGoogle(ValueError):
    """Falha da leitura, com texto fixo (nunca o endereço nem os eventos). trocar: o endereço morreu e a pessoa precisa
    colar outro; nas outras, o BI tenta de novo sozinho."""

    def __init__(self, mensagem: str, trocar: bool = False):
        super().__init__(mensagem)
        self.trocar = trocar


# --- o endereço -------------------------------------------------------------------------------------------------------
def endereco_valido(texto) -> tuple[str, str]:
    """O endereço secreto colado, conferido e remontado: (endereço, id da agenda em minúsculas)."""
    t = str(texto or "").strip()
    if not t:
        raise ErroGoogle(f"cole o endereço da agenda: {COMO_COPIAR}")
    if len(t) > 600:
        raise ErroGoogle(f"esse texto não é um endereço de agenda: {COMO_COPIAR}")
    if _ID.fullmatch(t):
        raise ErroGoogle(f"esse é o ID da agenda, não o endereço: {COMO_COPIAR}")
    u = urlsplit(t)
    do_google = u.netloc.lower() == "calendar.google.com"
    if do_google and "/public/" in u.path:
        raise ErroGoogle(f"esse é o endereço público, que só funciona com a agenda aberta a todos: {COMO_COPIAR}")
    if do_google and "/embed" in u.path:
        raise ErroGoogle(f"esse é o link para incorporar a agenda num site: {COMO_COPIAR}")
    m = _CAMINHO.fullmatch(u.path)
    if u.scheme.lower() != "https" or not do_google or u.query or u.fragment or not m:
        raise ErroGoogle(f"esse não é o endereço secreto do Google Agenda: {COMO_COPIAR}")
    calendario = unquote(m[1])
    if not _ID.fullmatch(calendario):
        raise ErroGoogle(f"esse não é o endereço secreto do Google Agenda: {COMO_COPIAR}")
    url = f"https://calendar.google.com/calendar/ical/{quote(calendario, safe='')}/private-{m[2]}/basic.ics"
    return url, calendario.lower()


def _fernet(chave: str):
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"bi-google-agenda\n" + chave.encode()).digest()))


def cifrar(chave: str, endereco: str) -> str:
    return _fernet(chave).encrypt(endereco.encode()).decode()


def decifrar(chave: str, cifrado: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        return _fernet(chave).decrypt(cifrado.encode()).decode()
    except (InvalidToken, ValueError):
        raise ErroGoogle("o endereço guardado não abre mais (a chave do servidor mudou): cole o endereço secreto de "
                         "novo", trocar=True) from None


# --- baixar e interpretar ---------------------------------------------------------------------------------------------
class _SoGoogle(urllib.request.HTTPRedirectHandler):
    """Desvio (redirecionamento) só para https em *.google.com, até 3."""

    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urlsplit(newurl)
        host = (u.hostname or "").lower()
        if (u.scheme.lower() != "https" or u.port not in (None, 443) or u.username or u.password
                or not (host == "google.com" or host.endswith(".google.com"))):
            raise ErroGoogle("o Google mandou o pedido para outro lugar; o BI tenta de novo sozinho mais tarde")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def baixar(url: str) -> bytes:
    """O arquivo da agenda (até MAX_BYTES, em até TEMPO segundos). Endereço que o Google não reconhece mais (ou uma
    página no lugar da agenda): ErroGoogle com trocar."""
    pedido = urllib.request.Request(url, headers={"User-Agent": "BIMetasMaisVida-agenda/1.0",
                                                  "Accept": "text/calendar"})
    limite = time.monotonic() + TEMPO
    partes, total = [], 0
    try:
        with urllib.request.build_opener(_SoGoogle).open(pedido, timeout=TEMPO) as r:
            while bloco := r.read(1 << 16):
                total += len(bloco)
                if total > MAX_BYTES:
                    raise ErroGoogle(f"a agenda passa de {MAX_BYTES // 2 ** 20} MB; o BI não lê agendas desse tamanho")
                if time.monotonic() > limite:
                    raise ErroGoogle("o Google demorou demais para mandar a agenda; o BI tenta de novo sozinho")
                partes.append(bloco)
    except ErroGoogle:
        raise
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404, 410):
            raise ErroGoogle("o Google não aceitou mais o endereço (ele pode ter sido redefinido): cole o endereço "
                             "secreto de novo", trocar=True) from None
        raise ErroGoogle(f"o Google não respondeu direito agora (erro {e.code}); o BI tenta de novo sozinho") from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise ErroGoogle("sem resposta do Google agora; o BI tenta de novo sozinho") from None
    corpo = b"".join(partes)
    if not corpo.lstrip(b"\xef\xbb\xbf \t\r\n").upper().startswith(b"BEGIN:VCALENDAR"):
        raise ErroGoogle("o endereço não trouxe uma agenda: cole de novo o “Endereço secreto no formato iCal”",
                         trocar=True)
    return corpo


def assinatura(corpo: bytes, hoje: dt.date) -> str:
    """O que distingue uma leitura da outra: o arquivo sem as linhas DTSTAMP (o Google refaz a cada download), o dia de
    hoje (a janela anda) e a versão do leitor. Igual à última: não há o que regravar."""
    return hashlib.sha256(f"{VERSAO}|{hoje.isoformat()}\n".encode() + _DTSTAMP.sub(b"", corpo)).hexdigest()


def janela(hoje: dt.date) -> tuple[dt.date, dt.date]:
    """Os dias que a leitura guarda: do 1º dia de MESES_ANTES meses atrás a HORIZONTE dias à frente (o fim,
    exclusive)."""
    mes = hoje.year * 12 + hoje.month - 1 - MESES_ANTES
    return dt.date(mes // 12, mes % 12 + 1, 1), hoje + dt.timedelta(HORIZONTE + 1)


def recortar(corpo: bytes, desde: dt.date) -> bytes:
    """Tira do arquivo, antes de interpretar, o que não pode cair na janela: os eventos avulsos (sem repetição) que
    acabaram dois dias antes de desde (a folga cobre o fuso) e as séries que se repetem por hora ou minuto (o Google não
    cria; abertas, encheriam a memória). O arquivo do Google traz o histórico inteiro da agenda."""
    corte = (desde - 2 * UM_DIA).strftime("%Y%m%d").encode()
    saida, evento = [], None
    for linha in re.sub(rb"\r?\n[ \t]", b"", corpo).splitlines():  # desdobra as linhas longas
        marca = linha.strip().upper()
        if evento is not None:
            evento.append(linha)
            if marca == b"END:VEVENT":
                if _fica(evento, corte):
                    saida += evento
                evento = None
        elif marca == b"BEGIN:VEVENT":
            evento = [linha]
        else:
            saida.append(linha)
    return b"\r\n".join(saida + (evento or [])) + b"\r\n"


def _fica(evento: list[bytes], corte: bytes) -> bool:
    campos = {}
    for linha in evento:
        campos.setdefault(re.split(rb"[;:]", linha, maxsplit=1)[0].strip().upper(), linha)
    if b"RRULE" in campos and _FREQ_ALTA.search(campos[b"RRULE"]):
        return False
    if campos.keys() & _REPETE:
        return True
    valor = (campos.get(b"DTEND") or campos.get(b"DTSTART") or b"").rsplit(b":", 1)[-1].strip()[:8]
    return not (len(valor) == 8 and valor.isdigit() and valor < corte)


def interpretar(corpo: bytes, desde: dt.date, ate: dt.date, dono: str) -> tuple[str | None, list[tuple]]:
    """O arquivo em (nome da agenda, [(título, início, fim, dia inteiro, ocupado)]): as ocorrências que tocam de desde a
    ate (exclusive), com início e fim em hora local com fuso, em ordem. Ficam de fora as canceladas e as que o dono
    recusou, ocorrência por ocorrência (a mudada sozinha traz STATUS e ATTENDEE próprios)."""
    import icalendar
    import recurring_ical_events
    try:
        cal = icalendar.Calendar.from_ical(corpo)
        ocorrencias = recurring_ical_events.of(cal, skip_bad_series=True).between(desde, ate)
        nome = " ".join(str(cal.get("X-WR-CALNAME") or "").split())[:MAX_TITULO] or None
    except Exception as e:
        log.warning("agenda do Google que não abriu (%s)", type(e).__name__)
        raise ErroGoogle("o BI não conseguiu interpretar esta agenda do Google; ele tenta de novo mais tarde") from None
    if len(ocorrencias) > MAX_OCORRENCIAS:
        teto = f"{MAX_OCORRENCIAS:_}".replace("_", ".")
        raise ErroGoogle(f"a agenda tem mais de {teto} eventos nos próximos meses; o BI não lê agendas desse tamanho")
    dono, eventos = dono.lower(), []
    for ev in ocorrencias:
        if str(ev.get("STATUS") or "").upper() == "CANCELLED" or _recusou(ev, dono):
            continue
        inicio, fim = _local(ev.start), _local(ev.end)
        titulo = " ".join(str(ev.get("SUMMARY") or "").split())[:MAX_TITULO] or SEM_TITULO
        eventos.append((titulo, inicio, max(inicio, fim), not isinstance(ev.start, dt.datetime),
                        str(ev.get("TRANSP") or "OPAQUE").upper() != "TRANSPARENT"))
    return nome, sorted(eventos, key=lambda e: (e[1], e[2], e[0]))


def _local(x) -> dt.datetime:
    """A data (dia inteiro: a meia-noite) ou a hora do evento em hora local com fuso; a hora sem fuso é a local."""
    return (x if isinstance(x, dt.datetime) else dt.datetime.combine(x, dt.time())).astimezone()


def _recusou(ev, dono: str) -> bool:
    convidados = ev.get("ATTENDEE")
    for c in convidados if isinstance(convidados, list) else [convidados] if convidados else []:
        if (str(c).lower().removeprefix("mailto:") == dono
                and str(c.params.get("PARTSTAT", "")).upper() == "DECLINED"):
            return True
    return False


def espera(falhas: int, trocar: bool) -> dt.timedelta:
    """Quanto o vigia espera desde a última tentativa: INTERVALO, dobrando a cada falha seguida, até ESPERA_MAX; o
    endereço que morreu espera o máximo (só volta quando a pessoa colar outro)."""
    return ESPERA_MAX if trocar else min(INTERVALO * 2 ** min(falhas, 8), ESPERA_MAX)


def _sem_fuso(x: dt.datetime) -> dt.datetime:
    return x.astimezone().replace(tzinfo=None)


class GoogleAgenda:
    def __init__(self, banco: Banco, ini=None, *, agora=None, baixador=None):
        """ini: o config.ini ([google] chave). agora: o relógio, hora local sem fuso (os testes fixam). baixador: troca
        o baixar (os testes não vão à internet)."""
        self.banco = banco
        self.chave = (ini.get("google", "chave", fallback="") if ini is not None else "").strip()
        self.agora = agora or dt.datetime.now
        self._baixar = baixador or baixar
        self.falta = [p for p in PACOTES if importlib.util.find_spec(p) is None]
        self.pausa = 1.0  # segundos entre uma agenda e outra numa volta do vigia
        self._vez_trava = threading.Lock()
        self._sem_banco_em = None

    @property
    def ativo(self) -> bool:
        return bool(self.chave) and not self.falta

    @property
    def aviso(self) -> str | None:
        if not self.chave:
            return SITE
        if self.falta:
            return f"Falta instalar no servidor os pacotes da leitura do Google Agenda: {', '.join(self.falta)}."
        return None

    def _exigir(self) -> None:
        if not self.ativo:
            raise ValueError(self.aviso)

    @contextlib.contextmanager
    def _vez(self, manual: bool):
        """Uma leitura por vez no processo (memória); quem clicou espera um pouco, o vigia espera o quanto for."""
        if not self._vez_trava.acquire(timeout=45 if manual else -1):
            raise ErroGoogle("outra agenda do Google está sendo lida agora; tente de novo em instantes")
        try:
            yield
        finally:
            self._vez_trava.release()

    # --- as agendas da pessoa --------------------------------------------------------------
    def listar(self, usuario: int) -> dict:
        """As agendas conectadas (sem o endereço) e como foi a última leitura de cada uma."""
        if not self.ativo:
            return {"ativo": False, "aviso": self.aviso, "agendas": []}
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT a.id, a.nome, a.calendario, a.lida_em, a.tentativa_em, a.erro, a.trocar, "
                "(SELECT count(*) FROM google_eventos e WHERE e.agenda = a.id) FROM google_agendas a "
                "WHERE a.usuario = %s ORDER BY a.criada_em, a.id", [usuario]).fetchall()
        agora = self.agora().astimezone()
        return {"ativo": True, "aviso": None, "agendas": [self._publica(linha, agora) for linha in linhas]}

    @staticmethod
    def _publica(linha, agora: dt.datetime) -> dict:
        """desatualizada: sem leitura boa há mais de VALIDADE (não trava). atencao: a página avisa (o endereço morreu,
        ou o erro passageiro já dura mais de ATRASO_AVISO)."""
        id_, nome, calendario, lida_em, tentativa_em, erro, trocar, eventos = linha
        sem_ler = lida_em is None or agora - lida_em > ATRASO_AVISO
        return {"id": id_, "nome": nome, "calendario": calendario, "lida_em": hora(lida_em),
                "tentativa_em": hora(tentativa_em), "erro": erro, "trocar": trocar, "eventos": eventos,
                "desatualizada": lida_em is None or agora - lida_em > VALIDADE,
                "atencao": bool(trocar or (erro and sem_ler))}

    def conectar(self, usuario: int, endereco) -> dict:
        """Lê a agenda do endereço colado e guarda. A mesma agenda de novo (o endereço redefinido no Google) troca o
        endereço na mesma linha; endereço que não lê não entra."""
        self._exigir()
        url, calendario = endereco_valido(endereco)
        with self.banco.conexao() as con:
            ja = con.execute("SELECT 1 FROM google_agendas WHERE usuario = %s AND calendario = %s",
                             [usuario, calendario]).fetchone()
            if not ja and con.execute("SELECT count(*) FROM google_agendas WHERE usuario = %s",
                                      [usuario]).fetchone()[0] >= MAX_AGENDAS:
                raise ValueError(f"cada pessoa conecta até {MAX_AGENDAS} agendas do Google: remova uma antes")
        agora = self.agora().astimezone()
        desde, ate = janela(agora.date())
        with self._vez(manual=True):
            corpo = self._baixar(url)
            nome, eventos = interpretar(recortar(corpo, desde), desde, ate, calendario)
        with self.banco.conexao() as con:
            linha = con.execute(
                "INSERT INTO google_agendas (usuario, calendario, nome, endereco, conteudo, lida_em, tentativa_em) "
                "SELECT id, %(cal)s, %(nome)s, %(end)s, %(cont)s, %(agora)s, %(agora)s FROM usuarios WHERE id = %(u)s "
                "ON CONFLICT (usuario, calendario) DO UPDATE SET nome = EXCLUDED.nome, endereco = EXCLUDED.endereco, "
                "conteudo = EXCLUDED.conteudo, lida_em = EXCLUDED.lida_em, tentativa_em = EXCLUDED.tentativa_em, "
                "erro = NULL, trocar = false, falhas = 0 RETURNING id, xmax = 0",
                {"cal": calendario, "nome": nome or calendario[:MAX_TITULO], "end": cifrar(self.chave, url),
                 "cont": assinatura(corpo, agora.date()), "agora": agora, "u": usuario}).fetchone()
            if not linha:
                raise NaoEncontrada("seu usuário não existe mais")
            self._gravar_eventos(con, linha[0], eventos)
        agenda = next(a for a in self.listar(usuario)["agendas"] if a["id"] == linha[0])
        return {"agenda": agenda, "nova": linha[1]}

    def remover(self, usuario: int, id_) -> None:
        """Tira a agenda e os eventos dela do BI (no Google nada muda)."""
        with self.banco.conexao() as con:
            if not con.execute("DELETE FROM google_agendas WHERE id = %s AND usuario = %s",
                               [_id(id_, _NAO_ACHOU), usuario]).rowcount:
                raise NaoEncontrada(_NAO_ACHOU)

    def atualizar(self, usuario: int, id_=None) -> int:
        """O botão Atualizar agora: relê as agendas da pessoa (ou só a id_) que não foram tentadas no último minuto."""
        self._exigir()
        uma = id_ is not None and id_ != ""
        with self.banco.conexao() as con:
            ids = [r[0] for r in con.execute(
                "SELECT id FROM google_agendas WHERE usuario = %s" + (" AND id = %s" if uma else "") + " ORDER BY id",
                [usuario, *([_id(id_, _NAO_ACHOU)] if uma else [])])]
        if uma and not ids:
            raise NaoEncontrada(_NAO_ACHOU)
        lidas = sum(self.ler(i, MANUAL) for i in ids)
        if ids and not lidas:
            raise ValueError("a agenda acabou de ser lida: tente de novo daqui a um minuto")
        return lidas

    # --- a leitura -------------------------------------------------------------------------
    def ler(self, id_: int, espera_min: dt.timedelta = INTERVALO) -> bool:
        """Lê uma agenda se a última tentativa tem mais de espera_min (False: não era a vez). A vez fica reservada em
        tentativa_em antes de baixar; baixar e interpretar não seguram conexão do banco, e o resultado só é gravado se
        o endereço não mudou enquanto isso (a pessoa colou outro ou removeu a agenda)."""
        with self._vez(manual=espera_min <= MANUAL):
            agora = self.agora().astimezone()
            with self.banco.conexao() as con:
                linha = con.execute(
                    "UPDATE google_agendas SET tentativa_em = %s WHERE id = %s AND (tentativa_em IS NULL OR "
                    "tentativa_em <= %s) RETURNING endereco, conteudo, calendario",
                    [agora, id_, agora - espera_min]).fetchone()
            if not linha:
                return False
            cifrado, conteudo, calendario = linha
            try:
                corpo = self._baixar(decifrar(self.chave, cifrado))
                assinado = assinatura(corpo, agora.date())
                if assinado == conteudo:
                    nome = eventos = None
                else:
                    desde, ate = janela(agora.date())
                    nome, eventos = interpretar(recortar(corpo, desde), desde, ate, calendario)
            except ErroGoogle as e:
                self._falhou(id_, cifrado, e)
                return True
            except Exception as e:  # o texto pode ter o endereço ou um evento: no log, só o tipo
                log.error("agenda do Google %s: falha inesperada na leitura (%s)", id_, type(e).__name__)
                self._falhou(id_, cifrado, ErroGoogle("falha inesperada na leitura; o BI tenta de novo sozinho"))
                return True
        with self.banco.conexao() as con:
            if not con.execute("SELECT 1 FROM google_agendas WHERE id = %s AND endereco = %s FOR UPDATE",
                               [id_, cifrado]).fetchone():
                return True  # reconectada ou removida enquanto lia: vale a de agora
            if eventos is not None:
                self._gravar_eventos(con, id_, eventos)
            con.execute("UPDATE google_agendas SET lida_em = %s, conteudo = %s, erro = NULL, trocar = false, "
                        "falhas = 0, nome = coalesce(%s, nome) WHERE id = %s", [agora, assinado, nome, id_])
        return True

    def _falhou(self, id_: int, cifrado: str, e: ErroGoogle) -> None:
        log.warning("agenda do Google %s: %s", id_, e)
        with self.banco.conexao() as con:
            con.execute("UPDATE google_agendas SET erro = %s, trocar = %s, falhas = least(falhas + 1, 30) "
                        "WHERE id = %s AND endereco = %s", [str(e), e.trocar, id_, cifrado])

    @staticmethod
    def _gravar_eventos(con, agenda: int, eventos: list[tuple]) -> None:
        con.execute("DELETE FROM google_eventos WHERE agenda = %s", [agenda])
        with con.cursor() as cur:
            cur.executemany("INSERT INTO google_eventos (agenda, titulo, inicio, fim, dia_inteiro, ocupado) "
                            "VALUES (%s, %s, %s, %s, %s, %s)", [(agenda, *e) for e in eventos])

    def rodada(self) -> int:
        """Uma volta do vigia: lê as agendas que estão na hora, das pessoas ativas com a Gestão (quem saiu deixa de
        ser lido). Uma agenda com erro não para as outras. Devolve quantas leu."""
        agora = self.agora().astimezone()
        with self.banco.conexao() as con:
            linhas = con.execute(
                "SELECT a.id, a.tentativa_em, a.falhas, a.trocar FROM google_agendas a JOIN usuarios u ON "
                f"u.id = a.usuario WHERE {_COM_GESTAO} ORDER BY a.tentativa_em NULLS FIRST, a.id").fetchall()
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
        """A leitura de tempos em tempos (thread "google"), onde a leitura está ligada: no PC e no VPS."""
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
        (google), que não contam nas contas do dia; no topo, as agendas (para a página avisar)."""
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
                "JOIN google_agendas a ON a.id = e.agenda WHERE a.usuario = %(u)s AND e.inicio < %(ate)s "
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
        """Os eventos ocupados das pessoas que tocam os dias de de a ate, só das agendas lidas há menos de VALIDADE,
        com o nome da pessoa, em hora local sem fuso (o horário ocupado, bi/agenda.py). Sem a leitura ligada, nenhum."""
        if not self.ativo or not pessoas:
            return []
        linhas = con.execute(
            "SELECT a.usuario, u.nome, e.titulo, e.inicio, e.fim, e.dia_inteiro FROM google_eventos e "
            "JOIN google_agendas a ON a.id = e.agenda JOIN usuarios u ON u.id = a.usuario "
            "WHERE a.usuario = ANY(%(p)s::bigint[]) AND e.ocupado AND e.fim > e.inicio AND a.lida_em >= %(validade)s "
            "AND e.fim > %(de)s AND e.inicio < %(ate)s ORDER BY e.inicio, e.fim",
            {"p": sorted(set(pessoas)), "validade": self.agora().astimezone() - VALIDADE, "de": inicio_do_dia(de),
             "ate": inicio_do_dia(ate + UM_DIA)}).fetchall()
        return [{"usuario": u, "nome": n, "titulo": t, "inicio": _sem_fuso(i), "fim": _sem_fuso(f), "dia_inteiro": d}
                for u, n, t, i, f, d in linhas]

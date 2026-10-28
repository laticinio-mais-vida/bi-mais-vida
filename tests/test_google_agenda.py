"""Google Agenda, só leitura (bi/google_agenda.py): o endereço secreto (conferido, remontado e cifrado), o arquivo iCal
(repetições, exceções, cancelados, recusados, fusos, dia inteiro), os pedaços de cada dia e, no PostgreSQL, conectar,
ler, o vigia, o que a agenda mostra, o horário ocupado (trava os outros, avisa a própria pessoa) e o Assistente.

Nada aqui vai à internet: o baixar é trocado por um falso. Os testes do arquivo e da cifra precisam dos pacotes
(icalendar, recurring-ical-events, cryptography); os com o banco, de BI_TESTE_POSTGRES (veja tests/apoio.py)."""
from __future__ import annotations

import configparser
import datetime as dt
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from bi import google_agenda
from bi.agenda import Agenda, faixa_pedaco, pedacos
from bi.assistente import Ferramentas
from bi.conversas import NaoEncontrada
from bi.google_agenda import (SITE, ErroGoogle, GoogleAgenda, _SoGoogle, assinatura, baixar, cifrar, decifrar,
                              endereco_valido, espera, interpretar, janela, recortar)
from bi.tarefas import Tarefas
from tests.apoio import BaseBanco, ConfiguracaoFixa, criar_assistente, criar_calc

D, T, DT = dt.date, dt.time, dt.datetime
UTC = dt.timezone.utc
HOJE = D(2026, 10, 26)  # segunda-feira
AGORA = DT(2026, 10, 26, 9, 0)
GESTAO = ["metas", "gestao"]
TEM_ICAL = all(importlib.util.find_spec(p) for p in ("icalendar", "recurring_ical_events"))
TEM_CIFRA = importlib.util.find_spec("cryptography") is not None
CHAVE = "chave-de-teste"
URL = ("https://calendar.google.com/calendar/ical/ana.silva%40gmail.com/private-0123456789abcdef0123456789abcdef/"
       "basic.ics")
URL2 = URL.replace("0123456789abcdef0123", "fedcba98765432100123")  # a mesma agenda, com o endereço redefinido


def ini_google(chave: str = CHAVE) -> configparser.ConfigParser:
    ini = configparser.ConfigParser()
    ini.read_dict({"google": {"chave": chave}})
    return ini


def ics(*eventos: str, nome: str = "Pessoal", tz: str | None = "America/Sao_Paulo") -> bytes:
    """Um arquivo como o do Google (linhas com CRLF)."""
    cab = ["BEGIN:VCALENDAR", "PRODID:-//Google Inc//Google Calendar 70.9054//EN", "VERSION:2.0",
           "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{nome}", *([f"X-WR-TIMEZONE:{tz}"] if tz else [])]
    return "\r\n".join([*cab, *eventos, "END:VCALENDAR", ""]).encode()


def ev(*linhas: str, uid: str = "u1", stamp: str = "20261026T120000Z") -> str:
    return "\r\n".join(["BEGIN:VEVENT", f"DTSTAMP:{stamp}", f"UID:{uid}@google.com", *linhas, "END:VEVENT"])


SP = "TZID=America/Sao_Paulo"
CONSULTA = ev("DTSTART:20261030T170000Z", "DTEND:20261030T180000Z", "SUMMARY:Consulta médica", "TRANSP:OPAQUE",
              uid="consulta")
# Segunda, quarta e sexta às 7h; a de sexta (30/10) foi tirada, a de quarta (28/10) passou para quinta e a de 02/11
# foi cancelada sozinha.
ACADEMIA = [
    ev(f"DTSTART;{SP}:20261005T070000", f"DTEND;{SP}:20261005T080000", "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR",
       f"EXDATE;{SP}:20261030T070000", "SUMMARY:Academia", uid="academia"),
    ev(f"DTSTART;{SP}:20261029T070000", f"DTEND;{SP}:20261029T080000", f"RECURRENCE-ID;{SP}:20261028T070000",
       "SUMMARY:Academia (quinta)", uid="academia"),
    ev(f"DTSTART;{SP}:20261102T070000", f"DTEND;{SP}:20261102T080000", f"RECURRENCE-ID;{SP}:20261102T070000",
       "STATUS:CANCELLED", "SUMMARY:Academia", uid="academia"),
]
FERIAS = ev("DTSTART;VALUE=DATE:20261110", "DTEND;VALUE=DATE:20261115", "SUMMARY:Férias", "TRANSP:OPAQUE", uid="ferias")


def ler(corpo: bytes, desde=D(2026, 10, 1), ate=D(2026, 12, 1), dono="ana.silva@gmail.com"):
    return interpretar(corpo, desde, ate, dono)


def titulos(eventos) -> list[str]:
    return [e[0] for e in eventos]


class TestEndereco(unittest.TestCase):
    def test_aceita_e_remonta(self):
        url, calendario = endereco_valido(f"  {URL}\n")
        self.assertEqual((url, calendario), (URL, "ana.silva@gmail.com"))
        url, calendario = endereco_valido(URL.replace("https", "HTTPS").replace("calendar.google", "Calendar.Google"))
        self.assertEqual(url, URL)
        grupo = URL.replace("ana.silva%40gmail.com", "abc123%40group.calendar.google.com")
        self.assertEqual(endereco_valido(grupo), (grupo, "abc123@group.calendar.google.com"))

    def test_recusa(self):
        casos = {
            "": "cole o endereço",
            "ana.silva@gmail.com": "ID da agenda",
            URL.replace("https", "http"): "não é o endereço secreto",
            URL.replace("https", "webcal"): "não é o endereço secreto",
            URL.replace("calendar.google.com", "calendar.google.com.evil.com"): "não é o endereço secreto",
            URL.replace("calendar.google.com", "evil.com/calendar.google.com"): "não é o endereço secreto",
            URL.replace("calendar.google.com", "calendar.google.com@evil.com"): "não é o endereço secreto",
            URL.replace("calendar.google.com", "calendar.google.com:8443"): "não é o endereço secreto",
            URL + "?x=1": "não é o endereço secreto",
            URL + "#a": "não é o endereço secreto",
            URL.replace("ana.silva%40gmail.com", "..%2F..%2Fetc"): "não é o endereço secreto",
            URL.replace("ana.silva%40gmail.com", "ana%2F%40gmail.com"): "não é o endereço secreto",
            URL.replace("private-0123456789abcdef0123456789abcdef", "public"): "endereço público",
            "https://calendar.google.com/calendar/embed?src=ana.silva%40gmail.com": "incorporar",
            "x" * 700: "não é um endereço",
        }
        for texto, trecho in casos.items():
            with self.subTest(texto[:60]), self.assertRaises(ErroGoogle) as e:
                endereco_valido(texto)
            self.assertIn(trecho, str(e.exception))
            self.assertNotIn("private-", str(e.exception))


@unittest.skipUnless(TEM_CIFRA, "falta o pacote cryptography")
class TestCifra(unittest.TestCase):
    def test_ida_e_volta(self):
        cifrado = cifrar(CHAVE, URL)
        self.assertNotIn("private-", cifrado)
        self.assertNotEqual(cifrado, cifrar(CHAVE, URL))  # cada cifra sai diferente
        self.assertEqual(decifrar(CHAVE, cifrado), URL)

    def test_chave_errada(self):
        with self.assertRaises(ErroGoogle) as e:
            decifrar("outra", cifrar(CHAVE, URL))
        self.assertTrue(e.exception.trocar)
        self.assertIn("cole o endereço secreto de novo", str(e.exception))


class TestPedacos(unittest.TestCase):
    def ver(self, inicio, fim, dia_inteiro=False, de=D(2026, 10, 1), ate=D(2026, 12, 31)):
        return [(p["dia"].day, p["hora"], p["hora_fim"], p["dia_todo"], p["antes"], p["depois"])
                for p in pedacos(inicio, fim, dia_inteiro, de, ate)]

    def test_no_mesmo_dia(self):
        self.assertEqual(self.ver(DT(2026, 10, 30, 14), DT(2026, 10, 30, 15)),
                         [(30, T(14), T(15), False, False, False)])

    def test_passa_da_meia_noite(self):
        self.assertEqual(self.ver(DT(2026, 11, 10, 22), DT(2026, 11, 11, 2)),
                         [(10, T(22), None, False, False, True), (11, None, T(2), False, True, False)])
        self.assertEqual(self.ver(DT(2026, 11, 10, 22), DT(2026, 11, 11, 0)),  # acaba na meia-noite: um dia só
                         [(10, T(22), None, False, False, False)])

    def test_tres_dias_com_horario(self):
        self.assertEqual([p[:4] for p in self.ver(DT(2026, 11, 10, 22), DT(2026, 11, 12, 2))],
                         [(10, T(22), None, False), (11, None, None, True), (12, None, T(2), False)])

    def test_dia_inteiro_e_recorte(self):
        dias = self.ver(DT(2026, 11, 10), DT(2026, 11, 15), dia_inteiro=True)
        self.assertEqual([d[0] for d in dias], [10, 11, 12, 13, 14])  # o fim (15) não entra
        self.assertTrue(all(d[3] for d in dias))
        self.assertEqual([d[0] for d in self.ver(DT(2026, 11, 10), DT(2026, 11, 15), True, D(2026, 11, 12),
                                                 D(2026, 11, 13))], [12, 13])

    def test_sem_duracao(self):
        self.assertEqual(self.ver(DT(2026, 10, 30, 14), DT(2026, 10, 30, 14)),
                         [(30, T(14), T(14), False, False, False)])

    def test_faixa(self):
        casos = [(DT(2026, 10, 30, 14), DT(2026, 10, 30, 15), "das 14:00 às 15:00"),
                 (DT(2026, 10, 30, 14), DT(2026, 10, 30, 14), "às 14:00"),
                 (DT(2026, 10, 30, 22), DT(2026, 10, 31, 0), "das 22:00 à meia-noite")]
        for inicio, fim, texto in casos:
            self.assertEqual(faixa_pedaco(pedacos(inicio, fim, False, D(2026, 10, 30), D(2026, 10, 30))[0]), texto)
        meio = pedacos(DT(2026, 10, 30, 22), DT(2026, 11, 1, 2), False, D(2026, 10, 31), D(2026, 11, 1))
        self.assertEqual([faixa_pedaco(p) for p in meio], ["o dia todo", "da meia-noite às 02:00"])


class TestArquivo(unittest.TestCase):
    def test_assinatura_ignora_o_dtstamp(self):
        a = ics(ev("DTSTART:20261030T170000Z", "SUMMARY:A", stamp="20261026T120000Z"))
        b = ics(ev("DTSTART:20261030T170000Z", "SUMMARY:A", stamp="20261026T121000Z"))
        c = ics(ev("DTSTART:20261030T170000Z", "SUMMARY:B"))
        self.assertEqual(assinatura(a, HOJE), assinatura(b, HOJE))
        self.assertNotEqual(assinatura(a, HOJE), assinatura(c, HOJE))
        self.assertNotEqual(assinatura(a, HOJE), assinatura(a, HOJE + dt.timedelta(1)))  # a janela andou

    def test_janela(self):
        self.assertEqual(janela(HOJE), (D(2026, 7, 1), D(2027, 10, 28)))
        self.assertEqual(janela(D(2027, 2, 15))[0], D(2026, 11, 1))

    def test_espera(self):
        self.assertEqual([espera(n, False).seconds // 60 for n in range(6)], [10, 20, 40, 80, 120, 120])
        self.assertEqual(espera(0, True), google_agenda.ESPERA_MAX)

    def test_recortar_tira_os_antigos_e_as_series_por_hora(self):
        antigo = ev("DTSTART;VALUE=DATE:20250110", "DTEND;VALUE=DATE:20250111", "SUMMARY:Antigo", uid="antigo")
        longo = ev("DTSTART:20250110T120000Z", "DTEND:20250110T130000Z",
                   "SUMMARY:Um título bem comprido que o Google dobra em várias linhas para caber no limite de "
                   "setenta e cinco",
                   uid="longo").replace("setenta e cinco", "setenta\r\n  e cinco")
        serie_antiga = ev("DTSTART:20250105T120000Z", "DTEND:20250105T130000Z", "RRULE:FREQ=WEEKLY",
                          "SUMMARY:Semanal desde 2025", uid="serie")
        por_minuto = ev("DTSTART:20261026T120000Z", "DTEND:20261026T120100Z", "RRULE:FREQ=MINUTELY",
                        "SUMMARY:Por minuto", uid="minuto")
        corpo = ics(antigo, longo, serie_antiga, por_minuto, CONSULTA, *ACADEMIA)
        recortado = recortar(corpo, D(2026, 7, 1))
        self.assertNotIn(b"Antigo", recortado)
        self.assertNotIn(b"comprido", recortado)
        self.assertNotIn(b"Por minuto", recortado)
        for fica in (b"Semanal desde 2025", b"Consulta", b"RECURRENCE-ID", b"X-WR-CALNAME:Pessoal"):
            self.assertIn(fica, recortado)

    @unittest.skipUnless(TEM_ICAL, "faltam os pacotes do iCal")
    def test_recortar_nao_muda_o_que_cai_na_janela(self):
        corpo = ics(CONSULTA, *ACADEMIA, FERIAS, ev("DTSTART:20261001T020000Z", "DTEND:20261001T040000Z",
                                                  "SUMMARY:Começo da janela", uid="borda"))
        desde = D(2026, 10, 1)
        self.assertEqual(ler(recortar(corpo, desde), desde), ler(corpo, desde))


@unittest.skipUnless(TEM_ICAL, "faltam os pacotes do iCal")
class TestInterpretar(unittest.TestCase):
    def test_horario_ocupado_e_disponivel(self):
        livre = ev(f"DTSTART;{SP}:20261030T160000", f"DTEND;{SP}:20261030T170000", "SUMMARY:Café",
                   "TRANSP:TRANSPARENT", uid="cafe")
        sem_transp = ev(f"DTSTART;{SP}:20261031T090000", f"DTEND;{SP}:20261031T100000", "SUMMARY:Sem TRANSP",
                        uid="sem")
        nome, eventos = ler(ics(CONSULTA, livre, sem_transp))
        self.assertEqual(nome, "Pessoal")
        consulta, cafe, sem = eventos
        self.assertEqual((consulta[1], consulta[2]),
                         (DT(2026, 10, 30, 17, tzinfo=UTC), DT(2026, 10, 30, 18, tzinfo=UTC)))
        self.assertEqual([e[4] for e in eventos], [True, False, True])  # sem TRANSP: ocupado
        self.assertFalse(any(e[3] for e in eventos))

    def test_repeticao_com_excecoes(self):
        _, eventos = ler(ics(*ACADEMIA), desde=D(2026, 10, 26), ate=D(2026, 11, 7))
        dias = [(e[0], e[1].astimezone(dt.timezone(dt.timedelta(hours=-3))).strftime("%d/%m %H:%M")) for e in eventos]
        self.assertEqual(dias, [("Academia", "26/10 07:00"), ("Academia (quinta)", "29/10 07:00"),
                                ("Academia", "04/11 07:00"), ("Academia", "06/11 07:00")])  # sem 30/10 e 02/11

    def test_dia_inteiro_e_sem_fim(self):
        sem_fim_dia = ev("DTSTART;VALUE=DATE:20261105", "SUMMARY:Dia sem fim", uid="dia")
        sem_fim_hora = ev("DTSTART:20261106T120000Z", "SUMMARY:Hora sem fim", uid="hora")
        duracao = ev("DTSTART:20261107T120000Z", "DURATION:PT90M", "SUMMARY:Duração", uid="dur")
        _, eventos = ler(ics(FERIAS, sem_fim_dia, sem_fim_hora, duracao))
        por = {e[0]: e for e in eventos}
        ferias = por["Férias"]
        self.assertTrue(ferias[3] and ferias[4])
        self.assertEqual((ferias[1], ferias[2]), (DT(2026, 11, 10).astimezone(), DT(2026, 11, 15).astimezone()))
        self.assertEqual(por["Dia sem fim"][2] - por["Dia sem fim"][1], dt.timedelta(days=1))
        self.assertEqual(por["Hora sem fim"][2], por["Hora sem fim"][1])
        self.assertEqual(por["Duração"][2] - por["Duração"][1], dt.timedelta(minutes=90))

    def test_cancelados_e_recusados(self):
        cancelado = ev("DTSTART:20261103T120000Z", "DTEND:20261103T130000Z", "STATUS:CANCELLED", "SUMMARY:Cancelado",
                       uid="canc")
        convite = "ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT={};CN=X;X-NUM-GUESTS=0:mailto:{}"
        recusado = ev("DTSTART:20261104T120000Z", "DTEND:20261104T130000Z", "SUMMARY:Recusado",
                      convite.format("DECLINED", "Ana.Silva@Gmail.com"), convite.format("ACCEPTED", "beto@gmail.com"),
                      uid="rec")
        outro_recusou = ev("DTSTART:20261105T120000Z", "DTEND:20261105T130000Z", "SUMMARY:Outro recusou",
                           convite.format("ACCEPTED", "ana.silva@gmail.com"),
                           convite.format("DECLINED", "beto@gmail.com"), uid="out")
        _, eventos = ler(ics(cancelado, recusado, outro_recusou))
        self.assertEqual(titulos(eventos), ["Outro recusou"])

    def test_fusos(self):
        flutuante = ev("DTSTART:20261108T090000", "DTEND:20261108T100000", "SUMMARY:Flutuante", uid="flu")
        _, com = ler(ics(flutuante))
        self.assertEqual(com[0][1], DT(2026, 11, 8, 12, tzinfo=UTC))  # o fuso de X-WR-TIMEZONE (São Paulo)
        _, sem = ler(ics(flutuante, tz=None))
        self.assertEqual(sem[0][1], DT(2026, 11, 8, 9).astimezone())  # sem ele, a hora local do servidor
        # Nova York sai do horário de verão em 01/11: 9h passa de 13:00 para 14:00 em UTC
        ny = ev("DTSTART;TZID=America/New_York:20261030T090000", "DTEND;TZID=America/New_York:20261030T100000",
                "RRULE:FREQ=DAILY;COUNT=4", "SUMMARY:Nova York", uid="ny")
        _, eventos = ler(ics(ny, tz="America/New_York"))
        self.assertEqual([e[1].astimezone(UTC).hour for e in eventos], [13, 13, 14, 14])

    def test_titulos(self):
        _, eventos = ler(ics(ev("DTSTART:20261103T120000Z", "DTEND:20261103T130000Z", uid="a"),
                             ev("DTSTART:20261104T120000Z", "DTEND:20261104T130000Z", f"SUMMARY:{'x' * 300}", uid="b"),
                             ev("DTSTART:20261105T120000Z", "DTEND:20261105T130000Z", "SUMMARY:  Duas   linhas\\n ",
                                uid="c")))
        self.assertEqual(titulos(eventos), ["(sem título)", "x" * 120, "Duas linhas"])

    def test_passa_do_teto(self):
        diario = ev("DTSTART:20261001T120000Z", "DTEND:20261001T130000Z", "RRULE:FREQ=DAILY", "SUMMARY:D", uid="d")
        with mock.patch.object(google_agenda, "MAX_OCORRENCIAS", 5), self.assertRaises(ErroGoogle) as e:
            ler(ics(diario))
        self.assertIn("mais de 5 eventos", str(e.exception))

    def test_serie_quebrada_nao_derruba_as_outras(self):
        quebrada = ev("DTSTART:20261003T120000Z", "DTEND:20261003T130000Z", "RRULE:FREQ=WEEKLY;BYDAY=XX",
                      "SUMMARY:Quebrada", uid="q")
        _, eventos = ler(ics(quebrada, CONSULTA))
        self.assertIn("Consulta médica", titulos(eventos))

    def test_nao_e_agenda(self):
        with self.assertRaises(ErroGoogle), self.assertLogs("bi.google", "WARNING") as logs:
            ler(b"<html>entre na sua conta</html>")
        self.assertNotIn("entre na sua conta", "".join(logs.output))  # no log, só o tipo do erro


class RespostaFalsa(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class TestBaixar(unittest.TestCase):
    def baixar_com(self, efeito):
        abridor = mock.Mock()
        abridor.open.side_effect = efeito
        with mock.patch.object(google_agenda.urllib.request, "build_opener", return_value=abridor):
            return baixar(URL)

    def erro(self, efeito) -> ErroGoogle:
        with self.assertRaises(ErroGoogle) as e:
            self.baixar_com(efeito)
        self.assertNotIn("private-", str(e.exception))
        return e.exception

    def test_baixa(self):
        corpo = ics(CONSULTA)
        self.assertEqual(self.baixar_com(lambda *a, **k: RespostaFalsa(corpo)), corpo)

    def test_falhas(self):
        http = lambda codigo: urllib.error.HTTPError(URL, codigo, "erro", {}, None)  # noqa: E731
        for codigo in (401, 403, 404, 410):
            self.assertTrue(self.erro(http(codigo)).trocar, codigo)
        self.assertFalse(self.erro(http(500)).trocar)
        self.assertFalse(self.erro(urllib.error.URLError(f"timed out {URL}")).trocar)
        self.assertFalse(self.erro(TimeoutError()).trocar)
        self.assertTrue(self.erro(lambda *a, **k: RespostaFalsa(b"<html>login</html>")).trocar)
        with mock.patch.object(google_agenda, "MAX_BYTES", 10):
            self.assertIn("MB", str(self.erro(lambda *a, **k: RespostaFalsa(ics(CONSULTA)))))

    def test_desvio_so_para_o_google(self):
        pedido = urllib.request.Request(URL)
        for destino in ("https://evil.com/x", "http://calendar.google.com/x", "https://google.com.evil.com/x",
                        "https://calendar.google.com:8443/x", "https://u:p@calendar.google.com/x"):
            with self.subTest(destino), self.assertRaises(ErroGoogle):
                _SoGoogle().redirect_request(pedido, None, 302, "Found", {}, destino)
        novo = _SoGoogle().redirect_request(pedido, None, 302, "Found", {}, "https://calendar.google.com/outro.ics")
        self.assertEqual(novo.full_url, "https://calendar.google.com/outro.ics")


def semear(banco, usuario: int, eventos: list[tuple], lida_em=None, calendario="ana.silva@gmail.com",
           nome="Pessoal") -> int:
    """Uma agenda do Google gravada direto no banco, sem baixar: eventos [(titulo, inicio, fim, dia_inteiro, ocupado)]
    em hora local sem fuso. lida_em: a última leitura (padrão: AGORA)."""
    with banco.conexao() as con:
        agenda = con.execute(
            "INSERT INTO google_agendas (usuario, calendario, nome, endereco, lida_em, tentativa_em) "
            "VALUES (%s, %s, %s, 'cifrado', %s, %s) RETURNING id",
            [usuario, calendario, nome, (lida_em or AGORA).astimezone(), (lida_em or AGORA).astimezone()]).fetchone()[0]
        for titulo, inicio, fim, dia_inteiro, ocupado in eventos:
            con.execute("INSERT INTO google_eventos (agenda, titulo, inicio, fim, dia_inteiro, ocupado) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        [agenda, titulo, inicio.astimezone(), fim.astimezone(), dia_inteiro, ocupado])
    return agenda


@unittest.skipUnless(TEM_ICAL and TEM_CIFRA, "faltam os pacotes da leitura do Google")
class TestGoogleNoBanco(BaseBanco):
    """Ana conecta a agenda pessoal; o baixar é um falso com os arquivos de self.arquivos."""

    def setUp(self):
        super().setUp()
        self.ana, self.beto = (self.criar_usuario(n, paginas=GESTAO) for n in ("ana", "beto"))
        self.agora = AGORA
        self.arquivos = {URL: ics(CONSULTA, *ACADEMIA), URL2: ics(CONSULTA)}
        self.baixados = []
        self.google = GoogleAgenda(self.banco, ini_google(), agora=lambda: self.agora, baixador=self.baixar)
        self.google.pausa = 0

    def baixar(self, url: str) -> bytes:
        self.baixados.append(url)
        r = self.arquivos.get(url, ErroGoogle("o Google não aceitou mais o endereço", trocar=True))
        if isinstance(r, Exception):
            raise r
        return r(url) if callable(r) else r

    def passar(self, minutos: int) -> None:
        self.agora += dt.timedelta(minutes=minutos)

    def agenda_do_banco(self, id_: int) -> dict:
        with self.banco.conexao() as con:
            linha = con.execute("SELECT endereco, lida_em, tentativa_em, erro, trocar, falhas, nome "
                                "FROM google_agendas WHERE id = %s", [id_]).fetchone()
        return dict(zip(("endereco", "lida_em", "tentativa_em", "erro", "trocar", "falhas", "nome"), linha))

    def test_conectar_e_listar_sem_o_endereco(self):
        r = self.google.conectar(self.ana, URL)
        self.assertTrue(r["nova"])
        a = r["agenda"]
        self.assertEqual((a["nome"], a["calendario"], a["erro"], a["desatualizada"], a["atencao"]),
                         ("Pessoal", "ana.silva@gmail.com", None, False, False))
        self.assertGreater(a["eventos"], 3)
        guardado = self.agenda_do_banco(a["id"])["endereco"]
        self.assertNotIn("private-", guardado)
        self.assertEqual(decifrar(CHAVE, guardado), URL)
        m = Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE).mes(self.ana, "2026-10")
        for resposta in (self.google.listar(self.ana), self.google.no_mes(self.ana, m)):
            self.assertNotIn("private-", json.dumps(resposta, default=str))
        self.assertEqual(self.google.listar(self.beto)["agendas"], [])

    def test_reconectar_a_mesma_agenda_troca_o_endereco(self):
        id_ = self.google.conectar(self.ana, URL)["agenda"]["id"]
        with self.banco.conexao() as con:
            con.execute("UPDATE google_agendas SET erro = 'morreu', trocar = true, falhas = 3 WHERE id = %s", [id_])
        r = self.google.conectar(self.ana, URL2)  # o endereço novo, depois de Redefinir no Google
        self.assertEqual((r["nova"], r["agenda"]["id"], r["agenda"]["eventos"]), (False, id_, 1))
        g = self.agenda_do_banco(id_)
        self.assertEqual((decifrar(CHAVE, g["endereco"]), g["erro"], g["trocar"], g["falhas"]), (URL2, None, False, 0))

    def test_limite_e_falha_nao_gravam(self):
        for n in range(5):
            outra = URL.replace("ana.silva", f"agenda{n}")
            self.arquivos[outra] = ics(CONSULTA, nome=f"Agenda {n}")
            self.google.conectar(self.ana, outra)
        with self.assertRaises(ValueError) as e:
            self.google.conectar(self.ana, URL)
        self.assertIn("até 5 agendas", str(e.exception))
        with self.assertRaises(ErroGoogle):
            self.google.conectar(self.beto, URL.replace("ana.silva", "beto"))  # o Google recusa: nada entra
        self.assertEqual(self.contar("google_agendas"), 5)

    def test_sem_a_chave(self):
        sem = GoogleAgenda(self.banco, ini_google(""), baixador=self.baixar)
        self.assertEqual(sem.listar(self.ana), {"ativo": False, "aviso": SITE, "agendas": []})
        with self.assertRaises(ValueError) as e:
            sem.conectar(self.ana, URL)
        self.assertEqual(str(e.exception), SITE)
        semear(self.banco, self.ana, [("Consulta", DT(2026, 10, 30, 14), DT(2026, 10, 30, 15), False, True)])
        m = sem.no_mes(self.ana, Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE).mes(self.ana, "2026-10"))
        self.assertFalse(m["google"]["ativo"])
        self.assertTrue(all(d["google"] == [] for d in m["dias"]))
        with self.banco.conexao() as con:
            self.assertEqual(sem.ocupados(con, [self.ana], HOJE, D(2026, 11, 30)), [])
        self.assertEqual(self.baixados, [])

    def test_ler_troca_os_eventos_e_guarda_o_erro(self):
        id_ = self.google.conectar(self.ana, URL)["agenda"]["id"]
        self.assertFalse(self.google.ler(id_))  # acabou de ler: não é a vez
        self.passar(11)
        self.arquivos[URL] = ics(CONSULTA, nome="Pessoal (nova)")
        self.assertTrue(self.google.ler(id_))
        self.assertEqual(self.contar("google_eventos"), 1)
        self.assertEqual(self.agenda_do_banco(id_)["nome"], "Pessoal (nova)")
        # o arquivo igual (só o DTSTAMP mudou): só a leitura é anotada, os eventos ficam como estão
        self.arquivos[URL] = self.arquivos[URL].replace(b"20261026T120000Z", b"20261026T121500Z")
        with self.banco.conexao() as con:
            antes = con.execute("SELECT ctid FROM google_eventos").fetchall()
        self.passar(11)
        self.assertTrue(self.google.ler(id_))
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT ctid FROM google_eventos").fetchall(), antes)
        self.assertEqual(self.agenda_do_banco(id_)["lida_em"], self.agora.astimezone())
        # falhou: os eventos da última leitura ficam e o erro é guardado
        del self.arquivos[URL]
        self.passar(11)
        with self.assertLogs("bi.google", "WARNING") as logs:
            self.assertTrue(self.google.ler(id_))
        self.assertFalse(any("private-" in linha for linha in logs.output))
        g = self.agenda_do_banco(id_)
        self.assertEqual((g["erro"], g["trocar"], g["falhas"]), ("o Google não aceitou mais o endereço", True, 1))
        self.assertEqual(self.contar("google_eventos"), 1)
        lista = self.google.listar(self.ana)["agendas"][0]
        self.assertTrue(lista["atencao"])  # o endereço morreu: a página avisa na hora
        self.assertFalse(lista["desatualizada"])

    def test_erro_passageiro_so_avisa_depois_de_uma_hora(self):
        id_ = self.google.conectar(self.ana, URL)["agenda"]["id"]
        self.arquivos[URL] = ErroGoogle("sem resposta do Google agora")
        self.passar(11)
        with self.assertLogs("bi.google", "WARNING"):
            self.google.ler(id_)
        self.assertFalse(self.google.listar(self.ana)["agendas"][0]["atencao"])
        self.passar(60)
        with self.assertLogs("bi.google", "WARNING"):
            self.google.ler(id_)
        lista = self.google.listar(self.ana)["agendas"][0]
        self.assertEqual((lista["atencao"], lista["trocar"]), (True, False))

    def test_leitura_atrasada_nao_grava_por_cima(self):
        """A pessoa colou o endereço novo (ou removeu a agenda) enquanto o vigia baixava o antigo."""
        id_ = self.google.conectar(self.ana, URL)["agenda"]["id"]
        n = self.contar("google_eventos")

        def no_meio(url):
            with self.banco.conexao() as con:
                con.execute("UPDATE google_agendas SET endereco = 'novo' WHERE id = %s", [id_])
            return ics(CONSULTA)

        self.arquivos[URL] = no_meio
        self.passar(11)
        self.assertTrue(self.google.ler(id_))
        self.assertEqual(self.contar("google_eventos"), n)
        self.assertEqual(self.agenda_do_banco(id_)["lida_em"], AGORA.astimezone())

    def test_atualizar_agora(self):
        id_ = self.google.conectar(self.ana, URL)["agenda"]["id"]
        with self.assertRaises(ValueError) as e:
            self.google.atualizar(self.ana)
        self.assertIn("acabou de ser lida", str(e.exception))
        self.passar(2)
        self.assertEqual(self.google.atualizar(self.ana, id_), 1)
        with self.assertRaises(NaoEncontrada):
            self.google.atualizar(self.beto, id_)
        with self.assertRaises(NaoEncontrada):
            self.google.remover(self.beto, id_)
        self.google.remover(self.ana, id_)
        self.assertEqual((self.contar("google_agendas"), self.contar("google_eventos")), (0, 0))

    def test_rodada(self):
        ana = self.google.conectar(self.ana, URL)["agenda"]["id"]
        self.arquivos[URL.replace("ana.silva", "beto")] = ics(CONSULTA)
        beto = self.google.conectar(self.beto, URL.replace("ana.silva", "beto"))["agenda"]["id"]
        self.baixados.clear()
        self.assertEqual(self.google.rodada(), 0)  # as duas acabaram de ser lidas
        self.passar(10)
        self.assertEqual(self.google.rodada(), 2)
        with self.banco.conexao() as con:  # Beto saiu da Gestão; a de Ana falhou duas vezes seguidas
            con.execute("UPDATE usuarios SET paginas = '{metas}' WHERE id = %s", [self.beto])
            con.execute("UPDATE google_agendas SET falhas = 2 WHERE id = %s", [ana])
        self.passar(10)
        self.assertEqual(self.google.rodada(), 0)  # Ana espera 40 min; Beto não é mais lido
        self.passar(30)
        self.assertEqual(self.google.rodada(), 1)
        self.assertNotIn(URL.replace("ana.silva", "beto"), self.baixados[2:])
        self.assertTrue(beto)

    def test_no_mes(self):
        semear(self.banco, self.ana, [
            ("Voo", DT(2026, 10, 30, 22), DT(2026, 10, 31, 2), False, True),
            ("Aniversário", DT(2026, 10, 31), DT(2026, 11, 1), True, False)])
        agenda = Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE)
        m = self.google.no_mes(self.ana, agenda.mes(self.ana, "2026-10"))
        dias = {d["data"]: d for d in m["dias"]}
        self.assertEqual([(g["titulo"], g["hora"], g["hora_fim"], g["depois"]) for g in dias["2026-10-30"]["google"]],
                         [("Voo", "22:00", None, True)])
        self.assertEqual([(g["titulo"], g["hora"], g["hora_fim"], g["antes"], g["dia_todo"])
                          for g in dias["2026-10-31"]["google"]],
                         [("Aniversário", None, None, False, True), ("Voo", None, "02:00", True, False)])
        self.assertEqual(dias["2026-10-31"]["itens"], [])  # as contas do dia continuam só com o BI
        self.assertEqual(self.google.no_mes(self.beto, agenda.mes(self.beto, "2026-10"))["dias"][29]["google"], [])
        self.passar(25 * 60)  # mais de um dia sem leitura: aparece, marcado como desatualizado
        m = self.google.no_mes(self.ana, agenda.mes(self.ana, "2026-10"))
        self.assertTrue(m["dias"][29]["google"][0]["desatualizada"])
        self.assertTrue(m["google"]["agendas"][0]["desatualizada"])


class TestHorarioOcupadoGoogle(BaseBanco):
    """Hoje é 26/10/2026. Ana tem no Google: Consulta médica 30/10 14:00–15:00 (ocupado), Café 30/10 16:00–17:00
    (disponível) e Férias de 10 a 14/11 (dia inteiro, ocupado). Beto cria as tarefas."""

    def setUp(self):
        super().setUp()
        self.ana, self.beto = (self.criar_usuario(n, paginas=GESTAO) for n in ("ana", "beto"))
        self.google = GoogleAgenda(self.banco, ini_google(), agora=lambda: AGORA)
        self.google.falta = []  # os eventos vêm semeados: não precisa dos pacotes do iCal
        cfg = ConfiguracaoFixa()
        self.agenda = Agenda(self.banco, cfg, hoje=lambda: HOJE, google=self.google)
        self.tarefas = Tarefas(self.banco, cfg, hoje=lambda: HOJE, google=self.google)
        self.id_google = semear(self.banco, self.ana, [
            ("Consulta médica", DT(2026, 10, 30, 14), DT(2026, 10, 30, 15), False, True),
            ("Café", DT(2026, 10, 30, 16), DT(2026, 10, 30, 17), False, False),
            ("Férias", DT(2026, 11, 10), DT(2026, 11, 15), True, True)])

    def tarefa(self, quem: int, prazo: str, hora: str | None, com=(), **campos) -> dict:
        return self.tarefas.criar(quem, {"titulo": "Feira", "prazo": prazo, "hora": hora,
                                         "participantes": [{"id": p, "autonomia": True} for p in com], **campos})

    def test_trava_para_outra_pessoa(self):
        with self.assertRaises(ValueError) as e:
            self.tarefa(self.beto, "2026-10-30", "14:30", [self.ana])
        msg = str(e.exception)
        self.assertEqual(msg, "Ana está com o horário ocupado em 30/10, das 14:00 às 15:00: mude o horário da tarefa "
                              "“Feira”")
        self.assertNotIn("Consulta", msg)
        self.assertNotIn("Google", msg)
        with self.assertRaises(ValueError) as e:
            self.tarefa(self.beto, "2026-11-12", "10:00", [self.ana])
        self.assertTrue(str(e.exception).startswith("Ana está com o dia 12/11 ocupado: mude o horário"))
        with self.assertRaises(ValueError):
            self.tarefa(self.beto, "2026-10-30", None, [self.ana], subtarefas=[
                {"titulo": "Estande", "responsavel": self.ana, "prazo": "2026-10-30", "hora": "14:00"}])
        self.assertEqual(self.contar("agenda_tarefas"), 0)

    def test_passa(self):
        casos = [("2026-10-30", "15:00"), ("2026-10-30", "16:30"), ("2026-10-30", None), ("2026-11-15", "10:00")]
        for prazo, hora in casos:
            with self.subTest(prazo=prazo, hora=hora):
                self.assertEqual(self.tarefa(self.beto, prazo, hora, [self.ana])["avisos"], [])
        with self.banco.conexao() as con:  # leitura de mais de um dia atrás: não trava mais
            con.execute("UPDATE google_agendas SET lida_em = %s", [(AGORA - dt.timedelta(hours=25)).astimezone()])
        self.assertEqual(self.tarefa(self.beto, "2026-10-30", "14:30", [self.ana])["avisos"], [])
        self.google.chave = ""  # sem a chave, o Google não trava
        with self.banco.conexao() as con:
            con.execute("UPDATE google_agendas SET lida_em = %s", [AGORA.astimezone()])
        self.tarefa(self.beto, "2026-10-30", "14:30", [self.ana])

    def test_avisa_a_propria_pessoa(self):
        t = self.tarefa(self.ana, "2026-10-30", "14:30")
        self.assertEqual(t["avisos"], ["você tem “Consulta médica” no Google em 30/10, das 14:00 às 15:00"])
        self.assertEqual(self.contar("agenda_tarefas"), 1)
        # a tarefa de Beto, com Ana, criada antes de ela marcar a consulta das 9h no Google: nada é desfeito depois;
        # a subtarefa que Ana (com autonomia) cria para si nessa tarefa só avisa
        feira = self.tarefa(self.beto, "2026-11-03", "09:30", [self.ana])
        semear(self.banco, self.ana, [("Dentista", DT(2026, 11, 3, 9), DT(2026, 11, 3, 10), False, True)],
               calendario="trabalho@gmail.com", nome="Trabalho")
        r = self.tarefas.nova_subtarefa(self.ana, feira["id"], {"titulo": "Levar o material"})
        self.assertEqual(r["avisos"], ["você tem “Dentista” no Google em 03/11, das 09:00 às 10:00"])

    def test_atividade_avisa(self):
        a = self.agenda.criar(self.ana, {"titulo": "Ligar", "inicio": "2026-10-30", "hora": "14:30"})
        self.assertEqual(a["avisos"], ["você tem “Consulta médica” no Google em 30/10, das 14:00 às 15:00"])
        trazida = self.agenda.criar(self.ana, {"titulo": "Consulta médica", "inicio": "2026-10-30", "hora": "14:00",
                                               "hora_fim": "15:00"})
        self.assertEqual(trazida["avisos"], [])  # o próprio evento, trazido como atividade
        self.assertEqual(self.agenda.criar(self.ana, {"titulo": "Depois", "inicio": "2026-10-30", "hora": "15:00",
                                                      "hora_fim": "16:00"})["avisos"], [])
        semanal = self.agenda.criar(self.ana, {"titulo": "Visita", "inicio": "2026-10-26", "hora": "10:00",
                                               "repeticao": "semanal", "dias_semana": [5]})
        self.assertEqual(semanal["avisos"], ["você tem “Férias” no Google em 13/11, o dia todo"])
        so_titulo = self.agenda.editar(self.ana, a["id"], {"titulo": "Ligar para o João", "inicio": "2026-10-30",
                                                           "hora": "14:30"})
        self.assertEqual(so_titulo["avisos"], [])  # nem o dia nem o horário mudaram
        de_beto = self.agenda.criar(self.beto, {"titulo": "B", "inicio": "2026-10-30", "hora": "14:30"})
        self.assertEqual(de_beto["avisos"], [])  # o Google de outra pessoa não conta na atividade de Beto

    def test_conflito_do_bi_vem_antes(self):
        self.agenda.criar(self.ana, {"titulo": "Reunião", "inicio": "2026-10-30", "hora": "14:00", "hora_fim": "14:45",
                                     "ocupado": True})
        with self.assertRaises(ValueError) as e:
            self.tarefa(self.beto, "2026-10-30", "14:30", [self.ana])
        self.assertIn("das 14:00 às 14:45", str(e.exception))

    def test_propor_traz_os_avisos(self):
        p = self.agenda.propor(self.ana, "criar", dados={"titulo": "Ligar", "inicio": "2026-10-30", "hora": "14:30"})
        self.assertEqual(p["avisos"], ["você tem “Consulta médica” no Google em 30/10, das 14:00 às 15:00"])
        p = self.agenda.propor(self.ana, "criar", dados={"titulo": "Ligar", "inicio": "2026-10-29", "hora": "14:30"})
        self.assertNotIn("avisos", p)

    def test_periodo_do_assistente(self):
        r = self.agenda.periodo(self.ana, "2026-10-26", "2026-11-15")
        dias = {d["data"]: d for d in r["dias"]}
        self.assertEqual(dias["2026-10-30"]["google"],
                         [{"titulo": "Consulta médica", "hora": "14:00", "hora_fim": "15:00", "ocupado": True},
                          {"titulo": "Café", "hora": "16:00", "hora_fim": "17:00", "ocupado": False}])
        self.assertEqual(dias["2026-11-12"]["google"], [{"titulo": "Férias", "dia_todo": True, "ocupado": True}])
        self.assertEqual(dias["2026-10-30"]["itens"], [])  # dia só com o Google também aparece
        self.assertEqual((r["totais"]["ocorrencias"], r["totais"]["google"]), (0, 7))
        r = self.agenda.periodo(self.ana, "2026-10-26", "2026-11-15", "consulta")
        self.assertEqual([g["titulo"] for d in r["dias"] for g in d["google"]], ["Consulta médica"])
        self.assertEqual(self.agenda.periodo(self.beto, "2026-10-26", "2026-11-15")["dias"], [])


class TestGoogleNoAssistente(BaseBanco):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.calc = criar_calc(self.pasta, fora=(999,))
        self.ana = self.criar_usuario("ana", paginas=GESTAO)
        google = GoogleAgenda(self.banco, ini_google(), agora=lambda: AGORA)
        google.falta = []  # os eventos vêm semeados
        self.agenda = Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE, google=google)
        semear(self.banco, self.ana, [("Consulta médica", DT(2026, 10, 30, 14), DT(2026, 10, 30, 15), False, True)])

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()
        super().tearDown()

    def test_ve_e_ouve_os_avisos(self):
        a = criar_assistente(self.pasta, self.calc)
        f = Ferramentas(a.recorte(None), self.calc, a.cfg, None, agenda=self.agenda.contexto(self.ana))
        r, passo = f.executar("ver_agenda", {"de": "2026-10-26", "ate": "2026-11-01"})
        self.assertIsNone(passo["erro"])
        self.assertNotIn("aviso", r)  # sem atividade do BI, mas com o Google
        self.assertEqual(passo["amostra"], [["2026-10-30", "14:00–15:00", "Consulta médica", "Google"]])
        r, passo = f.executar("propor_agenda", {"acao": "criar", "titulo": "Ligar", "inicio": "2026-10-30",
                                                "hora": "14:30"})
        self.assertEqual(r["proposta"]["avisos"], ["você tem “Consulta médica” no Google em 30/10, das 14:00 às 15:00"])
        self.assertEqual(f.agenda_propostas[0]["avisos"], r["proposta"]["avisos"])


if __name__ == "__main__":
    unittest.main()

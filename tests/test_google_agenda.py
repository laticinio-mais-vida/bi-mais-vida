"""Google Agenda, só leitura (bi/google_agenda.py): os eventos da API do Google (dia inteiro, fusos, cancelados,
recusados), os pedaços de cada dia e, no PostgreSQL, o login com o Google (state, PKCE, a autorização cifrada), ligar e
desligar agendas, ler, o vigia, o que a agenda mostra, o horário ocupado (trava os outros, avisa a própria pessoa) e o
Assistente.

Nada aqui vai à internet: o Google é um falso (GoogleFalso), que responde ao login, à lista de agendas e aos eventos.
Os testes com o banco precisam de BI_TESTE_POSTGRES (veja tests/apoio.py) e do pacote cryptography."""
from __future__ import annotations

import base64
import configparser
import datetime as dt
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

from bi import google_agenda
from bi.agenda import Agenda, faixa_pedaco, pedacos
from bi.assistente import Ferramentas
from bi.conversas import NaoEncontrada
from bi.google_agenda import (ESCOPO, RETORNO, REVOGAR, SEM_CLIENTE, SITE, TOKEN, ErroGoogle, GoogleAgenda,
                              assinatura, cifrar, conferir, decifrar, espera, interpretar, janela, pedir)
from bi.tarefas import Tarefas
from tests.apoio import BaseBanco, ConfiguracaoFixa, criar_assistente, criar_calc

D, T, DT = dt.date, dt.time, dt.datetime
UTC = dt.timezone.utc
HOJE = D(2026, 10, 26)  # segunda-feira
AGORA = DT(2026, 10, 26, 9, 0)
GESTAO = ["metas", "gestao"]
TEM_CIFRA = importlib.util.find_spec("cryptography") is not None
CHAVE = "chave-de-teste"
CLIENTE = {"chave": CHAVE, "cliente_id": "id-teste.apps.googleusercontent.com", "cliente_segredo": "segredo-teste"}
ANA, FAMILIA = "ana.silva@gmail.com", "familia123@group.calendar.google.com"


def ini_google(**campos) -> configparser.ConfigParser:
    ini = configparser.ConfigParser()
    ini.read_dict({"google": {**CLIENTE, **campos}})
    return ini


def local(*partes) -> str:
    """A hora como a API devolve, com o fuso desta máquina: "2026-10-30T14:00:00-03:00"."""
    return DT(*partes).astimezone().isoformat()


def evento(titulo: str | None, inicio: str, fim: str, **campos) -> dict:
    """Um evento como a API devolve: inicio e fim com hora (local(...)) ou só a data, no dia inteiro."""
    chave = "date" if len(inicio) == 10 else "dateTime"
    return {**({"summary": titulo} if titulo is not None else {}), "status": "confirmed",
            "start": {chave: inicio}, "end": {chave: fim}, **campos}


CONSULTA = evento("Consulta médica", local(2026, 10, 30, 14), local(2026, 10, 30, 15))
CAFE = evento("Café", local(2026, 10, 30, 16), local(2026, 10, 30, 17), transparency="transparent")
FERIAS = evento("Férias", "2026-11-10", "2026-11-15")


class GoogleFalso:
    """O Google de mentira: as contas (e-mail: [(agenda, nome, principal)]), os eventos de cada agenda e as autorizações
    valendo. Confere o segredo do cliente, o PKCE e o endereço de retorno; guarda os pedidos e as revogações."""

    def __init__(self):
        self.contas = {ANA: [(ANA, "Ana Silva", True), (FAMILIA, "Família", False)],
                       "beto@gmail.com": [("beto@gmail.com", "beto@gmail.com", True)]}
        self.eventos = {ANA: [CONSULTA, CAFE, FERIAS], FAMILIA: [evento("Almoço", local(2026, 11, 1, 12),
                                                                        local(2026, 11, 1, 13))]}
        self.validas: dict[str, str] = {}  # autorização (refresh token): e-mail
        self.codigos: dict[str, tuple] = {}
        self.escopo = ESCOPO
        self.pedidos: list[tuple[str, str]] = []
        self.revogadas: list[str] = []
        self.falha: dict[str, tuple] = {}  # agenda: (status, corpo) no lugar dos eventos
        self.pagina = 2500
        self.ao_ler = None  # chamado antes de responder os eventos (o que acontece no meio da leitura)

    def login(self, url: str, email: str) -> dict:
        """A pessoa entra no Google e autoriza: os parâmetros com que o Google volta ao BI."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        codigo = f"codigo-{len(self.codigos)}"
        self.codigos[codigo] = (email, q["code_challenge"], q["redirect_uri"])
        return {"code": codigo, "state": q["state"]}

    def __call__(self, metodo: str, url: str, dados: dict | None = None, token: str | None = None):
        self.pedidos.append((metodo, url.split("?")[0]))
        if url == TOKEN:
            if dados["client_secret"] != "segredo-teste":
                return 401, {"error": "invalid_client"}
            if dados["grant_type"] == "authorization_code":
                email, desafio, retorno = self.codigos.pop(dados["code"], (None, None, None))
                verificador = base64.urlsafe_b64encode(hashlib.sha256(dados["code_verifier"].encode()).digest())
                if not email or verificador.rstrip(b"=").decode() != desafio or dados["redirect_uri"] != retorno:
                    return 400, {"error": "invalid_grant"}
                renovar = f"renovar-{len(self.validas) + len(self.revogadas)}"
                self.validas[renovar] = email
                return 200, {"access_token": f"acesso|{renovar}", "expires_in": 3599, "refresh_token": renovar,
                             "scope": self.escopo, "token_type": "Bearer"}
            if dados["refresh_token"] not in self.validas:
                return 400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
            return 200, {"access_token": f"acesso|{dados['refresh_token']}", "expires_in": 3599}
        if url == REVOGAR:
            self.revogadas.append(dados["token"])
            self.validas.pop(dados["token"].removeprefix("acesso|"), None)
            return 200, {}
        email = self.validas.get((token or "").removeprefix("acesso|"))
        if not email:
            return 401, {"error": {"code": 401, "errors": [{"reason": "authError"}]}}
        u = urlsplit(url)
        if u.path.endswith("/users/me/calendarList"):
            return 200, {"items": [{"id": c, "summary": n, **({"primary": True} if p else {})}
                                   for c, n, p in self.contas[email]]}
        agenda = unquote(u.path.split("/calendars/")[1].removesuffix("/events"))
        if agenda not in {c for c, _, _ in self.contas[email]}:
            return 404, {"error": {"code": 404, "errors": [{"reason": "notFound"}]}}
        if self.ao_ler:
            self.ao_ler()
        if agenda in self.falha:
            return self.falha[agenda]
        itens, inicio = self.eventos.get(agenda, []), int(parse_qs(u.query).get("pageToken", ["0"])[0])
        fim = inicio + self.pagina
        return 200, {"items": itens[inicio:fim], **({"nextPageToken": str(fim)} if fim < len(itens) else {})}

    def contar(self, url: str) -> int:
        return sum(1 for _, u in self.pedidos if u == url)


class TestEventosDaApi(unittest.TestCase):
    def test_hora_dia_inteiro_e_ocupado(self):
        eventos = interpretar([
            evento("Em UTC", "2026-10-30T17:00:00Z", "2026-10-30T18:00:00Z"),
            evento("Com fuso", "2026-10-30T14:00:00-03:00", "2026-10-30T15:30:00-03:00", transparency="opaque"),
            evento("Livre", "2026-10-31T09:00:00-03:00", "2026-10-31T10:00:00-03:00", transparency="transparent"),
            FERIAS])
        por = {e[0]: e for e in eventos}
        self.assertEqual((por["Em UTC"][1], por["Em UTC"][2]),
                         (DT(2026, 10, 30, 17, tzinfo=UTC), DT(2026, 10, 30, 18, tzinfo=UTC)))
        self.assertEqual(por["Com fuso"][2], DT(2026, 10, 30, 18, 30, tzinfo=UTC))
        self.assertEqual([(e[0], e[4]) for e in eventos],  # sem transparency: ocupado
                         [("Em UTC", True), ("Com fuso", True), ("Livre", False), ("Férias", True)])
        ferias = por["Férias"]
        self.assertTrue(ferias[3])
        self.assertEqual((ferias[1], ferias[2]), (DT(2026, 11, 10).astimezone(), DT(2026, 11, 15).astimezone()))
        self.assertFalse(por["Em UTC"][3])

    def test_o_que_fica_de_fora(self):
        eu = {"self": True, "responseStatus": "declined"}
        eventos = interpretar([
            evento("Cancelado", local(2026, 11, 3, 9), local(2026, 11, 3, 10), status="cancelled"),
            evento("Recusei", local(2026, 11, 4, 9), local(2026, 11, 4, 10), attendees=[eu]),
            evento("Outro recusou", local(2026, 11, 5, 9), local(2026, 11, 5, 10),
                   attendees=[{"email": "beto@gmail.com", "responseStatus": "declined"},
                              {"self": True, "responseStatus": "accepted"}]),
            evento("Escritório", "2026-11-06", "2026-11-07", eventType="workingLocation"),
            {"summary": "Sem data", "start": {}, "end": {}},
            {"summary": "Data quebrada", "start": {"date": "2026-13-01"}, "end": {"date": "2026-13-02"}},
            "não é um evento"])
        self.assertEqual([e[0] for e in eventos], ["Outro recusou"])

    def test_titulos_e_sem_fim(self):
        eventos = interpretar([
            evento(None, local(2026, 11, 3, 9), local(2026, 11, 3, 10)),
            evento("x" * 300, local(2026, 11, 4, 9), local(2026, 11, 4, 10)),
            evento("  Duas \n  linhas ", local(2026, 11, 5, 9), local(2026, 11, 5, 10)),
            {"summary": "Sem fim", "start": {"dateTime": local(2026, 11, 6, 9)}},
            evento("Fim antes", local(2026, 11, 7, 9), local(2026, 11, 7, 8))])
        self.assertEqual([e[0] for e in eventos], ["(sem título)", "x" * 120, "Duas linhas", "Sem fim", "Fim antes"])
        self.assertEqual(eventos[3][1], eventos[3][2])
        self.assertEqual(eventos[4][1], eventos[4][2])  # o fim nunca fica antes do início

    def test_assinatura(self):
        a = interpretar([CONSULTA, CAFE])
        self.assertEqual(assinatura(a), assinatura(interpretar([CAFE, CONSULTA])))
        self.assertNotEqual(assinatura(a), assinatura(interpretar([CONSULTA])))
        self.assertNotEqual(assinatura(a), assinatura(interpretar([CONSULTA, {**CAFE, "transparency": "opaque"}])))

    def test_janela_e_espera(self):
        self.assertEqual(janela(HOJE), (D(2026, 7, 1), D(2027, 10, 28)))
        self.assertEqual(janela(D(2027, 2, 15))[0], D(2026, 11, 1))
        self.assertEqual([espera(n, False).seconds // 60 for n in range(6)], [10, 20, 40, 80, 120, 120])
        self.assertEqual(espera(0, True), google_agenda.ESPERA_MAX)

    def test_conferir(self):
        conferir(200, {})
        casos = [(404, [], True), (403, ["forbidden"], True), (403, ["rateLimitExceeded"], False),
                 (429, [], False), (500, [], False), (401, [], False)]
        for status, motivos, trocar in casos:
            with self.subTest(status=status, motivos=motivos), self.assertLogs("bi.google", "WARNING"), \
                    self.assertRaises(ErroGoogle) as e:
                conferir(status, {"error": {"code": status, "errors": [{"reason": m} for m in motivos]}})
            self.assertEqual(e.exception.trocar, trocar)
            self.assertFalse(e.exception.conta)


class RespostaFalsa(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class TestPedir(unittest.TestCase):
    def pedir_com(self, efeito, **k):
        with mock.patch.object(google_agenda.urllib.request, "urlopen", side_effect=efeito) as abrir:
            r = pedir("POST", TOKEN, **k)
        return r, abrir.call_args[0][0]

    def test_resposta_e_pedido(self):
        r, pedido = self.pedir_com(lambda *a, **k: RespostaFalsa(b'{"access_token": "a"}'), dados={"x": "1"},
                                   token="t")
        self.assertEqual(r, (200, {"access_token": "a"}))
        self.assertEqual((pedido.data, pedido.get_header("Authorization")), (b"x=1", "Bearer t"))

    def test_erros(self):
        erro = urllib.error.HTTPError(TOKEN, 400, "erro", {}, io.BytesIO(b'{"error": "invalid_grant"}'))
        self.assertEqual(self.pedir_com(erro)[0], (400, {"error": "invalid_grant"}))
        quebrado = urllib.error.HTTPError(TOKEN, 502, "erro", {}, io.BytesIO(b"<html>"))
        self.assertEqual(self.pedir_com(quebrado)[0], (502, {}))
        for efeito in (urllib.error.URLError("timed out"), TimeoutError()):
            with self.assertRaises(ErroGoogle):
                self.pedir_com(efeito)
        with mock.patch.object(google_agenda, "MAX_BYTES", 5), self.assertRaises(ErroGoogle):
            self.pedir_com(lambda *a, **k: RespostaFalsa(b'{"items": []}'))


@unittest.skipUnless(TEM_CIFRA, "falta o pacote cryptography")
class TestCifra(unittest.TestCase):
    def test_ida_e_volta(self):
        cifrado = cifrar(CHAVE, "renovar-0")
        self.assertNotIn("renovar", cifrado)
        self.assertNotEqual(cifrado, cifrar(CHAVE, "renovar-0"))  # cada cifra sai diferente
        self.assertEqual(decifrar(CHAVE, cifrado), "renovar-0")

    def test_chave_errada(self):
        with self.assertRaises(ErroGoogle) as e:
            decifrar("outra", cifrar(CHAVE, "renovar-0"))
        self.assertTrue(e.exception.conta)
        self.assertIn("entre com o Google de novo", str(e.exception))


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


def semear(banco, usuario: int, eventos: list[tuple], lida_em=None, calendario=ANA, nome="Pessoal") -> int:
    """Uma agenda do Google ligada, gravada direto no banco (sem o login): eventos [(titulo, inicio, fim, dia_inteiro,
    ocupado)] em hora local sem fuso. lida_em: a última leitura (padrão: AGORA)."""
    lida_em = (lida_em or AGORA).astimezone()
    with banco.conexao() as con:
        conta = con.execute("INSERT INTO google_contas (usuario, email, token) VALUES (%s, %s, 'cifrado') "
                            "ON CONFLICT (usuario, email) DO UPDATE SET erro = NULL RETURNING id",
                            [usuario, f"pessoa{usuario}@gmail.com"]).fetchone()[0]
        agenda = con.execute(
            "INSERT INTO google_agendas (usuario, conta, calendario, nome, ligada, lida_em, tentativa_em) "
            "VALUES (%s, %s, %s, %s, true, %s, %s) RETURNING id",
            [usuario, conta, calendario, nome, lida_em, lida_em]).fetchone()[0]
        for titulo, inicio, fim, dia_inteiro, ocupado in eventos:
            con.execute("INSERT INTO google_eventos (agenda, titulo, inicio, fim, dia_inteiro, ocupado) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        [agenda, titulo, inicio.astimezone(), fim.astimezone(), dia_inteiro, ocupado])
    return agenda


@unittest.skipUnless(TEM_CIFRA, "falta o pacote cryptography")
class TestGoogleNoBanco(BaseBanco):
    """Ana entra com a conta Google dela; o Google é o falso de self.falso."""

    def setUp(self):
        super().setUp()
        self.ana, self.beto = (self.criar_usuario(n, paginas=GESTAO) for n in ("ana", "beto"))
        self.agora = AGORA
        self.falso = GoogleFalso()
        self.google = GoogleAgenda(self.banco, ini_google(), agora=lambda: self.agora, pedidor=self.falso)
        self.google.pausa = 0

    def entrar(self, usuario: int, email: str = ANA, volta: int | None = None) -> dict:
        """O login inteiro: o endereço do Google, a pessoa autoriza lá e o Google volta ao BI (na sessão de volta)."""
        q = self.falso.login(self.google.endereco_login(usuario), email)
        return self.google.retorno(usuario if volta is None else volta, q)

    def passar(self, minutos: int) -> None:
        self.agora += dt.timedelta(minutes=minutos)

    def conta(self, usuario: int | None = None) -> dict:
        return self.google.listar(usuario or self.ana)["contas"][0]

    def agenda(self, nome: str, usuario: int | None = None) -> dict:
        return next(a for c in self.google.listar(usuario or self.ana)["contas"] for a in c["agendas"]
                    if a["nome"] == nome)

    def linha(self, tabela: str, id_: int, colunas: str) -> tuple:
        with self.banco.conexao() as con:
            return con.execute(f"SELECT {colunas} FROM {tabela} WHERE id = %s", [id_]).fetchone()

    def test_endereco_do_login(self):
        u = urlsplit(self.google.endereco_login(self.ana))
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.assertEqual((u.scheme, u.netloc, u.path), ("https", "accounts.google.com", "/o/oauth2/v2/auth"))
        self.assertEqual((q["client_id"], q["redirect_uri"], q["scope"], q["response_type"], q["access_type"]),
                         (CLIENTE["cliente_id"], RETORNO, ESCOPO, "code", "offline"))
        self.assertIn("consent", q["prompt"])
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertGreater(len(q["state"]), 30)
        self.assertNotIn("segredo", u.query)
        outro = GoogleAgenda(self.banco, ini_google(retorno="https://outro.exemplo/volta"))
        self.assertIn("outro.exemplo", parse_qs(urlsplit(outro.endereco_login(self.ana)).query)["redirect_uri"][0])

    def test_entrar_guarda_a_conta_e_le_a_principal(self):
        r = self.entrar(self.ana)
        self.assertEqual((r["email"], r["nova"]), (ANA, True))
        c = self.conta()
        self.assertEqual((c["email"], c["trocar"], c["atencao"]), (ANA, False, False))
        principal, familia = c["agendas"]
        self.assertEqual((principal["nome"], principal["principal"], principal["ligada"], principal["eventos"]),
                         ("Ana Silva", True, True, 3))
        self.assertEqual((familia["nome"], familia["ligada"], familia["eventos"], familia["lida_em"]),
                         ("Família", False, 0, None))
        guardado = self.linha("google_contas", r["id"], "token")[0]
        self.assertNotIn("renovar", guardado)
        self.assertEqual(decifrar(CHAVE, guardado), "renovar-0")
        m = Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE).mes(self.ana, "2026-10")
        for resposta in (self.google.listar(self.ana), self.google.no_mes(self.ana, m)):
            texto = json.dumps(resposta, default=str)
            self.assertNotIn("renovar", texto)
            self.assertNotIn("acesso|", texto)
        self.assertEqual(self.google.listar(self.beto)["contas"], [])
        self.assertEqual(self.falso.contar(TOKEN), 1)  # a leitura usou o acesso que veio no login

    def test_state_vale_uma_vez_e_so_para_quem_comecou(self):
        q = self.falso.login(self.google.endereco_login(self.ana), ANA)
        with self.assertRaises(ErroGoogle) as e:
            self.google.retorno(self.beto, q)  # o link do login de Ana aberto na sessão de Beto
        self.assertIn("sessão do BI mudou", str(e.exception))
        with self.assertRaises(ErroGoogle) as e:
            self.google.retorno(self.ana, q)  # o state já foi usado
        self.assertIn("venceu ou já foi usado", str(e.exception))
        with self.assertRaises(ErroGoogle):
            self.google.retorno(self.ana, {"code": "codigo-0", "state": "inventado"})
        with mock.patch.object(google_agenda, "PEDIDO_VALE", -1), self.assertRaises(ErroGoogle) as e:
            self.entrar(self.ana)
        self.assertIn("venceu", str(e.exception))
        q = self.falso.login(self.google.endereco_login(self.ana), ANA)
        with self.assertRaises(ErroGoogle) as e:
            self.google.retorno(self.ana, {"state": q["state"], "error": "access_denied"})
        self.assertIn("não autorizou", str(e.exception))
        self.assertEqual((self.contar("google_contas"), self.falso.contar(TOKEN)), (0, 0))

    def test_sem_a_permissao_da_agenda(self):
        self.falso.escopo = "openid"  # a pessoa desmarcou a permissão do Google Agenda
        with self.assertRaises(ErroGoogle) as e:
            self.entrar(self.ana)
        self.assertIn("permissão do Google Agenda", str(e.exception))
        self.assertEqual(self.falso.revogadas, ["renovar-0"])  # o BI larga o que recebeu
        self.assertEqual(self.contar("google_contas"), 0)

    def test_cliente_errado(self):
        errado = GoogleAgenda(self.banco, ini_google(cliente_segredo="outro"), pedidor=self.falso)
        q = self.falso.login(errado.endereco_login(self.ana), ANA)
        with self.assertLogs("bi.google", "ERROR"), self.assertRaises(ErroGoogle) as e:
            errado.retorno(self.ana, q)
        self.assertIn("mal configurado", str(e.exception))

    def test_entrar_de_novo_troca_a_autorizacao(self):
        id_ = self.entrar(self.ana)["id"]
        self.google.ligar(self.ana, self.agenda("Família")["id"], True)
        with self.banco.conexao() as con:
            con.execute("UPDATE google_contas SET erro = 'caiu', trocar = true WHERE id = %s", [id_])
        r = self.entrar(self.ana)
        self.assertEqual((r["id"], r["nova"]), (id_, False))
        token, erro, trocar = self.linha("google_contas", id_, "token, erro, trocar")
        self.assertEqual((decifrar(CHAVE, token), erro, trocar), ("renovar-1", None, False))
        self.assertTrue(self.agenda("Família")["ligada"])  # o que a pessoa ligou continua ligado
        self.assertEqual(self.contar("google_agendas"), 2)

    def test_limite_de_contas(self):
        for n in range(google_agenda.MAX_CONTAS):
            email = f"conta{n}@gmail.com"
            self.falso.contas[email] = [(email, email, True)]
            self.entrar(self.ana, email)
        with self.assertRaises(ValueError) as e:
            self.entrar(self.ana)
        self.assertIn("até 3 contas", str(e.exception))
        self.assertEqual(self.falso.revogadas, ["renovar-3"])
        self.assertEqual(self.contar("google_contas"), 3)

    def test_ligar_e_desligar(self):
        self.entrar(self.ana)
        familia = self.agenda("Família")["id"]
        with self.assertRaises(NaoEncontrada):
            self.google.ligar(self.beto, familia, True)
        self.google.ligar(self.ana, familia, True)  # lê na hora
        a = self.agenda("Família")
        self.assertEqual((a["ligada"], a["eventos"], a["lida_em"] is not None), (True, 1, True))
        m = self.google.no_mes(self.ana, Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE).mes(self.ana,
                                                                                                     "2026-11"))
        self.assertEqual([g["titulo"] for g in m["dias"][0]["google"]], ["Almoço"])
        self.google.ligar(self.ana, familia, False)
        a = self.agenda("Família")
        self.assertEqual((a["ligada"], a["eventos"], a["lida_em"]), (False, 0, None))
        with mock.patch.object(google_agenda, "MAX_AGENDAS", 1), self.assertRaises(ValueError) as e:
            self.google.ligar(self.ana, familia, True)
        self.assertIn("até 1 agendas", str(e.exception))

    def test_a_mesma_agenda_por_duas_contas(self):
        self.falso.contas["trabalho@gmail.com"] = [("trabalho@gmail.com", "Trabalho", True), (FAMILIA, "Família", False)]
        self.entrar(self.ana)
        self.entrar(self.ana, "trabalho@gmail.com")
        primeira, segunda = (c["agendas"][1]["id"] for c in self.google.listar(self.ana)["contas"])
        self.google.ligar(self.ana, primeira, True)
        with self.assertRaises(ValueError) as e:
            self.google.ligar(self.ana, segunda, True)
        self.assertIn(f"pela conta {ANA}", str(e.exception))

    def test_ler_regrava_so_quando_muda(self):
        self.entrar(self.ana)
        principal = self.agenda("Ana Silva")["id"]
        self.assertFalse(self.google.ler(principal))  # acabou de ler: não é a vez
        self.passar(11)
        self.falso.eventos[ANA] = [CONSULTA]
        self.assertTrue(self.google.ler(principal))
        self.assertEqual(self.contar("google_eventos"), 1)
        with self.banco.conexao() as con:
            antes = con.execute("SELECT ctid FROM google_eventos").fetchall()
        self.passar(11)
        self.assertTrue(self.google.ler(principal))  # os mesmos eventos: só a leitura é anotada
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT ctid FROM google_eventos").fetchall(), antes)
        self.assertEqual(self.linha("google_agendas", principal, "lida_em")[0], self.agora.astimezone())
        self.assertEqual(self.falso.contar(TOKEN), 1)  # o acesso do login ainda valia

    def test_paginas_e_teto(self):
        self.falso.pagina = 2
        self.falso.eventos[ANA] = [evento(f"E{n}", local(2026, 11, n, 9), local(2026, 11, n, 10)) for n in range(1, 6)]
        self.entrar(self.ana)
        self.assertEqual(self.agenda("Ana Silva")["eventos"], 5)
        self.passar(11)
        with mock.patch.object(google_agenda, "MAX_OCORRENCIAS", 3), self.assertLogs("bi.google", "WARNING"):
            self.google.rodada()
        a = self.agenda("Ana Silva")
        self.assertIn("mais de 3 eventos", a["erro"])
        self.assertEqual(a["eventos"], 5)  # a falha não apaga a última leitura

    def test_autorizacao_caiu(self):
        """Ana tirou o BI dos apps com acesso, no Google: a conta para de ser lida até ela entrar de novo."""
        self.entrar(self.ana)
        self.falso.validas.clear()
        self.passar(11)
        with self.assertLogs("bi.google", "WARNING") as logs:
            self.assertEqual(self.google.rodada(), 1)
        self.assertFalse(any("renovar" in linha for linha in logs.output))
        c = self.conta()
        self.assertEqual((c["trocar"], c["atencao"]), (True, True))
        self.assertIn("entre com o Google de novo", c["erro"])
        self.assertEqual(self.agenda("Ana Silva")["eventos"], 3)  # os eventos ficam (e param de travar em 24 h)
        self.passar(180)
        self.assertEqual(self.google.rodada(), 0)
        self.entrar(self.ana)
        c = self.conta()
        self.assertEqual((c["trocar"], c["erro"]), (False, None))
        self.assertEqual(self.agenda("Ana Silva")["lida_em"][:16], self.agora.isoformat()[:16])

    def test_a_chave_do_servidor_mudou(self):
        self.entrar(self.ana)
        outra = GoogleAgenda(self.banco, ini_google(chave="nova"), agora=lambda: self.agora, pedidor=self.falso)
        self.passar(11)
        with self.assertLogs("bi.google", "WARNING"):
            outra.rodada()
        self.assertTrue(outra.listar(self.ana)["contas"][0]["trocar"])

    def test_agenda_saiu_da_conta(self):
        self.entrar(self.ana)
        self.google.ligar(self.ana, self.agenda("Família")["id"], True)
        self.falso.contas[ANA] = self.falso.contas[ANA][:1]  # Ana saiu da agenda da família no Google
        self.passar(11)
        with self.assertLogs("bi.google", "WARNING"):
            self.google.rodada()
        a = self.agenda("Família")
        self.assertEqual((a["trocar"], a["atencao"]), (True, True))
        self.assertIn("não está mais na sua conta Google", a["erro"])
        self.passar(2)
        self.google.atualizar(self.ana)  # relê a lista: a agenda some do BI
        self.assertEqual([a["nome"] for a in self.conta()["agendas"]], ["Ana Silva"])

    def test_erro_passageiro_so_avisa_depois_de_uma_hora(self):
        self.entrar(self.ana)
        self.falso.falha[ANA] = (503, {})
        self.passar(11)
        with self.assertLogs("bi.google", "WARNING"):
            self.google.rodada()
        a = self.agenda("Ana Silva")
        self.assertEqual((a["atencao"], a["trocar"], a["eventos"]), (False, False, 3))
        self.passar(60)
        with self.assertLogs("bi.google", "WARNING"):
            self.google.rodada()
        self.assertTrue(self.agenda("Ana Silva")["atencao"])

    def test_leitura_atrasada_nao_grava_por_cima(self):
        """Ana entrou de novo (ou desligou a agenda) enquanto o vigia lia."""
        id_ = self.entrar(self.ana)["id"]

        def no_meio():
            with self.banco.conexao() as con:
                con.execute("UPDATE google_contas SET token = %s WHERE id = %s", [cifrar(CHAVE, "renovar-0"), id_])

        self.falso.eventos[ANA] = [CONSULTA]
        self.falso.ao_ler = no_meio
        self.passar(11)
        self.assertEqual(self.google.rodada(), 1)
        self.assertEqual(self.contar("google_eventos"), 3)
        self.assertEqual(self.agenda("Ana Silva")["lida_em"][:16], AGORA.isoformat()[:16])

    def test_atualizar_agora_e_desconectar(self):
        id_ = self.entrar(self.ana)["id"]
        with self.assertRaises(ValueError) as e:
            self.google.atualizar(self.ana)
        self.assertIn("acabou de ser lida", str(e.exception))
        self.falso.contas[ANA].append(("novo@group.calendar.google.com", "Nova", False))
        self.passar(2)
        self.assertEqual(self.google.atualizar(self.ana, id_), 1)
        self.assertIn("Nova", [a["nome"] for a in self.conta()["agendas"]])  # a agenda criada depois no Google
        with self.assertRaises(NaoEncontrada):
            self.google.atualizar(self.beto, id_)
        with self.assertRaises(NaoEncontrada):
            self.google.desconectar(self.beto, id_)
        self.google.desconectar(self.ana, id_)
        self.assertEqual([self.contar(t) for t in ("google_contas", "google_agendas", "google_eventos")], [0, 0, 0])
        self.assertEqual(self.falso.revogadas, ["renovar-0"])

    def test_rodada(self):
        self.entrar(self.ana)
        self.entrar(self.beto, "beto@gmail.com")
        self.assertEqual(self.google.rodada(), 0)  # as duas acabaram de ser lidas
        self.passar(10)
        self.assertEqual(self.google.rodada(), 2)
        with self.banco.conexao() as con:  # Beto saiu da Gestão; a de Ana falhou duas vezes seguidas
            con.execute("UPDATE usuarios SET paginas = '{metas}' WHERE id = %s", [self.beto])
            con.execute("UPDATE google_agendas SET falhas = 2 WHERE usuario = %s", [self.ana])
        self.passar(10)
        self.assertEqual(self.google.rodada(), 0)  # Ana espera 40 min; Beto não é mais lido
        self.passar(30)
        self.assertEqual(self.google.rodada(), 1)

    def test_sem_a_chave_ou_sem_o_cliente(self):
        for campos, aviso in (({"chave": ""}, SITE), ({"cliente_segredo": ""}, SEM_CLIENTE)):
            sem = GoogleAgenda(self.banco, ini_google(**campos), pedidor=self.falso)
            self.assertEqual(sem.listar(self.ana), {"ativo": False, "aviso": aviso, "contas": []})
            with self.assertRaises(ValueError) as e:
                sem.endereco_login(self.ana)
            self.assertEqual(str(e.exception), aviso)
        semear(self.banco, self.ana, [("Consulta", DT(2026, 10, 30, 14), DT(2026, 10, 30, 15), False, True)])
        m = sem.no_mes(self.ana, Agenda(self.banco, ConfiguracaoFixa(), hoje=lambda: HOJE).mes(self.ana, "2026-10"))
        self.assertFalse(m["google"]["ativo"])
        self.assertTrue(all(d["google"] == [] for d in m["dias"]))
        with self.banco.conexao() as con:
            self.assertEqual(sem.ocupados(con, [self.ana], HOJE, D(2026, 11, 30)), [])
        self.assertEqual(self.falso.pedidos, [])

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
        self.assertTrue(m["google"]["contas"][0]["agendas"][0]["desatualizada"])


class TestHorarioOcupadoGoogle(BaseBanco):
    """Hoje é 26/10/2026. Ana tem no Google: Consulta médica 30/10 14:00–15:00 (ocupado), Café 30/10 16:00–17:00
    (disponível) e Férias de 10 a 14/11 (dia inteiro, ocupado). Beto cria as tarefas."""

    def setUp(self):
        super().setUp()
        self.ana, self.beto = (self.criar_usuario(n, paginas=GESTAO) for n in ("ana", "beto"))
        self.google = GoogleAgenda(self.banco, ini_google(), agora=lambda: AGORA)
        self.google.falta = []  # os eventos vêm semeados: não precisa do pacote cryptography
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

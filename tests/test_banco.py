"""O que veio dos arquivos para o PostgreSQL: a importação na migração 005, as conversas por usuário na 006, as
versões das regras (bi/configuracao.py) e o registro de uso do Assistente (bi/uso.py). Precisam de
BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from bi.acesso import Usuarios, gerar_hash
from bi.banco import MIGRACOES, BancoNaoPreparado, inicio_do_dia
from bi.configuracao import Configuracao, padrao
from bi.conversas import Conversas
from bi.projecoes import ConfigProjecoes
from bi.uso import RegistroUso
from tests.apoio import BaseBanco

ONTEM = (dt.datetime.now() - dt.timedelta(days=1)).isoformat(timespec="seconds")


def registro(usuario, login, custo=0.01, **extra) -> dict:
    """No formato que o Assistente monta (bi/assistente.py, Assistente._responder)."""
    return {"usuario": usuario, "login": login, "nome": login.title(), "conversa": None, "escopo": "todos os vendedores",
            "pergunta": "quanto vendemos?", "resposta": "R$ 10,00.", "aviso": None, "erro": None, "parada": "end_turn",
            "uso": {"entrada": 1000, "saida": 100, "cache_leitura": 0, "cache_escrita": 0, "chamadas": 1,
                    "custo": custo, "modelo": "claude-opus-5-5", "segundos": 3.2},
            "passos": [{"ferramenta": "resumo_vendas", "args": {"de": "2026-10-01"}, "sql": None, "linhas": 3,
                        "ms": 12, "erro": None}],
            "data_ref": "2026-10-15", "pedidos_api": ["req_1", None], **extra}


class TestImportacao(BaseBanco):
    """Primeira subida com o banco: os arquivos da pasta do painel viram linhas, e os arquivos ficam lá."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    def escrever(self, nome: str, conteudo) -> Path:
        caminho = self.raiz / nome
        caminho.parent.mkdir(parents=True, exist_ok=True)
        texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo, ensure_ascii=False)
        caminho.write_text(texto, encoding="utf-8")
        return caminho

    def arquivos_antigos(self):
        senha = gerar_hash("segredo1")
        self.escrever("usuarios.json", {"versao": 1, "segredo": "ab" * 32, "usuarios": {
            "admin": {"nome": "Administrador", "papel": "admin", "ativo": True, "visoes": None, "vendedores": None,
                      "senha": senha, "sessao": 3, "criado_em": "2026-10-15T14:21:38", "ultimo_acesso": None},
            # de antes da escolha de páginas: vê Metas
            "supervisor.es": {"nome": "Supervisor ES", "papel": "visualizador", "ativo": True, "visoes": ["es"],
                              "vendedores": [124, 141], "senha": senha, "sessao": 0,
                              "criado_em": "2026-10-15T14:24:43", "ultimo_acesso": "2026-10-16T09:00:00"},
            "bia": {"nome": "Bia", "papel": "visualizador", "ativo": False, "visoes": [], "vendedores": None,
                    "paginas": ["projecoes", "assistente"], "projecoes": {"modo": "todos", "vendedores": None},
                    "assistente": {"modo": "alguns", "vendedores": [85]}, "senha": senha, "sessao": 1,
                    "criado_em": "2026-10-15T15:00:00", "ultimo_acesso": None},
        }})
        anterior = padrao()
        self.escrever("config_metas.anterior.json", anterior)
        atual = padrao()
        atual["devolucoes"]["motivos"] = [1, 2]
        self.escrever("config_metas.json", atual)
        os.utime(self.raiz / "config_metas.anterior.json", (time.time() - 3600,) * 2)
        self.escrever("config_projecoes.json", {"versao": 1, "incluir": [7], "excluir": [2, 4]})
        linhas = [json.dumps({**registro(None, "supervisor.es", custo=0.12), "quando": ONTEM}),
                  "isto não é json",
                  json.dumps({**registro(None, "quem.saiu", custo=0.5), "quando": "2026-10-01T10:00:00"})]
        self.escrever("logs/assistente-2026-10.jsonl", "\n".join(linhas) + "\n")
        return atual

    def test_importa_tudo_uma_vez(self):
        atual = self.arquivos_antigos()
        usuarios = Usuarios(self.banco)
        self.assertEqual([u["login"] for u in usuarios.listar()], ["admin", "bia", "supervisor.es"])
        sup, bia, admin = usuarios.obter("supervisor.es"), usuarios.obter("bia"), usuarios.obter("admin")
        self.assertEqual((sup["paginas"], sup["visoes"], sup["vendedores"]), (["metas"], ["es"], [124, 141]))
        self.assertEqual((sup["criado_em"], sup["ultimo_acesso"]), ("2026-10-15T14:24:43", "2026-10-16T09:00:00"))
        self.assertEqual(bia["paginas"], ["projecoes", "assistente"])
        self.assertEqual((bia["projecoes"], bia["assistente"]), ({"modo": "todos", "vendedores": None},
                                                                 {"modo": "alguns", "vendedores": [85]}))
        self.assertFalse(bia["ativo"])
        self.assertIsNone(admin["paginas"])
        self.assertIsNotNone(usuarios.autenticar("supervisor.es", "segredo1"))  # a senha veio junto
        self.assertNotEqual(usuarios._segredo().hex(), "ab" * 32)  # o segredo das sessões é novo
        with self.banco.conexao() as con:
            versoes = con.execute("SELECT nome, salva_por_nome FROM regras ORDER BY id").fetchall()
        self.assertEqual(versoes, [("metas", "importado de config_metas.anterior.json"),
                                   ("metas", "importado de config_metas.json"),
                                   ("projecoes", "importado de config_projecoes.json")])
        self.assertEqual(Configuracao(self.banco).atual(), atual)
        self.assertEqual(ConfigProjecoes(self.banco).atual(), {"versao": 1, "incluir": [7], "excluir": [2, 4]})
        # perguntas: a linha estragada fica de fora; quem saiu fica sem o vínculo
        self.assertEqual(self.contar("assistente_perguntas"), 2)
        self.assertEqual(self.contar("assistente_perguntas", "usuario IS NULL"), 1)
        por_usuario = {p["login"]: p for p in RegistroUso(self.banco).resumo(30)["por_usuario"]}
        self.assertEqual((por_usuario["supervisor.es"]["ultima"], por_usuario["supervisor.es"]["custo"]), (ONTEM, 0.12))
        # os arquivos ficam onde estavam, e a importação não roda de novo
        self.assertTrue((self.raiz / "usuarios.json").exists())
        outro = self.novo_banco(self.raiz)
        try:
            self.assertEqual(outro.migrar(), [])
        finally:
            outro.fechar()

    def test_sem_arquivos_comeca_vazio(self):
        self.assertTrue(Usuarios(self.banco).vazio())
        self.assertEqual(Configuracao(self.banco).atual(), padrao())
        self.assertEqual(self.contar("regras"), 0)

    def test_regras_que_nao_conferem_param_a_migracao(self):
        self.escrever("config_projecoes.json", {"incluir": [1], "excluir": [1]})
        with self.assertRaises(BancoNaoPreparado) as e, self.assertLogs("bi.banco", "ERROR"):
            Usuarios(self.banco).vazio()
        self.assertIn("logs/bi.log", e.exception.aviso)
        with self.assertRaises(BancoNaoPreparado):  # não tenta de novo a cada pedido
            Usuarios(self.banco).vazio()
        with self.banco._conexao() as con:  # tudo voltou atrás, até o schema
            self.assertIsNone(con.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", [self.schema]).fetchone())

    def contar_sem_migrar(self, tabela: str) -> int:
        with self.banco._conexao() as con:
            return con.execute(f'SELECT count(*) FROM "{self.schema}".{tabela}').fetchone()[0]

    # --- 006: as conversas de antes, com o login em texto -----------------------------------
    def banco_so_com_conversas(self):
        """O banco como ficou depois do commit 74c0325: só a migração 001, com conversas de dois logins."""
        with self.banco._conexao() as con:
            con.execute(f'CREATE SCHEMA "{self.schema}"')
            con.execute("CREATE TABLE migracoes (versao text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now())")
            con.execute((MIGRACOES / "001_conversas.sql").read_text(encoding="utf-8"))
            con.execute("INSERT INTO migracoes (versao) VALUES ('001_conversas')")
            for login in ("supervisor.es", "quem.saiu"):
                id_ = uuid.uuid4()
                con.execute("INSERT INTO conversas (id, login, titulo) VALUES (%s, %s, 'x')", [id_, login])
                con.execute("INSERT INTO mensagens (conversa, papel, texto) VALUES (%s, 'usuario', 'x')", [id_])

    def test_conversas_passam_para_o_usuario(self):
        self.arquivos_antigos()
        self.banco_so_com_conversas()
        with self.assertLogs("bi.banco", "WARNING") as logs:
            self.banco.migrar()
        self.assertTrue(any("1 conversas de logins que não existem mais" in m for m in logs.output))
        sup = Usuarios(self.banco).obter("supervisor.es")
        self.assertEqual(len(Conversas(self.banco).listar(sup["id"])), 1)
        self.assertEqual((self.contar("conversas"), self.contar("mensagens")), (1, 1))

    def test_conversas_sem_usuarios_nao_sao_apagadas(self):
        self.banco_so_com_conversas()  # e sem o usuarios.json na pasta
        with self.assertRaises(Exception) as e:
            self.banco.migrar()
        self.assertIn("nenhum usuário foi importado", str(e.exception))
        self.assertEqual(self.contar_sem_migrar("conversas"), 2)
        self.assertEqual(self.contar_sem_migrar("migracoes"), 1)


class TestRegras(BaseBanco):
    def setUp(self):
        super().setUp()
        self.chefe = self.criar_usuario("chefe", "admin")
        self.cfg = Configuracao(self.banco)

    def test_versoes_com_autor(self):
        self.assertEqual(self.cfg.atual(), padrao())
        novo = padrao()
        novo["calendario"]["sabado"]["ES"] = 0.5
        salvo = self.cfg.salvar(novo, {"id": self.chefe, "nome": "Chefe"})
        self.assertEqual(salvo["calendario"]["sabado"]["ES"], 0.5)
        self.assertEqual(self.cfg.atual()["calendario"]["sabado"]["ES"], 0.5)
        self.cfg.restaurar_padrao({"id": self.chefe, "nome": "Chefe"})
        self.assertEqual(self.cfg.atual(), padrao())
        with self.banco.conexao() as con:
            con.execute("DELETE FROM usuarios WHERE id = %s", [self.chefe])
            linhas = con.execute("SELECT salva_por, salva_por_nome FROM regras ORDER BY id").fetchall()
        self.assertEqual(linhas, [(None, "Chefe"), (None, "Chefe")])  # quem salvou continua escrito
        # outro painel (ou depois de reiniciar) lê a versão mais recente
        self.assertEqual(Configuracao(self.banco).atual(), padrao())

    def test_invalida_nao_grava(self):
        novo = padrao()
        novo["calendario"]["sabado"]["ES"] = 2
        with self.assertRaises(ValueError):
            self.cfg.salvar(novo)
        self.assertEqual(self.contar("regras"), 0)
        with self.assertRaises(ValueError):
            ConfigProjecoes(self.banco).salvar({"incluir": [1], "excluir": [1]})

    def test_regras_e_acessos_numa_transacao(self):
        """Como a configuração da página salva (app.py, _salvar_config_metas): ou grava as duas partes, ou nada."""
        usuarios = Usuarios(self.banco)
        novo = padrao()
        novo["devolucoes"]["motivos"] = [1]
        with self.assertRaises(ValueError):
            with self.banco.conexao() as con:
                versao = self.cfg.gravar(novo, None, con)
                usuarios.definir_metas({"ninguem": {"visoes": ["es"]}}, con)
        self.assertEqual(self.contar("regras"), 0)
        self.assertEqual(self.cfg.atual(), padrao())  # a memória não mudou
        with self.banco.conexao() as con:
            versao = self.cfg.gravar(novo, None, con)
        self.cfg.usar(*versao)
        self.cfg.usar(versao[0] - 1, padrao())  # uma versão mais velha que chegou atrasada não volta
        self.assertEqual(self.cfg.atual()["devolucoes"]["motivos"], [1])


class TestRegistroUso(BaseBanco):
    def setUp(self):
        super().setUp()
        self.ana = self.criar_usuario("ana")
        self.bia = self.criar_usuario("bia")
        self.r = RegistroUso(self.banco)

    def test_limites_do_dia_e_resumo(self):
        conversa = str(uuid.uuid4())
        self.r.gravar(registro(self.ana, "ana", 0.10, conversa=conversa))
        self.r.gravar(registro(self.ana, "ana", 0.20, erro="RuntimeError: a API caiu"))
        self.r.gravar(registro(self.bia, "bia", 0.05))
        with self.banco.conexao() as con:  # uma de ontem: conta no resumo, não nos limites de hoje
            con.execute("UPDATE assistente_perguntas SET quando = %s WHERE login = 'bia'",
                        [inicio_do_dia(dt.date.today()) - dt.timedelta(minutes=1)])
        n, custo = self.r.do_dia(self.ana)
        self.assertEqual(n, 2)
        self.assertAlmostEqual(custo, 0.30)
        self.assertEqual(self.r.do_dia(self.bia)[0], 0)
        resumo = self.r.resumo(30)
        json.dumps(resumo)  # vai direto para a página: nada de Decimal nem datetime
        self.assertEqual(resumo["hoje"], {"perguntas": 2, "custo": 0.3})
        self.assertEqual([(p["login"], p["perguntas"], p["custo"]) for p in resumo["por_usuario"]],
                         [("ana", 2, 0.3), ("bia", 1, 0.05)])
        ultima = resumo["ultimas"][0]
        self.assertEqual((ultima["login"], ultima["erro"], ultima["passos"], ultima["custo"]),
                         ("ana", "RuntimeError: a API caiu", 1, 0.2))
        self.assertNotIn("+", ultima["quando"])
        with self.banco.conexao() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM assistente_perguntas WHERE conversa = %s",
                                         [conversa]).fetchone()[0], 1)

    def test_usuario_excluido_no_meio_da_pergunta(self):
        with self.banco.conexao() as con:
            con.execute("DELETE FROM usuarios WHERE id = %s", [self.ana])
        self.r.gravar(registro(self.ana, "ana"))
        self.assertEqual(self.contar("assistente_perguntas", "usuario IS NULL AND login = 'ana'"), 1)

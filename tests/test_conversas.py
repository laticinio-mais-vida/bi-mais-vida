"""Histórico de conversas no PostgreSQL (bi/banco.py e bi/conversas.py). Os testes com o banco precisam de
BI_TESTE_POSTGRES (veja tests/apoio.py); sem ele, são pulados."""
from __future__ import annotations

import configparser
import time
import unittest
import uuid

from bi.banco import Banco, BancoForaDoAr, BancoNaoPreparado
from bi.conversas import Conversas, NaoEncontrada, titulo_de
from tests.apoio import TEM_PSYCOPG, BaseBanco

MIGRACOES = ["001_conversas", "002_usuarios", "003_regras", "004_assistente_perguntas", "005_importar_arquivos",
             "006_conversas_por_usuario", "007_gestao", "008_indicadores", "009_gestao_equipe",
             "010_efetividade_media_diaria", "011_efetividade_pedido_fora_da_previsao", "012_base_periodo",
             "013_preco_medio_aumento", "014_efetividade_visita_de_quem_compra", "015_meta_propria_preco"]


def resposta(texto: str, consultas: str = "") -> dict:
    return {"texto": texto, "consultas": consultas, "passos": [{"ferramenta": "resumo_vendas", "linhas": 3}],
            "data_ref": "2026-10-15", "aviso": None, "uso": {"segundos": 4.2}}


class TestTitulo(unittest.TestCase):
    def test_titulo(self):
        self.assertEqual(titulo_de("  Quanto   vendemos\neste mês?"), "Quanto vendemos")
        self.assertEqual(titulo_de("\n\n  "), "Nova conversa")
        longo = titulo_de("Quais clientes compraram no mês passado e ainda não compraram este mês, por vendedor?")
        self.assertEqual(longo, "Quais clientes compraram no mês passado e ainda não…")
        self.assertLessEqual(len(longo), 61)
        self.assertEqual(titulo_de("x" * 100), "x" * 60 + "…")


class TestForaDoAr(unittest.TestCase):
    @unittest.skipUnless(TEM_PSYCOPG, "sem o pacote psycopg")
    def test_banco_que_nao_responde(self):
        ini = configparser.ConfigParser()
        ini.read_dict({"postgres": {"host": "127.0.0.1", "porta": "9"}})  # porta fechada
        banco = Banco(ini)
        try:
            inicio = time.time()
            with self.assertRaises(BancoForaDoAr):
                Conversas(banco).listar(1)
            self.assertLess(time.time() - inicio, 15)
            banco.iniciar()  # na subida do painel só avisa, não derruba
        finally:
            banco.fechar()

    def test_sem_host_nao_esta_configurado(self):
        banco = Banco(configparser.ConfigParser())
        self.assertFalse(banco.configurado)
        with self.assertRaises(BancoNaoPreparado) as e:
            Conversas(banco).listar(1)
        self.assertIn("[postgres]", e.exception.aviso)
        with self.assertLogs("bi.banco", "ERROR"):
            banco.iniciar()  # só avisa


class TestConversas(BaseBanco):
    def setUp(self):
        super().setUp()
        self.c = Conversas(self.banco)
        self.ana = self.criar_usuario("ana")
        self.bia = self.criar_usuario("bia")

    def nova(self, usuario=None, pergunta="Quanto vendemos este mês?", texto="R$ 10.000,00.", consultas="") -> str:
        id_ = str(uuid.uuid4())
        self.c.acrescentar(usuario or self.ana, id_, pergunta, resposta(texto, consultas))
        return id_

    def test_migracoes_uma_vez_so(self):
        banco = self.novo_banco()  # outro painel no mesmo banco: nada a aplicar
        try:
            self.assertEqual(banco.migrar(), [])
        finally:
            banco.fechar()
        with self.banco.conexao() as con:
            self.assertEqual([r[0] for r in con.execute("SELECT versao FROM migracoes ORDER BY versao")], MIGRACOES)
        self.banco.iniciar()

    def test_acrescentar_obter_e_historico(self):
        id_ = self.nova(pergunta="Quais os 10 clientes que mais compraram no mês passado, por faturamento líquido?",
                        consultas='resumo_vendas{"de":"2026-09-01"}')
        meta = self.c.acrescentar(self.ana, id_, "e em agosto?", resposta("Em agosto, R$ 8.000,00."))
        self.assertEqual(meta["id"], id_)
        self.assertEqual(meta["titulo"], "Quais os 10 clientes que mais compraram no mês passado, por…")
        conversa = self.c.obter(self.ana, id_)
        self.assertEqual([m["papel"] for m in conversa["mensagens"]], ["usuario", "assistente"] * 2)
        ia = conversa["mensagens"][1]
        self.assertEqual(ia["texto"], "R$ 10.000,00.")
        self.assertEqual(ia["passos"], [{"ferramenta": "resumo_vendas", "linhas": 3}])
        self.assertEqual((ia["data_ref"], ia["uso"]), ("2026-10-15", {"segundos": 4.2}))
        self.assertEqual(self.c.historico(self.ana, id_), [
            {"papel": "usuario", "texto": "Quais os 10 clientes que mais compraram no mês passado, por faturamento líquido?"},
            {"papel": "assistente", "texto": "R$ 10.000,00.", "consultas": 'resumo_vendas{"de":"2026-09-01"}'},
            {"papel": "usuario", "texto": "e em agosto?"},
            {"papel": "assistente", "texto": "Em agosto, R$ 8.000,00."},
        ])

    def test_cada_pessoa_ve_so_as_suas(self):
        id_ = self.nova(self.ana)
        self.assertEqual([c["id"] for c in self.c.listar(self.ana)], [id_])
        self.assertEqual(self.c.listar(self.bia), [])
        self.assertIsNone(self.c.obter(self.bia, id_))
        self.assertIsNone(self.c.historico(self.bia, id_))
        with self.assertRaises(NaoEncontrada):
            self.c.renomear(self.bia, id_, "minha")
        with self.assertRaises(NaoEncontrada):
            self.c.excluir(self.bia, id_)
        with self.assertRaises(NaoEncontrada):
            self.c.acrescentar(self.bia, id_, "e agora?", resposta("ok"))
        self.assertEqual(len(self.c.obter(self.ana, id_)["mensagens"]), 2)

    def test_arquivo_e_rascunho_so_do_dono(self):
        id_ = str(uuid.uuid4())
        arquivo = {"id": str(uuid.uuid4()), "formato": "excel", "titulo": "Clientes", "sql": "SELECT 1", "linhas": 1}
        rascunho = {"id": str(uuid.uuid4()), "nome": "Mix"}
        self.c.acrescentar(self.ana, id_, "manda em excel", {**resposta("O arquivo traz 1 linha."),
                                                             "arquivos": [arquivo], "rascunhos": [rascunho]})
        self.assertEqual(self.c.arquivo(self.ana, arquivo["id"]), (arquivo, "O arquivo traz 1 linha."))
        self.assertEqual(self.c.rascunho(self.ana, rascunho["id"]), rascunho)
        self.assertEqual(self.c.obter(self.ana, id_)["mensagens"][1]["arquivos"], [arquivo])
        for usuario, procurado in ((self.bia, arquivo["id"]), (self.ana, rascunho["id"]), (self.ana, "abc"),
                                   (self.ana, str(uuid.uuid4()))):
            self.assertIsNone(self.c.arquivo(usuario, procurado))
        self.assertIsNone(self.c.rascunho(self.bia, rascunho["id"]))
        self.assertIsNone(self.c.rascunho(self.ana, arquivo["id"]))

    def test_ids_invalidos(self):
        for id_ in ("", None, "abc", "1; DROP TABLE conversas"):
            self.assertIsNone(self.c.obter(self.ana, id_))
            self.assertIsNone(self.c.historico(self.ana, id_))
            with self.assertRaises(NaoEncontrada):
                self.c.excluir(self.ana, id_)

    def test_ordem_e_busca(self):
        primeira = self.nova(pergunta="Vendas de Açaí em setembro", texto="R$ 1.000,00.")
        segunda = self.nova(pergunta="Metas do mês", texto="A produção ficou em 50% da meta.")
        self.assertEqual([c["id"] for c in self.c.listar(self.ana)], [segunda, primeira])
        self.c.acrescentar(self.ana, primeira, "e em outubro?", resposta("R$ 2.000,00."))  # sobe para o topo
        self.assertEqual([c["id"] for c in self.c.listar(self.ana)], [primeira, segunda])
        self.assertEqual([c["id"] for c in self.c.listar(self.ana, "acai")], [primeira])        # no título, sem acento
        self.assertEqual([c["id"] for c in self.c.listar(self.ana, "PRODUÇAO")], [segunda])   # nas mensagens
        self.assertEqual([c["id"] for c in self.c.listar(self.ana, "50%")], [segunda])
        self.assertEqual([c["id"] for c in self.c.listar(self.ana, "%")], [segunda])  # % e _ são procurados como texto
        self.assertEqual(self.c.listar(self.ana, "_"), [])
        self.assertEqual(self.c.listar(self.bia, "acai"), [])

    def test_renomear(self):
        id_ = self.nova()
        antes = self.c.listar(self.ana)[0]
        meta = self.c.renomear(self.ana, id_, "  Vendas   do mês ")
        self.assertEqual(meta["titulo"], "Vendas do mês")
        self.assertEqual(meta["atualizada_em"], antes["atualizada_em"])  # renomear não muda a ordem
        for titulo in ("", "   ", "x" * 81):
            with self.assertRaises(ValueError):
                self.c.renomear(self.ana, id_, titulo)
        with self.assertRaises(NaoEncontrada):
            self.c.renomear(self.ana, str(uuid.uuid4()), "outra")

    def test_excluir_apaga_as_mensagens(self):
        id_ = self.nova()
        outra = self.nova()
        self.c.excluir(self.ana, id_)
        self.assertEqual([c["id"] for c in self.c.listar(self.ana)], [outra])
        self.assertEqual(self.contar("mensagens"), 2)
        with self.assertRaises(NaoEncontrada):
            self.c.excluir(self.ana, id_)

    def test_seguem_o_usuario(self):
        """Trocar o login não muda nada; excluir o usuário apaga as conversas e as mensagens dele."""
        id_ = self.nova(self.ana)
        self.nova(self.bia)
        with self.banco.conexao() as con:
            con.execute("UPDATE usuarios SET login = 'ana.paula' WHERE id = %s", [self.ana])
        self.assertEqual([c["id"] for c in self.c.listar(self.ana)], [id_])
        with self.banco.conexao() as con:
            con.execute("DELETE FROM usuarios WHERE id = %s", [self.ana])
        self.assertEqual(self.contar("conversas"), 1)
        self.assertEqual(self.contar("mensagens"), 2)
        # Excluído enquanto a pergunta era respondida: a resposta não vira conversa de ninguém.
        with self.assertRaises(NaoEncontrada):
            self.c.acrescentar(self.ana, str(uuid.uuid4()), "x", resposta("y"))
        self.assertEqual(len(self.c.listar(self.bia)), 1)


if __name__ == "__main__":
    unittest.main()

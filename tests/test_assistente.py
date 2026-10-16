"""Assistente: recorte por acesso, ferramentas, travas do SQL e o laço com a API (cliente falso).

Rodar na raiz do projeto: python -m unittest discover -s tests
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from bi.assistente import ErroAssistente, Ferramentas
from tests.apoio import (BA, EDIR, ES, USUARIO_ADMIN, USUARIO_VIS, ClienteFalso, bloco_ferramenta, bloco_pensamento,
                         bloco_texto, criar_assistente, criar_calc, resposta)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.calc = criar_calc(self.pasta, fora=(999,))

    def tearDown(self):
        self.calc.cache._con.close()
        self._tmp.cleanup()

    def ferramentas(self, ids=None, equipes=None, **ia):
        a = criar_assistente(self.pasta, self.calc, **ia)
        return Ferramentas(a.recorte(ids), self.calc, a.cfg, equipes), a


class TestRecorte(Base):
    def test_faturamento_igual_ao_das_metas(self):
        f, _ = self.ferramentas()
        regras = self.calc.regras()
        mov, _ = self.calc._movimento(regras, [ES, BA, EDIR], [dt.date(2026, 9, 1)])
        esperado = sum(v for por_p in mov.values() for pid, (v, _q) in por_p.items() if regras.grupo_produto(pid) != "fora")
        total = f.cur.execute("SELECT SUM(valor_liquido) FROM faturamento WHERE ano = 2026 AND mes = 9").fetchone()[0]
        self.assertAlmostEqual(total, esperado, places=6)
        # 1000+300+200+80 + 5000+700 (sem o produto fora) − 100 (motivo 1) − 250 (motivo 2, não cancelada)
        self.assertAlmostEqual(total, 6930.0, places=6)

    def test_regras_aplicadas(self):
        f, _ = self.ferramentas()
        c = f.cur
        self.assertEqual(c.execute("SELECT COUNT(*) FROM faturamento WHERE id_produto = 999").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT DISTINCT id_produto FROM faturamento WHERE id_cliente = 3").fetchall(), [(11469,)])
        # a venda ao funcionário 7 não leva o nome do cliente 7
        self.assertEqual(c.execute("SELECT cliente FROM faturamento WHERE tipo_cliente = 'FUNCIONARIO'").fetchone()[0],
                         "Funcionário cód. 7")
        self.assertEqual(c.execute("SELECT COUNT(*) FROM devolucoes").fetchone()[0], 4)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM devolucoes WHERE desconta").fetchone()[0], 2)
        self.assertEqual(c.execute("SELECT vendedor_carteira FROM clientes WHERE id_cliente = 2").fetchone()[0], "Thais")

    def test_acesso_restrito_so_ve_os_seus(self):
        a = criar_assistente(self.pasta, self.calc)
        ids = a.ids_do_escopo(None, {"ES"})
        self.assertEqual(ids, frozenset({ES}))
        f = Ferramentas(a.recorte(ids), self.calc, a.cfg, {"ES"})
        c = f.cur
        for tabela in ("faturamento", "devolucoes", "pedidos", "metas_vendedor", "metas_produto", "vendedores"):
            vistos = {r[0] for r in c.execute(f"SELECT DISTINCT id_vendedor FROM {tabela}").fetchall()}
            self.assertLessEqual(vistos, {ES}, tabela)
        self.assertEqual({r[0] for r in c.execute("SELECT id_cliente FROM clientes").fetchall()}, {1, 3})
        r, p = f.executar("buscar_cliente", {"texto": "padaria maria"})
        self.assertEqual(r["linhas"], [])
        r, p = f.executar("metas_e_realizado", {"visao": "ba", "meses": ["2026-09"]})
        self.assertIn("acesso", p["erro"])
        r, p = f.executar("metas_e_realizado", {"visao": "es", "meses": ["2026-09"]})
        self.assertIsNone(p["erro"])
        self.assertEqual([v["id"] for v in r["vendedores"]], [ES])

    def test_alguns_vendedores(self):
        a = criar_assistente(self.pasta, self.calc)
        self.assertEqual(a.ids_do_escopo({BA, EDIR}, None), frozenset({BA, EDIR}))
        self.assertIsNone(a.ids_do_escopo(None, None))

    def test_recorte_reaproveitado_e_refeito_quando_regra_muda(self):
        a = criar_assistente(self.pasta, self.calc)
        r1 = a.recorte(None)
        self.assertIs(a.recorte(None), r1)
        cfg = self.calc.configuracao.atual()
        cfg["devolucoes"]["motivos"] = [1, 2, 3]
        self.calc.configuracao.salvar(cfg)
        self.assertIsNot(a.recorte(None), r1)


class TestFerramentas(Base):
    def test_sql_so_leitura(self):
        f, _ = self.ferramentas()
        bloqueados = ["DELETE FROM clientes", "CREATE TABLE x AS SELECT 1", "SELECT 1; SELECT 2",
                      "SELECT * FROM read_csv('config.ini')", "COPY clientes TO 'x.csv'", "ATTACH 'x.db'",
                      "SET threads = 4", "INSTALL httpfs", "SELECT * FROM glob('*')", "EXPLAIN SELECT 1",
                      "PRAGMA memory_limit = '4GB'"]
        for sql in bloqueados:
            _, p = f.executar("consultar_sql", {"sql": sql, "objetivo": "teste"})
            self.assertTrue(p["erro"], sql)
        r, p = f.executar("consultar_sql", {"sql": "WITH x AS (SELECT 1 AS a) SELECT a FROM x", "objetivo": "teste"})
        self.assertIsNone(p["erro"])
        self.assertEqual(r["linhas"], [[1]])

    def test_tempo_limite_e_linhas(self):
        f, _ = self.ferramentas(tempo_sql=0.3, max_linhas=5)
        _, p = f.executar("consultar_sql", {"sql": "SELECT count(*) FROM range(1000000000) a, range(1000) b", "objetivo": "x"})
        self.assertIn("interrompida", p["erro"])
        r, p = f.executar("consultar_sql", {"sql": "SELECT * FROM range(100)", "objetivo": "x"})
        self.assertEqual(len(r["linhas"]), 5)
        self.assertIn("cortado", r["aviso"])
        # o cursor continua bom depois da interrupção
        self.assertEqual(f.executar("consultar_sql", {"sql": "SELECT 2", "objetivo": "x"})[0]["linhas"], [[2]])

    def test_resumo_vendas(self):
        f, _ = self.ferramentas()
        r, p = f.executar("resumo_vendas", {"de": "2026-09-01", "ate": "2026-09-30", "clientes": [1]})
        self.assertIsNone(p["erro"])
        self.assertEqual(r["total"]["valor_bruto"], 1300.0)
        self.assertEqual(r["total"]["valor_devolvido"], 100.0)
        self.assertEqual(r["total"]["valor_liquido"], 1200.0)
        r, p = f.executar("resumo_vendas", {"de": "2026-08-01", "ate": "2026-09-30", "agrupar_por": ["mes", "equipe"]})
        self.assertEqual(r["colunas"][:2], ["mes", "equipe"])
        self.assertEqual(r["linhas"][0][0], "2026-08")
        r, p = f.executar("resumo_vendas", {"de": "2026-09-01", "ate": "2026-09-30", "clientes": [7]})
        self.assertEqual(r["total"]["valor_bruto"], 0.0)  # o 7 do funcionário não é o cliente 7
        _, p = f.executar("resumo_vendas", {"de": "2026-09-30", "ate": "2026-09-01"})
        self.assertTrue(p["erro"])
        _, p = f.executar("resumo_vendas", {"de": "2026-09-01", "ate": "2026-09-30", "agrupar_por": ["mes", "dia", "uf"]})
        self.assertTrue(p["erro"])
        _, p = f.executar("resumo_vendas", {"de": "2026-09-01", "ate": "2026-09-30", "inventado": 1})
        self.assertTrue(p["erro"])

    def test_buscas(self):
        f, _ = self.ferramentas()
        r, _ = f.executar("buscar_cliente", {"texto": "joão"})
        self.assertEqual(r["linhas"][0][0], 1)
        r, _ = f.executar("buscar_cliente", {"texto": "3"})
        self.assertEqual(r["linhas"][0][0], 3)
        r, _ = f.executar("buscar_cliente", {"texto": "acougue"})  # sem acento acha "AÇOUGUE" e "ACOUGUE"
        self.assertEqual(r["linhas"][0][0], 3)
        r, _ = f.executar("buscar_produto", {"texto": "mussarela"})
        self.assertEqual(r["linhas"][0][0], 32)
        r, _ = f.executar("buscar_vendedor", {"texto": ""})
        self.assertEqual({x[0] for x in r["linhas"]}, {ES, BA, EDIR})


class TestLaco(Base):
    def test_pergunta_com_ferramentas(self):
        pensamento = bloco_pensamento()
        primeira = resposta(pensamento, bloco_ferramenta("t1", "buscar_cliente", {"texto": "mercado do joao"}),
                            parada="tool_use", cache_escrita=3000)
        segunda = resposta(bloco_ferramenta("t2", "resumo_vendas", {"de": "2026-09-01", "ate": "2026-09-30", "clientes": [1]}),
                           bloco_ferramenta("t3", "consultar_sql", {"sql": "DROP TABLE clientes", "objetivo": "x"}),
                           parada="tool_use", cache_leitura=3000)
        terceira = resposta(bloco_texto("O **Mercado do João** comprou R$ 1.200,00 líquidos em setembro."), cache_leitura=3500)
        api = ClienteFalso([primeira, segunda, terceira])
        a = criar_assistente(self.pasta, self.calc, cliente=api)
        r = a.responder(USUARIO_VIS, [{"papel": "usuario", "texto": "quanto o mercado do joão comprou em setembro?"}],
                        None, None)
        self.assertIn("1.200,00", r["resposta"])
        self.assertEqual([p["ferramenta"] for p in r["passos"]], ["buscar_cliente", "resumo_vendas", "consultar_sql"])
        self.assertTrue(r["passos"][2]["erro"])
        self.assertIn("buscar_cliente", r["consultas"])
        self.assertEqual(len(api.pedidos), 3)
        # a resposta da API volta inteira e sem mudança, com o bloco de pensamento
        msgs = api.pedidos[1]["messages"]
        self.assertIs(msgs[1]["content"], primeira.content)
        self.assertIs(msgs[1]["content"][0], pensamento)
        resultado = msgs[2]["content"][0]
        self.assertEqual(resultado["tool_use_id"], "t1")
        self.assertEqual(json.loads(resultado["content"])["linhas"][0][0], 1)
        erro = api.pedidos[2]["messages"][4]["content"][1]
        self.assertEqual((erro["tool_use_id"], erro.get("is_error")), ("t3", True))
        # instruções fixas com cache e a parte do dia depois; nada de thinking/temperature
        p = api.pedidos[0]
        self.assertEqual(p["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertIn("Quem pergunta: Visualizador", p["system"][1]["text"])
        self.assertEqual(p["fallbacks"], "default")
        self.assertNotIn("thinking", p)
        self.assertNotIn("temperature", p)
        self.assertNotIn("tool_choice", p)
        self.assertEqual(api.pedidos[0]["system"], api.pedidos[2]["system"])
        self.assertEqual(api.pedidos[0]["tools"], api.pedidos[2]["tools"])
        # custo: 3 chamadas de 1000 de entrada + 100 de saída, mais cache
        esperado = (3000 * 4 + 300 * 20 + 6500 * 0.20 + 3000 * 5) / 1e6
        self.assertEqual(r["uso"], {"segundos": r["uso"]["segundos"]})  # visualizador não vê custo
        registro = json.loads(next((self.pasta / "logs").glob("assistente-*.jsonl")).read_text(encoding="utf-8"))
        self.assertAlmostEqual(registro["uso"]["custo"], esperado, places=6)
        self.assertEqual(registro["pergunta"], "quanto o mercado do joão comprou em setembro?")
        self.assertEqual(r["restantes"], 49)

    def test_historico_so_texto_com_consultas_anteriores(self):
        api = ClienteFalso([resposta(bloco_texto("Em agosto foram R$ 4.000,00."))])
        a = criar_assistente(self.pasta, self.calc, cliente=api)
        conversa = [
            {"papel": "usuario", "texto": "quanto a padaria da maria comprou em setembro?"},
            {"papel": "assistente", "texto": "R$ 4.750,00.", "consultas": 'buscar_cliente{"texto":"padaria"} -> 2 PADARIA'},
            {"papel": "usuario", "texto": "e em agosto?"},
        ]
        a.responder(USUARIO_ADMIN, conversa, None, None)
        msgs = api.pedidos[0]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[1]["content"], "R$ 4.750,00.")
        self.assertTrue(msgs[2]["content"].startswith("<consultas_anteriores>\nbuscar_cliente"))
        self.assertTrue(msgs[2]["content"].endswith("e em agosto?"))
        with self.assertRaises(ErroAssistente):
            a.responder(USUARIO_ADMIN, [{"papel": "usuario", "texto": "a"}, {"papel": "usuario", "texto": "b"}], None, None)

    def test_limite_de_passos_forca_resposta(self):
        def sempre_ferramenta(pedido):
            if pedido.get("tool_choice") == {"type": "none"}:
                return resposta(bloco_texto("Resposta com o que deu para consultar."))
            return resposta(bloco_ferramenta(f"t{len(api.pedidos)}", "buscar_vendedor", {"texto": ""}), parada="tool_use")
        api = ClienteFalso([sempre_ferramenta] * 4)
        a = criar_assistente(self.pasta, self.calc, cliente=api, max_passos=2)
        r = a.responder(USUARIO_ADMIN, [{"papel": "usuario", "texto": "liste tudo"}], None, None)
        self.assertEqual(len(api.pedidos), 3)
        self.assertEqual(api.pedidos[2]["tool_choice"], {"type": "none"})
        self.assertIn("muitas consultas", r["aviso"])
        self.assertIn("custo", r["uso"])  # administrador vê o custo

    def test_recusa(self):
        api = ClienteFalso([resposta(parada="refusal")])
        a = criar_assistente(self.pasta, self.calc, cliente=api)
        r = a.responder(USUARIO_ADMIN, [{"papel": "usuario", "texto": "x"}], None, None)
        self.assertIn("recusou", r["aviso"])

    def test_limites(self):
        api = ClienteFalso([resposta(bloco_texto("ok"))] * 3)
        a = criar_assistente(self.pasta, self.calc, cliente=api, limite_diario=2)
        pergunta = [{"papel": "usuario", "texto": "x"}]
        a.responder(USUARIO_VIS, pergunta, None, None)
        a.responder(USUARIO_VIS, pergunta, None, None)
        with self.assertRaises(ErroAssistente) as e:
            a.responder(USUARIO_VIS, pergunta, None, None)
        self.assertEqual(e.exception.status, 429)
        # o limite volta do registro quando o painel reinicia
        b = criar_assistente(self.pasta, self.calc, cliente=api, limite_diario=2)
        self.assertEqual(b.restantes(USUARIO_VIS), 0)
        self.assertIsNone(b.restantes(USUARIO_ADMIN))
        self.assertEqual(b.uso()["por_usuario"][0]["perguntas"], 2)

    def test_acesso_sem_vendedores(self):
        a = criar_assistente(self.pasta, self.calc, cliente=ClienteFalso([]))
        with self.assertRaises(ErroAssistente) as e:
            a.responder(USUARIO_VIS, [{"papel": "usuario", "texto": "x"}], set(), None)
        self.assertEqual(e.exception.status, 403)

    def test_sem_chave_ou_sem_detalhe(self):
        a = criar_assistente(self.pasta, self.calc, chave="")
        self.assertFalse(a.configurado)
        with self.assertRaises(ErroAssistente) as e:
            a.responder(USUARIO_ADMIN, [{"papel": "usuario", "texto": "x"}], None, None)
        self.assertEqual(e.exception.status, 503)
        self.calc.cache.sem_detalhe = True
        b = criar_assistente(self.pasta, self.calc, cliente=ClienteFalso([]))
        with self.assertRaises(ErroAssistente) as e:
            b.responder(USUARIO_ADMIN, [{"papel": "usuario", "texto": "x"}], None, None)
        self.assertIn("por cliente", str(e.exception))


if __name__ == "__main__":
    unittest.main()

"""O ritmo da página Metas conta até o último dia útil antes do dia da cópia do banco (bi/metas.py dia_do_ritmo): a
cópia da manhã ainda não tem as vendas do dia, ou só as primeiras notas. Usa o cache sintético de tests/apoio.py
(setembro de 2026: 21 dias úteis no ES, com o 7 de Setembro na segunda)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bi.calendario import Calendario
from tests.apoio import D, criar_calc


class TestDiaUtilAntes(unittest.TestCase):
    def test_volta_fim_de_semana_e_feriado(self):
        cal = Calendario()
        self.assertEqual(cal.dia_util_antes(D(2026, 11, 9), "ES"), D(2026, 11, 6))   # segunda -> sexta
        self.assertEqual(cal.dia_util_antes(D(2026, 11, 3), "BA"), D(2026, 10, 30))  # depois de Finados e do domingo
        self.assertEqual(cal.dia_util_antes(D(2026, 6, 5), "ES"), D(2026, 6, 3))     # Corpus Christi só para o ES
        self.assertEqual(cal.dia_util_antes(D(2026, 6, 5), "BA"), D(2026, 6, 4))

    def test_sabado_com_expediente_conta(self):
        cal = Calendario(peso_sabado={"ES": 0.5})
        self.assertEqual(cal.dia_util_antes(D(2026, 11, 9), "ES"), D(2026, 11, 7))
        self.assertEqual(cal.dia_util_antes(D(2026, 11, 9), "BA"), D(2026, 11, 6))


class TestRitmoDaPaginaMetas(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.calc = criar_calc(Path(self._tmp.name), fora=(999,))
        self.info = self.calc.cache.info

    def tearDown(self):
        self._tmp.cleanup()

    def visao(self, data_ref, copia, chave="banco_copia"):
        self.info["data_ref"] = data_ref
        self.info.pop("banco_copia", None)
        self.info[chave] = copia
        return self.calc.visao("es", [(2026, 9)])

    def test_copia_da_manha_com_as_primeiras_notas_do_dia(self):
        # terça 15/9 de manhã, já com notas do dia 15: o ritmo conta até a segunda 14/9 (9 dos 21 dias úteis)
        d = self.visao("2026-09-15", "2026-09-15T08:00")
        c = d["calendario"]
        self.assertEqual((d["data_ref"], c["ritmo_ate"]), ("2026-09-15", "2026-09-14"))
        self.assertEqual((c["dias_decorridos"], c["dias_uteis"], c["dias_restantes"], c["situacao"]), (9, 21, 12, "aberto"))
        self.assertAlmostEqual(c["ritmo"], 9 / 21)
        self.assertEqual([x["data"] for x in c["dias"] if x["passou"]][-1], "2026-09-14")
        fat = d["indicadores"]["faturamento"]
        self.assertAlmostEqual(fat["esperado"], fat["meta"] * 9 / 21)
        # as notas do dia 15 continuam no realizado (o mesmo de quando o ritmo contava o dia 15)
        self.assertEqual(fat["realizado"], self.visao("2026-09-15", "2026-09-16T08:00")["indicadores"]["faturamento"]["realizado"])

    def test_segunda_de_manha_conta_ate_a_sexta(self):
        c = self.visao("2026-09-14", "2026-09-14T08:00")["calendario"]
        self.assertEqual((c["ritmo_ate"], c["dias_decorridos"]), ("2026-09-11", 8))

    def test_sem_venda_no_dia_util_anterior_fica_na_ultima_venda(self):
        c = self.visao("2026-09-10", "2026-09-15T08:00")["calendario"]
        self.assertEqual(c["ritmo_ate"], "2026-09-10")

    def test_cache_antigo_sem_a_data_da_copia_usa_a_extracao(self):
        c = self.visao("2026-09-15", "2026-09-15T08:52:19", chave="extraido_em")["calendario"]
        self.assertEqual(c["ritmo_ate"], "2026-09-14")

    def test_mes_fechado_no_primeiro_dia_do_mes_seguinte(self):
        d = self.visao("2026-09-30", "2026-10-01T07:00")
        self.assertEqual((d["calendario"]["ritmo_ate"], d["calendario"]["situacao"], d["calendario"]["ritmo"]),
                         ("2026-09-30", "fechado", 1.0))
        # outubro, escolhido no dia 1º: nenhum dia útil fechou ainda
        self.assertEqual(self.calc.visao("es", [(2026, 10)])["calendario"]["situacao"], "futuro")


if __name__ == "__main__":
    unittest.main()

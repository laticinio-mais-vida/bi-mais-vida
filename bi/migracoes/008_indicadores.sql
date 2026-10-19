-- Indicadores das campanhas (bi/indicadores.py): os tipos prontos (positivação, mix médio, efetividade, frequência e
-- preço médio por produto) e a Personalizada, montada por blocos (medida × forma) em `parametros`. Faturamento,
-- volume e mix (produtos distintos) viram Personalizada, com os mesmos números.

-- O CHECK de metrica foi criado sem nome na 007: acha pelo texto.
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'campanhas'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%metrica%'
  LOOP
    EXECUTE format('ALTER TABLE campanhas DROP CONSTRAINT %I', r.conname);
  END LOOP;
END $$;

-- medida, forma e comparar (Personalizada), clientes e dias_sem_compra (base de clientes)
ALTER TABLE campanhas ADD COLUMN parametros jsonb NOT NULL DEFAULT '{}';
UPDATE campanhas SET metrica = 'personalizada',
       parametros = jsonb_build_object('medida', CASE metrica WHEN 'mix' THEN 'produtos' ELSE metrica END, 'forma', 'total')
 WHERE metrica IN ('faturamento', 'volume', 'mix');
UPDATE campanhas SET parametros = '{"clientes": "todos"}' WHERE metrica = 'positivacao';
ALTER TABLE campanhas ADD CONSTRAINT campanhas_metrica_check
  CHECK (metrica IN ('positivacao', 'mix_medio', 'efetividade', 'frequencia', 'preco_medio', 'personalizada'));

-- Preço médio por produto: o preço-alvo de cada produto (R$ por unidade do produto).
CREATE TABLE campanha_produtos (
  campanha bigint NOT NULL REFERENCES campanhas ON DELETE CASCADE,
  id_produto integer NOT NULL,  -- código do produto no ERP (já o equivalente)
  meta numeric NOT NULL CHECK (meta > 0),
  PRIMARY KEY (campanha, id_produto)
);

-- Dias de atendimento de cada área comercial (a efetividade conta as visitas esperadas por eles). ISO: 1 = segunda
-- ... 7 = domingo; '{}' = área que não é atendida (os clientes dela ficam fora da efetividade). Área sem linha aqui
-- fica pendente: também fica fora, e o andamento avisa. Começa com a planilha "Dia de Atendimento Areas
-- Comerciais.xlsx" do Power BI, pela coluna numérica (a de texto tem "Terça" com acento, que o Power BI não reconhece).
CREATE TABLE areas_atendimento (
  id_area integer PRIMARY KEY,  -- código da área no ERP (AREASCOMERCIAIS)
  nome text NOT NULL DEFAULT '',  -- cópia, para a tela de configuração mostrar áreas sem clientes
  dias smallint[] NOT NULL CHECK (dias <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]),
  atualizada_em timestamptz NOT NULL DEFAULT now(),
  atualizada_por_nome text
);
INSERT INTO areas_atendimento (id_area, nome, dias, atualizada_por_nome)
SELECT id_area, nome, ARRAY[dia]::smallint[], 'planilha do Power BI' FROM (VALUES
  (24, 'ITABELA (SEGUNDA)', 1),
  (166, 'PS - BAIANAO (SEGUNDA)', 1),
  (176, 'PS CENTRAL - ARRAIAL HOTEIS (SEGUNDA)', 1),
  (184, 'PS - ARRAIAL HOTELARIA (SEGUNDA)', 1),
  (207, 'EUNÁPOLIS (SEGUNDA)', 1),
  (209, 'EUNÁPOLIS (TERCA)', 1),
  (257, 'PS REDES - BAIANAO (SEGUNDA)', 1),
  (259, 'PS REDES - ARRAIAL (SEGUNDA)', 1),
  (267, 'PS CENTRAL - BAIANAO (SEGUNDA)', 1),
  (301, 'ROGERIO (SEGUNDA) MUDAR', 1),
  (311, 'ANTONIO (SEGUNDA) MUDAR', 1),
  (337, 'ADRIANA (SEGUNDA) MUDAR', 1),
  (341, 'RUBENS (SEGUNDA) MUDAR', 1),
  (351, 'RICARDO (SEGUNDA) MUDAR', 1),
  (359, 'RONALDO (SEGUNDA) MUDAR', 1),
  (375, 'JOSE CARLOS (SEGUNDA) MUDAR', 1),
  (391, 'ISAQUE (SEGUNDA) MUDAR', 1),
  (401, 'TATIANA (SEGUNDA) MUDAR', 1),
  (415, 'SAMIRA (SEGUNDA) MUDAR', 1),
  (45, 'ITAMARAJU (TERCA)', 2),
  (168, 'PS - COROA / CABRALIA (TERÇA)', 2),
  (178, 'PS CENTRAL - COROA / CABRALIA (TERÇA)', 2),
  (186, 'PS - ARRAIAL BAIRROS (TERÇA)', 2),
  (194, 'PS REDES - COROA / CABRALIA (TERÇA)', 2),
  (211, 'EUNÁPOLIS CENTRAL (SEGUNDA E TERÇA)', 2),
  (235, 'EUNÁPOLIS REDES (TERÇA)', 2),
  (265, 'PS CENTRAL - ARRAIAL BAIRROS (TERÇA)', 2),
  (289, 'PS REDES - ORLA (TERÇA)', 2),
  (303, 'ROGERIO (TERCA) MUDAR', 2),
  (313, 'ANTONIO (TERCA) MUDAR', 2),
  (333, 'ADRIANA (TERCA) MUDAR', 2),
  (343, 'RUBENS (TERÇA) MUDAR', 2),
  (349, 'RICARDO (TERÇA) MUDAR', 2),
  (361, 'RONALDO (TERÇA) MUDAR', 2),
  (369, 'SAMIRA (TERÇA) MUDAR', 2),
  (377, 'JOSE CARLOS (TERCA) MUDAR', 2),
  (393, 'ISAQUE (TERCA) MUDAR', 2),
  (403, 'TATIANA (TERÇA) MUDAR', 2),
  (170, 'PS - ORLA (QUARTA)', 3),
  (180, 'PS CENTRAL - ORLA (QUARTA)', 3),
  (196, 'PS REDES - BAIRROS (QUARTA)', 3),
  (273, 'PS CENTRAL - BAIRROS (QUARTA)', 3),
  (281, 'PS - BAIRROS (QUARTA)', 3),
  (305, 'ROGERIO (QUARTA) MUDAR', 3),
  (315, 'ANTONIO (QUARTA) MUDAR', 3),
  (335, 'ADRIANA (QUARTA) MUDAR', 3),
  (345, 'RUBENS (QUARTA) MUDAR', 3),
  (353, 'RICARDO (QUARTA) MUDAR', 3),
  (363, 'RONALDO (QUARTA) MUDAR', 3),
  (379, 'JOSE CARLOS (QUARTA) MUDAR', 3),
  (395, 'ISAQUE (QUARTA) MUDAR', 3),
  (405, 'TATIANA (QUARTA) MUDAR', 3),
  (417, 'SAMIRA (QUARTA) MUDAR', 3),
  (182, 'PS CENTRAL - CENTRO (QUINTA)', 4),
  (190, 'PS - CENTRO (QUINTA)', 4),
  (219, 'TEIXEIRA CENTRAL (QUINTA)', 4),
  (283, 'TEIXEIRA (QUINTA)', 4),
  (291, 'ITAMARAJU (QUINTA)', 4),
  (307, 'ROGERIO (QUINTA) MUDAR', 4),
  (317, 'ANTONIO (QUINTA) MUDAR', 4),
  (339, 'ADRIANA (QUINTA) MUDAR', 4),
  (347, 'RUBENS (QUINTA) MUDAR', 4),
  (355, 'RICARDO (QUINTA) MUDAR', 4),
  (365, 'RONALDO (QUINTA) MUDAR', 4),
  (381, 'JOSE CARLOS (QUINTA) MUDAR', 4),
  (397, 'ISAQUE (QUINTA) MUDAR', 4),
  (407, 'TATIANA (QUINTA) MUDAR', 4),
  (419, 'SAMIRA (QUINTA) MUDAR)', 4),
  (69, 'TEIXEIRA (SEXTA)', 5),
  (172, 'PS - TRANCOSO (SEXTA)', 5),
  (174, 'PS CENTRAL - TRANCOSO (SEXTA)', 5),
  (287, 'PS REDES - CENTRO (SEXTA)', 5),
  (309, 'ROGERIO (SEXTA) MUDAR', 5),
  (319, 'ANTONIO (SEXTA) MUDAR', 5),
  (331, 'ADRIANA (SEXTA) MUDAR', 5),
  (357, 'RICARDO (SEXTA) MUDAR', 5),
  (367, 'RONALDO (SEXTA) MUDAR', 5),
  (383, 'JOSE CARLOS (SEXTA) MUDAR', 5),
  (399, 'ISAQUE (SEXTA) MUDAR', 5),
  (409, 'TATIANA (SEXTA) MUDAR', 5),
  (421, 'SAMIRA (SEXTA) MUDAR', 5),
  (200, 'PS REDES - TRANCOSO (SABADO)', 6),
  (237, 'TEIXEIRA REDES (SABADO)', 6),
  (261, 'ITAMARAJU REDES (SABADO)', 6)
) AS v(id_area, nome, dia);

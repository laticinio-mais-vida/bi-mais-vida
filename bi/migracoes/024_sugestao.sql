-- Sugestão de Metas (bi/sugestao.py): as regras da página (crescimento desejado por estado, tetos, áreas com número
-- fixo de faturamentos, o prazo do faturamento de cada área e os ajustes à mão por área e mês) ficam na tabela regras,
-- com versões, como as de Metas e das Projeções. O CHECK do nome passa a aceitar 'sugestao'.

ALTER TABLE regras DROP CONSTRAINT regras_nome_check;
ALTER TABLE regras ADD CONSTRAINT regras_nome_check CHECK (nome IN ('metas', 'projecoes', 'sugestao'));

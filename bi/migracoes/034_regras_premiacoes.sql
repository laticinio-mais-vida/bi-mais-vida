-- Premiações (bi/premiacoes.py): as regras da página (faixas dos vendedores; pesos, mínimos e metas do supervisor; nomes
-- dos supervisores e os ajustes à mão das metas de um mês) ficam na tabela regras, com versões, como as de Metas, das
-- Projeções e da Sugestão. O CHECK do nome passa a aceitar 'premiacoes'. (A 033 é outra coisa: a premiação das
-- campanhas da Gestão.)

ALTER TABLE regras DROP CONSTRAINT regras_nome_check;
ALTER TABLE regras ADD CONSTRAINT regras_nome_check CHECK (nome IN ('metas', 'projecoes', 'sugestao', 'premiacoes'));

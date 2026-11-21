-- CRM (página CRM, bi/crm.py): a nota de 0 a 100 de cada cliente, pela aderência à frequência, a pontualidade, o mix
-- ideal do segmento e a rentabilidade. Nenhuma tabela nova: as regras da página (os números de cada indicador, o mix
-- ideal de cada segmento e a tabela de custos industriais) ficam na tabela regras, com versões, como as das outras
-- páginas (ConfigCrm em bi/crm.py). Sem nenhuma versão salva, vale o padrão do código.
ALTER TABLE regras DROP CONSTRAINT regras_nome_check;
ALTER TABLE regras ADD CONSTRAINT regras_nome_check
  CHECK (nome IN ('metas', 'projecoes', 'sugestao', 'premiacoes', 'credito', 'manejo', 'crm'));

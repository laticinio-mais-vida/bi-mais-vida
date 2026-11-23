-- Limites do Assistente por pessoa (Configurações do assistente › Limites): o gasto total por dia e por mês e, para
-- cada pessoa, perguntas por dia e gasto por dia e por mês, com um padrão e limites próprios. Nenhuma tabela nova:
-- ficam na tabela regras, com versões, como as regras das outras páginas (LimitesAssistente em bi/uso.py). Sem
-- nenhuma versão salva, valem os de [ia] no config.ini (limite_diario e limite_custo_dia).
ALTER TABLE regras DROP CONSTRAINT regras_nome_check;
ALTER TABLE regras ADD CONSTRAINT regras_nome_check
  CHECK (nome IN ('metas', 'projecoes', 'sugestao', 'premiacoes', 'credito', 'manejo', 'crm', 'assistente'));

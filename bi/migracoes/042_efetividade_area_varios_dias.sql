-- Na área com mais de um dia de atendimento, os dias passam a ser os dias em que o vendedor PODE atender, e a semana
-- conta como um dia só na efetividade (bi/indicadores.py, decisão do usuário de 11/11/2026); antes, cada dia marcado
-- esperava uma visita de cada cliente. Se alguma área já tem mais de um dia, as bases já medidas das ações de
-- efetividade sem resultado congelado voltam a "aguardando" e são medidas de novo na próxima leitura
-- (Gestao._pendencias), com o retrato dos eventos da mesma janela, como na 010, na 011 e na 014. Sem área assim, nada
-- muda: a conta das áreas de um dia é a mesma.

UPDATE gestao_eventos e SET dados = e.dados || '{"base_pendente": true}'::jsonb
  FROM campanhas c
 WHERE e.campanha = c.id AND c.tipo = 'acao' AND c.metrica = 'efetividade' AND NOT c.arquivada
   AND c.resultado_em IS NULL AND e.tipo <> 'nota'
   AND e.dados->>'base_inicio' = to_char(c.base_inicio, 'YYYY-MM-DD')
   AND e.dados->>'base_fim' = to_char(c.base_fim, 'YYYY-MM-DD')
   AND EXISTS (SELECT 1 FROM areas_atendimento WHERE cardinality(dias) > 1);

UPDATE campanha_vendedores v SET base = NULL, base_num = NULL, base_den = NULL, base_em = NULL
  FROM campanhas c
 WHERE v.campanha = c.id AND c.tipo = 'acao' AND c.metrica = 'efetividade' AND NOT c.arquivada
   AND c.resultado_em IS NULL
   AND EXISTS (SELECT 1 FROM areas_atendimento WHERE cardinality(dias) > 1);

UPDATE campanhas SET versao = versao + 1
 WHERE tipo = 'acao' AND metrica = 'efetividade' AND NOT arquivada AND resultado_em IS NULL
   AND EXISTS (SELECT 1 FROM areas_atendimento WHERE cardinality(dias) > 1);

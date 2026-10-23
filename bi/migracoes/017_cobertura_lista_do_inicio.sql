-- A cobertura da positivação passa a dividir pelos clientes ativos no início (decisão do usuário, 2026-10-23): todos os
-- clientes que o vendedor atendeu ÷ a lista de ativos da carteira dele no primeiro dia, que não muda depois (na base de
-- mais de 31 dias, cada mês com a lista do seu 1º dia). As bases das positivações de todos os clientes sem resultado
-- congelado, gravadas com a regra da 016 (os ativos de algum dia do mês), são medidas de novo na próxima leitura
-- (Gestao._pendencias); as já congeladas ficam como estão.

-- Meta em clientes: só a cobertura, ao lado da base (so_cobertura), sem mexer na base nem no alvo.
UPDATE campanha_vendedores v SET base_cobertura = NULL
  FROM campanhas c
 WHERE v.campanha = c.id AND c.tipo = 'acao' AND c.metrica = 'positivacao' AND NOT c.arquivada
   AND c.resultado_em IS NULL AND v.base_cobertura IS NOT NULL
   AND c.parametros->>'meta_em' IS DISTINCT FROM 'pct_base';

-- Meta em % da base: a cobertura é a própria base, que volta a "aguardando" com o retrato dos eventos da mesma janela,
-- como na 010, na 011 e na 014.
UPDATE gestao_eventos e SET dados = e.dados || '{"base_pendente": true}'::jsonb
  FROM campanhas c
 WHERE e.campanha = c.id AND c.tipo = 'acao' AND c.metrica = 'positivacao' AND NOT c.arquivada
   AND c.resultado_em IS NULL AND c.parametros->>'meta_em' = 'pct_base' AND e.tipo <> 'nota'
   AND e.dados->>'base_inicio' = to_char(c.base_inicio, 'YYYY-MM-DD')
   AND e.dados->>'base_fim' = to_char(c.base_fim, 'YYYY-MM-DD');

UPDATE campanha_vendedores v SET base = NULL, base_num = NULL, base_den = NULL, base_cobertura = NULL, base_em = NULL
  FROM campanhas c
 WHERE v.campanha = c.id AND c.tipo = 'acao' AND c.metrica = 'positivacao' AND NOT c.arquivada
   AND c.resultado_em IS NULL AND c.parametros->>'meta_em' = 'pct_base';

UPDATE campanhas SET versao = versao + 1
 WHERE tipo = 'acao' AND metrica = 'positivacao' AND NOT arquivada AND resultado_em IS NULL;

-- Na efetividade, o cliente fora da previsão do dia (quinzenal ou mensal que já tinha comprado) que compra no dia
-- passa a entrar nas visitas esperadas desse dia (bi/indicadores.py), e não só nos pedidos, como na 011. As bases já
-- medidas das ações de efetividade sem resultado congelado voltam a "aguardando" e são medidas de novo na próxima
-- leitura (Gestao._pendencias), com o retrato dos eventos da mesma janela, como na 010 e na 011.

UPDATE gestao_eventos e SET dados = e.dados || '{"base_pendente": true}'::jsonb
  FROM campanhas c
 WHERE e.campanha = c.id AND c.tipo = 'acao' AND c.metrica = 'efetividade' AND NOT c.arquivada
   AND c.resultado_em IS NULL AND e.tipo <> 'nota'
   AND e.dados->>'base_inicio' = to_char(c.base_inicio, 'YYYY-MM-DD')
   AND e.dados->>'base_fim' = to_char(c.base_fim, 'YYYY-MM-DD');

UPDATE campanha_vendedores v SET base = NULL, base_num = NULL, base_den = NULL, base_em = NULL
  FROM campanhas c
 WHERE v.campanha = c.id AND c.tipo = 'acao' AND c.metrica = 'efetividade' AND NOT c.arquivada
   AND c.resultado_em IS NULL;

UPDATE campanhas SET versao = versao + 1
 WHERE tipo = 'acao' AND metrica = 'efetividade' AND NOT arquivada AND resultado_em IS NULL;

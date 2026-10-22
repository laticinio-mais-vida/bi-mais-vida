-- Preço médio nas campanhas (bi/indicadores.py progresso_preco): o % da meta de cada vendedor passa a ser o aumento de
-- preço feito ÷ o aumento pedido, do preço dele na base até o preço-alvo de cada produto (decisão do usuário: a meta é
-- o aumento, não o preço cheio). Para isso o vendedor guarda o preço de cada produto na base e, no fim, o do resultado:
-- {"<código do produto>": {"preco": R$ por unidade, "quantidade": ...}}; '{}' = sem venda dos produtos na janela.
ALTER TABLE campanha_vendedores
  ADD COLUMN base_precos jsonb,
  ADD COLUMN resultado_precos jsonb;

-- As bases já gravadas com um produto só saem do próprio índice: preço = vendido ÷ quantidade, e a quantidade é o
-- "nos preços-alvo" ÷ o preço-alvo. Com mais produtos, a base é medida de novo na próxima leitura (bi/gestao.py
-- _pendencias). Resultado já congelado fica sem os preços (o histórico mostra o índice de antes).
UPDATE campanha_vendedores v
   SET base_precos = CASE WHEN v.base_den > 0 THEN jsonb_build_object(p.id_produto::text, jsonb_build_object(
                            'preco', round(v.base_num / (v.base_den / p.meta), 4),
                            'quantidade', round(v.base_den / p.meta, 4)))
                          ELSE '{}'::jsonb END
  FROM campanhas c
  JOIN campanha_produtos p ON p.campanha = c.id
 WHERE v.campanha = c.id AND c.metrica = 'preco_medio' AND v.base_em IS NOT NULL
   AND (SELECT count(*) FROM campanha_produtos x WHERE x.campanha = c.id) = 1;

-- E o histórico: os eventos que mostram essa mesma base levam os preços dela.
UPDATE gestao_eventos e
   SET dados = e.dados || jsonb_build_object('base_precos', v.base_precos)
  FROM campanha_vendedores v
 WHERE e.campanha = v.campanha AND e.id_vendedor = v.id_vendedor AND v.base_precos IS NOT NULL
   AND jsonb_typeof(e.dados->'base') = 'number' AND round((e.dados->>'base')::numeric, 4) = round(v.base, 4);

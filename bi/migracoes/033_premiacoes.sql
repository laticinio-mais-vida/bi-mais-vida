-- Premiações nas campanhas da Gestão (bi/gestao.py, pedido do usuário): um prêmio único ou por faixas (80% → x, 90% → y,
-- 100% → z), as mesmas para todos os vendedores da campanha. Cada um ganha a maior faixa que atingir. O % que decide a
-- faixa sai do crescimento ((resultado − base) ÷ (meta − base)) ou do número atingido (resultado ÷ meta), escolhido na
-- campanha (na meta Percentual e no preço médio, sempre o crescimento). O prêmio de cada vendedor não fica gravado:
-- sai da base, da meta e do resultado congelados, como a classe; o histórico guarda o do momento (evento resultado).
-- {"sobre": "crescimento" | "resultado", "faixas": [{"pct": 80, "premio": "Vale-compras", "valor": 100}, ...]}
-- (pct em %, em ordem crescente; valor em R$, NULL = só a descrição); NULL = sem premiação.
ALTER TABLE campanhas
  ADD COLUMN premiacoes jsonb,
  ADD CONSTRAINT campanhas_premiacoes_check CHECK (premiacoes IS NULL OR tipo = 'acao');

-- A coluna premiacao (texto, da 007) nunca foi usada pelo painel: sai, se estiver vazia em todas as campanhas.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM campanhas WHERE btrim(premiacao) <> '') THEN
    ALTER TABLE campanhas DROP COLUMN premiacao;
  ELSE
    RAISE NOTICE 'campanhas.premiacao tem texto: a coluna fica';
  END IF;
END
$$;

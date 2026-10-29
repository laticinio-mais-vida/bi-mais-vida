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

-- A premiação do formulário de antes (premiacao, texto da 007), que a tela não mostrava mais: nas campanhas de
-- 20/10/2026 do site ficou só um número ("50", "30"). Decisão do usuário: vira um prêmio único, em R$, para quem bater
-- 100% da meta; o texto continua na coluna velha. Texto que não é um número vira a descrição do prêmio, sem valor.
UPDATE campanhas
   SET premiacoes = jsonb_build_object(
         'sobre', CASE WHEN alvo_tipo = 'fixo' AND metrica <> 'preco_medio' THEN 'resultado' ELSE 'crescimento' END,
         'faixas', jsonb_build_array(CASE
           WHEN btrim(premiacao) ~ '^(R\$ ?)?[0-9]{1,7}([.,][0-9]{1,2})?$'
             THEN jsonb_build_object('pct', 100, 'premio', '', 'valor',
                                     replace(regexp_replace(btrim(premiacao), '^R\$ ?', ''), ',', '.')::numeric)
           ELSE jsonb_build_object('pct', 100, 'premio', left(btrim(premiacao), 120), 'valor', NULL) END))
 WHERE tipo = 'acao' AND btrim(premiacao) <> '';

-- Sem texto em nenhuma campanha (o painel nunca mais gravou nela), a coluna velha sai.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM campanhas WHERE btrim(premiacao) <> '') THEN
    ALTER TABLE campanhas DROP COLUMN premiacao;
  ELSE
    RAISE NOTICE 'campanhas.premiacao tem texto (convertido em premiacoes): a coluna fica';
  END IF;
END
$$;

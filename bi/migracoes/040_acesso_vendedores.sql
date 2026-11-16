-- Os vendedores que cada visualizador vê passam a ficar no cadastro dele (tela Usuários, bi/acesso.py) e valem para
-- todas as páginas, inclusive o Assistente, a API pública e a Reavaliação de Crédito. Antes, Metas tinha a lista de
-- vendedores (e as abas decidiam as equipes) e Projeções, Assistente e Gestão tinham cada uma o seu modo ("igual a
-- Metas", "todos" ou "só alguns"). As abas de Metas (visoes) continuam onde estão: são da página Metas.
--
-- escopo: {"modo": "todos"} | {"modo": "equipes", "equipes": ["ES", "BA", "EDIR"]} (os vendedores dessas equipes,
-- inclusive os que entrarem depois) | {"modo": "alguns", "vendedores": [124, 141]}. NULL: administrador (vê tudo) ou
-- visualizador ainda sem vendedores escolhidos (não vê nenhum até o administrador escolher).
ALTER TABLE usuarios ADD COLUMN escopo jsonb;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_escopo_check CHECK (
  CASE
    WHEN escopo IS NULL THEN true
    WHEN jsonb_typeof(escopo) <> 'object' THEN false
    WHEN escopo->>'modo' = 'todos' THEN true
    WHEN escopo->>'modo' = 'equipes' THEN
      CASE WHEN jsonb_typeof(escopo->'equipes') = 'array' THEN jsonb_array_length(escopo->'equipes') > 0 ELSE false END
    WHEN escopo->>'modo' = 'alguns' THEN
      CASE WHEN jsonb_typeof(escopo->'vendedores') = 'array' THEN jsonb_array_length(escopo->'vendedores') > 0 ELSE false END
    ELSE false
  END);

-- O ponto de partida é o acesso de Metas, que as outras páginas herdavam:
-- 1. com abas e lista de vendedores: só esses vendedores (lista vazia: nenhum);
-- 2. com abas e sem lista: as equipes das abas (bi/configuracao.py VISOES, em nov/26);
-- 3. sem abas (não via nenhum vendedor nas páginas que seguiam Metas): o que a pessoa escolheu nas páginas com modo
--    próprio que ela tem. Alguma em "todos" vira todos; senão, as listas de "só alguns" somadas; senão, nenhum.
WITH abas (visao, equipe) AS (
  VALUES ('es', 'ES'), ('ba', 'BA'), ('edir', 'EDIR'), ('outras_es', 'ES'),
         ('produtos_ba', 'BA'), ('produtos_ba', 'EDIR'), ('produtos_es', 'ES')
),
proprios AS (  -- os modos próprios das páginas que cada visualizador tem (NULL ou "metas" = igual a Metas)
  SELECT u.id, e.escopo->>'modo' AS modo, e.escopo->'vendedores' AS vendedores
  FROM usuarios u
  CROSS JOIN LATERAL (VALUES ('projecoes', u.escopo_projecoes), ('assistente', u.escopo_assistente),
                             ('gestao', u.escopo_gestao)) AS e (pagina, escopo)
  WHERE e.pagina = ANY (COALESCE(u.paginas, ARRAY['metas'])) AND e.escopo IS NOT NULL
)
UPDATE usuarios u SET escopo = CASE
  WHEN EXISTS (SELECT 1 FROM abas a WHERE a.visao = ANY (u.visoes)) THEN
    CASE
      WHEN u.vendedores IS NOT NULL THEN
        (SELECT jsonb_build_object('modo', 'alguns', 'vendedores', jsonb_agg(v ORDER BY v))
         FROM (SELECT DISTINCT v FROM unnest(u.vendedores) AS v) s HAVING count(*) > 0)
      ELSE
        (SELECT jsonb_build_object('modo', 'equipes',
                                   'equipes', jsonb_agg(q ORDER BY array_position(ARRAY['ES', 'BA', 'EDIR'], q)))
         FROM (SELECT DISTINCT a.equipe AS q FROM abas a WHERE a.visao = ANY (u.visoes)) s)
    END
  WHEN EXISTS (SELECT 1 FROM proprios p WHERE p.id = u.id AND p.modo = 'todos') THEN '{"modo": "todos"}'::jsonb
  ELSE
    (SELECT jsonb_build_object('modo', 'alguns', 'vendedores', jsonb_agg(v ORDER BY v))
     FROM (SELECT DISTINCT x::integer AS v
           FROM proprios p CROSS JOIN LATERAL jsonb_array_elements_text(p.vendedores) AS x
           WHERE p.id = u.id AND p.modo = 'alguns' AND jsonb_typeof(p.vendedores) = 'array') s
     HAVING count(*) > 0)
END
WHERE u.papel <> 'admin';

DO $$
DECLARE
  sem integer;
BEGIN
  SELECT count(*) INTO sem FROM usuarios WHERE papel <> 'admin' AND escopo IS NULL;
  IF sem > 0 THEN
    RAISE NOTICE '% visualizador(es) ficaram sem vendedores: escolha na tela Usuários', sem;
  END IF;
END $$;

ALTER TABLE usuarios DROP COLUMN vendedores, DROP COLUMN escopo_projecoes, DROP COLUMN escopo_assistente,
  DROP COLUMN escopo_gestao;

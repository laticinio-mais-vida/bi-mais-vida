-- O que cada visualizador vê na página Premiações, escolhido em Premiações › Configurar › Acesso por usuário
-- (bi/acesso.py definir_premiacoes): as abas e, na aba Supervisores, os quadros de quais supervisores.
--
-- premiacoes: {"abas": ["vendedores", "supervisores", "comissao"], "supervisores": ["marcos", "ronaldo", "valdirene"]}.
-- Os vendedores dentro das abas continuam sendo os do acesso (tela Usuários, coluna escopo), e o quadro de um supervisor
-- só aparece para quem vê a carteira inteira do estado dele (todos os vendedores, ou a equipe do estado inteira).
-- NULL: administrador (vê tudo) ou visualizador sem nada escolhido (não vê nenhuma aba até o administrador marcar, como
-- as abas de Metas).
ALTER TABLE usuarios ADD COLUMN premiacoes jsonb;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_premiacoes_check CHECK (
  CASE
    WHEN premiacoes IS NULL THEN true
    WHEN jsonb_typeof(premiacoes) <> 'object' THEN false
    ELSE COALESCE(jsonb_typeof(premiacoes->'abas') = 'array'
                  AND jsonb_typeof(premiacoes->'supervisores') = 'array', false)
  END);

-- Quem já tem a página continua vendo o mesmo de antes: as três abas e os três supervisores. A aba Supervisores e os
-- quadros continuam limitados pelos vendedores do acesso, como antes desta migração.
UPDATE usuarios
SET premiacoes = '{"abas": ["vendedores", "supervisores", "comissao"],
                   "supervisores": ["marcos", "ronaldo", "valdirene"]}'::jsonb
WHERE papel <> 'admin' AND 'premiacoes' = ANY (COALESCE(paginas, ARRAY['metas']));

-- Regras salvas pelos administradores (antes em config_metas.json e config_projecoes.json). Cada gravação é uma
-- versão nova, com quem salvou e quando; vale a mais recente de cada nome.
CREATE TABLE regras (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nome text NOT NULL CHECK (nome IN ('metas', 'projecoes')),
  dados jsonb NOT NULL,
  salva_em timestamptz NOT NULL DEFAULT now(),
  salva_por bigint REFERENCES usuarios ON DELETE SET NULL,
  salva_por_nome text  -- cópia: continua dizendo quem salvou depois que o usuário é excluído
);
CREATE INDEX regras_nome ON regras (nome, id DESC);

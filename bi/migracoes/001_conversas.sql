-- Histórico de conversas do Assistente. As conversas são de um login (por enquanto em usuarios.json; vira chave
-- estrangeira quando os usuários vierem para o banco). Cada pergunta acrescenta duas mensagens.

-- Para a busca não diferenciar acentos (sem depender da extensão unaccent).
CREATE FUNCTION sem_acento(t text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT translate(t, 'áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ',
                      'aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN')
$$;

CREATE TABLE conversas (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  login text NOT NULL,
  titulo text NOT NULL,
  criada_em timestamptz NOT NULL DEFAULT now(),
  atualizada_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversas_login ON conversas (login, atualizada_em DESC);

CREATE TABLE mensagens (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  conversa uuid NOT NULL REFERENCES conversas ON DELETE CASCADE,
  papel text NOT NULL CHECK (papel IN ('usuario', 'assistente')),
  texto text NOT NULL,
  detalhes jsonb NOT NULL DEFAULT '{}',  -- da resposta: consultas, passos, data_ref, aviso e uso
  criada_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mensagens_conversa ON mensagens (conversa, id);

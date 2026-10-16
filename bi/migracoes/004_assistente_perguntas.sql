-- Registro de cada pergunta ao Assistente (antes em logs/assistente-AAAA-MM.jsonl): quem, o quê, as consultas, os
-- tokens e o custo estimado. Os limites do dia e a tela "Uso e custo" saem daqui. Fica mesmo depois que o usuário
-- ou a conversa são excluídos (login e nome são cópias; a conversa não tem chave estrangeira).
CREATE TABLE assistente_perguntas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  quando timestamptz NOT NULL DEFAULT now(),
  usuario bigint REFERENCES usuarios ON DELETE SET NULL,
  login text NOT NULL,
  nome text NOT NULL,
  conversa uuid,
  escopo text,                -- o que a pessoa podia consultar ("todos os vendedores", "vendedores da equipe ES"...)
  pergunta text NOT NULL,
  resposta text,
  aviso text,
  erro text,
  parada text,                -- stop_reason da última chamada à API
  modelo text,
  entrada integer NOT NULL DEFAULT 0,        -- tokens
  saida integer NOT NULL DEFAULT 0,
  cache_leitura integer NOT NULL DEFAULT 0,
  cache_escrita integer NOT NULL DEFAULT 0,
  chamadas integer NOT NULL DEFAULT 0,
  custo numeric(12, 5) NOT NULL DEFAULT 0,   -- US$, pelos preços de [ia] no config.ini
  segundos real,
  passos jsonb NOT NULL DEFAULT '[]',        -- consultas feitas: ferramenta, argumentos, SQL, linhas, tempo, erro
  data_ref date,
  pedidos_api text[]
);
CREATE INDEX assistente_perguntas_quando ON assistente_perguntas (quando);
CREATE INDEX assistente_perguntas_usuario ON assistente_perguntas (usuario, quando);

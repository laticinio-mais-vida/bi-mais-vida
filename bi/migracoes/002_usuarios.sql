-- Usuários do painel (antes em usuarios.json). O login pode mudar: o que é da pessoa (conversas, perguntas ao
-- Assistente, versões das regras) aponta para o id.
CREATE TABLE usuarios (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  login text NOT NULL UNIQUE CHECK (login ~ '^[a-z0-9._-]{3,40}$'),
  nome text NOT NULL CHECK (nome <> ''),
  papel text NOT NULL CHECK (papel IN ('admin', 'visualizador')),
  ativo boolean NOT NULL DEFAULT true,
  senha text NOT NULL,                -- pbkdf2_sha256$iterações$sal$hash (bi/acesso.py); nunca a senha em si
  sessao integer NOT NULL DEFAULT 0,  -- sobe para derrubar as sessões abertas (senha trocada, acesso desativado)
  -- O que o visualizador vê; o administrador vê tudo e fica com paginas NULL.
  paginas text[],                     -- páginas liberadas
  visoes text[],                      -- abas de Metas
  vendedores integer[],               -- vendedores de Metas; NULL = todos os das abas
  escopo_projecoes jsonb,             -- {"modo": "metas" | "todos" | "alguns", "vendedores": [...]}; NULL = igual a Metas
  escopo_assistente jsonb,
  criado_em timestamptz NOT NULL DEFAULT now(),
  ultimo_acesso timestamptz
);

-- Valores do próprio painel. Por enquanto, o segredo que assina os cookies de sessão (criado no primeiro uso).
CREATE TABLE parametros (
  chave text PRIMARY KEY,
  valor text NOT NULL
);

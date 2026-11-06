-- API pública da Gestão (docs/api_publica.md, bi/acesso.py): a chave que outro aplicativo recebe quando a pessoa entra
-- nele com o usuário e a senha do BI. Uma por pessoa e por aplicativo: entrar de novo troca a chave da mesma linha.
-- O banco guarda só o hash SHA-256; a chave aparece uma vez, na resposta do login. Desconectar apaga a linha.
-- A chave vale até expira_em e só enquanto o contador de sessão da pessoa (usuarios.sessao) for o mesmo de quando ela
-- entrou: trocar a senha ou desativar a pessoa derruba as chaves, como derruba os cookies do site.
CREATE TABLE chaves_api (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  usuario bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,
  aplicativo text NOT NULL CHECK (char_length(aplicativo) BETWEEN 1 AND 60 AND aplicativo !~ '[[:cntrl:]]'),
  hash text NOT NULL UNIQUE CHECK (hash ~ '^[0-9a-f]{64}$'),
  sessao integer NOT NULL,                 -- usuarios.sessao na hora do login
  criada_em timestamptz NOT NULL DEFAULT now(),
  usada_em timestamptz,                    -- o último pedido (gravado no máximo a cada 5 minutos)
  expira_em timestamptz NOT NULL,
  UNIQUE (usuario, aplicativo)
);

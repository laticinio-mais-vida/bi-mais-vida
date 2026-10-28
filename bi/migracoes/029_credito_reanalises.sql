-- Reanálises de crédito (página Reavaliação de Crédito, bi/reanalise.py): quem analisa o crédito de um cliente registra
-- o limite e o prazo que liberou e a justificativa, e o painel grava junto o retrato do cliente naquele momento
-- (Credito.retrato em bi/credito.py, calculado no servidor a partir do cache). Cada registro é uma linha nova e não muda
-- depois: um engano se corrige excluindo (a linha fica, com excluida_em) e registrando de novo. Só o site grava.
CREATE TABLE credito_reanalises (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chave uuid NOT NULL UNIQUE,                -- a do formulário: o mesmo envio repetido (clique duplo) grava uma vez só
  id_cliente integer NOT NULL,
  cliente text NOT NULL,                     -- o nome na hora
  limite_antes numeric(14, 2) NOT NULL CHECK (limite_antes >= 0),  -- o cadastro do ERP no dia
  prazo_antes text,                          -- NULL = sem prazo no cadastro
  limite_pedido numeric(14, 2) NOT NULL CHECK (limite_pedido > 0),  -- o valor analisado no parecer
  limite_liberado numeric(14, 2) NOT NULL CHECK (limite_liberado >= 0),  -- 0 = cortou o crédito
  prazo_liberado text NOT NULL CHECK (prazo_liberado <> ''),  -- o nome de uma opção de pagamento do ERP
  justificativa text NOT NULL CHECK (length(justificativa) BETWEEN 1 AND 2000),
  -- A regra do parecer na hora, para o pedido e para o liberado (NULL = liberou R$ 0), e o limite que ela sugeria:
  parecer text NOT NULL CHECK (parecer IN ('indicado', 'ressalvas', 'nao_indicado')),
  parecer_liberado text CHECK (parecer_liberado IN ('indicado', 'ressalvas', 'nao_indicado')),
  limite_sugerido numeric(14, 2),
  dados_ate timestamp NOT NULL,              -- a extração do retrato (os dias de atraso contam até o dia dela)
  retrato jsonb NOT NULL,                    -- o que se sabia do cliente (o formato tem versao, dentro dele)
  feita_em timestamptz NOT NULL DEFAULT now(),
  feita_por bigint REFERENCES usuarios ON DELETE SET NULL,
  feita_por_nome text,                       -- cópia: continua dizendo quem registrou depois que o usuário é excluído
  -- Excluída por engano: some da página e do Assistente, mas fica guardada.
  excluida_em timestamptz,
  excluida_por bigint REFERENCES usuarios ON DELETE SET NULL,
  excluida_por_nome text
);
CREATE INDEX credito_reanalises_cliente ON credito_reanalises (id_cliente, id DESC);

-- A capa de análise de crédito (página Reavaliação de Crédito, botão "Capa de análise de crédito"; bi/capa_credito.py):
-- os 14 itens da capa (100 pontos), a indicação de prazo e limite pelo quadro da planilha "Classificação e Limites" e o
-- que foi concedido, com a justificativa. Serve para um cadastro novo (o cliente ainda não está no ERP: a capa fica pelo
-- CNPJ do PDF do Serasa e liga ao cliente quando o CNPJ dele chega do ERP, na leitura) e para uma reanálise (um cliente
-- do ERP). Cada capa é uma linha nova e não muda depois: um engano se corrige excluindo (a linha fica, com excluida_em).
-- Só o site grava.

-- O PDF do Serasa de um cadastro novo fica sem o código do cliente (ligado pelo CNPJ).
ALTER TABLE credito_serasa ALTER COLUMN id_cliente DROP NOT NULL;
-- O mesmo PDF sem código grava uma vez só (com código, vale o índice credito_serasa_mesmo_arquivo).
CREATE UNIQUE INDEX credito_serasa_mesmo_arquivo_sem_cliente ON credito_serasa (arquivo_sha256)
  WHERE id_cliente IS NULL AND excluido_em IS NULL;

CREATE TABLE credito_capas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chave uuid NOT NULL UNIQUE,                -- a do formulário: o mesmo envio repetido (clique duplo) grava uma vez só
  tipo text NOT NULL CHECK (tipo IN ('cadastro', 'reanalise')),
  id_cliente integer,                        -- o cliente da reanálise; no cadastro novo, vazio (liga pelo CNPJ)
  cnpj text NOT NULL CHECK (cnpj ~ '^[0-9]{14}$'),  -- só os dígitos, o do relatório do Serasa
  cliente text NOT NULL CHECK (length(cliente) BETWEEN 1 AND 200),  -- o nome (o do formulário, ou o do ERP na reanálise)
  razao_social text,                         -- a do relatório
  id_vendedor integer NOT NULL,              -- o vendedor do cliente (no cadastro novo, quem trouxe)
  vendedor text,                             -- o nome na hora
  serasa_id bigint NOT NULL REFERENCES credito_serasa,  -- o PDF lido
  porte text NOT NULL CHECK (porte IN ('A', 'B', 'C', 'D', 'E')),  -- Grande ... Pequena
  -- Cada item da capa: a opção, os pontos, se foi automático e de onde veio (o formato tem regra_versao).
  respostas jsonb NOT NULL,
  pontos smallint NOT NULL CHECK (pontos BETWEEN 0 AND 100),
  faixa smallint NOT NULL CHECK (faixa BETWEEN 0 AND 4),  -- 0 = sem faixa (menos de 40 pontos)
  -- A indicação na hora: parcelas, dias sugeridos e máximos, limites, negociação com a diretoria.
  indicacao jsonb NOT NULL,
  limite_sugerido numeric(14, 2) NOT NULL CHECK (limite_sugerido >= 0),
  limite_maximo numeric(14, 2) NOT NULL CHECK (limite_maximo >= limite_sugerido),
  limite_antes numeric(14, 2) CHECK (limite_antes >= 0),  -- reanálise: o cadastro do ERP na hora
  prazo_antes text,
  limite_concedido numeric(14, 2) NOT NULL CHECK (limite_concedido >= 0),
  prazo_concedido text NOT NULL CHECK (prazo_concedido <> ''),  -- o nome de uma opção de pagamento do ERP
  observacoes text CHECK (length(observacoes) <= 2000),
  justificativa text NOT NULL CHECK (length(justificativa) BETWEEN 1 AND 2000),
  id_cliente_historico integer,              -- o código do ERP de onde veio o histórico Mais Vida (NULL = cliente novo)
  dados_ate timestamp,                       -- a extração desse histórico Mais Vida
  regra_versao smallint NOT NULL,
  -- Reanálise registrada pelo administrador dentro do prazo mínimo entre reanálises: a regra que valia.
  bloqueio text,
  feita_em timestamptz NOT NULL DEFAULT now(),
  feita_por bigint REFERENCES usuarios ON DELETE SET NULL,
  feita_por_nome text,                       -- cópia: continua dizendo quem registrou depois que o usuário é excluído
  -- Excluída por engano: some das páginas, mas fica guardada.
  excluida_em timestamptz,
  excluida_por bigint REFERENCES usuarios ON DELETE SET NULL,
  excluida_por_nome text,
  CHECK ((tipo = 'reanalise') = (id_cliente IS NOT NULL)),
  CHECK ((tipo = 'reanalise') = (limite_antes IS NOT NULL))
);
CREATE INDEX credito_capas_cnpj ON credito_capas (cnpj, id DESC);
CREATE INDEX credito_capas_cliente ON credito_capas (id_cliente, id DESC) WHERE id_cliente IS NOT NULL;

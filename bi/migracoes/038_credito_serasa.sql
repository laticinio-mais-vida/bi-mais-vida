-- Dados do Serasa (página Reavaliação de Crédito, bi/serasa.py): quem analisa o crédito sobe o PDF do "Relato – Pessoa
-- Jurídica" de um cliente e o painel grava só a data de fundação, o score, o histórico de pagamento (títulos por faixa e
-- pontualidade em R$) e as anotações negativas. O PDF não é guardado. Cada envio é uma linha nova e não muda depois: um
-- engano se corrige excluindo (a linha fica, com excluido_em). Só o site grava.
CREATE TABLE credito_serasa (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_cliente integer NOT NULL,
  cliente text NOT NULL,                     -- o nome no painel na hora
  cnpj text NOT NULL,                        -- o do relatório
  razao_social text,                         -- a do relatório
  emitido_em timestamp NOT NULL,             -- "Emitido em" do relatório: a idade dos dados conta daqui
  arquivo_sha256 text NOT NULL CHECK (arquivo_sha256 ~ '^[0-9a-f]{64}$'),  -- o mesmo PDF de novo não grava outra vez
  fundacao date,                             -- NULL = não veio no relatório
  score integer CHECK (score BETWEEN 0 AND 1000),
  dados jsonb NOT NULL,                      -- score (probabilidade e risco), faixas, pontualidade em R$, anotações
  enviado_em timestamptz NOT NULL DEFAULT now(),
  enviado_por bigint REFERENCES usuarios ON DELETE SET NULL,
  enviado_por_nome text,                     -- cópia: continua dizendo quem enviou depois que o usuário é excluído
  -- Excluído por engano: some da página e do retrato das reanálises, mas fica guardado.
  excluido_em timestamptz,
  excluido_por bigint REFERENCES usuarios ON DELETE SET NULL,
  excluido_por_nome text
);
CREATE INDEX credito_serasa_cliente ON credito_serasa (id_cliente, emitido_em DESC, id DESC);
CREATE UNIQUE INDEX credito_serasa_mesmo_arquivo ON credito_serasa (id_cliente, arquivo_sha256) WHERE excluido_em IS NULL;

-- As regras do crédito (ConfigCredito em bi/reanalise.py: o prazo mínimo entre reanálises e a validade dos dados do
-- Serasa) ficam na tabela regras, com versões, como as das outras páginas. O CHECK do nome passa a aceitar 'credito'.
ALTER TABLE regras DROP CONSTRAINT regras_nome_check;
ALTER TABLE regras ADD CONSTRAINT regras_nome_check
  CHECK (nome IN ('metas', 'projecoes', 'sugestao', 'premiacoes', 'credito'));

-- O prazo mínimo entre reanálises: o administrador pode registrar um aumento mesmo dentro do prazo, e a reanálise guarda
-- a regra que valia. NULL = não havia bloqueio.
ALTER TABLE credito_reanalises ADD COLUMN bloqueio text;

-- Contratos de avalista (página Reavaliação de Crédito, botão "Avalista"; bi/avalista.py): o contrato de quando o
-- cliente compra num CNPJ que não está no nome dele e outra empresa (tipo pj) ou uma pessoa (tipo pf) garante o
-- pagamento. A página preenche, guarda e baixa o PDF igual ao modelo em Word. Cada contrato é uma linha; editar grava
-- por cima (sem guardar as versões antigas) e excluir só marca (a linha fica). Só o site grava.

-- Os dados da Mais Vida que saem no contrato: uma configuração só, salva pelo administrador.
ALTER TABLE regras DROP CONSTRAINT regras_nome_check;
ALTER TABLE regras ADD CONSTRAINT regras_nome_check
  CHECK (nome IN ('metas', 'projecoes', 'sugestao', 'premiacoes', 'credito', 'manejo', 'crm', 'assistente', 'avalista'));

CREATE TABLE credito_avalistas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chave uuid NOT NULL UNIQUE,                -- a do formulário: o mesmo envio repetido (clique duplo) grava uma vez só
  tipo text NOT NULL CHECK (tipo IN ('pj', 'pf')),  -- quem garante: uma empresa ou uma pessoa (o modelo do contrato)
  id_cliente integer,                        -- o cliente do ERP escolhido como compradora (vazio = digitada à mão)
  -- Cópias do que está em "dados", para a lista e a busca:
  compradora text NOT NULL CHECK (length(compradora) BETWEEN 1 AND 200),  -- a razão social
  compradora_cnpj text CHECK (compradora_cnpj ~ '^[0-9A-Z]{12}[0-9]{2}$'),  -- sem pontuação; vazio se falta ou não confere
  garantidor text CHECK (length(garantidor) <= 200),                     -- a razão social ou o nome
  garantidor_doc text CHECK (garantidor_doc ~ '^([0-9A-Z]{12}[0-9]{2}|[0-9]{11})$'),  -- o CNPJ ou o CPF, idem
  -- Tudo o que foi digitado: a compradora e quem garante (com os representantes) e a data. Pode estar pela metade.
  dados jsonb NOT NULL,
  versao integer NOT NULL DEFAULT 1,         -- sobe a cada gravação: quem edita por cima de uma versão velha é barrado
  feito_em timestamptz NOT NULL DEFAULT now(),
  feito_por bigint REFERENCES usuarios ON DELETE SET NULL,
  feito_por_nome text,                       -- cópia: continua dizendo quem fez depois que o usuário é excluído
  editado_em timestamptz,
  editado_por bigint REFERENCES usuarios ON DELETE SET NULL,
  editado_por_nome text,
  -- Excluído: some da página, mas fica guardado.
  excluido_em timestamptz,
  excluido_por bigint REFERENCES usuarios ON DELETE SET NULL,
  excluido_por_nome text
);
CREATE INDEX credito_avalistas_lista ON credito_avalistas (id DESC) WHERE excluido_em IS NULL;

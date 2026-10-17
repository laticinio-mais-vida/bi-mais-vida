-- Página Gestão: campanhas de vendas num quadro (kanban). Cada campanha é de quem a criou (os administradores veem
-- todas); o andamento de cada vendedor é calculado dos dados do ERP na hora (bi/gestao.py), nada dele fica aqui.
ALTER TABLE usuarios ADD COLUMN escopo_gestao jsonb;  -- vendedores que a pessoa pode pôr nas campanhas

CREATE TABLE campanhas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nome text NOT NULL CHECK (length(btrim(nome)) BETWEEN 1 AND 120),
  descricao text NOT NULL DEFAULT '',
  premiacao text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'planejada' CHECK (status IN ('planejada', 'andamento', 'concluida')),
  ordem integer NOT NULL DEFAULT 0,  -- posição do card na coluna
  inicio date NOT NULL,
  fim date NOT NULL,
  metrica text NOT NULL CHECK (metrica IN ('volume', 'faturamento', 'positivacao', 'mix')),
  filtros jsonb NOT NULL DEFAULT '{}',  -- produtos, linhas, categorias, grupos, ufs, segmentos
  meta_padrao numeric NOT NULL DEFAULT 0 CHECK (meta_padrao >= 0),  -- 0 = sem meta (só ranking)
  arquivada boolean NOT NULL DEFAULT false,
  rascunho uuid UNIQUE,  -- o rascunho do Assistente que virou esta campanha (clicar duas vezes não cria outra)
  criada_em timestamptz NOT NULL DEFAULT now(),
  criada_por bigint REFERENCES usuarios ON DELETE SET NULL,
  criada_por_nome text NOT NULL,  -- cópia: continua dizendo quem criou depois que o usuário é excluído
  atualizada_em timestamptz NOT NULL DEFAULT now(),
  atualizada_por_nome text,
  CHECK (fim >= inicio)
);
CREATE INDEX campanhas_dono ON campanhas (criada_por, status, ordem);

CREATE TABLE campanha_vendedores (
  campanha bigint NOT NULL REFERENCES campanhas ON DELETE CASCADE,
  id_vendedor integer NOT NULL,  -- código do vendedor no ERP
  meta numeric CHECK (meta >= 0),  -- NULL = a meta padrão da campanha; 0 = sem meta para este vendedor
  PRIMARY KEY (campanha, id_vendedor)
);

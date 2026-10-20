-- Página Gestão vira "Gestão da equipe" (bi/gestao.py): ações por vendedor numa região (base e alvo de cada um,
-- resultado congelado no fim), objetivos da região (alvo da equipe) e o histórico interno de cada vendedor. O quadro
-- kanban sai da tela: status e ordem ficam só como registro.

ALTER TABLE campanhas
  ADD COLUMN tipo text NOT NULL DEFAULT 'acao',         -- acao (por vendedor) ou objetivo (da equipe da região)
  ADD COLUMN regiao text,                               -- ES ou BA (o Edir é da BA)
  ADD COLUMN rotulo text NOT NULL DEFAULT '',           -- curto, para as etiquetas dos vendedores ("Mix")
  ADD COLUMN alvo_tipo text NOT NULL DEFAULT 'fixo',    -- fixo = meta_padrao; mais = base + meta_padrao; pct = base × (1 + meta_padrao/100)
  ADD COLUMN base_inicio date,                          -- janela da base: o mesmo tamanho da ação, logo antes do início
  ADD COLUMN base_fim date,
  ADD COLUMN encerrada_em timestamptz,                  -- encerrada pelo administrador
  ADD COLUMN encerrada_por_nome text,
  ADD COLUMN resultado_em timestamptz,                  -- quando o resultado de cada vendedor foi congelado
  ADD COLUMN versao integer NOT NULL DEFAULT 1;         -- muda a cada gravação (contas guardadas e cálculo preguiçoso)

-- As campanhas de antes não têm região nem base: ficam arquivadas (nos bancos do PC e do site não havia nenhuma).
UPDATE campanhas SET arquivada = true WHERE regiao IS NULL;

ALTER TABLE campanhas
  ADD CONSTRAINT campanhas_tipo_check CHECK (tipo IN ('acao', 'objetivo')),
  ADD CONSTRAINT campanhas_regiao_check CHECK (CASE WHEN regiao IS NULL THEN arquivada ELSE regiao IN ('ES', 'BA') END),
  ADD CONSTRAINT campanhas_rotulo_check CHECK (length(rotulo) <= 20),
  ADD CONSTRAINT campanhas_alvo_tipo_check CHECK (alvo_tipo IN ('fixo', 'mais', 'pct')),
  ADD CONSTRAINT campanhas_base_check CHECK ((base_inicio IS NULL) = (base_fim IS NULL)
      AND (base_fim IS NULL OR (base_inicio <= base_fim AND base_fim < inicio))),
  ADD CONSTRAINT campanhas_janela_check CHECK (tipo <> 'acao' OR arquivada OR base_inicio IS NOT NULL),
  ADD CONSTRAINT campanhas_objetivo_check CHECK (tipo = 'acao'
      OR (alvo_tipo = 'fixo' AND base_inicio IS NULL AND encerrada_em IS NULL AND resultado_em IS NULL));

DROP INDEX IF EXISTS campanhas_dono;
CREATE INDEX campanhas_quadro ON campanhas (regiao, tipo, fim) WHERE NOT arquivada;

ALTER TABLE campanha_vendedores
  ADD COLUMN base numeric,          -- o indicador na janela da base (percentuais em fração); NULL com base_em = sem base
  ADD COLUMN base_num numeric,
  ADD COLUMN base_den numeric,
  ADD COLUMN base_em timestamptz,   -- NULL = pendente (os dados ainda não cobrem a janela)
  ADD COLUMN resultado numeric,     -- congelado no fim (campanhas.resultado_em)
  ADD COLUMN resultado_num numeric,
  ADD COLUMN resultado_den numeric,
  ADD COLUMN parciais jsonb,        -- congeladas com o resultado: [{"semana", "ate", "valor", "num", "den"}]
  ADD COLUMN entrou_em timestamptz NOT NULL DEFAULT now();
CREATE INDEX campanha_vendedores_vendedor ON campanha_vendedores (id_vendedor);

-- Histórico interno de cada vendedor: as observações do administrador e o que aconteceu nas ações dele.
CREATE TABLE gestao_eventos (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_vendedor integer NOT NULL,     -- código do vendedor no ERP
  campanha bigint REFERENCES campanhas ON DELETE CASCADE,  -- excluir a ação apaga os eventos dela; arquivar não
  tipo text NOT NULL CONSTRAINT gestao_eventos_tipo_check
    CHECK (tipo IN ('nota', 'lancada', 'editada', 'prorrogada', 'encerrada', 'removido', 'resultado')),
  texto text NOT NULL DEFAULT '' CONSTRAINT gestao_eventos_texto_check CHECK (length(texto) <= 2000),
  dados jsonb NOT NULL DEFAULT '{}',  -- retrato do momento (base, alvo, fim, vendedores da ação, resultado...)
  criada_em timestamptz NOT NULL DEFAULT now(),
  criada_por bigint REFERENCES usuarios ON DELETE SET NULL,
  criada_por_nome text NOT NULL,      -- 'painel' nos eventos automáticos (o resultado)
  CONSTRAINT gestao_eventos_nota_check CHECK (tipo <> 'nota' OR (campanha IS NULL AND length(btrim(texto)) > 0)),
  CONSTRAINT gestao_eventos_acao_check CHECK (tipo = 'nota' OR campanha IS NOT NULL)
);
CREATE INDEX gestao_eventos_vendedor ON gestao_eventos (id_vendedor, criada_em, id);

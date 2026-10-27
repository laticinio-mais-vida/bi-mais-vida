-- Aprovação de metas (Sugestão de Metas › Configurar, bi/aprovacao.py): o administrador aprova a meta que a sugestão
-- gerou para um vendedor num mês, com o total em R$, a mussarela (ES) e os clientes editáveis, e ela passa a valer no
-- painel de Metas no lugar das linhas da METAS.xlsx e da METAS PRODUTOS.xlsx desse vendedor e mês. Cada gravação é uma
-- linha nova, como em regras: vale a última de cada vendedor × mês, e aprovada = false é a aprovação retirada.
CREATE TABLE metas_aprovadas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  mes date NOT NULL CHECK (extract(day FROM mes) = 1),  -- o mês da meta (dia 1º)
  id_vendedor integer NOT NULL,
  estado text NOT NULL CHECK (estado IN ('ES', 'BA')),
  aprovada boolean NOT NULL,
  vendedor text NOT NULL,                  -- o nome na hora (vai para o painel de Metas, como o da planilha)
  meta_fat numeric(14, 2) NOT NULL CHECK (meta_fat >= 0),
  meta_mus numeric(14, 2) NOT NULL DEFAULT 0,  -- só no ES (no BA a planilha também deixa 0)
  meta_out numeric(14, 2) NOT NULL DEFAULT 0,
  meta_cli integer NOT NULL CHECK (meta_cli >= 0),
  -- O retrato da sugestão na primeira aprovação (as edições partem dele, mesmo que a conta mude depois):
  sugerida_fat numeric(14, 2) NOT NULL,
  sugerida_mus numeric(14, 2) NOT NULL DEFAULT 0,
  clientes_carteira integer,               -- os ativos da carteira no dia (NULL = sem o histórico da carteira)
  clientes_dia date,
  -- [{id, produto, unidade, grupo, volume_sugerido, preco, meta_volume}], a meta de volume já distribuída
  produtos jsonb NOT NULL DEFAULT '[]',
  salva_em timestamptz NOT NULL DEFAULT now(),
  salva_por bigint REFERENCES usuarios ON DELETE SET NULL,
  salva_por_nome text,  -- cópia: continua dizendo quem salvou depois que o usuário é excluído
  CHECK (meta_mus >= 0 AND meta_out >= 0)
);
CREATE INDEX metas_aprovadas_chave ON metas_aprovadas (mes, id_vendedor, id DESC);

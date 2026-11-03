-- Ajustes da meta de volume na página Sugestão de Metas (bi/ajustes.py): o administrador troca a meta de volume que a
-- fórmula deu numa linha da conta (BA: vendedor × área × produto; ES: vendedor × produto) e a sugestão passa a usar o
-- número dele. Uma linha por ajuste em vigor; apagar volta para a fórmula. Se o vendedor já tem a meta aprovada no mês,
-- a mesma gravação acrescenta em metas_aprovadas a aprovação com a diferença.
CREATE TABLE sugestao_ajustes (
  mes date NOT NULL CHECK (extract(day FROM mes) = 1),  -- o mês da meta (dia 1º)
  id_vendedor integer NOT NULL,
  id_area integer NOT NULL,      -- a área atual do cliente, no BA; 0 no ES (a conta do ES junta as áreas)
  id_produto integer NOT NULL,   -- já com as equivalências das Configurações das metas
  meta_volume numeric(14, 4) NOT NULL CHECK (meta_volume >= 0),
  salva_em timestamptz NOT NULL DEFAULT now(),
  salva_por bigint REFERENCES usuarios ON DELETE SET NULL,
  salva_por_nome text,  -- cópia: continua dizendo quem salvou depois que o usuário é excluído
  PRIMARY KEY (mes, id_vendedor, id_area, id_produto)
);

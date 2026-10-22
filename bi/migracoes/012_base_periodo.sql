-- Campanhas da Gestão: a base de cada vendedor passa a ser um período fechado que o administrador escolhe (semana,
-- quinzena, mês, trimestre, semestre ou ano), o último que termina antes do início (bi/indicadores.py
-- janela_fechada), medido inteiro. NULL = as campanhas de antes: o mesmo tamanho da campanha, logo antes do início.

ALTER TABLE campanhas
  ADD COLUMN base_periodo text,
  ADD CONSTRAINT campanhas_base_periodo_check CHECK (base_periodo IN ('semana', 'quinzena', 'mes', 'trimestre',
                                                                      'semestre', 'ano')),
  ADD CONSTRAINT campanhas_base_periodo_tipo_check CHECK (tipo = 'acao' OR base_periodo IS NULL);

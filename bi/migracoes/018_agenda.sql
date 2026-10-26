-- Página Agenda (bi/agenda.py): as atividades de cada pessoa, só dela (ninguém mais vê), e o registro de cada dia em
-- que uma atividade foi concluída, com o feedback. Uma atividade repetida guarda um registro por dia: o histórico do
-- que foi feito.

CREATE TABLE agenda_atividades (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  usuario bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,  -- o dono; excluir o usuário apaga a agenda dele
  titulo text NOT NULL CONSTRAINT agenda_atividades_titulo_check CHECK (length(btrim(titulo)) BETWEEN 1 AND 120),
  descricao text NOT NULL DEFAULT '' CONSTRAINT agenda_atividades_descricao_check CHECK (length(descricao) <= 2000),
  inicio date NOT NULL,             -- o dia da atividade única; o primeiro dia da repetida
  repeticao text NOT NULL DEFAULT 'nenhuma' CONSTRAINT agenda_atividades_repeticao_check
    CHECK (repeticao IN ('nenhuma', 'diaria', 'semanal', 'mensal', 'intervalo')),
  dias_semana smallint[],           -- semanal: 1 = segunda ... 7 = domingo
  dia_mes smallint,                 -- mensal: o mês sem esse dia usa o último
  intervalo smallint,               -- a cada N dias, contando do início
  so_dias_uteis boolean NOT NULL DEFAULT false,  -- diária: pula domingos, feriados e sábados sem expediente
  regiao text,                      -- o calendário dos dias úteis (ES ou BA, bi/calendario.py)
  fim date,                         -- repetida: o último dia (NULL = sem fim)
  exige_feedback boolean NOT NULL DEFAULT false,  -- concluir pede um feedback
  criada_em timestamptz NOT NULL DEFAULT now(),
  atualizada_em timestamptz NOT NULL DEFAULT now(),
  -- coalesce: um campo nulo deixaria a conta nula, e o CHECK nulo passa
  CONSTRAINT agenda_atividades_tipo_check CHECK (coalesce(CASE repeticao
    WHEN 'semanal' THEN cardinality(dias_semana) > 0 AND dias_semana <@ '{1,2,3,4,5,6,7}'::smallint[]
                        AND dia_mes IS NULL AND intervalo IS NULL
    WHEN 'mensal' THEN dia_mes BETWEEN 1 AND 31 AND dias_semana IS NULL AND intervalo IS NULL
    WHEN 'intervalo' THEN intervalo BETWEEN 2 AND 365 AND dias_semana IS NULL AND dia_mes IS NULL
    ELSE dias_semana IS NULL AND dia_mes IS NULL AND intervalo IS NULL END, false)),
  CONSTRAINT agenda_atividades_uteis_check CHECK (coalesce(CASE WHEN so_dias_uteis
    THEN repeticao = 'diaria' AND regiao IN ('ES', 'BA') ELSE regiao IS NULL END, false)),
  CONSTRAINT agenda_atividades_fim_check CHECK (fim IS NULL OR (repeticao <> 'nenhuma' AND fim >= inicio))
);
CREATE INDEX agenda_atividades_usuario ON agenda_atividades (usuario, inicio);

-- Cada dia concluído de uma atividade (a repetida tem um por dia; a única, no máximo um).
CREATE TABLE agenda_registros (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  atividade bigint NOT NULL REFERENCES agenda_atividades ON DELETE CASCADE,
  dia date NOT NULL,
  feedback text NOT NULL DEFAULT '' CONSTRAINT agenda_registros_feedback_check CHECK (length(feedback) <= 2000),
  concluida_em timestamptz NOT NULL DEFAULT now(),
  editada_em timestamptz,           -- o feedback mudou depois de concluir
  CONSTRAINT agenda_registros_dia_unico UNIQUE (atividade, dia)
);

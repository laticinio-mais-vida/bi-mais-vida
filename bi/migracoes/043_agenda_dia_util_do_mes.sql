-- Atividade mensal num dia útil do mês (bi/agenda.py): dia_util conta os dias úteis do calendário da região (ES ou
-- BA, bi/calendario.py) do começo do mês (1 = o primeiro dia útil, 2 = o segundo...) ou do fim (-1 = o último dia
-- útil, -5 = faltando 5 dias úteis para acabar o mês, contando o próprio dia). A mensal usa ou o dia fixo (dia_mes) ou
-- o dia útil (dia_util, com so_dias_uteis e a regiao).

ALTER TABLE agenda_atividades ADD COLUMN dia_util smallint;

ALTER TABLE agenda_atividades DROP CONSTRAINT agenda_atividades_tipo_check;
ALTER TABLE agenda_atividades ADD CONSTRAINT agenda_atividades_tipo_check CHECK (coalesce(CASE repeticao
    WHEN 'semanal' THEN cardinality(dias_semana) > 0 AND dias_semana <@ '{1,2,3,4,5,6,7}'::smallint[]
                        AND dia_mes IS NULL AND dia_util IS NULL AND intervalo IS NULL
    WHEN 'mensal' THEN dias_semana IS NULL AND intervalo IS NULL
                       AND ((dia_mes BETWEEN 1 AND 31 AND dia_util IS NULL)
                            OR (dia_mes IS NULL AND dia_util BETWEEN -23 AND 23 AND dia_util <> 0 AND so_dias_uteis))
    WHEN 'intervalo' THEN intervalo BETWEEN 2 AND 365 AND dias_semana IS NULL AND dia_mes IS NULL AND dia_util IS NULL
    ELSE dias_semana IS NULL AND dia_mes IS NULL AND dia_util IS NULL AND intervalo IS NULL END, false));

ALTER TABLE agenda_atividades DROP CONSTRAINT agenda_atividades_uteis_check;
ALTER TABLE agenda_atividades ADD CONSTRAINT agenda_atividades_uteis_check CHECK (coalesce(CASE WHEN so_dias_uteis
    THEN (repeticao = 'diaria' OR (repeticao = 'mensal' AND dia_util IS NOT NULL)) AND regiao IN ('ES', 'BA')
    ELSE regiao IS NULL END, false));

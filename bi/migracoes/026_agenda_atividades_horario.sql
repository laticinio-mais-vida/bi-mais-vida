-- Agenda (bi/agenda.py): o horário da atividade ganha o fim (opcional) e pode ficar ocupado: ninguém marca outra
-- coisa para a pessoa nesse horário, nem ela (outra atividade), nem quem cria tarefas (tarefa ou subtarefa com horário
-- dentro dele); bi/agenda.py confere. A atividade única passa a aceitar o último dia: com ele, aparece em todos os
-- dias do início ao fim (vários dias).

ALTER TABLE agenda_atividades
  ADD COLUMN hora_fim time,                           -- NULL = só o começo (hora)
  ADD COLUMN ocupado boolean NOT NULL DEFAULT false,  -- trava o horário da pessoa, de hora a hora_fim
  ADD CONSTRAINT agenda_atividades_hora_fim_check CHECK (hora_fim IS NULL OR (hora IS NOT NULL AND hora_fim > hora)),
  ADD CONSTRAINT agenda_atividades_ocupado_check CHECK (NOT ocupado OR hora_fim IS NOT NULL);

ALTER TABLE agenda_atividades DROP CONSTRAINT agenda_atividades_fim_check;
ALTER TABLE agenda_atividades ADD CONSTRAINT agenda_atividades_fim_check CHECK (fim IS NULL OR fim >= inicio);

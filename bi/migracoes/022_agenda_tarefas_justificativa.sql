-- Agenda (bi/tarefas.py): a justificativa do atraso. Quando a tarefa ou a subtarefa passa do dia do prazo sem ser
-- concluída (ou é concluída depois dele), quem responde por ela conta por que atrasou: na tarefa, quem criou; na
-- subtarefa, o responsável. Todos da tarefa veem. Vazia = sem justificativa.

ALTER TABLE agenda_tarefas
  ADD COLUMN justificativa text NOT NULL DEFAULT ''
    CONSTRAINT agenda_tarefas_justificativa_check CHECK (length(justificativa) <= 2000),
  ADD COLUMN justificada_em timestamptz;

ALTER TABLE agenda_subtarefas
  ADD COLUMN justificativa text NOT NULL DEFAULT ''
    CONSTRAINT agenda_subtarefas_justificativa_check CHECK (length(justificativa) <= 2000),
  ADD COLUMN justificada_em timestamptz,
  ADD COLUMN justificada_por bigint REFERENCES usuarios ON DELETE SET NULL;  -- quem era o responsável quando justificou

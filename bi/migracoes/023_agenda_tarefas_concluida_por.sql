-- Agenda (bi/tarefas.py): qualquer pessoa da tarefa muda a situação dela (A fazer, Fazendo, Concluída), não só quem
-- criou. concluida_por guarda quem concluiu, como na subtarefa (as concluídas antes desta migração ficam sem).

ALTER TABLE agenda_tarefas
  ADD COLUMN concluida_por bigint REFERENCES usuarios ON DELETE SET NULL,
  ADD CONSTRAINT agenda_tarefas_conclusao_check CHECK (concluida_por IS NULL OR concluida_em IS NOT NULL);

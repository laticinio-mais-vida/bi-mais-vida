-- Agenda (bi/tarefas.py): o título da subtarefa aceita um texto longo, até 2000 caracteres, como a descrição (antes,
-- 120). No formulário da tarefa ele é o único texto da subtarefa. Nas mensagens e nos avisos do sino, vai cortado.
-- O título da tarefa e o da atividade continuam com até 120.
ALTER TABLE agenda_subtarefas DROP CONSTRAINT agenda_subtarefas_titulo_check;
ALTER TABLE agenda_subtarefas ADD CONSTRAINT agenda_subtarefas_titulo_check
  CHECK (length(btrim(titulo)) BETWEEN 1 AND 2000);

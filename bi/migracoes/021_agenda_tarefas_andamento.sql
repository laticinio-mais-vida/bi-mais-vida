-- Agenda (bi/tarefas.py): o quadro (kanban) das tarefas, com as colunas A fazer, Fazendo e Concluída. A tarefa e a
-- subtarefa ganham iniciada_em: preenchida, está sendo feita (Fazendo); vazia, a fazer. A conclusão continua em
-- concluida_em, que manda: concluída é concluída, tenha começado ou não. Quem criou muda a tarefa de coluna; a
-- subtarefa, o responsável ou quem criou.

ALTER TABLE agenda_tarefas ADD COLUMN iniciada_em timestamptz;
ALTER TABLE agenda_subtarefas ADD COLUMN iniciada_em timestamptz;

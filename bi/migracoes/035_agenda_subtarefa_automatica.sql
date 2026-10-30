-- Agenda (bi/tarefas.py): a subtarefa automática. Quem entra numa tarefa com autonomia (ou ganha a autonomia depois)
-- recebe uma subtarefa pedindo que crie as próprias subtarefas, para programar a execução. Ela aparece em dois dias, o
-- dia em que a pessoa entrou (inicio) e o seguinte de segunda a sexta (prazo), e é uma só: concluída num dos dias, fica
-- feita nos dois. Tirada a autonomia (ou a pessoa), ela sai. As outras subtarefas ficam com inicio vazio: só no dia do
-- prazo.

ALTER TABLE agenda_subtarefas
  ADD COLUMN automatica boolean NOT NULL DEFAULT false,
  ADD COLUMN inicio date,                              -- o outro dia em que aparece (NULL = só o dia do prazo)
  ADD CONSTRAINT agenda_subtarefas_inicio_check CHECK (inicio IS NULL OR inicio <= prazo);

-- uma automática por pessoa em cada tarefa
CREATE UNIQUE INDEX agenda_subtarefas_automatica ON agenda_subtarefas (tarefa, responsavel) WHERE automatica;

-- Agenda (bi/tarefas.py): a justificativa do atraso vira um histórico. Vencida e ainda aberta, a tarefa (quem criou) ou
-- a subtarefa (o responsável) precisa de uma justificativa do prazo de agora com menos de 24 horas; enquanto não tem,
-- o painel de quem responde por ela fica bloqueado. Cada justificativa guarda o prazo que tinha vencido: prorrogado o
-- prazo, as de antes não valem para o novo. As que já existiam entram no histórico, com o prazo de agora, e as colunas
-- saem de tarefas e subtarefas.

CREATE TABLE agenda_justificativas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tarefa bigint NOT NULL REFERENCES agenda_tarefas ON DELETE CASCADE,
  subtarefa bigint REFERENCES agenda_subtarefas ON DELETE CASCADE,  -- NULL = a justificativa da tarefa
  usuario bigint REFERENCES usuarios ON DELETE SET NULL,             -- quem escreveu
  prazo date NOT NULL,                                               -- o prazo que tinha vencido
  hora time,
  texto text NOT NULL CONSTRAINT agenda_justificativas_texto_check CHECK (length(btrim(texto)) BETWEEN 1 AND 2000),
  criada_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agenda_justificativas_item ON agenda_justificativas (tarefa, subtarefa, criada_em);

INSERT INTO agenda_justificativas (tarefa, subtarefa, usuario, prazo, hora, texto, criada_em)
SELECT id, NULL, criador, prazo, hora, justificativa, coalesce(justificada_em, now())
FROM agenda_tarefas WHERE justificativa <> ''
UNION ALL
SELECT tarefa, id, coalesce(justificada_por, responsavel), prazo, hora, justificativa, coalesce(justificada_em, now())
FROM agenda_subtarefas WHERE justificativa <> '';

ALTER TABLE agenda_tarefas DROP COLUMN justificativa, DROP COLUMN justificada_em;
ALTER TABLE agenda_subtarefas DROP COLUMN justificativa, DROP COLUMN justificada_em, DROP COLUMN justificada_por;

-- Atividade com outras pessoas (bi/agenda.py), como as pessoas da tarefa: quem cria (agenda_atividades.usuario)
-- escolhe quem faz, com ou sem autonomia, e pode ficar de fora. Cada pessoa que faz tem o próprio check e o próprio
-- feedback em cada dia (agenda_registros.usuario); quem criou também marca no lugar de quem faz (concluida_por).
-- As atividades de antes ficam como estavam: quem criou é quem faz, e cada registro é dele.

CREATE TABLE agenda_atividade_pessoas (
  atividade bigint NOT NULL REFERENCES agenda_atividades ON DELETE CASCADE,
  usuario bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,
  autonomia boolean NOT NULL DEFAULT false,  -- edita a atividade (o título, a descrição, os dias e o horário)
  desde date,  -- entrou depois do começo: os dias de antes não são dela (NULL = desde o começo da atividade)
  PRIMARY KEY (atividade, usuario)
);
CREATE INDEX agenda_atividade_pessoas_usuario ON agenda_atividade_pessoas (usuario);
INSERT INTO agenda_atividade_pessoas (atividade, usuario) SELECT id, usuario FROM agenda_atividades;

-- O dia feito é de uma pessoa; quem tira a pessoa da atividade não apaga o que ela fez (volta se ela voltar).
ALTER TABLE agenda_registros ADD COLUMN usuario bigint REFERENCES usuarios ON DELETE CASCADE;
ALTER TABLE agenda_registros ADD COLUMN concluida_por bigint REFERENCES usuarios ON DELETE SET NULL;
UPDATE agenda_registros r SET usuario = a.usuario, concluida_por = a.usuario FROM agenda_atividades a
 WHERE a.id = r.atividade;
ALTER TABLE agenda_registros ALTER COLUMN usuario SET NOT NULL;
ALTER TABLE agenda_registros DROP CONSTRAINT agenda_registros_dia_unico;
ALTER TABLE agenda_registros ADD CONSTRAINT agenda_registros_dia_unico UNIQUE (atividade, usuario, dia);

-- O sino também avisa das atividades: a notificação leva a atividade (excluída, o aviso sai junto) e o dia em que a
-- agenda abre ao clicar.
ALTER TABLE notificacoes ADD COLUMN atividade bigint REFERENCES agenda_atividades ON DELETE CASCADE;
ALTER TABLE notificacoes ADD COLUMN dia date;

-- Agenda (bi/agenda.py): o horário da atividade, opcional, e as propostas do Assistente que a pessoa já confirmou.
-- O Assistente nunca grava na agenda: ele propõe (criar, editar, encerrar, excluir ou concluir uma atividade), a
-- resposta mostra o botão e o clique aplica a proposta. A tabela guarda as aplicadas, para o mesmo botão não aplicar
-- duas vezes (clique repetido, a conversa aberta em outra aba) e para a conversa mostrar o que já foi feito.

ALTER TABLE agenda_atividades ADD COLUMN hora time;  -- NULL = sem horário

CREATE TABLE agenda_propostas (
  id uuid PRIMARY KEY,              -- o id da proposta na resposta do Assistente (mensagens.detalhes, "agenda")
  usuario bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,
  acao text NOT NULL CONSTRAINT agenda_propostas_acao_check
    CHECK (acao IN ('criar', 'editar', 'encerrar', 'excluir', 'concluir')),
  atividade bigint,                 -- a atividade criada ou mexida (sem chave estrangeira: ela pode ser excluída)
  aplicada_em timestamptz NOT NULL DEFAULT now()
);

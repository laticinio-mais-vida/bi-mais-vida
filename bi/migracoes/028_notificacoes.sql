-- Notificações do painel (bi/notificacoes.py): o sino no topo, para quem tem a página Gestão, com o que acontece nas
-- tarefas da agenda. Uma linha por aviso e por pessoa. Os avisos de ação (incluído numa tarefa, subtarefa nova, prazo
-- mudado, concluída, justificativa enviada) entram junto com a ação; os de prazo (vence em breve, venceu) nascem quando
-- o painel de quem recebe pergunta, uma vez só por item e por prazo (chave). Ficam 90 dias.

CREATE TABLE notificacoes (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  usuario bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,  -- quem recebe
  tipo text NOT NULL CONSTRAINT notificacoes_tipo_check CHECK (tipo IN ('incluido', 'subtarefa_nova', 'prazo_mudou',
                                                                       'vence_em_breve', 'venceu', 'concluida',
                                                                       'justificativa')),
  tarefa bigint REFERENCES agenda_tarefas ON DELETE CASCADE,     -- excluída a tarefa, os avisos dela saem junto
  subtarefa bigint REFERENCES agenda_subtarefas ON DELETE CASCADE,
  autor bigint REFERENCES usuarios ON DELETE SET NULL,           -- quem fez (NULL nos de prazo: é o painel que avisa)
  texto text NOT NULL,                                           -- pronto para mostrar
  chave text,                                                    -- os de prazo: uma vez só por item e prazo
  criada_em timestamptz NOT NULL DEFAULT now(),
  lida_em timestamptz,
  CONSTRAINT notificacoes_chave_unica UNIQUE (usuario, chave)
);
CREATE INDEX notificacoes_usuario ON notificacoes (usuario, criada_em DESC);

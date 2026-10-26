-- Agenda (bi/tarefas.py): tarefas com prazo (dia e horário opcional), que quem cria divide em subtarefas para outras
-- pessoas, cada uma com o próprio prazo. Diferente das atividades (só da pessoa), a tarefa é vista por quem criou e
-- pelos participantes. Só quem criou edita a tarefa e muda prazos; com autonomia, o participante edita o texto das
-- próprias subtarefas e cria subtarefas para si.

CREATE TABLE agenda_tarefas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  criador bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,  -- excluir o usuário apaga as tarefas que ele criou
  titulo text NOT NULL CONSTRAINT agenda_tarefas_titulo_check CHECK (length(btrim(titulo)) BETWEEN 1 AND 120),
  descricao text NOT NULL DEFAULT '' CONSTRAINT agenda_tarefas_descricao_check CHECK (length(descricao) <= 2000),
  prazo date NOT NULL,
  hora time,                        -- o horário do prazo (NULL = o dia todo)
  concluida_em timestamptz,         -- só quem criou conclui
  versao integer NOT NULL DEFAULT 1,  -- muda a cada edição (tarefa, pessoas, subtarefas): o Salvar não grava por cima
  criada_em timestamptz NOT NULL DEFAULT now(),
  atualizada_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agenda_tarefas_criador ON agenda_tarefas (criador);

-- Quem vê a tarefa: quem criou (a autonomia não se aplica) e os participantes.
CREATE TABLE agenda_tarefa_pessoas (
  tarefa bigint NOT NULL REFERENCES agenda_tarefas ON DELETE CASCADE,
  usuario bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,
  autonomia boolean NOT NULL DEFAULT false,  -- edita título e descrição das próprias subtarefas e cria subtarefas para si
  PRIMARY KEY (tarefa, usuario)
);
CREATE INDEX agenda_tarefa_pessoas_usuario ON agenda_tarefa_pessoas (usuario);

CREATE TABLE agenda_subtarefas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tarefa bigint NOT NULL REFERENCES agenda_tarefas ON DELETE CASCADE,
  responsavel bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,  -- excluir o usuário leva as subtarefas dele
  titulo text NOT NULL CONSTRAINT agenda_subtarefas_titulo_check CHECK (length(btrim(titulo)) BETWEEN 1 AND 120),
  descricao text NOT NULL DEFAULT '' CONSTRAINT agenda_subtarefas_descricao_check CHECK (length(descricao) <= 2000),
  prazo date NOT NULL,              -- até o prazo da tarefa (bi/tarefas.py confere)
  hora time,
  concluida_em timestamptz,
  concluida_por bigint REFERENCES usuarios ON DELETE SET NULL,
  criada_por bigint REFERENCES usuarios ON DELETE SET NULL,
  criada_em timestamptz NOT NULL DEFAULT now(),
  atualizada_em timestamptz NOT NULL DEFAULT now(),
  -- o responsável é uma das pessoas da tarefa. Sem ON DELETE (conferido no fim do comando): tirar da tarefa quem
  -- ainda tem subtarefa dá erro, e excluir o usuário funciona (as subtarefas dele saem pela coluna responsavel)
  CONSTRAINT agenda_subtarefas_pessoa_fk FOREIGN KEY (tarefa, responsavel)
    REFERENCES agenda_tarefa_pessoas (tarefa, usuario),
  CONSTRAINT agenda_subtarefas_conclusao_check CHECK (concluida_por IS NULL OR concluida_em IS NOT NULL)
);
CREATE INDEX agenda_subtarefas_tarefa ON agenda_subtarefas (tarefa, responsavel);
CREATE INDEX agenda_subtarefas_responsavel ON agenda_subtarefas (responsavel, prazo);

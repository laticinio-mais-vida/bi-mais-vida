-- Google Agenda, só leitura (bi/google_agenda.py): as agendas do Google que cada pessoa conectou pelo endereço secreto
-- no formato iCal e os eventos lidos delas, com as repetições já abertas (uma linha por ocorrência). O BI nunca escreve
-- no Google. Cada leitura troca todos os eventos da agenda numa transação; o arquivo igual ao da última leitura não
-- regrava nada.

CREATE TABLE google_agendas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  usuario bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,  -- o dono; excluir o usuário apaga as agendas dele
  calendario text NOT NULL,         -- o id da agenda no Google, tirado do endereço (na principal, o e-mail)
  nome text NOT NULL CONSTRAINT google_agendas_nome_check CHECK (length(btrim(nome)) BETWEEN 1 AND 120),
  endereco text NOT NULL,           -- o endereço secreto, cifrado: não volta para a página nem vai para o log
  conteudo text,                    -- a assinatura do arquivo da última leitura (sem as linhas DTSTAMP)
  lida_em timestamptz,              -- a última leitura que deu certo
  tentativa_em timestamptz,         -- a última tentativa, reservada antes de baixar
  erro text,                        -- o motivo da última falha (NULL: a última deu certo)
  trocar boolean NOT NULL DEFAULT false,  -- o endereço morreu (redefinido no Google): a pessoa cola outro
  falhas smallint NOT NULL DEFAULT 0,     -- falhas seguidas: espaçam as tentativas
  criada_em timestamptz NOT NULL DEFAULT now(),
  -- colar o endereço novo da mesma agenda (depois de "Redefinir" no Google) troca o antigo nesta linha
  CONSTRAINT google_agendas_unica UNIQUE (usuario, calendario)
);

CREATE TABLE google_eventos (
  agenda bigint NOT NULL REFERENCES google_agendas ON DELETE CASCADE,
  titulo text NOT NULL CONSTRAINT google_eventos_titulo_check CHECK (length(titulo) BETWEEN 1 AND 120),
  inicio timestamptz NOT NULL,
  fim timestamptz NOT NULL,         -- o dia inteiro vai da meia-noite do primeiro dia à seguinte ao último
  dia_inteiro boolean NOT NULL,
  ocupado boolean NOT NULL,         -- "Mostrar como: Ocupado" no Google: trava a pessoa para as tarefas dos outros
  CONSTRAINT google_eventos_fim_check CHECK (fim >= inicio)
);
CREATE INDEX google_eventos_agenda ON google_eventos (agenda, inicio);

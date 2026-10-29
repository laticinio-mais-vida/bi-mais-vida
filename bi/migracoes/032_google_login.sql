-- Google Agenda pelo login com o Google (bi/google_agenda.py), no lugar do endereço secreto no formato iCal (031): cada
-- pessoa entra com a conta Google dela, o BI guarda a autorização de só leitura (cifrada) e lê as agendas que ela
-- ligar. Os endereços colados não servem para a leitura nova: as agendas conectadas por eles saem (com os eventos).

CREATE TABLE google_contas (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  usuario bigint NOT NULL REFERENCES usuarios ON DELETE CASCADE,  -- o dono; excluir o usuário apaga as contas dele
  email text NOT NULL CONSTRAINT google_contas_email_check CHECK (length(email) BETWEEN 3 AND 320),  -- a conta Google
  token text NOT NULL,              -- a autorização de só leitura (refresh token), cifrada: não volta para a página
  erro text,                        -- o motivo da última falha da conta (NULL: tudo certo)
  trocar boolean NOT NULL DEFAULT false,  -- a autorização caiu: a pessoa entra com o Google de novo
  criada_em timestamptz NOT NULL DEFAULT now(),
  -- entrar de novo com a mesma conta troca a autorização nesta linha
  CONSTRAINT google_contas_unica UNIQUE (usuario, email)
);

DELETE FROM google_agendas;
ALTER TABLE google_agendas
  DROP CONSTRAINT google_agendas_unica,
  DROP COLUMN endereco,
  -- a conta de onde a agenda vem; desconectar a conta apaga as agendas dela
  ADD COLUMN conta bigint NOT NULL REFERENCES google_contas ON DELETE CASCADE,
  ADD COLUMN principal boolean NOT NULL DEFAULT false,  -- a agenda principal da conta
  ADD COLUMN ligada boolean NOT NULL DEFAULT false,     -- aparece no BI (só as ligadas são lidas)
  ADD CONSTRAINT google_agendas_unica UNIQUE (conta, calendario);
-- As outras colunas ficam, com sentidos novos: calendario é o id da agenda no Google (na principal, o e-mail da conta),
-- conteudo a assinatura dos eventos da última leitura e trocar diz que a agenda não abre mais (saiu da conta no Google).

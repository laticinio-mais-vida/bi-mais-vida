-- As conversas passam a ser do usuário (id), e não mais de um login em texto: trocar o login leva as conversas
-- junto e excluir o usuário apaga as dele, pelo próprio banco.
ALTER TABLE conversas ADD COLUMN usuario bigint;
UPDATE conversas c SET usuario = u.id FROM usuarios u WHERE u.login = c.login;

DO $$
DECLARE
  apagadas integer;
BEGIN
  -- Sem nenhum usuário, o usuarios.json não foi importado (não estava na pasta do painel): apagar as conversas
  -- "sem dono" seria apagar todas.
  IF EXISTS (SELECT 1 FROM conversas) AND NOT EXISTS (SELECT 1 FROM usuarios) THEN
    RAISE EXCEPTION 'há conversas do Assistente, mas nenhum usuário foi importado: confira se o usuarios.json está na pasta do painel';
  END IF;
  DELETE FROM conversas WHERE usuario IS NULL;  -- de logins que já não existiam
  GET DIAGNOSTICS apagadas = ROW_COUNT;
  IF apagadas > 0 THEN
    RAISE NOTICE '% conversas de logins que não existem mais foram apagadas', apagadas;
  END IF;
END $$;

ALTER TABLE conversas
  ALTER COLUMN usuario SET NOT NULL,
  ADD CONSTRAINT conversas_usuario_fkey FOREIGN KEY (usuario) REFERENCES usuarios ON DELETE CASCADE;
DROP INDEX conversas_login;
ALTER TABLE conversas DROP COLUMN login;
CREATE INDEX conversas_usuario ON conversas (usuario, atualizada_em DESC);

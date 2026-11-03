-- Notificações (bi/notificacoes.py): excluir do sino. A excluída some da lista e do número, mas a linha fica até a
-- limpeza dos 90 dias: os avisos de prazo saem uma vez só por item e prazo (chave), e apagar a linha faria o mesmo
-- aviso voltar no minuto seguinte.

ALTER TABLE notificacoes ADD COLUMN excluida_em timestamptz;  -- NULL = no sino

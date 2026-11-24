-- Editar uma capa de análise de crédito (bi/capa_credito.py). A edição grava uma versão nova (uma linha nova), e a de
-- antes fica guardada, marcada como substituída: some das páginas, mas o histórico das edições continua no banco. A
-- versão nova repete quando e por quem a capa foi registrada (feita_em/por, os da primeira versão: o prazo mínimo entre
-- reanálises continua contando dali) e guarda quando e por quem foi editada.
ALTER TABLE credito_capas ADD COLUMN versao_anterior bigint REFERENCES credito_capas;  -- a versão que esta substitui
ALTER TABLE credito_capas ADD COLUMN substituida_em timestamptz;  -- editada: a versão nova é outra linha
ALTER TABLE credito_capas ADD COLUMN editada_em timestamptz;
ALTER TABLE credito_capas ADD COLUMN editada_por bigint REFERENCES usuarios ON DELETE SET NULL;
ALTER TABLE credito_capas ADD COLUMN editada_por_nome text;  -- cópia: continua dizendo quem editou depois que o usuário sai
-- Cada versão é substituída por uma só.
CREATE UNIQUE INDEX credito_capas_versao_anterior ON credito_capas (versao_anterior) WHERE versao_anterior IS NOT NULL;

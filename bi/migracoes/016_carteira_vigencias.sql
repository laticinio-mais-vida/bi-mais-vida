-- Histórico da carteira (bi/carteira.py), para a cobertura da positivação nas campanhas: o ERP não guarda quando um
-- cliente foi inativado nem quando trocou de vendedor. A cada extração, o painel compara os clientes ativos
-- (INATIVO = 0) com os trechos abertos e grava só o que mudou (pedido do usuário): cada trecho diz de quem era a
-- carteira e de quando até quando valeu. Reativação abre um trecho novo; nada é apagado nem sobrescrito.
CREATE TABLE clientes_vigencias (
    id_cliente integer NOT NULL,
    de date NOT NULL,
    ate date,                                -- NULL = ainda vale
    id_vendedor integer,                     -- o vendedor da carteira (NULL = sem vendedor)
    bloqueado boolean NOT NULL DEFAULT false, -- "PEDIDO BLOQUEADO" no nome (fica fora da base, como na efetividade)
    uf text,
    id_area integer,
    area text,
    segmento text,
    PRIMARY KEY (id_cliente, de),
    CHECK (ate IS NULL OR ate >= de)
);
CREATE UNIQUE INDEX clientes_vigencias_aberta ON clientes_vigencias (id_cliente) WHERE ate IS NULL;

-- Cada dia conferido: desde quando há histórico e o resumo de quem entrou, saiu ou trocou de vendedor.
CREATE TABLE carteira_retratos (
    data date PRIMARY KEY,
    ativos integer NOT NULL,
    entradas integer NOT NULL DEFAULT 0,
    saidas integer NOT NULL DEFAULT 0,
    trocas integer NOT NULL DEFAULT 0,
    origem text NOT NULL DEFAULT 'extracao',  -- extracao ou semeadura (os retratos de antes, de 15/09 e 19/10/2026)
    em timestamptz NOT NULL DEFAULT now()
);

-- A cobertura da positivação de cada vendedor (os atendidos da base ÷ os ativos da base, mês a mês) na base e no
-- resultado congelado: {"atendidos", "ativos", "pct", "meses": [{"mes", "fonte", "atendidos", "ativos", "pct"}],
-- "falta": [...]}. NULL = ainda não medida (a base de antes da 016 mede só a cobertura na próxima leitura).
ALTER TABLE campanha_vendedores
  ADD COLUMN base_cobertura jsonb,
  ADD COLUMN resultado_cobertura jsonb;

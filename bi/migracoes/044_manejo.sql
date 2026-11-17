-- Manejo da Base (página Manejo da Base, bi/manejo.py), só no site: o painel sugere passar para a central o cliente que
-- parou de comprar e inativar o inadimplente e o cliente da central que não compra. Quem pode justificar responde até o
-- prazo da lista do mês; depois o administrador dá o veredito. Nada é apagado: cada justificativa e cada veredito é uma
-- linha nova em manejo_eventos.

-- A lista de cada mês e o prazo dela (o último dia para justificar, até o fim do dia). Enquanto a lista está aberta, o
-- prazo acompanha o calendário dos dias úteis; depois que passa, fica como está.
CREATE TABLE manejo_rodadas (
  mes date PRIMARY KEY CONSTRAINT manejo_rodadas_mes_check CHECK (extract(day FROM mes) = 1),  -- o mês do prazo
  prazo date NOT NULL,
  criada_em timestamptz NOT NULL DEFAULT now()
);

-- Uma linha por mês × cliente × lista. Um cliente tem no máximo uma sugestão em andamento (encerrada_em vazio): a
-- justificar, justificada, esperando o veredito ou esperando o ERP.
CREATE TABLE manejo_sugestoes (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  mes date NOT NULL REFERENCES manejo_rodadas,
  id_cliente integer NOT NULL,
  cliente text NOT NULL,                         -- o nome na hora
  sugestao text NOT NULL CONSTRAINT manejo_sugestoes_sugestao_check CHECK (sugestao IN ('central', 'inativar')),
  id_vendedor integer NOT NULL,                  -- quem vê a linha: acompanha a carteira enquanto não há veredito
  vendedor text NOT NULL,
  id_vendedor_entrada integer NOT NULL,          -- o vendedor de quando o cliente entrou na lista
  entrou_em date NOT NULL,                       -- o dia da cópia do ERP em que entrou
  retrato jsonb NOT NULL,                        -- os números do dia da entrada (o formato tem versao, dentro dele)
  fatos jsonb NOT NULL,                          -- os da última atualização; param de mudar quando a linha encerra
  dados_ate timestamp NOT NULL,                  -- a extração dos fatos
  encerrada_em date,                             -- vazio = em andamento
  -- comprou, pagou, na_central, inativado, fora_da_regra e outra_sugestao: o cliente saiu da regra antes do veredito;
  -- mantido: o veredito foi continuar; aplicado: o veredito foi seguir e o ERP já mostra a mudança.
  encerrada_motivo text CONSTRAINT manejo_sugestoes_motivo_check CHECK (encerrada_motivo IN
    ('comprou', 'pagou', 'na_central', 'inativado', 'fora_da_regra', 'outra_sugestao', 'mantido', 'aplicado')),
  criada_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT manejo_sugestoes_unica UNIQUE (mes, id_cliente, sugestao),
  CONSTRAINT manejo_sugestoes_encerrada_check CHECK ((encerrada_em IS NULL) = (encerrada_motivo IS NULL))
);
CREATE UNIQUE INDEX manejo_sugestoes_em_andamento ON manejo_sugestoes (id_cliente) WHERE encerrada_em IS NULL;
CREATE INDEX manejo_sugestoes_cliente ON manejo_sugestoes (id_cliente, id DESC);

-- O histórico: só inclusões. A última justificativa e o último veredito de uma sugestão são os que valem.
-- decisao: seguir = fazer o que a lista sugere (passar para a central ou inativar); manter = o cliente continua como está.
CREATE TABLE manejo_eventos (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sugestao bigint NOT NULL REFERENCES manejo_sugestoes,
  tipo text NOT NULL CONSTRAINT manejo_eventos_tipo_check CHECK (tipo IN ('justificativa', 'veredito')),
  decisao text NOT NULL CONSTRAINT manejo_eventos_decisao_check CHECK (decisao IN ('seguir', 'manter')),
  texto text NOT NULL DEFAULT '' CONSTRAINT manejo_eventos_texto_check CHECK (length(texto) <= 2000),
  retrato jsonb NOT NULL,                        -- os fatos da sugestão na hora
  criado_em timestamptz NOT NULL DEFAULT now(),
  criado_por bigint REFERENCES usuarios ON DELETE SET NULL,
  criado_por_nome text,                          -- cópia: continua dizendo quem foi depois que o usuário é excluído
  -- quem justifica para o cliente continuar como está precisa dizer por quê
  CONSTRAINT manejo_eventos_manter_check CHECK (tipo <> 'justificativa' OR decisao <> 'manter' OR btrim(texto) <> '')
);
CREATE INDEX manejo_eventos_sugestao ON manejo_eventos (sugestao, tipo, id DESC);

-- Quem pode justificar, escolhido em Manejo da Base › Configurar (bi/acesso.py definir_manejo): {"justifica": true}.
-- NULL ou false: o administrador (dá o veredito) ou o visualizador que só consulta. Os clientes que a pessoa vê são os
-- dos vendedores do acesso dela (tela Usuários, coluna escopo).
ALTER TABLE usuarios ADD COLUMN manejo jsonb;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_manejo_check CHECK (
  CASE
    WHEN manejo IS NULL THEN true
    WHEN jsonb_typeof(manejo) <> 'object' THEN false
    ELSE COALESCE(jsonb_typeof(manejo->'justifica') = 'boolean', false)
  END);

-- As regras da página (ConfigManejo em bi/manejo.py: a campanha ligada ou não, os dias de cada regra, o dia do prazo e os
-- vendedores da central) ficam na tabela regras, com versões, como as das outras páginas.
ALTER TABLE regras DROP CONSTRAINT regras_nome_check;
ALTER TABLE regras ADD CONSTRAINT regras_nome_check
  CHECK (nome IN ('metas', 'projecoes', 'sugestao', 'premiacoes', 'credito', 'manejo'));

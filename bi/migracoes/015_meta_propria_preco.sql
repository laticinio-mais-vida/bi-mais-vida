-- Preço médio nas campanhas: a meta própria de um vendedor é o preço-alvo dele em cada produto, por cima dos da
-- campanha (campanha_produtos) (pedido do usuário: no preço médio também dá para dar uma meta própria). Guarda só os
-- produtos com o preço diferente do da campanha: {"<código do produto>": R$ por unidade}; NULL = os da campanha.
ALTER TABLE campanha_vendedores ADD COLUMN alvos_precos jsonb;

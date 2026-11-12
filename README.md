# BI de Metas Mais Vida

Versão em Python das páginas de metas do Power BI (Metas ES, Metas BA, Metas Edir, Metas Produtos BA e
Metas Outras Linhas ES, mais a Produtos ES, que o Power BI não tinha), reunidas numa página só, com abas por visão e filtros de vendedores, meses e anos
(todos de seleção múltipla), e uma página de Configurações para as regras que antes ficavam dentro das
fórmulas DAX. A página **Projeções** prevê o
faturamento bruto dos próximos 6 meses. A página **Sugestão de Metas** sugere a meta do mês seguinte de cada vendedor, por
produto (as páginas de sugestão do Power BI). A página **Premiações** mostra o prêmio do mês de cada vendedor e de cada
supervisor (a dos vendedores, como no Power BI; a dos supervisores, pelos regulamentos de nov/2026) e a comissão dos vendedores. A página **Devoluções** separa o que voltou na
entrega do vencido e danificado no cliente, por causa, produto, cliente e vendedor, e monta o Parecer de Devoluções em PDF. A página **Assistente** responde perguntas sobre os dados com IA
(Claude). A página **Gestão** acompanha a equipe por região: objetivos, campanhas por vendedor (com base, meta e resultado) e o
histórico interno de cada vendedor; no topo, a agenda de cada pessoa, com atividades únicas ou repetidas e o feedback do
que foi feito, e tarefas com prazo divididas em subtarefas para outras pessoas, também num kanban. O atraso de
uma tarefa precisa ser justificado, e o **sino** no topo avisa o que acontece nas tarefas.

As páginas ficam na **barra lateral** à esquerda. O botão no topo dela recolhe a barra (só os ícones; o nome
aparece ao passar o mouse) ou expande, e o painel lembra a escolha neste navegador. No celular, a barra vira
uma gaveta que abre pelo botão de menu do topo. **Usuários** fica na seção Administração, que só o
administrador vê. Cada página tem a sua configuração, no botão **Configurar** da barra de filtros dela (só para
administradores): em Metas abre as Configurações das metas; em Projeções, as Configurações das projeções; no
Assistente, o que cada pessoa consulta e o uso; na Gestão, os vendedores que cada pessoa acompanha; na Sugestão de
Metas, o crescimento desejado, os tetos e os faturamentos das áreas do BA; nas Premiações, as faixas dos vendedores, as
regras dos supervisores e os brindes que descontam da comissão.

## Como abrir

O painel abre sem configurar nada: os caminhos do banco e das planilhas vêm de `config.exemplo.ini`. Para ele
ler o ERP, falta só a senha do banco: copie `config.exemplo.ini` para `config.ini` e preencha a senha em
`[banco]` (o `config.ini` vale por cima do exemplo e não vai para o GitHub, porque guarda a senha). Sem a senha, o
login funciona, mas a tela "Preparando os dados" avisa que ela falta.

Dê dois cliques em `iniciar.bat`, ou rode:

```bash
python app.py
```

O painel abre no navegador em http://127.0.0.1:8050. Para encerrar, feche a janela do terminal (ou Ctrl+C).

Na primeira vez, a tela de login pede para criar o **administrador** (nome, usuário e senha). Isso só funciona
no computador onde o painel está instalado. Depois, o administrador cadastra os outros acessos na página
**Usuários**.

O projeto usa o Python 3.11 que já está na máquina, com `fdb` (Firebird), `duckdb`, `pandas` e `numpy` (que vem
com o pandas), que já estão instalados. Usuários, regras e o histórico do Assistente ficam num PostgreSQL instalado
no próprio PC (veja [Banco de dados](#banco-de-dados)), que precisa de `pip install "psycopg[binary]" psycopg-pool`.
O Assistente precisa também de `pip install anthropic`, só onde for usado, e de `pip install XlsxWriter fpdf2` para os
arquivos Excel e PDF que ele prepara. A leitura do Google Agenda (só no site) usa `cryptography`, e a leitura do PDF
do Serasa na página de crédito (só no site) usa `pypdf`; no PC, eles servem só para os testes. No VPS, tudo já vem na
imagem.

## De onde vêm os dados

| Fonte | Caminho (em `config.ini`) |
|---|---|
| Cópia do banco do ERP (Firebird 2.1, só leitura) | `C:\Users\Micro\Documents\banco de dados\LATICINIOMAISVIDALTDA.GDB` |
| Metas de faturamento, mussarela, outras linhas e clientes | `C:\Users\Micro\Documents\METAS.xlsx` |
| Metas de volume por produto (BA) | `C:\Users\Micro\Documents\METAS PRODUTOS.xlsx` |

O sistema copia do banco só o que as páginas usam (vendas, clientes atendidos, devoluções e cadastros, desde
2024) para um cache local em `dados\cache.duckdb`. Por isso os filtros respondem na hora. Para o Assistente, o
cache também guarda as vendas e devoluções por cliente e por dia, e a cidade, a UF, a área e o segmento de cada
cliente. Para a Reavaliação de Crédito, guarda os títulos a receber de venda (de todo o histórico), as parcelas de
cada um (quantas, quantas pagas e quanto já foi pago) e o limite de crédito e o prazo de cada cliente. Também guarda
os pedidos de venda um a um, com os produtos de cada pedido (ver abaixo).

- **Cópia do banco nova:** o painel percebe sozinho em até 1 minuto, mesmo sem nenhuma página aberta, e
  atualiza o cache em segundo plano (cerca de um minuto e meio). O botão **Atualizar dados** força a leitura na hora.
- **Planilhas de metas:** são relidas sempre que o arquivo muda. Se estiverem abertas e bloqueadas, vale a
  última leitura boa e aparece um aviso no painel. A meta **aprovada no painel** (Sugestão de Metas › Configurar ›
  Aprovação de metas) vale no lugar das linhas das duas planilhas daquele vendedor e mês.

### Pedidos de venda no cache

Para quem programa no painel: duas tabelas com os pedidos da PEDIDOVENDAS (de venda e de brinde) desde o início do
cache até 30 dias à frente, e os produtos de cada um (LISTAPEDIDOVENDA). Os cancelados vêm marcados. Não trazem
endereço, coordenadas, observação nem usuários. A tabela `pedidos_venda` é outra: é o resumo por dia e cliente que a
efetividade das campanhas usa.

`pedidos_venda_detalhe`: um pedido por linha.

| Coluna | O que é |
|---|---|
| `id` | número do pedido (ID_PEDIDOVENDA) |
| `data`, `criado_em`, `entrega` | data do pedido, quando foi digitado (data e hora) e data de entrega (às vezes vazia) |
| `id_cliente`, `tipocliente` | o código é do cadastro do `tipocliente` (CLIENTE, FUNCIONARIO, FORNECEDOR, PRODUTOR) |
| `id_vendedor` | vendedor do pedido (0 = sem vendedor) |
| `tipopedido` | PEDIDOVENDA ou PEDIDOBRINDE |
| `status`, `status_nome` | V Venda, B Brinde, C Cancelado, L Liberado, S Separado, PC Pedido a confirmar, ES Em processo de separação (A não tem nome no ERP) |
| `cancelada` | verdadeiro se o pedido foi cancelado |
| `origem` | origem gravada pelo ERP (F, C, Magis TI, ANDROID, FV) |
| `id_venda` | a venda gerada (VENDAS), só em pedido de venda |
| `id_brinde` | o brinde gerado (BRINDES), só em pedido de brinde |
| `nota_fiscal` | número da nota da venda ou do brinde gerado, em texto como no ERP ("055770"); vazio no pedido que não foi faturado. O número sozinho identifica a nota: não se repete nem entre as séries 013 e 017 |
| `total`, `desconto`, `peso_liquido` | em R$ e kg |

`pedidos_venda_itens`: um produto do pedido por linha. Junta com a de cima por `id_pedido = id` e com `produtos` por
`id_produto` (nome, linha e unidade).

| Coluna | O que é |
|---|---|
| `id_pedido`, `id_produto` | o pedido e o produto |
| `quantidade` | na unidade do cadastro do produto |
| `preco`, `preco_tabela` | preço praticado e preço da tabela (R$ por unidade) |
| `desconto`, `total` | em R$; a soma do `total` dos itens é o `total` do pedido |

Em nov/2026 eram cerca de 187 mil pedidos e 936 mil itens desde jan/2024. Casos de borda: 163 pedidos não têm nenhum
item, e em 7 a soma dos itens difere do total do pedido em mais de 5 centavos. As tabelas são gravadas em ordem (os
pedidos por data, os itens por pedido) e não têm índice: filtrar por data ou por pedido continua rápido (cerca de 1
ms). Um cache sem elas (o PC ainda com o código anterior) vale para o resto do painel, e `cache.sem_pedidos_detalhe`
avisa que faltam.

### Devoluções nota a nota no cache

`devolucoes_notas` (página Devoluções): as devoluções da DEVOLUCOESVENDA com os produtos de cada uma
(LISTADEVOLUCAOVENDA), uma linha por nota, produto e motivo, desde o início do cache. As canceladas vêm marcadas. Os
totais batem com `devolucoes_itens` e `devolucoes_clientes_itens`, que agrupam as mesmas linhas por dia.

| Coluna | O que é |
|---|---|
| `id_devolucao` | a nota de devolução no ERP: é ela que identifica a nota |
| `nota`, `serie` | número (NUMDOCUMENTO, em texto como no ERP) e série. Na devolução na entrega a nota é a nossa (séries 013 e 017); na imprópria é a do cliente (séries 1, 2, 3…), por isso o número se repete entre clientes |
| `emissao`, `data` | data da nota e data da entrada (a das outras tabelas de devolução) |
| `id_vendedor`, `id_cliente`, `tipocliente` | como em `devolucoes_clientes_itens` |
| `cancelada` | verdadeiro se a devolução foi cancelada |
| `id_produto`, `id_motivo`, `valor`, `quantidade` | o produto, o motivo do item, em R$ e na unidade do produto |

A venda de origem (ID_VENDA) fica fora: só vem preenchida desde ago/26, e quase só no vencido. Em nov/2026 eram cerca de
18 mil linhas desde jan/2024 (1.140 notas em 2026). Um cache sem a tabela vale para o resto do painel, e
`cache.sem_devolucoes_notas` avisa que falta: até ela chegar, a página conta cada cliente num dia como uma nota.

### Bloqueio dos clientes no cache

`clientes_bloqueio` (Reavaliação de Crédito e o Assistente de quem tem a página): o bloqueio de hoje no cadastro do ERP,
só dos clientes bloqueados ou com alguma observação no campo do bloqueio (a observação só com espaços não conta).

| Coluna | O que é |
|---|---|
| `id` | o cliente |
| `bloqueado` | `CLIENTES.BLOQUEADO` = 1 |
| `data` | `DATABLOQUEADO`, sem a hora; o "zero" do ERP (30/12/1899) vira vazio |
| `observacao` | `OBSBLOQUEADO`, com as quebras de linha (os espaços repetidos e as linhas vazias em sequência viram um) |

O ERP não guarda o histórico do bloqueio: a tabela é o cadastro de agora. Quem é desbloqueado costuma ficar com a
observação e a data do bloqueio antigo. Em nov/2026 eram 1.392 linhas: 1.300 bloqueados (74 ativos) e 92 desbloqueados
com observação. O grupo é opcional, como os outros: um cache sem a tabela vale para o resto do painel, e
`cache.sem_bloqueio` faz a página avisar que o bloqueio ainda não chegou (ou que a leitura falhou, com `bloqueio_erro`).

## Página Metas

As abas no topo substituem as páginas do Power BI:

| Aba | Equivale a | Vendedores |
|---|---|---|
| Metas ES | Metas ES | grupo ES |
| Metas BA | Metas BA | grupo BA |
| Metas Edir | Metas Edir | grupo Edir |
| Outras Linhas ES | Metas Outras Linhas ES | grupo ES |
| Produtos BA | Metas Produtos BA | grupos BA e Edir |
| Produtos ES | (não havia no Power BI) | grupo ES |

Filtros (todos de seleção múltipla, com Aplicar; nada marcado é todos):

- **Vendedores:** um ou vários. Clicar num vendedor no ranking, no nome dele na tabela ou no cartão de
  Produtos BA ou Produtos ES mostra só ele; clicar de novo volta para todos. Com Ctrl (Cmd no Mac) o clique soma ou tira o
  vendedor dos já marcados.
- **Meses** e **Anos:** os meses marcados dos anos marcados, por exemplo setembro e outubro, ou todos os
  meses de 2026. Com vários meses, metas e realizados somam os meses (como uma segmentação do Power BI), a
  meta de clientes soma os atendidos de cada mês e o ritmo junta os dias úteis de todos os meses. O padrão é o
  mês dos dados.
- O filtro fica no endereço da página, então dá para mandar o link.

Em cada aba:

- **Ritmo do mês:** dias úteis do mês, quantos já passaram e o ritmo esperado (% mínimo da meta para hoje).
  Feriados aparecem marcados. É o antigo quadro "Dias úteis", agora calculado sozinho. Com vários meses vira
  **Ritmo do período**, com um bloco por mês.
- **Indicadores:** realizado contra a meta, situação (meta batida, no ritmo, atenção ou abaixo), projeção
  do mês e quanto falta. No mês de hoje, faturamento, mussarela e outras linhas mostram a **meta de venda de hoje**
  (a expectativa diária do [painel de desempenho](#painel-de-desempenho), no primeiro dia útil a partir de hoje; no
  total, a soma dos vendedores) no lugar do "necessário por dia útil". Os clientes e os outros meses seguem com o
  necessário por dia útil (o que falta ÷ os dias úteis restantes).
- **Corrida da meta:** acumulado do mês contra o ritmo esperado de cada dia, com a projeção.
- **Ranking** dos vendedores. Clicar num vendedor filtra a página por ele.
- **Detalhamento por vendedor** no mesmo formato das matrizes do Power BI: indicadores nas linhas,
  vendedores nas colunas (ordem alfabética) e Total no fim. Metas em azul e categorias em amarelo.
  - Em Outras Linhas ES, a tabela "Falta Outras Linhas / Dentro da meta?" fica num cartão separado, com o
    próprio Copiar imagem, para mandar as duas imagens separadas no WhatsApp.
  - Em Produtos BA e Produtos ES a tabela traz Meta e Realizado por vendedor, com os produtos em ordem alfabética.
- **Metas ES** tem a mesma tela da Metas BA (desde novembro de 2026): faturamento, clientes, venda média e composição
  (mussarela × outras linhas), a corrida e o ranking de faturamento e a tabela com faturamento, venda média e clientes.
  Os cartões e as linhas da tabela de mussarela e outras linhas e as categorias saíram dela; a meta de outras linhas
  continua na aba Outras Linhas ES.
- **Produtos ES** é igual à Produtos BA, com os vendedores do ES e o calendário do ES. A meta de volume vem da METAS
  PRODUTOS.xlsx (que só tem o ES em janeiro de 2026) ou da meta aprovada no painel (Aprovação de metas). Nas duas abas de
  produtos, o filtro de meses mostra só os meses com meta de produto de algum vendedor da aba.
  - As linhas de categoria seguem as categorias definidas em Configurações.
- **Tela cheia:** todo cartão tem um botão de tela cheia no canto superior direito (aparece ao passar o
  mouse), como no Power BI web. Indicadores e tabelas são ampliados para caber na tela, o gráfico da corrida
  é redesenhado maior e as animações rodam de novo. Esc ou o mesmo botão voltam.
- **Copiar imagem:** gera a tabela como imagem (com logo, mês, data dos dados e ritmo do dia) e copia para
  a área de transferência; é só colar no WhatsApp com Ctrl+V. O botão ao lado baixa o PNG. A imagem sai no
  tema que estiver na tela (claro ou escuro) e precisa de internet para carregar a ferramenta de imagem.

A situação compara o realizado com o ritmo esperado do dia:

| Situação | Quando |
|---|---|
| No ritmo | atingido ≥ ritmo esperado |
| Atenção | até 10% abaixo do ritmo |
| Abaixo | mais de 10% abaixo do ritmo |

Em mês fechado, o ritmo esperado é 100%.

## Página Projeções

Previsão do **faturamento bruto** dos próximos 6 meses, separado em **Mussarela** e **Mix** (outras linhas),
com o total. Bruto quer dizer todas as vendas válidas **sem descontar as devoluções**, por isso os valores ficam
acima do realizado da página de Metas. Valem as equivalências de produto, os produtos "não conta" ficam fora e
entram as carteiras dos vendedores escolhidos na configuração da página (por padrão, todas as equipes ES, BA e
Edir, inclusive vendedores sem meta na planilha).

- **Vendedor do cliente:** nas Projeções, cada venda conta para o vendedor que tem o cliente na carteira hoje
  (o vendedor do cliente no cadastro do ERP, na cópia mais recente do banco), não para quem fez a venda. Se em
  fevereiro os clientes do vendedor A passaram para o B, filtrar o B em janeiro já mostra as vendas desses
  clientes. O histórico acompanha o cliente, e vendedor que saiu e não tem mais clientes some do filtro e da
  configuração. Clientes sem vendedor no cadastro ficam fora, assim como as vendas a funcionários, fornecedores e
  produtores (não são clientes e não têm carteira). Se um vendedor que saiu ainda aparece, faltou repassar os
  clientes dele no ERP. A página de Metas continua com o vendedor da venda.
- **Filtros de vendedores e produtos:** seleção múltipla com busca. Vendedores vêm agrupados por equipe e
  produtos por Mussarela e pelas categorias do mix. Marcar o nome do grupo marca todos dele. Nada marcado é
  todos. O filtro fica no endereço da página (dá para mandar o link) e é lembrado neste navegador.
- **Indicadores:** total projetado dos 6 meses, comparação com os mesmos meses do ano anterior, média por mês,
  faixa provável, fechamento do mês em andamento e o erro médio do método. Quando o filtro não tem mussarela
  (ou mix), o cartão mostra "Não se aplica".
- **Gráficos:** realizado mês a mês, projeção pontilhada com a faixa provável e o mesmo mês do ano anterior.
- **Mês a mês:** tabela com dias úteis, projeção e faixa de cada mês, também em imagem (Copiar imagem).
- **Como a projeção é calculada:** o passo a passo e o erro do método por mês projetado, para o filtro escolhido.

### Configurar (Projeções)

O botão **Configurar** da página Projeções (só administradores) abre duas seções. Tudo vale depois de
**Salvar alterações**, e nada muda nas metas nem no ERP.

- **Vendedores da página:** de quem a carteira entra nos totais, nos gráficos e no filtro. Vendedores novos das
  equipes ES, BA e Edir entram sozinhos, para a projeção não perder faturamento sem ninguém perceber. Desmarque
  contas internas (Venda interna, Funcionário, Produtor...) ou quem não deve contar, e marque quem é de fora
  dessas equipes e deve entrar. A lista traz os vendedores com clientes que compraram desde 2024 e mostra, para
  cada um, a venda bruta da carteira nos últimos 12 meses, quantos clientes compraram e a última venda. Um aviso
  mostra quantos clientes estão sem vendedor no cadastro (e quanto venderam), porque ficam fora.
  Fica gravado no banco, com todas as versões anteriores (quem salvou e quando).
- **Acesso:** a página é liberada em Usuários, e cada pessoa vê, dos vendedores da página, só os do acesso dela (também
  em Usuários). Os totais somam só as carteiras dos vendedores que a pessoa vê. Administradores veem todos os vendedores
  da página.

### Como a projeção é calculada

1. Cada mês fechado desde jan/2024 vira **R$ por dia útil** (calendário de ES e BA com os feriados e os extras
   das Configurações), para meses curtos ou com feriado não parecerem queda.
2. A projeção é a **média de dois métodos**:
   - mesmo mês do ano anterior × crescimento (média dos últimos 12 meses ÷ média dos 12 anteriores);
   - tendência dos últimos 12 meses sem a sazonalidade, amortecida (a inclinação perde 20% a cada mês à
     frente), × o fator de sazonalidade do mês.
   O resultado volta para reais multiplicando pelos dias úteis de cada mês futuro. Faturamento = mussarela + mix.
3. **Com filtro:** média entre o modelo aplicado só ao filtro e a projeção do total × a participação do filtro
   nos últimos 6 meses. Se o filtro não tem 24 meses seguidos de vendas (vendedor ou produto novo), vale só a
   participação. Para quem vê só alguns vendedores, o acesso funciona como um filtro: a projeção de um vendedor
   é a mesma para ele e para o administrador.
4. **Faixa provável:** o método é refeito para os últimos 12 meses usando só o que se sabia antes de cada um, e a
   faixa é o erro médio dessas tentativas para cada distância (1 mês à frente, 2 meses...). Sem histórico para
   medir, a faixa é o dobro da do total.
5. **Mês em andamento:** realizado até agora mais o fechamento pelo ritmo (realizado ÷ dias úteis passados × dias
   úteis do mês), a mesma conta da página de Metas, mas sobre o bruto.

O método foi escolhido testando seis alternativas (Holt-Winters entre elas) nos meses de jul/2025 a set/2026.
Erro médio de 1 a 6 meses à frente, sem filtro: **faturamento 6,6%**, **mix 5,7%** e **mussarela 11,5%** (a
mussarela varia mais). Por vendedor o erro fica perto de 19% no mix e 26% na mussarela, e a faixa da página
mostra isso. As constantes ficam no topo de `bi/projecoes.py`.

## Página Sugestão de Metas

A meta do mês seguinte de cada vendedor, por produto, como nas páginas **Sugestão de Meta BA**, **Sugestão de Meta ES** e
**Duplicata de Sugestão de Meta BA** do Power BI. Do BA saem a METAS PRODUTOS.xlsx (volume por produto) e a META FATURAMENTO
da METAS.xlsx; no ES, a sugestão é a referência para a meta.

- **Filtros:** ES ou BA (o BA inclui o Edir), um vendedor ou todos, uma área comercial ou todas e o **mês da meta** (o padrão é
  o mês dos dados; o mês base é o anterior). Entram os vendedores do estado que têm meta (na METAS.xlsx ou aprovada no
  painel) no mês da meta ou nos dois anteriores e clientes na carteira (como as listas fixas de nomes do Power BI). O
  filtro fica no endereço da página.
- **Cartões:** a meta sugerida em R$, a base (o mês base na mesma conta) e as parcelas da conta (sazonalidade, faturamentos
  e crescimento proposto, em média ponderada quando há várias linhas).
- **Evolução:** o volume de cada mês do ano do mês base e do ano anterior e a sazonalidade de cada mês para o seguinte, como
  no Power BI. Clicar num produto da tabela mostra o gráfico só dele.
- **Meta por produto:** volume base, faturamentos, sazonalidade, acumulado do ano, crescimento proposto, meta em volume (já
  dentro da faixa), variação da meta sobre o volume base, preço médio, meta em R$ e a coluna **Faixa**: "—" quando a conta
  ficou entre o piso e o teto, "↑ piso" quando subiu até o piso, "↓ teto" quando baixou até o teto (numa linha que soma
  várias contas, "faixa" se algum item foi movido) e "ajuste" quando a meta é a do administrador. No BA, também **por
  área**, com os produtos de cada área. O administrador pode **ajustar a meta de volume** de uma linha na própria tabela
  (veja [Ajustes de volume](#ajustes-de-volume-na-página)).
- **Resumo dos vendedores:** todos os vendedores do estado, com a base, a meta sugerida, o crescimento e a meta já lançada
  (a aprovada no painel, com ✓, ou a da METAS.xlsx; Copiar imagem para o WhatsApp). Clicar num vendedor filtra a página.
- **Como a sugestão é calculada:** o passo a passo com os números em vigor.
- **Acesso:** a página é liberada em Usuários; cada pessoa vê só os vendedores do acesso dela (também em Usuários).
- **Assistente:** quem tem a página pergunta "qual a meta sugerida da Jamille para novembro?" e recebe os mesmos números.

### Como a sugestão é calculada

Por linha (BA: vendedor × área × produto; ES: vendedor × produto, como no Power BI), com os clientes que estão **hoje** na
carteira de cada vendedor (o cliente repassado leva o histórico, como nas Projeções; a área é a atual do cliente):

1. **Volume do mês base:** vendas válidas − devoluções que descontam (as regras de Metas), com as equivalências de produto.
2. **Por faturamento:** volume ÷ faturamentos do mês base. **BA:** os da área: cada dia de atendimento (Gestão ›
   Configurar) é faturado no prazo da área, em dias úteis (1 = o dia útil seguinte; sexta e sábado → segunda; feriado empurra
   para o próximo). Eunápolis (segunda) e Eunápolis (terça) faturam 2 dias úteis depois, como mostram as vendas. **ES:** os
   dias úteis do ES.
3. **Sazonalidade:** (volume do mês da meta no ano passado ÷ faturamentos dele) ÷ (volume do mês base no ano passado ÷
   faturamentos dele). Sem venda no ano passado = 1; teto de +20%; queda reduz a meta.
4. **Crescimento proposto:** 12% − (acumulado do ano até o mês base ÷ mesmo período do ano passado − 1), entre 0% e +20%. Sem
   venda no acumulado do ano passado = 0%.
5. **Meta (volume)** = por faturamento × sazonalidade × faturamentos do mês da meta × crescimento proposto.
6. **Faixa** (decisão de 03/11/2026): a meta de volume fica entre um piso e um teto. As referências são a média do ritmo (volume
   ÷ faturamentos) dos 3 meses até o mês base e a dos 3 meses em volta do mês da meta no ano passado (o mês base, o da meta e
   o seguinte; sem venda neles, não conta), as duas × os faturamentos do mês da meta. Piso = menor referência (menos a folga
   configurada, 0%); teto = maior × (1 + 20%). Abaixo do piso a meta sobe até ele; acima do teto desce até ele; dentro, a
   conta fica. No teste contra o realizado de ago–out/26 (3.638 linhas), o erro por item caiu de 32% para 26% e o do total
   de cada vendedor de 11% para 10%; 57% das linhas mudam. Limites conhecidos: produto sem venda no mês base continua sem
   linha; um produto novo na linha (sem venda nos 2 meses antes do base) tem a referência recente puxada para baixo pelos
   meses sem venda, e um cliente perdido há menos de 3 meses puxa o piso para cima — o ajuste manual resolve os dois.
7. **Meta (R$)** = meta (volume) × preço médio do mês base, que é o faturamento **bruto** ÷ o volume vendido. O total é a soma
   das linhas; "todos os vendedores" é a soma de cada um.

Área sem dia de atendimento e sem número fixo fica fora, como no Power BI (que deixava fora as áreas ausentes da planilha
"Quantidades Faturamentos.xlsx"), e um aviso diz quantos clientes e quanto do mês base ficaram fora. Mês base ainda aberto
também tem aviso.

### Ajustes de volume na página

O administrador troca a meta de volume que a fórmula deu numa linha da conta, na própria tabela da página:

- **Onde:** no BA, só na visão **Por área**, no produto dentro da área (a conta do BA é por vendedor × área × produto); a visão
  Por produto mostra a soma, marcada como ajustada. No ES, na tabela por produto, sem filtro de área (a conta do ES junta as
  áreas; com o filtro, a parte da área acompanha o ajuste no mesmo %). Só a linha de **um vendedor só** tem campo: um
  produto que soma vários vendedores (13 das 39 áreas do BA têm mais de um) pede o filtro de vendedor.
- **Como:** digita o volume (em cinza, o sugerido pela conta, já dentro da faixa); a linha mostra a meta em R$ nova (volume ×
  o preço médio da linha), a variação e "ajuste" na coluna Faixa, e a barra soma a diferença. Vale depois de **Salvar
  ajustes**; o × volta para o sugerido. Trocar de estado ou mês pergunta antes
  de descartar o que não foi salvo. Exemplo (Jamille, nov/26, Mussarela Mais Vida 4kg na PS - ORLA): a fórmula dá 1.539,9 kg
  × R$ 39,14 = R$ 60.269; com 2.000 kg, R$ 78.276, e a meta sugerida dela sobe R$ 18.006.
- **O que muda:** tudo que soma as linhas usa o ajuste: o total do produto e da área, os cartões, o resumo dos vendedores, a
  **Sugerida** da Aprovação de metas e o Assistente. O número digitado não muda quando a conta muda depois.
- **Meta já aprovada:** o produto ganha (ou perde) na aprovada a **mesma diferença** de volume, e a meta em R$ muda diferença
  × preço da linha; os outros produtos não mudam, e a aprovação mostra "alterada por". Para isso o retrato da aprovada anda
  pelo fator dela (meta ÷ sugerida), que fica igual: editar o R$ em Configurar continua movendo todos os produtos (os
  ajustados também) no mesmo %. A barra avisa "muda a meta aprovada de …" antes de salvar.
- **Linha que sai da conta** (cliente repassado, área sem faturamento, sem venda no mês base): o ajuste deixa de contar, e o
  administrador vê um aviso. Produto sem venda no mês base não tem linha, então não dá para criar meta para ele.
- **Só no site**, como a aprovação: os ajustes ficam na tabela `sugestao_ajustes` do banco onde foram salvos.

### Configurar (Sugestão de Metas)

O botão **Configurar** (só administradores) tem três seções. As duas primeiras são as regras da conta, gravadas no banco
com versões, como as regras de Metas:

- **Regras da conta:** crescimento desejado no ano (ES e BA, 12%), teto da sazonalidade (20%) e teto do crescimento proposto
  (20%), e a **faixa da meta**: usar a faixa (ligada), teto da faixa (20% acima da maior referência) e folga do piso (0%
  abaixo da menor), com "Restaurar padrão do Power BI" (que também restaura a faixa). As regras gravadas antes da faixa não
  têm os campos dela: valem os padrões até o próximo Salvar.
- **Faturamentos por área (BA):** para o mês da meta escolhido, os quatro meses que a conta usa (base, meta e os dois do ano
  passado). Para cada área: os dias de atendimento (mudam em Gestão › Configurar), o prazo do faturamento com o dia em que
  a área de fato fatura nas vendas dos últimos 6 meses, o número **fixo** por mês (as quinzenais: Itamaraju, Teixeira,
  Itabatã e Posto da Mata, com 2) e o número de cada mês, que pode ser **ajustado à mão** (apagar volta ao automático).
- **Aprovação de metas:** veja abaixo.

### Aprovação de metas

Em Configurar › **Aprovação de metas**, o administrador escolhe o estado e o mês da meta e vê cada vendedor com a meta que a
sugestão gerou. Ao aprovar, a meta passa a valer sozinha no **painel de Metas** (faturamento, clientes e, no ES, mussarela e
outras linhas; e a meta de volume por produto nas abas Produtos BA e Produtos ES), no Assistente e na Gestão, **no lugar das linhas da
METAS.xlsx e da METAS PRODUTOS.xlsx daquele vendedor e mês**. Os outros vendedores e meses seguem as planilhas. Um mês
aprovado aparece no filtro de Metas mesmo sem estar nas planilhas.

- **Meta (R$):** vem com a sugestão (com os ajustes de volume da página), arredondada ao real, e pode ser editada. A **meta
  de volume** de cada produto muda no mesmo percentual: no BA, volume sugerido × (meta aprovada ÷ sugerida). Clicar no nome
  do vendedor mostra os produtos com a meta de volume que vai para o painel. A meta de volume de um produto se ajusta na
  própria página (veja [Ajustes de volume](#ajustes-de-volume-na-página)).
- **Mussarela (só no ES):** vem com a soma dos produtos do grupo mussarela da sugestão (Configurações das metas). O
  administrador pode mudar, e outras linhas é o resto. Ao editar o total, a mussarela acompanha no mesmo percentual. Os
  produtos de mussarela seguem o fator da mussarela, e os outros o das outras linhas.
- **Clientes:** vêm com os clientes ativos da carteira no **dia 1º** do mês da meta, sem os de pedido bloqueado, pelo
  histórico da carteira. Esse é o número que a META CLIENTE da planilha acompanha: em out/26 bateu em quase todos (Antonio
  90 = 90, Edir 37 = 37, Rubens 137 × 136). O valor pode ser editado. Se o dia 1º ainda não chegou, vale a carteira da data
  dos dados. Antes do histórico (15/09/2026), vale a META CLIENTE da planilha.
- **Aprovar:** a chave da linha, ou "Aprovar as pendentes". Editar uma linha pendente já marca para aprovar. Tudo vale
  depois de **Salvar**.
- **Congelada:** a aprovação guarda o retrato da sugestão naquele momento (total, mussarela, clientes da carteira e volume e
  preço de cada produto). Se a conta mudar depois (devoluções lançadas tarde, troca de carteira), a meta não muda, e a
  linha mostra "hoje: R$ X". Editar uma aprovada aplica o novo valor sobre o retrato guardado.
- **Retirar:** desligar a chave de uma aprovada volta a valer a planilha. Aprovar de novo refaz a meta pela sugestão do dia.
- **Histórico:** cada gravação é uma linha nova na tabela `metas_aprovadas`, com quem salvou. A tela mostra quem aprovou,
  quem alterou e quem retirou. Se outro administrador gravou a mesma meta enquanto você editava, o painel recusa e pede
  para recarregar.
- **Vendedor novo:** quem não tem meta nos últimos 3 meses não está na lista da página. Se for do grupo do estado e tiver
  vendido no mês base, aparece em "Mostrar N vendedores sem meta recente". Depois de aprovado, entra na lista.
- **Só no site:** a aprovação fica no banco de onde foi feita. O painel do PC tem o próprio banco e continua só com as
  planilhas.

### Diferenças em relação ao Power BI (sugestão)

1. **Preço médio:** faturamento bruto ÷ volume vendido. O Power BI usava o líquido de todas as devoluções e dos brindes.
2. **Faturamentos:** calculados sozinhos, com prazo, número fixo e ajuste por área. A planilha do Power BI era digitada todo
   mês. A conta bate com ela em 120 de 140 células de set–out de 2025 e 2026. Nas que não batem, as vendas mostraram que a
   planilha errou: Baianão e Eunápolis faturaram 5 vezes em set/26 (a planilha tinha 4), e Trancoso faturou 4 vezes em
   out/25 (tinha 5).
3. **Acumulado do ano:** até o mês base. O Power BI ia até o último mês fechado pela data de hoje; em janeiro dava +20% para
   todos, porque o ano atual vinha vazio.
4. **Devoluções canceladas** não descontam, como no resto do painel; **metas negativas** contam como zero; venda a
   funcionário, fornecedor ou produtor fica fora (código de outro cadastro).
5. **Sazonalidade na tela:** a mesma da conta. A página Duplicata mostrava as quedas como 0%, mas a meta usava a queda.

Conferência em 27/10/2026 (meta de out/26, com as regras do Power BI ligadas: faturamentos da planilha e devoluções canceladas
descontando): dos 246 volumes por produto da METAS PRODUTOS.xlsx, 179 bateram (os de Jamille, Franquelin e Vicente, todos). A
maior parte dos outros é da Thais e do Ricardo - EU, que tiveram clientes repassados desde então; nos demais vendedores, até
3%, com um produto da Mauricia fora disso.

## Página Premiações

A premiação do mês, numa página só, com uma aba para cada parte, como as abas de Metas: **Vendedores** (a página
"Premiacao Vendedores" do Power BI, oculta lá), **Supervisores** (os regulamentos de nov/2026, que substituíram a página
"Premiacao Supervisores" do Power BI) e **Comissão**. Os filtros são o mês e o ano (o padrão é o mês dos dados; entram os
meses com META CLIENTE na planilha ou aprovada). Enquanto o mês está em andamento, o prêmio aparece como **previsto**;
depois, como **final**.

- **Vendedores:** um por linha, os que têm META CLIENTE maior que zero no mês (planilha METAS.xlsx ou meta aprovada no
  painel, com ✓), de todos os estados. Mostra a meta de clientes, os atendidos, o % da meta, a faixa atingida, o prêmio e
  quantos clientes faltam para a faixa seguinte. Os cartões trazem o total a pagar, os atendidos, as faixas e quem está a
  até 3 clientes da próxima faixa. A tabela vira imagem para o WhatsApp (Copiar imagem).
- **Supervisores:** um quadro por supervisor: Marcos (BA), Ronaldo (ES) e Valdirene (ES, a mesma carteira do Ronaldo,
  pelo regulamento dela). Cada quadro mostra os indicadores (realizado, meta, alcance, a faixa atingida e a parcela) e
  **A conta**, do conquistado ao valor a receber. "Ver as contas" mostra de onde sai cada número, a carteira de cada
  vendedor e as listas dos clientes novos e das reativações.
- **Comissão:** a comissão de cada vendedor das equipes BA e ES (veja [A aba Comissão](#a-aba-comissão)).
- **Como é calculado:** o passo a passo de cada aba, com as regras em vigor.
- **Baixar PDF:** a tabela da aba aberta, no mês escolhido, em PDF (A4 deitado), montada no servidor com o acesso de quem
  baixa: na aba Vendedores, a tabela da premiação com as faixas; na Supervisores, a tabela dos indicadores de cada quadro,
  com as parcelas conquistadas e o valor a receber; na Comissão, a tabela por vendedor, com os totais por estado. Só as
  tabelas: sem a conta passo a passo dos supervisores, as listas de clientes ou a comissão por produto. As observações da
  página vão no fim, e o PDF não mostra códigos do ERP, só nomes.
- **Acesso:** a página é liberada em Usuários, e cada pessoa vê só os vendedores do acesso dela (também em Usuários). As
  **abas** e os **quadros de supervisor** de cada pessoa são escolhidos em Premiações › Configurar › Acesso por usuário. O
  quadro de um supervisor soma a carteira inteira do estado: só aparece para quem vê todos os vendedores daquele estado
  (todos os vendedores, ou a equipe do estado inteira; nunca com "Só alguns vendedores"), mesmo que esteja marcado. Sem
  nenhum quadro que a pessoa possa ver, a aba Supervisores some.

### Como a premiação é calculada

**Vendedores:**

1. **Atendidos:** clientes distintos com venda não cancelada no mês, pelo vendedor da venda. É a mesma conta dos clientes
   realizados da página de Metas; devolução não tira o cliente.
2. **% da meta:** atendidos ÷ META CLIENTE.
3. **Prêmio:** o da maior faixa atingida (as faixas não se somam). Padrão do Power BI: 91% → R$ 200, 96% → R$ 250 e 100% →
   R$ 350. Abaixo de 91%, nada.

**Supervisores** (os regulamentos de nov/2026: o "segunda versão" do Ronaldo, que vale também para o Marcos, e a "nova
estrutura" da Valdirene). A carteira é a de **hoje**. Entram os clientes cujo vendedor no cadastro é do estado, pelas
Configurações das metas ou, sem configuração, pelo supervisor no ERP; terceiros, o Edir e as contas internas ficam fora.
Só entram vendas, devoluções e brindes de cliente (sem funcionário, fornecedor ou produtor), sem os produtos que ficam
fora das metas. O Ronaldo e a Valdirene usam os mesmos números do ES.

Cada indicador tem um peso; a **parcela** de referência é o peso × o variável:

| Indicador | Marcos e Ronaldo (R$ 6.000) | Valdirene (R$ 9.000) | Conta | Meta |
|---|---|---|---|---|
| Faturamento líquido | 30% | 35% | vendas do mês − as devoluções que descontam na meta (Metas › Configurar: erro de lançamento, recusa, falta de mercadoria, cliente ausente e os erros de faturamento, logística e expedição, sem as canceladas). Brindes não descontam, como na meta | soma das METAS FATURAMENTO dos vendedores do estado no mês (sem o Edir no BA) |
| Mix (exceto mussarela) | — | 20% | líquido sem a mussarela (32, 12551 e 12552, editável) ÷ líquido | 55% |
| Positivação | 25% | 15% | clientes da carteira com venda no mês | soma das METAS CLIENTE dos vendedores do estado no mês |
| Ativação de clientes novos | 25% | 15% | clientes da carteira cadastrados no ERP no mês **e** com compra no mesmo mês | 40 por mês |
| Reativação de clientes | 20% | 15% | clientes da carteira com uma compra no mês feita depois de **60 dias ou mais sem comprar**, contados da compra anterior até essa. **Só conta quem já tinha comprado:** a compra anterior é a última venda do painel (desde jan/24) ou, sem nenhuma, o último título de venda do ERP (os títulos vão até 2012) | 20 por mês |

As metas de novos e de reativação não existem na planilha nem nas aprovadas: ficam no Configurar (um número por
supervisor para todo mês). Qualquer meta pode ser trocada num mês específico.

**Faixas** (% da meta → % da parcela pago, sem interpolação), em Premiações › Configurar › Regras dos supervisores:
- faturamento e mix (as mesmas faixas): a partir de 90%, 30%; a partir de 100%, 100%;
- positivação, novos e reativação, **cada um com as suas faixas** (o padrão é igual para os três): a partir de 80%, 40%;
  a partir de 100%, 100%; a partir de 120%, 150%. Até 12/11/2026 os três tinham uma lista só; as regras salvas antes
  disso abrem com essa lista copiada para cada um.

**A conta**, nesta ordem (cada passo arredondado ao centavo):
1. **Conquistado** = a soma das parcelas (pode passar do variável, por causa das faixas de 150%).
2. **Trava** pelo % da meta de faturamento: abaixo de 90%, nada; de 90% até abaixo de 95%, metade; a partir de 95%, tudo.
3. **Bônus de superação**, sobre o valor depois da trava, só com o faturamento **acima** de 100% da meta: +2% (até abaixo
   de 110%), +5% (a partir de 110%), +7% (a partir de 120%) e +10% (a partir de 150%). Com 100% exato, sem bônus.
4. **Desconto pelo vencido**, por último: devoluções não canceladas e brindes com motivo "Devolução imprópria - vencido" ou
   "Brinde - vencido" ÷ as vendas do mês. Até 0,5%, sem desconto; acima de 0,5% até 1%, mantém 95%; acima de 1%, mantém 90%.
5. **Só a Valdirene: prêmio da inadimplência** de R$ 450 com a inadimplência em até 0,45%: títulos de venda a cliente
   emitidos de 7 a 2 meses antes (para outubro, março a agosto), vencidos há 30 dias ou mais na data dos dados e ainda em
   aberto, ÷ o faturamento líquido desses 6 meses. Entra depois de tudo, fora da trava, do bônus e do desconto, e **não é
   pago quando a trava zera** o prêmio (faturamento abaixo de 90%).

Exemplo do regulamento: parcelas de R$ 6.000 (100% de todas), faturamento a 105% da meta e vencido em 0,7%: a trava mantém
R$ 6.000, o bônus de 2% leva a R$ 6.120 e o desconto (mantém 95%) deixa R$ 5.814.

Casos de borda:
- Cadastrado em 30/09 e com a primeira compra em 01/10: não conta em nenhum dos dois meses como cliente novo.
- Voltou a comprar duas vezes no mesmo mês: uma reativação. Exatamente 60 dias sem comprar: conta.
- Cliente que nunca tinha comprado (nenhuma venda nem título de venda) e compra agora: nem novo, se o cadastro é de
  outro mês, nem reativado, porque não é compra "de novo". Em out/26, no BA, um cliente cadastrado em 2010 ficou fora por
  isso; outros dois, sem compra desde 2020 e 2021 (pelos títulos), contaram.
- O alcance aparece arredondado para baixo (89,96% vira 89,9%), para não mostrar 90% ao lado de uma parcela zerada.
- A inadimplência conta o que está em aberto **hoje** (o dia da extração dos dados): o prêmio de um mês já fechado muda
  quando um cliente paga depois.
- Os nomes dos clientes aparecem sem o código que o ERP põe no fim ("(CLIENTE 5959)").

Os brindes vêm de uma tabela do cache (`brindes_clientes_itens`). Sem ela (código anterior no computador da empresa), o
vencido conta só as devoluções, com aviso.

### A aba Comissão

A comissão de cada vendedor das equipes **BA e ES** no mês, que não vem do Power BI. Os filtros são os mesmos, mas valem
todos os meses com dados, mesmo sem META.

**De onde vem o % (conferido no ERP em 30/10/2026):**
- O % é de cada **vendedor para cada produto**, na tabela de comissão do ERP (`CONFIGCOMISSAOVENDEDOR`, linhas de
  vendedor). Os campos de comissão do cadastro de produto e do de vendedor estão zerados.
- Em cada item de venda, o ERP grava o % daquele dia e o valor da comissão (`LISTAVENDA.COMISSAO` e `VALORCOMISSAO` =
  valor do item × %).
- Na devolução, o ERP grava só o %, às vezes 0, e não o valor. O brinde não tem %.
- No cadastro do vendedor, as equipes BA e ES ganham comissão sobre a venda. O Edir e os terceiros ganham sobre o
  recebimento e ficam fora da aba.

**A conta:**
1. **Comissão das vendas:** a que o ERP gravou em cada item de venda a cliente não cancelada. Mudar a tabela depois não
   muda o passado. Venda feita antes de o produto ter % na tabela fica sem comissão: o WALDREY, por exemplo, teve 0% até
   02/10/2026, porque a tabela dele foi preenchida em 05/10.
2. **− Devoluções:** todas as devoluções não canceladas do mês, de todos os motivos, pela data de entrada e do vendedor
   que está na devolução, × o **% de hoje** da tabela para o produto.
3. **− Brindes:** os brindes do mês com os motivos escolhidos, × o % de hoje da tabela. O padrão é 10, 11 e 12
   ("BRINDE – DANIFICADO…") e 16 ("BRINDE – VENCIDO").
4. **A pagar** = comissão das vendas − os dois descontos. Fica negativo quando as devoluções do mês passam da comissão.

Só entram vendas, devoluções e brindes de cliente: venda a funcionário, fornecedor ou produtor não tem comissão no ERP.
Devolução ou brinde de um produto sem % na tabela do vendedor não desconta; a aba avisa e marca o produto.

**Na tela:**
- **Cartões:** o total a pagar, por estado; a comissão das vendas e o % médio; o desconto das devoluções; o dos brindes.
- **Tabela por vendedor:** vira imagem para o WhatsApp (Copiar imagem).
- **Comissão por produto:** do vendedor escolhido (ou clicado na tabela), com o % médio gravado e o % de hoje da tabela.

A comissão vem de duas tabelas novas do cache (`comissoes_vendas` e `comissoes_percentuais`). Enquanto o computador da
empresa não manda os dados com elas (código anterior), a aba avisa que a comissão ainda não chegou.

### Configurar (Premiações)

O botão **Configurar** (só administradores) tem seis seções. As regras ficam no banco, com versões, como as de Metas, e
valem para **todos os meses**: mudar uma faixa ou um peso recalcula também os meses que já passaram.

- **Vendedores:** as faixas (o % mínimo e o prêmio em R$). Dá para acrescentar e tirar faixas.
- **Supervisores:** de cada um, o nome, o variável, os pesos dos cinco indicadores (0 = não entra; a soma precisa dar
  100%), a meta do mix, o prêmio da inadimplência (liga/desliga, valor e limite) e as metas de todo mês de clientes novos
  e de reativação. O estado de cada um é fixo: ele diz a carteira.
- **Regras dos supervisores:** as faixas do faturamento e do mix e as da positivação, dos novos e da reativação, a trava,
  o bônus, o desconto pelo vencido (dá para acrescentar e tirar faixas), os motivos do vencido, os produtos fora do mix e
  os dias (sem comprar, da reativação; de atraso, da inadimplência). "Restaurar o padrão" mantém as metas trocadas em
  cada mês.
- **Metas dos supervisores:** para o mês escolhido e cada supervisor, a meta automática de faturamento, de clientes, de
  novos e de reativação e um campo para trocá-la naquele mês (0 = sem meta; apagar volta à automática). A meta trocada
  aparece marcada como "ajustada" no quadro.
- **Comissão:** os motivos dos brindes que descontam da comissão (as devoluções descontam todas). Os % de cada vendedor
  e produto ficam no ERP.
- **Acesso por usuário:** como as "Abas por usuário" de Metas: para cada visualizador, se vê a página, quais abas
  (Vendedores, Supervisores, Comissão) e, com a aba Supervisores, quais quadros (Marcos, Ronaldo, Valdirene). Fica no
  cadastro da pessoa (coluna `premiacoes`, migração 041), não nas regras: salvar só o acesso não grava uma versão nova das
  regras. A tela avisa do quadro marcado que fica fora dos vendedores do acesso da pessoa e não deixa salvar a página
  sem nenhuma aba, nem a aba Supervisores sem nenhum quadro. Quem já tinha a página quando a 041 entrou ficou com as três
  abas e os três quadros (o mesmo de antes); quem ganha a página depois começa **sem nenhuma aba**, até o administrador
  marcar (a tela Usuários avisa, com o link para cá).

As regras salvas antes dos regulamentos de nov/2026 (cinco indicadores × R$ 5.000) são convertidas ao abrir: ficam os
nomes, a meta do mix, os produtos fora do mix, os dias da inadimplência e as metas trocadas em cada mês (as do ES valem
para o Ronaldo e a Valdirene).

### Diferenças em relação ao Power BI (premiações)

1. **Total dos vendedores:** a soma dos prêmios. O Power BI aplicava a faixa ao % do total, o que não servia para pagar.
2. **Supervisores:** a conta do Power BI (cinco indicadores × R$ 5.000, um supervisor por estado) foi trocada pelos
   regulamentos de nov/2026, para todos os meses. Ficaram dela a carteira (pelas Configurações das metas e pelo supervisor
   do ERP, não por uma lista fixa de nomes; só vendas a cliente), o mix e a inadimplência.
3. **Regras editáveis** no Configurar (no Power BI ficavam nas fórmulas).

Conferência em 30/10/2026 (outubro até 29/10, com os brindes lidos do ERP): vendedores R$ 2.700 (11 de 21 com prêmio).
Comissão: R$ 67.173,75 a pagar (BA R$ 35.943,92 com 9 vendedores; ES R$ 31.229,83 com 11), de R$ 68.152,20 de comissão das
vendas − R$ 606,20 das devoluções − R$ 372,25 dos brindes. A comissão das vendas e os descontos de cada vendedor batem com
a conta feita direto no ERP.

Conferência dos supervisores em 10/11/2026 (outubro, cache do PC, metas padrão de 40 novos e 20 reativações): Marcos
R$ 4.284,00 (faturamento a 104,37% da meta, bônus de 2%), Ronaldo R$ 1.396,50 e Valdirene R$ 1.667,25 (os dois com o faturamento a
94,0%: trava de 50%; vencido em 0,80%: mantém 95%; inadimplência em 0,49%: sem o adicional). Os números (líquido, clientes,
novos, reativações, vencido e inadimplência) batem com as consultas feitas à parte, direto no cache.

## Página Devoluções

O que voltou dos clientes, separado em dois problemas de natureza diferente, e o **Parecer de Devoluções** em PDF, no
formato do documento que era montado à mão. A página é independente das outras: não tem meta (a de 1,5% é só da premiação
dos supervisores) nem usa o que se configura para Metas.

- **Voltou na entrega:** o pedido não ficou no cliente (erro de lançamento, recusa, cliente ausente, erro de faturamento,
  da expedição ou da logística, falta de mercadoria). Poucas notas, de valor alto, quase sempre a nota inteira: a página
  lista nota a nota. Em 12 meses (nov/25 a out/26), R$ 757 mil, 75% do total, em 485 notas.
- **Vencido e danificado no cliente:** o produto foi entregue, ficou na loja e voltou vencido ou danificado, pela
  devolução imprópria ou pela troca por brinde. É mercadoria que não volta para a venda. Muitos casos pequenos, todo mês: a página mede o índice sobre a venda por produto, segmento, frequência de
  visita e cliente.

Os filtros são o mês e o ano (o padrão é o mês dos dados), a região (BA, ES ou Terceirizados) e o vendedor. Tudo se compara
com a **média dos 6 meses anteriores**.

- **Resumo:** o índice de devolução (% da venda bruta) dividido em na entrega e no cliente, a evolução de 13 meses (em % ou
  em R$), cada causa agrupada pelo responsável (comercial, operação interna, logística, fábrica, ponto de venda) e as regiões
  lado a lado.
- **Na entrega:** as notas devolvidas (e quantas a cada 100 entregas), o valor, os erros de lançamento e o valor médio por
  nota; a tabela por causa; **as notas do mês**, uma a uma (número, série, cliente, vendedor, causa, itens e valor); a tabela
  por vendedor; e os **clientes que repetem** (duas ou mais notas em 6 meses).
- **No cliente:** o vencido e danificado e o vencido em % da venda, os clientes atingidos e os reincidentes (vencido em 3 ou mais dos 6
  meses); os **produtos**, com o vencido em quantidade sobre o vendido, no mês e em 6 meses (em vermelho, os 50% acima da
  média); o vencido por **segmento** e por **frequência de visita** (a rede Semanal, Quinzenal ou Mensal do cliente); a
  **danificado por origem** (na produção, na logística, no cliente, sem origem informada), com os produtos de cada uma;
  e os clientes, com a concentração ("95 clientes fizeram metade do vencido e danificado").
- **Vendedores:** a tabela por região (BA → ES → Terceirizados, com subtotais), ordenável pelo cabeçalho, que vira imagem
  para o WhatsApp. Nos terceirizados, quem vendeu sem devolução vira uma linha só ("Outros N sem devolução"). O clique num
  vendedor abre o bloco dele como sai no Parecer, com o botão **PDF do vendedor**.
- **Parecer em PDF** (no topo): o documento BA + ES, o de cada região e **Todos os PDFs (zip)**, com as pastas de antes
  (`Parecer Devoluções Setembro-2026.pdf`, `BA/… BA.pdf`, `BA/… Jamille.pdf`, …, `TERCEIRIZADOS/… Terceirizados.pdf`). O
  nome do vendedor no arquivo é o da planilha de metas. Os PDFs são montados na hora, com o acesso de quem baixa.
- **Acesso:** a página é liberada em Usuários, e cada pessoa vê só os vendedores do acesso dela, como nas outras páginas.
  As regiões são as desses vendedores. Os terceirizados (vendedores sem equipe) só aparecem para quem vê todos os
  vendedores (ou tem um deles na lista de "Só alguns"); os PDFs também seguem o acesso.

### Como as devoluções são calculadas

1. **Devoluções:** as não canceladas de cliente do cadastro, pela data de entrada e pelo vendedor da devolução, nota a nota
   (tabela `devolucoes_notas` do cache). Funcionário, fornecedor e produtor ficam fora. Cada produto fica com o código do
   ERP (sem a equivalência das Configurações).
2. **Trocas por brinde:** só os brindes de motivo vencido ou danificado (3, 4 e 10 a 16). Brinde de outro motivo
   (transferência, retorno, degustação, doação, pagamento de contrato, perda, sem motivo) não é devolução. O ERP passou a
   ter o motivo no brinde em abril de 2026: antes disso o vencido e danificado no cliente aparece menor, e a página
   avisa.
3. **Causas** (pelo código do motivo) e **responsáveis**:
   - comercial: erro de lançamento (1) e recusa (2);
   - operação interna: erro de faturamento (7), erro da expedição (9) e falta de mercadoria (5);
   - logística: erro da logística (8), cliente ausente (6) e danificado na logística (11, 13);
   - ponto de venda: vencido (3, 16) e danificado no cliente (12, 14);
   - fábrica: danificado na produção (10, 15);
   - danificado, sem origem informada (4).

   Motivo novo no ERP entra em **Outros motivos**, com aviso. As causas ficam em `CAUSAS` (`bi/devolucoes.py`), com
   a descrição de cada uma em `DESCRICOES`. A tela não mostra os códigos do ERP (motivo, produto, série da nota):
   quem usa o painel vê o nome e, ao passar o mouse, a descrição.
4. **Notas:** cada nota de devolução do ERP (`id_devolucao`) conta uma vez; uma nota com duas causas aparece nas duas.
   Entregas são as notas de venda do mês. Sem as notas no cache (PC com o código anterior), cada cliente num dia conta como
   uma nota, com aviso.
5. **% da venda:** sobre a venda bruta do mesmo recorte (vendas não canceladas a cliente, pelo vendedor da venda). Nos
   clientes, a compra é a do recorte nos 6 meses; no Parecer, o faturamento do cliente no mês, de todos os vendedores.
6. **Comparação:** a média dos 6 meses anteriores (o % é o total dos meses sobre a venda dos meses; notas, valores e
   clientes são a média por mês). Produto, segmento, frequência, clientes e reincidência usam os 6 meses até o escolhido.
7. **Região:** a equipe do vendedor nas Configurações das metas ou o supervisor no ERP (BA e Edir = BA, ES = ES, sem
   equipe = Terceirizados); o OCULTO fica fora.

**O Parecer** segue as regras do documento de antes: só os vendedores com devolução, em ordem alfabética; as seções
cliente ausente, erro de lançamento (com o nº de erros em vermelho: cada data e cliente conta um, como no documento),
recusa, vencido, danificado e os tipos adicionais (danificado por problema na produção, imprópria danificado no cliente e na
logística, brinde danificado no cliente, na logística e por problema na produção). Nas seções por produto, os produtos vêm
na ordem do Parecer, com os sabores de bebida láctea somados por tamanho (a bandeja inclui o código antigo, 3643), e cada
produto tem um **limite de volume** (15 para bebida láctea, manteiga de 200 e 500 g e requeijão; 10 para a manteiga a
granel; 4 para coalho, minas frescal e parmesão cunha; 5 para o parmesão peça; 3 para o prato; 1 para as mussarelas e para
produto fora da lista): o cliente abaixo do limite não aparece na tabela do produto, mas conta nos totais e nos rankings.
No fim do vencido, os **clientes em alerta**: vencido ≥ 20% das compras do mês e volume ≥ 30, ou volume ≥ 100 (o volume
soma quilos e unidades). Faturamento, expedição, logística e falta de mercadoria aparecem na página, mas não no Parecer.
Todo PDF termina com os rankings por tipo (erro de lançamento, vencido, danificado e os adicionais por vendedor; recusa e
cliente ausente por cliente). A ordem dos produtos e os limites ficam em `PRODUTOS_PARECER` (`bi/devolucoes.py`).

Conferência em 09/11/2026:
- **Setembro/26:** os rankings e os blocos batem com o Parecer feito à mão (as 19 linhas do erro de lançamento, os 23
  vendedores do vencido, os blocos de Edir, Franquelin e Jamille). Há duas diferenças esperadas: volumes em quilos que
  mudam na segunda casa (soma sem arredondar) e a linha "FUNCIONARIO" (um brinde a funcionário), que a página deixa fora.
- **Outubro/26:**
  - na entrega, R$ 52.719 em 39 notas, 0,74 a cada 100 entregas;
  - no cliente, R$ 40.065 em 370 clientes;
  - total R$ 92.783, 1,41% da venda, contra a média de 1,60% de abr a set/26.
- **Notas:** as devoluções nota a nota somam o mesmo que as outras tabelas de devolução do cache (R$ 2.654.182,39 desde
  2024).

## Página Assistente

Um chat em que a pessoa pergunta sobre os dados em português e a IA responde com os números do painel. Exemplos:
"quanto o Mercado do João comprou em setembro?", "quais clientes do Rubens compraram em agosto e não compraram em
setembro?", "como estão as metas do BA?". A IA é o Claude, pela API da Anthropic.

### Como responde

- **Não é um RAG.** A IA não guarda os dados nem procura trechos parecidos com a pergunta. A cada pergunta ela pede
  consultas ao servidor, o servidor executa no cache e devolve o resultado, e ela escreve a resposta. Todo número
  da resposta sai de uma dessas consultas. As consultas que ela pode pedir são:
  - buscar cliente, produto ou vendedor pelo nome;
  - resumo de vendas por período, com filtros e agrupamentos;
  - metas e realizado (os mesmos números da página Metas);
  - crédito de um cliente (os mesmos números da Reavaliação de Crédito; só para quem tem essa página);
  - as reanálises de crédito registradas: as de um cliente, as de clientes parecidos e o que aconteceu depois de
    cada uma (só para quem tem a página de crédito; veja [Reanálises](#reanálises));
  - a agenda de quem pergunta (só para quem tem a página Gestão; veja [Minha agenda](#minha-agenda));
  - para o resto, uma consulta SQL que só lê os dados;
  - um arquivo Excel ou PDF para baixar (veja [Arquivos](#arquivos-excel-e-pdf)).
- **As regras são as das metas.**
  - Faturamento líquido = vendas não canceladas − devoluções dos motivos marcados, pela data de entrada.
  - Valem as equivalências de produto, e os produtos que "não contam" ficam de fora.
  - Vendedor é o da venda, como em Metas. O da carteira aparece como "vendedor da carteira".
- **Como cheguei nesse número:** embaixo de cada resposta mostra cada consulta feita, com o SQL e uma amostra do
  resultado.
- **Histórico de conversas (no site):** como nos chats de IA, a lista ao lado mostra as conversas da pessoa,
  agrupadas por data (Hoje, Ontem, Últimos 7 dias…).
  - Dá para voltar a qualquer conversa e continuar. A pergunta seguinte pode se apoiar na anterior ("e em agosto?").
  - A busca procura no título e no texto das mensagens, sem diferenciar acentos.
  - Cada conversa pode ser renomeada ou excluída. O título começa como o início da primeira pergunta.
  - Cada conversa tem o seu link e abre em qualquer computador ou celular com o mesmo login. Cada pessoa vê só as
    próprias conversas.
  - Recarregar a página no meio de uma pergunta não perde a resposta: o servidor termina e grava, e ela aparece
    sozinha.
  - No celular, a lista abre pelo botão **Conversas**.
  - O histórico fica no banco PostgreSQL do painel (veja [Banco de dados](#banco-de-dados)).
- Cada pergunta leva de alguns segundos a um minuto, conforme o número de consultas.

### Arquivos (Excel e PDF)

Pedindo "me manda em Excel os clientes do Rubens sem compra há 60 dias" ou "faz um PDF com as metas do BA", a IA
prepara o arquivo e a resposta traz um card com o botão **Baixar**.

- **O que vai no arquivo:** todas as linhas da consulta que a IA montou, não só as que ela leu. São até 50.000 linhas
  no Excel e 2.000 no PDF. Quando a lista passa disso, o arquivo e a resposta avisam.
- **Excel:** título, período e "pedido por… · dados até…" em cima. Depois vem a tabela, com o cabeçalho congelado e
  com filtro. Valores em R$, percentuais e datas já chegam formatados, e os números continuam números.
- **PDF:** o mesmo cabeçalho, o texto da resposta e a tabela, com número de página. Ele deita quando as colunas não
  cabem em pé.
- **Montado no clique:** a conversa guarda a consulta, não o arquivo. Cada clique em Baixar roda a consulta de novo,
  com os dados do momento e o acesso atual de quem baixa. Só o dono da conversa baixa, e quem perdeu um vendedor ou a
  página de crédito não os vê no arquivo. As datas da consulta são fixas, então o período não muda.
- Precisa dos pacotes `XlsxWriter` e `fpdf2`. Sem eles o painel funciona e só o botão Baixar avisa o que falta.

### O que cada pessoa consulta

A IA só recebe as vendas, devoluções, clientes e metas dos vendedores do acesso de quem pergunta. Para cada acesso,
o servidor monta na memória uma cópia dos dados só com essas linhas. A IA consulta apenas essa cópia, sem acesso a
arquivos, ao resto do cache ou a configurações. Pedir "ignore as regras" não adianta, porque o que está fora do
acesso não existe para ela.

Cada pessoa consulta só os vendedores do acesso dela, escolhidos em Usuários (os mesmos de todas as páginas).

O botão **Configurar** da página (só administradores) mostra o **uso e custo**: perguntas e custo estimado por pessoa
nos últimos 30 dias, o gasto de hoje e as últimas perguntas.

### Chave, custo e limites

- **Chave da API:** é cobrada por uso e é **separada da assinatura do Claude**. Crie em platform.claude.com
  (API keys) e coloque só no `config.ini` do servidor, em `[ia]`: `chave = sk-ant-...`. Depois reinicie o painel.
  Sem a chave, a página avisa que não está configurada. O painel precisa do pacote `anthropic`: no VPS ele já está
  na imagem Docker; no PC, `pip install anthropic`.
- **Modelo:** `claude-opus-5-5` é o padrão, o mais capaz. `claude-sonnet-5-5` custa cerca de metade; ao trocar,
  ajuste também os preços em `[ia]`. `esforco = low` deixa as respostas mais rápidas e baratas.
- **Custo estimado com o Opus 5.5:** de US$ 0,05 a 0,15 por pergunta. As instruções fixas ficam em cache e, na
  repetição, custam 5% do preço normal.
- **Limites em `[ia]`:**
  - perguntas por pessoa por dia (`limite_diario`, 50; administradores sem limite);
  - gasto do dia, para todos (`limite_custo_dia`, US$ 2);
  - perguntas respondidas ao mesmo tempo (`simultaneos`, 2);
  - consultas por pergunta (`max_passos`, 8).
- **Memória:** os dados de cada acesso ficam na memória enquanto ele usa o assistente. O de todos os vendedores
  (uns 60 MB) tem vaga própria, porque a página Gestão usa ele sempre; os demais, até `recortes` (2) ao mesmo tempo.

  Vale também pôr um limite de gasto mensal no Console da Anthropic.
- **Recusas:** se o classificador de segurança da Anthropic recusar uma pergunta por engano, o próprio servidor
  da Anthropic refaz a pergunta no modelo que ela recomenda (`fallbacks: "default"`).
- **Registro:** a tabela `assistente_perguntas` do banco guarda uma linha por pergunta (quem, pergunta, resposta,
  consultas, tokens e custo). Os limites do dia são contados nela, então continuam valendo depois de reiniciar o
  painel.

### Privacidade

Nomes de clientes, cidades, segmentos e valores de venda vão para a API da Anthropic, que não usa o que recebe
pela API para treinar modelos. CPF/CNPJ, telefone e endereço não estão no cache e não vão. O limite de crédito, o
prazo, os títulos a receber e o **bloqueio no ERP** (com a observação do bloqueio, texto livre do cadastro, que às
vezes tem o nome de quem autorizou) estão no cache, mas só vão para a IA nas perguntas de quem tem a página
Reavaliação de Crédito; para os outros, esses dados nem existem na cópia que a IA consulta. A IA trata a observação
como dado, nunca como instrução. O mesmo vale para as reanálises de
crédito: as decisões e as **justificativas** (texto livre, que a página pede para não ter CPF, telefone ou endereço)
vão para a IA só nas perguntas de quem tem a página. Dos **dados do Serasa** (veja [Dados do Serasa](#dados-do-serasa)),
o banco do site guarda só a fundação, o score, o histórico de pagamento, as anotações negativas, o CNPJ e a razão
social; o PDF não fica guardado (os sócios e o CPF deles não entram), e nada disso vai para a IA. Do **Google Agenda** de cada pessoa (veja
[Google Agenda](#google-agenda-só-leitura)), o banco do site guarda só o título, o horário e se o evento está ocupado
(sem descrição, local nem convidados), e só o dono vê; o título e o horário vão para a IA só quando ele pergunta da
própria agenda. A IA trata esses títulos como dado, nunca como instrução: qualquer pessoa pode mandar um convite.

## Página Gestão

No topo fica a agenda de quem está vendo (veja [Minha agenda](#minha-agenda)). Abaixo, a **Gestão da equipe**,
separada por região (**ES** e **BA**; o Edir é da BA, com o calendário dela):

- primeiro, os **objetivos do período** da região;
- abaixo, as **campanhas**, com duas barras: o tempo que falta (aviso quando faltam 5 dias ou menos) e o andamento
  contra a meta (nas encerradas, o resultado final e quantos vendedores ficaram na meta);
- um **quadrado por vendedor** da equipe, com uma etiqueta por campanha em vigor e o % da meta dele até agora;
- e, abaixo da equipe, o **painel de desempenho** do dia (ou da semana) e do mês de cada vendedor (veja
  [Painel de desempenho](#painel-de-desempenho)).

As cores do andamento seguem o % da meta, sem olhar o prazo, num degradê contínuo: vermelho até 50%, passando pelo
laranja até o amarelo em 80% e pelo verde-amarelado até o verde em 100%; acima disso, o verde fica cada vez mais
forte até 150%. Na barra da campanha, o % é a soma dos resultados ÷ a soma das metas
nos indicadores que somam (positivação, faturamento, volume), a média do % de cada vendedor nos que são médias (mix,
efetividade, frequência, % da base) e, no preço médio, os aumentos feitos ÷ os pedidos, somando os vendedores em R$ (na média, quem
estava a centavos do alvo e subiu poucos centavos ficaria com centenas de % e puxaria a campanha); quem ainda não tem
meta (base aguardando os dados) fica de fora.

A equipe é quem tem meta no mês na planilha METAS, como na página Metas: contas da casa (venda interna, funcionário,
produtor) ficam fora. Quem está numa campanha em vigor aparece mesmo sem meta.

Cada parte da página (a agenda, os objetivos, as campanhas, a equipe e o desempenho) tem o botão **−** no cabeçalho, que a minimiza:
fica só o título, até o **+**. **Minimizar tudo**, na barra de cima, minimiza todas de uma vez; com todas minimizadas,
ele vira **Mostrar tudo**. A escolha vale para ES e BA e fica guardada no navegador. Com o formulário de uma campanha
aberto, a equipe aparece mesmo minimizada, porque é nela que se marcam os vendedores.

### Campanhas

- **Lançar:** **Nova campanha** liga a seleção no quadro: marque os vendedores e preencha o formulário que aparece
  acima dos quadrados (nome, indicador, prazo, base e meta; em **Mais opções**, início, etiqueta, descrição e os
  filtros). A mesma campanha vai para todos os marcados. No histórico de um vendedor, o botão **Campanha** abre o
  formulário só com ele.
- **Base:** o mesmo indicador, medido para cada vendedor no período fechado escolhido: **semana** (segunda a domingo),
  **quinzena** (1 a 15 ou 16 ao fim do mês), **mês**, **trimestre**, **semestre** ou **ano**, sempre o último que
  termina antes do início (campanha que começa em 22/10 com base mês: setembro inteiro). A base é o período inteiro,
  sem ajuste ao tamanho da campanha. Fica gravada no lançamento e não muda com os dados novos. Se os dados ainda não
  cobrem o período (campanha que começa no futuro), a base fica pendente e entra sozinha quando eles chegarem.
  - Enquanto o formulário está aberto, ele mostra a média da equipe na base (e a dos marcados) e cada quadrado mostra
    a base do vendedor; nos marcados, também a meta, com o botão **Meta própria** para dar uma meta diferente a ele.
    Ao fechar o formulário, isso some.
  - Campanhas de antes (migração 012) continuam com a base do mesmo tamanho, logo antes do início.
- **Meta:** **Número** (o valor que cada um precisa atingir, igual para todos) ou **Percentual** (a base de cada um +
  X%). No preço médio, é o preço-alvo de cada produto, e o % da meta é o aumento (veja abaixo). Campanhas de antes
  podem ter a meta "base + N", que só
  aparece na edição delas.
- **Enquanto corre:** o histórico mostra a parcial de cada semana completa; o detalhe da campanha (clicar no cartão
  dela) mostra base, meta, resultado até agora, o % da meta e a situação pelo ritmo dos dias úteis, por vendedor.
- **Resultado:** quando os dados passam um dia do fim, o resultado de cada vendedor congela e entra no histórico
  dele, com a base, a meta e a diferença. Até lá, aparece como provisório.
- **Encerrar** (antes do fim) e **Prorrogar 2 semanas** valem para a campanha inteira, com todos os vendedores. A base
  continua a mesma (nas campanhas de antes, ela é medida de novo no novo tamanho), e o histórico registra o antes e o
  depois.
- **Editar:** nome, etiqueta e descrição mudam sempre; meta, prazo, base, indicador e vendedores só antes do
  resultado congelar (vendedor que entra ganha a base dele; o que sai fica com o registro no histórico). Mudar o
  início ou o período da base mede a base de novo; mudar só o prazo, não.
- **Arquivar** tira a campanha do quadro (o histórico dos vendedores continua). **Excluir** apaga a campanha e os
  registros dela no histórico; as observações ficam. As encerradas saem do quadro sozinhas 30 dias depois do fim.

### O que uma campanha mede

Um dos tipos prontos, com as mesmas contas do Power BI da empresa, ou uma Personalizada (a conta fica em
`bi/indicadores.py`):

- **Positivação:** clientes distintos com venda no período. Com todos os clientes ("Quem conta"), vem junto a **% da
  base** (a cobertura): todos os clientes que o vendedor atendeu ÷ os clientes ativos da carteira dele **no início**.
  A meta é em clientes ou, na opção **Positivação (meta em % da base)**, na % da base. A "Cobertura da carteira" de
  antes ficou só nas campanhas antigas.
  - **A lista do início não muda.** Com 100 ativos no início, 5 inativados, 15 cadastrados e 3 reativados durante a
    campanha, o denominador continua 100. O numerador conta todo cliente atendido, da lista ou não, e o % pode passar
    de 100%. O cliente que troca de vendedor fica na lista de quem o tinha no início.
  - Desde o início do **histórico da carteira** (15/09/2026), a lista vem dos trechos que cobrem o dia, sem os "PEDIDO
    BLOQUEADO". Os filtros de cliente valem pelo trecho na lista e pelo cadastro nos atendidos.
  - Antes disso (11/2024 a 09/2026), a lista é a **META CLIENTE** da planilha METAS do mês, que acompanha os ativos da
    carteira no começo do mês (como o "% Meta Clientes" do Power BI). Vendedor fora da planilha fica sem %; com filtro
    de cliente, esses meses ficam sem %.
  - Período de até 31 dias: um % só. Mais que isso, a média dos % de cada mês: na campanha, sempre com a lista do
    início; na base de trimestre, semestre ou ano, cada mês com os ativos do seu 1º dia. Mês sem número deixa o
    período sem %.
  - O **histórico da carteira** não vem do ERP, que não guarda quando um cliente foi inativado ou trocou de vendedor.
    O painel do PC compara os ativos a cada atualização dos dados e grava só o que mudou (`bi/carteira.py`), em
    trechos: de quando até quando o cliente esteve ativo, com que vendedor, área e segmento. Reativação abre um
    trecho novo. O começo veio dos retratos de 15/09/2026 e 19/10/2026; o histórico vai no cache para o site.
- **Mix médio:** produtos escolhidos levados, somados cliente a cliente, ÷ todos os clientes positivados.
- **Efetividade:** a média da efetividade de cada dia, pela carteira do vendedor. A de um dia é pedidos na rota do
  dia ÷ visitas esperadas no dia.
  - Pedidos na rota: só os de clientes das áreas atendidas naquele dia da semana. Pedido de cliente de área de
    outro dia não conta (o "Pedidos Fora de Rota" do Power BI). Exemplo: a área X é atendida na segunda, com 10
    visitas; de 8 pedidos na segunda, 6 são de clientes da X e 2 de áreas de outros dias: 6 ÷ 10.
  - Visitas esperadas pela frequência de compra do cliente, que é a rede dele no cadastro do ERP (SEMANAL,
    QUINZENAL ou MENSAL): no dia de atendimento da área, entram todos os semanais, os quinzenais sem compra
    (pedido de venda) nos 7 dias antes e os mensais sem compra nos 21 dias antes. Quem não estava previsto e
    compra no dia entra nas visitas desse dia: o quinzenal que comprou na semana passada não é esperado nesta,
    mas, se comprar de novo, conta o pedido e a visita (sem isso, o pedido entrava sem visita e inflava a
    efetividade). Cliente em outra rede conta como semanal, com aviso.
  - Dia sem visita esperada (fim de semana, dia em que nenhuma área do vendedor é atendida) fica fora da média.
  - Diferente do Power BI, que divide todos os pedidos do período pelas visitas do período: lá, os pedidos fora de
    rota e os de sábado e domingo entram sem visita, e numa campanha curta isso distorce a conta.
  - Os pedidos vêm do ERP (PEDIDOVENDAS não cancelados, do tipo PEDIDOVENDA).
  - Visitas esperadas: cada cliente ativo da área recebe uma visita em cada semana com dia de atendimento dela no
    período. Feriados contam, como no Power BI.
  - **Área com mais de um dia** (decisão de 11/11/2026): os dias marcados são os dias em que o vendedor **pode**
    atender, não os que deve. A semana da área (de domingo a sábado) conta como **um dia só**, o último marcado:
    - o cliente tem uma visita na semana, que vale com o pedido em qualquer um dos dias marcados (contam os pedidos
      do primeiro; os dos outros dias da mesma semana não contam de novo);
    - quem não comprou em nenhum dos dias conta a visita sem pedido;
    - o quinzenal e o mensal olham a compra nos 7 ou 21 dias antes do primeiro dia marcado da semana.

    Exemplo: área de segunda a sexta, com 10 clientes semanais. Na semana, 6 compram na segunda, 3 na
    quarta e 1 não compra:

    | Dia | Pedidos | Visitas | Efetividade |
    |---|---|---|---|
    | Segunda a quinta | — | — | (fora da média) |
    | Sexta (o último dia marcado) | 9 | 10 | 90% |

    Se cada um contasse no dia em que comprou, e quem não comprou na sexta, a média dos dias daria 66,7%: segunda
    100%, quarta 100% e sexta 0%. O vendedor que não atende a área na sexta teria sempre uma sexta perto de 0%.
  - A semana entra inteira no período em que termina:
    - na campanha que começa numa quinta, a semana que fecha na sexta entra com os pedidos de segunda a quarta;
    - na que termina numa quinta, a última semana fica fora;
    - a semana em andamento só entra quando chega o último dia marcado.
  - Área de um dia só: a conta é a mesma de antes.
  - No painel de desempenho, os **atendimentos** do dia contam o cliente atendido no dia do pedido, e quem não foi
    atendido na semana, no último dia marcado. Assim, o painel de um dia mostra quem o vendedor atendeu nele.
  - Os dias de cada área ficam em **Configurar › Dias de atendimento**. Clientes em área sem dia ficam fora da conta
    (pedidos e visitas), e o andamento avisa quantos são. Diferente do Power BI, que contava os pedidos deles e não
    as visitas.
- **Frequência:** semanas com compra, somadas cliente a cliente, ÷ clientes positivados. A semana vai de domingo a
  sábado e é cortada na virada do mês, como no Power BI.
- **Preço médio por produto:** cada produto tem um preço-alvo (R$ por unidade), e a base de cada vendedor é o preço
  dele em cada produto. A meta é o aumento, não o preço cheio: com base R$ 10, alvo R$ 20 e preço de agora R$ 15, o
  vendedor está em 50%. Com vários produtos, soma em R$ nas quantidades vendidas agora: (preço de agora − o da base) ×
  quantidade ÷ (preço-alvo − o da base) × quantidade. Produto que já estava no alvo na base não pede aumento e só
  desconta se cair abaixo dele; produto sem preço na base fica fora. Os cards mostram o preço da base de cada um, e o
  detalhe, o preço de agora e o da base por produto. Nos objetivos (que não têm base), continua o índice: o que a
  equipe vendeu ÷ o que teria vendido as mesmas quantidades nos preços-alvo (100% = no alvo).
- **Personalizada:** faturamento, venda média por cliente, volume (produtos de uma unidade só), volume por cliente
  ou produtos distintos. Nos objetivos há também o crescimento sobre o período anterior
  ou o mesmo período do ano anterior (numa campanha, "crescer X%" é a meta Percentual: X% sobre a base).

- **Quem conta:** todos os clientes, ou só os novos (sem compra antes do início), os recuperados (sem compra há N dias
  ou mais; padrão 90), quem nunca comprou os produtos escolhidos ou quem já comprava. Na base, o "antes" é o começo
  do período da base. O histórico começa em `[cache] inicio`.
- **O que conta:** filtros opcionais de produtos, linhas, categorias, grupo (mussarela ou outras), UF, segmento e área
  comercial do cliente. Nada escolhido conta tudo. Efetividade e preço médio só têm filtros de cliente.
- As regras de venda são as de Metas: vendedor da venda (na efetividade e na % da carteira, o da carteira),
  equivalências de produto, produtos que "não contam" fora, devoluções dos motivos marcados, só clientes do cadastro
  (sem funcionário, fornecedor ou produtor).

### Objetivos do período

O indicador da equipe da região num período (por exemplo, mix médio da equipe em outubro e novembro), contra uma
meta da equipe. A conta é da equipe toda junta, sem repetir clientes entre os vendedores. A equipe é quem tem meta
nos meses do objetivo. Quem vê só parte da equipe vê a conta dos vendedores do acesso, com o aviso "conta só os seus
N de M vendedores".

### Histórico interno do vendedor

Clicar num vendedor abre o histórico dele, como uma conversa: cada campanha lançada (com a base e a meta dele), as
parciais de cada semana, o resultado com as barras de base, meta e resultado, e as **observações** (combinados,
conversas) que o administrador escreve no campo de baixo. É só controle interno: o vendedor não vê.

### Painel de desempenho

Veio do Painel Comercial (repositório `painel-mais-vida`), com as contas do bi-mais-vida. Fica abaixo da equipe, na
região escolhida, e mostra os vendedores com meta no mês (só os do acesso de quem vê). Tem duas abas: **Painel do
dia** (abaixo) e **Evolução mensal** (veja [Evolução mensal](#evolução-mensal)); a aba aberta fica guardada no
navegador.

- **Período**, nos atalhos do topo: **Último dia fechado** (o padrão: o último dia útil antes de hoje, pelo calendário
  da região), **Última semana** (a semana anterior, de segunda a domingo) ou **Hoje** (até a última cópia do banco,
  com o horário dela). Os números do período somam os dias dele; os do mês vão do dia 1º até o fim do período. A
  escolha fica guardada no navegador.
- **Destaque**: o faturamento do período da equipe contra a meta do período, o acumulado do mês contra a meta do mês e
  os dias úteis que restam.
- **Quadro**: uma coluna por vendedor (arrasta para o lado quando não cabe), com a **nota geral** (a média dos
  atingimentos, cada um no máximo 150%; na troca, o quanto do teto sobrou) e 9 linhas, cada uma com realizado, meta,
  % e barra. Passar o mouse numa linha mostra como ela é calculada.
- **Meta de venda diária por vendedor**, abaixo do quadro: uma barra por vendedor com o % da meta do período (de 0 a
  150%; o traço é a meta) ou, no botão **Ver tabela**, a venda, a meta, o atingido, os atendimentos sobre os
  clientes esperados, o ticket médio do período (venda ÷ clientes com nota, contra a meta do período ÷ os clientes
  esperados), o % de troca do mês e a situação. Passar o mouse na barra ou na meta mostra de onde ela veio: o saldo
  do mês, o potencial do dia e os pedidos em aberto. A escolha entre barras e tabela fica guardada no navegador.
- **Ficha**: clicar no nome de um vendedor abre os 9 cartões dele; o ⓘ de cada cartão explica a conta.
- **Sem avisos de cadastro** (decisão de 11/11/2026): o painel não mostra os avisos de clientes em área sem dia de
  atendimento nem de clientes sem frequência de compra no cadastro. As campanhas continuam avisando.
- **Cores**: verde a partir de 100% da meta, amarelo de 90% a 99%, vermelho abaixo de 90%. No % de troca, quanto menor
  melhor: verde até 1,0%, amarelo até 1,5% (o teto). Sem meta no período (dia sem cliente programado, mês sem
  planilha), a linha fica cinza com "sem meta".

| Indicador | Conta | De quem |
|---|---|---|
| Faturamento, mussarela e outras linhas (do período) | o realizado da página Metas (venda − devolução que desconta); a meta é a expectativa diária (abaixo) e, em mussarela e outras, a parte delas na meta do mês | vendedor da nota |
| Atendimentos (do período) | clientes com pedido no dia da rota ÷ clientes esperados no dia: semanal sempre, quinzenal sem compra nos 7 dias antes, mensal sem compra nos 21 dias antes (os dias de atendimento das áreas; na área com mais de um dia, uma visita por semana, que conta no dia do pedido ou, sem pedido, no último dia marcado) | carteira |
| Efetividade acumulada do mês | a das campanhas: a média da efetividade de cada dia (pedidos na rota ÷ visitas esperadas; a área de vários dias vale um dia por semana, o último marcado); meta de 100% | carteira |
| Frequência do mês | a das campanhas: semanas com compra ÷ clientes que compraram; meta: a média das compras esperadas desses clientes no mês inteiro, atendidos dentro da periodicidade e partindo da última compra antes do mês (o semanal que comprou no pedaço da semana que ficou no mês anterior não espera na primeira semana; na área com mais de um dia, uma compra por semana, contando do primeiro dia marcado dela) | vendedor da nota |
| Positivação | clientes distintos com nota no mês × META CLIENTE (como na página Metas) | vendedor da nota |
| Ticket médio | a venda média da página Metas: faturamento ÷ clientes × meta de faturamento ÷ META CLIENTE | vendedor da nota |
| % Troca | devoluções e brindes de vencido e danificado (pelo nome do motivo; os de PERDA ficam fora) ÷ faturamento bruto da carteira | dono do cliente |

No **BA**, onde a planilha não separa mussarela e outras em R$, a meta de cada uma é o volume da METAS PRODUTOS × o
preço médio do próprio vendedor no mês anterior (faturamento bruto ÷ volume; sem venda dele do produto, o preço da
região), ajustada para as duas somarem a meta de faturamento (a da planilha ou a aprovada).

**Expectativa diária** (a meta de venda do dia):

1. **Potencial do cliente**: a média do que ele comprou nos 2 meses fechados antes do mês (venda − devolução que
   desconta, de qualquer vendedor). Entram os clientes ativos da carteira atual do vendedor.
2. O potencial de cada cliente é dividido igualmente entre os dias de atendimento dele no mês (os dias da área, menos
   os feriados). O **potencial do dia** é a soma do que cai nele.
3. **Saldo** = meta do mês − faturado no mês até a véspera − **pedidos de venda em aberto** (feitos no mês, há menos de
   8 dias, sem nota e não cancelados; vêm dos [pedidos um a um](#pedidos-de-venda-no-cache)).
4. Com saldo, a meta do dia é a parte dele no saldo (pelo potencial do dia entre os dias que restam), **nunca abaixo
   do potencial normal do dia**. Com a meta do mês batida, a meta do dia volta a ser o potencial normal (não cobra
   venda acima da meta). Dia sem cliente programado: zero. Sem dia de atendimento pela frente e ainda com saldo: o
   saldo dividido pelos dias úteis que restam.

A conta é refeita a cada cópia nova do banco. Na semana, a meta é a soma da meta de cada dia, cada uma com o saldo
daquele dia. Os pedidos em aberto são os de agora: para um dia que já passou, o pedido que estava em aberto naquele
dia e já virou nota não entra (o cache ainda não guarda a data da nota de cada pedido).

#### Evolução mensal

Os últimos 12 meses (o de hoje é o último) da equipe da região ou, no seletor **Vendedor**, de um vendedor só. Na
equipe, cada mês soma os vendedores com meta naquele mês (só os do acesso de quem vê); um vendedor mostra tudo o que
ele vendeu, tenha tido meta ou não. As contas são as da página Metas, pelo vendedor da nota.

- **Faturamento por segmento**: uma pizza do mês escolhido (começa no mais recente), com a lista ao lado (valor e %
  de cada segmento e o total, que é o faturamento do mês). Passar o mouse numa fatia destaca o segmento. Vale o
  segmento de hoje no cadastro do cliente:

  | Fatia | Segmentos do cadastro |
  |---|---|
  | **FOOD** | restaurante, lanchonete e cafeteria, pizzaria, pastelaria, hamburgueria, churrascaria, hotel e pousada, buffet, fábricas de doce e de salgado, hospitais e prefeituras |
  | **PADARIAS** | padaria |
  | **REDES** | supermercado (por enquanto; um segmento "redes" no cadastro entra no lugar dele) |
  | **MERCADO** | mercearia, mercado, atacado e açougue |
  | **OUTROS** | o segmento "outros", o cliente sem segmento e a venda a funcionário, produtor ou fornecedor |

  A classificação fica em `bi/desempenho.py` (`_SEGMENTO_POR_PALAVRA`), pelas palavras do nome do segmento.
- **Cinco mini gráficos**, um ponto por mês (o mês sem dados quebra a linha; o do mês em andamento é o ponto vazado),
  com o valor do mês de hoje e a cor da situação:
  - **Atingimento da meta**: faturamento ÷ meta; o mês em andamento entra projetado pelo ritmo dos dias úteis (o
    faturamento ÷ os dias úteis passados × os dias úteis do mês). Linha da meta em 100%.
  - **Positivação**: clientes com nota ÷ META CLIENTE. Linha em 100%.
  - **Frequência**: semanas com compra ÷ clientes que compraram.
  - **% de troca**: vencido + danificado ÷ bruto da carteira, com a linha do teto (1,5%).
  - **Ticket médio**: faturamento ÷ clientes com nota.

  Passar o mouse num mês mostra o valor dele.

#### Simular a meta diária de um vendedor

Para conferir a conta à mão, o terminal monta a meta de cada dia do mês de um vendedor, com a meta que se quiser:

```
python app.py --simular "ricardo eu" --meta 100000 --planilha simulacao.xlsx
```

- **Antes de hoje**, com o realizado de verdade; **de hoje em diante**, a projeção: o vendedor vende exatamente a
  meta de cada dia, então o saldo de hoje se distribui pelos dias que restam.
- O vendedor vai pelo código ou por pedaços do nome (o da planilha e o do ERP, como "ricardo eu"); com mais de um
  achado, a resposta lista os códigos.
- **Opções:** `--meta` (sem ela, a da planilha ou a aprovada), `--mes AAAA-MM`, `--hoje AAAA-MM-DD` e `--faturado`
  (o faturado no mês até ontem, para os cenários "e se ele tivesse vendido X").
- A planilha tem três abas: **Resumo**, **Dias** (clientes programados, potencial, faturado antes, pedidos em aberto,
  saldo, meta do dia e realizado) e **Clientes** (potencial, representatividade, dias de atendimento e potencial por
  dia).
- No VPS: `docker compose exec bi python app.py --simular ... --planilha dados/simulacao.xlsx` (a pasta do sistema é
  montada no container: a planilha aparece em `dados/` no próprio VPS).
- Só lê: não grava nada no banco nem no cache, e pode rodar com o painel aberto.

### Quem vê o quê

- **Só o administrador** lança, edita, encerra, prorroga e exclui campanhas, cria objetivos e escreve observações.
- A **agenda** do topo é de cada um: quem tem a página cria, conclui e dá feedback nas próprias atividades. As
  **tarefas** são vistas por quem criou e pelos participantes (o administrador só vê as de que participa).
- Quem tem a página liberada **acompanha**: vê as campanhas, os objetivos e o histórico (com as observações) dos
  vendedores do acesso dela na Gestão, e só as regiões desses vendedores.
- Os vendedores de cada pessoa são os do acesso dela, escolhidos em **Usuários** (os mesmos de todas as páginas e da
  API pública).
- Em **Configurar**, o administrador marca os **dias de atendimento** de cada área comercial (vale para a
  efetividade).
  - São os dias em que o vendedor pode atender a área, um ou mais (veja a efetividade, acima).
  - O ponto de partida foi a planilha "Dia de Atendimento Areas Comerciais.xlsx" do Power BI, lida pela coluna
    numérica (a de texto tinha "Terça" com acento, que o Power BI não reconhecia).
  - Cada área pode ficar com dias, como **não atendida** (fora da conta, sem aviso) ou **pendente** (fora da conta,
    com aviso). Desmarcar todos os dias volta a área para pendente.
  - A área mexida continua na lista até trocar o filtro ou a busca, ou salvar, para dar para marcar vários dias.
  - **Usar o dia do nome nas pendentes** marca o dia que o nome diz, como em "TEIXEIRA (SEXTA)", ou os dias, como em
    "EUNÁPOLIS CENTRAL (SEGUNDA E TERÇA)".

### Minha agenda

No topo da Gestão fica a agenda de quem está vendo: cada pessoa vê e mexe só nas próprias atividades (nem o
administrador vê as dos outros) e vê as tarefas que criou ou de que participa (veja [Tarefas](#tarefas)) e, se
conectar, os eventos do Google Agenda dela, só para ver (veja [Google Agenda](#google-agenda-só-leitura)). Quem tem a
página Gestão tem a agenda, inclusive o visualizador, que na equipe só acompanha. O botão **−** minimiza a agenda e deixa só o título; o **+** mostra de novo (a escolha fica
guardada no navegador), e o link de um dia também abre. **Agenda | Kanban** troca a faixa de dias pelo
[kanban das tarefas](#kanban-das-tarefas) (a escolha também fica guardada; o link de um dia sempre abre a agenda).

- **Os dias do mês** ficam na mesma faixa do "Ritmo do mês" da página Metas, na largura toda do cartão, com hoje num
  quadrado maior. Em cada quadrado:
  - o número em cima é quantas atividades e tarefas o dia tem;
  - a barrinha embaixo do dia mostra as feitas (verde) e as que faltam (laranja; vermelho se o dia já passou), um
    pedaço por item (com mais de 6, só as duas partes);
  - a cor do quadrado diz como está o dia: com algo marcado, tudo feito ou com algo que ficou sem concluir;
  - passando o mouse, aparecem o total, as feitas, as que faltam e a lista do dia com o horário.

  As setas trocam de mês, e **Hoje** volta para o dia de hoje.
- **Clicar num dia** abre as atividades dele embaixo da faixa, as com horário primeiro, em ordem. O círculo marca a
  atividade como concluída. Se ela
  exige feedback, abre o campo para contar como foi, e só conclui com o texto escrito; se não exige, conclui na hora e
  o feedback pode ser acrescentado depois. Dá para editar o feedback e desfazer a conclusão. Dias que ainda não
  chegaram não podem ser concluídos.
- **Nova** (no cabeçalho, ou **Novo neste dia** no dia aberto) abre o formulário em **tela cheia**, com o seletor
  **Atividade | Tarefa** em cima; editar abre o mesmo formulário. **Cancelar**, o **×** ou Esc fecham (perguntando
  antes, se algo foi preenchido); Ctrl+Enter salva.
- **Escolher o dia** (o dia da atividade, o fim, o prazo da tarefa e o de cada subtarefa) é no mês inteiro em
  quadradinhos, como a faixa da agenda: cada um mostra o dia da semana, o número e, como na faixa, quantos itens o
  dia já tem e a cor dele (nas subtarefas de outra pessoa, sem a contagem, que é da sua agenda). O mês fica numa
  linha só; sem largura para isso (no celular), em semanas de segunda a domingo. As setas ao lado do nome do mês
  mostram o mês anterior e o seguinte, inteiros; o dia escolhido aparece à direita, e clicar nele volta para o mês
  dele. Com o foco num dia, as setas do teclado andam um dia (para cima e para baixo, uma semana). Os dias depois do
  prazo da tarefa ficam bloqueados nas subtarefas, e os antes do começo, no fim da atividade.
- **Atividade nova:** título, descrição, o dia (ou o primeiro dia, se repete), o horário (opcional: **Começa às** e,
  se quiser, **Termina às**), a repetição, um último dia opcional e se exige feedback ao concluir. Na agenda, o horário
  aparece como "14:00–15:00". As repetições:

  | Repetição | Acontece |
  |---|---|
  | Única | só no dia escolhido; com o último dia (**Até**), em todos os dias do início ao fim, cada um com o seu check (uma feira de 10 a 14/11: "De 10/11 a 14/11") |
  | Diária | todo dia; com "Só dias úteis", pula domingos, feriados e sábados sem expediente do calendário ES ou BA (o mesmo das metas, com os feriados extras de Configurações) |
  | Semanal | nos dias da semana marcados |
  | Mensal | num dia fixo do mês; o mês que não tem esse dia usa o último |
  | A cada N dias | contando do primeiro dia (quinzenal: 15) |

- **Horário ocupado:** com o começo do horário escrito, aparece a caixa **Horário ocupado**, que precisa do fim. Ela
  trava o horário da pessoa nos dias em que a atividade acontece, de hoje em diante: ninguém marca outra coisa para ela
  nesse horário. Exemplo, com a Ana ocupada em 30/10, das 14:00 às 15:00:

  | Tentativa | Resultado |
  |---|---|
  | A Ana cria uma atividade em 30/10 às 14:30 | recusa: "esse horário está ocupado por “Reunião com fornecedor” (30/10, 14:00–15:00)" |
  | A Ana cria uma atividade em 30/10, das 15:00 às 16:00, ou sem horário | pode |
  | O Beto cria uma tarefa com a Ana, prazo 30/10 às 14:30, ou uma subtarefa para ela até 14:00 | recusa: "Ana está com o horário ocupado em 30/10, das 14:00 às 15:00" (sem o título, que só a Ana vê) |
  | O Beto marca o mesmo horário como ocupado na agenda dele | pode: é outra pessoa |
  | A Ana marca como ocupado um horário em que já tem algo (uma atividade, ou uma tarefa ou subtarefa aberta) | recusa, dizendo o quê; numa tarefa de outra pessoa, ela pede a quem criou para mudar o prazo |

  A ocupada que se repete trava todos os dias em que acontece (entre duas que se repetem sem fim, o painel confere o
  próximo ano); os dias que já passaram e as tarefas e subtarefas concluídas não contam. Editar só confere o que
  mudou: trocar só o título não esbarra num conflito antigo. Dois itens sem "ocupado" continuam podendo ficar no mesmo
  horário.
- **Histórico de feedbacks** (o ícone de caderneta, nas atividades que se repetem ou duram vários dias): cada dia
  concluído com o feedback, quantas vezes ela aconteceu até hoje, quantas foram concluídas e os dias que ficaram sem
  concluir.
- **Editar** muda a atividade sem apagar o que já foi feito. **Encerrar** faz a atividade parar de se repetir depois
  de hoje (a de vários dias, terminar hoje) e mantém o histórico. **Excluir** apaga a atividade e todo o histórico
  dela.
- **Pelo Assistente** (para quem tem a Gestão), com a agenda de quem pergunta:
  - **resumos**, como "o que fiz esta semana?", "o que ficou atrasado?" ou "como foram as visitas ao Mercado do
    João?", com os feedbacks;
  - **mudanças**: criar ("visitar o Mercado do João toda segunda e quinta às 9h", "reunião amanhã das 14h às 15h,
    ocupado", "feira de 10 a 14/11"), mudar, encerrar, excluir ou concluir com feedback. Se o horário estiver ocupado,
    o Assistente conta e pergunta outro.

  O Assistente nunca grava sozinho: a resposta traz a proposta com um botão (**Adicionar à agenda**, **Salvar a
  mudança**, **Encerrar**, **Excluir** ou **Marcar como feita**), e só o clique aplica, uma vez só. Depois, o cartão
  mostra que foi feito e o link **Ver na agenda**, que abre a Gestão no dia. O Assistente ainda não vê as tarefas; os
  eventos do Google Agenda de quem pergunta, ele vê só para ler.

#### Tarefas

No formulário, **Tarefa** (em vez de **Atividade**) cria uma tarefa: título, descrição e o **prazo** (dia e
horário opcional) e, embaixo, um card por pessoa (você e os **participantes**) com as **subtarefas** dela, cada uma
com o próprio prazo, que vai até o da tarefa (sem prazo, vence com a tarefa).

- **Os cards das pessoas** começam recolhidos, só com o nome e quantas subtarefas cada uma tem. Clicar no nome abre
  o card (o que estava aberto se recolhe) com as subtarefas da pessoa e, embaixo, já uma subtarefa nova no prazo da
  tarefa, com o foco nos dias; clicar de novo recolhe. Quem entra na tarefa já tem o card aberto.
- **Criar as subtarefas: dia, nome, dia da próxima.** Na subtarefa nova, os dias ficam em cima e o nome (com o
  horário opcional ao lado) embaixo. Escolher o dia com o nome ainda vazio muda o dia dela e leva o cursor ao nome.
  Com o nome escrito, o dia escolhido é o da **próxima**: a que foi escrita fica guardada com o dia que tinha e abre
  outra, já no dia escolhido (o mesmo dia de novo abre a próxima nesse dia). Quem escreve o nome antes de escolher o
  dia fica com o prazo da tarefa. Enter no nome vai para os dias, sem salvar a tarefa; as setas do teclado só andam
  pelos dias, e Enter num deles escolhe. A subtarefa nova deixada em branco não conta ao salvar.

  | Você | Fica assim |
  |---|---|
  | Clica em 28, escreve "Levantar preços" | a subtarefa nova em 28/10, com o nome |
  | Clica em 29 | "Levantar preços · até 28/10" guardada; abre outra em 29/10 |
  | Escreve "Montar planilha" e clica em 29 de novo | "Montar planilha · até 29/10" guardada; abre outra em 29/10 |

- **Nome longo:** o nome da subtarefa aceita até 2000 caracteres (o título da tarefa e o da atividade, até 120), e a
  caixa cresce com o texto. O Enter continua indo para os dias (na janela da tarefa, cria a subtarefa). No dia e na
  janela da tarefa, o nome aparece inteiro; na subtarefa recolhida, na dica dos dias, nas mensagens e no sino, cortado.

- **As subtarefas no card** ficam recolhidas, só com o texto e o prazo (em vermelho, se passa do da tarefa). Uma de
  cada vez fica aberta para corrigir o prazo, o título e o horário: clicar numa recolhida abre ela, do mesmo jeito,
  com os dias em cima. Escolher um dia muda o dia dela, que se recolhe, e abre uma nova nesse dia; a seta à esquerda
  do título recolhe sem mudar o dia (e volta a subtarefa nova). Salvar com uma subtarefa sem título abre ela com o
  cursor no título.

- **Horário ocupado** (veja [Minha agenda](#minha-agenda)): o horário do prazo da tarefa vale para todas as pessoas
  dela, e o da subtarefa, para o responsável. Ele não pode cair no horário ocupado de ninguém: a mensagem diz quem e
  quando (sem o título da atividade, que só a pessoa vê). Ao editar, só o que entra ou muda é conferido: o prazo, as
  pessoas novas e as subtarefas novas ou mudadas.
- **Participantes** são os usuários ativos com a página Gestão. Quem entra já vem com **autonomia** marcada; quem
  criou pode tirar. Na janela da tarefa, o **+ Subtarefa** no card de cada um cria uma subtarefa para a pessoa (quem
  criou, para qualquer uma; quem tem autonomia, para si, escolhendo o dia até o prazo da tarefa).
- **Subtarefa automática** (migração 035): quem entra na tarefa com autonomia, ou ganha a autonomia depois, recebe a
  subtarefa **"Crie as suas subtarefas para programar a execução desta tarefa"**, com o selo **Automática**. Ela
  aparece em dois dias: o dia em que a pessoa entrou e o seguinte, pulando sábado e domingo (criada na sexta, fica na
  sexta e na segunda). É uma subtarefa só: concluída num dos dias, fica feita nos dois.

  | Prazo da tarefa (criada na terça, 03/11) | A automática |
  |---|---|
  | terça, 03/11 (o mesmo dia) | não é criada |
  | quarta, 04/11 (o dia seguinte) | só na terça |
  | sexta, 06/11 | na terça e na quarta |

  Ninguém edita a automática. Ela não entra no formulário de quem criou nem aparece nos dias da agenda de quem
  criou, só na janela da tarefa. Tirar a autonomia (ou a pessoa) apaga a automática, mesmo feita; devolver a autonomia cria
  outra, contando daquele dia. Se o prazo da tarefa encurtar, ela encurta junto. Vencida sem ser concluída, ela cobra a
  justificativa como as outras subtarefas. O aviso do sino de quem entra (ou ganha a autonomia) já pede para
  programar a execução, e a automática não tem o aviso "vence em breve".
- **Quem pode o quê:**

  | | Quem criou | Participante com autonomia | Participante sem autonomia |
  |---|---|---|---|
  | Editar e excluir a tarefa | sim | não | não |
  | Mudar a situação da tarefa, inclusive concluir e reabrir | sim | sim | sim |
  | Mudar prazos e responsáveis | sim | o prazo das subtarefas que criou para si | não |
  | Editar título e descrição de uma subtarefa (menos a automática) | todas | as próprias | não |
  | Criar subtarefa | para qualquer participante | só para si, escolhendo o dia | não |
  | Concluir uma subtarefa e mudar a situação dela | todas | as próprias | as próprias |
  | Justificar o atraso | da tarefa e das próprias subtarefas | das próprias subtarefas | das próprias subtarefas |

- **Na agenda:** a tarefa aparece no dia do prazo para todos; cada subtarefa, no dia do prazo dela (a automática,
  nos seus dois dias): quem criou vê todas (menos as automáticas dos outros), o participante vê as dele. O ícone de olho abre a tarefa com um card por pessoa e as subtarefas de todos, e
  ali cada um muda a situação da tarefa e a das suas subtarefas (e, com autonomia, edita o texto delas e cria
  subtarefas para si).
- **Situação:** a tarefa e cada subtarefa estão **A fazer**, **Fazendo** ou **Concluída**. Na janela da tarefa, quem
  pode mudar vê os três botões (na tarefa, todos); os outros veem só a situação. Concluir pelo círculo da agenda é o
  mesmo que Concluída; desfazer volta para onde estava (Fazendo, se tinha começado).
- **Concluir:** tarefa e subtarefa podem ser concluídas a qualquer dia, até antes do prazo, e mostram quem concluiu.
  Concluir a tarefa faz as subtarefas que faltavam contarem como feitas; reabrir traz elas de volta.
- **Atrasadas:** o que passou do prazo sem concluir (com horário, logo depois dele; sem horário, quando o dia acaba)
  fica vermelho no dia do prazo (o que venceu hoje ganha o aviso "Venceu às 10:00") e, o dos dias anteriores, aparece
  também no bloco **Atrasadas** do dia de hoje, até ser concluído.
- **Justificar o atraso:** depois do prazo (sem concluir, ou concluída depois dele), quem responde pela tarefa (quem
  criou) ou pela subtarefa (o responsável) conta por que atrasou: no dia e na janela da tarefa (**Justificar o
  atraso**, ou **Justificar de novo**). As justificativas formam um **histórico**, que não se edita nem se apaga: todos
  da tarefa veem, com quem escreveu, quando e, se o prazo mudou depois, de que prazo era; no dia aparece a última, e
  na janela da tarefa, todas. O card do kanban ganha o chip **Atraso justificado**. A justificativa não tira o item
  das atrasadas.
- **Justificativa obrigatória:** vencida e ainda aberta, a tarefa ou a subtarefa bloqueia o painel de quem responde
  por ela, em qualquer página, até ele justificar (a janela não fecha; o painel confere a cada minuto e ao voltar para
  a aba). A janela mostra quando venceu, a última justificativa (quando pede de novo) e o aviso **"Caso queira
  prorrogamento do prazo, solicite ao criador da tarefa"** (para quem criou: editar a tarefa depois de justificar);
  **Enviar e concluir** é para quem já terminou. Se continuar atrasada, a justificativa é pedida de novo **24 horas**
  depois; a de um prazo que foi prorrogado não vale para o novo. Exemplo, com a subtarefa do Beto até 27/10 às 10:00:

  | Quando | O que acontece | O painel do Beto |
  |---|---|---|
  | 27/10 10:01 | venceu sem concluir | bloqueia até ele justificar |
  | 27/10 10:15 | Beto justifica | libera |
  | 28/10 10:15 | 24 horas depois, ainda aberta | bloqueia de novo, com a justificativa anterior |
  | 28/10 11:00 | quem criou prorroga para 31/10 | não está mais atrasada |
  | 01/11 00:00 | venceu o prazo novo | bloqueia já (a justificativa de antes era de outro prazo) |
  | 01/11 08:00 | Beto justifica e conclui | sai da lista |

  A subtarefa de uma tarefa concluída conta como feita e não pede nada; a concluída depois do prazo também não obriga
  (a justificativa continua possível).
- **Editar** (só quem criou) muda tudo. Tirar um participante tira junto as subtarefas dele (a página pergunta
  antes); para passar uma subtarefa a outra pessoa, use o lápis dela na janela da tarefa. Se um participante mudou a
  tarefa enquanto o formulário estava aberto, o Salvar avisa e pede para abrir de novo. **Excluir** apaga a tarefa e
  as subtarefas para todos.

#### Kanban das tarefas

Em **Kanban**, as tarefas que você criou ou de que participa ficam em colunas pelo **vencimento** do prazo da tarefa
(o mesmo para todos da tarefa), e as concluídas numa coluna à parte. As subtarefas não aparecem no kanban.

| Coluna | O que entra (exemplo: hoje é sexta, 30/10) |
|---|---|
| **Vencido** | as abertas que passaram do prazo: com horário, logo depois dele; sem horário, quando o dia acaba (até 29/10, ou 30/10 com o horário já passado) |
| **Vence hoje** | as abertas com prazo hoje que ainda não venceram (30/10) |
| **Vence essa semana** | as abertas até o domingo desta semana, que vai de segunda a domingo (31/10 e 01/11); no domingo, fica vazia |
| **Vence depois** | todas as outras abertas (de 02/11 em diante) |
| **Concluídas** | as concluídas nos últimos 30 dias |

- **A ordem:** nas colunas das abertas, pelo prazo (no mesmo dia, pelo horário; as sem horário por último); em
  Concluídas, as mais recentes em cima. Embaixo do nome, cada coluna mostra o período que ela cobre.
- **O card** mostra o título, o prazo (vermelho se venceu), **Fazendo** se a tarefa já começou, quem criou (se não
  foi você), quantas pessoas participam, quantas subtarefas suas faltam e o andamento das subtarefas. Se uma
  subtarefa sua venceu ou vence hoje antes da tarefa, o card avisa (**Sua subtarefa venceu**, **Sua subtarefa vence
  hoje**), mas continua na coluna do prazo da tarefa.
- **Clicar no card** abre a janela da tarefa, com a situação dela e a de cada subtarefa (veja **Situação** acima). O
  card não se arrasta: a situação se muda na janela. Concluída, a tarefa vai para Concluídas; reaberta, volta para a
  coluna do prazo.
- **Nova**, no kanban, já abre o formulário em **Tarefa**.

#### Notificações (o sino)

Quem tem a página Gestão vê, no topo de qualquer página, um **sino** à esquerda do nome, com o número de notificações
não lidas. Clicar abre a lista com as 50 mais recentes; clicar numa abre a tarefa na Gestão e marca como lida, e
**Marcar todas como lidas** zera o número. A **lixeira** de cada notificação (aparece ao passar o mouse; no celular,
sempre) tira ela do sino, e **Excluir todas**, depois de confirmar, tira todas; não dá para desfazer. O painel confere
a cada minuto e ao voltar para a aba. Ninguém recebe aviso do que ele mesmo fez, e as notificações ficam guardadas por
90 dias.

| Aviso | Quem recebe | Exemplo |
|---|---|---|
| Incluído numa tarefa | quem entrou (um aviso só, com as subtarefas dele) | "Ana incluiu você na tarefa “Feira de novembro” (prazo 30/10 às 14:00), com 2 subtarefas para você" |
| Subtarefa nova para você | o responsável, se outra pessoa criou ou passou a subtarefa para ele | "Ana criou a subtarefa “Levantar preços” para você (até 28/10)" |
| Prazo mudou | o responsável (subtarefa) ou os participantes (tarefa) | "Ana mudou o prazo de “Levantar preços” para 31/10" |
| Vence em breve | subtarefa: o responsável; tarefa: todos dela | "“Levantar preços” vence amanhã (28/10)" |
| Venceu | quem criou a tarefa, nas subtarefas dos outros | "A subtarefa “Levantar preços”, de Beto, venceu sem ser concluída (28/10)" |
| Concluída | subtarefa: quem criou a tarefa; tarefa: todos dela | "Beto concluiu a subtarefa “Levantar preços” (tarefa “Feira de novembro”)" |
| Justificativa enviada | quem criou a tarefa | "Beto justificou o atraso de “Levantar preços”: “o fornecedor não respondeu”" |

Os avisos de prazo nascem quando o painel de quem recebe pergunta, uma vez só por item e por prazo: prorrogado, o
prazo novo avisa de novo. "Vence em breve" sai no dia de antes e no do prazo, até vencer; "venceu" sai só para os
prazos dos últimos 7 dias, para não chegar uma enxurrada de atrasos antigos. A tarefa excluída leva as notificações
dela. A notificação excluída no sino não volta: ela só fica escondida até completar os 90 dias (migração 036), porque
apagada de vez, o aviso de prazo, que sai uma vez só, sairia de novo no minuto seguinte. Um prazo novo (prorrogado)
avisa de novo, como antes.

#### Google Agenda (só leitura)

Cada pessoa pode trazer para a agenda os compromissos do Google Agenda dela. O BI **só lê**: nada é escrito no Google.
Funciona no site (bi.maisvida.cloud), onde o `config.ini` tem `[google]` preenchido; no PC, a janela avisa que fica
lá.

- **Conectar:** o botão **Google** da agenda abre a janela, e **Entrar com o Google** abre o login do Google numa
  janelinha:
  1. a pessoa escolhe a conta Google;
  2. aparece **"O Google não verificou este app"**: ela clica em **Avançado** e em **Acessar bi.maisvida.cloud**. O
     aviso aparece porque o BI é um app interno, sem a verificação que o Google faz nos apps públicos;
  3. o Google pergunta se o BI pode **ver as agendas** dela (só ver): **Continuar**;
  4. a janelinha fecha, e a agenda principal da conta já aparece, lida.

  A janela lista as agendas da conta (as dela, as compartilhadas com ela, os feriados), e a pessoa liga as que quer
  ver no BI, até 5 no total. Ela pode conectar até 3 contas Google. O BI relê as ligadas a cada 10 minutos; a janela
  mostra quando cada uma foi lida, **Atualizar agora** (que também traz as agendas criadas depois no Google) e a
  lixeira, que desconecta a conta.
- **A autorização:** o Google dá ao BI uma autorização de só leitura, guardada cifrada com a chave de `[google]` (fora
  do banco e das cópias de segurança dele); ela não volta para a página e não vai para o log. Desconectar no BI também
  avisa o Google, que tira o BI da lista de apps com acesso à conta. Se a pessoa tirar o acesso pelo Google (Conta ›
  Segurança › Apps de terceiros com acesso), a agenda e o botão Google avisam para entrar com o Google de novo.
- **Privacidade:** a tela de permissão do Google mostra a política do BI, em `/privacidade.html` (aberta sem login):
  o que o BI lê do Google, o que guarda, para que usa e como cortar o acesso.
- **O login é da pessoa que está no BI:** a volta do Google só vale na mesma sessão do BI que começou o login, uma vez
  e por 10 minutos. Um link de login aberto por outra pessoa não liga a agenda dela à conta de quem mandou.
- **Na agenda:** os eventos aparecem no dia, depois dos itens do BI, com o chip "Google · nome da agenda", só para ver
  (sem o círculo de concluir). Não entram no número do quadrado, na barrinha, nas cores nem nas contagens do escolher
  o dia, que são do que há para fazer: uma faixinha azul em cima do quadrado e a dica do mouse mostram que o dia tem
  evento do Google. O evento que passa da meia-noite aparece nos dois dias. Ficam de fora os cancelados e os convites
  que a pessoa recusou.
- **Trazer como atividade** (o **+** do evento): abre o formulário de atividade nova já com o título, o dia e o
  horário do evento; o de dia inteiro de vários dias vira a atividade única de vários dias. É uma cópia: depois, as
  duas ficam independentes.
- **Horário ocupado:** o evento marcado como **Ocupado** no Google (o "Mostrar como" do evento; o de dia inteiro vem
  como Disponível, a não ser que a pessoa mude) ocupa o horário dela, como o horário ocupado da agenda:

  | Tentativa (Ana tem no Google uma consulta em 30/10, das 14:00 às 15:00, Ocupado) | Resultado |
  |---|---|
  | Beto cria uma tarefa com Ana em 30/10 às 14:30, ou uma subtarefa para ela nesse horário | recusa: "Ana está com o horário ocupado em 30/10, das 14:00 às 15:00" (sem o título e sem dizer que veio do Google) |
  | O mesmo em 12/11, com as férias de Ana no Google marcadas como Ocupado (dia inteiro) | recusa: "Ana está com o dia 12/11 ocupado" |
  | Ana cria uma atividade às 14:30, ou se põe numa tarefa ou subtarefa nesse horário | grava, com o aviso amarelo "Você tem “Consulta médica” no Google em 30/10, das 14:00 às 15:00" |
  | Ana traz a consulta como atividade (o mesmo horário) | grava sem aviso |
  | O evento está como Disponível, o prazo não tem horário ou a agenda não é lida há mais de 24 horas | pode |

  O que já estava marcado no BI não muda quando a pessoa marca algo no Google depois. Ao editar, o aviso só aparece
  se o dia ou o horário mudaram.
- **Quando a leitura falha:** os eventos da última leitura ficam. Se a autorização caiu (a pessoa tirou o acesso no
  Google, ou a chave do servidor mudou), a agenda e o botão Google avisam na hora para entrar com o Google de novo, e
  a conta para de ser lida até lá. Se uma agenda saiu da conta no Google, ela é marcada; o **Atualizar agora** a tira
  da lista. Se é passageiro (o Google fora do ar), o BI tenta de novo sozinho, espaçando as tentativas até 2 horas, e
  só avisa depois de uma hora sem ler. Com mais de 24 horas sem leitura, os eventos aparecem como "pode estar
  desatualizado" e não travam ninguém. Quem é desativado ou perde a página Gestão deixa de ser lido.
- **Assistente:** em "o que tenho amanhã?", ele vê também os eventos do Google de quem pergunta, só para ler (não
  propõe mudar nenhum). Se a atividade que ele propõe cai num horário ocupado do Google, a proposta traz o aviso.

### Pelo Assistente

- **Lançar (só o administrador):** o Assistente traduz o pedido em texto para a região, o indicador, o prazo e o
  alvo. Exemplos:
  - "+1 no mix médio por 3 semanas para o Rubens e a Samira";
  - "subir a venda média em 10% para a equipe BA em novembro";
  - "recuperar as padarias sem compra há 60 dias";
  - "efetividade de 80% para a equipe ES";
  - "mussarela 4kg a R$ 39 o quilo".

  Ele confere tudo e mostra um **rascunho** embaixo da resposta, com a base de cada vendedor (quando os dados já
  cobrem o período) e os botões **Lançar ação** e **Revisar no painel** (abre o formulário preenchido, com os
  vendedores marcados). Nada é gravado antes do clique, e clicar de novo não lança outra.
- **Acompanhar:** "como está a ação de mix do ES, vendedor por vendedor?". O Assistente acha a ação e responde com
  os mesmos números da página (base, alvo, resultado). Quem não é administrador só acompanha, e só os vendedores do
  acesso dele na Gestão.
- No detalhe de uma ação, **Perguntar ao Assistente** abre uma conversa nova com a pergunta escrita (não envia
  sozinho).

## Página Reavaliação de Crédito

A página **Reavaliação Credito** do Power BI, para avaliar o crédito de um cliente: quanto ele compra, se paga em
dia, quanto deve e quanto ainda cabe no limite.

- **Filtros:** um ou mais clientes, mês, ano e vendedor.
  - **Clientes:** a busca acha por nome ou código, sem acento nem caixa. Cada cliente marcado vira uma etiqueta, e a
    lista fica aberta para marcar outros da mesma busca (ex.: as lojas de uma rede). Com vários clientes, os limites e
    o que está em aberto **somam**, e o topo mostra cada cliente com o limite e o restante dele.
  - **Mês e ano** valem pela **data de emissão** do título; mês sem ano vale para aquele mês em todos os anos.
  - **Vendedor:** o **do título**, não o da carteira do cliente (como no Power BI).
- **Cartões:**
  - **Valor total das compras**, **Quantidade de compras** e **Ticket médio** (valor ÷ quantidade);
  - **Pontualidade:** títulos quitados até 7 dias depois do vencimento ÷ títulos quitados;
  - **Limite de crédito**, com o **prazo** (a opção de pagamento do cadastro) e o vendedor da carteira;
  - **Inadimplência:** títulos em aberto vencidos há mais de 7 dias, pelo valor do título;
  - **Limite já utilizado:** tudo o que o cliente ainda tem em aberto (todos os títulos em aberto dele, de qualquer
    emissão e vendedor, menos as parcelas já pagas), com quantos títulos são e quanto do limite isso usa. Quando há
    parcelas pagas, mostra os títulos em aberto e o que já foi pago deles;
  - **Limite restante:** limite − limite já utilizado.
- **Títulos:** um por linha, com emissão, vencimento, quitação, valor, **valor já pago**, dias de atraso e a situação
  (a vencer, vencido, inadimplente, quitado, quitado com atraso).
  - **Ordenar:** clique no nome de qualquer coluna; de novo, para inverter. A ordem vale para todos os títulos do
    filtro, não só para os que aparecem. Sem ordem escolhida, vai do mais recente ao mais antigo.
  - Sem cliente escolhido, mostra os 500 primeiros do filtro na ordem escolhida.
- **Valor já pago** (não existe no Power BI): nos boletos divididos (7, 14, 21 dias…), o valor das parcelas já
  quitadas mais o que entrou numa parcela paga em parte, com "1 de 3 parcelas". Juros e abatimento não contam. O
  vencimento do título é o da última parcela.
- **Base:** os títulos a receber de venda a cliente (origem VENDA, tipo CLIENTE) que não foram cancelados, o mesmo
  filtro de todas as medidas da página no Power BI. Os dias de atraso contam até o dia da extração dos dados.
- **Bloqueio no ERP** (não existe no Power BI): se o cliente está bloqueado hoje no cadastro do ERP (`CLIENTES.BLOQUEADO`),
  desde quando (`DATABLOQUEADO`) e a observação escrita lá (`OBSBLOQUEADO`). O cliente bloqueado ganha o selo vermelho
  "Bloqueado no ERP" e a observação embaixo do nome; o desbloqueado que ficou com a observação do bloqueio antigo mostra
  a observação em cinza. Com vários clientes, a tabela ganha a coluna do bloqueio (a observação no balão), e a busca
  marca quem está bloqueado. O bloqueio **não muda o parecer** (decisão do usuário): ele aparece ao lado, para quem
  analisa ver o motivo antes de liberar. O ERP não guarda o histórico, só como o cliente está agora. Em 11/11/2026 eram
  74 clientes ativos bloqueados (1.300 contando os inativos) e 92 desbloqueados com observação.
- **Quem vê:** quem tem a página marcada em Usuários vê todos os clientes e vendedores; ela não tem configuração.

Diferenças em relação ao Power BI, combinadas com o usuário:

1. **Pontualidade em %.** No Power BI o cartão tem formato de número inteiro e mostra só 0 ou 1.
2. **Limite restante sem o período e com as parcelas pagas.** No Power BI, com mês e ano escolhidos, só os títulos em
   aberto emitidos no período eram descontados, e o restante parecia maior. Aqui desconta todos os títulos em aberto
   do cliente, e as parcelas já pagas dos boletos divididos voltam para o limite (no Power BI, o título inteiro
   continuava descontado até a última parcela).
3. **Limite, restante e prazo só com cliente escolhido.** Sem cliente, o Power BI somava o limite de todos os
   clientes e ignorava o filtro de vendedor nesses cartões. Aqui dá para escolher vários clientes, e os limites deles
   somam. O cartão **Limite já utilizado** não existe no Power BI.
4. **Tabela de títulos:** um título por linha, ordenável por qualquer coluna, com o valor já pago, em vez da matriz
   por data que somava os dias de atraso dos títulos do mesmo dia.
5. **Sem a tabela de preço médio por produto:** no Power BI ela usa uma medida ("Preço Medio Ultimo Trimestre") que
   não existe mais no modelo.

### Reanálises

Com um cliente escolhido, depois do parecer de um limite novo, quem tem a página **registra a reanálise**: o limite
liberado (vem com o valor analisado; 0 corta o crédito), o prazo liberado (uma caixa com os prazos que os clientes têm
no ERP, na ordem dos dias) e a justificativa (de 10 a 2.000 letras). O painel grava junto o **retrato** do cliente
naquele momento, calculado no servidor a partir dos dados (a página não manda números). Depois de algumas centenas de
registros, isso vira a base para uma IA ajudar nas decisões de crédito.

- **O painel não muda o ERP:** depois de registrar, a pessoa muda o limite e o prazo lá. O cartão **Reanálises deste
  cliente** mostra as anteriores (da mais nova para a mais antiga, com os números do dia) e compara a última com o
  cadastro de hoje: já aplicado, aguardando a próxima atualização dos dados ou diferente.
- **Só no site:** o banco do PC é outro, e as reanálises ficam todas num lugar só. No painel do PC, a página avisa.
- **Não dá para editar:** quem registrou ou um administrador exclui e registra de novo. A excluída some da página e do
  Assistente, mas fica guardada no banco (com quem excluiu e quando).
- **Os dados mudaram no meio:** se chegou uma extração nova entre analisar e registrar, o registro é recusado e a
  página refaz o parecer, para o retrato ser o que a pessoa viu. O mesmo envio repetido (clique duplo) grava uma vez.
- **O que vai no retrato** (`retrato`, um JSON com `versao`; datas AAAA-MM-DD, "hoje" = o dia da extração):
  - `cliente` e `cadastro`: o limite e o prazo de antes (com os dias do prazo: "14, 21 E 28 DIAS" = [14, 21, 28];
    A VISTA = [0]), o vendedor da carteira, cidade, UF, área, segmento, rede, se está inativo, a data de cadastro e o
    bloqueio no ERP naquele dia (`bloqueado_no_erp`, `data_do_bloqueio_no_erp` e `observacao_do_bloqueio_no_erp`;
    vazios nas reanálises de antes, ou enquanto o bloqueio não chegou do computador da empresa);
  - `historico`: os cartões da página com todos os títulos (compras, quantidade, ticket médio, pontualidade,
    inadimplência), o primeiro e o último título, os meses de cliente e os dias sem compra;
  - `aberto_hoje`: os títulos em aberto, o que já foi pago em parcelas, o limite restante e o % usado, o que está a
    vencer, os vencidos até 7 dias, os inadimplentes e o maior atraso em aberto;
  - `ultimos_12_meses` (os números da regra do parecer): títulos, compras e compras por mês, meses com compra,
    pontualidade, atraso médio dos atrasados, atraso ponderado pelo valor (pagamento adiantado conta negativo), maior
    atraso, quitados com mais de 30 dias de atraso, prazo real e o maior saldo em aberto;
  - `ultimos_3_meses` (90 dias): compras e pontualidade;
  - `mes_a_mes`: os 12 meses completos antes do mês de hoje, com compras, títulos e quitados no prazo e com atraso;
  - `vendas_12_meses`: venda bruta, devoluções não canceladas (de qualquer motivo) e a taxa de devolução, dias com
    venda e produtos (só do cadastro de clientes);
  - `parecer`: a regra do dia (`regra`) e o parecer do valor pedido e do liberado (sem o do liberado quando ele é 0),
    com cada critério, o limite sugerido e o valor ÷ o maior saldo.
- **O que aconteceu depois** não é gravado: sai dos títulos emitidos depois do registro, que o ERP guarda. O
  Assistente calcula na hora: títulos emitidos depois, quantos dos que venceram há mais de 7 dias foram pagos em dia
  (quem não pagou continua na conta), a inadimplência de hoje, o maior saldo em aberto contra o limite liberado e se o
  cadastro já está com ele.
- **Assistente:** a ferramenta `reanalises_credito` traz até 15 reanálises (as de um cliente, todas, ou as de outros
  clientes com os números mais parecidos com os de hoje dele) e um resumo por parecer da regra. A comparação usa
  pontualidade em 12 meses, compras por mês, maior saldo em aberto, tempo de cliente, inadimplência e, com um pedido,
  o pedido ÷ o maior saldo. As reanálises entram como referência ao lado do parecer da regra, sem trocá-lo.
- **Prazo mínimo entre reanálises** (em **Configurar**, só o administrador; começa desligado, 0 dias): depois de uma
  reanálise do cliente, um **aumento** de limite (liberado maior que o limite do cadastro de hoje) só pode ser
  registrado a partir do dia dela + o prazo. Redução, corte e manter o limite passam sempre; a reanálise excluída não
  conta. O administrador pode registrar mesmo assim, marcando "Registrar mesmo assim", e a reanálise guarda a regra
  que valia (coluna `bloqueio`, que a página mostra como "passou do bloqueio" e o Assistente recebe). Duas pessoas
  registrando o mesmo cliente ao mesmo tempo passam uma de cada vez.
- O retrato leva também o último envio do Serasa do cliente (`serasa`: emissão, idade, fundação, score, faixas,
  pontualidade em R$ e anotações), ou `null` quando não há nenhum.

### Dados do Serasa

Com um cliente escolhido, quem tem a página envia o **PDF do Relato – Pessoa Jurídica** do Serasa (até 10 MB e 20
páginas). O servidor lê o texto do PDF (`pypdf`, sem IA nem OCR: o relatório vem do Chrome, com texto) e guarda só:

- a **data de fundação**;
- o **score** (de 0 a 1000), com a probabilidade de inadimplência, o risco e o aviso da caixa vermelha quando ela
  não traz a probabilidade (ex.: "DEFAULT - DIVIDA VENCIDA COM INSTITUICAO FINANCEIRA HA MAIS DE 90 DIAS");
- o **histórico de pagamento comercial**: os títulos por faixa de atraso (pontual, 8-15, 16-30, 31-60, +60 e à vista:
  quantidade e %) e a pontualidade em R$ (total, médio e % de cada faixa e do mês). O Serasa dá intervalos ("200 A
  250", "6 MIL A 6,5 MIL"): ficam o texto e os números de/até;
- as **anotações negativas**: PEFIN, REFIN, dívidas vencidas, protestos, cheques sem fundos, ações judiciais e
  falências, com a quantidade e o valor ("NÃO CONSTAM OCORRÊNCIAS" = 0). Uma linha que não dá para ler fica sem número,
  com o texto que veio, e a página manda conferir no PDF.

Regras:

- **O PDF não fica guardado:** é lido na memória e descartado. O atraso médio mês a mês, os fornecedores, os sócios e
  as consultas ao Serasa ficam de fora.
- **Idade:** conta da data em que o Serasa emitiu o relatório (pode chegar hoje um PDF antigo). Passando da validade
  (em Configurar; padrão 90 dias), a página mostra "Desatualizado". Aparecem também quando e por quem foi enviado.
- **Cliente certo:** se a razão social e o nome fantasia do relatório não batem com o nome e a razão social do
  cadastro (sem LTDA, EPP…), a página pergunta antes de gravar.
- **Vários envios:** cada envio é uma linha nova; a página mostra o de emissão mais recente e os anteriores. O mesmo
  PDF de novo para o cliente não grava outra vez. Quem enviou ou um administrador exclui (a linha fica guardada).
- **Só no site**, como as reanálises; no painel do PC, a página avisa.
- Faltando o CNPJ, a data de emissão ou a tabela das anotações, o arquivo é recusado (não é o relatório). Sem score,
  grava e mostra "não veio no relatório"; com o histórico vazio (empresa sem histórico no Serasa), a página diz isso.

### Cores da página

Só verde (bom) e vermelho (ruim), num tom cada, pelo que cada número é comparado: pontualidade com o "ok" da regra do
parecer (90%), inadimplência com zero, o que está em aberto com o limite (o restante com zero), o atraso e a situação
do título com a tolerância de 7 dias, os critérios do parecer (atenção e bloqueio são vermelhos; "Indicado com
ressalvas" é verde, com o ícone de alerta), a idade do Serasa com a validade, as anotações com zero. O que bate exato
fica verde; o que não é comparado com nada (compras, quantidade, ticket, limite, score) fica cinza. Botões, campos e o
cliente escolhido seguem o padrão do painel.

## Banco de dados

O painel usa dois bancos, cada um para uma coisa:

- **DuckDB** (`dados/cache.duckdb`): a cópia das vendas, devoluções e cadastros do ERP. É refeito a cada extração
  e só é lido.
- **PostgreSQL:** o que as próprias pessoas criam no painel.

| Tabela | O que guarda |
|---|---|
| `usuarios` | acessos: nome, login, senha em hash, papel, páginas e o que cada um vê nelas: os vendedores (`escopo`, migração 040), as abas de Metas (`visoes`) e as abas e os quadros de supervisor das Premiações (`premiacoes`, migração 041) |
| `regras` | as regras de Metas, os vendedores de Projeções, as regras da Sugestão de Metas (migração 024), as das Premiações (migração 034) e as do crédito, o prazo mínimo entre reanálises e a validade do Serasa (migração 038); cada Salvar vira uma versão nova, com quem salvou e quando |
| `conversas` e `mensagens` | o histórico do Assistente, de cada usuário |
| `assistente_perguntas` | o registro de uso do Assistente: pergunta, consultas, tokens e custo |
| `campanhas` e `campanha_vendedores` | as ações e os objetivos da página Gestão (coluna `tipo`): região, período, indicador (`metrica`, `parametros`, filtros), alvo, quem lançou, e os vendedores com a base e o resultado congelado (no preço médio, também o preço de cada produto: `base_precos` e `resultado_precos`, migração 013) |
| `gestao_eventos` | o histórico interno de cada vendedor: observações e o que aconteceu nas ações dele (lançada, editada, prorrogada, encerrada, resultado) |
| `campanha_produtos` | o preço-alvo de cada produto nas ações e objetivos de preço médio |
| `areas_atendimento` | os dias de atendimento de cada área comercial (efetividade) |
| `metas_aprovadas` | as metas aprovadas na Sugestão de Metas (migração 025): uma linha por gravação (vale a última de cada vendedor × mês; `aprovada` falso = retirada), com o total, a mussarela e as outras linhas, os clientes, o retrato da sugestão (`sugerida_fat`, `sugerida_mus`, os clientes da carteira) e a meta de volume de cada produto (`produtos`) |
| `sugestao_ajustes` | os ajustes de volume da página Sugestão de Metas (migração 037): uma linha por ajuste em vigor (mês da meta × vendedor × área × produto; área 0 no ES), com o volume e quem salvou; apagar volta para a fórmula |
| `agenda_atividades` e `agenda_registros` | a agenda de cada pessoa: as atividades com a repetição e o horário, e cada dia concluído com o feedback (migrações 018 e 019); o fim do horário, o horário ocupado e a única de vários dias (migração 026) |
| `agenda_propostas` | as propostas do Assistente para a agenda que a pessoa já confirmou no botão, para não aplicar duas vezes (migração 019) |
| `agenda_tarefas`, `agenda_tarefa_pessoas` e `agenda_subtarefas` | as tarefas da agenda: o prazo, quem participa (quem criou também, e com que autonomia) e as subtarefas de cada um, com o prazo e a conclusão (migração 020) e quando começou a ser feita, a coluna Fazendo do kanban (migração 021), a justificativa do atraso (migração 022, passada para `agenda_justificativas` pela 027) e quem concluiu a tarefa (migração 023); o título da subtarefa vai até 2000 caracteres (migração 030); a subtarefa automática, com os dois dias em que aparece (migração 035). Excluir um usuário apaga as tarefas que ele criou e as subtarefas dele nas dos outros |
| `agenda_justificativas` | o histórico das justificativas do atraso de cada tarefa e subtarefa: quem escreveu, quando e o prazo que tinha vencido (migração 027) |
| `notificacoes` | as notificações do sino: para quem, o tipo, o texto, a tarefa, quando foi lida e quando foi excluída (a excluída fica escondida até a limpeza dos 90 dias); os avisos de prazo têm uma chave, para sair uma vez só (migrações 028 e 036) |
| `google_contas`, `google_agendas` e `google_eventos` | o Google Agenda de cada pessoa, só leitura (migrações 031 e 032): as contas Google conectadas (o e-mail, a autorização cifrada e se ela caiu), as agendas de cada conta (o id da agenda no Google, se é a principal, se está ligada, a assinatura da última leitura, quando foi lida e o último erro) e os eventos lidos das ligadas, uma linha por ocorrência (título, início e fim, dia inteiro e se está ocupado). Desconectar a conta leva as agendas e os eventos dela; só o site usa |
| `credito_reanalises` | as reanálises de crédito, só no site (migração 029): uma linha por registro, que não muda depois, com o cliente, o limite e o prazo de antes, o limite pedido, o liberado e o prazo liberado, a justificativa, o parecer da regra para o pedido e para o liberado, o limite sugerido, a extração usada (`dados_ate`), o retrato do cliente (`retrato`, veja [Reanálises](#reanálises)) e quem registrou; a excluída fica com `excluida_em`; a registrada pelo administrador dentro do prazo mínimo guarda a regra em `bloqueio` (migração 038) |
| `credito_serasa` | os dados do Serasa, só no site (migração 038): uma linha por envio, que não muda depois, com o cliente, o CNPJ e a razão social do relatório, a emissão, o hash do arquivo (o mesmo PDF não grava duas vezes), a fundação, o score e o resto em `dados` (veja [Dados do Serasa](#dados-do-serasa)) e quem enviou; o excluído fica com `excluido_em` |
| `parametros` | o segredo que assina os cookies de sessão |

O PC e o site têm cada um o seu PostgreSQL, com cadastros separados. No PC é o PostgreSQL instalado no Windows; no
site, o container `bi_banco`, ao lado do painel, sem porta aberta para a internet. Os dois têm cópia de segurança
diária. A instalação e a manutenção estão em
[docs/publicacao_vps.md](docs/publicacao_vps.md#banco-de-dados-postgresql). O painel acha o banco pela seção
`[postgres]` do `config.ini`.

Sem o banco (fora do ar ou sem configurar), ninguém entra no painel: a tela de login avisa. A extração do ERP e o
envio dos dados ao site continuam funcionando, e o painel volta sozinho quando o banco responder.

As tabelas são criadas e atualizadas sozinhas quando o painel sobe, pelos arquivos de `bi/migracoes/`. Na primeira
subida com o banco, a migração `005_importar_arquivos.py` traz o que estava nos arquivos da pasta do painel
(`usuarios.json`, `config_metas.json`, `config_projecoes.json` e `logs/assistente-*.jsonl`). Os arquivos ficam
onde estão, só como cópia: o painel não os lê mais. Nessa subida todos entram de novo uma vez, porque o cookie de
sessão mudou.

Para mudar o banco, crie um arquivo novo em `bi/migracoes/` com o número seguinte (ex.: `010_tarefas.sql`). Nunca
edite uma migração que já foi aplicada: ela não roda de novo. A `008_indicadores.sql` converteu as campanhas antigas
para os tipos novos, e a `009_gestao_equipe.sql` trouxe as ações, os objetivos e o histórico: depois delas, voltar o
código para uma versão anterior exige restaurar o banco.

## Login e acessos

Todo mundo entra com usuário e senha. Há dois papéis:

| Papel | Vê | Pode mexer |
|---|---|---|
| **Administrador** | todas as páginas, abas e vendedores | Configurações, Usuários e o botão Atualizar dados |
| **Visualizador** | só as páginas marcadas e, nelas, só os vendedores do acesso | só a própria senha |

Em Usuários ficam os dados da pessoa (nome, usuário, senha, papel), as páginas que ela vê e os **vendedores que ela vê**,
que valem para todas as páginas (inclusive o Assistente, a API pública e a Reavaliação de Crédito):

- **Todos os vendedores**, inclusive os sem equipe (terceirizados) e os que entrarem depois;
- **Só as equipes** marcadas (BA, ES, Edir): o vendedor novo dessas equipes entra sozinho. A equipe de cada vendedor
  fica em Metas › Configurar › Vendedores;
- **Só alguns vendedores:** a lista que você marcar.

O que é próprio de uma página fica no **Configurar** dela: em Metas, as **abas** que a pessoa vê ("Abas por
usuário"); dentro delas, só os vendedores do acesso (a aba sem nenhum deles não aparece para ela). Em Premiações, as
**abas** e os **quadros de supervisor** ("Acesso por usuário"); o quadro de um supervisor só aparece com "Todos" ou "Só
as equipes" com a equipe do estado dele. Os terceirizados das Devoluções aparecem com "Todos". Na Reavaliação
de Crédito, a pessoa só acha os clientes da carteira dos vendedores dela (ou com títulos deles) e vê só os títulos
desses vendedores; o limite, o em aberto e o parecer são do cliente inteiro. Quem é criado precisa ter os vendedores
escolhidos para salvar. Quem foi cadastrado antes de uma página existir não a recebe sozinho: o administrador marca a
página nova.

Exemplos:

- **Supervisor da BA:** em Usuários, "Só as equipes" BA e Edir; em Metas › Configurar, as abas Metas BA e Produtos BA;
  em Premiações › Configurar, as abas Vendedores e Supervisores, com o quadro do Marcos.
- **Vendedor:** em Usuários, "Só alguns vendedores" com só ele; em Metas, a aba dele. Indicadores, ranking, corrida e
  tabelas mostram só os números dele.

Quem barra é o servidor: o visualizador recebe só os números liberados, mesmo se mexer no endereço da página.
Mudanças de páginas, abas e vendedores valem na hora. Trocar a senha ou desativar alguém derruba as sessões abertas
dessa pessoa.

Na página **Usuários** (só para administradores):

- **Novo:** nome, usuário e senha. O botão **Gerar** cria uma senha aleatória (e copia, quando o navegador
  deixa) para você passar à pessoa.
- **Páginas que pode ver** (Metas, Projeções, Sugestão de Metas, Premiações, Devoluções, Assistente, Gestão, Reavaliação de Crédito).
- **Vendedores que vê:** todos, só as equipes ou só alguns (veja acima). Embaixo aparece o que muda de uma página
  para outra (as abas de Metas e as de Premiações, com o link **Configurar**, os terceirizados, os clientes do
  Crédito). Um aviso lembra quando a pessoa tem Metas ou Premiações mas ainda nenhuma aba, ou ainda não tem vendedores.
- **Acesso ativo:** desativar bloqueia a entrada sem apagar o cadastro.

Para todos: o menu com o nome, no canto superior direito, tem **Trocar minha senha** e **Sair**. A sessão dura
12 horas, ou 30 dias com "Manter conectado neste aparelho". Depois de 5 senhas erradas seguidas, o usuário
espera 15 minutos para tentar de novo.

### Abrir para outros computadores da rede

No `config.ini`, em `[servidor]`, troque `endereco = 127.0.0.1` por `endereco = 0.0.0.0` e abra o painel de
novo. O terminal mostra o endereço para os outros computadores (ex.: `http://192.168.0.10:8050`). Na primeira
vez, o Windows pergunta se libera o Python no firewall: libere em **rede privada**.

O painel usa HTTP sem criptografia. Na rede interna da empresa isso basta.

### Publicar na internet (VPS)

O painel roda num VPS com HTTPS, e o banco do ERP continua na empresa. Este computador extrai o cache e manda ao
VPS só ele e as planilhas (uns 10 MB compactados), sozinho, depois de cada cópia nova do banco. O passo a passo
está em [docs/publicacao_vps.md](docs/publicacao_vps.md).

### Outros aplicativos (API pública)

Outro aplicativo pode mostrar a página **Gestão** pela API pública (`https://bi.maisvida.cloud/api/v1`). Ela só lê: o
quadro de cada região, o detalhe das campanhas e dos objetivos e o histórico interno dos vendedores. Agenda, tarefas e
notificações ficam de fora.

- A pessoa entra no outro aplicativo com o usuário e a senha do BI. O aplicativo recebe uma chave dela e passa a ver a
  Gestão como ela vê no site, com o mesmo papel e os mesmos vendedores e regiões. Só quem tem a página Gestão consegue
  entrar.
- No menu com o nome, **Aplicativos conectados** mostra os aplicativos em que a pessoa entrou, com a data do último uso
  e a validade. **Desconectar** apaga a chave, e o aplicativo pede o login de novo.
- A chave vale 90 dias. Trocar a senha, ou o administrador desativar a pessoa, desconecta todos os aplicativos dela.
- O BI guarda só uma "impressão digital" de cada chave (o hash), nunca a chave em si.
- Para desligar a API sem publicar código, use `ativa = nao` em `[api]` no `config.ini` e reinicie o painel.

O guia para quem programa o outro aplicativo (rotas, respostas, erros e limites) está em
[docs/api_publica.md](docs/api_publica.md).

### Esqueci a senha do administrador

No computador do painel, abra um terminal na pasta do projeto e rode:

```bash
python app.py --senha LOGIN
```

O comando pede a senha nova duas vezes, reativa o usuário e derruba as sessões abertas. Se o login não
existir, ele cria um administrador com esse nome. No site, o comando roda dentro do container (veja
[docs/publicacao_vps.md](docs/publicacao_vps.md#esqueci-a-senha-de-administrador-do-site)).

## Página Configurações (das metas)

Abre pelo botão **Configurar** da página Metas. Tudo é gravado no banco: cada Salvar vira uma versão nova, com quem
salvou e quando, e as anteriores ficam guardadas. O padrão reproduz exatamente as fórmulas do Power BI. O botão
"Restaurar padrão do Power BI" volta a ele. Para voltar a uma versão anterior, veja
[docs/publicacao_vps.md](docs/publicacao_vps.md#voltar-as-regras-para-uma-versão-anterior).

- **Produtos:** cada produto conta como **Mussarela**, **Outras linhas** ou **Não conta**. Os de outras
  linhas podem ter uma categoria (Bebida Láctea, Manteiga etc.). Produto novo entra como outras linhas.
  - O faturamento é mussarela mais outras linhas.
  - Os alertas mostram produtos que parecem mal classificados (ex.: 12551 Mussarela Mais Natural Fatiada
    está na linha de mussarela do ERP, mas o Power BI contava em outras linhas).
- **Vendedores:** grupo de cada vendedor (ES, BA, Edir ou Oculto), ou seja, em quais abas ele aparece.
  Vendedor novo que ainda não foi configurado segue o supervisor do ERP.
- **Devoluções:** quais motivos de devolução descontam do faturamento (padrão: 1, 2, 5, 6, 7, 8 e 9) e se
  as devoluções canceladas são ignoradas.
- **Dias úteis e feriados:** feriados nacionais e estaduais automáticos, peso do sábado por estado e
  exceções (feriado local, meio expediente, dia trabalhado).
- **Abas por usuário:** para cada visualizador, se ele vê a página Metas e quais **abas** (os vendedores dentro
  delas são os do acesso dele, em Usuários; a aba sem nenhum deles ganha um aviso e não aparece para ele). O quadro
  azul resume o que a pessoa vai ver. Fica gravado no cadastro do usuário, não nas regras, e "Restaurar padrão do
  Power BI" não mexe nele. As regras e as abas são salvas juntas: se uma parte não puder ser gravada, nada é gravado. Quem é criado em Usuários com a página Metas começa sem abas (a página fica vazia
  para ele) até você escolher aqui.

## Regras de cálculo (iguais ao Power BI)

- **Faturamento:** soma dos itens das vendas não canceladas, pela data e pelo vendedor da venda, menos as
  devoluções dos motivos marcados, pela data de entrada e pelo vendedor da devolução.
- **Clientes:** clientes distintos com venda no mês. No total, quem comprou de dois vendedores conta uma vez.
- **Venda média:** faturamento ÷ clientes. A meta de venda média é meta de faturamento ÷ meta de clientes,
  também no total.
- **Produto 3643** (Bebida Láctea bandeja 540 g) conta como 11469, como no Power BI.
- **Metas da METAS.xlsx** (faturamento, mussarela, outras linhas e clientes) são arredondadas para número
  inteiro, como o Power BI faz ao importar (ex.: R$ 492.767,08 vira R$ 492.767,00).

### Diferenças em relação ao Power BI

1. **Dias úteis:** saem do calendário com feriados, não do número fixo 21 nem do "−2" ajustado à mão.
2. **Devoluções canceladas:** não descontam do faturamento. Dá para desligar em Configurações.
3. **Total da meta de venda média:** é meta de faturamento ÷ meta de clientes. O Power BI somava as médias
   de cada vendedor.
4. **Vendas com data errada no futuro** (ex.: ano 7190) ficam de fora.
5. **Reavaliação de Crédito:** veja as diferenças na [seção da página](#página-reavaliação-de-crédito).
6. **Sugestão de Metas:** veja as [diferenças da sugestão](#diferenças-em-relação-ao-power-bi-sugestão).

## Arquivos

| Arquivo | O que faz |
|---|---|
| `app.py` | servidor local e rotas da API |
| `bi/cache.py` | leitura do Firebird e cache DuckDB (os pedidos de venda e a rede dos clientes, para a efetividade, os títulos a receber, as parcelas e os limites, para o crédito, os brindes e a comissão, para as premiações, vêm em grupos à parte: se a leitura falhar, o resto segue) |
| `bi/metas.py` | cálculo das visões |
| `bi/projecoes.py` | projeção do faturamento bruto (modelo, faixa e filtros da página Projeções) |
| `bi/sugestao.py` | página Sugestão de Metas: a conta das páginas de sugestão do Power BI, os faturamentos das áreas, as regras da página (tabela regras), o resumo dos vendedores, a ferramenta do Assistente e a aba de aprovação das metas |
| `bi/premiacoes.py` | página Premiações: o prêmio de cada vendedor (faixas sobre a META CLIENTE) e de cada supervisor (os regulamentos de nov/2026: parcelas por indicador, trava, bônus e desconto pelo vencido), a comissão dos vendedores (a gravada no ERP − devoluções − brindes), as regras da página (tabela regras) e as metas dos supervisores |
| `bi/devolucoes.py` | página Devoluções: o que voltou na entrega (nota a nota) e o vencido e danificado no cliente por causa e responsável, a comparação com a média dos 6 meses anteriores, os produtos, segmentos, frequência de visita e clientes, a tabela dos vendedores e os dados do Parecer (blocos dos vendedores, limites dos produtos e rankings) |
| `bi/parecer_pdf.py` | o Parecer de Devoluções em PDF (fpdf2), no formato do documento de antes, e o zip com as pastas BA, ES e TERCEIRIZADOS |
| `bi/aprovacao.py` | metas aprovadas (tabela metas_aprovadas): a distribuição do volume pelo R$ aprovado e as planilhas de metas com as aprovadas por cima, que a Calculadora lê, e a diferença de um ajuste de volume somada na aprovada |
| `bi/ajustes.py` | ajustes de volume da página Sugestão de Metas (tabela sugestao_ajustes): os em vigor, em memória, e a gravação que leva a diferença para a meta aprovada na mesma transação |
| `bi/credito.py` | página Reavaliação de Crédito: cartões (um ou vários clientes), títulos com o valor já pago e a ordem da tabela, a busca de cliente, o parecer de um limite novo, os prazos do ERP, o retrato de uma reanálise e o que aconteceu depois dela |
| `bi/reanalise.py` | as reanálises de crédito (tabela credito_reanalises, só no site): registrar com o retrato, listar, excluir e o que o Assistente lê (por cliente e parecidas); as regras do crédito (tabela regras) e o prazo mínimo entre reanálises |
| `bi/serasa.py` | os dados do Serasa (tabela credito_serasa, só no site): a leitura do PDF do Relato PJ, enviar, listar, excluir e o último envio para o retrato |
| `bi/assistente.py` | página Assistente: dados de cada acesso, ferramentas de consulta e chamada à API da Anthropic |
| `bi/arquivos.py` | os arquivos Excel e PDF que o Assistente prepara para baixar (formatos das colunas, montagem) |
| `bi/conversas.py` | histórico de conversas do Assistente (no PostgreSQL) |
| `bi/gestao.py` | página Gestão: ações, objetivos, histórico e dias de atendimento das áreas (no PostgreSQL), base, alvo, resultado e o quadro |
| `bi/desempenho.py` | o painel de desempenho da Gestão: o período, os 9 indicadores de cada vendedor, a meta de mussarela e outras do BA pelo volume e a expectativa diária, a evolução mensal (a pizza de segmentos e os mini gráficos), a meta de venda de hoje da página Metas e a simulação (`web/js/desempenho.js` desenha) |
| `bi/simulacao.py` | o texto e a planilha .xlsx da simulação da meta diária (`python app.py --simular`) |
| `bi/agenda.py` | agenda de cada pessoa, no topo da Gestão: as atividades de cada pessoa, em que dias cada repetição acontece, a conclusão com feedback e o histórico (no PostgreSQL) |
| `bi/tarefas.py` | as tarefas da agenda: prazo, participantes com ou sem autonomia, subtarefas (e a automática, que pede para programar a execução), quem pode o quê, o que aparece em cada dia, as atrasadas, as justificativas do atraso (um histórico) e o que cada pessoa precisa justificar agora, a situação de cada tarefa e subtarefa e o kanban (as tarefas pelo vencimento) (no PostgreSQL) |
| `bi/notificacoes.py` | as notificações do sino: gravar (na transação de quem avisa), listar, contar as não lidas, marcar como lidas e excluir (no PostgreSQL) |
| `bi/google_agenda.py` | o Google Agenda, só leitura: o login com o Google (state, PKCE e a autorização cifrada), a lista de agendas de cada conta, a leitura dos eventos pela API do Google Agenda, de tempos em tempos, o que a agenda mostra e os eventos ocupados que o horário ocupado confere (no PostgreSQL) |
| `bi/indicadores.py` | os indicadores das ações (positivação, com a % da base, mix médio, efetividade, frequência, preço médio, Personalizada) e a conta do andamento |
| `bi/carteira.py` | o histórico da carteira: a cada extração, os trechos de cada cliente ativo (vendedor, área, segmento), gravados só quando algo muda, no PostgreSQL e no cache |
| `bi/uso.py` | registro de uso do Assistente: limites do dia e a tela "Uso e custo" (no PostgreSQL) |
| `bi/banco.py` | conexão com o PostgreSQL e as migrações |
| `bi/migracoes/` | tabelas do PostgreSQL, em ordem (`001_conversas.sql`, …), aplicadas sozinhas quando o painel sobe |
| `bi/calendario.py` | dias úteis e feriados de ES e BA |
| `bi/configuracao.py` | regras editáveis, padrões do Power BI e as versões das regras no banco |
| `bi/acesso.py` | usuários (no PostgreSQL), senhas (PBKDF2), sessões assinadas e permissões |
| `bi/planilhas.py` | leitura das planilhas de metas |
| `bi/fb.py` | conexão somente leitura com o Firebird 2.1 (a mesma do Painel Comercial ES) |
| `bi/publicacao.py` | envio do cache e das planilhas ao VPS (no PC) e recebimento com conferência (no VPS) |
| `web/` | página: HTML, CSS (identidade do Guia da Marca 2026) e JavaScript |
| `logs/bi.log` | registro de atualizações e erros |
| `tests/` | testes automáticos: `python -m unittest discover -s tests -t .` (os do PostgreSQL rodam só com `BI_TESTE_POSTGRES`; veja `tests/apoio.py`) |
| `config.exemplo.ini` | modelo do `config.ini` (sem as senhas) |
| `docs/analise_pbi_metas.md` | análise do Power BI original: tabelas, medidas DAX e divergências encontradas |
| `docs/publicacao_vps.md` | como o painel está publicado no VPS e como mantê-lo |
| `deploy/` | Dockerfile e docker-compose do painel e do banco no VPS, e as cópias de segurança do banco (`backup_banco.sh` no VPS, `backup_banco_pc.ps1` no PC) |

Ficam fora do repositório (`.gitignore`): `config.ini` (senhas), `banco.env` (senha do PostgreSQL no site), `dados/`
(cache com as vendas), `logs/`, `marca/` (guia da marca em PDF) e os arquivos de antes do banco (`usuarios.json`,
`config_metas.json`, `config_projecoes.json` e as cópias `.anterior.json`), que ficam na pasta só como cópia.

## Se algo der errado

- **"Preparando os dados" não termina:** veja `logs\bi.log`. O mais comum é o serviço
  *Firebird Server - DefaultInstance* parado.
- **Porta ocupada:** use `python app.py --porta 8051`.
- **Outro computador não abre o painel:** confira `endereco = 0.0.0.0` no `config.ini` e se o firewall do
  Windows liberou o Python em rede privada.
- **Números estranhos depois de mexer nas regras:** use "Restaurar padrão do Power BI" em Configurações.
- **Assistente "não configurado":** falta a chave em `[ia]` no `config.ini` do servidor, ou o painel não foi
  reiniciado depois de colocar a chave.
- **Assistente "a chave da API não foi aceita" ou "a API recusou o pedido":** confira a chave e o crédito no
  Console da Anthropic (platform.claude.com). O motivo exato fica em `logs/bi.log`.
- **Tela "Banco de dados fora do ar" ou "o banco de dados está fora do ar":** o PostgreSQL parou ou não responde.
  - No PC: confira se o serviço *postgresql-x64-18* está em execução (Win + R, `services.msc`) e inicie se não
    estiver.
  - No site: `cd /opt/bi-mais-vida/deploy && docker compose ps` e `docker compose logs banco --tail 50`.

  O painel volta sozinho quando o banco responder, e o envio dos dados ao site não para.
- **Tela "o banco de dados não está configurado" ou "falta instalar o pacote do banco de dados":** falta a seção
  `[postgres]` no `config.ini` (com a senha) ou o `pip install "psycopg[binary]" psycopg-pool`. Depois, reinicie o
  painel.
- **Tela "a atualização das tabelas do banco de dados falhou":** uma migração de `bi/migracoes/` deu erro. O motivo
  está em `logs/bi.log`. Depois de resolver, reinicie o painel.
- **Assistente "os dados por cliente ainda não chegaram":** o site ainda tem o cache de antes desta versão. Ele
  chega depois da próxima extração do PC, que já acontece sozinha uma vez quando o painel do PC abre com a versão
  nova.

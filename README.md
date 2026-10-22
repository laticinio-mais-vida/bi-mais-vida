# BI de Metas Mais Vida

Versão em Python das páginas de metas do Power BI (Metas ES, Metas BA, Metas Edir, Metas Produtos BA e
Metas Outras Linhas ES), reunidas numa página só, com abas por visão e filtros de vendedores, meses e anos
(todos de seleção múltipla), e uma página de Configurações para as regras que antes ficavam dentro das
fórmulas DAX. A página **Projeções** prevê o
faturamento bruto dos próximos 6 meses. A página **Assistente** responde perguntas sobre os dados com IA
(Claude). A página **Gestão** acompanha a equipe por região: objetivos, campanhas por vendedor (com base, meta e resultado) e o
histórico interno de cada vendedor.

As páginas ficam na **barra lateral** à esquerda. O botão no topo dela recolhe a barra (só os ícones; o nome
aparece ao passar o mouse) ou expande, e o painel lembra a escolha neste navegador. No celular, a barra vira
uma gaveta que abre pelo botão de menu do topo. **Usuários** fica na seção Administração, que só o
administrador vê. Cada página tem a sua configuração, no botão **Configurar** da barra de filtros dela (só para
administradores): em Metas abre as Configurações das metas; em Projeções, as Configurações das projeções; no
Assistente, o que cada pessoa consulta e o uso; na Gestão, os vendedores que cada pessoa acompanha.

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
arquivos Excel e PDF que ele prepara. No VPS, tudo já vem na imagem.

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
cada um (quantas, quantas pagas e quanto já foi pago) e o limite de crédito e o prazo de cada cliente.

- **Cópia do banco nova:** o painel percebe sozinho em até 1 minuto, mesmo sem nenhuma página aberta, e
  atualiza o cache em segundo plano (cerca de 40 segundos). O botão **Atualizar dados** força a leitura na hora.
- **Planilhas de metas:** são relidas sempre que o arquivo muda. Se estiverem abertas e bloqueadas, vale a
  última leitura boa e aparece um aviso no painel.

## Página Metas

As abas no topo substituem as páginas do Power BI:

| Aba | Equivale a | Vendedores |
|---|---|---|
| Metas ES | Metas ES | grupo ES |
| Metas BA | Metas BA | grupo BA |
| Metas Edir | Metas Edir | grupo Edir |
| Outras Linhas ES | Metas Outras Linhas ES | grupo ES |
| Produtos BA | Metas Produtos BA | grupos BA e Edir |

Filtros (todos de seleção múltipla, com Aplicar; nada marcado é todos):

- **Vendedores:** um ou vários. Clicar num vendedor no ranking, no nome dele na tabela ou no cartão de
  Produtos BA mostra só ele; clicar de novo volta para todos. Com Ctrl (Cmd no Mac) o clique soma ou tira o
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
  do mês e quanto falta por dia útil.
- **Corrida da meta:** acumulado do mês contra o ritmo esperado de cada dia, com a projeção.
- **Ranking** dos vendedores. Clicar num vendedor filtra a página por ele.
- **Detalhamento por vendedor** no mesmo formato das matrizes do Power BI: indicadores nas linhas,
  vendedores nas colunas (ordem alfabética) e Total no fim. Metas em azul e categorias em amarelo.
  - Em Outras Linhas ES, a tabela "Falta Outras Linhas / Dentro da meta?" fica num cartão separado, com o
    próprio Copiar imagem, para mandar as duas imagens separadas no WhatsApp.
  - Em Produtos BA a tabela traz Meta e Realizado por vendedor, com os produtos em ordem alfabética.
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
- **Acesso por usuário:** para cada visualizador, se ele vê a página e quais vendedores aparecem para ele:
  - **Igual a Metas** (padrão): as equipes das abas de Metas e os vendedores liberados em Metas › Configurar. Se o acesso
    de Metas mudar, este muda junto;
  - **Todos da página;**
  - **Só alguns:** a lista que você marcar.
  Os totais somam só as carteiras dos vendedores que a pessoa vê. Administradores veem todos os vendedores da página.

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

O botão **Configurar** da página (só administradores) tem duas seções:

- **Acesso por usuário:** para cada visualizador, se usa o assistente e quais vendedores consulta. Os modos são:
  - **Igual a Metas** (padrão): as equipes das abas de Metas e os vendedores liberados lá;
  - **Todos;**
  - **Só alguns.**
- **Uso e custo:** perguntas e custo estimado por pessoa nos últimos 30 dias, o gasto de hoje e as últimas
  perguntas.

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
prazo e os títulos a receber estão no cache, mas só vão para a IA nas perguntas de quem tem a página Reavaliação de
Crédito; para os outros, esses dados nem existem na cópia que a IA consulta.

## Página Gestão

A **Gestão da equipe**, separada por região (**ES** e **BA**; o Edir é da BA, com o calendário dela):

- no topo, os **objetivos do período** da região;
- abaixo, as **campanhas**, com duas barras: o tempo que falta (aviso quando faltam 5 dias ou menos) e o andamento
  contra a meta (nas encerradas, o resultado final e quantos vendedores ficaram na meta);
- e um **quadrado por vendedor** da equipe, com uma etiqueta por campanha em vigor e o % da meta dele até agora.

As cores do andamento seguem o % da meta, sem olhar o prazo, num degradê contínuo: vermelho até 50%, passando pelo
laranja até o amarelo em 80% e pelo verde-amarelado até o verde em 100%; acima disso, o verde fica cada vez mais
forte até 150%. Na barra da campanha, o % é a soma dos resultados ÷ a soma das metas
nos indicadores que somam (positivação, faturamento, volume), a média do % de cada vendedor nos que são médias (mix,
efetividade, frequência) e, no preço médio, os aumentos feitos ÷ os pedidos, somando os vendedores em R$ (na média, quem
estava a centavos do alvo e subiu poucos centavos ficaria com centenas de % e puxaria a campanha); quem ainda não tem
meta (base aguardando os dados) fica de fora.

A equipe é quem tem meta no mês na planilha METAS, como na página Metas: contas da casa (venda interna, funcionário,
produtor) ficam fora. Quem está numa campanha em vigor aparece mesmo sem meta.

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

- **Positivação:** clientes distintos com venda no período.
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
  - Visitas esperadas: cada cliente ativo da área recebe uma visita em cada dia de atendimento dela que cai no
    período. Feriados contam, como no Power BI.
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
- **Personalizada:** faturamento, venda média por cliente, volume (produtos de uma unidade só), volume por cliente,
  % da carteira que comprou ou produtos distintos. Nos objetivos há também o crescimento sobre o período anterior
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

### Quem vê o quê

- **Só o administrador** lança, edita, encerra, prorroga e exclui campanhas, cria objetivos e escreve observações.
- Quem tem a página liberada **acompanha**: vê as campanhas, os objetivos e o histórico (com as observações) dos
  vendedores do acesso dela na Gestão, e só as regiões desses vendedores.
- O acesso de cada pessoa se escolhe no botão **Configurar** da página: **Igual a Metas** (padrão), **Todos** ou
  **Só alguns**, como em Projeções e no Assistente.
- Também em **Configurar**, o administrador marca os **dias de atendimento** de cada área comercial (vale para a
  efetividade).
  - O ponto de partida foi a planilha "Dia de Atendimento Areas Comerciais.xlsx" do Power BI, lida pela coluna
    numérica (a de texto tinha "Terça" com acento, que o Power BI não reconhecia).
  - Cada área pode ficar com dias, como **não atendida** (fora da conta, sem aviso) ou **pendente** (fora da conta,
    com aviso).
  - **Usar o dia do nome nas pendentes** marca o dia que o nome diz, como em "TEIXEIRA (SEXTA)".

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

## Banco de dados

O painel usa dois bancos, cada um para uma coisa:

- **DuckDB** (`dados/cache.duckdb`): a cópia das vendas, devoluções e cadastros do ERP. É refeito a cada extração
  e só é lido.
- **PostgreSQL:** o que as próprias pessoas criam no painel.

| Tabela | O que guarda |
|---|---|
| `usuarios` | acessos: nome, login, senha em hash, papel, páginas e o que cada um vê nelas |
| `regras` | as regras de Metas e os vendedores de Projeções; cada Salvar vira uma versão nova, com quem salvou e quando |
| `conversas` e `mensagens` | o histórico do Assistente, de cada usuário |
| `assistente_perguntas` | o registro de uso do Assistente: pergunta, consultas, tokens e custo |
| `campanhas` e `campanha_vendedores` | as ações e os objetivos da página Gestão (coluna `tipo`): região, período, indicador (`metrica`, `parametros`, filtros), alvo, quem lançou, e os vendedores com a base e o resultado congelado (no preço médio, também o preço de cada produto: `base_precos` e `resultado_precos`, migração 013) |
| `gestao_eventos` | o histórico interno de cada vendedor: observações e o que aconteceu nas ações dele (lançada, editada, prorrogada, encerrada, resultado) |
| `campanha_produtos` | o preço-alvo de cada produto nas ações e objetivos de preço médio |
| `areas_atendimento` | os dias de atendimento de cada área comercial (efetividade) |
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
| **Visualizador** | só as páginas e abas marcadas e, se quiser, só alguns vendedores | só a própria senha |

Em Usuários ficam só os dados da pessoa (nome, usuário, senha, papel) e as páginas que ela vê. O que ela vê
dentro de cada página fica no botão **Configurar** da própria página, em "Acesso por usuário": em Metas, as
abas e os vendedores; em Projeções, no Assistente e na Gestão, os vendedores (o padrão é igual ao acesso de Metas). A
Reavaliação de Crédito não tem configuração: quem tem a página vê todos os clientes. Quem foi cadastrado antes de uma
página existir não a recebe sozinho: o administrador marca a página nova.

Exemplos (em Metas › Configurar › Acesso por usuário):

- **Supervisor da BA:** abas Metas BA e Produtos BA e "Todos dessas abas" em Vendedores.
- **Vendedor:** a aba dele e só ele marcado em Vendedores. Indicadores, ranking, corrida e tabelas mostram só
  os números dele.

Quem barra é o servidor: o visualizador recebe só os números liberados, mesmo se mexer no endereço da página.
Mudanças de abas e vendedores valem na hora. Trocar a senha ou desativar alguém derruba as sessões abertas
dessa pessoa.

Na página **Usuários** (só para administradores):

- **Novo:** nome, usuário e senha. O botão **Gerar** cria uma senha aleatória (e copia, quando o navegador
  deixa) para você passar à pessoa.
- **Páginas que pode ver** (Metas, Projeções, Assistente, Gestão, Reavaliação de Crédito). Embaixo aparece, só para consulta, o que a pessoa vê em cada
  página marcada, com o link **Configurar** para mudar na configuração da página. Um aviso lembra quando a
  pessoa tem Metas mas ainda nenhuma aba.
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
- **Acesso por usuário:** para cada visualizador, se ele vê a página Metas, quais **abas** e quais
  **vendedores** ("Todos dessas abas" inclui quem entrar depois; "Só alguns" fixa a lista). O quadro azul resume
  o que a pessoa vai ver. Fica gravado no cadastro do usuário, não nas regras, e "Restaurar padrão do Power BI"
  não mexe nele. As regras e os acessos são salvos juntos: se uma parte não puder ser gravada, nada é gravado. Quem é criado em Usuários com a página Metas começa sem abas (a página fica vazia
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

## Arquivos

| Arquivo | O que faz |
|---|---|
| `app.py` | servidor local e rotas da API |
| `bi/cache.py` | leitura do Firebird e cache DuckDB (os pedidos de venda e a rede dos clientes, para a efetividade, e os títulos a receber, as parcelas e os limites, para o crédito, vêm em grupos à parte: se a leitura falhar, o resto segue) |
| `bi/metas.py` | cálculo das visões |
| `bi/projecoes.py` | projeção do faturamento bruto (modelo, faixa e filtros da página Projeções) |
| `bi/credito.py` | página Reavaliação de Crédito: cartões (um ou vários clientes), títulos com o valor já pago e a ordem da tabela, e a busca de cliente |
| `bi/assistente.py` | página Assistente: dados de cada acesso, ferramentas de consulta e chamada à API da Anthropic |
| `bi/arquivos.py` | os arquivos Excel e PDF que o Assistente prepara para baixar (formatos das colunas, montagem) |
| `bi/conversas.py` | histórico de conversas do Assistente (no PostgreSQL) |
| `bi/gestao.py` | página Gestão: ações, objetivos, histórico e dias de atendimento das áreas (no PostgreSQL), base, alvo, resultado e o quadro |
| `bi/indicadores.py` | os indicadores das ações (positivação, mix médio, efetividade, frequência, preço médio, Personalizada) e a conta do andamento |
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

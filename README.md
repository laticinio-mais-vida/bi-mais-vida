# BI de Metas Mais Vida

Versão em Python das páginas de metas do Power BI (Metas ES, Metas BA, Metas Edir, Metas Produtos BA e
Metas Outras Linhas ES), reunidas numa página só, com abas por visão e filtros de vendedores, meses e anos
(todos de seleção múltipla), e uma página de Configurações para as regras que antes ficavam dentro das
fórmulas DAX. A página **Projeções** prevê o
faturamento bruto dos próximos 6 meses. A página **Sugestão de Metas** sugere a meta do mês seguinte de cada vendedor, por
produto (as páginas de sugestão do Power BI). A página **Assistente** responde perguntas sobre os dados com IA
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
Metas, o crescimento desejado, os tetos e os faturamentos das áreas do BA.

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
arquivos Excel e PDF que ele prepara. A leitura do Google Agenda (só no site) usa `icalendar`, `recurring-ical-events`
e `cryptography`; no PC, eles servem só para os testes. No VPS, tudo já vem na imagem.

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
  última leitura boa e aparece um aviso no painel. A meta **aprovada no painel** (Sugestão de Metas › Configurar ›
  Aprovação de metas) vale no lugar das linhas das duas planilhas daquele vendedor e mês.

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
- **Meta por produto:** volume base, faturamentos, sazonalidade, acumulado do ano, crescimento proposto, meta em volume, preço
  médio e meta em R$. No BA, também **por área**, com os produtos de cada área.
- **Resumo dos vendedores:** todos os vendedores do estado, com a base, a meta sugerida, o crescimento e a meta já lançada
  (a aprovada no painel, com ✓, ou a da METAS.xlsx; Copiar imagem para o WhatsApp). Clicar num vendedor filtra a página.
- **Como a sugestão é calculada:** o passo a passo com os números em vigor.
- **Acesso:** a página é liberada em Usuários; os vendedores que cada pessoa vê são os do acesso de Metas (as abas ES e BA
  liberadas e os vendedores marcados).
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
6. **Meta (R$)** = meta (volume) × preço médio do mês base, que é o faturamento **bruto** ÷ o volume vendido. O total é a soma
   das linhas; "todos os vendedores" é a soma de cada um.

Área sem dia de atendimento e sem número fixo fica fora, como no Power BI (que deixava fora as áreas ausentes da planilha
"Quantidades Faturamentos.xlsx"), e um aviso diz quantos clientes e quanto do mês base ficaram fora. Mês base ainda aberto
também tem aviso.

### Configurar (Sugestão de Metas)

O botão **Configurar** (só administradores) tem três seções. As duas primeiras são as regras da conta, gravadas no banco
com versões, como as regras de Metas:

- **Regras da conta:** crescimento desejado no ano (ES e BA, 12%), teto da sazonalidade (20%) e teto do crescimento proposto
  (20%), com "Restaurar padrão do Power BI".
- **Faturamentos por área (BA):** para o mês da meta escolhido, os quatro meses que a conta usa (base, meta e os dois do ano
  passado). Para cada área: os dias de atendimento (mudam em Gestão › Configurar), o prazo do faturamento com o dia em que
  a área de fato fatura nas vendas dos últimos 6 meses, o número **fixo** por mês (as quinzenais: Itamaraju, Teixeira,
  Itabatã e Posto da Mata, com 2) e o número de cada mês, que pode ser **ajustado à mão** (apagar volta ao automático).
- **Aprovação de metas:** veja abaixo.

### Aprovação de metas

Em Configurar › **Aprovação de metas**, o administrador escolhe o estado e o mês da meta e vê cada vendedor com a meta que a
sugestão gerou. Ao aprovar, a meta passa a valer sozinha no **painel de Metas** (faturamento, clientes e, no ES, mussarela e
outras linhas; no BA, a meta de volume por produto na aba Produtos BA), no Assistente e na Gestão, **no lugar das linhas da
METAS.xlsx e da METAS PRODUTOS.xlsx daquele vendedor e mês**. Os outros vendedores e meses seguem as planilhas. Um mês
aprovado aparece no filtro de Metas mesmo sem estar nas planilhas.

- **Meta (R$):** vem com a sugestão, arredondada ao real, e pode ser editada. A **meta de volume** de cada produto muda no
  mesmo percentual: no BA, volume sugerido × (meta aprovada ÷ sugerida). Clicar no nome do vendedor mostra os produtos com a
  meta de volume que vai para o painel.
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
Crédito; para os outros, esses dados nem existem na cópia que a IA consulta. O mesmo vale para as reanálises de
crédito: as decisões e as **justificativas** (texto livre, que a página pede para não ter CPF, telefone ou endereço)
vão para a IA só nas perguntas de quem tem a página. Do **Google Agenda** de cada pessoa (veja
[Google Agenda](#google-agenda-só-leitura)), o banco do site guarda só o título, o horário e se o evento está ocupado
(sem descrição, local nem convidados), e só o dono vê; o título e o horário vão para a IA só quando ele pergunta da
própria agenda. A IA trata esses títulos como dado, nunca como instrução: qualquer pessoa pode mandar um convite.

## Página Gestão

No topo fica a agenda de quem está vendo (veja [Minha agenda](#minha-agenda)). Abaixo, a **Gestão da equipe**,
separada por região (**ES** e **BA**; o Edir é da BA, com o calendário dela):

- primeiro, os **objetivos do período** da região;
- abaixo, as **campanhas**, com duas barras: o tempo que falta (aviso quando faltam 5 dias ou menos) e o andamento
  contra a meta (nas encerradas, o resultado final e quantos vendedores ficaram na meta);
- e um **quadrado por vendedor** da equipe, com uma etiqueta por campanha em vigor e o % da meta dele até agora.

As cores do andamento seguem o % da meta, sem olhar o prazo, num degradê contínuo: vermelho até 50%, passando pelo
laranja até o amarelo em 80% e pelo verde-amarelado até o verde em 100%; acima disso, o verde fica cada vez mais
forte até 150%. Na barra da campanha, o % é a soma dos resultados ÷ a soma das metas
nos indicadores que somam (positivação, faturamento, volume), a média do % de cada vendedor nos que são médias (mix,
efetividade, frequência, % da base) e, no preço médio, os aumentos feitos ÷ os pedidos, somando os vendedores em R$ (na média, quem
estava a centavos do alvo e subiu poucos centavos ficaria com centenas de % e puxaria a campanha); quem ainda não tem
meta (base aguardando os dados) fica de fora.

A equipe é quem tem meta no mês na planilha METAS, como na página Metas: contas da casa (venda interna, funcionário,
produtor) ficam fora. Quem está numa campanha em vigor aparece mesmo sem meta.

Cada parte da página (a agenda, os objetivos, as campanhas e a equipe) tem o botão **−** no cabeçalho, que a minimiza:
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

### Quem vê o quê

- **Só o administrador** lança, edita, encerra, prorroga e exclui campanhas, cria objetivos e escreve observações.
- A **agenda** do topo é de cada um: quem tem a página cria, conclui e dá feedback nas próprias atividades. As
  **tarefas** são vistas por quem criou e pelos participantes (o administrador só vê as de que participa).
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
- **Participantes** são os usuários ativos com a página Gestão. Quem criou marca quem tem **autonomia**. Na janela
  da tarefa, o **+ Subtarefa** no card de cada um cria uma subtarefa para a pessoa (quem criou, para qualquer uma;
  quem tem autonomia, para si).
- **Quem pode o quê:**

  | | Quem criou | Participante com autonomia | Participante sem autonomia |
  |---|---|---|---|
  | Editar e excluir a tarefa | sim | não | não |
  | Mudar a situação da tarefa (a coluna do kanban), inclusive concluir e reabrir | sim | sim | sim |
  | Mudar prazos e responsáveis | sim | não | não |
  | Editar título e descrição de uma subtarefa | todas | as próprias | não |
  | Criar subtarefa | para qualquer participante | só para si, com o prazo da tarefa | não |
  | Concluir uma subtarefa e mudar a situação dela | todas | as próprias | as próprias |
  | Justificar o atraso | da tarefa e das próprias subtarefas | das próprias subtarefas | das próprias subtarefas |

- **Na agenda:** a tarefa aparece no dia do prazo para todos; cada subtarefa, no dia do prazo dela: quem criou vê
  todas, o participante vê as dele. O ícone de olho abre a tarefa com um card por pessoa e as subtarefas de todos, e
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

Em **Kanban**, as tarefas que você criou ou de que participa ficam em três colunas: **A fazer**, **Fazendo** e
**Concluída** (as concluídas nos últimos 30 dias, as mais recentes em cima; as outras colunas, pelo prazo). As
subtarefas não aparecem no kanban.

- **O card** mostra o título, o prazo (vermelho se venceu), quem criou (se não foi você), quantas pessoas
  participam, quantas subtarefas suas faltam e o andamento das subtarefas.
- **Mudar de coluna:** qualquer pessoa da tarefa arrasta o card; arrastar para Concluída com subtarefas abertas
  pergunta antes, como o círculo da agenda.
- **Clicar no card** abre a janela da tarefa, com a situação dela e a de cada subtarefa (veja **Situação** acima).
  No celular, onde não dá para arrastar, a situação se muda por ali.
- **Nova**, no kanban, já abre o formulário em **Tarefa**.

#### Notificações (o sino)

Quem tem a página Gestão vê, no topo de qualquer página, um **sino** à esquerda do nome, com o número de notificações
não lidas. Clicar abre a lista com as 50 mais recentes; clicar numa abre a tarefa na Gestão e marca como lida, e
**Marcar todas como lidas** zera o número. O painel confere a cada minuto e ao voltar para a aba. Ninguém recebe aviso
do que ele mesmo fez, e as notificações ficam guardadas por 90 dias.

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
dela.

#### Google Agenda (só leitura)

Cada pessoa pode trazer para a agenda os compromissos do Google Agenda dela. O BI **só lê**: nada é escrito no Google.
Funciona no site (bi.maisvida.cloud), onde o `config.ini` tem a chave de `[google]`; no PC, a janela avisa que fica lá.

- **Conectar:** o botão **Google** da agenda abre a janela. A pessoa cola o **endereço secreto no formato iCal** da
  agenda e clica em **Conectar**. O BI lê na hora (endereço errado não entra) e depois relê a cada 10 minutos. Onde
  achar o endereço (no computador; o app do celular não mostra):
  1. em calendar.google.com, a engrenagem › **Configurações**;
  2. em **Configurações das minhas agendas**, clicar na agenda;
  3. em **Integrar agenda**, o último campo: **Endereço secreto no formato iCal**.

  Quem tem mais de uma agenda conecta cada uma, até 5. A janela mostra quando cada uma foi lida, **Atualizar agora** e
  **Remover** (no Google, nada muda).
- **O endereço é uma senha:** quem tem lê a agenda inteira. O BI guarda cifrado, com a chave de `[google]` (fora do
  banco e das cópias de segurança dele), não mostra de novo e não grava no log. Para cortar o acesso, a pessoa usa
  **Redefinir**, ao lado do endereço no Google, e cola o novo: a mesma agenda continua, com o endereço trocado.
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
- **Quando a leitura falha:** os eventos da última leitura ficam. Se o Google não aceita mais o endereço (redefinido),
  a agenda e o botão Google avisam na hora para colar de novo; se é passageiro (o Google fora do ar), o BI tenta de
  novo sozinho, espaçando as tentativas até 2 horas, e só avisa depois de uma hora sem ler. Com mais de 24 horas sem
  leitura, os eventos aparecem como "pode estar desatualizado" e não travam ninguém. Quem é desativado ou perde a
  página Gestão deixa de ser lido.
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
    A VISTA = [0]), o vendedor da carteira, cidade, UF, área, segmento, rede, se está inativo e a data de cadastro;
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

## Banco de dados

O painel usa dois bancos, cada um para uma coisa:

- **DuckDB** (`dados/cache.duckdb`): a cópia das vendas, devoluções e cadastros do ERP. É refeito a cada extração
  e só é lido.
- **PostgreSQL:** o que as próprias pessoas criam no painel.

| Tabela | O que guarda |
|---|---|
| `usuarios` | acessos: nome, login, senha em hash, papel, páginas e o que cada um vê nelas |
| `regras` | as regras de Metas, os vendedores de Projeções e as regras da Sugestão de Metas (migração 024); cada Salvar vira uma versão nova, com quem salvou e quando |
| `conversas` e `mensagens` | o histórico do Assistente, de cada usuário |
| `assistente_perguntas` | o registro de uso do Assistente: pergunta, consultas, tokens e custo |
| `campanhas` e `campanha_vendedores` | as ações e os objetivos da página Gestão (coluna `tipo`): região, período, indicador (`metrica`, `parametros`, filtros), alvo, quem lançou, e os vendedores com a base e o resultado congelado (no preço médio, também o preço de cada produto: `base_precos` e `resultado_precos`, migração 013) |
| `gestao_eventos` | o histórico interno de cada vendedor: observações e o que aconteceu nas ações dele (lançada, editada, prorrogada, encerrada, resultado) |
| `campanha_produtos` | o preço-alvo de cada produto nas ações e objetivos de preço médio |
| `areas_atendimento` | os dias de atendimento de cada área comercial (efetividade) |
| `metas_aprovadas` | as metas aprovadas na Sugestão de Metas (migração 025): uma linha por gravação (vale a última de cada vendedor × mês; `aprovada` falso = retirada), com o total, a mussarela e as outras linhas, os clientes, o retrato da sugestão (`sugerida_fat`, `sugerida_mus`, os clientes da carteira) e a meta de volume de cada produto (`produtos`) |
| `agenda_atividades` e `agenda_registros` | a agenda de cada pessoa: as atividades com a repetição e o horário, e cada dia concluído com o feedback (migrações 018 e 019); o fim do horário, o horário ocupado e a única de vários dias (migração 026) |
| `agenda_propostas` | as propostas do Assistente para a agenda que a pessoa já confirmou no botão, para não aplicar duas vezes (migração 019) |
| `agenda_tarefas`, `agenda_tarefa_pessoas` e `agenda_subtarefas` | as tarefas da agenda: o prazo, quem participa (quem criou também, e com que autonomia) e as subtarefas de cada um, com o prazo e a conclusão (migração 020) e quando começou a ser feita, a coluna Fazendo do kanban (migração 021), a justificativa do atraso (migração 022, passada para `agenda_justificativas` pela 027) e quem concluiu a tarefa (migração 023); o título da subtarefa vai até 2000 caracteres (migração 030). Excluir um usuário apaga as tarefas que ele criou e as subtarefas dele nas dos outros |
| `agenda_justificativas` | o histórico das justificativas do atraso de cada tarefa e subtarefa: quem escreveu, quando e o prazo que tinha vencido (migração 027) |
| `notificacoes` | as notificações do sino: para quem, o tipo, o texto, a tarefa e quando foi lida; os avisos de prazo têm uma chave, para sair uma vez só (migração 028) |
| `google_agendas` e `google_eventos` | o Google Agenda de cada pessoa, só leitura (migração 031): as agendas conectadas (o id da agenda no Google, o endereço secreto cifrado, a assinatura do último arquivo, quando foi lida e o último erro) e os eventos lidos, uma linha por ocorrência (título, início e fim, dia inteiro e se está ocupado). Remover a agenda leva os eventos dela; só o site usa |
| `credito_reanalises` | as reanálises de crédito, só no site (migração 029): uma linha por registro, que não muda depois, com o cliente, o limite e o prazo de antes, o limite pedido, o liberado e o prazo liberado, a justificativa, o parecer da regra para o pedido e para o liberado, o limite sugerido, a extração usada (`dados_ate`), o retrato do cliente (`retrato`, veja [Reanálises](#reanálises)) e quem registrou; a excluída fica com `excluida_em` |
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
Sugestão de Metas segue o acesso de Metas, sem escolha própria. A Reavaliação de Crédito não tem configuração: quem tem a
página vê todos os clientes. Quem foi cadastrado antes de uma
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
- **Páginas que pode ver** (Metas, Projeções, Sugestão de Metas, Assistente, Gestão, Reavaliação de Crédito). Embaixo aparece, só para consulta, o que a pessoa vê em cada
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
6. **Sugestão de Metas:** veja as [diferenças da sugestão](#diferenças-em-relação-ao-power-bi-sugestão).

## Arquivos

| Arquivo | O que faz |
|---|---|
| `app.py` | servidor local e rotas da API |
| `bi/cache.py` | leitura do Firebird e cache DuckDB (os pedidos de venda e a rede dos clientes, para a efetividade, e os títulos a receber, as parcelas e os limites, para o crédito, vêm em grupos à parte: se a leitura falhar, o resto segue) |
| `bi/metas.py` | cálculo das visões |
| `bi/projecoes.py` | projeção do faturamento bruto (modelo, faixa e filtros da página Projeções) |
| `bi/sugestao.py` | página Sugestão de Metas: a conta das páginas de sugestão do Power BI, os faturamentos das áreas, as regras da página (tabela regras), o resumo dos vendedores, a ferramenta do Assistente e a aba de aprovação das metas |
| `bi/aprovacao.py` | metas aprovadas (tabela metas_aprovadas): a distribuição do volume pelo R$ aprovado e as planilhas de metas com as aprovadas por cima, que a Calculadora lê |
| `bi/credito.py` | página Reavaliação de Crédito: cartões (um ou vários clientes), títulos com o valor já pago e a ordem da tabela, a busca de cliente, o parecer de um limite novo, os prazos do ERP, o retrato de uma reanálise e o que aconteceu depois dela |
| `bi/reanalise.py` | as reanálises de crédito (tabela credito_reanalises, só no site): registrar com o retrato, listar, excluir e o que o Assistente lê (por cliente e parecidas) |
| `bi/assistente.py` | página Assistente: dados de cada acesso, ferramentas de consulta e chamada à API da Anthropic |
| `bi/arquivos.py` | os arquivos Excel e PDF que o Assistente prepara para baixar (formatos das colunas, montagem) |
| `bi/conversas.py` | histórico de conversas do Assistente (no PostgreSQL) |
| `bi/gestao.py` | página Gestão: ações, objetivos, histórico e dias de atendimento das áreas (no PostgreSQL), base, alvo, resultado e o quadro |
| `bi/agenda.py` | agenda de cada pessoa, no topo da Gestão: as atividades de cada pessoa, em que dias cada repetição acontece, a conclusão com feedback e o histórico (no PostgreSQL) |
| `bi/tarefas.py` | as tarefas da agenda: prazo, participantes com ou sem autonomia, subtarefas, quem pode o quê, o que aparece em cada dia, as atrasadas, as justificativas do atraso (um histórico) e o que cada pessoa precisa justificar agora, e o kanban (a situação de cada tarefa e subtarefa) (no PostgreSQL) |
| `bi/notificacoes.py` | as notificações do sino: gravar (na transação de quem avisa), listar, contar as não lidas e marcar como lidas (no PostgreSQL) |
| `bi/google_agenda.py` | o Google Agenda, só leitura: o endereço secreto (conferido, remontado e cifrado), baixar e interpretar o arquivo iCal (repetições, exceções, fusos), a leitura de tempos em tempos, o que a agenda mostra e os eventos ocupados que o horário ocupado confere (no PostgreSQL) |
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

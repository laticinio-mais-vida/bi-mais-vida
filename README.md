# BI de Metas Mais Vida

Versão em Python das páginas de metas do Power BI (Metas ES, Metas BA, Metas Edir, Metas Produtos BA e
Metas Outras Linhas ES), reunidas numa página só, com abas por visão e filtros de vendedores, meses e anos
(todos de seleção múltipla), e uma página de Configurações para as regras que antes ficavam dentro das
fórmulas DAX. A página **Projeções** prevê o
faturamento bruto dos próximos 6 meses.

As páginas ficam na **barra lateral** à esquerda. O botão no topo dela recolhe a barra (só os ícones; o nome
aparece ao passar o mouse) ou expande, e o painel lembra a escolha neste navegador. No celular, a barra vira
uma gaveta que abre pelo botão de menu do topo. **Usuários** fica na seção Administração, que só o
administrador vê. Cada página tem a sua configuração, no botão **Configurar** da barra de filtros dela (só para
administradores): em Metas abre as Configurações das metas; em Projeções, as Configurações das projeções.

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

Não precisa instalar nada: o projeto usa o Python 3.11 que já está na máquina, com `fdb` (Firebird),
`duckdb`, `pandas` e `numpy` (que vem com o pandas), que já estão instalados.

## De onde vêm os dados

| Fonte | Caminho (em `config.ini`) |
|---|---|
| Cópia do banco do ERP (Firebird 2.1, só leitura) | `C:\Users\Micro\Documents\banco de dados\LATICINIOMAISVIDALTDA.GDB` |
| Metas de faturamento, mussarela, outras linhas e clientes | `C:\Users\Micro\Documents\METAS.xlsx` |
| Metas de volume por produto (BA) | `C:\Users\Micro\Documents\METAS PRODUTOS.xlsx` |

O sistema copia do banco só o que as metas usam (vendas, clientes atendidos, devoluções e cadastros, desde
2024) para um cache local em `dados\cache.duckdb`. Por isso os filtros respondem na hora.

- **Cópia do banco nova:** o painel percebe sozinho em até 1 minuto, mesmo sem nenhuma página aberta, e
  atualiza o cache em segundo plano (cerca de 15 segundos). O botão **Atualizar dados** força a leitura na hora.
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
entram os vendedores escolhidos na configuração da página (por padrão, todas as equipes ES, BA e Edir,
inclusive vendedores sem meta na planilha).

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

- **Vendedores da página:** quem entra nos totais, nos gráficos e no filtro. Vendedores novos das equipes ES,
  BA e Edir entram sozinhos, para a projeção não perder faturamento sem ninguém perceber. Desmarque contas
  internas (Venda interna, Funcionário, Produtor...) ou quem não deve contar, e marque quem é de fora dessas
  equipes e deve entrar. A lista mostra a venda bruta dos últimos 12 meses e a última venda de cada um.
  Fica gravado em `config_projecoes.json` (a versão anterior em `config_projecoes.anterior.json`).
- **Acesso por usuário:** para cada visualizador, se ele vê a página e quais vendedores aparecem para ele:
  - **Igual a Metas** (padrão): as equipes das abas de Metas e os vendedores liberados em Metas › Configurar. Se o acesso
    de Metas mudar, este muda junto;
  - **Todos da página;**
  - **Só alguns:** a lista que você marcar.
  Os totais somam só os vendedores que a pessoa vê. Administradores veem todos os vendedores da página.

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

## Login e acessos

Todo mundo entra com usuário e senha. Há dois papéis:

| Papel | Vê | Pode mexer |
|---|---|---|
| **Administrador** | todas as páginas, abas e vendedores | Configurações, Usuários e o botão Atualizar dados |
| **Visualizador** | só as páginas e abas marcadas e, se quiser, só alguns vendedores | só a própria senha |

Em Usuários ficam só os dados da pessoa (nome, usuário, senha, papel) e as páginas que ela vê. O que ela vê
dentro de cada página fica no botão **Configurar** da própria página, em "Acesso por usuário": em Metas, as
abas e os vendedores; em Projeções, os vendedores (o padrão é igual ao acesso de Metas). Quem foi cadastrado
antes da página Projeções existir continua só com Metas até o administrador marcar a página nova.

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
- **Páginas que pode ver** (Metas, Projeções). Embaixo aparece, só para consulta, o que a pessoa vê em cada
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
VPS só ele e as planilhas (uns 3 MB compactados), sozinho, depois de cada cópia nova do banco. O passo a passo
está em [docs/publicacao_vps.md](docs/publicacao_vps.md).

### Esqueci a senha do administrador

No computador do painel, abra um terminal na pasta do projeto e rode:

```bash
python app.py --senha LOGIN
```

O comando pede a senha nova duas vezes, reativa o usuário e derruba as sessões abertas. Se o login não
existir, ele cria um administrador com esse nome.

## Página Configurações (das metas)

Abre pelo botão **Configurar** da página Metas. Tudo é gravado em `config_metas.json`. A versão anterior fica em `config_metas.anterior.json`. O padrão
reproduz exatamente as fórmulas do Power BI. O botão "Restaurar padrão do Power BI" volta a ele.

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
  o que a pessoa vai ver. Fica gravado em `usuarios.json`, não em `config_metas.json`, e "Restaurar padrão do
  Power BI" não mexe nele. Quem é criado em Usuários com a página Metas começa sem abas (a página fica vazia
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

## Arquivos

| Arquivo | O que faz |
|---|---|
| `app.py` | servidor local e rotas da API |
| `bi/cache.py` | leitura do Firebird e cache DuckDB |
| `bi/metas.py` | cálculo das visões |
| `bi/projecoes.py` | projeção do faturamento bruto (modelo, faixa e filtros da página Projeções) |
| `bi/calendario.py` | dias úteis e feriados de ES e BA |
| `bi/configuracao.py` | regras editáveis e padrões do Power BI |
| `bi/acesso.py` | usuários, senhas (PBKDF2), sessões assinadas e permissões |
| `bi/planilhas.py` | leitura das planilhas de metas |
| `bi/fb.py` | conexão somente leitura com o Firebird 2.1 (a mesma do Painel Comercial ES) |
| `bi/publicacao.py` | envio do cache e das planilhas ao VPS (no PC) e recebimento com conferência (no VPS) |
| `web/` | página: HTML, CSS (identidade do Guia da Marca 2026) e JavaScript |
| `logs/bi.log` | registro de atualizações e erros |
| `config.exemplo.ini` | modelo do `config.ini` (sem a senha) |
| `config_metas.json` | regras salvas pela página Configurações (vai para o repositório, então as mudanças ficam no histórico) |
| `config_projecoes.json` | vendedores da página Projeções, salvos em Projeções › Configurar (só existe depois do primeiro Salvar) |
| `usuarios.json` | acessos do painel: senhas em hash e a chave das sessões (fica fora do repositório) |
| `docs/analise_pbi_metas.md` | análise do Power BI original: tabelas, medidas DAX e divergências encontradas |
| `docs/publicacao_vps.md` | como o painel está publicado no VPS e como mantê-lo |
| `deploy/` | Dockerfile e docker-compose do painel no VPS |

Ficam fora do repositório (`.gitignore`): `config.ini` (senha), `usuarios.json` (acessos), `dados/` (cache com as vendas), `logs/`,
`marca/` (guia da marca em PDF) e as cópias `config_metas.anterior.json` e `config_projecoes.anterior.json`.

## Se algo der errado

- **"Preparando os dados" não termina:** veja `logs\bi.log`. O mais comum é o serviço
  *Firebird Server - DefaultInstance* parado.
- **Porta ocupada:** use `python app.py --porta 8051`.
- **Outro computador não abre o painel:** confira `endereco = 0.0.0.0` no `config.ini` e se o firewall do
  Windows liberou o Python em rede privada.
- **Números estranhos depois de mexer nas regras:** use "Restaurar padrão do Power BI" em Configurações.

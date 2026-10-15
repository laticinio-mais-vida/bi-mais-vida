# BI de Metas Mais Vida

Versão em Python das páginas de metas do Power BI (Metas ES, Metas BA, Metas Edir, Metas Produtos BA e
Metas Outras Linhas ES), reunidas numa página só, com filtros de visão, vendedor, mês e ano, e uma página
de Configurações para as regras que antes ficavam dentro das fórmulas DAX.

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
`duckdb` e `pandas`, que já estão instalados.

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

Em cada aba:

- **Ritmo do mês:** dias úteis do mês, quantos já passaram e o ritmo esperado (% mínimo da meta para hoje).
  Feriados aparecem marcados. É o antigo quadro "Dias úteis", agora calculado sozinho.
- **Indicadores:** realizado contra a meta, situação (meta batida, no ritmo, atenção ou abaixo), projeção
  do mês e quanto falta por dia útil.
- **Corrida da meta:** acumulado do mês contra o ritmo esperado de cada dia, com a projeção.
- **Ranking** dos vendedores. Clicar num vendedor filtra a página por ele.
- **Detalhamento por vendedor** no mesmo formato das matrizes do Power BI: indicadores nas linhas,
  vendedores nas colunas (ordem alfabética) e Total no fim. Metas em azul e categorias em amarelo.
  - Em Outras Linhas ES vem também a tabela "Falta Outras Linhas / Dentro da meta?".
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

## Login e acessos

Todo mundo entra com usuário e senha. Há dois papéis:

| Papel | Vê | Pode mexer |
|---|---|---|
| **Administrador** | todas as abas e todos os vendedores | Configurações, Usuários e o botão Atualizar dados |
| **Visualizador** | só as abas marcadas e, se quiser, só alguns vendedores | só a própria senha |

Exemplos:

- **Supervisor da BA:** visualizador com as abas Metas BA e Produtos BA e "Todos dessas abas" em Vendedores.
- **Vendedor:** visualizador com a aba dele e só ele marcado em Vendedores. Indicadores, ranking, corrida e
  tabelas mostram só os números dele.

Quem barra é o servidor: o visualizador recebe só os números liberados, mesmo se mexer no endereço da página.
Mudanças de abas e vendedores valem na hora. Trocar a senha ou desativar alguém derruba as sessões abertas
dessa pessoa.

Na página **Usuários** (só para administradores):

- **Novo:** nome, usuário e senha. O botão **Gerar** cria uma senha aleatória (e copia, quando o navegador
  deixa) para você passar à pessoa.
- **Abas que pode ver** e **Vendedores** ("Todos dessas abas" inclui quem entrar depois; "Só alguns" fixa a
  lista). O quadro azul no fim resume o que a pessoa vai ver.
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

## Página Configurações

Tudo é gravado em `config_metas.json`. A versão anterior fica em `config_metas.anterior.json`. O padrão
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
| `usuarios.json` | acessos do painel: senhas em hash e a chave das sessões (fica fora do repositório) |
| `docs/analise_pbi_metas.md` | análise do Power BI original: tabelas, medidas DAX e divergências encontradas |
| `docs/publicacao_vps.md` | como o painel está publicado no VPS e como mantê-lo |
| `deploy/` | Dockerfile e docker-compose do painel no VPS |

Ficam fora do repositório (`.gitignore`): `config.ini` (senha), `usuarios.json` (acessos), `dados/` (cache com as vendas), `logs/`,
`marca/` (guia da marca em PDF) e a cópia `config_metas.anterior.json`.

## Se algo der errado

- **"Preparando os dados" não termina:** veja `logs\bi.log`. O mais comum é o serviço
  *Firebird Server - DefaultInstance* parado.
- **Porta ocupada:** use `python app.py --porta 8051`.
- **Outro computador não abre o painel:** confira `endereco = 0.0.0.0` no `config.ini` e se o firewall do
  Windows liberou o Python em rede privada.
- **Números estranhos depois de mexer nas regras:** use "Restaurar padrão do Power BI" em Configurações.

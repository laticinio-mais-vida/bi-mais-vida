# Painel na internet: bi.maisvida.cloud

Este guia explica como os números chegam ao site **https://bi.maisvida.cloud** e o que fazer para mantê-los em
dia. A primeira parte é para quem cuida dos dados no dia a dia e não exige saber nada de servidor. A
[parte técnica](#parte-técnica-para-quem-cuida-do-servidor), no fim, é para quem mexe no servidor.

## Em resumo

- O site **não lê o banco do ERP sozinho**. Ele mostra os números que o **computador da empresa** manda.
- O computador da empresa manda números novos quando **chega uma cópia nova do banco** e **o painel está
  aberto nele**.
- Com essas duas coisas, o site se atualiza sozinho em uns 2 minutos. Não existe botão para apertar no site.

## Como funciona

```
  1. Cópia do banco do ERP        2. Painel aberto no PC              3. Site
     (arquivo de ~7 GB)     ──►      lê o banco e resume       ──►     bi.maisvida.cloud
                                     os números (~10 MB)               troca os números
                                     e manda pela internet
```

O banco inteiro não vai para o site: são 7 GB, e o painel só precisa do resumo de vendas, clientes e
devoluções, que tem uns 10 MB compactado (com o detalhe por cliente do Assistente). Isso também é mais seguro, porque o banco do ERP nunca sai da empresa.

| Termo | O que é |
|---|---|
| **PC da empresa** | O computador onde a cópia do banco é feita e onde o painel roda (usuário do Windows: Micro). |
| **Painel do PC** | O programa aberto pelo `iniciar.bat`. Enquanto roda, fica uma janela preta aberta. **Fechar essa janela faz o PC parar de mandar dados.** |
| **Site** | https://bi.maisvida.cloud, o endereço que todo mundo acessa. |
| **Servidor** | O computador na internet que hospeda o site. Só a parte técnica mexe nele. |

## Atualizar os dados de vendas (todo dia)

1. **Copie o banco do ERP para o PC**, substituindo o arquivo anterior. O nome e a pasta precisam ser
   exatamente estes, senão o painel não encontra a cópia:

   `C:\Users\Micro\Documents\banco de dados\LATICINIOMAISVIDALTDA.GDB`

2. **Confira se o painel do PC está aberto**, ou seja, se existe a janela preta do painel. Se não existir, dê
   dois cliques em:

   `C:\Users\Micro\Desktop\BI MAIS VIDA\bi-mais-vida\iniciar.bat`

   Ele também abre o painel no navegador, que você pode fechar. A janela preta precisa ficar aberta, mas pode
   ser minimizada.

3. **Espere uns 2 minutos.** O painel percebe a cópia nova sozinho, lê o banco (uns 40 segundos) e manda os
   números para o site.

4. **Confira no site**, como explicado em [Conferir se o site está em dia](#conferir-se-o-site-está-em-dia).

Se o painel tentar ler o banco antes de a cópia terminar, aparece um erro e ele tenta de novo sozinho no
minuto seguinte. Não é preciso fazer nada.

## Atualizar as metas (início do mês)

As metas vêm de duas planilhas que ficam no PC:

| Planilha | O que tem |
|---|---|
| `C:\Users\Micro\Documents\METAS.xlsx` | Metas de faturamento, mussarela, outras linhas e clientes, por vendedor e mês |
| `C:\Users\Micro\Documents\METAS PRODUTOS.xlsx` | Metas de volume por produto e vendedor (BA) |

1. Abra a planilha, acrescente as linhas do mês novo e **salve com o mesmo nome, na mesma pasta**.
2. **Feche o Excel.**
3. Com o painel do PC aberto, a planilha vai para o site em até 1 minuto.

Para o site aceitar a planilha:

- **Não renomeie nem apague colunas.** As colunas podem estar em qualquer ordem e pode haver colunas a mais,
  mas estas precisam existir com estes nomes:
  - `METAS.xlsx`: ID_VENDEDOR, VENDEDOR, META FATURAMENTO, META MUSSARELA, META OUTRAS LINHAS, META CLIENTE e
    DATA.
  - `METAS PRODUTOS.xlsx`: DATA, ID_VENDEDOR, VENDEDOR, ID_PRODUTO, PRODUTO e META VOLUME.
- Na coluna DATA, qualquer dia do mês da meta serve: o painel só olha o mês.
- Salve como `.xlsx`, e não como `.xls` ou `.csv`.

Se a planilha tiver problema, o site a recusa e continua com a versão anterior. O motivo aparece no rodapé do
painel do PC (veja [O site não atualizou](#o-site-não-atualizou)).

## Conferir se o site está em dia

No site, olhe dois lugares:

| Onde | Exemplo | O que quer dizer |
|---|---|---|
| Embaixo do título "Acompanhamento de Metas" | `dados até quarta, 14/10` | Último dia com vendas nos números. A cópia feita de manhã costuma trazer as vendas até o dia anterior. |
| Rodapé (fim da página) | `Fonte: cópia do ERP de 15/10/2026 às 08:10` | Quando a cópia do banco usada foi feita. Deve ser a de hoje. |
| Rodapé | `Recebidos no servidor em 15/10/2026 às 08:12` | Quando o site recebeu esses números. |

No **painel do PC**, quem é administrador vê no rodapé `Enviado ao servidor em ...` quando o envio deu certo,
ou `Envio ao servidor falhou: ...` com o motivo.

## O site não atualizou

Siga na ordem e pare quando resolver:

1. **O painel do PC está aberto?** Se a janela preta foi fechada, nada é enviado. Abra o `iniciar.bat` e espere
   2 minutos.
2. **A cópia foi para o lugar certo?** Confira o nome e a pasta do passo 1 de
   [Atualizar os dados de vendas](#atualizar-os-dados-de-vendas-todo-dia). Uma cópia com outro nome, como
   "LATICINIOMAISVIDALTDA (2).GDB", não é lida.
3. **O rodapé do painel do PC mostra "Envio ao servidor falhou"?** Veja a tabela abaixo.
4. **Ainda não?** No painel do PC, clique em **Atualizar dados**, no topo da página (só aparece para
   administradores). Ele lê o banco de novo e manda em seguida.
5. **Ainda não?** Feche a janela preta e abra o `iniciar.bat` de novo. Ao abrir, o painel tenta enviar na hora.
   Depois de uma falha, ele espera entre uma tentativa e outra (2, 4, 8 e 16 minutos, e depois a cada 30).

| Mensagem no rodapé do painel do PC | O que fazer |
|---|---|
| `sem conexão com https://bi.maisvida.cloud` | A internet do PC caiu ou o site está fora do ar. Tente abrir o site no PC. Se ele também não abrir, chame quem cuida do servidor. |
| `o relógio do computador que envia está mais de 15 min diferente do VPS` | Acerte a hora do Windows: Configurações › Hora e idioma › Data e hora › **Sincronizar agora**. |
| `METAS.xlsx recebida não pôde ser lida` (ou `METAS PRODUTOS.xlsx`) | A planilha foi salva com problema. Veja os cuidados em [Atualizar as metas](#atualizar-as-metas-início-do-mês), corrija e salve de novo. |
| `assinatura inválida` | A chave do PC e a do servidor ficaram diferentes. Chame quem cuida do servidor (veja [Trocar a chave de envio](#trocar-a-chave-de-envio)). |
| `Falha ao ler o banco` ou `falta a senha do banco` | O problema é no PC, e não no site. Veja "Se algo der errado" no [README](../README.md). O mais comum é o serviço *Firebird Server - DefaultInstance* parado. |

A mesma mensagem aparece na janela preta do painel e fica gravada em
`C:\Users\Micro\Desktop\BI MAIS VIDA\bi-mais-vida\logs\bi.log`.

## Se o PC ficar desligado

O site continua no ar com os últimos números recebidos, e o rodapé mostra de quando eles são. Quando o PC voltar
e o painel for aberto, ele manda o que tiver de mais novo.

## Fazer o painel abrir junto com o Windows

Assim ninguém precisa lembrar de abrir o painel:

1. Aperte **Win + R**, digite `shell:startup` e aperte Enter. Abre uma pasta.
2. Nessa pasta, clique com o botão direito › **Novo › Atalho**.
3. Em "Procurar", escolha `C:\Users\Micro\Desktop\BI MAIS VIDA\bi-mais-vida\iniciar.bat` e conclua.

Da próxima vez que o Windows ligar, o painel abre sozinho.

## Usuários e configurações do site

O site e o painel do PC têm **cadastros separados**, cada um no banco de dados da sua máquina. O que muda num não
muda no outro.

| Quero... | Onde fazer |
|---|---|
| Dar acesso a alguém, mudar o que a pessoa vê ou bloquear um acesso | No site, página **Usuários** (só administradores) |
| Mudar regras: grupo de cada vendedor e produto, motivos de devolução, feriados | No site, página **Metas** › botão **Configurar** (só administradores) |
| Escolher os vendedores das projeções e o que cada pessoa vê nelas | No site, página **Projeções** › botão **Configurar** (só administradores) |
| Escolher quais vendedores cada pessoa consulta no assistente e ver o uso e o custo | No site, página **Assistente** › botão **Configurar** (só administradores) |
| Trocar a minha senha | No site, menu com o seu nome (canto superior direito) › Trocar minha senha |

Os acessos do site começaram, em 15/10/2026, como cópia dos do PC (mesmos logins e senhas).

---

## Parte técnica (para quem cuida do servidor)

### Onde está cada coisa

O servidor (`187.127.54.201`, Ubuntu 24.04, acesso por `ssh root@187.127.54.201`) também roda o app de promotoria
(`estoque.maisvida.cloud`), a Evolution API e a API do RAG. Não mude fuso, firewall nem portas do servidor: os
outros sistemas dependem deles.

| O quê | Onde |
|---|---|
| Painel: código, `config.ini` (modo vps, a chave de envio, a chave da API do Assistente e a senha do banco), `banco.env`, `dados/`, `logs/` (e, só como cópia, `usuarios.json` e `config_*.json`, de antes do banco) | `/opt/bi-mais-vida` |
| Container `bi_metas` (Python 3.12, usuário 10001, até 512 MB, horário de Brasília) | `/opt/bi-mais-vida/deploy/docker-compose.yml` |
| Container `bi_banco` (PostgreSQL 18, até 256 MB; só o painel enxerga), com os usuários, as regras, as conversas e o uso do Assistente. Os dados ficam no volume Docker `bi-mais-vida_bi_banco_dados` | `/opt/bi-mais-vida/deploy/docker-compose.yml` |
| Cópias de segurança do banco (uma por dia, 14 dias) | `/opt/backups/bi-banco/` |
| HTTPS de `bi.maisvida.cloud`, encaminhado para `bi_metas:8050` | bloco no fim de `/opt/app-promotoria/Caddyfile` (container `estoque_caddy`) |
| Rede que liga o Caddy ao painel | `app-promotoria_estoque_network` |

O painel não abre porta para a internet: só o Caddy fala com ele, pela rede Docker. O banco também não: só o
painel fala com ele, por uma rede Docker interna.

### Comandos do dia a dia

No servidor:

```bash
cd /opt/bi-mais-vida/deploy
docker compose ps                  # está rodando?
docker compose logs --tail 50      # últimas mensagens (recebimentos, logins, erros)
docker compose restart             # reiniciar (ex.: depois de mudar o config.ini)
```

### Publicar uma versão nova do código

O PC e o servidor rodam o mesmo código, então atualize os dois. No PC, abra o PowerShell na pasta do projeto
(`C:\Users\Micro\Desktop\BI MAIS VIDA\bi-mais-vida`) e rode:

```powershell
# 1. Cópia de segurança do banco e da pasta do servidor
ssh root@187.127.54.201 'bash /opt/bi-mais-vida/deploy/backup_banco.sh && cp -a /opt/bi-mais-vida /opt/bi-mais-vida.bak-$(date +%Y%m%d-%H%M)'

# 2. Enviar o código
scp -r app.py bi web deploy root@187.127.54.201:/opt/bi-mais-vida/

# 3. Acertar o dono dos arquivos e reiniciar
ssh root@187.127.54.201 'chown -R 10001:10001 /opt/bi-mais-vida && cd /opt/bi-mais-vida/deploy && docker compose up -d --build && docker compose restart'
```

O código entra no container como volume (`..:/app`). Se só o código mudou, a imagem fica igual e o `up` não
recria o container: é o `restart` que faz o painel carregar a versão nova (confira em `docker compose ps` que
o tempo de "Up" voltou a poucos segundos).

Depois, feche e abra o painel do PC (`iniciar.bat`).

**Não envie** `config.ini`, `banco.env`, `dados/` nem `logs/`. No servidor, esses arquivos são diferentes dos do PC:
lá estão as chaves e a senha do banco. Os acessos e as regras salvas no site ficam no banco do site, que o envio do
código não toca.

O passo 1 faz duas cópias: a do banco PostgreSQL (`backup_banco.sh`, em `/opt/backups/bi-banco/`, porque o banco
fica num volume do Docker, fora da pasta) e a da pasta. Se a versão nova mudar tabelas (arquivo novo em
`bi/migracoes/`), as mudanças são aplicadas quando o painel reinicia, e o log mostra `migrações aplicadas agora: ...`.

Se algo der errado, volte para as duas cópias de segurança. O código antigo pode não entender as tabelas novas, então
o banco volta junto. O `docker compose down` não apaga o banco (só `down -v` apagaria; nunca use `-v`):

```bash
cd /opt/bi-mais-vida/deploy && docker compose down
rm -rf /opt/bi-mais-vida && mv /opt/bi-mais-vida.bak-AAAAMMDD-HHMM /opt/bi-mais-vida
cd /opt/bi-mais-vida/deploy && docker compose up -d banco
docker exec -i bi_banco pg_restore -U bi -d bi --clean --if-exists < /opt/backups/bi-banco/bi-AAAA-MM-DD.dump
docker compose up -d --build
```

O dump do dia é o que o passo 1 acabou de gravar (se a cópia diária das 00:30 rodar depois da publicação, ela grava
por cima no mesmo arquivo do dia: nesse caso use o do dia anterior, ou copie o dump para outro nome logo depois do
passo 1).

### Assistente (chave da API da Anthropic)

O Assistente chama a API da Anthropic a partir do servidor. A chave é cobrada por uso (é separada da assinatura do
Claude) e fica só no `config.ini` do servidor:

1. No Console da Anthropic (platform.claude.com › API keys), crie uma chave para o painel. Ponha um limite de
   gasto mensal na conta.
2. No servidor, `nano /opt/bi-mais-vida/config.ini` e acrescente no fim:

   ```ini
   [ia]
   chave = sk-ant-...
   ```

   Os outros ajustes (modelo, esforço, limites e preços) têm padrão em `config.exemplo.ini` e só precisam entrar
   aqui se forem diferentes.
3. `cd /opt/bi-mais-vida/deploy && docker compose restart`.

O pacote `anthropic` vem na imagem (`deploy/Dockerfile`). Na primeira publicação desta versão, o
`docker compose up -d --build` do passo 3 de [Publicar uma versão nova do código](#publicar-uma-versão-nova-do-código)
refaz a imagem com ele.

O que acompanhar:

- **Memória:** os dados de cada acesso ficam na memória enquanto ele usa o assistente. O de todos os vendedores
  (uns 60 MB) tem vaga própria e fica carregado, porque a página Gestão usa ele sempre; além dele, até 2 acessos ao
  mesmo tempo (`recortes` em `[ia]`). Confira com `docker stats bi_metas`; o limite do container é 512 MB. Se
  apertar, use `recortes = 1`.
- **Perguntas longas:** uma pergunta pode levar até uns 100 s (`tempo_total`). O `reverse_proxy` do Caddy não tem
  tempo limite de resposta por padrão, então o Caddyfile não precisa mudar. Mesmo assim, depois de publicar, faça
  uma pergunta que exija várias consultas e confira que a resposta chega.
- **Registro:** a tabela `assistente_perguntas` do banco, uma linha por pergunta, com tokens e custo estimado. A
  página Assistente › Configurar › Uso e custo resume os últimos 30 dias.

### Banco de dados (PostgreSQL)

O que o painel cria fica num PostgreSQL só dele, o container `bi_banco`: usuários, regras salvas nas páginas,
conversas e uso do Assistente, as campanhas, os objetivos e o histórico da página Gestão (migrações `007_gestao.sql`,
`008_indicadores.sql`, `009_gestao_equipe.sql` e `012_base_periodo.sql`) e os dias de atendimento das áreas
comerciais.

- **Rede:** o banco fica numa rede Docker interna (`interno`) que só o painel enxerga. Ele não tem porta aberta para
  a internet e não fala com o app de promotoria.
- **Dados:** ficam no volume Docker `bi-mais-vida_bi_banco_dados`, fora de `/opt/bi-mais-vida`. Por isso o `chown`
  e o rollback do deploy não mexem neles.
- **Tabelas:** são criadas e atualizadas pelo próprio painel quando ele sobe, a partir de `bi/migracoes/`. Não é
  preciso rodar nada à mão.
- **Se o banco cair:** ninguém entra no site (a tela de login avisa que o banco está fora do ar), mas os dados que o
  PC manda continuam chegando. O painel volta sozinho quando o banco responder.

#### Primeira instalação

Faça uma vez, antes de publicar a primeira versão que traz o banco:

1. Criar a senha do banco, no servidor:

   ```bash
   cd /opt/bi-mais-vida
   echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)" > banco.env
   chmod 600 banco.env
   cat banco.env    # copie a senha para o passo 2
   ```

2. `nano /opt/bi-mais-vida/config.ini` e acrescentar no fim (porta, banco e usuário têm padrão: 5432, bi, bi):

   ```ini
   [postgres]
   host = bi_banco
   senha = A_MESMA_SENHA_DO_BANCO_ENV
   ```

3. Publicar o código como em [Publicar uma versão nova do código](#publicar-uma-versão-nova-do-código). O
   `docker compose up -d --build` faz três coisas:
   - cria o `bi_banco`;
   - refaz a imagem do painel com o pacote `psycopg`;
   - sobe o painel depois que o banco estiver pronto.
4. Conferir:
   - `docker compose ps` mostra o `bi_banco` como `healthy`;
   - `docker compose logs bi --tail 30` tem a linha `banco de dados bi@bi_banco:5432/bi pronto (migrações aplicadas agora: 001_conversas)`;
   - no site, faça uma pergunta no Assistente, recarregue a página e veja a conversa na lista.
5. Instalar a cópia de segurança diária (abaixo).

A senha só é lida pelo Postgres na primeira vez, quando ele cria o banco. Para trocá-la depois, troque no banco
(`docker exec -it bi_banco psql -U bi -d bi -c "ALTER USER bi PASSWORD 'nova'"`), no `banco.env` e no `config.ini`,
e reinicie o painel.

#### Cópia de segurança

O `deploy/backup_banco.sh` grava uma cópia (`pg_dump`) por dia em `/opt/backups/bi-banco/` e apaga as de mais de
14 dias. Para instalar, rode `crontab -e` e acrescente a linha abaixo (03:30 no horário do servidor, que é UTC;
00:30 em Brasília):

```
30 3 * * * bash /opt/bi-mais-vida/deploy/backup_banco.sh >> /var/log/bi-banco-backup.log 2>&1
```

Rode uma vez à mão para conferir: `bash /opt/bi-mais-vida/deploy/backup_banco.sh`.

Para conferir se uma cópia abre, sem mexer no banco do site:

```bash
docker exec bi_banco createdb -U bi teste_restauracao
docker exec -i bi_banco pg_restore -U bi -d teste_restauracao < /opt/backups/bi-banco/bi-AAAA-MM-DD.dump
docker exec bi_banco psql -U bi -d teste_restauracao -c "select count(*) from conversas"
docker exec bi_banco dropdb -U bi teste_restauracao
```

Para voltar o banco do site para uma cópia (perde o que foi gravado depois dela):

```bash
docker exec -i bi_banco pg_restore -U bi -d bi --clean --if-exists < /opt/backups/bi-banco/bi-AAAA-MM-DD.dump
cd /opt/bi-mais-vida/deploy && docker compose restart bi
```

#### Versão que trouxe os usuários e as regras para o banco

Na primeira subida dessa versão, o painel cria as tabelas novas e importa os arquivos da pasta: `usuarios.json`,
`config_metas.json`, `config_projecoes.json` e `logs/assistente-*.jsonl`. O log mostra, por exemplo:

```
migração: 5 usuários importados de usuarios.json
migração: regras de metas importadas de config_metas.json
banco de dados bi@bi_banco:5432/bi pronto (migrações aplicadas agora: 002_usuarios, …, 006_conversas_por_usuario)
```

Depois disso:

- Todos entram de novo uma vez, porque o cookie de sessão mudou. As senhas são as mesmas.
- As conversas do Assistente continuam com os mesmos donos. Conversas de logins que não existem mais são apagadas, e
  o log diz quantas.
- Os arquivos ficam na pasta só como cópia. Mudar um deles não muda mais nada.
- Se o `usuarios.json` não estiver na pasta e já houver conversas, a migração para com
  `nenhum usuário foi importado`, e o login mostra que a atualização das tabelas falhou. Nada é apagado. Ponha o
  arquivo de volta e reinicie o painel.

#### Versão dos indicadores das campanhas (migração 008)

Esta versão troca as 4 métricas das campanhas por tipos (positivação, mix médio, efetividade, frequência, preço médio
e Personalizada) e passa a ler os **pedidos de venda** do ERP, para a efetividade.

- **Ordem:** pode atualizar o PC antes ou depois do site. O site com o código anterior ignora a tabela de pedidos no
  pacote; o site novo sem ela mostra a efetividade sem números, com o aviso "os pedidos de venda ainda não chegaram",
  até o PC mandar.
- **No PC:** ao abrir a versão nova, o painel lê o banco do ERP de novo uma vez (etapa "Lendo pedidos de venda") e
  manda ao site. Se a leitura dos pedidos falhar, o resto do painel segue normal; o log mostra "não deu para ler os
  pedidos de venda", e ele tenta de novo na próxima cópia do banco.
- **A migração 008** converte as campanhas que já existem (faturamento, volume e mix viram Personalizada, com os
  mesmos números) e cria as tabelas `campanha_produtos` e `areas_atendimento`. Esta última já vem com as 84 áreas da
  planilha "Dia de Atendimento Areas Comerciais.xlsx". Ensaie a migração antes de publicar, como nas outras com
  dados.
- **Voltar atrás:** depois da 008, o código anterior não entende as campanhas convertidas. Voltar exige restaurar a
  cópia do banco feita antes da publicação, não só a pasta.
- **Depois de publicar:** o administrador abre Gestão › Configurar › Dias de atendimento no site e completa as áreas
  pendentes (o PC e o site têm cada um a sua tabela, e vale a do site).

#### Versão da Gestão da equipe (migração 009)

Esta versão troca o quadro kanban de campanhas pela Gestão da equipe: ações por vendedor (com base, alvo e resultado
congelado), objetivos da região e o histórico interno de cada vendedor. Só o administrador lança e muda; quem tem a
página acompanha os vendedores do acesso.

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram.
- **A migração 009** só acrescenta colunas (`tipo`, `regiao`, `alvo_tipo`, a janela da base, o resultado e a
  `versao`) e a tabela `gestao_eventos`. Campanhas de antes, sem região, ficam arquivadas (no PC e no site não havia
  nenhuma). Ensaie a migração antes de publicar, como nas outras com dados.
- **Voltar atrás:** depois da 009, o código anterior não entende as ações. Voltar exige restaurar a cópia do banco
  feita antes da publicação, não só a pasta.
- **Depois de publicar:** o administrador confere em Gestão › Configurar quem acompanha quais vendedores (o acesso
  de cada pessoa continua o mesmo de antes).

#### Versão da base por período fechado (migração 012)

Na tela, "ação" volta a se chamar **campanha**. A base de cada vendedor passa a ser um período fechado escolhido no
formulário (semana, quinzena, mês, trimestre, semestre ou ano, o último antes do início). A meta fica com dois tipos:
Número (o valor a atingir) e Percentual (a base + X%). Os cards dos vendedores mostram só as campanhas em vigor,
coloridas pelo % da meta, e o card da campanha ganha a barra da meta.

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram.
- **A migração 012** só acrescenta a coluna `base_periodo` em `campanhas` (vazia nas campanhas que já existem, que
  continuam com a base do mesmo tamanho, logo antes do início). Ensaie antes de publicar, como nas outras.
- **Voltar atrás:** o código anterior ignora a coluna. As campanhas lançadas na versão nova mantêm a base gravada, mas
  lá Prorrogar e Encerrar voltam a medir a base do mesmo tamanho, logo antes.
- **Assistente:** a ferramenta `propor_acao` ganhou o parâmetro `base` e o `alvo_tipo` só aceita `fixo` e `pct`.
  Depois de publicar, confira com uma pergunta curta de dentro do container (o modelo do VPS pode ser outro).

#### Versão da cobertura com o histórico da carteira (migração 016)

A positivação ganha a **% da base** (a cobertura, mês a mês) e a opção de meta em % da base; a "Cobertura da carteira"
sai da Personalizada. O PC passa a registrar o **histórico da carteira** a cada extração (`bi/carteira.py`) e manda as
tabelas `clientes_vigencias` e `carteira_retratos` dentro do cache.

- **Ordem:** pode publicar o site antes. Sem as tabelas no cache, a cobertura dos meses desde outubro/2026 fica
  "aguardando" (a base não é gravada com a planilha no lugar do histórico); os meses de antes saem da planilha METAS.
- **No PC, antes de reabrir o painel com a versão nova:** a semeadura (os retratos de 15/09 e 19/10/2026) tem de entrar
  antes da primeira extração, porque o registro recusa um dia anterior ao último. Ela aplica a 016 no banco do PC e
  lê o dump e a cópia de 19/10 só para leitura. Depois, o painel extrai de novo uma vez sozinho (cache sem a carteira)
  e manda ao site.
- **A migração 016** cria as duas tabelas e as colunas `base_cobertura` e `resultado_cobertura` em
  `campanha_vendedores`. As bases já gravadas de positivação ganham só a cobertura na leitura seguinte, sem mudar a
  base nem a meta. Ensaie antes de publicar, como nas outras.
- **Sem o banco do PC:** a extração segue e leva o histórico do cache anterior (o log diz "não deu para registrar a
  carteira"). Se o banco do PC se perder, o histórico volta do cache na extração seguinte. Mesmo assim, agende a
  cópia de segurança do PC (abaixo): o histórico nasce lá.
- **Voltar atrás:** o código anterior ignora as tabelas e as colunas novas, mas lê uma campanha lançada com a meta em
  % da base como positivação em clientes (com a base em % gravada): arquive ou exclua essas antes de voltar.
- **Assistente:** `propor_acao` ganhou `meta_em` (clientes ou pct_base) e não oferece mais a forma `pct_carteira`.

#### A % da base com a lista do início (migração 017)

A cobertura passa a dividir pelos clientes ativos da carteira **no início** da campanha. É uma lista que não muda:
quem entra ou volta depois não conta nos ativos, e quem sai continua. O numerador são todos os clientes que o vendedor
atendeu. Na base de trimestre, semestre ou ano, cada mês usa os ativos do seu 1º dia.

- **A migração 017** não cria nada. Nas positivações ainda sem resultado congelado, ela apaga a cobertura gravada com a
  regra da 016, que volta medida na leitura seguinte. Na meta em % da base, a base inteira volta a "aguardando", com o
  retrato dos eventos, como na 014. As campanhas congeladas ficam como estão. Ensaie antes de publicar.
- **Voltar atrás:** o código da 016 mede a cobertura de novo só onde ela estiver vazia. Para recalcular com a regra
  antiga, rode a 017 de novo no banco antes de voltar.

#### Tarefas na agenda (migração 020)

A agenda do topo da Gestão ganha as **tarefas**: prazo, participantes (com ou sem autonomia) e subtarefas para cada um.

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram.
- **A migração 020** só cria as tabelas `agenda_tarefas`, `agenda_tarefa_pessoas` e `agenda_subtarefas`; as
  atividades ficam como estão.
- **Voltar atrás:** o código anterior ignora as tabelas novas (as tarefas somem da agenda e voltam com a versão nova).

#### Kanban e justificativa do atraso nas tarefas (migrações 021 e 022)

O formulário da agenda passa a abrir em tela cheia, os dias se escolhem em quadradinhos, as tarefas ganham o kanban
(A fazer, Fazendo e Concluída) e o atraso de uma tarefa ou subtarefa pode ser justificado.

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram.
- **A migração 021** só acrescenta a coluna `iniciada_em` (vazia) em `agenda_tarefas` e `agenda_subtarefas`: tudo o
  que já existe começa em A fazer (ou Concluída, se já foi concluído).
- **A migração 022** só acrescenta as colunas da justificativa (`justificativa`, vazia, e `justificada_em`; na
  subtarefa, também `justificada_por`).
- **Voltar atrás:** o código anterior ignora as colunas novas (quem estava em Fazendo aparece só como aberta, e as
  justificativas ficam guardadas sem aparecer).

#### Situação da tarefa por qualquer participante (migração 023)

Qualquer pessoa da tarefa muda a situação dela (arrasta no kanban, conclui e reabre), não só quem criou.

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram.
- **A migração 023** só acrescenta `concluida_por` (vazia) em `agenda_tarefas`; as tarefas concluídas antes dela
  ficam sem quem concluiu.
- **Voltar atrás:** o código anterior ignora a coluna nova e volta a deixar só quem criou mudar a situação.

#### Sugestão de Metas (migração 024)

A página nova **Sugestão de Metas** sugere a meta do mês seguinte de cada vendedor, por produto (as páginas de sugestão
do Power BI), com a configuração própria e a ferramenta `sugestao_metas` no Assistente.

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram (a página usa as vendas
  por cliente do cache, a METAS.xlsx e os dias de atendimento das áreas, que já chegam ao site).
- **A migração 024** só troca o CHECK de `regras.nome` para aceitar `'sugestao'`; nenhuma regra existente muda.
- **Depois de publicar:** os administradores já veem a página; para os outros, marque a página em Usuários (os
  vendedores seguem o acesso de Metas). Em Configurar › Faturamentos por área, confira as áreas "fica fora" e o prazo do
  faturamento contra o dia que as vendas mostram.
- **Voltar atrás:** o código anterior ignora as regras com nome `sugestao` (ficam guardadas) e o CHECK novo não o atrapalha.

#### Aprovação de metas (migração 025)

A aba **Aprovação de metas** (Sugestão de Metas › Configurar) grava as metas aprovadas na tabela nova `metas_aprovadas`, e o
painel de Metas passa a usar a aprovada no lugar das linhas das planilhas daquele vendedor e mês.

- **Ordem:** só o site precisa da versão nova. Os dados que o PC manda não mudaram, e as planilhas continuam chegando
  como antes.
- **A migração 025** só cria a tabela `metas_aprovadas` e o índice; nada existente muda. Ensaie em BEGIN/ROLLBACK como as
  outras.
- **Depois de publicar:** sem nenhuma aprovação, o painel de Metas fica igual (só as planilhas). Aprovar no site não muda o
  painel do PC, que tem o próprio banco.
- **Voltar atrás:** o código anterior não lê a tabela (ela fica guardada) e volta a mostrar só as planilhas.

#### Horário com fim, horário ocupado e atividade de vários dias (migração 026)

Na agenda, a atividade ganha o fim do horário e pode ficar com o **horário ocupado** (ninguém marca outra coisa para a
pessoa nele: nem ela, nem quem cria tarefas), e a **Única** aceita o último dia (aparece em todos os dias do início ao
fim).

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram.
- **A migração 026** acrescenta `hora_fim` (vazia) e `ocupado` (falso) em `agenda_atividades`, com os CHECKs, e troca
  o CHECK do `fim` para aceitar a Única com o último dia. As atividades existentes ficam como estavam.
- **Voltar atrás:** nada muda no banco. O código anterior ignora `hora_fim` e `ocupado` (o horário deixa de ser
  conferido) e mostra a Única de vários dias só no primeiro dia.

#### Justificativa obrigatória, com histórico (migração 027)

Tarefa ou subtarefa vencida e ainda aberta bloqueia o painel de quem responde por ela até ele justificar e, se
continuar atrasada, pede de novo a cada 24 horas. As justificativas viram um histórico (tabela nova
`agenda_justificativas`), e o prazo com horário passa a vencer no horário, não no dia seguinte.

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram.
- **A migração 027** cria `agenda_justificativas`, copia para ela as justificativas que existem (com o prazo de agora
  e o dia em que foram escritas) e **tira as colunas** `justificativa` e `justificada_em` de `agenda_tarefas` e de
  `agenda_subtarefas`, e `justificada_por` de `agenda_subtarefas`. Ensaie em BEGIN/ROLLBACK, como as outras.
- **Depois de publicar:** quem tem tarefa ou subtarefa vencida e aberta é bloqueado no primeiro acesso até justificar;
  uma justificativa de antes com mais de 24 horas, de item ainda aberto, é pedida de novo. Vale avisar a equipe
  antes de publicar.
- **Voltar atrás:** o código anterior lê as colunas que a 027 tirou: é preciso restaurar o dump de antes da
  publicação (as justificativas escritas depois dela se perdem).

#### Notificações, o sino (migração 028)

Quem tem a página Gestão ganha o **sino** no topo, com o que acontece nas tarefas da agenda (incluído numa tarefa,
subtarefa nova, prazo mudado, vence em breve, venceu, concluída, justificativa enviada).

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram.
- **A migração 028** só cria a tabela `notificacoes` e o índice; nada existente muda. Ensaie em BEGIN/ROLLBACK, como
  as outras.
- **Depois de publicar:** o sino começa vazio. Os avisos de ação aparecem a partir das ações seguintes; os de prazo
  nascem no primeiro acesso de cada pessoa ("venceu" só para os prazos dos últimos 7 dias).
- **Voltar atrás:** o código anterior não lê a tabela (ela fica guardada) e o sino some.

#### Reanálises de crédito (migração 029)

Na Reavaliação de Crédito, depois do parecer de um limite novo, quem tem a página registra o limite e o prazo liberados
e a justificativa, e o painel grava junto o retrato do cliente (tabela nova `credito_reanalises`). O Assistente de quem
tem a página lê as reanálises (ferramenta `reanalises_credito`).

- **Ordem:** só o site precisa da versão nova (as reanálises ficam só nele). Os dados que o PC manda não mudaram; o PC
  pode atualizar antes ou depois e só cria a tabela, vazia.
- **A migração 029** só cria a tabela `credito_reanalises` e o índice; nada existente muda. Ensaie em BEGIN/ROLLBACK,
  como as outras.
- **Depois de publicar:** a página mostra "Nenhuma reanálise registrada" até a primeira. Confira o Assistente com uma
  chamada curta à API de dentro do container (o modelo do site é outro que o do PC). A ferramenta nova não é strict:
  strict, a gramática passava do limite da API, que recusava todo pedido.
- **Voltar atrás:** o código anterior não lê a tabela (ela fica guardada) e o registro some da página.

#### Título longo da subtarefa e partes minimizadas na Gestão (migração 030)

Na agenda, o título da subtarefa aceita até 2000 caracteres (antes, 120). Na Gestão, cada parte (agenda, objetivos,
campanhas, equipe) ganha o − que a deixa só com o título, e a barra de cima ganha o Minimizar tudo.

- **Ordem:** pode atualizar o PC antes ou depois do site: os dados que o PC manda não mudaram.
- **A migração 030** só troca o CHECK do título em `agenda_subtarefas` (de 120 para 2000 caracteres); nada existente
  muda. Ensaie em BEGIN/ROLLBACK, como as outras.
- **Depois de publicar:** quem tinha a agenda recolhida (só a faixa de dias) passa a vê-la só com o título; o + mostra
  de novo.
- **Voltar atrás:** o CHECK novo não atrapalha o código anterior, que mostra as subtarefas de título longo mas recusa
  salvar a tarefa enquanto alguma passar de 120 caracteres (é preciso encurtar).

#### Google Agenda, só leitura (migração 031)

Cada pessoa conecta as agendas do Google dela pelo endereço secreto no formato iCal; os eventos aparecem na agenda da
Gestão e os marcados como Ocupado travam o horário dela para as tarefas dos outros (veja o README, "Google Agenda"). O
BI só lê: nada é escrito no Google. É o primeiro trabalho que o servidor faz sozinho de tempos em tempos: a thread
`google` relê cada agenda a cada 10 minutos, baixando de `calendar.google.com`.

- **Ordem:** só o site precisa da versão nova (a leitura liga onde há a chave de `[google]`, e só o site terá). Os dados
  que o PC manda não mudaram; o PC pode atualizar antes ou depois e só cria as tabelas, vazias.
- **Pacotes novos:** `icalendar`, `recurring-ical-events`, `x-wr-timezone` e `cryptography`, na linha `RUN pip install`
  do `deploy/Dockerfile` (e no `requirements.txt`). O `docker compose up -d --build` do passo 3 de
  [Publicar uma versão nova do código](#publicar-uma-versão-nova-do-código) refaz a imagem com eles (o servidor precisa
  de internet para baixar). Para conferir que a imagem nova está no ar:
  `docker exec bi_metas python -c "import icalendar, recurring_ical_events, cryptography"`.
- **A chave:** gere uma chave nova (no PC, `python app.py --gerar-chave`; não use a de `[publicacao]`) e, no servidor,
  `nano /opt/bi-mais-vida/config.ini` e acrescente no fim:

  ```ini
  [google]
  chave = ...
  ```

  Ela cifra os endereços secretos que as pessoas colam (cada endereço dá acesso de leitura à agenda inteira). Fica
  fora do banco e das cópias de segurança dele; trocar a chave obriga cada pessoa a colar o endereço de novo. Dá para
  publicar primeiro sem a chave (a janela do Google avisa que a leitura está desligada) e acrescentar depois, com um
  `docker compose restart`.
- **A migração 031** só cria as tabelas `google_agendas` e `google_eventos` e o índice; nada existente muda. Ensaie em
  BEGIN/ROLLBACK, como as outras.
- **Depois de publicar:** o log mostra `031_google_agenda` e "leitura do Google Agenda ligada". Conecte uma agenda de
  verdade e confira a primeira leitura, um evento Ocupado recusando a tarefa de outro usuário e o Disponível passando.
  Acompanhe a memória durante as leituras (`docker stats bi_metas`; o arquivo do Google traz o histórico inteiro da
  agenda, e o painel corta o que é antigo antes de interpretar) e confira que nenhum endereço foi para o log:
  `docker compose logs bi | grep -c private-` tem de dar 0.
- **Voltar atrás:** tirar a chave de `[google]` e `docker compose restart` desliga a leitura (nada do Google aparece
  nem trava). O código anterior não lê as tabelas (elas ficam guardadas): não precisa restaurar o banco.

#### Google Agenda pelo login com o Google (migração 032)

A conexão deixa de ser pelo endereço secreto no formato iCal e passa a ser o **login com o Google** (OAuth, só a
permissão `calendar.readonly`): a pessoa clica em **Entrar com o Google**, escolhe a conta e autoriza; o BI guarda a
autorização cifrada e lê as agendas que ela ligar pela API do Google Agenda (veja o README, "Google Agenda"). O app
fica **sem a verificação do Google**: cada pessoa vê uma vez o aviso "O Google não verificou este app" (Avançado ›
Acessar bi.maisvida.cloud), e o Google limita o app a 100 pessoas, o que sobra para a equipe.

- **O projeto no Google Cloud (uma vez, com uma conta Google da empresa, não de um funcionário):**
  1. Em console.cloud.google.com, no seletor de projetos, **Novo projeto** › "BI Mais Vida".
  2. **APIs e serviços › Biblioteca** › "Google Calendar API" › **Ativar**.
  3. **Google Auth Platform** (ou "Tela de permissão OAuth") › **Começar**: nome do app "BI Mais Vida", o e-mail de
     suporte, público **Externo**, o e-mail de contato › **Criar**. Depois, em **Branding**: página inicial
     `https://bi.maisvida.cloud/`, política de privacidade `https://bi.maisvida.cloud/privacidade.html` (a página
     web/privacidade.html, aberta sem login) e o domínio autorizado `maisvida.cloud`. Sem eles, o **Publicar app** do
     passo 5 fica bloqueado.
  4. **Acesso a dados** › **Adicionar ou remover escopos** › `https://www.googleapis.com/auth/calendar.readonly` ›
     **Atualizar** › **Salvar**.
  5. **Público** › **Publicar app** › confirmar ("Em produção"). No modo de teste, a autorização vence a cada 7 dias e
     cada pessoa teria de entrar de novo toda semana.
  6. **Clientes** › **Criar cliente** › tipo **Aplicativo da Web**; em **URIs de redirecionamento autorizados**,
     `https://bi.maisvida.cloud/api/agenda/google/retorno` › **Criar**. Baixe o JSON na hora: o segredo do cliente só
     aparece nesse momento.
- **No servidor:** em `/opt/bi-mais-vida/config.ini`, na seção `[google]` (que já tem a `chave`), acrescente o
  `cliente_id` e o `cliente_segredo` do JSON. O endereço de retorno já vem certo no código (`retorno =` só se o site
  mudar de endereço). Sem os dois, a janela do Google avisa que falta configurar o login, e nada do Google aparece nem
  trava. Depois de mudar, `docker compose restart`.
- **Pacotes:** saem `icalendar`, `recurring-ical-events` e `x-wr-timezone`; fica o `cryptography`. A imagem é refeita
  no `up -d --build` de sempre.
- **A migração 032** cria `google_contas` e muda `google_agendas` (sai o endereço; entram a conta, se é a principal e se
  está ligada). As agendas conectadas pelo endereço secreto **saem, com os eventos**: elas não servem para a leitura
  nova, e cada pessoa entra com o Google de novo. Antes de publicar, `SELECT count(*) FROM google_agendas` mostra
  quantas são (em 29/10/2026, nenhuma). Ensaie em BEGIN/ROLLBACK, como as outras.
- **Depois de publicar:** o log mostra `032_google_login` e "leitura do Google Agenda ligada". Entre com uma conta de
  verdade e confira a primeira leitura, ligar uma segunda agenda, um evento Ocupado recusando a tarefa de outro
  usuário e o Disponível passando. Nenhuma autorização vai para o log (as do Google começam com `ya29.` e `1//`):
  `docker compose logs bi | grep -c 'ya29\.\|1//'` tem de dar 0.
- **Voltar atrás:** tirar `cliente_id` e `cliente_segredo` (ou a `chave`) e `docker compose restart` desliga a leitura.
  O código anterior não sabe ler as tabelas novas: para voltar a ele, restaure o banco de antes junto com a pasta.

#### Premiações (migração 034)

A página nova **Premiações** traz as páginas "Premiacao Vendedores" e "Premiacao Supervisores" do Power BI, com abas, e a
configuração própria (faixas, pesos, metas e nomes dos supervisores).

- **Ordem:** qualquer uma, mas a página só fica completa com as duas pontas. O site mostra a página assim que recebe o
  código. Os **brindes** (tabela nova `brindes_clientes_itens` do cache) só chegam depois que o painel do PC roda o código
  novo: feche e abra o `iniciar.bat`, e a primeira extração lê os brindes e manda ao site. Até lá, a aba Supervisores
  avisa e conta sem eles. O código anterior do site aceita o cache com a tabela nova (ignora o que não conhece).
- **A migração 034** só troca o CHECK de `regras.nome` para aceitar `'premiacoes'`; nenhuma regra existente muda.
- **Depois de publicar:** os administradores já veem a página; para os outros, marque a página em Usuários (os vendedores
  seguem o acesso de Metas; a aba Supervisores só aparece para quem vê todos os vendedores).
- **Voltar atrás:** o código anterior ignora as regras com nome `premiacoes` (ficam guardadas), o CHECK novo e a tabela de
  brindes do cache.

#### Premiações – aba Comissão (sem migração)

A aba **Comissão** das Premiações calcula a comissão dos vendedores das equipes BA e ES: a comissão gravada no ERP em
cada venda, menos as devoluções e os brindes danificados e vencidos.

- **Ordem:** qualquer uma; não há migração.
  - As duas tabelas novas do cache (`comissoes_vendas` e `comissoes_percentuais`) só chegam ao site depois que o painel do
    PC roda o código novo. Para isso, feche e abra o `iniciar.bat`: a primeira extração lê a comissão (e os brindes, se
    ainda faltarem) e manda ao site. A leitura da comissão leva uns 8 segundos a mais em cada extração.
  - Até lá, a aba avisa que a comissão ainda não chegou.
  - O código anterior do site aceita o cache com as tabelas novas.
- **As regras:** a seção nova `comissao` (os motivos dos brindes) entra com o padrão nas versões já salvas. O código
  anterior ignora essa seção.

#### Subtarefa automática na agenda (migração 035)

Quem entra numa tarefa com autonomia (que passa a vir marcada) ganha a subtarefa automática "Crie as suas subtarefas
para programar a execução desta tarefa", no dia em que entrou e no seguinte, pulando sábado e domingo (veja o README,
"Subtarefa automática"). Com autonomia, o participante também passa a escolher o dia das subtarefas que cria para si.

- **Ordem:** qualquer uma: os dados que o PC manda não mudaram.
- **A migração 035** acrescenta `automatica` (falso nas que existem) e `inicio` (vazio) em `agenda_subtarefas`, com um
  CHECK (`inicio` até o `prazo`) e um índice único (uma automática por pessoa em cada tarefa). Nada existente muda:
  as tarefas de antes não ganham automáticas. Ensaie em BEGIN/ROLLBACK, como as outras.
- **Depois de publicar:** crie uma tarefa com prazo para depois de amanhã e uma pessoa de teste; a automática aparece
  para ela hoje e no próximo dia de segunda a sexta. Tire a autonomia e salve: a automática sai.
- **Voltar atrás:** o código anterior não conhece as colunas novas e mostraria as automáticas como subtarefas comuns,
  só no dia do prazo. Antes de voltar, apague-as (`DELETE FROM agenda_subtarefas WHERE automatica`); as colunas podem
  ficar.

#### Voltar as regras para uma versão anterior

Cada Salvar em Metas › Configurar, em Projeções › Configurar, em Sugestão de Metas › Configurar e em Premiações ›
Configurar grava uma versão nova na
tabela `regras`. Para voltar a
uma delas, no console SQL (`docker exec -it bi_banco psql -U bi -d bi`):

```sql
-- as versões, da mais nova para a mais antiga (nome = metas, projecoes, sugestao ou premiacoes)
SELECT id, nome, salva_em, salva_por_nome FROM regras ORDER BY id DESC LIMIT 20;
-- copia a versão 12 como a mais nova (troque o 12)
INSERT INTO regras (nome, dados, salva_por_nome) SELECT nome, dados, 'volta para a versão 12' FROM regras WHERE id = 12;
```

Depois, `docker compose restart bi`: o painel lê as regras do banco quando sobe. No PC, use o `psql` do PostgreSQL
instalado (veja [Banco de dados no PC](#banco-de-dados-no-pc-postgresql)) e feche e abra o painel.

#### Comandos úteis

```bash
cd /opt/bi-mais-vida/deploy
docker compose logs banco --tail 50              # mensagens do banco
docker exec -it bi_banco psql -U bi -d bi        # console SQL (\dt lista as tabelas, \q sai)
docker stats bi_banco                            # memória em uso
```

Não troque a imagem para outra versão principal do Postgres (por exemplo, 19) só mudando o número: o formato dos
arquivos muda entre versões principais. Para trocar, faça a cópia, suba o banco novo vazio e restaure nele.

### Esqueci a senha de administrador do site

O banco só é visto de dentro do Docker, então o comando roda no container do painel, com ele no ar:

```bash
cd /opt/bi-mais-vida/deploy
docker compose exec bi python app.py --senha LOGIN   # pede a senha nova duas vezes
```

Se o login não existir, ele cria um administrador com esse nome. A senha vale na hora, sem reiniciar.

### Banco de dados no PC (PostgreSQL)

O painel do PC também guarda usuários, regras, conversas e uso do Assistente num PostgreSQL, instalado no próprio
Windows. Sem ele, ninguém entra no painel do PC, mas a extração e o envio dos dados ao site continuam.

#### Instalar (uma vez)

1. Baixe o instalador do PostgreSQL 18 para Windows em postgresql.org/download/windows (o da EDB) e instale com as
   opções padrão: porta 5432 e serviço `postgresql-x64-18`, que abre junto com o Windows. Anote a senha do
   usuário `postgres`. O Stack Builder, no fim, não é necessário. O instalador só aceita conexões deste
   computador. Não abra a porta 5432 no firewall.
2. Crie o usuário e o banco do painel, no PowerShell (troque a senha; ele pede a senha do `postgres`):

   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE ROLE bi LOGIN PASSWORD 'UMA_SENHA_FORTE'" -c "CREATE DATABASE bi OWNER bi"
   ```

3. No `config.ini` do PC, acrescente:

   ```ini
   [postgres]
   senha = UMA_SENHA_FORTE
   ```

   O resto (`host = localhost`, porta, banco e usuário `bi`) vem de `config.exemplo.ini`.
4. Instale o pacote do banco: `pip install "psycopg[binary]==3.3.6" psycopg-pool==3.3.3`.
5. Feche e abra o painel (`iniciar.bat`). Na janela preta aparecem as migrações e a importação dos arquivos do PC
   (veja [Versão que trouxe os usuários e as regras para o banco](#versão-que-trouxe-os-usuários-e-as-regras-para-o-banco)).

#### Cópia de segurança no PC

O `deploy/backup_banco_pc.ps1` grava uma cópia (`pg_dump`) por dia em `Documentos\backups-bi-banco` e apaga as de
mais de 14 dias. Para instalar:

1. Crie o arquivo `%APPDATA%\postgresql\pgpass.conf` (a pasta `postgresql` pode não existir) com uma linha:
   `localhost:5432:bi:bi:UMA_SENHA_FORTE`. É de onde o `pg_dump` lê a senha.
2. Agende, no PowerShell (os comandos estão também no começo do script):

   ```powershell
   $acao = New-ScheduledTaskAction -Execute powershell.exe -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\Micro\Desktop\BI MAIS VIDA\bi-mais-vida\deploy\backup_banco_pc.ps1"'
   Register-ScheduledTask -TaskName "BI Mais Vida - copia do banco" -Action $acao -Trigger (New-ScheduledTaskTrigger -Daily -At 12:30)
   ```

3. Rode uma vez à mão para conferir: `powershell -ExecutionPolicy Bypass -File deploy\backup_banco_pc.ps1`.

Para voltar o banco do PC para uma cópia (perde o que foi gravado depois dela), feche o painel e rode:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -U bi -h localhost -d bi --clean --if-exists "$env:USERPROFILE\Documents\backups-bi-banco\bi-AAAA-MM-DD.dump"
```

### Trocar a chave de envio

A chave é o que garante que só o PC da empresa consegue mandar dados para o site. Ela precisa ser **igual** nos
dois lados.

1. No PC, na pasta do projeto: `python app.py --gerar-chave`. Copie a linha `chave = ...` que aparecer.
2. Troque a linha `chave = ...` em `[publicacao]` nos dois arquivos:
   - no PC: `config.ini`, na pasta do projeto;
   - no servidor: `/opt/bi-mais-vida/config.ini` (`nano /opt/bi-mais-vida/config.ini`).
3. Reinicie os dois: no servidor, `cd /opt/bi-mais-vida/deploy && docker compose restart`. No PC, feche e abra
   o painel.

### HTTPS (Caddy)

O certificado é da Let's Encrypt, e o Caddy renova sozinho. O bloco do painel no Caddyfile é:

```
bi.maisvida.cloud {
    encode gzip
    reverse_proxy bi_metas:8050 {
        header_up X-Forwarded-For {remote_host}
    }
}
```

O Caddy repassa ao painel o IP real de quem acessa, no cabeçalho X-Forwarded-For. A linha `header_up` só deixa
isso explícito. O painel usa esse IP no limite de senhas erradas: sem ele, todo mundo apareceria com o IP do
Caddy, e 20 senhas erradas de qualquer pessoa bloqueariam o login de todos.

Cuidados ao mexer nesse arquivo:

- Ele é do app de promotoria e controla o HTTPS de todos os sistemas do servidor. Faça uma cópia antes
  (`cp -p Caddyfile Caddyfile.bak-$(date +%Y%m%d%H%M%S)`).
- O container monta esse arquivo sozinho. Editores que gravam um arquivo novo no lugar do antigo fazem o
  container continuar vendo a versão velha. Depois de editar, confira com
  `docker exec estoque_caddy cat /etc/caddy/Caddyfile`.
- Valide e só então recarregue (os outros sites não saem do ar):

  ```bash
  docker exec estoque_caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && \
  docker exec estoque_caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  ```

- Os blocos da Evolution API, do RAG e do BI não estão no git do app de promotoria. Se alguém refizer o
  Caddyfile a partir daquele repositório, os três somem.

### Como o envio funciona por dentro

A cada 30 segundos, o painel do PC confere se o cache ou uma das planilhas mudou desde o último envio aceito.
Se mudou, ele monta um `.zip` com `cache.duckdb`, `METAS.xlsx` e `METAS PRODUTOS.xlsx` e manda para
`https://bi.maisvida.cloud/api/publicacao/receber`, assinado com HMAC-SHA256 usando a chave. A chave em si
não trafega.

O servidor confere a assinatura e a hora do envio, abre o cache e as planilhas recebidas e só então troca os
arquivos em uso. Se qualquer coisa falhar, ele mantém os dados anteriores e devolve o motivo, que aparece no
rodapé do painel do PC. O código está em [bi/publicacao.py](../bi/publicacao.py).

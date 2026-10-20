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
conversas e uso do Assistente, as ações, os objetivos e o histórico da página Gestão (migrações `007_gestao.sql`,
`008_indicadores.sql` e `009_gestao_equipe.sql`) e os dias de atendimento das áreas comerciais.

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

#### Voltar as regras para uma versão anterior

Cada Salvar em Metas › Configurar e em Projeções › Configurar grava uma versão nova na tabela `regras`. Para voltar a
uma delas, no console SQL (`docker exec -it bi_banco psql -U bi -d bi`):

```sql
-- as versões, da mais nova para a mais antiga (nome = metas ou projecoes)
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

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
                                     os números (~3 MB)                troca os números
                                     e manda pela internet
```

O banco inteiro não vai para o site: são 7 GB, e o painel só precisa do resumo de vendas, clientes e
devoluções, que tem uns 3 MB. Isso também é mais seguro, porque o banco do ERP nunca sai da empresa.

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

3. **Espere uns 2 minutos.** O painel percebe a cópia nova sozinho, lê o banco (uns 15 segundos) e manda os
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

O site e o painel do PC têm **cadastros separados**. O que muda num não muda no outro.

| Quero... | Onde fazer |
|---|---|
| Dar acesso a alguém, mudar o que a pessoa vê ou bloquear um acesso | No site, página **Usuários** (só administradores) |
| Mudar regras: grupo de cada vendedor e produto, motivos de devolução, feriados | No site, página **Metas** › botão **Configurar** (só administradores) |
| Escolher os vendedores das projeções e o que cada pessoa vê nelas | No site, página **Projeções** › botão **Configurar** (só administradores) |
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
| Painel: código, `config.ini` (modo vps e a chave), `usuarios.json`, `config_metas.json`, `config_projecoes.json`, `dados/`, `logs/` | `/opt/bi-mais-vida` |
| Container `bi_metas` (Python 3.12, usuário 10001, até 512 MB, horário de Brasília) | `/opt/bi-mais-vida/deploy/docker-compose.yml` |
| HTTPS de `bi.maisvida.cloud`, encaminhado para `bi_metas:8050` | bloco no fim de `/opt/app-promotoria/Caddyfile` (container `estoque_caddy`) |
| Rede que liga o Caddy ao painel | `app-promotoria_estoque_network` |

O painel não abre porta para a internet: só o Caddy fala com ele, pela rede Docker.

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
# 1. Cópia de segurança da pasta do servidor
ssh root@187.127.54.201 'cp -a /opt/bi-mais-vida /opt/bi-mais-vida.bak-$(date +%Y%m%d-%H%M)'

# 2. Enviar o código
scp -r app.py bi web deploy root@187.127.54.201:/opt/bi-mais-vida/

# 3. Acertar o dono dos arquivos e reiniciar
ssh root@187.127.54.201 'chown -R 10001:10001 /opt/bi-mais-vida && cd /opt/bi-mais-vida/deploy && docker compose up -d --build && docker compose restart'
```

O código entra no container como volume (`..:/app`). Se só o código mudou, a imagem fica igual e o `up` não
recria o container: é o `restart` que faz o painel carregar a versão nova (confira em `docker compose ps` que
o tempo de "Up" voltou a poucos segundos).

Depois, feche e abra o painel do PC (`iniciar.bat`).

**Não envie** `config.ini`, `usuarios.json`, `config_metas.json`, `config_projecoes.json`, `dados/` nem `logs/`. No servidor, esses
arquivos são diferentes dos do PC: lá estão a chave, os acessos e as regras salvas no site. Se uma versão nova
mudar o `config_metas.json` do repositório, aplique a mudança pela página Configurações do site.

Se algo der errado, volte para a cópia de segurança:

```bash
cd /opt/bi-mais-vida/deploy && docker compose down
rm -rf /opt/bi-mais-vida && mv /opt/bi-mais-vida.bak-AAAAMMDD-HHMM /opt/bi-mais-vida
cd /opt/bi-mais-vida/deploy && docker compose up -d --build
```

### Esqueci a senha de administrador do site

O painel lê os usuários só quando inicia, então pare o container antes:

```bash
cd /opt/bi-mais-vida/deploy
docker compose stop
docker compose run --rm bi python app.py --senha LOGIN   # pede a senha nova duas vezes
docker compose start
```

Se o login não existir, ele cria um administrador com esse nome.

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

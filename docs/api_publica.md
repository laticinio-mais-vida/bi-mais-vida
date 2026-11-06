# API pública da Gestão (v1)

Este guia é para quem programa **outro aplicativo** que mostra os dados da página **Gestão** do BI Mais Vida. A API é
**só de leitura**. Cada pessoa entra no outro aplicativo com o usuário e a senha que ela já tem no BI e, pela API, vê
exatamente o que vê na página Gestão do site. Isso inclui o papel (administrador ou visualizador) e os vendedores e as
regiões do acesso dela.

- **Endereço:** `https://bi.maisvida.cloud/api/v1`. Use só HTTPS. O painel do PC também responde em
  `http://127.0.0.1:8050/api/v1`, mas isso serve só para testes: os dados, os usuários e as chaves do PC são outros.
- **Quem chama:** o **servidor** do outro aplicativo. Um pedido vindo de navegador (com o cabeçalho `Origin`) é
  recusado, porque a chave não pode ficar numa página.
- **O que dá para ler:** o quadro de uma região (campanhas, objetivos e os vendedores), o detalhe de uma campanha ou de
  um objetivo e o histórico interno de um vendedor (com as observações). Agenda, tarefas e notificações não fazem parte
  da v1.

## Como funciona

1. **Entrar.** A pessoa digita no outro aplicativo o usuário e a senha do BI, e o servidor do aplicativo manda:

   ```http
   POST /api/v1/entrar
   Content-Type: application/json

   {"login": "maria.santos", "senha": "••••••", "aplicativo": "App de Visitas"}
   ```

   Resposta (200):

   ```json
   {
     "chave": "bimv_Q2xhdmUgZGUgZXhlbXBsbyBuYW8gdXNlIGVzdGEgYXF1aQ",
     "expira_em": "2027-02-04T10:00:00",
     "usuario": {"id": 5, "login": "maria.santos", "nome": "Maria Santos", "papel": "visualizador"}
   }
   ```

   - `aplicativo` é o nome que aparece para a pessoa no BI, em **menu do usuário › Aplicativos conectados**. Ele tem
     de 1 a 60 caracteres e é sempre o mesmo para o seu aplicativo.
   - A chave aparece **só nesta resposta**: o BI guarda apenas uma "impressão digital" dela e não consegue mostrá-la
     de novo.
   - Cada pessoa tem **uma chave por aplicativo**. Entrar de novo troca a chave, e a anterior para de valer na hora.
     Guarde sempre a última.
   - **Não guarde a senha.** Ela só serve para este pedido.

2. **Usar.** Em cada pedido, mande a chave no cabeçalho `Authorization`:

   ```http
   GET /api/v1/gestao/quadro?regiao=BA
   Authorization: Bearer bimv_Q2xhdmUgZGUgZXhlbXBsbyBuYW8gdXNlIGVzdGEgYXF1aQ
   ```

   A chave só é aceita nesse cabeçalho, nunca no endereço (o endereço vai parar em logs).

3. **Sair.** Quando a pessoa sai do seu aplicativo, apague a chave no BI:

   ```http
   POST /api/v1/sair
   Authorization: Bearer bimv_…
   ```

   A pessoa também pode desconectar o seu aplicativo pelo BI. Nesse caso, o próximo pedido com a chave dela volta 401.

### Até quando a chave vale

A chave vale **90 dias** a partir do login (`expira_em`). Ela para antes disso quando:

- a pessoa entra de novo pelo mesmo aplicativo (a chave nova substitui a antiga);
- o aplicativo chama `/sair`, ou a pessoa o desconecta pelo BI;
- a pessoa troca a senha, ou o administrador troca a senha dela ou a desativa (como acontece com as sessões do site);
- a pessoa é excluída do BI.

Em todos esses casos a resposta é **401**: mostre a tela de login de novo. **Nunca repita o pedido sozinho com a
mesma chave nem com a senha guardada.**

## Rotas

Todas devolvem JSON em UTF-8. Os horários estão no fuso de Brasília, sem o fuso no texto (`2026-11-06T10:00:00`); as
datas vêm como `2026-11-06`. Percentuais vêm em fração (`0.95` = 95%).

| Método e endereço | Precisa da Gestão | O que devolve |
|---|---|---|
| `POST /api/v1/entrar` | sim | a chave (acima) |
| `POST /api/v1/sair` | não | `{"ok": true}` |
| `GET /api/v1/eu` | não | quem é a pessoa da chave |
| `GET /api/v1/gestao/quadro` | sim | o quadro de uma região |
| `GET /api/v1/gestao/campanha` | sim | o detalhe de uma campanha |
| `GET /api/v1/gestao/objetivo` | sim | o detalhe de um objetivo |
| `GET /api/v1/gestao/vendedor` | sim | o histórico interno de um vendedor |

As rotas da Gestão devolvem **o mesmo JSON que a página Gestão do site recebe** (menos o campo `pode_editar`, porque
a API não edita). Abaixo estão os campos principais. Campos que não estão aqui existem e podem mudar; ignore o que o
seu aplicativo não usa.

### `GET /api/v1/eu`

```json
{
  "usuario": {"id": 5, "login": "maria.santos", "nome": "Maria Santos", "papel": "visualizador"},
  "gestao": true,
  "chave": {"aplicativo": "App de Visitas", "criada_em": "2026-11-06T10:00:00", "expira_em": "2027-02-04T10:00:00"}
}
```

`gestao: false` quer dizer que o administrador tirou a página Gestão da pessoa. A chave continua valendo, mas as rotas
da Gestão respondem 403 até a página voltar.

### `GET /api/v1/gestao/quadro?regiao=ES|BA`

O quadro de uma região. Sem `regiao`, vem a primeira região do acesso da pessoa, e `regioes` lista as que ela pode
pedir.

```json
{
  "regiao": "BA", "regioes": ["ES", "BA"], "hoje": "2026-11-06", "data_ref": "2026-11-05", "aviso": null,
  "objetivos": [ { "id": 7, "nome": "Mix médio da equipe", "inicio": "2026-11-01", "fim": "2026-11-30",
                   "situacao": "em_vigor", "prazo": {"dias": 30, "faltam": 24, "comeca_em": 0, "decorrido": 0.1667},
                   "indicador": {"tipo": "mix_medio", "nome": "Mix médio", "formato": "razao", "casas": 2},
                   "meta_padrao": 3.5, "andamento": { "…": "o andamento da equipe" }, "aviso": null } ],
  "acoes": [ { "id": 12, "nome": "Mussarela de novembro", "rotulo": "Mussarela", "inicio": "2026-11-03",
               "fim": "2026-11-28", "situacao": "em_vigor", "prazo": { "…": "como acima" },
               "vendedores": 8, "total_vendedores": 8, "meta_pct": 0.42, "com_meta": 8,
               "indicador": {"tipo": "faturamento", "nome": "Faturamento", "formato": "moeda"},
               "alvo_tipo": "pct", "meta_padrao": 10, "premiacoes": null, "aviso": null } ],
  "vendedores": [ { "id": 98, "nome": "João Silva", "equipe": "BA", "inativo": false, "em_vigor": 1,
                    "acoes": [ {"id": 12, "rotulo": "Mussarela", "situacao": "em_vigor", "fim": "2026-11-28",
                                "resultado": 4200.0, "alvo": 11000.0, "pct": 0.3818} ] } ]
}
```

- **`acoes` são as campanhas.** O nome vem de quando elas se chamavam "ações" na página.
- `data_ref` é o último dia com dados do ERP. Os números só mudam quando o BI recebe dados novos da empresa (algumas
  vezes por dia).
- `situacao`: `planejada`, `em_vigor` ou `encerrada`. Uma campanha encerrada fica no quadro por mais 30 dias, e um
  objetivo que terminou fica por mais 7.
- `prazo`: `dias` da campanha, quantos `faltam`, em quantos dias `comeca_em` e a fração `decorrido`.
- `meta_pct`: o andamento da campanha contra a meta (a soma dos resultados ÷ a soma das metas, ou a média dos % nos
  indicadores de média). `com_meta` diz quantos vendedores entraram na conta.
- `indicador`: o que a campanha mede e como mostrar o número. `formato` pode ser `moeda`, `quantidade` (com
  `unidade`), `clientes`, `produtos`, `pct` (em fração) ou `razao` (com `sufixo`). `casas` são as casas decimais, e
  `descricao` explica a conta em texto.
- `vendedores`: os cards da região, só com os vendedores do acesso da pessoa. Em `acoes` ficam só as campanhas em
  vigor de cada um, com o `resultado` até agora, o `alvo` e o `pct` (resultado ÷ alvo).
- `aviso`: um texto para mostrar quando os dados de vendas ainda estão sendo preparados, ou quando a pessoa não tem
  nenhum vendedor no acesso.

### `GET /api/v1/gestao/campanha?id=12&abrir=area`

O detalhe de uma campanha, com uma linha por vendedor do acesso da pessoa. `abrir` abre cada vendedor por `area`,
`segmento` ou `produto`. Sem `abrir`, vem a abertura padrão do indicador; com `abrir=` vazio, nenhuma. O id de um
objetivo nesta rota dá 404.

```json
{
  "item": { "id": 12, "tipo": "acao", "nome": "Mussarela de novembro", "regiao": "BA", "inicio": "2026-11-03",
            "fim": "2026-11-28", "situacao": "em_vigor", "congelado": false, "provisorio": false, "encerrada": false,
            "alvo_tipo": "pct", "meta_padrao": 10, "base_inicio": "2026-10-01", "base_fim": "2026-10-31" },
  "indicador": { "tipo": "faturamento", "nome": "Faturamento", "formato": "moeda" },
  "linhas": [ { "id": 98, "nome": "João Silva", "equipe": "BA", "base": 10000.0, "alvo": 11000.0,
                "resultado": 4200.0, "pct": 0.3818, "status": "abaixo", "projecao": 9800.0,
                "classe": "bad", "delta": -5800.0, "delta_pct": -0.58, "caminho": null } ],
  "total": { "vendedores": 8, "no_alvo": 0, "acima_da_base": 2, "realizado": 30500.0 },
  "aviso": null, "ocultos": 0, "data_ref": "2026-11-05"
}
```

- Em cada linha: `base` é o mesmo indicador no período de comparação (`base_inicio` a `base_fim` do item), `alvo` é a
  meta do vendedor, `resultado` é o valor até agora (ou o final) e `pct` é resultado ÷ alvo.
- `status` é o ritmo enquanto a campanha corre: `no_ritmo`, `atencao` (de 90% a 99% do esperado), `abaixo`, `batida`
  (encerrada e batida), `sem_meta` ou `sem_dados`.
- `classe` compara o resultado com a base e o alvo: `ok` (alvo batido), `mid` (melhorou sobre a base sem chegar ao
  alvo), `bad` (não passou da base), `sem_alvo` ou `sem_dados`.
- `congelado: true` quer dizer que o resultado final está gravado e não muda mais. `provisorio: true` quer dizer que a
  campanha acabou, mas os dados ainda não passaram do fim.
- `ocultos` conta os vendedores da campanha que estão fora do acesso da pessoa e por isso não aparecem.
- Na campanha de **preço médio**, cada linha traz também `produtos` (a grade de preços) e `aumento_pedido`. Nas
  campanhas com premiação, cada linha traz `premio` (a faixa atingida).

### `GET /api/v1/gestao/objetivo?id=7`

O objetivo do período, com o andamento da equipe da região:
`{"item": {…, "tipo": "objetivo", "parcial": …}, "andamento": {…}, "aviso": null, "data_ref": "…"}`. O id de uma
campanha nesta rota dá 404.

### `GET /api/v1/gestao/vendedor?id=98`

O histórico interno do vendedor, como na página: as observações do administrador, cada campanha de que ele participou,
as parciais de cada semana e o resultado.

```json
{
  "vendedor": {"id": 98, "nome": "João Silva", "equipe": "BA", "regiao": "BA", "inativo": false},
  "eventos": [ {"id": 301, "tipo": "lancada", "acao": 12, "data": "2026-11-03", "texto": "", "autor": "Admin",
                "criada_em": "2026-11-02T17:40:00", "dados": {"base": 10000.0, "alvo": 11000.0}},
               {"id": 305, "tipo": "nota", "acao": null, "data": "2026-11-04", "texto": "Visitar a rede X",
                "autor": "Admin", "criada_em": "2026-11-04T09:12:00", "dados": {}} ],
  "acoes": { "12": {"id": 12, "nome": "Mussarela de novembro", "situacao": "em_vigor", "participa": true} },
  "em_vigor": 1, "data_ref": "2026-11-05", "hoje": "2026-11-06"
}
```

- `eventos` vêm em ordem de data. Os tipos são `lancada`, `nota` (observação), `parcial` (o valor de uma semana),
  `editada`, `prorrogada`, `encerrada`, `removido` e `resultado`.
- `acao` é o id da campanha do evento; as informações dela ficam em `acoes`, pelo id em texto.
- O vendedor fora do acesso da pessoa dá 404.

## Erros

O corpo do erro é sempre `{"erro": "mensagem em português"}`. Mostre a mensagem à pessoa quando fizer sentido.

| Código | Quando | O que fazer |
|---|---|---|
| 400 | pedido mal formado: login sem JSON, campo faltando, região inválida | corrigir o pedido |
| 401 | senha errada no `/entrar`; chave ausente, vencida, trocada ou desconectada | mostrar o login de novo; nunca repetir sozinho |
| 403 | a pessoa não tem a página Gestão, a região está fora do acesso dela ou o pedido veio de um navegador | avisar a pessoa (o administrador do BI muda o acesso) |
| 404 | rota desconhecida, ou campanha, objetivo ou vendedor que não existe ou está fora do acesso | — |
| 405 | método errado (o cabeçalho `Allow` diz o certo) | corrigir o pedido |
| 429 | muitas senhas erradas, ou muitos pedidos com a mesma chave | esperar os segundos do cabeçalho `Retry-After` |
| 503 | dados de vendas sendo preparados, banco fora do ar, muitos pedidos ao mesmo tempo ou API desligada | tentar de novo depois do `Retry-After` (quando vier) |
| 500 | erro interno do BI | tentar mais tarde; o detalhe fica no log do BI |

## Limites

| Limite | Valor |
|---|---|
| Senhas erradas no mesmo usuário (somando o site e a API) | 5 em 15 minutos; depois, 429 até a janela passar |
| Senhas erradas vindas do mesmo endereço (o servidor do seu aplicativo) | 20 em 15 minutos; depois, novos logins por ele esperam (as chaves já emitidas continuam valendo) |
| Pedidos por chave | 30 por minuto |
| Pedidos da API ao mesmo tempo, somando todas as chaves | 3; o próximo espera até 5 s e depois recebe 503 |
| Aplicativos conectados por pessoa | 10; o 11º desconecta o mais antigo |
| Validade da chave | 90 dias |
| Corpo do `/entrar` | até 16 KB, com `Content-Type: application/json` e `Content-Length` |

Os números só mudam quando chegam dados novos da empresa (`data_ref`). Guarde cada resposta por pelo menos 1 minuto em
vez de pedir de novo a cada tela.

## Exemplo (Python)

```python
import requests

BI = "https://bi.maisvida.cloud/api/v1"

def entrar(login: str, senha: str) -> str:
    r = requests.post(f"{BI}/entrar", json={"login": login, "senha": senha, "aplicativo": "App de Visitas"},
                      timeout=30)
    if r.status_code != 200:
        raise RuntimeError(r.json()["erro"])     # 401: senha errada; 403: sem a Gestão; 429: espere
    return r.json()["chave"]                     # guarde só a chave (no servidor), nunca a senha

def quadro(chave: str, regiao: str | None = None) -> dict:
    r = requests.get(f"{BI}/gestao/quadro", params={"regiao": regiao} if regiao else None,
                     headers={"Authorization": f"Bearer {chave}"}, timeout=60)
    if r.status_code == 401:
        raise PermissionError("peça o login de novo")
    r.raise_for_status()
    return r.json()
```

`requests` não manda o cabeçalho `Origin`. Se o seu aplicativo usar outra biblioteca ou um proxy que repasse os
cabeçalhos do navegador, confira que o `Origin` não chega ao BI.

## Versão e mudanças

O `v1` do endereço é a versão. Nela:

- campos novos podem aparecer a qualquer momento (ignore os que não conhece);
- se um campo descrito aqui mudar de nome ou sair, a mudança é anotada abaixo antes de ir para o site;
- uma mudança que quebre muita coisa vira `v2`, e a `v1` continua por um tempo.

Mudanças:

- 2026-11-06: primeira versão.

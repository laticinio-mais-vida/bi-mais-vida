# Análise do BI "MAIS VIDAS-PBIT" — foco nas páginas de metas

Análise feita em 15/10/2026 a partir do `MAIS VIDAS-PBIT.pbit`, da cópia do banco
(`banco de dados\LATICINIOMAISVIDALTDA.GDB`, cópia de 15/10/2026 09:04, vendas até 14/10/2026)
e das planilhas `Documents\METAS.xlsx` e `Documents\METAS PRODUTOS.xlsx`.

---

## 1. Visão geral do PBIT

| Item | Quantidade |
|---|---|
| Páginas | 30 (9 ocultas) |
| Tabelas | 43, sendo 15 tabelas de data automáticas (LocalDateTable) que podem ser ignoradas |
| Medidas DAX | 206 |
| Relacionamentos | 51 |
| Visuais personalizados | Scrolling Text, Datepicker, Text Search Slicer |

### Fontes de dados

| Origem | Tabelas no modelo |
|---|---|
| Firebird via ODBC (`dsn=BDMAISVIDA`) | fVendas (VENDAS), fListaVenda (LISTAVENDA), dClientes (CLIENTES), dVendedores (VENDEDORES), dSegmento, dProdutos (PRODUTOS), fDevolucoes (DEVOLUCOESVENDA), fListaDevolucoes (LISTADEVOLUCAOVENDA), dMotivoDevolução (MOTIVODEVOLUCAO), fBrindes, fListaBrinde, dAreaComercial (AREASCOMERCIAIS), fPedidoVenda, fListaPedidoVenda, fContasReceber, fParcelasContaReceber, dPrazos (OPCAOPAGAMENTO) |
| Excel | dMetas (`METAS.xlsx`, Tabela1), dMetaProduto (`METAS PRODUTOS.xlsx`, Tabela3), dQuantidadeFaturamentos (`Quantidades Faturamentos.xlsx`), dDiaDeAtendimento (`Dia de Atendimento Areas Comerciais.xlsx`) |
| Calculadas em DAX | dCalendario e 7 tabelas só de medidas (Medidas Criar Metas, Medidas Indicadores, Medidas Inadimplencia, Medidas Reavaliação de Credito, Medidas Clientes Ações, Medidas Efetividade, Medidas Premiacao Supervisor) |

### Páginas por tema

| Tema | Páginas |
|---|---|
| **Metas (escopo atual)** | Metas ES, Metas BA, Metas Edir, Metas Produtos BA, Metas Outras Linhas ES |
| Sugestão de metas | Sugestão de Meta BA, Sugestão de Meta ES, Duplicata de Sugestão de Meta BA |
| Premiação | Premiacao Vendedores (oculta), Premiacao Supervisores (oculta) |
| Comercial | Areas Comerciais, Pedido Venda, Variações, Indicadores 1, Indicadores 2, Venda Detalhada, Efetividade Visitas, Cliente Ações (oculta) |
| Devoluções | Devoluções, Devoluções2, Página 2 (oculta) |
| Crédito e cobrança | Total Contas Receber, Inadimplência, Reavaliação Crédito, Cliente Nao Quitados, Clientes Quitados, Clientes Quitados e Nao Quitados, Media Primeiras Compras (as 4 últimas ocultas), Página 1 |
| Outras | Capa |

---

## 2. Modelo usado pelas páginas de metas

### Tabelas e colunas

| Tabela PBI | Origem | Colunas usadas | Transformações |
|---|---|---|---|
| fVendas | VENDAS | ID_VENDA, ID_CLIENTE, ID_VENDEDOR, DATA, DATACANCELAMENTO | DATA vira data (sem hora) |
| fListaVenda | LISTAVENDA | ID_VENDA, ID_ITEM, QUANTIDADE, VALORTOTALITEM | **ID_ITEM 3643 é trocado por 11469** (Bebida láctea bandeja 540 g → 500 g) |
| fDevolucoes | DEVOLUCOESVENDA | ID_DEVOLUCAO, ID_VENDEDOR, ENTRADA, DATACANCELAMENTO | — |
| fListaDevolucoes | LISTADEVOLUCAOVENDA | ID_DEVOLUCAO, ID_ITEM, QUANTIDADE, VALORTOTALITEM, ID_MOTIVODEVOLUCAO | mesma troca 3643 → 11469 |
| dMotivoDevolução | MOTIVODEVOLUCAO | ID_MOTIVODEVOLUCAO | — |
| dVendedores | VENDEDORES | ID_VENDEDOR, NOME | — |
| dProdutos | PRODUTOS | ID_PRODUTO, NOME | — |
| dMetas | METAS.xlsx | ID_VENDEDOR, VENDEDOR, META FATURAMENTO, META MUSSARELA, META OUTRAS LINHAS, META CLIENTE, DATA | remove META VENDA MEDIA da planilha e recalcula; cria ESTADO |
| dMetaProduto | METAS PRODUTOS.xlsx | DATA, ID_VENDEDOR, ID_PRODUTO, META VOLUME | — |
| dCalendario | DAX | Datas, Ano, Mês (nome em português, minúsculo) | — |

Colunas calculadas em dMetas:

- `META VENDA MÉDIA = META FATURAMENTO / META CLIENTE`
- `ESTADO = "BA"` se VENDEDOR estiver na lista fixa {THAIS, EWERTON, JAMILLE, VICENTE, MICHELE, HENRIQUE, FRANQUELIN, ROBSON, EDIR, MAURICIA, RICARDO +, RICARDO - EU, ROBSON - EU, THIAGO}; senão `"ES"`.

### Como os filtros se propagam

```
dCalendario[Datas] ──► fVendas[DATA]          (vendas do período)
dCalendario[Datas] ──► fDevolucoes[ENTRADA]   (devoluções pela data de ENTRADA)
dCalendario[Datas] ──► dMetas[DATA] / dMetaProduto[DATA]   (meta do mês: DATA = dia 1)

dMetas[ID_VENDEDOR] ◄═► dVendedores[ID_VENDEDOR]   (filtro nos dois sentidos)
dVendedores ──► fVendas[ID_VENDEDOR]  e  fDevolucoes[ID_VENDEDOR]
dProdutos   ──► fListaVenda[ID_ITEM], fListaDevolucoes[ID_ITEM], dMetaProduto[ID_PRODUTO]
dMotivoDevolução ──► fListaDevolucoes[ID_MOTIVODEVOLUCAO]
```

Em Python isso vira: para cada (mês, vendedor da planilha de metas), somar as vendas
cujo `VENDAS.ID_VENDEDOR` é o ID da meta e cujo `VENDAS.DATA` cai no mês, e descontar
as devoluções cujo `DEVOLUCOESVENDA.ID_VENDEDOR` é o mesmo ID e cuja `ENTRADA` cai no mês.
O vendedor é sempre o da venda, não o da carteira do cliente.
Vendedor com venda mas sem linha na planilha de metas não aparece nas páginas.

---

## 3. Medidas das páginas de metas (em linguagem de negócio)

Base comum: venda válida = `VENDAS.DATACANCELAMENTO` nula. Devolução própria = item com
`ID_MOTIVODEVOLUCAO` em {1, 2, 5, 6, 7, 8, 9} (erro de lançamento, recusa, falta de mercadoria,
cliente ausente, erro de faturamento, erro de logística, erro de expedição).

| Medida | Definição |
|---|---|
| Faturamento Liquido (Devoluções Proprias) | Σ `LISTAVENDA.VALORTOTALITEM` das vendas válidas − Σ `LISTADEVOLUCAOVENDA.VALORTOTALITEM` das devoluções próprias. **Não exclui devoluções canceladas.** |
| Meta Realizada Mussarela | o mesmo, só para os produtos {32, 12175, 11989, 11928, 11988, 12189, 12548, 12552} |
| Meta Realizada Outras Linhas | o mesmo, para todos os outros produtos |
| Bebida Lactea | o mesmo, produtos {11469, 10354, 541, 5416, 5413, 10353, 3790, 3788, 3791, 10352, 4835, 2105} |
| Manteiga | {5754, 27, 26, 25} |
| Queijo Coalho | {9616, 5973} |
| Queijo Parmesão | {24, 4046} |
| Queijo Prato | {21} |
| Requeijão Cremoso | {11098, 9776} |
| Requeijão Bisnaga | {8991} |
| Meta Realizada Clientes | nº de clientes distintos com venda válida no período (qualquer TIPOCLIENTE; devolução não tira cliente) |
| Meta Venda Média Realizada | Faturamento Líquido / Clientes realizados |
| % Meta Faturamento / Mussarela / Outras / Clientes | realizado / soma da meta |
| Meta Restante Outras Linhas | meta outras linhas − realizado outras linhas |
| Parabens | "Parabéns, dentro da meta!" se % Outras Linhas ≥ % Mínimo Meta |
| Volume Liquido (Devoluções Proprias) | Σ `LISTAVENDA.QUANTIDADE` das vendas válidas − Σ `LISTADEVOLUCAOVENDA.QUANTIDADE` das devoluções próprias (Metas Produtos BA) |
| Data Atual | hoje − 1 |
| Dias Uteis | **21, fixo** (editado à mão todo mês) |
| Dias Corridos | dias de segunda a sexta do mês selecionado até hoje − 2 (o "−2" desconta hoje e o feriado de 12/10; ajustado à mão) |
| Dias Faltantes | Dias Úteis − Dias Corridos |
| % Minimo Meta | Dias Corridos / Dias Úteis (ritmo esperado) |

---

## 4. As cinco páginas

Todas têm 1280×720, título "Acompanhamento Metas -", cartão com a Data Atual e filtros de Ano e Mês
(salvos em 2026 / outubro). Não há formatação condicional: as cores das linhas são fixas
(metas em azul #00B1F2, realizados em cinza, venda média em amarelo #FFE798). As matrizes mostram
os indicadores nas linhas e os vendedores nas colunas, com coluna de total.

### Metas ES
- Filtro Estado (dMetas[ESTADO]) salvo em **ES**.
- Matriz com 21 linhas: Meta Faturamento, Faturamento Realizado, % Fat; Meta Mussarela, Realizado, %;
  Meta Outras Linhas, Realizado, %; Bebida Láctea, Manteiga, Queijo Coalho, Queijo Parmesão,
  Queijo Prato, Requeijão Cremoso, Requeijão Bisnaga; Meta Venda Média, Venda Média Realizada;
  Meta Clientes, Clientes Realizados, % Clientes.
- Exclui na matriz: EDIR, EWERTON, THAIS, GESSIMAR.
- Quadro "Dias úteis": Dias Úteis, Dias Corridos, Dias Faltantes, % Mínimo Meta.

### Metas BA
- Estado salvo em **BA**.
- Matriz com 8 linhas: Meta Faturamento, Realizado, %; Meta Venda Média, Realizada;
  Meta Clientes, Realizados, %.
- Exclui: GESSIMAR, LORENA, EDIR. Quadro "Dias úteis".

### Metas Edir
- Igual à Metas BA, mas só com o vendedor **EDIR** (ID 85, "EDIR - PS"). Estado salvo em BA.

### Metas Outras Linhas ES
- Filtro de vendedor (dMetas[VENDEDOR]) limitado a 15 nomes do ES, sem seleção salva. Sem filtro de Estado.
- Matriz principal (exclui os 10 nomes do BA): Meta Outras Linhas, Realizado, %, Meta Restante,
  Bebida Láctea, Manteiga, Queijo Coalho, Queijo Parmesão, Queijo Prato, Requeijão Cremoso, Requeijão Bisnaga.
- Segunda matriz (11 vendedores do ES): "Falta Outras Linhas" e "Dentro da meta?".
- Quadro "Dias úteis".

### Metas Produtos BA
- Filtro de vendedor (dVendedores[NOME]) limitado aos 10 do BA: EDIR - PS, EWERTON - PS,
  FRANQUELINR13 - ITABELA, JAMILLE - PS, MAURICIA - ITM, MICHELE - PS, RICARDO - EU,
  THAIS - CENTRAL, THIAGO TX, VICENTE - PS.
- Matriz: linhas = produto, colunas = vendedor, valores = Meta (Σ META VOLUME) e Realizado
  (Volume Líquido com devoluções próprias). Sem quadro de dias úteis.

---

## 5. Banco de dados

- Firebird **2.1** (serviço *Firebird Server - DefaultInstance* rodando), arquivo de 7 GB, 647 tabelas.
- O DSN `BDMAISVIDA` aponta para `127.0.0.1/3050:...\LATICINIOMAISVIDALTDA.GDB` (usuário SYSDBA).
- Python 3.11 já tem `fdb` 2.0.4, `pandas` 3.0.5, `duckdb` 1.5.5 e `streamlit` 1.64. **Não tem `openpyxl`** nem `pyodbc`.
- O projeto `Documents\Painel Comercial ES` já resolve a conexão com o Firebird 2.1
  (`fb.py`: shim para o fbclient 2.1, charset NONE decodificado em cp1252, transação somente leitura),
  a leitura da `METAS.xlsx` sem openpyxl (`metas.py`) e o calendário de dias úteis com feriados (`calendario.py`). Dá para reaproveitar.

| Tabela | Linhas | Observação |
|---|---|---|
| VENDAS | 391.168 | 168 colunas; 449 canceladas em 2026 (CANCELADA=1 ⇔ DATACANCELAMENTO preenchida, consistente) |
| LISTAVENDA | 2.201.498 | tem CFOP por item |
| DEVOLUCOESVENDA | 12.122 | DATA e ENTRADA diferem em 625 das 988 devoluções de 2026 |
| LISTADEVOLUCAOVENDA | 52.382 | |
| VENDEDORES | 111 | ESTADO incompleto; ID_SUPERVISOR: 3 = ES (Valdirene), 7 = BA (Marcos Vinicius), 8 = Terceiros (EDIR 85) |
| PRODUTOS | 12.769 | ID_LINHA → LINHASPRODUCAO (61 linhas) |
| CLIENTES | 11.029 | |

---

## 6. Planilhas de metas

### METAS.xlsx (aba Planilha2, tabela Tabela1, A1:H480)
- 479 linhas, de nov/2024 a out/2026, 18 a 22 vendedores por mês. Coluna DATA = dia 1 do mês.
- Desde jan/2026 os vendedores do BA têm META MUSSARELA = META OUTRAS LINHAS = 0 (só faturamento e clientes);
  os do ES têm a divisão (ex.: out/2026 = 30% mussarela, 70% outras).
- Algumas células são fórmulas (ex.: `META FATURAMENTO * 0,65`).
- O mesmo ID com dois nomes: 143 = "RICARDO +" e "ROBSON - EU"; 151 = "JOSE CARLOS" e "JOSE CARLOS (WALDREY)".
- Outubro/2026: BA = 85 EDIR, 111 EWERTON, 113 FRANQUELIN, 98 JAMILLE, 147 MAURICIA, 115 MICHELE,
  150 RICARDO - EU, 141 THAIS, 152 THIAGO, 145 VICENTE; ES = 119 ANTONIO, 153 ISAQUE, 156 JAIZA,
  151 JOSE CARLOS, 140 LORENA, 126 RICARDO, 134 ROGERIO, 124 RUBENS, 149 SAMIRA, 154 TATIANA, 157 WALDREY.

### METAS PRODUTOS.xlsx (aba Planilha1, tabela Tabela3, A1:F2821)
- 2.820 linhas, jan/2026 a out/2026. Janeiro tem 19 vendedores (BA e ES, 28 produtos);
  de fevereiro em diante só os 10 do BA × 26 produtos.
- META VOLUME fracionária (vem da página Sugestão de Meta BA), 301 metas = 0.
- O nome do vendedor muda de formato entre meses; usar o ID.

---

## 7. Divergências encontradas (o PBI calcula assim hoje)

| # | Problema | Impacto medido |
|---|---|---|
| 1 | Produto **12551** (Mussarela Mais Natural Fatiada 4 kg, linha de mussarela) não está na lista de mussarela e cai em **Outras Linhas** | R$ 1,97 mi vendidos em 2026 |
| 2 | Lista de Bebida Láctea tem **541** (enzima Quimosina, insumo) no lugar de **5417** (Bebida Láctea Morango 170 g) | R$ 510 mil de 2026 fora de "Bebida Láctea" (continuam em Outras Linhas) |
| 3 | Devoluções próprias não excluem devoluções canceladas | ~R$ 11 mil em 2026 |
| 4 | Dias Úteis = 21 fixo e Dias Corridos com "−2" ajustado à mão; em meses passados os dias corridos ficam errados | quadro de ritmo e "Dentro da meta?" |
| 5 | Total de "Meta Venda Média" soma as médias dos vendedores | coluna total |
| 6 | Estado do vendedor vem de lista fixa de nomes; vendedor novo do BA cai no ES até alguém editar o DAX | |
| 7 | Imobilizado e CFOPs de outras saídas entram no faturamento (carroceria R$ 12 mil em fev; CFOP 6949 ~R$ 12 mil em jun) | Outras Linhas |
| 8 | 3 vendas com ano absurdo (2201, 7190) | só precisa filtrar o período |
| 9 | O Painel Comercial ES usa regras diferentes (mussarela por linha de produto 1 e 61, exclui CFOP 5551/6551/5949/6949 e linha 27, positivação só de TIPOCLIENTE = CLIENTE, devolução pela DATA) | os dois painéis não vão bater entre si |

---

## 8. Conferência

Os números de outubro/2026 calculados pelo app foram conferidos com os prints das matrizes do Power BI
(Metas ES, BA, Edir e Produtos BA) e bateram. Os valores não ficam no repositório.

---

## 9. Páginas de sugestão de metas (analisadas em 27/10/2026)

Páginas **Sugestão de Meta BA**, **Sugestão de Meta ES** e **Duplicata de Sugestão de Meta BA** (esta mostra as parcelas da
conta em cartões: Crescimento Proposto, Sazonalidade, Fat Mês Atual, Fat Mês Seguinte, Crescimento em Fat). Medidas da
tabela "Medidas Criar Metas":

| Medida | Definição |
|---|---|
| Volume Liquido (Devoluções Proprias) | Σ QUANTIDADE das vendas válidas − Σ QUANTIDADE das devoluções dos motivos {1,2,5,6,7,8,9} (com as canceladas) |
| Variação LY | (vol. do ano passado + 1 mês ÷ Quant Faturamentos Mes Seguinte LY) ÷ (vol. do ano passado ÷ Quant Faturamentos Mês Atual LY) |
| Variação Ano Completo | vol. do ano de hoje até o fim do último mês fechado ÷ mesmo período do ano passado (usa TODAY()) |
| Percentual Crescimento | 1,12 (fixo; o ES tem outra medida igual) |
| Meta Sugerida | vol. ÷ Fat Mês Atual × [Variação LY: ≤0 → 1, >1,2 → 1,2] × Fat Mês Seguinte × [1,12 − Variação Ano Completo + 1, entre 1 e 1,2] |
| Meta Sugerida Faturamento | Meta Sugerida × Preço Medio (Faturamento Liquido ÷ Volume Vendido: vendas − todas as devoluções não canceladas − brindes) |
| Meta Sugerida Por Vendedor Faturamento | BA: SUMX em área × produto; ES: SUMX por produto (só as linhas ≠ 0) |

- Vendedor = `dClientes[NOME VENDEDOR]`, o vendedor da **carteira atual** do cliente; a área é a do cliente.
- BA: os faturamentos vêm da planilha "Quantidades Faturamentos.xlsx" (por área: mês passado, atual, seguinte e os dois do
  ano passado), digitada à mão, ligada só pela área (sem data). Áreas fora dela ficam sem meta. ES: 21, 21, 22 e 23 fixos no DAX.
- A tabela filtra Faturamento Liquido > 0; o cartão soma todas as linhas ≠ 0 (as negativas também).
- A página Duplicata mostra a sazonalidade travada entre 0% e 20% (Variação LY ajustada), mas a meta usa a variação abaixo de 1.
- Em janeiro, Variação Ano Completo fica vazia (ano de hoje sem nenhum mês fechado) e o crescimento proposto vai a +20%.

Conferência com o cache de 27/10/2026: com essas regras e a planilha de faturamentos, os volumes por produto de out/26 do
EDIR batem com a METAS PRODUTOS.xlsx, e o R$ de 8 dos 10 vendedores do BA fica a menos de 1% da META FATURAMENTO (os outros
dois tiveram mudança de carteira). No painel, ver a página Sugestão de Metas no README (as diferenças estão lá).

## 10. Decisões (pendentes na análise; resolvidas no app pela página Configurações)

1. **Fidelidade**: reproduzir o PBI exatamente (com as divergências da seção 7) ou já corrigir.
2. **Regras**: manter as listas de produtos do PBI ou alinhar com o Painel Comercial ES (linhas de produto, CFOPs, tipo de cliente).
3. **Tecnologia**: app Streamlit (já instalado, filtros interativos, roda local) ou página HTML gerada como o Painel Comercial ES.
4. **Estado/escopo do vendedor**: lista em arquivo de configuração ou pelo supervisor do ERP (3 = ES, 7 = BA).
5. **Dias úteis**: calcular sozinho com feriados (nacionais + estaduais de ES e BA) em vez do 21 fixo.

## 11. Páginas de premiação (analisadas em 30/10/2026)

Páginas ocultas **Premiacao Vendedores** e **Premiacao Supervisores**, com filtros de Ano e Mês (salvos em 2026 / outubro).
No painel viraram a página Premiações (`bi/premiacoes.py`), com as diferenças descritas no README.

**Premiacao Vendedores:** matriz com uma linha por `dMetas[VENDEDOR]`, filtrada por Σ META CLIENTE > 0, com Meta Cliente,
Meta Realizada Clientes, % Meta Clientes Realizada e a medida `Premiação`:

| % da meta de clientes | Premiação |
|---|---|
| < 91% | 0 |
| 91% a < 96% | 200 |
| 96% a < 100% | 250 |
| ≥ 100% | 350 |

O total da matriz aplica o mesmo IF ao % do total (não soma os prêmios).

**Premiacao Supervisores:** duas matrizes com os valores nas linhas, "Marcos" e "Ronaldo", filtradas por
`dClientes[NOME VENDEDOR]` (o vendedor da carteira atual do cliente):

- **Marcos:** os 9 vendedores do supervisor 7, sem o Edir.
- **Ronaldo:** os 12 do supervisor 3.

O filtro chega às vendas, às devoluções, aos brindes e aos títulos pelo `ID_CLIENTE`. As medidas ficam na tabela
"Medidas Premiacao Supervisor":

| Medida | Definição |
|---|---|
| Fat Liquido | Σ LISTAVENDA.VALORTOTALITEM das vendas válidas − Devoluções Total (devoluções não canceladas de todos os motivos + brindes não cancelados) |
| Fat Liquido Mix | Fat Liquido sem os produtos {32, 12551, 12552} |
| %Mix | Fat Liquido Mix ÷ Fat Liquido |
| Fat Liquido 6 meses | Fat Liquido de EOMONTH(mês, −8)+1 a EOMONTH(mês, −2): para outubro, março a agosto |
| Valor Inadimplencia Premiação | Σ CONTASRECEBER.TOTAL não cancelado, TIPOCLIENTE = CLIENTE, ORIGEM = VENDA, QUITADO = 0, VENCIMENTO ≤ TODAY() − 30, emitido na mesma janela de 6 meses |
| %Inadimplencia | Valor Inadimplencia ÷ Fat Liquido 6 meses |
| Devolucoes Improprias | Devoluções Total com motivo em {3, 4, 10–16} (o filtro de dMotivoDevolução também pega os brindes pelo ID_MOTIVO) |
| %Devolucoes | Devolucoes Improprias ÷ Faturamento Bruto |
| Positivação | Meta Realizada Clientes (clientes distintos com venda válida) |
| Premiação Supervisor BA/ES | (pontos de receita + mix + inadimplência + positivação + devoluções) × Max Premiacao (5000) |

Os pontos de cada indicador:

| Indicador | Alcance | Pontos |
|---|---|---|
| Receita | Fat Liquido ÷ Meta Fat | < 0,80 → 0; senão 0,25 × MIN(alcance, 1) |
| Mix | %Mix ÷ Meta Mix | < 0,85 → 0; senão 0,15 × MIN(alcance, 1) |
| Inadimplência | 2 − %Inad ÷ Meta Inad | < 1 → 0; senão 0,10 |
| Positivação | Positivação ÷ Meta Positivacao | < 0,80 → 0; senão 0,25 × MIN(alcance, 1) |
| Devoluções | 2 − %Dev ÷ Meta Dev | < 1 → 0; senão 0,25 |

As metas são números fixos no DAX:

| Meta | BA | ES |
|---|---|---|
| Fat | 2.252.568 | 2.075.000 |
| Mix | 0,55 | 0,55 |
| Inadimplência | 0,0042 | 0,005 |
| Positivação | 967 | 983 |
| Devoluções | 0,015 | 0,015 |

Conferido na METAS.xlsx: o faturamento e a positivação do BA são a soma de setembro/26 sem o Edir. O faturamento do ES é a
soma de setembro; a positivação dele (983) fica a 1 da soma sem a Adriana (984).

**Brindes no ERP** (BRINDES + LISTABRINDE, com TIPOCLIENTE e ID_MOTIVO): em outubro/26, ~R$ 5,9 mil na carteira do BA e
~R$ 16,8 mil na do ES, a maior parte "Brinde – vencido" (motivo 16, impróprio). As transferências e o consumo interno não
têm cliente de carteira.

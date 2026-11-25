"""O texto fixo dos dois contratos de avalista (bi/avalista_pdf.py monta o resto: as partes, a data e as assinaturas).

Copiado dos modelos em Word do usuário ("CONTRATO COMERCIAL COM GARANTIA PESSOA JURIDICA" e "... PESSOA FISICA", de
fevereiro de 2026), parágrafo a parágrafo, com os parágrafos em branco no mesmo lugar. O que mudou em relação aos
modelos, combinado com o usuário em 2026-11-25 (só digitação e pontuação; nenhuma regra do contrato):

- Pessoa Jurídica, 4.2: "não será inferior 5 (cinco) dias úteis" ganhou o "a" que faltava;
- Pessoa Jurídica, 1.2: os nomes das empresas são os do começo do contrato (o modelo trazia a garantidora sem "LTDA");
- Pessoa Física, 4.3: o parêntese de "(conforme Art. 406 ... do CTN)" fechava sem abrir;
- Pessoa Física, 15.2: "Comarca de  Itabela -BA" virou "Comarca de Itabela - BA".

Cada parágrafo é (estilo, texto). Estilos: "J" justificado; "T" título de cláusula (justificado, e não fica sozinho no
fim da página); "" no texto = parágrafo em branco. No texto, **negrito**, //itálico// e {campo}.
"""

# Contrato de Garantia Fidejussória (o garantidor é uma empresa): do fecho das partes até o fecho do contrato.
PJ_CLAUSULAS = (
    ("J",
     "As partes acima qualificadas, por seus representantes legais, têm entre si justo e contratado o "
     "presente Contrato de Garantia Fidejussória e Outras Avenças, que se regerá pelas cláusulas e "
     "condições seguintes:"),
    ("J", ""),
    ("J", ""),
    ("T", "**CLÁUSULA PRIMEIRA – DO OBJETO E DEFINIÇÕES**"),
    ("J",
     "1.1. O presente instrumento tem como objeto a prestação de garantia fidejussória pela "
     "**GARANTIDORA** em favor do **FORNECEDOR**, para assegurar o fiel e integral cumprimento das "
     "obrigações de pagamento decorrentes das compras de produtos realizadas pela **COMPRADORA** junto ao "
     "**FORNECEDOR**."),
    ("J",
     "1.2. Para os fins deste contrato, as partes concordam com as seguintes definições: a) "
     "**FORNECEDOR:** A empresa {fornecedor}, responsável pela venda e entrega dos produtos. b) "
     "**COMPRADORA:** A empresa **{compradora}**, responsável pela aquisição dos produtos e pelo "
     "pagamento. c) **GARANTIDORA:** A empresa {garantidora}, que assume a responsabilidade solidária pelo"
     " pagamento das obrigações da **COMPRADORA** junto ao **FORNECEDOR**. d) **Obrigações Garantidas:** "
     "Todas e quaisquer dívidas e encargos decorrentes das compras de produtos efetuadas pela "
     "**COMPRADORA** junto ao **FORNECEDOR**, incluindo, mas não se limitando a principal, juros, multas, "
     "correção monetária, custas processuais e honorários advocatícios."),
    ("J", ""),
    ("T", "**CLÁUSULA SEGUNDA – DAS CONDIÇÕES E TERMOS DAS COMPRAS E PAGAMENTOS**"),
    ("J",
     "2.1. As condições e termos específicos de cada compra (preços, prazos de entrega, quantidades, etc.)"
     " serão estabelecidos em pedidos de compra, notas fiscais, boletos bancários ou outros documentos "
     "comerciais emitidos pelo **FORNECEDOR** e aceitos pela **COMPRADORA**, que farão parte integrante da"
     " relação comercial entre eles."),
    ("J",
     "2.2. Os pagamentos das compras deverão ser efetuados pela **COMPRADORA** nas datas de vencimento "
     "indicadas nos respectivos documentos de cobrança (boletos, faturas, etc.), conforme acordado entre "
     "**FORNECEDOR** e **COMPRADORA**."),
    ("J", ""),
    ("T", "**CLÁUSULA TERCEIRA – DA GARANTIA E RESPONSABILIDADE DA GARANTIDORA**"),
    ("J",
     "3.1. A **GARANTIDORA** constitui-se, por este instrumento, fiadora e principal pagadora, em caráter "
     "solidário, de todas as Obrigações Garantidas assumidas pela **COMPRADORA** perante o **FORNECEDOR**."),
    ("J",
     "3.2. A **GARANTIDORA** renuncia expressamente aos benefícios de ordem, divisão e excussão previstos "
     "nos artigos 827, 828, 829 e 838 do Código Civil Brasileiro, bem como a qualquer outro que possa lhe "
     "ser conferido por lei, podendo o **FORNECEDOR** acioná-la diretamente em caso de inadimplência da "
     "**COMPRADORA**, independentemente de prévia interpelação ou execução desta."),
    ("J",
     "3.3. A responsabilidade da **GARANTIDORA** é solidária e se estende a todas as Obrigações "
     "Garantidas, incluindo principal, juros, multas, correção monetária, custas judiciais e "
     "extrajudiciais, honorários advocatícios e quaisquer outros encargos decorrentes da inadimplência da "
     "**COMPRADORA**."),
    ("J",
     "3.4. A presente garantia terá duração indeterminada, permanecendo válida e eficaz enquanto "
     "perdurarem as Obrigações Garantidas, suas eventuais prorrogações, aditamentos ou renovações, até a "
     "sua integral e final liquidação."),
    ("J",
     "3.5. A **GARANTIDORA** declara ter plena capacidade jurídica para assumir as obrigações decorrentes "
     "deste contrato, e que a prestação desta garantia foi devidamente autorizada por seus órgãos sociais "
     "competentes."),
    ("J", ""),
    ("T", "**CLÁUSULA QUARTA – DOS MECANISMOS DE GARANTIA E EXECUÇÃO**"),
    ("J",
     "4.1. Em caso de inadimplência da **COMPRADORA** em relação a qualquer das Obrigações Garantidas, o "
     "**FORNECEDOR** poderá, a seu exclusivo critério, acionar diretamente a **GARANTIDORA** para o "
     "cumprimento da obrigação, independentemente de prévia interpelação ou execução da **COMPRADORA**."),
    ("J",
     "4.2. Para a execução da garantia, o **FORNECEDOR** deverá notificar a **GARANTIDORA** por escrito, "
     "informando o valor atualizado da dívida, os encargos incidentes e o prazo para pagamento, que não "
     "será inferior a 5 (cinco) dias úteis."),
    ("J",
     "4.3. A notificação de inadimplência deverá ser acompanhada dos documentos comprobatórios da dívida e"
     " da inadimplência da **COMPRADORA**, tais como cópia dos pedidos de compra, notas fiscais, boletos "
     "vencidos, demonstrativos de débito, avisos de cobrança, entre outros."),
    ("J",
     "4.4. O não pagamento pela **GARANTIDORA** no prazo estipulado na notificação de execução da garantia"
     " a sujeitará às mesmas penalidades e encargos previstos para a **COMPRADORA** nas Obrigações "
     "Garantidas, além das medidas judiciais cabíveis para a cobrança."),
    ("J", ""),
    ("J", ""),
    ("T", "**CLÁUSULA QUINTA – DAS OBRIGAÇÕES E COMPROMISSOS DAS PARTES**"),
    ("J",
     "5.1. **Obrigações do FORNECEDOR:** a) Fornecer os produtos à **COMPRADORA** conforme os termos "
     "comerciais acordados. b) Notificar a **GARANTIDORA** por escrito, no prazo máximo de 30 dias úteis, "
     "sobre qualquer inadimplemento da **COMPRADORA** que possa ensejar a execução da garantia. c) "
     "Fornecer à **GARANTIDORA**, mediante solicitação, todas as informações e documentos pertinentes às "
     "Obrigações Garantidas e à inadimplência da **COMPRADORA**. d) Após o cumprimento da garantia pela "
     "**GARANTIDORA**, fornecer a esta todos os documentos comprobatórios do pagamento e, se for o caso, "
     "sub-rogar a **GARANTIDORA** nos direitos e ações contra a **COMPRADORA**."),
    ("J",
     "5.2. **Obrigações da COMPRADORA:** a) Efetuar o pagamento das compras realizadas junto ao "
     "**FORNECEDOR** nos prazos e condições acordados. b) Manter o **FORNECEDOR** e a **GARANTIDORA** "
     "informados sobre qualquer alteração em seus dados cadastrais ou de seus representantes legais. c) "
     "Notificar o **FORNECEDOR** e a **GARANTIDORA**, no prazo máximo de 5 dias úteis, sobre qualquer "
     "evento que possa impactar sua capacidade de pagamento."),
    ("J",
     "5.3. **Obrigações da GARANTIDORA:** a) Cumprir as Obrigações Garantidas, nos termos e condições "
     "estabelecidos neste contrato, caso a **COMPRADORA** não o faça. b) Manter o **FORNECEDOR** e a "
     "**COMPRADORA** informados sobre qualquer alteração em seus dados cadastrais ou de seus "
     "representantes legais. c) Notificar o **FORNECEDOR** e a **COMPRADORA**, no prazo máximo de 5 dias "
     "úteis, sobre qualquer evento que possa impactar sua capacidade de honrar a garantia."),
    ("J", ""),
    ("T", "**CLÁUSULA SEXTA – DAS NOTIFICAÇÕES E COMUNICAÇÕES**"),
    ("J",
     "6.1. Todas as notificações, comunicações e avisos referentes a este contrato deverão ser feitos por "
     "escrito e enviados aos endereços das partes indicados no preâmbulo, ou para outros endereços que "
     "venham a ser formalmente informados por escrito."),
    ("J",
     "6.2. As notificações serão consideradas recebidas na data de sua entrega, se entregues pessoalmente "
     "com protocolo de recebimento, ou na data de confirmação de recebimento, se enviadas por carta "
     "registrada com aviso de recebimento (AR), por e-mail e whatsapp com confirmação de leitura."),
    ("J",
     "6.3. As partes se comprometem a notificar as demais partes, no prazo máximo de 5 dias úteis, sobre "
     "qualquer alteração significativa em suas condições financeiras que possa impactar a capacidade de "
     "cumprimento das obrigações aqui assumidas ou das Obrigações Garantidas."),
    ("J", ""),
    ("J", ""),
    ("T", "**CLÁUSULA SÉTIMA – DA CONFIDENCIALIDADE**"),
    ("J",
     "7.1. As partes comprometem-se a manter sigilo sobre todas as informações comerciais, financeiras, "
     "técnicas ou quaisquer outras que venham a ter acesso em razão deste contrato, bem como sobre os "
     "termos e condições do presente instrumento."),
    ("J",
     "7.2. As informações confidenciais não poderão ser divulgadas a terceiros, salvo se exigido por lei "
     "ou por ordem judicial, ou com o consentimento prévio e por escrito da parte proprietária da "
     "informação."),
    ("T", "**CLÁUSULA OITAVA – DAS ALTERAÇÕES E VIGÊNCIA**"),
    ("J",
     "8.1. O presente contrato somente poderá ser alterado, aditado ou modificado mediante instrumento "
     "escrito, assinado por todos os representantes legais das partes, com as mesmas formalidades exigidas"
     " para a sua celebração."),
    ("J",
     "8.2. Qualquer tolerância ou omissão das partes em exigir o cumprimento de quaisquer das cláusulas e "
     "condições deste contrato não constituirá novação ou renúncia de direitos, podendo a parte "
     "prejudicada exigir o cumprimento a qualquer tempo."),
    ("T", "**CLÁUSULA NONA – DA DOCUMENTAÇÃO E REGISTRO**"),
    ("J",
     "9.1. O presente contrato, após assinado, deverá ser registrado no Cartório de Registro de Títulos e "
     "Documentos da comarca de Itabela – BA, para que produza efeitos perante terceiros."),
    ("J",
     "9.2. As partes se comprometem a fornecer mutuamente toda a documentação societária e de "
     "representação legal que for necessária para a formalização, registro e execução deste contrato."),
    ("T", "**CLÁUSULA DÉCIMA – DA RESCISÃO E EXTINÇÃO DA GARANTIA**"),
    ("J",
     "10.1. O presente contrato de garantia fidejussória será extinto automaticamente com a integral e "
     "final liquidação de todas as Obrigações Garantidas pela **COMPRADORA** ou pela própria "
     "**GARANTIDORA**."),
    ("J",
     "10.2. A garantia também poderá ser extinta por acordo escrito entre todas as partes, ou por decisão "
     "judicial transitada em julgado."),
    ("J",
     "10.3. Em caso de extinção das Obrigações Garantidas por qualquer motivo a garantia prestada pela "
     "**GARANTIDORA** será igualmente extinta, salvo se houver expressa previsão em contrário."),
    ("J", ""),
    ("T", "**CLÁUSULA DÉCIMA PRIMEIRA – DA LEI APLICÁVEL E FORO**"),
    ("J", "11.1. O presente contrato é regido pelas leis da República Federativa do Brasil."),
    ("J",
     "11.2. As partes elegem o foro da Comarca de Itabela - BA para dirimir quaisquer dúvidas ou litígios "
     "decorrentes deste contrato, renunciando a qualquer outro, por mais privilegiado que seja."),
    ("J",
     "E, por estarem assim justas e contratadas, as partes assinam o presente instrumento em 03 vias de "
     "igual teor e forma, na presença das duas testemunhas abaixo, para que produza seus jurídicos e "
     "legais efeitos."),
)

# Contrato de Compra e Venda de Produtos Lácteos (o garantidor é uma pessoa): da cláusula 2 até o fecho.
PF_CLAUSULAS = (
    ("T", "**2. DO OBJETO DO CONTRATO**"),
    ("J",
     "**2.1.** O presente contrato tem por objeto a compra e venda contínua de produtos lácteos, conforme "
     "especificações, tipos, quantidades e demais características a serem detalhadas em ordens de compra "
     "específicas ou em Anexo I (Lista de Produtos), que farão parte integrante e indissociável deste "
     "instrumento, por prazo indeterminado, nas condições estabelecidas nas cláusulas seguintes."),
    ("J",
     "**2.2.** Os produtos lácteos objeto deste contrato deverão atender rigorosamente às normas técnicas "
     "e sanitárias vigentes no Brasil, em especial as estabelecidas pela Agência Nacional de Vigilância "
     "Sanitária (ANVISA) e pelo Ministério da Agricultura, Pecuária e Abastecimento (MAPA), bem como às "
     "especificações de qualidade e embalagem acordadas entre as partes."),
    ("T", "**3. DAS CONDIÇÕES DE FORNECIMENTO E ENTREGA**"),
    ("J",
     "**3.1.** A COMPRADORA emitirá ordens de compra (pedidos) ao FORNECEDOR, contendo a descrição dos "
     "produtos, quantidades, prazos e locais de entrega. O FORNECEDOR deverá confirmar o recebimento e a "
     "aceitação do pedido."),
    ("J",
     "**3.2.** A entrega dos produtos será realizada no endereço indicado pela COMPRADORA na respectiva "
     "ordem de compra, sendo o frete e o seguro de responsabilidade do Fornecedor."),
    ("J",
     "**3.3.** O FORNECEDOR se compromete a entregar os produtos em perfeitas condições de uso, "
     "acondicionamento e higiene, dentro dos prazos acordados, acompanhados da documentação fiscal e "
     "sanitária exigida por lei."),
    ("J",
     "**3.4.** A responsabilidade pela guarda e conservação dos produtos (risco) será do FORNECEDOR até o "
     "momento da efetiva entrega e aceite pela COMPRADORA no local de destino."),
    ("T", "**4. DO PREÇO E DAS CONDIÇÕES DE PAGAMENTO**"),
    ("J",
     "**4.1.** O preço dos produtos será estabelecido em cada negociação, podendo ser reajustado a "
     "qualquer tempo."),
    ("J",
     "**4.2.** O pagamento será realizado pela COMPRADORA ao FORNECEDOR no prazo negociado no momento do "
     "pedido."),
    ("J",
     "**4.3.** Em caso de atraso no pagamento, a COMPRADORA incorrerá em multa de 2% sobre o valor devido,"
     " acrescido de juros de mora de 1% ao mês (conforme Art. 406 do Código Civil c/c Art. 161, §1º do "
     "CTN), calculados //pro rata die//, sem prejuízo da atualização monetária pelo IGPM."),
    ("T", "**5. DA QUALIDADE E ACEITAÇÃO DOS PRODUTOS**"),
    ("J",
     "**5.1.** A COMPRADORA fará o recebimento dos produtos e realizará a inspeção e verificação de sua "
     "conformidade com as especificações e a ordem de compra."),
    ("J",
     "**5.2.** Constatada qualquer não conformidade, vício ou defeito nos produtos (aparentes ou de fácil "
     "constatação), a COMPRADORA deverá notificar o FORNECEDOR, para que este providencie a substituição "
     "ou o recolhimento dos produtos defeituosos."),
    ("J",
     "**5.3.** Os vícios ocultos ou de difícil constatação que tornem os produtos impróprios ou lhes "
     "diminuam o valor, serão reclamados pela COMPRADORA no prazo legal, a contar da data em que forem "
     "detectados, nos termos do Código Civil."),
    ("J",
     "**5.4.** A recusa de recebimento ou devolução de produtos não conformes não exime a COMPRADORA do "
     "pagamento dos produtos aceitos e em conformidade."),
    ("T", "**6. DAS OBRIGAÇÕES DO FORNECEDOR**"),
    ("J",
     "**6.1.** Fornecer à COMPRADORA os produtos lácteos de acordo com as especificações acordadas, em "
     "conformidade com as normas sanitárias, técnicas e legais aplicáveis, e com os padrões de qualidade "
     "exigidos pela COMPRADORA."),
    ("J",
     "**6.2.** Entregar os produtos no prazo e local acordados, em embalagens adequadas que garantam a "
     "integridade e a qualidade dos produtos até o destino final."),
    ("J",
     "**6.3.** Manter toda a documentação fiscal, sanitária e licenças de operação em dia, apresentando-as"
     " à COMPRADORA sempre que solicitado."),
    ("J",
     "**6.4.** Arcar com todos os custos e despesas inerentes ao fornecimento, incluindo, mas não se "
     "limitando a, produção, embalagem, transporte, seguro e impostos, salvo disposição expressa em "
     "contrário."),
    ("T", "**7. DAS OBRIGAÇÕES DA COMPRADORA**"),
    ("J",
     "**7.1.** Pagar ao FORNECEDOR o preço acordado pelos produtos entregues e aceitos, no prazo e forma "
     "estabelecidos neste contrato."),
    ("J",
     "**7.2.** Receber os produtos e verificar sua conformidade com o pedido e as especificações, nos "
     "termos da Cláusula 5."),
    ("J",
     "**7.3.** Fornecer ao FORNECEDOR as informações necessárias para o cumprimento das obrigações "
     "contratuais, como endereços de entrega e detalhes de contato."),
    ("T", "**8. DA GARANTIA**"),
    ("J",
     "**8.1.** A GARANTIDORA, qualificada no item 1.3 deste instrumento, assume, neste ato, a condição de "
     "fiadora e principal pagadora da COMPRADORA perante o FORNECEDOR, garantindo solidariamente o "
     "cumprimento de todas as obrigações financeiras e contratuais assumidas pela COMPRADORA, incluindo, "
     "mas não se limitando a valores devidos pelos produtos, multas, juros, custas processuais e "
     "honorários advocatícios."),
    ("J",
     "**8.2.** A GARANTIDORA renuncia expressamente ao benefício de ordem previsto nos artigos 827 e 828 "
     "do Código Civil Brasileiro, bem como aos benefícios de excussão, divisão e quaisquer outros que "
     "possam implicar em sua desobrigação ou limitação de responsabilidade, respondendo com a totalidade "
     "de seus bens presentes e futuros pela dívida, até a efetiva e integral liquidação de todas as "
     "obrigações da COMPRADORA."),
    ("J",
     "**8.3.** A presente fiança vigorará por todo o período de duração deste contrato, incluindo "
     "eventuais prorrogações, aditamentos ou renovações, até a completa quitação de todas as obrigações da"
     " COMPRADORA."),
    ("J",
     "**8.4.** A GARANTIDORA declara, sob as penas da lei, que possui plena capacidade civil e patrimonial"
     " para assumir a presente fiança, e que a mesma não compromete sua subsistência ou a de sua família."),
    ("J",
     "**8.5.** Em caso de inadimplemento das obrigações financeiras garantidas por este instrumento, e "
     "após as devidas notificações e tentativas de cobrança amigável, o FORNECEDOR fica autorizado a "
     "solicitar a inclusão do nome da GARANTIDORA nos cadastros de proteção ao crédito, tais como SERASA e"
     " SPC, sem prejuízo das demais medidas legais cabíveis para a recuperação do crédito."),
    ("T", "**9. DA VIGÊNCIA E RESCISÃO**"),
    ("J",
     "**9.1.** O presente contrato entra em vigor na data de sua assinatura e vigerá por prazo "
     "indeterminado."),
    ("J",
     "**9.2.** Qualquer das partes poderá rescindir o presente contrato, a qualquer tempo e sem "
     "necessidade de justificativa, mediante comunicação escrita à outra parte com antecedência mínima de "
     "30 (trinta) dias."),
    ("J",
     "**9.3.** O presente contrato poderá ser rescindido de pleno direito, independentemente de aviso ou "
     "notificação judicial ou extrajudicial, nas seguintes hipóteses: a) Pelo descumprimento de qualquer "
     "cláusula ou condição do presente contrato por uma das partes, não sanado no prazo de 10 dias após "
     "notificação escrita da parte prejudicada; b) Pela decretação de falência, recuperação judicial ou "
     "extrajudicial de qualquer das partes; c) Pela insolvência ou liquidação de qualquer das partes; d) "
     "Pela ocorrência de caso fortuito ou força maior que impossibilite o cumprimento das obrigações por "
     "período superior a 10 dias."),
    ("J",
     '**9.4.** Em caso de rescisão por descumprimento contratual (item 9.3 "a"), a parte inadimplente '
     "pagará à parte inocente multa compensatória equivalente a 10% do valor total estimado das compras "
     "dos últimos 12 meses, sem prejuízo da apuração de perdas e danos e da cobrança de quaisquer débitos "
     "pendentes."),
    ("J",
     "**9.5.** Em qualquer hipótese de rescisão, a COMPRADORA deverá liquidar todos os débitos pendentes "
     "junto ao FORNECEDOR referentes aos produtos já entregues e aceitos, e o FORNECEDOR deverá entregar "
     "quaisquer produtos já pagos e não entregues."),
    ("J", ""),
    ("T", "**10. DO CASO FORTUITO OU FORÇA MAIOR**"),
    ("J",
     "**10.1.** Nenhuma das partes será responsável por atrasos ou falhas no cumprimento de suas "
     "obrigações decorrentes de caso fortuito ou força maior, nos termos do Art. 393 do Código Civil "
     "Brasileiro, tais como, mas não se limitando a guerras, revoluções, greves gerais, catástrofes "
     "naturais, pandemias, atos de autoridades governamentais que impeçam o cumprimento do contrato."),
    ("J",
     "**10.2.** A parte afetada deverá notificar a outra imediatamente sobre a ocorrência e a cessação do "
     "evento, bem como sobre os impactos previstos no cumprimento do contrato."),
    ("T", "**11. DA CONFIDENCIALIDADE**"),
    ("J",
     "**11.1.** As partes comprometem-se a manter sigilo e confidencialidade sobre todas as informações "
     "comerciais, técnicas, financeiras e estratégicas da outra parte, obtidas em razão da execução deste "
     "contrato, não as divulgando a terceiros, nem as utilizando para fins diversos dos previstos neste "
     "instrumento, mesmo após o término da relação contratual."),
    ("T", "**12. DA CESSÃO E SUCESSÃO**"),
    ("J",
     "**12.1.** Nenhuma das partes poderá ceder ou transferir, total ou parcialmente, os direitos e "
     "obrigações decorrentes deste contrato sem o prévio e expresso consentimento por escrito da outra "
     "parte."),
    ("J", "**12.2.** O presente contrato obriga as partes, seus herdeiros e sucessores a qualquer título."),
    ("T", "**13. DA TOLERÂNCIA**"),
    ("J",
     "**13.1.** A tolerância ou o não exercício, por qualquer das partes, de quaisquer direitos ou "
     "faculdades que lhes são assegurados por este contrato ou pela lei, não importará em renúncia a esses"
     " direitos ou faculdades, nem alteração das cláusulas aqui estabelecidas, podendo a parte exercê-los "
     "a qualquer tempo."),
    ("T", "**14. DAS DISPOSIÇÕES GERAIS**"),
    ("J",
     "**14.1.** Este contrato constitui o acordo integral entre as partes, substituindo quaisquer "
     "entendimentos ou acordos anteriores, verbais ou escritos, referentes ao objeto aqui tratado."),
    ("J",
     "**14.2.** Qualquer alteração ou aditamento ao presente contrato somente será válido se realizado por"
     " escrito e assinado por representantes legais de ambas as partes."),
    ("J",
     "**14.3.** A nulidade ou invalidade de qualquer cláusula ou condição deste contrato não afetará a "
     "validade e eficácia das demais disposições, que permanecerão em pleno vigor."),
    ("J",
     "**14.4.** As notificações e comunicações entre as partes deverão ser feitas por escrito, com "
     "comprovante de recebimento, para os endereços indicados no preâmbulo deste contrato ou para outros "
     "endereços que venham a ser informados por escrito."),
    ("T", "**15. DA LEGISLAÇÃO APLICÁVEL E DO FORO**"),
    ("J",
     "**15.1.** O presente contrato é regido e interpretado de acordo com as leis da República Federativa "
     "do Brasil."),
    ("J",
     "**15.2.** Fica eleito o Foro da Comarca de Itabela - BA, para dirimir quaisquer dúvidas ou litígios "
     "oriundos do presente contrato, com expressa renúncia a qualquer outro, por mais privilegiado que "
     "seja."),
    ("J",
     "E, por estarem assim justas e contratadas, as partes assinam o presente instrumento em 3 (três) vias"
     " de igual teor e forma, na presença das duas testemunhas abaixo, para que produza seus jurídicos e "
     "legais efeitos."),
)

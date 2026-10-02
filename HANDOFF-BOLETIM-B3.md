# HANDOFF - Agente do Boletim Diario do Mercado (B3)

Atualizado em 01/10/2026, na sessao do notebook (internet aberta). Codigo na `main` do
repositorio douglora/broadcast (desenvolvido no branch `claude/magical-hopper-18a6sh`). Substitui o handoff
anterior, escrito pela sessao na nuvem, que nao alcancava a B3.

Ultimas mudancas (01/10/2026, a tarde): (1) a renda fixa passou a comparar debentures pela taxa
indicativa da ANBIMA, com a taxa dos negocios da B3 ao lado (secao 2.1); (2) em papel de DI, quem diz
se a taxa e premio sobre o CDI ou percentual do CDI passou a ser o cadastro, e papel em estresse deixou
de ser lido como percentual do CDI (secao 2.2; esta espera o ok do Douglas para ir a `main`). O que
falta conferir e o que depende dele ficam na secao 4.

## 1. O pedido do Douglas

1. Um agente com laco diario, logo apos a B3 publicar o Boletim Diario do Mercado, que
   abre o site e baixa o arquivo.
2. Se precisar de acesso, pedir. Depois de validar, colocar em producao.
3. Tirar insights das movimentacoes, triangular com os ativos monitorados
   (config/livro.yaml) e dizer o que mais de valioso sai dos boletins.
4. (30/09, segundo pedido) Trazer tudo que importa, todo dia, num artefato limpo: renda
   variavel inteira, opcoes em profundidade, derivativos e, na renda fixa, so o que ele
   opera (debentures incentivadas, CRI e CRA), em formato que outros agentes consigam ler.

## 2. O que a validacao mostrou (30/09/2026, direto na B3)

- Nada exige cadastro. A pagina do boletim e um iframe de `https://arquivos.b3.com.br/bdi/tabelas`.
- O botao "Boletim completo" entrega `BDI_00_AAAAMMDD.pdf`; "Boletim em subcapitulos"
  entrega 10 cadernos (02, 02-0, 02-1, 02-3, 03-1, 03-3, 03-4, 04-1, 04-2, 04-3).
  O completo de 29/09 tem 51 MB e 1.855 paginas; os cadernos de um pregao somam 122 MB.
  PDF nao serve para o git nem para leitura: o dado esta nas tabelas.
- Rota oficial de situacao: `GET /bdi/download/status?dateRef=AAAA-MM-DD` (situacao, hora
  e link de cada caderno). Substitui a sondagem de 143 URLs do coletor antigo.
- Tabelas: `POST /bdi/table/<Nome>/<data>/<data>/<pagina>/<linhas>` com corpo `{}`,
  ate 1000 linhas por pagina. Sao 69 tabelas (`GET /bdi/table/classifications`); 67
  respondem (as duas de negocio a negocio de bolsa dao 500). Cada resposta traz a situacao
  (aguardando, publicando, atrasado, publicado, republicado) e a hora. Tabela nao
  publicada volta vazia, nunca com o dado de D-1. `?filter=<base64 do codigo>` devolve so
  as linhas daquele codigo (casamento exato na coluna-chave); filtro por coluna no corpo
  da 500.
- A PAGINACAO NAO E CONFIAVEL: em 30/09 a tabela `Trade` lida pagina a pagina trouxe 33.681
  linhas com so 23.129 negocios unicos (repete e pula linhas; um negocio de R$ 1,1 bi ficou de
  fora). Tabela de mais de uma pagina vem por `POST /bdi/table/export` (corpo com Name, Date,
  FinalDate, ClientId e Filters), que devolve tudo numa resposta: 92 mil linhas em 5 segundos.
- O negocio a negocio de renda fixa do proprio pregao e preliminar: a B3 ajusta em D+1 (o de
  29/09 fechou as 11h57 de 30/09).
- A rede falha de vez em quando (na carga de 21 pregoes feita do notebook, 4 pregoes perderam uma
  tabela por erro de conexao). Cada requisicao repete em falha passageira (rede, 429, 5xx) e a
  rodada `auto` refaz, ate 5 por vez, os pregoes da janela que ficaram sem resumo ou com falha de
  rede (`refeitos` no manifest). HTTP 400 no arquivo de posicoes em aberto e so "ainda nao saiu".
- "Acoes: medias diarias" (R$ 37 bi em 30/09) e o mercado de acoes inteiro (a vista, opcoes e
  termo), nao so o a vista (R$ 32,8 bi).
- API de download: so 5 nomes respondem (TradeInformationConsolidated, ...AfterHours,
  InstrumentsConsolidated, DerivativesOpenPosition, MarginScenarioLiquidAssets).
- Horario (medido em 11 pregoes): arquivo de negocios "Final" por volta das 20h; fluxo,
  IOPV e resumos ate 21h; carteira de indice e maiores altas 23h30; aluguel entre 01h e
  09h do dia seguinte; quadro de posicoes em aberto 08h05; aluguel negocio a negocio
  21h do pregao em diante. Por isso duas rodadas (21h40 e 08h35), cada uma refazendo os
  2 ultimos pregoes.
- A B3 guarda 21 pregoes nas tabelas (limite D-21): da para carregar o historico de uma vez.
- O quadro de posicoes em aberto vem marcado "atrasado" todo dia, mas com dado: vale.
  Em 14/09 a carteira de indice veio vazia: o runner usa a do ultimo pregao em que veio.
- NAO existe no boletim: posicao em aberto de derivativos por tipo de investidor.
- O fluxo por tipo de investidor e acumulado no mes e sai com dois pregoes de atraso.
- A taxa de aluguel vem como fracao (0,1287 = 12,87% ao ano), conferido contra o CSV.
- Renda fixa: `Trade` traz cada negocio de debenture, CRI e CRA com a taxa (cerca de 30
  mil negocios e 1.650 papeis por dia); `InstrumentRegistration` (cadastro) diz se e
  incentivada, o indexador, a taxa de emissao e o vencimento, mas tem 278 mil linhas: e
  consultado papel a papel pelo filtro e guardado em `rf_cadastro.json`.
- Aluguel negocio a negocio (`BTBTrade`): de 38 mil a mais de 90 mil emprestimos por dia,
  com corretora doadora e tomadora.

### 2.1 Taxa de debenture: a media dos negocios da B3 engana, a indicativa da ANBIMA nao (01/10/2026)

O problema. O bloco de renda fixa comparava debentures pela taxa media dos negocios de balcao da B3
(`Trade`), ponderada pelo volume. Em papel com muito negocio pequeno essa media pende para a taxa
do varejo, que compra a taxa menor. Medido: na media de 5 pregoes da B3, EQPA18 (Equatorial Para,
2036) saia a IPCA+7,70% e CGOS16 (Equatorial Goias, 2036) a 8,16%, 46 pontos-base de diferenca;
pela indicativa da ANBIMA de 30/09 as duas estavam em 8,16% e 8,19%. No pregao de 30/09, entre 129
incentivadas com as duas taxas, uma em cada cinco teve a media dos negocios a 17 pb ou mais da
indicativa (de -100 a +113 pb). Na edicao da manha de 01/10 (pregao de 30/09) a lista "quem abriu
e quem fechou taxa" pela B3 trazia SUMI17 com +102 pb (indicativa: +43), ETEN12 com +63
(indicativa: +1) e CEED19 com +44 (indicativa: +14), e tres debentures "fechando" de 29 a 38 pb
(EGIE27, RUMOA6, CEPEA6) que, pela indicativa, abriram de 1 a 6 pb.

A fonte. Arquivo diario do mercado secundario de debentures da ANBIMA, sem cadastro:
`https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/dbAAMMDD.txt`.

- Texto em latin-1, campos separados por `@`, virgula decimal, `--` e `N/D` onde nao ha taxa ou
  preco. Colunas: Codigo, Nome, Repac./Venc., Indice/Correcao, Taxa de Compra, Taxa de Venda, Taxa
  Indicativa, Desvio Padrao, Intervalo Indicativo Minimo e Maximo, PU, % PU Par / % VNE, Duration
  (dias uteis), % Reune, Referencia NTN-B. A data nao vem dentro do arquivo: e a do nome.
- 1.291 debentures em 30/09 (661 em IPCA, 602 em DI + taxa, 22 prefixadas, 5 em % do DI, 1 em
  IGP-M); 65 delas sem taxa (`--`). So debentures: CRI e CRA nao tem indicativa neste arquivo.
- Hora de publicacao (Last-Modified dos 13 arquivos no servidor): de 19h42 a 20h26 de Brasilia
  (o de 15/09 foi regravado na noite seguinte). A rodada das 21h40 costuma ja encontrar o
  arquivo do pregao.
- Arquivo que nao existe responde HTTP 404 com pagina HTML: e "ainda nao publicado", nao erro.
  A pagina da ANBIMA diz que ficam os ultimos 5 dias uteis; o servidor tinha 13 (14/09 a 30/09) e
  ja dava 404 em 10/09 e 11/09. Historico longo nao se refaz.
- A convencao do indice bateu com o cadastro da B3 nos 1.202 papeis presentes nos dois. Em 14
  papeis a data de Repac./Venc. nao e o vencimento do cadastro; em 12 deles vem antes (repactuacao
  ou resgate): a taxa da ANBIMA vale ate essa data, mais um motivo para medir o premio na duration.
- 11 papeis em IPCA tinham duration abaixo de um ano com vencimento a mais de um ano (amortizam
  cedo). O DAP de menos de um ano carrega a inflacao dos proximos meses e nao serve de referencia:
  esses papeis ficam sem premio, em vez de ganhar o do vencimento.
- A indicativa em IPCA+ anda pouco de um dia para o outro: em 7.564 variacoes diarias de 14/09 a
  30/09, 90% ficaram em ate 13 pb em modulo e 1% passou de +30 pb. O limiar do sinal de
  abertura (30 pb) ficou o mesmo para as duas fontes. Em papel de percentual do CDI a variacao
  nao e medida: a diferenca entre dois percentuais nao e ponto-base de taxa.

O que mudou no resumo (`renda_fixa`, formato na skill `boletim-b3`):

- cada debenture guarda `anbima` (indicativa, compra, venda, PU, % do par, duration, com a data do
  arquivo) e `ref`, a taxa que vale para comparar: a indicativa quando ha, a dos negocios quando nao
  ha. A taxa dos negocios continua em `taxa_media`, e as telas a chamam de "B3 negocios de DD/MM";
- premio sobre o DAP medido tambem na duration (`premio_base: duration`), contra o DAP da mesma
  data da taxa; duration abaixo de um ano fica sem premio, e so quando a ANBIMA nao da a duration
  vale o vencimento. CRI e CRA seguem por vencimento;
- curva de credito, medianas por classe, premios altos, emissores e quem abriu e fechou taxa saem
  de `ref`. A variacao pela indicativa e de um arquivo da ANBIMA para o seguinte; abaixo de 1 pb
  o papel ficou parado;
- papel acompanhado aparece pela indicativa mesmo sem negocio no dia e da sinal de abertura com
  qualquer giro;
- arquivo do pregao ainda nao publicado, ou que nao pode ser lido: vale o mais recente (ate 3 dias
  uteis antes), com a data dele na tela, o premio contra o DAP daquela data e a variacao do dia
  declarada como lacuna, com o motivo;
- ANBIMA fora do ar, com formato novo ou com dado que quebre o cruzamento: tudo volta para os
  negocios da B3 e a lacuna fica escrita. Dois arquivos sem resposta da rede e a rodada para de
  procurar a ANBIMA (a rodada seguinte tenta de novo). A falha fica em `index.json > anbima`, fora de `falhas`, para nao mandar a rodada
  refazer a coleta da B3 de pregao antigo.

### 2.2 Papel em DI: premio sobre o CDI ou percentual do CDI (01/10/2026)

O problema. A taxa do negocio de balcao vem na convencao do papel, e em DI ha duas: premio sobre o CDI
(DI + taxa) e percentual do CDI. `renda_fixa.convencao()` decidia so pela grandeza da taxa: acima de 30,
percentual do CDI. O corte nasceu por causa de CRI e CRA a 98% ou 105% do CDI, e errava nas duas pontas:

- Papel em DI + taxa que negocia em estresse sai acima de 30. BRKMA6 (Braskem, DI + 1,75%) fez 14 negocios
  e R$ 15,0 mi a 54,33 em 30/09, e a taxa era lida como "54,3% do CDI". E CDI + 54,33%: o PU estava a 44%
  do par (arquivo da ANBIMA) e, no mesmo mes, o papel saiu a 115 com o PU a 265 e a 54 com o PU a 470
  (taxa maior, preco menor). O corte ainda fazia o mesmo papel trocar de leitura de um dia para o outro:
  CSNAA1 a 29,12 em 30/09 e a 50,06 em 22/09; o CRA022008C2 a 29,30 e a 30,10 com o PU em 410 nos dois dias.
- Negocio fora de preco em papel de percentual do CDI sai abaixo de 30. O CRI 25G5827604 (109% do DI) saiu
  a 1,35 em 28/09 com o PU a 1.453, contra 110 e 113,1 com o PU a 1.001 e a 991 no mesmo dia. E 1,35% do
  CDI de um negocio 46% acima do preco dos outros, e a media do dia (20,42) era lida como "CDI + 20,42%".

Onde o erro aparecia. Debenture nao incentivada nao tem linha propria no painel, no `resumo.md` nem no
`mesa.py boletim rf`: a BRKMA6 errava os totais da classe (`renda_fixa.resumo.deb_comum` e a linha da
classe no `boletim rf`). CRI e CRA tem linha propria, mas as leituras erradas do periodo ficaram todas
abaixo dos volumes minimos das listas e dos sinais.

O que foi medido (bruto real dos 21 pregoes de 01/09 a 30/09/2026: 33.787 linhas de papel por pregao,
12.204 delas em DI, de 1.524 papeis; 13 arquivos da ANBIMA, de 14/09 a 30/09):

- A B3 da a taxa na convencao que o cadastro do papel descreve. Dos 57.681 negocios com taxa em papel de
  DI + taxa (100% do indexador e taxa de emissao maior que zero), 191 sairam acima de 30, todos em 12
  papeis em estresse. Dos 41.517 em papel de percentual do DI (percentual diferente de 100, sem taxa), 8
  sairam ate 30, todos em 3 CRI e todos com o PU de 18% a 46% acima dos outros negocios do mesmo dia.
- 66 leituras erradas (pregao x papel). 65 em papel de DI + taxa, lidas como percentual: 40 em 4 debentures
  nao incentivadas (BRKMA6, BRKMA8, CSNAA1 e AGAU13, R$ 59,0 mi), 24 em 7 CRA (R$ 1,7 mi) e 1 em 1 CRI. E 1
  em papel de percentual, lida como premio (o CRI de 28/09). Nenhuma de CRI ou CRA passou de R$ 0,5 mi no
  dia. Nenhuma debenture incentivada em DI negociou no periodo.
- Prova pelo preco nos 12 papeis de DI + taxa: em 10 a taxa varia muito de um negocio para outro e a
  correlacao entre taxa e PU fica entre -0,90 e -1,00 (preco cai quando a taxa sobe: e premio); 8 deles
  negociaram dos dois lados do corte. Os outros 2 (CRA023002XL e CRA02300EI9, 12 negocios, R$ 28 mil) so
  negociaram numa faixa estreita, acima de 30, e valem pelo cadastro.
- ANBIMA: nas 21 leituras erradas de debenture em pregao com arquivo, ela escreve o indice como "DI +
  taxa". Nas 544 debentures em DI que estao no cadastro lido e nos arquivos, o cadastro sozinho da a mesma
  convencao que ela em todas (541 em DI + taxa, 3 em percentual do DI).
- Cadastro que nao decide: 25 papeis (21 a 100% do indexador sem taxa, 3 com percentual de 1 ou de 3, que
  e cadastro torto, e 1 sem percentual). Os 3.796 negocios com taxa desses papeis sairam todos entre 83 e
  149: percentual do CDI, e ali o corte acerta.

A regra nova. O cadastro decide nos dois sentidos. DI + taxa: a taxa do negocio e premio sobre o CDI, por
mais alta que seja. Percentual do DI sem taxa (percentual acima de 30): e percentual do CDI, por mais baixa
que seja. So quando o cadastro nao decide vale o corte de antes (acima de 30, percentual do CDI). A
convencao do arquivo da ANBIMA nao entrou na regra: o cadastro chega ao mesmo resultado, vale tambem para
CRI e CRA (que a ANBIMA nao lista), para debenture fora do arquivo e para pregao sem arquivo, e as duas
fontes continuam se conferindo (quando a ANBIMA e a B3 leem a taxa de jeitos diferentes o papel leva
`anbima.convencao` e as taxas nao se comparam).

O que mudou no resumo (mesmo bruto, codigo de antes contra o de depois, nos 21 pregoes):

- 66 leituras mudaram (65 de `% do CDI` para `CDI+`, 1 no sentido contrario); as outras 33.721 linhas
  ficaram iguais. Das 2.986 leituras de CRI e CRA que eram percentual do CDI, 25 viraram premio (as de DI +
  taxa em estresse) e 2.961 ficaram como estavam. `resumo.md` e `painel.html` sairam identicos nos 21
  pregoes, e nenhuma lista nem sinal mudou;
- `renda_fixa.resumo.deb_comum`: a media de CDI+ subiu em 4 pregoes (30/09: de 1,17% para 1,62%; 24/09: de
  1,34% para 1,56%; 04/09: de 1,23% para 1,45%; 02/09: de 1,10% para 1,39%) e a mediana quase nao mexeu
  (0,99% em 30/09, antes e depois); a fatia `% do CDI` de `por_indexador_pct` caiu (30/09: de 0,8% para
  0,0%). Em CRA so `por_indexador_pct` mexeu, 0,1 ou 0,2 ponto em 5 pregoes;
- a media ponderada pelo volume agora carrega o papel em estresse: `mesa.py boletim rf` passou a mostrar a
  mediana de CDI+ ao lado da media em toda classe, e a skill manda usar a mediana;
- debenture em estresse voltou a falar a lingua da ANBIMA, e quando ha indicativa ela e a referencia
  (CSNAA1 em 7 pregoes: indicativa perto de CDI + 17%, negocios pequenos na B3 de CDI + 38% a CDI + 51%).

O que passa a poder aparecer nas classes em foco (nos 21 pregoes nenhum caso chegou ao volume minimo):

- CRI ou CRA em DI + taxa negociando em estresse com R$ 3 mi ou mais entra em `premios_altos` como `CDI+`
  (antes ficava escondido como percentual do CDI), e da sinal com R$ 5 mi;
- premio sobre o CDI tem variacao em pontos-base (percentual do CDI nao tem), entao esse papel tambem entra
  em quem abriu e quem fechou taxa. Papel em estresse alterna entre a taxa de emissao e a do estresse de um
  dia para o outro (CRA02400CI3: 5,00 em 25/09, 34,02 em 29/09 com R$ 213 mil, 5,00 em 30/09 com R$ 297
  mil): a abertura de um dia e o fechamento do seguinte sao negocios de natureza diferente, nao o mercado
  mudando de ideia;
- CRI ou CRA de percentual do CDI com negocio fora de preco deixa de poder entrar em `premios_altos` como
  se pagasse premio sobre o CDI (a media de 28/09 do 25G5827604 sairia como "CDI + 20,42%").

O que a regra nao resolve. Negocio fora de preco continua dentro da media do dia: o 25G5827604 fechou 29/09
com media de 71,6% do CDI (R$ 276 mil a 1,94% e R$ 489 mil a 110% e a 113,1%). E limite da media dos
negocios, o mesmo do lote pequeno do varejo; `taxa_min` e `taxa_max` do papel mostram a distancia. E tres
cadastros que parecem DI + taxa ficam fora da regra e seguem pelo corte: PLII11 (sem percentual, taxa 2,5)
e os CRI 26E3429212 e 26F2438121 (percentual 1, taxas 3,4 e 4,05). Nenhum negociou com taxa no periodo.

## 3. O que esta no branch

| Arquivo | O que faz |
|---|---|
| `boletim/b3.py` | Rotas da B3: situacao dos cadernos, tabelas (com filtro), catalogo, comunicados, arquivos CSV, cadastro de balcao |
| `boletim/anbima.py` | Arquivo diario de taxas indicativas de debentures da ANBIMA: leitura pelo titulo das colunas, 404 como "ainda nao publicado", o arquivo que vale para o pregao e o anterior a ele |
| `boletim/coleta.py` | O que se busca de cada pregao (47 tabelas, 4 arquivos, cadastro de renda fixa em paralelo, taxas indicativas da ANBIMA) e o que fica gravado |
| `boletim/resumo.py` | `resumo.json`: numeros com fonte e data, cruzados com o livro, opcoes em profundidade, sinais e historico |
| `boletim/mercado.py` | Radar do IBrA (volume e aluguel), opcoes do mercado inteiro, corretoras no aluguel, serie `mercado.json` |
| `boletim/renda_fixa.py` | Debentures incentivadas, CRI e CRA: como ler a taxa de cada papel (em DI, premio sobre o CDI ou percentual do CDI, pelo cadastro), taxa de referencia (indicativa da ANBIMA ou negocios da B3), premio sobre o DAP na duration ou no vencimento, quem abriu e fechou taxa |
| `boletim/render.py` | `resumo.md`: cards de texto com `[[LEITURA_DA_MESA]]` |
| `boletim/painel.py` | `painel.html`: a pagina do Artifact (formato branco e azul, graficos em SVG, sem biblioteca externa) |
| `boletim_b3.py` | Entrada: `--saida --data --dias (numero ou auto) --series --pdf --so-painel`. Um pregao leva cerca de um minuto |
| `config/boletim.yaml` | Grupos do livro, futuros, indices, carteiras, paridades, opcoes extras, renda fixa, radar e limiares |
| `.github/workflows/boletim-b3.yml` | Roda no Actions e grava em `boletim_b3/` no branch `dados`. Cron ligado: 21h40 e 08h35 BRT |
| `mesa.py boletim` | Leitura na sessao: veredito, resumo, ativo, sinais, rf, opcoes, radar, status, tabela, json, painel |
| `.claude/skills/boletim-b3/SKILL.md` | Regras da leitura, procedimento do turno, receita do painel e texto da Routine |
| `tests/test_boletim.py` | 69 testes sem rede (24 deles da ANBIMA e da taxa de referencia, 2 da leitura do papel em DI) |

Saida no branch `dados`: ver o cabecalho de `boletim_b3.py`.

Painel publicado (Artifact, privado do Douglas): https://claude.ai/artifact/LdEMW5YS5WXpqF72qkx3Kc
Primeira edicao em 01/10/2026 as 00h41, pregao de 30/09 (parcial), lida do branch `dados`.

Validado em producao (branch de desenvolvimento, gatilho de push): a rodada 36809747622 carregou os
21 pregoes em 9 minutos no Actions, sem falha (cerca de 25 segundos por pregao; no notebook leva um
minuto e a rede cai mais). As rodadas seguintes, de 2 pregoes, levam um minuto e meio.

## 4. Em producao desde 01/10/2026 (com o ok do Douglas) e o que ainda depende dele

Feito em 01/10/2026, depois de ele escrever "pode levar pra main, ligar o cron e criar a routine":

- **Main e cron.** O codigo esta na main e o agendamento do `boletim-b3.yml` esta ligado: 00h40 UTC
  (21h40 BRT do pregao) e 11h35 UTC (08h35 BRT do dia seguinte), de terca a sabado em UTC. O gatilho
  de push do branch de desenvolvimento saiu; sobram o relogio e o disparo manual
  (`gh workflow run boletim-b3.yml --ref main -f dias=auto`, ou `actions_run_trigger` com `ref: main`).
- **Routine.** Dois turnos por pregao, 21h50 BRT e 08h50 BRT do dia seguinte; nomes, ids e o texto
  do turno estao na secao "Routine" da skill `boletim-b3`. Desde 02/10/2026 (ok do Douglas) o turno
  nao espera o cron: se o dado nao esta no branch `dados` ao acordar, dispara a coleta na hora. O
  cron do GitHub atrasou horas nas duas primeiras rodadas (a das 21h40 de 01/10 rodou as 03h08; a
  das 08h35 de 02/10 nao tinha rodado as 09h00) e fica como reserva.
- **Papeis acompanhados.** `config/boletim.yaml > renda_fixa > papeis` tem CGOS16 e CGOS28
  (Equatorial Goias, vencimento em 2036): ele comprou uma delas para cliente em 01/10 a IPCA+8,40%.
  Falta ele dizer qual das duas e passar o resto da prateleira.

A conferir na primeira rodada do Actions com a ANBIMA (o que foi validado em 01/10 saiu do
notebook; nao da para saber de fora se o site da ANBIMA atende os enderecos do GitHub):

- `python3 mesa.py boletim status` traz a linha `ANBIMA (taxa indicativa de debentures)`. O
  esperado e `publicado, arquivo de <pregao>`. `anterior` de noite e so atraso da ANBIMA; `falhou`
  com HTTP 403 ou falha de rede em rodadas seguidas quer dizer que o Actions nao alcanca o site, e
  ai o boletim segue so com os negocios da B3 (lacuna escrita) ate se achar outro caminho.
- Os resumos de antes de 01/10 continuam no formato antigo (so negocios); o painel, o texto e o
  `mesa.py` leem os dois. Para trazer a indicativa dos pregoes que a ANBIMA ainda guarda, disparo
  manual com `dias` entre 3 e 13.

Ainda depende dele:

3. **Limpar o branch `dados`.** A rodada do coletor antigo (run 36800131287) gravou 195 MB
   de PDF e texto em `boletim_b3/<data>/pdf/`, `arquivos/` e `descoberta/`. O coletor novo
   nao escreve nessas pastas. Apagar e decisao dele; tirar do historico exige reescrever
   o branch.
4. **Resto da prateleira de renda fixa.** Os demais codigos que ele acompanha entram em
   `config/boletim.yaml > renda_fixa > papeis` e ganham linha propria no painel.
5. **Ok para levar a `main` a leitura do papel em DI (secao 2.2).** Em 01/10/2026 as 17h10 a mudanca
   estava so no branch `claude/magical-hopper-18a6sh`, um commit a frente da `main` (que ja tinha a
   ANBIMA, 70ea8088). Ate o ok, o cron e os turnos da Routine seguem decidindo a leitura so pela
   grandeza da taxa. Se `git log origin/main --oneline -3` ja mostrar o commit "Le a taxa de papel em DI
   pela convencao do cadastro", este item esta resolvido.

## 5. Ideias que a validacao abriu (fora do escopo atual)

- `ConsolidatedRecords` (negociacao consolidada de balcao por papel, com preco de
  referencia) e `Repodebenture` (compromissadas por debenture).
- `Renewals`: renovacoes de aluguel (quem esta rolando posicao vendida).
- `MarginScenarios`: cenarios de margem da B3 por ativo (o estresse que a clearing usa).
- Rating e devedor do CRI/CRA nao estao na B3: cruzar com ANBIMA ou com a securitizadora.
- Taxa indicativa de CRI e CRA: o arquivo diario da ANBIMA so traz debentures; CRI e CRA seguem
  pelos negocios da B3, com premio por vencimento (duration exigiria o fluxo de amortizacao).
- Premio contra a NTN-B de referencia que a propria ANBIMA aponta para cada debenture (coluna
  Referencia NTN-B, guardada em `anbima.ntnb_ref`), em vez do DAP.
- Serie da indicativa dos papeis acompanhados (hoje o resumo de cada pregao guarda a do dia; o
  grafico de varios dias pediria um arquivo de apoio).

## 6. Regras da casa que o agente herda

- Nunca "compre/venda" (Resolucao CVM 178): o Claude apresenta, o Douglas recomenda.
- Nenhum numero sem fonte e data; lacuna declarada, nunca placeholder.
- A sessao nunca faz push no branch `dados`; so o Actions grava la.
- Arquivos do repo sem acento (texto de tela leva); commits em portugues, imperativo curto.
- Resposta ao Douglas: "Em uma frase" primeiro, tabelas de ate 4 colunas, sigla explicada.
- Painel no formato branco e azul dele (skill relatorio-branco-azul): claro, sem versao escura.

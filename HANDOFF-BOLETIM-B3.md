# HANDOFF - Agente do Boletim Diario do Mercado (B3)

Atualizado em 01/10/2026, na sessao do notebook (internet aberta). Codigo na `main` do
repositorio douglora/broadcast (desenvolvido no branch `claude/magical-hopper-18a6sh`). Substitui o handoff
anterior, escrito pela sessao na nuvem, que nao alcancava a B3.

Ultima mudanca (01/10/2026, a tarde): a renda fixa passou a comparar debentures pela taxa
indicativa da ANBIMA, com a taxa dos negocios da B3 ao lado. O porque e o que foi medido estao na
secao 2.1; o que falta conferir, na secao 4.

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

## 3. O que esta no branch

| Arquivo | O que faz |
|---|---|
| `boletim/b3.py` | Rotas da B3: situacao dos cadernos, tabelas (com filtro), catalogo, comunicados, arquivos CSV, cadastro de balcao |
| `boletim/anbima.py` | Arquivo diario de taxas indicativas de debentures da ANBIMA: leitura pelo titulo das colunas, 404 como "ainda nao publicado", o arquivo que vale para o pregao e o anterior a ele |
| `boletim/coleta.py` | O que se busca de cada pregao (47 tabelas, 4 arquivos, cadastro de renda fixa em paralelo, taxas indicativas da ANBIMA) e o que fica gravado |
| `boletim/resumo.py` | `resumo.json`: numeros com fonte e data, cruzados com o livro, opcoes em profundidade, sinais e historico |
| `boletim/mercado.py` | Radar do IBrA (volume e aluguel), opcoes do mercado inteiro, corretoras no aluguel, serie `mercado.json` |
| `boletim/renda_fixa.py` | Debentures incentivadas, CRI e CRA: taxa de referencia de cada papel (indicativa da ANBIMA ou negocios da B3), premio sobre o DAP na duration ou no vencimento, quem abriu e fechou taxa |
| `boletim/render.py` | `resumo.md`: cards de texto com `[[LEITURA_DA_MESA]]` |
| `boletim/painel.py` | `painel.html`: a pagina do Artifact (formato branco e azul, graficos em SVG, sem biblioteca externa) |
| `boletim_b3.py` | Entrada: `--saida --data --dias (numero ou auto) --series --pdf --so-painel`. Um pregao leva cerca de um minuto |
| `config/boletim.yaml` | Grupos do livro, futuros, indices, carteiras, paridades, opcoes extras, renda fixa, radar e limiares |
| `.github/workflows/boletim-b3.yml` | Roda no Actions e grava em `boletim_b3/` no branch `dados`. Cron ligado: 21h40 e 08h35 BRT |
| `mesa.py boletim` | Leitura na sessao: veredito, resumo, ativo, sinais, rf, opcoes, radar, status, tabela, json, painel |
| `.claude/skills/boletim-b3/SKILL.md` | Regras da leitura, procedimento do turno, receita do painel e texto da Routine |
| `tests/test_boletim.py` | 67 testes sem rede (24 deles da ANBIMA e da taxa de referencia) |

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
  do turno estao na secao "Routine" da skill `boletim-b3`.
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

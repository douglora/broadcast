# HANDOFF - Agente do Boletim Diario do Mercado (B3)

Atualizado em 01/10/2026, na sessao do notebook (internet aberta). Codigo na `main` do
repositorio douglora/broadcast (desenvolvido no branch `claude/magical-hopper-18a6sh`). Substitui o handoff
anterior, escrito pela sessao na nuvem, que nao alcancava a B3.

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

## 3. O que esta no branch

| Arquivo | O que faz |
|---|---|
| `boletim/b3.py` | Rotas da B3: situacao dos cadernos, tabelas (com filtro), catalogo, comunicados, arquivos CSV, cadastro de balcao |
| `boletim/coleta.py` | O que se busca de cada pregao (47 tabelas, 4 arquivos, cadastro de renda fixa em paralelo) e o que fica gravado |
| `boletim/resumo.py` | `resumo.json`: numeros com fonte e data, cruzados com o livro, opcoes em profundidade, sinais e historico |
| `boletim/mercado.py` | Radar do IBrA (volume e aluguel), opcoes do mercado inteiro, corretoras no aluguel, serie `mercado.json` |
| `boletim/renda_fixa.py` | Debentures incentivadas, CRI e CRA: taxa do dia, premio sobre o DAP, quem abriu e fechou taxa |
| `boletim/render.py` | `resumo.md`: cards de texto com `[[LEITURA_DA_MESA]]` |
| `boletim/painel.py` | `painel.html`: a pagina do Artifact (formato branco e azul, graficos em SVG, sem biblioteca externa) |
| `boletim_b3.py` | Entrada: `--saida --data --dias (numero ou auto) --series --pdf --so-painel`. Um pregao leva cerca de um minuto |
| `config/boletim.yaml` | Grupos do livro, futuros, indices, carteiras, paridades, opcoes extras, renda fixa, radar e limiares |
| `.github/workflows/boletim-b3.yml` | Roda no Actions e grava em `boletim_b3/` no branch `dados`. Cron ligado: 21h40 e 08h35 BRT |
| `mesa.py boletim` | Leitura na sessao: veredito, resumo, ativo, sinais, rf, opcoes, radar, status, tabela, json, painel |
| `.claude/skills/boletim-b3/SKILL.md` | Regras da leitura, procedimento do turno, receita do painel e texto da Routine |
| `tests/test_boletim.py` | 43 testes sem rede |

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
- Duration em vez de vencimento no premio sobre o DAP (exige o fluxo de amortizacao).

## 6. Regras da casa que o agente herda

- Nunca "compre/venda" (Resolucao CVM 178): o Claude apresenta, o Douglas recomenda.
- Nenhum numero sem fonte e data; lacuna declarada, nunca placeholder.
- A sessao nunca faz push no branch `dados`; so o Actions grava la.
- Arquivos do repo sem acento (texto de tela leva); commits em portugues, imperativo curto.
- Resposta ao Douglas: "Em uma frase" primeiro, tabelas de ate 4 colunas, sigla explicada.
- Painel no formato branco e azul dele (skill relatorio-branco-azul): claro, sem versao escura.

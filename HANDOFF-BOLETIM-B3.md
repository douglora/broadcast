# HANDOFF - Agente do Boletim Diario do Mercado (B3)

Data: 01/10/2026. Branch: `claude/magical-hopper-18a6sh` (repositorio douglora/broadcast).
Sessao de origem: https://claude.ai/code/session_01L3GXWkPoY5daQ75tYMkxj2

## 1. O pedido do Douglas

1. Um agente com laco diario, logo apos a B3 publicar o Boletim Diario do Mercado
   (https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/boletim-diario/boletim-diario-do-mercado/),
   que abre o site e baixa o arquivo.
2. Se precisar de acesso, pedir. Depois de validar, colocar em producao.
3. O agente tem de tirar insights das movimentacoes, triangular com os ativos
   monitorados (config/livro.yaml) e dizer o que mais de valioso sai dos boletins.

## 2. O que se descobriu

- A sessao na nuvem NAO alcanca a B3: www.b3.com.br, arquivos.b3.com.br e
  clientes.b3.com.br devolvem 403 no proxy (curl e WebFetch). Ja era previsto no CLAUDE.md.
- O GitHub Actions alcanca: `livro/fontes/b3_di.py` ja baixa todo dia o
  TradeInformationConsolidated do boletim pela API de download da B3.
- No notebook (internet aberta) da para abrir o site direto e validar em minutos.
- Acesso: ate aqui nada exige cadastro. Os cadernos em PDF e a API de download sao
  publicos. A pagina "BDI automatizado" (clientes.b3.com.br/w/novo-boletim-de-mercados-b3-bd/bdi-automatizado)
  pode ser produto com cadastro: so pedir acesso se as rotas publicas falharem.

### Onde mora o arquivo (pela busca na web, a confirmar na validacao)

Cadernos em PDF, um por secao:

    https://arquivos.b3.com.br/bdi/download/bdi/AAAA-MM-DD/BDI_NN[-S]_AAAAMMDD.pdf
    (versao em ingles: ..._AAAAMMDD_en-Us.pdf)

| Arquivo visto | Titulo que a busca mostrou |
|---|---|
| BDI_01_20260526.pdf | Boletim Diario do Mercado, referente a terca 26/05/2026, n. 98 |
| BDI_02_20260410.pdf | Boletim Diario do Mercado, referente a sexta 10/04/2026, n. 68 |
| BDI_02_20250328.pdf | Indicadores e Informativos |
| BDI_02-0_20251217.pdf | Boletim Diario do Mercado |
| BDI_03-1_20260115.pdf | Boletim Diario do Mercado |
| BDI_03-3_20251202.pdf | After Market - Negocios realizados |
| BDI_03-4 | (aparece num exemplo de padrao) |
| BDI_05_20251002.pdf | Clearing |
| BDI_07_20250718.pdf | Derivativos de Balcao - Registro sem contraparte central |

Outras rotas:
- Aplicativo do BDI com as tabelas: https://arquivos.b3.com.br/bdi/ e /bdi/tabelas?lang=pt-BR.
  As tabelas saem de uma API POST em arquivos.b3.com.br/bdi (consulta no caminho da URL,
  corpo `{}`). A rota exata sai do JavaScript do aplicativo: e o que a descoberta guarda.
- API de download (CSV ';'), ja usada no repo:
  `GET https://arquivos.b3.com.br/api/download/requestname?fileName=<Nome>&date=AAAA-MM-DD` -> `{"token": ...}`
  `GET https://arquivos.b3.com.br/api/download/?token=<token>` -> CSV.
- Boletins com mais de 20 dias saem do BDI e vao para o Acervo B3 (PDF).

## 3. O que ja esta no branch

| Arquivo | O que faz |
|---|---|
| `boletim_b3.py` | Coletor. Parte `descoberta`: abre a pagina do boletim, a pesquisa por pregao e o aplicativo do BDI, segue iframes e scripts e guarda rotas, tabelas e trechos do JavaScript. Parte `pdf`: testa BDI_00 a BDI_12 e as secoes -0 a -9 do pregao, grava PDF e texto. Parte `arquivos`: testa 22 nomes na API de download e grava os CSV pequenos (cabecalho e amostra dos grandes). |
| `.github/workflows/boletim-b3.yml` | Roda o coletor no Actions e grava em `boletim_b3/` no branch `dados`. SEM cron (fase de validacao). O push no branch de desenvolvimento dispara a descoberta de 2 pregoes; tambem guarda tudo como artefato da rodada (30 dias). |

Saida no branch `dados`:

    boletim_b3/manifest.json                     o que veio e o que falhou na ultima rodada
    boletim_b3/descoberta/descoberta.json        paginas, iframes, scripts, rotas e trechos do JS
    boletim_b3/descoberta/*.html                 HTML das paginas abertas
    boletim_b3/<AAAA-MM-DD>/index.json           cadernos achados (tamanho, paginas, Last-Modified, titulo) e arquivos
    boletim_b3/<AAAA-MM-DD>/pdf/BDI_*.pdf|.txt   os cadernos e o texto
    boletim_b3/<AAAA-MM-DD>/arquivos/*.csv       arquivos da API de download

Testado na sessao so o caminho de erro (sem rede para a B3): nao quebra, registra a falha.
A primeira rodada real e a do Actions disparada pelo push deste branch, em andamento quando
este handoff foi escrito: https://github.com/douglora/broadcast/actions/runs/36800131287
(o resultado fica em `boletim_b3/` no branch `dados` e no artefato `boletim-b3-36800131287`).

## 4. Proximos passos, em ordem

1. **Validar** (no notebook e mais rapido):
   `pip install -r requirements-livro.txt && python boletim_b3.py --saida /tmp/bdi --dias 2`
   e ler `/tmp/bdi/manifest.json`, `/tmp/bdi/<data>/index.json` e `/tmp/bdi/descoberta/descoberta.json`.
   Ou ler a rodada do Actions: `git fetch origin dados && git show origin/dados:boletim_b3/manifest.json`.
   Conferir: (a) quais cadernos existem e o que tem em cada um; (b) qual e o arquivo
   do botao de download da pagina (boletim completo?); (c) quais nomes da API de
   download respondem; (d) a rota POST das tabelas do BDI.
2. **Enxugar o coletor**: trocar a sondagem de 143 URLs pela lista real de cadernos;
   decidir o que fica no git (texto e JSON sempre; PDF so o caderno principal, ou so
   no artefato da rodada, para nao inchar o branch `dados`).
3. **Horario**: o Last-Modified dos PDFs diz quando a B3 publica. Cron logo depois,
   com uma segunda tentativa (ex.: noite do pregao e 07h00 do dia seguinte), idempotente.
4. **Parser estruturado** -> `boletim_b3/<data>/resumo.json` (numeros com fonte e data).
5. **Triangulacao com o livro** (BR: EQTL3, SAPR4, KLBN4, ALUP4, ITUB4, BBDC4, PETR4,
   VALE3, MELI34, UGPA3, AXIA3, ITSA4, BBAS3, SBSP3, SMAL11, RARA11, DIRR3, MRVE3, CURY3;
   macro: USD/BRL, DI, Brent, minerio).
6. **Leitura na sessao**: comando `python3 mesa.py boletim` e skill `boletim-b3`
   (.claude/skills/boletim-b3/SKILL.md) com as regras da nota; registrar em `mesa.py skills`.
7. **Producao**: levar para a main, ligar o cron, tirar o gatilho de push do branch,
   criar a Routine que dispara um turno na sessao depois do cron (le, confere frescor,
   escreve a leitura). Atualizar CLAUDE.md (secao "Onde estao os dados") e README.

## 5. O que de valioso sai do boletim (hipoteses a confirmar com o dado real)

| Bloco do boletim | Insight | Triangulacao com o livro |
|---|---|---|
| Participacao por tipo de investidor (estrangeiro, institucional, pessoa fisica, bancos) | Saldo do dia e acumulado no mes e no ano; quem comprou a alta ou a queda | Fluxo estrangeiro x Ibovespa x USD/BRL |
| Posicao em aberto de derivativos por tipo de investidor | Estrangeiro comprado/vendido em dolar futuro, DI e indice: o posicionamento por tras do preco | Dolar futuro x USD/BRL; DI x construtoras (CURY3, DIRR3, MRVE3) e utilities (SAPR4, SBSP3, EQTL3, ALUP4) |
| Aluguel de acoes (BTC) | Saldo alugado, taxa e variacao: aposta vendida crescendo ou zerando | Aluguel subindo + preco caindo = pressao vendida; aluguel alto + preco subindo = risco de zeragem |
| Negocios por ativo | Volume e numero de negocios contra a media de 20 pregoes: volume anormal antes do preco | Todos os BR do livro; MELI34 contra MELI x cambio |
| Opcoes | Posicao em aberto por serie e strike: paredes de call e put perto do vencimento | PETR4, VALE3, ITUB4, BBAS3, BBDC4 |
| ETFs da B3 | Volume e cotas em circulacao (criacao e resgate) | RARA11 contra REMX x cambio (premio ou desconto); SMAL11 |
| Indicadores (BDI_02) | Ajustes do DI, cupom cambial, taxas referenciais | Curva do livro e Tesouro (ja no runner) |
| Informativos e avisos | Proventos, data ex, eventos societarios, mudanca de carteira teorica | Evento em ativo do livro vira alerta |
| After market e balcao | Negocios fora do pregao; registro de swaps e termos (demanda de hedge) | Contexto, nao gatilho |

## 6. Regras da casa que o agente herda

- Nunca "compre/venda" (Resolucao CVM 178): o Claude apresenta, o Douglas recomenda.
- Nenhum numero sem fonte e data; lacuna declarada, nunca placeholder.
- A sessao nunca faz push no branch `dados`; so o Actions grava la.
- Arquivos do repo sem acento; commits em portugues, imperativo curto.
- Resposta ao Douglas: "Em uma frase" primeiro, tabelas de ate 4 colunas, sigla explicada.

## 7. Prompt para colar no Claude Code do notebook

    Continue o agente do Boletim Diario do Mercado da B3. Leia HANDOFF-BOLETIM-B3.md no
    branch claude/magical-hopper-18a6sh do douglora/broadcast. Aqui a internet e aberta:
    abra https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/boletim-diario/boletim-diario-do-mercado/,
    descubra qual arquivo o botao de download entrega, rode
    `python boletim_b3.py --saida /tmp/bdi --dias 2` e me mostre o que veio (cadernos,
    arquivos da API, rota das tabelas, hora de publicacao pelo Last-Modified). Depois siga
    a secao 4 do handoff: enxugar o coletor, parser em resumo.json, triangulacao com o
    config/livro.yaml, `mesa.py boletim`, skill boletim-b3 e, validado, producao (main,
    cron e Routine). Me pergunte antes de ligar o cron.

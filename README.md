# BROADCAST — The Invest Post

Terminal de mercado em tempo real, estilo Bloomberg. Cotacoes, noticias,
indicadores macro, curva DI, Tesouro Direto, fatos relevantes da CVM,
spreads de credito privado e ranking de TIR real.

| Arquivo                     | O que e                                                       |
|-----------------------------|---------------------------------------------------------------|
| `index.html`                | O terminal (front-end)                                        |
| `app.py`                    | Servidor local: serve o terminal e os endpoints `/api/*`      |
| `gerar_dados.py`            | Gera o retrato estatico publicado no GitHub Pages             |
| `tir_real_servidor.py`      | Modelo DDM da TIR real (LPA, payout, P/L, rating)             |
| `INICIAR-TERMINAL.bat/.command` | Atalhos de duplo clique                                   |
| `INSTALAR-PLUGINS-CLAUDE.bat/.command` | Instala os plugins financeiros do Claude no computador |
| `GUIA-PLUGINS-CLAUDE.md`    | Como ativar e usar os plugins de analise e research           |
| `.claude/`                  | Plugins do Claude Code deste repositorio e hook que os instala |
| `CLAUDE.md`                 | Regras da mesa de analise para o Claude neste repositorio     |
| `.claude/skills/analise-ativo/` | Skill: briefing de ativo no padrao de analista senior     |
| `coletar_dados.py`          | Coleta dados de ativos no GitHub Actions e grava no branch `dados` |
| `pares.py`                  | Grupos de pares por setor e acao-mae dos BDRs (comparativos)  |
| `livro/` + `config/livro.yaml` | Livro monitorado: coleta, regras de alerta e fechamento diario (Actions -> branch `dados` -> sessao do Claude) |
| `.claude/skills/livro/`     | Skill: turnos de rotina do livro (manha, intradia, fechamento) na sessao |
| `config/fontes_noticias.yaml` | Veiculos e licencas, consultas do Google News, casamento por ativo, CVM e SEC |

---

## Como abrir o terminal

### 1. Pelo navegador, sem instalar nada

**https://douglora.github.io/broadcast/**

E so abrir. O GitHub Actions coleta os dados e republica o site sozinho, de
hora em hora nos dias uteis (09h-23h UTC) e uma vez por dia no fim de semana.
O selo **SNAPSHOT** no canto superior mostra a hora da ultima publicacao.

Este modo e um retrato, nao tempo real: as cotacoes tem a idade da ultima
publicacao. Para preco ao vivo, use o modo abaixo.

### 2. Na sua maquina, com dados ao vivo

**Clique duas vezes no atalho:**

| Sistema | Arquivo                     |
|---------|-----------------------------|
| Windows | `INICIAR-TERMINAL.bat`      |
| macOS   | `INICIAR-TERMINAL.command`  |
| Linux   | `./INICIAR-TERMINAL.command`|

O atalho busca a versao mais nova, instala o que faltar, sobe o servidor e
**abre o navegador sozinho** em `http://localhost:5051/terminal`. Ai as
cotacoes atualizam a cada 2 segundos.

Pela linha de comando e a mesma coisa:

```bash
python app.py               # porta 5051, abre o navegador
python app.py --port 5050   # outra porta
python app.py --no-open     # sem abrir o navegador
```

Nao precisa instalar nada antes: na primeira execucao o `app.py` instala as
dependencias que faltarem. Se o Python da maquina nao aceitar instalar pacotes
direto (o caso do Homebrew e do python.org no macOS, que seguem o PEP 668), ele
cria sozinho um ambiente proprio em `.venv/` e reinicia o servidor la dentro —
sem pedir nada e sem mexer no Python do sistema. Se a porta estiver ocupada por outro programa, ele
pega a proxima livre e avisa. Se o BROADCAST ja estiver rodando, so abre o
navegador em vez de subir um segundo servidor.

O terminal responde em `/terminal`, na raiz e em qualquer outro caminho. So
os endpoints `/api/*` sao reservados.

### Nao abriu no macOS?

Ao copiar a pasta entre computadores (AirDrop, zip, Drive, pendrive), o macOS
costuma tirar a permissao de execucao do atalho e marcar o arquivo como
"baixado da internet" — o duplo clique nao faz nada, ou reclama de
desenvolvedor nao identificado. Abra o **Terminal** e rode, uma vez:

```bash
cd ~/Desktop/broadcast          # a pasta onde voce colocou os arquivos
chmod +x INICIAR-TERMINAL.command
xattr -d com.apple.quarantine INICIAR-TERMINAL.command 2>/dev/null
./INICIAR-TERMINAL.command
```

Depois disso o duplo clique volta a funcionar. Se preferir pular o atalho,
`python3 app.py` na pasta faz exatamente a mesma coisa.

Se o Mac nao tiver Python, instale com `brew install python` ou baixe em
https://www.python.org/downloads/.

### Nao abriu?

1. No modo site: veja em **Actions** se a ultima execucao de
   *Publicar terminal* passou. O resumo dela diz quantos ativos e noticias
   entraram e quais fontes falharam.
2. No modo local: **http://localhost:5051/health** deve responder um JSON com
   `"status": "ok"`. Se nao responder, o servidor nao esta rodando — volte ao
   atalho.
3. Olhe a janela preta que o atalho abriu: qualquer erro aparece ali.
4. Se disser que o Python nao foi encontrado, instale em
   https://www.python.org/downloads/ (no Windows, marque
   **"Add Python to PATH"**) e clique no atalho de novo.

O terminal **abre mesmo com as fontes externas fora do ar** — os paineis sem
dado mostram "Carregando..." em vez de travar a tela. Nenhuma requisicao do
navegador espera por Yahoo, BCB ou CVM: as fontes sao atualizadas por threads
em segundo plano e os endpoints respondem sempre do cache.

Os graficos tambem nao dependem de CDN: tanto o site publicado quanto o
`app.py` trazem uma copia local do Chart.js.

### Acesso de outro aparelho da casa

O servidor escuta em todas as interfaces, entao basta usar o IP da maquina
(ex.: `http://192.168.0.10:5051`) — nao precisa configurar nada.

---

## De onde vem cada dado

| Painel                    | Fonte                                              |
|---------------------------|----------------------------------------------------|
| Cotacoes, graficos, busca | Yahoo Finance (`/v8/finance/chart`)                |
| Indicadores macro         | Banco Central — series SGS                         |
| Tesouro Direto            | API publica do tesourodireto.com.br                |
| Curva DI                  | Interpolada dos prefixados do Tesouro + Selic meta |
| Curva NTN-B               | Titulos IPCA+ do Tesouro                           |
| Fatos relevantes / proventos | CVM — dados abertos (arquivo IPE)               |
| SEC filings               | EDGAR (8-K, 10-Q, 10-K)                            |
| Noticias                  | RSS (InfoMoney, Money Times, Exame, Reuters, CNBC...) |
| TIR real                  | `tir_real_servidor.py` (modelo DDM proprio)        |
| Spreads de credito        | `data/spreads_ref.json` (tabela mantida a mao)     |

### Spreads de credito privado

Nao existe API publica gratuita de spread por rating. A tabela fica em
`data/spreads_ref.json` e e mantida manualmente; o servidor cruza esses
spreads com a curva NTN-B ao vivo para calcular o yield total. A data da
ultima revisao aparece no proprio painel.

### Atualizar o modelo de TIR

Edite os dicionarios de `tir_real_servidor.py`:
`FORWARD_EPS_SAFRA` (LPA 2025E/2026E), `PAYOUT_HISTORICO`,
`PL_MEDIO_HISTORICO` e `SAFRA_ANALISE` (rating, TIR alvo, nota).

---

## Publicar para clientes (GitHub Pages + tunel)

O `index.html` no GitHub Pages detecta que esta em host estatico e pede a URL
do servidor na primeira abertura. Exponha a sua maquina com:

```bash
ngrok http 5051
# ou
cloudflared tunnel --url http://localhost:5051
```

Envie a URL gerada aos clientes — eles colam no modal de configuracao.
Servido pelo proprio `app.py` (local, rede interna ou servidor proprio), o
terminal usa a mesma origem e nao pede configuracao nenhuma.

---

## Plugins financeiros do Claude

O repositorio vem com os plugins de **Financial Services** da Anthropic
(DCF, comparaveis, notas de resultado, teses) e o **Claude for Financial
Advisors** declarados em `.claude/settings.json`. Ao abrir o Claude Code
nesta pasta, na web ou no computador, um hook de inicio de sessao instala o
que faltar. Para ter os comandos em qualquer pasta do computador, clique duas
vezes em `INSTALAR-PLUGINS-CLAUDE.command` (macOS) ou
`INSTALAR-PLUGINS-CLAUDE.bat` (Windows).

Comandos, fluxos para empresas da B3 e manutencao: **GUIA-PLUGINS-CLAUDE.md**.

---

## Mesa de analise (branch `dados`)

Sessoes do Claude Code na nuvem nao alcancam Yahoo, CVM, SEC ou StatusInvest,
mas alcancam o GitHub. O workflow `.github/workflows/coletar-dados.yml` roda o
`coletar_dados.py` no GitHub Actions, com internet aberta, e grava JSONs por
ativo no branch `dados`. Por ativo, em ordem de autoridade:

1. Demonstracoes oficiais direto da fonte: ITR e DFP consolidados dos dados
   abertos da CVM (companhias da B3) ou XBRL dos 10-Q, 10-K e 20-F na SEC
   (papeis dos EUA, ADRs e a acao-mae dos BDRs), com series trimestrais
   limpas, 4T derivado do anual e LTM.
2. Releases de resultado do RI, os 8 ultimos trimestres: a copia oficial do
   PDF que a empresa publica no site de RI, entregue a CVM (IPE,
   "Press-release" ou "Relatorio de Analise Gerencial") ou a SEC (8-K item
   2.02 / 6-K, exhibit 99). O mais novo vai inteiro no JSON do ativo; os oito
   ficam em `releases/<TICKER>/` no branch, um `.txt` por trimestre mais um
   `index.json`. Cada coleta baixa so o que ainda nao esta la.
3. Yahoo (cotacao, historico, consenso, noticias), Fundamentus, fatos
   relevantes da CVM, macro do Banco Central e TIR real do modelo da casa.

Com o input `pares: auto`, o mesmo run coleta os pares do grupo definido em
`pares.py` e grava `comparativos/<grupo>.json` (multiplos, margens,
crescimento, alavancagem e series oficiais lado a lado, com medianas). Roda
a cada duas horas em dias uteis para a lista do modelo de TIR (sem pares) e
pode ser disparado a mao, pela aba Actions ou pelo proprio Claude.

O Claude le em `https://raw.githubusercontent.com/douglora/broadcast/dados/ativos/<TICKER>.json`,
`.../dados/comparativos/<grupo>.json` e `.../dados/releases/<TICKER>/index.json`. As regras da mesa estao em
`CLAUDE.md`; o procedimento de coleta, o aprofundamento obrigatorio e o
formato da nota, em `.claude/skills/analise-ativo/SKILL.md`. Basta mandar um
ticker.

---

## Livro monitorado (alertas e fechamento diario na sessao do Claude)

O livro e a lista de ativos que o Douglas acompanha (`config/livro.yaml`, com
o nome por extenso de cada UCITS). O sistema tem tres pecas:

1. **Runner** (`.github/workflows/livro.yml` + pacote `livro/`): roda no GitHub
   Actions, coleta Yahoo (series de 2 anos com fechamento ajustado), ajustes do
   DI na B3 (Boletim Diario), Tesouro Transparente, Treasury.gov (UST), BCB/Focus
   e proxies asiaticos (Sina), calcula os indicadores e as regras de alerta
   (`livro/sinais/`: MM200, MM50/MM100, golden/death cross, 52 semanas, movimento
   anormal do dia e da semana, RSI, volume anormal, forca relativa, pares que
   descolam, sequencias, drawdown, regime de risco, DI em bps, inclinacao da
   curva, niveis redondos, inflacao implicita vs Focus, UST e 2s10s, cambio,
   DXY, Brent, minerio, celulose, cripto, resultado D-3/D-1/D0, ex-dividendo,
   agenda macro, Focus da segunda, falha de dados), aplica a politica
   anti-fadiga (`livro/politica.py`)
   e grava em `livro/` no branch `dados`: `saida/fechamento.md` (BLOCO A e
   BLOCO B com dia/1s/1m/6m/1a/YTD), `saida/alertas.md`, `saida/intradia.md`,
   `saida/manha.md`, `saida/noticias.md`, `saida/fechamento_cards.md` (os cards que a
   sessao cola), `saida/painel.html`, `saida/manifest.json`,
   `estado/alertas.json` (fila com ack). Noticias e fatos (`livro/fontes/noticias.py`,
   `cvm.py`, `sec.py` + regras E03/E04/E05): Google News por grupo de ativos com o
   link do veiculo resolvido, fatos relevantes e comunicados do IPE da CVM com o
   PDF lido, 8-K/6-K do EDGAR com o documento lido (exige o secret
   `SEC_USER_AGENT`). Licenca por veiculo em `config/fontes_noticias.yaml`: texto
   integral so de fonte primaria ou veiculo `integral`; o resto e resumo + link.
2. **Sessao do Claude** (skill `.claude/skills/livro/SKILL.md`): e a interface.
   Routines disparam turnos na sessao (09h30, de hora em hora 10h20-17h20 e
   18h40 BRT); o turno dispara o workflow se o dado estiver velho, le o que o
   runner gravou e escreve a Leitura da Mesa. A entrega e na propria sessao, em
   cards de markdown: a sessao troca `[[LEITURA_DA_MESA]]` em
   `saida/fechamento_cards.md` pela manchete e cola os cards (um por bloco do
   livro, alertas, curvas, noticias, agenda). BLOCO A/BLOCO B saem sob demanda
   ("tabela", "completo"). `saida/painel.html` vira uma pagina publicada no
   mesmo Artifact em todo turno de manha e de fechamento, com a mesma leitura
   dos cards; no intradia, so a pedido.
   Push no celular para alerta critico, atencao agrupada e "Fechamento pronto".
3. **Configs**: `config/livro.yaml` (universo), `config/limiares.yaml` (regras),
   `config/calendario.yaml` (feriados, horarios, macro, resultados).

Disparo manual: aba Actions > "Livro monitorado" > Run workflow, com `modo`
(`sonda` mede a cobertura ticker a ticker; `backfill` traz o historico do DI;
`fechamento` gera o relatorio; `eventos` so noticias, CVM e SEC). Pausar: criar o
arquivo `PAUSADO` na raiz.
Pre-requisito que so o dono do repositorio faz: mesclar na `main` (o cron e as
permissoes da sessao so valem la). O contato que a SEC exige no User-Agent tem
padrao no proprio `livro.yml`, por URL publica do projeto, sem dado pessoal;
criar o secret `SEC_USER_AGENT` ("Nome contato@email") troca por um e-mail sem
po-lo em arquivo de repositorio publico.

Testes sem rede: `pip install -r requirements-livro.txt pytest` e
`python3 -m pytest tests/ -q`; execucao offline com as fixtures:
`python3 -m livro.rodar --modo fechamento --saida livro_out --offline tests/fixtures`.

---

## Dados gravados em disco

Ficam em `data/`: `watchlist.json`, `alert_history.json`,
`spread_history.json` e `spreads_ref.json`.

---

Flask + Yahoo Finance + Banco Central (SGS) + Tesouro Direto + CVM + EDGAR

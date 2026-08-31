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
dependencias que faltarem. Se a porta estiver ocupada por outro programa, ele
pega a proxima livre e avisa. Se o BROADCAST ja estiver rodando, so abre o
navegador em vez de subir um segundo servidor.

O terminal responde em `/terminal`, na raiz e em qualquer outro caminho. So
os endpoints `/api/*` sao reservados.

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

## Dados gravados em disco

Ficam em `data/`: `watchlist.json`, `alert_history.json`,
`spread_history.json` e `spreads_ref.json`.

---

Flask + Yahoo Finance + Banco Central (SGS) + Tesouro Direto + CVM + EDGAR

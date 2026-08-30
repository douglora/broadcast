# BROADCAST — The Invest Post

Terminal de mercado em tempo real, estilo Bloomberg. Cotacoes, noticias,
indicadores macro, curva DI, Tesouro Direto, fatos relevantes da CVM,
spreads de credito privado e ranking de TIR real.

O repositorio tem duas partes:

| Arquivo                | O que e                                                        |
|------------------------|----------------------------------------------------------------|
| `index.html`           | O terminal (front-end)                                          |
| `app.py`               | O servidor: serve o terminal **e** todos os endpoints `/api/*`  |
| `tir_real_servidor.py` | Modelo DDM da TIR real (LPA, payout, P/L, rating por analista)   |

---

## Como abrir o terminal

```bash
pip install -r requirements.txt
python app.py
```

Abra **http://localhost:5051**.

O servidor sobe na porta **5051** por padrao. Para trocar:

```bash
python app.py --port 5050     # ou
PORT=8080 python app.py
```

### Nao abriu?

1. Confira se o servidor esta de pe: **http://localhost:5051/health**
   deve responder um JSON com `"status": "ok"`.
2. Se a porta estiver ocupada, suba em outra (`--port 5052`) — o terminal
   funciona em qualquer porta.
3. `app.py` e `index.html` precisam estar na mesma pasta.
4. Os graficos usam Chart.js via CDN (`cdnjs.cloudflare.com`). Sem acesso a
   esse dominio os paineis carregam, mas os graficos ficam vazios.

O terminal **abre mesmo com as fontes externas fora do ar** — os paineis sem
dado mostram "Carregando..." em vez de travar a tela. Nenhuma requisicao do
navegador espera por Yahoo, BCB ou CVM: as fontes sao atualizadas por threads
em segundo plano e os endpoints respondem sempre do cache.

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

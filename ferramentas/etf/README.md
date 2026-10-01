# Analise de ETFs UCITS (mesa BROADCAST)

Scripts que montaram o relatorio "Entrada nos UCITS" de 29/09/2026
(https://claude.ai/artifact/BHUnMzteyivcHye62LFaMv). Leem o que o coletor
`etfs.py` (workflow `etfs.yml`) gravou em `etfs/` no branch `dados` e o livro em
`livro/series/`. Nao baixam nada da internet: rode a coleta antes.

A saida (JSONs com preco e indicadores) vai para `ferramentas/etf/saida/`, que o
git ignora: e dado de mercado e nao entra na main. Para outra pasta, defina
`ETF_SAIDA`.

## Ordem de execucao

Da pasta `ferramentas/etf/` (no Windows, troque `python3` por `py`):

```bash
git fetch origin dados
python3 justetf.py                    # carteiras, TER, paises e setores dos perfis do justETF
python3 analise.py "CSPX.L,VHYA.L,..." # tecnica de cada simbolo e o veredito da regra -> tecnica.json
python3 cenarios.py                   # 2004-06, 2018, 2022, sazonalidade, largura -> cenarios.json
python3 vhya.py                       # dividend yield historico, episodios e sensibilidade -> vhya.json
python3 ia.py                         # sobreposicao com o SPY, correlacao, beta, quedas -> ia.json
python3 consolida.py                  # liquidez, spread, taxa, P/L e niveis por ETF -> consolidado.json
python3 graf.py                       # series dos graficos -> graf.json
python3 monta.py                      # relatorio HTML -> saida/ucits.html
node shot.js saida/ucits.html         # opcional: prints de celular e PC (precisa do playwright)
```

`analise.py` recebe a lista de simbolos do Yahoo. A lista usada em 29/09 esta no
topo de `monta.py` (dicionario `VER`) e no relatorio.

## A regra de entrada (fixada antes de olhar os numeros)

- Tendencia de alta: preco acima da MM200, MM200 subindo em 20 pregoes, MM50 acima da MM200.
- Pullback: de 2% a 10% abaixo da maxima de fechamento de 52 semanas, ou RSI abaixo de 45.
  Queda maior que 10% e correcao, nao pullback.
- Sem esticar: menos de 5% acima da MM50, RSI abaixo de 65, menos de 15% acima da MM200.
- Entrada agora = as tres. Em parcelas = tendencia sem pullback, esticado, correcao de 10% a
  20%, volatilidade de 3 meses acima de 35% ou evento binario (acao com 10% ou mais do fundo
  divulgando resultado; lista em `EVENTO`, em `analise.py`). Esperar = abaixo da MM200 em queda,
  MM50 abaixo da MM200 com preco abaixo dela, ou queda maior que 20%.

## Cuidados que os dados ensinaram

- O Yahoo pode omitir o pregao anterior da LSE enquanto o pregao do dia esta aberto
  (28/09/2026). `analise.serie` preenche com a barra do livro ou com o fechamento anterior da
  cotacao do mesmo pregao, e marca a origem em `pregao_anterior`.
- `fiftyTwoWeekHigh` do CSPX.L vem com tick errado (888,76): use maxima de fechamento.
- `etfs/cotacoes.json` e sobrescrito por coleta parcial: `analise.cotacao` mescla os ultimos
  commits. Spread so com o pregao aberto: `analise.cotacao_aberta`.
- VHYL e VWRL sao em libra; para historico em dolar use VHYD e VWRD (distribuicao) com o
  fechamento ajustado.
- O P/L e o P/VP de carteira vem da Morningstar via Yahoo como inverso (`priceToEarnings` 0,06
  = P/L 16,7). Nao ha historico desses multiplos no branch.

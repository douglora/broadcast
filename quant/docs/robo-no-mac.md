# O robo no Mac (simulacao ao vivo), desde 08/10/2026

O que roda sozinho no computador do Douglas, onde fica cada coisa e o que ainda falta.
Nada aqui manda ordem a corretora: nao ha codigo de envio nem credencial.

## Em uma frase

Todo dia util as 8h35 o Mac atualiza os dados, recalcula os sinais, valida a regra contra o
NEFIN e emite a boleta; das 10h20 as 17h00 o robo simula a execucao contra as cotacoes ao vivo
do Autopilot Terminal e mostra na area QUANT; as 20h30 mede a mesma boleta contra a fita
oficial da B3 e grava o que executou, que vira a posicao do dia seguinte.

## Comandos

```bash
python -m quant.robo estado      # o que ja rodou hoje (e o que falhou, com o fim da saida)
python -m quant.robo preparar    # manha, na mao (pula se a boleta de hoje ja saiu; --repetir forca)
python -m quant.robo vivo        # so a simulacao ao vivo
python -m quant.robo fechar      # noite (--data AAAA-MM-DD para um pregao passado; --fita-do-robo)
python -m quant.robo dia         # o dia inteiro: e o que o agendador chama
```

Agendador: `~/Library/LaunchAgents/br.autopilot.quant.plist` (rotulo `br.autopilot.quant`).
Registro: `~/Library/Logs/autopilot-quant.log`. Reiniciar na mao:
`launchctl kickstart -k gui/$(id -u)/br.autopilot.quant`.

## A rotina da manha (`preparar`), em ordem de dependencia

| Passo | O que faz | Tempo (08/10) |
|---|---|---|
| cotacoes | COTAHIST do ano (traz o fechamento de ontem) | 71 s |
| identidade | mapa ticker, ISIN, CNPJ, codigo CVM | 3 s |
| boletim | BDI de ontem e carteiras de indice (sem a tabela BTBTrade, que estoura o tempo na B3) | 1 a 4 min |
| proventos | B3 por emissor e por nome de pregao; StatusInvest so na segunda | 88 s |
| balancos | ITR/DFP do ano e do anterior | 21 s |
| capital | numero de acoes (composicao do capital dos ITR/DFP) | 1 s |
| cdi | CDI diario do Banco Central | 1 s |
| fundamentos | painel recente, com valor de mercado | 40 s |
| sinais | momentum, qualidade, valor, risco | 4 s |
| validacao | gate da fase 1 (replica do WML do NEFIN) | 25 a 36 s |
| boleta | rodada diaria em simulacao | 3 s |

Passo que falha fica marcado em `quant/saida/rotina/<data>.json`; a boleta entao sai
bloqueada pelo modo seguro em vez de sair errada.

## O robo ao vivo (`execucao/robo_vivo.py`)

- Le `GET /vivo/retrato` do motor do terminal a cada 2 s. Para cada papel da boleta, a
  variacao do volume acumulado da sessao vira um negocio; o preco e o financeiro do intervalo
  (preco medio do dia vezes volume, diferenca entre dois retratos) dividido pelo volume, ou o
  ultimo preco quando o erro de arredondamento passa de 0,05%.
- Entrega a fita a `paper_vivo.Sessao`, que recasa a boleta inteira com `paper.simular`
  (teto de 1% do volume do periodo, limite com os degraus das 12h20, 14h20 e 16h20).
- So casa ordem das 10h20 as 17h00 (leilao de fechamento incluido, after-market fora).
- Grava o estado em `~/Desktop/terminal-artefato/web/d/x/quant.json` e
  `cache/out/pagina/quant.json` (a area QUANT le o primeiro; o montador publica o segundo).
- Estado do dia em `quant/saida/vivo/<data>/`: `fita.csv`, `estado.json` e `boleta.json`
  (a boleta que saiu primeiro hoje: a rodada refeita no meio do dia nao troca as ordens).
- Um robo por maquina (`quant/saida/vivo/robo.trava`).

## A noite (`fechar`)

1. `arquivar_b3 --fontes negocios,ipe` com os papeis da boleta.
2. `campanha.rodar_do_dia(boleta=<a da manha>, reprecificar=True, ate_hora="17:00")`: fills no
   livro de ordens e a linha do dia em `quant/saida/campanha_sessoes.csv`.
3. Se a B3 nao entregar o negocio a negocio ate 23h40 (em 08/10 o endereco respondia 504), a
   sessao fecha com a fita que o robo viu ao vivo, anotada como tal no arquivo da rotina.

## O que a primeira rodada com dado real consertou

Esta em `quant/testes/test_primeira_rodada_real.py`, um teste por achado: salto sem evento,
ticker reaproveitado, lote de mil, calendario fora da cobertura, PL de banco pela descricao da
conta, numero de acoes ex-tesouraria com a escala por companhia, reprecificacao, fita derivada
do volume acumulado e volume da vespera que reaparece.

## O que falta (em ordem de importancia)

1. **Caixa e resultado realizado entre pregoes.** `rodar_diario._estado_atual` monta o caixa
   como capital menos o custo das posicoes: lucro de venda some. Nao pesa enquanto so ha
   compras; pesa no primeiro rebalanceamento.
2. **Protecao (mini-indice) entre pregoes.** O estado da protecao nao persiste: a boleta diz
   "abertura" todo dia e o resultado da protecao da noite para o dia nao e contado.
3. **Serie de patrimonio contra CDI e Ibovespa** (`desempenho` do painel vem vazio; o robo
   grava so `quant/saida/vivo/serie.json`).
4. **Gate so com WML.** O HML precisa do PL historico (painel completo).
5. **Painel completo e backtest (fase 2)** nunca rodaram com dado real: mais de 1 hora de carga.
6. **Aluguel e insiders**: sem dado (o NEFIN parou de publicar a taxa por papel; a tabela
   BTBTrade da B3 estoura o tempo).
7. **Curadoria dos saltos**: `gate_fase1.json` (campo `limpeza.lista_saltos`) e a fila de
   grupamentos e desdobramentos que nenhuma fonte trouxe.

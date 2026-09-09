# quant — sistema quantitativo de ações B3 (pessoa física)

Pasta separada do terminal BROADCAST. Objetivo: carteira **long por interseção de fatores
(momentum × qualidade × valor) em small/mid/large caps líquidas, com hedge parcial de beta
em mini-índice**, rebalanceamento incremental por custo e apuração fiscal própria.
Long/short beta-neutro com short em ações foi descartado para esta escala (ver o plano).

## Veredito honesto (resumo)

- **Viável tecnicamente: sim.** Todos os dados necessários são gratuitos (B3, CVM, NEFIN, BCB).
- **Fonte de retorno relevante com R$100 mil: não, ou quase não.** Cenário base estimado:
  CDI −0,5 a +1,0 p.p. a.a. antes de IR; Sharpe do excesso 0,05–0,15; ano ruim CDI −20 p.p.
  Em R$200 mil: CDI +0,5 a +2,0 p.p. Nenhum backtest foi rodado ainda: são estimativas
  ancoradas em evidência (fatores NEFIN 2001–2026, track record da Bayes, base rates).
- **Vale como laboratório, infraestrutura e track record que escala**, com critérios de kill
  escritos antes do primeiro trade.
- O único fator com estatística forte na B3 é **momentum 12–2** (WML NEFIN: 15,4% a.a. bruto,
  t = 4,6, com anos de −32%/−36%). Size e iliquidez têm prêmio zero; valor é cíclico.
- Qualquer backtest deste sistema com Sharpe > 1,0 após custos é bug até prova em contrário.

O diagnóstico completo — citações do podcast com Marcello Paixão (Bayes/AZ Quest),
assimetrias reais vs mito, custos e impostos, estratégia recomendada, números esperados,
riscos, módulos e critérios de kill — está em [`docs/diagnostico-e-plano.md`](docs/diagnostico-e-plano.md).

## Estrutura

| Caminho | O que é | Estado |
|---|---|---|
| `comum.py` | caminhos, HTTP tolerante, escrita atômica, base64 dos proxies B3 | pronto |
| `dados/calendario.py` | pregões da B3 (bizdays B3 + ANBIMA) | pronto, testado |
| `dados/arquivar_b3.py` | **M0** arquivador diário: aluguel (BDI), negócio a negócio → barras de 1 min, carteiras e prévias de índice, IPE com hora de captura | pronto; parsers testados com fixtures; rede só no CI |
| `dados/cotahist.py` | **M2** COTAHIST anual/diário → parquet `banco/cotacoes_diarias/ano=AAAA/` | pronto; layout testado com fixture |
| `dados/nefin.py` | **M6** fatores NEFIN fixados por hash + estatísticas | pronto, testado ao vivo |
| `dados/identidade.py` | **M3** ticker ↔ ISIN ↔ CD_CVM point-in-time (FCA + cadastro + COTAHIST) | pronto; testado com fixtures; validar formato real ([docs/validar-com-fonte-real.md](docs/validar-com-fonte-real.md)) |
| `dados/eventos.py` | **M4** proventos/eventos (B3 + StatusInvest + curadoria) e retorno total forward | pronto; testado com fixtures; validar formato real ([docs/validar-com-fonte-real.md](docs/validar-com-fonte-real.md)) |
| `dados/cvm_fundamentos.py` | **M5** DFP/ITR point-in-time por `DT_RECEB`, TTM e métricas (mapa de contas em `dados/contas_cvm.py`) | pronto; testado com fixtures; validar formato real ([docs/validar-com-fonte-real.md](docs/validar-com-fonte-real.md)) |
| `dados/cdi.py` | **M6** CDI diário (SGS 12) com fallback NEFIN | pronto; testado com fixtures; validar formato real ([docs/validar-com-fonte-real.md](docs/validar-com-fonte-real.md)) |
| `universo.py` | **M7** universo PIT mensal (uma classe por empresa, ADTV, presença, preço) | pronto; testado com fixtures; validar formato real ([docs/validar-com-fonte-real.md](docs/validar-com-fonte-real.md)) |
| `validacao/replica_nefin.py` | gate da fase 1: réplica WML/HML do NEFIN (corr ≥ 0,90, ±3 p.p.) | pronto; testado com fixtures; **ainda não rodado com COTAHIST real** (precisa de rede) |
| `dados/setores.py` | macrossetor por CNPJ (SETOR_ATIV da CVM + `setores_curados.csv`); destrava o teto de 25% e a marcação de financeiras | pronto; testado com fixtures; validar formato real ([docs/validar-com-fonte-real.md](docs/validar-com-fonte-real.md)) |
| `dados/capital_social.py` | ações em circulação (FCA) com reserva por LPA; é o que dá valor de mercado ao sinal de valor | pronto; testado com fixtures; validar formato real ([docs/validar-com-fonte-real.md](docs/validar-com-fonte-real.md)) |
| `dados/painel_fundamentos.py` | painel PIT de TTM e métricas por data de decisão; equivalente a `ttm()` e ~200x mais rápido | pronto; equivalência com `ttm()` provada em teste |
| `dados/mercado.py` | excesso do mercado, nível do índice e beta móvel para o hedge de WIN | pronto; **nível âncora do Ibovespa a conferir** |
| `sinais.py` | **M8** os 8 sinais, portões, exclusões e o score 0,50/0,25/0,25 | pronto; teste de look-ahead por sinal |
| `custos.py` | **M9** emolumentos, meio-spread por faixa de ADTV, impacto, WIN, JCP, aluguel e modo 2× | pronto; parâmetros são ESTIMATIVA (validar no paper trading) |
| `carteira.py` | **M10** seleção com histerese, pesos 1/vol com cap e piso, hedge e regra incremental | pronto; ver os dois ACHADOS no docstring |
| `livro.py` | livro de tentativas encadeado por hash, lacre do holdout e Sharpe deflacionado | pronto, testado |
| `backtest.py` | **M11** laço mensal, atribuição NEFIN, comparações pré-registradas e veredito | pronto; **nunca rodado com dado real** |
| `validacao/mercado_sintetico.py` | mercado artificial nos esquemas reais, com gabarito e interruptor de look-ahead | pronto, testado |
| `fiscal.py` | **M12** apuração de IR: preço médio, day trade detectado, isenção de R$20 mil, DARF 6015 e memória de cálculo | pronto; **tabela tributária a conferir com contador** |
| `execucao/livro_ordens.py` | livro de ordens e fills, posição real com preço médio | pronto, testado |
| `execucao/boleta.py` | **M13** boleta noturna com limite ao mid, fatiamento e modo seguro | pronto; regras de execução nunca exercidas numa corretora |
| `execucao/paper.py` | fills simulados contra o negócio a negócio e medição de slippage | pronto; o slippage medido é piso, não estimativa |
| `execucao/campanha.py` | **Fase 4** campanha de paper trading: sessão diária, diário de erros e os 9 critérios de passagem | pronto; só rodou como **ensaio** sobre o mercado sintético |
| `rodar_diario.py` | **M14** orquestra a rodada e grava `saida/painel.json` | pronto, testado |
| `relatorio.py` | **M14** relatório periódico e os sete critérios de encerramento | pronto, testado |
| `versoes.py` | **M14** changelog de versões: 2 mudanças/ano, 3 meses de paper em paralelo, diff calculado e cadeia de hash | pronto, testado; o changelog começa vazio |
| `docs/painel-contrato.md` | contrato do `painel.json` entre o `rodar_diario` e o terminal | — |
| `docs/rotina-paper-trading.md` | a rotina de manhã, de fim de dia e de fim de mês da Fase 4 | — |
| `docs/comecar-a-rodar.md` | **passo a passo do que só o Douglas pode fazer** (corretora Safra, CVM 178, primeira carga, gate) | — |
| `docs/emails-para-enviar.md` | os dois e-mails prontos: tabela do Safra e consulta ao compliance | — |
| `docs/no-mac-do-zero.md` | **como fazer tudo no Mac**, do "abrir o Terminal" até a rotina diária | — |
| `primeira_carga.py` | a carga inicial inteira em um comando, com repeticao e relatório | pronto, testado |
| `dados/conferir.py` | conferência automática do banco contra os valores de referência | pronto; NEFIN já validado contra a fonte real |
| `../quant.html` | a página `/quant`: o painel de operação, fora do terminal de notícias | pronto; nunca entra no site publicado |
| `execucao/mt5_ponte.py` | M15 (estágio B) | fase 5 |
| `testes/` | pytest, sem rede (exceto NEFIN, que pula se não houver acesso) | |

Dados brutos ficam em `quant/dados_brutos/<fonte>/<data>/` (gzip) e derivados em
`quant/banco/` (parquet). Ambos são ignorados pelo git no `main`; o workflow
`.github/workflows/coletar-quant.yml` roda a cada pregão (21:00 BRT) e publica os brutos
no branch `dados-quant`.

## Como rodar

**No Mac, comece por [`docs/no-mac-do-zero.md`](docs/no-mac-do-zero.md)** — dois cliques em
`PREPARAR-MAC.command` instalam tudo num ambiente isolado (obrigatório do macOS Sonoma em
diante) e rodam os testes. Os comandos abaixo supõem o ambiente ativado com
`source .venv/bin/activate`.

```bash
pip install -r quant/requirements.txt
python3 -m pytest quant/testes -q                    # testes
python3 -m quant.dados.arquivar_b3                  # arquiva o último pregão (precisa de rede)
python3 -m quant.dados.arquivar_b3 --data 2026-09-04 --fontes bdi,indices
python3 -m quant.primeira_carga                     # A CARGA INTEIRA, em um comando
python3 -m quant.dados.conferir                     # confere o banco contra os valores de referencia

# ou passo a passo, se preferir controlar cada um:
python3 -m quant.dados.cotahist --anos 2005-2026    # baixa e converte o COTAHIST
python3 -c "from quant.dados import nefin; nefin.baixar('fatores'); nefin.baixar('aluguel_taxa')"
python3 -m quant.dados.identidade                   # FCA + cadastro CVM → banco/identidade.parquet
python3 -m quant.dados.eventos                      # proventos B3 + StatusInvest + curadoria → banco/eventos.parquet
python3 -m quant.dados.cvm_fundamentos --anos 2010-2026   # DFP/ITR → banco/fundamentos_pit/
python3 -m quant.dados.cdi                          # CDI diário (SGS 12) → dados_brutos/bcb/
python3 -m quant.dados.setores                      # macrossetor por CNPJ
python3 -m quant.dados.capital_social --anos 2010-2026     # acoes em circulacao (FCA)
python3 -m quant.dados.painel_fundamentos --anos 2010-2026 # painel PIT de TTM e metricas
python3 -m quant.validacao.replica_nefin --ini 2008 --fim 2026   # gate da fase 1 (precisa do COTAHIST)
python3 -m quant.sinais --ini 2011 --fim 2026       # painel mensal de sinais
python3 -m quant.backtest --janela treino           # 2011-2015, quantas vezes quiser
python3 -m quant.backtest --janela holdout --abrir-holdout   # UMA vez; depois lacra
python3 -m quant.livro --verificar                  # a cadeia do livro de tentativas
python3 -m quant.rodar_diario --paper               # rodada diaria: boleta do dia e painel.json
python3 app.py                                      # terminal em http://localhost:5051
                                                    # painel quant em /quant
python3 -m quant.fiscal --ano 2026                  # apuracao, DARF e memoria de calculo
python3 -m quant.relatorio --mes 2026-09            # relatorio e status dos criterios de kill
python3 -m quant.custos --corretagem 15.00          # a tarifa da corretora cabe no ganho esperado?

# fase 4 - campanha de paper trading (ver docs/rotina-paper-trading.md)
python3 -m quant.execucao.campanha --ensaio         # ensaio sintetico: prova que o laco fecha
python3 -m quant.execucao.campanha --sessao         # registra o pregao de hoje (APOS o fechamento)
python3 -m quant.execucao.campanha --erro 2026-09-08 ordem_esquecida "esqueci a venda de ABCD3"
python3 -m quant.execucao.campanha --conferir 2026-09   # assina o mes como conferido
python3 -m quant.execucao.campanha --status         # placar dos 9 criterios da fase 4

# changelog de versoes (criterio de kill 7: no maximo 2 mudancas por ano)
python3 -m quant.versoes                            # imprime o changelog
python3 -m quant.versoes --conferir                 # a config viva bate com a versao vigente?
python3 -m quant.versoes --registrar "momentum 50->55" "pesquisa X" --backtest '{"sharpe_novo":0.32}'
```

O painel do sistema quant tem **página própria** em `http://localhost:5051/quant`, com as
abas Carteira, Boleta, Fiscal e Desempenho (o placar da campanha de paper trading e a
versão vigente ficam no fim da aba Boleta). No terminal sobra só um card de resumo no fim
da coluna da direita — frescor dos dados, mês contra o CDI, ordens de hoje e o semáforo dos
critérios de kill — e ele leva para a página. Um terminal de notícias e um painel de
operação são coisas diferentes: um fica aberto o dia inteiro, o outro é usado 15 minutos de
manhã.

A página lê apenas `quant/saida/painel.json`: o `app.py` continua sem depender de pandas, e
**ela nunca entra no snapshot estático publicado no GitHub Pages** — o `gerar_dados.py`
copia HTML por nome e o `quant.html` não está lá, o que é verificado por teste. Carteira,
resultado e apuração de imposto são pessoais e ficam na máquina.

Ordem da primeira carga com rede: `cotahist` → `nefin` → `identidade` → `eventos` →
`cvm_fundamentos` → `cdi` → `replica_nefin`. O gate imprime correlação e diferença
média anual da réplica WML/HML contra o NEFIN e sai com código 1 se falhar; nada
da fase 2 deve ser construído sobre dados que não passaram por ele.

Tudo que só pôde ser testado com fixtures (formatos reais da B3, CVM, StatusInvest e
BCB não eram alcançáveis no ambiente de desenvolvimento) está listado com o teste a
fazer em [docs/validar-com-fonte-real.md](docs/validar-com-fonte-real.md).

## Regras que o código respeita (e que os testes cobram)

- **Point-in-time**: nenhum dado entra antes da data em que ficou disponível
  (`DT_RECEB` na CVM, `data_ex` em eventos, data do snapshot no NEFIN).
- **Sem viés de sobrevivência**: a série de preços segue o ISIN por todos os CODBDI
  (recuperação judicial continua na série); o universo de compra usa só CODBDI 02.
- **Proventos como retorno total forward** a partir da data-ex, nunca restatement.
- **Feriado** → HTTP 400 / ZIP vazio: tudo que baixa por data passa pelo calendário.
- **Custos** e **IR** são cidadãos de primeira classe no backtest (fase 2).
- **Modo seguro**: sem COTAHIST do dia, sem BDI, ou com o gate da Fase 1 não aprovado, o
  sistema **não emite boleta** e diz o que falta. Boleta com dado velho é pior que boleta
  nenhuma, porque seria executada.
- **A apuração de imposto é cálculo de apoio.** O módulo produz memória de cálculo linha a
  linha para ser conferida; conferir com contador antes de recolher qualquer DARF não é
  opcional.

## Changelog

- 2026-09-07 — v0.1.0: Fase 0 (calendário, arquivador, workflow de coleta) e início da
  Fase 1 (COTAHIST, NEFIN). Nenhum sinal ou backtest ainda.
- 2026-09-07 — Fase 1 completa em código: identidade PIT (M3), eventos e retorno total
  (M4), fundamentos CVM PIT (M5), CDI (M6), universo PIT (M7) e o gate de réplica
  WML/HML do NEFIN. 111 testes. Só o NEFIN foi validado ao vivo; os demais parsers
  esperam a primeira rodada com rede (ver `docs/validar-com-fonte-real.md`). O gate
  ainda não foi executado com COTAHIST real.
- 2026-09-07 — Fase 2 completa em código: sinais (M8), custos (M9), carteira (M10),
  backtest (M11), livro de tentativas com lacre do holdout, painel de fundamentos
  vetorizado, setor, capital social, mercado e o gerador de mercado sintético.
  **Os números que este código produz hoje são sintéticos e não são resultado de
  estratégia**: o banco está vazio e o gate da Fase 1 continua sem rodar. O que está
  provado é a mecânica — identidade contábil ao centavo, ausência de look-ahead por
  sinal, e o controle nulo (sem prêmio plantado, o motor não fabrica alfa). Três leituras
  do plano aprovado tiveram de ser corrigidas para funcionar; estão listadas em
  `docs/validar-com-fonte-real.md`.
- 2026-09-08 — Fase 3: apuração de IR (M12), livro de ordens, boleta e fills simulados
  (M13), orquestrador diário e relatório com os sete critérios de encerramento (M14), e o
  painel dentro do terminal. O terminal **não** ganhou pandas: o cálculo pesado roda em
  `rodar_diario.py` e o `app.py` só lê `saida/painel.json`. O painel nunca sai da máquina.
  A tabela tributária inteira ainda precisa de conferência com contador, e o modo seguro
  bloqueia a boleta enquanto o gate da Fase 1 não passar.

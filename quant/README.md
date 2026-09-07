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
| `sinais.py`, `custos.py`, `carteira.py`, `backtest.py`, `fiscal.py`, `execucao/`, `relatorio.py` | M8–M15 | fase 2+ |
| `testes/` | pytest, sem rede (exceto NEFIN, que pula se não houver acesso) | |

Dados brutos ficam em `quant/dados_brutos/<fonte>/<data>/` (gzip) e derivados em
`quant/banco/` (parquet). Ambos são ignorados pelo git no `main`; o workflow
`.github/workflows/coletar-quant.yml` roda a cada pregão (21:00 BRT) e publica os brutos
no branch `dados-quant`.

## Como rodar

```bash
pip install -r quant/requirements.txt
python3 -m pytest quant/testes -q                    # testes
python3 -m quant.dados.arquivar_b3                  # arquiva o último pregão (precisa de rede)
python3 -m quant.dados.arquivar_b3 --data 2026-09-04 --fontes bdi,indices
python3 -m quant.dados.cotahist --anos 2005-2026    # baixa e converte o COTAHIST
python3 -c "from quant.dados import nefin; nefin.baixar('fatores'); nefin.baixar('aluguel_taxa')"
python3 -m quant.dados.identidade                   # FCA + cadastro CVM → banco/identidade.parquet
python3 -m quant.dados.eventos                      # proventos B3 + StatusInvest + curadoria → banco/eventos.parquet
python3 -m quant.dados.cvm_fundamentos --anos 2010-2026   # DFP/ITR → banco/fundamentos_pit/
python3 -m quant.dados.cdi                          # CDI diário (SGS 12) → dados_brutos/bcb/
python3 -m quant.validacao.replica_nefin --ini 2008 --fim 2026   # gate da fase 1 (precisa do COTAHIST)
```

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

## Changelog

- 2026-09-07 — v0.1.0: Fase 0 (calendário, arquivador, workflow de coleta) e início da
  Fase 1 (COTAHIST, NEFIN). Nenhum sinal ou backtest ainda.
- 2026-09-07 — Fase 1 completa em código: identidade PIT (M3), eventos e retorno total
  (M4), fundamentos CVM PIT (M5), CDI (M6), universo PIT (M7) e o gate de réplica
  WML/HML do NEFIN. 111 testes. Só o NEFIN foi validado ao vivo; os demais parsers
  esperam a primeira rodada com rede (ver `docs/validar-com-fonte-real.md`). O gate
  ainda não foi executado com COTAHIST real.

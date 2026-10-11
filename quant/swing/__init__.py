"""
Swing trades curtos de acoes (SIMULACAO): operacoes de 2 a no maximo 10 pregoes, com stop, alvo e prazo.

Pesquisa (pre-registro `quant/saida/pesquisa_swing/PRE_REGISTRO.md`):
  dados.py       painel diario ajustado, universo point-in-time, ranking multifatorial, Ibovespa (proxy), CDI
  setups.py      as 13 regras de entrada (7 familias) e as 39 variantes (sobreposicoes S0, S1, S2)
  simulador.py   operacoes (entrada na abertura seguinte; saida por stop, alvo ou tempo) e o livro com capital, custos e marcacao diaria
  pesquisa.py    descoberta 2010-2017, validacao 2018-2021 e prova 2022-2026 (aberta uma vez, so para finalista)

Modulo de producao (o que o robo roda):
  tamanho.py     quantidade pelo risco, teto por papel, numero de posicoes, exposicao
  posicao.py     validacao do prazo (<= 10 pregoes) e decisao de saida ao vivo (stop, alvo, tempo, gap)
  estado.py      posicoes e operacoes fechadas em arquivo; conciliacao com as barras oficiais da B3
  evidencia.py   quem pode usar capital (so quem passou nas 3 etapas) e quem fica "so medido"
  candidatas.py  os sinais do ultimo fechamento, com stop, alvo, prazo e a frase do "porque"
  gestor.py      mesa (veto e preferencia), vespera de resultado, tamanho, exposicao, ficha do terminal (opcional)
  boleta.py      a rodada da manha: concilia, acha sinais, decide, grava a boleta e a tela (python -m quant.swing.boleta)
  vivo.py        o robo ao vivo: entrada na abertura, vigia stop/alvo/prazo, grava a tela (python -m quant.swing.vivo)
  painel.py      o JSON da tela (contrato: quant/docs/tela_swing.md)
  ensaio.py      um pregao inteiro de mentira numa pasta temporaria (python -m quant.swing.ensaio)
"""

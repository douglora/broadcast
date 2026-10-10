"""
Modulo de OPCOES do robo quant (pesquisa e simulacao, 10/10/2026). Nenhuma ordem real.

  bs.py         Black-Scholes proprio: premio, volatilidade implicita, delta, gama, teta, vega
  base.py       monta a base de opcoes por dia a partir do COTAHIST da B3 (parquet em
                quant/saida/pesquisa5/opcoes/dados/)
  dados.py      leitores da base: opcoes, ativo-objeto, retorno total, CDI, ciclos mensais
  custos.py     custo real: cruzar a oferta, emolumentos da B3, exercicio
  motor.py      simulador de ciclos mensais (venda de put, venda de call coberta, pozinho, protecao, travas)
  metricas.py   retorno anual, Sharpe, queda maxima, pior mes, Sharpe deflacionado, registro de tentativas
  painel.py     gera quant_opcoes.json para o terminal

Metodo: quant/pesquisa/METODO.md (hipotese antes do codigo, registro de tentativas, descoberta ate 2019,
validacao 2020-2023, prova 2024-2026 uma vez).
"""

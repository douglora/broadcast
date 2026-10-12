"""
Camada de OBSERVACAO do robo (12/10/2026): macro, micro, grafico e fundamento viram SINAIS medidos todo dia, com
termometro de regime (G20), escada de dose de risco (G23) e placar de calibracao (G19) com aposentadoria por decaimento (G2).

TUDO AQUI E SO MEDIDO. Nenhum sinal muda lote, exposicao, chave ou ordem de nenhum modulo: a camada le o terminal (so
leitura), grava a leitura do dia em quant/saida/observacao/ e, com o tempo, o placar diz quais sinais tem informacao
(60+ leituras, media a favor positiva e t >= 2) e quais devem ser aposentados (G2). So entao, com o "pode" escrito do
Douglas, um sinal vira regra de dose. Pedido dele em 12/10/2026: "estrategias que observam macro, micro, grafico e
fundamento toda hora, ache padroes e anomalias, triangule com o passado".

    python -m quant.observacao            # leitura de hoje: sinais, termometro, dose; grava e imprime
    python -m quant.observacao --placar   # o placar de cada sinal contra o que o mercado fez depois (e o Brier do cartao)

Modulos: fontes.py (leitura do terminal), sinais.py (as regras de cada sinal), termometro.py (G20), dose.py (G23),
placar.py (G19 e G2). Testes em quant/testes/test_observacao.py.
"""
import os

from quant.comum import DIR_SAIDA

DIR_OBS = os.path.join(DIR_SAIDA, "observacao")
ARQ_LEITURAS = os.path.join(DIR_OBS, "sinais.jsonl")
ARQ_HOJE = os.path.join(DIR_OBS, "hoje.json")
ARQ_PLACAR = os.path.join(DIR_OBS, "placar.json")

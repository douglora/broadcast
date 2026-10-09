"""Mini-indice: a tendencia do dia continua na ultima meia hora (achado da familia win_estrutura em 09/10/2026).

Regra: 31 minutos antes do fim do pregao (o fim e o horario da ultima barra do pregao ANTERIOR), compara o preco com a
abertura do dia. Acima: compra; abaixo: vende. A entrada sai na abertura do minuto seguinte (30 minutos antes do fim) e a
saida e por tempo, 25 minutos depois, ou no stop. Pregao que abre depois das 9h15 fica de fora.
Mecanismo provavel (nao verificado): zeragem obrigatoria das posicoes de day trade pelas corretoras, uns 10 minutos antes
do fim: quem estava contra a tendencia do dia e obrigado a sair, e empurra o preco a favor dela.
Saida congelada: tempo 25 minutos, stop 500 pontos. Reimplementacao independente da regra da pesquisa, para conferencia."""
import numpy as np
import pandas as pd


def regra(m, n=30):
    minuto = np.asarray(m.index.hour * 60 + m.index.minute)
    df = pd.DataFrame({"d": np.asarray(m.index.date), "min": minuto, "o": m["o"].to_numpy(dtype=float), "c": m["c"].to_numpy(dtype=float)})
    g = df.groupby("d", sort=False)
    primeiro_min, abertura = g["min"].transform("first"), g["o"].transform("first")
    fim_anterior = g["min"].last().shift(1)                      # ultima barra do pregao anterior: so passado
    decide = df["d"].map(fim_anterior) - n - 1
    s = np.where((df["min"] == decide) & (primeiro_min <= 9 * 60 + 15), np.sign(df["c"] - abertura), 0.0)
    return np.nan_to_num(s)

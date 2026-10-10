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


CUSTO_RS, RS_POR_PONTO = 5.20, 0.40      # 2 contratos: R$ 0,30 por contrato e lado + 1 tick (5 pontos) contra na entrada e na saida


def regra_adaptativa(m, n=30, tempo=25, janela=60, minimo=40):
    """Variante declarada em 10/10/2026, DEPOIS de a prova de 2026 mostrar que o efeito inverteu (a favor da tendencia do dia
    de 2021 a 2024; contra em 2026). Opera no sentido que vem dando resultado: mede, nos `janela` pregoes anteriores, o que
    teria rendido seguir a tendencia do dia e o que teria rendido ir contra (os dois ja com custo); entra no lado cuja media
    e positiva (o melhor dos dois), ou nao entra. So usa pregoes ja encerrados. Como nasceu depois de 2026 ser visto, NAO ha
    dado antigo que a prove: vale so a prova viva."""
    base = regra(m, n)
    idx = np.where(base != 0)[0]
    o = m["o"].to_numpy(dtype=float)
    d = np.asarray(m.index.date)
    ent, sai = idx + 1, idx + 1 + tempo
    ok = (sai < len(m)) & (d[np.minimum(sai, len(m) - 1)] == d[idx])
    bruto = np.where(ok, base[idx] * (o[np.minimum(sai, len(m) - 1)] - o[np.minimum(ent, len(m) - 1)]), np.nan)   # pontos a favor da tendencia
    segue = pd.Series(bruto * RS_POR_PONTO - CUSTO_RS)
    contra = pd.Series(-bruto * RS_POR_PONTO - CUSTO_RS)
    m_segue = segue.shift(1).rolling(janela, min_periods=minimo).mean().to_numpy()
    m_contra = contra.shift(1).rolling(janela, min_periods=minimo).mean().to_numpy()
    lado = np.where((m_segue > 0) & (m_segue >= m_contra), 1.0, np.where(m_contra > 0, -1.0, 0.0))
    s = np.zeros(len(m))
    s[idx] = base[idx] * np.nan_to_num(lado)
    return s

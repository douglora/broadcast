"""
Ferramentas de rigor estatistico (Marcos Lopez de Prado, "Advances in Financial Machine Learning") usadas pelo laboratorio.
Entraram em 10/10/2026, com o metodo de quant/pesquisa/METODO.md (Chan para a ideia e os custos; Lopez de Prado para nao
se enganar). Nada aqui cria vantagem: serve para medir quanto de um resultado e acaso.

  sharpe_anual(r)                       Sharpe anualizado de uma serie de retornos por pregao
  psr(r, sr_ref=0)                      probabilidade de o Sharpe verdadeiro ser maior que sr_ref (corrige assimetria e caudas)
  sharpe_esperado_do_acaso(n, var)      o maior Sharpe que n tentativas sem vantagem produzem em media
  dsr(r, n_tentativas)                  Sharpe deflacionado: psr contra o maior Sharpe esperado do acaso
  queda_maxima(r)                       maior queda do acumulado (na mesma unidade de r)
  cpcv(dias, grupos=6, teste=2, embargo=1)   validacao cruzada combinatoria com purga por pregao e embargo
  barras_de_volume(m, contratos)        barras de volume fixo a partir das barras de 1 minuto (reinicia a cada pregao)
  retorno_por_pregao(negocios, dias, capital)   serie diaria (zero nos pregoes sem negocio) a partir dos negocios do lab
"""
import itertools
import math

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

EULER = 0.5772156649015329


def sharpe_anual(r, por_ano=252):
    r = np.asarray(r, dtype=float)
    return float(r.mean() / r.std(ddof=1) * math.sqrt(por_ano)) if len(r) > 2 and r.std(ddof=1) > 0 else 0.0


def psr(r, sr_ref=0.0):
    """Probabilistic Sharpe Ratio. `sr_ref` e `r` na mesma frequencia (Sharpe por periodo, nao anualizado)."""
    r = np.asarray(r, dtype=float)
    t = len(r)
    if t < 5 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    g3, g4 = float(skew(r)), float(kurtosis(r, fisher=False))
    den = math.sqrt(max(1e-12, 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr))
    return float(norm.cdf((sr - sr_ref) * math.sqrt(t - 1.0) / den))


def sharpe_esperado_do_acaso(n_tentativas, variancia_dos_sharpes):
    """O maior Sharpe (por periodo) esperado entre n tentativas cujo Sharpe verdadeiro e zero."""
    n = max(2, int(n_tentativas))
    return float(math.sqrt(variancia_dos_sharpes) * ((1.0 - EULER) * norm.ppf(1.0 - 1.0 / n) + EULER * norm.ppf(1.0 - 1.0 / (n * math.e))))


def dsr(r, n_tentativas, variancia_dos_sharpes=None):
    """Deflated Sharpe Ratio: probabilidade de o Sharpe ser verdadeiro DEPOIS de descontar que n tentativas foram olhadas.
    Sem a variancia observada entre as tentativas, usa a do estimador sob o nulo: 1 / (T - 1)."""
    r = np.asarray(r, dtype=float)
    v = variancia_dos_sharpes if variancia_dos_sharpes is not None else 1.0 / max(1, len(r) - 1)
    return psr(r, sharpe_esperado_do_acaso(n_tentativas, v))


def queda_maxima(r):
    ac = np.cumsum(np.asarray(r, dtype=float))
    return float((ac - np.maximum.accumulate(ac)).min()) if len(ac) else 0.0


def retorno_por_pregao(negocios, dias, capital=100_000.0, coluna="res"):
    """Serie por pregao, em fracao do capital, com zero nos pregoes sem negocio. `negocios`: saida de lab.medir."""
    por_dia = negocios.groupby("dia")[coluna].sum() if len(negocios) else pd.Series(dtype=float)
    return (por_dia.reindex(sorted(set(dias)), fill_value=0.0) / capital).astype(float)


def cpcv(dias, grupos=6, teste=2, embargo=1):
    """Combinatorial Purged Cross-Validation por PREGAO. `dias`: os pregoes (ordenados, unicos). Divide em `grupos` blocos
    seguidos; cada combinacao de `teste` blocos e um teste, e o treino e o resto menos `embargo` pregoes de cada lado de cada
    bloco de teste (purga: rotulo de day trade nao passa do pregao, entao purgar por pregao basta). Gera (treino, teste)."""
    dias = np.array(sorted(set(dias)))
    blocos = np.array_split(np.arange(len(dias)), grupos)
    for combo in itertools.combinations(range(grupos), teste):
        idx_teste = np.concatenate([blocos[k] for k in combo])
        proibido = set(idx_teste.tolist())
        for k in combo:
            a, b = blocos[k][0], blocos[k][-1]
            proibido.update(range(max(0, a - embargo), a))
            proibido.update(range(b + 1, min(len(dias), b + 1 + embargo)))
        idx_treino = np.array([i for i in range(len(dias)) if i not in proibido])
        yield dias[idx_treino], dias[idx_teste]


def barras_de_volume(m, contratos):
    """Barras de volume fixo: fecha uma barra cada vez que o volume acumulado do pregao passa de um multiplo de `contratos`.
    Usa so barras de 1 minuto ja fechadas; a hora da barra e a do minuto em que ela fechou. Reinicia a cada pregao."""
    d = np.asarray(m.index.date)
    ac = m.groupby(d)["v"].cumsum().to_numpy()
    k = np.floor(ac / float(contratos)).astype(int)
    grupo = pd.Series(d).astype(str).to_numpy() + "_" + k.astype(str)
    g = m.groupby(grupo, sort=False)
    out = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(), "n": g["n"].sum(), "v": g["v"].sum()})
    out.index = pd.DatetimeIndex(g.apply(lambda x: x.index[-1]).to_numpy(), name="hora")
    return out

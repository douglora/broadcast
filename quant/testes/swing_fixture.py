"""Painel sintetico para os testes do swing: precos conhecidos, sem rede e sem banco."""
import numpy as np
import pandas as pd

from quant.swing.dados import Painel


def painel_sintetico(n=320, tickers=("AAAA3", "BBBB3", "CCCC3"), seed=1, fim="2026-10-09", preco0=20.0, vol=0.02, adtv=2e7):
    """Passeio aleatorio por papel (abertura perto do fechamento anterior, maxima/minima em volta), mais a coluna BOVA11 no fim.
    Tudo no universo, metade de cima do ranking e Ibovespa acima da media de 200 verdadeiros. Datas: dias uteis terminando em `fim`."""
    rng = np.random.default_rng(seed)
    datas = pd.bdate_range(end=fim, periods=n)
    cols = list(tickers) + ["BOVA11"]
    k = len(cols)
    ret = rng.normal(0.0003, vol, size=(n, k))
    C = preco0 * np.exp(np.cumsum(ret, axis=0))
    cprev = np.vstack([C[:1], C[:-1]])
    O = cprev * (1.0 + rng.normal(0, vol / 4, size=(n, k)))
    H = np.maximum(O, C) * (1.0 + np.abs(rng.normal(0, vol / 3, size=(n, k))))
    L = np.minimum(O, C) * (1.0 - np.abs(rng.normal(0, vol / 3, size=(n, k))))
    V = np.full((n, k), float(adtv))
    uni = np.ones((n, k), dtype=bool)
    uni[:, -1] = False
    return Painel(datas=datas, tickers=cols, O=O, H=H, L=L, C=C, V=V, ruim=np.zeros((n, k), dtype=bool), uni=uni, adtv=np.full((n, k), float(adtv)),
                  top=np.ones((n, k), dtype=bool), ibov_ok=np.ones(n, dtype=bool), ibov_c=C[:, -1].copy(), cdi=np.full(n, 0.0004), preco_cru=C.copy(), cd_cvm={})


def painel_plano(datas, tickers=("AAAA3",), preco=20.0):
    """Painel com precos constantes (abertura = maxima = minima = fechamento = preco): o teste muda as barras que quiser."""
    datas = pd.DatetimeIndex(datas)
    n, cols = len(datas), list(tickers) + ["BOVA11"]
    M = np.full((n, len(cols)), float(preco))
    return Painel(datas=datas, tickers=cols, O=M.copy(), H=M.copy(), L=M.copy(), C=M.copy(), V=np.full((n, len(cols)), 1e7), ruim=np.zeros((n, len(cols)), dtype=bool),
                  uni=np.ones((n, len(cols)), dtype=bool), adtv=np.full((n, len(cols)), 2e7), top=np.ones((n, len(cols)), dtype=bool), ibov_ok=np.ones(n, dtype=bool),
                  ibov_c=M[:, -1].copy(), cdi=np.full(n, 0.0004), preco_cru=M.copy(), cd_cvm={})


def barra(p, ticker, dia, o=None, h=None, l=None, c=None):
    """Troca a barra de um dia (string AAAA-MM-DD) de um papel do painel."""
    i = int(np.searchsorted(p.datas.values, np.datetime64(pd.Timestamp(dia))))
    j = p.tickers.index(ticker)
    for nome, v in (("O", o), ("H", h), ("L", l), ("C", c)):
        if v is not None:
            getattr(p, nome)[i, j] = v
    if c is not None:
        p.preco_cru[i, j] = c
    return p

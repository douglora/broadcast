"""
Tabela diaria de regime macro e micro, ponto a ponto no tempo: o valor atribuido ao dia D so usa fechamentos ate D-1
(nada do proprio dia vaza para o sinal). Le as series diarias que o terminal guarda em cache/out/hist (so leitura, via
quant.observacao.fontes), todas desde 10/2021, o que cobre a descoberta e a validacao do laboratorio.

Uso nos estudos: `f = regimes.tabela()`; `f.loc[dia]` da o estado conhecido na abertura do dia. Nenhuma regra aqui:
e insumo para condicionar e para medir (so medindo), nunca para operar sozinha.
"""
import numpy as np
import pandas as pd

from quant.observacao import fontes

SERIES = {"vix": ("VIX", "c"), "dxy": ("DXY", "c"), "ust10": ("UST10Y", "c"), "brent": ("BRENT", "c"), "usdbrl": ("USDBRL", "c"),
          "ibov": ("IBOV", "c"), "spy": ("SPY", "c"), "ewz": ("EWZ", "c"), "hyg": ("HYG", "c"), "ouro": ("OURO", "c"),
          "ntnb35": ("TD-IPCA-2035", "tx"), "smll": ("SMLL", "c")}
COLUNAS_REGIME = ("regime_vol", "dolar_tend", "risco_score")


def _ret(s, n):
    return s.pct_change(n) * 100.0


def brutas(series=None):
    """As series diarias alinhadas num calendario unico (uniao das datas), cada uma arrastada por ate 5 dias (feriados
    diferentes entre B3 e EUA)."""
    base = {k: fontes.serie(sym, campo) for k, (sym, campo) in (series or SERIES).items()}
    base = {k: s for k, s in base.items() if len(s)}
    if not base:
        return pd.DataFrame()
    idx = pd.DatetimeIndex(sorted(set().union(*[set(s.index) for s in base.values()])))
    df = pd.DataFrame(index=idx)
    for k, s in base.items():
        df[k] = s.reindex(idx).ffill(limit=5)
    return df


def tabela(de="2021-10-01", ate=None, df=None):
    """Caracteristicas (todas conhecidas na abertura do dia) e regimes. Colunas em % salvo aviso."""
    df = brutas() if df is None else df
    if df.empty:
        return pd.DataFrame()
    f = pd.DataFrame(index=df.index)
    g = df.get
    if "vix" in df:
        f["vix_nivel"] = df.vix
        f["vix_var10"] = _ret(df.vix, 10)
    if "dxy" in df:
        f["dxy_ret5"] = _ret(df.dxy, 5)
        f["dxy_ret20"] = _ret(df.dxy, 20)
    if "ust10" in df:
        f["ust10_chg10"] = df.ust10.diff(10)                      # pontos percentuais
    if "brent" in df:
        f["brent_ret10"] = _ret(df.brent, 10)
    if "usdbrl" in df:
        f["usdbrl_ret1"] = _ret(df.usdbrl, 1)
        f["usdbrl_ret5"] = _ret(df.usdbrl, 5)
        f["usdbrl_ret10"] = _ret(df.usdbrl, 10)
        f["usdbrl_vol20"] = df.usdbrl.pct_change().rolling(20).std() * 100.0 * np.sqrt(252)   # anualizada
        f["usdbrl_vs_mm50"] = (df.usdbrl / df.usdbrl.rolling(50).mean() - 1) * 100.0
    if "ibov" in df:
        f["ibov_ret5"] = _ret(df.ibov, 5)
        f["ibov_vs_mm200"] = (df.ibov / df.ibov.rolling(200).mean() - 1) * 100.0
        f["ibov_vol20"] = df.ibov.pct_change().rolling(20).std() * 100.0 * np.sqrt(252)
    if "spy" in df:
        f["spy_ret1"] = _ret(df.spy, 1)
        f["spy_ret5"] = _ret(df.spy, 5)
    if "ewz" in df and "spy" in df:
        f["ewz_spy_5"] = _ret(df.ewz, 5) - _ret(df.spy, 5)
    if "hyg" in df:
        f["hyg_ret5"] = _ret(df.hyg, 5)
    if "ouro" in df:
        f["ouro_ret10"] = _ret(df.ouro, 10)
    if "ntnb35" in df:
        f["ntnb35_chg10"] = df.ntnb35.diff(10)                    # pontos percentuais de taxa real
    if "smll" in df and "ibov" in df:
        f["smll_ibov_20"] = _ret(df.smll, 20) - _ret(df.ibov, 20)
    # regimes (rotulos simples, limiares fixos de antemao: nao sao ajustados aos dados)
    if "vix" in df:
        f["regime_vol"] = pd.cut(df.vix, [0, 15, 25, 1e9], labels=["calmo", "normal", "estresse"]).astype(object)
    if "dxy_ret20" in f:
        f["dolar_tend"] = np.sign(f.dxy_ret20)
    pontos = []
    for col, sentido in (("spy_ret5", 1), ("hyg_ret5", 1), ("dxy_ret5", -1), ("vix_var10", -1)):
        if col in f:
            pontos.append((np.sign(f[col]) * sentido > 0).astype(float).where(f[col].notna()))
    if pontos:
        f["risco_score"] = sum(pontos)                             # 0 (tudo avesso a risco) a 4 (tudo a favor)
    f = f.shift(1)                                                # ponto no tempo: dia D recebe o calculado ate D-1
    return f.loc[pd.Timestamp(de):(pd.Timestamp(ate) if ate else None)]


def no_dia(f, dias):
    """Linhas da tabela alinhadas a uma lista de dias (date ou Timestamp), arrastando ate 5 dias quando o dia nao existe."""
    idx = pd.DatetimeIndex(pd.to_datetime(list(dias)))
    return f.reindex(f.index.union(idx)).ffill(limit=5).reindex(idx)

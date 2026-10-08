"""Funcoes puras (pandas/numpy) usadas pelas regras e pelo renderizador.

Convencoes: series diarias ordenadas por data; 'adj' = fechamento ajustado
(dividendos e splits) para retornos e medias; 'close' = fechamento de tela
para niveis de preco. Janelas de retorno por DIAS CORRIDOS (7/30/182/365) e
YTD contra o ultimo fechamento do ano anterior, calculado por serie."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

JANELAS_DIAS = (("1s", 7), ("1m", 30), ("3m", 91), ("6m", 182), ("1a", 365))


def para_df(barras: list[list]) -> pd.DataFrame:
    """[[date, open, high, low, close, adj, volume], ...] -> DataFrame indexado por data."""
    if not barras:
        return pd.DataFrame(columns=["open", "high", "low", "close", "adj", "volume"])
    df = pd.DataFrame(barras, columns=["data", "open", "high", "low", "close", "adj", "volume"])
    df["data"] = pd.to_datetime(df["data"])
    df = df.drop_duplicates("data", keep="last").sort_values("data").set_index("data")
    for c in ("open", "high", "low", "close", "adj", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["adj"] = df["adj"].fillna(df["close"])
    return df.dropna(subset=["close"])


def de_precos(dates: list[str], prices: list[float]) -> pd.DataFrame:
    """Fixtures antigas (so dates/prices) -> DataFrame com open=high=low=close=adj."""
    return para_df([[d, p, p, p, p, p, 0] for d, p in zip(dates, prices)])


# ---------------------------------------------------------------- retornos
def _ref(df: pd.DataFrame, alvo: pd.Timestamp):
    """Ultima linha com data <= alvo (None se nao houver)."""
    sub = df.loc[:alvo]
    return sub.iloc[-1] if len(sub) else None


def janelas(df: pd.DataFrame, ate: date | None = None, col: str = "adj") -> dict:
    """Retornos dia/1s/1m/6m/1a/ytd em fracao, alem de ultimo/anterior e datas."""
    if df is None or len(df) == 0:
        return {}
    if ate is not None:
        df = df.loc[:pd.Timestamp(ate)]
        if len(df) == 0:
            return {}
    ultimo = df.iloc[-1]
    d_ult = df.index[-1]
    out = {"data": d_ult.date().isoformat(), "ultimo": float(ultimo["close"]),
           "ultimo_adj": float(ultimo[col])}
    if len(df) >= 2:
        ant = df.iloc[-2]
        out["anterior"] = float(ant["close"])
        out["data_anterior"] = df.index[-2].date().isoformat()
        out["dia"] = float(ultimo[col] / ant[col] - 1) if ant[col] else None
    for nome, dias in JANELAS_DIAS:
        ref = _ref(df, d_ult - pd.Timedelta(days=dias))
        out[nome] = float(ultimo[col] / ref[col] - 1) if ref is not None and ref[col] else None
    base = _ref(df, pd.Timestamp(year=d_ult.year - 1, month=12, day=31))
    out["ytd"] = float(ultimo[col] / base[col] - 1) if base is not None and base[col] else None
    return out


def retorno_em(df, dias: int, ate: date | None = None, col: str = "adj"):
    """Retorno sobre a barra mais proxima de `dias` corridos atras.

    Usado com a serie semanal longa para janelas que a serie diaria (2 anos) nao
    alcanca, como 5 anos. Devolve None quando o historico nao chega la - o ativo
    novo fica com a celula vazia em vez de um numero errado."""
    if df is None or len(df) == 0:
        return None
    if ate is not None:
        df = df.loc[:pd.Timestamp(ate)]
        if len(df) == 0:
            return None
    ultimo = df.iloc[-1]
    ref = _ref(df, df.index[-1] - pd.Timedelta(days=dias))
    if ref is None or not ref[col] or ref.name == df.index[-1]:
        return None
    # a serie tem de comecar antes da janela; senao 5 anos viraria "desde o inicio"
    if df.index[0] > pd.Timestamp(df.index[-1]) - pd.Timedelta(days=dias * 0.9):
        return None
    return float(ultimo[col] / ref[col] - 1)


def retorno_longo(df_longo, df_diario, dias: int, ate: date | None = None, col: str = "adj"):
    """Janela longa (5 anos) com a base na serie SEMANAL e o numerador na ultima barra
    DIARIA ate `ate`. A semanal da semana corrente pode ser um toco (em 23/09 a
    semanal do Brent era a sessao seguinte, 97,83); a diaria ja passou pelo portao."""
    if df_longo is None or len(df_longo) == 0 or df_diario is None or len(df_diario) == 0:
        return None
    d = df_diario.loc[:pd.Timestamp(ate)] if ate is not None else df_diario
    if len(d) == 0:
        return None
    fim = d.index[-1]
    ref = _ref(df_longo, fim - pd.Timedelta(days=dias))
    if ref is None or not ref[col]:
        return None
    if df_longo.index[0] > fim - pd.Timedelta(days=dias * 0.9):
        return None
    return float(d[col].iloc[-1] / ref[col] - 1)


# ---------------------------------------------------------------- tecnicos
def mm(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi_wilder(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    ganho = delta.clip(lower=0.0)
    perda = (-delta).clip(lower=0.0)
    mg = ganho.ewm(alpha=1.0 / n, min_periods=n, adjust=False).mean()
    mp = perda.ewm(alpha=1.0 / n, min_periods=n, adjust=False).mean()
    rs = mg / mp.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi.where(mp != 0.0, 100.0)


def retornos_log(s: pd.Series) -> pd.Series:
    return np.log(s / s.shift(1))


def sigma_ex(s: pd.Series, n: int = 20) -> pd.Series:
    """Desvio-padrao dos n retornos ANTERIORES (exclui o dia), alinhado ao dia."""
    r = retornos_log(s)
    return r.shift(1).rolling(n, min_periods=n).std()


def zscore_dia(s: pd.Series, n: int = 20, piso: float = 0.0) -> pd.Series:
    r = retornos_log(s)
    sig = sigma_ex(s, n).clip(lower=piso) if piso else sigma_ex(s, n)
    return r / sig


def vol_anualizada(s: pd.Series, n: int = 20) -> float | None:
    r = retornos_log(s).dropna()
    if len(r) < n:
        return None
    return float(r.iloc[-n:].std() * math.sqrt(252))


def drawdown(s: pd.Series, janela: int = 252) -> tuple[float | None, float | None, str | None]:
    """(dd em fracao, pico, data do pico) sobre a janela de sessoes."""
    if len(s) == 0:
        return None, None, None
    sub = s.iloc[-janela:]
    pico = float(sub.max())
    data_pico = sub.idxmax()
    return float(sub.iloc[-1] / pico - 1.0), pico, data_pico.date().isoformat()


def max_min(s: pd.Series, janela: int = 252) -> dict:
    sub = s.iloc[-janela:]
    return {"max": float(sub.max()), "data_max": sub.idxmax().date().isoformat(),
            "min": float(sub.min()), "data_min": sub.idxmin().date().isoformat(),
            "n": int(len(sub))}


def sequencia(s: pd.Series, tolerancia: float = 0.0005) -> tuple[int, float]:
    """(n, acumulado): fechamentos consecutivos na mesma direcao; dias com |r| <
    tolerancia nem somam nem quebram. n > 0 = altas, n < 0 = quedas."""
    r = (s / s.shift(1) - 1.0).dropna()
    n, sinal, acum = 0, 0, 0.0
    for v in reversed(r.values.tolist()):
        if abs(v) < tolerancia:
            continue
        sg = 1 if v > 0 else -1
        if sinal == 0:
            sinal = sg
        if sg != sinal:
            break
        n += 1
        acum = (1 + acum) * (1 + v) - 1 if n > 1 else v
    return n * sinal, acum


def inclinacao(s: pd.Series, n: int = 20) -> float | None:
    """Variacao relativa da serie em n sessoes (para 'MM200 ascendente/descendente')."""
    s = s.dropna()
    if len(s) <= n:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1.0)


def forca_relativa(a: pd.Series, b: pd.Series) -> pd.Series:
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1, sort=True).dropna()
    return df["a"] / df["b"]


def retorno_n(s: pd.Series, n: int) -> float | None:
    s = s.dropna()
    if len(s) <= n:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1.0)


# ---------------------------------------------------------------- curvas
def bps(a: float | None, b: float | None) -> float | None:
    """(a - b) em pontos-base, para taxas em % (14,05 -> 14,20 = +15 bps)."""
    if a is None or b is None:
        return None
    return round((a - b) * 100.0, 2)


def dv01_empirico(taxas: list[float], pus: list[float]) -> float | None:
    """Sensibilidade media |dPU/PU| por 10 bps, estimada das ultimas variacoes."""
    pares = [(t1, t0, p1, p0) for (t0, t1, p0, p1) in zip(taxas, taxas[1:], pus, pus[1:])
             if t0 and t1 and p0 and p1 and abs(t1 - t0) >= 0.02]
    if not pares:
        return None
    vals = [abs((p1 / p0 - 1.0) / ((t1 - t0) * 10.0)) for t1, t0, p1, p0 in pares]
    vals = sorted(vals)[len(vals) // 4: max(len(vals) * 3 // 4, len(vals) // 4 + 1)] or vals
    return float(np.mean(vals))


def percentil(historico: list[float], valor: float) -> float | None:
    """Percentil (0-100) de 'valor' na serie historica."""
    h = [x for x in historico if x is not None]
    if not h:
        return None
    return float(100.0 * sum(1 for x in h if x <= valor) / len(h))


def breakeven(pre: float, real: float) -> float:
    """Inflacao implicita (% a.a.) entre prefixado e IPCA+."""
    return ((1 + pre / 100.0) / (1 + real / 100.0) - 1.0) * 100.0


def beta(y: pd.Series, x: pd.Series, n: int = 60) -> float | None:
    df = pd.concat([retornos_log(y).rename("y"), retornos_log(x).rename("x")], axis=1, sort=True).dropna().iloc[-n:]
    if len(df) < n // 2 or df["x"].var() == 0:
        return None
    return float(df["y"].cov(df["x"]) / df["x"].var())


def cruzou(serie_a: pd.Series, serie_b: pd.Series, banda: float = 0.0) -> str | None:
    """'baixo' se a ultima barra tem a < b*(1-banda) e a anterior >= b*(1-banda); 'cima' espelho."""
    a, b = serie_a.dropna(), serie_b.dropna()
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if len(df) < 2:
        return None
    hoje, ontem = df.iloc[-1], df.iloc[-2]
    if hoje["a"] < hoje["b"] * (1 - banda) and ontem["a"] >= ontem["b"] * (1 - banda):
        return "baixo"
    if hoje["a"] > hoje["b"] * (1 + banda) and ontem["a"] <= ontem["b"] * (1 + banda):
        return "cima"
    return None


def dias_abaixo(serie_a: pd.Series, serie_b: pd.Series, banda: float = 0.0) -> int:
    """Quantas sessoes consecutivas (contando a ultima) a < b*(1-banda); negativo se acima de b*(1+banda)."""
    df = pd.concat([serie_a.rename("a"), serie_b.rename("b")], axis=1).dropna()
    n = 0
    for _, row in df[::-1].iterrows():
        if row["a"] < row["b"] * (1 - banda):
            if n < 0:
                break
            n += 1
        elif row["a"] > row["b"] * (1 + banda):
            if n > 0:
                break
            n -= 1
        else:
            break
    return n

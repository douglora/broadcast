"""
Black-Scholes proprio (europeu, com rendimento continuo q opcional) para o modulo de opcoes.

Convencoes (as mesmas da calculadora do terminal, src/js/57-derivativos.js, e do coletor/opcoes.py):
  s      preco do ativo-objeto
  k      preco de exercicio
  t      prazo em ANOS (dias uteis / 252)
  r      juro CONTINUO ao ano: ln(1 + taxa)   -> use `juro_continuo(taxa_aa)`
  sig    volatilidade ao ano, em fracao (0,30 = 30%)
  put    True para put, False para call
  q      rendimento de dividendos continuo (padrao 0: as series da B3 sao protegidas, o strike e ajustado por provento)

Unidades das gregas (iguais as da tela do terminal):
  delta   variacao do premio por R$ 1 do ativo
  gama    variacao do delta por R$ 1 do ativo
  vega    variacao do premio por 1 PONTO de volatilidade (1 p.p.)
  teta    variacao do premio por DIA UTIL (teta anual / 252)

Nada aqui e recomendacao. Funcoes puras, sem rede, sem estado. Aceitam escalares; as versoes `*_vet` aceitam arrays.
"""
import math

import numpy as np
from scipy.special import ndtr  # normal acumulada vetorizada

DIAS_UTEIS_ANO = 252.0
SIG_MIN = 0.01        # 1% a.a.  (mesmo piso do terminal)
SIG_MAX = 5.0         # 500% a.a. (mesmo teto do terminal)


def juro_continuo(taxa_aa):
    """Taxa efetiva anual (0,1365 = 13,65%) -> juro continuo ln(1 + taxa)."""
    return math.log1p(taxa_aa)


def _cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1d2(s, k, t, r, sig, q=0.0):
    v = sig * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q) * t) / v + 0.5 * v
    return d1, d1 - v


def preco(s, k, t, r, sig, put, q=0.0):
    """Premio de Black-Scholes. Com t <= 0 ou sig <= 0 devolve o valor intrinseco."""
    if t <= 0 or sig <= 0:
        return max(k - s, 0.0) if put else max(s - k, 0.0)
    d1, d2 = _d1d2(s, k, t, r, sig, q)
    sq, kd = s * math.exp(-q * t), k * math.exp(-r * t)
    return kd * _cdf(-d2) - sq * _cdf(-d1) if put else sq * _cdf(d1) - kd * _cdf(d2)


def delta(s, k, t, r, sig, put, q=0.0):
    if t <= 0 or sig <= 0:
        return (-1.0 if s < k else 0.0) if put else (1.0 if s > k else 0.0)
    d1, _ = _d1d2(s, k, t, r, sig, q)
    eq = math.exp(-q * t)
    return eq * (_cdf(d1) - 1.0) if put else eq * _cdf(d1)


def gama(s, k, t, r, sig, q=0.0):
    """Igual para call e put."""
    if t <= 0 or sig <= 0:
        return 0.0
    d1, _ = _d1d2(s, k, t, r, sig, q)
    return math.exp(-q * t) * _pdf(d1) / (s * sig * math.sqrt(t))


def vega(s, k, t, r, sig, q=0.0):
    """Por PONTO de volatilidade (divide o vega por 100)."""
    if t <= 0 or sig <= 0:
        return 0.0
    d1, _ = _d1d2(s, k, t, r, sig, q)
    return s * math.exp(-q * t) * _pdf(d1) * math.sqrt(t) / 100.0


def teta(s, k, t, r, sig, put, q=0.0):
    """Por DIA UTIL (teta anual / 252)."""
    if t <= 0 or sig <= 0:
        return 0.0
    d1, d2 = _d1d2(s, k, t, r, sig, q)
    raiz = math.sqrt(t)
    base = -s * math.exp(-q * t) * _pdf(d1) * sig / (2.0 * raiz)
    kd = k * math.exp(-r * t)
    if put:
        anual = base + r * kd * _cdf(-d2) - q * s * math.exp(-q * t) * _cdf(-d1)
    else:
        anual = base - r * kd * _cdf(d2) + q * s * math.exp(-q * t) * _cdf(d1)
    return anual / DIAS_UTEIS_ANO


def gregas(s, k, t, r, sig, put, q=0.0):
    """Dicionario com delta, gama, vega (por ponto) e teta (por dia util)."""
    return {"delta": delta(s, k, t, r, sig, put, q), "gama": gama(s, k, t, r, sig, q),
            "vega": vega(s, k, t, r, sig, q), "teta": teta(s, k, t, r, sig, put, q)}


def vol_implicita(premio, s, k, t, r, put, q=0.0, tol=1e-8):
    """Volatilidade que explica o premio (Newton com salvaguarda de bissecao). None quando nao ha resposta:
    premio <= 0, abaixo do piso (valor intrinseco descontado) ou acima do teto de volatilidade."""
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (premio, s, k, t, r)):
        return None
    if premio <= 0 or s <= 0 or k <= 0 or t <= 0:
        return None
    lo, hi = SIG_MIN, SIG_MAX
    if preco(s, k, t, r, lo, put, q) >= premio or preco(s, k, t, r, hi, put, q) <= premio:
        return None
    sig = 0.30
    for _ in range(60):
        p = preco(s, k, t, r, sig, put, q)
        dif = p - premio
        if abs(dif) < tol:
            return sig
        if dif > 0:
            hi = min(hi, sig)
        else:
            lo = max(lo, sig)
        vg = vega(s, k, t, r, sig, q) * 100.0
        novo = sig - dif / vg if vg > 1e-12 else 0.5 * (lo + hi)
        sig = novo if lo < novo < hi else 0.5 * (lo + hi)
    return sig if abs(preco(s, k, t, r, sig, put, q) - premio) < 1e-5 else None


# ---------------------------------------------------------------- versoes vetorizadas (a base inteira de uma vez)
def preco_vet(s, k, t, r, sig, put, q=0.0):
    s, k, t, r, sig = (np.asarray(x, dtype=float) for x in (s, k, t, r, sig))
    put = np.asarray(put, dtype=bool)
    with np.errstate(all="ignore"):
        v = sig * np.sqrt(t)
        d1 = (np.log(s / k) + (r - q) * t) / v + 0.5 * v
        d2 = d1 - v
        sq, kd = s * np.exp(-q * t), k * np.exp(-r * t)
        p = np.where(put, kd * ndtr(-d2) - sq * ndtr(-d1), sq * ndtr(d1) - kd * ndtr(d2))
        intr = np.where(put, np.maximum(k - s, 0.0), np.maximum(s - k, 0.0))
    return np.where((t <= 0) | (sig <= 0), intr, p)


def delta_vet(s, k, t, r, sig, put, q=0.0):
    s, k, t, r, sig = (np.asarray(x, dtype=float) for x in (s, k, t, r, sig))
    put = np.asarray(put, dtype=bool)
    with np.errstate(all="ignore"):
        v = sig * np.sqrt(t)
        d1 = (np.log(s / k) + (r - q) * t) / v + 0.5 * v
        eq = np.exp(-q * t)
        d = np.where(put, eq * (ndtr(d1) - 1.0), eq * ndtr(d1))
    return d


def vol_implicita_vet(premio, s, k, t, r, put, q=0.0, iteracoes=60):
    """Bissecao vetorizada (entre SIG_MIN e SIG_MAX). NaN onde nao ha resposta."""
    premio, s, k, t, r = (np.asarray(x, dtype=float) for x in (premio, s, k, t, r))
    put = np.broadcast_to(np.asarray(put, dtype=bool), premio.shape)
    lo = np.full(premio.shape, SIG_MIN)
    hi = np.full(premio.shape, SIG_MAX)
    p_lo = preco_vet(s, k, t, r, lo, put, q)
    p_hi = preco_vet(s, k, t, r, hi, put, q)
    ok = (premio > 0) & (s > 0) & (k > 0) & (t > 0) & (p_lo < premio) & (p_hi > premio)
    for _ in range(iteracoes):
        meio = 0.5 * (lo + hi)
        acima = preco_vet(s, k, t, r, meio, put, q) > premio
        hi = np.where(acima, meio, hi)
        lo = np.where(acima, lo, meio)
    return np.where(ok, 0.5 * (lo + hi), np.nan)

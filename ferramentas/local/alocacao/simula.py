"""Simulacao de Monte Carlo do patrimonio ao longo do tempo.

Mensal, retornos com cauda gorda (t de Student, 6 graus de liberdade, choque comum entre as classes para que a
crise derrube tudo junto), correlacao e volatilidade de risco.py, retorno medio liquido de premissas.py.
Mais um deslocamento persistente do nivel do CDI por trajetoria (risco de reinvestimento do que rende CDI).
Aportes, retiradas e eventos entram em reais de hoje e crescem com o IPCA esperado; a meta e em reais de hoje.
Rebalanceia para a carteira alvo uma vez por ano. Imposto ja esta dentro do retorno liquido (nao ha venda
forcada modelada). Mesma entrada, mesmo resultado (semente fixa).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import config as C
from . import risco as R


@dataclass
class Plano:
    pl: float                              # patrimonio financeiro a alocar, R$
    horizonte: float                       # anos
    aporte_mensal: float = 0.0             # R$ de hoje por mes (negativo = retirada)
    eventos: list = field(default_factory=list)   # [{"mes": 18, "valor": -300000, "desc": "..."}], R$ de hoje
    meta: float | None = None              # patrimonio desejado no fim, R$ de hoje
    rebalancear_meses: int = 12


def _fluxos(plano: Plano, T: int, ipca: float) -> np.ndarray:
    """Fluxo nominal de cada mes (1..T)."""
    f = np.zeros(T + 1)
    for t in range(1, T + 1):
        infl = (1.0 + ipca) ** (t / 12.0)
        f[t] += plano.aporte_mensal * infl
    for e in plano.eventos:
        t = int(e.get("mes", 0))
        if 1 <= t <= T:
            f[t] += float(e["valor"]) * (1.0 + ipca) ** (t / 12.0)
    return f


def retorno_necessario(plano: Plano, ipca: float) -> float | None:
    """CAGR nominal constante que leva `pl` com os fluxos do plano exatamente a meta (em reais de hoje inflada).
    None se nao ha meta. Pode ser negativo (a meta ja esta atendida so com os aportes)."""
    if plano.meta is None:
        return None
    T = max(int(round(plano.horizonte * 12)), 1)
    fluxos = _fluxos(plano, T, ipca)
    alvo = plano.meta * (1.0 + ipca) ** (T / 12.0)

    def final(r_aa: float) -> float:
        rm = (1.0 + r_aa) ** (1.0 / 12.0) - 1.0
        v = plano.pl
        for t in range(1, T + 1):
            v = v * (1.0 + rm) + fluxos[t]
        return v

    a, b = -0.5, 1.0
    if final(b) < alvo:
        return None
    for _ in range(80):
        m = 0.5 * (a + b)
        if final(m) < alvo:
            a = m
        else:
            b = m
    return 0.5 * (a + b)


def simular(w: np.ndarray, mu: np.ndarray, cov_mtm: np.ndarray, plano: Plano, ipca: float,
            n: int = 10000, semente: int = C.SEMENTE, gl: int = 6, sigma_juros: float = R.SIGMA_NIVEL_JUROS,
            benchmark: float | None = None) -> dict:
    """Roda `n` trajetorias e devolve percentis, probabilidades e estatisticas de risco."""
    T = max(int(round(plano.horizonte * 12)), 1)
    k = len(w)
    rng = np.random.default_rng(semente)
    w = np.asarray(w, dtype=float)
    w = w / w.sum()
    mu_m = (1.0 + mu) ** (1.0 / 12.0) - 1.0
    cm = np.asarray(cov_mtm) / 12.0
    L = np.linalg.cholesky(cm + 1e-12 * np.eye(k))
    b_j = R.sens_cdi()
    desl = rng.normal(0.0, sigma_juros, n)               # deslocamento persistente do CDI (a.a.) por trajetoria
    fluxos = _fluxos(plano, T, ipca)
    fator_t = np.sqrt((gl - 2.0) / gl)

    V = np.tile(w * plano.pl, (n, 1))
    riqueza = np.empty((n, T + 1), dtype=np.float32)
    indice = np.empty((n, T + 1), dtype=np.float32)
    riqueza[:, 0] = plano.pl
    indice[:, 0] = 1.0
    idx = np.ones(n)
    arruinado = np.zeros(n, dtype=bool)
    for t in range(1, T + 1):
        chi = rng.chisquare(gl, n) / gl
        z = rng.standard_normal((n, k)) @ L.T
        eps = z / np.sqrt(chi)[:, None] * fator_t
        r = mu_m + eps + desl[:, None] * b_j[None, :] / 12.0
        np.clip(r, -0.90, 3.0, out=r)
        antes = V.sum(axis=1)
        V *= (1.0 + r)
        depois = V.sum(axis=1)
        idx *= np.where(antes > 0, depois / np.maximum(antes, 1e-9), 1.0)
        f = fluxos[t]
        if f != 0.0:
            if f > 0:
                V += f * w[None, :]
            else:
                tot = V.sum(axis=1, keepdims=True)
                prop = np.where(tot > 0, V / np.maximum(tot, 1e-9), 0.0)
                V = np.maximum(V + f * prop, 0.0)
        total = V.sum(axis=1)
        arruinado |= total <= 1e-6
        if plano.rebalancear_meses and t % plano.rebalancear_meses == 0:
            V = total[:, None] * w[None, :]
        riqueza[:, t] = total
        indice[:, t] = idx

    infl_t = (1.0 + ipca) ** (np.arange(T + 1) / 12.0)
    real = riqueza / infl_t[None, :].astype(np.float32)
    pcts = [5, 25, 50, 75, 95]
    faixa_nom = {p: np.percentile(riqueza, p, axis=0) for p in pcts}
    faixa_real = {p: np.percentile(real, p, axis=0) for p in pcts}
    final_real = real[:, -1]
    anos = T / 12.0
    cagr = indice[:, -1] ** (1.0 / anos) - 1.0
    cagr_real = (1.0 + cagr) / (1.0 + ipca) - 1.0

    # queda maxima (pico a vale) do indice de retorno, sem o efeito dos aportes
    pico = np.maximum.accumulate(indice, axis=1)
    mdd = (indice / pico - 1.0).min(axis=1)

    # retornos moveis de 12 meses (todas as janelas de todas as trajetorias)
    if T >= 12:
        jan = (indice[:, 12:] / indice[:, :-12] - 1.0).ravel()
        var95 = float(np.percentile(jan, 5))
        cvar95 = float(jan[jan <= var95].mean())
        p_neg_12m = float((jan < 0).mean())
        p_abaixo_ipca = float((jan < ipca).mean())
    else:
        var95 = cvar95 = p_neg_12m = p_abaixo_ipca = float("nan")

    out = {
        "n": n, "meses": T, "anos": anos, "semente": semente, "gl": gl,
        "pcts": pcts, "faixa_nominal": faixa_nom, "faixa_real": faixa_real,
        "final_real": {p: float(np.percentile(final_real, p)) for p in pcts},
        "final_nominal": {p: float(np.percentile(riqueza[:, -1], p)) for p in pcts},
        "cagr_mediano": float(np.median(cagr)), "cagr_real_mediano": float(np.median(cagr_real)),
        "cagr_p5": float(np.percentile(cagr, 5)), "cagr_p95": float(np.percentile(cagr, 95)),
        "mdd_mediano": float(np.median(mdd)), "mdd_p95": float(np.percentile(mdd, 5)),  # 5% piores
        "var95_12m": var95, "cvar95_12m": cvar95, "p_neg_12m": p_neg_12m, "p_abaixo_ipca_12m": p_abaixo_ipca,
        "p_perde_poder_compra": float((cagr_real < 0).mean()),
        "p_ruina": float(arruinado.mean()),
        "p_meta": None, "meta_nominal": None,
        "p_abaixo_benchmark": None,
        "ipca": ipca, "pl": plano.pl,
    }
    if plano.meta is not None:
        out["p_meta"] = float((final_real >= plano.meta).mean())
        out["meta_nominal"] = plano.meta * (1.0 + ipca) ** anos
    if benchmark is not None:
        out["p_abaixo_benchmark"] = float((cagr < benchmark).mean())
    return out


def metricas_basicas(w: np.ndarray, mu: np.ndarray, cov: np.ndarray, ipca: float, benchmark: float) -> dict:
    """Numeros de uma pagina so (sem simulacao): retorno, volatilidade, retorno real, excesso sobre o caixa."""
    ret = float(w @ mu)
    vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
    return {"ret": ret, "vol": vol, "ret_real": (1.0 + ret) / (1.0 + ipca) - 1.0,
            "excesso": ret - benchmark, "sharpe": (ret - benchmark) / vol if vol > 0 else float("nan")}

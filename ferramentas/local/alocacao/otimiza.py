"""Otimizador de alocacao: media-variancia com bandas, teto de risco e ancora na carteira modelo.

So numpy. O problema e convexo: maximizar  retorno_liquido - (lambda/2)*variancia - (gamma/2)*|w - w0|^2
com  soma(w) = 1  e  banda_min <= w <= banda_max  por classe, mais um teto para a soma das classes de risco.
A solucao usa gradiente projetado acelerado (FISTA) com projecao exata no conjunto caixa-bandas-soma.

A ancora (w0 = carteira modelo do perfil, ou a carteira atual) existe porque o retorno esperado e incerto:
sem ela, qualquer diferenca pequena de premissa vira posicao de 40% numa classe so. `gamma` e o quanto a
mesa aceita se afastar do modelo; 0 = livre dentro das bandas (fronteira eficiente pura).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C


@dataclass
class Restricoes:
    lo: np.ndarray                       # banda minima por classe (ordem C.IDS)
    hi: np.ndarray                       # banda maxima por classe
    rv_max: float = 1.0                  # teto da soma das classes de risco
    vol_max: float | None = None         # orcamento de volatilidade anual
    w0: np.ndarray | None = None         # ancora
    gamma: float = 0.4                   # forca da ancora
    notas: list = field(default_factory=list)


def restricoes_do_perfil(perfil: str, override: dict | None = None, vol_max: float | None = None,
                         rv_max: float | None = None, gamma: float = 0.4,
                         w0: dict | None = None) -> Restricoes:
    """Bandas do perfil, ajustadas pelo que o cliente declarou (`override` = {classe: (min, max)}, em fracao)."""
    p = C.PERFIS[perfil]
    bandas = C.bandas_do_perfil(perfil)
    notas = []
    for cid, (a, b) in (override or {}).items():
        if cid in bandas:
            bandas[cid] = (float(a), float(b))
            notas.append(f"banda de {C.POR_ID[cid].curto} ajustada para {a*100:.0f}% a {b*100:.0f}% (ficha do cliente)")
    lo = np.array([bandas[c][0] for c in C.IDS])
    hi = np.array([bandas[c][1] for c in C.IDS])
    base = np.array([C.NEUTRO[perfil][c] for c in C.IDS]) if w0 is None else np.array([w0.get(c, 0.0) for c in C.IDS])
    return Restricoes(lo=lo, hi=hi, rv_max=p["rv_max"] if rv_max is None else rv_max,
                      vol_max=p["vol_alvo"] if vol_max is None else vol_max, w0=base, gamma=gamma, notas=notas)


def viabilidade(r: Restricoes) -> str | None:
    """None se existe carteira que cumpre as bandas e o teto de risco; senao, o motivo em portugues."""
    if np.any(r.lo > r.hi + 1e-12):
        i = int(np.argmax(r.lo - r.hi))
        return f"banda invertida em {C.POR_ID[C.IDS[i]].curto}"
    if r.lo.sum() > 1 + 1e-9:
        return f"as bandas minimas somam {r.lo.sum()*100:.0f}% (mais que 100%)"
    if r.hi.sum() < 1 - 1e-9:
        return f"as bandas maximas somam {r.hi.sum()*100:.0f}% (menos que 100%)"
    idx = [C.IDS.index(c) for c in C.GRUPO_RV]
    if r.lo[idx].sum() > r.rv_max + 1e-9:
        return (f"as bandas minimas de renda variavel somam {r.lo[idx].sum()*100:.0f}%, acima do teto de "
                f"{r.rv_max*100:.0f}% do perfil")
    return None


def projetar(v: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Projecao euclidiana de v em {lo <= w <= hi, soma(w) = 1} (bisecao no deslocamento)."""
    a = float(np.min(v - hi)) - 1.0
    b = float(np.max(v - lo)) + 1.0
    for _ in range(48):
        t = 0.5 * (a + b)
        s = float(np.clip(v - t, lo, hi).sum())
        if s > 1.0:
            a = t
        else:
            b = t
    return np.clip(v - 0.5 * (a + b), lo, hi)


def _fista(mu: np.ndarray, cov: np.ndarray, lam: float, gamma: float, w0: np.ndarray,
           lo: np.ndarray, hi: np.ndarray, penal: np.ndarray, w_ini: np.ndarray | None = None,
           iteracoes: int = 600) -> np.ndarray:
    """Resolve o QP convexo para um lambda e uma penalidade linear (`penal`) nas classes de risco."""
    n = len(mu)
    L = lam * float(np.linalg.eigvalsh(cov)[-1]) + gamma + 1e-9
    passo = 1.0 / L
    w = projetar(w0 if w_ini is None else w_ini, lo, hi)
    y, t = w.copy(), 1.0
    for _ in range(iteracoes):
        grad = -(mu - penal) + lam * (cov @ y) + gamma * (y - w0)
        w_novo = projetar(y - passo * grad, lo, hi)
        t_novo = 0.5 * (1.0 + np.sqrt(1.0 + 4.0 * t * t))
        y = w_novo + ((t - 1.0) / t_novo) * (w_novo - w)
        if np.max(np.abs(w_novo - w)) < 1e-10:
            w = w_novo
            break
        w, t = w_novo, t_novo
    return w


def _resolve_lambda(mu, cov, lam, r: Restricoes, gamma: float, w_ini: np.ndarray | None = None) -> np.ndarray:
    """QP para um lambda fixo, respeitando o teto de renda variavel (multiplicador por bisecao)."""
    idx = [C.IDS.index(c) for c in C.GRUPO_RV]
    ind = np.zeros(len(mu))
    ind[idx] = 1.0
    w0 = r.w0 if r.w0 is not None else projetar(np.full(len(mu), 1.0 / len(mu)), r.lo, r.hi)
    w = _fista(mu, cov, lam, gamma, w0, r.lo, r.hi, np.zeros(len(mu)), w_ini=w_ini)
    if float(w[idx].sum()) <= r.rv_max + 1e-9:
        return w
    a, b = 0.0, 1.0
    for _ in range(26):
        nu = 0.5 * (a + b)
        w = _fista(mu, cov, lam, gamma, w0, r.lo, r.hi, nu * ind, w_ini=w)
        if float(w[idx].sum()) > r.rv_max:
            a = nu
        else:
            b = nu
    return _fista(mu, cov, lam, gamma, w0, r.lo, r.hi, b * ind, w_ini=w)


def vol(w: np.ndarray, cov: np.ndarray) -> float:
    return float(np.sqrt(max(w @ cov @ w, 0.0)))


def otimizar(mu: np.ndarray, cov: pd.DataFrame | np.ndarray, r: Restricoes, vol_alvo: float | None = None,
             gamma: float | None = None) -> dict:
    """Carteira de maior retorno liquido com vol <= vol_alvo (default: o orcamento do perfil).
    Devolve {'w': ..., 'ok': bool, 'avisos': [...], 'lambda': ...}."""
    c = cov.values if hasattr(cov, "values") else np.asarray(cov)
    g = r.gamma if gamma is None else gamma
    alvo = r.vol_max if vol_alvo is None else vol_alvo
    motivo = viabilidade(r)
    if motivo:
        return {"w": None, "ok": False, "avisos": [f"sem solucao: {motivo}"], "lambda": None}
    avisos: list[str] = []
    # lambda minimo: se mesmo com pouca aversao o risco cabe no orcamento, nao ha o que apertar
    lam_lo, lam_hi = 1e-3, 1e3
    w_lo = _resolve_lambda(mu, c, lam_lo, r, g)
    if alvo is None or vol(w_lo, c) <= alvo + 1e-9:
        return {"w": w_lo, "ok": True, "avisos": avisos, "lambda": lam_lo}
    w_hi = _resolve_lambda(mu, c, lam_hi, r, g)
    if vol(w_hi, c) > alvo + 1e-9:
        avisos.append(f"mesmo no minimo de risco permitido pelas bandas a volatilidade fica em {vol(w_hi, c)*100:.1f}% "
                      f"(orcamento {alvo*100:.1f}%): afrouxe as bandas ou o orcamento")
        return {"w": w_hi, "ok": False, "avisos": avisos, "lambda": lam_hi}
    a, b = np.log(lam_lo), np.log(lam_hi)
    w, ult = w_hi, w_hi
    for _ in range(22):
        m = 0.5 * (a + b)
        w_m = _resolve_lambda(mu, c, float(np.exp(m)), r, g, w_ini=ult)
        ult = w_m
        if vol(w_m, c) > alvo:
            a = m
        else:
            b, w = m, w_m
    return {"w": w, "ok": True, "avisos": avisos, "lambda": float(np.exp(b))}


def fronteira(mu: np.ndarray, cov: pd.DataFrame, r: Restricoes, pontos: int = 14) -> list[dict]:
    """Fronteira eficiente dentro das bandas (sem ancora): maior retorno para cada volatilidade."""
    c = cov.values
    r0 = Restricoes(lo=r.lo, hi=r.hi, rv_max=r.rv_max, vol_max=None, w0=r.w0, gamma=0.01)
    w_min = _resolve_lambda(mu, c, 1e3, r0, 0.01)
    w_max = _resolve_lambda(mu, c, 1e-3, r0, 0.01)
    v0, v1 = vol(w_min, c), vol(w_max, c)
    out = []
    for alvo in np.linspace(v0, v1, pontos):
        res = otimizar(mu, c, r0, vol_alvo=float(alvo), gamma=0.01)
        if res["w"] is not None:
            w = res["w"]
            out.append({"vol": vol(w, c), "ret": float(w @ mu), "w": w})
    return out


def arredondar(w: np.ndarray, lo: np.ndarray, hi: np.ndarray, passo: float = 0.005) -> np.ndarray:
    """Arredonda para multiplos de `passo` (0,5 ponto) mantendo soma 100% e as bandas (maior resto)."""
    w = np.clip(w, lo, hi)
    base = np.floor(w / passo + 1e-9) * passo
    base = np.clip(base, lo, hi)
    falta = int(round((1.0 - base.sum()) / passo))
    resto = w - base
    ordem = np.argsort(-resto) if falta > 0 else np.argsort(resto)
    i = 0
    guarda = 0
    while falta != 0 and guarda < 10000:
        k = ordem[i % len(ordem)]
        if falta > 0 and base[k] + passo <= hi[k] + 1e-9:
            base[k] += passo
            falta -= 1
        elif falta < 0 and base[k] - passo >= lo[k] - 1e-9:
            base[k] -= passo
            falta += 1
        i += 1
        guarda += 1
    # banda fora da grade (ex.: piso de 9,6% em dolar) deixa um resto menor que o passo: a maior classe que comporta absorve
    resto_final = 1.0 - float(base.sum())
    if abs(resto_final) > 1e-12:
        folga = (hi - base) if resto_final > 0 else (base - lo)
        cabe = np.where(folga >= abs(resto_final) - 1e-12, base, -1.0)
        k = int(np.argmax(cabe)) if cabe.max() >= 0 else int(np.argmax(folga))
        base[k] += resto_final
    return base


def candidatos(mu: np.ndarray, cov: pd.DataFrame, r: Restricoes) -> list[dict]:
    """Tres pontos de partida para a conversa:
    A) ancorada no modelo do perfil (forca padrao); B) eficiente (livre nas bandas); C) defensiva (70% do risco)."""
    c = cov.values
    out = []
    vol_a = None
    specs = [
        ("A", "Ancorada no modelo do perfil", dict(gamma=r.gamma)),
        ("B", "Mais eficiente dentro das bandas", dict(gamma=0.02)),
        ("C", "Defensiva (70% do risco da A)", dict(gamma=r.gamma, fator=0.7)),
    ]
    for cod, nome, kw in specs:
        base = vol_a if (cod == "C" and vol_a is not None) else (r.vol_max or 1.0)
        alvo = base * kw.get("fator", 1.0)
        res = otimizar(mu, c, r, vol_alvo=alvo, gamma=kw["gamma"])
        if res["w"] is None:
            out.append({"cod": cod, "nome": nome, "w": None, "avisos": res["avisos"]})
            continue
        w = arredondar(res["w"], r.lo, r.hi)
        if cod == "A":
            vol_a = vol(w, c)
        out.append({"cod": cod, "nome": nome, "w": w, "vol": vol(w, c), "ret": float(w @ mu),
                    "avisos": res["avisos"], "ok": res["ok"]})
    return out


def para_dict(w: np.ndarray) -> dict:
    return {cid: float(w[i]) for i, cid in enumerate(C.IDS) if abs(w[i]) > 1e-9}


def de_dict(d: dict) -> np.ndarray:
    return np.array([float(d.get(cid, 0.0)) for cid in C.IDS])

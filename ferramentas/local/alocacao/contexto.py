"""Monta tudo que um cliente precisa (mercado, premissas, risco, restricoes) e avalia uma carteira.

`montar` junta a ficha, as visoes do Douglas e o retrato de mercado; `avaliar` pega uma carteira (pesos por
classe) e devolve os numeros que alimentam o alinhamento, o relatorio e a conversa: retorno, risco, simulacao,
estresse, contribuicao de risco, mapa fiscal, liquidez, moeda, juros e custos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import cenarios as K
from . import cliente as CL
from . import config as C
from . import fiscal as F
from . import mercado as M
from . import otimiza as O
from . import premissas as P
from . import risco as R
from . import simula as S


@dataclass
class Contexto:
    nome: str
    ficha: dict
    perfil: str
    horizonte: float
    mercado: M.Mercado
    prem: dict
    mu: np.ndarray
    cov: pd.DataFrame
    vol_cls: pd.Series
    corr: pd.DataFrame
    meta_risco: dict
    ipca: float
    bench: float
    plano: S.Plano
    restr: O.Restricoes
    visoes: list
    atual: dict | None
    curva: str = "viva"
    n_sim: int = 10000
    queda_limite: float = 0.09
    cenario_hoje: dict | None = None

    @property
    def w_modelo(self) -> np.ndarray:
        return np.array([C.NEUTRO[self.perfil][c] for c in C.IDS])


def montar(nome: str, curva: str = "viva", horizonte: float | None = None, n_sim: int = 10000,
           gamma: float = 0.4) -> Contexto:
    f = CL.ler_ficha(nome)
    perfil = CL.perfil_da_ficha(f)
    H = float(horizonte) if horizonte else CL.horizonte_da_ficha(f)
    visoes = CL.visoes_ativas(nome)
    mercado = M.carregar(curva=curva)
    prem = P.montar(mercado, H, visoes)
    cov, vol_cls, corr, meta = R.covariancia(H)
    mu = np.array([prem[c].liquido for c in C.IDS])
    ipca = mercado.ipca_esperado(H) / 100.0
    bench = P.benchmark_liquido(mercado, H, visoes)
    pl = float(f["patrimonio"].get("financeiro") or 1_000_000.0)
    plano = S.Plano(pl=pl, horizonte=H, aporte_mensal=float(f["fluxo"].get("aporte_mensal") or 0.0),
                    eventos=list(f["fluxo"].get("eventos") or []), meta=f["objetivo"].get("meta_patrimonio"))
    restr = O.restricoes_do_perfil(perfil, CL.bandas_override(f), gamma=gamma)
    qmax = f["risco"].get("queda_maxima_tolerada")
    limite = float(qmax) / 100.0 if qmax else C.PERFIS[perfil]["perda_12m"]
    return Contexto(nome=nome, ficha=f, perfil=perfil, horizonte=H, mercado=mercado, prem=prem, mu=mu, cov=cov,
                    vol_cls=vol_cls, corr=corr, meta_risco=meta, ipca=ipca, bench=bench, plano=plano, restr=restr,
                    visoes=visoes, atual=CL.ler_atual(nome), curva=curva, n_sim=n_sim, queda_limite=limite,
                    cenario_hoje=K.ler_extra())


def vetor(d: dict) -> np.ndarray:
    return O.de_dict(d)


def avaliar(ctx: Contexto, w: np.ndarray, rotulo: str = "") -> dict:
    """Todos os numeros de uma carteira, no horizonte e nas premissas do contexto."""
    w = np.asarray(w, dtype=float)
    w = w / w.sum()
    cov = ctx.cov.values
    ret = float(w @ ctx.mu)
    vol = O.vol(w, cov)
    bruto = float(sum(w[i] * ctx.prem[c].bruto_total for i, c in enumerate(C.IDS)))
    rc = R.contribuicao_risco(w, ctx.cov)
    enb = float(1.0 / np.sum(rc ** 2)) if np.sum(rc ** 2) > 0 else float("nan")
    mapa = F.mapa_irpfm({c: w[i] for i, c in enumerate(C.IDS)})
    sim = S.simular(w, ctx.mu, ctx.meta_risco["cov_mtm"].values, ctx.plano, ctx.ipca, n=ctx.n_sim, benchmark=ctx.bench)
    est = K.estresse(w, ctx.horizonte, ret, ctx.cenario_hoje)

    liq = {"d1": 0.0, "d5": 0.0, "d30": 0.0, "d90": 0.0, "mais": 0.0}
    for i, c in enumerate(C.IDS):
        d = C.POR_ID[c].liquidez_dias
        k = "d1" if d <= 1 else "d5" if d <= 5 else "d30" if d <= 30 else "d90" if d <= 90 else "mais"
        liq[k] += w[i]
    usd = float(sum(w[i] for i, c in enumerate(C.IDS) if C.POR_ID[c].moeda == "USD"))
    cdi_dep = float(sum(w[i] * R.SENS_CDI.get(c, 0.0) for i, c in enumerate(C.IDS)))
    travado = float(sum(w[i] for i, c in enumerate(C.IDS) if c in ("ipca_isenta", "ipca_trib", "pre_isenta", "pre_trib")))
    custo = float(sum(w[i] * C.CUSTO_AA.get(c, 0.0) for i, c in enumerate(C.IDS)))
    rv = float(sum(w[i] for i, c in enumerate(C.IDS) if c in C.GRUPO_RV))
    dur = R.duracoes(ctx.horizonte)
    duration = float(sum(w[i] * dur.get(c, 0.0) for i, c in enumerate(C.IDS)))
    # parte dos bancos com FGC: convencao (60% da renda fixa de emissor bancario/credito e FGC-elegivel)
    rf_banc = float(sum(w[i] for i, c in enumerate(C.IDS) if c in ("pos_isenta", "ipca_isenta", "pre_isenta", "pos_trib")))
    fgc_reais = rf_banc * 0.60 * ctx.plano.pl
    emissores_fgc = int(np.ceil(fgc_reais / 250_000.0)) if fgc_reais > 0 else 0
    return {
        "rotulo": rotulo, "w": w, "ret": ret, "bruto": bruto, "vol": vol, "ret_real": (1 + ret) / (1 + ctx.ipca) - 1,
        "excesso": ret - ctx.bench, "imposto_do_retorno": (1 - ret / bruto) if bruto > 0 else 0.0,
        "sharpe": (ret - ctx.bench) / vol if vol > 0 else float("nan"),
        "rc": rc, "enb": enb, "irpfm": mapa, "sim": sim, "estresse": est, "liq": liq, "usd": usd,
        "cdi_dep": cdi_dep, "travado": travado, "custo": custo, "rv": rv, "duration": duration,
        "emissores_fgc": emissores_fgc, "fgc_reais": fgc_reais,
        "maior_classe": float(w.max()), "maior_classe_id": C.IDS[int(w.argmax())],
        "retorno_necessario": S.retorno_necessario(ctx.plano, ctx.ipca),
    }

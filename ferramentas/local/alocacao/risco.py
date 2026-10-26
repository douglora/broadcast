"""Risco por classe: volatilidade e correlacao do historico real (preco ajustado do terminal),
com o CDI do BCB (SGS 12). Classe sem serie propria (credito, multimercado, previdencia) e
construida a partir dos fatores, com a receita escrita aqui, para a conta ser auditavel.

Janela: ~5 anos semanais (out/2021 em diante). Nao inclui 2008, 2015 nem 2020, e o relatorio
diz isso; o teste de estresse cobre o que a janela nao viu.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C

PROXIES = {
    "rv_br": "BOVA11",
    "fii": "IFIX",
    "rv_int": "IVVB11",
    "alt_ouro": "GOLD11",
    "cripto": "HASH11",
    "_ima_b5mais": "IB5M11",   # ETF do IMA-B 5+ (titulos IPCA+ acima de 5 anos)
}
DURACAO_IMA_B5MAIS = 2458.0 / 252.0   # IMA-B 5+: 2.458 dias uteis de duration (ANBIMA, 23/10/2026)
BETA_CREDITO = {"pos_isenta": 0.04, "pos_trib": 0.04, "ipca_isenta": 0.03, "pre_isenta": 0.03}
VOL_PISO = {"caixa": 0.001, "pos_isenta": 0.006, "pos_trib": 0.006}
MIX_MM = {"cdi": 0.55, "rv_br": 0.15, "rv_int": 0.15, "ima": 0.15}   # multimercado e VGBL
DUR_MM_JUROS = 3.0   # duracao da parte de juros do multimercado sintetico
SEMANAS = 52.0
# Risco de reinvestimento do CDI: o nivel medio do CDI nos proximos anos pode ficar acima ou abaixo da curva DI.
# Convencao da mesa: desvio de 1,5 ponto ao ano, persistente no horizonte. Vale para o que rende CDI.
SIGMA_NIVEL_JUROS = 0.015
SENS_CDI = {"caixa": 1.0, "pos_isenta": 1.0, "pos_trib": 1.0, "mm": MIX_MM["cdi"], "vgbl": MIX_MM["cdi"]}


def duracoes(horizonte: float) -> dict[str, float]:
    """Duracao (anos) de cada classe de juro prefixado/real, para escalar a volatilidade: o papel e
    comprado para segurar ate o horizonte, entao a duracao acompanha o prazo, com teto."""
    h = float(horizonte)
    return {
        "ipca_isenta": min(max(h * 0.85, 1.5), 6.0),
        "ipca_trib": min(max(h * 0.85, 1.5), 7.0),
        "pre_isenta": min(max(h * 0.80, 1.0), 4.0),
        "pre_trib": min(max(h * 0.80, 1.0), 4.0),
    }


def _hist(ticker: str) -> pd.Series | None:
    try:
        d = json.loads((C.HIST / f"{ticker}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    serie = d.get("ac") or d.get("c")
    if not serie or not d.get("t"):
        return None
    s = pd.Series(serie, index=pd.to_datetime(d["t"]), dtype="float64").dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if len(s) > 100 else None


def _cdi_sgs(anos: int = 6) -> pd.Series | None:
    """CDI diario (fator) pelo SGS 12 do BCB, com cache de um dia."""
    arq = C.CACHE / "cdi_sgs12.json"
    try:
        c = json.loads(arq.read_text(encoding="utf-8"))
        if time.time() - arq.stat().st_mtime < 20 * 3600 and c.get("dados"):
            return pd.Series([float(v) for _, v in c["dados"]], index=pd.to_datetime([d for d, _ in c["dados"]]))
    except (OSError, ValueError):
        pass
    fim = date.today()
    ini = fim - timedelta(days=int(365.25 * anos))
    url = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json"
           f"&dataInicial={ini.strftime('%d/%m/%Y')}&dataFinal={fim.strftime('%d/%m/%Y')}")
    for _ in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (mesa-alocacao)"})
            txt = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
            if txt.lstrip().startswith("["):
                linhas = json.loads(txt)
                dados = [[datetime.strptime(x["data"], "%d/%m/%Y").date().isoformat(), float(x["valor"])] for x in linhas]
                if len(dados) > 500:
                    C.CACHE.mkdir(parents=True, exist_ok=True)
                    arq.write_text(json.dumps({"fim": fim.isoformat(), "dados": dados}), encoding="utf-8")
                    return pd.Series([v for _, v in dados], index=pd.to_datetime([d for d, _ in dados]))
        except Exception:
            time.sleep(1.5)
    return None


def _cdi_semanal() -> tuple[pd.Series, str]:
    """Retorno semanal do CDI e a origem usada."""
    diario = _cdi_sgs()
    if diario is not None:
        fator = (1.0 + diario / 100.0)
        sem = fator.groupby(pd.Grouper(freq="W-FRI")).prod() - 1.0
        return sem.dropna(), "BCB SGS 12 (CDI diario)"
    macro = json.loads((C.OUT / "macro.json").read_text(encoding="utf-8"))
    serie = next((i["serie"] for i in macro.get("indicadores", []) if i.get("id") == "selic_meta"), [])
    s = pd.Series([v for _, v in serie], index=pd.to_datetime([d for d, _ in serie]), dtype="float64")
    sem = ((1.0 + (s - 0.10) / 100.0) ** (1.0 / 52.0) - 1.0).resample("W-FRI").last().dropna()
    return sem, "Selic meta do terminal menos 0,10 (aproximacao do CDI)"


def painel_semanal(horizonte: float = 5.0) -> tuple[pd.DataFrame, dict]:
    """Retornos semanais por classe (colunas = ids de C.CLASSES) e metadados da janela."""
    cdi_w, origem_cdi = _cdi_semanal()
    base: dict[str, pd.Series] = {}
    for cid, tk in PROXIES.items():
        s = _hist(tk)
        if s is None:
            raise RuntimeError(f"historico de {tk} ausente em {C.HIST}")
        base[cid] = s.resample("W-FRI").last().pct_change().dropna()
    base["caixa"] = cdi_w
    df = pd.DataFrame(base).dropna()
    # fatores
    cdi, rv, ima = df["caixa"], df["rv_br"], df["_ima_b5mais"]
    d = duracoes(horizonte)
    out = pd.DataFrame(index=df.index)
    out["caixa"] = cdi
    for cid, beta in BETA_CREDITO.items():
        if cid.startswith("pos"):
            out[cid] = cdi + beta * (rv - cdi)
    for cid in ("ipca_isenta", "ipca_trib", "pre_isenta", "pre_trib"):
        k = d[cid] / DURACAO_IMA_B5MAIS
        out[cid] = cdi + k * (ima - cdi) + BETA_CREDITO.get(cid, 0.0) * (rv - cdi)
    for cid in ("rv_br", "fii", "rv_int", "alt_ouro", "cripto"):
        out[cid] = df[cid]
    juros_mm = cdi + (DUR_MM_JUROS / DURACAO_IMA_B5MAIS) * (ima - cdi)
    mm = (MIX_MM["cdi"] * cdi + MIX_MM["rv_br"] * rv + MIX_MM["rv_int"] * df["rv_int"] + MIX_MM["ima"] * juros_mm)
    out["mm"] = mm
    out["vgbl"] = mm
    out = out[C.IDS]
    meta = {
        "inicio": out.index[0].date().isoformat(), "fim": out.index[-1].date().isoformat(),
        "semanas": int(len(out)), "origem_cdi": origem_cdi,
        "proxies": {k: v for k, v in PROXIES.items() if not k.startswith("_")} | {"ima_b5mais": PROXIES["_ima_b5mais"]},
        "duracoes": d,
    }
    return out, meta


def sens_cdi() -> np.ndarray:
    return np.array([SENS_CDI.get(c, 0.0) for c in C.IDS])


def covariancia(horizonte: float = 5.0, encolhimento: float = 0.20,
                sigma_juros: float = SIGMA_NIVEL_JUROS) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, dict]:
    """(cov anual, vol anual, correlacao, meta). A correlacao encolhe 20% na direcao da media, para
    nao dar confianca excessiva a uma amostra curta. A covariancia final soma o risco de reinvestimento do
    CDI (nivel de juros incerto) ao risco de marcacao; `meta['cov_mtm']` guarda a parte so de marcacao, que
    o Monte Carlo usa (la o nivel de juros entra como deslocamento persistente por trajetoria)."""
    df, meta = painel_semanal(horizonte)
    vol = df.std(ddof=1) * np.sqrt(SEMANAS)
    for cid, piso in VOL_PISO.items():
        vol[cid] = max(vol[cid], piso)
    corr = df.corr().fillna(0.0)
    n = len(corr)
    med = (corr.values.sum() - n) / (n * (n - 1))
    alvo = np.full((n, n), med)
    np.fill_diagonal(alvo, 1.0)
    c = (1 - encolhimento) * corr.values + encolhimento * alvo
    # garante matriz semidefinida positiva
    w, v = np.linalg.eigh(c)
    w = np.clip(w, 1e-6, None)
    c = (v * w) @ v.T
    dd = np.sqrt(np.diag(c))
    c = c / np.outer(dd, dd)
    cov_mtm = np.outer(vol.values, vol.values) * c
    b = sens_cdi()
    cov = cov_mtm + (sigma_juros ** 2) * np.outer(b, b)
    vol_f = pd.Series(np.sqrt(np.diag(cov)), index=corr.index)
    corr_f = pd.DataFrame(cov / np.outer(vol_f.values, vol_f.values), index=corr.index, columns=corr.columns)
    meta.update({"encolhimento": encolhimento, "sigma_juros": sigma_juros,
                 "cov_mtm": pd.DataFrame(cov_mtm, index=corr.index, columns=corr.columns),
                 "vol_mtm": pd.Series(np.sqrt(np.diag(cov_mtm)), index=corr.index)})
    return pd.DataFrame(cov, index=corr.index, columns=corr.columns), vol_f, corr_f, meta


def vol_carteira(w: np.ndarray, cov: pd.DataFrame) -> float:
    return float(np.sqrt(max(w @ cov.values @ w, 0.0)))


def contribuicao_risco(w: np.ndarray, cov: pd.DataFrame) -> np.ndarray:
    """Fatia do risco total (soma 1) que cada classe responde."""
    v = float(w @ cov.values @ w)
    if v <= 0:
        return np.zeros_like(w)
    return (w * (cov.values @ w)) / v

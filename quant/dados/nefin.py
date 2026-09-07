"""
Fatores de risco do NEFIN-USP (M6): Rm-Rf, SMB, HML, WML, IML e Risk_Free, diarios desde 2001.

O site inteiro do NEFIN e versionado no repositorio publico nefin/nefin.github.io, e o
CSV sofre revisoes retroativas materiais entre publicacoes (HML mudou em milhares de
datas entre dois snapshots de jun/2026). Por isso cada download e "fixado": guardamos
o conteudo com o hash SHA-256, o commit do GitHub quando der para descobrir, e a data
do snapshot (avail_date). Backtests devem citar o pin que usaram.
"""
import hashlib
import json
import os
import re
from datetime import date

import numpy as np
import pandas as pd

from quant.comum import DIR_BRUTOS, garantir_dir, gravar_gzip, gravar_json, http_get, ler_gzip, ler_json, log

REPO = "nefin/nefin.github.io"
URL_RAW = "https://raw.githubusercontent.com/{repo}/{ref}/static/resources/{caminho}"
URL_COMMITS_API = "https://api.github.com/repos/{repo}/commits?per_page=1&sha=main"
URL_COMMITS_ATOM = "https://github.com/{repo}/commits/main.atom"

ARQUIVOS = {
    "fatores": "risk_factors/nefin_factors.csv",
    "aluguel_taxa": "stock_loans/average_loan_fee.csv",
    "aluguel_short_interest": "stock_loans/average_short_interest.csv",
    "aluguel_days_to_cover": "stock_loans/average_days_to_cover.csv",
}
FATORES = ["Rm_minus_Rf", "SMB", "HML", "WML", "IML", "Risk_Free"]
DIR = os.path.join(DIR_BRUTOS, "nefin")


def sha_commit_atual():
    """Tenta descobrir o commit atual do repositorio (API, depois feed Atom). None se nao der."""
    r = http_get(URL_COMMITS_API.format(repo=REPO), tentativas=1, headers={"Accept": "application/vnd.github+json"})
    if r is not None:
        try:
            return r.json()[0]["sha"]
        except Exception:
            pass
    r = http_get(URL_COMMITS_ATOM.format(repo=REPO), tentativas=1)
    if r is not None:
        m = re.search(r"Commit/([0-9a-f]{40})", r.text)
        if m:
            return m.group(1)
    return None


def baixar(nome="fatores", ref="main"):
    """Baixa um arquivo do NEFIN e o fixa por hash. Devolve o dict do pin (ou None)."""
    caminho = ARQUIVOS[nome]
    r = http_get(URL_RAW.format(repo=REPO, ref=ref, caminho=caminho), timeout=120)
    if r is None or len(r.content) < 200:
        log(f"nefin {nome}: download falhou")
        return None
    sha256 = hashlib.sha256(r.content).hexdigest()
    pin = {"arquivo": nome, "caminho": caminho, "ref": ref, "sha256": sha256,
           "sha_commit": sha_commit_atual() if ref == "main" else ref,
           "avail_date": str(date.today()), "bytes": len(r.content)}
    garantir_dir(DIR)
    gravar_gzip(os.path.join(DIR, f"{nome}_{sha256[:12]}.csv.gz"), r.content)
    gravar_json(os.path.join(DIR, f"{nome}_{sha256[:12]}.json"), pin)
    gravar_json(os.path.join(DIR, f"{nome}_ultimo.json"), pin)
    log(f"nefin {nome}: {len(r.content)/1e3:.0f} kB, sha256 {sha256[:12]}, commit {pin['sha_commit']}")
    return pin


def pin_ultimo(nome="fatores"):
    return ler_json(os.path.join(DIR, f"{nome}_ultimo.json"))


def _ler_csv(conteudo):
    df = pd.read_csv(io_bytes(conteudo))
    if df.columns[0] in ("", "Unnamed: 0"):
        df = df.drop(columns=df.columns[0])
    return df


def io_bytes(b):
    import io
    return io.BytesIO(b)


def carregar_fatores(pin=None):
    """DataFrame indexado por data com os fatores em decimal diario. Usa o pin dado ou o ultimo."""
    pin = pin or pin_ultimo("fatores")
    if pin is None:
        raise FileNotFoundError("nenhum snapshot do NEFIN baixado; rode nefin.baixar()")
    df = _ler_csv(ler_gzip(os.path.join(DIR, f"fatores_{pin['sha256'][:12]}.csv.gz")))
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()[FATORES].astype(float)
    df.attrs["pin"] = pin
    return df


def carregar_aluguel(pin=None):
    pin = pin or pin_ultimo("aluguel_taxa")
    if pin is None:
        raise FileNotFoundError("nenhum snapshot do NEFIN (aluguel) baixado")
    df = _ler_csv(ler_gzip(os.path.join(DIR, f"aluguel_taxa_{pin['sha256'][:12]}.csv.gz")))
    df.columns = [c.strip() for c in df.columns]
    col_data = next(c for c in df.columns if c.lower().startswith("date"))
    df[col_data] = pd.to_datetime(df[col_data])
    return df.set_index(col_data).sort_index()


def estatisticas(df, ini=None, fim=None):
    """Media anualizada, vol, Sharpe e t-stat por fator (bruto de custos), como referencia."""
    d = df.loc[ini:fim] if (ini or fim) else df
    n = len(d)
    out = {}
    for c in FATORES:
        x = d[c].dropna()
        mu, sd = x.mean(), x.std(ddof=1)
        out[c] = {
            "media_aa": float(mu * 252), "vol_aa": float(sd * np.sqrt(252)),
            "sharpe": float(mu / sd * np.sqrt(252)) if sd > 0 else float("nan"),
            "t": float(mu / sd * np.sqrt(len(x))) if sd > 0 else float("nan"),
            "cagr": float((1 + x).prod() ** (252 / len(x)) - 1) if len(x) else float("nan"),
            "dias": int(len(x)),
        }
    out["_periodo"] = {"ini": str(d.index.min().date()), "fim": str(d.index.max().date()), "dias": n}
    return out


def mensal(df):
    """Retornos mensais compostos por fator (para comparar com replicas mensais)."""
    return (1 + df[FATORES]).resample("ME").prod() - 1

"""
Painel DIARIO de volatilidade por ativo (base das hipoteses A1 a A4 e do ranking de assimetrias).

Para cada ativo liquido e cada pregao, a partir das opcoes do COTAHIST (so series com negocio no dia):
  iv_atm30        volatilidade implicita no dinheiro, ~30 dias corridos (interpola os dois vencimentos que cercam 30 dias;
                  um so vencimento entre 14 e 50 dias vale como esta). No dinheiro = a call e a put de |delta| mais perto de 0,5,
                  media das duas (reduz o ruido de preco desencontrado entre a opcao e o ativo).
  iv_put25/iv_call25   volatilidade da put de delta -0,25 e da call de delta +0,25 do vencimento mais perto de 30 dias
  skew_put        iv_put25 - iv_atm (inclinacao: o quanto a protecao esta mais cara que o dinheiro)
  skew_call       iv_call25 - iv_atm
  desvio_paridade volatilidade da call menos a da put no MESMO exercicio e vencimento (so pares com 20+ negocios nas duas pernas)
  vr20/vr60/vr252 volatilidade realizada (retorno total, anualizada)
  perc_vi, perc_skew   percentil do valor de hoje entre os ultimos 252 pregoes do proprio ativo
  negocios_dia, series_liquidas   liquidez do dia

O preco de cada opcao e o ponto medio das ofertas do fechamento quando as duas existem e o spread e de ate 30%; senao o
ultimo negocio. Juro = CDI do dia, composto a 252 dias uteis, continuo.
"""
import os

import numpy as np
import pandas as pd

from quant.opcoes import bs, dados
from quant.opcoes.base import DIR_DADOS

ARQ = os.path.join(DIR_DADOS, "painel_vol.parquet")
DC_MIN, DC_MAX = 7, 75


def universo(top=25):
    from quant.opcoes import pozinho
    u = set().union(*pozinho.universo_por_ano(top).values())
    u.add("BOVA11")
    return u


def preparar_opcoes(op, spot, cdi_aa, dias):
    """op: opcoes de um ou mais dias (colunas da base); spot: Series indexada por (ativo, dia) com o fechamento.
    Devolve as linhas com iv e delta, prontas para agregar."""
    op = op[(~op["semanal"]) & (op["negocios"] >= 3)].copy()
    op["dc"] = (op["vencimento"] - op["dia"]).dt.days
    op = op[(op["dc"] >= DC_MIN) & (op["dc"] <= DC_MAX)]
    idx = pd.MultiIndex.from_arrays([op["ativo"], op["dia"]])
    op["S"] = spot.reindex(idx).values
    op = op[op["S"] > 0]
    op["r_aa"] = cdi_aa.reindex(op["dia"]).values
    op["r"] = np.log1p(op["r_aa"].astype(float))
    pos_d = np.searchsorted(dias.values, op["dia"].values.astype("datetime64[ns]"))
    pos_v = np.searchsorted(dias.values, op["vencimento"].values.astype("datetime64[ns]"))
    op["du"] = pos_v - pos_d
    op = op[op["du"] >= 3]
    quote = (op["oferta_compra"] > 0) & (op["oferta_venda"] > op["oferta_compra"])
    mid = (op["oferta_compra"] + op["oferta_venda"]) / 2.0
    spread = (op["oferta_venda"] - op["oferta_compra"]) / mid
    boa = quote & (spread <= 0.30)
    op["boa"] = boa
    op["spread"] = spread
    op["premio_ref"] = np.where(boa, mid, op["fech"])
    put = (op["tipo"] == "P").values
    t = (op["du"] / 252.0).values
    iv = bs.vol_implicita_vet(op["premio_ref"].values.astype(float), op["S"].values.astype(float), op["exercicio"].values.astype(float),
                              t, op["r"].values, put)
    op["iv"] = iv
    op["delta"] = bs.delta_vet(op["S"].values.astype(float), op["exercicio"].values.astype(float), t, op["r"].values, iv, put)
    op = op[op["iv"].notna() & (op["iv"] < 3.0)]
    return op


def agregar_dia(op):
    """Uma linha por (ativo, dia): iv_atm30, put25, call25, skews, desvio de paridade, liquidez."""
    op = op.copy()
    op["ad"] = op["delta"].abs()
    chave = ["ativo", "dia", "vencimento"]
    # no dinheiro: call e put de |delta| mais perto de 0,5 (>= 5 negocios)
    atm = op[(op["ad"] >= 0.35) & (op["ad"] <= 0.65) & (op["negocios"] >= 5)].copy()
    atm["dist"] = (atm["ad"] - 0.5).abs()
    atm = atm.sort_values(chave + ["tipo", "dist", "negocios"], ascending=[True, True, True, True, True, False]).drop_duplicates(chave + ["tipo"])
    a = atm.pivot_table(index=chave, columns="tipo", values="iv", aggfunc="first")
    a.columns = [f"iv_atm_{c}" for c in a.columns]
    a = a.reset_index()
    a["iv_atm"] = a[[c for c in a.columns if c.startswith("iv_atm_")]].mean(axis=1)
    dc = op.groupby(chave)["dc"].first().reset_index()
    a = a.merge(dc, on=chave)
    # put 25 e call 25
    def delta_alvo(tipo, alvo, nome):
        x = op[(op["tipo"] == tipo) & ((op["ad"] - alvo).abs() <= 0.08) & (op["negocios"] >= 5)].copy()
        x["dist"] = (x["ad"] - alvo).abs()
        x = x.sort_values(chave + ["dist", "negocios"], ascending=[True, True, True, True, False]).drop_duplicates(chave)
        return x[chave + ["iv"]].rename(columns={"iv": nome})
    a = a.merge(delta_alvo("P", 0.25, "iv_put25"), on=chave, how="left").merge(delta_alvo("C", 0.25, "iv_call25"), on=chave, how="left")
    # desvio de paridade no mesmo exercicio e vencimento
    pq = op[(op["negocios"] >= 20) & (op["ad"] >= 0.25) & (op["ad"] <= 0.75)]
    c = pq[pq["tipo"] == "C"][chave + ["exercicio", "iv"]].rename(columns={"iv": "iv_c"})
    p = pq[pq["tipo"] == "P"][chave + ["exercicio", "iv"]].rename(columns={"iv": "iv_p"})
    m = c.merge(p, on=chave + ["exercicio"])
    m["dev"] = m["iv_c"] - m["iv_p"]
    dev = m.groupby(chave)["dev"].mean().rename("desvio_paridade").reset_index()
    a = a.merge(dev, on=chave, how="left")
    # liquidez do dia
    liq = op.groupby(["ativo", "dia"]).agg(negocios_dia=("negocios", "sum")).reset_index()
    sl = op[(op["negocios"] >= 30) & op["boa"]].groupby(["ativo", "dia"])["codigo"].nunique().rename("series_liquidas").reset_index()
    # interpolacao a 30 dias corridos
    def a30(g):
        g = g[(g["dc"] >= 10) & (g["dc"] <= 60) & g["iv_atm"].notna()].sort_values("dc")
        if g.empty:
            return pd.Series({"iv_atm30": np.nan, "dc_ref": np.nan})
        baixo = g[g["dc"] <= 30]
        alto = g[g["dc"] > 30]
        if len(baixo) and len(alto):
            b, h = baixo.iloc[-1], alto.iloc[0]
            w = (30 - b["dc"]) / (h["dc"] - b["dc"])
            return pd.Series({"iv_atm30": b["iv_atm"] * (1 - w) + h["iv_atm"] * w, "dc_ref": 30.0})
        u = g.iloc[(g["dc"] - 30).abs().argmin()]
        if 14 <= u["dc"] <= 50:
            return pd.Series({"iv_atm30": u["iv_atm"], "dc_ref": float(u["dc"])})
        return pd.Series({"iv_atm30": np.nan, "dc_ref": np.nan})
    ref = a.groupby(["ativo", "dia"]).apply(a30).reset_index()
    # vencimento mais perto de 30 dias para skew e paridade
    a["dist30"] = (a["dc"] - 30).abs()
    mais_perto = a[a["iv_atm"].notna() & (a["dc"] >= 14) & (a["dc"] <= 50)].sort_values(["ativo", "dia", "dist30"]).drop_duplicates(["ativo", "dia"])
    out = mais_perto[["ativo", "dia", "vencimento", "iv_atm", "iv_put25", "iv_call25", "desvio_paridade"]].rename(columns={"iv_atm": "iv_atm_venc", "vencimento": "venc_ref"})
    out["skew_put"] = out["iv_put25"] - out["iv_atm_venc"]
    out["skew_call"] = out["iv_call25"] - out["iv_atm_venc"]
    out = ref.merge(out, on=["ativo", "dia"], how="outer").merge(liq, on=["ativo", "dia"], how="left").merge(sl, on=["ativo", "dia"], how="left")
    out["series_liquidas"] = out["series_liquidas"].fillna(0).astype(int)
    return out


def vol_realizada_painel(ativos, dias_idx):
    """DataFrame (ativo, dia) com vr20, vr60, vr252 e o retorno futuro de 5 e 21 pregoes (retorno total)."""
    f = dados.fator_retorno_total()
    ib = dados.ibov()
    linhas = []
    for a in ativos:
        s = ib if a == "BOVA11" else (f[a].dropna() if a in f.columns else None)
        if s is None or len(s) < 300:
            continue
        s = s[s.index.isin(dias_idx)]
        r = np.log(s).diff()
        d = pd.DataFrame({"ativo": a, "dia": s.index, "tr": s.values})
        for n in (20, 60, 252):
            d[f"vr{n}"] = (r.rolling(n, min_periods=int(n * 0.8)).std() * np.sqrt(252)).values
        d["fut5"] = (s.shift(-5) / s - 1.0).values
        d["fut21"] = (s.shift(-21) / s - 1.0).values
        linhas.append(d)
    return pd.concat(linhas, ignore_index=True)


def percentil_movel(s, janela=252, min_p=120):
    """Percentil (0-100) do valor de cada dia entre os ultimos `janela` valores validos (inclusive o de hoje)."""
    v = s.values.astype(float)
    out = np.full(len(v), np.nan)
    for i in range(len(v)):
        if np.isnan(v[i]):
            continue
        w = v[max(0, i - janela + 1):i + 1]
        w = w[~np.isnan(w)]
        if len(w) >= min_p:
            out[i] = (w <= v[i]).mean() * 100.0
    return pd.Series(out, index=s.index)


def construir(ano_ini=2011, ano_fim=2026):
    uni = universo()
    dias = dados.dias_estendidos()
    cdi = dados.cdi_diario()
    cdi_aa = ((1.0 + cdi.reindex(dias).ffill()) ** 252 - 1.0)
    partes = []
    for ano in range(ano_ini, ano_fim + 1):
        op = dados.carregar_opcoes(ano, ano)
        op = op[op["ativo"].isin(uni)]
        sp = pd.read_parquet(os.path.join(DIR_DADOS, f"ativo_{ano}.parquet"))
        sp = sp[(sp["fatcot"] == 1) & (sp["fech"] > 0) & sp["ativo"].isin(uni)]
        spot = sp.set_index(["ativo", "dia"])["fech"]
        spot = spot[~spot.index.duplicated(keep="last")]
        o = preparar_opcoes(op, spot, cdi_aa, dias)
        g = agregar_dia(o)
        g = g.merge(sp[["ativo", "dia", "fech"]].rename(columns={"fech": "spot"}).drop_duplicates(["ativo", "dia"]), on=["ativo", "dia"], how="left")
        partes.append(g)
        print(ano, len(g), flush=True)
    p = pd.concat(partes, ignore_index=True).sort_values(["ativo", "dia"]).reset_index(drop=True)
    vr = vol_realizada_painel(sorted(p["ativo"].unique()), set(dias))
    p = p.merge(vr, on=["ativo", "dia"], how="left")
    p["perc_vi"] = p.groupby("ativo", group_keys=False)["iv_atm30"].apply(percentil_movel)
    p["perc_skew"] = p.groupby("ativo", group_keys=False)["skew_put"].apply(percentil_movel)
    p["vr_menos_vi60"] = p["vr60"] - p["iv_atm30"]
    p["vr_menos_vi252"] = p["vr252"] - p["iv_atm30"]
    p.to_parquet(ARQ, index=False)
    return p


def carregar():
    return pd.read_parquet(ARQ)


if __name__ == "__main__":
    construir()

"""Estudo de eventos no mini-dolar (barras de 5 min, 888 pregoes): o que, medido numa hora fixa da manha, antecipa o
movimento seguinte ate as 13h? Metade 1 (60% dos pregoes) acha; metade 2 (40%) confirma. Pontos por contrato, sem custo."""
import numpy as np, pandas as pd
from quant.daytrade import historico as h
pd.set_option("display.width", 250)
m5 = h.carregar(h.arquivo_de("WDO$D", 5))
print(m5.columns.tolist(), m5.index[0], m5.index[-1])
O, H, L, C = m5["o"], m5["h"], m5["l"], m5["c"]
dias = sorted(set(m5.index.date)); corte = dias[int(len(dias) * 0.6)]
linhas = []
fech_ant = None; max_ant = None; min_ant = None; ret_ant = None
for d, g in m5.groupby(m5.index.date):
    c = g[C.name]; o = g[O.name]; hi = g[H.name]; lo = g[L.name]
    hm = g.index.strftime("%H:%M")
    def px(t):                                   # fechamento da ultima barra que termina ate t (barra carimbada no inicio)
        m = hm < t
        return float(c[m].iloc[-1]) if m.any() else None
    ab = float(o.iloc[0]); p1300 = px("13:00"); fim = float(c.iloc[-1])
    if p1300 is None or fech_ant is None:
        fech_ant, max_ant, min_ant, ret_ant = fim, float(hi.max()), float(lo.min()), fim - ab; continue
    for t in ("09:15", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00"):
        p = px(t)
        if p is None: continue
        m = hm < t
        r = {"dia": d, "t": t, "p": p, "gap": ab - fech_ant, "desde_abertura": p - ab, "desde_ontem": p - fech_ant,
             "faixa": float(hi[m].max() - lo[m].min()), "pos_faixa": (p - float(lo[m].min())) / max(float(hi[m].max() - lo[m].min()), 0.5),
             "ontem": ret_ant,
             "acima_max_ontem": p > max_ant, "abaixo_min_ontem": p < min_ant}
        for k, t2 in (("f15", 15), ("f30", 30), ("f60", 60)):
            hh, mm = int(t[:2]), int(t[3:]); tot = hh * 60 + mm + t2; t3 = f"{tot // 60:02d}:{tot % 60:02d}"
            q = px(t3); r[k] = (q - p) if q is not None else None
        for k, t2 in (("u15", 15), ("u30", 30), ("u60", 60)):
            hh, mm = int(t[:2]), int(t[3:]); tot = hh * 60 + mm - t2; t3 = f"{tot // 60:02d}:{tot % 60:02d}"
            q = px(t3); r[k] = (p - q) if q is not None else None
        r["ate13"] = p1300 - p; r["ate_fim"] = fim - p
        linhas.append(r)
    fech_ant, max_ant, min_ant, ret_ant = fim, float(hi.max()), float(lo.min()), fim - ab
df = pd.DataFrame(linhas); df["fora"] = df.dia > corte
df.to_pickle("quant/saida/estudo_eventos.pkl")
print("linhas", len(df), "pregoes", df.dia.nunique(), "corte", corte)
def linha(nome, sinal, alvo, x):
    """sinal: +1 compra, -1 vende, 0 fora. Devolve pontos por negocio e estatistica t nas duas metades."""
    out = [nome]
    for fora in (False, True):
        y = x[x.fora == fora]; s = sinal[y.index]; v = (s * y[alvo]).where(s != 0).dropna()
        n = len(v); med = v.mean() if n else float("nan"); t = med / (v.std() / np.sqrt(n)) if n > 5 and v.std() > 0 else float("nan")
        out += [n, round(med, 2), round(t, 1), round((v > 0).mean() * 100, 1) if n else None]
    return out
res = []
for t in ("09:15", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00"):
    x = df[df.t == t]
    for alvo in ("f30", "f60", "ate13"):
        for feat, lim in (("desde_abertura", 0), ("desde_abertura", 5), ("desde_abertura", 10), ("desde_ontem", 0), ("desde_ontem", 10), ("gap", 0), ("gap", 5),
                          ("u15", 0), ("u15", 3), ("u30", 0), ("u30", 5), ("u60", 0), ("u60", 8), ("ontem", 0), ("ontem", 15)):
            if x[feat].isna().all(): continue
            s = pd.Series(np.where(x[feat] > lim, 1, np.where(x[feat] < -lim, -1, 0)), index=x.index)
            res.append([t, alvo] + linha(f"segue {feat}>{lim}", s, alvo, x))
        s = pd.Series(np.where(x.pos_faixa > 0.8, 1, np.where(x.pos_faixa < 0.2, -1, 0)), index=x.index)
        res.append([t, alvo] + linha("segue ponta da faixa (80/20)", s, alvo, x))
        s = pd.Series(np.where(x.acima_max_ontem, 1, np.where(x.abaixo_min_ontem, -1, 0)), index=x.index)
        res.append([t, alvo] + linha("segue fora da faixa de ontem", s, alvo, x))
r = pd.DataFrame(res, columns=["hora", "alvo", "regra", "n1", "pts1", "t1", "ac1", "n2", "pts2", "t2", "ac2"])
r["mesmo_sinal"] = np.sign(r.pts1) == np.sign(r.pts2)
r["forca"] = np.minimum(r.t1.abs(), r.t2.abs()) * r.mesmo_sinal
print("\nregras testadas:", len(r), "| mesmo sinal nas duas metades:", int(r.mesmo_sinal.sum()), "| |t|>2 nas duas:", int(((r.t1.abs() > 2) & (r.t2.abs() > 2) & r.mesmo_sinal).sum()))
print("\n=== 30 mais fortes (menor |t| das duas metades, mesmo sinal)")
print(r.sort_values("forca", ascending=False).head(30).to_string(index=False))
r.to_pickle("quant/saida/estudo_eventos_res.pkl")

"""Reversao curta: depois de um tranco de 1 min no mini-dolar, o preco devolve? Entrada na ABERTURA do minuto seguinte (o que da para executar)."""
import numpy as np, pandas as pd, os
from quant.daytrade import historico as h
m1 = h.carregar(h.arquivo_de("WDO$D", 1))
x = m1[(m1.index.strftime("%H:%M") >= "09:15") & (m1.index.strftime("%H:%M") < "12:50")].copy()
dia = x.index.date; x["r"] = x.c - x.o
g = x.groupby(dia)
x["ent"] = g.o.shift(-1)
for k in (1, 3, 5, 10, 20):
    x[f"f{k}"] = g.c.shift(-k) - x.ent
dias = sorted(set(dia)); corte = dias[int(len(dias) * 0.6)]; x["fora"] = np.array(dia) > corte
x["vrel"] = x.v / x.v.rolling(30).mean()
print("minutos", len(x), "pregoes", len(dias), "| custo ~1,05 pt por contrato (ida e volta)")
for nome, m in (("tranco >= 3 pts", x.r.abs() >= 3), ("tranco >= 5 pts", x.r.abs() >= 5), ("tranco >= 8 pts", x.r.abs() >= 8),
                ("tranco >= 5 e volume 3x", (x.r.abs() >= 5) & (x.vrel >= 3)), ("tranco >= 5 e volume normal (<1,5x)", (x.r.abs() >= 5) & (x.vrel < 1.5))):
    for k in (1, 3, 5, 10, 20):
        out = []
        for fora in (False, True):
            y = x[m & (x.fora == fora)]; v = (-np.sign(y.r) * y[f"f{k}"]).dropna()
            out.append(f"n {len(v):>5} contra o tranco {v.mean():+.2f} pts t {v.mean() / (v.std() / np.sqrt(max(len(v), 1))):+.1f} acerto {(v > 0).mean() * 100:.0f}%")
        print(f"  {nome:<38} +{k:>2} min | dentro: {out[0]} | FORA: {out[1]}")

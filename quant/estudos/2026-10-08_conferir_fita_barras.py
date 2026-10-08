"""Confere a fita gravada pelo MetaTrader contra as barras de 1 minuto do proprio MetaTrader, no contrato vigente, hoje."""
import os, sys, pandas as pd, numpy as np
from quant.daytrade import historico as h, fluxo as fx
MT = fx.PASTA_MT5
dia = sys.argv[1] if len(sys.argv) > 1 else "20261008"
b = h.carregar(os.path.join(MT, "autopilot_historia_WDOX26_M1.csv"))
b = b[b.index.strftime("%Y%m%d") == dia]
linhas = []
with open(os.path.join(MT, f"autopilot_fita_{dia}.csv"), encoding="latin-1", errors="ignore") as f:
    for ln in f:
        x = fx.linha_da_fita(ln)
        if x and x["simbolo"] == "WDOX26":
            linhas.append(x)
t = pd.DataFrame(linhas)
t["min"] = pd.to_datetime((t.seg // 60) * 60, unit="s")
t["vol"] = t.compra + t.venda + t.get("indef", 0.0)
g = t.groupby("min").agg(o=("preco", "first"), h=("preco", "max"), l=("preco", "min"), c=("preco", "last"), v=("vol", "sum"), linhas=("preco", "size"))
j = b.join(g, rsuffix="_fita", how="inner")
print("minutos nas barras hoje:", len(b), "| na fita:", len(g), "| em comum:", len(j), "| fita desde", g.index[0], "ate", g.index[-1])
j["rv"] = j.v_fita / j.v
print("volume fita / volume barra: mediana", round(j.rv.median(), 3), "| p5", round(j.rv.quantile(.05), 3), "| p95", round(j.rv.quantile(.95), 3), "| minutos com diferenca > 10%:", int(((j.rv - 1).abs() > 0.10).sum()))
print("maxima igual:", int((j.h == j.h_fita).sum()), "| minima igual:", int((j.l == j.l_fita).sum()), "| fechamento igual:", int((j.c == j.c_fita).sum()), "| abertura igual:", int((j.o == j.o_fita).sum()), "de", len(j))
faltam = b.index.difference(g.index); faltam = faltam[faltam >= g.index[0]]
print("minutos que a barra tem e a fita nao (depois que a fita comecou):", len(faltam), list(faltam.strftime("%H:%M"))[:30])
print("\npiores diferencas de volume:"); print(j.assign(d=(j.rv - 1).abs()).sort_values("d", ascending=False).head(8)[["o", "h", "l", "c", "v", "o_fita", "h_fita", "l_fita", "c_fita", "v_fita", "linhas"]].to_string())
print("\n16:40-16:50:"); print(j.between_time("16:40", "16:50")[["o", "h", "l", "c", "v", "h_fita", "l_fita", "c_fita", "v_fita"]].to_string())

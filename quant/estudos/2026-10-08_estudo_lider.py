"""Quem anda na frente: o mini-indice antecipa o mini-dolar no minuto seguinte? Barras de 1 min de 2026 (MetaTrader)."""
import numpy as np, pandas as pd, os
from quant.daytrade import historico as h
MT = os.path.expanduser("~/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Files")
wdo = h.carregar(os.path.join(MT, "autopilot_historia_WDOSN_M1.csv")); win = h.carregar(os.path.join(MT, "autopilot_historia_WINSN_M1.csv"))
x = pd.DataFrame({"d": wdo.c, "do": wdo.o, "i": win.c, "vd": wdo.v, "vi": win.v}).dropna()
x = x[(x.index.strftime("%H:%M") >= "09:05") & (x.index.strftime("%H:%M") < "17:55")]
dia = x.index.date
x["rd"] = x.d.groupby(dia).diff(); x["ri"] = (x.i.groupby(dia).diff()) / x.i.shift(1) * 1e4      # dolar em pontos; indice em pontos-base
for k in (1, 2, 3, 5, 10):
    x[f"fd{k}"] = x.d.groupby(dia).shift(-k) - x.d                                              # dolar daqui a k minutos, fechamento a fechamento
    x[f"pi{k}"] = (x.i - x.i.groupby(dia).shift(k)) / x.i * 1e4                                 # indice nos ultimos k minutos
    x[f"pd{k}"] = x.d - x.d.groupby(dia).shift(k)
dias = sorted(set(dia)); corte = dias[int(len(dias) * 0.6)]; x["fora"] = np.array(dia) > corte
print("minutos", len(x), "pregoes", len(dias), "corte", corte)
print("correlacao no mesmo minuto (indice x dolar):", round(x.rd.corr(x.ri), 3))
print("\ncorrelacao: indice nos ultimos k min  x  dolar nos proximos j min   (dentro | FORA)")
for k in (1, 3, 5, 10):
    for j in (1, 3, 5, 10):
        a = x[~x.fora]; b = x[x.fora]
        print(f"  indice {k:>2} min -> dolar +{j:>2} min: {a[f'pi{k}'].corr(a[f'fd{j}']):+.3f} | {b[f'pi{k}'].corr(b[f'fd{j}']):+.3f}     proprio dolar {k:>2} -> +{j:>2}: {a[f'pd{k}'].corr(a[f'fd{j}']):+.3f} | {b[f'pd{k}'].corr(b[f'fd{j}']):+.3f}")
print("\nmovimento forte do indice em 1 min (acima do percentil 97,5 em modulo) -> dolar nos minutos seguintes, operando CONTRA o indice (indice sobe, vende dolar)")
lim = x.ri.abs().quantile(0.975)
for nome, m in (("indice forte", x.ri.abs() > lim), ("indice forte e dolar parado (|dolar| <= 0,5)", (x.ri.abs() > lim) & (x.rd.abs() <= 0.5))):
    for j in (1, 3, 5, 10):
        out = []
        for fora in (False, True):
            y = x[m & (x.fora == fora)]; v = (-np.sign(y.ri) * y[f"fd{j}"]).dropna()
            out.append(f"n {len(v):>5} media {v.mean():+.2f} pts t {v.mean() / (v.std() / np.sqrt(len(v))):+.1f}")
        print(f"  {nome} | +{j:>2} min | dentro: {out[0]} | FORA: {out[1]}")
print("\nlimiar do indice forte (pontos-base em 1 min):", round(lim, 1), "| custo de ida e volta no dolar: ~1,05 pt por contrato")

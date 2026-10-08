"""Climax de volume: barra com tranco e volume muito acima do normal; o preco devolve depois? Confirmacao nos 3 anos e meio (5 min),
ano a ano, e dose-resposta por multiplo de volume (1 min, 2026). Entrada na abertura da barra seguinte, contra o tranco. Pontos por contrato."""
import numpy as np, pandas as pd
from quant.daytrade import historico as h
pd.set_option("display.width", 250)
def base(tempo, ini="09:15", fim="12:50", jan=None):
    m = h.carregar(h.arquivo_de("WDO$D", tempo)); hm = m.index.strftime("%H:%M")
    dia_todos = m.index.date
    m["vrel"] = m.v / m.groupby(dia_todos).v.transform(lambda s: s.shift(1).rolling(jan or (30 // tempo * 1 if tempo > 1 else 30), min_periods=3).mean())
    m["r"] = m.c - m.o; g = m.groupby(dia_todos); m["ent"] = g.o.shift(-1)
    return m, g, hm
print("=== A. barras de 5 min, 2023-2026 (888 pregoes). volume relativo = volume da barra / media das 6 barras anteriores (30 min) do mesmo dia")
m, g, hm = base(5, jan=6)
for k in (1, 3, 6, 12):
    m[f"f{k}"] = g.c.shift(-k) - m.ent
x = m[(hm >= "09:15") & (hm < "12:50")].copy(); x["ano"] = x.index.year
def linha(y, k):
    v = (-np.sign(y.r) * y[f"f{k}"]).dropna(); n = len(v)
    return f"n {n:>4} {v.mean():+.2f} pts t {v.mean() / (v.std() / np.sqrt(max(n, 1))):+.1f} ac {(v > 0).mean() * 100:.0f}%" if n > 5 else f"n {n:>4}"
for nome, mk in (("tranco>=6 vol>=2x", (x.r.abs() >= 6) & (x.vrel >= 2)), ("tranco>=6 vol>=3x", (x.r.abs() >= 6) & (x.vrel >= 3)),
                 ("tranco>=8 vol>=2x", (x.r.abs() >= 8) & (x.vrel >= 2)), ("tranco>=8 vol>=3x", (x.r.abs() >= 8) & (x.vrel >= 3)),
                 ("tranco>=10 vol>=2x", (x.r.abs() >= 10) & (x.vrel >= 2)), ("tranco>=8 vol<1,5x (controle)", (x.r.abs() >= 8) & (x.vrel < 1.5))):
    print(f"\n{nome}")
    for k, rot in ((1, "+5 min"), (3, "+15 min"), (6, "+30 min"), (12, "+60 min")):
        print(f"   {rot:>7} | todos: {linha(x[mk], k)} | " + " | ".join(f"{a}: {linha(x[mk & (x.ano == a)], k)}" for a in (2023, 2024, 2025, 2026)))
print("\n=== B. barras de 1 min, 2026 (176 pregoes): dose-resposta por multiplo de volume, tranco >= 4 pts, contra o tranco")
m, g, hm = base(1, jan=30)
for k in (3, 5, 10, 20):
    m[f"f{k}"] = g.c.shift(-k) - m.ent
x = m[(hm >= "09:15") & (hm < "12:50")].copy()
dias = sorted(set(x.index.date)); corte = dias[int(len(dias) * 0.6)]; x["fora"] = np.array(x.index.date) > corte
x["faixa_vol"] = pd.cut(x.vrel, [0, 1, 1.5, 2, 3, 5, 999], labels=["<1x", "1-1,5x", "1,5-2x", "2-3x", "3-5x", ">5x"])
for fv, y in x[x.r.abs() >= 4].groupby("faixa_vol", observed=True):
    print(f"   volume {fv:>7} | " + " | ".join(f"+{k} min: {linha(y, k)}" for k in (3, 5, 10, 20)))
print("\n=== C. 1 min, tranco>=5 e volume>=3x, por hora e por metade")
y = x[(x.r.abs() >= 5) & (x.vrel >= 3)]
for hh, z in y.groupby(y.index.hour):
    print(f"   {hh}h | dentro: {linha(z[~z.fora], 10)} | FORA: {linha(z[z.fora], 10)}  (+10 min)")

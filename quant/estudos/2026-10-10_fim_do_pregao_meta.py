"""Meta-rotulagem minima do fim do pregao (mini-indice): o modelo primario e a regra (tendencia do dia nos ultimos 30
minutos); o secundario decide SE entra, com UM parametro: so opera quando a propria regra deu resultado medio positivo nos
ultimos L pregoes (medido em todos os pregoes, operando ou nao; so passado). Hipotese: a vantagem vem da zeragem obrigatoria
do varejo no fim do dia e liga e desliga com o comportamento do varejo; o desempenho recente e o termometro.
Desenho fixado ANTES de olhar: L = 60 (sensibilidade 40 e 80), minimo de 40 pregoes de historia, limiar zero.
Uso: python <arquivo> [--prova]   (sem --prova: so 10/2021 a 12/2025; com --prova: abre 2026 UMA vez)"""
import sys, numpy as np, pandas as pd
from quant.pesquisa import lab, ldp
from quant.pesquisa.regras import win_fim_do_dia as wf
KW = dict(stop=500.0, tempo=25, ini="09:00", ult="18:30", zerar="18:30")
abre_prova = "--prova" in sys.argv
partes = ("descoberta", "validacao") + (("prova",) if abre_prova else ())
m = pd.concat([lab.carregar("WIN", p) for p in partes]).sort_index()
r = lab.avaliar(m, wf.regra(m), "fim do pregao primario", "meta", ativo="WIN", registrar=False, **KW)
t = lab.medir(r["negocios"], espec=lab.espec_de("WIN"))
dias = sorted(set(lab.dia(m)))
res = t.groupby("dia").res.sum().reindex(dias, fill_value=0.0); res.index = pd.to_datetime(res.index)
def filtrado(L, minimo=40):
    liga = res.shift(1).rolling(L, min_periods=minimo).mean() > 0
    return res.where(liga, 0.0), liga
def linha(nome, x, de=None, ate=None):
    y = x[(x.index >= (de or x.index[0])) & (x.index <= (ate or x.index[-1]))]
    op = int((y != 0).sum())
    print(f"  {nome:<34} pregoes {len(y):>4} operados {op:>4} | Sharpe anual {ldp.sharpe_anual(y / 1e5):+.2f} | por pregao R$ {y.mean():+6.2f} | por negocio R$ {(y[y != 0].mean() if op else 0):+6.2f} | "
          f"acerto {((y[y != 0] > 0).mean() * 100 if op else 0):.0f}% | queda maxima R$ {ldp.queda_maxima(y):.0f} | PSR {ldp.psr(y / 1e5):.3f}")
print("=== 10/2021 a 12/2025 (onde o desenho foi fixado; 2 contratos)")
linha("primario (sempre opera)", res, ate="2025-12-31")
for L in (40, 60, 80):
    f, liga = filtrado(L); linha(f"com o filtro L={L}", f, ate="2025-12-31")
f60, liga60 = filtrado(60)
print("  por ano, L=60 (por pregao R$ | pregoes operados):", {a: (round(float(g.mean()), 1), int((g != 0).sum())) for a, g in f60[:"2025-12-31"].groupby(f60[:"2025-12-31"].index.year)})
print("  por ano, primario:", {a: round(float(g.mean()), 1) for a, g in res[:"2025-12-31"].groupby(res[:"2025-12-31"].index.year)})
x = f60[:"2025-12-31"]
print(f"  Sharpe deflacionado do filtro L=60 (10/2021-12/2025): com 100 tentativas {ldp.dsr(x / 1e5, 100):.3f} | com 2.500 {ldp.dsr(x / 1e5, 2500):.3f} | com 35.000 {ldp.dsr(x / 1e5, 35000):.3f}")
# permutacao: embaralhar os resultados diarios destroi a persistencia; o filtro ainda ajuda?
rng = np.random.default_rng(5); base = res[:"2025-12-31"]; ganho = []
for _ in range(500):
    p = pd.Series(rng.permutation(base.to_numpy()), index=base.index)
    lg = p.shift(1).rolling(60, min_periods=40).mean() > 0
    ganho.append(ldp.sharpe_anual(p.where(lg, 0.0) / 1e5) - ldp.sharpe_anual(p / 1e5))
real = ldp.sharpe_anual(x / 1e5) - ldp.sharpe_anual(base / 1e5)
print(f"  ganho de Sharpe do filtro: real {real:+.2f} | em 500 embaralhamentos: media {np.mean(ganho):+.2f}, p95 {np.percentile(ganho, 95):+.2f} | p-valor {np.mean(np.array(ganho) >= real):.3f}")
if abre_prova:
    print("\n=== PROVA FINAL: 2026 (aberta uma vez)")
    linha("primario (sempre opera)", res, de="2026-01-01")
    linha("com o filtro L=60", f60, de="2026-01-01")
    y = f60["2026-01-01":]
    print("  por trimestre, filtro:", {str(k): (round(float(g.mean()), 1), int((g != 0).sum())) for k, g in y.groupby(y.index.to_period("Q"))})
    print("  por trimestre, primario:", {str(k): round(float(g.mean()), 1) for k, g in res["2026-01-01":].groupby(res["2026-01-01":].index.to_period("Q"))})
    print(f"  filtro ligado hoje? {bool(liga60.iloc[-1])} | media dos ultimos 60 pregoes do primario: R$ {res.iloc[-60:].mean():+.2f}")

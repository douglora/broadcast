"""Estrutura do negocio no teste de nivel: stop, alvo e parcial mudam a taxa de acerto; mudam o resultado? Base de 5 min."""
import pandas as pd
from quant.daytrade import historico as h, estrategias_hist as eh
m5 = h.carregar(h.arquivo_de("WDO$D", 5))
dias = sorted(set(m5.index.date)); corte = dias[int(len(dias) * 0.6)]
regras = h.RegrasDoDia(meta_rs=None, perda_maxima_rs=None, perdas_para_parar=None, max_operacoes=60, espera_min=0)
casos = {
    "atual (stop 3-10, alvo >=13, parcial 1R)": {},
    "alvo curto (alvo 6-10, sem exigir 2:1)": dict(alvo_min=6.0, alvo_max=10.0, alvo_padrao=8.0, rr_min=1.0),
    "alvo = risco (1:1), sem parcial": dict(alvo_min=3.0, alvo_max=10.0, alvo_padrao=5.0, rr_min=0.9, parcial_r=None),
    "stop largo 8-15, alvo 8-15": dict(stop_min=8.0, stop_max=15.0, alvo_min=8.0, alvo_max=15.0, alvo_padrao=10.0, rr_min=0.8),
    "sem parcial (stop 3-10, alvo >=13)": dict(parcial_r=None),
    "so 3:1 ou mais": dict(rr_min=3.0),
}
linhas = []
for nome, kw in casos.items():
    try:
        est = eh.NivelReacao(tempo=5, **kw)
    except TypeError as e:
        linhas.append([nome, "parametro nao existe: " + str(e)]); continue
    neg = h.simular(m5, est, regras, h.Custos())
    df = pd.DataFrame([dict(dia=x.dia, res=x.resultado, pts=x.pontos, c=x.contratos if hasattr(x, "contratos") else 2) for x in neg])
    for fora in (False, True):
        y = df[(df.dia > corte) == fora]
        linhas.append([nome, "FORA" if fora else "dentro", len(y), round((y.res > 0).mean() * 100, 1), round(y.res.mean(), 2), round(y.res[y.res > 0].mean(), 1), round(y.res[y.res <= 0].mean(), 1)])
for l in linhas: print(l)

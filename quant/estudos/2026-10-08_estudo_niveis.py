"""Estudo: o que separa ganho de perda no teste de nivel com reacao. Base de 5 minutos (888 pregoes), sem as travas do dia."""
import numpy as np, pandas as pd
from quant.daytrade import historico as h, estrategias_hist as eh
pd.set_option("display.width", 250)
m5 = h.carregar(h.arquivo_de("WDO$D", 5))
dias = sorted(set(m5.index.date)); corte = dias[int(len(dias) * 0.6)]
est = eh.NivelReacao(tempo=5, medias=(36, 72, 205), tempo_medias=5, medias_como_nivel=False)
regras = h.RegrasDoDia(meta_rs=None, perda_maxima_rs=None, perdas_para_parar=None, max_operacoes=60, espera_min=0)
neg = h.simular(m5, est, regras, h.Custos())
df = pd.DataFrame([dict(x.info, dia=x.dia, res=x.resultado, pts=x.pontos, saida=x.saida, melhor=x.melhor_pts) for x in neg])
df["fora"] = df["dia"] > corte
print("negocios:", len(df), "| dentro:", (~df.fora).sum(), "| fora:", df.fora.sum(), "| por negocio R$", round(df.res.mean(), 2), "| acerto", round((df.res > 0).mean() * 100, 1), "%")
print("saidas:", df.saida.value_counts().to_dict())
def tab(col, cortes=None, rot=None):
    x = df.copy()
    if cortes is not None:
        x[col] = pd.cut(x[col], cortes, labels=rot)
    g = x.groupby([col, "fora"], observed=True).res.agg(["count", "mean", lambda v: (v > 0).mean() * 100]).round(1)
    g.columns = ["n", "R$/neg", "acerto%"]
    t = g.unstack("fora"); t.columns = [f"{a} {'FORA' if b else 'dentro'}" for a, b in t.columns]
    print(f"\n--- por {col}"); print(t.to_string())
tab("nivel"); tab("hora"); tab("lado")
tab("contra_30", [-999, -10, -4, 0, 4, 10, 999], ["a favor >10", "a favor 4-10", "a favor 0-4", "contra 0-4", "contra 4-10", "contra >10"])
tab("contra_60", [-999, -15, -5, 0, 5, 15, 999], ["a favor >15", "a favor 5-15", "a favor 0-5", "contra 0-5", "contra 5-15", "contra >15"])
tab("lado_do_medio", [-999, -15, -5, 0, 5, 15, 999], ["contra >15", "contra 5-15", "contra 0-5", "a favor 0-5", "a favor 5-15", "a favor >15"])
tab("posicao_na_faixa", [-0.01, 0.2, 0.4, 0.6, 0.8, 1.01], ["fundo 0-20%", "20-40%", "meio", "60-80%", "topo 80-100%"])
tab("faixa_do_dia", [0, 15, 25, 40, 60, 999], ["<15", "15-25", "25-40", "40-60", ">60"])
tab("vai_e_vem_30", [0, 6, 10, 15, 25, 999], ["<6", "6-10", "10-15", "15-25", ">25"])
tab("risco", [0, 3.5, 4.5, 6, 8, 99], ["3-3,5", "4-4,5", "5-6", "6,5-8", ">8"])
tab("rr", [0, 2.5, 3.5, 5, 99], ["2-2,5", "2,5-3,5", "3,5-5", ">5"])
tab("sombra", [0, 2, 3, 4.5, 99], ["1,5-2", "2,5-3", "3,5-4,5", ">4,5"])
tab("toque_numero", [0, 1, 2, 3, 99], ["1o", "2o", "3o", "4o+"])
tab("lado_medias"); tab("lado_longa")
df.to_pickle("quant/saida/estudo_niveis.pkl")

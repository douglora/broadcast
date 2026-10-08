"""Climax de volume no simulador (1 min, 2026, com custo e deslize): varias estruturas, metade 1 x metade 2."""
import pandas as pd, numpy as np
from quant.daytrade import historico as h, estrategias_hist as eh
m1 = h.carregar(h.arquivo_de("WDO$D", 1))
dias = sorted(set(m1.index.date)); corte = dias[int(len(dias) * 0.6)]
regras = h.RegrasDoDia(meta_rs=None, perda_maxima_rs=None, perdas_para_parar=None, max_operacoes=60, espera_min=0)
def roda(nome, custos=None, **kw):
    neg = h.simular(m1, eh.Climax(**kw), regras, custos or h.Custos())
    df = pd.DataFrame([dict(dia=x.dia, res=x.resultado, pts=x.pontos, saida=x.saida) for x in neg])
    out = [nome]
    for fora in (False, True):
        y = df[(df.dia > corte) == fora]; n = len(y)
        out.append(f"n {n:>3} ac {(y.res > 0).mean() * 100:>4.0f}% R$/neg {y.res.mean():>+7.2f} bruto pts {y.pts.mean():>+5.2f} total {y.res.sum():>+8.0f} t {y.res.mean() / (y.res.std() / np.sqrt(max(n, 1))):+.1f}")
    out.append(str(df.saida.value_counts().to_dict()))
    print(" | ".join(out))
print("pregoes", len(dias), "corte", corte, "| dentro | FORA | saidas")
roda("D tempo 20, stop 10, sem alvo", tempo_max=20, stop_fixo=10)
roda("E tempo 20, stop 10, alvo devolve 60%", tempo_max=20, stop_fixo=10, alvo_devolve=0.6)
roda("M tempo 20, stop 10, parcial devolve 60%, resto no tempo", tempo_max=20, stop_fixo=10, parcial_devolve=0.6)
roda("N = M com tranco >=5", tempo_max=20, stop_fixo=10, parcial_devolve=0.6, tranco=5)
roda("O = M com parcial devolve 50%", tempo_max=20, stop_fixo=10, parcial_devolve=0.5)
roda("P = M com stop 8", tempo_max=20, stop_fixo=8, parcial_devolve=0.6)
roda("Q = M com tempo 30", tempo_max=30, stop_fixo=10, parcial_devolve=0.6)
print("--- com as travas do dia e a janela 9:15-12:50 (como o robo roda)")
regras = h.RegrasDoDia()
roda("M com travas", tempo_max=20, stop_fixo=10, parcial_devolve=0.6)
roda("E com travas", tempo_max=20, stop_fixo=10, alvo_devolve=0.6)

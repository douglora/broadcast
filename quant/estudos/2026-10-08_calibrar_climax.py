"""Calibracao do climax de volume (mini-dolar, barras de 1 min de 2026). Pedido do Douglas em 08/10: "ajuste para acertar
2 em 3, objetivo de 1% por dia". Escolhe na metade 1 (60% dos pregoes) e confere na metade 2 (40%). 2 contratos, com custo
(R$ 1,20 por contrato e lado) e 1 tick contra na entrada e nas saidas a mercado (stop e tempo); alvo sai no preco."""
import itertools, sys
import numpy as np, pandas as pd
from quant.daytrade import historico as h
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
TICK, VP, TAXA = 0.5, 10.0, 1.20
m1 = h.carregar(h.arquivo_de("WDO$D", 1))
o, hi, lo, c, v = (m1[k].to_numpy() for k in ("o", "h", "l", "c", "v"))
hm = np.array(m1.index.strftime("%H:%M")); dia = np.array(m1.index.date)
vrel = (m1.v / m1.groupby(dia).v.transform(lambda s: s.shift(1).rolling(30, min_periods=3).mean())).to_numpy()
dias = sorted(set(dia)); corte = dias[int(len(dias) * 0.6)]
fim_do_dia = np.r_[dia[1:] != dia[:-1], True]

def negocios(tranco, vol, alvo_dev, stop, tempo, ini="09:15", ult="12:50", zerar="13:00", vol_max=None):
    """Lista de (dia, hora, pontos por contrato ja com deslize, saida). Sem posicoes sobrepostas."""
    r = c - o
    cand = np.where((np.abs(r) >= tranco) & (vrel >= vol) & (hm >= ini) & (hm < ult) & ~fim_do_dia & ((vrel < vol_max) if vol_max else True))[0]
    fora, livre = [], -1
    for i in cand:
        if i < livre:
            continue
        s = -1.0 if r[i] > 0 else 1.0                       # contra o tranco
        ent = o[i + 1] + s * TICK
        alvo = ent + s * max(abs(r[i]) * alvo_dev, 1.5) if alvo_dev else None
        stp = ent - s * stop
        j, pts, saida = i + 1, None, None
        while True:
            if dia[j] != dia[i] or hm[j] >= zerar:
                pts, saida = s * ((o[j] if dia[j] == dia[i] else c[j - 1]) - s * TICK - ent), "fim da janela"; break
            if j - (i + 1) >= tempo:
                pts, saida = s * (o[j] - s * TICK - ent), "tempo"; break
            pior, melhor = (lo[j], hi[j]) if s > 0 else (hi[j], lo[j])
            if (pior <= stp) if s > 0 else (pior >= stp):
                base = min(o[j], stp) if s > 0 else max(o[j], stp)
                pts, saida = s * (base - s * TICK - ent), "stop"; break
            if alvo is not None and ((melhor >= alvo) if s > 0 else (melhor <= alvo)):
                pts, saida = s * (alvo - ent), "alvo"; break
            j += 1
            if j >= len(o):
                pts, saida = s * (c[-1] - ent), "fim"; break
        fora.append((dia[i], hm[i], pts, saida)); livre = j
    return fora

def medir(neg, contratos=2):
    d = pd.DataFrame(neg, columns=["dia", "hora", "pts", "saida"])
    d["res"] = d.pts * VP * contratos - 2 * TAXA * contratos
    return d

def linha(d):
    out = []
    for fora in (False, True):
        y = d[(d.dia > corte) == fora]; n = len(y)
        out += [n, round((y.res > 0).mean() * 100, 0) if n else np.nan, round(y.res.mean(), 1) if n else np.nan]
    return out

if __name__ == "__main__":
    grade = list(itertools.product((3.0, 4.0, 5.0, 6.0), (2.5, 3.0, 4.0, 5.0), (0.4, 0.5, 0.6, 0.8, 1.0), (6.0, 8.0, 10.0, 12.0, 15.0), (10, 20, 30)))
    lin = []
    for tranco, vol, ad, stop, tempo in grade:
        lin.append([tranco, vol, ad, stop, tempo] + linha(medir(negocios(tranco, vol, ad, stop, tempo))))
    g = pd.DataFrame(lin, columns=["tranco", "vol", "devolve", "stop", "tempo", "n1", "ac1", "rs1", "n2", "ac2", "rs2"])
    g.to_pickle("quant/saida/calibrar_climax.pkl")
    print("pregoes", len(dias), "| corte", corte, "| configuracoes", len(g))
    print("metade 1: acerto medio", round(g.ac1.mean(), 1), "R$/neg", round(g.rs1.mean(), 1), "| metade 2: acerto", round(g.ac2.mean(), 1), "R$/neg", round(g.rs2.mean(), 1))
    print("configuracoes com acerto >= 66% nas duas metades:", int(((g.ac1 >= 66) & (g.ac2 >= 66)).sum()), "| com R$/neg > 0 nas duas:", int(((g.rs1 > 0) & (g.rs2 > 0)).sum()),
          "| com acerto >= 66% e R$/neg > 0 nas duas:", int(((g.ac1 >= 66) & (g.ac2 >= 66) & (g.rs1 > 0) & (g.rs2 > 0)).sum()))
    ok = g[(g.n1 >= 50) & (g.ac1 >= 66)].sort_values("rs1", ascending=False)
    print("\n=== escolhidas pela METADE 1 (acerto >= 66%, 50+ negocios), 15 melhores em R$/neg; a metade 2 e a prova")
    print(ok.head(15).to_string(index=False))
    print("\nmedia da metade 2 nas 15 escolhidas: acerto", round(ok.head(15).ac2.mean(), 1), "| R$/neg", round(ok.head(15).rs2.mean(), 1))
    print("\n=== efeito de cada parametro (media das configuracoes): R$/neg metade 1 | metade 2 | acerto 1 | acerto 2")
    for k in ("tranco", "vol", "devolve", "stop", "tempo"):
        print(g.groupby(k)[["rs1", "rs2", "ac1", "ac2", "n1", "n2"]].mean().round(1).to_string()); print()

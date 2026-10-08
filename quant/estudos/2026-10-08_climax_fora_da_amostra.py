"""Prova fora da amostra do climax de volume: a configuracao foi escolhida so com 2026 (26/01 a 08/10). Aqui ela roda nos
pregoes ANTERIORES, que a calibracao nunca viu. Uso: python <este arquivo> <arquivo de barras de 1 minuto do WDO$D>."""
import importlib.util, os, sys
import numpy as np, pandas as pd
from quant.daytrade import historico as h, estrategias_hist as eh
aqui = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cal", os.path.join(aqui, "2026-10-08_calibrar_climax.py")); cal = importlib.util.module_from_spec(spec); spec.loader.exec_module(cal)
INICIO_DA_CALIBRACAO = pd.Timestamp("2026-01-26")

def usar(m1):
    """Troca a base do calibrador por estas barras."""
    cal.m1 = m1
    cal.o, cal.hi, cal.lo, cal.c, cal.v = (m1[k].to_numpy() for k in ("o", "h", "l", "c", "v"))
    cal.hm = np.array(m1.index.strftime("%H:%M")); cal.dia = np.array(m1.index.date)
    cal.vrel = (m1.v / m1.groupby(cal.dia).v.transform(lambda s: s.shift(1).rolling(30, min_periods=3).mean())).to_numpy()
    cal.dias = sorted(set(cal.dia)); cal.fim_do_dia = np.r_[cal.dia[1:] != cal.dia[:-1], True]

def resumo(nome, d, ndias):
    n = len(d)
    if n < 4:
        print(f"{nome:<34} n {n:>4}"); return
    t = d.res.mean() / (d.res.std() / np.sqrt(n))
    print(f"{nome:<34} n {n:>4} ({n / max(ndias, 1):.2f}/pregao) acerto {(d.res > 0).mean() * 100:>3.0f}% R$/neg {d.res.mean():>+7.1f} t {t:+.1f} "
          f"ganho medio {d.res[d.res > 0].mean():>+6.0f} perda media {d.res[d.res <= 0].mean():>+6.0f} total {d.res.sum():>+8.0f}")

if __name__ == "__main__":
    todo = h.carregar(sys.argv[1])
    print("arquivo:", os.path.basename(sys.argv[1]), "|", len(todo), "barras, de", todo.index[0], "a", todo.index[-1], "|", len(set(todo.index.date)), "pregoes")
    por_dia = todo.groupby(todo.index.date).size()
    print("barras por pregao: mediana", int(por_dia.median()), "| pregoes com menos de 400 barras:", int((por_dia < 400).sum()))
    antes = todo[todo.index < INICIO_DA_CALIBRACAO]
    for nome, base in (("FORA DA AMOSTRA (antes de 26/01/2026)", antes), ("TUDO (com 2026)", todo)):
        if not len(base):
            print(nome, ": sem barras"); continue
        usar(base); nd = len(cal.dias)
        print(f"\n=== {nome}: {nd} pregoes, de {cal.dias[0]} a {cal.dias[-1]} | manha 9:15-12:50, 2 contratos, depois de custo")
        for rot, cfg in (("ESCOLHIDA 5 pts, 3x, alvo 80%", (5.0, 3.0, 0.8, 10.0, 20)), ("anterior 4 pts, 3x, alvo 60%", (4.0, 3.0, 0.6, 10.0, 20)),
                         ("vizinha 5 pts, 4x, alvo 80%", (5.0, 4.0, 0.8, 10.0, 20)), ("vizinha 6 pts, 3x, alvo 80%", (6.0, 3.0, 0.8, 10.0, 20)),
                         ("vizinha 5 pts, 3x, alvo 60%", (5.0, 3.0, 0.6, 10.0, 20)), ("fraco 3 pts, 2,5x, alvo 80%", (3.0, 2.5, 0.8, 10.0, 20))):
            d = cal.medir(cal.negocios(*cfg)); resumo(rot, d, nd)
            if rot.startswith("ESCOLHIDA"):
                d["ano"] = pd.to_datetime(d.dia).dt.year
                for ano, y in d.groupby("ano"):
                    resumo(f"   {ano}", y, len({x for x in cal.dias if x.year == ano}))
                sem = d[~((d.hora >= "09:27") & (d.hora < "09:39"))]; resumo("   sem os sinais da pausa das 9h30", sem, nd)
                resumo("   tarde 13:00-16:30", cal.medir(cal.negocios(*cfg, ini="13:00", ult="16:30", zerar="17:20")), nd)
        if nome.startswith("FORA"):
            for lote in (2, 4):
                neg = h.simular(base, eh.Climax(tranco=5.0, vol=3.0, stop_fixo=10.0, alvo_devolve=0.8, tempo_max=20), h.RegrasDoDia(contratos=lote), h.Custos())
                d = pd.DataFrame([dict(dia=x.dia, res=x.resultado) for x in neg])
                pdia = d.groupby("dia").res.sum().reindex(cal.dias, fill_value=0.0)
                print(f"   com as regras do dia, lote {lote}: {len(d)} negocios | acerto {(d.res > 0).mean() * 100:.0f}% | por negocio {d.res.mean():+.1f} | por pregao {pdia.mean():+.1f} | "
                      f"sem operar {int((pdia == 0).sum())} | positivos {int((pdia > 0).sum())} | negativos {int((pdia < 0).sum())} | melhor {pdia.max():+.0f} | pior {pdia.min():+.0f} | dias >= +1.000: {int((pdia >= 1000).sum())}")

"""Estudo 13/10/2026: o desfaz do ajuste das 16h no mini-dolar (regras.desfaz_ajuste_1600) como regra de tarde para operar todo dia.
Variantes de limiar, tempo e stop (familia ajuste_16h); descoberta; so candidata abre 2025."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from quant.pesquisa import lab  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402
PASTA = os.path.join(lab.PASTA, "montecarlo")
def rodar(parte, so=None):
    m = lab.carregar("WDO", parte); preg = len(set(lab.dia(m))); out = {}
    for thr in (3.0, 5.0, 8.0):
        for tempo in (30, 60):
            for stop in (20.0, 40.0):
                nome = f"ajuste16h thr{thr:g} tempo{tempo} stop{stop:g}"
                if so is not None and nome not in so: continue
                s = regras.desfaz_ajuste_1600(m, thr=thr, a=10)
                r = lab.avaliar(m, s, nome=f"{nome} [{parte}]", familia="ajuste_16h", stop=stop, alvo=None, tempo=tempo, ini="15:50", ult="16:05", zerar="17:30")
                out[nome] = {k: r.get(k) for k in ("n", "acerto", "rs_por_negocio", "t", "total", "semestres_positivos")}
                out[nome]["candidata"] = bool(lab.candidata(r)) if r.get("n") else False
                print(f"{parte:10s} {nome:34s} n={r['n']:4d} ({r['n']/preg:.2f}/pregao) acerto={r['acerto']:5.1f}% R$/neg={r['rs_por_negocio']:7.1f} t={r['t']:5.2f} sem={r['semestres_positivos']}")
    return out
desc = rodar("descoberta"); cands = [k for k, v in desc.items() if v["candidata"]]; print("candidatas:", cands or "nenhuma")
val = rodar("validacao", so=set(cands)) if cands else None
json.dump({"descoberta": desc, "validacao": val, "candidatas": cands}, open(os.path.join(PASTA, "ajuste_16h.json"), "w"), indent=1, default=str)

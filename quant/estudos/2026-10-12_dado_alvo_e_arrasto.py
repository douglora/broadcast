"""
Estudo 12/10/2026 (rodada 3): "acertar mais que errar". A regra congelada sai por tempo (120 min) ou no stop (40 pts), sem
alvo: taxa de acerto ~58%. Pergunta: um alvo de lucro, um stop movel (arrasto) ou um tempo menor sobem a taxa de acerto SEM
derrubar o resultado por negocio? Cada variante e uma tentativa (familia dado_saida); roda na descoberta; so candidata
(t >= 3, n >= 200, 5 de 7 semestres E resultado por negocio >= 90% do base) abre 2025, uma vez. A prova nao se abre. Nada
muda na regra: o que passar vira variante so medindo na prova viva.
Saida: quant/saida/pesquisa5/montecarlo/dado_saida.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from quant.pesquisa import lab  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402

PARAM = dict(r=2, thr=3.0)
FAMILIA = "dado_saida"
PASTA = os.path.join(lab.PASTA, "montecarlo")
VARIANTES = {
    "base (stop 40, tempo 120)": dict(stop=40.0, alvo=None, tempo=120),
    "alvo 10": dict(stop=40.0, alvo=10.0, tempo=120), "alvo 15": dict(stop=40.0, alvo=15.0, tempo=120),
    "alvo 20": dict(stop=40.0, alvo=20.0, tempo=120), "alvo 30": dict(stop=40.0, alvo=30.0, tempo=120),
    "arrasto 15": dict(stop=40.0, alvo=None, tempo=120, arrasto=15.0), "arrasto 25": dict(stop=40.0, alvo=None, tempo=120, arrasto=25.0),
    "tempo 60": dict(stop=40.0, alvo=None, tempo=60), "tempo 90": dict(stop=40.0, alvo=None, tempo=90),
    "stop 30": dict(stop=30.0, alvo=None, tempo=120), "stop 25 + alvo 25": dict(stop=25.0, alvo=25.0, tempo=120),
}


def rodar(parte, so=None, registrar=True):
    m = lab.carregar("WDO", parte)
    s = regras.reverte_dado_ny(m, **PARAM)
    out = {}
    for nome, kw in VARIANTES.items():
        if so is not None and nome not in so and not nome.startswith("base"):
            continue
        r = lab.avaliar(m, s, nome=f"dado saida | {nome} [{parte}]", familia=FAMILIA, registrar=registrar and not nome.startswith("base"), **kw)
        out[nome] = {k: r.get(k) for k in ("n", "acerto", "rs_por_negocio", "t", "total", "ganho_medio", "perda_media", "semestres_positivos", "saidas", "por_ano")}
        print(f"{parte:10s} {nome:26s} n={r['n']:4d} acerto={r['acerto']:5.1f}% R$/neg={r['rs_por_negocio']:7.1f} t={r['t']:5.2f} total={r['total']:8.0f} sem={r['semestres_positivos']} saidas={r['saidas']}")
    return out


def main():
    os.makedirs(PASTA, exist_ok=True)
    desc = rodar("descoberta")
    base = desc["base (stop 40, tempo 120)"]
    cands = [k for k, v in desc.items() if not k.startswith("base") and lab.candidata(v) and v["rs_por_negocio"] >= 0.9 * base["rs_por_negocio"] and v["acerto"] > base["acerto"]]
    print("candidatas (acerto maior e resultado >= 90% do base):", cands or "nenhuma")
    val = rodar("validacao", so=set(cands)) if cands else None
    json.dump({"descoberta": desc, "validacao": val, "candidatas": cands}, open(os.path.join(PASTA, "dado_saida.json"), "w"), indent=1, default=str)
    print("gravado", os.path.join(PASTA, "dado_saida.json"))


if __name__ == "__main__":
    main()

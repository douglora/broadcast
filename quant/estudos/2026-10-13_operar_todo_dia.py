"""
Estudo 13/10/2026: "o robo tem de operar todos os dias" (pedido do Douglas depois de um dia sem entrada: reacao de 1 pt ao dado).
Quanto custa, no historico, operar todo dia? Variantes da reversao do dado com gatilho menor (3 -> 2,5 / 2 / 1,5 / 1 / 0 = sempre)
e, para comparar, o que o setup de niveis (so medido desde 08/10) renderia operando. Cada variante e uma tentativa (familia
dado_gatilho); roda na descoberta (10/2021-12/2024); so candidata abre 2025. Nada muda na regra que opera.
Saida: quant/saida/pesquisa5/montecarlo/operar_todo_dia.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from quant.pesquisa import lab  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402

SAIDA = dict(stop=40.0, alvo=None, tempo=120)
FAMILIA = "dado_gatilho"
PASTA = os.path.join(lab.PASTA, "montecarlo")


def rodar(parte, so=None):
    m = lab.carregar("WDO", parte)
    pregoes = len(set(lab.dia(m)))
    out = {}
    for thr in (3.0, 2.5, 2.0, 1.5, 1.0, 0.0):
        nome = f"gatilho {thr:g} pts" + (" (todo dia)" if thr == 0 else "")
        if so is not None and nome not in so and thr != 3.0:
            continue
        r = lab.avaliar(m, regras.reverte_dado_ny(m, r=2, thr=thr), nome=f"dado {nome} [{parte}]", familia=FAMILIA, registrar=(thr != 3.0), **SAIDA)
        out[nome] = {k: r.get(k) for k in ("n", "acerto", "rs_por_negocio", "t", "total", "semestres_positivos", "por_ano")}
        out[nome].update(rs_por_pregao=round(r["total"] / max(pregoes, 1), 1), negocios_por_pregao=round(r["n"] / max(pregoes, 1), 2), candidata=bool(lab.candidata(r)) if r.get("n") else False)
        print(f"{parte:10s} {nome:24s} n={r['n']:4d} ({out[nome]['negocios_por_pregao']:.2f}/pregao) acerto={r['acerto']:5.1f}% R$/neg={r['rs_por_negocio']:7.1f} R$/pregao={out[nome]['rs_por_pregao']:6.1f} t={r['t']:5.2f} sem={r['semestres_positivos']}")
    return out


def main():
    os.makedirs(PASTA, exist_ok=True)
    desc = rodar("descoberta")
    cands = [k for k, v in desc.items() if v["candidata"] and not k.startswith("gatilho 3 ")]
    print("candidatas:", cands or "nenhuma")
    val = rodar("validacao", so=set(cands)) if cands else None
    json.dump({"descoberta": desc, "validacao": val, "candidatas": cands}, open(os.path.join(PASTA, "operar_todo_dia.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()

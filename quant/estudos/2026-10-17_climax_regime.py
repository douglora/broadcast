"""
Estudo 17/10/2026 (revisao da semana pedida pelo Douglas: "o que conseguimos melhorar ou mudar... a de indice e dolar nao").
O climax de volume foi DESLIGADO em 16/10 (decisao dele) porque perde nos 5 anos (-R$ 19,50 por negocio em 2021-2025), mas
na semana de 09 a 16/10 os 14 sinais medidos acertaram 13 (+R$ 679) e a calibracao de 08/10 mostrava 2026 positivo.
Hipotese escrita antes: o climax tem vantagem em alguns regimes e nao em outros; operar SO quando o proprio resultado dele nos
ultimos N pregoes encerrados e positivo (o mesmo liga/desliga da regra do mini-indice, N = 60, nao otimizado) tornaria a regra
positiva. Mecanismo possivel: em fases de mercado de reversao curta o tranco com volume e exagero; em fases de tendencia, nao.
Descoberta 10/2021-12/2024; candidata (t >= 3, n >= 200, 5 de 7 semestres) abre 2025 uma vez; 2026 ja foi visto para o climax
(calibracao de 08/10): nao escolhe nada, so a prova viva vale. N = 40 e 120 so para ver se e plato. Familia climax_regime.
Saida: quant/saida/pesquisa5/montecarlo/climax_regime.json
"""
import importlib.util
import json
import os
import sys
import time

import numpy as np
import pandas as pd

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)
from quant.daytrade import robo_fluxo as rf  # noqa: E402
from quant.pesquisa import lab  # noqa: E402

FAMILIA = "climax_regime"
PASTA = os.path.join(lab.PASTA, "montecarlo")


def _cal(m):
    spec = importlib.util.spec_from_file_location("cal", os.path.join(RAIZ, "quant", "estudos", "2026-10-08_calibrar_climax.py"))
    cal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cal)
    cal.m1 = m
    cal.o, cal.hi, cal.lo, cal.c, cal.v = (m[k].to_numpy() for k in ("o", "h", "l", "c", "v"))
    cal.hm = np.array(m.index.strftime("%H:%M"))
    cal.dia = np.array(m.index.date)
    cal.vrel = (m.v / m.groupby(cal.dia).v.transform(lambda s: s.shift(1).rolling(30, min_periods=3).mean())).to_numpy()
    cal.dias = sorted(set(cal.dia))
    cal.fim_do_dia = np.r_[cal.dia[1:] != cal.dia[:-1], True]
    return cal


def negocios_climax(m):
    """Todos os negocios do climax com os parametros vivos (janela 9h15-18h10), 2 contratos, depois de custo."""
    cal = _cal(m)
    c = rf.CLIMAX
    d = cal.medir(cal.negocios(c["tranco"], c["vol"], c["alvo_devolve"], c["stop_fixo"], c["tempo_max"], ini="09:15", ult="18:10", zerar="18:24"))
    d["dia"] = pd.to_datetime(d.dia)
    return d, [pd.Timestamp(x) for x in cal.dias]


def filtro_regime(d, dias, n=60, minimo=None):
    """So os negocios dos dias em que a media dos negocios dos ultimos `n` pregoes ENCERRADOS (antes do dia) e positiva."""
    minimo = minimo or max(10, n // 3)
    por_dia = d.groupby("dia").res.agg(["sum", "count"]).reindex(dias, fill_value=0.0)
    soma = por_dia["sum"].shift(1).rolling(n, min_periods=1).sum()
    cont = por_dia["count"].shift(1).rolling(n, min_periods=1).sum()
    liga = (cont >= minimo) & (soma / cont.replace(0, np.nan) > 0)
    return d[d.dia.map(liga).fillna(False).astype(bool)]


def resumo(d, pregoes):
    if not len(d):
        return {"n": 0}
    r = d.res.to_numpy()
    sem = d.dia.dt.year.astype(str) + "S" + ((d.dia.dt.month > 6) + 1).astype(str)
    ps = d.groupby(sem.values).res.mean()
    return {"n": int(len(r)), "rs_por_negocio": round(float(r.mean()), 2), "t": round(float(lab._t(r)), 2), "acerto": round(float((r > 0).mean() * 100), 1),
            "rs_por_pregao": round(float(r.sum() / pregoes), 2), "semestres_positivos": f"{int((ps > 0).sum())} de {len(ps)}",
            "por_ano": {int(a): [int(len(g)), round(float(g.res.mean()), 1)] for a, g in d.groupby(d.dia.dt.year)}}


def candidata(x):
    if not x.get("n") or x["n"] < 200:
        return False
    pos = int(str(x["semestres_positivos"]).split(" de ")[0])
    return bool(x["rs_por_negocio"] > 0 and x["t"] >= 3.0 and pos >= 5)


def registrar(nome, parte, x):
    with open(lab.REGISTRO, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(x, nome=nome, familia=FAMILIA, parte=parte, quando=time.strftime("%Y-%m-%d %H:%M:%S")), ensure_ascii=False) + "\n")


def rodar(parte, so=None):
    m = lab.carregar("WDO", parte)
    d, dias = negocios_climax(m)
    pregoes = len(dias)
    out = {"base (sem filtro)": resumo(d, pregoes)}
    for n in (60, 40, 120):
        nome = f"liga/desliga {n} pregoes"
        if so is not None and nome not in so:
            continue
        x = resumo(filtro_regime(d, dias, n), pregoes)
        x["candidata"] = candidata(x)
        out[nome] = x
        registrar(f"climax {nome} [{parte}]", parte, x)
    for k, x in out.items():
        print(f"{parte:10s} {k:26s} {x}")
    return out


def main():
    os.makedirs(PASTA, exist_ok=True)
    desc = rodar("descoberta")
    cands = [k for k, v in desc.items() if v.get("candidata") and k == "liga/desliga 60 pregoes"]
    print("candidata (N = 60, o pre-registrado):", cands or "nenhuma")
    val = rodar("validacao", so=set(cands)) if cands else None
    with open(os.path.join(PASTA, "climax_regime.json"), "w", encoding="utf-8") as f:
        json.dump({"descoberta": desc, "validacao": val, "candidatas": cands}, f, ensure_ascii=False, indent=1, default=str)


if __name__ == "__main__":
    main()

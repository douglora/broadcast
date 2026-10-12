"""
Monte Carlo do setup aprovado (reversao do dado americano, parametros CONGELADOS: 2 minutos, gatilho 3 pontos, stop 40,
tempo 120, 2 contratos), pedido do Douglas em 12/10/2026 ("Monte Carlo ... bootstrap de trades, testes de permutacao").

Nao e tentativa nova: e a MESMA regra ja medida (registro.jsonl, 09/10/2026) olhada por outro angulo. Por isso nao grava
no registro (registrar=False). Le descoberta (2021-2024) e validacao (2025); a prova de 2026 ja foi aberta para esta
regra em 09/10/2026 e NAO e lida de novo aqui.

Saidas (quant/saida/pesquisa5/montecarlo/):
  dado_negocios.csv            os negocios da regra (dia, hora, lado, pontos, R$)
  dado_bootstrap.json          distribuicao por ano simulado (bootstrap por blocos de 10 negocios e por negocio):
                               media, Sharpe, queda maxima, prob. de ano negativo, prob. de estourar os limites do robo
  dado_permutacao.json         a regra contra regras aleatorias com o MESMO numero de entradas, mesma hora, lado sorteado
Rodar: cd ~/Desktop/quant-b3 && PYTHONPATH=. .venv/bin/python -W ignore quant/estudos/2026-10-12_montecarlo_dado.py
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.getcwd())
from quant.pesquisa import lab, ldp  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402

PASTA = os.path.join(lab.PASTA, "montecarlo")
PARAM = dict(r=2, thr=3.0)
SAIDA = dict(stop=40.0, alvo=None, tempo=120)
LIMITES = {"dia": -1000.0, "semana": -2000.0, "queda": -10000.0}
CAPITAL = 100_000.0
SEMENTE = 20261012


def negocios_da_regra(m):
    s = regras.reverte_dado_ny(m, **PARAM)
    r = lab.avaliar(m, s, nome="MC dado (re-run, nao e tentativa)", familia="montecarlo", registrar=False, **SAIDA)
    t = lab.medir(r["negocios"])
    t["dia"] = pd.to_datetime(t["dia"])
    return t


def queda_maxima(x):
    ac = np.cumsum(x)
    return float((ac - np.maximum.accumulate(ac)).min()) if len(ac) else 0.0


def limites_estourados(serie_dia):
    """Quantas vezes a serie diaria teria parado o robo: dia <= -1000, semana <= -2000, queda <= -10000."""
    d = pd.Series(serie_dia)
    dia = int((d <= LIMITES["dia"]).sum())
    iso = d.index.isocalendar()
    sem = d.groupby([iso.year.to_numpy(), iso.week.to_numpy()]).sum()
    semana = int((sem <= LIMITES["semana"]).sum())
    return {"dias_com_perda_maxima": dia, "semanas_com_perda_maxima": semana, "semanas": int(len(sem)),
            "queda_maxima_rs": round(queda_maxima(d.to_numpy()), 0), "estourou_queda_10k": bool(queda_maxima(d.to_numpy()) <= LIMITES["queda"])}


def bootstrap(t, n_pregoes, n_sim=10_000, bloco=10, pregoes_por_ano=250):
    """Anos simulados: sorteia negocios (por bloco de `bloco` negocios seguidos, preservando sequencias) ate completar
    o numero medio de negocios por ano, e tambem por negocio solto. Devolve a distribuicao do resultado anual."""
    rng = np.random.default_rng(SEMENTE)
    res = t["res"].to_numpy(dtype=float)
    n_ano = max(1, int(round(len(res) * pregoes_por_ano / n_pregoes)))
    fora = {}
    for modo in ("bloco", "negocio"):
        anos, sharpes, quedas = [], [], []
        for _ in range(n_sim):
            if modo == "negocio":
                amostra = rng.choice(res, size=n_ano, replace=True)
            else:
                ini = rng.integers(0, max(1, len(res) - bloco), size=int(np.ceil(n_ano / bloco)))
                amostra = np.concatenate([res[i:i + bloco] for i in ini])[:n_ano]
            anos.append(amostra.sum())
            sd = amostra.std(ddof=1) if len(amostra) > 2 else 0.0
            sharpes.append(float(amostra.mean() / sd * np.sqrt(n_ano)) if sd > 0 else 0.0)   # Sharpe anual por negocio
            quedas.append(queda_maxima(amostra))
        anos, sharpes, quedas = np.array(anos), np.array(sharpes), np.array(quedas)
        fora[modo] = {"n_negocios_por_ano": n_ano, "n_sim": n_sim,
                      "ano_rs": {"media": round(float(anos.mean()), 0), "p05": round(float(np.percentile(anos, 5)), 0), "p25": round(float(np.percentile(anos, 25)), 0),
                                 "mediana": round(float(np.median(anos)), 0), "p75": round(float(np.percentile(anos, 75)), 0), "p95": round(float(np.percentile(anos, 95)), 0)},
                      "prob_ano_negativo": round(float((anos < 0).mean()), 3),
                      "prob_ano_abaixo_de_menos_5k": round(float((anos < -5000).mean()), 3),
                      "sharpe": {"mediana": round(float(np.median(sharpes)), 2), "p05": round(float(np.percentile(sharpes, 5)), 2), "p95": round(float(np.percentile(sharpes, 95)), 2),
                                 "prob_sharpe_negativo": round(float((sharpes < 0).mean()), 3)},
                      "queda_maxima_rs": {"mediana": round(float(np.median(quedas)), 0), "p05_pior": round(float(np.percentile(quedas, 5)), 0), "p01_pior": round(float(np.percentile(quedas, 1)), 0)},
                      "prob_queda_passa_10k": round(float((quedas <= LIMITES["queda"]).mean()), 4),
                      "prob_queda_passa_5k": round(float((quedas <= -5000).mean()), 4)}
    return fora


def permutacao(m, t, n_sim=400):
    """Placebo: o mesmo numero de entradas, na mesma hora do dia (o minuto de entrada do dado), em DIAS sorteados, lado
    sorteado, mesma saida (stop 40, 120 min). Quantas regras aleatorias ganham mais que a regra?"""
    rng = np.random.default_rng(SEMENTE + 1)
    h = lab.hm(m)
    verao = regras._verao_eua(m)
    alvo = np.where(verao, "09:31", "10:31")
    cand = np.where(h == alvo)[0]                          # a barra em que a regra decide (fecha o 2o minuto)
    n_ent = len(t)
    medias = []
    for _ in range(n_sim):
        idx = rng.choice(cand, size=n_ent, replace=False)
        s = np.zeros(len(m))
        s[idx] = rng.choice([-1.0, 1.0], size=n_ent)
        r = lab.medir(lab.negocios(m, s, stop=SAIDA["stop"], alvo=None, tempo=SAIDA["tempo"]))
        medias.append(float(r["res"].mean()) if len(r) else 0.0)
    medias = np.array(medias)
    real = float(t["res"].mean())
    return {"n_sim": n_sim, "n_entradas": n_ent, "media_real_rs": round(real, 2),
            "placebo_media_rs": {"media": round(float(medias.mean()), 2), "desvio": round(float(medias.std(ddof=1)), 2),
                                 "p95": round(float(np.percentile(medias, 95)), 2), "p99": round(float(np.percentile(medias, 99)), 2)},
            "p_valor": round(float((medias >= real).mean()), 4),
            "z": round(float((real - medias.mean()) / medias.std(ddof=1)), 2) if medias.std(ddof=1) > 0 else None}


def main():
    os.makedirs(PASTA, exist_ok=True)
    t0 = time.time()
    md = lab.carregar("WDO", "descoberta")
    mv = lab.carregar("WDO", "validacao")
    m = pd.concat([md, mv]).sort_index()
    t = negocios_da_regra(m)
    t.to_csv(os.path.join(PASTA, "dado_negocios.csv"), index=False)
    dias = pd.DatetimeIndex(sorted(set(pd.to_datetime(pd.Series(lab.dia(m))).dt.normalize())))
    serie = t.groupby("dia")["res"].sum().reindex(dias, fill_value=0.0)
    r_frac = serie / CAPITAL
    resumo = {"negocios": int(len(t)), "pregoes": int(len(serie)), "de": str(t["dia"].min().date()), "ate": str(t["dia"].max().date()),
              "media_rs_por_negocio": round(float(t["res"].mean()), 2), "t": round(float(lab._t(t["res"])), 2),
              "acerto": round(float((t["res"] > 0).mean()), 3), "total_rs": round(float(t["res"].sum()), 0),
              "rs_por_pregao": round(float(serie.mean()), 2),
              "sharpe_anual": round(ldp.sharpe_anual(r_frac), 2),
              "psr": round(ldp.psr(r_frac), 3),
              "dsr_100": round(ldp.dsr(r_frac, 100), 3), "dsr_1000": round(ldp.dsr(r_frac, 1000), 3), "dsr_2500": round(ldp.dsr(r_frac, 2500), 3),
              "dsr_35000": round(ldp.dsr(r_frac, 35000), 3),
              "limites_na_serie_real": limites_estourados(serie),
              "por_ano": {int(k): {"n": int(v.shape[0]), "media": round(float(v["res"].mean()), 1), "total": round(float(v["res"].sum()), 0)}
                          for k, v in t.groupby(t["dia"].dt.year)}}
    print(json.dumps(resumo, ensure_ascii=False, indent=1))
    boot = bootstrap(t, len(serie))
    print("bootstrap:", json.dumps(boot, ensure_ascii=False, indent=1))
    perm = permutacao(m, t)
    print("permutacao:", json.dumps(perm, ensure_ascii=False, indent=1))
    with open(os.path.join(PASTA, "dado_bootstrap.json"), "w", encoding="utf-8") as f:
        json.dump({"resumo": resumo, "bootstrap": boot, "quando": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(PASTA, "dado_permutacao.json"), "w", encoding="utf-8") as f:
        json.dump(perm, f, ensure_ascii=False, indent=1)
    print(f"tempo {time.time() - t0:.0f}s; saidas em {PASTA}")


if __name__ == "__main__":
    main()

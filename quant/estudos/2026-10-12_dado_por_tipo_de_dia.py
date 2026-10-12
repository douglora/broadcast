"""
O setup do dado americano (parametros congelados) separado pelo TIPO DO DIA: payroll, CPI, PPI, outro dado do BLS,
so pedidos de auxilio (quinta) e dia SEM divulgacao conhecida as 8h30. Pergunta: a vantagem vem dos dias de dado, ou o
robo esta apostando em ruido nos dias sem dado?

PRE-REGISTRO (12/10/2026, antes de rodar):
  - Descritivo: os negocios da regra base (r=2, gatilho 3, stop 40, tempo 120, 2 contratos) na descoberta (10/2021-12/2024)
    e na validacao (2025; a prova de 2026 NAO e aberta), rotulados pelo tipo do dia (quant/dados/calendario_eua.py).
  - Duas variantes, cada uma UMA tentativa no registro (familia calendario_tipo_dia):
      V1  so entra em dia com divulgacao das 8h30 conhecida (BLS ou pedidos de auxilio);
      V2  so entra em dia de payroll, CPI ou PPI.
    Criterio para seguir: media por negocio e R$ por pregao >= os da regra base na descoberta E positiva na validacao;
    senao, fica registrado como "nao agrega" e a regra base continua como esta.
  - Lacuna declarada: BEA e Census (PIB, PCE, varejo, bens duraveis, balanca) nao estao no calendario: dias deles caem
    em "nenhum conhecido", o que ENFRAQUECE a separacao (vies contra V1/V2, nao a favor).
Rodar: cd ~/Desktop/quant-b3 && PYTHONPATH=. .venv/bin/python -W ignore quant/estudos/2026-10-12_dado_por_tipo_de_dia.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.getcwd())
from quant.dados import calendario_eua as ce  # noqa: E402
from quant.pesquisa import lab  # noqa: E402
from quant.saida.pesquisa5.calendario import regras  # noqa: E402

PASTA = os.path.join(lab.PASTA, "montecarlo")
PARAM = dict(r=2, thr=3.0)
SAIDA = dict(stop=40.0, alvo=None, tempo=120)


def rotular(t, mapa):
    t = t.copy()
    t["tipo"] = [ce.tipo_do_dia(pd.Timestamp(d).date(), mapa) for d in t["dia"]]
    t["com_dado"] = t["tipo"] != "nenhum"
    return t


def resumo_por_tipo(t):
    linhas = []
    for tipo, g in t.groupby("tipo"):
        linhas.append({"tipo": tipo, "n": int(len(g)), "acerto": round(float((g["res"] > 0).mean()), 3),
                       "media_rs": round(float(g["res"].mean()), 1), "t": round(float(lab._t(g["res"])), 2) if len(g) > 3 else None,
                       "total_rs": round(float(g["res"].sum()), 0)})
    linhas.sort(key=lambda x: -x["n"])
    return linhas


def variante(m, mapa, nome, tipos_ok, registrar=True):
    s = regras.reverte_dado_ny(m, **PARAM)
    d = [pd.Timestamp(x).date() for x in lab.dia(m)]
    ok = np.array([ce.tipo_do_dia(x, mapa) in tipos_ok for x in d])
    s = np.where(ok, s, 0.0)
    r = lab.avaliar(m, s, nome=nome, familia="calendario_tipo_dia", registrar=registrar, **SAIDA)
    return r


def main():
    os.makedirs(PASTA, exist_ok=True)
    mapa = ce.tipos_por_dia()
    fora = {}
    for parte in ("descoberta", "validacao"):
        m = lab.carregar("WDO", parte)
        base = lab.avaliar(m, regras.reverte_dado_ny(m, **PARAM), nome=f"dado base (re-run) [{parte}]", familia="calendario_tipo_dia", registrar=False, **SAIDA)
        t = rotular(lab.medir(base["negocios"]), mapa)
        pregoes = len(set(lab.dia(m)))
        dias_tipo = {}
        for x in sorted(set(lab.dia(m))):
            k = ce.tipo_do_dia(pd.Timestamp(x).date(), mapa)
            dias_tipo[k] = dias_tipo.get(k, 0) + 1
        # tamanho da reacao por tipo de dia (todos os dias, nao so os operados)
        h, verao = lab.hm(m), regras._verao_eua(m)
        alvo = np.where(verao, "09:31", "10:31")
        mv = regras._mov(m, PARAM["r"])
        idx = np.where(h == alvo)[0]
        reac = pd.DataFrame({"dia": [pd.Timestamp(x).date() for x in lab.dia(m)[idx]], "mv": np.abs(mv[idx])})
        reac["tipo"] = [ce.tipo_do_dia(x, mapa) for x in reac["dia"]]
        reacao = {k: {"dias": int(len(g)), "mediana_pts": round(float(g["mv"].median()), 2), "fracao_acima_3": round(float((g["mv"] > 3).mean()), 3)}
                  for k, g in reac.groupby("tipo")}
        v1 = variante(m, mapa, f"V1 dado so em dia com divulgacao 8h30 [{parte}]", {"payroll", "cpi", "ppi", "outro_bls", "claims"})
        v2 = variante(m, mapa, f"V2 dado so em payroll/CPI/PPI [{parte}]", {"payroll", "cpi", "ppi"})
        fora[parte] = {"pregoes": pregoes, "dias_por_tipo": dias_tipo, "reacao_por_tipo": reacao,
                       "base": {"n": base["n"], "media_rs": base["rs_por_negocio"], "t": base["t"], "rs_por_pregao": round(base["total"] / pregoes, 2)},
                       "por_tipo": resumo_por_tipo(t),
                       "V1": {"n": v1["n"], "media_rs": v1["rs_por_negocio"], "t": v1["t"], "rs_por_pregao": round(v1["total"] / pregoes, 2), "semestres": v1["semestres_positivos"]},
                       "V2": {"n": v2["n"], "media_rs": v2["rs_por_negocio"], "t": v2["t"], "rs_por_pregao": round(v2["total"] / pregoes, 2), "semestres": v2["semestres_positivos"]}}
        print(parte, json.dumps(fora[parte], ensure_ascii=False, indent=1))
    with open(os.path.join(PASTA, "dado_por_tipo_de_dia.json"), "w", encoding="utf-8") as f:
        json.dump(fora, f, ensure_ascii=False, indent=1)
    print("gravado em", os.path.join(PASTA, "dado_por_tipo_de_dia.json"))


if __name__ == "__main__":
    main()

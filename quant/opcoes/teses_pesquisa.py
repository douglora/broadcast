"""
Terceira etapa: roda os itens 2, 3 e 5 e grava resultados_teses.json (o relatorio e o livro de teses leem este arquivo).

  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.teses_pesquisa
"""
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

from quant.opcoes import assimetrias_pesquisa as AP
from quant.opcoes import dados, diario, eleicoes, gatilho_tecnico, metricas, queda_forte
from quant.opcoes.base import DIR_DADOS, DIR_OPC
from quant.opcoes.painel import sem_nan
from quant.opcoes.painel_vol import carregar as carregar_painel

ARQ = os.path.join(DIR_OPC, "resultados_teses.json")


def esmagamento_resultados(m):
    """Variacao mediana da volatilidade implicita (iv_atm30) de 5 pregoes antes do protocolo ate o dia seguinte."""
    pv = carregar_painel()[["ativo", "dia", "iv_atm30"]].dropna().set_index(["ativo", "dia"])["iv_atm30"]
    a = pv.reindex(pd.MultiIndex.from_arrays([m["ativo"], m["entrada"]])).values
    b = pv.reindex(pd.MultiIndex.from_arrays([m["ativo"], m["saida"]])).values
    x = (b / a - 1.0) * 100
    x = x[~np.isnan(x)]
    return {"n": int(len(x)), "mediana_pct": round(float(np.median(x)), 1), "media_pct": round(float(x.mean()), 1), "p25": round(float(np.quantile(x, 0.25)), 1), "p75": round(float(np.quantile(x, 0.75)), 1)}


def movimentos_bbas3():
    """BBAS3 de 5 pregoes antes ate 5 pregoes depois (R+4) de cada turno -- so o papel, sem exigir opcao."""
    f = dados.fechamentos()["BBAS3"].dropna()
    dias = dados.dias_de_pregao()
    out = []
    for dom, rot in eleicoes.ELEICOES:
        R, iR = eleicoes._pregao_reacao(dom)
        d_in, d_out = dias[iR - 5], dias[iR + 4]
        out.append({"evento": rot, "entrada": str(d_in.date()), "saida": str(d_out.date()), "movimento_pct": round(float((f[d_out] / f[d_in] - 1) * 100), 1),
                    "movimento_do_pregao_de_reacao_pct": round(float((f[R] / f[dias[iR - 1]] - 1) * 100), 1)})
    return out


def caso_amer3():
    """Americanas: -77% em 12/01/2023. O sinal do robo nao dispara (a serie de retorno total descarta queda diaria acima de 50%); o caso e marcado a mao:
    a put de delta ~-0,25 do dia seguinte (13/01), marcada pelo ultimo fechamento disponivel do papel (19/01)."""
    tab = diario.carregar()
    f = dados.fechamentos()["AMER3"].dropna()
    x = tab[(tab["ativo"] == "AMER3") & (tab["dia"] == "2023-01-13") & (tab["tipo"] == "P") & tab["boa"] & (tab["negocios"] >= 30)]
    x = x.assign(d=(x["delta"].abs() - 0.25).abs()).sort_values("d")
    if x.empty:
        return None
    r = x.iloc[0]
    S_fim = float(f.iloc[-1])
    ultimo = f.index[-1]
    payoff = max(float(r["exercicio"]) - S_fim, 0.0)
    return {"queda_do_dia_pct": round(float((f["2023-01-12"] / f["2023-01-11"] - 1) * 100), 1), "preco_11_01": round(float(f["2023-01-11"]), 2), "preco_12_01": round(float(f["2023-01-12"]), 2),
            "put": r["codigo"], "exercicio": round(float(r["exercicio"]), 2), "delta": round(float(r["delta"]), 3), "bid": round(float(r["bid"]), 2), "ask": round(float(r["ask"]), 2),
            "preco_13_01": round(float(f["2023-01-13"]), 2), "ultimo_preco_disponivel": round(S_fim, 2), "ultima_data": str(ultimo.date()),
            "perda_marcada_pct_do_exercicio": round(float((payoff - float(r["bid"]) * (1 - 0.0005)) / float(r["exercicio"]) * 100), 1)}


def rodar():
    metricas.FORCAR = True
    R = {"gerado": datetime.now().isoformat(timespec="seconds")}
    # ---- item 2
    r2, out, todos = queda_forte.rodar()
    sin, _ = queda_forte.sinais()
    r2["cobertura"] = queda_forte.cobertura_e_casos(sin, out["A"], diario.carregar())
    r2["amer3"] = caso_amer3()
    R["queda_forte"] = r2
    # ---- item 3
    df = eleicoes.estudo_eleicoes()
    R["eleicoes"] = eleicoes.resumo_eleicoes(df)
    R["eleicoes"]["bbas3_movimentos"] = movimentos_bbas3()
    ev = df[(df["k"] == 5) & (df["j"] == 5)]
    R["eleicoes"]["tabela_k5_j5"] = [{"ativo": r["ativo"], "evento": r["evento"], **{c: (None if pd.isna(r.get(c)) else round(float(r[c]) * (100 if c in ("papel", "call", "trava_alta", "put", "straddle") else 1), 2))
                                                                                       for c in ("papel", "call", "trava_alta", "put", "straddle", "iv_in", "iv_out", "esmagamento_vol_pct", "exigido_call_pct", "movimento_veio_pct")}, "estimado": bool(r["estimado"])}
                                    for _, r in ev.sort_values(["ativo", "ano", "turno"]).iterrows()]
    m6, _meta = AP.a6()
    R["resultado_trimestral"] = {"call_contra_papel": eleicoes.resultado_call_contra_papel(m6), "esmagamento_vol": esmagamento_resultados(m6)}
    for k in ("n_linhas",):
        metricas.registrar("T3_eleicoes", "estudo descritivo 6 eventos", "descritivo", {"linhas": R["eleicoes"][k]})
    # ---- item 5
    R["gatilho_tecnico"] = gatilho_tecnico.rodar()
    with open(ARQ, "w", encoding="utf-8") as f:
        json.dump(sem_nan(R), f, ensure_ascii=False, indent=1, allow_nan=False, default=str)
    return R


if __name__ == "__main__":
    R = rodar()
    print("gravado", ARQ)
    q = R["queda_forte"]
    print(q["A"]["veredito"], q["cobertura"]["pct_com_put_executavel"], R["eleicoes"]["esmagamento_vol_pct"], R["resultado_trimestral"]["esmagamento_vol"])

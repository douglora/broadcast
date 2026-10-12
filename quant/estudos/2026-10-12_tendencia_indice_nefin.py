"""
Tendencia de 12 meses (time-series momentum, Moskowitz, Ooi e Pedersen, JFE 2012) na BOLSA brasileira, com o fator de
mercado do NEFIN (Rm - Rf, 2001 em diante) como serie: a regra G3 do estudo dos gestores, versao indice.

PRE-REGISTRO (12/10/2026): regra = no fim de cada mes, posicao = sinal do retorno em excesso dos 12 meses anteriores
pulando o ultimo (12-1), com tamanho = 10% de volatilidade alvo / volatilidade realizada de 63 pregoes (teto 1,5x);
custo de 0,015% por unidade de exposicao negociada (mini-indice, ida e volta). Janelas: DESENVOLVIMENTO 2001-2010,
VALIDACAO 2011-2015. 2016 em diante NAO e aberto (e a janela lacrada da carteira; fica para a prova viva). Sensibilidade
declarada: 3-1 e 6-1 meses (3 tentativas no total, registradas). Criterio: Sharpe liquido >= 0,5 na validacao com o
mesmo sinal da descoberta; senao, "nao passa".
Rodar: cd ~/Desktop/quant-b3 && PYTHONPATH=. .venv/bin/python -W ignore quant/estudos/2026-10-12_tendencia_indice_nefin.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.getcwd())
from quant.pesquisa import lab  # noqa: E402

ARQ = "quant/dados_brutos/nefin/fatores_093d49393521.csv.gz"
PASTA = os.path.join(lab.PASTA, "montecarlo")
VOL_ALVO, TETO, CUSTO = 0.10, 1.5, 0.00015


def carregar():
    f = pd.read_csv(ARQ)
    f["date"] = pd.to_datetime(f["Date"])
    f = f.set_index("date").sort_index()
    return f["Rm_minus_Rf"].astype(float), f["Risk_Free"].astype(float)


def tsmom(rm, meses, ini, fim):
    """Serie diaria do retorno em excesso da regra (liquido) entre ini e fim."""
    nivel = (1 + rm).cumprod()
    mensal = nivel.resample("ME").last()
    sinal_m = np.sign(mensal.shift(1) / mensal.shift(1 + meses) - 1.0)       # 12-1: ate o fim do mes anterior, pulando o ultimo mes
    vol = rm.rolling(63).std() * np.sqrt(252)
    tam_m = (VOL_ALVO / vol.resample("ME").last()).clip(upper=TETO)
    pos_m = (sinal_m * tam_m).shift(1)                                       # decidida no fim do mes, vale no mes seguinte
    pos = pos_m.reindex(rm.index, method="ffill").fillna(0.0)
    custo = pos.diff().abs().fillna(0.0) * CUSTO
    r = (pos * rm - custo).loc[ini:fim]
    return r, pos.loc[ini:fim]


def metricas(r, rm_ref):
    sh = float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if r.std(ddof=1) > 0 else float("nan")
    curva = (1 + r).cumprod()
    por_ano = (1 + r).groupby(r.index.year).prod() - 1
    return {"n_pregoes": int(len(r)), "retorno_excesso_aa": round(float(curva.iloc[-1] ** (252 / len(r)) - 1), 4), "sharpe": round(sh, 2),
            "queda_maxima": round(float((1 - curva / curva.cummax()).max()), 3),
            "anos_positivos": f"{int((por_ano > 0).sum())} de {len(por_ano)}",
            "mercado_sharpe": round(float(rm_ref.mean() / rm_ref.std(ddof=1) * np.sqrt(252)), 2),
            "mercado_excesso_aa": round(float((1 + rm_ref).prod() ** (252 / len(rm_ref)) - 1), 4),
            "correlacao_com_mercado": round(float(r.corr(rm_ref)), 2)}


def main():
    os.makedirs(PASTA, exist_ok=True)
    rm, _rf = carregar()
    fora = {}
    for meses in (12, 6, 3):
        fora[f"{meses}-1"] = {}
        for nome, (ini, fim) in {"desenvolvimento": ("2001-01-01", "2010-12-31"), "validacao": ("2011-01-01", "2015-12-31")}.items():
            r, _pos = tsmom(rm, meses, ini, fim)
            fora[f"{meses}-1"][nome] = metricas(r, rm.loc[ini:fim])
        with open(lab.REGISTRO, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tipo": "simulacao", "nome": f"TSMOM {meses}-1 indice NEFIN, vol alvo 10%", "familia": "tendencia_indice",
                                 "dev": fora[f"{meses}-1"]["desenvolvimento"], "val": fora[f"{meses}-1"]["validacao"],
                                 "quando": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n")
    fora["veredito"] = {k: ("passa" if v["validacao"]["sharpe"] >= 0.5 and v["desenvolvimento"]["sharpe"] >= 0.5 else "nao passa") for k, v in fora.items() if k != "veredito"}
    print(json.dumps(fora, ensure_ascii=False, indent=1))
    with open(os.path.join(PASTA, "tendencia_indice_nefin.json"), "w", encoding="utf-8") as fh:
        json.dump(fora, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

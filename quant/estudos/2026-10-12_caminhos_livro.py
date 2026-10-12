"""
Simulacao de caminhos do LIVRO 60/30/10 (acoes, opcoes, dolar) contra o orcamento de queda do Douglas (30% do livro:
17% acoes, 3% opcoes, 10% day trade), pedido de 12/10/2026 ("simulacao de caminhos para orcamento de queda do livro").

Series mensais (quant/saida/pesquisa_carteira/alocacao_series_mensais.parquet, 2016-02 a 2021-12, 71 meses):
  ACOES S1 = carteira de acoes com 1 contrato de protecao (a do robo de hoje, descritivo do holdout); OPCOES = capital
  protegido A0; DOLAR tendencia = regra de tendencia do dolar (reprovada na validacao: proxy fraco); CDI.
Para a classe DOLAR ha uma segunda versao: o day trade do dado americano, com os negocios medidos em 2021-2025
(quant/saida/pesquisa5/montecarlo/dado_negocios.csv), agregados por mes e reamostrados por bloco.

Bootstrap por blocos de 3 meses (10.000 caminhos de 12 meses): distribuicao do retorno do livro, da queda maxima e da
frequencia com que cada classe estoura a sua fatia. Tudo e descritivo: as series sao de periodos diferentes e nenhuma
regra foi escolhida aqui. Capital R$ 100 mil.
Rodar: cd ~/Desktop/quant-b3 && PYTHONPATH=. .venv/bin/python -W ignore quant/estudos/2026-10-12_caminhos_livro.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.getcwd())
from quant.pesquisa import lab  # noqa: E402

PASTA = os.path.join(lab.PASTA, "montecarlo")
ARQ = "quant/saida/pesquisa_carteira/alocacao_series_mensais.parquet"
ARQ_DADO = os.path.join(PASTA, "dado_negocios.csv")
CAPITAL = 100_000.0
PESOS = {"acoes": 0.60, "opcoes": 0.30, "dolar": 0.10}
ORCAMENTO = {"livro": 0.30, "acoes": 0.17, "opcoes": 0.03, "dolar": 0.10}
SEMENTE = 20261012


def queda_max(path):
    ac = np.cumprod(1 + path)
    return float((1 - ac / np.maximum.accumulate(ac)).max())


def caminhos(ret, n_sim=10_000, meses=12, bloco=3):
    """ret: DataFrame mensal com colunas acoes, opcoes, dolar (excesso sobre o CDI, em fracao da CLASSE)."""
    rng = np.random.default_rng(SEMENTE)
    r = ret.to_numpy(dtype=float)
    n = len(r)
    fora = {"livro": [], "acoes": [], "opcoes": [], "dolar": [], "ret": []}
    for _ in range(n_sim):
        ini = rng.integers(0, n - bloco + 1, size=int(np.ceil(meses / bloco)))
        amostra = np.concatenate([r[i:i + bloco] for i in ini])[:meses]
        a, o, d = amostra[:, 0], amostra[:, 1], amostra[:, 2]
        livro = PESOS["acoes"] * a + PESOS["opcoes"] * o + PESOS["dolar"] * d          # fracao do CAPITAL
        fora["livro"].append(queda_max(livro))
        fora["acoes"].append(queda_max(PESOS["acoes"] * a))                              # queda da classe em fracao do capital
        fora["opcoes"].append(queda_max(PESOS["opcoes"] * o))
        fora["dolar"].append(queda_max(PESOS["dolar"] * d))
        fora["ret"].append(float(np.prod(1 + livro) - 1))
    res = {}
    for k in ("livro", "acoes", "opcoes", "dolar"):
        q = np.array(fora[k])
        res[k] = {"queda_mediana_pct": round(float(np.median(q)) * 100, 2), "queda_p95_pct": round(float(np.percentile(q, 95)) * 100, 2),
                  "queda_p99_pct": round(float(np.percentile(q, 99)) * 100, 2),
                  "prob_estourar_orcamento": round(float((q >= ORCAMENTO[k]).mean()), 4), "orcamento_pct": ORCAMENTO[k] * 100}
    rr = np.array(fora["ret"])
    res["retorno_12m_excesso_cdi"] = {"media_pct": round(float(rr.mean()) * 100, 2), "p05_pct": round(float(np.percentile(rr, 5)) * 100, 2),
                                      "mediana_pct": round(float(np.median(rr)) * 100, 2), "p95_pct": round(float(np.percentile(rr, 95)) * 100, 2),
                                      "prob_negativo": round(float((rr < 0).mean()), 3)}
    return res


def main():
    os.makedirs(PASTA, exist_ok=True)
    d = pd.read_parquet(ARQ)
    cdi = d["CDI"].astype(float)
    base = pd.DataFrame({"acoes": d["ACOES S1"].astype(float) - cdi, "opcoes": d["OPCOES"].astype(float) - cdi, "dolar": d["DOLAR tendencia"].astype(float) - cdi})
    fora = {"meses": int(len(base)), "periodo": f"{d.index[0]} a {d.index[-1]}", "pesos": PESOS, "orcamento": ORCAMENTO,
            "v1_dolar_tendencia": caminhos(base)}
    # v2: a classe dolar = day trade do dado (R$ por mes sobre os R$ 10 mil da classe), reamostrado por bloco de meses
    try:
        t = pd.read_csv(ARQ_DADO, parse_dates=["dia"])
        mensal = t.groupby(t["dia"].dt.to_period("M"))["res"].sum()
        todos = pd.period_range(mensal.index.min(), mensal.index.max(), freq="M")
        mensal = mensal.reindex(todos, fill_value=0.0) / (CAPITAL * PESOS["dolar"])       # fracao da classe (R$ 10 mil)
        rng = np.random.default_rng(SEMENTE + 7)
        m2 = mensal.to_numpy()
        amostra = m2[rng.integers(0, len(m2), size=len(base))]                            # mesma extensao das outras series
        v2 = base.copy()
        v2["dolar"] = amostra
        fora["v2_dolar_daytrade_dado"] = caminhos(v2)
        fora["v2_nota"] = f"dado: {len(m2)} meses de 2021-10 a 2025-12 (inclui a descoberta: otimista), media {mensal.mean() * 100:.2f}% da classe por mes"
    except Exception as e:
        fora["v2_dolar_daytrade_dado"] = f"nao rodou: {type(e).__name__}: {e}"
    print(json.dumps(fora, ensure_ascii=False, indent=1))
    with open(os.path.join(PASTA, "caminhos_livro.json"), "w", encoding="utf-8") as f:
        json.dump(fora, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

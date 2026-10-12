"""
Estudo 12/10/2026 (rodada 2): dias analogos ("triangular com o passado").

Ideia: descrever cada dia pelo estado macro e micro conhecido na abertura (tabela de regimes, ponto no tempo), procurar os
k dias passados mais parecidos (vizinhos mais proximos em z-score calculado so com o passado) e perguntar o que aconteceu
no dia seguinte deles: o dolar subiu? o Ibovespa subiu? a reversao do dado rendeu? Se os analogos tiverem informacao, a
taxa de acerto nos dias de conviccao (maioria clara entre os vizinhos) fica acima de 50% fora da amostra.

Disciplina: k fixado de antemao (20 e 50); medida na descoberta por janela crescente (precisa de 250 dias de historico,
entao comeca em 10/2022) e UMA olhada em 2025. Cada alvo x k e uma tentativa registrada (familia analogos).
Saida: quant/saida/pesquisa5/montecarlo/dias_analogos.json
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from quant.pesquisa import lab, regimes  # noqa: E402
from quant.observacao import fontes  # noqa: E402

PASTA = os.path.join(lab.PASTA, "montecarlo")
KS = (20, 50)
MIN_HIST = 250
CONVICCAO = 0.2
COLS = ("vix_nivel", "vix_var10", "dxy_ret5", "dxy_ret20", "ust10_chg10", "brent_ret10", "usdbrl_ret1", "usdbrl_ret5", "usdbrl_ret10",
        "usdbrl_vol20", "usdbrl_vs_mm50", "ibov_ret5", "ibov_vol20", "spy_ret1", "spy_ret5", "ewz_spy_5", "hyg_ret5", "ouro_ret10",
        "ntnb35_chg10", "smll_ibov_20")


def alvos(f):
    """Retornos do proprio dia D (o que os analogos tentam prever): dolar e Ibovespa (fechamento D contra D-1) e o resultado
    do setup do dado no dia (so nos dias operados)."""
    usd = fontes.serie("USDBRL").pct_change() * 100
    ibov = fontes.serie("IBOV").pct_change() * 100
    base = pd.read_csv(os.path.join(PASTA, "base_dado_todos.csv")) if os.path.exists(os.path.join(PASTA, "base_dado_todos.csv")) else None
    a = pd.DataFrame(index=f.index)
    a["usdbrl"] = usd.reindex(f.index)
    a["ibov"] = ibov.reindex(f.index)
    if base is not None:
        r = base.groupby(pd.to_datetime(base.dia)).res.sum()
        a["dado"] = r.reindex(f.index)
    return a


def analogos(f, a, k):
    """Para cada dia D (com >= MIN_HIST dias antes), z-score com media e desvio ate D-1, k vizinhos mais proximos no passado,
    previsao = media do sinal do alvo nos vizinhos. Devolve DataFrame com previsao e realizado por alvo."""
    X = f[list(COLS)].astype(float)
    linhas = []
    idx = X.index
    for i in range(MIN_HIST, len(idx)):
        passado = X.iloc[:i]
        mu, sd = passado.mean(), passado.std().replace(0, np.nan)
        z_hist = ((passado - mu) / sd).fillna(0.0)
        z_hoje = ((X.iloc[i] - mu) / sd).fillna(0.0)
        if X.iloc[i].isna().mean() > 0.3:
            continue
        dist = np.sqrt(((z_hist - z_hoje) ** 2).sum(axis=1))
        viz = dist.nsmallest(k).index
        rec = {"dia": idx[i]}
        for alvo in a.columns:
            r_viz = a.loc[viz, alvo].dropna()
            rec[f"prev_{alvo}"] = float(np.sign(r_viz).mean()) if len(r_viz) >= max(5, k // 4) else np.nan
            rec[f"real_{alvo}"] = a.loc[idx[i], alvo]
        linhas.append(rec)
    return pd.DataFrame(linhas).set_index("dia")


def registrar(nome, familia, resumo):
    """Toda hipotese olhada conta no ledger (mesmo arquivo do lab, quant/saida/pesquisa5/registro.jsonl)."""
    import time
    linha = dict(resumo); linha.update(nome=nome, familia=familia, ativo="MACRO", quando=time.strftime("%Y-%m-%d %H:%M:%S"), tipo="analogos")
    with open(lab.REGISTRO, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")


def medir(df, alvo, de, ate):
    d = df.loc[de:ate].dropna(subset=[f"prev_{alvo}", f"real_{alvo}"])
    d = d[d[f"real_{alvo}"] != 0]
    conv = d[d[f"prev_{alvo}"].abs() >= CONVICCAO]
    acertos = int((np.sign(conv[f"prev_{alvo}"]) == np.sign(conv[f"real_{alvo}"])).sum())
    n = int(len(conv))
    p = float(stats.binomtest(acertos, n, 0.5).pvalue) if n else None
    rho = stats.spearmanr(d[f"prev_{alvo}"], d[f"real_{alvo}"]).correlation if len(d) > 10 else None
    return {"dias": int(len(d)), "dias_conviccao": n, "acerto_pct": round(acertos / n * 100, 1) if n else None, "p_binomial": round(p, 4) if p is not None else None,
            "rho_spearman": round(float(rho), 3) if rho is not None and not np.isnan(rho) else None}


def main():
    os.makedirs(PASTA, exist_ok=True)
    f = regimes.tabela()
    a = alvos(f)
    so = sys.argv[sys.argv.index("--so") + 1] if "--so" in sys.argv else None     # --so dado: so um alvo (os outros ja contados)
    out = {}
    for k in KS:
        df = analogos(f, a, k)
        for alvo in a.columns:
            if so and alvo != so:
                continue
            desc = medir(df, alvo, "2022-10-01", "2024-12-31")
            rec = {"descoberta": desc}
            registrar(f"analogos k={k} alvo={alvo} [descoberta]", "analogos", desc)
            # so olha 2025 se a descoberta mostrou algo (acerto >= 55% com p < 0,05); senao, fica registrado como sem informacao
            if desc["dias_conviccao"] and desc["acerto_pct"] is not None and desc["acerto_pct"] >= 55 and (desc["p_binomial"] or 1) < 0.05:
                rec["validacao"] = medir(df, alvo, "2025-01-01", "2025-12-31")
            out[f"k{k}_{alvo}"] = rec
            print(f"k={k:2d} alvo={alvo:7s} desc: {desc}" + (f" | 2025: {rec['validacao']}" if "validacao" in rec else ""))
        df.to_csv(os.path.join(PASTA, f"dias_analogos_k{k}.csv"))
    arq = os.path.join(PASTA, "dias_analogos.json")
    antigo = json.load(open(arq)) if os.path.exists(arq) else {}
    antigo.update(out)
    json.dump(antigo, open(arq, "w"), indent=1, default=str)
    print("gravado", os.path.join(PASTA, "dias_analogos.json"))


if __name__ == "__main__":
    main()

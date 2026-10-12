"""
Conferencia do indice de retorno total contra o preco ajustado do terminal, mes a mes, em TODO o universo.

Regra (a mesma da auditoria da TIR de 11/10/2026): retorno total inclui dividendos e JCP, entao num mes ele nunca sobe MENOS do que o preco ajustado a
desdobramento e bonificacao. Se (indice_t / indice_{t-1}) / (preco_t / preco_{t-1}) fica abaixo de `LIMIAR` (0,95), falta um evento de quantidade na
tabela `eventos`: o indice "cai" na data-ex. O inverso (acima de 1/0,95) e evento APLICADO DE MAIS ou na data errada.

O preco ajustado do terminal e a serie mensal (`cache/out/longo/<TICKER>.json`, Yahoo Finance: `c` = fechamento ajustado a desdobramento e bonificacao,
sem dividendos). O Yahoo erra de vez em quando (nao ajusta uma bonificacao recente, ajusta com atraso): esses meses ficam em `CONHECIDOS`, cada um com a
evidencia, e o teste so reprova mes NOVO fora da lista.

    python -m quant.dados.conferir_retorno_total [--limiar 0.95]
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

LIMIAR = 0.95
PASTA_TERMINAL = os.environ.get("AUTOPILOT_TERMINAL") or os.path.expanduser("~/Desktop/terminal-artefato")


def pasta_longo():
    return os.path.join(PASTA_TERMINAL, "cache", "out", "longo")


def disponivel():
    return os.path.isdir(pasta_longo()) and len(os.listdir(pasta_longo())) > 100


def serie_do_terminal(ticker):
    """Fechamento mensal ajustado a desdobramento e bonificacao (Series indexada pelo ultimo dia do mes) ou None."""
    try:
        with open(os.path.join(pasta_longo(), f"{ticker}.json"), encoding="utf-8") as f:
            d = json.load(f)
        s = pd.Series(d["c"], index=pd.to_datetime(d["t"]), dtype=float).dropna()
        return s[s > 0]
    except (OSError, ValueError, KeyError):
        return None


def casos(rt, tickers=None, limiar=LIMIAR, desde="2006-01-01", serie=serie_do_terminal, eventos=None):
    """DataFrame(ticker, mes, razao, lado, bruto, yahoo, indice, explicacao) com os meses em que o indice se afasta do preco ajustado: `lado` = "falta evento"
    (razao < limiar) ou "evento a mais" (razao > 1/limiar; num mes de dividendo grande isto e normal, por isso so "falta evento" reprova). `rt`: saida de
    `eventos.retorno_total_limpo` (colunas ticker, data, ret_preco, fator_acum). `bruto` = variacao do preco SEM ajuste no mes; `yahoo` = a do preco ajustado
    do terminal; `indice` = a do indice de retorno total. `explicacao` (so com `eventos`): por que a diferenca NAO e bonificacao ou desdobramento que falta:
      "subscricao"   a companhia teve direito de subscricao com data-ex no mes: o Yahoo ajusta o preco como se fosse desdobramento, o retorno total nao modela o direito;
      "yahoo_parado" o preco ajustado do Yahoo nao se mexeu (exatamente 1,000) enquanto o preco bruto andou mais de 3%: serie mensal velha/desatualizada do Yahoo;
      None           sem explicacao: e o que o teste cobra."""
    linhas = []
    sub = None
    if eventos is not None and len(eventos):
        e = eventos[eventos["tipo"] == "SUBSCRICAO"]
        sub = {(t, d.strftime("%Y-%m")) for t, d in zip(e["ticker"], pd.to_datetime(e["data_ex"])) if pd.notna(d)}
    por_ticker = {t: g for t, g in rt.groupby("ticker")} if tickers is None else {t: g for t, g in rt.groupby("ticker") if t in set(tickers)}
    for t, g in por_ticker.items():
        s = serie(t)
        if s is None or len(s) < 3:
            continue
        g = g.sort_values("data")
        f = g.set_index("data")["fator_acum"]
        f = f[~f.index.duplicated(keep="last")]
        cp = (1.0 + g.set_index("data")["ret_preco"].fillna(0.0)).cumprod()
        cp = cp[~cp.index.duplicated(keep="last")]
        meses = s.index[s.index >= pd.Timestamp(desde)]
        def _em(x, d):
            h = x[:d]
            return h.iloc[-1] if len(h) and (d - h.index[-1]).days <= 7 else np.nan
        fm = pd.Series([_em(f, d) for d in s.index], index=s.index)
        cm = pd.Series([_em(cp, d) for d in s.index], index=s.index)
        razao_y = s / s.shift(1)
        indice = fm / fm.shift(1)
        bruto = cm / cm.shift(1)
        razao = indice / razao_y
        for d in meses:
            r = razao.get(d)
            if r is None or not np.isfinite(r):
                continue
            lado = "falta evento" if r < limiar else ("evento a mais" if r > 1.0 / limiar else None)
            if lado is None:
                continue
            mes = d.strftime("%Y-%m")
            expl = None
            if sub is not None:
                if (t, mes) in sub:
                    expl = "subscricao"
                elif abs(razao_y.get(d) - 1.0) < 1e-3 and abs(bruto.get(d) - 1.0) > 0.03:
                    expl = "yahoo_parado"
            linhas.append((t, mes, float(r), lado, float(bruto.get(d)), float(razao_y.get(d)), float(indice.get(d)), expl))
    return pd.DataFrame(linhas, columns=["ticker", "mes", "razao", "lado", "bruto", "yahoo", "indice", "explicacao"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Indice de retorno total contra o preco ajustado do terminal, mes a mes")
    ap.add_argument("--limiar", type=float, default=LIMIAR)
    a = ap.parse_args(argv)
    from quant.dados import cotahist, eventos
    if not disponivel():
        print("serie mensal do terminal indisponivel")
        return 0
    cot = cotahist.carregar(2005, pd.Timestamp.now().year, colunas=["data", "ticker", "codbdi", "tpmerc", "fec", "fatcot"])
    cot = cot[(cot["tpmerc"].astype(str).str.strip() == "010") & (cot["codbdi"].astype(str).str.strip().str.zfill(2) == "02")]
    rt = eventos.retorno_total_limpo(cot[["ticker", "data", "fec", "fatcot"]], eventos.carregar_eventos())
    c = casos(rt, limiar=a.limiar)
    print(c["lado"].value_counts().to_dict(), "em", c["ticker"].nunique(), "papeis")
    return 0


if __name__ == "__main__":
    sys.exit(main())

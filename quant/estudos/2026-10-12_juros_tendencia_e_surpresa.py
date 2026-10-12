"""
Duas frentes novas, pedidas em 12/10/2026 ("procure mais formas de bater o mercado, nao limite o sistema ao Monte Carlo"):

 1. TENDENCIA EM JUROS (o que a Kadima declara fazer: tendencia de curto prazo em DI e dolar). Serie: taxa DI de 2 anos
    interpolada da curva da B3 (quant/saida/pesquisa5/dolar_dias/dados/di_curva.csv, 2002-2026, diaria). Regra pre-registrada:
    posicao no DI de 2 anos (comprado em taxa = vendido em PU) no sinal da variacao da taxa nos ultimos N pregoes (N = 63,
    126, 252: 3 tentativas), tamanho por volatilidade alvo de 10% a.a. (teto 1,5), decidida no fechamento e valendo do dia
    seguinte; resultado = -duration x variacao da taxa (duration ~ 1,8 ano para o vertice de 2 anos; sem carrego, que e
    pequeno em prazo de dias); custo 0,01% por unidade de exposicao negociada (DI1 e barato). DESENVOLVIMENTO 2005-2015,
    VALIDACAO 2016-2020, PROVA 2021-2026 NAO aberta. Criterio: Sharpe >= 0,5 nas duas janelas.
    Tambem: a tendencia de 63 pregoes do DI de 2 anos como SINAL para o indice (NEFIN Rm) e o dolar (PTAX): retorno medio dos
    20 pregoes seguintes quando a DI caiu x subiu (estudo de evento, sem custo), mesmas janelas.
 2. MECANISMO DA SURPRESA no dado americano: nos dias de payroll e CPI de 2021-2025, a direcao da reacao de 2 minutos do
    mini-dolar contra o sinal da surpresa ingenua (efetivo menos o anterior, pela API publica do BLS) e o que o mini-dolar
    fez nas 2 horas seguintes. Descritivo; so explica o setup que ja opera. Nao e tentativa de regra.
Rodar: cd ~/Desktop/quant-b3 && PYTHONPATH=. .venv/bin/python -W ignore quant/estudos/2026-10-12_juros_tendencia_e_surpresa.py
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
ARQ_DI = os.path.join(lab.PASTA, "dolar_dias", "dados", "di_curva.csv")
ARQ_PTAX = os.path.join(lab.PASTA, "dolar_dias", "dados", "ptax_venda_sgs1.csv")
ARQ_NEFIN = "quant/dados_brutos/nefin/fatores_093d49393521.csv.gz"
DURATION, VOL_ALVO, TETO, CUSTO = 1.8, 0.10, 1.5, 0.0001
JANELAS = {"desenvolvimento": ("2005-01-01", "2015-12-31"), "validacao": ("2016-01-01", "2020-12-31")}


def _sharpe(r):
    return float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if len(r) > 2 and r.std(ddof=1) > 0 else float("nan")


def di2():
    d = pd.read_csv(ARQ_DI, parse_dates=["data"]).set_index("data").sort_index()
    return d["di_2a"].astype(float) / 100.0


def tendencia_di(taxa, n):
    """Retorno diario da regra em fracao do nocional: posicao = sinal(variacao da taxa em n pregoes) x tamanho; ganha quando a
    taxa continua na mesma direcao (comprado em taxa ganha com alta)."""
    dr = taxa.diff()                                              # variacao diaria da taxa (fracao)
    ret_pu = -DURATION * dr                                       # retorno de quem esta COMPRADO em PU (aplicado)
    sinal = np.sign(taxa - taxa.shift(n))                         # taxa subiu em n pregoes: aposta que continua subindo
    vol = ret_pu.rolling(63).std() * np.sqrt(252)
    tam = (VOL_ALVO / vol).clip(upper=TETO)
    pos = (sinal * tam).shift(1)                                  # decidida no fechamento, vale amanha
    custo = pos.diff().abs().fillna(0.0) * CUSTO
    return (pos * (-ret_pu) - custo).dropna()                     # comprado em taxa = vendido em PU


def metricas(r):
    curva = (1 + r).cumprod()
    por_ano = (1 + r).groupby(r.index.year).prod() - 1
    return {"n": int(len(r)), "retorno_aa": round(float(curva.iloc[-1] ** (252 / len(r)) - 1), 4), "sharpe": round(_sharpe(r), 2),
            "queda_maxima": round(float((1 - curva / curva.cummax()).max()), 3), "anos_positivos": f"{int((por_ano > 0).sum())} de {len(por_ano)}"}


def sinal_di_para(ativo_ret, taxa, n=63, h=20):
    """Estudo de evento: retorno dos h pregoes seguintes do ativo quando a DI de 2 anos caiu (queda > 0,5 pp em n pregoes) contra
    quando subiu (> 0,5 pp), por janela. Sem sobreposicao: um evento a cada h pregoes."""
    var = (taxa - taxa.shift(n)).reindex(ativo_ret.index).ffill()
    fwd = ativo_ret.rolling(h).sum().shift(-h)
    fora = {}
    for nome, (ini, fim) in JANELAS.items():
        v, f = var.loc[ini:fim], fwd.loc[ini:fim]
        idx = f.index[::h]
        caiu, subiu, resto = f.loc[idx][v.loc[idx] < -0.005], f.loc[idx][v.loc[idx] > 0.005], f.loc[idx][v.loc[idx].abs() <= 0.005]
        fora[nome] = {k: {"n": int(len(x)), "media_pct": round(float(x.mean()) * 100, 2), "t": round(float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))), 2) if len(x) > 3 else None}
                      for k, x in (("di_caiu", caiu), ("di_subiu", subiu), ("estavel", resto)) if len(x.dropna())}
    return fora


def surpresa(m):
    """Nos dias de payroll e CPI: sinal da surpresa ingenua x direcao da reacao de 2 min x o que veio nas 2 horas seguintes."""
    mapa = ce.tipos_por_dia()
    h = lab.hm(m)
    verao = regras._verao_eua(m)
    alvo = np.where(verao, "09:31", "10:31")
    idx = np.where(h == alvo)[0]
    c = m["c"].to_numpy(dtype=float)
    linhas = []
    dias = lab.dia(m)
    for i in idx:
        d = pd.Timestamp(dias[i]).date()
        tipo = ce.tipo_do_dia(d, mapa)
        if tipo not in ("payroll", "cpi"):
            continue
        if i < 2 or i + 120 >= len(m) or dias[i + 120] != dias[i]:
            continue
        reac = c[i] - c[i - 2]                                    # fechamento do 2o minuto menos o anterior ao dado
        depois = c[i + 120] - c[i]                                # as 2 horas seguintes
        mes_ref = (pd.Timestamp(d) - pd.DateOffset(months=1)).replace(day=1)   # o dado do mes anterior sai neste mes
        s = ce.surpresa_ingenua("payroll" if tipo == "payroll" else "cpi", mes_ref)
        linhas.append({"dia": str(d), "tipo": tipo, "surpresa": s, "reacao_pts": round(float(reac), 1), "depois_pts": round(float(depois), 1)})
    t = pd.DataFrame(linhas)
    if t.empty:
        return {"n": 0}
    t["sinal_surpresa"] = np.sign(t["surpresa"].fillna(0.0))
    t["coerente"] = np.sign(t["reacao_pts"]) == t["sinal_surpresa"]    # payroll/CPI acima do anterior -> dolar sobe (juro americano sobe)
    grandes = t[t["reacao_pts"].abs() > 3]
    fora = {"n_dias": int(len(t)), "n_com_surpresa": int(t["surpresa"].notna().sum()),
            "reacao_coerente_com_surpresa_pct": round(float(t.loc[t["surpresa"].notna(), "coerente"].mean() * 100), 1),
            "reacao_grande_n": int(len(grandes)),
            "devolucao_media_pts_em_2h": round(float(-(np.sign(grandes["reacao_pts"]) * grandes["depois_pts"]).mean()), 2) if len(grandes) else None,
            "devolucao_quando_coerente": round(float(-(np.sign(grandes["reacao_pts"]) * grandes["depois_pts"])[grandes["coerente"]].mean()), 2) if grandes["coerente"].any() else None,
            "devolucao_quando_contra_surpresa": round(float(-(np.sign(grandes["reacao_pts"]) * grandes["depois_pts"])[~grandes["coerente"]].mean()), 2) if (~grandes["coerente"]).any() else None,
            "por_tipo": {k: {"n": int(len(g)), "reacao_mediana_abs": round(float(g["reacao_pts"].abs().median()), 1),
                             "coerente_pct": round(float(g.loc[g["surpresa"].notna(), "coerente"].mean() * 100), 1) if g["surpresa"].notna().any() else None}
                         for k, g in t.groupby("tipo")}}
    t.to_csv(os.path.join(PASTA, "surpresa_payroll_cpi.csv"), index=False)
    return fora


def main():
    os.makedirs(PASTA, exist_ok=True)
    taxa = di2()
    fora = {"tendencia_di_2a": {}}
    for n in (63, 126, 252):
        r = tendencia_di(taxa, n)
        fora["tendencia_di_2a"][f"N={n}"] = {k: metricas(r.loc[a:b]) for k, (a, b) in JANELAS.items()}
        with open(lab.REGISTRO, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tipo": "simulacao", "nome": f"tendencia DI 2 anos N={n}, vol alvo 10%", "familia": "tendencia_juros",
                                 **{k: fora["tendencia_di_2a"][f"N={n}"][k] for k in JANELAS}, "quando": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")},
                                ensure_ascii=False) + "\n")
    fora["veredito_tendencia_di"] = {k: ("passa" if v["desenvolvimento"]["sharpe"] >= 0.5 and v["validacao"]["sharpe"] >= 0.5 else "nao passa")
                                     for k, v in fora["tendencia_di_2a"].items()}
    f = pd.read_csv(ARQ_NEFIN)
    f["date"] = pd.to_datetime(f["Date"])
    rm = f.set_index("date").sort_index()["Rm_minus_Rf"].astype(float)
    ptax = pd.read_csv(ARQ_PTAX, parse_dates=["data"]).set_index("data")["valor"].astype(float).pct_change().dropna()
    fora["di_como_sinal"] = {"indice_nefin_20_pregoes": sinal_di_para(rm, taxa), "dolar_ptax_20_pregoes": sinal_di_para(ptax, taxa)}
    m = pd.concat([lab.carregar("WDO", "descoberta"), lab.carregar("WDO", "validacao")]).sort_index()
    fora["surpresa_dado"] = surpresa(m)
    print(json.dumps(fora, ensure_ascii=False, indent=1))
    with open(os.path.join(PASTA, "juros_tendencia_e_surpresa.json"), "w", encoding="utf-8") as fh:
        json.dump(fora, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

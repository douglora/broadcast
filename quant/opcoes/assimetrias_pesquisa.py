"""
Pesquisa de ASSIMETRIAS em opcoes (hipoteses A0 a A6 em quant/saida/pesquisa5/opcoes/HIPOTESES_ASSIMETRIAS.md, escritas antes de rodar).

Cada teste devolve um dicionario de numeros; `rodar()` roda tudo, grava `resultados_assimetrias.json` e as linhas de
`tentativas.jsonl` (familias novas A0..A6). Corredor: descoberta ate 2019, validacao 2020-2023, prova 2024-2026 SO para quem
passar nas duas fases (uma vez, parametros congelados). Passar de fase:
  estrategias (retorno mensal): excesso medio positivo, Sharpe mensal anualizado > 0,3 e >= 24 meses / 30 operacoes
  previsao (IC por postos): descoberta |t| >= 2 no sinal esperado; validacao mesmo sinal com |t| >= 1,5
  operacoes avulsas (A6, A5): media liquida positiva, t >= 2 (descoberta) e >= 1,5 (validacao), mesma regra de n

  PYTHONPATH=. .venv/bin/python -W ignore -m quant.opcoes.assimetrias_pesquisa
"""
import json
import math
import os

import numpy as np
import pandas as pd
from scipy import stats

from quant.opcoes import bs, dados, metricas
from quant.opcoes import custos as C
from quant.opcoes.base import DIR_DADOS, DIR_OPC
from quant.opcoes.painel_vol import carregar as carregar_painel
from quant.opcoes.pesquisa import PERIODOS

ARQ = os.path.join(DIR_OPC, "resultados_assimetrias.json")
FEE = C.FEE_PREMIO
SHARPE_MIN = 0.3
PROVA_ABERTA = []          # nomes das configuracoes cuja prova foi aberta (uma vez cada)


def _periodo(d, per, col="T"):
    a, b = PERIODOS[per]
    return d[(d[col] >= pd.Timestamp(a)) & (d[col] <= pd.Timestamp(b))]


# -------------------------------------------------------------------------------------------------------------- base comum
def carregar_base():
    cad = pd.read_parquet(os.path.join(DIR_DADOS, "cadeia_preparada.parquet"))
    cic = pd.read_parquet(os.path.join(DIR_DADOS, "ciclos.parquet"))
    cic["cdi_ciclo"] = [dados.acumular_cdi(e, t) - 1.0 for e, t in zip(cic["E"], cic["T"])]
    pv = carregar_painel()
    from quant.opcoes import pozinho
    uni = pozinho.universo_por_ano()
    cad = cad[[a in uni.get(y, set()) for a, y in zip(cad["ativo"], cad["E"].dt.year)]].copy()
    cols = ["ativo", "dia", "iv_atm30", "vr20", "vr60", "vr252", "perc_vi", "perc_skew", "skew_put", "skew_call", "desvio_paridade", "vr_menos_vi60", "vr_menos_vi252"]
    cad = cad.merge(pv[cols].rename(columns={"dia": "E"}), on=["ativo", "E"], how="left", suffixes=("", "_pv"))
    return cad, cic, pv


def liq(cad, tipo, neg=20, spr=0.30):
    m = ((cad["tipo"] == tipo) & cad["escolhido"] & cad["oferta_compra"].notna() & cad["oferta_venda"].notna() & (cad["oferta_compra"] > 0)
         & (cad["oferta_venda"] > cad["oferta_compra"]) & (cad["negocios"] >= neg) & (cad["spread"] <= spr)
         & cad["S_E"].notna() & cad["S_T"].notna() & (cad["K_T"] > 0))
    return cad[m]


def straddles(cad, neg=10, spr=0.40, dist=0.05):
    """Uma linha por (ativo, E): call e put de mesmo exercicio mais perto do dinheiro (<= 4%), custo na oferta de venda."""
    c = liq(cad, "C", neg, spr)
    p = liq(cad, "P", neg, spr)
    k = ["ativo", "E", "T", "exercicio"]
    m = c.merge(p, on=k, suffixes=("_c", "_p"))
    m["dist"] = (m["exercicio"] / m["S_E_c"] - 1.0).abs()
    m = m[m["dist"] <= dist].sort_values(["ativo", "E", "dist", "negocios_c"], ascending=[True, True, True, False]).drop_duplicates(["ativo", "E"])
    out = pd.DataFrame({
        "ativo": m["ativo"], "E": m["E"], "T": m["T"], "K": m["exercicio"], "S_E": m["S_E_c"], "cdi": m["cdi_ciclo_c"],
        "custo_c": m["oferta_venda_c"] * (1 + FEE), "custo_p": m["oferta_venda_p"] * (1 + FEE),
        "pay_c": m["payoff_T_c"] * (1 - FEE), "pay_p": m["payoff_T_p"] * (1 - FEE),
        "iv_c": m["iv_c"], "iv_p": m["iv_p"], "bid_c": m["oferta_compra_c"], "bid_p": m["oferta_compra_p"],
        "vr20": m["vr20_c"], "vr60": m["vr60_c"], "vr252": m["vr252_c"], "iv_atm30": m["iv_atm30_c"], "perc_vi": m["perc_vi_c"],
        "perc_skew": m["perc_skew_c"], "skew_put": m["skew_put_c"], "desvio_paridade": m["desvio_paridade_c"],
        "vr_menos_vi60": m["vr_menos_vi60_c"], "vr_menos_vi252": m["vr_menos_vi252_c"], "tr": m["tr_c"],
    })
    out["custo"] = out["custo_c"] + out["custo_p"]
    out["ret_straddle"] = (out["pay_c"] + out["pay_p"]) / out["custo"] - 1.0 - out["cdi"]
    out["ret_call"] = out["pay_c"] / out["custo_c"] - 1.0 - out["cdi"]
    out["ret_put"] = out["pay_p"] / out["custo_p"] - 1.0 - out["cdi"]
    return out.reset_index(drop=True)


# -------------------------------------------------------------------------------------------------------------- utilitarios
def serie_mensal(df, col, cic, per, filtro=None):
    """Retorno medio por mes (igual peso nas operacoes do mes; mes sem operacao = 0) -> DataFrame por ciclo T."""
    a, b = PERIODOS[per]
    cc = cic[(cic["T"] >= pd.Timestamp(a)) & (cic["T"] <= pd.Timestamp(b))][["E", "T", "du", "cdi_ciclo"]].copy()
    d = df if filtro is None else df[filtro(df)]
    g = d.groupby("T")[col].agg(["mean", "count"])
    cc["ex"] = cc["T"].map(g["mean"]).fillna(0.0)
    cc["n_ops"] = cc["T"].map(g["count"]).fillna(0).astype(int)
    cc["cdi"] = cc["cdi_ciclo"]
    return cc


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and x != x) else round(float(x), n)


def teste_t(x):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 5 or x.std(ddof=1) == 0:
        return None
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x))))


def resumo_estrategia(s, familia, config, per, n_tent):
    """Metricas de uma serie mensal de retorno POR OPERACAO (media por R$ 1 de custo): media, t, Sharpe mensal anualizado."""
    if len(s) < 6:
        return {"n_meses": int(len(s))}
    x = s["ex"].values
    com = s["n_ops"].values > 0
    n_ops = int(s["n_ops"].sum())
    sd = x.std(ddof=1)
    sh = float(x.mean() / sd * math.sqrt(len(x) / (s["du"].sum() / 252.0))) if sd > 0 else 0.0
    from quant.pesquisa import ldp
    d = ldp.dsr(x, n_tent) if n_tent else None
    m = {"n_meses": int(len(x)), "n_meses_com_op": int(com.sum()), "n_ops": n_ops, "media_por_op_pct": round(float(x[com].mean() * 100), 2) if com.any() else None,
         "media_mes_pct": round(float(x.mean() * 100), 3), "t": _r(teste_t(x[com])) if com.sum() > 5 else None,
         "sharpe": round(sh, 3), "pct_meses_positivos": round(float((x[com] > 0).mean() * 100), 1) if com.any() else None,
         "pior_mes_por_op_pct": round(float(x[com].min() * 100), 1) if com.any() else None, "melhor_mes_por_op_pct": round(float(x[com].max() * 100), 1) if com.any() else None,
         "sharpe_deflacionado": round(float(d), 3) if d is not None and d == d else None, "n_tentativas": n_tent}
    metricas.registrar(familia, config, per, m)
    return m


def passou_estrategia(m):
    return bool(m.get("n_ops", 0) >= 30 and m.get("n_meses", 0) >= 24 and (m.get("media_mes_pct") or -1) > 0 and (m.get("sharpe") or -9) > SHARPE_MIN)


# -------------------------------------------------------------------------------------------------------------- A1
def a1(cad, cic, pv, sd):
    fam, res = "A1_vol_barata", {}
    S = straddles(cad)
    S = S[S["vr60"].notna() & S["iv_atm30"].notna()]
    cfgs = []
    # tercil por mes de (VR - VI): barato = tercil de cima
    def _grupos(x):
        # >= 6 ativos no mes: tercis (2 = barato, 0 = caro); 4 ou 5 ativos: metades; menos de 4: o mes fica de fora
        if len(x) >= 6:
            return pd.qcut(x.rank(method="first"), 3, labels=False)
        if len(x) >= 4:
            return pd.Series(np.where(x.rank(method="first") > len(x) / 2, 2, 0), index=x.index)
        return pd.Series(np.nan, index=x.index)
    for sinal in ("vr_menos_vi60", "vr_menos_vi252"):
        S[f"q_{sinal}"] = S.groupby("E")[sinal].transform(_grupos)
    S["q_sinal60"] = np.where(S["vr_menos_vi60"] > 0, 2, 0)
    cfgs += [("straddle_barato_vr60", "ret_straddle", lambda d: d["q_vr_menos_vi60"] == 2), ("straddle_caro_vr60", "ret_straddle", lambda d: d["q_vr_menos_vi60"] == 0),
             ("straddle_barato_vr252", "ret_straddle", lambda d: d["q_vr_menos_vi252"] == 2), ("straddle_caro_vr252", "ret_straddle", lambda d: d["q_vr_menos_vi252"] == 0),
             ("call_barata_vr60", "ret_call", lambda d: d["q_vr_menos_vi60"] == 2), ("put_barata_vr60", "ret_put", lambda d: d["q_vr_menos_vi60"] == 2),
             ("straddle_vr60_maior_vi", "ret_straddle", lambda d: d["q_sinal60"] == 2), ("straddle_vr60_menor_vi", "ret_straddle", lambda d: d["q_sinal60"] == 0),
             ("straddle_perc_vi_menor_20", "ret_straddle", lambda d: d["perc_vi"] < 20), ("straddle_perc_vi_maior_80", "ret_straddle", lambda d: d["perc_vi"] > 80),
             ("straddle_todos", "ret_straddle", lambda d: d["ret_straddle"].notna())]
    n_cfg = len(cfgs) + 2          # + 2 estruturas vendidas de risco definido (abaixo)
    out = {}
    for nome, col, f in cfgs:
        out[nome] = {}
        for per in ("descoberta", "validacao"):
            s = serie_mensal(S, col, cic, per, f)
            out[nome][per] = resumo_estrategia(s, fam, nome, per, n_cfg)
    # spread barato - caro (a hipotese central)
    for sinal in ("vr60", "vr252"):
        b = S[S[f"q_vr_menos_vi{sinal[2:]}"] == 2].groupby("E")["ret_straddle"].mean()
        c = S[S[f"q_vr_menos_vi{sinal[2:]}"] == 0].groupby("E")["ret_straddle"].mean()
        dif = (b - c).dropna()
        d = dif.to_frame("dif").join(S.drop_duplicates("E").set_index("E")["T"])
        out[f"spread_barato_menos_caro_{sinal}"] = {per: {"n_meses": int(len(_periodo(d, per))), "media_pct": _r(_periodo(d, per)["dif"].mean() * 100),
                                                           "t": _r(teste_t(_periodo(d, per)["dif"].values))} for per in ("descoberta", "validacao")}
    # estruturas vendidas de RISCO DEFINIDO quando perc_vi > 80: trava de credito com puts (delta 0,25, largura 5%) e condor (+ call)
    from quant.opcoes import motor
    for nome, tipos in (("trava_credito_put_perc_vi_maior_80", ("P",)), ("condor_perc_vi_maior_80", ("P", "C"))):
        t = _credito(cad, tipos, 0.25, 0.05, condicao=lambda d: d["perc_vi"] > 80)
        out[nome] = {}
        for per in ("descoberta", "validacao"):
            s = serie_mensal(t, "ex_risco", cic, per)
            out[nome][per] = resumo_estrategia(s, fam, nome, per, n_cfg)
        tb = _credito(cad, tipos, 0.25, 0.05, condicao=lambda d: d["perc_vi"] <= 80)
        out[nome + "_contraste_perc_vi_ate_80"] = {per: resumo_estrategia(serie_mensal(tb, "ex_risco", cic, per), fam, nome + "_contraste", per, n_cfg) for per in ("descoberta", "validacao")}
    # aprovacao da familia: o melhor candidato COMPRADO pre-declarado (straddle barato por vr60) e os demais
    passou = [n for n, v in out.items() if isinstance(v, dict) and "descoberta" in v and "n_ops" in v["descoberta"] and passou_estrategia(v["descoberta"]) and passou_estrategia(v["validacao"])
              and not n.endswith("contraste_perc_vi_ate_80") and "todos" not in n and "caro" not in n]
    res["configs"] = out
    res["n_configuracoes"] = n_cfg
    res["passaram_descoberta_e_validacao"] = passou
    return res, S


def _credito(cad, tipos, delta, largura, condicao=None):
    """Trava(s) de credito de risco definido por (ativo, E): put (e call) vendida de |delta| ~ `delta` e comprada `largura` x S mais longe.
    Retorna ex_risco = (credito*(1+cdi) - perda no vencimento)/risco maximo. Condor = soma das duas travas com o risco da maior."""
    linhas = []
    base = cad if condicao is None else cad[condicao(cad)]
    for ativo_E, g in base.groupby(["ativo", "E"]):
        partes = []
        for tp in tipos:
            el = liq(g, tp, 30, 0.30)
            if el.empty:
                partes = None
                break
            el = el.assign(dist=(el["delta"].abs() - delta).abs())
            curta = el[el["dist"] <= 0.06].sort_values(["dist", "negocios"], ascending=[True, False])
            if curta.empty:
                partes = None
                break
            c = curta.iloc[0]
            alvo = c["exercicio"] - largura * c["S_E"] if tp == "P" else c["exercicio"] + largura * c["S_E"]
            cand = el[(el["exercicio"] < c["exercicio"]) if tp == "P" else (el["exercicio"] > c["exercicio"])]
            if cand.empty:
                partes = None
                break
            cand = cand.assign(dk=(cand["exercicio"] - alvo).abs()).sort_values(["dk", "negocios"], ascending=[True, False])
            l = cand.iloc[0]
            if l["dk"] > 0.5 * largura * c["S_E"]:
                partes = None
                break
            cred = c["oferta_compra"] * (1 - FEE) - l["oferta_venda"] * (1 + FEE)
            larg = abs(c["exercicio"] - l["exercicio"])
            if cred <= 0 or cred >= larg:
                partes = None
                break
            perda = c["payoff_T"] - l["payoff_T"]
            partes.append((cred, larg, perda, c["cdi_ciclo"], c["T"]))
        if not partes:
            continue
        cred = sum(p[0] for p in partes)
        perda = sum(p[2] for p in partes)
        risco = max(p[1] for p in partes) - cred            # condor: so uma das pontas pode perder
        if risco <= 0:
            continue
        ex = (cred * (1 + partes[0][3]) - perda) / risco
        linhas.append({"ativo": ativo_E[0], "E": ativo_E[1], "T": partes[0][4], "ex_risco": float(ex), "risco": float(risco), "credito": float(cred)})
    return pd.DataFrame(linhas, columns=["ativo", "E", "T", "ex_risco", "risco", "credito"])


# -------------------------------------------------------------------------------------------------------------- A2
def a2(cad, cic, pv):
    """Proteger na hora barata (BOVA11, 2020-2026): put delta -0,25 so com percentil da VI < 30, contra sempre e contra nunca."""
    from quant.opcoes import protecao
    c = protecao.simular(cad.merge(cad[["ativo", "E"]].drop_duplicates().assign(_x=1), on=["ativo", "E"], how="left").drop(columns="_x"), cic)
    b = pv[pv["ativo"] == "BOVA11"][["dia", "perc_vi", "iv_atm30"]].rename(columns={"dia": "E"})
    c = c.merge(b, on="E", how="left")
    barato = (c["perc_vi"] < 30)
    c["ex_barato"] = np.where(barato & c["tem_put"], c["ex_put"], c["ex_nu"])
    c["ex_colar_barato"] = np.where(barato & c["tem_colar"], c["ex_colar"], c["ex_nu"])
    c["custo_sempre"] = np.where(c["tem_put"], c["custo_put_pct"], 0.0)
    c["custo_barato"] = np.where(barato & c["tem_put"], c["custo_put_pct"], 0.0)
    out = {"meses_barato": int(barato.sum()), "meses": int(len(c)), "variantes": {}}
    var = {"nunca": "ex_nu", "sempre_put": "ex_put", "so_barato_put": "ex_barato", "sempre_colar": "ex_colar", "so_barato_colar": "ex_colar_barato"}
    for per, (a, b_) in {"2020-2023": ("2020-01-01", "2023-12-31")}.items():
        x = c[(c["T"] >= a) & (c["T"] <= b_)]
        anos = x["du"].sum() / 252.0
        for nome, col in var.items():
            m = metricas.calcular(x[col].values, x["cdi_ciclo"].values, None, x["E"].iloc[0], x["T"].iloc[-1], anos=anos)
            if nome in ("sempre_put", "so_barato_put"):
                m["custo_bruto_anual_pct"] = round(float((x["custo_sempre"] if nome == "sempre_put" else x["custo_barato"]).sum() / anos), 2)
            out["variantes"].setdefault(nome, {})[per] = {k: m.get(k) for k in ("n_ciclos", "retorno_anual_pct", "cdi_anual_pct", "excesso_anual_pct", "queda_maxima_pct", "pior_mes_pct", "custo_bruto_anual_pct")}
    j = c[c["T"] == pd.Timestamp("2020-03-16")]
    out["mar2020"] = {"perc_vi_na_entrada": _r(j["perc_vi"].iloc[0]) if len(j) else None, "iv_atm30_na_entrada": _r(j["iv_atm30"].iloc[0], 3) if len(j) else None}
    if len(j):
        for n, col in var.items():
            out["mar2020"][n] = _r(float(j[col].iloc[0] + j["cdi_ciclo"].iloc[0]) * 100)
    jj = c[(c["T"] >= "2021-01-01") & (c["T"] <= "2022-12-31")]
    out["2021_22"] = {n: _r((np.prod(1 + jj[col].values + jj["cdi_ciclo"].values) - 1) * 100) for n, col in var.items()}
    for nome in var:
        metricas.registrar("A2_protecao_barata", nome, "2020-2023", out["variantes"][nome]["2020-2023"])
    out["n_configuracoes"] = len(var)
    # criterio declarado: custo anual menor em >= 30% que o de proteger sempre, cobertura de mar/2020 (ciclo >= -10%) e retorno a.a. >= o de proteger sempre
    s, b2 = out["variantes"]["sempre_put"]["2020-2023"], out["variantes"]["so_barato_put"]["2020-2023"]
    out["passou"] = bool(b2["custo_bruto_anual_pct"] <= 0.7 * s["custo_bruto_anual_pct"] and (out["mar2020"].get("so_barato_put") or -99) >= -10
                         and b2["retorno_anual_pct"] >= s["retorno_anual_pct"])
    out["nota"] = "2024-2026 nao aberto: a variante so_barato nao passou em 2020-2023"
    return out


# -------------------------------------------------------------------------------------------------------------- A3 (i)
def _debito_put(cad, condicao=None, d_long=0.30, d_short=0.10):
    linhas = []
    base = cad if condicao is None else cad[condicao(cad)]
    for (a, E), g in base.groupby(["ativo", "E"]):
        el = liq(g, "P", 30, 0.30)
        if el.empty:
            continue
        l = el.assign(dist=(el["delta"].abs() - d_long).abs()).sort_values(["dist", "negocios"], ascending=[True, False])
        l = l[l["dist"] <= 0.07]
        s = el.assign(dist=(el["delta"].abs() - d_short).abs()).sort_values(["dist", "negocios"], ascending=[True, False])
        s = s[s["dist"] <= 0.06]
        if l.empty or s.empty:
            continue
        l, s = l.iloc[0], s.iloc[0]
        if not s["exercicio"] < l["exercicio"]:
            continue
        deb = l["oferta_venda"] * (1 + FEE) - s["oferta_compra"] * (1 - FEE)
        if deb <= 0 or deb >= l["exercicio"] - s["exercicio"]:
            continue
        pay = (l["payoff_T"] - s["payoff_T"]) * (1 - FEE)
        linhas.append({"ativo": a, "E": E, "T": l["T"], "ex": pay / deb - 1.0 - l["cdi_ciclo"], "debito": deb})
    return pd.DataFrame(linhas, columns=["ativo", "E", "T", "ex", "debito"])


def a3_estruturas(cad, cic):
    fam, out = "A3_inclinacao", {}
    pares = [("trava_credito_put_skew_maior_80", lambda: _credito(cad, ("P",), 0.25, 0.05, lambda d: d["perc_skew"] > 80), "ex_risco"),
             ("trava_credito_put_skew_ate_80", lambda: _credito(cad, ("P",), 0.25, 0.05, lambda d: d["perc_skew"] <= 80), "ex_risco"),
             ("trava_baixa_debito_skew_menor_20", lambda: _debito_put(cad, lambda d: d["perc_skew"] < 20), "ex"),
             ("trava_baixa_debito_skew_a_partir_20", lambda: _debito_put(cad, lambda d: d["perc_skew"] >= 20), "ex")]
    n_cfg = len(pares) + 4        # + 4 testes de previsao (ver a3_previsao)
    for nome, f, col in pares:
        t = f()
        out[nome] = {per: resumo_estrategia(serie_mensal(t, col, cic, per), fam, nome, per, n_cfg) for per in ("descoberta", "validacao")}
    out["passaram"] = [n for n in ("trava_credito_put_skew_maior_80", "trava_baixa_debito_skew_menor_20")
                       if passou_estrategia(out[n]["descoberta"]) and passou_estrategia(out[n]["validacao"])]
    return out


def ic_cross(pv, sinal, fut, esperado, per, passo, min_ativos=8):
    a, b = PERIODOS[per]
    d = pv[(pv["dia"] >= pd.Timestamp(a)) & (pv["dia"] <= pd.Timestamp(b))][["ativo", "dia", sinal, fut]].dropna()
    dias = sorted(d["dia"].unique())[::passo]
    ics, spreads = [], []
    for dia in dias:
        g = d[d["dia"] == dia]
        if len(g) < min_ativos or g[sinal].nunique() < 4:
            continue
        ics.append(stats.spearmanr(g[sinal], g[fut])[0])
        q = pd.qcut(g[sinal].rank(method="first"), 5, labels=False)
        spreads.append(g[fut][q == 4].mean() - g[fut][q == 0].mean())
    ics, spreads = np.array(ics), np.array(spreads)
    if len(ics) < 8:
        return {"n_datas": int(len(ics))}
    t = float(ics.mean() / (ics.std(ddof=1) / math.sqrt(len(ics))))
    ts = float(spreads.mean() / (spreads.std(ddof=1) / math.sqrt(len(spreads))))
    return {"n_datas": int(len(ics)), "ic_medio": round(float(ics.mean()), 4), "t": round(t, 2), "spread_q5_menos_q1_pct": round(float(spreads.mean() * 100), 2), "t_spread": round(ts, 2),
            "ativos_por_data": round(float(d.groupby("dia").size().reindex(dias).dropna().mean()), 1), "sinal_esperado": esperado}


def ic_series(pv, ativo, sinal, fut, per, passo):
    a, b = PERIODOS[per]
    d = pv[(pv["ativo"] == ativo) & (pv["dia"] >= pd.Timestamp(a)) & (pv["dia"] <= pd.Timestamp(b))][["dia", sinal, fut]].dropna().iloc[::passo]
    if len(d) < 12:
        return {"n_datas": int(len(d))}
    r = stats.spearmanr(d[sinal], d[fut])[0]
    t = r * math.sqrt((len(d) - 2) / max(1e-9, 1 - r * r))
    return {"n_datas": int(len(d)), "ic": round(float(r), 4), "t": round(float(t), 2)}


def a3_a4_previsao(pv):
    """A3 (ii) inclinacao e A4 paridade: IC por postos com o retorno futuro de 5 e 21 pregoes."""
    out = {}
    testes = [("A3_inclinacao", "skew_put", -1), ("A4_paridade", "desvio_paridade", +1)]
    for fam, sinal, esp in testes:
        for fut, passo in (("fut5", 5), ("fut21", 21)):
            nome = f"{sinal}_vs_{fut}"
            blocos = {}
            for per in ("descoberta", "validacao"):
                blocos[per] = {"corte_entre_acoes": ic_cross(pv, sinal, fut, esp, per, passo), "BOVA11": ic_series(pv, "BOVA11", sinal, fut, per, passo)}
            ok_d = (blocos["descoberta"]["corte_entre_acoes"].get("t") or 0) * esp >= 2.0
            ok_v = (blocos["validacao"]["corte_entre_acoes"].get("t") or 0) * esp >= 1.5
            blocos["passou"] = bool(ok_d and ok_v)
            out[nome] = blocos
            metricas.registrar(fam, nome, "descoberta+validacao", {"descoberta": blocos["descoberta"]["corte_entre_acoes"], "validacao": blocos["validacao"]["corte_entre_acoes"]})
    return out


# -------------------------------------------------------------------------------------------------------------- A6
def a6(pv_unused=None):
    """Straddle no dinheiro comprado 5 pregoes antes do protocolo do resultado na CVM e vendido no dia seguinte.
    Entrada: oferta de venda do fechamento do dia (protocolo - 5 pregoes), vencimento mensal com >= 10 pregoes depois da saida.
    Saida: oferta de COMPRA do fechamento do dia seguinte ao protocolo (as duas pernas precisam ter oferta de compra nesse dia)."""
    from quant.opcoes import pozinho
    dias = dados.dias_de_pregao()
    ident = pd.read_parquet(os.path.join(dados.DIR_BANCO, "identidade.parquet"))
    datas = pozinho.datas_de_resultado()
    uni = pozinho.universo_por_ano()
    op = dados.carregar_opcoes(2012, 2026, colunas=["dia", "codigo", "ativo", "tipo", "exercicio", "vencimento", "fech", "oferta_compra", "oferta_venda", "negocios", "semanal"])
    op = op[~op["semanal"]]
    sp = pd.concat([pd.read_parquet(os.path.join(DIR_DADOS, f"ativo_{y}.parquet"), columns=["ativo", "dia", "fech", "fatcot"]) for y in range(2012, 2027)])
    sp = sp[(sp["fatcot"] == 1) & (sp["fech"] > 0)].drop_duplicates(["ativo", "dia"]).set_index(["ativo", "dia"])["fech"]
    ev = []
    for ativo in sorted(set().union(*uni.values())):
        cd = pozinho.cd_cvm_de(ativo, ident)
        arr = datas.get(cd or "", None)
        if arr is None or ativo == "BOVA11":
            continue
        for d in np.unique(arr.astype("datetime64[D]")):
            F = pd.Timestamp(d)
            if F < pd.Timestamp("2012-03-01") or F > pd.Timestamp("2026-09-01") or ativo not in uni.get(F.year, set()):
                continue
            i = int(np.searchsorted(dias.values, np.datetime64(F)))
            if i >= len(dias) - 2 or i < 6:
                continue
            ev.append({"ativo": ativo, "F": F, "entrada": dias[i - 5] if dias[i] == F else dias[i - 5], "saida": dias[i + 1] if dias[i] == F else dias[i]})
    ev = pd.DataFrame(ev).drop_duplicates(["ativo", "F"])
    # series na entrada
    e_ = ev.merge(op, left_on=["ativo", "entrada"], right_on=["ativo", "dia"], how="inner")
    e_ = e_[(e_["oferta_venda"] > 0) & (e_["negocios"] >= 5)]
    du = (np.searchsorted(dias.values, e_["vencimento"].values.astype("datetime64[ns]")) - np.searchsorted(dias.values, e_["saida"].values.astype("datetime64[ns]")))
    e_ = e_[du >= 10]
    e_["S"] = [sp.get((a, d), np.nan) for a, d in zip(e_["ativo"], e_["entrada"])]
    e_["dist"] = (e_["exercicio"] / e_["S"] - 1.0).abs()
    # primeiro vencimento disponivel por evento, strike mais perto do dinheiro que tenha call e put
    e_["vdist"] = e_["vencimento"]
    prim = e_.groupby(["ativo", "F"])["vdist"].min().rename("v1").reset_index()
    e_ = e_.merge(prim, on=["ativo", "F"])
    e_ = e_[e_["vencimento"] == e_["v1"]]
    c = e_[e_["tipo"] == "C"]
    p = e_[e_["tipo"] == "P"]
    k = ["ativo", "F", "entrada", "saida", "vencimento", "exercicio"]
    m = c.merge(p, on=k, suffixes=("_c", "_p"))
    m = m[m["dist_c"] <= 0.05].sort_values(["ativo", "F", "dist_c"]).drop_duplicates(["ativo", "F"])
    # saida
    sx = op[["ativo", "dia", "codigo", "oferta_compra"]].rename(columns={"dia": "saida", "oferta_compra": "bid_saida"})
    m = m.merge(sx.rename(columns={"codigo": "codigo_c", "bid_saida": "bid_c"}), on=["ativo", "saida", "codigo_c"], how="left")
    m = m.merge(sx.rename(columns={"codigo": "codigo_p", "bid_saida": "bid_p"}), on=["ativo", "saida", "codigo_p"], how="left")
    total = len(m)
    m = m[(m["bid_c"] > 0) & (m["bid_p"] > 0)]
    m["custo"] = (m["oferta_venda_c"] + m["oferta_venda_p"]) * (1 + FEE)
    m["valor_saida"] = (m["bid_c"] + m["bid_p"]) * (1 - FEE)
    m["ret"] = m["valor_saida"] / m["custo"] - 1.0
    m["T"] = m["saida"]
    m["S_in"] = [sp.get((a, d), np.nan) for a, d in zip(m["ativo"], m["entrada"])]
    m["S_out"] = [sp.get((a, d), np.nan) for a, d in zip(m["ativo"], m["saida"])]
    return m, {"eventos_com_serie_na_entrada": int(total), "eventos_com_saida_cotada": int(len(m)), "eventos_brutos": int(len(ev))}


def a6_resumo(m, meta, n_tent=1):
    """Resume A6. O por-ano so vai ate 2023: a prova 2024-2026 nao se abre para quem nao passou."""
    fam, out = "A6_pre_resultado", {"meta": meta}
    for per in ("descoberta", "validacao"):
        x = _periodo(m, per)["ret"].values
        out[per] = {"n": int(len(x)), "media_pct": _r(x.mean() * 100) if len(x) else None, "mediana_pct": _r(np.median(x) * 100) if len(x) else None,
                    "t": _r(teste_t(x)), "pct_positivos": _r((x > 0).mean() * 100, 1) if len(x) else None,
                    "pior_pct": _r(x.min() * 100, 1) if len(x) else None, "melhor_pct": _r(x.max() * 100, 1) if len(x) else None}
        metricas.registrar(fam, "straddle_5_pregoes_antes_do_protocolo", per, out[per])
    mm = m[m["T"] <= pd.Timestamp("2023-12-31")]
    por_ano = mm.groupby(mm["T"].dt.year)["ret"].agg(["mean", "count"])
    out["por_ano_media_pct"] = {int(a): _r(r["mean"] * 100, 1) for a, r in por_ano.iterrows()}
    d, v = out["descoberta"], out["validacao"]
    out["passou"] = bool((d["n"] or 0) >= 30 and (v["n"] or 0) >= 30 and (d["media_pct"] or -1) > 0 and (v["media_pct"] or -1) > 0 and (d["t"] or 0) >= 2.0 and (v["t"] or 0) >= 1.5)
    out["n_configuracoes"] = n_tent
    return out


# -------------------------------------------------------------------------------------------------------------- A0
def a0(cad1, cic):
    from quant.opcoes import capital_protegido as cp
    fam = "A0_capital_protegido"
    comp = pd.read_parquet(os.path.join(DIR_DADOS, "a0_compras.parquet"))
    desc_ativos, val_ativos = ["PETR4", "VALE"], ["PETR4", "VALE", "BOVA11", "ITUB4", "BBDC4", "BBAS3"]
    n_cfg = len(cp.VARIANTES) * len(cp.ORCAMENTOS)
    out = {"variantes": {}, "por_ativo": {}, "n_configuracoes": n_cfg}
    for v in cp.VARIANTES:
        for pct in cp.ORCAMENTOS:
            nome = f"{v} orcamento={pct * 100:.1f}%"
            blocos = {}
            for per, ativos in (("descoberta", desc_ativos), ("validacao", val_ativos)):
                a, b = PERIODOS[per]
                d, trm = cp.cesta(ativos, v, pct, a, b, comp, cic, cad1)
                m = cp.metricas_variante(d, trm, n_tent=n_cfg)
                blocos[per] = m
                metricas.registrar(fam, nome, per, m)
            ok = all((blocos[p].get("n_ops", 0) >= 30 and blocos[p].get("n_ciclos", 0) >= 24 and (blocos[p].get("excesso_anual_pct") or -1) > 0
                      and (blocos[p].get("sharpe") or -9) > SHARPE_MIN) for p in blocos)
            blocos["passou_descoberta_e_validacao"] = bool(ok)
            out["variantes"][nome] = blocos
    # por ativo (orcamento de 0,5%), descoberta e validacao, descritivo
    for g in cp.INICIO_ATIVO:
        tr = cp.retorno_do_ativo(g, cic, cad1)
        for v in cp.VARIANTES:
            blocos = {}
            for per in ("descoberta", "validacao"):
                a, b = PERIODOS[per]
                a = max(pd.Timestamp(a), pd.Timestamp(cp.INICIO_ATIVO[g]))
                if a > pd.Timestamp(b):
                    continue
                d = cp.simular(g, v, 0.005, comp, cic, a, b)
                if len(d) >= 12:
                    blocos[per] = cp.metricas_variante(d, tr)
            out["por_ativo"][f"{g} {v}"] = blocos
    out["passaram"] = [n for n, b in out["variantes"].items() if b["passou_descoberta_e_validacao"]]
    # PROVA 2024-2026: uma vez, so das que passaram nas duas fases
    out["prova"], out["prova_por_ativo"] = {}, {}
    for nome in out["passaram"]:
        v, pct = nome.split(" orcamento=")[0], float(nome.split("=")[1].rstrip("%")) / 100
        a, b = PERIODOS["prova"]
        d, trm = cp.cesta(val_ativos, v, pct, a, b, comp, cic, cad1)
        m = cp.metricas_variante(d, trm, n_tent=n_cfg)
        out["prova"][nome] = m
        metricas.registrar(fam, nome, "prova", m, nota="PROVA aberta uma vez (passou descoberta e validacao)")
        PROVA_ABERTA.append(("A0", nome))
        out["prova_por_ativo"][nome] = {g: cp.metricas_variante(cp.simular(g, v, pct, comp, cic, max(pd.Timestamp(a), pd.Timestamp(cp.INICIO_ATIVO[g])), b),
                                                              cp.retorno_do_ativo(g, cic, cad1)) for g in val_ativos}
    # serie completa 2012-2026 (descoberta 2 ativos + validacao e prova com 6) para o quadro do painel -- so de quem passou
    out["historico_completo"] = {}
    for nome in out["passaram"]:
        v, pct = nome.split(" orcamento=")[0], float(nome.split("=")[1].rstrip("%")) / 100
        partes, trs = [], []
        for per, ativos in (("descoberta", desc_ativos), ("validacao", val_ativos), ("prova", val_ativos)):
            a, b = PERIODOS[per]
            d, trm = cp.cesta(ativos, v, pct, a, b, comp, cic, cad1)
            partes.append(d)
            trs.append(trm)
        d = pd.concat(partes, ignore_index=True)
        trm = pd.concat(trs)
        trm = trm[~trm.index.duplicated(keep="last")]
        out["historico_completo"][nome] = cp.metricas_variante(d, trm, n_tent=n_cfg)
    return out


def a5():
    """Descritivo: arbitragens no fechamento nos ultimos 250 pregoes da base."""
    from quant.opcoes import arbitragens
    dias = dados.dias_de_pregao()
    ult = set(dados.carregar_opcoes(2026, 2026, colunas=["dia"])["dia"].unique())
    base_dias = [d for d in dias if d in ult or d >= dias[-300]]
    op = dados.carregar_opcoes(2025, 2026)
    sp = pd.concat([pd.read_parquet(os.path.join(DIR_DADOS, f"ativo_{y}.parquet")) for y in (2025, 2026)])
    ultimos = sorted(op["dia"].unique())[-250:]
    op = op[op["dia"].isin(ultimos)]
    sp = sp[(sp["fatcot"] == 1) & sp["dia"].isin(ultimos)]
    r = arbitragens.varrer(op, sp)
    res = arbitragens.resumo_historico(r, len(ultimos))
    res["periodo"] = f"{pd.Timestamp(ultimos[0]).date()} a {pd.Timestamp(ultimos[-1]).date()}"
    metricas.registrar("A5_arbitragem", "varredura_250_pregoes", "descritivo", {k: v for k, v in res.items() if k != "por_tipo"})
    return res


def rodar():
    metricas.FORCAR = True
    cad, cic, pv = carregar_base()
    cad1 = pd.read_parquet(os.path.join(DIR_DADOS, "cadeia_preparada.parquet"))
    R = {"gerado": pd.Timestamp.now().isoformat(timespec="seconds")}
    R["A0"] = a0(cad1, cic)
    r1, S = a1(cad, cic, pv, None)
    R["A1"] = dict(r1)
    f1 = {"straddle_barato_vr252": ("ret_straddle", lambda d: d["q_vr_menos_vi252"] == 2),
          "straddle_barato_vr60": ("ret_straddle", lambda d: d["q_vr_menos_vi60"] == 2),
          "call_barata_vr60": ("ret_call", lambda d: d["q_vr_menos_vi60"] == 2),
          "put_barata_vr60": ("ret_put", lambda d: d["q_vr_menos_vi60"] == 2),
          "straddle_vr60_maior_vi": ("ret_straddle", lambda d: d["q_sinal60"] == 2),
          "straddle_perc_vi_menor_20": ("ret_straddle", lambda d: d["perc_vi"] < 20)}
    R["A1"]["prova"] = {}
    for nome in r1["passaram_descoberta_e_validacao"]:
        col, f = f1[nome]
        s = serie_mensal(S, col, cic, "prova", f)
        R["A1"]["prova"][nome] = resumo_estrategia(s, "A1_vol_barata", nome, "prova", r1["n_configuracoes"])
        PROVA_ABERTA.append(("A1", nome))
        ss = pd.concat([serie_mensal(S, col, cic, per, f) for per in ("descoberta", "validacao", "prova")], ignore_index=True)
        x = ss["ex"].values
        com = ss["n_ops"].values > 0
        sd = x.std(ddof=1)
        R["A1"].setdefault("historico_completo", {})[nome] = {"n_meses": int(len(x)), "n_ops": int(ss["n_ops"].sum()), "media_por_op_pct": _r(x[com].mean() * 100), "t": _r(teste_t(x[com])),
                                                              "sharpe": _r(x.mean() / sd * math.sqrt(len(x) / (ss["du"].sum() / 252.0)), 3),
                                                              "pior_mes_por_op_pct": _r(x[com].min() * 100, 1), "pct_meses_positivos": _r((x[com] > 0).mean() * 100, 1)}
    R["A2"] = a2(cad1, cic, pv)
    R["A3"] = {"estruturas": a3_estruturas(cad, cic), "previsao": a3_a4_previsao(pv)}
    R["A4"] = {k: v for k, v in R["A3"]["previsao"].items() if k.startswith("desvio")}
    R["A3"]["previsao"] = {k: v for k, v in R["A3"]["previsao"].items() if k.startswith("skew")}
    R["A5"] = a5()
    m6, meta6 = a6()
    R["A6"] = a6_resumo(m6, meta6)
    R["prova_aberta"] = list(PROVA_ABERTA)
    json.dump(_limpa(R), open(ARQ, "w"), ensure_ascii=False, indent=1)
    return R


def _limpa(x):
    if isinstance(x, dict):
        return {str(k): _limpa(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_limpa(v) for v in x]
    if isinstance(x, (np.floating,)):
        return None if np.isnan(x) else float(x)
    if isinstance(x, float):
        return None if x != x else x
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp,)):
        return x.isoformat()
    return x


if __name__ == "__main__":
    rodar()

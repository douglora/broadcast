"""
Simulador de ciclos mensais. Entra no fechamento do primeiro pregao depois do vencimento anterior, na serie do vencimento
mensal seguinte, e carrega ate o vencimento (sem gestao no meio do ciclo). Retorno sempre por unidade de capital empenhado
e EXCEDENTE sobre o CDI do ciclo (o caixa rende CDI por premissa).

Estrategias (cada uma com a hipotese em estrategias.py):
  venda_put       put vendida coberta por caixa (capital = strike)
  call_coberta    acao comprada + call vendida (capital = preco da acao)
  trava_put       trava de alta de credito com puts: vende put delta ~0,25 e compra put mais baixa (capital = risco maximo)
  hedge_*         protecao de uma carteira espelhada no BOVA11 (put, trava de baixa, colar, venda de mini-indice)
"""
import numpy as np
import pandas as pd

from quant.opcoes import custos as C
from quant.opcoes import dados


# ---------------------------------------------------------------- preparo
def preparar(cad, ciclos):
    """Marca o ativo escolhido por (grupo, T) -- o de maior volume de opcoes no dia de entrada -- e junta retorno total."""
    cad = cad.copy()
    vol = cad.groupby(["grupo", "T", "ativo"])["volume"].sum().reset_index()
    vol = vol.sort_values("volume", ascending=False).drop_duplicates(["grupo", "T"])
    cad = cad.merge(vol[["grupo", "T", "ativo"]].assign(escolhido=True), on=["grupo", "T", "ativo"], how="left")
    cad["escolhido"] = cad["escolhido"].fillna(False).astype(bool)
    cdi = ciclos.set_index("T")
    cad["cdi_ciclo"] = cad["T"].map({t: dados.acumular_cdi(e, t) - 1.0 for t, e in zip(ciclos["T"], ciclos["E"])})
    # retorno total do ativo no ciclo (uma conta por ativo x ciclo)
    from quant.opcoes import ciclos as cm
    u = cad[["ativo", "E", "T", "du"]].drop_duplicates().reset_index(drop=True)
    u["tr"] = cm.retorno_total_ciclo(u).values
    cad = cad.merge(u[["ativo", "E", "T", "tr"]], on=["ativo", "E", "T"], how="left")
    # volatilidade realizada (20 pregoes ate a entrada, com retorno total) e volatilidade implicita no dinheiro
    cad = cad.merge(vol_realizada(u), on=["ativo", "E"], how="left")
    meio = cad[(cad["delta"].abs() >= 0.35) & (cad["delta"].abs() <= 0.65) & (cad["negocios"] >= 10) & cad["iv"].notna()]
    atm = meio.groupby(["ativo", "T"])["iv"].median().rename("iv_atm").reset_index()
    cad = cad.merge(atm, on=["ativo", "T"], how="left")
    cad["vrp"] = cad["iv_atm"] / cad["rv20"]
    return cad


def vol_realizada(u, janela=20):
    """Contexto do ativo na entrada, sem olhar adiante: volatilidade realizada anualizada dos `janela` pregoes ate o
    fechamento de E (retorno total), retorno de 5 e de 10 pregoes e se o indice de retorno total esta acima da media de 200
    pregoes. Acoes: retorno total (sem salto de dividendo); BOVA11: Ibovespa. `u`: DataFrame com ativo, E."""
    f = dados.fator_retorno_total()
    ib = dados.ibov()
    out = []
    cache = {}
    for a, e in zip(u["ativo"], u["E"]):
        if a == "BOVA11":
            serie = ib
        elif a in f.columns:
            serie = f[a]
        else:
            out.append((np.nan, np.nan, np.nan, np.nan))
            continue
        if a not in cache:
            x = serie.dropna()
            cache[a] = (x, np.log(x).diff(), x.rolling(200, min_periods=150).mean())
        x, r, mm = cache[a]
        i = r.index.searchsorted(e, side="right")        # ate o fechamento de E, inclusive
        w = r.iloc[max(0, i - janela):i].dropna()
        rv = float(w.std(ddof=1) * np.sqrt(252)) if len(w) >= 15 else np.nan
        if i >= 11 and x.index[i - 1] == e:
            r5, r10 = x.iloc[i - 1] / x.iloc[i - 6] - 1.0, x.iloc[i - 1] / x.iloc[i - 11] - 1.0
            ok = float(x.iloc[i - 1] > mm.iloc[i - 1]) if mm.iloc[i - 1] == mm.iloc[i - 1] else np.nan
        else:
            r5 = r10 = ok = np.nan
        out.append((rv, r5, r10, ok))
    res = u[["ativo", "E"]].copy()
    res[["rv20", "ret5", "ret10", "acima_mm200"]] = pd.DataFrame(out, index=res.index)
    return res.drop_duplicates(["ativo", "E"])


def liquidas(cad, tipo, neg_min=C.NEG_MIN, spread_max=C.SPREAD_MAX):
    """Series do tipo pedido que passam no filtro de liquidez FIXO (negocios no dia e spread das ofertas do fechamento)."""
    m = ((cad["tipo"] == tipo) & cad["escolhido"] & cad["iv"].notna() & cad["oferta_compra"].notna()
         & cad["oferta_venda"].notna() & (cad["oferta_compra"] > 0) & (cad["oferta_venda"] > cad["oferta_compra"])
         & (cad["negocios"] >= neg_min) & (cad["spread"] <= spread_max) & cad["S_E"].notna() & cad["S_T"].notna()
         & (cad["K_T"] > 0))
    return cad[m]


def mais_perto_do_delta(el, alvo, tol=C.DELTA_TOL):
    d = el.assign(dist=(el["delta"].abs() - alvo).abs())
    d = d[d["dist"] <= tol]
    return (d.sort_values(["grupo", "T", "dist", "negocios"], ascending=[True, True, True, False])
            .drop_duplicates(["grupo", "T"]))


# ---------------------------------------------------------------- estrategias: devolvem uma linha por operacao
def venda_put(cad, grupos, delta=0.20, exec="oferta", neg_min=C.NEG_MIN, spread_max=C.SPREAD_MAX):
    el = liquidas(cad[cad["grupo"].isin(grupos)], "P", neg_min, spread_max)
    s = mais_perto_do_delta(el, delta).copy()
    prem = np.where(exec == "oferta", s["oferta_compra"], s["mid"]) * (1.0 - C.FEE_PREMIO)
    exercida = s["payoff_T"] > 0
    taxa = np.where(exercida, C.FEE_EXERC * (s["K_T"] + s["S_T"]), 0.0)
    pnl = prem * (1.0 + s["cdi_ciclo"]) - s["payoff_T"] - taxa
    s["premio_recebido"] = prem
    s["pnl_acao"] = pnl
    s["capital"] = s["exercicio"]
    s["ex"] = pnl / s["exercicio"]
    s["exercida"] = exercida
    return s


def call_coberta(cad, grupos, delta=0.30, exec="oferta", neg_min=C.NEG_MIN, spread_max=C.SPREAD_MAX):
    """Devolve DataFrame com 'ex_coberta' e 'ex_acao' por (grupo, T), para TODOS os grupos que tinham retorno total no ciclo
    (sem call elegivel o ciclo fica so com a acao: ex_coberta = ex_acao)."""
    base = (cad[cad["grupo"].isin(grupos) & cad["escolhido"] & cad["S_E"].notna() & cad["tr"].notna()]
            [["grupo", "ativo", "E", "T", "S_E", "tr", "cdi_ciclo"]].drop_duplicates(["grupo", "T"]).copy())
    base["ex_acao"] = base["tr"] - base["cdi_ciclo"]
    el = liquidas(cad[cad["grupo"].isin(grupos)], "C", neg_min, spread_max)
    s = mais_perto_do_delta(el, delta).copy()
    prem = np.where(exec == "oferta", s["oferta_compra"], s["mid"]) * (1.0 - C.FEE_PREMIO)
    exercida = s["payoff_T"] > 0
    taxa = np.where(exercida, C.FEE_EXERC * (s["K_T"] + s["S_T"]), 0.0)
    s["pnl_call"] = (prem * (1.0 + s["cdi_ciclo"]) - s["payoff_T"] - taxa)
    s["exercida"] = exercida
    s["premio_recebido"] = prem
    base = base.merge(s[["grupo", "T", "pnl_call", "exercida", "premio_recebido", "exercicio", "delta"]], on=["grupo", "T"], how="left")
    base["com_call"] = base["pnl_call"].notna()
    base["ex_coberta"] = base["ex_acao"] + base["pnl_call"].fillna(0.0) / base["S_E"]
    return base


def trava_put(cad, grupos, delta=0.25, largura=0.05, exec="oferta", neg_min=C.NEG_MIN, spread_max=C.SPREAD_MAX):
    """Vende put delta ~0,25 e compra a put liquida de strike mais perto de K_vendido - largura x S_E (abaixo)."""
    el = liquidas(cad[cad["grupo"].isin(grupos)], "P", neg_min, spread_max)
    curta = mais_perto_do_delta(el, delta).copy()
    lin = []
    longas = el.set_index(["grupo", "T"])
    for _, c in curta.iterrows():
        try:
            g = longas.loc[[(c["grupo"], c["T"])]]
        except KeyError:
            continue
        alvo_k = c["exercicio"] - largura * c["S_E"]
        g = g[(g["exercicio"] < c["exercicio"]) & (g["ativo"] == c["ativo"])]
        if g.empty:
            continue
        g = g.assign(dk=(g["exercicio"] - alvo_k).abs())
        l = g.sort_values(["dk", "negocios"], ascending=[True, False]).iloc[0]
        if l["dk"] > 0.5 * largura * c["S_E"]:
            continue                                  # nao ha put liquida perto da largura pedida
        pc = (c["oferta_compra"] if exec == "oferta" else c["mid"]) * (1 - C.FEE_PREMIO)
        pl = (l["oferta_venda"] if exec == "oferta" else l["mid"]) * (1 + C.FEE_PREMIO)
        credito = pc - pl
        larg = c["exercicio"] - l["exercicio"]
        if credito <= 0 or credito >= larg:
            continue
        pay = c["payoff_T"] - l["payoff_T"]
        taxa = (C.FEE_EXERC * (c["K_T"] + c["S_T"]) if c["payoff_T"] > 0 else 0.0) \
            + (C.FEE_EXERC * (l["K_T"] + l["S_T"]) if l["payoff_T"] > 0 else 0.0)
        pnl = credito * (1 + c["cdi_ciclo"]) - pay - taxa
        risco = larg - credito
        lin.append({"grupo": c["grupo"], "ativo": c["ativo"], "E": c["E"], "T": c["T"], "cdi_ciclo": c["cdi_ciclo"],
                    "K_curta": c["exercicio"], "K_longa": l["exercicio"], "credito": credito, "largura": larg,
                    "risco_max": risco, "pnl_acao": pnl, "ex": pnl / risco, "capital": risco,
                    "perda_total": pay >= larg - 1e-9, "delta_curta": c["delta"], "cod_curta": c["codigo"], "cod_longa": l["codigo"]})
    return pd.DataFrame(lin)


# ---------------------------------------------------------------- agregacao por ciclo
def serie_por_ciclo(trades, cad, ciclos, grupos, ini, fim, coluna="ex"):
    """Uma linha por ciclo T em [ini, fim]: excesso medio = soma do excesso das operacoes / numero de grupos ativos no ciclo.
    Grupo ativo = tem alguma linha de opcao na cadeia de entrada do ciclo (existe mercado de opcoes dele naquele mes)."""
    ini, fim = pd.Timestamp(ini), pd.Timestamp(fim)
    cic = ciclos[(ciclos["T"] >= ini) & (ciclos["T"] <= fim)].copy()
    ativos = cad[cad["grupo"].isin(grupos)].groupby("T")["grupo"].nunique()
    soma = trades.groupby("T")[coluna].sum() if len(trades) else pd.Series(dtype=float)
    nops = trades.groupby("T")[coluna].size() if len(trades) else pd.Series(dtype=float)
    cic["n_grupos"] = cic["T"].map(ativos).fillna(0)
    cic = cic[cic["n_grupos"] > 0].copy()
    cic["ex"] = cic["T"].map(soma).fillna(0.0) / cic["n_grupos"]
    cic["n_ops"] = cic["T"].map(nops).fillna(0).astype(int)
    cic["cdi"] = [dados.acumular_cdi(e, t) - 1.0 for e, t in zip(cic["E"], cic["T"])]
    return cic.reset_index(drop=True)

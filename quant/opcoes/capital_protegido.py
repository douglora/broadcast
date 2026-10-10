"""
A0. CAPITAL PROTEGIDO FEITO EM CASA.

O caixa fica no CDI; todo mes um ORCAMENTO fixo (fracao do patrimonio do momento) compra opcao de alta. A perda maxima de cada
mes e o orcamento; o ganho e aberto (calls) ou limitado (trava). Variantes pre-fixadas (nenhum parametro escolhido pelos dados):

  call_atm_1m     call no dinheiro (exercicio mais perto do preco), vence no mes seguinte (~20 pregoes)
  call_5otm_2m    call 5% fora do dinheiro (+-2,5%), vence no SEGUNDO mes (~40 pregoes); uma compra por mes, posicoes se sobrepoem
  trava_alta_1m   compra a call no dinheiro e vende a 10% acima (+-3%), ~20 pregoes

Compra na oferta de venda e vende na oferta de compra do fechamento, emolumento de 0,05% por lado, so serie liquida (30 negocios,
spread <= 30%, ofertas dos dois lados). Mes sem serie liquida: o orcamento fica no CDI. Posicao de 2 meses ainda aberta no fim do
mes e marcada pelo Black-Scholes proprio com a volatilidade implicita de entrada e o preco do ativo daquele dia (modelo, nao oferta).
"""
import numpy as np
import pandas as pd

from quant.opcoes import bs, dados, metricas
from quant.opcoes import custos as C

VARIANTES = ("call_atm_1m", "call_5otm_2m", "trava_alta_1m")
ORCAMENTOS = (0.003, 0.005, 0.010)
INICIO_ATIVO = {"PETR4": "2012-01-01", "VALE": "2012-01-01", "BOVA11": "2020-01-01", "ITUB4": "2019-01-01", "BBDC4": "2019-01-01", "BBAS3": "2019-01-01"}


def _marcar_escolhido(cad):
    cad = cad.drop(columns=["escolhido"], errors="ignore")
    vol = cad.groupby(["grupo", "T", "ativo"])["volume"].sum().reset_index().sort_values("volume", ascending=False).drop_duplicates(["grupo", "T"])
    cad = cad.merge(vol[["grupo", "T", "ativo"]].assign(escolhido=True), on=["grupo", "T", "ativo"], how="left")
    cad["escolhido"] = cad["escolhido"].fillna(False).astype(bool)
    return cad


def _liquidas_calls(cad):
    m = ((cad["tipo"] == "C") & cad["escolhido"] & cad["oferta_compra"].notna() & cad["oferta_venda"].notna() & (cad["oferta_compra"] > 0)
         & (cad["oferta_venda"] > cad["oferta_compra"]) & (cad["negocios"] >= C.NEG_MIN) & (cad["spread"] <= C.SPREAD_MAX)
         & cad["S_E"].notna() & cad["S_T"].notna() & (cad["K_T"] > 0) & cad["iv"].notna())
    return cad[m]


def _mais_perto(df, alvo_col, alvo, tol, chaves=("grupo", "E")):
    d = df.assign(_d=(df["exercicio"] / df["S_E"] - alvo).abs())
    d = d[d["_d"] <= tol]
    return d.sort_values(list(chaves) + ["_d", "negocios"], ascending=[True] * len(chaves) + [True, False]).drop_duplicates(list(chaves))


def compras(cad1, cad2):
    """Uma linha por (grupo, E, variante) com custo por acao, pagamento no vencimento, exercicio, vencimento e IV de entrada."""
    fee = C.FEE_PREMIO
    c1 = _liquidas_calls(_marcar_escolhido(cad1))
    c2 = _liquidas_calls(_marcar_escolhido(cad2))
    sai = []
    atm = _mais_perto(c1, None, 1.0, 0.03)
    sai.append(pd.DataFrame({"grupo": atm["grupo"], "E": atm["E"], "variante": "call_atm_1m", "custo": atm["oferta_venda"] * (1 + fee),
                             "pagto": atm["payoff_T"] * (1 - fee), "K": atm["exercicio"], "iv": atm["iv"], "venc": atm["T"], "S_E": atm["S_E"], "ativo": atm["ativo"]}))
    o5 = _mais_perto(c2, None, 1.05, 0.025)
    sai.append(pd.DataFrame({"grupo": o5["grupo"], "E": o5["E"], "variante": "call_5otm_2m", "custo": o5["oferta_venda"] * (1 + fee),
                             "pagto": o5["payoff_T"] * (1 - fee), "K": o5["exercicio"], "iv": o5["iv"], "venc": o5["T"], "S_E": o5["S_E"], "ativo": o5["ativo"]}))
    curta = _mais_perto(c1, None, 1.10, 0.03).rename(columns={"oferta_compra": "bid_c", "payoff_T": "pay_c", "exercicio": "K_c"})
    m = atm.merge(curta[["grupo", "E", "bid_c", "pay_c", "K_c"]], on=["grupo", "E"])
    m = m[m["K_c"] > m["exercicio"]]
    custo = m["oferta_venda"] * (1 + fee) - m["bid_c"] * (1 - fee)
    m = m[(custo > 0) & (custo < (m["K_c"] - m["exercicio"]))]
    custo = m["oferta_venda"] * (1 + fee) - m["bid_c"] * (1 - fee)
    sai.append(pd.DataFrame({"grupo": m["grupo"], "E": m["E"], "variante": "trava_alta_1m", "custo": custo,
                             "pagto": (m["payoff_T"] - m["pay_c"]) * (1 - fee), "K": m["exercicio"], "iv": m["iv"], "venc": m["T"], "S_E": m["S_E"], "ativo": m["ativo"]}))
    return pd.concat(sai, ignore_index=True)


def simular(grupo, variante, pct, comp, cic, ini, fim, h=None):
    """Patrimonio mensal de um ativo e uma variante. `cic`: ciclos de 1 mes (E, T, du, cdi). Devolve DataFrame por ciclo."""
    fech = dados.fechamentos()
    cdi = dados.cdi_diario()
    r_aa = ((1.0 + cdi.reindex(dados.dias_de_pregao()).ffill()) ** 252 - 1.0)
    cs = cic[(cic["E"] >= pd.Timestamp(ini)) & (cic["T"] <= pd.Timestamp(fim))].sort_values("E")
    cp = comp[(comp["grupo"] == grupo) & (comp["variante"] == variante)].set_index("E")
    equity = 1.0
    cash = 1.0
    abertas = []
    linhas = []
    for E, T, du, c in zip(cs["E"], cs["T"], cs["du"], cs["cdi_ciclo"]):
        inicio = cash + sum(p["qtd"] * p["mtm_ult"] for p in abertas)
        gasto = 0.0
        comprou = False
        if E in cp.index:
            r = cp.loc[E]
            if r["custo"] > 0:
                gasto = pct * inicio
                abertas.append({"qtd": gasto / r["custo"], "pagto": r["pagto"], "K": r["K"], "iv": r["iv"], "venc": r["venc"], "mtm_ult": r["custo"]})
                cash -= gasto
                comprou = True
        cash *= (1.0 + c)
        resto = []
        for p in abertas:
            if p["venc"] <= T:
                cash += p["qtd"] * p["pagto"]
            else:
                a = grupo_ativo(grupo, T, fech)
                S = fech.at[T, a] if (a in fech.columns and T in fech.index) else np.nan
                dias = dados.dias_estendidos()
                trem = (np.searchsorted(dias.values, np.datetime64(p["venc"])) - np.searchsorted(dias.values, np.datetime64(T))) / 252.0
                rr = np.log1p(float(r_aa.get(T, 0.1365)))
                p["mtm_ult"] = bs.preco(float(S), float(p["K"]), max(trem, 1e-6), rr, float(p["iv"]), False) * (1 - C.FEE_PREMIO) if S == S else p["mtm_ult"]
                resto.append(p)
        abertas = resto
        fim_eq = cash + sum(p["qtd"] * p["mtm_ult"] for p in abertas)
        linhas.append({"E": E, "T": T, "du": du, "cdi": c, "r": fim_eq / inicio - 1.0, "comprou": comprou, "gasto_pct": gasto / inicio if inicio else 0.0})
    d = pd.DataFrame(linhas)
    d["ex"] = d["r"] - d["cdi"]
    return d


def grupo_ativo(grupo, T, fech):
    if grupo == "VALE":
        return "VALE3" if "VALE3" in fech.columns and T >= pd.Timestamp("2018-01-01") else "VALE5"
    return grupo


def retorno_do_ativo(grupo, cic, cad1):
    """Retorno total do ativo em cada ciclo (E -> T)."""
    t = cad1[cad1["escolhido"] & (cad1["grupo"] == grupo)].drop_duplicates("E")[["E", "T", "tr"]].set_index("E")["tr"]
    return t


def resumo_anual(d, tr):
    """Retorno por ano calendario (ciclos agrupados pelo ano do vencimento) da estrategia, do CDI e do ativo."""
    d = d.copy()
    d["tr"] = d["E"].map(tr)
    d["ano"] = d["T"].dt.year
    out = []
    for a, g in d.groupby("ano"):
        out.append({"ano": int(a), "ciclos": len(g), "estrategia": float(np.prod(1 + g["r"]) - 1), "cdi": float(np.prod(1 + g["cdi"]) - 1),
                    "ativo": float(np.prod(1 + g["tr"].fillna(0)) - 1), "ativo_70_30": float(np.prod(1 + 0.7 * g["tr"].fillna(0) + 0.3 * g["cdi"]) - 1)})
    return pd.DataFrame(out)


def metricas_variante(d, tr, n_tent=None):
    """Metricas do patrimonio mensal; compara com CDI, ativo e 70/30."""
    if len(d) < 6:
        return {"n_ciclos": len(d)}
    m = metricas.calcular(d["ex"].values, d["cdi"].values, d["comprou"].values, d["E"].iloc[0], d["T"].iloc[-1], n_tentativas=n_tent, anos=d["du"].sum() / 252.0)
    anual = resumo_anual(d, tr)
    anos_completos = anual[anual["ciclos"] >= 10]
    m["pior_ano_pct"] = round(float(anos_completos["estrategia"].min() * 100), 2) if len(anos_completos) else None
    m["pior_ano_do_ativo_pct"] = round(float(anos_completos["ativo"].min() * 100), 2) if len(anos_completos) else None
    m["anos_acima_do_cdi_pct"] = round(float((anos_completos["estrategia"] > anos_completos["cdi"]).mean() * 100), 0) if len(anos_completos) else None
    m["n_anos"] = int(len(anos_completos))
    parados = anos_completos[anos_completos["ativo"] <= anos_completos["cdi"]]
    m["anos_parados_n"] = int(len(parados))
    m["excesso_medio_ano_parado_pct"] = round(float((parados["estrategia"] - parados["cdi"]).mean() * 100), 2) if len(parados) else None
    m["excesso_medio_ano_de_alta_pct"] = round(float((anos_completos[anos_completos["ativo"] > anos_completos["cdi"]].eval("estrategia - cdi")).mean() * 100), 2) if (anos_completos["ativo"] > anos_completos["cdi"]).any() else None
    t = d["E"].map(tr).fillna(0.0).values
    cdi = d["cdi"].values
    up = t > cdi
    m["captura_da_alta_pct"] = round(float(d["ex"].values[up].sum() / (t[up] - cdi[up]).sum() * 100), 1) if up.any() else None
    parado = t <= cdi
    m["excesso_medio_mes_parado_pct"] = round(float(d["ex"].values[parado].mean() * 100), 3) if parado.any() else None
    m["gasto_medio_pct_do_patrimonio_por_mes"] = round(float(d.loc[d["comprou"], "gasto_pct"].mean() * 100), 3) if d["comprou"].any() else None
    # referencias
    ret_ativo = float(np.prod(1 + t))
    anos = d["du"].sum() / 252.0
    m["ref_cdi_aa_pct"] = m["cdi_anual_pct"]
    m["ref_ativo_aa_pct"] = round((ret_ativo ** (1 / anos) - 1) * 100, 2)
    m["ref_70_30_aa_pct"] = round((float(np.prod(1 + 0.7 * t + 0.3 * cdi)) ** (1 / anos) - 1) * 100, 2)
    pico = np.maximum.accumulate(np.cumprod(1 + t))
    m["ref_ativo_queda_maxima_pct"] = round(float((np.cumprod(1 + t) / pico - 1).min() * 100), 2)
    s73 = np.cumprod(1 + 0.7 * t + 0.3 * cdi)
    m["ref_70_30_queda_maxima_pct"] = round(float((s73 / np.maximum.accumulate(s73) - 1).min() * 100), 2)
    m["ref_70_30_pior_ano_pct"] = round(float(anos_completos["ativo_70_30"].min() * 100), 2) if len(anos_completos) else None
    m["ref_cdi_pior_ano_pct"] = round(float(anos_completos["cdi"].min() * 100), 2) if len(anos_completos) else None
    return m


def cesta(grupos, variante, pct, ini, fim, comp, cic, cad1):
    """Media simples dos ativos que ja tinham opcao liquida (INICIO_ATIVO) em cada ciclo. Devolve (DataFrame por ciclo, retorno total medio do ativo)."""
    ds, trs = [], []
    for g in grupos:
        aa = max(pd.Timestamp(ini), pd.Timestamp(INICIO_ATIVO[g]))
        if aa > pd.Timestamp(fim):
            continue
        d = simular(g, variante, pct, comp, cic, aa, fim).set_index("E")
        ds.append(d)
        trs.append(retorno_do_ativo(g, cic, cad1))
    base = pd.concat([x[["T", "du", "cdi"]] for x in ds]).groupby(level=0).first()
    ex = pd.concat([x["ex"] for x in ds], axis=1).mean(axis=1)
    com = pd.concat([x["comprou"] for x in ds], axis=1).any(axis=1)
    gasto = pd.concat([x["gasto_pct"] for x in ds], axis=1).mean(axis=1)
    d = pd.DataFrame({"E": base.index, "T": base["T"].values, "du": base["du"].values, "cdi": base["cdi"].values, "ex": ex.values,
                      "r": (ex + base["cdi"]).values, "comprou": com.values, "gasto_pct": gasto.values})
    return d, pd.concat(trs, axis=1).mean(axis=1)

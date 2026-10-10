"""
"Pozinho": opcao muito fora do dinheiro, de centavos, comprada como bilhete de loteria.

Definicao FIXA do bilhete (antes de olhar o resultado):
  - compra na melhor oferta de VENDA do fechamento da entrada (ask), mais 0,05% de emolumento;
  - ask entre R$ 0,01 e o teto (R$ 0,10 ou R$ 0,20);
  - pelo menos 10 negocios da serie no dia da entrada (senao a oferta do fechamento nao diz nada);
  - call com exercicio >= 105% do preco do ativo, ou put com exercicio <= 95% (muito fora do dinheiro);
  - ativos: os 25 de maior volume de opcoes NO ANO ANTERIOR (sem olhar adiante);
  - uma unidade de R$ 1 por bilhete; todos os bilhetes que passam no filtro entram.
Saida: (i) ate o vencimento (pagamento = valor intrinseco com o preco SEM ajuste e o strike da B3 ajustado por provento);
(ii) saida antecipada: vende na melhor oferta de compra do fechamento do primeiro dia em que ela paga M vezes o custo
(M = 5 ou 10); se nao chegar, vai ate o vencimento. A saida antecipada usa so fechamentos: nao usa maxima do dia.

Condicoes testadas (todas definidas a priori): tipo, teto, entrada no inicio do ciclo (~20 pregoes ate o vencimento) ou curta (8
pregoes), volatilidade implicita no dinheiro menor que a realizada de 20 pregoes (vrp < 0,9), queda forte (retorno de 10
pregoes <= -10%), resultado trimestral protocolado na CVM dentro da janela entre a entrada e o dia anterior ao vencimento.
"""
import os

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO
from quant.opcoes import ciclos, dados, motor
from quant.opcoes import custos as C
from quant.opcoes.base import DIR_DADOS

TOP_ATIVOS = 25
PREFIXOS_FIXOS = {"VALE5": "VALE3", "BVMF3": "B3SA3"}


def universo_por_ano(top=TOP_ATIVOS):
    """{ano: conjunto de ativos} = os `top` de maior volume de opcoes no ano ANTERIOR."""
    op = dados.carregar_opcoes(2011, 2026, colunas=["ativo", "volume", "dia"])
    op["ano"] = op["dia"].dt.year
    v = op.groupby(["ano", "ativo"])["volume"].sum().reset_index()
    out = {}
    for ano in range(2012, 2027):
        p = v[v["ano"] == ano - 1].sort_values("volume", ascending=False).head(top)
        out[ano] = set(p["ativo"])
    return out


def datas_de_resultado():
    """{cd_cvm: array ordenado de datas em que a CVM recebeu ITR ou DFP (primeira versao)}."""
    partes = []
    base = os.path.join(DIR_BANCO, "fundamentos_pit")
    for pasta in sorted(os.listdir(base)):
        if pasta.startswith("ano="):
            d = pd.read_parquet(os.path.join(base, pasta), columns=["cd_cvm", "tipo", "dt_refer", "dt_receb", "versao"])
            partes.append(d[d["versao"] == 1].drop_duplicates(["cd_cvm", "tipo", "dt_refer"]))
    d = pd.concat(partes)
    d["cd_cvm"] = d["cd_cvm"].astype(str)
    return {k: np.sort(g["dt_receb"].dropna().values) for k, g in d.groupby("cd_cvm")}


def cd_cvm_de(ativo, ident):
    if ativo == "BOVA11":
        return None
    a = PREFIXOS_FIXOS.get(ativo, ativo)
    x = ident[ident["ticker"] == a]["cd_cvm"].dropna()
    if len(x):
        return str(x.iloc[0])
    x = ident[ident["ticker"].str[:4] == a[:4]]["cd_cvm"].dropna()
    return str(x.mode().iloc[0]) if len(x) else None


def marcar_resultado(trades):
    """Coluna `resultado_na_janela`: True se algum ITR/DFP foi protocolado em (E, T) -- depois da entrada e antes do vencimento."""
    ident = pd.read_parquet(os.path.join(DIR_BANCO, "identidade.parquet"))
    datas = datas_de_resultado()
    cache = {}
    res = []
    for a, e, t in zip(trades["ativo"], trades["E"], trades["T"]):
        if a not in cache:
            cache[a] = datas.get(cd_cvm_de(a, ident) or "", None)
        arr = cache[a]
        if arr is None:
            res.append(np.nan)
            continue
        i = np.searchsorted(arr, np.datetime64(e), side="right")
        res.append(float(i < len(arr) and arr[i] < np.datetime64(t)))
    trades = trades.copy()
    trades["resultado_na_janela"] = res
    return trades


def bilhetes(cad, teto, modo):
    """Bilhetes (um por serie) de uma tabela de cadeias na entrada. `modo`: 'inicio' ou 'curto'."""
    uni = universo_por_ano()
    d = cad[cad["ativo"].isin(set().union(*uni.values()))].copy()
    d = d[[a in uni.get(y, set()) for a, y in zip(d["ativo"], d["E"].dt.year)]]
    call = (d["tipo"] == "C") & (d["exercicio"] >= 1.05 * d["S_E"])
    put = (d["tipo"] == "P") & (d["exercicio"] <= 0.95 * d["S_E"])
    m = ((call | put) & d["oferta_venda"].notna() & (d["oferta_venda"] >= 0.01) & (d["oferta_venda"] <= teto)
         & (d["negocios"] >= 10) & d["S_E"].notna() & d["S_T"].notna() & (d["K_T"] > 0))
    t = d[m].copy()
    t["custo"] = t["oferta_venda"] * (1.0 + C.FEE_PREMIO)
    t["pagto"] = t["payoff_T"] * (1.0 - C.FEE_PREMIO)
    t["mult"] = t["pagto"] / t["custo"]
    t["teto"] = teto
    t["modo"] = modo
    t["ano"] = t["T"].dt.year
    return t.reset_index(drop=True)


def saida_antecipada(t, multiplos=(5, 10)):
    """Para cada bilhete, o multiplo realizado se vender na oferta de compra do primeiro fechamento (E < dia < T) que pague
    >= M vezes o custo; senao o multiplo do vencimento. Colunas mult_saida{M} e saiu_antes{M}."""
    op = dados.carregar_opcoes(2012, 2026, colunas=["dia", "codigo", "vencimento", "oferta_compra"])
    op = op[op["oferta_compra"].notna() & (op["oferta_compra"] > 0)]
    chave = t[["codigo", "vencimento", "E", "T", "custo"]].drop_duplicates(["codigo", "vencimento", "E"])
    x = op.merge(chave, on=["codigo", "vencimento"], how="inner")
    x = x[(x["dia"] > x["E"]) & (x["dia"] < x["T"])]
    x["m"] = x["oferta_compra"] * (1.0 - C.FEE_PREMIO) / x["custo"]
    t = t.copy()
    for M in multiplos:
        h = x[x["m"] >= M].sort_values("dia").drop_duplicates(["codigo", "vencimento", "E"])[["codigo", "vencimento", "E", "m"]]
        h = h.rename(columns={"m": f"_m{M}"})
        t = t.merge(h, on=["codigo", "vencimento", "E"], how="left")
        t[f"saiu_antes{M}"] = t[f"_m{M}"].notna()
        t[f"mult_saida{M}"] = np.where(t[f"saiu_antes{M}"], t[f"_m{M}"], t["mult"])
        t = t.drop(columns=[f"_m{M}"])
    pico = x.groupby(["codigo", "vencimento", "E"])["m"].max().rename("pico_mult").reset_index()
    t = t.merge(pico, on=["codigo", "vencimento", "E"], how="left")
    return t


def contexto_cad(cad):
    """Acrescenta rv20, ret5, ret10, acima_mm200, iv_atm e vrp a uma tabela de cadeias (so para os ativos do universo, que
    sao os que viram bilhete)."""
    uni = set().union(*universo_por_ano().values())
    cad = cad[cad["ativo"].isin(uni)].copy()
    u = cad[["ativo", "E"]].drop_duplicates().reset_index(drop=True)
    cad = cad.merge(motor.vol_realizada(u), on=["ativo", "E"], how="left")
    meio = cad[(cad["delta"].abs() >= 0.35) & (cad["delta"].abs() <= 0.65) & (cad["negocios"] >= 10) & cad["iv"].notna()]
    atm = meio.groupby(["ativo", "T"])["iv"].median().rename("iv_atm").reset_index()
    cad = cad.merge(atm, on=["ativo", "T"], how="left")
    cad["vrp"] = cad["iv_atm"] / cad["rv20"]
    return cad


def construir(cad_inicio, cad_curto, tetos=(0.10, 0.20)):
    """Todos os bilhetes (inicio e curto, dois tetos), com saida antecipada e marca de resultado."""
    partes = []
    for modo, cad in (("inicio", cad_inicio), ("curto", cad_curto)):
        for teto in tetos:
            partes.append(bilhetes(cad, teto, modo))
    t = pd.concat(partes, ignore_index=True)
    t = marcar_resultado(t)
    return saida_antecipada(t)


def estatisticas(t, rotulo="", n_boot=400, seed=7):
    """Distribuicao do bilhete (R$ 1 por bilhete). EV = media do multiplo - 1. IC de 90% por reamostragem dos ciclos (T)."""
    n = len(t)
    if n == 0:
        return {"rotulo": rotulo, "n": 0}
    mult = t["mult"].values
    out = {"rotulo": rotulo, "n": int(n), "n_ciclos": int(t["T"].nunique()),
           "ev_pct": round((mult.mean() - 1.0) * 100, 1), "mediana_mult": round(float(np.median(mult)), 2),
           "po_pct": round(float((t["pagto"] <= 0).mean() * 100), 1),
           "pct_ge1x": round(float((mult >= 1).mean() * 100), 1), "pct_ge2x": round(float((mult >= 2).mean() * 100), 1),
           "pct_ge5x": round(float((mult >= 5).mean() * 100), 1), "pct_ge10x": round(float((mult >= 10).mean() * 100), 1)}
    for M in (5, 10):
        if f"mult_saida{M}" in t:
            out[f"ev_saida{M}_pct"] = round((t[f"mult_saida{M}"].mean() - 1.0) * 100, 1)
            out[f"pct_tocou{M}x"] = round(float(t[f"saiu_antes{M}"].mean() * 100), 1)
    g = t.groupby("T")["mult"].agg(["sum", "count"])
    rng = np.random.default_rng(seed)
    evs = []
    idx = np.arange(len(g))
    for _ in range(n_boot):
        s = rng.choice(idx, size=len(idx), replace=True)
        evs.append(g["sum"].values[s].sum() / g["count"].values[s].sum() - 1.0)
    out["ev_ic90_pct"] = [round(float(np.percentile(evs, 5)) * 100, 1), round(float(np.percentile(evs, 95)) * 100, 1)]
    return out

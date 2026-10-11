"""
ITEM 2. PUT DEPOIS DE QUEDA FORTE (regra do Douglas nº 1). Hipotese e definicao FIXA em HIPOTESES_TESES.md.

  sinal   fechamento de D (retorno total): retorno de 5 pregoes <= -8% OU <= -2 desvios (media e desvio dos retornos de 5 pregoes dos 252
          pregoes anteriores) E fechamento abaixo das medias de 21 e de 50 pregoes (versao A); versao B tambem abaixo da de 200.
          Evento = primeiro dia por ativo; novo evento so 10 pregoes depois.
  put     vendida coberta por caixa, delta 0,25 +- 0,05, vencimento com 14 a 30 pregoes (o mais perto de 21), 30+ negocios, ofertas dos dois lados,
          spread ate 30%, vende na oferta de compra, segura ate o vencimento. Retorno = (premio capitalizado - pagamento) / exercicio, menos o CDI
          do prazo ja contado no caixa (excesso).
  trava   de alta de credito com puts: vende a mesma put e compra a de exercicio mais perto de 95% do vendido (+-3% do preco). Retorno sobre o
          risco maximo.
  papel   comprar o papel no mesmo dia e segurar ate a mesma data (retorno total menos CDI, sobre o preco).
  todos   a mesma put vendida em QUALQUER dia (a cada 5 pregoes por ativo do universo): o comparador do "depois de queda forte".
"""
import math

import numpy as np
import pandas as pd

from quant.opcoes import custos as C
from quant.opcoes import dados, diario
from quant.opcoes import metricas
from quant.opcoes.pesquisa import PERIODOS

FEE = C.FEE_PREMIO
R5, Z5, JANELA_Z = -0.08, -2.0, 252
DELTA_ALVO, DELTA_TOL = 0.25, 0.05
DU_MIN, DU_MAX, DU_ALVO = 14, 30, 21
LARGURA = 0.05
FAMILIA = "T2_queda_forte"


def universo_acoes():
    from quant.opcoes import pozinho
    return {a: {x for x in s if x != "BOVA11"} for a, s in pozinho.universo_por_ano().items()}


def sinais():
    """Todas as combinacoes (ativo, dia) com sinal A e B (antes de deduplicar) e a amostra de 'qualquer dia' (a cada 5 pregoes)."""
    f = dados.fator_retorno_total()
    uni = universo_acoes()
    todos = set().union(*uni.values())
    linhas, amostra = [], []
    for a in sorted(todos):
        if a not in f.columns:
            continue
        s = f[a].dropna()
        s = s[s.index >= "2010-06-01"]
        if len(s) < 400:
            continue
        r5 = s / s.shift(5) - 1.0
        mu = r5.shift(1).rolling(JANELA_Z).mean()
        sd = r5.shift(1).rolling(JANELA_Z).std()
        z = (r5 - mu) / sd
        m21, m50, m200 = s.rolling(21).mean(), s.rolling(50).mean(), s.rolling(200).mean()
        queda = ((r5 <= R5) | (z <= Z5)) & (s < m21) & (s < m50)
        d = pd.DataFrame({"ativo": a, "dia": s.index, "r5": r5.values, "z5": z.values, "A": queda.values, "B": (queda & (s < m200)).values, "abaixo200": (s < m200).values})
        d = d[(d["dia"] >= "2012-01-01") & [a in uni.get(y, set()) for y in d["dia"].dt.year]]
        linhas.append(d)
        amostra.append(d.iloc[::5][["ativo", "dia"]])
    sin = pd.concat(linhas, ignore_index=True)
    return sin, pd.concat(amostra, ignore_index=True)


def eventos(sin, versao, separacao=10):
    """Primeiro dia do sinal por ativo; novo evento so 10 pregoes depois do anterior."""
    out = []
    for a, g in sin[sin[versao]].groupby("ativo"):
        g = g.sort_values("dia")
        ult = None
        idx = {d: i for i, d in enumerate(sin[sin["ativo"] == a]["dia"].sort_values())}
        for _, r in g.iterrows():
            i = idx[r["dia"]]
            if ult is None or i - ult >= separacao:
                out.append(r)
                ult = i
    return pd.DataFrame(out).reset_index(drop=True)


# --------------------------------------------------------------------------------------------------- avaliacao
def _fatores():
    dias = dados.dias_de_pregao()
    cdi = dados.cdi_diario().reindex(dias).fillna(0.0)
    cf = pd.Series(np.cumprod(1.0 + cdi.values), index=dias)
    fech = dados.fechamentos()
    f = dados.fator_retorno_total()
    return cf, fech.stack().rename("fech"), f.stack().rename("tr")


def avaliar(cand, tab, aj=None):
    """cand: DataFrame (ativo, dia). Para cada um monta a put vendida e a trava de credito e o papel. Devolve DataFrame com os retornos."""
    aj = aj or diario.Ajuste()
    cf, fech_s, tr_s = _fatores()
    t = tab[(tab["tipo"] == "P") & (tab["negocios"] >= 30) & tab["boa"] & tab["du"].between(DU_MIN, DU_MAX)]
    m = cand[["ativo", "dia"]].merge(t, on=["ativo", "dia"])
    m["dexp"] = (m["du"] - DU_ALVO).abs()
    m = m[m["dexp"] == m.groupby(["ativo", "dia"])["dexp"].transform("min")]
    m = m[m["vencimento"] == m.groupby(["ativo", "dia"])["vencimento"].transform("min")]
    m["dd"] = (m["delta"].abs() - DELTA_ALVO).abs()
    curta = m[m["dd"] <= DELTA_TOL].sort_values(["ativo", "dia", "dd", "negocios"], ascending=[True, True, True, False]).drop_duplicates(["ativo", "dia"])
    out = curta[["ativo", "dia", "vencimento", "exercicio", "bid", "ask", "delta", "iv", "negocios", "S", "du"]].rename(columns={"exercicio": "K", "bid": "bid_c", "negocios": "neg_c"}).copy()
    # perna comprada da trava
    l = m[["ativo", "dia", "vencimento", "exercicio", "ask", "negocios"]].rename(columns={"exercicio": "Kl", "ask": "ask_l", "negocios": "neg_l"})
    j = out[["ativo", "dia", "vencimento", "K", "S"]].merge(l, on=["ativo", "dia", "vencimento"])
    j = j[j["Kl"] < j["K"]]
    j["dk"] = ((j["Kl"] - LARGURA_ALVO(j)) / j["S"]).abs()
    j = j[j["dk"] <= 0.03].sort_values(["ativo", "dia", "dk", "neg_l"], ascending=[True, True, True, False]).drop_duplicates(["ativo", "dia"])
    out = out.merge(j[["ativo", "dia", "Kl", "ask_l"]], on=["ativo", "dia"], how="left")
    # liquidacao
    v, q = aj.vetor(out["ativo"], out["dia"], out["vencimento"])
    out["prov"] = v
    out["evento_qtd"] = q
    idx = pd.MultiIndex.from_arrays([out["vencimento"], out["ativo"]])
    out["S_T"] = fech_s.reindex(idx).values
    idx0 = pd.MultiIndex.from_arrays([out["dia"], out["ativo"]])
    out["tr0"] = tr_s.reindex(idx0).values
    out["trT"] = tr_s.reindex(idx).values
    out["cdi_f"] = cf.reindex(out["vencimento"]).values / cf.reindex(out["dia"]).values
    out = out[~out["evento_qtd"] & out["S_T"].notna() & out["trT"].notna()].copy()
    KT = out["K"] - out["prov"]
    pay = np.maximum(KT - out["S_T"], 0.0)
    taxa = np.where(pay > 0, C.FEE_EXERC * (KT + out["S_T"]), 0.0)
    out["pay_pct_k"] = pay / out["K"]
    out["ex_put"] = (out["bid_c"] * (1 - FEE) * out["cdi_f"] - pay - taxa) / out["K"]
    KlT = out["Kl"] - out["prov"]
    payl = np.maximum(KlT - out["S_T"], 0.0)
    credito = out["bid_c"] * (1 - FEE) - out["ask_l"] * (1 + FEE)
    larg = out["K"] - out["Kl"]
    ok = out["Kl"].notna() & (credito > 0) & (credito < larg)
    risco = larg - credito
    taxa_s = np.where(pay > 0, C.FEE_EXERC * (KT + out["S_T"]), 0.0) + np.where(payl > 0, C.FEE_EXERC * (KlT + out["S_T"]), 0.0)
    out["ex_trava"] = np.where(ok, (credito * out["cdi_f"] - (pay - payl) - taxa_s) / risco, np.nan)
    out["ex_acao"] = out["trT"] / out["tr0"] - 1.0 - (out["cdi_f"] - 1.0)
    out["queda_ate_o_vencimento_pct"] = (out["S_T"] / out["S"] - 1.0) * 100
    return out


def LARGURA_ALVO(j):
    return j["K"] * (1 - LARGURA)


# --------------------------------------------------------------------------------------------------- estatisticas
def mensal(df, col):
    g = df.dropna(subset=[col]).groupby(df["dia"].dt.to_period("M"))[col].agg(["sum", "count"])
    return g


def t_cluster(df, col):
    g = mensal(df, col)
    if len(g) < 5:
        return None
    m = g["sum"] / g["count"]
    return float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m)))) if m.std(ddof=1) > 0 else None


def dif_bootstrap(a, b, col, n=1000, seed=3):
    """Diferenca de medias (a - b) com bootstrap por mes; devolve (diferenca, desvio, t)."""
    ga, gb = mensal(a, col), mensal(b, col)
    meses = sorted(set(ga.index) | set(gb.index))
    sa = ga.reindex(meses).fillna(0.0).values
    sb = gb.reindex(meses).fillna(0.0).values
    rng = np.random.default_rng(seed)
    d0 = sa[:, 0].sum() / max(sa[:, 1].sum(), 1) - sb[:, 0].sum() / max(sb[:, 1].sum(), 1)
    bs_ = []
    for _ in range(n):
        ix = rng.integers(0, len(meses), len(meses))
        na, nb = sa[ix, 1].sum(), sb[ix, 1].sum()
        if na == 0 or nb == 0:
            continue
        bs_.append(sa[ix, 0].sum() / na - sb[ix, 0].sum() / nb)
    sd = float(np.std(bs_)) if bs_ else float("nan")
    return float(d0), sd, float(d0 / sd) if sd and sd == sd and sd > 0 else None


def resumo_grupo(df, col):
    x = df[col].dropna()
    if len(x) == 0:
        return {"n": 0}
    return {"n": int(len(x)), "media_pct": round(float(x.mean() * 100), 2), "desvio_pct": round(float(x.std(ddof=1) * 100), 2) if len(x) > 1 else None, "t": round(t_cluster(df, col), 2) if t_cluster(df, col) is not None else None,
            "pct_positivos": round(float((x > 0).mean() * 100), 1), "pior_pct": round(float(x.min() * 100), 1), "p5_pct": round(float(np.quantile(x, 0.05) * 100), 1),
            "media_sobre_desvio": round(float(x.mean() / x.std(ddof=1)), 3) if len(x) > 1 and x.std(ddof=1) > 0 else None}


def fase(df, per):
    a, b = PERIODOS[per]
    return df[(df["dia"] >= pd.Timestamp(a)) & (df["dia"] <= pd.Timestamp(b))]


def rodar(fases=("descoberta", "validacao")):
    tab = diario.carregar()
    sin, amostra = sinais()
    aj = diario.Ajuste()
    res = {"definicao": {"queda_5_pregoes": R5, "z_5_pregoes": Z5, "janela_z": JANELA_Z, "delta": DELTA_ALVO, "pregoes_ate_o_vencimento": [DU_MIN, DU_MAX, DU_ALVO], "largura_trava": LARGURA}}
    todos = avaliar(amostra, tab, aj)
    res["todos_os_dias"] = {}
    out = {}
    n_cfg = 4
    for versao in ("A", "B"):
        ev = eventos(sin, versao)
        av = avaliar(ev[["ativo", "dia"]], tab, aj).merge(ev[["ativo", "dia", "r5", "z5"]], on=["ativo", "dia"], how="left")
        out[versao] = av
        res[versao] = {"eventos_brutos": int(len(ev)), "com_put_liquida": int(len(av))}
        for per in fases:
            s, t = fase(av, per), fase(todos, per)
            blocos = {"n_eventos": int(len(s)), "put_vendida": resumo_grupo(s, "ex_put"), "trava_credito": resumo_grupo(s, "ex_trava"), "papel": resumo_grupo(s, "ex_acao"),
                      "put_vendida_todos_os_dias": resumo_grupo(t, "ex_put"), "trava_todos_os_dias": resumo_grupo(t, "ex_trava"), "papel_todos_os_dias": resumo_grupo(t, "ex_acao")}
            d_put = dif_bootstrap(s, t, "ex_put")
            d_trava = dif_bootstrap(s, t, "ex_trava")
            blocos["dif_put_sinal_menos_todos_pp"] = {"dif": round(d_put[0] * 100, 2), "t": round(d_put[2], 2) if d_put[2] is not None else None}
            blocos["dif_trava_sinal_menos_todos_pp"] = {"dif": round(d_trava[0] * 100, 2), "t": round(d_trava[2], 2) if d_trava[2] is not None else None}
            res[versao][per] = blocos
            metricas.registrar(FAMILIA, f"versao {versao} put vendida delta 0,25", per, blocos["put_vendida"])
            metricas.registrar(FAMILIA, f"versao {versao} trava de credito com puts", per, blocos["trava_credito"])
        # veredito fixo
        def v(tipo):
            d, va = res[versao]["descoberta"], res[versao]["validacao"]
            kd, kv = f"dif_{tipo}_sinal_menos_todos_pp", f"dif_{tipo}_sinal_menos_todos_pp"
            gd = d["put_vendida" if tipo == "put" else "trava_credito"]
            gv = va["put_vendida" if tipo == "put" else "trava_credito"]
            if gd.get("n", 0) < 15 or gv.get("n", 0) < 15:
                return "sem amostra"
            td, tv = d[kd]["t"] or 0, va[kv]["t"] or 0
            if gd["media_pct"] > 0 and gv["media_pct"] > 0 and d[kd]["dif"] >= 1 and va[kv]["dif"] >= 1 and td >= 2 and tv >= 1.5:
                return "melhora"
            if d[kd]["dif"] <= -1 and va[kv]["dif"] <= -1 and td <= -2 and tv <= -1.5:
                return "piora"
            return "sem diferenca comprovada"
        res[versao]["veredito"] = {"put_vendida": v("put"), "trava_credito": v("trava")}
    # cauda: piores casos (versao A, descoberta + validacao)
    av = out["A"]
    av = av[(av["dia"] <= "2023-12-31")]
    pior = av.sort_values("ex_put").head(12)
    res["cauda"] = [{"ativo": r["ativo"], "dia": str(r["dia"].date()), "vencimento": str(r["vencimento"].date()), "exercicio": round(float(r["K"]), 2), "preco_na_entrada": round(float(r["S"]), 2),
                     "preco_no_vencimento": round(float(r["S_T"]), 2), "perda_pct_do_exercicio": round(float(-r["ex_put"] * 100), 1), "ex_trava_pct": None if pd.isna(r["ex_trava"]) else round(float(r["ex_trava"] * 100), 1)}
                    for _, r in pior.iterrows()]
    res["quedas_que_continuaram"] = {"pct_eventos_A_com_queda_adicional_acima_de_10pct": round(float((av["queda_ate_o_vencimento_pct"] < -10).mean() * 100), 1),
                                    "pct_eventos_A_exercidos": round(float((av["pay_pct_k"] > 0).mean() * 100), 1), "pct_todos_os_dias_exercidos": round(float((fase(todos, 'descoberta')["ex_put"].notna() & (fase(todos, 'descoberta')["pay_pct_k"] > 0)).mean() * 100), 1)}
    res["n_configuracoes"] = n_cfg
    return res, out, todos


if __name__ == "__main__":
    import json
    r, _, _ = rodar()
    print(json.dumps(r, ensure_ascii=False, indent=1)[:6000])


def cobertura_e_casos(sin, out_A, tab, aj=None):
    """Quantos sinais tinham put executavel (por ano e em marco de 2020), e os casos de cauda pedidos (PETR4 2014-15, marco/2020)."""
    ev = eventos(sin, "A")
    ev = ev[ev["dia"] <= pd.Timestamp("2023-12-31")].copy()          # a prova 2024-2026 nao e aberta: nem contagem nem retorno dos sinais de depois
    av = out_A[out_A["dia"] <= pd.Timestamp("2023-12-31")]
    chave = set(zip(av["ativo"], av["dia"]))
    ev["tem_put"] = [(a, d) in chave for a, d in zip(ev["ativo"], ev["dia"])]
    f = dados.fator_retorno_total()

    def fut(r):
        s = f[r["ativo"]].dropna()
        i = s.index.searchsorted(r["dia"])
        return float(s.iloc[i + 21] / s.iloc[i] - 1) if i + 21 < len(s) else np.nan
    ev["fut21"] = ev.apply(fut, axis=1)
    por_ano = ev.groupby(ev["dia"].dt.year)["tem_put"].agg(["sum", "count"])
    m20 = ev[(ev["dia"] >= "2020-02-20") & (ev["dia"] <= "2020-04-10")]
    petr = av[(av["ativo"] == "PETR4") & (av["dia"] >= "2014-01-01") & (av["dia"] <= "2016-01-01")].sort_values("dia")
    m20av = av[(av["dia"] >= "2020-02-20") & (av["dia"] <= "2020-04-10")]
    return {
        "sinais_A": int(len(ev)), "com_put_executavel": int(ev["tem_put"].sum()), "pct_com_put_executavel": round(float(ev["tem_put"].mean() * 100), 1),
        "por_ano": {int(a): {"sinais": int(r["count"]), "com_put": int(r["sum"])} for a, r in por_ano.iterrows()},
        "marco_2020": {"sinais": int(len(m20)), "com_put_executavel": int(m20["tem_put"].sum()), "retorno_medio_21_pregoes_dos_sinais_pct": round(float(m20["fut21"].mean() * 100), 1),
                       "casos_com_put": [{"ativo": r["ativo"], "dia": str(r["dia"].date()), "perda_pct_do_exercicio": round(float(-r["ex_put"] * 100), 1), "preco_entrada": round(float(r["S"]), 2), "preco_vencimento": round(float(r["S_T"]), 2)} for _, r in m20av.iterrows()]},
        "retorno_21_pregoes_dos_sinais_com_put_pct": round(float(ev.loc[ev["tem_put"], "fut21"].mean() * 100), 2),
        "retorno_21_pregoes_dos_sinais_sem_put_pct": round(float(ev.loc[~ev["tem_put"], "fut21"].mean() * 100), 2),
        "petr4_2014_2015": [{"dia": str(r["dia"].date()), "preco_entrada": round(float(r["S"]), 2), "exercicio": round(float(r["K"]), 2), "preco_vencimento": round(float(r["S_T"]), 2),
                             "resultado_put_pct_do_exercicio": round(float(r["ex_put"] * 100), 1), "resultado_papel_pct": round(float(r["ex_acao"] * 100), 1)} for _, r in petr.iterrows()],
    }

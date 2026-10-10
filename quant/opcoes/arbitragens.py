"""
A5. Arbitragem de verdade no fechamento, com a oferta de compra e a de venda (COTAHIST). Descritivo: quantas, de que tamanho, com que liquidez,
e quantas sobrevivem ao teste de "nao e cotacao velha".

Tipos procurados (todas com precos EXECUTAVEIS: compra na oferta de venda, vende na de compra; custo de bolsa incluido):
  conversao   compra a acao + compra a put + vende a call do mesmo exercicio e vencimento: trava o exercicio K no vencimento
              (dividendo e strike protegido se anulam). Folga = K/(1+juro) - custo liquido.
  reversao    vende a acao (a descoberto) + vende a put + compra a call: o inverso. NAO inclui o aluguel da acao.
  trava_call / trava_put   trava vertical entre exercicios vizinhos que custa menos que zero (compra e recebe) ou que paga mais que a
              diferenca entre os exercicios, trazida a valor presente (vende e recebe mais que o maximo que pode pagar).
  borboleta   borboleta de exercicios vizinhos e igualmente espacados com custo negativo (recebe para montar uma posicao que nunca perde).

SOBREVIVE = todas as pernas com 5+ negocios no dia E ultimo negocio de cada perna dentro das ofertas do fechamento (se a oferta esta
fora do ultimo negocio, ela e quase sempre sobra de livro, nao preco). Folga minima: R$ 0,02 por acao (dois ticks) depois dos custos.
Opcoes exercidas antes do vencimento (americanas) e aluguel de acao NAO entram: por isso e lista de PERGUNTAS ao livro, nao de ordens.
"""
import math

import numpy as np
import pandas as pd

from quant.opcoes import dados
from quant.opcoes import custos as C

FOLGA_MIN = 0.02
FEE_ACAO = C.FEE_EXERC
CHAVE = ["ativo", "dia", "vencimento"]


def _dentro(fech, bid, ask):
    return (fech >= bid - 1e-9) & (fech <= ask + 1e-9)


def varrer(op, sp, dias_ext=None):
    """op: opcoes (colunas da base) de um ou mais dias; sp: acoes (ativo, dia, oferta_compra, oferta_venda). Devolve DataFrame com uma linha por oportunidade."""
    dias = dias_ext if dias_ext is not None else dados.dias_estendidos()
    op = op[(~op["semanal"]) & op["oferta_compra"].notna() & op["oferta_venda"].notna() & (op["oferta_compra"] > 0) & (op["oferta_venda"] >= op["oferta_compra"])].copy()
    cdi = dados.cdi_diario()
    cdi_aa = ((1.0 + cdi.reindex(dias).ffill()) ** 252 - 1.0)
    op["dc"] = (op["vencimento"] - op["dia"]).dt.days
    op = op[op["dc"] >= 3]
    pd_ = np.searchsorted(dias.values, op["dia"].values.astype("datetime64[ns]"))
    pv_ = np.searchsorted(dias.values, op["vencimento"].values.astype("datetime64[ns]"))
    op["t"] = (pv_ - pd_) / 252.0
    op["r"] = np.log1p(cdi_aa.reindex(op["dia"]).values.astype(float))
    op["disc"] = np.exp(-op["r"] * op["t"])
    sp = sp[sp["oferta_compra"].notna() & sp["oferta_venda"].notna()].rename(columns={"oferta_compra": "S_bid", "oferta_venda": "S_ask"})[["ativo", "dia", "S_bid", "S_ask"]]
    sp = sp.drop_duplicates(["ativo", "dia"])
    saida = []

    # ---------------- conversao e reversao
    c = op[op["tipo"] == "C"].drop(columns=["tipo"])
    p = op[op["tipo"] == "P"].drop(columns=["tipo"])
    m = c.merge(p, on=CHAVE + ["exercicio"], suffixes=("_c", "_p")).merge(sp, on=["ativo", "dia"])
    K, disc = m["exercicio"], m["disc_c"]
    custo_conv = m["S_ask"] + m["oferta_venda_p"] - m["oferta_compra_c"]
    tx_conv = FEE_ACAO * (m["S_ask"] + K) + C.FEE_PREMIO * (m["oferta_venda_p"] + m["oferta_compra_c"])
    m["folga_conversao"] = K * disc - custo_conv - tx_conv
    custo_rev = m["S_bid"] + m["oferta_compra_p"] - m["oferta_venda_c"]
    tx_rev = FEE_ACAO * (m["S_bid"] + K) + C.FEE_PREMIO * (m["oferta_compra_p"] + m["oferta_venda_c"])
    m["folga_reversao"] = custo_rev - K * disc - tx_rev
    m["min_neg"] = np.minimum(m["negocios_c"], m["negocios_p"])
    m["dentro"] = _dentro(m["fech_c"], m["oferta_compra_c"], m["oferta_venda_c"]) & _dentro(m["fech_p"], m["oferta_compra_p"], m["oferta_venda_p"])
    # conferencia pelo ULTIMO NEGOCIO das opcoes e o ponto medio da acao: se a folga some, era oferta velha e nao preco
    Sm = (m["S_bid"] + m["S_ask"]) / 2.0
    m["fl_fech_conv"] = K * disc - (Sm + m["fech_p"] - m["fech_c"]) - FEE_ACAO * (Sm + K)
    m["fl_fech_rev"] = (Sm + m["fech_p"] - m["fech_c"]) - K * disc - FEE_ACAO * (Sm + K)
    for tipo, col, colf in (("conversao", "folga_conversao", "fl_fech_conv"), ("reversao", "folga_reversao", "fl_fech_rev")):
        x = m[m[col] >= FOLGA_MIN]
        saida.append(pd.DataFrame({"tipo": tipo, "ativo": x["ativo"], "dia": x["dia"], "vencimento": x["vencimento"], "exercicio": x["exercicio"], "folga": x[col],
                                   "min_negocios": x["min_neg"], "dentro_das_ofertas": x["dentro"], "pernas": x["codigo_c"] + " / " + x["codigo_p"], "preco_ref": x["S_ask"],
                                   "folga_pelo_ultimo_negocio": x[colf]}))

    # ---------------- travas verticais entre exercicios vizinhos
    for tp, nome in (("C", "trava_call"), ("P", "trava_put")):
        o = op[op["tipo"] == tp].sort_values(CHAVE + ["exercicio"])
        g = o.groupby(CHAVE)
        n = pd.DataFrame({
            "ativo": o["ativo"].values, "dia": o["dia"].values, "vencimento": o["vencimento"].values, "K1": o["exercicio"].values,
            "bid1": o["oferta_compra"].values, "ask1": o["oferta_venda"].values, "neg1": o["negocios"].values, "fech1": o["fech"].values, "cod1": o["codigo"].values,
            "disc": o["disc"].values})
        for col, nova in (("exercicio", "K2"), ("oferta_compra", "bid2"), ("oferta_venda", "ask2"), ("negocios", "neg2"), ("fech", "fech2"), ("codigo", "cod2")):
            n[nova] = g[col].shift(-1).values
        n = n[n["K2"].notna() & (n["K2"] > n["K1"])]
        larg = n["K2"] - n["K1"]
        if tp == "C":
            comprar = n["ask1"] - n["bid2"]                      # compra c1, vende c2: custo
            vender = n["bid1"] - n["ask2"]                       # vende c1, compra c2: recebe
        else:
            comprar = n["ask2"] - n["bid1"]                      # compra p2 (strike alto), vende p1: custo
            vender = n["bid2"] - n["ask1"]                       # vende p2, compra p1: recebe
        tx = C.FEE_PREMIO * (n["ask1"] + n["bid1"] + n["ask2"] + n["bid2"]) / 2.0
        f1 = -comprar - tx                                       # custo negativo: recebe para ter posicao que nao perde
        f2 = vender - larg * n["disc"] - tx                      # recebe mais que o maximo que pode pagar
        n["min_neg"] = np.minimum(n["neg1"], n["neg2"])
        n["dentro"] = _dentro(n["fech1"], n["bid1"], n["ask1"]) & _dentro(n["fech2"], n["bid2"], n["ask2"])
        for sub, folga in (("custo_negativo", f1), ("recebe_mais_que_o_maximo", f2)):
            x = n[folga >= FOLGA_MIN]
            saida.append(pd.DataFrame({"tipo": nome, "ativo": x["ativo"], "dia": x["dia"], "vencimento": x["vencimento"], "exercicio": x["K1"], "folga": folga[folga >= FOLGA_MIN],
                                       "min_negocios": x["min_neg"], "dentro_das_ofertas": x["dentro"], "pernas": x["cod1"] + " / " + x["cod2"], "preco_ref": np.nan, "sub": sub}))

    # ---------------- borboleta de custo negativo (exercicios vizinhos igualmente espacados)
    o = op[op["tipo"] == "C"].sort_values(CHAVE + ["exercicio"])
    g = o.groupby(CHAVE)
    b = pd.DataFrame({"ativo": o["ativo"].values, "dia": o["dia"].values, "vencimento": o["vencimento"].values, "K1": o["exercicio"].values,
                      "ask1": o["oferta_venda"].values, "neg1": o["negocios"].values, "fech1": o["fech"].values, "bid1": o["oferta_compra"].values, "cod1": o["codigo"].values})
    for k in (1, 2):
        for col, nova in (("exercicio", f"K{k + 1}"), ("oferta_compra", f"bid{k + 1}"), ("oferta_venda", f"ask{k + 1}"), ("negocios", f"neg{k + 1}"), ("fech", f"fech{k + 1}"), ("codigo", f"cod{k + 1}")):
            b[nova] = g[col].shift(-k).values
    b = b[b["K3"].notna() & ((b["K2"] - b["K1"]) - (b["K3"] - b["K2"])).abs().lt(1e-6) & (b["K2"] > b["K1"])]
    custo = b["ask1"] + b["ask3"] - 2.0 * b["bid2"]
    tx = C.FEE_PREMIO * (b["ask1"] + b["ask3"] + 2.0 * b["bid2"])
    folga = -custo - tx
    b["min_neg"] = np.minimum(np.minimum(b["neg1"], b["neg2"]), b["neg3"])
    b["dentro"] = _dentro(b["fech1"], b["bid1"], b["ask1"]) & _dentro(b["fech2"], b["bid2"], b["ask2"]) & _dentro(b["fech3"], b["bid3"], b["ask3"])
    x = b[folga >= FOLGA_MIN]
    saida.append(pd.DataFrame({"tipo": "borboleta", "ativo": x["ativo"], "dia": x["dia"], "vencimento": x["vencimento"], "exercicio": x["K2"], "folga": folga[folga >= FOLGA_MIN],
                               "min_negocios": x["min_neg"], "dentro_das_ofertas": x["dentro"], "pernas": x["cod1"] + " / " + x["cod2"] + " / " + x["cod3"], "preco_ref": np.nan}))
    r = pd.concat(saida, ignore_index=True)
    ref = sp.assign(S_ref=(sp["S_bid"] + sp["S_ask"]) / 2.0)[["ativo", "dia", "S_ref"]]
    r = r.drop(columns=["preco_ref"]).merge(ref, on=["ativo", "dia"], how="left")
    r["dc"] = (r["vencimento"] - r["dia"]).dt.days
    r["moneyness"] = r["exercicio"] / r["S_ref"]
    r["sobrevive"] = (r["min_negocios"] >= 5) & r["dentro_das_ofertas"]
    # estrita: liquidez de verdade (20+ negocios nas pernas), prazo de ate 90 dias e exercicio a ate 15% do preco do ativo
    r["estrita"] = r["sobrevive"] & (r["min_negocios"] >= 20) & (r["dc"] <= 90) & ((r["moneyness"] - 1.0).abs() <= 0.15)
    return r


def resumo_historico(r, dias_total):
    """Quantas por dia, tamanho e quantas sobrevivem, por tipo."""
    est = r[r["estrita"] & r["folga_pelo_ultimo_negocio"].notna()]
    # persistencia: a mesma combinacao de pernas aparece de novo no pregao seguinte?
    ch = r[["pernas", "dia"]].drop_duplicates()
    dias_ord = sorted(r["dia"].unique())
    prox = {d: dias_ord[i + 1] for i, d in enumerate(dias_ord[:-1])}
    vistos = set(zip(ch["pernas"], ch["dia"]))
    est_all = r[r["estrita"]]
    pers = np.mean([(p, prox[d]) in vistos for p, d in zip(est_all["pernas"], est_all["dia"]) if d in prox]) if len(est_all) else float("nan")
    out = {"dias_na_amostra": int(dias_total), "total_detectadas": int(len(r)), "por_dia_media": round(len(r) / max(dias_total, 1), 2),
           "sobrevivem": int(r["sobrevive"].sum()), "sobrevivem_por_dia": round(float(r["sobrevive"].sum() / max(dias_total, 1)), 3),
           "estritas": int(r["estrita"].sum()), "estritas_por_dia": round(float(r["estrita"].sum() / max(dias_total, 1)), 3),
           "dias_com_estrita": int(r.loc[r["estrita"], "dia"].nunique()),
           "estritas_conv_rev_com_folga_tambem_no_ultimo_negocio_pct": round(float((est["folga_pelo_ultimo_negocio"] >= FOLGA_MIN).mean() * 100), 1) if len(est) else None,
           "estritas_que_reaparecem_no_pregao_seguinte_pct": round(float(pers * 100), 1) if pers == pers else None, "por_tipo": {}}
    for t, g in r.groupby("tipo"):
        s = g[g["sobrevive"]]
        out["por_tipo"][t] = {"detectadas": int(len(g)), "folga_mediana_rs": round(float(g["folga"].median()), 3), "folga_maxima_rs": round(float(g["folga"].max()), 2),
                              "negocios_mediano": int(g["min_negocios"].median()), "sobrevivem": int(len(s)),
                              "sobrevivem_folga_mediana_rs": round(float(s["folga"].median()), 3) if len(s) else None,
                              "sobrevivem_folga_maxima_rs": round(float(s["folga"].max()), 2) if len(s) else None,
                              "dias_com_alguma_sobrevivente": int(s["dia"].nunique()) if len(s) else 0,
                              "estritas": int(g["estrita"].sum()), "estritas_folga_mediana_rs": round(float(g.loc[g["estrita"], "folga"].median()), 3) if g["estrita"].any() else None,
                              "estritas_folga_maxima_rs": round(float(g.loc[g["estrita"], "folga"].max()), 2) if g["estrita"].any() else None}
    return out

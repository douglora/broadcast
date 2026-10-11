"""
ITEM 3. EVENTO BINARIO: OPCAO NO LUGAR DO PAPEL. Estudo DESCRITIVO (poucos eventos: nao ha regra aqui).

Eleicoes (domingo; o pregao de reacao R e a segunda-feira seguinte): 2014 (05/10 e 26/10), 2018 (07/10 e 28/10), 2022 (02/10 e 30/10).
Entrada no fechamento 10, 5 e 1 pregao antes de R; saida no fechamento de R (1 pregao depois) e de R+4 (5 pregoes depois).
Estruturas: papel, call no dinheiro, trava de alta (compra no dinheiro, vende ~10% acima), put no dinheiro, straddle. Opcao do primeiro vencimento
com pelo menos 8 pregoes depois da saida. Compra na oferta de venda e saida na oferta de compra; SEM oferta no dia, o ultimo negocio com 5% contra
(marcado `estimado`). Serie sem negocio no dia da saida: o evento sai da conta daquela estrutura.

Para cada evento e estrutura: a volatilidade implicita no dinheiro na entrada e na saida (esmagamento), o movimento que o preco da opcao EXIGIA
para empatar na saida (Black-Scholes com a volatilidade da saida) e o movimento que veio.

Tambem, em serie maior (resultado trimestral na CVM): call no dinheiro contra papel no MESMO lado, entrada 5 pregoes antes do protocolo e saida
no dia seguinte (usa as series do teste A6).
"""
import math
import os

import numpy as np
import pandas as pd

from quant.opcoes import bs, dados
from quant.opcoes import custos as C
from quant.opcoes.base import DIR_DADOS

FEE = C.FEE_PREMIO
ELEICOES = [("2014-10-05", "1º turno 2014"), ("2014-10-26", "2º turno 2014"), ("2018-10-07", "1º turno 2018"), ("2018-10-28", "2º turno 2018"),
            ("2022-10-02", "1º turno 2022"), ("2022-10-30", "2º turno 2022")]
ATIVOS = ["BBAS3", "PETR4", "ELET3", "CMIG4", "SBSP3"]
ATIVOS_COM_INDICE = ATIVOS + ["IBOV"]
ENTRADAS = (10, 5, 1)
SAIDAS = (1, 5)


def _pregao_reacao(domingo):
    dias = dados.dias_de_pregao()
    i = int(np.searchsorted(dias.values, np.datetime64(pd.Timestamp(domingo)), side="right"))
    return dias[i], i


def _juro(dia):
    c = dados.cdi_diario()
    v = c.reindex(dados.dias_estendidos()).ffill().get(dia, 0.0005)
    return math.log1p((1.0 + float(v)) ** 252 - 1.0)


def _preco_entrada(r, lado):
    """compra: oferta de venda; venda: oferta de compra; senao ultimo negocio com 5% contra. Devolve (preco, estimado)."""
    if lado == "compra":
        if r["oferta_venda"] == r["oferta_venda"] and r["oferta_venda"] > 0:
            return float(r["oferta_venda"]), False
        return float(r["fech"]) * 1.05, True
    if r["oferta_compra"] == r["oferta_compra"] and r["oferta_compra"] > 0:
        return float(r["oferta_compra"]), False
    return float(r["fech"]) * 0.95, True


def _preco_saida(r, lado_entrada):
    """sai da posicao comprada na oferta de compra; da vendida, na de venda. Sem oferta, ultimo negocio com 5% contra."""
    if lado_entrada == "compra":
        if r["oferta_compra"] == r["oferta_compra"] and r["oferta_compra"] > 0:
            return float(r["oferta_compra"]), False
        return float(r["fech"]) * 0.95, True
    if r["oferta_venda"] == r["oferta_venda"] and r["oferta_venda"] > 0:
        return float(r["oferta_venda"]), False
    return float(r["fech"]) * 1.05, True


def _serie(op, ativo, dia):
    d = op[(op["ativo"] == ativo) & (op["dia"] == dia) & (~op["semanal"]) & (op["negocios"] >= 3)]
    return d


def _empate(S0, K, t_rem, r, iv, put, custo):
    """Preco do ativo na saida em que a opcao (valor de Black-Scholes com a volatilidade da saida, menos emolumento) iguala o custo da entrada."""
    f = lambda S: bs.preco(S, K, t_rem, r, iv, put) * (1 - FEE) - custo  # noqa: E731
    lo, hi = 0.3 * S0, 3.0 * S0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if f(mid) * flo > 0:
            lo, flo = mid, f(mid)
        else:
            hi = mid
    return 0.5 * (lo + hi)


def evento_acao(ativo, d_in, d_out, spot_ser, painel, cache_op):
    """Resultados de papel, call, trava, put e straddle para um ativo e um par (entrada, saida). None se nao houver opcao."""
    ano = d_in.year
    if ano not in cache_op:
        cache_op[ano] = dados.carregar_opcoes(ano, ano)
    op = cache_op[ano]
    dias = dados.dias_estendidos()
    S_in, S_out = spot_ser.get(d_in), spot_ser.get(d_out)
    if S_in is None or S_out is None or S_in != S_in or S_out != S_out:
        return None
    pos = lambda d: int(np.searchsorted(dias.values, np.datetime64(d)))  # noqa: E731
    h = pos(d_out) - pos(d_in)
    e = _serie(op, ativo, d_in)
    if e.empty:
        return None
    e = e.assign(du=[pos(v) - pos(d_in) for v in e["vencimento"]])
    e = e[e["du"] >= h + 8]
    if e.empty:
        return None
    venc = e["vencimento"].min()
    e = e[e["vencimento"] == venc]
    saida = op[(op["ativo"] == ativo) & (op["dia"] == d_out) & (op["vencimento"] == venc)].set_index("codigo")
    c, p = e[e["tipo"] == "C"], e[e["tipo"] == "P"]
    m = c.merge(p, on="exercicio", suffixes=("_c", "_p"))
    m = m.assign(dist=(m["exercicio"] / S_in - 1).abs()).sort_values("dist")
    m = m[m["dist"] <= 0.05]
    if m.empty:
        return None
    k = m.iloc[0]
    K = float(k["exercicio"])
    rc = {x[:-2]: k[x] for x in k.index if x.endswith("_c")}
    rp = {x[:-2]: k[x] for x in k.index if x.endswith("_p")}
    out = {"ativo": ativo, "entrada": d_in, "saida": d_out, "S_in": S_in, "S_out": S_out, "K": K, "vencimento": venc, "pregoes_entre": h,
           "du_ate_vencimento": int(k["du_c"]) if "du_c" in k else None, "papel": S_out / S_in - 1.0}
    est_flag = False

    def perna(r, lado):
        nonlocal est_flag
        pe, es = _preco_entrada(r, lado)
        if r["codigo"] not in saida.index:
            return None
        ps, es2 = _preco_saida(saida.loc[r["codigo"]], lado)
        est_flag = est_flag or es or es2
        return pe, ps

    pc, pp = perna(rc, "compra"), perna(rp, "compra")
    if pc:
        out["call"] = pc[1] * (1 - FEE) / (pc[0] * (1 + FEE)) - 1.0
        out["custo_call_pct"] = pc[0] * (1 + FEE) / S_in * 100
    if pp:
        out["put"] = pp[1] * (1 - FEE) / (pp[0] * (1 + FEE)) - 1.0
    if pc and pp:
        out["straddle"] = (pc[1] + pp[1]) * (1 - FEE) / ((pc[0] + pp[0]) * (1 + FEE)) - 1.0
    # trava de alta: vende call ~10% acima
    cc = c.assign(d2=(c["exercicio"] / S_in - 1.10).abs()).sort_values("d2")
    cc = cc[(cc["d2"] <= 0.04) & (cc["exercicio"] > K)]
    if pc and len(cc):
        rs = cc.iloc[0]
        ps_ = perna(rs, "venda")
        if ps_:
            nl = (pc[0] * (1 + FEE)) - ps_[0] * (1 - FEE)
            if nl > 0:
                out["trava_alta"] = ((pc[1] * (1 - FEE)) - ps_[1] * (1 + FEE)) / nl - 1.0
    out["estimado"] = est_flag
    # volatilidade implicita no dinheiro na entrada e na saida e o movimento exigido para empatar
    r_in, r_out = _juro(d_in), _juro(d_out)
    t_in, t_out = (pos(venc) - pos(d_in)) / 252.0, (pos(venc) - pos(d_out)) / 252.0
    def ivs(r_c, r_p, preco_c, preco_p, S, t, rr):
        vs = [bs.vol_implicita(preco_c, S, K, t, rr, False), bs.vol_implicita(preco_p, S, K, t, rr, True)]
        vs = [v for v in vs if v]
        return float(np.mean(vs)) if vs else None
    if pc and pp:
        pc_out = pc[1]
        pp_out = pp[1]
        out["iv_in"] = ivs(rc, rp, (pc[0] + 0.0), (pp[0] + 0.0), S_in, t_in, r_in)
        out["iv_out"] = ivs(rc, rp, pc_out, pp_out, S_out, t_out, r_out)
        if out["iv_in"] and out["iv_out"]:
            out["esmagamento_vol_pct"] = (out["iv_out"] / out["iv_in"] - 1.0) * 100
            cu = _empate(S_in, K, t_out, r_out, out["iv_out"], False, pc[0] * (1 + FEE))
            pu = _empate(S_in, K, t_out, r_out, out["iv_out"], True, pp[0] * (1 + FEE))
            if cu:
                out["exigido_call_pct"] = (cu / S_in - 1.0) * 100
            if pu:
                out["exigido_put_pct"] = (pu / S_in - 1.0) * 100
            out["movimento_veio_pct"] = (S_out / S_in - 1.0) * 100
    return out


def estudo_eleicoes():
    fech = dados.fechamentos().copy()
    fech["IBOV"] = dados.ibov()
    cache = {}
    for y in sorted({int(x[0][:4]) for x in ELEICOES}):
        op = dados.carregar_opcoes(y, y, ativos=ATIVOS)
        ix = pd.read_parquet(os.path.join(DIR_DADOS, f"indice_{y}.parquet"))
        ix["semanal"] = False
        cache[y] = pd.concat([op, ix[[c for c in op.columns if c in ix.columns]]], ignore_index=True)
    linhas = []
    for dom, rot in ELEICOES:
        R, iR = _pregao_reacao(dom)
        dias = dados.dias_de_pregao()
        for ativo in ATIVOS_COM_INDICE:
            if ativo not in fech.columns:
                continue
            ser = fech[ativo].dropna()
            for k in ENTRADAS:
                for j in SAIDAS:
                    d_in, d_out = dias[iR - k], dias[iR + j - 1]
                    r = evento_acao(ativo, d_in, d_out, ser, None, cache)
                    if r:
                        r.update({"evento": rot, "turno": rot[:1], "ano": int(rot[-4:]), "k": k, "j": j})
                        linhas.append(r)
    return pd.DataFrame(linhas)


def resumo_eleicoes(df):
    """Medias por (entrada, saida) e por estrutura; tabela por evento para BBAS3; esmagamento e exigido contra veio."""
    out = {"n_eventos": 6, "n_linhas": int(len(df)), "aviso": "6 eventos (3 eleicoes x 2 turnos), 5 ativos, entradas e saidas que se sobrepoem: NAO e amostra para regra."}
    est = ["papel", "call", "trava_alta", "put", "straddle"]
    tab = []
    for (k, j), g in df.groupby(["k", "j"]):
        tab.append({"entrada_pregoes_antes": int(k), "saida_pregoes_depois": int(j), **{e: (round(float(g[e].mean() * 100), 1), int(g[e].notna().sum())) for e in est if e in g}})
    out["medias_por_entrada_saida"] = tab
    b = df[(df["ativo"] == "BBAS3") & (df["k"] == 5) & (df["j"] == 5)].sort_values(["ano", "turno"])
    out["bbas3_k5_j5"] = [{"evento": r["evento"], **{e: (None if pd.isna(r.get(e)) else round(float(r[e] * 100), 1)) for e in est}, "iv_in": None if pd.isna(r.get("iv_in")) else round(float(r["iv_in"] * 100), 1),
                          "iv_out": None if pd.isna(r.get("iv_out")) else round(float(r["iv_out"] * 100), 1), "esmagamento_pct": None if pd.isna(r.get("esmagamento_vol_pct")) else round(float(r["esmagamento_vol_pct"]), 1),
                          "exigido_call_pct": None if pd.isna(r.get("exigido_call_pct")) else round(float(r["exigido_call_pct"]), 1), "veio_pct": None if pd.isna(r.get("movimento_veio_pct")) else round(float(r["movimento_veio_pct"]), 1),
                          "estimado": bool(r["estimado"])} for _, r in b.iterrows()]
    c = df[(df["j"] == 1)].dropna(subset=["esmagamento_vol_pct"])
    out["esmagamento_vol_pct"] = {"n": int(len(c)), "mediana": round(float(c["esmagamento_vol_pct"].median()), 1), "media": round(float(c["esmagamento_vol_pct"].mean()), 1),
                                  "p25": round(float(c["esmagamento_vol_pct"].quantile(0.25)), 1), "p75": round(float(c["esmagamento_vol_pct"].quantile(0.75)), 1)}
    c5 = df[(df["j"] == 5)].dropna(subset=["esmagamento_vol_pct"])
    out["esmagamento_vol_pct_5_pregoes"] = {"n": int(len(c5)), "mediana": round(float(c5["esmagamento_vol_pct"].median()), 1)} if len(c5) else None
    d = df.dropna(subset=["exigido_call_pct", "movimento_veio_pct"])
    out["call_exigia_empatar_mediano_pct"] = round(float(d["exigido_call_pct"].median()), 1) if len(d) else None
    out["movimento_absoluto_que_veio_mediano_pct"] = round(float(d["movimento_veio_pct"].abs().median()), 1) if len(d) else None
    out["calls_que_empataram_na_saida_pct"] = round(float((d["movimento_veio_pct"] >= d["exigido_call_pct"]).mean() * 100), 1) if len(d) else None
    out["linhas_estimadas_pct"] = round(float(df["estimado"].mean() * 100), 1)
    # por ativo: quantos eventos tiveram opcao
    out["linhas_por_ativo"] = {k: int(v) for k, v in df.groupby("ativo").size().items()}
    return out


# ------------------------------------------------------------------------------------------------------- serie maior: resultado trimestral
def resultado_call_contra_papel(m):
    """m: eventos do A6 (com S_in e S_out). Compara call no dinheiro com papel no MESMO lado e put com papel vendido."""
    from quant.opcoes.pesquisa import PERIODOS
    m = m.copy()
    m["ret_papel"] = m["S_out"] / m["S_in"] - 1.0
    m["ret_call"] = m["bid_c"] * (1 - FEE) / (m["oferta_venda_c"] * (1 + FEE)) - 1.0
    m["ret_put"] = m["bid_p"] * (1 - FEE) / (m["oferta_venda_p"] * (1 + FEE)) - 1.0
    out = {}
    for per in ("descoberta", "validacao"):
        a, b = PERIODOS[per]
        x = m[(m["T"] >= pd.Timestamp(a)) & (m["T"] <= pd.Timestamp(b))]
        alta, baixa = x[x["ret_papel"] > 0], x[x["ret_papel"] < 0]
        def bloco(g, opc, sinal):
            if len(g) == 0:
                return {"n": 0}
            papel = sinal * g["ret_papel"]
            dif = g[opc] - papel
            return {"n": int(len(g)), "papel_medio_pct": round(float(papel.mean() * 100), 2), "opcao_media_pct": round(float(g[opc].mean() * 100), 1),
                    "opcao_melhor_que_o_papel_pct_dos_eventos": round(float((g[opc] > papel).mean() * 100), 1), "opcao_positiva_pct": round(float((g[opc] > 0).mean() * 100), 1),
                    "mov_papel_mediano_pct": round(float(papel.median() * 100), 2)}
        out[per] = {"n_eventos": int(len(x)), "papel_subiu": bloco(alta, "ret_call", 1), "papel_caiu": bloco(baixa, "ret_put", -1)}
        # por tamanho do movimento
        grande = x[x["ret_papel"].abs() >= 0.05]
        out[per]["movimento_de_5pct_ou_mais"] = {"n": int(len(grande)), "call_media_pct_quando_subiu": round(float(grande[grande["ret_papel"] > 0]["ret_call"].mean() * 100), 1) if (grande["ret_papel"] > 0).any() else None,
                                                  "put_media_pct_quando_caiu": round(float(grande[grande["ret_papel"] < 0]["ret_put"].mean() * 100), 1) if (grande["ret_papel"] < 0).any() else None}
    return out

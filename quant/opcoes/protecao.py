"""
Protecao de uma carteira espelhada no BOVA11 com opcoes de BOVA11, contra a venda de mini-indice (WIN).

Carteira: comprada em BOVA11, retorno total pelo Ibovespa (que ja e indice de retorno total) menos 0,10% ao ano de taxa.
A cada ciclo mensal (entrada no primeiro pregao depois do vencimento anterior, saida no vencimento):

  nu          so a carteira
  put         compra de put delta ~ -0,25 (na oferta de venda)
  trava       trava de baixa com puts: compra put delta ~ -0,30 e vende put delta ~ -0,10
  colar       compra put delta ~ -0,25 e vende call delta ~ +0,25 (na oferta de compra)
  win100      vende mini-indice com nocional = carteira (hedge cheio)
  win50       vende mini-indice com metade do nocional

PARAMETROS FIXADOS A PRIORI (nao otimizados): os deltas acima; liquidez minima 30 negocios e spread <= 30% em CADA perna.
Ciclo sem perna liquida: a carteira fica sem hedge naquele mes (e o numero de meses assim aparece no resultado).

A venda de mini-indice e modelada por identidade de custo de carregamento (ver quant/dados/mercado.py): um futuro
colateralizado paga a variacao do indice menos o CDI; quem vende ganha o oposto. Resultado do WIN no ciclo =
-(retorno do Ibovespa - CDI do ciclo) x nocional, menos R$ 0,01% de custo por ciclo (corretagem e emolumentos de um contrato
sao desprezíveis; o erro do modelo e a base do futuro contra o fair value, que nao foi medida porque o historico do WIN
nao esta na base). BOVA11 so tem opcao liquida a partir de 2020: antes disso a funcao nao se aplica.
"""
import numpy as np
import pandas as pd

from quant.opcoes import custos as C
from quant.opcoes import dados, motor

WIN_CUSTO = 0.0001
TOL = 0.07


def _linha(cad, tipo, delta, lado):
    el = motor.liquidas(cad, tipo)
    s = motor.mais_perto_do_delta(el, delta, tol=TOL)
    return s.set_index("T")


def ciclos_bova(cad, cic, ini="2020-01-01", fim="2026-12-31"):
    b = cad[(cad["ativo"] == "BOVA11") & (cad["T"] >= pd.Timestamp(ini)) & (cad["T"] <= pd.Timestamp(fim))].copy()
    b = b[b["escolhido"]]
    base = b.drop_duplicates("T")[["T", "E", "S_E", "S_T", "tr", "cdi_ciclo"]].set_index("T")
    base = base[base["tr"].notna() & base["S_E"].notna()]
    base = base.join(cic.set_index("T")[["du"]])
    return b, base


def simular(cad, cic, ini="2020-01-01", fim="2026-12-31", exec="oferta"):
    b, base = ciclos_bova(cad, cic, ini, fim)
    put25 = _linha(b, "P", 0.25, "compra")
    put30 = _linha(b, "P", 0.30, "compra")
    put10 = _linha(b, "P", 0.10, "venda")
    call25 = _linha(b, "C", 0.25, "venda")

    def compra(s):
        return (s["oferta_venda"] if exec == "oferta" else s["mid"]) * (1 + C.FEE_PREMIO)

    def venda(s):
        return (s["oferta_compra"] if exec == "oferta" else s["mid"]) * (1 - C.FEE_PREMIO)

    out = base.copy()
    out["ex_nu"] = out["tr"] - out["cdi_ciclo"]
    # put comprada
    p = put25.reindex(out.index)
    out["tem_put"] = p["codigo"].notna()
    out["pnl_put"] = (p["payoff_T"] - compra(p) * (1 + p["cdi_ciclo"]) - np.where(p["payoff_T"] > 0, C.FEE_EXERC * p["K_T"], 0.0)) / out["S_E"]
    out["custo_put_pct"] = compra(p) / out["S_E"] * 100
    out["k_put_pct"] = p["exercicio"] / out["S_E"] * 100
    # trava de baixa
    l, c = put30.reindex(out.index), put10.reindex(out.index)
    ok = l["codigo"].notna() & c["codigo"].notna() & (l["exercicio"] > c["exercicio"]).fillna(False)
    out["tem_trava"] = ok
    debito = compra(l) - venda(c)
    pay = l["payoff_T"] - c["payoff_T"]
    out["pnl_trava"] = np.where(ok, (pay - debito * (1 + l["cdi_ciclo"]) - np.where(l["payoff_T"] > 0, C.FEE_EXERC * l["K_T"], 0.0)) / out["S_E"], 0.0)
    out["custo_trava_pct"] = np.where(ok, debito / out["S_E"] * 100, np.nan)
    # colar
    cl = call25.reindex(out.index)
    okc = p["codigo"].notna() & cl["codigo"].notna()
    out["tem_colar"] = okc
    pnl_call = venda(cl) * (1 + cl["cdi_ciclo"]) - cl["payoff_T"] - np.where(cl["payoff_T"] > 0, C.FEE_EXERC * cl["K_T"], 0.0)
    out["pnl_colar"] = np.where(okc, (p["payoff_T"] - compra(p) * (1 + p["cdi_ciclo"]) + pnl_call
                                        - np.where(p["payoff_T"] > 0, C.FEE_EXERC * p["K_T"], 0.0)) / out["S_E"], 0.0)
    # mini-indice vendido
    ib = dados.ibov()
    r_ib = pd.Series([ib[t] / ib[e] - 1.0 for e, t in zip(out["E"], out.index)], index=out.index)
    win = -(r_ib - out["cdi_ciclo"]) - WIN_CUSTO
    out["ex_win100"] = out["ex_nu"] + win
    out["ex_win50"] = out["ex_nu"] + 0.5 * win
    out["ex_put"] = out["ex_nu"] + out["pnl_put"].where(out["tem_put"], 0.0)
    out["ex_trava"] = out["ex_nu"] + out["pnl_trava"].where(out["tem_trava"], 0.0)
    out["ex_colar"] = out["ex_nu"] + out["pnl_colar"].where(out["tem_colar"], 0.0)
    out["ret_ibov"] = r_ib
    return out.reset_index()


ESTRATEGIAS = ["nu", "put", "trava", "colar", "win50", "win100"]


def tabela(ciclos, ini=None, fim=None):
    """Metricas de cada variante num recorte de ciclos (por T)."""
    from quant.opcoes import metricas
    c = ciclos
    if ini is not None:
        c = c[(c["T"] >= pd.Timestamp(ini)) & (c["T"] <= pd.Timestamp(fim))]
    lin = []
    for e in ESTRATEGIAS:
        m = metricas.calcular(c[f"ex_{e}"].values, c["cdi_ciclo"].values, None, c["E"].iloc[0], c["T"].iloc[-1],
                              anos=c["du"].sum() / 252.0)
        if e == "win100":
            m["sharpe"] = None            # desvio quase zero: o Sharpe nao quer dizer nada
        m["variante"] = e
        lin.append(m)
    return pd.DataFrame(lin).set_index("variante")


def janela(ciclos, ini, fim):
    """Retorno acumulado TOTAL (CDI + excesso) de cada variante nos ciclos com T no recorte, em %."""
    c = ciclos[(ciclos["T"] >= pd.Timestamp(ini)) & (ciclos["T"] <= pd.Timestamp(fim))]
    out = {}
    for e in ESTRATEGIAS:
        out[e] = round((float(np.prod(1 + c["cdi_ciclo"].values + c[f"ex_{e}"].values)) - 1) * 100, 2)
    out["n_ciclos"] = len(c)
    return out


# ------------------------------------------------------------------------------------------------ opcoes do INDICE (2013-2019)
def simular_indice(ano_ini=2013, ano_fim=2019, sp_est=0.05, neg_min=3):
    """Mesma comparacao do BOVA11, para os anos em que BOVA11 nao tinha opcao liquida, usando as opcoes sobre o proprio
    Ibovespa (CODBDI 74/75; premio e exercicio em pontos). Ciclo = entre dois vencimentos padrao (quarta-feira de mes par,
    cerca de DOIS meses; vencimentos com menos de 2.000 negocios no total nao contam como padrao). Alvos fixos: put a 95% do
    indice; trava de baixa 95%/85%; colar put 95% e call 105%. Precos: oferta do fechamento quando existe; SEM oferta (a
    regra, antes de 2020), ultimo negocio com 5% contra quem compra (ou vende) -- ESTIMATIVA, marcada em `estimado`.
    A serie precisa ter `neg_min` negocios na entrada."""
    import glob
    import os
    from quant.opcoes.base import DIR_DADOS
    d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(DIR_DADOS, "indice_20*.parquet")))
                   if ano_ini - 1 <= int(f[-12:-8]) <= ano_fim + 1])
    ib = dados.ibov()
    dias = dados.dias_de_pregao()
    v = d.groupby("vencimento")["negocios"].sum()
    padrao = list(v[v >= 2000].index)
    lin = []
    for p, t in zip(padrao[:-1], padrao[1:]):
        if t.year < ano_ini or t.year > ano_fim:
            continue
        e_idx = dados.indice_de_dia(dias, p) + 1
        e = dias[e_idx]
        if e not in ib.index or t not in ib.index:
            continue
        s_e, s_t = float(ib[e]), float(ib[t])
        x = d[(d["dia"] == e) & (d["vencimento"] == t) & (d["negocios"] >= neg_min) & (d["fech"] > 0)]

        def pegar(tipo, alvo, compra):
            y = x[x["tipo"] == tipo]
            if y.empty:
                return None
            r = y.iloc[(y["exercicio"] / s_e - alvo).abs().argsort()[:1]].iloc[0]
            if abs(r["exercicio"] / s_e - alvo) > 0.03:
                return None
            q = r["oferta_venda"] if compra else r["oferta_compra"]
            est = not (q == q and q > 0)
            if est:
                q = r["fech"] * (1 + sp_est if compra else 1 - sp_est)
            return {"k": float(r["exercicio"]), "q": float(q), "est": bool(est), "payoff": max(r["exercicio"] - s_t, 0.0) if tipo == "P" else max(s_t - r["exercicio"], 0.0)}

        cdi = dados.acumular_cdi(e, t) - 1.0
        p95, p85, c105 = pegar("P", 0.95, True), pegar("P", 0.85, False), pegar("C", 1.05, False)
        nu = s_t / s_e - 1.0 - cdi
        row = {"E": e, "T": t, "cdi_ciclo": cdi, "du": dados.indice_de_dia(dias, t) - dados.indice_de_dia(dias, e),
               "ret_ibov": s_t / s_e - 1.0, "ex_nu": nu, "tem_put": p95 is not None}
        f = 1 + C.FEE_PREMIO
        row["pnl_put"] = (p95["payoff"] - p95["q"] * f * (1 + cdi)) / s_e if p95 else 0.0
        row["custo_put_pct"] = p95["q"] / s_e * 100 if p95 else np.nan
        row["estimado"] = bool(p95["est"]) if p95 else None
        ok = bool(p95 and p85)
        row["tem_trava"] = ok
        row["pnl_trava"] = ((p95["payoff"] - p85["payoff"]) - (p95["q"] * f - p85["q"] * (1 - C.FEE_PREMIO)) * (1 + cdi)) / s_e if ok else 0.0
        okc = bool(p95 and c105)
        row["tem_colar"] = okc
        row["pnl_colar"] = ((p95["payoff"] - c105["payoff"]) - (p95["q"] * f - c105["q"] * (1 - C.FEE_PREMIO)) * (1 + cdi)) / s_e if okc else 0.0
        win = -(s_t / s_e - 1.0 - cdi) - WIN_CUSTO
        row["ex_win100"], row["ex_win50"] = nu + win, nu + 0.5 * win
        row["ex_put"] = nu + row["pnl_put"]
        row["ex_trava"] = nu + row["pnl_trava"]
        row["ex_colar"] = nu + row["pnl_colar"]
        lin.append(row)
    return pd.DataFrame(lin)

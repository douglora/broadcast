"""
Simulador dos swing trades: (1) as operacoes de um setup, uma por sinal, com entrada na abertura do dia seguinte e saida por stop, alvo ou tempo;
(2) o livro de swing com capital, tamanho por risco, teto por nome e numero maximo de posicoes, marcado a mercado todo dia.

REGRAS DE SAIDA (pre-registro): stop e alvo em multiplos do ATR de 14 pregoes do dia do sinal, a partir do preco de entrada. Stop a mercado: se a
abertura de um dia ja esta abaixo do stop, sai na abertura (gap contra, perda maior que a planejada); se a abertura ja esta acima do alvo, sai na abertura;
stop e alvo na mesma barra: vale o stop. Tempo: fechamento do pregao `prazo` (o dia da entrada e o 1o). Dia de dado ruim na janela descarta a operacao.

TAMANHO: quantidade = risco em R$ / (distancia do stop em R$ por acao, em preco REAL), lote de 100 ate R$ 30 e unidade acima; teto por nome; maximo de posicoes;
exposicao bruta <= limite. Custos reais por ordem (`custos.custo_ordem`) nos dois lados.
"""
import numpy as np
import pandas as pd

from quant import custos as cst

from quant.swing import tamanho
from quant.swing.tamanho import CAPITAL, EXPO_MAX, LOTE, MAX_POSICOES, PRECO_MAX_LOTE, RISCO, TETO_NOME


def operacoes(p, sig, stop_atr, alvo_atr, prazo, atr):
    """DataFrame com uma linha por operacao valida. Precos em escala AJUSTADA; `escala_real` converte para o preco da epoca."""
    D = len(p.datas)
    ii, jj = np.nonzero(sig)
    ok = ii + 1 < D
    ii, jj = ii[ok], jj[ok]
    K = int(prazo)
    i0 = ii + 1
    dias = i0[:, None] + np.arange(K)[None, :]
    dentro = dias < D
    dc = np.minimum(dias, D - 1)
    J = jj[:, None]
    Ow, Hw, Lw, Cw = p.O[dc, J], p.H[dc, J], p.L[dc, J], p.C[dc, J]
    ruim = p.ruim[dc, J]
    entrada = Ow[:, 0]
    a = atr[ii, jj]
    stop = entrada - stop_atr * a
    alvo = entrada + (alvo_atr * a if alvo_atr else np.inf)
    k = np.arange(K)[None, :]
    gap_stop = (Ow <= stop[:, None]) & (k >= 1)
    gap_alvo = (Ow >= alvo[:, None]) & (k >= 1)
    hit_stop = Lw <= stop[:, None]
    hit_alvo = Hw >= alvo[:, None]
    ev = np.zeros(Ow.shape, dtype=np.int8)
    ev[hit_alvo] = 4
    ev[hit_stop] = 3
    ev[gap_alvo] = 2
    ev[gap_stop] = 1
    tem = (ev > 0).any(axis=1)
    primeiro = np.argmax(ev > 0, axis=1)
    k_saida = np.where(tem, primeiro, K - 1)
    evento = np.where(tem, ev[np.arange(len(ev)), primeiro], 0)
    o_k = Ow[np.arange(len(ev)), k_saida]
    c_k = Cw[np.arange(len(ev)), k_saida]
    saida = np.select([evento == 1, evento == 2, evento == 3, evento == 4], [o_k, o_k, stop, alvo], default=c_k)
    # validade: janela completa ate a saida, sem NaN e sem dia ruim
    ate = k <= k_saida[:, None]
    nan_na_janela = (~np.isfinite(Ow) | ~np.isfinite(Hw) | ~np.isfinite(Lw) | ~np.isfinite(Cw)) & ate
    fora = (~dentro) & ate
    valido = ~(nan_na_janela.any(axis=1) | fora.any(axis=1) | (ruim & ate).any(axis=1)) & np.isfinite(a) & (a > 0) & np.isfinite(entrada) & (entrada > 0)
    nomes = np.array(["tempo", "gap_stop", "gap_alvo", "stop", "alvo"])
    i0c = np.minimum(i0, D - 1)
    cru = p.preco_cru[i0c, jj]
    escala_real = np.where(np.isfinite(cru) & np.isfinite(p.C[i0c, jj]), cru / p.C[i0c, jj], np.nan)
    df = pd.DataFrame({"i_sinal": ii, "j": jj, "i_entrada": i0, "i_saida": i0 + k_saida, "entrada": entrada, "saida": saida, "stop": stop,
                       "alvo": np.where(np.isfinite(alvo), alvo, np.nan), "atr": a, "evento": nomes[evento], "pregoes": k_saida + 1,
                       "escala_real": escala_real, "adtv": p.adtv[ii, jj], "ticker": [p.tickers[x] for x in jj]})
    df = df[valido & np.isfinite(escala_real)].copy()
    df["ret_bruto"] = df["saida"] / df["entrada"] - 1.0
    df["data_sinal"] = p.datas[df["i_sinal"].to_numpy()]
    df["data_entrada"] = p.datas[df["i_entrada"].to_numpy()]
    df["data_saida"] = p.datas[np.minimum(df["i_saida"].to_numpy(), D - 1)]
    return df.sort_values(["i_entrada", "adtv"], ascending=[True, False]).reset_index(drop=True)


FAIXAS_LEVES = ((100e6, 0.0005), (20e6, 0.0025), (5e6, 0.0040), (0.0, 0.0080))   # SENSIBILIDADE (nao pre-registrada): papel de giro > R$ 100 mi a 5 bps


def _custo(valor, adtv, preco_real, faixas=None):
    kw = {"faixas": faixas} if faixas else {}
    return cst.custo_ordem(valor, adtv, fracionario=bool(preco_real > PRECO_MAX_LOTE), **kw)["total"]


def livro(p, ops, ini, fim, capital=CAPITAL, risco=RISCO, teto_nome=TETO_NOME, max_pos=MAX_POSICOES, expo_max=EXPO_MAX, faixas=None):
    """Simula o livro de swing de `ini` a `fim` (datas). Entra so quem tem i_entrada no periodo; saidas podem passar do fim e nao entram no patrimonio.

    Devolve dict(equity Series diaria, operacoes DataFrame das tomadas, sinais, tomadas)."""
    D = len(p.datas)
    d0 = int(np.searchsorted(p.datas.values, np.datetime64(pd.Timestamp(ini))))
    d1 = int(np.searchsorted(p.datas.values, np.datetime64(pd.Timestamp(fim)), side="right")) - 1
    sub = ops[(ops["i_entrada"] >= d0) & (ops["i_entrada"] <= d1)]
    por_dia = {k: g for k, g in sub.groupby("i_entrada")}
    cash, eq_prev = float(capital), float(capital)
    abertas, tomadas = [], []
    eq = np.full(d1 - d0 + 1, np.nan)
    giro = custo_total = 0.0
    expo_dias = []
    for d in range(d0, d1 + 1):
        cash *= 1.0 + float(p.cdi[d])
        # entradas (abertura de d), por prioridade de giro
        g = por_dia.get(d)
        if g is not None:
            valor_aberto = sum(x["notional"] * p.C[d - 1, x["j"]] / x["entrada"] for x in abertas) if d > 0 else 0.0
            for r in g.itertuples():
                if len(abertas) >= max_pos:
                    break
                preco_real = r.entrada * r.escala_real
                dist_real = (r.entrada - r.stop) * r.escala_real
                if dist_real <= 0:
                    continue
                qtd, valor = tamanho.quantidade(eq_prev, preco_real, dist_real, risco, teto_nome)
                if qtd <= 0 or valor <= 0:
                    continue
                if not tamanho.cabe(valor, valor_aberto, eq_prev, len(abertas), cash, expo_max, max_pos):
                    continue
                c_in = _custo(valor, r.adtv, preco_real, faixas)
                cash -= valor + c_in
                valor_aberto += valor
                giro += valor
                custo_total += c_in
                abertas.append({"j": r.j, "notional": valor, "entrada": r.entrada, "i_saida": r.i_saida, "saida": r.saida, "adtv": r.adtv,
                                "preco_real": preco_real, "risco_rs": qtd * dist_real, "c_in": c_in, "ticker": r.ticker, "evento": r.evento,
                                "data_entrada": r.data_entrada, "i_entrada": d, "qtd": qtd, "pregoes": r.pregoes})
        # saidas programadas para d (inclusive quem entrou hoje)
        resto = []
        for x in abertas:
            if x["i_saida"] == d:
                v_saida = x["notional"] * x["saida"] / x["entrada"]
                c_out = _custo(v_saida, x["adtv"], x["preco_real"], faixas)
                cash += v_saida - c_out
                giro += v_saida
                custo_total += c_out
                liquido = v_saida - x["notional"] - x["c_in"] - c_out
                tomadas.append({**{k: x[k] for k in ("ticker", "evento", "data_entrada", "qtd", "pregoes", "risco_rs")}, "notional": x["notional"],
                                "data_saida": p.datas[d], "resultado_rs": liquido, "resultado_pct": liquido / x["notional"],
                                "r_multiplo": liquido / x["risco_rs"] if x["risco_rs"] > 0 else np.nan, "ret_bruto": x["saida"] / x["entrada"] - 1.0,
                                "custo_rs": x["c_in"] + c_out})
            else:
                resto.append(x)
        abertas = resto
        pos_val = sum(x["notional"] * p.C[d, x["j"]] / x["entrada"] for x in abertas)
        pos_val = pos_val if np.isfinite(pos_val) else sum(x["notional"] for x in abertas)
        eq[d - d0] = cash + pos_val
        eq_prev = eq[d - d0]
        expo_dias.append(pos_val / eq_prev if eq_prev else 0.0)
    serie = pd.Series(eq, index=p.datas[d0:d1 + 1])
    t = pd.DataFrame(tomadas)
    return {"equity": serie, "operacoes": t, "sinais": int(len(sub)), "tomadas": int(len(t)), "giro_rs": giro, "custo_rs": custo_total,
            "exposicao_media": float(np.mean(expo_dias)) if expo_dias else 0.0}


def metricas(res, cdi, bench, dias_ano=252):
    """Metricas liquidas do livro. `cdi`, `bench`: Series diarias (fracao e nivel) alinhaveis ao indice do patrimonio."""
    e = res["equity"]
    t = res["operacoes"]
    r = e.pct_change().fillna(0.0)
    c = pd.Series(cdi, dtype=float).reindex(e.index).fillna(0.0)
    ex = r - c
    n = len(e)
    anos = n / dias_ano
    ret_aa = float((e.iloc[-1] / e.iloc[0]) ** (1 / anos) - 1) if anos > 0 and e.iloc[0] > 0 else np.nan
    # a curva comeca no 1o dia: o retorno do 1o dia entra como diferenca para o capital inicial
    cap0 = e.iloc[0] / (1.0 + r.iloc[0]) if r.iloc[0] != -1 else e.iloc[0]
    cdi_aa = float((1 + c).prod() ** (1 / anos) - 1) if anos > 0 else np.nan
    b = pd.Series(bench, dtype=float).reindex(e.index).ffill()
    bench_aa = float((b.iloc[-1] / b.iloc[0]) ** (1 / anos) - 1) if b.notna().all() and b.iloc[0] > 0 and anos > 0 else np.nan
    curva = e / e.cummax()
    mensal = (1 + ex).groupby([e.index.year, e.index.month]).prod() - 1
    por_ano = (1 + r).groupby(e.index.year).prod() - (1 + c).groupby(e.index.year).prod()
    sr = float(ex.mean() / ex.std(ddof=1) * np.sqrt(dias_ano)) if ex.std(ddof=1) > 0 else np.nan
    m = {"dias": int(n), "retorno_aa": ret_aa, "cdi_aa": cdi_aa, "excesso_aa": ret_aa - cdi_aa if np.isfinite(ret_aa) else np.nan, "ibov_aa": bench_aa,
         "excesso_ibov_aa": ret_aa - bench_aa if np.isfinite(bench_aa) and np.isfinite(ret_aa) else np.nan,
         "vol_aa": float(ex.std(ddof=1) * np.sqrt(dias_ano)), "sharpe": sr, "queda_maxima": float(1 - curva.min()),
         "sharpe_mensal": float(mensal.mean() / mensal.std(ddof=1)) if len(mensal) > 2 and mensal.std(ddof=1) > 0 else np.nan, "n_meses": int(len(mensal)),
         "anos_positivos": int((por_ano > 0).sum()), "n_anos": int(len(por_ano)), "excesso_por_ano": {int(k): float(v) for k, v in por_ano.items()},
         "exposicao_media": res["exposicao_media"], "sinais": res["sinais"], "operacoes": int(res["tomadas"]),
         "operacoes_por_ano": float(res["tomadas"] / anos) if anos > 0 else np.nan,
         "giro_aa": float(res["giro_rs"] / e.mean() / anos) if anos > 0 else np.nan, "custo_aa": float(res["custo_rs"] / e.mean() / anos) if anos > 0 else np.nan}
    if len(t):
        gan, per = t[t["resultado_rs"] > 0], t[t["resultado_rs"] <= 0]
        m.update({"expectativa_pct": float(t["resultado_pct"].mean()), "expectativa_r": float(t["r_multiplo"].mean()), "acerto": float(len(gan) / len(t)),
                  "payoff": float(gan["resultado_pct"].mean() / abs(per["resultado_pct"].mean())) if len(gan) and len(per) and per["resultado_pct"].mean() != 0 else np.nan,
                  "ret_bruto_medio": float(t["ret_bruto"].mean()), "pregoes_medios": float(t["pregoes"].mean()),
                  "saidas": {k: int(v) for k, v in t["evento"].value_counts().items()}})
    else:
        m.update({"expectativa_pct": np.nan, "expectativa_r": np.nan, "acerto": np.nan, "payoff": np.nan, "ret_bruto_medio": np.nan, "pregoes_medios": np.nan, "saidas": {}})
    return m

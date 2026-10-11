"""
Pesquisa das vertentes V2 (dividendo sintetico) e V3 (travas com BOVA11): grades PRE-REGISTRADAS em
quant/saida/pesquisa5/opcoes/HIPOTESES_VERTENTES.md, so descoberta (2012-2019) e validacao (2020-2023). A prova 2024-2026 nao entra:
estas familias ja tiveram a prova aberta em turnos anteriores.

  python -m quant.opcoes.vertentes_pesquisa        grava resultados_vertentes.json e acrescenta as tentativas em tentativas.jsonl
"""
import json
import os

import numpy as np
import pandas as pd

from quant.opcoes import assimetrias_pesquisa as A
from quant.opcoes import custos as C
from quant.opcoes import dados, manejo, metricas, motor
from quant.opcoes.base import DIR_OPC
from quant.opcoes.pesquisa import CESTA, PERIODOS

FEE = C.FEE_PREMIO
ARQ = os.path.join(DIR_OPC, "resultados_vertentes.json")
FAM_V2 = "V2_dividendo_sintetico"
FAM_V3 = "V3_travas_bova"
MANEJOS = ("M0", "M1", "M2")
FILTROS = ("F0", "F1", "F2")
PERC_VI_ALTA = 0.60
N_V2 = 54                   # configuracoes da familia V2 (HIPOTESES_VERTENTES.md): 6 selecoes x 3 manejos x 3 filtros
N_V3 = 76                   # V3: 72 de credito (8 selecoes x 3 manejos x 3 filtros) + 4 de debito
FRACAO_EM_RISCO_V3 = 0.10   # dimensionamento das travas na pesquisa: 10% do patrimonio em risco maximo por mes (ver HIPOTESES_VERTENTES.md, correcoes)
ALVO = 0.20                 # recomprar com 20% do credito (80% capturado)
STOP_UNICA = 3.0
STOP_TRAVA = 2.0
FASES_V2 = ("descoberta", "validacao")
FASES_V3 = ("validacao",)
REFERENCIA_V2 = {"put": "put delta=0.20 M1 F0 cesta", "call": "call delta=0.30 M1 F0 cesta"}
REFERENCIA_V3 = {"alta": "trava alta credito delta=0.20 largura=3% M2 F0", "baixa": "trava baixa credito delta=0.20 largura=3% M2 F0"}


# ---------------------------------------------------------------------------------------------------------------- filtros
def filtro_mascara(df, filtro, lado):
    """F0 nada; F1 percentil da VI >= 0,60; F2 direcao (put: acima da media de 200; call: abaixo dela)."""
    if filtro == "F0":
        return np.ones(len(df), dtype=bool)
    if filtro == "F1":
        return (df["perc_vi"].values >= PERC_VI_ALTA) & np.isfinite(df["perc_vi"].values)
    acima = df["acima_mm200"].values
    ok = np.isfinite(acima)
    return ok & ((acima == 1.0) if lado == "put" else (acima == 0.0))


# ---------------------------------------------------------------------------------------------------------------- selecao
def selecionar_unica(cad, grupos, tipo, delta):
    el = motor.liquidas(cad[cad["grupo"].isin(grupos)], tipo)
    return motor.mais_perto_do_delta(el, delta).copy()


def selecionar_trava(cad, tipo, delta, largura, grupos=("BOVA11",)):
    """Vende o `tipo` de |delta| mais perto de `delta` e compra a liquida mais perto de `largura` x S_E mais OTM (put: abaixo; call: acima)."""
    el = motor.liquidas(cad[cad["grupo"].isin(grupos)], tipo)
    curta = motor.mais_perto_do_delta(el, delta)
    long_por = {k: g for k, g in el.groupby(["grupo", "T"])}
    lin = []
    for c in curta.itertuples(index=False):
        g = long_por.get((c.grupo, c.T))
        if g is None:
            continue
        g = g[g["ativo"] == c.ativo]
        g = g[g["exercicio"] < c.exercicio] if tipo == "P" else g[g["exercicio"] > c.exercicio]
        if g.empty:
            continue
        alvo_k = c.exercicio - largura * c.S_E if tipo == "P" else c.exercicio + largura * c.S_E
        g = g.assign(dk=(g["exercicio"] - alvo_k).abs())
        l = g.sort_values(["dk", "negocios"], ascending=[True, False]).iloc[0]
        if l["dk"] > 0.5 * largura * c.S_E:
            continue
        lin.append({"grupo": c.grupo, "ativo": c.ativo, "E": c.E, "T": c.T, "cdi_ciclo": c.cdi_ciclo, "S_E": c.S_E, "S_T": c.S_T,
                    "venc": c.vencimento, "K_curta": c.exercicio, "K_longa": l["exercicio"], "bid_c": c.oferta_compra, "ask_l": l["oferta_venda"],
                    "pay_c": c.payoff_T, "pay_l": l["payoff_T"], "KT_c": c.K_T, "KT_l": l["K_T"], "delta": c.delta,
                    "cod_curta": c.codigo, "cod_longa": l["codigo"], "perc_vi": c.perc_vi, "acima_mm200": c.acima_mm200, "negocios_c": c.negocios})
    return pd.DataFrame(lin)


def pares_de_caminho(selecoes):
    pares = set()
    for s in selecoes:
        if s is None or len(s) == 0:
            continue
        if "cod_curta" in s.columns:
            pares.update(zip(s["cod_curta"], s["venc"]))
            pares.update(zip(s["cod_longa"], s["venc"]))
        else:
            pares.update(zip(s["codigo"], s["vencimento"]))
    return pares


# ---------------------------------------------------------------------------------------------------------------- simulacao
def simular_unica(sel, cam, manejo_id, lado):
    """lado: 'put' (capital = strike) ou 'call' (resultado sobre o preco do papel). Uma linha por operacao."""
    lin = []
    for r in sel.itertuples(index=False):
        credito = r.oferta_compra * (1.0 - FEE)
        saida = None
        if manejo_id != "M0":
            saida = manejo.saida_perna_unica(cam, r.codigo, r.vencimento, r.E, credito, ALVO, STOP_UNICA if manejo_id == "M2" else None)
        exercida = r.payoff_T > 0
        taxa = C.FEE_EXERC * (r.K_T + r.S_T) if (saida is None and exercida) else 0.0
        pnl, motivo = manejo.pnl_com_saida(credito, r.E, r.T, saida, r.payoff_T, taxa)
        lin.append({"grupo": r.grupo, "ativo": r.ativo, "E": r.E, "T": r.T, "K": r.exercicio, "S_E": r.S_E, "delta": r.delta, "credito": credito,
                    "pnl": pnl, "motivo": motivo, "exercida": bool(exercida and saida is None), "perc_vi": r.perc_vi, "acima_mm200": r.acima_mm200,
                    "ex": pnl / (r.exercicio if lado == "put" else r.S_E), "tr": r.tr, "cdi_ciclo": r.cdi_ciclo})
    return pd.DataFrame(lin)


def simular_trava(sel, cam, manejo_id):
    lin = []
    for r in sel.itertuples(index=False):
        credito = r.bid_c * (1.0 - FEE) - r.ask_l * (1.0 + FEE)
        larg = abs(r.K_curta - r.K_longa)
        if credito <= 0 or credito >= larg:
            continue
        saida = None
        if manejo_id != "M0":
            saida = manejo.saida_trava(cam, r.cod_curta, r.cod_longa, r.venc, r.E, credito, ALVO, STOP_TRAVA if manejo_id == "M2" else None)
        pay = r.pay_c - r.pay_l
        taxa = 0.0
        if saida is None:
            taxa = (C.FEE_EXERC * (r.KT_c + r.S_T) if r.pay_c > 0 else 0.0) + (C.FEE_EXERC * (r.KT_l + r.S_T) if r.pay_l > 0 else 0.0)
        pnl, motivo = manejo.pnl_com_saida(credito, r.E, r.T, saida, pay, taxa)
        risco = larg - credito
        lin.append({"grupo": r.grupo, "ativo": r.ativo, "E": r.E, "T": r.T, "credito": credito, "largura": larg, "risco": risco, "pnl": pnl,
                    "motivo": motivo, "perda_total": bool(saida is None and pay >= larg - 1e-9), "perc_vi": r.perc_vi,
                    "acima_mm200": r.acima_mm200, "ex": pnl / risco, "S_E": r.S_E, "delta": r.delta, "cdi_ciclo": r.cdi_ciclo})
    return pd.DataFrame(lin)


# ---------------------------------------------------------------------------------------------------------------- metricas
def _sequencia_perdas(ex):
    mx = atual = 0
    for x in ex:
        atual = atual + 1 if x < -1e-12 else 0
        mx = max(mx, atual)
    return int(mx)


def metricas_serie(s, per, n_tent):
    a, b = PERIODOS[per]
    if len(s) < 3:
        return {"n_ciclos": int(len(s)), "n_ops": int(s["n_ops"].sum()) if len(s) else 0}
    com_op = (s["n_ops"] > 0).values
    anos = s["du"].sum() / 252.0 if "du" in s else None
    m = metricas.calcular(s["ex"].values, s["cdi"].values, com_op, s["E"].iloc[0], s["T"].iloc[-1], n_tentativas=n_tent, anos=anos)
    ex = s["ex"].values
    m["maior_sequencia_de_perdas_meses"] = _sequencia_perdas(ex)
    m["pior_excesso_mes_pct"] = round(float(ex.min() * 100), 2)
    m20 = s[(s["T"].dt.year == 2020) & (s["T"].dt.month == 3)]
    m["ciclo_mar2020_excesso_pct"] = round(float(m20["ex"].iloc[0] * 100), 2) if len(m20) else None
    m["meses_com_operacao"] = int(com_op.sum())
    keep = ~((s["T"].dt.year == 2020) & (s["T"].dt.month == 3)).values
    if keep.sum() >= 3 and keep.sum() < len(s):
        m2 = metricas.calcular(ex[keep], s["cdi"].values[keep], com_op[keep], s["E"].iloc[0], s["T"].iloc[-1], anos=(anos * keep.sum() / len(s)) if anos else None)
        m["excesso_sem_mar2020_anual_pct"] = m2.get("excesso_anual_pct")
        m["sharpe_sem_mar2020"] = m2.get("sharpe")
    return m


def metades(s, per):
    """Excesso anual em 2020-2021 e em 2022-2023 (consistencia de uma validacao sem descoberta)."""
    out = []
    for ini, fim in (("2020-01-01", "2021-12-31"), ("2022-01-01", "2023-12-31")):
        sm = s[(s["T"] >= pd.Timestamp(ini)) & (s["T"] <= pd.Timestamp(fim))]
        out.append(float(metricas_serie(sm, per, None).get("excesso_anual_pct", -99.0)) if len(sm) >= 3 else -99.0)
    return out

def passa_fase(m, estrito_metades=None):
    if not m or "sharpe" not in m:
        return False
    ok = m["excesso_anual_pct"] > 0 and m["sharpe"] > 0.3 and (m.get("meses_com_operacao", 0) >= 24 or m["n_ops"] >= 30)
    if estrito_metades is not None:
        ok = ok and all(x > 0 for x in estrito_metades)
    return bool(ok)


def serie_bova(cic, per):
    """Excesso mensal do BOVA11 (Ibovespa retorno total menos 0,10% ao ano) sobre o CDI, nos mesmos ciclos."""
    a, b = PERIODOS[per]
    ib = dados.ibov()
    c = cic[(cic["T"] >= pd.Timestamp(a)) & (cic["T"] <= pd.Timestamp(b))].copy()
    c["ex"] = [ib.get(t, np.nan) / ib.get(e, np.nan) - 1.0 - 0.001 * du / 252.0 - cdi for e, t, du, cdi in zip(c["E"], c["T"], c["du"], c["cdi_ciclo"])]
    c["cdi"] = c["cdi_ciclo"]
    c["n_ops"] = 1
    return c.dropna(subset=["ex"]).reset_index(drop=True)


def cauda_bova(cic, per):
    s = serie_bova(cic, per)
    m = metricas_serie(s, per, None)
    return {k: m.get(k) for k in ("excesso_anual_pct", "sharpe", "queda_maxima_pct", "pior_mes_pct", "ciclo_mar2020_excesso_pct", "maior_sequencia_de_perdas_meses")}


def _resumo_ops(tr):
    if len(tr) == 0:
        return {}
    return {"pct_alvo_80": round(float((tr["motivo"] == "alvo").mean() * 100), 1), "pct_stop": round(float((tr["motivo"] == "stop").mean() * 100), 1),
            "pct_ate_vencimento": round(float((tr["motivo"] == "vencimento").mean() * 100), 1),
            "pior_operacao_pct_do_capital": round(float(tr["ex"].min() * 100), 1)}


def avaliar_serie(tr, cad, cic, grupos, per, n_tent, coluna="ex", escala=1.0):
    """Serie por ciclo e metricas. `escala` multiplica o excesso por ciclo (travas: fracao do patrimonio em risco maximo)."""
    a, b = PERIODOS[per]
    s = motor.serie_por_ciclo(tr, cad, cic, grupos, a, b, coluna=coluna)
    if escala != 1.0:
        s["ex"] = s["ex"] * escala
    return s, metricas_serie(s, per, n_tent)


# ---------------------------------------------------------------------------------------------------------------- V2
def rodar_v2(cad, cic, cam, sel):
    """sel: dicionario de selecoes. Devolve lista de resultados (uma por configuracao), com D e V."""
    linhas = []
    for (univ, tipo, delta), s in sel.items():
        lado = "put" if tipo == "P" else "call"
        grupos = CESTA if univ == "cesta" else ["BOVA11"]
        fases = FASES_V2 if univ == "cesta" else FASES_V3
        for mj in MANEJOS:
            tr = simular_unica(s, cam, mj, lado)
            for f in FILTROS:
                nome = "cesta" if univ == "cesta" else "BOVA11"
                cfg = f"{nome} {lado} delta={delta:.2f} {mj} {f}"
                if lado == "put":
                    t = tr[filtro_mascara(tr, f, "put")] if len(tr) else tr
                    row = {"config": cfg, "familia": FAM_V2, "universo": nome, "estrutura": "put coberta por caixa", "delta": delta, "manejo": mj, "filtro": f, "fases": {}}
                    for per in fases:
                        a, b = PERIODOS[per]
                        tp = t[(t["T"] >= pd.Timestamp(a)) & (t["T"] <= pd.Timestamp(b))]
                        s_, m = avaliar_serie(tp, cad, cic, grupos, per, N_V2)
                        m.update(_resumo_ops(tp))
                        if univ != "cesta":
                            m["excesso_anual_metade_1_pct"], m["excesso_anual_metade_2_pct"] = metades(s_, per)
                        row["fases"][per] = m
                else:
                    row = _call_coberta(cad, cic, grupos, tr, delta, mj, f, fases, cfg)
                linhas.append(row)
    return linhas


def _call_coberta(cad, cic, grupos, tr, delta, mj, f, fases, cfg):
    base = (cad[cad["grupo"].isin(grupos) & cad["escolhido"] & cad["S_E"].notna() & cad["tr"].notna()]
            [["grupo", "ativo", "E", "T", "S_E", "tr", "cdi_ciclo"]].drop_duplicates(["grupo", "T"]).copy())
    base["ex_acao"] = base["tr"] - base["cdi_ciclo"]
    t = tr[filtro_mascara(tr, f, "call")] if len(tr) else tr
    add = t.groupby(["grupo", "T"])["pnl"].sum().rename("pnl_call") if len(t) else pd.Series(dtype=float)
    base = base.merge(add.reset_index(), on=["grupo", "T"], how="left")
    base["ex_cob"] = base["ex_acao"] + base["pnl_call"].fillna(0.0) / base["S_E"]
    row = {"config": cfg, "familia": FAM_V2, "universo": "cesta", "estrutura": "call coberta", "delta": delta, "manejo": mj, "filtro": f, "fases": {}}
    for per in fases:
        a, b = PERIODOS[per]
        bp = base[(base["T"] >= pd.Timestamp(a)) & (base["T"] <= pd.Timestamp(b))]
        s, m = avaliar_serie(bp, cad, cic, grupos, per, N_V2, coluna="ex_cob")
        s0, m0 = avaliar_serie(bp, cad, cic, grupos, per, None, coluna="ex_acao")
        tp = t[(t["T"] >= pd.Timestamp(a)) & (t["T"] <= pd.Timestamp(b))] if len(t) else t
        m.update(_resumo_ops(tp))
        m["n_ops"] = int(len(tp))
        m["papel_sozinho_sharpe"] = m0.get("sharpe")
        m["papel_sozinho_excesso_anual_pct"] = m0.get("excesso_anual_pct")
        m["papel_sozinho_queda_maxima_pct"] = m0.get("queda_maxima_pct")
        m["papel_sozinho_pior_mes_pct"] = m0.get("pior_mes_pct")
        m["meses_com_operacao"] = int(len(tp.groupby("T"))) if len(tp) else 0
        row["fases"][per] = m
    return row


# ---------------------------------------------------------------------------------------------------------------- V3 credito
def rodar_v3_credito(cad, cic, cam, sel):
    linhas = []
    for (tipo, delta, larg), s in sel.items():
        lado = "put" if tipo == "P" else "call"
        for mj in MANEJOS:
            tr = simular_trava(s, cam, mj)
            for f in FILTROS:
                cfg = f"trava {'alta' if tipo == 'P' else 'baixa'} credito delta={delta:.2f} largura={int(larg * 100)}% {mj} {f}"
                t = tr[filtro_mascara(tr, f, lado)] if len(tr) else tr
                row = {"config": cfg, "familia": FAM_V3, "universo": "BOVA11", "estrutura": "trava de baixa com call a credito" if tipo == "C" else "trava de alta com put a credito",
                       "delta": delta, "largura_pct": int(larg * 100), "manejo": mj, "filtro": f, "fases": {}}
                for per in FASES_V3:
                    a, b = PERIODOS[per]
                    tp = t[(t["T"] >= pd.Timestamp(a)) & (t["T"] <= pd.Timestamp(b))]
                    s_, m = avaliar_serie(tp, cad, cic, ["BOVA11"], per, N_V3, escala=FRACAO_EM_RISCO_V3)
                    m["fracao_do_patrimonio_em_risco_pct"] = int(FRACAO_EM_RISCO_V3 * 100)
                    m.update(_resumo_ops(tp))
                    if len(tp):
                        m["pct_perda_total_do_risco"] = round(float(tp["perda_total"].mean() * 100), 1)
                    m["excesso_anual_metade_1_pct"], m["excesso_anual_metade_2_pct"] = metades(s_, per)
                    row["fases"][per] = m
                linhas.append(row)
    return linhas


# ---------------------------------------------------------------------------------------------------------------- V3 debito
def _gatilhos_bova():
    ib = dados.ibov()
    ib = ib[ib.index >= "2019-01-01"]
    m50, m200 = ib.rolling(50).mean(), ib.rolling(200).mean()
    ant = ib.shift(1)
    return {
        "alta_T1": ib > ant.rolling(55).max(),
        "alta_T2": (ib > m200) & (ib.shift(1) <= m200.shift(1)) & (m50 > m50.shift(5)),
        "baixa_T1": ib < ant.rolling(55).min(),
        "baixa_T2": (ib < m200) & (ib.shift(1) >= m200.shift(1)) & (m50 < m50.shift(5)),
    }


def _eventos_gatilho(sinal, separacao=21):
    dias = list(sinal.index)
    out, ult = [], None
    for i, (d, v) in enumerate(sinal.items()):
        if v and (ult is None or i - ult >= separacao):
            out.append(d)
            ult = i
    return [d for d in out if pd.Timestamp("2020-01-01") <= d <= pd.Timestamp("2023-12-31")]


def avaliar_debito(lado, dias_entrada, tab, fech, ib):
    """lado 'alta': compra call ~ATM e vende a ~6% acima; 'baixa': compra put ~ATM e vende a ~6% abaixo. Segura ate o vencimento (15 a 30 pregoes).
    Retorno por R$ 1 de debito, menos o CDI do prazo. BOVA11 sem tabela de proventos: o strike de liquidacao NAO e ajustado (limite declarado)."""
    tp = "C" if lado == "alta" else "P"
    t = tab[(tab["ativo"] == "BOVA11") & (tab["tipo"] == tp) & tab["boa"] & (tab["negocios"] >= 30) & tab["du"].between(15, 30)]
    lin = []
    for d in dias_entrada:
        x = t[t["dia"] == d]
        if x.empty:
            continue
        x = x.assign(dexp=(x["du"] - 21).abs())
        x = x[x["dexp"] == x["dexp"].min()]
        x = x[x["vencimento"] == x["vencimento"].min()]
        s0 = float(x["S"].iloc[0])
        venc = x["vencimento"].iloc[0]
        x = x.assign(dk=(x["exercicio"] / s0 - 1.0).abs())
        longa = x[x["dk"] <= 0.03].sort_values(["dk", "negocios"], ascending=[True, False])
        if longa.empty:
            continue
        L = longa.iloc[0]
        alvo = 1.06 if lado == "alta" else 0.94
        cur = x.assign(d2=(x["exercicio"] / s0 - alvo).abs())
        cur = cur[(cur["d2"] <= 0.03) & ((cur["exercicio"] > L["exercicio"]) if lado == "alta" else (cur["exercicio"] < L["exercicio"]))]
        if cur.empty:
            continue
        S_ = cur.sort_values(["d2", "negocios"], ascending=[True, False]).iloc[0]
        if venc not in fech.index or d not in ib.index or venc not in ib.index:
            continue
        st = float(fech.loc[venc])
        pay_l = max(st - L["exercicio"], 0.0) if lado == "alta" else max(L["exercicio"] - st, 0.0)
        pay_s = max(st - S_["exercicio"], 0.0) if lado == "alta" else max(S_["exercicio"] - st, 0.0)
        deb = float(L["ask"]) * (1 + FEE) - float(S_["bid"]) * (1 - FEE)
        larg = abs(S_["exercicio"] - L["exercicio"])
        if not (deb > 0 and deb < larg):
            continue
        cdi_fator = manejo.fator_cdi(d, venc)
        ret = (pay_l - pay_s) * (1 - FEE) / deb - cdi_fator          # retorno do debito empenhado menos o CDI do prazo
        papel = ib[venc] / ib[d] - 1.0 - 0.001 * float(L["du"]) / 252.0 - (cdi_fator - 1.0)
        lin.append({"dia": d, "venc": venc, "ret_trava": ret, "ret_papel": papel, "debito": deb, "largura": larg})
    return pd.DataFrame(lin)


def _resumo_debito(df, col):
    x = df[col].dropna() if len(df) else pd.Series(dtype=float)
    if len(x) == 0:
        return {"n": 0}
    sd = x.std(ddof=1) if len(x) > 1 else np.nan
    return {"n": int(len(x)), "media_pct": round(float(x.mean() * 100), 2), "desvio_pct": round(float(sd * 100), 2) if sd == sd else None,
            "pct_positivos": round(float((x > 0).mean() * 100), 1), "pior_pct": round(float(x.min() * 100), 1),
            "media_sobre_desvio": round(float(x.mean() / sd), 3) if sd == sd and sd > 0 else None}


def rodar_v3_debito():
    from quant.opcoes import diario
    tab = diario.carregar()
    tab = tab[tab["ativo"] == "BOVA11"]
    fech = dados.fechamentos()["BOVA11"].dropna()
    ib = dados.ibov()
    gat = _gatilhos_bova()
    amostra_dias = list(ib[(ib.index >= "2020-01-01") & (ib.index <= "2023-12-31")].index[::5])
    out = []
    for lado, gatilhos in (("alta", ("alta_T1", "alta_T2")), ("baixa", ("baixa_T1", "baixa_T2"))):
        base = avaliar_debito(lado, amostra_dias, tab, fech, ib)
        for g in gatilhos:
            ev = _eventos_gatilho(gat[g])
            av = avaliar_debito(lado, ev, tab, fech, ib)
            tr, pa = _resumo_debito(av, "ret_trava"), _resumo_debito(av, "ret_papel")
            ba = _resumo_debito(base, "ret_trava")
            passa = bool(tr.get("n", 0) >= 20 and (tr.get("media_pct") or -1) > 0 and (tr.get("media_sobre_desvio") or -9) > (pa.get("media_sobre_desvio") or 9))
            out.append({"config": f"trava {lado} debito gatilho {g[-2:]} (BOVA11)", "familia": FAM_V3, "universo": "BOVA11", "estrutura": f"trava de {lado} a debito",
                        "gatilho": g, "eventos_brutos": len(ev), "fases": {"validacao": {"trava": tr, "bova11_comprado": pa, "trava_em_qualquer_dia": ba, "passou": passa}}})
    return out


# ---------------------------------------------------------------------------------------------------------------- orquestracao
def _limpa(x):
    if isinstance(x, dict):
        return {k: _limpa(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_limpa(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if (x != x or x in (float("inf"), float("-inf"))) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def estresse_stop(cad, cic, cam, sel_bova):
    """Estresse do stop 3x na put de BOVA11 delta 0,20 (nao e configuracao da grade, nao entra no N): executa `atraso` pregoes com cotacao
    DEPOIS do gatilho, na oferta de venda desse dia. Mostra o quanto o resultado depende de sair no proprio fechamento do gatilho."""
    out = {}
    for atraso in (0, 1, 2):
        lin = []
        for r in sel_bova.itertuples(index=False):
            credito = r.oferta_compra * (1.0 - FEE)
            saida = manejo.saida_perna_unica(cam, r.codigo, r.vencimento, r.E, credito, ALVO, STOP_UNICA, atraso=atraso)
            taxa = C.FEE_EXERC * (r.K_T + r.S_T) if (saida is None and r.payoff_T > 0) else 0.0
            pnl, motivo = manejo.pnl_com_saida(credito, r.E, r.T, saida, r.payoff_T, taxa)
            lin.append({"grupo": r.grupo, "T": r.T, "E": r.E, "ex": pnl / r.exercicio, "motivo": motivo})
        tr = pd.DataFrame(lin)
        _, m = avaliar_serie(tr, cad, cic, ["BOVA11"], "validacao", N_V2)
        out[f"atraso_{atraso}_pregoes"] = {k: m.get(k) for k in ("excesso_anual_pct", "sharpe", "pior_mes_pct", "ciclo_mar2020_excesso_pct", "excesso_sem_mar2020_anual_pct")}
        x = tr[(tr["T"].dt.year == 2020) & (tr["T"].dt.month == 3)]
        out[f"atraso_{atraso}_pregoes"]["perda_mar2020_pct_do_strike"] = round(float(x["ex"].iloc[0] * 100), 2) if len(x) else None
    return out


def diagnostico_stop_acoes(sel, cam):
    """Nas puts de acoes da cesta (delta 0,20): das operacoes em que o stop de 3x disparou, quantas teriam terminado no lucro se seguradas, e o resultado medio
    com e sem o stop (R$ por opcao). Explica por que o stop piorou em acoes. Nao entra na grade."""
    t0 = simular_unica(sel, cam, "M0", "put")
    t2 = simular_unica(sel, cam, "M2", "put")
    m = t0[["grupo", "T", "pnl"]].merge(t2[["grupo", "T", "pnl", "motivo"]], on=["grupo", "T"], suffixes=("_seguro", "_stop"))
    st = m[m["motivo"] == "stop"]
    if len(st) == 0:
        return {}
    return {"operacoes": int(len(m)), "stops": int(len(st)), "pct_que_teria_dado_lucro_sem_stop": round(float((st["pnl_seguro"] > 0).mean() * 100), 1),
            "resultado_medio_com_stop_rs": round(float(st["pnl_stop"].mean()), 3), "resultado_medio_sem_stop_rs": round(float(st["pnl_seguro"].mean()), 3)}


def classificar_v2(linhas):
    """passou D e V (cesta); cobertura em call exige Sharpe acima do papel sozinho; BOVA11 so validacao."""
    for r in linhas:
        f = r["fases"]
        if r["universo"] == "cesta":
            ok = all(passa_fase(f.get(p, {})) for p in FASES_V2)
            if r["estrutura"] == "call coberta" and ok:
                ok = all((f[p].get("sharpe") or -9) > (f[p].get("papel_sozinho_sharpe") or 9) for p in FASES_V2)
        else:
            m = f.get("validacao", {})
            ok = passa_fase(m, estrito_metades=[m.get("excesso_anual_metade_1_pct", -99), m.get("excesso_anual_metade_2_pct", -99)])
        r["passou"] = bool(ok)


def classificar_v3(linhas):
    for r in linhas:
        if "gatilho" in r:
            r["passou"] = bool(r["fases"]["validacao"]["passou"])
            continue
        m = r["fases"]["validacao"]
        meta = [m.get("excesso_anual_metade_1_pct", -99), m.get("excesso_anual_metade_2_pct", -99)]
        r["passou"] = passa_fase(m, estrito_metades=meta)


def registrar_tentativas(linhas):
    """Acrescenta as linhas em tentativas.jsonl. FORCAR=True: a primeira execucao (com os defeitos descritos em HIPOTESES_VERTENTES.md,
    'Correcoes durante a execucao') deixou linhas antigas das mesmas configuracoes; o arquivo e so de acrescentar e vale a ultima."""
    metricas.FORCAR = True
    for r in linhas:
        for per, m in r["fases"].items():
            metricas.registrar(r["familia"], r["config"], per, {k: v for k, v in m.items() if not isinstance(v, dict)} if "trava" not in m else m["trava"],
                               nota="grade pre-registrada em HIPOTESES_VERTENTES.md; prova 2024-2026 nao usada; valem as linhas desta execucao (com correcoes)")


def rodar(gravar=True):
    cad, cic, pv = A.carregar_base()
    sel = {}
    for d in (0.20, 0.30):
        sel[("cesta", "P", d)] = selecionar_unica(cad, CESTA, "P", d)
        sel[("cesta", "C", d)] = selecionar_unica(cad, CESTA, "C", d)
        sel[("bova", "P", d)] = selecionar_unica(cad, ["BOVA11"], "P", d)
    tr_sel = {}
    for tipo in ("P", "C"):
        for d in (0.20, 0.30):
            for larg in (0.03, 0.06):
                tr_sel[(tipo, d, larg)] = selecionar_trava(cad, tipo, d, larg)
    cam = manejo.Caminhos(pares_de_caminho(list(sel.values()) + list(tr_sel.values())))
    v2 = rodar_v2(cad, cic, cam, sel)
    v3 = rodar_v3_credito(cad, cic, cam, tr_sel) + rodar_v3_debito()
    classificar_v2(v2)
    classificar_v3(v3)
    n2, n3 = len(v2), len(v3)
    assert n2 == N_V2 and n3 == N_V3, (n2, n3)
    out = {"gerado": pd.Timestamp.now().isoformat(timespec="seconds"), "v2": v2, "v3": v3, "n_v2": n2, "n_v3": n3,
           "estresse_stop_bova11": estresse_stop(cad, cic, cam, sel[("bova", "P", 0.20)]),
           "stop_em_acoes": diagnostico_stop_acoes(sel[("cesta", "P", 0.20)], cam),
           "bova11": {per: cauda_bova(cic, per) for per in ("descoberta", "validacao")} }
    out["resumo"] = resumo(v2, v3)
    out = _limpa(out)
    if gravar:
        registrar_tentativas(v2 + v3)
        with open(ARQ, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1, allow_nan=False)
    return out


def resumo(v2, v3):
    return {"v2_passaram": [r["config"] for r in v2 if r.get("passou")], "v3_passaram": [r["config"] for r in v3 if r.get("passou")],
            "v2_total": len(v2), "v3_total": len(v3)}


if __name__ == "__main__":
    r = rodar()
    print(json.dumps(r["resumo"], ensure_ascii=False, indent=1))

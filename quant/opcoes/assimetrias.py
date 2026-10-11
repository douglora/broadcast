"""
RANKING DIARIO DE ASSIMETRIAS em opcoes (bloco "assimetrias" do quant_opcoes.json).

Com a cadeia mais recente de TODOS os ativos com opcao liquida:
  por_ativo   leitura de volatilidade (implicita 30 dias contra realizada 20 e 60 pregoes, percentil no proprio ultimo ano),
              inclinacao (skew) da put, desvio da paridade put-call, proximo resultado (estimado), liquidez do dia
  ranking     as 15 melhores entradas de RISCO DEFINIDO (call e put fora do dinheiro de delta ~0,10 e ~0,25, call e put no dinheiro,
              trava de alta com calls, trava de baixa com puts, straddle), nos dois vencimentos mensais seguintes, a precos EXECUTAVEIS
              (compra na oferta de venda, vende na de compra do fechamento, emolumento de 0,05% por lado)
  arbitragens oportunidades de preco no fechamento (conversao, reversao, travas e borboletas), com aviso

COMO O RANKING E FEITO
  1. Filtro de liquidez de cada perna: 30+ negocios da serie no dia, ofertas dos dois lados e spread de ate 30% do ponto medio.
     Ativo entra no ranking se tem 6+ series assim e 1.000+ negocios de opcoes no dia.
  2. Valor esperado com a distribuicao HISTORICA dos retornos totais do proprio ativo no mesmo prazo (todas as janelas sobrepostas dos
     ultimos 10 anos) e, separado, com a mesma distribuicao REESCALADA para a volatilidade realizada de 60 pregoes de agora.
     valor_esperado_rs = pagamento esperado no vencimento menos o custo capitalizado pelo CDI do prazo (R$ por acao).
     vantagem_pct = valor_esperado_rs / custo. O ranking ordena pela MENOR das duas vantagens (a mais prudente).
  3. prob_lucro_implicita: probabilidade de lucro se o ativo seguir a volatilidade que a propria opcao embute (lognormal, juro = CDI).
     prob_lucro_historica: a mesma conta com os retornos historicos. Se a historica for bem maior que a implicita, o historico do ativo
     tem sido favoravel a essa estrutura -- que NAO e previsao e depende do periodo (10 anos de um ativo e pouca historia).
  4. Cada linha leva o veredito da FAMILIA na pesquisa (hipoteses A0 a A6): o ranking mostra a melhor entrada e diz se a historia
     da familia sustenta o criterio. Estrutura de familia reprovada aparece com o numero, e a carteira simulada nao a abre.

  ganho_sobre_perda: ganho maximo / perda maxima quando o ganho e limitado; quando e aberto, o ganho medio nos cenarios historicos de
  lucro dividido pela perda maxima. Colar nao entra: e protecao de uma posicao em acao (ver candidatas_hoje) e nao tem custo
  comparavel.
Nada aqui e recomendacao (Resolucao CVM 178): descreve estruturas e o que a historia mostrou.
"""
import json
import math
import os

import numpy as np
import pandas as pd
from scipy.special import ndtri

from quant.opcoes import arbitragens as arb
from quant.opcoes import bs, dados
from quant.opcoes import custos as C
from quant.opcoes import painel_vol as pv
from quant.opcoes.base import DIR_DADOS, DIR_OPC

FEE = C.FEE_PREMIO
NEG = C.NEG_MIN
SPR = C.SPREAD_MAX
TOP = 15
DU_MIN_VENC = 8


# ------------------------------------------------------------------------------------------------------------- series de retorno
def serie_tr_estendida(ativos, dia):
    """Indice de retorno total por ativo, estendido ate `dia` com a razao dos fechamentos sem ajuste dos dias que a base anual ainda nao tem."""
    f = dados.fator_retorno_total()
    ib = dados.ibov()
    fech = dados.fechamentos()
    out = {}
    for a in ativos:
        s = ib.copy() if a == "BOVA11" else (f[a].dropna() if a in f.columns else None)
        if s is None or len(s) < 500:
            continue
        ult = s.index[-1]
        if a in fech.columns:
            x = fech[a].dropna()
            novos = x[(x.index > ult) & (x.index <= dia)]
            if len(novos) and ult in x.index:
                base = s.iloc[-1]
                ref = x.loc[ult]
                add = pd.Series(base * novos.values / ref, index=novos.index)
                s = pd.concat([s, add])
        out[a] = s
    return out


def retornos_historicos(s, h, anos=10):
    """Retornos totais de h pregoes (janelas sobrepostas) dos ultimos `anos` anos. Devolve (array de retornos, volatilidade anualizada do periodo)."""
    x = s[s.index >= s.index[-1] - pd.DateOffset(years=anos)]
    if len(x) < h + 250:
        return None, None
    r = (x.shift(-h) / x - 1.0).dropna().values
    vol = float(np.log(x).diff().dropna().std() * math.sqrt(252))
    return r, vol


def vol_realizada(s, n):
    r = np.log(s).diff().dropna()
    return float(r.iloc[-n:].std() * math.sqrt(252)) if len(r) >= n else float("nan")


# ------------------------------------------------------------------------------------------------------------- estruturas
def _pagamento(estrutura, S):
    """Pagamento no vencimento por acao, vetorizado em S (array). pernas: lista de (tipo, lado, K)."""
    tot = np.zeros_like(S, dtype=float)
    for tipo, lado, K in estrutura:
        p = np.maximum(S - K, 0.0) if tipo == "C" else np.maximum(K - S, 0.0)
        tot += p * (1 - FEE) if lado == "compra" else -p
    return tot


def _implicita(S0, iv, t, r, n=2001):
    z = ndtri((np.arange(n) + 0.5) / n)
    return S0 * np.exp((r - 0.5 * iv * iv) * t + iv * math.sqrt(t) * z)


def avaliar_estrutura(estrutura, custo, S0, ret_hist, vol_hist, vr_agora, iv, du, r_aa):
    """Valor esperado, probabilidades e vantagem de uma estrutura. custo em R$ por acao (positivo = debito)."""
    t = du / 252.0
    financ = (1 + r_aa) ** t
    alvo = custo * financ
    S_h = S0 * (1.0 + ret_hist)
    pay_h = _pagamento(estrutura, S_h)
    ev_h = float(pay_h.mean() - alvo)
    k = vr_agora / vol_hist if vol_hist and vr_agora == vr_agora else 1.0
    S_e = S0 * np.exp(k * np.log1p(ret_hist))
    pay_e = _pagamento(estrutura, S_e)
    ev_e = float(pay_e.mean() - alvo)
    S_i = _implicita(S0, iv, t, math.log1p(r_aa))
    pay_i = _pagamento(estrutura, S_i)
    ganha_h = pay_h > alvo
    return {"ev_hist": ev_h, "ev_reesc": ev_e, "vant_hist": ev_h / custo * 100, "vant_reesc": ev_e / custo * 100,
            "prob_hist": float(ganha_h.mean() * 100), "prob_impl": float((pay_i > alvo).mean() * 100),
            "ganho_medio_quando_ganha": float((pay_h[ganha_h] - alvo).mean()) if ganha_h.any() else 0.0,
            "reescala": float(k)}


def perna_json(r, lado):
    return {"codigo": r["codigo"], "tipo": "put" if r["tipo"] == "P" else "call", "lado": lado, "exercicio": round(float(r["exercicio"]), 2),
            "vencimento": str(pd.Timestamp(r["vencimento"]).date()), "premio": round(float(r["premio_ref"]), 2),
            "oferta_compra": round(float(r["oferta_compra"]), 2), "oferta_venda": round(float(r["oferta_venda"]), 2),
            "delta": round(float(r["delta"]), 3), "vol_implicita": round(float(r["iv"]), 4), "negocios": int(r["negocios"])}


def liquidez_de(pernas_df):
    neg = min(int(x["negocios"]) for x in pernas_df)
    spr = max(float(x["spread"]) for x in pernas_df)
    if neg >= 100 and spr <= 0.15:
        return "boa"
    return "media" if (neg >= NEG and spr <= SPR) else "fraca"


def _escolher(el, tipo, alvo, tol):
    x = el[el["tipo"] == tipo].assign(_d=lambda d: (d["delta"].abs() - alvo).abs())
    x = x[x["_d"] <= tol].sort_values(["_d", "negocios"], ascending=[True, False])
    return x.iloc[0] if len(x) else None


def estruturas_do_ativo_venc(el, S0):
    """Todas as estruturas montaveis com as pernas liquidas `el` (um ativo, um vencimento). Devolve lista de dicts."""
    out = []
    c10, c25, cat = _escolher(el, "C", 0.10, 0.05), _escolher(el, "C", 0.25, 0.07), _escolher(el, "C", 0.50, 0.12)
    p10, p25, pat = _escolher(el, "P", 0.10, 0.05), _escolher(el, "P", 0.25, 0.07), _escolher(el, "P", 0.50, 0.12)

    def compra(r):
        return float(r["oferta_venda"]) * (1 + FEE)

    def venda(r):
        return float(r["oferta_compra"]) * (1 - FEE)

    for nome, r, fam, rot in (("call_fora_10", c10, "pozinho", "Call fora do dinheiro (delta ~0,10)"), ("call_fora_25", c25, "call_direcional", "Call fora do dinheiro (delta ~0,25)"),
                              ("call_no_dinheiro", cat, "capital_protegido", "Call no dinheiro"),
                              ("put_fora_10", p10, "pozinho", "Put fora do dinheiro (delta ~0,10)"), ("put_fora_25", p25, "baixa_direcional", "Put fora do dinheiro (delta ~0,25)"),
                              ("put_no_dinheiro", pat, "baixa_direcional", "Put no dinheiro")):
        if r is None:
            continue
        K = float(r["exercicio"])
        custo = compra(r)
        est = [(r["tipo"], "compra", K)]
        out.append({"estrutura": nome, "familia": fam, "rotulo": rot, "pernas": [(r, "compra")], "est": est, "custo": custo,
                    "perda_maxima": custo, "ganho_maximo": (K - custo) if r["tipo"] == "P" else None,
                    "equilibrio": (K - custo) if r["tipo"] == "P" else (K + custo), "equilibrio_inf": None})
    if cat is not None and c25 is not None and c25["exercicio"] > cat["exercicio"]:
        deb = compra(cat) - venda(c25)
        larg = float(c25["exercicio"] - cat["exercicio"])
        if 0 < deb < larg:
            out.append({"estrutura": "trava_alta_calls", "familia": "trava_alta", "rotulo": "Trava de alta com calls (no dinheiro / delta ~0,25)",
                        "pernas": [(cat, "compra"), (c25, "venda")], "est": [("C", "compra", float(cat["exercicio"])), ("C", "venda", float(c25["exercicio"]))],
                        "custo": deb, "perda_maxima": deb, "ganho_maximo": larg - deb, "equilibrio": float(cat["exercicio"]) + deb, "equilibrio_inf": None})
    if pat is not None and p25 is not None and p25["exercicio"] < pat["exercicio"]:
        deb = compra(pat) - venda(p25)
        larg = float(pat["exercicio"] - p25["exercicio"])
        if 0 < deb < larg:
            out.append({"estrutura": "trava_baixa_puts", "familia": "baixa_direcional", "rotulo": "Trava de baixa com puts (no dinheiro / delta ~-0,25)",
                        "pernas": [(pat, "compra"), (p25, "venda")], "est": [("P", "compra", float(pat["exercicio"])), ("P", "venda", float(p25["exercicio"]))],
                        "custo": deb, "perda_maxima": deb, "ganho_maximo": larg - deb, "equilibrio": float(pat["exercicio"]) - deb, "equilibrio_inf": None})
    # straddle: call e put do mesmo exercicio mais perto do dinheiro
    c = el[el["tipo"] == "C"]
    p = el[el["tipo"] == "P"]
    m = c.merge(p, on=["exercicio"], suffixes=("_c", "_p"))
    if len(m):
        m = m.assign(_d=(m["exercicio"] / S0 - 1).abs()).sort_values("_d")
        m = m[m["_d"] <= 0.05]
        if len(m):
            x = m.iloc[0]
            rc = {k[:-2]: x[k] for k in x.index if k.endswith("_c")}
            rp = {k[:-2]: x[k] for k in x.index if k.endswith("_p")}
            rc["exercicio"], rp["exercicio"] = x["exercicio"], x["exercicio"]
            custo = compra(rc) + compra(rp)
            K = float(x["exercicio"])
            out.append({"estrutura": "straddle", "familia": "vol_barata", "rotulo": "Straddle no dinheiro (call + put)", "pernas": [(pd.Series(rc), "compra"), (pd.Series(rp), "compra")],
                        "est": [("C", "compra", K), ("P", "compra", K)], "custo": custo, "perda_maxima": custo, "ganho_maximo": None,
                        "equilibrio": K + custo, "equilibrio_inf": K - custo})
    return out


# ------------------------------------------------------------------------------------------------------------- painel de hoje
def proximo_resultado(ativo, dia, datas, ident):
    from quant.opcoes import pozinho
    cd = pozinho.cd_cvm_de(ativo, ident) if ativo != "BOVA11" else None
    arr = datas.get(cd or "", None)
    if arr is None or len(arr) == 0:
        return None
    futuros = []
    for d in np.unique(arr.astype("datetime64[D]"))[-10:]:
        d = pd.Timestamp(d)
        for k in (1, 2):
            x = d + pd.DateOffset(years=k)
            if x > dia:
                futuros.append(x)
                break
    return str(min(futuros).date()) if futuros else None


def percentil_hoje(hist, valor):
    h = hist.dropna().values[-251:]
    if len(h) < 120 or valor != valor:
        return None
    return float(((np.append(h, valor)) <= valor).mean() * 100)


def montar(op, sp, dia, origem=""):
    """Constroi o bloco 'assimetrias' para a cadeia `op`/`sp` do pregao `dia`."""
    from quant.opcoes import pozinho
    dias = dados.dias_estendidos()
    cdi = dados.cdi_diario()
    cdi_aa_ser = ((1.0 + cdi.reindex(dias).ffill()) ** 252 - 1.0)
    r_aa = float(cdi_aa_ser.get(dia, cdi_aa_ser.dropna().iloc[-1]))
    spot = sp[(sp["fatcot"] == 1) & (sp["fech"] > 0)].drop_duplicates(["ativo", "dia"]).set_index(["ativo", "dia"])["fech"]
    o = pv.preparar_opcoes(op, spot, cdi_aa_ser, dias)
    hoje = pv.agregar_dia(o)
    hoje = hoje[hoje["dia"] == dia]
    hist = pv.carregar()
    ativos_hoje = sorted(set(hoje["ativo"]))
    tr = serie_tr_estendida(ativos_hoje, dia)
    ident = pd.read_parquet(os.path.join(dados.DIR_BANCO, "identidade.parquet"))
    datas = pozinho.datas_de_resultado()
    linhas = []
    for _, h in hoje.iterrows():
        a = h["ativo"]
        if a not in tr or pd.isna(h["iv_atm30"]):
            continue
        s = tr[a]
        hh = hist[(hist["ativo"] == a) & (hist["dia"] < dia)].sort_values("dia")
        p_vi = percentil_hoje(hh["iv_atm30"], h["iv_atm30"])
        p_sk = percentil_hoje(hh["skew_put"], h["skew_put"]) if h["skew_put"] == h["skew_put"] else None
        vr20, vr60, vr252 = vol_realizada(s, 20), vol_realizada(s, 60), vol_realizada(s, 252)
        linhas.append({"ativo": a, "preco": round(float(spot.get((a, dia), np.nan)), 2), "vol_implicita_30d": round(float(h["iv_atm30"]), 4),
                       "vol_realizada_20d": round(vr20, 4), "vol_realizada_60d": round(vr60, 4), "vol_realizada_252d": round(vr252, 4),
                       "percentil_vol_implicita_1a": None if p_vi is None else round(p_vi, 1),
                       "leitura_vol": None if p_vi is None else ("barata" if p_vi < 20 else ("cara" if p_vi > 80 else "normal")),
                       "inclinacao_put": None if h["skew_put"] != h["skew_put"] else round(float(h["skew_put"]), 4),
                       "percentil_inclinacao": None if p_sk is None else round(p_sk, 1),
                       "leitura_inclinacao": None if p_sk is None else ("baixa" if p_sk < 20 else ("alta" if p_sk > 80 else "normal")),
                       "desvio_paridade": None if h["desvio_paridade"] != h["desvio_paridade"] else round(float(h["desvio_paridade"]), 4),
                       "proximo_resultado": proximo_resultado(a, dia, datas, ident), "proximo_resultado_origem": "estimado: protocolo do mesmo trimestre do ano anterior",
                       "negocios_no_dia": int(h["negocios_dia"]) if h["negocios_dia"] == h["negocios_dia"] else 0, "series_liquidas": int(h["series_liquidas"]),
                       "spread_vr252_menos_vi": round(float(vr252 - h["iv_atm30"]), 4) if vr252 == vr252 else None})
    pa = pd.DataFrame(linhas)
    liq_ativos = pa[(pa["series_liquidas"] >= 6) & (pa["negocios_no_dia"] >= 1000)]["ativo"].tolist() if len(pa) else []
    # tercil da hora: barato por vr252 - vi entre os ativos liquidos (usado na familia A1)
    if len(liq_ativos) >= 6:
        sp252 = pa[pa["ativo"].isin(liq_ativos)].set_index("ativo")["spread_vr252_menos_vi"].dropna()
        corte = sp252.quantile(2 / 3)
        baratos_vr = set(sp252[sp252 >= corte].index)
    else:
        baratos_vr = set()
    # estruturas
    venc_m = [v for v in dados.vencimentos_padrao() if v > dia]
    vencs = []
    for v in venc_m:
        if arbitragens_du(dia, v) >= DU_MIN_VENC:
            vencs.append(v)
        if len(vencs) == 2:
            break
    liqs = pernas_liquidas(o, vencs)
    rows = []
    for a in liq_ativos:
        if a not in tr:
            continue
        S0 = float(spot.get((a, dia), np.nan))
        if S0 != S0:
            continue
        for v in vencs:
            el = liqs[(liqs["ativo"] == a) & (liqs["vencimento"] == v)]
            if len(el) < 4:
                continue
            du = arbitragens_du(dia, v)
            rh, vh = retornos_historicos(tr[a], du)
            if rh is None:
                continue
            vr60 = float(pa.loc[pa["ativo"] == a, "vol_realizada_60d"].iloc[0])
            for e in estruturas_do_ativo_venc(el, S0):
                if e["custo"] <= 0.02:
                    continue
                iv = float(np.mean([float(p["iv"]) for p, _ in e["pernas"]]))
                av = avaliar_estrutura(e["est"], e["custo"], S0, rh, vh, vr60, iv, du, r_aa)
                liq = liquidez_de([p for p, _ in e["pernas"]])
                vant = min(av["vant_hist"], av["vant_reesc"])
                gsp = (e["ganho_maximo"] / e["perda_maxima"]) if e["ganho_maximo"] else (av["ganho_medio_quando_ganha"] / e["perda_maxima"])
                rows.append({"ativo": a, "estrutura": e["estrutura"], "familia": e["familia"], "rotulo": e["rotulo"], "vencimento": str(pd.Timestamp(v).date()), "du": du,
                             "pernas_obj": e["pernas"], "custo": e["custo"], "perda_maxima": e["perda_maxima"], "ganho_maximo": e["ganho_maximo"], "equilibrio": e["equilibrio"],
                             "equilibrio_inf": e["equilibrio_inf"], "av": av, "vantagem": vant, "liquidez": liq, "ganho_sobre_perda": gsp, "S0": S0,
                             "barato_vr252": a in baratos_vr})
    df = pd.DataFrame(rows)
    return {"dia": dia, "origem": origem, "por_ativo": pa, "liq_ativos": liq_ativos, "vencs": vencs, "ranking_bruto": df, "r_aa": r_aa, "baratos_vr252": sorted(baratos_vr),
            "op": op, "sp": sp, "tr": tr, "o": o}


def pernas_liquidas(o, vencs=None):
    """Filtro de liquidez de cada perna: 30+ negocios da serie no dia, ofertas dos dois lados e spread de ate 30% do ponto medio (coluna `boa`)."""
    m = (o["negocios"] >= NEG) & o["boa"] & (o["spread"] <= SPR)
    if vencs is not None:
        m &= o["vencimento"].isin(vencs)
    return o[m]


def arbitragens_du(dia, venc):
    from quant.dados import calendario
    return len(calendario.pregoes((pd.Timestamp(dia) + pd.Timedelta(days=1)).date(), pd.Timestamp(venc).date()))


# ------------------------------------------------------------------------------------------------------------- veredito da familia
def _vf(x, n=2, sinal=False):
    """Numero com virgula decimal para os textos que vao para a tela."""
    if x is None or x != x:
        return "n/d"
    t = f"{x:+.{n}f}" if sinal else f"{x:.{n}f}"
    return t.replace(".", ",")


def veredito_familia(R_ass, R_ant, row):
    """historico_da_familia {estado, texto} a partir de resultados_assimetrias.json (R_ass) e resultados.json (R_ant)."""
    f, est = row["familia"], row["estrutura"]
    if f == "pozinho":
        pzd = {(x["modo"], x["tipo"]): x for x in R_ant["pozinho"]["descritivo"]}
        x = pzd[("inicio", "C" if "call" in est else "P")]
        return {"estado": "reprovada", "texto": f"Pozinho de {'call' if 'call' in est else 'put'}: {x['po_pct']:.0f}% viram pó, valor esperado {x['ev_pct']:+.0f}% por R$ 1 (2012-2026); nenhuma condição ficou positiva nas duas fases."}
    if f == "capital_protegido":
        a0 = R_ass["A0"]["variantes"]["call_atm_1m orcamento=1.0%"]
        pr = R_ass["A0"]["prova"].get("call_atm_1m orcamento=1.0%", {})
        return {"estado": "medindo", "texto": f"Call no dinheiro de ~1 mês como parte do capital protegido (A0): Sharpe {_vf(a0['descoberta']['sharpe'])} / {_vf(a0['validacao']['sharpe'])} / {_vf(pr.get('sharpe'))} "
                                              f"(descoberta / validação / prova), excesso de {_vf(pr.get('excesso_anual_pct'), 1, True)}% ao ano na prova com 1% de orçamento; Sharpe deflacionado {_vf(a0['descoberta'].get('sharpe_deflacionado'), 2)}: passou as fases, não está aprovada."}
    if f == "trava_alta":
        v = R_ass["A0"]["variantes"]["trava_alta_1m orcamento=0.5%"]
        return {"estado": "reprovada", "texto": f"Trava de alta (A0): Sharpe {_vf(v['descoberta']['sharpe'])} na descoberta e {_vf(v['validacao']['sharpe'])} na validação, abaixo da barra de 0,3."}
    if f == "vol_barata":
        c = R_ass["A1"]["configs"]["straddle_barato_vr252"]
        pr = R_ass["A1"]["prova"].get("straddle_barato_vr252", {})
        if row.get("barato_vr252"):
            return {"estado": "medindo", "texto": f"Straddle no tercil mais barato (volatilidade realizada de 252 dias acima da implícita, A1): {_vf(c['descoberta']['media_por_op_pct'], 0, True)}% / {_vf(c['validacao']['media_por_op_pct'], 0, True)}% / {_vf(pr.get('media_por_op_pct'), 0, True)}% por straddle "
                                                  f"(descoberta / validação / prova), mas t de {_vf(c['descoberta']['t'])} / {_vf(c['validacao']['t'])} / {_vf(pr.get('t'))} e Sharpe deflacionado {_vf(pr.get('sharpe_deflacionado'))}: passou as fases, não está aprovada."}
        td = R_ass["A1"]["configs"]["straddle_todos"]
        return {"estado": "reprovada", "texto": f"Straddle fora do tercil barato: sem sinal em A1 (straddle sem filtro: {_vf(td['descoberta']['media_por_op_pct'], 0, True)}% na descoberta, {_vf(td['validacao']['media_por_op_pct'], 0, True)}% na validação, t {_vf(td['validacao']['t'])}); antes de resultado trimestral perde {-R_ass['A6']['validacao']['media_pct']:.0f}% em média (A6)."}
    if f == "baixa_direcional":
        s = R_ass["A3"]["estruturas"]["trava_baixa_debito_skew_menor_20"]
        return {"estado": "reprovada", "texto": f"Comprar queda (put ou trava de baixa) sem sinal: a trava de baixa com inclinação baixa deu {_vf(s['descoberta']['media_por_op_pct'], 0, True)}% na descoberta (n {s['descoberta']['n_ops']}) e {_vf(s['validacao']['media_por_op_pct'], 0, True)}% na validação (A3)."}
    if f == "call_direcional":
        return {"estado": "reprovada", "texto": "Call fora do dinheiro (delta ~0,25) como aposta direcional: sem teste favorável; a variante testada de call fora do dinheiro de 2 meses ficou com Sharpe negativo na descoberta (A0)."}
    return {"estado": "reprovada", "texto": "Sem teste que sustente."}


def porque(row, pa_row, ver):
    partes = []
    if pa_row is not None and pa_row.get("leitura_vol"):
        partes.append(f"volatilidade implícita {pa_row['leitura_vol']} ({pa_row['percentil_vol_implicita_1a']:.0f}º percentil do ano)")
    partes.append(f"a distribuição histórica paga {row['vantagem']:+.0f}% sobre o custo (a mais prudente das duas contas)")
    if row["av"]["prob_hist"] - row["av"]["prob_impl"] > 5:
        partes.append("a chance histórica de lucro supera a implícita no preço")
    return "; ".join(partes).capitalize() + f". Família {ver['estado']} na pesquisa."


def montar_ranking(M, R_ass, R_ant):
    df = M["ranking_bruto"]
    if df.empty:
        return []
    df = df.sort_values("vantagem", ascending=False)
    pa = M["por_ativo"].set_index("ativo")
    out, vistos = [], set()
    for _, r in df.iterrows():
        chave = (r["ativo"], r["estrutura"])
        if chave in vistos:                              # um por ativo e estrutura: o melhor dos dois vencimentos
            continue
        vistos.add(chave)
        ver = veredito_familia(R_ass, R_ant, r)
        out.append({"posicao": len(out) + 1, "ativo": r["ativo"], "estrutura": r["estrutura"], "titulo": f"{r['rotulo']} em {r['ativo']}, vencimento {r['vencimento']}",
                    "familia": r["familia"], "pernas": [perna_json(p, lado) for p, lado in r["pernas_obj"]], "vencimento": r["vencimento"], "pregoes_ate_o_vencimento": int(r["du"]),
                    "preco_do_ativo": round(r["S0"], 2), "custo": round(float(r["custo"]), 3), "ganho_maximo": None if pd.isna(r["ganho_maximo"]) else round(float(r["ganho_maximo"]), 3),
                    "perda_maxima": round(float(r["perda_maxima"]), 3), "ponto_de_equilibrio": round(float(r["equilibrio"]), 2),
                    "ponto_de_equilibrio_inferior": None if pd.isna(r["equilibrio_inf"]) else round(float(r["equilibrio_inf"]), 2),
                    "prob_lucro_historica_pct": round(r["av"]["prob_hist"], 1), "prob_lucro_implicita_pct": round(r["av"]["prob_impl"], 1),
                    "valor_esperado_rs": round(min(r["av"]["ev_hist"], r["av"]["ev_reesc"]), 3), "vantagem_pct": round(float(r["vantagem"]), 1),
                    "vantagem_historica_pct": round(r["av"]["vant_hist"], 1), "vantagem_reescalada_pct": round(r["av"]["vant_reesc"], 1), "reescala_da_volatilidade": round(r["av"]["reescala"], 2),
                    "ganho_sobre_perda": round(float(r["ganho_sobre_perda"]), 2), "liquidez": r["liquidez"], "unidade": "R$ por ação (1 lote = 100 ações)",
                    "historico_da_familia": ver, "porque": porque(r, pa.loc[r["ativo"]].to_dict() if r["ativo"] in pa.index else None, ver)})
        if len(out) == TOP:
            break
    return out


def montar_arbitragens(M, n=8):
    op, sp, dia = M["op"], M["sp"], M["dia"]
    sp = sp[(sp["fatcot"] == 1) & (sp["fech"] > 0)]
    try:
        r = arb.varrer(op[op["dia"] == dia], sp[sp["dia"] == dia])
    except Exception as e:  # noqa: BLE001
        return [], {"erro": f"{type(e).__name__}: {e}"}
    if r.empty:
        return [], {"detectadas": 0}
    est = r[r["estrita"]].sort_values("folga", ascending=False)
    rotulos_arb = {"conversao": "Conversão", "reversao": "Reversão", "trava_call": "Trava com calls", "trava_put": "Trava com puts", "borboleta": "Borboleta"}
    out = []
    for _, x in est.head(n).iterrows():
        desc = {"conversao": "compra a ação, compra a put e vende a call do mesmo exercício: trava o exercício e rende acima do CDI",
                "reversao": "vende a ação a descoberto, vende a put e compra a call: o inverso da conversão (exige aluguel de ação)",
                "trava_call": "trava vertical de calls cotada fora do que pode valer", "trava_put": "trava vertical de puts cotada fora do que pode valer",
                "borboleta": "borboleta de custo negativo: recebe para montar uma posição que não perde"}[x["tipo"]]
        liq = "boa" if x["min_negocios"] >= 100 else ("media" if x["min_negocios"] >= 20 else "fraca")
        out.append({"tipo": x["tipo"], "ativo": x["ativo"], "descricao": f"{rotulos_arb[x['tipo']]} em {x['ativo']}, vencimento {pd.Timestamp(x['vencimento']).date()}, exercício {x['exercicio']:.2f} ({x['pernas']}): {desc}.",
                    "folga_rs": round(float(x["folga"]), 3), "liquidez": liq, "negocios_minimo_nas_pernas": int(x["min_negocios"]),
                    "aviso": "Folga em centavos por ação, calculada com as ofertas de FECHAMENTO depois de emolumentos; não garante execução simultânea das pernas. "
                             "Não inclui aluguel de ação, exercício antecipado nem margem. Na história de 250 pregões, só ~15% dessas combinações reaparecem no pregão seguinte."})
    return out, {"detectadas": int(len(r)), "estritas": int(r["estrita"].sum())}

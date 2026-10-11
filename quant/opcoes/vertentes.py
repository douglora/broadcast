"""
AS TRES VERTENTES de assimetria em opcoes (mandato do Douglas de 11/10/2026). Tudo SIMULACAO; nenhuma ordem real; nunca "compre/venda"
(Resolucao CVM 178); nunca call descoberta; nunca premio por formula quando a cadeia real existe (as formulas aqui so servem para
PROBABILIDADE implicita, nao para preco).

  especulativa          compra de calls onde a opcao esta barata para o que pode pagar (livro: carteira_simulada.json)
  dividendo_sintetico   venda de put coberta por CAIXA e call coberta; saida em 80% do premio, stop (livro: carteira_vertentes.json)
  travas_bova           travas de credito (renda com risco definido) e a debito (direcao) com BOVA11 (livro: carteira_vertentes.json)

Cada vertente tem regra, evidencia (HIPOTESES_VERTENTES.md / resultados_vertentes.json), ranking do dia, posicoes, placar e limites.
O bloco `vertentes` do quant_opcoes.json sai de `montar_bloco`. Contrato da tela: quant/docs/tela_opcoes_vertentes.md.
"""
import json
import math
import os
from datetime import datetime

import numpy as np
import pandas as pd

from quant.comum import DIR_SAIDA
from quant.opcoes import bs, dados, manejo
from quant.opcoes import carteira_simulada as CS
from quant.opcoes import custos as C
from quant.opcoes.base import DIR_OPC

ARQ_PESQUISA = os.path.join(DIR_OPC, "resultados_vertentes.json")
ARQ_ESTADO = os.path.join(DIR_SAIDA, "opcoes", "carteira_vertentes.json")
NOMES = ("especulativa", "dividendo_sintetico", "travas_bova")
LOTE = CS.LOTE
FEE = C.FEE_PREMIO
ALVO = 0.20                 # recompra com 20% do credito (80% capturado)
STOP_UNICA = 3.0
STOP_TRAVA = 2.0
FRACAO_LIMITE = {"especulativa": 0.30, "dividendo_sintetico": 0.40, "travas_bova": 0.30}   # repartição proposta do orcamento de queda
FRACAO_GARANTIA_V2 = 2.0 / 3.0                    # do caixa da classe, no maximo, como garantia de put vendida
DU_MIN_ENTRADA = 15
DELTA_V2 = (0.15, 0.30)                           # janela do delta da put vendida (alvo 0,20)
DELTA_V3 = (0.10, 0.30)
LARGURA_V3 = (0.02, 0.07)                         # da cotacao do ativo
MAX_ABERTAS_V2 = 2
MAX_ABERTAS_V3 = 3
RISCO_POR_TRAVA = 900.0                           # perda maxima de 1 lote de trava de 3% a 6% de largura com BOVA11 perto de R$ 200 (largura 4,5% = uns R$ 800)
RISCO_CONTADO_SEM_STOP = 0.25                     # put sem stop (acoes): risco contado no teto = 25% do strike (pior mes da cesta no teste: -24%); o pior caso real e o strike inteiro
SCORE_MIN_V1 = 3                                  # pontos minimos para o livro abrir uma call da vertente especulativa
MAX_ABERTAS_V1_CALL = 2


def _n(x, nd=2):
    """Float arredondado ou None (NaN/inf/None) -- JSON estrito."""
    try:
        if x is None:
            return None
        x = float(x)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return round(x, nd)


_t = CS._t


def _pct_fracao(v):
    return f"{FRACAO_LIMITE[v] * 100:.0f}"


def _brl(x):
    return f"{x:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------------------------------------------- limites
def orcamentos():
    """(capital da classe de opcoes, orcamento de queda das opcoes) em R$. Livro por classes desligado: capital inteiro e o teto antigo."""
    from quant.risco import livro
    cfg = livro.config()
    cap = CS.CAPITAL
    classe = cap * livro.peso("opcoes")
    queda = cap * float(cfg["orcamento_de_queda_pct"]["opcoes"]) / 100.0 if cfg.get("ligado") else CS.RISCO_TOTAL_MAX
    return float(classe), float(queda)


def limite_risco(vertente):
    """Teto de risco aberto da vertente, R$ (parte do orcamento de queda)."""
    _, queda = orcamentos()
    return round(queda * FRACAO_LIMITE[vertente], 2)


def pesquisa():
    try:
        with open(ARQ_PESQUISA, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _cfg(res, lista, nome):
    for r in res.get(lista, []):
        if r.get("config") == nome:
            return r
    return None


# ---------------------------------------------------------------------------------------------------------------- regime e sinais
def regime(s):
    """Direcao de uma serie de preco/retorno total (pandas Series): alta, baixa ou neutra, com os numeros.
    alta: fechamento acima da media de 200 pregoes e media de 50 acima da de 5 pregoes atras; baixa: o espelho; senao neutra."""
    s = s.dropna()
    if len(s) < 260:
        return {"direcao": "neutra", "motivos": ["histórico curto: sem leitura de tendência"], "acima_mm200": None}
    c = float(s.iloc[-1])
    m200 = float(s.rolling(200).mean().iloc[-1])
    m50 = s.rolling(50).mean()
    m50_sobe = bool(m50.iloc[-1] > m50.iloc[-6])
    acima = c > m200
    ret20 = c / float(s.iloc[-21]) - 1.0
    topo = float(s.iloc[-252:].max())
    base = float(s.iloc[-60:].min())
    if acima and m50_sobe:
        d = "alta"
    elif (not acima) and (not m50_sobe):
        d = "baixa"
    else:
        d = "neutra"
    mot = [f"fechamento {'acima' if acima else 'abaixo'} da média de 200 pregões ({_t((c / m200 - 1) * 100)}%)",
           f"média de 50 pregões {'subindo' if m50_sobe else 'caindo'} frente a 5 pregões atrás",
           f"retorno de 20 pregões {_t(ret20 * 100)}%", f"{_t((c / topo - 1) * 100)}% do topo de 12 meses; {_t((c / base - 1) * 100)}% acima da mínima de 60 pregões"]
    return {"direcao": d, "motivos": mot, "acima_mm200": bool(acima), "retorno_20d_pct": _n(ret20 * 100, 1), "distancia_minima_60d_pct": _n((c / base - 1) * 100, 1),
            "distancia_topo_12m_pct": _n((c / topo - 1) * 100, 1)}


def gatilho_alta(s, janela=5):
    """T1 (fechamento acima da maxima dos 55 anteriores) ou T2 (volta acima da media de 200 com a de 50 virando para cima) nos ultimos `janela` pregoes."""
    s = s.dropna()
    if len(s) < 260:
        return None
    m50, m200 = s.rolling(50).mean(), s.rolling(200).mean()
    t1 = s > s.shift(1).rolling(55).max()
    t2 = (s > m200) & (s.shift(1) <= m200.shift(1)) & (m50 > m50.shift(5))
    if bool(t1.iloc[-janela:].any()):
        return "T1"
    if bool(t2.iloc[-janela:].any()):
        return "T2"
    return None


def suporte_60d(s):
    """Minima de 60 pregoes convertida para o preco de hoje (razao do indice de retorno total)."""
    s = s.dropna()
    if len(s) < 61:
        return None
    return float(s.iloc[-60:].min() / s.iloc[-1])


# ---------------------------------------------------------------------------------------------------------------- probabilidades
def p_acima_implicita(S, K, du, r, iv):
    """P(S_T > K) que o preco embute: N(d2) de Black-Scholes com a volatilidade implicita da propria serie (so probabilidade, nao preco)."""
    if not (S > 0 and K > 0 and du > 0 and iv and iv > 0):
        return float("nan")
    d2 = bs._d1d2(S, K, du / 252.0, r, iv)[1]
    return float(bs._cdf(d2))


def p_acima_empirica(ret, S, K):
    """Fracao dos retornos historicos de mesmo prazo em que S*(1+ret) > K."""
    if ret is None or len(ret) == 0:
        return float("nan")
    return float(np.mean(S * (1.0 + ret) > K))


def retornos_empiricos(s, du, anos=15):
    from quant.opcoes.assimetrias import retornos_historicos
    if s is None:
        return None
    r, _ = retornos_historicos(s, int(du), anos=anos)
    return r


def _tr(M, a):
    tr = M.get("tr") or {}
    return tr.get(a)


def _linhas_liquidas(M, ativo, dia, tipo, venc):
    o = M["o"]
    x = o[(o["ativo"] == ativo) & (o["dia"] == dia) & (o["tipo"] == tipo) & (o["vencimento"] == venc) & (o["negocios"] >= C.NEG_MIN) & o["boa"]
          & (o["spread"] <= C.SPREAD_MAX) & o["oferta_compra"].notna() & o["oferta_venda"].notna() & (o["oferta_compra"] > 0)]
    return x


def _du(dia, venc):
    from quant.opcoes.assimetrias import arbitragens_du
    return int(arbitragens_du(dia, venc))


def _venc_alvo(M, dia, du_min=DU_MIN_ENTRADA):
    """Primeiro vencimento mensal com pelo menos `du_min` pregoes pela frente."""
    for v in dados.vencimentos_padrao():
        if v > dia and _du(dia, v) >= du_min:
            return v
    return None


def _perna(r, lado, ativo=None):
    return CS._perna_estado(r, lado, LOTE, ativo or r["ativo"])


# ---------------------------------------------------------------------------------------------------------------- V1 especulativa
def ranking_v1(M, dia, n=8):
    """Calls no dinheiro (delta mais perto de 0,50) onde a opcao esta barata para o que pode pagar. Pontos FIXOS (regra no texto da tela):
    +2 volatilidade implicita barata contra a realizada de 252 pregoes (terco de cima entre os ativos liquidos; sinal A1);
    +1 percentil da VI do proprio ativo abaixo de 40 e -1 acima de 80; +2 gatilho tecnico de alta (T1/T2) nos ultimos 5 pregoes;
    +1 fechamento acima da media de 200; -1 resultado trimestral antes do vencimento (a VI ja carrega o evento; A6 reprovou o straddle).
    Inclinacao: informativa (A3 reprovou como sinal)."""
    pa = M["por_ativo"].set_index("ativo")
    baratos = set(M.get("baratos_vr252", []))
    venc = _venc_alvo(M, dia)
    if venc is None:
        return []
    du = _du(dia, venc)
    linhas = []
    for a in M["liq_ativos"]:
        if a not in pa.index:
            continue
        el = _linhas_liquidas(M, a, dia, "C", venc)
        if el.empty:
            continue
        S = float(el["S"].iloc[0])
        el = el.assign(_d=(el["delta"] - 0.50).abs()).sort_values(["_d", "negocios"], ascending=[True, False])
        c = el.iloc[0]
        if c["_d"] > 0.15:
            continue
        s = _tr(M, a)
        g = gatilho_alta(s) if s is not None else None
        rg = regime(s) if s is not None else {"acima_mm200": None}
        p = pa.loc[a]
        pts, motivos = 0, []
        if a in baratos:
            pts += 2
            sp252 = p.get("spread_vr252_menos_vi")
            motivos.append("entre o terço mais barato dos ativos líquidos na volatilidade implícita contra a realizada de 252 pregões"
                           + (f" (realizada menos implícita: {_t(float(sp252) * 100)} pontos; negativo = a opção ainda custa mais que a realizada)" if sp252 is not None and sp252 == sp252 else "") + " (+2)")
        pvi = p.get("percentil_vol_implicita_1a")
        if pvi is not None and pvi == pvi:
            if pvi < 40:
                pts += 1
                motivos.append(f"percentil da volatilidade implícita {_t(pvi, 0)} (+1)")
            elif pvi > 80:
                pts -= 1
                motivos.append(f"percentil da volatilidade implícita {_t(pvi, 0)}: cara (-1)")
        if g:
            pts += 2
            motivos.append(f"gatilho técnico de alta {g} nos últimos 5 pregões (+2)")
        if rg.get("acima_mm200"):
            pts += 1
            motivos.append("acima da média de 200 pregões (+1)")
        evento = p.get("proximo_resultado")
        if evento and str(dia.date()) < str(evento) <= str(pd.Timestamp(venc).date()):
            pts -= 1
            motivos.append(f"resultado trimestral provável em {evento}, antes do vencimento: o preço já carrega o evento (-1)")
        ask = float(c["oferta_venda"])
        custo_op = ask * (1 + FEE)
        K = float(c["exercicio"])
        be = K + custo_op
        ret = retornos_empiricos(s, du)
        iv = float(c["iv"])
        linhas.append({
            "ativo": a, "serie": c["codigo"], "vencimento": str(pd.Timestamp(venc).date()), "pregoes": du, "strike": _n(K), "premio": _n(ask), "delta": _n(c["delta"]),
            "preco_ativo": _n(S), "equilibrio": _n(be), "distancia_equilibrio_pct": _n((be / S - 1) * 100, 1),
            "prob_acima_equilibrio_preco_pct": _n((p_acima_implicita(S, be, du, float(c["r"]), iv)) * 100, 0),
            "prob_acima_equilibrio_historico_pct": _n((p_acima_empirica(ret, S, be)) * 100, 0),
            "vol_implicita_pct": _n(iv * 100, 1), "vol_realizada_252d_pct": _n(float(p["vol_realizada_252d"]) * 100, 1),
            "percentil_vol_implicita": _n(pvi, 0), "inclinacao_put_percentil": _n(p.get("percentil_inclinacao"), 0),
            "gatilho_tecnico": g, "acima_media_200": rg.get("acima_mm200"), "proximo_resultado": evento,
            "pontos": pts, "porque": motivos, "custo_do_lote_rs": _n(custo_op * LOTE, 0),
            "liquidez": {"negocios": int(c["negocios"]), "spread_pct": _n(float(c["spread"]) * 100, 1)},
            "cabe_no_teto_por_estrutura": bool(custo_op * LOTE <= CS.RISCO_POR_ESTRUTURA),
            "pernas_obj": c,
        })
    linhas.sort(key=lambda r: (-r["pontos"], -(r["liquidez"]["negocios"])))
    return linhas[:n]


# ---------------------------------------------------------------------------------------------------------------- V2 dividendo sintetico
def _candidatos_put(M, dia, ativo, venc, s, pa_row, perc_vi):
    el = _linhas_liquidas(M, ativo, dia, "P", venc)
    if el.empty:
        return []
    el = el[(el["delta"].abs() >= DELTA_V2[0]) & (el["delta"].abs() <= DELTA_V2[1])]
    if el.empty:
        return []
    el = el.assign(_d=(el["delta"].abs() - 0.20).abs()).sort_values(["_d", "negocios"], ascending=[True, False])
    r = el.iloc[0]
    S = float(r["S"])
    du = _du(dia, venc)
    K = float(r["exercicio"])
    bid = float(r["oferta_compra"])
    credito = bid * (1 - FEE)
    sup = suporte_60d(s)
    sup_preco = S * sup if sup else None
    ret = retornos_empiricos(s, du)
    iv = float(r["iv"])
    p_ex_impl = 1.0 - (p_acima_implicita(S, K, du, float(r["r"]), iv))
    p_ex_emp = 1.0 - (p_acima_empirica(ret, S, K))
    evento = pa_row.get("proximo_resultado") if pa_row is not None else None
    ev_no_caminho = bool(evento and str(dia.date()) < str(evento) <= str(pd.Timestamp(venc).date()))
    rend = credito / K
    return [{"tipo": "put coberta por caixa", "ativo": ativo, "serie": r["codigo"], "vencimento": str(pd.Timestamp(venc).date()), "pregoes": du,
             "strike": _n(K), "premio": _n(bid), "delta": _n(r["delta"]), "preco_ativo": _n(S), "distancia_strike_pct": _n((K / S - 1) * 100, 1),
             "rendimento_no_prazo_pct": _n(rend * 100, 2), "rendimento_anualizado_pct": _n(((1 + rend) ** (252.0 / du) - 1) * 100, 1),
             "garantia_do_lote_rs": _n(K * LOTE, 0), "credito_do_lote_rs": _n(credito * LOTE, 0),
             "recompra_em_80pct": _n(credito * ALVO, 2), "stop_em": _n(credito * STOP_UNICA, 2),
             "prob_exercicio_preco_pct": _n(p_ex_impl * 100, 0), "prob_exercicio_historico_pct": _n(p_ex_emp * 100, 0),
             "percentil_vol_implicita": _n(perc_vi, 0), "vol_implicita_pct": _n(iv * 100, 1),
             "suporte_60d": _n(sup_preco), "strike_abaixo_do_suporte": bool(sup_preco is not None and K < sup_preco),
             "evento_no_caminho": ev_no_caminho, "proximo_resultado": evento,
             "liquidez": {"negocios": int(r["negocios"]), "spread_pct": _n(float(r["spread"]) * 100, 1)},
             "pernas_obj": r}]


def _candidatos_call_coberta(M, dia, ativo, venc, s, pa_row):
    el = _linhas_liquidas(M, ativo, dia, "C", venc)
    if el.empty:
        return []
    el = el[(el["delta"] >= 0.20) & (el["delta"] <= 0.40)]
    if el.empty:
        return []
    el = el.assign(_d=(el["delta"] - 0.30).abs()).sort_values(["_d", "negocios"], ascending=[True, False])
    r = el.iloc[0]
    S = float(r["S"])
    du = _du(dia, venc)
    K = float(r["exercicio"])
    bid = float(r["oferta_compra"])
    credito = bid * (1 - FEE)
    ret = retornos_empiricos(s, du)
    iv = float(r["iv"])
    evento = pa_row.get("proximo_resultado") if pa_row is not None else None
    return [{"tipo": "call coberta (exige o papel em carteira)", "ativo": ativo, "serie": r["codigo"], "vencimento": str(pd.Timestamp(venc).date()), "pregoes": du,
             "strike": _n(K), "premio": _n(bid), "delta": _n(r["delta"]), "preco_ativo": _n(S), "distancia_strike_pct": _n((K / S - 1) * 100, 1),
             "rendimento_no_prazo_pct": _n(credito / S * 100, 2), "rendimento_anualizado_pct": _n(((1 + credito / S) ** (252.0 / du) - 1) * 100, 1),
             "garantia_do_lote_rs": _n(S * LOTE, 0), "credito_do_lote_rs": _n(credito * LOTE, 0),
             "recompra_em_80pct": _n(credito * ALVO, 2), "stop_em": None,
             "prob_exercicio_preco_pct": _n((p_acima_implicita(S, K, du, float(r["r"]), iv)) * 100, 0),
             "prob_exercicio_historico_pct": _n((p_acima_empirica(ret, S, K)) * 100, 0),
             "percentil_vol_implicita": _n(pa_row.get("percentil_vol_implicita_1a") if pa_row is not None else None, 0), "vol_implicita_pct": _n(iv * 100, 1),
             "suporte_60d": None, "strike_abaixo_do_suporte": None,
             "evento_no_caminho": bool(evento and str(dia.date()) < str(evento) <= str(pd.Timestamp(venc).date())), "proximo_resultado": evento,
             "liquidez": {"negocios": int(r["negocios"]), "spread_pct": _n(float(r["spread"]) * 100, 1)}, "pernas_obj": r}]


def ranking_v2(M, dia, n=8):
    """Puts cobertas por caixa e calls cobertas, nos ativos liquidos. Criterios (regra no texto da tela): delta da put 0,15 a 0,30 (alvo 0,20), vencimento com
    15+ pregoes, liquidez (30+ negocios, spread ate 30%), sem resultado trimestral no caminho; ordena pelo rendimento anualizado entre as que passam; strike abaixo do
    suporte de 60 pregoes e percentil da VI alto aparecem como motivos (a grade da pesquisa nao achou ganho nesses filtros: so contexto). BOVA11 primeiro por empate."""
    pa = M["por_ativo"].set_index("ativo")
    venc = _venc_alvo(M, dia)
    if venc is None:
        return []
    out = []
    for a in M["liq_ativos"]:
        s = _tr(M, a)
        if s is None or a not in pa.index:
            continue
        prow = pa.loc[a].to_dict()
        out += _candidatos_put(M, dia, a, venc, s, prow, prow.get("percentil_vol_implicita_1a"))
        out += _candidatos_call_coberta(M, dia, a, venc, s, prow)
    for r in out:
        pts, mot = [], []
        if r["tipo"].startswith("put"):
            if r["strike_abaixo_do_suporte"]:
                mot.append("strike abaixo da mínima de 60 pregões")
            if (r["percentil_vol_implicita"] or 0) >= 60:
                mot.append(f"volatilidade implícita no percentil {r['percentil_vol_implicita']:.0f}")
            if r["evento_no_caminho"]:
                mot.append(f"resultado trimestral provável em {r['proximo_resultado']}, antes do vencimento")
        r["porque"] = mot
        r["elegivel_livro"] = bool(r["tipo"].startswith("put") and not r["evento_no_caminho"])
    out.sort(key=lambda r: (not r["elegivel_livro"], r["ativo"] != "BOVA11", -(r["rendimento_anualizado_pct"] or 0)))
    return out[:n]


# ---------------------------------------------------------------------------------------------------------------- V3 travas BOVA11
def tabela_travas(M, dia, regime_bova):
    """Por vencimento mensal de BOVA11 (os dois proximos com 8+ pregoes): as melhores travas de credito (put spread e call spread) por retorno sobre o risco.
    Credito = oferta de compra da vendida - oferta de venda da comprada (menos emolumento nas duas pontas). Probabilidades: a que o PRECO embute (N(d2) com a
    volatilidade implicita de cada perna) e a EMPIRICA (retornos de mesmo prazo do Ibovespa de retorno total, 15 anos, janelas sobrepostas)."""
    s = _tr(M, "BOVA11")
    if s is None:
        return []
    vencs = [v for v in M.get("vencs", []) if _du(dia, v) >= 8]
    linhas = []
    for venc in vencs:
        du = _du(dia, venc)
        ret = retornos_empiricos(s, du)
        for tipo in ("P", "C"):
            el = _linhas_liquidas(M, "BOVA11", dia, tipo, venc)
            if el.empty:
                continue
            S = float(el["S"].iloc[0])
            vend = el[(el["delta"].abs() >= DELTA_V3[0]) & (el["delta"].abs() <= DELTA_V3[1])]
            cand = []
            for c in vend.itertuples(index=False):
                dk = (el["exercicio"] < c.exercicio) if tipo == "P" else (el["exercicio"] > c.exercicio)
                for l in el[dk].itertuples(index=False):
                    larg = abs(c.exercicio - l.exercicio)
                    if not (LARGURA_V3[0] * S <= larg <= LARGURA_V3[1] * S):
                        continue
                    credito = c.oferta_compra * (1 - FEE) - l.oferta_venda * (1 + FEE)
                    if credito <= 0 or credito >= larg:
                        continue
                    risco = larg - credito
                    if tipo == "P":
                        be = c.exercicio - credito
                        p_max_i = p_acima_implicita(S, c.exercicio, du, float(c.r), float(c.iv))
                        p_perda_i = 1.0 - (p_acima_implicita(S, l.exercicio, du, float(l.r), float(l.iv)))
                        p_lucro_i = p_acima_implicita(S, be, du, float(c.r), float(c.iv))
                        ST = S * (1.0 + ret) if ret is not None else None
                        pay = (credito - np.clip(c.exercicio - ST, 0.0, larg)) if ST is not None else None
                        p_max_e = p_acima_empirica(ret, S, c.exercicio)
                        p_perda_e = 1.0 - (p_acima_empirica(ret, S, l.exercicio) if ret is not None else float("nan"))
                    else:
                        be = c.exercicio + credito
                        p_max_i = 1.0 - (p_acima_implicita(S, c.exercicio, du, float(c.r), float(c.iv)))
                        p_perda_i = p_acima_implicita(S, l.exercicio, du, float(l.r), float(l.iv))
                        p_lucro_i = 1.0 - (p_acima_implicita(S, be, du, float(c.r), float(c.iv)))
                        ST = S * (1.0 + ret) if ret is not None else None
                        pay = (credito - np.clip(ST - c.exercicio, 0.0, larg)) if ST is not None else None
                        p_max_e = 1.0 - (p_acima_empirica(ret, S, c.exercicio) if ret is not None else float("nan"))
                        p_perda_e = p_acima_empirica(ret, S, l.exercicio)
                    ev = float(np.mean(pay)) if pay is not None else None
                    alinhada = (tipo == "P" and regime_bova["direcao"] in ("alta", "neutra")) or (tipo == "C" and regime_bova["direcao"] in ("baixa", "neutra"))
                    cand.append({
                        "vencimento": str(pd.Timestamp(venc).date()), "pregoes": du, "trava": "alta com put (crédito)" if tipo == "P" else "baixa com call (crédito)",
                        "tipo": "put_spread" if tipo == "P" else "call_spread", "strike_vendido": _n(c.exercicio), "strike_comprado": _n(l.exercicio), "largura": _n(larg),
                        "largura_pct": _n(larg / S * 100, 1), "credito": _n(credito), "risco_maximo": _n(risco),
                        "retorno_sobre_risco_pct": _n(credito / risco * 100, 1), "delta_vendido": _n(c.delta), "equilibrio": _n(be),
                        "distancia_equilibrio_pct": _n((be / S - 1) * 100, 1),
                        "prob_ganho_maximo_preco_pct": _n((p_max_i) * 100, 0), "prob_ganho_maximo_historico_pct": _n((p_max_e) * 100, 0),
                        "prob_lucro_preco_pct": _n((p_lucro_i) * 100, 0),
                        "prob_perda_maxima_preco_pct": _n((p_perda_i) * 100, 0), "prob_perda_maxima_historico_pct": _n((p_perda_e) * 100, 0),
                        "valor_esperado_historico_por_lote_rs": _n(ev * LOTE, 0) if ev is not None else None,
                        "credito_do_lote_rs": _n(credito * LOTE, 0), "risco_do_lote_rs": _n(risco * LOTE, 0),
                        "alinhada_com_a_tendencia": bool(alinhada),
                        "liquidez": {"negocios_minimo": int(min(c.negocios, l.negocios)), "spread_maximo_pct": _n(max(c.spread, l.spread) * 100, 1)},
                        "perna_vendida": c.codigo, "perna_comprada": l.codigo, "preco_ativo": _n(S),
                        "_c": pd.Series(c._asdict()), "_l": pd.Series(l._asdict()),
                    })
            cand.sort(key=lambda r: -(r["retorno_sobre_risco_pct"] or 0))
            linhas += cand
    return linhas


def melhores_travas(tabela, n_por_grupo=3):
    """Tela: as `n_por_grupo` melhores por retorno sobre o risco de cada (vencimento, tipo)."""
    out, cont = [], {}
    for r in sorted(tabela, key=lambda r: (r["vencimento"], r["tipo"], -(r["retorno_sobre_risco_pct"] or 0))):
        k = (r["vencimento"], r["tipo"])
        cont[k] = cont.get(k, 0) + 1
        if cont[k] <= n_por_grupo:
            out.append(r)
    return out


# ---------------------------------------------------------------------------------------------------------------- livro das vertentes V2 e V3
def estado_vazio(dia):
    return {"desde": str(pd.Timestamp(dia).date()), "ultima_data": None, "posicoes": [], "criado_em": datetime.now().isoformat(timespec="seconds")}


def carregar_estado(dia, caminho=ARQ_ESTADO):
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    return estado_vazio(dia)


def gravar_estado(est, caminho=ARQ_ESTADO):
    CS.gravar_estado(est, caminho)


def _credito_unit(pos):
    return -float(pos["custo"]) / pos["qtd"]


def _observavel(pos):
    """Hoje todas as pernas tem oferta no fechamento (a decisao de sair so vale com cotacao do dia, como no historico)."""
    m = pos.get("marcacao") or ""
    return "mantido" not in m and "último negócio" not in m and "intrínseco" not in m


def gerir(pos, dia, indice=None):
    """Saida por alvo (80% do premio) ou stop, em posicao vendida aberta e ja marcada hoje. Fecha a posicao no custo marcado. Devolve o motivo ou None.
    Como no historico: so decide em pregao com cotacao das pernas e, na perna vendida, 10+ negocios (`indice` da cadeia do dia)."""
    if pos["estado"] != "aberta" or pd.Timestamp(pos["vencimento"]) <= dia or not _observavel(pos):
        return None
    if indice is not None:
        for p in pos["pernas"]:
            if p["lado"] == "venda":
                r = indice.get((p["codigo"], p["vencimento"]))
                if r is None or int(r["negocios"]) < manejo.NEG_OBS:
                    return None
    cred = _credito_unit(pos)
    custo = -float(pos["valor_hoje"]) / pos["qtd"]
    if cred <= 0:
        return None
    motivo = None
    if custo <= ALVO * cred:
        motivo = "alvo: 80% do prêmio capturado"
    elif pos.get("stop_multiplo") and custo >= pos["stop_multiplo"] * cred:
        motivo = f"stop: custo de fechar chegou a {pos['stop_multiplo']:g} vezes o prêmio"
    if motivo:
        pos["estado"] = "encerrada"
        pos["fechada_em"] = str(dia.date())
        pos["valor_final"] = pos["valor_hoje"]
        pos["motivo_fechamento"] = motivo
    return motivo


def _taxa_exercicio(pos, spot):
    """Taxa de exercicio (0,03% sobre strike + preco) de cada perna dentro do dinheiro no vencimento."""
    t = 0.0
    for p in pos["pernas"]:
        S = spot.get(p["ativo"])
        if S is None or S != S:
            continue
        dentro = (S > p["exercicio"]) if p["tipo"] == "call" else (S < p["exercicio"])
        if dentro:
            t += C.FEE_EXERC * (p["exercicio"] + S) * p["qtd"]
    return t


def rendimento_caixa(pos, dia):
    """CDI sobre a garantia enquanto a posicao ficou aberta (V2: caixa da classe; V3: o risco maximo)."""
    fim = pd.Timestamp(pos["fechada_em"]) if pos.get("fechada_em") else dia
    return float(pos.get("garantia_rs", 0.0)) * (manejo.fator_cdi(pd.Timestamp(pos["aberta_em"]), fim) - 1.0)


def _pos_v2(c, dia, qtd):
    r = c["pernas_obj"]
    perna = CS._perna_estado(r, "venda", qtd, c["ativo"])
    credito = float(r["oferta_compra"]) * (1 - FEE) * qtd
    stop = STOP_UNICA if c["ativo"] == "BOVA11" else None
    return {"id": f"{pd.Timestamp(dia).date()}|dividendo_sintetico|{c['ativo']}|put|{c['vencimento']}", "aberta_em": str(pd.Timestamp(dia).date()), "vertente": "dividendo_sintetico",
            "titulo": f"Put coberta por caixa em {c['ativo']}, strike {_t(c['strike'], 2)}, vencimento {c['vencimento']}", "ativo": c["ativo"], "estrutura": "put_coberta_por_caixa",
            "familia": "dividendo_sintetico", "pernas": [perna], "qtd": qtd, "custo": round(-credito, 2), "valor_hoje": round(-credito, 2), "resultado_rs": 0.0,
            "risco_rs": round(2.0 * credito, 2) if stop else round(RISCO_CONTADO_SEM_STOP * float(c["strike"]) * qtd, 2), "garantia_rs": round(float(c["strike"]) * qtd, 2),
            "pior_caso_rs": round(float(c["strike"]) * qtd, 2), "vencimento": c["vencimento"], "estado": "aberta", "stop_multiplo": stop, "alvo_pct": 80,
            "marcacao": "aberta na oferta de compra do fechamento (venda); recompra a ser medida na oferta de venda",
            "nota": ("Saída recomprando quando a opção vale 20% do recebido (80% capturado) ou no vencimento"
                     + (f"; stop em {stop:g} vezes o prêmio (só em BOVA11: em ações o stop piorou o histórico)" if stop else "; sem stop (em ações o stop piorou o histórico)")
                     + ". Garantia: o caixa da classe, que rende CDI. Risco contado no teto = perda se o stop funcionar (2 vezes o prêmio) ou, sem stop, 25% do strike; o pior caso real é o strike inteiro menos o prêmio.")}


def _pos_v3(c, dia, qtd):
    cs, ls = c["_c"], c["_l"]
    tipo = "put" if c["tipo"] == "put_spread" else "call"
    pc = {"codigo": cs["codigo"], "ativo": "BOVA11", "tipo": tipo, "lado": "venda", "exercicio": round(float(cs["exercicio"]), 2), "vencimento": c["vencimento"],
          "premio_entrada": round(float(cs["oferta_compra"]), 2), "qtd": qtd}
    pl = {"codigo": ls["codigo"], "ativo": "BOVA11", "tipo": tipo, "lado": "compra", "exercicio": round(float(ls["exercicio"]), 2), "vencimento": c["vencimento"],
          "premio_entrada": round(float(ls["oferta_venda"]), 2), "qtd": qtd}
    credito = c["credito"] * qtd
    risco = c["risco_maximo"] * qtd
    return {"id": f"{pd.Timestamp(dia).date()}|travas_bova|{c['tipo']}|{c['strike_vendido']}|{c['strike_comprado']}|{c['vencimento']}", "aberta_em": str(pd.Timestamp(dia).date()),
            "vertente": "travas_bova", "titulo": f"Trava de {'alta' if tipo == 'put' else 'baixa'} de crédito em BOVA11: vende {c['strike_vendido']:.0f}, compra {c['strike_comprado']:.0f}, vencimento {c['vencimento']}",
            "ativo": "BOVA11", "estrutura": c["tipo"], "familia": "travas_bova", "pernas": [pc, pl], "qtd": qtd, "custo": round(-credito, 2), "valor_hoje": round(-credito, 2),
            "resultado_rs": 0.0, "risco_rs": round(risco, 2), "garantia_rs": round(risco, 2), "pior_caso_rs": round(risco, 2), "vencimento": c["vencimento"], "estado": "aberta",
            "stop_multiplo": STOP_TRAVA, "alvo_pct": 80,
            "marcacao": "aberta nas ofertas do fechamento (venda na de compra, compra na de venda)",
            "nota": (f"Saída recomprando a trava quando ela vale 20% do crédito (80% capturado) ou no vencimento; stop quando custa {STOP_TRAVA:g} vezes o crédito. "
                     "Perda máxima definida (largura menos crédito). Garantia = a perda máxima.")}


def abrir_v2(est, candidatos, dia, travado):
    """Abre no maximo 1 put por dia, so de BOVA11 ou de acao liquida, 1 lote, sem evento no caminho, dentro da garantia e do teto de risco da vertente."""
    if travado:
        return []
    classe, _ = orcamentos()
    garantia_max = classe * FRACAO_GARANTIA_V2
    abertas = [p for p in est["posicoes"] if p["vertente"] == "dividendo_sintetico" and p["estado"] == "aberta"]
    if len(abertas) >= MAX_ABERTAS_V2:
        return []
    teto = limite_risco("dividendo_sintetico")
    for c in candidatos:
        if not c.get("elegivel_livro"):
            continue
        if any(p["ativo"] == c["ativo"] and p["vencimento"] == c["vencimento"] for p in abertas):
            continue
        pos = _pos_v2(c, dia, LOTE)
        if sum(p["garantia_rs"] for p in abertas) + pos["garantia_rs"] > garantia_max:
            continue
        if sum(p["risco_rs"] for p in abertas) + pos["risco_rs"] > teto:
            continue
        return [pos]
    return []


def abrir_v3(est, tabela, regime_bova, dia, travado):
    """Abre no maximo 1 trava por dia, alinhada com a tendencia, delta do vendido 0,15 a 0,25, largura 3% a 6%, 1 lote, dentro do teto de perda maxima da vertente."""
    if travado:
        return []
    abertas = [p for p in est["posicoes"] if p["vertente"] == "travas_bova" and p["estado"] == "aberta"]
    if len(abertas) >= MAX_ABERTAS_V3:
        return []
    teto = limite_risco("travas_bova")
    for c in sorted(tabela, key=lambda r: -(r["retorno_sobre_risco_pct"] or 0)):
        if not c["alinhada_com_a_tendencia"] or not (0.15 <= abs(c["delta_vendido"]) <= 0.25) or not (3.0 <= c["largura_pct"] <= 6.0):
            continue
        if any(p["estrutura"] == c["tipo"] and p["vencimento"] == c["vencimento"] for p in abertas):
            continue
        pos = _pos_v3(c, dia, LOTE)
        if sum(p["risco_rs"] for p in abertas) + pos["risco_rs"] > teto or pos["risco_rs"] > RISCO_POR_TRAVA:
            continue
        return [pos]
    return []


def garantir_sem_call_descoberta(posicoes):
    """Trava de seguranca: toda call vendida de uma posicao precisa ter, na MESMA posicao, uma call comprada de exercicio maior e mesma quantidade (nunca call descoberta)."""
    for p in posicoes:
        for perna in p["pernas"]:
            if perna["lado"] == "venda" and perna["tipo"] == "call":
                if not any(q["lado"] == "compra" and q["tipo"] == "call" and q["exercicio"] > perna["exercicio"] and q["qtd"] >= perna["qtd"] for q in p["pernas"]):
                    raise ValueError(f"call vendida sem cobertura na posicao {p['id']}: o livro nao abre call descoberta")


def atualizar_livros(M, cand_v2, tab_v3, regime_bova, dia, caminho=ARQ_ESTADO, gravar=True):
    """Roda um dia dos livros V2 e V3 com a cadeia M: marca, gere saidas (alvo e stop), liquida vencidas, abre. Idempotente pela data da cadeia."""
    dia = pd.Timestamp(dia)
    est = carregar_estado(dia, caminho)
    ja = est.get("ultima_data") == str(dia.date())
    travado = CS.livro_estourado()
    mudou = False
    if not ja:
        op, sp = M["op"], M["sp"]
        indice = {(r["codigo"], str(pd.Timestamp(r["vencimento"]).date())): r for _, r in op[op["dia"] == dia].iterrows()}
        spot = {r["ativo"]: float(r["fech"]) for _, r in sp[(sp["dia"] == dia) & (sp["fatcot"] == 1)].iterrows()}
        for pos in est["posicoes"]:
            if pos["estado"] == "aberta":
                CS.marcar(pos, indice, spot, dia)
                if pos["estado"] == "aberta":
                    gerir(pos, dia, indice)
                else:
                    taxa = _taxa_exercicio(pos, spot)
                    if taxa:
                        pos["valor_hoje"] = round(pos["valor_hoje"] - taxa, 2)
                        pos["valor_final"] = pos["valor_hoje"]
                        pos["resultado_rs"] = round(pos["valor_hoje"] - pos["custo"], 2)
                    pos["motivo_fechamento"] = "vencimento" + (" (exercida: perda realizada pelo valor de mercado do papel)" if taxa and pos["estrutura"] == "put_coberta_por_caixa" else "")
        novas = abrir_v2(est, cand_v2, dia, travado) + abrir_v3(est, tab_v3, regime_bova, dia, travado)
        garantir_sem_call_descoberta(novas)
        est["posicoes"] += novas
        est["ultima_data"] = str(dia.date())
        mudou = True
    if gravar and mudou:
        gravar_estado(est, caminho)
    return est


# ---------------------------------------------------------------------------------------------------------------- placar
SAIDA_CAMPOS = ("id", "aberta_em", "titulo", "ativo", "estrutura", "pernas", "custo", "valor_hoje", "resultado_rs", "vencimento", "estado", "familia", "qtd", "risco_rs",
                "marcacao", "permanente", "fechada_em", "valor_final", "vantagem_na_abertura_pct", "nota", "origem", "tese_id", "orcamento_rs", "complementado_em",
                "vertente", "garantia_rs", "pior_caso_rs", "stop_multiplo", "alvo_pct", "motivo_fechamento", "pontos_na_abertura")


def _saida(p, dia):
    d = {k: p.get(k) for k in SAIDA_CAMPOS}
    if p.get("vertente") in ("dividendo_sintetico", "travas_bova"):
        d["rendimento_caixa_rs"] = _n(rendimento_caixa(p, dia))
        d["resultado_com_caixa_rs"] = _n(p["resultado_rs"] + rendimento_caixa(p, dia))
    return d


def placar(posicoes, vertente, dia, limite_rs, desde):
    """Placar de uma vertente a partir das posicoes (dicts de `_saida`)."""
    ps = [p for p in posicoes if p.get("vertente") == vertente]
    ab = [p for p in ps if p["estado"] == "aberta"]
    en = [p for p in ps if p["estado"] == "encerrada"]
    aberto = sum(p["resultado_rs"] for p in ab)
    real = sum(p["resultado_rs"] for p in en)
    caixa = sum((p.get("rendimento_caixa_rs") or 0.0) for p in ps)
    risco = sum(p["risco_rs"] for p in ab if not p.get("permanente"))
    ganhos = [p for p in en if p["resultado_rs"] > 0]
    motivos = {}
    for p in en:
        m = (p.get("motivo_fechamento") or "vencimento").split(":")[0].split(" (")[0]
        motivos[m] = motivos.get(m, 0) + 1
    return {"desde": desde, "n_abertas": len(ab), "n_encerradas": len(en), "resultado_aberto_rs": _n(aberto), "resultado_realizado_rs": _n(real),
            "resultado_acumulado_rs": _n(aberto + real), "rendimento_do_caixa_rs": _n(caixa) if vertente != "especulativa" else None,
            "resultado_com_caixa_rs": _n(aberto + real + caixa) if vertente != "especulativa" else None,
            "acerto_pct": _n(len(ganhos) / len(en) * 100, 0) if en else None, "pior_posicao_rs": _n(min([p["resultado_rs"] for p in ps], default=0.0)),
            "fechadas_por": motivos, "risco_em_aberto_rs": _n(risco), "limite_de_risco_rs": _n(limite_rs), "uso_do_limite_pct": _n(risco / limite_rs * 100, 0) if limite_rs else None,
            "nota": "Resultado em R$ pelas ofertas do fechamento, sem imposto e sem corretagem. Sem posições encerradas ainda, o placar mede só marcação a mercado." if not en else
                    "Resultado em R$ pelas ofertas do fechamento, sem imposto e sem corretagem."}


# ---------------------------------------------------------------------------------------------------------------- limites propostos
def limites(vertente, M, cand_v2, tab_v3, res):
    classe, queda = orcamentos()
    teto = limite_risco(vertente)
    base = {"capital_da_classe_rs": _n(classe, 0), "orcamento_de_queda_rs": _n(queda, 0), "teto_de_risco_aberto_rs": _n(teto, 0),
            "fracao_do_orcamento_de_queda_pct": _n(FRACAO_LIMITE[vertente] * 100, 0)}
    if vertente == "especulativa":
        base.update({"perda_maxima_por_estrutura_rs": CS.RISCO_POR_ESTRUTURA, "estruturas_abertas_no_maximo": CS.MAX_ABERTAS, "novas_por_dia": CS.MAX_NOVAS_POR_DIA,
                     "capital_protegido_por_mes_rs": CS.orcamento_mensal(),
                     "texto": (f"Perda máxima = prêmio pago. Teto de R$ {_brl(teto)} em risco aberto ({_pct_fracao("especulativa")}% do orçamento de queda de R$ {_brl(queda)}), até R$ {_brl(CS.RISCO_POR_ESTRUTURA)} por "
                               f"estrutura e {CS.MAX_ABERTAS} abertas; o capital protegido (R$ {_brl(CS.orcamento_mensal())} por mês, 1% do capital da classe) é a base e fica à parte.")})
        return base
    if vertente == "dividendo_sintetico":
        bova = [c for c in cand_v2 if c["ativo"] == "BOVA11" and c["tipo"].startswith("put")]
        r0 = _cfg(res, "v2", "BOVA11 put delta=0.20 M0 F0")
        pior = (r0 or {}).get("fases", {}).get("validacao", {}).get("pior_mes_pct")
        est2 = (res.get("estresse_stop_bova11") or {})
        garantia = classe * FRACAO_GARANTIA_V2
        base.update({"garantia_maxima_rs": _n(garantia, 0), "lotes_por_posicao": 1, "posicoes_abertas_no_maximo": MAX_ABERTAS_V2})
        if bova:
            b = bova[0]
            g = b["garantia_do_lote_rs"]
            base["bova11_garantia_por_lote_rs"] = g
            base["bova11_lotes_que_cabem_na_garantia"] = int(garantia // g) if g else None
            if pior is not None:
                pc = abs(pior) / 100.0 * g
                base["bova11_pior_caso_historico_por_lote_rs"] = _n(pc, 0)
                base["bova11_pior_caso_pct_do_livro"] = _n(pc / CS.CAPITAL * 100, 1)
                base["orcamento_de_queda_que_comportaria_o_pior_caso_rs"] = _n(pc, 0)
                base["orcamento_de_queda_que_comportaria_o_pior_caso_pct"] = _n(pc / CS.CAPITAL * 100, 1)
            a0, a1 = (est2.get("atraso_0_pregoes") or {}).get("perda_mar2020_pct_do_strike"), (est2.get("atraso_1_pregoes") or {}).get("perda_mar2020_pct_do_strike")
            if a0 is not None and a1 is not None:
                base["bova11_perda_no_stop_simulada_por_lote_rs"] = _n(abs(a0) / 100.0 * g, 0)
                base["bova11_perda_no_stop_com_atraso_de_1_pregao_por_lote_rs"] = _n(abs(a1) / 100.0 * g, 0)
            base["bova11_perda_no_stop_pelo_premio_de_hoje_rs"] = _n(b["credito_do_lote_rs"] * (STOP_UNICA - 1.0), 0)
            if pior is not None:
                base["texto"] = (f"Um lote de 100 puts de BOVA11 trava R$ {_brl(g)} de garantia (cabem {base['bova11_lotes_que_cabem_na_garantia']} com R$ {_brl(garantia)} de caixa). "
                                 f"O pior mês de 2020-2023 sem stop foi {_t(abs(pior))}% da garantia, R$ {_brl(base['bova11_pior_caso_historico_por_lote_rs'])} por lote ({_t(base['bova11_pior_caso_pct_do_livro'])}% do livro de R$ {_brl(CS.CAPITAL)}), "
                                 f"acima dos R$ {_brl(queda)} (3%) do orçamento de queda das opções. Com stop em 3 vezes o prêmio a simulação perdeu {_t(abs(a0 or 0))}% (R$ {_brl(base.get('bova11_perda_no_stop_simulada_por_lote_rs') or 0)}), "
                                 f"e {_t(abs(a1 or 0))}% se o stop sair um pregão depois. Para comportar o pior caso sem stop o orçamento de queda das opções teria de ser de uns {_t(base['orcamento_de_queda_que_comportaria_o_pior_caso_pct'], 0)}% do livro "
                                 f"(R$ {_brl(base['orcamento_de_queda_que_comportaria_o_pior_caso_rs'])}); a decisão é do Douglas. Enquanto isso o livro simulado conta como risco a perda do stop (ou 25% do strike nas ações sem stop), com teto de R$ {_brl(teto)}.")
        base.setdefault("texto", f"Pesquisa indisponível para dimensionar o pior caso. Garantia máxima R$ {_brl(garantia)}, teto de risco R$ {_brl(teto)}.")
        return base
    # travas_bova
    base.update({"perda_maxima_por_trava_rs": RISCO_POR_TRAVA, "travas_abertas_no_maximo": MAX_ABERTAS_V3, "lotes_por_trava": 1})
    ex = [c for c in tab_v3 if c["alinhada_com_a_tendencia"]]
    if ex:
        e = ex[0]
        base["exemplo_de_trava_de_hoje"] = {"trava": e["trava"], "vencimento": e["vencimento"], "risco_do_lote_rs": e["risco_do_lote_rs"], "credito_do_lote_rs": e["credito_do_lote_rs"]}
    base["texto"] = (f"Perda máxima definida (largura menos crédito). Teto de R$ {_brl(teto)} em perda máxima somada ({_pct_fracao("travas_bova")}% do orçamento de queda de R$ {_brl(queda)}), até R$ {_brl(RISCO_POR_TRAVA)} por trava, "
                     f"1 lote de 100 opções. Com BOVA11 perto de R$ 200 uma trava de 3% de largura arrisca uns R$ 500 por lote e uma de 4,5%, uns R$ 800: o teto comporta uma trava por vez; para duas ao mesmo tempo seria preciso subir a fatia das travas no orçamento de queda.")
    return base


# ---------------------------------------------------------------------------------------------------------------- texto e evidencia
def evidencia(vertente, res):
    """Etiqueta e numeros por vertente, lidos de resultados_vertentes.json e das familias A0/A1 (assimetrias). 'aprovada' e impossivel hoje (sem prova virgem)."""
    if vertente == "especulativa":
        return {"etiqueta": "medindo",
                "resumo": ("Capital protegido (A0) e straddle barato contra a volatilidade realizada de 252 pregões (A1) passaram descoberta, validação e prova, sem aprovação (Sharpe deflacionado abaixo de 0,95). "
                           "Call comprada isolada onde a opção parece barata não passou como regra; proteger na hora barata (A2), inclinação (A3) e paridade (A4) foram reprovadas. "
                           "Os pontos do ranking vêm dessa evidência; não houve rodada nova de pesquisa para esta vertente."),
                "itens": [{"regra": "capital protegido (calls no dinheiro com 1% do caixa da classe por mês)", "etiqueta": "medindo", "numeros": "excesso +0,96 ponto ao ano sobre o CDI; Sharpe 0,39; nunca perdeu mais que o orçamento"},
                          {"regra": "straddle onde a opção está barata (volatilidade realizada de 252 pregões menos a implícita)", "etiqueta": "medindo", "numeros": "+20% por operação (t 2,24); Sharpe deflacionado 0,20"},
                          {"regra": "gatilho técnico de alta com call no dinheiro (T1/T2)", "etiqueta": "medindo", "numeros": "ver RESULTADO_TESES.md"}]}
    if vertente == "dividendo_sintetico":
        itens = []
        for nome, rot in (("cesta put delta=0.20 M1 F0", "put coberta de ações líquidas, delta 0,20, saída em 80% (referência do mandato)"),
                          ("cesta call delta=0.30 M1 F0", "call coberta, delta 0,30, saída em 80% (referência)"),
                          ("BOVA11 put delta=0.20 M1 F0", "put coberta de BOVA11, delta 0,20, saída em 80%, sem stop"),
                          ("BOVA11 put delta=0.20 M2 F0", "put coberta de BOVA11, delta 0,20, saída em 80% e stop em 3 vezes o prêmio")):
            r = _cfg(res, "v2", nome)
            if not r:
                continue
            f = r["fases"]
            num = []
            for per in ("descoberta", "validacao"):
                if per in f:
                    m = f[per]
                    num.append(f"{'D' if per == 'descoberta' else 'V'}: excesso {_t(m.get('excesso_anual_pct'))}% ao ano, Sharpe {_t(m.get('sharpe'), 2)}, pior mês {_t(m.get('pior_mes_pct'))}%")
            itens.append({"regra": rot, "etiqueta": "medindo" if r.get("passou") else "reprovada no histórico: só medida", "numeros": "; ".join(num)})
        return {"etiqueta": "reprovada no histórico: só medida",
                "resumo": ("Vender put de ações da cesta e vender call coberta, com saída em 80% do prêmio, filtro de volatilidade implícita alta ou filtro de direção, não pagaram o risco contra o CDI em 2012-2023. "
                           "A única família que passou foi a put de BOVA11 COM stop em 3 vezes o prêmio (2020-2023, sem fase de descoberta; Sharpe deflacionado baixo), e ela depende de sair no pregão do gatilho em março de 2020. "
                           "A prova 2024-2026 destas famílias já tinha sido aberta antes: nada aqui foi escolhido com ela, e a confirmação vem da simulação ao vivo."),
                "itens": itens, "grade": f"{res.get('n_v2', 54)} configurações pré-registradas", "estresse_do_stop": res.get("estresse_stop_bova11")}
    itens = []
    for nome in ("trava alta credito delta=0.20 largura=3% M1 F0", "trava alta credito delta=0.20 largura=6% M0 F0", "trava baixa credito delta=0.30 largura=6% M1 F0"):
        r = _cfg(res, "v3", nome)
        if r:
            m = r["fases"]["validacao"]
            itens.append({"regra": nome.replace("F0", "").strip(), "etiqueta": "medindo" if r.get("passou") else "reprovada no histórico: só medida",
                          "numeros": f"V (2020-2023): excesso {_t(m.get('excesso_anual_pct'))}% ao ano com 10% do patrimônio em risco, Sharpe {_t(m.get('sharpe'), 2)}, pior mês {_t(m.get('pior_mes_pct'))}%, {_t(m.get('pct_perda_total_do_risco') or 0)}% das travas perderam o risco todo"})
    deb = [r for r in res.get("v3", []) if "gatilho" in r]
    if deb:
        itens.append({"regra": "travas a débito com gatilho de direção (rompimento de 55 pregões ou média de 200)", "etiqueta": "medindo" if any(r.get("passou") for r in deb) else "reprovada no histórico: só medida",
                      "numeros": "amostra pequena: " + "; ".join(f"{r['config'].split(' (')[0]}: {r['fases']['validacao']['trava'].get('n')} operações, média {_t(r['fases']['validacao']['trava'].get('media_pct') or 0)}%" for r in deb)})
    return {"etiqueta": "reprovada no histórico: só medida",
            "resumo": ("Em 2020-2023, com as ofertas de compra e de venda do fechamento, nenhuma das 72 travas de crédito da grade (alta com put, baixa com call; delta 0,20 e 0,30; largura 3% e 6%; sem saída antecipada, saída em 80%, saída em 80% com stop) "
                       "passou: o crédito é pequeno perto do bid-ask das duas pernas e uma queda forte consome vários meses. As quatro travas a débito com gatilho têm amostra pequena. "
                       "BOVA11 só tem opção líquida desde 2020: não existe fase de descoberta."),
            "itens": itens, "grade": f"{res.get('n_v3', 76)} configurações pré-registradas"}


REGRAS = {
    "especulativa": [
        "Compra de call só com perda máxima igual ao prêmio. O capital protegido (1% do caixa da classe por mês, R$ 300) é a base e vem antes de qualquer outra compra.",
        "O ranking pontua calls no dinheiro: +2 opção barata contra a volatilidade realizada de 252 pregões, +1 percentil da volatilidade implícita abaixo de 40 (-1 se acima de 80), +2 gatilho técnico de alta nos últimos 5 pregões, +1 acima da média de 200, -1 se há resultado trimestral antes do vencimento.",
        f"O livro abre uma call do ranking com {SCORE_MIN_V1} pontos ou mais, uma por dia, até {MAX_ABERTAS_V1_CALL} abertas desta regra, com perda máxima de R$ {_brl(CS.RISCO_POR_ESTRUTURA)} por estrutura. As teses da mesa (livro de teses) entram aqui.",
        "Sem orçamento de queda do livro, nada novo abre. Nada de venda de opção nesta vertente."],
    "dividendo_sintetico": [
        "Vende put coberta por caixa (garantia = o strike inteiro, no caixa da classe que rende CDI) e call coberta (exige o papel em carteira). Nunca call descoberta.",
        "Escolha: delta da put entre 0,15 e 0,30 (alvo 0,20), vencimento com 15+ pregões, 30+ negócios, ofertas dos dois lados e spread até 30%, sem resultado trimestral antes do vencimento. Percentil da volatilidade implícita, distância do suporte de 60 pregões e prazo aparecem como contexto.",
        "Saída: recompra quando a opção vale 20% do que foi recebido (80% do prêmio capturado) ou liquida no vencimento. Stop em 3 vezes o prêmio só em BOVA11 (nas ações a pesquisa mostrou que o stop piorou).",
        "Quando vai contra: (1) rolar para o mês seguinte só com crédito líquido e sem aumentar a perda; (2) stop como acima; (3) aceitar o exercício e lançar call coberta sobre o papel recebido (a roda). Rolagem e roda NÃO foram testadas no histórico; no livro simulado o exercício aparece como perda realizada."],
    "travas_bova": [
        "Travas de crédito com BOVA11 (renda com perda máxima definida): alta com put quando a tendência é de alta ou neutra, baixa com call quando é de baixa ou neutra. Tendência: fechamento contra a média de 200 pregões e inclinação da média de 50.",
        "Escolha: delta da perna vendida 0,15 a 0,25, largura de 3% a 6% do preço, 1 lote, vencimento mensal; ordena por retorno sobre o risco com liquidez de 30+ negócios nas duas pernas.",
        "Saída: recompra quando a trava vale 20% do crédito (80% capturado), stop quando custa 2 vezes o crédito, ou liquida no vencimento. Travas a débito só com gatilho de direção (rompimento de 55 pregões ou média de 200).",
        "Perto do vencimento: fechar antes se o ativo está sobre o strike vendido; o exercício automático das opções dentro do dinheiro cobra emolumento nas duas pernas. Ver o manual quant/docs/travas-bova.md."],
}
TITULOS = {"especulativa": "Especulativa: compra de calls", "dividendo_sintetico": "Dividendo sintético: venda de put e call coberta", "travas_bova": "Travas com BOVA11"}


# ---------------------------------------------------------------------------------------------------------------- bloco para o painel
def _publico(linhas):
    return [{k: v for k, v in r.items() if k not in ("pernas_obj", "_c", "_l")} for r in linhas]


def montar_bloco(M, dia, posicoes_v1, gravar=True, caminho=ARQ_ESTADO):
    """Bloco `vertentes` do JSON da tela + os candidatos para o livro. `posicoes_v1`: posicoes da carteira_simulada (saida de `atualizar`)."""
    dia = pd.Timestamp(dia)
    res = pesquisa()
    s_bova = _tr(M, "BOVA11")
    rg = regime(s_bova) if s_bova is not None else {"direcao": "neutra", "motivos": ["sem série de BOVA11"], "acima_mm200": None}
    r1 = ranking_v1(M, dia)
    r2 = ranking_v2(M, dia)
    t3 = tabela_travas(M, dia, rg)
    est = atualizar_livros(M, r2, t3, rg, dia, caminho=caminho, gravar=gravar)
    pos_v23 = [_saida(p, dia) for p in est["posicoes"]]
    pos_v1 = [dict(p, vertente="especulativa") for p in posicoes_v1]
    out = []
    for nome in NOMES:
        pos = pos_v1 if nome == "especulativa" else [p for p in pos_v23 if p["vertente"] == nome]
        rank = {"especulativa": _publico(r1), "dividendo_sintetico": _publico(r2), "travas_bova": _publico(melhores_travas(t3))}[nome]
        desde = est["desde"] if nome != "especulativa" else (min([p["aberta_em"] for p in pos_v1], default=str(dia.date())))
        lim = limites(nome, M, r2, t3, res)
        b = {"nome": nome, "titulo": TITULOS[nome], "regra": REGRAS[nome], "evidencia": evidencia(nome, res), "ranking_hoje": rank, "posicoes": pos,
             "placar": placar(pos, nome, dia, limite_risco(nome), desde), "limites": lim}
        if nome == "travas_bova":
            b["direcao_hoje"] = rg
            b["regime_bova11"] = rg
        out.append(b)
    return out, r1, est


def aviso_ranking_v1_para_livro(r1):
    """Candidatos da vertente especulativa que o livro pode abrir: pontos >= minimo e cabe no teto por estrutura."""
    return [r for r in r1 if r["pontos"] >= SCORE_MIN_V1 and r["cabe_no_teto_por_estrutura"]]

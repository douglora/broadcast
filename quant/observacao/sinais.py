"""
Os sinais da camada de observacao. Cada um e uma funcao pura sobre as fontes (dict com as series e tabelas do dia) que
devolve {id, grupo, modulo, horizonte, valor, leitura, texto, data_dado, fonte} ou None (sem dado: nunca inventa).

  leitura  +1 = a favor do modulo (bolsa/swing sobe; dolar sobe), -1 = contra, 0 = neutro ou so informativo
  modulo   indice (WIN e BOVA11), swing (acoes), dolar (WDO)
  horizonte  pregoes a frente em que o placar mede o sinal

Os limiares sao declarados aqui, fixos, e vieram do estudo dos gestores (G20, G26) e da literatura; nenhum foi escolhido
olhando resultado [MINHA]. O placar (placar.py) e quem dira, com 60+ leituras, se o sinal tem informacao.
"""
from datetime import date

import time

import numpy as np
import pandas as pd

from quant.dados import calendario_eua as ce
from quant.observacao import fontes

LIMIARES = {
    "ust10_10d_bps": 25.0, "dxy_20d_pct": 2.0, "vix_nivel": 20.0, "vix_10d_pct": 30.0, "brent_10d_pct": 10.0,
    "usdbrl_10d_pct": 3.0, "hy_10d_bps": 40.0, "di2_63d_bps": 50.0, "ntnb35_20d_bps": 30.0,
    "fluxo_5d_rs_bi": 2.0, "revisoes_pct": 55.0, "vol_razao_alta": 1.5, "vol_razao_baixa": 0.8,
    "erp_alto_pp": 5.0, "erp_baixo_pp": 2.0, "cartas_razao": 1.5,
}


def _ultimo(s):
    return (float(s.iloc[-1]), s.index[-1].date()) if len(s) else (None, None)


def _variacao(s, n, pct=True):
    """Variacao dos ultimos n pregoes da serie: em % (pct) ou em pontos."""
    if len(s) <= n:
        return None
    a, b = float(s.iloc[-1 - n]), float(s.iloc[-1])
    return (b / a - 1.0) * 100.0 if pct else b - a


def _sinal(id_, grupo, modulo, horizonte, valor, leitura, texto, data_dado, fonte):
    return {"id": id_, "grupo": grupo, "modulo": modulo, "horizonte": int(horizonte), "valor": None if valor is None else round(float(valor), 4),
            "leitura": int(leitura), "texto": texto, "data_dado": str(data_dado) if data_dado else None, "fonte": fonte}


# ─────────────────────────────────────────────────────────────
# macro
# ─────────────────────────────────────────────────────────────
def ust10_10d(f):
    s = f["series"].get("UST10Y", pd.Series(dtype=float))
    v = _variacao(s, 10, pct=False)
    if v is None:
        return None
    bps = v * 100.0
    leit = -1 if bps >= LIMIARES["ust10_10d_bps"] else (1 if bps <= -LIMIARES["ust10_10d_bps"] else 0)
    return _sinal("ust10_10d", "macro", "indice", 10, bps, leit, f"Treasury de 10 anos {bps:+.0f} pontos-base em 10 pregoes (estresse acima de +{LIMIARES['ust10_10d_bps']:.0f})",
                  s.index[-1].date(), "terminal hist/UST10Y.json")


def dxy_20d(f):
    s = f["series"].get("DXY", pd.Series(dtype=float))
    v = _variacao(s, 20)
    if v is None:
        return None
    leit = 1 if v >= LIMIARES["dxy_20d_pct"] else (-1 if v <= -LIMIARES["dxy_20d_pct"] else 0)
    return _sinal("dxy_20d", "macro", "dolar", 10, v, leit, f"Dolar global (DXY) {v:+.1f}% em 20 pregoes: tendencia do dolar la fora", s.index[-1].date(), "terminal hist/DXY.json")


def vix_regime(f):
    s = f["series"].get("VIX", pd.Series(dtype=float))
    nivel, d = _ultimo(s)
    if nivel is None:
        return None
    v10 = _variacao(s, 10)
    estresse = nivel >= LIMIARES["vix_nivel"] or (v10 is not None and v10 >= LIMIARES["vix_10d_pct"])
    leit = -1 if estresse else (1 if nivel < 15 else 0)
    return _sinal("vix_regime", "macro", "indice", 10, nivel, leit, f"VIX em {nivel:.1f}" + (f" ({v10:+.0f}% em 10 pregoes)" if v10 is not None else ""), d, "terminal hist/VIX.json")


def brent_10d(f):
    s = f["series"].get("BRENT", pd.Series(dtype=float))
    v = _variacao(s, 10)
    if v is None:
        return None
    leit = -1 if abs(v) >= LIMIARES["brent_10d_pct"] else 0                   # choque de petroleo em qualquer direcao = estresse (G20)
    return _sinal("brent_10d", "macro", "indice", 10, v, leit, f"Brent {v:+.1f}% em 10 pregoes", s.index[-1].date(), "terminal hist/BRENT.json")


def usdbrl_10d(f):
    s = f["series"].get("USDBRL", pd.Series(dtype=float))
    v = _variacao(s, 10)
    if v is None:
        return None
    leit = 1 if v >= LIMIARES["usdbrl_10d_pct"] else (-1 if v <= -LIMIARES["usdbrl_10d_pct"] else 0)
    return _sinal("usdbrl_10d", "macro", "dolar", 10, v, leit, f"Dolar/real {v:+.1f}% em 10 pregoes", s.index[-1].date(), "terminal hist/USDBRL.json")


def hy_10d(f):
    s = f.get("hy", pd.Series(dtype=float))
    v = _variacao(s, 10, pct=False)
    if v is None:
        return None
    bps = v * 100.0
    leit = -1 if bps >= LIMIARES["hy_10d_bps"] else (1 if bps <= -LIMIARES["hy_10d_bps"] else 0)
    return _sinal("hy_10d", "macro", "indice", 10, bps, leit, f"Spread high yield dos EUA {bps:+.0f} pontos-base em 10 pregoes", s.index[-1].date(), "terminal rf.json spreads.hy")


def di2_63d(f):
    s = f["series"].get("DI2A", pd.Series(dtype=float))
    v = _variacao(s, 63, pct=False)
    if v is None:
        return None
    bps = v * 100.0
    leit = 1 if bps <= -LIMIARES["di2_63d_bps"] else (-1 if bps >= LIMIARES["di2_63d_bps"] else 0)      # juro caindo favorece bolsa (G8)
    return _sinal("di2_63d", "macro", "swing", 20, bps, leit, f"DI de 2 anos {bps:+.0f} pontos-base em 63 pregoes", s.index[-1].date(), "terminal hist/DI1 (2 anos) / rf.json")


def ntnb35_20d(f):
    s = f["series"].get("TD-IPCA-2035", pd.Series(dtype=float))
    v = _variacao(s, 20, pct=False)
    if v is None:
        return None
    bps = v * 100.0
    leit = 1 if bps <= -LIMIARES["ntnb35_20d_bps"] else (-1 if bps >= LIMIARES["ntnb35_20d_bps"] else 0)
    return _sinal("ntnb35_20d", "fundamento", "swing", 20, bps, leit, f"NTN-B 2035 {bps:+.0f} pontos-base em 20 pregoes (juro real)", s.index[-1].date(), "terminal hist/TD-IPCA-2035.json")


def focus_ipca_1sem(f):
    x = f.get("focus")
    if not x or x.get("mediana") is None or x.get("ha_1_sem") is None:
        return None
    d = float(x["mediana"]) - float(x["ha_1_sem"])
    leit = -1 if d > 0.05 else (1 if d < -0.05 else 0)
    return _sinal("focus_ipca_1sem", "macro", "swing", 10, d, leit, f"Focus IPCA {x.get('ano')}: {x['mediana']:.2f}% ({d:+.2f} ponto na semana)", x.get("focus_data"), "terminal macro.json focus")


def copom_proximo(f):
    data, bps = f.get("copom") or (None, None)
    if not data:
        return None
    return _sinal("copom_proximo", "macro", "swing", 10, bps, 0, f"Proximo Copom em {data}" + (f": {bps:+.0f} pontos-base no preco" if bps is not None else ""), data, "terminal pagina/wirp.json")


def dado_eua_hoje(f):
    hoje = f["hoje"]
    tipo = ce.tipo_do_dia(hoje, f.get("mapa_eua"))
    evs = [e for e in ce.consenso_ff(hoje) if str(e.get("date", ""))[11:16] == "08:30"]
    txt = {"payroll": "payroll (emprego)", "cpi": "inflacao ao consumidor (CPI)", "ppi": "inflacao ao produtor (PPI)", "outro_bls": "dado do BLS",
           "claims": "pedidos de auxilio-desemprego", "nenhum": "sem divulgacao conhecida as 8h30"}[tipo]
    detalhe = "; ".join(f"{e.get('title')}: consenso {e.get('forecast') or '?'} (anterior {e.get('previous') or '?'})" for e in evs[:4])
    return _sinal("dado_eua_hoje", "macro", "dolar", 1, {"payroll": 3, "cpi": 2, "ppi": 1, "outro_bls": 1, "claims": 0.5, "nenhum": 0}[tipo], 0,
                  f"Hoje as 8h30 de NY: {txt}" + (f". {detalhe}" if detalhe else ""), hoje, "quant/dados/calendario_eua.py (BLS + ForexFactory)")


# ─────────────────────────────────────────────────────────────
# micro
# ─────────────────────────────────────────────────────────────
def fluxo_estrangeiro_5d(f):
    s = f.get("fluxo", pd.Series(dtype=float))
    if len(s) < 5:
        return None
    v = float(s.iloc[-5:].sum()) / 1e9
    leit = 1 if v >= LIMIARES["fluxo_5d_rs_bi"] else (-1 if v <= -LIMIARES["fluxo_5d_rs_bi"] else 0)
    return _sinal("fluxo_estrangeiro_5d", "micro", "indice", 10, v, leit, f"Estrangeiro na B3: R$ {v:+.1f} bi em 5 pregoes", s.index[-1].date(), "terminal b3.json fluxo")


def consenso_revisoes_30d(f):
    t = f.get("tabela")
    if t is None or "consenso_lpa_rev_30d_pct" not in getattr(t, "columns", []):
        return None
    r = pd.to_numeric(t["consenso_lpa_rev_30d_pct"], errors="coerce").dropna()
    r = r[(r != 0) & (r.abs() < 100)]
    if len(r) < 20:
        return None
    pct = float((r > 0).mean() * 100.0)
    leit = 1 if pct >= LIMIARES["revisoes_pct"] else (-1 if pct <= 100 - LIMIARES["revisoes_pct"] else 0)
    return _sinal("consenso_revisoes_30d", "micro", "swing", 20, pct, leit, f"{pct:.0f}% dos papeis com revisao de lucro para cima em 30 dias ({len(r)} papeis)",
                  f["hoje"], "terminal consenso (Yahoo)")


# ─────────────────────────────────────────────────────────────
# grafico
# ─────────────────────────────────────────────────────────────
def ibov_mm200(f):
    s = f["series"].get("IBOV", pd.Series(dtype=float))
    if len(s) < 200:
        return None
    mm = float(s.iloc[-200:].mean())
    v = (float(s.iloc[-1]) / mm - 1.0) * 100.0
    return _sinal("ibov_mm200", "grafico", "indice", 20, v, 1 if v > 0 else -1, f"Ibovespa {v:+.1f}% contra a media de 200 pregoes", s.index[-1].date(), "terminal hist/IBOV.json")


def ibov_vol_20_252(f):
    s = f["series"].get("IBOV", pd.Series(dtype=float))
    if len(s) < 253:
        return None
    r = np.log(s).diff().dropna()
    v20, v252 = float(r.iloc[-20:].std() * np.sqrt(252)), float(r.iloc[-252:].std() * np.sqrt(252))
    razao = v20 / v252 if v252 > 0 else None
    if razao is None:
        return None
    leit = -1 if razao >= LIMIARES["vol_razao_alta"] else (1 if razao <= LIMIARES["vol_razao_baixa"] else 0)
    return _sinal("ibov_vol_20_252", "grafico", "indice", 10, razao, leit, f"Volatilidade de 20 pregoes {v20 * 100:.0f}% contra {v252 * 100:.0f}% de 1 ano (razao {razao:.2f})",
                  s.index[-1].date(), "terminal hist/IBOV.json")


# ─────────────────────────────────────────────────────────────
# fundamento
# ─────────────────────────────────────────────────────────────
def erp_tir_safra_mediana(f):
    """Premio mediano da TIR nova (metodo do Safra) sobre a NTN-B 2035. Nasceu em 19/10/2026 no lugar de `erp_tir_mediana` (TIR prudente antiga sobre
    a NTN-B de ~10 anos), com id novo para o placar nao misturar as duas definicoes; os limiares sao os mesmos, declarados antes. So entram as linhas da
    TIR nova (`tir_fonte` 'safra' ou 'analistas'): a reserva antiga fica de fora da mediana, que mudaria de nivel."""
    t = f.get("tabela")
    if t is None or not {"tir_premio_pp", "tir_fonte"} <= set(getattr(t, "columns", [])):
        return None
    p = pd.to_numeric(t.loc[t["tir_fonte"].isin(("safra", "analistas")), "tir_premio_pp"], errors="coerce").dropna()
    if len(p) < 20:
        return None
    med = float(p.median())
    leit = 1 if med >= LIMIARES["erp_alto_pp"] else (-1 if med <= LIMIARES["erp_baixo_pp"] else 0)
    return _sinal("erp_tir_safra_mediana", "fundamento", "swing", 20, med, leit,
                  f"Premio mediano da TIR real (metodo do Safra) sobre a NTN-B 2035: {med:+.1f} pontos ({len(p)} empresas; G26)", f["hoje"], "terminal tir_safra")


def cartas_tom(f):
    x = f.get("cartas")
    if not x or not x.get("docs"):
        return None
    razao = (x["cautela"] + 1.0) / (x["oportunidade"] + 1.0)
    leit = -1 if razao >= LIMIARES["cartas_razao"] else (1 if razao <= 1.0 / LIMIARES["cartas_razao"] else 0)
    return _sinal("cartas_tom", "fundamento", "swing", 20, razao, leit,
                  f"Cartas de gestores desde {x['desde']}: {x['cautela']} paginas de cautela contra {x['oportunidade']} de oportunidade ({x['docs']} documentos)", f["hoje"], "cache/cartas/cartas.sqlite")


def risco_apetite(f):
    """Apetite a risco em 4 bandeiras (0 a 4): S&P 500 subiu em 5 pregoes, credito high yield (HYG) subiu em 5, dolar global
    (DXY) caiu em 5, VIX caiu em 10. Mesmo criterio do `risco_score` de quant/pesquisa/regimes.py (estudo de 12/10/2026):
    na descoberta, a reversao do dado rendeu R$ 130/negocio com 0-1 bandeiras contra R$ 83 com 3-4. So medido."""
    pontos, datas = [], []
    for sim, n, sentido in (("SPY", 5, 1), ("HYG", 5, 1), ("DXY", 5, -1), ("VIX", 10, -1)):
        s = f["series"].get(sim, pd.Series(dtype=float))
        v = _variacao(s, n)
        if v is None:
            return None
        pontos.append(1 if v * sentido > 0 else 0)
        datas.append(s.index[-1].date())
    score = sum(pontos)
    leit = 1 if score >= 3 else (-1 if score <= 1 else 0)
    return _sinal("risco_apetite", "macro", "dolar", 5, score, leit, f"Apetite a risco {score} de 4 (S&P 5d, HYG 5d, DXY 5d, VIX 10d)", max(datas), "terminal hist/SPY,HYG,DXY,VIX")


def usdbrl_vol_regime(f):
    """Vol realizada do dolar (20 pregoes, anualizada) contra a mediana movel de 1 ano: alta ou baixa. Na descoberta
    (12/10/2026) a reversao do dado rendeu R$ 181/negocio com vol alta contra R$ 51 com vol baixa (n 128 e 210). So medido."""
    s = f["series"].get("USDBRL", pd.Series(dtype=float))
    if len(s) < 140:
        return None
    vol = s.pct_change().rolling(20).std() * 100.0 * np.sqrt(252)
    med = vol.rolling(252, min_periods=120).median().shift(1)
    (v, _), (m, _) = _ultimo(vol), _ultimo(med)
    if v is None or m is None or pd.isna(v) or pd.isna(m):
        return None
    alta = v > m
    return _sinal("usdbrl_vol_regime", "micro", "dolar", 10, v, 1 if alta else -1,
                  f"Vol realizada do dolar {v:.1f}% a.a. contra mediana de 1 ano {m:.1f}%: " + ("alta" if alta else "baixa"), s.index[-1].date(), "terminal hist/USDBRL.json")


# ─────────────────────────────────────────────────────────────
# estado do mundo em tempo real (terminal, cache/out/tempo_real/estado.json; "3- pode" relatado em 12/10/2026: so medindo)
# ─────────────────────────────────────────────────────────────
SINAL_USD_TERMINAL = {"payroll": 1, "cpi_mm": 1, "cpi_nucleo_mm": 1, "cpi_12m": 1, "ppi_mm": 1, "varejo_us": 1, "pib_us": 1, "pce_nucleo_mm": 1,
                      "ism_industria": 1, "ism_servicos": 1, "fed_funds": 1, "pedidos_seguro": -1, "desemprego_us": -1}


def _tr(f):
    return f.get("tempo_real") or None


def tr_proximo_evento(f):
    """Proximo evento relevante (importancia 2+) da agenda do terminal, com o consenso quando ha. Informativo: leitura 0."""
    e = _tr(f)
    if not e:
        return None
    prox = [p for p in ((e.get("agenda") or {}).get("proximos") or []) if (p.get("importancia") or 0) >= 2]
    if not prox:
        return None
    p = prox[0]
    faltam_h = (float(p.get("faltam_s") or 0) - (time.time() - float(e.get("gerado_epoch") or 0))) / 3600.0
    cons = p.get("consenso")
    txt = f"Proximo evento: {p.get('evento')} ({p.get('pais')}) em {faltam_h:.1f} h" + (f", consenso {cons}{p.get('unidade') or ''}" if cons is not None else ", sem consenso")
    return _sinal("tr_proximo_evento", "macro", "dolar", 1, faltam_h, 0, txt, str(p.get("quando") or "")[:10], "terminal tempo_real/estado.json (agenda)")


def tr_ultimo_dado(f):
    """O ultimo dado que saiu, com a surpresa em desvios (quando ha historico). Leitura so para dado dos EUA com |surpresa| >= 1
    desvio, no sentido do dolar (payroll acima = dolar mais forte; pedidos de auxilio acima = dolar mais fraco)."""
    e = _tr(f)
    u = ((e or {}).get("agenda") or {}).get("ultimo_que_saiu") if e else None
    if not u:
        return None
    dp, surp = u.get("surpresa_dp"), u.get("surpresa")
    valor = dp if dp is not None else surp
    if valor is None:
        return None
    sinal = SINAL_USD_TERMINAL.get(u.get("indicador"), 0) if u.get("pais") == "US" else 0
    leit = int(np.sign(dp * sinal)) if (sinal and dp is not None and abs(dp) >= 1.0) else 0
    txt = (f"Ultimo dado: {u.get('evento')} ({u.get('pais')}): efetivo {u.get('efetivo')} contra consenso {u.get('consenso')}"
           + (f", surpresa de {dp:+.1f} desvios" if dp is not None else ", surpresa sem historico"))
    return _sinal("tr_ultimo_dado", "macro", "dolar", 1, valor, leit, txt, str(u.get("quando") or "")[:10], "terminal tempo_real/estado.json (agenda)")


def tr_vix_percentil(f):
    """VIX no percentil de 1 ano (regime do terminal): acima de 80 e estresse (contra), abaixo de 20 e calmaria (a favor)."""
    e = _tr(f)
    v = (((e or {}).get("regime") or {}).get("itens") or {}).get("VIX") or {}
    pctl = v.get("pctl_1a")
    if pctl is None:
        return None
    leit = -1 if pctl >= 80 else (1 if pctl <= 20 else 0)
    return _sinal("tr_vix_percentil", "macro", "indice", 5, pctl, leit, f"VIX {v.get('valor')} no percentil {float(pctl):.0f} de 1 ano ({v.get('fonte')})",
                  str(v.get("hora") or "")[:10], "terminal tempo_real/estado.json (regime)")


def tr_feed_mt5(f):
    """Saude do feed do MetaTrader (em rajadas = cotacoes atrasadas; o robo pode reabrir o MetaTrader). Contra quando em rajadas."""
    e = _tr(f)
    mt5 = ((((e or {}).get("saude") or {}).get("motor") or {}).get("mt5") or {})
    if not mt5:
        return None
    raj = bool(mt5.get("em_rajadas"))
    txt = "Feed do MetaTrader " + ("em rajadas: cotacoes atrasadas" if raj else "normal") + f" (ultimo tique ha {mt5.get('idade_ultimo_tique_s')} s)"
    return _sinal("tr_feed_mt5", "micro", "dolar", 0, 1.0 if raj else 0.0, -1 if raj else 0, txt, str(e.get("gerado") or "")[:10], "terminal tempo_real/estado.json (saude)")


def tr_posicao_aberta_wdo(f):
    """Contratos em aberto do mini-dolar (total; a B3 nao abre por participante desde 04/2025) e a variacao do dia. Informativo."""
    e = _tr(f)
    pa = (((e or {}).get("fluxo") or {}).get("posicao_em_aberto_total") or {})
    v = (pa.get("valor") or {}).get("WDO") if isinstance(pa.get("valor"), dict) else None
    if not v or v.get("contratos_em_aberto") is None:
        return None
    var = v.get("variacao_dia")
    txt = f"Mini-dolar: {int(v['contratos_em_aberto']):,} contratos em aberto".replace(",", ".") + (f" ({int(var):+,} no dia)".replace(",", ".") if isinstance(var, (int, float)) else "") + f", pregao {pa.get('pregao')}"
    return _sinal("tr_posicao_aberta_wdo", "micro", "dolar", 5, v["contratos_em_aberto"], 0, txt, str(pa.get("pregao") or "")[:10], "terminal tempo_real/estado.json (fluxo)")


SINAIS = (ust10_10d, dxy_20d, vix_regime, brent_10d, usdbrl_10d, hy_10d, di2_63d, ntnb35_20d, focus_ipca_1sem, copom_proximo, dado_eua_hoje,
          fluxo_estrangeiro_5d, consenso_revisoes_30d, ibov_mm200, ibov_vol_20_252, erp_tir_safra_mediana, cartas_tom, risco_apetite, usdbrl_vol_regime,
          tr_proximo_evento, tr_ultimo_dado, tr_vix_percentil, tr_feed_mt5, tr_posicao_aberta_wdo)


def montar_fontes(hoje=None, com_tabela=True):
    """Le tudo uma vez. Cada pedaco que falha vira serie vazia ou None (o sinal correspondente fica fora)."""
    hoje = pd.Timestamp(hoje or date.today()).date()
    series = {s: fontes.serie(s) for s in ("UST10Y", "DXY", "VIX", "BRENT", "USDBRL", "IBOV", "TD-IPCA-2035", "SPY", "HYG")}
    r = fontes.rf()
    series["DI2A"] = _di2_serie(r)
    return {"hoje": hoje, "series": series, "hy": fontes.spread_serie("hy", r), "focus": fontes.focus(m=fontes.macro()),
            "copom": fontes.copom_proximo(), "fluxo": fontes.fluxo_estrangeiro(), "tabela": fontes.tabela_terminal() if com_tabela else None,
            "cartas": fontes.cartas_tom(hoje), "mapa_eua": ce.tipos_por_dia(), "tempo_real": fontes.tempo_real()}


def _di2_serie(r):
    """Serie da DI de ~2 anos: o contrato DI1 com vencimento mais perto de 2 anos (hist/DI1<cod>.json), que o terminal guarda
    com a taxa de ajuste diaria. Sem ele, serie vazia (o sinal fica fora e a tela diz)."""
    import glob
    import os
    melhor, alvo = None, pd.Timestamp.today() + pd.DateOffset(years=2)
    for arq in glob.glob(os.path.join(fontes.cache_out(), "hist", "DI1*.json")):
        d = fontes._json(arq) or {}
        try:
            venc = pd.Timestamp(d.get("venc"))
        except (TypeError, ValueError):
            continue
        dist = abs((venc - alvo).days)
        if dist > 400:                                   # so contratos a ate 13 meses do alvo de 2 anos
            continue
        n = len(d.get("t") or [])
        chave = (-(n >= 70), dist)                       # prefere quem tem historia para 63 pregoes; entre esses, o mais perto do alvo
        if melhor is None or chave < melhor[0]:
            melhor = (chave, os.path.basename(arq)[:-5])
    return fontes.serie(melhor[1]) if melhor else pd.Series(dtype=float)


def calcular(f):
    fora, faltam = [], []
    for fn in SINAIS:
        try:
            s = fn(f)
        except Exception as e:                       # um sinal estragado nao derruba os outros
            faltam.append(f"{fn.__name__}: {type(e).__name__}: {e}")
            continue
        if s is None:
            faltam.append(fn.__name__)
        else:
            fora.append(s)
    return fora, faltam

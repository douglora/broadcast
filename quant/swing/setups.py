"""
Setups de swing trade de 2 a 10 pregoes: as familias e as 39 variantes pre-registradas em
`quant/saida/pesquisa_swing/PRE_REGISTRO.md`. Cada setup devolve uma matriz booleana (dia x papel) com o sinal no FECHAMENTO do dia
(so dado ate esse dia) e os parametros de saida (stop e alvo em ATR, prazo). A entrada e na abertura do dia seguinte (ver `simulador.py`).

Funcoes puras sobre o `Painel` de `dados.py`. Nenhum parametro aqui foi escolhido olhando resultado: mudar um e uma variante nova.
"""
import warnings

import numpy as np
import pandas as pd

ATR_JANELA = 14
OVERLAYS = ("S0", "S1", "S2")        # nenhuma, metade de cima do ranking multifatorial, Ibovespa acima da media de 200

# nucleos: familia -> {id: parametros}
NUCLEOS = {
    "a_pullback": {
        "A1": dict(drop_n=3, drop_atr=2.0, stop_atr=1.5, alvo_atr=2.0, prazo=5),
        "A2": dict(drop_n=3, drop_atr=3.0, stop_atr=2.0, alvo_atr=3.0, prazo=10)},
    "b_reversao": {
        "B1": dict(drop_n=4, drop_atr=3.0, stop_atr=2.0, alvo_atr=2.5, prazo=5),
        "B2": dict(drop_n=4, drop_atr=4.5, stop_atr=3.0, alvo_atr=4.0, prazo=10)},
    "c_rompimento": {
        "C1": dict(vol_x=1.5, stop_atr=2.0, alvo_atr=3.0, prazo=10),
        "C2": dict(vol_x=2.0, stop_atr=2.5, alvo_atr=5.0, prazo=10)},
    "d_resultado": {
        "D1": dict(reacao_min=0.04, vol_x=1.5, stop_atr=2.0, alvo_atr=4.0, prazo=10),
        "D2": dict(lucro_yoy_min=0.20, stop_atr=2.0, alvo_atr=4.0, prazo=10)},
    "e_forca_relativa": {
        "E1": dict(n=10, stop_atr=2.0, alvo_atr=3.0, prazo=10),
        "E2": dict(n=20, stop_atr=2.0, alvo_atr=3.0, prazo=10)},
    "f1_gap": {
        "F1": dict(gap=0.03, vol_x=2.0, stop_atr=2.0, alvo_atr=3.0, prazo=5),
        "F2": dict(gap=0.05, vol_x=2.0, stop_atr=2.5, alvo_atr=4.0, prazo=10)},
    "f2_virada_de_mes": {
        "G1": dict(stop_atr=3.0, alvo_atr=None, prazo=4)},
}
ROTULOS = {
    "a_pullback": "pullback em tendência de alta", "b_reversao": "reversão após queda forte sem médias",
    "c_rompimento": "rompimento da máxima de 20 pregões com volume", "d_resultado": "deriva pós-resultado",
    "e_forca_relativa": "força relativa contra o Ibovespa", "f1_gap": "continuação de gap de alta com volume",
    "f2_virada_de_mes": "virada de mês"}


def variantes():
    """As 39 variantes: lista de dicts (id, familia, nucleo, overlay, params)."""
    out = []
    for fam, nucs in NUCLEOS.items():
        for nid, par in nucs.items():
            for ov in OVERLAYS:
                out.append({"id": f"{nid}.{ov}", "familia": fam, "nucleo": nid, "overlay": ov, "params": dict(par)})
    return out


# ─────────────────────────────────────────────────────────────
# Indicadores (todos usam so dado ate o proprio dia, salvo quando o nome diz "anterior")
# ─────────────────────────────────────────────────────────────
def _df(a, p):
    return pd.DataFrame(a, index=p.datas, columns=p.tickers)


def indicadores(p):
    """Dict de matrizes numpy (dia x papel) com ATR, medias, maxima e volume anteriores, quedas, gap e posicao na barra."""
    O, H, L, C, V = (_df(x, p) for x in (p.O, p.H, p.L, p.C, p.V))
    cprev = C.shift(1)
    a1, a2, a3 = (H - L).to_numpy(), (H - cprev).abs().to_numpy(), (L - cprev).abs().to_numpy()
    tr = np.fmax(np.fmax(a1, a2), a3)                           # fmax ignora o NaN do 1o dia; barra sem H ou L fica NaN
    tr[~np.isfinite(a1)] = np.nan
    atr = pd.DataFrame(tr, index=p.datas, columns=p.tickers).rolling(ATR_JANELA, min_periods=ATR_JANELA).mean()
    ind = {"atr": atr.to_numpy(), "sma20": C.rolling(20, min_periods=20).mean().to_numpy(),
           "sma50": C.rolling(50, min_periods=50).mean().to_numpy(), "sma200": C.rolling(200, min_periods=200).mean().to_numpy(),
           "hi20_ant": H.rolling(20, min_periods=20).max().shift(1).to_numpy(),
           "vol_ant": V.rolling(20, min_periods=20).mean().shift(1).to_numpy(),
           "gap": (O / cprev - 1.0).to_numpy(),
           "pos_barra": ((C - L) / (H - L).where(H > L)).to_numpy()}
    for n in (3, 4):
        ind[f"drop{n}"] = ((C.shift(n) - C) / atr).to_numpy()
    ib = pd.Series(p.ibov_c, index=p.datas)
    for n in (10, 20):
        ind[f"ret{n}"] = (C / C.shift(n) - 1.0).to_numpy()
        rs = (C / C.shift(n) - 1.0).sub(ib / ib.shift(n) - 1.0, axis=0)
        ind[f"rs{n}"] = rs.to_numpy()
    ind["ruim_ant"] = (_df(p.ruim.astype(float), p).rolling(25, min_periods=1).max() > 0).to_numpy()
    ind["completo"] = np.isfinite(p.O) & np.isfinite(p.H) & np.isfinite(p.L) & np.isfinite(p.C)
    return ind


def _base(p, ind, overlay):
    """Mascara comum: universo, sem dado ruim, ATR valido, e a sobreposicao."""
    m = p.uni & ~ind["ruim_ant"] & ind["completo"] & np.isfinite(ind["atr"]) & (ind["atr"] > 0)
    if overlay == "S1":
        m = m & p.top
    elif overlay == "S2":
        m = m & p.ibov_ok[:, None]
    return m


def _cond(a):
    return np.nan_to_num(a, nan=0.0).astype(bool) if a.dtype != bool else a


def _virada_de_mes(p):
    """Dia do 3o pregao antes do ultimo do mes (fechamento)."""
    d = pd.Series(np.arange(len(p.datas)), index=p.datas)
    ultimos = d.groupby([p.datas.year, p.datas.month]).max().to_numpy()
    alvo = ultimos - 2
    m = np.zeros(len(p.datas), dtype=bool)
    m[alvo[(alvo >= 0) & (alvo < len(p.datas))]] = True
    return m


def sinal_resultado(p, ind, nucleo_id, par, eventos):
    """Familia d: sinal no fechamento de E+1. `eventos`: DataFrame(ticker, i_evento, lucro_yoy) de `eventos_resultado`."""
    sig = np.zeros(p.O.shape, dtype=bool)
    if eventos is None or len(eventos) == 0:
        return sig
    C, V = p.C, p.V
    for r in eventos.itertuples():
        j, e = p.tickers.index(r.ticker) if r.ticker in p.tickers else -1, int(r.i_evento)
        t = e + 1
        if j < 0 or e < 1 or t >= len(p.datas):
            continue
        c0, c1 = C[e - 1, j], C[t, j]
        if not (np.isfinite(c0) and np.isfinite(c1)) or c0 <= 0:
            continue
        r2 = c1 / c0 - 1.0
        if nucleo_id == "D1":
            va = ind["vol_ant"][e, j]  # media de 20 dias anterior a E
            ve = np.nanmean(V[e:t + 1, j])
            ok = r2 >= par["reacao_min"] and np.isfinite(va) and va > 0 and ve >= par["vol_x"] * va
        else:
            y = getattr(r, "lucro_yoy", np.nan)
            ok = r2 > 0 and np.isfinite(y) and y >= par["lucro_yoy_min"]
        if ok:
            sig[t, j] = True
    return sig


def sinais(p, ind, v, eventos=None):
    """Matriz booleana (dia x papel) do sinal da variante `v` (dict de `variantes()`), no fechamento do dia."""
    fam, nid, par = v["familia"], v["nucleo"], v["params"]
    base = _base(p, ind, v["overlay"])
    C = p.C
    if fam == "a_pullback":
        tendencia = (C > ind["sma50"]) & (ind["sma50"] > ind["sma200"])
        s = tendencia & (ind[f"drop{par['drop_n']}"] >= par["drop_atr"])
    elif fam == "b_reversao":
        s = (C < ind["sma20"]) & (C < ind["sma50"]) & (ind[f"drop{par['drop_n']}"] >= par["drop_atr"])
    elif fam == "c_rompimento":
        s = (C > ind["hi20_ant"]) & (C > ind["sma50"]) & (p.V >= par["vol_x"] * ind["vol_ant"])
    elif fam == "d_resultado":
        s = sinal_resultado(p, ind, nid, par, eventos)
    elif fam == "e_forca_relativa":
        rs = ind[f"rs{par['n']}"]
        rs_uni = np.where(p.uni, rs, np.nan)
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)                 # dia sem nenhum papel no universo: corte NaN, sem sinal
            corte = np.nanquantile(rs_uni, 0.9, axis=1)
        s = (rs >= corte[:, None]) & (ind[f"ret{par['n']}"] > 0) & (C > ind["sma20"])
    elif fam == "f1_gap":
        s = (ind["gap"] >= par["gap"]) & (C >= p.O) & (p.V >= par["vol_x"] * ind["vol_ant"]) & (ind["pos_barra"] >= 0.70)
    elif fam == "f2_virada_de_mes":
        s = _virada_de_mes(p)[:, None] & (C > ind["sma200"])
    else:
        raise ValueError(f"familia desconhecida: {fam!r}")
    return _cond(s) & base


# ─────────────────────────────────────────────────────────────
# Eventos de resultado (familia d)
# ─────────────────────────────────────────────────────────────
def eventos_resultado(p, arq_fundamentos=None, anos=None):
    """DataFrame(ticker, i_evento, dt_receb, lucro_yoy): a primeira entrega de cada ITR/DFP na CVM (DT_RECEB), no primeiro pregao >= a data.
    lucro_yoy = lucro liquido dos 12 meses contra o dos 12 meses terminados um ano antes (so quando os dois sao positivos); vem do painel de
    fundamentos point-in-time (TTM na primeira vez em que o trimestre aparece)."""
    from quant.dados import cvm_fundamentos as cf
    anos = anos or range(int(p.datas[0].year) - 1, int(p.datas[-1].year) + 1)
    d = cf.carregar(list(anos), colunas=["cd_cvm", "dt_refer", "dt_receb"])
    if d is None or len(d) == 0:
        return pd.DataFrame(columns=["ticker", "i_evento", "dt_receb", "lucro_yoy"])
    d = d.dropna(subset=["dt_receb", "dt_refer"]).drop_duplicates()
    ev = d.groupby(["cd_cvm", "dt_refer"], as_index=False)["dt_receb"].min()
    ev = ev[(ev["dt_receb"] >= p.datas[0]) & (ev["dt_receb"] <= p.datas[-1])]
    # lucro TTM e variacao contra um ano antes
    yoy = pd.DataFrame(columns=["cd_cvm", "dt_refer", "lucro_yoy"])
    arq = arq_fundamentos
    if arq and __import__("os").path.exists(arq):
        f = pd.read_parquet(arq, columns=["data", "cd_cvm", "dt_refer", "lucro_liquido"]).dropna(subset=["dt_refer", "lucro_liquido"])
        f = f.sort_values("data").drop_duplicates(["cd_cvm", "dt_refer"], keep="first")
        f["dt_ant"] = f["dt_refer"] - pd.DateOffset(years=1)
        ant = f[["cd_cvm", "dt_refer", "lucro_liquido"]].rename(columns={"dt_refer": "dt_ant", "lucro_liquido": "ll_ant"})
        j = f.merge(ant, on=["cd_cvm", "dt_ant"], how="left")
        j["lucro_yoy"] = np.where((j["lucro_liquido"] > 0) & (j["ll_ant"] > 0), j["lucro_liquido"] / j["ll_ant"] - 1.0, np.nan)
        yoy = j[["cd_cvm", "dt_refer", "lucro_yoy"]]
    ev = ev.merge(yoy, on=["cd_cvm", "dt_refer"], how="left")
    por_cd = {}
    for t, c in p.cd_cvm.items():
        por_cd.setdefault(c, []).append(t)
    pos = np.searchsorted(np.asarray(p.datas, dtype="datetime64[ns]"), np.asarray(ev["dt_receb"], dtype="datetime64[ns]"), side="left")
    linhas = []
    for r, i in zip(ev.itertuples(), pos):
        for t in por_cd.get(int(r.cd_cvm), []):
            if i < len(p.datas):
                linhas.append((t, int(i), r.dt_receb, r.lucro_yoy))
    return pd.DataFrame(linhas, columns=["ticker", "i_evento", "dt_receb", "lucro_yoy"])

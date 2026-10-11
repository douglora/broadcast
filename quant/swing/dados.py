"""
Painel diario para os swing trades: precos ajustados (abertura, maxima, minima, fechamento), universo point-in-time por dia,
metade de cima do ranking multifatorial, Ibovespa (BOVA11) acima da media de 200 e CDI. Um so lugar, usado pela pesquisa e pelo robo.

AJUSTE. As cotacoes da B3 nao vem ajustadas. O fator de retorno total do projeto (`eventos.retorno_total_limpo`, JCP liquido) vira um
fator por papel e dia: fator = fator_acum / (fechamento por acao); preco ajustado = preco por acao x fator. Como o mesmo fator vale para
abertura, maxima, minima e fechamento do dia, as razoes ENTRE dias (a conta de uma operacao de swing) saem certas. Dia cujo retorno a
limpeza invalidou ("salto sem evento", buraco de mais de 60 dias) fica marcado em `ruim`: operacao que o toca na janela de 25 pregoes
antes do sinal ou na de saida e descartada.

POINT-IN-TIME. O universo e o do ultimo fim de mes ate o dia (`universo_pit`), com giro medio de 21 dias >= ADTV_MIN. A metade de cima do
ranking multifatorial usa o score do painel de sinais no ultimo fim de mes ate o dia (so existe de 2011-01 em diante).
"""
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.comum import DIR_SAIDA

ADTV_MIN = 5_000_000.0           # giro medio de 21 dias: entra e sai em dias, papel mais fino so custa
TICKER_IBOV = "BOVA11"
ARQ_SINAIS_PESQUISA = os.path.join(DIR_SAIDA, "pesquisa_carteira", "sinais_2011_2026.parquet")
JANELA_RUIM = 25


@dataclass
class Painel:
    datas: pd.DatetimeIndex
    tickers: list
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    V: np.ndarray                 # financeiro do dia (R$)
    ruim: np.ndarray              # retorno invalidado pela limpeza
    uni: np.ndarray               # no universo (giro >= ADTV_MIN) no ultimo fim de mes ate o dia
    adtv: np.ndarray              # giro medio de 21 dias do ultimo fim de mes ate o dia
    top: np.ndarray               # metade de cima do ranking multifatorial (False quando indisponivel)
    ibov_ok: np.ndarray           # BOVA11 ajustado acima da media de 200 pregoes (por dia)
    ibov_c: np.ndarray            # BOVA11 ajustado (fechamento)
    cdi: np.ndarray               # CDI diario (fracao) alinhado as datas
    preco_cru: np.ndarray = None  # fechamento nao ajustado por acao (para lote/fracionario)
    cd_cvm: dict = field(default_factory=dict)

    def idx(self, ticker):
        return self.tickers.index(ticker)

    def recorte(self, ate):
        """Painel cortado em `ate` (inclusive). A pesquisa de descoberta/validacao nunca ve 2022 em diante."""
        n = int((self.datas <= pd.Timestamp(ate)).sum())
        cortes = {k: (v[:n] if isinstance(v, np.ndarray) and v.ndim >= 1 and len(v) == len(self.datas) else v) for k, v in self.__dict__.items()}
        cortes["datas"] = self.datas[:n]
        return Painel(**cortes)


def _mapa_diario(datas_ref, datas_mes):
    """Para cada dia, o indice do ultimo fim de mes <= dia (-1 se nao houver)."""
    return np.searchsorted(np.asarray(datas_mes, dtype="datetime64[ns]"), np.asarray(datas_ref, dtype="datetime64[ns]"), side="right") - 1


def _expandir(matriz_mes, datas, datas_mes):
    pos = _mapa_diario(datas, datas_mes)
    out = np.zeros((len(datas), matriz_mes.shape[1]), dtype=matriz_mes.dtype)
    ok = pos >= 0
    out[ok] = matriz_mes[pos[ok]]
    return out


def _ibov(datas, bova):
    """Nivel do 'Ibovespa' por dia: mercado NEFIN (Rm-Rf + Rf composto, 2001 em diante) e, depois da ultima data dele, o
    retorno diario do BOVA11 (que so existe no banco desde 2019-08). O COTAHIST do projeto nao traz o BOVA11 antes de 2019-08
    nem o indice em si; o NEFIN e a carteira de mercado ponderada por valor, correlacao ~0,99 com o Ibovespa."""
    from quant.dados import nefin
    try:
        f = nefin.carregar_fatores()
        nivel = (1.0 + f["Rm_minus_Rf"] + f["Risk_Free"]).cumprod()
    except Exception:                                           # pragma: no cover (sem snapshot do NEFIN)
        nivel = pd.Series(dtype=float)
    nivel = nivel.reindex(datas)
    ultimo = nivel.last_valid_index()
    if ultimo is not None and ultimo < datas[-1]:
        r = bova.pct_change().where(bova.index > ultimo)
        ext = (1.0 + r.fillna(0.0)).cumprod() * float(nivel.loc[ultimo])
        nivel = nivel.where(nivel.index <= ultimo, ext)
    elif ultimo is None:
        nivel = bova
    return nivel.ffill()


def montar(ano_ini=2009, ano_fim=None, ate=None, arq_sinais=None, adtv_min=ADTV_MIN):
    """Painel completo. `ate`: corta as cotacoes ANTES de qualquer conta (a descoberta nunca carrega 2022 em diante)."""
    from quant import universo as uni_mod
    from quant.dados import cdi as cdi_mod, cotahist, eventos, identidade
    ano_fim = ano_fim or (pd.Timestamp(ate).year if ate else pd.Timestamp.now().year)
    cot = cotahist.carregar(ano_ini, ano_fim)
    if ate:
        cot = cot[pd.to_datetime(cot["data"]) <= pd.Timestamp(ate)]
    av_padrao = cotahist.acoes_a_vista(cot, apenas_lote_padrao=True)
    ident = identidade.carregar_identidade()
    u = uni_mod.universo_pit(av_padrao, identidade=ident)
    u["data"] = pd.to_datetime(u["data"])
    u_ok = u[u["adtv21"] >= adtv_min]
    tickers = sorted(set(u_ok["ticker"]))
    serie = cotahist.acoes_a_vista(cot, apenas_lote_padrao=False)
    ibov = cot[(cot["ticker"] == TICKER_IBOV) & (cot["tpmerc"] == "010")]
    serie = pd.concat([serie[serie["ticker"].isin(tickers)], ibov], ignore_index=True)
    serie = serie.drop_duplicates(["ticker", "data"], keep="last").copy()
    serie["data"] = pd.to_datetime(serie["data"])
    rt = eventos.retorno_total_limpo(serie[["ticker", "data", "fec", "fatcot"]], eventos.carregar_eventos(), jcp_liquido=True)
    rt["data"] = pd.to_datetime(rt["data"])
    d = serie.merge(rt[["ticker", "data", "ret_total", "fator_acum"]], on=["ticker", "data"], how="left")
    d["data"] = pd.to_datetime(d["data"])
    fc = d["fatcot"].where(d["fatcot"] > 0, 1.0)
    pps = d["fec"] / fc
    fator = d["fator_acum"] / pps
    for c in ("abe", "max", "min", "fec"):
        d[c + "_aj"] = (d[c] / fc) * fator
        d.loc[d[c] <= 0, c + "_aj"] = np.nan
    d = d.sort_values(["ticker", "data"])
    primeiro = ~d.duplicated("ticker", keep="first")
    d["ruim"] = d["ret_total"].isna() & ~primeiro
    d["preco_cru"] = pps
    cols = tickers + [TICKER_IBOV]
    datas = pd.DatetimeIndex(sorted(d["data"].unique()))

    def pv(c, fill=np.nan):
        return d.pivot(index="data", columns="ticker", values=c).reindex(index=datas, columns=cols).to_numpy(dtype=float) if c != "ruim" else \
            d.pivot(index="data", columns="ticker", values=c).reindex(index=datas, columns=cols).fillna(False).to_numpy(dtype=bool)
    O, H, L, C = pv("abe_aj"), pv("max_aj"), pv("min_aj"), pv("fec_aj")
    V, ruim, cru = pv("volume"), pv("ruim"), pv("preco_cru")
    # universo e giro por dia (ultimo fim de mes ate o dia)
    meses = pd.DatetimeIndex(sorted(u["data"].unique()))
    adtv_m = u.pivot(index="data", columns="ticker", values="adtv21").reindex(index=meses, columns=cols).to_numpy(dtype=float)
    adtv = _expandir(np.nan_to_num(adtv_m, nan=0.0), datas, meses)
    uni = adtv >= adtv_min
    uni[:, -1] = False                                          # BOVA11 e referencia, nao e candidato
    # metade de cima do ranking multifatorial
    top = np.zeros_like(uni)
    arq = arq_sinais or ARQ_SINAIS_PESQUISA
    if os.path.exists(arq):
        s = pd.read_parquet(arq, columns=["data", "ticker", "score"])
        s["data"] = pd.to_datetime(s["data"])
        if ate:
            s = s[s["data"] <= pd.Timestamp(ate)]
        sc = s.pivot(index="data", columns="ticker", values="score").reindex(columns=cols)
        med = sc.median(axis=1)
        top_m = sc.ge(med, axis=0).fillna(False).to_numpy(dtype=bool)
        top = _expandir(top_m, datas, sc.index)
    # Ibovespa (proxy): mercado NEFIN em retorno total, estendido com BOVA11 depois da ultima data do NEFIN
    ib = _ibov(datas, pd.Series(C[:, -1], index=datas))
    ibov_ok = (ib > ib.rolling(200, min_periods=200).mean()).fillna(False).to_numpy(dtype=bool)
    taxa = cdi_mod.carregar(permitir_rede=False)
    cdi = taxa.reindex(datas).fillna(0.0).to_numpy(dtype=float) if taxa is not None else np.zeros(len(datas))
    cd = {}
    try:
        from quant import sinais as sg
        m = sg.mapear_empresa(u_ok, ident)[["ticker", "cd_cvm"]].dropna().drop_duplicates("ticker")
        cd = {r.ticker: int(r.cd_cvm) for r in m.itertuples()}
    except Exception:                                           # pragma: no cover
        cd = {}
    return Painel(datas=datas, tickers=cols, O=O, H=H, L=L, C=C, V=V, ruim=ruim, uni=uni, adtv=adtv, top=top, ibov_ok=ibov_ok,
                  ibov_c=ib.to_numpy(dtype=float), cdi=cdi, preco_cru=cru, cd_cvm=cd)

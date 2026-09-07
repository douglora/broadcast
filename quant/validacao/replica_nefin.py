"""
Gate da fase 1: replicar os fatores WML e HML do NEFIN com a metodologia oficial.

Por que existe: se os nossos precos, a identidade (uma classe por empresa) e o retorno
total estiverem errados, o backtest de momentum vai "descobrir" um premio que nao existe
(ou perder o que existe). O NEFIN publica WML e HML diarios desde 2001 com regras
simples e documentadas; se a nossa base reproduz esses fatores (correlacao mensal >= 0,90
e media anual dentro de +-3 p.p.), o pipeline de dados esta certo. Se nao reproduz, o
dado esta errado e NAO se segue para a fase 2 (README: "bloqueio duro").

Metodologia NEFIN (site, "Methodology"):
  elegiveis no ano t: (1) a acao mais negociada da empresa (maior volume medio em t-1);
    (2) negociada em mais de 80% dos pregoes de t-1 com volume > R$ 500 mil no dia;
    (3) listada antes de dezembro de t-1;
  WML: todo mes t as elegiveis sao ordenadas pelo retorno acumulado entre os meses t-12 e
    t-2 (o ultimo mes e pulado) em 3 terciles; carteiras equal-weighted; WML = tercil
    alto - tercil baixo; rebalance mensal; retornos diarios;
  HML: em janeiro de t, ordenadas pelo book-to-market (PL de dezembro de t-1 / valor de
    mercado em dezembro de t-1) em 3 terciles; HML = alto - baixo; rebalance anual.

Suposicoes desta replica (validar quando houver rede e COTAHIST):
  - "equal-weighted, retornos diarios" foi lido como media simples dos retornos diarios dos
    membros (rebalanceado diariamente), nao buy-and-hold dentro do mes; a diferenca e de
    segunda ordem na correlacao mensal;
  - "volume > R$ 500 mil por dia" foi lido como: fracao dos pregoes de t-1 em que o papel
    negociou com volume > 500 mil deve superar 80% (um unico criterio); a leitura
    alternativa (presenca > 80% E volume medio > 500 mil) esta em elegiveis_nefin(criterio=);
  - o HML do NEFIN usa o PL de dezembro de t-1 em janeiro de t, antes da DFP ser publicada
    (nao e point-in-time). A replica segue o NEFIN de proposito - e um teste de dados, nao
    um sinal negociavel; book_equity deve trazer o PL de referencia de dezembro;
  - o ranking mensal usa apenas retornos ate o fim de t-2 e a elegibilidade usa apenas o
    ano t-1: nao ha look-ahead (test_replica_nefin prova isso alterando dados apos t);
  - a serie mensal e o composto dos retornos diarios do fator no mes, igual a nefin.mensal;
  - so ACOES e UNITS entram no pool (universo.classificar_papel por sufixo/ISIN/CODBDI):
    sem esse filtro BOVA11, BDRs e FIIs - que passam folgados no volume - viravam
    "empresas" do WML; o fracionario (ticker com letra no fim) tambem fica de fora;
  - retornos_de_cotacoes usa o ultimo fechamento conhecido: um dia sem negocio da NaN
    (o papel sai da media naquele dia) e o movimento acumulado aparece no dia em que
    volta a negociar; fechamento <= 0 e tratado como ausente;
  - terciles: n nao divisivel por 3 -> o excedente vai para o tercil do meio (n = 3k+1)
    ou para os extremos (n = 3k+2), simetrico; o NEFIN usa pontos de corte de 33/66%.

O gate REAL so roda com o COTAHIST baixado (bvmf.bmfbovespa.com.br, bloqueado nesta
maquina) e, idealmente, com o retorno total de eventos.py em vez do fechamento cru:
    python -m quant.dados.cotahist --anos 2006-2026
    python -m quant.validacao.replica_nefin --ini 2008 --fim 2026
"""
import argparse
import json
import re
import sys

import numpy as np
import pandas as pd

from quant.universo import classificar_papel

VOLUME_MIN_DIA = 500_000.0
PRESENCA_MIN = 0.80
CORR_MIN = 0.90
DIF_MAX_PP = 3.0
TIPOS_NEFIN = ("acao", "unit")
_TICKER_LOTE = re.compile(r"^[A-Z0-9]{4}\d{1,2}$")     # sem a letra do fracionario (PETR4F)


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def _empresa_padrao(ticker):
    return str(ticker).strip().upper()[:4]


def _cotacoes_limpas(cotacoes):
    fec = pd.to_numeric(cotacoes["fec"], errors="coerce")
    c = pd.DataFrame({
        "data": pd.to_datetime(cotacoes["data"]),
        "ticker": cotacoes["ticker"].astype(str).str.strip().str.upper(),
        "fec": fec.where(fec > 0),                      # fechamento 0 no COTAHIST = sem preco
        "volume": pd.to_numeric(cotacoes["volume"], errors="coerce").fillna(0.0),
        "isin": cotacoes["isin"].astype(str).str.strip().str.upper() if "isin" in cotacoes else "",
        "codbdi": cotacoes["codbdi"].astype(str).str.strip().str.zfill(2) if "codbdi" in cotacoes else "",
    })
    if "negocios" in cotacoes:
        c["negocios"] = pd.to_numeric(cotacoes["negocios"], errors="coerce").fillna(0)
    else:
        c["negocios"] = (c["volume"] > 0).astype(int)
    return c.sort_values(["data", "ticker"]).drop_duplicates(["data", "ticker"], keep="last")


def retornos_de_cotacoes(cotacoes):
    """DataFrame data x ticker de retorno de fechamento (fec_t / fec_{t-1} - 1), SEM proventos.
    Serve para testes e para uma primeira passada; o gate real deve usar eventos.retorno_total."""
    c = _cotacoes_limpas(cotacoes)
    fec = c.pivot(index="data", columns="ticker", values="fec").sort_index()
    ultimo = fec.ffill()
    ret = ultimo / ultimo.shift(1) - 1
    return ret.where(fec.notna())       # dia sem negocio: NaN; o gap acumula no dia da volta


def terciles(valores):
    """Series (ticker -> valor) -> dict {'baixo': [...], 'medio': [...], 'alto': [...]}.

    Ordem crescente; n = 3k: k cada; n = 3k+1: o extra vai para o meio; n = 3k+2: um extra
    em cada extremo. Assim alto e baixo tem sempre o MESMO tamanho (WML/HML nao ficam com
    uma perna maior). Empates mantem a ordem original (mergesort)."""
    v = valores.dropna().sort_values(kind="mergesort")
    n = len(v)
    if n < 3:
        return {"baixo": [], "medio": [], "alto": []}
    k, resto = divmod(n, 3)
    n_ext = k + (1 if resto == 2 else 0)
    idx = list(v.index)
    return {"baixo": idx[:n_ext], "medio": idx[n_ext:n - n_ext], "alto": idx[n - n_ext:]}


def _apenas_acoes(c, tipos):
    """Mantem so tickers de lote padrao cujo tipo (universo.classificar_papel, com o ultimo
    ISIN/CODBDI visto) esta em `tipos`. None em tipos desliga o filtro."""
    if tipos is None:
        return c
    ult = c.sort_values("data").drop_duplicates("ticker", keep="last").set_index("ticker")
    ok = {t for t, r in ult.iterrows()
          if _TICKER_LOTE.match(t) and classificar_papel(t, r["isin"] or None, r["codbdi"] or None) in tipos}
    return c[c["ticker"].isin(ok)]


def elegiveis_nefin(cotacoes, data, empresa_de=None, volume_min=VOLUME_MIN_DIA,
                    presenca_min=PRESENCA_MIN, criterio="conjunto", tipos=TIPOS_NEFIN):
    """Tickers elegiveis para o ano de `data` segundo o NEFIN, usando apenas o ano anterior.

    criterio='conjunto': fracao dos pregoes de t-1 com volume > volume_min supera presenca_min;
    criterio='separado': presenca (negocios > 0) > presenca_min E volume medio > volume_min.
    empresa_de: funcao ticker -> chave de empresa (default: 4 primeiros caracteres).
    tipos: tipos de papel aceitos (default acao e unit; ETF/BDR/FII/direitos ficam fora).
    Devolve lista ordenada. Vazia se nao ha dados do ano anterior.
    """
    ano = pd.Timestamp(data).year
    c = _apenas_acoes(_cotacoes_limpas(cotacoes), tipos)
    ant = c[c["data"].dt.year == ano - 1]
    if ant.empty:
        return []
    empresa_de = empresa_de or _empresa_padrao
    n_pregoes = ant["data"].nunique()
    limite_listagem = pd.Timestamp(year=ano - 1, month=12, day=1)
    primeira = c.groupby("ticker")["data"].min()
    g = ant.groupby("ticker")
    vol_medio = g["volume"].mean()
    if criterio == "separado":
        presenca = g["negocios"].apply(lambda s: (s > 0).sum()) / n_pregoes
        ok = (presenca > presenca_min) & (vol_medio > volume_min)
    else:
        dias_ok = g["volume"].apply(lambda s: (s > volume_min).sum()) / n_pregoes
        ok = dias_ok > presenca_min
    cand = vol_medio[ok].to_frame("vol")
    cand = cand[primeira.reindex(cand.index) < limite_listagem]
    if cand.empty:
        return []
    cand["empresa"] = [empresa_de(t) for t in cand.index]
    cand = cand.sort_values("vol", ascending=False)
    cand = cand[~cand["empresa"].duplicated(keep="first")]
    return sorted(cand.index.tolist())


def _mensal_de_diario(ret):
    """Retorno mensal composto por ticker (NaN se algum dia do mes faltar totalmente)."""
    return (1 + ret).resample("ME").prod(min_count=1) - 1


def _fator_mensal(diario):
    return (1 + diario).resample("ME").prod(min_count=1) - 1


# ─────────────────────────────────────────────────────────────
# WML
# ─────────────────────────────────────────────────────────────
def carteiras_wml(retornos, cotacoes, empresa_de=None, meses_ini=12, meses_fim=2, min_meses=None):
    """Composicao dos terciles de momentum por mes de aplicacao.

    Para o mes m: elegiveis do ano de m; momentum = composto dos retornos mensais de
    m-meses_ini ate m-meses_fim (11 meses com os defaults); terciles por momentum.
    Devolve DataFrame(mes (Period M), n, alto, medio, baixo) com listas de tickers.
    Meses sem ao menos 3 candidatos ficam de fora.
    """
    ret = retornos.sort_index()
    mensal = _mensal_de_diario(ret)
    mensal.index = mensal.index.to_period("M")
    min_meses = min_meses or (meses_ini - meses_fim + 1)
    linhas = []
    eleg_cache = {}
    for m in mensal.index:
        ini, fim = m - meses_ini, m - meses_fim
        if ini < mensal.index[0]:
            continue
        if m.year not in eleg_cache:
            eleg_cache[m.year] = elegiveis_nefin(cotacoes, m.to_timestamp(), empresa_de=empresa_de)
        eleg = [t for t in eleg_cache[m.year] if t in mensal.columns]
        if not eleg:
            continue
        janela = mensal.loc[ini:fim, eleg]
        validos = janela.count() >= min_meses
        mom = (1 + janela.loc[:, validos]).prod() - 1
        if len(mom) < 3:
            continue
        t = terciles(mom)
        linhas.append({"mes": m, "n": int(len(mom)), "alto": t["alto"], "medio": t["medio"], "baixo": t["baixo"]})
    return pd.DataFrame(linhas, columns=["mes", "n", "alto", "medio", "baixo"])


def _retorno_carteira(ret, membros, periodo):
    """Media simples dos retornos diarios dos membros no periodo (Period M ou Y)."""
    if not membros:
        return pd.Series(dtype=float)
    ini, fim = periodo.start_time, periodo.end_time
    r = ret.loc[(ret.index >= ini) & (ret.index <= fim), [t for t in membros if t in ret.columns]]
    return r.mean(axis=1, skipna=True)


def replicar_wml(retornos, cotacoes, empresa_de=None, meses_ini=12, meses_fim=2):
    """Replica do WML: (serie diaria, serie mensal). Vazias se nao houver meses formados.

    retornos: DataFrame data x ticker de retorno TOTAL diario (eventos.retorno_total) ou,
    para testes, retornos_de_cotacoes(). cotacoes: formato de cotahist.py.
    """
    ret = retornos.sort_index()
    cart = carteiras_wml(ret, cotacoes, empresa_de=empresa_de, meses_ini=meses_ini, meses_fim=meses_fim)
    partes = []
    for _, r in cart.iterrows():
        alto = _retorno_carteira(ret, r["alto"], r["mes"])
        baixo = _retorno_carteira(ret, r["baixo"], r["mes"])
        partes.append((alto - baixo).dropna())
    if not partes:
        vazio = pd.Series(dtype=float, name="WML")
        return vazio, vazio.copy()
    diario = pd.concat(partes).sort_index()
    diario.name = "WML"
    mensal = _fator_mensal(diario)
    mensal.name = "WML"
    return diario, mensal


# ─────────────────────────────────────────────────────────────
# HML
# ─────────────────────────────────────────────────────────────
def _book_to_market(book_equity, cotacoes, ano):
    """Series ticker -> B/M para o rebalance de janeiro de `ano` (PL e VM de dezembro de ano-1).

    book_equity: DataFrame(ticker, data_ref, pl) + uma de: bm | valor_mercado | qtd_acoes.
    Com qtd_acoes, VM = ultimo fechamento de dezembro de ano-1 x qtd_acoes.
    """
    be = book_equity.copy()
    be["ticker"] = be["ticker"].astype(str).str.strip().str.upper()
    be["data_ref"] = pd.to_datetime(be["data_ref"])
    dez = be[(be["data_ref"].dt.year == ano - 1) & (be["data_ref"].dt.month == 12)]
    if dez.empty:
        return pd.Series(dtype=float)
    dez = dez.sort_values("data_ref").drop_duplicates("ticker", keep="last").set_index("ticker")
    if "bm" in dez.columns:
        bm = pd.to_numeric(dez["bm"], errors="coerce")
    elif "valor_mercado" in dez.columns:
        bm = pd.to_numeric(dez["pl"], errors="coerce") / pd.to_numeric(dez["valor_mercado"], errors="coerce")
    elif "qtd_acoes" in dez.columns:
        c = _cotacoes_limpas(cotacoes)
        c = c[(c["data"].dt.year == ano - 1) & (c["data"].dt.month == 12) & c["fec"].notna()]
        fec = c.sort_values("data").drop_duplicates("ticker", keep="last").set_index("ticker")["fec"]
        vm = fec.reindex(dez.index) * pd.to_numeric(dez["qtd_acoes"], errors="coerce")
        bm = pd.to_numeric(dez["pl"], errors="coerce") / vm
    else:
        return None
    bm = bm.replace([np.inf, -np.inf], np.nan).dropna()
    return bm[bm > 0]        # PL negativo fica fora (suposicao: NEFIN exclui book equity <= 0)


def carteiras_hml(retornos, cotacoes, book_equity, empresa_de=None):
    """Terciles anuais de B/M: DataFrame(ano (Period Y), n, alto, medio, baixo)."""
    anos = sorted(set(retornos.index.year))
    linhas = []
    for ano in anos:
        eleg = elegiveis_nefin(cotacoes, pd.Timestamp(year=ano, month=1, day=1), empresa_de=empresa_de)
        if not eleg:
            continue
        bm = _book_to_market(book_equity, cotacoes, ano)
        if bm is None:
            return None
        bm = bm.reindex([t for t in eleg if t in bm.index]).dropna()
        if len(bm) < 3:
            continue
        t = terciles(bm)
        linhas.append({"ano": pd.Period(year=ano, freq="Y"), "n": int(len(bm)),
                       "alto": t["alto"], "medio": t["medio"], "baixo": t["baixo"]})
    return pd.DataFrame(linhas, columns=["ano", "n", "alto", "medio", "baixo"])


def replicar_hml(retornos, cotacoes, book_equity=None, empresa_de=None):
    """Replica do HML: (serie diaria, serie mensal). None se book_equity for None ou nao
    tiver como calcular o B/M (ver _book_to_market)."""
    if book_equity is None or len(book_equity) == 0:
        return None
    ret = retornos.sort_index()
    cart = carteiras_hml(ret, cotacoes, book_equity, empresa_de=empresa_de)
    if cart is None:
        return None
    partes = []
    for _, r in cart.iterrows():
        alto = _retorno_carteira(ret, r["alto"], r["ano"])
        baixo = _retorno_carteira(ret, r["baixo"], r["ano"])
        partes.append((alto - baixo).dropna())
    if not partes:
        vazio = pd.Series(dtype=float, name="HML")
        return vazio, vazio.copy()
    diario = pd.concat(partes).sort_index()
    diario.name = "HML"
    mensal = _fator_mensal(diario)
    mensal.name = "HML"
    return diario, mensal


# ─────────────────────────────────────────────────────────────
# Comparacao com o NEFIN (o gate)
# ─────────────────────────────────────────────────────────────
def _serie_mensal(x, fator):
    s = x[fator] if isinstance(x, pd.DataFrame) else x
    s = pd.Series(s).dropna().astype(float)
    idx = pd.to_datetime(s.index) if not isinstance(s.index, pd.PeriodIndex) else s.index.to_timestamp()
    s.index = pd.DatetimeIndex(idx).to_period("M")
    return s[~s.index.duplicated(keep="last")].sort_index()


def comparar(replica_mensal, nefin_mensal, fator="WML", corr_min=CORR_MIN, dif_max_pp=DIF_MAX_PP):
    """Compara a replica mensal com o NEFIN mensal (alinhados por mes).

    Devolve {"correlacao", "media_anual_replica", "media_anual_nefin", "diferenca_pp",
    "n_meses", "passou"}; passou = corr >= corr_min e |diferenca| <= dif_max_pp.
    Medias anuais = media aritmetica mensal x 12 (em decimal); diferenca em pontos percentuais.
    """
    a = _serie_mensal(replica_mensal, fator)
    b = _serie_mensal(nefin_mensal, fator)
    comum = a.index.intersection(b.index)
    a, b = a.loc[comum], b.loc[comum]
    n = int(len(comum))
    if n < 2:
        return {"correlacao": float("nan"), "media_anual_replica": float("nan"),
                "media_anual_nefin": float("nan"), "diferenca_pp": float("nan"), "n_meses": n, "passou": False}
    corr = float(np.corrcoef(a.values, b.values)[0, 1]) if a.std() > 0 and b.std() > 0 else float("nan")
    ma, mb = float(a.mean() * 12), float(b.mean() * 12)
    dif = (ma - mb) * 100
    passou = bool(np.isfinite(corr) and corr >= corr_min and abs(dif) <= dif_max_pp)
    return {"correlacao": corr, "media_anual_replica": ma, "media_anual_nefin": mb,
            "diferenca_pp": float(dif), "n_meses": n, "passou": passou}


# ─────────────────────────────────────────────────────────────
# Linha de comando: o gate de verdade (precisa do COTAHIST no banco)
# ─────────────────────────────────────────────────────────────
def rodar_gate(ini, fim, book_equity=None, retornos=None):
    """Carrega COTAHIST (ini-2..fim) e o snapshot NEFIN, replica WML (e HML se houver PL)
    e devolve o dict de comparacoes. Levanta FileNotFoundError sem COTAHIST/NEFIN."""
    from quant.dados import cotahist, nefin
    cot = cotahist.carregar(ini - 2, fim)
    if cot is None or len(cot) == 0:
        raise FileNotFoundError("sem COTAHIST no banco; rode python -m quant.dados.cotahist --anos ...")
    cot = cotahist.acoes_a_vista(cot, apenas_lote_padrao=False)
    alvo = nefin.mensal(nefin.carregar_fatores())
    if retornos is None:
        retornos = retornos_de_cotacoes(cot)
    diario, mensal = replicar_wml(retornos, cot)
    janela = mensal[(mensal.index.year >= ini) & (mensal.index.year <= fim)]
    out = {"WML": comparar(janela, alvo, "WML")}
    hml = replicar_hml(retornos, cot, book_equity)
    if hml is not None:
        janela_h = hml[1][(hml[1].index.year >= ini) & (hml[1].index.year <= fim)]
        out["HML"] = comparar(janela_h, alvo, "HML")
    out["passou"] = all(v["passou"] for k, v in out.items() if k != "passou")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gate da fase 1: replica WML/HML do NEFIN")
    ap.add_argument("--ini", type=int, default=2008)
    ap.add_argument("--fim", type=int, default=2026)
    args = ap.parse_args(argv)
    try:
        res = rodar_gate(args.ini, args.fim)
    except FileNotFoundError as e:
        print(str(e))
        return 2
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["passou"] else 1


if __name__ == "__main__":
    sys.exit(main())

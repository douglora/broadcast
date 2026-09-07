"""
Universo investivel point-in-time (M7): quem podia ser comprado no ultimo pregao de cada mes.

Por que existe: o universo e a primeira fonte de vies de um backtest. Se ele for montado
com a lista de hoje (quem existe, quem e liquido, quem e "acao"), a carteira de 2010 ja
sabe quem sobreviveu. Aqui cada mes e recalculado usando SOMENTE as cotacoes ate o ultimo
pregao daquele mes; papeis que depois morreram (RJ, OPA, incorporacao) entram normalmente
enquanto passavam nas regras, e saem quando deixaram de passar.

Regras (defaults, todos parametrizaveis em universo_pit):
  - adtv21 >= R$ 1,5 mi: media do volume financeiro (COTAHIST `volume`, ja em R$) dos
    ultimos 21 pregoes, com dias sem negocio contando zero;
  - presenca >= 80%: fracao dos ultimos 252 pregoes do MERCADO (nao do papel) em que o
    papel teve negocios > 0;
  - preco >= R$ 2,00 (ultimo fechamento conhecido ate a data): abaixo disso o tick de
    R$ 0,01 vira spread de meio por cento;
  - codbdi em ('02',): lote padrao. RJ/concordata/intervencao (05..11) continuam na SERIE de
    precos (cotahist.py) mas nao entram no universo de compra;
  - tipo em ('acao', 'unit'): sem BDR, ETF, FII, direitos/recibos;
  - UMA CLASSE POR EMPRESA: entre tickers da mesma empresa fica o de maior adtv21. A chave
    de empresa e o CNPJ quando o DataFrame `identidade` (ticker, isin, cnpj, data_ini,
    data_fim) e fornecido - respeitando a vigencia na data - e os 4 primeiros caracteres
    do ticker caso contrario (PETR3/PETR4, SANB3/SANB4/SANB11; falha para holdings com
    prefixo diferente, por isso a identidade importa).

Armadilhas:
  - o "ultimo pregao de cada mes" e o ultimo pregao PRESENTE NAS COTACOES, nao o do
    calendario: assim o universo de um mes so existe quando os dados daquele mes existem
    (e o teste de look-ahead vale para dados sinteticos com qualquer calendario);
  - com menos de 252 pregoes de historico a presenca e medida sobre o que existe
    (n_pregoes diz quantos foram); min_pregoes evita universo com 1 dia de dado;
  - o fechamento e o ultimo conhecido (ffill) porque um papel pode nao ter negocio
    justamente no ultimo pregao; a presenca ja penaliza quem nao negocia;
  - classificacao interna (classificar_papel) e uma heuristica por sufixo/ISIN/CODBDI.
    Se identidade.py estiver disponivel, passe `classificar=identidade.classificar_papel`
    ou um dicionario {ticker: tipo} - a assinatura e a mesma;
  - setor NAO e calculado aqui: setores() e um placeholder documentado (o setor vem do
    cadastro CVM SETOR_ATIV ou do segmento das carteiras de indice da B3).

Saida: universo_pit(data, ticker, isin, empresa, adtv21, presenca, preco, n_pregoes),
uma linha por (data, ticker) aprovado; contagem_mensal() publica o tamanho por mes.
"""
import re

import numpy as np
import pandas as pd

ADTV_MIN = 1_500_000.0
PRESENCA_MIN = 0.80
PRECO_MIN = 2.0
CODBDI_UNIVERSO = ("02",)
TIPOS_UNIVERSO = ("acao", "unit")
JANELA_ADTV = 21
JANELA_PRESENCA = 252
MIN_PREGOES = 21

COLUNAS = ["data", "ticker", "isin", "empresa", "adtv21", "presenca", "preco", "n_pregoes"]
_TICKER = re.compile(r"^[A-Z0-9]{4}(\d{1,2})[A-Z]?$")


# ─────────────────────────────────────────────────────────────
# Classificacao e chave de empresa (puras)
# ─────────────────────────────────────────────────────────────
def sufixo(ticker):
    """'PETR4' -> '4'; 'AAPL34' -> '34'; 'BOVA11' -> '11'; 'PETR4F' -> '4'; invalido -> None."""
    m = _TICKER.match(str(ticker).strip().upper())
    return m.group(1) if m else None


def classificar_papel(ticker, isin=None, codbdi=None):
    """'acao' | 'unit' | 'bdr' | 'etf' | 'fii' | 'direito' | 'outro' (regras internas).

    - CODBDI 10 ou sufixo 1/2/9/10 -> direito (recibos e direitos de subscricao);
    - sufixo 31..39 ou ISIN com 'BDR' -> bdr (31..35 sao os niveis usuais; 36..39 idem);
    - sufixo 11: CODBDI 12 -> fii; ISIN com 'CTF' (certificado de fundo) -> etf; senao unit
      (ISIN de unit na B3 e 'CDAM'; aceita-se qualquer ISIN de acao);
    - sufixo 3..8 -> acao; resto -> outro.
    """
    t = str(ticker).strip().upper()
    isin = ("" if isin is None or (isinstance(isin, float) and np.isnan(isin)) else str(isin)).strip().upper()
    cb = None if codbdi is None or (isinstance(codbdi, float) and np.isnan(codbdi)) or str(codbdi).strip() == "" \
        else str(codbdi).strip().zfill(2)
    suf = sufixo(t)
    if cb == "10":
        return "direito"
    if suf is None:
        return "outro"
    if suf in ("1", "2", "9", "10"):
        return "direito"
    if suf in {str(n) for n in range(31, 40)} or "BDR" in isin:
        return "bdr"
    if suf == "11":
        if cb == "12":
            return "fii"
        if "CTF" in isin:
            return "etf"
        return "unit"
    if suf in ("3", "4", "5", "6", "7", "8"):
        return "acao"
    return "outro"


def _classificador(classificar):
    """Aceita None (regras internas), funcao(ticker, isin, codbdi) ou dict {ticker: tipo}."""
    if classificar is None:
        return classificar_papel
    if isinstance(classificar, dict):
        d = {str(k).upper(): v for k, v in classificar.items()}
        return lambda t, isin=None, codbdi=None: d.get(str(t).upper()) or classificar_papel(t, isin, codbdi)
    return classificar


def _indice_identidade(identidade):
    """Pre-processa a identidade uma vez: {ticker: DataFrame(cnpj, data_ini, data_fim)} com datas
    ja convertidas. universo_pit chama empresa_chave milhares de vezes; filtrar o DataFrame
    inteiro a cada chamada custava minutos com a identidade real."""
    if identidade is None or len(identidade) == 0:
        return {}
    d = pd.DataFrame({
        "ticker": identidade["ticker"].astype(str).str.strip().str.upper(),
        "cnpj": identidade["cnpj"] if "cnpj" in identidade else None,
        "data_ini": pd.to_datetime(identidade["data_ini"], errors="coerce") if "data_ini" in identidade else pd.NaT,
        "data_fim": pd.to_datetime(identidade["data_fim"], errors="coerce") if "data_fim" in identidade else pd.NaT,
    })
    return {t: g.sort_values("data_ini") for t, g in d.groupby("ticker")}


def empresa_chave(ticker, data=None, identidade=None):
    """Chave 'uma classe por empresa': CNPJ vigente na identidade (se houver) ou ticker[:4].

    identidade: DataFrame (ticker, cnpj, data_ini, data_fim) ou o dict de _indice_identidade.
    Sem data, vale a vigencia mais recente do ticker."""
    t = str(ticker).strip().upper()
    if identidade is None or len(identidade) == 0:
        return t[:4]
    idx = identidade if isinstance(identidade, dict) else _indice_identidade(identidade)
    d = idx.get(t)
    if d is None or d.empty:
        return t[:4]
    if data is not None:
        ts = pd.Timestamp(data)
        d = d[(d["data_ini"].isna() | (d["data_ini"] <= ts)) & (d["data_fim"].isna() | (d["data_fim"] >= ts))]
    if d.empty:
        return t[:4]
    cnpj = d.iloc[-1]["cnpj"]
    if cnpj is None or (isinstance(cnpj, float) and np.isnan(cnpj)) or not str(cnpj).strip():
        return t[:4]
    return str(cnpj).strip()


# ─────────────────────────────────────────────────────────────
# Painel diario (pivots) e universo
# ─────────────────────────────────────────────────────────────
def _painel(cotacoes):
    """Pivots data x ticker: volume (0 sem negocio), negocios, fec/isin/codbdi (ffill)."""
    c = pd.DataFrame({
        "data": pd.to_datetime(cotacoes["data"]),
        "ticker": cotacoes["ticker"].astype(str).str.strip().str.upper(),
        "isin": cotacoes["isin"].astype(str).str.strip().str.upper() if "isin" in cotacoes else "",
        "codbdi": cotacoes["codbdi"].astype(str).str.strip().str.zfill(2) if "codbdi" in cotacoes else "02",
        "fec": pd.to_numeric(cotacoes["fec"], errors="coerce"),
        "volume": pd.to_numeric(cotacoes["volume"], errors="coerce"),
        "negocios": pd.to_numeric(cotacoes["negocios"], errors="coerce"),
    }).sort_values(["data", "ticker"]).drop_duplicates(["data", "ticker"], keep="last")
    piv = lambda col: c.pivot(index="data", columns="ticker", values=col).sort_index()
    return {
        "volume": piv("volume").fillna(0.0),
        "negocios": piv("negocios").fillna(0.0),
        "fec": piv("fec").ffill(),
        "isin": piv("isin").ffill(),
        "codbdi": piv("codbdi").ffill(),
    }


def _ultimos_pregoes_do_mes(datas):
    """Ultima data presente em cada mes (DatetimeIndex ordenado)."""
    s = pd.Series(datas, index=datas)
    return pd.DatetimeIndex(s.groupby([datas.year, datas.month]).max().values)


def universo_pit(cotacoes, identidade=None, classificar=None, datas=None,
                 adtv_min=ADTV_MIN, presenca_min=PRESENCA_MIN, preco_min=PRECO_MIN,
                 codbdi=CODBDI_UNIVERSO, tipos=TIPOS_UNIVERSO,
                 janela_adtv=JANELA_ADTV, janela_presenca=JANELA_PRESENCA, min_pregoes=MIN_PREGOES):
    """Universo investivel no ultimo pregao de cada mes, usando so dados ate aquela data.

    cotacoes: DataFrame no formato de cotahist.py (data, ticker, isin, codbdi, fec, volume,
    negocios). datas: opcional, lista de datas de calculo (default: ultimo pregao presente em
    cada mes). Devolve DataFrame com COLUNAS, ordenado por data e -adtv21.
    """
    if cotacoes is None or len(cotacoes) == 0:
        return pd.DataFrame(columns=COLUNAS)
    p = _painel(cotacoes)
    pregoes = p["volume"].index
    if datas is None:
        datas = _ultimos_pregoes_do_mes(pregoes)
    else:
        datas = pd.DatetimeIndex(sorted({pd.Timestamp(d) for d in datas}))
    classif = _classificador(classificar)
    ident = _indice_identidade(identidade)

    adtv = p["volume"].rolling(janela_adtv, min_periods=1).mean()
    negociou = (p["negocios"] > 0).astype(float)
    pres = negociou.rolling(janela_presenca, min_periods=1).sum()
    n_preg = pd.Series(np.arange(1, len(pregoes) + 1), index=pregoes).clip(upper=janela_presenca)
    presenca = pres.div(n_preg, axis=0)

    linhas = []
    usadas = set()
    for d in datas:
        if d not in pregoes:
            # data sem pregao nos dados: usa o ultimo pregao ate ela (point-in-time)
            ant = pregoes[pregoes <= d]
            if len(ant) == 0:
                continue
            d = ant[-1]
        if d in usadas:
            continue          # duas datas pedidas resolvendo para o mesmo pregao: uma linha so
        usadas.add(d)
        n = int(n_preg.loc[d])
        if n < min_pregoes:
            continue
        cand = pd.DataFrame({
            "adtv21": adtv.loc[d], "presenca": presenca.loc[d], "preco": p["fec"].loc[d],
            "isin": p["isin"].loc[d], "codbdi": p["codbdi"].loc[d],
        })
        cand = cand[(cand["adtv21"] >= adtv_min) & (cand["presenca"] >= presenca_min)
                    & (cand["preco"] >= preco_min) & cand["codbdi"].isin(codbdi)]
        if cand.empty:
            continue
        cand["tipo"] = [classif(t, r["isin"], r["codbdi"]) for t, r in cand.iterrows()]
        cand = cand[cand["tipo"].isin(tipos)]
        if cand.empty:
            continue
        cand["empresa"] = [empresa_chave(t, d, ident) for t in cand.index]
        cand = cand.sort_values("adtv21", ascending=False)
        cand = cand[~cand["empresa"].duplicated(keep="first")]
        for t, r in cand.iterrows():
            linhas.append({"data": d, "ticker": t, "isin": r["isin"], "empresa": r["empresa"],
                           "adtv21": float(r["adtv21"]), "presenca": float(r["presenca"]),
                           "preco": float(r["preco"]), "n_pregoes": n})
    if not linhas:
        return pd.DataFrame(columns=COLUNAS)
    out = pd.DataFrame(linhas, columns=COLUNAS)
    return out.sort_values(["data", "adtv21"], ascending=[True, False]).reset_index(drop=True)


def universo_em(universo, data):
    """Tickers do universo vigentes em `data`: a ultima data de calculo <= data (point-in-time)."""
    if universo is None or len(universo) == 0:
        return []
    ts = pd.Timestamp(data)
    datas = pd.to_datetime(universo["data"])
    ant = datas[datas <= ts]
    if len(ant) == 0:
        return []
    return sorted(universo.loc[datas == ant.max(), "ticker"].tolist())


def contagem_mensal(universo):
    """Series (data -> numero de papeis) para publicar o tamanho do universo por mes."""
    if universo is None or len(universo) == 0:
        return pd.Series(dtype=int, name="n")
    s = universo.groupby(pd.to_datetime(universo["data"]))["ticker"].nunique().sort_index()
    s.name = "n"
    return s


def setores(universo, mapa=None):
    """PLACEHOLDER: acrescenta a coluna `setor` ao universo.

    O setor NAO e derivado de precos. As fontes sao (a) SETOR_ATIV do cadastro CVM
    (cad_cia_aberta.csv, chave CNPJ; ver identidade.py) ou (b) o segmento das carteiras de
    indice da B3 (arquivar_b3.py, chave ticker). Esta funcao so aplica um `mapa`
    {empresa_ou_ticker: setor} ja montado por quem tem esses dados; sem mapa, setor = None.
    Nada de rede aqui.
    """
    out = universo.copy()
    if mapa is None:
        out["setor"] = None
        return out
    m = {str(k).upper(): v for k, v in mapa.items()}
    out["setor"] = [m.get(str(e).upper(), m.get(str(t).upper())) for e, t in zip(out["empresa"], out["ticker"])]
    return out

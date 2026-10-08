"""
Sinais da estrategia INTERSECAO-PF (M8): os oito sinais da secao 7 do plano, calculados
mes a mes sobre o universo point-in-time, com portoes, exclusoes e o score combinado.

Por que "intersecao" e nao soma: a ideia central do gestor entrevistado e que os fatores
se combinam por INTERSECAO, nao por somatoria - uma acao barata e podre nao vira boa
porque o desconto compensa a podridao. Aqui isso vira portao: quem falha em momento,
qualidade ou crescimento sai da lista, e so entao os sobreviventes sao ordenados. O modo
`soma_z` existe porque a comparacao (a) da secao 7 e pre-registrada: as duas formas
precisam ser medidas contra a mesma base.

PERCENTIS FIXOS, SEM BUSCA EM GRADE. 50 / 40 / 25 / 10 estao escritos como constantes e
nao devem ser "otimizados". A janela in-sample real com fundamentos e 2011-2015: cinco
anos nao sustentam doze parametros livres, e o backtest com parametro caçado nao mede
nada. Mudar qualquer um deles exige uma linha nova no livro de tentativas (quant/livro.py)
porque muda o N do Sharpe deflacionado.

Convencao de momento (a mesma de validacao/replica_nefin.carteiras_wml):
  a decisao e tomada no fechamento do ultimo pregao do mes M e vale para o mes M+1, entao
  a janela de momento e a do mes de aplicacao M+1: de (M+1)-12 ate (M+1)-2, ou seja os
  meses M-11 ate M-1. O mes M, recem-terminado, e PULADO - e o "12-2" da literatura. Um
  erro de um mes aqui troca momento por reversao de curto prazo e inverte o sinal.

Point-in-time:
  - fundamentos entram por `painel_fundamentos`, que deve ter sido montado com
    `deslocar=True` (visao em t-1). `painel()` avisa quando recebe painel nao deslocado.
  - retornos e volatilidade usam so pregoes ate a data de decisao, inclusive.
  - o universo ja e point-in-time (M7).

Sinais 6 e 7 sao INTERFACE, nao implementacao (decisao registrada no plano):
  - Aluguel (6): a retencao publica da B3 e de ~21 pregoes e o arquivamento deste
    repositorio comecou agora, entao no backtest a cobertura e ZERO. Nao e "nao testado",
    e nao testavel: `filtro_aluguel` devolve uma mascara toda falsa com
    attrs['meses_cobertos']=0, e o relatorio tem de dizer isso.
  - Insiders (7): o VLMO comeca em 2017 (fora do in-sample) e o bonus exige free float,
    que exige numero de acoes. `bonus_insiders` devolve zeros com
    attrs['disponivel']=False. O parser fica para a fase 3.

Suposicoes que valem a pena olhar:
  - LPA da CVM vem 0,00 com frequencia; `LPA TTM > 0` como portao obrigatorio poderia
    esvaziar o universo sozinho. Tratamos LPA 0 ou NaN como DESCONHECIDO e caimos para
    `lucro_liquido > 0`; a coluna `lpa_por_reserva` marca quando isso aconteceu.
  - DL/EBITDA NaN em nao-financeira (EBITDA <= 0) REPROVA o portao, exceto quando a
    divida liquida e <= 0: sem divida, alavancagem nao e criterio.
  - O componente de valor precisa de valor de mercado. Quando a cobertura na secao
    transversal fica abaixo de COBERTURA_VALOR_MIN, o peso de valor e redistribuido
    proporcionalmente entre momento e qualidade e a data e marcada `valor_ativo=False`.
    Sem isso o ranking passaria a comparar quem tem valor com quem nao tem.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO, garantir_dir, log
from quant.dados import calendario

# Percentis e limiares FIXOS A PRIORI (ver docstring: nao otimizar)
PCT_MOMENTUM = 50.0          # portao: momento na metade de cima
PCT_GPOA = 40.0              # alternativa ao retorno sobre capital acima da mediana
QUARTIL_CRESCIMENTO = 25.0   # exclui so o quartil inferior de crescimento de receita
DECIL_VALOR = 10.0           # exclui o decil mais caro
DECIL_VOL = 10.0             # exclui o decil de maior volatilidade
DL_EBITDA_MAX = 3.0
PESOS = {"momentum": 0.50, "qualidade": 0.25, "valor": 0.25}
BONUS_INSIDER = 10.0
COBERTURA_VALOR_MIN = 0.60

# Janelas
MOM_INI, MOM_FIM = 12, 2     # meses, na convencao do mes de aplicacao (ver docstring)
MOM6_INI = 6
JANELA_VOL, MIN_VOL = 252, 126
TAXA_ALUGUEL_MAX = 0.05
ALTA_POS_ABERTA, JANELA_POS_ABERTA = 0.50, 60

ARQ_PARQUET = os.path.join(DIR_BANCO, "sinais.parquet")
# datetime64[ns] so vai ate 2262: nao usar 2999 como "sem fim".
LIMITE_INFERIOR = pd.Timestamp("1900-01-01")
LIMITE_SUPERIOR = pd.Timestamp("2200-01-01")

COLUNAS = [
    "data", "ticker", "empresa", "cd_cvm", "setor", "financeira",
    "mom12", "mom6", "pct_mom12", "pct_mom6", "score_momentum", "pct_momentum",
    "fco", "fcf", "dl_ebitda", "retorno_capital", "gpoa", "pct_gpoa",
    "score_qualidade", "pct_qualidade",
    "crescimento_receita", "lpa", "lucro_liquido", "lpa_por_reserva",
    "bm", "ev_ebit", "fcf_yield", "score_valor", "pct_valor",
    "vol252", "adtv21", "preco",
    "taxa_aluguel", "bonus_insider",
    "passa_momentum", "passa_qualidade", "passa_crescimento",
    "excluido_valor", "excluido_vol", "excluido_aluguel",
    "elegivel", "motivo", "score", "rank",
]


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def percentis(serie):
    """Percentil (0 a 100) dentro da secao transversal. NaN continua NaN, e nao vira 0."""
    s = pd.to_numeric(pd.Series(serie), errors="coerce")
    if s.notna().sum() == 0:
        return pd.Series(np.nan, index=s.index, dtype=float)
    return s.rank(pct=True, na_option="keep") * 100.0


def painel_retornos(ret_longo, coluna="ret_total"):
    """`eventos.retorno_total` (longo) -> painel largo data x ticker.

    E o ponto de troca que `replica_nefin` documenta: o backtest usa retorno TOTAL, nao
    variacao de preco, senao dividendo vira alfa perdido e desdobramento vira crash.
    """
    if ret_longo is None or len(ret_longo) == 0:
        return pd.DataFrame()
    d = ret_longo[["ticker", "data", coluna]].copy()
    d["data"] = pd.to_datetime(d["data"])
    largo = d.pivot_table(index="data", columns="ticker", values=coluna, aggfunc="last")
    return largo.sort_index()


def mensais(ret_diario):
    """Painel diario -> composto mensal com indice Period[M] (mesma regra do replica_nefin)."""
    if ret_diario is None or len(ret_diario) == 0:
        return pd.DataFrame()
    m = (1 + ret_diario).resample("ME").prod() - 1
    m.index = m.index.to_period("M")
    return m


def _janela_momento(mensal, mes_decisao, meses_ini, meses_fim, min_meses):
    """Composto dos meses de aplicacao (M+1)-meses_ini ate (M+1)-meses_fim.

    mes_decisao e o Period do mes M em que a carteira e decidida; o mes de aplicacao e
    M+1. Com os defaults (12, 2) a janela e M-11 ate M-1 e o mes M fica de fora.
    """
    aplicacao = mes_decisao + 1
    ini, fim = aplicacao - meses_ini, aplicacao - meses_fim
    if len(mensal) == 0 or ini < mensal.index[0]:
        return pd.Series(dtype=float)
    janela = mensal.loc[ini:fim]
    if janela.empty:
        return pd.Series(dtype=float)
    validos = janela.count() >= min_meses
    if not validos.any():
        return pd.Series(dtype=float)
    return (1 + janela.loc[:, validos]).prod() - 1


def momentum(mensal, datas, meses_ini=MOM_INI, meses_fim=MOM_FIM, meses_ini6=MOM6_INI):
    """DataFrame(data, ticker, mom12, mom6) para cada data de decisao."""
    colunas = ["data", "ticker", "mom12", "mom6"]
    if mensal is None or len(mensal) == 0 or datas is None or len(datas) == 0:
        return pd.DataFrame(columns=colunas)
    linhas = []
    for d in sorted({pd.Timestamp(x) for x in datas}):
        mes = pd.Period(d, freq="M")
        m12 = _janela_momento(mensal, mes, meses_ini, meses_fim, meses_ini - meses_fim + 1)
        m6 = _janela_momento(mensal, mes, meses_ini6, meses_fim, meses_ini6 - meses_fim + 1)
        if len(m12) == 0 and len(m6) == 0:
            continue
        idx = sorted(set(m12.index) | set(m6.index))
        linhas.append(pd.DataFrame({"data": d, "ticker": idx,
                                    "mom12": [m12.get(t, np.nan) for t in idx],
                                    "mom6": [m6.get(t, np.nan) for t in idx]}))
    if not linhas:
        return pd.DataFrame(columns=colunas)
    return pd.concat(linhas, ignore_index=True)[colunas]


def volatilidade(ret_diario, datas, janela=JANELA_VOL, min_periodos=MIN_VOL):
    """DataFrame(data, ticker, vol252) anualizada, so com pregoes ate a data (inclusive)."""
    colunas = ["data", "ticker", "vol252"]
    if ret_diario is None or len(ret_diario) == 0 or datas is None or len(datas) == 0:
        return pd.DataFrame(columns=colunas)
    linhas = []
    for d in sorted({pd.Timestamp(x) for x in datas}):
        ate = ret_diario.loc[ret_diario.index <= d]
        if len(ate) == 0:
            continue
        v = ate.tail(janela)
        vol = v.std(ddof=1) * np.sqrt(252.0)
        vol = vol.where(v.count() >= min_periodos)
        vol = vol.dropna()
        if vol.empty:
            continue
        linhas.append(pd.DataFrame({"data": d, "ticker": vol.index, "vol252": vol.values}))
    if not linhas:
        return pd.DataFrame(columns=colunas)
    return pd.concat(linhas, ignore_index=True)[colunas]


def _serie_bool(valor, indice):
    return pd.Series(bool(valor), index=indice, dtype=bool)


def qualidade(fund, dl_max=DL_EBITDA_MAX, pct_gpoa_min=PCT_GPOA):
    """Portao 2 e score de qualidade sobre uma secao transversal (uma data).

    fund: DataFrame com fco, fcf, dl_ebitda, retorno_capital, gpoa, divida_liquida,
    financeira. Devolve (passa, score, pct_gpoa) com o indice de `fund`.
    """
    if fund is None or len(fund) == 0:
        vazio = pd.Series(dtype=float)
        return pd.Series(dtype=bool), vazio, vazio
    fluxo_ok = (fund["fco"] > 0) & (fund["fcf"] > 0)              # NaN reprova, de proposito
    fin = fund["financeira"].fillna(False).astype(bool)
    dl = pd.to_numeric(fund["dl_ebitda"], errors="coerce")
    sem_divida = pd.to_numeric(fund["divida_liquida"], errors="coerce") <= 0
    # NaN em nao-financeira = EBITDA <= 0 ou dado ausente: reprova, salvo quem nao tem divida
    alav_ok = fin | (dl <= dl_max) | (dl.isna() & sem_divida)
    pct_rc = percentis(fund["retorno_capital"])
    pct_gp = percentis(fund["gpoa"])
    retorno_ok = (pct_rc >= 50.0) | (pct_gp >= pct_gpoa_min)
    passa = fluxo_ok & alav_ok & retorno_ok.fillna(False)
    score = pd.concat([pct_rc, pct_gp], axis=1).mean(axis=1, skipna=True)
    return passa.fillna(False), score, pct_gp


def crescimento(fund, quartil=QUARTIL_CRESCIMENTO):
    """Portao 3: fora do quartil inferior de crescimento de receita e lucro por acao > 0.

    Devolve (passa, por_reserva) onde por_reserva marca as linhas em que o LPA veio zero
    ou ausente e a decisao usou lucro liquido.
    """
    if fund is None or len(fund) == 0:
        return pd.Series(dtype=bool), pd.Series(dtype=bool)
    pct_cres = percentis(fund["crescimento_receita"])
    cres_ok = (pct_cres > quartil) | pct_cres.isna()      # sem dado de crescimento nao reprova
    lpa = pd.to_numeric(fund["lpa"], errors="coerce")
    desconhecido = lpa.isna() | (lpa == 0)
    ll = pd.to_numeric(fund["lucro_liquido"], errors="coerce")
    lucro_ok = np.where(desconhecido, ll > 0, lpa > 0)
    lucro_ok = pd.Series(lucro_ok, index=fund.index).fillna(False).astype(bool)
    return (cres_ok & lucro_ok).fillna(False), desconhecido.fillna(True)


def valor(fund, decil=DECIL_VALOR, cobertura_min=COBERTURA_VALOR_MIN):
    """Sinal 4: score de valor e exclusao do decil mais caro.

    score = media dos percentis de B/M, EBIT/EV e FCF yield (componentes ausentes sao
    pulados). Devolve (score, excluido, ativo) - `ativo` e False quando a cobertura na
    secao transversal fica abaixo de cobertura_min, e nesse caso nada e excluido.
    """
    if fund is None or len(fund) == 0:
        return pd.Series(dtype=float), pd.Series(dtype=bool), False
    partes = [percentis(fund[c]) for c in ("bm", "ev_ebit", "fcf_yield") if c in fund]
    score = pd.concat(partes, axis=1).mean(axis=1, skipna=True) if partes else pd.Series(np.nan, index=fund.index)
    cobertura = float(score.notna().sum()) / float(len(score)) if len(score) else 0.0
    ativo = cobertura >= float(cobertura_min)
    if not ativo:
        return score, _serie_bool(False, fund.index), False
    limite = np.nanpercentile(score.dropna(), decil) if score.notna().any() else np.nan
    excluido = (score <= limite) if np.isfinite(limite) else _serie_bool(False, fund.index)
    return score, excluido.fillna(False), True


def baixo_risco(vol, decil=DECIL_VOL):
    """Sinal 5: exclui o decil de maior volatilidade. Devolve a mascara de exclusao."""
    v = pd.to_numeric(pd.Series(vol), errors="coerce")
    if v.notna().sum() == 0:
        return _serie_bool(False, v.index)
    limite = np.nanpercentile(v.dropna(), 100.0 - decil)
    return (v >= limite).fillna(False)


def filtro_aluguel(btc, datas, tickers, taxa_max=TAXA_ALUGUEL_MAX,
                   alta=ALTA_POS_ABERTA, janela=JANELA_POS_ABERTA):
    """Sinal 6, so ao vivo: exclui taxa de tomador alta com posicao em aberto subindo.

    NAO E TESTAVEL NO BACKTEST: a B3 publica ~21 pregoes de historico e o arquivamento
    deste repositorio comecou agora. Sem `btc` devolve mascara toda falsa e
    attrs['meses_cobertos'] = 0, que o relatorio tem de imprimir.
    """
    idx = pd.MultiIndex.from_product([sorted({pd.Timestamp(d) for d in (datas or [])}),
                                      sorted(set(tickers or []))], names=["data", "ticker"])
    fora = pd.Series(False, index=idx, dtype=bool)
    if btc is None or len(btc) == 0:
        fora.attrs["meses_cobertos"] = 0
        fora.attrs["testado"] = False
        return fora
    b = btc.copy()
    b["data"] = pd.to_datetime(b["data"])
    b = b.sort_values(["ticker", "data"])
    b["pos_ant"] = b.groupby("ticker")["pos_aberta"].shift(janela)
    b["subiu"] = (b["pos_aberta"] / b["pos_ant"] - 1.0) > alta
    b["ruim"] = (b["taxa_tomador"] > taxa_max) & b["subiu"].fillna(False)
    for (d, t) in idx:
        linhas = b[(b["ticker"] == t) & (b["data"] <= d)]
        if len(linhas):
            fora.loc[(d, t)] = bool(linhas.iloc[-1]["ruim"])
    fora.attrs["meses_cobertos"] = int(b["data"].dt.to_period("M").nunique())
    fora.attrs["testado"] = True
    return fora


def bonus_insiders(vlmo, datas, tickers, bonus=BONUS_INSIDER):
    """Sinal 7 (INTERFACE): compras liquidas de insiders somariam +10 pontos ao ranking.

    Devolve zeros com attrs['disponivel'] = False enquanto nao houver parser de VLMO.
    A assinatura existe para o backtest ja registrar que o sinal estava desligado, e para
    que ligar o sinal depois nao mude nenhuma outra chamada.
    """
    idx = pd.MultiIndex.from_product([sorted({pd.Timestamp(d) for d in (datas or [])}),
                                      sorted(set(tickers or []))], names=["data", "ticker"])
    s = pd.Series(0.0, index=idx, dtype=float)
    s.attrs["disponivel"] = False
    s.attrs["bonus"] = float(bonus)
    return s


def escolher_classe(candidatos, janela=60):
    """Sinal 8: entre classes do mesmo emissor, a que esta mais barata contra a propria
    mediana recente.

    candidatos: DataFrame(ticker, ask, fec, mediana_relativa) - `mediana_relativa` e a
    mediana de `janela` pregoes da razao entre o preco da classe e o da classe de
    referencia. Devolve o ticker escolhido, ou None.

    A regra e de ENTRADA. Girar entre classes depois realiza ganho, paga custo e consome
    a isencao de R$20 mil por CPF; quem carrega a trava e o estado da carteira.
    """
    if candidatos is None or len(candidatos) == 0:
        return None
    c = candidatos.copy()
    preco = pd.to_numeric(c.get("ask"), errors="coerce")
    preco = preco.where(preco > 0, pd.to_numeric(c["fec"], errors="coerce"))
    mediana = pd.to_numeric(c.get("mediana_relativa", pd.Series(np.nan, index=c.index)), errors="coerce")
    razao = preco / preco.iloc[0]
    desconto = (mediana - razao) / mediana
    desconto = desconto.where(mediana.notna() & (mediana > 0), 0.0)
    c = c.assign(_desconto=desconto.fillna(0.0), _preco=preco)
    c = c[c["_preco"] > 0]
    if c.empty:
        return None
    return str(c.sort_values("_desconto", ascending=False).iloc[0]["ticker"])


# ─────────────────────────────────────────────────────────────
# Painel mensal e ranking
# ─────────────────────────────────────────────────────────────
def mapear_empresa(universo, identidade=None):
    """Acrescenta `cd_cvm` ao universo, resolvendo a vigencia do ticker em cada data."""
    u = universo.copy()
    u["data"] = pd.to_datetime(u["data"])
    if identidade is None or len(identidade) == 0:
        u["cd_cvm"] = pd.NA
        return u
    ident = identidade[["ticker", "cd_cvm", "data_ini", "data_fim"]].copy()
    ident["data_ini"] = pd.to_datetime(ident["data_ini"]).fillna(LIMITE_INFERIOR)
    ident["data_fim"] = pd.to_datetime(ident["data_fim"]).fillna(LIMITE_SUPERIOR)
    j = u.merge(ident, on="ticker", how="left")
    ok = (j["data"] >= j["data_ini"]) & (j["data"] <= j["data_fim"])
    j = j[ok | j["cd_cvm"].isna()]
    j = j.sort_values(["data", "ticker", "data_ini"]).drop_duplicates(["data", "ticker"], keep="last")
    return j.drop(columns=["data_ini", "data_fim"]).reset_index(drop=True)


def painel(universo, retornos, fundamentos=None, identidade=None, setores=None,
           datas=None, btc=None, vlmo=None, pesos=PESOS):
    """Tabela mensal de sinais: uma linha por (data, ticker) do universo.

    universo: saida de `universo.universo_pit`. retornos: painel largo data x ticker de
    retorno total. fundamentos: saida de `painel_fundamentos.painel_ttm` (montado com
    deslocar=True). setores: dict {empresa -> setor}.
    """
    if universo is None or len(universo) == 0:
        return pd.DataFrame(columns=COLUNAS)
    uni = mapear_empresa(universo, identidade)
    datas = sorted({pd.Timestamp(d) for d in (datas if datas is not None else uni["data"].unique())})
    uni = uni[uni["data"].isin(datas)]
    if uni.empty:
        return pd.DataFrame(columns=COLUNAS)
    mensal = mensais(retornos)
    mom = momentum(mensal, datas)
    vol = volatilidade(retornos, datas)
    tickers = sorted(set(uni["ticker"]))
    aluguel = filtro_aluguel(btc, datas, tickers)
    insid = bonus_insiders(vlmo, datas, tickers)

    fund = None
    if fundamentos is not None and len(fundamentos) > 0:
        fund = fundamentos.copy()
        fund["data"] = pd.to_datetime(fund["data"])

    partes = []
    for d in datas:
        base = uni[uni["data"] == d].set_index("ticker")
        if base.empty:
            continue
        linha = pd.DataFrame(index=base.index)
        linha["data"] = d
        linha["empresa"] = base["empresa"]
        linha["cd_cvm"] = base["cd_cvm"]
        linha["adtv21"] = base["adtv21"]
        linha["preco"] = base["preco"]
        linha["setor"] = base["empresa"].map(setores) if setores else None
        # 1) momento
        m = mom[mom["data"] == d].set_index("ticker")
        linha["mom12"] = m["mom12"].reindex(linha.index)
        linha["mom6"] = m["mom6"].reindex(linha.index)
        linha["pct_mom12"] = percentis(linha["mom12"])
        linha["pct_mom6"] = percentis(linha["mom6"])
        linha["score_momentum"] = linha[["pct_mom12", "pct_mom6"]].mean(axis=1, skipna=True)
        linha["pct_momentum"] = percentis(linha["score_momentum"])
        linha["passa_momentum"] = (linha["pct_momentum"] >= PCT_MOMENTUM).fillna(False)
        # 2, 3, 4) fundamentos
        # Junta por cd_cvm com tipo NORMALIZADO dos dois lados. O reindex direto com
        # Int64 de um lado e int64 do outro casa zero linha em SILENCIO, e o painel sai
        # inteiro NaN sem erro nenhum - foi exatamente o que aconteceu na primeira versao.
        fx = pd.DataFrame(index=linha.index)
        if fund is not None:
            f = fund[fund["data"] == d].copy()
            if len(f):
                f["cd_cvm"] = pd.to_numeric(f["cd_cvm"], errors="coerce").astype("float64")
                f = f.dropna(subset=["cd_cvm"]).drop_duplicates("cd_cvm").set_index("cd_cvm")
                cod = pd.to_numeric(linha["cd_cvm"], errors="coerce").astype("float64")
                for c in f.columns:
                    fx[c] = cod.map(f[c])
        for c in ("fco", "fcf", "dl_ebitda", "retorno_capital", "gpoa", "divida_liquida",
                  "crescimento_receita", "lpa", "lucro_liquido", "bm", "ev_ebit", "fcf_yield"):
            linha[c] = fx[c] if c in fx else np.nan
        linha["financeira"] = (fx["financeira"] if "financeira" in fx else False)
        linha["financeira"] = linha["financeira"].map(lambda x: bool(x) if x == x and x is not None else False)
        passa_q, score_q, pct_gp = qualidade(linha)
        linha["passa_qualidade"] = passa_q
        linha["score_qualidade"] = score_q
        linha["pct_qualidade"] = percentis(score_q)
        linha["pct_gpoa"] = pct_gp
        passa_c, reserva = crescimento(linha)
        linha["passa_crescimento"] = passa_c
        linha["lpa_por_reserva"] = reserva
        score_v, excl_v, valor_ativo = valor(linha)
        linha["score_valor"] = score_v
        linha["pct_valor"] = percentis(score_v)
        linha["excluido_valor"] = excl_v
        # 5) baixo risco
        v = vol[vol["data"] == d].set_index("ticker")["vol252"].reindex(linha.index)
        linha["vol252"] = v
        linha["excluido_vol"] = baixo_risco(v)
        # 6, 7) aluguel e insiders
        linha["excluido_aluguel"] = [bool(aluguel.get((d, t), False)) for t in linha.index]
        linha["taxa_aluguel"] = np.nan
        linha["bonus_insider"] = [float(insid.get((d, t), 0.0)) for t in linha.index]
        # combinacao
        linha["elegivel"] = (linha["passa_momentum"] & linha["passa_qualidade"]
                             & linha["passa_crescimento"] & ~linha["excluido_valor"]
                             & ~linha["excluido_vol"] & ~linha["excluido_aluguel"])
        linha["motivo"] = _motivos(linha)
        linha["score"] = _score(linha, pesos, valor_ativo)
        linha["rank"] = linha["score"].where(linha["elegivel"]).rank(ascending=False, method="first")
        linha = linha.reset_index().rename(columns={"index": "ticker"})
        linha.attrs["valor_ativo"] = valor_ativo
        partes.append(linha)
    if not partes:
        return pd.DataFrame(columns=COLUNAS)
    out = pd.concat(partes, ignore_index=True)
    for c in COLUNAS:
        if c not in out:
            out[c] = np.nan
    out = out[COLUNAS].sort_values(["data", "rank"], na_position="last").reset_index(drop=True)
    out.attrs["aluguel_meses_cobertos"] = aluguel.attrs.get("meses_cobertos", 0)
    out.attrs["insiders_disponivel"] = insid.attrs.get("disponivel", False)
    return out


def _motivos(linha):
    """Primeiro motivo de exclusao, para o relatorio poder contar por que o universo encolhe."""
    motivos = []
    for _, r in linha.iterrows():
        if not r["passa_momentum"]:
            motivos.append("momento")
        elif not r["passa_qualidade"]:
            motivos.append("qualidade")
        elif not r["passa_crescimento"]:
            motivos.append("crescimento")
        elif r["excluido_valor"]:
            motivos.append("caro")
        elif r["excluido_vol"]:
            motivos.append("volatil")
        elif r["excluido_aluguel"]:
            motivos.append("aluguel")
        else:
            motivos.append("")
    return pd.Series(motivos, index=linha.index)


def _score(linha, pesos, valor_ativo):
    """0,50 momento + 0,25 qualidade + 0,25 valor, em percentis, mais o bonus de insider.

    Sem valor utilizavel o peso e redistribuido PROPORCIONALMENTE entre momento e
    qualidade: manter os 25% com score ausente compararia quem tem valor com quem nao tem.
    """
    p = dict(pesos)
    if not valor_ativo:
        resto = p["momentum"] + p["qualidade"]
        p = {"momentum": p["momentum"] / resto, "qualidade": p["qualidade"] / resto, "valor": 0.0}
    s = (p["momentum"] * linha["pct_momentum"].fillna(0.0)
         + p["qualidade"] * linha["pct_qualidade"].fillna(0.0)
         + p["valor"] * linha["pct_valor"].fillna(0.0)
         + linha["bonus_insider"].fillna(0.0))
    return s


def ranquear(sinais, pesos=PESOS, modo="intersecao"):
    """Recalcula score e rank. modo='intersecao' (portoes) ou 'soma_z' (sem portoes).

    O modo `soma_z` existe para a comparacao (a) pre-registrada: soma dos z-scores dos
    tres blocos, sem nenhum portao, so com as exclusoes de vol e aluguel.
    """
    if sinais is None or len(sinais) == 0:
        return sinais
    out = []
    for d, g in sinais.groupby("data", sort=True):
        g = g.copy()
        if modo == "soma_z":
            z = pd.concat([_z(g["score_momentum"]), _z(g["score_qualidade"]), _z(g["score_valor"])], axis=1)
            g["score"] = (z * [pesos["momentum"], pesos["qualidade"], pesos["valor"]]).sum(axis=1, skipna=True)
            g["elegivel"] = ~g["excluido_vol"] & ~g["excluido_aluguel"]
        else:
            valor_ativo = bool(g["score_valor"].notna().mean() >= COBERTURA_VALOR_MIN)
            g["score"] = _score(g, pesos, valor_ativo)
            g["elegivel"] = (g["passa_momentum"] & g["passa_qualidade"] & g["passa_crescimento"]
                             & ~g["excluido_valor"] & ~g["excluido_vol"] & ~g["excluido_aluguel"])
        g["rank"] = g["score"].where(g["elegivel"]).rank(ascending=False, method="first")
        out.append(g)
    return pd.concat(out, ignore_index=True).sort_values(["data", "rank"], na_position="last").reset_index(drop=True)


def _z(serie):
    s = pd.to_numeric(serie, errors="coerce")
    dp = s.std(ddof=0)
    return (s - s.mean()) / dp if dp and np.isfinite(dp) and dp > 0 else s * 0.0


def em(sinais, data):
    """Linhas de uma data, elegiveis primeiro, ordenadas por rank."""
    if sinais is None or len(sinais) == 0:
        return pd.DataFrame(columns=COLUNAS)
    d = pd.Timestamp(data)
    g = sinais[pd.to_datetime(sinais["data"]) == d]
    return g.sort_values(["rank"], na_position="last").reset_index(drop=True)


def resumo(sinais):
    """Diagnostico mensal: quantos sobreviveram e por que os outros sairam.

    O `n_elegivel` mes a mes e o numero que diz se a estrategia realmente teve 22 nomes
    para escolher em 2011-2013 - um backtest que segurou 11 nomes em 2012 nao e a
    estrategia que se pretende testar.
    """
    colunas = ["data", "n_universo", "n_elegivel", "momento", "qualidade", "crescimento",
               "caro", "volatil", "aluguel"]
    if sinais is None or len(sinais) == 0:
        return pd.DataFrame(columns=colunas)
    linhas = []
    for d, g in sinais.groupby("data", sort=True):
        contagem = g["motivo"].value_counts()
        linhas.append({"data": d, "n_universo": int(len(g)), "n_elegivel": int(g["elegivel"].sum()),
                       **{m: int(contagem.get(m, 0)) for m in
                          ("momento", "qualidade", "crescimento", "caro", "volatil", "aluguel")}})
    return pd.DataFrame(linhas, columns=colunas)


# ─────────────────────────────────────────────────────────────
# Banco
# ─────────────────────────────────────────────────────────────
def gravar(sinais, caminho=ARQ_PARQUET):
    garantir_dir(os.path.dirname(caminho))
    sinais[COLUNAS].to_parquet(caminho, index=False)
    return caminho


def carregar(caminho=ARQ_PARQUET):
    if not os.path.exists(caminho):
        return pd.DataFrame(columns=COLUNAS)
    return pd.read_parquet(caminho)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Painel mensal de sinais (M8)")
    ap.add_argument("--ini", type=int, default=2011)
    ap.add_argument("--fim", type=int, default=2026)
    args = ap.parse_args(argv)
    from quant.dados import cotahist, eventos, painel_fundamentos, identidade as ident_mod
    from quant import universo as uni_mod
    cot = cotahist.carregar(args.ini - 2, args.fim)
    if cot is None or len(cot) == 0:
        print("sem COTAHIST no banco; rode python -m quant.dados.cotahist --anos ...")
        return 2
    ident = ident_mod.carregar_identidade()
    uni = uni_mod.universo_pit(cotahist.acoes_a_vista(cot, apenas_lote_padrao=True), identidade=ident)
    ret = painel_retornos(eventos.retorno_total(cot[["ticker", "data", "fec"]], eventos.carregar_eventos()))
    fund = painel_fundamentos.carregar()
    s = painel(uni, ret, fundamentos=fund, identidade=ident)
    gravar(s)
    r = resumo(s)
    log(f"sinais: {len(s)} linhas, {r['n_elegivel'].mean():.1f} elegiveis por mes em media")
    log(f"aluguel: {s.attrs.get('aluguel_meses_cobertos', 0)} meses cobertos; "
        f"insiders disponivel: {s.attrs.get('insiders_disponivel', False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

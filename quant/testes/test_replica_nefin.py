import numpy as np
import pandas as pd
import pytest

from quant.validacao import replica_nefin as rn

PREGOES = pd.bdate_range("2019-01-02", "2021-12-31")
N = 30
TICKERS = [f"TK{i:02d}3" for i in range(N)]      # TK003..TK293: 4 letras/digitos + classe 3
VENCEDORES = TICKERS[:5]          # drift positivo forte
PERDEDORES = TICKERS[-5:]         # drift negativo forte


def _precos(seed=42, drift_extra=True):
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0, 0.015, size=(len(PREGOES), N))
    if drift_extra:
        ret[:, :5] += 0.004
        ret[:, -5:] -= 0.004
    precos = 20.0 * np.cumprod(1 + ret, axis=0)
    return pd.DataFrame(precos, index=PREGOES, columns=TICKERS)


def _cotacoes(precos, volume=2_000_000.0):
    linhas = []
    for t in precos.columns:
        p = precos[t]
        for d, v in p.items():
            linhas.append({"data": d.date(), "ticker": t, "isin": f"BR{t[:4]}ACNOR1", "codbdi": "02",
                           "fec": float(v), "volume": volume, "negocios": 50, "qtd": int(volume / v)})
    return pd.DataFrame(linhas)


@pytest.fixture(scope="module")
def base():
    precos = _precos()
    cot = _cotacoes(precos)
    return precos, cot, rn.retornos_de_cotacoes(cot)


def test_elegiveis_seguem_as_regras(base):
    precos, cot, _ = base
    assert rn.elegiveis_nefin(cot, "2019-06-01") == []                 # sem ano anterior nos dados
    assert rn.elegiveis_nefin(cot, "2020-03-01") == sorted(TICKERS)
    # iliquido em 2019 (volume 100 mil) -> fora em 2020; listado depois de dez/2019 -> fora em 2020
    cot2 = cot.copy()
    cot2.loc[cot2["ticker"] == "TK133", "volume"] = 100_000.0
    cot2 = cot2[~((cot2["ticker"] == "TK233") & (pd.to_datetime(cot2["data"]) < "2019-12-15"))]
    eleg = rn.elegiveis_nefin(cot2, "2020-01-15")
    assert "TK133" not in eleg and "TK233" not in eleg and len(eleg) == N - 2
    # mesma empresa (prefixo): fica a mais negociada
    cot3 = cot.copy()
    cot3.loc[cot3["ticker"] == "TK133", "ticker"] = "TK034"          # TK034 = "PN" da empresa TK03
    cot3.loc[cot3["ticker"] == "TK034", "volume"] = 9_000_000.0
    eleg = rn.elegiveis_nefin(cot3, "2020-01-15")
    assert "TK034" in eleg and "TK033" not in eleg and len(eleg) == N - 1
    assert "TK033" in rn.elegiveis_nefin(cot3, "2020-01-15", empresa_de=lambda t: t)   # chave = ticker


def test_elegiveis_excluem_etf_bdr_fii_e_fracionario(base):
    """BOVA11/AAPL34/HGLG11 passam folgados no volume: sem o filtro de tipo viravam 'empresas'
    do WML. PETR4F (fracionario) e a mesma acao repetida e tambem fica fora."""
    precos, cot, _ = base
    extras = []
    for t, isin, cb in [("BOVA11", "BRBOVACTF003", "02"), ("AAPL34", "BRAAPLBDR004", "02"),
                        ("HGLG11", "BRHGLGCTF003", "12"), ("PETR4F", "BRPETRACNPR6", "96"),
                        ("SANB11", "BRSANBCDAM13", "02"), ("PETR4", "BRPETRACNPR6", "02")]:
        extras.append(cot[cot["ticker"] == TICKERS[0]].assign(ticker=t, isin=isin, codbdi=cb, volume=9e8))
    cot_x = pd.concat([cot] + extras, ignore_index=True)
    eleg = rn.elegiveis_nefin(cot_x, "2020-06-01")
    assert {"BOVA11", "AAPL34", "HGLG11", "PETR4F"}.isdisjoint(eleg)
    assert {"SANB11", "PETR4"} <= set(eleg) and len(eleg) == N + 2
    # tipos=None desliga o filtro (para diagnostico)
    assert "BOVA11" in rn.elegiveis_nefin(cot_x, "2020-06-01", tipos=None)


def test_terciles_tamanhos_iguais():
    v = pd.Series(np.arange(10.0), index=list("abcdefghij"))
    t = rn.terciles(v)
    # n = 3k+1: o extra vai para o meio; alto e baixo com o mesmo tamanho
    assert t["baixo"] == ["a", "b", "c"] and t["medio"] == ["d", "e", "f", "g"] and t["alto"] == ["h", "i", "j"]
    t11 = rn.terciles(pd.Series(np.arange(11.0), index=list("abcdefghijk")))
    assert len(t11["baixo"]) == len(t11["alto"]) == 4 and len(t11["medio"]) == 3      # n = 3k+2
    t9 = rn.terciles(pd.Series(np.arange(9.0), index=list("abcdefghi")))
    assert [len(t9[k]) for k in ("baixo", "medio", "alto")] == [3, 3, 3]
    assert rn.terciles(v.iloc[:2]) == {"baixo": [], "medio": [], "alto": []}
    assert rn.terciles(pd.Series([1.0, np.nan, 3.0, 2.0], index=list("abcd")))["alto"] == ["c"]   # NaN fora


def test_replicar_wml_roda_e_momentum_artificial_cai_no_tercil_alto(base):
    precos, cot, ret = base
    diario, mensal = rn.replicar_wml(ret, cot)
    assert len(diario) > 400 and diario.index.min().year == 2020 and diario.index.max().year == 2021
    assert mensal.index.min().strftime("%Y-%m") == "2020-01" and len(mensal) == 24
    assert diario.abs().max() < 0.2
    cart = rn.carteiras_wml(ret, cot)
    assert len(cart) == 24 and (cart["n"] == N).all()
    for _, r in cart.iterrows():
        assert set(VENCEDORES) <= set(r["alto"]), r["mes"]
        assert set(PERDEDORES) <= set(r["baixo"]), r["mes"]
    # com drift de +0,4%/dia nos winners e -0,4% nos losers, o WML e claramente positivo
    assert mensal.mean() * 12 > 0.5
    # mensal e o composto do diario
    m = (1 + diario).resample("ME").prod() - 1
    pd.testing.assert_series_equal(mensal, m.rename("WML"))


def test_wml_sem_look_ahead(base):
    precos, cot, ret = base
    corte = pd.Timestamp("2021-06-30")
    _, mensal_original = rn.replicar_wml(ret, cot)
    # bagunca tudo depois do corte: retornos invertidos e embaralhados, volumes zerados de metade
    rng = np.random.default_rng(1)
    ret2 = ret.copy()
    depois = ret2.index > corte
    bloco = -ret2.loc[depois].values
    rng.shuffle(bloco, axis=1)
    ret2.loc[depois] = bloco
    cot2 = cot.copy()
    m = pd.to_datetime(cot2["data"]) > corte
    cot2.loc[m & cot2["ticker"].isin(TICKERS[::2]), "volume"] = 0.0
    cot2.loc[m, "fec"] = 1.0
    diario2, mensal2 = rn.replicar_wml(ret2, cot2)
    pd.testing.assert_series_equal(mensal_original.loc[:corte], mensal2.loc[:corte])
    diario1, _ = rn.replicar_wml(ret, cot)
    pd.testing.assert_series_equal(diario1.loc[:corte], diario2.loc[:corte])
    # e o futuro mudou de fato
    assert not np.allclose(mensal_original.loc[corte + pd.Timedelta(days=1):].values,
                           mensal2.loc[corte + pd.Timedelta(days=1):].values)


def test_wml_sem_look_ahead_na_virada_do_ano(base):
    """A elegibilidade do ano t usa so t-1: bagunçar 2021 inteiro (volumes zerados, listagem
    tardia, retornos invertidos) nao pode mudar nada de 2020."""
    precos, cot, ret = base
    corte = pd.Timestamp("2020-12-31")
    _, mensal_original = rn.replicar_wml(ret, cot)
    ret2 = ret.copy()
    ret2.loc[ret2.index > corte] = -ret2.loc[ret2.index > corte]
    cot2 = cot.copy()
    m = pd.to_datetime(cot2["data"]) > corte
    cot2.loc[m & cot2["ticker"].isin(TICKERS[:15]), "volume"] = 0.0
    cot2 = cot2[~(m & (cot2["ticker"] == TICKERS[20]))]
    _, mensal2 = rn.replicar_wml(ret2, cot2)
    pd.testing.assert_series_equal(mensal_original.loc[:corte], mensal2.loc[:corte])
    assert len(mensal_original.loc[:corte]) == 12
    assert rn.elegiveis_nefin(cot2, "2021-03-01") == rn.elegiveis_nefin(cot, "2021-03-01")   # usa 2020


def test_retornos_de_cotacoes_gap_e_preco_zero():
    idx = pd.bdate_range("2020-01-01", periods=6)
    linhas = []
    for d, pa, pb in zip(idx, [10, 11, None, 13, 14, 0], [10, 10, 10, 10, 10, 10]):
        if pa is not None:
            linhas.append({"data": d, "ticker": "AAAA3", "fec": pa, "volume": 1e6, "negocios": 1})
        linhas.append({"data": d, "ticker": "BBBB3", "fec": pb, "volume": 1e6, "negocios": 1})
    r = rn.retornos_de_cotacoes(pd.DataFrame(linhas))
    a = r["AAAA3"]
    assert np.isnan(a.iloc[0]) and abs(a.iloc[1] - 0.1) < 1e-12
    assert np.isnan(a.iloc[2])                                   # dia sem negocio: NaN, nao 0
    assert abs(a.iloc[3] - (13 / 11 - 1)) < 1e-12                # o gap acumula na volta
    assert np.isnan(a.iloc[5])                                   # fechamento 0: ausente, nao -100%
    assert np.isfinite(r.values[1:, 1]).all() and (r["BBBB3"].iloc[1:] == 0).all()


def test_wml_eh_positivo_com_momentum_e_ruido_sem_momentum_nao_explode():
    precos = _precos(seed=3, drift_extra=False)
    cot = _cotacoes(precos)
    ret = rn.retornos_de_cotacoes(cot)
    _, mensal = rn.replicar_wml(ret, cot)
    assert len(mensal) == 24 and mensal.abs().max() < 0.25


def test_replicar_hml(base):
    precos, cot, ret = base
    assert rn.replicar_hml(ret, cot, None) is None
    # PL crescente com o indice do ticker: B/M alto = ultimos tickers
    be = pd.DataFrame({"ticker": TICKERS, "data_ref": "2020-12-31", "pl": np.arange(1, N + 1) * 1e6,
                       "valor_mercado": 10e6})
    be = pd.concat([be, be.assign(data_ref="2019-12-31")], ignore_index=True)
    diario, mensal = rn.replicar_hml(ret, cot, be)
    assert diario.index.min().year == 2020 and len(mensal) == 24
    cart = rn.carteiras_hml(ret, cot, be)
    assert len(cart) == 2 and set(cart.iloc[0]["alto"]) == set(TICKERS[-10:])
    # com qtd_acoes, o valor de mercado vem do fechamento de dezembro; sem nada, None
    be_q = be.drop(columns="valor_mercado").assign(qtd_acoes=1e6)
    assert rn.replicar_hml(ret, cot, be_q) is not None
    assert rn.replicar_hml(ret, cot, be.drop(columns="valor_mercado")) is None
    # PL negativo fica fora
    be_neg = be.copy()
    be_neg.loc[be_neg["ticker"] == "TK003", "pl"] = -1.0
    cart_neg = rn.carteiras_hml(ret, cot, be_neg)
    assert "TK003" not in cart_neg.iloc[0]["alto"] + cart_neg.iloc[0]["medio"] + cart_neg.iloc[0]["baixo"]


def test_comparar_identico_passa_e_deslocado_nao():
    idx = pd.date_range("2015-01-31", periods=60, freq="ME")
    x = pd.Series(np.random.default_rng(0).normal(0.01, 0.04, 60), index=idx, name="WML")
    r = rn.comparar(x, x, "WML")
    assert abs(r["correlacao"] - 1) < 1e-12 and r["passou"] and r["n_meses"] == 60
    assert abs(r["diferenca_pp"]) < 1e-9 and abs(r["media_anual_replica"] - x.mean() * 12) < 1e-12
    # aceita DataFrame com a coluna do fator e indices em dias diferentes do mesmo mes
    df = pd.DataFrame({"WML": x.values, "HML": 0.0}, index=idx - pd.Timedelta(days=3))
    assert rn.comparar(x, df, "WML")["passou"]
    # mesma correlacao mas media 5 p.p. acima: reprova pela diferenca
    r2 = rn.comparar(x + 0.05 / 12, x, "WML")
    assert abs(r2["correlacao"] - 1) < 1e-12 and abs(r2["diferenca_pp"] - 5) < 1e-9 and not r2["passou"]
    # ruido independente: reprova pela correlacao
    y = pd.Series(np.random.default_rng(1).normal(0.01, 0.04, 60), index=idx)
    assert not rn.comparar(x, y, "WML")["passou"]
    assert rn.comparar(x.iloc[:1], x.iloc[:1], "WML")["n_meses"] == 1


def test_snapshot_nefin_local_tem_as_colunas():
    from quant.dados import nefin
    if nefin.pin_ultimo("fatores") is None:
        pytest.skip("sem snapshot NEFIN local")
    m = nefin.mensal(nefin.carregar_fatores())
    assert {"WML", "HML"} <= set(m.columns) and len(m) > 300
    r = rn.comparar(m["WML"], m, "WML")
    assert r["passou"] and r["n_meses"] == len(m["WML"].dropna())


def test_rodar_gate_de_ponta_a_ponta_com_cotahist_sintetico(monkeypatch, base):
    """O caminho do CLI: COTAHIST (simulado) -> retornos -> WML -> comparar com o NEFIN real.
    Com ruido puro o gate REPROVA (isso e o esperado); o que se testa e a mecanica."""
    from quant.dados import cotahist, nefin
    if nefin.pin_ultimo("fatores") is None:
        pytest.skip("sem snapshot NEFIN local")
    precos, cot, _ = base
    cot = cot.assign(tpmerc="010")
    extra = cot[cot["ticker"] == TICKERS[0]]
    cot = pd.concat([cot, extra.assign(ticker="BOVA11", isin="BRBOVACTF003", volume=9e8),
                     extra.assign(ticker="TK003F", codbdi="96", tpmerc="020", volume=9e8)], ignore_index=True)
    monkeypatch.setattr(cotahist, "carregar", lambda a, b, **k: cot)
    res = rn.rodar_gate(2020, 2021)
    assert set(res) == {"WML", "passou"} and res["WML"]["n_meses"] == 24
    assert set(res["WML"]) == {"correlacao", "media_anual_replica", "media_anual_nefin", "diferenca_pp", "n_meses", "passou"}
    assert np.isfinite(res["WML"]["correlacao"]) and res["passou"] is False
    cart = rn.carteiras_wml(rn.retornos_de_cotacoes(cot), cot)
    membros = set(sum((r["alto"] + r["medio"] + r["baixo"] for _, r in cart.iterrows()), []))
    assert "BOVA11" not in membros and "TK003F" not in membros and TICKERS[0] in membros
    # sem COTAHIST no banco: main devolve 2 e nao levanta
    monkeypatch.setattr(cotahist, "carregar", lambda a, b, **k: pd.DataFrame())
    assert rn.main(["--ini", "2020", "--fim", "2021"]) == 2

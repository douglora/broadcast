import numpy as np
import pandas as pd
import pytest

from quant import universo as u

N_PREGOES = 300
PREGOES = pd.bdate_range("2023-01-02", periods=N_PREGOES)

# ticker -> (isin, codbdi, preco, volume diario, fracao de dias com negocio)
PAPEIS = {
    "LIQD3": ("BRLIQDACNOR5", "02", 20.0, 8_000_000, 1.00),   # acao liquida: entra
    "ILIQ3": ("BRILIQACNOR1", "02", 20.0, 100_000, 1.00),     # iliquida (adtv < 1,5 mi)
    "AAPL34": ("BRAAPLBDR004", "02", 200.0, 50_000_000, 1.00),  # BDR: fora
    "EMPX11": ("BREMPXCDAM15", "02", 60.0, 5_000_000, 1.00),   # unit da EMPX
    "EMPX4": ("BREMPXACNPR7", "02", 30.0, 3_000_000, 1.00),    # PN da mesma empresa (menos liquida)
    "CHEP3": ("BRCHEPACNOR3", "02", 1.50, 9_000_000, 1.00),    # preco < 2: fora
    "RJUD3": ("BRRJUDACNOR9", "08", 10.0, 9_000_000, 1.00),    # recuperacao judicial: fora
    "PRES3": ("BRPRESACNOR2", "02", 10.0, 9_000_000, 0.50),    # negocia em metade dos dias: fora
    "BOVA11": ("BRBOVACTF003", "02", 120.0, 300_000_000, 1.00),  # ETF: fora
    "HGLG11": ("BRHGLGCTF003", "12", 160.0, 5_000_000, 1.00),  # FII: fora
}


def _cotacoes(pregoes=PREGOES, papeis=PAPEIS, seed=7):
    rng = np.random.default_rng(seed)
    linhas = []
    for t, (isin, codbdi, preco, vol, frac) in papeis.items():
        for i, d in enumerate(pregoes):
            if frac < 1 and (i % 2 == 1):          # PRES3 negocia so em dias pares
                continue
            fec = preco * (1 + 0.001 * rng.standard_normal())
            linhas.append({"data": d.date(), "ticker": t, "isin": isin, "codbdi": codbdi, "fec": round(fec, 2),
                           "volume": float(vol), "negocios": 100, "qtd": int(vol / max(fec, 0.01))})
    return pd.DataFrame(linhas)


@pytest.fixture(scope="module")
def cot():
    return _cotacoes()


def test_classificacao_interna():
    assert u.classificar_papel("PETR4", "BRPETRACNPR6", "02") == "acao"
    assert u.classificar_papel("AAPL34", "BRAAPLBDR004", "02") == "bdr"
    assert u.classificar_papel("MSFT32", None, None) == "bdr"
    assert u.classificar_papel("BOVA11", "BRBOVACTF003", "02") == "etf"
    assert u.classificar_papel("HGLG11", "BRHGLGCTF003", "12") == "fii"
    assert u.classificar_papel("HGLG11", "BRHGLGCTF003", "02") == "etf"      # CODBDI 12 e o que faz FII
    assert u.classificar_papel("SANB11", "BRSANBCDAM13", "02") == "unit"
    assert u.classificar_papel("PETR1", "BRPETRACNOR9", "10") == "direito"
    assert u.classificar_papel("VALE3", "BRVALEACNOR0", "10") == "direito"   # codbdi 10 manda
    assert u.classificar_papel("PETR4F", "BRPETRACNPR6", "96") == "acao"
    assert u.classificar_papel("IBOV", None, None) == "outro"


def test_regras_no_ultimo_mes(cot):
    uni = u.universo_pit(cot)
    assert list(uni.columns) == u.COLUNAS
    ultimo = uni[uni["data"] == uni["data"].max()]
    assert set(ultimo["ticker"]) == {"LIQD3", "EMPX11"}
    linha = ultimo.set_index("ticker").loc["LIQD3"]
    assert abs(linha["adtv21"] - 8_000_000) < 1 and linha["presenca"] == 1.0 and linha["n_pregoes"] == 252
    assert linha["empresa"] == "LIQD" and linha["isin"] == "BRLIQDACNOR5" and 19 < linha["preco"] < 21
    # a data de calculo e o ultimo pregao presente em cada mes
    assert set(uni["data"]) <= set(PREGOES) and uni["data"].max() == PREGOES[-1]
    assert uni.groupby(uni["data"].dt.to_period("M"))["data"].nunique().max() == 1


def test_cada_regra_isoladamente(cot):
    ultimo = lambda uni: set(uni[uni["data"] == uni["data"].max()]["ticker"])
    # afrouxando a liquidez, ILIQ3 entra
    assert "ILIQ3" in ultimo(u.universo_pit(cot, adtv_min=50_000))
    # afrouxando a presenca, PRES3 entra (negocia em ~50% dos pregoes)
    uni = u.universo_pit(cot, presenca_min=0.40)
    assert "PRES3" in ultimo(uni)
    pres = uni[(uni["data"] == uni["data"].max()) & (uni["ticker"] == "PRES3")]["presenca"].iloc[0]
    assert 0.45 < pres < 0.55
    # afrouxando o preco, CHEP3 entra
    assert "CHEP3" in ultimo(u.universo_pit(cot, preco_min=1.0))
    # aceitando RJ, RJUD3 entra
    assert "RJUD3" in ultimo(u.universo_pit(cot, codbdi=("02", "08")))
    # aceitando BDR/ETF/FII, eles entram (FII precisa tambem do CODBDI 12)
    uni = u.universo_pit(cot, tipos=("acao", "unit", "bdr", "etf", "fii"), codbdi=("02", "12"))
    assert {"AAPL34", "BOVA11", "HGLG11"} <= ultimo(uni)


def test_uma_classe_por_empresa(cot):
    # default: a unit EMPX11 (adtv 5 mi) vence a PN EMPX4 (3 mi)
    uni = u.universo_pit(cot)
    assert "EMPX11" in set(uni["ticker"]) and "EMPX4" not in set(uni["ticker"])
    # invertendo a liquidez, a PN vence
    cot2 = cot.copy()
    cot2.loc[cot2["ticker"] == "EMPX4", "volume"] = 9_000_000.0
    uni2 = u.universo_pit(cot2)
    assert "EMPX4" in set(uni2["ticker"]) and "EMPX11" not in set(uni2["ticker"])


def test_identidade_define_a_empresa(cot):
    # LIQD3 e EMPX11 passam a ser a mesma empresa pelo CNPJ: fica so a mais liquida (LIQD3)
    ident = pd.DataFrame([
        {"ticker": "LIQD3", "isin": "BRLIQDACNOR5", "cnpj": "11.111.111/0001-11", "data_ini": "2000-01-01", "data_fim": None},
        {"ticker": "EMPX11", "isin": "BREMPXCDAM15", "cnpj": "11.111.111/0001-11", "data_ini": "2000-01-01", "data_fim": None},
        {"ticker": "EMPX4", "isin": "BREMPXACNPR7", "cnpj": "22.222.222/0001-22", "data_ini": "2000-01-01", "data_fim": None},
    ])
    uni = u.universo_pit(cot, identidade=ident)
    ultimo = uni[uni["data"] == uni["data"].max()].set_index("ticker")
    assert set(ultimo.index) == {"LIQD3", "EMPX4"}
    assert ultimo.loc["LIQD3", "empresa"] == "11.111.111/0001-11"
    # vigencia respeitada: identidade que so vale a partir de 2030 nao muda nada hoje
    ident_fut = ident.assign(data_ini="2030-01-01")
    assert u.empresa_chave("LIQD3", "2024-01-31", ident_fut) == "LIQD"
    assert u.empresa_chave("LIQD3", "2024-01-31", ident) == "11.111.111/0001-11"
    assert u.empresa_chave("XXXX3", "2024-01-31", ident) == "XXXX"


def test_classificador_externo_dicionario(cot):
    uni = u.universo_pit(cot, classificar={"LIQD3": "bdr"})
    assert "LIQD3" not in set(uni["ticker"]) and "EMPX11" in set(uni["ticker"])


def test_sem_look_ahead(cot):
    corte = pd.Timestamp("2023-12-29")                  # ultimo pregao de dezembro nos dados
    ate = cot[pd.to_datetime(cot["data"]) <= corte]
    uni_ate = u.universo_pit(ate)
    # depois do corte, ILIQ3 vira liquida, LIQD3 some e EMPX4 fica mais liquida que a unit
    depois = cot.copy()
    depois["data"] = pd.to_datetime(depois["data"])
    m = depois["data"] > corte
    depois.loc[m & (depois["ticker"] == "ILIQ3"), "volume"] = 50_000_000.0
    depois.loc[m & (depois["ticker"] == "EMPX4"), "volume"] = 50_000_000.0
    depois = depois[~(m & (depois["ticker"] == "LIQD3"))]
    uni_depois = u.universo_pit(depois)
    a = uni_ate.reset_index(drop=True)
    b = uni_depois[uni_depois["data"] <= corte].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    # e o universo posterior de fato mudou (o teste nao e vazio)
    fim = uni_depois[uni_depois["data"] == uni_depois["data"].max()]
    assert {"ILIQ3", "EMPX4"} <= set(fim["ticker"]) and "LIQD3" not in set(fim["ticker"])


def test_universo_em_e_point_in_time(cot):
    uni = u.universo_pit(cot)
    datas = sorted(uni["data"].unique())
    assert u.universo_em(uni, datas[0] - pd.Timedelta(days=1)) == []
    assert u.universo_em(uni, datas[1] + pd.Timedelta(days=3)) == sorted(uni[uni["data"] == datas[1]]["ticker"])


def test_contagem_mensal_e_setores(cot):
    uni = u.universo_pit(cot)
    cont = u.contagem_mensal(uni)
    assert cont.index.is_monotonic_increasing and (cont == 2).all()
    assert len(cont) == uni["data"].nunique()
    assert len(u.contagem_mensal(pd.DataFrame(columns=u.COLUNAS))) == 0
    s = u.setores(uni)
    assert s["setor"].isna().all()
    s = u.setores(uni, {"LIQD": "Financeiro", "EMPX11": "Energia"})
    assert set(s["setor"].dropna()) == {"Financeiro", "Energia"}


def test_datas_explicitas_resolvem_para_o_pregao_anterior_sem_duplicar(cot):
    # 2023-03-25 (sabado) e 2023-03-26 (domingo) -> ambos usam sexta 2023-03-24, uma linha so
    uni = u.universo_pit(cot, datas=["2023-03-25", "2023-03-26"], min_pregoes=5)
    assert uni["data"].unique().tolist() == [pd.Timestamp("2023-03-24")]
    assert not uni.duplicated(["data", "ticker"]).any()
    assert len(u.universo_pit(cot, datas=["2022-12-01"])) == 0            # antes do primeiro pregao


def test_empresa_chave_aceita_indice_pre_calculado():
    ident = pd.DataFrame([
        {"ticker": "AAAA3", "cnpj": "1", "data_ini": "2000-01-01", "data_fim": "2010-12-31"},
        {"ticker": "AAAA3", "cnpj": "2", "data_ini": "2011-01-01", "data_fim": None},
        {"ticker": "BBBB3", "cnpj": None, "data_ini": None, "data_fim": None},
    ])
    idx = u._indice_identidade(ident)
    assert u.empresa_chave("AAAA3", "2005-06-30", idx) == "1"
    assert u.empresa_chave("AAAA3", "2020-06-30", idx) == "2"
    assert u.empresa_chave("AAAA3", "2020-06-30", ident) == "2"
    assert u.empresa_chave("AAAA3", None, idx) == "2"                   # sem data: vigencia mais recente
    assert u.empresa_chave("BBBB3", "2020-06-30", idx) == "BBBB"          # cnpj vazio -> prefixo
    assert u.empresa_chave("CCCC3", "2020-06-30", idx) == "CCCC"


def test_min_pregoes_e_entrada_vazia(cot):
    curto = cot[pd.to_datetime(cot["data"]) <= PREGOES[10]]
    assert len(u.universo_pit(curto)) == 0                      # 11 pregoes < min_pregoes
    assert len(u.universo_pit(curto, min_pregoes=5)) > 0
    assert len(u.universo_pit(pd.DataFrame(columns=cot.columns))) == 0

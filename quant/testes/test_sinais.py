"""Painel sintetico com estrutura conhecida para checar cada portao isoladamente.

Doze papeis, tres anos de pregoes, retornos plantados para que a ordem de momento seja
sabida de antemao, e um painel de fundamentos montado a mao com um caso para cada regra
(fluxo negativo, alavancagem alta, banco sem alavancagem, LPA zero, crescimento no fundo
do quartil, valor caro, vol alta).
"""
import numpy as np
import pandas as pd
import pytest

from quant import sinais as sg
from quant.dados import calendario

TICKERS = [f"TK{i:02d}3" for i in range(1, 13)]
INI, FIM = "2021-01-01", "2023-12-31"
DATAS_DEC = [pd.Timestamp(calendario.ultimo_pregao_do_mes(a, m))
             for a in (2022, 2023) for m in range(1, 13)]


def _pregoes():
    return [pd.Timestamp(d) for d in calendario.pregoes(INI, FIM)]


def _retornos(seed=7):
    """Retorno diario com uma DERIVA por papel: TK01 sobe mais, TK12 menos.

    Assim a ordem de momento e conhecida (TK01 > TK02 > ... > TK12) sem depender do ruido.
    """
    dias = _pregoes()
    rng = np.random.default_rng(seed)
    dados = {}
    for i, t in enumerate(TICKERS):
        deriva = (len(TICKERS) - i) * 0.0006          # TK01 tem a maior deriva
        dados[t] = deriva + rng.normal(0, 0.004, len(dias))
    return pd.DataFrame(dados, index=pd.DatetimeIndex(dias, name="data"))


def _universo(datas=None):
    datas = datas or DATAS_DEC
    linhas = []
    for d in datas:
        for i, t in enumerate(TICKERS):
            linhas.append({"data": d, "ticker": t, "isin": f"BR{t}ACNOR0", "empresa": f"CNPJ{i:02d}",
                           "adtv21": 30e6 - i * 2e6, "presenca": 1.0, "preco": 20.0, "n_pregoes": 252})
    return pd.DataFrame(linhas)


def _fundamentos(datas=None):
    """Um painel de fundamentos com um problema plantado por papel.

    TK01..TK06 sao boas; TK07 tem FCO negativo; TK08 tem FCF negativo; TK09 tem
    DL/EBITDA 5; TK10 e banco (DL/EBITDA NaN, ROE alto); TK11 tem LPA zero e lucro
    positivo; TK12 tem prejuizo.
    """
    datas = datas or DATAS_DEC
    linhas = []
    for d in datas:
        for i, t in enumerate(TICKERS, start=1):
            r = {"data": d, "cd_cvm": 1000 + i, "financeira": (i == 10),
                 "fco": 100.0, "fcf": 50.0, "dl_ebitda": 1.0, "divida_liquida": 100.0,
                 "retorno_capital": 0.30 - i * 0.01, "gpoa": 0.30 - i * 0.01,
                 "crescimento_receita": 0.20 - i * 0.01, "lpa": 2.0, "lucro_liquido": 200.0,
                 "bm": 0.5 + i * 0.05, "ev_ebit": 0.10 + i * 0.005, "fcf_yield": 0.05 + i * 0.002}
            if i == 7:
                r["fco"] = -10.0
            if i == 8:
                r["fcf"] = -10.0
            if i == 9:
                r["dl_ebitda"] = 5.0
            if i == 10:
                r["dl_ebitda"] = np.nan
                r["retorno_capital"] = 0.35
            if i == 11:
                r["lpa"] = 0.0
            if i == 12:
                r["lpa"] = -1.0
                r["lucro_liquido"] = -50.0
            linhas.append(r)
    return pd.DataFrame(linhas)


def _identidade():
    return pd.DataFrame([{"ticker": t, "cd_cvm": 1000 + i, "data_ini": pd.Timestamp("2000-01-01"),
                          "data_fim": pd.NaT}
                         for i, t in enumerate(TICKERS, start=1)])


@pytest.fixture(scope="module")
def base():
    ret = _retornos()
    return ret, _universo(), _fundamentos(), _identidade()


@pytest.fixture(scope="module")
def sinais(base):
    ret, uni, fund, ident = base
    return sg.painel(uni, ret, fundamentos=fund, identidade=ident)


# ─────────────────────────────────────────────────────────────
# Momento: a janela e a fronteira do mes
# ─────────────────────────────────────────────────────────────
def test_momento_usa_os_meses_m_menos_11_ate_m_menos_1(base):
    ret, _, _, _ = base
    mensal = sg.mensais(ret)
    d = pd.Timestamp("2023-06-30")
    mom = sg.momentum(mensal, [d])
    esperado = {}
    janela = mensal.loc[pd.Period("2022-07"):pd.Period("2023-05")]
    assert len(janela) == 11                                  # 11 meses, M-11 ate M-1
    for t in TICKERS:
        esperado[t] = float((1 + janela[t]).prod() - 1)
    for t in TICKERS:
        obtido = float(mom[(mom["data"] == d) & (mom["ticker"] == t)].iloc[0]["mom12"])
        assert abs(obtido - esperado[t]) < 1e-12


def test_momento_pula_o_mes_da_decisao(base):
    """Um choque no proprio mes M nao pode entrar no momento de M: e reversao, nao momento."""
    ret, _, _, _ = base
    d = pd.Timestamp("2023-06-30")
    normal = sg.momentum(sg.mensais(ret), [d])
    chocado = ret.copy()
    junho = (chocado.index >= pd.Timestamp("2023-06-01")) & (chocado.index <= d)
    chocado.loc[junho, TICKERS[-1]] = 0.05                     # +5% ao dia em junho
    com_choque = sg.momentum(sg.mensais(chocado), [d])
    a = float(normal[normal["ticker"] == TICKERS[-1]].iloc[0]["mom12"])
    b = float(com_choque[com_choque["ticker"] == TICKERS[-1]].iloc[0]["mom12"])
    assert abs(a - b) < 1e-12
    # e o choque de fato existiu (o teste nao e vazio): no mes seguinte ele entra
    d2 = pd.Timestamp(calendario.ultimo_pregao_do_mes(2023, 7))
    c = float(sg.momentum(sg.mensais(chocado), [d2])[lambda x: x["ticker"] == TICKERS[-1]].iloc[0]["mom12"])
    d_ = float(sg.momentum(sg.mensais(ret), [d2])[lambda x: x["ticker"] == TICKERS[-1]].iloc[0]["mom12"])
    assert c > d_


def test_ordem_de_momento_segue_a_deriva_plantada(sinais):
    ult = sg.em(sinais, DATAS_DEC[-1])
    ordem = ult.sort_values("mom12", ascending=False)["ticker"].tolist()
    assert ordem[0] == TICKERS[0] and ordem[-1] == TICKERS[-1]


def test_portao_de_momento_corta_a_metade_de_baixo(sinais):
    """Com 12 papeis o percentil do 6o mais fraco e exatamente 50, e o portao e ">= 50":
    passam 7 (a mediana fica dentro). E a leitura literal da especificacao."""
    ult = sg.em(sinais, DATAS_DEC[-1])
    assert ult["passa_momentum"].sum() == 7
    assert set(ult[ult["passa_momentum"]]["ticker"]) == set(TICKERS[:7])


# ─────────────────────────────────────────────────────────────
# Qualidade, crescimento, valor, vol
# ─────────────────────────────────────────────────────────────
def test_fluxo_de_caixa_negativo_reprova(sinais):
    ult = sg.em(sinais, DATAS_DEC[-1]).set_index("ticker")
    assert not ult.loc["TK073", "passa_qualidade"]              # FCO < 0
    assert not ult.loc["TK083", "passa_qualidade"]              # FCF < 0


def test_alavancagem_acima_de_tres_reprova_mas_banco_escapa(sinais):
    ult = sg.em(sinais, DATAS_DEC[-1]).set_index("ticker")
    assert not ult.loc["TK093", "passa_qualidade"]              # DL/EBITDA 5
    assert ult.loc["TK103", "financeira"] and ult.loc["TK103", "passa_qualidade"]


def test_alavancagem_nan_reprova_nao_financeira_com_divida():
    fund = pd.DataFrame([{"fco": 1.0, "fcf": 1.0, "dl_ebitda": np.nan, "divida_liquida": 100.0,
                          "retorno_capital": 0.2, "gpoa": 0.2, "financeira": False},
                         {"fco": 1.0, "fcf": 1.0, "dl_ebitda": np.nan, "divida_liquida": -50.0,
                          "retorno_capital": 0.2, "gpoa": 0.2, "financeira": False}],
                        index=["COM_DIVIDA", "SEM_DIVIDA"])
    passa, _, _ = sg.qualidade(fund)
    assert not passa["COM_DIVIDA"] and passa["SEM_DIVIDA"]


def test_lpa_zero_cai_para_lucro_liquido():
    """LPA 0 ou ausente e DESCONHECIDO, nao "prejuizo": a CVM publica 0,00 com frequencia
    e o portao literal esvaziaria o universo sozinho."""
    fund = pd.DataFrame([{"crescimento_receita": 0.5, "lpa": 0.0, "lucro_liquido": 100.0},
                         {"crescimento_receita": 0.5, "lpa": np.nan, "lucro_liquido": 100.0},
                         {"crescimento_receita": 0.5, "lpa": 0.0, "lucro_liquido": -100.0},
                         {"crescimento_receita": 0.5, "lpa": 2.0, "lucro_liquido": -100.0},
                         {"crescimento_receita": 0.5, "lpa": -1.0, "lucro_liquido": 100.0}],
                        index=["ZERO_LUCRO", "NAN_LUCRO", "ZERO_PREJUIZO", "LPA_MANDA", "LPA_NEGATIVO"])
    passa, reserva = sg.crescimento(fund)
    assert passa["ZERO_LUCRO"] and passa["NAN_LUCRO"] and not passa["ZERO_PREJUIZO"]
    assert passa["LPA_MANDA"] and not passa["LPA_NEGATIVO"]     # com LPA valido o LPA decide
    assert reserva["ZERO_LUCRO"] and reserva["NAN_LUCRO"] and not reserva["LPA_MANDA"]


def test_reserva_de_lpa_aparece_no_painel(sinais):
    ult = sg.em(sinais, DATAS_DEC[-1]).set_index("ticker")
    assert ult.loc["TK113", "lpa_por_reserva"]                  # LPA zero na fixture
    assert not ult.loc["TK013", "lpa_por_reserva"]              # LPA valido nao usa reserva
    assert not ult.loc["TK123", "passa_crescimento"]            # prejuizo reprova


def test_crescimento_corta_so_o_quartil_inferior(sinais):
    ult = sg.em(sinais, DATAS_DEC[-1])
    # crescimento cai com o indice: os 3 ultimos de 12 estao no quartil inferior
    reprovados = set(ult[~ult["passa_crescimento"]]["ticker"])
    assert {"TK103", "TK113", "TK123"} & reprovados            # pelo menos o fundo entra
    assert "TK013" not in reprovados


def test_valor_exclui_o_decil_mais_caro_e_desliga_sem_cobertura(sinais):
    ult = sg.em(sinais, DATAS_DEC[-1])
    assert ult["excluido_valor"].sum() >= 1
    # sem nenhuma metrica de valor o componente se desliga e nada e excluido
    fund = pd.DataFrame({"bm": [np.nan] * 5, "ev_ebit": [np.nan] * 5, "fcf_yield": [np.nan] * 5})
    score, excl, ativo = sg.valor(fund)
    assert ativo is False and not excl.any() and score.isna().all()


def test_vol_exclui_o_decil_mais_alto():
    v = pd.Series(np.arange(1, 21) / 100.0, index=[f"T{i}" for i in range(20)])
    fora = sg.baixo_risco(v)
    assert fora.sum() == 2 and fora.iloc[-1] and not fora.iloc[0]
    assert not sg.baixo_risco(pd.Series([np.nan, np.nan])).any()


def test_percentis_preservam_nan_e_tratam_empate():
    s = pd.Series([1.0, 1.0, 2.0, np.nan])
    p = sg.percentis(s)
    assert np.isnan(p.iloc[3]) and abs(p.iloc[0] - p.iloc[1]) < 1e-12 and p.iloc[2] > p.iloc[0]
    assert sg.percentis(pd.Series([np.nan, np.nan])).isna().all()


# ─────────────────────────────────────────────────────────────
# Sinais 6 e 7: interface desligada
# ─────────────────────────────────────────────────────────────
def test_aluguel_sem_historico_nao_exclui_ninguem_e_diz_que_nao_cobre(sinais):
    fora = sg.filtro_aluguel(None, DATAS_DEC, TICKERS)
    assert not fora.any() and fora.attrs["meses_cobertos"] == 0 and fora.attrs["testado"] is False
    assert sinais.attrs["aluguel_meses_cobertos"] == 0
    assert not sinais["excluido_aluguel"].any()


def test_insiders_e_stub_e_nao_muda_o_ranking(base, sinais):
    ret, uni, fund, ident = base
    b = sg.bonus_insiders(None, DATAS_DEC, TICKERS)
    assert b.attrs["disponivel"] is False and (b == 0.0).all()
    assert sinais.attrs["insiders_disponivel"] is False
    assert (sinais["bonus_insider"] == 0.0).all()


def test_seletor_de_classe_escolhe_a_mais_barata_contra_a_propria_mediana():
    cand = pd.DataFrame({"ticker": ["EMPX3", "EMPX4"], "ask": [10.0, 8.0], "fec": [10.0, 8.0],
                         "mediana_relativa": [1.0, 0.90]})
    assert sg.escolher_classe(cand) == "EMPX4"                 # negocia a 0,80 contra mediana 0,90
    cand2 = cand.assign(ask=[10.0, 9.5])
    assert sg.escolher_classe(cand2) == "EMPX3"                # a PN ficou cara contra a mediana
    assert sg.escolher_classe(pd.DataFrame()) is None
    sem_preco = pd.DataFrame({"ticker": ["A3"], "ask": [0.0], "fec": [0.0]})
    assert sg.escolher_classe(sem_preco) is None


# ─────────────────────────────────────────────────────────────
# Painel, ranking e point-in-time
# ─────────────────────────────────────────────────────────────
def test_painel_tem_o_esquema_e_uma_linha_por_papel_e_data(sinais):
    assert list(sinais.columns) == sg.COLUNAS
    assert len(sinais) == len(DATAS_DEC) * len(TICKERS)
    assert sinais.groupby("data")["ticker"].nunique().eq(len(TICKERS)).all()


def test_elegivel_e_a_intersecao_dos_portoes_e_exclusoes(sinais):
    esperado = (sinais["passa_momentum"] & sinais["passa_qualidade"] & sinais["passa_crescimento"]
                & ~sinais["excluido_valor"] & ~sinais["excluido_vol"] & ~sinais["excluido_aluguel"])
    assert (sinais["elegivel"] == esperado).all()
    assert sinais.loc[sinais["elegivel"], "motivo"].eq("").all()
    assert sinais.loc[~sinais["elegivel"], "motivo"].ne("").all()


def test_rank_so_existe_para_elegivel_e_comeca_em_um(sinais):
    ult = sg.em(sinais, DATAS_DEC[-1])
    assert ult.loc[~ult["elegivel"], "rank"].isna().all()
    elig = ult[ult["elegivel"]]
    if len(elig):
        assert elig["rank"].min() == 1.0 and elig["rank"].max() == float(len(elig))
        assert elig.sort_values("rank").iloc[0]["score"] == elig["score"].max()


def test_soma_z_ignora_portoes_e_muda_o_conjunto(sinais):
    z = sg.ranquear(sinais, modo="soma_z")
    d = DATAS_DEC[-1]
    a = set(sg.em(sinais, d).query("elegivel")["ticker"])
    b = set(sg.em(z, d).query("elegivel")["ticker"])
    assert b > a                                               # sem portoes sobra mais gente
    assert not sg.em(z, d)["score"].isna().all()


def test_score_redistribui_o_peso_quando_valor_nao_existe(base):
    ret, uni, fund, ident = base
    sem_valor = fund.assign(bm=np.nan, ev_ebit=np.nan, fcf_yield=np.nan)
    s = sg.painel(uni, ret, fundamentos=sem_valor, identidade=ident)
    ult = sg.em(s, DATAS_DEC[-1])
    esperado = (sg.PESOS["momentum"] / (sg.PESOS["momentum"] + sg.PESOS["qualidade"])
                * ult["pct_momentum"].fillna(0.0)
                + sg.PESOS["qualidade"] / (sg.PESOS["momentum"] + sg.PESOS["qualidade"])
                * ult["pct_qualidade"].fillna(0.0))
    assert (ult["score"] - esperado).abs().max() < 1e-12
    assert ult["pct_valor"].isna().all()


def test_sem_look_ahead_dado_futuro_nao_altera_o_passado(base):
    ret, uni, fund, ident = base
    corte = DATAS_DEC[11]
    datas_ate = [d for d in DATAS_DEC if d <= corte]
    a = sg.painel(uni[uni["data"] <= corte], ret[ret.index <= corte],
                  fundamentos=fund[fund["data"] <= corte], identidade=ident, datas=datas_ate)
    # depois do corte, TK12 dispara e TK01 desaba, e os fundamentos viram
    ret2 = ret.copy()
    m = ret2.index > corte
    ret2.loc[m, "TK123"] = 0.03
    ret2.loc[m, "TK013"] = -0.03
    fund2 = fund.copy()
    fund2.loc[fund2["data"] > corte, "fco"] = -1.0
    b_todo = sg.painel(uni, ret2, fundamentos=fund2, identidade=ident, datas=DATAS_DEC)
    b = b_todo[b_todo["data"] <= corte].reset_index(drop=True)
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b)
    # e o futuro de fato mudou (o teste nao e vazio)
    fim = sg.em(b_todo, DATAS_DEC[-1]).set_index("ticker")
    assert not fim["passa_qualidade"].any()


def test_fundamento_ausente_reprova_qualidade_mas_nao_quebra(base):
    ret, uni, _, ident = base
    s = sg.painel(uni, ret, fundamentos=None, identidade=ident)
    assert len(s) == len(DATAS_DEC) * len(TICKERS)
    assert not s["passa_qualidade"].any() and not s["elegivel"].any()
    assert s["rank"].isna().all()


def test_resumo_conta_o_funil(sinais):
    r = sg.resumo(sinais)
    assert len(r) == len(DATAS_DEC)
    assert (r["n_universo"] == len(TICKERS)).all()
    assert (r["n_elegivel"] <= r["n_universo"]).all()
    linha = r.iloc[-1]
    soma = sum(int(linha[c]) for c in ("momento", "qualidade", "crescimento", "caro", "volatil", "aluguel"))
    assert soma + int(linha["n_elegivel"]) == int(linha["n_universo"])


def test_entrada_vazia_mantem_o_esquema():
    assert list(sg.painel(pd.DataFrame(), pd.DataFrame()).columns) == sg.COLUNAS
    assert len(sg.painel(None, None)) == 0
    assert len(sg.momentum(pd.DataFrame(), [])) == 0
    assert len(sg.volatilidade(pd.DataFrame(), [])) == 0
    assert len(sg.painel_retornos(None)) == 0
    assert len(sg.resumo(None)) == 0


def test_gravar_e_carregar_parquet(sinais, tmp_path):
    caminho = str(tmp_path / "sinais.parquet")
    sg.gravar(sinais, caminho)
    lido = sg.carregar(caminho)
    assert list(lido.columns) == sg.COLUNAS and len(lido) == len(sinais)
    assert sg.carregar(str(tmp_path / "nao_existe.parquet")).empty

"""Regras de mao: por volatilidade e por queda do patrimonio. Causais, sem alavancagem, com custo e defasagem."""
import numpy as np
import pandas as pd
import pytest

from quant.risco import mao


def _serie(n=600, seed=3, vol=0.01, ini="2005-01-03"):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0003, vol, n), index=pd.bdate_range(ini, periods=n))


def _com_choque(n=600, corte=300, vol_baixa=0.006, vol_alta=0.03, seed=5):
    rng = np.random.default_rng(seed)
    x = np.r_[rng.normal(0.0004, vol_baixa, corte), rng.normal(0.0, vol_alta, 60), rng.normal(0.0004, vol_baixa, n - corte - 60)]
    return pd.Series(x, index=pd.bdate_range("2005-01-03", periods=n))


# ─────────────────────────────────────────────────────────────
# Volatilidade
# ─────────────────────────────────────────────────────────────
def test_sem_historia_a_exposicao_e_cheia():
    ex = mao.exposicao_por_vol(_serie(), janela=63)
    assert (ex["decidida"].iloc[:63] == 1.0).all() and (ex["aplicada"].iloc[:65] == 1.0).all()


def test_exposicao_nunca_passa_do_teto_e_nunca_e_negativa():
    ex = mao.exposicao_por_vol(_com_choque(), janela=21, teto=1.0)
    assert ex["decidida"].max() <= 1.0 + 1e-12 and ex["decidida"].min() > 0
    ex15 = mao.exposicao_por_vol(_com_choque(), janela=21, teto=1.5)
    assert ex15["decidida"].max() <= 1.5 + 1e-12 and ex15["decidida"].max() > 1.0


def test_vol_alta_diminui_a_mao_e_vol_baixa_volta_a_mao_cheia():
    r = _com_choque()
    ex = mao.exposicao_por_vol(r, janela=21)
    durante = ex["decidida"].iloc[330:360].mean()
    antes = ex["decidida"].iloc[200:290].mean()
    depois = ex["decidida"].iloc[500:].mean()
    assert durante < 0.6 * antes
    assert depois > 0.9


def test_alvo_e_a_media_da_propria_vol_ate_o_dia_anterior():
    r = _serie(300)
    m = mao.MaoVol(janela=21)
    vols, alvos = [], []
    for x in r:
        m.passo(x)
        vols.append(m.vol), alvos.append(m.alvo)
    vols, alvos = np.array(vols), np.array(alvos)
    t = 200
    assert abs(alvos[t] - np.nanmean(vols[:t])) < 1e-12           # media de vol_s para s <= t-1
    assert np.isnan(alvos[20])                                    # primeira vol valida: sem alvo ainda


def test_mudar_o_futuro_nao_muda_a_exposicao_do_passado_vol():
    r = _com_choque()
    base = mao.exposicao_por_vol(r, janela=63)
    r2 = r.copy()
    r2.iloc[420:] = np.random.default_rng(1).normal(-0.02, 0.05, len(r2) - 420)
    alt = mao.exposicao_por_vol(r2, janela=63)
    pd.testing.assert_frame_equal(base.iloc[:420], alt.iloc[:420])


def test_defasagem_de_dois_pregoes():
    r = _com_choque()
    ex = mao.exposicao_por_vol(r, janela=21, defasagem=2)
    pd.testing.assert_series_equal(ex["aplicada"].iloc[2:], ex["decidida"].shift(2).iloc[2:], check_names=False)
    assert ex["aplicada"].iloc[:2].tolist() == [1.0, 1.0]


def test_retorno_gerenciado_com_exposicao_um_e_sem_custo_e_o_original():
    r = _serie()
    rf = pd.Series(0.0004, index=r.index)
    tot = mao.retorno_gerenciado(r, pd.Series(1.0, index=r.index), rf, 0.01)
    assert np.allclose(tot, rf + r)                                  # exposicao constante: sem variacao, sem custo


def test_custo_so_cobra_quando_a_exposicao_muda():
    a = pd.Series([1.0, 1.0, 0.5, 0.5, 1.0])
    c = mao.custo_da_variacao(a, 0.01)
    assert c.tolist() == pytest.approx([0.0, 0.0, 0.005, 0.0, 0.005])


def test_meia_exposicao_e_meio_retorno_em_excesso():
    r = _serie()
    rf = pd.Series(0.0004, index=r.index)
    tot = mao.retorno_gerenciado(r, pd.Series(0.5, index=r.index), rf, 0.0)
    assert np.allclose(tot - rf, 0.5 * r)


def test_gerenciar_por_vol_reduz_vol_e_queda_maxima_num_mercado_com_choque_de_vol():
    r = _com_choque()
    g = mao.gerenciar_por_vol(r, janela=21)
    assert mao.metricas(g["total"])["mdd"] <= mao.metricas(r)["mdd"] + 1e-9
    assert g["exposicao"].min() < 1.0 and g["exposicao"].max() <= 1.0


# ─────────────────────────────────────────────────────────────
# Queda do patrimonio
# ─────────────────────────────────────────────────────────────
def test_queda_nao_corta_enquanto_a_queda_for_menor_que_o_limiar():
    m = mao.MaoQueda(limiar=0.10)
    assert [m.passo(x) for x in (100, 105, 98, 96)] == [1.0, 1.0, 1.0, 1.0]       # fundo de 8,6% desde 105


def test_queda_corta_ao_pela_metade_a_10_por_cento_e_volta_ao_recuperar_metade():
    m = mao.MaoQueda(limiar=0.10)
    saida = [m.passo(x) for x in (100, 110, 99, 97, 100, 103, 104, 106)]
    # pico 110; 99 = -10% -> corta; fundo 97; metade da distancia (110-97=13) = 103,5 -> volta a partir de 104
    assert saida == [1.0, 1.0, 0.5, 0.5, 0.5, 0.5, 1.0, 1.0]


def test_depois_da_volta_o_pico_recomeca_e_nao_recorta_no_dia_seguinte():
    m = mao.MaoQueda(limiar=0.10)
    for x in (100, 100, 60):            # queda de 40%: corta
        m.passo(x)
    assert m.cortado
    assert m.passo(80) == 1.0           # recuperou metade de (100-60)=40 -> 80: volta; pico reinicia em 80
    assert m.passo(79) == 1.0           # -1,25% desde o novo pico: nao corta (sem recorte todo dia)


def test_mudar_o_futuro_nao_muda_o_corte_do_passado():
    r = _com_choque()
    base = mao.gerenciar_por_queda(r - 0.0004, limiar=0.05)
    r2 = r.copy()
    r2.iloc[400:] = -0.03
    alt = mao.gerenciar_por_queda(r2 - 0.0004, limiar=0.05)
    pd.testing.assert_frame_equal(base.iloc[:400], alt.iloc[:400])


def test_gerenciar_por_queda_tem_defasagem_de_dois_pregoes():
    r = pd.Series([0.0] * 5 + [-0.15] + [0.0] * 6 + [0.0], index=pd.bdate_range("2020-01-01", periods=13))
    g = mao.gerenciar_por_queda(r, limiar=0.10, defasagem=2)
    # a queda acontece no dia 5; o corte e decidido no fechamento do dia 5 e rende so a partir do dia 7
    assert g["exposicao"].iloc[:7].tolist() == [1.0] * 7
    assert g["exposicao"].iloc[7] == 0.5


def test_sem_corte_com_limiar_infinito_e_igual_ao_original():
    r = _serie()
    g = mao.gerenciar_por_queda(r, limiar=10.0)
    assert np.allclose(g["total"], r)


# ─────────────────────────────────────────────────────────────
# Metricas
# ─────────────────────────────────────────────────────────────
def test_metricas_de_serie_construida_a_mao():
    idx = pd.bdate_range("2020-01-01", periods=504)
    r = pd.Series(np.tile([0.01, -0.005], 252), index=idx)
    m = mao.metricas(r)
    assert abs(m["sharpe"] - r.mean() / r.std(ddof=1) * np.sqrt(252)) < 1e-12
    assert m["mdd"] == pytest.approx(0.005, abs=1e-12) and m["pior_mes"] < 0.02


def test_giro_anual():
    a = pd.Series([1.0] * 126 + [0.5] * 126)
    assert mao.giro_anual(a) == pytest.approx(0.5 / 1.0)           # 0,5 de variacao em 1 ano de 252 dias

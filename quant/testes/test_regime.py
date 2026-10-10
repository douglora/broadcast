"""Testes do regime (ALTA/NEUTRO/BAIXA) e do plano de protecao em mini-indice."""
import numpy as np
import pandas as pd

from quant import regime as rg


def _indice(retornos, ini="2005-01-03"):
    idx = pd.bdate_range(ini, periods=len(retornos))
    return pd.Series(100.0 * np.cumprod(1.0 + np.asarray(retornos)), index=idx, name="indice")


def _ex(retornos, ini="2005-01-03"):
    idx = pd.bdate_range(ini, periods=len(retornos))
    return pd.Series(np.asarray(retornos, dtype=float), index=idx)


def _mercado_em_tres_fases(seed=7):
    """300 dias de alta firme, 300 de queda firme, 300 de alta firme, com ruido."""
    rng = np.random.default_rng(seed)
    ruido = rng.normal(0, 0.008, 900)
    drift = np.r_[np.full(300, 0.0012), np.full(300, -0.0015), np.full(300, 0.0012)]
    return drift + ruido


# ─────────────────────────────────────────────────────────────
# Nao olhar o futuro
# ─────────────────────────────────────────────────────────────
def test_mudar_o_futuro_nao_muda_o_regime_do_passado():
    r = _mercado_em_tres_fases()
    base = rg.detectar(_indice(r), _ex(r))
    for corte in (350, 520, 640, 800):
        r2 = r.copy()
        rng = np.random.default_rng(99)
        r2[corte:] = rng.normal(-0.01, 0.03, len(r2) - corte)      # futuro inteiramente diferente
        alt = rg.detectar(_indice(r2), _ex(r2))
        pd.testing.assert_frame_equal(base.iloc[:corte], alt.iloc[:corte])


def test_plano_do_passado_nao_depende_do_futuro():
    r = _mercado_em_tres_fases()
    p1 = _indice(r)
    det = rg.detectar(p1, _ex(r))
    mp = rg.mapa(exposicao_baixa=0.55, razao_baixa=1.0)
    plano = rg.plano_protecao(p1, det["estado"], mp, stop_atr=3.0)
    corte = 600
    r2 = r.copy()
    r2[corte:] = np.random.default_rng(5).normal(0.02, 0.04, len(r2) - corte)
    p2 = _indice(r2)
    det2 = rg.detectar(p2, _ex(r2))
    plano2 = rg.plano_protecao(p2, det2["estado"], mp, stop_atr=3.0)
    cols = ["razao_decidida", "razao_exec", "exposicao_sinal", "stopado"]
    pd.testing.assert_frame_equal(plano[cols].iloc[:corte], plano2[cols].iloc[:corte])


def test_votos_so_usam_janelas_que_terminam_em_t():
    r = _mercado_em_tres_fases()
    v1 = rg.votos(_indice(r), _ex(r))
    r2 = r.copy()
    r2[500:] = 0.05
    v2 = rg.votos(_indice(r2), _ex(r2))
    pd.testing.assert_frame_equal(v1.iloc[:500], v2.iloc[:500])


# ─────────────────────────────────────────────────────────────
# Detector
# ─────────────────────────────────────────────────────────────
def test_sem_historia_nao_ha_regime():
    r = _mercado_em_tres_fases()
    det = rg.detectar(_indice(r), _ex(r))
    assert det["estado"].iloc[:250].isna().all()          # 252 pregoes de historia para o voto de 12 meses
    assert det["estado"].iloc[260:].notna().all()


def test_mercado_em_alta_e_alta_e_em_queda_e_baixa():
    r = _mercado_em_tres_fases()
    det = rg.detectar(_indice(r), _ex(r))
    assert det["estado"].iloc[290] == rg.ALTA
    assert det["estado"].iloc[580] == rg.BAIXA            # bem dentro da fase de queda
    assert det["estado"].iloc[880] == rg.ALTA             # recuperou


def test_classificar_pela_soma_dos_votos():
    v = pd.DataFrame({k: [1.0, 1.0, 0.0, 0.0, 1.0, 1.0] for k in rg.NOMES_VOTOS})
    v.loc[2] = [1.0, 0.0, 1.0, 0.0]          # 2 votos -> NEUTRO
    v.loc[3] = [0.0, 0.0, 0.0, 1.0]          # 1 voto -> BAIXA
    v.loc[4] = [1.0, 1.0, 1.0, 0.0]          # 3 votos -> ALTA
    v.loc[5] = [np.nan, 1.0, 1.0, 1.0]       # voto faltando -> sem regime
    assert rg.classificar(v).tolist()[:5] == [rg.ALTA, rg.ALTA, rg.NEUTRO, rg.BAIXA, rg.ALTA]
    assert pd.isna(rg.classificar(v).iloc[5])


def test_confirmacao_exige_dias_seguidos():
    bruto = pd.Series([rg.ALTA] * 5 + [rg.BAIXA] * 2 + [rg.ALTA] * 3 + [rg.BAIXA] * 6)
    est = rg.confirmar(bruto, dias=3)
    # a queda de 2 dias (posicoes 5 e 6) nao troca; a de 6 dias (10 a 15) troca no terceiro dia seguido (12)
    assert est.tolist() == [rg.ALTA] * 12 + [rg.BAIXA] * 4


def test_confirmacao_um_dia_e_identidade():
    bruto = pd.Series([rg.ALTA, rg.BAIXA, rg.ALTA, rg.NEUTRO])
    assert rg.confirmar(bruto, dias=1).tolist() == bruto.tolist()


def test_trocas_conta_so_mudancas():
    est = pd.Series([np.nan, rg.ALTA, rg.ALTA, rg.BAIXA, rg.BAIXA, rg.ALTA])
    assert rg.trocas(est) == 2
    assert rg.trocas(pd.Series([rg.ALTA] * 5)) == 0


def test_indice_total_compoe_excesso_e_cdi():
    ex = _ex([0.01, -0.02, 0.0])
    cdi = _ex([0.0004, 0.0004, 0.0004])
    n = rg.indice_total(ex, cdi)
    esperado = 100 * (1.0104) * (0.9804) * (1.0004)
    assert abs(n.iloc[-1] - esperado) < 1e-9


def test_amplitude_media_e_media_do_modulo_da_variacao():
    p = pd.Series([100.0, 101.0, 99.0, 100.0, 102.0], index=pd.bdate_range("2020-01-01", periods=5))
    a = rg.amplitude_media(p, janela=4)
    assert abs(a.iloc[-1] - (1 + 2 + 1 + 2) / 4) < 1e-12
    assert a.iloc[:3].isna().all()


# ─────────────────────────────────────────────────────────────
# Plano de protecao
# ─────────────────────────────────────────────────────────────
def _plano_manual(precos, estados, mp, stop=None):
    idx = pd.bdate_range("2020-01-01", periods=len(precos))
    p = pd.Series(np.asarray(precos, dtype=float), index=idx)
    e = pd.Series(estados, index=idx, dtype=object)
    return rg.plano_protecao(p, e, mp, stop_atr=stop, janela_amd=3)


def test_razao_em_vigor_e_a_decidida_no_pregao_anterior():
    mp = rg.mapa(razao_baixa=1.0, razao_neutro=0.5)
    estados = [rg.ALTA] * 3 + [rg.BAIXA] * 3 + [rg.NEUTRO] * 3
    pl = _plano_manual([100] * 9, estados, mp)
    assert pl["razao_decidida"].tolist() == [0, 0, 0, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5]
    assert pl["razao_exec"].tolist() == [0, 0, 0, 0, 1.0, 1.0, 1.0, 0.5, 0.5]


def test_stop_reduz_para_a_razao_do_neutro_quando_o_indice_sobe_demais():
    mp = rg.mapa(razao_baixa=1.0, razao_neutro=0.5)
    # BAIXA desde o dia 2; a venda entra em vigor no dia 3 (preco 100); o indice sobe devagar e depois dispara
    precos = [100, 100, 100, 100, 100.5, 101, 101.5, 108, 108, 108, 108]
    estados = [rg.NEUTRO, rg.NEUTRO] + [rg.BAIXA] * 9
    pl = _plano_manual(precos, estados, mp, stop=3.0)
    assert pl["stopado"].any()
    d = int(np.argmax(pl["stopado"].to_numpy()))
    assert pl["razao_decidida"].iloc[d] == 0.5
    assert pl["razao_exec"].iloc[d + 1] == 0.5          # vale no pregao seguinte


def test_sem_stop_a_venda_segue_o_regime_mesmo_com_o_indice_disparando():
    mp = rg.mapa(razao_baixa=1.0, razao_neutro=0.5)
    precos = [100, 100, 100, 100, 100.5, 101, 101.5, 108, 108, 108, 108]
    estados = [rg.NEUTRO, rg.NEUTRO] + [rg.BAIXA] * 9
    pl = _plano_manual(precos, estados, mp, stop=None)
    assert not pl["stopado"].any()
    assert pl["razao_exec"].iloc[-1] == 1.0


def test_stop_rearma_quando_o_indice_volta_abaixo_do_nivel_da_venda():
    mp = rg.mapa(razao_baixa=1.0, razao_neutro=0.5)
    precos = [100, 100, 100, 100, 100.5, 101, 101.5, 108, 108, 108, 99, 98, 98]
    estados = [rg.NEUTRO, rg.NEUTRO] + [rg.BAIXA] * 11
    pl = _plano_manual(precos, estados, mp, stop=3.0)
    assert pl["stopado"].any()
    assert pl["stopado"].iloc[-1] == False            # rearmou
    assert pl["razao_decidida"].iloc[-1] == 1.0


def test_stop_e_resetado_quando_o_regime_sai_de_baixa():
    mp = rg.mapa(razao_baixa=1.0, razao_neutro=0.5)
    precos = [100, 100, 100, 100, 100.5, 101, 101.5, 108, 108, 108, 108, 108]
    estados = [rg.NEUTRO, rg.NEUTRO] + [rg.BAIXA] * 7 + [rg.ALTA] * 3
    pl = _plano_manual(precos, estados, mp, stop=3.0)
    assert not pl["stopado"].iloc[-1]
    assert pl["razao_decidida"].iloc[-1] == 0.0       # ALTA: protecao zerada


def test_eventos_de_stop_conta_acionamentos():
    mp = rg.mapa(razao_baixa=1.0, razao_neutro=0.5)
    precos = [100, 100, 100, 100, 100.5, 101, 101.5, 108, 108, 108, 99, 98, 98]
    estados = [rg.NEUTRO, rg.NEUTRO] + [rg.BAIXA] * 11
    pl = _plano_manual(precos, estados, mp, stop=3.0)
    assert rg.eventos_de_stop(pl) == 1


def test_exposicao_do_sinal_segue_o_mapa():
    mp = rg.mapa(exposicao_baixa=0.55)
    estados = [rg.ALTA, rg.NEUTRO, rg.BAIXA, np.nan]
    pl = _plano_manual([100] * 4, estados, mp)
    assert pl["exposicao_sinal"].tolist() == [0.70, 0.70, 0.55, 0.70]      # sem regime = NEUTRO


def test_mapa_alta_zera_a_protecao():
    mp = rg.mapa()
    assert mp[rg.ALTA]["razao"] == 0.0
    assert mp[rg.NEUTRO]["razao"] == 0.5

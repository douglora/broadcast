"""Swing: tamanho pelo risco, regras de saida (ao vivo e na pesquisa dao a mesma resposta), prazo de no maximo 10 pregoes e os setups sem olhar o futuro."""
import numpy as np
import pandas as pd
import pytest

from quant.swing import estado as est
from quant.swing import posicao, setups, simulador, tamanho
from quant.testes.swing_fixture import painel_sintetico


# ── tamanho ───────────────────────────────────────────────────
def test_tamanho_pelo_risco_em_lote():
    # R$ 300 de risco, stop a R$ 1,50 do preco: 200 acoes (R$ 4.000 a R$ 20), lote de 100
    qtd, valor = tamanho.quantidade(60_000, 20.0, 1.5)
    assert (qtd, valor) == (200, 4000.0)
    assert qtd * 1.5 <= 0.005 * 60_000 + 1e-9                    # nunca arrisca mais que 0,5%


def test_tamanho_respeita_o_teto_por_papel():
    qtd, valor = tamanho.quantidade(60_000, 20.0, 0.10)          # stop curto pediria 3.000 acoes (R$ 60 mil): o teto de 12% corta
    assert valor <= 0.12 * 60_000 + 1e-9 and qtd == 300


def test_tamanho_acima_de_30_reais_e_unidade():
    qtd, valor = tamanho.quantidade(60_000, 80.0, 4.0)
    assert qtd == 75 and valor == 6000.0                          # 300/4 = 75 acoes, sem lote de 100


def test_tamanho_que_nao_cabe_um_lote_e_zero():
    assert tamanho.quantidade(60_000, 20.0, 10.0) == (0, 0.0)     # 300/10 = 30 acoes: menos que um lote
    assert tamanho.quantidade(0, 20.0, 1.0) == (0, 0.0) and tamanho.quantidade(60_000, 20.0, 0) == (0, 0.0)


def test_cabe_limita_posicoes_exposicao_e_caixa():
    assert tamanho.cabe(5000, 0, 60_000, 0)
    assert not tamanho.cabe(5000, 0, 60_000, 10)                  # 10 posicoes: cheio
    assert not tamanho.cabe(5000, 58_000, 60_000, 3)              # passaria do limite de exposicao
    assert not tamanho.cabe(5000, 0, 60_000, 3, caixa=4000)       # sem caixa


# ── prazo e datas ─────────────────────────────────────────────
def test_prazo_nunca_passa_de_10_pregoes():
    posicao.validar(10, 1.0, 2.0)
    with pytest.raises(ValueError):
        posicao.validar(11, 1.0)
    with pytest.raises(ValueError):
        posicao.validar(0, 1.0)
    with pytest.raises(ValueError):
        posicao.validar(5, 0.0)                                   # swing sem stop nao existe
    for nid, par in sum((list(n.items()) for n in setups.NUCLEOS.values()), []):
        assert par["prazo"] <= posicao.PRAZO_MAX, nid


def test_decimo_pregao_conta_o_dia_da_entrada_e_pula_feriado():
    # entrada na terca 13/10/2026; a segunda 12/10 e feriado e nao entra na conta; o 10o pregao e 26/10
    assert str(est.prazo_ate("2026-10-13", 10)) == "2026-10-26"
    assert str(est.prazo_ate("2026-10-13", 1)) == "2026-10-13"
    assert est.pregoes_na_posicao("2026-10-13", "2026-10-13") == 1
    assert est.pregoes_na_posicao("2026-10-13", "2026-10-26") == 10
    assert est.pregoes_restantes("2026-10-13", "2026-10-26", 10) == 0
    assert est.pregoes_restantes("2026-10-13", "2026-10-14", 10) == 8


# ── saida ao vivo ─────────────────────────────────────────────
def _pos(**kw):
    p = est.nova_posicao("C1", "AAAA3", "2026-10-09", 20.0, 2.0, 4.0, 10, 100, "2026-10-13", 2e7, modo="capital", porque="teste")
    p.update(kw)
    return p


def test_stop_alvo_e_tempo_ao_vivo():
    p = _pos()
    assert p["stop"] == 18.0 and p["alvo"] == 24.0 and p["prazo_ate"] == "2026-10-26"
    assert posicao.decidir_saida(p, 19.0, 20.0, "2026-10-14", "11:00") is None
    assert posicao.decidir_saida(p, 17.9, 19.0, "2026-10-14", "11:00") == (17.9, "stop")           # a mercado: no ultimo preco visto
    assert posicao.decidir_saida(p, 24.3, 21.0, "2026-10-14", "11:00") == (24.0, "alvo")           # limitada: no preco do alvo
    assert posicao.decidir_saida(p, 21.0, 20.5, "2026-10-26", "11:00") is None                     # no ultimo dia, antes do leilao, ainda nao
    assert posicao.decidir_saida(p, 21.0, 20.5, "2026-10-26", "16:50") == (21.0, "tempo")
    assert posicao.decidir_saida(p, 21.0, 20.5, "2026-10-27", "10:05") == (21.0, "tempo")           # passou do prazo (robo ficou desligado): sai ja


def test_gap_contra_o_stop_sai_na_abertura_pior_que_o_stop():
    p = _pos()
    assert posicao.decidir_saida(p, 17.0, 17.2, "2026-10-14", "10:01") == (17.2, "gap_stop")
    assert posicao.decidir_saida(p, 25.0, 24.8, "2026-10-14", "10:01") == (24.8, "gap_alvo")


def test_no_dia_da_entrada_nao_ha_gap_so_stop_e_alvo():
    p = _pos()
    # abertura abaixo do stop no PROPRIO dia da entrada nao e "gap": a entrada e na abertura, o stop e dali para baixo
    assert posicao.decidir_saida(p, 19.5, 17.0, "2026-10-13", "10:30") is None
    assert posicao.decidir_saida(p, 17.9, 20.0, "2026-10-13", "10:30") == (17.9, "stop")


def test_posicao_sem_alvo_so_sai_por_stop_ou_tempo():
    p = est.nova_posicao("G1", "AAAA3", "2026-10-28", 20.0, 3.0, None, 4, 100, "2026-10-29", 2e7, modo="capital")
    assert p["alvo"] is None and posicao.decidir_saida(p, 99.0, 20.0, "2026-10-30", "11:00") is None
    assert str(p["prazo_ate"]) == str(est.prazo_ate("2026-10-29", 4))


def test_resultado_liquido_de_custos_dos_dois_lados():
    p = _pos()
    f = est.fechar(p, 22.0, "tempo", "2026-10-20")
    bruto = (22.0 - 20.0) * 100
    assert f["custo_entrada"] > 0 and f["custo_saida"] > 0
    assert f["resultado_rs"] == pytest.approx(bruto - f["custo_entrada"] - f["custo_saida"])
    assert f["r_multiplo"] == pytest.approx(f["resultado_rs"] / (2.0 * 100))


# ── a regra de uma operacao e a da pesquisa ───────────────────
def test_saida_da_operacao_e_igual_ao_simulador_da_pesquisa():
    p = painel_sintetico(n=400, seed=5, vol=0.03)
    ind = setups.indicadores(p)
    rng = np.random.default_rng(3)
    sig = np.zeros(p.O.shape, dtype=bool)
    sig[250:380, :3] = rng.random((130, 3)) < 0.15
    sig &= ind["completo"] & np.isfinite(ind["atr"])
    for stop_atr, alvo_atr, prazo in ((1.5, 2.0, 5), (2.0, 3.0, 10), (3.0, None, 4)):
        ops = simulador.operacoes(p, sig, stop_atr, alvo_atr, prazo, ind["atr"])
        assert len(ops) > 20
        for r in ops.itertuples():
            sl = slice(r.i_entrada, r.i_entrada + prazo)
            O, H, L, C = (a[sl, r.j] for a in (p.O, p.H, p.L, p.C))
            e = O[0]
            stop_rel = 1.0 - stop_atr * r.atr / e
            alvo_rel = None if not alvo_atr else 1.0 + alvo_atr * r.atr / e
            k, preco_rel, motivo = est.saida_da_operacao(O / e, H / e, L / e, C / e, stop_rel, alvo_rel, prazo)
            assert motivo == r.evento and k + 1 == r.pregoes
            assert preco_rel * e == pytest.approx(r.saida, rel=1e-9)


# ── os setups nao olham o futuro ──────────────────────────────
def test_sinais_nao_mudam_se_o_futuro_mudar():
    p = painel_sintetico(n=420, seed=9, vol=0.035)
    ind = setups.indicadores(p)
    corte = 350
    futuro = painel_sintetico(n=420, seed=9, vol=0.035)
    futuro.O[corte + 1:], futuro.H[corte + 1:], futuro.L[corte + 1:], futuro.C[corte + 1:] = 7.0, 7.5, 6.5, 7.2          # muda tudo depois do corte
    ind2 = setups.indicadores(futuro)
    achou = 0
    for v in setups.variantes():
        if v["familia"] == "d_resultado":
            continue
        a, b = setups.sinais(p, ind, v), setups.sinais(futuro, ind2, v)
        assert (a[:corte + 1] == b[:corte + 1]).all(), v["id"]
        achou += int(a[:corte + 1].sum())
    assert achou > 0                                               # o teste olhou sinais de verdade, nao so matrizes vazias


def test_sao_39_variantes_em_13_setups():
    vs = setups.variantes()
    assert len(vs) == 39 and len({v["nucleo"] for v in vs}) == 13
    assert max(len([v for v in vs if v["familia"] == f]) for f in {v["familia"] for v in vs}) <= 6      # ate 6 por familia

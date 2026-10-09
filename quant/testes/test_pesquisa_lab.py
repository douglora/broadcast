"""O laboratorio de pesquisa (quant/pesquisa/lab.py): as contas de execucao tem de ser as conservadoras."""
import numpy as np
import pandas as pd
import pytest

from quant.pesquisa import lab


def _dia(barras, inicio="2024-03-04 09:00"):
    idx = pd.date_range(inicio, periods=len(barras), freq="min", name="hora")
    o, h, l, c = zip(*barras)
    return pd.DataFrame({"o": o, "h": h, "l": l, "c": c, "n": 10.0, "v": 100.0}, index=idx)


def _sinal(m, onde, lado):
    s = np.zeros(len(m))
    s[onde] = lado
    return s


PARADO = (5000.0, 5000.0, 5000.0, 5000.0)


def test_entrada_a_mercado_alvo_so_quando_o_preco_passa_um_tick():
    # sinal na barra 20 (9h20); entra na abertura da 21 (5.000) com 1 tick contra = 5.000,5; alvo de 4 pontos = 5.004,5
    b = [PARADO] * 21 + [(5000.0, 5002.0, 5000.0, 5002.0), (5002.0, 5004.5, 5002.0, 5004.5), (5004.5, 5005.0, 5004.0, 5005.0)] + [PARADO] * 5
    m = _dia(b)
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, alvo=4.0)
    assert len(t) == 1 and t.entrada[0] == 5000.5 and t.saida[0] == "alvo" and t.pts[0] == 4.0 and t.hora[0] == "09:20"
    assert t.minutos[0] == 2                                   # na barra 22 o preco so TOCOU 5.004,5: nao executou; passou na 23
    t2 = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, alvo=4.0, alvo_no_toque=True)
    assert t2.minutos[0] == 1
    r = lab.medir(t)
    assert r.res[0] == pytest.approx(4.0 * 10 * 2 - 4.8)


def test_stop_vem_primeiro_e_abertura_alem_do_stop_sai_na_abertura():
    b = [PARADO] * 21 + [(5000.0, 5006.0, 4994.0, 5005.0)] + [PARADO] * 5         # mesma barra bate o alvo e o stop: vale o stop
    m = _dia(b)
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, alvo=4.0)
    assert t.saida[0] == "stop" and t.pts[0] == pytest.approx(-6.0 - 0.5)          # stop em 4.994,5, sai 1 tick pior
    b = [PARADO] * 21 + [(5000.0, 5000.0, 4999.0, 4999.0), (4990.0, 4991.0, 4989.0, 4990.0)] + [PARADO] * 5
    m = _dia(b)
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0)
    assert t.saida[0] == "stop" and t.pts[0] == pytest.approx(4990.0 - 0.5 - 5000.5)   # abriu abaixo do stop: sai na abertura


def test_venda_tempo_janela_e_uma_posicao_por_vez():
    b = [PARADO] * 40
    m = _dia(b)
    s = _sinal(m, 20, -1)
    s[22] = -1                                                   # segundo sinal com a posicao aberta: ignorado
    t = lab.negocios(m, s, stop=6.0, tempo=10)
    assert len(t) == 1 and t.lado[0] == "V" and t.entrada[0] == 4999.5 and t.saida[0] == "tempo" and t.pts[0] == -1.0
    # sinal antes das 9h15 e depois da ultima entrada nao opera
    assert len(lab.negocios(m, _sinal(m, 5, 1), stop=6.0)) == 0
    assert len(lab.negocios(m, _sinal(m, 30, 1), stop=6.0, ult="09:30")) == 0
    # zera no fim da janela, a mercado
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, zerar="09:30")
    assert t.saida[0] == "fim da janela" and t.pts[0] == -1.0


def test_entrada_por_ordem_parada_exige_passar_um_tick():
    # compra parada em 4.998: a barra 21 so toca 4.998 (nao executa); a 22 vai a 4.997,5 (executa a 4.998, sem deslize)
    b = [PARADO] * 21 + [(5000.0, 5000.0, 4998.0, 4999.0), (4999.0, 4999.0, 4997.5, 4998.5), (4998.5, 5003.0, 4998.5, 5003.0)] + [PARADO] * 5
    m = _dia(b)
    lim = np.full(len(m), np.nan)
    lim[20] = 4998.0
    t = lab.negocios(m, _sinal(m, 20, 1), stop=5.0, alvo=3.0, limite=lim, validade=5)
    assert len(t) == 1 and t.entrada[0] == 4998.0 and t.saida[0] == "alvo" and t.pts[0] == 3.0
    # sem passar o tick dentro da validade, nao ha negocio
    b = [PARADO] * 21 + [(5000.0, 5000.0, 4998.0, 4999.0)] * 8
    assert len(lab.negocios(_dia(b), _sinal(_dia(b), 20, 1), stop=5.0, limite=lim[:29], validade=5)) == 0


def test_arrasto_sobe_o_stop_so_na_barra_seguinte():
    b = [PARADO] * 21 + [(5000.0, 5008.0, 5000.0, 5008.0), (5008.0, 5008.0, 5004.0, 5004.0)] + [PARADO] * 5
    m = _dia(b)
    t = lab.negocios(m, _sinal(m, 20, 1), stop=6.0, arrasto=3.0)
    assert t.saida[0] == "stop movel" and t.pts[0] == pytest.approx(5005.0 - 0.5 - 5000.5)   # melhor 5.008, stop movel em 5.005


def test_sem_futuro_pega_regra_que_olha_a_barra_seguinte_e_evento_mede_sem_custo():
    rng = np.random.default_rng(3)
    c = 5000 + np.cumsum(rng.normal(0, 1, 3000)).round(1)
    idx = pd.date_range("2024-03-04 09:00", periods=3000, freq="min", name="hora")
    m = pd.DataFrame({"o": np.r_[5000.0, c[:-1]], "h": c + 1, "l": c - 1, "c": c, "n": 10.0, "v": 100.0}, index=idx)
    honesta = lambda x: np.sign(x.c - x.c.shift(3)).fillna(0).to_numpy()            # noqa: E731
    trapaca = lambda x: np.sign(x.c.shift(-1) - x.c).fillna(0).to_numpy()           # noqa: E731
    assert lab.sem_futuro(honesta, m) is True
    with pytest.raises(AssertionError):
        lab.sem_futuro(trapaca, m)
    tab = lab.evento(m, np.ones(len(m), bool), trapaca(m), horizontes=(1,), ini="00:00", ult="23:59", registrar=False)
    assert tab.media_pts[0] > 0.5                                 # quem ve o futuro ganha: o estudo de evento mede direito

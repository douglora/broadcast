import math

import pandas as pd

from livro import indicadores as ind
from tests.conftest import ler_serie_fixture


def serie(valores, inicio="2025-01-01"):
    datas = pd.bdate_range(inicio, periods=len(valores))
    return ind.para_df([[d.date().isoformat(), v, v, v, v, v, 100] for d, v in zip(datas, valores)])


def test_janelas_vale3_fixture():
    df = ler_serie_fixture("VALE3.SA")
    j = ind.janelas(df)
    assert j["data"] == "2026-09-18"
    assert j["ultimo"] == 73.61
    for k in ("dia", "1s", "1m", "6m", "1a", "ytd"):
        assert k in j and j[k] is not None
    # dia = 73,61 / 73,00 - 1
    assert abs(j["dia"] - (73.61 / 73.0 - 1)) < 1e-9
    # 1a usa o fechamento de <= 365 dias corridos atras
    assert j["1a"] > 0.2


def test_ytd_usa_ultimo_fechamento_do_ano_anterior():
    datas = ["2025-12-29", "2025-12-30", "2026-01-02", "2026-01-05"]
    df = ind.para_df([[d, p, p, p, p, p, 0] for d, p in zip(datas, [100, 110, 120, 121])])
    j = ind.janelas(df)
    assert abs(j["ytd"] - (121 / 110 - 1)) < 1e-9
    # virada de ano: em 2027 a base passa a ser o ultimo fechamento de 2026
    datas2 = datas + ["2026-12-30", "2027-01-04"]
    df2 = ind.para_df([[d, p, p, p, p, p, 0] for d, p in zip(datas2, [100, 110, 120, 121, 130, 143])])
    assert abs(ind.janelas(df2)["ytd"] - (143 / 130 - 1)) < 1e-9


def test_mm_e_cruzamento():
    vals = [100.0] * 210 + [95.0, 94.0]
    df = serie(vals)
    m = ind.mm(df["adj"], 200)
    assert not math.isnan(m.iloc[-1])
    assert ind.dias_abaixo(df["adj"], m, 0.005) == 2
    assert ind.cruzou(df["adj"], m, 0.005) is None  # cruzou ontem, nao hoje


def test_rsi_limites():
    up = serie([100 + i for i in range(40)])
    assert ind.rsi_wilder(up["adj"]).iloc[-1] > 90
    down = serie([100 - i for i in range(40)])
    assert ind.rsi_wilder(down["adj"]).iloc[-1] < 10


def test_zscore_exclui_o_dia_e_tem_piso():
    vals = [100 * (1.001 ** i) for i in range(30)] + [100 * (1.001 ** 30) * 0.95]
    df = serie(vals)
    z = ind.zscore_dia(df["adj"], 20, piso=0.006)
    assert z.iloc[-1] < -5  # queda de 5% contra sigma no piso de 0,6%


def test_drawdown_e_sequencia():
    vals = [100, 105, 110, 108, 100, 90, 88]
    df = serie(vals)
    dd, pico, data = ind.drawdown(df["close"])
    assert abs(dd - (88 / 110 - 1)) < 1e-9 and pico == 110
    n, acum = ind.sequencia(df["close"])
    assert n == -4 and abs(acum - (88 / 110 - 1)) < 1e-9


def test_curvas_helpers():
    assert ind.bps(14.20, 14.05) == 15.0
    assert abs(ind.breakeven(13.85, 7.43) - 5.976) < 0.01
    assert ind.percentil([1, 2, 3, 4, 5], 4) == 80.0
    dv = ind.dv01_empirico([7.0, 7.1, 7.2, 7.15], [3000, 2980, 2960, 2970])
    assert dv is not None and 0.0005 < dv < 0.01

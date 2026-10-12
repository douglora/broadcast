"""Variantes so medidas da reversao do dado (12/10/2026): a regra base dispara; cada filtro so tira dias, nunca muda o lado."""
import numpy as np
import pandas as pd

from quant.dados import calendario_eua as ce
from quant.pesquisa import regimes
from quant.pesquisa.regras import dado_variantes as dv


def _barras(dias=("2026-10-13", "2026-10-14", "2026-10-15"), reacao=4.0):
    """Tres pregoes de outubro (verao dos EUA: dado as 09:30), 09:00-12:59, preco parado e um pulo de `reacao` pontos as 09:30-09:31;
    depois o preco continua subindo (a venda da regra perde)."""
    partes = []
    for d in dias:
        idx = pd.date_range(f"{d} 09:00", f"{d} 12:59", freq="min")
        c = np.full(len(idx), 5000.0)
        i = idx.get_loc(pd.Timestamp(f"{d} 09:30"))
        c[i:] += reacao / 2
        c[i + 1:] += reacao / 2
        c[i + 2:] += np.arange(1, len(idx) - i - 1) * 0.5               # sobe 0,5 por minuto depois do sinal
        partes.append(pd.DataFrame({"o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "v": 10.0}, index=idx))
    return pd.concat(partes)


def test_base_dispara_uma_venda_por_dia_no_marco():
    m = _barras()
    s = dv.base(m)
    assert int((s != 0).sum()) == 3 and set(s[s != 0]) == {-1.0}
    assert all(pd.Timestamp(x).strftime("%H:%M") == "09:31" for x in m.index[s != 0])


def test_filtros_so_tiram_dias(monkeypatch):
    m = _barras()
    monkeypatch.setattr(ce, "tipos_por_dia", lambda *a, **k: {})
    monkeypatch.setattr(ce, "tipo_do_dia", lambda d, mapa=None, arq=None: "nenhum" if str(d) == "2026-10-14" else "cpi")
    s = dv.so_dia_de_dado(m)
    assert int((s != 0).sum()) == 2 and set(s[s != 0]) == {-1.0}
    # vol alta: tabela de regimes de mentira, com a vol dos ultimos 30 dias acima da mediana de 1 ano
    idx = pd.bdate_range(end="2026-10-15", periods=400)
    vol = pd.Series(np.r_[np.full(370, 10.0), np.full(30, 20.0)], index=idx)
    monkeypatch.setattr(regimes, "tabela", lambda *a, **k: pd.DataFrame({"usdbrl_vol20": vol}))
    s = dv.vol_alta(m)
    assert int((s != 0).sum()) == 3
    # ontem perdeu: a venda do dia 13 perde (o preco sobe), entao o dia 14 entra; o 13 (sem ontem) nao
    s = dv.ontem_perdeu(m)
    dias = sorted({pd.Timestamp(x).date().isoformat() for x in m.index[s != 0]})
    assert "2026-10-13" not in dias and "2026-10-14" in dias
    # contra a surpresa: reacao positiva; S > 0 concorda (fora), S < 0 contra (entra), sem S (fora)
    S = pd.DataFrame({"S": [1.0, -1.2, np.nan]}, index=pd.to_datetime(["2026-10-13", "2026-10-14", "2026-10-15"]))
    monkeypatch.setattr(ce, "tabela_surpresa_dia", lambda *a, **k: S)
    monkeypatch.setattr(ce, "surpresa_terminal_por_dia", lambda *a, **k: pd.DataFrame())
    s = dv.contra_surpresa(m)
    assert int((s != 0).sum()) == 1 and pd.Timestamp(m.index[s != 0][0]).date().isoformat() == "2026-10-14"
    # o livro do terminal cobre o dia 15 (sem MetaTrader): S < 0 contra a reacao positiva -> entra
    St = pd.DataFrame({"S": [-0.9]}, index=pd.to_datetime(["2026-10-15"]))
    monkeypatch.setattr(ce, "surpresa_terminal_por_dia", lambda *a, **k: St)
    s = dv.contra_surpresa(m)
    assert int((s != 0).sum()) == 2

"""
Testes de quant/dados/mercado.py e do vencimento de futuro de indice em calendario.py.

Sem rede e sem conftest: as unicas dependencias externas sao o pacote bizdays (calendario)
e o snapshot local do NEFIN, e todo teste que precisa do snapshot pula quando ele nao existe.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from quant.dados import calendario, mercado, nefin


def _quarta_mais_proxima_do_15(ano, mes):
    """Reimplementacao independente da regra: a quarta-feira que minimiza |dia - 15|."""
    dia15 = date(ano, mes, 15)
    quartas = [dia15 + timedelta(days=k) for k in range(-6, 7) if (dia15 + timedelta(days=k)).weekday() == 2]
    return min(quartas, key=lambda d: abs((d - dia15).days))


def _dias(valores, ini="2024-01-02"):
    """Series diaria em pregoes ficticios (dias uteis), para aritmetica exata."""
    idx = pd.bdate_range(ini, periods=len(valores))
    idx.name = "data"
    return pd.Series([float(v) for v in valores], index=idx, name="x")


# ─────────────────────────────────────────────────────────────
# calendario.vencimento_indice / proximo_vencimento_indice
# ─────────────────────────────────────────────────────────────
def test_vencimento_indice_e_a_quarta_mais_proxima_do_dia_15_em_mes_par():
    # casos conhecidos: 15/02/2024 e quinta -> 14; 15/04/2024 e segunda -> 17; 15/06/2024 e sabado -> 12
    assert calendario.vencimento_indice(2024, 2) == date(2024, 2, 14)
    assert calendario.vencimento_indice(2024, 4) == date(2024, 4, 17)
    assert calendario.vencimento_indice(2024, 6) == date(2024, 6, 12)
    assert calendario.vencimento_indice(2023, 2) == date(2023, 2, 15)     # o proprio dia 15 e quarta
    for ano in range(2005, 2031):
        for mes in calendario.MESES_VENCIMENTO_INDICE:
            v = calendario.vencimento_indice(ano, mes)
            quarta = _quarta_mais_proxima_do_15(ano, mes)
            assert v.year == ano and v.month == mes and 11 <= v.day <= 18
            assert calendario.eh_pregao(v)
            assert v == quarta if calendario.eh_pregao(quarta) else v < quarta
            assert v.weekday() == 2 or not calendario.eh_pregao(quarta)


def test_vencimento_indice_recua_quando_a_quarta_nao_e_pregao():
    # 15/10/2022 caiu num sabado -> quarta mais proxima e 12/10 (Nossa Senhora Aparecida)
    assert _quarta_mais_proxima_do_15(2022, 10) == date(2022, 10, 12)
    assert not calendario.eh_pregao(date(2022, 10, 12))
    assert calendario.vencimento_indice(2022, 10) == date(2022, 10, 11)
    assert calendario.vencimento_indice(2016, 10) == date(2016, 10, 11)


def test_vencimento_indice_rejeita_mes_impar():
    for mes in (1, 3, 5, 7, 9, 11):
        with pytest.raises(ValueError):
            calendario.vencimento_indice(2026, mes)
    with pytest.raises(ValueError):
        calendario.vencimento_indice(2026, 0)
    with pytest.raises(ValueError):
        calendario.vencimento_indice(2026, 13)


def test_proximo_vencimento_indice_e_estritamente_depois_e_vira_o_ano():
    assert calendario.proximo_vencimento_indice(date(2024, 1, 5)) == date(2024, 2, 14)
    assert calendario.proximo_vencimento_indice(date(2024, 2, 13)) == date(2024, 2, 14)
    # no dia do vencimento ja aponta para o proximo contrato (estritamente depois)
    assert calendario.proximo_vencimento_indice(date(2024, 2, 14)) == date(2024, 4, 17)
    # depois do vencimento de dezembro pula para fevereiro do ano seguinte
    assert calendario.proximo_vencimento_indice(date(2022, 12, 20)) == date(2023, 2, 15)
    assert calendario.proximo_vencimento_indice(calendario.vencimento_indice(2024, 12)) \
        == calendario.vencimento_indice(2025, 2)
    # aceita string e datetime, como o resto do calendario
    assert calendario.proximo_vencimento_indice("2024-01-05") == date(2024, 2, 14)


# ─────────────────────────────────────────────────────────────
# nivel do indice
# ─────────────────────────────────────────────────────────────
def test_nivel_indice_reproduz_a_ancora_e_compoe_nos_dois_sentidos():
    ex = _dias([0.001, -0.002, 0.003, 0.0, 0.004, -0.001, 0.002, 0.0005, -0.003, 0.001])
    taxa = _dias([0.0004] * 10)
    ancora = ex.index[4].date()
    nivel = mercado.nivel_indice(ex, taxa, nivel_ancora=100_000.0, data_ancora=ancora)

    assert len(nivel) == 10 and nivel.name == "nivel" and nivel.index.name == "data"
    assert abs(nivel.loc[pd.Timestamp(ancora)] - 100_000.0) < 1e-12       # ancora exata
    assert nivel.attrs["data_ancora_efetiva"] == str(ancora)
    assert abs(nivel.attrs["nivel_ancora"] - 100_000.0) < 1e-12

    # para frente: nivel_t / nivel_{t-1} == 1 + excesso_t + cdi_t
    total = ex + taxa
    razao = nivel / nivel.shift(1)
    for i in range(1, len(nivel)):
        assert abs(razao.iloc[i] - (1.0 + total.iloc[i])) < 1e-12

    # ida e volta: descontando do ultimo nivel todos os retornos volta-se ao primeiro
    v = float(nivel.iloc[-1])
    for r in total.iloc[1:][::-1]:
        v /= 1.0 + r
    assert abs(v / float(nivel.iloc[0]) - 1.0) < 1e-12

    # para tras a partir da ancora: nivel_{ancora-1} = ancora / (1 + total_ancora)
    esperado = 100_000.0 / (1.0 + float(total.iloc[4]))
    assert abs(nivel.iloc[3] / esperado - 1.0) < 1e-12


def test_nivel_indice_com_ancora_fora_da_serie_usa_o_ultimo_dia_anterior():
    ex = _dias([0.001] * 10, ini="2021-12-20")
    nivel = mercado.nivel_indice(ex, 0.0, nivel_ancora=125_000.0, data_ancora=date(2022, 1, 1))
    efetiva = pd.Timestamp(nivel.attrs["data_ancora_efetiva"])
    assert efetiva == ex.index[ex.index <= pd.Timestamp("2022-01-01")].max()
    assert abs(nivel.loc[efetiva] - 125_000.0) < 1e-12
    # ancora antes do inicio da serie: ancora no primeiro dia e avisa (nao levanta)
    nivel2 = mercado.nivel_indice(ex, 0.0, data_ancora=date(2000, 1, 1))
    assert abs(nivel2.iloc[0] - mercado.NIVEL_ANCORA) < 1e-12


def test_nivel_indice_usa_so_as_datas_com_excesso_e_cdi():
    ex = _dias([0.01] * 5)
    taxa = _dias([0.0] * 3)                       # so os 3 primeiros dias tem CDI
    nivel = mercado.nivel_indice(ex, taxa, nivel_ancora=100.0, data_ancora=ex.index[0].date())
    assert len(nivel) == 3
    assert abs(nivel.iloc[-1] - 100.0 * 1.01 ** 2) < 1e-12


# ─────────────────────────────────────────────────────────────
# nocional, hedge e beta
# ─────────────────────────────────────────────────────────────
def test_nocional_win_e_nivel_vezes_contratos_vezes_valor_do_ponto():
    assert abs(mercado.nocional_win(125_000.0) - 25_000.0) < 1e-12          # 1 WIN a 125k pontos
    assert abs(mercado.nocional_win(125_000.0, 3) - 75_000.0) < 1e-12
    assert abs(mercado.nocional_win(125_000.0, 1, mercado.VALOR_PONTO_IND) - 125_000.0) < 1e-12
    nivel = _dias([100_000.0, 110_000.0])
    noc = mercado.nocional_win(nivel, 2)
    assert noc.name == "nocional" and noc.index.name == "data"
    assert abs(noc.iloc[0] - 40_000.0) < 1e-12 and abs(noc.iloc[1] - 44_000.0) < 1e-12
    # contratos tambem pode variar no tempo
    variavel = mercado.nocional_win(nivel, _dias([1.0, 2.0]))
    assert abs(variavel.iloc[0] - 20_000.0) < 1e-12 and abs(variavel.iloc[1] - 44_000.0) < 1e-12


def test_retorno_hedge_e_o_negativo_do_excesso_escalado_pelo_nocional():
    ex = 0.02
    # nocional (125.000 x 0,20 = 25.000) sobre patrimonio de 100.000 = 25% do patrimonio
    r = mercado.retorno_hedge(ex, 1, 125_000.0, 100_000.0)
    assert abs(r - (-0.02 * 25_000.0 / 100_000.0)) < 1e-12
    assert abs(r - (-0.005)) < 1e-12
    # nocional igual ao patrimonio: o hedge devolve exatamente -excesso
    assert abs(mercado.retorno_hedge(ex, 1, 125_000.0, 25_000.0) - (-ex)) < 1e-12
    assert abs(mercado.retorno_hedge(-0.013, 4, 125_000.0, 100_000.0) - 0.013) < 1e-12
    # contratos negativos = ponta comprada
    assert abs(mercado.retorno_hedge(ex, -1, 125_000.0, 25_000.0) - ex) < 1e-12
    # patrimonio invalido nao estoura
    assert np.isnan(mercado.retorno_hedge(ex, 1, 125_000.0, 0.0))
    assert np.isnan(mercado.retorno_hedge(ex, 1, 125_000.0, float("nan")))


def test_retorno_hedge_com_series_alinhadas():
    ex = _dias([0.01, -0.02, 0.005])
    nivel = _dias([125_000.0, 125_000.0, 100_000.0])
    r = mercado.retorno_hedge(ex, 1, nivel, 25_000.0)
    assert r.name == "ret_hedge" and r.index.name == "data"
    assert abs(r.iloc[0] - (-0.01)) < 1e-12          # nocional == patrimonio
    assert abs(r.iloc[1] - 0.02) < 1e-12
    assert abs(r.iloc[2] - (-0.005 * 20_000.0 / 25_000.0)) < 1e-12
    # a intersecao das datas manda: patrimonio so em 2 dos 3 dias
    parcial = mercado.retorno_hedge(ex, 1, nivel, _dias([25_000.0, 25_000.0]))
    assert len(parcial) == 2


def test_contratos_para_beta_arredonda_para_o_contrato_inteiro():
    # beta 1,0 -> 0,3 em R$100 mil com o indice a 125.000: 0,7 x 100.000 / 25.000 = 2,8 -> 3
    assert mercado.contratos_para_beta(0.3, 1.0, 100_000.0, 125_000.0) == 3
    assert mercado.contratos_para_beta(1.0, 1.0, 100_000.0, 125_000.0) == 0
    assert mercado.contratos_para_beta(0.0, 1.0, 25_000.0, 125_000.0) == 1


def test_beta_movel_recupera_beta_plantado_e_e_nan_antes_do_minimo():
    rng = np.random.default_rng(20260907)
    n = 400
    idx = pd.bdate_range("2022-01-03", periods=n)
    ex = pd.Series(rng.normal(0.0, 0.012, n), index=idx, name="excesso")
    ruido = pd.Series(rng.normal(0.0, 0.0006, n), index=idx)
    carteira = 0.8 * ex + ruido

    beta = mercado.beta_movel(carteira, ex, janela=60, min_periodos=40)
    assert beta.name == "beta" and len(beta) == n
    assert beta.iloc[:39].isna().all() and not np.isnan(beta.iloc[39])
    assert abs(float(beta.dropna().mean()) - 0.8) < 0.01
    assert float((beta.dropna() - 0.8).abs().max()) < 0.05
    # sem ruido, o beta e exato
    exato = mercado.beta_movel(0.8 * ex, ex, janela=60, min_periodos=40).dropna()
    assert abs(float(exato.max()) - 0.8) < 1e-12 and abs(float(exato.min()) - 0.8) < 1e-12
    # excesso constante (variancia zero) nao vira infinito
    plano = mercado.beta_movel(carteira, pd.Series(0.001, index=idx), janela=60, min_periodos=40)
    assert plano.isna().all()


# ─────────────────────────────────────────────────────────────
# fontes do excesso
# ─────────────────────────────────────────────────────────────
def test_excesso_mercado_le_o_snapshot_nefin():
    if nefin.pin_ultimo("fatores") is None:
        pytest.skip("sem snapshot NEFIN local")
    ex = mercado.excesso_mercado()
    assert ex.attrs["fonte"] == "nefin" and ex.attrs["pin"]["sha256"]
    assert ex.name == "excesso_mercado" and ex.index.name == "data"
    assert str(ex.index.min().date()) == "2001-01-02" and len(ex) > 6000
    assert ex.abs().max() < 0.25                                  # limite de oscilacao do dia
    assert 0.0 < float(ex.std(ddof=1)) * np.sqrt(252) < 0.40       # vol do Ibovespa ~ 25% a.a.
    # o nivel composto com o CDI do proprio NEFIN bate a ancora e fica em ordem de grandeza de indice
    fatores = nefin.carregar_fatores()
    nivel = mercado.nivel_indice(ex, fatores["Risk_Free"])
    assert abs(nivel.loc[pd.Timestamp(mercado.DATA_ANCORA)] - mercado.NIVEL_ANCORA) < 1e-12
    # ordem de grandeza de indice em toda a amostra - a trajetoria NAO e a do Ibovespa real
    # (carteira de mercado do NEFIN != carteira teorica do Ibovespa; ver o topo de mercado.py)
    assert 1_000.0 < float(nivel.min()) and float(nivel.max()) < 1_000_000.0
    assert float(nivel.loc["2026-07-03"]) > float(nivel.loc["2002-10-16"])
    # a procedencia sobrevive ao recorte: o backtest precisa citar o pin que usou
    recorte = mercado._recorte(ex, "2024-01-01", "2024-12-31")
    assert recorte.attrs["pin"]["sha256"] == ex.attrs["pin"]["sha256"] and 200 < len(recorte) < 260


def test_excesso_mercado_aceita_fatores_ja_carregados():
    df = pd.DataFrame({"Rm_minus_Rf": [0.01, -0.02], "Risk_Free": [0.0004, 0.0004]},
                      index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    ex = mercado.excesso_mercado(fatores=df)
    assert list(ex.values) == [0.01, -0.02] and ex.attrs["fonte"] == "nefin"
    # DataFrame sem a coluna do fator de mercado: serie vazia com o schema, sem levantar
    ruim = mercado.excesso_mercado(fatores=pd.DataFrame({"SMB": [0.01]}, index=pd.to_datetime(["2024-01-02"])))
    assert len(ruim) == 0 and ruim.attrs["fonte"] == "indisponivel"


def test_excesso_mercado_sem_snapshot_devolve_vazio_sem_levantar(monkeypatch):
    def sem_snapshot(*a, **k):
        raise FileNotFoundError("nenhum snapshot do NEFIN baixado")

    monkeypatch.setattr(mercado.nefin, "carregar_fatores", sem_snapshot)
    ex = mercado.excesso_mercado()
    assert len(ex) == 0 and ex.attrs["fonte"] == "indisponivel" and ex.name == "excesso_mercado"


def test_excesso_mercado_pela_fonte_ibov_desconta_o_cdi():
    idx = pd.bdate_range("2024-01-02", periods=4)
    niveis = pd.Series([100.0, 101.0, 101.0, 102.0], index=idx)
    taxa = pd.Series(0.0004, index=idx)
    ex = mercado.excesso_mercado(ibov=niveis, taxa_cdi=taxa)
    assert ex.attrs["fonte"] == "ibov_menos_cdi" and len(ex) == 3
    assert abs(ex.iloc[0] - ((101.0 / 100.0 - 1.0) - 0.0004)) < 1e-12
    assert abs(ex.iloc[1] - (-0.0004)) < 1e-12
    # tambem aceita o DataFrame (data, fec) que baixar_ibov_yahoo devolve
    df = pd.DataFrame({"data": idx, "fec": [100.0, 101.0, 101.0, 102.0]})
    assert mercado.excesso_mercado(ibov=df, taxa_cdi=taxa).equals(ex)
    # sem CDI nenhum: vazio, sem levantar
    vazio = mercado.excesso_mercado(ibov=niveis, taxa_cdi=pd.Series(dtype=float))
    assert len(vazio) == 0


def test_retornos_ibov_e_retorno_total_por_ser_indice_de_retorno_total():
    niveis = _dias([100.0, 110.0, 99.0])
    r = mercado.retornos_ibov(niveis)
    assert len(r) == 2 and r.name == "ret_ibov"
    assert abs(r.iloc[0] - 0.10) < 1e-12 and abs(r.iloc[1] - (99.0 / 110.0 - 1.0)) < 1e-12


# ─────────────────────────────────────────────────────────────
# Yahoo (rede) e comparacao de fontes
# ─────────────────────────────────────────────────────────────
def _chart_yahoo(datas, fechamentos):
    ts = [int(pd.Timestamp(f"{d} 13:00:00", tz="UTC").timestamp()) for d in datas]
    return {"chart": {"result": [{"meta": {"symbol": "^BVSP", "currency": "BRL"},
                                  "timestamp": ts,
                                  "indicators": {"quote": [{"close": fechamentos}]}}],
                      "error": None}}


def test_parse_chart_yahoo_le_o_formato_documentado():
    bruto = _chart_yahoo(["2021-12-29", "2021-12-30", "2022-01-03"], [104_000.0, None, 105_000.5])
    df = mercado.parse_chart_yahoo(bruto)
    assert list(df.columns) == ["data", "fec"] and len(df) == 2      # o close nulo cai fora
    assert str(df["data"].iloc[0].date()) == "2021-12-29"
    assert abs(df["fec"].iloc[1] - 105_000.5) < 1e-12
    import json
    assert mercado.parse_chart_yahoo(json.dumps(bruto)).equals(df)   # aceita a string JSON crua
    # lixo nunca levanta: devolve o schema vazio
    for ruim in (None, "nao e json", {}, {"chart": {"result": []}},
                 {"chart": {"result": [{"timestamp": [1, 2], "indicators": {"quote": [{"close": [1.0]}]}}]}}):
        vazio = mercado.parse_chart_yahoo(ruim)
        assert len(vazio) == 0 and list(vazio.columns) == ["data", "fec"]


def test_baixar_ibov_yahoo_devolve_none_sem_rede(monkeypatch):
    chamadas = []
    monkeypatch.setattr(mercado, "http_get", lambda url, **k: chamadas.append(url) or None)
    assert mercado.baixar_ibov_yahoo("2024-01-01", "2024-01-31") is None
    assert len(chamadas) == len(mercado.HOSTS_YAHOO)                 # tentou os dois hosts
    assert all("%5EBVSP" in u and "period1=" in u and "period2=" in u for u in chamadas)


def test_baixar_ibov_yahoo_com_rede_simulada(monkeypatch):
    class Resp:
        def json(self):
            return _chart_yahoo(["2024-01-02", "2024-01-03"], [132_000.0, 131_000.0])

    monkeypatch.setattr(mercado, "http_get", lambda url, **k: Resp())
    df = mercado.baixar_ibov_yahoo("2024-01-01", "2024-01-31")
    assert len(df) == 2 and str(df["data"].iloc[0].date()) == "2024-01-02"
    # resposta que nao e JSON tambem devolve None em vez de levantar
    class Ruim:
        def json(self):
            raise ValueError("html de captcha")

    monkeypatch.setattr(mercado, "http_get", lambda url, **k: Ruim())
    assert mercado.baixar_ibov_yahoo("2024-01-01", "2024-01-31") is None


def test_comparar_fontes_com_series_equivalentes():
    idx = pd.bdate_range("2024-01-02", periods=30)
    rng = np.random.default_rng(7)
    ret = pd.Series(rng.normal(0.0005, 0.01, 30), index=idx)
    taxa = pd.Series(0.0004, index=idx)
    niveis = 100_000.0 * (1.0 + ret).cumprod()
    ex_nefin = (ret - taxa).iloc[1:]                    # mesma informacao, via nivel do indice
    comp = mercado.comparar_fontes(ex_nefin, niveis, taxa)
    assert comp["dias"] == 29
    assert abs(comp["correlacao"] - 1.0) < 1e-12
    assert abs(comp["dif_media_aa"]) < 1e-12
    assert comp["ini"] == str(idx[1].date()) and comp["fim"] == str(idx[-1].date())
    vazio = mercado.comparar_fontes(pd.Series(dtype=float), pd.Series(dtype=float), 0.0)
    assert vazio["dias"] == 0 and np.isnan(vazio["correlacao"])


# ─────────────────────────────────────────────────────────────
# schema e CLI
# ─────────────────────────────────────────────────────────────
def test_entradas_vazias_mantem_o_schema():
    vazia = pd.Series(dtype=float)
    for s in (mercado.nivel_indice(vazia, 0.0), mercado.beta_movel(vazia, vazia),
              mercado.retornos_ibov(vazia), mercado.nocional_win(vazia),
              mercado.retorno_hedge(vazia, 1, 125_000.0, 100_000.0)):
        assert isinstance(s, pd.Series) and len(s) == 0
        assert s.dtype == float and isinstance(s.index, pd.DatetimeIndex) and s.index.name == "data"
    assert len(mercado.excesso_mercado(fatores=pd.DataFrame({"Rm_minus_Rf": pd.Series(dtype=float)}))) == 0
    assert len(mercado.nivel_indice(vazia, pd.Series(dtype=float))) == 0


def test_main_roda_sem_rede(monkeypatch, capsys):
    if nefin.pin_ultimo("fatores") is None:
        pytest.skip("sem snapshot NEFIN local")
    monkeypatch.setattr(mercado, "http_get", lambda url, **k: None)
    assert mercado.main(["--sem-rede", "--patrimonio", "100000", "--contratos", "1"]) == 0
    saida = capsys.readouterr().out
    assert "fonte=nefin" in saida and "WIN" in saida and "SUPOSICAO" in saida
    assert str(calendario.proximo_vencimento_indice(date.today())) in saida


def test_main_devolve_1_sem_serie_de_excesso(monkeypatch):
    monkeypatch.setattr(mercado, "excesso_mercado", lambda *a, **k: pd.Series(dtype=float))
    assert mercado.main([]) == 1

"""Mercado minimo e deterministico para checar a mecanica do motor.

Nao se testa aqui se a estrategia ganha dinheiro: testa-se a identidade contabil, a
defasagem entre sinal e execucao, o hedge, os custos e o calculo das metricas. Se a
identidade contabil quebrar, todo numero produzido pelo backtest e ficcao.
"""
import numpy as np
import pandas as pd
import pytest

from quant import backtest as bt
from quant import carteira as ct
from quant import custos as cst
from quant.dados import calendario

TICKERS = [f"AC{i:02d}3" for i in range(1, 11)]
INI, FIM = "2021-06-01", "2023-06-30"


def _pregoes(ini=INI, fim=FIM):
    return pd.DatetimeIndex([pd.Timestamp(d) for d in calendario.pregoes(ini, fim)], name="data")


def _retornos(taxa=0.0, seed=3):
    """Retorno diario constante `taxa` mais ruido, igual para todos os papeis."""
    dias = _pregoes()
    rng = np.random.default_rng(seed)
    return pd.DataFrame({t: taxa + rng.normal(0, 0.001, len(dias)) for t in TICKERS}, index=dias)


def _cdi(taxa=0.0005):
    return pd.Series(taxa, index=_pregoes(), name="cdi")


def _sinais(datas=None, preco=20.0, vol=0.30, adtv=50e6):
    datas = datas or [pd.Timestamp(calendario.ultimo_pregao_do_mes(a, m))
                      for a in (2021, 2022, 2023) for m in range(1, 13)]
    datas = [d for d in datas if pd.Timestamp(INI) <= d <= pd.Timestamp(FIM)]
    linhas = []
    for d in datas:
        for i, t in enumerate(TICKERS, start=1):
            linhas.append({"data": d, "ticker": t, "rank": float(i), "elegivel": True,
                           "passa_momentum": True, "passa_qualidade": True,
                           "passa_crescimento": True, "excluido_valor": False,
                           "excluido_vol": False, "excluido_aluguel": False,
                           "score_momentum": 100.0 - i, "score_qualidade": 50.0, "score_valor": 50.0,
                           "vol252": vol, "setor": f"setor{i % 3}", "adtv21": adtv, "preco": preco})
    return pd.DataFrame(linhas)


@pytest.fixture(scope="module")
def base():
    return _sinais(), _retornos(), _cdi()


# ─────────────────────────────────────────────────────────────
# Utilitarios
# ─────────────────────────────────────────────────────────────
def test_datas_de_rebalance_sao_o_ultimo_pregao_de_cada_mes():
    d = bt.datas_rebalance("2023-01-01", "2023-03-31")
    assert len(d) == 3
    for x in d:
        assert calendario.eh_pregao(x.date())
        assert x.date() == calendario.ultimo_pregao_do_mes(x.year, x.month)
    assert bt.datas_rebalance("2023-03-31", "2023-01-01") == []


def test_drawdown_de_serie_conhecida():
    r = pd.Series([0.10, -0.20, 0.05])          # 1,10 -> 0,88 -> 0,924; pico 1,10
    assert abs(bt.drawdown(r) - (1 - 0.88 / 1.10)) < 1e-12
    assert bt.drawdown(pd.Series([0.01, 0.01])) == 0.0
    assert np.isnan(bt.drawdown(None))


# ─────────────────────────────────────────────────────────────
# Identidade contabil e defasagem
# ─────────────────────────────────────────────────────────────
def test_identidade_contabil_vale_todo_dia(base):
    sinais, ret, cdi = base
    r = bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0)
    ok, erro = bt.verificar_contabilidade(r["serie"])
    assert ok, f"identidade violada em ate R${erro:.4f}"
    assert len(r["serie"]) > 200


def test_execucao_e_no_pregao_seguinte_ao_sinal(base):
    sinais, ret, cdi = base
    r = bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0)
    primeira = pd.Timestamp(r["ordens"]["data"].min())
    primeiro_sinal = sinais["data"].min()
    assert primeira == pd.Timestamp(calendario.proximo_pregao(primeiro_sinal))


def test_retorno_do_dia_da_compra_nao_e_creditado():
    """Um salto de +50% no dia da execucao nao pode virar lucro: a posicao so passa a
    render no pregao seguinte."""
    sinais = _sinais()
    ret = _retornos(taxa=0.0, seed=1)
    d_sinal = sinais["data"].min()
    d_exec = pd.Timestamp(calendario.proximo_pregao(d_sinal))
    chocado = ret.copy()
    chocado.loc[d_exec, :] = 0.50
    a = bt.rodar(sinais, ret, _cdi(0.0), ini=INI, fim=FIM, capital=100_000.0)
    b = bt.rodar(sinais, chocado, _cdi(0.0), ini=INI, fim=FIM, capital=100_000.0)
    pa = a["serie"].set_index("data").loc[d_exec, "patrimonio"]
    pb = b["serie"].set_index("data").loc[d_exec, "patrimonio"]
    assert abs(pa - pb) < 1e-6
    # e o choque existe de fato: no dia seguinte as duas series ja diferem se o choque for la
    chocado2 = ret.copy()
    d2 = pd.Timestamp(calendario.proximo_pregao(d_exec))
    chocado2.loc[d2, :] = 0.50
    c = bt.rodar(sinais, chocado2, _cdi(0.0), ini=INI, fim=FIM, capital=100_000.0)
    pc = c["serie"].set_index("data").loc[d2, "patrimonio"]
    assert pc > pa * 1.2


def test_dia_sem_negocio_nao_muda_o_valor_da_posicao():
    sinais = _sinais()
    ret = _retornos(taxa=0.0, seed=5)
    com_buraco = ret.copy()
    meio = com_buraco.index[len(com_buraco) // 2]
    com_buraco.loc[meio, :] = np.nan
    r = bt.rodar(sinais, com_buraco, _cdi(0.0), ini=INI, fim=FIM, capital=100_000.0)
    s = r["serie"].set_index("data")
    if meio in s.index:
        anterior = s.index[s.index.get_loc(meio) - 1]
        assert abs(s.loc[meio, "valor_posicoes"] - s.loc[anterior, "valor_posicoes"]) < 1e-6
    ok, _ = bt.verificar_contabilidade(r["serie"])
    assert ok


def test_caixa_rende_cdi_sem_posicao_nenhuma():
    """Sem sinal elegivel a carteira fica 100% em caixa e tem de render exatamente o CDI."""
    sinais = _sinais().assign(elegivel=False, rank=np.nan)
    r = bt.rodar(sinais, _retornos(taxa=0.10), _cdi(0.0005), ini=INI, fim=FIM,
                 capital=100_000.0, com_hedge=False)
    s = r["serie"].set_index("data")
    assert (s["n_posicoes"] == 0).all()
    dias = len(s) - 1
    esperado = 100_000.0 * (1.0005 ** dias)
    assert abs(s["patrimonio"].iloc[-1] / esperado - 1.0) < 0.02


# ─────────────────────────────────────────────────────────────
# Hedge e custos
# ─────────────────────────────────────────────────────────────
def test_hedge_ganha_quando_o_mercado_cai(base):
    sinais, ret, cdi = base
    dias = _pregoes()
    excesso = pd.Series(-0.002, index=dias)          # mercado abaixo do CDI todo dia
    nivel = pd.Series(120_000.0, index=dias)
    com = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0)
    sem = bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0, com_hedge=False)
    assert com["serie"]["patrimonio"].iloc[-1] > sem["serie"]["patrimonio"].iloc[-1]
    assert (com["serie"]["contratos"] > 0).any()
    ok, _ = bt.verificar_contabilidade(com["serie"])
    assert ok


def test_hedge_perde_quando_o_mercado_sobe(base):
    sinais, ret, cdi = base
    dias = _pregoes()
    excesso = pd.Series(0.002, index=dias)
    nivel = pd.Series(120_000.0, index=dias)
    com = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0)
    sem = bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0, com_hedge=False)
    assert com["serie"]["patrimonio"].iloc[-1] < sem["serie"]["patrimonio"].iloc[-1]


def test_custo_dobrado_reduz_o_resultado(base):
    sinais, ret, cdi = base
    normal = bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0, estresse=1.0)
    caro = bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0, estresse=2.0)
    assert caro["serie"]["custo_dia"].sum() >= normal["serie"]["custo_dia"].sum()
    assert caro["serie"]["patrimonio"].iloc[-1] <= normal["serie"]["patrimonio"].iloc[-1]


def test_custo_cobrado_bate_com_o_custo_das_ordens(base):
    """Sem hedge o custo debitado tem de ser exatamente o das boletas; com hedge, a
    diferenca e exatamente a tarifa e o tick dos contratos de indice."""
    sinais, ret, cdi = base
    sem = bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0, com_hedge=False)
    assert abs(sem["serie"]["custo_dia"].sum() - sem["ordens"]["custo"].sum()) < 1e-6
    com = bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0)
    extra = com["serie"]["custo_dia"].sum() - com["ordens"]["custo"].sum()
    unidade = cst.custo_win(1)["total"]
    assert extra > 0 and abs(extra / unidade - round(extra / unidade)) < 1e-9


# ─────────────────────────────────────────────────────────────
# Metricas, atribuicao, concentracao e veredito
# ─────────────────────────────────────────────────────────────
def test_metricas_de_serie_construida_a_mao():
    dias = _pregoes("2022-01-03", "2022-12-30")
    serie = pd.DataFrame({"data": dias, "patrimonio": 100_000.0 * (1.0004 ** np.arange(len(dias))),
                          "caixa": 0.0, "valor_posicoes": 0.0, "retorno": 0.0004,
                          "retorno_hedge": 0.0, "cdi": 0.0002, "n_posicoes": 10,
                          "contratos": 0, "custo_dia": 0.0, "giro_dia": 0.0})
    m = bt.metricas({"serie": serie})
    assert abs(m["retorno_aa"] - (1.0004 ** 252 - 1)) < 0.01
    assert abs(m["cdi_aa"] - (1.0002 ** 252 - 1)) < 0.01
    assert m["excesso_aa"] > 0 and m["mdd"] == 0.0
    assert bt.metricas({"serie": pd.DataFrame()})["n_dias"] == 0


def test_atribuicao_recupera_beta_e_alfa_plantados():
    dias = _pregoes("2019-01-02", "2023-12-29")
    rng = np.random.default_rng(11)
    mercado_ = pd.Series(rng.normal(0.0003, 0.012, len(dias)), index=dias)
    alfa_dia = 0.0004
    carteira_ = 0.6 * mercado_ + alfa_dia + rng.normal(0, 0.002, len(dias))
    serie = pd.DataFrame({"data": dias, "patrimonio": 100_000.0, "caixa": 0.0,
                          "valor_posicoes": 0.0, "retorno": carteira_.values,
                          "retorno_hedge": 0.0, "cdi": 0.0, "n_posicoes": 10,
                          "contratos": 0, "custo_dia": 0.0, "giro_dia": 0.0})
    outros = {c: rng.normal(0, 0.004, len(dias)) for c in ("SMB", "HML", "WML", "IML")}
    fatores = pd.DataFrame({"Rm_minus_Rf": mercado_, **outros}, index=dias)
    a = bt.atribuicao_nefin({"serie": serie}, fatores)
    assert abs(a["betas"]["Rm_minus_Rf"] - 0.6) < 0.1
    assert a["alfa_mensal"] > 0 and a["t_alfa"] > 2.0
    assert bt.atribuicao_nefin({"serie": serie}, None)["n_meses"] == 0


def test_concentracao_e_definida_com_pnl_total_negativo():
    r = {"pnl_nome": pd.Series({"A3": 100.0, "B3": 50.0, "C3": -500.0}), "serie": None}
    c = bt.concentracao(r)
    assert abs(c["maior_nome"] - 100.0 / 150.0) < 1e-12 and c["ticker"] == "A3"
    assert c["n_nomes"] == 3
    assert np.isnan(bt.concentracao({"pnl_nome": pd.Series(dtype=float)})["maior_nome"])


def test_avaliar_reprova_cada_criterio_isoladamente():
    bom = {"excesso_aa": 0.02, "sharpe_excesso": 0.4, "giro_mensal": 0.10, "mdd": 0.20}
    v = bt.avaliar(bom, {"t_alfa": 2.0}, {"maior_nome": 0.10, "maior_ano": 0.4}, 0.6, 4)
    assert v["passou"] and not v["reprovados"]
    for chave, valor, esperado in (("excesso_aa", -0.01, "excesso_positivo"),
                                   ("sharpe_excesso", 0.05, "sharpe_na_faixa"),
                                   ("giro_mensal", 0.40, "giro_ok"),
                                   ("mdd", 0.50, "mdd_ok")):
        ruim = dict(bom, **{chave: valor})
        v2 = bt.avaliar(ruim, {"t_alfa": 2.0}, {"maior_nome": 0.10, "maior_ano": 0.4}, 0.6, 4)
        assert esperado in v2["reprovados"] and not v2["passou"]


def test_sharpe_alto_demais_vira_alerta_e_rejeicao():
    suspeito = bt.avaliar({"excesso_aa": 0.2, "sharpe_excesso": 1.2, "giro_mensal": 0.1, "mdd": 0.1})
    assert any("procurar bug" in a for a in suspeito["alertas"])
    rejeitado = bt.avaliar({"excesso_aa": 0.5, "sharpe_excesso": 1.8, "giro_mensal": 0.1, "mdd": 0.1})
    assert any("REJEITAR" in a for a in rejeitado["alertas"]) and not rejeitado["passou"]


def test_relatorio_carimba_dado_sintetico():
    res = {"metricas": bt.metricas({"serie": pd.DataFrame()}), "veredito": {}}
    texto = bt.relatorio(res, None, origem="sintetico", gate_passou=False)
    assert "dados sinteticos" in texto and "Nenhum numero abaixo e resultado" in texto
    assert "NAO RODOU / NAO PASSOU" in texto
    real = bt.relatorio(res, None, origem="real", gate_passou=True)
    assert "dados sinteticos" not in real and "passou" in real


def test_relatorio_grava_arquivo(tmp_path):
    caminho = str(tmp_path / "r.md")
    bt.relatorio({"metricas": {}, "veredito": {}}, caminho, origem="sintetico")
    assert open(caminho, encoding="utf-8").read().startswith("# Backtest")


# ─────────────────────────────────────────────────────────────
# Robustez
# ─────────────────────────────────────────────────────────────
def test_entrada_vazia_nao_quebra():
    vazio = bt.rodar(pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=float))
    assert len(vazio["serie"]) == 0 and len(vazio["ordens"]) == 0
    assert bt.metricas(vazio)["n_dias"] == 0
    assert bt.verificar_contabilidade(vazio["serie"])[0]


def test_periodo_sem_sinal_devolve_serie_vazia(base):
    sinais, ret, cdi = base
    r = bt.rodar(sinais, ret, cdi, ini="2030-01-01", fim="2030-12-31")
    assert len(r["serie"]) == 0


def test_n_efetivo_e_reportado_mes_a_mes(base):
    sinais, ret, cdi = base
    r = bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0)
    assert len(r["n_efetivo"]) > 0
    assert (r["n_efetivo"] == len(TICKERS)).all()      # so ha 10 papeis: abaixo da banda de 18
    assert r["n_efetivo"].min() < ct.BANDA[0]


def test_main_sem_banco_devolve_dois(monkeypatch):
    monkeypatch.setattr(bt, "carregar_do_banco", lambda *a, **k: None)
    assert bt.main(["--janela", "treino"]) == 2


def test_holdout_lacrado_recusa_sem_flag(monkeypatch):
    monkeypatch.setattr(bt, "carregar_do_banco", lambda *a, **k: {"sinais": None})
    assert bt.main(["--janela", "holdout"]) == 3

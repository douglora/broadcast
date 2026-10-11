"""Regime ligado ao backtest: desligado reproduz o de antes; ligado fecha a contabilidade."""
import numpy as np
import pandas as pd
import pytest

from quant import backtest as bt
from quant import carteira as ct
from quant import custos as cst
from quant import regime as rg
from quant.testes.test_backtest import FIM, INI, _cdi, _pregoes, _retornos, _sinais


@pytest.fixture(scope="module")
def mercado():
    sinais, ret, cdi = _sinais(), _retornos(), _cdi()
    dias = _pregoes()
    rng = np.random.default_rng(21)
    excesso = pd.Series(rng.normal(0.0002, 0.01, len(dias)), index=dias)
    nivel = pd.Series(120_000.0 * np.cumprod(1 + excesso.values + 0.0005), index=dias)
    return sinais, ret, cdi, excesso, nivel


def _plano(dias, razao=0.5, expo=0.70, estados=None, razoes=None, expos=None):
    """Plano manual com os mesmos nomes de coluna de `regime.plano_protecao`."""
    n = len(dias)
    return pd.DataFrame({
        "razao_decidida": np.full(n, razao) if razoes is None else razoes,
        "razao_exec": np.full(n, razao) if razoes is None else razoes,
        "exposicao_sinal": np.full(n, expo) if expos is None else expos,
        "stopado": np.zeros(n, dtype=bool), "referencia": np.nan,
        "estado": np.array([rg.NEUTRO] * n, dtype=object) if estados is None else estados}, index=dias)


# ─────────────────────────────────────────────────────────────
# Desligado: exatamente o resultado de antes (numeros gravados ANTES de editar o motor)
# ─────────────────────────────────────────────────────────────
GOLDEN = {
    "base": (104856.83641640388, 52640918.083023, 309.63746359531547, 1, 499, 22),
    "sem_hedge": (107966.41818267916, 51723378.427523, 210.3006413835481, 0, 499, 10),
    "estresse2": (104511.5152511911, 52495594.71399907, 582.4696048786952, 1, 499, 22),
}


@pytest.mark.parametrize("nome,kw", [("base", {}), ("sem_hedge", {"com_hedge": False}),
                                     ("estresse2", {"estresse": 2.0})])
def test_regime_desligado_reproduz_o_resultado_de_antes(mercado, nome, kw):
    sinais, ret, cdi, excesso, nivel = mercado
    r = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0, **kw)
    s = r["serie"]
    final, soma, custo, max_contr, n_dias, n_ordens = GOLDEN[nome]
    assert abs(float(s["patrimonio"].iloc[-1]) - final) < 1e-6
    assert abs(float(s["patrimonio"].sum()) - soma) < 1e-3
    assert abs(float(s["custo_dia"].sum()) - custo) < 1e-6
    assert int(s["contratos"].max()) == max_contr and len(s) == n_dias and len(r["ordens"]) == n_ordens
    assert "regime" not in r and "estado_regime" not in s.columns       # nada extra na saida


def test_regime_none_e_igual_a_nao_passar_regime(mercado):
    sinais, ret, cdi, excesso, nivel = mercado
    a = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0)
    b = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0, regime=None)
    pd.testing.assert_frame_equal(a["serie"], b["serie"])


def test_limiar_de_peso_padrao_da_carteira_nao_mudou():
    import inspect
    assert inspect.signature(ct.carteira_alvo).parameters["limiar_peso"].default == ct.LIMIAR_PESO == 0.015


# ─────────────────────────────────────────────────────────────
# Ligado
# ─────────────────────────────────────────────────────────────
def test_contratos_para_razao_arredonda_e_respeita_a_margem():
    # nivel 100.000 -> 1 WIN = R$ 20.000 de nocional
    assert bt.contratos_para_razao(0.5, 80_000.0, 100_000.0, 50_000.0) == 2        # 40.000 / 20.000
    assert bt.contratos_para_razao(0.5, 70_000.0, 100_000.0, 50_000.0) == 2        # 1,75 arredonda para 2
    assert bt.contratos_para_razao(0.5, 30_000.0, 100_000.0, 50_000.0) == 1        # 0,75 -> 1
    assert bt.contratos_para_razao(0.5, 10_000.0, 100_000.0, 50_000.0) == 0        # 0,25 -> 0
    # margem de R$ 5.000 por contrato: caixa de R$ 12.000 so cobre 2
    assert bt.contratos_para_razao(2.0, 100_000.0, 100_000.0, 12_000.0) == 2
    assert bt.contratos_para_razao(0.0, 100_000.0, 100_000.0, 50_000.0) == 0
    assert bt.contratos_para_razao(0.5, 0.0, 100_000.0, 50_000.0) == 0
    assert bt.contratos_para_razao(0.5, 80_000.0, float("nan"), 50_000.0) == 0


def test_identidade_contabil_vale_com_regime_ligado(mercado):
    sinais, ret, cdi, excesso, nivel = mercado
    dias = _pregoes()
    razoes = np.where(np.arange(len(dias)) % 120 < 60, 0.5, 1.0)
    expos = np.where(np.arange(len(dias)) % 120 < 60, 0.70, 0.55)
    r = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0,
                 regime=_plano(dias, razoes=razoes, expos=expos))
    ok, erro = bt.verificar_contabilidade(r["serie"])
    assert ok, f"identidade violada em ate R${erro:.4f}"
    assert r["regime"] and (r["serie"]["contratos"] > 0).any()
    assert {"estado_regime", "razao_hedge", "stopado"} <= set(r["serie"].columns)


def test_razao_zero_nao_abre_contrato_algum(mercado):
    sinais, ret, cdi, excesso, nivel = mercado
    r = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0,
                 regime=_plano(_pregoes(), razao=0.0))
    assert (r["serie"]["contratos"] == 0).all() and r["custo_win"] == 0.0
    sem = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0, com_hedge=False)
    pd.testing.assert_series_equal(r["serie"]["patrimonio"], sem["serie"]["patrimonio"])


def test_mercado_em_queda_a_protecao_por_regime_ganha(mercado):
    sinais, ret, cdi, _, _ = mercado
    dias = _pregoes()
    excesso = pd.Series(-0.002, index=dias)
    nivel = pd.Series(120_000.0, index=dias)
    com = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0,
                   regime=_plano(dias, razao=0.5))
    sem = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0, com_hedge=False)
    assert com["serie"]["patrimonio"].iloc[-1] > sem["serie"]["patrimonio"].iloc[-1]
    assert com["serie"]["retorno_hedge"].sum() > 0


def test_mercado_em_alta_a_protecao_por_regime_perde(mercado):
    sinais, ret, cdi, _, _ = mercado
    dias = _pregoes()
    excesso = pd.Series(0.002, index=dias)
    nivel = pd.Series(120_000.0, index=dias)
    com = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0,
                   regime=_plano(dias, razao=0.5))
    sem = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0, com_hedge=False)
    assert com["serie"]["patrimonio"].iloc[-1] < sem["serie"]["patrimonio"].iloc[-1]


def test_a_exposicao_do_regime_chega_nas_acoes_e_o_corte_e_executado(mercado):
    """De 70% para 40% em acoes: o ajuste de ~1 p.p. por nome passa pelo limiar reduzido."""
    sinais, ret, cdi, excesso, nivel = mercado
    dias = _pregoes()
    corte = pd.Timestamp("2022-06-30")
    expos = np.where(dias < corte, 0.70, 0.40)
    r = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0,
                 com_hedge=False, regime=_plano(dias, razao=0.0, expos=expos))
    s = r["serie"].set_index("data")
    antes = (s.loc[:"2022-05-31", "valor_posicoes"] / s.loc[:"2022-05-31", "patrimonio"]).iloc[-1]
    depois = (s.loc["2022-09-01":, "valor_posicoes"] / s.loc["2022-09-01":, "patrimonio"]).iloc[0]
    assert 0.55 < antes < 0.80
    assert depois < 0.50, f"o corte de exposicao nao foi executado: {depois:.2%} em acoes"
    ok, _ = bt.verificar_contabilidade(r["serie"])
    assert ok


def test_sem_a_baixa_do_limiar_o_corte_nao_sairia():
    """Documenta por que LIMIAR_PESO_REGIME existe: 70% -> 55% com 10 nomes mexe 1,5 p.p. por nome
    em carteira de 10, mas com 22 nomes mexeria 0,7 p.p. e o limiar de 1,5 p.p. barraria tudo."""
    assert ct.LIMIAR_PESO == 0.015 and bt.LIMIAR_PESO_REGIME < ct.LIMIAR_PESO
    n, corte = 22, 0.70 - 0.55
    assert corte / n < ct.LIMIAR_PESO              # por nome, o corte e menor que o limiar padrao


def test_custo_do_win_com_regime_e_multiplo_exato_da_unidade(mercado):
    sinais, ret, cdi, excesso, nivel = mercado
    dias = _pregoes()
    razoes = np.where(np.arange(len(dias)) % 100 < 50, 0.5, 1.0)
    r = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0,
                 regime=_plano(dias, razoes=razoes))
    extra = r["serie"]["custo_dia"].sum() - r["ordens"]["custo"].sum()
    assert extra > 0 and abs(extra - r["custo_win"]) < 1e-9
    unidade = cst.custo_win(1)["total"]
    assert abs(extra / unidade - round(extra / unidade)) < 1e-9


def test_a_razao_em_vigor_vale_no_proprio_dia_porque_a_defasagem_esta_no_plano(mercado):
    """`_hedge_por_regime` usa razao_exec[d] sem deslocar de novo: a defasagem mora no plano."""
    sinais, ret, cdi, excesso, nivel = mercado
    dias = _pregoes()
    liga = np.where(dias >= pd.Timestamp("2022-03-01"), 0.5, 0.0)
    r = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0,
                 regime=_plano(dias, razoes=liga))
    s = r["serie"].set_index("data")
    primeiro = s.index[s["contratos"] > 0][0]
    assert primeiro >= pd.Timestamp("2022-03-01")


def test_plano_do_futuro_nao_muda_o_passado_do_backtest(mercado):
    """Mudar o plano DEPOIS de uma data nao muda a serie ate aquela data."""
    sinais, ret, cdi, excesso, nivel = mercado
    dias = _pregoes()
    a = _plano(dias, razao=0.5)
    b = _plano(dias, razoes=np.where(dias < pd.Timestamp("2023-01-02"), 0.5, 1.2))
    ra = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0, regime=a)
    rb = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0, regime=b)
    sa, sb = ra["serie"].set_index("data"), rb["serie"].set_index("data")
    antes = sa.index < pd.Timestamp("2023-01-02")
    pd.testing.assert_frame_equal(sa[antes][["patrimonio", "caixa", "contratos"]],
                                  sb[antes][["patrimonio", "caixa", "contratos"]])
    assert sa["patrimonio"].iloc[-1] != sb["patrimonio"].iloc[-1]


def test_roll_cobra_fechar_e_abrir(mercado):
    sinais, ret, cdi, excesso, nivel = mercado
    dias = _pregoes()
    r = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0,
                 regime=_plano(dias, razao=0.5))
    com_custo = (r["serie"]["custo_dia"] - 0).gt(0).sum()
    assert r["custo_win"] > cst.custo_win(1)["total"]            # abriu e rolou varias vezes
    assert com_custo > 0


def test_variantes_pre_registradas_tem_no_maximo_3_parametros_livres():
    for nome, v in rg.VARIANTES.items():
        livres = [k for k in ("razao_baixa", "stop_atr", "exposicao_baixa") if v[k] is not None]
        assert len(livres) <= 3, nome
    assert [k for k in rg.VARIANTES if k.startswith("R")] == ["R1", "R2", "R3", "R4", "R5"]


def test_plano_da_variante_s2_e_constante_e_sem_detector():
    dias = _pregoes()
    ex = pd.Series(np.random.default_rng(1).normal(0, 0.01, len(dias)), index=dias)
    p = rg.plano_da_variante("S2", ex, pd.Series(0.0005, index=dias))
    assert set(p["razao_exec"].iloc[5:]) == {0.5} and set(p["exposicao_sinal"]) == {0.70}
    assert (p["estado"] == rg.NEUTRO).all()


def test_main_aceita_regime_e_sinais_alternativos(monkeypatch, tmp_path):
    chamadas = {}

    def falso_carregar(ini, fim, arq_sinais=None):
        chamadas.update(ini=ini, fim=fim, arq_sinais=arq_sinais)
        return None
    monkeypatch.setattr(bt, "carregar_do_banco", falso_carregar)
    assert bt.main(["--janela", "treino", "--regime", "R3", "--sinais", "x.parquet"]) == 2
    assert chamadas["fim"] == bt.TREINO[1] and chamadas["arq_sinais"] == "x.parquet"


def test_holdout_lacrado_nem_carrega_dados(monkeypatch):
    def nao_deve_chamar(*a, **k):
        raise AssertionError("o holdout lacrado nao pode carregar o banco")
    monkeypatch.setattr(bt, "carregar_do_banco", nao_deve_chamar)
    assert bt.main(["--janela", "holdout"]) == 3
    assert bt.main(["--janela", "holdout", "--regime", "S2"]) == 3


def test_carregar_do_banco_corta_tudo_em_fim():
    """A rodada de treino nao pode carregar uma linha do holdout (usa o banco real, se existir)."""
    import os
    from quant.comum import DIR_BANCO
    if not os.path.exists(os.path.join(DIR_BANCO, "cotacoes_diarias", "ano=2015")):
        pytest.skip("sem banco local de cotacoes")
    corte = pd.Timestamp("2014-12-31")
    d = bt.carregar_do_banco("2012-01-01", "2014-12-31")
    if d is None:
        pytest.skip("banco incompleto")
    assert d["retornos"].index.max() <= corte
    for k in ("cdi", "excesso", "nivel", "fatores"):
        if d[k] is not None and len(d[k]):
            assert d[k].index.max() <= corte, k
    sinais = d["sinais"]
    assert len(sinais) == 0 or pd.to_datetime(sinais["data"]).max() <= corte
    assert len(d["retornos"]) > 0


def _mercado_com_muitos_nomes(n=24):
    """24 papeis a R$ 2 (lote de R$ 200, fino): o corte de 70% para 55% mexe ~0,7 p.p. por nome,
    abaixo do limiar padrao de 1,5 p.p. Com lote grosso o arredondamento sozinho passaria do limiar."""
    from quant.dados import calendario
    tickers = [f"BX{i:02d}3" for i in range(1, n + 1)]
    dias = _pregoes()
    rng = np.random.default_rng(3)
    ret = pd.DataFrame({t: rng.normal(0, 0.001, len(dias)) for t in tickers}, index=dias)
    datas = [pd.Timestamp(calendario.ultimo_pregao_do_mes(a, m)) for a in (2021, 2022, 2023) for m in range(1, 13)]
    datas = [d for d in datas if pd.Timestamp(INI) <= d <= pd.Timestamp(FIM)]
    linhas = []
    for d in datas:
        for i, t in enumerate(tickers, start=1):
            linhas.append({"data": d, "ticker": t, "rank": float(i), "elegivel": True,
                           "passa_momentum": True, "passa_qualidade": True, "passa_crescimento": True,
                           "excluido_valor": False, "excluido_vol": False, "excluido_aluguel": False,
                           "score_momentum": 100.0 - i, "score_qualidade": 50.0, "score_valor": 50.0,
                           "vol252": 0.30, "setor": f"setor{i % 8}", "adtv21": 50e6, "preco": 2.0})
    return pd.DataFrame(linhas), ret


def _fracao_em_acoes(monkeypatch, limiar):
    monkeypatch.setattr(bt, "LIMIAR_PESO_REGIME", limiar)
    sinais, ret = _mercado_com_muitos_nomes()
    dias = _pregoes()
    expos = np.where(dias < pd.Timestamp("2022-06-30"), 0.70, 0.55)
    r = bt.rodar(sinais, ret, _cdi(0.0), ini=INI, fim=FIM, capital=100_000.0, com_hedge=False,
                 regime=_plano(dias, razao=0.0, expos=expos), config={})
    s = r["serie"].set_index("data")
    return float((s["valor_posicoes"] / s["patrimonio"]).iloc[-1])


def test_corte_de_70_para_55_com_24_nomes_so_sai_com_o_limiar_reduzido(monkeypatch):
    com = _fracao_em_acoes(monkeypatch, 0.002)
    sem = _fracao_em_acoes(monkeypatch, 0.015)
    assert com < 0.60, f"com o limiar reduzido o corte devia ter sido executado: {com:.2%}"
    assert sem > 0.65, f"com o limiar padrao o corte nao sairia (era o defeito): {sem:.2%}"


def test_gate_aprovado_le_o_arquivo_do_gate(tmp_path):
    import json
    ok = tmp_path / "g.json"
    ok.write_text(json.dumps({"passou": True}))
    ruim = tmp_path / "r.json"
    ruim.write_text(json.dumps({"passou": False}))
    assert bt.gate_aprovado(str(ok)) is True
    assert bt.gate_aprovado(str(ruim)) is False
    assert bt.gate_aprovado(str(tmp_path / "nao_existe.json")) is None
    (tmp_path / "x.json").write_text("[]")
    assert bt.gate_aprovado(str(tmp_path / "x.json")) is None


def test_rodar_holdout_com_regime_roda_de_ponta_a_ponta_sem_tocar_nos_arquivos_reais(monkeypatch, mercado):
    """Pre-voo do holdout: o caminho que o Douglas vai abrir UMA vez roda inteiro com regime, num mercado
    sintetico, com o livro e a trava substituidos por registradores falsos (nada e gravado)."""
    from quant import livro
    sinais, ret, cdi, excesso, nivel = mercado
    # `ranquear` (usado nas comparacoes pre-registradas) le os percentis e o bonus do painel real
    sinais = sinais.assign(pct_momentum=sinais["score_momentum"], pct_qualidade=50.0, pct_valor=50.0,
                           bonus_insider=0.0)
    gravado = {"abrir": [], "registrar": [], "resultado": []}
    monkeypatch.setattr(livro, "HOLDOUT", ("2021-09-01", "2023-06-30"))
    monkeypatch.setattr(livro, "abrir_holdout", lambda cfg, motivo: gravado["abrir"].append(cfg) or {})
    monkeypatch.setattr(livro, "registrar", lambda *a, **k: gravado["registrar"].append((a, k)) or {})
    monkeypatch.setattr(livro, "registrar_holdout", lambda res: gravado["resultado"].append(res) or {})
    monkeypatch.setattr(livro, "n_tentativas", lambda *a, **k: 16)
    monkeypatch.setattr(livro, "variancia_sharpes", lambda *a, **k: 0.009)
    plano = rg.plano_da_variante("S2", excesso, cdi)
    cfg = {"versao": "intersecao-pf-1", "regime": "S2"}
    res = bt.rodar_holdout(sinais, ret, cdi, excesso, nivel, fatores=None, capital=100_000.0,
                           config=cfg, regime=plano)
    assert gravado["abrir"] == [cfg] and len(gravado["resultado"]) == 1 and len(gravado["registrar"]) == 1
    assert res["metricas"]["n_dias"] > 100 and "veredito" in res and "comparacoes" in res
    assert res["metricas_2x"]["custo_aa"] >= res["metricas"]["custo_aa"]
    sem = bt.rodar_holdout(sinais, ret, cdi, excesso, nivel, fatores=None, capital=100_000.0, config=cfg)
    assert sem["metricas"]["n_dias"] == res["metricas"]["n_dias"]
    assert sem["metricas"]["retorno_aa"] != res["metricas"]["retorno_aa"]       # o regime mudou algo


# ─────────────────────────────────────────────────────────────
# Holdout com a principal e as comparacoes declaradas numa abertura so
# ─────────────────────────────────────────────────────────────
def _livro_falso(monkeypatch, gravado):
    from quant import livro
    monkeypatch.setattr(livro, "HOLDOUT", ("2021-09-01", "2023-06-30"))
    monkeypatch.setattr(livro, "abrir_holdout", lambda cfg, motivo: gravado["abrir"].append(cfg) or {})
    monkeypatch.setattr(livro, "registrar", lambda *a, **k: gravado["registrar"].append((a, k)) or {})
    monkeypatch.setattr(livro, "registrar_holdout", lambda res: gravado["resultado"].append(res) or {})
    monkeypatch.setattr(livro, "n_tentativas", lambda *a, **k: 22)
    monkeypatch.setattr(livro, "variancia_sharpes", lambda *a, **k: 0.009)


def test_holdout_multiplo_roda_tudo_numa_abertura_e_grava_tudo_junto(monkeypatch, mercado):
    import json
    sinais, ret, cdi, excesso, nivel = mercado
    sinais = sinais.assign(pct_momentum=sinais["score_momentum"], pct_qualidade=50.0, pct_valor=50.0,
                           bonus_insider=0.0)
    gravado = {"abrir": [], "registrar": [], "resultado": []}
    _livro_falso(monkeypatch, gravado)
    cfg = bt.config_holdout("S2", bt.COMPARACOES_DECLARADAS, 100_000.0, "sinais_2011_2026.parquet")
    res = bt.rodar_holdout_multiplo(sinais, ret, cdi, excesso, nivel, fatores=None, capital=100_000.0, config=cfg,
                                    principal="S2", comparar=bt.COMPARACOES_DECLARADAS)
    # uma abertura, um resultado, uma linha no livro: o lacre vale
    assert len(gravado["abrir"]) == 1 and gravado["abrir"][0] == cfg
    assert len(gravado["resultado"]) == 1 and len(gravado["registrar"]) == 1
    assert list(res["configs"]) == ["S2", "S0", "S1", "R1", "R2", "R3", "R4", "R5"]
    assert res["principal"] == "S2" and res["comparacoes_declaradas"] == ["S0", "S1", "R1", "R2", "R3", "R4", "R5"]
    for nome, b in res["configs"].items():
        assert b["extras"]["contabilidade_ok"], nome
        assert b["metricas_2x"]["custo_aa"] >= b["metricas"]["custo_aa"] - 1e-12, nome
        assert set(b["subperiodos"]) == {"2011-2015", "2016-2019", "2020-2022", "2023-2026"}
        assert "pior_ano" in b["extras"] and "retorno_por_ano" in b["extras"] and "perna_indice_rs" in b["extras"]
        assert "passou" in b["veredito"]
    assert res["configs"]["S0"]["extras"]["perna_indice_rs"] == 0.0
    assert res["configs"]["S0"]["extras"]["contratos_medio"] == 0.0
    assert res["configs"]["S1"]["extras"]["contratos_medio"] > 0.0
    assert res["configs"]["S2"]["trocas_regime"] == 0 and res["configs"]["R1"]["trocas_regime"] is not None
    assert "a_intersecao" in res["comparacoes_pre_registradas"] and res["n_tentativas_livro"] == 22
    # chaves de sempre vem da principal
    assert res["metricas"] == res["configs"]["S2"]["metricas"] and res["veredito"] == res["configs"]["S2"]["veredito"]
    # e tudo vira JSON sem erro (a trava grava com json.dumps puro)
    json.dumps(res, allow_nan=True)
    json.dumps(gravado["registrar"][0][0][2], allow_nan=True)


def test_holdout_multiplo_s1_nao_depende_das_funcoes_de_hedge_do_robo_ao_vivo(monkeypatch, mercado):
    """O S1 usa a copia congelada do hedge de 1 contrato: reescrever carteira.ajustar_hedge nao o move."""
    sinais, ret, cdi, excesso, nivel = mercado
    ref = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0)
    monkeypatch.setattr(ct, "ajustar_hedge", lambda *a, **k: (7, None, "abertura"))
    monkeypatch.setattr(ct, "contratos_hedge", lambda *a, **k: 7)
    alt = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0)
    pd.testing.assert_frame_equal(ref["serie"], alt["serie"])
    assert int(alt["serie"]["contratos"].max()) == 1


def test_hedge_legado_congelado_1_contrato_ate_200_mil_2_acima():
    assert bt._contratos_hedge_legado(150_000.0) == 1 and bt._contratos_hedge_legado(200_000.0) == 2
    assert bt._contratos_hedge_legado(0.0) == 0 and bt._contratos_hedge_legado(float("nan")) == 0
    est = {"hedge": {"contratos": 0}}
    h = bt._ajustar_hedge_legado(est, pd.Timestamp("2022-03-31"), 100_000.0)
    assert h["motivo"] == "abertura" and h["contratos"] == 1 and h["vencimento"] is not None
    est2 = {"hedge": {"contratos": 1, "vencimento": h["vencimento"]}}
    assert bt._ajustar_hedge_legado(est2, pd.Timestamp("2022-03-31"), 100_000.0)["motivo"] == "manter"
    assert bt._ajustar_hedge_legado(est2, pd.Timestamp("2022-03-31"), 100_000.0, beta60=0.9)["motivo"] == "beta"
    assert bt._ajustar_hedge_legado(est2, pd.Timestamp("2022-03-31"), 250_000.0)["motivo"] == "tamanho"
    perto = {"hedge": {"contratos": 1, "vencimento": h["vencimento"]}}
    assert bt._ajustar_hedge_legado(perto, pd.Timestamp(h["vencimento"]), 100_000.0)["motivo"] == "roll"


def test_configuracoes_desconhecida_levanta_e_s0_s1_nao_tem_plano(mercado):
    _, _, cdi, excesso, _ = mercado
    c = bt.configuracoes(["S0", "S1", "S2", "R3"], excesso, cdi)
    assert c["S0"] == {"com_hedge": False, "regime": None} and c["S1"] == {"com_hedge": True, "regime": None}
    assert c["S2"]["regime"] is not None and c["R3"]["regime"] is not None
    with pytest.raises(ValueError):
        bt.configuracoes(["X9"], excesso, cdi)


def test_config_holdout_e_estavel_e_nao_depende_de_caminho():
    from quant import livro
    a = bt.config_holdout("S2", bt.COMPARACOES_DECLARADAS, 100_000.0, "/Users/x/a/sinais_2011_2026.parquet")
    b = bt.config_holdout("S2", bt.COMPARACOES_DECLARADAS, 100_000.0, "sinais_2011_2026.parquet")
    assert livro.hash_config(a) == livro.hash_config(b)
    assert a["comparacoes"] == ["S0", "S1", "R1", "R2", "R3", "R4", "R5"] and a["principal"] == "S2"
    assert livro.hash_config(a) != livro.hash_config(bt.config_holdout("R3", bt.COMPARACOES_DECLARADAS, 100_000.0))


def test_main_holdout_com_comparar_chama_a_abertura_multipla(monkeypatch):
    chamadas = {}
    monkeypatch.setattr(bt, "carregar_do_banco", lambda *a, **k: {
        "sinais": pd.DataFrame(), "retornos": pd.DataFrame(), "cdi": pd.Series(dtype=float),
        "excesso": pd.Series(dtype=float), "nivel": pd.Series(dtype=float), "fatores": None})
    monkeypatch.setattr(bt.rg, "plano_da_variante", lambda *a, **k: None)
    monkeypatch.setattr(bt, "rodar_holdout_multiplo",
                        lambda *a, **k: chamadas.update(k) or {"metricas": {}, "veredito": {}})
    monkeypatch.setattr(bt, "relatorio", lambda *a, **k: "ok")
    assert bt.main(["--janela", "holdout", "--abrir-holdout", "--regime", "S2",
                    "--comparar", "S0,S1,R1,R2,R3,R4,R5", "--sinais", "x/sinais.parquet"]) == 1
    assert chamadas["principal"] == "S2" and chamadas["comparar"] == ["S0", "S1", "R1", "R2", "R3", "R4", "R5"]
    assert chamadas["config"]["sinais"] == "sinais.parquet"


# ─────────────────────────────────────────────────────────────
# Mao (tamanho da posicao) dentro do motor
# ─────────────────────────────────────────────────────────────
def _rodar_sem_hedge(sinais, ret, cdi, **kw):
    return bt.rodar(sinais, ret, cdi, ini=INI, fim=FIM, capital=100_000.0, com_hedge=False, **kw)


def test_mao_fixa_em_um_reproduz_o_motor_sem_mao(mercado):
    sinais, ret, cdi, _, _ = mercado
    a = _rodar_sem_hedge(sinais, ret, cdi)
    b = _rodar_sem_hedge(sinais, ret, cdi, mao={"regra": "fixa", "exposicao": 1.0})
    pd.testing.assert_frame_equal(a["serie"], b["serie"].drop(columns=["exposicao_mao"]))
    assert b["custo_mao"] == 0.0 and (b["serie"]["exposicao_mao"] == 1.0).all()


def test_mao_desligada_nao_acrescenta_coluna_nem_chave(mercado):
    sinais, ret, cdi, _, _ = mercado
    a = _rodar_sem_hedge(sinais, ret, cdi)
    assert "exposicao_mao" not in a["serie"].columns and "mao" not in a


def test_mao_fixa_em_meio_fica_perto_de_metade_do_resultado_das_acoes(mercado):
    sinais, _, _, _, _ = mercado
    ret = _retornos(taxa=0.0006, seed=9)
    cheio = _rodar_sem_hedge(sinais, ret, _cdi(0.0))
    meio = _rodar_sem_hedge(sinais, ret, _cdi(0.0), mao={"regra": "fixa", "exposicao": 0.5})
    g_cheio = cheio["serie"]["patrimonio"].iloc[-1] - 100_000.0
    g_meio = meio["serie"]["patrimonio"].iloc[-1] - 100_000.0
    assert g_cheio > 1_000
    assert abs(g_meio / g_cheio - 0.5) < 0.08
    ok, erro = bt.verificar_contabilidade(meio["serie"])
    assert ok, erro


def test_mao_com_cdi_a_parte_fora_das_acoes_rende_o_cdi(mercado):
    """Com retorno das acoes zero e e = 0,5, a metade 'vendida' rende o CDI sobre o valor das acoes."""
    sinais, _, _, _, _ = mercado
    ret = _retornos(taxa=0.0, seed=2) * 0.0
    cdi = _cdi(0.0004)
    cheio = _rodar_sem_hedge(sinais, ret, cdi)
    meio = _rodar_sem_hedge(sinais, ret, cdi, mao={"regra": "fixa", "exposicao": 0.5})
    # as acoes nao rendem nada: o patrimonio so ganha CDI no caixa; na versao meio, mais CDI (sobre metade das acoes)
    assert meio["serie"]["patrimonio"].iloc[-1] > cheio["serie"]["patrimonio"].iloc[-1]


def test_mao_por_volatilidade_diminui_a_mao_no_choque_e_cobra_custo(mercado):
    sinais, _, cdi, _, _ = mercado
    dias = _pregoes()
    rng = np.random.default_rng(4)
    vol = np.full(len(dias), 0.004)
    vol[300:340] = 0.03                                   # choque de volatilidade
    ret = pd.DataFrame({t: rng.normal(0.0003, vol) for t in _retornos().columns}, index=dias)
    r = _rodar_sem_hedge(sinais, ret, cdi, mao={"regra": "vol", "janela": 21, "teto": 1.0})
    e = r["serie"].set_index("data")["exposicao_mao"]
    assert e.min() < 0.7 and e.max() <= 1.0 + 1e-12
    assert r["custo_mao"] > 0
    ok, erro = bt.verificar_contabilidade(r["serie"])
    assert ok, erro


def test_mao_por_queda_corta_depois_da_queda_e_nunca_alavanca(mercado):
    sinais, _, cdi, _, _ = mercado
    dias = _pregoes()
    ret = pd.DataFrame({t: np.where(np.arange(len(dias)) == 200, -0.15, 0.0003) for t in _retornos().columns}, index=dias)
    r = _rodar_sem_hedge(sinais, ret, cdi, mao={"regra": "queda", "limiar": 0.05})
    e = r["serie"].set_index("data")["exposicao_mao"]
    assert e.min() == 0.5 and e.max() == 1.0
    primeiro_corte = e.index[(e < 1.0).to_numpy().argmax()]
    assert primeiro_corte > dias[200]                       # so DEPOIS da queda, com a defasagem do projeto


def test_mao_do_passado_nao_depende_do_futuro(mercado):
    sinais, ret, cdi, _, _ = mercado
    cfg = {"regra": "vol", "janela": 21, "teto": 1.0}
    a = _rodar_sem_hedge(sinais, ret, cdi, mao=cfg)
    dias = _pregoes()
    alt = ret.copy()
    alt.iloc[400:] = np.random.default_rng(8).normal(-0.01, 0.04, alt.iloc[400:].shape)
    b = _rodar_sem_hedge(sinais, alt, cdi, mao=cfg)
    sa, sb = a["serie"].set_index("data"), b["serie"].set_index("data")
    corte = dias[400]
    pd.testing.assert_frame_equal(sa[sa.index < corte][["patrimonio", "caixa", "exposicao_mao"]],
                                  sb[sb.index < corte][["patrimonio", "caixa", "exposicao_mao"]])


def test_mao_regra_desconhecida_levanta(mercado):
    sinais, ret, cdi, _, _ = mercado
    with pytest.raises(ValueError):
        _rodar_sem_hedge(sinais, ret, cdi, mao={"regra": "palpite"})


def test_mao_funciona_junto_com_o_regime(mercado):
    sinais, ret, cdi, excesso, nivel = mercado
    r = bt.rodar(sinais, ret, cdi, excesso, nivel, ini=INI, fim=FIM, capital=100_000.0,
                 regime=_plano(_pregoes(), razao=0.5), mao={"regra": "vol", "janela": 21, "teto": 1.0})
    ok, erro = bt.verificar_contabilidade(r["serie"])
    assert ok, erro

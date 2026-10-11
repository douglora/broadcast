"""A tabela do leitor do terminal: colunas estaveis e documentadas, uma linha por ticker, os mesmos numeros da ficha, vazio onde nao ha dado."""
import math
from datetime import date

import pandas as pd
import pytest

from quant import terminal as T
from quant.testes.terminal_fixture import montar_terminal

HOJE = date(2026, 10, 12)

# O contrato de colunas: quem usa a tabela depende destes nomes. Mudar um nome aqui e quebrar o robo; acrescentar no fim e seguro.
COLUNAS_ESTAVEIS = [
    "nome", "classe", "setor", "subsetor", "preco", "mcap_rs", "liq_21d_rs", "tir_pct", "tir_prudente_pct", "tir_premio_pp", "tir_premio_hoje_pp",
    "ciclo_lucro", "ciclo_razao", "tir_caixa_g0_pct", "tir_caixa_diverge", "tir_casas", "consenso_upside_pct", "consenso_alvo_n", "consenso_nota",
    "consenso_pct_compra", "consenso_lpa_rev_30d_pct", "consenso_lpa_rev_90d_pct", "consenso_lpa_subiram_30d", "consenso_lpa_cortaram_30d",
    "consenso_pl_proj", "insiders_saldo_90d_rs", "insiders_saldo_gestao_90d_rs", "insiders_negocios_90d", "insiders_idade_dias", "aluguel_taxa_aa",
    "aluguel_pct_float", "aluguel_var_20d_pct", "aluguel_dias_para_cobrir", "aluguel_saldo_rs", "noticia_n_7d", "noticia_score_7d", "noticia_max_7d",
    "dias_ate_resultado", "dias_ate_provento_ex", "reacao_resultado_media_abs_pct", "pl", "pvp", "ev_ebitda", "div_liq_ebitda", "dy_12m_pct", "roe_pct",
    "mg_liq_12m_pct", "cresc_lucro_12m_pct", "balanco_idade_dias", "pl_pct_5a", "pl_z_5a", "pvp_pct_5a", "ev_ebitda_pct_5a", "div_cp_pct",
    "div_cobertura_juros", "div_custo_pct", "div_moeda_estrangeira_pct", "iv_atm_pct", "iv_pctil", "opcoes_pc_oi", "opcoes_dor_maxima_dist_pct",
    "retorno_12d_pct", "retorno_12d_vs_pares_pp", "fundos_pct_classe",
    # acrescentadas em 12/10/2026 (sempre no fim: a ordem das anteriores nao muda)
    "resultado_antes_da_abertura", "resultado_momento_confianca", "iv_skew_10_pp", "opcoes_pregao_incompleto"]


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    montar_terminal(tmp_path)
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path))
    T.limpar_cache()
    yield tmp_path
    T.limpar_cache()


def test_colunas_estaveis_na_ordem_combinada(raiz):
    df = T.tabela(["PETR4"], hoje=HOJE)
    assert list(df.columns) == COLUNAS_ESTAVEIS
    assert T.COLUNAS_TABELA == COLUNAS_ESTAVEIS


def test_toda_coluna_esta_documentada_no_docstring(raiz):
    for c in COLUNAS_ESTAVEIS:
        assert c in T.tabela.__doc__, c
    assert "tir_premio_pp" in T.tabela.__doc__ and "ciclo_lucro" in T.tabela.__doc__ and "dias_ate_resultado" in T.tabela.__doc__


def test_uma_linha_por_ticker_na_ordem_pedida_com_indice_ticker(raiz):
    df = T.tabela(["DIRR3", "PETR4", "BBAS3"], hoje=HOJE)
    assert list(df.index) == ["DIRR3", "PETR4", "BBAS3"] and df.index.name == "ticker"


def test_colunas_numericas_sao_float_e_as_de_texto_ficam_texto(raiz):
    df = T.tabela(["PETR4", "BBAS3"], hoje=HOJE)
    for c in COLUNAS_ESTAVEIS:
        if c in ("nome", "classe", "setor", "subsetor"):
            assert df[c].dtype == object, c
        else:
            assert pd.api.types.is_float_dtype(df[c]), c


def test_numeros_da_tabela_sao_os_da_ficha(raiz):
    df = T.tabela(["PETR4"], hoje=HOJE)
    f = T.ficha("PETR4", hoje=HOJE)
    r = df.loc["PETR4"]
    assert r["tir_prudente_pct"] == f["tir"]["tir_prudente"]["pct"] == 18.39
    assert r["tir_premio_pp"] == 11.68 and r["ciclo_lucro"] == 0.0 and r["tir_caixa_diverge"] == 0.0 and r["tir_casas"] == 1
    assert r["consenso_upside_pct"] == 4.1 and r["consenso_lpa_rev_30d_pct"] == pytest.approx(16.67, abs=0.01) and r["consenso_lpa_subiram_30d"] == 3
    assert r["insiders_saldo_90d_rs"] == -27900 and r["insiders_saldo_gestao_90d_rs"] == 12100 and r["insiders_idade_dias"] == 42
    assert r["aluguel_taxa_aa"] == 0.05 and r["aluguel_var_20d_pct"] == -28.0
    assert r["noticia_n_7d"] == 4 and r["noticia_score_7d"] == 5 and r["noticia_max_7d"] == 3
    assert r["dias_ate_resultado"] == 29 and r["dias_ate_provento_ex"] == 1 and r["reacao_resultado_media_abs_pct"] == 3.14
    assert r["pl"] == 5.41 and r["ev_ebitda"] == 3.98 and r["div_liq_ebitda"] == 1.14 and r["balanco_idade_dias"] == 103
    assert r["pl_pct_5a"] == 73 and r["div_cp_pct"] == 16.5 and r["iv_atm_pct"] == 32.0 and r["iv_pctil"] == 50.0 and r["opcoes_pc_oi"] == 1.12
    assert r["retorno_12d_pct"] == 2.01 and r["retorno_12d_vs_pares_pp"] == 3.01 and r["fundos_pct_classe"] == 7.03
    assert r["resultado_antes_da_abertura"] == 0.0 and r["resultado_momento_confianca"] == 1.0 and r["iv_skew_10_pp"] == 10.0 and r["opcoes_pregao_incompleto"] == 1.0


def test_antes_da_abertura_na_tabela_true_false_nan(raiz):
    t = T.tabela(["PETR4", "PRIO3", "DIRR3", "VALE3"], hoje=HOJE)["resultado_antes_da_abertura"]
    assert t["PETR4"] == 0.0 and t["PRIO3"] == 1.0 and math.isnan(t["DIRR3"]) and math.isnan(t["VALE3"])


def test_onde_nao_ha_dado_e_nan_nunca_zero(raiz):
    r = T.tabela(["BBAS3", "DIRR3"], hoje=HOJE).loc["BBAS3"]
    assert math.isnan(r["ev_ebitda"]) and math.isnan(r["div_liq_ebitda"]) and math.isnan(r["tir_pct"]) and math.isnan(r["consenso_upside_pct"])
    assert math.isnan(r["div_cp_pct"]) and math.isnan(r["iv_atm_pct"]) and math.isnan(r["noticia_score_7d"])
    assert r["noticia_n_7d"] == 0                                                  # zero noticias e um fato (contado), score sem noticia nao e zero
    d = T.tabela(["DIRR3"], hoje=HOJE).loc["DIRR3"]
    assert d["ciclo_lucro"] == 2 and d["tir_prudente_pct"] == 10.0 and d["tir_pct"] == 30.0 and math.isnan(d["consenso_nota"])


def test_dado_velho_demais_vira_nan_na_tabela_tambem(raiz):
    r = T.tabela(["PETR4"], hoje=date(2026, 10, 20)).loc["PETR4"]
    assert math.isnan(r["tir_prudente_pct"]) and math.isnan(r["aluguel_taxa_aa"]) and math.isnan(r["consenso_upside_pct"]) and math.isnan(r["pl"])


def test_sem_tickers_traz_as_acoes_do_universo(raiz):
    df = T.tabela(hoje=HOJE)
    assert sorted(df.index) == ["BBAS3", "DIRR3", "PETR4", "PRIO3"]                # so acao_br: sem BDR nem EUA
    df2 = T.tabela(hoje=HOJE, classes=("acao_br", "bdr"))
    assert "NVDC34" in df2.index and df2.loc["NVDC34", "consenso_alvo_n"] == 40


def test_ticker_fora_do_universo_entra_como_linha_vazia(raiz):
    df = T.tabela(["XXXX9"], hoje=HOJE)
    assert list(df.index) == ["XXXX9"] and df.loc["XXXX9"].drop(["nome", "classe", "setor", "subsetor"]).isna().sum() >= len(COLUNAS_ESTAVEIS) - 12


def test_cobertura_conta_quantos_tem_cada_coluna(raiz):
    df = T.tabela(hoje=HOJE)
    c = T.cobertura(df)
    assert c["tir_prudente_pct"] == 2 and c["pl"] == 3 and c["iv_atm_pct"] == 1 and "nome" not in c.index


def test_sem_terminal_a_tabela_vem_vazia_de_dado_sem_levantar(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path / "x"))
    T.limpar_cache()
    df = T.tabela(["PETR4"], hoje=HOJE)
    assert df.shape == (1, len(COLUNAS_ESTAVEIS)) and df.drop(columns=["nome", "classe", "setor", "subsetor"]).isna().all().all()

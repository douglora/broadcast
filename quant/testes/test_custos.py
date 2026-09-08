"""
Testes do modelo de custos (M9).

Todos os numeros esperados estao escritos como a ARITMETICA que os produz (10_000 * 0.00030),
nunca como o resultado ja calculado: se alguem mudar uma constante do modulo, o teste tem que
falhar mostrando qual premissa mudou, e nao um numero magico sem procedencia.
"""
import numpy as np
import pandas as pd

from quant import custos as c


def test_faixas_de_spread_nos_limites():
    # o limite pertence a faixa MAIS BARATA
    assert abs(c.meio_spread(50e6) - 0.0025) < 1e-12
    assert abs(c.meio_spread(20e6) - 0.0025) < 1e-12
    assert abs(c.meio_spread(20e6 - 0.01) - 0.0040) < 1e-12
    assert abs(c.meio_spread(10e6) - 0.0040) < 1e-12
    assert abs(c.meio_spread(5e6) - 0.0040) < 1e-12
    assert abs(c.meio_spread(5e6 - 0.01) - 0.0080) < 1e-12
    assert abs(c.meio_spread(0.0) - 0.0080) < 1e-12


def test_adtv_ausente_cai_na_faixa_mais_cara():
    assert abs(c.meio_spread(float("nan")) - 0.0080) < 1e-12
    assert abs(c.meio_spread(None) - 0.0080) < 1e-12
    assert abs(c.meio_spread("liquido") - 0.0080) < 1e-12
    assert abs(c.meio_spread(-1.0) - 0.0080) < 1e-12


def test_meio_spread_aceita_series_e_devolve_series_do_mesmo_tamanho():
    s = pd.Series([50e6, 20e6, 6e6, 1e6, np.nan], index=["A", "B", "C", "D", "E"])
    r = c.meio_spread(s)
    assert isinstance(r, pd.Series)
    assert len(r) == len(s)
    assert list(r.index) == list(s.index)
    assert abs(r["A"] - 0.0025) < 1e-12 and abs(r["B"] - 0.0025) < 1e-12
    assert abs(r["C"] - 0.0040) < 1e-12
    assert abs(r["D"] - 0.0080) < 1e-12 and abs(r["E"] - 0.0080) < 1e-12
    vazia = c.meio_spread(pd.Series(dtype=float))
    assert isinstance(vazia, pd.Series) and len(vazia) == 0


def test_impacto_e_dez_bps_em_um_por_cento_e_vinte_bps_em_quatro_por_cento():
    # participacao de 1% do ADTV: 10 bps por construcao
    assert abs(c.impacto(100_000.0, 10e6) - 10.0 / 10_000.0) < 1e-12
    # participacao de 4%: sqrt(4) = 2, entao o dobro
    assert abs(c.impacto(400_000.0, 10e6) - 2.0 * 10.0 / 10_000.0) < 1e-12
    # participacao de 0,25%: sqrt(0,25) = 0,5, metade
    assert abs(c.impacto(25_000.0, 10e6) - 0.5 * 10.0 / 10_000.0) < 1e-12


def test_impacto_sem_liquidez_devolve_teto_em_vez_de_infinito():
    assert abs(c.impacto(10_000.0, 0.0) - c.IMPACTO_TETO) < 1e-12
    assert abs(c.impacto(10_000.0, float("nan")) - c.IMPACTO_TETO) < 1e-12
    assert abs(c.impacto(10_000.0, -1.0) - c.IMPACTO_TETO) < 1e-12
    # ordem absurda em papel liquido tambem para no teto (o modelo nao extrapola)
    assert abs(c.impacto(1e12, 1e6) - c.IMPACTO_TETO) < 1e-12
    # sem ordem nao ha impacto
    assert abs(c.impacto(0.0, 10e6) - 0.0) < 1e-12
    assert abs(c.impacto(float("nan"), 10e6) - 0.0) < 1e-12


def test_custo_ordem_decompoe_a_faixa_liquida():
    o = c.custo_ordem(10_000.0, 50e6)
    assert abs(o["b3"] - 10_000.0 * 0.00030) < 1e-12
    assert abs(o["spread"] - 10_000.0 * 0.0025) < 1e-12
    assert abs(o["fracionario"] - 0.0) < 1e-12
    assert abs(o["impacto"] - 10_000.0 * c.impacto(10_000.0, 50e6)) < 1e-12
    assert abs(o["total"] - (o["b3"] + o["spread"] + o["fracionario"] + o["impacto"])) < 1e-12
    assert abs(o["bps"] - o["total"] / 10_000.0 * 10_000.0) < 1e-12


def test_fracionario_soma_exatamente_vinte_bps():
    cheio = c.custo_ordem(10_000.0, 50e6)
    frac = c.custo_ordem(10_000.0, 50e6, fracionario=True)
    assert abs(frac["fracionario"] - 10_000.0 * 0.0020) < 1e-12
    assert abs((frac["total"] - cheio["total"]) - 10_000.0 * 0.0020) < 1e-12
    assert abs((frac["bps"] - cheio["bps"]) - 20.0) < 1e-12
    # so o componente do fracionario muda
    assert abs(frac["b3"] - cheio["b3"]) < 1e-12
    assert abs(frac["spread"] - cheio["spread"]) < 1e-12
    assert abs(frac["impacto"] - cheio["impacto"]) < 1e-12


def test_leilao_troca_apenas_a_taxa_da_b3():
    normal = c.custo_ordem(10_000.0, 50e6)
    leilao = c.custo_ordem(10_000.0, 50e6, leilao=True)
    assert abs(leilao["b3"] - 10_000.0 * 0.00032) < 1e-12
    assert abs(leilao["spread"] - normal["spread"]) < 1e-12
    assert abs((leilao["total"] - normal["total"]) - 10_000.0 * (0.00032 - 0.00030)) < 1e-12


def test_ida_e_volta_na_faixa_iliquida_bate_com_a_conta_a_mao():
    # R$ 20 mil em papel com ADTV de R$ 2 mi: participacao de 1% -> impacto de 10 bps
    # por lado: 3 bps de B3 + 80 bps de meio-spread + 10 bps de impacto = 93 bps
    ida = c.custo_ordem(20_000.0, 2e6)
    assert abs(ida["b3"] - 20_000.0 * 0.00030) < 1e-12
    assert abs(ida["spread"] - 20_000.0 * 0.0080) < 1e-12
    assert abs(ida["impacto"] - 20_000.0 * 0.0010) < 1e-12
    assert abs(ida["total"] - 20_000.0 * (0.00030 + 0.0080 + 0.0010)) < 1e-12
    assert abs(ida["bps"] - (0.00030 + 0.0080 + 0.0010) * 10_000.0) < 1e-12
    volta = c.custo_ordem(-20_000.0, 2e6)          # venda: mesmo custo, sinal e de quem chama
    assert abs(volta["total"] - ida["total"]) < 1e-12
    assert abs((ida["total"] + volta["total"]) - 2.0 * 20_000.0 * 0.0093) < 1e-12


def test_estresse_dobra_as_estimativas_e_nao_toca_na_taxa_da_b3():
    simples = c.custo_ordem(50_000.0, 3e6, fracionario=True)
    dobro = c.custo_ordem(50_000.0, 3e6, fracionario=True, estresse=2.0)
    # a taxa da B3 e publicada: identica nos dois cenarios
    assert abs(dobro["b3"] - simples["b3"]) < 1e-12
    assert abs(dobro["b3"] - 50_000.0 * 0.00030) < 1e-12
    # os componentes estimados dobram
    assert abs(dobro["spread"] - 2.0 * simples["spread"]) < 1e-12
    assert abs(dobro["fracionario"] - 2.0 * simples["fracionario"]) < 1e-12
    assert abs(dobro["impacto"] - 2.0 * simples["impacto"]) < 1e-12
    # e o total e a B3 uma vez mais o resto duas vezes
    assert abs(dobro["total"] - (simples["b3"] + 2.0 * (simples["total"] - simples["b3"]))) < 1e-12
    # estresse invalido nao estressa nada
    assert abs(c.custo_ordem(50_000.0, 3e6, estresse=float("nan"))["total"]
               - c.custo_ordem(50_000.0, 3e6)["total"]) < 1e-12


def test_custo_win_e_tarifa_mais_um_tick():
    w = c.custo_win(1)
    assert abs(w["tarifa"] - 1.0 * 0.35) < 1e-12
    assert abs(w["tick"] - 1.0 * 5.0 * 0.20) < 1e-12
    assert abs(w["total"] - (1.0 * 0.35 + 1.0 * 5.0 * 0.20)) < 1e-12
    dois = c.custo_win(2)
    assert abs(dois["total"] - 2.0 * w["total"]) < 1e-12
    assert abs(c.custo_win(-2)["total"] - dois["total"]) < 1e-12       # o lado nao importa
    assert abs(c.custo_win(0)["total"] - 0.0) < 1e-12


def test_custo_win_com_estresse_multiplica_so_o_tick():
    simples = c.custo_win(2)
    dobro = c.custo_win(2, estresse=2.0)
    assert abs(dobro["tarifa"] - simples["tarifa"]) < 1e-12
    assert abs(dobro["tick"] - 2.0 * simples["tick"]) < 1e-12
    assert abs(dobro["total"] - (2.0 * 0.35 + 2.0 * 2.0 * 5.0 * 0.20)) < 1e-12


def test_jcp_liquido_desconta_quinze_por_cento_na_fonte():
    assert abs(c.jcp_liquido(1_000.0) - 1_000.0 * (1.0 - 0.15)) < 1e-12
    assert abs(c.jcp_liquido(0.0) - 0.0) < 1e-12
    assert abs(c.jcp_liquido(float("nan")) - 0.0) < 1e-12


def test_custo_aluguel_usa_piso_markup_medio_e_prazo():
    markup_medio = (1.4 + 3.0) / 2.0
    assert abs(markup_medio - 2.2) < 1e-12
    # taxa acima do piso: entra a taxa
    assert abs(c.custo_aluguel(0.02, 100_000.0, 21)
               - 0.02 * markup_medio * 100_000.0 * (21.0 / 252.0)) < 1e-12
    # taxa abaixo do piso: entra o piso de 0,5% a.a.
    assert abs(c.custo_aluguel(0.001, 100_000.0, 21)
               - 0.005 * markup_medio * 100_000.0 * (21.0 / 252.0)) < 1e-12
    # taxa ausente tambem cai no piso
    assert abs(c.custo_aluguel(float("nan"), 100_000.0, 21)
               - c.custo_aluguel(0.0, 100_000.0, 21)) < 1e-12
    # o prazo e proporcional e a tarifa e somada uma vez
    assert abs(c.custo_aluguel(0.02, 100_000.0, 42) - 2.0 * c.custo_aluguel(0.02, 100_000.0, 21)) < 1e-12
    assert abs(c.custo_aluguel(0.02, 100_000.0, 21, tarifa=10.0)
               - (0.02 * markup_medio * 100_000.0 * (21.0 / 252.0) + 10.0)) < 1e-12
    # sem posicao ou sem prazo nao ha contrato: nem tarifa
    assert abs(c.custo_aluguel(0.02, 0.0, 21, tarifa=10.0) - 0.0) < 1e-12
    assert abs(c.custo_aluguel(0.02, 100_000.0, 0, tarifa=10.0) - 0.0) < 1e-12


def test_custo_carteira_precifica_ordem_a_ordem_e_soma():
    ordens = pd.DataFrame([
        {"ticker": "LIQD3", "valor": 30_000.0, "adtv": 50e6, "fracionario": False},
        {"ticker": "MEIO3", "valor": 20_000.0, "adtv": 10e6, "fracionario": True},
        {"ticker": "ILIQ3", "valor": 20_000.0, "adtv": 2e6, "fracionario": False},
        {"ticker": "SEMV3", "valor": 10_000.0, "adtv": float("nan"), "fracionario": False},
    ])
    out = c.custo_carteira(ordens)
    assert len(out) == len(ordens)
    assert list(out.columns) == c.COLUNAS_CARTEIRA
    assert list(out["ticker"]) == ["LIQD3", "MEIO3", "ILIQ3", "SEMV3"]
    linha = out.set_index("ticker")
    # ILIQ3 e a conta a mao do teste de ida e volta
    assert abs(linha.loc["ILIQ3", "custo_total"] - 20_000.0 * (0.00030 + 0.0080 + 0.0010)) < 1e-12
    # MEIO3 esta na faixa de 40 bps e paga o adicional de fracionario
    assert abs(linha.loc["MEIO3", "custo_spread"] - 20_000.0 * 0.0040) < 1e-12
    assert abs(linha.loc["MEIO3", "custo_fracionario"] - 20_000.0 * 0.0020) < 1e-12
    # SEMV3 nao tem ADTV: faixa mais cara e teto de impacto
    assert abs(linha.loc["SEMV3", "custo_spread"] - 10_000.0 * 0.0080) < 1e-12
    assert abs(linha.loc["SEMV3", "custo_impacto"] - 10_000.0 * c.IMPACTO_TETO) < 1e-12
    # o total do modulo bate com a soma das linhas e com o attrs
    soma = sum(c.custo_ordem(v, a, fracionario=f)["total"]
               for v, a, f in zip(ordens["valor"], ordens["adtv"], ordens["fracionario"]))
    assert abs(c.total_carteira(out) - soma) < 1e-12
    assert abs(out.attrs["custo_total"] - soma) < 1e-12
    # a boleta original nao foi tocada
    assert list(ordens.columns) == ["ticker", "valor", "adtv", "fracionario"]


def test_custo_carteira_com_estresse_preserva_a_taxa_da_b3():
    ordens = pd.DataFrame([{"ticker": "ILIQ3", "valor": 20_000.0, "adtv": 2e6}])
    simples = c.custo_carteira(ordens)
    dobro = c.custo_carteira(ordens, estresse=2.0)
    assert abs(dobro["custo_b3"].iloc[0] - simples["custo_b3"].iloc[0]) < 1e-12
    assert abs(dobro["custo_spread"].iloc[0] - 2.0 * simples["custo_spread"].iloc[0]) < 1e-12
    assert c.total_carteira(dobro) > c.total_carteira(simples)
    # colunas opcionais ausentes viram False, nunca True por causa de NaN
    assert bool(simples["fracionario"].iloc[0]) is False
    assert abs(simples["custo_fracionario"].iloc[0] - 0.0) < 1e-12


def test_entrada_degenerada_devolve_schema_e_nao_levanta():
    zero = c.custo_ordem(0, 0)
    assert set(zero) == set(c.CHAVES_ORDEM)
    assert abs(zero["total"] - 0.0) < 1e-12 and abs(zero["bps"] - 0.0) < 1e-12
    lixo = c.custo_ordem("dez mil", "muito liquido", fracionario=float("nan"))
    assert abs(lixo["total"] - 0.0) < 1e-12
    assert abs(lixo["fracionario"] - 0.0) < 1e-12
    vazia = c.custo_carteira(pd.DataFrame())
    assert list(vazia.columns) == c.COLUNAS_CARTEIRA and len(vazia) == 0
    assert list(c.custo_carteira(None).columns) == c.COLUNAS_CARTEIRA
    assert abs(c.total_carteira(vazia) - 0.0) < 1e-12
    assert abs(c.total_carteira(pd.DataFrame({"outra": [1.0]})) - 0.0) < 1e-12
    # boleta com texto no lugar de numero custa zero, mas nao derruba a rodada
    suja = c.custo_carteira(pd.DataFrame([{"ticker": "XXXX3", "valor": "n/d", "adtv": None}]))
    assert len(suja) == 1 and abs(suja["custo_total"].iloc[0] - 0.0) < 1e-12
    assert abs(c.custo_win(float("nan"))["total"] - 0.0) < 1e-12
    assert abs(c.custo_aluguel("x", "y", "z") - 0.0) < 1e-12


def test_main_imprime_a_tabela_das_tres_faixas(capsys):
    assert c.main(["--valor", "10000", "--estresse", "1"]) == 0
    saida = capsys.readouterr().out
    assert "adtv" in saida and "impacto" in saida
    assert "20,000,000" in saida and "5,000,000" in saida and "2,000,000" in saida
    assert "850.00" in saida                       # JCP liquido de R$ 1.000 brutos
    assert c.main(["--valor", "30000", "--estresse", "2", "--fracionario"]) == 0
    # 2 cabecalhos + 1 linha por faixa de ADTV + 3 rodapes (WIN, JCP, aluguel)
    linhas = capsys.readouterr().out.strip().splitlines()
    assert len(linhas) == 2 + len(c.FAIXAS_SPREAD) + 3


# ─────────────────────────────────────────────────────────────
# Corretagem: o custo FIXO por ordem, e por que ele e perigoso aqui
# ─────────────────────────────────────────────────────────────
def test_corretagem_e_por_ordem_e_nao_por_valor():
    """Custo fixo por ordem pesa mais quanto MENOR a ordem — e o rebalanceamento
    incremental desta estrategia gera muitas ordens pequenas."""
    grande = c.custo_ordem(20_000, 50e6, corretagem=15.0)
    pequena = c.custo_ordem(2_000, 50e6, corretagem=15.0)
    assert grande["corretagem"] == pequena["corretagem"] == 15.0
    # em bps a mesma corretagem custa dez vezes mais na ordem dez vezes menor
    so_corr_grande = 15.0 / 20_000 * c.BPS
    so_corr_pequena = 15.0 / 2_000 * c.BPS
    assert abs(so_corr_pequena - 10 * so_corr_grande) < 1e-9
    assert pequena["bps"] > grande["bps"]


def test_corretagem_padrao_e_zero_e_ordem_vazia_nao_paga():
    assert c.custo_ordem(10_000, 50e6)["corretagem"] == 0.0
    assert c.custo_ordem(0, 50e6, corretagem=25.0)["corretagem"] == 0.0
    assert c.custo_ordem(10_000, 50e6, corretagem="nao e numero")["corretagem"] == 0.0
    assert c.custo_ordem(10_000, 50e6, corretagem=-5)["corretagem"] == 0.0


def test_corretagem_nao_e_afetada_por_estresse():
    """Estresse dobra o que e ESTIMADO. Tabela de corretora e preco publicado."""
    normal = c.custo_ordem(10_000, 50e6, corretagem=12.0)
    dobro = c.custo_ordem(10_000, 50e6, corretagem=12.0, estresse=2.0)
    assert normal["corretagem"] == dobro["corretagem"] == 12.0
    assert dobro["spread"] > normal["spread"]


def test_corretagem_maxima_responde_a_pergunta_da_corretora():
    """Quanto a corretora pode cobrar por ordem antes de comer o excesso esperado."""
    r = c.corretagem_maxima(excesso_pp=0.30, capital=100_000, ordens_ano=250)
    assert abs(r["excesso_reais"] - 300.0) < 1e-9
    assert abs(r["por_ordem"] - 1.20) < 1e-9
    assert r["ordens_ano"] == 250


def test_corretagem_maxima_com_entrada_degenerada_nao_levanta():
    assert c.corretagem_maxima(0.3, 100_000, 0)["por_ordem"] is None
    assert c.corretagem_maxima(0.0, 100_000, 250)["por_ordem"] == 0.0
    assert c.corretagem_maxima(-1.0, 100_000, 250)["por_ordem"] == 0.0


def test_custo_anual_de_uma_tabela_de_corretagem():
    """A conta que decide a corretora: R$/ano e p.p. ao ano sobre o capital."""
    r = c.custo_corretagem_ano(por_ordem=25.0, ordens_ano=250, capital=100_000)
    assert abs(r["reais_ano"] - 6_250.0) < 1e-9
    assert abs(r["pct_capital"] - 0.0625) < 1e-12
    assert abs(c.custo_corretagem_ano(0, 250, 100_000)["pct_capital"]) < 1e-12
    assert c.custo_corretagem_ano(25.0, 250, 0)["pct_capital"] is None

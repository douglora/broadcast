"""Sinais sinteticos minimos (so as colunas que a carteira le) para exercitar cada regra.

Aqui nao se testa se a estrategia ganha dinheiro: testa-se se a carteira obedece as
restricoes escritas na secao 7 do plano - banda de nomes, cap e piso, teto de setor, balde
iliquido, histerese, lote, hedge e a regra incremental de custo.
"""
import numpy as np
import pandas as pd
import pytest

from quant import carteira as ct
from quant import custos as cst
from quant.dados import calendario

COLUNAS_MIN = ["ticker", "rank", "elegivel", "passa_momentum", "passa_qualidade",
               "passa_crescimento", "vol252", "setor", "adtv21", "preco"]


def _sinais(n=30, vol_base=0.30, setor=None, adtv=50e6, preco=20.0, elegiveis=None):
    """n papeis ranqueados de 1 a n; vol cresce com o rank para o 1/vol ter o que fazer."""
    linhas = []
    for i in range(1, n + 1):
        t = f"AC{i:02d}3"
        eleg = True if elegiveis is None else (t in elegiveis)
        linhas.append({"ticker": t, "rank": float(i) if eleg else np.nan, "elegivel": eleg,
                       "passa_momentum": True, "passa_qualidade": True, "passa_crescimento": True,
                       "vol252": vol_base + i * 0.01, "adtv21": adtv, "preco": preco,
                       "setor": (setor or {}).get(t, f"setor{i % 6}")})
    return pd.DataFrame(linhas, columns=COLUNAS_MIN)


def _posicoes(tickers, qtd=100, meses=1):
    return {t: {"qtd": qtd, "preco_medio": 20.0, "meses": meses} for t in tickers}


@pytest.fixture(scope="module")
def sinais():
    return _sinais()


# ─────────────────────────────────────────────────────────────
# Selecao e histerese
# ─────────────────────────────────────────────────────────────
def test_seleciona_os_22_melhores_quando_a_carteira_esta_vazia(sinais):
    alvo, saidas = ct.selecionar(sinais, {})
    assert len(alvo) == ct.N_ALVO and saidas == {}
    assert alvo == [f"AC{i:02d}3" for i in range(1, 23)]


def test_nome_no_rank_39_fica_e_no_41_sai(sinais):
    s = _sinais(n=45)
    for rank, esperado in ((39.0, True), (41.0, False)):
        alvo, saidas = ct.selecionar(s.assign(rank=np.where(s["ticker"] == "AC013", rank, s["rank"])),
                                     _posicoes(["AC013"]))
        assert ("AC013" in alvo) is esperado
        assert (saidas.get("AC013") == "saida_rank") is (not esperado)


def test_falha_de_portao_obrigatorio_expulsa_seja_qual_for_o_rank(sinais):
    s = sinais.assign(passa_qualidade=np.where(sinais["ticker"] == "AC013", False, True),
                      elegivel=np.where(sinais["ticker"] == "AC013", False, sinais["elegivel"]))
    alvo, saidas = ct.selecionar(s, _posicoes(["AC013"]))
    assert saidas["AC013"] == "saida_gate" and "AC013" not in alvo


def test_teto_de_doze_meses_revoga_a_histerese_sem_forcar_venda(sinais):
    """Aos 12 meses o nome perde o passe livre e volta a disputar por rank. O de rank 1
    fica sem trade nenhum; o de rank 30, que so estava la pela histerese, sai."""
    alvo, saidas = ct.selecionar(sinais, _posicoes(["AC013"], meses=12))
    assert "AC013" in alvo and "AC013" not in saidas          # rank 1: continua, sem custo
    alvo2, saidas2 = ct.selecionar(sinais, _posicoes(["AC303"], meses=12))
    assert saidas2["AC303"] == "saida_prazo" and "AC303" not in alvo2
    alvo3, saidas3 = ct.selecionar(sinais, _posicoes(["AC303"], meses=11))
    assert "AC303" in alvo3 and "AC303" not in saidas3        # aos 11 meses a histerese vale


def test_carteira_inteira_completando_doze_meses_nao_zera():
    """Se todos os nomes entraram juntos, o teto de 12 meses nao pode esvaziar a carteira
    e recompra-la no mes seguinte pagando spread duas vezes por nada."""
    s = _sinais(n=30)
    posicoes = _posicoes([f"AC{i:02d}3" for i in range(1, 23)], meses=12)
    alvo, saidas = ct.selecionar(s, posicoes)
    assert len(alvo) == ct.N_ALVO
    assert not saidas


def test_papel_que_sumiu_do_universo_sai(sinais):
    alvo, saidas = ct.selecionar(sinais, _posicoes(["SUMIU3"]))
    assert saidas["SUMIU3"] == "saida_universo" and "SUMIU3" not in alvo


def test_histerese_segura_quem_ja_esta_dentro(sinais):
    """Um nome no rank 30 nao entra do zero, mas quem ja carrega nao vende por isso."""
    novo, _ = ct.selecionar(sinais, {})
    assert "AC303" not in novo
    mantido, saidas = ct.selecionar(sinais, _posicoes(["AC303"]))
    assert "AC303" in mantido and "AC303" not in saidas


def test_nunca_passa_do_teto_da_banda(sinais):
    posicoes = _posicoes([f"AC{i:02d}3" for i in range(1, 29)])   # 28 nomes carregados
    alvo, saidas = ct.selecionar(sinais, posicoes)
    assert len(alvo) == ct.BANDA[1]
    assert sum(1 for m in saidas.values() if m == "saida_rank") == 28 - ct.BANDA[1]


# ─────────────────────────────────────────────────────────────
# Pesos
# ─────────────────────────────────────────────────────────────
def test_pesos_somam_a_exposicao_e_respeitam_cap_e_piso():
    tickers = [f"AC{i:02d}3" for i in range(1, 23)]
    vol = {t: 0.20 + i * 0.02 for i, t in enumerate(tickers)}
    w = ct.pesos_alvo(tickers, vol, setor=None, adtv=None)
    assert abs(w.sum() - ct.EXPOSICAO_ALVO) < 1e-9
    assert w.max() <= ct.CAP_NOME + 1e-9 and w.min() >= ct.PISO_NOME - 1e-9
    assert not w.attrs["violacoes"]


def test_menos_volatil_pesa_mais():
    w = ct.pesos_alvo(["A", "B"], {"A": 0.10, "B": 0.40}, exposicao=0.70, cap=0.60, piso=0.01)
    assert w["A"] > w["B"] and abs(w.sum() - 0.70) < 1e-9


def test_teto_de_setor_segura_a_concentracao():
    tickers = [f"AC{i:02d}3" for i in range(1, 23)]
    setor = {t: ("banco" if i < 12 else f"outro{i}") for i, t in enumerate(tickers)}
    w = ct.pesos_alvo(tickers, {t: 0.30 for t in tickers}, setor=setor, adtv=None)
    banco = sum(w[t] for t in tickers if setor[t] == "banco")
    assert banco <= ct.CAP_SETOR + 1e-6
    assert abs(w.sum() - ct.EXPOSICAO_ALVO) < 1e-6


def test_balde_iliquido_nao_passa_de_quarenta_por_cento():
    tickers = [f"AC{i:02d}3" for i in range(1, 23)]
    adtv = {t: (1e6 if i < 15 else 50e6) for i, t in enumerate(tickers)}
    w = ct.pesos_alvo(tickers, {t: 0.30 for t in tickers}, setor=None, adtv=adtv)
    iliquidos = sum(w[t] for i, t in enumerate(tickers) if adtv[t] < ct.ADTV_ILIQUIDO)
    assert iliquidos <= ct.CAP_ILIQUIDOS * ct.EXPOSICAO_ALVO + 1e-6


def test_piso_infactivel_e_reportado_e_nao_violado_em_silencio():
    tickers = [f"AC{i:02d}3" for i in range(1, 26)]              # 25 x 3% = 75% > 70%
    w = ct.pesos_alvo(tickers, {t: 0.30 for t in tickers})
    assert w.attrs["violacoes"] and "piso" in w.attrs["violacoes"][0]
    assert abs(w.sum() - ct.EXPOSICAO_ALVO) < 1e-9
    assert w.min() >= ct.EXPOSICAO_ALVO / len(tickers) - 1e-9


def test_com_vol_igual_ninguem_encosta_no_piso():
    tickers = [f"AC{i:02d}3" for i in range(1, 23)]
    w = ct.pesos_alvo(tickers, {t: 0.30 for t in tickers})       # 70% / 22 = 3,18% > piso
    d = ct.diagnostico(w)
    assert d["n"] == 22 and d["fracao_no_piso"] == 0.0
    assert abs(d["dispersao"] - 1.0) < 1e-9
    assert ct.diagnostico(pd.Series(dtype=float))["n"] == 0


def test_o_piso_engole_a_maior_parte_da_carteira_com_vol_dispersa():
    """O aviso do docstring, medido: com 22 nomes e piso de 3% sobre exposicao de 70%, so
    sobram 4 p.p. para o 1/vol distribuir, e a maioria dos nomes fica presa no piso."""
    tickers = [f"AC{i:02d}3" for i in range(1, 23)]
    vol = {t: 0.15 + i * 0.03 for i, t in enumerate(tickers)}    # vol de 15% a 78%
    d = ct.diagnostico(ct.pesos_alvo(tickers, vol))
    assert d["fracao_no_piso"] > 0.5
    assert d["dispersao"] <= ct.CAP_NOME / ct.PISO_NOME + 1e-9   # o intervalo inteiro e so 2x


def test_sem_papel_nenhum_devolve_serie_vazia():
    w = ct.pesos_alvo([], {})
    assert len(w) == 0 and w.attrs["violacoes"] == []


# ─────────────────────────────────────────────────────────────
# Lotes
# ─────────────────────────────────────────────────────────────
def test_lote_de_cem_ate_trinta_reais_e_fracionario_acima():
    pesos = pd.Series({"BARATO3": 0.05, "CARO3": 0.05})
    precos = {"BARATO3": 10.0, "CARO3": 100.0}
    alvo = ct.arredondar_lotes(pesos, precos, 100_000.0).set_index("ticker")
    assert alvo.loc["BARATO3", "qtd"] % ct.LOTE == 0 and not alvo.loc["BARATO3", "fracionario"]
    assert alvo.loc["CARO3", "fracionario"]
    assert alvo.loc["CARO3", "qtd"] == round(0.05 * 100_000.0 / 100.0)


def test_erro_de_lote_e_reportado_por_nome():
    pesos = pd.Series({"AC013": 0.05})
    alvo = ct.arredondar_lotes(pesos, {"AC013": 27.0}, 100_000.0).iloc[0]
    # 5.000 / 27 = 185,2 acoes -> 200 no lote de 100
    assert alvo["qtd"] == 200
    assert abs(alvo["erro_lote_pp"] - (200 * 27.0 / 100_000.0 - 0.05) * 100.0) < 1e-12


def test_preco_ausente_nao_gera_ordem():
    alvo = ct.arredondar_lotes(pd.Series({"A3": 0.05, "B3": 0.05}), {"A3": np.nan, "B3": 0.0}, 100_000.0)
    assert len(alvo) == 0
    assert len(ct.arredondar_lotes(pd.Series(dtype=float), {}, 100_000.0)) == 0


# ─────────────────────────────────────────────────────────────
# Hedge
# ─────────────────────────────────────────────────────────────
def test_um_contrato_ate_duzentos_mil_e_dois_acima():
    assert ct.contratos_hedge(150_000.0) == 1
    assert ct.contratos_hedge(199_999.0) == 1
    assert ct.contratos_hedge(200_000.0) == 2
    assert ct.contratos_hedge(0.0) == 0 and ct.contratos_hedge(np.nan) == 0


def test_hedge_nao_se_mexe_com_beta_dentro_da_banda():
    venc = calendario.proximo_vencimento_indice("2023-01-10")
    estado = {"hedge": {"contratos": 1, "vencimento": venc, "nivel_entrada": 100_000.0}}
    c, v, motivo = ct.ajustar_hedge(estado, "2023-01-10", 150_000.0, beta60=0.30)
    assert motivo == "manter" and c == 1 and v == venc


def test_beta_fora_da_banda_dispara_ajuste():
    venc = calendario.proximo_vencimento_indice("2023-01-10")
    estado = {"hedge": {"contratos": 1, "vencimento": venc, "nivel_entrada": 100_000.0}}
    assert ct.ajustar_hedge(estado, "2023-01-10", 150_000.0, beta60=0.05)[2] == "beta"
    assert ct.ajustar_hedge(estado, "2023-01-10", 150_000.0, beta60=0.80)[2] == "beta"


def test_roll_dispara_cinco_pregoes_antes_do_vencimento():
    venc = calendario.vencimento_indice(2023, 4)
    estado = {"hedge": {"contratos": 1, "vencimento": venc, "nivel_entrada": 100_000.0}}
    gatilho = calendario.pregoes_atras(venc, ct.PREGOES_ROLL)
    antes = calendario.pregao_anterior(gatilho)
    assert ct.ajustar_hedge(estado, antes, 150_000.0, beta60=0.30)[2] == "manter"
    c, novo_venc, motivo = ct.ajustar_hedge(estado, gatilho, 150_000.0, beta60=0.30)
    assert motivo == "roll" and novo_venc > venc


def test_cruzar_duzentos_mil_troca_o_tamanho():
    venc = calendario.proximo_vencimento_indice("2023-01-10")
    estado = {"hedge": {"contratos": 1, "vencimento": venc, "nivel_entrada": 100_000.0}}
    c, _, motivo = ct.ajustar_hedge(estado, "2023-01-10", 250_000.0, beta60=0.30)
    assert motivo == "tamanho" and c == 2


def test_caixa_minimo_respeita_margem_e_fracao():
    assert ct.caixa_minimo(100_000.0, 1) == 0.25 * 100_000.0        # a fracao manda
    assert ct.caixa_minimo(20_000.0, 2) == 2 * ct.MARGEM_CONTRATO   # a margem manda
    assert ct.caixa_minimo(0.0, 1) == 0.0


# ─────────────────────────────────────────────────────────────
# Regra incremental de custo
# ─────────────────────────────────────────────────────────────
def test_a_regra_de_tres_vezes_o_custo_nunca_corta_nada():
    """O ACHADO do docstring, provado: custo = c x valor com c pequeno, entao
    `valor > 3 x custo` e `1 > 3c`, verdadeiro sempre. Quem corta e o piso absoluto."""
    for valor, adtv in ((200.0, 50e6), (200.0, 1e6), (50.0, 500e3), (1e6, 1e6)):
        custo = cst.custo_ordem(valor, adtv)["total"]
        assert valor > ct.LIMIAR_CUSTO * custo, (valor, adtv, custo)


def test_ordem_abaixo_do_piso_absoluto_nao_sai():
    estado = ct.estado_inicial(100_000.0)
    alvo = pd.Series({"AC013": 100})                                # R$200, abaixo dos R$500
    o = ct.ordens_incrementais(estado, alvo, {"AC013": 2.0}, {"AC013": 50e6}, 100_000.0)
    assert len(o) == 0
    maior = ct.ordens_incrementais(estado, pd.Series({"AC013": 400}), {"AC013": 2.0},
                                   {"AC013": 50e6}, 100_000.0)
    assert len(maior) == 1 and maior.iloc[0]["valor"] == 800.0


def test_ordem_grande_o_bastante_sai():
    estado = ct.estado_inicial(100_000.0)
    alvo = pd.Series({"AC013": 300})                                # R$6.000 a R$20,00
    o = ct.ordens_incrementais(estado, alvo, {"AC013": 20.0}, {"AC013": 50e6}, 100_000.0)
    assert len(o) == 1 and o.iloc[0]["lado"] == "C" and o.iloc[0]["motivo"] == "entrada"
    assert o.iloc[0]["qtd"] == 300 and abs(o.iloc[0]["valor"] - 6_000.0) < 1e-9


def test_ajuste_precisa_de_um_ponto_e_meio_percentual():
    estado = ct.estado_inicial(100_000.0)
    estado["posicoes"] = {"AC013": {"qtd": 300, "preco_medio": 20.0, "meses": 1}}
    # +50 acoes = R$1.000 = 1,0 p.p. do patrimonio: nao passa
    o = ct.ordens_incrementais(estado, pd.Series({"AC013": 350}), {"AC013": 20.0},
                               {"AC013": 50e6}, 100_000.0)
    assert len(o) == 0
    # +100 acoes = R$2.000 = 2,0 p.p.: passa
    o2 = ct.ordens_incrementais(estado, pd.Series({"AC013": 400}), {"AC013": 20.0},
                                {"AC013": 50e6}, 100_000.0)
    assert len(o2) == 1 and o2.iloc[0]["motivo"] == "ajuste"


def test_saida_por_portao_ignora_a_regra_de_custo():
    """Uma posicao minuscula que reprovou em qualidade tem de sair mesmo sem pagar o custo."""
    estado = ct.estado_inicial(100_000.0)
    estado["posicoes"] = {"AC013": {"qtd": 100, "preco_medio": 2.0, "meses": 1}}
    o = ct.ordens_incrementais(estado, pd.Series(dtype=float), {"AC013": 2.0},
                               {"AC013": 50e6}, 100_000.0, saidas={"AC013": "saida_gate"})
    assert len(o) == 1 and o.iloc[0]["lado"] == "V" and o.iloc[0]["motivo"] == "saida_gate"
    # a mesma posicao de R$200, saindo por rank, para no piso absoluto
    o2 = ct.ordens_incrementais(estado, pd.Series(dtype=float), {"AC013": 2.0},
                                {"AC013": 50e6}, 100_000.0, saidas={"AC013": "saida_rank"})
    assert len(o2) == 0


def test_estresse_de_custo_reduz_o_numero_de_ordens():
    estado = ct.estado_inicial(100_000.0)
    alvo = pd.Series({f"AC{i:02d}3": 60 for i in range(1, 20)})     # ordens de R$1.200
    normal = ct.ordens_incrementais(estado, alvo, {t: 20.0 for t in alvo.index},
                                    {t: 1e6 for t in alvo.index}, 100_000.0, estresse=1.0)
    caro = ct.ordens_incrementais(estado, alvo, {t: 20.0 for t in alvo.index},
                                  {t: 1e6 for t in alvo.index}, 100_000.0, estresse=4.0)
    assert len(caro) <= len(normal)


def test_ordens_tem_o_esquema_e_entrada_vazia_nao_quebra():
    estado = ct.estado_inicial(100_000.0)
    o = ct.ordens_incrementais(estado, pd.Series(dtype=float), {}, {}, 100_000.0)
    assert list(o.columns) == ct.COLUNAS_ORDEM and len(o) == 0


# ─────────────────────────────────────────────────────────────
# Orquestrador
# ─────────────────────────────────────────────────────────────
def test_carteira_alvo_monta_tudo_e_reporta_n_efetivo(sinais):
    estado = ct.estado_inicial(100_000.0, pd.Timestamp("2023-01-31"))
    precos = sinais.set_index("ticker")["preco"].to_dict()
    adtv = sinais.set_index("ticker")["adtv21"].to_dict()
    setor = sinais.set_index("ticker")["setor"].to_dict()
    r = ct.carteira_alvo(sinais, estado, precos, adtv=adtv, setor=setor,
                         patrimonio=100_000.0, data=pd.Timestamp("2023-01-31"))
    assert r["n_efetivo"] == ct.N_ALVO
    assert ct.BANDA[0] <= len(r["tickers"]) <= ct.BANDA[1]
    assert abs(r["pesos"].sum() - ct.EXPOSICAO_ALVO) < 1e-9
    assert len(r["ordens"]) > 0 and set(r["ordens"]["motivo"]) == {"entrada"}
    assert r["hedge"]["contratos"] == 1 and r["hedge"]["motivo"] == "abertura"
    assert r["caixa_minimo"] == 25_000.0


def test_universo_curto_reporta_n_efetivo_abaixo_da_banda():
    """Em 2011-2013 o universo pode nao ter 18 nomes depois dos portoes. O motor tem de
    dizer isso, e nao fingir que carregou 22."""
    curto = _sinais(n=8)
    estado = ct.estado_inicial(100_000.0)
    r = ct.carteira_alvo(curto, estado, curto.set_index("ticker")["preco"].to_dict(),
                         patrimonio=100_000.0)
    assert r["n_efetivo"] == 8 and r["n_efetivo"] < ct.BANDA[0]


def test_carteira_alvo_sem_sinais_nao_quebra():
    estado = ct.estado_inicial(100_000.0)
    r = ct.carteira_alvo(pd.DataFrame(columns=COLUNAS_MIN), estado, {}, patrimonio=100_000.0)
    assert r["n_efetivo"] == 0 and len(r["ordens"]) == 0

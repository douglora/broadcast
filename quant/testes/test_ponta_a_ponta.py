"""Fim a fim sobre o mercado sintetico: o unico teste que diz se o motor inteiro presta.

O teste que carrega informacao de verdade e o CONTROLE NULO: gerado um mercado sem premio
nenhum (so mercado e ruido), o backtest BRUTO (sem custo e sem hedge) tem de terminar com t
do alfa dentro do ruido. Se a maquina fabrica alfa a partir de ruido, todo o resto e ficcao.

Por que BRUTO e nao liquido: custo de corretagem, meio-spread e IR sobre JCP sao drenos
DETERMINISTICOS de uns 2,5% ao ano. Cobrar isso para negociar ruido produz um alfa
negativo com t grande - e o resultado CERTO, nao um defeito. Um controle nulo de duas
caudas sobre a serie liquida reprovaria o motor por estar funcionando. Entao: no bruto o
alfa tem de ser ruido; no liquido ele so pode ser MENOR que o bruto, nunca maior.

Os outros dois - recuperar um premio plantado e acusar um look-ahead plantado - validam
MECANICA, nao edge: a estrutura de fatores do gerador e o mesmo modelo que os sinais
assumem, entao encontrar o que foi plantado prova que o encanamento funciona, e so isso.
Nenhum numero deste arquivo e resultado de estrategia.

Roda com poucos papeis e poucos anos de proposito: a suite tem de continuar rapida.
"""
import numpy as np
import pandas as pd
import pytest

from quant import backtest as bt
from quant import carteira as ct
from quant import sinais as sg
from quant import universo as uni_mod
from quant.dados import cotahist, eventos, painel_fundamentos, setores
from quant.validacao import mercado_sintetico as ms

INI, FIM = "2013-01-01", "2019-06-30"
INI_BT, FIM_BT = "2015-01-01", "2019-06-30"
N_EMPRESAS = 45


def _montar(seed=7, lambda_mom=0.0, vazar=False, n=N_EMPRESAS):
    """Gera o mercado e monta universo, retornos, painel de fundamentos e sinais."""
    dados = ms.gerar(ini=INI, fim=FIM, n_empresas=n, seed=seed, lambda_mom=lambda_mom,
                     vazar=vazar, fracao_mortas=0.15)
    cot = dados["cotacoes"]
    ident = dados["identidade"]
    uni = uni_mod.universo_pit(cotahist.acoes_a_vista(cot, apenas_lote_padrao=True),
                              identidade=ident, adtv_min=800_000.0)
    ret = sg.painel_retornos(eventos.retorno_total(cot[["ticker", "data", "fec"]],
                                                   dados["eventos"], jcp_liquido=True))
    datas = sorted({pd.Timestamp(d) for d in uni["data"].unique()})
    mapa = setores.mapa_setores(identidade=ident, cadastro=dados["cadastro"])
    fin = setores.financeiras(mapa, ident)
    fund = painel_fundamentos.painel_ttm(dados["fundamentos"], datas, financeiras=fin,
                                         deslocar=True)
    painel = sg.painel(uni, ret, fundamentos=fund, identidade=ident, setores=mapa, datas=datas)
    return dados, painel, ret


@pytest.fixture(scope="module")
def nulo():
    return _montar(seed=7, lambda_mom=0.0)


# lambda_mom e o premio DIARIO por desvio-padrao da caracteristica: 0,0008 ao dia sao uns
# 20% ao ano, ja generoso. Valores da ordem de 1,0 estouram o preco em poucos meses.
LAMBDA_MOM = 0.0008


@pytest.fixture(scope="module")
def com_premio():
    return _montar(seed=7, lambda_mom=LAMBDA_MOM)


def _rodar(dados, painel, ret, estresse=1.0, com_hedge=True):
    from quant.dados import mercado
    exc = mercado.excesso_mercado(dados["fatores"])
    niv = mercado.nivel_indice(exc, dados["cdi"])
    return bt.rodar(painel, ret, dados["cdi"], exc, niv, ini=INI_BT, fim=FIM_BT,
                    capital=100_000.0, estresse=estresse, com_hedge=com_hedge)


# ─────────────────────────────────────────────────────────────
# O pipeline inteiro roda
# ─────────────────────────────────────────────────────────────
def test_o_pipeline_inteiro_produz_carteira_todo_mes(nulo):
    dados, painel, ret = nulo
    assert len(painel) > 0 and list(painel.columns) == sg.COLUNAS
    r = _rodar(dados, painel, ret)
    assert len(r["serie"]) > 200
    assert len(r["ordens"]) > 0
    assert r["n_efetivo"].mean() > 0


def test_identidade_contabil_no_mercado_sintetico(nulo):
    dados, painel, ret = nulo
    r = _rodar(dados, painel, ret)
    ok, erro = bt.verificar_contabilidade(r["serie"])
    assert ok, f"identidade contabil violada em ate R${erro:.4f}"


def test_restricoes_da_carteira_valem_todo_mes(nulo):
    dados, painel, ret = nulo
    r = _rodar(dados, painel, ret)
    s = r["serie"]
    assert (s["n_posicoes"] <= ct.BANDA[1]).all()
    assert (s["contratos"].isin([0, 1, 2])).all()
    assert (r["n_efetivo"] <= ct.N_ALVO).all()


# ─────────────────────────────────────────────────────────────
# O teste que importa: controle nulo
# ─────────────────────────────────────────────────────────────
def test_controle_nulo_nao_fabrica_alfa(nulo):
    """Sem premio plantado, o motor BRUTO nao pode produzir alfa fora do ruido.
    E o unico teste deste arquivo que carrega informacao real (ver o docstring)."""
    dados, painel, ret = nulo
    bruto = _rodar(dados, painel, ret, estresse=0.0, com_hedge=False)
    a = bt.atribuicao_nefin(bruto, dados["fatores"])
    assert np.isfinite(a["t_alfa"]), "sem regressao nao ha controle nulo"
    assert -2.5 <= a["t_alfa"] <= 2.5, f"t do alfa bruto {a['t_alfa']:.2f} fora do ruido"


def test_custo_so_pode_tirar_nunca_por(nulo):
    """No liquido o alfa so pode ser MENOR que no bruto: custo nao cria retorno."""
    dados, painel, ret = nulo
    bruto = bt.metricas(_rodar(dados, painel, ret, estresse=0.0, com_hedge=False))
    liquido = bt.metricas(_rodar(dados, painel, ret))
    assert liquido["excesso_aa"] < bruto["excesso_aa"]
    assert liquido["custo_aa"] > 0.0


def test_controle_nulo_reprova_no_veredito(nulo):
    dados, painel, ret = nulo
    r = _rodar(dados, painel, ret)
    v = bt.avaliar(bt.metricas(r), bt.atribuicao_nefin(r, dados["fatores"]), bt.concentracao(r))
    assert not v["passou"] and v["reprovados"]


# ─────────────────────────────────────────────────────────────
# Mecanica: recuperar o plantado e acusar o vazamento
# ─────────────────────────────────────────────────────────────
def test_premio_plantado_aparece_no_resultado(nulo, com_premio):
    """Valida MECANICA, nao edge: o gerador usa a mesma estrutura que os sinais assumem."""
    d0, p0, r0 = nulo
    d1, p1, r1 = com_premio
    base = bt.metricas(_rodar(d0, p0, r0))
    premio = bt.metricas(_rodar(d1, p1, r1))
    assert premio["excesso_aa"] > base["excesso_aa"]


def test_look_ahead_plantado_muda_os_portoes():
    """Se publicar o balanco no proprio dia de referencia NAO mudar nada, a camada
    point-in-time nao esta barrando coisa alguma e o backtest inteiro e suspeito."""
    honesto = _montar(seed=11, lambda_mom=LAMBDA_MOM, vazar=False, n=35)
    vazado = _montar(seed=11, lambda_mom=LAMBDA_MOM, vazar=True, n=35)
    d_h, p_h, r_h = honesto
    d_v, p_v, r_v = vazado
    # a prova direta: com vazamento o painel conhece o balanco antes
    receb_h = pd.to_datetime(d_h["fundamentos"]["dt_receb"])
    receb_v = pd.to_datetime(d_v["fundamentos"]["dt_receb"])
    refer = pd.to_datetime(d_h["fundamentos"]["dt_refer"])
    assert (receb_v == pd.to_datetime(d_v["fundamentos"]["dt_refer"])).all()
    assert (receb_h > refer).all()
    # e os sinais de fato diferem: o portao de qualidade muda de mao em algum mes
    junta = p_h.merge(p_v, on=["data", "ticker"], suffixes=("_h", "_v"))
    assert (junta["passa_qualidade_h"] != junta["passa_qualidade_v"]).any(), \
        "vazar=True nao mudou nenhum portao: a camada point-in-time nao esta ligada"


def test_custo_dobrado_piora_o_resultado_no_sintetico(com_premio):
    dados, painel, ret = com_premio
    normal = bt.metricas(_rodar(dados, painel, ret, estresse=1.0))
    caro = bt.metricas(_rodar(dados, painel, ret, estresse=2.0))
    assert caro["excesso_aa"] <= normal["excesso_aa"]
    assert caro["custo_aa"] >= normal["custo_aa"]


# ─────────────────────────────────────────────────────────────
# Sobrevivencia e reprodutibilidade
# ─────────────────────────────────────────────────────────────
def test_deslistada_aparece_antes_e_some_depois(nulo):
    dados, painel, ret = nulo
    mortas = dados["gabarito"]["papeis"]
    cot = dados["cotacoes"]
    ultimo = cot.groupby("ticker")["data"].max()
    cedo = ultimo[ultimo < pd.Timestamp(FIM).date() - pd.Timedelta(days=200)]
    assert len(cedo) > 0, "o gerador nao produziu nenhuma deslistagem"
    t = cedo.index[0]
    datas_com = set(painel[painel["ticker"] == t]["data"])
    if datas_com:
        assert max(datas_com) < pd.Timestamp(FIM)


def test_mesma_semente_da_o_mesmo_resultado():
    a = ms.gerar(ini="2015-01-01", fim="2017-12-31", n_empresas=12, seed=42)
    b = ms.gerar(ini="2015-01-01", fim="2017-12-31", n_empresas=12, seed=42)
    pd.testing.assert_frame_equal(a["cotacoes"], b["cotacoes"])
    c = ms.gerar(ini="2015-01-01", fim="2017-12-31", n_empresas=12, seed=43)
    assert not a["cotacoes"]["fec"].equals(c["cotacoes"]["fec"])


def test_resumo_do_funil_soma(nulo):
    dados, painel, ret = nulo
    r = sg.resumo(painel)
    assert len(r) > 0
    for _, linha in r.iterrows():
        soma = sum(int(linha[c]) for c in ("momento", "qualidade", "crescimento",
                                           "caro", "volatil", "aluguel"))
        assert soma + int(linha["n_elegivel"]) == int(linha["n_universo"])

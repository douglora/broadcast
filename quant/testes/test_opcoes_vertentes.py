"""
Testes das tres vertentes de opcoes (quant/opcoes/vertentes.py, manejo.py, vertentes_pesquisa.py).
Casos pequenos e deterministicos: caminho de preco sintetico, cadeia sintetica de BOVA11, livro em arquivo temporario.
Nada aqui depende da base de 2005-2026, exceto o teste do JSON de resultados (que le o arquivo ja gerado).
"""
import json
import math
import os

import numpy as np
import pandas as pd
import pytest

from quant.opcoes import carteira_simulada as CS
from quant.opcoes import custos as C
from quant.opcoes import manejo
from quant.opcoes import vertentes as V
from quant.opcoes import vertentes_pesquisa as VP

FEE = C.FEE_PREMIO
DIA = pd.Timestamp("2026-10-09")
VENC = pd.Timestamp("2026-11-19")


# ------------------------------------------------------------------------------------------------------------ caminho e saidas
def caminho(codigo, venc, linhas):
    """linhas: (dia, bid, ask, negocios). Devolve um Caminhos sem ler a base."""
    cam = manejo.Caminhos([])
    d = pd.DataFrame(linhas, columns=["dia", "bid", "ask", "neg"])
    cam.d[(codigo, pd.Timestamp(venc))] = (pd.to_datetime(d["dia"]).values.astype("datetime64[ns]"), d["bid"].values.astype(float),
                                           d["ask"].values.astype(float), d["neg"].values.astype(int))
    return cam


def test_saida_em_80pct_pega_o_primeiro_pregao_com_cotacao_e_negocios():
    cam = caminho("X", "2026-11-19", [("2026-10-12", 0.9, 1.0, 50), ("2026-10-13", 0.1, 0.19, 5), ("2026-10-14", 0.1, 0.19, 40), ("2026-10-15", 0.01, 0.02, 40)])
    credito = 1.00
    dia, custo, motivo = manejo.saida_perna_unica(cam, "X", "2026-11-19", "2026-10-09", credito, 0.20, None)
    # dia 13 tem so 5 negocios: nao observavel; dia 14 e o primeiro (0,19 <= 20% de 1,00)
    assert dia == pd.Timestamp("2026-10-14") and motivo == "alvo"
    assert custo == pytest.approx(0.19 * (1 + FEE))


def test_stop_em_multiplo_do_premio_e_primeiro_evento_vence():
    cam = caminho("X", "2026-11-19", [("2026-10-12", 2.0, 3.2, 80), ("2026-10-13", 0.1, 0.1, 80)])
    sa = manejo.saida_perna_unica(cam, "X", "2026-11-19", "2026-10-09", 1.0, 0.20, 3.0)
    assert sa[2] == "stop" and sa[0] == pd.Timestamp("2026-10-12") and sa[1] == pytest.approx(3.2 * (1 + FEE))


def test_atraso_do_stop_executa_no_pregao_seguinte_com_cotacao():
    cam = caminho("X", "2026-11-19", [("2026-10-12", 2.0, 3.2, 80), ("2026-10-13", 3.0, 5.0, 3), ("2026-10-14", 4.0, 6.0, 80)])
    sa0 = manejo.saida_perna_unica(cam, "X", "2026-11-19", "2026-10-09", 1.0, 0.20, 3.0, atraso=0)
    sa1 = manejo.saida_perna_unica(cam, "X", "2026-11-19", "2026-10-09", 1.0, 0.20, 3.0, atraso=1)
    assert sa0[0] == pd.Timestamp("2026-10-12")
    assert sa1[0] == pd.Timestamp("2026-10-13") and sa1[1] == pytest.approx(5.0 * (1 + FEE))      # 1 negocio basta para EXECUTAR; so a decisao exige 10


def test_sem_evento_segura_ate_o_vencimento():
    cam = caminho("X", "2026-11-19", [("2026-10-12", 0.8, 1.0, 80), ("2026-10-13", 0.7, 0.9, 80)])
    assert manejo.saida_perna_unica(cam, "X", "2026-11-19", "2026-10-09", 1.0, 0.20, 3.0) is None
    assert manejo.saida_perna_unica(cam, "SEM_SERIE", "2026-11-19", "2026-10-09", 1.0, 0.20, 3.0) is None


def test_trava_so_e_observada_com_as_duas_pernas_cotadas():
    cam = caminho("CURTA", "2026-11-19", [("2026-10-12", 1.0, 1.1, 50), ("2026-10-13", 0.05, 0.10, 50)])
    cam.d[("LONGA", VENC)] = (pd.to_datetime(["2026-10-13"]).values.astype("datetime64[ns]"), np.array([0.02]), np.array([0.05]), np.array([30]))
    # dia 12: perna comprada sem cotacao -> nao decide; dia 13: custo = 0,10*(1+f) - 0,02*(1-f) = ~0,08 <= 20% do credito 1,0
    dia, custo, motivo = manejo.saida_trava(cam, "CURTA", "LONGA", "2026-11-19", "2026-10-09", 1.0, 0.20, 2.0)
    assert dia == pd.Timestamp("2026-10-13") and motivo == "alvo"
    assert custo == pytest.approx(0.10 * (1 + FEE) - 0.02 * (1 - FEE))


def test_pnl_com_caixa_no_cdi(monkeypatch):
    monkeypatch.setattr(manejo, "fator_cdi", lambda d0, d1: 1.0 + 0.001 * (pd.Timestamp(d1) - pd.Timestamp(d0)).days)
    e, t = pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31")
    # segura: credito capitalizado ate T menos o pagamento
    pnl, mot = manejo.pnl_com_saida(1.0, e, t, None, 0.30, 0.01)
    assert mot == "vencimento" and pnl == pytest.approx(1.0 * 1.030 - 0.30 - 0.01)
    # sai no dia 10: credito capitalizado ate D, paga a recompra, o saldo segue no CDI ate T
    d = pd.Timestamp("2026-10-10")
    pnl2, mot2 = manejo.pnl_com_saida(1.0, e, t, (d, 0.20, "alvo"), 0.0, 0.0)
    assert mot2 == "alvo" and pnl2 == pytest.approx((1.0 * 1.009 - 0.20) * 1.021)


# ------------------------------------------------------------------------------------------------------------ pesquisa: filtros e criterios
def test_filtros_da_grade():
    df = pd.DataFrame({"perc_vi": [0.2, 0.6, 0.9, np.nan], "acima_mm200": [1.0, 0.0, 1.0, np.nan]})
    assert list(VP.filtro_mascara(df, "F0", "put")) == [True] * 4
    assert list(VP.filtro_mascara(df, "F1", "put")) == [False, True, True, False]
    assert list(VP.filtro_mascara(df, "F2", "put")) == [True, False, True, False]
    assert list(VP.filtro_mascara(df, "F2", "call")) == [False, True, False, False]


def test_criterio_de_fase_e_das_duas_metades():
    bom = {"sharpe": 0.5, "excesso_anual_pct": 2.0, "meses_com_operacao": 30, "n_ops": 40}
    assert VP.passa_fase(bom)
    assert not VP.passa_fase({**bom, "sharpe": 0.29})
    assert not VP.passa_fase({**bom, "excesso_anual_pct": -0.1})
    assert not VP.passa_fase({**bom, "meses_com_operacao": 10, "n_ops": 10})
    assert VP.passa_fase(bom, estrito_metades=[1.0, 0.5])
    assert not VP.passa_fase(bom, estrito_metades=[1.0, -0.5])
    assert not VP.passa_fase({})


def test_sequencia_de_perdas():
    assert VP._sequencia_perdas([0.01, -0.01, -0.02, 0.0, -0.01]) == 2


def test_resultados_gerados_sao_estritos_e_so_usam_descoberta_e_validacao():
    arq = VP.ARQ
    if not os.path.exists(arq):
        pytest.skip("resultados_vertentes.json ainda nao gerado")
    texto = open(arq, encoding="utf-8").read()
    r = json.loads(texto, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))        # NaN/Infinity proibidos
    assert len(r["v2"]) == VP.N_V2 and len(r["v3"]) == VP.N_V3
    for x in r["v2"] + r["v3"]:
        assert set(x["fases"]).issubset({"descoberta", "validacao"}), x["config"]               # a prova 2024-2026 nao entra
        assert isinstance(x["passou"], bool)
    # reprovada nao pode ter sido promovida: nenhuma V3 de credito passa sem as duas metades positivas
    for x in r["v3"]:
        if "gatilho" not in x and x["passou"]:
            m = x["fases"]["validacao"]
            assert m["excesso_anual_metade_1_pct"] > 0 and m["excesso_anual_metade_2_pct"] > 0


# ------------------------------------------------------------------------------------------------------------ probabilidades e regime
def test_probabilidade_implicita_e_empirica():
    p1 = V.p_acima_implicita(100.0, 95.0, 21, 0.1, 0.25)
    p2 = V.p_acima_implicita(100.0, 105.0, 21, 0.1, 0.25)
    assert p1 > p2 and 0 < p2 < 1 and p1 < 1                                                       # strike menor: mais chance de ficar acima
    assert math.isnan(V.p_acima_implicita(100.0, 95.0, 0, 0.1, 0.25))
    ret = np.array([-0.10, -0.02, 0.0, 0.03, 0.08])
    assert V.p_acima_empirica(ret, 100.0, 99.0) == pytest.approx(0.6)
    assert math.isnan(V.p_acima_empirica(None, 100.0, 99.0))


def serie(n=400, passo=0.0005, final_queda=False):
    idx = pd.bdate_range(end=DIA, periods=n)
    v = 100.0 * np.cumprod(np.full(n, 1.0 + passo))
    if final_queda:
        v[-60:] = v[-60] * np.cumprod(np.full(60, 0.995))
    return pd.Series(v, index=idx)


def test_regime_alta_baixa_neutra():
    assert V.regime(serie())["direcao"] == "alta"
    assert V.regime(serie(passo=-0.0005))["direcao"] == "baixa"
    assert V.regime(serie(final_queda=True))["direcao"] in ("neutra", "baixa")
    assert V.regime(serie(n=50))["direcao"] == "neutra"                                           # historico curto


def test_gatilho_de_alta_rompimento():
    s = serie()
    assert V.gatilho_alta(s) == "T1"                                                              # serie sempre sobe: rompe o maximo de 55 todo dia
    assert V.gatilho_alta(serie(passo=-0.0005)) is None


# ------------------------------------------------------------------------------------------------------------ cadeia sintetica de BOVA11
def linha(codigo, tipo, K, delta, bid, ask, neg=200, iv=0.25, S=200.0, venc=VENC, ativo="BOVA11"):
    return {"dia": DIA, "codigo": codigo, "ativo": ativo, "tipo": tipo, "exercicio": K, "vencimento": venc, "fech": (bid + ask) / 2, "oferta_compra": bid, "oferta_venda": ask,
            "negocios": neg, "fatcot": 1, "semanal": False, "S": S, "r": 0.12, "du": 28, "boa": True, "spread": (ask - bid) / ((ask + bid) / 2), "premio_ref": (ask + bid) / 2,
            "iv": iv, "delta": delta, "mensal": True, "quantidade": 1000, "volume": 1e6, "dc": 41, "r_aa": 0.13}


def chain():
    o = pd.DataFrame([
        linha("BOVAW190", "P", 190.0, -0.20, 2.00, 2.10), linha("BOVAW195", "P", 195.0, -0.30, 3.30, 3.40), linha("BOVAW184", "P", 184.0, -0.12, 1.00, 1.10),
        linha("BOVAW181", "P", 181.0, -0.09, 0.70, 0.80),
        linha("BOVAK210", "C", 210.0, 0.35, 4.20, 4.35), linha("BOVAK215", "C", 215.0, 0.27, 2.40, 2.50), linha("BOVAK220", "C", 220.0, 0.17, 1.20, 1.30),
        linha("BOVAK225", "C", 225.0, 0.10, 0.60, 0.70), linha("BOVAK205", "C", 205.0, 0.50, 6.00, 6.20),
        linha("BOVAW200", "P", 200.0, -0.45, 5.00, 5.10, neg=5),                                   # sem liquidez: nao entra
    ])
    return o


def M_sintetico():
    o = chain()
    pa = pd.DataFrame([{"ativo": "BOVA11", "preco": 200.0, "vol_implicita_30d": 0.25, "vol_realizada_252d": 0.19, "percentil_vol_implicita_1a": 30.0, "percentil_inclinacao": 40.0,
                        "proximo_resultado": None, "spread_vr252_menos_vi": -0.06, "series_liquidas": 9, "negocios_no_dia": 5000}])
    op = o[["dia", "codigo", "vencimento", "oferta_compra", "oferta_venda", "fech", "exercicio", "negocios", "ativo"]].copy()
    sp = pd.DataFrame([{"ativo": "BOVA11", "dia": DIA, "fatcot": 1, "fech": 200.0}])
    return {"dia": DIA, "o": o, "op": op, "sp": sp, "por_ativo": pa, "liq_ativos": ["BOVA11"], "baratos_vr252": ["BOVA11"], "vencs": [VENC], "tr": {"BOVA11": serie()}}


@pytest.fixture
def mundo(monkeypatch):
    monkeypatch.setattr(V, "_venc_alvo", lambda M, dia, du_min=15: VENC)
    monkeypatch.setattr(V, "_du", lambda dia, venc: 28)
    monkeypatch.setattr(V, "retornos_empiricos", lambda s, du, anos=15: np.array([-0.12, -0.05, -0.01, 0.0, 0.01, 0.02, 0.04, 0.06]))
    monkeypatch.setattr(manejo, "fator_cdi", lambda d0, d1: 1.0 + 0.0004 * (pd.Timestamp(d1) - pd.Timestamp(d0)).days)
    monkeypatch.setattr(CS, "livro_estourado", lambda: False)
    return M_sintetico()


def test_tabela_de_travas_credito_risco_e_retorno(mundo):
    M = mundo
    rg = V.regime(M["tr"]["BOVA11"])
    t = V.tabela_travas(M, DIA, rg)
    assert t and all(r["tipo"] in ("put_spread", "call_spread") for r in t)
    ps = [r for r in t if r["tipo"] == "put_spread" and r["strike_vendido"] == 190.0 and r["strike_comprado"] == 184.0]
    assert len(ps) == 1
    x = ps[0]
    credito = 2.00 * (1 - FEE) - 1.10 * (1 + FEE)
    assert x["credito"] == pytest.approx(credito, abs=0.005) and x["largura"] == 6.0
    assert x["risco_maximo"] == pytest.approx(6.0 - credito, abs=0.005)
    assert x["retorno_sobre_risco_pct"] == pytest.approx(credito / (6.0 - credito) * 100, abs=0.1)
    assert x["credito_do_lote_rs"] == pytest.approx(credito * 100, abs=0.5)
    # a perna sem liquidez (5 negocios) nunca aparece
    assert all("BOVAW200" not in (r["perna_vendida"], r["perna_comprada"]) for r in t)
    # prob. de lucro maximo da trava de alta (fica acima do strike vendido) < prob. de nao perder o risco todo
    assert x["prob_ganho_maximo_preco_pct"] < 100 - x["prob_perda_maxima_preco_pct"]
    assert x["alinhada_com_a_tendencia"] is True                                                  # tendencia de alta -> put spread
    cs = [r for r in t if r["tipo"] == "call_spread"]
    assert cs and all(r["alinhada_com_a_tendencia"] is False for r in cs)
    # tela: no maximo 3 por (vencimento, tipo)
    assert len(V.melhores_travas(t)) <= 6


def test_ranking_v2_so_tem_put_elegivel_e_call_e_sempre_coberta(mundo):
    r = V.ranking_v2(mundo, DIA)
    assert r
    for x in r:
        if x["tipo"].startswith("call"):
            assert "coberta" in x["tipo"] and x["elegivel_livro"] is False                         # nunca call descoberta, e call coberta nao abre no livro
        else:
            assert x["tipo"] == "put coberta por caixa" and abs(x["delta"]) <= 0.30 + 1e-9
    puts = [x for x in r if x["tipo"].startswith("put")]
    assert puts[0]["strike"] == 190.0 and puts[0]["garantia_do_lote_rs"] == pytest.approx(19000.0)
    assert puts[0]["recompra_em_80pct"] == pytest.approx(puts[0]["premio"] * (1 - FEE) * 0.20, abs=0.01)


def test_ranking_v1_pontos_e_teto(mundo):
    r = V.ranking_v1(mundo, DIA)
    assert len(r) == 1 and r[0]["ativo"] == "BOVA11"
    # barata (+2), percentil 30 < 40 (+1), gatilho T1 (+2), acima da MM200 (+1) = 6
    assert r[0]["pontos"] == 6 and r[0]["gatilho_tecnico"] == "T1"
    assert r[0]["premio"] == 6.2 and r[0]["cabe_no_teto_por_estrutura"] is False                   # 100 x 6,2 > R$ 500
    assert V.aviso_ranking_v1_para_livro(r) == []


# ------------------------------------------------------------------------------------------------------------ livro das vertentes V2 e V3
def test_livro_abre_marca_gere_e_nao_repete(mundo, tmp_path):
    M = mundo
    arq = str(tmp_path / "v.json")
    rg = V.regime(M["tr"]["BOVA11"])
    c2, t3 = V.ranking_v2(M, DIA), V.tabela_travas(M, DIA, rg)
    est = V.atualizar_livros(M, c2, t3, rg, DIA, caminho=arq)
    ab = [p for p in est["posicoes"] if p["estado"] == "aberta"]
    v2 = [p for p in ab if p["vertente"] == "dividendo_sintetico"]
    v3 = [p for p in ab if p["vertente"] == "travas_bova"]
    assert len(v2) == 1 and v2[0]["ativo"] == "BOVA11" and v2[0]["stop_multiplo"] == V.STOP_UNICA
    assert v2[0]["pernas"][0]["lado"] == "venda" and v2[0]["pernas"][0]["tipo"] == "put"
    assert v2[0]["garantia_rs"] == pytest.approx(v2[0]["pernas"][0]["exercicio"] * 100)
    assert len(v3) == 1 and v3[0]["risco_rs"] <= V.RISCO_POR_TRAVA
    # credito: custo negativo; valor_hoje igual ao custo no dia da abertura
    assert v2[0]["custo"] < 0 and v3[0]["custo"] < 0 and v2[0]["valor_hoje"] == v2[0]["custo"]
    # idempotente: mesma data nao abre nem marca de novo
    n = len(est["posicoes"])
    est2 = V.atualizar_livros(M, c2, t3, rg, DIA, caminho=arq)
    assert len(est2["posicoes"]) == n
    # nunca call descoberta: toda call vendida tem uma call comprada de strike maior na mesma posicao
    for p in est["posicoes"]:
        for perna in p["pernas"]:
            if perna["lado"] == "venda" and perna["tipo"] == "call":
                assert any(q["lado"] == "compra" and q["tipo"] == "call" and q["exercicio"] > perna["exercicio"] for q in p["pernas"])


def avancar(M, dia_novo, cotacoes, S=200.0):
    """Cadeia do dia seguinte: novas ofertas por codigo (bid, ask, negocios)."""
    M2 = dict(M)
    o = M["o"].copy()
    o["dia"] = dia_novo
    for cod, (bid, ask, neg) in cotacoes.items():
        m = o["codigo"] == cod
        o.loc[m, ["oferta_compra", "oferta_venda", "negocios", "fech"]] = [bid, ask, neg, (bid + ask) / 2]
    M2["o"] = o
    M2["op"] = o[["dia", "codigo", "vencimento", "oferta_compra", "oferta_venda", "fech", "exercicio", "negocios", "ativo"]].copy()
    M2["sp"] = pd.DataFrame([{"ativo": "BOVA11", "dia": dia_novo, "fatcot": 1, "fech": S}])
    M2["dia"] = dia_novo
    return M2


def test_saida_em_80pct_no_livro(mundo, tmp_path):
    M = mundo
    arq = str(tmp_path / "v.json")
    rg = V.regime(M["tr"]["BOVA11"])
    est = V.atualizar_livros(M, V.ranking_v2(M, DIA), [], rg, DIA, caminho=arq)
    p2 = [p for p in est["posicoes"] if p["vertente"] == "dividendo_sintetico"][0]
    cod = p2["pernas"][0]["codigo"]
    credito_unit = -p2["custo"] / p2["qtd"]
    # a put vendida passa a valer 15% do recebido, com 50 negocios -> fecha por alvo
    d1 = pd.Timestamp("2026-10-13")
    M1 = avancar(M, d1, {cod: (0.10, 0.15 * credito_unit / (1 + FEE), 50)})
    est1 = V.atualizar_livros(M1, [], [], rg, d1, caminho=arq)
    p = [q for q in est1["posicoes"] if q["id"] == p2["id"]][0]
    assert p["estado"] == "encerrada" and p["motivo_fechamento"].startswith("alvo") and p["fechada_em"] == "2026-10-13"
    assert 0 < p["resultado_rs"] <= credito_unit * p["qtd"]
    assert p["resultado_rs"] == pytest.approx(credito_unit * p["qtd"] - 0.15 * credito_unit * p["qtd"], abs=0.02)


def test_stop_da_trava_com_as_duas_pernas_cotadas(mundo, tmp_path):
    M = mundo
    arq = str(tmp_path / "v.json")
    rg = V.regime(M["tr"]["BOVA11"])
    est = V.atualizar_livros(M, [], V.tabela_travas(M, DIA, rg), rg, DIA, caminho=arq)
    t3 = [q for q in est["posicoes"] if q["vertente"] == "travas_bova"][0]
    curta = [x for x in t3["pernas"] if x["lado"] == "venda"][0]["codigo"]
    longa = [x for x in t3["pernas"] if x["lado"] == "compra"][0]["codigo"]
    cred_t = -t3["custo"] / t3["qtd"]
    # so a perna vendida cotada, comprada sem negocio e sem oferta: nao decide
    d1 = pd.Timestamp("2026-10-13")
    M1 = avancar(M, d1, {curta: (3.0 * cred_t + 0.4, 3.0 * cred_t + 0.5, 60)})
    M1["o"].loc[M1["o"]["codigo"] == longa, "oferta_compra"] = np.nan
    M1["op"].loc[M1["op"]["codigo"] == longa, "oferta_compra"] = np.nan
    est1 = V.atualizar_livros(M1, [], [], rg, d1, caminho=arq)
    assert [q for q in est1["posicoes"] if q["id"] == t3["id"]][0]["estado"] == "aberta"
    # as duas cotadas e o custo de fechar >= 2x o credito -> stop
    d2 = pd.Timestamp("2026-10-14")
    M2 = avancar(M, d2, {curta: (3.0 * cred_t + 0.4, 3.0 * cred_t + 0.5, 60), longa: (0.2, 0.3, 40)})
    est2 = V.atualizar_livros(M2, [], [], rg, d2, caminho=arq)
    t = [q for q in est2["posicoes"] if q["id"] == t3["id"]][0]
    assert t["estado"] == "encerrada" and t["motivo_fechamento"].startswith("stop") and t["resultado_rs"] < 0


def test_sem_cotacao_ou_com_poucos_negocios_nao_decide(mundo, tmp_path):
    M = mundo
    arq = str(tmp_path / "v.json")
    rg = V.regime(M["tr"]["BOVA11"])
    est = V.atualizar_livros(M, V.ranking_v2(M, DIA), [], rg, DIA, caminho=arq)
    p2 = [p for p in est["posicoes"] if p["vertente"] == "dividendo_sintetico"][0]
    cod = p2["pernas"][0]["codigo"]
    d1 = pd.Timestamp("2026-10-13")
    M1 = avancar(M, d1, {cod: (0.01, 0.02, 4)})                                                   # valendo quase nada, mas com 4 negocios: nao observavel
    est1 = V.atualizar_livros(M1, [], [], rg, d1, caminho=arq)
    assert [q for q in est1["posicoes"] if q["id"] == p2["id"]][0]["estado"] == "aberta"


def test_vencimento_liquida_pelo_valor_intrinseco_com_taxa(mundo, tmp_path):
    M = mundo
    arq = str(tmp_path / "v.json")
    rg = V.regime(M["tr"]["BOVA11"])
    est = V.atualizar_livros(M, V.ranking_v2(M, DIA), [], rg, DIA, caminho=arq)
    p2 = [p for p in est["posicoes"] if p["vertente"] == "dividendo_sintetico"][0]
    K = p2["pernas"][0]["exercicio"]
    M1 = avancar(M, VENC, {}, S=K - 10.0)                                                         # BOVA11 fecha 10 abaixo do strike: put exercida
    est1 = V.atualizar_livros(M1, [], [], rg, VENC, caminho=arq)
    p = [q for q in est1["posicoes"] if q["id"] == p2["id"]][0]
    assert p["estado"] == "encerrada" and p["motivo_fechamento"].startswith("vencimento") and "exercida" in p["motivo_fechamento"]
    credito = -p2["custo"]
    taxa = C.FEE_EXERC * (K + (K - 10.0)) * 100
    assert p["resultado_rs"] == pytest.approx(credito - 10.0 * 100 - taxa, abs=0.02)


def test_livro_estourado_bloqueia_aberturas(mundo, tmp_path, monkeypatch):
    M = mundo
    monkeypatch.setattr(CS, "livro_estourado", lambda: True)
    rg = V.regime(M["tr"]["BOVA11"])
    est = V.atualizar_livros(M, V.ranking_v2(M, DIA), V.tabela_travas(M, DIA, rg), rg, DIA, caminho=str(tmp_path / "v.json"))
    assert est["posicoes"] == []


def test_limite_de_garantia_e_de_risco(mundo, tmp_path, monkeypatch):
    M = mundo
    # garantia maxima = 2/3 do caixa da classe (R$ 100 mil sem o livro por classes nos testes): um lote de BOVA11 (R$ 19 mil) cabe; o segundo ativo igual nao repete serie
    rg = V.regime(M["tr"]["BOVA11"])
    est = V.atualizar_livros(M, V.ranking_v2(M, DIA), [], rg, DIA, caminho=str(tmp_path / "v.json"))
    assert sum(p["garantia_rs"] for p in est["posicoes"] if p["estado"] == "aberta") <= V.orcamentos()[0] * V.FRACAO_GARANTIA_V2 + 1e-6
    assert sum(V.FRACAO_LIMITE.values()) == pytest.approx(1.0)


# ------------------------------------------------------------------------------------------------------------ bloco da tela
def test_bloco_vertentes_json_estrito_e_contrato(mundo, tmp_path):
    M = mundo
    bloco, r1, est = V.montar_bloco(M, DIA, [], gravar=True, caminho=str(tmp_path / "v.json"))
    assert [b["nome"] for b in bloco] == ["especulativa", "dividendo_sintetico", "travas_bova"]
    for b in bloco:
        for k in ("nome", "titulo", "regra", "evidencia", "ranking_hoje", "posicoes", "placar", "limites"):
            assert k in b, (b["nome"], k)
        assert isinstance(b["regra"], list) and all(isinstance(x, str) for x in b["regra"])
        assert b["evidencia"]["etiqueta"] in ("aprovada", "medindo", "reprovada no histórico: só medida")
        assert b["evidencia"]["etiqueta"] != "aprovada"                                            # sem prova virgem, nada pode estar aprovado
        json.dumps(b, ensure_ascii=False, allow_nan=False, default=str)
        assert all("pernas_obj" not in r and "_c" not in r for r in b["ranking_hoje"])
    assert bloco[2]["direcao_hoje"]["direcao"] == "alta"
    # texto de tela com acento normal
    assert any("é" in t or "ã" in t or "ç" in t for t in bloco[1]["regra"])


def test_placar_conta_aberto_realizado_e_motivos():
    pos = [{"vertente": "travas_bova", "estado": "encerrada", "resultado_rs": 50.0, "risco_rs": 400.0, "motivo_fechamento": "alvo: 80% do prêmio capturado", "rendimento_caixa_rs": 3.0},
           {"vertente": "travas_bova", "estado": "encerrada", "resultado_rs": -300.0, "risco_rs": 400.0, "motivo_fechamento": "stop: custo de fechar chegou a 2 vezes o prêmio", "rendimento_caixa_rs": 2.0},
           {"vertente": "travas_bova", "estado": "aberta", "resultado_rs": 10.0, "risco_rs": 450.0, "rendimento_caixa_rs": 1.0},
           {"vertente": "dividendo_sintetico", "estado": "aberta", "resultado_rs": 99.0, "risco_rs": 1.0}]
    p = V.placar(pos, "travas_bova", DIA, 900.0, "2026-10-01")
    assert p["n_abertas"] == 1 and p["n_encerradas"] == 2 and p["resultado_realizado_rs"] == -250.0 and p["resultado_aberto_rs"] == 10.0
    assert p["acerto_pct"] == 50.0 and p["pior_posicao_rs"] == -300.0 and p["fechadas_por"] == {"alvo": 1, "stop": 1}
    assert p["risco_em_aberto_rs"] == 450.0 and p["uso_do_limite_pct"] == 50.0 


# ------------------------------------------------------------------------------------------------------------ conferencia com o motor original (precisa da base)
def test_manejo_m0_reproduz_o_motor_original():
    from quant.opcoes import assimetrias_pesquisa as A
    from quant.opcoes import motor
    from quant.opcoes.pesquisa import CESTA
    if not os.path.exists(os.path.join(A.DIR_DADOS, "cadeia_preparada.parquet")):
        pytest.skip("base de opcoes ausente")
    cad, cic, pv = A.carregar_base()
    cad = cad[(cad["E"] >= "2019-01-01") & (cad["E"] <= "2019-12-31")]
    sel = VP.selecionar_unica(cad, CESTA, "P", 0.20)
    ref = motor.venda_put(cad, CESTA, 0.20).sort_values(["grupo", "T"]).reset_index(drop=True)
    cam = manejo.Caminhos([])
    mio = VP.simular_unica(sel, cam, "M0", "put").sort_values(["grupo", "T"]).reset_index(drop=True)
    assert len(ref) == len(mio) > 0
    assert np.allclose(ref["pnl_acao"].values, mio["pnl"].values, atol=1e-9)
    assert np.allclose(ref["ex"].values, mio["ex"].values, atol=1e-12)


# ------------------------------------------------------------------------------------------------------------ livro da vertente especulativa
def candidato_v1(ativo="XXXX3", ask=2.0, pontos=4):
    r = pd.Series({"codigo": f"{ativo[:4]}K30", "tipo": "C", "exercicio": 30.0, "vencimento": VENC, "oferta_compra": ask - 0.1, "oferta_venda": ask, "ativo": ativo})
    return {"ativo": ativo, "vencimento": "2026-11-19", "strike": 30.0, "pontos": pontos, "porque": ["gatilho"], "pernas_obj": r, "cabe_no_teto_por_estrutura": True}


def test_v1_abre_uma_call_por_dia_com_perda_maxima_do_premio(monkeypatch):
    est = CS.estado_vazio(DIA)
    novas = CS.abrir_v1_calls(est, [candidato_v1("AAAA3"), candidato_v1("BBBB3")], DIA)
    assert len(novas) == 1                                                                         # uma por dia
    p = novas[0]
    assert p["vertente"] == "especulativa" and p["familia"] == "v1_call_barata" and p["pontos_na_abertura"] == 4
    assert p["pernas"][0]["lado"] == "compra" and p["pernas"][0]["tipo"] == "call"
    assert p["qtd"] == 200 and p["risco_rs"] == pytest.approx(200 * 2.0 * (1 + FEE))              # R$ 500 / (2,0 x 100) = 2 lotes; risco = o premio pago
    assert p["risco_rs"] <= CS.RISCO_POR_ESTRUTURA
    est["posicoes"] += novas
    assert CS.ja_v1_hoje(est, DIA)
    # nao repete ativo + vencimento; respeita o maximo de abertas da regra
    assert CS.abrir_v1_calls(est, [candidato_v1("AAAA3")], DIA + pd.Timedelta(days=1)) == []
    est["posicoes"] += CS.abrir_v1_calls(est, [candidato_v1("BBBB3")], DIA + pd.Timedelta(days=1))
    assert CS.abrir_v1_calls(est, [candidato_v1("CCCC3")], DIA + pd.Timedelta(days=2), max_abertas_v1=2) == []


def test_v1_respeita_o_teto_da_fatia(monkeypatch):
    monkeypatch.setattr(CS, "limite_risco_v1", lambda: 300.0)
    est = CS.estado_vazio(DIA)
    # premio 2,0 -> 200 opcoes (R$ 400) por causa do teto por estrutura de R$ 500: estoura a fatia de R$ 300, nao abre
    assert CS.abrir_v1_calls(est, [candidato_v1(ask=2.0)], DIA) == []
    # premio 2,5 -> 100 opcoes (R$ 250): cabe
    novas = CS.abrir_v1_calls(est, [candidato_v1(ask=2.5)], DIA)
    assert len(novas) == 1 and novas[0]["qtd"] == 100 and novas[0]["risco_rs"] <= 300.0


def test_guarda_contra_call_descoberta():
    coberta = {"id": "a", "pernas": [{"lado": "venda", "tipo": "call", "exercicio": 215.0, "qtd": 100}, {"lado": "compra", "tipo": "call", "exercicio": 220.0, "qtd": 100}]}
    V.garantir_sem_call_descoberta([coberta])
    nua = {"id": "b", "pernas": [{"lado": "venda", "tipo": "call", "exercicio": 215.0, "qtd": 100}]}
    with pytest.raises(ValueError):
        V.garantir_sem_call_descoberta([nua])
    invertida = {"id": "c", "pernas": [{"lado": "venda", "tipo": "call", "exercicio": 215.0, "qtd": 100}, {"lado": "compra", "tipo": "call", "exercicio": 210.0, "qtd": 100}]}
    with pytest.raises(ValueError):
        V.garantir_sem_call_descoberta([invertida])
    V.garantir_sem_call_descoberta([{"id": "d", "pernas": [{"lado": "venda", "tipo": "put", "exercicio": 190.0, "qtd": 100}]}])     # put vendida coberta por caixa e outro assunto


def test_sem_pesquisa_o_bloco_ainda_sai(mundo, tmp_path, monkeypatch):
    monkeypatch.setattr(V, "pesquisa", lambda: {})
    bloco, _, _ = V.montar_bloco(mundo, DIA, [], gravar=False, caminho=str(tmp_path / "v.json"))
    assert all(b["limites"].get("texto") for b in bloco)
    json.dumps(bloco, ensure_ascii=False, allow_nan=False, default=str)

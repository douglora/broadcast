"""
Testes do ranking de assimetrias, do filtro de liquidez, da varredura de arbitragem e da carteira simulada (quant/opcoes/).
Casos pequenos e deterministicos; nenhum depende da base de 2005-2026 (o calendario e o CDI sao trocados por versoes fixas).
"""
import json
import math

import numpy as np
import pandas as pd
import pytest

from quant.opcoes import arbitragens as arb
from quant.opcoes import assimetrias as A
from quant.opcoes import carteira_simulada as CS
from quant.opcoes import custos as C
from quant.opcoes import dados

FEE = C.FEE_PREMIO


def perna(codigo, tipo, K, delta, bid, ask, neg=200, iv=0.30, venc="2026-11-19"):
    spread = (ask - bid) / ((ask + bid) / 2)
    return {"codigo": codigo, "tipo": tipo, "exercicio": K, "delta": delta, "oferta_compra": bid, "oferta_venda": ask, "negocios": neg, "iv": iv,
            "vencimento": pd.Timestamp(venc), "premio_ref": (ask + bid) / 2, "spread": spread, "ativo": "XXXX3"}


def cadeia_pequena():
    return pd.DataFrame([
        perna("XXXXK100", "C", 100.0, 0.50, 3.90, 4.00), perna("XXXXK105", "C", 105.0, 0.30, 1.90, 2.00), perna("XXXXK110", "C", 110.0, 0.15, 0.70, 0.80),
        perna("XXXXW100", "P", 100.0, -0.50, 3.40, 3.50), perna("XXXXW095", "P", 95.0, -0.30, 1.40, 1.50), perna("XXXXW090", "P", 90.0, -0.15, 0.40, 0.50),
    ])


# -------------------------------------------------------------------------------------------------------------- liquidez
def test_filtro_de_liquidez_corta_negocios_e_spread():
    o = pd.DataFrame({"negocios": [30, 29, 500, 500], "boa": [True, True, False, True], "spread": [0.10, 0.10, 0.10, 0.31],
                      "vencimento": pd.Timestamp("2026-11-19")})
    ok = A.pernas_liquidas(o)
    assert list(ok.index) == [0]                      # 29 negocios, oferta ruim e spread de 31% saem
    assert A.pernas_liquidas(o, [pd.Timestamp("2026-12-18")]).empty


def test_liquidez_da_estrutura_pelo_pior_leg():
    boa = pd.Series({"negocios": 300, "spread": 0.10})
    media = pd.Series({"negocios": 40, "spread": 0.25})
    assert A.liquidez_de([boa, boa]) == "boa"
    assert A.liquidez_de([boa, media]) == "media"


# -------------------------------------------------------------------------------------------------------------- estruturas e valor esperado
def test_estruturas_e_custos_executaveis():
    est = {e["estrutura"]: e for e in A.estruturas_do_ativo_venc(cadeia_pequena(), 100.0)}
    # compra na oferta de venda + emolumento
    assert est["call_no_dinheiro"]["custo"] == pytest.approx(4.00 * (1 + FEE))
    assert est["straddle"]["custo"] == pytest.approx((4.00 + 3.50) * (1 + FEE))
    # trava de alta: compra a call de delta 0,50 na oferta de venda, vende a de delta 0,30 na oferta de compra
    assert est["trava_alta_calls"]["custo"] == pytest.approx(4.00 * (1 + FEE) - 1.90 * (1 - FEE))
    assert est["trava_alta_calls"]["ganho_maximo"] == pytest.approx(5.0 - est["trava_alta_calls"]["custo"])
    assert est["trava_baixa_puts"]["custo"] == pytest.approx(3.50 * (1 + FEE) - 1.40 * (1 - FEE))
    assert est["put_no_dinheiro"]["equilibrio"] == pytest.approx(100.0 - est["put_no_dinheiro"]["custo"])
    assert est["straddle"]["equilibrio_inf"] == pytest.approx(100.0 - est["straddle"]["custo"])
    assert est["call_fora_10"]["perda_maxima"] == pytest.approx(0.80 * (1 + FEE))


def test_valor_esperado_de_caso_conhecido():
    # call no dinheiro, custo 3, retornos historicos -10%, 0, +10%, +20%, juro zero: pagamentos 0, 0, 10, 20 (menos emolumento)
    ret = np.array([-0.10, 0.0, 0.10, 0.20])
    av = A.avaliar_estrutura([("C", "compra", 100.0)], 3.0, 100.0, ret, 0.30, 0.30, 0.30, 21, 0.0)
    assert av["ev_hist"] == pytest.approx(7.5 * (1 - FEE) - 3.0)
    assert av["vant_hist"] == pytest.approx((7.5 * (1 - FEE) - 3.0) / 3.0 * 100)
    assert av["prob_hist"] == pytest.approx(50.0)
    assert av["reescala"] == pytest.approx(1.0)
    # determinismo
    assert A.avaliar_estrutura([("C", "compra", 100.0)], 3.0, 100.0, ret, 0.30, 0.30, 0.30, 21, 0.0) == av


def test_probabilidade_implicita_de_lucro_da_call_perto_de_um_terco():
    # call no dinheiro, custo = premio justo de Black-Scholes: chance de pagar mais que o custo ~33% (assimetria da lognormal)
    from quant.opcoes import bs
    t = 21 / 252
    custo = bs.preco(100, 100, t, 0.0, 0.30, False)
    av = A.avaliar_estrutura([("C", "compra", 100.0)], custo, 100.0, np.array([0.0]), 0.30, 0.30, 0.30, 21, 0.0)
    assert 28 < av["prob_impl"] < 40


def test_percentil_do_ano():
    h = pd.Series(np.linspace(0.20, 0.40, 200))
    assert A.percentil_hoje(h, 0.40) == pytest.approx(100.0, abs=0.6)
    assert A.percentil_hoje(h, 0.20) < 2.0
    assert A.percentil_hoje(h.iloc[:50], 0.3) is None            # historico curto demais


def test_ranking_ordena_por_vantagem_prudente_um_por_ativo_e_estrutura(monkeypatch):
    monkeypatch.setattr(A, "veredito_familia", lambda *a, **k: {"estado": "medindo", "texto": "x"})
    pa = pd.DataFrame([{"ativo": "XXXX3", "leitura_vol": "barata", "percentil_vol_implicita_1a": 10.0}])
    linhas = []
    for venc, vant in (("2026-11-19", 5.0), ("2026-12-18", 9.0)):
        for est, v in (("call_no_dinheiro", vant), ("straddle", vant - 20)):
            e = {"estrutura": est, "familia": "capital_protegido", "rotulo": est}
            av = {"ev_hist": v, "ev_reesc": v, "vant_hist": v, "vant_reesc": v, "prob_hist": 40.0, "prob_impl": 35.0, "reescala": 1.0}
            p = pd.Series(perna("XXXXK100", "C", 100.0, 0.5, 3.9, 4.0, venc=venc))
            linhas.append({"ativo": "XXXX3", "estrutura": est, "familia": "capital_protegido", "rotulo": est, "vencimento": venc, "du": 20, "pernas_obj": [(p, "compra")],
                           "custo": 4.0, "perda_maxima": 4.0, "ganho_maximo": None, "equilibrio": 104.0, "equilibrio_inf": None, "av": av, "vantagem": v, "liquidez": "boa",
                           "ganho_sobre_perda": 1.5, "S0": 100.0, "barato_vr252": True})
    M = {"ranking_bruto": pd.DataFrame(linhas), "por_ativo": pa}
    r = A.montar_ranking(M, {}, {})
    assert [x["posicao"] for x in r] == [1, 2]                                     # um por (ativo, estrutura)
    assert r[0]["estrutura"] == "call_no_dinheiro" and r[0]["vencimento"] == "2026-12-18" and r[0]["vantagem_pct"] == 9.0
    assert r[1]["estrutura"] == "straddle" and r[1]["vencimento"] == "2026-12-18"
    for chave in ("titulo", "familia", "pernas", "custo", "ganho_maximo", "perda_maxima", "ponto_de_equilibrio", "prob_lucro_historica_pct", "prob_lucro_implicita_pct",
                  "valor_esperado_rs", "vantagem_pct", "ganho_sobre_perda", "liquidez", "historico_da_familia", "porque"):
        assert chave in r[0]


# -------------------------------------------------------------------------------------------------------------- arbitragem
def test_reversao_detectada_e_conversao_nao(monkeypatch):
    dias = pd.bdate_range("2026-10-01", "2026-12-31")
    monkeypatch.setattr(dados, "cdi_diario", lambda: pd.Series(0.0005, index=dias))
    dia, venc = pd.Timestamp("2026-10-09"), pd.Timestamp("2026-11-09")
    base = {"dia": dia, "vencimento": venc, "ativo": "XXXX3", "exercicio": 10.0, "semanal": False}
    op = pd.DataFrame([
        {**base, "codigo": "XXXXK10", "tipo": "C", "oferta_compra": 0.50, "oferta_venda": 0.55, "fech": 0.52, "negocios": 30},
        {**base, "codigo": "XXXXW10", "tipo": "P", "oferta_compra": 0.60, "oferta_venda": 0.65, "fech": 0.62, "negocios": 30}])
    sp = pd.DataFrame([{"ativo": "XXXX3", "dia": dia, "oferta_compra": 9.99, "oferta_venda": 10.00}])
    r = arb.varrer(op, sp, dias_ext=pd.DatetimeIndex(dias))
    assert set(r["tipo"]) == {"reversao"}
    t = (len(dias[(dias > dia) & (dias <= venc)])) / 252
    disc = math.exp(-math.log1p((1.0005 ** 252) - 1.0) * t)
    esperado = (9.99 + 0.60 - 0.55) - 10.0 * disc - 0.0003 * (9.99 + 10.0) - FEE * (0.60 + 0.55)
    assert r["folga"].iloc[0] == pytest.approx(esperado, abs=1e-9)
    assert bool(r["sobrevive"].iloc[0]) is True                                   # 30 negocios e ultimo negocio dentro das ofertas
    # ultimo negocio fora das ofertas: continua detectada, mas nao sobrevive (cotacao velha)
    op2 = op.copy()
    op2.loc[0, "fech"] = 0.80
    assert bool(arb.varrer(op2, sp, dias_ext=pd.DatetimeIndex(dias))["sobrevive"].iloc[0]) is False


# -------------------------------------------------------------------------------------------------------------- carteira simulada
def _linha_ranking(ativo, venc, custo, vant, familia="capital_protegido", est="call_no_dinheiro"):
    p = pd.Series(perna(f"{ativo}K10", "C", 10.0, 0.5, custo - 0.1, custo, venc=venc))
    return {"ativo": ativo, "estrutura": est, "familia": familia, "rotulo": est, "vencimento": venc, "pernas_obj": [(p, "compra")], "custo": custo, "perda_maxima": custo,
            "vantagem": vant, "ganho_maximo": None, "equilibrio": 10.0, "equilibrio_inf": None}


def _M(dia, linhas):
    op = pd.DataFrame([{"dia": pd.Timestamp(dia), "codigo": f"{l['ativo']}K10", "vencimento": l["vencimento"], "exercicio": 10.0, "oferta_compra": l["custo"] - 0.1,
                        "oferta_venda": l["custo"], "fech": l["custo"] - 0.05} for l in linhas])
    sp = pd.DataFrame([{"ativo": l["ativo"], "dia": pd.Timestamp(dia), "fech": 10.0, "fatcot": 1} for l in linhas])
    o = pd.DataFrame(columns=["ativo", "vencimento", "tipo", "boa", "negocios", "oferta_venda", "S", "exercicio"])
    return {"dia": pd.Timestamp(dia), "op": op, "sp": sp, "o": o, "ranking_bruto": pd.DataFrame(linhas)}


def test_carteira_idempotente_e_respeita_o_risco(tmp_path, monkeypatch):
    monkeypatch.setattr(dados, "vencimentos_padrao", lambda: [pd.Timestamp("2026-11-19")])
    monkeypatch.setattr(A, "arbitragens_du", lambda *a: 27)
    caminho = str(tmp_path / "carteira.json")
    linhas = [_linha_ranking("AAAA3", "2026-11-19", 3.0, 30.0),                      # 100 acoes = R$ 300 de risco: cabe
              _linha_ranking("BBBB3", "2026-11-19", 6.0, 25.0),                      # 1 lote = R$ 600 > R$ 500: nao pode abrir
              _linha_ranking("CCCC3", "2026-11-19", 2.0, 20.0, familia="pozinho"),   # familia reprovada: nao abre
              _linha_ranking("DDDD3", "2026-11-19", 1.5, 15.0),
              _linha_ranking("EEEE3", "2026-11-19", 1.0, 10.0),                      # terceira valida do dia: passa do limite de 2 por dia
              _linha_ranking("FFFF3", "2026-11-19", 1.0, -5.0)]                      # vantagem negativa: nao abre
    veredito = lambda r: {"estado": "reprovada" if r["familia"] == "pozinho" else "medindo"}  # noqa: E731
    M = _M("2026-10-09", linhas)
    pos1, res1, _ = CS.atualizar(M, veredito, caminho)
    abertas = [p for p in pos1 if not p.get("permanente")]
    assert [p["ativo"] for p in abertas] == ["AAAA3", "DDDD3"]
    assert all(p["risco_rs"] <= CS.RISCO_POR_ESTRUTURA for p in abertas)
    assert abertas[0]["qtd"] == 100 and abertas[0]["risco_rs"] == pytest.approx(300.0)
    assert abertas[1]["qtd"] == 300 and abertas[1]["risco_rs"] == pytest.approx(450.0)  # 500/1,5 = 333 acoes -> 3 lotes
    conteudo = open(caminho, encoding="utf-8").read()
    # segunda rodada com a MESMA cadeia: nada novo
    pos2, res2, _ = CS.atualizar(M, veredito, caminho)
    assert len(pos2) == len(pos1) and open(caminho, encoding="utf-8").read() == conteudo and res2 == res1
    assert res1["n_abertas"] == 2 and res1["risco_em_aberto_rs"] == pytest.approx(750.0)


def test_carteira_limites_de_seis_posicoes_e_tres_mil(tmp_path, monkeypatch):
    """Teto global antigo (6 posicoes e R$ 3.000): vale quando a fatia da vertente especulativa e o teto inteiro."""
    monkeypatch.setattr(dados, "vencimentos_padrao", lambda: [])
    monkeypatch.setattr(CS, "limite_risco_v1", lambda: CS.RISCO_TOTAL_MAX)
    caminho = str(tmp_path / "carteira.json")
    veredito = lambda r: {"estado": "medindo"}  # noqa: E731
    total = 0
    for i, dia in enumerate(pd.bdate_range("2026-10-09", periods=6)):
        linhas = [_linha_ranking(f"A{i}{j}", "2026-11-19", 2.4, 50.0 - j) for j in range(3)]        # 2,4 x 200 = R$ 480 de risco cada
        pos, res, _ = CS.atualizar(_M(dia, linhas), veredito, caminho)
        assert res["n_abertas"] <= CS.MAX_ABERTAS
        assert res["risco_em_aberto_rs"] <= CS.RISCO_TOTAL_MAX + 1e-6
        assert all(p["risco_rs"] <= CS.RISCO_POR_ESTRUTURA + 1e-6 for p in pos)
    assert res["n_abertas"] == 6 and res["risco_em_aberto_rs"] == pytest.approx(6 * 480)


def test_carteira_respeita_a_fatia_da_vertente_especulativa(tmp_path, monkeypatch):
    """Desde 11/10/2026 o risco aberto do ranking de assimetrias cabe na fatia da vertente especulativa (30% do orcamento de queda das opcoes)."""
    monkeypatch.setattr(dados, "vencimentos_padrao", lambda: [])
    caminho = str(tmp_path / "carteira.json")
    veredito = lambda r: {"estado": "medindo"}  # noqa: E731
    limite = CS.limite_risco_v1()
    assert limite == pytest.approx(0.30 * CS.RISCO_TOTAL_MAX)
    for i, dia in enumerate(pd.bdate_range("2026-10-09", periods=4)):
        linhas = [_linha_ranking(f"A{i}{j}", "2026-11-19", 2.4, 50.0 - j) for j in range(3)]
        pos, res, _ = CS.atualizar(_M(dia, linhas), veredito, caminho)
        assert res["risco_em_aberto_rs"] <= limite + 1e-6
    assert res["n_abertas"] == int(limite // 480)


def test_carteira_marca_pela_oferta_de_compra_e_encerra_no_vencimento(tmp_path, monkeypatch):
    monkeypatch.setattr(dados, "vencimentos_padrao", lambda: [])
    caminho = str(tmp_path / "carteira.json")
    veredito = lambda r: {"estado": "medindo"}  # noqa: E731
    l = _linha_ranking("AAAA3", "2026-10-16", 2.0, 10.0)
    CS.atualizar(_M("2026-10-09", [l]), veredito, caminho)
    # dia seguinte: oferta de compra de 1,90 -> valor = 1,90 x 200 acoes x (1 - emolumento)
    l2 = dict(l)
    M2 = _M("2026-10-13", [l2])
    M2["ranking_bruto"] = pd.DataFrame([])
    pos, res, _ = CS.atualizar(M2, veredito, caminho)
    p = pos[0]
    assert p["estado"] == "aberta" and p["valor_hoje"] == pytest.approx(1.9 * 200 * (1 - FEE), abs=0.01)
    assert p["resultado_rs"] == pytest.approx(p["valor_hoje"] - p["custo"], abs=0.01)
    # vencimento com o ativo a 12 e exercicio 10: valor intrinseco 2 x 200 acoes
    M3 = _M("2026-10-16", [l])
    M3["ranking_bruto"] = pd.DataFrame([])
    M3["sp"].loc[:, "fech"] = 12.0
    pos, res, _ = CS.atualizar(M3, veredito, caminho)
    assert pos[0]["estado"] == "encerrada" and pos[0]["valor_final"] == pytest.approx(400 * (1 - FEE), abs=0.01)
    assert res["n_encerradas"] == 1 and res["realizado_rs"] == pytest.approx(400 * (1 - FEE) - p["custo"], abs=0.01)

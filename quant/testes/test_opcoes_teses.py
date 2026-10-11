"""
Testes do livro de teses (quant/opcoes/teses.py): expressoes de um caso pequeno com conta feita a mao, teto de perda, tese sem cadeia liquida,
leitura dos arquivos da mesa e abertura na carteira simulada.
"""
import json

import pandas as pd
import pytest

from quant.opcoes import assimetrias as A
from quant.opcoes import carteira_simulada as CS
from quant.opcoes import custos as C
from quant.opcoes import teses as T

FEE = C.FEE_PREMIO
VENC = pd.Timestamp("2026-11-19")
DIA = pd.Timestamp("2026-10-09")


def linha(cod, tipo, K, delta, bid, ask, neg=200, iv=0.30, spread=None):
    mid = (bid + ask) / 2
    return {"ativo": "XXXX3", "codigo": cod, "tipo": tipo, "exercicio": K, "delta": delta, "oferta_compra": bid, "oferta_venda": ask, "negocios": neg, "iv": iv, "vencimento": VENC,
            "premio_ref": mid, "spread": (ask - bid) / mid if spread is None else spread, "boa": True, "S": 100.0, "du": 25}


def cadeia(**kw):
    return pd.DataFrame([
        linha("XXXXK100", "C", 100.0, 0.50, 3.00, 3.10, **kw), linha("XXXXK110", "C", 110.0, 0.25, 0.90, 1.00, **kw),
        linha("XXXXW100", "P", 100.0, -0.50, 2.90, 3.00, **kw), linha("XXXXW095", "P", 95.0, -0.30, 1.20, 1.30, **kw), linha("XXXXW090", "P", 90.0, -0.25, 0.60, 0.70, **kw)])


def M_de(o, S0=100.0):
    return {"dia": DIA, "o": o, "sp": pd.DataFrame([{"ativo": "XXXX3", "dia": DIA, "fech": S0, "fatcot": 1}]), "r_aa": 0.0, "tr": {}}


def tese(**kw):
    t = {"id": "t1", "ativo": "XXXX3", "direcao": "alta", "horizonte_pregoes": 10, "evento": None, "conviccao": 2, "origem": "mesa", "texto": "x",
         "cenarios": [{"nome": "alta", "probabilidade": 0.5, "retorno_do_ativo_pct": 10.0}, {"nome": "baixa", "probabilidade": 0.5, "retorno_do_ativo_pct": -10.0}]}
    t.update(kw)
    return t


@pytest.fixture(autouse=True)
def calendario_fixo(monkeypatch):
    monkeypatch.setattr(A, "arbitragens_du", lambda *a: 25)


# -------------------------------------------------------------------------------------------------------------- conta feita a mao
def test_custos_e_perdas_maximas_das_expressoes():
    ex = {e["nome"]: e for e in T.montar_expressoes(tese(), 100.0, cadeia(), "XXXX3", VENC, 25, 0.0)}
    assert ex["papel"]["custo"] == 100.0 and ex["papel"]["perda_maxima"] == 100.0
    assert ex["call_no_dinheiro"]["custo"] == pytest.approx(3.10 * (1 + FEE))
    assert ex["call_fora_do_dinheiro"]["custo"] == pytest.approx(1.00 * (1 + FEE))
    # trava de alta: compra a call de 100 na oferta de venda e vende a de 110 na oferta de compra; perda maxima = debito; ganho maximo = largura - debito
    deb = 3.10 * (1 + FEE) - 0.90 * (1 - FEE)
    assert ex["trava_de_alta"]["custo"] == pytest.approx(deb) and ex["trava_de_alta"]["perda_maxima"] == pytest.approx(deb)
    assert ex["trava_de_alta"]["ganho_maximo"] == pytest.approx(10.0 - deb)
    # put vendida coberta (delta 0,25 -> exercicio 90): recebe na oferta de compra, caixa = exercicio, perda maxima = exercicio - credito
    cred = 0.60 * (1 - FEE)
    assert ex["put_vendida_coberta"]["custo"] == pytest.approx(-cred)
    assert ex["put_vendida_coberta"]["caixa"] == pytest.approx(90.0) and ex["put_vendida_coberta"]["perda_maxima"] == pytest.approx(90.0 - cred)
    # trava de alta de credito com puts: vende a de 90 e compra a mais perto de 95% de 100... ~ 95: largura 5? (90 - 5 = 85 nao existe; usa a de strike mais perto dentro da tolerancia)
    if "trava_de_alta_com_puts" in ex:
        e = ex["trava_de_alta_com_puts"]
        assert e["perda_maxima"] < 90.0 and e["custo"] < 0


def test_resultado_no_vencimento_e_intrinseco():
    # call de 100 comprada a 3,10 (+ emolumento), ativo vai a 110 no vencimento (du_rem = 0): ganho = 10 x (1 - emolumento) - custo
    legs = [(pd.Series(linha("XXXXK100", "C", 100.0, 0.5, 3.0, 3.1, spread=0.0)), "compra", 3.10 * (1 + FEE))]
    g = T._resultado_cenario(legs, 100.0, 110.0, 0.0, 0, 1.0)
    assert g == pytest.approx(10.0 * (1 - FEE) - 3.10 * (1 + FEE))
    assert T._resultado_cenario(legs, 100.0, 95.0, 0.0, 0, 1.0) == pytest.approx(-3.10 * (1 + FEE))      # po: perde so o premio


def test_probabilidade_que_o_preco_exige_do_papel_e_50_por_cento_com_cenarios_simetricos():
    b, _ = T.avaliar_tese(tese(), M_de(cadeia()), None, [VENC])
    papel = next(e for e in b["expressoes"] if e["nome"] == "papel")
    assert papel["probabilidade_que_o_preco_exige_pct"] == pytest.approx(50.0)
    assert papel["valor_esperado_rs"] == pytest.approx(0.0, abs=1e-9)
    assert [g["resultado_rs"] for g in papel["ganho_por_cenario"]] == [pytest.approx(1000.0), pytest.approx(-1000.0)]      # R$ por lote de 100


# -------------------------------------------------------------------------------------------------------------- teto de perda e escolha
def test_perda_maxima_nunca_passa_do_teto_na_escolhida():
    # cenario muito favoravel: a call seca (R$ 3,10 x 100 = R$ 310) cabe; a put vendida (caixa de R$ 9.000) nao cabe mesmo com valor esperado positivo
    t = tese(cenarios=[{"nome": "alta", "probabilidade": 0.9, "retorno_do_ativo_pct": 20.0}, {"nome": "baixa", "probabilidade": 0.1, "retorno_do_ativo_pct": -2.0}])
    b, _ = T.avaliar_tese(t, M_de(cadeia()), None, [VENC])
    assert b["escolhida"] is not None
    esc = next(e for e in b["expressoes"] if e["nome"] == b["escolhida"])
    assert esc["perda_maxima"] <= T.TETO_PERDA + 1e-9 and esc["cabe_no_teto"]
    nao_cabem = [e for e in b["expressoes"] if not e["cabe_no_teto"]]
    assert nao_cabem and all(e["nome"] != b["escolhida"] for e in nao_cabem)
    # papel e put vendida passam do teto
    assert {"papel", "put_vendida_coberta"} <= {e["nome"] for e in nao_cabem}
    # a escolhida e a de maior valor esperado por R$ de perda maxima entre as que cabem e tem valor esperado positivo
    cab = [e for e in b["expressoes"] if e["cabe_no_teto"] and (e["valor_esperado_rs"] or 0) > 0]
    assert esc["retorno_sobre_risco"] == max(e["retorno_sobre_risco"] for e in cab)


def test_opcao_cara_demais_para_o_teto_nao_e_escolhida():
    o = pd.DataFrame([linha("XXXXK100", "C", 100.0, 0.50, 5.90, 6.00), linha("XXXXK110", "C", 110.0, 0.25, 4.90, 5.00), linha("XXXXW100", "P", 100.0, -0.50, 2.90, 3.00),
                      linha("XXXXW095", "P", 95.0, -0.30, 1.20, 1.30)])
    t = tese(cenarios=[{"nome": "alta", "probabilidade": 0.95, "retorno_do_ativo_pct": 30.0}, {"nome": "baixa", "probabilidade": 0.05, "retorno_do_ativo_pct": -2.0}])
    b, _ = T.avaliar_tese(t, M_de(o), None, [VENC])
    seca = next(e for e in b["expressoes"] if e["nome"] == "call_no_dinheiro")
    assert seca["perda_maxima"] > T.TETO_PERDA and not seca["cabe_no_teto"]
    assert b["escolhida"] != "call_no_dinheiro"


def test_tese_sem_cadeia_liquida_nao_gera_expressao():
    b, abrir = T.avaliar_tese(tese(), M_de(cadeia(neg=5)), None, [VENC])
    assert b["expressoes"] == [] and b["escolhida"] is None and abrir == []
    assert "Sem cadeia líquida" in b["porque"]
    # mesma coisa quando o spread passa do limite
    b2, _ = T.avaliar_tese(tese(), M_de(cadeia(spread=0.50)), None, [VENC])
    assert b2["expressoes"] == []


def test_escolha_e_deterministica():
    t = tese(cenarios=[{"nome": "alta", "probabilidade": 0.8, "retorno_do_ativo_pct": 15.0}, {"nome": "baixa", "probabilidade": 0.2, "retorno_do_ativo_pct": -5.0}])
    a, _ = T.avaliar_tese(t, M_de(cadeia()), None, [VENC])
    b, _ = T.avaliar_tese(t, M_de(cadeia()), None, [VENC])
    assert json.dumps(a, default=str, sort_keys=True) == json.dumps(b, default=str, sort_keys=True)


def test_esmagamento_da_volatilidade_reduz_o_valor_da_call_com_evento():
    t_ev = tese(evento={"data": "2026-10-25", "descricao": "eleição"})
    com, _ = T.avaliar_tese(t_ev, M_de(cadeia()), -30.0, [VENC])
    sem, _ = T.avaliar_tese(tese(), M_de(cadeia()), -30.0, [VENC])          # sem evento o esmagamento nao entra
    c_com = next(e for e in com["expressoes"] if e["nome"] == "call_no_dinheiro")
    c_sem = next(e for e in sem["expressoes"] if e["nome"] == "call_no_dinheiro")
    assert c_com["efeito_do_esmagamento_rs"] < 0 and c_sem["efeito_do_esmagamento_rs"] == 0
    assert c_com["valor_esperado_rs"] < c_sem["valor_esperado_rs"]


# -------------------------------------------------------------------------------------------------------------- arquivos da mesa
def test_leitura_de_teses_da_mesa_ausente_e_presente(tmp_path):
    assert T.ler_teses_mesa(str(tmp_path / "nao_existe.json")) == []
    f = tmp_path / "teses.json"
    f.write_text(json.dumps([tese(), {"id": "ruim", "direcao": "lado"}, {"id": "t2", "ativo": "YYYY3", "direcao": "baixa", "horizonte_pregoes": 5}]), encoding="utf-8")
    lidas = T.ler_teses_mesa(str(f))
    assert [t["id"] for t in lidas] == ["t1", "t2"]
    f.write_text("{ nao e json", encoding="utf-8")
    assert T.ler_teses_mesa(str(f)) == []


def test_teses_automaticas_do_evento_binario_da_visao_da_mesa(tmp_path):
    assert T.teses_da_visao_mesa(DIA, str(tmp_path / "x.json")) == []
    f = tmp_path / "visao.json"
    f.write_text(json.dumps({"acoes": [{"ticker": "BBAS3", "evento_binario": {"data": "2026-10-25", "descricao": "2º turno"}}, {"ticker": "PETR4"},
                                       {"ticker": "VALE3", "evento_binario": {"data": "2026-01-01", "descricao": "passado"}}]}), encoding="utf-8")
    ts = T.teses_da_visao_mesa(DIA, str(f))
    assert [t["ativo"] for t in ts] == ["BBAS3"] and ts[0]["origem"] == "robo" and ts[0]["evento"]["data"] == "2026-10-25"


# -------------------------------------------------------------------------------------------------------------- carteira
def test_tese_escolhida_abre_na_carteira_com_origem_e_sem_duplicar(tmp_path):
    t = tese(cenarios=[{"nome": "alta", "probabilidade": 0.9, "retorno_do_ativo_pct": 20.0}, {"nome": "baixa", "probabilidade": 0.1, "retorno_do_ativo_pct": -2.0}])
    b, abrir = T.avaliar_tese(t, M_de(cadeia()), None, [VENC])
    assert len(abrir) == 1 and abrir[0]["id"] == "t1"
    est = CS.estado_vazio(DIA)
    novas = CS.abrir_teses(est, abrir, DIA)
    assert len(novas) == 1 and novas[0]["origem"] == "mesa" and novas[0]["tese_id"] == "t1" and novas[0]["risco_rs"] <= CS.RISCO_POR_ESTRUTURA
    est["posicoes"] += novas
    assert CS.abrir_teses(est, abrir, DIA) == []                      # idempotente: a tese ja tem posicao aberta
    # tese com probabilidade pendente (caso do Douglas) nao abre
    t2 = dict(t, id="t2", origem="douglas", probabilidade_pendente=True)
    _, abrir2 = T.avaliar_tese(t2, M_de(cadeia()), None, [VENC])
    assert abrir2 == []


def test_capital_protegido_e_completado_uma_vez_so(monkeypatch, tmp_path):
    # tranche aberta com R$ 500 passa a R$ 1.000 na primeira rodada seguinte e nao muda na segunda
    o = pd.DataFrame([{"ativo": "PETR4", "codigo": "PETRK10", "tipo": "C", "vencimento": VENC, "oferta_venda": 2.0, "oferta_compra": 1.9, "fech": 1.95, "exercicio": 10.0, "negocios": 100, "boa": True, "S": 10.0}])
    est = {"desde": "2026-10-09", "ultima_data": "2026-10-09", "posicoes": [{"id": "x", "estado": "aberta", "permanente": True, "vencimento": "2026-11-19", "custo": 500.0, "risco_rs": 500.0,
                                                                      "valor_hoje": 500.0, "resultado_rs": 0.0, "titulo": "t", "pernas": [{"codigo": "PETRK10", "ativo": "PETR4", "tipo": "call", "lado": "compra", "exercicio": 10.0,
                                                                                                                                      "vencimento": "2026-11-19", "premio_entrada": 2.0, "qtd": 250.0}]}]}
    M = {"o": o}
    assert CS.completar_orcamento(est, M, {}, {"PETR4": 10.0}, DIA) == 1
    p = est["posicoes"][0]
    assert p["custo"] == pytest.approx(1000.0, abs=0.01) and p["orcamento_rs"] == pytest.approx(1000.0, abs=0.01)
    assert CS.completar_orcamento(est, M, {}, {"PETR4": 10.0}, DIA) == 0
    assert p["custo"] == pytest.approx(1000.0, abs=0.01)

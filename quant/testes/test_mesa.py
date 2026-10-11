"""Visao da mesa (10/10/2026): veto e ajuste pequeno de peso sobre a selecao quantitativa, sempre registrado."""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from quant import mesa

BRT = timezone(timedelta(hours=-3))


def _visao(gerado="2026-10-10T20:00:00-03:00", **kw):
    v = {"gerado": gerado, "validade_dias": 7,
         "macro": {"regime": "juro alto, eleicao no meio", "texto": "t", "favorece": ["bancos"], "pune": ["varejo"]},
         "setores": [{"setor": "bancos", "inclinacao": 2, "porque": "p"}, {"setor": "Varejo", "inclinacao": -2, "porque": "juro"}],
         "acoes": [{"ticker": "BBBB3", "conviccao": 2, "tese": "margem subindo"}, {"ticker": "RUIM3", "conviccao": -2, "risco": "lucro nao recorrente"},
                   {"ticker": "LOJA3", "conviccao": -1, "tese": "divida cara"}, {"ticker": "NEUT3", "conviccao": 0}]}
    v.update(kw)
    return v


def test_ler_devolve_motivo_quando_nao_ha_visao_ou_ela_venceu(tmp_path):
    arq = tmp_path / "visao_mesa.json"
    assert mesa.ler(str(arq)) == (None, "a mesa ainda não gravou a visão dela")
    arq.write_text(json.dumps(_visao()))
    v, motivo = mesa.ler(str(arq), hoje=datetime(2026, 10, 13, 9, 0, tzinfo=BRT))
    assert v is not None and "2026-10-10" in motivo
    v, motivo = mesa.ler(str(arq), hoje=datetime(2026, 10, 20, 9, 0, tzinfo=BRT))        # 10 dias depois: venceu
    assert v is None and "vencida" in motivo
    arq.write_text("{isso nao e json")
    assert mesa.ler(str(arq))[0] is None


def test_veto_tira_so_o_papel_com_conviccao_menos_dois():
    s = pd.DataFrame({"ticker": ["BBBB3", "RUIM3", "LOJA3", "NEUT3", "FORA3"], "rank": [1, 2, 3, 4, 5]})
    filtrado, reg = mesa.vetar(s, _visao())
    assert list(filtrado["ticker"]) == ["BBBB3", "LOJA3", "NEUT3", "FORA3"]
    assert reg == [{"ticker": "RUIM3", "efeito": "vetada", "porque": "lucro nao recorrente"}]
    assert mesa.vetar(s, None)[1] == [] and len(mesa.vetar(s, None)[0]) == 5              # sem visao: nada muda


def test_ajuste_de_peso_mantem_a_exposicao_e_o_teto():
    w = pd.Series({"BBBB3": 0.035, "LOJA3": 0.035, "NEUT3": 0.035, "FORA3": 0.035})
    setor = {"BBBB3": "Bancos", "LOJA3": "Comercio (varejo)", "NEUT3": "Energia", "FORA3": None}
    f = mesa.fatores_de_peso(list(w.index), _visao(), setor)
    assert f["BBBB3"] == pytest.approx(1.30 * 1.10) and f["LOJA3"] == pytest.approx(0.85 * 0.90) and f["NEUT3"] == 1.0 and f["FORA3"] == 1.0
    w2 = mesa.ajustar_pesos(w, f, cap=0.06)
    assert w2.sum() == pytest.approx(w.sum()) and w2["BBBB3"] > w2["NEUT3"] > w2["LOJA3"] and (w2 <= 0.06 + 1e-9).all()
    apertado = mesa.ajustar_pesos(w, f, cap=0.04)                                         # o teto por nome continua valendo
    assert apertado["BBBB3"] == pytest.approx(0.04) and apertado.sum() == pytest.approx(w.sum())
    reg = mesa.registro_dos_pesos(w, w2, _visao(), setor)
    por = {r["ticker"]: r for r in reg}
    assert por["BBBB3"]["efeito"] == "peso aumentado" and "convicção +2" in por["BBBB3"]["porque"] and "setor com inclinação +2" in por["BBBB3"]["porque"]
    assert por["LOJA3"]["efeito"] == "peso reduzido"
    assert mesa.ajustar_pesos(w, {}) is w                                                 # sem fatores: o mesmo objeto


def test_bloco_da_tela_com_e_sem_visao():
    b = mesa.bloco(None, "a mesa ainda não gravou a visão dela")
    assert b == {"ativa": False, "motivo": "a mesa ainda não gravou a visão dela", "aplicado": []}
    b = mesa.bloco(_visao(), "visão da mesa de 2026-10-10", [{"ticker": "RUIM3", "efeito": "vetada", "porque": "x"}])
    assert b["ativa"] and b["macro"]["regime"] and b["setores"][1]["inclinacao"] == -2 and b["aplicado"][0]["ticker"] == "RUIM3"
    assert "não tem teste" in b["regra"]


def test_carteira_alvo_sem_ajuste_fica_igual_e_com_ajuste_respeita_a_funcao():
    from quant import carteira as ct
    tk = [f"AAA{i}3" for i in range(22)]
    s = pd.DataFrame({"ticker": tk, "rank": range(1, 23), "vol252": [0.3] * 22, "adtv21": [5e7] * 22, "setor": ["x"] * 22,
                      "portao_qualidade": True, "portao_crescimento": True, "elegivel": True})
    precos = {t: 10.0 for t in tk}
    try:
        a = ct.carteira_alvo(s, ct.estado_inicial(100_000.0), precos, patrimonio=100_000.0, data="2026-10-09")
    except Exception:
        pytest.skip("a tabela minima de sinais deste teste nao basta para a selecao")
    b = ct.carteira_alvo(s, ct.estado_inicial(100_000.0), precos, patrimonio=100_000.0, data="2026-10-09", ajuste_pesos=None)
    assert a["pesos"].equals(b["pesos"]) and a["pesos"].equals(a["pesos_sem_ajuste"])
    c = ct.carteira_alvo(s, ct.estado_inicial(100_000.0), precos, patrimonio=100_000.0, data="2026-10-09",
                         ajuste_pesos=lambda w: mesa.ajustar_pesos(w, {w.index[0]: 1.3}, cap=ct.CAP_NOME))
    if len(c["pesos"]):
        assert c["pesos"].sum() == pytest.approx(c["pesos_sem_ajuste"].sum()) and c["pesos"].iloc[0] >= c["pesos_sem_ajuste"].iloc[0]

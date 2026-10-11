"""Orcamento de risco: funcoes puras, limites do livro de opcoes, corte por queda desligado por padrao e CLI."""
import json

import numpy as np
import pandas as pd
import pytest

from quant.risco import mao, orcamento as ob


# ─────────────────────────────────────────────────────────────
# (i) Exposicao por classe
# ─────────────────────────────────────────────────────────────
def test_exposicao_cai_quando_a_vol_recente_passa_da_media_e_nunca_alavanca():
    e, txt = ob.exposicao_de_classe(0.30, 0.20)
    assert e == pytest.approx(0.20 / 0.30) and "mao cai" in txt
    e2, txt2 = ob.exposicao_de_classe(0.10, 0.20)
    assert e2 == 1.0 and "mao cheia" in txt2                       # teto 1,0: sem alavancagem
    assert ob.exposicao_de_classe(0.10, 0.20, teto=1.5)[0] == 1.5  # so se o teto for mudado de proposito


def test_sem_dado_a_mao_fica_cheia_e_a_explicacao_diz_que_faltou():
    for v, a in ((None, 0.2), (0.2, None), (0.0, 0.2), (float("nan"), 0.2)):
        e, txt = ob.exposicao_de_classe(v, a)
        assert e == 1.0 and "sem volatilidade" in txt


def test_a_regra_do_orcamento_e_a_mesma_do_modulo_mao():
    r = pd.Series(np.random.default_rng(1).normal(0, 0.01, 400), index=pd.bdate_range("2020-01-01", periods=400))
    ex = mao.exposicao_por_vol(r, 63).iloc[-1]
    e, _ = ob.exposicao_de_classe(ex["vol"], ex["alvo"])
    assert e == pytest.approx(ex["decidida"])


def test_alocar_divide_o_capital_e_manda_o_resto_para_o_cdi():
    a = ob.alocar(100_000.0, {"acoes": 0.6, "opcoes": 0.3, "dolar": 0.1}, {"acoes": {"exposicao": 0.5}, "dolar": {"exposicao": 1.0}})
    assert a["acoes"]["capital_rs"] == pytest.approx(60_000.0) and a["acoes"]["em_risco_rs"] == pytest.approx(30_000.0)
    assert a["acoes"]["para_o_cdi_rs"] == pytest.approx(30_000.0)
    assert a["opcoes"]["exposicao"] == 1.0                           # sem exposicao informada: cheia
    t = a["_total"]
    assert t["capital_rs"] == 100_000.0 and t["em_risco_rs"] + t["para_o_cdi_rs"] == pytest.approx(100_000.0)


def test_pesos_que_nao_somam_um_sao_normalizados():
    a = ob.alocar(100_000.0, {"acoes": 6, "opcoes": 3, "dolar": 1}, {})
    assert a["acoes"]["peso"] == pytest.approx(0.6) and a["_total"]["em_risco_rs"] == pytest.approx(100_000.0)


# ─────────────────────────────────────────────────────────────
# (ii) Opcoes
# ─────────────────────────────────────────────────────────────
TESES = [{"titulo": "Call PRIO3", "risco_rs": 370.19, "familia": "capital_protegido", "vencimento": "2026-11-19"},
         {"titulo": "Call PETR4", "risco_rs": 317.16, "familia": "capital_protegido", "vencimento": "2026-12-18"},
         {"titulo": "Estrutura grande", "risco_rs": 900.0},
         {"titulo": "Capital protegido (permanente)", "risco_rs": 1000.0, "permanente": True}]


def test_risco_por_tese_e_total_contra_os_limites():
    r = ob.risco_opcoes(TESES, 100_000.0)
    assert r["n_teses"] == 3 and r["total_em_risco_rs"] == pytest.approx(1587.35)         # a posicao permanente fica de fora
    assert [t["dentro_do_limite"] for t in r["por_tese"]] == [True, True, False]     # R$ 900 > R$ 500 por estrutura
    assert r["limite_total_rs"] == 3000.0 and r["folga_rs"] == pytest.approx(3000.0 - 1587.35) and r["dentro_do_limite_total"]
    assert r["capital_protegido_mensal_rs"] == 1000.0 and r["pior_caso_rs"] == pytest.approx(2587.35)


def test_total_acima_de_tres_por_cento_e_sinalizado():
    r = ob.risco_opcoes([{"titulo": f"t{i}", "risco_rs": 500.0} for i in range(7)], 100_000.0)
    assert not r["dentro_do_limite_total"] and r["folga_rs"] < 0


def test_sem_teses_o_risco_e_zero_e_o_protegido_cai_no_padrao_de_um_por_cento():
    r = ob.risco_opcoes([], 100_000.0)
    assert r["total_em_risco_rs"] == 0.0 and r["n_teses"] == 0 and r["dentro_do_limite_total"]
    assert r["capital_protegido_mensal_rs"] == 1000.0


# ─────────────────────────────────────────────────────────────
# (iii) Corte por queda
# ─────────────────────────────────────────────────────────────
def test_corte_por_queda_vem_desligado_e_nao_muda_a_exposicao():
    c = ob.corte_por_queda([100, 110, 90])
    assert c["ativo"] is False and c["estaria_cortado"] is True and c["exposicao_aplicada"] == 1.0
    assert c["queda_atual"] == pytest.approx(20 / 110) and "nao se sustentou" in c["motivo"]


def test_corte_por_queda_ligado_aplica_o_fator():
    c = ob.corte_por_queda([100, 110, 90], ativo=True)
    assert c["ativo"] and c["exposicao_aplicada"] == 0.5


def test_corte_por_queda_sem_historico():
    c = ob.corte_por_queda([])
    assert not c["estaria_cortado"] and np.isnan(c["queda_atual"])


# ─────────────────────────────────────────────────────────────
# Montagem e CLI
# ─────────────────────────────────────────────────────────────
def _entradas():
    return dict(capital=100_000.0, vols={"acoes": 0.30, "dolar": 0.10, "opcoes": None}, alvos={"acoes": 0.20, "dolar": 0.12, "opcoes": None},
                teses=TESES, patrimonio=[100_000.0, 100_040.0])


def test_orcamento_completo_fecha_as_contas_e_explica_cada_numero():
    o = ob.orcamento(**_entradas())
    assert o["classes"]["acoes"]["exposicao"] == pytest.approx(0.2 / 0.3)
    assert o["classes"]["dolar"]["exposicao"] == 1.0 and o["classes"]["opcoes"]["exposicao"] == 1.0
    t = o["total"]
    assert t["em_risco_rs"] + t["para_o_cdi_rs"] == pytest.approx(100_000.0)
    assert len(o["porque"]) == 5 and "Acoes" in o["porque"][0] and "Opcoes:" in o["porque"][3] and "Corte por queda" in o["porque"][4]
    assert "22,0%" not in " ".join(o["porque"]) and "," in o["porque"][0]                # formato brasileiro
    assert o["corte_por_queda"]["ativo"] is False and o["avisos"] == []
    assert "premio pago" in o["classes"]["opcoes"]["porque"]
    o2 = ob.orcamento(**dict(_entradas(), vols={"acoes": None, "dolar": 0.1, "opcoes": None}))
    assert any("acoes" in a for a in o2["avisos"])
    assert o["regra_mao"]["teto"] == 1.0 and o["regra_mao"]["janela"] == 63
    json.dumps(o, default=float)                                       # serializa


def test_corte_ligado_nao_deixa_a_exposicao_passar_do_fator():
    ent = _entradas()
    ent["patrimonio"] = [100_000.0, 120_000.0, 100_000.0]            # queda de 16,7% desde o pico
    o = ob.orcamento(**ent, queda_ativa=True)
    assert o["corte_por_queda"]["exposicao_aplicada"] == 0.5
    assert all(c["exposicao"] <= 0.5 + 1e-12 for c in o["classes"].values())


def test_orcamento_nao_depende_do_relogio_quando_a_data_e_dada():
    from datetime import datetime
    a = ob.orcamento(**_entradas(), agora=datetime(2026, 10, 10, 12, 0, 0))
    b = ob.orcamento(**_entradas(), agora=datetime(2026, 10, 10, 12, 0, 0))
    assert a == b and a["gerado_em"] == "2026-10-10T12:00:00"


def test_cli_imprime_e_grava_o_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ob, "carregar_entradas", lambda *a, **k: dict(_entradas(), fontes={"acoes": "teste"}))
    arq = tmp_path / "risco" / "orcamento.json"
    assert ob.main(["--saida", str(arq)]) == 0
    saida = capsys.readouterr().out
    assert "Orcamento de risco" in saida and "TOTAL" in saida and "Corte por queda" in saida
    d = json.loads(arq.read_text(encoding="utf-8"))
    assert d["capital"] == 100_000.0 and d["fontes"]["acoes"] == "teste" and "porque" in d and d["opcoes"]["n_teses"] == 3


def test_cli_aceita_outro_capital(monkeypatch, tmp_path):
    monkeypatch.setattr(ob, "carregar_entradas", lambda *a, **k: dict(_entradas(), fontes={}))
    arq = tmp_path / "o.json"
    ob.main(["--saida", str(arq), "--capital", "200000"])
    assert json.loads(arq.read_text())["capital"] == 200_000.0


def test_vol_e_alvo_de_serie_curta_devolve_vazio():
    assert ob._vol_e_alvo(pd.Series([0.01] * 10)) == (None, None)
    r = pd.Series(np.random.default_rng(2).normal(0, 0.01, 300))
    v, a = ob._vol_e_alvo(r)
    assert v > 0 and a > 0


def test_carregar_entradas_sem_arquivos_nao_quebra(tmp_path):
    e = ob.carregar_entradas(painel=str(tmp_path / "nao.json"), livro_opcoes=str(tmp_path / "nao2.json"),
                             ptax=str(tmp_path / "nao.csv"), serie_vivo=str(tmp_path / "nao3.json"))
    assert e["capital"] == 100_000.0 and e["teses"] == [] and e["patrimonio"] == []
    assert e["vols"]["dolar"] is None and e["vols"]["acoes"] is None and "sem PTAX" in e["fontes"]["dolar"]

"""Livro inteiro: pesos entre classes, mao por volatilidade e orcamento de queda (quant/risco/livro.py)."""
import json
from datetime import datetime

import pytest

from quant.risco import livro


def _orc(tmp_path, exposicao=0.8, quando="2026-10-12T08:40:00"):
    a = tmp_path / "orcamento.json"
    a.write_text(json.dumps({"gerado_em": quando, "classes": {"acoes": {"exposicao": exposicao}}}))
    return str(a)


def test_config_sem_arquivo_e_o_padrao_desligado(tmp_path):
    c = livro.config(str(tmp_path / "nao_existe.json"))
    assert c["ligado"] is False and c["pesos"] == {"acoes": 0.60, "opcoes": 0.30, "dolar": 0.10}
    assert c["corte_por_queda"] is False and c["queda_maxima_livro_pct"] == 25.0
    assert livro.peso("opcoes", str(tmp_path / "nao_existe.json")) == 1.0          # desligado: cada modulo com o capital inteiro


def test_config_recusa_pesos_que_nao_somam_um(tmp_path):
    a = tmp_path / "l.json"
    a.write_text(json.dumps({"ligado": True, "pesos": {"acoes": 0.9, "opcoes": 0.3, "dolar": 0.1}, "queda_maxima_livro_pct": 500}))
    c = livro.config(str(a))
    assert c["ligado"] is True and c["pesos"]["acoes"] == 0.60 and c["queda_maxima_livro_pct"] == 25.0
    a.write_text("isto nao e json")
    assert livro.config(str(a))["ligado"] is False


def test_exposicao_das_acoes_e_peso_vezes_mao(tmp_path):
    a = tmp_path / "l.json"
    a.write_text(json.dumps({"ligado": True, "pesos": {"acoes": 0.6, "opcoes": 0.3, "dolar": 0.1}}))
    v, txt = livro.exposicao_acoes("2026-10-13", str(a), _orc(tmp_path, 0.8))
    assert v == pytest.approx(0.48) and "48%" in txt and "0,80" in txt
    v, _ = livro.exposicao_acoes("2026-10-13", str(a), _orc(tmp_path, 1.7))            # nunca alavanca
    assert v == pytest.approx(0.60)
    a.write_text(json.dumps({"ligado": True, "mao_por_volatilidade": False}))
    assert livro.exposicao_acoes("2026-10-13", str(a), _orc(tmp_path, 0.5))[0] == pytest.approx(0.60)
    a.write_text(json.dumps({"ligado": False}))
    assert livro.exposicao_acoes("2026-10-13", str(a), _orc(tmp_path, 0.5))[0] is None


def test_orcamento_de_risco_velho_ou_ausente_da_mao_cheia_e_diz(tmp_path):
    m, txt = livro.mao_das_acoes("2026-10-13", str(tmp_path / "nada.json"))
    assert m == 1.0 and "sem orçamento" in txt
    m, txt = livro.mao_das_acoes("2026-10-20", _orc(tmp_path, 0.5, "2026-10-12T08:40:00"))
    assert m == 1.0 and "velho" in txt
    m, _ = livro.mao_das_acoes(datetime(2026, 10, 13, 9, 0), _orc(tmp_path, 0.5, "2026-10-09T18:30:00"))   # sexta vale ate terca
    assert m == 0.5


def test_carteira_le_o_livro_quando_nao_ha_ordem_direta(tmp_path):
    from quant import config_carteira as cc
    lv = tmp_path / "l.json"
    lv.write_text(json.dumps({"ligado": True}))
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"razao_protecao": 0.25}))
    v, txt = cc.exposicao_acoes("2026-10-13", arq=str(cfg), padrao=0.70, arq_livro=str(lv), arq_orcamento=_orc(tmp_path, 0.9))
    assert v == pytest.approx(0.54) and "peso de 60%" in txt
    cfg.write_text(json.dumps({"exposicao_acoes": 0.35}))                               # ordem direta do Douglas manda
    assert cc.exposicao_acoes("2026-10-13", arq=str(cfg), padrao=0.70, arq_livro=str(lv), arq_orcamento=_orc(tmp_path, 0.9))[0] == 0.35
    lv.write_text(json.dumps({"ligado": False}))
    cfg.write_text(json.dumps({}))
    assert cc.exposicao_acoes("2026-10-13", arq=str(cfg), padrao=0.70, arq_livro=str(lv)) == (0.70, "padrão da carteira")


def test_situacao_soma_as_quedas_e_marca_quem_estourou(tmp_path):
    a = str(tmp_path / "nao_existe.json")                                               # padrao: 25% = 17 + 3 + 5
    s = livro.situacao(100_000, {"acoes": {"pico_rs": 2000, "agora_rs": -3000}, "opcoes": {"pico_rs": 0, "agora_rs": -3100},
                                 "daytrade": {"pico_rs": 500, "agora_rs": 900}}, a)
    por = {m["modulo"]: m for m in s["modulos"]}
    assert por["acoes"]["queda_rs"] == 5000 and por["acoes"]["orcamento_rs"] == 17000 and not por["acoes"]["estourou"]
    assert por["opcoes"]["estourou"] and por["daytrade"]["queda_rs"] == 0.0             # acima do pico: queda zero, nunca negativa
    assert s["queda_do_livro_rs"] == 8100 and s["orcamento_do_livro_rs"] == 25000 and not s["estourou"]
    s = livro.situacao(100_000, {"acoes": {"pico_rs": 0, "agora_rs": -22000}, "daytrade": {"pico_rs": 0, "agora_rs": -3000}}, a)
    assert s["estourou"] and s["usado_pct"] == 100.0


def test_daytrade_soma_todas_as_regras_por_pregao(tmp_path):
    (tmp_path / "serie.json").write_text(json.dumps([{"data": "2026-10-08", "resultado": 300.0}]))
    (tmp_path / "serie_niveis.json").write_text(json.dumps([{"data": "2026-10-08", "resultado": -100.0}, {"data": "2026-10-09", "resultado": -500.0}]))
    (tmp_path / "outro.json").write_text("[]")
    assert livro.resultado_daytrade(str(tmp_path)) == (-300.0, 200.0)
    assert livro.resultado_daytrade(str(tmp_path / "vazia")) == (0.0, 0.0)


def test_orcamento_do_capital_protegido_e_sobre_a_classe(tmp_path, monkeypatch):
    from quant.opcoes import carteira_simulada as cs
    lv = tmp_path / "l.json"
    lv.write_text(json.dumps({"ligado": True}))
    monkeypatch.setattr(livro, "ARQ", str(lv))
    assert cs.orcamento_mensal() == 300.0                                               # 1% de 30% de R$ 100 mil
    lv.write_text(json.dumps({"ligado": False}))
    assert cs.orcamento_mensal() == 1000.0                                              # livro desligado: base antiga


def test_risco_de_opcoes_usa_o_capital_da_classe_para_o_capital_protegido():
    from quant.risco import orcamento as orc
    r = orc.risco_opcoes([], 100_000, capital_da_classe=30_000)
    assert r["capital_protegido_mensal_rs"] == 300.0 and r["capital_protegido_regra_rs"] == 300.0 and r["limite_total_rs"] == 3000.0
    aberta = [{"titulo": "tranche de outubro", "risco_rs": 1000.0, "permanente": True}]
    r = orc.risco_opcoes(aberta, 100_000, capital_da_classe=30_000)                     # o que ja esta aberto aparece como esta
    assert r["capital_protegido_mensal_rs"] == 1000.0 and r["capital_protegido_regra_rs"] == 300.0


def test_tranche_maior_que_o_orcamento_novo_nao_e_mexida(tmp_path, monkeypatch):
    import pandas as pd
    from quant.opcoes import carteira_simulada as cs
    lv = tmp_path / "l.json"
    lv.write_text(json.dumps({"ligado": True}))
    monkeypatch.setattr(livro, "ARQ", str(lv))
    est = {"posicoes": [{"permanente": True, "estado": "aberta", "vencimento": "2026-11-19", "orcamento_rs": 1000.0, "custo": 1000.0, "pernas": []}]}
    assert cs.completar_orcamento(est, {"o": pd.DataFrame()}, {}, {}, pd.Timestamp("2026-10-13")) == 0
    assert est["posicoes"][0]["orcamento_rs"] == 1000.0


def test_livro_estourado_trava_tese_nova(tmp_path, monkeypatch):
    from quant.opcoes import carteira_simulada as cs
    assert cs.livro_estourado() is False                                                # sem arquivo: nao trava
    arq = tmp_path / "livro.json"
    arq.write_text(json.dumps({"estourou": True}))
    monkeypatch.setattr(livro, "ARQ_SAIDA", str(arq))
    assert cs.livro_estourado() is True


def test_caso_de_estudo_nunca_abre():
    import inspect
    from quant.opcoes import teses
    fonte = inspect.getsource(teses.caso_bbas3)
    assert '"exemplo": True' in fonte and '"origem": "exemplo"' in fonte
    assert 'not tese.get("exemplo")' in inspect.getsource(teses.avaliar_tese)


def test_resultado_das_acoes_soma_fatores_e_swing(tmp_path):
    fat = tmp_path / "fat.json"
    swi = tmp_path / "swi.json"
    fat.write_text(json.dumps([{"data": "2026-10-08", "patrimonio": 99_900.0}]))                       # fatores: -100, depois parou
    swi.write_text(json.dumps([{"data": "2026-10-13", "patrimonio": 60_500.0}, {"data": "2026-10-14", "patrimonio": 59_700.0}]))
    agora, pico = livro.resultado_acoes(100_000, arq=str(fat), arq_swing=str(swi), capital_swing=60_000)
    assert agora == pytest.approx(-400.0) and pico == pytest.approx(400.0)                               # -100 +500 no pico; -100 -300 agora
    assert livro.resultado_acoes(100_000, arq=str(tmp_path / "x.json"), arq_swing=str(tmp_path / "y.json"), capital_swing=60_000) == (0.0, 0.0)

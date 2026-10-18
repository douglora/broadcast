"""Camada de observacao (12/10/2026): sinais, termometro, dose e placar, tudo so medido, com um terminal de mentira."""
import json
import os
from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant.observacao import dose, fontes, placar, sinais, termometro


def _hist(pasta, simbolo, valores, inicio="2025-01-01", venc=None):
    datas = pd.bdate_range(inicio, periods=len(valores))
    d = {"s": simbolo, "t": [x.strftime("%Y-%m-%d") for x in datas], "c": list(map(float, valores)), "ac": list(map(float, valores))}
    if venc:
        d["venc"] = venc
    with open(os.path.join(pasta, f"{simbolo}.json"), "w", encoding="utf-8") as f:
        json.dump(d, f)


@pytest.fixture
def terminal(tmp_path, monkeypatch):
    out = tmp_path / "cache" / "out"
    (out / "hist").mkdir(parents=True)
    (out / "pagina").mkdir()
    n = 300
    base = np.linspace(100, 130, n)
    _hist(out / "hist", "IBOV", base * 1000)
    _hist(out / "hist", "USDBRL", np.r_[np.full(n - 10, 5.0), np.full(10, 5.2)])          # +4% nos ultimos 10 pregoes
    _hist(out / "hist", "DXY", np.r_[np.full(n - 20, 100.0), np.full(20, 103.0)])          # +3% em 20 pregoes
    _hist(out / "hist", "VIX", np.r_[np.full(n - 1, 14.0), [26.0]])                        # VIX 26: estresse
    _hist(out / "hist", "BRENT", np.full(n, 80.0))
    _hist(out / "hist", "SPY", np.r_[np.full(n - 5, 500.0), np.full(5, 510.0)])             # +2% em 5 pregoes (a favor do risco)
    _hist(out / "hist", "HYG", np.r_[np.full(n - 5, 80.0), np.full(5, 79.0)])               # credito caiu (contra)
    _hist(out / "hist", "UST10Y", np.r_[np.full(n - 10, 4.0), np.full(10, 4.4)])            # +40 pontos-base
    _hist(out / "hist", "TD-IPCA-2035", np.full(n, 7.0))
    _hist(out / "hist", "DI1F28", np.r_[np.full(n - 63, 13.0), np.full(63, 12.0)], venc="2028-01-03")   # -100 pontos-base em 63 pregoes
    datas = [x.strftime("%Y-%m-%d") for x in pd.bdate_range("2025-01-01", periods=n)]
    hy = {"spreads": {"series": {"hy": {"t": datas, "v": list(np.r_[np.full(n - 10, 3.0), np.full(10, 3.5)])}}},
          "di": {"data": datas[-1], "curvas": {"hoje": [[20, 13.5], [250, 13.0], [500, 12.5], [750, 12.4]]}}}
    (out / "rf.json").write_text(json.dumps(hy))
    (out / "macro.json").write_text(json.dumps({"focus": {"data": "2026-10-09", "itens": [{"indicador": "IPCA", "ano": 2026, "mediana": 5.01, "ha_1_sem": 4.90, "ha_4_sem": 5.0}]},
                                                 "indicadores": [{"id": "vix", "valor": 26.0}]}))
    (out / "b3.json").write_text(json.dumps({"fluxo": {"serie_dia": {"t": datas[-8:], "estrangeiro": [1e9] * 8}}}))
    (out / "pagina" / "wirp.json").write_text(json.dumps({"copom": {"reunioes": [{"data": "2026-11-05", "movimento_bps": -25}]}}))
    import time as _t
    (out / "tempo_real").mkdir()
    estado = {"v": 1, "gerado": "2026-10-13T08:35:00-03:00", "gerado_epoch": _t.time(), "ok": True,
              "agenda": {"proximos": [{"evento": "CPI (mes)", "pais": "US", "indicador": "cpi_mm", "quando": "2026-10-14T09:30:00-03:00", "faltam_s": 3600, "importancia": 3, "consenso": 0.6, "unidade": "%"}],
                         "ultimo_que_saiu": {"evento": "Payroll", "pais": "US", "indicador": "payroll", "quando": "2026-10-02T09:30:00-03:00", "consenso": 52, "efetivo": 29, "surpresa": -23, "surpresa_dp": -1.4}},
              "regime": {"itens": {"VIX": {"valor": 26.0, "pctl_1a": 92.0, "fonte": "Yahoo", "hora": "2026-10-13T08:34:00-03:00"}}},
              "saude": {"motor": {"mt5": {"em_rajadas": True, "idade_ultimo_tique_s": 25}}},
              "fluxo": {"posicao_em_aberto_total": {"valor": {"WDO": {"contratos_em_aberto": 500000, "variacao_dia": -1200}}, "pregao": "2026-10-09"}}}
    (out / "tempo_real" / "estado.json").write_text(json.dumps(estado))
    monkeypatch.setenv("AUTOPILOT_TERMINAL", str(tmp_path))
    # TIR (19/10/2026): 20 papeis na TIR nova a 6 pontos e 20 na reserva antiga a 1 ponto; a mediana conta so a nova
    tabela = pd.DataFrame({"consenso_lpa_rev_30d_pct": [2.0] * 30 + [-1.0] * 10, "tir_premio_pp": [6.0] * 20 + [1.0] * 20,
                           "tir_fonte": ["analistas"] * 18 + ["safra"] * 2 + ["antiga"] * 20})
    monkeypatch.setattr(fontes, "tabela_terminal", lambda: tabela)
    monkeypatch.setattr(fontes, "cartas_tom", lambda hoje, meses=3, caminho=None: {"cautela": 30, "oportunidade": 10, "docs": 12, "desde": "2026-07"})
    return out


def test_fontes_le_serie_e_curva(terminal):
    s = fontes.serie("IBOV")
    assert len(s) == 300 and s.index.is_monotonic_increasing and float(s.iloc[-1]) == pytest.approx(130_000.0)
    assert fontes.serie("NAO_EXISTE").empty
    taxa, data = fontes.di_taxa(504)
    assert taxa == pytest.approx(12.5 - 0.1 * 4 / 250, abs=1e-6)
    assert fontes.copom_proximo() == ("2026-11-05", -25)
    assert len(fontes.fluxo_estrangeiro()) == 8 and len(fontes.spread_serie("hy")) == 300


def test_sinais_leem_o_terminal_de_mentira(terminal):
    f = sinais.montar_fontes(date(2026, 10, 13))
    lidos, faltam = sinais.calcular(f)
    por = {s["id"]: s for s in lidos}
    assert por["ust10_10d"]["leitura"] == -1 and por["ust10_10d"]["valor"] == pytest.approx(40.0)
    assert por["dxy_20d"]["leitura"] == 1 and por["usdbrl_10d"]["leitura"] == 1
    assert por["vix_regime"]["leitura"] == -1 and por["brent_10d"]["leitura"] == 0
    assert por["hy_10d"]["leitura"] == -1 and por["hy_10d"]["valor"] == pytest.approx(50.0)
    assert por["di2_63d"]["leitura"] == 1 and por["di2_63d"]["valor"] == pytest.approx(-100.0)
    assert por["focus_ipca_1sem"]["leitura"] == -1                       # IPCA subiu na semana: contra
    assert por["fluxo_estrangeiro_5d"]["leitura"] == 1 and por["fluxo_estrangeiro_5d"]["valor"] == pytest.approx(5.0)
    assert por["consenso_revisoes_30d"]["leitura"] == 1 and por["consenso_revisoes_30d"]["valor"] == pytest.approx(75.0)
    assert por["ibov_mm200"]["leitura"] == 1 and por["ibov_vol_20_252"]["leitura"] in (-1, 0, 1)
    assert por["erp_tir_safra_mediana"]["leitura"] == 1 and por["cartas_tom"]["leitura"] == -1
    assert por["erp_tir_safra_mediana"]["valor"] == pytest.approx(6.0) and "(20 empresas" in por["erp_tir_safra_mediana"]["texto"]
    assert "erp_tir_mediana" not in por                                  # a definicao antiga saiu (id novo: o placar nao mistura)
    # rodada 2 (12/10/2026): apetite a risco conta so o S&P (HYG caiu, DXY parado em 5 pregoes, VIX subiu) e a vol do dolar esta alta
    assert por["risco_apetite"]["valor"] == 1 and por["risco_apetite"]["leitura"] == -1
    assert por["usdbrl_vol_regime"]["leitura"] == 1
    # estado do mundo em tempo real (so medindo): proximo evento em ~1 h, payroll 1,4 desvios abaixo (dolar mais fraco), VIX no percentil 92, feed em rajadas
    assert abs(por["tr_proximo_evento"]["valor"] - 1.0) < 0.05 and por["tr_proximo_evento"]["leitura"] == 0
    assert por["tr_ultimo_dado"]["leitura"] == -1 and por["tr_ultimo_dado"]["valor"] == pytest.approx(-1.4)
    assert por["tr_vix_percentil"]["leitura"] == -1 and por["tr_feed_mt5"]["leitura"] == -1
    assert por["tr_posicao_aberta_wdo"]["valor"] == 500000
    assert por["dado_eua_hoje"]["leitura"] == 0 and "8h30" in por["dado_eua_hoje"]["texto"]
    assert por["copom_proximo"]["data_dado"] == "2026-11-05"
    assert not faltam or all(x in ("ntnb35_20d",) for x in faltam)
    for s in lidos:
        assert set(s) >= {"id", "grupo", "modulo", "horizonte", "valor", "leitura", "texto", "fonte"} and s["leitura"] in (-1, 0, 1)


def test_estado_velho_nao_vale(terminal):
    arq = terminal / "tempo_real" / "estado.json"
    e = json.loads(arq.read_text())
    e["gerado_epoch"] -= 3600
    arq.write_text(json.dumps(e))
    assert fontes.tempo_real() is None                                  # processo parado: sem dado, nunca dado velho


def test_termometro_conta_as_sete_e_declara_desconhecidas(terminal):
    f = sinais.montar_fontes(date(2026, 10, 13), com_tabela=False)
    t = termometro.ler(f)
    # acesas: ust10 (+40), vix (26), hy (+50), usdbrl (+4%); nao: dxy (o salto de 3% foi ha 20 pregoes, nao 10), brent, di2 (caiu)
    assert t["pontos"] == 4 and t["estado"] == "estresse" and t["desconhecidas"] == []
    f["series"]["VIX"] = pd.Series(dtype=float)
    f["series"]["UST10Y"] = pd.Series(dtype=float)
    f["hy"] = pd.Series(dtype=float)
    t2 = termometro.ler(f)
    assert t2["estado"] == "sem leitura" and sorted(t2["desconhecidas"]) == ["hy_10d_bps", "ust10_10d_bps", "vix"]


def test_dose_escada_e_eventos():
    mapa = {date(2026, 10, 14): {"cpi"}}
    evs = dose.eventos_proximos(date(2026, 10, 13), mapa, copom=("2026-11-05", -25))
    assert [e["evento"] for e in evs] == ["cpi"] and evs[0]["pregoes"] == 1
    evs2 = dose.eventos_proximos(date(2026, 10, 20), mapa, copom=None)
    assert any(e["evento"].startswith("2o turno") and e["pregoes"] == 4 for e in evs2)   # terca 20/10 -> domingo 25/10: 4 pregoes
    assert dose.degrau("estresse", [])[0] == "zero"
    assert dose.degrau("calmo", [])[0] == "medio"
    assert dose.degrau("calmo", evs)[0] == "baixo"
    assert dose.degrau("alerta", [])[0] == "baixo"
    r = dose.recomendar(date(2026, 10, 13), {"estado": "calmo"}, mapa, None, vol_ibov_20d=0.20, mao_atual=1.0)
    assert r["degrau"] == "baixo" and r["exposicao_equivalente_bolsa"] == pytest.approx(0.075) and r["mao_atual_do_livro"] == 1.0


def test_placar_pontua_aposenta_e_registra(tmp_path, monkeypatch):
    arq = tmp_path / "sinais.jsonl"
    monkeypatch.setattr(placar, "ARQ_LEITURAS", str(arq))
    monkeypatch.setattr(placar, "ARQ_PLACAR", str(tmp_path / "placar.json"))
    monkeypatch.setattr(placar, "DIR_OBS", str(tmp_path))
    datas = pd.bdate_range("2026-01-01", periods=200)
    ibov = pd.Series(np.linspace(100.0, 200.0, 200), index=datas)                 # so sobe
    usd = pd.Series(np.linspace(5.0, 4.0, 200), index=datas)                      # so cai
    regs = []
    for i in range(0, 150):
        regs.append({"dia": datas[i].strftime("%Y-%m-%d"),
                     "sinais": [{"id": "bom", "modulo": "indice", "grupo": "grafico", "horizonte": 10, "leitura": 1},
                                {"id": "ruim", "modulo": "dolar", "grupo": "macro", "horizonte": 10, "leitura": 1},
                                {"id": "neutro", "modulo": "indice", "grupo": "macro", "horizonte": 10, "leitura": 0}]})
    tab = {x["id"]: x for x in placar.pontuar(regs, {"IBOV": ibov, "USDBRL": usd})}
    assert tab["bom"]["estado"] == "informativo" and tab["bom"]["acerto_pct"] == 100.0 and tab["bom"]["n"] == 150
    assert tab["ruim"]["estado"] == "aposentado" and tab["ruim"]["acerto_pct"] == 0.0
    assert "neutro" not in tab                                                    # leitura 0 nao pontua
    # as ultimas 40 leituras do "ruim" passam a acertar: volta a medir (G2)
    regs2 = regs[:110] + [dict(r, sinais=[dict(s, leitura=-1) if s["id"] == "ruim" else s for s in r["sinais"]]) for r in regs[110:]]
    assert {x["id"]: x for x in placar.pontuar(regs2, {"IBOV": ibov, "USDBRL": usd})}["ruim"]["estado"] == "medindo"
    # registrar substitui o mesmo dia
    assert placar.registrar("2026-10-13", [{"id": "x", "leitura": 1}], {"estado": "calmo", "pontos": 0, "desconhecidas": []}, {"degrau": "medio", "vol_alvo_aa_pct": 4.0}) == 1
    assert placar.registrar("2026-10-13", [{"id": "y", "leitura": 1}], {"estado": "calmo", "pontos": 0, "desconhecidas": []}, {"degrau": "medio", "vol_alvo_aa_pct": 4.0}) == 1
    assert placar.carregar()[0]["sinais"][0]["id"] == "y"
    obj = placar.montar(regs, {"IBOV": ibov, "USDBRL": usd})
    assert os.path.exists(tmp_path / "placar.json") and "informativo" in placar.texto(obj)


def test_brier_do_cartao():
    datas = pd.bdate_range("2026-10-01", periods=30)
    ibov = pd.Series(np.linspace(100.0, 110.0, 30), index=datas)
    cartao = {"cenarios": [{"nome": "sobe", "probabilidade": 0.7, "gatilhos": [{"serie": "IBOV", "limiar": 105.0, "sentido": "acima", "data_verificacao": "2026-10-30"}]},
                           {"nome": "cai", "probabilidade": 0.3, "gatilhos": [{"serie": "IBOV", "limiar": 95.0, "sentido": "abaixo", "data_verificacao": "2026-10-30"}]}]}
    assert placar.brier(cartao, {"IBOV": ibov}, hoje="2026-10-20") is None             # ainda nao e hora
    r = placar.brier(cartao, {"IBOV": ibov}, hoje="2026-11-05")
    assert r["realizado"] == ["sobe"] and r["brier"] == pytest.approx(0.18) and r["brier_ingenuo"] == pytest.approx(0.5) and r["melhor_que_ingenuo"]


def test_retrato_diario_da_tir_grava_so_a_nova_e_o_dia_recusado(tmp_path):
    from quant.observacao import tir_diaria
    t = pd.DataFrame({"tir_prudente_pct": [10.33, np.nan, 15.0], "tir_premio_pp": [3.43, np.nan, 8.1], "tir_fonte": ["analistas", None, "safra"],
                      "tir_potencial_pct": [1.17, np.nan, np.nan]}, index=pd.Index(["PETR4", "BBAS3", "VALE3"], name="ticker"))
    ok = {"ok": True, "motivo": None, "gerado": "2026-10-19T08:40:00-03:00", "conferido_em": "2026-10-19T08:40:02-03:00",
          "sem_tir": {"ENEV3": "fora da TIR nova: sem preco-alvo"}}
    arq = str(tmp_path / "tir_diaria.jsonl")
    assert tir_diaria.registrar("2026-10-19", t, ok, arq=arq) == 2                # BBAS3 sem TIR fica de fora
    assert tir_diaria.registrar("2026-10-19", t, ok, arq=arq) == 2                # repetir o dia substitui
    recusa = {"ok": False, "motivo": "o recalculo da TIR no terminal falhou: codigo 1", "gerado": None, "conferido_em": "2026-10-20T08:40:00-03:00"}
    assert tir_diaria.registrar("2026-10-20", t, recusa, arq=arq) == 0            # dia recusado: nenhum numero, mesmo com a tabela cheia
    linhas = [json.loads(x) for x in open(arq, encoding="utf-8")]
    assert [x["dia"] for x in linhas] == ["2026-10-19", "2026-10-20"]
    assert linhas[0]["papeis"]["PETR4"] == [10.33, 3.43, "analistas", 1.17] and linhas[0]["papeis"]["VALE3"][3] is None
    assert linhas[0]["sem_tir"] == {"ENEV3": "fora da TIR nova: sem preco-alvo"} and linhas[0]["recusada"] is None
    assert linhas[1]["ok"] is False and linhas[1]["papeis"] == {} and "codigo 1" in linhas[1]["recusada"]
    assert tir_diaria.registrar("2026-10-21", t, None, arq=arq) == 0 and len(open(arq).readlines()) == 2    # sem terminal: nao grava

import json
import os
from datetime import date

import pandas as pd
import pytest

from quant.dados import calendario_eua as ce


@pytest.fixture
def pasta(tmp_path):
    csv = tmp_path / "bls.csv"
    csv.write_text("data;hora_ny;divulgacao;fonte\n2024-01-05;08:30;Employment Situation;x\n2024-01-11;08:30;Consumer Price Index;x\n"
                   "2024-01-11;08:30;Real Earnings;x\n2024-01-12;08:30;Producer Price Index;x\n2024-01-17;08:30;Import and Export Price Indexes;x\n",
                   encoding="utf-8")
    ff = tmp_path / "ff"
    ff.mkdir()
    (ff / "ff_calendar_thisweek_2026-10-12.json").write_text(json.dumps([
        {"title": "CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High", "forecast": "0.6%", "previous": "0.4%"},
        {"title": "Bank Holiday", "country": "JPY", "date": "2026-10-11T19:00:00-04:00", "impact": "Holiday", "forecast": "", "previous": ""}]))
    (ff / "ff_calendar_thisweek_2026-10-19.json").write_text(json.dumps([
        {"title": "CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High", "forecast": "0.6%", "previous": "0.4%", "actual": "0.8%"}]))
    return {"csv": str(csv), "ff": str(ff)}


def test_claims_na_quinta_e_quarta_no_feriado():
    dias = set(ce.claims_dias(2024, 2024))
    assert date(2024, 1, 4) in dias                       # quinta comum
    assert date(2024, 11, 27) in dias and date(2024, 11, 28) not in dias   # Thanksgiving (quinta 28/11): adiantado para quarta
    assert date(2024, 7, 3) in dias and date(2024, 7, 4) not in dias       # 4 de julho caiu numa quinta
    assert all(d.weekday() in (2, 3) for d in dias)


def test_tipo_do_dia_prioridade_e_claims(pasta):
    mapa = ce.tipos_por_dia(arq=pasta["csv"])
    assert ce.tipo_do_dia(date(2024, 1, 5), mapa) == "payroll"
    assert ce.tipo_do_dia(date(2024, 1, 11), mapa) == "cpi"          # Real Earnings nao muda o tipo
    assert ce.tipo_do_dia(date(2024, 1, 12), mapa) == "ppi"
    assert ce.tipo_do_dia(date(2024, 1, 17), mapa) == "outro_bls"
    assert ce.tipo_do_dia(date(2024, 1, 18), mapa) == "claims"       # quinta sem BLS
    assert ce.tipo_do_dia(date(2024, 1, 16), mapa) == "nenhum"       # terca sem nada conhecido


def test_divulgacoes_filtra_periodo(pasta):
    d = ce.divulgacoes(date(2024, 1, 10), date(2024, 1, 12), arq=pasta["csv"])
    assert set(d["tipo"]) == {"cpi", "ppi", "claims"}
    assert list(d.columns) == ["data", "tipo", "divulgacao", "fonte"]


def test_consenso_ff_vale_o_arquivo_mais_novo_e_surpresa(pasta):
    evs = ce.consenso_ff(date(2026, 10, 14), pasta=pasta["ff"])
    assert len(evs) == 1 and evs[0]["actual"] == "0.8%"
    assert abs(ce.surpresa_ff(evs[0]) - 0.2) < 1e-9
    assert ce.surpresa_ff({"actual": "150K", "forecast": "140K"}) == 10_000.0
    assert ce.surpresa_ff({"actual": "", "forecast": "1"}) is None
    assert ce.consenso_ff(date(2026, 10, 11), pasta=pasta["ff"]) == []     # JPY fica de fora


def test_efetivos_e_surpresa_ingenua(tmp_path, monkeypatch):
    arq = tmp_path / "bls.json"
    arq.write_text(json.dumps({"Results": {"series": [{"seriesID": "CES0000000001", "data": [
        {"year": "2024", "period": "M03", "value": "1030"}, {"year": "2024", "period": "M02", "value": "1000"},
        {"year": "2024", "period": "M01", "value": "990"}, {"year": "2023", "period": "M13", "value": "9999"}]}]}}))
    monkeypatch.setattr(ce, "ARQS_EFETIVOS", (str(arq),))
    s = ce.efetivos("payroll")
    assert list(s.index) == [pd.Timestamp(2024, 1, 1), pd.Timestamp(2024, 2, 1), pd.Timestamp(2024, 3, 1)]
    assert ce.surpresa_ingenua("payroll", "2024-03-01") == 20.0       # variacao 30 contra 10 do mes anterior
    assert ce.surpresa_ingenua("payroll", "2024-02-01") is None
    assert ce.efetivos("nao_existe").empty


def test_arquivos_reais_existem_e_batem_com_datas_conhecidas():
    if not os.path.exists(ce.ARQ_BLS):
        pytest.skip("sem a copia do calendario do BLS")
    mapa = ce.tipos_por_dia()
    for d in (date(2024, 1, 5), date(2024, 8, 2), date(2025, 2, 7)):
        assert ce.tipo_do_dia(d, mapa) == "payroll"
    assert ce.tipo_do_dia(date(2025, 3, 12), mapa) == "cpi"
    assert ce.tipo_do_dia(date(2026, 10, 14), mapa) == "cpi"

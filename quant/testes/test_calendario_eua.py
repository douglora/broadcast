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


# --- calendario do MetaTrader (12/10/2026) -------------------------------------------------------------------------------
COLS_MT5 = ("hora_servidor;valor_id;evento_id;codigo;nome;setor;importancia;unidade;digitos;multiplicador;modo_hora;frequencia;"
            "efetivo;consenso;anterior;anterior_revisado;impacto")


def _mt5(tmp_path, linhas):
    arq = tmp_path / "autopilot_calendario_US_teste.csv"
    arq.write_text(COLS_MT5 + "\n" + "\n".join(linhas) + "\n", encoding="cp1252")
    return str(arq)


def _linha(hora, codigo, efetivo, consenso, imp=3, i=1):
    return f"{hora};{i};{i};{codigo};{codigo};1;{imp};0;1;1;0;2;{efetivo};{consenso};;;0"


def test_marco_segue_o_verao_dos_eua():
    assert ce.verao_eua("2024-04-05") and not ce.verao_eua("2024-01-05")
    assert ce.marco_brt("2024-04-05") == "09:30" and ce.marco_brt("2024-01-05") == "10:30"


def test_mt5_converte_o_fuso_fixo_do_servidor_para_brasilia(tmp_path):
    arq = _mt5(tmp_path, [_linha("2024.01.05 16:30", "nonfarm-payrolls", 216, 170), _linha("2024.04.05 15:30", "nonfarm-payrolls", 303, 176, i=2),
                          _linha("2024.04.05 17:00", "ism-manufacturing-pmi", 50, 49, i=3)])
    df = ce.carregar_mt5(arq)
    assert list(df.hora_brt) == ["10:30", "09:30", "11:00"]
    ev = ce.eventos_830(df)
    assert list(ev.codigo) == ["nonfarm-payrolls", "nonfarm-payrolls"]      # o ISM das 10h de NY fica de fora do marco


def test_surpresa_z_robusta_e_sinal_do_dolar(tmp_path):
    # 7 quintas de pedidos de auxilio: surpresas passadas de |5| a |35| mil; a 8a surpreende em +40 mil (mais pedidos = dolar mais fraco)
    linhas = [_linha(f"2024.0{m}.{d:02d} 15:30", "initial-jobless-claims", 220 + s, 220, i=k) for k, (m, d, s) in
              enumerate([(4, 4, 5), (4, 11, -10), (4, 18, 15), (4, 25, -20), (5, 2, 25), (5, 9, -30), (5, 16, 35)], start=1)]
    linhas.append(_linha("2024.05.23 15:30", "initial-jobless-claims", 260, 220, i=8))
    sp = ce.surpresas(ce.eventos_830(ce.carregar_mt5(_mt5(tmp_path, linhas))))
    ultimo = sp.iloc[-1]
    assert ultimo.surpresa == 40
    assert abs(ultimo.z - 40 / (1.4826 * 20)) < 1e-6                      # mediana de |5,10,15,20,25,30,35| = 20
    assert sp.z.iloc[:ce.MIN_HIST_Z - 1].isna().all()                      # sem historico suficiente, sem z
    t = ce.tabela_surpresa_dia(sp)
    assert t.loc["2024-05-23", "S"] < 0 and t.loc["2024-05-23", "tipo_principal"] == "claims"


def test_tabela_surpresa_dia_prioriza_o_payroll(tmp_path):
    linhas = [_linha(f"2024.0{m}.{d:02d} 15:30", "initial-jobless-claims", 220, 220, i=k) for k, (m, d) in enumerate([(4, 4), (4, 11), (4, 18), (4, 25), (5, 2), (5, 9)], start=1)]
    linhas += [_linha("2024.05.03 15:30", "nonfarm-payrolls", 175, 240, i=20), _linha("2024.05.03 15:30", "initial-jobless-claims", 230, 220, i=21)]
    t = ce.tabela_surpresa_dia(ce.eventos_830(ce.carregar_mt5(_mt5(tmp_path, linhas))))
    assert t.loc["2024-05-03", "tipo_principal"] == "payroll" and t.loc["2024-05-03", "n_eventos"] == 2



def test_surpresa_pelo_livro_do_terminal(tmp_path):
    """Livro do terminal (itens[indicador] = [dia, consenso, efetivo, surpresa, fonte]): mesma escala robusta, sinal do dolar."""
    import json
    hist = [[f"2024-0{m}-{d:02d}", 220, 220 + s, s, "teste"] for (m, d, s) in [(4, 4, 5), (4, 11, -10), (4, 18, 15), (4, 25, -20), (5, 2, 25), (5, 9, -30), (5, 16, 35)]]
    hist.append(["2024-05-23", 220, 260, 40, "teste"])
    arq = tmp_path / "surpresas.json"
    arq.write_text(json.dumps({"v": 1, "itens": {"pedidos_seguro": hist, "ipca_mes": [["2026-10-09", 0.6, 0.82, 0.22, "Focus"]]}}))
    t = ce.surpresa_terminal_por_dia(str(arq))
    assert list(t.index.strftime("%Y-%m-%d")) == ["2024-05-16", "2024-05-23"]   # so a partir da 7a observacao (6 anteriores no minimo)
    assert t.loc["2024-05-23", "S"] == pytest.approx(-40 / (1.4826 * 20)) and t.loc["2024-05-23", "tipo_principal"] == "claims"
    assert ce.surpresa_terminal_por_dia(str(tmp_path / "nao_existe.json")).empty

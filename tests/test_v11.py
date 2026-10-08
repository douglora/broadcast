"""Regras v1.1: tecnicas (T02/T06/T07/T09/T10/T11/T12), curvas (C02/C03/C06/C08),
fx/commodity (F02/F04/F05), agenda e macro (E01/E02/M01/M03)."""
import json
import math
from datetime import date

import pandas as pd

from livro import indicadores as ind
from livro.fontes import agenda, bcb
from livro.sinais import curvas, eventos_macro, fx_commod, tecnicas2
from livro.sinais.base import Contexto, Estado
from tests.test_sinais import contexto, serie


def serie_vol(valores, volumes, fim="2026-09-18"):
    datas = pd.bdate_range(end=fim, periods=len(valores))
    return ind.para_df([[d.date().isoformat(), v, v, v, v, v, vol] for d, v, vol in zip(datas, valores, volumes)])


def test_t02_perde_mm50_e_mm100_acima_da_mm200(universo, limiares):
    vals = [80 + i * 0.1 for i in range(200)] + [104.0] * 40 + [98.0, 97.5]   # MM50 ~103, MM100 ~100, MM200 ~94
    ctx = contexto(universo, limiares, {"ITUB4": serie(vals)})
    al = tecnicas2.T02MM50100().avaliar(ctx, Estado())
    assert al and al[0].regra == "T02" and "perdeu a MM50" in al[0].titulo and "MM100" in al[0].titulo
    assert al[0].severidade == "atencao" and "acima da MM200" in al[0].titulo


def test_t06_acumulado_5_sessoes(universo, limiares):
    vals = [100.0 + (i % 5) * 0.05 for i in range(60)] + [101, 103, 105, 107, 109]
    ctx = contexto(universo, limiares, {"PETR4": serie(vals)})
    al = tecnicas2.T06Acumulado().avaliar(ctx, Estado())
    assert al and al[0].regra == "T06" and "5 sessões" in al[0].titulo and al[0].severidade in ("atencao", "critico")


def test_t07_rsi_entra_em_sobrecomprado_uma_vez(universo, limiares):
    vals = [100 + (0.5 if i % 2 else -0.5) for i in range(30)] + [100 + i * 1.5 for i in range(1, 12)]
    r = ind.rsi_wilder(serie(vals)["adj"], 14).tolist()
    corte = max(i for i in range(1, len(r)) if r[i - 1] < 75 <= r[i])   # a ultima barra e a entrada
    ctx = contexto(universo, limiares, {"MU": serie(vals[: corte + 1])})
    est = Estado()
    al = tecnicas2.T07RSI().avaliar(ctx, est)
    assert al and al[0].tag == "sobrecomprado" and al[0].severidade == "info"
    assert tecnicas2.T07RSI().avaliar(ctx, est) == []


def test_t09_volume_anormal_com_preco(universo, limiares):
    vals = [50.0] * 40 + [52.0]
    vols = [1_000_000] * 40 + [4_000_000]
    ctx = contexto(universo, limiares, {"VALE3": serie_vol(vals, vols)})
    al = tecnicas2.T09Volume().avaliar(ctx, Estado())
    assert al and "volume 4,0x" in al[0].titulo and al[0].severidade == "atencao"
    # UCITS nao entra (bloco excluido)
    ctx2 = contexto(universo, limiares, {"VWRA": serie_vol(vals, vols)})
    assert tecnicas2.T09Volume().avaliar(ctx2, Estado()) == []


def test_t10_forca_relativa_no_extremo(universo, limiares):
    bench = [100.0 + i * 0.1 for i in range(120)]
    ativo = [100.0 + i * 0.1 for i in range(100)] + [110 + i * 1.2 for i in range(20)]
    ctx = contexto(universo, limiares, {"ITUB4": serie(ativo), "IBOV": serie(bench)})
    al = tecnicas2.T10ForcaRelativa().avaliar(ctx, Estado())
    assert al and al[0].tag == "máximo" and "IBOV" in al[0].titulo


def test_t11_par_descola_por_dois_dias(universo, limiares):
    import random
    random.seed(7)
    base = [100.0]
    for _ in range(320):
        base.append(base[-1] * (1 + random.gauss(0, 0.01)))
    a = list(base)
    b = list(base)
    for i in range(1, 25):       # PETR4 sobe 25% a mais que o Brent em 24 sessoes
        a[-i] = a[-i] * (1 + 0.012 * (25 - i))
    ctx = contexto(universo, limiares, {"PETR4": serie(a), "BRENT": serie(b)})
    al = tecnicas2.T11Pares().avaliar(ctx, Estado())
    assert al and al[0].ativo == "PETR4" and "descolou à frente de" in al[0].titulo and "BRENT" in al[0].ativos_afetados


def test_t11_pares_de_setor_nao_chama_todo_mundo_de_banco(universo, limiares):
    """23/09: o alerta 'META descolou a frente de GOOGL' saiu com o texto 'dois bancos
    com o mesmo balanco macro'. Dos 8 pares `pares_setor` do config, so 2 sao bancos;
    os outros sao semis e plataformas."""
    import random
    random.seed(11)
    base = [100.0]
    for _ in range(320):
        base.append(base[-1] * (1 + random.gauss(0, 0.01)))
    a, b = list(base), list(base)
    for i in range(1, 25):
        a[-i] = a[-i] * (1 + 0.012 * (25 - i))
    ctx = contexto(universo, limiares, {"META": serie(a), "GOOGL": serie(b)})
    al = tecnicas2.T11Pares().avaliar(ctx, Estado())
    assert al and al[0].ativo == "META"
    assert "banco" not in al[0].por_que.lower(), al[0].por_que
    assert "mesmo setor" in al[0].por_que


def test_t12_sequencia_de_8_altas(universo, limiares):
    vals = [100.0] * 20 + [100 + i * 0.5 for i in range(1, 9)]
    ctx = contexto(universo, limiares, {"KO": serie(vals)})
    al = tecnicas2.T12Sequencia().avaliar(ctx, Estado())
    assert al and "8 altas seguidas" in al[0].titulo and al[0].severidade == "atencao"


def _di(hist_por_codigo, ultimo="2026-09-18"):
    return {"historico": hist_por_codigo, "ultimo_pregao": ultimo}


def test_c02_inclinacao_bear_steepening(universo, limiares):
    datas = [d.date().isoformat() for d in pd.bdate_range(end="2026-09-18", periods=30)]
    f28 = [[d, 13.60, 85000.0] for d in datas]
    f35 = [[d, 14.00, 33000.0] for d in datas[:-1]] + [[datas[-1], 14.15, 32900.0]]   # +15 bps no longo
    f30 = [[d, 13.90, 65000.0] for d in datas]
    ctx = contexto(universo, limiares, {}, curvas_={"di": _di({"DI1F28": f28, "DI1F35": f35, "DI1F30": f30})})
    al = curvas.C02Inclinacao().avaliar(ctx, Estado())
    assert al and "F35-F28 +15 bps no dia: bear steepening" in al[0].titulo and al[0].severidade == "atencao"


def test_c03_di_cruza_nivel_redondo(universo, limiares):
    datas = [d.date().isoformat() for d in pd.bdate_range(end="2026-09-18", periods=30)]
    f28 = [[d, 13.45, 85000.0] for d in datas[:-1]] + [[datas[-1], 13.56, 84900.0]]
    ctx = contexto(universo, limiares, {}, curvas_={"di": _di({"DI1F28": f28})})
    al = curvas.C03NiveisJuro().avaliar(ctx, Estado())
    assert al and "F28 cruzou 13,50%" in al[0].titulo and al[0].severidade == "atencao"


def test_c06_implicita_vs_focus(universo, limiares):
    bases = [d.date().isoformat() for d in pd.bdate_range(end="2026-09-17", periods=10)]
    pre = {"apelido": "Pre 2029", "historico": [[b, 13.80, 750.0, "compra"] for b in bases[:-1]] + [[bases[-1], 14.10, 745.0, "compra"]]}
    ipca = {"apelido": "IPCA+ 2029", "historico": [[b, 7.40, 3900.0, "compra"] for b in bases]}
    tes = {"data_base": bases[-1], "titulos": {"PRE2029": pre, "IPCA2029": ipca}}
    macro = {"focus": {"expectativas": {"IPCA": {"por_ano": {"2027": {"mediana": 4.3, "data": "2026-09-11"}}}}}}
    ctx = contexto(universo, limiares, {}, curvas_={"tesouro": tes}, macro=macro)
    al = curvas.C06Implicita().avaliar(ctx, Estado())
    assert al and "implícita 2029" in al[0].titulo and "bps na semana" in al[0].titulo and al[0].severidade == "atencao"
    assert any("Focus IPCA 2027" in l for l in al[0].corpo)


def test_c08_2s10s_inverte(universo, limiares):
    datas = [d.date().isoformat() for d in pd.bdate_range(end="2026-09-18", periods=12)]
    hist = [[d, 4.50, 4.60, 4.70, 5.00] for d in datas[:-1]] + [[datas[-1], 4.80, 4.75, 4.70, 5.00]]
    ctx = contexto(universo, limiares, {}, curvas_={"ust": {"historico": hist, "prazos": ["2y", "5y", "10y", "30y"]}})
    al = curvas.C082s10s().avaliar(ctx, Estado())
    assert al and "inverteu" in al[0].titulo and al[0].severidade == "atencao"


def test_f02_dxy_cruza_100(universo, limiares):
    vals = [99.0 + (i % 3) * 0.05 for i in range(220)] + [99.8, 100.9]
    ctx = contexto(universo, limiares, {"DXY": serie(vals), "USDBRL": serie([5.0] * 221 + [5.05])})
    al = fx_commod.F02DXY().avaliar(ctx, Estado())
    assert al and "cruzou 100" in al[0].titulo and al[0].severidade == "atencao" and "no dia" in al[0].titulo


def test_f04_minerio_queda_forte(universo, limiares):
    vals = [100.0] * 40 + [96.0]
    ctx = contexto(universo, limiares, {"MINERIO": serie(vals), "VALE3": serie([70.0] * 40 + [68.0])})
    al = fx_commod.F04Minerio().avaliar(ctx, Estado())
    assert al and "Minério de ferro cai" in al[0].titulo and "VALE3 -2,9%" in " ".join(al[0].corpo)


def test_f05_bhkp_proxy_e_manual(universo, limiares):
    datas = [d.date().isoformat() for d in pd.bdate_range(end="2026-09-18", periods=8)]
    hist = [[d, 4800.0] for d in datas[:-1]] + [[datas[-1], 4990.0]]
    macro = {"proxies": {"historico": {"SHFE_SP": hist},
                         "bhkp_semanal": {"valor": 620, "data": "2026-09-15", "fonte": "PIX BHKP Europe"},
                         "bhkp_anterior": {"valor": 595, "data": "2026-09-08"}}}
    ctx = contexto(universo, limiares, {}, macro=macro)
    al = fx_commod.F05BHKP().avaliar(ctx, Estado())
    assert len(al) == 2 and any("proxy SHFE" in a.titulo for a in al) and any(a.severidade == "atencao" and "BHKP sobe US$ 25/t" in a.titulo for a in al)


def test_agenda_parse_e_consolidar(universo):
    from datetime import datetime, timezone
    ep = lambda y, m, d: int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())
    payload = {"quoteSummary": {"result": [{"calendarEvents": {"earnings": {"earningsDate": [{"raw": ep(2026, 9, 30)}], "isEarningsDateEstimate": False},
                                                                 "exDividendDate": {"raw": ep(2026, 9, 25)}, "dividendDate": {"raw": ep(2026, 10, 20)}},
                                              "defaultKeyStatistics": {"lastDividendValue": {"raw": 0.115}, "lastDividendDate": {"raw": ep(2026, 6, 25)}}}]}}
    p = agenda.parse_quote_summary(payload)
    assert p["resultado_datas"] == ["2026-09-30"] and p["ex_dividendo"] == "2026-09-25" and p["ultimo_dividendo"] == 0.115
    cal = {"resultados": [{"ticker": "MU", "data": "2026-09-30", "quando": "apos_ny", "confirmado": True, "fonte": "RI"},
                          {"ticker": "KO", "data": "2026-10-27", "quando": "antes_ny", "confirmado": False}]}
    por_ativo = {"MU": p, "KO": {"resultado_datas": ["2026-10-21"], "resultado_estimado": True, "ex_dividendo": None},
                 "NVDA": {"resultado_datas": ["2026-11-25"], "resultado_estimado": True, "ex_dividendo": "2026-10-02", "ultimo_dividendo": 0.01}}
    c = agenda.consolidar(cal, por_ativo, date(2026, 9, 18), universo, horizonte_dias=90)
    por = {r["ticker"]: r for r in c["resultados"]}
    assert por["MU"]["confirmado"] and por["MU"]["fonte"] == "RI"
    assert por["KO"]["data"] == "2026-10-27" and "Yahoo indica 21/10" in por["KO"]["nota"]
    assert por["NVDA"]["fonte"].startswith("Yahoo") and not por["NVDA"]["confirmado"]
    assert c["ex_dividendos"] and c["ex_dividendos"][0]["ticker"] == "MU" and c["ex_dividendos"][0]["moeda"] == "US$"


def test_e01_e02_m01_m03(universo, limiares):
    ag = {"resultados": [{"ticker": "MU", "data": "2026-09-21", "quando": "apos_ny", "confirmado": True, "fonte": "RI"},
                         {"ticker": "JPM", "data": "2026-09-23", "quando": "antes_ny", "confirmado": True, "fonte": "RI"}],
          "ex_dividendos": [{"ticker": "KO", "data": "2026-09-21", "valor": 0.51, "moeda": "US$", "pagamento": "2026-10-01"}]}
    cal = {"eventos_macro": [{"data": "2026-09-18", "hora_brt": "09:00", "evento": "IPCA-15 de setembro (IBGE)", "pais": "BR"},
                             {"data": "2026-09-21", "hora_brt": "08:25", "evento": "Relatorio Focus (BCB)", "pais": "BR"}]}
    macro = {"focus": {"expectativas": {"IPCA": {"por_ano": {"2026": {"mediana": 4.9, "data": "2026-09-18", "anterior": {"mediana": 4.75, "data": "2026-09-11"}},
                                                             "2027": {"mediana": 4.3, "data": "2026-09-18", "anterior": {"mediana": 4.3, "data": "2026-09-11"}}}},
                                        "Selic": {"por_ano": {"2026": {"mediana": 14.5, "data": "2026-09-18", "anterior": {"mediana": 14.5, "data": "2026-09-11"}}}},
                                        "Cambio": {"por_ano": {"2026": {"mediana": 5.2, "data": "2026-09-18", "anterior": {"mediana": 5.25, "data": "2026-09-11"}}}}}}}
    vals = [100.0 + (i % 4) * 0.3 for i in range(60)]
    ctx = contexto(universo, limiares, {"MU": serie(vals), "KO": serie([60.0] * 60)}, macro=macro)
    ctx.eventos = {"agenda": ag, "calendario": cal}
    e01 = eventos_macro.E01Resultado().avaliar(ctx, Estado())
    ids = {a.id: a for a in e01}
    assert "E01-MU-D-1-2026-09-18" in ids and ids["E01-MU-D-1-2026-09-18"].severidade == "atencao"
    assert "E01-JPM-D-3-2026-09-18" in ids and ids["E01-JPM-D-3-2026-09-18"].severidade == "info"
    assert any("movimento típico" in l for l in ids["E01-MU-D-1-2026-09-18"].corpo) and any("Consenso: não disponível" in l for l in ids["E01-MU-D-1-2026-09-18"].corpo)
    e02 = eventos_macro.E02ExDividendo().avaliar(ctx, Estado())
    assert e02 and "KO" in e02[0].titulo and "US$ 0,51" in e02[0].titulo and "0,85%" in e02[0].titulo
    m01 = eventos_macro.M01AgendaMacro().avaliar(ctx, Estado())
    t = {a.tag[:2]: a for a in m01}
    assert "D0" in t and t["D0"].severidade == "atencao" and "IPCA-15" in t["D0"].titulo
    assert "D-" in t and t["D-"].severidade == "info"
    est = Estado()
    m03 = eventos_macro.M03Focus().avaliar(ctx, est)
    assert m03 and m03[0].severidade == "atencao" and "IPCA: 2026 4,90% (+15 bps)" in m03[0].titulo and "Câmbio" in " ".join(m03[0].corpo)
    assert eventos_macro.M03Focus().avaliar(ctx, est) == []


def test_focus_guarda_pesquisa_anterior():
    rows = [{"DataReferencia": 2026, "Mediana": 4.9, "Data": "2026-09-18", "Media": 4.88, "numeroRespondentes": 100},
            {"DataReferencia": 2026, "Mediana": 4.9, "Data": "2026-09-18"},
            {"DataReferencia": 2026, "Mediana": 4.75, "Data": "2026-09-11"},
            {"DataReferencia": 2027, "Mediana": 4.3, "Data": "2026-09-18"}]
    f = bcb.parse_focus(rows, "IPCA")
    assert f["por_ano"]["2026"]["anterior"] == {"mediana": 4.75, "data": "2026-09-11"} and f["por_ano"]["2027"]["anterior"] is None

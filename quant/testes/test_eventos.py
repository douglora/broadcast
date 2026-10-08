import json
import math

import numpy as np
import pandas as pd

from quant.dados import eventos as ev

# pregoes de marco/2024 (sem feriado): 1, 4-8, 11-15
DATAS = ["2024-03-01", "2024-03-04", "2024-03-05", "2024-03-06", "2024-03-07", "2024-03-08",
         "2024-03-11", "2024-03-12", "2024-03-13", "2024-03-14", "2024-03-15"]
FEC = [40.0, 41.0, 42.0, 41.5, 43.0, 42.0, 44.0, 45.0, 44.5, 46.0, 47.0]


def _precos(ticker="PETR4", datas=DATAS, fec=FEC):
    return pd.DataFrame({"ticker": ticker, "data": pd.to_datetime(datas), "fec": fec})


def _evento(ticker="PETR4", tipo="DIVIDENDO", data_com="2024-03-05", valor=float("nan"), fator=float("nan"),
            fonte="teste"):
    dc = pd.Timestamp(data_com)
    return pd.DataFrame([{"ticker": ticker, "tipo": tipo, "data_com": dc, "data_ex": ev.data_ex_de(dc),
                          "valor": valor, "fator": fator, "data_aprov": pd.NaT, "fonte": fonte,
                          "carimbo": "t", "obs": ""}])


def _ret(df, data):
    return df[df["data"] == pd.Timestamp(data)].iloc[0]


# ─────────────────────────────────────────────────────────────
# Retorno total
# ─────────────────────────────────────────────────────────────
def test_sem_eventos_ret_total_igual_ret_preco():
    r = ev.retorno_total(_precos(), None)
    assert list(r.columns) == ["ticker", "data", "ret_preco", "ret_total", "fator_acum"]
    assert np.isnan(r.iloc[0]["ret_preco"]) and r.iloc[0]["fator_acum"] == 1.0
    assert np.allclose(r["ret_total"].iloc[1:], r["ret_preco"].iloc[1:])
    assert abs(r.iloc[-1]["fator_acum"] - FEC[-1] / FEC[0]) < 1e-12


def test_dividendo_reinvestido_no_fechamento_da_data_ex():
    d = 1.5
    r = ev.retorno_total(_precos(), _evento(tipo="DIVIDENDO", data_com="2024-03-05", valor=d))
    x = _ret(r, "2024-03-06")                      # data-ex = pregao seguinte a data-com
    assert abs(x["ret_total"] - ((41.5 + d) / 42.0 - 1)) < 1e-12
    assert abs(x["ret_preco"] - (41.5 / 42.0 - 1)) < 1e-12
    # nenhum outro dia muda
    outros = r[r["data"] != pd.Timestamp("2024-03-06")]
    assert np.allclose(outros["ret_total"].iloc[1:], outros["ret_preco"].iloc[1:])


def test_desdobramento_1_para_2():
    r = ev.retorno_total(_precos(), _evento(tipo="DESDOBRAMENTO", data_com="2024-03-05", fator=2.0))
    x = _ret(r, "2024-03-06")
    assert abs(x["ret_total"] - (2 * 41.5 / 42.0 - 1)) < 1e-12


def test_bonificacao_10_por_cento_e_grupamento():
    r = ev.retorno_total(_precos(), _evento(tipo="BONIFICACAO", data_com="2024-03-05", fator=1.10))
    assert abs(_ret(r, "2024-03-06")["ret_total"] - (1.1 * 41.5 / 42.0 - 1)) < 1e-12
    r = ev.retorno_total(_precos(), _evento(tipo="GRUPAMENTO", data_com="2024-03-05", fator=0.1))
    assert abs(_ret(r, "2024-03-06")["ret_total"] - (0.1 * 41.5 / 42.0 - 1)) < 1e-12


def test_point_in_time_evento_futuro_nao_altera_passado():
    base = ev.retorno_total(_precos(), _evento(tipo="DIVIDENDO", data_com="2024-03-05", valor=1.0))
    futuro = _evento(tipo="DESDOBRAMENTO", data_com="2024-03-12", fator=2.0)      # data-ex 13/03
    com = ev.retorno_total(_precos(), pd.concat([_evento(tipo="DIVIDENDO", data_com="2024-03-05", valor=1.0), futuro]))
    t = pd.Timestamp("2024-03-12")
    a, b = base[base["data"] <= t].reset_index(drop=True), com[com["data"] <= t].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    assert _ret(com, "2024-03-13")["ret_total"] != _ret(base, "2024-03-13")["ret_total"]
    # evento alem do ultimo preco e simplesmente ignorado (ainda nao aconteceu)
    depois = ev.retorno_total(_precos(), _evento(tipo="DIVIDENDO", data_com="2024-03-20", valor=9.0))
    pd.testing.assert_frame_equal(depois, ev.retorno_total(_precos(), None))


def test_jcp_liquido_aplica_15_por_cento():
    e = _evento(tipo="JCP", data_com="2024-03-05", valor=1.0)
    bruto = _ret(ev.retorno_total(_precos(), e, jcp_liquido=False), "2024-03-06")["ret_total"]
    liq = _ret(ev.retorno_total(_precos(), e, jcp_liquido=True), "2024-03-06")["ret_total"]
    assert abs(bruto - ((41.5 + 1.0) / 42.0 - 1)) < 1e-12
    assert abs(liq - ((41.5 + 0.85) / 42.0 - 1)) < 1e-12
    # dividendo nao sofre IR
    d = _evento(tipo="DIVIDENDO", data_com="2024-03-05", valor=1.0)
    assert _ret(ev.retorno_total(_precos(), d, jcp_liquido=True), "2024-03-06")["ret_total"] == bruto


def test_varios_eventos_na_mesma_data_ex_se_compoem():
    e = pd.concat([_evento(tipo="DIVIDENDO", data_com="2024-03-05", valor=1.0),
                   _evento(tipo="JCP", data_com="2024-03-05", valor=0.5),
                   _evento(tipo="DESDOBRAMENTO", data_com="2024-03-05", fator=2.0),
                   _evento(tipo="SUBSCRICAO", data_com="2024-03-05", valor=30.0)])      # ignorada
    x = _ret(ev.retorno_total(_precos(), e), "2024-03-06")
    assert abs(x["ret_total"] - ((41.5 * 2 + 1.5) / 42.0 - 1)) < 1e-12


def test_data_ex_sem_cotacao_cai_no_proximo_preco_e_varios_tickers():
    p = pd.concat([_precos("AAAA3"), _precos("BBBB3", DATAS[:3] + DATAS[5:], FEC[:3] + FEC[5:])])
    e = pd.concat([_evento("AAAA3", "DIVIDENDO", "2024-03-05", valor=1.0),
                   _evento("BBBB3", "DIVIDENDO", "2024-03-05", valor=1.0)])   # BBBB3 nao cotou em 06 e 07/03
    r = ev.retorno_total(p, e)
    a = r[r["ticker"] == "AAAA3"]
    b = r[r["ticker"] == "BBBB3"]
    assert abs(_ret(a, "2024-03-06")["ret_total"] - ((41.5 + 1) / 42 - 1)) < 1e-12
    assert abs(_ret(b, "2024-03-08")["ret_total"] - ((42.0 + 1) / 42 - 1)) < 1e-12
    assert len(r) == len(p)


# ─────────────────────────────────────────────────────────────
# Parsers das fontes (fixtures no formato documentado)
# ─────────────────────────────────────────────────────────────
B3_DIVIDENDOS = {
    "page": {"pageNumber": 1, "pageSize": 120, "totalRecords": 3, "totalPages": 1},
    "results": [
        {"typeStock": "PN", "dateApproval": "07/03/2024", "valueCash": "1.234,56", "ratio": "1,00000000000",
         "lastDatePriorEx": "05/03/2024", "closingPricePriorExDate": "42,00", "paymentDate": "20/05/2024",
         "relatedTo": "4º Trimestre/2023", "label": "JRS CAP PROPRIO"},
        {"typeStock": "PN", "dateApproval": "07/03/2024", "valueCash": "1.234,56", "ratio": "1,00000000000",
         "lastDatePriorEx": "05/03/2024", "closingPricePriorExDate": "42,00", "paymentDate": "20/05/2024",
         "relatedTo": "4º Trimestre/2023", "label": "JRS CAP PROPRIO"},                  # duplicata
        {"typeStock": "ON", "dateApproval": "07/03/2024", "valueCash": "0,50", "ratio": "1,00000000000",
         "lastDatePriorEx": "05/03/2024", "closingPricePriorExDate": "40,00", "paymentDate": "20/05/2024",
         "relatedTo": "4º Trimestre/2023", "label": "DIVIDENDO"},
        {"typeStock": "PN", "dateApproval": "12/03/2024", "valueCash": "0,731", "ratio": "1,00000000000",
         "lastDatePriorEx": "12/03/2024", "closingPricePriorExDate": "45,00", "paymentDate": "",
         "relatedTo": "", "label": "DIVIDENDO"},
    ],
}

B3_SUPLEMENTO = [{
    "tradingName": "PETROBRAS", "code": "PETR", "codeCVM": "9512",
    "stockDividends": [
        {"assetIssued": "BRPETRACNPR6", "factor": "100,00000000000", "approvedOn": "01/03/2024",
         "isinCode": "BRPETRACNPR6", "label": "DESDOBRAMENTO", "lastDatePrior": "05/03/2024", "remarks": ""},
        {"assetIssued": "BRPETRACNOR9", "factor": "100,00000000000", "approvedOn": "01/03/2024",
         "isinCode": "BRPETRACNOR9", "label": "DESDOBRAMENTO", "lastDatePrior": "05/03/2024", "remarks": ""},
        {"assetIssued": "BRPETRACNPR6", "factor": "10,00000000000", "approvedOn": "27/04/2023",
         "isinCode": "BRPETRACNPR6", "label": "BONIFICACAO", "lastDatePrior": "08/05/2023", "remarks": ""},
    ],
    "cashDividends": [
        {"assetIssued": "BRPETRACNPR6", "paymentDate": "20/05/2024", "rate": "1.234,56",
         "relatedTo": "4º Trimestre/2023", "approvedOn": "07/03/2024", "isinCode": "BRPETRACNPR6",
         "label": "JRS CAP PROPRIO", "lastDatePrior": "05/03/2024", "remarks": ""},
    ],
    "subscriptions": [
        {"assetIssued": "BRPETRACNPR6", "percentage": "10,00000000000", "priceUnit": "30,00",
         "tradingPeriod": "01/04/2024 a 30/04/2024", "subscriptionDate": "30/04/2024", "approvedOn": "20/03/2024",
         "isinCode": "BRPETRACNPR6", "label": "SUBSCRICAO", "lastDatePrior": "25/03/2024", "remarks": ""},
    ],
}]

STATUSINVEST = {
    "assetEarningsModels": [
        {"y": 2024, "m": 3, "d": 5, "ed": "05/03/2024", "pd": "20/05/2024", "et": "JCP", "etd": "Juros Sobre Capital Próprio",
         "v": 1234.56, "sv": "1.234,56", "adj": False, "sov": 1234.56},
        {"y": 2024, "m": 3, "d": 12, "ed": "12/03/2024", "pd": "-", "et": "Dividendo", "etd": "Dividendo",
         "v": 0.731, "sv": "0,731", "adj": False, "sov": 0.731},
        {"y": 2019, "m": 6, "d": 3, "ed": "03/06/2019", "pd": "28/06/2019", "et": "Dividendo", "etd": "Dividendo",
         "v": 0.05, "sv": "0,05", "adj": True, "sov": 0.10},                                    # ajustado: usa sov
        {"y": 2010, "m": 1, "d": 1, "ed": "", "pd": "", "et": "Dividendo", "etd": "", "v": 9.9, "adj": False},  # sem data-com
    ],
    "assetEarningsYearlyModels": [],
}


def test_normalizar_b3_dividendos_valores_br_datas_br_classe_e_duplicata():
    df = ev.normalizar_b3_dividendos(B3_DIVIDENDOS, "PETR4", carimbo="c")
    assert len(df) == 2                                          # duplicata removida e ON descartado
    jcp = df[df["tipo"] == "JCP"].iloc[0]
    assert jcp["valor"] == 1234.56 and jcp["data_com"] == pd.Timestamp("2024-03-05")
    assert jcp["data_ex"] == pd.Timestamp("2024-03-06") and jcp["data_aprov"] == pd.Timestamp("2024-03-07")
    assert jcp["fonte"] == "b3" and jcp["carimbo"] == "c" and math.isnan(jcp["fator"])
    div = df[df["tipo"] == "DIVIDENDO"].iloc[0]
    assert div["valor"] == 0.731 and div["data_ex"] == pd.Timestamp("2024-03-13")
    on = ev.normalizar_b3_dividendos(B3_DIVIDENDOS, "PETR3")
    assert len(on) == 1 and on.iloc[0]["valor"] == 0.5
    # JSON envolto em aspas (string de JSON), como a B3 devolve as vezes
    assert len(ev.normalizar_b3_dividendos(json.dumps(json.dumps(B3_DIVIDENDOS)), "PETR4")) == 2


def test_normalizar_b3_suplemento_fatores_e_filtro_por_isin():
    df = ev.normalizar_b3_suplemento(B3_SUPLEMENTO, "PETR4")
    tipos = df.set_index("tipo")
    assert set(df["tipo"]) == {"DESDOBRAMENTO", "BONIFICACAO", "JCP", "SUBSCRICAO"}
    assert tipos.loc["DESDOBRAMENTO", "fator"] == 2.0 and tipos.loc["DESDOBRAMENTO", "data_ex"] == pd.Timestamp("2024-03-06")
    assert abs(tipos.loc["BONIFICACAO", "fator"] - 1.10) < 1e-12
    assert tipos.loc["BONIFICACAO", "data_ex"] == pd.Timestamp("2023-05-09")
    assert tipos.loc["JCP", "valor"] == 1234.56 and math.isnan(tipos.loc["JCP", "fator"])
    assert tipos.loc["SUBSCRICAO", "valor"] == 30.0 and "percentual=10" in tipos.loc["SUBSCRICAO", "obs"]
    assert (df["fonte"] == "b3_suplemento").all()
    on = ev.normalizar_b3_suplemento(B3_SUPLEMENTO, "PETR3")
    assert len(on) == 1 and on.iloc[0]["tipo"] == "DESDOBRAMENTO"    # so o ISIN ...ACNOR...


def test_fator_de_convencao_percentual():
    assert ev.fator_de("DESDOBRAMENTO", "100,00000000000") == 2.0
    assert ev.fator_de("DESDOBRAMENTO", "700,00000000000") == 8.0            # MGLU3 2019: 1 -> 8
    assert abs(ev.fator_de("BONIFICACAO", "10,00000000000") - 1.10) < 1e-12
    assert abs(ev.fator_de("GRUPAMENTO", "90,00000000000") - 0.10) < 1e-12   # 90% retirado
    assert abs(ev.fator_de("GRUPAMENTO", "10") - 0.90) < 1e-12               # 10% retirado (convencao percentual)
    assert abs(ev.fator_de("GRUPAMENTO", "0,1") - 0.10) < 1e-12              # multiplicador pronto
    assert abs(ev.fator_de("GRUPAMENTO", "100") - 0.01) < 1e-12              # >= 100: razao N:1
    assert math.isnan(ev.fator_de("DIVIDENDO", "1,5"))


def test_normalizar_statusinvest():
    df = ev.normalizar_statusinvest(STATUSINVEST, "PETR4", carimbo="c")
    assert len(df) == 3                                           # sem data-com cai fora
    jcp = df[df["tipo"] == "JCP"].iloc[0]
    assert jcp["valor"] == 1234.56 and jcp["data_ex"] == pd.Timestamp("2024-03-06") and jcp["fonte"] == "statusinvest"
    antigo = df[df["data_com"] == pd.Timestamp("2019-06-03")].iloc[0]
    assert antigo["valor"] == 0.10                                # nominal original (sov), nao o ajustado
    assert "pagamento 28/06/2019" in antigo["obs"]
    assert len(ev.normalizar_statusinvest(json.dumps(STATUSINVEST), "PETR4")) == 3
    assert len(ev.normalizar_statusinvest("nao e json", "PETR4")) == 0


def test_valor_num_nao_confunde_float_com_milhar():
    assert ev.valor_num(1.234) == 1.234
    assert ev.valor_num("1.234") == 1234.0                        # texto no formato BR de milhar
    assert ev.valor_num("1.234,56") == 1234.56
    assert math.isnan(ev.valor_num(None)) and math.isnan(ev.valor_num(""))


def test_consolidar_une_b3_e_statusinvest_sem_duplicar():
    b3 = ev.normalizar_b3_dividendos(B3_DIVIDENDOS, "PETR4")
    sup = ev.normalizar_b3_suplemento(B3_SUPLEMENTO, "PETR4")
    si = ev.normalizar_statusinvest(STATUSINVEST, "PETR4")
    c = ev.consolidar(b3, sup, si)
    # JCP 05/03 esta nas tres fontes -> 1 linha, fonte b3; dividendo 12/03 em b3 e si -> 1 linha b3;
    # dividendo 2019 so no statusinvest -> entra; desdobro/bonificacao/subscricao so no suplemento -> entram
    assert len(c) == 6
    jcp = c[(c["tipo"] == "JCP")]
    assert len(jcp) == 1 and jcp.iloc[0]["fonte"] == "b3"
    assert c[c["tipo"] == "DIVIDENDO"]["fonte"].tolist() == ["statusinvest", "b3"]
    assert set(c[c["fonte"] == "b3_suplemento"]["tipo"]) == {"DESDOBRAMENTO", "BONIFICACAO", "SUBSCRICAO"}
    assert list(c.columns) == ev.COLUNAS
    # arredondamento diferente entre fontes (1,2346 x 1,23) ainda e o mesmo evento
    si2 = si.copy()
    si2.loc[si2["tipo"] == "JCP", "valor"] = 1234.0
    assert len(ev.consolidar(b3, si2)) == len(ev.consolidar(b3, si))
    # valores realmente diferentes na mesma data (dois dividendos) sao mantidos
    si3 = si.copy()
    si3.loc[si3["tipo"] == "JCP", "valor"] = 600.0
    assert len(ev.consolidar(b3, si3)) == len(ev.consolidar(b3, si)) + 1
    assert len(ev.consolidar()) == 0 and list(ev.consolidar(None).columns) == ev.COLUNAS


def test_curadoria_slce3_bonificacao_2023():
    cur = ev.carregar_curados()
    s = cur[(cur["ticker"] == "SLCE3") & (cur["tipo"] == "BONIFICACAO")]
    assert len(s) == 1
    r = s.iloc[0]
    assert abs(r["fator"] - 1.10) < 1e-12 and math.isnan(r["valor"])
    assert r["data_ex"] == pd.Timestamp("2023-05-09") and r["data_com"] == pd.Timestamp("2023-05-08")
    assert r["data_aprov"] == pd.Timestamp("2023-04-27") and r["fonte"] == "curadoria"
    # consolidar mantem a curadoria quando a B3 nao tem o evento, e prefere a B3 quando tem
    b3 = _evento("SLCE3", "BONIFICACAO", "2023-05-08", fator=1.10, fonte="b3_suplemento")
    c = ev.consolidar(b3, cur)
    assert len(c[c["ticker"] == "SLCE3"]) == 1 and c[c["ticker"] == "SLCE3"].iloc[0]["fonte"] == "b3_suplemento"
    assert ev.consolidar(cur)[lambda d: d["ticker"] == "SLCE3"].iloc[0]["fonte"] == "curadoria"


def test_tipo_de_e_data_ex_de():
    assert ev.tipo_de("JRS CAP PROPRIO") == "JCP" and ev.tipo_de("Juros Sobre Capital Próprio") == "JCP"
    assert ev.tipo_de("DIVIDENDO") == "DIVIDENDO" and ev.tipo_de("Dividendo") == "DIVIDENDO"
    assert ev.tipo_de("RENDIMENTO") == "RENDIMENTO" and ev.tipo_de("RESG TOTAL RV") == "OUTRO"
    assert ev.tipo_de("CIS RED CAP") == "OUTRO" and ev.tipo_de("INCORPORACAO") == "OUTRO"
    assert ev.data_ex_de("08/03/2024") == pd.Timestamp("2024-03-11")       # sexta -> segunda
    assert ev.data_ex_de("28/03/2024") == pd.Timestamp("2024-04-01")       # sexta-feira santa no meio
    assert pd.isna(ev.data_ex_de(""))


def test_gravar_e_carregar_parquet(tmp_path):
    c = ev.consolidar(ev.normalizar_b3_dividendos(B3_DIVIDENDOS, "PETR4"), ev.carregar_curados())
    caminho = str(tmp_path / "eventos.parquet")
    ev.gravar_eventos(c, caminho)
    lido = ev.carregar_eventos(caminho)
    assert len(lido) == len(c) and list(lido.columns) == ev.COLUNAS
    r = ev.retorno_total(_precos(), lido)
    assert abs(_ret(r, "2024-03-06")["ret_total"] - ((41.5 + 1234.56) / 42.0 - 1)) < 1e-9


def test_type_stock_com_segmento_e_rotulos_acentuados():
    # a B3 concatena o segmento de listagem ao typeStock ("PN N2"); sem isso TODAS as linhas cairiam fora
    obj = json.loads(json.dumps(B3_DIVIDENDOS))
    for r in obj["results"]:
        r["typeStock"] = {"PN": "PN N2", "ON": "ON NM"}[r["typeStock"]]
    assert len(ev.normalizar_b3_dividendos(obj, "PETR4")) == 2
    assert len(ev.normalizar_b3_dividendos(obj, "PETR3")) == 1
    assert ev._casa_classe("UNT N2", "SANB11") and ev._casa_classe("UNIT", "SANB11")
    assert not ev._casa_classe("PN N2", "PETR3")
    assert ev._casa_classe("", "PETR3") and ev._casa_classe("PN", "XXXXA")      # sem classe: aceita
    # bonificacao rotulada como "dividendo em acoes" e evento de QUANTIDADE, nao dinheiro
    assert ev.tipo_de("Dividendo em Ações") == "BONIFICACAO" and ev.tipo_de("DIVIDENDO EM ACOES") == "BONIFICACAO"
    assert ev.tipo_de("Bonificação") == "BONIFICACAO" and ev.tipo_de("Amortização") == "RENDIMENTO"
    assert ev.tipo_de("RESTITUICAO DE CAPITAL") == "RENDIMENTO"                # dinheiro: entra no retorno
    assert ev.tipo_de("Juros Sobre Capital Próprio") == "JCP"


def test_curados_ponto_decimal_nao_e_milhar(tmp_path):
    arq = tmp_path / "curados.csv"
    arq.write_text(
        "# comentario\n"
        "ticker;tipo;data_com;data_ex;valor;fator;data_aprov;fonte;carimbo;obs\n"
        "AAAA3;DESDOBRAMENTO;2024-03-05;;;2.000;;curadoria;t;desdobro 1:2 escrito com 3 casas\n"
        "AAAA3;DIVIDENDO;2024-03-05;;1.125;;;curadoria;t;\n"
        "AAAA3;BONIFICACAO;;2024-03-13;;1,10;;curadoria;t;virgula tambem vale\n", encoding="utf-8")
    c = ev.carregar_curados(str(arq))
    assert len(c) == 3
    assert c[c["tipo"] == "DESDOBRAMENTO"].iloc[0]["fator"] == 2.0          # nao 2000
    assert c[c["tipo"] == "DIVIDENDO"].iloc[0]["valor"] == 1.125
    assert c[c["tipo"] == "DESDOBRAMENTO"].iloc[0]["data_ex"] == pd.Timestamp("2024-03-06")
    b = c[c["tipo"] == "BONIFICACAO"].iloc[0]
    assert abs(b["fator"] - 1.10) < 1e-12 and b["data_com"] == pd.Timestamp("2024-03-12")   # pregao anterior
    assert (c["fonte"] == "curadoria").all()
    assert len(ev.carregar_curados(str(tmp_path / "nao_existe.csv"))) == 0


def test_preco_zero_ou_ausente_nao_contamina_fator_acum():
    p = _precos(fec=[40.0, 0.0, 42.0, float("nan"), 43.0, 42.0, 44.0, 45.0, 44.5, 46.0, 47.0])
    r = ev.retorno_total(p, _evento(tipo="DIVIDENDO", data_com="2024-03-05", valor=1.0))    # data-ex 06/03: sem preco
    assert len(r) == len(p) and np.isfinite(r["fator_acum"]).all()
    assert np.isnan(_ret(r, "2024-03-04")["ret_total"]) and np.isnan(_ret(r, "2024-03-06")["ret_total"])
    assert abs(_ret(r, "2024-03-05")["ret_total"] - (42.0 / 40.0 - 1)) < 1e-12        # base = ultimo preco valido
    # o dividendo cai no primeiro dia COM preco depois da data-ex, como quando a linha nao existe
    assert abs(_ret(r, "2024-03-07")["ret_total"] - ((43.0 + 1.0) / 42.0 - 1)) < 1e-12
    assert abs(_ret(r, "2024-03-07")["ret_preco"] - (43.0 / 42.0 - 1)) < 1e-12
    assert np.allclose(r["ret_total"].iloc[5:], r["ret_preco"].iloc[5:])
    assert abs(r.iloc[-1]["fator_acum"] - (44.0 / 40.0) * (47.0 / 43.0)) < 1e-12        # 40->42, 42->44 (43+1), 43->47


def test_suplemento_como_string_json_de_dict():
    s = json.dumps(B3_SUPLEMENTO[0])                       # dict sem 'results', em texto
    df = ev.normalizar_b3_suplemento(s, "PETR4")
    assert set(df["tipo"]) == {"DESDOBRAMENTO", "BONIFICACAO", "JCP", "SUBSCRICAO"}
    assert len(ev.normalizar_b3_suplemento(json.dumps(json.dumps(B3_SUPLEMENTO)), "PETR4")) == len(df)
    assert len(ev.normalizar_b3_suplemento("nao e json", "PETR4")) == 0
    assert len(ev.normalizar_b3_suplemento(None, "PETR4")) == 0

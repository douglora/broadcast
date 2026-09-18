import os

from livro.fontes import b3_di, bcb, sina, tesouro, ust, yahoo


def _ler(fixtures_dir, nome, binario=False):
    modo = "rb" if binario else "r"
    with open(os.path.join(fixtures_dir, "raw", nome), modo, **({} if binario else {"encoding": "utf-8"})) as f:
        return f.read()


def test_b3_parse_e_conversao(fixtures_dir):
    d = b3_di.parse_csv(_ler(fixtures_dir, "b3_amostra.csv"), ["DI1F28", "DI1F35"])
    assert set(d) == {"DI1F28", "DI1F35"}
    assert d["DI1F28"]["taxa"] == 13.42 and d["DI1F28"]["pu"] == 84712.55
    assert d["DI1F28"]["data"] == "2026-09-18"
    from livro import relogios
    du = relogios.dias_uteis_b3("2026-09-18", relogios.vencimento_di("DI1F28"))
    pu = 100000.0 / ((1 + 0.1342) ** (du / 252.0))
    assert abs(b3_di.taxa_de_pu(pu, du) - 13.42) < 1e-6  # conferencia PU->taxa


def test_tesouro_parse_com_fallback_venda(fixtures_dir):
    titulos = [{"id": "PRE2029", "tipo": "Tesouro Prefixado", "ano": 2029},
               {"id": "PRE2031", "tipo": "Tesouro Prefixado", "ano": 2031},
               {"id": "IPCA2032", "tipo": "Tesouro IPCA+", "ano": 2032}]
    d = tesouro.parse_csv(_ler(fixtures_dir, "tesouro_amostra.csv"), titulos)
    assert d["PRE2029"]["historico"][-1][:2] == ["2026-09-17", 13.85]
    assert d["PRE2029"]["historico"][-1][3] == "compra"
    assert d["PRE2031"]["historico"][-1][1] == 13.95 and d["PRE2031"]["historico"][-1][3] == "venda"
    assert d["IPCA2032"]["historico"][-1][1] == 7.61 and d["IPCA2032"]["historico"][-1][2] == 3075.64
    assert d["IPCA2032"]["vencimento"] == "2032-08-15"
    # 'com Juros Semestrais' nao casa com 'Tesouro IPCA+'
    assert len(d["IPCA2032"]["historico"]) == 2


def test_ust_parse_e_mescla(fixtures_dir):
    linhas = ust.parse_xml(_ler(fixtures_dir, "ust_amostra.xml", binario=True))
    assert [l[0] for l in linhas] == ["2026-09-17", "2026-09-18"]
    assert linhas[-1][3] == 4.83 and linhas[-1][1] == 4.43
    m = ust.mesclar([["2026-09-16", 4.4, 4.5, 4.6, 5.1]], linhas)
    assert len(m) == 3 and m[0][0] == "2026-09-16"
    assert ust.parse_fred_csv("DATE,DGS10\n2026-09-17,4.69\n2026-09-18,.\n") == {"2026-09-17": 4.69}


def test_sina_parse(fixtures_dir):
    d = sina.parse(_ler(fixtures_dir, "sina_amostra.txt"))
    assert d["preco"] == 5480.0 and d["data"] == "2026-09-18"


def test_yahoo_parse_chart():
    payload = {"chart": {"result": [{
        "meta": {"currency": "USD", "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 101.5,
                 "previousClose": 100.0, "marketState": "CLOSED"},
        "timestamp": [1789660800, 1789747200],  # 2026-09-17 e 2026-09-18 (00:00 UTC)
        "indicators": {"quote": [{"open": [99.0, 100.5], "high": [101, 102], "low": [98, 99.5],
                                  "close": [100.0, 101.5], "volume": [1000, 2000]}],
                       "adjclose": [{"adjclose": [99.5, 101.5]}]},
        "events": {"dividends": {"1789660800": {"amount": 0.5, "date": 1789660800}}},
    }], "error": None}}
    d = yahoo.parse_chart(payload, "XYZ")
    assert d["moeda"] == "USD" and len(d["barras"]) == 2
    assert d["barras"][-1][4] == 101.5 and d["barras"][0][5] == 99.5
    assert d["eventos"]["dividendos"][0][1] == 0.5
    assert d["meta"]["marketState"] == "CLOSED"


def test_yahoo_mesclar_preserva_antiga():
    antiga = {"simbolo": "X", "barras": [["2026-09-17", 1, 1, 1, 1, 1, 0]]}
    assert yahoo.mesclar(antiga, None)["reaproveitada"] is True
    assert yahoo.mesclar(antiga, {"simbolo": "X", "barras": []})["barras"] == []


def test_bcb_parse():
    pts = bcb.parse_sgs([{"data": "17/09/2026", "valor": "5,1489"}, {"data": "x", "valor": "1"}])
    assert pts == [{"data": "2026-09-17", "valor": 5.1489}]
    f = bcb.parse_focus([{"DataReferencia": 2027, "Mediana": "4.30", "Data": "2026-09-11"},
                         {"DataReferencia": 2027, "Mediana": "4.25", "Data": "2026-09-04"}], "IPCA")
    assert f["por_ano"]["2027"]["mediana"] == 4.30

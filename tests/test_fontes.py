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
    # coleta que volta sem barra nao apaga o historico ja guardado
    assert yahoo.mesclar(antiga, {"simbolo": "X", "barras": []})["barras"] == antiga["barras"]


def test_bcb_parse():
    pts = bcb.parse_sgs([{"data": "17/09/2026", "valor": "5,1489"}, {"data": "x", "valor": "1"}])
    assert pts == [{"data": "2026-09-17", "valor": 5.1489}]
    f = bcb.parse_focus([{"DataReferencia": 2027, "Mediana": "4.30", "Data": "2026-09-11"},
                         {"DataReferencia": 2027, "Mediana": "4.25", "Data": "2026-09-04"}], "IPCA")
    assert f["por_ano"]["2027"]["mediana"] == 4.30


def test_mesclar_nao_perde_a_barra_do_ultimo_pregao():
    """O Yahoo as vezes devolve o chart sem a barra do dia (visto em 18/09 com MU)."""
    from livro.fontes import yahoo
    def barra(d, p):
        return [d, p, p, p, p, p, 100]
    antiga = {"simbolo": "MU", "barras": [barra("2026-09-16", 900.0), barra("2026-09-17", 977.5), barra("2026-09-18", 1015.8)]}
    nova = {"simbolo": "MU", "meta": {"regularMarketPrice": 1015.8}, "coletado_em": "x",
            "barras": [barra("2026-09-16", 900.0), barra("2026-09-17", 977.5)]}
    m = yahoo.mesclar(antiga, nova)
    assert [b[0] for b in m["barras"]] == ["2026-09-16", "2026-09-17", "2026-09-18"]
    assert m["barras"][-1][4] == 1015.8 and m["barras_recuperadas"] == ["2026-09-18"]
    assert m["meta"]["regularMarketPrice"] == 1015.8   # metadados sao os da coleta nova
    # coleta nova com a barra do dia corrigida vence a guardada
    nova2 = {"simbolo": "MU", "meta": {}, "barras": [barra("2026-09-16", 900.0), barra("2026-09-17", 977.5), barra("2026-09-18", 1016.4)]}
    m2 = yahoo.mesclar(m, nova2)
    assert m2["barras"][-1][4] == 1016.4 and "barras_recuperadas" not in m2
    # intradia (range=5d) tambem preserva os 2 anos
    import pandas as pd
    dias = [d.date().isoformat() for d in pd.bdate_range(end="2026-09-17", periods=900)]
    m3 = yahoo.mesclar({"barras": [barra(d, 10.0) for d in dias[-200:]]},
                       {"meta": {}, "barras": [barra("2026-09-18", 12.0)]})
    assert len(m3["barras"]) == 201 and m3["barras"][-1][4] == 12.0
    # sem coleta nova, a antiga fica marcada
    assert yahoo.mesclar(antiga, None)["reaproveitada"] is True
    assert yahoo.mesclar(None, None) is None
    # teto de barras: fica com as mais recentes
    longa = {"barras": [barra(d, float(i)) for i, d in enumerate(dias)]}
    m4 = yahoo.mesclar(longa, {"meta": {}, "barras": [barra("2026-09-18", 1.0)]}, max_barras=800)
    assert len(m4["barras"]) == 800 and m4["barras"][-1][0] == "2026-09-18" and m4["barras"][0][0] == dias[101]


def test_sina_em_dolar_tira_o_iva_chines_e_bate_com_o_cfr():
    """Futuro chines vem com IVA de 13% embutido: sem tirar, o minerio de Dalian
    aparece acima do CFR 62% sem motivo economico."""
    from livro.fontes import sina
    from livro import indicadores as ind
    p = {"proxies": {"SHFE_SP": {"preco": 4928.0, "data": "2026-09-18"},
                     "DCE_I0": {"preco": 715.0, "data": "2026-09-18"}},
         "historico": {"SHFE_SP": [["2026-09-17", 4900.0], ["2026-09-18", 4928.0]],
                       "DCE_I0": [["2026-09-18", 715.0]]}}
    fx = ind.de_precos(["2026-09-17", "2026-09-18"], [6.70, 6.71])
    d = sina.em_dolar(p, fx)
    minerio = d["MINERIO_DALIAN"]
    assert round(minerio["usd"]) == 94                    # 715 / 6,71 / 1,13
    assert round(minerio["usd_com_iva"]) == 107
    assert "sem o IVA de 13%" in minerio["rotulo"]
    # o que vai para a tela tem de ficar perto do CFR 62% (97,57 em 18/09)
    assert abs(minerio["usd"] / 97.57 - 1) < 0.06
    longa = d["CELULOSE_LONGA"]
    assert round(longa["usd"]) == 650
    assert longa["pontos"] == 2 and longa["janelas"]["dia"] is not None


def test_sina_em_dolar_sem_cambio_do_dia_nao_inventa_taxa():
    from livro.fontes import sina
    p = {"proxies": {"DCE_I0": {"preco": 715.0, "data": "2026-09-18"}}, "historico": {}}
    d = sina.em_dolar(p, None)
    assert d["MINERIO_DALIAN"].get("usd") is None         # declara a lacuna, nao converte no chute
    assert d["MINERIO_DALIAN"]["cny"] == 715.0

def test_barras_recuperadas_so_quando_falta_o_ultimo_pregao():
    """No intradia a coleta e range=5d: centenas de datas antigas ficam fora da janela
    por construcao. Contar isso fazia o log dizer "80 series com barra faltando" em
    toda rodada intradiaria, o que mascarava a anomalia de verdade."""
    from livro.fontes import yahoo
    antiga = {"barras": [["2026-09-01", 1, 1, 1, 1, 1, 10], ["2026-09-18", 1, 1, 1, 1, 1, 10]]}
    nova = {"barras": [["2026-09-18", 2, 2, 2, 2, 2, 20], ["2026-09-21", 2, 2, 2, 2, 2, 20]], "moeda": "USD"}
    assert "barras_recuperadas" not in yahoo.mesclar(antiga, nova)
    # anomalia real: o Yahoo devolveu sem o ultimo pregao que ja estava guardado
    antiga2 = {"barras": [["2026-09-18", 1, 1, 1, 1, 1, 10], ["2026-09-21", 1, 1, 1, 1, 1, 10]]}
    nova2 = {"barras": [["2026-09-17", 2, 2, 2, 2, 2, 20], ["2026-09-18", 2, 2, 2, 2, 2, 20]], "moeda": "USD"}
    assert yahoo.mesclar(antiga2, nova2)["barras_recuperadas"] == ["2026-09-21"]


def test_cury_candidato_nao_vira_noticia_da_construtora():
    """23/09: 'Cury cancela participacao em debate da Veja; evento tera Caiado e Zema'
    (Augusto Cury, candidato a presidente) virou noticia da CURY3."""
    import yaml
    from livro.fontes.noticias import atribuir
    cfg = yaml.safe_load(open("config/fontes_noticias.yaml", encoding="utf-8"))
    at = lambda t: atribuir(t, "", cfg["casar"], cfg.get("excluir"), cfg.get("previsor_macro"), cfg.get("excluir_global"))
    assert "CURY3" not in at("Cury cancela participação em debate da Veja; evento terá Caiado e Zema")
    assert "CURY3" not in at("Augusto Cury sobe na pesquisa Quaest")
    assert "CURY3" not in at("Zema e Cury trocam críticas em sabatina")
    assert "CURY3" in at("Cury (CURY3) cai 4% com juros futuros em alta")
    assert "CURY3" in at("Construtora Cury bate recorde de lançamentos no 3T26")
    assert "CURY3" in at("Cury, Direcional e MRV: o que esperar das construtoras de baixa renda")


# 23/10/2026 (auditoria do terminal, salto 10): o CSV do Tesouro Transparente parou em 15/10 e, desde 21/10, devolve a pagina anti-robo.
# Reserva: o dia pelo site do Tesouro Direto, somado ao historico (do CSV quando ele responde velho, do guardado quando ele falha).
_TIT_TD = [{"id": "PRE2029", "tipo": "Tesouro Prefixado", "ano": 2029}, {"id": "PRE2031", "tipo": "Tesouro Prefixado", "ano": 2031},
           {"id": "IPCA2032", "tipo": "Tesouro IPCA+", "ano": 2032}, {"id": "IPCA2050", "tipo": "Tesouro IPCA+", "ano": 2050}]


def _site_td(base="2026-10-23T18:00:08.193"):
    def it(nome, venc, taxa_inv, pu_inv, taxa_res, pu_res):
        return {"treasuryBondName": nome, "maturityDate": venc + "T00:00", "lastMarketPricingDate": base,
                "investmentProfitabilityIndexerName": taxa_inv, "unitaryInvestmentValue": pu_inv,
                "redemptionProfitabilityFeeIndexerName": taxa_res, "unitaryRedemptionValue": pu_res}
    investir = {"TesouroLegado": [it("Tesouro Prefixado 2029", "2029-01-01", "13,02%", 760.5, "13,14%", 759.1),
                                  it("Tesouro IPCA+ 2032", "2032-08-15", "IPCA + 7,41%", 3101.2, "IPCA + 7,53%", 3080.0),
                                  it("Tesouro IPCA+ com Juros Semestrais 2032", "2032-08-15", "IPCA + 7,20%", 4400.0, "IPCA + 7,32%", 4390.0)],
                "Tesouro24x7": [it("Tesouro Prefixado 2029", "2029-01-01", "13,50%", 750.0, "13,60%", 749.0)]}
    resgatar = {"TesouroLegado": investir["TesouroLegado"] + [it("Tesouro Prefixado 2031", "2031-01-01", "", 0, "13,77%", 601.3)]}
    return {"investir": investir, "resgatar": resgatar}


class _CliTD:
    """O CSV do jeito que vier (texto, ou None = pagina anti-robo) e o site do Tesouro Direto (None = fora)."""
    def __init__(self, csv, site):
        self.csv, self.site = csv, site

    def get(self, url, **kw):
        from livro.http import Resposta
        return Resposta(404, b"")

    def get_ok(self, url, **kw):
        import json as _j
        from livro.http import HttpError, Resposta
        if url.startswith(tesouro.SITE_URL):
            if self.site is None:
                raise HttpError(403, "bloqueado", url)
            return Resposta(200, _j.dumps(self.site[url[len(tesouro.SITE_URL):]]).encode())
        if self.csv is None:
            return Resposta(200, b"<html><body>Request Rejected. F5 support ID</body></html>")
        return Resposta(200, self.csv.encode())


def test_tesouro_site_quando_o_csv_falha(fixtures_dir):
    guardado = tesouro.parse_csv(_ler(fixtures_dir, "tesouro_amostra.csv"), _TIT_TD)
    anterior = {"fonte": tesouro.FONTE_CSV, "data_base": "2026-09-17", "titulos": guardado}
    d = tesouro.coletar(_TIT_TD, _CliTD(None, _site_td()), anterior=anterior)
    assert d["fonte"] == tesouro.FONTE_SITE and d["data_base"] == "2026-10-23"
    r = d["reserva"]
    assert r["csv_ate"] == "2026-09-17" and r["hora_site"] == "18:00" and "em falha" in r["motivo"]
    assert r["do_site"] == ["IPCA2032", "PRE2029", "PRE2031"] and r["sem_site"] == ["IPCA2050"]
    p29 = d["titulos"]["PRE2029"]["historico"]
    assert p29[-1] == ["2026-10-23", 13.02, 760.5, "compra"]           # o TesouroLegado ganha do Tesouro24x7
    assert p29[-2][:2] == ["2026-09-17", 13.85] and len(p29) == len(guardado["PRE2029"]["historico"]) + 1
    assert d["titulos"]["PRE2031"]["historico"][-1] == ["2026-10-23", 13.77, 601.3, "venda"]   # fora de venda: taxa de recompra
    assert d["titulos"]["IPCA2032"]["historico"][-1][1] == 7.41                # 'com Juros Semestrais' nao casa com 'Tesouro IPCA+'
    assert d["titulos"]["IPCA2050"]["historico"] == []
    # a rodada seguinte, ainda sem CSV, guarda a data em que o CSV parou e nao duplica o dia
    d2 = tesouro.coletar(_TIT_TD, _CliTD(None, _site_td()), anterior=d)
    assert d2["reserva"]["csv_ate"] == "2026-09-17" and d2["titulos"]["PRE2029"]["historico"] == p29


def test_tesouro_site_completa_o_csv_parado(fixtures_dir):
    csv = _ler(fixtures_dir, "tesouro_amostra.csv")
    d = tesouro.coletar(_TIT_TD, _CliTD(csv, _site_td()))
    assert d["fonte"] == tesouro.FONTE_SITE and d["data_base"] == "2026-10-23"
    assert d["reserva"]["csv_ate"] == "2026-09-17" and "parado na base 2026-09-17" in d["reserva"]["motivo"]
    assert d["titulos"]["PRE2029"]["historico"][-2][:2] == ["2026-09-17", 13.85]
    # site sem data mais nova que a do CSV, ou site fora: fica o CSV como sempre
    assert "reserva" not in tesouro.coletar(_TIT_TD, _CliTD(csv, _site_td("2026-09-17T18:00:00")))
    assert tesouro.coletar(_TIT_TD, _CliTD(csv, None))["fonte"] == tesouro.FONTE_CSV


def test_tesouro_csv_e_site_fora_levanta(fixtures_dir):
    import pytest
    with pytest.raises(ValueError, match="site do Tesouro Direto em falha"):
        tesouro.coletar(_TIT_TD, _CliTD(None, None), anterior={})


def test_tesouro_site_nao_mistura_resgate_com_compra(fixtures_dir):
    """Titulo fora de venda: o site so traz a taxa de resgate, 0,12 pp acima da de compra (medido em 23/10/2026). Com o historico
    em taxa de compra, o ponto do site nao entra (o titulo fica na base antiga e o render o tira da tabela)."""
    guardado = tesouro.parse_csv(_ler(fixtures_dir, "tesouro_amostra.csv"), _TIT_TD)
    guardado["PRE2031"]["historico"] = [["2026-09-17", 13.60, 610.0, "compra"]]
    anterior = {"fonte": tesouro.FONTE_CSV, "data_base": "2026-09-17", "titulos": guardado}
    d = tesouro.coletar(_TIT_TD, _CliTD(None, _site_td()), anterior=anterior)
    assert d["titulos"]["PRE2031"]["historico"] == [["2026-09-17", 13.60, 610.0, "compra"]]
    assert d["reserva"]["so_resgate"] == ["PRE2031"] and "PRE2031" not in d["reserva"]["do_site"] + d["reserva"]["sem_site"]
    assert d["titulos"]["PRE2029"]["historico"][-1][3] == "compra"

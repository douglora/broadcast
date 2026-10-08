import io
import zipfile

import pandas as pd

from quant.dados import cotahist as ch


def _linha(**kw):
    base = dict(tipreg="01", data="20241227", codbdi="02", ticker="PETR4", tpmerc="010",
                nome="PETROBRAS", especi="PN      N2", prazot="", moeda="R$",
                abe="3550", max="3570", min="3540", med="3555", fec="3566", bid="3565", ask="3567",
                negocios="12345", qtd="100000", volume="355500000", preexe="0", indopc="0",
                datven="99991231", fatcot="1", ptoexe="0", isin="BRPETRACNPR6", dismes="103")
    base.update(kw)
    return ch.montar_registro(base)


def test_layout_soma_245_e_e_contiguo():
    pos = 0
    for nome, ini, fim in ch.LAYOUT:
        assert ini == pos, nome
        pos = fim
    assert pos == ch.TAMANHO_REGISTRO


def test_parse_registro_conhecido():
    texto = "00COTAHIST.2024BOVESPA " + " " * 220 + "\n" + _linha() + "\n" + "99" + " " * 243
    df = ch.parse(texto)
    assert len(df) == 1
    r = df.iloc[0]
    assert str(r["data"]) == "2024-12-27"
    assert r["ticker"] == "PETR4" and r["codbdi"] == "02" and r["tpmerc"] == "010"
    assert r["fec"] == 35.66 and r["abe"] == 35.50 and r["bid"] == 35.65 and r["ask"] == 35.67
    assert r["negocios"] == 12345 and r["qtd"] == 100000 and r["volume"] == 3555000.0
    assert r["isin"] == "BRPETRACNPR6" and r["fatcot"] == 1
    assert pd.isna(r["datven"])            # 99991231 = sem vencimento


def test_parse_ignora_linhas_curtas_e_aceita_cr():
    texto = _linha() + "\r\n" + _linha(ticker="VALE3", isin="BRVALEACNOR0") + "\r\n" + "lixo\n"
    df = ch.parse(texto)
    assert df["ticker"].tolist() == ["PETR4", "VALE3"]


def test_acoes_a_vista_mantem_rj_na_serie_mas_nao_no_universo():
    texto = "\n".join([
        _linha(ticker="PETR4"),
        _linha(ticker="AMER3", codbdi="08", isin="BRAMERACNOR6"),      # recuperacao judicial
        _linha(ticker="PETR4F", tpmerc="020", codbdi="96"),            # fracionario
        _linha(ticker="PETRA100", tpmerc="070", codbdi="82"),          # opcao
        _linha(ticker="HGLG11", codbdi="12", isin="BRHGLGCTF003"),     # FII
        _linha(ticker="BOVA11", codbdi="02", isin="BRBOVACTF003"),     # ETF (CODBDI 02: fica; filtro e por ISIN/cadastro)
    ])
    df = ch.parse(texto)
    serie = ch.acoes_a_vista(df, apenas_lote_padrao=False)
    universo = ch.acoes_a_vista(df, apenas_lote_padrao=True)
    assert set(serie["ticker"]) == {"PETR4", "AMER3", "BOVA11"}
    assert set(universo["ticker"]) == {"PETR4", "BOVA11"}


def test_parse_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("COTAHIST_A2024.TXT", (_linha() + "\n").encode("latin-1"))
    df = ch.parse_zip(buf.getvalue())
    assert len(df) == 1 and df.iloc[0]["fec"] == 35.66

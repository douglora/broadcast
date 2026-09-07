import json

import pandas as pd

from quant.dados import arquivar_b3 as a


TICKERCSV = (
    "RptDt;TckrSymb;UpdActn;GrssTradAmt;TradQty;NtryTm;TradId;TradgSsnId;TradDt\n"
    "2026-09-04;PETR4;new;35,660;100;100000123;10;regular;2026-09-04\n"
    "2026-09-04;PETR4;new;35,700;200;100030456;11;regular;2026-09-04\n"
    "2026-09-04;PETR4;new;35,650;100;100115000;12;regular;2026-09-04\n"
    "2026-09-04;VALE3;new;62,100;300;100000999;13;regular;2026-09-04\n"
    "2026-09-04;VALE3;delete;62,100;300;100000999;13;regular;2026-09-04\n"
)


def test_barras_1min_agrega_por_minuto_e_ignora_cancelados():
    df = a.ler_csv_b3(TICKERCSV.encode("latin-1"))
    barras = a.barras_1min(df)
    p = barras[barras.ticker == "PETR4"].set_index("minuto")
    assert list(p.index) == ["10:00", "10:01"]
    assert p.loc["10:00", "abe"] == 35.66 and p.loc["10:00", "fec"] == 35.70
    assert p.loc["10:00", "qtd"] == 300 and p.loc["10:00", "negocios"] == 2
    assert abs(p.loc["10:00", "vwap"] - (35.66 * 100 + 35.70 * 200) / 300) < 1e-9
    # VALE3 teve 1 negocio e 1 cancelamento: o cancelado nao conta (fica 1 linha 'new')
    v = barras[barras.ticker == "VALE3"]
    assert len(v) == 1 and v.iloc[0]["negocios"] == 1


def test_numero_br():
    assert a.numero_br("1.234,56") == 1234.56
    assert a.numero_br("35,660") == 35.66
    assert a.numero_br("1234.5") == 1234.5
    assert a.numero_br("") != a.numero_br("")   # NaN


def test_ler_csv_b3_pula_linha_de_status_e_aceita_latin1():
    bruto = "Status do Arquivo: Final\nTckrSymb;Nome;Taxa\nPETR4;PETRÓLEO;1,25\n".encode("latin-1")
    df = a.ler_csv_b3(bruto)
    assert list(df.columns) == ["TckrSymb", "Nome", "Taxa"]
    assert df.iloc[0]["Nome"].startswith("PETR")


def test_normalizar_carteira_aceita_json_entre_aspas():
    obj = {"page": {"totalPages": 1}, "results": [
        {"cod": "PETR4", "asset": "PETROBRAS", "type": "PN N2", "part": "7,123", "theoricalQty": "4.380.195.841"},
        {"cod": "VALE3", "asset": "VALE", "type": "ON NM", "part": "10,5", "theoricalQty": "1.000"}]}
    texto = json.dumps(json.dumps(obj))          # B3 as vezes devolve string JSON de um JSON
    df = a.normalizar_carteira(a.json_b3(texto), "IBOV", "carteira")
    assert len(df) == 2 and df.iloc[0]["part"] == 7.123 and df.iloc[0]["theoricalQty"] == 4380195841


def test_filtrar_ipe_novos():
    df = pd.DataFrame({"Protocolo_Entrega": ["1", "2", "3"], "Assunto": ["a", "b", "c"]})
    novos = a.filtrar_ipe_novos(df, vistos=["2"])
    assert novos["Protocolo_Entrega"].tolist() == ["1", "3"]


def test_resumo_aluguel_conta_contratos():
    df = pd.DataFrame({"Ticker": ["A", "B"], "Contratos": ["0", "12"], "Taxa": ["1,2", "1,2"]})
    assert a.resumo_aluguel(df) == {"linhas": 2, "com_contrato": 1}


def test_zip_vazio_e_feriado():
    assert a._ler_zip_negocios(b"") is None
    assert a._ler_zip_negocios(b"PK\x05\x06" + b"\x00" * 18) is None

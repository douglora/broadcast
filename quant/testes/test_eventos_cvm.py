"""Eventos de quantidade que a lista da B3 nao traz (bonificacao, desdobramento, grupamento): a CVM completa e o preco data. Mais o conserto do leitor da B3."""
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from quant.dados import calendario
from quant.dados import eventos as ev
from quant.dados import eventos_cvm as cvm


# ── proporcao redonda ─────────────────────────────────────────
def test_proporcao_redonda_e_k_final():
    assert cvm.proporcao_redonda(1.0957) == 1.10                      # a CVM soma emissao e cancelamento do mesmo ato (Bradesco 2021)
    assert cvm.proporcao_redonda(1.2) == 1.2 and cvm.proporcao_redonda(8.0) == 8.0
    assert cvm.proporcao_redonda(0.0999) == pytest.approx(0.1)        # grupamento 10:1
    assert cvm.proporcao_redonda(1.1285) is None and cvm.proporcao_redonda(0.9404) is None
    assert cvm.k_final(1.0957) == 1.10 and cvm.k_final(1.1285) == pytest.approx(1.1285)
    assert cvm.proporcao_redonda(float("nan")) is None and cvm.proporcao_redonda(0) is None


def test_tipo_do_evento():
    assert cvm.tipo_do_evento(1.1, "Bonificação") == "BONIFICACAO"
    assert cvm.tipo_do_evento(8.0, "Desdobramento") == "DESDOBRAMENTO"
    assert cvm.tipo_do_evento(0.1, "Grupamento") == "GRUPAMENTO"


# ── FRE ───────────────────────────────────────────────────────
def _fre(linhas):
    return pd.DataFrame(linhas, columns=["cnpj", "aprov", "tipo", "antes", "depois", "versao", "ano_arq", "nome"]).assign(aprov=lambda d: pd.to_datetime(d["aprov"]))


def test_eventos_fre_repete_versoes_cancela_grupamento_com_desdobramento_e_tira_ruido():
    f = _fre([
        ("111", "2013-04-19", "Bonificação", 1000, 1100, 10, 2012, "A"),
        ("111", "2013-04-19", "Bonificação", 1000, 1100, 11, 2013, "A"),               # mesma assembleia em outra versao do FRE: conta uma vez
        ("222", "2011-04-25", "Grupamento", 4570936100, 45709361, 15, 2011, "B"),
        ("222", "2011-04-25", "Desdobramento", 45709361, 4570936100, 15, 2011, "B"),   # os dois do mesmo dia se anulam (bancos, 2011)
        ("333", "2015-01-10", "Bonificação", 1000, 1010, 1, 2015, "C"),                # 1%: ruido
        ("444", "2017-09-04", "Desdobramento", 100, 800, 1, 2017, "D"),
    ])
    e = cvm.eventos_fre(f).set_index("cnpj")
    assert list(e.index) == ["111", "444"]
    assert e.loc["111", "K"] == pytest.approx(1.1) and e.loc["444", "K"] == pytest.approx(8.0)


def test_ler_fre_le_o_zip_da_cvm(tmp_path):
    csv = ("CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;ID_Capital_Social_Desdobramento;Data_Aprovacao;Tipo_Evento;"
           "Quantidade_Acoes_Ordinarias_Antes_Aprovacao;Quantidade_Acoes_Preferenciais_Antes_Aprovacao;Quantidade_Total_Acoes_Antes_Aprovacao;"
           "Quantidade_Acoes_Ordinarias_Depois_Aprovacao;Quantidade_Acoes_Preferenciais_Depois_Aprovacao;Quantidade_Total_Acoes_Depois_Aprovacao\n"
           "60.872.504/0001-23;2012-01-01;14;1;ITAU UNIBANCO HOLDING S.A.;5;2013-04-19;Bonificação;1;1;4570936100;1;1;5028029710\n")
    with zipfile.ZipFile(tmp_path / "fre_cia_aberta_2012.zip", "w") as z:
        z.writestr("fre_cia_aberta_capital_social_desdobramento_2012.csv", csv.encode("latin1"))
        z.writestr("fre_cia_aberta_capital_social_desdobramento_classe_acao_2012.csv", b"x;y\n")      # a tabela por classe nao entra
    d = cvm.ler_fre(str(tmp_path))
    assert len(d) == 1 and d["cnpj"].iloc[0] == "60872504000123" and d["aprov"].iloc[0] == pd.Timestamp("2013-04-19")
    e = cvm.eventos_fre(d)
    assert e["K"].iloc[0] == pytest.approx(5028029710 / 4570936100)
    assert cvm.ler_fre(str(tmp_path / "nao_existe")).empty


# ── numero de acoes ───────────────────────────────────────────
def _capital(linhas):
    return pd.DataFrame(linhas, columns=["cd_cvm", "cnpj", "data_ref", "versao", "acoes_on", "acoes_pn", "acoes_total"])


def test_saltos_de_capital_so_proporcao_redonda_igual_nas_classes_e_depois_de_2023():
    c = _capital([
        (1, "11.111.111/0001-11", "2023-12-31", 1, 300e6, 600e6, 900e6), (1, "11.111.111/0001-11", "2024-03-31", 1, 360e6, 720e6, 1080e6),     # +20% nas duas: evento
        (2, "22.222.222/0001-22", "2023-12-31", 1, 300e6, 600e6, 900e6), (2, "22.222.222/0001-22", "2024-03-31", 1, 360e6, 600e6, 960e6),     # so a ON saltou: emissao
        (3, "33.333.333/0001-33", "2023-12-31", 1, 100e6, 0, 100e6), (3, "33.333.333/0001-33", "2024-03-31", 1, 137e6, 0, 137e6),            # 37%: nao e redondo
        (4, "44.444.444/0001-44", "2021-12-31", 1, 100e6, 0, 100e6), (4, "44.444.444/0001-44", "2022-03-31", 1, 120e6, 0, 120e6),            # antes de 2023-10: e do FRE
    ])
    s = cvm.saltos_de_capital(c)
    assert len(s) == 1 and s["cnpj"].iloc[0] == "11111111000111" and s["K"].iloc[0] == pytest.approx(1.2)
    assert s["aprov"].iloc[0] == pd.Timestamp("2023-12-31") and s["ate"].iloc[0] == pd.Timestamp("2024-03-31") and s["fonte"].iloc[0] == "cvm_capital"


# ── datar pelo preco e completar a tabela ─────────────────────
def _cot(dias=200, k=1.1, queda=120, tickers=("AAAA3",), mercado=12, seed=7, dividendo_no_dia=0.0):
    """`mercado` papeis sem evento (para a mediana do mercado) mais os `tickers`, estes com o preco dividido por k no dia `queda`."""
    datas = pd.bdate_range("2019-06-03", periods=dias)
    rng = np.random.default_rng(seed)
    comum = rng.normal(0, 0.008, dias)
    linhas = []
    for i, t in enumerate([f"M{j:02d}Y3" for j in range(mercado)] + list(tickers)):
        p = 40.0 * np.exp(np.cumsum(comum + rng.normal(0, 0.009, dias)))
        if t in tickers:
            p[queda:] = p[queda:] / k
        linhas.append(pd.DataFrame({"ticker": t, "data": datas, "fec": p, "fatcot": 1}))
    return pd.concat(linhas, ignore_index=True), datas


def _ident(tickers=("AAAA3",), cnpj="12345678000100"):
    return pd.DataFrame({"ticker": list(tickers), "cnpj": cnpj})


def test_datar_acha_o_dia_do_salto_mesmo_com_dividendo_no_mesmo_dia():
    cot, datas = _cot()
    dia = datas[120]
    vazio = ev._tabela_vazia()
    p = cvm.Precos(cot, vazio)
    d, escore, margem = p.datar("AAAA3", datas[100], datas[95], datas[190], 1.1)
    assert d == dia and escore < 0.03 and margem > 0.02
    # dividendo de 3% na mesma data-ex: a conta e (preco x fator + provento) / preco anterior, nao (preco + provento) x fator
    preco_antes = cot[(cot.ticker == "AAAA3") & (cot.data == datas[119])]["fec"].iloc[0]
    com_div = ev._montar([{"ticker": "AAAA3", "tipo": "DIVIDENDO", "data_com": datas[119], "data_ex": dia, "valor": 0.03 * preco_antes, "fator": np.nan, "data_aprov": pd.NaT,
                           "fonte": "b3", "carimbo": "", "obs": ""}])
    cot2 = cot.copy()
    m = (cot2.ticker == "AAAA3") & (cot2.data >= dia)
    cot2.loc[m, "fec"] = cot2.loc[m, "fec"] - 0.03 * preco_antes / 1.1            # o dividendo tambem tira do preco
    d2, escore2, _ = cvm.Precos(cot2, com_div).datar("AAAA3", datas[100], datas[95], datas[190], 1.1)
    assert d2 == dia and escore2 < 0.03


def _completar(cot, fre, eventos=None, capital=None, tickers=("AAAA3",)):
    capital = capital if capital is not None else _capital([])
    return cvm.completar(eventos if eventos is not None else ev._tabela_vazia(), cot=cot, identidade=_ident(tickers), fre=fre, capital=capital)


def test_completar_acrescenta_a_bonificacao_que_a_b3_nao_traz():
    cot, datas = _cot()
    fre = _fre([("12345678000100", str(datas[110].date()), "Bonificação", 1000, 1100, 1, 2019, "X S.A.")])
    novos, diag = _completar(cot, fre)
    assert len(novos) == 1
    r = novos.iloc[0]
    assert r["ticker"] == "AAAA3" and r["tipo"] == "BONIFICACAO" and r["data_ex"] == datas[120] and r["fator"] == pytest.approx(1.1) and r["fonte"] == "cvm_fre"
    assert r["data_com"] == pd.Timestamp(calendario.pregao_anterior(datas[120].date())) and "FRE item 17.3" in r["obs"] and "escore" in r["obs"]
    assert diag["destino"].tolist() == ["aplicado"]


def test_completar_nao_repete_o_que_a_tabela_ja_tem_nem_aceita_data_fora():
    cot, datas = _cot()
    fre = _fre([("12345678000100", str(datas[110].date()), "Bonificação", 1000, 1100, 1, 2019, "X S.A.")])
    ja = ev._montar([{"ticker": "AAAA3", "tipo": "BONIFICACAO", "data_com": datas[119], "data_ex": datas[120], "valor": np.nan, "fator": 1.1, "data_aprov": pd.NaT,
                      "fonte": "b3_suplemento", "carimbo": "", "obs": ""}])
    novos, diag = _completar(cot, fre, eventos=ja)
    assert len(novos) == 0 and diag["destino"].tolist() == ["ja_registrado"]
    # B3 com o fator 4% diferente e um dia fora (dado ruim) ainda e o mesmo evento: nao duplica
    ja2 = ja.assign(fator=1.14, data_ex=datas[124])
    assert len(_completar(cot, fre, eventos=ja2)[0]) == 0


def test_completar_pula_evento_pequeno_reducao_que_nao_e_grupamento_e_papel_que_nao_saltou():
    cot, datas = _cot()
    fre = _fre([
        ("12345678000100", str(datas[110].date()), "Bonificação", 1000, 1030, 1, 2019, "X"),            # 3%: abaixo do minimo
        ("12345678000100", str(datas[111].date()), "Grupamento", 1000, 940, 1, 2019, "X"),             # 0,94: cancelamento de acoes, nao grupamento
        ("12345678000100", str(datas[112].date()), "Bonificação", 1000, 1250, 1, 2019, "X"),           # 25%, mas o preco deste papel nao saltou 25%
    ])
    novos, diag = _completar(cot, fre)
    assert len(novos) == 0
    assert diag["destino"].tolist() == ["pequeno", "reducao_nao_e_grupamento", "sem_salto_no_preco"]


def test_completar_so_da_o_evento_a_classe_que_saltou_e_acha_a_classe_pela_raiz():
    cot, datas = _cot(tickers=("AAAA3", "AAAA4"))
    cot.loc[(cot.ticker == "AAAA4") & (cot.data >= datas[120]), "fec"] *= 1.1               # a PN nao teve a bonificacao
    fre = _fre([("12345678000100", str(datas[110].date()), "Bonificação", 1000, 1100, 1, 2019, "X")])
    novos, diag = _completar(cot, fre, tickers=("AAAA3",))                                    # a identidade so lista a ON; a PN vem pela raiz AAAA
    assert novos["ticker"].tolist() == ["AAAA3"]
    assert dict(zip(diag["ticker"], diag["destino"])) == {"AAAA3": "aplicado", "AAAA4": "sem_salto_no_preco"}


def test_completar_pelo_salto_do_numero_de_acoes_depois_de_2023():
    cot, datas = _cot()
    cot["data"] = cot["data"] + pd.DateOffset(years=5)                                       # 2024-06
    datas = datas + pd.DateOffset(years=5)
    c = _capital([(9, "12.345.678/0001-00", "2024-06-30", 1, 300e6, 0, 300e6), (9, "12.345.678/0001-00", "2024-12-31", 1, 330e6, 0, 330e6)])
    novos, diag = _completar(cot, _fre([]), capital=c)
    assert len(novos) == 1 and novos["fonte"].iloc[0] == "cvm_capital" and novos["data_ex"].iloc[0] == datas[120] and novos["fator"].iloc[0] == pytest.approx(1.1)


def test_completar_tabela_nao_duplica_e_a_prioridade_da_b3_vence():
    cot, datas = _cot()
    fre = _fre([("12345678000100", str(datas[110].date()), "Bonificação", 1000, 1100, 1, 2019, "X")])
    nova, diag = cvm.completar_tabela(ev._tabela_vazia(), cot=cot, identidade=_ident(), fre=fre, capital=_capital([]))
    assert len(nova) == 1
    de_novo, _ = cvm.completar_tabela(nova, cot=cot, identidade=_ident(), fre=fre, capital=_capital([]))
    assert len(de_novo) == 1                                                                 # rodar duas vezes nao acrescenta nada
    assert ev.PRIORIDADE_FONTE["b3"] < ev.PRIORIDADE_FONTE["cvm_fre"] < ev.PRIORIDADE_FONTE["cvm_capital"]


# ── o leitor da B3: a bonificacao e de quem recebe (isinCode), nao da classe emitida (assetIssued) ──
def _bonus(asset, isin, factor="18,95833333300"):
    return {"stockDividends": [{"assetIssued": asset, "factor": factor, "approvedOn": "30/12/2025", "isinCode": isin, "label": "BONIFICACAO",
                                "lastDatePrior": "30/12/2025", "remarks": ""}]}


def test_leitor_da_b3_aceita_a_bonificacao_paga_a_on_que_emite_acoes_pn():
    obj = _bonus("BRCYREACNPR4", "BRCYREACNOR7")                          # CYRE3, 2025: emite PN, paga ao titular da ON
    on = ev.normalizar_b3_suplemento(obj, "CYRE3")
    assert len(on) == 1 and on["tipo"].iloc[0] == "BONIFICACAO" and on["fator"].iloc[0] == pytest.approx(1.1895833333)
    assert len(ev.normalizar_b3_suplemento(obj, "CYRE4")) == 1            # a PN tambem (assetIssued)
    assert len(ev.normalizar_b3_suplemento(obj, "CYRE11")) == 1           # e a unit, que e cesta dessas classes


def test_leitor_da_b3_continua_recusando_evento_de_outra_classe():
    obj = _bonus("BRXXXXACNPR4", "BRXXXXACNPR4")                          # so PN
    assert len(ev.normalizar_b3_suplemento(obj, "XXXX3")) == 0
    assert len(ev.normalizar_b3_suplemento(obj, "XXXX4")) == 1
    sem_isin = {"stockDividends": [{"assetIssued": "", "factor": "10,0", "isinCode": "", "label": "BONIFICACAO", "lastDatePrior": "30/12/2025"}]}
    assert len(ev.normalizar_b3_suplemento(sem_isin, "XXXX3")) == 1       # sem classe informada casa com todos, como antes


def test_axia_em_2025_a_bonificacao_chega_nas_tres_classes():
    obj = {"stockDividends": [{"assetIssued": "BRAXIAACNPC9", "factor": "26,28378881074", "isinCode": i, "label": "BONIFICACAO", "lastDatePrior": "19/12/2025",
                               "approvedOn": "19/12/2025"} for i in ("BRAXIAACNOR0", "BRAXIAACNPA3", "BRAXIAACNPB1")]}
    for t in ("AXIA3", "AXIA5", "AXIA6"):
        assert ev.normalizar_b3_suplemento(obj, t)["fator"].tolist() == [pytest.approx(1.2628378881)]

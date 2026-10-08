"""Doze meses inventados, com a conta refeita a mao dentro do proprio teste.

Cada mes cobre uma regra: mes isento, mes que estoura o teto de R$20 mil por causa de
venda externa, day trade criado sem querer, prejuizo em mes isento (o caso controverso),
DARF abaixo de R$10 que acumula, ajuste diario de futuro entrando na base comum, prejuizo
comum compensado adiante e prejuizo de day trade que so compensa com day trade.

Os valores esperados sao escritos como a aritmetica que os produz, nunca como literal
solto: quem le o teste tem de conseguir refazer a conta.
"""
import numpy as np
import pandas as pd
import pytest

from quant import fiscal as fs


def _op(data, ticker, lado, qtd, preco, custos, classe="acao"):
    return {"data": data, "ticker": ticker, "classe": classe, "lado": lado, "qtd": qtd,
            "preco": preco, "valor": qtd * preco, "custos": custos, "fonte": "teste"}


OPERACOES = pd.DataFrame([
    # jan: so compra. pm = (1000*10 + 5) / 1000 = 10,005
    _op("2026-01-05", "ABCD3", "C", 1000, 10.00, 5.0),
    # fev: vende 500 a 12; vendas de 6.000 cabem no teto -> ISENTO
    _op("2026-02-10", "ABCD3", "V", 500, 12.00, 5.0),
    # mar: vende 500 a 15; com 15.000 de venda externa o mes estoura o teto
    _op("2026-03-10", "ABCD3", "V", 500, 15.00, 5.0),
    # abr: day trade puro, detectado pela movimentacao do dia
    _op("2026-04-15", "EFGH3", "C", 100, 20.00, 2.0),
    _op("2026-04-15", "EFGH3", "V", 100, 21.00, 2.0),
    # mai: prejuizo num mes isento (o caso controverso)
    _op("2026-05-12", "IJKL3", "C", 200, 30.00, 6.0),
    _op("2026-05-20", "IJKL3", "V", 200, 25.00, 5.0),
    # jun: lucro pequeno num mes tributado -> DARF abaixo de R$10, acumula
    _op("2026-06-10", "MNOP3", "C", 100, 50.00, 5.0),
    _op("2026-06-20", "MNOP3", "V", 100, 50.70, 5.0),
    # jul: repete, e a soma dos dois passa de R$10 -> recolhe
    _op("2026-07-10", "QRST3", "C", 100, 50.00, 5.0),
    _op("2026-07-20", "QRST3", "V", 100, 50.70, 5.0),
    # out: lucro que consome o prejuizo do ajuste de futuro de setembro
    _op("2026-10-05", "UVWX3", "C", 1000, 20.00, 10.0),
    _op("2026-10-20", "UVWX3", "V", 1000, 22.02, 10.0),
    # nov: prejuizo de day trade
    _op("2026-11-10", "YZAB3", "C", 100, 10.00, 1.0),
    _op("2026-11-10", "YZAB3", "V", 100, 9.00, 1.0),
    # dez: lucro de day trade, compensa so com o prejuizo de day trade
    _op("2026-12-10", "CDEF3", "C", 100, 10.00, 1.0),
    _op("2026-12-10", "CDEF3", "V", 100, 13.00, 1.0),
])

# ago: ajuste diario de futuro positivo; set: negativo. O fato gerador e o ajuste.
AJUSTES = pd.DataFrame([
    {"data": "2026-08-14", "valor": 500.0, "custos": 10.0},
    {"data": "2026-09-15", "valor": -800.0, "custos": 0.0},
])

EXTERNAS = {"2026-03": 15_000.0, "2026-06": 16_000.0, "2026-07": 16_000.0}

PM_ABCD = (1000 * 10.00 + 5.0) / 1000          # 10,005


@pytest.fixture(scope="module")
def apuracao():
    return fs.apurar(OPERACOES, vendas_externas=EXTERNAS, ajustes_futuros=AJUSTES)


def _mes(apuracao, mes):
    m = apuracao["mensal"]
    linha = m[m["mes"] == mes]
    assert len(linha) == 1, f"mes {mes} ausente na apuracao"
    return linha.iloc[0]


# ─────────────────────────────────────────────────────────────
# Preco medio e realizacao
# ─────────────────────────────────────────────────────────────
def test_preco_medio_incorpora_os_custos_da_compra():
    pos = fs.posicao_media(OPERACOES, ate="2026-01-31")
    r = pos[pos["ticker"] == "ABCD3"].iloc[0]
    assert r["qtd"] == 1000 and abs(r["preco_medio"] - PM_ABCD) < 1e-12


def test_venda_nao_muda_o_preco_medio_do_que_sobra():
    pos = fs.posicao_media(OPERACOES, ate="2026-02-28")
    r = pos[pos["ticker"] == "ABCD3"].iloc[0]
    assert r["qtd"] == 500 and abs(r["preco_medio"] - PM_ABCD) < 1e-12


def test_resultado_da_venda_desconta_preco_medio_e_custos(apuracao):
    r = apuracao["realizadas"]
    fev = r[(r["mes"] == "2026-02") & (r["ticker"] == "ABCD3")].iloc[0]
    assert abs(fev["resultado"] - (500 * 12.00 - PM_ABCD * 500 - 5.0)) < 1e-9


# ─────────────────────────────────────────────────────────────
# Isencao de R$20 mil
# ─────────────────────────────────────────────────────────────
def test_mes_dentro_do_teto_e_isento(apuracao):
    m = _mes(apuracao, "2026-02")
    assert m["vendas_acoes"] == 500 * 12.00 and m["isento"]
    assert abs(m["resultado_acoes"] - (500 * 12.00 - PM_ABCD * 500 - 5.0)) < 1e-9
    assert m["resultado_comum_tributavel"] == 0.0 and m["imposto_total"] == 0.0


def test_venda_externa_estoura_o_teto_e_tributa_o_mes_inteiro(apuracao):
    m = _mes(apuracao, "2026-03")
    assert m["vendas_acoes"] == 500 * 15.00 + 15_000.0 > fs.ISENCAO_VENDAS_MES
    assert not m["isento"]
    resultado = 500 * 15.00 - PM_ABCD * 500 - 5.0
    assert abs(m["resultado_comum_tributavel"] - resultado) < 1e-9
    assert abs(m["imposto_comum"] - resultado * fs.ALIQUOTA_COMUM) < 1e-9
    assert abs(m["irrf_comum"] - 500 * 15.00 * fs.IRRF_COMUM) < 1e-12
    assert abs(m["darf_devido"] - (resultado * fs.ALIQUOTA_COMUM - 500 * 15.00 * fs.IRRF_COMUM)) < 1e-9


def test_isencao_disponivel_diz_quanto_ainda_cabe(apuracao):
    assert abs(fs.isencao_disponivel(apuracao, "2026-02") - (20_000.0 - 6_000.0)) < 1e-9
    assert fs.isencao_disponivel(apuracao, "2026-03") < 0          # ja estourou
    assert fs.isencao_disponivel(apuracao, "2030-01") == fs.ISENCAO_VENDAS_MES


def test_day_trade_nao_conta_para_o_teto(apuracao):
    m = _mes(apuracao, "2026-04")
    assert m["vendas_acoes"] == 0.0 and not m["isento"]


# ─────────────────────────────────────────────────────────────
# Day trade detectado
# ─────────────────────────────────────────────────────────────
def test_compra_e_venda_no_mesmo_pregao_viram_day_trade(apuracao):
    m = _mes(apuracao, "2026-04")
    resultado = 100 * (21.00 - 20.00) - (2.0 + 2.0)
    assert abs(m["resultado_day_trade"] - resultado) < 1e-9
    assert m["resultado_comum_bruto"] == 0.0
    assert abs(m["imposto_day_trade"] - resultado * fs.ALIQUOTA_DAY_TRADE) < 1e-9
    assert abs(m["irrf_day_trade"] - resultado * fs.IRRF_DAY_TRADE) < 1e-9
    esperado = resultado * fs.ALIQUOTA_DAY_TRADE - resultado * fs.IRRF_DAY_TRADE
    assert abs(m["darf_devido"] - esperado) < 1e-9


def test_ordem_parcialmente_casada_no_dia_se_divide():
    """Comprar 300 e vender 100 no mesmo dia gera 100 de day trade e 200 de compra comum."""
    ops = pd.DataFrame([_op("2026-03-02", "XPTO3", "C", 300, 10.0, 3.0),
                        _op("2026-03-02", "XPTO3", "V", 100, 11.0, 1.0)])
    c = fs.classificar_day_trade(ops)
    dt = c[c["modalidade"] == "day_trade"]
    comum = c[c["modalidade"] == "comum"]
    assert set(dt["lado"]) == {"C", "V"} and dt[dt["lado"] == "C"]["qtd"].iloc[0] == 100
    assert len(comum) == 1 and comum.iloc[0]["lado"] == "C" and comum.iloc[0]["qtd"] == 200
    # custos sao rateados pela quantidade
    assert abs(comum.iloc[0]["custos"] - 3.0 * 200 / 300) < 1e-12


def test_prejuizo_de_day_trade_nao_compensa_com_comum(apuracao):
    nov = _mes(apuracao, "2026-11")
    dez = _mes(apuracao, "2026-12")
    prejuizo = -(100 * (10.00 - 9.00) + 1.0 + 1.0)
    assert abs(nov["resultado_day_trade"] - prejuizo) < 1e-9
    assert abs(nov["prejuizo_day_trade"] - prejuizo) < 1e-9
    assert nov["prejuizo_comum"] == 0.0                         # nao vazou para o comum
    lucro = 100 * (13.00 - 10.00) - (1.0 + 1.0)
    assert abs(dez["base_day_trade"] - (lucro + prejuizo)) < 1e-9
    assert abs(dez["imposto_day_trade"] - (lucro + prejuizo) * fs.ALIQUOTA_DAY_TRADE) < 1e-9


# ─────────────────────────────────────────────────────────────
# Futuros, prejuizo comum e DARF minimo
# ─────────────────────────────────────────────────────────────
def test_ajuste_diario_de_futuro_entra_na_base_comum(apuracao):
    ago = _mes(apuracao, "2026-08")
    assert abs(ago["ajuste_futuros"] - (500.0 - 10.0)) < 1e-9
    assert abs(ago["resultado_comum_tributavel"] - 490.0) < 1e-9
    assert abs(ago["imposto_comum"] - 490.0 * fs.ALIQUOTA_COMUM) < 1e-9


def test_prejuizo_comum_e_carregado_e_consumido(apuracao):
    set_ = _mes(apuracao, "2026-09")
    out = _mes(apuracao, "2026-10")
    assert abs(set_["ajuste_futuros"] + 800.0) < 1e-9
    assert abs(set_["prejuizo_comum"] + 800.0) < 1e-9 and set_["base_comum"] == 0.0
    pm = (1000 * 20.00 + 10.0) / 1000
    lucro = 1000 * 22.02 - pm * 1000 - 10.0
    assert abs(out["resultado_comum_tributavel"] - lucro) < 1e-9
    assert abs(out["base_comum"] - (lucro - 800.0)) < 1e-9
    assert out["prejuizo_comum"] == 0.0                          # consumido por inteiro


def test_darf_abaixo_do_minimo_acumula_e_e_recolhido_no_mes_seguinte(apuracao):
    jun = _mes(apuracao, "2026-06")
    jul = _mes(apuracao, "2026-07")
    pm = (100 * 50.00 + 5.0) / 100
    lucro = 100 * 50.70 - pm * 100 - 5.0
    bruto = lucro * fs.ALIQUOTA_COMUM - 100 * 50.70 * fs.IRRF_COMUM
    assert bruto < fs.DARF_MINIMO
    assert jun["darf_devido"] == 0.0 and abs(jun["darf_a_acumular"] - bruto) < 1e-9
    assert abs(jul["darf_devido"] - 2 * bruto) < 1e-9 and jul["darf_a_acumular"] == 0.0
    assert 2 * bruto >= fs.DARF_MINIMO


def test_vencimento_do_darf_e_no_mes_seguinte(apuracao):
    m = _mes(apuracao, "2026-03")
    venc = pd.Timestamp(m["darf_vence"])
    assert venc.year == 2026 and venc.month == 4


# ─────────────────────────────────────────────────────────────
# O caso controverso: prejuizo em mes isento
# ─────────────────────────────────────────────────────────────
def test_prejuizo_em_mes_isento_e_descartado_por_padrao(apuracao):
    mai = _mes(apuracao, "2026-05")
    pm = (200 * 30.00 + 6.0) / 200
    prejuizo = 200 * 25.00 - pm * 200 - 5.0
    assert prejuizo < 0 and mai["isento"]
    assert abs(mai["resultado_acoes"] - prejuizo) < 1e-9
    assert mai["resultado_comum_tributavel"] == 0.0
    assert mai["prejuizo_comum"] == 0.0                          # leitura conservadora


def test_a_leitura_alternativa_e_calculada_e_a_diferenca_reportada(apuracao):
    outra = fs.apurar(OPERACOES, vendas_externas=EXTERNAS, ajustes_futuros=AJUSTES,
                      prejuizo_isento_compensa=True)
    pm = (200 * 30.00 + 6.0) / 200
    prejuizo = 200 * 25.00 - pm * 200 - 5.0
    mai = outra["mensal"][outra["mensal"]["mes"] == "2026-05"].iloc[0]
    assert abs(mai["prejuizo_comum"] - prejuizo) < 1e-9         # aqui o prejuizo fica
    imposto_a = apuracao["mensal"]["imposto_total"].sum()
    imposto_b = outra["mensal"]["imposto_total"].sum()
    assert imposto_b < imposto_a                                 # compensar paga menos
    assert abs(apuracao["divergencia_prejuizo_isento"] - (imposto_b - imposto_a)) < 1e-6
    assert apuracao["divergencia_prejuizo_isento"] < 0


# ─────────────────────────────────────────────────────────────
# Proventos, memoria e exportacao
# ─────────────────────────────────────────────────────────────
def test_jcp_paga_quinze_por_cento_na_fonte_e_dividendo_e_isento():
    p = pd.DataFrame([
        {"data": "2026-03-10", "ticker": "ABCD3", "tipo": "JCP", "valor": 1000.0, "pagador": "ABCD"},
        {"data": "2026-03-10", "ticker": "ABCD3", "tipo": "DIVIDENDO", "valor": 2000.0, "pagador": "ABCD"},
    ])
    r = fs.proventos_retidos(p).set_index("tipo")
    assert abs(r.loc["JCP", "retido"] - 1000.0 * fs.IR_JCP) < 1e-12
    assert r.loc["DIVIDENDO", "retido"] == 0.0


def test_dividendo_acima_do_limite_mensal_retem_dez_por_cento():
    p = pd.DataFrame([{"data": "2026-03-10", "ticker": "ABCD3", "tipo": "DIVIDENDO",
                       "valor": 60_000.0, "pagador": "ABCD"}])
    r = fs.proventos_retidos(p).iloc[0]
    esperado = (60_000.0 - fs.LIMITE_DIVIDENDO_MES) * fs.IRRF_DIVIDENDO
    assert abs(r["retido"] - esperado) < 1e-12
    assert abs(r["valor_liquido"] - (60_000.0 - esperado)) < 1e-12
    assert fs.proventos_retidos(None).empty


def test_memoria_de_calculo_cobre_todo_mes_apurado(apuracao):
    m = fs.memoria_calculo(apuracao)
    assert set(m["mes"]) == set(apuracao["mensal"]["mes"])
    mar = m[m["mes"] == "2026-03"]
    assert (mar["etapa"].str.startswith("8 darf")).any()
    recolher = mar[mar["descricao"] == "a recolher"].iloc[0]["valor"]
    assert abs(recolher - _mes(apuracao, "2026-03")["darf_devido"]) < 1e-9
    assert fs.memoria_calculo({"mensal": pd.DataFrame()}).empty


def test_resumo_do_mes_e_serializavel(apuracao):
    import json
    r = fs.resumo_mes(apuracao, "2026-03")
    json.dumps(r)                                                # nao pode ter NaN nem numpy
    assert r["mes"] == "2026-03" and r["isento"] is False
    assert r["aviso"] and "contador" in r["aviso"]
    vazio = fs.resumo_mes({"mensal": pd.DataFrame()})
    json.dumps(vazio)
    assert vazio["isencao_restante"] == fs.ISENCAO_VENDAS_MES


def test_exporta_revar_e_grava_apuracao(apuracao, tmp_path):
    caminho = str(tmp_path / "revar.csv")
    fs.exportar_revar(apuracao, caminho)
    lido = pd.read_csv(caminho, sep=";", decimal=",")
    assert len(lido) == len(apuracao["mensal"])
    assert (lido["codigo_darf"].astype(str) == fs.CODIGO_DARF).all()
    caminhos = fs.gravar(apuracao, str(tmp_path))
    assert pd.read_csv(caminhos["apuracao"], sep=";", decimal=",").shape[0] == len(apuracao["mensal"])
    assert not pd.read_csv(caminhos["memoria"], sep=";", decimal=",").empty


# ─────────────────────────────────────────────────────────────
# Robustez
# ─────────────────────────────────────────────────────────────
def test_entrada_vazia_nao_quebra():
    a = fs.apurar(None)
    assert a["mensal"].empty and list(a["mensal"].columns) == fs.COLUNAS_APURACAO
    assert fs.realizar(None).empty and fs.classificar_day_trade(None).empty
    assert fs.posicao_media(None).empty
    assert fs.normalizar(pd.DataFrame()).empty


def test_operacao_com_lixo_e_descartada_sem_levantar():
    sujo = pd.DataFrame([
        _op("2026-01-05", "ABCD3", "C", 0, 10.0, 0.0),           # quantidade zero
        {"data": "2026-01-06", "ticker": "X3", "classe": "acao", "lado": "Z", "qtd": 10,
         "preco": 1.0, "valor": 10.0, "custos": 0.0, "fonte": "t"},   # lado invalido
        {"data": "2026-01-07", "ticker": "Y3", "classe": "esquisito", "lado": "C", "qtd": 10,
         "preco": 2.0, "valor": 20.0, "custos": 0.0, "fonte": "t"},   # classe desconhecida
    ])
    n = fs.normalizar(sujo)
    assert len(n) == 1 and n.iloc[0]["ticker"] == "Y3" and n.iloc[0]["classe"] == "acao"


def test_venda_sem_posicao_nao_levanta():
    ops = pd.DataFrame([_op("2026-02-10", "SEMPOS3", "V", 100, 10.0, 1.0)])
    r = fs.realizar(ops)
    assert len(r) == 1 and abs(r.iloc[0]["resultado"] - (100 * 10.0 - 1.0)) < 1e-9

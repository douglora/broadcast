"""
Testes do paper trading (M13): o casamento da boleta com o negocio-a-negocio.

O que se testa aqui e a HONESTIDADE do simulador, nao se ele "executa bem": um simulador
que executa tudo sempre produz slippage otimo e taxa de execucao de 100%, e os dois
numeros do criterio de pronto viram decoracao. Por isso os testes cobrem, um por um, os
tres jeitos de nao executar - preco fora do limite, teto de participacao e negocio
anterior a hora de envio - e so depois o slippage, plantado com precos escolhidos para que
a media seja conhecida na mao.
"""
import numpy as np
import pandas as pd

from quant import custos as cst
from quant.execucao import boleta as bo
from quant.execucao import paper as pp

DATA = "2026-09-08"


def _boleta(ordens, emitida=True, hora_envio=bo.HORA_ENVIO):
    """Boleta minima no formato de boleta.gerar (so o que simular() le)."""
    linhas = []
    for o in ordens:
        linha = {"ticker": "ABCD3", "lado": "C", "qtd": 100, "preco_limite": 10.0,
                 "validade": bo.VALIDADE, "motivo": "entrada", "custo": 0.0,
                 "fatia": "1/1", "adtv": 50e6, "fracionario": False}
        linha.update(o)
        linhas.append(linha)
    return {"data": DATA, "id": DATA.replace("-", ""), "emitida": emitida,
            "motivo_bloqueio": [], "custo_total": 0.0, "ordens": linhas,
            "hora_envio": hora_envio, "validade": bo.VALIDADE}


def _negocios(linhas, ticker="ABCD3"):
    """(hora, preco, quantidade) -> DataFrame no formato de arquivar_b3."""
    return pd.DataFrame([{"ticker": ticker, "hora": h, "preco": p, "quantidade": q}
                         for h, p, q in linhas])


# ─────────────────────────────────────────────────────────────
# Casamento: os tres jeitos de nao executar
# ─────────────────────────────────────────────────────────────
def test_negocio_exatamente_no_preco_limite_executa():
    b = _boleta([{"qtd": 100, "preco_limite": 10.00}])
    f = pp.simular(b, _negocios([("10:30:00", 10.00, 100)]), participacao_max=1.0)
    assert len(f) == 1
    assert int(f["qtd"].iloc[0]) == 100
    assert abs(float(f["preco"].iloc[0]) - 10.00) < 1e-9
    assert f["origem"].iloc[0] == "paper"
    assert {"data", "hora", "boleta", "ticker", "lado", "qtd", "preco",
            "corretagem", "emolumentos", "origem", "obs"} <= set(f.columns)
    # o custo do fill so traz o que e FATO: emolumentos da B3 e corretagem zero
    assert abs(float(f["emolumentos"].iloc[0]) - 100 * 10.00 * cst.TAXA_B3) < 1e-12
    assert float(f["corretagem"].iloc[0]) == 0.0


def test_um_centavo_acima_do_limite_nao_executa_numa_compra():
    b = _boleta([{"qtd": 100, "lado": "C", "preco_limite": 10.00}])
    f = pp.simular(b, _negocios([("10:30:00", 10.01, 1000)]), participacao_max=1.0)
    assert len(f) == 0
    # e o espelho na venda: um centavo abaixo tambem nao executa
    v = _boleta([{"qtd": 100, "lado": "V", "preco_limite": 10.00}])
    assert len(pp.simular(v, _negocios([("10:30:00", 9.99, 1000)]), participacao_max=1.0)) == 0
    assert len(pp.simular(v, _negocios([("10:30:00", 10.00, 1000)]), participacao_max=1.0)) == 1


def test_quantidade_executada_respeita_o_teto_de_participacao():
    # volume do periodo = 10.000 acoes; 1% = 100 acoes, mesmo com a ordem pedindo 1.000
    b = _boleta([{"qtd": 1_000, "preco_limite": 10.00}])
    negocios = _negocios([("10:30:00", 9.90, 5_000), ("10:40:00", 9.95, 5_000)])
    f = pp.simular(b, negocios, participacao_max=bo.MAX_PARTICIPACAO)
    assert int(f["qtd"].iloc[0]) == int(bo.MAX_PARTICIPACAO * 10_000)
    assert "teto" in f["obs"].iloc[0]
    # sem o teto, a mesma boleta executa tudo o que pediu
    solto = pp.simular(b, negocios, participacao_max=1.0)
    assert int(solto["qtd"].iloc[0]) == 1_000


def test_negocios_antes_da_hora_de_envio_sao_ignorados():
    b = _boleta([{"qtd": 100, "preco_limite": 10.00}])
    cedo = _negocios([("10:00:00", 9.50, 1_000)])       # otimo preco, mas a ordem nao existia
    assert len(pp.simular(b, cedo, participacao_max=1.0)) == 0
    # exatamente na hora de envio ja vale
    na_hora = _negocios([(bo.HORA_ENVIO + ":00", 9.50, 1_000)])
    f = pp.simular(b, na_hora, participacao_max=1.0)
    assert len(f) == 1 and abs(float(f["preco"].iloc[0]) - 9.50) < 1e-9


def test_boleta_bloqueada_ou_vazia_nao_gera_fill_nenhum():
    bloqueada = _boleta([{"qtd": 100, "preco_limite": 10.00}], emitida=False)
    negocios = _negocios([("10:30:00", 9.00, 10_000)])
    assert len(pp.simular(bloqueada, negocios, participacao_max=1.0)) == 0
    assert len(pp.simular(_boleta([]), negocios)) == 0
    assert len(pp.simular(None, negocios)) == 0


def test_normalizar_aceita_o_tickercsv_cru_da_b3():
    cru = pd.DataFrame([{"TckrSymb": "abcd3", "GrssTradAmt": "10,50",
                         "TradQty": "100", "NtryTm": "103015123"}])
    d = pp.normalizar_negocios(cru)
    assert list(d.columns) == pp.COLUNAS_NEGOCIOS
    assert d["ticker"].iloc[0] == "ABCD3"
    assert d["hora"].iloc[0] == "10:30:15"
    assert abs(d["preco"].iloc[0] - 10.50) < 1e-9
    # coluna faltando nao levanta: devolve o schema vazio
    assert len(pp.normalizar_negocios(pd.DataFrame([{"TckrSymb": "ABCD3"}]))) == 0
    assert len(pp.normalizar_negocios(None)) == 0


# ─────────────────────────────────────────────────────────────
# Medicao
# ─────────────────────────────────────────────────────────────
def test_medir_slippage_recupera_um_slippage_plantado():
    # dois negocios de 100 acoes a 9,90 e 9,98: preco medio 9,94 contra limite de 10,00
    b = _boleta([{"qtd": 200, "preco_limite": 10.00}])
    negocios = _negocios([("10:30:00", 9.90, 100), ("10:40:00", 9.98, 100)])
    f = pp.simular(b, negocios, participacao_max=1.0)
    assert abs(float(f["preco"].iloc[0]) - 9.94) < 1e-9
    m = pp.medir_slippage(b, f)
    assert abs(m["preco_medio_obtido"] - 9.94) < 1e-9
    assert abs(m["preco_limite"] - 10.00) < 1e-9
    # (9,94 - 10,00) / 10,00 = -60 bps: negativo porque uma ordem limitada nunca
    # executa pior que o proprio limite - o custo dela aparece na taxa de execucao
    assert abs(m["slippage_bps"] - (9.94 - 10.00) / 10.00 * 10_000) < 1e-6
    assert abs(m["taxa_execucao"] - 1.0) < 1e-12
    assert m["slippage_vwap_bps"] is None            # sem barras nao ha VWAP para comparar
    # com o VWAP do dia armado em 9,90 exatos, o slippage contra o VWAP e desfavoravel
    barras = _negocios([("10:00:00", 9.86, 200), ("10:30:00", 9.90, 100),
                        ("10:40:00", 9.98, 100)])
    m2 = pp.medir_slippage(b, f, barras=barras)
    assert abs(m2["slippage_vwap_bps"] - (9.94 - 9.90) / 9.90 * 10_000) < 1e-6


def test_taxa_execucao_e_a_quantidade_que_saiu_sobre_a_pedida():
    b = _boleta([{"qtd": 200, "preco_limite": 10.00}])
    # so 100 acoes negociam dentro do limite; as outras 400 saem acima dele
    negocios = _negocios([("10:30:00", 10.00, 100), ("10:40:00", 10.05, 400)])
    m = pp.medir_slippage(b, pp.simular(b, negocios, participacao_max=1.0))
    assert abs(m["taxa_execucao"] - 100 / 200) < 1e-12
    assert m["qtd_executada"] == 100 and m["qtd_pedida"] == 200
    assert m["por_ordem"][0]["taxa_execucao"] == 0.5


def test_sem_negocio_nenhum_a_taxa_e_zero_e_nada_levanta():
    b = _boleta([{"qtd": 200, "preco_limite": 10.00}])
    for negocios in (None, pd.DataFrame(), _negocios([])):
        f = pp.simular(b, negocios)
        assert len(f) == 0
        m = pp.medir_slippage(b, f)
        assert m["taxa_execucao"] == 0.0
        assert m["slippage_bps"] is None             # zero seria dizer "executou no preco"
        assert m["slippage_vwap_bps"] is None
        assert m["custo_realizado"] == 0.0
        assert m["preco_medio_obtido"] is None
    # boleta sem ordem nenhuma tambem nao levanta
    assert pp.medir_slippage(_boleta([]), pd.DataFrame())["taxa_execucao"] == 0.0
    assert pp.medir_slippage(None, None)["taxa_execucao"] == 0.0


def test_custo_realizado_soma_taxas_e_diferenca_de_preco():
    b = _boleta([{"qtd": 100, "preco_limite": 10.00}])
    f = pp.simular(b, _negocios([("10:30:00", 9.90, 100)]), participacao_max=1.0)
    m = pp.medir_slippage(b, f)
    taxas = 100 * 9.90 * cst.TAXA_B3
    assert abs(m["taxas"] - taxas) < 1e-12
    # comprou 10 centavos abaixo do limite: a diferenca de preco entra como custo negativo
    assert abs(m["custo_realizado"] - (taxas + (9.90 - 10.00) * 100)) < 1e-9


def test_acumular_pondera_pelo_financeiro():
    dia_pequeno = {"financeiro": 1_000.0, "slippage_bps": 10.0, "slippage_vwap_bps": 10.0,
                   "qtd_pedida": 100.0, "qtd_executada": 100.0, "custo_realizado": 1.0}
    dia_grande = {"financeiro": 3_000.0, "slippage_bps": 50.0, "slippage_vwap_bps": 50.0,
                  "qtd_pedida": 300.0, "qtd_executada": 150.0, "custo_realizado": 5.0}
    a = pp.acumular([dia_pequeno, dia_grande])
    esperado = (10.0 * 1_000 + 50.0 * 3_000) / (1_000 + 3_000)
    assert abs(a["slippage_bps"] - esperado) < 1e-9
    assert abs(a["slippage_vwap_bps"] - esperado) < 1e-9
    assert abs(a["slippage_bps"] - (10.0 + 50.0) / 2) > 1e-6      # nao e media simples
    assert abs(a["taxa_execucao"] - (100 + 150) / (100 + 300)) < 1e-12
    assert a["n_pregoes"] == 2 and abs(a["custo_realizado"] - 6.0) < 1e-12
    vazio = pp.acumular([])
    assert vazio["n_pregoes"] == 0 and vazio["taxa_execucao"] == 0.0
    assert vazio["slippage_bps"] is None


def test_veredito_usa_os_dois_numeros_do_criterio_de_pronto():
    bom = {"taxa_execucao": 0.80, "slippage_vwap_bps": 30.0}
    assert pp.veredito(bom, modelado_bps=25.0)[0] is True          # 30 <= 1,5 x 25
    passou, motivos = pp.veredito({"taxa_execucao": 0.30, "slippage_vwap_bps": 5.0},
                                  modelado_bps=25.0)
    assert passou is False and any("execucao" in m for m in motivos)
    passou, motivos = pp.veredito({"taxa_execucao": 0.90, "slippage_vwap_bps": 60.0},
                                  modelado_bps=25.0)
    assert passou is False and any("slippage" in m for m in motivos)


def test_simulacao_nunca_executa_mais_do_que_o_pedido_nem_fora_do_limite():
    rng = np.random.default_rng(20260908)
    limite = 10.00
    for _ in range(50):
        pedida = int(rng.integers(100, 5_000))
        linhas = [(f"1{rng.integers(0, 6):01d}:{rng.integers(0, 60):02d}:00",
                   round(float(rng.uniform(9.5, 10.5)), 2),
                   int(rng.integers(100, 2_000))) for _ in range(40)]
        b = _boleta([{"qtd": pedida, "preco_limite": limite}])
        negocios = _negocios(linhas)
        f = pp.simular(b, negocios, participacao_max=bo.MAX_PARTICIPACAO)
        if len(f) == 0:
            continue
        executada = int(f["qtd"].iloc[0])
        d = pp.normalizar_negocios(negocios)
        vivos = d[d["hora"].str[:5] >= bo.HORA_ENVIO]
        teto = int(bo.MAX_PARTICIPACAO * float(vivos["quantidade"].sum()))
        assert 0 < executada <= min(pedida, teto)
        assert float(f["preco"].iloc[0]) <= limite + 1e-9        # compra nunca paga mais
        m = pp.medir_slippage(b, f)
        assert 0.0 < m["taxa_execucao"] <= 1.0
        assert m["slippage_bps"] <= 1e-9

"""
Simulacao ao vivo: a garantia de que o vivo e o fechamento nao podem divergir.

O teste que importa aqui e `test_pedacos_dao_o_mesmo_que_a_fita_inteira`. Todo o desenho do
modulo existe para ele passar: se o estado ao vivo no fim do pregao pudesse diferir do que a
medicao de fechamento produz, o paper trading inteiro viraria teatro - "funcionou na
simulacao" nao significaria nada, e a primeira vez que alguem fosse conferir seria com
dinheiro dentro.

O segundo teste em importancia e o do tique de cotacao: o MetaTrader entrega mudanca de book
na mesma sequencia dos negocios, e contar book como negocio infla o volume do periodo. Como
o volume do periodo e o que limita a execucao pelo teto de participacao, o teto viraria
decoracao e a simulacao passaria a executar tudo sempre - que e exatamente o jeito de um
simulador mentir para quem o escreveu.
"""
import pandas as pd
import pytest

from quant.execucao import boleta as bo
from quant.execucao import paper
from quant.execucao import paper_vivo as pv

DATA = "2026-09-08"


def _boleta(ordens, emitida=True, hora_envio=bo.HORA_ENVIO):
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
    return pd.DataFrame([{"ticker": ticker, "hora": h, "preco": p, "quantidade": q}
                         for h, p, q in linhas])


def _fita_longa(n=240, ticker="ABCD3"):
    """Uma fita plausivel: do 10:20 em diante, preco oscilando em torno do limite."""
    linhas = []
    for i in range(n):
        hora = f"{10 + (20 + i) // 60:02d}:{(20 + i) % 60:02d}:00"
        preco = 9.90 + ((i * 7) % 11) / 100.0        # 9,90 a 10,00, deterministico
        linhas.append((hora, round(preco, 2), 100.0))
    return _negocios(linhas, ticker)


# ─────────────────────────────────────────────────────────────
# A garantia central
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("pedacos", [1, 2, 3, 7, 13, 60])
def test_pedacos_dao_o_mesmo_que_a_fita_inteira(pedacos):
    """A MESMA fita, entregue em N pedacos, tem de dar exatamente o mesmo resultado.

    E o que garante que o numero que o painel mostra as 16:50 e o mesmo que o relatorio
    de fechamento vai publicar. Sem isso, o estagio 1 nao prova nada sobre o estagio 3.
    """
    b = _boleta([{"qtd": 1000, "preco_limite": 10.00}])
    fita = _fita_longa()

    inteira = pv.Sessao(b)
    inteira.aplicar(fita)

    picado = pv.Sessao(b)
    tamanho = max(1, len(fita) // pedacos)
    for i in range(0, len(fita), tamanho):
        picado.aplicar(fita.iloc[i:i + tamanho])

    a, z = inteira.estado(), picado.estado()
    assert a["totais"] == z["totais"]
    assert a["ordens"] == z["ordens"]
    assert len(inteira.fills) == len(picado.fills)


def test_o_vivo_no_fim_e_igual_ao_fechamento():
    """O estado ao vivo com a fita toda == `paper.simular` sobre a mesma fita."""
    b = _boleta([{"qtd": 1000, "preco_limite": 10.00}])
    fita = _fita_longa()

    s = pv.Sessao(b)
    s.aplicar(fita)
    fechamento = paper.simular(b, fita)

    assert len(s.fills) == len(fechamento)
    assert s.fills["qtd"].tolist() == fechamento["qtd"].tolist()
    assert s.fills["preco"].round(6).tolist() == fechamento["preco"].round(6).tolist()


def test_medicao_usa_a_mesma_funcao_do_fechamento():
    b = _boleta([{"qtd": 1000, "preco_limite": 10.00}])
    fita = _fita_longa()
    s = pv.Sessao(b)
    s.aplicar(fita)
    assert s.medicao() == paper.medir_slippage(b, paper.simular(b, fita), barras=fita)


# ─────────────────────────────────────────────────────────────
# Tique de cotacao nao e negocio
# ─────────────────────────────────────────────────────────────
def test_mudanca_de_book_nao_vira_negocio():
    """Tique com volume zero e mudanca de bid/ask. Contar como negocio infla o volume do
    periodo, e o volume do periodo e o que limita a execucao pelo teto de participacao."""
    tiques = [
        {"time": 1757339000, "bid": 9.98, "ask": 10.02, "last": 10.00, "volume": 0, "flags": 6},
        {"time": 1757339001, "bid": 9.98, "ask": 10.02, "last": 10.00, "volume": 500, "flags": 8},
        {"time": 1757339002, "bid": 9.99, "ask": 10.01, "last": 0.0, "volume": 0, "flags": 2},
    ]
    d = pv.de_mt5(tiques, "ABCD3")
    assert len(d) == 1
    assert float(d["quantidade"].iloc[0]) == 500.0


def test_flag_sem_marca_de_negocio_e_descartada():
    """Volume > 0 mas sem TICK_FLAG_LAST: nao e negocio."""
    tiques = [{"time": 1757339001, "last": 10.0, "volume": 300, "flags": 2}]
    assert len(pv.de_mt5(tiques, "ABCD3")) == 0


def test_sem_flags_cai_no_criterio_de_volume_e_preco():
    """Fonte que nao preenche flags: volume > 0 e last > 0 decidem."""
    tiques = [{"time": 1757339001, "last": 10.0, "volume": 300},
              {"time": 1757339002, "last": 0.0, "volume": 300},
              {"time": 1757339003, "last": 10.0, "volume": 0}]
    assert len(pv.de_mt5(tiques, "ABCD3")) == 1


def test_tique_sem_hora_nao_entra():
    assert len(pv.de_mt5([{"last": 10.0, "volume": 100}], "ABCD3")) == 0


def test_lixo_na_entrada_nao_levanta():
    assert len(pv.de_mt5(None, "ABCD3")) == 0
    assert len(pv.de_mt5([None, 3, "x"], "ABCD3")) == 0


# ─────────────────────────────────────────────────────────────
# Marcacao a mercado: nunca inventar preco
# ─────────────────────────────────────────────────────────────
def test_papel_sem_negocio_fica_sem_marcacao():
    """Sem negocio nao ha preco de mercado. Marcar com o fechamento de ontem e o jeito
    silencioso de o P&L mentir."""
    b = _boleta([{"ticker": "ZZZZ3", "qtd": 100, "preco_limite": 10.0}])
    s = pv.Sessao(b)
    s.aplicar(_negocios([("10:30:00", 9.95, 1000.0)], ticker="ABCD3"))
    o = s.estado()["ordens"][0]
    assert o["executado"] == 0
    assert o["preco_mercado"] is None and o["aberto"] is None


def test_aberto_tem_o_sinal_do_lado():
    """Compra ganha quando o mercado sobe; venda ganha quando cai."""
    compra = pv.Sessao(_boleta([{"lado": "C", "qtd": 100, "preco_limite": 10.00}]))
    compra.aplicar(_negocios([("10:30:00", 10.00, 100_000.0), ("11:00:00", 11.00, 100.0)]))
    assert compra.estado()["ordens"][0]["aberto"] > 0

    venda = pv.Sessao(_boleta([{"lado": "V", "qtd": 100, "preco_limite": 10.00}]))
    venda.aplicar(_negocios([("10:30:00", 10.00, 100_000.0), ("11:00:00", 11.00, 100.0)]))
    assert venda.estado()["ordens"][0]["aberto"] < 0


def test_boleta_bloqueada_nao_executa_nada():
    b = _boleta([{"qtd": 100, "preco_limite": 10.0}], emitida=False)
    s = pv.Sessao(b)
    e = s.aplicar(_fita_longa())
    assert e["emitida"] is False
    assert e["totais"]["qtd_executada"] == 0


def test_estado_vazio_antes_do_primeiro_tique():
    s = pv.Sessao(_boleta([{"qtd": 100, "preco_limite": 10.0}]))
    e = s.estado()
    assert e["negocios_vistos"] == 0
    assert e["ordens"][0]["executado"] == 0
    assert e["totais"]["taxa_execucao"] == 0.0


def test_estado_e_serializavel_em_json():
    """O painel le isto pela ponte: nada de NaN, Timestamp ou numpy."""
    import json
    s = pv.Sessao(_boleta([{"qtd": 1000, "preco_limite": 10.0}]))
    s.aplicar(_fita_longa())
    json.dumps(s.estado())


def test_ultimo_preco_e_o_ultimo_negocio_visto():
    s = pv.Sessao(_boleta([{"qtd": 100, "preco_limite": 10.0}]))
    s.aplicar(_negocios([("10:30:00", 9.90, 100.0), ("11:00:00", 9.95, 100.0)]))
    assert s.ultimo_preco("ABCD3") == 9.95
    assert s.ultimo_preco("abcd3") == 9.95

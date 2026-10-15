"""Swing: o livro guarda as operacoes, concilia com as barras oficiais e nao duplica nada."""
import numpy as np
import pandas as pd
import pytest

from quant.dados import calendario
from quant.swing import estado as est
from quant.testes.swing_fixture import barra, painel_plano


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_SWING_DIR", str(tmp_path / "swing"))
    return tmp_path / "swing"


def _sessoes(a, n):
    return [pd.Timestamp(d) for d in calendario.pregoes(a, "2026-12-30")[:n]]


def _medida(entrada="2026-10-13", stop_dist=2.0, alvo_dist=4.0, prazo=5, ticker="AAAA3", setup="A1"):
    return est.nova_pendente(setup, ticker, "2026-10-09", entrada, stop_dist, alvo_dist, prazo, 2e7, porque="teste", overlays={"top": True, "ibov_ok": False},
                             preco_ref=20.0)


def test_pendente_so_entra_quando_a_barra_do_dia_existe(pasta):
    datas = _sessoes("2026-10-01", 8)                      # 01/10 ... 13/10 (12/10 e feriado)
    p = painel_plano(datas[:6])                            # barras ate 08/10; a de 13/10 ainda nao existe
    e = est.vazio()
    e["posicoes"].append(_medida())
    assert est.conciliar(e, p, hoje="2026-10-13") == []
    assert e["posicoes"][0]["status"] == "pendente"        # nada mudou: sem barra, sem entrada


def test_medida_entra_na_abertura_oficial_e_sai_no_alvo(pasta):
    datas = [d for d in _sessoes("2026-10-01", 12)]
    p = painel_plano(datas)
    d_ent = "2026-10-13"
    barra(p, "AAAA3", d_ent, o=20.0, h=21.0, l=19.5, c=20.5)
    barra(p, "AAAA3", "2026-10-14", o=20.6, h=24.5, l=20.2, c=24.0)            # 24 e o alvo (20 + 4)
    e = est.vazio()
    e["posicoes"].append(_medida(entrada=d_ent))
    novas = est.conciliar(e, p, hoje="2026-10-20")
    assert len(novas) == 1 and novas[0]["motivo_saida"] == "alvo" and novas[0]["saida_em"] == "2026-10-14"
    assert novas[0]["preco_entrada"] == 20.0 and novas[0]["qtd"] == 300 and novas[0]["modo"] == "medida"       # R$ 6.000 / R$ 20 = 300
    assert novas[0]["resultado_rs"] == pytest.approx(300 * 4.0 - novas[0]["custo_entrada"] - novas[0]["custo_saida"])
    assert e["posicoes"] == [] and len(est.fechadas()) == 1


def test_stop_no_mesmo_dia_da_entrada_e_stop_vence_alvo_na_mesma_barra(pasta):
    p = painel_plano(_sessoes("2026-10-01", 12))
    barra(p, "AAAA3", "2026-10-13", o=20.0, h=25.0, l=17.0, c=21.0)           # toca alvo (24) e stop (18) na mesma barra
    e = est.vazio()
    e["posicoes"].append(_medida())
    n = est.conciliar(e, p, hoje="2026-10-20")
    assert n[0]["motivo_saida"] == "stop" and n[0]["preco_saida"] == pytest.approx(18.0) and n[0]["saida_em"] == "2026-10-13"


def test_gap_contra_sai_na_abertura_pior_que_o_stop(pasta):
    p = painel_plano(_sessoes("2026-10-01", 12))
    barra(p, "AAAA3", "2026-10-14", o=16.0, h=16.5, l=15.5, c=16.0)           # abre abaixo do stop (18)
    e = est.vazio()
    e["posicoes"].append(_medida())
    n = est.conciliar(e, p, hoje="2026-10-20")
    assert n[0]["motivo_saida"] == "gap_stop" and n[0]["preco_saida"] == pytest.approx(16.0)
    assert n[0]["r_multiplo"] < -1.0                                            # a perda passou do risco planejado


def test_sem_stop_nem_alvo_sai_por_tempo_no_fechamento_do_ultimo_pregao_do_prazo(pasta):
    datas = _sessoes("2026-10-01", 12)
    p = painel_plano(datas)
    barra(p, "AAAA3", "2026-10-19", c=21.0)                                    # 5o pregao a partir de 13/10: 13,14,15,16,19
    e = est.vazio()
    e["posicoes"].append(_medida(prazo=5))
    n = est.conciliar(e, p, hoje="2026-10-26")
    assert n[0]["motivo_saida"] == "tempo" and n[0]["saida_em"] == "2026-10-19" and n[0]["preco_saida"] == 21.0 and n[0]["pregoes"] == 5


def test_barra_de_hoje_nao_conta_ainda_incompleta(pasta):
    p = painel_plano(_sessoes("2026-10-01", 12))
    barra(p, "AAAA3", "2026-10-14", o=20.0, h=30.0, l=20.0, c=30.0)           # alvo batido em 14/10
    e = est.vazio()
    e["posicoes"].append(_medida())
    assert est.conciliar(e, p, hoje="2026-10-14") == []                         # "hoje" e 14/10: a barra do dia nao esta completa
    assert est.conciliar(e, p, hoje="2026-10-15")[0]["motivo_saida"] == "alvo"


def test_dia_com_dado_ruim_descarta_a_medida_como_na_pesquisa(pasta):
    p = painel_plano(_sessoes("2026-10-01", 12))
    p.ruim[list(p.datas).index(pd.Timestamp("2026-10-14")), 0] = True
    e = est.vazio()
    e["posicoes"].append(_medida())
    n = est.conciliar(e, p, hoje="2026-10-26")
    assert n[0]["status"] == "descartada" and "inválido" in n[0]["motivo_descarte"]


def test_papel_sem_negocio_no_dia_da_entrada_e_descartado(pasta):
    p = painel_plano(_sessoes("2026-10-01", 12))
    p.O[list(p.datas).index(pd.Timestamp("2026-10-13")), 0] = np.nan
    e = est.vazio()
    e["posicoes"].append(_medida())
    assert est.conciliar(e, p, hoje="2026-10-20")[0]["status"] == "descartada"


def test_conciliar_duas_vezes_nao_duplica(pasta):
    p = painel_plano(_sessoes("2026-10-01", 12))
    barra(p, "AAAA3", "2026-10-14", o=20.0, h=30.0, l=20.0, c=30.0)
    e = est.vazio()
    e["posicoes"].append(_medida())
    est.conciliar(e, p, hoje="2026-10-20")
    est.conciliar(e, p, hoje="2026-10-20")
    assert len(est.fechadas()) == 1
    e["posicoes"].append(_medida())                                           # mesmo id de novo: nao entra se ja foi fechado
    assert est.adicionar(e, _medida()) is False


def test_posicao_com_capital_aberta_ao_vivo_e_fechada_pela_barra_se_o_robo_nao_viu(pasta):
    p = painel_plano(_sessoes("2026-10-01", 12))
    barra(p, "AAAA3", "2026-10-14", o=20.0, h=20.5, l=17.0, c=19.0)           # derrubou o stop (18) durante o dia
    pos = est.nova_posicao("C1", "AAAA3", "2026-10-09", 20.0, 2.0, 4.0, 10, 100, "2026-10-13", 2e7, modo="capital")
    e = est.vazio()
    e["posicoes"].append(pos)
    n = est.conciliar(e, p, hoje="2026-10-20")
    assert n[0]["modo"] == "capital" and n[0]["motivo_saida"] == "stop" and n[0]["origem_saida"] == "conciliacao"


def test_arquivo_de_estado_vai_e_volta(pasta):
    e = est.vazio()
    e["posicoes"].append(_medida())
    est.anotar(e, "teste", "uma linha")
    est.salvar(e)
    de_volta = est.carregar()
    assert de_volta["posicoes"][0]["id"] == e["posicoes"][0]["id"] and de_volta["diario"][-1]["texto"] == "uma linha"
    assert est.carregar(str(pasta / "nao_existe.json"))["posicoes"] == []


def test_entrada_fora_da_abertura_nao_usa_a_minima_de_antes_da_entrada(pasta):
    """15/10/2026 (achado 9): a posicao que entrou as 15h10 a R$ 22 nao pode sair no stop pela minima da manha; a base e o preco de entrada."""
    p = painel_plano(_sessoes("2026-10-01", 12))
    barra(p, "AAAA3", "2026-10-13", o=20.0, h=22.5, l=18.0, c=22.2)           # a minima (18) e de antes da entrada; o stop e 20
    barra(p, "AAAA3", "2026-10-14", o=22.3, h=26.5, l=22.0, c=26.0)           # alvo 26 (22 + 4) no dia seguinte
    e = est.vazio()
    pos = est.nova_posicao("C1", "AAAA3", "2026-10-09", 22.0, 2.0, 4.0, 10, 100, "2026-10-13", 2e7, modo="capital", porque="teste",
                           extras={"entrada_fora_da_abertura": True, "hora_entrada": "15:10"})
    e["posicoes"].append(pos)
    n = est.conciliar(e, p, hoje="2026-10-20")
    assert len(n) == 1 and n[0]["motivo_saida"] == "alvo" and n[0]["saida_em"] == "2026-10-14" and n[0]["preco_saida"] == pytest.approx(26.0)


def test_entrada_fora_da_abertura_fecha_no_stop_se_o_fechamento_do_dia_ja_furou(pasta):
    p = painel_plano(_sessoes("2026-10-01", 12))
    barra(p, "AAAA3", "2026-10-13", o=20.0, h=22.5, l=19.0, c=19.5)           # o fechamento (posterior a entrada) ja esta abaixo do stop (20)
    e = est.vazio()
    e["posicoes"].append(est.nova_posicao("C1", "AAAA3", "2026-10-09", 22.0, 2.0, 4.0, 10, 100, "2026-10-13", 2e7, modo="capital",
                                          extras={"entrada_fora_da_abertura": True}))
    n = est.conciliar(e, p, hoje="2026-10-20")
    assert n[0]["motivo_saida"] == "stop" and n[0]["saida_em"] == "2026-10-13" and n[0]["preco_saida"] == pytest.approx(20.0)

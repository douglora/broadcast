"""
Regra do robo de day trade (versao 0): cada caso com a conta feita a mao no comentario.
"""
from datetime import datetime

import pytest

from quant.comum import agora_brt
from quant.daytrade import estrategia as es

TZ = agora_brt().tzinfo


def _ts(h, m, s=0):
    return datetime(2026, 10, 8, h, m, s, tzinfo=TZ).timestamp()


def _hora(h, m, s=0):
    return f"{h:02d}:{m:02d}:{s:02d}"


def _faixa(estado, ini_min, fim_min, minimo, maximo):
    """Barras fechadas das 9h00+ini ate 9h00+fim, todas com a mesma faixa."""
    for k in range(ini_min, fim_min):
        estado.barras.append([_ts(9, 0) + 60 * k, maximo, minimo, (maximo + minimo) / 2])


def test_compra_no_rompimento_da_maxima_acima_do_medio():
    p = es.Parametros()
    e = es.EstadoAtivo("WINFUT")
    _faixa(e, 0, 31, 204200.0, 204500.0)          # 9h00 a 9h30: faixa de 300 pontos
    # 9h31: 204.505 = maxima (204.500) + 1 tick, acima do medio (204.300): compra
    ev = es.passo(e, _ts(9, 31), _hora(9, 31), 204505.0, 204300.0, p)
    assert [x["tipo"] for x in ev] == ["entrada"]
    pos = e.posicao
    # entrada a mercado, 1 tick contra: 204.510. Risco = vai-e-vem de 15 min = 300 pontos (entre 150 e 400).
    # Contratos = 250 / (300 x 0,20) = 4,17 -> 4. Stop 204.210; alvo = entrada + 2 x 300 = 205.110.
    assert (pos.lado, pos.contratos, pos.entrada, pos.stop, pos.alvo) == ("C", 4, 204510.0, 204210.0, 205110.0)
    # andou 1 risco (204.810): stop vai para a entrada
    ev = es.passo(e, _ts(9, 40), _hora(9, 40), 204810.0, 204350.0, p)
    assert [x["tipo"] for x in ev] == ["protecao"] and e.posicao.stop == 204510.0
    # bateu o alvo: sai a 205.110. 600 pontos x 0,20 x 4 = 480,00; custos 2 x 0,30 x 4 = 2,40; liquido 477,60
    ev = es.passo(e, _ts(9, 55), _hora(9, 55), 205115.0, 204500.0, p)
    assert ev[0]["tipo"] == "saida" and ev[0]["motivo"] == "alvo" and ev[0]["saida"] == 205110.0
    assert ev[0]["pontos"] == 600.0 and ev[0]["resultado"] == pytest.approx(477.60)
    assert e.posicao is None and e.operacoes == 1


def test_venda_no_rompimento_da_minima_e_stop():
    p = es.Parametros()
    e = es.EstadoAtivo("WDOFUT")
    _faixa(e, 0, 31, 5030.0, 5035.0)              # faixa de 5 pontos
    # 5.029,5 = minima (5.030) - 1 tick, abaixo do medio (5.040): vende
    ev = es.passo(e, _ts(9, 32), _hora(9, 32), 5029.5, 5040.0, p)
    pos = e.posicao
    # entrada 5.029,0; risco 5 pontos; contratos = 250 / (5 x 10) = 5; stop 5.034,0; alvo 5.019,0
    assert ev[0]["tipo"] == "entrada"
    assert (pos.lado, pos.contratos, pos.entrada, pos.stop, pos.alvo) == ("V", 5, 5029.0, 5034.0, 5019.0)
    # preco pula para 5.034,5: stop. Sai no pior entre o stop e o preco, 1 tick contra: 5.035,0
    ev = es.passo(e, _ts(9, 36), _hora(9, 36), 5034.5, 5040.0, p)
    # -6 pontos x 10 x 5 = -300,00; custos 2 x 1,20 x 5 = 12,00; liquido -312,00
    assert ev[0]["motivo"] == "stop" and ev[0]["saida"] == 5035.0
    assert ev[0]["pontos"] == -6.0 and ev[0]["resultado"] == pytest.approx(-312.0)


def test_nao_entra_contra_o_medio_nem_fora_do_horario():
    p = es.Parametros()
    e = es.EstadoAtivo("WINFUT")
    _faixa(e, 0, 31, 204200.0, 204500.0)
    # rompeu a maxima mas esta ABAIXO do medio do dia: nada
    assert es.passo(e, _ts(9, 31), _hora(9, 31), 204505.0, 204600.0, p) == []
    # antes das 9h30: nada, mesmo rompendo
    e2 = es.EstadoAtivo("WINFUT")
    _faixa(e2, 0, 20, 204200.0, 204500.0)
    assert es.passo(e2, _ts(9, 20), _hora(9, 20), 204505.0, 204300.0, p) == []
    # depois das 16h30: nada
    e3 = es.EstadoAtivo("WINFUT")
    _faixa(e3, 0, 31, 204200.0, 204500.0)
    assert es.passo(e3, _ts(16, 30), _hora(16, 30), 204505.0, 204300.0, p) == []
    # trava do dia disparada: nada
    assert es.passo(e3, _ts(10, 0), _hora(10, 0), 204505.0, 204300.0, p, pode_entrar=False) == []
    # dentro da faixa: nada
    assert es.passo(e3, _ts(10, 1), _hora(10, 1), 204400.0, 204300.0, p) == []


def test_o_minuto_corrente_nao_conta_como_maxima():
    p = es.Parametros()
    e = es.EstadoAtivo("WINFUT")
    _faixa(e, 0, 31, 204200.0, 204500.0)
    # no mesmo minuto o preco vai a 204.480 e depois a 204.505: a referencia continua 204.500 (minutos fechados)
    assert es.passo(e, _ts(9, 31, 5), _hora(9, 31, 5), 204480.0, 204300.0, p) == []
    ev = es.passo(e, _ts(9, 31, 40), _hora(9, 31, 40), 204505.0, 204300.0, p)
    assert ev and ev[0]["rompeu"] == 204500.0


def test_espera_depois_da_saida_e_limite_de_operacoes():
    p = es.Parametros()
    e = es.EstadoAtivo("WINFUT")
    _faixa(e, 0, 31, 204200.0, 204500.0)
    es.passo(e, _ts(9, 31), _hora(9, 31), 204505.0, 204300.0, p)
    es.passo(e, _ts(9, 33), _hora(9, 33), 204200.0, 204300.0, p)             # stop
    assert e.posicao is None and e.operacoes == 1
    # 2 minutos depois rompe de novo: ainda na espera de 5 minutos
    assert es.passo(e, _ts(9, 35), _hora(9, 35), 204600.0, 204300.0, p) == []
    # 6 minutos depois: entra (a maxima fechada agora e 204.600)
    ev = es.passo(e, _ts(9, 39, 30), _hora(9, 39, 30), 204605.0, 204300.0, p)
    assert ev and ev[0]["tipo"] == "entrada" and e.operacoes == 2
    # com o limite de operacoes do dia batido nao entra mais
    e.posicao = None
    e.operacoes = p.max_operacoes
    e.ultima_saida_ts = 0.0
    assert es.passo(e, _ts(11, 0), _hora(11, 0), 209000.0, 204300.0, p) == []


def test_zera_no_fim_do_dia_e_na_trava():
    p = es.Parametros()
    e = es.EstadoAtivo("WINFUT")
    _faixa(e, 0, 31, 204200.0, 204500.0)
    es.passo(e, _ts(9, 31), _hora(9, 31), 204505.0, 204300.0, p)             # comprado a 204.510, 4 contratos
    # 17h20 com o preco a 204.700: sai a mercado, 1 tick contra (204.695). 185 pontos x 0,20 x 4 = 148,00 - 2,40
    ev = es.passo(e, _ts(17, 20), _hora(17, 20), 204700.0, 204400.0, p)
    assert ev[0]["motivo"] == "fim_do_dia" and ev[0]["saida"] == 204695.0
    assert ev[0]["resultado"] == pytest.approx(145.60) and e.posicao is None
    # trava do dia: `zerar` fecha a mercado com o motivo dado
    e2 = es.EstadoAtivo("WDOFUT")
    _faixa(e2, 0, 31, 5030.0, 5035.0)
    es.passo(e2, _ts(9, 32), _hora(9, 32), 5029.5, 5040.0, p)                # vendido a 5.029,0, 5 contratos
    ev = es.zerar(e2, _ts(10, 0), _hora(10, 0), 5025.0, "meta")
    # recompra a 5.025,5: 3,5 pontos x 10 x 5 = 175,00 - 12,00 = 163,00
    assert ev["motivo"] == "meta" and ev["saida"] == 5025.5 and ev["resultado"] == pytest.approx(163.0)
    assert es.zerar(e2, _ts(10, 1), _hora(10, 1), 5025.0, "meta") is None


def test_risco_tem_piso_e_teto_e_define_os_contratos():
    p = es.Parametros()
    assert es.risco_em_pontos("WINFUT", 40.0) == 150.0 and es.risco_em_pontos("WINFUT", 900.0) == 400.0
    assert es.risco_em_pontos("WDOFUT", 1.0) == 3.0 and es.risco_em_pontos("WDOFUT", 20.0) == 8.0
    # mini-indice com 150 pontos de risco: 250 / (150 x 0,20) = 8,33 -> 8 contratos; com 400: 3,1 -> 3
    assert es.contratos_para("WINFUT", 150.0, p) == 8 and es.contratos_para("WINFUT", 400.0, p) == 3
    # mini-dolar com 3 pontos: 250 / 30 = 8,33 -> 8; com 8 pontos: 3,1 -> 3
    assert es.contratos_para("WDOFUT", 3.0, p) == 8 and es.contratos_para("WDOFUT", 8.0, p) == 3
    assert len(es.regras_em_texto(p)) >= 8

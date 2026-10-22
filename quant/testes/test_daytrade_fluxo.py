"""
Leitura de fluxo e regra versao 1.1 do robo de day trade: fitas escritas a mao, contas no comentario.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from quant.daytrade import estrategia_fluxo as ef
from quant.daytrade import fluxo as fx

T0 = 1_791_470_000          # um segundo qualquer do pregao (hora do servidor)
AJUSTE = [("ajuste de ontem", 5030.0)]


def _linha(seg, preco, compra, venda, simbolo="WDOX26", maior_c=None, maior_v=None, tamanho=None):
    base = (f"F;{simbolo};{seg};{preco};{compra};{venda};0;{max(1, int((compra + venda) // 5))};"
            f"{maior_c if maior_c is not None else compra};{maior_v if maior_v is not None else venda};300")
    if tamanho is not None:                       # (compra_media, venda_media, compra_grande, venda_grande)
        base += ";" + ";".join(str(x) for x in tamanho)
    return base


def _por(fita, seg, preco, compra, venda, **kw):
    fita.acrescentar(fx.linha_da_fita(_linha(seg, preco, compra, venda, **kw)))


def _fita_de_fundo(fita, ate, janelas=20, volume=200, preco=5035.0):
    """`janelas` janelas de 30 s, cada uma com `volume` agredido (metade de cada lado), longe do nivel."""
    for k in range(janelas, 0, -1):
        _por(fita, ate - 30 * k - 100, preco, volume / 2, volume / 2)


def test_linha_e_livro():
    x = fx.linha_da_fita("F;WDOX26;1791470000;5030.500;120;80;0;14;50;30;250")
    assert (x["preco"], x["compra"], x["venda"], x["negocios"], x["maior_compra"]) == (5030.5, 120.0, 80.0, 14, 50.0)
    assert "compra_media" not in x
    assert fx.linha_da_fita("lixo") is None and fx.linha_da_fita("F;WDOX26;1;0;1;1;0;1;1;1") is None
    # fita 1.3 com o tamanho do negocio: 120 comprados, dos quais 100 em negocios de 10+ e 50 em negocios de 50+
    y = fx.linha_da_fita("F;DOLX26;1791470000;5030.500;120;80;0;14;50;30;250;100;60;50;0")
    assert (y["compra_media"], y["venda_media"], y["compra_grande"], y["venda_grande"]) == (100.0, 60.0, 50.0, 0.0)
    livro = fx.ler_livro("#LIVRO;1;2026.10.08 12:00:00;1\nL;WDOX26;C;5030.0;45;5029.5;120;V;5030.5;30;5031.0;200\n#FIM\n")
    assert livro["WDOX26"]["compra"] == [(5030.0, 45.0), (5029.5, 120.0)]
    assert livro["WDOX26"]["venda"][0] == (5030.5, 30.0)
    # foto pela metade (sem #FIM) nao vale
    assert fx.ler_livro("#LIVRO;1;x;1\nL;WDOX26;C;5030.0;45;V;5030.5;30\n") == {}


def test_agressao_saldo_e_volume_tipico():
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)
    _por(f, T0 - 5, 5031.0, 80, 20, maior_c=40)
    _por(f, T0, 5031.5, 60, 40)
    a = f.agressao(15)
    # 80 + 60 = 140 de compra; 20 + 40 = 60 de venda; saldo +80; 70% de compra
    assert (a["compra"], a["venda"], a["saldo"]) == (140.0, 60.0, 80.0) and a["fracao_compra"] == pytest.approx(0.7)
    assert a["maior_compra"] == 60.0 and (a["minimo"], a["maximo"], a["ultimo"]) == (5031.0, 5031.5, 5031.5)
    assert f.volume_tipico(30) == 200.0            # a mediana das janelas de fundo
    assert fx.Fita("WDOX26", 0.5).volume_tipico(30) is None


def test_contrato_cheio_descarta_o_lote_de_robo():
    # 120 comprados no segundo, mas so 100 em negocios de 10 ou mais; 50 em lote de instituicao
    cheio = fx.Fita("DOLX26", 0.5, sem_lote_de_robo=True)
    tudo = fx.Fita("DOLX26", 0.5)
    for f in (cheio, tudo):
        _por(f, T0, 5030.5, 120, 80, simbolo="DOLX26", tamanho=(100, 60, 50, 0))
    assert (cheio.agressao(15)["compra"], cheio.agressao(15)["venda"]) == (100.0, 60.0)
    assert (tudo.agressao(15)["compra"], tudo.agressao(15)["venda"]) == (120.0, 80.0)
    assert cheio.agressao(15)["compra_grande"] == 50.0 and cheio.separa_tamanho and tudo.separa_tamanho
    assert fx.Fita("WDOX26", 0.5).separa_tamanho is False


def test_absorcao_testes_e_vai_e_vem():
    f = fx.Fita("WDOX26", 0.5)
    # 6 segundos de venda agredindo em 5.030,0 e 5.030,5 (400 no total) e o preco nunca abaixo de 5.030,0
    for k, (preco, venda) in enumerate([(5030.5, 60), (5030.0, 80), (5030.0, 70), (5030.5, 60), (5030.0, 70), (5030.0, 60)]):
        _por(f, T0 - 60 + 5 * k, preco, 10, venda)
    ab = f.absorcao(5030.0, "compra", 90)
    assert ab["agredido"] == 400.0 and ab["contra"] == 60.0 and ab["toques"] == 6 and ab["furou"] is False
    # um negocio a 5.029,5: sem tolerancia o suporte furou; com 1 tick de tolerancia, ainda nao
    _por(f, T0 - 10, 5029.5, 0, 30)
    assert f.absorcao(5030.0, "compra", 90)["furou"] is True
    assert f.absorcao(5030.0, "compra", 90, tolerancia_ticks=1)["furou"] is False
    # testes: foi ao nivel, afastou 1,5 ponto, voltou, afastou, voltou = 3 testes
    g = fx.Fita("WDOX26", 0.5)
    for k, preco in enumerate([5035.0, 5030.0, 5030.5, 5032.0, 5030.0, 5031.0, 5031.5, 5030.5]):
        _por(g, T0 - 80 + 10 * k, preco, 10, 10)
    # 5.031,0 (1 ponto) ainda nao e afastar; 5.031,5 (1,5 ponto) e
    assert g.testes(5030.0, "compra", 900, zona_ticks=1, afasta_ticks=3) == 3
    assert g.testes(5035.0, "venda", 900, zona_ticks=1, afasta_ticks=3) == 1
    # vai-e-vem tipico: 5 janelas de 60 s com 2,0 pontos de amplitude cada
    h = fx.Fita("WDOX26", 0.5)
    for k in range(5):
        _por(h, T0 - 60 * k - 30, 5030.0, 5, 5)
        _por(h, T0 - 60 * k - 10, 5032.0, 5, 5)
    assert h.amplitude_tipica(60) == 2.0 and fx.Fita("WDOX26", 0.5).amplitude_tipica(60) is None


def _cenario_defesa(testes=3, tamanho_no_nivel=None):
    """Suporte em 5.030,0 testado `testes` vezes, 350 de venda batendo nele sem passar, e os compradores assumem."""
    f = fx.Fita("WDOX26", 0.5, sem_lote_de_robo=True)
    _fita_de_fundo(f, T0)                          # tipico = 200 por janela de 30 s
    kw = {} if tamanho_no_nivel is None else {"tamanho": tamanho_no_nivel}
    passos = [(120, 5030.0, 10, 80), (110, 5030.5, 10, 60),           # teste 1
              (100, 5032.0, 30, 10),                                    # afasta 2 pontos
              (90, 5030.0, 10, 70),                                     # teste 2
              (80, 5032.0, 30, 10)]
    passos += [(60, 5030.5, 10, 60), (55, 5030.0, 10, 70)] if testes >= 3 else [(60, 5032.0, 10, 60), (55, 5032.5, 10, 70)]
    for atras, preco, compra, venda in passos:
        no_nivel = preco <= 5030.5
        _por(f, T0 - atras, preco, compra, venda, **(kw if no_nivel else ({} if tamanho_no_nivel is None else {"tamanho": (compra, venda, 0, 0)})))
    extra = {} if tamanho_no_nivel is None else {"tamanho": (50, 10, 0, 0)}
    _por(f, T0 - 8, 5030.5, 50, 10, **extra)
    _por(f, T0 - 2, 5031.0, 70, 20, **({} if tamanho_no_nivel is None else {"tamanho": (70, 20, 0, 0)}))   # 120 x 30 em 15 s
    return f


def test_defesa_de_suporte_vira_compra_e_e_conduzida_como_ele_faz():
    p = ef.ParamFluxo()
    f = _cenario_defesa()
    s = ef.ler_defesa("WDOFUT", f, 5031.0, AJUSTE, p)
    # 3 testes; 80 + 60 + 70 + 60 + 70 + 10 = 350 agredidos no nivel >= 1,5 x 200; nao furou; 120 / 150 = 80% de compra em 15 s
    assert s and s["tecnica"] == "defesa" and s["lado"] == "C"
    assert s["medidas"]["testes"] == 3 and s["medidas"]["agredido_no_nivel"] == 350.0
    assert s["medidas"]["fracao_a_favor"] == pytest.approx(0.8)
    e = ef.EstadoF("WDOFUT")
    ev = ef.passo(e, 1000.0, "10:15:00", 5031.0, f, AJUSTE, p, lote=2)
    pos = e.posicao
    # entrada a mercado 5.031,5; stop atras do nivel: 5.030,0 - 1,0 = 5.029,0 (2,5 pontos)
    assert ev[0]["tipo"] == "entrada" and (pos.entrada, pos.stop, pos.contratos) == (5031.5, 5029.0, 2)
    # +2,0 pontos: parcial de 1 contrato a 5.033,5 = 2,0 x 10 x 1 - 2,40 = 17,60; stop vai para a entrada
    ev = ef.passo(e, 1060.0, "10:16:00", 5033.5, f, AJUSTE, p, lote=2)
    assert ev[0]["tipo"] == "parcial" and ev[0]["contratos"] == 1 and ev[0]["resultado"] == pytest.approx(17.60)
    assert e.posicao.contratos == 1 and e.posicao.stop == 5031.5 and e.posicao.parcial_feita
    # preco a 5.036,0: stop movel 3 pontos atras = 5.033,0
    assert ef.passo(e, 1100.0, "10:17:00", 5036.0, f, AJUSTE, p, lote=2) == [] and e.posicao.stop == 5033.0
    # volta a 5.033,0: sai a mercado em 5.032,5 = +1,0 ponto x 10 x 1 - 2,40 = 7,60
    ev = ef.passo(e, 1150.0, "10:18:00", 5033.0, f, AJUSTE, p, lote=2)
    assert ev[0]["tipo"] == "saida" and ev[0]["motivo"] == "stop móvel" and ev[0]["saida"] == 5032.5
    assert ev[0]["resultado"] == pytest.approx(7.60) and e.posicao is None and e.ultima_foi_perda is False


def test_sem_defesa_nao_entra():
    p = ef.ParamFluxo()
    # no proprio nivel nao compra: ali e o teste (5.030,5 esta a meio ponto)
    assert ef.ler_defesa("WDOFUT", _cenario_defesa(), 5030.5, AJUSTE, p) is None
    # o preco ja fugiu 4 pontos: nao persegue
    assert ef.ler_defesa("WDOFUT", _cenario_defesa(), 5034.0, AJUSTE, p) is None
    # so 2 testes do nivel: ainda nao e defesa
    assert ef.ler_defesa("WDOFUT", _cenario_defesa(testes=2), 5031.0, AJUSTE, p) is None
    # pouca agressao contra o nivel (3 testes, mas 16 + 16 + 16 = 48 < 1,5 x 200)
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)
    for atras, preco in ((120, 5030.0), (100, 5032.0), (90, 5030.0), (80, 5032.0), (60, 5030.0)):
        _por(f, T0 - atras, preco, 5, 16)
    _por(f, T0 - 2, 5031.0, 70, 20)
    assert ef.ler_defesa("WDOFUT", f, 5031.0, AJUSTE, p) is None
    # defesa de verdade, mas quem agride agora e o vendedor: nao confirma
    g = _cenario_defesa()
    _por(g, T0, 5031.0, 20, 300)
    assert ef.ler_defesa("WDOFUT", g, 5031.0, AJUSTE, p) is None
    # o nivel foi perdido por mais de 1 tick dentro da janela: nao ha defesa
    h = _cenario_defesa()
    _por(h, T0 - 1, 5029.0, 0, 10)
    _por(h, T0, 5031.0, 80, 10)
    assert ef.ler_defesa("WDOFUT", h, 5031.0, AJUSTE, p) is None


def test_no_contrato_cheio_a_defesa_pede_lote_de_instituicao():
    p = ef.ParamFluxo()
    # mesma defesa, lida numa fita que separa tamanho: sem nenhum negocio de 50+ batendo no nivel, nao vale
    sem = _cenario_defesa(tamanho_no_nivel=(10, 60, 0, 0))
    assert sem.separa_tamanho and ef.ler_defesa("WDOFUT", sem, 5031.0, AJUSTE, p) is None
    # com lote de 50 batendo no nivel a cada teste, vale
    com = _cenario_defesa(tamanho_no_nivel=(10, 70, 0, 50))
    s = ef.ler_defesa("WDOFUT", com, 5031.0, AJUSTE, p)
    assert s and s["medidas"]["lotes_grandes_no_nivel"] >= 3
    # o dolar le o contrato cheio; o indice le o proprio mini, tambem sem o negocio pequeno
    assert ef.ATIVOS["WINFUT"].sem_lote_de_robo is True and ef.ATIVOS["WINFUT"].fonte_fluxo == "WIN"
    assert ef.ATIVOS["WDOFUT"].fonte_fluxo == "DOL"


def test_perda_de_nivel_nao_entra_na_primeira_quebra_e_entra_no_reteste():
    p = ef.ParamFluxo()
    e = ef.EstadoF("WDOFUT")
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)
    _por(f, T0 - 40, 5031.5, 30, 30)
    assert ef.passo(e, 1000.0, "11:00:00", 5031.5, f, AJUSTE, p, lote=2) == []       # acima do ajuste: so anota o lado
    assert e.lado_dos_niveis["ajuste de ontem"] == "acima"
    # perde o ajuste com venda agredindo (80%): e a PRIMEIRA quebra, nao entra
    _por(f, T0 - 1, 5029.0, 20, 80)
    assert ef.passo(e, 1030.0, "11:00:30", 5029.0, f, AJUSTE, p, lote=2) == []
    assert e.perdas["ajuste de ontem"]["lado"] == "V" and e.perdas["ajuste de ontem"]["retestou"] is False
    # 30 s depois o preco volta a encostar no ajuste: reteste anotado, ainda sem entrada
    _por(f, T0 + 29, 5030.0, 30, 20)
    assert ef.passo(e, 1060.0, "11:01:00", 5030.0, f, AJUSTE, p, lote=2) == []
    assert e.perdas["ajuste de ontem"]["retestou"] is True
    # nao retoma e sai de novo com venda: 130 x 30 em 15 s (81%) -> vende
    _por(f, T0 + 58, 5029.0, 10, 60)
    _por(f, T0 + 60, 5028.5, 20, 70)
    ev = ef.passo(e, 1090.0, "11:01:30", 5028.5, f, AJUSTE, p, lote=2)
    pos = e.posicao
    # vende a mercado em 5.028,0; stop 1 ponto alem do nivel perdido = 5.031,0 (3,0 pontos)
    assert ev[0]["tecnica"] == "perda de nível" and ev[0]["medidas"]["confirmacao"] == "reteste"
    assert (pos.lado, pos.entrada, pos.stop) == ("V", 5028.0, 5031.0) and "ajuste de ontem" not in e.perdas
    # stop cheio: preco a 5.031,0 -> recompra a 5.031,5 = -3,5 pontos x 10 x 2 - 4,80 = -74,80
    ev = ef.passo(e, 1150.0, "11:02:30", 5031.0, f, AJUSTE, p, lote=2)
    assert ev[0]["motivo"] == "stop" and ev[0]["resultado"] == pytest.approx(-74.80) and e.ultima_foi_perda is True
    # depois de uma perda, espera 5 minutos ("errou, respira mais"): 2 minutos depois ainda nao entra
    assert ef.passo(e, 1150.0 + 130, "11:04:40", 5031.0, _cenario_defesa(), AJUSTE, p, lote=2) == []
    assert ef.passo(e, 1150.0 + 301, "11:07:31", 5031.0, _cenario_defesa(), AJUSTE, p, lote=2)[0]["tipo"] == "entrada"


def test_perda_de_nivel_confirmada_pela_agressao():
    p = ef.ParamFluxo()
    e = ef.EstadoF("WDOFUT")
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)                                  # tipico de 15 s = 200
    ef.passo(e, 1000.0, "11:00:00", 5031.5, f, AJUSTE, p, lote=2)
    # quebra com agressao enorme, mas nos primeiros segundos: e a primeira quebra, nao entra
    _por(f, T0, 5029.0, 50, 300)
    assert ef.passo(e, 1030.0, "11:00:30", 5029.0, f, AJUSTE, p, lote=2) == []
    # 20 s depois, sem ter voltado ao nivel, a venda segue pesada: 350 em 15 s >= 1,5 x 200 e 86% de um lado
    _por(f, T0 + 20, 5028.5, 50, 300)
    ev = ef.passo(e, 1050.0, "11:00:50", 5028.5, f, AJUSTE, p, lote=2)
    assert ev and ev[0]["tecnica"] == "perda de nível" and ev[0]["medidas"]["confirmacao"] == "agressão"
    # agressao so um pouco acima do normal nao confirma: 220 < 300
    e2 = ef.EstadoF("WDOFUT")
    g = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(g, T0)
    ef.passo(e2, 1000.0, "11:00:00", 5031.5, g, AJUSTE, p, lote=2)
    _por(g, T0, 5029.0, 20, 80)
    ef.passo(e2, 1030.0, "11:00:30", 5029.0, g, AJUSTE, p, lote=2)
    _por(g, T0 + 20, 5028.5, 40, 180)
    assert ef.passo(e2, 1050.0, "11:00:50", 5028.5, g, AJUSTE, p, lote=2) == []
    # passados 20 minutos sem confirmacao, a perda caduca
    ef.passo(e2, 1030.0 + 1201, "11:20:31", 5028.5, g, AJUSTE, p, lote=2)
    assert "ajuste de ontem" not in e2.perdas


def _ate_o_rompimento(e, f, p, batidas):
    """Leva o preco `batidas` vezes a maxima de 5.040,0 (a primeira ja conta) e devolve os niveis."""
    niveis = [("máxima do dia", 5040.0), ("preço médio do dia", 5035.0)]
    ts = 1000.0
    for preco in [5038.0] + [5039.5, 5038.0] * (batidas - 1):
        assert ef.passo(e, ts, "11:00:00", preco, f, niveis, p, lote=2) == []
        ts += 10.0
    return niveis, ts


def test_rompimento_depois_de_duas_batidas_e_saida_se_nao_anda():
    p = ef.ParamFluxo()
    e = ef.EstadoF("WDOFUT")
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)
    niveis, ts = _ate_o_rompimento(e, f, p, batidas=3)
    assert e.extremos["max"] == {"nivel": 5040.0, "testes": 3, "fora": True}
    # rompe com compra: 180 x 40 em 15 s (82%), 220 >= 200 do normal; preco acima do medio do dia
    _por(f, T0, 5041.0, 180, 40)
    ev = ef.passo(e, ts, "11:01:00", 5041.0, f, [("máxima do dia", 5041.0), ("preço médio do dia", 5035.0)], p, lote=2)
    pos = e.posicao
    # compra a mercado em 5.041,5; stop de rompimento de 3 pontos = 5.038,5
    assert ev[0]["tecnica"] == "rompimento" and ev[0]["medidas"]["testes"] == 3
    assert (pos.entrada, pos.stop) == (5041.5, 5038.5) and e.extremos["max"]["testes"] == 1
    # 2 minutos depois o preco nao andou 1 ponto: sai a mercado em 5.041,0 = -0,5 x 10 x 2 - 4,80 = -14,80
    ev = ef.passo(e, ts + 121, "11:03:01", 5041.5, f, niveis, p, lote=2)
    assert ev[0]["motivo"] == "não andou" and ev[0]["resultado"] == pytest.approx(-14.80)
    # com 1 batida so (o extremo nunca foi testado de novo), o rompimento nao vira entrada, e o extremo novo recomeca a contagem
    e2, g = ef.EstadoF("WDOFUT"), fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(g, T0)
    niveis, ts = _ate_o_rompimento(e2, g, p, batidas=1)
    _por(g, T0, 5041.0, 180, 40)
    assert ef.passo(e2, ts, "11:01:00", 5041.0, g, niveis, p, lote=2) == []
    assert e2.extremos["max"] == {"nivel": 5041.0, "testes": 1, "fora": False}
    # 3 batidas, mas o preco esta ABAIXO do medio do dia: comprar o rompimento seria contra o lado do dia
    e3, h = ef.EstadoF("WDOFUT"), fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(h, T0)
    niveis, ts = _ate_o_rompimento(e3, h, p, batidas=3)
    _por(h, T0, 5041.0, 180, 40)
    assert ef.passo(e3, ts, "11:01:00", 5041.0, h, [("máxima do dia", 5041.0), ("preço médio do dia", 5045.0)], p, lote=2) == []


def test_filtros_de_entrada_e_stop_pelo_preco():
    p = ef.ParamFluxo()

    def tenta(hora="10:15:00", **contexto):
        return ef.passo(ef.EstadoF("WDOFUT"), 1000.0, hora, 5031.0, _cenario_defesa(), AJUSTE, p, lote=2, contexto=contexto)
    assert tenta()[0]["tipo"] == "entrada"
    assert tenta(spread=0.5)[0]["tipo"] == "entrada" and tenta(spread=1.0) == []      # spread aberto: falta volume
    assert tenta(var=0.016) == [] and tenta(var=-0.016)[0]["lado"] == "C"            # dolar +1,5%: nao compra
    assert tenta(hora="09:30:00") == [] and tenta(hora="09:14:59") == []             # dado das 9h30; antes das 9h15
    assert tenta(hora="09:15:00")[0]["tipo"] == "entrada"
    assert tenta(hora="12:50:00") == [] and tenta(hora="12:49:59")[0]["tipo"] == "entrada"   # janela do Douglas: ate as 13h
    assert ef.passo(ef.EstadoF("WDOFUT"), 1000.0, "10:15:00", 5031.0, _cenario_defesa(), AJUSTE, p, lote=2, pode_entrar=False) == []
    # stop: atras do nivel, minimo de 2, teto de 5 (6 em dia rapido, com a folga dobrada)
    assert ef.calcular_stop("WDOFUT", "C", 5031.5, 5030.0, "defesa", False) == 5029.0      # 1 ponto atras do nivel
    assert ef.calcular_stop("WDOFUT", "V", 5029.5, 5030.0, "perda de nível", False) == 5031.5   # 1,5 viraria 2 (minimo)
    assert ef.calcular_stop("WDOFUT", "C", 5036.0, 5030.0, "defesa", False) == 5031.0      # 7 pontos viram 5 (teto)
    assert ef.calcular_stop("WDOFUT", "C", 5031.5, 5030.0, "defesa", True) == 5028.0       # dia rapido: 2 pontos atras
    assert ef.calcular_stop("WDOFUT", "C", 5036.0, 5030.0, "defesa", True) == 5030.0       # teto de 6
    assert ef.calcular_stop("WINFUT", "C", 207300.0, 207200.0, "defesa", False) == 207140.0   # 60 atras do nivel = 160
    assert ef.calcular_stop("WINFUT", "C", 207500.0, 207200.0, "defesa", False) == 207250.0   # 360 viram 250 (teto do indice)
    # niveis: a variacao de 1% entra como nivel (5.030 x 1,01 = 5.080,3; x 0,99 = 4.979,7)
    de = dict(ef.niveis_do_dia({"ajuste": 5030.0, "maxima": 5040.0}, p))
    assert de["1% acima do ajuste"] == pytest.approx(5080.3) and de["1% abaixo do ajuste"] == pytest.approx(4979.7)
    assert de["máxima do dia"] == 5040.0 and "mínima do dia" not in de


def test_escada_de_lote_e_fim_do_dia():
    p = ef.ParamFluxo()
    # R$ 1.000 de lucro acumulado paga um degrau de 2 contratos; devolveu o lucro, volta; teto de 8
    assert [ef.lote_do_dia(x, p) for x in (-500.0, 0.0, 999.0, 1000.0, 2500.0, 50_000.0)] == [2, 2, 2, 4, 6, 8]
    e = ef.EstadoF("WINFUT")
    e.posicao = ef.PosicaoF("C", 2, 206000.0, 205880.0, "12:40:00", "defesa", 205950.0, "abertura", 2, False, 206000.0)
    assert ef.passo(e, 4990.0, "12:59:59", 206100.0, None, [], p, lote=2) == []
    ev = ef.passo(e, 5000.0, "13:00:00", 206100.0, None, [], p, lote=2)
    # sai a mercado, 1 tick contra: 206.095 = +95 pontos x 0,20 x 2 - 1,20 = 36,80
    assert ev[0]["motivo"] == "fim_do_dia" and ev[0]["resultado"] == pytest.approx(36.80) and e.posicao is None
    regras = ef.regras_em_texto(p)
    assert len(regras) >= 10 and any("20%" in r for r in regras) and any("contrato cheio" in r for r in regras)
    # sem meta (como ele dizia em 2015) o texto nao fala em meta
    assert not any("sua meta" in r for r in ef.regras_em_texto(ef.ParamFluxo(meta_dia_rs=None)))


def test_leitor_le_a_fita_aos_poucos(tmp_path):
    leitor = fx.Leitor(pasta=str(tmp_path), dia="20261008")
    arq = leitor.arquivo_da_fita()
    assert leitor.novas_linhas() == []
    with open(arq, "w") as f:
        f.write(_linha(T0, 5030.0, 10, 20) + "\n" + _linha(T0 + 1, 5030.5, 5, 5)[:20])   # segunda linha pela metade
    assert [x["preco"] for x in leitor.novas_linhas()] == [5030.0]
    with open(arq, "a") as f:
        f.write(_linha(T0 + 1, 5030.5, 5, 5)[20:] + "\n")
    assert [x["preco"] for x in leitor.novas_linhas()] == [5030.5] and leitor.novas_linhas() == []
    leitor.pedir(["WINV26", "WDOX26"])
    assert open(os.path.join(str(tmp_path), fx.ARQ_TAPE)).read() == "WDOX26\nWINV26\n"


# ── o robo inteiro, com motor de mentira e a fita num arquivo ────────────────────────────────────
BRT = timezone(timedelta(hours=-3))


def _cotacao(preco, ts, compra=None, venda=None, anterior=5030.0, maxima=5035.0, minima=5029.5):
    # [ultimo, var%, abertura, max, min, volume, fech.anterior, ts, bid, ask, sess, negocios, financeiro, medio]
    return [preco, 0.0, 5032.0, maxima, minima, 1000, anterior, ts, compra or preco - 0.5, venda or preco, "aberto", 10, 0, 5032.0]


def _robo(tmp_path, monkeypatch, dia):
    from quant.daytrade import chave
    from quant.daytrade import robo_fluxo as rf
    monkeypatch.setattr(chave, "ARQ_CHAVE", str(tmp_path / "chave.json"))   # a chave de verdade e do Douglas
    monkeypatch.setattr(chave, "ARQ_JANELA", str(tmp_path / "janela.json"))  # e a janela tambem
    monkeypatch.setattr(rf, "DIR_DT", str(tmp_path / "dt"))
    monkeypatch.setattr(rf, "ARQ_SERIE", str(tmp_path / "dt" / "serie_fluxo.json"))
    monkeypatch.setattr(rf, "ARQ_MODO", str(tmp_path / "modo_robo.json"))    # quem opera (climax, niveis) e do Douglas
    monkeypatch.setattr(chave, "ARQ_RISCO", str(tmp_path / "risco_robo.json"))  # e os limites de risco tambem
    monkeypatch.setattr(rf, "ler_motor", lambda *a, **k: None)
    monkeypatch.setattr(rf, "ARQ_FUTUROS_B3", str(tmp_path / "sem_futuros.json"))
    mt5 = tmp_path / "mt5"
    mt5.mkdir()
    r = rf.RoboFluxo(dia, saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5))
    r.codigos = {"WINFUT": "WINV26", "WDOFUT": "WDOX26"}
    r.ajustes = {"WDOFUT": 5030.0}
    return rf, r, mt5


def test_robo_le_o_fluxo_no_dolar_cheio_e_simula_no_mini(tmp_path, monkeypatch):
    rf, r, mt5 = _robo(tmp_path, monkeypatch, "2026-10-08")
    assert rf.codigo_da_fonte("WDOFUT", "WDOX26") == "DOLX26" and rf.codigo_da_fonte("WINFUT", "WINV26") == "WINV26"
    # a mesma defesa do teste da regra, gravada como fita do DOLAR CHEIO
    fita = _cenario_defesa()
    with open(mt5 / "autopilot_fita_20261008.csv", "w") as f:
        for x in fita.linhas:
            f.write(_linha(x["seg"], x["preco"], x["compra"], x["venda"], simbolo="DOLX26") + "\n")
    agora = datetime(2026, 10, 8, 10, 15, 7, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5031.0, agora.timestamp())}})
    dol = next(i for i in est["instrumentos"] if i["ativo"] == "WDOFUT")
    assert dol["fluxo"]["fonte"] == "DOL" and dol["fluxo"]["contrato_fonte"] == "DOLX26"
    assert dol["posicao"] and dol["posicao"]["tecnica"] == "defesa" and dol["posicao"]["entrada"] == 5031.5
    assert est["regra"] == "fluxo" and est["resultado"]["meta"] == 1000.0 and est["resultado"]["perda_maxima"] == -1000.0
    assert json.load(open(tmp_path / "quant.json"))["tipo"] == "daytrade"
    # o estado salvo volta inteiro (perdas, extremos, posicao com a hora da entrada)
    r2 = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5))
    assert r2.estados["WDOFUT"].posicao.ts_entrada == agora.timestamp()


def test_robo_sem_fita_do_cheio_cai_para_o_mini_e_sem_fita_nao_entra(tmp_path, monkeypatch):
    rf, r, mt5 = _robo(tmp_path, monkeypatch, "2026-10-08")
    agora = datetime(2026, 10, 8, 10, 15, 7, tzinfo=BRT)
    q = {"q": {"WDOFUT": _cotacao(5031.0, agora.timestamp())}}
    est = r.ciclo(agora, retrato=q)                       # nenhuma fita: nao entra e avisa
    assert r.estados["WDOFUT"].posicao is None and est["avisos"][0].startswith("ATENÇÃO: sem a fita")
    fita = _cenario_defesa()
    with open(mt5 / "autopilot_fita_20261008.csv", "w") as f:
        for x in fita.linhas:
            f.write(_linha(x["seg"], x["preco"], x["compra"], x["venda"], simbolo="WDOX26") + "\n")
    est = r.ciclo(agora + timedelta(seconds=1), retrato=q)
    dol = next(i for i in est["instrumentos"] if i["ativo"] == "WDOFUT")
    assert dol["fluxo"]["fonte"] == "mini" and dol["posicao"] is not None
    assert any("Fluxo lido no mini" in a for a in est["avisos"])


def test_robo_para_quando_devolve_20_por_cento_do_lucro_do_dia(tmp_path, monkeypatch):
    rf, r, mt5 = _robo(tmp_path, monkeypatch, "2026-10-08")
    agora = datetime(2026, 10, 8, 11, 0, 7, tzinfo=BRT)
    q = {"q": {"WDOFUT": _cotacao(5031.0, agora.timestamp())}}

    def op(resultado):
        return {"tipo": "saida", "ativo": "WDOFUT", "lado": "C", "contratos": 2, "entrada": 5030.0, "hora_entrada": "10:00:00",
                "saida": 5040.0, "hora_saida": "10:10:00", "motivo": "stop móvel", "pontos": 1.0, "custos": 4.8, "resultado": resultado}
    r.operacoes = [op(200.0)]                              # o dia chegou a +R$ 200 realizados
    r.ciclo(agora, retrato=q)
    assert r.trava is None and r.pico_realizado == 200.0
    r.operacoes.append(op(-30.0))                          # devolveu R$ 30 (15%): segue
    r.ciclo(agora + timedelta(seconds=1), retrato=q)
    assert r.trava is None
    r.operacoes.append(op(-15.0))                          # devolveu R$ 45 (22,5%): para
    est = r.ciclo(agora + timedelta(seconds=2), retrato=q)
    assert r.trava == "devolucao" and est["resultado"]["motivo_trava"] == "devolucao" and "devolveu 20%" in est["vivo"]["fase_texto"]
    # lucro pequeno (abaixo de R$ 100) nao arma a regra
    rf2, r2, _ = _robo(tmp_path / "b", monkeypatch, "2026-10-08") if (tmp_path / "b").mkdir() is None else (None, None, None)
    r2.operacoes = [op(60.0), op(-40.0)]
    r2.ciclo(agora, retrato=q)
    assert r2.trava is None


def test_chave_do_douglas_desliga_zera_e_religa(tmp_path, monkeypatch):
    from quant.daytrade import chave
    arq = str(tmp_path / "chave.json")
    assert chave.ler(arq)["ligado"] is True                # sem arquivo, vale ligado
    monkeypatch.setattr(chave, "ARQ_CHAVE", arq)
    rf, r, mt5 = _robo(tmp_path, monkeypatch, "2026-10-08")
    fita = _cenario_defesa()
    with open(mt5 / "autopilot_fita_20261008.csv", "w") as f:
        for x in fita.linhas:
            f.write(_linha(x["seg"], x["preco"], x["compra"], x["venda"], simbolo="DOLX26") + "\n")
    agora = datetime(2026, 10, 8, 10, 15, 7, tzinfo=BRT)
    q = {"q": {"WDOFUT": _cotacao(5031.0, agora.timestamp())}}
    r.ciclo(agora, retrato=q)
    assert r.estados["WDOFUT"].posicao is not None         # comprado a 5.031,5
    chave.gravar(False, "pedido do Douglas")
    est = r.ciclo(agora + timedelta(seconds=1), retrato=q)
    # zera a mercado em 5.030,5: -1,0 ponto x 10 x 2 - 4,80 = -24,80; fase "desligado"; nao entra de novo
    assert r.estados["WDOFUT"].posicao is None and r.operacoes[-1]["motivo"] == "desligado"
    assert r.operacoes[-1]["resultado"] == pytest.approx(-24.80)
    assert est["vivo"]["fase"] == "desligado" and "DESLIGADO" in est["vivo"]["fase_texto"]
    est = r.ciclo(agora + timedelta(seconds=400), retrato={"q": {"WDOFUT": _cotacao(5031.0, agora.timestamp() + 400)}})
    assert r.estados["WDOFUT"].posicao is None
    chave.gravar(True)
    assert chave.ler()["ligado"] is True and chave.hora_de({"desde": "2026-10-08T13:20:05-03:00"}) == "13:20 de 08/10"


def test_janela_do_douglas_com_excecao_por_data(tmp_path):
    from quant.daytrade import chave
    arq = str(tmp_path / "janela.json")
    assert chave.janela("2026-10-09", arq) == {"inicio": "09:15", "ultima_entrada": "12:50", "zerar": "13:00", "motivo": ""}
    with open(arq, "w") as f:
        json.dump({"inicio": "09:15", "ultima_entrada": "12:50", "zerar": "13:00",
                   "excecoes": {"2026-10-08": {"ultima_entrada": "16:30", "zerar": "17:20", "motivo": "ate o fim do pregao"}}}, f)
    hoje = chave.janela("2026-10-08", arq)
    assert (hoje["ultima_entrada"], hoje["zerar"], hoje["motivo"]) == ("16:30", "17:20", "ate o fim do pregao")
    assert chave.janela("2026-10-09", arq)["zerar"] == "13:00"
    with open(arq, "w") as f:
        f.write('{"zerar": "25h", "inicio": 9}')              # lixo: fica o padrao
    assert chave.janela("2026-10-09", arq)["zerar"] == "13:00" and chave.janela("2026-10-09", arq)["inicio"] == "09:15"


def test_ajuste_oficial_da_b3_e_spread_pelo_livro(tmp_path):
    from quant.daytrade import robo_fluxo as rf
    arq = str(tmp_path / "futuros.json")
    with open(arq, "w") as f:
        json.dump({"data": "2026-10-07", "familias": [{"contratos": [
            {"s": "WDOX26", "ajuste": 5027.758, "ajuste_ant": 4999.488, "ult": 5044.0},
            {"s": "WINV26", "ajuste": 204918.0, "ajuste_ant": 206332.0}]}]}, f)
    cods = {"WDOFUT": "WDOX26", "WINFUT": "WINV26"}
    # de manha o arquivo e de ontem: vale o "ajuste" (5.027,758, e nao o ultimo negocio da noite, 5.044,0)
    assert rf.ajustes_oficiais(cods, "2026-10-08", arq) == {"WDOFUT": (5027.758, "2026-10-07"), "WINFUT": (204918.0, "2026-10-07")}
    # se o arquivo ja for o de hoje (de noite), o ajuste de ontem e o "ajuste_ant"
    assert rf.ajustes_oficiais(cods, "2026-10-07", arq)["WDOFUT"][0] == 4999.488
    # segunda-feira com arquivo de sexta vale; arquivo velho demais nao; arquivo do futuro nao
    assert rf.ajustes_oficiais(cods, "2026-10-12", arq)["WDOFUT"][0] == 5027.758
    assert rf.ajustes_oficiais(cods, "2026-10-13", arq) == {} and rf.ajustes_oficiais(cods, "2026-10-06", arq) == {}
    assert rf.ajustes_oficiais(cods, "2026-10-08", str(tmp_path / "nao_existe.json")) == {}
    # o nivel entra arredondado ao tick: 5.027,758 -> 5.028,0; e o 1% sai dele
    de = dict(ef.niveis_do_dia({"ajuste": 5027.758, "anterior": 5044.0}))
    assert de["ajuste de ontem"] == 5027.758 and de["1% acima do ajuste"] == pytest.approx(5078.03558)
    livro = {"WDOX26": {"compra": [(5028.5, 10.0), (5028.0, 40.0)], "venda": [(5029.0, 5.0)]}}
    assert rf.spread_do_livro(livro, "WDOX26") == 0.5 and rf.spread_do_livro(livro, "WINV26") is None
    assert rf.spread_do_livro({"WDOX26": {"compra": [(5029.5, 1.0)], "venda": [(5029.0, 1.0)]}}, "WDOX26") is None   # livro cruzado: foto ruim


def _corrida_de_alta(f, topo=5080.0, tamanho=24.0, agressao_no_topo=20):
    """10 minutos: o dolar sobe `tamanho` pontos com 200 de compra por preco no miolo, chega ao topo com pouca
    compra, fica 40 s sem renovar e recua 1,5 ponto com venda agredindo."""
    _fita_de_fundo(f, T0 - 600, preco=topo - tamanho)
    passos = int(tamanho / 2)
    for k in range(passos):                                 # sobe 2 pontos a cada 40 s, 200 de compra em cada preco
        _por(f, T0 - 560 + 40 * k, topo - tamanho + 2.0 * k, 200, 40)
    _por(f, T0 - 60, topo, agressao_no_topo, 10)            # no topo a compra secou
    _por(f, T0 - 8, topo - 1.0, 10, 60)
    _por(f, T0 - 2, topo - 1.5, 20, 90)                     # 150 x 30 de venda em 15 s (83%)
    return f


def test_exaustao_vende_a_corrida_esticada_so_com_o_dia_em_1_por_cento():
    p = ef.ParamFluxo()
    f = _corrida_de_alta(fx.Fita("WDOX26", 0.5))
    c = f.corrida(600)["alta"]
    assert (c["extremo"], c["origem"], c["tamanho"], c["seg_extremo"]) == (5080.0, 5056.0, 24.0, T0 - 60)
    e = ef.EstadoF("WDOFUT")
    # dia em +0,6%: nao opera contra (a regra dele e 1%; abaixo disso, nas lives, perdeu 4 de 5)
    assert ef.ler_exaustao("WDOFUT", e, f, 5078.5, p, var=0.006) is None
    s = ef.ler_exaustao("WDOFUT", e, f, 5078.5, p, var=0.011)
    # corrida de 24 pontos; no topo 20 de compra contra 200 no miolo (10% < 50%); recuo de 1,5; 83% de venda
    assert s and s["tecnica"] == "exaustão" and s["lado"] == "V" and s["nivel"] == 5080.0
    assert s["medidas"]["corrida_pts"] == 24.0 and s["medidas"]["agressao_no_extremo"] == 20.0 and s["medidas"]["agressao_no_miolo"] == 200.0
    ev = ef.passo(e, 1000.0, "10:15:00", 5078.5, f, [], p, lote=2, contexto={"var": 0.011})
    # vende a mercado em 5.078,0; stop 1 ponto alem do topo = 5.081,0 (3,0 pontos)
    assert ev[0]["tecnica"] == "exaustão" and (e.posicao.entrada, e.posicao.stop) == (5078.0, 5081.0)
    assert e.contras["alta"] == {"extremo": 5080.0, "n": 1}
    # nao vale: corrida curta (14 pontos); compra ainda forte no topo; preco ainda colado no topo; topo feito agora
    assert ef.ler_exaustao("WDOFUT", ef.EstadoF("WDOFUT"), _corrida_de_alta(fx.Fita("WDOX26", 0.5), tamanho=14.0), 5078.5, p, var=0.011) is None
    assert ef.ler_exaustao("WDOFUT", ef.EstadoF("WDOFUT"), _corrida_de_alta(fx.Fita("WDOX26", 0.5), agressao_no_topo=150), 5078.5, p, var=0.011) is None
    assert ef.ler_exaustao("WDOFUT", ef.EstadoF("WDOFUT"), f, 5079.5, p, var=0.011) is None
    g = _corrida_de_alta(fx.Fita("WDOX26", 0.5))
    _por(g, T0 - 1, 5080.0, 5, 5)
    assert ef.ler_exaustao("WDOFUT", ef.EstadoF("WDOFUT"), g, 5078.5, p, var=0.011) is None
    # no maximo 3 vezes contra o mesmo extremo
    e3 = ef.EstadoF("WDOFUT")
    e3.contras["alta"] = {"extremo": 5080.0, "n": 3}
    assert ef.ler_exaustao("WDOFUT", e3, f, 5078.5, p, var=0.011) is None


def test_nivel_testado_demais_nao_e_defesa():
    p = ef.ParamFluxo()
    f = _cenario_defesa()                                   # 3 testes: vale
    assert ef.ler_defesa("WDOFUT", f, 5031.0, AJUSTE, p)["medidas"]["testes"] == 3
    g = fx.Fita("WDOX26", 0.5, sem_lote_de_robo=True)
    _fita_de_fundo(g, T0)
    for k in range(5):                                      # 5 idas ao nivel: ele so opera a perda, nao compra o suporte
        _por(g, T0 - 200 + 30 * k, 5030.0, 10, 80)
        _por(g, T0 - 190 + 30 * k, 5032.0, 30, 10)
    _por(g, T0 - 8, 5030.5, 50, 10)
    _por(g, T0 - 2, 5031.0, 70, 20)
    assert g.testes(5030.0, "compra", 900, zona_ticks=1, afasta_ticks=3) == 6
    assert ef.ler_defesa("WDOFUT", g, 5031.0, AJUSTE, p) is None


def test_confirmacao_usa_o_relogio_do_pregao_e_pede_amostra():
    p = ef.ParamFluxo()
    # contrato que negocia pouco: o ultimo negocio foi ha 40 s. Sem o relogio do pregao, "os ultimos 15 s" seriam os dele
    cheio = fx.Fita("WDOX26", 0.5)                               # o simbolo nao importa aqui: so a esparsidade
    _fita_de_fundo(cheio, T0)
    _por(cheio, T0 - 40, 5031.0, 80, 0)
    assert cheio.agressao(15)["compra"] == 80.0                    # ancorado no ultimo negocio do proprio simbolo
    cheio.agora = T0                                               # o robo acerta o relogio pelo contrato que negociou por ultimo
    assert cheio.relogio() == T0 and cheio.agressao(15)["total"] == 0.0
    assert ef.confirmacao(cheio, p)["vale"] is False
    # um negocio sozinho, mesmo grande, nao confirma: pede 3 negocios e metade do volume normal de 15 s
    um = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(um, T0)
    um.acrescentar(fx.linha_da_fita(f"F;WDOX26;{T0};5031.0;500;0;0;1;500;0;300"))
    assert ef.confirmacao(um, p)["vale"] is False and ef.confirmacao(um, p)["negocios"] == 1
    pouco = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(pouco, T0)
    _por(pouco, T0, 5031.0, 60, 10)                                # 70 < metade de 200
    assert ef.confirmacao(pouco, p)["vale"] is False
    # o mini vivo confirma no lugar do cheio parado; mini parado ha mais de 30 s nao serve
    mini = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(mini, T0)
    _por(mini, T0 - 3, 5031.0, 150, 20)
    mini.agora = T0
    assert ef.fita_viva(mini, cheio) is mini and ef.confirmacao(mini, p)["vale"] is True
    mini.agora = T0 + 60
    assert ef.fita_viva(mini, cheio) is cheio and ef.fita_viva(None, cheio) is cheio
    # na defesa: a leitura do nivel vem do cheio, a confirmacao do mini. Mini com vendedor agredindo derruba a entrada
    def_cheio = _cenario_defesa()
    vendedor = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(vendedor, T0)
    _por(vendedor, T0 - 2, 5031.0, 20, 300)
    assert ef.ler_defesa("WDOFUT", def_cheio, 5031.0, AJUSTE, p) is not None
    assert ef.ler_defesa("WDOFUT", def_cheio, 5031.0, AJUSTE, p, vendedor) is None


def test_robo_so_de_dolar_ignora_a_fita_do_indice(tmp_path, monkeypatch):
    rf, r, mt5 = _robo(tmp_path, monkeypatch, "2026-10-08")
    monkeypatch.setattr(rf, "ATIVOS", ("WDOFUT",))
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5))
    r.codigos = {"WINFUT": "WINV26", "WDOFUT": "WDOX26"}       # o estado salvo ainda lembra do indice
    with open(mt5 / "autopilot_fita_20261008.csv", "w") as f:
        f.write(_linha(T0, 207000.0, 10, 20, simbolo="WINV26") + "\n" + _linha(T0, 5031.0, 10, 20, simbolo="WDOX26") + "\n")
    agora = datetime(2026, 10, 8, 10, 15, 7, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5031.0, agora.timestamp()), "WINFUT": _cotacao(207000.0, agora.timestamp())}})
    assert [i["ativo"] for i in est["instrumentos"]] == ["WDOFUT"] and list(r.estados) == ["WDOFUT"]
    assert not any("ndice" in a for a in est["avisos"])


# ── setup PhiCube: barras, sinal e robo ──────────────────────────────────────────────────────────
def _serie_em_alta(minutos=12_000, inclinacao=0.01, onda=1.0, periodo=23):
    """Barras de 1 minuto subindo devagar, com um vai-e-vem: tendencia de alta no grafico de 15 minutos."""
    import numpy as np
    import pandas as pd
    idx = pd.bdate_range("2026-06-01", periods=minutos // 540 + 2, freq="B")
    horas = [d + pd.Timedelta(hours=9, minutes=m) for d in idx for m in range(540)][:minutos]
    t = np.arange(minutos)
    c = 5000.0 + inclinacao * t + onda * np.sin(2 * np.pi * t / periodo)
    c = np.round(c * 2) / 2
    return pd.DataFrame({"o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "n": 10.0, "v": 100.0}, index=pd.DatetimeIndex(horas, name="hora"))


def test_phicube_tendencia_em_15_gatilho_em_4_e_o_mesmo_do_teste_historico():
    from quant.daytrade import barras as br, estrategias_hist as eh, historico as hist
    df = _serie_em_alta()
    est = eh.PhiCube(15, 4, "sma")
    est.preparar(df)
    # com o preco subindo ha 22 pregoes, o grafico de 15 minutos esta em tendencia de alta no fim da serie
    # (a media de 34 em 15 minutos fica 2,5 pontos atras do preco; o vai-e-vem de 1 ponto nao chega nela)
    assert (est.tend[est.ig[-600:]] == 1).mean() > 0.95
    ordens = [(i, est.decidir(i, None, {})) for i in range(len(df) - 600, len(df))]
    ordens = [(i, o) for i, o in ordens if o is not None]
    assert ordens and all(o.lado == "C" for _i, o in ordens)            # so compra em tendencia de alta
    i, o = ordens[0]
    assert 2.0 <= o.stop_pts <= 8.0 and o.alvo_pts == pytest.approx(3 * o.stop_pts) and o.parcial_pts == pytest.approx(o.stop_pts)
    assert est.nova_s[i]                                                # a ordem nasce no minuto em que fecha uma barra de 4
    # a leitura ao vivo, no mesmo ponto, da a mesma ordem; e so uma vez por barra
    sinal = br.SinalPhiCube(maior=15, menor=4, tipo="sma")
    leitura, ordem = sinal.atualizar(df.iloc[:i + 1])
    assert leitura["pronto"] and leitura["tendencia"] == "alta" and leitura["alinhadas"] and ordem is not None
    assert (ordem.lado, ordem.stop_pts) == (o.lado, o.stop_pts)
    assert sinal.atualizar(df.iloc[:i + 1])[1] is None
    # sem historia suficiente nao ha leitura nem ordem
    curto, nada = br.SinalPhiCube(maior=15, menor=4).atualizar(df.iloc[:500])
    assert curto["pronto"] is False and nada is None
    # o simulador: uma ordem de compra com stop de 4, parcial em +4 e alvo em +12
    class Uma(hist.Estrategia):
        def decidir(self, i, dia, ctx):
            return hist.Ordem("C", 4.0, parcial_pts=4.0, alvo_pts=12.0) if not ctx.get("ja") and not ctx.update(ja=True) else None
    import pandas as pd
    horas = pd.date_range("2026-10-08 09:15", periods=8, freq="min")
    b = pd.DataFrame({"o": [5000, 5000, 5001, 5005, 5008, 5012, 5013, 5013], "h": [5000, 5001, 5005, 5008, 5012, 5013.5, 5013, 5013],
                      "l": [5000, 4999, 5000, 5004, 5007, 5011, 5012, 5012], "c": [5000, 5001, 5005, 5008, 5012, 5013, 5013, 5013],
                      "n": 1.0, "v": 1.0}, index=horas).astype(float)
    neg = hist.simular(b, Uma(), hist.RegrasDoDia(), hist.Custos())
    # entra a 5.000,5 (abertura + 1 tick); parcial de 1 em 5.004,5 (+4); alvo de 1 em 5.012,5 (+12): 16 pontos x R$ 10 - R$ 4,80
    assert len(neg) == 1 and neg[0].saida == "alvo" and neg[0].resultado == pytest.approx(155.20)


def test_robo_no_setup_phicube_entra_pelo_sinal_do_grafico_e_comeca_zerado(tmp_path, monkeypatch):
    from quant.daytrade import historico as hist
    rf, r0, mt5 = _robo(tmp_path, monkeypatch, "2026-10-08")
    monkeypatch.setattr(rf, "ATIVOS", ("WDOFUT",))
    r0.operacoes = [{"tipo": "saida", "ativo": "WDOFUT", "resultado": -74.8, "custos": 4.8}]
    r0.perdas, r0.trava = 3, "tres_perdas"
    r0._salvar()                                               # o placar da regra de fluxo: 3 perdedores, travado
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="phicube")
    r.codigos, r.ajustes = {"WDOFUT": "WDOX26"}, {"WDOFUT": 5030.0}
    assert r.trava is None and r.perdas == 0 and r.operacoes == []        # setup novo, placar zerado
    leitura = {"pronto": True, "maior_min": 15, "menor_min": 4, "tipo_media": "sma", "periodos": [34, 144, 610], "tendencia": "alta",
               "fechamento_maior": 5031.0, "medias_maior": [5029.0, 5025.0, 5015.0], "alinhadas": True, "fechamento_menor": 5031.0,
               "medias_menor": [5030.5, 5028.0], "lado_menor": "acima", "virou": 1, "barra_menor": "x", "barras": 12000}

    class Falso:
        def __init__(self): self.vez = 0
        def atualizar(self, df):
            self.vez += 1
            return leitura, (hist.Ordem("C", 4.0, parcial_pts=4.0, alvo_pts=12.0) if self.vez == 1 else None)
    r.sinais_pc["WDOFUT"] = Falso()
    agora = datetime(2026, 10, 8, 10, 16, 7, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5031.0, agora.timestamp())}})    # sem fita nenhuma: o grafico basta
    pos = r.estados["WDOFUT"].posicao
    # compra a mercado em 5.031,5; stop 4 pontos = 5.027,5; alvo 3 por 1 = 5.043,5; parcial em +4
    assert pos and (pos.tecnica, pos.entrada, pos.stop, pos.alvo, pos.parcial_pts, pos.sem_arrasto) == ("phicube", 5031.5, 5027.5, 5043.5, 4.0, True)
    assert est["regra"] == "phicube" and "PhiCube" in est["regras"]["nome"] and any("PERDEU" in a for a in est["avisos"])
    assert est["instrumentos"][0]["phicube"]["tendencia"] == "alta" and est["posicoes"][0]["tecnica"] == "phicube"
    # +4: parcial de 1 (4 x 10 - 2,40 = 37,60) e stop na entrada; depois o alvo em 5.043,5: +12 x 10 - 2,40 = 117,60
    r.ciclo(agora + timedelta(seconds=30), retrato={"q": {"WDOFUT": _cotacao(5035.5, agora.timestamp() + 30)}})
    assert r.operacoes[-1]["tipo"] == "parcial" and r.operacoes[-1]["resultado"] == pytest.approx(37.60) and pos.stop == 5031.5
    r.ciclo(agora + timedelta(seconds=90), retrato={"q": {"WDOFUT": _cotacao(5038.0, agora.timestamp() + 90)}})
    assert r.estados["WDOFUT"].posicao.stop == 5031.5            # sem stop movel: o resto espera o alvo
    est = r.ciclo(agora + timedelta(seconds=150), retrato={"q": {"WDOFUT": _cotacao(5044.0, agora.timestamp() + 150)}})
    assert r.operacoes[-1]["motivo"] == "alvo" and r.operacoes[-1]["saida"] == 5043.5 and r.operacoes[-1]["resultado"] == pytest.approx(117.60)
    assert est["resultado"]["dia"] == pytest.approx(155.20)
    assert os.path.exists(tmp_path / "dt" / "2026-10-08" / "estado_phicube.json") and os.path.exists(tmp_path / "dt" / "2026-10-08" / "estado_fluxo.json")


# ── setup de niveis (o que os instrutores fazem nas lives): teste de nivel e reacao ──────────────
def _dois_dias(hoje_precos):
    """Ontem: um pregao de 5.000 a 5.040 (maxima 5.040,0, minima 5.000,0, fecha em 5.020,0). Hoje: os fechamentos dados,
    um por minuto a partir das 9h00, com maxima e minima meio ponto alem."""
    import numpy as np
    import pandas as pd
    ontem = pd.date_range("2026-10-07 09:00", periods=540, freq="min")
    c1 = np.r_[np.linspace(5010, 5040, 200), np.linspace(5040, 5000, 200), np.linspace(5000, 5020, 140)]
    c1 = np.round(c1 * 2) / 2
    hoje = pd.date_range("2026-10-08 09:00", periods=len(hoje_precos), freq="min")
    c2 = np.array(hoje_precos, dtype=float)
    c = np.r_[c1, c2]
    return pd.DataFrame({"o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "n": 10.0, "v": 100.0}, index=ontem.append(hoje))


def test_nivel_e_reacao_vende_a_rejeicao_da_maxima_de_ontem():
    from quant.daytrade import barras as br, estrategias_hist as eh, historico as hist
    # hoje abre em 5.022 e sobe ate encostar na maxima de ontem (5.040,5 com a sombra); a barra de 4 minutos das 9h28
    # vai a 5.040,0 e fecha de volta em 5.038,0
    sobe = [5022.0 + 0.5 * k for k in range(28)]                       # 9h00 a 9h27: 5.022,0 ate 5.035,5
    teste = [5037.5, 5040.0, 5039.0, 5038.0]                           # 9h28 a 9h31: encosta e volta
    df = _dois_dias(sobe + teste)
    est = eh.NivelReacao()
    est.preparar(df)
    i = len(df) - 1
    assert est.nova_s[i] and est.max_ontem[i] == 5040.5
    nomes = est.niveis_com_nome(i, 5038.0)
    assert nomes[5040.5] == "máxima de ontem" and nomes[5040.0] == "número redondo" and nomes[5020.0] == "fechamento de ontem"
    o = est.decidir(i, None, {})
    # barra: abre 5.037,5, maxima 5.040,5, fecha 5.038,0. Nivel 5.040,0: encostou e fechou 2 pontos abaixo -> vende.
    # stop 1 ponto acima da maxima da barra = 5.041,5 -> 3,5 de risco + 0,5 do tick = 4,0; alvo: o nivel seguinte a 13+ pontos
    # abaixo e 5.022,0 (a abertura), 16 pontos. 16 / 4 = 4 vezes o risco.
    assert o and (o.lado, o.stop_pts, o.alvo_pts, o.parcial_pts, o.nivel) == ("V", 4.0, 16.0, 4.0, 5040.0)
    assert o.nome_nivel == "número redondo"
    # ao vivo, sobre as mesmas barras, a ordem e a mesma, com o ajuste oficial entrando como nivel de fora
    sinal = br.SinalNiveis()
    leitura, ordem = sinal.atualizar(df, [(5027.758, "ajuste de ontem")])
    assert leitura["pronto"] and leitura["acima"] == 5040.0 and leitura["abaixo"] == 5030.0
    assert {"preco": 5028.0, "nome": "ajuste de ontem"} in leitura["niveis"]
    assert ordem and (ordem.lado, ordem.stop_pts) == ("V", 4.0) and sinal.atualizar(df)[1] is None
    # sem rejeicao (fechou colado no nivel) nao ha ordem; com o stop caro (sombra longa) tambem nao
    assert eh.NivelReacao().__class__ and br.SinalNiveis().atualizar(_dois_dias(sobe + [5037.5, 5040.0, 5039.5, 5039.5]))[1] is None
    caro = _dois_dias(sobe + teste)
    caro.iloc[-3, caro.columns.get_loc("h")] = 5041.5                 # fura 1,5 ponto: ainda vale, mas o stop iria a 5.042,5
    assert br.SinalNiveis(stop_max=4.0).atualizar(caro)[1] is None
    # o simulador com a mesma regra faz o negocio no dia
    neg = hist.simular(_dois_dias(sobe + teste + [5037.0, 5034.0, 5030.0, 5026.0, 5022.0, 5020.0]), eh.NivelReacao(), hist.RegrasDoDia(), hist.Custos())
    # vende a 5.036,5 (abertura 5.037,0 menos 1 tick); parcial de 1 em 5.032,5 (+4); alvo de 1 em 5.020,5 (+16): 20 x 10 - 4,80
    neg = [x for x in neg if str(x.dia) == "2026-10-08"]              # o pregao de ontem, de mentira, tambem gera negocios
    assert len(neg) == 1 and neg[0].lado == "V" and neg[0].saida == "alvo" and neg[0].resultado == pytest.approx(195.20)


def test_minutos_tirados_da_fita_tem_maxima_e_minima():
    from quant.daytrade import barras as br
    import pandas as pd
    f = fx.Fita("WDOX26", 0.5)
    base = int(pd.Timestamp("2026-10-08 10:15:00").timestamp())       # a fita carimba a hora de Brasilia como se fosse UTC
    for seg, preco, vol in ((0, 5030.0, 10), (20, 5032.5, 5), (40, 5029.5, 8), (59, 5031.0, 2), (60, 5031.5, 4), (125, 5033.0, 1)):
        _por(f, base + seg, preco, vol, 0)
    m = br.minutos_da_fita(f)
    # o minuto das 10h15 fechou: abre 5.030,0, maxima 5.032,5, minima 5.029,5, fecha 5.031,0, volume 25. O das 10h17 ainda corre.
    assert m[0] == (pd.Timestamp("2026-10-08 10:15:00"), 5030.0, 5032.5, 5029.5, 5031.0, 25.0)
    assert [x[0].strftime("%H:%M") for x in m] == ["10:15", "10:16"]
    assert br.minutos_da_fita(f, depois_de=pd.Timestamp("2026-10-08 10:15:00"))[0][0].strftime("%H:%M") == "10:16"
    # onde a fita tem o minuto inteiro, ela vale; o resto vem do fechamento do motor
    juntos = br.juntar_minutos([(pd.Timestamp("2026-10-08 10:14:00"), 5029.0), (pd.Timestamp("2026-10-08 10:15:00"), 5031.0)], m)
    assert len(juntos) == 3 and len(juntos[0]) == 2 and juntos[1][2] == 5032.5


def test_robo_no_setup_de_niveis(tmp_path, monkeypatch):
    from quant.daytrade import historico as hist
    rf, _r0, mt5 = _robo(tmp_path, monkeypatch, "2026-10-08")
    monkeypatch.setattr(rf, "ATIVOS", ("WDOFUT",))
    (tmp_path / "modo_robo.json").write_text(json.dumps({"niveis_opera": True}))     # o teste de nivel operando, como em 08/10
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos, r.ajustes = {"WDOFUT": "WDOX26"}, {"WDOFUT": 5027.758}
    leitura = {"pronto": True, "setup": "niveis", "tempo_min": 4, "fechamento": 5038.0, "barra": [5037.5, 5040.5, 5037.0, 5038.0],
               "niveis": [{"preco": 5022.0, "nome": "abertura"}, {"preco": 5030.0, "nome": "número redondo"},
                          {"preco": 5040.0, "nome": "máxima de ontem"}], "acima": 5040.0, "abaixo": 5030.0, "barras": 9000}
    vistos = []

    class Falso:
        def __init__(self): self.vez = 0
        def atualizar(self, df, extras=()):
            self.vez += 1
            vistos.append(list(extras))
            return leitura, (hist.Ordem("V", 4.0, parcial_pts=4.0, alvo_pts=16.0, nivel=5040.0, nome_nivel="máxima de ontem") if self.vez == 1 else None)
    r.sinais_pc["WDOFUT"] = Falso()
    agora = datetime(2026, 10, 8, 10, 16, 7, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5038.0, agora.timestamp())}})
    pos = r.estados["WDOFUT"].posicao
    # vende a mercado em 5.037,5; stop 4 pontos acima = 5.041,5; alvo 16 pontos abaixo = 5.021,5
    assert pos and (pos.tecnica, pos.lado, pos.entrada, pos.stop, pos.alvo, pos.nome_nivel) == ("nível e reação", "V", 5037.5, 5041.5, 5021.5, "máxima de ontem")
    assert vistos[0] == [(5027.758, "ajuste de ontem")]                # o ajuste oficial vai para a regra como nivel
    assert est["regra"] == "niveis" and "níveis" in est["regras"]["nome"] and any("perdeu cerca de" in a for a in est["avisos"])
    assert [n["nome"] for n in est["instrumentos"][0]["niveis"]] == ["máxima de ontem", "número redondo", "abertura"]
    assert "teste de máxima de ontem" in r.diario[-1]["texto"] and est["instrumentos"][0]["grafico"]["acima"] == 5040.0
    # sem posicao, a tela diz o que ele espera
    r2 = rf.RoboFluxo("2026-10-09", saidas=[str(tmp_path / "q2.json")], pasta_mt5=str(mt5), setup="niveis")
    r2.codigos = {"WDOFUT": "WDOX26"}
    r2.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): (leitura, None)})()
    amanha = datetime(2026, 10, 9, 10, 16, 7, tzinfo=BRT)
    est2 = r2.ciclo(amanha, retrato={"q": {"WDOFUT": _cotacao(5036.0, amanha.timestamp())}})
    espera = est2["instrumentos"][0]["espera"][-1]
    assert "máxima de ontem em 5.040,0" in espera and "vende" in espera and "número redondo em 5.030,0" in espera and "compra" in espera


def test_fita_e_medida_em_toda_entrada_de_niveis_e_o_relatorio_compara(tmp_path, monkeypatch):
    from quant.daytrade import historico as hist, medir
    rf, _r0, mt5 = _robo(tmp_path, monkeypatch, "2026-10-08")
    monkeypatch.setattr(rf, "ATIVOS", ("WDOFUT",))
    # a fita do mini: fundo de 200 por janela e, nos ultimos 15 s, 150 de venda contra 30 de compra (83% de venda)
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)
    _por(f, T0 - 8, 5039.0, 10, 60)
    _por(f, T0 - 2, 5038.5, 20, 90)
    with open(mt5 / "autopilot_fita_20261008.csv", "w") as arq:
        for x in f.linhas:
            arq.write(_linha(x["seg"], x["preco"], x["compra"], x["venda"], simbolo="WDOX26") + "\n")
    (tmp_path / "modo_robo.json").write_text(json.dumps({"niveis_opera": True}))
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    leitura = {"pronto": True, "setup": "niveis", "tempo_min": 6, "fechamento": 5038.0, "barra": [5037.5, 5040.5, 5037.0, 5038.0],
               "niveis": [{"preco": 5040.0, "nome": "média de 72 (6 min)"}], "acima": 5040.0, "abaixo": None, "barras": 9000}
    ordens = [hist.Ordem("V", 4.0, parcial_pts=4.0, alvo_pts=16.0, nivel=5040.0, nome_nivel="média de 72 (6 min)")]
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): (leitura, ordens.pop() if ordens else None)})()
    agora = datetime(2026, 10, 8, 10, 16, 7, tzinfo=BRT)
    r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5038.0, agora.timestamp())}})
    pos = r.estados["WDOFUT"].posicao
    assert pos and pos.lado == "V" and "CONFIRMA" in r.diario[-1]["texto"] and "83%" in r.diario[-1]["texto"]
    sinal = json.loads(open(tmp_path / "dt" / "2026-10-08" / "sinais_niveis.jsonl").read().splitlines()[-1])
    fita = sinal["medidas"]["fita"]
    assert fita["confirmou"] is True and fita["fracao_a_favor"] == pytest.approx(0.833, abs=0.001) and fita["fonte"] == "mini"
    assert fita["volume_15s"] == 180.0 and fita["amostra_basta"] is True
    # numa COMPRA no mesmo instante a mesma fita nao confirmaria (17% a favor)
    assert r.leitura_da_fita("WDOFUT", "C", 5036.0)["confirmou"] is False
    # o negocio fecha no stop e o relatorio junta entrada e saida: 1 negocio confirmado pela fita, perdedor
    r.ciclo(agora + timedelta(seconds=30), retrato={"q": {"WDOFUT": _cotacao(5041.5, agora.timestamp() + 30)}})
    assert r.estados["WDOFUT"].posicao is None
    n = medir.negocios("niveis", str(tmp_path / "dt"))
    assert len(n) == 1 and n[0]["confirmou"] is True and n[0]["saida"] == "stop" and n[0]["resultado"] < 0
    texto = medir.relatorio("niveis", str(tmp_path / "dt"))
    assert "fita CONFIRMOU a entrada" in texto and "nível: média de 72 (6 min)" in texto and "menos de 100" in texto
    # as tres medias do Douglas entram como niveis, com nome
    from quant.daytrade import estrategias_hist as eh
    e = eh.NivelReacao(**rf.NIVEIS)
    df = _dois_dias([5022.0 + 0.05 * k for k in range(900)])
    e.preparar(df)
    nomes = set(e.niveis_com_nome(len(df) - 1, float(df["c"].iloc[-1])).values())
    assert {"média de 36 (6 min)", "média de 72 (6 min)", "média de 205 (6 min)"} <= nomes and e.tempo == 6


# ── revisao de 08/10/2026: climax de volume opera, teste de nivel so medido, limite do dia unico ──────────────
def _seg_brt(h, m, sg=0):
    """A hora de Brasilia na escala da fita (hora de parede carimbada como UTC), em 08/10/2026."""
    import calendar
    return calendar.timegm((2026, 10, 8, h, m, sg))


def _fita_com_climax(mt5, tranco=5.0, volume=450):
    """30 minutos mornos (100 contratos por minuto em 5.035,0) e o minuto das 10:15 subindo `tranco` pontos com `volume`."""
    with open(mt5 / "autopilot_fita_20261008.csv", "w") as arq:
        for k in range(30):
            arq.write(_linha(_seg_brt(9, 45 + k, 30) if 45 + k < 60 else _seg_brt(10, k - 15, 30), 5035.0, 50, 50) + "\n")
        terco = volume // 3
        arq.write(_linha(_seg_brt(10, 15, 5), 5035.0, terco, 0) + "\n")
        arq.write(_linha(_seg_brt(10, 15, 30), 5035.0 + tranco / 2, terco, 0) + "\n")
        arq.write(_linha(_seg_brt(10, 15, 55), 5035.0 + tranco, volume - 2 * terco, 0) + "\n")
        arq.write(_linha(_seg_brt(10, 16, 1), 5035.0 + tranco, 10, 10) + "\n")


def _robo_niveis(tmp_path, monkeypatch, modo=None):
    rf, _r0, mt5 = _robo(tmp_path, monkeypatch, "2026-10-08")
    monkeypatch.setattr(rf, "ATIVOS", ("WDOFUT",))
    if modo is not None:
        (tmp_path / "modo_robo.json").write_text(json.dumps(modo))
    return rf, mt5


def test_climax_de_volume_entra_contra_o_tranco_e_sai_por_tempo(tmp_path, monkeypatch):
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    _fita_com_climax(mt5)
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    assert r.climax_opera is True and r.niveis_opera is False            # o padrao depois da revisao
    r.codigos = {"WDOFUT": "WDOX26"}
    leitura = {"pronto": True, "setup": "niveis", "tempo_min": 6, "fechamento": 5040.0, "barra": [5035.0, 5040.0, 5035.0, 5040.0],
               "niveis": [{"preco": 5050.0, "nome": "número redondo"}], "acima": 5050.0, "abaixo": None, "barras": 9000}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): (leitura, None)})()
    agora = datetime(2026, 10, 8, 10, 16, 3, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5040.0, agora.timestamp(), maxima=5040.0)}})
    pos = r.estados["WDOFUT"].posicao
    # subiu 5 pontos com 4,5 vezes o volume: VENDE a mercado em 5.039,5; stop 10 acima; alvo quando devolve 80% (4 pontos)
    assert pos and (pos.tecnica, pos.lado, pos.entrada, pos.stop, pos.alvo, pos.tempo_max_s) == ("climax de volume", "V", 5039.5, 5049.5, 5035.5, 1200.0)
    assert rf.CLIMAX["tranco"] == 5.0 and rf.CLIMAX["vol"] == 3.0 and rf.CLIMAX["alvo_devolve"] == 0.8      # a calibracao de 08/10
    lc = est["instrumentos"][0]["climax"]
    assert lc["pronto"] and lc["minuto"] == "10:15" and lc["tranco"] == 5.0 and lc["volume_x"] == 4.5
    assert "contra um tranco de 5 pontos com volume de 4,5x" in r.diario[-1]["texto"]        # formato brasileiro (achado 83)
    linhas = [json.loads(x) for x in open(tmp_path / "dt" / "2026-10-08" / "sinais_niveis.jsonl").read().splitlines()]
    assert [x["tipo"] for x in linhas] == ["sinal", "entrada"] and linhas[0]["opera"] is True and linhas[0]["entrada"] == 5039.5
    assert any("climax de volume" in x.lower() for x in est["regras"]["itens"])
    # 19 minutos depois, sem stop nem alvo: segue aberta. Com 20 minutos, sai a mercado por tempo.
    depois = agora + timedelta(minutes=19)
    r.ciclo(depois, retrato={"q": {"WDOFUT": _cotacao(5041.0, depois.timestamp(), maxima=5041.0)}})
    assert r.estados["WDOFUT"].posicao is not None
    depois = agora + timedelta(minutes=20, seconds=1)
    r.ciclo(depois, retrato={"q": {"WDOFUT": _cotacao(5041.0, depois.timestamp(), maxima=5041.0)}})
    assert r.estados["WDOFUT"].posicao is None and r.operacoes[-1]["motivo"] == "tempo esgotado" and r.operacoes[-1]["saida"] == 5041.5


def test_climax_nao_entra_com_volume_normal_nem_com_a_fita_atrasada(tmp_path, monkeypatch):
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    _fita_com_climax(mt5, tranco=5.0, volume=200)                        # 2 vezes a media: nao e climax
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 8, 10, 16, 3, tzinfo=BRT)
    r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5040.0, agora.timestamp(), maxima=5040.0)}})
    assert r.estados["WDOFUT"].posicao is None and r.leitura_climax["WDOFUT"]["volume_x"] == 2.0
    # o mesmo climax, mas lido 40 s depois de o minuto fechar (a fita chegou em rajada): fica guardado como medida, nao entra
    rf2, mt52 = rf, tmp_path / "mt5b"
    mt52.mkdir()
    _fita_com_climax(mt52)
    monkeypatch.setattr(rf, "DIR_DT", str(tmp_path / "dt2"))
    r2 = rf2.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "q2.json")], pasta_mt5=str(mt52), setup="niveis")
    r2.codigos = {"WDOFUT": "WDOX26"}
    r2.sinais_pc["WDOFUT"] = r.sinais_pc["WDOFUT"]
    tarde = datetime(2026, 10, 8, 10, 16, 41, tzinfo=BRT)
    r2.ciclo(tarde, retrato={"q": {"WDOFUT": _cotacao(5040.0, tarde.timestamp(), maxima=5040.0)}})
    assert r2.estados["WDOFUT"].posicao is None
    sinal = json.loads(open(tmp_path / "dt2" / "2026-10-08" / "sinais_niveis.jsonl").read().splitlines()[-1])
    assert sinal["tipo"] == "sinal" and sinal["opera"] is False and sinal["medidas"]["atraso_fita_s"] == 40


def test_teste_de_nivel_so_medido_guarda_o_sinal_e_nao_abre_posicao(tmp_path, monkeypatch):
    from quant.daytrade import historico as hist
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    leitura = {"pronto": True, "setup": "niveis", "tempo_min": 6, "fechamento": 5038.0, "barra": [5037.5, 5040.5, 5037.0, 5038.0],
               "niveis": [{"preco": 5040.0, "nome": "máxima de ontem"}], "acima": 5040.0, "abaixo": None, "barras": 9000}
    ordens = [hist.Ordem("V", 4.0, parcial_pts=4.0, alvo_pts=16.0, nivel=5040.0, nome_nivel="máxima de ontem")]
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): (leitura, ordens.pop() if ordens else None)})()
    agora = datetime(2026, 10, 8, 10, 16, 7, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5038.0, agora.timestamp())}})
    assert r.estados["WDOFUT"].posicao is None and r.estados["WDOFUT"].operacoes == 0
    sinal = json.loads(open(tmp_path / "dt" / "2026-10-08" / "sinais_niveis.jsonl").read().splitlines()[-1])
    assert (sinal["tipo"], sinal["tecnica"], sinal["opera"], sinal["entrada"], sinal["stop_pts"], sinal["alvo_pts"]) == \
        ("sinal", "nível e reação", False, 5037.5, 4.0, 16.0)
    assert "só medindo" in r.diario[-1]["texto"] and "venderia a 5.037,5" in r.diario[-1]["texto"]
    assert any("só medindo" in f for f in est["instrumentos"][0]["espera"])


def test_limite_de_perdas_vale_para_o_dia_mesmo_trocando_de_regra(tmp_path, monkeypatch):
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    pasta = tmp_path / "dt" / "2026-10-08"
    pasta.mkdir(parents=True, exist_ok=True)
    ops = [{"ativo": "WDOFUT", "hora_entrada": f"13:4{k}:00", "tipo": "saida", "motivo": "stop", "resultado": -70.0, "custos": 4.8} for k in range(2)]
    ops += [{"ativo": "WDOFUT", "hora_entrada": "14:13:04", "tipo": "parcial", "resultado": 17.6, "custos": 2.4},
            {"ativo": "WDOFUT", "hora_entrada": "14:13:04", "tipo": "saida", "motivo": "zero a zero", "resultado": -7.4, "custos": 2.4}]
    (pasta / "estado_fluxo.json").write_text(json.dumps({"operacoes": ops}))
    _fita_com_climax(mt5)
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    assert r.outras == {"resultado": -129.8, "perdas": 2}               # o negocio com parcial fechou positivo: nao e perda
    (pasta / "estado_phicube.json").write_text(json.dumps({"operacoes": [
        {"ativo": "WDOFUT", "hora_entrada": "15:10:00", "tipo": "saida", "motivo": "stop", "resultado": -90.0, "custos": 4.8}]}))
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    assert r.outras["perdas"] == 3
    agora = datetime(2026, 10, 8, 10, 16, 3, tzinfo=BRT)
    r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5040.0, agora.timestamp(), maxima=5040.0)}})
    # ha um climax pronto na fita, mas o dia ja tem 3 perdedores em outras regras: nao entra e trava
    assert r.estados["WDOFUT"].posicao is None and r.trava == "tres_perdas"
    assert any("em outra regra" in d["texto"] for d in r.diario)


def test_barra_inteira_toma_o_lugar_da_que_entrou_so_com_o_fechamento(tmp_path):
    import pandas as pd
    from quant.daytrade import barras as br
    b = br.Barras("WDOFUT", str(tmp_path / "dt"), str(tmp_path / "sem_mt5"))
    t1, t2 = pd.Timestamp("2026-10-08 10:15"), pd.Timestamp("2026-10-08 10:16")
    assert b.acrescentar([(t1, 5030.0)]) == 1 and b.df.at[t1, "h"] == 5030.0 and b.df.at[t1, "v"] == 0.0
    assert b.acrescentar([(t1, 5029.5, 5031.0, 5029.0, 5030.0, 800.0), (t2, 5030.0, 5030.5, 5029.5, 5030.5, 300.0)]) == 2
    assert (b.df.at[t1, "h"], b.df.at[t1, "l"], b.df.at[t1, "v"]) == (5031.0, 5029.0, 800.0) and len(b.df) == 2
    assert b.acrescentar([(t1, 5000.0, 5000.0, 5000.0, 5000.0, 9.0)]) == 0      # barra inteira ja guardada nao e trocada
    de_novo = br.Barras("WDOFUT", str(tmp_path / "dt"), str(tmp_path / "sem_mt5"))
    assert (de_novo.df.at[t1, "h"], de_novo.df.at[t1, "v"]) == (5031.0, 800.0) and len(de_novo.df) == 2


def _dia_com_tranco(depois):
    """Um pregao: das 9h00 as 9h59 parado em 5.030 com 100 contratos por minuto; as 10h00 sobe 5 pontos com 500; depois, `depois`."""
    import pandas as pd
    idx = pd.date_range("2026-10-08 09:00", periods=61 + len(depois), freq="min")
    o = [5030.0] * 60 + [5030.0] + [x[0] for x in depois]
    h = [5030.0] * 60 + [5035.0] + [x[1] for x in depois]
    l = [5030.0] * 60 + [5030.0] + [x[2] for x in depois]
    c = [5030.0] * 60 + [5035.0] + [x[3] for x in depois]
    v = [100.0] * 60 + [500.0] + [100.0] * len(depois)
    return pd.DataFrame({"o": o, "h": h, "l": l, "c": c, "n": 0.0, "v": v}, index=idx)


def test_climax_no_historico_alvo_tempo_e_volume_normal():
    from quant.daytrade import estrategias_hist as eh, historico as hist
    regras = hist.RegrasDoDia(meta_rs=None, perda_maxima_rs=None, perdas_para_parar=None)
    est = dict(tranco=4.0, vol=3.0, stop_fixo=10.0, alvo_devolve=0.6, tempo_max=20)
    # devolve: abre 5.035, vende a 5.034,5 (1 tick contra); alvo 3 pontos abaixo = 5.031,5, batido no terceiro minuto
    volta = [(5035.0, 5035.0, 5034.0, 5034.0), (5034.0, 5034.0, 5032.5, 5032.5), (5032.5, 5032.5, 5031.0, 5031.0)] + [(5031.0,) * 4] * 30
    n = hist.simular(_dia_com_tranco(volta), eh.Climax(**est), regras)
    assert len(n) == 1 and (n[0].lado, n[0].entrada, n[0].saida, n[0].pontos) == ("V", 5034.5, "alvo", 3.0)
    assert n[0].info["volume_x"] == 5.0 and n[0].resultado == pytest.approx(3.0 * 10 * 2 - 4.8)
    # nao devolve: 20 minutos depois sai a mercado, 1 tick contra
    parado = [(5035.0,) * 4] * 40
    n = hist.simular(_dia_com_tranco(parado), eh.Climax(**est), regras)
    assert len(n) == 1 and n[0].saida == "tempo" and n[0].pontos == -1.0
    # o mesmo tranco com volume de 2 vezes a media nao e climax
    df = _dia_com_tranco(volta)
    df.iloc[60, df.columns.get_loc("v")] = 200.0
    assert hist.simular(df, eh.Climax(**est), regras) == []


def test_medir_calcula_o_que_o_sinal_guardado_teria_dado(tmp_path):
    import pandas as pd
    from quant.daytrade import medir
    df = _dia_com_tranco([(5035.0, 5035.0, 5034.0, 5034.0), (5034.0, 5034.0, 5031.0, 5031.0)] + [(5031.0,) * 4] * 30)
    ev = {"tipo": "sinal", "ativo": "WDOFUT", "lado": "V", "entrada": 5034.5, "stop_pts": 10.0, "alvo_pts": 3.0, "parcial_pts": 3.0,
          "tempo_max_s": 1200.0, "quando": "2026-10-08T10:01:02-03:00"}
    r = medir.hipotetico(ev, df)
    assert r["saida"] == "alvo" and r["pontos"] == 3.0 and r["resultado"] == pytest.approx(60.0 - 4.8)
    # teste de nivel: parcial em 4 pontos (metade), stop vai para a entrada e o resto sai zero a zero
    ev2 = {"lado": "C", "entrada": 5030.5, "stop_pts": 4.0, "alvo_pts": 16.0, "parcial_pts": 4.0, "quando": "2026-10-08T10:00:10-03:00"}
    df2 = _dia_com_tranco([(5035.0, 5035.0, 5034.0, 5034.0), (5034.0, 5034.0, 5031.0, 5031.0), (5031.0, 5031.0, 5030.5, 5030.5)] + [(5030.5,) * 4] * 5)
    r2 = medir.hipotetico(ev2, df2)
    assert r2["saida"] == "zero a zero" and r2["pontos"] == pytest.approx((4.0 - 0.5) / 2)
    assert medir.hipotetico(dict(ev, quando="2026-10-09T10:00:00-03:00"), df) is None       # sem barras depois do sinal


def test_climax_fraco_fica_so_medido_e_o_forte_espera_o_spread_fechar(tmp_path, monkeypatch):
    # tranco de 4 pontos com 4,5 vezes o volume: abaixo dos 5 pontos da calibracao. Guarda o sinal, nao entra, nao suja o diario.
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    _fita_com_climax(mt5, tranco=4.0)
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 8, 10, 16, 3, tzinfo=BRT)
    r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5039.0, agora.timestamp(), maxima=5039.0)}})
    sinal = json.loads(open(tmp_path / "dt" / "2026-10-08" / "sinais_niveis.jsonl").read().splitlines()[-1])
    assert r.estados["WDOFUT"].posicao is None and sinal["tipo"] == "sinal" and sinal["opera"] is False and sinal["medidas"]["opera"] is False
    assert not any("só medindo" in d["texto"] for d in r.diario)
    # tranco de 5 pontos, mas o spread esta aberto no primeiro segundo: nao entra; 4 s depois fechou: entra; passados 10 s, desiste
    monkeypatch.setattr(rf, "DIR_DT", str(tmp_path / "dt2"))
    mt52 = tmp_path / "mt5b"
    mt52.mkdir()
    _fita_com_climax(mt52)
    r2 = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "q2.json")], pasta_mt5=str(mt52), setup="niveis")
    r2.codigos = {"WDOFUT": "WDOX26"}
    r2.sinais_pc["WDOFUT"] = r.sinais_pc["WDOFUT"]
    aberto = [1.5]
    monkeypatch.setattr(rf, "spread_do_livro", lambda livro, codigo: aberto[0])
    r2.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5040.0, agora.timestamp(), maxima=5040.0)}})
    assert r2.estados["WDOFUT"].posicao is None and "WDOFUT" in r2.climax_pendente
    aberto[0] = 0.5
    depois = agora + timedelta(seconds=4)
    r2.ciclo(depois, retrato={"q": {"WDOFUT": _cotacao(5039.5, depois.timestamp(), maxima=5040.0)}})
    pos = r2.estados["WDOFUT"].posicao
    assert pos and (pos.tecnica, pos.lado, pos.entrada, pos.alvo) == ("climax de volume", "V", 5039.0, 5035.0)
    monkeypatch.setattr(rf, "DIR_DT", str(tmp_path / "dt3"))
    mt53 = tmp_path / "mt5c"
    mt53.mkdir()
    _fita_com_climax(mt53)
    r3 = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "q3.json")], pasta_mt5=str(mt53), setup="niveis")
    r3.codigos = {"WDOFUT": "WDOX26"}
    r3.sinais_pc["WDOFUT"] = r.sinais_pc["WDOFUT"]
    aberto[0] = 1.5
    r3.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5040.0, agora.timestamp(), maxima=5040.0)}})
    aberto[0] = 0.5
    tarde = agora + timedelta(seconds=11)
    r3.ciclo(tarde, retrato={"q": {"WDOFUT": _cotacao(5039.5, tarde.timestamp(), maxima=5040.0)}})
    assert r3.estados["WDOFUT"].posicao is None and "WDOFUT" not in r3.climax_pendente


def test_lote_de_partida_vem_da_configuracao_do_douglas(tmp_path, monkeypatch):
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch, modo={"lote_base": 4})
    _fita_com_climax(mt5)
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    assert r.p.lote_base == 4
    r.codigos = {"WDOFUT": "WDOX26"}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 8, 10, 16, 3, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5040.0, agora.timestamp(), maxima=5040.0)}})
    pos = r.estados["WDOFUT"].posicao
    assert pos and pos.contratos == 4 and est["regras"]["parametros"]["lote_hoje"] == 4
    aviso = next(a for a in est["avisos"] if "climax" in a)
    assert "NÃO se confirmou" in aviso and "PERDEU cerca de R$ 33 por negócio com 4 contratos" in aviso and "nenhuma ganha de 2021 a 2025" in aviso
    # lote absurdo no arquivo fica no teto da regra; sem a chave, o padrao (2)
    (tmp_path / "modo_robo.json").write_text(json.dumps({"lote_base": 50}))
    assert rf.RoboFluxo("2026-10-09", saidas=[str(tmp_path / "q2.json")], pasta_mt5=str(mt5), setup="niveis").p.lote_base == 8
    (tmp_path / "modo_robo.json").write_text(json.dumps({}))
    assert rf.RoboFluxo("2026-10-09", saidas=[str(tmp_path / "q3.json")], pasta_mt5=str(mt5), setup="niveis").p.lote_base == 2


# ── setup proprio: reversao da reacao ao dado americano (busca de 08/10/2026) ──────────────────────────────────
def _fita_do_dado(mt5, reacao=6.0, com_climax=False):
    """Manha morna em 5.030,0 e, no dado das 9h30, o mini-dolar sobe `reacao` pontos em dois minutos (9h30 e 9h31)."""
    with open(mt5 / "autopilot_fita_20261008.csv", "w") as arq:
        for k in range(30):                                            # 9h00 a 9h29
            arq.write(_linha(_seg_brt(9, k, 30), 5030.0, 50, 50) + "\n")
        vol = 300 if com_climax else 50
        arq.write(_linha(_seg_brt(9, 30, 20), 5030.0 + reacao / 2, vol, 0) + "\n")
        arq.write(_linha(_seg_brt(9, 31, 5), 5030.0 + reacao / 2, vol, 0) + "\n")
        arq.write(_linha(_seg_brt(9, 31, 40), 5030.0 + reacao, vol, 0) + "\n")
        arq.write(_linha(_seg_brt(9, 32, 1), 5030.0 + reacao, 10, 10) + "\n")


def test_horario_de_verao_dos_eua_define_a_hora_do_dado():
    from datetime import date
    from quant.daytrade import barras as br
    assert [br.verao_eua(date(2026, 3, 7)), br.verao_eua(date(2026, 3, 8)), br.verao_eua(date(2026, 10, 31)), br.verao_eua(date(2026, 11, 1))] == [False, True, True, False]
    assert [br.verao_eua(date(2024, 3, 9)), br.verao_eua(date(2024, 3, 10)), br.verao_eua(date(2024, 11, 2)), br.verao_eua(date(2024, 11, 3))] == [False, True, True, False]
    s = br.SinalDado()
    assert [x.strftime("%H:%M") for x in s.horarios(date(2026, 10, 9))] == ["09:30", "09:31", "09:32"]
    assert [x.strftime("%H:%M") for x in s.horarios(date(2026, 12, 4))] == ["10:30", "10:31", "10:32"]


def test_setup_do_dado_entra_contra_a_reacao_mesmo_na_pausa_e_sai_por_tempo(tmp_path, monkeypatch):
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    _fita_do_dado(mt5, reacao=6.0)
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    assert r.dado_opera is True and rf.DADO == {"minutos": 2, "limiar": 3.0, "stop": 40.0, "tempo_max": 120, "atraso_max_s": 8}
    r.codigos = {"WDOFUT": "WDOX26"}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 8, 9, 32, 3, tzinfo=BRT)                # dentro da pausa do dado (9h28 a 9h40): este setup passa
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5036.0, agora.timestamp(), maxima=5036.0)}})
    pos = r.estados["WDOFUT"].posicao
    # subiu 6 pontos na reacao: VENDE a mercado em 5.035,5; stop 40 pontos acima; sem alvo, sem parcial; 120 minutos
    assert pos and (pos.tecnica, pos.lado, pos.entrada, pos.stop, pos.alvo, pos.sem_parcial, pos.tempo_max_s) == \
        ("reversão do dado", "V", 5035.5, 5075.5, None, True, 7200.0)
    assert "contra a reação de +6 pontos ao dado das 09h30" in r.diario[-1]["texto"] and est["posicoes"][0]["parcial_em"] is None \
        and "faltam 120 minutos" in est["posicoes"][0]["proximo_passo"]
    assert est["instrumentos"][0]["dado"]["movimento"] == 6.0 and any("SETUP PRÓPRIO" in x for x in est["regras"]["itens"])
    sinal = json.loads(open(tmp_path / "dt" / "2026-10-08" / "sinais_niveis.jsonl").read().splitlines()[0])
    assert (sinal["tipo"], sinal["tecnica"], sinal["opera"], sinal["stop_pts"], sinal["tempo_max_s"]) == ("sinal", "reversão do dado", True, 40.0, 7200.0)
    # 5 pontos a favor: NAO faz parcial nem leva o stop para a entrada (a regra testada nao tem parcial)
    depois = agora + timedelta(minutes=30)
    r.ciclo(depois, retrato={"q": {"WDOFUT": _cotacao(5030.5, depois.timestamp(), maxima=5036.0)}})
    pos = r.estados["WDOFUT"].posicao
    assert pos and pos.contratos == 2 and pos.stop == 5075.5 and not pos.parcial_feita and len(r.operacoes) == 0
    # passados 120 minutos, sai a mercado
    fim = agora + timedelta(minutes=120, seconds=1)
    r.ciclo(fim, retrato={"q": {"WDOFUT": _cotacao(5031.0, fim.timestamp(), maxima=5036.0)}})
    assert r.estados["WDOFUT"].posicao is None and r.operacoes[-1]["motivo"] == "tempo esgotado" and r.operacoes[-1]["pontos"] == 4.0


def test_setup_do_dado_nao_entra_com_reacao_pequena_e_reserva_a_vaga_antes_do_dado(tmp_path, monkeypatch):
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    _fita_do_dado(mt5, reacao=3.0)                                   # exatamente 3 pontos nao basta: o gatilho pede MAIS de 3
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": True, "setup": "niveis", "tempo_min": 6,
                                           "fechamento": 5033.0, "barra": [5030.0] * 4, "niveis": [{"preco": 5040.0, "nome": "número redondo"}],
                                           "acima": 5040.0, "abaixo": None, "barras": 9000}, None)})()
    agora = datetime(2026, 10, 8, 9, 32, 3, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5033.0, agora.timestamp(), maxima=5033.0)}})
    assert r.estados["WDOFUT"].posicao is None and r.leitura_dado["WDOFUT"]["movimento"] == 3.0
    assert any("sem entrada hoje" in f for f in est["instrumentos"][0]["espera"])
    # das 9h08 as 9h32 as outras leituras nao abrem posicao (a vaga e do setup proprio); fora disso, sim
    assert r._perto_do_dado(datetime(2026, 10, 8, 9, 7, 59, tzinfo=BRT)) is False
    assert r._perto_do_dado(datetime(2026, 10, 8, 9, 20, 0, tzinfo=BRT)) is True
    assert r._perto_do_dado(datetime(2026, 10, 8, 9, 32, 5, tzinfo=BRT)) is True
    assert r._perto_do_dado(datetime(2026, 10, 8, 9, 32, 11, tzinfo=BRT)) is False
    assert r._perto_do_dado(datetime(2026, 12, 4, 9, 20, 0, tzinfo=BRT)) is False and r._perto_do_dado(datetime(2026, 12, 4, 10, 20, 0, tzinfo=BRT)) is True


def test_robo_reabre_o_metatrader_sozinho_quando_as_cotacoes_vem_em_rajadas(tmp_path, monkeypatch):
    rf, r, _mt5 = _robo(tmp_path, monkeypatch, "2026-10-09")
    chamadas = []
    monkeypatch.setattr(rf, "reabrir_metatrader", lambda: chamadas.append(1))
    monkeypatch.setattr(rf, "metatrader_aberto", lambda: True)
    monkeypatch.setattr(rf.threading, "Thread", lambda target, daemon=None: type("T", (), {"start": lambda self: target()})())
    agora = datetime(2026, 10, 9, 10, 45, 0, tzinfo=BRT)       # depois da abertura da B3 (22/10/2026)

    def leitura(sem_tique, atraso, quando=agora):
        r.feed, r.feed_em = {"sem_tique_s": sem_tique, "atraso_ms": atraso, "mt5": "ligado"}, r.feed_em + 6.0
        return r._vigiar_feed(quando)
    # saudavel: nada. Duas leituras ruins: ainda nada. A terceira seguida: reabre.
    assert [leitura(0.3, 180.0), leitura(31.0, 24000.0), leitura(4.0, 24000.0)] == [False, False, False] and chamadas == []
    assert leitura(22.0, 24500.0) is True and chamadas == [1] and "Reabrindo o MetaTrader sozinho (1ª vez hoje)" in r.diario[-1]["texto"]
    # logo depois nao repete (espera de 15 minutos), mesmo que siga ruim
    assert [leitura(35.0, 30000.0) for _ in range(4)] == [False] * 4 and chamadas == [1]
    # passada a espera e ainda ruim: reabre de novo. A mesma leitura da saude nao conta duas vezes; leitura boa zera a contagem
    r.reconectou_em = 0.0
    assert leitura(35.0, 30000.0) is True and chamadas == [1, 1] and "2ª vez hoje" in r.diario[-1]["texto"]
    r.reconectou_em = 0.0
    assert r._vigiar_feed(agora) is False and leitura(0.2, 150.0) is False and r.feed_ruim == 0
    # fora do pregao, com o MetaTrader fechado de proposito ou no limite do dia: nao reabre
    for _ in range(3):
        assert leitura(40.0, 30000.0, datetime(2026, 10, 9, 18, 40, 0, tzinfo=BRT)) is False
    monkeypatch.setattr(rf, "metatrader_aberto", lambda: False)
    reconexoes, r.reconexoes = r.reconexoes, 0                  # fechado de proposito (o robo nao fechou nada hoje): nao abre
    assert [leitura(40.0, 30000.0) for _ in range(4)] == [False] * 4 and chamadas == [1, 1]
    # 14/10/2026: fechado PELO ROBO para reabrir, e a XP nao voltou: ele insiste (com a mesma espera de 15 minutos)
    r.reconexoes, r.reconectou_em = reconexoes, 0.0
    assert leitura(40.0, 30000.0) is True and chamadas == [1, 1, 1] and "não voltou: tentando abrir de novo (3ª vez hoje)" in r.diario[-1]["texto"]
    assert [leitura(40.0, 30000.0) for _ in range(4)] == [False] * 4 and chamadas == [1, 1, 1]
    monkeypatch.setattr(rf, "metatrader_aberto", lambda: True)
    r.reconexoes = rf.FEED_RUIM["max_por_dia"]
    assert [leitura(40.0, 30000.0) for _ in range(4)] == [False] * 4 and chamadas == [1, 1, 1]
    monkeypatch.setattr(rf, "metatrader_aberto", lambda: False)  # no limite do dia nem fechado pelo robo ele insiste
    r.reconectou_em = 0.0
    assert leitura(40.0, 30000.0) is False and chamadas == [1, 1, 1]



def test_robo_nao_reabre_o_metatrader_pelo_engasgo_da_abertura_nem_logo_depois_de_reabrir(tmp_path, monkeypatch):
    # 22/10/2026: das 10h02 as 10h14 o robo reabriu o MetaTrader 5 vezes (uma a cada 3 min): na abertura da B3 a XP engasga e o atraso
    # tipico do motor vai a 25-28 s; cada reabertura gerava outro engasgo. O atraso tipico nao conta na abertura (09h58 as 10h20) nem nos
    # 10 min depois de uma reabertura; a parada de verdade (sem tique) conta sempre
    rf, r, _mt5 = _robo(tmp_path, monkeypatch, "2026-10-22")
    chamadas = []
    monkeypatch.setattr(rf, "reabrir_metatrader", lambda: chamadas.append(1))
    monkeypatch.setattr(rf, "metatrader_aberto", lambda: True)
    monkeypatch.setattr(rf.threading, "Thread", lambda target, daemon=None: type("T", (), {"start": lambda self: target()})())
    abertura = datetime(2026, 10, 22, 10, 2, 13, tzinfo=BRT)

    def leitura(sem_tique, atraso, quando):
        r.feed, r.feed_em = {"sem_tique_s": sem_tique, "atraso_ms": atraso, "mt5": "ligado"}, r.feed_em + 6.0
        return r._vigiar_feed(quando)
    assert [leitura(1.0, 28000.0, abertura) for _ in range(6)] == [False] * 6 and chamadas == [], "engasgo da abertura: nao reabre"
    assert [leitura(35.0, 28000.0, abertura) for _ in range(3)] == [False, False, True] and chamadas == [1], "parada de verdade: reabre"
    depois = datetime(2026, 10, 22, 10, 30, 0, tzinfo=BRT)
    r.reconectou_em = rf.time.time() - 300.0                   # reabriu ha 5 min: o atraso tipico ainda e o engasgo da reabertura
    assert [leitura(1.0, 28000.0, depois) for _ in range(4)] == [False] * 4 and chamadas == [1]
    r.reconectou_em = rf.time.time() - 1000.0                  # passados a carencia e a espera: atraso tipico alto de novo conta
    assert [leitura(1.0, 28000.0, depois) for _ in range(3)] == [False, False, True] and chamadas == [1, 1]
    assert rf.FEED_RUIM["max_por_dia"] == 3 and rf.FEED_RUIM["espera_s"] == 900.0


def test_reabrir_devolve_a_frente_da_tela_ao_aplicativo_que_estava_nela(monkeypatch):
    from quant.daytrade import ligar_fita as lf
    frentes = [("com.google.Chrome", "Google Chrome"), (None, "wine"), ("com.google.Chrome", "Google Chrome"), (None, "wine")]
    abertos = []
    monkeypatch.setattr(lf, "_frente", lambda: frentes.pop(0) if frentes else ("com.google.Chrome", "Google Chrome"))
    monkeypatch.setattr(lf.subprocess, "run", lambda cmd, **k: abertos.append(cmd))
    monkeypatch.setattr(lf.time, "sleep", lambda s: None)
    relogio = [0.0]
    def _t():
        relogio[0] += 0.5
        return relogio[0]
    monkeypatch.setattr(lf.time, "time", _t)
    lf.devolver_foco("com.google.Chrome", segundos=3.0)
    assert abertos.count(["open", "-b", "com.google.Chrome"]) == 2, abertos
    assert lf._eh_metatrader(None, "wine") and lf._eh_metatrader("net.metaquotes.wine.MetaTrader5", None) and not lf._eh_metatrader("com.google.Chrome", "Google Chrome")
    abertos.clear()
    lf.devolver_foco("net.metaquotes.wine.MetaTrader5", segundos=3.0)    # o proprio MetaTrader estava na frente: nada a devolver
    assert abertos == []

def test_robo_nao_reabre_o_metatrader_quando_o_mac_acabou_de_acordar(tmp_path, monkeypatch):
    # 09/10/2026: tampa fechada as 13h59; a cada despertar de manutencao o robo via preco velho e reabria o MetaTrader a toa
    rf, r, _mt5 = _robo(tmp_path, monkeypatch, "2026-10-09")
    chamadas = []
    monkeypatch.setattr(rf, "reabrir_metatrader", lambda: chamadas.append(1))
    monkeypatch.setattr(rf, "metatrader_aberto", lambda: True)
    monkeypatch.setattr(rf.threading, "Thread", lambda target, daemon=None: type("T", (), {"start": lambda self: target()})())
    relogio = [1_000_000.0]
    monkeypatch.setattr(rf.time, "time", lambda: relogio[0])
    r.vigia_em = relogio[0]
    agora = datetime(2026, 10, 9, 14, 37, 3, tzinfo=BRT)

    def leitura(sem_tique, atraso, passo=6.0):
        relogio[0] += passo
        r.feed, r.feed_em = {"sem_tique_s": sem_tique, "atraso_ms": atraso, "mt5": "ligado"}, relogio[0]
        return r._vigiar_feed(agora)
    # o robo ficou 15 minutos sem rodar (Mac dormindo) e acorda vendo preco de 23 minutos atras: nao reabre
    assert leitura(1358.0, 0.0, passo=900.0) is False
    assert [leitura(1370.0, 0.0) for _ in range(5)] == [False] * 5 and chamadas == []
    # passada a carencia de 2 minutos, se continuar sem preco, ai sim reabre
    assert [leitura(1500.0, 0.0) for _ in range(14)] == [False] * 14
    assert [leitura(1600.0, 0.0) for _ in range(3)] == [False, False, True] and chamadas == [1]      # tres leituras ruins contadas depois da carencia


# ── limites de risco de prazo longo e lote limitado pelo stop (metodo de 10/10/2026) ─────────────────────────────
def test_perda_da_semana_e_queda_maxima_param_o_robo(tmp_path, monkeypatch):
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    (tmp_path / "dt").mkdir(exist_ok=True)
    serie = tmp_path / "dt" / "serie_niveis.json"
    # semana de 05 a 09/10/2026: ja perdeu R$ 1.900 ate quinta; sexta abre operando e para ao perder mais R$ 100
    serie.write_text(json.dumps([{"data": "2026-10-02", "resultado": 500.0}, {"data": "2026-10-05", "resultado": -900.0},
                                 {"data": "2026-10-08", "resultado": -1000.0}]))
    _fita_do_dado(mt5, reacao=6.0)
    r = rf.RoboFluxo("2026-10-09", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    assert r.trava is None and r._semana_e_queda(0.0) == (-1900.0, -1900.0)          # pico em +500 (02/10); hoje 1.900 abaixo
    assert r._limite_longo(-100.0) == "semana" and r._limite_longo(-50.0) is None
    # na semana seguinte a conta da semana recomeca, mas a queda desde o pico continua contando
    r2 = rf.RoboFluxo("2026-10-13", saidas=[str(tmp_path / "q2.json")], pasta_mt5=str(mt5), setup="niveis")
    assert r2.trava is None and r2._semana_e_queda(0.0) == (0.0, -1900.0)
    # limite da semana ja estourado antes de abrir: o robo nasce parado e a tela diz por que
    serie.write_text(json.dumps([{"data": "2026-10-05", "resultado": -900.0}, {"data": "2026-10-08", "resultado": -1200.0}]))
    r3 = rf.RoboFluxo("2026-10-09", saidas=[str(tmp_path / "q3.json")], pasta_mt5=str(mt5), setup="niveis")
    assert r3.trava == "semana"
    r3.codigos = {"WDOFUT": "WDOX26"}
    agora = datetime(2026, 10, 9, 10, 0, 0, tzinfo=BRT)
    est = r3.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5030.0, agora.timestamp())}})
    assert "Perda máxima da semana" in est["vivo"]["fase_texto"] and est["risco"]["semana"] == -2100.0 and est["risco"]["limite_semana"] == -2000.0
    # queda maxima: R$ 10 mil abaixo do pico para ate o Douglas religar; "queda_zerada_em" recomeca a contagem
    serie.write_text(json.dumps([{"data": "2026-08-03", "resultado": 3000.0}, {"data": "2026-09-01", "resultado": -6000.0},
                                 {"data": "2026-09-15", "resultado": -4500.0}]))
    r4 = rf.RoboFluxo("2026-10-14", saidas=[str(tmp_path / "q4.json")], pasta_mt5=str(mt5), setup="niveis")     # outro pregao: estado novo
    assert r4.trava == "queda" and r4._semana_e_queda(0.0) == (0.0, -10500.0)
    (tmp_path / "risco_robo.json").write_text(json.dumps({"queda_zerada_em": "2026-10-01", "perda_maxima_semana_rs": 1500}))
    r5 = rf.RoboFluxo("2026-10-15", saidas=[str(tmp_path / "q5.json")], pasta_mt5=str(mt5), setup="niveis")
    assert r5.trava is None and r5.risco["perda_maxima_semana_rs"] == 1500.0 and r5._semana_e_queda(0.0) == (0.0, 0.0)


def test_lote_nunca_deixa_o_stop_passar_da_perda_maxima_do_dia(tmp_path, monkeypatch):
    # lote de 4 pedido, stop de 40 pontos: 4 contratos arriscariam R$ 1.630; cabem 2 (R$ 815) na perda maxima de R$ 1.000
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch, modo={"lote_base": 4})
    _fita_do_dado(mt5, reacao=6.0)
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 8, 9, 32, 3, tzinfo=BRT)
    r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5036.0, agora.timestamp(), maxima=5036.0)}})
    pos = r.estados["WDOFUT"].posicao
    assert pos and pos.tecnica == "reversão do dado" and pos.contratos == 2


# ── duas chaves de ganho do dia em risco_robo.json (11/10/2026): o OBJETIVO (so placar) e o TETO (zera e para) ──────────────────────
MEDICAO = {"pregoes": 1055, "teto_testado_rs": 100.0, "media_por_pregao_sem_teto_rs": 33.7, "media_por_pregao_com_teto_rs": 1.8,
           "pior_dia_sem_teto_rs": -815.0, "pior_dia_com_teto_rs": -815.0}


def test_chaves_do_arquivo_de_risco_e_os_textos_saem_do_valor(tmp_path):
    from quant.daytrade import chave
    arq = tmp_path / "risco_robo.json"
    r = chave.risco(str(arq))                                                   # sem arquivo: sem objetivo; o teto vale o padrao do codigo
    assert r["objetivo_dia_rs"] is None and r["meta_dia_rs"] is None and ef.ParamFluxo().meta_dia_rs == 1000.0
    arq.write_text(json.dumps({"objetivo_dia_rs": 100.0, "meta_dia_rs": 1000.0, "queda_maxima_rs": 10000}))
    r = chave.risco(str(arq))
    assert r["objetivo_dia_rs"] == 100.0 and r["meta_dia_rs"] == 1000.0 and r["queda_maxima_rs"] == 10000.0 and r["perda_maxima_semana_rs"] == 2000.0
    for ruim in (0, -5, "abc", None):                                           # valor invalido nao liga nada
        arq.write_text(json.dumps({"objetivo_dia_rs": ruim, "meta_dia_rs": ruim}))
        r = chave.risco(str(arq))
        assert r["objetivo_dia_rs"] is None and r["meta_dia_rs"] is None
    # o JSON da medicao: so vale completo
    bom = tmp_path / "medicao.json"
    bom.write_text(json.dumps(dict(MEDICAO, fonte="x", data="2026-10-11")))
    assert ef.carregar_medicao(str(bom))["pregoes"] == 1055
    bom.write_text(json.dumps({"pregoes": 1055}))
    assert ef.carregar_medicao(str(bom)) is None and ef.carregar_medicao(str(tmp_path / "nao_existe.json")) is None
    real = ef.carregar_medicao()                                                # o arquivo de verdade (gerado por meta_dia.relatorio)
    assert real and real["pregoes"] == 1055 and real["teto_testado_rs"] == 100.0
    # os textos: o do objetivo (com os numeros da medicao), sem o arquivo, com objetivo diferente do medido, e o interruptor
    p = ef.ParamFluxo()
    assert ef.teto_em_texto(p) == "ao ganhar R$ 1.000 (1% do capital)" and ef.teto_em_texto(ef.ParamFluxo(meta_dia_rs=None)) is None
    assert ef.objetivo_em_texto(p, 100.0, MEDICAO) == (
        "Objetivo do dia: R$ 100 (0,10%). O robô não para ao bater o objetivo: no histórico de 1.055 pregões, parar em R$ 100 baixou o resultado médio "
        "de R$ 34 para R$ 2 por pregão sem reduzir a pior perda. O ganho que zera e para o dia é R$ 1.000.")
    assert ef.objetivo_em_texto(p, 100.0, None) == "Objetivo do dia: R$ 100 (0,10%). O robô não para ao bater o objetivo. O ganho que zera e para o dia é R$ 1.000."
    assert "1.055" not in ef.objetivo_em_texto(p, 250.0, MEDICAO) and ef.objetivo_em_texto(p, None, MEDICAO) is None
    assert "sem reduzir a pior perda" not in ef.objetivo_em_texto(p, 100.0, dict(MEDICAO, pior_dia_com_teto_rs=-500.0))     # se o teto melhorasse a pior perda, nao diz isso
    assert "PARA ao bater o objetivo" in ef.objetivo_em_texto(ef.ParamFluxo(meta_dia_rs=100.0), 100.0, MEDICAO)            # o interruptor ligado
    from quant.daytrade import robo_fluxo as rf
    for itens in (rf.regras_niveis(p, objetivo_rs=100.0, medicao=MEDICAO), rf.regras_phicube(p, 100.0, MEDICAO), ef.regras_em_texto(p, 100.0, MEDICAO)):
        assert any(x.startswith("Objetivo do dia: R$ 100 (0,10%).") for x in itens) and any("ao ganhar R$ 1.000 (1% do capital)" in x for x in itens)
        assert not any("meta de 1%" in x for x in itens)
    assert not any(x.startswith("Objetivo do dia") for x in rf.regras_niveis(p)) and not any("Objetivo" in x for x in ef.regras_em_texto(p))   # sem objetivo, sem texto


def _cenario_dia(tmp_path, monkeypatch, risco, dia="2026-10-08"):
    (tmp_path / "risco_robo.json").write_text(json.dumps(risco))
    rf, r, mt5 = _robo(tmp_path, monkeypatch, dia)
    agora = datetime(2026, 10, 8, 11, 0, 7, tzinfo=BRT)
    r.estados["WDOFUT"].posicao = ef.PosicaoF("C", 2, 5030.0, 5000.0, "10:59:00", "reversão do dado", 5030.0, "dado", 2, False, 5030.0,
                                              ts_entrada=agora.timestamp() - 60, sem_parcial=True)   # sem parcial nem alvo: so teto ou stop fecham
    return rf, r, mt5, agora


def test_objetivo_nao_zera_o_robo_mas_o_teto_zera_e_para_ate_amanha(tmp_path, monkeypatch):
    rf, r, mt5, agora = _cenario_dia(tmp_path, monkeypatch, {"objetivo_dia_rs": 100.0, "meta_dia_rs": 1000.0})
    assert r.objetivo_rs == 100.0 and r.p.meta_dia_rs == 1000.0

    def q(preco, seg=0):
        return {"q": {"WDOFUT": _cotacao(preco, (agora + timedelta(seconds=seg)).timestamp())}}
    # +10 pontos x R$ 10 x 2 contratos = R$ 200 bruto, R$ 195,20 liquidos: passou do OBJETIVO e o robo segue com a posicao aberta
    est = r.ciclo(agora, retrato=q(5040.0))
    assert r.trava is None and r.estados["WDOFUT"].posicao is not None and est["resultado"]["aberto"] == pytest.approx(195.2)
    m = est["meta"]
    assert m["atingido"] is True and m["pct_do_objetivo"] == pytest.approx(1.952) and m["faltam_rs"] == 0.0 and m["parado_ate_amanha"] is False
    assert m["objetivo_rs"] == 100.0 and m["teto_rs"] == 1000.0 and m["teto_batido"] is False and m["robo_para_ao_bater_o_objetivo"] is False
    assert est["vivo"]["fase"] != "meta_batida" and not any("Teto de ganho" in d["texto"] for d in r.diario)
    # realizado de R$ 1.000 liquidos no dia: bate o TETO, zera tudo a mercado e para
    r.operacoes = [{"tipo": "saida", "ativo": "WDOFUT", "lado": "C", "contratos": 2, "entrada": 5030.0, "hora_entrada": "10:00:00",
                    "saida": 5080.0, "hora_saida": "10:10:00", "motivo": "alvo", "pontos": 50.0, "custos": 4.8, "resultado": 995.2}]
    est = r.ciclo(agora + timedelta(seconds=1), retrato=q(5040.0, 1))
    assert r.trava == "meta" and r.estados["WDOFUT"].posicao is None and r.operacoes[-1]["motivo"] == "meta"
    m = est["meta"]
    assert m["teto_batido"] is True and m["parado_ate_amanha"] is True and m["atingido"] is True
    assert est["vivo"]["fase"] == "meta_batida" and "Teto de ganho do dia atingido" in est["vivo"]["fase_texto"]
    assert est["resultado"]["meta"] == 1000.0 and est["resultado"]["teto"] == 1000.0 and est["resultado"]["objetivo"] == 100.0
    # reiniciar no mesmo dia nao religa; amanha e outro dia
    r2 = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "q2.json")], pasta_mt5=str(mt5))
    assert r2.trava == "meta"
    r3 = rf.RoboFluxo("2026-10-09", saidas=[str(tmp_path / "q3.json")], pasta_mt5=str(mt5))
    assert r3.trava is None and r3.objetivo_rs == 100.0 and r3.p.meta_dia_rs == 1000.0


def test_interruptor_meta_dia_rs_100_faz_o_robo_parar_ao_bater_o_objetivo(tmp_path, monkeypatch):
    rf, r, mt5, agora = _cenario_dia(tmp_path, monkeypatch, {"objetivo_dia_rs": 100.0, "meta_dia_rs": 100.0})
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5040.0, agora.timestamp())}})        # R$ 195,20 liquidos: passou de R$ 100
    assert r.trava == "meta" and r.estados["WDOFUT"].posicao is None
    m = est["meta"]
    assert m["robo_para_ao_bater_o_objetivo"] is True and m["parado_ate_amanha"] is True and m["teto_rs"] == 100.0
    assert any("PARA ao bater o objetivo" in x for x in rf.regras_niveis(r.p, objetivo_rs=100.0))


def test_sem_objetivo_nao_ha_bloco_meta_e_o_teto_segue_valendo(tmp_path, monkeypatch):
    for risco in ({}, {"meta_dia_rs": 1000.0}, {"objetivo_dia_rs": 0}):
        pasta = tmp_path / str(len(str(risco)))
        pasta.mkdir()
        rf, r, mt5, agora = _cenario_dia(pasta, monkeypatch, risco)
        assert r.objetivo_rs is None and r.p.meta_dia_rs == 1000.0
        est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5031.0, agora.timestamp())}})
        assert "meta" not in est and est["resultado"]["meta"] == 1000.0 and est["resultado"]["objetivo"] is None
        assert not any(x.startswith("Objetivo do dia") for x in est["regras"]["itens"])
        assert "meta" not in json.load(open(pasta / "quant.json"))


def test_tela_traz_o_bloco_do_objetivo_e_o_placar_dos_pregoes(tmp_path, monkeypatch):
    (tmp_path / "risco_robo.json").write_text(json.dumps({"objetivo_dia_rs": 100.0, "meta_dia_rs": 1000.0}))
    rf, r, mt5 = _robo(tmp_path, monkeypatch, "2026-10-13")
    (tmp_path / "dt").mkdir(exist_ok=True)
    # pregoes anteriores: dois de antes da mudanca (sem o objetivo guardado: conta o resultado do dia contra o objetivo de hoje), um novo que bateu e um sem negocio
    (tmp_path / "dt" / "serie_fluxo.json").write_text(json.dumps([
        {"data": "2026-10-08", "resultado": 1200.0, "operacoes": 2}, {"data": "2026-10-09", "resultado": -300.0, "operacoes": 1},
        {"data": "2026-10-12", "resultado": 120.0, "operacoes": 1, "objetivo_rs": 100.0, "objetivo_batido": True, "objetivo_tocado": True},
        {"data": "2026-10-12b", "resultado": 0.0, "operacoes": 0, "objetivo_rs": 100.0, "objetivo_batido": False, "objetivo_tocado": False}]))
    r2 = rf.RoboFluxo("2026-10-13", saidas=[str(tmp_path / "q.json")], pasta_mt5=str(mt5))
    r2.codigos = r.codigos
    agora = datetime(2026, 10, 13, 11, 0, 7, tzinfo=BRT)
    est = r2.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5031.0, agora.timestamp())}})
    m = est["meta"]
    assert m["objetivo_rs"] == 100.0 and m["objetivo_pct"] == pytest.approx(0.001) and m["liquido"] is True and m["capital"] == 100_000.0
    assert m["hoje_rs"] == 0.0 and m["faltam_rs"] == 100.0 and m["atingido"] is False and m["pct_do_objetivo"] == 0.0
    assert m["teto_rs"] == 1000.0 and m["teto_pct"] == pytest.approx(0.01) and m["teto_batido"] is False and m["parado_ate_amanha"] is False
    assert (m["meta_rs"], m["pct_da_meta"], m["atingida"]) == (100.0, 0.0, False)                    # apelidos antigos = o objetivo
    pl = m["placar"]
    # 4 pregoes (hoje sem fita nem negocio nao entra); operados 3; bateram o objetivo: 08/10 (1.200 >= 100) e 12/10 (guardado)
    assert pl["pregoes"] == 4 and pl["pregoes_operados"] == 3 and pl["pregoes_bateram_o_objetivo"] == 2 and pl["pregoes_bateram_a_meta"] == 2
    assert pl["pct_operados_que_bateram"] == pytest.approx(2 / 3) and pl["acumulado_rs"] == pytest.approx(1020.0)
    assert pl["media_por_pregao"] == pytest.approx(255.0) and pl["media_por_pregao_operado"] == pytest.approx(340.0)
    assert pl["melhor_dia_rs"] == 1200.0 and pl["pior_dia_rs"] == -300.0 and pl["desde"] == "2026-10-08"
    # o dia passa do objetivo SEM parar: o pregao entra na serie como "bateu o objetivo" e nao como teto
    r2.operacoes = [{"tipo": "saida", "ativo": "WDOFUT", "lado": "C", "contratos": 2, "entrada": 5030.0, "hora_entrada": "10:00:00",
                     "saida": 5040.0, "hora_saida": "10:10:00", "motivo": "alvo", "pontos": 5.5, "custos": 4.8, "resultado": 105.2}]
    est = r2.ciclo(agora + timedelta(seconds=1), retrato={"q": {"WDOFUT": _cotacao(5031.0, (agora + timedelta(seconds=1)).timestamp())}})
    m = est["meta"]
    assert r2.trava is None and m["atingido"] is True and m["hoje_rs"] == pytest.approx(105.2) and m["pct_do_objetivo"] == pytest.approx(1.052)
    assert m["parado_ate_amanha"] is False and est["vivo"]["fase"] != "meta_batida"
    ultimo = json.load(open(tmp_path / "dt" / "serie_fluxo.json"))[-1]
    assert ultimo["data"] == "2026-10-13" and ultimo["objetivo_rs"] == 100.0 and ultimo["objetivo_batido"] is True and ultimo["meta_batida"] is False
    assert est["meta"]["placar"]["pregoes_bateram_o_objetivo"] == 3
    assert json.load(open(tmp_path / "q.json"))["meta"]["objetivo_rs"] == 100.0                      # e vai para o arquivo da tela


def test_avisos_e_fase_do_setup_de_niveis_saem_do_modo_robo(tmp_path, monkeypatch):
    def rodar(modo):
        pasta = tmp_path / ("m" + str(len(json.dumps(modo))))
        pasta.mkdir()
        rf, mt5 = _robo_niveis(pasta, monkeypatch, modo=modo)
        _fita_do_dado(mt5, reacao=3.0)
        r = rf.RoboFluxo("2026-10-08", saidas=[str(pasta / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
        r.codigos = {"WDOFUT": "WDOX26"}
        r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
        agora = datetime(2026, 10, 8, 11, 0, 3, tzinfo=BRT)
        return r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5033.0, agora.timestamp(), maxima=5033.0)}})
    # como esta o modo_robo.json de verdade: so o dado opera
    est = rodar({"dado_opera": True, "climax_opera": False, "niveis_opera": False})
    avisos = " ".join(est["avisos"])
    assert "Quem opera é a reversão da reação ao dado americano" in avisos and "mais de 3 pontos" in avisos
    assert "O climax de volume está só medido" in avisos and "Quem opera é o climax" not in avisos and "Também opera o climax" not in avisos
    assert est["vivo"]["fase_texto"].startswith("Operando o dado americano, medindo o climax de volume e os níveis: ")
    regras = " ".join(est["regras"]["itens"])
    assert "Opera a reversão do dado americano; o climax de volume e o teste de nível são só medidos." in regras and "O robô opera para gerar operações" not in regras
    # climax ligado por escolha dele: o aviso fala dele, com a ressalva da calibracao
    est = rodar({"dado_opera": True, "climax_opera": True, "niveis_opera": False})
    avisos = " ".join(est["avisos"])
    assert "Também opera o climax de volume" in avisos and "NÃO se confirmou" in avisos and "O climax de volume está só medido" not in avisos
    assert est["vivo"]["fase_texto"].startswith("Operando o dado americano e o climax de volume, medindo os níveis: ")
    # nada ligado
    est = rodar({"dado_opera": False, "climax_opera": False, "niveis_opera": False})
    assert "Nenhuma leitura opera" in " ".join(est["avisos"]) and est["vivo"]["fase_texto"].startswith("Nenhuma leitura operando, medindo ")


def test_sinal_do_dado_leva_o_tipo_do_dia_so_como_rotulo(tmp_path, monkeypatch):
    """12/10/2026: cada sinal do dado guarda que divulgacao saiu as 8h30 de NY (calendario_eua); nao muda a regra."""
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    _fita_do_dado(mt5, reacao=6.0)
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 8, 9, 32, 3, tzinfo=BRT)
    r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5036.0, agora.timestamp(), maxima=5036.0)}})
    sinal = json.loads(open(tmp_path / "dt" / "2026-10-08" / "sinais_niveis.jsonl").read().splitlines()[0])
    assert sinal["medidas"]["tipo_do_dia"] == "claims"                 # quinta-feira sem dado do BLS: pedidos de auxilio
    assert isinstance(sinal["medidas"]["deriva_pre_dado"], (int, float))   # rodada 2: deriva pre-dado tambem so como rotulo
    pos = r.estados["WDOFUT"].posicao
    assert pos and (pos.lado, pos.entrada, pos.stop) == ("V", 5035.5, 5075.5)   # a regra continua a mesma


def test_stop_vale_mesmo_com_cotacao_velha(tmp_path, monkeypatch):
    """12/10/2026 (furo A8): cotacao com mais de 15 s nao dispara entrada, mas uma posicao aberta continua sendo conduzida:
    o stop sai com o ultimo preco conhecido em vez de esperar um tique novo."""
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    _fita_do_dado(mt5, reacao=6.0)
    r = rf.RoboFluxo("2026-10-08", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 8, 9, 32, 3, tzinfo=BRT)
    r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5036.0, agora.timestamp(), maxima=5036.0)}})
    pos = r.estados["WDOFUT"].posicao
    assert pos and pos.lado == "V" and pos.stop == 5075.5
    depois = datetime(2026, 10, 8, 9, 40, 0, tzinfo=BRT)
    velha = _cotacao(5080.0, depois.timestamp() - 40.0, maxima=5080.0)       # ultimo tique ha 40 s, acima do stop
    r.ciclo(depois, retrato={"q": {"WDOFUT": velha}})
    assert r.estados["WDOFUT"].posicao is None                                 # saiu no stop com o preco velho


def test_dose_da_regra_e_janela_do_dia_configuravel(tmp_path, monkeypatch):
    """13/10/2026: a regra pode trazer a sua dose em contratos (laboratorio opera pequeno) e a janela do dia vem do modo_robo.json."""
    from quant.daytrade import estrategia_fluxo as ef2
    p = ef2.ParamFluxo()
    e = ef2.EstadoF(ativo="WDOFUT")
    f = _fita_vazia() if "_fita_vazia" in globals() else None
    sinal = {"tecnica": "laboratório", "lado": "C", "nivel": 5030.0, "nome_nivel": "lab", "stop_pts": 40.0, "alvo_pts": None, "parcial_pts": None,
             "sem_parcial": True, "sem_arrasto": True, "tempo_max_s": 1500.0, "contratos": 1, "medidas": {"risco_pts": 40.0, "fracao_a_favor": None}}
    ev = ef2.passo(e, 1000.0, "10:15:00", 5031.0, f, AJUSTE, p, lote=2, contexto={"sinal": sinal, "spread": 0.5})
    assert ev and ev[0]["tipo"] == "entrada" and ev[0]["contratos"] == 1          # a dose da regra vence o lote do dia (2)
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch, modo={"hora_ultima_entrada": "18:10", "hora_zerar": "18:24", "niveis_opera": True})
    r = rf.RoboFluxo("2026-10-14", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    assert (r.p.hora_ultima_entrada, r.p.hora_zerar) == ("18:10", "18:24")
    outra = tmp_path / "outra"
    outra.mkdir()
    rf2, mt52 = _robo_niveis(outra, monkeypatch, modo={"hora_zerar": "25:99"})
    r2 = rf2.RoboFluxo("2026-10-14", saidas=[str(outra / "quant2.json")], pasta_mt5=str(mt52), setup="niveis")
    assert r2.p.hora_zerar == "13:00"                                              # valor invalido: fica o padrao


# ── varredura de 15/10/2026: achados do robo de day trade ────────────────────────────────────────────────────
def _regra_win(tmp_path, monkeypatch, minuto="17:40"):
    """Registro com UMA regra do laboratorio do mini-indice que opera (como a do fim do pregao, decisao do Douglas de 13/10): compra na
    barra das `minuto`."""
    from quant.daytrade import regras_lab
    arq = tmp_path / "regra_win.py"
    arq.write_text("import numpy as np\n\n\ndef regra(m):\n    s = np.zeros(len(m))\n"
                   f"    if len(m) and m.index[-1].strftime('%H:%M') == '{minuto}':\n        s[-1] = 1.0\n    return s\n")
    reg = tmp_path / "setups.json"
    reg.write_text(json.dumps({"regras": [{"nome": "win_teste", "titulo": "fim do pregão (teste)", "arquivo": str(arq), "funcao": "regra",
                                           "ativo": "WINFUT", "estado": "opera", "contratos": 1, "barras": 5000, "janela": ["17:30", "18:10"],
                                           "saida": {"stop": 500, "alvo": None, "tempo": 25}}]}))
    monkeypatch.setattr(regras_lab, "ARQ_SETUPS", str(reg))


def _serie_win(dia, ate="17:40", preco=209000.0, sem=()):
    """/vivo/intradia do mini-indice: uma amostra por minuto (no segundo 30), das 9h00 ate `ate`, menos os minutos de `sem`."""
    ini = datetime.fromisoformat(f"{dia}T09:00:00-03:00")
    fim = datetime.fromisoformat(f"{dia}T{ate}:00-03:00")
    t, p, k = [], [], 0
    while ini + timedelta(minutes=k) <= fim:
        if (ini + timedelta(minutes=k)).strftime("%H:%M") not in sem:
            t.append((ini + timedelta(minutes=k)).timestamp() + 30)
            p.append(preco + 5 * (k % 7))
        k += 1
    return {"s": "WINFUT", "codigo": "WINZ26", "dia": dia, "t": t, "p": p}


def _historia_win(caminho, dias, fim="18:24", cortes=None, gravado=None, base=200000.0):
    """Historico de 1 minuto do mini-indice como o leitor do MetaTrader grava (#HISTORIA;1;WIN$N;...; cabecalho; barras; #FIM): cada dia das
    9h00 ate `fim` (ou `cortes[dia]`), subindo 2 pontos por minuto. `gravado`: a hora da gravacao do arquivo."""
    import pandas as pd
    linhas = []
    for j, d in enumerate(dias):
        for k, t in enumerate(pd.date_range(f"{d} 09:00", f"{d} {(cortes or {}).get(d, fim)}", freq="1min")):
            c = base + 100 * j + 2 * k
            linhas.append(f"{t.strftime('%Y.%m.%d %H:%M')};{c - 1:.0f};{c + 1:.0f};{c - 2:.0f};{c:.0f};100;1000")
    rotulo = caminho.name.split("_M")[-1][:-4]
    caminho.write_text(f"#HISTORIA;1;WIN$N;M{rotulo};{len(linhas)}\nhora_servidor;abertura;maxima;minima;fechamento;negocios;volume\n"
                       + "\n".join(linhas) + "\n#FIM\n", encoding="latin-1")
    if gravado is not None:
        os.utime(caminho, (gravado.timestamp(), gravado.timestamp()))
    return caminho


def _pregoes_ate(dia, n):
    """Os `n` pregoes da B3 antes de `dia` (AAAA-MM-DD), do mais velho ao mais novo."""
    from datetime import date as _date
    from quant.dados import calendario as cal
    fora, d = [], _date.fromisoformat(dia)
    while len(fora) < n:
        d = cal.pregao_anterior(d)
        fora.append(d.isoformat())
    return fora[::-1]


def _cotacao_win(preco, ts):
    return [preco, -0.4, 208000.0, 210800.0, 207235.0, 1000, 210905.0, ts, None, None, "aberto", 10, 0, 209185.0]


def test_regra_do_mini_indice_roda_mesmo_fora_dos_contratos_do_robo(tmp_path, monkeypatch):
    """Achado 10: a regra do laboratorio do mini-indice, marcada 'opera' (decisao do Douglas de 13/10), nunca rodava: o laco do robo so
    passava pelos contratos de ativos_robo.json (so o mini-dolar desde 08/10). Agora ela roda nas barras do motor e entra."""
    import pandas as pd
    _regra_win(tmp_path, monkeypatch)
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch, modo={"hora_ultima_entrada": "18:10", "hora_zerar": "18:24"})
    dia = "2026-10-15"
    _historia_win(mt5 / "autopilot_historia_WINSN_M2610151.csv", _pregoes_ate(dia, 3), gravado=datetime(2026, 10, 15, 8, 52, tzinfo=BRT))
    serie = _serie_win(dia, sem=("17:35",))                                   # o motor nao amostrou o minuto das 17:35
    lidas = []
    monkeypatch.setattr(rf, "ler_motor", lambda caminho, *a, **k: (lidas.append(caminho) or serie) if "s=WINFUT" in caminho else None)
    r = rf.RoboFluxo(dia, saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    assert rf.ATIVOS == ("WDOFUT",) and r.extras == ("WINFUT",) and r.todos == ("WDOFUT", "WINFUT")
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 15, 17, 41, 3, tzinfo=BRT)
    q = {"WDOFUT": _cotacao(5090.0, agora.timestamp()), "WINFUT": _cotacao_win(209100.0, agora.timestamp())}
    est = r.ciclo(agora, retrato={"q": q})
    assert r.codigos["WINFUT"] == "WINZ26"                                   # o contrato vem do motor, nao fica escrito no codigo
    b = r.barras["WINFUT"].df
    assert b.index[-1] == pd.Timestamp(f"{dia} 17:40") and pd.Timestamp(f"{dia} 17:35") in b.index   # minuto sem amostra completado
    linhas = [json.loads(x) for x in open(tmp_path / "dt" / dia / "sinais_niveis.jsonl").read().splitlines()]
    sinais = [x for x in linhas if x["tipo"] == "sinal" and x["ativo"] == "WINFUT"]
    assert len(sinais) == 1 and sinais[0]["opera"] is True and sinais[0]["bloqueio"] is None and sinais[0]["tecnica"] == "fim do pregão (teste)"
    entradas = [x for x in linhas if x["tipo"] == "entrada" and x["ativo"] == "WINFUT"]
    assert len(entradas) == 1 and entradas[0]["lado"] == "C" and entradas[0]["contratos"] == 1      # a dose da regra: 1 contrato
    pos = r.estados["WINFUT"].posicao
    assert pos and pos.entrada == 209105.0 and pos.stop == 208605.0 and pos.tempo_max_s == 1500.0
    assert any(p["ativo"] == "WINFUT" for p in est["posicoes"]) and "regra do laboratório" in r.diario[-1]["texto"]
    assert json.loads(open(r.arq_estado).read())["labs_rodando"] == {"win_teste": "WINFUT"}       # a revisao da noite sabe que rodou
    # no mesmo minuto o motor nao e relido e o sinal nao se repete
    n = len(lidas)
    depois = agora + timedelta(seconds=2)
    r.ciclo(depois, retrato={"q": {"WDOFUT": _cotacao(5090.0, depois.timestamp()), "WINFUT": _cotacao_win(209110.0, depois.timestamp())}})
    linhas = [json.loads(x) for x in open(tmp_path / "dt" / dia / "sinais_niveis.jsonl").read().splitlines()]
    assert len([x for x in linhas if x["ativo"] == "WINFUT"]) == 2 and len([c for c in lidas[n:] if "dias=1" in c]) <= 1
    # o resultado do mini-indice entra no dia em reais (R$ 0,20 o ponto), como o de qualquer outro contrato
    realizado, aberto, _c = r.resultado()
    assert aberto == pytest.approx((209110.0 - 209105.0) * 0.20 - 2 * 0.30)


def test_regra_do_mini_indice_mede_a_barra_que_chega_atrasada(tmp_path, monkeypatch):
    """A barra do mini-indice que chega com o minuto ja passado (motor atrasado) e medida, nao vira entrada, e diz por que."""
    _regra_win(tmp_path, monkeypatch, minuto="17:35")
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch, modo={"hora_ultima_entrada": "18:10", "hora_zerar": "18:24"})
    dia = "2026-10-15"
    _historia_win(mt5 / "autopilot_historia_WINSN_M2610151.csv", _pregoes_ate(dia, 3), gravado=datetime(2026, 10, 15, 8, 52, tzinfo=BRT))
    serie = _serie_win(dia, ate="17:40")
    monkeypatch.setattr(rf, "ler_motor", lambda caminho, *a, **k: serie if "s=WINFUT" in caminho else None)
    r = rf.RoboFluxo(dia, saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 15, 17, 41, 3, tzinfo=BRT)
    r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5090.0, agora.timestamp()), "WINFUT": _cotacao_win(209100.0, agora.timestamp())}})
    sinal = [json.loads(x) for x in open(tmp_path / "dt" / dia / "sinais_niveis.jsonl").read().splitlines()][-1]
    assert sinal["ativo"] == "WINFUT" and sinal["opera"] is False and sinal["bloqueio"] == "barra das 17:35 chegou atrasada"
    assert r.estados["WINFUT"].posicao is None


def test_sinais_do_dia_so_contam_como_operado_o_que_entrou(tmp_path, monkeypatch):
    """Achado 43: o sinal das 9h36 de 15/10, barrado pela pausa do dado, aparecia na tela como OPERADO e com R$ de verdade."""
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    r = rf.RoboFluxo("2026-10-15", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    base = {"tipo": "sinal", "ativo": "WDOFUT", "tecnica": "nível e reação", "lado": "C", "entrada": 5060.5, "stop_pts": 4.0, "alvo_pts": 14.0}
    linhas = [dict(base, hora="09:30:00", opera=False, bloqueio="reservado ao dado das 9h30", quando="2026-10-15T09:30:00-03:00"),
              dict(base, hora="09:36:00", opera=True, bloqueio="pausa do dado", quando="2026-10-15T09:36:00-03:00"),
              dict(base, hora="09:48:00", opera=True, bloqueio=None, quando="2026-10-15T09:48:00-03:00"),
              {"tipo": "entrada", "ativo": "WDOFUT", "tecnica": "nível e reação", "lado": "C", "contratos": 2, "entrada": 5050.5, "hora": "09:48:00"},
              dict(base, hora="10:06:00", opera=True, bloqueio="posição aberta (nível e reação)", quando="2026-10-15T10:06:00-03:00")]
    (tmp_path / "dt" / "2026-10-15" / "sinais_niveis.jsonl").write_text("\n".join(json.dumps(x) for x in linhas) + "\n")
    s = {x["hora"]: x for x in r.sinais_hoje(datetime(2026, 10, 15, 10, 30, tzinfo=BRT))}
    assert (s["09:36:00"]["opera"], s["09:36:00"]["regra_opera"], s["09:36:00"]["bloqueio"]) == (False, True, "pausa do dado")
    assert (s["09:48:00"]["opera"], s["09:48:00"]["regra_opera"], s["09:48:00"]["bloqueio"]) == (True, True, None)
    assert (s["10:06:00"]["opera"], s["10:06:00"]["bloqueio"]) == (False, "posição aberta (nível e reação)")
    assert (s["09:30:00"]["opera"], s["09:30:00"]["regra_opera"], s["09:30:00"]["bloqueio"]) == (False, False, "reservado ao dado das 9h30")
    assert sum(1 for x in s.values() if x["opera"]) == 1                    # 4 sinais, 1 operado (o das 9h48)


def test_sinal_na_reserva_do_dado_diz_o_motivo(tmp_path, monkeypatch):
    """Achado 44: com o teste de nivel ligado, o sinal das 9h20 (reserva do dado, das 9h08 as 9h32) ficava 'so medindo' sem motivo, e a
    revisao contava a regra como desligada."""
    from quant.daytrade import historico as hist
    from quant.pesquisa import revisao as rv
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch, modo={"niveis_opera": True})
    r = rf.RoboFluxo("2026-10-15", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    leitura = {"pronto": True, "setup": "niveis", "tempo_min": 6, "fechamento": 5068.0, "barra": [5068.5, 5070.5, 5067.0, 5068.0],
               "niveis": [{"preco": 5070.0, "nome": "número redondo"}], "acima": 5070.0, "abaixo": None, "barras": 9000}
    ordens = [hist.Ordem("V", 4.0, parcial_pts=4.0, alvo_pts=16.0, nivel=5070.0, nome_nivel="número redondo")]
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): (leitura, ordens.pop() if ordens else None)})()
    agora = datetime(2026, 10, 15, 9, 20, 7, tzinfo=BRT)
    r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5068.0, agora.timestamp())}})
    sinal = [json.loads(x) for x in open(tmp_path / "dt" / "2026-10-15" / "sinais_niveis.jsonl").read().splitlines()][-1]
    assert (sinal["tipo"], sinal["opera"], sinal["bloqueio"]) == ("sinal", False, "reservado ao dado das 9h30")
    assert r.estados["WDOFUT"].posicao is None
    medida = next(x["texto"] for x in reversed(r.diario) if x["tipo"] == "medida")
    assert medida.startswith("Mini-dólar: só medindo, sem operar: nível e reação em número redondo (5.070,0); venderia a 5.067,5; ")
    assert medida.endswith("não entrou: reservado ao dado das 9h30.")      # o comeco continua no formato que a tela le
    assert rv.motivo_sem_entrada(sinal, [], [], {}, "2026-10-15") == ("reservado ao dado das 9h30", None)    # e nao "só medido"


def test_mac_dormindo_nao_vira_cegueira_do_metatrader(tmp_path, monkeypatch):
    """Achado 42: em 15/10 o Mac dormiu das 9h00 as 9h24 (tampa fechada, na bateria) e o robo anotou 'sem cotacao do MetaTrader'."""
    rf, r, _mt5 = _robo(tmp_path, monkeypatch, "2026-10-15")
    t = lambda h, m, s=0: datetime(2026, 10, 15, h, m, s, tzinfo=BRT)
    relogio = [t(9, 0).timestamp()]
    monkeypatch.setattr(rf.time, "time", lambda: relogio[0])
    r.vigia_em = relogio[0]
    r.cot = {"WDOFUT": {"preco": 5050.0, "ts_tique": t(8, 59, 50).timestamp()}}
    relogio[0] = t(9, 24, 30).timestamp()                                    # o processo ficou parado 24 minutos: o Mac dormia
    r._vigiar_feed(t(9, 24, 30))
    r._vigiar_cegueira(t(9, 24, 30))
    assert "o Mac estava dormindo" in r.diario[-1]["texto"] and "do MetaTrader desde" not in r.diario[-1]["texto"]
    relogio[0] = t(9, 24, 40).timestamp()
    r.cot["WDOFUT"]["ts_tique"] = relogio[0]
    r._vigiar_feed(t(9, 24, 40))
    r._vigiar_cegueira(t(9, 24, 40))
    assert r.cegueira == [["09:00", "09:24", 24, "mac_dormindo"]] and "não foi o MetaTrader" in r.diario[-1]["texto"]
    r._salvar()                                                              # religado no meio do pregao, le os 4 campos de volta
    assert rf.RoboFluxo("2026-10-15", saidas=[str(tmp_path / "q2.json")], pasta_mt5=str(_mt5)).cegueira == [["09:00", "09:24", 24, "mac_dormindo"]]


def test_pausa_do_dado_segue_o_horario_do_dado_americano(tmp_path, monkeypatch):
    """Achado 81: a pausa era 9h28-9h40 fixa; fora do horario de verao dos EUA (a partir de 02/11/2026) o dado sai as 10h30."""
    from datetime import date
    from quant.daytrade import barras as br
    from quant.pesquisa import revisao as rv
    assert br.pausa_do_dado(date(2026, 10, 15)) == ("09:28", "09:40")
    assert br.pausa_do_dado(date(2026, 11, 3)) == ("10:28", "10:40")         # EUA fora do horario de verao desde 01/11/2026
    assert br.pausa_do_dado(date(2027, 3, 15)) == ("09:28", "09:40")
    rf, r, _mt5 = _robo(tmp_path, monkeypatch, "2026-11-03")
    assert r.p.pausa_dado == ("10:28", "10:40") and ef.hora_do_dado(r.p) == "10h30"
    s = {"tecnica": "nível e reação", "lado": "V", "nivel": 5040.0, "nome_nivel": "abertura", "stop_pts": 4.0}
    assert r._bloqueio("WDOFUT", datetime(2026, 11, 3, 9, 30, tzinfo=BRT), s) is None
    assert r._bloqueio("WDOFUT", datetime(2026, 11, 3, 10, 31, tzinfo=BRT), s) == "pausa do dado"
    textos = " ".join(rf.regras_niveis(r.p) + ef.regras_em_texto(r.p))
    assert "10:28 a 10:40 (dado das 10h30)" in textos and "entre 10:28 e 10:40 (dado das 10h30)" in textos and "dado das 9h30)" not in textos
    m = lambda dia, h: rv.motivo_sem_entrada({"tecnica": "nível e reação", "hora": h, "opera": True}, [], [], {}, dia)[0]
    assert m("2026-11-03", "10:31:00") == "pausa do dado" and m("2026-11-03", "09:30:00") != "pausa do dado"
    assert m("2026-10-14", "09:30:00") == "pausa do dado"                    # no horario de verao dos EUA continua 9h28-9h40


def test_ciclo_de_1_segundo_vai_ate_a_hora_de_zerar(tmp_path, monkeypatch):
    """Achado 45: depois das 17h25 o robo dormia 10 s por ciclo, mas desde 13/10 entra ate 18h10 e zera as 18h24."""
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch, modo={"hora_ultima_entrada": "18:10", "hora_zerar": "18:24"})
    original = rf.RoboFluxo
    monkeypatch.setattr(rf, "RoboFluxo", lambda hoje, **kw: original(hoje, pasta_mt5=str(mt5), **kw))

    class Para(Exception):
        pass

    pedidos = []

    def dorme(s):
        pedidos.append(s)
        raise Para()

    monkeypatch.setattr(rf.time, "sleep", dorme)
    for k, (hora, modo, esperado) in enumerate((((17, 40), None, 1.0), ((18, 26), None, 10.0), ((17, 40), {}, 10.0))):
        if modo is not None:                                                 # sem as chaves da janela: o corte antigo das 17h25
            (tmp_path / "modo_robo.json").write_text(json.dumps(modo))
        monkeypatch.setattr(rf, "DIR_DT", str(tmp_path / f"dt{k}"))         # a trava de um robo por maquina e por pasta
        monkeypatch.setattr(rf, "agora_brt", lambda h=hora: datetime(2026, 10, 15, *h, tzinfo=BRT))
        with pytest.raises(Para):
            rf.rodar(saidas=[str(tmp_path / f"q{k}.json")], setup="niveis")
        assert pedidos[-1] == esperado, (hora, modo, pedidos)


def test_textos_do_climax_saem_com_virgula(tmp_path, monkeypatch):
    """Achado 83: 'volume de 0.6 vezes a média' na tela."""
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    r = rf.RoboFluxo("2026-10-15", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.leitura_pc["WDOFUT"] = {"pronto": True, "setup": "niveis", "tempo_min": 6, "fechamento": 5060.0,
                              "niveis": [{"preco": 5070.0, "nome": "número redondo"}], "acima": 5070.0, "abaixo": None}
    r.leitura_climax["WDOFUT"] = {"pronto": True, "minuto": "09:50", "tranco": 2.0, "volume_x": 0.6, "pede_tranco": 5.0, "pede_volume_x": 2.5}
    r.cot = {"WDOFUT": {"preco": 5060.0}}
    frase = next(f for f in r._espera_niveis("WDOFUT", datetime(2026, 10, 15, 9, 51, tzinfo=BRT)) if f.startswith("Climax"))
    assert "andou 2,0 pontos com volume de 0,6 vezes a média" in frase and "5,0 pontos e 2,5 vezes ou mais" in frase


def test_niveis_de_ontem_vem_do_boletim_oficial_e_nao_das_barras_cortadas(tmp_path, monkeypatch):
    """Achado 41: em 14/10 o robo ficou cego das 11h51 ao fim do pregao e o 'fechamento de ontem' de 15/10 saiu 5.059,0 (a barra das
    11h50); o oficial do WDOX26 foi 5.066,0."""
    import numpy as np
    import pandas as pd
    from quant.daytrade import barras as br, estrategias_hist as eh
    idx = pd.date_range("2026-10-14 09:00", "2026-10-14 11:50", freq="1min").append(pd.date_range("2026-10-15 09:00", "2026-10-15 10:00", freq="1min"))
    c = np.r_[np.linspace(5040.0, 5059.0, 171), np.full(61, 5085.0)]
    m1 = pd.DataFrame({"o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "n": 0.0, "v": 0.0}, index=idx)
    assert br.falha_de_ontem(m1, "2026-10-15") == "as barras de 14/10 param às 11:50"
    futuros = tmp_path / "futuros.json"
    futuros.write_text(json.dumps({"data": "2026-10-14", "familias": [{"contratos": [
        {"s": "WDOX26", "ajuste": 5049.791, "ajuste_ant": 5037.501, "ult": 5066.0, "max": 5071.0, "min": 5033.5}]}]}))
    from quant.daytrade import robo_fluxo as rf0
    of = rf0.extremos_oficiais({"WDOFUT": "WDOX26"}, "2026-10-15", arquivo=str(futuros))
    assert of == {"WDOFUT": [(5071.0, "máxima de ontem"), (5033.5, "mínima de ontem"), (5066.0, "fechamento de ontem")]}
    assert rf0.extremos_oficiais({"WDOFUT": "WDOX26"}, "2026-10-14", arquivo=str(futuros)) == {}    # de noite o arquivo ja e o de hoje
    assert rf0.extremos_oficiais({"WDOFUT": "WDOX26"}, "2026-10-16", arquivo=str(futuros)) == {}    # dois pregoes atras nao e "ontem"
    assert rf0.extremos_oficiais({"WDOFUT": "WDOX26"}, "2026-10-13", arquivo=str(futuros)) == {}
    e = eh.NivelReacao(**rf0.NIVEIS)
    e.preparar(m1)
    i = len(m1) - 1
    calculado = e.niveis_com_nome(i, 5085.0)
    assert [v for v, n in calculado.items() if n == "fechamento de ontem"] == [5059.0]            # o defeito: a barra das 11h50
    e.extras = ((5049.791, "ajuste de ontem"), *of["WDOFUT"])
    oficial = e.niveis_com_nome(i, 5085.0)
    assert [v for v, n in oficial.items() if n == "fechamento de ontem"] == [5066.0]
    assert [v for v, n in oficial.items() if n == "máxima de ontem"] == [5071.0] and [v for v, n in oficial.items() if n == "mínima de ontem"] == [5033.5]
    # no robo: o oficial vai como nivel, e a tela avisa que as barras de ontem estao incompletas
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch)
    monkeypatch.setattr(rf, "ARQ_FUTUROS_B3", str(futuros))
    r = rf.RoboFluxo("2026-10-15", saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.codigos = {"WDOFUT": "WDOX26"}
    r.barras["WDOFUT"].df, r.barras["WDOFUT"].ultimo_minuto = m1, m1.index[-1]
    pedidos = []
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): pedidos.append(list(extras)) or ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 15, 10, 1, 3, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5085.0, agora.timestamp())}})
    assert (5066.0, "fechamento de ontem") in pedidos[-1] and (5049.791, "ajuste de ontem") in pedidos[-1]
    aviso = next(a for a in est["avisos"] if a.startswith("Níveis de ontem incompletos"))
    assert "as barras de 14/10 param às 11:50" in aviso and "boletim oficial da B3" in aviso


# ── revisao de 15/10/2026 do achado 10: a vespera do mini-indice (a regra decide pela ultima barra do pregao anterior) ──
def _regra_win_real(tmp_path, monkeypatch):
    """O registro com a regra DE VERDADE do mini-indice (quant/pesquisa/regras/win_fim_do_dia.py, regra_adaptativa), como em setups.json."""
    from quant.daytrade import regras_lab
    reg = tmp_path / "setups.json"
    reg.write_text(json.dumps({"regras": [{"nome": "win_fim_do_dia_adaptativa", "titulo": "fim do pregão (mini-índice, lado que vem dando certo)",
                                           "arquivo": os.path.join(regras_lab.RAIZ, "quant", "pesquisa", "regras", "win_fim_do_dia.py"),
                                           "funcao": "regra_adaptativa", "ativo": "WINFUT", "estado": "opera", "contratos": 1, "barras": 60000,
                                           "janela": ["17:30", "18:10"], "saida": {"stop": 500, "alvo": None, "tempo": 25}}]}))
    monkeypatch.setattr(regras_lab, "ARQ_SETUPS", str(reg))


def _serie_win_subindo(dia, ate):
    """/vivo/intradia do mini-indice subindo 2 pontos por minuto desde as 9h00 (o dia e de alta: a regra compra)."""
    ini = datetime.fromisoformat(f"{dia}T09:00:00-03:00")
    n = int((datetime.fromisoformat(f"{dia}T{ate}:00-03:00") - ini).total_seconds() // 60) + 1
    return {"s": "WINFUT", "codigo": "WINZ26", "dia": dia, "t": [(ini + timedelta(minutes=k)).timestamp() + 30 for k in range(n)],
            "p": [209000.0 + 2 * k for k in range(n)]}


def _sinais_win(tmp_path, dia):
    arq = tmp_path / "dt" / dia / "sinais_niveis.jsonl"
    return [x for x in (json.loads(y) for y in arq.read_text().splitlines()) if x["ativo"] == "WINFUT" and x["tipo"] == "sinal"] if arq.exists() else []


def test_historico_do_servidor_vale_o_arquivo_do_dia_seguinte_com_mais_barras(tmp_path):
    """De noite o servidor ainda guarda o leilao de fechamento numa barra das 18h31 (no dia seguinte ela vai para a das 18h24); e o primeiro
    pedido da manha as vezes vem cortado (08h51 de 16/10/2026: parava as 15h55 de 15/10)."""
    from quant.daytrade import barras as br
    dias = _pregoes_ate("2026-10-16", 3)                                      # 13/10, 14/10 e 15/10
    noite = _historia_win(tmp_path / "autopilot_historia_WINSN_M26101520.csv", dias, cortes={dias[-1]: "18:31"},
                          gravado=datetime(2026, 10, 15, 20, 40, tzinfo=BRT))
    cortado = _historia_win(tmp_path / "autopilot_historia_WINSN_M2610160.csv", dias, cortes={dias[-1]: "15:55"},
                            gravado=datetime(2026, 10, 16, 8, 51, tzinfo=BRT))
    inteiro = _historia_win(tmp_path / "autopilot_historia_WINSN_M2610161.csv", dias, gravado=datetime(2026, 10, 16, 8, 50, tzinfo=BRT))
    (tmp_path / "autopilot_historia_WINSN_M2610162.csv").write_text("#HISTORIA;1;WIN$N;M2610162;10\nhora_servidor;a\n2026.10.15 09:00;1;1;1;1;1;1\n")
    _historia_win(tmp_path / "autopilot_historia_WDOSN_M2610161.csv", dias)            # outro simbolo
    arqs = br.arquivos_de_historia("WINFUT", str(tmp_path), desde_ts=datetime(2026, 10, 15, tzinfo=BRT).timestamp())
    assert [os.path.basename(c) for _m, c in arqs] == [cortado.name, inteiro.name, noite.name]   # o sem #FIM (ainda gravando) fica de fora
    h = br.historia_do_servidor(arqs, BRT)
    assert h[h.index.normalize() == "2026-10-15"].index[-1].strftime("%H:%M") == "18:24"
    so_noite = br.historia_do_servidor([(m, c) for m, c in arqs if c.endswith(noite.name)], BRT)
    assert so_noite.index[-1].strftime("%H:%M") == "18:31"                   # sem arquivo do dia seguinte, vale o que ha


def test_falha_da_vespera_confere_o_pregao_anterior_inteiro():
    import pandas as pd
    from quant.daytrade import barras as br
    dias = _pregoes_ate("2026-10-15", 6)

    def barras(cortes=None, buraco=None, sem=()):
        idx = []
        for d in dias:
            if d in sem:
                continue
            r = pd.date_range(f"{d} 09:00", f"{d} {(cortes or {}).get(d, '18:24')}", freq="1min")
            if buraco and d == buraco[0]:
                r = r[(r < pd.Timestamp(f"{d} {buraco[1]}")) | (r > pd.Timestamp(f"{d} {buraco[2]}"))]
            idx.extend(r)
        idx = pd.DatetimeIndex(idx)
        return pd.DataFrame({"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "n": 0.0, "v": 0.0}, index=idx)

    ontem = dias[-1]
    assert br.falha_da_vespera(barras(), "2026-10-15", ontem) is None
    assert br.falha_da_vespera(barras(sem=(ontem,)), "2026-10-15", ontem) == "faltam as barras do pregão de 14/10 (as últimas são de 13/10)"
    assert br.falha_da_vespera(barras(cortes={ontem: "15:54"}), "2026-10-15", ontem) == "as barras de 14/10 terminam às 15:54, e o pregão termina às 18:24"
    assert br.falha_da_vespera(barras(cortes={ontem: "18:28"}), "2026-10-15", ontem) == "as barras de 14/10 terminam às 18:28, e o pregão termina às 18:24"
    assert br.falha_da_vespera(barras(cortes={ontem: "18:31"}), "2026-10-15", ontem) == "as barras de 14/10 terminam às 18:31, e o pregão termina às 18:24"
    assert br.falha_da_vespera(barras(buraco=(ontem, "12:00", "12:40")), "2026-10-15", ontem) == "as barras de 14/10 têm um buraco das 11:59 às 12:41"
    # a B3 mudou o horario: o pregao de antes ja terminou as 18:29, entao 18:29 ontem serve
    assert br.falha_da_vespera(barras(cortes={dias[-2]: "18:29", ontem: "18:29"}), "2026-10-15", ontem) is None
    assert br.falha_da_vespera(barras().iloc[:0], "2026-10-15", ontem) == "sem barras do pregão de 14/10"


def test_pedido_de_historico_nao_atropela_o_pedido_de_outro(tmp_path):
    from quant.daytrade import barras as br
    pedido = tmp_path / "autopilot_historia.txt"
    pedido.write_text("WIN$N;2610161;49340\n")                              # a prova viva pediu e o leitor ainda nao entregou
    assert br.pedir_historia("WINFUT", str(tmp_path), 261015700, 62000) is None and pedido.read_text() == "WIN$N;2610161;49340\n"
    (tmp_path / "autopilot_historia_WINSN_M2610161.csv").write_text("x")      # entregou: agora pode
    assert br.pedir_historia("WINFUT", str(tmp_path), 261015700, 62000).endswith("autopilot_historia_WINSN_M261015700.csv")
    assert pedido.read_text() == "WIN$N;261015700;62000\n"
    pedido.write_text("WDO$N;2610169;100\n")
    velho = datetime(2026, 10, 15, 8, 0, tzinfo=BRT).timestamp()
    os.utime(pedido, (velho, velho))                                         # pedido abandonado (o leitor nunca respondeu): pode
    assert br.pedir_historia("WINFUT", str(tmp_path), 261015701, 62000) and pedido.read_text() == "WIN$N;261015701;62000\n"


def test_regra_real_do_mini_indice_decide_pelo_fim_do_pregao_anterior_do_servidor(tmp_path, monkeypatch):
    """A regra de verdade decide 31 minutos antes da ultima barra do pregao anterior. As barras do proprio robo de 14/10 iam ate as 18h28
    (amostras do motor depois do fechamento) e o arquivo M1 do MetaTrader parou em 13/10 (18h31): sem o servidor, a regra decidiria as 17h57,
    ou no minuto de 13/10. Com o historico que a prova viva pediu de manha, a vespera termina as 18h24 e a regra decide as 17h53."""
    import pandas as pd
    _regra_win_real(tmp_path, monkeypatch)
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch, modo={"hora_ultima_entrada": "18:10", "hora_zerar": "18:24"})
    dia = "2026-10-15"
    dias = _pregoes_ate(dia, 50)
    _historia_win(mt5 / "autopilot_historia_WINSN_M1.csv", dias[:-1], cortes={dias[-2]: "18:31"}, gravado=datetime(2026, 10, 13, 19, 30, tzinfo=BRT))
    (tmp_path / "dt").mkdir(exist_ok=True)
    (tmp_path / "dt" / "m1_WINFUT.csv").write_text("".join(f"{t:%Y-%m-%d %H:%M:%S};{205000 + k};{205000 + k};{205000 + k};{205000 + k};0.0\n"
                                                           for k, t in enumerate(pd.date_range(f"{dias[-1]} 09:00", f"{dias[-1]} 18:28", freq="1min"))))
    _historia_win(mt5 / "autopilot_historia_WINSN_M2610151.csv", dias, gravado=datetime(2026, 10, 15, 8, 52, tzinfo=BRT))
    serie = _serie_win_subindo(dia, "17:53")
    monkeypatch.setattr(rf, "ler_motor", lambda caminho, *a, **k: serie if "s=WINFUT" in caminho else None)
    r = rf.RoboFluxo(dia, saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()
    agora = datetime(2026, 10, 15, 17, 54, 3, tzinfo=BRT)
    est = r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5090.0, agora.timestamp()), "WINFUT": _cotacao_win(210070.0, agora.timestamp())}})
    assert r.vespera == {"WINFUT": None}
    b = r.barras["WINFUT"].df
    assert b[b.index.normalize() == pd.Timestamp(dias[-1])].index[-1].strftime("%H:%M") == "18:24"
    sinais = _sinais_win(tmp_path, dia)
    assert [(x["hora"][:5], x["lado"], x["opera"], x["bloqueio"]) for x in sinais] == [("17:54", "C", True, None)]
    assert sinais[0]["medidas"]["regra"] == "win_fim_do_dia_adaptativa" and r.estados["WINFUT"].posicao is not None
    assert r.barras["WINFUT"].df.loc[pd.Timestamp(f"{dia} 17:53"), "c"] == 209000.0 + 2 * 533       # o sinal saiu na barra das 17h53
    win = next(i for i in est["instrumentos"] if i["ativo"] == "WINFUT")
    assert (win["tick"], win["valor_ponto"], win["so_laboratorio"], win["vespera"]) == (5.0, 0.20, True, None) and win["posicao"]["lado"] == "C"
    assert est["instrumentos"][0]["ativo"] == "WDOFUT"                          # o mini-dolar continua o primeiro
    assert not (mt5 / "autopilot_historia.txt").exists()                         # com a vespera completa, nada e pedido ao MetaTrader


def test_vespera_cortada_deixa_a_regra_so_medida_pede_ao_metatrader_e_volta_quando_chega(tmp_path, monkeypatch):
    """Sem o historico do servidor e com as barras do robo de 14/10 parando as 18h10, a regra de verdade decidiria as 17h39 (o minuto errado)
    e operaria. Agora: o sinal fica so medido com o motivo, a tela avisa, o robo pede o historico ao MetaTrader e, quando ele chega, a regra
    volta a operar no minuto certo (17h53)."""
    import pandas as pd
    _regra_win_real(tmp_path, monkeypatch)
    rf, mt5 = _robo_niveis(tmp_path, monkeypatch, modo={"hora_ultima_entrada": "18:10", "hora_zerar": "18:24"})
    dia = "2026-10-15"
    dias = _pregoes_ate(dia, 50)
    _historia_win(mt5 / "autopilot_historia_WINSN_M1.csv", dias[:-1], gravado=datetime(2026, 10, 13, 19, 30, tzinfo=BRT))
    (tmp_path / "dt").mkdir(exist_ok=True)
    (tmp_path / "dt" / "m1_WINFUT.csv").write_text("".join(f"{t:%Y-%m-%d %H:%M:%S};{205000 + k};{205000 + k};{205000 + k};{205000 + k};0.0\n"
                                                           for k, t in enumerate(pd.date_range(f"{dias[-1]} 09:00", f"{dias[-1]} 18:10", freq="1min"))))
    serie = {"v": _serie_win_subindo(dia, "17:39")}
    monkeypatch.setattr(rf, "ler_motor", lambda caminho, *a, **k: serie["v"] if "s=WINFUT" in caminho else None)
    r = rf.RoboFluxo(dia, saidas=[str(tmp_path / "quant.json")], pasta_mt5=str(mt5), setup="niveis")
    r.sinais_pc["WDOFUT"] = type("S", (), {"atualizar": lambda self, df, extras=(): ({"pronto": False, "motivo": "teste"}, None)})()

    def ciclo(h, m, sg, preco):
        agora = datetime(2026, 10, 15, h, m, sg, tzinfo=BRT)
        return r.ciclo(agora, retrato={"q": {"WDOFUT": _cotacao(5090.0, agora.timestamp()), "WINFUT": _cotacao_win(preco, agora.timestamp())}})

    est = ciclo(17, 40, 3, 210040.0)
    falha = "as barras de 14/10 terminam às 18:10, e o pregão termina às 18:24"
    assert r.vespera == {"WINFUT": falha}
    sinais = _sinais_win(tmp_path, dia)
    assert [(x["hora"][:5], x["opera"], x["bloqueio"]) for x in sinais] == [("17:40", False, "véspera incompleta: " + falha)]   # a barra das 17h39
    assert r.estados["WINFUT"].posicao is None
    assert any(a.startswith("Mini-índice: véspera incompleta nas barras (" + falha) for a in est["avisos"])
    assert json.loads(open(r.arq_estado).read())["vespera"] == {"WINFUT": falha}
    assert (mt5 / "autopilot_historia.txt").read_text() == "WIN$N;261015700;62000\n"     # pediu o historico ao MetaTrader, sem esperar
    # o leitor do MetaTrader entrega o pedido; no minuto seguinte o robo junta e a vespera passa a servir
    _historia_win(mt5 / "autopilot_historia_WINSN_M261015700.csv", dias, gravado=datetime(2026, 10, 15, 17, 41, tzinfo=BRT))
    serie["v"] = _serie_win_subindo(dia, "17:53")
    ciclo(17, 54, 0, 210070.0)
    assert r.vespera == {"WINFUT": None} and any("véspera ficou completa" in x["texto"] for x in r.diario)
    sinais = _sinais_win(tmp_path, dia)
    assert [(x["hora"][:5], x["opera"], x["bloqueio"]) for x in sinais][-1] == ("17:54", True, None) and r.estados["WINFUT"].posicao is not None

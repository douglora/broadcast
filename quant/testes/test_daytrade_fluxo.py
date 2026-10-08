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
    assert "contra um tranco de 5 pontos com volume de 4.5x" in r.diario[-1]["texto"]
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

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
    # o mini-indice nao pede (a fonte dele nao separa robo de instituicao)
    assert ef.ATIVOS["WINFUT"].sem_lote_de_robo is False and ef.ATIVOS["WDOFUT"].fonte_fluxo == "DOL"


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


def test_rompimento_depois_de_tres_batidas_e_saida_se_nao_anda():
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
    # compra a mercado em 5.041,5; stop de 4,5 pontos = 5.037,0 (o dele: comprou 43,5 com stop em 39)
    assert ev[0]["tecnica"] == "rompimento" and ev[0]["medidas"]["testes"] == 3
    assert (pos.entrada, pos.stop) == (5041.5, 5037.0) and e.extremos["max"]["testes"] == 1
    # 2 minutos depois o preco nao andou 1 ponto: sai a mercado em 5.041,0 = -0,5 x 10 x 2 - 4,80 = -14,80
    ev = ef.passo(e, ts + 121, "11:03:01", 5041.5, f, niveis, p, lote=2)
    assert ev[0]["motivo"] == "não andou" and ev[0]["resultado"] == pytest.approx(-14.80)
    # com 2 batidas so, o rompimento nao vira entrada, e o extremo novo recomeca a contagem
    e2, g = ef.EstadoF("WDOFUT"), fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(g, T0)
    niveis, ts = _ate_o_rompimento(e2, g, p, batidas=2)
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
    assert tenta(hora="09:30:00") == [] and tenta(hora="09:04:00") == []             # dado das 9h30; primeiros minutos
    assert tenta(hora="15:45:00") == [] and tenta(hora="15:44:59")[0]["tipo"] == "entrada"
    assert ef.passo(ef.EstadoF("WDOFUT"), 1000.0, "10:15:00", 5031.0, _cenario_defesa(), AJUSTE, p, lote=2, pode_entrar=False) == []
    # stop: atras do nivel, minimo de 2, teto de 5 (6 em dia rapido, com a folga dobrada)
    assert ef.calcular_stop("WDOFUT", "C", 5031.5, 5030.0, "defesa", False) == 5029.0      # 1 ponto atras do nivel
    assert ef.calcular_stop("WDOFUT", "V", 5029.5, 5030.0, "perda de nível", False) == 5031.5   # 1,5 viraria 2 (minimo)
    assert ef.calcular_stop("WDOFUT", "C", 5036.0, 5030.0, "defesa", False) == 5031.0      # 7 pontos viram 5 (teto)
    assert ef.calcular_stop("WDOFUT", "C", 5031.5, 5030.0, "defesa", True) == 5028.0       # dia rapido: 2 pontos atras
    assert ef.calcular_stop("WDOFUT", "C", 5036.0, 5030.0, "defesa", True) == 5030.0       # teto de 6
    assert ef.calcular_stop("WINFUT", "C", 207300.0, 207200.0, "defesa", False) == 207140.0   # 60 atras do nivel = 160
    # niveis: a variacao de 1% entra como nivel (5.030 x 1,01 = 5.080,3; x 0,99 = 4.979,7)
    de = dict(ef.niveis_do_dia({"ajuste": 5030.0, "maxima": 5040.0}, p))
    assert de["1% acima do ajuste"] == pytest.approx(5080.3) and de["1% abaixo do ajuste"] == pytest.approx(4979.7)
    assert de["máxima do dia"] == 5040.0 and "mínima do dia" not in de


def test_escada_de_lote_e_fim_do_dia():
    p = ef.ParamFluxo()
    # R$ 1.000 de lucro acumulado paga um degrau de 2 contratos; devolveu o lucro, volta; teto de 8
    assert [ef.lote_do_dia(x, p) for x in (-500.0, 0.0, 999.0, 1000.0, 2500.0, 50_000.0)] == [2, 2, 2, 4, 6, 8]
    e = ef.EstadoF("WINFUT")
    e.posicao = ef.PosicaoF("C", 2, 206000.0, 205880.0, "15:00:00", "defesa", 205950.0, "abertura", 2, False, 206000.0)
    ev = ef.passo(e, 5000.0, "16:30:00", 206100.0, None, [], p, lote=2)
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
    from quant.daytrade import robo_fluxo as rf
    monkeypatch.setattr(rf, "DIR_DT", str(tmp_path / "dt"))
    monkeypatch.setattr(rf, "ARQ_SERIE", str(tmp_path / "dt" / "serie_fluxo.json"))
    monkeypatch.setattr(rf, "ler_motor", lambda *a, **k: None)
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

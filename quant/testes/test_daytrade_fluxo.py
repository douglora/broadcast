"""
Leitura de fluxo e regra versao 1 do robo de day trade: fitas escritas a mao, contas no comentario.
"""
import os

import pytest

from quant.daytrade import estrategia_fluxo as ef
from quant.daytrade import fluxo as fx

T0 = 1_791_470_000          # um segundo qualquer do pregao (hora do servidor)


def _linha(seg, preco, compra, venda, simbolo="WDOX26", maior_c=None, maior_v=None):
    return (f"F;{simbolo};{seg};{preco};{compra};{venda};0;{max(1, int((compra + venda) // 5))};"
            f"{maior_c if maior_c is not None else compra};{maior_v if maior_v is not None else venda};300")


def _fita_de_fundo(fita, ate, janelas=20, volume=200):
    """`janelas` janelas de 30 s, cada uma com `volume` agredido (metade de cada lado), longe do nivel."""
    for k in range(janelas, 0, -1):
        fita.acrescentar(fx.linha_da_fita(_linha(ate - 30 * k - 100, 5035.0, volume / 2, volume / 2)))


def test_linha_e_livro():
    x = fx.linha_da_fita("F;WDOX26;1791470000;5030.500;120;80;0;14;50;30;250")
    assert (x["preco"], x["compra"], x["venda"], x["negocios"], x["maior_compra"]) == (5030.5, 120.0, 80.0, 14, 50.0)
    assert fx.linha_da_fita("lixo") is None and fx.linha_da_fita("F;WDOX26;1;0;1;1;0;1;1;1") is None
    livro = fx.ler_livro("#LIVRO;1;2026.10.08 12:00:00;1\nL;WDOX26;C;5030.0;45;5029.5;120;V;5030.5;30;5031.0;200\n#FIM\n")
    assert livro["WDOX26"]["compra"] == [(5030.0, 45.0), (5029.5, 120.0)]
    assert livro["WDOX26"]["venda"][0] == (5030.5, 30.0)
    # foto pela metade (sem #FIM) nao vale
    assert fx.ler_livro("#LIVRO;1;x;1\nL;WDOX26;C;5030.0;45;V;5030.5;30\n") == {}


def test_agressao_saldo_e_volume_tipico():
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)
    f.acrescentar(fx.linha_da_fita(_linha(T0 - 5, 5031.0, 80, 20, maior_c=40)))
    f.acrescentar(fx.linha_da_fita(_linha(T0, 5031.5, 60, 40)))
    a = f.agressao(15)
    # 80 + 60 = 140 de compra; 20 + 40 = 60 de venda; saldo +80; 70% de compra
    assert (a["compra"], a["venda"], a["saldo"]) == (140.0, 60.0, 80.0) and a["fracao_compra"] == pytest.approx(0.7)
    assert a["maior_compra"] == 60.0 and (a["minimo"], a["maximo"], a["ultimo"]) == (5031.0, 5031.5, 5031.5)
    assert f.volume_tipico(30) == 200.0            # a mediana das janelas de fundo
    assert fx.Fita("WDOX26", 0.5).volume_tipico(30) is None


def test_absorcao_no_suporte():
    f = fx.Fita("WDOX26", 0.5)
    # 6 segundos de venda agredindo em 5.030,0 e 5.030,5 (400 no total) e o preco nunca abaixo de 5.030,0
    for k, (preco, venda) in enumerate([(5030.5, 60), (5030.0, 80), (5030.0, 70), (5030.5, 60), (5030.0, 70), (5030.0, 60)]):
        f.acrescentar(fx.linha_da_fita(_linha(T0 - 60 + 5 * k, preco, 10, venda)))
    ab = f.absorcao(5030.0, "compra", 90)
    assert ab["agredido"] == 400.0 and ab["contra"] == 60.0 and ab["toques"] == 6 and ab["furou"] is False
    # um negocio a 5.029,5 dentro da janela: o suporte foi furado
    f.acrescentar(fx.linha_da_fita(_linha(T0 - 10, 5029.5, 0, 30)))
    assert f.absorcao(5030.0, "compra", 90)["furou"] is True


def _cenario_defesa():
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)                          # tipico = 200 por janela de 30 s
    for k, (preco, venda) in enumerate([(5030.5, 60), (5030.0, 80), (5030.0, 70), (5030.5, 60), (5030.0, 70), (5030.0, 60)]):
        f.acrescentar(fx.linha_da_fita(_linha(T0 - 70 + 8 * k, preco, 10, venda)))     # 400 de venda contra o nivel
    f.acrescentar(fx.linha_da_fita(_linha(T0 - 8, 5030.5, 50, 10)))
    f.acrescentar(fx.linha_da_fita(_linha(T0 - 2, 5031.0, 70, 20)))                    # compradores assumem: 120 x 30 em 15 s
    return f


def test_defesa_de_suporte_vira_compra_e_e_conduzida_como_ele_faz():
    p = ef.ParamFluxo()
    f = _cenario_defesa()
    niveis = [("ajuste de ontem", 5030.0)]
    s = ef.ler_fluxo("WDOFUT", f, 5031.0, niveis, p)
    # 400 agredidos no nivel >= 1,5 x 200; nao furou; 6 toques; 120 / 150 = 80% de compra nos ultimos 15 s
    assert s and s["tecnica"] == "defesa" and s["lado"] == "C" and s["medidas"]["fracao_a_favor"] == pytest.approx(0.8)
    e = ef.EstadoF("WDOFUT")
    ev = ef.passo(e, 1000.0, "10:15:00", 5031.0, f, niveis, p, lote=2)
    pos = e.posicao
    # entrada a mercado 5.031,5; stop = o menor entre "atras do nivel" (5.029,0) e 3 pontos (5.028,5)
    assert ev[0]["tipo"] == "entrada" and (pos.entrada, pos.stop, pos.contratos) == (5031.5, 5028.5, 2)
    # +2,5 pontos: parcial de 1 contrato a 5.034,0 = 2,5 x 10 x 1 - 2,40 = 22,60; stop vai para a entrada
    ev = ef.passo(e, 1060.0, "10:16:00", 5034.0, f, niveis, p, lote=2)
    assert ev[0]["tipo"] == "parcial" and ev[0]["contratos"] == 1 and ev[0]["resultado"] == pytest.approx(22.60)
    assert e.posicao.contratos == 1 and e.posicao.stop == 5031.5 and e.posicao.parcial_feita
    # preco a 5.036,0: stop movel 3 pontos atras = 5.033,0
    assert ef.passo(e, 1100.0, "10:17:00", 5036.0, f, niveis, p, lote=2) == [] and e.posicao.stop == 5033.0
    # volta a 5.033,0: sai a mercado em 5.032,5 = +1,0 ponto x 10 x 1 - 2,40 = 7,60
    ev = ef.passo(e, 1150.0, "10:18:00", 5033.0, f, niveis, p, lote=2)
    assert ev[0]["tipo"] == "saida" and ev[0]["motivo"] == "stop móvel" and ev[0]["saida"] == 5032.5
    assert ev[0]["resultado"] == pytest.approx(7.60) and e.posicao is None


def test_sem_defesa_nao_entra():
    p = ef.ParamFluxo()
    niveis = [("ajuste de ontem", 5030.0)]
    # pouca agressao contra o nivel (100 < 1,5 x 200): nao e defesa
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)
    for k in range(6):
        f.acrescentar(fx.linha_da_fita(_linha(T0 - 70 + 8 * k, 5030.0, 5, 16)))
    f.acrescentar(fx.linha_da_fita(_linha(T0 - 2, 5031.0, 70, 20)))
    assert ef.ler_fluxo("WDOFUT", f, 5031.0, niveis, p) is None
    # defesa de verdade, mas o preco ja fugiu 8 ticks: nao persegue
    assert ef.ler_fluxo("WDOFUT", _cenario_defesa(), 5034.0, niveis, p) is None
    # defesa, mas quem agride agora e o vendedor: nao confirma
    g = _cenario_defesa()
    g.acrescentar(fx.linha_da_fita(_linha(T0, 5031.0, 20, 300)))
    assert ef.ler_fluxo("WDOFUT", g, 5031.0, niveis, p) is None


def test_perda_de_nivel_vira_venda():
    p = ef.ParamFluxo()
    niveis = [("ajuste de ontem", 5030.0)]
    e = ef.EstadoF("WDOFUT")
    f = fx.Fita("WDOX26", 0.5)
    _fita_de_fundo(f, T0)
    f.acrescentar(fx.linha_da_fita(_linha(T0 - 40, 5031.5, 30, 30)))
    assert ef.passo(e, 1000.0, "11:00:00", 5031.5, f, niveis, p, lote=2) == []       # preco acima do ajuste: so anota o lado
    assert e.lado_dos_niveis["ajuste de ontem"] == "acima"
    # o preco perde o ajuste com venda agredindo: 160 de venda x 40 de compra em 15 s (80%), total 200 >= metade do tipico
    f.acrescentar(fx.linha_da_fita(_linha(T0 - 6, 5029.5, 20, 80)))
    f.acrescentar(fx.linha_da_fita(_linha(T0 - 1, 5029.0, 20, 80)))
    ev = ef.passo(e, 1030.0, "11:00:30", 5029.0, f, niveis, p, lote=2)
    pos = e.posicao
    # vende a mercado em 5.028,5; stop = o maior entre "atras do nivel" (5.031,0) e 3 pontos (5.031,5)
    assert ev[0]["tecnica"] == "perda de nível" and (pos.lado, pos.entrada, pos.stop) == ("V", 5028.5, 5031.5)
    # stop cheio: preco a 5.031,5 -> recompra a 5.032,0 = -3,5 pontos x 10 x 2 - 4,80 = -74,80
    ev = ef.passo(e, 1090.0, "11:01:30", 5031.5, f, niveis, p, lote=2)
    assert ev[0]["motivo"] == "stop" and ev[0]["resultado"] == pytest.approx(-74.80)


def test_escada_de_lote_e_fim_do_dia():
    p = ef.ParamFluxo()
    # R$ 1.000 de lucro acumulado paga um degrau de 2 contratos; devolveu o lucro, volta
    assert [ef.lote_do_dia(x, p) for x in (-500.0, 0.0, 999.0, 1000.0, 2500.0, 50_000.0)] == [2, 2, 2, 4, 6, 10]
    e = ef.EstadoF("WINFUT")
    e.posicao = ef.PosicaoF("C", 2, 206000.0, 205880.0, "16:00:00", "defesa", 205950.0, "abertura", 2, False, 206000.0)
    ev = ef.passo(e, 5000.0, "17:20:00", 206100.0, None, [], p, lote=2)
    # sai a mercado, 1 tick contra: 206.095 = +95 pontos x 0,20 x 2 - 1,20 = 36,80
    assert ev[0]["motivo"] == "fim_do_dia" and ev[0]["resultado"] == pytest.approx(36.80) and e.posicao is None
    assert len(ef.regras_em_texto(p)) >= 9


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

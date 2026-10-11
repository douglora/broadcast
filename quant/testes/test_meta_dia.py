"""Motor da medicao da meta do dia (quant/pesquisa/meta_dia.py): igual ao historico.py do robo sem a meta, e com a meta, a perda e a reserva do dado."""
import numpy as np
import pandas as pd
import pytest

from quant.daytrade import historico as h
from quant.daytrade.historico import Custos, Estrategia, Ordem, RegrasDoDia
from quant.pesquisa import meta_dia as md

DIA = "2026-03-03"          # sem horario de verao nos EUA: o dado das 8h30 de Nova York cai as 10h30 de Brasilia


def barras(precos, inicio="09:00", dia=DIA, amplitude=0.5, minutos=330):
    """Barras de 1 minuto ate as 14h30: `precos` e o fechamento dos primeiros minutos (depois fica no ultimo); abre no fechamento anterior;
    maxima/minima com `amplitude` de folga. O dia inteiro existe para o robo poder zerar as 13h."""
    precos = list(precos) + [precos[-1]] * max(0, minutos - len(precos))
    idx = pd.date_range(f"{dia} {inicio}", periods=len(precos), freq="min")
    c = np.array(precos, dtype=float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"o": o, "h": np.maximum(o, c) + amplitude, "l": np.minimum(o, c) - amplitude, "c": c, "n": 100.0, "v": 100.0}, index=idx)


class Fixa(Estrategia):
    """Sinaliza nas barras pedidas: {indice_da_barra: Ordem}."""
    nome = "fixa"

    def __init__(self, pedidos):
        self.pedidos = pedidos

    def decidir(self, i, dia, ctx):
        return self.pedidos.get(i - ctx["i0"])


def ordem_c(stop=40.0, tempo=120):
    return Ordem("C", stop_pts=stop, tempo_max=tempo, motivo="teste")


def rodar(precos, pedidos, meta, amplitude=0.5, **kw):
    m = barras(precos, amplitude=amplitude)
    # a regra do robo: 2 contratos, janela 09:15-12:50, zera as 13:00
    return md.simular(m, Fixa(pedidos), RegrasDoDia(contratos=2), Custos(), meta=meta, **kw)


def test_sem_meta_e_igual_ao_historico_do_robo():
    precos = [5000.0] * 20 + list(np.linspace(5000, 5012, 30)) + list(np.linspace(5012, 4990, 60)) + [4990.0] * 120
    m = barras(precos)
    ped = {20: ordem_c(stop=8.0), 100: Ordem("V", stop_pts=5.0, alvo_pts=3.0, parcial_pts=2.0, motivo="teste")}
    ref = h.simular(m, _Absoluta(ped), RegrasDoDia(contratos=2, meta_rs=None, perda_maxima_rs=None, perdas_para_parar=None))
    novo, _ = md.simular(m, _Absoluta(ped), RegrasDoDia(contratos=2), Custos(), meta=None, perda_dentro=False)
    assert [round(x.resultado, 6) for x in ref] == [round(x.resultado, 6) for x in novo] and len(ref) >= 1


class _Absoluta(Estrategia):
    nome = "abs"

    def __init__(self, pedidos):
        self.pedidos = pedidos

    def decidir(self, i, dia, ctx):
        return self.pedidos.get(i)


def test_a_meta_fecha_a_mercado_em_torno_de_r_95_liquidos_e_para_o_dia():
    # compra na barra 20 (09:20) -> entra na abertura de 09:21 a 5000,5 (1 tick pior); sobe devagar 1 ponto por minuto
    precos = [5000.0] * 21 + [5000.0 + k for k in range(1, 30)] + [5029.0] * 60
    negs, bateu = rodar(precos, {20: ordem_c(), 40: ordem_c()}, meta=100.0)
    assert len(negs) == 1 and negs[0].saida == "meta do dia" and bateu[pd.Timestamp(DIA).date()] is True       # o segundo sinal nao entra: parou
    # 2 contratos: o dia chega a R$ 100 liquidos com 5,24 pontos a favor (R$ 4,80 de custo): gatilho em 5000,5 + 5,5; sai 1 tick pior: +5,0 pontos
    assert negs[0].pontos == pytest.approx(5.0) and negs[0].resultado == pytest.approx(5.0 * 10 * 2 - 4.8)
    assert 90.0 <= negs[0].resultado <= 100.0
    # sem meta o mesmo negocio corre ate o tempo e rende mais
    sem, _ = rodar(precos, {20: ordem_c()}, meta=None)
    assert sem[0].saida == "tempo" and sem[0].resultado > 300.0


def test_no_mesmo_minuto_o_stop_vem_antes_da_meta():
    # na barra de entrada o preco vai ate +6 e volta a -5: dentro da mesma barra o lado adverso vale primeiro
    m = barras([5000.0] * 25)
    i = 21
    m.iloc[i, m.columns.get_loc("h")] = 5006.0
    m.iloc[i, m.columns.get_loc("l")] = 4994.0
    negs, bateu = md.simular(m, _Absoluta({20: ordem_c(stop=5.0)}), RegrasDoDia(contratos=2), Custos(), meta=100.0)
    assert negs[0].saida == "stop" and bateu[pd.Timestamp(DIA).date()] is False


def test_perda_do_dia_vale_dentro_do_negocio():
    # primeiro negocio perde R$ 700 no stop (35 pontos x R$ 20); o segundo, com stop de 40, so poderia perder mais R$ 300 antes do limite de R$ 1.000
    precos = [5000.0] * 21 + [5000.0 - k for k in range(1, 36)] + [4965.0] * 10 + [4965.0 - 0.5 * k for k in range(1, 61)] + [4935.0] * 60
    negs, _ = rodar(precos, {20: ordem_c(stop=34.0), 72: ordem_c(stop=40.0)}, meta=None)
    assert len(negs) == 2 and negs[0].saida == "stop"
    assert negs[1].saida == "perda maxima do dia" and negs[0].resultado + negs[1].resultado == pytest.approx(-1000.0, abs=15.0)
    # sem o limite dentro do negocio (como o historico.py), o segundo sairia so no stop de 40 pontos
    fora, _ = rodar(precos, {20: ordem_c(stop=34.0), 72: ordem_c(stop=40.0)}, meta=None, perda_dentro=False)
    assert len(fora) <= 2 and (len(fora) < 2 or fora[1].saida != "perda maxima do dia")


def test_trava_de_protecao_leva_o_stop_para_o_dia_fechar_em_90_e_deixa_correr():
    # sobe 6 pontos (toca a meta), recua ate 1 ponto e sobe de novo ate +15: a protecao segura +R$ 90 se o recuo passar do stop dela
    sobe_e_recua = [5000.0] * 21 + [5000.0 + k for k in range(1, 7)] + [5006.0 - k for k in range(1, 7)] + [5000.0] * 60
    negs, _ = rodar(sobe_e_recua, {20: ordem_c()}, meta=100.0, lock=90.0)
    assert negs[0].saida in ("stop", "stop móvel") and 80.0 <= negs[0].resultado <= 95.0      # saiu protegido, perto de R$ 90
    corre = [5000.0] * 21 + [5006.0] + [5020.0] * 100          # toca a meta na barra de entrada e dispara; sem folga de maxima/minima
    negs, bateu = rodar(corre, {20: ordem_c()}, meta=100.0, lock=90.0, amplitude=0.0)
    assert negs[0].saida == "tempo" and negs[0].resultado > 300.0 and bateu[pd.Timestamp(DIA).date()] is True
    # e o dia termina: sem entrada nova depois da protecao
    negs2, _ = rodar(corre, {20: ordem_c(), 150: ordem_c()}, meta=100.0, lock=90.0, amplitude=0.0)
    assert len(negs2) == 1


def test_reserva_do_dado_tira_as_outras_regras_da_janela_antes_do_dado():
    precos = [5000.0] * 300
    m = barras(precos)
    dado = md.DadoNY()
    outra = _Absoluta({k: ordem_c() for k in range(0, 300)})
    pri = md.Prioridade([dado, outra])
    pri.preparar(m)
    hm = m.index.strftime("%H:%M")
    # decisao no fechamento da barra: a barra de 10h07 decide as 10h08 (22 minutos antes do dado) e a de 10h31 decide as 10h32 (minuto da entrada)
    assert not pri.reserva[list(hm).index("10:06")] and pri.reserva[list(hm).index("10:07")] and pri.reserva[list(hm).index("10:31")]
    assert not pri.reserva[list(hm).index("10:32")]
    assert pri.decidir(list(hm).index("10:20"), None, {}) is None and pri.decidir(list(hm).index("11:00"), None, {}) is not None

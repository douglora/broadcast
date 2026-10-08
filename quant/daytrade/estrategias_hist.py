"""
Regras escritas so com preco e volume, para o teste historico (historico.py).

  PhiCube        o day trade que Bo Williams descreve para quem comeca: no grafico de 15 minutos as tres
                 medias (34, 144, 610) dizem se ha tendencia; no de 4 minutos, a virada a favor e o gatilho;
                 em consolidacao, fica de fora.
  Rompimento     a regra antiga do robo (versao 0): maxima ou minima do dia rompida do lado do preco medio.
  NivelPerdido   o nivel perdido com reteste, do metodo de fluxo, so com preco: ajuste de ontem.

Nenhuma olha o futuro: no fechamento da barra de 1 minuto `i` so entram barras de 4 e de 15 minutos que
JA FECHARAM.
"""
import numpy as np
import pandas as pd

from quant.daytrade.historico import Estrategia, Ordem, reamostrar


def media(serie, n, tipo="sma"):
    if tipo == "ema":
        return serie.ewm(span=n, adjust=False, min_periods=n).mean()
    return serie.rolling(n, min_periods=n).mean()


def _fechadas(m1_index, tf, minutos):
    """Para cada barra de 1 minuto, a posicao da ultima barra de `minutos` que ja fechou (-1 se nenhuma)."""
    fim_m1 = m1_index.values.astype("datetime64[ns]") + np.timedelta64(1, "m")
    fim_tf = tf.index.values.astype("datetime64[ns]") + np.timedelta64(int(minutos), "m")
    return np.searchsorted(fim_tf, fim_m1, side="right") - 1


def vwap_do_dia(m1):
    tipico = (m1["h"] + m1["l"] + m1["c"]) / 3.0
    dia = m1.index.date
    pv = (tipico * m1["v"]).groupby(dia).cumsum()
    vv = m1["v"].groupby(dia).cumsum().replace(0, np.nan)
    return (pv / vv).ffill()


def ajuste_de_ontem(m1):
    """O ajuste do mini-dolar e a media ponderada dos negocios das 15h50 as 16h. Devolve, por barra, o do pregao anterior."""
    hm = m1.index.strftime("%H:%M")
    janela = m1[(hm >= "15:50") & (hm < "16:00")]
    tipico = (janela["h"] + janela["l"] + janela["c"]) / 3.0
    por_dia = (tipico * janela["v"]).groupby(janela.index.date).sum() / janela["v"].groupby(janela.index.date).sum()
    por_dia = por_dia.dropna()
    dias = pd.Series(m1.index.date, index=m1.index)
    anterior = por_dia.shift(1)                                   # o de ontem vale hoje
    return dias.map(anterior).astype(float)


class PhiCube(Estrategia):
    """Tendencia no tempo maior, gatilho no menor.

    tendencia de alta (tempo maior): fechamento acima das tres medias e 34 > 144 > 610 ("alinhadas numericamente");
    gatilho (tempo menor): a barra fecha acima da media curta depois de ter fechado abaixo ("virou para cima").
    stop: abaixo da minima das ultimas `fundo` barras do tempo menor (entre stop_min e stop_max pontos);
    saida: parcial com 1 risco e stop na entrada, resto com alvo em `alvo_r` riscos (o "3 por 1" dele) ou stop movel.
    """

    def __init__(self, maior=15, menor=4, tipo="sma", periodos=(34, 144, 610), gatilho="cruza34", exige_alinhamento=True,
                 fundo=5, stop_min=2.0, stop_max=8.0, alvo_r=3.0, parcial_r=1.0, arrasto_r=None, menor_alinhado=False, nome=None):
        self.maior, self.menor, self.tipo, self.periodos = maior, menor, tipo, tuple(periodos)
        self.gatilho, self.exige_alinhamento, self.fundo = gatilho, exige_alinhamento, fundo
        self.stop_min, self.stop_max, self.alvo_r, self.parcial_r, self.arrasto_r = stop_min, stop_max, alvo_r, parcial_r, arrasto_r
        self.menor_alinhado = menor_alinhado
        self.nome = nome or f"PhiCube {maior}/{menor} {tipo}"

    def preparar(self, m1):
        self.m1 = m1
        p1, p2, p3 = self.periodos
        g = reamostrar(m1, self.maior)
        a, b, c = media(g["c"], p1, self.tipo), media(g["c"], p2, self.tipo), media(g["c"], p3, self.tipo)
        acima = (g["c"] > a) & (g["c"] > b) & (g["c"] > c)
        abaixo = (g["c"] < a) & (g["c"] < b) & (g["c"] < c)
        if self.exige_alinhamento:
            acima &= (a > b) & (b > c)
            abaixo &= (a < b) & (b < c)
        self.tend = np.where(acima, 1, np.where(abaixo, -1, 0))
        self.tend[np.isnan(c.to_numpy())] = 0
        s = reamostrar(m1, self.menor)
        ms, mm = media(s["c"], p1, self.tipo), media(s["c"], p2, self.tipo)
        fech = s["c"].to_numpy()
        ma = ms.to_numpy()
        virou_cima = (fech > ma) & (np.roll(fech, 1) <= np.roll(ma, 1))
        virou_baixo = (fech < ma) & (np.roll(fech, 1) >= np.roll(ma, 1))
        if self.menor_alinhado:                                   # no tempo menor a media curta tambem ja esta acima da media
            virou_cima &= (ms > mm).to_numpy()
            virou_baixo &= (ms < mm).to_numpy()
        virou_cima[0] = virou_baixo[0] = False
        self.virou = np.where(virou_cima, 1, np.where(virou_baixo, -1, 0))
        self.virou[np.isnan(ma)] = 0
        self.fundo_min = s["l"].rolling(self.fundo, min_periods=1).min().to_numpy()
        self.topo_max = s["h"].rolling(self.fundo, min_periods=1).max().to_numpy()
        self.fech_s = fech
        self.ig = _fechadas(m1.index, g, self.maior)
        self.is_ = _fechadas(m1.index, s, self.menor)
        self.nova_s = np.r_[True, self.is_[1:] != self.is_[:-1]]  # nesta barra de 1 minuto fechou uma barra do tempo menor

    def decidir(self, i, dia, ctx):
        if not self.nova_s[i] or self.ig[i] < 0 or self.is_[i] < 0:
            return None
        t, k = self.tend[self.ig[i]], self.is_[i]
        if t == 0 or self.virou[k] != t:
            return None
        ref = self.fech_s[k]
        risco = (ref - self.fundo_min[k]) if t > 0 else (self.topo_max[k] - ref)
        risco = float(min(max(risco + 0.5, self.stop_min), self.stop_max))
        return Ordem(lado="C" if t > 0 else "V", stop_pts=risco,
                     parcial_pts=None if self.parcial_r is None else self.parcial_r * risco,
                     alvo_pts=None if self.alvo_r is None else self.alvo_r * risco,
                     arrasto_pts=None if self.arrasto_r is None else self.arrasto_r * risco, motivo=self.nome)


class Rompimento(Estrategia):
    """A regra antiga (versao 0), no essencial: rompe a maxima do dia acima do preco medio -> compra; espelho na venda.
    Stop = vai-e-vem dos ultimos 15 minutos, entre 3 e 8 pontos; alvo de 2 riscos; stop na entrada com 1 risco."""
    nome = "Rompimento do dia (regra antiga)"

    def __init__(self, stop_min=3.0, stop_max=8.0, alvo_r=2.0):
        self.stop_min, self.stop_max, self.alvo_r = stop_min, stop_max, alvo_r

    def preparar(self, m1):
        self.m1 = m1
        dia = m1.index.date
        self.max_antes = m1["h"].groupby(dia).cummax().groupby(dia).shift(1).to_numpy()
        self.min_antes = m1["l"].groupby(dia).cummin().groupby(dia).shift(1).to_numpy()
        self.vwap = vwap_do_dia(m1).to_numpy()
        self.vai = (m1["h"].rolling(15, min_periods=5).max() - m1["l"].rolling(15, min_periods=5).min()).to_numpy()
        self.c = m1["c"].to_numpy()

    def decidir(self, i, dia, ctx):
        c, mx, mn, vw, vai = self.c[i], self.max_antes[i], self.min_antes[i], self.vwap[i], self.vai[i]
        if np.isnan(mx) or np.isnan(vw) or np.isnan(vai):
            return None
        risco = float(min(max(vai, self.stop_min), self.stop_max))
        if c > mx and c > vw:
            return Ordem("C", risco, parcial_pts=None, alvo_pts=self.alvo_r * risco, arrasto_pts=None, motivo=self.nome)
        if c < mn and c < vw:
            return Ordem("V", risco, parcial_pts=None, alvo_pts=self.alvo_r * risco, arrasto_pts=None, motivo=self.nome)
        return None


class NivelPerdido(Estrategia):
    """O nivel perdido com reteste, so com preco, no ajuste de ontem: o preco passa para o outro lado do ajuste,
    volta a encostar nele (ate meio ponto), falha e fecha de novo 1 ponto alem. Stop 1 ponto alem do ajuste;
    parcial de 2 pontos; resto com stop 3 pontos atras."""
    nome = "Nível perdido com reteste (ajuste)"

    def __init__(self, gatilho=1.0, zona=0.5, validade=20, parcial=2.0, arrasto=3.0, stop_max=5.0):
        self.gatilho, self.zona, self.validade, self.parcial, self.arrasto, self.stop_max = gatilho, zona, validade, parcial, arrasto, stop_max

    def preparar(self, m1):
        self.m1 = m1
        self.aj = ajuste_de_ontem(m1).to_numpy()
        self.c, self.h, self.l = m1["c"].to_numpy(), m1["h"].to_numpy(), m1["l"].to_numpy()

    def decidir(self, i, dia, ctx):
        aj = self.aj[i]
        if np.isnan(aj):
            return None
        e = ctx.setdefault("np", {"lado": None, "perda": None})
        c = self.c[i]
        d = c - aj
        if e["lado"] is None:
            if abs(d) >= self.gatilho:
                e["lado"] = 1 if d > 0 else -1
            return None
        if e["lado"] > 0 and d <= -self.gatilho:
            e["lado"], e["perda"] = -1, {"i": i, "s": -1, "ret": False}
            return None
        if e["lado"] < 0 and d >= self.gatilho:
            e["lado"], e["perda"] = 1, {"i": i, "s": 1, "ret": False}
            return None
        p = e["perda"]
        if p is None:
            return None
        if i - p["i"] > self.validade:
            e["perda"] = None
            return None
        s = p["s"]
        alem = d * s
        encostou = (self.h[i] >= aj - self.zona) if s < 0 else (self.l[i] <= aj + self.zona)
        if encostou and i > p["i"]:
            p["ret"] = True
        if p["ret"] and alem >= self.gatilho and i > p["i"]:
            e["perda"] = None
            risco = float(min(max(alem + 1.0 + 0.5, 2.0), self.stop_max))
            return Ordem("C" if s > 0 else "V", risco, parcial_pts=self.parcial, alvo_pts=None, arrasto_pts=self.arrasto, motivo=self.nome)
        return None

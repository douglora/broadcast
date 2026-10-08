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
    v = m1_index.values.astype("datetime64[ns]")
    passo = int(np.median(np.diff(v[:2000]).astype("timedelta64[m]").astype(int))) if len(v) > 2 else 1   # a base pode ser de 5 minutos
    fim_m1 = v + np.timedelta64(max(passo, 1), "m")
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


# ── PhiCube, segunda leitura: MIMA reconstruida, ROC e Prisma ────────────────────────────────────
PHI = (1 + 5 ** 0.5) / 2


def mima(serie, n, tipo="mima"):
    """A media do PhiCube. A formula oficial nao e publicada; `mima` e a reconstrucao de terceiro
    (2 x EMA curta - EMA longa, com a longa em n x 4,236), que anda mais colada no preco que a EMA.
    `ema` e o modelo oficial simples ("PhiCube EMA")."""
    if tipo == "ema":
        return serie.ewm(span=n, adjust=False, min_periods=n).mean()
    longa = int(n * PHI ** 3)
    curta = int(round(2 * n * (1 + PHI ** -6))) - 1
    return 2 * serie.ewm(span=curta, adjust=False, min_periods=curta).mean() - serie.ewm(span=longa, adjust=False, min_periods=longa).mean()


def roc(m):
    """O ROC do PhiCube: a media menos a media exponencial de 4 dela mesma. Acima de zero, a media sobe."""
    return m - m.ewm(span=4, adjust=False).mean()


def prisma(barras, tipo="mima", periodos=(34, 144, 610)):
    """De 0 a 7: 1 se a media pequena sobe, mais 2 se a media sobe, mais 4 se a grande sobe. 6 e 7 compra, 0 e 1 venda."""
    c = barras["c"]
    ms = [mima(c, n, tipo) for n in periodos]
    rs = [roc(m) for m in ms]
    p = (rs[0] > 0).astype(int) + 2 * (rs[1] > 0).astype(int) + 4 * (rs[2] > 0).astype(int)
    p[rs[2].isna()] = -1
    return p, ms, rs


class PhiCubeV1(Estrategia):
    """O que os videos mais detalhados descrevem:
    filtro   no tempo maior, Prisma 6 ou 7 (media e grande subindo) so compra; 0 ou 1 so vende; o resto fica fora.
             Com `exige_preco`, o preco tambem tem de estar acima (abaixo) das tres medias do tempo maior.
    gatilho  no tempo menor, o ROC da media de 34 VIRA a favor (passa de negativo a positivo) com as de 144 e 610
             a favor: o Prisma do tempo menor vai a 7 (ou a 0 na venda). E o "virou" dele.
    stop     atras do fundo (topo) das ultimas `fundo` barras do tempo menor, entre stop_min e stop_max pontos.
    saida    `saida="alvo"`: alvo em alvo_r riscos, parcial em parcial_r riscos com stop na entrada;
             `saida="fixo"`: alvo de alvo_pts pontos (ele cita 35 pontos no dolar), parcial em parcial_r riscos;
             `saida="movel"`: sem alvo, stop andando arrasto_r riscos atras do melhor preco."""

    def __init__(self, maior=15, menor=4, tipo="mima", exige_preco=True, fundo=5, stop_min=2.0, stop_max=8.0,
                 saida="alvo", alvo_r=3.0, alvo_pts=35.0, parcial_r=1.0, arrasto_r=1.5, menor_completo=True, nome=None):
        self.maior, self.menor, self.tipo, self.exige_preco, self.fundo = maior, menor, tipo, exige_preco, fundo
        self.stop_min, self.stop_max, self.saida = stop_min, stop_max, saida
        self.alvo_r, self.alvo_pts, self.parcial_r, self.arrasto_r, self.menor_completo = alvo_r, alvo_pts, parcial_r, arrasto_r, menor_completo
        self.nome = nome or f"PhiCube v1 {maior}/{menor} {tipo} {saida}"

    def preparar(self, m1):
        self.m1 = m1
        g = reamostrar(m1, self.maior)
        pg, mg, _ = prisma(g, self.tipo)
        lado = np.where(pg >= 6, 1, np.where((pg >= 0) & (pg <= 1), -1, 0))
        if self.exige_preco:
            acima = ((g["c"] > mg[0]) & (g["c"] > mg[1]) & (g["c"] > mg[2])).to_numpy()
            abaixo = ((g["c"] < mg[0]) & (g["c"] < mg[1]) & (g["c"] < mg[2])).to_numpy()
            lado = np.where((lado == 1) & acima, 1, np.where((lado == -1) & abaixo, -1, 0))
        self.lado_g = lado
        s = reamostrar(m1, self.menor)
        ps, _ms, rs = prisma(s, self.tipo)
        r34 = rs[0].to_numpy()
        antes = np.roll(r34, 1)
        cima, baixo = (r34 > 0) & (antes <= 0), (r34 < 0) & (antes >= 0)
        if self.menor_completo:
            cima &= (ps == 7).to_numpy()
            baixo &= (ps == 0).to_numpy()
        cima[0] = baixo[0] = False
        self.virou = np.where(cima, 1, np.where(baixo, -1, 0))
        self.virou[np.isnan(r34)] = 0
        self.fundo_min = s["l"].rolling(self.fundo, min_periods=1).min().to_numpy()
        self.topo_max = s["h"].rolling(self.fundo, min_periods=1).max().to_numpy()
        self.fech_s = s["c"].to_numpy()
        self.ig, self.is_ = _fechadas(m1.index, g, self.maior), _fechadas(m1.index, s, self.menor)
        self.nova_s = np.r_[True, self.is_[1:] != self.is_[:-1]]

    def decidir(self, i, dia, ctx):
        if not self.nova_s[i] or self.ig[i] < 0 or self.is_[i] < 0:
            return None
        t, k = self.lado_g[self.ig[i]], self.is_[i]
        if t == 0 or self.virou[k] != t:
            return None
        ref = self.fech_s[k]
        risco = (ref - self.fundo_min[k]) if t > 0 else (self.topo_max[k] - ref)
        risco = float(min(max(risco + 0.5, self.stop_min), self.stop_max))
        lado = "C" if t > 0 else "V"
        parcial = None if self.parcial_r is None else self.parcial_r * risco
        if self.saida == "movel":
            return Ordem(lado, risco, parcial_pts=parcial, alvo_pts=None, arrasto_pts=self.arrasto_r * risco, motivo=self.nome)
        if self.saida == "fixo":
            return Ordem(lado, risco, parcial_pts=parcial, alvo_pts=self.alvo_pts, motivo=self.nome)
        return Ordem(lado, risco, parcial_pts=parcial, alvo_pts=self.alvo_r * risco, motivo=self.nome)


# ── O que os instrutores do PhiCube FAZEM nas lives (e o Alison tambem): teste de nivel e reacao ─
class NivelReacao(Estrategia):
    """O preco vai a um nivel marcado antes, e rejeitado, e a entrada e contra a chegada, com o stop colado
    atras do nivel e o alvo no nivel seguinte. Serve para as pontas de uma faixa e para o reteste de um nivel
    perdido (o suporte que virou resistencia): os dois sao "chegou no nivel e voltou".

    niveis   de ontem: maxima, minima, fechamento e ajuste (media das 15h50 as 16h); de hoje: abertura e a
             maxima e a minima do dia formadas ha pelo menos `idade_extremo` minutos; numeros redondos (de 10 em 10).
    teste    uma barra do tempo `tempo` encosta no nivel (ate `tol` antes, ate `fura` alem) e FECHA de volta,
             pelo menos `rejeita` pontos do lado de onde veio.
    stop     `folga` pontos alem do extremo da barra de teste (ou do nivel); maior que stop_max: nao opera ("stop caro").
    alvo     o proximo nivel na direcao da operacao, entre alvo_min e alvo_max pontos; sem nivel, `alvo_padrao`.
    filtro   so entra se o alvo paga pelo menos `rr_min` vezes o risco; com `linhas`, respeita o "proibido vender"
             (Prisma 6 ou 7 com preco acima das medias no proprio tempo) e o "proibido comprar"."""

    def __init__(self, tempo=4, tol=1.0, fura=2.0, rejeita=1.5, folga=1.0, stop_min=3.0, stop_max=10.0, alvo_min=13.0, alvo_max=40.0,
                 alvo_padrao=20.0, rr_min=2.0, parcial_r=1.0, idade_extremo=20, redondo=10.0, linhas=False, tipo="mima", nome=None):
        self.tempo, self.tol, self.fura, self.rejeita, self.folga = tempo, tol, fura, rejeita, folga
        self.stop_min, self.stop_max, self.alvo_min, self.alvo_max, self.alvo_padrao = stop_min, stop_max, alvo_min, alvo_max, alvo_padrao
        self.rr_min, self.parcial_r, self.idade_extremo, self.redondo, self.linhas, self.tipo = rr_min, parcial_r, idade_extremo, redondo, linhas, tipo
        self.nome = nome or f"Teste de nível e reação ({tempo} min)"

    def preparar(self, m1):
        self.m1 = m1
        dia = pd.Series(m1.index.date, index=m1.index)
        por_dia = m1.groupby(m1.index.date).agg(h=("h", "max"), l=("l", "min"), c=("c", "last"), o=("o", "first"))
        ontem = por_dia.shift(1)
        self.max_ontem, self.min_ontem, self.fech_ontem = (dia.map(ontem[k]).to_numpy(dtype=float) for k in ("h", "l", "c"))
        self.abertura = dia.map(por_dia["o"]).to_numpy(dtype=float)
        self.ajuste = ajuste_de_ontem(m1).to_numpy()
        d = m1.index.date
        self.max_dia = m1["h"].groupby(d).cummax().groupby(d).shift(self.idade_extremo).to_numpy()
        self.min_dia = m1["l"].groupby(d).cummin().groupby(d).shift(self.idade_extremo).to_numpy()
        s = reamostrar(m1, self.tempo)
        self.so, self.sh, self.sl, self.sc = (s[k].to_numpy() for k in ("o", "h", "l", "c"))
        self.is_ = _fechadas(m1.index, s, self.tempo)
        self.nova_s = np.r_[True, self.is_[1:] != self.is_[:-1]]
        if self.linhas:
            ps, ms, _ = prisma(s, self.tipo)
            acima = ((s["c"] > ms[0]) & (s["c"] > ms[1]) & (s["c"] > ms[2])).to_numpy()
            abaixo = ((s["c"] < ms[0]) & (s["c"] < ms[1]) & (s["c"] < ms[2])).to_numpy()
            p = ps.to_numpy()
            self.proibido_vender, self.proibido_comprar = (p >= 6) & acima, (p >= 0) & (p <= 1) & abaixo

    extras = ()                                            # niveis de fora: [(valor, nome)], postos pelo robo ao vivo

    def niveis_com_nome(self, i, preco):
        """{valor arredondado ao tick: nome}. Quando dois niveis caem no mesmo preco, vale o primeiro da lista."""
        base = np.floor(preco / self.redondo) * self.redondo
        lista = [(self.ajuste[i], "ajuste de ontem"), *[(v, n) for v, n in self.extras],
                 (self.max_ontem[i], "máxima de ontem"), (self.min_ontem[i], "mínima de ontem"), (self.fech_ontem[i], "fechamento de ontem"),
                 (self.abertura[i], "abertura"), (self.max_dia[i], "máxima do dia"), (self.min_dia[i], "mínima do dia"),
                 *[(base + k * self.redondo, "número redondo") for k in (-1, 0, 1, 2)]]
        fora = {}
        for v, nome in lista:
            if v is None or np.isnan(v):
                continue
            fora.setdefault(round(float(v) * 2) / 2, nome)
        return fora

    def niveis(self, i, preco):
        return sorted(self.niveis_com_nome(i, preco))

    def decidir(self, i, dia, ctx):
        if not self.nova_s[i] or self.is_[i] < 1:
            return None
        k = self.is_[i]
        o, h, l, c = self.so[k], self.sh[k], self.sl[k], self.sc[k]
        niveis = self.niveis(i, c)
        for L in niveis:
            # resistencia: veio de baixo, encostou (ou furou pouco) e fechou de volta
            if o < L and L - self.tol <= h <= L + self.fura and c <= L - self.rejeita:
                lado, risco = "V", max(h, L) + self.folga - c
                alvos = [c - x for x in niveis if self.alvo_min <= c - x <= self.alvo_max]
            elif o > L and L - self.fura <= l <= L + self.tol and c >= L + self.rejeita:
                lado, risco = "C", c - (min(l, L) - self.folga)
                alvos = [x - c for x in niveis if self.alvo_min <= x - c <= self.alvo_max]
            else:
                continue
            if self.linhas and ((lado == "V" and self.proibido_vender[k]) or (lado == "C" and self.proibido_comprar[k])):
                continue
            risco = max(risco + 0.5, self.stop_min)            # + meio ponto: a entrada sai 1 tick pior
            if risco > self.stop_max:
                continue                                       # stop caro: nao opera
            alvo = min(alvos) if alvos else self.alvo_padrao
            if alvo / risco < self.rr_min:
                continue
            return Ordem(lado, float(risco), parcial_pts=None if self.parcial_r is None else float(self.parcial_r * risco),
                         alvo_pts=float(alvo), motivo=f"{self.nome}: nível {L:.1f}", nivel=float(L),
                         nome_nivel=self.niveis_com_nome(i, c).get(L, "nível"))
        return None


class OrdemNoNivel(NivelReacao):
    """A mesma leitura de niveis, mas com a ordem PARADA no proprio nivel, antes de o preco chegar (como Bo faz numa
    live: "ordem de venda posta antes da resistencia"). Nao espera a rejeicao: economiza o deslize da entrada e
    aceita ser atropelada. Entra quando o preco vem na direcao do nivel e esta a ate `distancia` pontos dele."""

    def __init__(self, distancia=3.0, stop_pts=4.0, **kw):
        super().__init__(**kw)
        self.distancia, self.stop_fixo = distancia, stop_pts
        self.nome = kw.get("nome") or "Ordem parada no nível"

    def decidir(self, i, dia, ctx):
        if not self.nova_s[i] or self.is_[i] < 1:
            return None
        k = self.is_[i]
        o, c = self.so[k], self.sc[k]
        niveis = self.niveis(i, c)
        for L in niveis:
            if 0 < L - c <= self.distancia and c > o:                 # subindo para o nivel: vende nele
                lado, alvos = "V", [L - x for x in niveis if self.alvo_min <= L - x <= self.alvo_max]
            elif 0 < c - L <= self.distancia and c < o:               # caindo para o nivel: compra nele
                lado, alvos = "C", [x - L for x in niveis if self.alvo_min <= x - L <= self.alvo_max]
            else:
                continue
            if self.linhas and ((lado == "V" and self.proibido_vender[k]) or (lado == "C" and self.proibido_comprar[k])):
                continue
            alvo = min(alvos) if alvos else self.alvo_padrao
            if alvo / self.stop_fixo < self.rr_min:
                continue
            return Ordem(lado, float(self.stop_fixo), parcial_pts=None if self.parcial_r is None else float(self.parcial_r * self.stop_fixo),
                         alvo_pts=float(alvo), motivo=f"{self.nome}: nível {L:.1f}", limite=float(L), validade=12)
        return None

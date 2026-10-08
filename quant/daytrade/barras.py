"""
As barras de 1 minuto do mini-dolar para o robo ao vivo, e o sinal do setup PhiCube calculado sobre elas.

DE ONDE VEM A BARRA
  - o passado: o arquivo que o AutopilotFeed 1.3 exporta do MetaTrader (serie continua do mini-dolar com
    ajuste por diferenca, `autopilot_historia_WDOSD_M1.csv`), lido uma vez;
  - de hoje em diante: o fechamento de cada minuto, que o motor do terminal entrega em /vivo/intradia.
    O que chega e guardado em `quant/saida/daytrade/m1_<ATIVO>.csv` (so acrescenta), para a serie
    continuar inteira de um dia para o outro sem depender de exportar de novo.
As barras que vem do motor so tem o fechamento do minuto: maxima e minima ficam iguais a ele. As medias
do PhiCube sao sobre fechamento; o "fundo recente" usado no stop fica um pouco mais raso do que o real.

O SINAL
  A mesma classe do teste historico (estrategias_hist.PhiCube), chamada quando fecha uma barra do tempo
  menor: o que o robo opera ao vivo e exatamente o que foi testado no passado.
"""
import os

import numpy as np
import pandas as pd

from quant.comum import garantir_dir
from quant.daytrade import estrategias_hist as eh
from quant.daytrade import historico as hist

SERIE_DO_PASSADO = {"WDOFUT": "WDO$D", "WINFUT": "WIN$N"}
MAXIMO_NA_MEMORIA = 110_000         # barras de 1 minuto: a media de 610 reconstruida, em 15 minutos, pede 2.583 barras de 15 (72 pregoes)


class Barras:
    def __init__(self, ativo, pasta_saida, pasta_mt5=None):
        self.ativo = ativo
        self.arq_proprio = os.path.join(pasta_saida, f"m1_{ativo}.csv")
        self.df = self._carregar(pasta_mt5)
        self.ultimo_minuto = self.df.index[-1] if len(self.df) else None

    def _carregar(self, pasta_mt5):
        partes = []
        passado = hist.arquivo_de(SERIE_DO_PASSADO.get(self.ativo, self.ativo), 1, pasta_mt5)
        if os.path.exists(passado):
            try:
                partes.append(hist.carregar(passado))
            except Exception:
                pass
        if os.path.exists(self.arq_proprio):
            try:
                p = pd.read_csv(self.arq_proprio, sep=";", names=["hora", "a", "b", "c", "d", "e"], parse_dates=["hora"])
                p = p.dropna(subset=["a"]).drop_duplicates("hora", keep="last").set_index("hora").sort_index()
                inteira = p["d"].notna()                           # linha nova: hora;o;h;l;c;v. Linha antiga: hora;fechamento
                p = pd.DataFrame({"o": p["a"], "h": p["b"].where(inteira, p["a"]), "l": p["c"].where(inteira, p["a"]),
                                  "c": p["d"].where(inteira, p["a"]), "n": 0.0, "v": p["e"].where(inteira, 0.0)})
                partes.append(p)
            except Exception:
                pass
        if not partes:
            return pd.DataFrame(columns=["o", "h", "l", "c", "n", "v"], index=pd.DatetimeIndex([], name="hora"), dtype=float)
        df = pd.concat(partes)
        df = df[~df.index.duplicated(keep="first")].sort_index()      # onde o MetaTrader tem a barra inteira, vale a dele
        return df.iloc[-MAXIMO_NA_MEMORIA:]

    def acrescentar(self, minutos):
        """`minutos`: lista de (hora do minuto como Timestamp sem fuso, fechamento), so minutos JA FECHADOS.
        Guarda os que ainda nao tem. Devolve quantos entraram."""
        novos, trocas = {}, {}
        for x in minutos:                                    # (hora, fechamento) ou (hora, o, h, l, c, v)
            t = x[0]
            o, h, l, c, v = (x[1], x[1], x[1], x[1], 0.0) if len(x) == 2 else x[1:6]
            if not (c and c > 0):
                continue
            if self.ultimo_minuto is not None and t <= self.ultimo_minuto:
                # minuto guardado so com o fechamento (o motor chegou antes de a fita fechar o minuto): a barra inteira
                # da fita, quando chega, toma o lugar. Sem isso a maxima e a minima do candle ficavam erradas (08/10/2026).
                if float(v) > 0 and t in self.df.index and float(self.df.at[t, "v"]) == 0.0:
                    trocas[t] = (float(o), float(h), float(l), float(c), float(v))
                continue
            novos[t] = (float(o), float(h), float(l), float(c), float(v))
        for t, val in trocas.items():
            self.df.loc[t, ["o", "h", "l", "c", "v"]] = val
        if trocas:
            self._gravar_linhas(trocas)                      # o arquivo le a ULTIMA linha de cada minuto
        if not novos:
            return len(trocas)
        ordem = sorted(novos)
        add = pd.DataFrame({"o": [novos[t][0] for t in ordem], "h": [novos[t][1] for t in ordem], "l": [novos[t][2] for t in ordem],
                            "c": [novos[t][3] for t in ordem], "n": 0.0, "v": [novos[t][4] for t in ordem]},
                           index=pd.DatetimeIndex(ordem, name="hora"))
        self.df = pd.concat([self.df, add]).iloc[-MAXIMO_NA_MEMORIA:]
        self.ultimo_minuto = self.df.index[-1]
        self._gravar_linhas(novos)
        return len(novos) + len(trocas)

    def _gravar_linhas(self, barras):
        try:
            garantir_dir(os.path.dirname(self.arq_proprio))
            with open(self.arq_proprio, "a", encoding="ascii") as f:
                for t in sorted(barras):
                    o, h, l, c, v = barras[t]
                    f.write(f"{t.strftime('%Y-%m-%d %H:%M:%S')};{o};{h};{l};{c};{v}\n")
        except OSError:
            pass


def minutos_do_motor(serie, agora):
    """A serie de /vivo/intradia -> [(minuto, fechamento)] dos minutos de hoje que ja fecharam."""
    fora = {}
    limite = int(agora.timestamp() // 60) * 60
    for t, p in zip(serie.get("t") or [], serie.get("p") or []):
        try:
            t, p = float(t), float(p)
        except (TypeError, ValueError):
            continue
        if p <= 0 or t >= limite:
            continue
        m = int(t // 60) * 60
        fora[m] = p                                            # o ultimo preco do minuto
    tz = agora.tzinfo
    return [(pd.Timestamp.fromtimestamp(m, tz).tz_localize(None), p) for m, p in sorted(fora.items())]


def minutos_da_fita(fita, depois_de=None):
    """Barras de 1 minuto INTEIRAS (abertura, maxima, minima, fechamento, volume) tiradas da fita de negocios,
    so dos minutos que ja fecharam no relogio da fita. A hora da fita ja e a de Brasilia."""
    if fita is None or not fita.linhas:
        return []
    minuto_atual = fita.relogio() // 60
    fora = {}
    for x in fita.linhas:
        m = x["seg"] // 60
        if m >= minuto_atual:
            continue
        p, v = x["preco"], x["compra"] + x["venda"] + x.get("indef", 0.0)
        b = fora.get(m)
        if b is None:
            fora[m] = [p, p, p, p, v]
        else:
            b[1], b[2], b[3], b[4] = max(b[1], p), min(b[2], p), p, b[4] + v
    lista = [(pd.Timestamp(m * 60, unit="s"), *b) for m, b in sorted(fora.items())]
    return [x for x in lista if depois_de is None or x[0] > depois_de]


def juntar_minutos(do_motor, da_fita):
    """Onde a fita tem o minuto inteiro, vale ela; onde nao tem, o fechamento que o motor da."""
    fora = {x[0]: x for x in do_motor}
    fora.update({x[0]: x for x in da_fita})
    return [fora[t] for t in sorted(fora)]


class SinalNiveis:
    """O teste de nivel com reacao (estrategias_hist.NivelReacao), calculado sobre as barras ao vivo."""
    BARRAS = 8_000                    # basta o pregao de ontem e o de hoje; sobra

    def __init__(self, **parametros):
        self.est = eh.NivelReacao(**parametros)
        self.leitura = None
        self.minuto_decidido = None

    def atualizar(self, df, extras=()):
        e = self.est
        d = df.iloc[-self.BARRAS:]
        if len(d) < 300:
            self.leitura = {"pronto": False, "motivo": f"faltam barras: {len(d)} de 300 minutos"}
            return self.leitura, None
        e.extras = tuple(extras)
        e.preparar(d)
        i = len(d) - 1
        k = int(e.is_[i])
        if k < 1:
            self.leitura = {"pronto": False, "motivo": "sem barra fechada"}
            return self.leitura, None
        c = float(e.sc[k])
        com_nome = e.niveis_com_nome(i, c)
        self.leitura = {"pronto": True, "setup": "niveis", "tempo_min": e.tempo, "fechamento": c,
                        "barra": [float(e.so[k]), float(e.sh[k]), float(e.sl[k]), c],
                        "niveis": [{"preco": v, "nome": com_nome[v]} for v in sorted(com_nome)],
                        "acima": next((v for v in sorted(com_nome) if v > c), None),
                        "abaixo": next((v for v in sorted(com_nome, reverse=True) if v < c), None),
                        "barras": int(len(df))}
        ordem = None
        if bool(e.nova_s[i]) and self.minuto_decidido != d.index[i]:
            self.minuto_decidido = d.index[i]
            ordem = e.decidir(i, d.index[i].date(), {})
        return self.leitura, ordem


class SinalClimax:
    """Climax de volume ao vivo (a regra e a de estrategias_hist.Climax), lido direto na fita do mini: no primeiro
    ciclo depois de um minuto fechar no relogio da fita, mede o tranco desse minuto (do abre ao fecha) e o volume dele
    contra a media dos minutos anteriores. Tranco com volume de `vol` vezes a media ou mais: ordem CONTRA o tranco."""

    def __init__(self, tranco=4.0, vol=3.0, janela=30, minimo=10, stop_fixo=10.0, alvo_devolve=0.6, tempo_max=20, atraso_max_s=8):
        self.tranco, self.vol, self.janela, self.minimo = tranco, vol, janela, minimo
        self.stop_fixo, self.alvo_devolve, self.tempo_max, self.atraso_max_s = stop_fixo, alvo_devolve, tempo_max, atraso_max_s
        self.minuto_visto = None
        self.leitura = {"pronto": False, "motivo": "esperando a fita"}

    def atualizar(self, fita):
        """Devolve (leitura, ordem). A ordem so sai no ciclo em que o minuto acabou de fechar."""
        if fita is None or not fita.linhas:
            self.leitura = {"pronto": False, "motivo": "sem fita de negócios"}
            return self.leitura, None
        relogio = fita.relogio()
        m_atual = relogio // 60
        if self.minuto_visto == m_atual:
            return self.leitura, None
        self.minuto_visto = m_atual
        fechados = minutos_da_fita(fita)
        ultimo = pd.Timestamp((m_atual - 1) * 60, unit="s")
        desde = pd.Timestamp((m_atual - 1 - self.janela) * 60, unit="s")
        barra = next((x for x in reversed(fechados) if x[0] == ultimo), None)
        antes = [x[5] for x in fechados if desde <= x[0] < ultimo and x[0].date() == ultimo.date() and x[5] > 0]
        if barra is None or len(antes) < self.minimo:
            self.leitura = {"pronto": False, "motivo": ("o último minuto não teve negócio" if barra is None else
                                                        f"faltam minutos de fita para a média de volume: {len(antes)} de {self.minimo}")}
            return self.leitura, None
        _t, o, h, l, c, v = barra
        r, media = c - o, sum(antes) / len(antes)
        vezes = v / media if media > 0 else 0.0
        self.leitura = {"pronto": True, "minuto": ultimo.strftime("%H:%M"), "tranco": round(r, 1), "volume": v, "media": round(media, 1),
                        "volume_x": round(vezes, 2), "pede_tranco": self.tranco, "pede_volume_x": self.vol}
        if abs(r) < self.tranco or vezes < self.vol or relogio % 60 > self.atraso_max_s:
            return self.leitura, None
        lado = "V" if r > 0 else "C"
        alvo = max(abs(r) * self.alvo_devolve, 1.5)
        return self.leitura, hist.Ordem(lado, stop_pts=self.stop_fixo, alvo_pts=alvo, parcial_pts=alvo, tempo_max=self.tempo_max,
                                        motivo="climax de volume", nivel=h if r > 0 else l,
                                        nome_nivel=f"tranco de {abs(r):g} pontos com volume de {vezes:.1f}x",
                                        info={"tranco": round(r, 1), "volume_x": round(vezes, 2), "volume": v, "media": round(media, 1)})


class SinalPhiCube:
    """Calcula, sobre as barras, a leitura do PhiCube (tendencia no tempo maior, virada no menor) e a ordem."""

    def __init__(self, classe=None, **parametros):
        self.est = (classe or eh.PhiCube)(**parametros)
        self.leitura = None
        self.minuto_decidido = None

    def atualizar(self, df):
        """Refaz as medias e devolve (leitura, ordem). A ordem so sai uma vez por barra do tempo menor."""
        if isinstance(self.est, eh.PhiCubeV1):
            return self._atualizar_v1(df)
        e = self.est
        minimo = e.periodos[2] * e.maior
        if len(df) < minimo:
            self.leitura = {"pronto": False, "motivo": f"faltam barras: {len(df)} de {minimo} minutos para a média de {e.periodos[2]} em {e.maior} minutos"}
            return self.leitura, None
        e.preparar(df)
        i = len(df) - 1
        ig, k = int(e.ig[i]), int(e.is_[i])
        if ig < 0 or k < 0:
            self.leitura = {"pronto": False, "motivo": "sem barra fechada"}
            return self.leitura, None
        g = hist.reamostrar(df, e.maior)
        p1, p2, p3 = e.periodos
        medias_g = [float(eh.media(g["c"], n, e.tipo).iloc[ig]) for n in (p1, p2, p3)]
        s = hist.reamostrar(df, e.menor)
        medias_s = [float(eh.media(s["c"], n, e.tipo).iloc[k]) for n in (p1, p2)]
        tend = int(e.tend[ig])
        self.leitura = {
            "pronto": True, "maior_min": e.maior, "menor_min": e.menor, "tipo_media": e.tipo, "periodos": [p1, p2, p3],
            "tendencia": {1: "alta", -1: "baixa", 0: "consolidação"}[tend],
            "fechamento_maior": float(g["c"].iloc[ig]), "medias_maior": medias_g,
            "alinhadas": bool((medias_g[0] > medias_g[1] > medias_g[2]) or (medias_g[0] < medias_g[1] < medias_g[2])),
            "fechamento_menor": float(s["c"].iloc[k]), "medias_menor": medias_s,
            "lado_menor": "acima" if s["c"].iloc[k] > medias_s[0] else "abaixo",
            "virou": int(e.virou[k]), "barra_menor": str(s.index[k]), "barras": int(len(df)),
        }
        ordem = None
        if bool(e.nova_s[i]) and self.minuto_decidido != df.index[i]:
            self.minuto_decidido = df.index[i]
            ordem = e.decidir(i, df.index[i].date(), {})
        return self.leitura, ordem

    def _atualizar_v1(self, df):
        """A leitura do PhiCube pela segunda versao: Prisma (0 a 7) nos dois tempos e a virada do ROC de 34."""
        e = self.est
        longa_610 = int(610 * eh.PHI ** 3) if e.tipo == "mima" else 610
        minimo = longa_610 * e.maior
        if len(df) < minimo:
            self.leitura = {"pronto": False, "motivo": f"faltam barras: {len(df)} de {minimo} minutos para a média grande em {e.maior} minutos"}
            return self.leitura, None
        e.preparar(df)
        i = len(df) - 1
        ig, k = int(e.ig[i]), int(e.is_[i])
        if ig < 0 or k < 0:
            self.leitura = {"pronto": False, "motivo": "sem barra fechada"}
            return self.leitura, None
        g, s = hist.reamostrar(df, e.maior), hist.reamostrar(df, e.menor)
        pg, mg, _rg = eh.prisma(g, e.tipo)
        ps, ms, rs = eh.prisma(s, e.tipo)
        lado = int(e.lado_g[ig])
        medias_g = [float(m.iloc[ig]) for m in mg]
        fech = float(g["c"].iloc[ig])
        self.leitura = {
            "pronto": True, "versao": 1, "maior_min": e.maior, "menor_min": e.menor, "tipo_media": e.tipo, "periodos": [34, 144, 610],
            "tendencia": {1: "alta", -1: "baixa", 0: "consolidação"}[lado],
            "prisma_maior": int(pg.iloc[ig]), "prisma_menor": int(ps.iloc[k]),
            "fechamento_maior": fech, "medias_maior": medias_g,
            "preco_fora_das_medias": bool(fech > max(medias_g) or fech < min(medias_g)),
            "alinhadas": bool((medias_g[0] > medias_g[1] > medias_g[2]) or (medias_g[0] < medias_g[1] < medias_g[2])),
            "fechamento_menor": float(s["c"].iloc[k]), "medias_menor": [float(m.iloc[k]) for m in ms[:2]],
            "lado_menor": "subindo" if float(rs[0].iloc[k]) > 0 else "caindo",
            "virou": int(e.virou[k]), "barra_menor": str(s.index[k]), "barras": int(len(df)),
        }
        ordem = None
        if bool(e.nova_s[i]) and self.minuto_decidido != df.index[i]:
            self.minuto_decidido = df.index[i]
            ordem = e.decidir(i, df.index[i].date(), {})
        return self.leitura, ordem

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
MAXIMO_NA_MEMORIA = 30_000          # barras de 1 minuto: ~55 pregoes, sobra para a media de 610 em 15 minutos


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
                p = pd.read_csv(self.arq_proprio, sep=";", names=["hora", "c"], parse_dates=["hora"])
                p = p.dropna().drop_duplicates("hora", keep="last").set_index("hora").sort_index()
                p = pd.DataFrame({"o": p["c"], "h": p["c"], "l": p["c"], "c": p["c"], "n": 0.0, "v": 0.0})
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
        novos = [(t, float(c)) for t, c in minutos if c and (self.ultimo_minuto is None or t > self.ultimo_minuto)]
        if not novos:
            return 0
        novos.sort()
        add = pd.DataFrame({"o": [c for _t, c in novos], "h": [c for _t, c in novos], "l": [c for _t, c in novos],
                            "c": [c for _t, c in novos], "n": 0.0, "v": 0.0}, index=pd.DatetimeIndex([t for t, _c in novos], name="hora"))
        self.df = pd.concat([self.df, add]).iloc[-MAXIMO_NA_MEMORIA:]
        self.ultimo_minuto = self.df.index[-1]
        try:
            garantir_dir(os.path.dirname(self.arq_proprio))
            with open(self.arq_proprio, "a", encoding="ascii") as f:
                for t, c in novos:
                    f.write(f"{t.strftime('%Y-%m-%d %H:%M:%S')};{c}\n")
        except OSError:
            pass
        return len(novos)


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


class SinalPhiCube:
    """Calcula, sobre as barras, a leitura do PhiCube (tendencia no tempo maior, virada no menor) e a ordem."""

    def __init__(self, **parametros):
        self.est = eh.PhiCube(**parametros)
        self.leitura = None
        self.minuto_decidido = None

    def atualizar(self, df):
        """Refaz as medias e devolve (leitura, ordem). A ordem so sai uma vez por barra do tempo menor."""
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

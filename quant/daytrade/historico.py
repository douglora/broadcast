"""
Teste historico do robo de day trade em barras de 1 minuto (as que o AutopilotFeed 1.3 exporta do
MetaTrader: `autopilot_historia_<SIMBOLO>_M<n>.csv`).

O QUE ELE RESPONDE: se uma regra escrita SO COM PRECO E VOLUME teria ganho dinheiro no passado,
depois de custo e de deslize. Regra que depende da fita (quem agrediu, lote no nivel) nao cabe
aqui: a fita so existe desde 08/10/2026.

COMO SIMULA, sempre contra a regra (o erro aceitavel e o que piora o resultado):
  - a regra decide no FECHAMENTO de uma barra de 1 minuto e a ordem sai na ABERTURA da seguinte,
    1 tick pior (ordem a mercado);
  - dentro de uma barra nao se sabe a ordem dos precos: se o stop e o ganho cabem na mesma barra,
    vale o stop;
  - stop sai a mercado, 1 tick pior; parcial e alvo saem no preco (ordem parada);
  - custo por contrato e por lado, em reais, em toda perna;
  - zera tudo na hora de zerar; nao dorme posicionado.

As regras do dia sao as do Douglas: janela, meta e perda maxima em reais, parada por perdas seguidas.
"""
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.daytrade import fluxo as fx

PASTA = fx.PASTA_MT5


def arquivo_de(simbolo, minutos=1, pasta=None):
    nome = simbolo.replace("$", "S").replace("@", "A")
    return os.path.join(pasta or PASTA, f"autopilot_historia_{nome}_M{minutos}.csv")


def carregar(arquivo):
    """Barras do arquivo do MetaTrader -> DataFrame indexado pela hora (de Brasilia), colunas o, h, l, c, n, v."""
    df = pd.read_csv(arquivo, sep=";", skiprows=1, comment="#", encoding="latin-1")
    df.columns = ["hora", "o", "h", "l", "c", "n", "v"]
    df["hora"] = pd.to_datetime(df["hora"], format="%Y.%m.%d %H:%M")
    df = df.dropna().drop_duplicates("hora").set_index("hora").sort_index()
    return df.astype({"o": float, "h": float, "l": float, "c": float, "n": float, "v": float})


def reamostrar(m1, minutos):
    """Barras de 1 minuto -> barras de `minutos`, fechadas a esquerda (a barra das 9h00 de 5 min vai de 9h00 a 9h04)."""
    r = m1.resample(f"{int(minutos)}min", label="left", closed="left").agg(
        {"o": "first", "h": "max", "l": "min", "c": "last", "n": "sum", "v": "sum"})
    return r.dropna(subset=["o"])


@dataclass
class Custos:
    por_lado_rs: float = 1.20          # por contrato e por lado (emolumentos e registro; corretagem zero)
    deslize_ticks: int = 1             # nas ordens a mercado (entrada e stop)
    valor_ponto: float = 10.0          # mini-dolar
    tick: float = 0.5


@dataclass
class RegrasDoDia:
    inicio: str = "09:15"
    ultima_entrada: str = "12:50"
    zerar: str = "13:00"
    contratos: int = 2
    meta_rs: float | None = 1_000.0
    perda_maxima_rs: float | None = 1_000.0
    perdas_para_parar: int | None = 3
    max_operacoes: int = 12
    espera_min: int = 2                # minutos sem entrar depois de uma saida


@dataclass
class Ordem:
    lado: str                          # "C" ou "V"
    stop_pts: float                    # distancia do stop ao preco de entrada
    parcial_pts: float | None = None   # realiza metade aqui e leva o stop para a entrada
    alvo_pts: float | None = None      # sai de tudo aqui (None = sem alvo)
    arrasto_pts: float | None = None   # depois da parcial (ou desde o inicio, se nao ha parcial): stop atras do melhor preco
    motivo: str = ""
    limite: float | None = None        # ordem PARADA neste preco (sem deslize); None = a mercado na abertura da barra seguinte
    validade: int = 30                 # por quantas barras de 1 minuto a ordem parada espera
    nivel: float | None = None         # o nivel que motivou a ordem, e o nome dele (para a tela do robo)
    nome_nivel: str = ""
    info: dict = field(default_factory=dict)   # o que se sabia na hora da entrada (para estudar depois o que separa ganho de perda)
    tempo_max: int | None = None       # minutos: passou disso com a posicao aberta, sai a mercado (None = so stop, alvo ou fim da janela)


@dataclass
class Negocio:
    dia: object
    entrada_hora: object
    saida_hora: object
    lado: str
    contratos: int
    entrada: float
    saida_media: float
    pontos: float                      # medio por contrato, ja com deslize
    resultado: float                   # em reais, liquido de custos
    motivo: str
    saida: str
    info: dict = field(default_factory=dict)
    melhor_pts: float = 0.0            # o mais longe que o preco foi a favor, em pontos, enquanto a posicao esteve aberta


class Estrategia:
    """Uma regra: `preparar` calcula o que precisa sobre a serie inteira; `decidir` e chamada no fechamento
    de cada barra de 1 minuto dentro da janela, sem posicao, e devolve uma Ordem ou None. So pode olhar
    barras ate a posicao `i` (inclusive)."""
    nome = "base"

    def preparar(self, m1):
        self.m1 = m1

    def decidir(self, i, dia, ctx):
        return None


def simular(m1, estrategia, regras: RegrasDoDia | None = None, custos: Custos | None = None, de=None, ate=None):
    """Roda a estrategia dia a dia. Devolve a lista de Negocio."""
    regras, custos = regras or RegrasDoDia(), custos or Custos()
    estrategia.preparar(m1)
    o, h, l, c = (m1[k].to_numpy() for k in ("o", "h", "l", "c"))
    horas = m1.index
    hm = np.array([t.strftime("%H:%M") for t in horas])
    dias = np.array([t.date() for t in horas])
    desl = custos.deslize_ticks * custos.tick
    negocios = []
    n = len(m1)
    i = 0
    while i < n:
        dia = dias[i]
        j = i
        while j < n and dias[j] == dia:
            j += 1
        if (de is None or dia >= de) and (ate is None or dia <= ate):
            negocios.extend(_um_dia(i, j, dia, o, h, l, c, horas, hm, estrategia, regras, custos, desl))
        i = j
    return negocios


def _um_dia(i0, i1, dia, o, h, l, c, horas, hm, est, regras, custos, desl):
    fora = []
    pos = None                      # dict da posicao aberta
    pendente = None                 # (ordem parada, barra em que vence)
    resultado_dia, perdas, operacoes, livre_em = 0.0, 0, 0, i0
    travado = False
    ctx = {"i0": i0}
    for i in range(i0, i1):
        if pos is None and pendente is not None:
            ordem, vence = pendente
            if i > vence or hm[i] >= regras.ultima_entrada or travado:
                pendente = None
            else:
                # so conta como executada se o preco PASSA do limite por 1 tick: encostar nao garante a vez na fila
                pegou = (h[i] >= ordem.limite + custos.tick) if ordem.lado == "V" else (l[i] <= ordem.limite - custos.tick)
                if pegou:
                    pendente = None
                    pos = _abrir(ordem, ordem.limite, horas[i], i, regras)
                    operacoes += 1
        if pos is not None:
            fechou = _conduzir(pos, i, o, h, l, c, hm, regras, custos, desl)
            if fechou:
                pts = pos["soma_pts"] / pos["inicial"]
                custo = 2 * custos.por_lado_rs * pos["inicial"]
                res = pos["soma_pts"] * custos.valor_ponto - custo
                fora.append(Negocio(dia, pos["hora"], horas[i], pos["lado"], pos["inicial"], pos["entrada"],
                                    pos["entrada"] + (pts if pos["lado"] == "C" else -pts), pts, res, pos["motivo"], fechou,
                                    pos.get("info") or {}, abs(pos["melhor"] - pos["entrada"])))
                resultado_dia += res
                perdas += 1 if res < 0 else 0
                pos, livre_em = None, i + regras.espera_min
                if (regras.meta_rs and resultado_dia >= regras.meta_rs) or \
                        (regras.perda_maxima_rs and resultado_dia <= -regras.perda_maxima_rs) or \
                        (regras.perdas_para_parar and perdas >= regras.perdas_para_parar):
                    travado = True
            continue
        if travado or i + 1 >= i1 or i < livre_em or operacoes >= regras.max_operacoes:
            continue
        if not (regras.inicio <= hm[i] < regras.ultima_entrada):
            continue
        if pendente is not None:
            continue
        ordem = est.decidir(i, dia, ctx)
        if ordem is None:
            continue
        if ordem.limite is not None:
            pendente = (ordem, i + ordem.validade)
            continue
        pos = _abrir(ordem, o[i + 1] + (desl if ordem.lado == "C" else -desl), horas[i + 1], i + 1, regras)
        operacoes += 1
    return fora


def _abrir(ordem, entrada, hora, barra, regras):
    sinal = 1.0 if ordem.lado == "C" else -1.0
    return {"lado": ordem.lado, "sinal": sinal, "entrada": entrada, "hora": hora, "motivo": ordem.motivo, "info": ordem.info,
            "stop": entrada - sinal * ordem.stop_pts, "restam": regras.contratos, "inicial": regras.contratos,
            "parcial": None if ordem.parcial_pts is None or regras.contratos < 2 else entrada + sinal * ordem.parcial_pts,
            "alvo": None if ordem.alvo_pts is None else entrada + sinal * ordem.alvo_pts,
            "arrasto": ordem.arrasto_pts, "melhor": entrada, "soma_pts": 0.0, "aberta_em": barra, "parcial_feita": False,
            "tempo_max": ordem.tempo_max}


def _conduzir(pos, i, o, h, l, c, hm, regras, custos, desl):
    """Uma barra com posicao aberta. Devolve o motivo da saida final, ou None se segue aberta."""
    s = pos["sinal"]
    if i < pos["aberta_em"]:
        return None
    if hm[i] >= regras.zerar:                              # fim da janela: sai na abertura desta barra, a mercado
        pos["soma_pts"] += s * ((o[i] - s * desl) - pos["entrada"]) * pos["restam"]
        return "fim da janela"
    if pos.get("tempo_max") and i - pos["aberta_em"] >= pos["tempo_max"]:   # tempo esgotado: sai na abertura desta barra, a mercado
        pos["soma_pts"] += s * ((o[i] - s * desl) - pos["entrada"]) * pos["restam"]
        return "tempo"
    pior, melhor = (l[i], h[i]) if s > 0 else (h[i], l[i])
    if (pior <= pos["stop"]) if s > 0 else (pior >= pos["stop"]):   # o stop vem primeiro, sempre
        base = min(o[i], pos["stop"]) if s > 0 else max(o[i], pos["stop"])     # abriu alem do stop: sai na abertura
        pos["soma_pts"] += s * ((base - s * desl) - pos["entrada"]) * pos["restam"]
        return "stop" if not pos["parcial_feita"] else ("zero a zero" if abs(pos["stop"] - pos["entrada"]) < 1e-9 else "stop móvel")
    if pos["alvo"] is not None and ((melhor >= pos["alvo"]) if s > 0 else (melhor <= pos["alvo"])):
        pos["soma_pts"] += s * (pos["alvo"] - pos["entrada"]) * pos["restam"]
        return "alvo"
    if pos["parcial"] is not None and not pos["parcial_feita"] and ((melhor >= pos["parcial"]) if s > 0 else (melhor <= pos["parcial"])):
        metade = pos["restam"] // 2
        pos["soma_pts"] += s * (pos["parcial"] - pos["entrada"]) * metade
        pos["restam"] -= metade
        pos["parcial_feita"] = True
        pos["stop"] = pos["entrada"]
    pos["melhor"] = max(pos["melhor"], melhor) if s > 0 else min(pos["melhor"], melhor)
    if pos["arrasto"] is not None and (pos["parcial_feita"] or pos["parcial"] is None):
        movel = pos["melhor"] - s * pos["arrasto"]
        if (movel > pos["stop"]) if s > 0 else (movel < pos["stop"]):
            pos["stop"] = movel                              # vale a partir da barra seguinte
    return None


def resumo(negocios, capital=100_000.0):
    """Os numeros de uma rodada: quantos negocios, acerto, ganho e perda medios, resultado, pior sequencia."""
    if not negocios:
        return {"negocios": 0}
    r = np.array([x.resultado for x in negocios])
    dias = pd.Series(r, index=[x.dia for x in negocios]).groupby(level=0).sum()
    curva = dias.cumsum()
    queda = (curva - curva.cummax()).min()
    g, p = r[r > 0], r[r < 0]
    return {"negocios": int(len(r)), "dias": int(len(dias)), "acerto": float((r > 0).mean()),
            "ganho_medio": float(g.mean()) if len(g) else 0.0, "perda_media": float(p.mean()) if len(p) else 0.0,
            "por_negocio": float(r.mean()), "total": float(r.sum()), "por_dia": float(dias.mean()),
            "dias_positivos": float((dias > 0).mean()), "pior_dia": float(dias.min()), "melhor_dia": float(dias.max()),
            "maior_queda": float(queda), "pontos_por_negocio": float(np.mean([x.pontos for x in negocios])),
            "fator_de_lucro": float(g.sum() / -p.sum()) if len(p) and p.sum() < 0 else None,
            "retorno_pct": float(r.sum() / capital)}


def tabela(nome, rs):
    f = lambda v, casas=0: "-" if v is None else f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if not rs.get("negocios"):
        return f"{nome:<34} sem negocios"
    return (f"{nome:<34} neg {rs['negocios']:>5} | acerto {rs['acerto'] * 100:>4.0f}% | por negocio R$ {f(rs['por_negocio'], 2):>8} "
            f"| total R$ {f(rs['total']):>9} | por dia R$ {f(rs['por_dia'], 1):>7} | dias + {rs['dias_positivos'] * 100:>3.0f}% "
            f"| maior queda R$ {f(rs['maior_queda']):>8} | fator {f(rs['fator_de_lucro'], 2):>5}")

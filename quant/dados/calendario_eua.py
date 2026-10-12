"""
Calendario das divulgacoes economicas dos EUA (as das 8h30 de Nova York, que o setup do dado do mini-dolar opera) e os
numeros efetivos, de fontes publicas e gratuitas, sem login:

  1. DIVULGACOES do BLS (Employment Situation = payroll, CPI, PPI, precos de importacao, ECI, produtividade), 2021 a 2026:
     paginas publicas bls.gov/schedule/<ano>/home.htm, copiadas em 12/10/2026 para
     quant/dados_brutos/calendario_eua/bls_divulgacoes_2021_2026.csv (o site bloqueia robo; a copia foi feita pelo leitor
     de paginas do assistente e conferida contra 5 datas conhecidas: payroll de 05/01/2024, 02/08/2024, 07/02/2025,
     CPI de 12/03/2025, 14/10/2026).
  2. PEDIDOS DE AUXILIO-DESEMPREGO (jobless claims): toda quinta-feira as 8h30, adiantados para quarta quando a quinta e
     feriado federal (Thanksgiving, 4 de julho, Natal, Ano Novo, Juneteenth). Regra de calendario, nao lista baixada.
  3. EFETIVOS: API publica v1 do BLS (api.bls.gov/publicAPI/v1, sem chave; limite de 25 consultas por dia), guardados em
     bls_v1_lote1.json (payroll CES0000000001, desemprego LNS14000000, salario-hora CES0500000003) e bls_v1_lote2.json
     (CPI CUSR0000SA0, nucleo CUSR0000SA0L1E, PPI WPSFD4). Serve para a "surpresa ingenua" (efetivo contra o anterior).
  4. CONSENSO (mediana dos analistas): o feed semanal publico do ForexFactory (nfs.faireconomy.media/ff_calendar_thisweek.json,
     robots.txt libera; so a semana corrente), arquivado uma vez por semana em calendario_eua/ff/ff_calendar_thisweek_<data>.json.
     Historico de consenso de 3+ anos so existe no calendario do MetaTrader (script AutopilotCalendario.mq5, que precisa do
     "pode" do Douglas para ser compilado e rodado) ou em fontes pagas. Sem ele, a surpresa contra o consenso so existe de
     12/10/2026 em diante (prova viva).

O que NAO esta aqui (lacuna declarada): divulgacoes do BEA (PIB, PCE, balanca) e do Census (varejo, bens duraveis,
construcao) e os indices regionais do Fed, todos as 8h30 tambem. Dia marcado como "sem divulgacao conhecida" pode ter um
desses: a classificacao e conservadora para o lado do "tem dado", nunca o contrario.

Uso:
    from quant.dados import calendario_eua as ce
    ce.tipo_do_dia(date(2026, 10, 14))      # "cpi"
    ce.divulgacoes(date(2026, 10, 12), date(2026, 10, 16))   # DataFrame(data, tipo, divulgacao, fonte)
    ce.efetivos("CES0000000001")            # Series mensal (data de referencia -> valor)
    ce.consenso_ff(date(2026, 10, 14))      # eventos USD do feed arquivado, com consenso, anterior e efetivo
"""
import glob
import json
import os
from datetime import date, timedelta

import pandas as pd

from quant.comum import DIR_BRUTOS

DIR = os.path.join(DIR_BRUTOS, "calendario_eua")
ARQ_BLS = os.path.join(DIR, "bls_divulgacoes_2021_2026.csv")
# copia versionada (o site do BLS bloqueia robo; a lista foi copiada a mao e nao se refaz por script): vale quando dados_brutos nao a tem
ARQ_BLS_FIXO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixos", "bls_divulgacoes_2021_2026.csv")
ARQS_EFETIVOS = (os.path.join(DIR, "bls_v1_lote1.json"), os.path.join(DIR, "bls_v1_lote2.json"))
DIR_FF = os.path.join(DIR, "ff")

TIPOS = {"Employment Situation": "payroll", "Consumer Price Index": "cpi", "Real Earnings": "cpi", "Producer Price Index": "ppi",
         "Import and Export Price Indexes": "outro_bls", "Employment Cost Index": "outro_bls", "Productivity and Costs": "outro_bls"}
PRIORIDADE = ("payroll", "cpi", "ppi", "outro_bls", "claims", "nenhum")
SERIES = {"payroll": "CES0000000001", "desemprego": "LNS14000000", "salario_hora": "CES0500000003",
          "cpi": "CUSR0000SA0", "cpi_nucleo": "CUSR0000SA0L1E", "ppi": "WPSFD4"}


def _feriados_federais(ano):
    """Feriados federais dos EUA que caem em dia util e deslocam os pedidos de auxilio-desemprego (quinta -> quarta)."""
    def n_esimo(mes, dia_semana, n):
        d = date(ano, mes, 1)
        d += timedelta(days=(dia_semana - d.weekday()) % 7)
        return d + timedelta(days=7 * (n - 1))
    fixos = [date(ano, 1, 1), date(ano, 6, 19), date(ano, 7, 4), date(ano, 11, 11), date(ano, 12, 25)]
    return set(fixos + [n_esimo(11, 3, 4)])          # Thanksgiving = 4a quinta de novembro


def claims_dias(ano_ini=2021, ano_fim=2026):
    """Quintas-feiras (8h30 NY) dos pedidos de auxilio-desemprego; quarta quando a quinta e feriado federal."""
    fora = []
    for ano in range(ano_ini, ano_fim + 1):
        fer = _feriados_federais(ano)
        d = date(ano, 1, 1)
        d += timedelta(days=(3 - d.weekday()) % 7)   # primeira quinta
        while d.year == ano:
            fora.append(d - timedelta(days=1) if d in fer else d)
            d += timedelta(days=7)
    return fora


def carregar_bls(arq=None):
    arq = arq or (ARQ_BLS if os.path.exists(ARQ_BLS) else ARQ_BLS_FIXO)
    d = pd.read_csv(arq, sep=";", parse_dates=["data"])
    d["tipo"] = d["divulgacao"].map(TIPOS).fillna("outro_bls")
    d["data"] = d["data"].dt.date
    return d


def divulgacoes(de=None, ate=None, arq=None):
    """Uma linha por (dia, tipo): as divulgacoes das 8h30 de NY conhecidas. `tipo` em payroll, cpi, ppi, outro_bls, claims."""
    b = carregar_bls(arq)[["data", "tipo", "divulgacao", "fonte"]]
    anos = sorted({x.year for x in b["data"]}) or [2021, 2026]
    c = pd.DataFrame({"data": claims_dias(min(anos), max(anos)), "tipo": "claims", "divulgacao": "Unemployment Insurance Weekly Claims",
                      "fonte": "regra: quinta-feira 8h30 (quarta se feriado)"})
    d = pd.concat([b, c], ignore_index=True).drop_duplicates(["data", "tipo"]).sort_values(["data", "tipo"])
    if de is not None:
        d = d[d["data"] >= pd.Timestamp(de).date()]
    if ate is not None:
        d = d[d["data"] <= pd.Timestamp(ate).date()]
    return d.reset_index(drop=True)


def tipos_por_dia(de=None, ate=None, arq=None):
    """dict data -> conjunto de tipos das 8h30 naquele dia."""
    fora = {}
    for r in divulgacoes(de, ate, arq).itertuples():
        fora.setdefault(r.data, set()).add(r.tipo)
    return fora


def tipo_do_dia(dia, mapa=None, arq=None):
    """O tipo principal do dia, pela prioridade payroll > cpi > ppi > outro_bls > claims; "nenhum" quando nao ha divulgacao
    das 8h30 conhecida (pode haver BEA/Census: lacuna declarada no cabecalho)."""
    dia = pd.Timestamp(dia).date()
    tipos = (mapa if mapa is not None else tipos_por_dia(arq=arq)).get(dia, set())
    for t in PRIORIDADE:
        if t in tipos:
            return t
    return "nenhum"


def efetivos(serie, arqs=None):
    """Serie mensal do BLS (indice = primeiro dia do mes de referencia) para um codigo (ou apelido de SERIES)."""
    cod = SERIES.get(serie, serie)
    for arq in (arqs or ARQS_EFETIVOS):
        try:
            with open(arq, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        for s in (d.get("Results") or {}).get("series") or []:
            if s.get("seriesID") != cod:
                continue
            pts = []
            for x in s.get("data") or []:
                if not str(x.get("period", "")).startswith("M") or x.get("period") == "M13":
                    continue
                try:                                          # o BLS escreve "-" quando o mes nao foi coletado (paralisacao de 2025)
                    pts.append((pd.Timestamp(int(x["year"]), int(x["period"][1:]), 1), float(x["value"])))
                except (TypeError, ValueError):
                    continue
            return pd.Series(dict(pts)).sort_index()
    return pd.Series(dtype=float)


def surpresa_ingenua(serie, mes_referencia, variacao=True):
    """Efetivo do mes contra o que o mes anterior mostrava: para niveis (payroll), a variacao mensal contra a variacao do mes
    anterior; para indices (CPI, PPI), a variacao % mensal contra a do mes anterior. Nao e consenso: e o 'nada mudou' como
    expectativa. None sem dado."""
    s = efetivos(serie)
    m = pd.Timestamp(mes_referencia).replace(day=1)
    if m not in s.index:
        return None
    i = s.index.get_loc(m)
    if i < 2:
        return None
    if variacao and SERIES.get(serie, serie) in ("CUSR0000SA0", "CUSR0000SA0L1E", "WPSFD4"):
        v = s.pct_change()
        return float(v.iloc[i] - v.iloc[i - 1])
    v = s.diff()
    return float(v.iloc[i] - v.iloc[i - 1])


def consenso_ff(dia=None, pasta=None, pais="USD"):
    """Eventos do feed semanal arquivado do ForexFactory: lista de dicts com date, title, forecast, previous, actual, impact.
    Com `dia`, so os daquele dia (hora de Nova York no proprio campo date). Arquivos repetidos: vale o mais novo."""
    fora = {}
    for arq in sorted(glob.glob(os.path.join(pasta or DIR_FF, "ff_calendar_*.json"))):
        try:
            with open(arq, encoding="utf-8") as f:
                for ev in json.load(f):
                    if ev.get("country") != pais:
                        continue
                    chave = (str(ev.get("date"))[:16], ev.get("title"))
                    fora[chave] = dict(ev, arquivo=os.path.basename(arq))
        except (OSError, ValueError):
            continue
    evs = list(fora.values())
    if dia is not None:
        d = str(pd.Timestamp(dia).date())
        evs = [e for e in evs if str(e.get("date", ""))[:10] == d]
    return sorted(evs, key=lambda e: str(e.get("date")))


def surpresa_ff(ev):
    """(efetivo - consenso) de um evento do feed, em numero, ou None. Aceita '0.2%', '150K', '3.96M', '-1.5'."""
    def num(x):
        s = str(x or "").strip().replace(",", "")
        if not s:
            return None
        mult = 1.0
        if s.endswith("%"):
            s = s[:-1]
        elif s.endswith("K"):
            s, mult = s[:-1], 1e3
        elif s.endswith("M"):
            s, mult = s[:-1], 1e6
        elif s.endswith("B"):
            s, mult = s[:-1], 1e9
        try:
            return float(s) * mult
        except ValueError:
            return None
    a, f = num(ev.get("actual")), num(ev.get("forecast"))
    return None if a is None or f is None else a - f

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


# ----------------------------------------------------------------------------------------------------------------------
# Calendario economico do MetaTrader (exportado por AutopilotCalendario.mq5 na instancia Global; 12/10/2026, "pode" do
# Douglas). Historico desde 2019 com consenso, efetivo e anterior. Horario do arquivo: fuso fixo UTC+3 do servidor da
# MetaQuotes (conferido no payroll: 15:30 no horario de verao dos EUA, 16:30 fora dele). Brasilia = servidor - 6 h.
# ----------------------------------------------------------------------------------------------------------------------
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DIR_MT5 = os.path.join(DIR, "mt5")
ARQ_MT5_FIXO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixos", "mt5_calendario_us_830.csv")
DESLOC_SERVIDOR_H = 6                       # horas entre o servidor (UTC+3 fixo) e Brasilia (UTC-3)
# codigo do evento -> (tipo, sinal para o dolar: +1 valor maior = dolar mais forte/juro mais alto; -1 o contrario)
EVENTOS_830 = {
    "nonfarm-payrolls": ("payroll", 1), "private-nonfarm-payrolls": ("payroll", 1), "unemployment-rate": ("payroll", -1),
    "average-hourly-earnings-mm": ("payroll", 1), "average-hourly-earnings-yy": ("payroll", 1),
    "consumer-price-index-mm": ("cpi", 1), "consumer-price-index-ex-food-energy-mm": ("cpi", 1), "consumer-price-index-yy": ("cpi", 1),
    "consumer-price-index-ex-food-energy-yy": ("cpi", 1), "real-earnings-mm": ("cpi", 0),
    "producer-price-index-mm": ("ppi", 1), "producer-price-index-ex-food-energy-mm": ("ppi", 1), "producer-price-index-yy": ("ppi", 1),
    "producer-price-index-ex-food-energy-yy": ("ppi", 1),
    "core-pce-price-index-mm": ("pce", 1), "pce-price-index-mm": ("pce", 1), "core-pce-price-index-yy": ("pce", 1), "pce-price-index-yy": ("pce", 1),
    "personal-spending-mm": ("pce", 1), "personal-income-mm": ("pce", 1),
    "retail-sales-mm": ("varejo", 1), "retail-sales-ex-autos-mm": ("varejo", 1), "retail-control-mm": ("varejo", 1),
    "gross-domestic-product-qq": ("pib", 1), "gross-domestic-product-price-index": ("pib", 1), "gdp-sales-qq": ("pib", 1), "core-pce-price-index-qq": ("pib", 1),
    "initial-jobless-claims": ("claims", -1), "continuing-jobless-claims": ("claims", -1),
    "durable-goods-orders": ("outro", 1), "durable-goods-orders-ex-transportation": ("outro", 1),
    "housing-starts": ("outro", 1), "building-permits": ("outro", 1),
    "philadelphia-fed-manufacturing-index": ("outro", 1), "ny-empire-state-manufacturing-index": ("outro", 1),
    "import-price-index-mm": ("outro", 1), "export-price-index-mm": ("outro", 1), "trade-balance": ("outro", 1),
    "nonfarm-productivity-qq": ("outro", 1), "unit-labor-costs-qq": ("outro", 1),
}
PESO_IMPORTANCIA = {3: 1.0, 2: 0.5, 1: 0.25, 0: 0.0}
PRIORIDADE_MT5 = ("payroll", "cpi", "ppi", "pce", "varejo", "pib", "claims", "outro")
MIN_HIST_Z = 6
JANELA_Z = 24                               # observacoes passadas do mesmo evento usadas na escala (2 anos de dado mensal)
CAP_Z = 4.0


def verao_eua(dia):
    """Horario de verao dos EUA: do 2o domingo de marco ao 1o domingo de novembro (regra de calendario, conhecida de antemao)."""
    d = pd.Timestamp(dia)
    mar = pd.Timestamp(d.year, 3, 1)
    ini = mar + pd.Timedelta(days=(6 - mar.weekday()) % 7 + 7)          # 2o domingo de marco
    nov = pd.Timestamp(d.year, 11, 1)
    fim = nov + pd.Timedelta(days=(6 - nov.weekday()) % 7)              # 1o domingo de novembro
    return ini <= d.normalize() < fim


def marco_brt(dia):
    """Hora de Brasilia em que sai o dado das 8h30 de Nova York no dia: 09:30 no verao dos EUA, 10:30 fora dele."""
    return "09:30" if verao_eua(dia) else "10:30"


def _arquivo_mt5(arq=None):
    if arq:
        return arq
    if os.path.isdir(DIR_MT5):
        brutos = sorted(a for a in os.listdir(DIR_MT5) if a.startswith("autopilot_calendario_US") and a.endswith(".csv"))
        if brutos:
            return os.path.join(DIR_MT5, brutos[-1])
    return ARQ_MT5_FIXO if os.path.exists(ARQ_MT5_FIXO) else None


def carregar_mt5(arq=None):
    """Tabela do calendario do MetaTrader (a exportacao bruta mais nova em dados_brutos/calendario_eua/mt5 ou a copia
    versionada so com o horario das 8h30 em quant/dados/fixos). Vazia quando nao ha arquivo."""
    arq = _arquivo_mt5(arq)
    if not arq:
        return pd.DataFrame()
    enc = "utf-8" if os.path.abspath(arq) == os.path.abspath(ARQ_MT5_FIXO) else "cp1252"
    df = pd.read_csv(arq, sep=";", encoding=enc, dtype=str)
    df["t_servidor"] = pd.to_datetime(df.hora_servidor, format="%Y.%m.%d %H:%M", errors="coerce")
    df["t_brt"] = df.t_servidor - pd.Timedelta(hours=DESLOC_SERVIDOR_H)
    df["dia"] = df.t_brt.dt.normalize()
    df["hora_brt"] = df.t_brt.dt.strftime("%H:%M")
    for c in ("efetivo", "consenso", "anterior", "anterior_revisado"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["importancia"] = pd.to_numeric(df.importancia, errors="coerce").fillna(0).astype(int)
    df["tipo"] = [EVENTOS_830.get(c, ("outro", 0))[0] if c in EVENTOS_830 else "nao_mapeado" for c in df.codigo]
    df["sinal_usd"] = [EVENTOS_830.get(c, ("outro", 0))[1] for c in df.codigo]
    return df.sort_values("t_servidor").reset_index(drop=True)


def eventos_830(df=None):
    """Eventos divulgados no marco das 8h30 de Nova York (09:30 ou 10:30 de Brasilia conforme o verao dos EUA)."""
    df = carregar_mt5() if df is None else df
    if df.empty:
        return df
    marco = df.dia.map(marco_brt)
    return df[df.hora_brt == marco].copy()


def surpresas(df=None):
    """Surpresa de cada evento (efetivo - consenso) e o z contra a escala ROBUSTA das surpresas PASSADAS do mesmo evento:
    1,4826 x mediana de |surpresa| nas ultimas JANELA_Z observacoes anteriores (equivale ao desvio-padrao sem o estrago dos
    meses da pandemia, que no payroll chegam a milhoes), pelo menos MIN_HIST_Z; |z| limitado a CAP_Z. Ponto no tempo."""
    df = eventos_830() if df is None else df
    if df.empty:
        return df
    df = df.copy()
    df["surpresa"] = df.efetivo - df.consenso
    z = pd.Series(np.nan, index=df.index)
    for cod, g in df[df.surpresa.notna()].groupby("codigo"):
        g = g.sort_values("t_servidor")
        s = g.surpresa
        escala = (s.abs().rolling(JANELA_Z, min_periods=MIN_HIST_Z).median().shift(1) * 1.4826).replace(0, np.nan)   # so o passado
        z.loc[g.index] = (s / escala).clip(-CAP_Z, CAP_Z).to_numpy()
    df["z"] = z
    return df


def tabela_surpresa_dia(df=None):
    """Por dia: S = soma de z x sinal_usd x peso(importancia) dos eventos do marco das 8h30 (positivo = surpresa que
    fortalece o dolar), o tipo principal do dia, o evento de maior |z|, o numero de eventos e quantos tinham consenso."""
    df = surpresas(df)
    if df.empty:
        return pd.DataFrame()
    linhas = []
    for dia, g in df.groupby("dia"):
        g2 = g[g.z.notna() & (g.sinal_usd != 0)]
        peso = g2.importancia.map(PESO_IMPORTANCIA).fillna(0)
        S = float((g2.z * g2.sinal_usd * peso).sum()) if len(g2) else np.nan
        tipos = [t for t in PRIORIDADE_MT5 if t in set(g.tipo)]
        principal = g2.loc[g2.z.abs().idxmax()] if len(g2) else None
        linhas.append({"dia": dia, "S": S, "n_eventos": int(len(g)), "n_com_consenso": int(g.consenso.notna().sum()), "n_com_z": int(len(g2)),
                       "tipo_principal": tipos[0] if tipos else "nenhum",
                       "codigo_maior_z": principal.codigo if principal is not None else None,
                       "z_maior": round(float(principal.z * principal.sinal_usd), 2) if principal is not None else np.nan,
                       "surpresa_maior": float(principal.surpresa) if principal is not None else np.nan})
    return pd.DataFrame(linhas).set_index("dia").sort_index()


def gravar_fixo_830(df=None, arq=None):
    """Copia versionada so com os eventos do marco das 8h30 (com consenso ou efetivo), em utf-8, para o repositorio."""
    df = eventos_830(carregar_mt5() if df is None else df)
    cols = ["hora_servidor", "valor_id", "evento_id", "codigo", "nome", "setor", "importancia", "unidade", "digitos", "multiplicador",
            "modo_hora", "frequencia", "efetivo", "consenso", "anterior", "anterior_revisado", "impacto"]
    sel = df[df.efetivo.notna() | df.consenso.notna()][cols]
    os.makedirs(os.path.dirname(arq or ARQ_MT5_FIXO), exist_ok=True)
    sel.to_csv(arq or ARQ_MT5_FIXO, sep=";", index=False, encoding="utf-8")
    return len(sel)


# indicador do terminal (DADOS_ENTREGUES.md) -> (tipo, sinal para o dolar), para o livro cache/out/tempo_real/surpresas.json
INDICADORES_TERMINAL = {"payroll": ("payroll", 1), "desemprego_us": ("payroll", -1), "cpi_mm": ("cpi", 1), "cpi_nucleo_mm": ("cpi", 1),
                        "cpi_12m": ("cpi", 1), "ppi_mm": ("ppi", 1), "pce_nucleo_mm": ("pce", 1), "varejo_us": ("varejo", 1),
                        "pib_us": ("pib", 1), "pedidos_seguro": ("claims", -1), "ism_industria": ("outro", 1), "ism_servicos": ("outro", 1)}


def surpresa_terminal_por_dia(arq=None, min_hist=MIN_HIST_Z):
    """S por dia a partir do livro de surpresas do terminal (itens[indicador] = [dia, consenso, efetivo, surpresa, fonte]), com a
    mesma escala robusta do calendario do MetaTrader (mediana de |surpresa| das JANELA_Z anteriores, |z| <= CAP_Z) e o sinal do
    dolar; sem peso por importancia (o livro nao traz). Serve para os dias que a exportacao do MetaTrader ainda nao cobre."""
    arq = arq or os.path.join(os.path.expanduser(os.environ.get("AUTOPILOT_TERMINAL", "~/Desktop/terminal-artefota".replace("artefota", "artefato"))),
                              "cache", "out", "tempo_real", "surpresas.json")
    try:
        with open(arq, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return pd.DataFrame()
    linhas = []
    for ind, (tipo, sinal) in INDICADORES_TERMINAL.items():
        vals = []
        for it in (d.get("itens") or {}).get(ind) or []:
            try:
                dia, surp = pd.Timestamp(it[0]), it[3]
            except (IndexError, TypeError, ValueError):
                continue
            if surp is None:
                continue
            vals.append((dia.normalize(), float(surp)))
        vals.sort()
        for i, (dia, surp) in enumerate(vals):
            passado = [abs(x) for _, x in vals[max(0, i - JANELA_Z):i]]
            if len(passado) < min_hist:
                continue
            escala = 1.4826 * float(np.median(passado))
            if escala <= 0:
                continue
            linhas.append({"dia": dia, "tipo": tipo, "z": float(np.clip(surp / escala, -CAP_Z, CAP_Z)) * sinal})
    if not linhas:
        return pd.DataFrame()
    df = pd.DataFrame(linhas)
    g = df.groupby("dia")
    return pd.DataFrame({"S": g.z.sum(), "n_com_z": g.size(),
                         "tipo_principal": g.tipo.agg(lambda t: next((p for p in PRIORIDADE_MT5 if p in set(t)), "outro"))}).sort_index()

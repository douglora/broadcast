"""
Proventos e eventos corporativos (M4) e o RETORNO TOTAL forward que eles geram.

Por que existe: o COTAHIST e "preco de tela", sem ajuste. Sem os proventos, um
backtest de valor/dividendos subestima o retorno das pagadoras (ITSA4 rende ~5%/ano so
de proventos) e um desdobramento 1:2 vira um "crash" de -50%. E as series "ajustadas"
dos sites (Yahoo, StatusInvest) sao RE-ESCRITAS para tras a cada evento - o preco de
2015 muda em 2024 - o que quebra a reproducibilidade e esconde look-ahead. Aqui o
ajuste e FORWARD e sem restatement: o retorno da data-ex incorpora o provento/fator
naquele dia e nenhum retorno anterior muda.

Fontes (todas com defeitos conhecidos, por isso a UNIAO delas):
  (a) B3 GetListedCashDividends (por tradingName): dividendos/JCP/rendimentos com
      data-com (lastDatePriorEx), pagamento e valor em decimal BR. So empresas vivas,
      pagina de ~120 itens, repete registros e mistura ON/PN/UNIT (typeStock).
  (b) B3 GetListedSupplementCompany (por issuingCompany): DESDOBRAMENTO, GRUPAMENTO,
      BONIFICACAO, subscricoes e alguns dividendos. TRUNCA as listas (so os ultimos N)
      e repete o mesmo evento por ISIN (ON/PN/UNIT).
  (c) StatusInvest companytickerprovents (por ticker): cobre deslistadas, JCP BRUTO,
      exige User-Agent e Referer. `adj` marca valores ja ajustados por desdobro - aqui
      usamos o nominal original (`sov`) quando existe, porque o ajuste e forward.
  (d) quant/dados/eventos_curados.csv: curadoria manual do que as APIs truncam ou
      omitem (ex.: bonificacao de 10% da SLCE3 em 2023).

Tabela `eventos`: ticker, tipo, data_com, data_ex, valor, fator, data_aprov, fonte, carimbo, obs
  tipo   DIVIDENDO | JCP | RENDIMENTO | DESDOBRAMENTO | GRUPAMENTO | BONIFICACAO | SUBSCRICAO | OUTRO
  valor  provento BRUTO por acao (base: quantidade ANTES do evento); NaN em eventos de quantidade
  fator  multiplicador de quantidade: desdobro 1:2 -> 2.0, grupamento 10:1 -> 0.1,
         bonificacao 10% -> 1.10; NaN em proventos em dinheiro
  data_ex = primeiro pregao apos data_com (calendario.proximo_pregao)

Convencoes do retorno total (retorno_total):
  - na data-ex: ret_total = (fec_t * fator_qtd + provento) / fec_{t-1} - 1; nos demais
    dias ret_total = fec_t / fec_{t-1} - 1; varios eventos na mesma data-ex se compoem
    (fatores multiplicam, proventos somam);
  - o provento e reinvestido no FECHAMENTO da data-ex (convencao; o dinheiro so entra
    na data de pagamento, que pode ser meses depois - viés pequeno e conservador em juros);
  - JCP e bruto; jcp_liquido=True aplica 15% de IR na fonte (pessoa fisica);
  - SUBSCRICAO nao entra no retorno (exigiria o preco do direito); fica registrada.
  - PIT: um evento com data_ex > t nao altera nenhum retorno ate t (sem restatement).
"""
import argparse
import io
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd

from quant.comum import DIR_BANCO, DIR_BRUTOS, agora_brt, agora_iso, garantir_dir, gravar_gzip, http_get, json_b3, log, payload_b3
from quant.dados import calendario
from quant.dados.arquivar_b3 import numero_br

URL_B3_DIVIDENDOS = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetListedCashDividends/{payload}"
URL_B3_SUPLEMENTO = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetListedSupplementCompany/{payload}"
URL_STATUSINVEST = "https://statusinvest.com.br/acao/companytickerprovents?ticker={ticker}&chartProventsType=2"
HEADERS_STATUSINVEST = {"Referer": "https://statusinvest.com.br/", "Accept": "application/json, text/plain, */*",
                        "X-Requested-With": "XMLHttpRequest"}

ARQ_CURADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eventos_curados.csv")
ARQ_PARQUET = os.path.join(DIR_BANCO, "eventos.parquet")
DIR_B3 = os.path.join(DIR_BRUTOS, "b3_proventos")
DIR_SI = os.path.join(DIR_BRUTOS, "statusinvest")

COLUNAS = ["ticker", "tipo", "data_com", "data_ex", "valor", "fator", "data_aprov", "fonte", "carimbo", "obs"]
TIPOS = ("DIVIDENDO", "JCP", "RENDIMENTO", "DESDOBRAMENTO", "GRUPAMENTO", "BONIFICACAO", "SUBSCRICAO", "OUTRO")
TIPOS_DINHEIRO = ("DIVIDENDO", "JCP", "RENDIMENTO")
TIPOS_QUANTIDADE = ("DESDOBRAMENTO", "GRUPAMENTO", "BONIFICACAO")
PRIORIDADE_FONTE = {"b3": 0, "b3_suplemento": 1, "statusinvest": 2, "curadoria": 3}
IR_JCP = 0.15

# sufixo do ticker -> classe, e classe -> trecho do ISIN (posicoes 6-10: ACNOR, ACNPR, CDAM...)
CLASSE_SUFIXO = {"3": "ON", "4": "PN", "5": "PNA", "6": "PNB", "7": "PNC", "8": "PND", "11": "UNT"}
CLASSE_ISIN = {"ACNOR": "ON", "ACNPR": "PN", "ACNPA": "PNA", "ACNPB": "PNB", "ACNPC": "PNC", "ACNPD": "PND",
               "CDAM": "UNT", "CTF": "UNT"}


# ─────────────────────────────────────────────────────────────
# Utilitarios puros
# ─────────────────────────────────────────────────────────────
def data_br(s):
    """'27/04/2023', '2023-04-27', '2023-04-27T00:00:00' ou vazio -> Timestamp/NaT."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return pd.NaT
    s = str(s).strip()
    if not s or s.lower() in ("nan", "nat", "none", "-"):
        return pd.NaT
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%Y%m%d"):
        try:
            return pd.Timestamp(datetime.strptime(s[:10], fmt))
        except ValueError:
            continue
    return pd.NaT


def valor_num(v):
    """Numero de JSON: float/int passam direto; texto usa numero_br ('1.234,56' -> 1234.56)."""
    if v is None or isinstance(v, bool):
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    return numero_br(v)


def data_ex_de(data_com):
    """Primeiro pregao apos a data-com. NaT -> NaT."""
    ts = data_br(data_com) if not isinstance(data_com, pd.Timestamp) else data_com
    if pd.isna(ts):
        return pd.NaT
    return pd.Timestamp(calendario.proximo_pregao(ts.date()))


def classe_do_ticker(ticker):
    """'PETR4' -> 'PN'; 'SANB11' -> 'UNT'; 'VALE3' -> 'ON'; desconhecido -> None."""
    from quant.dados.identidade import sufixo
    return CLASSE_SUFIXO.get(sufixo(ticker) or "")


def classe_do_isin(isin):
    s = str(isin or "").strip().upper()
    if len(s) < 11:
        return None
    for trecho, classe in CLASSE_ISIN.items():
        if s[6:].startswith(trecho):
            return classe
    return None


def _casa_classe(classe_evento, ticker):
    """True se o evento (typeStock/ISIN) e da classe do ticker; eventos sem classe casam sempre."""
    if not classe_evento:
        return True
    alvo = classe_do_ticker(ticker)
    if alvo is None:
        return True
    # a B3 costuma concatenar o segmento ("ON NM", "PN N2", "UNT N2"): so o primeiro token e a classe
    partes = str(classe_evento).strip().upper().split()
    ce = partes[0] if partes else ""
    if ce.startswith("UNIT") or ce == "UNT":
        ce = "UNT"
    return ce == alvo


def tipo_de(label):
    """Rotulo da fonte -> tipo canonico."""
    s = unicodedata.normalize("NFKD", str(label or "")).encode("ascii", "ignore").decode().strip().upper()
    s = "".join(c for c in s if c.isalnum() or c == " ")
    if not s:
        return "OUTRO"
    if "JRS" in s or "JUROS" in s or "JCP" in s or "CAP PROPRIO" in s or "CAPITAL PROPRIO" in s:
        return "JCP"
    if "BONIFIC" in s or ("DIVIDEND" in s and "ACOES" in s):
        return "BONIFICACAO"          # "DIVIDENDO EM ACOES" e bonificacao (quantidade), nao dinheiro
    if "DIVIDENDO" in s:
        return "DIVIDENDO"
    if "RENDIMENTO" in s or "AMORTIZ" in s or "RESTITUI" in s or "TRIBUTADO" in s:
        return "RENDIMENTO"           # dinheiro sem IR na fonte de JCP: restituicao de capital, rendimento tributado
    if "DESDOBRAMENTO" in s or "DESDOBRO" in s or "SPLIT" in s:
        return "DESDOBRAMENTO"
    if "GRUPAMENTO" in s or "INPLIT" in s:
        return "GRUPAMENTO"
    if "BONIFIC" in s:
        return "BONIFICACAO"
    if "SUBSCRI" in s or "PRIORIDADE" in s:
        return "SUBSCRICAO"
    return "OUTRO"


def fator_de(tipo, factor):
    """Campo `factor` do suplemento da B3 -> multiplicador de quantidade.

    SUPOSICAO (validar com rede): a B3 informa o factor como PERCENTUAL sobre a posicao:
    DESDOBRAMENTO 100 -> 1:2 (fator 2.0), MGLU3 2019 700 -> 1:8; BONIFICACAO 10 -> 1.10.
    Para GRUPAMENTO a convencao percentual da o percentual RETIRADO (90 -> 0.10); um valor
    < 1 e tratado como multiplicador pronto (0.1 -> 0.10) e um valor >= 100 como razao N:1
    (100 -> 0.01), porque 100% retirado nao existe. A validacao com rede deve comparar o
    fator com o salto do preco no COTAHIST na data-ex (ex.: IRBR3 30:1 em 2023).
    """
    f = valor_num(factor)
    if math.isnan(f):
        return float("nan")
    if tipo == "DESDOBRAMENTO":
        return 1.0 + f / 100.0 if f >= 1 else float("nan")
    if tipo == "BONIFICACAO":
        return 1.0 + f / 100.0
    if tipo == "GRUPAMENTO":
        if f <= 0:
            return float("nan")
        if f < 1:
            return f
        return 1.0 - f / 100.0 if f < 100 else 1.0 / f
    return float("nan")


def _montar(linhas):
    df = pd.DataFrame(linhas, columns=COLUNAS)
    for c in ("data_com", "data_ex", "data_aprov"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["fator"] = pd.to_numeric(df["fator"], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.upper()
    return df


def _tabela_vazia():
    return _montar([])


def _resultados(obj):
    """Os proxies da B3 devolvem {'results': [...]} ou uma lista; aceita string JSON tambem."""
    if obj is None:
        return []
    if isinstance(obj, (str, bytes)):
        try:
            obj = json_b3(obj if isinstance(obj, str) else obj.decode("utf-8"))
        except Exception:
            return []
    if isinstance(obj, dict):
        return obj.get("results") or obj.get("Results") or []
    if isinstance(obj, list):
        return obj
    return []


# ─────────────────────────────────────────────────────────────
# Normalizadores (puros)
# ─────────────────────────────────────────────────────────────
def normalizar_b3_dividendos(obj, ticker, carimbo=None):
    """JSON de GetListedCashDividends -> tabela `eventos` do ticker.

    A resposta e por EMPRESA e mistura classes em typeStock ('ON', 'PN', 'UNIT'...); ficam so
    as linhas cuja classe casa com o sufixo do ticker (3=ON, 4=PN, 11=UNIT). Linhas sem
    data-com sao descartadas. Duplicatas exatas sao removidas.
    """
    carimbo = carimbo or agora_iso()
    linhas = []
    for r in _resultados(obj):
        if not isinstance(r, dict):
            continue
        if not _casa_classe(r.get("typeStock"), ticker):
            continue
        data_com = data_br(r.get("lastDatePriorEx") or r.get("lastDatePrior"))
        if pd.isna(data_com):
            continue
        valor = valor_num(r.get("valueCash", r.get("rate")))
        if math.isnan(valor):
            continue
        linhas.append({
            "ticker": ticker, "tipo": tipo_de(r.get("label")), "data_com": data_com,
            "data_ex": data_ex_de(data_com), "valor": valor, "fator": float("nan"),
            "data_aprov": data_br(r.get("dateApproval") or r.get("approvedOn")), "fonte": "b3",
            "carimbo": carimbo,
            "obs": "; ".join(x for x in (str(r.get("relatedTo") or "").strip(),
                                         f"pagamento {r.get('paymentDate')}" if r.get("paymentDate") else "") if x),
        })
    df = _montar(linhas)
    return df.drop_duplicates(["ticker", "tipo", "data_ex", "valor"]).reset_index(drop=True)


def normalizar_b3_suplemento(obj, ticker, carimbo=None):
    """JSON de GetListedSupplementCompany -> tabela `eventos` do ticker.

    Le stockDividends (DESDOBRAMENTO/GRUPAMENTO/BONIFICACAO com `factor`), cashDividends
    (com `rate`) e subscriptions (`priceUnit`, `percentage`). A B3 repete cada evento por
    classe (assetIssued = ISIN): ficam so os ISINs da classe do ticker. Lembre que a lista
    e TRUNCADA pela B3 - por isso existe eventos_curados.csv.
    """
    carimbo = carimbo or agora_iso()
    if isinstance(obj, (str, bytes)):
        try:
            obj = json_b3(obj if isinstance(obj, str) else obj.decode("utf-8"))
        except Exception:
            return _tabela_vazia()
    res = _resultados(obj)
    if isinstance(obj, dict) and not res:
        res = [obj]
    linhas = []
    for bloco in res:
        if not isinstance(bloco, dict):
            continue
        for r in bloco.get("stockDividends") or []:
            if not _casa_classe(classe_do_isin(r.get("assetIssued") or r.get("isinCode")), ticker):
                continue
            data_com = data_br(r.get("lastDatePrior"))
            if pd.isna(data_com):
                continue
            tipo = tipo_de(r.get("label"))
            linhas.append({
                "ticker": ticker, "tipo": tipo, "data_com": data_com, "data_ex": data_ex_de(data_com),
                "valor": float("nan"), "fator": fator_de(tipo, r.get("factor")),
                "data_aprov": data_br(r.get("approvedOn")), "fonte": "b3_suplemento", "carimbo": carimbo,
                "obs": f"factor={r.get('factor')}; {r.get('remarks') or ''}".strip("; "),
            })
        for r in bloco.get("cashDividends") or []:
            if not _casa_classe(classe_do_isin(r.get("assetIssued") or r.get("isinCode")), ticker):
                continue
            data_com = data_br(r.get("lastDatePrior") or r.get("lastDatePriorEx"))
            valor = valor_num(r.get("rate", r.get("valueCash")))
            if pd.isna(data_com) or math.isnan(valor):
                continue
            linhas.append({
                "ticker": ticker, "tipo": tipo_de(r.get("label")), "data_com": data_com,
                "data_ex": data_ex_de(data_com), "valor": valor, "fator": float("nan"),
                "data_aprov": data_br(r.get("approvedOn")), "fonte": "b3_suplemento", "carimbo": carimbo,
                "obs": str(r.get("relatedTo") or "").strip(),
            })
        for r in bloco.get("subscriptions") or []:
            if not _casa_classe(classe_do_isin(r.get("assetIssued") or r.get("isinCode")), ticker):
                continue
            data_com = data_br(r.get("lastDatePrior"))
            if pd.isna(data_com):
                continue
            linhas.append({
                "ticker": ticker, "tipo": "SUBSCRICAO", "data_com": data_com, "data_ex": data_ex_de(data_com),
                "valor": valor_num(r.get("priceUnit")), "fator": float("nan"),
                "data_aprov": data_br(r.get("approvedOn")), "fonte": "b3_suplemento", "carimbo": carimbo,
                "obs": f"percentual={r.get('percentage')}; periodo={r.get('tradingPeriod')}; {r.get('remarks') or ''}".strip("; "),
            })
    df = _montar(linhas)
    return df.drop_duplicates(["ticker", "tipo", "data_ex", "valor", "fator"]).reset_index(drop=True)


def normalizar_statusinvest(obj, ticker, carimbo=None):
    """JSON de companytickerprovents -> tabela `eventos` do ticker.

    Campos: ed (data-com), pd (pagamento), et ('Dividendo'|'JCP'|'Rendimento'...), v (valor,
    ja ajustado quando adj=True), sov (valor nominal original). Usa sov quando adj e True e sov
    existe, senao v - porque o ajuste aqui e forward e o preco do COTAHIST e nominal.
    """
    carimbo = carimbo or agora_iso()
    if isinstance(obj, (str, bytes)):
        try:
            obj = json.loads(obj)
        except Exception:
            return _tabela_vazia()
    itens = obj.get("assetEarningsModels") if isinstance(obj, dict) else obj
    linhas = []
    for r in itens or []:
        if not isinstance(r, dict):
            continue
        data_com = data_br(r.get("ed"))
        if pd.isna(data_com):
            continue
        valor = valor_num(r.get("v"))
        if r.get("adj") and r.get("sov") not in (None, "", 0):
            nominal = valor_num(r.get("sov"))
            if not math.isnan(nominal):
                valor = nominal
        if math.isnan(valor):
            continue
        tipo = tipo_de(r.get("et") or r.get("etd"))
        if tipo == "OUTRO" and str(r.get("et") or "").upper().startswith("JCP"):
            tipo = "JCP"
        linhas.append({
            "ticker": ticker, "tipo": tipo, "data_com": data_com, "data_ex": data_ex_de(data_com),
            "valor": valor, "fator": float("nan"), "data_aprov": pd.NaT, "fonte": "statusinvest",
            "carimbo": carimbo,
            "obs": "; ".join(x for x in (str(r.get("etd") or "").strip(),
                                         f"pagamento {r.get('pd')}" if r.get("pd") else "") if x),
        })
    df = _montar(linhas)
    return df.drop_duplicates(["ticker", "tipo", "data_ex", "valor"]).reset_index(drop=True)


def _num_ponto(v):
    """Numero do CSV curado: ponto decimal ('1.10', '2.000' = 2.0). Virgula e aceita ('1,10'),
    mas ponto NUNCA e milhar aqui - numero_br leria '2.000' como 2000."""
    s = str(v or "").strip()
    if not s:
        return float("nan")
    try:
        return float(s.replace(",", ".") if "," in s and "." not in s else s)
    except ValueError:
        return float("nan")


def carregar_curados(caminho=ARQ_CURADOS):
    """eventos_curados.csv (';', ponto decimal, datas AAAA-MM-DD; linhas iniciadas por '#' sao
    comentario - nao use '#' dentro de obs) -> tabela `eventos`."""
    if not os.path.exists(caminho):
        return _tabela_vazia()
    with open(caminho, encoding="utf-8") as f:
        texto = "\n".join(l for l in f.read().splitlines() if l.strip() and not l.lstrip().startswith("#"))
    if not texto.strip():
        return _tabela_vazia()
    df = pd.read_csv(io.StringIO(texto), sep=";", dtype=str, keep_default_na=False)
    if df.empty:
        return _tabela_vazia()
    linhas = []
    for r in df.to_dict("records"):
        data_com = data_br(r.get("data_com"))
        data_ex = data_br(r.get("data_ex"))
        if pd.isna(data_ex):
            data_ex = data_ex_de(data_com)
        if pd.isna(data_com) and pd.notna(data_ex):
            data_com = pd.Timestamp(calendario.pregao_anterior(data_ex.date()))
        linhas.append({
            "ticker": str(r.get("ticker", "")).upper(), "tipo": tipo_de(r.get("tipo")),
            "data_com": data_com, "data_ex": data_ex,
            "valor": _num_ponto(r.get("valor")),
            "fator": _num_ponto(r.get("fator")),
            "data_aprov": data_br(r.get("data_aprov")), "fonte": r.get("fonte") or "curadoria",
            "carimbo": r.get("carimbo") or "", "obs": r.get("obs") or "",
        })
    return _montar(linhas)


def consolidar(*dfs, tolerancia=0.005):
    """Uniao das fontes sem duplicar.

    Chave: (ticker, tipo, data_ex, valor arredondado em 4 casas, fator em 4 casas). Em
    empate fica a fonte de maior prioridade (b3 > b3_suplemento > statusinvest > curadoria).
    Segunda passada: mesmo (ticker, tipo, data_ex) com valores a menos de `tolerancia`
    (relativa) tambem e duplicata - a B3 arredonda diferente do StatusInvest.
    """
    partes = [d for d in dfs if d is not None and len(d)]
    if not partes:
        return _tabela_vazia()
    df = pd.concat(partes, ignore_index=True)
    for c in COLUNAS:
        if c not in df.columns:
            df[c] = np.nan
    df = _montar(df.to_dict("records"))
    df["_prio"] = df["fonte"].map(PRIORIDADE_FONTE).fillna(9)
    df["_v4"] = df["valor"].round(4)
    df["_f4"] = df["fator"].round(4)
    df = df.sort_values(["ticker", "tipo", "data_ex", "_prio"], kind="stable")
    df = df.drop_duplicates(["ticker", "tipo", "data_ex", "_v4", "_f4"], keep="first")
    # segunda passada: mesmo evento com arredondamento diferente entre fontes
    manter = []
    for _, g in df.groupby(["ticker", "tipo", "data_ex"], sort=False, dropna=False):
        aceitos = []
        for r in g.itertuples():
            dup = False
            for a in aceitos:
                v_ok = (pd.isna(r.valor) and pd.isna(a.valor)) or (
                    pd.notna(r.valor) and pd.notna(a.valor) and abs(r.valor - a.valor) <= tolerancia * max(abs(a.valor), 1e-9))
                f_ok = (pd.isna(r.fator) and pd.isna(a.fator)) or (
                    pd.notna(r.fator) and pd.notna(a.fator) and abs(r.fator - a.fator) <= tolerancia * abs(a.fator))
                if v_ok and f_ok:
                    dup = True
                    break
            if not dup:
                aceitos.append(r)
                manter.append(r.Index)
    df = df.loc[manter, COLUNAS].sort_values(["ticker", "data_ex", "tipo"]).reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────
# Retorno total forward
# ─────────────────────────────────────────────────────────────
def _agregar_por_data_ex(ev, jcp_liquido):
    """eventos de um ticker -> DataFrame(data_ex, fator_qtd, provento)."""
    e = ev[ev["data_ex"].notna()].copy()
    if e.empty:
        return pd.DataFrame(columns=["data_ex", "fator_qtd", "provento"])
    e["_f"] = np.where(e["tipo"].isin(TIPOS_QUANTIDADE), e["fator"].fillna(1.0), 1.0)
    e.loc[e["tipo"].isin(TIPOS_QUANTIDADE) & (e["_f"] <= 0), "_f"] = 1.0
    prov = e["valor"].where(e["tipo"].isin(TIPOS_DINHEIRO), 0.0).fillna(0.0)
    if jcp_liquido:
        prov = prov.where(e["tipo"] != "JCP", prov * (1 - IR_JCP))
    e["_p"] = prov
    g = e.groupby("data_ex").agg(fator_qtd=("_f", "prod"), provento=("_p", "sum")).reset_index()
    return g


def retorno_total(precos, eventos, jcp_liquido=False):
    """Retorno diario de preco e retorno total forward por ticker.

    precos: colunas ticker, data, fec (COTAHIST). eventos: tabela `eventos` (pode ser vazia).
    Devolve DataFrame(ticker, data, ret_preco, ret_total, fator_acum), ordenado por ticker/data;
    fator_acum e o indice de retorno total com base 1.0 no primeiro pregao da serie.

    Regra: na data-ex, ret_total = (fec_t * fator_qtd + provento) / fec_{t-1} - 1, com o
    provento por acao na quantidade ANTES do evento; varios eventos na mesma data-ex se
    compoem. Se a data-ex nao tem cotacao (papel sem negocio), o evento e aplicado no
    primeiro pregao com preco depois dela. Eventos alem do ultimo preco sao ignorados.
    Preco <= 0 ou ausente e tratado como "sem pregao": o retorno daquele dia e NaN, o dia
    seguinte com preco usa o ultimo preco VALIDO como base e um evento cuja data-ex caiu no
    dia sem preco e aplicado nesse proximo dia (mesma regra da data-ex sem linha). fator_acum
    trata NaN como retorno zero - convencao, nao dado.
    """
    cols = ["ticker", "data", "ret_preco", "ret_total", "fator_acum"]
    if precos is None or len(precos) == 0:
        return pd.DataFrame(columns=cols)
    p = pd.DataFrame({
        "ticker": precos["ticker"].astype(str).str.upper(),
        "data": pd.to_datetime(precos["data"]),
        "fec": pd.to_numeric(precos["fec"], errors="coerce"),
    }).sort_values(["ticker", "data"]).drop_duplicates(["ticker", "data"], keep="last")
    ev = eventos if eventos is not None and len(eventos) else _tabela_vazia()
    ev = ev.assign(ticker=ev["ticker"].astype(str).str.upper(), data_ex=pd.to_datetime(ev["data_ex"]))
    partes = []
    for ticker, g in p.groupby("ticker", sort=True):
        g = g.reset_index(drop=True)
        fec = g["fec"].values.astype(float)
        fec[~(fec > 0)] = np.nan                   # preco zero/negativo/ausente nao e preco
        validos = np.flatnonzero(~np.isnan(fec))   # so dias com preco recebem eventos e servem de base
        fator_qtd = np.ones(len(g))
        provento = np.zeros(len(g))
        ag = _agregar_por_data_ex(ev[ev["ticker"] == ticker], jcp_liquido)
        if len(ag) and len(validos):
            datas = g["data"].values[validos]
            pos = np.searchsorted(datas, ag["data_ex"].values, side="left")
            for i, fq, pv in zip(pos, ag["fator_qtd"].values, ag["provento"].values):
                if i >= len(validos):
                    continue                       # data-ex depois do ultimo preco: ainda nao aconteceu
                fator_qtd[validos[i]] *= fq
                provento[validos[i]] += pv
        # base do retorno = ultimo preco VALIDO anterior (um dia sem preco e como um dia sem pregao)
        fec_ant = np.full(len(g), np.nan)
        if len(validos) > 1:
            fec_ant[validos[1:]] = fec[validos[:-1]]
        with np.errstate(divide="ignore", invalid="ignore"):
            ret_preco = fec / fec_ant - 1.0
            ret_total = (fec * fator_qtd + provento) / fec_ant - 1.0
        ret_preco[~np.isfinite(ret_preco)] = np.nan
        ret_total[~np.isfinite(ret_total)] = np.nan
        fator_acum = np.cumprod(np.where(np.isnan(ret_total), 0.0, ret_total) + 1.0)
        partes.append(pd.DataFrame({"ticker": ticker, "data": g["data"], "ret_preco": ret_preco,
                                    "ret_total": ret_total, "fator_acum": fator_acum}))
    if not partes:
        return pd.DataFrame(columns=cols)
    return pd.concat(partes, ignore_index=True)[cols]


# ─────────────────────────────────────────────────────────────
# Rede (tolerante) e banco
# ─────────────────────────────────────────────────────────────
def _guardar_bruto(pasta, nome, texto):
    nome = re.sub(r"[^A-Za-z0-9_-]+", "_", str(nome)).strip("_") or "sem_nome"
    garantir_dir(pasta)
    gravar_gzip(os.path.join(pasta, f"{nome}_{agora_brt():%Y%m%d}.json.gz"), texto)


def baixar_b3_dividendos(trading_name, page_size=120, max_paginas=30):
    """GetListedCashDividends por nome de pregao (ex.: 'PETROBRAS'). Devolve {'results': [...]} ou None.
    Percorre as paginas ate esgotar; o bruto vai para dados_brutos/b3_proventos."""
    todos, pagina = [], 1
    while pagina <= max_paginas:
        payload = payload_b3({"language": "pt-br", "pageNumber": pagina, "pageSize": page_size,
                              "tradingName": trading_name})
        r = http_get(URL_B3_DIVIDENDOS.format(payload=payload))
        if r is None:
            return None if not todos else {"results": todos}
        try:
            obj = json_b3(r.text)
        except Exception:
            log(f"b3 dividendos {trading_name}: JSON invalido")
            return None if not todos else {"results": todos}
        res = obj.get("results", []) if isinstance(obj, dict) else []
        todos.extend(res)
        total = int(((obj.get("page") or {}).get("totalPages") or 1) if isinstance(obj, dict) else 1)
        if pagina >= total or not res:
            break
        pagina += 1
    out = {"results": todos, "tradingName": trading_name, "capturado_em": agora_iso()}
    _guardar_bruto(DIR_B3, f"dividendos_{trading_name}", json.dumps(out, ensure_ascii=False))
    return out


def baixar_b3_suplemento(issuing_company):
    """GetListedSupplementCompany por codigo de emissor (ex.: 'PETR'). Devolve o JSON (lista) ou None."""
    payload = payload_b3({"issuingCompany": issuing_company, "language": "pt-br"})
    r = http_get(URL_B3_SUPLEMENTO.format(payload=payload))
    if r is None:
        return None
    try:
        obj = json_b3(r.text)
    except Exception:
        log(f"b3 suplemento {issuing_company}: JSON invalido")
        return None
    _guardar_bruto(DIR_B3, f"suplemento_{issuing_company}", json.dumps(obj, ensure_ascii=False))
    return obj


def baixar_statusinvest(ticker):
    """companytickerprovents do StatusInvest (exige User-Agent + Referer). JSON ou None."""
    r = http_get(URL_STATUSINVEST.format(ticker=ticker.lower()), headers=HEADERS_STATUSINVEST)
    if r is None:
        return None
    try:
        obj = r.json()
    except Exception:
        log(f"statusinvest {ticker}: JSON invalido (provavel bloqueio/captcha)")
        return None
    _guardar_bruto(DIR_SI, f"proventos_{ticker.upper()}", json.dumps(obj, ensure_ascii=False))
    return obj


def baixar_eventos(ticker, trading_name=None, issuing_company=None):
    """Baixa as tres fontes para um ticker e consolida com a curadoria. Nunca levanta."""
    carimbo = agora_iso()
    partes = []
    if trading_name:
        obj = baixar_b3_dividendos(trading_name)
        if obj is not None:
            partes.append(normalizar_b3_dividendos(obj, ticker, carimbo))
    emissor = issuing_company or ticker[:4]
    obj = baixar_b3_suplemento(emissor)
    if obj is not None:
        partes.append(normalizar_b3_suplemento(obj, ticker, carimbo))
    obj = baixar_statusinvest(ticker)
    if obj is not None:
        partes.append(normalizar_statusinvest(obj, ticker, carimbo))
    cur = carregar_curados()
    partes.append(cur[cur["ticker"] == ticker.upper()])
    return consolidar(*partes)


def gravar_eventos(df, caminho=ARQ_PARQUET):
    garantir_dir(os.path.dirname(caminho))
    df[COLUNAS].to_parquet(caminho, index=False)
    return caminho


def carregar_eventos(caminho=ARQ_PARQUET):
    if not os.path.exists(caminho):
        return _tabela_vazia()
    return pd.read_parquet(caminho)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Baixa proventos/eventos de um ticker e mostra a tabela consolidada")
    ap.add_argument("ticker")
    ap.add_argument("--nome", default=None, help="tradingName na B3 (ex.: PETROBRAS)")
    ap.add_argument("--emissor", default=None, help="issuingCompany na B3 (ex.: PETR)")
    args = ap.parse_args(argv)
    df = baixar_eventos(args.ticker.upper(), args.nome, args.emissor)
    print(df.to_string())
    return 0 if len(df) else 1


if __name__ == "__main__":
    sys.exit(main())

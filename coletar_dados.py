#!/usr/bin/env python3
"""
Coleta dados de ativos da B3 para a mesa de analise do Claude.

Roda no GitHub Actions (workflow coletar-dados.yml), que tem internet aberta,
e grava JSONs no branch `dados` deste repositorio. O Claude, numa sessao na
nuvem sem acesso direto as fontes, le esses JSONs por raw.githubusercontent.com:

    https://raw.githubusercontent.com/douglora/broadcast/dados/ativos/PETR4.json
    https://raw.githubusercontent.com/douglora/broadcast/dados/snapshot/tesouro.json

Uso:
    python coletar_dados.py --tickers PETR4,VALE3 --saida dados_out
    python coletar_dados.py --snapshot --saida dados_out        # retrato geral do terminal
    python coletar_dados.py --saida dados_out                    # lista padrao (modelo de TIR)

Fontes por ativo: Yahoo Finance via yfinance (cotacao, historico, demonstracoes,
dividendos, consenso de analistas), Fundamentus (indicadores no padrao
brasileiro), CVM dados abertos (fatos relevantes e comunicados), Banco Central
(Selic, IPCA, dolar) e o modelo de TIR real deste repositorio. Cada fonte falha
sozinha: o JSON registra o que respondeu e o que nao.
"""

import argparse
import csv
import html as htmlmod
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import requests  # noqa: E402

import app  # noqa: E402  (reaproveita http_get, IPE_URL, sgs_fetch)
import tir_real_servidor as TIR  # noqa: E402

UA = app.UA
GENERICAS = {"S", "A", "SA", "S.A.", "S/A", "HOLDING", "PARTICIPACOES", "CIA", "COMPANHIA",
             "DO", "DA", "DE", "DOS", "DAS", "E", "ON", "PN", "N1", "N2", "NM", "UNT", "BCO", "BANCO"}


def agora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nativo(v):
    """Converte numpy/pandas em tipos JSON; NaN vira None."""
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            v = float(v)
    except Exception:
        pass
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if hasattr(v, "isoformat"):
        try:
            return v.strftime("%Y-%m-%d")
        except Exception:
            return str(v)
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return str(v)


def df_para_dict(df, max_colunas=8):
    """DataFrame de demonstracoes (linhas x periodos) -> {linha: {periodo: valor}}."""
    if df is None or getattr(df, "empty", True):
        return {}
    out = {}
    cols = list(df.columns)[:max_colunas]
    for linha in df.index:
        item = {}
        for c in cols:
            val = nativo(df.at[linha, c])
            if val is not None:
                item[nativo(c)] = val
        if item:
            out[str(linha)] = item
    return out


def normalizar(texto):
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9 ]+", " ", t.upper())
    return re.sub(r"\s+", " ", t).strip()


def nucleo_nome(nome):
    """'Banco do Brasil S.A.' -> 'BCO BRASIL'; 'Petróleo Brasileiro S.A. - Petrobras' -> 'PETROLEO BRASILEIRO PETROBRAS'."""
    palavras = [p for p in normalizar(nome).split() if p not in GENERICAS]
    return " ".join(palavras)


# ───────────────────────── Yahoo Finance ─────────────────────────
CAMPOS_INFO = [
    "longName", "shortName", "sector", "industry", "website", "longBusinessSummary",
    "fullTimeEmployees", "currency", "exchange", "currentPrice", "regularMarketPrice",
    "previousClose", "open", "dayLow", "dayHigh", "fiftyTwoWeekLow", "fiftyTwoWeekHigh",
    "fiftyDayAverage", "twoHundredDayAverage", "averageVolume", "averageVolume10days",
    "marketCap", "enterpriseValue", "sharesOutstanding", "floatShares", "beta",
    "trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months",
    "enterpriseToRevenue", "enterpriseToEbitda", "dividendYield", "trailingAnnualDividendRate",
    "trailingAnnualDividendYield", "payoutRatio", "fiveYearAvgDividendYield",
    "returnOnEquity", "returnOnAssets", "profitMargins", "grossMargins", "ebitdaMargins",
    "operatingMargins", "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
    "totalRevenue", "ebitda", "netIncomeToCommon", "totalDebt", "totalCash", "debtToEquity",
    "currentRatio", "freeCashflow", "operatingCashflow", "trailingEps", "forwardEps",
    "bookValue", "recommendationKey", "recommendationMean", "numberOfAnalystOpinions",
    "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice",
    "earningsTimestamp", "exDividendDate", "lastDividendValue", "lastDividendDate",
]


def eh_simbolo_us(tk):
    """Ticker so com letras (ate 5) e um papel dos EUA, ex.: MELI, AAPL."""
    return tk.isalpha() and 1 <= len(tk) <= 5


def eh_bdr(tk):
    """BDR da B3: 4 letras + 32..39, ex.: MELI34, AAPL34, GOGL35."""
    return re.fullmatch(r"[A-Z]{4}3[2-9]", tk) is not None


def coletar_yahoo(tk, fontes, simbolo=None):
    import yfinance as yf
    simbolo = simbolo or (tk if eh_simbolo_us(tk) else f"{tk}.SA")
    t = yf.Ticker(simbolo)
    dados = {"simbolo": simbolo}

    try:
        info = t.info or {}
        dados["info"] = {k: nativo(info.get(k)) for k in CAMPOS_INFO if info.get(k) is not None}
        fontes["yahoo_info"] = "ok" if dados["info"] else "vazio"
    except Exception as e:
        fontes["yahoo_info"] = f"falha: {type(e).__name__}: {e}"[:160]
        dados["info"] = {}

    try:
        h = t.history(period="1y", interval="1d", auto_adjust=False)
        fech = [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in h["Close"].dropna().items()]
        dados["historico"] = {"fechamentos_diarios": fech}
        if fech:
            ultimo = fech[-1][1]
            def ret(n):
                if len(fech) > n and fech[-1 - n][1]:
                    return round(ultimo / fech[-1 - n][1] - 1, 4)
                return None
            ano = fech[-1][0][:4]
            ytd_base = next((c for d, c in fech if d.startswith(ano)), None)
            dados["retornos"] = {
                "1m": ret(21), "3m": ret(63), "6m": ret(126),
                "12m": round(ultimo / fech[0][1] - 1, 4) if fech[0][1] else None,
                "ytd": round(ultimo / ytd_base - 1, 4) if ytd_base else None,
                "max_52s": round(max(c for _, c in fech), 4),
                "min_52s": round(min(c for _, c in fech), 4),
                "ultimo_fechamento": {"data": fech[-1][0], "preco": ultimo},
            }
        fontes["yahoo_historico"] = f"ok ({len(fech)} pregoes)"
    except Exception as e:
        fontes["yahoo_historico"] = f"falha: {type(e).__name__}: {e}"[:160]

    try:
        div = t.dividends
        corte = datetime.now(timezone.utc) - timedelta(days=730)
        itens = []
        for d, v in div.items():
            d2 = d.to_pydatetime()
            if d2.tzinfo is None:
                d2 = d2.replace(tzinfo=timezone.utc)
            if d2 >= corte:
                itens.append({"data": d2.strftime("%Y-%m-%d"), "valor": round(float(v), 6)})
        soma12 = sum(i["valor"] for i in itens
                     if datetime.strptime(i["data"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                     >= datetime.now(timezone.utc) - timedelta(days=365))
        dados["dividendos"] = {"ultimos_24m": itens, "soma_12m_por_acao": round(soma12, 6)}
        fontes["yahoo_dividendos"] = f"ok ({len(itens)} eventos em 24m)"
    except Exception as e:
        fontes["yahoo_dividendos"] = f"falha: {type(e).__name__}: {e}"[:160]

    demonstracoes = {}
    for nome, attr in (("dre_anual", "income_stmt"), ("dre_trimestral", "quarterly_income_stmt"),
                       ("balanco_anual", "balance_sheet"), ("balanco_trimestral", "quarterly_balance_sheet"),
                       ("caixa_anual", "cashflow"), ("caixa_trimestral", "quarterly_cashflow")):
        try:
            demonstracoes[nome] = df_para_dict(getattr(t, attr))
            n = len(demonstracoes[nome])
            fontes[f"yahoo_{nome}"] = f"ok ({n} linhas)" if n else "vazio"
        except Exception as e:
            fontes[f"yahoo_{nome}"] = f"falha: {type(e).__name__}: {e}"[:160]
    dados["demonstracoes"] = demonstracoes

    consenso = {}
    try:
        alvo = t.analyst_price_targets
        if alvo:
            consenso["preco_alvo"] = {k: nativo(v) for k, v in dict(alvo).items()}
    except Exception as e:
        fontes["yahoo_preco_alvo"] = f"falha: {type(e).__name__}"
    try:
        rec = t.recommendations
        if rec is not None and not rec.empty:
            consenso["recomendacoes"] = [{k: nativo(v) for k, v in row.items()}
                                         for row in rec.to_dict("records")]
    except Exception as e:
        fontes["yahoo_recomendacoes"] = f"falha: {type(e).__name__}"
    info = dados.get("info", {})
    for k in ("recommendationKey", "recommendationMean", "numberOfAnalystOpinions",
              "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice"):
        if info.get(k) is not None:
            consenso[k] = info[k]
    dados["consenso"] = consenso
    fontes["yahoo_consenso"] = "ok" if consenso else "vazio"

    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            hoje = datetime.now(timezone.utc)
            prox = [nativo(d) for d in ed.index if d.to_pydatetime().replace(tzinfo=timezone.utc) >= hoje]
            dados["eventos"] = {"datas_de_resultado": sorted(set(prox))[:4]}
            fontes["yahoo_eventos"] = "ok"
    except Exception as e:
        fontes["yahoo_eventos"] = f"falha: {type(e).__name__}"

    try:
        noticias = []
        for n in (t.news or [])[:12]:
            c = n.get("content") or n
            titulo = c.get("title")
            link = ((c.get("canonicalUrl") or {}).get("url")) or c.get("link")
            fonte = ((c.get("provider") or {}).get("displayName")) or c.get("publisher")
            data = c.get("pubDate") or c.get("providerPublishTime")
            if titulo:
                noticias.append({"titulo": titulo, "fonte": fonte, "data": nativo(data), "link": link})
        dados["noticias_yahoo"] = noticias
        fontes["yahoo_noticias"] = f"ok ({len(noticias)})"
    except Exception as e:
        fontes["yahoo_noticias"] = f"falha: {type(e).__name__}"

    # Multiplos recalculados a partir dos insumos, para cruzar com os prontos
    try:
        preco = info.get("currentPrice") or info.get("regularMarketPrice") \
            or (dados.get("retornos") or {}).get("ultimo_fechamento", {}).get("preco")
        calc = {"preco_usado": preco}
        if preco and info.get("trailingEps"):
            calc["pl_12m"] = round(preco / info["trailingEps"], 2)
        if preco and info.get("forwardEps"):
            calc["pl_projetado"] = round(preco / info["forwardEps"], 2)
        if preco and info.get("bookValue"):
            calc["pvp"] = round(preco / info["bookValue"], 2)
        if info.get("enterpriseValue") and info.get("ebitda"):
            calc["ev_ebitda"] = round(info["enterpriseValue"] / info["ebitda"], 2)
        if preco and dados.get("dividendos"):
            calc["dy_12m"] = round(dados["dividendos"]["soma_12m_por_acao"] / preco, 4)
        if info.get("totalDebt") is not None and info.get("totalCash") is not None:
            calc["divida_liquida"] = info["totalDebt"] - info["totalCash"]
            if info.get("ebitda"):
                calc["divida_liquida_ebitda"] = round(calc["divida_liquida"] / info["ebitda"], 2)
        dados["multiplos_calculados"] = calc
    except Exception as e:
        fontes["multiplos_calculados"] = f"falha: {type(e).__name__}"
    return dados


# ───────────────────────── Fundamentus ─────────────────────────
PAR_FUNDAMENTUS = re.compile(
    r'<span class="txt">(.*?)</span>\s*</td>\s*<td class="data[^"]*">\s*<span class="txt">(.*?)</span>', re.S)


def _limpar(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return htmlmod.unescape(s).replace("\xa0", " ").strip()


def _numero_br(s):
    s = _limpar(s)
    if s in ("", "-", "--"):
        return None
    pct = s.endswith("%")
    s = s.rstrip("%").replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return _limpar(s) or None
    return round(v / 100, 6) if pct else v


def coletar_fundamentus(tk, fontes):
    url = f"https://www.fundamentus.com.br/detalhes.php?papel={tk}"
    r = app.http_get(url, timeout=20, headers={"Accept-Language": "pt-BR,pt;q=0.9"})
    if not r:
        fontes["fundamentus"] = "falha: sem resposta"
        return {}
    pares = PAR_FUNDAMENTUS.findall(r.text)
    out = {}
    for rotulo, valor in pares:
        rot = _limpar(rotulo).lstrip("?").strip()
        if not rot or rot in out:
            continue
        out[rot] = _numero_br(valor)
    if not out:
        fontes["fundamentus"] = "falha: pagina sem indicadores (bloqueio ou layout novo)"
        return {}
    out["_fonte"] = url
    fontes["fundamentus"] = f"ok ({len(out) - 1} campos)"
    return out


# ───────────────────────── CVM (IPE) ─────────────────────────
_IPE_CACHE = {}


def _linhas_ipe(ano):
    if ano in _IPE_CACHE:
        return _IPE_CACHE[ano]
    texto = app.baixar_ipe(ano)
    linhas = []
    if texto:
        try:
            linhas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
        except Exception:
            linhas = []
    _IPE_CACHE[ano] = linhas
    return linhas


def coletar_cvm(tk, nomes, fontes, limite=40):
    """Fatos relevantes e comunicados da CVM para a companhia do ticker."""
    nucleos = [nucleo_nome(n) for n in nomes if n]
    nucleos = [n for n in nucleos if n]
    if not nucleos:
        fontes["cvm"] = "sem nome de companhia para casar"
        return {}
    ano = datetime.now(timezone.utc).year
    linhas = _linhas_ipe(ano) + (_linhas_ipe(ano - 1) if datetime.now(timezone.utc).month <= 2 else [])
    if not linhas:
        fontes["cvm"] = "falha: IPE indisponivel"
        return {}

    def casa(nome_cvm):
        n = nucleo_nome(nome_cvm)
        for alvo in nucleos:
            if n == alvo or n.startswith(alvo + " ") or alvo.startswith(n + " "):
                return "exato"
        return None

    def casa_fraco(nome_cvm):
        n = set(nucleo_nome(nome_cvm).split())
        for alvo in nucleos:
            palavras = [p for p in alvo.split() if len(p) >= 5]
            if palavras and all(p in n for p in palavras):
                return "parcial"
        return None

    docs, metodo = [], None
    for tentativa in (casa, casa_fraco):
        docs = []
        for row in linhas:
            empresa = (row.get("Nome_Companhia") or "").strip()
            if not empresa or not tentativa(empresa):
                continue
            docs.append({
                "empresa": empresa,
                "categoria": (row.get("Categoria") or "").strip(),
                "tipo": (row.get("Tipo") or "").strip(),
                "assunto": (row.get("Assunto") or "").strip()[:240],
                "data": (row.get("Data_Entrega") or "")[:10],
                "link": (row.get("Link_Download") or "").strip(),
            })
        if docs:
            metodo = tentativa.__name__
            break
    docs.sort(key=lambda d: d["data"], reverse=True)
    fatos = [d for d in docs if d["categoria"] == "Fato Relevante"][:limite]
    outros = [d for d in docs if d["categoria"] != "Fato Relevante"][:limite]
    fontes["cvm"] = (f"ok ({len(fatos)} fatos relevantes, {len(outros)} outros; casamento {metodo}; "
                     f"empresa: {docs[0]['empresa']})") if docs else "sem documentos casados"
    codigos = {}
    for row in linhas:
        empresa = (row.get("Nome_Companhia") or "").strip()
        if docs and empresa == docs[0]["empresa"]:
            codigos[empresa] = (row.get("Codigo_CVM") or "").strip()
            break
    return {"fatos_relevantes": fatos, "outros_documentos": outros,
            "empresas_casadas": sorted({d["empresa"] for d in docs}),
            "codigo_cvm": codigos.get(docs[0]["empresa"]) if docs else None}


# ───────────────────────── SEC XBRL (demonstracoes oficiais, EUA) ─────────────────────────
# Para empresas que reportam a SEC (acoes dos EUA e ADRs de brasileiras), a API
# companyfacts entrega cada linha das demonstracoes, trimestre a trimestre e
# ano a ano, direto do XBRL dos 10-Q, 10-K e 20-F. E a fonte oficial.
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_HEADERS = {"User-Agent": app.SEC_UA, "Accept-Encoding": "gzip, deflate"}

# ADR nos EUA de empresas da B3 (20-F anual em IFRS)
ADR_DE_B3 = {
    "PETR4": "PBR", "PETR3": "PBR", "VALE3": "VALE", "ITUB4": "ITUB", "ITUB3": "ITUB",
    "BBDC4": "BBD", "BBDC3": "BBDO", "SANB11": "BSBR", "ABEV3": "ABEV", "SUZB3": "SUZ",
    "GGBR4": "GGB", "SBSP3": "SBS", "CMIG4": "CIG", "CPLE6": "ELP", "BRFS3": "BRFS",
    "EMBR3": "ERJ", "ELET3": "EBR", "TIMS3": "TIMB", "VIVT3": "VIV", "UGPA3": "UGP",
    "BRKM5": "BAK", "AZUL4": "AZUL", "CSNA3": "SID", "NTCO3": "NTCO", "PAGS": "PAGS",
}

# Linhas que interessam, por taxonomia. Chave = nome amigavel; valor = tags candidatas.
SEC_LINHAS = {
    "receita": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenue"],
    "custo": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfSales"],
    "lucro_bruto": ["GrossProfit"],
    "despesas_vendas_marketing": ["SellingAndMarketingExpense"],
    "despesas_gerais_adm": ["GeneralAndAdministrativeExpense"],
    "pesquisa_desenvolvimento": ["ResearchAndDevelopmentExpense"],
    "provisao_devedores_duvidosos": ["ProvisionForDoubtfulAccounts", "ProvisionForLoanLossesExpensed"],
    "ebit": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "despesa_juros": ["InterestExpense", "InterestExpenseNonoperating", "FinanceCosts"],
    "lucro_antes_ir": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "ProfitLossBeforeTax"],
    "imposto_renda": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"],
    "lucro_liquido": ["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "lpa_diluido": ["EarningsPerShareDiluted", "DilutedEarningsLossPerShare"],
    "depreciacao_amortizacao": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"],
    "ativo_total": ["Assets"],
    "caixa": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"],
    "patrimonio_liquido": ["StockholdersEquity", "Equity", "EquityAttributableToOwnersOfParent"],
    "divida_curto_prazo": ["DebtCurrent", "LongTermDebtCurrent", "ShorttermBorrowings", "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"],
    "divida_longo_prazo": ["LongTermDebtNoncurrent", "LongTermDebt", "NoncurrentPortionOfNoncurrentBorrowings"],
    "carteira_credito": ["LoansAndLeasesReceivableNetReportedAmount", "NotesReceivableNet", "LoansAndAdvancesToCustomers"],
    "caixa_operacional": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "acoes_diluidas": ["WeightedAverageNumberOfDilutedSharesOutstanding", "DilutedWeightedAverageNumberOfShares"],
}
_SEC_TICKERS = {}


def _cik_por_ticker(simbolo):
    global _SEC_TICKERS
    if not _SEC_TICKERS:
        r = app.http_get(SEC_TICKERS_URL, timeout=30, headers=SEC_HEADERS)
        if r:
            try:
                _SEC_TICKERS = {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}
            except Exception:
                _SEC_TICKERS = {}
    return _SEC_TICKERS.get(simbolo.upper())


def coletar_sec_xbrl(simbolo, fontes, max_periodos=40):
    cik = _cik_por_ticker(simbolo)
    if not cik:
        fontes["sec_xbrl"] = f"sem CIK para {simbolo}"
        return {}
    r = app.http_get(SEC_FACTS_URL.format(cik=cik), timeout=90, headers=SEC_HEADERS)
    if not r:
        fontes["sec_xbrl"] = "falha: companyfacts indisponivel"
        return {}
    try:
        facts = r.json().get("facts", {})
    except Exception:
        fontes["sec_xbrl"] = "falha: JSON ilegivel"
        return {}
    taxonomias = [tx for tx in ("us-gaap", "ifrs-full") if tx in facts]
    out = {"cik": cik, "taxonomias": taxonomias, "trimestral": {}, "anual": {}, "tags_usadas": {}}
    for nome, candidatos in SEC_LINHAS.items():
        for tag in candidatos:
            serie = None
            for tx in taxonomias:
                if tag in facts.get(tx, {}):
                    serie = facts[tx][tag]
                    break
            if not serie:
                continue
            unidades = serie.get("units", {})
            valores = unidades.get("USD") or unidades.get("USD/shares") or unidades.get("shares") \
                or unidades.get("BRL") or next(iter(unidades.values()), [])
            tri, anu = {}, {}
            for v in valores:
                frame = v.get("frame")
                if not frame:
                    continue
                if re.fullmatch(r"CY\d{4}Q[1-4]", frame):
                    tri[frame] = v.get("val")
                elif re.fullmatch(r"CY\d{4}", frame):
                    anu[frame] = v.get("val")
            if tri or anu:
                out["trimestral"][nome] = dict(sorted(tri.items())[-max_periodos:])
                out["anual"][nome] = dict(sorted(anu.items())[-15:])
                out["tags_usadas"][nome] = tag
                break
    n = len(out["tags_usadas"])
    fontes["sec_xbrl"] = f"ok ({n} linhas; CIK {cik})" if n else "vazio"
    return out


# ───────────────────────── CVM ITR/DFP (demonstracoes oficiais, B3) ─────────────────────────
# Dados abertos da CVM: um zip por ano com todas as companhias. Filtramos pelo
# codigo CVM da empresa (obtido no IPE) e guardamos as contas principais das
# demonstracoes consolidadas: DRE, balanco (ativo e passivo) e fluxo de caixa.
CVM_DFP_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip"
CVM_ITR_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip"
CVM_CONTAS = {
    "3.01": "receita_liquida", "3.02": "custos", "3.03": "resultado_bruto",
    "3.04": "despesas_receitas_operacionais", "3.05": "ebit", "3.06": "resultado_financeiro",
    "3.07": "resultado_antes_ir", "3.08": "imposto_renda", "3.09": "resultado_operacoes_continuadas",
    "3.11": "lucro_liquido_consolidado", "3.99.02.01": "lpa_diluido_on",
    "1": "ativo_total", "1.01": "ativo_circulante", "1.01.01": "caixa_equivalentes",
    "1.01.02": "aplicacoes_financeiras", "1.01.04": "estoques", "1.02": "ativo_nao_circulante",
    "2.01": "passivo_circulante", "2.01.04": "emprestimos_curto_prazo", "2.02": "passivo_nao_circulante",
    "2.02.01": "emprestimos_longo_prazo", "2.03": "patrimonio_liquido_consolidado",
    "6.01": "caixa_operacional", "6.02": "caixa_investimento", "6.03": "caixa_financiamento",
}
_CVM_ZIPS = {}


def _csvs_do_zip(url):
    """{nome_arquivo: linhas(dict)} dos CSVs de um zip da CVM (baixa uma vez por execucao)."""
    if url in _CVM_ZIPS:
        return _CVM_ZIPS[url]
    r = app.http_get(url, timeout=180)
    arquivos = {}
    if r:
        try:
            import zipfile
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                for nome in z.namelist():
                    low = nome.lower()
                    if low.endswith(".csv") and any(k in low for k in ("_dre_con_", "_bpa_con_", "_bpp_con_", "_dfc_mi_con_")):
                        arquivos[nome] = z.read(nome).decode("latin-1")
        except Exception as e:
            print(f"  cvm: zip ilegivel {url[-40:]}: {e}")
    _CVM_ZIPS[url] = arquivos
    return arquivos


def _demonstracoes_cvm(arquivos, cd_cvm, tipo):
    """Filtra as contas da empresa (ultima versao de cada periodo). tipo = 'dfp' ou 'itr'."""
    saida = {}
    alvo = str(int(cd_cvm))
    for nome, texto in arquivos.items():
        for row in csv.DictReader(io.StringIO(texto), delimiter=";"):
            try:
                if str(int(row.get("CD_CVM") or 0)) != alvo:
                    continue
            except ValueError:
                continue
            if (row.get("ORDEM_EXERC") or "").upper() != "ÚLTIMO":
                continue
            conta = (row.get("CD_CONTA") or "").strip()
            chave = CVM_CONTAS.get(conta)
            if not chave:
                continue
            fim = (row.get("DT_FIM_EXERC") or "")[:10]
            ini = (row.get("DT_INI_EXERC") or "")[:10]
            try:
                # A CVM publica a escala como texto ("MIL" ou "UNIDADE"); guardamos em R$ milhoes
                escala = (row.get("ESCALA_MOEDA") or "").strip().upper()
                fator = 1000.0 if escala == "MIL" else 1.0
                valor = float((row.get("VL_CONTA") or "0").replace(",", ".")) * fator / 1e6
            except ValueError:
                continue
            # DRE e DFC do ITR trazem o trimestre (3 meses) e o acumulado no ano:
            # marcamos o periodo pelo intervalo para nao misturar.
            periodo = fim if not ini else f"{ini}..{fim}"
            saida.setdefault(chave, {})[periodo] = round(valor, 3)
    return saida


def coletar_cvm_demonstracoes(cd_cvm, fontes):
    if not cd_cvm:
        fontes["cvm_demonstracoes"] = "sem codigo CVM (IPE nao casou a empresa)"
        return {}
    ano = datetime.now(timezone.utc).year
    out = {"cd_cvm": cd_cvm, "unidade": "R$ milhoes", "dfp_anual": {}, "itr_trimestral": {}}
    for a in (ano - 1, ano - 2, ano - 3):
        arq = _csvs_do_zip(CVM_DFP_URL.format(ano=a))
        if arq:
            for k, v in _demonstracoes_cvm(arq, cd_cvm, "dfp").items():
                out["dfp_anual"].setdefault(k, {}).update(v)
    for a in (ano, ano - 1):
        arq = _csvs_do_zip(CVM_ITR_URL.format(ano=a))
        if arq:
            for k, v in _demonstracoes_cvm(arq, cd_cvm, "itr").items():
                out["itr_trimestral"].setdefault(k, {}).update(v)
    for bloco in ("dfp_anual", "itr_trimestral"):
        for k in out[bloco]:
            out[bloco][k] = dict(sorted(out[bloco][k].items()))
    n_a, n_t = len(out["dfp_anual"]), len(out["itr_trimestral"])
    fontes["cvm_demonstracoes"] = f"ok (DFP: {n_a} contas, ITR: {n_t} contas)" if (n_a or n_t) else "vazio: zips da CVM sem a empresa"
    return out


# ───────────────────────── Macro e TIR ─────────────────────────
def coletar_macro(fontes):
    out = {}
    for chave, (codigo, nome, unidade) in app.SGS_SERIES.items():
        if chave not in ("selic_meta", "ipca_12m", "cdi_mes", "dolar_ptax", "ipca_mes"):
            continue
        pts = app.sgs_fetch(codigo, 1)
        if pts:
            out[chave] = {"nome": nome, "unidade": unidade, **pts[-1]}
    fontes["bcb"] = f"ok ({len(out)} series)" if out else "falha: sem resposta"
    return out


def tir_modelo(tk, preco, ipca):
    if tk not in TIR.tickers_cobertos():
        return {"coberto": False}
    r = TIR.calcular_tir(tk, preco or 0, ipca) if preco else {"error": "sem preco"}
    return {"coberto": True, "resultado": r,
            "insumos": {"lpa_2025e_2026e": TIR.FORWARD_EPS_SAFRA.get(tk),
                        "payout_historico": TIR.PAYOUT_HISTORICO.get(tk),
                        "pl_medio_historico": TIR.PL_MEDIO_HISTORICO.get(tk),
                        "analise": TIR.SAFRA_ANALISE.get(tk)}}


# ───────────────────────── Orquestracao ─────────────────────────
def coletar_ativo(tk, macro):
    fontes = {}
    dados = {"ticker": tk, "gerado_em": agora(), "fontes": fontes}
    try:
        dados["yahoo"] = coletar_yahoo(tk, fontes)
    except Exception as e:
        fontes["yahoo"] = f"falha geral: {type(e).__name__}: {e}"[:160]
        dados["yahoo"] = {}
    if eh_simbolo_us(tk):
        dados["fundamentus"], dados["cvm"] = {}, {}
        fontes["fundamentus"] = fontes["cvm"] = "nao se aplica (papel dos EUA)"
    else:
        try:
            dados["fundamentus"] = coletar_fundamentus(tk, fontes)
        except Exception as e:
            fontes["fundamentus"] = f"falha geral: {type(e).__name__}: {e}"[:160]
            dados["fundamentus"] = {}
    info = (dados.get("yahoo") or {}).get("info") or {}
    if not eh_simbolo_us(tk):
        nomes = [info.get("longName"), info.get("shortName"), dados["fundamentus"].get("Empresa")]
        try:
            dados["cvm"] = coletar_cvm(tk, nomes, fontes)
        except Exception as e:
            fontes["cvm"] = f"falha geral: {type(e).__name__}: {e}"[:160]
            dados["cvm"] = {}

    # Demonstracoes oficiais
    if eh_simbolo_us(tk):
        try:
            dados["sec_xbrl"] = coletar_sec_xbrl(tk, fontes)
        except Exception as e:
            fontes["sec_xbrl"] = f"falha geral: {type(e).__name__}: {e}"[:160]
    else:
        try:
            dados["cvm_demonstracoes"] = coletar_cvm_demonstracoes((dados.get("cvm") or {}).get("codigo_cvm"), fontes)
        except Exception as e:
            fontes["cvm_demonstracoes"] = f"falha geral: {type(e).__name__}: {e}"[:160]
        adr = ADR_DE_B3.get(tk)
        if adr:
            try:
                dados["sec_xbrl_adr"] = {"adr": adr, **coletar_sec_xbrl(adr, fontes)}
            except Exception as e:
                fontes["sec_xbrl"] = f"falha geral: {type(e).__name__}: {e}"[:160]

    # BDR: traz tambem a acao-mae nos EUA e a paridade implicita
    if eh_bdr(tk):
        base = tk[:4]
        fontes_sub = {}
        try:
            sub = coletar_yahoo(base, fontes_sub, simbolo=base)
            sub_info = sub.get("info") or {}
            dados["subjacente_us"] = {"simbolo": base, "fontes": fontes_sub, "yahoo": sub}
            try:
                dados["subjacente_us"]["sec_xbrl"] = coletar_sec_xbrl(base, fontes_sub)
            except Exception as e:
                fontes_sub["sec_xbrl"] = f"falha geral: {type(e).__name__}: {e}"[:160]
            preco_bdr = info.get("currentPrice") or info.get("regularMarketPrice")
            preco_us = sub_info.get("currentPrice") or sub_info.get("regularMarketPrice")
            dolar = (macro.get("dolar_ptax") or {}).get("value")
            if preco_bdr and preco_us and dolar:
                dados["subjacente_us"]["paridade_implicita"] = {
                    "descricao": "quantas BDRs equivalem a 1 acao nos EUA, pelo preco: preco_us x dolar / preco_bdr",
                    "bdrs_por_acao": round(preco_us * dolar / preco_bdr, 3),
                    "preco_bdr": preco_bdr, "preco_us": preco_us, "dolar_ptax": dolar,
                }
            fontes["subjacente_us"] = f"ok ({base}; {sum(1 for v in fontes_sub.values() if str(v).startswith('ok'))} fontes ok)"
        except Exception as e:
            fontes["subjacente_us"] = f"falha: {type(e).__name__}: {e}"[:160]
    preco = info.get("currentPrice") or info.get("regularMarketPrice") \
        or ((dados.get("yahoo") or {}).get("retornos") or {}).get("ultimo_fechamento", {}).get("preco")
    ipca = (macro.get("ipca_12m") or {}).get("value", 4.5)
    dados["tir_modelo"] = tir_modelo(tk, preco, ipca)
    dados["macro"] = macro
    dados["identificacao"] = {
        "nome": info.get("longName") or info.get("shortName") or dados["fundamentus"].get("Empresa"),
        "setor_yahoo": info.get("sector"), "industria_yahoo": info.get("industry"),
        "setor_fundamentus": dados["fundamentus"].get("Setor"),
        "subsetor_fundamentus": dados["fundamentus"].get("Subsetor"),
        "site": info.get("website"),
    }
    return dados


def gravar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"), default=nativo)


def snapshot_terminal(saida):
    """Roda os coletores do terminal (gerar_dados.py) e copia os JSONs para snapshot/."""
    import gerar_dados
    tmp = tempfile.mkdtemp(prefix="broadcast_site_")
    try:
        gerar_dados.gerar(tmp)
        destino = os.path.join(saida, "snapshot")
        if os.path.isdir(destino):
            shutil.rmtree(destino)
        shutil.copytree(os.path.join(tmp, "api"), destino)
        return {"ok": True, "falhas": gerar_dados.resumo.get("falhas", [])}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", default="", help="separados por virgula ou espaco; vazio = modelo de TIR")
    ap.add_argument("--saida", default="dados_out")
    ap.add_argument("--snapshot", action="store_true", help="tambem grava o retrato geral do terminal")
    args = ap.parse_args()

    tickers = [t.strip().upper().replace(".SA", "") for t in re.split(r"[,\s;]+", args.tickers) if t.strip()]
    if not tickers and not args.snapshot:
        tickers = TIR.tickers_cobertos()
    os.makedirs(args.saida, exist_ok=True)

    resumo = {"gerado_em": agora(), "tickers": {}, "snapshot": None}
    if args.snapshot:
        print("Retrato geral do terminal...")
        try:
            resumo["snapshot"] = snapshot_terminal(args.saida)
        except Exception as e:
            resumo["snapshot"] = {"ok": False, "erro": f"{type(e).__name__}: {e}"[:200]}
        print("  snapshot:", resumo["snapshot"])

    macro = {}
    if tickers:
        fontes_macro = {}
        macro = coletar_macro(fontes_macro)
        print("Macro:", fontes_macro)

    for tk in tickers:
        print(f"Coletando {tk}...")
        dados = coletar_ativo(tk, macro)
        gravar_json(os.path.join(args.saida, "ativos", f"{tk}.json"), dados)
        resumo["tickers"][tk] = dados["fontes"]
        for k, v in dados["fontes"].items():
            print(f"  {k}: {v}")

    # indice acumulado dos ativos ja coletados no branch
    idx_path = os.path.join(args.saida, "ativos", "index.json")
    indice = {}
    if os.path.exists(idx_path):
        try:
            indice = json.load(open(idx_path, encoding="utf-8")).get("ativos", {})
        except Exception:
            indice = {}
    for tk in tickers:
        indice[tk] = {"gerado_em": resumo["gerado_em"], "arquivo": f"ativos/{tk}.json"}
    gravar_json(idx_path, {"atualizado_em": agora(), "ativos": dict(sorted(indice.items()))})
    gravar_json(os.path.join(args.saida, "ultima_coleta.json"), resumo)
    print(f"\n{len(tickers)} ativos gravados em {args.saida}/ativos/")


if __name__ == "__main__":
    main()

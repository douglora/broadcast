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
    python coletar_dados.py --tickers MELI34 --pares auto --saida dados_out   # ticker + pares + comparativo
    python coletar_dados.py --snapshot --saida dados_out        # retrato geral do terminal
    python coletar_dados.py --saida dados_out                    # lista padrao (modelo de TIR)

Fontes por ativo, em ordem de autoridade:
  1. Demonstracoes oficiais: CVM dados abertos (DFP anual e ITR trimestral,
     consolidado) para companhias da B3; XBRL da SEC (10-K, 10-Q, 20-F) para
     papeis dos EUA, ADRs e a acao-mae dos BDRs. Series trimestrais limpas,
     com o 4T derivado do anual.
  2. Release de resultados do RI: o mesmo PDF que a empresa publica no site
     de RI, lido na copia oficial entregue a CVM (IPE, "Press-release") ou a
     SEC (8-K item 2.02 / 6-K, exhibit 99). Texto integral no JSON, para os
     KPIs que nao estao nas demonstracoes (GMV, NIMAL, same-store sales,
     guidance, divida por moeda). Quando a copia da CVM esta atras do ITR
     mais novo (o IPE do ano corrente ja saiu do ar), a central de resultados
     do site de RI (ri_fontes.py) completa os trimestres que faltam; o bloco
     `frescor` do JSON mede essa defasagem.
  3. Yahoo Finance (cotacao, historico, consenso, noticias), Fundamentus
     (indicadores no padrao brasileiro), CVM IPE (fatos relevantes), Banco
     Central (Selic, IPCA, dolar) e o modelo de TIR real deste repositorio.
Com --pares auto, coleta tambem os pares do grupo (pares.py) e grava
comparativos/<grupo>.json com multiplos, margens e series oficiais lado a lado.
Cada fonte falha sozinha: o JSON registra o que respondeu e o que nao.
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
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import requests  # noqa: E402

import app  # noqa: E402  (reaproveita http_get, IPE_URL, sgs_fetch)
import pares as PARES_MOD  # noqa: E402  (grupos de pares e acao-mae dos BDRs)
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
    """Ticker so com letras (ate 5, classe opcional) e um papel dos EUA, ex.: MELI, AAPL, BRK-B."""
    return re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", tk) is not None


def eh_bdr(tk):
    """BDR da B3: 4 caracteres + 31..39, ex.: MELI34, AAPL34, GOGL35, M1TA34, STOC31."""
    return re.fullmatch(r"[A-Z][A-Z0-9]{3}3[1-9]", tk) is not None


def simbolo_subjacente(tk):
    """Acao-mae nos EUA de um BDR: excecoes em pares.BDR_SUBJACENTE, senao as 4 letras."""
    return PARES_MOD.BDR_SUBJACENTE.get(tk, tk[:4])


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
        # O rotulo as vezes vem colado ao bloco anterior da tabela ("Dia -2,53% ?P/L"):
        # fica so a ultima linha, sem o "?" do tooltip.
        rot = _limpar(rotulo).strip().split("\n")[-1].strip().lstrip("?").strip()
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
    """Indice IPE do ano, de todas as partes do zip. Cacheado por execucao."""
    if ano in _IPE_CACHE:
        return _IPE_CACHE[ano]
    try:
        linhas = app.baixar_ipe_linhas(ano)
    except Exception as e:
        app.log(f"cvm: IPE {ano} falhou ({e})")
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
    hoje = datetime.now(timezone.utc)
    ano = hoje.year
    # Tres anos de IPE: fatos relevantes usam so a janela recente, mas o historico de releases
    # precisa de 8 trimestres para tras. Os zips ficam em cache por execucao.
    linhas, por_ano = [], {}
    for a in (ano, ano - 1, ano - 2):
        do_ano = _linhas_ipe(a)
        por_ano[a] = len(do_ano)
        linhas += do_ano
    if not linhas:
        fontes["cvm"] = "falha: IPE indisponivel"
        return {}
    vazios = [str(a) for a, n in por_ano.items() if not n]
    if vazios:
        app.log(f"cvm: IPE sem linhas em {', '.join(vazios)} (indice incompleto; documentos desses anos vao faltar)")

    def casa(nome_cvm):
        """2 = nucleo igual (BANCO DO BRASIL S.A. -> BRASIL); 1 = um e prefixo do outro (BRASIL TECNOLOGIA)."""
        n = nucleo_nome(nome_cvm)
        melhor = 0
        for alvo in nucleos:
            if n == alvo:
                return 2
            if n.startswith(alvo + " ") or alvo.startswith(n + " "):
                melhor = max(melhor, 1)
        return melhor

    def casa_fraco(nome_cvm):
        n = set(nucleo_nome(nome_cvm).split())
        for alvo in nucleos:
            palavras = [p for p in alvo.split() if len(p) >= 5]
            if palavras and all(p in n for p in palavras):
                return 1
        return 0

    docs, metodo = [], None
    for tentativa in (casa, casa_fraco):
        docs, pontuacao = [], {}
        for row in linhas:
            empresa = (row.get("Nome_Companhia") or "").strip()
            if not empresa:
                continue
            nota = pontuacao.get(empresa)
            if nota is None:
                nota = pontuacao[empresa] = tentativa(empresa)
            if not nota:
                continue
            docs.append({
                "empresa": empresa, "_nota": nota,
                "categoria": (row.get("Categoria") or "").strip(),
                "tipo": (row.get("Tipo") or "").strip(),
                "assunto": (row.get("Assunto") or "").strip()[:240],
                "data": (row.get("Data_Entrega") or "")[:10],
                "link": (row.get("Link_Download") or "").strip(),
            })
        if docs:
            # Fica a empresa com o melhor casamento; no empate, a que tem mais documentos.
            # Evita trocar o Banco do Brasil pela Brasil Tecnologia ou o BTG pela BTG Commodities.
            melhor_nota = max(d["_nota"] for d in docs)
            contagem = {}
            for d in docs:
                if d["_nota"] == melhor_nota:
                    contagem[d["empresa"]] = contagem.get(d["empresa"], 0) + 1
            escolhida = max(contagem, key=contagem.get)
            outras = sorted({d["empresa"] for d in docs if d["empresa"] != escolhida})
            docs = [{k: v for k, v in d.items() if k != "_nota"} for d in docs if d["empresa"] == escolhida]
            metodo = tentativa.__name__
            break
    docs.sort(key=lambda d: d["data"], reverse=True)
    corte = (hoje - timedelta(days=365)).strftime("%Y-%m-%d")
    recentes = [d for d in docs if d["data"] >= corte]
    fatos = [d for d in recentes if d["categoria"] == "Fato Relevante"][:limite]
    outros = [d for d in recentes if d["categoria"] != "Fato Relevante"][:limite]
    # Documentos de resultado dos 3 anos: o release (mesmo PDF do site de RI) e a apresentacao.
    # Teto alto de proposito: o Itau publica quatro por trimestre (duas apresentacoes, o press
    # release e a Analise Gerencial), e um teto baixo cortava o historico em menos de 8 trimestres.
    resultado = [d for d in docs if _eh_documento_resultado(d)][:60]
    indice = ", ".join(f"{a}: {n} linhas" for a, n in sorted(por_ano.items(), reverse=True))
    fontes["cvm"] = (f"ok ({len(fatos)} fatos relevantes, {len(outros)} outros, "
                     f"{len(resultado)} de resultado; casamento {metodo}; "
                     f"empresa: {docs[0]['empresa']}; indice IPE {indice})") if docs else (
                     f"sem documentos casados (indice IPE {indice})")
    codigos = {}
    for row in linhas:
        empresa = (row.get("Nome_Companhia") or "").strip()
        if docs and empresa == docs[0]["empresa"]:
            codigos[empresa] = (row.get("Codigo_CVM") or "").strip()
            break
    return {"fatos_relevantes": fatos, "outros_documentos": outros, "documentos_resultado": resultado,
            "empresa_escolhida": docs[0]["empresa"] if docs else None,
            "empresas_casadas": ([docs[0]["empresa"]] + outras) if docs else [],
            "codigo_cvm": codigos.get(docs[0]["empresa"]) if docs else None}


# Documento anual ou societario que as vezes chega com tipo "Press-release": nao e release
# de trimestre e polui o historico (o "Relatorio da Administracao 2025" do Magalu virou 4T24).
_RE_NAO_E_RELEASE = re.compile(
    r"RELATORIO DA ADMINISTRACAO|RELATORIO ANUAL|RELATO INTEGRADO|FORMULARIO DE REFERENCIA|"
    r"DEMONSTRACOES FINANCEIRAS|RELATORIO DE SUSTENTABILIDADE|RELATORIO DO AUDITOR|"
    r"POLITICA DE|ESTATUTO|ATA DE|EDITAL|PROSPECTO|CODIGO DE CONDUTA|PARECER")
_RE_ASSUNTO_RESULTADO = re.compile(
    r"PRESS RELEASE|RELEASE DE RESULTADO|RELEASE RESULTADO|DIVULGACAO DE RESULTADO|DIVULGACAO DOS RESULTADOS|"
    r"EARNINGS RELEASE|EARNINGS|INFORMACOES SOBRE O RESULTADO|RESULTADO DO [1-4]|RESULTADOS DO [1-4]|"
    r"ANALISE GERENCIAL|ANALISE DO DESEMPENHO|COMENTARIO DE DESEMPENHO|RESULTADO [1-4]T|RESULTADOS [1-4]T")


def _classe_documento_resultado(d):
    """'release' (texto de resultados: press-release ou relatorio gerencial), 'apresentacao' ou None."""
    cat, tipo, assunto = normalizar(d["categoria"]), normalizar(d["tipo"]), normalizar(d["assunto"])
    if _RE_NAO_E_RELEASE.search(assunto):
        return None
    if cat.startswith("DADOS ECONOMICO") and (tipo.startswith("PRESS RELEASE") or tipo.startswith("RELATORIO DE ANALISE GERENCIAL")):
        return "release"
    if tipo.startswith("APRESENTACOES A ANALISTAS"):
        return "apresentacao" if re.search(r"RESULTADO|EARNINGS|RESULTS|[1-4]T\d\d|[1-4]Q\d\d", assunto) else None
    if cat.startswith("COMUNICADO AO MERCADO") and _RE_ASSUNTO_RESULTADO.search(assunto) \
            and not re.search(r"\bCALL\b|TELECONFERENCIA|WEBCAST|CONVITE|PERIODO DE SILENCIO|CALENDARIO", assunto):
        return "release"
    return None


def _eh_documento_resultado(d):
    return _classe_documento_resultado(d) is not None


# ───────────────────────── Release de resultados (RI via CVM e SEC) ─────────────────────────
# O release que a empresa publica no site de RI e entregue, no mesmo dia, a
# CVM (IPE, categoria "Dados Economico-Financeiros / Press-release") e, para
# quem reporta a SEC, como exhibit 99 de um 8-K (item 2.02) ou 6-K. Lemos
# essa copia oficial: mesmo PDF, sem depender do layout de cada site de RI.
RELEASE_MAX_CHARS = 150000
RELEASE_MAX_PAGINAS = 80
# Quantos releases guardar por ativo (8 trimestres = 2 anos de discurso da gestao)
RELEASES_POR_ATIVO = 8
# Teto de tempo, por ativo, gasto baixando releases que ainda nao estao no branch.
# Estourou, para e completa o historico na proxima coleta.
RELEASE_ORCAMENTO_S = 150

_RE_TRI_CURTO = re.compile(r"\b([1-4])\s*[TQ]\s*(\d{2})\b")
_RE_TRI_LONGO = re.compile(r"\b([1-4])\s*O?\s*(?:TRIMESTRE|QUARTER)\s*(?:DE|OF)?\s*(\d{4})\b")
_RE_TRI_EN = re.compile(r"\b(FIRST|SECOND|THIRD|FOURTH)\s+QUARTER\b.{0,45}?\b(20\d{2})\b")
_ORDINAL_EN = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4}


def periodo_release(*textos):
    """'Release de Resultados 2T26' ou 'second quarter 2026' -> '2T26'. None se nao achar."""
    for texto in textos:
        t = normalizar(texto)[:4000]
        for rx, conv in ((_RE_TRI_CURTO, lambda a, b: (int(a), int(b))),
                         (_RE_TRI_LONGO, lambda a, b: (int(a), int(b) % 100)),
                         (_RE_TRI_EN, lambda a, b: (_ORDINAL_EN[a], int(b) % 100))):
            m = rx.search(t)
            if m:
                tri, ano = conv(m.group(1), m.group(2))
                return f"{tri}T{ano:02d}"
    return None


def trimestre_anterior(data):
    """'2026-08-05' -> '2T26': o trimestre que fechou antes dessa data."""
    try:
        d = datetime.strptime(data[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    tri, ano = (d.month - 1) // 3, d.year
    if tri == 0:
        tri, ano = 4, ano - 1
    return f"{tri}T{ano % 100:02d}"


def _texto_pdf(conteudo, max_paginas=RELEASE_MAX_PAGINAS):
    """Texto de um PDF (pypdf), com marcadores de pagina. None se nao der."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "pypdf nao instalado"
    try:
        leitor = PdfReader(io.BytesIO(conteudo))
        partes, n = [], len(leitor.pages)
        for i, pagina in enumerate(leitor.pages[:max_paginas]):
            try:
                t = pagina.extract_text() or ""
            except Exception:
                t = ""
            t = re.sub(r"[ \t\xa0]+", " ", t)
            t = re.sub(r"\n{3,}", "\n\n", t).strip()
            if t:
                partes.append(f"[p. {i + 1}]\n{t}")
        return "\n\n".join(partes), f"{n} paginas"
    except Exception as e:
        return None, f"pdf ilegivel: {type(e).__name__}"


def _html_para_texto(html):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", t)
    t = re.sub(r"(?i)</t[dh]>", " | ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _texto_de_download(r):
    """Texto de uma resposta HTTP que pode ser PDF, zip com PDF, ou HTML."""
    conteudo = r.content or b""
    tipo = (r.headers.get("Content-Type") or "").lower()
    # PDF pela assinatura (a norma admite ate 1024 bytes antes de %PDF) ou pelo Content-Type: um PDF
    # truncado ou servido com tipo errado cai em _texto_pdf ('pdf ilegivel', falha passageira) em vez
    # de virar 'formato desconhecido' e ser descartado como se nao fosse release
    if b"%PDF" in conteudo[:1024] or tipo.startswith("application/pdf"):
        return _texto_pdf(conteudo)
    if conteudo[:2] == b"PK":
        try:
            import zipfile
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                pdfs = [n for n in z.namelist() if n.lower().endswith(".pdf")]
                if pdfs:
                    return _texto_pdf(z.read(pdfs[0]))
        except Exception as e:
            return None, f"zip ilegivel: {type(e).__name__}"
        return None, "zip sem PDF"
    if "html" in tipo or b"<html" in conteudo[:2000].lower():
        return _html_para_texto(r.text), "html"
    try:
        return r.content.decode("utf-8"), "texto"
    except Exception:
        return None, f"formato desconhecido ({tipo[:40]})"


_RE_FALHA_PASSAGEIRA = re.compile(r"^(pypdf nao instalado|pdf ilegivel|zip ilegivel|formato desconhecido)")
_RE_PAGINA_BLOQUEIO = re.compile(r"(?i)just a moment|checking your browser|attention required|access denied|"
                                 r"enable javascript and cookies|cf-browser-verification|incapsula|"
                                 r"request unsuccessful|service unavailable|temporarily unavailable|"
                                 r"too many requests|(error|erro) 5\d\d")


def _falha_passageira(texto, detalhe, curto_passageiro=False):
    """True quando a reprovacao de um documento pode ser do ambiente ou do servidor, nao do documento.

    Um link gravado em `descartados` no index.json nunca mais e baixado; por isso so vai para la o que
    e deterministico: zip sem PDF, PDF legivel sem texto nenhum (imagem escaneada) e pagina HTML de
    verdade que nao e release. 'pypdf nao instalado' (pip falhou no runner), 'pdf ilegivel' (download
    truncado), 'zip ilegivel', 'formato desconhecido' e, com `curto_passageiro`, texto curto (pagina de
    erro momentanea ou desafio de WAF com 200 OK) ficam de fora e o link e tentado de novo na proxima
    coleta. Sem isso um pip que falhasse uma vez apagava o release mais novo de todos os ativos do run."""
    if texto is None:
        return bool(_RE_FALHA_PASSAGEIRA.match(detalhe or ""))
    if not texto and re.match(r"\d+ paginas$", detalhe or ""):
        return False
    return curto_passageiro


SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
SEC_ARQUIVO_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{nome}"
_PALAVRAS_RESULTADO = re.compile(r"(?i)(quarter|trimestre|fiscal year|full[- ]year|results|resultados|earnings)")


def _montar_release(texto, detalhe, meta):
    """Objeto de release: metadados, trimestre e o texto (cortado em RELEASE_MAX_CHARS)."""
    if not texto:
        return None
    texto = texto.strip()
    cortado = len(texto) > RELEASE_MAX_CHARS
    periodo = meta.get("periodo") or periodo_release(meta.get("assunto") or "", texto[:4000]) \
        or trimestre_anterior(meta.get("data"))
    return {**meta, "periodo": periodo, "detalhe": detalhe, "caracteres_total": len(texto),
            "cortado": cortado, "texto": texto[:RELEASE_MAX_CHARS]}


def _preferencia_release_cvm(d):
    """Ordem dentro do trimestre: relatorio gerencial, press-release em portugues, sem idioma, ingles, comunicado."""
    tipo, assunto = normalizar(d["tipo"]), normalizar(d["assunto"])
    if tipo.startswith("RELATORIO DE ANALISE GERENCIAL"):
        return 0
    if tipo.startswith("PRESS RELEASE"):
        if re.search(r"PORTUGU|\bPT\b|\bPOR\b", assunto):
            return 0.5
        return 1 if re.search(r"INGL|ENGL|\bEN\b|ENGLISH", assunto) else 0.7
    return 2


_FIM_DO_TRIMESTRE = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def ordem_periodo(periodo):
    """'2T26' -> (2026, 2), para ordenar; (0, 0) quando nao ha trimestre."""
    m = re.fullmatch(r"([1-4])T(\d{2})", periodo or "")
    return (2000 + int(m.group(2)), int(m.group(1))) if m else (0, 0)


def _ano_trimestre(rotulo):
    """'2T26', '2026T2' ou 'CY2026Q2' -> (ano, trimestre). None quando nao e um trimestre.

    Os tres formatos convivem no branch: releases ('2T26'), series da CVM ('2026T2') e da SEC
    ('CY2026Q2'). Comparar frescor exige le-los todos."""
    p = str(rotulo or "").strip().upper()
    m = re.fullmatch(r"([1-4])[TQ](\d{2}|\d{4})", p)
    if m:
        ano = int(m.group(2))
        return (ano if ano > 99 else 2000 + ano, int(m.group(1)))
    m = re.fullmatch(r"(?:CY)?(\d{4})[TQ]([1-4])", p)
    return (int(m.group(1)), int(m.group(2))) if m else None


def defasagem_release(periodo_release, periodo_itr):
    """Quantos trimestres o release mais novo esta ATRAS do ITR/XBRL mais novo.

    defasagem_release('3T25', '2026T2') == 3; ('2T26', '2026T2') == 0; sem release == 99.
    Sem ITR legivel nao ha como medir: devolve 0 (quem chama escolhe outra referencia)."""
    rel = _ano_trimestre(periodo_release)
    if rel is None:
        return 99
    itr = _ano_trimestre(periodo_itr)
    if itr is None:
        return 0
    return max(0, (itr[0] * 4 + itr[1]) - (rel[0] * 4 + rel[1]))


def _periodo_plausivel(periodo, data, dias=120):
    """O trimestre precisa ter fechado nos ultimos `dias` antes da entrega do documento.

    Sem isso, um trimestre citado de passagem no meio de um relatorio anual vira o rotulo
    do documento inteiro."""
    ano, tri = ordem_periodo(periodo)
    if not tri or not data:
        return False
    try:
        fim = datetime.strptime(f"{ano}-{_FIM_DO_TRIMESTRE[tri]}", "%Y-%m-%d")
        entrega = datetime.strptime(str(data)[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return -10 <= (entrega - fim).days <= dias


def _ajustar_periodo(item):
    """Troca o trimestre implausivel pelo que fechou antes da entrega. Devolve o item."""
    if not _periodo_plausivel(item.get("periodo"), item.get("data")):
        item["periodo"] = trimestre_anterior(item.get("data"))
    return item


def _melhor_release(novo, atual):
    """Mesmo trimestre, dois documentos: origem melhor, depois o entregue mais perto do fechamento
    do trimestre (o release sai primeiro; relatorio anual e owners' day vem meses depois), depois tamanho."""
    if atual is None:
        return True
    pn, pa = novo.get("preferencia", 1), atual.get("preferencia", 1)
    if pn != pa:
        return pn < pa
    dn, da = novo.get("data") or "9999", atual.get("data") or "9999"
    if dn != da:
        return dn < da
    return (novo.get("caracteres_total") or 0) > (atual.get("caracteres_total") or 0)


def _lista_por_periodo(achados, max_releases):
    """Do trimestre mais novo para o mais antigo."""
    return sorted(achados.values(),
                  key=lambda r: (ordem_periodo(r.get("periodo")), r.get("data") or ""),
                  reverse=True)[:max_releases]


def _grupos_por_periodo(documentos):
    """Agrupa por trimestre citado no assunto; sem trimestre, pela data. Mais novo primeiro."""
    grupos = {}
    for d in documentos:
        grupos.setdefault(periodo_release(d["assunto"]) or d["data"], []).append(d)
    return sorted(grupos.items(), key=lambda kv: max(x["data"] for x in kv[1]), reverse=True)


def _resumo_releases(fontes, lista, baixados, reusados, estourou, vazio):
    if not lista:
        fontes["release_ri"] = f"{vazio}; orcamento de tempo estourou antes de baixar" if estourou else vazio
        return lista
    n = lista[0]
    rotulo = n.get("assunto") or n.get("formulario") or ""
    fontes["release_ri"] = (f"ok ({rotulo[:50]}; {n.get('periodo')}; {n.get('data')}; "
                            f"{n.get('caracteres_total')} caracteres); historico de {len(lista)} releases "
                            f"({baixados} baixados, {reusados} reusados"
                            f"{'; orcamento de tempo estourou, completa na proxima coleta' if estourou else ''})")
    return lista


def coletar_releases_cvm(documentos, fontes, conhecidos=None,
                         max_releases=RELEASES_POR_ATIVO, orcamento_s=RELEASE_ORCAMENTO_S):
    """Ate `max_releases` releases de resultado entregues a CVM, um por trimestre, mais novo primeiro.

    `conhecidos` mapeia link -> release ja gravado no branch; esse nao e baixado de novo."""
    conhecidos = conhecidos or {}
    candidatos = [d for d in documentos if _classe_documento_resultado(d) == "release"]
    if not candidatos:
        fontes["release_ri"] = "sem press-release no IPE"
        return []
    achados, baixados, reusados = {}, 0, 0
    t0, estourou = time.monotonic(), False
    for _, docs in _grupos_por_periodo(candidatos):
        if len(achados) >= max_releases:
            break
        docs = sorted(docs, key=_preferencia_release_cvm)
        pref = _preferencia_release_cvm(docs[0])
        # Trimestre ja resolvido por um documento de origem melhor: nem baixa
        no_assunto = periodo_release(docs[0]["assunto"])
        if no_assunto and no_assunto in achados and achados[no_assunto].get("preferencia", 1) <= pref:
            continue
        item = None
        ja = next((d for d in docs if conhecidos.get(d["link"])), None)
        if ja is not None:
            item = {**conhecidos[ja["link"]], "link": ja["link"]}
            reusados += 1
        elif time.monotonic() - t0 > orcamento_s:
            estourou = True
            break
        else:
            for d in docs[:2]:
                r = app.http_get(d["link"], timeout=90)
                if not r:
                    continue
                texto, detalhe = _texto_de_download(r)
                item = _montar_release(texto, detalhe, {
                    "fonte": "CVM IPE (copia oficial do release publicado no RI)", "empresa": d["empresa"],
                    "assunto": d["assunto"], "data": d["data"], "link": d["link"],
                    "preferencia": pref})
                if item:
                    baixados += 1
                    break
        if not item:
            continue
        item.setdefault("preferencia", pref)
        _ajustar_periodo(item)
        if _melhor_release(item, achados.get(item["periodo"])):
            achados[item["periodo"]] = item
    return _resumo_releases(fontes, _lista_por_periodo(achados, max_releases), baixados, reusados, estourou,
                            "falha: nao consegui ler nenhum press-release do IPE")


def _documento_release_sec(cik, acc, nomes, filing, form, conhecidos, descartados):
    """Dentro de um 8-K/6-K, o documento que e o release de resultados. (item, reusado).

    `descartados` recebe os links que nao sao release, para nao baixa-los de novo na proxima coleta."""
    primario = filing.get("primaryDocument")

    def nota_nome(n):
        # Release de texto primeiro; apresentacao de slides depois (vira sopa de numeros no PDF);
        # relatorio anual, institucional e owners' day nao sao release de trimestre
        if re.search(r"(?i)annual[-_ ]?report|institutional|owners?[-_ ]?day|20-?f|proxy", n):
            return 0
        if re.search(r"(?i)release|press|\bpr\d", n):
            return 4
        if re.search(r"(?i)present|prese|deck|slides", n):
            return 2
        if re.search(r"(?i)ex[-_]?99|99[-_.]?1|earnings|results", n):
            return 3
        return 0 if n == primario else 1

    docs = [n for n in nomes if n.lower().endswith((".htm", ".html", ".pdf"))
            and not re.search(r"(?i)^r\d+\.htm|-index|xbrl|_lab|_pre|_cal|_def", n)]
    docs.sort(key=nota_nome, reverse=True)
    if form == "8-K":
        docs = [n for n in docs if nota_nome(n) >= 2] or docs[:1]
    else:
        # 6-K: so o exhibit com cara de release ou apresentacao; o principal apenas quando nao ha exhibit
        docs = [n for n in docs if nota_nome(n) >= 2][:2] or docs[:1]
    melhor, melhor_nota = None, 1
    for nome in docs:
        url = SEC_ARQUIVO_URL.format(cik=cik, acc=acc, nome=nome)
        if url in conhecidos:
            if conhecidos[url] is None:
                continue                      # ja conferido antes: nao e release
            return {**conhecidos[url], "link": url}, True
        doc = app.http_get(url, timeout=60, headers=SEC_HEADERS)
        if not doc:
            continue
        texto, detalhe = _texto_de_download(doc)
        if not texto or len(texto) < 1500:
            if _falha_passageira(texto, detalhe):
                app.log(f"SEC {acc}: {nome} sem texto util ({detalhe}); pode ser falha passageira, "
                        f"nao vai para descartados e sera tentado na proxima coleta")
            else:
                descartados.append(url)
            continue
        cabeca = texto[:8000]
        nota = nota_nome(nome)
        if re.search(r"(?i)press release|reports? (first|second|third|fourth|[1-4]q|q[1-4]).{0,40}(quarter|results)"
                     r"|quarterly results|financial results for|results for the (first|second|third|fourth)", cabeca):
            nota += 2
        if re.search(r"(?i)(quarter|trimestre|fiscal year|full[- ]year)", cabeca) and re.search(r"(?i)(results|earnings|resultados)", cabeca):
            nota += 1
        if re.search(r"(?i)interim (condensed )?(consolidated )?financial statements|notes to the (interim|consolidated) financial", cabeca):
            nota -= 1
        if re.search(r"(?i)annual general meeting|extraordinary general meeting|shareholders.? meeting|notice of (meeting|annual)"
                     r"|appointment of|dividend declaration|share repurchase program", cabeca[:3000]):
            nota -= 2
        if nota < 2:
            descartados.append(url)
            continue
        if nota <= melhor_nota:
            continue
        melhor_nota = nota
        melhor = _montar_release(texto, detalhe, {
            "fonte": f"SEC EDGAR ({form}, exhibit do release publicado no RI)", "formulario": form,
            "data": filing.get("filingDate"), "periodo_reportado": filing.get("reportDate"),
            "arquivo_sec": nome, "link": url,
            # preferencia menor = melhor: release de texto (0) antes de apresentacao (2)
            "preferencia": 4 - nota_nome(nome)})
    return melhor, False


def coletar_releases_sec(cik, fontes, conhecidos=None, descartados=None,
                         max_releases=RELEASES_POR_ATIVO, max_filings=60, orcamento_s=RELEASE_ORCAMENTO_S):
    """Ate `max_releases` releases de resultado da SEC (8-K item 2.02 e 6-K), um por trimestre."""
    conhecidos = conhecidos or {}
    descartados = descartados if descartados is not None else []
    if not cik:
        fontes["release_ri"] = "sem CIK"
        return []
    r = app.http_get(SEC_SUBMISSIONS_URL.format(cik=cik), timeout=60, headers=SEC_HEADERS)
    if not r:
        fontes["release_ri"] = "falha: submissions da SEC indisponivel"
        return []
    try:
        rec = r.json().get("filings", {}).get("recent", {})
        filings = [dict(zip(rec.keys(), vals)) for vals in zip(*rec.values())]
    except Exception:
        fontes["release_ri"] = "falha: submissions ilegivel"
        return []
    achados, baixados, reusados, examinados = {}, 0, 0, 0
    t0, estourou = time.monotonic(), False
    for f in filings:
        if len(achados) >= max_releases or examinados >= max_filings:
            break
        form = (f.get("form") or "").upper()
        if form not in ("8-K", "6-K"):
            continue
        if form == "8-K" and "2.02" not in (f.get("items") or ""):
            continue
        examinados += 1
        if time.monotonic() - t0 > orcamento_s:
            estourou = True
            break
        acc = (f.get("accessionNumber") or "").replace("-", "")
        idx = app.http_get(SEC_INDEX_URL.format(cik=cik, acc=acc), timeout=30, headers=SEC_HEADERS)
        if not idx:
            continue
        try:
            nomes = [it["name"] for it in idx.json()["directory"]["item"]]
        except Exception:
            continue
        item, reusado = _documento_release_sec(cik, acc, nomes, f, form, conhecidos, descartados)
        if not item:
            continue
        _ajustar_periodo(item)
        if _melhor_release(item, achados.get(item["periodo"])):
            achados[item["periodo"]] = item
        if reusado:
            reusados += 1
        else:
            baixados += 1
    return _resumo_releases(fontes, _lista_por_periodo(achados, max_releases), baixados, reusados, estourou,
                            f"sem release de resultados nos ultimos {examinados} 8-K/6-K")


# ───────────────── Release de resultados direto no site de RI ─────────────────
# O IPE da CVM e a copia oficial, mas o indice do ano corrente ja saiu do ar
# (ipe_cia_aberta_2026 respondeu 404 em 20/09/2026) e o historico parou no 3T25
# enquanto o ITR ja ia no 2T26. O site de RI da companhia e o caminho
# complementar: quando o release mais novo esta atras do ITR mais novo, a central
# de resultados (mapa em ri_fontes.py) e varrida atras dos trimestres que faltam.
# Tudo aqui roda so no Actions; por isso cada passo deixa uma linha no log.
RI_MIN_CARACTERES = 2000          # menos que isso nao e release: e pagina de erro ou capa
RI_MAX_SEM_PERIODO = 4            # links de arquivo sem trimestre no rotulo: poucos, para nao gastar o orcamento
_RE_RI_CANDIDATO = re.compile(r"RELEASE|RESULTADO|RESULTS|EARNINGS|DIVULGA|\bPRESS")
# Previa operacional (construtoras publicam ~4 semanas antes do release) nunca e o release: sem este
# descarte ela seria o unico documento do trimestre na janela entre previa e release, viraria o
# 'release' do trimestre no branch e trancaria o verdadeiro (ate_periodo) nas coletas seguintes.
_RE_RI_DESCARTE = re.compile(
    r"APRESENTA|PRESENTATION|WEBCAST|VIDEO|TRANSCRI|TELECONF|\bCALL\b|AUDIO|PLANILHA|SPREADSHEET|"
    r"\bXLS|\bZIP\b|INSTITUCIONAL|INSTITUTIONAL|PREVIA|PREVIEW")
# Demonstracoes contabeis, formularios e relatorios ficam na mesma central, muitas vezes ANTES do
# release do trimestre (na central em ingles da MZ: 'ITR 2Q26', 'Financial Statements 2Q26'). Nao
# sao a fala da gestao; so passam se o proprio rotulo disser RELEASE ('Release de Resultados 2T26 (ITR)').
_RE_RI_DEMONSTRACAO = re.compile(
    r"\bITRS?\b|\bDFP\b|\bDFS?\b|DEMONSTRA|INFORMACOES TRIMESTRAIS|BALANCO|COMENTARIO DE DESEMPENHO|"
    r"FINANCIAL STATEMENTS|QUARTERLY INFORMATION|FORMULARIO|\bFRE\b|REFERENCE FORM|"
    r"RELATORIO ANUAL|ANNUAL REPORT|SUSTENTAB|\bESG\b")
_RE_RI_ARQUIVO = re.compile(r"(?i)api\.mziq\.com/mzfilemanager|filemanager-cdn\.mziq\.com|\.pdf(?:[?#]|$)")
_RE_RI_EN = re.compile(r"\bEN\b|ENGLISH|INGL|EARNINGS|\bRESULTS\b")
_RE_RI_PT = re.compile(r"RELEASE|DIVULGA|\bPT\b|PT BR|PORTUGU")
_RE_RI_CORPO = re.compile(r"(?i)receita|revenue|ebitda|lucro|net income|destaques|highlights|margem|margin")
# Numero com unidade de dinheiro: 'R$ 1.234 milhoes', 'R$ milhoes' (cabecalho de tabela), 'US$ 12 million'.
# A cotacao no menu do site ('DIRR3 R$ 22,10 +1,5%') nao passa: nao tem milhoes/bilhoes.
_RE_RI_NUMEROS = re.compile(r"(?i)R\$\s*[\d.,]*\s*(?:milh|bilh|\bmi\b|\bbi\b|\bmm\b)|\d[\d.,]*\s*(?:milh|bilh|million|billion)")
# 'Q2 2026', 'Q2/26', '2T2026': formas que periodo_release nao le e aparecem em rotulo de site
_RE_TRI_SITE = re.compile(r"\b[TQ]([1-4])\s*(?:FY)?\s*(?:20)?(\d{2})\b|\b([1-4])[TQ]20(\d{2})\b")
_RE_ANCORA = re.compile(r"(?is)<a\b([^>]*)>(.*?)</a>")
_RE_HREF = re.compile(r"""(?i)\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
# Abas e acordeoes: o rotulo da aba (<a href="#painel">2T26</a>, <button data-bs-target="#painel">) e o
# id do painel que ela abre; <nav>/<select> sao menu, nunca contexto de um link
_RE_ABA = re.compile(r"(?is)<(a|button)\b([^>]*)>(.*?)</\1>")
_RE_ABA_ALVO = re.compile(r"""(?i)\b(?:href|data-target|data-bs-target)\s*=\s*["']?#([^"'\s>]+)|\baria-controls\s*=\s*["']([^"'\s>]+)""")
_RE_ID = re.compile(r"""(?i)\bid\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_RE_MENU = re.compile(r"(?is)<(nav|select)\b.*?</\1>")
_RE_TITLE = re.compile(r"""(?i)\btitle\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_RE_DATA_NUM = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})\b")
_RE_DATA_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_RE_DATA_EXT = re.compile(r"(?i)\b(\d{1,2})\s+(?:de\s+)?([a-z]{3})[a-z]*\.?,?\s+(?:de\s+)?(20\d{2})\b")
_RE_DATA_EN = re.compile(r"(?i)\b([a-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(20\d{2})\b")
_MESES = {"JAN": 1, "FEV": 2, "FEB": 2, "MAR": 3, "ABR": 4, "APR": 4, "MAI": 5, "MAY": 5, "JUN": 6,
          "JUL": 7, "AGO": 8, "AUG": 8, "SET": 9, "SEP": 9, "OUT": 10, "OCT": 10, "NOV": 11, "DEZ": 12, "DEC": 12}


def _mapa_ri():
    """RI_FONTES de ri_fontes.py: {ticker: {'central': url, 'alternativas': [urls], 'plataforma': 'MZ'}}.

    O valor tambem pode ser so a url da central. Arquivo ausente ou quebrado nao derruba a coleta:
    vira mapa vazio, com uma linha no log."""
    try:
        import ri_fontes
    except ImportError:
        return {}
    except Exception as e:
        app.log(f"ri_fontes.py ilegivel ({type(e).__name__}: {e}); site de RI desligado nesta coleta")
        return {}
    mapa = getattr(ri_fontes, "RI_FONTES", None)
    return mapa if isinstance(mapa, dict) else {}


def _html_da_resposta(r):
    """HTML como texto. Tenta UTF-8 antes do palpite do requests: sem charset no cabecalho ele assume
    latin-1 e 'Apresentacao' vira lixo, o que furaria o filtro de descarte."""
    try:
        return (r.content or b"").decode("utf-8")
    except UnicodeDecodeError:
        return r.text or ""


def _texto_em_volta(html, ini, fim, largura=200):
    """Texto legivel de ate `largura` caracteres antes de [ini] e depois de [fim] no HTML."""
    antes = html[max(0, ini - 4 * largura):ini]
    if "<" not in antes.partition(">")[0] and ">" in antes:
        antes = antes.partition(">")[2]      # o corte caiu no meio de uma tag: joga fora o pedaco
    depois = html[fim:fim + 4 * largura]
    return _html_para_texto(antes)[-largura:], _html_para_texto(depois)[:largura]


def _href_de(atributos):
    h = _RE_HREF.search(atributos)
    return htmlmod.unescape(next(g for g in h.groups() if g is not None)).strip() if h else ""


def _tem_link_de_arquivo(trecho):
    """Ha <a href> para fora da pagina (nao vazio, nao '#', nao javascript:) neste pedaco de HTML?"""
    for m in _RE_ANCORA.finditer(trecho):
        h = _href_de(m.group(1)).lower()
        if h and not h.startswith(("#", "javascript:")):
            return True
    return False


def _abas_e_paineis(html):
    """(html com a barra de abas e o menu apagados, {id do painel: trimestre}).

    Aba ou cabecalho de acordeao e <a href="#..."> (ou <a> sem link, ou <button>) cujo rotulo e um
    trimestre ('2T26'). O id que ela aponta (href, data-target, aria-controls) e o painel: um link de
    arquivo dentro dele herda esse trimestre, o que resolve abas e acordeoes de uma vez.
    Duas ou mais dessas abas em sequencia, sem link de arquivo entre elas, sao a BARRA de abas: todos
    os trimestres listados antes dos paineis. Ela e trocada por espacos (mesmo tamanho, para os
    deslocamentos dos links nao mudarem), senao o ultimo trimestre da barra, o mais antigo, virava o
    'contexto' de todo arquivo do primeiro painel. Cabecalho sozinho, seguido dos seus links, fica:
    e ele o trimestre do acordeao. <nav> e <select> (menu, seletor de trimestre) somem pelo mesmo motivo."""
    limpo = _RE_MENU.sub(lambda m: " " * len(m.group(0)), html)
    paineis, abas = {}, []
    for m in _RE_ABA.finditer(limpo):
        tag, atributos, corpo = m.group(1), m.group(2), m.group(3)
        href = _href_de(atributos).lower()
        if tag == "a" and href and not href.startswith(("#", "javascript:")):
            continue                          # link de verdade, nao e aba
        periodo = _periodo_no_site(_html_para_texto(corpo)[:80], "")
        if not periodo:
            continue
        alvo = _RE_ABA_ALVO.search(atributos)
        alvo_id = next((g for g in alvo.groups() if g), None) if alvo else None
        if alvo_id:
            paineis.setdefault(alvo_id, periodo)
        abas.append((m.start(), m.end()))
    barras, atual = [], []
    for ini, fim in abas:
        if atual and _tem_link_de_arquivo(limpo[atual[-1][1]:ini]):
            barras.append(atual)
            atual = []
        atual.append((ini, fim))
    if atual:
        barras.append(atual)
    pedacos, pos = [], 0
    for barra in barras:
        if len(barra) < 2:
            continue
        ini, fim = barra[0][0], barra[-1][1]
        pedacos.append(limpo[pos:ini])
        pedacos.append(" " * (fim - ini))
        pos = fim
    if pedacos:
        pedacos.append(limpo[pos:])
        limpo = "".join(pedacos)
    return limpo, paineis


def _links_da_pagina(html, url_base):
    """[(url absoluta, texto do ancora, texto antes, texto depois, trimestre do painel)] de cada
    <a href> da pagina. O contexto (antes/depois) vem do HTML sem a barra de abas e sem o menu; o
    trimestre do painel e o da aba/acordeao que abre o bloco em que o link esta (None fora deles)."""
    limpo, paineis = _abas_e_paineis(html)
    ids = [(m.start(), next(g for g in m.groups() if g is not None)) for m in _RE_ID.finditer(limpo)]
    ids = [(pos, i) for pos, i in ids if i in paineis]
    links = []
    for m in _RE_ANCORA.finditer(html):
        atributos, corpo = m.group(1), m.group(2)
        href = _href_de(atributos)
        if not href or href.lower().startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        t = _RE_TITLE.search(atributos)
        titulo = htmlmod.unescape((t.group(1) or t.group(2) or "")) if t else ""
        texto = " ".join(x for x in (_html_para_texto(corpo), titulo) if x).strip()
        antes, depois = _texto_em_volta(limpo, m.start(), m.end())
        painel = next((paineis[i] for pos, i in reversed(ids) if pos < m.start()), None)
        links.append((urljoin(url_base, href), texto[:200], antes, depois, painel))
    return links


def _periodo_no_site(texto, url):
    """Trimestre no rotulo ou na url do link, nas formas da CVM/SEC e nas de site ('Q2 2026')."""
    p = periodo_release(texto, url)
    if p:
        return p
    for alvo in (texto, url):
        m = _RE_TRI_SITE.search(normalizar(alvo))
        if m:
            tri, ano = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            return f"{int(tri)}T{int(ano):02d}"
    return None


def _periodo_no_contexto(antes, depois):
    """Trimestre citado perto do link: o ULTIMO antes dele (a linha ou o acordeao em que o link
    esta), senao o primeiro depois. O primeiro antes seria o da linha de cima. E palpite: o texto
    vem de _links_da_pagina ja sem a barra de abas e sem o menu, mas quem decide e o documento."""
    achados = list(_RE_TRI_CURTO.finditer(normalizar(antes))) + list(_RE_TRI_SITE.finditer(normalizar(antes)))
    if achados:
        m = max(achados, key=lambda x: x.start())
        g = [x for x in m.groups() if x is not None]
        return f"{int(g[0])}T{int(g[1]):02d}"
    return _periodo_no_site(antes, "") or _periodo_no_site(depois, "")


def _data_no_texto(*textos):
    """Primeira data legivel ('12/08/2026', '2026-08-12', '12 de agosto de 2026', 'August 12, 2026')."""
    for t in textos:
        t = str(t or "")
        for rx, ordem in ((_RE_DATA_ISO, "amd"), (_RE_DATA_NUM, "dma"), (_RE_DATA_EXT, "dMa"), (_RE_DATA_EN, "Mda")):
            for m in rx.finditer(t):
                g = m.groups()
                try:
                    if ordem == "amd":
                        ano, mes, dia = int(g[0]), int(g[1]), int(g[2])
                    elif ordem == "dma":
                        dia, mes, ano = int(g[0]), int(g[1]), int(g[2])
                    elif ordem == "dMa":
                        dia, mes, ano = int(g[0]), _MESES.get(normalizar(g[1])[:3], 0), int(g[2])
                    else:
                        mes, dia, ano = _MESES.get(normalizar(g[0])[:3], 0), int(g[1]), int(g[2])
                    return datetime(ano, mes, dia).strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return None


def _hoje():
    """Data de hoje (UTC) como 'AAAA-MM-DD', comparavel com as datas lidas do site."""
    return agora()[:10]


def _trimestre_fechou(periodo, hoje=None):
    """False quando o fim do trimestre e depois de hoje: 'Divulgacao de Resultados 3T26' em setembro
    e a agenda do site (Proximos Eventos), nao release. Sem trimestre legivel devolve True (nao decide)."""
    ano, tri = ordem_periodo(periodo)
    if not tri:
        return True
    return f"{ano}-{_FIM_DO_TRIMESTRE[tri]}" <= (hoje or _hoje())


def _data_estimada_release(periodo):
    """Fim do trimestre + 40 dias (janela tipica de divulgacao) quando o site nao diz a data; nunca
    depois de hoje, porque um release baixado hoje nao pode ter data futura."""
    ano, tri = ordem_periodo(periodo)
    if not tri:
        return None
    fim = datetime.strptime(f"{ano}-{_FIM_DO_TRIMESTRE[tri]}", "%Y-%m-%d")
    return min((fim + timedelta(days=40)).strftime("%Y-%m-%d"), _hoje())


def _trimestres_citados(texto):
    """Todos os trimestres citados no texto, como '2T26' (formas da CVM/SEC e de site: 'Q2 2026')."""
    t = normalizar(texto)
    achados = set()
    for rx, conv in ((_RE_TRI_CURTO, lambda a, b: (int(a), int(b))),
                     (_RE_TRI_LONGO, lambda a, b: (int(a), int(b) % 100)),
                     (_RE_TRI_EN, lambda a, b: (_ORDINAL_EN[a], int(b) % 100))):
        for m in rx.finditer(t):
            tri, ano = conv(m.group(1), m.group(2))
            achados.add(f"{tri}T{ano:02d}")
    for m in _RE_TRI_SITE.finditer(t):
        tri, ano = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        achados.add(f"{int(tri)}T{int(ano):02d}")
    return achados


def _cara_de_release_html(texto, periodo):
    """Pagina HTML so vale como release com evidencia forte. Devolve (True, '') ou (False, motivo).

    O tema do site (menu, rodape, widget 'Proximos Eventos') passa de RI_MIN_CARACTERES e traz
    'Destaques'/'Highlights' no menu, o que enganava a checagem de uma palavra so. Exige: o trimestre
    do rotulo citado no mesmo trecho em que _montar_release le o trimestre (4000 primeiros
    caracteres), ao menos duas palavras de resultado distintas e ao menos dois numeros com R$/milhoes."""
    citados = _trimestres_citados(texto[:4000])
    if periodo and periodo not in citados:
        return False, (f"pagina HTML nao cita {periodo} no comeco do texto "
                       f"(cita {', '.join(sorted(citados, key=ordem_periodo)) or 'nenhum trimestre'})")
    if not periodo and not citados:
        return False, "pagina HTML sem trimestre no comeco do texto"
    trecho = texto[:20000]
    palavras = {m.group(0).lower() for m in _RE_RI_CORPO.finditer(trecho)}
    if len(palavras) < 2:
        return False, (f"pagina HTML com {len(palavras)} palavra(s) de resultado "
                       f"({', '.join(sorted(palavras)) or 'nenhuma'}); release tem 2 ou mais")
    numeros = len(_RE_RI_NUMEROS.findall(trecho))
    if numeros < 2:
        return False, f"pagina HTML com {numeros} numero(s) em R$/milhoes; release tem 2 ou mais"
    return True, ""


_RE_RI_RELEASE = re.compile(r"RELEASE|\bPRESS|DIVULGA")     # a palavra que diz que o documento E o release


def _preferencia_release_site(texto, url):
    """Convencao de _preferencia_release_cvm (portugues 0.5, sem idioma 0.7, ingles 1) com dois ajustes
    do site, onde o rotulo e a unica pista.

    Release em ingles ('Earnings Release', 'Press Release EN') vale 0.6, abaixo dos 0.7 sem idioma
    ('Resultados 2T26'): um documento sem a palavra release nunca deve vencer um release. Arquivo que
    so entrou por ser MZ/PDF, sem release/resultado/earnings no rotulo nem na url, fica em 1.5: pode
    completar um trimestre sem release, mas nunca vence um release rotulado."""
    alvo = f"{normalizar(texto)} {normalizar(url)}"
    if not _RE_RI_CANDIDATO.search(alvo):
        return 1.5
    if _RE_RI_EN.search(alvo):
        return 0.6 if _RE_RI_RELEASE.search(alvo) else 1
    return 0.5 if _RE_RI_PT.search(alvo) else 0.7


_ROTULO_PLATAFORMA = {"mz": "MZ", "riweb": "RiWeb", "proprio": "site proprio"}
_RE_MZ_ID = re.compile(r"(?i)mzfilemanager/v2/d/([0-9a-f-]{36})|mziq\.com/published/([0-9a-f-]{36})")


def _plataforma_ri(mapa, url):
    """Rotulo da plataforma para o campo `fonte`: do mapa, senao inferido da url do documento."""
    p = str(mapa.get("plataforma") or "").lower()
    if p in _ROTULO_PLATAFORMA:
        return _ROTULO_PLATAFORMA[p]
    u = (url or "").lower()
    if "mziq.com" in u:
        return "MZ"
    if "riweb" in u:
        return "RiWeb"
    m = re.match(r"https?://([^/]+)", u)
    return m.group(1) if m else "site"


def _sem_fragmento(url):
    return re.split(r"[?#]", url or "", 1)[0].rstrip("/")


def _candidatos_ri(links, pagina=None):
    """Links da central que parecem release de resultado, com trimestre, data e preferencia.

    Candidato: rotulo ou url com release/resultado/results/earnings/divulga/press, ou arquivo (MZ, PDF).
    Descarte: apresentacao, webcast, video, transcricao, teleconferencia, planilha, zip, institucional
    (mas 'release e apresentacao' num so PDF fica); ITR, DFP, demonstracoes financeiras, financial
    statements, quarterly information e formulario de referencia (mas rotulo com RELEASE fica).
    Trimestre: rotulo/url, senao a aba/acordeao em que o link esta, senao o texto em volta. Os dois
    ultimos sao palpite (origem 'contexto'): nunca descartam um arquivo antes do download, e em
    coletar_releases_ri o documento baixado e quem decide o trimestre.
    Link de pagina (nao arquivo) so entra com o trimestre no proprio rotulo (o menu 'Central de
    Resultados' herdaria o trimestre do acordeao vizinho e viraria um falso release) e com
    preferencia +1: e pagina do site, nao o documento, e nunca vence o arquivo do mesmo trimestre.
    Trimestre que ainda nao fechou ('Divulgacao de Resultados 3T26' em setembro) e agenda, nao
    release: fora. Data futura ao lado do link: pagina e agenda (fora); arquivo perde so a data."""
    por_url, descartados_rotulo = {}, 0
    propria = _sem_fragmento(pagina)
    hoje = _hoje()
    for link in links:
        url, texto, antes, depois = link[:4]
        painel = link[4] if len(link) > 4 else None    # tupla antiga, sem o painel, continua valendo
        if propria and _sem_fragmento(url) == propria:
            continue
        alvo = f"{normalizar(texto)} {normalizar(url)}"
        eh_arquivo = _RE_RI_ARQUIVO.search(url) is not None
        if not (_RE_RI_CANDIDATO.search(alvo) or eh_arquivo):
            continue
        if _RE_RI_DESCARTE.search(alvo) and not ("RELEASE" in alvo and "APRESENTA" in alvo):
            descartados_rotulo += 1
            continue
        if _RE_RI_DEMONSTRACAO.search(alvo) and "RELEASE" not in alvo:
            descartados_rotulo += 1     # demonstracao contabil ao lado do release: nao e a fala da gestao
            continue
        periodo, origem = _periodo_no_site(texto, url), "rotulo"
        if not periodo:
            if not eh_arquivo:
                continue
            periodo, origem = painel or _periodo_no_contexto(antes, depois), "contexto"
            if periodo and not _trimestre_fechou(periodo, hoje):
                # Arquivo nao e release de trimestre aberto: o palpite veio da agenda vizinha, nao dele.
                # Fica sem trimestre e e baixado como tal; o documento diz o que e.
                app.log(f"site de RI: '{texto[:60]}' ({url[:90]}): contexto diz {periodo}, trimestre ainda nao "
                        f"fechou (hoje {hoje}); palpite ignorado, o documento decide")
                periodo = None
        if periodo and not _trimestre_fechou(periodo, hoje):
            descartados_rotulo += 1
            app.log(f"site de RI: descartou '{texto[:60]}' ({url[:90]}): trimestre {periodo} ainda nao fechou "
                    f"(hoje {hoje}); e agenda, nao release")
            continue
        data = _data_no_texto(texto, antes, depois)
        if periodo and data and not _periodo_plausivel(periodo, data):
            data = None      # data de outra linha da tabela: melhor estimar do que rotular errado
        if data and data > hoje:
            if not eh_arquivo:
                descartados_rotulo += 1
                app.log(f"site de RI: descartou '{texto[:60]}' ({url[:90]}): data futura {data}; e agenda, nao release")
                continue
            app.log(f"site de RI: '{texto[:60]}' ({url[:90]}) tem data futura {data} ao lado (agenda vizinha?); "
                    f"data ignorada, sera estimada")
            data = None
        # Link de pagina: +1 para nunca vencer o arquivo (PDF) do mesmo trimestre
        preferencia = _preferencia_release_site(texto, url) + (0 if eh_arquivo else 1)
        c = {"url": url, "texto": texto, "periodo": periodo, "origem_periodo": origem if periodo else None,
             "data": data, "arquivo": eh_arquivo, "preferencia": preferencia}
        atual = por_url.get(url)
        if atual is None or (not atual["periodo"] and periodo) or \
                (bool(periodo) == bool(atual["periodo"]) and c["preferencia"] < atual["preferencia"]):
            por_url[url] = c
    return list(por_url.values()), descartados_rotulo


def coletar_releases_ri(tk, fontes, conhecidos=None, descartados=None, max_releases=RELEASES_POR_ATIVO,
                        orcamento_s=RELEASE_ORCAMENTO_S, ate_periodo=None, preferencias=None):
    """Releases de resultado lidos direto da central de resultados do site de RI (ri_fontes.py).

    Complementa o IPE da CVM: com `ate_periodo` (o release mais novo que ja existe, ex.: '3T25')
    so trimestres MAIS NOVOS sao baixados, mais o proprio `ate_periodo` quando o documento da pagina
    e MELHOR (preferencia menor) que o gravado nesse trimestre, dado por `preferencias`
    ({periodo: preferencia do release no branch}): e o que troca um documento errado no trimestre
    mais novo pelo release de verdade na coleta seguinte, em vez de tranca-lo. `conhecidos`
    (link -> release ja no branch) e reusado; `descartados` recebe os links que nao sao release.
    Devolve a lista mais novo primeiro."""
    conhecidos = conhecidos or {}
    descartados = descartados if descartados is not None else []
    rotulo = f"{tk}: site de RI"
    mapa = _mapa_ri().get(tk)
    if not mapa:
        fontes["release_ri_site"] = "sem mapa de RI"
        app.log(f"{rotulo}: sem entrada em ri_fontes.py; fica so o IPE da CVM")
        return []
    if isinstance(mapa, str):
        mapa = {"central": mapa}
    paginas = [p for p in dict.fromkeys([mapa.get("central")] + list(mapa.get("alternativas") or [])) if p]
    if not paginas:
        fontes["release_ri_site"] = "falha: mapa de RI sem url"
        return []
    t0, estourou = time.monotonic(), False
    candidatos, pagina, motivo, fora_rotulo = [], None, "sem pagina", 0
    for url in paginas:
        if time.monotonic() - t0 > orcamento_s:
            estourou, motivo = True, "orcamento de tempo estourou antes de ler a pagina"
            break
        r = app.http_get(url, timeout=60)
        if not r:
            motivo = f"pagina indisponivel ({url})"
            app.log(f"{rotulo}: {url} nao respondeu 200 (status na linha HTTP acima)")
            continue
        html = _html_da_resposta(r)
        links = _links_da_pagina(html, url)
        cands, fora_rotulo = _candidatos_ri(links, url)
        app.log(f"{rotulo}: {url} ok ({len(html)} caracteres, {len(links)} links, {len(cands)} candidatos, "
                f"{fora_rotulo} descartados pelo rotulo)")
        if cands:
            candidatos, pagina = cands, url
            break
        motivo = f"pagina sem link de release ({url}; {len(links)} links; se forem 0, a pagina e montada por JavaScript)"
        app.log(f"{rotulo}: {motivo}")
    if not candidatos:
        fontes["release_ri_site"] = (f"falha: {motivo}")[:220]
        return []
    plataforma = _plataforma_ri(mapa, next((c["url"] for c in candidatos if c["arquivo"]), pagina))
    # mz_id do mapa e so conferencia (foi inferido por busca): link de outra conta MZ vai para o log,
    # nao e rejeitado, para um id errado no mapa nao apagar a fonte inteira
    mz_id = str(mapa.get("mz_id") or "").lower()
    if mz_id:
        outros = {next(g for g in m.groups() if g) for c in candidatos
                  for m in [_RE_MZ_ID.search(c["url"])] if m and next(g for g in m.groups() if g).lower() != mz_id}
        if outros:
            app.log(f"{rotulo}: ATENCAO: links MZ de outra conta que nao o mz_id do mapa ({mz_id[:8]}...): "
                    f"{', '.join(sorted(o[:8] + '...' for o in outros))}; confira ri_fontes.py se o release vier errado")
    com = [c for c in candidatos if c["periodo"]]
    sem = [c for c in candidatos if not c["periodo"] and c["arquivo"]]
    app.log(f"{rotulo}: trimestres na pagina: "
            f"{', '.join(sorted({c['periodo'] for c in com}, key=ordem_periodo, reverse=True)) or 'nenhum'}"
            f"; {len(sem)} arquivos sem trimestre no rotulo; plataforma {plataforma}")
    corte = ordem_periodo(ate_periodo) if ate_periodo else None
    # Preferencia do release ja gravado no trimestre do corte; sem `preferencias` ninguem disputa o corte
    pref_corte = (preferencias or {}).get(ate_periodo) if ate_periodo else None

    def disputa(periodo, preferencia):
        # Mais novo que o corte, ou o proprio trimestre do corte com documento melhor que o gravado
        o = ordem_periodo(periodo)
        return o > corte or (o == corte and pref_corte is not None and preferencia < pref_corte)

    duvida = []
    if ate_periodo:
        # So o trimestre do ROTULO pula o download. O lido do contexto (aba, acordeao, linha vizinha) e
        # palpite: a barra de abas ja rotulou um release 2T26 como 2T25 e o corte o escondia para sempre.
        # Quem cai no corte so pelo contexto vai para `duvida`: e baixado (poucos por coleta) e o
        # documento decide; se for antigo mesmo, vai para descartados e o indice lembra. Cada link
        # custa um download, uma vez.
        duvida = [c for c in com if c["origem_periodo"] == "contexto" and not disputa(c["periodo"], c["preferencia"])]
        ja_cobertos = sorted({c["periodo"] for c in com if c["origem_periodo"] == "rotulo"
                              and not disputa(c["periodo"], c["preferencia"])}, key=ordem_periodo, reverse=True)
        com = [c for c in com if disputa(c["periodo"], c["preferencia"])]
        melhores = [c for c in com if ordem_periodo(c["periodo"]) == corte]
        app.log(f"{rotulo}: ate {ate_periodo} ja existe ({len(ja_cobertos)} trimestres pulados"
                f"{f'; {len(melhores)} documento(s) de {ate_periodo} melhor(es) que o gravado, preferencia {pref_corte}, disputam' if melhores else ''}); "
                f"faltam {', '.join(sorted({c['periodo'] for c in com}, key=ordem_periodo, reverse=True)) or 'nenhum'}"
                f"{f'; {len(duvida)} arquivo(s) com trimestre so pelo contexto, o documento decide' if duvida else ''}")
    # Mais novo primeiro; dentro do trimestre, portugues antes do ingles
    com.sort(key=lambda c: (ordem_periodo(c["periodo"]), -c["preferencia"]), reverse=True)
    duvida.sort(key=lambda c: (ordem_periodo(c["periodo"]), -c["preferencia"]), reverse=True)
    # Link ja conferido e descartado nao gasta a cota dos palpites: senao ele trancaria a fila e os
    # arquivos atras dele nunca seriam baixados
    duvida = [c for c in duvida if conhecidos.get(c["url"], 1) is not None]
    sem = [c for c in sem if conhecidos.get(c["url"], 1) is not None]
    achados, baixados, reusados, novos_descartes, adiados = {}, 0, 0, [], []
    for c in com + duvida[:RI_MAX_SEM_PERIODO] + sem[:RI_MAX_SEM_PERIODO]:
        if len(achados) >= max_releases:
            break
        p, url = c["periodo"], c["url"]
        if p and p in achados and achados[p].get("preferencia", 1) <= c["preferencia"]:
            continue                      # trimestre ja resolvido por documento igual ou melhor: nem baixa
        if url in conhecidos:
            if conhecidos[url] is None:
                continue                  # ja conferido antes: nao e release
            item = {**conhecidos[url], "link": url}
            reusados += 1
        else:
            if time.monotonic() - t0 > orcamento_s:
                estourou = True
                break
            r = app.http_get(url, timeout=90)
            if not r:
                app.log(f"{rotulo}: {p or 'sem trimestre'} nao baixou ({url[:90]}); tenta na proxima coleta")
                continue                  # falha transitoria: nao vai para descartados
            texto, detalhe = _texto_de_download(r)
            tipo = (r.headers.get("Content-Type") or "").lower()
            if not texto or len(texto) < RI_MIN_CARACTERES:
                motivo = f"sem texto util ({detalhe}; {len(texto or '')} caracteres)"
                # Falha do runner (pypdf), download truncado, pagina de erro ou desafio de WAF nao e
                # veredito sobre o documento: fica em `adiados` e volta a ser tentado na proxima coleta
                if _falha_passageira(texto, detalhe, curto_passageiro=True):
                    adiados.append((url, motivo))
                else:
                    novos_descartes.append((url, motivo))
                continue
            if detalhe == "html":
                # Pagina do tema do site (menu, rodape, agenda) passa do minimo de caracteres e tem
                # 'Destaques' no menu: so entra com trimestre, palavras de resultado e numeros
                ok, porque = _cara_de_release_html(texto, p if c["origem_periodo"] == "rotulo" else None)
                if not ok:
                    # So pagina HTML de verdade (link de pagina, Content-Type text/html, sem cara de
                    # bloqueio) e veredito definitivo; link de arquivo que respondeu HTML e erro do servidor
                    if c["arquivo"]:
                        adiados.append((url, f"{porque}; link de arquivo respondeu HTML no lugar do documento"))
                    elif "html" not in tipo:
                        adiados.append((url, f"{porque}; Content-Type '{tipo[:40]}' nao e text/html"))
                    elif _RE_PAGINA_BLOQUEIO.search(texto[:3000]):
                        adiados.append((url, f"{porque}; pagina de bloqueio ou erro do servidor"))
                    else:
                        novos_descartes.append((url, porque))
                    continue
            # Trimestre do rotulo vale como o assunto do IPE; o do contexto (linha vizinha) so entra
            # se o proprio documento nao disser qual trimestre e
            item = _montar_release(texto, detalhe, {
                "fonte": f"site de RI ({plataforma})", "tipo": "release site RI", "assunto": c["texto"],
                "data": c["data"], "link": url, "periodo": p if c["origem_periodo"] == "rotulo" else None,
                "preferencia": c["preferencia"], "pagina_ri": pagina})
            if item and not item.get("periodo"):
                item["periodo"] = p
            if not item or not item.get("periodo"):
                novos_descartes.append((url, "sem trimestre plausivel"))
                continue
            if not _trimestre_fechou(item["periodo"]):
                novos_descartes.append((url, f"trimestre {item['periodo']} ainda nao fechou (hoje {_hoje()}); "
                                             f"e agenda, nao release"))
                continue
            if p and item["periodo"] != p:
                app.log(f"{rotulo}: contexto dizia {p}, o documento diz {item['periodo']}; fica o documento")
            if not item.get("data") or not _periodo_plausivel(item["periodo"], item["data"]):
                # A pagina nao disse a data, ou disse uma implausivel. O cabecalho do proprio
                # release costuma dizer ("Belo Horizonte, 11 de agosto de 2026"): e a data real,
                # e vale mais que a estimativa de fim do trimestre + 40 dias.
                no_texto = _data_no_texto((item.get("texto") or "")[:2500])
                if no_texto and _periodo_plausivel(item["periodo"], no_texto):
                    item["data"], item["data_estimada"] = no_texto, False
            if not item.get("data"):
                item["data"], item["data_estimada"] = _data_estimada_release(item["periodo"]), True
            elif not _periodo_plausivel(item["periodo"], item["data"]):
                item["data"], item["data_estimada"] = _data_estimada_release(item["periodo"]), True
            baixados += 1
            app.log(f"{rotulo}: baixou {item['periodo']} ({detalhe}; {item['caracteres_total']} caracteres; "
                    f"data {item['data']}{' estimada' if item.get('data_estimada') else ''}; {url[:90]})")
        item.setdefault("preferencia", c["preferencia"])
        _ajustar_periodo(item)
        if ate_periodo and not disputa(item["periodo"], item.get("preferencia", 1)):
            # Este caminho so completa o que falta: um arquivo sem rotulo que se revelou antigo nao
            # disputa com a copia oficial da CVM (trocaria o arquivo no branch a cada coleta)
            if url not in conhecidos:
                novos_descartes.append((url, f"release antigo ({item['periodo']}), ja coberto ate {ate_periodo}"))
            continue
        if _melhor_release(item, achados.get(item["periodo"])):
            achados[item["periodo"]] = item
    for url, porque in novos_descartes:
        descartados.append(url)
        app.log(f"{rotulo}: descartou {url[:90]}: {porque}")
    for url, porque in adiados:
        app.log(f"{rotulo}: adiou {url[:90]}: {porque}; pode ser falha passageira, nao vai para "
                f"descartados e sera baixado de novo na proxima coleta")
    lista = _lista_por_periodo(achados, max_releases)
    periodos = ", ".join(r["periodo"] for r in lista)
    extra = (f"; {len(adiados)} adiado(s) por falha passageira" if adiados else "") + \
            ("; orcamento de tempo estourou, completa na proxima coleta" if estourou else "")
    if lista:
        fontes["release_ri_site"] = f"ok: {periodos} ({baixados} baixados, {reusados} reusados; {plataforma}{extra})"
    else:
        fontes["release_ri_site"] = (f"sem release novo ({len(candidatos)} candidatos na pagina, "
                                     f"{len(com)} mais novos que {ate_periodo or 'nada'}, "
                                     f"{len(duvida[:RI_MAX_SEM_PERIODO]) + len(sem[:RI_MAX_SEM_PERIODO])} conferidos pelo documento, "
                                     f"{len(novos_descartes)} descartados{extra})")
    app.log(f"{rotulo}: {fontes['release_ri_site']}")
    return lista


# ───────────────── Historico de releases no branch (releases/<TICKER>/) ─────────────────
DESCARTE_VALIDADE_DIAS = 90       # descarte de link no index.json vale isso; depois o link e conferido de novo


def _limite_descarte():
    """Data ('AAAA-MM-DD') antes da qual um descarte gravado no index.json venceu."""
    return (datetime.strptime(_hoje(), "%Y-%m-%d") - timedelta(days=DESCARTE_VALIDADE_DIAS)).strftime("%Y-%m-%d")


def carregar_indice_releases(saida, tk):
    """{link: entrada} dos releases ja gravados, para nao baixar o mesmo documento de novo."""
    if not saida:
        return {}
    caminho = os.path.join(saida, "releases", tk, "index.json")
    if not os.path.exists(caminho):
        return {}
    try:
        idx = json.load(open(caminho, encoding="utf-8"))
    except Exception:
        return {}
    conhecidos = {}
    for e in idx.get("releases", []):
        if e.get("link") and e.get("arquivo") and os.path.exists(os.path.join(saida, e["arquivo"])):
            entrada = {k: v for k, v in e.items() if k != "texto"}
            if entrada.get("data_estimada"):
                # Entrada guardada com data estimada (fim do trimestre + 40 dias): o cabecalho do
                # texto guardado costuma trazer a data real. Rederiva aqui, no reuso, para nao
                # depender de baixar de novo.
                try:
                    with open(os.path.join(saida, e["arquivo"]), encoding="utf-8") as fh:
                        cabeca = fh.read(2500)
                    no_texto = _data_no_texto(cabeca)
                    if no_texto and _periodo_plausivel(entrada.get("periodo"), no_texto):
                        entrada["data"], entrada["data_estimada"] = no_texto, False
                except OSError:
                    pass
            conhecidos[e["link"]] = entrada
    # Descarte vale DESCARTE_VALIDADE_DIAS; sem data (indice antigo) ou vencido, o link e conferido de
    # novo: um descarte errado (falha passageira gravada antes desta regra) nao esconde o release para sempre
    datas, limite, vencidos = idx.get("descartados_em") or {}, _limite_descarte(), 0
    for link in idx.get("descartados", []):
        if (datas.get(link) or "") >= limite:
            conhecidos.setdefault(link, None)   # ja conferido antes: nao e release
        else:
            vencidos += 1
    if vencidos:
        app.log(f"{tk}: {vencidos} descarte(s) de release sem data ou com mais de {DESCARTE_VALIDADE_DIAS} dias "
                f"no index.json; esses links serao conferidos de novo")
    return conhecidos


def texto_do_release(saida, entrada):
    """Texto de um release: do proprio objeto quando acabou de ser baixado, senao do arquivo no branch."""
    if entrada.get("texto"):
        return entrada["texto"]
    arq = os.path.join(saida or "", entrada.get("arquivo") or "")
    if entrada.get("arquivo") and os.path.exists(arq):
        try:
            return open(arq, encoding="utf-8").read()
        except OSError:
            return None
    return None


def gravar_releases(saida, tk, lista, descartados=None):
    """Grava um .txt por release em releases/<TK>/ mais o index.json. Devolve o indice sem texto."""
    if not saida or not lista:
        return []
    pasta = os.path.join(saida, "releases", tk)
    os.makedirs(pasta, exist_ok=True)
    indice, usados = [], set()
    for r in lista:
        base = r.get("data") or r.get("periodo") or "sem-data"
        nome, n = f"{base}.txt", 2
        while nome in usados:
            nome, n = f"{base}-{n}.txt", n + 1
        usados.add(nome)
        rel = os.path.join("releases", tk, nome)
        if r.get("texto"):
            with open(os.path.join(saida, rel), "w", encoding="utf-8") as fh:
                fh.write(r["texto"])
        elif r.get("arquivo") and r["arquivo"] != rel and os.path.exists(os.path.join(saida, r["arquivo"])):
            os.replace(os.path.join(saida, r["arquivo"]), os.path.join(saida, rel))
        indice.append({**{k: v for k, v in r.items() if k != "texto"}, "arquivo": rel})
    for antigo in os.listdir(pasta):   # fora da janela dos ultimos N
        if antigo.endswith(".txt") and antigo not in usados:
            try:
                os.remove(os.path.join(pasta, antigo))
            except OSError:
                pass
    descartados = list(dict.fromkeys(descartados or []))[-80:]
    # Data de cada descarte (carregar_indice_releases vence os antigos): a data anterior fica enquanto
    # vale; link novo ou reconferido nesta coleta ganha a data de hoje
    try:
        antes = json.load(open(os.path.join(pasta, "index.json"), encoding="utf-8")).get("descartados_em") or {}
    except Exception:
        antes = {}
    limite, hoje = _limite_descarte(), _hoje()
    descartados_em = {u: antes[u] if (antes.get(u) or "") >= limite else hoje for u in descartados}
    gravar_json(os.path.join(pasta, "index.json"),
                {"ticker": tk, "atualizado_em": agora(),
                 "nota": ("um release por trimestre, do mais novo para o mais antigo; o texto integral "
                          "esta no .txt indicado em `arquivo`, relativo a raiz do branch `dados`; "
                          f"`descartados` sao links conferidos que nao sao release, com a data em "
                          f"`descartados_em` (valem {DESCARTE_VALIDADE_DIAS} dias)"),
                 "releases": indice,
                 "descartados": descartados, "descartados_em": descartados_em})
    return indice


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
    "despesa_juros": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense", "FinanceCosts"],
    "lucro_antes_ir": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "ProfitLossBeforeTax"],
    "imposto_renda": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"],
    "lucro_liquido": ["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "lpa_diluido": ["EarningsPerShareDiluted", "DilutedEarningsLossPerShare"],
    "depreciacao_amortizacao": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"],
    "ativo_total": ["Assets"],
    "caixa": ["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"],
    "patrimonio_liquido": ["StockholdersEquity", "Equity", "EquityAttributableToOwnersOfParent"],
    "divida_curto_prazo": ["DebtCurrent", "LongTermDebtCurrent", "ShorttermBorrowings", "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"],
    "divida_longo_prazo": ["LongTermDebtNoncurrent", "NoncurrentPortionOfNoncurrentBorrowings"],
    # LongTermDebt e o total (circulante + nao circulante) em boa parte dos emissores:
    # fica em linha propria para ninguem somar com divida_curto_prazo. No MELI, o
    # balanco de 30/06/2026 traz 6.482 circulante + 4.144 nao circulante = 10.626,
    # que e exatamente o LongTermDebt.
    "divida_total": ["LongTermDebt", "DebtLongtermAndShorttermCombinedAmount", "Borrowings"],
    "carteira_credito": ["LoansAndLeasesReceivableNetReportedAmount", "NotesReceivableNet", "LoansAndAdvancesToCustomers"],
    "caixa_operacional": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "acoes_diluidas": ["WeightedAverageNumberOfDilutedSharesOutstanding", "DilutedWeightedAverageNumberOfShares"],
    "resultado_financeiro_outros": ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense"],
    "receita_juros": ["InterestAndDividendIncomeOperating", "InterestIncomeOperating", "InterestRevenueExpenseNet", "InterestIncome"],
    "dividendos_pagos": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "DividendsPaidClassifiedAsFinancingActivities"],
    "recompra_acoes": ["PaymentsForRepurchaseOfCommonStock", "PaymentsToAcquireOrRedeemEntitysShares"],
    "passivo_total": ["Liabilities"],
    "contas_a_receber": ["AccountsReceivableNetCurrent", "TradeAndOtherCurrentReceivables"],
    "estoques": ["InventoryNet", "Inventories"],
}
# Linhas por acao ou de contagem: nao derivar o 4T por subtracao
SEC_SEM_DERIVACAO = {"lpa_diluido", "acoes_diluidas"}
# Quando nenhuma tag padrao tem dado recente, procura na taxonomia propria da
# empresa (ex.: meli:...) uma tag com esse padrao. tags_usadas registra qual foi.
SEC_REGEX_FALLBACK = {
    "despesa_juros": r"^(Interest\w*Expense|InterestAndOtherFinancial|Financial\w*(Expense|Charges|Losses|Costs)|Finance(Cost|Expense))",
    "resultado_financeiro_outros": r"^(NonoperatingIncomeExpense|OtherNonoperatingIncomeExpense|FinanceIncomeCost|FinancialResult|"
                                   r"NetFinancial|OtherIncomeExpense|InterestAndOtherFinancial\w*Net)",
    "divida_curto_prazo": r"^(Debt|Borrowings|LoansPayable|ShortTermBorrowings|LoansAndOtherFinancialLiabilities)\w*Current$",
    "divida_longo_prazo": r"^(LongTermDebt|Borrowings|LoansPayable|LoansAndOtherFinancialLiabilities)\w*Noncurrent$",
    "divida_total": r"^(LongTermDebt|Borrowings|LoansPayableAndOtherFinancialLiabilities)$",
}
_SEC_TICKERS = {}


def _parse_serie_sec(serie):
    """Uma tag do companyfacts -> (trimestral, anual, instantanea, unidade), so com frames."""
    unidades = serie.get("units", {})
    unidade = next((u for u in ("USD", "USD/shares", "shares", "BRL") if u in unidades), None) \
        or next(iter(unidades.keys()), None)
    tri, anu, instantanea = {}, {}, False
    for v in unidades.get(unidade, []) if unidade else []:
        frame = v.get("frame")
        if not frame:
            continue
        m = re.fullmatch(r"CY(\d{4})(?:Q([1-4]))?(I?)", frame)
        if not m:
            continue
        ano, tri_n, inst = m.groups()
        if inst:
            # Saldo instantaneo (balanco): CY2025Q2I = saldo em 30/06/2025
            instantanea = True
            if tri_n:
                tri[f"CY{ano}Q{tri_n}"] = v.get("val")
                if tri_n == "4":
                    anu[f"CY{ano}"] = v.get("val")
            else:
                anu[f"CY{ano}"] = v.get("val")
        elif tri_n:
            tri[frame] = v.get("val")
        else:
            anu[frame] = v.get("val")
    return tri, anu, instantanea, unidade


def _ultimo_ano(tri, anu):
    anos = [int(k[2:6]) for k in list(tri) + list(anu)]
    return max(anos) if anos else 0


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
    out = {"cik": cik, "taxonomias": taxonomias, "trimestral": {}, "anual": {}, "tags_usadas": {},
           "unidades": {}, "instantaneas": [], "derivados": {}, "ltm": {}, "desatualizadas": [],
           "nota": ("trimestral: frames CYyyyyQn do XBRL (3 meses; balanco = saldo no fim do trimestre). "
                    "O 4T de fluxo e derivado: anual menos 1T+2T+3T (lista em derivados). "
                    "ltm: soma dos ultimos 4 trimestres consecutivos.")}
    ano_atual = datetime.now(timezone.utc).year
    for nome, candidatos in SEC_LINHAS.items():
        # Entre as tags candidatas, vale a que tem dado mais recente (empresas trocam de tag
        # ao longo dos anos: o InterestExpense do MELI parou em 2011) e, no empate, a mais longa.
        # Ordem de desempate: a posicao na lista de candidatas (Revenues antes de
        # RevenueFromContractWithCustomer, que no MELI exclui a receita de juros do credito);
        # as tags achadas por regex vem depois de todas, e entre elas vale a mais longa.
        opcoes = []
        for ordem, tag in enumerate(candidatos):
            for tx in taxonomias:
                if tag in facts.get(tx, {}):
                    tri, anu, inst, unidade = _parse_serie_sec(facts[tx][tag])
                    if tri or anu:
                        opcoes.append((_ultimo_ano(tri, anu), -ordem, tag, tri, anu, inst, unidade))
                    break
        if nome in SEC_REGEX_FALLBACK and (not opcoes or max(o[0] for o in opcoes) < ano_atual - 1):
            rx = re.compile(SEC_REGEX_FALLBACK[nome])
            for tx, tags in facts.items():
                if tx == "dei":
                    continue
                for tag, serie in tags.items():
                    if rx.search(tag):
                        tri, anu, inst, unidade = _parse_serie_sec(serie)
                        if tri or anu:
                            opcoes.append((_ultimo_ano(tri, anu), -10000 + len(tri) + len(anu), f"{tx}:{tag}", tri, anu, inst, unidade))
        if not opcoes:
            continue
        opcoes.sort(key=lambda o: (o[0], o[1]), reverse=True)
        ultimo_ano, _, tag, tri, anu, instantanea, unidade = opcoes[0]
        if ultimo_ano < ano_atual - 1:
            # A empresa parou de usar a tag (o InterestExpenseDebt do MELI acaba em 2018):
            # fica registrado, mas nao entra no LTM nem nas comparacoes.
            out["desatualizadas"].append(nome)
        # 4T derivado para linhas de fluxo (DRE e caixa), quando ha o anual e os tres trimestres
        if not instantanea and nome not in SEC_SEM_DERIVACAO:
            for chave_ano, total in anu.items():
                ano = chave_ano[2:]
                q = [tri.get(f"CY{ano}Q{n}") for n in (1, 2, 3)]
                if f"CY{ano}Q4" not in tri and total is not None and all(x is not None for x in q):
                    tri[f"CY{ano}Q4"] = total - sum(q)
                    out["derivados"].setdefault(nome, []).append(f"CY{ano}Q4")
        out["trimestral"][nome] = dict(sorted(tri.items())[-max_periodos:])
        out["anual"][nome] = dict(sorted(anu.items())[-15:])
        out["tags_usadas"][nome] = tag
        out["unidades"][nome] = unidade
        if instantanea:
            out["instantaneas"].append(nome)
        elif nome not in SEC_SEM_DERIVACAO and ultimo_ano >= ano_atual - 1:
            ltm = _ltm(out["trimestral"][nome], lambda k: (int(k[2:6]), int(k[7])))
            if ltm:
                out["ltm"][nome] = ltm
    n = len(out["tags_usadas"])
    fontes["sec_xbrl"] = f"ok ({n} linhas; CIK {cik}; 4T derivado em {len(out['derivados'])} linhas)" if n else "vazio"
    return out


def _ltm(serie, chave_ordem):
    """Soma dos ultimos 4 trimestres consecutivos de {rotulo: valor}. None se houver buraco."""
    itens = [(k, v) for k, v in serie.items() if v is not None]
    if len(itens) < 4:
        return None
    itens.sort(key=lambda kv: chave_ordem(kv[0]))
    ultimos = itens[-4:]
    ordens = [chave_ordem(k) for k, _ in ultimos]
    for a, b in zip(ordens, ordens[1:]):
        esperado = (a[0] + 1, 1) if a[1] == 4 else (a[0], a[1] + 1)
        if b != esperado:
            return None
    return {"ate": ultimos[-1][0], "valor": round(sum(v for _, v in ultimos), 6),
            "trimestres": [k for k, _ in ultimos]}


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
# Descricao esperada de cada conta mapeada por codigo. Em banco e seguradora o codigo
# aponta para outra coisa (2.03 e "Provisoes" no Bradesco, "Passivos ao custo amortizado"
# no Itau): se a descricao nao bate, o valor e descartado em vez de enganar o leitor.
CVM_ESPERADO = {
    "ativo_circulante": r"^ATIVO CIRCULANTE", "ativo_nao_circulante": r"^ATIVO NAO CIRCULANTE",
    "caixa_equivalentes": r"^CAIXA", "aplicacoes_financeiras": r"^APLICACOES FINANCEIRAS", "estoques": r"^ESTOQUES",
    "passivo_circulante": r"^PASSIVO CIRCULANTE", "passivo_nao_circulante": r"^PASSIVO NAO CIRCULANTE",
    "emprestimos_curto_prazo": r"^EMPRESTIMOS E FINANCIAMENTOS", "emprestimos_longo_prazo": r"^EMPRESTIMOS E FINANCIAMENTOS",
    "patrimonio_liquido_consolidado": r"^PATRIMONIO LIQUIDO",
    "receita_liquida": r"^RECEITA", "custos": r"^(CUSTO|DESPESAS D[AE] INTERMEDIACAO)",
    "resultado_bruto": r"^RESULTADO BRUTO",
    # normalizar() troca "/" e parenteses por espaco: "Despesas/Receitas Operacionais" vira "DESPESAS RECEITAS OPERACIONAIS"
    "despesas_receitas_operacionais": r"(DESPESAS RECEITAS OPERACIONAIS|RECEITAS DESPESAS OPERACIONAIS|DESPESAS E RECEITAS OPERACIONAIS)",
    "ebit": r"^RESULTADO ANTES DO RESULTADO FINANCEIRO", "resultado_financeiro": r"^RESULTADO FINANCEIRO",
    "resultado_antes_ir": r"^RESULTADO ANTES DOS TRIBUTOS", "imposto_renda": r"^IMPOSTO DE RENDA",
    "resultado_operacoes_continuadas": r"^RESULTADO LIQUIDO DAS OPERACOES CONTINUADAS",
    "lucro_liquido_consolidado": r"^(LUCRO|RESULTADO LIQUIDO)",
    "caixa_operacional": r"^CAIXA LIQUIDO", "caixa_investimento": r"^CAIXA LIQUIDO", "caixa_financiamento": r"^CAIXA LIQUIDO",
}
# Contas reconhecidas pela descricao, para quando o codigo nao serve (plano de instituicao
# financeira) ou a conta nao tem codigo fixo: chave -> (regex na descricao normalizada,
# grupo do codigo, profundidade maxima do codigo).
CVM_SEMANTICAS = {
    "patrimonio_liquido_consolidado": (r"^PATRIMONIO LIQUIDO", "2", 2),
    "lucro_liquido_consolidado": (r"^(LUCRO PREJUIZO( LIQUIDO)?( CONSOLIDADO)? DO (PERIODO|EXERCICIO)|"
                                  r"LUCRO OU PREJUIZO( LIQUIDO)?( CONSOLIDADO)?( DO (PERIODO|EXERCICIO))?|"
                                  r"LUCRO LIQUIDO( CONSOLIDADO)?( DO (PERIODO|EXERCICIO))?|"
                                  r"RESULTADO LIQUIDO DO (PERIODO|EXERCICIO))$", "3", 2),
    "lucro_atribuido_controladores": (r"ATRIBUID[OA] AO?S? (SOCIOS|ACIONISTAS)( D[AEO])?( EMPRESA)? CONTROLADOR(A|ES)|"
                                      r"ATRIBUIVEL AOS (SOCIOS|ACIONISTAS) CONTROLADOR(A|ES)|^ACIONISTAS CONTROLADORES$", "3", 3),
    "resultado_antes_ir": (r"^RESULTADO ANTES DOS TRIBUTOS", "3", 2),
    "imposto_renda": (r"^IMPOSTO DE RENDA E CONTRIBUICAO SOCIAL", "3", 2),
    "caixa_equivalentes": (r"^CAIXA E EQUIVALENTES", "1", 3),
    # "Emprestimos e Adiantamentos em Instituicoes Financeiras" e interbancario, nao carteira de
    # credito: no Inter, a conta 1.02.03.01 com esse nome entrava como carteira e subestimava em
    # dez vezes. So conta a carteira a clientes.
    "carteira_credito": (r"^(OPERACOES DE CREDITO(?! E ARRENDAMENTO A INSTITUICOES)|"
                         r"EMPRESTIMOS E ADIANTAMENTOS (A|AOS) (CLIENTES|COSTUMERS|CUSTOMERS)|"
                         r"EMPRESTIMOS E RECEBIVEIS(?!.*INSTITUICOES)|CARTEIRA DE CREDITO|"
                         r"EMPRESTIMOS E FINANCIAMENTOS A CLIENTES|OPERACOES DE CREDITO E ARRENDAMENTO MERCANTIL)", "1", 4),
    "depositos": (r"^DEPOSITOS( DE CLIENTES)?$", "2", 3),
}
_CVM_ZIPS = {}


def _profundidade(conta):
    return conta.count(".") + 1


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


def _demonstracoes_cvm(arquivos, cd_cvm, tipo, descricoes=None, descartadas=None):
    """Filtra as contas da empresa (ultima versao de cada periodo). tipo = 'dfp' ou 'itr'.

    Cada chave sai de uma conta: a do codigo fixo (CVM_CONTAS) quando a descricao bate com
    CVM_ESPERADO, senao a conta reconhecida pela descricao (CVM_SEMANTICAS). descricoes recebe
    "codigo descricao" da conta usada; descartadas, as contas cujo codigo apontava para outra coisa."""
    candidatos = {}   # (chave, conta) -> {periodo: valor}
    nomes_conta = {}  # conta -> descricao
    alvo = str(int(cd_cvm))
    semanticas = [(chave, re.compile(rx), grupo, prof) for chave, (rx, grupo, prof) in CVM_SEMANTICAS.items()]
    for nome, texto in arquivos.items():
        for row in csv.DictReader(io.StringIO(texto), delimiter=";"):
            try:
                if str(int(row.get("CD_CVM") or 0)) != alvo:
                    continue
            except ValueError:
                continue
            if normalizar(row.get("ORDEM_EXERC") or "") != "ULTIMO":
                continue
            conta = (row.get("CD_CONTA") or "").strip()
            ds = (row.get("DS_CONTA") or "").strip()
            ds_norm = normalizar(ds)
            chaves = []
            if conta in CVM_CONTAS:
                chaves.append(CVM_CONTAS[conta])
            prof = _profundidade(conta)
            for chave, rx, grupo, prof_max in semanticas:
                if prof <= prof_max and (conta == grupo or conta.startswith(grupo + ".")) and rx.search(ds_norm):
                    if chave not in chaves:
                        chaves.append(chave)
            if not chaves:
                continue
            nomes_conta[conta] = ds
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
            for chave in chaves:
                candidatos.setdefault((chave, conta), {})[periodo] = round(valor, 3)

    saida = {}
    por_chave = {}
    for (chave, conta), valores in candidatos.items():
        por_chave.setdefault(chave, []).append((conta, valores))
    for chave, opcoes in por_chave.items():
        escolhida = None
        codigo_fixo = next((c for c, _ in opcoes if CVM_CONTAS.get(c) == chave), None)
        if codigo_fixo is not None:
            esperado = CVM_ESPERADO.get(chave)
            if not esperado or re.search(esperado, normalizar(nomes_conta.get(codigo_fixo, ""))):
                escolhida = codigo_fixo
        if escolhida is None:
            outras = [c for c, _ in opcoes if c != codigo_fixo]
            if outras:
                # Conta reconhecida pela descricao: a mais alta na hierarquia, depois a de menor codigo
                escolhida = sorted(outras, key=lambda c: (_profundidade(c), [int(p) for p in c.split(".")]))[0]
        if escolhida is None:
            if descartadas is not None and codigo_fixo is not None and chave not in descartadas:
                descartadas[chave] = f"{codigo_fixo} {nomes_conta.get(codigo_fixo, '')}"[:90]
            continue
        saida[chave] = dict(next(v for c, v in opcoes if c == escolhida))
        if descricoes is not None and chave not in descricoes:
            # Nome da conta no plano da empresa: em bancos, 3.01 e "Receitas da
            # Intermediacao Financeira". O leitor precisa saber de onde veio o numero.
            descricoes[chave] = f"{escolhida} {nomes_conta.get(escolhida, '')}"[:90]
    return saida


def coletar_cvm_demonstracoes(cd_cvm, fontes):
    if not cd_cvm:
        fontes["cvm_demonstracoes"] = "sem codigo CVM (IPE nao casou a empresa)"
        return {}
    ano = datetime.now(timezone.utc).year
    out = {"cd_cvm": cd_cvm, "unidade": "R$ milhoes", "descricao_contas": {}, "descartadas": {},
           "dfp_anual": {}, "itr_trimestral": {},
           "serie_trimestral": {}, "serie_anual": {}, "derivados": {}, "ltm": {},
           "nota": ("dfp_anual e itr_trimestral: contas consolidadas como a CVM publica (periodo 'inicio..fim'; "
                    "no ITR ha o trimestre de 3 meses e o acumulado no ano). serie_trimestral: cada trimestre "
                    "com 3 meses (fluxo) ou saldo no fim do trimestre (balanco); o 4T e o anual da DFP menos o "
                    "acumulado de 9 meses, e trimestres sem linha de 3 meses saem da diferenca dos acumulados "
                    "(lista em derivados). ltm: soma dos ultimos 4 trimestres consecutivos. descricao_contas: "
                    "codigo e nome da conta usada em cada chave; descartadas: contas cujo codigo fixo apontava "
                    "para outra coisa no plano da empresa (bancos) e por isso ficaram de fora.")}
    for a in (ano - 1, ano - 2, ano - 3):
        arq = _csvs_do_zip(CVM_DFP_URL.format(ano=a))
        if arq:
            for k, v in _demonstracoes_cvm(arq, cd_cvm, "dfp", out["descricao_contas"], out["descartadas"]).items():
                out["dfp_anual"].setdefault(k, {}).update(v)
    for a in (ano, ano - 1, ano - 2):
        arq = _csvs_do_zip(CVM_ITR_URL.format(ano=a))
        if arq:
            for k, v in _demonstracoes_cvm(arq, cd_cvm, "itr", out["descricao_contas"], out["descartadas"]).items():
                out["itr_trimestral"].setdefault(k, {}).update(v)
    for bloco in ("dfp_anual", "itr_trimestral"):
        for k in out[bloco]:
            out[bloco][k] = dict(sorted(out[bloco][k].items()))
    _series_cvm(out)
    if re.search(r"INTERMEDIACAO", normalizar(out["descricao_contas"].get("receita_liquida", ""))):
        out["plano_de_contas"] = "instituicao_financeira"
    else:
        out["plano_de_contas"] = "geral"
    n_a, n_t = len(out["dfp_anual"]), len(out["itr_trimestral"])
    fontes["cvm_demonstracoes"] = (f"ok (DFP: {n_a} contas, ITR: {n_t} contas; serie trimestral: "
                                   f"{len(out['serie_trimestral'])} contas)") if (n_a or n_t) else "vazio: zips da CVM sem a empresa"
    return out


_FIM_TRIMESTRE = {"03-31": 1, "06-30": 2, "09-30": 3, "12-31": 4}


def _series_cvm(out):
    """Monta serie_trimestral, serie_anual, derivados e ltm a partir de dfp_anual e itr_trimestral."""
    fluxo, saldo = {}, {}   # fluxo[conta][ano] = {"3m": {fim: v}, "acum": {fim: v}}; saldo[conta][fim] = v
    for bloco in ("itr_trimestral", "dfp_anual"):
        for conta, itens in out[bloco].items():
            for periodo, v in itens.items():
                if ".." in periodo:
                    ini, fim = periodo.split("..")
                    try:
                        dias = (datetime.strptime(fim, "%Y-%m-%d") - datetime.strptime(ini, "%Y-%m-%d")).days
                    except ValueError:
                        continue
                    ano = fluxo.setdefault(conta, {}).setdefault(fim[:4], {"3m": {}, "acum": {}})
                    if dias <= 100:
                        ano["3m"][fim[5:]] = v
                    if ini[5:] == "01-01":
                        ano["acum"][fim[5:]] = v
                else:
                    saldo.setdefault(conta, {})[periodo] = v
    for conta, anos in fluxo.items():
        serie, derivados = {}, []
        for ano, d in sorted(anos.items()):
            anterior = None
            for fim, n in sorted(_FIM_TRIMESTRE.items()):
                rotulo = f"{ano}T{n}"
                if fim in d["3m"]:
                    serie[rotulo] = d["3m"][fim]
                elif fim in d["acum"] and (n == 1 or anterior is not None):
                    serie[rotulo] = round(d["acum"][fim] - (anterior or 0.0), 3)
                    derivados.append(rotulo)
                if fim in d["acum"]:
                    anterior = d["acum"][fim]
                elif rotulo in serie:
                    anterior = (anterior or 0.0) + serie[rotulo]
                else:
                    anterior = None
            if "12-31" in d["acum"]:
                out["serie_anual"].setdefault(conta, {})[ano] = d["acum"]["12-31"]
        if serie:
            out["serie_trimestral"][conta] = serie
            if derivados:
                out["derivados"][conta] = derivados
            ltm = _ltm(serie, lambda k: (int(k[:4]), int(k[5])))
            if ltm:
                out["ltm"][conta] = ltm
    for conta, itens in saldo.items():
        serie = {}
        for fim, v in sorted(itens.items()):
            n = _FIM_TRIMESTRE.get(fim[5:])
            if n:
                serie[f"{fim[:4]}T{n}"] = v
                if n == 4:
                    out["serie_anual"].setdefault(conta, {})[fim[:4]] = v
        if serie:
            out["serie_trimestral"][conta] = serie


# ───────────────────────── Macro e TIR ─────────────────────────
# Series do BCB que a mesa usa. O CDI mensal (4391) e o acumulado do mes corrente, parcial
# ate a data: para custo do dinheiro vale o CDI anualizado (4389), que ja e taxa ao ano.
SERIES_MACRO = {
    "selic_meta": (432, "Meta Selic (vigente)", "% a.a."),
    "selic_efetiva": (4390, "Selic efetiva acumulada no mes", "% no mes"),
    "cdi_anual": (4389, "CDI anualizado (base 252)", "% a.a."),
    "cdi_mes": (4391, "CDI acumulado no mes corrente, parcial ate a data", "% no mes"),
    "ipca_12m": (13522, "IPCA acumulado 12 meses", "% a.a."),
    "ipca_mes": (433, "IPCA mensal", "% no mes"),
    "dolar_ptax": (1, "Dolar PTAX venda", "R$"),
}


def coletar_macro(fontes):
    out = {}
    for chave, (codigo, nome, unidade) in SERIES_MACRO.items():
        pts = app.sgs_fetch(codigo, 1)
        if pts:
            out[chave] = {"nome": nome, "unidade": unidade, **pts[-1]}
    out["nota"] = ("Para custo do dinheiro use cdi_anual (taxa ao ano). cdi_mes e selic_efetiva sao o acumulado "
                   "do mes em curso e nao se comparam com taxas anuais. A data de selic_meta e o inicio da vigencia.")
    fontes["bcb"] = f"ok ({sum(1 for k in out if k != 'nota')} series)" if len(out) > 1 else "falha: sem resposta"
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


# ───────────────────────── Comparativo de pares ─────────────────────────
def _primeiro(*valores):
    for v in valores:
        if v is not None:
            return v
    return None


def _fracao_dy(v):
    """dividendYield do Yahoo vem em percentual (7,75) ou fracao (0,0775) conforme a versao."""
    if v is None:
        return None
    return round(v / 100, 6) if v > 1 else round(v, 6)


def _ultimos(serie, n):
    """Ultimos n pares (rotulo, valor) de {rotulo: valor}, em ordem cronologica."""
    itens = sorted((k, v) for k, v in (serie or {}).items() if v is not None)
    return itens[-n:]


def _oficial(dados):
    """Resumo das demonstracoes oficiais (CVM ou SEC) para a tabela de pares."""
    cvm = dados.get("cvm_demonstracoes") or {}
    sec = _primeiro((dados.get("subjacente_us") or {}).get("sec_xbrl"), dados.get("sec_xbrl"),
                    dados.get("sec_xbrl_adr")) or {}
    if cvm.get("serie_trimestral"):
        st, ltm = cvm["serie_trimestral"], cvm.get("ltm") or {}
        rec, ebit, ll, pl, fin = ("receita_liquida", "ebit", "lucro_liquido_consolidado",
                                  "patrimonio_liquido_consolidado", "resultado_financeiro")
        if not ltm.get("lucro_liquido_consolidado") and ltm.get("lucro_atribuido_controladores"):
            ll = "lucro_atribuido_controladores"   # plano IFRS de banco: so a linha dos controladores tem 3 meses
        out = {"fonte": "CVM ITR/DFP consolidado", "unidade": "R$ milhoes",
               "plano_de_contas": cvm.get("plano_de_contas", "geral"), "conta_lucro": ll}
    elif sec.get("ltm"):
        st, ltm = sec["trimestral"], sec.get("ltm") or {}
        rec, ebit, ll, pl, fin = "receita", "ebit", "lucro_liquido", "patrimonio_liquido", None
        out = {"fonte": "SEC XBRL (10-Q/10-K/20-F)", "unidade": _moeda_sec(sec), "plano_de_contas": "geral",
               "adr": (dados.get("sec_xbrl_adr") or {}).get("adr")}
    elif (sec.get("anual") or {}).get("receita") or (sec.get("anual") or {}).get("lucro_liquido"):
        # Emissor estrangeiro (20-F): o XBRL so tem o ano fiscal. Vale o ultimo ano, dito com todas as letras.
        return _oficial_anual_sec(sec, dados)
    else:
        return {}
    geral = out["plano_de_contas"] == "geral"
    periodo = (ltm.get(rec) or ltm.get(ll) or {}).get("ate") \
        or max((v.get("ate") for v in ltm.values() if v and v.get("ate")), default=None)
    out["ltm_ate"] = periodo

    def valor_ltm(conta):
        # So entra o LTM que termina no mesmo trimestre da receita: linha parada no tempo fica de fora
        item = ltm.get(conta)
        return item["valor"] if item and item.get("ate") == periodo else None
    for nome, conta in (("receita_ltm", rec), ("ebit_ltm", ebit), ("lucro_ltm", ll), ("resultado_financeiro_ltm", fin)):
        if conta and valor_ltm(conta) is not None:
            out[nome] = valor_ltm(conta)
    if fin is None:
        # SEC: resultado financeiro = outras receitas/despesas nao operacionais menos a despesa de juros
        # (positivo = receita, como na CVM). Registra a composicao para o leitor.
        outros, juros = valor_ltm("resultado_financeiro_outros"), valor_ltm("despesa_juros")
        if outros is not None or juros is not None:
            out["resultado_financeiro_ltm"] = round((outros or 0.0) - (juros or 0.0), 6)
            out["resultado_financeiro_nota"] = ("outros nao operacionais" if outros is not None else "") + \
                (" menos " if outros is not None and juros is not None else "") + \
                ("despesa de juros" if juros is not None else "")
            if juros is not None:
                out["despesa_juros_ltm"] = juros
    receita, ebit_v, lucro = out.get("receita_ltm"), out.get("ebit_ltm"), out.get("lucro_ltm")
    if receita and geral:
        if ebit_v is not None:
            out["margem_ebit_ltm"] = round(ebit_v / receita, 4)
        if lucro is not None:
            out["margem_liquida_ltm"] = round(lucro / receita, 4)
    if ebit_v and out.get("resultado_financeiro_ltm") is not None and geral:
        # Quanto do resultado operacional o custo do dinheiro consome (negativo = despesa)
        out["resultado_financeiro_sobre_ebit"] = round(out["resultado_financeiro_ltm"] / ebit_v, 3)
    saldos = _ultimos(st.get(pl), 5)
    if saldos:
        out["patrimonio_liquido"] = saldos[-1][1]
        out["patrimonio_liquido_em"] = saldos[-1][0]
        if lucro is not None and len(saldos) == 5 and saldos[0][1] and saldos[-1][1]:
            media = (saldos[0][1] + saldos[-1][1]) / 2
            if media > 0:
                out["roe_ltm"] = round(lucro / media, 4)
    rec_tri = _ultimos(st.get(rec), 12)
    if len(rec_tri) >= 8:
        atual = sum(v for _, v in rec_tri[-4:])
        anterior = sum(v for _, v in rec_tri[-8:-4])
        if anterior:
            out["cresc_receita_ltm"] = round(atual / anterior - 1, 4)
    ll_tri = _ultimos(st.get(ll), 12)
    if len(ll_tri) >= 8:
        atual = sum(v for _, v in ll_tri[-4:])
        anterior = sum(v for _, v in ll_tri[-8:-4])
        if anterior and anterior > 0 and atual is not None:
            out["cresc_lucro_ltm"] = round(atual / anterior - 1, 4)
    out["receita_trimestral"] = dict(rec_tri[-10:])
    out["lucro_trimestral"] = dict(ll_tri[-10:])
    if geral:
        ebit_tri = dict(_ultimos(st.get(ebit), 12))
        margens = {}
        for k, v in rec_tri[-10:]:
            if v and ebit_tri.get(k) is not None:
                margens[k] = round(ebit_tri[k] / v, 4)
        out["margem_ebit_trimestral"] = margens
    return out


def _moeda_sec(sec):
    """Moeda das demonstracoes no XBRL: XP, Stone e PagBank reportam a SEC em reais, nao em dolar."""
    un = sec.get("unidades") or {}
    return un.get("receita") or un.get("lucro_liquido") or un.get("patrimonio_liquido") or "USD"


def _oficial_anual_sec(sec, dados):
    """Resumo oficial de quem reporta a SEC so anualmente (20-F): ultimo ano fiscal."""
    an = sec.get("anual") or {}
    anos = sorted(set(an.get("receita", {})) | set(an.get("lucro_liquido", {})))
    if not anos:
        return {}
    ano, ant = anos[-1], (anos[-2] if len(anos) > 1 else None)
    out = {"fonte": "SEC XBRL anual (20-F): ultimo ano fiscal, nao 12 meses correntes", "unidade": _moeda_sec(sec),
           "plano_de_contas": "geral", "periodicidade": "anual", "ltm_ate": ano,
           "adr": (dados.get("sec_xbrl_adr") or {}).get("adr")}
    rec, ebit, luc = an.get("receita", {}).get(ano), an.get("ebit", {}).get(ano), an.get("lucro_liquido", {}).get(ano)
    if rec is not None:
        out["receita_ltm"] = rec
    if ebit is not None:
        out["ebit_ltm"] = ebit
    if luc is not None:
        out["lucro_ltm"] = luc
    if rec and ebit is not None:
        out["margem_ebit_ltm"] = round(ebit / rec, 4)
    if rec and luc is not None:
        out["margem_liquida_ltm"] = round(luc / rec, 4)
    pl_a, pl_b = an.get("patrimonio_liquido", {}).get(ano), (an.get("patrimonio_liquido", {}).get(ant) if ant else None)
    if pl_a:
        out["patrimonio_liquido"], out["patrimonio_liquido_em"] = pl_a, ano
        media = (pl_a + pl_b) / 2 if pl_b else pl_a
        if luc is not None and media > 0:
            out["roe_ltm"] = round(luc / media, 4)
    if ant:
        ra, la = an.get("receita", {}).get(ant), an.get("lucro_liquido", {}).get(ant)
        if rec and ra:
            out["cresc_receita_ltm"] = round(rec / ra - 1, 4)
        if luc is not None and la and la > 0:
            out["cresc_lucro_ltm"] = round(luc / la - 1, 4)
    out["receita_anual"] = dict(sorted(an.get("receita", {}).items())[-5:])
    out["lucro_anual"] = dict(sorted(an.get("lucro_liquido", {}).items())[-5:])
    return out


def linha_comparativa(dados):
    """Uma linha da tabela de pares a partir do JSON do ativo."""
    y = dados.get("yahoo") or {}
    sub = dados.get("subjacente_us") or {}
    base = (sub.get("yahoo") or y) if sub else y   # BDR: multiplos da acao-mae (mesma empresa, mais liquidez)
    info, calc = base.get("info") or {}, base.get("multiplos_calculados") or {}
    fn = {normalizar(k): v for k, v in (dados.get("fundamentus") or {}).items() if isinstance(v, (int, float))}
    ret = y.get("retornos") or {}
    preco = _primeiro(info.get("currentPrice"), info.get("regularMarketPrice"), calc.get("preco_usado"))
    alvo = info.get("targetMeanPrice")
    linha = {
        "ticker": dados["ticker"], "nome": (dados.get("identificacao") or {}).get("nome"),
        "gerado_em": dados.get("gerado_em"), "moeda": info.get("currency"),
        "simbolo_base": base.get("simbolo"),
        "preco": preco, "valor_mercado": info.get("marketCap"), "ev": info.get("enterpriseValue"),
        # Papel da B3: Fundamentus primeiro (padrao brasileiro, consistente no grupo); BDR e EUA: Yahoo da acao-mae
        "pl_12m": _primeiro(fn.get("P L"), calc.get("pl_12m"), info.get("trailingPE")),
        "pl_projetado": _primeiro(info.get("forwardPE"), calc.get("pl_projetado")),
        "pvp": _primeiro(fn.get("P VP"), calc.get("pvp"), info.get("priceToBook")),
        "ev_ebitda": _primeiro(fn.get("EV EBITDA"), calc.get("ev_ebitda"), info.get("enterpriseToEbitda")),
        "dy_12m": _primeiro(calc.get("dy_12m"), fn.get("DIV YIELD"), _fracao_dy(info.get("dividendYield"))),
        "roe": _primeiro(fn.get("ROE"), info.get("returnOnEquity")),
        "roic": fn.get("ROIC"),
        "margem_bruta": _primeiro(info.get("grossMargins"), fn.get("MARG BRUTA")),
        "margem_ebitda": info.get("ebitdaMargins"),
        "margem_ebit": _primeiro(info.get("operatingMargins"), fn.get("MARG EBIT")),
        "margem_liquida": _primeiro(info.get("profitMargins"), fn.get("MARG LIQUIDA")),
        "cresc_receita_yoy": info.get("revenueGrowth"), "cresc_lucro_yoy": info.get("earningsGrowth"),
        "cresc_receita_5a": fn.get("CRES REC 5A"),
        "divida_liquida_ebitda": calc.get("divida_liquida_ebitda"),
        "divida_liquida_pl": _primeiro(fn.get("DIV LIQ PATRIM"),
                                       round(info["debtToEquity"] / 100, 4) if info.get("debtToEquity") is not None else None),
        "beta": info.get("beta"),
        "retorno_12m": ret.get("12m"), "retorno_ytd": ret.get("ytd"),
        "consenso": {"recomendacao": info.get("recommendationKey"), "n_analistas": info.get("numberOfAnalystOpinions"),
                     "alvo_medio": alvo, "upside": round(alvo / preco - 1, 4) if (alvo and preco) else None},
        "tir_real": ((dados.get("tir_modelo") or {}).get("resultado") or {}).get("tir_real"),
        "oficial": _oficial(dados),
        "fontes_ok": sum(1 for v in (dados.get("fontes") or {}).values() if str(v).startswith("ok")),
        "fontes_total": len(dados.get("fontes") or {}),
    }
    if sub:
        linha["preco_bdr_brl"] = (y.get("info") or {}).get("currentPrice")
        linha["paridade"] = (sub.get("paridade_implicita") or {}).get("bdrs_por_acao")
    if (dados.get("pares") or {}).get("tipo") == "financeiro":
        # Banco e seguradora: EV/EBITDA, margens operacionais e divida liquida nao descrevem o negocio
        for k in _METRICAS_NAO_FINANCEIRAS:
            linha[k] = None
    return linha


_METRICAS_NAO_FINANCEIRAS = ["ev_ebitda", "margem_bruta", "margem_ebitda", "margem_ebit", "margem_liquida",
                             "divida_liquida_ebitda", "divida_liquida_pl"]


_METRICAS_MEDIANA = ["pl_12m", "pl_projetado", "pvp", "ev_ebitda", "dy_12m", "roe", "roic", "margem_bruta",
                     "margem_ebitda", "margem_ebit", "margem_liquida", "cresc_receita_yoy", "cresc_lucro_yoy",
                     "divida_liquida_ebitda", "divida_liquida_pl", "beta", "retorno_12m", "retorno_ytd",
                     "oficial.margem_ebit_ltm", "oficial.margem_liquida_ltm", "oficial.roe_ltm",
                     "oficial.cresc_receita_ltm", "oficial.cresc_lucro_ltm", "oficial.resultado_financeiro_sobre_ebit"]


def _mediana(valores):
    v = sorted(x for x in valores if isinstance(x, (int, float)))
    if not v:
        return None
    m = len(v) // 2
    return round(v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2, 4)


def montar_comparativo(grupo, nome, tipo, linhas, pedidos):
    """Tabela de pares: linhas por ticker, mediana do grupo e posicao de cada um."""
    medianas = {}
    ignorar = set(_METRICAS_NAO_FINANCEIRAS + ["oficial.margem_ebit_ltm", "oficial.margem_liquida_ltm",
                                                "oficial.resultado_financeiro_sobre_ebit"]) if tipo == "financeiro" else set()
    for metrica in _METRICAS_MEDIANA:
        if metrica in ignorar:
            continue
        valores = []
        for ln in linhas:
            v = ln.get("oficial", {}).get(metrica[8:]) if metrica.startswith("oficial.") else ln.get(metrica)
            valores.append(v)
        med = _mediana(valores)
        if med is not None:
            medianas[metrica] = {"mediana": med, "n": sum(1 for x in valores if isinstance(x, (int, float)))}
    return {
        "grupo": grupo, "nome": nome, "tipo": tipo, "gerado_em": agora(),
        "tickers_pedidos": pedidos, "tickers": [ln["ticker"] for ln in linhas],
        "leitura": ("financeiro: compare P/L, P/VP, ROE, DY e lucro oficial; ignore EV/EBITDA e margens. "
                    "operacional: EV/EBITDA, margens, alavancagem, crescimento e resultado financeiro sobre EBIT. "
                    "Multiplos de BDR vem da acao-mae nos EUA (simbolo_base); valores oficiais na unidade indicada em oficial.unidade. "
                    "gerado_em de cada linha mostra a idade do dado; linhas velhas vieram do branch e nao desta coleta."),
        "linhas": linhas, "medianas": medianas,
    }


# ───────────────────────── Orquestracao ─────────────────────────
def _itr_mais_novo(dados):
    """Rotulo do trimestre mais novo nas demonstracoes oficiais: '2026T2' (CVM) ou 'CY2026Q2' (SEC).

    Olha a receita liquida; sem ela, qualquer conta. E a referencia de frescor do release."""
    blocos = [(dados.get("cvm_demonstracoes") or {}).get("serie_trimestral"),
              (dados.get("sec_xbrl") or {}).get("trimestral"),
              ((dados.get("subjacente_us") or {}).get("sec_xbrl") or {}).get("trimestral"),
              (dados.get("sec_xbrl_adr") or {}).get("trimestral")]
    for series in blocos:
        if not series:
            continue
        contas = [series["receita_liquida"]] if series.get("receita_liquida") else list(series.values())
        rotulos = [k for s in contas for k, v in s.items() if v is not None and _ano_trimestre(k)]
        if rotulos:
            return max(rotulos, key=_ano_trimestre)
    return None


# Prazo legal de entrega apos o fim do trimestre: ITR em 45 dias (1T a 3T), DFP em 90 dias (4T).
# E a segunda referencia de frescor: se o proprio ITR atrasar ou o zip da CVM sumir, o release
# "em dia com o ITR" continua velho para o calendario, e o site de RI precisa ser consultado.
_PRAZO_DIAS = {1: 45, 2: 45, 3: 45, 4: 90}


def trimestre_vencido(hoje=None):
    """Ultimo trimestre fechado cujo prazo legal de divulgacao ja venceu: '2026T2' (formato da serie CVM).

    Em 21/09/2026 devolve 2026T2 (3T26 so vence em 14/11). None se nao der para calcular."""
    try:
        h = datetime.strptime(str(hoje or agora())[:10], "%Y-%m-%d")
    except ValueError:
        return None
    ano, tri = ordem_periodo(trimestre_anterior(h.strftime("%Y-%m-%d")))
    for _ in range(6):
        if not tri:
            return None
        fim = datetime.strptime(f"{ano}-{_FIM_DO_TRIMESTRE[tri]}", "%Y-%m-%d")
        if (h - fim).days >= _PRAZO_DIAS[tri]:
            return f"{ano}T{tri}"
        tri -= 1
        if tri == 0:
            tri, ano = 4, ano - 1
    return None


def _referencia_frescor(dados):
    """(referencia, origem): o mais novo entre o ITR e o trimestre vencido no calendario."""
    itr = _itr_mais_novo(dados)
    vencido = trimestre_vencido()
    candidatos = [(r, o) for r, o in ((itr, "ITR"), (vencido, "calendario")) if r]
    if not candidatos:
        return None, None
    return max(candidatos, key=lambda ro: _ano_trimestre(ro[0]))


def _completar_pelo_site_ri(tk, dados, fontes, historico, conhecidos, descartados):
    """Quando o release mais novo esta atras da referencia (ITR mais novo ou trimestre vencido no
    calendario, o que for mais novo), busca no site de RI os trimestres que faltam e mescla com o que
    a CVM trouxe, um por trimestre."""
    itr = _itr_mais_novo(dados)
    mais_novo = historico[0].get("periodo") if historico else None
    referencia, origem = _referencia_frescor(dados)
    atraso = defasagem_release(mais_novo, referencia)
    preferencias = {r.get("periodo"): r.get("preferencia", 1) for r in historico if r.get("periodo")}
    # Release mais novo que entrou sem a palavra release no rotulo (arquivo avulso da central, 1.5) ou
    # como documento de outro tipo (2): pode nao ser o release. O site e consultado de novo a cada
    # coleta ate um release rotulado do mesmo trimestre tomar o lugar dele (preferencias + ate_periodo).
    fraco = bool(historico) and historico[0].get("preferencia", 1) > 1
    if historico and atraso <= 0 and not fraco:
        app.log(f"{tk}: release {mais_novo} em dia com o ITR {referencia}; site de RI nao consultado")
        return historico
    if historico and atraso <= 0:
        app.log(f"{tk}: release mais novo {mais_novo} em dia com {referencia}, mas entrou sem rotulo de release "
                f"(preferencia {historico[0].get('preferencia')}); consultando o site de RI atras de um documento melhor")
    else:
        app.log(f"{tk}: release mais novo {mais_novo or 'nenhum'} esta {atraso} trimestre(s) atras de "
                f"{referencia} ({origem}); consultando o site de RI")
    do_site = coletar_releases_ri(tk, fontes, conhecidos, descartados, ate_periodo=mais_novo, preferencias=preferencias)
    if not do_site:
        return historico
    achados = {}
    for item in list(historico) + list(do_site):
        if _melhor_release(item, achados.get(item.get("periodo"))):
            achados[item.get("periodo")] = item
    lista = _lista_por_periodo(achados, RELEASES_POR_ATIVO)
    novos = [r["periodo"] for r in lista if any(r is s for s in do_site)]
    trocados = [p for p in novos if p in preferencias]
    if novos:
        fontes["release_ri"] = (f"{fontes.get('release_ri', '')}; site de RI trouxe {', '.join(novos)}"
                                f"{' (trocou o documento de ' + ', '.join(trocados) + ')' if trocados else ''}; "
                                f"mais novo agora: {lista[0].get('periodo')} ({lista[0].get('data')}{' estimada' if lista[0].get('data_estimada') else ''})")[:400]
    return lista


def _frescor(dados, historico, fontes, releases=True):
    """Bloco `frescor` do JSON: o ITR mais novo, o release mais novo e a distancia entre eles."""
    itr = _itr_mais_novo(dados)
    mais_novo = historico[0].get("periodo") if historico else None
    vencido = trimestre_vencido()
    return {"itr_mais_novo": itr, "release_mais_novo": mais_novo,
            "release_data": historico[0].get("data") if historico else None,
            "release_data_estimada": bool(historico[0].get("data_estimada")) if historico else None,
            "defasagem_trimestres": defasagem_release(mais_novo, itr) if releases else None,
            "calendario_vencido": vencido,
            "defasagem_calendario": defasagem_release(mais_novo, vencido) if (releases and vencido) else None,
            "itr_atras_do_calendario": (defasagem_release(f"{_ano_trimestre(itr)[1]}T{str(_ano_trimestre(itr)[0])[-2:]}", vencido)
                                        if (itr and vencido and _ano_trimestre(itr)) else None),
            "fontes_release": sorted({r.get("fonte") for r in historico if r.get("fonte")}),
            "site_ri": fontes.get("release_ri_site", "nao consultado"),
            "nota": ("defasagem_trimestres: quantos trimestres o release mais novo esta atras do ITR/XBRL "
                     "mais novo (0 = em dia; 99 = sem release; null = coleta sem releases). "
                     "calendario_vencido: ultimo trimestre cujo prazo legal de divulgacao venceu; "
                     "defasagem_calendario e itr_atras_do_calendario medem release e ITR contra ele")}


def coletar_ativo(tk, macro, releases=True, saida=None):
    """JSON completo de um ativo. `saida` e a raiz do branch `dados`, onde fica o historico de releases."""
    fontes = {}
    dados = {"ticker": tk, "gerado_em": agora(), "fontes": fontes}
    grupo = PARES_MOD.grupo_de(tk)
    dados["pares"] = ({"grupo": grupo, "nome": PARES_MOD.PARES[grupo]["nome"], "tipo": PARES_MOD.PARES[grupo]["tipo"],
                       "tickers": PARES_MOD.PARES[grupo]["tickers"], "comparativo": f"comparativos/{grupo}.json"}
                      if grupo else {"grupo": None, "tickers": [], "comparativo": None})
    try:
        dados["yahoo"] = coletar_yahoo(tk, fontes)
    except Exception as e:
        fontes["yahoo"] = f"falha geral: {type(e).__name__}: {e}"[:160]
        dados["yahoo"] = {}
    if eh_simbolo_us(tk):
        dados["fundamentus"], dados["cvm"] = {}, {}
        fontes["fundamentus"] = fontes["cvm"] = "nao se aplica (papel dos EUA)"
    elif eh_bdr(tk):
        dados["fundamentus"] = {}
        fontes["fundamentus"] = "nao se aplica (BDR; indicadores vem da acao-mae em subjacente_us)"
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

    # Releases de resultado do RI: os ultimos 8 trimestres. O mais novo entra inteiro no JSON
    # (`release_ri`); todos ficam em releases/<TICKER>/ no branch, indexados em `releases_historico`.
    historico = []
    if releases:
        descartados = []
        try:
            conhecidos = carregar_indice_releases(saida, tk)
            if eh_simbolo_us(tk):
                historico = coletar_releases_sec(_cik_por_ticker(tk), fontes, conhecidos, descartados)
            elif eh_bdr(tk):
                # O release da acao-mae e o release da empresa
                historico = coletar_releases_sec(_cik_por_ticker(simbolo_subjacente(tk)), fontes, conhecidos, descartados)
            else:
                historico = coletar_releases_cvm((dados.get("cvm") or {}).get("documentos_resultado") or [],
                                                 fontes, conhecidos)
                if not historico and ADR_DE_B3.get(tk):
                    # Sem release na CVM: tenta os 6-K do ADR (mesmo documento, em ingles)
                    historico = coletar_releases_sec(_cik_por_ticker(ADR_DE_B3[tk]), fontes, conhecidos, descartados)
                # Release atras do ITR (IPE do ano corrente fora do ar): completa pelo site de RI
                historico = _completar_pelo_site_ri(tk, dados, fontes, historico, conhecidos, descartados)
            descartados = [k for k, v in conhecidos.items() if v is None] + descartados
        except Exception as e:
            fontes["release_ri"] = f"falha geral: {type(e).__name__}: {e}"[:160]
        try:
            dados["releases_historico"] = gravar_releases(saida, tk, historico, descartados) if saida else \
                [{k: v for k, v in r.items() if k != "texto"} for r in historico]
            if historico:
                dados["release_ri"] = {**historico[0], "texto": texto_do_release(saida, historico[0])}
        except Exception as e:
            fontes["release_ri"] = f"{fontes.get('release_ri', '')} | falha ao gravar: {type(e).__name__}"[:180]

    # BDR: traz tambem a acao-mae nos EUA (demonstracoes, release e paridade implicita)
    if eh_bdr(tk):
        base = simbolo_subjacente(tk)
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
    # Frescor: o release mais novo contra o ITR/XBRL mais novo. E o que o deep search confere
    # antes de escrever; defasagem > 0 e o sinal de que o site de RI precisa entrar (ou de que falhou).
    try:
        dados["frescor"] = _frescor(dados, historico, fontes, releases)
    except Exception as e:
        dados["frescor"] = {"erro": f"{type(e).__name__}: {e}"[:160]}
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
    ap.add_argument("--pares", default="nao",
                    help="auto = coleta os pares do grupo (pares.py) e grava o comparativo; "
                         "lista de tickers = pares explicitos; nao = so os tickers pedidos")
    ap.add_argument("--sem-releases", action="store_true", help="nao baixa o release de resultados (mais rapido)")
    args = ap.parse_args()

    def lista(texto):
        return [t.strip().upper().replace(".SA", "") for t in re.split(r"[,\s;]+", texto or "") if t.strip()]

    tickers = lista(args.tickers)
    if not tickers and not args.snapshot:
        tickers = TIR.tickers_cobertos()
    os.makedirs(args.saida, exist_ok=True)

    # Pares: expande a lista e define os grupos dos comparativos
    pedidos = list(tickers)
    grupos = {}   # chave -> {"nome", "tipo", "tickers"}
    modo_pares = (args.pares or "").strip().lower()
    if modo_pares == "auto":
        for tk in pedidos:
            g = PARES_MOD.grupo_de(tk)
            if g and g not in grupos:
                grupos[g] = {"nome": PARES_MOD.PARES[g]["nome"], "tipo": PARES_MOD.PARES[g]["tipo"],
                             "tickers": list(PARES_MOD.PARES[g]["tickers"])}
    elif modo_pares not in ("", "nao", "no", "false", "0"):
        extra = lista(args.pares)
        if pedidos and extra:
            chave = f"pares_de_{pedidos[0]}"
            g0 = PARES_MOD.grupo_de(pedidos[0])
            grupos[chave] = {"nome": f"Pares escolhidos para {pedidos[0]}",
                             "tipo": PARES_MOD.PARES[g0]["tipo"] if g0 else "operacional",
                             "tickers": pedidos[:1] + [t for t in extra if t != pedidos[0]]}
    for g in grupos.values():
        for tk in g["tickers"]:
            if tk not in tickers:
                tickers.append(tk)

    resumo = {"gerado_em": agora(), "tickers": {}, "snapshot": None, "pares": modo_pares or "nao", "comparativos": {}}
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

    coletados = {}
    for tk in tickers:
        print(f"Coletando {tk}...")
        dados = coletar_ativo(tk, macro, releases=not args.sem_releases, saida=args.saida)
        gravar_json(os.path.join(args.saida, "ativos", f"{tk}.json"), dados)
        coletados[tk] = dados
        resumo["tickers"][tk] = dados["fontes"]
        for k, v in dados["fontes"].items():
            print(f"  {k}: {v}")

    # Comparativos por grupo: linhas desta coleta e, na falta, o JSON ja existente no branch
    for chave, g in grupos.items():
        linhas = []
        for tk in g["tickers"]:
            dados = coletados.get(tk)
            if dados is None:
                caminho = os.path.join(args.saida, "ativos", f"{tk}.json")
                if os.path.exists(caminho):
                    try:
                        dados = json.load(open(caminho, encoding="utf-8"))
                    except Exception:
                        dados = None
            if dados:
                try:
                    linhas.append(linha_comparativa(dados))
                except Exception as e:
                    print(f"  comparativo {chave}: {tk} sem linha ({type(e).__name__}: {e})")
        comp = montar_comparativo(chave, g["nome"], g["tipo"], linhas, [t for t in pedidos if t in g["tickers"]])
        arquivo = f"comparativos/{chave}.json"
        gravar_json(os.path.join(args.saida, arquivo), comp)
        resumo["comparativos"][chave] = {"arquivo": arquivo, "tickers": comp["tickers"], "medianas": len(comp["medianas"])}
        print(f"Comparativo {chave}: {len(linhas)} linhas, {len(comp['medianas'])} medianas -> {arquivo}")

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

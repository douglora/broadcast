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
     guidance, divida por moeda).
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
import unicodedata
from datetime import datetime, timedelta, timezone

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
    fatos = [d for d in docs if d["categoria"] == "Fato Relevante"][:limite]
    outros = [d for d in docs if d["categoria"] != "Fato Relevante"][:limite]
    # Documentos de resultado: o release (mesmo PDF do site de RI) e a apresentacao
    resultado = [d for d in docs if _eh_documento_resultado(d)][:12]
    fontes["cvm"] = (f"ok ({len(fatos)} fatos relevantes, {len(outros)} outros, "
                     f"{len(resultado)} de resultado; casamento {metodo}; "
                     f"empresa: {docs[0]['empresa']})") if docs else "sem documentos casados"
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


_RE_ASSUNTO_RESULTADO = re.compile(
    r"PRESS RELEASE|RELEASE DE RESULTADO|RELEASE RESULTADO|DIVULGACAO DE RESULTADO|DIVULGACAO DOS RESULTADOS|"
    r"EARNINGS RELEASE|EARNINGS|INFORMACOES SOBRE O RESULTADO|RESULTADO DO [1-4]|RESULTADOS DO [1-4]|"
    r"ANALISE GERENCIAL|ANALISE DO DESEMPENHO|COMENTARIO DE DESEMPENHO|RESULTADO [1-4]T|RESULTADOS [1-4]T")


def _classe_documento_resultado(d):
    """'release' (texto de resultados: press-release ou relatorio gerencial), 'apresentacao' ou None."""
    cat, tipo, assunto = normalizar(d["categoria"]), normalizar(d["tipo"]), normalizar(d["assunto"])
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
    if conteudo[:4] == b"%PDF":
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


def _release_reutilizavel(anterior, link):
    """Mesmo documento ja lido na coleta anterior, sem corte menor que o limite atual."""
    if not anterior or anterior.get("link") != link or not anterior.get("texto"):
        return False
    return (not anterior.get("cortado")) or len(anterior["texto"]) >= RELEASE_MAX_CHARS


def _montar_release(texto, detalhe, meta):
    if not texto:
        return None
    texto = texto.strip()
    cortado = len(texto) > RELEASE_MAX_CHARS
    return {**meta, "detalhe": detalhe, "caracteres_total": len(texto), "cortado": cortado,
            "texto": texto[:RELEASE_MAX_CHARS]}


def coletar_release_cvm(documentos, fontes, anterior=None):
    """Baixa o press-release de resultados mais recente entregue a CVM (portugues primeiro).

    `anterior` e o release ja gravado no branch: se o link for o mesmo, reusa o texto."""
    releases = [d for d in documentos if _classe_documento_resultado(d) == "release"]
    if not releases:
        fontes["release_ri"] = "sem press-release no IPE do ano"
        return {}
    # Documentos dos ultimos 20 dias a partir do mais recente (o release e o relatorio gerencial
    # saem juntos ou com dias de diferenca), em ordem de preferencia: relatorio gerencial de banco
    # (mais completo), press-release em portugues, press-release em ingles, comunicado.
    data_max = releases[0]["data"]
    try:
        corte = (datetime.strptime(data_max, "%Y-%m-%d") - timedelta(days=20)).strftime("%Y-%m-%d")
    except ValueError:
        corte = data_max
    do_dia = [d for d in releases if d["data"] >= corte]

    def preferencia(d):
        tipo, assunto = normalizar(d["tipo"]), normalizar(d["assunto"])
        if tipo.startswith("RELATORIO DE ANALISE GERENCIAL"):
            return 0
        if tipo.startswith("PRESS RELEASE"):
            if re.search(r"PORTUGU|\bPT\b|\bPOR\b", assunto):
                return 0.5
            return 1 if re.search(r"INGL|ENGL|\bEN\b|ENGLISH", assunto) else 0.7
        return 2
    do_dia.sort(key=lambda d: (preferencia(d), d["data"] < data_max))
    for d in do_dia[:3]:
        if _release_reutilizavel(anterior, d["link"]):
            fontes["release_ri"] = f"ok ({d['assunto'][:60]}; {d['data']}; reusado da coleta anterior)"
            return anterior
        r = app.http_get(d["link"], timeout=90)
        if not r:
            continue
        texto, detalhe = _texto_de_download(r)
        rel = _montar_release(texto, detalhe, {
            "fonte": "CVM IPE (copia oficial do release publicado no RI)", "empresa": d["empresa"],
            "assunto": d["assunto"], "data": d["data"], "link": d["link"]})
        if rel:
            fontes["release_ri"] = f"ok ({d['assunto'][:60]}; {d['data']}; {detalhe}; {rel['caracteres_total']} caracteres)"
            return rel
    fontes["release_ri"] = f"falha: nao consegui ler {do_dia[0]['assunto'][:60]} ({do_dia[0]['data']})"
    return {}


SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
SEC_ARQUIVO_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{nome}"
_PALAVRAS_RESULTADO = re.compile(r"(?i)(quarter|trimestre|fiscal year|full[- ]year|results|resultados|earnings)")


def coletar_release_sec(cik, fontes, max_filings=20, anterior=None):
    """Exhibit 99 do 8-K (item 2.02) ou 6-K mais recente com resultados trimestrais.

    `anterior` e o release ja gravado no branch: se o link for o mesmo, reusa o texto."""
    if not cik:
        fontes["release_ri"] = "sem CIK"
        return {}
    r = app.http_get(SEC_SUBMISSIONS_URL.format(cik=cik), timeout=60, headers=SEC_HEADERS)
    if not r:
        fontes["release_ri"] = "falha: submissions da SEC indisponivel"
        return {}
    try:
        rec = r.json().get("filings", {}).get("recent", {})
        filings = [dict(zip(rec.keys(), vals)) for vals in zip(*rec.values())]
    except Exception:
        fontes["release_ri"] = "falha: submissions ilegivel"
        return {}
    # Pontua os documentos dos ultimos 8-K/6-K e fica com o melhor: um 6-K pode ser a
    # demonstracao financeira, outro o press-release; o nome do arquivo e o inicio do
    # texto dizem qual e qual.
    examinados, melhor, melhor_nota = 0, None, -1
    for f in filings:
        form = (f.get("form") or "").upper()
        if form not in ("8-K", "6-K"):
            continue
        if form == "8-K" and "2.02" not in (f.get("items") or ""):
            continue
        examinados += 1
        if examinados > max_filings or melhor_nota >= 5:
            break
        acc = (f.get("accessionNumber") or "").replace("-", "")
        idx = app.http_get(SEC_INDEX_URL.format(cik=cik, acc=acc), timeout=30, headers=SEC_HEADERS)
        if not idx:
            continue
        try:
            nomes = [it["name"] for it in idx.json()["directory"]["item"]]
        except Exception:
            continue
        docs = [n for n in nomes if n.lower().endswith((".htm", ".html", ".pdf")) and not re.search(r"(?i)^r\d+\.htm|-index|xbrl|_lab|_pre|_cal|_def", n)]
        primario = f.get("primaryDocument")

        def nota_nome(n):
            if re.search(r"(?i)ex[-_]?99|99[-_.]?1", n):
                return 3
            if re.search(r"(?i)release|earnings|results|press|\bpr\d", n):
                return 3
            return 0 if n == primario else 1
        docs.sort(key=nota_nome, reverse=True)
        if form == "8-K":
            docs = [n for n in docs if nota_nome(n) >= 3] or docs[:1]
        else:
            # 6-K: baixa so o exhibit com cara de release; o documento principal apenas quando nao ha exhibit
            docs = [n for n in docs if nota_nome(n) >= 3][:2] or docs[:1]
        for nome in docs:
            url = SEC_ARQUIVO_URL.format(cik=cik, acc=acc, nome=nome)
            reusado = _release_reutilizavel(anterior, url)
            if reusado:
                texto, detalhe = anterior["texto"], anterior.get("detalhe")
            else:
                doc = app.http_get(url, timeout=60, headers=SEC_HEADERS)
                if not doc:
                    continue
                texto, detalhe = _texto_de_download(doc)
            if not texto or len(texto) < 1500:
                continue
            cabeca = texto[:8000]
            nota = nota_nome(nome)
            if re.search(r"(?i)press release|reports? (first|second|third|fourth|[1-4]q|q[1-4]).{0,40}(quarter|results)|quarterly results|financial results for|results for the (first|second|third|fourth)", cabeca):
                nota += 2
            if re.search(r"(?i)(quarter|trimestre|fiscal year|full[- ]year)", cabeca) and re.search(r"(?i)(results|earnings|resultados)", cabeca):
                nota += 1
            if re.search(r"(?i)interim (condensed )?(consolidated )?financial statements|notes to the (interim|consolidated) financial", cabeca):
                nota -= 1
            if re.search(r"(?i)annual general meeting|extraordinary general meeting|shareholders.? meeting|notice of (meeting|annual)|appointment of|dividend declaration|share repurchase program", cabeca[:3000]):
                nota -= 2
            if nota < 2:
                continue
            if nota > melhor_nota:
                melhor_nota = nota
                melhor = anterior if reusado else _montar_release(texto, detalhe, {
                    "fonte": f"SEC EDGAR ({form}, exhibit do release publicado no RI)", "formulario": form,
                    "data": f.get("filingDate"), "periodo_reportado": f.get("reportDate"), "arquivo": nome,
                    "link": url})
    if melhor:
        fontes["release_ri"] = (f"ok ({melhor.get('formulario')} de {melhor.get('data')}; {melhor.get('arquivo') or melhor.get('link', '')[-40:]}; "
                                f"{melhor.get('caracteres_total')} caracteres{'; reusado da coleta anterior' if melhor is anterior else ''})")
        return melhor
    fontes["release_ri"] = f"sem release de resultados nos ultimos {examinados} 8-K/6-K"
    return {}


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
    "carteira_credito": (r"^(OPERACOES DE CREDITO|EMPRESTIMOS E ADIANTAMENTOS|EMPRESTIMOS E RECEBIVEIS|"
                         r"CARTEIRA DE CREDITO|EMPRESTIMOS E FINANCIAMENTOS A CLIENTES|OPERACOES DE CREDITO E ARRENDAMENTO)", "1", 4),
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
    elif sec.get("trimestral"):
        st, ltm = sec["trimestral"], sec.get("ltm") or {}
        rec, ebit, ll, pl, fin = "receita", "ebit", "lucro_liquido", "patrimonio_liquido", None
        out = {"fonte": "SEC XBRL (10-Q/10-K/20-F)", "unidade": "USD", "plano_de_contas": "geral",
               "adr": (dados.get("sec_xbrl_adr") or {}).get("adr")}
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
def coletar_ativo(tk, macro, releases=True, anterior=None):
    """JSON completo de um ativo. `anterior` e o JSON ja gravado no branch (reuso do release)."""
    fontes = {}
    dados = {"ticker": tk, "gerado_em": agora(), "fontes": fontes}
    anterior = anterior or {}
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

    # Demonstracoes oficiais e release de resultados (copia oficial do que o RI publica)
    if eh_simbolo_us(tk):
        try:
            dados["sec_xbrl"] = coletar_sec_xbrl(tk, fontes)
        except Exception as e:
            fontes["sec_xbrl"] = f"falha geral: {type(e).__name__}: {e}"[:160]
        if releases:
            try:
                dados["release_ri"] = coletar_release_sec(_cik_por_ticker(tk), fontes, anterior=anterior.get("release_ri"))
            except Exception as e:
                fontes["release_ri"] = f"falha geral: {type(e).__name__}: {e}"[:160]
    else:
        try:
            dados["cvm_demonstracoes"] = coletar_cvm_demonstracoes((dados.get("cvm") or {}).get("codigo_cvm"), fontes)
        except Exception as e:
            fontes["cvm_demonstracoes"] = f"falha geral: {type(e).__name__}: {e}"[:160]
        if releases:
            try:
                dados["release_ri"] = coletar_release_cvm((dados.get("cvm") or {}).get("documentos_resultado") or [],
                                                          fontes, anterior=anterior.get("release_ri"))
            except Exception as e:
                fontes["release_ri"] = f"falha geral: {type(e).__name__}: {e}"[:160]
        adr = ADR_DE_B3.get(tk)
        if adr:
            try:
                dados["sec_xbrl_adr"] = {"adr": adr, **coletar_sec_xbrl(adr, fontes)}
            except Exception as e:
                fontes["sec_xbrl"] = f"falha geral: {type(e).__name__}: {e}"[:160]
            if releases and not dados.get("release_ri"):
                # Sem release na CVM: tenta o 6-K do ADR (mesmo documento, em ingles)
                try:
                    dados["release_ri"] = coletar_release_sec(_cik_por_ticker(adr), fontes, anterior=anterior.get("release_ri"))
                except Exception as e:
                    fontes["release_ri"] = f"falha geral: {type(e).__name__}: {e}"[:160]

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
            if releases:
                try:
                    rel_ant = (anterior.get("subjacente_us") or {}).get("release_ri")
                    dados["subjacente_us"]["release_ri"] = coletar_release_sec(_cik_por_ticker(base), fontes_sub, anterior=rel_ant)
                except Exception as e:
                    fontes_sub["release_ri"] = f"falha geral: {type(e).__name__}: {e}"[:160]
                if not dados.get("release_ri") and dados["subjacente_us"].get("release_ri"):
                    # O release da acao-mae e o release da empresa: fica tambem no topo do JSON
                    dados["release_ri"] = dados["subjacente_us"]["release_ri"]
                    fontes["release_ri"] = f"ok (via acao-mae {base}: {fontes_sub.get('release_ri', '')[:100]})"
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
        anterior = None
        caminho = os.path.join(args.saida, "ativos", f"{tk}.json")
        if os.path.exists(caminho):
            try:
                anterior = json.load(open(caminho, encoding="utf-8"))
            except Exception:
                anterior = None
        dados = coletar_ativo(tk, macro, releases=not args.sem_releases, anterior=anterior)
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

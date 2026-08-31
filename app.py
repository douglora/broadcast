#!/usr/bin/env python3
"""
BROADCAST — The Invest Post
Servidor do terminal de mercado (estilo Bloomberg).

Sobe em http://localhost:5051 e serve tanto o front (index.html) quanto
todos os endpoints /api/* que ele consome.

    python app.py                # porta 5051, abre o navegador sozinho
    python app.py --port 5050    # outra porta
    python app.py --no-open      # nao abrir o navegador
    PORT=8080 python app.py      # via variavel de ambiente

Nao precisa instalar nada antes: as dependencias que faltarem sao instaladas
na primeira execucao. Se a porta estiver ocupada, o servidor pega a proxima
livre sozinho. Se ja houver um BROADCAST rodando, so abre o navegador nele.

Principio de projeto: o terminal SEMPRE abre.
Nenhuma requisicao HTTP do navegador espera por uma fonte externa — os dados
sao atualizados por threads em segundo plano e os endpoints respondem
instantaneamente a partir do cache. Se uma fonte cair (Yahoo, BCB, CVM...),
o painel correspondente mostra o ultimo dado bom em vez de travar a tela.
"""

import argparse
import csv
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

DEPENDENCIAS = (
    ("flask", "flask"),
    ("flask_cors", "flask-cors"),
    ("requests", "requests"),
    ("feedparser", "feedparser"),
)


def _garantir_dependencias():
    """Instala o que faltar na primeira execucao, para nao exigir setup manual."""
    faltando = []
    for modulo, pacote in DEPENDENCIAS:
        try:
            __import__(modulo)
        except ImportError:
            faltando.append(pacote)
    if not faltando:
        return

    print(f"Instalando dependencias que faltam: {', '.join(faltando)}")
    print("(so acontece na primeira vez)")
    base = [sys.executable, "-m", "pip", "install", "--quiet"]
    if subprocess.run(base + faltando).returncode != 0:
        # Em Python de sistema o pip costuma exigir --user
        subprocess.run(base + ["--user"] + faltando)

    ainda_falta = []
    for modulo, pacote in DEPENDENCIAS:
        try:
            __import__(modulo)
        except ImportError:
            ainda_falta.append(pacote)
    if ainda_falta:
        print("\nNao consegui instalar: " + ", ".join(ainda_falta))
        print("Rode manualmente e tente de novo:")
        print(f"  {sys.executable} -m pip install " + " ".join(ainda_falta))
        sys.exit(1)
    print("Dependencias prontas.\n")


_garantir_dependencias()

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DEFAULT_PORT = 5051
HTTP_TIMEOUT = 8            # nenhuma fonte externa segura o servidor por mais que isso
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SEC_UA = "BROADCAST Terminal (contato: admin@theinvestpost.local)"

app = Flask(__name__, static_folder=None)
CORS(app)


# ─────────────────────────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────────────────────────
class Cache:
    """Cache em memoria com escrita atomica. Leitura nunca bloqueia em rede."""

    def __init__(self):
        self._lock = threading.Lock()
        self._d = {}
        self._stamp = {}

    def set(self, key, value):
        with self._lock:
            self._d[key] = value
            self._stamp[key] = time.time()

    def get(self, key, default=None):
        with self._lock:
            return self._d.get(key, default)

    def age(self, key):
        with self._lock:
            t = self._stamp.get(key)
        return None if t is None else time.time() - t

    def has(self, key):
        with self._lock:
            return key in self._d


CACHE = Cache()


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def naive_utc_iso(dt):
    """O front faz new Date(pub + 'Z'), entao 'pub' vai sem timezone, em UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def http_get(url, timeout=HTTP_TIMEOUT, headers=None, **kw):
    """GET tolerante a falha: devolve o Response ou None. Nunca levanta excecao."""
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    try:
        r = requests.get(url, headers=h, timeout=timeout, **kw)
        if r.status_code == 200:
            return r
        log(f"HTTP {r.status_code} em {url[:90]}")
    except Exception as e:
        log(f"falha em {url[:90]}: {type(e).__name__}")
    return None


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        log(f"nao consegui gravar {os.path.basename(path)}: {e}")


# ─────────────────────────────────────────────────────────────
# UNIVERSO DE ATIVOS
# categoria precisa bater com o front: futures | commodity | forex | index | etf | b3 | us
# ─────────────────────────────────────────────────────────────
UNIVERSE = [
    # ── FUTUROS ──
    ("ES=F", "S&P 500 Futuro", "futures"),
    ("NQ=F", "Nasdaq Futuro", "futures"),
    ("YM=F", "Dow Futuro", "futures"),
    ("RTY=F", "Russell Futuro", "futures"),

    # ── INDICES ──
    ("^BVSP", "Ibovespa", "index"),
    ("^GSPC", "S&P 500", "index"),
    ("^IXIC", "Nasdaq", "index"),
    ("^DJI", "Dow Jones", "index"),
    ("^VIX", "VIX", "index"),
    ("^TNX", "US 10Y", "index"),
    ("^N225", "Nikkei 225", "index"),
    ("^GDAXI", "DAX", "index"),
    ("^FTSE", "FTSE 100", "index"),
    ("^HSI", "Hang Seng", "index"),
    ("^KS11", "Kospi", "index"),
    ("000001.SS", "Shanghai", "index"),

    # ── CAMBIO ──
    ("USDBRL=X", "Dolar/Real", "forex"),
    ("EURBRL=X", "Euro/Real", "forex"),
    ("GBPBRL=X", "Libra/Real", "forex"),
    ("EURUSD=X", "Euro/Dolar", "forex"),
    ("DX-Y.NYB", "Indice DXY", "forex"),

    # ── COMMODITIES ──
    ("BZ=F", "Petroleo Brent", "commodity"),
    ("CL=F", "Petroleo WTI", "commodity"),
    ("NG=F", "Gas Natural", "commodity"),
    ("GC=F", "Ouro", "commodity"),
    ("SI=F", "Prata", "commodity"),
    ("HG=F", "Cobre", "commodity"),
    ("PL=F", "Platina", "commodity"),
    ("PA=F", "Paladio", "commodity"),
    ("ZS=F", "Soja", "commodity"),
    ("ZC=F", "Milho", "commodity"),
    ("ZW=F", "Trigo", "commodity"),
    ("KC=F", "Cafe", "commodity"),
    ("SB=F", "Acucar", "commodity"),
    ("CT=F", "Algodao", "commodity"),
    ("LE=F", "Boi Gordo", "commodity"),

    # ── ACOES B3 ──
    ("PETR4.SA", "Petrobras PN", "b3"),
    ("VALE3.SA", "Vale ON", "b3"),
    ("ITUB4.SA", "Itau Unibanco PN", "b3"),
    ("BBDC4.SA", "Bradesco PN", "b3"),
    ("BBAS3.SA", "Banco do Brasil ON", "b3"),
    ("ABEV3.SA", "Ambev ON", "b3"),
    ("WEGE3.SA", "WEG ON", "b3"),
    ("B3SA3.SA", "B3 ON", "b3"),
    ("BPAC11.SA", "BTG Pactual UNT", "b3"),
    ("ITSA4.SA", "Itausa PN", "b3"),
    ("PRIO3.SA", "PRIO ON", "b3"),
    ("SUZB3.SA", "Suzano ON", "b3"),
    ("RENT3.SA", "Localiza ON", "b3"),
    ("EQTL3.SA", "Equatorial ON", "b3"),
    ("RADL3.SA", "Raia Drogasil ON", "b3"),
    ("TOTS3.SA", "Totvs ON", "b3"),
    ("SBSP3.SA", "Sabesp ON", "b3"),
    ("VIVT3.SA", "Vivo ON", "b3"),
    ("GGBR4.SA", "Gerdau PN", "b3"),
    ("CSNA3.SA", "CSN ON", "b3"),
    ("USIM5.SA", "Usiminas PNA", "b3"),
    ("KLBN11.SA", "Klabin UNT", "b3"),
    ("UGPA3.SA", "Ultrapar ON", "b3"),
    ("VBBR3.SA", "Vibra ON", "b3"),
    ("CSAN3.SA", "Cosan ON", "b3"),
    ("ELET3.SA", "Eletrobras ON", "b3"),
    ("CPLE6.SA", "Copel PNB", "b3"),
    ("TAEE11.SA", "Taesa UNT", "b3"),
    ("HAPV3.SA", "Hapvida ON", "b3"),
    ("MGLU3.SA", "Magazine Luiza ON", "b3"),

    # ── ACOES EUA ──
    ("AAPL", "Apple", "us"),
    ("MSFT", "Microsoft", "us"),
    ("NVDA", "NVIDIA", "us"),
    ("GOOGL", "Alphabet", "us"),
    ("AMZN", "Amazon", "us"),
    ("META", "Meta Platforms", "us"),
    ("TSLA", "Tesla", "us"),
    ("BRK-B", "Berkshire Hathaway", "us"),
    ("JPM", "JPMorgan", "us"),
    ("V", "Visa", "us"),
    ("XOM", "Exxon Mobil", "us"),
    ("JNJ", "Johnson & Johnson", "us"),
    ("WMT", "Walmart", "us"),
    ("AMD", "AMD", "us"),
    ("NFLX", "Netflix", "us"),
]

# ETFs carregam 'region' — o front usa o ultimo token para escolher a bandeira
ETFS = [
    ("EWZ", "iShares MSCI Brazil", "Brasil BR"),
    ("SPY", "SPDR S&P 500", "EUA US"),
    ("QQQ", "Invesco Nasdaq 100", "Nasdaq Tech"),
    ("IWM", "iShares Russell 2000", "Russell Small"),
    ("EFA", "iShares MSCI EAFE", "Desenvolvidos GL"),
    ("EEM", "iShares MSCI Emerging", "Emergentes EM"),
    ("FXI", "iShares China Large-Cap", "China CN"),
    ("EWJ", "iShares MSCI Japan", "Japao JP"),
    ("EWG", "iShares MSCI Germany", "Alemanha DE"),
    ("EWU", "iShares MSCI UK", "Reino Unido GB"),
    ("EWC", "iShares MSCI Canada", "Canada CA"),
    ("EWY", "iShares MSCI South Korea", "Coreia KR"),
    ("EWT", "iShares MSCI Taiwan", "Taiwan TW"),
    ("INDA", "iShares MSCI India", "India IN"),
    ("EWA", "iShares MSCI Australia", "Australia AU"),
]

CRYPTOS = [
    ("BTC", "Bitcoin", "BTC-USD"),
    ("ETH", "Ethereum", "ETH-USD"),
    ("BNB", "BNB", "BNB-USD"),
    ("SOL", "Solana", "SOL-USD"),
    ("XRP", "XRP", "XRP-USD"),
    ("ADA", "Cardano", "ADA-USD"),
]

TICKER_META = {t: (name, cat) for t, name, cat in UNIVERSE}
for t, name, region in ETFS:
    TICKER_META[t] = (name, "etf")
ETF_REGION = {t: region for t, _, region in ETFS}
ALL_QUOTE_TICKERS = list(TICKER_META.keys())


# ─────────────────────────────────────────────────────────────
# COTACOES — Yahoo Finance (endpoint /v8/chart, sem necessidade de crumb)
# ─────────────────────────────────────────────────────────────
YAHOO_HOSTS = ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]


def yahoo_chart(symbol, rng="5d", interval="1d", timeout=HTTP_TIMEOUT):
    for host in YAHOO_HOSTS:
        url = f"{host}/v8/finance/chart/{requests.utils.quote(symbol)}?range={rng}&interval={interval}"
        r = http_get(url, timeout=timeout)
        if not r:
            continue
        try:
            res = r.json()["chart"]["result"]
            if res:
                return res[0]
        except Exception:
            continue
    return None


def quote_from_chart(res):
    """Extrai preco e variacao % de um resultado do endpoint chart."""
    meta = res.get("meta") or {}
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")

    # Se o meta nao trouxer o fechamento anterior, tira das series.
    if prev in (None, 0):
        try:
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) >= 2:
                prev = closes[-2]
                if price is None:
                    price = closes[-1]
        except Exception:
            pass
    if price is None:
        return None
    try:
        change = ((price - prev) / prev * 100.0) if prev else 0.0
    except Exception:
        change = 0.0
    return {"price": round(float(price), 6), "change_pct": round(float(change), 4)}


def fetch_quotes_batch(tickers):
    """Busca varios tickers em paralelo. Tickers que falharem sao omitidos."""
    out = {}

    def one(tk):
        res = yahoo_chart(tk, rng="5d", interval="1d")
        if not res:
            return tk, None
        return tk, quote_from_chart(res)

    with ThreadPoolExecutor(max_workers=12) as pool:
        for tk, q in pool.map(one, tickers):
            if q:
                out[tk] = q
    return out


def refresh_quotes():
    """Atualiza /api/quotes e /api/quotes_fast. Preserva o ultimo valor bom."""
    fresh = fetch_quotes_batch(ALL_QUOTE_TICKERS)
    prev = (CACHE.get("quotes") or {}).get("quotes", {})

    quotes = {}
    for tk in ALL_QUOTE_TICKERS:
        name, cat = TICKER_META[tk]
        q = fresh.get(tk)
        if q is None:
            # fonte falhou para esse ticker: mantem o ultimo dado bom
            if tk in prev:
                quotes[tk] = prev[tk]
            continue
        row = {
            "ticker": tk,
            "name": name,
            "category": cat,
            "price": q["price"],
            "change_pct": q["change_pct"],
        }
        if cat == "etf":
            row["region"] = ETF_REGION.get(tk, "")
        quotes[tk] = row

    # Cripto — precos em USD convertidos para BRL pelo par USDBRL
    usdbrl = None
    u = quotes.get("USDBRL=X")
    if u:
        usdbrl = u.get("price")
    crypto_syms = [y for _, _, y in CRYPTOS]
    craw = fetch_quotes_batch(crypto_syms)
    crypto = {}
    prev_crypto = (CACHE.get("quotes") or {}).get("crypto", {})
    for sym, name, yh in CRYPTOS:
        q = craw.get(yh)
        if q is None:
            if sym in prev_crypto:
                crypto[sym] = prev_crypto[sym]
            continue
        crypto[sym] = {
            "name": name,
            "price_usd": q["price"],
            "price_brl": round(q["price"] * usdbrl, 2) if usdbrl else None,
            "change_pct": q["change_pct"],
        }

    payload = {
        "quotes": quotes,
        "crypto": crypto,
        "last_update": utcnow_iso(),
        "source": "api" if fresh else "none",
        "api_tickers": len(fresh),
        "ws_tickers": 0,
    }
    CACHE.set("quotes", payload)
    log(f"cotacoes: {len(fresh)}/{len(ALL_QUOTE_TICKERS)} tickers, {len(craw)} criptos")


# ─────────────────────────────────────────────────────────────
# INDICADORES MACRO — Banco Central (SGS)
# ─────────────────────────────────────────────────────────────
SGS_SERIES = {
    "selic_meta":     (432,   "Meta Selic",        "%"),
    "cdi_mes":        (4391,  "CDI Mensal",        "%"),
    "ipca_12m":       (13522, "IPCA 12 meses",     "%"),
    "ipca_mes":       (433,   "IPCA Mensal",       "%"),
    "igpm":           (189,   "IGP-M",             "%"),
    "dolar_ptax":     (1,     "Dolar PTAX",        "R$"),
    "selic_efetiva":  (4390,  "Selic Efetiva",     "%"),
    "inpc":           (188,   "INPC",              "%"),
    "igp_di":         (190,   "IGP-DI",            "%"),
    "incc":           (192,   "INCC",              "%"),
    "poupanca":       (195,   "Poupanca",          "%"),
    "tr":             (226,   "TR",                "%"),
    "euro_ptax":      (21619, "Euro PTAX",         "R$"),
    "desemprego":     (24369, "Desemprego PNAD",   "%"),
}
SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados/ultimos/{n}?formato=json"


def sgs_fetch(code, n=1):
    r = http_get(SGS_URL.format(code=code, n=n))
    if not r:
        return []
    try:
        rows = r.json()
    except Exception:
        return []
    out = []
    for row in rows:
        try:
            d = datetime.strptime(row["data"], "%d/%m/%Y").strftime("%Y-%m-%d")
            out.append({"date": d, "value": float(str(row["valor"]).replace(",", "."))})
        except Exception:
            continue
    return out


def refresh_indicators():
    prev = CACHE.get("indicators") or {}
    ind = dict(prev)
    ok = 0

    def one(item):
        key, (code, label, unit) = item
        return key, label, unit, sgs_fetch(code, 1)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for key, label, unit, rows in pool.map(one, SGS_SERIES.items()):
            if not rows:
                continue  # mantem o valor anterior
            last = rows[-1]
            ind[key] = {
                "label": label,
                "unit": unit,
                "value": last["value"],
                "date": datetime.strptime(last["date"], "%Y-%m-%d").strftime("%d/%m/%Y"),
            }
            ok += 1

    if ind:
        CACHE.set("indicators", ind)
    log(f"indicadores BCB: {ok}/{len(SGS_SERIES)} series")


def indicator_history(key, points=240):
    code, label, unit = SGS_SERIES[key]
    ck = f"indhist:{key}"
    age = CACHE.age(ck)
    if age is not None and age < 3600:
        return CACHE.get(ck)
    rows = sgs_fetch(code, points)
    payload = {"key": key, "label": label, "unit": unit, "history": rows}
    if rows:
        CACHE.set(ck, payload)
        return payload
    return CACHE.get(ck, payload)


# ─────────────────────────────────────────────────────────────
# TESOURO DIRETO — API publica do tesourodireto.com.br
# ─────────────────────────────────────────────────────────────
TD_URL = ("https://www.tesourodireto.com.br/json/br/com/b3/tesourodireto/"
          "service/api/treasurybondsinfo.json")


def refresh_tesouro():
    r = http_get(TD_URL, headers={"Accept": "application/json"})
    if not r:
        return
    try:
        bonds = r.json()["response"]["TrsrBdTradgList"]
    except Exception as e:
        log(f"tesouro: resposta inesperada ({e})")
        return

    ipca, pre = [], []
    for item in bonds:
        b = item.get("TrsrBd") or {}
        name = b.get("nm") or ""
        rate = b.get("anulInvstmtRate")
        price = b.get("untrRedVal") or b.get("untrInvstmtVal")
        mat = b.get("mtrtyDt") or ""
        if rate is None:
            continue
        row = {
            "name": name,
            "maturity": mat[:10],
            "rate": float(rate),
            "price": float(price) if price else None,
        }
        low = name.lower()
        if "ipca" in low:
            ipca.append(row)
        elif "prefixado" in low:
            pre.append(row)

    if ipca or pre:
        CACHE.set("tesouro", {"ipca": ipca, "pre": pre, "last_update": utcnow_iso()})
        log(f"tesouro direto: {len(ipca)} IPCA+, {len(pre)} prefixados")


# ─────────────────────────────────────────────────────────────
# CURVA DI — interpolada dos prefixados do Tesouro (proxy do DI futuro)
# ─────────────────────────────────────────────────────────────
DI_TENORS = [("1m", 1/12), ("3m", 0.25), ("6m", 0.5), ("1a", 1), ("2a", 2),
             ("3a", 3), ("4a", 4), ("5a", 5), ("7a", 7), ("10a", 10)]


def _interp(points, x):
    """Interpolacao linear em (prazo_anos, taxa), com extrapolacao achatada."""
    if not points:
        return None
    pts = sorted(points)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def refresh_di():
    tes = CACHE.get("tesouro") or {}
    pre = tes.get("pre") or []
    today = datetime.now(timezone.utc).date()

    points = []
    for b in pre:
        try:
            mat = datetime.strptime(b["maturity"], "%Y-%m-%d").date()
            yrs = (mat - today).days / 365.25
            if yrs > 0.05:
                points.append((yrs, b["rate"]))
        except Exception:
            continue

    ind = CACHE.get("indicators") or {}
    selic = (ind.get("selic_meta") or {}).get("value")

    # A ponta curta da curva ancora na Selic; o resto vem dos prefixados.
    if selic is not None:
        points.append((1/12, float(selic)))

    if not points:
        return  # sem fonte: preserva a curva anterior em vez de inventar numero

    di = [{"tenor": t, "rate": round(float(_interp(points, y)), 2)} for t, y in DI_TENORS]
    CACHE.set("di", {"di": di, "fonte": "Tesouro Direto (prefixados) + Selic meta",
                     "last_update": utcnow_iso()})
    log(f"curva DI: {len(di)} vertices a partir de {len(points)} pontos")


# ─────────────────────────────────────────────────────────────
# SPREADS DE CREDITO PRIVADO
# A curva NTN-B de referencia vem do Tesouro (dado vivo). Os spreads por
# rating/prazo nao tem API publica gratuita — ficam em data/spreads_ref.json
# para o administrador manter (o front mostra a data da ultima revisao).
# ─────────────────────────────────────────────────────────────
SPREADS_REF_PATH = os.path.join(DATA_DIR, "spreads_ref.json")
SPREAD_HIST_PATH = os.path.join(DATA_DIR, "spread_history.json")

SPREADS_REF_DEFAULT = {
    "revisado_em": "2026-08-01",
    "fonte": "Referencia interna — revisar contra ANBIMA/corretoras",
    "debentures_ipca": [
        {"rating": "AAA", "tenor": "3-5a",  "spread": 0.45},
        {"rating": "AAA", "tenor": "6-8a",  "spread": 0.60},
        {"rating": "AAA", "tenor": "9a+",   "spread": 0.75},
        {"rating": "AA",  "tenor": "3-5a",  "spread": 0.75},
        {"rating": "AA",  "tenor": "6-8a",  "spread": 0.95},
        {"rating": "A",   "tenor": "3-5a",  "spread": 1.30},
        {"rating": "A",   "tenor": "6-8a",  "spread": 1.60},
        {"rating": "BBB", "tenor": "3-5a",  "spread": 2.40},
    ],
    "cri_ipca": [
        {"type": "Pulverizado", "tenor": "5-7a", "spread": 1.40},
        {"type": "Corporativo", "tenor": "5-7a", "spread": 0.95},
        {"type": "Corporativo", "tenor": "8a+",  "spread": 1.15},
    ],
    "cra_ipca": [
        {"type": "Agro AAA",  "tenor": "4-6a", "spread": 0.85},
        {"type": "Agro AA",   "tenor": "4-6a", "spread": 1.10},
        {"type": "Agro A",    "tenor": "4-6a", "spread": 1.55},
    ],
}


def ntnb_curve():
    """{ano_de_vencimento: taxa_real} a partir dos titulos IPCA+ do Tesouro."""
    tes = CACHE.get("tesouro") or {}
    curve = {}
    for b in tes.get("ipca") or []:
        mat = b.get("maturity") or ""
        if len(mat) < 4:
            continue
        year = mat[:4]
        # se houver mais de um titulo no mesmo ano, fica o de vencimento mais curto
        if year not in curve:
            curve[year] = round(float(b["rate"]), 2)
    return curve


def refresh_spreads():
    ref = load_json_file(SPREADS_REF_PATH, SPREADS_REF_DEFAULT)
    curve = ntnb_curve()
    today = datetime.now(timezone.utc).date()

    def tenor_mid_year(tenor):
        nums = [int(x) for x in re.findall(r"\d+", tenor)]
        if not nums:
            return None
        mid = sum(nums) / len(nums)
        return str(today.year + int(round(mid)))

    def enrich(rows):
        out = []
        for r in rows:
            row = dict(r)
            year = tenor_mid_year(row.get("tenor", ""))
            ref_rate = None
            if year and curve:
                if year in curve:
                    ref_rate = curve[year]
                else:  # vencimento mais proximo disponivel
                    nearest = min(curve, key=lambda y: abs(int(y) - int(year)))
                    ref_rate = curve[nearest]
            row["ntnb_ref"] = ref_rate
            row["total_yield"] = round(ref_rate + row["spread"], 2) if ref_rate is not None else None
            out.append(row)
        return out

    spreads = {
        "debentures_ipca": enrich(ref.get("debentures_ipca", [])),
        "cri_ipca": enrich(ref.get("cri_ipca", [])),
        "cra_ipca": enrich(ref.get("cra_ipca", [])),
        "ntnb": curve,
        "fonte": f"{ref.get('fonte','')} · NTN-B ao vivo via Tesouro Direto",
        "context": (f"Spreads de referencia revisados em {ref.get('revisado_em','-')}. "
                    f"Curva NTN-B atualizada em {today.strftime('%d/%m/%Y')}."),
    }
    CACHE.set("spreads", {"spreads": spreads, "last_update": utcnow_iso()})

    # Serie historica: uma amostra por dia da mediana dos spreads de debenture.
    vals = sorted(r["spread"] for r in ref.get("debentures_ipca", []))
    if vals:
        median = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals)//2 - 1] + vals[len(vals)//2]) / 2
        hist = load_json_file(SPREAD_HIST_PATH, [])
        stamp = today.strftime("%Y-%m-%d")
        if not any(h.get("date") == stamp for h in hist):
            hist.append({"date": stamp, "spread": round(float(median), 3)})
            hist = hist[-750:]
            save_json_file(SPREAD_HIST_PATH, hist)
        CACHE.set("spread_history", hist)


# ─────────────────────────────────────────────────────────────
# NOTICIAS — RSS
# ─────────────────────────────────────────────────────────────
FEEDS = [
    ("InfoMoney",        "https://www.infomoney.com.br/feed/",                            ["BR"]),
    ("Money Times",      "https://www.moneytimes.com.br/feed/",                           ["BR"]),
    ("Seu Dinheiro",     "https://www.seudinheiro.com/feed/",                             ["BR"]),
    ("Exame Invest",     "https://exame.com/invest/feed/",                                ["BR"]),
    ("Valor Investe",    "https://valorinveste.globo.com/rss/valorinveste",               ["BR"]),
    ("BC Noticias",      "https://www.bcb.gov.br/rss/noticias",                           ["MACRO"]),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews",                ["US"]),
    ("CNBC Markets",     "https://www.cnbc.com/id/20910258/device/rss/rss.html",          ["US"]),
    ("MarketWatch",      "https://feeds.marketwatch.com/marketwatch/topstories/",         ["US"]),
    ("Yahoo Finance",    "https://finance.yahoo.com/news/rssindex",                       ["US"]),
    ("CoinDesk",         "https://www.coindesk.com/arc/outboundfeeds/rss/",               ["CRYPTO"]),
    ("Cointelegraph",    "https://cointelegraph.com/rss",                                 ["CRYPTO"]),
]

CAT_KEYWORDS = {
    "B3":       ["ibovespa", "b3", "bovespa", "petr4", "vale3", "itub4", "bbas3", "acoes brasileiras"],
    "CRYPTO":   ["bitcoin", "ethereum", "cripto", "crypto", "blockchain", "btc", "eth", "stablecoin"],
    "MACRO":    ["selic", "copom", "ipca", "inflacao", "inflação", "pib", "juros", "fed", "fomc", "cpi", "payroll"],
    "ECONOMIA": ["economia", "fiscal", "orcamento", "orçamento", "divida", "dívida", "arrecadacao"],
    "GEO":      ["guerra", "ucrania", "ucrânia", "russia", "rússia", "israel", "china", "tarifa", "tariff", "opep"],
    "CORP":     ["lucro", "resultado", "ebitda", "dividendo", "jcp", "aquisicao", "aquisição", "fusao", "ipo", "earnings"],
}


def classify(title, summary, base_cats):
    text = f"{title} {summary}".lower()
    cats = list(base_cats)
    for cat, kws in CAT_KEYWORDS.items():
        if cat in cats:
            continue
        if any(k in text for k in kws):
            cats.append(cat)
    return cats[:4]


def parse_feed(source, url, base_cats):
    import feedparser
    r = http_get(url, timeout=HTTP_TIMEOUT)
    if not r:
        return []
    try:
        parsed = feedparser.parse(r.content)
    except Exception:
        return []

    items = []
    for e in parsed.entries[:40]:
        title = (getattr(e, "title", "") or "").strip()
        link = getattr(e, "link", "") or ""
        if not title or not link:
            continue

        pub = None
        for attr in ("published", "updated", "created"):
            raw = getattr(e, attr, None)
            if raw:
                try:
                    pub = parsedate_to_datetime(raw)
                    break
                except Exception:
                    pass
        if pub is None:
            st = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
            if st:
                pub = datetime(*st[:6], tzinfo=timezone.utc)
        if pub is None:
            pub = datetime.now(timezone.utc)

        summary = re.sub(r"<[^>]+>", "", getattr(e, "summary", "") or "").strip()
        summary = re.sub(r"\s+", " ", summary)[:400]

        img = ""
        for m in (getattr(e, "media_content", None) or []):
            if m.get("url"):
                img = m["url"]
                break
        if not img:
            for l in (getattr(e, "links", None) or []):
                if str(l.get("type", "")).startswith("image"):
                    img = l.get("href", "")
                    break

        items.append({
            "title": title,
            "link": link,
            "source": source,
            "pub": naive_utc_iso(pub),
            "summary": summary,
            "img": img,
            "cats": classify(title, summary, base_cats),
        })
    return items


def refresh_news():
    all_items = []

    def one(f):
        return parse_feed(*f)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for items in pool.map(one, FEEDS):
            all_items.extend(items)

    if not all_items:
        log("noticias: nenhuma fonte respondeu, mantendo cache")
        return

    seen, dedup = set(), []
    for n in sorted(all_items, key=lambda x: x["pub"] or "", reverse=True):
        key = n["title"].lower()[:90]
        if key in seen:
            continue
        seen.add(key)
        dedup.append(n)

    CACHE.set("news", {"news": dedup[:250], "ts": utcnow_iso()})
    log(f"noticias: {len(dedup)} itens de {len(FEEDS)} feeds")
    build_weekly_summary(dedup)


CORP_KW = ["lucro", "prejuizo", "prejuízo", "resultado", "receita", "ebitda", "dividendo",
           "jcp", "jscp", "provento", "aquisicao", "aquisição", "fusao", "fusão", "ipo",
           "follow-on", "recompra", "guidance", "balanco", "balanço", "earnings", "revenue",
           "profit", "buyback", "acquisition", "merger", "quarterly", "dividend"]


def build_weekly_summary(news):
    cutoff = naive_utc_iso(datetime.now(timezone.utc) - timedelta(days=7))
    br, us = [], []
    for n in news:
        if (n.get("pub") or "") < cutoff:
            continue
        text = f"{n['title']} {n.get('summary','')}".lower()
        if not any(k in text for k in CORP_KW):
            continue
        item = {"title": n["title"], "summary": n.get("summary", ""),
                "source": n["source"], "pub": n["pub"], "link": n["link"]}
        cats = n.get("cats") or []
        if "BR" in cats:
            br.append(item)
        elif "US" in cats:
            us.append(item)

    now = datetime.now(timezone.utc)
    CACHE.set("weekly_summary", {
        "br": br[:40],
        "us": us[:40],
        "week_label": f"{(now - timedelta(days=7)).strftime('%d/%m')} a {now.strftime('%d/%m/%Y')}",
    })


# ─────────────────────────────────────────────────────────────
# CVM — Fatos Relevantes (portal de dados abertos, arquivo IPE)
# ─────────────────────────────────────────────────────────────
IPE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{year}.csv"
ALERT_HIST_PATH = os.path.join(DATA_DIR, "alert_history.json")


def refresh_cvm():
    year = datetime.now(timezone.utc).year
    r = http_get(IPE_URL.format(year=year), timeout=25)
    if not r:
        return

    try:
        text = r.content.decode("latin-1")
        rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    except Exception as e:
        log(f"cvm: nao consegui ler o CSV ({e})")
        return

    fatos, proventos = [], []
    for row in rows[-4000:]:
        categoria = (row.get("Categoria") or "").strip()
        assunto = (row.get("Assunto") or "").strip()
        empresa = (row.get("Nome_Companhia") or "").strip()
        data = (row.get("Data_Entrega") or "")[:10]
        link = (row.get("Link_Download") or "").strip()
        if not empresa:
            continue

        if categoria == "Fato Relevante":
            fatos.append({
                "company": empresa,
                "type": assunto[:90] or "Fato Relevante",
                "date": data,
                "link": link,
                "summary": assunto[:200],
            })
        elif "provento" in categoria.lower() or "rendimento" in assunto.lower() \
                or "dividendo" in assunto.lower() or "juros sobre capital" in assunto.lower():
            tipo = "JCP" if "juros sobre capital" in assunto.lower() else "Dividendo"
            proventos.append({
                "type": tipo,
                "summary": f"{empresa} — {assunto[:120]}",
                "date": data,
            })

    fatos.sort(key=lambda x: x["date"], reverse=True)
    proventos.sort(key=lambda x: x["date"], reverse=True)
    fatos = fatos[:120]

    prev = CACHE.get("cvm") or {}
    old_keys = {(f["company"], f["date"], f["type"]) for f in prev.get("fatos", [])}
    novos = [f for f in fatos if (f["company"], f["date"], f["type"]) not in old_keys]

    CACHE.set("cvm", {
        "fatos": fatos,
        "corp_events": proventos[:40],
        "sec_filings": (prev.get("sec_filings") or []),
        "corp_highlights": [],
    })

    # Alertas so disparam depois da primeira carga (senao a tela abre com 120 toasts).
    if prev.get("fatos") and novos:
        CACHE.set("pending_alerts", novos[:20])
        hist = load_json_file(ALERT_HIST_PATH, [])
        hist = (novos[:20] + hist)[:300]
        save_json_file(ALERT_HIST_PATH, hist)
        CACHE.set("alert_history", hist)
        log(f"cvm: {len(novos)} fatos relevantes novos")
    log(f"cvm: {len(fatos)} fatos, {len(proventos)} proventos")


SEC_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={t}"
           "&company=&dateb=&owner=include&count=40&output=atom")


def refresh_sec():
    import feedparser
    filings = []
    for ftype in ("8-K", "10-Q", "10-K"):
        r = http_get(SEC_URL.format(t=ftype), headers={"User-Agent": SEC_UA}, timeout=15)
        if not r:
            continue
        try:
            parsed = feedparser.parse(r.content)
        except Exception:
            continue
        for e in parsed.entries[:20]:
            title = (getattr(e, "title", "") or "").strip()
            updated = (getattr(e, "updated", "") or "")[:10]
            filings.append({
                "type": ftype,
                "summary": title,
                "date": updated,
                "link": getattr(e, "link", "") or "",
            })
        time.sleep(0.3)  # EDGAR pede no maximo 10 req/s

    if filings:
        cvm = CACHE.get("cvm") or {"fatos": [], "corp_events": [], "corp_highlights": []}
        cvm["sec_filings"] = filings[:60]
        CACHE.set("cvm", cvm)
        log(f"sec edgar: {len(filings)} filings")


# ─────────────────────────────────────────────────────────────
# TIR REAL
# ─────────────────────────────────────────────────────────────
try:
    import tir_real_servidor as TIR
except Exception as e:  # pragma: no cover
    TIR = None
    log(f"modulo TIR indisponivel: {e}")


def _ipca_atual():
    ind = CACHE.get("indicators") or {}
    v = (ind.get("ipca_12m") or {}).get("value")
    return float(v) if v is not None else 4.5


def _preco_b3(ticker):
    tk = ticker.upper().replace(".SA", "")
    quotes = (CACHE.get("quotes") or {}).get("quotes", {})
    row = quotes.get(f"{tk}.SA")
    return row.get("price") if row else None


def refresh_tir():
    if TIR is None:
        return
    ipca = _ipca_atual()
    assets = []
    for tk in TIR.tickers_cobertos():
        preco = _preco_b3(tk)
        if not preco:
            continue
        r = TIR.calcular_tir(tk, preco, ipca)
        if "error" not in r:
            assets.append(r)
    assets.sort(key=lambda a: a["tir_real"], reverse=True)
    if assets:
        CACHE.set("tir_all", {"assets": assets, "ipca": ipca, "last_update": utcnow_iso()})
        log(f"tir real: {len(assets)} ativos calculados")


# ─────────────────────────────────────────────────────────────
# WATCHLIST
# ─────────────────────────────────────────────────────────────
WATCHLIST_PATH = os.path.join(DATA_DIR, "watchlist.json")


def default_watchlist():
    wl = {}
    for tk, name, cat in UNIVERSE:
        if cat == "b3":
            wl[name] = {"ticker": tk, "market": "B3", "active": True}
        elif cat == "us":
            wl[name] = {"ticker": tk, "market": "US", "active": True}
    for sym, name, yh in CRYPTOS:
        wl[name] = {"ticker": sym, "market": "CRYPTO", "active": True}
    return wl


def get_watchlist():
    wl = load_json_file(WATCHLIST_PATH, None)
    if not wl:
        wl = default_watchlist()
        save_json_file(WATCHLIST_PATH, wl)
    return wl


# ─────────────────────────────────────────────────────────────
# ROTAS — front
# ─────────────────────────────────────────────────────────────
@app.after_request
def no_cache_html(resp):
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store"
    return resp


def serve_terminal():
    return send_from_directory(BASE_DIR, "index.html")


# O terminal responde na raiz e em /terminal — este e o endereco que costuma
# ser digitado (http://localhost:5051/terminal).
@app.route("/")
@app.route("/terminal")
@app.route("/terminal/")
@app.route("/index.html")
def index():
    return serve_terminal()


VENDOR_DIR = os.path.join(BASE_DIR, "vendor")
CHARTJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
CHARTJS_ARQ = "chart.umd.min.js"


@app.route("/vendor/<path:arquivo>")
def vendor(arquivo):
    """Bibliotecas locais (Chart.js). 404 de verdade se nao existir, para o
    fallback do CDN entrar no lugar em vez de receber HTML."""
    destino = os.path.join(VENDOR_DIR, arquivo)
    if os.path.isfile(destino):
        return send_from_directory(VENDOR_DIR, arquivo)
    return ("nao encontrado", 404)


def baixar_chartjs():
    """Guarda uma copia do Chart.js para os graficos nao dependerem do CDN."""
    destino = os.path.join(VENDOR_DIR, CHARTJS_ARQ)
    if os.path.exists(destino) and os.path.getsize(destino) > 50_000:
        return
    r = http_get(CHARTJS_URL, timeout=20)
    if not r or len(r.content) < 50_000:
        return  # sem rede agora: o CDN cobre, e tentamos de novo na proxima vez
    os.makedirs(VENDOR_DIR, exist_ok=True)
    with open(destino, "wb") as f:
        f.write(r.content)
    log(f"Chart.js salvo em vendor/ ({len(r.content)//1024} KB)")


@app.errorhandler(404)
def not_found(err):
    """
    Fora de /api/* e /vendor/*, qualquer caminho abre o terminal em vez de
    devolver 404. Assim um endereco digitado com uma variacao qualquer
    (/terminal, /painel, /broadcast...) continua abrindo a tela.
    """
    if request.path.startswith("/api/") or request.path.startswith("/vendor/"):
        return jsonify({"error": "nao encontrado", "path": request.path}), 404
    return serve_terminal()


FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="10" fill="#1c1c1e"/>'
    '<path d="M8 44 L22 30 L34 38 L56 16" stroke="#34c759" stroke-width="6" '
    'fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


@app.route("/favicon.ico")
def favicon():
    return app.response_class(FAVICON, mimetype="image/svg+xml")


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "server_time": utcnow_iso(),
        "caches": {k: round(CACHE.age(k), 1) for k in
                   ("quotes", "news", "indicators", "cvm", "di", "spreads", "tesouro", "tir_all")
                   if CACHE.age(k) is not None},
    })


# ─────────────────────────────────────────────────────────────
# ROTAS — mercado
# ─────────────────────────────────────────────────────────────
@app.route("/api/quotes")
def api_quotes():
    return jsonify(CACHE.get("quotes") or {
        "quotes": {}, "crypto": {}, "last_update": utcnow_iso(),
        "source": "none", "api_tickers": 0, "ws_tickers": 0})


@app.route("/api/quotes_fast")
def api_quotes_fast():
    d = CACHE.get("quotes") or {}
    return jsonify({
        "quotes": d.get("quotes", {}),
        "crypto": d.get("crypto", {}),
        "last_update": d.get("last_update", utcnow_iso()),
        "source": d.get("source", "none"),
        "api_tickers": d.get("api_tickers", 0),
        "ws_tickers": 0,
    })


@app.route("/api/indicators")
def api_indicators():
    return jsonify({"indicators": CACHE.get("indicators") or {}})


@app.route("/api/indicator_history")
def api_indicator_history():
    key = request.args.get("key", "")
    if key not in SGS_SERIES:
        return jsonify({"error": "serie desconhecida", "history": []}), 404
    return jsonify(indicator_history(key))


@app.route("/api/di")
def api_di():
    return jsonify(CACHE.get("di") or {"di": []})


@app.route("/api/tesouro")
def api_tesouro():
    return jsonify(CACHE.get("tesouro") or {"ipca": [], "pre": []})


@app.route("/api/spreads")
def api_spreads():
    return jsonify(CACHE.get("spreads") or {"spreads": {}})


@app.route("/api/spread_history")
def api_spread_history():
    hist = CACHE.get("spread_history")
    if hist is None:
        hist = load_json_file(SPREAD_HIST_PATH, [])
    return jsonify({"history": hist})


# ─────────────────────────────────────────────────────────────
# ROTAS — noticias e eventos corporativos
# ─────────────────────────────────────────────────────────────
@app.route("/api/news")
def api_news():
    return jsonify(CACHE.get("news") or {"news": [], "ts": utcnow_iso()})


@app.route("/api/cvm")
def api_cvm():
    return jsonify(CACHE.get("cvm") or
                   {"fatos": [], "corp_events": [], "sec_filings": [], "corp_highlights": []})


@app.route("/api/weekly_summary")
def api_weekly_summary():
    return jsonify(CACHE.get("weekly_summary") or {"br": [], "us": [], "week_label": ""})


@app.route("/api/alerts")
def api_alerts():
    """Fila de disparo unico: cada fato relevante novo notifica uma vez so."""
    pend = CACHE.get("pending_alerts") or []
    CACHE.set("pending_alerts", [])
    return jsonify({"alerts": pend})


@app.route("/api/alert_history")
def api_alert_history():
    hist = CACHE.get("alert_history")
    if hist is None:
        hist = load_json_file(ALERT_HIST_PATH, [])
        CACHE.set("alert_history", hist)
    return jsonify({"history": hist})


# ─────────────────────────────────────────────────────────────
# ROTAS — watchlist
# ─────────────────────────────────────────────────────────────
@app.route("/api/watchlist", methods=["GET", "POST"])
def api_watchlist():
    wl = get_watchlist()
    if request.method == "GET":
        return jsonify({"watchlist": wl})

    patch = request.get_json(silent=True) or {}
    for name, v in patch.items():
        if name in wl and isinstance(v, dict) and "active" in v:
            wl[name]["active"] = bool(v["active"])
    save_json_file(WATCHLIST_PATH, wl)
    return jsonify({"ok": True, "watchlist": wl})


# ─────────────────────────────────────────────────────────────
# ROTAS — ativo, busca, TIR
# ─────────────────────────────────────────────────────────────
VALID_PERIODS = {"5d": "1h", "1mo": "1d", "3mo": "1d", "6mo": "1d",
                 "1y": "1d", "2y": "1wk", "5y": "1wk", "max": "1mo"}


@app.route("/api/asset")
def api_asset():
    ticker = (request.args.get("ticker") or "").strip()
    period = request.args.get("period", "1mo")
    if not ticker:
        return jsonify({"error": "ticker obrigatorio"}), 400
    interval = VALID_PERIODS.get(period, "1d")

    # Simbolos de cripto chegam como 'BTC' e no Yahoo sao 'BTC-USD'
    sym = ticker
    if sym.upper() in {c[0] for c in CRYPTOS}:
        sym = f"{sym.upper()}-USD"

    ck = f"asset:{sym}:{period}"
    age = CACHE.age(ck)
    if age is not None and age < 120:
        return jsonify(CACHE.get(ck))

    res = yahoo_chart(sym, rng=period, interval=interval, timeout=12)
    if not res:
        cached = CACHE.get(ck)
        return jsonify(cached or {"error": "sem dados para este ativo"})

    try:
        stamps = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
    except Exception:
        return jsonify({"error": "sem dados para este ativo"})

    dates, prices = [], []
    for ts, c in zip(stamps, closes):
        if c is None:
            continue
        dates.append(datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"))
        prices.append(round(float(c), 4))

    if not prices:
        return jsonify({"error": "sem dados para este ativo"})

    first, current = prices[0], prices[-1]
    payload = {
        "ticker": ticker,
        "dates": dates,
        "prices": prices,
        "current": current,
        "change_pct": round(((current - first) / first * 100.0) if first else 0.0, 2),
        "high": max(prices),
        "low": min(prices),
        "period": period,
    }
    CACHE.set(ck, payload)
    return jsonify(payload)


SEARCH_TYPE = {"b3": "acao_br", "us": "stock", "etf": "etf", "index": "index",
               "forex": "forex", "commodity": "commodity", "futures": "futures"}


@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify({"results": []})

    quotes = (CACHE.get("quotes") or {}).get("quotes", {})
    crypto = (CACHE.get("quotes") or {}).get("crypto", {})
    results = []

    for tk, row in quotes.items():
        if q in tk.lower() or q in row.get("name", "").lower():
            results.append({
                "ticker": tk,
                "name": row.get("name", tk),
                "type": SEARCH_TYPE.get(row.get("category"), row.get("category", "stock")),
                "price": row.get("price"),
                "change_pct": row.get("change_pct"),
                "source": "local",
            })

    for sym, row in crypto.items():
        if q in sym.lower() or q in row.get("name", "").lower():
            results.append({
                "ticker": sym,
                "name": row.get("name", sym),
                "type": "crypto",
                "price": row.get("price_usd"),
                "change_pct": row.get("change_pct"),
                "source": "local",
            })

    # Complementa com a busca do Yahoo para o que estiver fora do universo local
    if len(results) < 8:
        known = {r["ticker"].upper() for r in results}
        r = http_get("https://query2.finance.yahoo.com/v1/finance/search"
                     f"?q={requests.utils.quote(q)}&quotesCount=10&newsCount=0", timeout=6)
        if r:
            try:
                for item in r.json().get("quotes", []):
                    sym = item.get("symbol")
                    if not sym or sym.upper() in known:
                        continue
                    qt = (item.get("quoteType") or "").upper()
                    tipo = {"EQUITY": "stock", "ETF": "etf", "INDEX": "index",
                            "CURRENCY": "forex", "CRYPTOCURRENCY": "crypto",
                            "FUTURE": "futures", "MUTUALFUND": "fundo"}.get(qt, "stock")
                    if sym.endswith(".SA") and tipo == "stock":
                        tipo = "acao_br"
                    results.append({
                        "ticker": sym,
                        "name": item.get("longname") or item.get("shortname") or sym,
                        "type": tipo,
                        "price": None,
                        "change_pct": None,
                        "source": "yahoo",
                    })
            except Exception:
                pass

    return jsonify({"results": results[:40]})


@app.route("/api/search_news")
def api_search_news():
    q = (request.args.get("q") or "").strip().lower()
    news = (CACHE.get("news") or {}).get("news", [])
    if len(q) < 2:
        return jsonify({"news": []})
    hits = [n for n in news
            if q in n["title"].lower() or q in (n.get("summary") or "").lower()]
    return jsonify({"news": hits[:10]})


@app.route("/api/tir/all")
def api_tir_all():
    return jsonify(CACHE.get("tir_all") or {"assets": []})


@app.route("/api/tir")
def api_tir():
    if TIR is None:
        return jsonify({"error": "modelo TIR indisponivel"}), 503
    ticker = (request.args.get("ticker") or "").strip().upper().replace(".SA", "")
    if not ticker:
        return jsonify({"error": "ticker obrigatorio"}), 400
    preco = _preco_b3(ticker)
    if not preco:
        cached = next((a for a in (CACHE.get("tir_all") or {}).get("assets", [])
                       if a["ticker"] == ticker), None)
        if cached:
            return jsonify(cached)
        return jsonify({"error": f"sem cotacao para {ticker}"})
    return jsonify(TIR.calcular_tir(ticker, preco, _ipca_atual()))


# ─────────────────────────────────────────────────────────────
# ROTAS — fontes externas opcionais (degradam sem quebrar a tela)
# ─────────────────────────────────────────────────────────────
SI_LABELS = {
    "dy": "dy", "p/l": "pl", "p/vp": "pvp", "ev/ebitda": "ev_ebitda",
    "peg ratio": "peg_ratio", "vpa": "vpa", "lpa": "lpa", "p/sr": "psr",
    "div. líquida/patrimônio": "div_liq_pl", "dív. líquida/patrimônio": "div_liq_pl",
    "div. líquida/ebitda": "div_liq_ebitda", "dív. líquida/ebitda": "div_liq_ebitda",
    "patrimônio/ativos": "pl_ativos", "passivos/ativos": "passivos_ativos",
    "m. bruta": "margem_bruta", "m. ebitda": "margem_ebitda",
    "m. líquida": "margem_liquida", "m. ebit": "margem_ebit",
    "roe": "roe", "roa": "roa", "roic": "roic",
    "cagr receitas 5 anos": "cagr_receitas", "cagr lucros 5 anos": "cagr_lucros",
}


@app.route("/api/statusinvest")
def api_statusinvest():
    ticker = (request.args.get("ticker") or "").strip().lower()
    tipo = request.args.get("type", "stock")
    if not ticker:
        return jsonify({"indicators": {}})

    ck = f"si:{ticker}:{tipo}"
    age = CACHE.age(ck)
    if age is not None and age < 3600:
        return jsonify(CACHE.get(ck))

    path = "fundos-imobiliarios" if tipo == "fii" else "acoes"
    r = http_get(f"https://statusinvest.com.br/{path}/{ticker}", timeout=12,
                 headers={"Accept-Language": "pt-BR,pt;q=0.9"})
    if not r:
        return jsonify(CACHE.get(ck) or {"indicators": {}})

    html = r.text
    indicators = {}
    # Os cards do StatusInvest expoem o valor cru em data-value junto ao titulo
    for m in re.finditer(
            r'title="([^"]{2,60})"[^>]*>.{0,600}?data-value="(-?[\d.,]+)"', html, re.S):
        label = m.group(1).strip().lower()
        key = SI_LABELS.get(label)
        if not key or key in indicators:
            continue
        try:
            indicators[key] = round(float(m.group(2).replace(",", ".")), 2)
        except Exception:
            continue

    payload = {"ticker": ticker.upper(), "indicators": indicators,
               "fonte": "StatusInvest"}
    if indicators:
        CACHE.set(ck, payload)
    return jsonify(payload)


@app.route("/api/maisretorno")
def api_maisretorno():
    fund = (request.args.get("fund") or "").strip()
    if not fund:
        return jsonify({"error": "fundo obrigatorio"}), 400
    # Sem API publica estavel: responde vazio de forma previsivel em vez de 500.
    return jsonify({"fund": fund, "profile": {}, "returns": {},
                    "error": "perfil de fundo indisponivel nesta instalacao"})


# ─────────────────────────────────────────────────────────────
# AGENDADOR
# ─────────────────────────────────────────────────────────────
JOBS = [
    # (funcao, intervalo_em_segundos, roda_no_boot)
    (refresh_quotes,     20,    True),
    (refresh_indicators, 3600,  True),
    (refresh_tesouro,    900,   True),
    (refresh_di,         900,   True),
    (refresh_spreads,    1800,  True),
    (refresh_news,       180,   True),
    (refresh_cvm,        600,   True),
    (refresh_sec,        900,   True),
    (refresh_tir,        300,   True),
]


def run_job(fn):
    try:
        fn()
    except Exception as e:
        log(f"job {fn.__name__} falhou: {type(e).__name__}: {e}")


def scheduler_loop(fn, interval):
    while True:
        time.sleep(interval)
        run_job(fn)


def bootstrap():
    """Primeira carga em paralelo: a tela ja abre com dado em vez de spinner."""
    log("carregando dados iniciais...")
    ordered = [refresh_quotes, refresh_indicators, refresh_tesouro, refresh_news]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run_job, ordered))

    # dependem do que acabou de carregar
    for fn in (refresh_di, refresh_spreads, refresh_tir):
        run_job(fn)

    # mais lentos, seguem em segundo plano sem segurar o boot
    for fn in (refresh_cvm, refresh_sec, baixar_chartjs):
        threading.Thread(target=run_job, args=(fn,), daemon=True).start()

    log("dados iniciais prontos")


def start_scheduler():
    for fn, interval, _ in JOBS:
        threading.Thread(target=scheduler_loop, args=(fn, interval), daemon=True).start()
    log(f"agendador ativo: {len(JOBS)} rotinas")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def porta_ocupada(porta):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", porta))
            return False
        except OSError:
            return True


def broadcast_ja_rodando(porta):
    """True se quem ocupa a porta e um BROADCAST — ai basta abrir o navegador."""
    try:
        sess = requests.Session()
        sess.trust_env = False          # ignora proxy do ambiente para o loopback
        r = sess.get(f"http://127.0.0.1:{porta}/health", timeout=3)
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


def escolher_porta(preferida):
    """Usa a porta pedida; se estiver ocupada por outro programa, pega a proxima."""
    if not porta_ocupada(preferida):
        return preferida, None
    if broadcast_ja_rodando(preferida):
        return preferida, "ja_rodando"
    for porta in range(preferida + 1, preferida + 25):
        if not porta_ocupada(porta):
            return porta, "trocada"
    return preferida, "sem_porta"


def abrir_navegador_quando_subir(porta, tentativas=60):
    """Espera o servidor responder e entao abre a tela no navegador padrao."""
    def esperar():
        sess = requests.Session()
        sess.trust_env = False
        url = f"http://localhost:{porta}/terminal"
        for _ in range(tentativas):
            try:
                if sess.get(f"http://127.0.0.1:{porta}/health", timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        try:
            webbrowser.open(url)
            log(f"navegador aberto em {url}")
        except Exception:
            log(f"abra manualmente: {url}")
    threading.Thread(target=esperar, daemon=True).start()


def main():
    ap = argparse.ArgumentParser(description="Servidor BROADCAST — The Invest Post")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)),
                    help=f"porta HTTP (padrao {DEFAULT_PORT})")
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    ap.add_argument("--no-open", action="store_true",
                    help="nao abrir o navegador automaticamente")
    ap.add_argument("--no-bootstrap", action="store_true",
                    help="sobe sem a carga inicial (util para debug)")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(BASE_DIR, "index.html")):
        print("ERRO: index.html nao foi encontrado na mesma pasta que app.py.")
        print(f"Pasta consultada: {BASE_DIR}")
        sys.exit(1)

    porta, situacao = escolher_porta(args.port)

    if situacao == "ja_rodando":
        print("=" * 62)
        print("  O BROADCAST ja esta rodando nesta porta.")
        print(f"  Abrindo http://localhost:{porta}/terminal")
        print("=" * 62)
        try:
            webbrowser.open(f"http://localhost:{porta}/terminal")
        except Exception:
            pass
        return
    if situacao == "sem_porta":
        print(f"ERRO: as portas {args.port} a {args.port + 24} estao todas ocupadas.")
        print("Feche algum programa ou escolha outra:  python app.py --port 6000")
        sys.exit(1)
    if situacao == "trocada":
        print(f"A porta {args.port} esta ocupada por outro programa — usando a {porta}.")

    if not os.path.exists(SPREADS_REF_PATH):
        save_json_file(SPREADS_REF_PATH, SPREADS_REF_DEFAULT)

    CACHE.set("alert_history", load_json_file(ALERT_HIST_PATH, []))
    CACHE.set("spread_history", load_json_file(SPREAD_HIST_PATH, []))
    CACHE.set("pending_alerts", [])

    print("=" * 62)
    print("  BROADCAST — The Invest Post")
    print(f"  Terminal:  http://localhost:{porta}/terminal")
    print(f"             http://localhost:{porta}   (mesma tela)")
    print(f"  Saude:     http://localhost:{porta}/health")
    print("  Para parar: Ctrl+C")
    print("=" * 62)

    if not args.no_open:
        abrir_navegador_quando_subir(porta)

    if not args.no_bootstrap:
        bootstrap()
    start_scheduler()

    try:
        app.run(host=args.host, port=porta, debug=False, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\nServidor encerrado.")


if __name__ == "__main__":
    main()

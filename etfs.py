#!/usr/bin/env python3
"""Coletor de ETFs para a mesa: UCITS na LSE, referencias nos EUA e macro.

Roda no GitHub Actions (internet aberta) e grava em etfs/ no branch dados:
  etfs/series/<SIMBOLO>.json   barras diarias [data, abre, max, min, fech, ajust, vol] + eventos
  etfs/meta/<SIMBOLO>.json     quoteSummary do Yahoo (bid/ask, volume medio, taxa, patrimonio, carteira)
  etfs/cotacoes.json           cotacao v7 do Yahoo de todos os simbolos (bid, ask, volume, hora)
  etfs/fred/<ID>.csv           series do FRED (Treasury, spreads, Fed, inflacao esperada)
  etfs/docs/<nome>.<ext>       documentos baixados (lista UCITS da Avenue, FactSet, S&P, curva do Tesouro)
  etfs/docs/<nome>.txt         texto extraido dos PDFs
  etfs/justetf/<ISIN>.html     perfil do fundo no justETF, sem scripts nem estilos
  etfs/isins.json              ticker -> ISIN (lista da Avenue + informados)
  etfs/manifest.json           o que veio e o que falhou

A sessao do Claude le com `git show origin/dados:etfs/...`.
Uso: python etfs.py --saida dados_branch/etfs [--simbolos A,B] [--fred X,Y] [--isins T=ISIN ...] [--docs nome=url ...]
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

from livro.http import Cliente, HttpError
from livro.fontes.yahoo import HOSTS, baixar_serie, preparar_sessao

# UCITS da carteira modelo e do universo de IA/infraestrutura, na linha em USD da LSE,
# mais as linhas antigas (VHYL, VWRL) para cobrir 2018 e as referencias americanas.
SIMBOLOS = (
    "CSPX.L VHYA.L VHYL.L VWRA.L VWRL.L DGRA.L IWVL.L IUVL.L EMVL.L XEOU.L IJPD.L QNTM.L "
    "IB01.L VDCA.L CBU7.L STYC.L IGLN.L XDEW.L R2US.L CMOD.L "
    "XAID.L XAIX.L SMH.L WTAI.L IUIT.L XDWT.L CNDX.L GRDU.L VPN.L NUCL.L COPX.L CIBR.L USPY.L "
    "DFNS.L REMX.L "
    "SPY RSP QQQ SMH SOXX XLK WTAI CIBR COPX NLR GRID VPN AIQ "
    "^GSPC ^SPXEW ^NDX ^TNX ^FVX ^TYX ^IRX ^VIX DX-Y.NYB GC=F BZ=F"
).split()

# quoteSummary so para os ETFs (indices e futuros nao tem carteira)
MODULOS = "price,summaryDetail,defaultKeyStatistics,fundProfile,topHoldings,fundPerformance,quoteType"

FRED = ("DGS3MO DGS1 DGS2 DGS5 DGS10 DGS30 DFII10 T10YIE T10Y2Y BAMLH0A0HYM2 BAMLC0A0CM "
        "BAMLH0A0HYM2EY BAMLC0A0CMEY DFEDTARU DFEDTARL MICH ECBDFR VIXCLS DTWEXBGS SP500").split()

# ISINs ja conhecidos (carteira modelo e prospectos); a lista da Avenue completa o resto
ISINS = {
    "CSPX": "IE00B5BMR087", "VHYA": "IE00BK5BR626", "VWRA": "IE00BK5BQT80", "DGRA": "IE00BZ56RG20",
    "IWVL": "IE00BP3QZB59", "XEOU": "LU1184092051", "IJPD": "IE00BCLWRG39", "QNTM": "IE0007Y8Y157",
    "IB01": "IE00BGSF1X88", "VDCA": "IE00BGYWSV06", "CBU7": "IE00B3VWN393", "STYC": "IE00BVZ6SQ11",
    "IGLN": "IE00B4ND3602", "IUIT": "IE00B3WJKG14", "CNDX": "IE00B53SZB19",
}
TICKERS_AVENUE = ("CSPX VHYA VWRA DGRA IWVL IUVL EMVL XEOU IJPD QNTM IB01 VDCA CBU7 STYC IGLN XDEW R2US CMOD "
                  "XAID XAIX SMH WTAI IUIT XDWT CNDX GRDU VPN NUCL COPX CIBR USPY DFNS REMX "
                  "AIAI ROBO RBOT BOTZ AIQ GRID ELEC DTCR DATA SEMI SMGB SOXX CHIP ITEK WTEC NDIA").split()

DOCS = {
    "avenue_ucits.pdf": "https://avenue.us/assets/pdf/Lista_UCITS_ETFs.pdf",
    "sp500_eps.xlsx": "https://www.spglobal.com/spdji/en/documents/additional-material/sp-500-eps-est.xlsx",
    "spy_carteira.xlsx": "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx",
    "tesouro_curva_2026.csv": ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                               "daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv"),
}
FACTSET = ("https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/"
           "Earnings%20Insight/EarningsInsight_{:%m%d%y}.pdf")

RX_ISIN = re.compile(r"\b((?:IE|LU|DE|FR|GB|JE|XS|NL)[A-Z0-9]{9}\d)\b")


def agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gravar(caminho: str, conteudo, binario: bool = False) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    if binario:
        with open(caminho, "wb") as f:
            f.write(conteudo)
    elif isinstance(conteudo, (dict, list)):
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(conteudo, f, ensure_ascii=False, separators=(",", ":"))
    else:
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(conteudo)


def nome_arquivo(simbolo: str) -> str:
    return simbolo.replace("^", "_").replace("=", "_").replace("/", "_")


def series(cli: Cliente, crumb, simbolos: list[str], saida: str, falhas: list) -> dict:
    ok = {}
    for s in simbolos:
        for tentativa in range(3):
            try:
                d = baixar_serie(cli, s, "max", crumb)
                gravar(os.path.join(saida, "series", nome_arquivo(s) + ".json"), d)
                b = d["barras"]
                ok[s] = {"barras": len(b), "de": b[0][0] if b else None, "ate": b[-1][0] if b else None,
                         "moeda": d.get("moeda"), "estado": d["meta"].get("marketState")}
                break
            except HttpError as e:
                if e.status in (429, 500, 502, 503, 504, 0) and tentativa < 2:
                    time.sleep(15 * (tentativa + 1))
                    continue
                falhas.append(f"serie {s}: HTTP {e.status}")
                break
            except Exception as e:
                falhas.append(f"serie {s}: {type(e).__name__}: {str(e)[:100]}")
                break
        time.sleep(0.4)
    return ok


def resumo(cli: Cliente, crumb, simbolos: list[str], saida: str, falhas: list) -> dict:
    ok = {}
    for s in simbolos:
        if s.startswith("^") or "=" in s or s.endswith(".NYB"):
            continue
        params = {"modules": MODULOS, "formatted": "false"}
        if crumb:
            params["crumb"] = crumb
        feito = False
        for host in HOSTS:
            try:
                r = cli.get(f"{host}/v10/finance/quoteSummary/{s}", params=params)
            except HttpError as e:
                falhas.append(f"resumo {s}: rede {e.body[:60]}")
                continue
            if r.status == 200:
                res = ((r.json().get("quoteSummary") or {}).get("result") or [None])[0]
                if res:
                    res["coletado_em"] = agora()
                    gravar(os.path.join(saida, "meta", nome_arquivo(s) + ".json"), res)
                    ok[s] = sorted(k for k in res if k != "coletado_em")
                    feito = True
                    break
            if r.status not in (429, 500, 502, 503, 504):
                falhas.append(f"resumo {s}: HTTP {r.status}")
                break
        if not feito and s not in ok:
            pass
        time.sleep(0.5)
    return ok


def cotacoes(cli: Cliente, crumb, simbolos: list[str], saida: str, falhas: list) -> int:
    todas = []
    for i in range(0, len(simbolos), 40):
        lote = simbolos[i:i + 40]
        params = {"symbols": ",".join(lote)}
        if crumb:
            params["crumb"] = crumb
        for host in HOSTS:
            try:
                r = cli.get(f"{host}/v7/finance/quote", params=params)
            except HttpError:
                continue
            if r.status == 200:
                todas += (r.json().get("quoteResponse") or {}).get("result") or []
                break
            falhas.append(f"cotacao lote {i}: HTTP {r.status}")
    gravar(os.path.join(saida, "cotacoes.json"), {"coletado_em": agora(), "cotacoes": todas})
    return len(todas)


def fred(cli: Cliente, ids: list[str], saida: str, falhas: list) -> dict:
    ok = {}
    for i in ids:
        try:
            r = cli.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": i}, timeout=40)
        except HttpError as e:
            falhas.append(f"fred {i}: rede {e.body[:60]}")
            continue
        texto = r.text
        if r.status == 200 and texto[:40].lower().startswith(("observation_date", "date")):
            gravar(os.path.join(saida, "fred", i + ".csv"), texto)
            linhas = texto.strip().splitlines()
            ok[i] = linhas[-1]
        else:
            falhas.append(f"fred {i}: HTTP {r.status}")
        time.sleep(0.3)
    return ok


def texto_pdf(conteudo: bytes) -> str:
    from pypdf import PdfReader
    leitor = PdfReader(io.BytesIO(conteudo))
    partes = []
    for n, pag in enumerate(leitor.pages, 1):
        try:
            partes.append(f"[p. {n}]\n" + (pag.extract_text() or ""))
        except Exception as e:
            partes.append(f"[p. {n}] (falhou: {type(e).__name__})")
    return "\n".join(partes)


def baixar_doc(cli: Cliente, nome: str, url: str, saida: str, falhas: list) -> dict | None:
    try:
        r = cli.get(url, timeout=60)
    except HttpError as e:
        falhas.append(f"doc {nome}: rede {e.body[:60]}")
        return None
    if r.status != 200 or len(r.content) < 200:
        falhas.append(f"doc {nome}: HTTP {r.status}, {len(r.content)} bytes")
        return None
    caminho = os.path.join(saida, "docs", nome)
    gravar(caminho, r.content, binario=True)
    info = {"url": url, "bytes": len(r.content)}
    if nome.endswith(".pdf"):
        try:
            txt = texto_pdf(r.content)
            gravar(caminho[:-4] + ".txt", txt)
            info["chars_texto"] = len(txt)
        except Exception as e:
            falhas.append(f"doc {nome}: texto {type(e).__name__}")
    return info


def factset(cli: Cliente, saida: str, falhas: list, hoje: date) -> list:
    """Earnings Insight da FactSet: tenta as ultimas quatro sextas-feiras."""
    achados = []
    d = hoje
    while d.weekday() != 4:
        d -= timedelta(days=1)
    for k in range(4):
        sexta = d - timedelta(days=7 * k)
        info = baixar_doc(cli, f"factset_{sexta:%Y-%m-%d}.pdf", FACTSET.format(sexta), saida, [])
        if info:
            achados.append(f"{sexta:%Y-%m-%d}")
        if len(achados) >= 2:
            break
    if not achados:
        falhas.append("factset: nenhuma das ultimas quatro sextas")
    return achados


def isins_da_lista(texto: str, tickers: list[str]) -> dict:
    """Procura cada ticker como palavra inteira e pega o ISIN mais proximo na mesma linha
    ou nas vizinhas. A lista da Avenue traz uma linha por ETF."""
    linhas = texto.splitlines()
    achados = {}
    for t in tickers:
        rx = re.compile(rf"(?<![A-Z0-9]){re.escape(t)}(?![A-Z0-9])")
        for i, linha in enumerate(linhas):
            if not rx.search(linha):
                continue
            # mesma linha primeiro; depois a de baixo (nome longo quebra a linha); por ultimo a de cima
            m = RX_ISIN.findall(linha)
            if not m and i + 1 < len(linhas):
                m = RX_ISIN.findall(linhas[i + 1])
            if not m and i > 0:
                m = RX_ISIN.findall(linhas[i - 1])
            if m:
                achados.setdefault(t, []).append({"isin": m[0], "linha": linha.strip()[:220]})
    return achados


def limpar_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1>", "", html)
    html = re.sub(r"(?s)<!--.*?-->", "", html)
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n\s*\n+", "\n", html))


def justetf(cli: Cliente, isins: dict, saida: str, falhas: list) -> dict:
    ok = {}
    for t, isin in sorted(isins.items()):
        url = f"https://www.justetf.com/en/etf-profile.html?isin={isin}"
        try:
            r = cli.get(url, timeout=40)
        except HttpError as e:
            falhas.append(f"justetf {t} {isin}: rede {e.body[:60]}")
            continue
        if r.status == 200 and len(r.content) > 5000:
            limpo = limpar_html(r.text)
            gravar(os.path.join(saida, "justetf", f"{isin}.html"), limpo)
            ok[t] = {"isin": isin, "chars": len(limpo)}
        else:
            falhas.append(f"justetf {t} {isin}: HTTP {r.status}, {len(r.content)} bytes")
        time.sleep(1.2)
    return ok


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", required=True)
    ap.add_argument("--simbolos", default="")
    ap.add_argument("--fred", default="")
    ap.add_argument("--isins", default="", help="TICKER=ISIN separados por espaco")
    ap.add_argument("--docs", default="", help="nome=url separados por espaco")
    ap.add_argument("--partes", default="series,meta,cotacoes,fred,docs,factset,justetf")
    a = ap.parse_args(argv)
    partes = {p.strip() for p in a.partes.split(",") if p.strip()}
    simbolos = [s.strip() for s in a.simbolos.replace(" ", ",").split(",") if s.strip()] or SIMBOLOS
    ids_fred = [s.strip() for s in a.fred.replace(" ", ",").split(",") if s.strip()] or FRED
    docs = dict(DOCS)
    for par in a.docs.split():
        if "=" in par:
            n, u = par.split("=", 1)
            docs[n] = u
    isins = dict(ISINS)
    for par in a.isins.split():
        if "=" in par:
            t, i = par.split("=", 1)
            isins[t.upper()] = i.upper()

    os.makedirs(a.saida, exist_ok=True)
    falhas: list[str] = []
    manifest = {"gerado_em": agora(), "partes": {}}
    cli = Cliente()
    crumb = preparar_sessao(cli)
    manifest["cliente"] = {"tipo": cli.tipo, "crumb": bool(crumb)}

    def registra(nome, fn):
        t0 = time.time()
        try:
            manifest["partes"][nome] = {"resultado": fn(), "segundos": round(time.time() - t0, 1)}
        except Exception as e:
            falhas.append(f"{nome}: {type(e).__name__}: {str(e)[:120]}")
        print(f"[{nome}] {round(time.time() - t0, 1)} s", flush=True)

    if "series" in partes:
        registra("series", lambda: series(cli, crumb, simbolos, a.saida, falhas))
    if "cotacoes" in partes:
        registra("cotacoes", lambda: cotacoes(cli, crumb, simbolos, a.saida, falhas))
    if "meta" in partes:
        registra("meta", lambda: resumo(cli, crumb, simbolos, a.saida, falhas))
    if "fred" in partes:
        registra("fred", lambda: fred(Cliente(), ids_fred, a.saida, falhas))
    if "docs" in partes:
        registra("docs", lambda: {n: baixar_doc(Cliente(), n, u, a.saida, falhas) for n, u in docs.items()})
    if "factset" in partes:
        registra("factset", lambda: factset(Cliente(), a.saida, falhas, date.today()))
    # ISINs: os informados valem; a lista da Avenue completa os que faltam
    txt_avenue = os.path.join(a.saida, "docs", "avenue_ucits.txt")
    da_lista = {}
    if os.path.exists(txt_avenue):
        with open(txt_avenue, encoding="utf-8") as f:
            da_lista = isins_da_lista(f.read(), TICKERS_AVENUE)
        for t, lst in da_lista.items():
            isins.setdefault(t, lst[0]["isin"])
    gravar(os.path.join(a.saida, "isins.json"), {"usados": isins, "da_lista_avenue": da_lista, "gerado_em": agora()})
    if "justetf" in partes:
        registra("justetf", lambda: justetf(Cliente(), isins, a.saida, falhas))

    manifest["falhas"] = falhas
    gravar(os.path.join(a.saida, "manifest.json"), manifest)
    print(json.dumps({k: (v.get("segundos") if isinstance(v, dict) else v) for k, v in manifest["partes"].items()}))
    print(f"falhas: {len(falhas)}")
    for f in falhas[:60]:
        print("  -", f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

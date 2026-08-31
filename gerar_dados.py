#!/usr/bin/env python3
"""
Gera o retrato estatico do terminal para publicar no GitHub Pages.

Roda os mesmos coletores do app.py e grava o resultado como arquivos JSON
em site/api/, junto com uma copia do index.html. O GitHub Actions executa
isto de tempos em tempos e publica a pasta site/ — assim o terminal fica
disponivel como um endereco na web, sem ninguem precisar rodar servidor.

    python gerar_dados.py [--saida site]
"""

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import app  # reaproveita os coletores e o cache do servidor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Graficos gerados para cada ativo do universo
PERIODOS_GRAFICO = ("1mo", "1y")

resumo = {"arquivos": 0, "bytes": 0, "falhas": []}


def gravar(saida, caminho_rel, dados):
    destino = os.path.join(saida, caminho_rel)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    with open(destino, "w", encoding="utf-8") as f:
        f.write(texto)
    resumo["arquivos"] += 1
    resumo["bytes"] += len(texto.encode("utf-8"))


def coletar():
    """Roda os coletores na ordem de dependencia."""
    etapas = [
        ("cotacoes", app.refresh_quotes),
        ("indicadores", app.refresh_indicators),
        ("tesouro", app.refresh_tesouro),
        ("noticias", app.refresh_news),
        ("cvm", app.refresh_cvm),
        ("sec", app.refresh_sec),
    ]
    # os quatro primeiros nao dependem uns dos outros
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda e: executar(*e), etapas[:4]))
    for nome, fn in etapas[4:]:
        executar(nome, fn)

    # dependem do que acabou de ser coletado
    for nome, fn in (("curva DI", app.refresh_di),
                     ("spreads", app.refresh_spreads),
                     ("tir", app.refresh_tir)):
        executar(nome, fn)


def executar(nome, fn):
    try:
        fn()
    except Exception as e:
        msg = f"{nome}: {type(e).__name__}: {e}"
        print(f"  FALHA {msg}")
        resumo["falhas"].append(msg)


def gerar_graficos(saida):
    """Um JSON por ativo/periodo, para o grafico funcionar sem backend."""
    tickers = list(app.ALL_QUOTE_TICKERS) + [f"{s}-USD" for s, _, _ in app.CRYPTOS]
    tarefas = [(t, p) for t in tickers for p in PERIODOS_GRAFICO]

    def um(par):
        ticker, periodo = par
        intervalo = app.VALID_PERIODS.get(periodo, "1d")
        res = app.yahoo_chart(ticker, rng=periodo, interval=intervalo, timeout=12)
        if not res:
            return None
        try:
            stamps = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]
        except Exception:
            return None
        datas, precos = [], []
        for ts, c in zip(stamps, closes):
            if c is None:
                continue
            datas.append(datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"))
            precos.append(round(float(c), 4))
        if not precos:
            return None
        primeiro, atual = precos[0], precos[-1]
        return ticker, periodo, {
            "ticker": ticker,
            "dates": datas,
            "prices": precos,
            "current": atual,
            "change_pct": round(((atual - primeiro) / primeiro * 100.0) if primeiro else 0.0, 2),
            "high": max(precos),
            "low": min(precos),
            "period": periodo,
        }

    feitos = 0
    with ThreadPoolExecutor(max_workers=10) as pool:
        for r in pool.map(um, tarefas):
            if r:
                ticker, periodo, payload = r
                gravar(saida, f"api/asset/{nome_arquivo(ticker)}_{periodo}.json", payload)
                feitos += 1
    print(f"  graficos: {feitos}/{len(tarefas)}")


def nome_arquivo(ticker):
    """Ticker vira nome de arquivo seguro (^BVSP -> _BVSP, PETR4.SA -> PETR4.SA)."""
    return "".join(c if (c.isalnum() or c in ".-") else "_" for c in ticker)


def baixar_chartjs(saida):
    """Copia local do Chart.js dentro do site publicado."""
    destino = os.path.join(saida, "vendor", app.CHARTJS_ARQ)
    os.makedirs(os.path.dirname(destino), exist_ok=True)

    origem_local = os.path.join(BASE_DIR, "vendor", app.CHARTJS_ARQ)
    if os.path.exists(origem_local) and os.path.getsize(origem_local) > 50_000:
        shutil.copy(origem_local, destino)
    else:
        r = app.http_get(app.CHARTJS_URL, timeout=25)
        if not r or len(r.content) < 50_000:
            print("  AVISO: nao baixei o Chart.js; o site vai depender do CDN")
            resumo["falhas"].append("chart.js: download falhou")
            return
        with open(destino, "wb") as f:
            f.write(r.content)

    # /terminal/ resolve vendor/ com um nivel a menos
    dest_terminal = os.path.join(saida, "terminal", "vendor", app.CHARTJS_ARQ)
    os.makedirs(os.path.dirname(dest_terminal), exist_ok=True)
    shutil.copy(destino, dest_terminal)
    print(f"  chart.js: {os.path.getsize(destino)//1024} KB")


def gerar(saida):
    os.makedirs(saida, exist_ok=True)

    print("Coletando dados das fontes...")
    coletar()

    print("Gravando o retrato estatico...")
    cotacoes = app.CACHE.get("quotes") or {"quotes": {}, "crypto": {}}
    gravar(saida, "api/quotes.json", cotacoes)

    indicadores = app.CACHE.get("indicators") or {}
    gravar(saida, "api/indicators.json", {"indicators": indicadores})

    gravar(saida, "api/di.json", app.CACHE.get("di") or {"di": []})
    gravar(saida, "api/tesouro.json", app.CACHE.get("tesouro") or {"ipca": [], "pre": []})
    gravar(saida, "api/spreads.json", app.CACHE.get("spreads") or {"spreads": {}})
    gravar(saida, "api/spread_history.json",
           {"history": app.CACHE.get("spread_history") or []})
    gravar(saida, "api/news.json", app.CACHE.get("news") or {"news": [], "ts": ""})
    gravar(saida, "api/cvm.json", app.CACHE.get("cvm") or
           {"fatos": [], "corp_events": [], "sec_filings": [], "corp_highlights": []})
    gravar(saida, "api/weekly_summary.json", app.CACHE.get("weekly_summary") or
           {"br": [], "us": [], "week_label": ""})
    gravar(saida, "api/tir_all.json", app.CACHE.get("tir_all") or {"assets": []})
    gravar(saida, "api/watchlist.json", {"watchlist": app.default_watchlist()})

    # Sem servidor nao ha disparo de alerta em tempo real; o historico dos
    # fatos relevantes vem do proprio /api/cvm.
    fatos = (app.CACHE.get("cvm") or {}).get("fatos", [])
    gravar(saida, "api/alerts.json", {"alerts": []})
    gravar(saida, "api/alert_history.json", {"history": fatos[:100]})

    for chave in app.SGS_SERIES:
        hist = app.indicator_history(chave, points=240)
        gravar(saida, f"api/indicator_history/{chave}.json", hist)

    gerar_graficos(saida)

    # Manifesto: o front usa para saber que existe retrato estatico e de quando e
    gravar(saida, "api/manifest.json", {
        "gerado_em": app.utcnow_iso(),
        "modo": "estatico",
        "tickers": len(cotacoes.get("quotes", {})),
        "indicadores": len(indicadores),
        "noticias": len((app.CACHE.get("news") or {}).get("news", [])),
        "fatos_cvm": len(fatos),
        "falhas": resumo["falhas"],
    })

    # Chart.js junto: o site publicado nao depende do CDN estar no ar
    baixar_chartjs(saida)

    # O terminal em si
    shutil.copy(os.path.join(BASE_DIR, "index.html"), os.path.join(saida, "index.html"))
    # /terminal tambem funciona no Pages
    os.makedirs(os.path.join(saida, "terminal"), exist_ok=True)
    shutil.copy(os.path.join(BASE_DIR, "index.html"),
                os.path.join(saida, "terminal", "index.html"))
    # o Pages ignora pastas com _ na frente sem isto
    open(os.path.join(saida, ".nojekyll"), "w").close()

    mb = resumo["bytes"] / 1_000_000
    print(f"\n{resumo['arquivos']} arquivos, {mb:.2f} MB em {saida}/")
    if resumo["falhas"]:
        print(f"Fontes que falharam ({len(resumo['falhas'])}):")
        for f in resumo["falhas"]:
            print(f"  - {f}")
    return resumo


def main():
    ap = argparse.ArgumentParser(description="Gera o retrato estatico do terminal")
    ap.add_argument("--saida", default="site")
    args = ap.parse_args()

    r = gerar(args.saida)

    # Publicar uma tela vazia seria pior que nao publicar: se nem cotacao nem
    # noticia vieram, e falha de coleta e o passo deve quebrar.
    cot = len((app.CACHE.get("quotes") or {}).get("quotes", {}))
    noticias = len((app.CACHE.get("news") or {}).get("news", []))
    if cot == 0 and noticias == 0:
        print("\nERRO: nenhuma cotacao e nenhuma noticia foram coletadas.")
        sys.exit(1)


if __name__ == "__main__":
    main()

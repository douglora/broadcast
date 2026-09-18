"""Yahoo Finance chart v8: series diarias (OHLCV + fechamento ajustado + eventos)
para todos os simbolos do livro e benchmarks.

    https://query1.finance.yahoo.com/v8/finance/chart/<SIMBOLO>?range=2y&interval=1d&events=div%2Csplit

Regras: sessao de navegador (curl_cffi) + cookie fc.yahoo.com + crumb quando
possivel; rodadas de retry so para 429/5xx/rede; falha por simbolo e
declarada e a serie anterior (ja no branch dados) e preservada."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from livro.http import Cliente, HttpError, com_rodadas

HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
COOKIE_URL = "https://fc.yahoo.com/"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"


def preparar_sessao(cli: Cliente) -> str | None:
    """Cookie + crumb. Devolve o crumb (ou None, e seguimos sem ele)."""
    try:
        cli.get(COOKIE_URL, timeout=15)
    except HttpError:
        pass
    try:
        r = cli.get(CRUMB_URL, timeout=15)
        texto = r.text.strip()
        if r.status == 200 and texto and "<" not in texto and len(texto) < 40:
            return texto
    except HttpError:
        pass
    return None


def parse_chart(payload: dict, simbolo: str) -> dict:
    """JSON do chart v8 -> {barras, eventos, meta}. Barras sem close sao descartadas."""
    res = (payload.get("chart") or {}).get("result") or []
    if not res:
        erro = ((payload.get("chart") or {}).get("error") or {}).get("description", "sem result")
        raise ValueError(f"chart vazio: {erro}")
    r = res[0]
    meta = r.get("meta") or {}
    tz = meta.get("exchangeTimezoneName") or "UTC"
    zona = ZoneInfo(tz) if tz else timezone.utc
    stamps = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((r.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    barras = []
    for i, ts in enumerate(stamps):
        close = (q.get("close") or [None] * len(stamps))[i]
        if close is None:
            continue
        d = datetime.fromtimestamp(ts, zona).date().isoformat()
        aj = adj[i] if i < len(adj) and adj[i] is not None else close

        def v(nome):
            arr = q.get(nome) or []
            return arr[i] if i < len(arr) else None

        barras.append([d, v("open"), v("high"), v("low"), float(close), float(aj), v("volume")])
    ev = r.get("events") or {}
    dividendos = sorted(
        [[datetime.fromtimestamp(int(x.get("date", 0)), zona).date().isoformat(), x.get("amount")]
         for x in (ev.get("dividends") or {}).values() if x.get("date")])
    splits = sorted(
        [[datetime.fromtimestamp(int(x.get("date", 0)), zona).date().isoformat(), x.get("splitRatio")]
         for x in (ev.get("splits") or {}).values() if x.get("date")])
    return {
        "simbolo": simbolo,
        "moeda": meta.get("currency"),
        "tz": tz,
        "meta": {
            "regularMarketPrice": meta.get("regularMarketPrice"),
            "previousClose": meta.get("previousClose") or meta.get("chartPreviousClose"),
            "marketState": meta.get("marketState"),
            "regularMarketTime": meta.get("regularMarketTime"),
            "exchangeName": meta.get("exchangeName") or meta.get("fullExchangeName"),
            "instrumentType": meta.get("instrumentType"),
        },
        "barras": barras,
        "eventos": {"dividendos": dividendos, "splits": splits},
    }


def baixar_serie(cli: Cliente, simbolo: str, rng: str = "2y", crumb: str | None = None,
                 intervalo: str = "1d") -> dict:
    params = {"range": rng, "interval": intervalo, "events": "div,split", "includeAdjustedClose": "true"}
    if crumb:
        params["crumb"] = crumb
    ultimo_erro: Exception | None = None
    for host in HOSTS:
        url = f"{host}/v8/finance/chart/{simbolo}"
        try:
            r = cli.get(url, params=params)
        except HttpError as e:
            ultimo_erro = e
            continue
        if r.status == 200:
            dados = parse_chart(r.json(), simbolo)
            dados["coletado_em"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return dados
        ultimo_erro = HttpError(r.status, r.text, url)
        if r.status not in (429, 500, 502, 503, 504):
            break
    raise ultimo_erro or HttpError(0, "sem resposta", simbolo)


def coletar(simbolos: list[str], rng: str = "2y", cli: Cliente | None = None,
            dormir=None) -> tuple[dict, dict]:
    """Baixa todas as series com rodadas de retry. Devolve ({simbolo: dados}, {simbolo: erro})."""
    cli = cli or Cliente()
    crumb = preparar_sessao(cli)
    kw = {"dormir": dormir} if dormir else {}
    return com_rodadas(lambda s: baixar_serie(cli, s, rng, crumb), simbolos, espaco=0.4, **kw)


def mesclar(antiga: dict | None, nova: dict | None) -> dict | None:
    """Serie nova substitui a antiga; se a nova falhou, a antiga fica (com marca de idade)."""
    if nova:
        return nova
    if antiga:
        antiga = dict(antiga)
        antiga["reaproveitada"] = True
        return antiga
    return None


def sonda(simbolos: list[str], cli: Cliente | None = None) -> dict:
    """Cobertura ticker a ticker: status, barras, moeda, fuso, tem adjclose/volume, ultima data."""
    cli = cli or Cliente()
    crumb = preparar_sessao(cli)
    out = {"cliente": cli.tipo, "crumb": bool(crumb), "simbolos": {}}
    for s in simbolos:
        try:
            d = baixar_serie(cli, s, "2y", crumb)
            b = d["barras"]
            out["simbolos"][s] = {
                "status": "ok", "barras": len(b), "moeda": d.get("moeda"), "tz": d.get("tz"),
                "primeira": b[0][0] if b else None, "ultima": b[-1][0] if b else None,
                "tem_volume": any(x[6] for x in b[-20:]) if b else False,
                "adj_diferente": any(x[4] != x[5] for x in b) if b else False,
                "marketState": d["meta"].get("marketState"),
            }
        except HttpError as e:
            out["simbolos"][s] = {"status": f"HTTP {e.status}" if e.status else "rede", "detalhe": e.body}
        except Exception as e:
            out["simbolos"][s] = {"status": f"erro {type(e).__name__}", "detalhe": str(e)[:120]}
    return out

"""Agenda corporativa: data do proximo resultado e do proximo ex-dividendo por
ativo (Yahoo quoteSummary: calendarEvents + defaultKeyStatistics), consolidada
com config/calendario.yaml (entrada 'confirmado' do config vence o agregador).

O Yahoo e fraco para .SA (data de resultado muitas vezes estimada); por isso o
que vem dele e sempre rotulado 'estimado' e a data-com de provento e conferida
pelo aviso aos acionistas (CVM) quando existir."""

from __future__ import annotations

import time
from datetime import date, datetime, timezone

from livro.http import Cliente, HttpError

QS_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{simbolo}"
MODULOS = "calendarEvents,defaultKeyStatistics"


def _data(epoch) -> str | None:
    try:
        return datetime.fromtimestamp(int(epoch), timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _raw(d: dict | None):
    if isinstance(d, dict):
        return d.get("raw")
    return d


def parse_quote_summary(payload: dict) -> dict:
    """{resultado_datas: [iso], ex_dividendo: iso|None, pagamento: iso|None,
    ultimo_dividendo: float|None, ultimo_dividendo_data: iso|None}"""
    res = ((payload.get("quoteSummary") or {}).get("result") or [{}])[0] or {}
    cal = res.get("calendarEvents") or {}
    ks = res.get("defaultKeyStatistics") or {}
    earn = (cal.get("earnings") or {}).get("earningsDate") or []
    datas = [d for d in (_data(_raw(x)) for x in earn) if d]
    return {
        "resultado_datas": sorted(set(datas)),
        "resultado_estimado": bool((cal.get("earnings") or {}).get("isEarningsDateEstimate", True)),
        "ex_dividendo": _data(_raw(cal.get("exDividendDate"))),
        "pagamento": _data(_raw(cal.get("dividendDate"))),
        "ultimo_dividendo": _raw(ks.get("lastDividendValue")),
        "ultimo_dividendo_data": _data(_raw(ks.get("lastDividendDate"))),
    }


def coletar(universo, cli: Cliente | None = None, crumb: str | None = None, dormir=None, so_classes=("acao", "etf")) -> dict:
    """Uma requisicao por ativo (acoes e ETFs). Falha por ativo e declarada, nao derruba a perna."""
    from livro.fontes import yahoo
    dormir = dormir or time.sleep
    cli = cli or Cliente()
    if crumb is None:
        crumb = yahoo.preparar_sessao(cli)
    por_ativo, falhas = {}, {}
    for a in universo.ativos:
        if not a.ativo or a.classe not in so_classes or a.proxy:
            continue
        params = {"modules": MODULOS}
        if crumb:
            params["crumb"] = crumb
        try:
            r = cli.get(QS_URL.format(simbolo=a.yahoo), params=params, timeout=25)
            if r.status != 200:
                falhas[a.id] = f"HTTP {r.status}"
                continue
            por_ativo[a.id] = parse_quote_summary(r.json())
        except (HttpError, ValueError) as e:
            falhas[a.id] = str(e)[:80]
        dormir(0.3)
    return {"por_ativo": por_ativo, "falhas": falhas, "coletado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def consolidar(calendario: dict, por_ativo: dict, hoje: date, universo=None, horizonte_dias: int = 45) -> dict:
    """Resultados e ex-dividendos futuros: config confirmado > config estimado > Yahoo."""
    resultados: dict[str, dict] = {}
    for r in calendario.get("resultados") or []:
        d = str(r.get("data"))[:10]
        if d < hoje.isoformat():
            continue
        resultados[r["ticker"]] = {"ticker": r["ticker"], "data": d, "quando": r.get("quando", ""),
                                   "confirmado": bool(r.get("confirmado")), "fonte": r.get("fonte") or "config/calendario.yaml",
                                   "nota": r.get("nota", "")}
    for ativo, info in (por_ativo or {}).items():
        datas = [d for d in info.get("resultado_datas") or [] if d >= hoje.isoformat()]
        if not datas:
            continue
        d = datas[0]
        atual = resultados.get(ativo)
        if atual and (atual["confirmado"] or atual["data"] == d):
            atual.setdefault("yahoo", d)
            continue
        if atual and not atual["confirmado"]:
            atual["yahoo"] = d
            if abs((date.fromisoformat(d) - date.fromisoformat(atual["data"])).days) > 3:
                atual["nota"] = (atual.get("nota", "") + f" Yahoo indica {d[8:10]}/{d[5:7]}.").strip()
            continue
        resultados[ativo] = {"ticker": ativo, "data": d, "quando": "", "confirmado": False,
                             "fonte": "Yahoo (estimado)" if info.get("resultado_estimado", True) else "Yahoo",
                             "nota": "faixa " + " a ".join(datas[:2]) if len(datas) > 1 else ""}
    ex_divs = []
    for ativo, info in (por_ativo or {}).items():
        d = info.get("ex_dividendo")
        if not d or d < hoje.isoformat():
            continue
        if (date.fromisoformat(d) - hoje).days > horizonte_dias:
            continue
        moeda = ""
        if universo is not None:
            a = universo.por_id(ativo)
            moeda = {"BRL": "R$", "USD": "US$"}.get(a.moeda, "") if a else ""
        ex_divs.append({"ticker": ativo, "data": d, "valor": info.get("ultimo_dividendo"), "moeda": moeda,
                        "pagamento": info.get("pagamento"), "nota": "valor = último provento pago (Yahoo); conferir aviso aos acionistas"})
    fim = hoje.isoformat()
    lista = sorted([r for r in resultados.values() if (date.fromisoformat(r["data"]) - hoje).days <= horizonte_dias], key=lambda r: r["data"])
    return {"resultados": lista, "ex_dividendos": sorted(ex_divs, key=lambda e: e["data"]), "referencia": fim}

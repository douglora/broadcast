"""Preco de fechamento de um pregao para acoes, FII e opcoes, no arquivo publico da B3
(TradeInformationConsolidated, o mesmo do opcoes.py). Guarda o arquivo do dia em cache para a
rotina nao baixar de novo.

Preco = ultimo negocio do dia (LastPric). Serie sem negocio no dia sai pelo ultimo negocio dos
pregoes anteriores (ate `volta` pregoes), como a IRTrade faz (conferido no fechamento de 30/09/2026, numa
serie sem negocio no dia: vale o ultimo negocio, e nao a referencia da B3); sem negocio na janela, vale a
referencia (RefPric), marcada 'ref'.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

AQUI = pathlib.Path(__file__).resolve().parent.parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))


def _num(s):
    s = (s or '').strip()
    if not s:
        return None
    try:
        return float(s.replace('.', '').replace(',', '.')) if ',' in s else float(s)
    except ValueError:
        return None


def pregao(dia: dt.date, cache: pathlib.Path | None = None) -> dict:
    """{ticker: {'ultimo', 'ref'}} do arquivo da B3 do dia; {} se nao houve pregao ou nao saiu ainda."""
    arq = cache / f'b3_{dia.isoformat()}.json' if cache else None
    if arq and arq.exists():
        return json.loads(arq.read_text())
    import opcoes                                   # noqa: E402 (cliente HTTP e leitor da B3)
    from livro.http import Cliente                  # noqa: E402
    brutas = opcoes.baixar_arquivo(Cliente(), 'TradeInformationConsolidated', dia) or []
    linhas = {r['TckrSymb'].strip(): {'ultimo': _num(r.get('LastPric')), 'ref': _num(r.get('RefPric'))}
              for r in brutas if r.get('TckrSymb')}
    if arq and linhas:
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps(linhas))
    return linhas


def _instrumentos(dia: dt.date) -> list[dict] | None:
    """Cadastro de instrumentos da B3 do dia (InstrumentsConsolidated, o mesmo do opcoes.py); None se nao saiu."""
    import opcoes                                   # noqa: E402
    from livro.http import Cliente                  # noqa: E402
    try:
        return opcoes.baixar_arquivo(Cliente(), 'InstrumentsConsolidated', dia)
    except Exception:       # noqa: BLE001  (rede)
        return None


def series(dia: dt.date, tickers: list[str], cache: pathlib.Path | None = None, volta: int = 5) -> dict[str, dict]:
    """{serie: {'strike', 'vencimento', 'tipo', 'subjacente', 'estilo', 'dia'}} das opcoes pedidas, no cadastro de
    instrumentos da B3 do pregao `dia` (ou do anterior, ate `volta` pregoes, se ele nao saiu). O strike e o do dia: a B3
    o ajusta quando o ativo-objeto paga provento. Guarda so as series pedidas (o cadastro inteiro tem ~90 mil linhas)."""
    tickers = sorted(set(tickers))
    d, n = dia, 0
    while tickers and n <= volta:
        if d.weekday() < 5:
            n += 1
            arq = cache / f'series_{d.isoformat()}.json' if cache else None
            guardado = json.loads(arq.read_text()) if arq and arq.exists() else {}
            if set(tickers) <= set(guardado.get('pedidos', [])):
                return {t: guardado['series'][t] for t in tickers if t in guardado['series']}
            brutas = _instrumentos(d)
            if brutas:
                pedidos = sorted(set(tickers) | set(guardado.get('pedidos', [])))
                achadas = {}
                for r in brutas:
                    t = (r.get('TckrSymb') or '').strip()
                    if t in pedidos and (r.get('OptnTp') or '').strip():
                        achadas[t] = {'strike': _num(r.get('ExrcPric')), 'vencimento': (r.get('XprtnDt') or '')[:10] or None,
                                      'tipo': r['OptnTp'].strip().lower(), 'subjacente': (r.get('Asst') or '').strip() or None,
                                      'estilo': (r.get('OptnStyle') or '').strip().lower() or None, 'dia': d.isoformat()}
                if arq:
                    arq.parent.mkdir(parents=True, exist_ok=True)
                    arq.write_text(json.dumps({'pedidos': pedidos, 'series': achadas}))
                return {t: achadas[t] for t in tickers if t in achadas}
        d -= dt.timedelta(1)
    return {}


def fechamento(dia: dt.date, tickers: list[str], cache: pathlib.Path | None = None,
               volta: int = 15) -> dict[str, dict]:
    """{ticker: {'preco', 'fonte': 'ultimo'|'ref', 'dia'}} dos tickers pedidos, no fechamento de `dia`."""
    linhas = pregao(dia, cache)
    out, falta = {}, []
    for t in tickers:
        r = linhas.get(t) or {}
        if r.get('ultimo'):
            out[t] = {'preco': r['ultimo'], 'fonte': 'ultimo', 'dia': dia.isoformat()}
        else:
            falta.append(t)
    d, n = dia, 0
    while falta and n < volta:
        d -= dt.timedelta(1)
        if d.weekday() >= 5:
            continue
        ant = pregao(d, cache)
        if not ant:
            continue
        n += 1
        for t in list(falta):
            if (ant.get(t) or {}).get('ultimo'):
                out[t] = {'preco': ant[t]['ultimo'], 'fonte': 'ultimo', 'dia': d.isoformat()}
                falta.remove(t)
    for t in falta:
        if (linhas.get(t) or {}).get('ref'):
            out[t] = {'preco': linhas[t]['ref'], 'fonte': 'ref', 'dia': dia.isoformat()}
    return out

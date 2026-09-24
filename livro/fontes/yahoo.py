"""Yahoo Finance chart v8: series diarias (OHLCV + fechamento ajustado + eventos)
para todos os simbolos do livro e benchmarks.

    https://query1.finance.yahoo.com/v8/finance/chart/<SIMBOLO>?range=2y&interval=1d&events=div%2Csplit

Regras: sessao de navegador (curl_cffi) + cookie fc.yahoo.com + crumb quando
possivel; rodadas de retry so para 429/5xx/rede; falha por simbolo e
declarada e a serie anterior (ja no branch dados) e preservada."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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


def parse_chart(payload: dict, simbolo: str, diario: bool = True) -> dict:
    """JSON do chart v8 -> {barras, eventos, meta}. Barras sem close sao descartadas.
    Com diario=False (graficos de minutos), devolve tambem `_intradia` = [[ts, close]]
    e nao mexe em datas repetidas, que ali sao a regra."""
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
    redatadas = []
    # so futuro e indice da ICE negociam a noite com sessao nova as 18h de Nova York;
    # cambio e acao tambem mandam duas linhas do mesmo dia (a diaria e a viva), e ai a
    # ULTIMA vence, como sempre foi (revisao de 23/09: redatar o USDBRL criava barra
    # fantasma no dia seguinte e cegava o portao)
    tipo = str(meta.get("instrumentType") or "").upper()
    bolsa = str(meta.get("exchangeName") or "").upper()
    noturno = (tipo == "FUTURE" or simbolo.endswith("=F") or bolsa in ("NYB", "ICE", "NYM", "CMX")
               or bool(re.match(r"^[A-Z]{1,4}[FGHJKMNQUVXZ]\d{2}\.(NYM|CMX|CBT|CME|NYB)$", simbolo)))
    reabre = {"America/New_York": 18, "America/Chicago": 17}.get(tz)
    for i, ts in enumerate(stamps):
        close = (q.get("close") or [None] * len(stamps))[i]
        if close is None:
            continue
        d = datetime.fromtimestamp(ts, zona).date().isoformat()
        aj = adj[i] if i < len(adj) and adj[i] is not None else close

        def v(nome):
            arr = q.get(nome) or []
            return arr[i] if i < len(arr) else None

        nova = [d, v("open"), v("high"), v("low"), float(close), float(aj), v("volume")]
        if diario and barras and barras[-1][0] == d:
            hora_local = datetime.fromtimestamp(ts, zona).hour
            if noturno and reabre is not None and hora_local >= reabre:
                # Futuro/ICE, segunda linha da mesma data depois das 18h ET: e a sessao
                # seguinte (23/09 no BZX26.NYM: 103,08 com volume 47 mil e depois 101,94
                # com volume 958, as duas "de 23/09"). Pertence ao proximo dia util.
                nova[0] = _proximo_dia_util(d)
                redatadas.append(nova[0])
            else:
                barras[-1] = nova          # mesma sessao: a linha mais nova vence
                continue
        barras.append(nova)
    ev = r.get("events") or {}
    dividendos = sorted(
        [[datetime.fromtimestamp(int(x.get("date", 0)), zona).date().isoformat(), x.get("amount")]
         for x in (ev.get("dividends") or {}).values() if x.get("date")])
    splits = sorted(
        [[datetime.fromtimestamp(int(x.get("date", 0)), zona).date().isoformat(), x.get("splitRatio")]
         for x in (ev.get("splits") or {}).values() if x.get("date")])
    out = {
        "simbolo": simbolo,
        "moeda": meta.get("currency"),
        "tz": tz,
        "meta": {
            "regularMarketPrice": meta.get("regularMarketPrice"),
            # sem fallback: o chartPreviousClose e o fechamento ANTES da janela pedida
            # (no BZ=F saia 73,9 como "fechamento anterior")
            "previousClose": meta.get("previousClose"),
            "chartPreviousClose": meta.get("chartPreviousClose"),
            "marketState": meta.get("marketState"),
            "regularMarketTime": meta.get("regularMarketTime"),
            "exchangeName": meta.get("exchangeName") or meta.get("fullExchangeName"),
            "instrumentType": meta.get("instrumentType"),
        },
        "barras": barras,
        "eventos": {"dividendos": dividendos, "splits": splits},
    }
    if redatadas:
        out["barras_redatadas"] = redatadas
    if not diario:
        closes = q.get("close") or []
        out["_intradia"] = [[ts, float(closes[i])] for i, ts in enumerate(stamps)
                            if i < len(closes) and closes[i] is not None]
    return out


def normalizar_datas(barras: list[list], noturno: bool) -> list[list]:
    """Datas repetidas num arquivo ja gravado (o parser antigo guardava as duas linhas
    "de 23/09" do BZX26.NYM). Futuro/ICE: a segunda e a sessao seguinte e vai para o
    proximo dia util; resto: a mais nova vence. Mesma regra do parse_chart."""
    out: list[list] = []
    for b in barras or []:
        if out and out[-1][0] == b[0]:
            if noturno:
                out.append([_proximo_dia_util(b[0]), *b[1:]])
            else:
                out[-1] = b
            continue
        out.append(b)
    out.sort(key=lambda x: x[0])
    return out


def _proximo_dia_util(iso: str) -> str:
    from datetime import date, timedelta
    d = date.fromisoformat(iso) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


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
            dados = parse_chart(r.json(), simbolo, diario=intervalo == "1d")
            if not intervalo.endswith("m"):
                dados.pop("_intradia", None)     # semanal: nao guarda o bruto
            dados["coletado_em"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return dados
        ultimo_erro = HttpError(r.status, r.text, url)
        if r.status not in (429, 500, 502, 503, 504):
            break
    raise ultimo_erro or HttpError(0, "sem resposta", simbolo)


def coletar(simbolos: list[str], rng: str = "2y", cli: Cliente | None = None,
            dormir=None, intervalo: str = "1d") -> tuple[dict, dict]:
    """Baixa todas as series com rodadas de retry. Devolve ({simbolo: dados}, {simbolo: erro})."""
    cli = cli or Cliente()
    crumb = preparar_sessao(cli)
    kw = {"dormir": dormir} if dormir else {}
    return com_rodadas(lambda s: baixar_serie(cli, s, rng, crumb, intervalo=intervalo),
                       simbolos, espaco=0.4, **kw)


MAX_BARRAS = 800   # ~3,2 anos: cobre 1a e YTD com folga e limita o tamanho do arquivo
REPRECIFICACAO = 0.005   # mediana da diferenca nas datas comuns que denuncia rolagem/split


def _reprecificada(antigas: list[list], novas: list[list], limiar: float = REPRECIFICACAO) -> float | None:
    """Mediana da diferenca relativa nas datas comuns, se passar do limiar.

    Futuro continuo (BZ=F, TIO=F) troca de vencimento e o Yahoo reprecifica a serie
    inteira; split faz o mesmo. Nesses casos unir barras antigas com novas misturaria
    dois contratos: a serie nova tem de valer sozinha."""
    import statistics
    nova_por_data = {b[0]: b for b in novas}
    difs = [abs(b[4] / nova_por_data[b[0]][4] - 1.0) for b in antigas
            if b[0] in nova_por_data and b[4] and nova_por_data[b[0]][4]]
    if len(difs) < 5:
        return None
    m = statistics.median(difs)
    return m if m > limiar else None


def _mediana(xs):
    import statistics
    xs = [x for x in xs if x]
    return statistics.median(xs) if xs else 0.0


def barra_sa(b: list, ref: list[list]) -> bool:
    """Barra coerente: abertura e fechamento dentro da maxima e da minima (0,1%) e,
    quando a serie tem volume, volume >= 5% da mediana das barras de referencia.
    Barra so com fechamento (O/H/L vazios ou zero) conta como sa."""
    try:
        o, h, l, c, vol = b[1], b[2], b[3], b[4], b[6]
    except (IndexError, TypeError):
        return False
    if None not in (o, h, l, c) and h and l and h >= l:
        tol = 0.001
        if c > h * (1 + tol) or c < l * (1 - tol) or o > h * (1 + tol) or o < l * (1 - tol):
            return False
    med = _mediana([x[6] for x in ref if len(x) > 6])
    if med and vol and vol < 0.05 * med:
        return False
    return True


def troca_de_contrato(antiga: list, nova: list, tol: float = 0.002) -> bool:
    """Futuro, mesma data: as duas barras nao cabem no mesmo pregao (a maxima nova
    abaixo da antiga ou a minima nova acima), sinal de que o continuo trocou de
    vencimento no meio do caminho."""
    try:
        ha, la, hn, ln = antiga[2], antiga[3], nova[2], nova[3]
    except (IndexError, TypeError):
        return False
    if None in (ha, la, hn, ln) or not ha or not la:
        return False
    return hn < ha * (1 - tol) or ln > la * (1 + tol)


def mesclar(antiga: dict | None, nova: dict | None, max_barras: int = MAX_BARRAS) -> dict | None:
    """Une as barras por data: a coleta nova vence na mesma data, mas NENHUMA barra ja
    guardada e descartada.

    O Yahoo as vezes devolve a serie sem a barra do ultimo pregao (visto em 18/09:
    o chart de MU terminava em 17/09 com o fechamento de 18/09 em meta.regularMarketPrice).
    Substituir a serie inteira fazia a tabela do Fechamento voltar um dia.
    Se a coleta falhou, a antiga fica com marca de idade."""
    if nova is not None:
        antigas = (antiga or {}).get("barras") or []
        if not antigas:
            return nova
        dif = _reprecificada(antigas, nova.get("barras") or [])
        if dif is not None:
            return {**nova, "reprecificada": round(dif, 4)}
        por_data = {b[0]: b for b in antigas}
        rejeitadas = []
        futuro = str((nova.get("meta") or {}).get("instrumentType") or "").upper() == "FUTURE" \
            or str(nova.get("simbolo") or "").endswith("=F") \
            or str((nova.get("meta") or {}).get("exchangeName") or "").upper() in ("NYB", "ICE", "NYM", "CMX")
        ref = [b for b in antigas[-21:]]
        for b in (nova.get("barras") or []):
            velha = por_data.get(b[0])
            if velha is not None and not barra_sa(b, ref) and barra_sa(velha, ref):
                # a coleta nova trouxe uma barra podre (OHLC incoerente, toco de volume)
                # para uma data que ja tinha barra boa: fica a boa (18/09 do Brent
                # virou 104,09/100,14/97,81/99,29, abertura acima da maxima)
                rejeitadas.append(b[0])
                continue
            if velha is not None and futuro and barra_sa(velha, ref) and troca_de_contrato(velha, b):
                # a guardada e sa e a nova nao cabe no mesmo pregao: o continuo trocou de
                # vencimento; fica a guardada (se a guardada e podre, a nova entra acima)
                rejeitadas.append(b[0])
                continue
            por_data[b[0]] = b
        barras = [por_data[k] for k in sorted(por_data)][-max_barras:]
        datas_novas = {x[0] for x in (nova.get("barras") or [])}
        out = {**nova, "barras": barras}
        if rejeitadas:
            out["revisoes_rejeitadas"] = rejeitadas[-10:]
        # So e anomalia quando a barra MAIS RECENTE veio do historico: e o caso que o
        # docstring descreve. No intradia a coleta e range=5d, entao centenas de datas
        # antigas ficam fora da janela por construcao - contar isso fazia o log dizer
        # "80 series com barra faltando" em toda rodada intradiaria.
        if barras and barras[-1][0] not in datas_novas:
            out["barras_recuperadas"] = [b[0] for b in barras if b[0] not in datas_novas][-5:]
        return out
    if antiga:
        antiga = dict(antiga)
        antiga["reaproveitada"] = True
        return antiga
    return None


def fechamentos_intradia(cli: Cliente, simbolo: str, hora_corte: str = "17:00",
                         tz_corte: str = "America/Sao_Paulo", crumb: str | None = None, rng: str = "5d") -> dict:
    """{data: [preco, 'hh:mm']}: ultimo negocio ate `hora_corte` (fuso `tz_corte`) de
    cada dia, a partir do grafico de 15 minutos dos ultimos 5 dias.

    A barra DIARIA do USDBRL=X no Yahoo nao presta para o fechamento: em 23/09 a
    barra "de 23/09" fechava em 5,0999 (o numero da vespera) e a de 24/09 abria em
    5,1625; o dolar tinha subido 1,28%. O dolar a vista no Brasil fecha as 17h."""
    d = baixar_serie(cli, simbolo, rng, crumb, intervalo="15m")
    hh, mm = (int(x) for x in hora_corte.split(":"))
    z = ZoneInfo(tz_corte)
    out: dict = {}
    for b in d.get("_intradia") or []:
        ts, preco = b
        t = datetime.fromtimestamp(ts, z)
        # a barra de 15 min que COMECA antes do corte e a ultima que termina ate ele (a
        # das 16h45 fecha as 17h00); o rotulo e a hora em que a barra termina
        if (t.hour, t.minute) < (hh, mm) and t.weekday() < 5:
            fim = t + timedelta(minutes=15)
            out[t.date().isoformat()] = [preco, f"{fim:%H:%M}"]
    # dia sem negocio na ultima meia hora antes do corte nao e fechamento
    minimo = f"{(hh * 60 + mm - 30) // 60:02d}:{(hh * 60 + mm - 30) % 60:02d}"
    return {k: x for k, x in out.items() if x[1] > minimo}


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
                # as 3 ultimas barras: para conferir contrato explicito e toco sem outro run
                "ultimas": [[x[0], x[4], x[6]] for x in b[-3:]],
            }
        except HttpError as e:
            out["simbolos"][s] = {"status": f"HTTP {e.status}" if e.status else "rede", "detalhe": e.body}
        except Exception as e:
            out["simbolos"][s] = {"status": f"erro {type(e).__name__}", "detalhe": str(e)[:120]}
    return out

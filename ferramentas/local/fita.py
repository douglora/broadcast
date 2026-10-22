#!/usr/bin/env python3
"""Fita intradia: o caminho do preco dentro do pregao, hora a hora, direto do Yahoo.

So roda com internet aberta (computador do Douglas). Na nuvem o Yahoo era
bloqueado e o dia tinha de ser reconstruido pelo historico do git das series
do livro (caso CURY3 de 30/09/2026). Aqui a barra intradia vem direto:

    python3 ferramentas/local/fita.py CURY3 DIRR3 TEND3                 # ultimo pregao, barras de 60 min
    python3 ferramentas/local/fita.py CURY3 DIRR3 --dia 2026-09-30      # um pregao passado
    python3 ferramentas/local/fita.py CURY3 DIRR3 --intervalo 15m       # 60m | 30m | 15m | 5m
    python3 ferramentas/local/fita.py PETR4 BRENT USDBRL --json         # ids do livro tambem valem

O primeiro ticker e a referencia: a ultima tabela mostra a diferenca dele contra
cada um dos outros, hora a hora, e marca a hora em que a divergencia abriu.

Limites do Yahoo: 60m guarda cerca de 2 anos; 30m, 15m e 5m guardam 60 dias.
A cotacao da B3 no Yahoo atrasa uns 15 minutos. Variacao sempre contra o
fechamento do pregao anterior. Nada aqui e regra do livro nem vai para o branch
`dados`: e leitura de apoio para a pergunta "por que mexeu".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from livro.http import Cliente  # noqa: E402

BRT = ZoneInfo("America/Sao_Paulo")
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{s}"
INTERVALOS = ("60m", "30m", "15m", "5m")
DIAS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")


def simbolo_yahoo(nome: str) -> str:
    """Id do livro (BRENT, USDBRL, VWRA) vira o simbolo do config; ticker da B3 ganha .SA."""
    n = nome.strip().upper()
    try:
        from livro import universo
        u = universo.carregar()
        achado = u.por_id(n) or u.bench(n)
        if achado is not None and getattr(achado, "yahoo", None):
            return achado.yahoo
    except Exception:
        pass
    if "." in n or "=" in n or n.startswith("^") or "-" in n:
        return n
    if n[-1:].isdigit() and len(n) in (5, 6):
        return n + ".SA"
    return n


def pct(x: float | None, casas: int = 1) -> str:
    if x is None:
        return "-"
    return f"{x:+.{casas}f}%".replace(".", ",").replace("-", "−")


def num(x: float | None, casas: int = 2) -> str:
    if x is None:
        return "-"
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def baixar(cli: Cliente, simbolo: str, ini: datetime, fim: datetime, intervalo: str) -> dict:
    url = (CHART.format(s=simbolo) + f"?period1={int(ini.timestamp())}&period2={int(fim.timestamp())}"
           f"&interval={intervalo}&includePrePost=false&events=div%2Csplit")
    r = cli.get(url)
    if r.status != 200:
        raise RuntimeError(f"{simbolo}: HTTP {r.status}")
    res = (r.json().get("chart") or {}).get("result") or []
    if not res:
        raise RuntimeError(f"{simbolo}: resposta vazia do Yahoo")
    return res[0]


def barras(res: dict) -> list[dict]:
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    out = []
    for i, t in enumerate(ts):
        c = (q.get("close") or [None] * len(ts))[i]
        if c is None:
            continue
        out.append({
            "t": datetime.fromtimestamp(t, timezone.utc),
            "abre": (q.get("open") or [None] * len(ts))[i],
            "max": (q.get("high") or [None] * len(ts))[i],
            "min": (q.get("low") or [None] * len(ts))[i],
            "fech": c,
            "vol": (q.get("volume") or [0] * len(ts))[i] or 0,
        })
    return out


def coletar(cli: Cliente, nome: str, dia: date | None, intervalo: str) -> dict:
    """Devolve a fita de um ativo no pregao pedido (ou no ultimo com barras)."""
    s = simbolo_yahoo(nome)
    agora = datetime.now(timezone.utc)
    if dia is None:
        ini, fim = agora - timedelta(days=6), agora + timedelta(hours=1)
    else:
        ini = datetime(dia.year, dia.month, dia.day, tzinfo=BRT) - timedelta(hours=6)
        fim = datetime(dia.year, dia.month, dia.day, tzinfo=BRT) + timedelta(hours=30)
    try:
        intra = barras(baixar(cli, s, ini, fim, intervalo))
    except RuntimeError:
        intra = []
    if not intra:
        raise RuntimeError(f"sem barra intradia de {s} no periodo (feriado, fim de semana, simbolo errado "
                           f"ou fora do limite do Yahoo para {intervalo})")
    diario_res = baixar(cli, s, ini - timedelta(days=45), fim, "1d")
    diario = barras(diario_res)
    meta = diario_res.get("meta") or {}
    # o "dia" e o da bolsa de origem: na B3 e Brasilia; em cambio e futuros (24h) e o fuso da praca
    try:
        fuso = ZoneInfo(meta.get("exchangeTimezoneName") or "America/Sao_Paulo")
    except Exception:
        fuso = BRT
    por_dia: dict[date, list[dict]] = {}
    for b in intra:
        por_dia.setdefault(b["t"].astimezone(fuso).date(), []).append(b)
    alvo = dia if dia in por_dia else (max(por_dia) if dia is None else None)
    if alvo is None:
        raise RuntimeError(f"sem pregao de {s} em {dia.isoformat()} (feriado ou fim de semana)")
    do_dia = por_dia[alvo]
    dias_d = [(b["t"].astimezone(fuso).date(), b) for b in diario]
    anteriores = [b for d, b in dias_d if d < alvo]
    if not anteriores:
        raise RuntimeError(f"sem fechamento de {s} anterior a {alvo.isoformat()}")
    ant = anteriores[-1]["fech"]
    barra_dia = next((b for d, b in dias_d if d == alvo), None)
    vols = [b["vol"] for d, b in dias_d if d < alvo and b["vol"]][-20:]
    media20 = sum(vols) / len(vols) if vols else None
    fech = barra_dia["fech"] if barra_dia else do_dia[-1]["fech"]
    mx = max(b["max"] for b in do_dia if b["max"] is not None)
    mn = min(b["min"] for b in do_dia if b["min"] is not None)
    vol_dia = (barra_dia or {}).get("vol") or sum(b["vol"] for b in do_dia)
    reg = ((meta.get("currentTradingPeriod") or {}).get("regular") or {})
    aberto = bool(reg) and reg.get("start", 0) <= agora.timestamp() < reg.get("end", 0)
    return {
        "nome": nome.upper(), "simbolo": s, "dia": alvo, "moeda": meta.get("currency"),
        "fuso": str(fuso), "continuo": s.endswith("=F"),
        "fech_anterior": ant, "fechamento": fech, "var_dia": (fech / ant - 1) * 100,
        "max": mx, "min": mn,
        "posicao_na_faixa": None if mx == mn else (fech - mn) / (mx - mn) * 100,
        "volume": vol_dia, "volume_sobre_media20": (vol_dia / media20) if media20 and vol_dia else None,
        "em_andamento": dia is None and aberto and alvo == agora.astimezone(fuso).date(),
        "var_abertura": None if do_dia[0]["abre"] is None else (do_dia[0]["abre"] / ant - 1) * 100,
        "fita": [{"hora": b["t"].astimezone(BRT).strftime("%Hh%M"), "preco": b["fech"],
                  "var": (b["fech"] / ant - 1) * 100, "vol": b["vol"]} for b in do_dia],
    }


def tabela(cab: list[str], linhas: list[list[str]]) -> str:
    larg = [max(len(str(x)) for x in col) for col in zip(cab, *linhas)]
    out = ["  ".join(str(c).ljust(larg[i]) if i == 0 else str(c).rjust(larg[i]) for i, c in enumerate(cab))]
    for l in linhas:
        out.append("  ".join(str(c).ljust(larg[i]) if i == 0 else str(c).rjust(larg[i]) for i, c in enumerate(l)))
    return "\n".join(out)


def imprimir(fitas: list[dict], intervalo: str, limiar: float) -> None:
    dia = fitas[0]["dia"]
    print(f"FITA INTRADIA · {DIAS[dia.weekday()]} {dia.strftime('%d/%m/%Y')} · barras de {intervalo} · hora de Brasilia")
    print("Fonte: Yahoo Finance (B3 com atraso de ~15 min). Variacao contra o fechamento do pregao anterior.")
    print("Cada linha e uma barra: a hora e o INICIO da barra e o numero e o preco no FIM dela.")
    if fitas[0]["em_andamento"]:
        print("PREGAO EM ANDAMENTO: a ultima linha e parcial, nao e fechamento.")
    for f in fitas:
        if f["dia"] != dia:
            print(f"ATENCAO: {f['nome']} tem o ultimo pregao em {f['dia'].strftime('%d/%m')}, nao em {dia.strftime('%d/%m')} (outro mercado ou feriado).")
        if f["continuo"]:
            print(f"ATENCAO: {f['nome']} ({f['simbolo']}) e contrato continuo. Perto do vencimento a variacao mistura a troca "
                  "de contrato e NAO vale como movimento do dia: confira com `python3 -m livro.portao`.")
        elif f["fuso"] != "America/Sao_Paulo":
            print(f"Nota: o dia de {f['nome']} e contado no fuso da praca de origem ({f['fuso']}); as horas abaixo sao de Brasilia.")
    print()
    # as linhas sao as horas da referencia (o primeiro ativo): mercado 24h nao estica a tabela
    horas = sorted({b["hora"] for b in fitas[0]["fita"]})
    mapa = [{b["hora"]: b for b in f["fita"]} for f in fitas]
    linhas = [["abertura"] + [pct(f["var_abertura"]) for f in fitas]]
    linhas += [[h] + [pct(m[h]["var"]) if h in m else "-" for m in mapa] for h in horas]
    rot = "parcial" if fitas[0]["em_andamento"] else "fecham."
    linhas.append([rot] + [pct(f["var_dia"]) for f in fitas])
    print(tabela(["hora"] + [f["nome"] for f in fitas], linhas))
    print()
    print(tabela(["resumo"] + [f["nome"] for f in fitas], [
        ["fech. anterior"] + [num(f["fech_anterior"]) for f in fitas],
        ["ultimo"] + [num(f["fechamento"]) for f in fitas],
        ["minima do dia"] + [num(f["min"]) for f in fitas],
        ["maxima do dia"] + [num(f["max"]) for f in fitas],
        ["posicao na faixa"] + ["-" if f["posicao_na_faixa"] is None else f"{f['posicao_na_faixa']:.0f}%" for f in fitas],
        ["volume / media 20d"] + ["-" if f["volume_sobre_media20"] is None else num(f["volume_sobre_media20"], 1) + "x" for f in fitas],
    ]))
    print("posicao na faixa: 0% = fechou na minima do dia, 100% = fechou na maxima.")
    if len(fitas) > 1:
        ref, m0 = fitas[0], mapa[0]
        print()
        print(f"DIFERENCA DE {ref['nome']} CONTRA CADA UM (pontos percentuais; negativo = {ref['nome']} pior)")
        dl = []
        for h in horas:
            if h not in m0:
                continue
            dl.append([h] + [pct(m0[h]["var"] - m[h]["var"]).replace("%", " pp") if h in m else "-" for m in mapa[1:]])
        dl.append([rot] + [pct(ref["var_dia"] - f["var_dia"]).replace("%", " pp") for f in fitas[1:]])
        print(tabela(["hora"] + [f["nome"] for f in fitas[1:]], dl))
        for f, m in zip(fitas[1:], mapa[1:]):
            comuns = [h for h in horas if h in m0 and h in m]
            dif = [(h, m0[h]["var"] - m[h]["var"]) for h in comuns]
            final = ref["var_dia"] - f["var_dia"]
            if abs(final) < limiar:
                print(f"- {ref['nome']} x {f['nome']}: sem divergencia no fim do dia ({pct(final).replace('%', ' pp')}).")
                continue
            # a divergencia "abre" na primeira hora a partir da qual ela fica do lado final e acima do limiar ate o fim
            abre = None
            for i in range(len(dif) - 1, -1, -1):
                if abs(dif[i][1]) >= limiar and (dif[i][1] > 0) == (final > 0):
                    abre = dif[i][0]
                else:
                    break
            antes = "desde a abertura" if abre == (dif[0][0] if dif else None) else f"a partir das {abre}" if abre else "so no leilao de fechamento"
            print(f"- {ref['nome']} x {f['nome']}: divergencia de {pct(final).replace('%', ' pp')} no fim do dia, aberta {antes}.")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="+", help="tickers da B3, simbolos do Yahoo ou ids do livro; o primeiro e a referencia")
    ap.add_argument("--dia", help="AAAA-MM-DD (padrao: ultimo pregao com barras)")
    ap.add_argument("--intervalo", default="60m", choices=INTERVALOS)
    ap.add_argument("--limiar", type=float, default=1.0, help="pontos percentuais para chamar de divergencia (padrao 1,0)")
    ap.add_argument("--json", action="store_true", help="saida em JSON")
    a = ap.parse_args(argv[1:])
    dia = date.fromisoformat(a.dia) if a.dia else None
    cli = Cliente()
    fitas, falhas = [], []
    for tk in a.tickers:
        try:
            fitas.append(coletar(cli, tk, dia, a.intervalo))
        except Exception as e:
            falhas.append(f"{tk.upper()}: {e}")
    for f in falhas:
        print(f"LACUNA: {f}", file=sys.stderr if a.json else sys.stdout)
    if not fitas:
        return 1
    if a.json:
        print(json.dumps([{**f, "dia": f["dia"].isoformat()} for f in fitas], ensure_ascii=False, indent=1))
    else:
        imprimir(fitas, a.intervalo, a.limiar)
    return 0 if not falhas else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

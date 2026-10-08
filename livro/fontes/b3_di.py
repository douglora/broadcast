"""DI futuro (DI1F28..F35): taxa de ajuste diaria oficial da B3, do arquivo
TradeInformationConsolidated do Boletim Diario do Mercado.

    GET https://arquivos.b3.com.br/api/download/requestname?fileName=TradeInformationConsolidated&date=YYYY-MM-DD
        -> {"token": "..."}
    GET https://arquivos.b3.com.br/api/download/?token=<token>
        -> CSV ';' (1a linha 'Status do Arquivo: ...' e pulada). Colunas: RptDt;TckrSymb;ISIN;
           SgmtNm;MinPric;MaxPric;TradAvrgPric;LastPric;OscnPctg;AdjstdQt;AdjstdQtTax;RefPric;...
           AdjstdQt = PU de ajuste; AdjstdQtTax = taxa de ajuste (% a.a.).

Dia sem pregao devolve HTTP 400. Historico disponivel desde 2021. Os endpoints
ASP antigos (ajustes do pregao, taxas referenciais) morreram em 2025/26.
Conversao PU -> taxa como conferencia: (100000/PU)^(252/du) - 1."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from livro import relogios
from livro.http import Cliente, HttpError

TOKEN_URL = "https://arquivos.b3.com.br/api/download/requestname"
DOWNLOAD_URL = "https://arquivos.b3.com.br/api/download/"


def _num(s: str) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)
    except ValueError:
        return None


def parse_csv(texto: str, codigos: list[str]) -> dict:
    """-> {codigo: {taxa, pu, ultimo, data}} so para os vertices pedidos."""
    linhas = texto.splitlines()
    inicio = 0
    for i, l in enumerate(linhas[:5]):
        if l.lower().startswith("rptdt") or "TckrSymb" in l:
            inicio = i
            break
    leitor = csv.DictReader(io.StringIO("\n".join(linhas[inicio:])), delimiter=";")
    alvo = set(codigos)
    out = {}
    for row in leitor:
        tk = (row.get("TckrSymb") or "").strip()
        if tk not in alvo:
            continue
        out[tk] = {
            "data": (row.get("RptDt") or "").strip()[:10],
            "taxa": _num(row.get("AdjstdQtTax")),
            "pu": _num(row.get("AdjstdQt")),
            "ultimo": _num(row.get("LastPric")),
            "negocios": _num(row.get("TradQty")),
        }
    return out


def taxa_de_pu(pu: float, du: int) -> float | None:
    if not pu or du <= 0:
        return None
    return ((100000.0 / pu) ** (252.0 / du) - 1.0) * 100.0


def baixar_dia(cli: Cliente, d: date, codigos: list[str]) -> dict:
    r = cli.get(TOKEN_URL, params={"fileName": "TradeInformationConsolidated", "date": d.isoformat()}, timeout=40)
    if r.status != 200:
        raise HttpError(r.status, r.text, TOKEN_URL)
    token = (r.json() or {}).get("token")
    if not token:
        raise ValueError("B3 nao devolveu token")
    r2 = cli.get(DOWNLOAD_URL, params={"token": token}, timeout=120)
    if r2.status != 200:
        raise HttpError(r2.status, r2.text, DOWNLOAD_URL)
    texto = r2.content.decode("utf-8-sig", errors="replace")
    if texto.count(";") < 5:
        texto = r2.content.decode("latin-1", errors="replace")
    dados = parse_csv(texto, codigos)
    if not dados:
        raise ValueError("arquivo sem os vertices do livro")
    return dados


def coletar(historico: dict | None, codigos: list[str], cli: Cliente | None = None,
            hoje: date | None = None, dias_backfill: int = 10, max_tentativas: int = 40) -> dict:
    """Atualiza o historico {codigo: [[data, taxa, pu], ...]} andando para tras a partir
    do ultimo pregao B3 ate cobrir `dias_backfill` datas novas (ou esgotar tentativas)."""
    cli = cli or Cliente()
    hoje = hoje or relogios.data_pregao_b3()
    hist = {c: list((historico or {}).get(c) or []) for c in codigos}
    conhecidas = set()
    for c in codigos:
        conhecidas |= {h[0] for h in hist[c]}
    falhas, novas, d, tentativas = [], 0, hoje, 0
    while novas < dias_backfill and tentativas < max_tentativas:
        d = relogios.ultimo_dia_util("B3", d)
        if d.isoformat() not in conhecidas:
            tentativas += 1
            try:
                dia = baixar_dia(cli, d, codigos)
                for c in codigos:
                    v = dia.get(c)
                    if v and v.get("taxa") is not None:
                        hist[c].append([d.isoformat(), v["taxa"], v.get("pu")])
                novas += 1
            except HttpError as e:
                falhas.append(f"{d}: HTTP {e.status}")
                if e.status == 400 and d == hoje:
                    pass  # ainda nao publicado hoje: segue para tras
            except Exception as e:
                falhas.append(f"{d}: {type(e).__name__}: {str(e)[:60]}")
        d = d - timedelta(days=1)
    for c in codigos:
        vistos = {h[0]: h for h in hist[c]}
        hist[c] = [vistos[k] for k in sorted(vistos)][-600:]
    ultimas = [hist[c][-1][0] for c in codigos if hist[c]]
    return {"fonte": "B3 Boletim Diario (TradeInformationConsolidated)", "historico": hist,
            "ultimo_pregao": max(ultimas) if ultimas else None, "pregao_referencia": hoje.isoformat(),
            "cobertura": {c: len(hist[c]) for c in codigos}, "falhas": falhas[-20:],
            "coletado_em": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}

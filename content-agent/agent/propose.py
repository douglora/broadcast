"""Propositor de pautas (Gate 1): lê um snapshot e sugere ângulos de post.

Tudo aqui é determinístico (sem LLM): heurísticas sobre os dados. O objetivo é
te entregar 5-6 ângulos com os números de suporte para você escolher um.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# Universo B3 acompanhado (nome -> ticker), extraído do index.html / watchlist.
B3_UNIVERSE = {
    "petrobras": "PETR4", "vale": "VALE3", "itau": "ITUB4", "bradesco": "BBDC4",
    "banco do brasil": "BBAS3", "ambev": "ABEV3", "weg": "WEGE3", "b3": "B3SA3",
    "btg": "BPAC11", "magazine": "MGLU3", "localiza": "RENT3", "suzano": "SUZB3",
    "sabesp": "SBSP3", "copel": "CPLE3", "sanepar": "SAPR11", "equatorial": "EQTL3",
    "prio": "PRIO3", "brava": "BRAV3", "cosan": "CSAN3", "energisa": "ENGI11",
    "totvs": "TOTS3", "raia": "RADL3", "hapvida": "HAPV3", "vibra": "VBBR3",
    "eneva": "ENEV3", "multiplan": "MULT3", "iguatemi": "IGTI11", "taesa": "TAEE11",
    "alupar": "ALUP11", "itausa": "ITSA4", "vivo": "VIVT3", "tim": "TIMS3",
    "gerdau": "GGBR4", "usiminas": "USIM5", "csn": "CSNA3", "klabin": "KLBN11",
    "ultrapar": "UGPA3", "raizen": "RAIZ4",
}
TICKERS = set(B3_UNIVERSE.values())

_CHG_KEYS = ("chg_pct", "change_pct", "changePercent", "pct", "variation", "var", "chg", "change")
_PRICE_KEYS = ("price", "last", "close", "value", "px")


def _num(d, keys) -> float | None:
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _unwrap(node, key):
    """Aceita tanto {"key": <x>} quanto <x> direto (shapes do backend variam)."""
    if isinstance(node, dict) and key in node:
        return node[key]
    return node


@dataclass
class Pauta:
    id: str
    pillar: str  # macro | us | br | micro | fato
    title: str
    angle: str
    data: dict = field(default_factory=dict)
    score: float = 0.0
    source: str = ""

    def to_dict(self):
        return asdict(self)


def _quotes_map(snap: dict) -> dict:
    inner = _unwrap(snap.get("quotes") or {}, "quotes")
    return inner if isinstance(inner, dict) else {}


def propose_pautas(snap: dict, limit: int = 6) -> list[Pauta]:
    pautas: list[Pauta] = []
    quotes = _quotes_map(snap)

    # 1) Fatos relevantes (CVM) — combustível renovável, prioridade máxima.
    alert_list = _unwrap(snap.get("alerts") or {}, "alerts") or []
    for a in alert_list:
        if not isinstance(a, dict):
            continue
        comp = a.get("company") or a.get("empresa") or "Empresa"
        typ = a.get("type") or a.get("tipo") or "Fato relevante"
        pautas.append(Pauta(
            id="", pillar="fato",
            title=f"Fato relevante: {comp} — {typ}",
            angle=(f"Pegar o fato relevante de {comp} ({typ}) e explicar o que "
                   f"significa para quem acompanha a ação. Micro → macro."),
            data={"company": comp, "type": typ},
            score=9.0, source=f"alert:{comp}:{typ}",
        ))

    # 2) Maiores movimentos do universo acompanhado.
    movers = []
    for tk, qd in quotes.items():
        if tk not in TICKERS or not isinstance(qd, dict):
            continue
        chg = _num(qd, _CHG_KEYS)
        if chg is None:
            continue
        movers.append((abs(chg), tk, chg, qd))
    movers.sort(reverse=True)
    for _, tk, chg, qd in movers[:2]:
        name = qd.get("name") or tk
        pautas.append(Pauta(
            id="", pillar="micro",
            title=f"{tk} {'+' if chg >= 0 else ''}{chg:.1f}% — {name}",
            angle=(f"Comentar o movimento de {name} ({tk}) e ancorar no cenário "
                   f"(setor, juro, câmbio). Contexto, não recomendação."),
            data={"ticker": tk, "price": _num(qd, _PRICE_KEYS),
                  "chg_pct": round(chg, 2), "name": name},
            score=6.0 + min(abs(chg), 6.0) / 2, source=f"mover:{tk}",
        ))

    # 3) Macro BR — curva DI + indicadores + resumo semanal.
    di_list = _unwrap(snap.get("di") or {}, "di")
    ind = _unwrap(snap.get("indicators") or {}, "indicators")
    if di_list:
        pautas.append(Pauta(
            id="", pillar="macro",
            title="Curva DI / juro no Brasil",
            angle=("Ler a curva DI (curto vs longo) e o que ela embute sobre "
                   "Selic/inflação. Conectar a 1 setor ou ação sensível a juro."),
            data={"di": di_list, "indicators": ind,
                  "weekly_br": (snap.get("weekly_summary") or {}).get("br", [])[:3]},
            score=5.5, source="macro:di",
        ))

    # 4) EUA / commodities.
    us_hits = {tk: quotes[tk] for tk in ("CL=F", "BZ=F", "^GSPC", "^IXIC", "^DJI") if tk in quotes}
    if us_hits:
        pautas.append(Pauta(
            id="", pillar="us",
            title="EUA / commodities",
            angle=("Comentar índices americanos ou petróleo (WTI/Brent) e o "
                   "reflexo no Brasil (câmbio, Petrobras, exportadoras)."),
            data={"quotes": us_hits,
                  "weekly_us": (snap.get("weekly_summary") or {}).get("us", [])[:3]},
            score=4.5, source="us:commodities",
        ))

    # Ordenação determinística e atribuição de ids estáveis.
    pautas.sort(key=lambda p: (-p.score, p.source, p.title))
    for i, p in enumerate(pautas, 1):
        p.id = f"p{i}"
    return pautas[:limit]


def find_pauta(snap: dict, pauta_id: str) -> Pauta | None:
    for p in propose_pautas(snap):
        if p.id == pauta_id:
            return p
    return None


def render_brief(pautas: list[Pauta]) -> str:
    lines = ["# Pautas sugeridas (Gate 1 — escolha uma)\n"]
    for p in pautas:
        lines.append(f"## {p.id} · [{p.pillar.upper()}] {p.title}  (score {p.score:.1f})")
        lines.append(p.angle)
        if p.data:
            blob = json.dumps(p.data, ensure_ascii=False)
            if len(blob) > 600:
                blob = blob[:600] + "…"
            lines.append(f"`dados:` {blob}")
        lines.append("")
    lines.append("Para rascunhar:  python -m agent.cli draft --pauta <id>")
    return "\n".join(lines)

"""Eventos dos proximos dias: resultados, proventos, assembleias, vencimento de opcoes e a agenda economica."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from . import _leitor as L
from . import _secoes as S


class Eventos(list):
    """Lista de eventos (dicts), do mais proximo para o mais distante. `.avisos` diz o que faltou (arquivo velho ou ausente)."""

    def __init__(self, itens: Iterable[dict] = (), avisos: Iterable[str] = ()):
        super().__init__(itens)
        self.avisos: list[str] = list(avisos)


def _titulo(x: dict) -> str:
    nome = x.get("empresa") or x.get("ticker") or ""
    tipo = x.get("tipo")
    if tipo == "resultado":
        return f"Resultado {x.get('periodo') or ''} - {nome}".replace("  ", " ").strip()
    if tipo == "teleconferencia":
        return f"Teleconferencia {x.get('periodo') or ''} - {nome}".replace("  ", " ").strip()
    if tipo == "provento_ex":
        return f"Data ex de provento - {nome}"
    if tipo == "assembleia":
        return f"Assembleia - {nome}"
    if tipo == "vencimento_opcoes":
        return f"Vencimento de opcoes - {x.get('periodo') or ''}".strip()
    return f"{tipo} - {nome}"


def montar(dias: int, ctx: S.Ctx, *, tipos: Iterable[str] | None = None, pais: str | None = None,
           tickers: Iterable[str] | None = None) -> Eventos:
    hoje = ctx.hoje
    ate = hoje + timedelta(days=int(dias))
    de_s, ate_s = hoje.isoformat(), ate.isoformat()
    quer_tipos = set(tipos) if tipos else None
    quer_tickers = {t.upper() for t in tickers} if tickers else None
    saida: list[dict] = []
    avisos: list[str] = []

    ev = L.ler("pagina/eventos.json")
    if not isinstance(ev, dict):
        avisos.append("calendario de empresas (cache/out/pagina/eventos.json) ausente")
    else:
        mot = S._velho("eventos", ev.get("gerado"), ctx, "o calendario de empresas")
        if mot:
            avisos.append(mot + ": eventos de empresas descartados")
        else:
            for x in ev.get("itens") or []:
                d = x.get("data")
                if not d or d < de_s or d > ate_s:
                    continue
                tks = list(x.get("tickers") or ([x["ticker"]] if x.get("ticker") else []))
                if quer_tickers and not (quer_tickers & set(tks)):
                    continue
                saida.append({
                    "data": d, "hora": x.get("hora"), "dias_ate": (date.fromisoformat(d) - hoje).days, "tipo": x.get("tipo"),
                    "ticker": x.get("ticker"), "tickers": tks, "empresa": x.get("empresa"), "pais": x.get("pais"),
                    "titulo": _titulo(x), "periodo": x.get("periodo"), "confirmado": x.get("confirmado"), "relevancia": None,
                    "expectativa": None, "anterior": None, "efetivo": None, "unidade": None, "indices": x.get("indices") or [],
                    "fonte": x.get("fonte"), "detalhe": x.get("det")})

    ag = L.ler("pagina/agenda.json")
    if not isinstance(ag, dict):
        avisos.append("agenda economica (cache/out/pagina/agenda.json) ausente")
    elif not quer_tickers:
        mot = S._velho("agenda", ag.get("gerado"), ctx, "a agenda economica")
        if mot:
            avisos.append(mot + ": agenda macro descartada")
        else:
            for x in ag.get("eventos") or []:
                d = x.get("dia")
                if not d or d < de_s or d > ate_s:
                    continue
                saida.append({
                    "data": d, "hora": x.get("hora"), "dias_ate": (date.fromisoformat(d) - hoje).days, "tipo": "macro", "ticker": None,
                    "tickers": [], "empresa": None, "pais": x.get("pais"), "titulo": x.get("evento"), "periodo": x.get("periodo"),
                    "confirmado": True, "relevancia": x.get("relevancia"), "expectativa": L.num(x.get("expectativa")),
                    "anterior": L.num(x.get("anterior")), "efetivo": L.num(x.get("efetivo")), "unidade": x.get("unidade"), "indices": [],
                    "fonte": x.get("fonte"), "detalhe": x.get("indicador")})
    if quer_tipos:
        saida = [e for e in saida if e["tipo"] in quer_tipos]
    if pais:
        saida = [e for e in saida if (e.get("pais") or "").upper() == pais.upper()]
    saida.sort(key=lambda e: (e["data"], e["hora"] or "99:99", e["tipo"], e["ticker"] or ""))
    return Eventos(saida, avisos)

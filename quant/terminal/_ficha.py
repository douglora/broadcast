"""Monta a ficha de um ticker: identidade + os pedacos de `_secoes`, cada um com fonte, data e idade, ou None com o motivo."""
from __future__ import annotations

from typing import Any

from . import _leitor as L
from . import _secoes as S

ORDEM = tuple(S.SECOES)          # tir, consenso, insiders, aluguel, noticias, proximo_resultado, multiplos, valuation, divida, opcoes, fundos, pares


def disponivel() -> bool:
    """True se o terminal esta no disco e tem o cadastro de ativos (cache/out/universo.json) para consultar."""
    return L.raiz().is_dir() and (L.saida() / "universo.json").is_file()


def montar(ticker: str, ctx: S.Ctx) -> dict[str, Any]:
    t = (ticker or "").strip().upper()
    out: dict[str, Any] = {"ticker": t, "hoje": ctx.hoje.isoformat(), "terminal": str(L.raiz()), "disponivel": disponivel(),
                           "nome": None, "classe": None, "setor": None, "subsetor": None, "indices": [], "moeda": None}
    motivos: dict[str, str] = {}
    if not out["disponivel"]:
        for k in ORDEM:
            out[k] = None
            motivos[k] = f"terminal nao encontrado em {L.raiz()} (variavel {L.ENV_TERMINAL}) ou sem cache/out/universo.json"
        out.update({"motivos": motivos, "avisos": [], "cobertura": {"com_dado": 0, "total": len(ORDEM)}})
        return out
    ident = S.identidade(ctx, t)
    if ident:
        out.update({k: ident[k] for k in ("nome", "classe", "setor", "subsetor", "indices", "moeda")})
        out["isin"] = ident.get("isin")
    else:
        motivos["identidade"] = f"{t} nao esta no universo do terminal (cache/out/universo.json)"
    avisos: list[str] = []
    for nome in ORDEM:
        try:
            val, mot = S.SECOES[nome](ctx, t)
        except Exception as ex:                      # arquivo com formato inesperado nao pode derrubar o robo
            val, mot = None, f"erro ao ler este pedaco ({type(ex).__name__}: {ex}); formato inesperado no arquivo do terminal"
        out[nome] = val
        if val is None:
            motivos[nome] = mot or "sem dado"
        else:
            avisos += [f"{nome}: {a}" for a in val.get("avisos") or []]
    com = sum(1 for k in ORDEM if out.get(k) is not None)
    out.update({"motivos": motivos, "avisos": avisos, "cobertura": {"com_dado": com, "total": len(ORDEM)}})
    return out

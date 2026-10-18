"""A TIR que o robo usa: so a do metodo do Safra, sempre recalculada antes de usar.

Pedido do Douglas em 18/10/2026: "o robo nao pode usar antiga, sempre tem que ser TIR atualizada". Vale desde o pregao de 19/10/2026:
  1. A TIR antiga do terminal (cache/out/pagina/tir.json) nao e lida. Papel sem a TIR nova e papel SEM TIR, com o motivo.
  2. Antes de ler, o robo roda o recalculo do proprio terminal com o preco mais novo que ele tem (`python -m coletor.tir_safra` na pasta do
     terminal, sem rede, cerca de 2 s; regrava cache/out/pagina/tir_safra.json e web/d/x/tir_safra.json). E a unica coisa que o leitor dispara
     no terminal.
  3. Depois confere o `gerado` do arquivo: com mais de 36 horas, ou de antes do fim do ultimo pregao encerrado (18h), o arquivo e velho.
  4. Recalculo que falha ou arquivo velho: o robo NAO usa TIR nenhuma naquele dia. A recusa vai para o log e para
     quant/saida/terminal/tir_checagens.jsonl (uma linha por conferencia; a revisao do pregao le dali), e o resto do dia segue sem TIR,
     mesmo que um recalculo mais tarde de certo. No dia seguinte tudo recomeca.
  5. Por papel: o preco da conta tem de ser do ultimo pregao encerrado ou mais novo; senao o papel fica sem TIR, com o motivo.
Num mesmo processo uma conferencia vale 10 minutos: uma tabela de 369 papeis faz um recalculo so.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import date, datetime, time as dtime
from typing import Any

from quant.comum import DIR_SAIDA, log
from quant.dados import calendario

from . import _leitor as L

ARQ = "pagina/tir_safra.json"
LIMITE_HORAS = 36
FIM_PREGAO = dtime(18, 0)
VALIDADE_S = 600
TEMPO_MAX_S = 120
ARQ_CHECAGENS = os.path.join(DIR_SAIDA, "terminal", "tir_checagens.jsonl")
_MEMO: dict[tuple[str, str], dict[str, Any]] = {}


def limpar() -> None:
    _MEMO.clear()


def recalcular() -> str | None:
    """Roda o recalculo da TIR no terminal. None se deu certo; senao, o motivo da falha (nunca levanta)."""
    raiz = L.raiz()
    py = raiz / ".venv" / "bin" / "python"
    if not py.exists():
        return f"o Python do terminal ({py}) nao existe"
    try:
        r = subprocess.run([str(py), "-m", "coletor.tir_safra"], cwd=str(raiz), capture_output=True, text=True, timeout=TEMPO_MAX_S)
    except subprocess.TimeoutExpired:
        return f"o recalculo passou de {TEMPO_MAX_S} s"
    except OSError as e:
        return f"o recalculo nao rodou ({type(e).__name__}: {e})"
    if r.returncode != 0:
        linhas = (r.stderr or "").strip().splitlines() or (r.stdout or "").strip().splitlines()
        return f"o recalculo saiu com codigo {r.returncode}" + (f": {linhas[-1][:200]}" if linhas else "")
    return None


def ultimo_pregao_encerrado(agora: datetime) -> date:
    d = agora.date()
    return d if calendario.eh_pregao(d) and agora.time() >= FIM_PREGAO else calendario.pregao_anterior(d)


def _quando(x: Any) -> datetime | None:
    try:
        g = datetime.fromisoformat(str(x))
    except ValueError:
        return None
    return g if g.tzinfo else g.replace(tzinfo=L.FUSO_BRT)


def motivo_arquivo(d: Any, agora: datetime) -> str | None:
    """Por que o arquivo inteiro nao vale; None se vale."""
    if not isinstance(d, dict) or not d.get("empresas"):
        return "arquivo da TIR nova (cache/out/pagina/tir_safra.json) ausente ou vazio"
    g = _quando(d.get("gerado"))
    if g is None:
        return "o arquivo da TIR nova nao diz quando foi gerado (campo gerado)"
    horas = (agora - g).total_seconds() / 3600
    if horas > LIMITE_HORAS:
        return f"a TIR nova foi gerada em {g:%d/%m %H:%M} ({horas:.0f} h atras), acima do limite de {LIMITE_HORAS} h"
    up = ultimo_pregao_encerrado(agora)
    if g < datetime.combine(up, FIM_PREGAO, L.FUSO_BRT):
        return f"a TIR nova foi gerada em {g:%d/%m %H:%M}, antes do fim do ultimo pregao encerrado ({up:%d/%m}, 18h)"
    return None


def motivo_papel(t: str, e: Any, agora: datetime) -> str | None:
    """Por que o numero de um papel nao vale; None se vale."""
    if not isinstance(e, dict) or L.num(e.get("tir")) is None:
        return f"a TIR nova nao traz numero para {t}"
    p = L.como_data(e.get("preco_data"))
    if p is None:
        return f"a TIR nova de {t} nao diz de quando e o preco"
    up = ultimo_pregao_encerrado(agora)
    if p < up:
        return f"o preco da TIR nova de {t} e de {p:%d/%m}, antes do ultimo pregao encerrado ({up:%d/%m})"
    return None


def _ler_checagens(arq: str) -> list[dict]:
    try:
        with open(arq, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []


def _anotar(arq: str, linha: dict) -> None:
    try:
        os.makedirs(os.path.dirname(arq), exist_ok=True)
        with open(arq, "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError as e:
        log(f"TIR: nao consegui anotar a conferencia em {arq} ({type(e).__name__}: {e})")


def estado(agora: datetime | None = None) -> dict[str, Any]:
    """A TIR do dia, conferida: {ok, motivo, gerado, ultimo_pregao, conferido_em, dados}. `dados` e o JSON lido logo depois do recalculo
    (None quando `ok` e False). Roda o recalculo, no maximo uma vez a cada 10 minutos por processo, e anota cada conferencia."""
    agora = agora or L.agora()
    dia = agora.date().isoformat()
    chave = (str(L.raiz()), dia)
    m = _MEMO.get(chave)
    if m is not None and abs((agora - m["_agora"]).total_seconds()) < VALIDADE_S:      # pela hora da consulta (os testes andam o relogio)
        return m
    arq = ARQ_CHECAGENS
    out = {"ok": False, "motivo": None, "gerado": None, "ultimo_pregao": ultimo_pregao_encerrado(agora).isoformat(),
           "conferido_em": agora.isoformat(timespec="seconds"), "dados": None}
    antes = next((x for x in _ler_checagens(arq) if x.get("dia") == dia and not x.get("ok")), None)
    if antes is not None:
        out["motivo"] = f"a TIR foi recusada hoje as {antes.get('hora')} ({antes.get('motivo')}); o robo nao usa TIR no resto do dia"
    else:
        t0 = time.monotonic()
        falha = recalcular()
        d = None if falha else L.ler(ARQ, memo=False)
        motivo = f"o recalculo da TIR no terminal falhou: {falha}" if falha else motivo_arquivo(d, agora)
        out.update({"ok": motivo is None, "motivo": motivo, "gerado": d.get("gerado") if isinstance(d, dict) else None,
                    "dados": d if motivo is None else None})
        _anotar(arq, {"dia": dia, "hora": agora.strftime("%H:%M:%S"), "ok": out["ok"], "motivo": motivo, "gerado": out["gerado"],
                      "segundos": round(time.monotonic() - t0, 1), "empresas": len(d.get("empresas") or {}) if isinstance(d, dict) else 0})
        if motivo:
            log(f"TIR RECUSADA em {agora:%d/%m %H:%M}: {motivo}. O robo nao usa TIR nenhuma hoje.")
    out["_agora"] = agora
    _MEMO[chave] = out
    return out


def sem_tir(est: dict[str, Any], agora: datetime) -> dict[str, str]:
    """Os papeis que o arquivo da TIR nova conhece e que ficaram sem TIR, com o motivo (os de fora da conta e os recusados um a um)."""
    d = est.get("dados") or {}
    out = {str(x.get("t")): f"fora da TIR nova: {x.get('motivo')}" for x in d.get("fora") or [] if isinstance(x, dict) and x.get("t")}
    for t, e in (d.get("empresas") or {}).items():
        m = motivo_papel(t, e, agora)
        if m:
            out[t] = m
    return dict(sorted(out.items()))

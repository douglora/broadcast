"""Portao de qualidade do lado da SESSAO: le as series do branch dados e roda a
mesma avaliacao do runner (livro/qualidade.py) antes de a sessao escrever um numero.

Uso na sessao (skill livro, regra R0):
    python3 -m livro.portao                    # drivers + todo ativo com problema
    python3 -m livro.portao BRENT USDBRL CURY3 # so estes
    python3 -m livro.portao --ref 1cc16f1 BRENT

Imprime uma linha por serie: ok / suspeito / nao_confirmado, a data da ultima barra
e o motivo em portugues. Serie que nao sai "ok" nao pode entrar na tese, no push
nem numa frase causal da Leitura da Mesa (SKILL.md, R1 a R4)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone

from livro import qualidade as qa
from livro import relogios
from livro import universo as uni
from livro.fontes import futuros, yahoo


def _show(ref: str, caminho: str) -> dict | None:
    r = subprocess.run(["git", "show", f"{ref}:{caminho}"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return json.loads(r.stdout)


def _redatar(barras: list[list]) -> list[list]:
    """Duas barras com a mesma data: a 2a e a sessao seguinte (o parser novo ja faz isso
    na coleta; aqui cobre arquivo gravado antes da correcao)."""
    out = []
    for b in barras:
        if out and out[-1][0] == b[0]:
            b = [yahoo._proximo_dia_util(b[0]), *b[1:]]
        out.append(b)
    return out


def avaliar_ref(ids: list[str], ref: str = "origin/dados", agora: datetime | None = None) -> list[tuple]:
    u = uni.carregar()
    agora = agora or datetime.now(timezone.utc)
    info = (_show(ref, "livro/saida/fechamento.json") or {}).get("series_info") or {}
    todos = ids or [a.id for a in u.ativos]
    out = []
    for id_ in todos:
        obj = u.por_id(id_) or u.bench(id_)
        if obj is None:
            out.append((id_, "?", None, ["id desconhecido"]))
            continue
        simbolo = obj.yahoo
        if getattr(obj, "param", lambda *a: None)("contrato_explicito") == "brent":
            # o runner usa o contrato do 1o vencimento (livro/fontes/futuros.py): avaliar o mesmo
            cod = futuros.contrato_vigente(relogios.brt(agora).date())
            if _show(ref, f"livro/series/{uni.nome_seguro(futuros.simbolo_brent(cod))}.json"):
                simbolo = futuros.simbolo_brent(cod)
        d = _show(ref, f"livro/series/{uni.nome_seguro(simbolo)}.json")
        if d and simbolo != obj.yahoo:
            d = {**d, "barras": _redatar(d.get("barras") or [])}
        if not d:
            out.append((id_, "ausente", None, ["sem série no branch"]))
            continue
        mercado = obj.mercado
        ate = relogios.data_referencia(mercado, agora)
        barras = qa.limpar_fim_de_semana(d.get("barras") or [], mercado)
        f17 = d.get("fechamentos_17h") or {}
        defasado = int(getattr(obj, "param", lambda *a: 0)("defasagem_pregoes", 0) or 0) > 0
        if defasado:
            ate = relogios.dia_util_anterior(mercado, ate)
        v = qa.avaliar({**d, "barras": barras}, simbolo, mercado, getattr(obj, "classe", ""), agora, ate,
                       confirmadas={k: x[1] for k, x in f17.items()})
        motivos = list(v.motivos)
        i = info.get(id_) or {}
        if i.get("contrato"):
            motivos.append(f"contrato: {i['contrato']}")
        if simbolo != obj.yahoo:
            motivos.append(f"avaliado no contrato {simbolo}")
        if v.data_barra and v.data_barra < ate.isoformat():
            motivos.append(f"última barra {v.data_barra}, esperado {ate.isoformat()}")
        status = v.status if not (v.dia_pregoes > 1 or v.parcial) else f"{v.status} (dia não é um pregão)"
        out.append((id_, status, v.data_barra, motivos))
    return out


def main(argv: list[str]) -> int:
    ref = "origin/dados"
    if "--ref" in argv:
        k = argv.index("--ref")
        ref = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    ids = argv or list(qa.DRIVERS)
    linhas = avaliar_ref(ids, ref)
    ruins = 0
    for id_, status, data, motivos in linhas:
        if not argv and status == qa.OK and not motivos:
            continue
        ruins += status != qa.OK
        print(f"{id_:8} {status:28} {data or '-':10}  " + ("; ".join(motivos) if motivos else "ok"))
    if not argv:
        print(f"-- {len(linhas)} drivers avaliados; {ruins} fora de ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

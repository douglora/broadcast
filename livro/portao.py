"""Portao de qualidade do lado da SESSAO: le as series do branch dados e roda a
mesma avaliacao do runner (livro/qualidade.py) antes de a sessao escrever um numero.

Uso na sessao (skill livro, regra R0):
    python3 -m livro.portao                    # os drivers (Brent, dolar, DXY, minerio, IBOV, SPX, VIX, BTC)
    python3 -m livro.portao --todos            # o universo inteiro, so o que nao esta ok
    python3 -m livro.portao BRENT USDBRL CURY3 # so estes
    python3 -m livro.portao --ref 1cc16f1 BRENT
    python3 -m livro.portao --modo intradia    # forca o corte do intradia (padrao: o slot do manifest)

Imprime uma linha por serie: ok / suspeito / nao_confirmado, a data da ultima barra
e o motivo em portugues. Serie que nao sai "ok" nao pode entrar na tese, no push
nem numa frase causal da Leitura da Mesa (SKILL.md, R1 a R4)."""

from __future__ import annotations

import json
import re
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


def avaliar_ref(ids: list[str], ref: str = "origin/dados", agora: datetime | None = None,
                modo: str | None = None) -> list[tuple]:
    u = uni.carregar()
    agora = agora or datetime.now(timezone.utc)
    info = (_show(ref, "livro/saida/fechamento.json") or {}).get("series_info") or {}
    modo = modo or ((_show(ref, "livro/saida/manifest.json") or {}).get("slot") or "fechamento")
    todos = ids or [a.id for a in u.ativos]
    out = []
    for id_ in todos:
        obj = u.por_id(id_) or u.bench(id_)
        if obj is None:
            out.append((id_, "?", None, ["id desconhecido"]))
            continue
        simbolo = obj.yahoo
        i = info.get(id_) or {}
        extra_status = None
        if getattr(obj, "param", lambda *a: None)("contrato_explicito") == "brent":
            # avaliar a serie que o RUNNER publicou: o contrato vem de series_info.contrato.
            # Runner sem o portao (main antiga) ou sem contrato = o Brent publicado e o
            # continuo BZ=F, que errou em 18, 21 e 23/09
            contrato = str(i.get("contrato") or "")
            m = re.search(r"\((BZ[A-Z]\d{2}\.NYM)\)", contrato)
            if m and "a conferir" not in contrato and i.get("qualidade"):
                simbolo = m.group(1)
            else:
                extra_status = "runner publicou o contínuo BZ=F, não o contrato"
        d = _show(ref, f"livro/series/{uni.nome_seguro(simbolo)}.json")
        if d and simbolo != obj.yahoo:
            d = {**d, "barras": _redatar(d.get("barras") or [])}
        if not d:
            out.append((id_, "ausente", None, ["sem série no branch"]))
            continue
        mercado = obj.mercado
        # mesmo corte do runner (Coleta.ate): no intradia, hoje; na manha e no fechamento,
        # o ultimo pregao encerrado do mercado
        ate = relogios.brt(agora).date() if modo == "intradia" else relogios.data_referencia(mercado, agora)
        noturno = qa.e_futuro(d, simbolo) or mercado == "ICE"
        barras = qa.limpar_fim_de_semana(yahoo.normalizar_datas(d.get("barras") or [], noturno), mercado)
        f17 = d.get("fechamentos_17h") or {}
        v = qa.avaliar({**d, "barras": barras}, simbolo, mercado, getattr(obj, "classe", ""), agora, ate,
                       confirmadas={k: x[1] for k, x in f17.items()})
        motivos = list(v.motivos)
        if i.get("contrato"):
            motivos.append(f"contrato: {i['contrato']}")
        # minerio CME liquida com um pregao de atraso: D-1 e o esperado, nao atraso
        defasado = int(getattr(obj, "param", lambda *a: 0)("defasagem_pregoes", 0) or 0) > 0
        esperado = relogios.dia_util_anterior(mercado, ate) if defasado else ate
        status = v.status
        if v.descartar_ultima:
            status = f"{qa.NAO_CONFIRMADO} (barra de {v.data_barra} descartada)"
        elif v.data_barra and v.data_barra < esperado.isoformat() and modo != "intradia":
            status = f"{qa.NAO_CONFIRMADO} (velha: dia {v.data_barra[8:10]}/{v.data_barra[5:7]})"
        elif v.dia_pregoes > 1 or v.parcial:
            status = f"{v.status} (dia não é um pregão)"
        if extra_status:
            status = f"{qa.NAO_CONFIRMADO} ({extra_status})"
        out.append((id_, status, v.data_barra, motivos))
    return out


def main(argv: list[str]) -> int:
    ref = "origin/dados"
    if "--ref" in argv:
        k = argv.index("--ref")
        ref = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    modo = None
    if "--modo" in argv:
        k = argv.index("--modo")
        modo = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    todos = "--todos" in argv
    argv = [x for x in argv if x != "--todos"]
    # sem argumento: os drivers; --todos: o universo inteiro, imprimindo so o que nao esta ok
    ids = argv or ([] if todos else list(qa.DRIVERS))
    linhas = avaliar_ref(ids, ref, modo=modo)
    ruins = 0
    for id_, status, data, motivos in linhas:
        if todos and status == qa.OK:
            continue
        ruins += status != qa.OK
        print(f"{id_:8} {status:34} {data or '-':10}  " + ("; ".join(motivos) if motivos else "ok"))
    if not argv:
        print(f"-- {len(linhas)} séries avaliadas; {ruins} fora de ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

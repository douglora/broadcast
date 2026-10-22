#!/usr/bin/env python3
"""Dispara um workflow do Actions pelo `gh` e espera o resultado chegar ao branch `dados`.

Na nuvem o disparo era a ferramenta `mcp__github__actions_run_trigger` e a espera
um laco de `git fetch` em segundo plano. Rodando no computador do Douglas a
ferramenta do GitHub nao vem pronta; este script faz as duas coisas com o `gh`
(ja logado na conta douglora) e devolve UMA linha de veredito.

    python3 ferramentas/local/disparar.py livro fechamento --ids "E04-MU-...,T01-..."
    python3 ferramentas/local/disparar.py livro intradia
    python3 ferramentas/local/disparar.py livro eventos
    python3 ferramentas/local/disparar.py coleta CURY3 DIRR3 --pares auto
    python3 ferramentas/local/disparar.py etfs
    python3 ferramentas/local/disparar.py ultimo livro          # so consulta: ultimo run, status e link

Regras que continuam valendo: o disparo e o plano B (o cron do Actions e o caminho
principal do livro); a sessao nunca escreve no branch `dados`; se o run falhar, a
resposta e a falha com o link, nunca silencio.

Use `--sem-esperar` para so disparar. A espera vai ate 8 minutos (`--espera`); no
Claude Code, rode com `run_in_background` ou com timeout de 10 minutos.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS = {"livro": "livro.yml", "coleta": "coletar-dados.yml", "etfs": "etfs.yml", "kinea": "kinea.yml"}
MODOS_LIVRO = ("manha", "intradia", "fechamento", "eventos", "ack", "sonda", "backfill")


def gh_bin() -> str | None:
    g = shutil.which("gh") or os.path.expanduser("~/.local/bin/gh")
    return g if os.path.exists(g) else None


def rodar(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=RAIZ, text=True, capture_output=True)


def agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def do_branch(caminho: str) -> dict | None:
    r = rodar(["git", "show", f"origin/dados:{caminho}"])
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def ultimo_run(gh: str, workflow: str) -> dict | None:
    r = rodar([gh, "run", "list", "--workflow", workflow, "--limit", "1", "--json",
               "databaseId,status,conclusion,event,createdAt,url,displayTitle"])
    if r.returncode != 0:
        return None
    try:
        lista = json.loads(r.stdout)
    except Exception:
        return None
    return lista[0] if lista else None


def linha_run(run: dict | None) -> str:
    if not run:
        return "sem run encontrado"
    return (f"run {run.get('databaseId')} ({run.get('event')}) criado {run.get('createdAt')}: "
            f"{run.get('status')}/{run.get('conclusion') or '-'} {run.get('url')}")


def chegou(alvo: str, args, desde: str) -> str | None:
    """Devolve o carimbo do arquivo-prova quando ele e posterior ao disparo."""
    if alvo == "livro":
        m = do_branch("livro/saida/manifest.json") or {}
        if m.get("slot") == args.modo and str(m.get("gerado_em") or "") > desde:
            return f"{m.get('slot')} gerado em {m.get('gerado_em_brt') or m.get('gerado_em')}"
        return None
    if alvo == "coleta":
        prontos = []
        for tk in args.tickers:
            d = do_branch(f"ativos/{tk}.json") or {}
            if str(d.get("gerado_em") or "") <= desde:
                return None
            prontos.append(f"{tk} {d.get('gerado_em')}")
        return "; ".join(prontos)
    c = do_branch("ultima_coleta.json" if alvo == "kinea" else "etfs/manifest.json") or {}
    g = str(c.get("gerado_em") or c.get("atualizado_em") or "")
    return g if g > desde else None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("alvo", choices=[*WORKFLOWS, "ultimo"])
    ap.add_argument("resto", nargs="*", help="livro: o modo; coleta: os tickers; ultimo: o alvo")
    ap.add_argument("--ids", default="", help="livro: ids ja narrados (ids_entregues)")
    ap.add_argument("--pares", default="nao", help="coleta: auto | lista | nao")
    ap.add_argument("--espera", type=int, default=480, help="segundos de espera (padrao 480)")
    ap.add_argument("--sem-esperar", action="store_true")
    a = ap.parse_args(argv[1:])

    gh = gh_bin()
    if not gh:
        print("LACUNA: gh nao encontrado neste computador; sem ele nao ha como disparar o workflow. "
              "Entregue o ultimo dado do branch com o horario em destaque.")
        return 3

    if a.alvo == "ultimo":
        alvo = (a.resto or ["livro"])[0]
        print(linha_run(ultimo_run(gh, WORKFLOWS.get(alvo, alvo))))
        return 0

    campos: list[str] = []
    if a.alvo == "livro":
        a.modo = (a.resto or ["intradia"])[0]
        if a.modo not in MODOS_LIVRO:
            print(f"modo invalido: {a.modo} (use um de {', '.join(MODOS_LIVRO)})")
            return 2
        campos = ["-f", f"modo={a.modo}", "-f", f"ids_entregues={a.ids}"]
    elif a.alvo == "coleta":
        a.tickers = [t.strip().upper() for parte in a.resto for t in parte.replace(",", " ").split() if t.strip()]
        if not a.tickers:
            print("coleta: informe ao menos um ticker")
            return 2
        campos = ["-f", f"tickers={','.join(a.tickers)}", "-f", f"pares={a.pares}"]

    wf = WORKFLOWS[a.alvo]
    desde = agora_iso()
    d = rodar([gh, "workflow", "run", wf, "--ref", "main", *campos])
    if d.returncode != 0:
        print(f"LACUNA: disparo de {wf} falhou: {(d.stderr or d.stdout).strip()[:200]}")
        return 3
    print(f"{wf} disparado as {desde} (ref main{', ' + ' '.join(campos[1::2]) if campos else ''})", flush=True)
    if a.sem_esperar:
        return 0

    fim = time.time() + a.espera
    tentativa = 0
    while time.time() < fim:
        time.sleep(20)
        tentativa += 1
        rodar(["git", "fetch", "-q", "origin", "dados"])
        ok = chegou(a.alvo, a, desde)
        if ok:
            print(f"FRESCO (tentativa {tentativa}): {ok}")
            return 0
        if tentativa % 3 == 0:
            run = ultimo_run(gh, wf)
            if run and run.get("status") == "completed" and run.get("conclusion") not in (None, "", "success") \
                    and str(run.get("createdAt") or "") >= desde[:16]:
                print(f"FALHOU: {linha_run(run)}")
                return 1
    print(f"NAO CHEGOU em {a.espera // 60} min: {linha_run(ultimo_run(gh, wf))}. "
          "Narre o ultimo dado disponivel com o horario dele em destaque.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

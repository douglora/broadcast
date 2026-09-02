#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Material de aprofundamento de um alerta do TrackNews, para o Hermes.

Uso:  python3 aprofundar.py <alert_id | "ultimo">

Le o branch `state` de douglora/tracknews-autopilot (o mesmo clone bare que a
ponte usa em ~/tracknews-bridge/repo.git) e imprime, SO LEITURA, tudo o que o
Hermes precisa para escrever a camada 2 sem inventar numero: o texto do alerta
como saiu no grupo, os claims auditados (valor, unidade, as_of, trecho da
fonte), a fonte e a hora. Nao envia nada, nao grava nada, nao chama rede alem
do git fetch do repo de estado.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path(os.environ.get("TRACKNEWS_BRIDGE_HOME", str(Path.home() / "tracknews-bridge")))
REPO_DIR = HOME / "repo.git"
REPO_URL = "https://github.com/douglora/tracknews-autopilot.git"
BRANCH = "state"
DIAS = 3


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def garante_repo() -> None:
    if (REPO_DIR / "HEAD").is_file():
        git("--git-dir", str(REPO_DIR), "fetch", "--depth", "1", "--force",
            "origin", f"{BRANCH}:refs/heads/{BRANCH}")
        return
    HOME.mkdir(parents=True, exist_ok=True)
    proc = git("clone", "--bare", "--depth", "1", "--single-branch",
               "--branch", BRANCH, REPO_URL, str(REPO_DIR))
    if proc.returncode != 0:
        sys.exit(f"nao consegui ler o repo de estado: {proc.stderr.strip()[:200]}")


def registros() -> list[dict]:
    hoje = datetime.now(timezone.utc).date()
    saida = []
    for i in range(DIAS):
        caminho = f"outputs/review/{(hoje - timedelta(days=i)).isoformat()}.jsonl"
        proc = git("--git-dir", str(REPO_DIR), "show", f"{BRANCH}:{caminho}")
        if proc.returncode != 0:
            continue
        for linha in proc.stdout.splitlines():
            try:
                registro = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if isinstance(registro.get("alert"), dict):
                saida.append(registro)
    return saida


def fmt_valor(claim: dict) -> str:
    valor = claim.get("value")
    if isinstance(valor, float):
        texto = f"{valor:,.4f}".rstrip("0").rstrip(".")
        texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    else:
        texto = str(valor)
    moeda = claim.get("currency") or ""
    unidade = claim.get("unit") or ""
    return " ".join(p for p in (moeda, texto, unidade) if p)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    pedido = sys.argv[1].strip()
    garante_repo()
    todos = registros()
    if not todos:
        print("nenhum alerta na janela dos ultimos dias.")
        return 1

    if pedido.lower() in ("ultimo", "último", "last"):
        aprovados = [r for r in todos if (r.get("gate") or {}).get("allowed") is True]
        escolhido = sorted(aprovados or todos, key=lambda r: r.get("recorded_at") or "")[-1]
    else:
        candidatos = [r for r in todos if r["alert"].get("alert_id") == pedido]
        if not candidatos:
            print(f"alerta {pedido} nao esta na janela dos ultimos {DIAS} dias.")
            return 1
        escolhido = candidatos[-1]

    alerta = escolhido["alert"]
    gate = escolhido.get("gate") or {}
    print(f"ALERTA {alerta.get('alert_id')}  prioridade={alerta.get('priority')}  "
          f"revisao={alerta.get('revision_type')}  gate={gate.get('action')}/"
          f"{'aprovado' if gate.get('allowed') else 'nao aprovado'}")
    print(f"registrado em {escolhido.get('recorded_at')}  story={alerta.get('story_id')}")
    print("\n--- texto exato que saiu no grupo ---")
    print(alerta.get("text", ""))
    print("--- fim do texto ---\n")

    claims = [c for c in (alerta.get("claims") or []) if isinstance(c, dict)]
    print(f"CLAIMS AUDITADOS ({len(claims)}): so estes numeros tem lastro. Numero fora "
          "desta lista precisa de fonte propria, citada com link e hora.")
    for c in claims:
        trecho = (c.get("source_context") or "").strip().replace("\n", " ")
        print(f"  - [{c.get('kind')}] {c.get('entity')} / {c.get('metric')}: "
              f"{fmt_valor(c)}  as_of={c.get('as_of')}  status={c.get('status')}  "
              f"confianca={c.get('confidence')}")
        if trecho:
            print(f"      fonte diz: \"{trecho[:220]}\"")

    print(f"\nFONTE: {escolhido.get('source_url') or alerta.get('source_url')}")
    if alerta.get("parent_alert_id"):
        print(f"REVISAO DE: {alerta['parent_alert_id']} (revision_no={alerta.get('revision_no')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

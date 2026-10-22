#!/usr/bin/env python3
"""Coleta direta no computador do Douglas: o mesmo coletor do Actions, sem a fila.

Na nuvem, toda coleta passava pelo GitHub Actions (3 a 8 minutos por ativo, mais a
fila). Com internet aberta o `coletar_dados.py` roda aqui mesmo, em cerca de um
minuto por ativo, e grava em `dados_local/` (fora do git). O `mesa.py` le essa
copia enquanto ela for mais nova que a do branch `dados`.

    python3 ferramentas/local/coletar.py CURY3                    # um ativo
    python3 ferramentas/local/coletar.py CURY3 --pares auto       # o ativo e o grupo de pares (pares.py)
    python3 ferramentas/local/coletar.py CURY3 DIRR3 --so-local   # nao avisa o Actions

O branch `dados` continua sendo o armazem compartilhado (celular, terminal, outras
sessoes) e so o Actions escreve nele. Por isso, depois da coleta local, este
script dispara tambem o `coletar-dados.yml` (sem esperar): em alguns minutos o
branch alcanca e volta a mandar. Use `--so-local` para pular esse disparo.

Depois de rodar, a leitura e a de sempre: `python3 mesa.py frescor TICKER`,
`cobertura`, `ficha`. Quando o dado vem daqui, o `mesa.py` avisa numa linha
">> ... coleta local de ...".
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL = os.environ.get("MESA_LOCAL", os.path.join(RAIZ, "dados_local"))
SEMENTE = ("ativos", "comparativos", "releases", "ri_descobertos.json", "ultima_coleta.json")


def rodar(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=RAIZ, text=True, **kw)


def carimbo(caminho: str) -> str | None:
    try:
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    return (d.get("gerado_em") or d.get("atualizado_em")) if isinstance(d, dict) else None


def semear() -> tuple[int, int]:
    """Traz do branch `dados` o que falta em dados_local/ (ou o que la esta mais novo).

    O coletor reaproveita o que ja existe na pasta de saida (releases baixados,
    indice, site de RI descoberto), como faz no Actions com o checkout do branch."""
    r = rodar(["git", "fetch", "-q", "origin", "dados"], capture_output=True)
    if r.returncode != 0:
        print(f"LACUNA: git fetch origin dados falhou ({r.stderr.strip()[:120]}); sigo com o que ha em dados_local/")
        return 0, 0
    existentes = rodar(["git", "ls-tree", "--name-only", "origin/dados"], capture_output=True).stdout.split()
    alvos = [s for s in SEMENTE if s in existentes]
    novos = atualizados = 0
    with tempfile.TemporaryDirectory() as tmp:
        tar = os.path.join(tmp, "dados.tar")
        with open(tar, "wb") as f:
            a = subprocess.run(["git", "archive", "origin/dados", *alvos], cwd=RAIZ, stdout=f)
        if a.returncode != 0:
            print("LACUNA: git archive do branch dados falhou; sigo com o que ha em dados_local/")
            return 0, 0
        ext = os.path.join(tmp, "x")
        os.makedirs(ext)
        subprocess.run(["tar", "-xf", tar, "-C", ext], check=True)
        for base, _dirs, arqs in os.walk(ext):
            for nome in arqs:
                origem = os.path.join(base, nome)
                rel = os.path.relpath(origem, ext)
                destino = os.path.join(LOCAL, rel)
                if not os.path.exists(destino):
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    shutil.copy2(origem, destino)
                    novos += 1
                elif nome.endswith(".json"):
                    cb, cl = carimbo(origem), carimbo(destino)
                    if cb and (not cl or cb > cl):
                        shutil.copy2(origem, destino)
                        atualizados += 1
    return novos, atualizados


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--pares", default="nao", help="auto = grupo do pares.py; lista de tickers; nao (padrao)")
    ap.add_argument("--sem-releases", action="store_true", help="nao baixa os releases (mais rapido)")
    ap.add_argument("--so-local", action="store_true", help="nao dispara o coletar-dados.yml no Actions")
    a = ap.parse_args(argv[1:])
    tks = [t.strip().upper() for parte in a.tickers for t in parte.replace(",", " ").split() if t.strip()]

    os.makedirs(LOCAL, exist_ok=True)
    novos, atualizados = semear()
    print(f"dados_local/: {novos} arquivos trazidos do branch dados, {atualizados} atualizados", flush=True)

    cmd = [sys.executable, "coletar_dados.py", "--tickers", ",".join(tks), "--pares", a.pares, "--saida", LOCAL]
    if a.sem_releases:
        cmd.append("--sem-releases")
    t0 = time.time()
    r = rodar(cmd)
    seg = time.time() - t0
    if r.returncode != 0:
        print(f"LACUNA: coleta local terminou com erro (saida {r.returncode}) em {seg:.0f} s; o branch dados segue valendo")
    else:
        print(f"coleta local concluida em {seg:.0f} s: {', '.join(tks)}" + (f" + pares ({a.pares})" if a.pares != "nao" else ""))

    if not a.so_local:
        gh = shutil.which("gh") or os.path.expanduser("~/.local/bin/gh")
        if not os.path.exists(gh):
            print("LACUNA: gh nao encontrado; o branch dados so alcanca na proxima rodada agendada do Actions")
        else:
            campos = ["-f", f"tickers={','.join(tks)}", "-f", f"pares={a.pares}"]
            if a.sem_releases:
                campos += ["-f", "sem_releases=true"]
            g = rodar([gh, "workflow", "run", "coletar-dados.yml", "--ref", "main", *campos], capture_output=True)
            if g.returncode == 0:
                print("Actions avisado (coletar-dados.yml): o branch dados alcanca em 3 a 8 minutos, sem precisar esperar")
            else:
                print(f"LACUNA: nao consegui disparar o coletar-dados.yml ({(g.stderr or g.stdout).strip()[:160]})")

    print("Leia como sempre: python3 mesa.py frescor " + tks[0] + " | cobertura | ficha")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""Cutuca a nuvem quando o agendador do GitHub Actions falha.

O cron "7,27,47 12-21 * * 1-5" do repo douglora/tracknews-autopilot deveria rodar
30 ciclos por dia util; na pratica o GitHub dispara 2 a 4 (buracos de horas).
Sem ciclo nao ha coleta nem alerta novo, e o push chega horas atrasado. Este
script roda a cada 10 min (ExecStartPre da ponte, via atualizar.sh) e, se o
ultimo ciclo gravado no branch state estiver velho, dispara o workflow.

Credencial: a MESMA que a ponte ja usa para buscar o repo privado (git
credential fill, no repo.git da ponte). Nao depende do `gh` estar no PATH do
systemd nem de token em variavel de ambiente; o `gh auth token` fica como
segunda opcao. O token nunca e impresso nem gravado.

Seguro por construcao:
  - so no dia util e na janela do cron (12h-21h UTC = 9h-18h de Brasilia);
  - nunca empilha: se ha run na fila ou rodando, nao dispara;
  - no maximo um disparo a cada 20 min (marca em .cutucada);
  - digest: se depois das 10h20 UTC (7h20 BRT) o branch state ainda nao tem
    outputs/digest/<hoje>.md, dispara UMA vez com digest=true;
  - qualquer falha e silenciosa para a entrega: o motivo vai para o
    atualizar.log uma unica vez por motivo (arquivo .cutucar-diag), e o
    heartbeat mostra essas linhas.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEST = Path(os.environ.get("TRACKNEWS_BRIDGE_HOME", str(Path.home() / "tracknews-bridge")))
LOG = DEST / "atualizar.log"
MARCA = DEST / ".cutucada"
DIAG = DEST / ".cutucar-diag"
REPO = "douglora/tracknews-autopilot"
WORKFLOW = "tracknews.yml"
API = os.environ.get("TRACKNEWS_GITHUB_API", "https://api.github.com")
INTERVALO = 1200  # 20 min entre disparos
CICLO_VELHO = 1500  # 25 min sem commit no state = agendador falhou
TIMEOUT = 30
PATH_EXTRA = (
    str(Path.home() / ".local/bin"),
    "/usr/local/bin",
    "/home/linuxbrew/.linuxbrew/bin",
    "/snap/bin",
    "/usr/bin",
    "/bin",
)


def log(msg: str) -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%F %T')}  cutucar-nuvem: {msg}\n")


def diag(msg: str) -> None:
    """Loga o motivo uma vez; repete so quando o motivo muda."""
    try:
        if DIAG.exists() and DIAG.read_text(encoding="utf-8").strip() == msg:
            return
        DIAG.write_text(msg + "\n", encoding="utf-8")
    except OSError:
        pass
    log(msg)


def diag_limpa() -> None:
    try:
        if DIAG.exists():
            DIAG.unlink()
    except OSError:
        pass


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([*PATH_EXTRA, env.get("PATH", "")])
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    return env


def token() -> tuple[str | None, str]:
    """(token, fonte). Primeiro a credencial do git, depois o gh."""
    for gitdir in (DEST / "repo.git", None):
        if gitdir is not None and not gitdir.exists():
            continue
        cmd = ["git"]
        if gitdir is not None:
            cmd += ["--git-dir", str(gitdir)]
        cmd += ["credential", "fill"]
        try:
            proc = subprocess.run(
                cmd,
                input="protocol=https\nhost=github.com\n\n",
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                env=_env(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in proc.stdout.splitlines():
            if line.startswith("password=") and line[9:].strip():
                return line[9:].strip(), "git-credential"
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env=_env(),
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip(), "gh"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None, ""


def api(tok: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict | list | None]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "tracknews-bridge cutucar-nuvem",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def main() -> int:
    agora = datetime.now(timezone.utc)
    if agora.isoweekday() > 5:
        return 0
    if MARCA.exists():
        try:
            ultimo = int(MARCA.read_text(encoding="utf-8").strip() or 0)
        except ValueError:
            ultimo = 0
        if agora.timestamp() - ultimo < INTERVALO:
            return 0

    hhmm = agora.hour * 100 + agora.minute
    na_janela = 12 <= agora.hour <= 21
    quer_digest_check = hhmm >= 1020
    if not (na_janela or quer_digest_check):
        return 0

    tok, fonte = token()
    if not tok:
        diag("sem credencial do GitHub neste ambiente (git credential fill e gh auth token falharam)")
        return 0

    ciclo_falta = False
    if na_janela:
        status, dados = api(tok, "GET", f"/repos/{REPO}/branches/state")
        if status != 200 or not isinstance(dados, dict):
            diag(f"GET branches/state respondeu {status} (token sem acesso ao repo? rede?)")
            return 0
        try:
            quando = dados["commit"]["commit"]["committer"]["date"]
            ultimo_state = datetime.fromisoformat(quando.replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            ultimo_state = None
        if ultimo_state is not None:
            ciclo_falta = (agora - ultimo_state).total_seconds() >= CICLO_VELHO

    digest_falta = False
    if quer_digest_check:
        hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()
        status, _ = api(tok, "GET", f"/repos/{REPO}/contents/outputs/digest/{hoje}.md?ref=state")
        digest_falta = status == 404

    if not (ciclo_falta or digest_falta):
        diag_limpa()
        return 0

    # Nao empilha: run na fila ou rodando conta como ciclo em andamento.
    status, dados = api(tok, "GET", f"/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page=5")
    if status != 200 or not isinstance(dados, dict):
        diag(f"GET workflow runs respondeu {status} (token sem escopo actions?)")
        return 0
    if any(run.get("status") != "completed" for run in dados.get("workflow_runs", [])):
        return 0

    status, _ = api(
        tok,
        "POST",
        f"/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
        {"ref": "main", "inputs": {"digest": "true" if digest_falta else "false"}},
    )
    if status == 204:
        MARCA.write_text(f"{int(agora.timestamp())}\n", encoding="utf-8")
        diag_limpa()
        log(
            f"workflow disparado via {fonte} "
            f"(ciclo_falta={int(ciclo_falta)} digest={'true' if digest_falta else 'false'})"
        )
    else:
        diag(f"dispatch respondeu {status} (token sem escopo workflow?)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # nunca derruba a entrega
        try:
            diag(f"erro inesperado: {type(exc).__name__}")
        except Exception:
            pass
        sys.exit(0)

#!/usr/bin/env bash
# Heartbeat: publica o estado da ponte no branch `tracknews-heartbeat` do repo
# douglora/broadcast, num unico commit sempre reescrito (a branch nunca cresce).
# Chamado pelo systemd (ExecStartPost) depois de cada execucao de 10 em 10 min.
#
# E o que permite acompanhar o PC de fora -- do celular, ou de uma sessao na
# nuvem -- sem ninguem colar nada em terminal. Por isso NUNCA carrega segredo:
# nenhum token, telefone ou id de chat (o destino sai so como rotulo id:<hash>,
# o mesmo que a ponte imprime na tela). O repo e publico; trate assim.
#
# Qualquer falha e silenciosa: sem rede ou sem credencial, simplesmente nao
# publica; a entrega nao depende disto.
set -uo pipefail

SRC="${TRACKNEWS_BRIDGE_SRC:-$HOME/src/broadcast}"
DEST="${TRACKNEWS_BRIDGE_HOME:-$HOME/tracknews-bridge}"
RAMO="tracknews-heartbeat"
WORK="$DEST/heartbeat"

[ -d "$DEST" ] || exit 0
URL="$(git -C "$SRC" remote get-url origin 2>/dev/null)" || exit 0
[ -n "$URL" ] || exit 0

# credencial: o gh ja autenticado configura o helper do git uma unica vez
if ! git config --global --get-all credential.helper 2>/dev/null | grep -q .; then
  command -v gh >/dev/null 2>&1 && gh auth setup-git >/dev/null 2>&1 || true
fi

mkdir -p "$WORK"
python3 - "$DEST" "$SRC" > "$WORK/status.json" <<'PY' || exit 0
import json, os, pathlib, socket, subprocess, sys, urllib.request
from datetime import datetime, timezone, timedelta

dest, src = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
tz = timezone(timedelta(hours=-3))
agora = datetime.now(tz)

def sh(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return ""

cfg = {}
try:
    cfg = json.loads((dest / "config.json").read_text(encoding="utf-8"))
except Exception:
    pass

enviados = {"alertas": {}}
try:
    enviados = json.loads((dest / "enviados.json").read_text(encoding="utf-8"))
except Exception:
    pass
registros = enviados.get("alertas") or {}
reais = [v for v in registros.values() if v.get("resultado") == "enviado"]
hoje = [v for v in reais if (v.get("enviado_em") or "").startswith(agora.date().isoformat())]

ultimos = []
try:
    linhas = (dest / "log.jsonl").read_text(encoding="utf-8").splitlines()[-6:]
    for l in linhas:
        try:
            e = json.loads(l)
        except Exception:
            continue
        ultimos.append({k: e.get(k) for k in ("ts", "evento", "alert_id", "resultado", "motivo", "http")
                        if e.get(k) is not None})
except Exception:
    pass

def saude(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            d = json.loads(r.read(2000).decode("utf-8", "replace"))
        return {k: d.get(k) for k in ("status", "queueLength", "uptime") if k in d}
    except Exception as erro:
        return {"erro": str(erro)[:60]}

transporte = cfg.get("transporte") or "waha"
base = (cfg.get("hermes") or {}).get("base_url") if transporte == "hermes" else (cfg.get("waha") or {}).get("base_url")

import hashlib
chat = cfg.get("destino", {}).get("chat_id")
rotulo = ("id:" + hashlib.sha256(chat.encode()).hexdigest()[:12]) if chat else None

marca = dest / ".teste-ok"
print(json.dumps({
    "gerado_em": agora.isoformat(),
    "host": socket.gethostname(),
    "commit_instalado": sh("git", "-C", str(src), "rev-parse", "--short", "HEAD"),
    "commit_data": sh("git", "-C", str(src), "log", "-1", "--format=%ci"),
    "transporte": transporte,
    "endpoint": base,
    "saude_transporte": saude((base or "http://localhost:3000").rstrip("/") + ("/health" if transporte == "hermes" else "/api/sessions")),
    "envio_habilitado": bool(cfg.get("envio_habilitado")),
    "pausado": (dest / "PAUSED").exists(),
    "destino": rotulo,
    "teste_enviado_em": marca.read_text().strip() if marca.exists() else None,
    "entregues_total": len(reais),
    "entregues_hoje": len(hoje),
    "ids_conhecidos": len(registros),
    "timer": sh("systemctl", "--user", "list-timers", "tracknews-bridge.timer", "--no-pager", "--no-legend"),
    "ultimos_eventos": ultimos,
    "atualizacoes": (dest / "atualizar.log").read_text(encoding="utf-8").splitlines()[-3:] if (dest / "atualizar.log").exists() else [],
}, ensure_ascii=False, indent=2))
PY

cd "$WORK" || exit 0
if [ ! -d .git ]; then
  git init -q 2>/dev/null || exit 0
  git config user.name "tracknews-bridge" 2>/dev/null
  git config user.email "tracknews-bridge@localhost" 2>/dev/null
  git remote add origin "$URL" 2>/dev/null
fi
git remote set-url origin "$URL" 2>/dev/null
# um unico commit orfao a cada vez: a branch nunca acumula historico
git checkout -q --orphan _hb 2>/dev/null || true
git add -A 2>/dev/null
git commit -q -m "heartbeat $(date -u '+%FT%TZ')" 2>/dev/null || exit 0
git branch -M "$RAMO" 2>/dev/null
GIT_TERMINAL_PROMPT=0 timeout 60 git push -q --force origin "$RAMO" >/dev/null 2>&1 || true
exit 0

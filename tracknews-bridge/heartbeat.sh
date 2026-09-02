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

# Enquanto o destino nao estiver gravado, o heartbeat carrega o diagnostico da
# descoberta (rotas do bridge, listagem de grupos, busca local) -- sem ids.
diag = None
if not chat:
    try:
        sys.path.insert(0, str(dest))
        import hermes as _h
        diag = _h.diagnostico((cfg.get("hermes") or {}).get("base_url") or "http://localhost:3000",
                              cfg.get("destino", {}).get("nome_grupo") or "AutoPilot News")
    except Exception as erro:
        diag = {"erro": str(erro)[:120]}

import re as _re
def _mask(s):
    s = _re.sub(r"\d{10,}@(g\.us|c\.us|s\.whatsapp\.net)", r"<id>@\1", s or "")
    s = _re.sub(r"\+?\d{2}\s?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}", "<fone>", s)
    return _re.sub(r"(key|token|secret|senha|pass)([=: ])\S+", r"\1\2<omitido>", s, flags=_re.I)

# --- o que ha no grupo de destino (so leitura, sem ids): quem mandou, tamanho,
#     comeco do texto. E o que permite saber se o que o Douglas ve veio da ponte
#     ou de outro agente que ainda posta no grupo.
recentes = []
if chat and transporte == "hermes" and base:
    def _get(url):
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                return json.loads(r.read(400_000).decode("utf-8", "replace"))
        except Exception:
            return None
    itens = []
    d1 = _get(base.rstrip("/") + "/chat/" + chat)
    if isinstance(d1, dict):
        for k in ("messages", "recent", "history"):
            if isinstance(d1.get(k), list): itens += d1[k]
        if isinstance(d1.get("chat"), dict):
            for k in ("messages", "recent", "history"):
                if isinstance(d1["chat"].get(k), list): itens += d1["chat"][k]
    d2 = _get(base.rstrip("/") + "/messages?limit=500") or _get(base.rstrip("/") + "/messages")
    lista = d2 if isinstance(d2, list) else (d2.get("messages") if isinstance(d2, dict) else None) or []
    for m in lista:
        if not isinstance(m, dict): continue
        cid = m.get("chatId") or m.get("chat_id") or m.get("jid") or m.get("remoteJid") or m.get("from") or m.get("chat")
        if isinstance(cid, dict): cid = cid.get("_serialized") or cid.get("id")
        if cid == chat: itens.append(m)
    for m in itens[-12:]:
        if not isinstance(m, dict): continue
        texto = m.get("text") or m.get("message") or m.get("body") or m.get("content") or ""
        if isinstance(texto, dict): texto = texto.get("text") or texto.get("conversation") or json.dumps(texto)[:80]
        recentes.append({
            "ts": m.get("timestamp") or m.get("ts") or m.get("t") or m.get("time"),
            "de_mim": m.get("fromMe") if "fromMe" in m else m.get("from_me"),
            "quem": _mask(str(m.get("pushName") or m.get("sender") or m.get("author") or ""))[:30],
            "tam": len(str(texto)),
            "inicio": _mask(str(texto))[:70],
        })

# --- resumo mascarado do recon do agente antigo (o que ainda posta no grupo)
antigo = []
try:
    for l in (pathlib.Path.home() / "relatorio-antigo.txt").read_text(encoding="utf-8", errors="replace").splitlines():
        if _re.search(r"timer|\.service|docker|container|schtasks|Tarefa|pm2|cron|\.py|\.js|\.ps1|\.bat|sendText|/api/send|@g\.us|=====", l, _re.I):
            antigo.append(_mask(l)[:150])
    antigo = antigo[:70]
except Exception:
    pass

# --- o handler /send do bridge.js do Hermes: ele altera o texto?
handler = []
try:
    sys.path.insert(0, str(dest))
    import hermes as _h2
    bjs = _h2.caminho_bridge_js()
    if bjs:
        linhas = bjs.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, l in enumerate(linhas):
            if _re.search(r"post\(\s*['\"]/send['\"]", l):
                handler = [_mask(x)[:140] for x in linhas[i:i+32]]
                break
except Exception:
    pass
try:
    rabo = [ _mask(l)[:160] for l in (pathlib.Path.home() / "bootstrap-tracknews.log").read_text(encoding="utf-8", errors="replace").splitlines()[-25:] ]
except Exception:
    rabo = []

print(json.dumps({
    "diagnostico_descoberta": diag,
    "bootstrap_ultimas_linhas": rabo,
    "grupo_recentes": recentes,
    "agente_antigo_recon": antigo,
    "bridge_send_handler": handler,
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

#!/usr/bin/env bash
# Instalacao completa da ponte TrackNews com UM comando, colado no Ubuntu do WSL:
#
#   curl -fsSL -o /tmp/tn.sh https://raw.githubusercontent.com/douglora/broadcast/claude/tracknews-bridge-autopilot-k3avgo/tracknews-bridge/bootstrap.sh && bash /tmp/tn.sh
#
# Ja tendo o repo em disco, o caminho curto e:  bash ~/src/broadcast/tracknews-bridge/bootstrap.sh
#
# Faz, nesta ordem, tudo que o runbook manual fazia:
#   1. clona/atualiza o repo e instala a ponte (install.sh + autoteste)
#   2. agenda: timer systemd de usuario; sem systemd, Tarefa Agendada do Windows
#   3. linger, para o timer sobreviver ao fechamento do terminal
#   4. lado Windows via interop (powershell.exe): tarefa que religa o WSL no
#      logon, energia sem suspensao, Docker Desktop no boot; confere autologon
#   5. WAHA: acha o endpoint, localiza o grupo (so leitura) e, se o container
#      estiver no Docker, garante --restart unless-stopped (nao reinicia nada)
#   6. dry-run; se o WAHA confirmou o grupo, liga o envio e faz UM teste com o
#      alerta aprovado mais recente da janela (unico envio autorizado)
#   7. recon do agente antigo e hermes-check, ambos SO LEITURA
#   8. resumo com o que ficou OK e o que ficou PENDENTE
#
# Idempotente: rodar de novo nao duplica nada. Nunca mexe em autopilot-br,
# broadcast-terminal, nem em tarefas/containers alheios.
set -uo pipefail

BRANCH="claude/tracknews-bridge-autopilot-k3avgo"
REPO_URL="https://github.com/douglora/broadcast"
SRC="$HOME/src/broadcast"
DEST="${TRACKNEWS_BRIDGE_HOME:-$HOME/tracknews-bridge}"
LOG="$HOME/bootstrap-tracknews.log"
PENDENCIAS=()

diz()  { printf '\n==> %s\n' "$*"; }
pend() { PENDENCIAS+=("$1"); printf '    PENDENTE: %s\n' "$1"; }

# Depois de um re-exec (veja abaixo) a saida ja esta ligada ao tee do processo
# anterior; montar um segundo gravaria cada linha duas vezes no log.
if [ "${TRACKNEWS_REEXEC:-}" != "1" ]; then
  exec > >(tee -a "$LOG") 2>&1
fi
diz "bootstrap TrackNews $(date '+%F %T') em $(uname -n)"

# ---------------------------------------------------------------- 1. repo
diz "repo em $SRC (branch $BRANCH)"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch origin "$BRANCH" \
    && git -C "$SRC" checkout -q "$BRANCH" \
    && git -C "$SRC" pull --ff-only -q origin "$BRANCH" \
    || { pend "nao consegui atualizar o repo; confira a rede e rode de novo"; exit 1; }
else
  mkdir -p "$HOME/src"
  git clone -q -b "$BRANCH" "$REPO_URL" "$SRC" \
    || { pend "clone do repo falhou; confira a rede e rode de novo"; exit 1; }
fi
echo "    commit: $(git -C "$SRC" log -1 --format='%h %s')"

# Sob `curl | bash` o proprio script chega pela entrada padrao. Qualquer
# subprocesso que leia stdin (o powershell.exe do passo 4 le) engole o resto do
# script e a execucao termina no meio, em silencio. Agora que o repo esta em
# disco, seguimos a partir do arquivo e com stdin fechado.
if [ "${TRACKNEWS_REEXEC:-}" != "1" ] && [ ! -f "${BASH_SOURCE[0]:-}" ]; then
  export TRACKNEWS_REEXEC=1
  echo "    seguindo a partir do arquivo (stdin fechado)"
  exec bash "$SRC/tracknews-bridge/bootstrap.sh" < /dev/null
fi

# ------------------------------------------------- 2. instalar + agendar
COM_SYSTEMD=1
if systemctl --user show-environment >/dev/null 2>&1; then
  bash "$SRC/tracknews-bridge/install.sh" --agendar \
    || { pend "install.sh --agendar falhou (veja acima); parando"; exit 1; }
else
  COM_SYSTEMD=0
  diz "systemd de usuario indisponivel: instalando sem timer (fallback Windows adiante)"
  bash "$SRC/tracknews-bridge/install.sh" \
    || { pend "install.sh falhou (veja acima); parando"; exit 1; }
fi

# ----------------------------------------------------------- 3. linger
if [ "$COM_SYSTEMD" = 1 ]; then
  usuario="${USER:-$(id -un)}"
  if loginctl show-user "$usuario" 2>/dev/null | grep -q '^Linger=yes'; then
    echo "    linger ja ativo"
  elif loginctl enable-linger "$usuario" 2>/dev/null \
       || sudo -n loginctl enable-linger "$usuario" 2>/dev/null; then
    echo "    linger ativado"
  else
    pend "linger nao ativado (pede senha); rode depois: sudo loginctl enable-linger $usuario"
  fi
fi

# ------------------------------------- 4. lado Windows, via interop
PS_EXE=""
for c in powershell.exe /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe; do
  command -v "$c" >/dev/null 2>&1 && { PS_EXE="$c"; break; }
done
if [ -n "$PS_EXE" ]; then
  diz "configurando o lado Windows (tarefas, energia, Docker Desktop)"
  WTEMP_WIN="$(timeout 30 "$PS_EXE" -NoProfile -Command '[Console]::Out.Write($env:TEMP)' </dev/null 2>/dev/null | tr -d '\r')"
  if [ -n "$WTEMP_WIN" ] && WTEMP_WSL="$(wslpath -u "$WTEMP_WIN" 2>/dev/null)" && [ -d "$WTEMP_WSL" ]; then
    cp "$SRC/tracknews-bridge/windows/wsl-autostart-task.xml" \
       "$SRC/tracknews-bridge/windows/tracknews-bridge-task.xml" \
       "$SRC/tracknews-bridge/windows/bootstrap-windows.ps1" "$WTEMP_WSL/"
    FLAG=""
    [ "$COM_SYSTEMD" = 0 ] && FLAG="-ComBridgeTask"
    PSOUT="$(mktemp)"
    timeout 120 "$PS_EXE" -NoProfile -ExecutionPolicy Bypass \
      -File "$WTEMP_WIN\\bootstrap-windows.ps1" $FLAG </dev/null 2>&1 | tr -d '\r' > "$PSOUT" || true
    sed 's/^/    /' "$PSOUT"
    while IFS= read -r l; do
      PENDENCIAS+=("windows: ${l#PENDENTE }")
    done < <(grep '^PENDENTE' "$PSOUT" || true)
    rm -f "$PSOUT"
  else
    pend "nao achei o TEMP do Windows; rode na mao (PowerShell): $SRC/tracknews-bridge/windows/bootstrap-windows.ps1"
  fi
else
  pend "powershell.exe inacessivel (interop desligado?): o religamento pos-boot do WSL nao foi configurado"
fi

# ------------------- 5. WAHA: achar o endpoint, grupo, restart policy
cd "$DEST" || { pend "diretorio $DEST nao existe"; exit 1; }

# Procura onde o WAHA realmente atende e corrige waha.base_url. So leitura:
# nada e iniciado, reiniciado ou reconfigurado no WAHA.
#
# "Alguem respondeu na porta" nao basta: um 404 em /api/sessions quer dizer que
# ha um servidor ali que NAO e o WAHA (no PC do Douglas a porta 3000 e do
# gateway do Hermes). So contam 200 com JSON, ou 401/403, que e WAHA pedindo
# chave.
python3 - <<'PY'
import json, pathlib, re, subprocess, urllib.error, urllib.request

caminho = pathlib.Path.home() / "tracknews-bridge/config.json"
cfg = json.loads(caminho.read_text(encoding="utf-8"))
atual = cfg["waha"]["base_url"].rstrip("/")

def sonda(base: str):
    """(veredito, detalhe) com veredito em {waha, outro, mudo}."""
    try:
        with urllib.request.urlopen(base + "/api/sessions", timeout=3) as resp:
            corpo = resp.read(400).decode("utf-8", "replace").lstrip()
            status = resp.status
        if corpo.startswith(("[", "{")):
            return "waha", f"HTTP {status}, resposta JSON"
        return "outro", f"HTTP {status}, resposta nao e JSON"
    except urllib.error.HTTPError as erro:
        if erro.code in (401, 403):
            return "waha", f"HTTP {erro.code}, pede chave de API"
        return "outro", f"HTTP {erro.code} (ha um servidor, mas nao e o WAHA)"
    except Exception as erro:
        return "mudo", str(erro)[:60]

def portas_do_docker():
    """Portas publicadas por containers cuja imagem ou nome cita waha."""
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Image}}|{{.Names}}|{{.Ports}}"],
            capture_output=True, text=True, timeout=20)
    except Exception:
        return []
    achadas = []
    for linha in proc.stdout.splitlines():
        if "waha" not in linha.lower():
            continue
        for porta in re.findall(r":(\d+)->", linha):
            achadas.append(f"http://localhost:{porta}")
    return achadas

candidatos = []
for base in (portas_do_docker() + [atual, "http://localhost:3000",
                                   "http://localhost:3001", "http://localhost:3002",
                                   "http://localhost:8080", "http://localhost:8000",
                                   "http://localhost:4000"]):
    if base not in candidatos:
        candidatos.append(base)

escolhido = None
for base in candidatos:
    veredito, detalhe = sonda(base)
    print(f"    {base}: {veredito} ({detalhe})")
    if veredito == "waha" and escolhido is None:
        escolhido = base

if escolhido is None:
    print("    nenhum WAHA encontrado nas portas sondadas")
elif escolhido == atual:
    print(f"    WAHA confirmado em {atual}")
else:
    cfg["waha"]["base_url"] = escolhido
    caminho.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    caminho.chmod(0o600)
    print(f"    WAHA achado em {escolhido}: base_url corrigido no config.json")
PY

WAHA_OK=0
if python3 bridge.py waha; then
  WAHA_OK=1
else
  pend "WAHA nao confirmou o grupo (veja acima): envio segue DESLIGADO; suba o WAHA e rode o bootstrap de novo"
fi

if command -v docker >/dev/null 2>&1 && timeout 20 docker ps >/dev/null 2>&1; then
  CANDIDATOS="$(docker ps --format '{{.ID}} {{.Image}} {{.Names}}' | grep -i waha | awk '{print $1}')"
  [ -z "$CANDIDATOS" ] && CANDIDATOS="$(docker ps --filter publish=3000 --format '{{.ID}}')"
  N="$(printf '%s\n' "$CANDIDATOS" | grep -c . || true)"
  if [ "$N" = 1 ]; then
    POLITICA="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$CANDIDATOS")"
    case "$POLITICA" in
      always|unless-stopped) echo "    WAHA: restart policy ja e '$POLITICA'" ;;
      *) docker update --restart unless-stopped "$CANDIDATOS" >/dev/null \
           && echo "    WAHA: restart unless-stopped aplicado (nada foi reiniciado)" \
           || pend "docker update --restart unless-stopped falhou no container do WAHA" ;;
    esac
  elif [ "$N" = 0 ]; then
    pend "nenhum container do WAHA visivel no docker: se ele roda por outro caminho, garanta o retorno automatico no boot"
  else
    pend "mais de um container parece ser o WAHA; nao mexi em nenhum (decida qual e rode: docker update --restart unless-stopped <id>)"
  fi
else
  echo "    docker nao acessivel deste shell; pulei a politica de restart do WAHA"
fi

# --------------------------- 6. dry-run; ligar envio; UM teste real
python3 bridge.py dry-run || pend "dry-run falhou (veja acima)"

if [ "$WAHA_OK" = 1 ]; then
  python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / "tracknews-bridge/config.json"
c = json.loads(p.read_text(encoding="utf-8"))
c["envio_habilitado"] = True
p.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
p.chmod(0o600)
print("    envio_habilitado = true")
PY
  ALERT_ID="$(python3 - <<'PY'
import sys, pathlib
sys.path.insert(0, str(pathlib.Path.home() / "tracknews-bridge"))
import bridge
try:
    aprovados, _ = bridge.coleta_aprovados(bridge.carrega_config())
    fila = bridge.ordena_fila(aprovados)
    if fila:
        print(fila[-1]["alert_id"])
except Exception:
    pass
PY
)"
  MARCA="$DEST/.teste-ok"
  if [ -f "$MARCA" ]; then
    diz "teste de envio ja foi feito antes ($(cat "$MARCA")); nao repito"
  elif [ -n "$ALERT_ID" ]; then
    diz "teste unico autorizado: $ALERT_ID"
    SAIDA="$(python3 bridge.py test-send --confirmo --alert-id "$ALERT_ID" 2>&1)"; RC=$?
    printf '%s\n' "$SAIDA"
    if [ $RC -ne 0 ] && printf '%s' "$SAIDA" | grep -q "silencio"; then
      diz "janela de silencio; unico envio autorizado com --ignorar-silencio"
      SAIDA="$(python3 bridge.py test-send --confirmo --alert-id "$ALERT_ID" --ignorar-silencio 2>&1)"; RC=$?
      printf '%s\n' "$SAIDA"
    fi
    if [ $RC -eq 0 ]; then
      date '+%F %T' > "$MARCA"
      echo "    TESTE ENVIADO: confira o grupo AutoPilot News no WhatsApp"
    else
      python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / "tracknews-bridge/config.json"
c = json.loads(p.read_text(encoding="utf-8"))
c["envio_habilitado"] = False
p.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
p.chmod(0o600)
PY
      pend "teste de envio falhou: envio_habilitado voltou para false; veja a saida acima e o log.jsonl"
    fi
  else
    diz "nenhum alerta aprovado na janela agora: envio fica LIGADO e o primeiro alerta real sai sozinho pelo agendamento"
  fi
fi

# ------------------------------ 7. recon (so leitura) + hermes-check
bash "$DEST/recon-antigo.sh" > "$HOME/relatorio-antigo.txt" 2>&1 \
  && echo "    recon do agente antigo: $HOME/relatorio-antigo.txt (nada foi desligado)" \
  || pend "recon-antigo.sh falhou"
bash "$DEST/hermes-check.sh" > "$HOME/relatorio-hermes.txt" 2>&1 \
  && echo "    hermes-check: $HOME/relatorio-hermes.txt (nada foi alterado)" \
  || pend "hermes-check.sh falhou"

# ----------------------------------------------------------- 8. resumo
diz "RESUMO"
if [ "$COM_SYSTEMD" = 1 ]; then
  systemctl --user list-timers tracknews-bridge.timer --no-pager 2>/dev/null || true
fi
python3 bridge.py status --sem-fila || true
echo
if [ "${#PENDENCIAS[@]}" -eq 0 ]; then
  echo "VEREDITO: FUNCIONANDO — nada pendente."
else
  echo "VEREDITO: PARCIAL — pendencias:"
  for p in "${PENDENCIAS[@]}"; do echo "  - $p"; done
fi
echo
echo "pausar:  touch $DEST/PAUSED    voltar: rm $DEST/PAUSED"
echo "log completo: $LOG"
echo "NAO DESLIGUE O PC."

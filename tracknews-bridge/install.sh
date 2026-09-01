#!/usr/bin/env bash
# Instala a ponte em ~/tracknews-bridge. NAO liga o envio: isso e decisao do Douglas.
# Nao mexe no WAHA, nao mexe em autopilot-br, nao mexe em broadcast-terminal e nao
# altera nenhuma unit ou tarefa agendada que ja exista com outro nome.
set -euo pipefail

origem="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
destino="${TRACKNEWS_BRIDGE_HOME:-$HOME/tracknews-bridge}"
com_systemd=false
com_launchd=false
case "${1:-}" in
  --systemd) com_systemd=true ;;
  --launchd) com_launchd=true ;;
  --agendar) [[ "$(uname -s)" == "Darwin" ]] && com_launchd=true || com_systemd=true ;;
  "") ;;
  *) echo "uso: install.sh [--systemd | --launchd | --agendar]" >&2; exit 2 ;;
esac

command -v python3 >/dev/null || { echo "python3 nao encontrado"; exit 1; }
command -v git     >/dev/null || { echo "git nao encontrado"; exit 1; }
python3 - <<'PY' || { echo "precisa de python3 >= 3.9"; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)
PY

echo "==> instalando em $destino"
mkdir -p "$destino"; chmod 700 "$destino"
install -m 0755 "$origem/bridge.py"    "$destino/bridge.py"
install -m 0755 "$origem/autoteste.py" "$destino/autoteste.py"
install -m 0755 "$origem/recon-antigo.sh" "$destino/recon-antigo.sh"
install -m 0755 "$origem/hermes-check.sh" "$destino/hermes-check.sh"
install -m 0755 "$origem/diagnostico-entrega.sh" "$destino/diagnostico-entrega.sh"

if [[ ! -f "$destino/config.json" ]]; then
  install -m 0600 "$origem/config.example.json" "$destino/config.json"
  echo "    config.json criado (envio_habilitado=false)"
else
  chmod 600 "$destino/config.json"
  echo "    config.json ja existia; preservado"
fi

mkdir -p "$HOME/.config/tracknews-bridge"; chmod 700 "$HOME/.config/tracknews-bridge"
if [[ ! -f "$HOME/.config/tracknews-bridge/.env" ]]; then
  printf '# chave do WAHA, se o seu exigir. Formato: WAHA_API_KEY=...\n' \
    > "$HOME/.config/tracknews-bridge/.env"
fi
chmod 600 "$HOME/.config/tracknews-bridge/.env"

echo "==> autoteste"
python3 "$destino/autoteste.py" >/dev/null && echo "    tudo passou" || { echo "    AUTOTESTE FALHOU"; exit 1; }

if command -v gh >/dev/null 2>&1; then
  gh auth status >/dev/null 2>&1 && echo "==> gh autenticado" \
    || echo "==> ATENCAO: gh existe mas nao esta autenticado (rode: gh auth login && gh auth setup-git)"
else
  echo "==> gh nao encontrado; o clone do repo privado vai depender do credential helper do git"
fi

if [[ "$com_systemd" == true ]]; then
  if ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "==> systemd de usuario indisponivel."
    echo "    Habilite systemd no /etc/wsl.conf ([boot] systemd=true), rode 'wsl --shutdown'"
    echo "    no PowerShell e reabra o Ubuntu. Alternativa: windows/tracknews-bridge-task.xml"
    exit 1
  fi
  unidades="$HOME/.config/systemd/user"; mkdir -p "$unidades"
  backup="$HOME/.local/state/tracknews-bridge/unit-backups/$(date -u +%Y%m%dT%H%M%SZ)"
  for arquivo in "$origem"/systemd/tracknews-bridge.*; do
    alvo="$unidades/$(basename "$arquivo")"
    if [[ -f "$alvo" ]]; then mkdir -p "$backup"; cp -p "$alvo" "$backup/"; fi
    install -m 0644 "$arquivo" "$alvo"
  done
  systemctl --user daemon-reload
  systemctl --user enable --now tracknews-bridge.timer
  # $USER pode nao estar exportado (shell nao-login); com set -u a referencia
  # crua abortaria a instalacao exatamente aqui.
  usuario="${USER:-$(id -un)}"
  loginctl enable-linger "$usuario" 2>/dev/null \
    || echo "    rode manualmente: sudo loginctl enable-linger $usuario"
  echo "==> timer ligado (a cada 10 min). O envio segue DESLIGADO por config.json."
  systemctl --user list-timers tracknews-bridge.timer --no-pager || true
fi

if [[ "$com_launchd" == true ]]; then
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "==> --launchd so faz sentido no macOS"; exit 1
  fi
  plist="$HOME/Library/LaunchAgents/com.tracknews.bridge.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  if [[ -f "$plist" ]]; then
    cp -p "$plist" "$plist.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    echo "    plist anterior salvo em $plist.bak.*"
  fi
  # launchd nao expande $HOME: o caminho vai literal.
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.tracknews.bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v python3)</string>
    <string>$destino/bridge.py</string>
    <string>run</string>
  </array>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><false/>
  <key>WorkingDirectory</key><string>$destino</string>
  <key>StandardOutPath</key><string>$destino/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$destino/launchd.err.log</string>
</dict>
</plist>
PLIST
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist" && echo "==> launchd carregado (a cada 10 min)."
  echo "    O envio segue DESLIGADO por config.json."
  echo "    desligar : launchctl unload $plist"
  echo "    religar  : launchctl load $plist"
fi

cat <<FIM

pronto. proximos passos, nesta ordem:

  1. cd $destino && python3 bridge.py waha        # acha o grupo e grava o id (so leitura)
  2. python3 bridge.py dry-run                    # mostra o que sairia, sem enviar
  3. (com o "pode enviar" do Douglas)
     jq '.envio_habilitado = true' config.json > c.tmp && mv c.tmp config.json && chmod 600 config.json
     python3 bridge.py test-send --confirmo       # UM unico envio

pausar a qualquer momento:  touch $destino/PAUSED
voltar:                     rm $destino/PAUSED
FIM

#!/usr/bin/env bash
# Auto-atualizacao da ponte, chamada pelo systemd (ExecStartPre) antes de cada
# execucao de 10 em 10 minutos. Objetivo: uma correcao publicada no branch
# chega ao PC sozinha, sem ninguem colar nada em terminal.
#
# Seguro por construcao:
#   - so instala se o autoteste da versao NOVA passar, rodando no checkout,
#     antes de encostar em ~/tracknews-bridge;
#   - nunca toca em config.json, enviados.json, .env, nem no timer/unit;
#   - qualquer falha (rede, teste) e silenciosa e a ponte segue com a versao
#     que ja tinha -- o systemd chama este script com "-" na frente, entao um
#     erro aqui nunca impede a entrega.
set -uo pipefail

BRANCH="claude/tracknews-bridge-autopilot-k3avgo"
SRC="${TRACKNEWS_BRIDGE_SRC:-$HOME/src/broadcast}"
DEST="${TRACKNEWS_BRIDGE_HOME:-$HOME/tracknews-bridge}"
LOG="$DEST/atualizar.log"

[ -d "$SRC/.git" ] || exit 0
mkdir -p "$DEST"

antes="$(git -C "$SRC" rev-parse HEAD 2>/dev/null)"
timeout 60 git -C "$SRC" fetch -q origin "$BRANCH" 2>/dev/null || exit 0
depois="$(git -C "$SRC" rev-parse "origin/$BRANCH" 2>/dev/null)"
[ -n "$depois" ] || exit 0

# Tambem cobre o caso em que o checkout ja esta na frente mas ~/tracknews-bridge
# ficou para tras (bootstrap interrompido): compara o bridge.py instalado.
if [ "$antes" = "$depois" ] \
   && cmp -s "$SRC/tracknews-bridge/bridge.py" "$DEST/bridge.py" 2>/dev/null; then
  exit 0
fi

git -C "$SRC" checkout -q "$BRANCH" 2>/dev/null || exit 0
git -C "$SRC" reset -q --hard "origin/$BRANCH" 2>/dev/null || exit 0

# Autoteste da versao nova, num diretorio descartavel, ANTES de instalar.
if ! TRACKNEWS_BRIDGE_HOME="$(mktemp -d)" python3 "$SRC/tracknews-bridge/autoteste.py" >/dev/null 2>&1; then
  printf '%s  versao %s reprovou no autoteste; mantive a instalada\n' \
    "$(date '+%F %T')" "${depois:0:7}" >> "$LOG"
  exit 0
fi

# install.sh sem --agendar: copia os arquivos, preserva config.json, nao mexe
# em unit nem timer.
if bash "$SRC/tracknews-bridge/install.sh" >/dev/null 2>&1; then
  printf '%s  atualizado para %s\n' "$(date '+%F %T')" "${depois:0:7}" >> "$LOG"
else
  printf '%s  install.sh falhou na versao %s\n' "$(date '+%F %T')" "${depois:0:7}" >> "$LOG"
fi

# Bridge do Hermes: garante o `raw: true` no /send (patch de duas linhas,
# idempotente, com backup e restart unico do gateway quando acabou de aplicar).
[ -x "$DEST/hermes-bridge-raw.sh" ] && bash "$DEST/hermes-bridge-raw.sh" || true

# Units do systemd: se mudaram no branch, copia e recarrega. daemon-reload nao
# para o timer nem interrompe nada; so faz o systemd reler os arquivos.
unidades="$HOME/.config/systemd/user"
if [ -d "$unidades" ] && systemctl --user show-environment >/dev/null 2>&1; then
  mudou=0
  for arquivo in "$SRC"/tracknews-bridge/systemd/tracknews-bridge.*; do
    alvo="$unidades/$(basename "$arquivo")"
    if [ -f "$alvo" ] && ! cmp -s "$arquivo" "$alvo"; then
      install -m 0644 "$arquivo" "$alvo" && mudou=1
    fi
  done
  if [ "$mudou" = 1 ]; then
    systemctl --user daemon-reload 2>/dev/null \
      && printf '%s  units do systemd recarregadas\n' "$(date '+%F %T')" >> "$LOG"
  fi
fi
exit 0

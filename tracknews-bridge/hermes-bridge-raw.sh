#!/usr/bin/env bash
# Ensina o bridge.js do Hermes a aceitar `raw: true` no POST /send: com isso a
# ponte entrega o alerta EXATAMENTE como a nuvem escreveu, sem o cabecalho de
# self-chat ("⚕ *Hermes Agent*" + regua) que o bridge cola em toda mensagem.
#
# Patch minimo (duas linhas), idempotente e reversivel:
#   - guarda bridge.js.tracknews-bak antes de mexer;
#   - so aplica se as duas linhas esperadas existirem exatamente uma vez;
#   - reinicia o hermes-gateway UMA vez, so quando acabou de aplicar (o bridge
#     e filho do gateway e so recarrega o codigo ao subir). A sessao pareada
#     do WhatsApp fica em ~/.hermes/whatsapp/session e sobrevive ao restart --
#     os proprios logs do Hermes registram reinicios anteriores sem re-pareamento.
#
# Reverter:  cp ~/.hermes/hermes-agent/scripts/whatsapp-bridge/bridge.js.tracknews-bak \
#               ~/.hermes/hermes-agent/scripts/whatsapp-bridge/bridge.js \
#            && systemctl --user restart hermes-gateway.service
set -uo pipefail

DEST="${TRACKNEWS_BRIDGE_HOME:-$HOME/tracknews-bridge}"
LOG="$DEST/atualizar.log"
BRIDGE="${HERMES_BRIDGE_JS:-$HOME/.hermes/hermes-agent/scripts/whatsapp-bridge/bridge.js}"
MARCA="/* tracknews:raw */"

[ -f "$BRIDGE" ] || exit 0
grep -qF "$MARCA" "$BRIDGE" && exit 0        # ja aplicado

# As duas linhas que o patch toca, como estao no bridge.js do Hermes:
A='const { chatId, message, replyTo } = req.body;'
B='const chunks = splitLongMessage(formatOutgoingMessage(message));'
# B aparece no /send e no /edit; so o /send recebe `raw`. A so aparece no /send.
if [ "$(grep -cF "$A" "$BRIDGE")" != "1" ]; then
  printf '%s  hermes-bridge-raw: linha do /send nao encontrada exatamente uma vez; nada feito\n' "$(date '+%F %T')" >> "$LOG"
  exit 0
fi

cp -p "$BRIDGE" "$BRIDGE.tracknews-bak" || exit 0
python3 - "$BRIDGE" "$MARCA" <<'PY' || { cp -p "$BRIDGE.tracknews-bak" "$BRIDGE"; exit 0; }
import sys, pathlib
caminho, marca = pathlib.Path(sys.argv[1]), sys.argv[2]
fonte = caminho.read_text(encoding="utf-8")
a = "const { chatId, message, replyTo } = req.body;"
b = "const chunks = splitLongMessage(formatOutgoingMessage(message));"
i = fonte.index(a)
j = fonte.index(b, i)                       # o B do /send: o primeiro depois de A
if fonte.find("app.post('/edit'", i) != -1 and fonte.find("app.post('/edit'", i) < j:
    sys.exit("o primeiro B depois de A ja esta no /edit; layout inesperado")
novo = (fonte[:i]
        + "const { chatId, message, replyTo, raw } = req.body; " + marca
        + fonte[i + len(a):j]
        + "const chunks = splitLongMessage(raw ? String(message) : formatOutgoingMessage(message));"
        + fonte[j + len(b):])
caminho.write_text(novo, encoding="utf-8")
PY

if ! grep -qF "$MARCA" "$BRIDGE"; then
  printf '%s  hermes-bridge-raw: patch nao aplicado\n' "$(date '+%F %T')" >> "$LOG"
  exit 0
fi
if command -v node >/dev/null 2>&1 && ! node --check "$BRIDGE" >/dev/null 2>&1; then
  cp -p "$BRIDGE.tracknews-bak" "$BRIDGE"
  printf '%s  hermes-bridge-raw: bridge.js nao passou no node --check; revertido\n' "$(date '+%F %T')" >> "$LOG"
  exit 0
fi
printf '%s  hermes-bridge-raw: patch aplicado (backup em bridge.js.tracknews-bak)\n' "$(date '+%F %T')" >> "$LOG"

# Reinicia o gateway uma unica vez, para o bridge subir com o patch.
if systemctl --user is-active hermes-gateway.service >/dev/null 2>&1; then
  if systemctl --user restart hermes-gateway.service 2>/dev/null; then
    printf '%s  hermes-bridge-raw: hermes-gateway reiniciado para carregar o patch\n' "$(date '+%F %T')" >> "$LOG"
  else
    printf '%s  hermes-bridge-raw: nao consegui reiniciar o hermes-gateway; o patch vale no proximo boot\n' "$(date '+%F %T')" >> "$LOG"
  fi
fi
exit 0

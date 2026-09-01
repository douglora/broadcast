#!/usr/bin/env bash
# Descobre a API do bridge.js do Hermes -- o transporte de WhatsApp que ja esta
# pareado e vivo nesta maquina (porta 3000, ~/.hermes/whatsapp/session).
#
# ESTRITAMENTE SÓ LEITURA: lê o arquivo do bridge e faz GET em caminhos
# inofensivos. NÃO envia mensagem, não altera configuração do Hermes, não
# reinicia serviço, não pareia e não escaneia QR. Valores que pareçam chave,
# token ou telefone saem mascarados.
#
#   bash ~/tracknews-bridge/descobrir-hermes.sh
set -uo pipefail

mascara() {
  sed -E -e 's/(key|token|secret|senha|pass|apikey|authorization)([^A-Za-z0-9]{1,3})[A-Za-z0-9_\-\.]{8,}/\1\2<omitido>/Ig' \
         -e 's/[0-9]{10,}@(c\.us|s\.whatsapp\.net|g\.us)/<numero-omitido>/g'
}
titulo() { printf '\n===== %s =====\n' "$*"; }

BRIDGE=""
for c in "$HOME/.hermes/hermes-agent/scripts/whatsapp-bridge/bridge.js" \
         "$HOME/.hermes"/*/scripts/whatsapp-bridge/bridge.js; do
  [ -f "$c" ] && { BRIDGE="$c"; break; }
done
if [ -z "$BRIDGE" ]; then
  BRIDGE="$(find "$HOME/.hermes" -name 'bridge.js' -path '*whatsapp*' 2>/dev/null | head -1)"
fi

titulo "1. arquivo do bridge"
if [ -z "$BRIDGE" ] || [ ! -f "$BRIDGE" ]; then
  echo "bridge.js nao encontrado sob ~/.hermes"; exit 1
fi
echo "$BRIDGE"
echo "linhas: $(wc -l < "$BRIDGE")   modificado: $(date -r "$BRIDGE" '+%F %T' 2>/dev/null)"

titulo "2. rotas HTTP declaradas"
grep -nE "(app|router|server)\.(get|post|put|patch|delete|all)\s*\(\s*['\"\`][^'\"\`]+" "$BRIDGE" \
  | sed -E "s/^([0-9]+):.*(get|post|put|patch|delete|all)\s*\(\s*['\"\`]([^'\"\`]+).*/  linha \1  \U\2\E  \3/" \
  | mascara | head -30
# servidores http crus, sem Express
grep -nE "req\.url\s*={2,3}|pathname\s*={2,3}|case\s+['\"\`]/" "$BRIDGE" \
  | cut -c1-140 | mascara | head -15
echo "(fim das rotas)"

titulo "3. campos que o corpo do POST espera"
grep -nE "req\.body|JSON\.parse\(body|const\s*\{[^}]*\}\s*=\s*(req\.body|payload|data)" "$BRIDGE" \
  | cut -c1-160 | mascara | head -20

titulo "4. exige autenticacao?"
if grep -qniE "x-api-key|authorization|bearer|apiKey|AUTH_TOKEN" "$BRIDGE"; then
  grep -nE -i "x-api-key|authorization|bearer|apiKey|AUTH_TOKEN" "$BRIDGE" \
    | cut -c1-140 | mascara | head -10
else
  echo "nenhuma checagem de chave encontrada no codigo (provavelmente aberto em 127.0.0.1)"
fi

titulo "5. como o destino e identificado (chatId, jid, to...)"
grep -nE "chatId|chat_id|\bjid\b|remoteJid|['\"]to['\"]|groupId" "$BRIDGE" \
  | cut -c1-140 | mascara | head -15

titulo "6. o que o /health responde agora"
python3 - <<'PY' | mascara
import json, urllib.request
try:
    with urllib.request.urlopen("http://localhost:3000/health", timeout=3) as r:
        dados = json.loads(r.read(4000).decode("utf-8", "replace"))
    for chave, valor in dados.items():
        print(f"  {chave}: {valor}")
except Exception as erro:
    print(f"  falhou: {erro}")
PY

titulo "7. caminhos de leitura que existem (nenhum envia nada)"
python3 - <<'PY' | mascara
import urllib.error, urllib.request
caminhos = ["/", "/health", "/status", "/chats", "/groups", "/api/chats",
            "/api/groups", "/sessions", "/state", "/info", "/me", "/queue"]
for caminho in caminhos:
    try:
        with urllib.request.urlopen("http://localhost:3000" + caminho, timeout=3) as r:
            corpo = " ".join(r.read(200).decode("utf-8", "replace").split())
        print(f"  {caminho:14} HTTP {r.status}  {corpo[:110]}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  {caminho:14} HTTP {e.code}")
    except Exception:
        pass
PY

titulo "8. como o Hermes chama o proprio bridge (quem ja usa esta API)"
grep -rnE "localhost:3000|127\.0\.0\.1:3000" "$HOME/.hermes" --include='*.py' --include='*.js' \
  --include='*.json' --include='*.toml' --include='*.yaml' 2>/dev/null \
  | grep -v node_modules | cut -c1-150 | mascara | head -15

titulo "pronto"
echo "Cole esta saida na conversa. Com as rotas e o formato do corpo eu aponto a"
echo "ponte para este transporte -- o texto do alerta continua vindo pronto da"
echo "nuvem, byte a byte; o Hermes so carrega, nao reescreve."

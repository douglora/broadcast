#!/usr/bin/env bash
# Parte 6 -- estado do Hermes, com evidencia. SO LEITURA.
# Nao reinicia, nao repara, nao escaneia QR, nao mexe em sessao.
set -uo pipefail

echo "===== 1. servico ====="
if systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user status hermes-gateway --no-pager 2>&1 | head -20
  echo
  echo "--- reinicios recentes (sinal de crash-loop) ---"
  systemctl --user show hermes-gateway -p NRestarts -p ActiveState -p SubState \
    -p ExecMainStartTimestamp 2>/dev/null
else
  echo "(systemd de usuario indisponivel; nao da para afirmar nada sobre o servico)"
fi

echo
echo "===== 2. gateway na porta 3000 ====="
if curl -s -m 3 http://127.0.0.1:3000/ >/dev/null 2>&1; then
  echo "gateway :3000 OK"
else
  echo "gateway :3000 mudo"
fi

echo
echo "===== 3. ultimos erros ====="
if [[ -f "$HOME/.hermes/logs/gateway.error.log" ]]; then
  tail -20 "$HOME/.hermes/logs/gateway.error.log"
else
  echo "(sem ~/.hermes/logs/gateway.error.log)"
fi

echo
echo "===== 4. sessao do WhatsApp ====="
if [[ -d "$HOME/.hermes/whatsapp/session" ]]; then
  ls -la "$HOME/.hermes/whatsapp/session/" 2>/dev/null | head
  echo "--- idade dos arquivos de sessao ---"
  find "$HOME/.hermes/whatsapp/session" -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM  %f\n' \
    2>/dev/null | sort | tail -5
else
  echo "(sem ~/.hermes/whatsapp/session/ -> sessao nao pareada ou caminho diferente)"
fi

echo
echo "===== 5. ultima entrega registrada ====="
for arquivo in "$HOME/.hermes/logs/delivery.log" "$HOME/.hermes/logs/gateway.log"; do
  [[ -f "$arquivo" ]] && { echo "--- $arquivo ---"; tail -5 "$arquivo"; }
done
ls -1t "$HOME/.hermes/logs/" 2>/dev/null | head -10

echo
echo "Se o gateway estiver em crash-loop ou a sessao deslogada: APENAS RELATE."
echo "Nao reparar, nao reiniciar, nao escanear QR (limite de aparelhos vinculados)."

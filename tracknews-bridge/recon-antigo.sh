#!/usr/bin/env bash
# Parte 1 -- descobrir QUEM manda mensagem hoje para o grupo "AutoPilot News".
#
# ESTE SCRIPT SO OLHA. Ele nao para, nao desabilita, nao apaga e nao reinicia nada.
# Ele tambem nao imprime valores de variaveis, tokens, telefones nem ids de chat:
# nas buscas por conteudo usa `grep -l`, que mostra apenas o CAMINHO do arquivo.
#
#   bash recon-antigo.sh            > relatorio.txt
set -uo pipefail

titulo() { printf '\n===== %s =====\n' "$1"; }
filtro='waha|autopilot|auto-pilot|autopilot-news|grok|hermes|broadcast|whatsapp|noticia|news'

titulo "1. processos em execucao"
ps aux 2>/dev/null | grep -iE "$filtro" | grep -v -e grep -e recon-antigo || echo "(nenhum)"

titulo "2. systemd do usuario -- timers"
if systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user list-timers --all --no-pager 2>/dev/null | grep -iE "$filtro|NEXT" || echo "(nenhum)"
  echo "--- units ---"
  systemctl --user list-units --all --type=service --no-pager 2>/dev/null \
    | grep -iE "$filtro" || echo "(nenhuma)"
else
  echo "(systemd de usuario indisponivel)"
fi

titulo "3. systemd do sistema"
if command -v systemctl >/dev/null 2>&1; then
  systemctl list-units --all --type=service --no-pager 2>/dev/null | grep -iE "$filtro" || echo "(nenhuma)"
  systemctl list-timers --all --no-pager 2>/dev/null | grep -iE "$filtro" || echo "(nenhum timer)"
else
  echo "(sem systemctl)"
fi

titulo "4. cron"
crontab -l 2>/dev/null | grep -vE '^\s*#' | grep -E '\S' || echo "(crontab do usuario vazio)"
ls -1 /etc/cron.d /etc/cron.hourly /etc/cron.daily 2>/dev/null | grep -iE "$filtro" || true

titulo "5. containers docker"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null
  echo
  echo "--- NOMES (sem valores) das variaveis de ambiente dos containers do WAHA ---"
  for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -iE 'waha|whatsapp' || true); do
    echo "  container: $c"
    docker inspect "$c" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
      | cut -d= -f1 | sed 's/^/    /' | sort -u
    echo "    politica de restart: $(docker inspect "$c" --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null)"
  done
else
  echo "(docker indisponivel a partir daqui)"
fi

titulo "6. pm2 / node"
command -v pm2 >/dev/null 2>&1 && pm2 list 2>/dev/null || echo "(sem pm2)"

titulo "7. tarefas agendadas do Windows (leitura)"
if command -v schtasks.exe >/dev/null 2>&1; then
  schtasks.exe /query /fo CSV /nh 2>/dev/null | tr -d '\r' \
    | grep -iE "$filtro" | cut -d, -f1,3 || echo "(nenhuma com esses nomes)"
else
  echo "(schtasks.exe nao acessivel deste shell)"
fi
# $USER pode nao estar exportado (shell nao-login, unit, tarefa agendada); com
# set -u a referencia crua abortaria o script antes das secoes 8 e 9.
usuario_win="${USER:-$(id -un)}"
for pasta in "/mnt/c/Users/$usuario_win/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup" \
             "/mnt/c/ProgramData/Microsoft/Windows/Start Menu/Programs/StartUp"; do
  [[ -d "$pasta" ]] && { echo "--- $pasta ---"; ls -1 "$pasta" 2>/dev/null; }
done

titulo "8. arquivos que falam com o endpoint de envio do WAHA (so caminhos)"
echo "procurando por sendText / api/sendText / @g.us em \$HOME (sem imprimir conteudo)..."
timeout 180 grep -rlIE 'sendText|/api/send|@g\.us' "$HOME" \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv \
  --exclude-dir=__pycache__ --exclude-dir=.cache --exclude-dir=repo.git \
  2>/dev/null | head -60 || echo "(nada encontrado ou busca interrompida)"

titulo "9. o que fazer DEPOIS do OK do Douglas (nada disto foi executado)"
cat <<'FIM'
Formas reversiveis de desligar, por tipo. Escolha a linha do item que o Douglas apontar.

  systemd (usuario):
    desligar : systemctl --user disable --now NOME.timer
    religar  : systemctl --user enable  --now NOME.timer

  systemd (sistema):
    desligar : sudo systemctl disable --now NOME.service
    religar  : sudo systemctl enable  --now NOME.service

  container docker (parar sem apagar):
    desligar : docker update --restart=no NOME && docker stop NOME
    religar  : docker start NOME && docker update --restart=unless-stopped NOME

  tarefa agendada do Windows (PowerShell):
    desligar : Disable-ScheduledTask -TaskName "NOME"
    religar  : Enable-ScheduledTask  -TaskName "NOME"

  pm2:
    desligar : pm2 stop NOME && pm2 save
    religar  : pm2 start NOME && pm2 save

  cron (comentar a linha, nunca apagar):
    desligar : crontab -l > ~/crontab.bak && crontab -e   # prefixe a linha com '#'
    religar  : crontab ~/crontab.bak

Nunca: apagar container, apagar unit, apagar tarefa, apagar arquivo.
Nunca: mexer em qualquer coisa de autopilot-br ou broadcast-terminal.
Nunca: reiniciar, reparar ou reconfigurar o WAHA.
FIM

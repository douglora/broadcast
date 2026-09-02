#!/usr/bin/env bash
# Cutuca a nuvem quando o agendador do GitHub Actions falha.
#
# O cron "*/20 12-21 * * 1-5" do repo douglora/tracknews-autopilot deveria rodar
# 30 ciclos por dia util; na pratica o GitHub dispara 2 a 4 (buracos de horas).
# Sem ciclo nao ha coleta nem alerta novo, e o push chega horas atrasado. Este
# script roda a cada 10 min (ExecStartPre da ponte) e, se o ultimo ciclo gravado
# no branch state estiver velho, dispara o workflow pelo `gh` ja autenticado.
#
# Seguro por construcao:
#   - so no dia util e na janela do cron (12h-21h UTC = 9h-18h de Brasilia);
#   - nunca empilha: se ha run na fila ou rodando, nao dispara;
#   - no maximo um disparo a cada 20 min (marca em .cutucada);
#   - digest: se depois das 10h20 UTC (7h20 BRT) o branch state ainda nao tem
#     outputs/digest/<hoje>.md, dispara UMA vez com digest=true;
#   - qualquer falha e silenciosa (log em atualizar.log) e nao afeta a entrega.
set -uo pipefail

DEST="${TRACKNEWS_BRIDGE_HOME:-$HOME/tracknews-bridge}"
LOG="$DEST/atualizar.log"
REPO="douglora/tracknews-autopilot"
WORKFLOW="tracknews.yml"
MARCA="$DEST/.cutucada"
INTERVALO=1200          # 20 min entre disparos
CICLO_VELHO=1500        # 25 min sem commit no state = agendador falhou

log() { printf '%s  cutucar-nuvem: %s\n' "$(date '+%F %T')" "$1" >> "$LOG"; }

command -v gh >/dev/null 2>&1 || exit 0
timeout 30 gh auth status >/dev/null 2>&1 || exit 0

agora="$(date -u +%s)"
dia_semana="$(date -u +%u)"              # 1=segunda ... 7=domingo
hora="$((10#$(date -u +%H)))"
hhmm="$((10#$(date -u +%H%M)))"
[ "$dia_semana" -le 5 ] || exit 0

if [ -f "$MARCA" ]; then
  ultimo="$(cat "$MARCA" 2>/dev/null || echo 0)"
  [ $((agora - ${ultimo:-0})) -ge "$INTERVALO" ] || exit 0
fi

ciclo_falta=0
if [ "$hora" -ge 12 ] && [ "$hora" -le 21 ]; then
  ultimo_state="$(timeout 30 gh api "repos/$REPO/branches/state" \
                    --jq '.commit.commit.committer.date' 2>/dev/null || true)"
  if [ -n "$ultimo_state" ]; then
    ts="$(date -u -d "$ultimo_state" +%s 2>/dev/null || echo 0)"
    [ $((agora - ts)) -ge "$CICLO_VELHO" ] && ciclo_falta=1
  fi
fi

digest_falta=0
if [ "$hhmm" -ge 1020 ]; then
  hoje="$(TZ=America/Sao_Paulo date +%F)"
  if ! timeout 30 gh api "repos/$REPO/contents/outputs/digest/$hoje.md?ref=state" \
        --jq '.sha' >/dev/null 2>&1; then
    digest_falta=1
  fi
fi

[ "$ciclo_falta" = 1 ] || [ "$digest_falta" = 1 ] || exit 0

# Nao empilha: run na fila ou rodando conta como ciclo em andamento.
em_andamento="$(timeout 30 gh api "repos/$REPO/actions/workflows/$WORKFLOW/runs?per_page=5" \
  --jq '[.workflow_runs[] | select(.status != "completed")] | length' 2>/dev/null || echo "")"
[ "$em_andamento" = "0" ] || exit 0

quer_digest=false
[ "$digest_falta" = 1 ] && quer_digest=true
if timeout 60 gh workflow run "$WORKFLOW" -R "$REPO" --ref main -f "digest=$quer_digest" >/dev/null 2>&1; then
  echo "$agora" > "$MARCA"
  log "workflow disparado (ciclo_falta=$ciclo_falta digest=$quer_digest)"
else
  log "gh workflow run falhou (token sem escopo workflow? rede?)"
fi
exit 0

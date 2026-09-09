#!/usr/bin/env bash
# BROADCAST + sistema quant — a primeira carga de dados
#
# Clique duas vezes neste arquivo. Ele baixa 20 anos de precos da B3, os fundamentos
# da CVM, os fatores do NEFIN e o CDI, na ordem certa, e no fim confere o que chegou.
#
# DEMORA HORAS na primeira vez. Pode deixar rodando e ir fazer outra coisa: enquanto
# esta janela estiver aberta, o Mac nao adormece (o `caffeinate` cuida disso).
#
# Se a internet cair, ou se voce fechar a janela no meio, NAO se perde nada: cada
# coletor e idempotente. Clique duas vezes de novo e ele continua de onde parou.
#
# Tudo o que aparece na tela tambem vai para um arquivo de log, para voce poder mandar
# o resultado sem precisar de print.

cd "$(dirname "$0")" || exit 1

fim() {
  echo
  read -r -p "Pressione Enter para fechar esta janela."
  exit "${1:-0}"
}

echo "============================================================"
echo "  Primeira carga de dados — sistema quant"
echo "============================================================"
echo

# ── O ambiente isolado ───────────────────────────────────────
if [ ! -x ".venv/bin/python" ]; then
  echo "O ambiente isolado (.venv) nao existe nesta pasta."
  echo
  echo "Clique duas vezes em PREPARAR-MAC.command primeiro — ele instala tudo."
  echo "Depois volte aqui."
  fim 1
fi
PY=".venv/bin/python"

# ── Onde guardar o log ───────────────────────────────────────
mkdir -p quant/saida
LOG="quant/saida/carga_$(date +%Y%m%d_%H%M%S).log"
echo "O que aparecer aqui tambem esta sendo salvo em:"
echo "  $LOG"
echo

# ── caffeinate: impede o Mac de adormecer durante a carga ────
# Sem isso, um Mac que dorme no meio derruba o download e a carga fica pela metade.
# O -i so impede o adormecimento por inatividade; fechar a tampa ainda suspende.
CAFE=""
if command -v caffeinate >/dev/null 2>&1; then
  CAFE="caffeinate -i"
  echo "O Mac nao vai adormecer enquanto esta janela estiver aberta."
else
  echo "Aviso: nao achei o caffeinate. Se o Mac adormecer, a carga para —"
  echo "desligue o adormecimento em Ajustes do Sistema > Bateria."
fi
echo
echo "Comecando. Isso demora horas; pode minimizar a janela."
echo "Para interromper: Control + C (nada se perde, e so rodar de novo)."
echo

# ── A carga ──────────────────────────────────────────────────
# `set -o pipefail` para o codigo de saida ser o do python, nao o do tee.
set -o pipefail
$CAFE "$PY" -m quant.primeira_carga --continuar 2>&1 | tee "$LOG"
CODIGO=${PIPESTATUS[0]}

echo | tee -a "$LOG"
echo "============================================================" | tee -a "$LOG"
echo "  Conferindo o que chegou" | tee -a "$LOG"
echo "============================================================" | tee -a "$LOG"
echo | tee -a "$LOG"

"$PY" -m quant.dados.conferir 2>&1 | tee -a "$LOG"
CONFERIU=${PIPESTATUS[0]}

echo
echo "============================================================"
if [ "$CODIGO" = "0" ] && [ "$CONFERIU" = "0" ]; then
  echo "  Carga completa e banco conferido."
  echo "============================================================"
  echo
  echo "O proximo passo e o gate da fase 1 — o bloqueio duro do plano."
  echo "Ele reconstroi os fatores a partir dos SEUS dados e compara com o NEFIN."
  echo
  echo "Abra o Terminal nesta pasta e rode:"
  echo "  source .venv/bin/activate"
  echo "  python3 -m quant.validacao.replica_nefin --ini 2008 --fim 2026"
elif [ "$CODIGO" != "0" ]; then
  echo "  A carga nao terminou."
  echo "============================================================"
  echo
  echo "Faltou algum passo obrigatorio (o quadro acima diz qual)."
  echo "Na maioria das vezes e fonte fora do ar ou internet instavel:"
  echo "clique duas vezes neste arquivo de novo, que ele continua de onde parou."
  echo
  echo "Se falhar sempre no mesmo passo, me mande o arquivo:"
  echo "  $LOG"
else
  echo "  A carga terminou, mas a conferencia acusou problema."
  echo "============================================================"
  echo
  echo "NAO siga para o gate. O quadro acima diz o que falhou."
  echo "A falha mais grave e empresa deslistada faltando: ela nao quebra nada,"
  echo "so faz o backtest parecer melhor do que e."
  echo
  echo "Me mande o arquivo:"
  echo "  $LOG"
fi

fim 0

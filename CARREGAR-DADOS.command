#!/usr/bin/env bash
# BROADCAST + sistema quant — a primeira carga de dados
#
# Clique duas vezes neste arquivo. Ele baixa 20 anos de precos da B3, os fundamentos
# da CVM, os fatores do NEFIN e o CDI, na ordem certa, e no fim confere o que chegou.
#
# DEMORA HORAS na primeira vez. Pode deixar rodando e ir fazer outra coisa: enquanto
# esta janela estiver aberta, o Mac nao adormece (o `caffeinate` cuida disso).
#
# Se a internet cair, ou se voce fechar a janela no meio, NAO se perde nada: clique duas
# vezes de novo e ele retoma. Os dois passos maiores (os precos da B3 e a CVM) baixam um
# arquivo por ano e retomam PELOS ANOS QUE FALTAM, em vez de comecar do zero ou, pior, de
# se dar por prontos com um buraco no meio.
#
# Tudo o que aparece na tela tambem vai para um arquivo de log, para voce poder mandar
# o resultado sem precisar de print.

cd "$(dirname "$0")" || exit 1

# ── Pegar a versao mais recente do codigo ────────────────────
# Por que isto esta aqui: ate agora, atualizar exigia abrir o Terminal e digitar
# `git pull`. O Terminal e onde este projeto trava (colar no Mac e Command+V, e nao
# Ctrl+V; quem nao sabe ve a janela nao responder e conclui que o programa quebrou).
# Com este bloco, atualizar e carregar viram o mesmo duplo-clique.
#
# Tres cuidados, todos sobre nao piorar o que ja funciona:
#
#   - FALHA AQUI NAO IMPEDE O QUE VEM DEPOIS. Atualizar e conveniencia; preparar o Mac
#     e baixar os dados e que sao o trabalho. Sem internet, sem git, ou com alteracao
#     local, o bloco avisa e segue com o codigo que ja esta no disco.
#   - GIT_TERMINAL_PROMPT=0. Janela de duplo-clique nao tem ninguem olhando: se o git
#     resolver pedir usuario e senha, ela congela para sempre sem dizer por que. Assim
#     ele falha na hora, e o limite de velocidade minima aborta download travado em 20s.
#   - --ff-only. Havendo alteracao local, um `git pull` comum abriria um merge — talvez
#     um editor de texto dentro desta janela, que e o pior lugar possivel para descobrir
#     o que e um conflito. Recusar e seguir e melhor.
#
# E o `exec`: o bash le o arquivo do script conforme executa. Se o `git pull` trocasse
# ESTE arquivo no meio da execucao, o resto sairia embaralhado. Por isso a atualizacao e
# a primeira coisa que acontece e o script se reinicia em seguida, ja com o codigo novo.
ESTE="$(pwd)/$(basename "$0")"
if [ -z "$JA_ATUALIZOU" ] && [ -d ".git" ] && command -v git >/dev/null 2>&1; then
  echo "Buscando a versao mais recente do codigo..."
  if GIT_TERMINAL_PROMPT=0 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 \
       pull --ff-only --quiet 2>/dev/null; then
    echo "  atualizado."
  else
    echo "  nao deu para atualizar (sem internet, ou ha alteracao local nesta pasta)."
    echo "  Seguindo com a versao que ja esta no disco."
  fi
  echo
  JA_ATUALIZOU=1 exec "$ESTE"
fi

RAMO=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
VERSAO=$(git log -1 --format='%h %s' 2>/dev/null || echo "?")


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
# O cabecalho do log responde a primeira pergunta de qualquer diagnostico: em QUE versao
# do codigo isto rodou. Sem ele, so da para deduzir.
{
  echo "carga iniciada em $(date '+%Y-%m-%d %H:%M:%S')"
  echo "codigo: ramo $RAMO | commit $VERSAO"
  echo "maquina: $(uname -s) $(uname -r)"
  echo
} > "$LOG"
echo "Versao do codigo: $VERSAO"
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
$CAFE "$PY" -m quant.primeira_carga --continuar 2>&1 | tee -a "$LOG"
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

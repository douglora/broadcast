#!/usr/bin/env bash
# BROADCAST + sistema quant — preparacao do Mac
#
# Clique duas vezes neste arquivo UMA VEZ. Ele:
#   1. acha o Python 3 e confere a versao;
#   2. cria um ambiente isolado (.venv) dentro desta pasta;
#   3. instala tudo que o terminal e o sistema quant precisam;
#   4. roda os testes para provar que ficou funcionando.
#
# POR QUE O AMBIENTE ISOLADO. Do macOS Sonoma em diante, instalar biblioteca no
# Python do sistema da erro "externally-managed-environment" — a Apple protege o
# Python dela de propósito. O .venv e uma copia separada, so desta pasta, onde
# instalar e seguro. Ele fica fora do git e nao interfere em nada do seu Mac.
#
# Se algo der errado, a janela NAO fecha sozinha: leia a mensagem, ela diz o que fazer.

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


echo "============================================================"
echo "  BROADCAST + sistema quant — preparando este Mac"
echo "============================================================"
echo

fim() {
  echo
  read -r -p "Pressione Enter para fechar esta janela."
  exit "${1:-0}"
}

echo "Versao do codigo: $VERSAO (ramo $RAMO)"
echo

# ── 1. Python ────────────────────────────────────────────────
PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done

if [ -z "$PY" ]; then
  echo "Python 3 nao encontrado neste Mac."
  echo
  echo "Instale de um destes jeitos e rode este arquivo de novo:"
  echo
  echo "  A) Baixe o instalador oficial (mais simples):"
  echo "     https://www.python.org/downloads/macos/"
  echo "     Escolha a versao 3.12 ou 3.13, baixe o .pkg e instale."
  echo
  echo "  B) Se voce ja usa Homebrew:  brew install python@3.12"
  fim 1
fi

VERSAO=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
MENOR=$("$PY" -c 'import sys; print(1 if sys.version_info < (3,11) else 0)' 2>/dev/null)
echo "Python encontrado: $PY (versao $VERSAO)"

if [ "$MENOR" = "1" ]; then
  echo
  echo "Esta versao e antiga demais. O projeto precisa de Python 3.11 ou mais novo."
  echo "Baixe em https://www.python.org/downloads/macos/ e rode este arquivo de novo."
  fim 1
fi

# ── 2. Ambiente isolado ──────────────────────────────────────
if [ -d ".venv" ]; then
  echo "Ambiente .venv ja existe; vou reaproveitar."
else
  echo "Criando o ambiente isolado (.venv)..."
  if ! "$PY" -m venv .venv; then
    echo
    echo "Nao consegui criar o ambiente."
    echo "No Mac isso costuma ser falta das ferramentas de linha de comando."
    echo "Rode no Terminal:  xcode-select --install"
    echo "Depois aceite a instalacao e rode este arquivo de novo."
    fim 1
  fi
fi

VENV_PY=".venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "O ambiente foi criado mas o Python dele nao apareceu em $VENV_PY."
  echo "Apague a pasta .venv e rode este arquivo de novo."
  fim 1
fi

# ── 3. Dependencias ──────────────────────────────────────────
echo
echo "Instalando as bibliotecas. Isso demora alguns minutos na primeira vez."
echo

"$VENV_PY" -m pip install --upgrade pip --quiet

if ! "$VENV_PY" -m pip install -r requirements.txt; then
  echo
  echo "Falhou ao instalar as bibliotecas do terminal (flask e companhia)."
  echo "O motivo mais comum e falta de internet. Confira a conexao e tente de novo."
  fim 1
fi

if ! "$VENV_PY" -m pip install -r quant/requirements.txt; then
  echo
  echo "Falhou ao instalar as bibliotecas do sistema quant (pandas e companhia)."
  echo "Se a mensagem acima fala em compilar ou em 'wheel', rode no Terminal:"
  echo "  xcode-select --install"
  echo "e depois rode este arquivo de novo."
  fim 1
fi

# ── 4. Prova que funcionou ───────────────────────────────────
echo
echo "Instalado. Rodando os testes para conferir (leva uns 8 minutos)..."
echo

if "$VENV_PY" -m pytest quant/testes -q; then
  echo
  echo "============================================================"
  echo "  Tudo pronto."
  echo "============================================================"
  echo
  echo "A partir de agora:"
  echo
  echo "  - Para abrir o terminal e o painel:"
  echo "      clique duas vezes em INICIAR-TERMINAL.command"
  echo
  echo "  - Para rodar comandos do sistema quant, abra o Terminal nesta"
  echo "    pasta e use SEMPRE o Python do ambiente:"
  echo "      .venv/bin/python -m quant.primeira_carga"
  echo "      .venv/bin/python -m quant.dados.conferir"
  echo
  echo "  O passo a passo completo esta em quant/docs/no-mac-do-zero.md"
else
  echo
  echo "As bibliotecas instalaram, mas algum teste falhou."
  echo "Isso nao impede o terminal de abrir. Guarde a mensagem acima e me mostre."
fi

fim 0

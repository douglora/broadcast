#!/usr/bin/env bash
# BROADCAST - The Invest Post
# macOS: clique duas vezes neste arquivo.
# Linux: ./INICIAR-TERMINAL.command
cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "  BROADCAST - The Invest Post"
echo "============================================================"
echo

PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done

if [ -z "$PY" ]; then
  echo "Python nao encontrado neste computador."
  echo
  echo "macOS: instale com  brew install python"
  echo "       ou baixe em https://www.python.org/downloads/"
  echo
  read -r -p "Pressione Enter para fechar."
  exit 1
fi

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Buscando atualizacoes..."
  git pull --quiet 2>/dev/null || true
fi

echo "Iniciando o servidor. O navegador abre sozinho em alguns segundos."
echo "Para parar, aperte Ctrl+C."
echo
"$PY" app.py

echo
read -r -p "O servidor parou. Pressione Enter para fechar."

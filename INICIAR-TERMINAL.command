#!/usr/bin/env bash
# BROADCAST - The Invest Post
# macOS: clique duas vezes neste arquivo.
# Linux: ./INICIAR-TERMINAL.command
cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "  BROADCAST - The Invest Post"
echo "============================================================"
echo

# O ambiente isolado criado pelo PREPARAR-MAC.command vem primeiro: do macOS Sonoma em
# diante, instalar biblioteca no Python do sistema da "externally-managed-environment",
# entao e no .venv que as dependencias existem.
PY=""
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
fi

if [ -z "$PY" ]; then
  echo "Python nao encontrado neste computador."
  echo
  echo "macOS: clique duas vezes em PREPARAR-MAC.command (ele instala tudo),"
  echo "       ou baixe o Python em https://www.python.org/downloads/macos/"
  echo
  read -r -p "Pressione Enter para fechar."
  exit 1
fi

if [ "$PY" != ".venv/bin/python" ]; then
  echo "Aviso: rodando com o Python do sistema, sem o ambiente isolado."
  echo "Se aparecer erro de biblioteca faltando, clique duas vezes em"
  echo "PREPARAR-MAC.command uma vez e depois volte aqui."
  echo
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

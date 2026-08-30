@echo off
REM BROADCAST - The Invest Post
REM Clique duas vezes neste arquivo para abrir o terminal.
title BROADCAST - The Invest Post
cd /d "%~dp0"

echo ============================================================
echo   BROADCAST - The Invest Post
echo ============================================================
echo.

REM Procura o Python instalado
set PY=
where py >nul 2>&1 && set PY=py
if "%PY%"=="" (where python >nul 2>&1 && set PY=python)
if "%PY%"=="" (where python3 >nul 2>&1 && set PY=python3)

if "%PY%"=="" (
  echo Python nao encontrado neste computador.
  echo.
  echo Instale em https://www.python.org/downloads/
  echo IMPORTANTE: marque "Add Python to PATH" durante a instalacao.
  echo.
  pause
  exit /b 1
)

REM Busca a versao mais recente do repositorio (silencioso se nao houver git)
git rev-parse --is-inside-work-tree >nul 2>&1 && (
  echo Buscando atualizacoes...
  git pull --quiet 2>nul
)

echo Iniciando o servidor. O navegador abre sozinho em alguns segundos.
echo Para parar, feche esta janela ou aperte Ctrl+C.
echo.
%PY% app.py

echo.
echo O servidor parou. Pressione uma tecla para fechar.
pause >nul

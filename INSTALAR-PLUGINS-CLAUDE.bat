@echo off
REM BROADCAST - The Invest Post
REM Instala os plugins financeiros do Claude no Claude Code deste computador.
REM Clique duas vezes neste arquivo.
title BROADCAST - Plugins financeiros do Claude
cd /d "%~dp0"

echo ============================================================
echo   BROADCAST - Plugins financeiros do Claude
echo ============================================================
echo.

where claude >nul 2>&1
if errorlevel 1 (
  echo Claude Code nao encontrado neste computador.
  echo.
  echo Instale seguindo https://code.claude.com/docs/en/setup
  echo e clique neste arquivo de novo.
  echo.
  pause
  exit /b 1
)

echo Adicionando os marketplaces da Anthropic...
call claude plugin marketplace add anthropics/financial-services
call claude plugin marketplace add anthropics/claude-for-financial-advisors
echo.

for %%P in (financial-analysis equity-research market-researcher earnings-reviewer model-builder meeting-prep-agent) do (
  echo Instalando %%P...
  call claude plugin install %%P@claude-for-financial-services --scope user
)
echo Instalando claude-for-financial-advisors...
call claude plugin install claude-for-financial-advisors@claude-for-financial-advisors --scope user

echo.
echo Pronto. Os plugins valem em qualquer pasta deste computador.
echo Abra o Claude Code (comando: claude) e digite /financial-analysis:dcf para testar.
echo O guia de uso esta em GUIA-PLUGINS-CLAUDE.md.
echo.
pause

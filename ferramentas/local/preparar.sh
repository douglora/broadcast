#!/usr/bin/env bash
# BROADCAST - prepara a mesa para rodar no computador do Douglas (macOS ou Linux).
#
# Chamado pelo hook SessionStart de .claude/settings.json. Idempotente: na primeira
# vez cria o ambiente Python em .venv e instala as dependencias (cerca de 1 minuto);
# depois so confere (1 a 2 segundos). Na nuvem sai sem fazer nada.
#
# O que deixa pronto:
#   - `python3` passa a ser o do .venv (3.11 ou mais novo, com pandas, curl_cffi etc.),
#     entao os comandos das skills (`python3 mesa.py ...`, `python3 -m livro.portao`)
#     valem sem mudar uma letra. O Python do macOS e o 3.9 e nao serve.
#   - `gh` no PATH (fica em ~/.local/bin; neste Mac nao ha Homebrew, de proposito).
#   - branch `dados` buscado, para o `git show origin/dados:...` responder na hora.
#
# A mao: bash ferramentas/local/preparar.sh
cd "$(dirname "$0")/../.." || exit 0
RAIZ="$(pwd)"

# Na nuvem (Claude Code na web) nada disto se aplica.
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] && exit 0
[ "$RAIZ" = "/home/user/broadcast" ] && exit 0

export PATH="$HOME/.local/bin:$PATH"
avisos=""
aviso() { avisos="$avisos | $1"; }

versao_ok() { "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; }

# 1. Ambiente Python
if [ ! -x .venv/bin/python ] || ! versao_ok .venv/bin/python; then
  base=""
  for c in python3.13 python3.12 python3.11 python3; do
    p="$(command -v "$c" 2>/dev/null)" || continue
    if versao_ok "$p"; then base="$p"; break; fi
  done
  if [ -z "$base" ]; then
    aviso "LACUNA: nao achei Python 3.11 ou mais novo (o do macOS e 3.9); mesa.py funciona, livro.portao e a coleta local nao"
  elif command -v uv >/dev/null 2>&1; then
    uv venv --quiet --python "$base" .venv >/dev/null 2>&1 || aviso "LACUNA: uv venv falhou"
  else
    "$base" -m venv .venv >/dev/null 2>&1 || aviso "LACUNA: python -m venv falhou"
  fi
fi

# 2. Dependencias (so reinstala quando os requirements mudam)
if [ -x .venv/bin/python ]; then
  extras="yfinance lxml pytest openpyxl"
  marca="$(cat requirements.txt requirements-livro.txt 2>/dev/null | shasum 2>/dev/null | cut -d' ' -f1)-$extras"
  if [ "$(cat .venv/.mesa_deps 2>/dev/null)" != "$marca" ]; then
    if command -v uv >/dev/null 2>&1; then
      uv pip install --quiet --python .venv/bin/python -r requirements.txt -r requirements-livro.txt $extras >/dev/null 2>&1 \
        && echo "$marca" > .venv/.mesa_deps || aviso "LACUNA: instalacao das dependencias falhou (uv pip)"
    else
      .venv/bin/python -m pip install --quiet -r requirements.txt -r requirements-livro.txt $extras >/dev/null 2>&1 \
        && echo "$marca" > .venv/.mesa_deps || aviso "LACUNA: instalacao das dependencias falhou (pip)"
    fi
  fi
  [ -e .venv/bin/python3 ] || ln -s python .venv/bin/python3 2>/dev/null
fi

# 3. PATH das proximas chamadas de Bash desta sessao
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    printf 'export PATH="%s/.venv/bin:%s/.local/bin:$PATH"\n' "$RAIZ" "$HOME"
    printf 'export PYTHONIOENCODING=utf-8\n'
  } >> "$CLAUDE_ENV_FILE"
fi

# 4. Branch dados e gh
git fetch -q origin dados >/dev/null 2>&1 || aviso "LACUNA: git fetch origin dados falhou (sem rede?)"
if command -v gh >/dev/null 2>&1; then
  gh auth status >/dev/null 2>&1 && gh_txt="gh logado" || { gh_txt="gh SEM login"; aviso "rode: gh auth login"; }
else
  gh_txt="gh ausente"; aviso "LACUNA: sem gh nao ha disparo de workflow"
fi

py_txt="$(.venv/bin/python -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo ausente)"
ult="$(TZ=America/Sao_Paulo git log -1 --format=%cd --date=format-local:'%d/%m %Hh%M' origin/dados 2>/dev/null || echo '?')"
echo "MODO LOCAL (computador do Douglas, internet aberta): python3 = .venv ($py_txt); $gh_txt; branch dados de $ult. Vale a secao \"Modo local\" do CLAUDE.md: coleta direta (ferramentas/local/coletar.py), fita intradia (fita.py), disparo por gh (disparar.py).$avisos"
exit 0

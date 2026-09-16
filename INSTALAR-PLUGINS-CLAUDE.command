#!/usr/bin/env bash
# BROADCAST - The Invest Post
# Instala os plugins financeiros do Claude (Financial Services e Claude for
# Financial Advisors) no Claude Code deste computador, no escopo de usuario:
# depois disso os comandos valem em qualquer pasta, nao so nesta.
#
# macOS: clique duas vezes neste arquivo.
# Linux: ./INSTALAR-PLUGINS-CLAUDE.command
#
# Idempotente: o que ja esta instalado e so conferido. Com --quiet roda sem
# janela nem pausa e imprime uma linha de resumo (para o Claude na web, por
# exemplo: "rode bash INSTALAR-PLUGINS-CLAUDE.command --quiet").
cd "$(dirname "$0")" || exit 1

QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1
say()   { [ "$QUIET" = 0 ] && echo "$@"; return 0; }
pausa() { [ "$QUIET" = 0 ] && read -r -p "Pressione Enter para fechar."; return 0; }

say "============================================================"
say "  BROADCAST - Plugins financeiros do Claude"
say "============================================================"
say

if ! command -v claude >/dev/null 2>&1; then
  say "Claude Code nao encontrado neste computador."
  say
  say "Instale seguindo https://code.claude.com/docs/en/setup"
  say "e clique neste arquivo de novo."
  say
  [ "$QUIET" = 1 ] && echo "CLI 'claude' nao encontrada; nada instalado."
  pausa
  exit 1
fi

# nome-do-marketplace=repositorio-no-github
MARKETPLACES="claude-for-financial-services=anthropics/financial-services
claude-for-financial-advisors=anthropics/claude-for-financial-advisors"

# plugin@marketplace (o mesmo conjunto de enabledPlugins em .claude/settings.json)
PLUGINS="financial-analysis@claude-for-financial-services
equity-research@claude-for-financial-services
market-researcher@claude-for-financial-services
earnings-reviewer@claude-for-financial-services
model-builder@claude-for-financial-services
meeting-prep-agent@claude-for-financial-services
claude-for-financial-advisors@claude-for-financial-advisors"

installed="$(claude plugin list 2>/dev/null || true)"
missing=""
for p in $PLUGINS; do
  case "$installed" in
    *"$p"*) say "ok         $p" ;;
    *)      missing="$missing $p" ;;
  esac
done

if [ -z "$missing" ]; then
  say
  say "Tudo ja estava instalado. Nada a fazer."
  [ "$QUIET" = 1 ] && echo "Plugins financeiros do Claude: todos ja instalados."
  pausa
  exit 0
fi

known="$(claude plugin marketplace list 2>/dev/null || true)"
for m in $MARKETPLACES; do
  name="${m%%=*}"
  repo="${m#*=}"
  case "$known" in
    *"$name"*) ;;
    *)
      say "Adicionando marketplace $name ($repo)..."
      claude plugin marketplace add "$repo" >/dev/null 2>&1 || say "  nao consegui adicionar $name (sem internet?)"
      ;;
  esac
done

count=0
falhas=""
for p in $missing; do
  say "Instalando $p..."
  if claude plugin install "$p" --scope user >/dev/null 2>&1; then
    count=$((count + 1))
  else
    falhas="$falhas $p"
  fi
done

say
say "Instalados agora: $count."
[ -n "$falhas" ] && say "Nao instalaram (tente de novo com internet):$falhas"
say
say "Os plugins valem em qualquer pasta deste computador a partir da proxima"
say "sessao do Claude Code (ou apos /reload-plugins numa sessao aberta)."
say "Teste com /financial-analysis:dcf. O guia de uso esta em GUIA-PLUGINS-CLAUDE.md."
say
if [ "$QUIET" = 1 ]; then
  echo "Plugins financeiros do Claude instalados agora: $count.${falhas:+ Falharam:$falhas.} Valem na proxima sessao ou apos /reload-plugins."
fi
pausa
exit 0

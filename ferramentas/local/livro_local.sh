#!/usr/bin/env bash
# BROADCAST - roda o runner do livro AQUI, no computador do Douglas, sem o Actions.
#
# Para que serve: o livro ficou parado de 21 a 23/09/2026 porque o GitHub Actions
# travou, e o cron do Actions falhou de novo em 29 e 30/09. Com internet aberta, a
# mesa nao precisa ficar sem dado: este script copia o estado do livro do branch
# `dados` para `livro_out/previa/` e roda o mesmo runner (`python -m livro.rodar`).
#
#   bash ferramentas/local/livro_local.sh intradia      # ou: manha | fechamento | eventos
#
# E uma PREVIA: nada vai para o branch `dados` (so o Actions escreve la), os alertas
# daqui nao contam como entregues e o painel publicado so muda se a sessao republicar.
# Na resposta, diga sempre "previa local das HHhMM" e por que o Actions nao serviu.
# A leitura e a de sempre, trocando o caminho:
#   cat livro_out/previa/livro/saida/<modo>_cards.md   (fechamento_cards.md, manha_cards.md)
#   cat livro_out/previa/livro/saida/intradia.md
cd "$(dirname "$0")/../.." || exit 1
MODO="${1:-intradia}"
case "$MODO" in
  manha|intradia|fechamento|eventos) ;;
  *) echo "modo invalido: $MODO (use manha, intradia, fechamento ou eventos)"; exit 2 ;;
esac
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
# A SEC exige User-Agent com forma de contato; mesmo padrao sem dado pessoal do livro.yml.
export SEC_USER_AGENT="${SEC_USER_AGENT:-BROADCAST Livro (contato admin@theinvestpost.local)}"
export TZ=America/Sao_Paulo

git fetch -q origin dados 2>/dev/null || echo "LACUNA: git fetch origin dados falhou; uso o estado ja baixado"
mkdir -p livro_out/previa
if ! git archive origin/dados livro 2>/dev/null | tar -x -C livro_out/previa; then
  echo "LACUNA: nao consegui copiar o estado do livro do branch dados"; exit 1
fi
echo "previa local do livro, modo $MODO, iniciada as $(TZ=America/Sao_Paulo date +%Hh%M) de Brasilia (leva de 1 a 3 minutos)"
"$PY" -m livro.rodar --modo "$MODO" --saida livro_out/previa/livro --run-id "local-$(date +%s)" || {
  echo "FALHOU: o runner local terminou com erro; veja a mensagem acima"; exit 1; }
echo "PREVIA PRONTA em livro_out/previa/livro/saida/ (nao publicada no branch dados)"

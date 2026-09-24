"""Modo do livro a partir do cron que disparou o workflow.

O `case` do livro.yml casava a string exata do cron. Quando os crons mudaram para
08h20 e 18h05 BRT (PR #51), o `case` continuou com as strings antigas e as duas
rodadas agendadas mais importantes cairiam no `*) MODO=intradia` (achado da
auditoria de 23/09). Aqui o modo sai da HORA UTC do cron, que e o que importa:
mudar o minuto nao quebra mais nada.

Uso no workflow:  MODO=$(python -m livro.agenda_modo "$AGENDA")
"""
from __future__ import annotations

import sys

HORA_FECHAMENTO_UTC = 21   # 18h BRT: depois do fechamento da B3
HORA_MANHA_UTC = 11        # 08h BRT: antes da abertura da B3


def modo_do_cron(cron: str) -> str:
    campos = (cron or "").split()
    if len(campos) < 2:
        return "intradia"
    hora = campos[1]
    if hora.isdigit():
        h = int(hora)
        if h == HORA_FECHAMENTO_UTC:
            return "fechamento"
        if h == HORA_MANHA_UTC:
            return "manha"
    return "intradia"


if __name__ == "__main__":
    print(modo_do_cron(sys.argv[1] if len(sys.argv) > 1 else ""))

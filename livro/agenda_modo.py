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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BRT = ZoneInfo("America/Sao_Paulo")

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


def modo_efetivo(cron: str, agora: datetime | None = None) -> str:
    """Modo pela hora em que a rodada agendada DE FATO dispara.

    O cron do GitHub atrasa: em 24/09 o de 08h20 BRT saiu as 12h49, rodou como
    "manha" no meio do pregao e trocou o slot do manifest. Rodada atrasada vale pelo
    relogio de agora: manha depois das 09h45 vira intradia (a B3 abre as 10h);
    fechamento que escorregou para o pregao seguinte vira intradia; intradia fora do
    pregao (antes das 09h30 ou depois das 18h00) vira eventos (so noticia, CVM e SEC),
    para nao sobrescrever o fechamento com uma coleta de fora do horario."""
    modo = modo_do_cron(cron)
    agora = (agora or datetime.now(timezone.utc)).astimezone(BRT)
    minutos = agora.hour * 60 + agora.minute
    if modo == "manha" and minutos >= 9 * 60 + 45:
        modo = "intradia"
    if modo == "fechamento" and 9 * 60 <= minutos < 18 * 60:
        modo = "intradia"
    if modo == "intradia" and (minutos < 9 * 60 + 30 or minutos >= 18 * 60):
        modo = "eventos"
    return modo


if __name__ == "__main__":
    print(modo_efetivo(sys.argv[1] if len(sys.argv) > 1 else ""))

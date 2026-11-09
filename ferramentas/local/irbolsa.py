#!/usr/bin/env python3
"""Contador de bolsa do Douglas: apuracao do mes, relatorio mensal, DARF e rotina diaria (no lugar da IRTrade).

O motor vive em ferramentas/local/contador_bolsa/ (notas -> carteira -> apuracao -> mes -> relatorio e DARF). As
notas de corretagem e de aluguel chegam pelo e-mail do Safra; proventos, aluguel e a conciliacao vem do Open Finance
que o terminal le as 8h e as 19h. Dado do titular fica em ~/.autopilot/contador-bolsa/<titular>/ (nunca no git,
nunca em Artifact). A conversa e a rotina seguem a skill `contador-bolsa`.

    python3 ferramentas/local/irbolsa.py apurar                  # mes em curso, se fechasse hoje
    python3 ferramentas/local/irbolsa.py apurar 2026-10          # um mes, sem gravar nada
    python3 ferramentas/local/irbolsa.py fechar 2026-10          # grava, gera o relatorio e o DARF em PDF
    python3 ferramentas/local/irbolsa.py diario                  # rotina: fecha, revisa, alerta, monta e-mails
    python3 ferramentas/local/irbolsa.py email 2026-10           # arquivo do e-mail do fechamento
    python3 ferramentas/local/irbolsa.py enviado <email.json> --raw <raw.txt>
    python3 ferramentas/local/irbolsa.py pago 2026-10 2026-11-25 # DARF pago fora da conta do Safra
    python3 ferramentas/local/irbolsa.py busca                   # consulta do Gmail das notas novas
    python3 ferramentas/local/irbolsa.py importar-email <raw.txt> --id <id>

Senhas dos PDFs, como na IRTrade: relatorio = 4 primeiros digitos do CPF; DARF = 5 primeiros.
"""

from __future__ import annotations

import pathlib
import sys

AQUI = pathlib.Path(__file__).resolve().parent
for p in (AQUI, AQUI.parent.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from contador_bolsa.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())

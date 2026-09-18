#!/usr/bin/env python3
"""Ponto de entrada do workflow do livro.

    python -m livro.rodar --modo fechamento --saida dados_branch/livro --run-id 123
    python -m livro.rodar --modo ack --ids-entregues "T01-BBDC4-perda-2026-09-18,C01-DI-abriu-2026-09-18" --saida dados_branch/livro
    python -m livro.rodar --modo fechamento --saida livro_out --offline tests/fixtures   # sem rede

Modos: intradia | fechamento | manha | ack | sonda | backfill | fimdesemana.
Sai com 0 quando gravou algo (falha de perna e dado declarado); 1 so quando nada
foi escrito."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from livro import coletar

MODOS = ("intradia", "fechamento", "manha", "ack", "sonda", "backfill", "fimdesemana")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", default="intradia", choices=MODOS)
    ap.add_argument("--saida", default="livro_out")
    ap.add_argument("--ids-entregues", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--dias-backfill", type=int, default=10)
    ap.add_argument("--simbolos-extra", default="")
    ap.add_argument("--offline", default=None, help="pasta de fixtures (tests/fixtures) para rodar sem rede")
    ap.add_argument("--agora", default=None, help="instante UTC ISO para testes (ex.: 2026-09-18T21:40:00Z)")
    args = ap.parse_args(argv)

    agora = None
    if args.agora:
        agora = datetime.fromisoformat(args.agora.replace("Z", "+00:00")).astimezone(timezone.utc)
    modo = "fechamento" if args.modo in ("fimdesemana", "backfill") else args.modo
    if args.modo == "backfill":
        modo = "backfill"
    extra = [s.strip() for s in args.simbolos_extra.replace(";", ",").split(",") if s.strip()]
    try:
        m = coletar.executar(modo, args.saida, ids_entregues=args.ids_entregues, run_id=args.run_id,
                             dias_backfill=args.dias_backfill, offline=args.offline, agora=agora, simbolos_extra=extra)
    except Exception as e:  # noqa: BLE001
        print(f"FALHA GERAL: {type(e).__name__}: {e}", file=sys.stderr)
        raise
    print(json.dumps({k: m.get(k) for k in ("slot", "gerado_em_brt", "data_pregao", "pernas", "alertas", "render", "duracao_s")},
                     ensure_ascii=False, indent=1))
    return 0 if os.path.exists(os.path.join(args.saida, "saida", "manifest.json")) else 1


if __name__ == "__main__":
    sys.exit(main())

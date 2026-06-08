"""CLI do agente. Fluxo: collect -> propose (Gate 1) -> draft (Gate 2)."""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(__file__))
SAMPLE = os.path.join(HERE, "sample_snapshot.json")


def _load_config(path: str | None) -> dict:
    candidates = ([path] if path else []) + [
        os.path.join(HERE, "config.json"),
        os.path.join(HERE, "config.example.json"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            with open(c, encoding="utf-8") as f:
                return json.load(f)
    return {}


def _load_snapshot(arg: str | None) -> tuple[dict, str]:
    from .collect import latest_snapshot_path
    path = arg or latest_snapshot_path() or SAMPLE
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


def cmd_collect(args):
    from .broadcast_client import BroadcastClient
    from .collect import collect_snapshot, save_snapshot

    cfg = _load_config(args.config)
    base = cfg.get("broadcast_base_url", "")
    if not base or "SEU-TUNEL-AQUI" in base:
        sys.exit("Defina broadcast_base_url em config.json (copie de config.example.json).")
    snap = collect_snapshot(BroadcastClient(base, timeout=cfg.get("timeout", 10)))
    path = save_snapshot(snap)
    print(f"Snapshot salvo em {path}")
    if snap.get("errors"):
        print(f"Avisos (endpoints que falharam): {', '.join(snap['errors'])}")


def cmd_propose(args):
    from .propose import propose_pautas, render_brief
    snap, path = _load_snapshot(args.snapshot)
    if path == SAMPLE:
        print("[aviso] usando sample_snapshot.json (dados ilustrativos). "
              "Rode 'collect' para dados reais.\n")
    print(render_brief(propose_pautas(snap)))


def cmd_draft(args):
    from .draft import DEFAULT_EFFORT, DEFAULT_MODEL, draft_post, render_prompt_only
    from .propose import find_pauta

    cfg = _load_config(args.config)
    snap, _ = _load_snapshot(args.snapshot)
    pauta = find_pauta(snap, args.pauta)
    if not pauta:
        sys.exit(f"Pauta '{args.pauta}' não encontrada. Rode 'propose' para ver os ids.")

    if args.prompt_only or not os.environ.get("ANTHROPIC_API_KEY"):
        if not args.prompt_only:
            print("[aviso] ANTHROPIC_API_KEY ausente — modo prompt-only.\n", file=sys.stderr)
        print(render_prompt_only(pauta))
        return

    model = args.model or cfg.get("model", DEFAULT_MODEL)
    effort = args.effort or cfg.get("effort", DEFAULT_EFFORT)
    print(draft_post(pauta, model=model, effort=effort))


def main(argv=None):
    p = argparse.ArgumentParser(prog="agent", description="BROADCAST → rascunhos de LinkedIn")
    p.add_argument("--config", help="caminho do config.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="coleta um snapshot do servidor BROADCAST")
    c.set_defaults(func=cmd_collect)

    pr = sub.add_parser("propose", help="Gate 1: sugere pautas a partir de um snapshot")
    pr.add_argument("--snapshot", help="caminho do snapshot (default: mais recente ou sample)")
    pr.set_defaults(func=cmd_propose)

    d = sub.add_parser("draft", help="Gate 2: rascunha o post da pauta escolhida")
    d.add_argument("--pauta", required=True, help="id da pauta (ex.: p2)")
    d.add_argument("--snapshot", help="caminho do snapshot")
    d.add_argument("--model", help="modelo (default em config / claude-opus-4-8)")
    d.add_argument("--effort", help="effort: low|medium|high|max (default high)")
    d.add_argument("--prompt-only", action="store_true", help="não chama a API; imprime o prompt")
    d.set_defaults(func=cmd_draft)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

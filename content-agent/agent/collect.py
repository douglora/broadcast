"""Coletor: tira um snapshot dos dados do BROADCAST e salva em data/."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .broadcast_client import BroadcastClient

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Endpoint sem argumento -> chave no snapshot
_ENDPOINTS = ("quotes", "indicators", "di", "alerts", "cvm", "weekly_summary", "watchlist")


def collect_snapshot(client: BroadcastClient) -> dict:
    """Bate em cada endpoint. Um que falhe não derruba o snapshot inteiro."""
    snap: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "errors": {}}
    for key in _ENDPOINTS:
        try:
            snap[key] = getattr(client, key)()
        except Exception as e:
            snap[key] = None
            snap["errors"][key] = str(e)
    return snap


def save_snapshot(snap: dict, data_dir: str = DATA_DIR) -> str:
    os.makedirs(data_dir, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(data_dir, f"snapshot-{day}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    return path


def latest_snapshot_path(data_dir: str = DATA_DIR) -> str | None:
    if not os.path.isdir(data_dir):
        return None
    snaps = sorted(
        p for p in os.listdir(data_dir)
        if p.startswith("snapshot-") and p.endswith(".json")
    )
    return os.path.join(data_dir, snaps[-1]) if snaps else None

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
RETENTION_DAYS = 60


def load(path: Path) -> dict:
    if not path.exists():
        return {"seen": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def filter_new(state: dict, items: list[dict]) -> list[dict]:
    seen = state.setdefault("seen", {})
    return [item for item in items if item["id"] not in seen]


def mark_seen(state: dict, items: list[dict]) -> None:
    seen = state.setdefault("seen", {})
    now = dt.datetime.now(KST).isoformat()
    for item in items:
        seen[item["id"]] = now


def prune(state: dict) -> None:
    seen = state.setdefault("seen", {})
    cutoff = dt.datetime.now(KST) - dt.timedelta(days=RETENTION_DAYS)
    for key in list(seen.keys()):
        try:
            recorded = dt.datetime.fromisoformat(seen[key])
        except ValueError:
            del seen[key]
            continue
        if recorded < cutoff:
            del seen[key]

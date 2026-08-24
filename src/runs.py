from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_PATH = BASE_DIR / ".local" / "runs.json"
MAX_RUNS = 30


def append(entry: dict) -> None:
    RUNS_PATH.parent.mkdir(mode=0o700, exist_ok=True)
    runs = recent()
    entry = {"at": dt.datetime.now(KST).isoformat(), **entry}
    runs.insert(0, entry)
    runs = runs[:MAX_RUNS]
    RUNS_PATH.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")


def recent() -> list[dict]:
    if not RUNS_PATH.exists():
        return []
    return json.loads(RUNS_PATH.read_text(encoding="utf-8"))

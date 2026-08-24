from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_DIR = BASE_DIR / ".local"
PREFS_PATH = LOCAL_DIR / "prefs.json"


DEFAULTS = {
    "course_ids": None,
    "types": None,
    "known_courses": [],
    "poll_minutes": None,
    "schedule_mode": "off",  # "off" | "interval" | "fixed"
    "fixed_times": [],  # ["09:00", "18:00"] 형식, KST 기준 매일
}


def load() -> dict:
    if not PREFS_PATH.exists():
        return dict(DEFAULTS)
    data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    for key, value in DEFAULTS.items():
        data.setdefault(key, value)
    return data


def save(data: dict) -> None:
    LOCAL_DIR.mkdir(mode=0o700, exist_ok=True)
    PREFS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(PREFS_PATH, 0o600)


def set_filters(course_ids: list[str] | None, types: list[str] | None) -> dict:
    data = load()
    data["course_ids"] = course_ids
    data["types"] = types
    save(data)
    return data


def set_known_courses(courses: list[dict]) -> dict:
    data = load()
    data["known_courses"] = courses
    save(data)
    return data


def set_schedule(mode: str, poll_minutes: int | None, fixed_times: list[str]) -> dict:
    data = load()
    data["schedule_mode"] = mode
    data["poll_minutes"] = poll_minutes
    data["fixed_times"] = fixed_times
    save(data)
    return data

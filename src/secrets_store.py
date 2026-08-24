from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_DIR = BASE_DIR / ".local"
SECRETS_PATH = LOCAL_DIR / "secrets.json"


def _ensure_dir() -> None:
    LOCAL_DIR.mkdir(mode=0o700, exist_ok=True)


def load() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    return json.loads(SECRETS_PATH.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    _ensure_dir()
    SECRETS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(SECRETS_PATH, 0o600)


def set_account(student_id: str, password: str) -> None:
    data = load()
    data["account"] = {"student_id": student_id, "password": password}
    save(data)


def clear_account() -> None:
    data = load()
    data.pop("account", None)
    save(data)


def get_account() -> dict | None:
    return load().get("account")


def set_telegram(bot_token: str, chat_id: str) -> None:
    data = load()
    data["telegram"] = {"bot_token": bot_token, "chat_id": chat_id}
    save(data)


def clear_telegram() -> None:
    data = load()
    data.pop("telegram", None)
    save(data)


def get_telegram() -> dict | None:
    return load().get("telegram")


def mask_id(student_id: str) -> str:
    if len(student_id) <= 4:
        return student_id
    return f"{student_id[:2]}{'*' * (len(student_id) - 4)}{student_id[-2:]}"

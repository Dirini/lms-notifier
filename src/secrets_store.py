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
    try:
        os.chmod(SECRETS_PATH, 0o600)
    except (OSError, NotImplementedError):
        pass  # 윈도우에는 POSIX 권한이 없다 — 실패해도 저장 자체는 계속한다


def set_account(student_id: str, password: str) -> None:
    """한동대 SSO 방식 — 학번/비밀번호로 로그인한다."""
    data = load()
    data["account"] = {"mode": "handong", "student_id": student_id, "password": password}
    save(data)


def set_token_account(base_url: str, token: str, label: str = "") -> None:
    """Canvas 액세스 토큰 방식 — 어느 Canvas 학교든 되고, 비밀번호를 저장하지 않는다."""
    data = load()
    data["account"] = {"mode": "canvas", "base_url": base_url, "token": token, "label": label}
    save(data)


def clear_account() -> None:
    data = load()
    data.pop("account", None)
    save(data)


def get_account() -> dict | None:
    account = load().get("account")
    if account and "mode" not in account:
        account["mode"] = "handong"   # 토큰 방식이 생기기 전에 저장된 계정
    return account


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


def mask_token(token: str) -> str:
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}{'*' * 6}{token[-4:]}"

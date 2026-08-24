from __future__ import annotations

import requests

TELEGRAM_MAX_LEN = 4096


def send_message(bot_token: str, chat_id: str, text: str) -> None:
    """텔레그램으로 메시지를 보낸다. 4096자 제한을 넘으면 여러 통으로 나눠 보낸다."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for chunk in _split(text, TELEGRAM_MAX_LEN):
        resp = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"텔레그램 전송 실패: {resp.status_code} {resp.text}")


def _split(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    lines = text.split("\n")
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def get_latest_chat_id(bot_token: str) -> str | None:
    """봇에게 /start 를 보낸 사람들 중 가장 최근 chat_id를 알아낸다 (설정용 헬퍼)."""
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("result", [])
    if not results:
        return None
    last = results[-1]
    chat = (last.get("message") or {}).get("chat") or {}
    chat_id = chat.get("id")
    return str(chat_id) if chat_id is not None else None

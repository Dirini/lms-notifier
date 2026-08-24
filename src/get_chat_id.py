from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
import os

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        print("먼저 .env에 TELEGRAM_BOT_TOKEN을 설정하세요.", file=sys.stderr)
        return 2

    print("텔레그램에서 봇을 찾아 아무 메시지나 (예: /start) 보낸 뒤 Enter를 누르세요...")
    input()

    chat_id = telegram.get_latest_chat_id(bot_token)
    if chat_id is None:
        print("아직 메시지를 받지 못했습니다. 봇에게 메시지를 보냈는지 확인하고 다시 시도하세요.", file=sys.stderr)
        return 1

    print(f"당신의 chat_id: {chat_id}")
    print("이 값을 .env의 TELEGRAM_CHAT_ID에 넣으세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

import lms_client
import prefs
import secrets_store
import state as state_mod
import telegram

KST = ZoneInfo("Asia/Seoul")
BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "state.json"

TYPE_LABELS = {
    "assignment": "과제",
    "quiz": "퀴즈",
    "calendar_event": "일정",
    "discussion_topic": "토론",
    "planner_note": "메모",
    "announcement": "공지",
}


WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]

# 캔버스 마감시각이 23:59나 00:00이면 실제 "몇시 몇분"이 아니라 "그날 하루" 대신 넣은
# 기본값인 경우가 대부분이라, 이때는 시각을 생략하고 날짜만 보여준다.
_NO_MEANINGFUL_TIME = {(23, 59), (0, 0)}


def format_due(iso_date: str) -> str:
    parsed = dt.datetime.fromisoformat(iso_date).astimezone(KST)
    weekday = WEEKDAY_KO[parsed.weekday()]
    date_part = f"{parsed.month}월 {parsed.day}일 {weekday}요일"

    if (parsed.hour, parsed.minute) in _NO_MEANINGFUL_TIME:
        return date_part

    period = "오전" if parsed.hour < 12 else "오후"
    hour_12 = parsed.hour % 12 or 12
    time_part = f"{period} {hour_12}시" + (f" {parsed.minute}분" if parsed.minute else "")
    return f"{date_part} {time_part}"


def _format_detailed(new_schedule: list[dict], new_announcements: list[dict]) -> str:
    """분류·과목·마감시각·제출여부까지 담는다."""
    lines = ["LMS 새 소식"]
    if new_schedule:
        lines.append("")
        lines.append("[일정/과제]")
        for item in new_schedule:
            label = TYPE_LABELS.get(item["type"], item["type"])
            course = f" ({item['course']})" if item.get("course") else ""
            submitted = " - 제출됨" if item.get("submitted") else ""
            lines.append(f"- [{label}] {format_due(item['date'])} {item['title']}{course}{submitted}")
    if new_announcements:
        lines.append("")
        lines.append("[공지사항]")
        for item in new_announcements:
            course = f" ({item['course']})" if item.get("course") else ""
            lines.append(f"- {format_due(item['date'])} {item['title']}{course}")
    return "\n".join(lines)


def _format_simple(new_schedule: list[dict], new_announcements: list[dict]) -> str:
    """한 줄에 하나씩. 이미 제출한 항목은 빼서 할 일만 남긴다.

    제목만으로는 어느 수업 건인지 알 수 없어서 과목명을 함께 붙인다 —
    분류·제출 여부처럼 없어도 되는 것만 덜어내는 게 '간단히'의 목적이다."""
    pending = [i for i in new_schedule if not i.get("submitted")]
    counts = []
    if pending:
        counts.append(f"할 일 {len(pending)}")
    if new_announcements:
        counts.append(f"공지 {len(new_announcements)}")
    lines = ["LMS " + (" · ".join(counts) if counts else "새 소식")]
    for item in pending + new_announcements:
        course = f" ({item['course']})" if item.get("course") else ""
        lines.append(f"· {format_due(item['date'])} {item['title']}{course}")
    if not pending and not new_announcements:
        # 새 일정이 전부 제출 완료라 보여줄 게 없을 때
        lines.append("· 새로 생긴 항목이 모두 제출 완료 상태예요")
    return "\n".join(lines)


def format_message(new_schedule: list[dict], new_announcements: list[dict],
                   message_format: str = "detailed") -> str:
    if message_format == "simple":
        return _format_simple(new_schedule, new_announcements)
    return _format_detailed(new_schedule, new_announcements)


def run(days: int, dry_run: bool) -> int:
    account = secrets_store.get_account() or {}
    telegram_cfg = secrets_store.get_telegram() or {}

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or telegram_cfg.get("bot_token", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or telegram_cfg.get("chat_id", "")

    student_id = os.environ.get("HGU_ID", "").strip() or account.get("student_id", "")
    password = os.environ.get("HGU_PASSWORD", "") or account.get("password", "")

    if not student_id or not password:
        print("LMS 계정 정보가 없습니다. 웹 화면(src/server.py)에서 먼저 연결하거나, "
              ".env에 HGU_ID/HGU_PASSWORD를 설정하세요.", file=sys.stderr)
        return 2

    if not dry_run and (not bot_token or not chat_id):
        print("텔레그램 정보가 없습니다. .env에 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID를 설정하거나, 웹 UI에서 먼저 연결하세요.", file=sys.stderr)
        return 2

    try:
        session = lms_client.login(student_id, password)
    except lms_client.LMSLoginError as exc:
        print(f"LMS 로그인 실패: {exc}", file=sys.stderr)
        return 1

    schedule, announcements = lms_client.fetch_all(session, days)
    filters = prefs.load()
    schedule = lms_client.apply_filters(schedule, filters["course_ids"], filters["types"])
    announcements = lms_client.apply_filters(announcements, filters["course_ids"], filters["types"])

    state = state_mod.load(STATE_PATH)
    new_schedule = state_mod.filter_new(state, schedule)
    new_announcements = state_mod.filter_new(state, announcements)

    if not new_schedule and not new_announcements:
        print("새로운 일정/공지 없음")
        return 0

    message = format_message(new_schedule, new_announcements,
                             filters.get("message_format", "detailed"))
    print(message)

    if dry_run:
        print("\n(dry-run: 텔레그램 전송 및 상태 저장 생략)")
        return 0

    telegram.send_message(bot_token, chat_id, message)

    state_mod.mark_seen(state, new_schedule + new_announcements)
    state_mod.prune(state)
    state_mod.save(STATE_PATH, state)
    return 0


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    parser = argparse.ArgumentParser(description="한동대 LMS 일정/공지 텔레그램 알리미")
    parser.add_argument("--days", type=int, default=int(os.environ.get("DAYS_AHEAD", "7")))
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 결과만 출력")
    args = parser.parse_args()
    return run(args.days, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

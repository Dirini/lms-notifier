from __future__ import annotations

import base64
import datetime as dt
import html
import json
import re
import sys
import time
from contextlib import contextmanager
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

KST = ZoneInfo("Asia/Seoul")
REQUEST_TIMEOUT = 15  # 초. 각 단계는 이 시간 안에 응답이 와야 한다 (학교 서버가 느리면 여기서 걸린다).
SESSION_TTL = 25 * 60  # noqa: E262
HANDONG_BASE = "https://lms.handong.edu"


def base_of(session: requests.Session) -> str:
    """이 세션이 바라보는 학교 Canvas 주소. 로그인 방식과 무관하게 세션에 붙여 둔다."""
    return getattr(session, "base_url", HANDONG_BASE)


def normalize_base(raw: str) -> str:
    """사용자가 붙여넣는 형태(`lms.handong.edu`, `https://lms.handong.edu/`,
    `https://lms.handong.edu/courses` 등)를 API 호출에 쓸 origin 으로 정리한다."""
    value = (raw or "").strip()
    if not value:
        raise ValueError("학교 LMS 주소를 입력하세요")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("https:// 로 시작하는 학교 LMS 주소를 입력하세요")
    return f"https://{parsed.netloc}"


def token_session(base_url: str, token: str) -> requests.Session:
    """Canvas 개인 액세스 토큰으로 붙는다. 학교 SSO 를 거치지 않으므로 어느 Canvas 학교든 동작하고,
    비밀번호를 저장할 필요가 없다."""
    base = normalize_base(base_url)
    session = requests.session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 LMSNotifier/1.0",
        "Accept": "application/json",
        "Authorization": f"Bearer {token.strip()}",
    })
    session.base_url = base
    with _step("토큰 확인"):
        resp = session.get(f"{base}/api/v1/users/self", timeout=REQUEST_TIMEOUT)
    if resp.status_code == 401:
        raise LMSLoginError("토큰이 올바르지 않거나 만료됐어요. LMS에서 새 액세스 토큰을 발급받아 주세요.")
    if resp.status_code != 200:
        raise LMSLoginError(
            f"이 주소는 Canvas LMS가 아닌 것 같아요 (응답 {resp.status_code}). "
            "로그인 포털이 아니라, 브라우저에서 과목 목록이 보이는 주소를 넣어 주세요."
        )
    try:
        me = _parse_canvas_json_or_raise(resp)
    except LMSLoginError:
        raise LMSLoginError(
            "이 주소에서 Canvas API 응답을 받지 못했어요. 학교 LMS 주소가 맞는지 확인해 주세요."
        ) from None
    # JSON 이라고 다 Canvas 가 아니다 — 사용자 객체 모양인지까지 본다
    if not isinstance(me, dict) or not me.get("id"):
        raise LMSLoginError(
            "이 주소는 Canvas LMS가 아닌 것 같아요. "
            "로그인 포털이 아니라, 브라우저에서 과목 목록이 보이는 주소를 넣어 주세요."
        )
    return session  # 초. 로그인 세션을 이만큼 재사용해서, 매번 SSO 5단계를 다시 안 거치게 한다.

_session_cache: dict[str, tuple[requests.Session, float]] = {}


class LMSLoginError(RuntimeError):
    pass


@contextmanager
def _step(name: str):
    started = time.monotonic()
    try:
        yield
    except requests.Timeout as exc:
        elapsed = time.monotonic() - started
        print(f"[lms_client] {name}: 시간 초과 ({elapsed:.1f}s)", file=sys.stderr)
        raise LMSLoginError(f"'{name}' 단계에서 학교 서버 응답이 {REQUEST_TIMEOUT}초 넘게 없었습니다. 네트워크가 느리거나 서버가 응답하지 않는 것 같아요.") from exc
    except requests.RequestException as exc:
        elapsed = time.monotonic() - started
        print(f"[lms_client] {name}: 네트워크 오류 ({elapsed:.1f}s) {exc}", file=sys.stderr)
        raise LMSLoginError(f"'{name}' 단계에서 네트워크 오류가 발생했습니다: {exc}") from exc
    else:
        elapsed = time.monotonic() - started
        print(f"[lms_client] {name}: {elapsed:.1f}s", file=sys.stderr)

# 한동대 캔버스(LMS) 플래너가 다루는 유형 중 "일정"과 "공지사항"으로 나눠서 취급한다.
SCHEDULE_TYPES = {"assignment", "quiz", "calendar_event", "discussion_topic", "planner_note"}
ANNOUNCEMENT_TYPES = {"announcement"}


def _format_pem(raw_key_block: str) -> bytes:
    body = (
        raw_key_block.replace("-----BEGIN RSA PRIVATE KEY-----", "")
        .replace("-----END RSA PRIVATE KEY-----", "")
        .strip()
    )
    wrapped = "\n".join(body[i : i + 64] for i in range(0, len(body), 64))
    pem = f"-----BEGIN RSA PRIVATE KEY-----\n{wrapped}\n-----END RSA PRIVATE KEY-----\n"
    return pem.encode()


def _decrypt_canvas_password(handoff_html: str) -> str:
    crypt_match = re.search(r'window\.loginCryption\("([^"]+)"', handoff_html)
    key_match = re.search(
        r"(-----BEGIN RSA PRIVATE KEY-----.*?-----END RSA PRIVATE KEY-----)",
        handoff_html,
        re.S,
    )
    if not crypt_match or not key_match:
        raise LMSLoginError("LearningX-Canvas 인계 페이지에서 암호화 정보를 찾지 못했습니다 (사이트 구조가 바뀌었을 수 있음)")
    private_key = serialization.load_pem_private_key(_format_pem(key_match.group(1)), password=None)
    ciphertext = base64.b64decode(crypt_match.group(1))
    plaintext = private_key.decrypt(ciphertext, padding.PKCS1v15())
    return plaintext.decode()


def _strip_canvas_json(payload: str):
    if payload.startswith("while(1);"):
        payload = payload[len("while(1);") :]
    return json.loads(payload)


def _parse_canvas_json_or_raise(resp: requests.Response):
    try:
        return _strip_canvas_json(resp.text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LMSLoginError("세션이 만료된 것 같아요. 다시 로그인해서 시도할게요.") from exc


def login(student_id: str, password: str) -> requests.Session:
    """히스넷 학번/비밀번호로 한동대 캔버스 LMS에 로그인한 세션을 반환한다.

    실패 시 LMSLoginError를 던진다. 비밀번호는 이 함수 밖으로 전달되지 않는다.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 LMSNotifier/1.0",
            "Accept": "text/html,application/json,*/*",
        }
    )

    login_started = time.monotonic()

    with _step("1/5 SSO 로그인 페이지"):
        session.get("https://lms.handong.edu/login", timeout=REQUEST_TIMEOUT)
    csrf = session.cookies.get("xn_sso_csrf_token_for_this_login")
    if not csrf:
        raise LMSLoginError("SSO CSRF 토큰을 받지 못했습니다 (네트워크 또는 사이트 문제)")

    with _step("2/5 통합 로그인 제출"):
        callback = session.post(
            "https://online.handong.edu/xn-sso-e/gw-cb.php?from=&login_type=&return_url=",
            data={
                "csrf_token": csrf,
                "login_user_id": student_id,
                "login_user_password": password,
            },
            headers={"Referer": "https://online.handong.edu/xn-sso-e/login.php"},
            timeout=REQUEST_TIMEOUT,
        )
    location_match = re.search(r'window\.location\.href\s*=\s*"([^"]+)"', callback.text)
    if not location_match:
        raise LMSLoginError("학번 또는 비밀번호가 올바르지 않거나, 통합 로그인에 실패했습니다")

    with _step("3/5 Canvas 인계 페이지"):
        handoff = session.get(html.unescape(location_match.group(1)), timeout=REQUEST_TIMEOUT)
    canvas_password = _decrypt_canvas_password(handoff.text)

    with _step("4/5 Canvas 로그인 제출"):
        session.post(
            "https://lms.handong.edu/login/canvas",
            data={
                "utf8": "✓",
                "redirect_to_ssl": "1",
                "after_login_url": "",
                "pseudonym_session[unique_id]": student_id,
                "pseudonym_session[password]": canvas_password,
                "pseudonym_session[remember_me]": "0",
            },
            headers={"Referer": "https://lms.handong.edu/learningx/login/from_cc"},
            timeout=REQUEST_TIMEOUT,
        )

    session.base_url = HANDONG_BASE
    with _step("5/5 로그인 확인"):
        check = session.get(f"{HANDONG_BASE}/api/v1/users/self", timeout=REQUEST_TIMEOUT)
    try:
        _strip_canvas_json(check.text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LMSLoginError("Canvas 로그인 확인에 실패했습니다 (학번/비밀번호를 확인하세요)") from exc

    print(f"[lms_client] 로그인 전체: {time.monotonic() - login_started:.1f}s", file=sys.stderr)
    _session_cache[student_id] = (session, time.monotonic() + SESSION_TTL)
    return session


def get_session(student_id: str, password: str) -> requests.Session:
    """캐시된 로그인 세션이 있으면 재사용하고, 없거나 오래됐으면 새로 로그인한다.

    같은 계정으로 짧은 시간 안에 여러 번 요청할 때(과목 불러오기 → 지금 확인 등)
    매번 5단계짜리 SSO 로그인을 반복하지 않도록 하는 게 목적이다.
    """
    cached = _session_cache.get(student_id)
    if cached:
        session, expires_at = cached
        if time.monotonic() < expires_at:
            print(f"[lms_client] 캐시된 세션 재사용 (로그인 생략)", file=sys.stderr)
            return session
    return login(student_id, password)


def invalidate_session(student_id: str) -> None:
    _session_cache.pop(student_id, None)


def fetch_planner_items(session: requests.Session, days: int) -> tuple[list[dict], list[dict]]:
    """앞으로 `days`일 안의 일정(과제/퀴즈/캘린더 이벤트)과 공지사항을 함께 가져온다."""
    now = dt.datetime.now(KST)
    end = now + dt.timedelta(days=days)
    params = {
        "start_date": now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "end_date": end.replace(hour=23, minute=59, second=59, microsecond=0).isoformat(),
        "per_page": "100",
    }
    with _step("플래너 항목 조회"):
        resp = session.get(f"{base_of(session)}/api/v1/planner/items", params=params, timeout=REQUEST_TIMEOUT)
    raw_items = _parse_canvas_json_or_raise(resp)

    schedule: list[dict] = []
    announcements: list[dict] = []
    for item in raw_items:
        plannable_type = item.get("plannable_type")
        plannable = item.get("plannable") or {}
        due_raw = item.get("plannable_date") or plannable.get("due_at")
        if not due_raw:
            continue
        due = dt.datetime.fromisoformat(due_raw.replace("Z", "+00:00")).astimezone(KST)
        title = plannable.get("title") or item.get("title") or "(제목 없음)"
        entry = {
            "id": f"{plannable_type}:{item.get('plannable_id')}",
            "type": plannable_type,
            "date": due.isoformat(),
            "title": title,
            "course": item.get("context_name", ""),
            "course_id": item.get("course_id"),
            "submitted": bool((item.get("submissions") or {}).get("submitted")),
        }
        if plannable_type in ANNOUNCEMENT_TYPES:
            announcements.append(entry)
        elif plannable_type in SCHEDULE_TYPES:
            schedule.append(entry)

    schedule.sort(key=lambda x: x["date"])
    announcements.sort(key=lambda x: x["date"])
    return schedule, announcements


def fetch_courses(session: requests.Session) -> list[dict]:
    """수강 중인 과목 목록을 가져온다 (설정 화면에서 과목 필터를 고를 때 씀)."""
    with _step("과목 목록 조회"):
        resp = session.get(
            f"{base_of(session)}/api/v1/courses",
            params={"enrollment_state": "active", "per_page": "100"},
            timeout=REQUEST_TIMEOUT,
        )
    raw_courses = _parse_canvas_json_or_raise(resp)
    return [
        {"id": str(course["id"]), "name": course.get("name") or course.get("course_code") or f"course {course['id']}"}
        for course in raw_courses
        if course.get("id") and not course.get("access_restricted_by_date")
    ]


def fetch_announcements(session: requests.Session, courses: list[dict], days: int) -> list[dict]:
    """공지사항을 직접 가져온다.

    캔버스 플래너(`/api/v1/planner/items`)는 교수가 "할 일 날짜(todo_date)"를 따로
    설정해둔 공지사항만 보여준다 — 실제로는 대부분의 공지사항에 이 값이 없어서
    fetch_planner_items만으로는 공지사항이 거의 항상 0건으로 나온다. 그래서 공지사항은
    `/api/v1/announcements`를 과목별로 직접 조회해서 채운다.
    """
    course_ids = [c["id"] for c in courses]
    if not course_ids:
        return []
    course_names = {c["id"]: c["name"] for c in courses}

    now = dt.datetime.now(KST)
    start = now - dt.timedelta(days=days)
    end = now + dt.timedelta(days=1)
    params = {
        "context_codes[]": [f"course_{cid}" for cid in course_ids],
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "per_page": "50",
    }
    with _step("공지사항 조회"):
        resp = session.get(f"{base_of(session)}/api/v1/announcements", params=params, timeout=REQUEST_TIMEOUT)
    raw_items = _parse_canvas_json_or_raise(resp)

    out: list[dict] = []
    for item in raw_items:
        date_raw = item.get("posted_at") or item.get("delayed_post_at") or item.get("created_at")
        if not date_raw:
            continue
        date = dt.datetime.fromisoformat(date_raw.replace("Z", "+00:00")).astimezone(KST)
        context_code = item.get("context_code", "")
        course_id = context_code[len("course_") :] if context_code.startswith("course_") else None
        out.append(
            {
                "id": f"announcement:{item.get('id')}",
                "type": "announcement",
                "date": date.isoformat(),
                "title": item.get("title") or "(제목 없음)",
                "course": course_names.get(course_id, ""),
                "course_id": course_id,
                "submitted": False,
            }
        )
    out.sort(key=lambda x: x["date"])
    return out


def fetch_all(session: requests.Session, days: int) -> tuple[list[dict], list[dict]]:
    """일정(과제/퀴즈/캘린더)과 공지사항을 함께 가져온다. 앱이 실제로 쓰는 진입점."""
    schedule, planner_announcements = fetch_planner_items(session, days)
    courses = fetch_courses(session)
    direct_announcements = fetch_announcements(session, courses, days)

    seen_ids = {a["id"] for a in planner_announcements}
    announcements = planner_announcements + [a for a in direct_announcements if a["id"] not in seen_ids]
    announcements.sort(key=lambda x: x["date"])
    return schedule, announcements


def apply_filters(items: list[dict], course_ids: list[str] | None, types: list[str] | None) -> list[dict]:
    """설정에서 고른 과목/유형만 남긴다. None은 '전체 포함'을 뜻한다."""
    out = items
    if course_ids is not None:
        allowed = set(course_ids)
        out = [
            item
            for item in out
            if item.get("course_id") is None or str(item["course_id"]) in allowed
        ]
    if types is not None:
        allowed_types = set(types)
        out = [item for item in out if item.get("type") in allowed_types]
    return out

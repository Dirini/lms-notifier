from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import lms_client
import main as flow
import prefs
import runs
import secrets_store
import state as state_mod
import telegram

KST = ZoneInfo("Asia/Seoul")
BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
HOST = "127.0.0.1"
PORT = 8912
SCHEDULER_TICK = 30  # 초. 이 주기로 poll_minutes 설정이 바뀌었는지, 실행할 때가 됐는지 확인한다.
MIN_POLL_MINUTES = 15  # 학교 SSO에 너무 자주 로그인하지 않도록 두는 최소 자동 확인 주기.

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}

run_lock = threading.Lock()
scheduler_state = {"next_run_at": None, "running": False}


def account_status() -> dict:
    account = secrets_store.get_account()
    if not account:
        return {"connected": False}
    if account.get("mode") == "canvas":
        return {"connected": True, "mode": "canvas",
                "masked": secrets_store.mask_token(account.get("token", "")),
                "base_url": account.get("base_url", "")}
    return {"connected": True, "mode": "handong",
            "masked": secrets_store.mask_id(account["student_id"])}


def telegram_status() -> dict:
    tg = secrets_store.get_telegram()
    if not tg:
        return {"connected": False}
    return {"connected": True, "chat_id": tg["chat_id"]}


def _fetch_with_retry(account: dict, fn):
    """캐시된 세션으로 먼저 시도하고, 세션이 만료돼서 실패하면 한 번만 새로 붙어서 다시 시도한다."""
    if account.get("mode") == "canvas":
        # 토큰 방식은 만료 개념이 없어 캐시도 재시도도 필요 없다
        return fn(lms_client.token_session(account["base_url"], account["token"]))

    student_id, password = account["student_id"], account["password"]
    session = lms_client.get_session(student_id, password)
    try:
        return fn(session)
    except lms_client.LMSLoginError:
        lms_client.invalidate_session(student_id)
        session = lms_client.get_session(student_id, password)
        return fn(session)


def perform_run(days: int = 7) -> dict:
    """계정 로그인 → 새 항목 조회 → 필터 적용 → 텔레그램 전송까지 한 번 수행한다.

    수동 실행 버튼과 자동 확인 스케줄러가 동시에 로그인을 시도해 계정이 잠기는 일이
    없도록 run_lock으로 겹쳐 실행되지 않게 막는다.
    """
    if not run_lock.acquire(blocking=False):
        return {"ok": False, "error": "이미 다른 확인이 진행 중이에요. 잠시 후 다시 시도하세요."}
    try:
        account = secrets_store.get_account()
        tg = secrets_store.get_telegram()
        if not account:
            return {"ok": False, "error": "먼저 LMS 계정을 연결하세요"}
        if not tg:
            return {"ok": False, "error": "먼저 텔레그램을 연결하세요"}

        try:
            schedule, announcements = _fetch_with_retry(
                account,
                lambda s: lms_client.fetch_all(s, days),
            )
        except lms_client.LMSLoginError as exc:
            result = {"ok": False, "error": str(exc)}
            runs.append(result)
            return result

        filters = prefs.load()
        schedule = lms_client.apply_filters(schedule, filters["course_ids"], filters["types"])
        announcements = lms_client.apply_filters(announcements, filters["course_ids"], filters["types"])

        state = state_mod.load(flow.STATE_PATH)
        new_schedule = state_mod.filter_new(state, schedule)
        new_announcements = state_mod.filter_new(state, announcements)

        result = {
            "ok": True,
            "new_schedule": len(new_schedule),
            "new_announcements": len(new_announcements),
            "sent": False,
        }

        if new_schedule or new_announcements:
            message = flow.format_message(new_schedule, new_announcements,
                                          filters.get("message_format", "detailed"))
            telegram.send_message(tg["bot_token"], tg["chat_id"], message)
            state_mod.mark_seen(state, new_schedule + new_announcements)
            state_mod.prune(state)
            state_mod.save(flow.STATE_PATH, state)
            result["sent"] = True
            result["preview"] = message

        runs.append(result)
        return result
    finally:
        run_lock.release()


def _next_fixed_time(fixed_times: list[str], after: dt.datetime) -> dt.datetime | None:
    candidates = []
    for value in fixed_times:
        try:
            hh, mm = (int(part) for part in value.split(":"))
        except ValueError:
            continue
        candidate = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= after:
            candidate += dt.timedelta(days=1)
        candidates.append(candidate)
    return min(candidates) if candidates else None


def _missed_since(fixed_times: list[str], since: dt.datetime, now: dt.datetime) -> list[dt.datetime]:
    """since 이후 now 까지 지나간 예약 시각을 모두 돌려준다.

    컴퓨터가 꺼져 있었거나 프로그램이 떠 있지 않았다면 그 시각들은 실행되지 않았다.
    스케줄러는 항상 '지금' 기준으로 다음 실행을 잡기 때문에 놓친 회차는 따라잡지 않는다 —
    그래서 여기서 따로 세어 사용자에게 알려준다."""
    if not fixed_times or since >= now:
        return []
    missed = []
    day = since.date()
    while day <= now.date():
        for value in fixed_times:
            try:
                hh, mm = (int(part) for part in value.split(":"))
            except ValueError:
                continue
            at = dt.datetime.combine(day, dt.time(hh, mm), tzinfo=now.tzinfo)
            if since < at <= now:
                missed.append(at)
        day += dt.timedelta(days=1)
    return sorted(missed)


def missed_summary() -> dict:
    """놓친 예약 실행과 마지막 실패를 요약한다 (화면 상단 배너용)."""
    p = prefs.load()
    history = runs.recent()
    now = dt.datetime.now(KST)

    last_ok_at = None
    for entry in history:
        if entry.get("ok"):
            try:
                last_ok_at = dt.datetime.fromisoformat(entry["at"])
            except (ValueError, KeyError):
                pass
            break

    last_error = None
    if history and not history[0].get("ok"):
        last_error = history[0].get("error") or "확인에 실패했어요"

    missed = []
    if p.get("schedule_mode") == "fixed" and last_ok_at:
        missed = _missed_since(p.get("fixed_times") or [], last_ok_at, now)

    return {
        "lastSuccessAt": last_ok_at.isoformat() if last_ok_at else None,
        "lastError": last_error,
        "missedCount": len(missed),
        "missedTimes": [m.isoformat() for m in missed[-5:]],
    }


def _compute_next_run(mode: str, poll_minutes: int | None, fixed_times: list[str], now: dt.datetime) -> dt.datetime | None:
    if mode == "interval":
        minutes = max(poll_minutes or MIN_POLL_MINUTES, MIN_POLL_MINUTES)
        return now + dt.timedelta(minutes=minutes)
    if mode == "fixed":
        return _next_fixed_time(fixed_times, now)
    return None


def scheduler_loop() -> None:
    next_run_at: dt.datetime | None = None
    while True:
        time.sleep(SCHEDULER_TICK)
        p = prefs.load()
        mode = p.get("schedule_mode", "off")
        now = dt.datetime.now(KST)

        if mode == "off":
            next_run_at = None
            scheduler_state["next_run_at"] = None
            continue

        if next_run_at is None:
            next_run_at = _compute_next_run(mode, p.get("poll_minutes"), p.get("fixed_times") or [], now)
        scheduler_state["next_run_at"] = next_run_at.isoformat() if next_run_at else None

        if next_run_at and now >= next_run_at:
            if secrets_store.get_account() and secrets_store.get_telegram():
                scheduler_state["running"] = True
                try:
                    perform_run()
                finally:
                    scheduler_state["running"] = False
            next_run_at = _compute_next_run(mode, p.get("poll_minutes"), p.get("fixed_times") or [], now)
            scheduler_state["next_run_at"] = next_run_at.isoformat() if next_run_at else None


class Handler(BaseHTTPRequestHandler):
    server_version = "LMSNotifier/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _same_origin(self) -> bool:
        """이 서버는 인증이 없다. 사용자가 방문한 아무 웹페이지나 localhost로 요청을
        보낼 수 있으므로(CSRF), Host와 Origin을 직접 확인해서 막는다.
        Host 검사는 DNS rebinding(외부 도메인이 127.0.0.1로 해석되게 하는 공격)도 함께 차단한다."""
        allowed = {f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"}
        if self.headers.get("Host", "") not in allowed:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in allowed}:
            return False
        return True

    def _read_json(self) -> dict:
        # Content-Type 을 강제하면 브라우저가 프리플라이트를 보내야만 해서
        # 크로스 사이트에서 오는 '단순 요청' 우회가 막힌다.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise ValueError("content-type must be application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        if length > 256 * 1024:
            raise ValueError("body too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _serve_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        target = (WEB_DIR / path.lstrip("/")).resolve()
        if WEB_DIR not in target.parents and target != WEB_DIR:
            self.send_error(404)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        content_type = STATIC_TYPES.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._same_origin():
            return self._send_json(403, {"error": "허용되지 않은 요청입니다"})
        path = urlparse(self.path).path
        if path == "/api/account":
            return self._send_json(200, account_status())
        if path == "/api/telegram":
            return self._send_json(200, telegram_status())
        if path == "/api/runs":
            return self._send_json(200, {"runs": runs.recent(), "missed": missed_summary()})
        if path == "/api/prefs":
            return self._send_json(200, prefs.load())
        if path == "/api/schedule":
            p = prefs.load()
            return self._send_json(
                200,
                {
                    **scheduler_state,
                    "schedule_mode": p.get("schedule_mode", "off"),
                    "poll_minutes": p.get("poll_minutes"),
                    "fixed_times": p.get("fixed_times") or [],
                },
            )
        return self._serve_static(path)

    def do_POST(self):
        if not self._same_origin():
            return self._send_json(403, {"error": "허용되지 않은 요청입니다"})
        path = urlparse(self.path).path
        try:
            body = self._read_json()
        except (json.JSONDecodeError, ValueError):
            return self._send_json(400, {"error": "잘못된 요청입니다"})

        if path == "/api/account":
            return self._handle_account_connect(body)
        if path == "/api/message-format":
            fmt = (body.get("format") or "detailed").strip()
            if fmt not in ("simple", "detailed"):
                return self._send_json(400, {"error": "형식 값이 올바르지 않습니다"})
            return self._send_json(200, prefs.set_message_format(fmt))
        if path == "/api/account/disconnect":
            secrets_store.clear_account()
            return self._send_json(200, {"connected": False})
        if path == "/api/telegram":
            return self._handle_telegram_connect(body)
        if path == "/api/telegram/disconnect":
            secrets_store.clear_telegram()
            return self._send_json(200, {"connected": False})
        if path == "/api/telegram/chat-id":
            return self._handle_chat_id(body)
        if path == "/api/run":
            return self._handle_run(body)
        if path == "/api/prefs":
            return self._handle_prefs_save(body)
        if path == "/api/courses/refresh":
            return self._handle_courses_refresh(body)
        if path == "/api/schedule":
            return self._handle_schedule_save(body)
        return self._send_json(404, {"error": "not found"})

    def _handle_account_connect(self, body: dict):
        if str(body.get("mode", "")).strip() == "canvas":
            return self._handle_token_connect(body)
        student_id = str(body.get("student_id", "")).strip()
        password = str(body.get("password", ""))
        if not student_id or not password:
            return self._send_json(400, {"error": "학번과 비밀번호를 입력하세요"})
        try:
            lms_client.login(student_id, password)
        except lms_client.LMSLoginError as exc:
            return self._send_json(200, {"ok": False, "error": str(exc)})
        secrets_store.set_account(student_id, password)
        return self._send_json(200, {"ok": True, "mode": "handong",
                                     "masked": secrets_store.mask_id(student_id)})

    def _handle_token_connect(self, body: dict):
        raw_base = str(body.get("base_url", "")).strip()
        token = str(body.get("token", "")).strip()
        if not raw_base or not token:
            return self._send_json(400, {"error": "학교 LMS 주소와 액세스 토큰을 모두 입력하세요"})
        try:
            base_url = lms_client.normalize_base(raw_base)
        except ValueError as exc:
            return self._send_json(400, {"error": str(exc)})
        try:
            lms_client.token_session(base_url, token)
        except lms_client.LMSLoginError as exc:
            return self._send_json(200, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 — 주소 오타로 인한 접속 실패도 화면에 그대로 보여준다
            return self._send_json(200, {"ok": False, "error": f"접속하지 못했어요: {str(exc)[:160]}"})
        secrets_store.set_token_account(base_url, token)
        return self._send_json(200, {"ok": True, "mode": "canvas", "base_url": base_url,
                                     "masked": secrets_store.mask_token(token)})

    def _handle_telegram_connect(self, body: dict):
        bot_token = str(body.get("bot_token", "")).strip()
        chat_id = str(body.get("chat_id", "")).strip()
        if not bot_token or not chat_id:
            return self._send_json(400, {"error": "봇 토큰과 chat_id를 입력하세요"})
        try:
            telegram.send_message(bot_token, chat_id, "LMS 알리미 연결 확인 메시지예요. 이 메시지가 보이면 정상 연결된 거예요.")
        except RuntimeError as exc:
            return self._send_json(200, {"ok": False, "error": str(exc)})
        secrets_store.set_telegram(bot_token, chat_id)
        return self._send_json(200, {"ok": True, "chat_id": chat_id})

    def _handle_chat_id(self, body: dict):
        bot_token = str(body.get("bot_token", "")).strip()
        if not bot_token:
            return self._send_json(400, {"error": "봇 토큰을 입력하세요"})
        try:
            chat_id = telegram.get_latest_chat_id(bot_token)
        except Exception as exc:  # noqa: BLE001 - surface any Telegram API failure to the UI
            # 예외 메시지에 토큰이 실려 올 수 있다 — 화면으로 돌려주기 전에 가린다
            return self._send_json(200, {"chat_id": None, "error": telegram.scrub(exc, bot_token)})
        return self._send_json(200, {"chat_id": chat_id})

    def _handle_prefs_save(self, body: dict):
        course_ids = body.get("course_ids")
        types = body.get("types")
        if course_ids is not None and not isinstance(course_ids, list):
            return self._send_json(400, {"error": "course_ids는 목록이어야 합니다"})
        if types is not None and not isinstance(types, list):
            return self._send_json(400, {"error": "types는 목록이어야 합니다"})
        data = prefs.set_filters(course_ids, types)
        return self._send_json(200, data)

    def _handle_schedule_save(self, body: dict):
        mode = body.get("schedule_mode", "off")
        if mode not in ("off", "interval", "fixed"):
            return self._send_json(400, {"error": "schedule_mode 값이 올바르지 않습니다"})

        minutes = body.get("poll_minutes")
        if mode == "interval":
            try:
                minutes = int(minutes)
            except (TypeError, ValueError):
                return self._send_json(400, {"error": "poll_minutes는 숫자여야 합니다"})
            if minutes < MIN_POLL_MINUTES:
                return self._send_json(400, {"error": f"자동 확인은 {MIN_POLL_MINUTES}분 이상으로만 설정할 수 있어요"})

        # 형식 검증은 모드와 무관하게 항상 한다 — off/interval 로 보내면서 임의 문자열을
        # 심어두면 화면이 그걸 그대로 렌더해 저장형 XSS 가 된다.
        fixed_times = body.get("fixed_times") or []
        if not isinstance(fixed_times, list):
            return self._send_json(400, {"error": "fixed_times는 목록이어야 합니다"})
        if len(fixed_times) > 24:
            return self._send_json(400, {"error": "시각은 24개까지만 설정할 수 있어요"})
        for value in fixed_times:
            if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(value)):
                return self._send_json(400, {"error": f"'{value}'는 올바른 시각(HH:MM) 형식이 아니에요"})
        fixed_times = [str(v) for v in fixed_times]
        if mode == "fixed" and not fixed_times:
            return self._send_json(400, {"error": "적어도 한 개 이상의 시각을 추가하세요"})

        prefs.set_schedule(mode, minutes, fixed_times)
        scheduler_state["next_run_at"] = None  # 다음 스케줄러 틱에서 새 설정으로 다시 계산
        return self._send_json(
            200, {**scheduler_state, "schedule_mode": mode, "poll_minutes": minutes, "fixed_times": fixed_times}
        )

    def _handle_courses_refresh(self, body: dict):
        account = secrets_store.get_account()
        if not account:
            return self._send_json(400, {"error": "먼저 LMS 계정을 연결하세요"})
        try:
            courses = _fetch_with_retry(account, lms_client.fetch_courses)
        except lms_client.LMSLoginError as exc:
            return self._send_json(200, {"error": str(exc)})
        data = prefs.set_known_courses(courses)
        return self._send_json(200, data)

    def _handle_run(self, body: dict):
        try:
            days = int(body.get("days") or 7)
        except (TypeError, ValueError):
            return self._send_json(400, {"error": "days는 숫자여야 합니다"})
        days = max(1, min(days, 60))   # 학교 서버에 과한 조회를 보내지 않도록 상한을 둔다
        result = perform_run(days)
        return self._send_json(200, result)


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    url = f"http://{HOST}:{PORT}"
    print(f"LMS 알리미 로컬 서버 실행 중: {url}")
    print("이 창을 닫으면 서버가 멈춰요(자동 확인도 같이 멈춰요). 종료하려면 Ctrl+C")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

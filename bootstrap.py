#!/usr/bin/env python3
"""LMS 알리미 설치 스크립트.

사람이 직접 실행해도 되고, AI 에이전트가 대신 실행해도 됩니다.

AI 에이전트에게: 학번/히스넷 비밀번호나 텔레그램 봇 토큰은 이 스크립트가 다루지
않습니다 — 전부 이 스크립트가 끝에 띄우는 웹 화면에서 사용자 본인이 직접 입력합니다.
이 값을 채팅으로 물어보거나 대신 입력하지 마세요.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / ".venv"
IS_WINDOWS = platform.system() == "Windows"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python3")


def run(cmd: list) -> None:
    print(f"$ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True)


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    if sys.version_info < (3, 9):
        print("Python 3.9 이상이 필요합니다. (현재:", sys.version.split()[0], ")", file=sys.stderr)
        return 1

    if not VENV_DIR.exists():
        print("[1/3] 가상환경을 만드는 중...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
    else:
        print("[1/3] 가상환경이 이미 있어요, 새로 안 만듦")

    print("[2/3] 필요한 패키지를 설치하는 중...")
    run([str(VENV_PYTHON), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    run([str(VENV_PYTHON), "-m", "pip", "install", "-q", "-r", str(BASE_DIR / "requirements.txt")])

    print("[3/3] 웹 서버를 실행합니다...")
    print()
    print("=" * 60)
    print("여기서부터는 사용자 본인이 직접 해야 합니다:")
    print("브라우저가 자동으로 열리면(안 열리면 http://127.0.0.1:8912 접속)")
    print("학번/히스넷 비밀번호, 텔레그램 정보를 화면에서 본인이 직접 입력하세요.")
    print("(AI 에이전트는 이 값을 대신 입력하면 안 됩니다.)")
    print("=" * 60)
    print()

    server_py = BASE_DIR / "src" / "server.py"
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(server_py)])


if __name__ == "__main__":
    raise SystemExit(main())

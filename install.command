#!/bin/bash
# LMS 알리미 무설치 다운로드·실행 스크립트 (git 불필요)
# 더블클릭하거나 터미널에서 실행하세요. macOS 기본 도구(curl/unzip/bash)만 씁니다.
set -e

REPO_ZIP="https://github.com/Dirini/lms-notifier/archive/refs/heads/main.zip"
DEST="$HOME/lms-notifier"

echo "───────────────────────────────"
echo "  LMS 알리미 설치"
echo "───────────────────────────────"

# 1) Python 3.9+ 확인
PY=""
for c in python3 python3.12 python3.11 python3.10 python3.9; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "")
    if [ -n "$v" ]; then
      major=${v%%.*}; minor=${v##*.}
      if [ "$major" -eq 3 ] && [ "$minor" -ge 9 ]; then PY="$c"; break; fi
    fi
  fi
done

if [ -z "$PY" ]; then
  echo
  echo "⚠️  Python 3.9 이상이 필요한데 찾지 못했어요."
  echo
  echo "   아래에서 설치 파일을 받아 설치한 뒤, 이 파일을 다시 실행하세요:"
  echo "   https://www.python.org/downloads/macos/"
  echo "   (다운로드 → 더블클릭 → 안내대로 설치. 5분이면 돼요.)"
  echo
  read -n 1 -s -r -p "확인했으면 아무 키나 누르세요..."
  # 파이썬 받는 페이지를 자동으로 열어준다
  open "https://www.python.org/downloads/macos/" 2>/dev/null || true
  exit 1
fi
echo "✓ Python 확인: $($PY --version 2>&1)"

# 2) 코드 내려받기 (git 없이 ZIP)
echo "→ 프로그램을 내려받는 중..."
TMP="$(mktemp -d)"
curl -fsSL "$REPO_ZIP" -o "$TMP/app.zip"
unzip -q "$TMP/app.zip" -d "$TMP"

# 기존 설치가 있으면 개인 설정(.local/.env)은 지키고 코드만 교체
if [ -d "$DEST" ]; then
  echo "→ 기존 설치 발견 — 코드만 업데이트해요 (설정은 유지)"
  rsync -a --delete \
    --exclude ".local/" --exclude ".env" --exclude "state.json" --exclude ".venv/" \
    "$TMP/lms-notifier-main/" "$DEST/"
else
  mv "$TMP/lms-notifier-main" "$DEST"
fi
rm -rf "$TMP"
echo "✓ 내려받기 완료: $DEST"

# 3) 실행
echo "→ 설치·실행 시작..."
cd "$DEST"
exec "$PY" bootstrap.py

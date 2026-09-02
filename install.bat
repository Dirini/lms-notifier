@echo off
REM LMS 알리미 무설치 다운로드·실행 (Windows, Git 불필요)
REM 더블클릭하면 실행됩니다. Windows 기본 PowerShell 만 씁니다.
setlocal enabledelayedexpansion
title LMS 알리미 설치

echo ===============================
echo   LMS 알리미 설치
echo ===============================

REM 1) Python 3.9+ 확인
set "PY="
for %%C in (python py) do (
  where %%C >nul 2>nul && (
    for /f "delims=" %%V in ('%%C -c "import sys;print(1 if sys.version_info[:2]>=(3,9) else 0)" 2^>nul') do (
      if "%%V"=="1" set "PY=%%C"
    )
  )
)

if not defined PY (
  echo.
  echo [!] Python 3.9 이상이 필요한데 찾지 못했어요.
  echo     아래 페이지에서 설치한 뒤 이 파일을 다시 실행하세요.
  echo     설치 중 "Add Python to PATH" 체크를 꼭 켜세요.
  echo     https://www.python.org/downloads/windows/
  start "" "https://www.python.org/downloads/windows/"
  pause
  exit /b 1
)
echo [OK] Python 확인 완료

REM 2) 코드 내려받기 (git 없이 ZIP, PowerShell 사용)
set "DEST=%USERPROFILE%\lms-notifier"
echo -^> 프로그램을 내려받는 중...
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$zip=Join-Path $env:TEMP 'lms-notifier.zip';" ^
  "Invoke-WebRequest -Uri 'https://github.com/Dirini/lms-notifier/archive/refs/heads/main.zip' -OutFile $zip;" ^
  "$out=Join-Path $env:TEMP 'lms-notifier-extract';" ^
  "if(Test-Path $out){Remove-Item $out -Recurse -Force};" ^
  "Expand-Archive -Path $zip -DestinationPath $out -Force;" ^
  "$src=Join-Path $out 'lms-notifier-main';" ^
  "$dest='%DEST%';" ^
  "if(Test-Path $dest){" ^
  "  robocopy $src $dest /E /XD '.local' '.venv' /XF '.env' 'state.json' | Out-Null" ^
  "} else { Move-Item $src $dest }"
if errorlevel 8 (
  echo [!] 내려받기에 실패했어요. 인터넷 연결을 확인하고 다시 시도하세요.
  pause
  exit /b 1
)
echo [OK] 내려받기 완료: %DEST%

REM 3) 실행
echo -^> 설치·실행 시작...
cd /d "%DEST%"
%PY% bootstrap.py
pause

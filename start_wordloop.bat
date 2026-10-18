@echo off
chcp 65001 >nul
title WordLoop 영단어 - 이 창을 닫으면 앱이 종료됩니다
cd /d "%~dp0"

rem 이미 실행 중이면 브라우저만 연다
curl -s -o nul -m 2 http://localhost:8501/_stcore/health && (
  echo 이미 실행 중입니다. 브라우저를 엽니다.
  start "" "http://localhost:8501"
  timeout /t 2 >nul
  exit /b 0
)

if not exist ".venv\Scripts\streamlit.exe" (
  echo [오류] 가상환경이 없습니다. 이 폴더에서 아래 두 줄을 먼저 실행하세요.
  echo   py -3.12 -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

echo ==================================================
echo   WordLoop 영단어 학습기
echo.
echo   PC 브라우저 : http://localhost:8501
echo   갤럭시탭 S펜 (같은 Wi-Fi) :
for /f %%i in ('powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceAlias -notmatch 'vEthernet|Loopback|WSL|Bluetooth' } | ForEach-Object IPAddress"') do echo     http://%%i:8501/?tab=write
echo.
echo   이 창을 닫으면 앱이 종료됩니다.
echo ==================================================

rem 서버가 뜰 시간을 두고 브라우저 열기
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 5; Start-Process 'http://localhost:8501'"
".venv\Scripts\streamlit.exe" run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
pause

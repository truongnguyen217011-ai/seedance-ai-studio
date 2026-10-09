@echo off
title Mo Dola AI Nick #16
echo ========================================================
echo     DANG MO GOOGLE CHROME NICK #16 (DOLA AI)
echo ========================================================
echo.
cd /d "C:\AI SEEDANE"
del /f /q "profiles\acc_16\SingletonLock" 2>nul
del /f /q "profiles\acc_16\SingletonCookie" 2>nul
del /f /q "profiles\acc_16\SingletonSocket" 2>nul
del /f /q "profiles\acc_16\DevToolsActivePort" 2>nul
echo Dang khoi dong Google Chrome...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\AI SEEDANE\profiles\acc_16" --remote-debugging-port=9222 --no-first-run --no-default-browser-check --disable-session-crashed-bubble "https://www.dola.com/chat/"
echo Cua so Chrome da duoc mo tren man hinh!
timeout /t 3
exit

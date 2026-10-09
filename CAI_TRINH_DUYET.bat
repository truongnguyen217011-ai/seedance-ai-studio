@echo off
title Cai Chromium cho Seedance AI Studio
color 0b
cd /d "%~dp0"
echo ========================================================
echo      CAI TRINH DUYET CHROMIUM (PLAYWRIGHT) CHO STUDIO
echo ========================================================
echo.
echo Chi can chay mot lan. Se tai khoang 150 MB tu Internet.
echo.
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Python. Hay cai Python 3.10 tro len truoc.
    pause
    exit /b 1
)
python -c "import playwright" >nul 2>&1
if %errorlevel% neq 0 (
    echo [...] Chua co thu vien playwright, dang cai tu requirements.txt ...
    python -m pip install -r requirements.txt
)
echo [...] Dang tai Chromium ...
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo.
    echo [LOI] Tai Chromium that bai. Kiem tra ket noi mang roi chay lai file nay.
    echo       Hoac cai Google Chrome thu cong roi vao Cai dat trong Studio chi duong dan chrome.exe.
    pause
    exit /b 1
)
echo.
echo [OK] Da cai Chromium xong. Bay gio chay KHOI_DONG.bat de mo Studio.
pause

@echo off
cd /d "%~dp0"
set VER=
if exist VERSION set /p VER=<VERSION
title Seedance AI Studio v%VER%
color 0b
echo ========================================================
echo        HE THONG TU DONG HOA SEEDANCE AI STUDIO
echo                 DOLA 2.5 AUTOMATION   v%VER%
echo ========================================================
echo.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo [1/4] Kiem tra Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Python tren may! Hay cai Python 3.10 tro len tai https://www.python.org/downloads/
    echo       Khi cai nho tich "Add python.exe to PATH".
    pause
    exit /b 1
)

echo [2/4] Kiem tra moi truong (thu vien, Chrome)...
python check_env.py
if %errorlevel% neq 0 (
    echo.
    echo [LOI] Moi truong chua san sang, ma loi %errorlevel%. Xem huong dan o tren roi chay lai KHOI_DONG.bat.
    pause
    exit /b %errorlevel%
)

echo [3/4] Se mo trinh duyet Studio tai http://localhost:8000 sau 5 giay ...
echo       Neu trang trang, bam F5.
start "" cmd /c "timeout /t 5 /nobreak >nul && start http://localhost:8000"

echo [4/4] Dang khoi dong Web Server Seedance AI Studio...
echo (Luu y: Giu cua so nay mo trong suot qua trinh lam viec)
echo Nhan Ctrl+C de dung ung dung.
echo.
python -m uvicorn app:app --host 127.0.0.1 --port 8000
echo.
echo Server da dung.
pause

@echo off
title Seedance AI Studio (Dola 2.5)
color 0b
echo ========================================================
echo        HE THONG TU DONG HOA SEEDANCE AI STUDIO
echo                 DOLA 2.5 AUTOMATION
echo ========================================================
echo.
cd /d "%~dp0"

echo [1/3] Kiem tra moi truong Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Python tren may tinh! Vui long cai dat Python 3.10+
    pause
    exit /b
)

echo [2/3] Dang mo trinh duyet Studio tai http://localhost:8000 ...
timeout /t 2 /nobreak >nul
start http://localhost:8000

echo [3/3] Dang khoi dong Web Server Seedance AI Studio...
echo (Luu y: Giu cua so nay mo trong suot qua trinh lam viec)
echo Nhan Ctrl+C de dung ung dung.
echo.
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
pause

@echo off
title Cap nhat Seedance AI Studio
color 0b
cd /d "%~dp0"
echo ========================================================
echo           CAP NHAT SEEDANCE AI STUDIO TU GITHUB
echo ========================================================
echo.
echo Luu y: cap nhat KHONG xoa studio.db, profiles, outputs, logs cua ban.
echo.

set BRANCH=%~1
if "%BRANCH%"=="" (
    for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set BRANCH=%%b
)
if "%BRANCH%"=="" set BRANCH=main
if "%BRANCH%"=="HEAD" set BRANCH=main
echo Nhanh se cap nhat: %BRANCH%  - muon nhanh khac: CAP_NHAT.bat ten_nhanh

git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] May chua cai Git nen khong tu cap nhat duoc.
    echo       Cach 1: cai Git tai https://git-scm.com/download/win roi chay lai file nay.
    echo       Cach 2: len trang GitHub cua du an, bam "Code" -^> "Download ZIP", giai nen de len thu muc nay
    echo               - chi ghi de file ma, GIU NGUYEN studio.db, profiles, outputs, logs.
    pause
    exit /b 1
)

if not exist ".git" (
    echo [LOI] Thu muc nay khong phai ban clone tu Git nen khong "pull" duoc.
    echo       Lam MOT LAN: mo cmd o thu muc cha va chay:
    echo           git clone ^<dia-chi-repo-github^> seedance-ai-studio
    echo       roi chep studio.db, profiles, outputs, logs tu thu muc cu sang thu muc moi.
    echo       Tu lan sau chi can chay CAP_NHAT.bat.
    pause
    exit /b 1
)

echo [1/5] git fetch origin ...
git fetch origin
if %errorlevel% neq 0 (
    echo [LOI] Khong ket noi duoc GitHub. Kiem tra mang hoac quyen truy cap repo.
    pause
    exit /b 1
)

echo [2/5] Chuyen sang nhanh %BRANCH% ...
git checkout %BRANCH%
if %errorlevel% neq 0 (
    echo [LOI] Khong co nhanh "%BRANCH%". Cach dung: CAP_NHAT.bat ten_nhanh  - mac dinh: main
    pause
    exit /b 1
)

echo [3/5] git pull --ff-only origin %BRANCH% ...
git pull --ff-only origin %BRANCH%
if %errorlevel% neq 0 (
    echo [LOI] Khong cap nhat duoc vi ban da sua file ma trong thu muc nay.
    echo       Xem "git status". Neu khong can giu sua doi, chay: git checkout -- . roi chay lai CAP_NHAT.bat
    pause
    exit /b 1
)

echo [4/5] Cai/cap nhat thu vien Python ...
python -m pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [CANH BAO] Cai thu vien gap loi, KHOI_DONG.bat se thu lai.
)

echo [5/5] Xong.
set APPVER=
if exist VERSION set /p APPVER=<VERSION
if not "%APPVER%"=="" echo Phien ban hien tai: %APPVER%
echo.
echo Bay gio chay KHOI_DONG.bat de mo Studio.
pause

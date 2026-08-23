@echo off
title Build Overnight Edge EXE
cd /d "%~dp0"

echo.
echo Building OvernightEdge.exe (one-file Windows app)...
echo This takes several minutes the first time.
echo.

python -m pip install -r requirements.txt -q
python -m pip install pyinstaller -q
python -m PyInstaller --noconfirm --clean OvernightEdge.spec
if errorlevel 1 (
    echo APP BUILD FAILED
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --clean OvernightEdgeSetup.spec
if errorlevel 1 (
    echo SETUP BUILD FAILED
    pause
    exit /b 1
)

if not exist "dist\GiveToBoss" mkdir "dist\GiveToBoss"
copy /Y "dist\OvernightEdge.exe" "dist\GiveToBoss\OvernightEdge.exe" >nul
copy /Y "dist\OvernightEdgeSetup.exe" "dist\GiveToBoss\OvernightEdgeSetup.exe" >nul
copy /Y "FOR_THE_BOSS.md" "dist\GiveToBoss\READ_ME_FIRST.md" >nul
copy /Y "EXECUTIVE_BRIEF.md" "dist\GiveToBoss\EXECUTIVE_BRIEF.md" >nul
copy /Y "LICENSE.txt" "dist\GiveToBoss\LICENSE.txt" >nul
copy /Y "installer\Install-OvernightEdge.bat" "dist\GiveToBoss\Install-OvernightEdge.bat" >nul

echo.
echo Give your boss: dist\GiveToBoss
echo   OvernightEdgeSetup.exe  = installer for any PC (no admin needed)
echo   OvernightEdge.exe       = portable app
echo.

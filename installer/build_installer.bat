@echo off
title Build Overnight Edge installer
cd /d "%~dp0\.."

echo.
echo [1/3] Building OvernightEdge.exe
python -m pip install -r requirements.txt pyinstaller -q
python -m PyInstaller --noconfirm --clean OvernightEdge.spec
if errorlevel 1 (
    echo EXE build failed.
    exit /b 1
)

echo.
echo [2/3] Locating Inno Setup compiler
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" (
    echo Inno Setup not found. Downloading installer...
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://jrsoftware.org/download.php/is.exe' -OutFile '%TEMP%\innosetup-installer.exe'"
    "%TEMP%\innosetup-installer.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
    if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
)
if "%ISCC%"=="" (
    echo Could not install Inno Setup automatically.
    exit /b 1
)

echo.
echo [3/3] Compiling setup package
if not exist "dist\GiveToBoss" mkdir "dist\GiveToBoss"
"%ISCC%" "installer\OvernightEdge.iss"
if errorlevel 1 (
    echo Installer compile failed.
    exit /b 1
)

copy /Y "dist\OvernightEdge.exe" "dist\GiveToBoss\OvernightEdge.exe" >nul
copy /Y "FOR_THE_BOSS.md" "dist\GiveToBoss\READ_ME_FIRST.md" >nul
copy /Y "EXECUTIVE_BRIEF.md" "dist\GiveToBoss\EXECUTIVE_BRIEF.md" >nul

echo.
echo Installer: dist\GiveToBoss\OvernightEdgeSetup.exe
echo Portable : dist\GiveToBoss\OvernightEdge.exe
echo.

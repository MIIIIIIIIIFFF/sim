@echo off
:: Copie Overnight Edge dans le dossier Programmes de cet utilisateur (aucun administrateur requis).
set "SRC=%~dp0OvernightEdge.exe"
set "DEST=%LOCALAPPDATA%\Programs\Overnight Edge"
if not exist "%SRC%" (
    echo OvernightEdge.exe introuvable a côté de ce script.
    pause
    exit /b 1
)
mkdir "%DEST%" 2>nul
copy /Y "%SRC%" "%DEST%\OvernightEdge.exe" >nul
if exist "%~dp0LICENSE.txt" copy /Y "%~dp0LICENSE.txt" "%DEST%\LICENSE.txt" >nul
if exist "%~dp0READ_ME_FIRST.md" copy /Y "%~dp0READ_ME_FIRST.md" "%DEST%\LISEZ_MOI.txt" >nul 2>nul
mkdir "%APPDATA%\OvernightEdge" 2>nul

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Overnight Edge.lnk'); $s.TargetPath = '%DEST%\OvernightEdge.exe'; $s.WorkingDirectory = [Environment]::GetFolderPath('ApplicationData') + '\OvernightEdge'; $s.Save(); $sm = [Environment]::GetFolderPath('Programs') + '\Overnight Edge'; New-Item -ItemType Directory -Force -Path $sm | Out-Null; $s2 = $ws.CreateShortcut($sm + '\Overnight Edge.lnk'); $s2.TargetPath = '%DEST%\OvernightEdge.exe'; $s2.WorkingDirectory = [Environment]::GetFolderPath('ApplicationData') + '\OvernightEdge'; $s2.Save()"

echo Installé dans %DEST%
start "" "%DEST%\OvernightEdge.exe"
pause

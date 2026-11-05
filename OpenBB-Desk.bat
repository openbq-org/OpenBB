@echo off
REM OpenBB Trading Desk - Windows launcher (double-click).
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo Installation de uv ^(gestionnaire Python^)...
  powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
where uv >nul 2>nul
if errorlevel 1 (
  echo [ERR] uv introuvable ^| [FIX] installez-le : https://docs.astral.sh/uv/
  pause
  exit /b 1
)
uv run --no-project --python 3.12 desk.py %*
set "CODE=%ERRORLEVEL%"
if "%~1"=="" (pause) else if not "%CODE%"=="0" pause
exit /b %CODE%

@echo off
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
title Xue Zhi You Xi - Server

rem NOTE: keep this file pure ASCII.
rem cmd.exe re-reads a .bat by byte offset; putting non-ASCII text here
rem together with "chcp 65001" makes it lose its place and run garbage.

set "BOOTSTRAP="
where py >nul 2>nul
if not errorlevel 1 set "BOOTSTRAP=py"
if defined BOOTSTRAP goto have_python

where python >nul 2>nul
if not errorlevel 1 set "BOOTSTRAP=python"
if defined BOOTSTRAP goto have_python

echo.
echo   Python not found. Please install Python 3 first:
echo   https://www.python.org/downloads/
echo   Remember to check "Add python.exe to PATH" during setup.
echo.
goto end

:have_python
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Preparing BloodGame for first launch...
    %BOOTSTRAP% -m venv ".venv"
    if errorlevel 1 goto venv_error
)

set "APP_PY=.venv\Scripts\python.exe"
"%APP_PY%" -c "import qrcode" >nul 2>nul
if errorlevel 1 (
    echo   Installing the QR code component...
    "%APP_PY%" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto dependency_error
)

"%APP_PY%" server.py %*
goto end

:venv_error
echo.
echo   Could not create the local Python environment.
echo   Check that your Python installation includes the venv module.
echo.
goto end

:dependency_error
echo.
echo   Could not install the QR code component.
echo   Connect to the internet and run this launcher again.
echo.

:end
pause

@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Xue Zhi You Xi - Server

rem NOTE: keep this file pure ASCII.
rem cmd.exe re-reads a .bat by byte offset; putting non-ASCII text here
rem together with "chcp 65001" makes it lose its place and run garbage.

where py >nul 2>nul
if %errorlevel%==0 (
    py server.py %*
    goto end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python server.py %*
    goto end
)

echo.
echo   Python not found. Please install Python 3 first:
echo   https://www.python.org/downloads/
echo   Remember to check "Add python.exe to PATH" during setup.
echo.

:end
pause

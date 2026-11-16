@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title MMacro HUD Launcher

set "PY="
for /f "delims=" %%I in ('where python 2^>nul') do (
    "%%I" -c "import sys" >nul 2>&1
    if !errorlevel! EQU 0 (
        set "PY=%%I"
        goto :found_py
    )
)

where py >nul 2>&1
if %errorlevel% EQU 0 (
    for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do (
        if exist "%%I" (
            set "PY=%%I"
            goto :found_py
        )
    )
)

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "C:\Python3*") do (
    if exist "%%~D\python.exe" (
        "%%~D\python.exe" -c "import sys" >nul 2>&1
        if !errorlevel! EQU 0 (
            set "PY=%%~D\python.exe"
            goto :found_py
        )
    )
)

echo.
echo [MMacro HUD] Python 3.11 or newer was not found on this PC.
echo Please install Python from https://www.python.org/downloads/
echo IMPORTANT: Check "Add python.exe to PATH" during installation.
echo.
pause
exit /b 1

:found_py
if exist "%~dp0deps" set "PYTHONPATH=%~dp0deps;%PYTHONPATH%"

"%PY%" -c "import webview, cv2, rapidocr_onnxruntime, pynput, PIL, numpy, psutil, mousekey" >nul 2>&1
if %errorlevel% NEQ 0 (
    echo [MMacro HUD] First-time setup: installing required packages into .\deps ...
    "%PY%" -m pip install --upgrade --target "%~dp0deps" -r "%~dp0requirements.txt"
    if !errorlevel! NEQ 0 (
        echo.
        echo [MMacro HUD] Failed to install packages. Check your internet connection and try again.
        pause
        exit /b 1
    )
)

for %%F in ("%PY%") do set "PYW=%%~dpFpythonw.exe"
if not exist "%PYW%" set "PYW=%PY%"

start "" "%PYW%" "%~dp0app.py"
exit /b 0

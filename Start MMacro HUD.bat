@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title MMacro HUD Launcher

set "PY="
for /f "delims=" %%I in ('where python 2^>nul') do (
    "%%I" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if !errorlevel! EQU 0 (
        set "PY=%%I"
        goto :found_py
    )
)

where py >nul 2>&1
if %errorlevel% EQU 0 (
    for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable) if sys.version_info >= (3, 11) else None" 2^>nul') do (
        if exist "%%I" (
            set "PY=%%I"
            goto :found_py
        )
    )
)

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "C:\Python3*") do (
    if exist "%%~D\python.exe" (
        "%%~D\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
        if !errorlevel! EQU 0 (
            set "PY=%%~D\python.exe"
            goto :found_py
        )
    )
)

echo.
echo [MMacro HUD] Python 3.11 or newer was not found on this PC.
choice /c YN /n /m "Do you want MMacro HUD to download and install Python 3.13 automatically now? [Y/N]: "
if errorlevel 2 (
    echo Cancelled. Install Python from https://www.python.org/downloads/ and check "Add python.exe to PATH".
    pause
    exit /b 1
)
where winget >nul 2>&1
if %errorlevel% EQU 0 (
    winget install --id Python.Python.3.13 -e --accept-package-agreements --accept-source-agreements
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.2/python-3.13.2-amd64.exe' -OutFile '$env:TEMP\python-3.13.2-amd64.exe'; Start-Process -Wait '$env:TEMP\python-3.13.2-amd64.exe' -ArgumentList '/passive InstallAllUsers=0 PrependPath=1'"
)
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "C:\Python3*") do (
    if exist "%%~D\python.exe" (
        "%%~D\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
        if !errorlevel! EQU 0 (
            set "PY=%%~D\python.exe"
            goto :found_py
        )
    )
)
echo [MMacro HUD] Could not locate Python after install. Reopen this launcher or restart PC.
pause
exit /b 1

:found_py
if exist "%~dp0deps" set "PYTHONPATH=%~dp0deps;%PYTHONPATH%"

"%PY%" -c "import webview, cv2, rapidocr_onnxruntime, pynput, PIL, numpy, psutil, mousekey" >nul 2>&1
if %errorlevel% NEQ 0 (
    echo.
    echo [MMacro HUD] Some required Python packages are not installed yet.
    choice /c YN /n /m "Download and install missing packages from requirements.txt into .\deps now? [Y/N]: "
    if errorlevel 2 (
        echo Cancelled by user.
        pause
        exit /b 1
    )
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

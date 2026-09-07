@echo off
setlocal enabledelayedexpansion

:: ============================================================
::  OTT Giveaway Bot - One-Click Setup & Run
::  Fresh Windows PC pe ek click mein sab install ho jayega
:: ============================================================

title OTT Bot - Setup ^& Run

echo.
echo ============================================================
echo     OTT GIVEAWAY BOT - COMPLETE SETUP
echo     Telegram Bot + Web Admin Panel
echo ============================================================
echo.

:: --------------------------------------------------
:: STEP 0: Admin check
:: --------------------------------------------------
echo [STEP 0/6] Checking administrator privileges...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Not running as Administrator.
    echo [WARNING] If Python needs to be installed, please right-click
    echo           this file and select "Run as administrator".
    echo.
)

:: --------------------------------------------------
:: STEP 1: Check if Python is installed
:: --------------------------------------------------
echo [STEP 1/6] Checking Python installation...
echo.

set "PYTHON_CMD="
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :python_found
)

python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python3"
    goto :python_found
)

py --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=py"
    goto :python_found
)

for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
) do (
    if exist %%P (
        set "PYTHON_CMD=%%~P"
        goto :python_found
    )
)

echo [INFO] Python is NOT installed on this system.
echo [INFO] Downloading Python 3.12.x installer...
echo.

curl --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] curl is not available. Please install Python manually.
    pause
    exit /b 1
)

set "PYTHON_INSTALLER=%TEMP%\python_installer.exe"
curl -L -o "%PYTHON_INSTALLER%" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"

if not exist "%PYTHON_INSTALLER%" (
    echo [ERROR] Failed to download Python installer!
    pause
    exit /b 1
)

echo [INFO] Installing Python 3.12 (this may take 1-2 minutes)...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1

if %errorlevel% neq 0 (
    echo [WARNING] Silent install failed. Opening interactive installer...
    "%PYTHON_INSTALLER%" PrependPath=1
)

del "%PYTHON_INSTALLER%" >nul 2>&1
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
    goto :python_found
)

echo [ERROR] Python installation could not be verified.
pause
exit /b 1

:python_found
echo [OK] Python found: "%PYTHON_CMD%"
for /f "tokens=*" %%v in ('"%PYTHON_CMD%" --version 2^>^&1') do echo [OK] Version: %%v
echo.

:: --------------------------------------------------
:: STEP 2: Check Python version
:: --------------------------------------------------
echo [STEP 2/6] Verifying Python version...
"%PYTHON_CMD%" -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.8 or higher is required!
    pause
    exit /b 1
)
echo [OK] Python version is compatible.
echo.

:: --------------------------------------------------
:: STEP 3: Change to bot directory
:: --------------------------------------------------
echo [STEP 3/6] Setting up working directory...
cd /d "%~dp0"
echo [OK] Working directory: %cd%
echo.

:: --------------------------------------------------
:: STEP 4: Create Virtual Environment
:: --------------------------------------------------
echo [STEP 4/6] Creating Python virtual environment...
if exist "venv\Scripts\activate.bat" (
    echo [OK] Virtual environment already exists. Reusing it.
) else (
    echo [INFO] Creating new virtual environment 'venv'...
    "%PYTHON_CMD%" -m venv venv
    echo [OK] Virtual environment created.
)
echo.

:: --------------------------------------------------
:: STEP 5: Activate venv and install dependencies
:: --------------------------------------------------
echo [STEP 5/6] Installing Python dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
pip install flask flask-login python-telegram-bot==22.2 requests schedule APScheduler >nul 2>&1
echo [OK] All Python dependencies installed.
echo.

:: --------------------------------------------------
:: STEP 6: Start Bot
:: --------------------------------------------------
echo [STEP 6/6] Starting the bot...
echo.
echo ============================================================
echo     SETUP COMPLETE! Starting Bot + Web Admin Panel...
echo ============================================================
echo     Web Admin Panel: http://localhost:5001
echo     Login: admin / admin123
echo ============================================================
echo.
python main.py

echo.
echo [INFO] Bot has stopped.
pause

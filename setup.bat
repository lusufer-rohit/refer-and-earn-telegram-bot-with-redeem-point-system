@echo off
echo [INFO] Starting setup for Windows...

echo [INFO] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH. Please install Python first.
    pause
    exit /b
)

echo [INFO] Creating virtual environment 'venv'...
python -m venv venv

echo [INFO] Activating virtual environment and installing requirements...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [SUCCESS] Setup Complete!
echo [INFO] Starting the bot automatically now...
echo.
call start.bat

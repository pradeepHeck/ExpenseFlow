@echo off
setlocal
if not exist "venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv venv
)
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Dependency installation failed. Check your internet connection and try again.
  pause
  exit /b 1
)
venv\Scripts\python.exe app.py
endlocal

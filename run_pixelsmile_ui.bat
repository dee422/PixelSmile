@echo off
setlocal

set "APP_DIR=%~dp0"
set "PY_EXE=C:\Users\deejo\anaconda3\envs\tts\python.exe"
set "APP_FILE=%APP_DIR%app.py"
set "URL=http://127.0.0.1:7861"

cd /d "%APP_DIR%"

if not exist "%PY_EXE%" (
  echo [ERROR] Python not found:
  echo %PY_EXE%
  pause
  exit /b 1
)

if not exist "%APP_FILE%" (
  echo [ERROR] app.py not found:
  echo %APP_FILE%
  pause
  exit /b 1
)

echo Checking dependencies...
"%PY_EXE%" -c "import gradio,requests,PIL; print('deps_ok')" >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies...
  "%PY_EXE%" -m pip install gradio requests pillow
  if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
  )
)

echo Starting PixelSmile UI...
echo Open: %URL%
"%PY_EXE%" "%APP_FILE%"

echo.
echo UI exited.
pause

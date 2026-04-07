@echo off
setlocal

set "APP_DIR=%~dp0"
set "PY_EXE=C:\Users\deejo\anaconda3\envs\tts\python.exe"

set "INPUT_DIR=%~1"
if "%INPUT_DIR%"=="" set "INPUT_DIR=%APP_DIR%assets"

set "LABEL_SOURCE=%~2"
if "%LABEL_SOURCE%"=="" set "LABEL_SOURCE=filename"

set "MODEL=%~3"
if "%MODEL%"=="" set "MODEL=llava:7b"

set "RAW_JSON=%APP_DIR%expression_library\library.demo.json"
set "NORM_JSON=%APP_DIR%expression_library\library.demo.normalized.json"
set "ALIASES_JSON=%APP_DIR%expression_library\aliases.template.json"
set "BUILD_SCRIPT=%APP_DIR%scripts\build_expression_library.py"
set "NORMALIZE_SCRIPT=%APP_DIR%scripts\normalize_expression_library.py"

echo.
echo [PixelSmile] Expression library quick test
echo APP_DIR:      %APP_DIR%
echo PY_EXE:       %PY_EXE%
echo INPUT_DIR:    %INPUT_DIR%
echo LABEL_SOURCE: %LABEL_SOURCE%
if /I "%LABEL_SOURCE%"=="ollama" echo MODEL:        %MODEL%
echo.

if not exist "%PY_EXE%" (
  echo [ERROR] Python not found:
  echo %PY_EXE%
  pause
  exit /b 1
)

if not exist "%BUILD_SCRIPT%" (
  echo [ERROR] Script not found:
  echo %BUILD_SCRIPT%
  pause
  exit /b 1
)

if not exist "%NORMALIZE_SCRIPT%" (
  echo [ERROR] Script not found:
  echo %NORMALIZE_SCRIPT%
  pause
  exit /b 1
)

if not exist "%INPUT_DIR%" (
  echo [ERROR] Input dir not found:
  echo %INPUT_DIR%
  pause
  exit /b 1
)

cd /d "%APP_DIR%"

if /I "%LABEL_SOURCE%"=="ollama" (
  "%PY_EXE%" "%BUILD_SCRIPT%" ^
    --input-dir "%INPUT_DIR%" ^
    --output "%RAW_JSON%" ^
    --label-source ollama ^
    --model "%MODEL%"
) else (
  "%PY_EXE%" "%BUILD_SCRIPT%" ^
    --input-dir "%INPUT_DIR%" ^
    --output "%RAW_JSON%" ^
    --label-source filename ^
    --filename-pattern prefix
)

if errorlevel 1 (
  echo.
  echo [ERROR] build_expression_library failed.
  pause
  exit /b 1
)

"%PY_EXE%" "%NORMALIZE_SCRIPT%" ^
  --input "%RAW_JSON%" ^
  --output "%NORM_JSON%" ^
  --aliases "%ALIASES_JSON%"

if errorlevel 1 (
  echo.
  echo [ERROR] normalize_expression_library failed.
  pause
  exit /b 1
)

echo.
echo [OK] Done.
echo Raw:        %RAW_JSON%
echo Normalized: %NORM_JSON%
echo.
echo Next: load Normalized JSON in ComfyUI node:
echo       PixelSmileExpressionLibraryLoad
pause
exit /b 0

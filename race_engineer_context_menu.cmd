@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo BLOCKED: no se recibio ningun archivo DuckDB.
  echo.
  pause
  exit /b 2
)

"%~dp0.venv\Scripts\python.exe" "%~dp0analyze_telemetry_file.py" "%~1"
set "RACE_ENGINEER_EXIT=%ERRORLEVEL%"

echo.
if "%RACE_ENGINEER_EXIT%"=="0" (
  echo Race Engineer termino correctamente.
) else (
  echo Race Engineer no completo el analisis. Codigo: %RACE_ENGINEER_EXIT%
)
echo.
pause
exit /b %RACE_ENGINEER_EXIT%

@echo off
setlocal
set "APP_DIR=%~dp0"
set "PYTHONW=%LocalAppData%\Python\pythoncore-3.14-64\pythonw.exe"
if exist "%PYTHONW%" (
  start "Race Engineer" "%PYTHONW%" "%APP_DIR%RaceEngineer.pyw"
  exit /b 0
)
start "Race Engineer" python "%APP_DIR%race_engineer_gui.py"
endlocal

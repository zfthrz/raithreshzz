@echo off
title Race Engineer Scheduler
set "SCHEDULER_CONTROL=%~dp0scheduler_control.ps1"
if not exist "%SCHEDULER_CONTROL%" set "SCHEDULER_CONTROL=%USERPROFILE%\Documents\GitHub\raithreshzz\scheduler_control.ps1"
if not exist "%SCHEDULER_CONTROL%" (
  echo No se encontro scheduler_control.ps1.
  echo Copia este archivo junto al script o conserva el repositorio en:
  echo %USERPROFILE%\Documents\GitHub\raithreshzz
  echo.
  echo Presiona una tecla para cerrar esta consola.
  pause >nul
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%SCHEDULER_CONTROL%"
if errorlevel 1 (
  echo.
  echo No se pudo abrir el controlador del scheduler.
) else (
  echo.
  echo El controlador grafico se cerro.
)
echo Presiona una tecla para cerrar esta consola.
pause >nul

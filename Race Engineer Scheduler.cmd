@echo off
title Race Engineer Scheduler
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0scheduler_control.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo abrir el controlador del scheduler.
) else (
  echo.
  echo El controlador grafico se cerro.
)
echo Presiona una tecla para cerrar esta consola.
pause >nul

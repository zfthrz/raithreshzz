@echo off
title Race Engineer Scheduler
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0scheduler_control.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo abrir el controlador del scheduler.
  echo Revisa el error anterior y presiona una tecla para cerrar.
  pause >nul
)

@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0Bosun.exe" (
  echo Bosun.exe is missing. Extract the complete Windows package first.
  pause
  exit /b 1
)
start "Bosun" cmd /k ""%~dp0Bosun.exe""
endlocal

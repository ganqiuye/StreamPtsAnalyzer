@echo off
setlocal
set "DIR=%~dp0"

if not exist "%DIR%_internal\" (
  echo.
  echo [ERROR] _internal folder not found.
  echo.
  echo Copy the ENTIRE StreamPtsAnalyzer folder to this location.
  echo Do NOT copy StreamPtsAnalyzer.exe alone.
  echo.
  echo Expected:
  echo   %DIR%StreamPtsAnalyzer.exe
  echo   %DIR%_internal\
  echo   %DIR%logo.ico
  echo.
  pause
  exit /b 1
)

start "" "%DIR%StreamPtsAnalyzer.exe"
endlocal

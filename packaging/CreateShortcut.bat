@echo off
setlocal
set "DIR=%~dp0"

if not exist "%DIR%StreamPtsAnalyzer.exe" (
  echo StreamPtsAnalyzer.exe not found.
  pause
  exit /b 1
)
if not exist "%DIR%logo.ico" (
  echo logo.ico not found. Copy the full StreamPtsAnalyzer folder.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=(Resolve-Path '%DIR%').Path;" ^
  "$desktop=[Environment]::GetFolderPath('Desktop');" ^
  "$lnk=Join-Path $desktop 'Stream PTS Analyzer.lnk';" ^
  "if (Test-Path $lnk) { Remove-Item $lnk -Force };" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath=Join-Path $d 'StreamPtsAnalyzer.exe';" ^
  "$s.WorkingDirectory=$d;" ^
  "$s.IconLocation=(Join-Path $d 'logo.ico')+',0';" ^
  "$s.Description='Media PTS analyzer';" ^
  "$s.Save()"

echo Desktop shortcut created.
pause
endlocal

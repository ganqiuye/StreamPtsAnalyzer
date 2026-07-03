@echo off
setlocal
cd /d "%~dp0.."

echo Installing build dependencies...
python -m pip install -e ".[gui,build]" || exit /b 1

echo Generating application icon...
python packaging\generate-icon.py || exit /b 1

echo Cleaning previous build output...
if exist build rmdir /s /q build
if exist dist\StreamPtsAnalyzer rmdir /s /q dist\StreamPtsAnalyzer

echo Building StreamPtsAnalyzer (onedir) ...
python -m PyInstaller packaging\streampts-gui.spec --noconfirm --clean
if errorlevel 1 (
  echo.
  echo Build FAILED. See error above.
  exit /b 1
)

if not exist "dist\StreamPtsAnalyzer\StreamPtsAnalyzer.exe" (
  echo.
  echo Build FAILED: dist\StreamPtsAnalyzer\StreamPtsAnalyzer.exe not found.
  exit /b 1
)

copy /Y "src\streampts\gui\assets\logo.ico" "dist\StreamPtsAnalyzer\logo.ico" >nul
copy /Y "packaging\CreateShortcut.bat" "dist\StreamPtsAnalyzer\CreateShortcut.bat" >nul
copy /Y "packaging\StreamPtsAnalyzer.cmd" "dist\StreamPtsAnalyzer\StreamPtsAnalyzer.cmd" >nul
copy /Y "packaging\DIST_README.txt" "dist\StreamPtsAnalyzer\README.txt" >nul

echo.
echo Done: dist\StreamPtsAnalyzer\StreamPtsAnalyzer.exe
echo IMPORTANT: copy the whole StreamPtsAnalyzer folder, not exe alone.
endlocal

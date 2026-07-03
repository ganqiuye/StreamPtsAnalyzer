Stream PTS Analyzer
===================

COPY THE ENTIRE FOLDER
----------------------
You must copy the whole StreamPtsAnalyzer folder:

  StreamPtsAnalyzer/
    StreamPtsAnalyzer.exe
    StreamPtsAnalyzer.cmd   (optional launcher with folder check)
    _internal/              REQUIRED - do not delete
    logo.ico
    CreateShortcut.bat
    README.txt

Do NOT copy StreamPtsAnalyzer.exe alone. Without _internal you will see:
  "Cannot load PyInstaller's embedded PKG archive"

After copying (example: D:\tools\StreamPtsAnalyzer\):

  1. Double-click StreamPtsAnalyzer.exe
     or StreamPtsAnalyzer.cmd (shows a clear error if _internal is missing)

  2. Desktop shortcut with logo:
     Run CreateShortcut.bat

Do not use "Send to desktop" if the icon is wrong; use CreateShortcut.bat instead.

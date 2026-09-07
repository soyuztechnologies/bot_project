@echo off

rem Use the batch file's own directory so it works regardless of install path.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" youtube_main.py
) else (
    python youtube_main.py
)

exit /b %ERRORLEVEL%
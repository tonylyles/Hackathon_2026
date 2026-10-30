@echo off
setlocal
chcp 65001 >nul
title Naiwa - PhotoBooth - VTube Studio 照相亭

rem Always run from the project directory, including when double-clicked.
pushd "%~dp0"
if errorlevel 1 goto directory_error

rem Keep Python's Chinese diagnostics readable in the Windows console.
set "PYTHONIOENCODING=utf-8"

if not exist ".venv\Scripts\python.exe" goto python_error
where ffmpeg >nul 2>&1
if errorlevel 1 goto ffmpeg_error

echo ========================================
echo   Naiwa - PhotoBooth - VTube Studio 照相亭
echo ========================================
echo Starting VTube Studio character capture; no local torch stylization.
echo Enable the VTS API and virtual camera before taking photos.
echo Press Q or use the Exit button to close the booth.
echo.
".venv\Scripts\python.exe" -m app.main --booth --vts-preview %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo [ERROR] The booth exited with code %RESULT%.
    echo Read the error above before closing this window.
    pause
)
popd
exit /b %RESULT%

:python_error
echo [ERROR] Project Python environment is missing.
echo Expected: %CD%\.venv\Scripts\python.exe
echo Set up the project dependencies before running this launcher.
popd
pause
exit /b 1

:ffmpeg_error
echo [ERROR] FFmpeg was not found in PATH.
echo Install FFmpeg and reopen this launcher.
popd
pause
exit /b 1

:directory_error
echo [ERROR] Cannot open the project directory.
pause
exit /b 1

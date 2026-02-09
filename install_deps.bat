@echo off
title Install Spotify Liked Songs Dependencies

echo.
echo =============================================
echo   Installing dependencies from requirements.txt
echo =============================================
echo.

:: Check if python is available
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found.
    echo        Please install Python and make sure it's added to PATH.
    echo        https://www.python.org/downloads/
    pause
    exit /b
)

:: Check if pip is available
python -m pip --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: pip not found.
    echo        Try running: python -m ensurepip --upgrade
    pause
    exit /b
)

echo Using Python:
python --version
echo.

echo Upgrading pip...
python -m pip install --upgrade pip

echo.
echo Installing packages...
python -m pip install -r requirements.txt

echo.
echo =============================================
echo               FINISHED!
echo =============================================
echo.

if %ERRORLEVEL% EQU 0 (
    echo All packages installed successfully!
) else (
    echo Some packages may have failed to install.
    echo Check the messages above for errors.
)

echo.
echo You can now run your script (e.g. python spotify_playlist_to_liked.py)
pause
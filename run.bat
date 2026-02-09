@echo off
title Spotify Playlist to Liked Songs

echo.

echo.

python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found.
    echo Please install Python and add it to PATH.
    pause
    exit /b
)

echo Starting spotify tool...
echo.

python spotify_playlist_to_liked.py

echo.
echo tool shutting down.
pause
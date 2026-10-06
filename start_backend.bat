@echo off
title Amazon PL Extractor - Extension Backend
echo ============================================================
echo Starting Amazon PL Extractor Backend Server (Port 8000)...
echo Keep this window open while using the Chrome Extension.
echo ============================================================
echo.

if exist "%~dp0dist\Amazon_PL_Backend\Amazon_PL_Backend.exe" (
    echo [OK] Running Standalone Backend (No Python required)...
    "%~dp0dist\Amazon_PL_Backend\Amazon_PL_Backend.exe"
    goto end
)

if exist "%~dp0Amazon_PL_Backend.exe" (
    echo [OK] Running Standalone Backend (No Python required)...
    "%~dp0Amazon_PL_Backend.exe"
    goto end
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    echo [OK] Running via local Python...
    python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload
    goto end
)

echo [ERROR] Neither standalone executable nor Python was found!
echo Please ensure dist\Amazon_PL_Backend\Amazon_PL_Backend.exe exists.
pause

:end

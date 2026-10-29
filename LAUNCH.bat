@echo off
:: =====================================================================
::  SEO Automation Bot — DAILY LAUNCHER
::  Double-click this file every day to start the dashboard.
::  Opens http://localhost:5050 in your browser automatically.
::
::  Requirements: Run SETUP.bat once first on a fresh laptop.
:: =====================================================================
title SEO Automation — Dashboard Launcher
color 0A

echo.
echo  ===========================================
echo    SEO Automation Bot - Dashboard Launcher
echo  ===========================================
echo.

:: ---- Check Docker is installed -----------------------------------------
where docker >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Docker Desktop is not installed.
    echo  Please run SETUP.bat first to set up the project.
    echo.
    pause
    exit /b 1
)

:: ---- Start Docker Desktop if the engine is not running -----------------
docker info >nul 2>&1
if errorlevel 1 (
    echo  Docker engine is not running. Starting Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo  Waiting for Docker to be ready (may take up to 60 seconds)...
    :WAIT_LOOP
    timeout /t 5 /nobreak >nul
    docker info >nul 2>&1
    if errorlevel 1 goto WAIT_LOOP
    echo  Docker is ready.
    echo.
)

:: ---- Change to the project directory -----------------------------------
cd /d "%~dp0"

:: ---- Start (or restart) the dashboard container ------------------------
echo  Starting dashboard...
docker compose up -d dashboard
if errorlevel 1 (
    echo.
    echo  ERROR: Could not start dashboard.
    echo  Make sure SETUP.bat was run successfully at least once.
    echo.
    pause
    exit /b 1
)

:: ---- Give Flask a moment to bind the port, then open browser -----------
echo  Opening dashboard in browser...
timeout /t 4 /nobreak >nul
start "" "http://localhost:5050"

echo.
echo  Dashboard is running at: http://localhost:5050
echo.
echo  Leave this window open while you work.
echo  To stop the dashboard, close this window or press Ctrl+C.
echo.

:: ---- Keep window open and tail docker logs (optional convenience) ------
docker compose logs -f dashboard

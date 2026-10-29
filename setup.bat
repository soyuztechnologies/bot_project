@echo off
:: =====================================================================
::  SEO Automation Bot — FIRST TIME SETUP
::  Double-click this file on a fresh laptop.
::  Installs Git, Docker Desktop, downloads the project, sets up
::  credentials, builds the Docker image, and opens the dashboard.
::
::  After setup is done, use LAUNCH.bat for daily use.
:: =====================================================================
title SEO Automation — First Time Setup

echo.
echo  ===========================================
echo    SEO Automation Bot - First Time Setup
echo  ===========================================
echo.
echo  Starting setup... (this window may flash — that is normal)
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

if errorlevel 1 (
    echo.
    echo  Setup encountered an error. See messages above.
    echo  Fix the issue and run SETUP.bat again.
    echo.
)

pause

@echo off
:: =====================================================================
::  SEO Automation Bot — STOP DASHBOARD
::  Double-click to cleanly shut down the dashboard container.
:: =====================================================================
title SEO Automation — Stop Dashboard
color 0C

echo.
echo  Stopping SEO Automation Dashboard...
echo.

cd /d "%~dp0"
docker compose down

echo.
echo  Dashboard stopped.
echo.
pause

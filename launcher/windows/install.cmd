@echo off
rem Entry point to run install.ps1 by double-click (bypasses the execution policy for this run only).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause

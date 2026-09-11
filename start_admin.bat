@echo off
title Admin Panel - Retro Bonus
echo ========================================
echo   Admin Panel - Family Market
echo ========================================
echo.
echo Starting on http://localhost:3000/admin.html (only this computer)
echo.
cd /d "%~dp0"
start "" /min cmd /c "timeout /t 2 >nul & start http://localhost:3000/admin.html"
python core\admin_server.py
pause

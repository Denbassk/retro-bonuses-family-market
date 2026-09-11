@echo off
title Admin Panel - Retro Bonus
echo ========================================
echo   Admin Panel - Family Market
echo ========================================
echo.
echo Starting on http://localhost:3000 ...
echo.

cd /d "D:\РЕТРО_БОНУСЫ Фэмэли маркет"
start "" /min cmd /c "timeout /t 2 >nul & start http://localhost:3000/admin.html"
python -m http.server 3000

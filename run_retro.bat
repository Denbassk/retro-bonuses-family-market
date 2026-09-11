@echo off
title Retro Bonus - Interactive Menu
cd /d "%~dp0"
python core\calculate_retro.py --menu
pause

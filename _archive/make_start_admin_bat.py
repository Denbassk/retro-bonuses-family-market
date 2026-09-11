"""Разовый: start_admin.bat -> локальный сервер админки core\\admin_server.py (CRLF, без кириллицы в пути)."""
from pathlib import Path
lines = [
    "@echo off",
    "title Admin Panel - Retro Bonus",
    "echo ========================================",
    "echo   Admin Panel - Family Market",
    "echo ========================================",
    "echo.",
    "echo Starting on http://localhost:3000/admin.html (only this computer)",
    "echo.",
    'cd /d "%~dp0"',
    'start "" /min cmd /c "timeout /t 2 >nul & start http://localhost:3000/admin.html"',
    r"python core\admin_server.py",
    "pause",
]
p = Path(__file__).resolve().parent.parent / "start_admin.bat"
p.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
print(p.read_text())

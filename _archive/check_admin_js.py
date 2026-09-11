"""Проверка синтаксиса inline-скриптов admin.html через node --check (без запуска)."""
import re, subprocess, tempfile, sys
from pathlib import Path
html = (Path(__file__).resolve().parent.parent / "admin.html").read_text(encoding="utf-8")
blocks = [m.group(1) for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)]
ok = True
for i, b in enumerate(blocks):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(b)
    r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(f"script #{i}: {len(b)} символов -> {'OK' if r.returncode == 0 else 'ОШИБКА'}")
    if r.returncode:
        ok = False
        print(r.stderr[-1500:])
sys.exit(0 if ok else 1)

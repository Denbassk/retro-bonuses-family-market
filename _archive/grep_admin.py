"""Разовый: номера строк по шаблону в admin.html -> output/grep_admin.txt. Запуск: python _archive\\grep_admin.py "шаблон" """
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
pat = re.compile(sys.argv[1])
fn = ROOT / (sys.argv[2] if len(sys.argv) > 2 else "admin.html")
out = [f"{i}: {l.rstrip()[:220]}" for i, l in enumerate(fn.read_text(encoding="utf-8").splitlines(), 1) if pat.search(l)]
(ROOT / "output" / "grep_admin.txt").write_text("\n".join(out), encoding="utf-8")

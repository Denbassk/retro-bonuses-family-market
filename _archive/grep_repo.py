"""Разовый: поиск шаблона по репозиторию (py, html, gs, js, sql, md) -> output/grep_repo.txt.
Также имена переменных .env (без значений). Запуск: python _archive\\grep_repo.py "шаблон" """
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
pat = re.compile(sys.argv[1])
out = []
for p in sorted(ROOT.rglob("*")):
    if p.suffix.lower() not in (".py", ".html", ".gs", ".js", ".sql", ".md", ".bat") or "_archive" in p.parts or ".git" in p.parts:
        continue
    try:
        for i, l in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pat.search(l):
                out.append(f"{p.relative_to(ROOT)}:{i}: {l.strip()[:200]}")
    except OSError:
        pass
env = ROOT / ".env"
if env.exists():
    out.append("\n.env keys: " + ", ".join(l.split("=", 1)[0] for l in env.read_text(encoding="utf-8").splitlines() if "=" in l))
(ROOT / "output" / "grep_repo.txt").write_text("\n".join(out), encoding="utf-8")
print(len(out))

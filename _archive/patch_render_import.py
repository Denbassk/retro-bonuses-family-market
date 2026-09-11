"""Разовый патч admin.html: заменить renderImportDraft (до importSelection) на _archive/new_render_import.js."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
fn = ROOT / "admin.html"
s = fn.read_text(encoding="utf-8")
a = s.index("function renderImportDraft() {")
b = s.index("function importSelection() {")
new = (ROOT / "_archive" / "new_render_import.js").read_text(encoding="utf-8")
s = s[:a] + new + s[b:]
old_t = "  return `<h3 style=\"margin:18px 0 8px;font-size:14px\">${title}</h3>"
assert s.count(old_t) == 1
s = s.replace(old_t, "  return (title ? `<h3 style=\"margin:18px 0 8px;font-size:14px\">${title}</h3>` : '') + `")
fn.write_text(s, encoding="utf-8")
print("ok")

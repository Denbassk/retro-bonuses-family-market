"""ЧАСТЬ B (проверка сборки плагина retro-lean) -> output/check_partB.txt. Только чтение."""
import json, hashlib, re
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
pj = ROOT / "build" / "retro-lean" / ".claude-plugin" / "plugin.json"
sk = ROOT / "build" / "retro-lean" / "skills" / "retro-lean" / "SKILL.md"
cp = ROOT / ".claude" / "skills" / "retro-lean" / "SKILL.md"
out = []
for p in (pj, sk, cp):
    out.append(f"{p.relative_to(ROOT)}: {'есть' if p.exists() else 'НЕТ'}"
               + (f", {p.stat().st_size} байт" if p.exists() else ""))
if pj.exists():
    raw = pj.read_bytes()
    out.append(f"plugin.json BOM: {'ДА' if raw[:3] == b'\xef\xbb\xbf' else 'нет'}")
    try:
        j = json.loads(raw.decode("utf-8-sig"))
        out.append(f"plugin.json валиден, ключи: {sorted(j)}; name={j.get('name')!r} version={j.get('version')!r}")
    except Exception as e:
        out.append(f"plugin.json НЕВАЛИДЕН: {e}")
        j = {}
else:
    j = {}
if sk.exists():
    raw = sk.read_bytes()
    out.append(f"SKILL.md BOM: {'ДА' if raw[:3] == b'\xef\xbb\xbf' else 'нет'}; "
               f"первые байты: {raw[:12]!r}; перевод строки: {'CRLF' if b'\r\n' in raw[:200] else 'LF'}")
    txt = raw.decode("utf-8-sig")
    out.append(f"начинается ровно с '---': {'ДА' if txt.startswith('---\n') or txt.startswith('---\r\n') else 'НЕТ'}")
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", txt, re.S)
    if m:
        fm = dict(re.findall(r"^([A-Za-z_]+):\s*(.+?)\s*$", m.group(1), re.M))
        out.append(f"фронтматтер: name={fm.get('name')!r}, description непустой: "
                   f"{'ДА' if (fm.get('description') or '').strip() else 'НЕТ'} ({len(fm.get('description') or '')} симв.)")
        out.append(f"совпадение имён: SKILL.md={fm.get('name')!r}, plugin.json={j.get('name')!r}, папка={sk.parent.name!r} -> "
                   f"{'СОВПАДАЮТ' if fm.get('name') == j.get('name') == sk.parent.name else 'НЕ СОВПАДАЮТ'}")
    else:
        out.append("фронтматтер не найден")
if sk.exists() and cp.exists():
    a, b = sk.read_bytes(), cp.read_bytes()
    out.append(f"копия .claude/skills побайтово: {'СОВПАДАЕТ' if a == b else 'ОТЛИЧАЕТСЯ'} "
               f"(sha {hashlib.sha256(a).hexdigest()[:8]} / {hashlib.sha256(b).hexdigest()[:8]}, {len(a)} / {len(b)} байт)")
(ROOT / "output" / "check_partB.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

"""Проверка ЧАСТЬ A (только чтение): литерал 0.80 в calculate_retro, наличие таблиц/колонки в БД.
-> output/check_partA.txt"""
import os, re, sys, json, urllib.request, urllib.error
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
out = []

f = ROOT / "core" / "calculate_retro.py"
hits = [(i, l.strip()) for i, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if re.search(r"0\.80\b|0\.8\b", l)]
out.append(f"[A1] core/calculate_retro.py, вхождений 0.80/0.8: {len(hits)}")
for i, l in hits:
    out.append(f"   строка {i}: {l[:120]}")

out.append("\n[A3] состояние БД (REST-проба: 200 = есть, 404/PGRST205 = нет таблицы, 400/42703 = нет колонки)")
for q, what in (("retro_reconciliation?select=supplier_id&limit=1", "таблица retro_reconciliation"),
                ("retro_fact_imports?select=id&limit=1", "таблица retro_fact_imports"),
                ("retro_adjustments?select=payment_mode&limit=1", "колонка retro_adjustments.payment_mode"),
                ("retro_adjustments?select=id&limit=1", "таблица retro_adjustments")):
    req = urllib.request.Request(f"{sb.URL}/rest/v1/{q}", headers={"apikey": sb.KEY, "Authorization": f"Bearer {sb.KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out.append(f"   {what}: ДА (HTTP {r.status})")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        code = (json.loads(body).get("code") if body.startswith("{") else "") or ""
        out.append(f"   {what}: НЕТ (HTTP {e.code}, code={code})")

for t, cnt in (("retro_reconciliation", 1), ("retro_fact_imports", 1)):
    try:
        n = sb.get(t, "select=id&limit=2000")
        out.append(f"   {t}: строк {len(n)}")
    except Exception as e:
        out.append(f"   {t}: нет данных ({str(e)[:60]})")
try:
    adj = sb.get("retro_adjustments", "select=payment_mode")
    from collections import Counter
    out.append(f"   retro_adjustments по режимам: {dict(Counter(a.get('payment_mode') for a in adj))}")
except Exception as e:
    out.append(f"   retro_adjustments payment_mode: {str(e)[:80]}")
(ROOT / "output" / "check_partA.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

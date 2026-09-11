"""Разовый probe: июль после пересчёта с сохранением - сохранённое теперь = пересчёт на текущих данных?
+ ничего лишнего не тронуто (created_at сегодня только у списка), Оболонь не тронута."""
import os, sys, csv, re
from pathlib import Path
from collections import defaultdict
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
rows = list(csv.reader(open(ROOT / "_archive" / "recalc_now_2026-01_2026-08.csv", encoding="utf-8-sig"), delimiter=";"))
h = rows[0]; k = h.index("2026-07")
recalc = defaultdict(float)
for r in rows[1:]:
    if r and r[k].strip():
        recalc[r[0]] += float(r[k])
recalc["Маршалл Табако"] = 1600.0  # порог 10 SKU после правки правила
calcs = sb.get("retro_calculations", "period_label=eq.2026-07&select=supplier_id,total_retro,status,created_at")
today = [c for c in calcs if c["created_at"].startswith("2026-09-11")]
print(f"июль: расчётов {len(calcs)}, пересохранено сегодня {len(today)}")
bad = 0
for c in sorted(calcs, key=lambda c: sup.get(c["supplier_id"], "")):
    nm = sup.get(c["supplier_id"], "?"); t = float(c["total_retro"] or 0); n = recalc.get(nm)
    fresh = c["created_at"].startswith("2026-09-11")
    ok = n is not None and abs(t - n) < 0.01
    if fresh or not ok or "оболон" in nm.lower():
        bad += (not ok)
        print(f"  {'СЕГОДНЯ' if fresh else '       '} {nm[:44]:<45}{t:>12,.2f}  пересчёт {n if n is not None else '-':>12}  {'OK' if ok else 'РАЗНИЦА'}  {c['status']}")
print("расхождений с пересчётом:", bad)

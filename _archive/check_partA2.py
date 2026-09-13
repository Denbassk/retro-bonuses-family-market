"""Свежесть сверки/диагностики: когда последний прогон и есть ли строка «данные» -> output/check_partA2.txt"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
rows = sb.get("retro_reconciliation", "select=checked_at,diagnosis,status")
last = max((r["checked_at"] or "") for r in rows)
with_diag = sum(1 for r in rows if r.get("diagnosis"))
with_data = sum(1 for r in rows if "данные" in (r.get("diagnosis") or ""))
from collections import Counter
st = Counter(r["status"] for r in rows)
(ROOT / "output" / "check_partA2.txt").write_text(
    f"retro_reconciliation: строк {len(rows)}, последний checked_at {last[:19]}\n"
    f"с диагнозом {with_diag}, из них со строкой «данные» {with_data}\n"
    f"статусы: {dict(st.most_common())}\n", encoding="utf-8")
print("ok")

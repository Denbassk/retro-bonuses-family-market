"""Разовый: сохранённый расчёт августа по затронутым правками поставщикам (до пересчёта)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb
sp = {s["name"]: s["id"] for s in sb.get("suppliers", "select=id,name")}
for name in [n for n in sp if n.startswith("Інтрейд Мікс (Батоша") or n.startswith("Союз (Жако")]:
    rows = sb.get("retro_calculations", f"supplier_id=eq.{sp[name]}&period_label=gte.2026-07&select=period_label,total_retro,status")
    print(f"{name[:46]:<48}" + " | ".join(f"{r['period_label']} {float(r['total_retro']):,.2f} [{r['status']}]"
                                          for r in sorted(rows, key=lambda x: x["period_label"])))

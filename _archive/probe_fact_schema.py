"""Разовый probe: колонки целевых таблиц этапа 3-4 по OpenAPI PostgREST + статусы расчётов."""
import sys, json
from pathlib import Path
sys.path.insert(0, str((Path(__file__).resolve().parent.parent) / "core"))
import sb

spec = sb._req(f"{sb.URL}/rest/v1/")
defs = spec.get("definitions", {})
for t in ("retro_payments_fact", "store_opening_bonuses", "retro_fact_name_map",
          "retro_reconciliation", "retro_adjustments"):
    d = defs.get(t)
    if not d:
        print(f"{t}: НЕТ ТАБЛИЦЫ"); continue
    req = set(d.get("required", []))
    cols = [f"{k}{'*' if k in req else ''}:{v.get('format', v.get('type'))}" for k, v in d["properties"].items()]
    print(f"{t}: {', '.join(cols)}")

rows = sb.get("retro_payments_fact", "select=supplier_id,period_label,amount_paid,import_source")
print(f"\nretro_payments_fact строк: {len(rows)}")
from collections import Counter
print("  по import_source:", Counter(r.get("import_source") for r in rows))
print("  по периодам:", sorted(Counter(r["period_label"] for r in rows).items()))
calc = sb.get("retro_calculations", "select=period_label,status")
print("\nretro_calculations статусы:", sorted(Counter((c["period_label"], c["status"]) for c in calc).items()))

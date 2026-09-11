"""Разовый probe: строки retro_calculation_details без правила (доп. выплаты из админки / фикс-бонусы)."""
import sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, str((Path(__file__).resolve().parent.parent) / "core"))
import sb
calc = {c["id"]: c for c in sb.get("retro_calculations", "select=id,supplier_id,period_label,status")}
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
rows = sb.get("retro_calculation_details", "retro_rule_id=is.null&select=id,calculation_id,retro_amount,amount_purchased,applied_percent,notes")
print("без правила:", len(rows))
for r in sorted(rows, key=lambda r: (calc.get(r["calculation_id"], {}).get("period_label", ""), sup.get(calc.get(r["calculation_id"], {}).get("supplier_id"), ""))):
    c = calc.get(r["calculation_id"], {})
    print(f"  {c.get('period_label')} {sup.get(c.get('supplier_id'), '?')[:34]:<35}{float(r['retro_amount'] or 0):>11,.2f}  "
          f"base={float(r['amount_purchased'] or 0):,.0f} pct={r['applied_percent']}  {c.get('status')}  {(r['notes'] or '')[:60]}")

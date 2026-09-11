"""Разовая правка 11.09.2026 по решению пользователя: Маршалл Табако, порог покрытия 8 -> 10 SKU.
Август не меняется (все 13 ТТ имеют 10 SKU = 10 400 = факт), июль: 4 ТТ -> 2 ТТ.
Без --apply только показывает."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb

sid = [s for s in sb.get("suppliers", "select=id,name") if s["name"] == "Маршалл Табако"]
assert len(sid) == 1, sid
sid = sid[0]["id"]
bids = [b["id"] for b in sb.get("supplier_brands", f"supplier_id=eq.{sid}&select=id")]
rules = [r for r in sb.get("retro_rules", "select=id,supplier_brand_id,retro_base_type,min_sku_per_store,price_per_store,status,notes")
         if r["supplier_brand_id"] in bids and r["retro_base_type"] == "coverage_per_store" and r["status"] == "active"]
assert len(rules) == 1, rules
r = rules[0]
print(f"правило {r['id']}: min_sku_per_store={r['min_sku_per_store']} price={r['price_per_store']}\n  notes: {r['notes']}")
for c in sb.get("retro_calculations", f"supplier_id=eq.{sid}&select=period_label,total_retro,status&order=period_label"):
    print(f"  расчёт {c['period_label']}: {c['total_retro']} ({c['status']})")
new_notes = (r["notes"] or "").replace("[2026-08] Порог снижен 10→8 SKU.",
             "[11.09.2026] Порог 10 SKU (8 ставился подгонкой; в августе все 13 ТТ имеют 10 SKU).")
if "--apply" in sys.argv:
    res = sb._req(f"{sb.URL}/rest/v1/retro_rules?id=eq.{r['id']}", {"min_sku_per_store": 10, "notes": new_notes},
                  "PATCH", {"Prefer": "return=representation"})
    print("ЗАПИСАНО:", res[0]["min_sku_per_store"], "|", res[0]["notes"])
else:
    print("пробный прогон, для записи --apply")

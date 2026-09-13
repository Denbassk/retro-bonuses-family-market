"""Разовый, только чтение: правила ЗЛАГОДА-ОПТ (бренд «Тиса коньяк») - пересечение SKU правил 10% и 17%,
и состав правила 10% с наименованиями. Имена берём из retro_calculation_sku_details (без BigQuery).
-> output/probe_zlagoda_rules.txt"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
sup = {s["name"]: s["id"] for s in sb.get("suppliers", "select=id,name")}
sid = sup["ЗЛАГОДА-ОПТ"]
brands = {b["id"]: b["name"] for b in sb.get("supplier_brands", f"supplier_id=eq.{sid}&select=id,name")}
rules = [r for r in sb.get("retro_rules", f"supplier_brand_id=in.({','.join(brands)})&select=*")]
names = {}
for c in sb.get("retro_calculations", f"supplier_id=eq.{sid}&select=id"):
    for s in sb.get("retro_calculation_sku_details", f"calculation_id=eq.{c['id']}&select=barcode,product_name"):
        names.setdefault(str(s["barcode"]), s.get("product_name") or "")
out = []
by = {}
for r in rules:
    key = f"{brands.get(r['supplier_brand_id'])} {r.get('retro_min')}% [{r['status']}]"
    by[key] = {str(b) for b in (r.get("sku_barcodes") or [])}
    out.append(f"{key}: SKU {len(by[key])}, {r['valid_from']}..{r.get('valid_to')} | {(r.get('notes') or '')[:60]}")
keys = [k for k in by if "Тиса" in k]
out.append("\nпересечение SKU правил бренда «Тиса коньяк»:")
for i, a in enumerate(keys):
    for b in keys[i + 1:]:
        both = by[a] & by[b]
        out.append(f"  {a} ∩ {b}: {len(both)}")
        for bc in sorted(both):
            out.append(f"      {bc}  {names.get(bc, '(нет в разбивке расчёта)')[:60]}")
ten = next((k for k in keys if k.startswith("Тиса коньяк 10")), None)
if ten:
    out.append(f"\nсостав правила «{ten}» ({len(by[ten])} SKU):")
    for bc in sorted(by[ten]):
        nm = names.get(bc, "(нет в разбивке расчёта)")
        mark = "  <-- не коньяк" if any(w in nm.lower() for w in ("вода", "корм", "пюре", "напій", "сік")) else ""
        out.append(f"    {bc}  {nm[:60]}{mark}")
(ROOT / "output" / "probe_zlagoda_rules.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

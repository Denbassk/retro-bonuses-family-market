"""Разовый probe: что лежит в retro_adjustments и additional_payments фактов -> output/probe_adjustments_model.txt"""
import os, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
out = []
adj = sb.get("retro_adjustments", "select=*")
out.append(f"retro_adjustments: {len(adj)}; колонки: {sorted(adj[0].keys()) if adj else '-'}")
for a in adj:
    out.append(f"  {sup.get(a['supplier_id'], '?')[:30]:<30} {a['period_label']} {a['amount']:>10} {a.get('bonus_form')} "
               f"src={a.get('source')} | {a.get('notes')}")
det = sb.get("retro_calculation_details", "select=id,calculation_id,retro_amount,notes,adjustment_id&adjustment_id=not.is.null")
out.append(f"\nстрок расчёта с adjustment_id: {len(det)}")
facts = sb.get("retro_payments_fact", "select=supplier_id,period_label,amount_paid,additional_payments,notes")
n = 0
out.append("\nфакты с additional_payments:")
for f in facts:
    ap = f.get("additional_payments") or []
    if ap:
        n += 1
        out.append(f"  {sup.get(f['supplier_id'], '?')[:30]:<30} {f['period_label']} paid={f['amount_paid']} ap={json.dumps(ap, ensure_ascii=False)}")
out.append(f"итого: {n}")
(ROOT / "output" / "probe_adjustments_model.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

"""Разовый probe: что лежит в retro_payments_fact.additional_payments (ключи, у кого)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
for f in sb.get("retro_payments_fact", "additional_payments=not.is.null&select=supplier_id,period_label,amount_paid,additional_payments,notes"):
    ap = f["additional_payments"]
    if ap:
        print(sup.get(f["supplier_id"]), f["period_label"], f["amount_paid"], json.dumps(ap, ensure_ascii=False)[:300], "|", (f["notes"] or "")[:80])

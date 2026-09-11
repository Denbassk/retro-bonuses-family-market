"""Разовый probe: для пар с доплатами - расчёт, факт, Excel, статус сверки -> output/probe_adjustments_recon.txt
Цель: понять по числам, входили ли доплаты в «Оплачено» (in_payment) или платились отдельно."""
import os, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
pairs = {}
for a in sb.get("retro_adjustments", "select=supplier_id,period_label,amount,notes"):
    pairs.setdefault((a["supplier_id"], a["period_label"]), {"adj": 0.0, "ap": 0.0, "txt": []})
    pairs[(a["supplier_id"], a["period_label"])]["adj"] += float(a["amount"])
    pairs[(a["supplier_id"], a["period_label"])]["txt"].append(a["notes"][:25])
for f in sb.get("retro_payments_fact", "select=supplier_id,period_label,additional_payments"):
    for e in f.get("additional_payments") or []:
        if e.get("amount"):
            p = pairs.setdefault((f["supplier_id"], f["period_label"]), {"adj": 0.0, "ap": 0.0, "txt": []})
            p["ap"] += float(e["amount"])
            p["txt"].append("ap:" + str(e.get("note") or e.get("label")))
calc = {(c["supplier_id"], c["period_label"]): float(c["total_retro"] or 0)
        for c in sb.get("retro_calculations", "select=supplier_id,period_label,total_retro")}
fact = {(f["supplier_id"], f["period_label"]): float(f["amount_paid"] or 0)
        for f in sb.get("retro_payments_fact", "select=supplier_id,period_label,amount_paid")}
rec = {(r["supplier_id"], r["period_label"]): r for r in sb.get(
    "retro_reconciliation", "select=supplier_id,period_label,status,delta,excel_amount,group_key")}
out = [f"{'поставщик':<28} {'период':<8} {'расчёт(с adj)':>13} {'adj':>9} {'ap':>9} {'факт':>10} {'Δ факт-расчёт':>13} {'Δ если adj вне':>14} статус | прим"]
for (sid, per), p in sorted(pairs.items(), key=lambda x: (sup.get(x[0][0], ""), x[0][1])):
    c, f = calc.get((sid, per)), fact.get((sid, per))
    r = rec.get((sid, per), {})
    d = (f or 0) - (c or 0)
    out.append(f"{sup.get(sid, '?')[:28]:<28} {per:<8} {c if c is not None else '-':>13} {p['adj']:>9.2f} {p['ap']:>9.2f} "
               f"{f if f is not None else '-':>10} {d:>13.2f} {(f or 0) - ((c or 0) - p['adj']):>14.2f} "
               f"{r.get('status')} {r.get('group_key') or ''} | {'; '.join(p['txt'])}")
(ROOT / "output" / "probe_adjustments_recon.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

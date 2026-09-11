"""Разовый: Юрія, строки расчёта по правилу 15% (сгущёнка) и по 12% за июль-август -> output/probe_yuria_condensed2.txt"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
sid = [s for s in sb.get("suppliers", "select=id,name") if s["name"] == "Юрія"][0]["id"]
out = []
for c in sb.get("retro_calculations", f"supplier_id=eq.{sid}&period_label=gte.2026-06&select=id,period_label,total_retro"):
    out.append(f"{c['period_label']} total_retro {c['total_retro']}")
    for d in sb.get("retro_calculation_details", f"calculation_id=eq.{c['id']}&select=id,retro_rule_id,applied_percent,amount_purchased,amount_returned,amount_net,retro_amount,notes"):
        net = float(d["amount_net"] or 0)
        out.append(f"   rule {str(d['retro_rule_id'])[:8]} {d['applied_percent']}% приход {float(d['amount_purchased'] or 0):,.2f} "
                   f"возвр {float(d['amount_returned'] or 0):,.2f} база {net:,.2f} ретро {float(d['retro_amount'] or 0):,.2f} "
                   f"= {(float(d['retro_amount'] or 0) / net * 100 if net else 0):.2f}% | {d['notes']}")
        for s in sb.get("retro_calculation_sku_details", f"detail_id=eq.{d['id']}&select=barcode,product_name,amount_purchased,amount_returned,retro_amount"):
            if str(s["barcode"]) in ("4820261570113", "4820261570816"):
                out.append(f"      {s['barcode']} {s['product_name'][:45]} приход {float(s['amount_purchased'] or 0):,.2f} "
                           f"возвр {float(s['amount_returned'] or 0):,.2f} ретро {float(s['retro_amount'] or 0):,.2f}")
(ROOT / "output" / "probe_yuria_condensed2.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

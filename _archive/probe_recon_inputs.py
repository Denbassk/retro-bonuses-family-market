"""Разовый probe перед автосверкой: ручные/составные в маппинге, безнал-поставщики, лаг оплат по датам."""
import os, sys
from pathlib import Path
from datetime import date
from collections import Counter
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb

sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
for m in sb.get("retro_fact_name_map", "or=(needs_manual.eq.true,split_targets.not.is.null,is_ignored.eq.true)"
                "&select=excel_name_raw,supplier_id,is_ignored,split_targets,needs_manual,notes"):
    print("map:", m["excel_name_raw"], "->", sup.get(m["supplier_id"]), "| ign", m["is_ignored"], "| manual", m["needs_manual"],
          "| split", m["split_targets"], "|", (m.get("notes") or "")[:60])
print("безнал-кандидаты:", [n for n in sup.values() if any(k in n for k in ("Аванта", "Еліт", "Ново-Бавар", "Сервіс Про"))])
lag = Counter()
for f in sb.get("retro_payments_fact", "payment_date=not.is.null&select=id,supplier_id,period_label,payment_date,amount_paid"):
    y, mth = map(int, f["period_label"].split("-"))
    end = date(y + (mth == 12), mth % 12 + 1, 1)
    try:
        d = (date.fromisoformat(f["payment_date"]) - end).days
    except ValueError:
        print("КРИВАЯ ДАТА:", sup.get(f["supplier_id"]), f["period_label"], f["payment_date"], f["amount_paid"], f["id"])
        continue
    if d < -31 or d > 200:
        print("ПОДОЗРИТЕЛЬНАЯ ДАТА:", sup.get(f["supplier_id"]), f["period_label"], f["payment_date"], f["amount_paid"])
    lag[(d // 30) + 1 if d >= 0 else 0] += 1
print("лаг оплаты (месяцев после конца периода -> кол-во фактов):", sorted(lag.items()))
print("колонки supplier_payments:", list(sb.get("supplier_payments", "select=*&limit=1")[0].keys()))

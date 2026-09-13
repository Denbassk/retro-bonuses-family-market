"""Разовая правка справочника: алиас «Українська Злагода» у ЗЛАГОДА-ОПТ -> alias_type=excluded.
Проверено: за 01-04 через него прошло 1 199 292 ₴, из них в правилах 0 - ретро по нему не начислялось,
весь товар УДК (владелец - Промтехнорент, не ретро). Расчёты не меняются, чистится только база сверки.
Запуск: python _archive\\fix_alias_ukr_zlagoda.py [--apply]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb

NAME = "Українська Злагода"
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
rows = [a for a in sb.get("supplier_aliases", "select=id,alias_name,alias_type,supplier_id,supplier_brand_id")
        if (a["alias_name"] or "").strip() == NAME]
for a in rows:
    print(f"{a['id']}  «{a['alias_name']}» -> {sup.get(a['supplier_id'], '?')} [{a['alias_type']}]")
if not rows:
    sys.exit("алиас не найден")
if "--apply" not in sys.argv:
    sys.exit("будет установлен alias_type=excluded. Для записи: --apply")
for a in rows:
    # CHECK supplier_aliases_type_brand_check: у excluded бренд должен быть пустым
    sb._req(f"{sb.URL}/rest/v1/supplier_aliases?id=eq.{a['id']}",
            {"alias_type": "excluded", "supplier_brand_id": None}, "PATCH", {"Prefer": "return=minimal"})
chk = [a for a in sb.get("supplier_aliases", "select=alias_name,alias_type,supplier_id")
       if (a["alias_name"] or "").strip() == NAME]
print("после правки:", [(x["alias_type"], sup.get(x["supplier_id"], "?")) for x in chk])

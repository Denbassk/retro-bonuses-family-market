"""Разовая правка справочника: добавить баркод 4820139280786 (Бренді Тіса Три Зірочки V.S. 0,5л)
в sku_barcodes правила «Тиса коньяк 10%» ЗЛАГОДА-ОПТ. Проверено: приход есть (июнь 18 663, август 7 197),
ни в одном активном правиле баркода нет, переплата июня 1 867 = 18 663 x 10%.
Запуск: python _archive\\fix_zlagoda_add_sku.py [--apply]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb

RULE = "1dded774-fcff-4443-9b43-e0c688447225"   # ЗЛАГОДА-ОПТ / Тиса коньяк 10% active
BC = "4820139280786"
r = sb.get("retro_rules", f"id=eq.{RULE}&select=id,retro_min,status,sku_barcodes")[0]
cur = [str(x) for x in (r["sku_barcodes"] or [])]
print(f"правило {RULE[:8]} {r['retro_min']}% [{r['status']}]: SKU было {len(cur)}, баркод в списке: {BC in cur}")
if BC in cur:
    sys.exit("уже добавлен - ничего не делаю")
new = sorted(cur + [BC])
if "--apply" not in sys.argv:
    sys.exit(f"будет добавлен {BC}, станет {len(new)} SKU. Для записи: --apply")
sb._req(f"{sb.URL}/rest/v1/retro_rules?id=eq.{RULE}", {"sku_barcodes": new}, "PATCH", {"Prefer": "return=minimal"})
chk = [str(x) for x in sb.get("retro_rules", f"id=eq.{RULE}&select=sku_barcodes")[0]["sku_barcodes"]]
print(f"записано: SKU стало {len(chk)}, баркод в списке: {BC in chk}")

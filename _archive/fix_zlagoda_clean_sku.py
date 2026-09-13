"""Разовая правка справочника: убрать из правила «Тиса коньяк 10%» (ЗЛАГОДА-ОПТ) 8 баркодов,
не имеющих отношения к коньяку (вода, корм Пан Кот, пюре). Все восемь есть в правиле «ЗЛАГОДА продукти 10%»
с той же ставкой, поэтому деньги не меняются - приход перестаёт делиться между двумя правилами.
Запуск: python _archive\\fix_zlagoda_clean_sku.py [--apply]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb

RULE = "1dded774-fcff-4443-9b43-e0c688447225"   # Тиса коньяк 10% active
OTHER = "0f7ff634-a24b-4e0b-9410-cca3678cf86a"  # ЗЛАГОДА продукти 10% active
DROP = ["4820001020021", "4820001021066", "4820001830071", "4820111140985",
        "4820111141005", "4820111141029", "4820111141036", "4820219343028"]
r = sb.get("retro_rules", f"id=eq.{RULE}&select=sku_barcodes")[0]
o = {str(x) for x in (sb.get("retro_rules", f"id=eq.{OTHER}&select=sku_barcodes")[0]["sku_barcodes"] or [])}
cur = [str(x) for x in (r["sku_barcodes"] or [])]
missing = [b for b in DROP if b not in o]
print(f"в правиле «Тиса коньяк 10%»: {len(cur)} SKU; к удалению {len([b for b in DROP if b in cur])}")
print(f"все удаляемые есть в «ЗЛАГОДА продукти 10%»: {not missing}" + (f"; НЕТ там: {missing}" if missing else ""))
if missing:
    sys.exit("остановка: удаление оставит SKU без правила")
new = [b for b in cur if b not in DROP]
if "--apply" not in sys.argv:
    sys.exit(f"станет {len(new)} SKU (только коньяк и бренді). Для записи: --apply")
sb._req(f"{sb.URL}/rest/v1/retro_rules?id=eq.{RULE}", {"sku_barcodes": sorted(new)}, "PATCH", {"Prefer": "return=minimal"})
chk = [str(x) for x in sb.get("retro_rules", f"id=eq.{RULE}&select=sku_barcodes")[0]["sku_barcodes"]]
print(f"записано: стало {len(chk)} SKU, из удаляемых осталось {len([b for b in DROP if b in chk])}")

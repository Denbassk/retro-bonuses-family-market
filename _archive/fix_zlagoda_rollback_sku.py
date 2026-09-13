"""Откат: вернуть 8 баркодов в правило «Тиса коньяк 10%». Их удаление уронило август
с 25 082,25 до 20 887,97 (-4 194,28): приход этих SKU приходит по бренду «Тиса коньяк»
и в правило «ЗЛАГОДА продукти» не попадает. Значит списки не дублируют друг друга."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb
RULE = "1dded774-fcff-4443-9b43-e0c688447225"
BACK = ["4820001020021", "4820001021066", "4820001830071", "4820111140985",
        "4820111141005", "4820111141029", "4820111141036", "4820219343028"]
cur = [str(x) for x in (sb.get("retro_rules", f"id=eq.{RULE}&select=sku_barcodes")[0]["sku_barcodes"] or [])]
new = sorted(set(cur) | set(BACK))
print(f"было {len(cur)} SKU, станет {len(new)}")
if "--apply" in sys.argv:
    sb._req(f"{sb.URL}/rest/v1/retro_rules?id=eq.{RULE}", {"sku_barcodes": new}, "PATCH", {"Prefer": "return=minimal"})
    chk = [str(x) for x in sb.get("retro_rules", f"id=eq.{RULE}&select=sku_barcodes")[0]["sku_barcodes"]]
    print(f"восстановлено: {len(chk)} SKU, все 8 на месте: {all(b in chk for b in BACK)}")

"""Разовые правки справочника по решениям владельца 14.09:
1) Батоша: 8 новых SKU августа -> sku_barcodes правила e8b86718 (бренд Батоша, 15%).
2) Золоте Зерно: 4820017291873 -> правило 617f21d5 (20% с 2026-06), приход 17 755 за 07-08.
3) Бумага и рушник (3 SKU) -> excluded_sku_barcodes тех же правил, где уже лежит Обухов.
Перед записью проверяет, что баркод не попадёт в два активных правила сразу.
Запуск: python _archive\\fix_rules_batch_0914.py [--apply]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb

BAT_RULE = "e8b86718"
ZZ_RULE = "617f21d5"
BAT = ["2212256006349", "2201398010789", "2207564005481", "4820149828688",
       "4820149829296", "2212339006921", "2204470003327", "2207400003428"]
ZZ = ["4820017291873"]
PAPER = ["4820003830017", "4820003831915", "4820003831885"]
APPLY = "--apply" in sys.argv

rules = sb.get("retro_rules", "status=eq.active&select=id,supplier_brand_id,retro_min,sku_barcodes,excluded_sku_barcodes")
by_id = {r["id"][:8]: r for r in rules}
sku_owner = {}
for r in rules:
    for b in (r.get("sku_barcodes") or []):
        sku_owner.setdefault(str(b), []).append(r["id"][:8])


def add(rule8, codes, field):
    r = by_id[rule8]
    cur = [str(x) for x in (r.get(field) or [])]
    add_now = [c for c in codes if c not in cur]
    clash = [c for c in add_now if field == "sku_barcodes" and sku_owner.get(c)]
    print(f"{rule8} {field}: было {len(cur)}, добавляем {len(add_now)}"
          + (f", КОНФЛИКТ (уже в правилах {clash}) - пропуск" if clash else ""))
    if clash:
        return
    if not add_now or not APPLY:
        return
    sb._req(f"{sb.URL}/rest/v1/retro_rules?id=eq.{r['id']}", {field: sorted(cur + add_now)},
            "PATCH", {"Prefer": "return=minimal"})
    chk = [str(x) for x in sb.get("retro_rules", f"id=eq.{r['id']}&select={field}")[0][field]]
    print(f"    записано: стало {len(chk)}, все на месте: {all(c in chk for c in codes)}")


add(BAT_RULE, BAT, "sku_barcodes")
add(ZZ_RULE, ZZ, "sku_barcodes")
# Обухов уже в исключениях у «Сервіс Про» (Фрекен Бок) - это другой поставщик, нам нужен Союз:
# статус «исключён правилом» смотрит правила ТОГО ЖЕ поставщика, поэтому вносим в правило Полюс.
add("6520a5f8", PAPER, "excluded_sku_barcodes")
if not APPLY:
    print("\nпробный прогон, для записи: --apply")

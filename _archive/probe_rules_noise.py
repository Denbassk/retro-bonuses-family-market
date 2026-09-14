"""Разовый, только чтение. Три вопроса:
1) Інтрейд Мікс (Батоша/Деліция): что в правилах - есть ли sku_barcodes, ограничения по числу SKU;
2) Союз (Жако, Золоте Зерно): правило и почему 4820017291873 не посчитан; куда вносить 3 баркода в исключения;
3) «До Бочкового» и «Авангард Грінки»: чей это поставщик и есть ли по нему правила.
-> output/probe_rules_noise.txt"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
brands = {b["id"]: b for b in sb.get("supplier_brands", "select=id,name,supplier_id")}
rules = sb.get("retro_rules", "select=*")
out = []
KEYS = ("id", "status", "valid_from", "valid_to", "retro_min", "retro_max", "retro_base_type", "income_source",
        "min_purchase_threshold", "returns_policy", "subtract_vat_from_retro", "notes")
def show(name_part):
    out.append(f"\n===== правила: поставщики с «{name_part}» =====")
    for r in rules:
        b = brands.get(r.get("supplier_brand_id")) or {}
        sname = sup.get(b.get("supplier_id"), "?")
        if name_part.lower() not in sname.lower():
            continue
        out.append(f"  [{r['status']}] {sname[:34]} / бренд {b.get('name', '?')[:28]} | "
                   + " | ".join(f"{k}={r.get(k)}" for k in ("valid_from", "valid_to", "retro_min", "retro_base_type"))
                   + f" | sku={len(r.get('sku_barcodes') or [])} excl={len(r.get('excluded_sku_barcodes') or [])}"
                   + f" | rule_id={r['id'][:8]}")
        extra = {k: v for k, v in r.items() if k not in KEYS and k not in
                 ("supplier_brand_id", "sku_barcodes", "excluded_sku_barcodes", "created_at", "updated_at",
                  "supplier_id", "source", "source_num", "retro_raw") and v not in (None, "", False, 0)}
        if extra:
            out.append(f"      прочие поля: {extra}")
        if r.get("notes"):
            out.append(f"      notes: {r['notes'][:150]}")
for n in ("Інтрейд Мікс", "Союз (Жако", "Авангард"):
    show(n)
BC = {"4820017291873": "Золоте Зерно Фігурні Вироби", "4820003831915": "Папір Диво 4 шт",
      "4820003830017": "Папір Обухов 65 м", "4820003831885": "Рушник Білий Диво"}
out.append("\n===== где эти баркоды в правилах =====")
for bc, nm in BC.items():
    hits = [f"{sup.get((brands.get(r.get('supplier_brand_id')) or {}).get('supplier_id'), '?')[:28]}/"
            f"{(brands.get(r.get('supplier_brand_id')) or {}).get('name', '?')[:20]} "
            f"{r['retro_min']}% {'sku' if bc in {str(x) for x in (r.get('sku_barcodes') or [])} else 'excl'}"
            for r in rules if bc in {str(x) for x in (r.get('sku_barcodes') or [])} | {str(x) for x in (r.get('excluded_sku_barcodes') or [])}]
    out.append(f"  {bc} {nm[:34]:<36} {hits or 'нигде'}")
(ROOT / "output" / "probe_rules_noise.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

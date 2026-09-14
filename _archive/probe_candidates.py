"""Разовый, только чтение: кандидаты на добавление в правила из готового sku_coverage_2026.csv.
1) Інтрейд Мікс (Батоша) - позиции «вне правил»; 2) Союз/Золоте Зерно; 3) где сейчас лежат 3 бумажных баркода.
-> output/probe_candidates.txt"""
import csv, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import sb
rows = list(csv.DictReader((ROOT / "output" / "sku_coverage_2026.csv").open(encoding="utf-8-sig"), delimiter=";"))
out = []
def block(title, pred):
    agg = defaultdict(lambda: [0.0, 0.0, "", set()])
    for r in rows:
        if pred(r):
            a = agg[r["баркод"]]
            a[0] += float(r["приход"] or 0)
            a[1] += float(r["недосчитано"] or 0)
            a[2] = a[2] or r["наименование"]
            a[3].add(r["месяц"])
    out.append(f"\n=== {title}: SKU {len(agg)}, приход {sum(a[0] for a in agg.values()):,.0f}, "
               f"оценка {sum(a[1] for a in agg.values()):,.0f}")
    for bc, a in sorted(agg.items(), key=lambda x: -x[1][0]):
        out.append(f"    {bc}  {a[2][:52]:<54}{a[0]:>11,.0f}{a[1]:>10,.0f}  {min(a[3])}..{max(a[3])}")
    return sorted(agg)

bat = block("Інтрейд Мікс (Батоша), статус «вне правил»",
            lambda r: r["поставщик"].startswith("Інтрейд Мікс (Батоша") and r["статус покрытия"].startswith("вне правил"))
zz = block("Союз (Жако...), «вне правил», в названии «Золоте Зерно»",
           lambda r: r["поставщик"].startswith("Союз (Жако") and r["статус покрытия"].startswith("вне правил")
           and "золоте зерно" in (r["наименование"] or "").lower())
pap = block("Союз (Жако...), «вне правил», бумага/рушник",
            lambda r: r["поставщик"].startswith("Союз (Жако") and r["статус покрытия"].startswith("вне правил")
            and any(w in (r["наименование"] or "").lower() for w in ("папір", "рушник")))

brands = {b["id"]: b for b in sb.get("supplier_brands", "select=id,name,supplier_id")}
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
out.append("\n=== активные правила Союз (Жако...) и Інтрейд Мікс: куда вносить")
for r in sb.get("retro_rules", "status=eq.active&select=id,supplier_brand_id,retro_min,sku_barcodes,excluded_sku_barcodes"):
    b = brands.get(r["supplier_brand_id"]) or {}
    s = sup.get(b.get("supplier_id"), "")
    if s.startswith("Союз (Жако") or s.startswith("Інтрейд Мікс"):
        out.append(f"    {r['id'][:8]} {s[:30]:<32}/{b.get('name', '?')[:22]:<24}{r['retro_min']:>6}%  "
                   f"sku={len(r.get('sku_barcodes') or [])} excl={len(r.get('excluded_sku_barcodes') or [])}")
(ROOT / "output" / "probe_candidates.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

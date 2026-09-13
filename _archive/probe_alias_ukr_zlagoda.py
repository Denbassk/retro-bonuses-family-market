"""Разовый, только чтение: что даёт алиас «Українська Злагода» у ЗЛАГОДА-ОПТ.
Помесячно: приход всего, из него покрыто правилами Злагоды (вошло в ретро) и не покрыто; топ SKU.
Нужно, чтобы оценить последствия снятия алиаса. -> output/probe_alias_ukr_zlagoda.txt"""
import os, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
from google.cloud import bigquery
PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics"); DS = os.environ.get("BQ_DATASET", "family_market")
ALIAS = "Українська Злагода"
sup = {s["name"]: s["id"] for s in sb.get("suppliers", "select=id,name")}
sid = sup["ЗЛАГОДА-ОПТ"]
brands = {b["id"]: b["name"] for b in sb.get("supplier_brands", f"supplier_id=eq.{sid}&select=id,name")}
rules = sb.get("retro_rules", f"supplier_brand_id=in.({','.join(brands)})&status=eq.active&select=*")
in_rules = {str(b) for r in rules for b in (r.get("sku_barcodes") or [])}
cli = bigquery.Client(project=PROJ)
cfg = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("a", "STRING", ALIAS)])
rows = [dict(r) for r in cli.query(f"""SELECT FORMAT_DATE('%Y-%m', doc_date) per, CAST(barcode AS STRING) bc,
      ANY_VALUE(product_name) nm, ROUND(SUM(amount_purchase),2) amt FROM `{PROJ}.{DS}.incoming_transactions`
    WHERE TRIM(supplier) = @a AND doc_date >= '2026-01-01' GROUP BY 1,2""", job_config=cfg)]
m = defaultdict(lambda: [0.0, 0.0])
for r in rows:
    m[r["per"]][0 if r["bc"] in in_rules else 1] += r["amt"]
out = [f"алиас «{ALIAS}» -> ЗЛАГОДА-ОПТ; SKU в активных правилах поставщика: {len(in_rules)}", "",
       f"{'месяц':<9}{'приход всего':>14}{'в правилах (в ретро)':>22}{'вне правил':>14}"]
for per in sorted(m):
    a, b = m[per]
    out.append(f"{per:<9}{a + b:>14,.0f}{a:>22,.0f}{b:>14,.0f}")
ta = sum(v[0] for v in m.values()); tb = sum(v[1] for v in m.values())
out.append(f"{'ИТОГО':<9}{ta + tb:>14,.0f}{ta:>22,.0f}{tb:>14,.0f}")
out.append(f"\nретро, начисленное через этот алиас (10%, НДС не вычитается): {ta * 0.1:,.0f} ₴ ориентировочно")
out.append("\nтоп-12 SKU алиаса:")
for r in sorted(rows, key=lambda x: -x["amt"])[:12]:
    key = "в правиле" if r["bc"] in in_rules else "вне правил"
    out.append(f"    {r['bc']}  {(r['nm'] or '')[:46]:<48}{r['amt']:>11,.0f}  {key}")
udk = sum(r["amt"] for r in rows if (r["nm"] or "").upper().startswith("УДК"))
out.append(f"\nиз них позиции с названием «УДК ...»: {udk:,.0f} ₴")
(ROOT / "output" / "probe_alias_ukr_zlagoda.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

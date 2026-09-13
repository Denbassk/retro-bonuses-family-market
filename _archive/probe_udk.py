"""Разовый, только чтение: откуда взялся «УДК Бренді Шустов-160» в приходах ЗЛАГОДА.
Под каким supplier он лежит в BigQuery, есть ли алиасы/поставщики УДК, ПРОМТЕХНОРЕНТ, Шустов.
-> output/probe_udk.txt"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
from google.cloud import bigquery
PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics"); DS = os.environ.get("BQ_DATASET", "family_market")
out = []
cli = bigquery.Client(project=PROJ)
for r in cli.query(f"""SELECT TRIM(supplier) supplier, CAST(barcode AS STRING) bc, ANY_VALUE(product_name) nm,
      COUNT(DISTINCT doc_number) docs, MIN(doc_date) d1, MAX(doc_date) d2, ROUND(SUM(amount_purchase),2) amt
    FROM `{PROJ}.{DS}.incoming_transactions`
    WHERE doc_date >= '2026-01-01' AND (CAST(barcode AS STRING) = '4820256582985'
       OR REGEXP_CONTAINS(LOWER(IFNULL(product_name,'')), r'шустов')
       OR REGEXP_CONTAINS(LOWER(IFNULL(supplier,'')), r'удк|промтех'))
    GROUP BY 1,2 ORDER BY amt DESC"""):
    out.append(f"BQ supplier «{r['supplier']}» {r['bc']} {(r['nm'] or '')[:44]:<46} док {r['docs']:>3} "
               f"{r['d1']}..{r['d2']} {r['amt']:>10,.0f}")
out.append("")
al = sb.get("supplier_aliases", "select=alias_name,alias_type,supplier_id,supplier_brand_id")
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
hit = [a for a in al if any(w in (a["alias_name"] or "").lower() for w in ("удк", "промтех", "шустов"))]
out.append(f"алиасы с «УДК/Промтех/Шустов»: {len(hit)}")
for a in hit:
    out.append(f"    «{a['alias_name']}» -> {sup.get(a['supplier_id'], '?')} [{a['alias_type']}]")
out.append("поставщики с такими именами: " + str([n for n in sup.values() if any(
    w in n.lower() for w in ("удк", "промтех", "шустов"))]))
zl = [s for s, n in sup.items() if n == "ЗЛАГОДА-ОПТ"][0]
out.append("\nвсе алиасы ЗЛАГОДА-ОПТ:")
for a in al:
    if a["supplier_id"] == zl:
        out.append(f"    «{a['alias_name']}» [{a['alias_type']}]")
(ROOT / "output" / "probe_udk.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

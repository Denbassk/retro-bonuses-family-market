"""Перед правкой ключа: тип incoming_datetime, NULL-ы, и какая из двух doc_date совпадает с эталоном."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb  # noqa: F401
from google.cloud import bigquery

cli = bigquery.Client(project="family-market-analytics")
DS = "family-market-analytics.family_market"
T = f"`{DS}.incoming_transactions`"
REF = f"`{DS}.torgsoft_incoming_ref_2026`"

print("=== Схема ===")
for f in cli.get_table(f"{DS}.incoming_transactions").schema:
    if f.name in ("line_id", "doc_date", "doc_number", "incoming_datetime", "quantity",
                  "price_purchase", "amount_purchase", "supplier", "store", "barcode", "loaded_at"):
        print(f"  {f.name:<20} {f.field_type:<10} {f.mode}")

print("\n=== NULL-ы в ключевых полях (2026) ===")
r = list(cli.query(f"""
    SELECT COUNT(*) n, COUNTIF(incoming_datetime IS NULL) no_dt, COUNTIF(doc_date IS NULL) no_dd,
           COUNTIF(price_purchase IS NULL) no_price, COUNTIF(barcode IS NULL) no_bc,
           COUNTIF(supplier IS NULL) no_sup, COUNTIF(store IS NULL) no_store
    FROM {T} WHERE doc_date >= '2026-01-01' OR doc_date IS NULL"""))[0]
print(f"  всего {r.n:,} | без incoming_datetime {r.no_dt} | без doc_date {r.no_dd} | "
      f"без цены {r.no_price} | без ШК {r.no_bc} | без поставщика {r.no_sup} | без ТТ {r.no_store}")

print("\n=== Какая из двух дат совпадает с эталоном (по номеру документа) ===")
print("    группа = один incoming_datetime+ТТ+поставщик+ШК+кол-во+цена с двумя doc_date")
for r in cli.query(f"""
    WITH g AS (
      SELECT incoming_datetime, store, supplier, barcode,
             MIN(doc_date) d_min, MAX(doc_date) d_max,
             ANY_VALUE(doc_number) num, ANY_VALUE(store) st
      FROM {T}
      WHERE doc_date >= '2026-04-01' AND incoming_datetime IS NOT NULL
      GROUP BY incoming_datetime, store, supplier, barcode,
               FORMAT('%.3f', quantity), FORMAT('%.4f', price_purchase)
      HAVING COUNT(DISTINCT doc_date) = 2),
    e AS (SELECT DISTINCT doc_number, doc_date, store FROM {REF})
    SELECT FORMAT_DATE('%Y-%m', g.d_min) per, COUNT(*) n,
           COUNTIF(EXISTS (SELECT 1 FROM e WHERE e.doc_number = g.num AND e.doc_date = g.d_min)) hit_min,
           COUNTIF(EXISTS (SELECT 1 FROM e WHERE e.doc_number = g.num AND e.doc_date = g.d_max)) hit_max
    FROM g GROUP BY per ORDER BY per"""):
    print(f"  {r.per}  групп {r.n:>4}  эталон подтверждает раннюю {r.hit_min:>4} | позднюю {r.hit_max:>4}")

print("\n=== Совпадает ли формат дат: как doc_date лежит в эталоне ===")
for r in cli.query(f"SELECT doc_number, doc_date, store FROM {REF} WHERE doc_number = '6176' LIMIT 5"):
    print(f"  №{r.doc_number} {r.doc_date} {r.store}")

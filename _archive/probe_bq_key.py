"""Безопасен ли ключ без qty/price/doc_date: бывают ли законные повторы одного ШК в одной записи."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb  # noqa: F401
from google.cloud import bigquery

cli = bigquery.Client(project="family-market-analytics")
T = "`family-market-analytics.family_market.incoming_transactions`"

print("=== Повторы (supplier, store, incoming_datetime, barcode) с РАЗНОЙ ценой ===")
print("    если таких много - ключ без цены схлопнет законные строки")
for r in cli.query(f"""
    SELECT per, COUNTIF(np > 1) diff_price, COUNTIF(np = 1) same_price
    FROM (
      SELECT FORMAT_DATE('%Y-%m', MIN(doc_date)) per,
             COUNT(DISTINCT FORMAT('%.4f', price_purchase)) np
      FROM {T} WHERE doc_date >= '2026-01-01'
      GROUP BY supplier, store, incoming_datetime, barcode
      HAVING COUNT(*) > 1)
    GROUP BY per ORDER BY per"""):
    print(f"  {r.per}  групп-повторов: с разной ценой {r.diff_price:>5} | с той же ценой {r.same_price:>5}")

print("\n=== Что даст ключ (supplier, store, incoming_datetime, barcode, price): лишних строк ===")
for r in cli.query(f"""
    SELECT per, SUM(n - 1) lines, SUM(amt - amt / n) amt
    FROM (
      SELECT FORMAT_DATE('%Y-%m', MIN(doc_date)) per, COUNT(*) n, SUM(amount_purchase) amt
      FROM {T} WHERE doc_date >= '2026-01-01'
      GROUP BY supplier, store, incoming_datetime, barcode, FORMAT('%.4f', price_purchase)
      HAVING COUNT(*) > 1)
    GROUP BY per ORDER BY per"""):
    print(f"  {r.per}  схлопнулось бы строк {r.lines:>6}  на {r.amt:>14,.0f}")

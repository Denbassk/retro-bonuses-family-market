#!/usr/bin/env python3
"""Посмотреть товары поставщика в BQ. Запуск: python check_supplier_products.py "Промтехнорент" """
import os, sys
from pathlib import Path

# .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

from google.cloud import bigquery

BQ_PROJECT = os.environ.get("BQ_PROJECT", "family-market-analytics")
BQ_DATASET = os.environ.get("BQ_DATASET", "family_market")
client = bigquery.Client(project=BQ_PROJECT)

supplier = sys.argv[1] if len(sys.argv) > 1 else "Промтехнорент"

sql = f"""
SELECT product_name, barcode, COUNT(*) as tx, ROUND(SUM(amount_purchase),2) as total
FROM `{BQ_PROJECT}.{BQ_DATASET}.incoming_transactions`
WHERE supplier = '{supplier}'
  AND doc_date >= '2026-01-01'
GROUP BY product_name, barcode
ORDER BY total DESC
LIMIT 50
"""

print(f"Товары поставщика: {supplier}\n")
print(f"{'Товар':<65} {'Штрих-код':<15} {'tx':>4}  {'Сумма':>12}")
print("-" * 100)
for r in client.query(sql).result():
    d = dict(r.items())
    print(f"{d['product_name'][:64]:<65} {d['barcode']:<15} {d['tx']:>4}  {d['total']:>12,.2f}")

#!/usr/bin/env python3
"""
Извлечь штрихкоды из BQ для поставщика "Союз (Зерно)"
и показать группировку по торговым маркам.
Запуск: python extract_zerno_skus.py
"""
import os, json
from pathlib import Path
from collections import defaultdict

# ─── .env ─────────────────────────────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS",
    r"D:\Family_Market_Analytics\credentials\family-market-analytics-23fbcbcee571c.json")

from google.cloud import bigquery

BQ_PROJECT = os.environ.get("BQ_PROJECT", "family-market-analytics")
BQ_DATASET = os.environ.get("BQ_DATASET", "family_market")

client = bigquery.Client(project=BQ_PROJECT)

# ─── Запрос ───────────────────────────────────────────────────────────────────
sql = f"""
SELECT
    barcode,
    product_name,
    SUM(quantity) AS total_qty,
    ROUND(SUM(amount_purchase), 2) AS total_amount
FROM `{BQ_PROJECT}.{BQ_DATASET}.incoming_transactions`
WHERE supplier = 'Союз (Зерно)'
  AND barcode IS NOT NULL
  AND barcode != ''
GROUP BY barcode, product_name
ORDER BY product_name
"""

print("Запрос BQ...")
rows = list(client.query(sql).result())
print(f"Найдено {len(rows)} уникальных штрихкодов\n")

# ─── Показать всё ─────────────────────────────────────────────────────────────
brands = {
    "Жако":           [],
    "Золотое Зерно":  [],
    "Золоте зерно":   [],
    "Полюс":          [],
    "Сезам":          [],
    "Світтейл":       [],
    "Чарівна мозаїка": [],
    "НЕОПОЗНАНО":     [],
}

for row in rows:
    name = row.product_name or ""
    barcode = row.barcode
    matched = False
    for brand_key in brands:
        if brand_key == "НЕОПОЗНАНО":
            continue
        if brand_key.lower() in name.lower():
            brands[brand_key].append((barcode, name, row.total_qty, row.total_amount))
            matched = True
            break
    if not matched:
        brands["НЕОПОЗНАНО"].append((barcode, name, row.total_qty, row.total_amount))

print("=" * 80)
print("ГРУППИРОВКА ПО ТОРГОВЫМ МАРКАМ")
print("=" * 80)

# Merge "Золоте зерно" into "Золотое Зерно"
brands["Золотое Зерно"].extend(brands.pop("Золоте зерно", []))

for brand, items in brands.items():
    if not items:
        continue
    barcodes_only = [it[0] for it in items]
    print(f"\n--- {brand} ({len(items)} SKU) ---")
    print(f"    Штрихкоды (для Supabase): {json.dumps(barcodes_only)}")
    for bc, name, qty, amt in items:
        print(f"    {bc}  {name}  (qty={qty}, amt={amt})")

# ─── Сохранить JSON ──────────────────────────────────────────────────────────
output = {}
for brand, items in brands.items():
    if items:
        output[brand] = [it[0] for it in items]

out_path = Path(__file__).parent / "zerno_skus.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\nСохранено в {out_path}")

#!/usr/bin/env python3
"""
audit_bq_suppliers.py — Аудит поставщиков BQ vs Supabase aliases.
Выгружает уникальные supplier из incoming_transactions за 2026,
сопоставляет с алиасами и брендами в Supabase, находит дыры.

Запуск:
  python audit_bq_suppliers.py
"""

import os
import json
import urllib.request
from pathlib import Path
from collections import defaultdict

# ─── .env ────────────────────────────────────────────────────────────────────
def load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

load_env()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
BQ_PROJECT   = os.environ.get("BQ_PROJECT", "family-market-analytics")
BQ_DATASET   = os.environ.get("BQ_DATASET", "family_market")

def sb_get(table, params=""):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def run_bq(sql):
    from google.cloud import bigquery
    client = bigquery.Client(project=BQ_PROJECT)
    return [dict(r.items()) for r in client.query(sql).result()]

# ═══════════════════════════════════════════════════════════════════════════
print("=" * 80)
print("  АУДИТ ПОСТАВЩИКОВ: BigQuery vs Supabase")
print("=" * 80)

# 1. Все уникальные supplier из BQ за 2026
print("\n[1] Загрузка уникальных supplier из BQ incoming_transactions 2026...")
bq_suppliers = run_bq(f"""
    SELECT supplier,
           COUNT(*) AS tx_count,
           ROUND(SUM(amount_purchase), 2) AS total_purchase
    FROM `{BQ_PROJECT}.{BQ_DATASET}.incoming_transactions`
    WHERE doc_date >= '2026-01-01' AND doc_date < '2027-01-01'
      AND supplier IS NOT NULL AND TRIM(supplier) != ''
    GROUP BY supplier
    ORDER BY total_purchase DESC
""")
print(f"  Уникальных supplier в BQ: {len(bq_suppliers)}")

# 2. Загрузка справочников Supabase
print("\n[2] Загрузка справочников Supabase...")
aliases = sb_get("supplier_aliases", "select=alias_name,supplier_id,supplier_brand_id")
brands = sb_get("supplier_brands", "select=id,name,supplier_id")
suppliers = sb_get("suppliers", "select=id,name,is_retro_active")
rules = sb_get("retro_rules", "status=eq.active&select=id,supplier_brand_id,retro_min,retro_max")

brand_map = {b["id"]: b for b in brands}
supplier_map = {s["id"]: s for s in suppliers}

# alias_name → {supplier_id, supplier_brand_id, supplier_name, brand_name}
alias_info = {}
for a in aliases:
    sup = supplier_map.get(a["supplier_id"], {})
    brand = brand_map.get(a.get("supplier_brand_id"), {})
    alias_info[a["alias_name"]] = {
        "supplier_id": a["supplier_id"],
        "supplier_brand_id": a.get("supplier_brand_id"),
        "supplier_name": sup.get("name", "???"),
        "brand_name": brand.get("name"),
        "is_retro_active": sup.get("is_retro_active", False),
    }

# Бренды с retro правилами
brands_with_rules = set()
for r in rules:
    brands_with_rules.add(r["supplier_brand_id"])

print(f"  Алиасов: {len(aliases)}, Брендов: {len(brands)}, Поставщиков: {len(suppliers)}")

# ═══════════════════════════════════════════════════════════════════════════
# 3. Сопоставление
print("\n" + "=" * 80)
print("  РЕЗУЛЬТАТ СОПОСТАВЛЕНИЯ")
print("=" * 80)

matched_with_brand = []    # alias есть + brand привязка есть
matched_no_brand = []      # alias есть, но без brand привязки
not_in_aliases = []        # нет в алиасах вообще

for row in bq_suppliers:
    name = row["supplier"]
    info = alias_info.get(name)
    if info:
        if info["supplier_brand_id"]:
            matched_with_brand.append({**row, **info})
        else:
            matched_no_brand.append({**row, **info})
    else:
        not_in_aliases.append(row)

# 3a. Алиасы БЕЗ brand привязки (ретро-активные поставщики)
print(f"\n--- АЛИАСЫ БЕЗ BRAND ПРИВЯЗКИ ({len(matched_no_brand)}) ---")
print(f"{'BQ supplier':<55} {'Поставщик':<25} {'Приход':>14} {'tx':>6}")
print("-" * 105)
for row in sorted(matched_no_brand, key=lambda x: -x["total_purchase"]):
    retro = "★" if row["is_retro_active"] else " "
    print(f"{retro} {row['supplier']:<53} {row['supplier_name']:<25} {row['total_purchase']:>14,.2f} {row['tx_count']:>6}")

# 3b. НЕ В АЛИАСАХ
print(f"\n--- НЕ В АЛИАСАХ ({len(not_in_aliases)}) ---")
print(f"{'BQ supplier':<55} {'Приход':>14} {'tx':>6}")
print("-" * 80)
for row in sorted(not_in_aliases, key=lambda x: -x["total_purchase"]):
    print(f"  {row['supplier']:<53} {row['total_purchase']:>14,.2f} {row['tx_count']:>6}")

# 3c. Алиасы С brand привязкой (ОК)
print(f"\n--- АЛИАСЫ С BRAND ПРИВЯЗКОЙ — ОК ({len(matched_with_brand)}) ---")
print(f"{'BQ supplier':<55} {'Бренд':<25} {'Приход':>14}")
print("-" * 100)
for row in sorted(matched_with_brand, key=lambda x: x["supplier_name"]):
    print(f"  {row['supplier']:<53} {row['brand_name'] or '?':<25} {row['total_purchase']:>14,.2f}")

# ═══════════════════════════════════════════════════════════════════════════
# 4. Сводка
print(f"\n{'=' * 80}")
print(f"  СВОДКА")
print(f"{'=' * 80}")
total_purchase = sum(r["total_purchase"] for r in bq_suppliers)
matched_brand_sum = sum(r["total_purchase"] for r in matched_with_brand)
matched_no_brand_sum = sum(r["total_purchase"] for r in matched_no_brand)
not_in_sum = sum(r["total_purchase"] for r in not_in_aliases)

print(f"  Всего supplier в BQ:       {len(bq_suppliers):>5}   {total_purchase:>16,.2f} грн")
print(f"  С brand alias (точно):     {len(matched_with_brand):>5}   {matched_brand_sum:>16,.2f} грн  ({matched_brand_sum/total_purchase*100:.1f}%)")
print(f"  Без brand alias:           {len(matched_no_brand):>5}   {matched_no_brand_sum:>16,.2f} грн  ({matched_no_brand_sum/total_purchase*100:.1f}%)")
print(f"  Не в алиасах:              {len(not_in_aliases):>5}   {not_in_sum:>16,.2f} грн  ({not_in_sum/total_purchase*100:.1f}%)")

# 5. Сохранить CSV для удобства
csv_path = Path(__file__).resolve().parent.parent / "output" / "bq_supplier_audit.csv"
import csv
with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["bq_supplier", "status", "supabase_supplier", "brand", "tx_count", "total_purchase"])
    for row in matched_with_brand:
        w.writerow([row["supplier"], "brand_alias_ok", row["supplier_name"],
                    row["brand_name"], row["tx_count"], f"{row['total_purchase']:.2f}"])
    for row in matched_no_brand:
        w.writerow([row["supplier"], "no_brand_alias", row["supplier_name"],
                    "", row["tx_count"], f"{row['total_purchase']:.2f}"])
    for row in not_in_aliases:
        w.writerow([row["supplier"], "not_in_aliases", "",
                    "", row["tx_count"], f"{row['total_purchase']:.2f}"])

print(f"\n[>] CSV сохранён: {csv_path}")

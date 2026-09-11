#!/usr/bin/env python3
"""bq_catalog.py - каталог таблиц датасета BigQuery: имена, строки, колонки."""
import os, csv
from pathlib import Path

def load_env(p=None):
    p = p or Path(__file__).parent / ".env"
    if not p.exists(): return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

load_env()
from google.cloud import bigquery

PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics")
DS   = os.environ.get("BQ_DATASET", "family_market")
cli  = bigquery.Client(project=PROJ)

rows = list(cli.query(f"""
  SELECT t.table_name, t.table_type,
         IFNULL(p.row_count, 0) AS rows_cnt,
         STRING_AGG(c.column_name || ':' || c.data_type, ', '
                    ORDER BY c.ordinal_position) AS cols
  FROM `{PROJ}.{DS}.INFORMATION_SCHEMA.TABLES` t
  JOIN `{PROJ}.{DS}.INFORMATION_SCHEMA.COLUMNS` c USING (table_name)
  LEFT JOIN (SELECT table_id, SUM(row_count) row_count
             FROM `{PROJ}.{DS}.__TABLES__` GROUP BY table_id) p
         ON p.table_id = t.table_name
  GROUP BY 1,2,3 ORDER BY 1
"""))

with open("bq_catalog.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["table", "type", "rows", "columns"])
    for r in rows:
        w.writerow([r["table_name"], r["table_type"], r["rows_cnt"], r["cols"]])

print(f"Таблиц: {len(rows)}\n")
for r in rows:
    print(f"{r['table_name']}  [{r['table_type']}]  строк={r['rows_cnt']:,}")
    print(f"    {r['cols']}\n")
print("CSV: bq_catalog.csv")

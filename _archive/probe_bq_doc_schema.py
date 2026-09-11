"""Разовый probe: колонки таблиц приходов/возвратов и эталонов + пример документа -> output/probe_bq_doc_schema.txt"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb  # noqa: F401  (загружает .env)
from google.cloud import bigquery
PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics"); DS = os.environ.get("BQ_DATASET", "family_market")
cli = bigquery.Client(project=PROJ)
T = ("incoming_transactions", "outgoing_to_supplier_transactions", "torgsoft_incoming_ref_2026", "torgsoft_outgoing_ref")
out = []
for r in cli.query(f"SELECT table_name, column_name, data_type FROM `{PROJ}.{DS}.INFORMATION_SCHEMA.COLUMNS` "
                   f"WHERE table_name IN UNNEST({list(T)}) ORDER BY table_name, ordinal_position"):
    out.append(f"{r['table_name']}.{r['column_name']} {r['data_type']}")
for t in T:
    out.append(f"\n-- {t}: пример")
    for r in cli.query(f"SELECT * FROM `{PROJ}.{DS}.{t}` WHERE doc_date = '2026-06-10' LIMIT 2"):
        out.append("  " + " | ".join(f"{k}={v}" for k, v in dict(r).items()))
    q = f"SELECT COUNT(*) n, MIN(doc_date) a, MAX(doc_date) b FROM `{PROJ}.{DS}.{t}` WHERE doc_date >= '2026-01-01'"
    for r in cli.query(q):
        out.append(f"  2026: строк {r['n']}, {r['a']} .. {r['b']}")
(ROOT / "output" / "probe_bq_doc_schema.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

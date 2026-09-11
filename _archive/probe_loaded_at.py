"""Разовый probe: почему loaded_at > created_at расчёта почти у всего прихода. Распределение партий загрузки."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str((ROOT) / "core")); os.chdir(ROOT)
import sb  # noqa
from google.cloud import bigquery
P, D = os.environ.get("BQ_PROJECT", "family-market-analytics"), os.environ.get("BQ_DATASET", "family_market")
c = bigquery.Client(project=P)
for t in ("incoming_transactions", "outgoing_to_supplier_transactions"):
    print(f"\n{t}: партии загрузки (DATE(loaded_at)) x месяцы документа, 2026")
    rows = list(c.query(f"""SELECT DATE(TIMESTAMP(loaded_at)) ld, FORMAT_DATE('%Y-%m', doc_date) per,
        COUNT(*) n, ROUND(SUM(amount_purchase)) s FROM `{P}.{D}.{t}` WHERE doc_date >= '2026-01-01'
        GROUP BY 1,2 ORDER BY 1,2"""))
    cur = None
    for r in rows:
        if r["ld"] != cur:
            cur = r["ld"]; print(f"  загружено {cur}:")
        print(f"      док.месяц {r['per']}  строк {r['n']:>7,}  сумма {r['s']:>14,.0f}")

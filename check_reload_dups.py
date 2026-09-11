#!/usr/bin/env python3
"""check_reload_dups.py - проверка перезалива 29-30.07 на дубли."""
import os
from pathlib import Path


def load_env(p=None):
    p = p or Path(__file__).parent / ".env"
    if not p.exists():
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


load_env()
from google.cloud import bigquery

PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics")
DS = os.environ.get("BQ_DATASET", "family_market")
T = f"`{PROJ}.{DS}"
cli = bigquery.Client(project=PROJ)
run = lambda sql: list(cli.query(sql))

print("\n[1] Документы с двумя и более loaded_at (признак двойной заливки)")
rows = run(f"""
  SELECT doc_date, doc_number, supplier,
         COUNT(DISTINCT DATE(loaded_at)) batches,
         COUNT(*) lines, ROUND(SUM(amount_purchase),2) amt
  FROM {T}.incoming_transactions`
  WHERE EXTRACT(YEAR FROM doc_date)=2026
  GROUP BY 1,2,3
  HAVING COUNT(DISTINCT DATE(loaded_at)) > 1
  ORDER BY amt DESC
  LIMIT 30
""")
if not rows:
    print("    чисто")
for r in rows:
    print(f"    {r['doc_date']} {str(r['doc_number']):<12}{(r['supplier'] or '')[:34]:<36}"
          f"партий {r['batches']}  строк {r['lines']}  {float(r['amt']):>14,.2f}")

print("\n[2] Дубли строк по (incoming_id, line_number)")
rows = run(f"""
  SELECT COUNT(*) pairs, SUM(c-1) extra_lines, ROUND(SUM(amt*(c-1)/c),2) extra_amt
  FROM (SELECT incoming_id, line_number, COUNT(*) c, SUM(amount_purchase) amt
        FROM {T}.incoming_transactions`
        WHERE EXTRACT(YEAR FROM doc_date)=2026
        GROUP BY 1,2 HAVING COUNT(*)>1)
""")
r = rows[0]
print(f"    пар: {r['pairs']}  лишних строк: {r['extra_lines'] or 0}  "
      f"лишняя сумма: {float(r['extra_amt'] or 0):,.2f}")

print("\n[3] 29-30.07: наши vs эталон по поставщикам")
rows = run(f"""
  WITH e AS (SELECT supplier, SUM(amount) amt, COUNT(DISTINCT doc_number) docs
             FROM {T}.torgsoft_incoming_ref_2026`
             WHERE doc_date BETWEEN '2026-07-29' AND '2026-07-30' GROUP BY 1),
       o AS (SELECT supplier, SUM(amount_purchase) amt, COUNT(DISTINCT doc_number) docs
             FROM {T}.incoming_transactions`
             WHERE doc_date BETWEEN '2026-07-29' AND '2026-07-30' GROUP BY 1)
  SELECT COALESCE(e.supplier,o.supplier) supplier,
         IFNULL(e.amt,0) etalon, IFNULL(o.amt,0) ours,
         IFNULL(o.amt,0)-IFNULL(e.amt,0) over_amt,
         IFNULL(e.docs,0) e_docs, IFNULL(o.docs,0) o_docs
  FROM e FULL OUTER JOIN o ON e.supplier=o.supplier
  ORDER BY ABS(IFNULL(o.amt,0)-IFNULL(e.amt,0)) DESC
""")
te = sum(float(r["etalon"]) for r in rows)
to = sum(float(r["ours"]) for r in rows)
ed = sum(r["e_docs"] for r in rows)
od = sum(r["o_docs"] for r in rows)
print(f"    ИТОГО эталон {te:,.2f} ({ed} док) | наши {to:,.2f} ({od} док) | "
      f"перебор {to-te:+,.2f} ({od-ed:+d} док)")
for r in rows:
    if abs(float(r["over_amt"])) >= 1:
        print(f"    {(r['supplier'] or '<нет>')[:36]:<38}"
              f"{float(r['etalon']):>14,.2f}{float(r['ours']):>14,.2f}"
              f"{float(r['over_amt']):>+14,.2f}  {r['e_docs']}/{r['o_docs']}")

print("\n[4] Приход по месяцам: наши vs эталон (Jan-Aug)")
rows = run(f"""
  WITH e AS (SELECT FORMAT_DATE('%Y-%m',doc_date) per, SUM(amount) amt,
                    COUNT(DISTINCT doc_number) docs
             FROM {T}.torgsoft_incoming_ref_2026`
             WHERE EXTRACT(YEAR FROM doc_date)=2026 GROUP BY 1),
       o AS (SELECT FORMAT_DATE('%Y-%m',doc_date) per, SUM(amount_purchase) amt,
                    COUNT(DISTINCT doc_number) docs
             FROM {T}.incoming_transactions`
             WHERE EXTRACT(YEAR FROM doc_date)=2026 GROUP BY 1)
  SELECT COALESCE(e.per,o.per) per, IFNULL(e.amt,0) etalon, IFNULL(o.amt,0) ours,
         IFNULL(e.docs,0) e_docs, IFNULL(o.docs,0) o_docs
  FROM e FULL OUTER JOIN o ON e.per=o.per ORDER BY 1
""")
for r in rows:
    print(f"    {r['per']}  эталон {float(r['etalon']):>14,.0f} ({r['e_docs']:>5})  "
          f"наши {float(r['ours']):>14,.0f} ({r['o_docs']:>5})  "
          f"дельта {float(r['ours'])-float(r['etalon']):>+14,.0f}")

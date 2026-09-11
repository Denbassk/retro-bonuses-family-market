#!/usr/bin/env python3
"""probe_delta_structure.py - структура дельты: дубли, границы загрузки, переименования."""
import os, csv
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

print("\n[A] Мультипартийные документы: наша сумма vs эталон (тест на задвоение)")
rows = run(f"""
  WITH mb AS (
    SELECT doc_date, doc_number
    FROM {T}.incoming_transactions`
    WHERE EXTRACT(YEAR FROM doc_date)=2026
    GROUP BY 1,2 HAVING COUNT(DISTINCT DATE(loaded_at)) > 1),
  o AS (
    SELECT i.doc_date, i.doc_number, ANY_VALUE(i.supplier) sup,
           SUM(i.amount_purchase) amt, COUNT(DISTINCT i.line_id) lines
    FROM {T}.incoming_transactions` i JOIN mb USING (doc_date, doc_number)
    GROUP BY 1,2),
  e AS (
    SELECT r.doc_date, r.doc_number, SUM(r.amount) amt
    FROM {T}.torgsoft_incoming_ref_2026` r JOIN mb USING (doc_date, doc_number)
    GROUP BY 1,2)
  SELECT o.doc_date, o.doc_number, o.sup, o.amt ours, IFNULL(e.amt,0) etalon,
         o.amt - IFNULL(e.amt,0) delta, o.lines
  FROM o LEFT JOIN e USING (doc_date, doc_number)
  ORDER BY ABS(o.amt - IFNULL(e.amt,0)) DESC LIMIT 15
""")
tot = run(f"""
  WITH mb AS (
    SELECT doc_date, doc_number FROM {T}.incoming_transactions`
    WHERE EXTRACT(YEAR FROM doc_date)=2026
    GROUP BY 1,2 HAVING COUNT(DISTINCT DATE(loaded_at)) > 1)
  SELECT (SELECT COUNT(*) FROM mb) docs,
    (SELECT SUM(amount_purchase) FROM {T}.incoming_transactions` i
       JOIN mb USING (doc_date, doc_number)) ours,
    (SELECT SUM(amount) FROM {T}.torgsoft_incoming_ref_2026` r
       JOIN mb USING (doc_date, doc_number)) etalon
""")[0]
print(f"    таких документов {tot['docs']}: наши {float(tot['ours'] or 0):,.2f} | "
      f"эталон {float(tot['etalon'] or 0):,.2f} | "
      f"перебор {float(tot['ours'] or 0)-float(tot['etalon'] or 0):+,.2f}")
print("    (перебор ~0 => доливка частями, не дубль)")
for r in rows:
    print(f"    {r['doc_date']} {str(r['doc_number']):<10}{(r['sup'] or '')[:30]:<32}"
          f"{float(r['ours']):>13,.2f}{float(r['etalon']):>13,.2f}"
          f"{float(r['delta']):>+12,.2f}  стр {r['lines']}")

print("\n[B] Почему incoming_id+line_number не уникален")
r = run(f"""
  SELECT COUNT(*) pairs,
         COUNTIF(stores > 1) multi_store,
         COUNTIF(barcodes > 1) multi_barcode
  FROM (SELECT incoming_id, line_number,
               COUNT(DISTINCT store) stores, COUNT(DISTINCT barcode) barcodes
        FROM {T}.incoming_transactions`
        WHERE EXTRACT(YEAR FROM doc_date)=2026
        GROUP BY 1,2 HAVING COUNT(*) > 1)
""")[0]
print(f"    пар {r['pairs']}: с разными store {r['multi_store']}, "
      f"с разными barcode {r['multi_barcode']}")
r2 = run(f"""
  SELECT COUNT(*) rows_all, COUNT(DISTINCT line_id) line_ids
  FROM {T}.incoming_transactions` WHERE EXTRACT(YEAR FROM doc_date)=2026
""")[0]
print(f"    строк {r2['rows_all']:,} | уникальных line_id {r2['line_ids']:,} "
      f"=> дублей по PK: {r2['rows_all']-r2['line_ids']}")

print("\n[C] По дням, июль-август: наши vs эталон")
rows = run(f"""
  WITH e AS (SELECT doc_date, SUM(amount) amt, COUNT(DISTINCT doc_number) docs
             FROM {T}.torgsoft_incoming_ref_2026`
             WHERE doc_date BETWEEN '2026-07-01' AND '2026-08-31' GROUP BY 1),
       o AS (SELECT doc_date, SUM(amount_purchase) amt, COUNT(DISTINCT doc_number) docs
             FROM {T}.incoming_transactions`
             WHERE doc_date BETWEEN '2026-07-01' AND '2026-08-31' GROUP BY 1)
  SELECT COALESCE(e.doc_date,o.doc_date) d,
         IFNULL(e.amt,0) etalon, IFNULL(o.amt,0) ours,
         IFNULL(o.amt,0)-IFNULL(e.amt,0) delta,
         IFNULL(e.docs,0) e_docs, IFNULL(o.docs,0) o_docs
  FROM e FULL OUTER JOIN o ON e.doc_date=o.doc_date ORDER BY 1
""")
with open("delta_by_day.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["date", "etalon", "ours", "delta", "e_docs", "o_docs"])
    for r in rows:
        w.writerow([r["d"], f"{float(r['etalon']):.2f}", f"{float(r['ours']):.2f}",
                    f"{float(r['delta']):.2f}", r["e_docs"], r["o_docs"]])
for r in rows:
    dl, ed, od = float(r["delta"]), r["e_docs"], r["o_docs"]
    if abs(dl) >= 5000 or abs(ed - od) >= 5:
        print(f"    {r['d']}  эталон {float(r['etalon']):>13,.0f} ({ed:>4})  "
              f"наши {float(r['ours']):>13,.0f} ({od:>4})  {dl:>+13,.0f}")

print("\n[D] Кандидаты в переименования (док+дата+сумма совпали, поставщик разный)")
rows = run(f"""
  WITH e AS (SELECT doc_date, doc_number, supplier, SUM(amount) amt
             FROM {T}.torgsoft_incoming_ref_2026`
             WHERE EXTRACT(YEAR FROM doc_date)=2026 GROUP BY 1,2,3),
       o AS (SELECT doc_date, doc_number, supplier, SUM(amount_purchase) amt
             FROM {T}.incoming_transactions`
             WHERE EXTRACT(YEAR FROM doc_date)=2026 GROUP BY 1,2,3)
  SELECT e.supplier e_sup, o.supplier o_sup,
         COUNT(*) docs, SUM(e.amt) amt, MIN(e.doc_date) d1, MAX(e.doc_date) d2
  FROM e JOIN o ON e.doc_date=o.doc_date AND e.doc_number=o.doc_number
              AND ABS(e.amt-o.amt) < 0.01
  WHERE e.supplier != o.supplier
  GROUP BY 1,2 ORDER BY amt DESC LIMIT 25
""")
for r in rows:
    print(f"    эталон «{(r['e_sup'] or '')[:34]}» = наши «{(r['o_sup'] or '')[:34]}»  "
          f"{r['docs']} док {float(r['amt']):>12,.2f}  {r['d1']}..{r['d2']}")
print("\nCSV: delta_by_day.csv")

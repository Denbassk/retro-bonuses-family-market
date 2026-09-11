"""Разовый probe перед сверкой документов с эталоном:
 1) дубли внутри эталона (одна ТТ, дата, сумма, разные номера) - какие номера;
 2) совпадают ли номера документов и названия ТТ между нашими приходами и эталоном.
-> output/probe_etalon_dupes.txt"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb  # noqa: F401
from google.cloud import bigquery
PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics"); DS = os.environ.get("BQ_DATASET", "family_market")
cli = bigquery.Client(project=PROJ)
T = lambda t: f"`{PROJ}.{DS}.{t}`"
out = []
q = f"""SELECT supplier, store, doc_date, ROUND(amount, 2) amt, ARRAY_AGG(doc_number ORDER BY doc_number) nums, COUNT(*) n
FROM {T('torgsoft_incoming_ref_2026')} WHERE doc_date BETWEEN '2026-05-01' AND '2026-07-31'
GROUP BY 1,2,3,4 HAVING COUNT(*) > 1 ORDER BY n DESC LIMIT 25"""
rows = list(cli.query(q))
out.append(f"эталон приходов май-июль: групп (ТТ, дата, сумма) с >1 документом (показано до 25): {len(rows)}")
for r in rows:
    out.append(f"  {r['supplier'][:25]:<25} {r['store'][:20]:<20} {r['doc_date']} {r['amt']:>10} nums={list(r['nums'])}")
q = f"""SELECT COUNT(*) n, COUNTIF(k > 1) dup, SUM(IF(k > 1, amt * (k - 1), 0)) dup_amt FROM (
  SELECT supplier, store, doc_date, ROUND(amount, 2) amt, COUNT(*) k FROM {T('torgsoft_incoming_ref_2026')}
  WHERE doc_date >= '2026-01-01' GROUP BY 1,2,3,4)"""
for r in cli.query(q):
    out.append(f"\nэталон 2026: групп {r['n']}, из них с повтором {r['dup']}, лишняя сумма повторов {r['dup_amt']:,.0f}")

# номера и ТТ: наши документы против эталона за июнь по всем поставщикам
q = f"""WITH o AS (SELECT supplier, store, doc_date, doc_number, ROUND(SUM(amount_purchase), 2) amt
          FROM {T('incoming_transactions')} WHERE doc_date BETWEEN '2026-06-01' AND '2026-06-30' GROUP BY 1,2,3,4),
     e AS (SELECT supplier, store, doc_date, doc_number, ROUND(SUM(amount), 2) amt
          FROM {T('torgsoft_incoming_ref_2026')} WHERE doc_date BETWEEN '2026-06-01' AND '2026-06-30' GROUP BY 1,2,3,4)
SELECT
  (SELECT COUNT(*) FROM o) o_docs, (SELECT COUNT(*) FROM e) e_docs,
  (SELECT COUNT(*) FROM o JOIN e USING (supplier, store, doc_date, doc_number)) by_num,
  (SELECT COUNT(*) FROM o JOIN e USING (supplier, doc_number)) by_sup_num,
  (SELECT COUNT(*) FROM o JOIN e ON o.supplier = e.supplier AND o.store = e.store AND o.doc_date = e.doc_date AND ABS(o.amt - e.amt) < 1) by_amt,
  (SELECT COUNT(DISTINCT store) FROM o) o_st, (SELECT COUNT(DISTINCT store) FROM e) e_st,
  (SELECT COUNT(*) FROM (SELECT DISTINCT store FROM o) JOIN (SELECT DISTINCT store FROM e) USING (store)) st_common,
  (SELECT COUNT(*) FROM (SELECT DISTINCT supplier FROM o) JOIN (SELECT DISTINCT supplier FROM e) USING (supplier)) sup_common,
  (SELECT COUNT(DISTINCT supplier) FROM o) o_sup, (SELECT COUNT(DISTINCT supplier) FROM e) e_sup"""
for r in cli.query(q):
    out.append("\nиюнь, все поставщики: " + ", ".join(f"{k}={v}" for k, v in dict(r).items()))
q = f"""SELECT o.supplier, o.store, o.doc_date, o.doc_number onum, e.doc_number enumb, o.amt oamt, e.amt eamt FROM
 (SELECT supplier, store, doc_date, doc_number, ROUND(SUM(amount_purchase), 2) amt FROM {T('incoming_transactions')}
  WHERE doc_date = '2026-06-15' GROUP BY 1,2,3,4) o
 JOIN (SELECT supplier, store, doc_date, doc_number, ROUND(amount, 2) amt FROM {T('torgsoft_incoming_ref_2026')}
  WHERE doc_date = '2026-06-15') e ON o.supplier = e.supplier AND o.store = e.store AND ABS(o.amt - e.amt) < 1 LIMIT 15"""
out.append("\nпримеры пар по сумме (15.06): наш номер / номер эталона")
for r in cli.query(q):
    out.append(f"  {r['supplier'][:25]:<25} {r['store'][:18]:<18} {r['onum']:>10} / {r['enumb']:<12} {r['oamt']:>10} {r['eamt']:>10}")
(ROOT / "output" / "probe_etalon_dupes.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

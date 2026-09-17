"""Масштаб двух механизмов дублей в incoming_transactions."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb  # noqa: F401
from google.cloud import bigquery

cli = bigquery.Client(project="family-market-analytics")
T = "`family-market-analytics.family_market.incoming_transactions`"

print("=== A. Одна запись Торгсофта (тот же incoming_datetime), но РАЗНАЯ doc_date ===")
print("    (сдвиг даты между выгрузками -> другой line_id -> MERGE не схлопнул)")
for r in cli.query(f"""
    SELECT per, COUNT(*) grp, SUM(n - 1) lines, SUM(amt - amt / n) dup_amt
    FROM (
      SELECT FORMAT_DATE('%Y-%m', MIN(doc_date)) per, COUNT(*) n, SUM(amount_purchase) amt
      FROM {T}
      WHERE doc_date >= '2026-01-01' AND incoming_datetime IS NOT NULL
      GROUP BY incoming_datetime, store, supplier, barcode,
               FORMAT('%.3f', quantity), FORMAT('%.4f', price_purchase)
      HAVING COUNT(DISTINCT doc_date) > 1)
    GROUP BY per ORDER BY per"""):
    print(f"  {r.per}  групп {r.grp:>5}  лишних строк {r.lines:>6}  на {r.dup_amt:>14,.0f}")

print("\n=== B. Тот же документ и строка, но РАЗНОЕ количество или цена ===")
print("    (документ перевыставили; MERGE вставил новую версию, старая осталась)")
for r in cli.query(f"""
    SELECT per, COUNT(*) grp, SUM(n - 1) lines, SUM(amt - mx) dup_amt
    FROM (
      SELECT FORMAT_DATE('%Y-%m', doc_date) per, COUNT(*) n,
             SUM(amount_purchase) amt, MAX(amount_purchase) mx
      FROM {T}
      WHERE doc_date >= '2026-01-01' AND doc_number IS NOT NULL
      GROUP BY per, doc_date, doc_number, store, supplier, barcode
      HAVING COUNT(*) > 1)
    GROUP BY per ORDER BY per"""):
    print(f"  {r.per}  групп {r.grp:>5}  лишних строк {r.lines:>6}  на {r.dup_amt:>14,.0f}")

print("\n=== C. Пересечение файлов: сколько дней покрыто более чем одним файлом ===")
for r in cli.query(f"""
    SELECT FORMAT_DATE('%Y-%m', doc_date) per, COUNT(DISTINCT doc_date) days,
           COUNT(DISTINCT source_file) files, COUNTIF(nf > 1) over_days
    FROM (
      SELECT doc_date, source_file, COUNT(DISTINCT source_file)
               OVER (PARTITION BY doc_date) nf
      FROM {T} WHERE doc_date >= '2026-01-01' GROUP BY doc_date, source_file)
    GROUP BY per ORDER BY per"""):
    print(f"  {r.per}  дней {r.days:>3}  файлов {r.files:>3}  пар день-файл там, где файлов >1: {r.over_days:>4}")

print("\n=== D. Чем перекрываются файлы июля ===")
for r in cli.query(f"""
    SELECT source_file, MIN(doc_date) d1, MAX(doc_date) d2, COUNT(*) n, SUM(amount_purchase) amt
    FROM {T} WHERE doc_date BETWEEN '2026-07-01' AND '2026-07-31'
    GROUP BY source_file ORDER BY d1"""):
    print(f"  {str(r.source_file)[:44]:<44} {r.d1}..{r.d2}  строк {r.n:>7}  {r.amt:>14,.0f}")

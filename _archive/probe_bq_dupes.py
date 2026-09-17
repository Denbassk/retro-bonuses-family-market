"""Откуда берутся дубли приходов: разбор конкретных задвоенных документов по line_id/source_file."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb  # noqa: F401
from google.cloud import bigquery

cli = bigquery.Client(project="family-market-analytics")
T = "`family-market-analytics.family_market.incoming_transactions`"

print("=== 1. БІР №11949, 22.07 ===")
for r in cli.query(f"""
    SELECT doc_date, incoming_datetime, store, barcode, quantity, price_purchase,
           amount_purchase, source_file, line_id
    FROM {T}
    WHERE doc_number = '11949' AND doc_date BETWEEN '2026-07-20' AND '2026-07-24'
    ORDER BY barcode, source_file LIMIT 12"""):
    print(f"  {r.doc_date} dt={r.incoming_datetime} {str(r.store)[:18]:<18} {r.barcode} "
          f"q={r.quantity} p={r.price_purchase} s={r.amount_purchase:>9.2f} {r.source_file}")

print("\n=== 2. Арсенал ПК (Шейк) №6176 ===")
for r in cli.query(f"""
    SELECT doc_date, incoming_datetime, doc_number, store, barcode, quantity, price_purchase,
           amount_purchase, source_file
    FROM {T}
    WHERE doc_number = '6176' AND doc_date BETWEEN '2026-07-01' AND '2026-07-31'
    ORDER BY barcode, doc_date LIMIT 12"""):
    print(f"  {r.doc_date} dt={r.incoming_datetime} №{r.doc_number} {str(r.store)[:18]:<18} {r.barcode} "
          f"q={r.quantity} p={r.price_purchase} s={r.amount_purchase:>9.2f} {r.source_file}")

print("\n=== 3. Массовая картина: один документ, две разные doc_date ===")
for r in cli.query(f"""
    SELECT FORMAT_DATE('%Y-%m', doc_date) per, COUNT(*) n, SUM(amt) suma
    FROM (
      SELECT doc_number, store, supplier, barcode, quantity, price_purchase,
             MIN(doc_date) doc_date, COUNT(DISTINCT doc_date) nd, SUM(amount_purchase) amt
      FROM {T}
      WHERE doc_date >= '2026-01-01' AND doc_number IS NOT NULL
      GROUP BY 1,2,3,4,5,6 HAVING nd > 1)
    GROUP BY 1 ORDER BY 1"""):
    print(f"  {r.per}  строк-двойников {r.n:>5}  на {r.suma:>14,.0f} ₴")

print("\n=== 4. Массовая картина: одинаковая строка, разный source_file и разная дата ===")
for r in cli.query(f"""
    SELECT FORMAT_DATE('%Y-%m', doc_date) per,
           COUNTIF(nf > 1) files, COUNTIF(nd > 1) dates, COUNTIF(ndn > 1) nums
    FROM (
      SELECT MIN(doc_date) doc_date, COUNT(DISTINCT source_file) nf,
             COUNT(DISTINCT doc_date) nd, COUNT(DISTINCT IFNULL(doc_number,'')) ndn
      FROM {T} WHERE doc_date >= '2026-01-01'
      GROUP BY store, supplier, barcode, quantity, price_purchase,
               FORMAT_DATE('%Y-%m', doc_date))
    GROUP BY 1 ORDER BY 1"""):
    print(f"  {r.per}  групп с >1 файлом {r.files:>5} | с >1 датой {r.dates:>5} | с >1 номером {r.nums:>5}")

print("\n=== 5. Сколько строк грузилось несколькими файлами (один line_id, разный source_file нельзя) ===")
for r in cli.query(f"""
    SELECT FORMAT_DATE('%Y-%m', doc_date) per, source_file, COUNT(*) n, SUM(amount_purchase) amt
    FROM {T} WHERE doc_date >= '2026-07-01'
    GROUP BY 1,2 HAVING n > 0 ORDER BY 1, n DESC LIMIT 25"""):
    print(f"  {r.per}  {r.source_file[:60]:<60} {r.n:>7} строк {r.amt:>14,.0f} ₴")

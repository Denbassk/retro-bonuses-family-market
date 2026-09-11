import os, sys
sys.stdout.reconfigure(encoding='utf-8')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'D:\Family_Market_Analytics\credentials\family-market-analytics-23fbcbcee571c.json'
from google.cloud import bigquery
client = bigquery.Client(project='family-market-analytics')

# 1. Всі supplier names з incoming для СТВ Схід
print("=== ВСІ SUPPLIER NAMES СТВ Схід в incoming (квітень-травень) ===")
q1 = """
SELECT DISTINCT supplier, SUM(amount_purchase) as total
FROM `family-market-analytics.family_market.incoming_transactions`
WHERE doc_date BETWEEN '2026-04-01' AND '2026-05-31'
  AND (supplier LIKE '%СТВ%' OR supplier LIKE '%Корона%' OR supplier LIKE '%Монделіс%' OR supplier LIKE '%Milka%')
GROUP BY supplier ORDER BY total DESC
"""
for r in client.query(q1).result():
    print(f"  [{round(float(r.total),2)}] {r.supplier}")

# 2. Чи є negative в incoming для всіх СТВ Схід?
print()
print("=== NEGATIVE РЯДКИ в incoming (СТВ Схід, квітень-травень) ===")
q2 = """
SELECT supplier, doc_date, CAST(barcode AS STRING) as bc, amount_purchase
FROM `family-market-analytics.family_market.incoming_transactions`
WHERE doc_date BETWEEN '2026-04-01' AND '2026-05-31'
  AND supplier LIKE '%СТВ%'
  AND amount_purchase < 0
ORDER BY doc_date
"""
neg_rows = list(client.query(q2).result())
if neg_rows:
    for r in neg_rows:
        print(f"  {r.doc_date} | {r.supplier} | {r.bc} | {r.amount_purchase}")
else:
    print("  Негативних записів немає")

# 3. Порівняємо базу по місяцях — чи є в BQ документи що прийшли ПІСЛЯ початку місяця
# (тобто заднім числом в квітні/травні)
print()
print("=== КВІТЕНЬ: прихід по тижнях ===")
q3 = """
SELECT
  DATE_TRUNC(doc_date, WEEK) as week_start,
  SUM(amount_purchase) as week_total
FROM `family-market-analytics.family_market.incoming_transactions`
WHERE doc_date BETWEEN '2026-04-01' AND '2026-04-30'
  AND supplier LIKE '%СТВ Схід%Корона%'
GROUP BY week_start ORDER BY week_start
"""
total_apr = 0
for r in client.query(q3).result():
    wt = float(r.week_total)
    total_apr += wt
    print(f"  Тиждень {r.week_start}: {round(wt,2)}")
print(f"  Разом квітень: {round(total_apr,2)}")
print(f"  База клієнта:  513955.0 (102791/20%)")
print(f"  Різниця:       {round(total_apr - 513955.0, 2)}")

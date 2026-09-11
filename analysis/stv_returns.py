import os, sys
sys.stdout.reconfigure(encoding='utf-8')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'D:\Family_Market_Analytics\credentials\family-market-analytics-23fbcbcee571c.json'
from google.cloud import bigquery
client = bigquery.Client(project='family-market-analytics')

# Які supplier імена є в outgoing по СТВ Схід?
print("=== SUPPLIER NAMES в outgoing_to_supplier ===")
q0 = """
SELECT DISTINCT supplier, COUNT(*) as cnt, SUM(amount_purchase) as total
FROM `family-market-analytics.family_market.outgoing_to_supplier_transactions`
WHERE doc_date BETWEEN '2026-04-01' AND '2026-05-31'
  AND supplier LIKE '%СТВ%'
GROUP BY supplier ORDER BY total DESC
"""
for r in client.query(q0).result():
    print(f"  {r.supplier} | {r.cnt} рядків | {round(float(r.total or 0),2)} грн")

# Повернення тільки Корона
print()
print("=== ПОВЕРНЕННЯ КОРОНА (outgoing) — по місяцях ===")
for month, d1, d2, our_base in [
    ('КВІТЕНЬ', '2026-04-01', '2026-04-30', 518664.18),
    ('ТРАВЕНЬ',  '2026-05-01', '2026-05-31', 524955.36),
]:
    q1 = f"""
    SELECT SUM(amount_purchase) as ret_total, COUNT(*) as cnt
    FROM `family-market-analytics.family_market.outgoing_to_supplier_transactions`
    WHERE doc_date BETWEEN '{d1}' AND '{d2}'
      AND supplier LIKE '%СТВ Схід%Корона%'
    """
    r1 = list(client.query(q1).result())[0]
    ret = float(r1.ret_total or 0)
    net_base = our_base - ret
    retro = round(net_base * 0.20, 2)
    print(f"  {month}: повернення={round(ret,2)} ({r1.cnt} рядків)")
    print(f"    Наша база: {our_base} - {round(ret,2)} = {round(net_base,2)}")
    print(f"    Ретро 20%: {retro}")

import os, sys
sys.stdout.reconfigure(encoding='utf-8')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = r'D:\Family_Market_Analytics\credentials\family-market-analytics-23fbcbcee571c.json'
from google.cloud import bigquery
client = bigquery.Client(project='family-market-analytics')

for month, d1, d2, our_base, paid in [
    ('БЕРЕЗЕНЬ', '2026-03-01', '2026-03-31', 501947.40, 100391.00),
    ('КВІТЕНЬ',  '2026-04-01', '2026-04-30', 518664.18, 102791.00),
    ('ТРАВЕНЬ',  '2026-05-01', '2026-05-31', 524955.36, 103712.00),
]:
    q = f"""
    SELECT
      SUM(CASE WHEN amount_purchase > 0 THEN amount_purchase ELSE 0 END) AS incoming,
      SUM(CASE WHEN amount_purchase < 0 THEN amount_purchase ELSE 0 END) AS returns,
      SUM(amount_purchase) AS net,
      COUNT(CASE WHEN amount_purchase < 0 THEN 1 END) AS return_rows
    FROM `family-market-analytics.family_market.incoming_transactions`
    WHERE doc_date BETWEEN '{d1}' AND '{d2}'
      AND supplier LIKE '%СТВ Схід%Корона%'
    """
    r = list(client.query(q).result())[0]
    inc = float(r.incoming or 0)
    ret = float(r.returns or 0)
    net = float(r.net or 0)
    client_base = paid / 0.20
    print(f"=== {month} ===")
    print(f"  BQ прихід:    {round(inc,2)}")
    print(f"  BQ повернення:{round(ret,2)}  ({r.return_rows} рядків)")
    print(f"  BQ нетто:     {round(net,2)}")
    print(f"  Наша база:    {our_base}  (saved in Supabase)")
    print(f"  База клієнта: {round(client_base,2)}  ({paid}/20%)")
    print(f"  Різниця баз:  {round(net - client_base,2)}")
    print()

# Також перевіримо outgoing_to_supplier
print("=== OUTGOING_TO_SUPPLIER (повернення постачальнику) ===")
for month, d1, d2 in [('КВІТЕНЬ','2026-04-01','2026-04-30'), ('ТРАВЕНЬ','2026-05-01','2026-05-31')]:
    try:
        q2 = f"""
        SELECT SUM(amount_purchase) as ret_total, COUNT(*) as cnt
        FROM `family-market-analytics.family_market.outgoing_to_supplier_transactions`
        WHERE doc_date BETWEEN '{d1}' AND '{d2}'
          AND supplier LIKE '%СТВ Схід%'
        """
        r2 = list(client.query(q2).result())[0]
        print(f"  {month}: {round(float(r2.ret_total or 0),2)} грн ({r2.cnt} записів)")
    except Exception as e:
        print(f"  {month}: помилка — {e}")

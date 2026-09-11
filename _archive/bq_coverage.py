import os
from pathlib import Path
def load_env(p=None):
    p = p or Path(__file__).parent / ".env"
    if not p.exists(): return
    for l in open(p, encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#"):
            k, _, v = l.partition("="); os.environ.setdefault(k.strip(), v.strip())
load_env()
from google.cloud import bigquery
P = os.environ.get("BQ_PROJECT", "family-market-analytics")
D = os.environ.get("BQ_DATASET", "family_market")
c = bigquery.Client(project=P)
for t, f in [("torgsoft_incoming_ref_2026","amount"),
             ("torgsoft_outgoing_ref","amount_purchase"),
             ("incoming_transactions","amount_purchase"),
             ("outgoing_to_supplier_transactions","amount_purchase")]:
    r = list(c.query(f"""SELECT MIN(doc_date) a, MAX(doc_date) b, COUNT(*) n,
                         COUNT(DISTINCT FORMAT_DATE('%Y-%m', doc_date)) m
                         FROM `{P}.{D}.{t}` WHERE EXTRACT(YEAR FROM doc_date)=2026"""))[0]
    print(f"{t:<40} {r['a']} .. {r['b']}   строк={r['n']:,}  месяцев={r['m']}")

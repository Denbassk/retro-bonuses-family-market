#!/usr/bin/env python3
"""probe_gap_docs.py - чем объясняется каждая дыра: нет вовсе / другой алиас / сдвиг даты."""
import os, csv
from collections import defaultdict
from datetime import date, timedelta
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
cli = bigquery.Client(project=P)

gaps = list(csv.DictReader(open("bq_gaps.csv", encoding="utf-8-sig"), delimiter=";"))
print(f"дыр на проверку: {len(gaps)}\n")

print("тяну сводку документов incoming_transactions за 2026...")
rows = list(cli.query(f"""
  SELECT doc_number, supplier, doc_date, ROUND(SUM(amount_purchase),2) amt
  FROM `{P}.{D}.incoming_transactions`
  WHERE EXTRACT(YEAR FROM doc_date)=2026
  GROUP BY 1,2,3
"""))
print(f"документов у нас: {len(rows):,}\n")

by_num = defaultdict(list)
by_amt = defaultdict(list)
for r in rows:
    by_num[str(r["doc_number"])].append(r)
    by_amt[round(float(r["amt"]), 2)].append(r)

out, stat = [], defaultdict(lambda: [0, 0.0])
for g in gaps:
    num, amt = g["doc_number"], round(float(g["amount"]), 2)
    d = date.fromisoformat(g["doc_date"])
    verdict, detail = "НЕТ ВОВСЕ", ""

    hit = by_num.get(num)
    if hit:
        h = hit[0]
        verdict = "ЕСТЬ ПО НОМЕРУ"
        detail = f"у нас: {h['supplier']} / {h['doc_date']} / {float(h['amt']):,.2f}"
    else:
        near = [r for r in by_amt.get(amt, [])
                if abs((r["doc_date"] - d).days) <= 7]
        if near:
            h = near[0]
            same = h["supplier"] == g["supplier_bq"]
            verdict = "СДВИГ ДАТЫ" if same else "ДРУГОЙ АЛИАС"
            detail = (f"у нас: {h['supplier']} / {h['doc_date']} / док {h['doc_number']}"
                      f" (±{(h['doc_date']-d).days} дн)")

    stat[verdict][0] += 1
    stat[verdict][1] += amt
    out.append([g["supplier_canon"], g["doc_date"], num, f"{amt:.2f}", verdict, detail])

with open("probe_gaps_result.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["supplier", "doc_date", "doc_number", "amount", "verdict", "detail"])
    w.writerows(out)

print("ИТОГ:")
for k, (n, s) in sorted(stat.items(), key=lambda x: -x[1][1]):
    print(f"  {k:<18} {n:>4} док  {s:>14,.2f}")

print("\nОДИНОЧНЫЕ ДАТЫ (не 29-30.07):")
for r in out:
    if r[1] not in ("2026-07-29", "2026-07-30"):
        print(f"  {r[0][:40]:<42}{r[1]}  {float(r[3]):>12,.2f}  {r[4]}")
        if r[5]:
            print(f"      {r[5]}")

print("\nCSV: probe_gaps_result.csv")

#!/usr/bin/env python3
"""
classify_gaps.py - корректная классификация дыр.

Исправляет две ошибки предыдущих скриптов:
  1) сравнение шло внутри одинаковой строки supplier -> разные написания алиаса
     одного поставщика давали ложные дыры. Теперь сводим к каноническому поставщику.
  2) совпадение по doc_number принималось без проверки суммы -> коллизии номеров
     между поставщиками. Теперь номер засчитывается только при совпадении суммы.

Вердикты:
  OK_MATCH      - документ есть, ложная тревога
  WRONG_BRAND   - есть, но отнесён к другому бренду ТОГО ЖЕ поставщика (перекос ставки!)
  WRONG_SUPPLIER- есть, но отнесён к чужому поставщику
  DATE_SHIFT    - есть, дата отличается (важно только при переходе через месяц)
  MISSING       - нет вовсе
"""
import os, csv
from collections import defaultdict
from datetime import date
from pathlib import Path

def load_env(p=None):
    p = p or Path(__file__).parent / ".env"
    if not p.exists(): return
    for l in open(p, encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#"):
            k, _, v = l.partition("="); os.environ.setdefault(k.strip(), v.strip())

load_env()
import sb
from google.cloud import bigquery

P = os.environ.get("BQ_PROJECT", "family-market-analytics")
D = os.environ.get("BQ_DATASET", "family_market")
cli = bigquery.Client(project=P)

# ── карта: строка поставщика в BQ -> канонический поставщик Supabase ──────────
sups   = {s["id"]: s.get("name") for s in sb.get("suppliers", "select=*")}
brands = {b["id"]: b for b in sb.get("supplier_brands", "select=*")}
canon = {}
for a in sb.get("supplier_aliases", "select=*"):
    nm = a.get("alias_name") or a.get("alias") or a.get("name")
    sid = a.get("supplier_id")
    if nm and sid:
        canon[nm.strip()] = sups.get(sid, "?")
for sid, nm in sups.items():
    if nm:
        canon.setdefault(nm.strip(), nm)

def C(s):
    return canon.get((s or "").strip(), (s or "").strip())

rows = list(cli.query(f"""
  SELECT doc_number, supplier, doc_date, ROUND(SUM(amount_purchase),2) amt
  FROM `{P}.{D}.incoming_transactions`
  WHERE EXTRACT(YEAR FROM doc_date)=2026 GROUP BY 1,2,3
"""))
print(f"документов у нас: {len(rows):,}")

by_num = defaultdict(list)
by_amt = defaultdict(list)
for r in rows:
    by_num[str(r["doc_number"])].append(r)
    by_amt[round(float(r["amt"]), 2)].append(r)

gaps = list(csv.DictReader(open("bq_gaps.csv", encoding="utf-8-sig"), delimiter=";"))
print(f"дыр на проверку: {len(gaps)}\n")

out, stat = [], defaultdict(lambda: [0, 0.0])
for g in gaps:
    num  = g["doc_number"]
    amt  = round(float(g["amount"]), 2)
    d    = date.fromisoformat(g["doc_date"])
    cbq  = C(g["supplier_bq"])

    cands = [r for r in by_num.get(num, []) if abs(float(r["amt"]) - amt) < 0.01]
    cands += [r for r in by_amt.get(amt, [])
              if abs((r["doc_date"] - d).days) <= 7 and r not in cands]

    if not cands:
        v, det = "MISSING", ""
    else:
        h = cands[0]
        ch = C(h["supplier"])
        dd = (h["doc_date"] - d).days
        if ch == cbq and dd == 0:
            v = "OK_MATCH"
        elif ch == cbq:
            v = "DATE_SHIFT"
        elif ch.split("(")[0].strip() == cbq.split("(")[0].strip():
            v = "WRONG_BRAND"
        else:
            v = "WRONG_SUPPLIER"
        det = f"{h['supplier']} / {h['doc_date']} / док {h['doc_number']} / {float(h['amt']):,.2f}"

    stat[v][0] += 1; stat[v][1] += amt
    out.append([g["supplier_canon"], g["doc_date"], num, f"{amt:.2f}", v, det])

with open("gaps_classified.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(["supplier", "doc_date", "doc_number", "amount", "verdict", "found_as"])
    w.writerows(out)

print("ИТОГ:")
for k, (n, s) in sorted(stat.items(), key=lambda x: -x[1][1]):
    print(f"  {k:<16}{n:>4} док {s:>14,.2f}")

miss = [r for r in out if r[4] == "MISSING"]
byday = defaultdict(float)
for r in miss:
    byday[r[1]] += float(r[3])
print("\nMISSING по датам:")
for dt, s in sorted(byday.items(), key=lambda x: -x[1]):
    print(f"  {dt}  {s:>13,.2f}  ({sum(1 for r in miss if r[1]==dt)} док)")

wb = [r for r in out if r[4] in ("WRONG_BRAND", "WRONG_SUPPLIER")]
if wb:
    print("\nПРИХОД ОТНЕСЁН НЕ ТУДА (перекос ставок):")
    for r in wb:
        print(f"  {r[0][:38]:<40}{r[1]}  {float(r[3]):>11,.2f}  {r[4]}")
        print(f"      у нас: {r[5]}")

print("\nCSV: gaps_classified.csv")

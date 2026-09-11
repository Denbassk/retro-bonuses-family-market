#!/usr/bin/env python3
"""find_bq_gaps.py - реальные дыры в incoming_transactions (только ретро-поставщики)."""
import os, csv, argparse
from collections import defaultdict
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


def months(a, b):
    y, m = int(a[:4]), int(a[5:7]); out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13: m, y = 1, y + 1
    return out


def retro_aliases():
    sups   = {s["id"]: s for s in sb.get("suppliers", "select=*")}
    brands = {b["id"]: b for b in sb.get("supplier_brands", "select=*")}
    rules  = sb.get("retro_rules", "select=*")
    als    = sb.get("supplier_aliases", "select=*")
    live = set()
    for r in rules:
        if (r.get("status") or "") != "active":
            continue
        sid = r.get("supplier_id") or (brands.get(r.get("supplier_brand_id")) or {}).get("supplier_id")
        if sid: live.add(sid)
    out = {}
    for a in als:
        sid = a.get("supplier_id")
        if sid in live and a.get("alias_name"):
            out[a["alias_name"]] = (sups.get(sid) or {}).get("name", "?")
    for sid in live:
        n = (sups.get(sid) or {}).get("name")
        if n: out.setdefault(n, n)
    return out


def fetch(table, field, aliases, per):
    y, m = int(per[:4]), int(per[5:7])
    sql = f"""
      SELECT supplier, doc_number, ANY_VALUE(doc_date) d, ROUND(SUM({field}),2) amt
      FROM `{P}.{D}.{table}`
      WHERE supplier IN UNNEST(@a)
        AND EXTRACT(YEAR FROM doc_date)=@y AND EXTRACT(MONTH FROM doc_date)=@m
      GROUP BY 1,2
    """
    job = cli.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ArrayQueryParameter("a", "STRING", aliases),
        bigquery.ScalarQueryParameter("y", "INT64", y),
        bigquery.ScalarQueryParameter("m", "INT64", m)]))
    res = defaultdict(dict)
    for r in job:
        res[r["supplier"]][str(r["doc_number"])] = (str(r["d"]), float(r["amt"]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="a", default="2026-01")
    ap.add_argument("--to", dest="b", default="2026-08")
    ap.add_argument("--min", type=float, default=50.0)
    ar = ap.parse_args()

    amap = retro_aliases()
    aliases = sorted(amap)
    print(f"Ретро-поставщиков (алиасов): {len(aliases)}\n")

    gaps, by_day, dup_total = [], defaultdict(float), 0.0

    for per in months(ar.a, ar.b):
        E = fetch("torgsoft_incoming_ref_2026", "amount", aliases, per)
        O = fetch("incoming_transactions", "amount_purchase", aliases, per)
        for sup in set(E) | set(O):
            e, o = E.get(sup, {}), O.get(sup, {})
            matched = {k for k in e if k in o}
            # ключи уже совпавших документов: (дата, сумма)
            seen = defaultdict(int)
            for k in matched:
                seen[e[k]] += 1
            for k in o:
                if k not in e:
                    seen[o[k]] += 1
            for k in e:
                if k in o:
                    continue
                d, amt = e[k]
                if abs(amt) < 0.01:
                    continue
                if seen.get((d, amt), 0) > 0:
                    seen[(d, amt)] -= 1
                    dup_total += amt
                    continue
                if amt >= ar.min:
                    gaps.append((amap.get(sup, sup), sup, per, d, k, amt))
                    by_day[d] += amt

    gaps.sort(key=lambda x: -x[5])
    with open("bq_gaps.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["supplier_canon", "supplier_bq", "period", "doc_date", "doc_number", "amount"])
        for g in gaps:
            w.writerow([g[0], g[1], g[2], g[3], g[4], f"{g[5]:.2f}"])

    tot = sum(g[5] for g in gaps)
    print(f"Погашено как дубли нумерации эталона: {dup_total:,.2f}")
    print(f"РЕАЛЬНЫЕ ДЫРЫ: {len(gaps)} документов на {tot:,.2f}")
    print(f"  недоначислено ретро ориентировочно (12%): {tot*0.12:,.0f}\n")

    if by_day:
        print("ПО ДАТАМ (топ-15) — ищем оборванные загрузки:")
        for d, s in sorted(by_day.items(), key=lambda x: -x[1])[:15]:
            n = sum(1 for g in gaps if g[3] == d)
            print(f"  {d}   {s:>14,.2f}   документов: {n}")

    agg = defaultdict(float)
    for g in gaps:
        agg[g[0]] += g[5]
    print("\nПО ПОСТАВЩИКАМ (топ-15):")
    for s, v in sorted(agg.items(), key=lambda x: -x[1])[:15]:
        print(f"  {s[:45]:<47}{v:>14,.2f}")

    print("\nCSV: bq_gaps.csv")


if __name__ == "__main__":
    main()

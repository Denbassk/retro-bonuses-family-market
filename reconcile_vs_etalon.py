#!/usr/bin/env python3
"""
reconcile_vs_etalon.py - сверка детальных таблиц BQ с эталонами Торгсофт.

Эталоны документного уровня, без barcode -> сверяем ПОЛНЫЙ оборот поставщика
без SKU-фильтров. Это контроль слоя данных, а не слоя правил.

  torgsoft_incoming_ref_2026 (amount)          vs incoming_transactions (amount_purchase)
  torgsoft_outgoing_ref      (amount_purchase) vs outgoing_to_supplier_transactions

Запуск:
  python reconcile_vs_etalon.py --year 2026
  python reconcile_vs_etalon.py --year 2026 --min-delta 1000
  python reconcile_vs_etalon.py --docs --supplier "Монжар" --period 2026-05
"""
import os, csv, argparse
from pathlib import Path


def load_env(p=None):
    p = p or Path(__file__).parent / ".env"
    if not p.exists():
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


load_env()
from google.cloud import bigquery

PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics")
DS = os.environ.get("BQ_DATASET", "family_market")
T = f"`{PROJ}.{DS}"
cli = bigquery.Client(project=PROJ)


def run(sql, **params):
    tp = []
    for k, v in params.items():
        t = "INT64" if isinstance(v, int) else "STRING"
        tp.append(bigquery.ScalarQueryParameter(k, t, v))
    return list(cli.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=tp)))


def money(x):
    return f"{x:>16,.2f}"


def agg_incoming(year):
    return run(f"""
      WITH e AS (
        SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per,
               SUM(amount) amt, COUNT(DISTINCT doc_number) docs
        FROM {T}.torgsoft_incoming_ref_2026`
        WHERE EXTRACT(YEAR FROM doc_date) = @y
        GROUP BY 1,2),
      o AS (
        SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per,
               SUM(amount_purchase) amt, COUNT(DISTINCT doc_number) docs
        FROM {T}.incoming_transactions`
        WHERE EXTRACT(YEAR FROM doc_date) = @y
        GROUP BY 1,2)
      SELECT COALESCE(e.supplier,o.supplier) supplier,
             COALESCE(e.per,o.per) per,
             IFNULL(e.amt,0) etalon, IFNULL(o.amt,0) ours,
             IFNULL(e.amt,0)-IFNULL(o.amt,0) delta,
             IFNULL(e.docs,0) e_docs, IFNULL(o.docs,0) o_docs
      FROM e FULL OUTER JOIN o ON e.supplier=o.supplier AND e.per=o.per
      ORDER BY ABS(IFNULL(e.amt,0)-IFNULL(o.amt,0)) DESC
    """, y=year)


def agg_returns(year):
    return run(f"""
      WITH e AS (
        SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per,
               SUM(amount_purchase) all_amt,
               SUM(IF(NOT IFNULL(is_internal,FALSE), amount_purchase, 0)) ext_amt,
               SUM(IF(NOT IFNULL(is_internal,FALSE)
                      AND NOT IFNULL(is_prosrok,FALSE), amount_purchase, 0)) clean_amt,
               COUNT(DISTINCT doc_number) docs
        FROM {T}.torgsoft_outgoing_ref`
        WHERE EXTRACT(YEAR FROM doc_date) = @y
        GROUP BY 1,2),
      o AS (
        SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per,
               SUM(amount_purchase) amt, COUNT(DISTINCT doc_number) docs
        FROM {T}.outgoing_to_supplier_transactions`
        WHERE EXTRACT(YEAR FROM doc_date) = @y
        GROUP BY 1,2)
      SELECT COALESCE(e.supplier,o.supplier) supplier,
             COALESCE(e.per,o.per) per,
             IFNULL(e.all_amt,0) e_all, IFNULL(e.ext_amt,0) e_ext,
             IFNULL(e.clean_amt,0) e_clean, IFNULL(o.amt,0) ours,
             IFNULL(e.docs,0) e_docs, IFNULL(o.docs,0) o_docs
      FROM e FULL OUTER JOIN o ON e.supplier=o.supplier AND e.per=o.per
      ORDER BY ABS(IFNULL(e.ext_amt,0)-IFNULL(o.amt,0)) DESC
    """, y=year)


def docs_diff(supplier, period):
    y, m = int(period[:4]), int(period[5:7])
    rows = run(f"""
      WITH e AS (
        SELECT doc_number, ANY_VALUE(doc_date) d, SUM(amount) amt
        FROM {T}.torgsoft_incoming_ref_2026`
        WHERE LOWER(supplier) LIKE @s
          AND EXTRACT(YEAR FROM doc_date)=@y AND EXTRACT(MONTH FROM doc_date)=@m
        GROUP BY 1),
      o AS (
        SELECT doc_number, ANY_VALUE(doc_date) d, SUM(amount_purchase) amt
        FROM {T}.incoming_transactions`
        WHERE LOWER(supplier) LIKE @s
          AND EXTRACT(YEAR FROM doc_date)=@y AND EXTRACT(MONTH FROM doc_date)=@m
        GROUP BY 1)
      SELECT COALESCE(e.doc_number,o.doc_number) doc,
             COALESCE(e.d,o.d) d,
             IFNULL(e.amt,0) etalon, IFNULL(o.amt,0) ours,
             IFNULL(e.amt,0)-IFNULL(o.amt,0) delta
      FROM e FULL OUTER JOIN o USING (doc_number)
      ORDER BY ABS(IFNULL(e.amt,0)-IFNULL(o.amt,0)) DESC, d
    """, s=f"%{supplier.lower()}%", y=y, m=m)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--min-delta", type=float, default=100.0)
    ap.add_argument("--supplier")
    ap.add_argument("--period")
    ap.add_argument("--docs", action="store_true")
    a = ap.parse_args()

    if a.docs:
        if not (a.supplier and a.period):
            print("для --docs нужны --supplier и --period")
            return
        rows = docs_diff(a.supplier, a.period)
        print(f"\nДОКУМЕНТЫ: {a.supplier} / {a.period}\n")
        print(f"{'документ':<22}{'дата':<12}{'эталон':>16}{'у нас':>16}{'дельта':>14}")
        tot = 0.0
        for r in rows:
            d = float(r["delta"])
            tot += d
            mark = "" if abs(d) < 0.01 else "  <<<"
            print(f"{str(r['doc']):<22}{str(r['d']):<12}"
                  f"{money(float(r['etalon']))}{money(float(r['ours']))}"
                  f"{d:>14,.2f}{mark}")
        print(f"\nИТОГО дельта: {tot:,.2f}   документов: {len(rows)}")
        return

    # ── приходы ──────────────────────────────────────────────────────────
    inc = agg_incoming(a.year)
    if a.supplier:
        inc = [r for r in inc if a.supplier.lower() in (r["supplier"] or "").lower()]
    if a.period:
        inc = [r for r in inc if r["per"] == a.period]

    with open(f"etalon_incoming_{a.year}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["supplier", "period", "etalon", "ours", "delta", "etalon_docs", "our_docs"])
        for r in inc:
            w.writerow([r["supplier"], r["per"], f"{float(r['etalon']):.2f}",
                        f"{float(r['ours']):.2f}", f"{float(r['delta']):.2f}",
                        r["e_docs"], r["o_docs"]])

    bad = [r for r in inc if abs(float(r["delta"])) >= a.min_delta]
    te, to = sum(float(r["etalon"]) for r in inc), sum(float(r["ours"]) for r in inc)
    print(f"\n{'='*78}\nПРИХОДЫ {a.year}: эталон {te:,.2f} | наши {to:,.2f} | дельта {te-to:,.2f}")
    print(f"пар поставщик-месяц: {len(inc)}, расхождений >= {a.min_delta:,.0f}: {len(bad)}\n")
    if bad:
        print(f"{'поставщик':<38}{'период':<9}{'эталон':>15}{'наши':>15}{'дельта':>14}  док")
        for r in bad[:40]:
            print(f"{(r['supplier'] or '<нет>')[:37]:<38}{r['per']:<9}"
                  f"{float(r['etalon']):>15,.0f}{float(r['ours']):>15,.0f}"
                  f"{float(r['delta']):>14,.0f}  {r['e_docs']}/{r['o_docs']}")
        if len(bad) > 40:
            print(f"    ... ещё {len(bad)-40}, полный список в CSV")

    only_e = sorted({r["supplier"] for r in inc if float(r["ours"]) == 0 and float(r["etalon"]) != 0})
    only_o = sorted({r["supplier"] for r in inc if float(r["etalon"]) == 0 and float(r["ours"]) != 0})
    if only_e:
        print(f"\n[!] Есть в эталоне, НЕТ у нас ({len(only_e)}): {', '.join(only_e[:12])}")
    if only_o:
        print(f"[!] Есть у нас, НЕТ в эталоне ({len(only_o)}): {', '.join(only_o[:12])}")

    # ── возвраты ─────────────────────────────────────────────────────────
    ret = agg_returns(a.year)
    if a.supplier:
        ret = [r for r in ret if a.supplier.lower() in (r["supplier"] or "").lower()]
    if a.period:
        ret = [r for r in ret if r["per"] == a.period]

    with open(f"etalon_returns_{a.year}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["supplier", "period", "etalon_all", "etalon_no_internal",
                    "etalon_clean", "ours", "delta_no_internal", "etalon_docs", "our_docs"])
        for r in ret:
            w.writerow([r["supplier"], r["per"], f"{float(r['e_all']):.2f}",
                        f"{float(r['e_ext']):.2f}", f"{float(r['e_clean']):.2f}",
                        f"{float(r['ours']):.2f}",
                        f"{float(r['e_ext'])-float(r['ours']):.2f}",
                        r["e_docs"], r["o_docs"]])

    s_all = sum(float(r["e_all"]) for r in ret)
    s_ext = sum(float(r["e_ext"]) for r in ret)
    s_cln = sum(float(r["e_clean"]) for r in ret)
    s_our = sum(float(r["ours"]) for r in ret)
    print(f"\n{'='*78}\nВОЗВРАТЫ {a.year}: наши {s_our:,.2f}")
    print(f"  эталон, всё подряд          {s_all:>16,.2f}   дельта {s_all-s_our:>14,.2f}")
    print(f"  эталон, без is_internal     {s_ext:>16,.2f}   дельта {s_ext-s_our:>14,.2f}")
    print(f"  эталон, без internal+prosrok{s_cln:>16,.2f}   дельта {s_cln-s_our:>14,.2f}")
    best = min([("всё подряд", s_all), ("без internal", s_ext),
                ("без internal+prosrok", s_cln)], key=lambda x: abs(x[1] - s_our))
    print(f"  -> ближе всего к нашим данным: «{best[0]}»")

    rbad = [r for r in ret if abs(float(r["e_ext"]) - float(r["ours"])) >= a.min_delta]
    print(f"\nрасхождений (база: без internal) >= {a.min_delta:,.0f}: {len(rbad)}\n")
    if rbad:
        print(f"{'поставщик':<38}{'период':<9}{'эталон':>14}{'наши':>14}{'дельта':>13}  док")
        for r in rbad[:30]:
            print(f"{(r['supplier'] or '<нет>')[:37]:<38}{r['per']:<9}"
                  f"{float(r['e_ext']):>14,.0f}{float(r['ours']):>14,.0f}"
                  f"{float(r['e_ext'])-float(r['ours']):>13,.0f}  {r['e_docs']}/{r['o_docs']}")
        if len(rbad) > 30:
            print(f"    ... ещё {len(rbad)-30}, полный список в CSV")

    print(f"\nCSV: etalon_incoming_{a.year}.csv, etalon_returns_{a.year}.csv")


if __name__ == "__main__":
    main()

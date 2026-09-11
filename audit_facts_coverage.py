#!/usr/bin/env python3
"""
audit_facts_coverage.py - аудит покрытия фактов по всем месяцам.

Сводит три источника: ячейки Excel, retro_payments_fact (админка), retro_calculations (расчёт).
Отличает перераспределение доплат от реальных расхождений: сравнивает годовые суммы
в окне месяцев, где у поставщика есть хотя бы один факт (пустые ячейки Excel учитываются).

Ничего не пишет в БД.

Запуск:
  python audit_facts_coverage.py "Ретро Бонусы.xlsx" --sheet 2026 --upto 7
"""
import re, csv, argparse
from pathlib import Path
from collections import defaultdict
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

import sb
from import_retro_facts import norm_name, parse_amount, classify_header, STOP_NAMES

CALC_COLS = ("total_retro_amount", "retro_amount_total", "retro_total",
             "total_amount", "amount_total", "retro_amount", "calculated_amount")
EPS = 0.5


def pick_calc_col(rows):
    if not rows:
        return None
    keys = list(rows[0].keys())
    for c in CALC_COLS:
        if c in keys:
            return c
    num = [k for k in keys if isinstance(rows[0][k], (int, float))
           and any(t in k for t in ("amount", "retro", "sum"))]
    if num:
        print(f"    (кандидаты: {', '.join(num)})")
        return num[0]
    print(f"    (числовых колонок не нашёл; доступны: {', '.join(keys)})")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--sheet", default="2026")
    ap.add_argument("--header-row", type=int, default=1)
    ap.add_argument("--upto", type=int, default=None)
    ap.add_argument("--calc-col", default=None)
    args = ap.parse_args()

    year = int(re.search(r"(20\d{2})", args.sheet).group(1))
    ws = load_workbook(Path(args.xlsx), data_only=True)[args.sheet]

    cols = {}
    for c in range(2, ws.max_column + 1):
        cl = classify_header(ws.cell(row=args.header_row, column=c).value, year)
        if cl and cl[0] == "month":
            cols[c] = cl[1]

    nmap = {m["excel_name_normalized"]: m for m in sb.get(
        "retro_fact_name_map",
        "select=excel_name_normalized,supplier_id,is_ignored,split_targets")}
    sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}

    excel, rowname = {}, {}
    for r in range(args.header_row + 1, ws.max_row + 1):
        v = ws.cell(row=r, column=1).value
        if v is None or not str(v).strip():
            continue
        nm = norm_name(str(v).strip())
        if nm in STOP_NAMES:
            continue
        mp = nmap.get(nm)
        if not mp or mp.get("is_ignored") or mp.get("split_targets") or not mp.get("supplier_id"):
            continue
        sid = mp["supplier_id"]
        rowname[sid] = (r, str(v).strip())
        for c, per in cols.items():
            excel[(sid, per)] = (parse_amount(ws.cell(row=r, column=c).value),
                                 f"{get_column_letter(c)}{r}")

    facts = {(x["supplier_id"], x["period_label"]): float(x["amount_paid"])
             for x in sb.get("retro_payments_fact",
                             f"select=supplier_id,period_label,amount_paid&period_label=like.{year}-*")}

    craw = sb.get("retro_calculations", f"select=*&period_label=like.{year}-*")
    ccol = args.calc_col or pick_calc_col(craw)
    print(f"[i] Колонка суммы расчёта: {ccol or 'НЕ НАЙДЕНА'}")
    calc = {(x["supplier_id"], x["period_label"]): float(x[ccol])
            for x in craw if ccol and x.get(ccol) is not None}

    months = sorted(cols.values())
    if args.upto:
        months = [m for m in months if int(m.split("-")[1]) <= args.upto]

    sids = {k[0] for k in excel} | {k[0] for k in facts} | {k[0] for k in calc}
    out, cells_by_sup, stat = [], defaultdict(list), defaultdict(int)

    for sid in sids:
        in_sheet = sid in rowname
        for per in months:
            ex, cell = excel.get((sid, per), (None, ""))
            ft, cl = facts.get((sid, per)), calc.get((sid, per))
            has_ex, has_ft = ex is not None, ft is not None
            if not (has_ex or has_ft or cl is not None):
                continue

            if not in_sheet:
                st = "NO_ROW_IN_EXCEL"
            elif has_ex and has_ft:
                st = "MATCH" if abs(ex - ft) < EPS else "CONFLICT"
            elif has_ex:
                st = "NOT_IMPORTED"
            elif has_ft:
                st = "FACT_ONLY"
            else:
                st = "CALC_NO_FACT"

            stat[st] += 1
            rec = {"supplier": sup.get(sid, sid), "period": per, "cell": cell,
                   "status": st, "excel": ex, "fact": ft, "calc": cl,
                   "delta_excel_fact": (ex or 0) - (ft or 0) if (has_ex or has_ft) else None}
            out.append(rec)
            if in_sheet:
                cells_by_sup[sid].append((per, cell, st, ex, ft))

    print(f"[i] Поставщиков: {len(sids)} | месяцев: {len(months)}\n")
    for k in ("MATCH", "CONFLICT", "NOT_IMPORTED", "FACT_ONLY", "CALC_NO_FACT", "NO_ROW_IN_EXCEL"):
        print(f"    {k:<17} {stat[k]}")

    redis, real, pending = [], [], defaultdict(list)
    for sid, rows in cells_by_sup.items():
        fact_months = [p for p, _, _, _, ft in rows if ft is not None]
        if not fact_months:
            continue
        win = max(fact_months)
        inwin = [x for x in rows if x[0] <= win]
        diff = sum((ex or 0) - (ft or 0) for _, _, _, ex, ft in inwin)
        bad = [x for x in inwin if x[2] in ("CONFLICT", "FACT_ONLY")]
        if not bad:
            continue
        (redis if abs(diff) < EPS else real).append((sid, diff, win, bad))
        for p, cell, st, ex, ft in rows:
            if st == "NOT_IMPORTED":
                pending[p].append((sup.get(sid, sid), cell, ex))

    print(f"\n[i] ПЕРЕРАСПРЕДЕЛЕНИЕ (годовая сумма сходится) — {len(redis)} поставщиков.")
    print("    Excel держит доплату в месяце платежа, админка разнесла по месяцам начисления.")
    for sid, diff, win, bad in sorted(redis, key=lambda x: sup.get(x[0], "")):
        print(f"    {sup.get(sid, sid)[:45]}  (окно до {win})")
        for p, cell, st, ex, ft in sorted(bad):
            print(f"        {p}  {cell:<6} админка {(ft or 0):>11,.0f} | "
                  f"excel {(ex if ex is not None else 0):>11,.0f} | "
                  f"{((ex or 0)-(ft or 0)):>+10,.0f}  {st}")

    print(f"\n[!] РЕАЛЬНЫЕ расхождения — {len(real)} поставщиков:")
    for sid, diff, win, bad in sorted(real, key=lambda x: -abs(x[1])):
        print(f"    {sup.get(sid, sid)[:45]}   итого {diff:>+12,.0f}  (окно до {win})")
        for p, cell, st, ex, ft in sorted(bad):
            print(f"        {p}  {cell:<6} админка {(ft or 0):>11,.0f} | "
                  f"excel {(ex if ex is not None else 0):>11,.0f} | "
                  f"{((ex or 0)-(ft or 0)):>+10,.0f}  {st}")

    print(f"\n[i] Есть в Excel, нет в админке — к импорту ({stat['NOT_IMPORTED']}):")
    byp = defaultdict(list)
    for r in out:
        if r["status"] == "NOT_IMPORTED":
            byp[r["period"]].append(r)
    for p in sorted(byp):
        tot = sum(x["excel"] for x in byp[p])
        print(f"    {p}: {len(byp[p]):>2} ячеек, сумма {tot:>12,.0f}")

    gaps = [r for r in out if r["status"] == "CALC_NO_FACT"]
    if gaps:
        print(f"\n[!] Расчёт есть, оплаты нет нигде ({len(gaps)}):")
        for r in sorted(gaps, key=lambda x: -(x["calc"] or 0)):
            print(f"    {r['period']}  {r['supplier'][:38]:<38} начислено {r['calc']:>12,.2f}")

    dst = Path(f"facts_coverage_{year}.csv")
    with dst.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(sorted(out, key=lambda x: (x["supplier"], x["period"])))
    print(f"\n[>] {dst}")


if __name__ == "__main__":
    main()

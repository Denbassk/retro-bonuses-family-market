#!/usr/bin/env python3
"""
diagnose_retro.py - ЭТАП 5: диагностика расхождений «расчёт vs факт».

Для поставщика и периода поднимает правила, расчёт, факт и сырые данные BigQuery,
затем проверяет набор гипотез и показывает, какая объясняет дельту.

Запуск:
  python diagnose_retro.py --supplier "Моршин" --period 2026-05
  python diagnose_retro.py --period 2026-06 --all
"""
import os, re, argparse
from datetime import date, timedelta
from decimal import Decimal

import sb

PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics")
DS = os.environ.get("BQ_DATASET", "family_market")
TOL_ABS, TOL_PCT = 50.0, 1.5


def bq():
    from google.cloud import bigquery
    return bigquery.Client(project=PROJ)


def q_sum(cli, table, aliases, d1, d2, field="amount_purchase", date_col="doc_date"):
    from google.cloud import bigquery
    if not aliases:
        return 0.0, 0
    sql = f"""
      SELECT IFNULL(SUM({field}),0) t, COUNT(*) c
      FROM `{PROJ}.{DS}.{table}`
      WHERE supplier IN UNNEST(@a) AND DATE({date_col}) BETWEEN @d1 AND @d2
    """
    job = cli.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[
        bigquery.ArrayQueryParameter("a", "STRING", aliases),
        bigquery.ScalarQueryParameter("d1", "DATE", d1),
        bigquery.ScalarQueryParameter("d2", "DATE", d2)]))
    r = list(job)[0]
    return float(r["t"]), int(r["c"])


def q_suppliers_like(cli, words, d1, d2):
    from google.cloud import bigquery
    if not words:
        return []
    cond = " OR ".join(f"LOWER(supplier) LIKE @w{i}" for i in range(len(words)))
    sql = f"""
      SELECT supplier, SUM(amount_purchase) t, COUNT(*) c
      FROM `{PROJ}.{DS}.incoming_transactions`
      WHERE DATE(doc_date) BETWEEN @d1 AND @d2 AND ({cond})
      GROUP BY 1 ORDER BY t DESC
    """
    p = [bigquery.ScalarQueryParameter("d1", "DATE", d1),
         bigquery.ScalarQueryParameter("d2", "DATE", d2)]
    p += [bigquery.ScalarQueryParameter(f"w{i}", "STRING", f"%{w.lower()}%")
          for i, w in enumerate(words)]
    return [(r["supplier"], float(r["t"]), int(r["c"]))
            for r in cli.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=p))]


def month_bounds(per):
    y, m = int(per[:4]), int(per[5:7])
    a = date(y, m, 1)
    b = (a.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return a, b


def active(rules, per):
    a, b = month_bounds(per)
    out = []
    for r in rules:
        if (r.get("status") or "") not in ("active", ""):
            continue
        vf = r.get("valid_from")
        vt = r.get("valid_to")
        if vf and str(vf) > str(b):
            continue
        if vt and str(vt) < str(a):
            continue
        out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--supplier")
    ap.add_argument("--period", required=True)
    ap.add_argument("--all", action="store_true", help="все поставщики с расхождением")
    args = ap.parse_args()

    per = args.period
    d1, d2 = month_bounds(per)

    sups = sb.get("suppliers", "select=*")
    brands = sb.get("supplier_brands", "select=*")
    rules = sb.get("retro_rules", "select=*")
    aliases = sb.get("supplier_aliases", "select=*")
    try:
        monthly = sb.get("supplier_monthly_bonuses", "select=*")
    except RuntimeError:
        monthly = []
    calc = {x["supplier_id"]: x for x in sb.get(
        "retro_calculations", f"select=*&period_label=eq.{per}")}
    fact = {x["supplier_id"]: x for x in sb.get(
        "retro_payments_fact", f"select=*&period_label=eq.{per}")}

    bsup = {b["id"]: b.get("supplier_id") for b in brands}
    bname = {b["id"]: b.get("name") for b in brands}
    r_by_sup, a_by_sup, m_by_sup = {}, {}, {}
    for r in rules:
        r_by_sup.setdefault(r.get("supplier_id") or bsup.get(r.get("supplier_brand_id")), []).append(r)
    for a in aliases:
        a_by_sup.setdefault(a.get("supplier_id"), []).append(a)
    for m in monthly:
        m_by_sup.setdefault(m.get("supplier_id"), []).append(m)

    targets = []
    for s in sups:
        if args.supplier and args.supplier.lower() not in (s.get("name") or "").lower():
            continue
        c, f = calc.get(s["id"]), fact.get(s["id"])
        if not c and not f:
            continue
        cv = float(c["total_retro"]) if c and c.get("total_retro") is not None else None
        fv = float(f["amount_paid"]) if f else None
        if args.all and cv is not None and fv is not None:
            d = fv - cv
            if abs(d) <= TOL_ABS or (cv and abs(d) / cv * 100 <= TOL_PCT):
                continue
        targets.append(s)
    if not targets:
        print("[i] Нечего диагностировать.")
        return

    cli = bq()
    print(f"[i] Период {per} ({d1} — {d2}) | поставщиков: {len(targets)}\n")

    for s in sorted(targets, key=lambda x: x.get("name") or ""):
        sid = s["id"]
        c, f = calc.get(sid), fact.get(sid)
        cv = float(c["total_retro"]) if c and c.get("total_retro") is not None else None
        fv = float(f["amount_paid"]) if f else None
        print("=" * 78)
        print(f"{s.get('name')}   [{per}]")
        print(f"  расчёт: {cv if cv is None else f'{cv:,.2f}'}   "
              f"факт: {fv if fv is None else f'{fv:,.2f}'}", end="")
        delta = (fv - cv) if (cv is not None and fv is not None) else None
        if delta is not None:
            print(f"   дельта: {delta:+,.2f}"
                  f"{f' ({delta/cv*100:+.1f}%)' if cv else ''}")
        else:
            print()
        if c:
            print(f"  база расчёта: приход {float(c.get('total_purchase') or 0):,.2f} | "
                  f"возвраты {float(c.get('total_returns') or 0):,.2f} | "
                  f"база {float(c.get('total_base') or 0):,.2f} | статус {c.get('status')}")

        al = a_by_sup.get(sid, [])
        inc_al = [a["alias_name"] for a in al if (a.get("alias_type") or "") != "excluded"]
        act = active(r_by_sup.get(sid, []), per)
        print(f"  правил активно: {len(act)} | алиасов: {len(inc_al)}")
        for r in act:
            print(f"    · {bname.get(r.get('supplier_brand_id'), '—')}: "
                  f"{r.get('retro_min')}–{r.get('retro_max')}% | {r.get('retro_base_type')} | "
                  f"{r.get('returns_policy')}"
                  + (f" | порог {r.get('min_purchase_threshold')}" if r.get("min_purchase_threshold") else "")
                  + (" | НДС−20%" if r.get("subtract_vat_from_retro") else ""))

        hyp = []

        if not act:
            hyp.append(("НЕТ АКТИВНОГО ПРАВИЛА", "правило не покрывает период — расчёт нулевой"))

        mb = sum(float(m.get("amount") or 0) for m in m_by_sup.get(sid, [])
                 if (m.get("status") or "active") == "active")
        if mb and delta is not None and abs(delta - mb) <= max(TOL_ABS, mb * 0.02):
            hyp.append(("ФИКС-БОНУС НЕ УЧТЁН", f"{mb:,.2f} ≈ дельта {delta:+,.2f}"))
        elif mb:
            hyp.append(("есть фикс-бонус", f"{mb:,.2f}/мес — проверить, входит ли в total_retro"))

        if cv and delta is not None:
            for label, k in (("НДС ×0.80", 0.20), ("НДС ÷1.2", 1 - 1 / 1.2)):
                if abs(abs(delta) - cv * k) <= max(TOL_ABS, cv * k * 0.03):
                    hyp.append((f"ПОХОЖЕ НА {label}", f"{cv*k:,.2f} ≈ |дельта| {abs(delta):,.2f}"))

        inc, nin = q_sum(cli, "incoming_transactions", inc_al, d1, d2)
        ret, nret = q_sum(cli, "outgoing_to_supplier_transactions", inc_al, d1, d2)
        cut = int(s.get("returns_cutoff_day") or 0)
        ret2 = ret
        if cut:
            ret2, _ = q_sum(cli, "outgoing_to_supplier_transactions", inc_al, d1,
                            (d2 + timedelta(days=cut + 1)))
        print(f"  BigQuery: приход {inc:,.2f} ({nin} строк) | возвраты {ret:,.2f} ({nret})"
              + (f" | с окном +{cut}дн: {ret2:,.2f}" if cut else ""))

        if c and abs(inc - float(c.get("total_purchase") or 0)) > max(TOL_ABS, inc * 0.01):
            hyp.append(("ПРИХОД НЕ СХОДИТСЯ С РАСЧЁТОМ",
                        f"BQ {inc:,.2f} vs расчёт {float(c.get('total_purchase') or 0):,.2f}"))
        if cut and abs(ret2 - ret) > TOL_ABS:
            hyp.append(("ОКНО ВОЗВРАТОВ", f"в окне +{cut}дн возвраты больше на {ret2-ret:,.2f}"))

        base = inc - ret
        if fv is not None and base > 0:
            print(f"  подразумеваемая ставка по факту: {fv/base*100:.2f}% "
                  f"(база приход−возврат = {base:,.2f})")
            for r in act:
                rm = r.get("retro_min")
                if rm and base:
                    exp = base * float(rm) / 100
                    if abs(fv - exp) <= max(TOL_ABS, exp * 0.02):
                        hyp.append(("ФАКТ = СТАВКА × (ПРИХОД−ВОЗВРАТ)",
                                    f"{rm}% × {base:,.2f} = {exp:,.2f}"))

        if any((r.get("retro_base_type") or "") == "payments" for r in act):
            pay = sb.get("supplier_payments",
                         f"select=amount&supplier_id=eq.{sid}&period_label=eq.{per}")
            ps = sum(float(x["amount"]) for x in pay)
            print(f"  оплаты поставщику за период: {ps:,.2f} ({len(pay)} шт)")
            for r in act:
                rm = r.get("retro_min")
                if rm and ps:
                    exp = ps * float(rm) / 100
                    if fv is not None and abs(fv - exp) <= max(TOL_ABS, exp * 0.02):
                        hyp.append(("ФАКТ = СТАВКА × ОПЛАТЫ", f"{rm}% × {ps:,.2f} = {exp:,.2f}"))

        thr = [float(r["min_purchase_threshold"]) for r in act if r.get("min_purchase_threshold")]
        if thr and inc < max(thr):
            hyp.append(("ПОРОГ НЕ ВЫПОЛНЕН", f"приход {inc:,.2f} < порога {max(thr):,.2f}"))

        words = {w for w in re.findall(r"[А-Яа-яЇїІіЄєҐґA-Za-z]{4,}", s.get("name") or "")}
        known = {a.lower() for a in inc_al}
        found = [x for x in q_suppliers_like(cli, sorted(words)[:3], d1, d2)
                 if x[0].lower() not in known]
        if found:
            hyp.append(("АЛИАСЫ НЕ ПОКРЫТЫ",
                        "; ".join(f"«{n}» {t:,.0f}" for n, t, _ in found[:4])))

        if f and f.get("covers_periods"):
            hyp.append(("ПЛАТЁЖ ЗА НЕСКОЛЬКО ПЕРИОДОВ", ", ".join(f["covers_periods"])))
        if f and f.get("additional_payments"):
            e = ", ".join(f"{x.get('amount'):,.0f} {x.get('label')}"
                          for x in f["additional_payments"])
            hyp.append(("ЕСТЬ НЕФАКТОРНЫЕ КОМПОНЕНТЫ", e))
        if f and f.get("needs_manual"):
            hyp.append(("помечен как ручной", f.get("notes") or ""))

        print("\n  ГИПОТЕЗЫ:")
        if hyp:
            for k, v in hyp:
                print(f"    [{k}] {v}")
        else:
            print("    — автоматических объяснений нет, нужен ручной разбор")
        print()


if __name__ == "__main__":
    main()

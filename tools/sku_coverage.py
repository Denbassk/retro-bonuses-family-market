#!/usr/bin/env python3
"""
sku_coverage.py - позиционный отчёт: какие SKU поставщика попали в ретро, какие нет и сколько это стоит.

Источник истины «посчитано» - retro_calculation_sku_details (что реально учёл расчёт), а не пересчёт правил.
Приход и возвраты по SKU - diagnose_retro.Data.load_bq (тот же запрос, что у диагностики, без новых).
Классификация статусов повторяет diagnose_retro.h_sku: вне правил / исключён / сырьё / двойной счёт / дрейф.
Флаги месяца (недогруз, задвоено) читаются из готового output\\data_health_2026.csv - BigQuery не трогаем.

«Недосчитано» = база x ставка правила через apply_vat того же правила (иначе оценка завышена на 20%).
Для баз не от приходов (payments, per_portion_sold, coverage_per_store, income_source=torgsoft_ref)
«недосчитано» НЕ считается: приход по SKU там не база.

Запуск (из корня):
  python tools\\sku_coverage.py --supplier "Юрія" --month 2026-07 --dry-run
  python tools\\sku_coverage.py --from 2026-01 --to 2026-08        -> output\\sku_coverage_2026.csv
"""
import sys, csv, argparse
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import sb
from paths import OUT
import bq_docs
from diagnose_retro import Data, rule_active, pair_context, in_chunks, f2, bounds
from calculate_retro import apply_vat
from reconcile_facts import months, last_closed

NO_INCOME_BASE = ("payments", "per_portion_sold", "coverage_per_store")
COLUMNS = ["месяц", "поставщик", "имя в BigQuery", "бренд", "баркод", "наименование", "количество",
           "приход", "возвраты", "база", "статус покрытия", "правило", "период правила", "ставка %",
           "ретро посчитано", "недосчитано", "приход в расчёте", "дрейф", "флаги месяца"]


def scope(supplier=None, per_from="2026-01", per_to=None):
    """-> (поставщики в ретро, месяцы, имена брендов, имена поставщиков). Оболонь исключена (EXCLUDED_OWNER)."""
    sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
    brands = {b["id"]: b for b in sb.get("supplier_brands", "select=id,name,supplier_id")}
    sids = {brands[r["supplier_brand_id"]]["supplier_id"]
            for r in sb.get("retro_rules", "status=eq.active&select=supplier_brand_id")
            if r.get("supplier_brand_id") in brands}
    sids = {s for s in sids if s in sup and "оболон" not in sup[s].lower()}
    if supplier:
        sids = {s for s in sids if sup[s] == supplier}
        if not sids:
            sys.exit(f"поставщик «{supplier}» не найден среди ретро-поставщиков (нужно EXACT-имя)")
    return sids, months(per_from, per_to or last_closed()), brands, sup


def month_flags(aliases, per):
    """Флаги месяца из готового отчёта полноты базы: недогруз / задвоено по алиасам этого поставщика."""
    p = OUT / "data_health_2026.csv"
    if not p.exists():
        return ""
    out = set()
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            if r["месяц"] == per and r["поставщик BQ"] in aliases and r["тип"] in ("missing", "double"):
                out.add("недогруз" if r["тип"] == "missing" else "задвоено")
    return ", ".join(sorted(out))


def rep_rule(D, sid, per, ctx):
    """Представительное правило поставщика за месяц: по нему считается «недосчитано» у непокрытых SKU."""
    ship = sorted(ctx["ship"], key=lambda d: -f2(d["amount_net"]))
    if ship and ship[0]["_rule"]:
        return ship[0]["_rule"]
    act = [r for r in D.rules_by_sup[sid] if rule_active(r, per)]
    act.sort(key=lambda r: -f2(r.get("retro_min")))
    return act[0] if act else None


def supplier_month(D, sid, per, ctx, sku_calc, brands, sup):
    """Строки отчёта по одному поставщику-месяцу. Логика статусов - как в diagnose_retro.h_sku."""
    rows = []
    names_in = D.aliases[sid]["in"]
    inc = D.bq_barcodes("inc", sid, per)
    raw = D.bq_barcodes("raw", sid, per)
    ret = D.bq_barcodes("ret", sid, per)
    act = [r for r in D.rules_by_sup[sid] if rule_active(r, per)]
    excluded = {str(b) for r in act for b in (r.get("excluded_sku_barcodes") or [])}
    a_day, b_day = bounds(per)
    # правило может быть неактивно по двум разным причинам, и это разные выводы:
    notyet = {str(b): r for r in D.rules_by_sup[sid] if not rule_active(r, per)
              and r.get("valid_from") and str(r["valid_from"]) > str(b_day) for b in (r.get("sku_barcodes") or [])}
    expired = {str(b): r for r in D.rules_by_sup[sid] if not rule_active(r, per)
               and r.get("valid_to") and str(r["valid_to"]) < str(a_day) for b in (r.get("sku_barcodes") or [])}
    no_income = act and all((r.get("retro_base_type") in NO_INCOME_BASE)
                            or (r.get("income_source") == "torgsoft_ref") for r in act)
    subtract = {r["id"] for r in act if (r.get("returns_policy") or "") == "subtract"}
    rep = rep_rule(D, sid, per, ctx)
    flags = month_flags(names_in, per)
    calc_status = (ctx["calcs"][0].get("status") if ctx["calcs"] else "") or ""
    if per <= "2026-06":
        flags = ", ".join(x for x in (flags, "TRUTH_UNTIL: не пересчитывать") if x)
    if calc_status in ("approved", "paid"):
        flags = ", ".join(x for x in (flags, f"расчёт {calc_status}") if x)

    for bc in sorted(set(inc) | set(raw) | set(ret) | {k[2] for k in sku_calc if k[0] == sid and k[1] == per}):
        c = sku_calc.get((sid, per, bc))
        owners = D.sku_by[per].get(bc, [])
        mine = [x for x in owners if x[0] == sid]
        others = sorted({sup.get(x[0], "?") for x in owners if x[0] != sid})
        det = ctx["det_by_id"].get(mine[0][1]) if mine else None
        rule = (det or {}).get("_rule") or {}
        amount = inc.get(bc, 0.0) + raw.get(bc, 0.0)
        returns = ret.get(bc, 0.0)
        base = amount - (returns if (rule.get("id") in subtract or (not mine and rep and rep.get("id") in subtract)) else 0.0)

        if mine:
            status = "в правиле" if len(mine) == 1 else f"в двух правилах ({len(mine)})"
        elif others:
            status = "покрыт правилом другого поставщика: " + ", ".join(others)
        elif bc in raw:
            status = "сырьё"
        elif bc in excluded:
            status = "исключён правилом"
        elif bc in notyet:
            status = f"правило ещё не действует с {notyet[bc].get('valid_from')}"
        elif bc in expired:
            status = f"правило истекло {expired[bc].get('valid_to')}"
        elif not act:
            status = "нет активных правил в месяце"
        else:
            status = "вне правил"
        if no_income:
            status += "; база не от приходов"

        rate = f2(rule.get("retro_min")) if mine else (f2(rep.get("retro_min")) if rep else 0.0)
        under = ""   # у покрытых ретро уже посчитано; у баз не от приходов приход - не база
        # у «чужих» SKU (общий алиас, БІР Кег/Славутич) ретро уже посчитано у другого поставщика - не считать
        # «ещё не действует» - не недосчёт: договор в этом месяце не работал
        if not mine and not others and base > 0 and rate and not no_income and not status.startswith("правило ещё не"):
            under = float(apply_vat(Decimal(str(round(base, 2))) * Decimal(str(rate)) / Decimal("100"), rep or {}))
        rows.append([
            per, sup.get(sid, "?"), ", ".join(sorted(names_in)),
            brands.get(rule.get("supplier_brand_id"), {}).get("name", ""), bc,
            (c or {}).get("product_name") or D.bq.get("names", {}).get(bc) or NAMES.get(bc, ""),
            (c or {}).get("quantity", ""), round(amount, 2), round(returns, 2), round(base, 2), status,
            (rule.get("notes") or "")[:60] if mine else ((rep or {}).get("notes") or "")[:60],
            f"{rule.get('valid_from') or ''}..{rule.get('valid_to') or ''}" if mine else "",
            rate or "", round(f2((c or {}).get("retro_amount")), 2), under,
            round(f2((c or {}).get("amount_purchased")), 2),
            round(amount - f2((c or {}).get("amount_purchased")), 2) if c else "", flags])
    return rows


NAMES = {}              # баркод -> наименование из SKU-разбивки расчётов
DETAILS_WITH_SKU = set()  # id строк расчёта, у которых есть SKU-разбивка (остальные - оплаты, фикс-бонус, доплаты)


def control(D, rows, sids, pers, sku_calc, sup):
    """Контроль по парам: отчёт против SKU-разбивки и против total_retro; «недосчитано» с флагами и без."""
    rep = defaultdict(float)
    for r in rows:
        rep[(r[1], r[0])] += r[14]
    bad = []
    for s in sids:
        for p in pers:
            ctrl = round(sum(v["retro_amount"] for k, v in sku_calc.items() if k[0] == s and k[1] == p), 2)
            d = round(rep.get((sup.get(s), p), 0.0) - ctrl, 2)
            if abs(d) >= 0.01:
                bad.append((sup.get(s), p, d))
    print("\n[1] отчёт против retro_calculation_sku_details: " +
          ("расхождений нет по всем парам" if not bad else f"расхождения в {len(bad)} парах"))
    for n, p, d in sorted(bad, key=lambda x: -abs(x[2]))[:15]:
        print(f"    {p} {n[:34]:<35} {d:+,.2f}")

    print("\n[2] total_retro минус строки без SKU-разбивки против суммы SKU (порог 100 ₴):")
    hits = 0
    for s in sids:
        for p in pers:
            c = D.calc.get((s, p))
            if not c:
                continue
            dets = D.details.get(c["id"], [])
            no_sku = sum(f2(d["retro_amount"]) for d in dets if d["id"] not in DETAILS_WITH_SKU)
            sku = round(sum(v["retro_amount"] for k, v in sku_calc.items() if k[0] == s and k[1] == p), 2)
            diff = round(f2(c["total_retro"]) - no_sku - sku, 2)
            if abs(diff) > 100:
                hits += 1
                # ретро в SKU-разбивке считается ДО вычета возвратов, возвраты вычитаются на уровне строки расчёта
                ret_eff = sum(f2(d["amount_returned"]) * d.get("_rate", 0) for d in dets)
                why = ("возвраты вычтены на уровне строки расчёта, в SKU-разбивке их нет"
                       if ret_eff and abs(abs(diff) - ret_eff) <= max(1.0, 0.05 * ret_eff)
                       else "дрейф округления при распределении возвратов" if abs(diff) < 0.01 * (sku or 1)
                       else "строка расчёта без SKU-разбивки (проверить detail)")
                print(f"    {p} {sup.get(s, '?')[:34]:<35} total {f2(c['total_retro']):>12,.2f} - без SKU {no_sku:>11,.2f}"
                      f" - SKU {sku:>12,.2f} = {diff:>+10,.2f}  {why}")
    if not hits:
        print("    разниц больше 100 ₴ нет")

    blocks = [("январь-июнь (TRUTH_UNTIL, справочно)", [r for r in rows if r[0] <= "2026-06"]),
              ("июль-август (рабочие месяцы)", [r for r in rows if r[0] > "2026-06"])]
    for label, rs in blocks:
        if not rs:
            continue
        flags = {(r[1], r[0]): bool("недогруз" in r[18] or "задвоено" in r[18]) for r in rs}
        grp = defaultdict(lambda: defaultdict(float))
        for r in rs:
            if r[15]:
                grp["с флагами" if flags[(r[1], r[0])] else "без флагов"][r[10].split(";")[0]] += r[15]
        print(f"\n[3-4] {label}: строк {len(rs)}, пар {len(flags)}")
        for g in ("без флагов", "с флагами"):
            n = sum(1 for v in flags.values() if v == (g == "с флагами"))
            print(f"    {g} ({n} пар): итого {sum(grp[g].values()):,.0f} ₴")
            for st in ("вне правил", "сырьё", "исключён правилом"):
                print(f"        {st:<24}{grp[g].get(st, 0.0):>12,.0f}")
            other = {k: v for k, v in grp[g].items() if k not in ("вне правил", "сырьё", "исключён правилом")}
            for st, v in sorted(other.items(), key=lambda x: -x[1]):
                print(f"        {st[:24]:<24}{v:>12,.0f}")

    work = [r for r in rows if r[0] > "2026-06"]
    wf = {(r[1], r[0]): bool("недогруз" in r[18] or "задвоено" in r[18]) for r in work}
    top = sorted([r for r in work if r[15] and not wf[(r[1], r[0])]], key=lambda r: -r[15])[:20]
    print(f"\n[топ-20] июль-август, только пары без флагов данных:")
    print(f"    {'месяц':<8}{'поставщик':<30}{'баркод':<15}{'наименование':<36}{'статус':<20}{'недосчитано':>12}")
    for r in top:
        print(f"    {r[0]:<8}{r[1][:29]:<30}{str(r[4]):<15}{(r[5] or '')[:34]:<36}{r[10][:19]:<20}{r[15]:>12,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--supplier", help="точное имя поставщика (EXACT)")
    ap.add_argument("--month", help="один месяц, напр. 2026-07")
    ap.add_argument("--from", dest="per_from", default="2026-01")
    ap.add_argument("--to", dest="per_to", default=None)
    ap.add_argument("--dry-run", action="store_true", help="посчитать и показать итоги, CSV не писать")
    ap.add_argument("--control", action="store_true", help="контроль по парам: сверка сумм и «недосчитано» по флагам")
    a = ap.parse_args()
    sids, pers, brands, sup = scope(a.supplier, a.month or a.per_from, a.month or a.per_to)
    targets = [{"members": (s,), "per": p} for s in sorted(sids) for p in pers]
    print(f"[i] поставщиков {len(sids)}, месяцев {len(pers)} ({pers[0]}..{pers[-1]})")
    D = Data([], targets, docs=False)

    cids = [D.calc[(s, p)]["id"] for s in sids for p in pers if (s, p) in D.calc]
    by_calc = {D.calc[(s, p)]["id"]: (s, p) for s in sids for p in pers if (s, p) in D.calc}
    sku_calc = {}
    for r in in_chunks("retro_calculation_sku_details", "calculation_id", cids,
                       "calculation_id,detail_id,barcode,product_name,quantity,amount_purchased,"
                       "amount_returned,applied_percent,retro_amount"):
        c = by_calc.get(r["calculation_id"])
        if not c:
            continue
        k = (c[0], c[1], str(r["barcode"]))
        cur = sku_calc.setdefault(k, {"product_name": r.get("product_name") or "", "quantity": 0.0,
                                      "amount_purchased": 0.0, "amount_returned": 0.0, "retro_amount": 0.0})
        for f in ("quantity", "amount_purchased", "amount_returned", "retro_amount"):
            cur[f] = round(cur[f] + f2(r.get(f)), 2)
        NAMES.setdefault(str(r["barcode"]), r.get("product_name") or "")
        DETAILS_WITH_SKU.add(r["detail_id"])

    rows = []
    for s in sorted(sids, key=lambda x: sup.get(x, "")):
        for p in pers:
            ctx = pair_context(D, {"members": (s,), "per": p})
            if not ctx["calcs"] and not D.bq_barcodes("inc", s, p):
                continue
            rows += supplier_month(D, s, p, ctx, sku_calc, brands, sup)

    by = defaultdict(lambda: [0, 0.0, 0.0, 0.0])   # статус -> [строк, приход, ретро, недосчитано]
    for r in rows:
        st = r[10].split(":")[0]
        by[st][0] += 1
        by[st][1] += r[7]
        by[st][2] += r[14]
        by[st][3] += r[15] or 0
    print(f"\n[i] строк: {len(rows)}")
    print(f"    {'статус покрытия':<42}{'строк':>7}{'приход':>14}{'ретро':>12}{'недосчитано':>14}")
    for st, v in sorted(by.items(), key=lambda x: -x[1][3]):
        print(f"    {st[:42]:<42}{v[0]:>7}{v[1]:>14,.0f}{v[2]:>12,.0f}{v[3]:>14,.0f}")
    pairs = {(r[1], r[0]) for r in rows}
    flagged = {(r[1], r[0]) for r in rows if "недогруз" in r[18] or "задвоено" in r[18]}
    print(f"\n[i] пар поставщик-месяц: {len(pairs)}, из них с флагами данных (задвоено/недогруз): {len(flagged)}"
          f" - «недосчитано» по ним читать с поправкой")
    top = sorted([r for r in rows if r[15]], key=lambda r: -r[15])[:10]
    if top:
        print(f"\n[i] Топ-10 по «недосчитано»:")
        print(f"    {'месяц':<8}{'поставщик':<28}{'баркод':<15}{'наименование':<40}{'статус':<26}{'недосчитано':>12}")
        for r in top:
            print(f"    {r[0]:<8}{r[1][:27]:<28}{str(r[4]):<15}{(r[5] or '')[:38]:<40}{r[10][:25]:<26}{r[15]:>12,.0f}")
    if a.control:
        control(D, rows, sids, pers, sku_calc, sup)
    done = sum(r[14] for r in rows)
    ctrl = sum(v["retro_amount"] for k, v in sku_calc.items() if k[0] in sids and k[1] in pers)
    calc_total = sum(f2(D.calc[(s, p)]["total_retro"]) for s in sids for p in pers if (s, p) in D.calc)
    print(f"\n[i] ретро посчитано в отчёте {done:,.2f} | retro_calculation_sku_details {ctrl:,.2f} | "
          f"расхождение {done - ctrl:+,.2f}")
    print(f"    total_retro расчёта {calc_total:,.2f} (разница с SKU-разбивкой - строки без SKU: доплаты, фикс-бонус)")

    if a.dry_run:
        print("\n[i] Пробный прогон, CSV не записан")
        return
    dst = OUT / "sku_coverage_2026.csv"
    with dst.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(COLUMNS)
        w.writerows(sorted(rows, key=lambda r: (r[0], r[1], -(r[15] or 0), -r[7])))
    print(f"\n[>] {dst.relative_to(OUT.parent)}")


if __name__ == "__main__":
    main()

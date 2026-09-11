#!/usr/bin/env python3
"""
import_facts_to_db.py - ЭТАП 3: запись фактов оплат ретро в Supabase.

Принцип: админка - источник истины для уже внесённого, Excel - для нового.
По умолчанию пишутся ТОЛЬКО ячейки, которых нет в retro_payments_fact.
Конфликты (суммы расходятся) показываются, но не перезаписываются - для них нужен
--with-conflicts, и прежнее значение сохраняется в amount_previous.

Не пишутся: is_ignored, составные (split_targets).
Подозрительные даты не записываются, запись помечается needs_manual.

Запуск:
  python import_facts_to_db.py "Ретро Бонусы.xlsx" --sheet 2026
  python import_facts_to_db.py "Ретро Бонусы.xlsx" --sheet 2026 --apply
  python import_facts_to_db.py "Ретро Бонусы.xlsx" --sheet 2026 --with-conflicts --apply
"""
import re, argparse, getpass
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, column_index_from_string

import sb
from import_retro_facts import norm_name, parse_amount, classify_header, STOP_NAMES
from parse_payment_notes import parse_note, AUTHOR_RE, DATE_RE, EARMARK_RE
from parse_note_components import components, month_refs, ADJ_WORDS
from dump_cell_comments import comments_from_zip

NON_RETRO = ("дмп", "кубы", "кубі", "куби", "стойки", "стойка", "сгущёнка", "сгущенка")
RANGE_RE = re.compile(r"\b([а-яіїєґ]{3,})\s*[-—]\s*([а-яіїєґ]{3,})\b", re.IGNORECASE)
SRC = "excel_retro_sheet"
EPS = 1.0  # Excel округлён до гривны: разница < 1 ₴ = совпадение


def note_body(text):
    b = AUTHOR_RE.sub("", re.sub(r"\s+", " ", text or "").strip())
    b = EARMARK_RE.sub(" ", b)
    return DATE_RE.sub(" ", b).strip(" .,-—")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--sheet", default="2026")
    ap.add_argument("--header-row", type=int, default=1)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--with-conflicts", action="store_true",
                    help="перезаписать суммы, уже внесённые в админке")
    ap.add_argument("--skip-zero", action="store_true", help="не импортировать нулевые ячейки")
    args = ap.parse_args()

    path = Path(args.xlsx)
    year = int(re.search(r"(20\d{2})", args.sheet).group(1))
    ws = load_workbook(path, data_only=True)[args.sheet]
    who = getpass.getuser()
    now = datetime.now(timezone.utc).isoformat()

    cols = {}
    for c in range(2, ws.max_column + 1):
        cl = classify_header(ws.cell(row=args.header_row, column=c).value, year)
        if cl and cl[0] != "skip":
            cols[c] = cl

    cmts = {}
    for r in range(args.header_row + 1, ws.max_row + 1):
        for c in cols:
            cm = ws.cell(row=r, column=c).comment
            if cm and (cm.text or "").strip():
                cmts[(r, c)] = cm.text
    if not cmts:
        for ref, txt in comments_from_zip(path, args.sheet).items():
            m = re.match(r"([A-Z]+)(\d+)", ref)
            if m:
                cmts[(int(m.group(2)), column_index_from_string(m.group(1)))] = txt

    nmap = {m["excel_name_normalized"]: m for m in sb.get(
        "retro_fact_name_map",
        "select=excel_name_normalized,supplier_id,is_ignored,split_targets,needs_manual")}
    sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
    existing = {(x["supplier_id"], x["period_label"]): float(x["amount_paid"])
                for x in sb.get("retro_payments_fact",
                                "select=supplier_id,period_label,amount_paid")}

    new, conflict, same, openings = [], [], 0, []
    skipped, manual, unmapped, zeros = [], [], set(), 0

    for r in range(args.header_row + 1, ws.max_row + 1):
        raw = ws.cell(row=r, column=1).value
        if raw is None or not str(raw).strip():
            continue
        raw = str(raw).strip()
        nm = norm_name(raw)
        if nm in STOP_NAMES:
            continue

        mp = nmap.get(nm)
        if not mp:
            unmapped.add(raw)
            continue
        if mp.get("is_ignored"):
            skipped.append(raw)
            continue
        if mp.get("split_targets"):
            manual.append((raw, "составной платёж"))
            continue
        sid = mp.get("supplier_id")
        if not sid:
            unmapped.add(raw)
            continue

        for c, (kind, label) in cols.items():
            amt = parse_amount(ws.cell(row=r, column=c).value)
            if amt is None:
                continue
            if amt == 0 and args.skip_zero:
                zeros += 1
                continue
            cell = f"{get_column_letter(c)}{r}"
            txt = cmts.get((r, c), "")
            p = parse_note(txt, label if kind == "month" else None, fallback_year=year)
            body = note_body(txt)

            if kind == "one_off":
                openings.append({
                    "supplier_id": sid, "store_label": label, "amount": amt, "year": year,
                    "payment_date": p["payment_date"].isoformat() if p["payment_date"] else None,
                    "source_file": path.name, "imported_at": now})
                continue

            flags = []
            if p["date_warning"]:
                flags.append(p["date_warning"])
            if mp.get("needs_manual"):
                flags.append("поставщик помечен как ручной")

            extra = [{"amount": e["amount"], "label": e["label"], "source": "note"}
                     for e in p["earmarks"]]
            covers, own = [], int(label.split("-")[1])
            if body:
                comps = [x for x in components(body) if x["is_money"]]
                for x in comps:
                    if any(x["label"].startswith(k) for k in NON_RETRO):
                        extra.append({"amount": x["amount"], "label": x["label"], "source": "note"})
                refs = set(month_refs(body))
                rng = RANGE_RE.search(body)
                if rng:
                    a, b = month_refs(rng.group(1)), month_refs(rng.group(2))
                    if a and b:
                        lo, hi = min(a), max(b)
                        if lo < hi:
                            refs |= set(range(lo, hi + 1))
                other = sorted(refs - {own})
                if other and (any(w in body.lower() for w in ADJ_WORDS) or rng):
                    covers = [f"{year}-{m:02d}" for m in other]
                if len(comps) >= 2 and abs(sum(x["amount"] for x in comps) - amt) > 5:
                    flags.append(f"состав примечания != суммы ячейки")

            rec = {"supplier_id": sid, "period_label": label, "amount_paid": amt,
                   "payment_date": (p["payment_date"].isoformat()
                                    if p["payment_date"] and not p["date_warning"] else None),
                   "notes": txt or None, "source_file": path.name, "import_source": SRC,
                   "imported_at": now, "needs_manual": bool(flags), "amount_previous": None,
                   "covers_periods": covers or None, "additional_payments": extra}

            prev = existing.get((sid, label))
            if prev is None:
                new.append((cell, raw, rec, flags))
            elif abs(prev - amt) < EPS:
                same += 1
            else:
                rec["amount_previous"] = prev
                conflict.append((cell, raw, rec, flags))

    print(f"[i] Новых к записи: {len(new)} | совпадает: {same} | конфликтов: {len(conflict)}")
    print(f"    разовых бонусов: {len(openings)} | ignore: {len(skipped)} | "
          f"составных: {len(manual)} | без маппинга: {len(unmapped)}"
          + (f" | нулей пропущено: {zeros}" if args.skip_zero else ""))

    if unmapped:
        print("\n[!] Нет в retro_fact_name_map:")
        for x in sorted(unmapped):
            print(f"    {x}")

    byp = defaultdict(list)
    for cell, raw, rec, fl in new:
        byp[rec["period_label"]].append((cell, raw, rec))
    print("\n[i] Новые записи по периодам:")
    for per in sorted(byp):
        tot = sum(x[2]["amount_paid"] for x in byp[per])
        print(f"    {per}: {len(byp[per]):>2} шт, сумма {tot:>12,.0f}")
        for cell, raw, rec in sorted(byp[per], key=lambda x: sup.get(x[2]["supplier_id"], "")):
            print(f"        {cell:<6} {raw[:30]:<30} -> {sup.get(rec['supplier_id'], '?')[:34]:<34}"
                  f" {rec['amount_paid']:>10,.0f}  {rec['payment_date'] or ''}")

    if conflict:
        print(f"\n[!] Конфликты — НЕ пишутся без --with-conflicts ({len(conflict)}):")
        agg = defaultdict(float)
        for cell, raw, rec, fl in conflict:
            agg[rec["supplier_id"]] += rec["amount_paid"] - rec["amount_previous"]
        for cell, raw, rec, fl in sorted(conflict, key=lambda x: x[2]["period_label"]):
            d = rec["amount_paid"] - rec["amount_previous"]
            tag = "перераспределение?" if abs(agg[rec["supplier_id"]]) < 0.5 else "РАСХОЖДЕНИЕ"
            print(f"    {cell:<6} {raw[:24]:<24} {rec['period_label']}  "
                  f"{rec['amount_previous']:>10,.0f} -> {rec['amount_paid']:>10,.0f} "
                  f"({d:>+9,.0f})  {tag}")

    flagged = [x for x in new if x[3]]
    if flagged:
        print(f"\n[~] Помечены needs_manual ({len(flagged)}):")
        for cell, raw, rec, fl in flagged:
            print(f"    {cell:<6} {raw[:24]:<24} {rec['period_label']}  {'; '.join(fl)}")

    cov = [x for x in new if x[2]["covers_periods"]]
    if cov:
        print(f"\n[i] Платежи за несколько периодов ({len(cov)}):")
        for cell, raw, rec, fl in cov:
            print(f"    {cell:<6} {raw[:24]:<24} {rec['period_label']} "
                  f"+ {', '.join(rec['covers_periods'])}")

    ex = [x for x in new if x[2]["additional_payments"]]
    if ex:
        print(f"\n[i] Нефакторные компоненты ({len(ex)}):")
        for cell, raw, rec, fl in ex:
            s = ", ".join(f"{a['amount']:,.0f} {a['label']}" for a in rec["additional_payments"])
            print(f"    {cell:<6} {raw[:24]:<24} {rec['period_label']}  {s}")

    if not args.apply:
        print("\n[i] Пробный прогон. Для записи добавьте --apply")
        return

    batch = [x[2] for x in new]
    if args.with_conflicts:
        batch += [x[2] for x in conflict]
        print(f"\n[!] Режим --with-conflicts: перезаписываю {len(conflict)} записей")
    if batch:
        sb.upsert("retro_payments_fact", batch, on_conflict="supplier_id,period_label")
        print(f"[>] retro_payments_fact: записано {len(batch)}")
    if openings:
        sb.upsert("store_opening_bonuses", openings, on_conflict="supplier_id,store_label,year")
        print(f"[>] store_opening_bonuses: записано {len(openings)}")


if __name__ == "__main__":
    main()

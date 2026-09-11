#!/usr/bin/env python3
"""
parse_payment_notes.py - разбор примечаний к ячейкам факт-таблицы.

Формат: "ASISTEC: 12.03.26" | "ASISTEC: из них 13000 стойки 15.06.26"
Извлекает: дату оплаты, целевые суммы (стойки/куби/акции), остаток текста.
Проверяет правдоподобность года относительно периода.
Колонки разовых бонусов (роган.148 и т.п.) периода не имеют - проверка года пропускается.

Самопроверка:
  python parse_payment_notes.py --selftest
  python parse_payment_notes.py --csv cell_comments_2026.csv
"""
import re, csv, argparse
from datetime import date
from pathlib import Path

AUTHOR_RE = re.compile(r"^\s*[A-ZА-ЯЇІЄҐ][\w\-\.]{1,20}\s*:\s*", re.IGNORECASE)
DATE_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b")
PERIOD_RE = re.compile(r"^(\d{4})-(\d{1,2})$")
EARMARK_RE = re.compile(
    r"(?:из\s+них|в\s+т\.?ч\.?|вкл\.?|из\s+ни[хй])\s*"
    r"(\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*"
    r"([^\d,;]{0,40})", re.IGNORECASE)


def _num(s):
    return float(s.replace("\u00a0", "").replace(" ", "").replace(",", "."))


def _period(period_label):
    """-> (год, месяц) или None, если это не YYYY-MM (разовые колонки)."""
    m = PERIOD_RE.match(str(period_label or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_note(text, period_label=None, fallback_year=None):
    """-> dict(payment_date, date_warning, earmarks, author, rest, raw)"""
    out = {"raw": text or "", "author": None, "payment_date": None,
           "date_warning": None, "earmarks": [], "rest": ""}
    if not text or not str(text).strip():
        return out
    t = re.sub(r"\s+", " ", str(text)).strip()
    per = _period(period_label)

    m = AUTHOR_RE.match(t)
    if m:
        out["author"] = m.group(0).rstrip(": ").strip()
        t = t[m.end():]

    for em in EARMARK_RE.finditer(t):
        amt = _num(em.group(1))
        label = em.group(2).strip(" .,-—") or "не указано"
        out["earmarks"].append({"amount": amt, "label": label})
    t_wo = EARMARK_RE.sub(" ", t)

    default_year = per[0] if per else (fallback_year or date.today().year)
    cands = []
    for d, mth, y in DATE_RE.findall(t_wo):
        d, mth = int(d), int(mth)
        if not (1 <= d <= 31 and 1 <= mth <= 12):
            continue
        if y:
            yy = int(y)
            yy = 2000 + yy if yy < 100 else yy
        else:
            yy = default_year
        try:
            cands.append((date(yy, mth, d), bool(y)))
        except ValueError:
            continue

    if cands:
        dt, _ = cands[-1]
        out["payment_date"] = dt
        if per:
            py, pm = per
            pstart = date(py, pm, 1)
            months = (dt.year - py) * 12 + (dt.month - pm)
            if months < 0 or months > 12:
                fixed = None
                for yy in (py, py + 1):
                    try:
                        c = date(yy, dt.month, dt.day)
                    except ValueError:
                        continue
                    k = (c.year - py) * 12 + (c.month - pm)
                    if 0 <= k <= 12:
                        fixed = c
                        break
                out["date_warning"] = (
                    f"год не бьётся с периодом {period_label}: {dt.isoformat()}"
                    + (f" (похоже на {fixed.isoformat()})" if fixed else ""))
            elif dt < pstart:
                out["date_warning"] = f"оплата раньше начала периода {period_label}"

    rest = DATE_RE.sub(" ", t_wo)
    out["rest"] = re.sub(r"\s+", " ", rest).strip(" .,-—")
    return out


def _selftest():
    cases = [
        ("ASISTEC: 12.03.26", "2026-01"),
        ("ASISTEC: 18.05.24", "2026-04"),
        ("ASISTEC: 13.08.23", "2026-07"),
        ("ASISTEC: из них 13000 стойки 15.06.26", "2026-05"),
        ("ASISTEC: 21.07", "2026-06"),
        ("кег 12000 + бутылка 8000, 14.07.26", "2026-06"),
        ("ASISTEC: 05.03.26", "роган.148"),
    ]
    for txt, per in cases:
        r = parse_note(txt, per, fallback_year=2026)
        print(f"\n  «{txt}»  [{per}]")
        print(f"    дата: {r['payment_date']}  автор: {r['author']}")
        if r["earmarks"]:
            print(f"    целевые: {r['earmarks']}")
        if r["rest"]:
            print(f"    остаток: «{r['rest']}»")
        if r["date_warning"]:
            print(f"    [!] {r['date_warning']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="cell_comments_YYYY.csv из dump_cell_comments.py")
    ap.add_argument("--year", type=int, default=None, help="год для дат без года в разовых колонках")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest or not args.csv:
        _selftest()
        return

    year = args.year or int(re.search(r"(20\d{2})", args.csv).group(1))
    rows = list(csv.DictReader(Path(args.csv).open(encoding="utf-8-sig"), delimiter=";"))
    warn, marks, nodate, notes, oneoff = [], [], [], [], []
    for r in rows:
        p = parse_note(r["comment"], r["period_label"] or None, fallback_year=year)
        if r.get("kind") == "one_off":
            oneoff.append((r, p))
        if p["date_warning"]:
            warn.append((r, p))
        if p["earmarks"]:
            marks.append((r, p))
        if not p["payment_date"]:
            nodate.append(r)
        if p["rest"]:
            notes.append((r, p))

    print(f"[i] Примечаний: {len(rows)} | дат распознано: {len(rows)-len(nodate)} "
          f"| на разовых колонках: {len(oneoff)}")

    print(f"\n[!] Подозрительные даты ({len(warn)}):")
    for r, p in warn:
        print(f"    {r['cell']:<6} {r['supplier_raw'][:30]:<30} {r['period_label']:<14} "
              f"«{r['comment'][:50]}»\n         {p['date_warning']}")

    print(f"\n[i] Целевые суммы внутри платежа ({len(marks)}):")
    for r, p in marks:
        for e in p["earmarks"]:
            print(f"    {r['cell']:<6} {r['supplier_raw'][:30]:<30} {r['period_label']:<14} "
                  f"сумма={r['amount']}  из них {e['amount']:,.0f} — {e['label']}")

    print(f"\n[~] Примечания с текстом помимо даты ({len(notes)}):")
    for r, p in notes[:25]:
        print(f"    {r['cell']:<6} {r['supplier_raw'][:28]:<28} «{p['rest'][:60]}»")
    if len(notes) > 25:
        print(f"    ... ещё {len(notes)-25}")

    if nodate:
        print(f"\n[~] Без даты ({len(nodate)}):")
        for r in nodate[:15]:
            print(f"    {r['cell']:<6} {r['supplier_raw'][:30]:<30} «{r['comment'][:60]}»")


if __name__ == "__main__":
    main()

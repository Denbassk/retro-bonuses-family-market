#!/usr/bin/env python3
"""
parse_note_components.py - разбор состава примечаний.

Находит пары «метка-сумма» (в обоих порядках), ссылки на другие периоды
(доплаты/перерасчёты) и сверяет сумму компонентов с суммой ячейки.

Запуск:
  python parse_note_components.py --csv cell_comments_2026.csv
"""
import re, csv, argparse
from pathlib import Path

from parse_payment_notes import parse_note, AUTHOR_RE, DATE_RE, EARMARK_RE

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "май": 5, "мая": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
    "січ": 1, "лют": 2, "берез": 3, "квіт": 4, "трав": 5, "черв": 6,
    "лип": 7, "серп": 8, "верес": 9, "жовт": 10, "листоп": 11, "груд": 12,
}
ADJ_WORDS = ("доплат", "допл", "перерасч", "перерах", "корректир", "коригув")
NUM = r"\d[\d\s\u00a0]*(?:[.,]\d{1,2})?"
TOKEN_RE = re.compile(rf"({NUM})|([a-zа-яёїієґ%][a-zа-яёїієґ%.\u0027]*)", re.IGNORECASE)


def _num(s):
    return float(s.replace("\u00a0", "").replace(" ", "").replace(",", "."))


def month_refs(text):
    """Месяцы, упомянутые в тексте -> множество номеров."""
    t = text.lower()
    found = set()
    for stem, n in MONTHS.items():
        if re.search(rf"\b{stem}", t):
            found.add(n)
    return found


def components(text):
    """Пары метка-сумма. Порядок «слово число» и «число-слово» оба поддержаны."""
    toks = []
    for m in TOKEN_RE.finditer(text):
        if m.group(1):
            try:
                toks.append(("n", _num(m.group(1)), m.start()))
            except ValueError:
                pass
        else:
            w = m.group(2).strip(".")
            if len(w) > 1 or w == "%":
                toks.append(("w", w, m.start()))
    out, used = [], set()
    for i, (k, v, _) in enumerate(toks):
        if k != "n" or i in used:
            continue
        label = None
        if i + 1 < len(toks) and toks[i + 1][0] == "w":
            label, used = toks[i + 1][1], used | {i + 1}
        elif i > 0 and toks[i - 1][0] == "w" and (i - 1) not in used:
            label, used = toks[i - 1][1], used | {i - 1}
        out.append({"amount": v, "label": label or "?"})
        used.add(i)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--tol", type=float, default=2.0, help="допуск сверки компонентов, грн")
    args = ap.parse_args()

    year = int(re.search(r"(20\d{2})", args.csv).group(1))
    rows = list(csv.DictReader(Path(args.csv).open(encoding="utf-8-sig"), delimiter=";"))

    out, multi, mism, plain = [], [], [], 0
    for r in rows:
        p = parse_note(r["comment"], r["period_label"] or None, fallback_year=year)
        body = AUTHOR_RE.sub("", re.sub(r"\s+", " ", r["comment"]).strip())
        body = EARMARK_RE.sub(" ", body)
        body = DATE_RE.sub(" ", body).strip(" .,-—")

        if not body:
            plain += 1
            continue

        comps = components(body)
        refs = month_refs(body)
        is_adj = any(w in body.lower() for w in ADJ_WORDS)
        cell_amt = float(r["amount"]) if r["amount"] else None
        csum = sum(c["amount"] for c in comps) if comps else None
        delta = (csum - cell_amt) if (csum is not None and cell_amt is not None) else None

        own = None
        m = re.match(r"^(\d{4})-(\d{1,2})$", r["period_label"] or "")
        if m:
            own = int(m.group(2))
        other = sorted(refs - ({own} if own else set()))

        rec = {"cell": r["cell"], "supplier_raw": r["supplier_raw"],
               "period_label": r["period_label"], "cell_amount": cell_amt,
               "components": " + ".join(f"{c['amount']:g} {c['label']}" for c in comps),
               "components_sum": csum, "delta": delta,
               "months_referenced": ",".join(str(x) for x in sorted(refs)) or "",
               "other_periods": ",".join(str(x) for x in other) or "",
               "is_adjustment": is_adj, "note_body": body}
        out.append(rec)

        if other or is_adj:
            multi.append(rec)
        if delta is not None and comps and abs(delta) > args.tol:
            mism.append(rec)

    print(f"[i] Примечаний: {len(rows)} | только дата: {plain} | с составом: {len(out)}")

    print(f"\n[!] Платежи, затрагивающие другие периоды ({len(multi)}):")
    for r in multi:
        print(f"    {r['cell']:<6} {r['supplier_raw'][:26]:<26} {r['period_label']:<10} "
              f"сумма={r['cell_amount']}")
        print(f"           «{r['note_body']}»  -> месяцы: {r['other_periods'] or '-'}"
              f"{'  ДОПЛАТА' if r['is_adjustment'] else ''}")

    ok = [r for r in out if r["delta"] is not None and abs(r["delta"]) <= args.tol]
    print(f"\n[i] Состав сходится с суммой ячейки: {len(ok)}")
    for r in ok[:10]:
        print(f"    {r['cell']:<6} {r['supplier_raw'][:26]:<26} "
              f"{r['cell_amount']:>12,.0f} = {r['components']}")

    print(f"\n[~] Состав НЕ сходится ({len(mism)}):")
    for r in mism:
        print(f"    {r['cell']:<6} {r['supplier_raw'][:26]:<26} ячейка={r['cell_amount']:>11,.0f} "
              f"компоненты={r['components_sum']:>11,.0f}  дельта={r['delta']:>+10,.0f}")
        print(f"           «{r['note_body']}»")

    dst = Path(f"note_components_{year}.csv")
    with dst.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(out)
    print(f"\n[>] {dst}")


if __name__ == "__main__":
    main()

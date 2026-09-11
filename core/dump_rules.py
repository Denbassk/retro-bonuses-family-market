#!/usr/bin/env python3
"""
dump_rules.py - выгрузка правил ретро в читаемый вид.

Собирает retro_rules + supplier_brands + suppliers + supplier_monthly_bonuses
+ supplier_aliases и пишет rules_snapshot.md (для чтения) и rules_snapshot.csv.

Запуск:
  python dump_rules.py
  python dump_rules.py --supplier "Моршин"
"""
import csv, argparse
from pathlib import Path
from paths import OUT
from collections import defaultdict

import sb

SKIP = {"id", "supplier_id", "supplier_brand_id", "created_at", "updated_at"}


def val(v):
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, bool):
        return "да" if v else None
    if isinstance(v, list):
        return f"[{len(v)} шт]" if len(v) > 3 else ", ".join(str(x) for x in v)
    return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--supplier", default=None, help="фильтр по имени поставщика")
    args = ap.parse_args()

    sups = sb.get("suppliers", "select=*")
    brands = sb.get("supplier_brands", "select=*")
    rules = sb.get("retro_rules", "select=*")
    try:
        monthly = sb.get("supplier_monthly_bonuses", "select=*")
    except RuntimeError:
        monthly = []
    try:
        aliases = sb.get("supplier_aliases", "select=*")
    except RuntimeError:
        aliases = []

    print(f"[i] поставщиков {len(sups)} | брендов {len(brands)} | правил {len(rules)} "
          f"| фикс-бонусов {len(monthly)} | алиасов {len(aliases)}")
    if rules:
        print(f"[i] поля retro_rules: {', '.join(rules[0].keys())}")

    sname = {s["id"]: s.get("name", "?") for s in sups}
    bname = {b["id"]: b.get("name", "?") for b in brands}
    bsup = {b["id"]: b.get("supplier_id") for b in brands}

    r_by_sup = defaultdict(list)
    for r in rules:
        sid = r.get("supplier_id") or bsup.get(r.get("supplier_brand_id"))
        r_by_sup[sid].append(r)
    b_by_sup = defaultdict(list)
    for b in brands:
        b_by_sup[b.get("supplier_id")].append(b)
    m_by_sup = defaultdict(list)
    for m in monthly:
        m_by_sup[m.get("supplier_id")].append(m)
    a_by_sup = defaultdict(list)
    for a in aliases:
        a_by_sup[a.get("supplier_id")].append(a)

    sel = [s for s in sups
           if not args.supplier or args.supplier.lower() in (s.get("name") or "").lower()]
    sel = [s for s in sel if r_by_sup.get(s["id"]) or m_by_sup.get(s["id"])]
    sel.sort(key=lambda s: s.get("name") or "")

    lines = ["# Правила ретро — снимок\n"]
    for s in sel:
        sid = s["id"]
        head = f"## {s.get('name')}"
        extra = [f"{k}={val(v)}" for k, v in s.items()
                 if k not in SKIP and k != "name" and val(v) and k not in ("legal_name",)]
        lines.append(head)
        if extra:
            lines.append(f"*{' · '.join(extra)}*")

        al = a_by_sup.get(sid, [])
        if al:
            by_t = defaultdict(list)
            for a in al:
                by_t[a.get("alias_type") or "-"].append(a.get("alias_name") or "?")
            lines.append("\nАлиасы 1С/BQ: " + "; ".join(
                f"**{t}**: {', '.join(v[:6])}" + (f" (+{len(v)-6})" if len(v) > 6 else "")
                for t, v in by_t.items()))

        for r in sorted(r_by_sup.get(sid, []), key=lambda x: str(x.get("valid_from"))):
            br = bname.get(r.get("supplier_brand_id"), "— весь поставщик —")
            parts = []
            for k, v in r.items():
                if k in SKIP:
                    continue
                sv = val(v)
                if sv is not None:
                    parts.append(f"{k}={sv}")
            lines.append(f"\n- **{br}** — " + "; ".join(parts))

        for m in sorted(m_by_sup.get(sid, []), key=lambda x: str(x.get("period_label"))):
            parts = [f"{k}={val(v)}" for k, v in m.items() if k not in SKIP and val(v) is not None]
            lines.append(f"\n- *фикс-бонус* — " + "; ".join(parts))
        lines.append("")

    (OUT / "rules_snapshot.md").write_text("\n".join(lines), encoding="utf-8")

    flat = []
    for r in rules:
        sid = r.get("supplier_id") or bsup.get(r.get("supplier_brand_id"))
        row = {"supplier": sname.get(sid, "?"),
               "brand": bname.get(r.get("supplier_brand_id"), "")}
        row.update({k: v for k, v in r.items() if k not in SKIP})
        flat.append(row)
    if flat:
        keys = sorted({k for x in flat for k in x})
        keys = ["supplier", "brand"] + [k for k in keys if k not in ("supplier", "brand")]
        with open(OUT / "rules_snapshot.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=keys, delimiter=";")
            w.writeheader()
            w.writerows(flat)

    print(f"[>] rules_snapshot.md ({len(sel)} поставщиков), rules_snapshot.csv ({len(flat)} правил)")


if __name__ == "__main__":
    main()

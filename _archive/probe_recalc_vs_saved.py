"""Разовый probe (не-эталон): пересчёт calculate_retro.py --no-save на ТЕКУЩИХ данных BQ
против сохранённого total_retro в retro_calculations. Разница = расчёт устарел после перезаливок
(приходы 01,03-06 перезалиты 17.07, 07 - 11.09, 08 - 07.09; возвраты 01-07 - 17.08)."""
import os, sys, csv
from pathlib import Path
from collections import defaultdict
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str((ROOT) / "core")); os.chdir(ROOT)
import sb

src = ROOT / "_archive" / "recalc_now_2026-01_2026-08.csv"
rows = list(csv.reader(open(src, encoding="utf-8-sig"), delimiter=";"))
head = rows[0]
pers = [h for h in head if len(h) == 7 and h[4] == "-"]
now = defaultdict(float)
for r in rows[1:]:
    if not r or not r[0] or r[0].upper().startswith("ИТОГО"):
        continue
    for p in pers:
        v = r[head.index(p)].replace(",", ".").strip()
        if v:
            now[(r[0].strip(), p)] += float(v)

sups = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
saved, status, manual, cid = defaultdict(float), {}, defaultdict(float), {}
for c in sb.get("retro_calculations", "select=id,supplier_id,period_label,total_retro,status"):
    k = (sups.get(c["supplier_id"], "?"), c["period_label"])
    saved[k] += float(c["total_retro"] or 0)
    status[k] = c["status"]
    cid[c["id"]] = k
# доп. выплаты, внесённые в админке (строки без правила, кроме фикс-бонуса) - пересчёт их НЕ воспроизводит
for d in sb.get("retro_calculation_details", "retro_rule_id=is.null&select=calculation_id,retro_amount,notes"):
    if "фиксированный ежемесячный бонус" not in (d.get("notes") or "").lower() and d["calculation_id"] in cid:
        manual[cid[d["calculation_id"]]] += float(d["retro_amount"] or 0)
for k, v in manual.items():
    saved[k] -= v
print(f"[i] доп. выплат из админки вычтено из сохранённого: {len(manual)} пар на {sum(manual.values()):,.2f}"
      " (пересчёт с сохранением их СОТРЁТ, кроме approved)")

keys = sorted(set(now) | set(saved), key=lambda k: (k[1], k[0]))
diff = [(k, saved.get(k, 0.0), now.get(k, 0.0)) for k in keys if abs(saved.get(k, 0.0) - now.get(k, 0.0)) >= 1]
byp = defaultdict(lambda: [0.0, 0.0, 0.0, 0])
for k in keys:
    s, n = saved.get(k, 0.0), now.get(k, 0.0)
    b = byp[k[1]]; b[0] += s; b[1] += n; b[2] += abs(n - s); b[3] += abs(n - s) >= 1
print(f"{'период':<9}{'сохранено':>14}{'пересчёт сейчас':>17}{'нетто Δ':>12}{'валовая |Δ|':>13}{'пар ≥1₴':>9}")
for p in sorted(byp):
    s, n, g, c = byp[p]
    print(f"{p:<9}{s:>14,.0f}{n:>17,.0f}{n-s:>12,.0f}{g:>13,.0f}{c:>9}")
S = sum(v[0] for v in byp.values()); N = sum(v[1] for v in byp.values()); G = sum(v[2] for v in byp.values())
print(f"{'ИТОГО':<9}{S:>14,.0f}{N:>17,.0f}{N-S:>12,.0f}{G:>13,.0f}{len(diff):>9}")
print(f"\nТоп расхождений (пересчёт - сохранено), статус сохранённого:")
for (nm, p), s, n in sorted(diff, key=lambda x: -abs(x[2] - x[1]))[:40]:
    tag = "  <-- Оболонь, не трогаем" if "оболон" in nm.lower() else ""
    print(f"  {nm[:46]:<47}{p:<9}{s:>12,.2f}{n:>12,.2f}{n-s:>+11,.2f}  {status.get((nm, p), 'нет расчёта')}{tag}")
with open(ROOT / "_archive" / "recalc_vs_saved_2026.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh, delimiter=";"); w.writerow(["supplier", "period", "saved", "recalc_now", "delta", "status"])
    for (nm, p), s, n in diff:
        w.writerow([nm, p, f"{s:.2f}", f"{n:.2f}", f"{n-s:.2f}", status.get((nm, p), "")])

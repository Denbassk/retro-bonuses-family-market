"""Разовый probe к прогону 4: разбор двух групп позиционного отчёта.
1) SKU, попавшие в две строки расчёта (два правила) - оба правила, периоды, ставки, ретро по каждому.
2) SKU истёкших правил - дата окончания, приход после неё, оценка недосчёта.
-> output/probe_sku_two_rules.txt. Ничего не пишет в БД, код проекта не трогает."""
import os, sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core")); sys.path.insert(0, str(ROOT / "tools")); os.chdir(ROOT)
import sb
from diagnose_retro import Data, rule_active, pair_context, in_chunks, f2
from calculate_retro import apply_vat
from reconcile_facts import months
from sku_coverage import scope

PERS = months("2026-01", "2026-08")
sids, pers, brands, sup = scope(None, "2026-01", "2026-08")
targets = [{"members": (s,), "per": p} for s in sorted(sids) for p in PERS]
D = Data([], targets, docs=False)
by_calc = {D.calc[(s, p)]["id"]: (s, p) for s in sids for p in PERS if (s, p) in D.calc}
det_rule = {d["id"]: d for ds in D.details.values() for d in ds}

# ── 1. один баркод в двух строках расчёта ──
agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, ""]))   # (sid,per,bc) -> detail_id -> [приход, ретро, имя]
for r in in_chunks("retro_calculation_sku_details", "calculation_id", list(by_calc),
                   "calculation_id,detail_id,barcode,product_name,amount_purchased,retro_amount"):
    k = by_calc.get(r["calculation_id"])
    if not k:
        continue
    x = agg[(k[0], k[1], str(r["barcode"]))][r["detail_id"]]
    x[0] += f2(r["amount_purchased"])
    x[1] += f2(r["retro_amount"])
    x[2] = r.get("product_name") or x[2]

out = ["[1] Один баркод в двух строках расчёта", ""]
rows = [(k, v) for k, v in agg.items() if len(v) > 1]
out.append(f"строк: {len(rows)}, ретро всего: {sum(x[1] for _, v in rows for x in v.values()):,.2f}")
for (s, per, bc), v in sorted(rows, key=lambda x: -sum(y[1] for y in x[1].values())):
    name = next((x[2] for x in v.values() if x[2]), "")
    out.append(f"\n{per} {sup.get(s, '?')[:34]:<35} {bc} {name[:44]}")
    for did, (amt, retro, _) in sorted(v.items(), key=lambda x: -x[1][1]):
        d = det_rule.get(did, {})
        r = D.rules.get(d.get("retro_rule_id")) or {}
        out.append(f"    правило {(r.get('notes') or '-')[:46]:<48} {r.get('valid_from') or '-'}..{r.get('valid_to') or '-'} "
                   f" {f2(r.get('retro_min')):>5.1f}%  приход {amt:>11,.2f}  ретро {retro:>10,.2f}")


# ── 2. SKU истёкших правил: приход после даты окончания ──
out += ["", "", "[2] SKU истёкших правил: приход в месяце, когда правило уже не действует", ""]
res = []
for s in sids:
    expired = {}
    for r in D.rules_by_sup[s]:
        for b in (r.get("sku_barcodes") or []):
            expired.setdefault(str(b), r)
    if not expired:
        continue
    for per in PERS:
        act = [r for r in D.rules_by_sup[s] if rule_active(r, per)]
        covered = {bc for bc, lst in D.sku_by[per].items() if any(x[0] == s for x in lst)}
        inc = D.bq_barcodes("inc", s, per)
        for bc, rule in expired.items():
            if rule_active(rule, per) or bc in covered or bc in inc is False:
                continue
            amt = inc.get(bc, 0.0)
            if amt <= 0 or any(bc in {str(x) for x in (a.get("sku_barcodes") or [])} for a in act):
                continue
            rate = f2(rule.get("retro_min"))
            under = float(apply_vat(Decimal(str(round(amt, 2))) * Decimal(str(rate)) / Decimal("100"), rule))
            res.append((amt, per, sup.get(s, "?"), (rule.get("notes") or "-")[:40], str(rule.get("valid_to")),
                        rate, under, bc, D.bq.get("names", {}).get(bc, "")))
out.append(f"строк: {len(res)}, приход {sum(x[0] for x in res):,.0f}, оценка недосчёта {sum(x[6] for x in res):,.0f}")
for amt, per, name, rule, vto, rate, under, bc, prod in sorted(res, key=lambda x: -x[0]):
    out.append(f"{per} {name[:30]:<31} {rule[:38]:<40} до {vto} {rate:>5.1f}%  приход {amt:>10,.0f}  недосчёт {under:>9,.0f}  "
               f"{bc} {prod[:34]}")
(ROOT / "output" / "probe_sku_two_rules.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

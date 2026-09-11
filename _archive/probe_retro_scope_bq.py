#!/usr/bin/env python3
"""
probe_retro_scope_bq.py - разовая сверка BQ ТОЛЬКО по ретро-поставщикам (янв-авг 2026).

Метрика, которую раньше не мерили: валовая (по модулю) дельта эталон vs наши
по парам ГРУППА-месяц, где группа = поставщики Supabase, связанные общими алиасами
(Інтрейд Батоша+Деліція, БІР Кег+Славутич считаются одной группой, без задвоения).
В зачёт идут только месяцы, где у группы есть активное правило, зависящее от прихода
(shipment_minus_return, income_source=incoming). Возвраты - только при returns_policy=subtract.
Оценка ретро-ущерба: |дельта| x (ретро по shipment-правилам / весь наш приход группы).

Блоки:
  [0] покрытие и целостность 4 таблиц (даты, строки, дубли line_id / полных строк возвратов)
  [1] ПРИХОДЫ  эталон vs incoming_transactions  - все / ретро-скоуп / вне скоупа
  [2] ВОЗВРАТЫ эталон vs outgoing_to_supplier_transactions - то же
  [3] НЕ-ЭТАЛОН: приход, долитый в BQ ПОСЛЕ сохранения расчёта (loaded_at > created_at)
      -> расчёт устарел и недосчитан на эту сумму
  [4] имена поставщиков BQ без алиаса (кандидаты в незаведённых, НЕ склеивать)

Союз (Оболонь) показывается отдельной строкой и НЕ входит в итоги (ограничение владельца).
Ничего не пишет в БД. CSV: _archive/bq_retro_scope_2026.csv
"""
import os, sys, csv
from pathlib import Path
from collections import defaultdict
from datetime import date, datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str((ROOT) / "core"))
os.chdir(ROOT)
import sb  # noqa: E402  (грузит .env)
from google.cloud import bigquery  # noqa: E402

P = os.environ.get("BQ_PROJECT", "family-market-analytics")
D = os.environ.get("BQ_DATASET", "family_market")
T = lambda t: f"`{P}.{D}.{t}`"
cli = bigquery.Client(project=P)
PER_FROM, PER_TO = "2026-01", "2026-08"
D_FROM, D_TO = "2026-01-01", "2026-09-01"
MIN_ABS, MIN_PCT = 1000.0, 0.005


def q(sql):
    return [dict(r) for r in cli.query(sql)]


def f(x):
    return float(x or 0)


def is_obolon(name):
    return "оболон" in (name or "").lower()


def parse_ts(v):
    import re
    v = v.replace("Z", "+00:00")
    m = re.match(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:\.\d+)?(.*)$", v)
    ts = datetime.fromisoformat(m.group(1) + (m.group(2) or ""))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def month_bounds(per):
    y, m = int(per[:4]), int(per[5:7])
    return date(y, m, 1), (date(y + (m == 12), m % 12 + 1, 1))


# ─── Supabase: справочники ──────────────────────────────────────────────────
sups = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
bsup = {b["id"]: b["supplier_id"] for b in sb.get("supplier_brands", "select=id,supplier_id")}
rules = sb.get("retro_rules", "status=eq.active&select=id,supplier_brand_id,retro_base_type,"
               "income_source,returns_policy,returns_allowed,valid_from,valid_to")
aliases = sb.get("supplier_aliases", "select=id,alias_name,supplier_id,alias_type")

# группы: union-find по общим алиасам (кроме excluded)
parent = {}
def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
def union(a, b):
    parent[find(a)] = find(b)

by_alias = defaultdict(set)
raw_kind = {}                      # raw name -> 'in' | 'ret_only' | 'excluded'
for a in aliases:
    nm = (a.get("alias_name") or "").strip()
    if not nm or not a.get("supplier_id"):
        continue
    t = a.get("alias_type")
    if t == "excluded":
        raw_kind.setdefault(nm, "excluded")
        continue
    by_alias[nm].add(a["supplier_id"])
    raw_kind[nm] = "ret_only" if t == "returns_only" and raw_kind.get(nm) != "in" else "in"
for nm, ss in by_alias.items():
    ss = list(ss)
    find(ss[0])
    for s in ss[1:]:
        union(ss[0], s)

gname = {}
for sid in list(parent):
    gname.setdefault(find(sid), []).append(sups.get(sid, "?"))
gname = {g: " + ".join(sorted(v)) for g, v in gname.items()}
raw2g = {nm: find(next(iter(ss))) for nm, ss in by_alias.items()}

def rule_sid(r):
    return bsup.get(r["supplier_brand_id"])

def active(r, per):
    a, b = month_bounds(per)
    vf = date.fromisoformat(r["valid_from"]) if r.get("valid_from") else date(2000, 1, 1)
    vt = date.fromisoformat(r["valid_to"]) if r.get("valid_to") else date(2100, 1, 1)
    return vf < b and vt >= a

def subtract(r):
    if r.get("returns_policy"):
        return r["returns_policy"] == "subtract"
    return bool(r.get("returns_allowed"))

sens_in, sens_ret = set(), set()          # (group, per)
PERS = [f"2026-{m:02d}" for m in range(1, 9)]
for r in rules:
    sid = rule_sid(r)
    if not sid or sid not in parent:
        continue
    ship = (r.get("retro_base_type") or "shipment_minus_return") == "shipment_minus_return"
    inc = (r.get("income_source") or "incoming") == "incoming"
    for per in PERS:
        if active(r, per) and ship and inc:
            sens_in.add((find(sid), per))
            if subtract(r):
                sens_ret.add((find(sid), per))

# ретро по shipment-правилам на группу-месяц (для оценки ущерба) + время расчёта
calcs = sb.get("retro_calculations", "select=id,supplier_id,period_label,total_purchase,created_at")
cinfo = {c["id"]: c for c in calcs}
det = sb.get("retro_calculation_details", "select=id,calculation_id,retro_rule_id,retro_amount")
rtype = {r["id"]: r for r in rules}
retro_ship = defaultdict(float)
calc_time = {}
for c in calcs:
    if c["supplier_id"] in parent:
        k = (find(c["supplier_id"]), c["period_label"])
        ts = parse_ts(c["created_at"])
        calc_time[k] = min(calc_time.get(k, ts), ts)
for d in det:
    c = cinfo.get(d["calculation_id"])
    r = rtype.get(d.get("retro_rule_id"))
    if not c or not r or c["supplier_id"] not in parent:
        continue
    if (r.get("retro_base_type") or "shipment_minus_return") == "shipment_minus_return" \
            and (r.get("income_source") or "incoming") == "incoming":
        retro_ship[(find(c["supplier_id"]), c["period_label"])] += f(d.get("retro_amount"))

print(f"[i] Supabase: поставщиков {len(sups)}, активных правил {len(rules)}, алиасов {len(aliases)}, "
      f"групп {len(set(raw2g.values()))}, расчётов {len(calcs)}, деталей {len(det)}")

# ─── [0] покрытие и целостность ─────────────────────────────────────────────
print(f"\n{'='*96}\n[0] ПОКРЫТИЕ И ЦЕЛОСТНОСТЬ (2026)")
cols_out = [r["column_name"] for r in q(f"""SELECT column_name FROM `{P}.{D}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name='outgoing_to_supplier_transactions' ORDER BY ordinal_position""")]
print(f"    колонки outgoing_to_supplier_transactions: {', '.join(cols_out)}")
for t, amt in [("torgsoft_incoming_ref_2026", "amount"), ("incoming_transactions", "amount_purchase"),
               ("torgsoft_outgoing_ref", "amount_purchase"), ("outgoing_to_supplier_transactions", "amount_purchase")]:
    r = q(f"""SELECT MIN(doc_date) a, MAX(doc_date) b, COUNT(*) n, SUM({amt}) s
              FROM {T(t)} WHERE doc_date >= '2026-01-01'""")[0]
    print(f"    {t:<36} {r['a']} .. {r['b']}  строк {r['n']:>9,}  сумма {f(r['s']):>16,.2f}")
r = q(f"SELECT COUNT(*) n, COUNT(DISTINCT line_id) u FROM {T('incoming_transactions')} WHERE doc_date >= '2026-01-01'")[0]
print(f"    incoming_transactions: строк {r['n']:,} / уникальных line_id {r['u']:,} -> дублей PK {r['n']-r['u']:,}")
key = [c for c in cols_out if c not in ("loaded_at", "source_file")]
r = q(f"""SELECT COUNT(*) n, COUNT(DISTINCT TO_JSON_STRING(STRUCT({', '.join(key)}))) u,
          SUM(amount_purchase) s FROM {T('outgoing_to_supplier_transactions')} WHERE doc_date >= '2026-01-01'""")[0]
print(f"    outgoing_to_supplier_transactions: строк {r['n']:,} / уникальных полных строк {r['u']:,} "
      f"-> полных дублей {r['n']-r['u']:,}")
if r["n"] != r["u"]:
    dd = q(f"""SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per, COUNT(*) - 1 extra, SUM(amount_purchase)/COUNT(*) amt
               FROM {T('outgoing_to_supplier_transactions')} WHERE doc_date >= '2026-01-01'
               GROUP BY TO_JSON_STRING(STRUCT({', '.join(key)})), supplier, per HAVING COUNT(*) > 1
               ORDER BY ABS(SUM(amount_purchase)/COUNT(*)*(COUNT(*)-1)) DESC LIMIT 15""")
    for x in dd:
        print(f"        дубль: {x['supplier'][:34]:<34} {x['per']}  x{x['extra']}  {f(x['amt']):>12,.2f}")

# ─── BQ агрегаты ────────────────────────────────────────────────────────────
inc_o = q(f"""SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per, SUM(amount_purchase) amt,
                     SUM(IF(REGEXP_CONTAINS(LOWER(IFNULL(product_name,'')), r'^сырье'), 0, amount_purchase)) amt_nr,
                     COUNT(DISTINCT doc_number) docs
              FROM {T('incoming_transactions')} WHERE doc_date >= '{D_FROM}' AND doc_date < '{D_TO}' GROUP BY 1,2""")
inc_e = q(f"""SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per, SUM(amount) amt, COUNT(DISTINCT doc_number) docs
              FROM {T('torgsoft_incoming_ref_2026')} WHERE doc_date >= '{D_FROM}' AND doc_date < '{D_TO}' GROUP BY 1,2""")
ret_o = q(f"""SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per, SUM(amount_purchase) amt, COUNT(DISTINCT doc_number) docs
              FROM {T('outgoing_to_supplier_transactions')} WHERE doc_date >= '{D_FROM}' AND doc_date < '{D_TO}' GROUP BY 1,2""")
ret_e = q(f"""SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per, SUM(amount_purchase) amt, COUNT(DISTINCT doc_number) docs
              FROM {T('torgsoft_outgoing_ref')} WHERE doc_date >= '{D_FROM}' AND doc_date < '{D_TO}' GROUP BY 1,2""")

our_total_in = defaultdict(float)     # (group, per) -> весь наш приход группы (для ставки)
for x in inc_o:
    g = raw2g.get((x["supplier"] or "").strip())
    if g and raw_kind.get(x["supplier"].strip()) == "in":
        our_total_in[(g, x["per"])] += f(x["amt"])

csv_rows = []


def block(title, e_rows, o_rows, sens, kind):
    """Сводит эталон/наши по ключу: группа (если алиас есть) иначе сырое имя."""
    agg = defaultdict(lambda: [0.0, 0.0, 0, 0])   # key -> e, o, e_docs, o_docs
    label = {}
    for side, rows in ((0, e_rows), (1, o_rows)):
        for x in rows:
            raw = (x["supplier"] or "<пусто>").strip()
            ok_kind = raw_kind.get(raw) in (("in", "ret_only") if kind == "ret" else ("in",))
            g = raw2g.get(raw) if ok_kind else None
            k = (("G", g) if g else ("R", raw), x["per"])
            label[k[0]] = gname[g] if g else raw
            agg[k][side] += f(x["amt"])
            agg[k][2 + side] += int(x["docs"] or 0)

    buckets = {"scope": [], "obolon": [], "out": []}
    for (key, per), (e, o, ed, od) in agg.items():
        if not (PER_FROM <= per <= PER_TO):
            continue
        nm = label[key]
        if is_obolon(nm):
            b = "obolon"
        elif key[0] == "G" and (key[1], per) in sens:
            b = "scope"
        else:
            b = "out"
        rate = 0.0
        if b == "scope" and our_total_in.get((key[1], per)):
            rate = retro_ship.get((key[1], per), 0.0) / our_total_in[(key[1], per)]
        buckets[b].append((nm, per, e, o, e - o, ed, od, rate))
        csv_rows.append([kind, b, nm, per, f"{e:.2f}", f"{o:.2f}", f"{e-o:.2f}", ed, od,
                         f"{rate:.4f}", f"{abs(e-o)*rate:.2f}"])

    print(f"\n{'='*96}\n{title}")
    print(f"    {'срез':<28}{'пар':>5}{'эталон':>17}{'наши':>17}{'нетто Δ':>14}{'валовая |Δ|':>14}{'пар>порога':>11}{'≈ретро ₴':>11}")
    for b, cap in (("scope", "РЕТРО-СКОУП"), ("out", "вне скоупа"), ("obolon", "Оболонь (не трогаем)")):
        rows = buckets[b]
        E = sum(r[2] for r in rows); O = sum(r[3] for r in rows)
        G = sum(abs(r[4]) for r in rows)
        big = [r for r in rows if abs(r[4]) >= MIN_ABS and abs(r[4]) >= MIN_PCT * max(abs(r[2]), abs(r[3]), 1)]
        imp = sum(abs(r[4]) * r[7] for r in rows)
        print(f"    {cap:<28}{len(rows):>5}{E:>17,.0f}{O:>17,.0f}{E-O:>14,.0f}{G:>14,.0f}{len(big):>11}"
              f"{(f'{imp:,.0f}' if b == 'scope' else '-'):>11}")
    rows = sorted(buckets["scope"], key=lambda r: -abs(r[4]) * max(r[7], 1e-9))
    big = [r for r in rows if abs(r[4]) >= MIN_ABS and abs(r[4]) >= MIN_PCT * max(abs(r[2]), abs(r[3]), 1)]
    print(f"\n    Ретро-скоуп, пары выше порога ({MIN_ABS:,.0f} ₴ и {MIN_PCT:.1%}), по ретро-ущербу:")
    print(f"    {'группа':<44}{'период':<9}{'эталон':>13}{'наши':>13}{'Δ':>11}{'док':>10}{'ставка':>8}{'≈ретро':>9}")
    for nm, per, e, o, d, ed, od, rate in big[:35]:
        print(f"    {nm[:43]:<44}{per:<9}{e:>13,.0f}{o:>13,.0f}{d:>11,.0f}{f'{ed}/{od}':>10}"
              f"{rate:>8.1%}{abs(d)*rate:>9,.0f}")
    if len(big) > 35:
        print(f"    ... ещё {len(big)-35} в CSV")
    return buckets


bi = block("[1] ПРИХОДЫ: torgsoft_incoming_ref_2026 vs incoming_transactions (янв-авг)", inc_e, inc_o, sens_in, "inc")
br = block("[2] ВОЗВРАТЫ: torgsoft_outgoing_ref vs outgoing_to_supplier_transactions (янв-авг)", ret_e, ret_o, sens_ret, "ret")

# ─── [3] не-эталон: приход, долитый после расчёта ───────────────────────────
print(f"\n{'='*96}\n[3] НЕ-ЭТАЛОН: приход в incoming_transactions, загруженный ПОСЛЕ сохранения расчёта")
late = q(f"""SELECT supplier, FORMAT_DATE('%Y-%m', doc_date) per, TIMESTAMP_TRUNC(TIMESTAMP(loaded_at), MINUTE) ts,
                    SUM(IF(REGEXP_CONTAINS(LOWER(IFNULL(product_name,'')), r'^сырье'), 0, amount_purchase)) amt
             FROM {T('incoming_transactions')} WHERE doc_date >= '{D_FROM}' AND doc_date < '{D_TO}' GROUP BY 1,2,3""")
lag = defaultdict(float)
for x in late:
    raw = (x["supplier"] or "").strip()
    g = raw2g.get(raw) if raw_kind.get(raw) == "in" else None
    if not g or (g, x["per"]) not in sens_in or is_obolon(gname[g]):
        continue
    ct = calc_time.get((g, x["per"]))
    ts = x["ts"] if x["ts"].tzinfo else x["ts"].replace(tzinfo=timezone.utc)
    if ct and ts > ct:
        lag[(g, x["per"])] += f(x["amt"])
lr = sorted(((gname[g], per, a, retro_ship.get((g, per), 0) / our_total_in[(g, per)] if our_total_in.get((g, per)) else 0,
              calc_time[(g, per)]) for (g, per), a in lag.items() if abs(a) >= 1), key=lambda r: -abs(r[2]) * r[3])
print(f"    пар с доливкой после расчёта: {len(lr)} | сумма прихода {sum(r[2] for r in lr):,.0f} "
      f"| ≈ недосчитано ретро {sum(r[2]*r[3] for r in lr):,.0f} ₴")
for nm, per, a, rate, ct in lr[:25]:
    print(f"    {nm[:44]:<45}{per:<9}{a:>13,.0f}  ставка {rate:>6.1%}  ≈ретро {a*rate:>8,.0f}  расчёт от {ct:%d.%m %H:%M}")

# ─── [4] имена без алиаса ───────────────────────────────────────────────────
print(f"\n{'='*96}\n[4] ИМЕНА ПОСТАВЩИКОВ В BQ БЕЗ АЛИАСА (приход янв-авг, топ-20; НЕ склеивать, только завести/решить)")
na = defaultdict(lambda: [0.0, 0.0])
for side, rows in ((0, inc_e), (1, inc_o)):
    for x in rows:
        raw = (x["supplier"] or "<пусто>").strip()
        if raw not in raw_kind and PER_FROM <= x["per"] <= PER_TO:
            na[raw][side] += f(x["amt"])
for raw, (e, o) in sorted(na.items(), key=lambda kv: -max(kv[1]))[:20]:
    print(f"    {raw[:50]:<51} эталон {e:>14,.0f}   наши {o:>14,.0f}")

out = ROOT / "_archive" / "bq_retro_scope_2026.csv"
with open(out, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh, delimiter=";")
    w.writerow(["table", "bucket", "group_or_raw", "period", "etalon", "ours", "delta",
                "etalon_docs", "our_docs", "retro_rate", "retro_impact"])
    w.writerows(csv_rows)
print(f"\nCSV: {out.relative_to(ROOT)}")

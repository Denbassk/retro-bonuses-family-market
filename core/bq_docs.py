#!/usr/bin/env python3
"""
bq_docs.py - сверка ДОКУМЕНТОВ BigQuery с эталоном Торгсофт (приходы и возвраты поставщику).

Зачем: расчёт ретро берёт базу из incoming_transactions / outgoing_to_supplier_transactions. Если база
недогружена, задвоена или документ попал в другой месяц - расчёт неверный, хотя правила верные.
Эталон (torgsoft_incoming_ref_2026, torgsoft_outgoing_ref) - выгрузка документов из Торгсофта.

Сопоставление (проверено 11.09 на июне: номер + ТТ + поставщик совпадают у 7113 из 7113 наших документов):
  1) по (поставщик, ТТ, номер документа) - дальше сравниваются дата и сумма;
  2) непарные: по (поставщик, ТТ, сумма ±1 ₴, дата ±3 дня) - номер записан по-разному.
Типы расхождений:
  missing  - документ есть в эталоне, у нас нет (недогруз)
  extra    - у нас есть, в эталоне нет
  double   - у нас документ загружен дважды (две даты/два файла или сумма = 2 × эталон)
  amount   - сумма документа у нас другая (часть строк потеряна/лишняя)
  date     - дата у нас в другом месяце, чем в эталоне (сдвиг через границу месяца)
Эффект на месяц m считается строго: база эталона(m) - наша база(m) по этому документу,
поэтому сумма всех эффектов месяца = итог эталона - наш итог.

Запуск (из корня):  python core\\bq_docs.py                 # общий отчёт по всем поставщикам -> output\\data_health_2026.csv
                    python core\\bq_docs.py --supplier "Юрія"
"""
import os, csv, argparse
from collections import defaultdict
from datetime import date

from paths import OUT
import sb  # noqa: F401  (загружает .env)

PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics")
DS = os.environ.get("BQ_DATASET", "family_market")
KINDS = {
    "inc": {"ours": "incoming_transactions", "o_amt": "amount_purchase",
            "etalon": "torgsoft_incoming_ref_2026", "e_amt": "amount", "e_where": ""},
    "ret": {"ours": "outgoing_to_supplier_transactions", "o_amt": "amount_purchase",
            "etalon": "torgsoft_outgoing_ref", "e_amt": "amount_purchase", "e_where": "AND NOT IFNULL(is_internal, FALSE)"},
}
TYPE_RU = {"missing": "нет у нас (недогруз)", "extra": "нет в эталоне", "double": "задвоено у нас",
           "amount": "сумма документа другая", "date": "дата в другом месяце", "number": "номер другой, дата в другом месяце",
           "et_double": "задвоено в эталоне (у нас верно)"}
NOT_OURS = {"et_double"}   # расхождения по вине эталона - не объясняют ретро и не считаются дырой в нашей базе
AMT_EPS = 1.0
DAY_WINDOW = 3


def per_of(d):
    return f"{d.year}-{d.month:02d}"


def month_bounds(per):
    y, m = int(per[:4]), int(per[5:])
    return date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)


def fetch(kind, d1, d2, names=None, cli=None):
    """-> (наши документы, документы эталона, последняя дата эталона). Документ = поставщик+ТТ+дата+номер."""
    from google.cloud import bigquery
    k = KINDS[kind]
    cli = cli or bigquery.Client(project=PROJ)
    T = lambda t: f"`{PROJ}.{DS}.{t}`"
    flt = "AND TRIM(supplier) IN UNNEST(@n)" if names else ""
    params = [bigquery.ScalarQueryParameter("d1", "DATE", d1), bigquery.ScalarQueryParameter("d2", "DATE", d2)]
    if names:
        params.append(bigquery.ArrayQueryParameter("n", "STRING", sorted(names)))
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    q_o = f"""SELECT TRIM(supplier) supplier, store, doc_date, doc_number, ROUND(SUM({k['o_amt']}), 2) amt,
                COUNT(*) lines, STRING_AGG(DISTINCT IFNULL(source_file, '?'), ', ') files
              FROM {T(k['ours'])} WHERE doc_date BETWEEN @d1 AND @d2 {flt} GROUP BY 1, 2, 3, 4"""
    q_e = f"""SELECT TRIM(supplier) supplier, store, doc_date, doc_number, ROUND(SUM({k['e_amt']}), 2) amt
              FROM {T(k['etalon'])} WHERE doc_date BETWEEN @d1 AND @d2 {k['e_where']} {flt} GROUP BY 1, 2, 3, 4"""
    ours = [dict(r) for r in cli.query(q_o, job_config=cfg)]
    et = [dict(r) for r in cli.query(q_e, job_config=cfg)]
    et_max = next(iter(cli.query(f"SELECT MAX(doc_date) m FROM {T(k['etalon'])}")))["m"]
    return ours, et, et_max


def _event(typ, o, e):
    eff = defaultdict(float)
    for x in o:
        eff[per_of(x["doc_date"])] -= float(x["amt"] or 0)
    for x in e:
        eff[per_of(x["doc_date"])] += float(x["amt"] or 0)
    eff = {p: round(v, 2) for p, v in eff.items() if abs(v) >= 0.005}
    base = (o or e)[0]
    return {"type": typ, "supplier": base["supplier"], "store": base["store"], "number": base["doc_number"],
            "o": [(str(x["doc_date"]), float(x["amt"] or 0), x.get("files") or "") for x in o],
            "e": [(str(x["doc_date"]), float(x["amt"] or 0)) for x in e], "eff": eff}


def match(ours, et):
    """Сопоставить документы -> список событий-расхождений с эффектом по месяцам (эталон - наши)."""
    ok, ek = defaultdict(list), defaultdict(list)
    for d in ours:
        ok[(d["supplier"], d["store"], d["doc_number"])].append(d)
    for d in et:
        ek[(d["supplier"], d["store"], d["doc_number"])].append(d)
    events, lo, le, matched_e = [], [], [], []
    for key in set(ok) | set(ek):
        o, e = ok.get(key, []), ek.get(key, [])
        if not e:
            lo += o
            continue
        if not o:
            le += e
            continue
        matched_e += e
        oa, ea = sum(float(x["amt"] or 0) for x in o), sum(float(x["amt"] or 0) for x in e)
        # задвоение: документ у нас в двух экземплярах (разные даты) или сумма ≈ 2 × эталон (±2%)
        if len(o) > len(e) or (abs(ea) >= AMT_EPS and abs(oa - 2 * ea) <= max(2 * AMT_EPS, 0.02 * abs(ea))):
            typ = "double"
        elif len(e) > len(o) or (abs(oa) >= AMT_EPS and abs(ea - 2 * oa) <= max(2 * AMT_EPS, 0.02 * abs(oa))):
            typ = "et_double"   # в эталоне документ вдвое больше - проблема выгрузки эталона, наша база верна
        elif {per_of(x["doc_date"]) for x in o} != {per_of(x["doc_date"]) for x in e}:
            typ = "date"
        elif abs(oa - ea) >= AMT_EPS:
            typ = "amount"
        else:
            continue
        ev = _event(typ, o, e)
        if ev["eff"]:
            events.append(ev)

    # 2-й проход: номер записан по-разному - та же ТТ, сумма ±1 ₴, дата ±3 дня
    pool = defaultdict(list)
    for x in le:
        pool[(x["supplier"], x["store"])].append(x)
    used = set()
    for o in sorted(lo, key=lambda x: (x["doc_date"], x["doc_number"])):
        best = None
        for i, e in enumerate(pool.get((o["supplier"], o["store"]), [])):
            if id(e) in used or abs(float(o["amt"] or 0) - float(e["amt"] or 0)) >= AMT_EPS:
                continue
            gap = abs((o["doc_date"] - e["doc_date"]).days)
            if gap <= DAY_WINDOW and (best is None or gap < best[0]):
                best = (gap, e)
        if best:
            used.add(id(best[1]))
            matched_e.append(best[1])
            if per_of(o["doc_date"]) != per_of(best[1]["doc_date"]):
                events.append(_event("number", [o], [best[1]]))
        elif abs(float(o["amt"] or 0)) >= AMT_EPS:
            events.append(_event("extra", [o], []))
    # непарный документ эталона, у которого есть «близнец» (та же ТТ, дата, сумма) среди сопоставленных,
    # - это дубль внутри самого эталона (короткий и длинный номер), не недогруз
    twins = {(x["supplier"], x["store"], x["doc_date"], round(float(x["amt"] or 0))) for x in matched_e}
    for e in le:
        if id(e) in used or abs(float(e["amt"] or 0)) < AMT_EPS:
            continue
        if (e["supplier"], e["store"], e["doc_date"], round(float(e["amt"] or 0))) in twins:
            continue
        events.append(_event("missing", [], [e]))
    return events


def summarize(events, per, names=None):
    """События месяца по поставщикам names -> {type: {"n", "delta", "docs": [...]}} (delta = эталон - наши)."""
    out = {}
    for ev in events:
        if names is not None and ev["supplier"] not in names:
            continue
        v = ev["eff"].get(per)
        if not v:
            continue
        s = out.setdefault(ev["type"], {"n": 0, "delta": 0.0, "docs": []})
        s["n"] += 1
        s["delta"] = round(s["delta"] + v, 2)
        s["docs"].append((abs(v), ev))
    for s in out.values():
        s["docs"] = [ev for _, ev in sorted(s["docs"], key=lambda x: -x[0])]
    return out


def n0(x, sign=False):
    return (f"{x:+,.0f}" if sign else f"{x:,.0f}").replace(",", " ")


def doc_label(ev):
    o = "/".join(f"{d[8:10]}.{d[5:7]} {n0(a)}" for d, a, _ in ev["o"]) or "нет"
    e = "/".join(f"{d[8:10]}.{d[5:7]} {n0(a)}" for d, a in ev["e"]) or "нет"
    return f"№{ev['number']} {ev['store']}: у нас {o}, эталон {e}"


def describe(summ, what="приходы", limit=2):
    """Короткая строка для диагноза: «приходы: нет у нас 3 док. на +12 345 (№...), задвоено 1 на -2 000»."""
    parts = []
    for typ in ("missing", "double", "amount", "date", "number", "extra", "et_double"):
        s = summ.get(typ)
        if not s:
            continue
        ex = " | ".join(doc_label(ev) for ev in s["docs"][:limit])
        parts.append(f"{TYPE_RU[typ]} {s['n']} док. на {n0(s['delta'], True)} ({ex}{' …' if s['n'] > limit else ''})")
    return f"{what}: " + ", ".join(parts) if parts else ""


def load_all(per_from, per_to, names=None):
    """Документы обоих видов за окно (с запасом ±1 мес. для сдвигов дат) -> {kind: (events, etalon_last_per)}."""
    from google.cloud import bigquery
    cli = bigquery.Client(project=PROJ)
    d1 = month_bounds(per_from)[0]
    d1 = date(d1.year - (d1.month == 1), (d1.month - 2) % 12 + 1, 1)
    d2 = month_bounds(per_to)[1]
    d2 = date(d2.year + (d2.month == 12), d2.month % 12 + 1, 1)
    out = {}
    for kind in KINDS:
        ours, et, et_max = fetch(kind, d1, d2, names, cli)
        # за пределами эталона всё выглядело бы «нет в эталоне» - документы после его последней даты не сверяем
        if et_max:
            ours = [x for x in ours if x["doc_date"] <= et_max]
        out[kind] = (match(ours, et), per_of(et_max) if et_max else None, len(ours), len(et))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="per_from", default="2026-01")
    ap.add_argument("--to", dest="per_to", default=None)
    ap.add_argument("--supplier", help="имя поставщика как в BigQuery (точно)")
    a = ap.parse_args()
    t = date.today()
    per_to = a.per_to or per_of(date(t.year - (t.month == 1), (t.month - 2) % 12 + 1, 1))
    health(a.per_from, per_to, {a.supplier} if a.supplier else None)


def retro_alias_names():
    """Имена в BigQuery, по которым РЕАЛЬНО есть ретро: алиас привязан к бренду/поставщику с активным правилом.
    Просто наличие алиаса не значит ретро (Кока-Кола, Алко Трейдінг заведены, но правил нет)."""
    brands = {b["id"]: b["supplier_id"] for b in sb.get("supplier_brands", "select=id,supplier_id")}
    rule_brands = {r["supplier_brand_id"] for r in sb.get("retro_rules", "status=eq.active&select=supplier_brand_id")}
    rule_sups = {brands[b] for b in rule_brands if b in brands}
    out = set()
    for a in sb.get("supplier_aliases", "alias_type=neq.excluded&select=alias_name,supplier_id,supplier_brand_id"):
        nm = (a.get("alias_name") or "").strip()
        if nm and (a["supplier_brand_id"] in rule_brands if a.get("supplier_brand_id") else a.get("supplier_id") in rule_sups):
            out.add(nm)
    return out


def doc_range(evs, typ):
    """Диапазон проблемных документов -> («20.07-23.07», «№18479-№25113 (34)»).
    Чтобы по сводке было сразу видно, какой кусок базы подгружать или где искать дубли.
    У «нет у нас» и «задвоено в эталоне» диапазон берём по эталонным датам, у остальных - по нашим."""
    src_e = typ in ("missing", "et_double")
    ds, ns = [], set()
    for ev in evs:
        ds += [d for d, *_ in (ev["e"] if src_e else ev["o"])]
        if ev.get("number"):
            ns.add(str(ev["number"]))
    ds = sorted(x for x in ds if x)
    ns = sorted(ns, key=lambda x: (len(x), x) if x.isdigit() else (99, x))
    dm = lambda d: f"{d[8:10]}.{d[5:7]}"
    dr = "" if not ds else (dm(ds[0]) if ds[0] == ds[-1] else f"{dm(ds[0])}-{dm(ds[-1])}")
    nr = "" if not ns else (f"№{ns[0]}" if len(ns) == 1 else f"№{ns[0]}-№{ns[-1]} ({len(ns)} док.)")
    return dr, nr


def health(per_from, per_to, names=None):
    """Полнота и дубли базы по всем поставщикам: таблица по месяцам + крупнейшие у ретро-поставщиков -> CSV."""
    retro_names = retro_alias_names()
    data = load_all(per_from, per_to, names)
    pers, p = [], per_from
    while p <= per_to:
        pers.append(p)
        y, m = int(p[:4]), int(p[5:]) + 1
        p = f"{y + (m > 12)}-{(m - 1) % 12 + 1:02d}"

    rows = []
    for kind, (events, et_last, n_o, n_e) in data.items():
        print(f"\n[{'ПРИХОДЫ' if kind == 'inc' else 'ВОЗВРАТЫ'}] документов у нас {n_o}, в эталоне {n_e}, эталон до {et_last}")
        print(f"    {'месяц':<8}" + "".join(f"{TYPE_RU[x][:18]:>22}" for x in TYPE_RU) + f"{'итог эталон-наши':>20}")
        for per in pers:
            if et_last and per > et_last:
                print(f"    {per:<8}  эталона нет - не сверяется")
                continue
            summ = summarize(events, per)
            cells = "".join(f"{(str(summ[x]['n']) + ' / ' + n0(summ[x]['delta'], True)) if x in summ else '':>22}" for x in TYPE_RU)
            print(f"    {per:<8}{cells}{n0(sum(s['delta'] for s in summ.values()), True):>20}")
            by_sup = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
            for typ, s in summ.items():
                for ev in s["docs"]:
                    c = by_sup[ev["supplier"]][typ]
                    c[0] += 1
                    c[1] += ev["eff"][per]
            for sup, types in by_sup.items():
                for typ, (n, dl) in types.items():
                    evs = [ev for ev in summ[typ]["docs"] if ev["supplier"] == sup]
                    dr, nr = doc_range(evs, typ)
                    rows.append([kind, per, sup, "да" if sup in retro_names else "", typ, TYPE_RU[typ], n, round(dl, 2),
                                 dr, nr, " | ".join(doc_label(ev) for ev in evs[:3])])
        big = sorted([r for r in rows if r[0] == kind and r[3] and r[4] in ("missing", "double", "amount")],
                     key=lambda r: -abs(r[7]))[:12]
        if big:
            print("    крупнейшие у ретро-поставщиков (недогруз / задвоение / сумма):")
            for r in big:
                print(f"      {r[1]} {r[2][:32]:<32} {r[5]:<20} {r[6]:>3} док. {n0(r[7], True):>10}  "
                      f"{r[8]:<12} {r[9][:28]:<28} {r[10][:60]}")
    dst = OUT / "data_health_2026.csv"
    with dst.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["вид", "месяц", "поставщик BQ", "в ретро", "тип", "тип_ru", "документов", "эталон - наши",
                    "даты", "номера", "примеры"])
        w.writerows(sorted(rows, key=lambda r: (r[0], r[1], -abs(r[7]))))
    print(f"\n[>] {dst.relative_to(OUT.parent)}")


if __name__ == "__main__":
    main()

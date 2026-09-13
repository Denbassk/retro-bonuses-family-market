"""Разовый, только чтение. Гипотеза: коньяк ЗЛАГОДА переименован в «бренді» с новыми баркодами,
старые баркоды в правилах мёртвые -> расчёт занижен, сверка видит переплату.
Один запрос в BQ: приходы ЗЛАГОДА по интересующим SKU за 2026-01..08.
-> output/probe_zlagoda_brandy.txt"""
import os, sys
from decimal import Decimal
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
from calculate_retro import apply_vat
from google.cloud import bigquery
PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics"); DS = os.environ.get("BQ_DATASET", "family_market")

sup = {s["name"]: s["id"] for s in sb.get("suppliers", "select=id,name")}
sid = sup["ЗЛАГОДА-ОПТ"]
brands = {b["id"]: b["name"] for b in sb.get("supplier_brands", f"supplier_id=eq.{sid}&select=id,name")}
rules = sb.get("retro_rules", f"supplier_brand_id=in.({','.join(brands)})&status=eq.active&select=*")
rule_of = {}
for r in rules:
    for b in (r.get("sku_barcodes") or []):
        rule_of[str(b)] = f"{brands.get(r['supplier_brand_id'])} {r.get('retro_min')}%"
al = sorted({a["alias_name"].strip() for a in sb.get("supplier_aliases", f"supplier_id=eq.{sid}&alias_type=neq.excluded&select=alias_name")})
cli = bigquery.Client(project=PROJ)
cfg = bigquery.QueryJobConfig(query_parameters=[
    bigquery.ArrayQueryParameter("n", "STRING", al),
    bigquery.ArrayQueryParameter("b", "STRING", sorted(rule_of) or ["-"])])
q = f"""SELECT CAST(barcode AS STRING) bc, ANY_VALUE(product_name) nm,
   STRING_AGG(DISTINCT FORMAT_DATE('%m', doc_date) ORDER BY FORMAT_DATE('%m', doc_date)) mons,
   ROUND(SUM(amount_purchase), 2) amt
 FROM `{PROJ}.{DS}.incoming_transactions`
 WHERE TRIM(supplier) IN UNNEST(@n) AND doc_date BETWEEN '2026-01-01' AND '2026-08-31'
   AND (REGEXP_CONTAINS(LOWER(product_name), r'бренді|бренди|коньяк|коньяк|тиса|тіса') OR CAST(barcode AS STRING) IN UNNEST(@b))
 GROUP BY 1 ORDER BY amt DESC"""
rows = [dict(r) for r in cli.query(q, job_config=cfg)]
by_month = defaultdict(float)
q2 = f"""SELECT FORMAT_DATE('%Y-%m', doc_date) per, CAST(barcode AS STRING) bc, ROUND(SUM(amount_purchase),2) amt
 FROM `{PROJ}.{DS}.incoming_transactions`
 WHERE TRIM(supplier) IN UNNEST(@n) AND doc_date BETWEEN '2026-01-01' AND '2026-08-31'
   AND REGEXP_CONTAINS(LOWER(product_name), r'бренді|бренди|коньяк|тиса|тіса') GROUP BY 1,2"""
per_bc = [dict(r) for r in cli.query(q2, job_config=cfg)]

out = [f"алиасы ЗЛАГОДА: {al}", f"активных правил: {len(rules)}, SKU в правилах: {len(rule_of)}",
       f"subtract_vat_from_retro: {sorted({bool(r.get('subtract_vat_from_retro')) for r in rules})}", ""]
out.append("[1] коньяк/бренді/тиса в приходах BQ 2026-01..08")
out.append(f"{'баркод':<15}{'наименование':<52}{'месяцы':<26}{'приход':>12}  правило")
name_hit = [r for r in rows if any(w in (r["nm"] or "").lower() for w in ("бренді", "бренди", "коньяк", "тиса", "тіса"))]
for r in sorted(name_hit, key=lambda x: -x["amt"]):
    out.append(f"{r['bc']:<15}{(r['nm'] or '')[:50]:<52}{r['mons']:<26}{r['amt']:>12,.0f}  "
               f"{rule_of.get(r['bc'], 'НЕТ в правилах')}")

out.append("\n[2] баркоды правил «Тиса коньяк» без прихода за окно (мёртвые)")
seen = {r["bc"]: r for r in rows}
for bc, rl in sorted(rule_of.items()):
    if "Тиса" in rl and bc not in seen:
        out.append(f"    {bc}  {rl}")
out.append("    (в приходах BQ за 8 месяцев такого баркода нет)")

out.append("\n[3] retro_reconciliation по ЗЛАГОДА")
rec = sorted(sb.get("retro_reconciliation", f"supplier_id=eq.{sid}&select=period_label,calc_amount,fact_amount,delta,status"),
             key=lambda r: r["period_label"])
out.append(f"{'месяц':<9}{'расчёт':>12}{'факт':>12}{'разница':>12}  статус")
for r in rec:
    out.append(f"{r['period_label']:<9}{float(r['calc_amount'] or 0):>12,.0f}{float(r['fact_amount'] or 0):>12,.0f}"
               f"{float(r['delta'] or 0):>+12,.0f}  {r['status']}")

out.append("\n[4] проверка гипотезы: переплата против ретро по непокрытым «бренді/коньяк» SKU")
uncovered = {r["bc"] for r in name_hit if r["bc"] not in rule_of}
rule10 = next((r for r in rules if "Тиса" in brands.get(r["supplier_brand_id"], "") and float(r["retro_min"]) == 10.0), rules[0])
inc_m = defaultdict(float)
for r in per_bc:
    if r["bc"] in uncovered:
        inc_m[r["per"]] += r["amt"]
out.append(f"непокрытых баркодов: {len(uncovered)}; ставка для оценки {rule10.get('retro_min')}%, "
           f"НДС-вычет {bool(rule10.get('subtract_vat_from_retro'))}")
out.append(f"{'месяц':<9}{'приход непокр.':>15}{'оценка ретро':>14}{'переплата факта':>17}  вывод")
delta = {r["period_label"]: float(r["delta"] or 0) for r in rec}
for per in sorted(set(inc_m) | set(delta)):
    est = float(apply_vat(Decimal(str(round(inc_m.get(per, 0.0), 2))) * Decimal(str(rule10["retro_min"])) / Decimal("100"), rule10))
    d = delta.get(per, 0.0)
    verdict = "совпадает" if est and abs(est - d) <= max(50.0, 0.15 * max(est, abs(d))) else "не совпадает"
    out.append(f"{per:<9}{inc_m.get(per, 0.0):>15,.0f}{est:>14,.0f}{d:>+17,.0f}  {verdict}")
(ROOT / "output" / "probe_zlagoda_brandy.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

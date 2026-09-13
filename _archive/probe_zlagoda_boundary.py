"""Разовый, только чтение. ЗЛАГОДА-ОПТ, июль: версия про граничные документы (28-30.06 и 01-03.07).
Наши документы против эталона Торгсофт в том же окне: дата, сумма, в каком месяце учтено.
-> output/probe_zlagoda_boundary.txt"""
import os, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
from google.cloud import bigquery
PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics"); DS = os.environ.get("BQ_DATASET", "family_market")
sup = {s["name"]: s["id"] for s in sb.get("suppliers", "select=id,name")}
sid = sup["ЗЛАГОДА-ОПТ"]
al = sorted({a["alias_name"].strip() for a in sb.get("supplier_aliases", f"supplier_id=eq.{sid}&alias_type=neq.excluded&select=alias_name")})
cli = bigquery.Client(project=PROJ)
cfg = bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("n", "STRING", al)])
ours = [dict(r) for r in cli.query(f"""SELECT doc_number num, store, doc_date, ROUND(SUM(amount_purchase),2) amt
  FROM `{PROJ}.{DS}.incoming_transactions` WHERE TRIM(supplier) IN UNNEST(@n)
   AND doc_date BETWEEN '2026-06-26' AND '2026-07-05' GROUP BY 1,2,3 ORDER BY 3, 4 DESC""", job_config=cfg)]
et = {(r["num"], r["store"]): r for r in [dict(x) for x in cli.query(
    f"""SELECT doc_number num, store, doc_date, ROUND(SUM(amount),2) amt FROM `{PROJ}.{DS}.torgsoft_incoming_ref_2026`
    WHERE TRIM(supplier) IN UNNEST(@n) AND doc_date BETWEEN '2026-06-20' AND '2026-07-10' GROUP BY 1,2,3""", job_config=cfg)]}
calcs = {c["period_label"]: c for c in sb.get("retro_calculations", f"supplier_id=eq.{sid}&select=period_label,total_retro,total_base")}
rate = {p: (float(c["total_retro"] or 0) / float(c["total_base"] or 1)) for p, c in calcs.items()}
out = [f"эффективная ставка: июнь {rate.get('2026-06', 0):.2%}, июль {rate.get('2026-07', 0):.2%}",
       f"\n{'документ':<12}{'ТТ':<24}{'дата у нас':<12}{'сумма':>11}{'учтён у нас':<10}  эталон (дата/сумма)"]
last3, first3 = 0.0, 0.0
for r in sorted(ours, key=lambda x: (x["doc_date"], -x["amt"])):
    e = et.get((r["num"], r["store"]))
    d = str(r["doc_date"])
    per = "июнь" if d < "2026-07-01" else "июль"
    if "2026-06-28" <= d <= "2026-06-30":
        last3 += r["amt"]
    if "2026-07-01" <= d <= "2026-07-03":
        first3 += r["amt"]
    if not e:
        mark = "нет в эталоне"
    elif str(e["doc_date"]) != d:
        mark = f"эталон датирует {e['doc_date']}"
    elif abs(float(e["amt"]) - r["amt"]) >= 1:
        mark = f"дата совпадает, сумма эталона {float(e['amt']):,.0f}"
    else:
        mark = "совпадает с эталоном"
    out.append(f"{str(r['num']):<12}{(r['store'] or '')[:22]:<24}{d:<12}{r['amt']:>11,.0f}  {per:<10}  {mark}")
out.append(f"\nитого 28-30.06 (у нас июнь): {last3:,.0f} -> ретро по ставке июля {last3 * rate.get('2026-07', 0):,.0f}")
out.append(f"итого 01-03.07 (у нас июль): {first3:,.0f} -> ретро {first3 * rate.get('2026-07', 0):,.0f}")
out.append(f"переплата июля по сверке: +5 973")
(ROOT / "output" / "probe_zlagoda_boundary.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

"""Разовый: приход BQ по спорным SKU ЗЛАГОДА (май/август) против сумм двух строк расчёта;
плюс карточки правил СТВ Схід и БІР (Пиво Кег), попавших в группу «правило истекло».
-> output/probe_zlagoda_double.txt"""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb
from google.cloud import bigquery
PROJ = os.environ.get("BQ_PROJECT", "family-market-analytics"); DS = os.environ.get("BQ_DATASET", "family_market")
BCS = ["4820001830071", "4820001020021", "4820111141029", "4820001021066", "4820111141036",
       "4820111140985", "4820219343028", "4820111141005"]
sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
name2id = {v: k for k, v in sup.items()}
zl = name2id["ЗЛАГОДА-ОПТ"]
al = sorted({a["alias_name"].strip() for a in sb.get("supplier_aliases", f"supplier_id=eq.{zl}&alias_type=neq.excluded&select=alias_name")})
cli = bigquery.Client(project=PROJ)
cfg = bigquery.QueryJobConfig(query_parameters=[
    bigquery.ArrayQueryParameter("n", "STRING", al), bigquery.ArrayQueryParameter("b", "STRING", BCS)])
out = [f"ЗЛАГОДА-ОПТ, алиасы: {al}", "приход BQ по спорным SKU (май, август):"]
for r in cli.query(f"""SELECT FORMAT_DATE('%Y-%m', doc_date) per, CAST(barcode AS STRING) bc,
      ROUND(SUM(amount_purchase),2) amt FROM `{PROJ}.{DS}.incoming_transactions`
    WHERE TRIM(supplier) IN UNNEST(@n) AND CAST(barcode AS STRING) IN UNNEST(@b)
      AND doc_date BETWEEN '2026-05-01' AND '2026-08-31' GROUP BY 1,2 ORDER BY 1,3 DESC""", job_config=cfg):
    if r["per"] in ("2026-05", "2026-08"):
        out.append(f"  {r['per']} {r['bc']} {r['amt']:>12,.2f}")
brands = {b["id"]: b["name"] for b in sb.get("supplier_brands", "select=id,name")}
for nm in ("ЗЛАГОДА-ОПТ", "СТВ Схід (Наша Ряба, Легко!, Бащинський)", "БІР (Пиво Кег)"):
    sid = name2id.get(nm)
    bids = [b["id"] for b in sb.get("supplier_brands", f"supplier_id=eq.{sid}&select=id")]
    out.append(f"\nправила {nm}:")
    for r in sb.get("retro_rules", f"supplier_brand_id=in.({','.join(bids)})&select=*"):
        out.append(f"  [{r['status']}] {brands.get(r['supplier_brand_id'], '?')[:30]:<32} {r['valid_from']}..{r.get('valid_to')} "
                   f"{r.get('retro_min')}% base={r.get('retro_base_type')} sku={len(r.get('sku_barcodes') or [])} "
                   f"excl={len(r.get('excluded_sku_barcodes') or [])} | {(r.get('notes') or '')[:50]}")
(ROOT / "output" / "probe_zlagoda_double.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")

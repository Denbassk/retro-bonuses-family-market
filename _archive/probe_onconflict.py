"""Разовый probe: есть ли уникальный индекс под on_conflict. Пустой upsert ничего не пишет,
но Postgres валидирует ON CONFLICT при планировании (42P10, если индекса нет)."""
import sys
from pathlib import Path
sys.path.insert(0, str((Path(__file__).resolve().parent.parent) / "core"))
import sb

for t, oc in [("retro_payments_fact", "supplier_id,period_label"),   # контроль: индекс есть (админка)
              ("store_opening_bonuses", "supplier_id,store_label,year"),
              ("store_opening_bonuses", "source_file")]:              # контроль: индекса точно нет
    try:
        sb._req(f"{sb.URL}/rest/v1/{t}?on_conflict={oc}", [], "POST",
                {"Prefer": "return=minimal,resolution=merge-duplicates"})
        print(f"OK    {t} ({oc})")
    except RuntimeError as e:
        print(f"FAIL  {t} ({oc}): {str(e)[-160:]}")
print("store_opening_bonuses строк:", len(sb.get("store_opening_bonuses", "select=id")))

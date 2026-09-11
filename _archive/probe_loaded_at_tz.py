"""Разовый probe: тип и часовой пояс loaded_at (сверка показала загрузку «в 14:16 UTC» раньше, чем она могла быть)."""
import os, sys
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb  # noqa
from google.cloud import bigquery
P, D = os.environ.get("BQ_PROJECT", "family-market-analytics"), os.environ.get("BQ_DATASET", "family_market")
c = bigquery.Client(project=P)
for r in c.query(f"""SELECT table_name, column_name, data_type FROM `{P}.{D}.INFORMATION_SCHEMA.COLUMNS`
                     WHERE column_name = 'loaded_at' AND table_name IN ('incoming_transactions','outgoing_to_supplier_transactions')"""):
    print(dict(r))
for t in ("incoming_transactions", "outgoing_to_supplier_transactions"):
    r = list(c.query(f"SELECT MAX(loaded_at) mx, CURRENT_TIMESTAMP() now_utc FROM `{P}.{D}.{t}`"))[0]
    print(t, "MAX(loaded_at) =", r["mx"], "| сейчас UTC =", r["now_utc"])
print("локально сейчас:", datetime.now(), "| UTC:", datetime.now(timezone.utc))

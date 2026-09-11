"""
migrate_references_to_supabase.py

Миграция справочников из BigQuery в Supabase:
  - delivery_points  (магазины, РЦ, опт, производство)
  - suppliers        (предварительно — имена из BigQuery как канонические)
  - supplier_aliases (алиас = каноническое имя из BigQuery)

После финализации HTML-справочника поставщиков:
  1. Канонические имена в `suppliers` обновятся на правильные.
  2. Алиасы переподвяжутся при необходимости.
"""

import os
import sys
import logging
from typing import Optional
from dotenv import load_dotenv
from google.cloud import bigquery
from supabase import create_client, Client

# --- Настройки ---
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
BQ_PROJECT = os.getenv("BQ_PROJECT", "family-market-analytics")
BQ_DATASET = os.getenv("BQ_DATASET", "family_market")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    sys.exit("❌ Не заданы SUPABASE_URL или SUPABASE_SERVICE_KEY в .env")

# --- Логирование ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# --- Клиенты ---
bq = bigquery.Client(project=BQ_PROJECT)
sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# =====================================================
#  1. Классификация точек поставки
# =====================================================
def classify_delivery_point(store_name: str) -> str:
    """Возвращает значение для delivery_point_type_enum."""
    s = store_name.lower().strip()
    if "полевая-склад" in s or s == "склад":
        return "rc"
    if "полевая-магазин" in s or "опт" in s:
        return "wholesale"
    if "производство" in s or "виробництво" in s:
        return "production"
    return "store"


# =====================================================
#  2. Выгрузка магазинов из BigQuery (приходы + возвраты)
# =====================================================
def fetch_stores_from_bq() -> list[dict]:
    log.info("📥 Выгружаю список магазинов из BigQuery...")
    query = f"""
        SELECT store AS name, COUNT(*) AS cnt
        FROM (
          SELECT store FROM `{BQ_PROJECT}.{BQ_DATASET}.incoming_transactions`
          UNION ALL
          SELECT store FROM `{BQ_PROJECT}.{BQ_DATASET}.outgoing_to_supplier_transactions`
        )
        WHERE store IS NOT NULL AND TRIM(store) != ''
        GROUP BY store
        ORDER BY cnt DESC
    """
    rows = list(bq.query(query).result())
    stores = [{"name": r.name.strip(), "cnt": r.cnt} for r in rows]
    log.info(f"   Найдено магазинов: {len(stores)}")
    return stores


# =====================================================
#  3. Выгрузка поставщиков из BigQuery
# =====================================================
def fetch_suppliers_from_bq() -> list[dict]:
    log.info("📥 Выгружаю список поставщиков из BigQuery...")
    query = f"""
        SELECT supplier AS name,
               COUNT(*) AS cnt,
               ROUND(SUM(amount_purchase), 2) AS total_purchase
        FROM (
          SELECT supplier, amount_purchase
          FROM `{BQ_PROJECT}.{BQ_DATASET}.incoming_transactions`
          UNION ALL
          SELECT supplier, amount_purchase
          FROM `{BQ_PROJECT}.{BQ_DATASET}.outgoing_to_supplier_transactions`
        )
        WHERE supplier IS NOT NULL AND TRIM(supplier) != ''
        GROUP BY supplier
        ORDER BY total_purchase DESC NULLS LAST
    """
    rows = list(bq.query(query).result())
    suppliers = [
        {"name": r.name.strip(), "cnt": r.cnt, "total_purchase": float(r.total_purchase or 0)}
        for r in rows
    ]
    log.info(f"   Найдено поставщиков: {len(suppliers)}")
    return suppliers


# =====================================================
#  4. Заливка delivery_points в Supabase (UPSERT)
# =====================================================
def upsert_delivery_points(stores: list[dict]) -> None:
    log.info("📤 Заливаю delivery_points в Supabase...")
    rows = []
    for s in stores:
        rows.append({
            "name": s["name"],
            "type": classify_delivery_point(s["name"]),
            "notes": f"Импортировано из BigQuery, транзакций: {s['cnt']}",
        })

    # ON CONFLICT (name) DO NOTHING — uniqueness гарантируется constraint'ом
    res = sb.table("delivery_points").upsert(
        rows, on_conflict="name", ignore_duplicates=True
    ).execute()

    log.info(f"   ✓ Обработано: {len(rows)} (новых вставлено: {len(res.data)})")

    # Сводка по типам
    types_count: dict[str, int] = {}
    for r in rows:
        types_count[r["type"]] = types_count.get(r["type"], 0) + 1
    log.info(f"   Распределение по типам: {types_count}")


# =====================================================
#  5. Заливка suppliers + supplier_aliases (UPSERT)
# =====================================================
def upsert_suppliers_and_aliases(suppliers: list[dict]) -> None:
    log.info("📤 Заливаю suppliers и supplier_aliases в Supabase...")

    # Шаг 1. Заливаем поставщиков
    supplier_rows = []
    for s in suppliers:
        supplier_rows.append({
            "name": s["name"],
            "is_retro_active": True,
            "notes": f"Импортировано из BigQuery, оборот: {s['total_purchase']:.2f} грн",
        })

    sb.table("suppliers").upsert(
        supplier_rows, on_conflict="name", ignore_duplicates=True
    ).execute()

    # Шаг 2. Получаем актуальный маппинг name -> id
    res = sb.table("suppliers").select("id, name").execute()
    name_to_id = {r["name"]: r["id"] for r in res.data}
    log.info(f"   ✓ В suppliers сейчас: {len(name_to_id)} записей")

    # Шаг 3. Заливаем алиасы (alias_name = name из BigQuery)
    alias_rows = []
    for s in suppliers:
        sid = name_to_id.get(s["name"])
        if not sid:
            log.warning(f"   ⚠ Не найден id для {s['name']}, пропускаю алиас")
            continue
        alias_rows.append({
            "supplier_id": sid,
            "alias_name": s["name"],
            "source": "torgsoft",
            "notes": "Авто-алиас из BigQuery (имя совпадает с каноническим)",
        })

    sb.table("supplier_aliases").upsert(
        alias_rows, on_conflict="alias_name", ignore_duplicates=True
    ).execute()
    log.info(f"   ✓ Обработано алиасов: {len(alias_rows)}")


# =====================================================
#  6. Проверка результата
# =====================================================
def verify() -> None:
    log.info("🔍 Проверка содержимого Supabase...")
    dp = sb.table("delivery_points").select("id", count="exact").execute()
    sup = sb.table("suppliers").select("id", count="exact").execute()
    al = sb.table("supplier_aliases").select("id", count="exact").execute()
    log.info(f"   delivery_points:   {dp.count}")
    log.info(f"   suppliers:         {sup.count}")
    log.info(f"   supplier_aliases:  {al.count}")


# =====================================================
#  Main
# =====================================================
def main() -> None:
    log.info("=" * 60)
    log.info("🚀 Миграция справочников BigQuery → Supabase")
    log.info("=" * 60)

    stores = fetch_stores_from_bq()
    suppliers = fetch_suppliers_from_bq()

    if not stores and not suppliers:
        log.error("❌ Нет данных в BigQuery, выхожу")
        return

    # Превью
    log.info(f"\n📋 Превью первых 5 магазинов:")
    for s in stores[:5]:
        log.info(f"   {s['name']:<35} | {classify_delivery_point(s['name']):<10} | {s['cnt']} транз.")
    log.info(f"\n📋 Превью первых 5 поставщиков:")
    for s in suppliers[:5]:
        log.info(f"   {s['name']:<45} | {s['total_purchase']:>15,.2f} грн")

    confirm = input("\n❓ Заливаем в Supabase? (y/n): ").strip().lower()
    if confirm != "y":
        log.info("Отменено.")
        return

    upsert_delivery_points(stores)
    upsert_suppliers_and_aliases(suppliers)
    verify()
    log.info("\n✅ Готово!")


if __name__ == "__main__":
    main()

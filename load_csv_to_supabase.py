"""
Загрузка справочников из CSV в Supabase.
Этап 1: suppliers + supplier_brands
Этап 2 (отдельно, после Block 6 DDL): retro_rules
"""
import os
import csv
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
if not SUPABASE_URL or not SUPABASE_KEY:
    raise SystemExit("Не заданы SUPABASE_URL / SUPABASE_SERVICE_KEY в .env")

OUTPUT_DIR = Path(r"D:\РЕТРО_БОНУСЫ Фэмэли маркет\output")
SUPPLIERS_CSV = OUTPUT_DIR / 'suppliers.csv'
BRANDS_CSV = OUTPUT_DIR / 'supplier_brands.csv'

sb = create_client(SUPABASE_URL, SUPABASE_KEY)


def to_bool(v) -> bool:
    return str(v).strip().lower() in ('true', '1', 'yes', 'да')


def load_suppliers_csv():
    rows = []
    with SUPPLIERS_CSV.open('r', encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            rows.append({
                'name': r['name'].strip(),
                'is_retro_active': to_bool(r['is_retro_active']),
                'notes': (r.get('notes') or '').strip() or None,
            })
    return rows


def load_brands_csv():
    rows = []
    with BRANDS_CSV.open('r', encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            rows.append({
                'supplier_name': r['supplier_name'].strip(),
                'brand_name': r['brand_name'].strip(),
                'is_retro_active': to_bool(r['is_retro_active']),
                'notes': '; '.join(filter(None, [
                    f"original: {r['original_name']}" if r.get('original_name') else None,
                    f"suffix: {r['suffix']}" if r.get('suffix') else None,
                    f"categories: {r['categories']}" if r.get('categories') else None,
                    f"delivery: {r['delivery']}" if r.get('delivery') else None,
                ])) or None,
                'retro_description': '; '.join(filter(None, [
                    f"retro: {r['retro_raw']}" if r.get('retro_raw') else None,
                    f"discount: {r['discount']}" if r.get('discount') else None,
                    f"note: {r['note']}" if r.get('note') else None,
                    f"extra: {r['extra']}" if r.get('extra') else None,
                ])) or None,
            })
    return rows


def upsert_suppliers(rows):
    print(f"\n=== UPSERT suppliers ({len(rows)}) ===")
    res = sb.table('suppliers').upsert(
        rows, on_conflict='name', ignore_duplicates=False
    ).execute()
    print(f"  загружено: {len(res.data)}")
    # вернуть карту name -> id
    all_rows = sb.table('suppliers').select('id,name').execute().data
    return {r['name']: r['id'] for r in all_rows}


def upsert_brands(rows, supplier_id_map):
    print(f"\n=== UPSERT supplier_brands ({len(rows)}) ===")
    payload = []
    skipped = []
    for r in rows:
        sid = supplier_id_map.get(r['supplier_name'])
        if not sid:
            skipped.append(r['supplier_name'])
            continue
        payload.append({
            'supplier_id': sid,
            'name': r['brand_name'],
            'is_retro_active': r['is_retro_active'],
            'notes': r['notes'],
            'retro_description': r['retro_description'],
        })
    if skipped:
        print(f"  ПРОПУЩЕНО (нет supplier): {len(skipped)} -> {set(skipped)}")
    
    # Supabase ограничивает batch ~1000, но у нас 158 — грузим разом
    res = sb.table('supplier_brands').upsert(
        payload, on_conflict='supplier_id,name', ignore_duplicates=False
    ).execute()
    print(f"  загружено: {len(res.data)}")


def verify():
    print("\n=== VERIFY ===")
    for tbl in ('suppliers', 'supplier_brands'):
        cnt = sb.table(tbl).select('id', count='exact').execute()
        print(f"  {tbl}: {cnt.count} строк")


def preview(suppliers, brands):
    print(f"\nЧитаем CSV:")
    print(f"  suppliers.csv:        {len(suppliers)} строк")
    print(f"  supplier_brands.csv:  {len(brands)} строк")
    
    print("\n--- Первые 5 поставщиков ---")
    for s in suppliers[:5]:
        flag = "✓ретро" if s['is_retro_active'] else "—"
        print(f"  {flag:10s} {s['name']}")
    
    print("\n--- Первые 5 брендов ---")
    for b in brands[:5]:
        flag = "✓" if b['is_retro_active'] else "—"
        print(f"  {flag} {b['supplier_name']:30s} → {b['brand_name']}")
    
    suppliers_with_retro = sum(1 for s in suppliers if s['is_retro_active'])
    brands_with_retro = sum(1 for b in brands if b['is_retro_active'])
    print(f"\n  Поставщиков с ретро: {suppliers_with_retro} / {len(suppliers)}")
    print(f"  Брендов с ретро:     {brands_with_retro} / {len(brands)}")


def main():
    suppliers = load_suppliers_csv()
    brands = load_brands_csv()
    preview(suppliers, brands)
    
    print()
    answer = input("Загрузить в Supabase? (y/n): ").strip().lower()
    if answer != 'y':
        print("Отмена.")
        return
    
    supplier_id_map = upsert_suppliers(suppliers)
    upsert_brands(brands, supplier_id_map)
    verify()
    print("\nГотово.")


if __name__ == '__main__':
    main()

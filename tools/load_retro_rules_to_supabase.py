"""
Загрузка категорий и черновика правил ретро в Supabase.

Шаги:
1. Переименование (СТВ Схід) Якобз -> Якобз кофе аппараты
2. UPSERT product_categories (25 категорий с маппингом RU->EN)
3. UPSERT supplier_brand_categories (связи M:N)
4. UPSERT retro_rules из retro_rules_draft.csv
   (Якобс / Якобз кофе аппараты пропускаются — добавим вручную)
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
BRANDS_CSV = OUTPUT_DIR / 'supplier_brands.csv'
RULES_CSV = OUTPUT_DIR / 'retro_rules_draft.csv'

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- маппинги ----------

# Маппинг русских категорий в канонические английские коды
CATEGORY_MAP = {
    'Пресервы':                    'fish',
    'Хозтовары':                   'chem',
    'Фаст Фуд':                    'fastfood',
    'Фаст-фуд':                    'fastfood',
    'Еда быстрого приготовления':  'fastfood',
    'С/А Напитки':                 'softdrinks',
    'Орехи и сухофрукты':          'nuts',
    'Вода разлив':                 'water',
    'Яйца':                        'eggs',
    'Соления':                     'pickles',
}

# Все категории (английские коды) с человекочитаемым названием
CATEGORIES = [
    ('candy',      'Кондитерка',                1),
    ('alcohol',    'Алкоголь',                  2),
    ('grocery',    'Бакалея',                   3),
    ('snacks',     'Снеки',                     4),
    ('coffee',     'Кофе/Чай',                  5),
    ('hygiene',    'Гигиена',                   6),
    ('pet',        'Зоотовары',                 7),
    ('water',      'Вода',                      8),
    ('beer',       'Пиво',                      9),
    ('chem',       'Бытовая химия',            10),
    ('dairy',      'Молочка',                  11),
    ('juice',      'Соки',                     12),
    ('frozen',     'Заморозка/Мороженое',      13),
    ('meat',       'Мясо/Колбасы',             14),
    ('bread',      'Хлеб/Выпечка',             15),
    ('fish',       'Рыба/Пресервы',            16),
    ('tobacco',    'Табак',                    17),
    ('veg',        'Овощи и фрукты',           18),
    ('sauce',      'Соусы',                    19),
    ('fastfood',   'Фастфуд',                  20),
    ('softdrinks', 'Сильно/слабоалкогольные', 21),
    ('nuts',       'Орехи и сухофрукты',       22),
    ('eggs',       'Яйца',                     23),
    ('pickles',    'Соления',                  24),
    ('pack',       'Упаковка/Пакеты',          25),
    ('other',      'Прочее',                   99),
]

# Маппинг канала доставки
DELIVERY_MAP = {
    'РЦ':      'rc',
    'ТТ':      'direct_to_store',
    'Прямая':  'direct_to_store',
    '':        None,
}

# Бренды, которые пропускаем — для них правила добавим вручную с per_portion_sold
SKIP_BRANDS = {
    ('Якобс', 'Кофе апараты'),
    ('СТВ Схід', 'Якобз кофе аппараты'),  # уже после переименования
    ('СТВ Схід', 'Якобз'),                # на случай если ещё не переименовали
}


def to_bool(v) -> bool:
    return str(v).strip().lower() in ('true', '1', 'yes', 'да')


def parse_num(v):
    """Превращает '0.1', '9.5', '' в float или None."""
    if v is None or str(v).strip() == '':
        return None
    try:
        return float(str(v).strip().replace(',', '.'))
    except ValueError:
        return None


def parse_categories_field(field_value: str) -> list:
    """'candy, alcohol, Пресервы' -> ['candy', 'alcohol', 'fish']"""
    if not field_value:
        return []
    out = set()
    for raw in field_value.split(','):
        c = raw.strip()
        if not c:
            continue
        # маппим RU -> EN
        c_mapped = CATEGORY_MAP.get(c, c)
        out.add(c_mapped)
    return sorted(out)


# ---------- шаги ----------

def step_rename_yakobz():
    print("\n=== ШАГ 1: переименование (СТВ Схід) Якобз -> Якобз кофе аппараты ===")
    # Найдём supplier_id СТВ Схід
    sup = sb.table('suppliers').select('id').eq('name', 'СТВ Схід').execute()
    if not sup.data:
        print("  ! Поставщик 'СТВ Схід' не найден, пропускаем")
        return
    sup_id = sup.data[0]['id']
    
    # Найдём бренд "Якобз" и переименуем
    res = sb.table('supplier_brands') \
        .update({'name': 'Якобз кофе аппараты'}) \
        .eq('supplier_id', sup_id) \
        .eq('name', 'Якобз') \
        .execute()
    if res.data:
        print(f"  ✓ переименовано: {len(res.data)} запись(ей)")
    else:
        print("  - бренд 'Якобз' уже переименован или не найден")


def step_load_categories():
    print(f"\n=== ШАГ 2: UPSERT product_categories ({len(CATEGORIES)}) ===")
    payload = [{
        'code': code,
        'name_ru': name_ru,
        'name_ua': None,
        'sort_order': sort_order,
    } for code, name_ru, sort_order in CATEGORIES]
    res = sb.table('product_categories').upsert(
        payload, on_conflict='code', ignore_duplicates=False
    ).execute()
    print(f"  загружено: {len(res.data)}")
    
    # Получаем карту code -> id
    all_cats = sb.table('product_categories').select('id,code').execute().data
    return {c['code']: c['id'] for c in all_cats}


def step_load_brand_categories(category_id_map):
    print("\n=== ШАГ 3: UPSERT supplier_brand_categories ===")
    
    # Загружаем все бренды из БД -> карта (supplier_name, brand_name) -> brand_id
    brands_db = sb.table('supplier_brands') \
        .select('id,name,suppliers(name)') \
        .execute().data
    brand_map = {}
    for b in brands_db:
        sup_name = b['suppliers']['name']
        # на случай, если переименование Якобз уже прошло
        brand_map[(sup_name, b['name'])] = b['id']
    print(f"  брендов в БД: {len(brand_map)}")
    
    # Читаем CSV и собираем связки
    pairs = []
    skipped_brands = set()
    skipped_cats = set()
    seen = set()  # для дедупликации (brand_id, cat_id)
    
    with BRANDS_CSV.open('r', encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            sup_name = r['supplier_name'].strip()
            brand_name = r['brand_name'].strip()
            
            # Учитываем переименование Якобз
            if (sup_name, brand_name) == ('СТВ Схід', 'Якобз'):
                brand_name = 'Якобз кофе аппараты'
            
            brand_id = brand_map.get((sup_name, brand_name))
            if not brand_id:
                skipped_brands.add((sup_name, brand_name))
                continue
            
            cats = parse_categories_field(r['categories'])
            for cat_code in cats:
                cat_id = category_id_map.get(cat_code)
                if not cat_id:
                    skipped_cats.add(cat_code)
                    continue
                key = (brand_id, cat_id)
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({'supplier_brand_id': brand_id, 'category_id': cat_id})
    
    if skipped_brands:
        print(f"  ! пропущены бренды (нет в БД): {len(skipped_brands)}")
        for s, b in list(skipped_brands)[:5]:
            print(f"      {s} -> {b}")
    if skipped_cats:
        print(f"  ! пропущены категории: {skipped_cats}")
    
    if not pairs:
        print("  нечего загружать")
        return
    
    res = sb.table('supplier_brand_categories').upsert(
        pairs, on_conflict='supplier_brand_id,category_id', ignore_duplicates=True
    ).execute()
    print(f"  загружено связок: {len(pairs)} (вернулось от API: {len(res.data)})")


def step_load_retro_rules():
    print("\n=== ШАГ 4: UPSERT retro_rules ===")
    
    # Карта (supplier_name, brand_name) -> brand_id
    brands_db = sb.table('supplier_brands') \
        .select('id,name,suppliers(name)') \
        .execute().data
    brand_map = {(b['suppliers']['name'], b['name']): b['id'] for b in brands_db}
    
    payload = []
    skipped_yakobz = []
    skipped_unknown = []
    
    with RULES_CSV.open('r', encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            sup_name = r['supplier_name'].strip()
            brand_name = r['brand_name'].strip()
            
            # Учитываем переименование
            if (sup_name, brand_name) == ('СТВ Схід', 'Якобз'):
                brand_name = 'Якобз кофе аппараты'
            
            # Пропуск Якобса/Якобз — добавим вручную
            if (sup_name, brand_name) in SKIP_BRANDS:
                skipped_yakobz.append((sup_name, brand_name))
                continue
            
            brand_id = brand_map.get((sup_name, brand_name))
            if not brand_id:
                skipped_unknown.append((sup_name, brand_name))
                continue
            
            delivery_raw = (r.get('delivery') or '').strip()
            delivery_channel = DELIVERY_MAP.get(delivery_raw)
            
            payload.append({
                'supplier_brand_id':    brand_id,
                'valid_from':           '2026-01-01',
                'valid_to':             None,
                'retro_min':            parse_num(r.get('retro_min')),
                'retro_max':            parse_num(r.get('retro_max')),
                'retro_raw':            r.get('retro_raw') or None,
                'retro_base_type':      'shipment_minus_return',
                'retro_amount_field':   'amount_purchase',
                'discount_percent':     parse_num(r.get('discount')),
                'delivery_channel':     delivery_channel,
                'returns_allowed':      r.get('returns_allowed') or None,
                'notes':                r.get('note') or None,
                'extra_conditions':     r.get('extra') or None,
                'status':               'draft',
                'source':               'html_2026',
                'source_num':           r.get('num_html') or None,
            })
    
    if skipped_yakobz:
        print(f"  ! пропущено Якобс/Якобз: {len(skipped_yakobz)} (добавим вручную)")
        for s, b in skipped_yakobz:
            print(f"      {s} -> {b}")
    if skipped_unknown:
        print(f"  ! пропущено бренды без brand_id: {len(skipped_unknown)}")
        for s, b in skipped_unknown[:10]:
            print(f"      {s} -> {b}")
    
    if not payload:
        print("  нечего загружать")
        return
    
    # retro_rules не имеет UNIQUE на пару (brand, period), поэтому просто INSERT
    res = sb.table('retro_rules').insert(payload).execute()
    print(f"  загружено правил: {len(res.data)}")


def step_verify():
    print("\n=== ШАГ 5: ПРОВЕРКА ===")
    for tbl in ('product_categories', 'supplier_brand_categories', 'retro_rules'):
        cnt = sb.table(tbl).select('id', count='exact').execute()
        print(f"  {tbl}: {cnt.count}")


def main():
    print("Загрузка категорий и черновика правил ретро в Supabase")
    print("=" * 60)
    
    answer = input("\nПродолжить? (y/n): ").strip().lower()
    if answer != 'y':
        print("Отмена.")
        return
    
    step_rename_yakobz()
    cat_map = step_load_categories()
    step_load_brand_categories(cat_map)
    step_load_retro_rules()
    step_verify()
    
    print("\nГотово.")


if __name__ == '__main__':
    main()

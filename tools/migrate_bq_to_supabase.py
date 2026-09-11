"""
Миграция справочников из BigQuery в Supabase.
- delivery_points + delivery_point_aliases из store_mapping + store_info
- supplier_aliases + unmapped_suppliers из supplier_mapping + dc_returns.supplier_aliases
"""
import os
import re
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import bigquery
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
BQ_PROJECT = os.getenv('BQ_PROJECT', 'family-market-analytics')
GCP_CREDS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise SystemExit("Не заданы SUPABASE_URL / SUPABASE_SERVICE_KEY в .env")
if not GCP_CREDS or not Path(GCP_CREDS).exists():
    raise SystemExit(f"Не найден GOOGLE_APPLICATION_CREDENTIALS: {GCP_CREDS}")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)
bq = bigquery.Client(project=BQ_PROJECT)

UNMAPPED_THRESHOLD = 100

# Технический мусор — не мапим, не автосоздаём, в unmapped попадает с пометкой
TECHNICAL_NAMES = {
    'Магазин', 'ПОСТАВЩИК', 'Поставщик', 'магазин',
    'Неизвестный', 'Не визначено',
    'ПРИХОД ПРОДУКЦИИ С ПРОИЗВОДСТВА',
}
# Выведенные поставщики (товара больше нет, в БД не создавать, в unmapped с пометкой)
DEPRECATED_NAMES = {
    'Авангард продукти',
    'ТОВ Кафе Ярославское',
    'Данон',
    'Свіфт',
    'Безлюдовський МК',
    'Безлюдівський М*ясокомбінат',
    'Укркорн',
    'Чумак',
    'Хлібний Двір',
    'Боніта',
    'Айсберг',
    'Бейкері Фуд',
    'Євромікс',
    'Кузя Сервіс',
    'ДДС+',
    'Левітрейд',
    'Асканія',
    'Пакети',
    'Не визначено',
    'Інтрейд(ЧАЇ)',     # ← НОВОЕ
    'Артефіс Плюс',     # ← НОВОЕ
}

# Поставщики, которые нужно создать ДО маппинга оверрайдов
PRECREATE_SUPPLIERS = [
    {'name': 'Юрія', 'is_retro_active': False,
     'notes': 'auto-created: молочка (Волошкове Поле, Хмельницька Маслосирбаза)'},
]

# Ручные сопоставления raw_name → supplier (или supplier+brand)
MANUAL_OVERRIDES = {
    # === Авангард Дистрибуції ===
    'Авангард':                  {'supplier': 'Авангард Дистрибуції'},
    'Авангард ваговий':          {'supplier': 'Авангард Дистрибуції'},

    # === Арсенал ПК / Шейк ===
    'Шейки':                     {'supplier': 'Арсенал ПК', 'brand': 'Шейк'},

    # === Баядера ===
    'Хлібний Дар (Еліт)':        {'supplier': 'Баядера', 'brand': 'Хлебный дар'},
    'Баядера':                   {'supplier': 'Баядера'},

    # === Інтрейд Мікс ===
    'Інтрейд':                   {'supplier': 'Інтрейд Мікс'},
    'Корм Інтрейд':              {'supplier': 'Інтрейд Мікс', 'brand': 'Корма Клуб 4 Лапы'},

    # === СТВ Схід ===
    'Кава Апарат':               {'supplier': 'СТВ Схід', 'brand': 'Якобз кофе аппараты'},
    'Бащінський МК':             {'supplier': 'СТВ Схід', 'brand': 'Наша Ряба'},
    'ПП Торговий Дім СМК Груп':  {'supplier': 'СТВ Схід', 'brand': 'Наша Ряба'},
    'СМК ГРУП':                  {'supplier': 'СТВ Схід', 'brand': 'Наша Ряба'},

    # === Форвард-св ===
    'Форвард':                   {'supplier': 'Форвард-св'},

    # === Глобинський М'ясокомбінат ===
    'Глобино МК':                {'supplier': "Глобинський М'ясокомбінат"},
    'Глобино':                   {'supplier': "Глобинський М'ясокомбінат"},

    # === ДЛ Солюшн (есть в БД) ===
    'ДЛ Солюшн':                 {'supplier': 'ДЛ Солюшн'},

    # === ЧП Рома ===
    'Рома':                      {'supplier': 'ЧП Рома'},

    # === Хладопром ===
    'Хладопром':                 {'supplier': 'Хладопром'},

    # === Лютсдорф / Селянське ===
    'Люстдорф':                  {'supplier': 'Лютсдорф', 'brand': 'Селянське'},

    # === Юрія (молочка) ===
    'Юрія':                      {'supplier': 'Юрія'},
    'Хмельницька Маслосирбаза':  {'supplier': 'Юрія'},

    # === Гармідова / Сулугуні ===
    'СУЛУГУНІ':                  {'supplier': 'Гармідова', 'brand': 'Сулугуні Ф2'},

    # === ФКК Авангард ЛТД (яйце) ===
    'Яйце':                      {'supplier': 'ФКК Авангард ЛТД', 'brand': 'Яйце куриное'},

    # === Кріофудтрейд ===
    'Кріофудтрейд':              {'supplier': 'Кріофудтрейд'},
    'Водний світ':               {'supplier': 'Кріофудтрейд'},

    # === АСК / Мон Шер (предсоздаются) ===
    'АСК':                       {'supplier': 'ТОВ Кондитерська Фабрика АСК'},
    'Мон Шер':                   {'supplier': 'ТОВ Мон Шер'},


    # === САВСЕРВІС-МОВА ===
    'САВСЕРВІС-МОВА':            {'supplier': 'САВСЕРВІС-МОВА'},

    # === Алко Трейдінг ===
    'Алко Трейдінг':             {'supplier': 'Алко Трейдінг'},
    'Трейдінг Продакт Компані':  {'supplier': 'Алко Трейдінг', 'brand': 'Медофф'},

    # === ФОП Кирьяк ===
    "ФОП Кір'як О.С.":           {'supplier': 'ФОП Кирьяк'},
    'ФОП Кір*як О.С.':           {'supplier': 'ФОП Кирьяк'},

    # === ТОВ Галиция (ФОП Матіїв) ===
    'ФОП Матіїв Оксана Володиміровна': {'supplier': 'ТОВ Галиция'},

    # === БІР (кеговое пиво) ===
    'Фізична Особа-Підприємець Нікітенко Роман Васильович': {'supplier': 'БІР'},
    # === ЮМК-ПЛАСТ ===
'ЮМК-ПЛАСТ':                 {'supplier': 'ЮМК-ПЛАСТ'},
# === УДК (вариант написания УТДК) ===
'УДК': {'supplier': 'Українська Торгова Дистрибуційна Компанія'},

# === Артефіс Плюс — на вывод ===
'Артефіс Плюс': None,  # ← но MANUAL_OVERRIDES не поддерживает None,
                       # см. ниже — добавим в DEPRECATED_NAMES вместо этого

# === Прат Охтирський Пивоварний завод ===
'Прат Охтирський Пивоварний завод': {'supplier': 'Прат Охтирський Пивоварний завод', 'brand': 'Пиво Охтирське'},
'Прат Охтирський пивоварний завод': {'supplier': 'Прат Охтирський Пивоварний завод', 'brand': 'Пиво Охтирське'},

}

# Переопределение canonical из dc_returns
CANONICAL_OVERRIDES = {
    # уже было
    'Бащінський МК':    {'supplier': 'СТВ Схід', 'brand': 'Наша Ряба'},
    'Глобино МК':       {'supplier': "Глобинський М'ясокомбінат"},
    'Хлібний Дар':      {'supplier': 'Баядера', 'brand': 'Хлебный дар'},

    # выведенные
    'Айсберг':          None,
    'Євромікс':         None,
    'Чумак':            None,
    'Хлібний Двір':     None,
    'Боніта':           None,
    'Бейкері Фуд':      None,
    'Кузя Сервіс':      None,
    'ДДС+':             None,
    'Левітрейд':        None,
    'Асканія':          None,
    'Пакети':           None,
    'Не визначено':     None,
    'Інтрейд(ЧАЇ)':     None,     # ← НОВОЕ
    'Артефіс Плюс':     None,     # ← НОВОЕ

    # сегменты BQ → реальные поставщики
    'Авангард':         {'supplier': 'Авангард Дистрибуції'},
    'Авангард ваговий': {'supplier': 'Авангард Дистрибуції'},
    'Шейки':            {'supplier': 'Арсенал ПК', 'brand': 'Шейк'},
    'Інтрейд':          {'supplier': 'Інтрейд Мікс'},
    'СУЛУГУНІ':         {'supplier': 'Гармідова', 'brand': 'Сулугуні Ф2'},
    'Кава Апарат':      {'supplier': 'СТВ Схід', 'brand': 'Якобз кофе аппараты'},
    'Яйце':             {'supplier': 'ФКК Авангард ЛТД', 'brand': 'Яйце куриное'},
    'Корм Інтрейд':     {'supplier': 'Інтрейд Мікс', 'brand': 'Корма Клуб 4 Лапы'},
    'Форвард':          {'supplier': 'Форвард-св'},
    'Овочі-Фрукти':     {'supplier': 'Тропік', 'brand': 'Овощи и фрукты'},
    'Соління':          {'supplier': 'ФОП Кабанов М.Ю.', 'brand': 'Соления'},
    'Риба':             {'supplier': 'ФОП Кульомза Роман Миколайович', 'brand': 'рыба копч.'},
    'Броварня':         {'supplier': 'ТОВ Рідна марка', 'brand': 'Перша приватна броварня'},
    'Комо':             {'supplier': 'Сирний Дім', 'brand': 'Комо сыры'},
    'Укркремопт':       {'supplier': 'Укр-Крем-Опт'},
    'УДК':              {'supplier': 'Українська Торгова Дистрибуційна Компанія'},  # ← НОВОЕ
    'Ресурс':           {'supplier': 'Продресурс ЛТД'},
    'Кегове Бір Хаус':  {'supplier': 'Прометал', 'brand': 'Бир Хаус пиво кеговое и сидры'},
    'Пиво Охтирське':   {'supplier': 'Прат Охтирський Пивоварний завод', 'brand': 'Пиво Охтирське'},
}


# ============================================================
# ШАГ 1. delivery_points + delivery_point_aliases
# ============================================================

def fetch_stores_from_bq():
    sql = f"""
    SELECT sm.store_original, sm.store_normalized, sm.is_active,
           si.opened_date, si.last_transaction, si.days_active
    FROM `{BQ_PROJECT}.family_market.store_mapping` sm
    LEFT JOIN `{BQ_PROJECT}.family_market.store_info` si
      ON si.store = sm.store_normalized
    """
    return [dict(r) for r in bq.query(sql).result()]


def migrate_stores(stores, dry_run=True):
    # Группируем точки по нормализованному имени
    points = {}
    for s in stores:
        norm = s['store_normalized']
        if norm not in points:
            points[norm] = {
                'name': norm,
                'is_active': s['is_active'],
                'opened_date': s.get('opened_date'),
                'last_transaction': s.get('last_transaction'),
                'aliases': set(),
            }
        if s['store_original'] and s['store_original'] != norm:
            points[norm]['aliases'].add(s['store_original'])

    print(f"\n=== ШАГ 1. delivery_points ===")
    print(f"Уникальных точек: {len(points)}")
    active = sum(1 for p in points.values() if p['is_active'])
    aliases_count = sum(len(p['aliases']) for p in points.values())
    print(f"Активных: {active}, алиасов: {aliases_count}")

    print(f"\n--- Превью точек (первые 5) ---")
    for name, p in list(points.items())[:5]:
        print(f"  {name} (active={p['is_active']}, aliases={list(p['aliases'])})")

    if dry_run:
        return

    payload = []
    for name, p in points.items():
        opened = p.get('opened_date')
        last_tx = p.get('last_transaction')
        payload.append({
            'name': name,
            'type': 'store',
            'is_active': p['is_active'],
            'opened_at': opened.isoformat() if opened else None,
            'last_transaction_at': last_tx.isoformat() if last_tx else None,
        })
    sb.table('delivery_points').upsert(payload, on_conflict='name').execute()

    all_dp = sb.table('delivery_points').select('id,name').execute().data
    dp_map = {r['name']: r['id'] for r in all_dp}

    alias_payload = []
    for name, p in points.items():
        dp_id = dp_map.get(name)
        if not dp_id:
            continue
        for alias in p['aliases']:
            alias_payload.append({
                'delivery_point_id': dp_id,
                'alias_name': alias,
                'source': 'bq_store_mapping',
            })
    if alias_payload:
        sb.table('delivery_point_aliases').upsert(alias_payload, on_conflict='alias_name').execute()

    print(f"Загружено: {len(payload)} точек, {len(alias_payload)} алиасов")


# ============================================================
# ШАГ 2. supplier_aliases + unmapped_suppliers
# ============================================================

def fetch_suppliers_from_bq():
    sql_mapping = f"""
    SELECT incoming_supplier, matrix_supplier
    FROM `{BQ_PROJECT}.family_market.supplier_mapping`
    """
    sql_dc = f"""
    SELECT raw_supplier, canonical, notes
    FROM `{BQ_PROJECT}.dc_returns.supplier_aliases`
    """
    sql_counts = f"""
    SELECT supplier AS supplier_name,
           COUNT(*) AS tx_count,
           SUM(amount_purchase) AS total_purchase,
           MIN(doc_date) AS first_date,
           MAX(doc_date) AS last_date
    FROM `{BQ_PROJECT}.family_market.incoming_transactions`
    WHERE supplier IS NOT NULL
    GROUP BY supplier
    """
    mapping = [dict(r) for r in bq.query(sql_mapping).result()]
    dc = [dict(r) for r in bq.query(sql_dc).result()]
    counts = {r['supplier_name']: dict(r) for r in bq.query(sql_counts).result()}
    return mapping, dc, counts


def build_brand_lookup():
    suppliers = sb.table('suppliers').select('id,name').execute().data
    brands = sb.table('supplier_brands').select('id,name,supplier_id').execute().data
    sup_map = {s['name']: s['id'] for s in suppliers}
    brand_by_name = {}
    brand_by_supplier = defaultdict(list)
    for b in brands:
        brand_by_name[b['name']] = b
        brand_by_supplier[b['supplier_id']].append(b)
    return sup_map, brand_by_name, brand_by_supplier


def normalize(s):
    if not s:
        return ''
    s = s.lower()
    s = s.translate(str.maketrans({
        'і': 'и', 'ї': 'и', 'є': 'е', 'ё': 'е', 'ъ': '', 'ь': '',
        '*': '', "'": '', '`': '', '"': '',
    }))
    s = re.sub(r'\([^)]*\)', '', s)
    s = re.sub(r'[-\s]+(опт|мк|тд|тзов|тов|пп|фоп|чп|кф|пвкф)\b', '', s)
    s = re.sub(r'[-_]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def find_supplier_or_brand(canonical, sup_map, brand_by_name, raw_name=None):
    # 0. Ручной оверрайд по raw_name
    if raw_name and raw_name in MANUAL_OVERRIDES:
        ov = MANUAL_OVERRIDES[raw_name]
        sid = sup_map.get(ov['supplier'])
        bid = None
        if 'brand' in ov and sid:
            for name, b in brand_by_name.items():
                if name == ov['brand'] and b['supplier_id'] == sid:
                    bid = b['id']; break
        if sid:
            return sid, bid
        return None, None

    # 0.5 Оверрайд canonical (из dc_returns)
    if canonical and canonical in CANONICAL_OVERRIDES:
        ov = CANONICAL_OVERRIDES[canonical]
        if ov is None:
            return None, None  # принудительно в unmapped
        sid = sup_map.get(ov['supplier'])
        bid = None
        if 'brand' in ov and sid:
            for name, b in brand_by_name.items():
                if name == ov['brand'] and b['supplier_id'] == sid:
                    bid = b['id']; break
        if sid:
            return sid, bid
        return None, None

    if not canonical:
        return None, None
    # 1. Точное совпадение с поставщиком
    if canonical in sup_map:
        return sup_map[canonical], None
    # 2. Точное совпадение с брендом
    if canonical in brand_by_name:
        b = brand_by_name[canonical]
        return b['supplier_id'], b['id']
    # 3. Fuzzy
    norm = normalize(canonical)
    if not norm:
        return None, None
    for name, sid in sup_map.items():
        if normalize(name) == norm:
            return sid, None
    for name, b in brand_by_name.items():
        if normalize(name) == norm:
            return b['supplier_id'], b['id']
    return None, None


def migrate_suppliers(mapping, dc, counts, dry_run=True):
    # Предсоздание поставщиков для оверрайдов (только при реальной загрузке)
    if not dry_run and PRECREATE_SUPPLIERS:
        sb.table('suppliers').upsert(PRECREATE_SUPPLIERS, on_conflict='name').execute()

    sup_map, brand_by_name, brand_by_supplier = build_brand_lookup()

    aliases_by_name = {}
    unmapped_by_name = {}
    new_suppliers_by_name = {}

    def add_alias(raw, target, source):
        # Сначала проверяем оверрайд по raw
        if raw in MANUAL_OVERRIDES:
            ov = MANUAL_OVERRIDES[raw]
            sid = sup_map.get(ov['supplier'])
            bid = None
            if sid and 'brand' in ov:
                for name, b in brand_by_name.items():
                    if name == ov['brand'] and b['supplier_id'] == sid:
                        bid = b['id']; break
            if sid:
                aliases_by_name[raw] = {
                    'alias_name': raw, 'supplier_id': sid,
                    'supplier_brand_id': bid, 'source': 'manual_override',
                }
                return True
            else:
                # Pending — будет привязан после precreate
                aliases_by_name[raw] = {
                    'alias_name': raw, 'supplier_id': None,
                    'supplier_brand_id': None, 'source': 'manual_override_pending',
                    '_pending_canonical': ov['supplier'],
                    '_pending_brand': ov.get('brand'),
                }
                return True
        if not target:
            return False
        sid, bid = find_supplier_or_brand(target, sup_map, brand_by_name, raw_name=raw)
        if sid and raw not in aliases_by_name:
            aliases_by_name[raw] = {
                'alias_name': raw, 'supplier_id': sid,
                'supplier_brand_id': bid, 'source': source,
            }
            return True
        return False

    def add_unmapped(raw, note):
        if raw in aliases_by_name or raw in unmapped_by_name:
            return
        cnt = counts.get(raw, {})
        unmapped_by_name[raw] = {
            'raw_name': raw,
            'transactions_count': cnt.get('tx_count', 0) or 0,
            'total_purchase': float(cnt.get('total_purchase', 0) or 0),
            'first_seen_date': cnt.get('first_date').isoformat() if cnt.get('first_date') else None,
            'last_seen_date': cnt.get('last_date').isoformat() if cnt.get('last_date') else None,
            'status': 'pending',
            'notes': note,
        }

     # ИСТОЧНИК 1 (приоритет): dc_returns
    for r in dc:
        raw = r['raw_supplier']
        if not raw:
            continue
        tx = counts.get(raw, {}).get('tx_count', 0) or 0  # ← ДОБАВЛЕНО

        if raw in TECHNICAL_NAMES:
            add_unmapped(raw, f"технический мусор (canonical={r['canonical']})")
            continue
        if raw in DEPRECATED_NAMES:
            add_unmapped(raw, "выведенный поставщик (товара больше нет)")
            continue

        if add_alias(raw, r['canonical'], 'bq_dc_returns'):
            continue
        canonical_name = r['canonical']
        if tx > UNMAPPED_THRESHOLD and raw not in TECHNICAL_NAMES \
                and raw not in DEPRECATED_NAMES \
                and canonical_name not in DEPRECATED_NAMES:
            new_suppliers_by_name.setdefault(canonical_name, {
                'name': canonical_name, 'is_retro_active': False,
                'notes': f'auto-created from dc_returns, tx={tx}',
            })
            aliases_by_name.setdefault(raw, {
                'alias_name': raw, 'supplier_id': None, 'supplier_brand_id': None,
                'source': 'bq_dc_returns_autocreate',
                '_pending_canonical': canonical_name,
            })
        elif canonical_name in DEPRECATED_NAMES:
            add_unmapped(raw, f"выведенный поставщик (canonical={canonical_name})")
        else:
            add_unmapped(raw, f"dc_returns canonical={canonical_name}, не найден, tx={tx}")

    # ИСТОЧНИК 2: supplier_mapping
    for r in mapping:
        raw = r['incoming_supplier']
        target = r['matrix_supplier']
        if not raw or raw in aliases_by_name:
            continue
        if raw in TECHNICAL_NAMES:
            add_unmapped(raw, "технический мусор")
            continue
        if raw in DEPRECATED_NAMES:
            add_unmapped(raw, "выведенный поставщик")
            continue

        cnt = counts.get(raw, {})
        tx = cnt.get('tx_count', 0) or 0

        if target:
            if not add_alias(raw, target, 'bq_supplier_mapping'):
                if tx > UNMAPPED_THRESHOLD and target not in DEPRECATED_NAMES:
                    new_suppliers_by_name.setdefault(target, {
                        'name': target, 'is_retro_active': False,
                        'notes': f'auto-created from supplier_mapping, tx={tx}',
                    })
                    aliases_by_name.setdefault(raw, {
                        'alias_name': raw, 'supplier_id': None, 'supplier_brand_id': None,
                        'source': 'bq_supplier_mapping_autocreate',
                        '_pending_canonical': target,
                    })
                else:
                    add_unmapped(raw, f"matrix_supplier={target}, не найден, tx={tx}")
        else:
            if tx > UNMAPPED_THRESHOLD and raw not in TECHNICAL_NAMES and raw not in DEPRECATED_NAMES:
                new_suppliers_by_name.setdefault(raw, {
                    'name': raw, 'is_retro_active': False,
                    'notes': f'auto-created from BQ, tx={tx}',
                })
            else:
                reason = 'тех. имя' if raw in TECHNICAL_NAMES else 'мало транзакций'
                add_unmapped(raw, f'matrix_supplier IS NULL, tx={tx} ({reason})')

    # Второй проход: пробуем перемапить unmapped через новых поставщиков
    if new_suppliers_by_name:
        retry = []
        for raw, u in list(unmapped_by_name.items()):
            note = u['notes']
            m = re.search(r'canonical=([^,]+),', note) or re.search(r'matrix_supplier=([^,]+),', note)
            if not m:
                continue
            canonical = m.group(1).strip()
            norm_canonical = normalize(canonical)
            for new_name in new_suppliers_by_name:
                if normalize(new_name) == norm_canonical:
                    aliases_by_name[raw] = {
                        'alias_name': raw, 'supplier_id': None, 'supplier_brand_id': None,
                        'source': 'bq_retry_autocreate',
                        '_pending_canonical': new_name,
                    }
                    retry.append(raw); break
        for raw in retry:
            unmapped_by_name.pop(raw, None)

    aliases_to_load = list(aliases_by_name.values())
    unmapped_to_load = list(unmapped_by_name.values())
    new_suppliers = list(new_suppliers_by_name.values())

    print(f"\n=== ШАГ 2. supplier_aliases ===")
    print(f"Алиасов на загрузку:      {len(aliases_to_load)}")
    print(f"Новых поставщиков (auto): {len(new_suppliers)}")
    print(f"Предсоздаваемых:          {len(PRECREATE_SUPPLIERS)}")
    print(f"Unmapped suppliers:       {len(unmapped_to_load)}")

    print(f"\n--- Превью алиасов (первые 15) ---")
    for a in aliases_to_load[:15]:
        bid_str = '-' if not a['supplier_brand_id'] else a['supplier_brand_id'][:8] + '...'
        if a['supplier_id']:
            sid_str = a['supplier_id'][:8] + '...'
        else:
            sid_str = f"PENDING({a.get('_pending_canonical', '?')})"
        print(f"  '{a['alias_name']}' → {sid_str}/brand={bid_str}  [{a['source']}]")

    print(f"\n--- ВСЕ новые поставщики ({len(new_suppliers)}) ---")
    for s in sorted(new_suppliers, key=lambda x: -int(x['notes'].split('tx=')[1]) if 'tx=' in x['notes'] else 0):
        print(f"  + {s['name']} ({s['notes']})")

    print(f"\n--- ВСЕ unmapped ({len(unmapped_to_load)}) ---")
    for u in sorted(unmapped_to_load, key=lambda x: -x['transactions_count']):
        print(f"  ? {u['raw_name']} (tx={u['transactions_count']}) — {u['notes']}")

    if dry_run:
        return

    # Реальная загрузка
    if new_suppliers:
        sb.table('suppliers').upsert(new_suppliers, on_conflict='name').execute()

    # Перестраиваем lookup
    sup_map, brand_by_name, brand_by_supplier = build_brand_lookup()

    # Достраиваем supplier_id для pending-алиасов
    for a in aliases_to_load:
        if a.get('_pending_canonical'):
            a['supplier_id'] = sup_map.get(a['_pending_canonical'])
            if a.get('_pending_brand') and a['supplier_id']:
                for name, b in brand_by_name.items():
                    if name == a['_pending_brand'] and b['supplier_id'] == a['supplier_id']:
                        a['supplier_brand_id'] = b['id']; break
            a.pop('_pending_canonical', None)
            a.pop('_pending_brand', None)

    aliases_to_load = [a for a in aliases_to_load if a.get('supplier_id')]

    if aliases_to_load:
        sb.table('supplier_aliases').upsert(aliases_to_load, on_conflict='alias_name').execute()

    if unmapped_to_load:
        sb.table('unmapped_suppliers').upsert(unmapped_to_load, on_conflict='raw_name').execute()

    print(f"\nЗагружено: {len(new_suppliers)} новых, "
          f"{len(aliases_to_load)} алиасов, {len(unmapped_to_load)} unmapped")


def verify():
    print(f"\n=== Финальная сверка ===")
    for tbl in ('delivery_points', 'delivery_point_aliases',
                'suppliers', 'supplier_aliases', 'unmapped_suppliers'):
        cnt = sb.table(tbl).select('id', count='exact').execute()
        print(f"  {tbl}: {cnt.count}")


def main():
    print("Тяну данные из BigQuery...")
    store_rows = fetch_stores_from_bq()
    mapping, dc, counts = fetch_suppliers_from_bq()
    print(f"  store_mapping+info: {len(store_rows)}")
    print(f"  supplier_mapping:   {len(mapping)}")
    print(f"  dc_returns aliases: {len(dc)}")
    print(f"  incoming суппл-каунт: {len(counts)}")

    migrate_stores(store_rows, dry_run=True)
    migrate_suppliers(mapping, dc, counts, dry_run=True)

    if input("\nВыполнить загрузку в Supabase? (y/n): ").strip().lower() != 'y':
        print("Отмена.")
        return

    migrate_stores(store_rows, dry_run=False)
    migrate_suppliers(mapping, dc, counts, dry_run=False)
    verify()
    print("Готово.")


if __name__ == '__main__':
    main()

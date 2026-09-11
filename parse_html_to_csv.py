"""
Парсер HTML с коммерческими условиями поставщиков (v3).
Изменения v3:
- словарь BRAND_SPLIT для ручной разбивки слипшихся брендов
- округление retro_min/retro_max до 2 знаков
"""
import re
import json
import csv
from pathlib import Path
from collections import OrderedDict

HTML_PATH = Path(r"D:\РЕТРО_БОНУСЫ Фэмэли маркет\Коммерческие_условия_поставщиков_2026.html")
OUTPUT_DIR = Path(r"D:\РЕТРО_БОНУСЫ Фэмэли маркет\output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Слияние юрлиц
SUPPLIER_MERGE = {
    "Глобал-Сервіс Алкоголь": "Глобал-Сервіс",
}

# Ручная разбивка брендов: имя из HTML -> список реальных брендов
BRAND_SPLIT = {
"Алкоголь-Азнаури":                            ["Азнаури"],
"Алкоголь-Zubrovka":                           ["Zubrovka"],
    "Сок Ранок+Алкоголь-Привитальный и Франц Бульвар": ["Сок Ранок", "Коньяк Привитальный", "Франц Бульвар"],
    "Грин Дей-Аджари":                             ["Грин Дей", "Аджари"],
    "Марс-Сникерс":                                ["Марс", "Сникерс"],
    "Нестле-Торчин":                               ["Нестле", "Торчин"],
    "Мак Кофе и Петровская Слобода":               ["Мак Кофе", "Петровская Слобода"],
    "Тиса коньяк и Закарпатский":                  ["Тиса коньяк", "коньяк Закарпатский"],
    "Картуливази и Поляна дешовая":                ["Картуливази", "Поляна"],
    "Продукти-Мак май":                            ["Мак май"],
}

# Подозрительные паттерны для review (после применения BRAND_SPLIT)
SUSPICIOUS_BRAND_PATTERNS = [
    (r'-', 'дефис'),
    (r'\+', 'плюс'),
    (r'\bи\b', 'союз "и"'),
]


def extract_data_array(html_text: str) -> list:
    match = re.search(r'const\s+DATA\s*=\s*\[', html_text)
    if not match:
        raise ValueError("Не найден 'const DATA=[' в HTML")
    start = match.end() - 1
    depth = 0
    in_string = False
    escape = False
    end = None
    for i in range(start, len(html_text)):
        ch = html_text[i]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("Не найдено закрытие массива DATA")
    return json.loads(html_text[start:end])


def split_name(name: str) -> dict:
    name = name.strip()
    m = re.match(r'^([^()]+?)\s*\(([^()]*)\)\s*(.*)$', name)
    if not m:
        return {"supplier": name, "brands": [name], "suffix": ""}
    supplier = m.group(1).strip()
    brands_raw = m.group(2).strip()
    suffix = m.group(3).strip()
    if not brands_raw:
        brands = [supplier]
    else:
        brands = [b.strip() for b in brands_raw.split(',') if b.strip()]
    
    # Применяем BRAND_SPLIT — раскрываем слипшиеся бренды
    expanded = []
    for b in brands:
        if b in BRAND_SPLIT:
            expanded.extend(BRAND_SPLIT[b])
        else:
            expanded.append(b)
    
    return {"supplier": supplier, "brands": expanded, "suffix": suffix}


def parse_retro_range(retro_value):
    """Возвращает (is_active, retro_min, retro_max, raw_text)."""
    if retro_value is None:
        return (False, None, None, "")
    raw = str(retro_value).strip()
    s = raw.lower()
    if s in ('', 'нет', 'нет.', '-', '0', '0.0', '0.00', '0%'):
        return (False, None, None, raw)
    
    s_clean = s.replace(',', '.').replace('%', '').replace('от', '').strip()
    
    m_range = re.search(r'([\d.]+)\s*[-–]\s*([\d.]+)', s_clean)
    if m_range:
        try:
            v_min = float(m_range.group(1))
            v_max = float(m_range.group(2))
            if v_max <= 1:
                v_min *= 100
                v_max *= 100
            return (True, round(v_min, 2), round(v_max, 2), raw)
        except ValueError:
            pass
    
    m_single = re.search(r'([\d.]+)', s_clean)
    if m_single:
        try:
            v = float(m_single.group(1))
            if v <= 1:
                v *= 100
            return (True, round(v, 2), round(v, 2), raw)
        except ValueError:
            pass
    
    return (True, None, None, raw)


def parse_percent(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def find_suspicious(brand_name: str) -> str:
    reasons = []
    for pattern, label in SUSPICIOUS_BRAND_PATTERNS:
        if re.search(pattern, brand_name, re.IGNORECASE):
            reasons.append(label)
    return '; '.join(reasons)


def main():
    print(f"Читаем HTML: {HTML_PATH}")
    if not HTML_PATH.exists():
        raise FileNotFoundError(HTML_PATH)
    
    html_text = HTML_PATH.read_text(encoding='utf-8')
    data = extract_data_array(html_text)
    print(f"Извлечено записей: {len(data)}")
    
    suppliers_dict = OrderedDict()
    brands_list = []
    rules_list = []
    review_list = []
    log_lines = []
    merge_log = []
    split_log = []
    
    for row in data:
        num = row.get('num', '')
        name_raw = row.get('name', '').strip()
        if not name_raw:
            log_lines.append(f"[SKIP] num={num}: пустое имя")
            continue
        
        parsed = split_name(name_raw)
        original_supplier = parsed['supplier']
        brands = parsed['brands']
        suffix = parsed['suffix']
        
        supplier_name = SUPPLIER_MERGE.get(original_supplier, original_supplier)
        if supplier_name != original_supplier:
            merge_log.append(f"[MERGE] num={num}: '{original_supplier}' -> '{supplier_name}'")
        
        # Логируем применение BRAND_SPLIT
        m = re.match(r'^[^()]+?\s*\(([^()]*)\)', name_raw)
        if m:
            raw_brands = [b.strip() for b in m.group(1).split(',') if b.strip()]
            for rb in raw_brands:
                if rb in BRAND_SPLIT:
                    split_log.append(f"[SPLIT] num={num}: '{rb}' -> {BRAND_SPLIT[rb]}")
        
        retro_active, retro_min, retro_max, retro_raw = parse_retro_range(row.get('retro'))
        
        if supplier_name not in suppliers_dict:
            suppliers_dict[supplier_name] = {
                'name': supplier_name,
                'is_retro_active': False,
                'notes': '',
                'first_num': num,
            }
        
        if retro_active:
            suppliers_dict[supplier_name]['is_retro_active'] = True
        
        if suffix and suffix not in suppliers_dict[supplier_name]['notes']:
            existing = suppliers_dict[supplier_name]['notes']
            suppliers_dict[supplier_name]['notes'] = (existing + '; ' + suffix).strip('; ')
        
        for brand_name in brands:
            brand_record = {
                'num_html': num,
                'supplier_name': supplier_name,
                'brand_name': brand_name,
                'original_name': name_raw,
                'suffix': suffix,
                'is_retro_active': retro_active,
                'retro_raw': retro_raw,
                'retro_min': retro_min if retro_min is not None else '',
                'retro_max': retro_max if retro_max is not None else '',
                'discount': parse_percent(row.get('discount')),
                'positions': row.get('positions', ''),
                'sponsor': row.get('sponsor', ''),
                'entry_pay': row.get('entryPay', ''),
                'sku_entry': row.get('skuEntry', ''),
                'returns': row.get('returns', ''),
                'markup_opt': parse_percent(row.get('markupOpt')),
                'markup_retail': parse_percent(row.get('markupRetail')),
                'delivery': row.get('delivery', ''),
                'extra': row.get('extra', ''),
                'note': row.get('note', ''),
                'categories': ', '.join(row.get('_categories', []) or []),
                'color': row.get('_color', ''),
            }
            brands_list.append(brand_record)
            
            if retro_active:
                rules_list.append({
                    'num_html': num,
                    'supplier_name': supplier_name,
                    'brand_name': brand_name,
                    'retro_raw': retro_raw,
                    'retro_min': retro_min if retro_min is not None else '',
                    'retro_max': retro_max if retro_max is not None else '',
                    'discount': parse_percent(row.get('discount')),
                    'delivery': row.get('delivery', ''),
                    'returns_allowed': row.get('returns', ''),
                    'note': row.get('note', ''),
                    'extra': row.get('extra', ''),
                })
            
            reason = find_suspicious(brand_name)
            if reason:
                review_list.append({
                    'num_html': num,
                    'supplier_name': supplier_name,
                    'brand_name': brand_name,
                    'reason': reason,
                    'original_name': name_raw,
                    'is_retro_active': retro_active,
                })
        
        if len(brands) > 1:
            log_lines.append(f"[MULTI-BRAND] num={num} '{name_raw}' -> {len(brands)} брендов: {brands}")
        if suffix:
            log_lines.append(f"[SUFFIX] num={num} '{name_raw}' -> suffix='{suffix}'")
    
    # запись CSV
    suppliers_csv = OUTPUT_DIR / 'suppliers.csv'
    with suppliers_csv.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['name', 'is_retro_active', 'notes', 'first_num'])
        w.writeheader()
        for s in suppliers_dict.values():
            w.writerow(s)
    
    brands_csv = OUTPUT_DIR / 'supplier_brands.csv'
    with brands_csv.open('w', encoding='utf-8-sig', newline='') as f:
        fields = ['num_html', 'supplier_name', 'brand_name', 'original_name', 'suffix',
                  'is_retro_active', 'retro_raw', 'retro_min', 'retro_max', 'discount',
                  'positions', 'sponsor', 'entry_pay', 'sku_entry', 'returns',
                  'markup_opt', 'markup_retail', 'delivery', 'extra', 'note',
                  'categories', 'color']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for b in brands_list:
            w.writerow(b)
    
    rules_csv = OUTPUT_DIR / 'retro_rules_draft.csv'
    with rules_csv.open('w', encoding='utf-8-sig', newline='') as f:
        fields = ['num_html', 'supplier_name', 'brand_name', 'retro_raw',
                  'retro_min', 'retro_max', 'discount', 'delivery',
                  'returns_allowed', 'note', 'extra']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rules_list:
            w.writerow(r)
    
    review_csv = OUTPUT_DIR / 'brands_to_review.csv'
    with review_csv.open('w', encoding='utf-8-sig', newline='') as f:
        fields = ['num_html', 'supplier_name', 'brand_name', 'reason',
                  'original_name', 'is_retro_active']
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in review_list:
            w.writerow(r)
    
    log_path = OUTPUT_DIR / 'parse_log.txt'
    full_log = log_lines + [''] + ['=== MERGES ==='] + merge_log + [''] + ['=== SPLITS ==='] + split_log
    log_path.write_text('\n'.join(full_log), encoding='utf-8')
    
    total_suppliers = len(suppliers_dict)
    active_suppliers = sum(1 for s in suppliers_dict.values() if s['is_retro_active'])
    total_brands = len(brands_list)
    active_brands = sum(1 for b in brands_list if b['is_retro_active'])
    
    print()
    print("=" * 60)
    print(f"  Поставщиков (юрлиц):       {total_suppliers}")
    print(f"  ... из них с ретро:        {active_suppliers}")
    print(f"  Брендов всего:             {total_brands}")
    print(f"  ... из них с ретро:        {active_brands}")
    print(f"  Правил ретро (черновик):   {len(rules_list)}")
    print(f"  Брендов для проверки:      {len(review_list)}")
    print(f"  Слияний юрлиц:             {len(merge_log)}")
    print(f"  Разбивок брендов:          {len(split_log)}")
    print("=" * 60)


if __name__ == '__main__':
    main()

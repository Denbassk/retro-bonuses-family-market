# State — Family Market Retro-Бонусы

**Дата:** 2026-05-20
**Стадия:** Полный pipeline работает, идёт пошаговая сверка факт оплат с расчётом по каждому поставщику. Закрыты БІР (Соки) и Виналь, в процессе остальные ~45 поставщиков.

---

## 1. Цель проекта

Автоматизировать расчёт ретро-бонусов поставщиков Family Market: переход от ручных Excel-актов к воспроизводимому расчёту на основе данных BigQuery с хранением справочников и результатов в Supabase, отчётами в Google Sheets и админкой на HTML+Supabase JS SDK.

**Ключевые задачи:**
- Унифицировать справочник поставщиков и брендов (1С → канонические имена).
- Считать ретро-бонусы помесячно по правилам (% от приход − возврат, оплат, либо за порцию проданного).
- Учитывать обе формы оформления: маркетинговая услуга (Ф1 с НДС) и корректировка цены / наличка (Ф2).
- Учитывать фикс-бонусы помесячно (`supplier_monthly_bonuses`).
- Учитывать вычет 20% НДС из ретро (`subtract_vat_from_retro`) для отдельных поставщиков.
- Давать бухгалтерии отчёт в Google Sheets с детализацией по бренду+SKU + сверку начислений с фактом оплат.

---

## 2. Архитектура

### Слой данных (источник истины — BigQuery)

Сырые транзакции хранятся только в BigQuery:
- `family-market-analytics.family_market.incoming_transactions` — приход от поставщиков (~806 тыс. строк).
- `family-market-analytics.family_market.outgoing_to_supplier_transactions` — возвраты поставщикам (~9,6 тыс. строк).
- `family-market-analytics.analytics_reports.mart_sales_daily` — продажи (~1,1 млн строк), для per_portion_sold.

**Схема `incoming_transactions`:** `line_id, incoming_id, line_number, product_name, barcode, supplier, store, delivery_type, quantity, price_retail, price_purchase, amount_retail, amount_purchase, incoming_datetime, source_file, loaded_at, doc_date, doc_number`.

### Слой справочников и результатов (Supabase / Postgres)

**Справочники:**
- `suppliers` — поставщики (47 активных, поле `returns_cutoff_day` для окна возвратов).
- `supplier_brands` — бренды поставщика (один поставщик может иметь несколько брендов с разными %).
- `supplier_aliases` — имена в 1С/BigQuery. UNIQUE на пару `(supplier_id, alias_name)`. Типы: `branded`, `remainder`, `excluded`.
- `retro_rules` — правила (% или фикс ставка, валидность, форма, политика возвратов, SKU-фильтры, **`subtract_vat_from_retro` BOOL**).
- `supplier_monthly_bonuses` — фикс-бонусы помесячно (НЕ зависят от оборота).
- `supplier_payments` — банковская выписка платежей поставщикам (импортируется автоматически). Используется как **база для начисления ретро** у поставщиков с `retro_base_type='payments'`.
- `retro_payments_fact` — факт оплат ретро (ручной ввод в админке, для сверки).
- **`bank_counterparty_map`** (новая, 2026-05-19) — маппинг названий контрагентов из банковской выписки на `supplier_id`. Используется когда один поставщик платится через несколько юрлиц (например, Виналь оплачивается через ТОВ "Виналь", ТОВ "Бест Брендс", ТОВ "Торговий Дім АВ"). Поля: `counterparty_normalized`, `counterparty_raw`, `supplier_id`, `notes`.

**Результаты расчётов:**
- `retro_calculations` — заголовок «поставщик-месяц».
- `retro_calculation_details` — по брендам/правилам (поля `bonus_form`, `retro_amount_vat`).
- `retro_calculation_sku_details` — разбивка по штрих-кодам (используется в листе «Детализация»).

**ENUM-ы:**
- `delivery_point_type_enum`: rc, store, wholesale, production.
- `calculation_status_enum`: draft, in_progress, completed, approved, paid, cancelled.
- `retro_base_type`: shipment_minus_return, payments, per_portion_sold.
- `bonus_form` (CHECK): `price_correction`, `marketing_service`, `cash`.

### Слой расчёта

**Скрипт `calculate_retro.py`** — берёт активные правила и алиасы из Supabase, выполняет агрегирующие SQL-запросы в BigQuery, пишет результаты в `retro_calculations` / `retro_calculation_details` / `retro_calculation_sku_details`, экспорт CSV.

**Запуск:**
- `run_retro.bat` — однокликовый, период 2026-01 до предыдущего месяца.
- CLI: `python core\calculate_retro.py 2026-01 2026-04 --supplier "Виналь" --no-save --dry-run --verify`.
- Интерактивное меню: 8 пунктов.

**Логика резолвинга алиасов** (приоритет): brand-level → SKU-фильтр → fallback (средневзвешенный %).

**Логика возвратов (вариант B):** при `returns_cutoff_day` — общий приход/возвраты поставщика, доля распределяется пропорционально приходу каждого правила.

**Логика per_portion_sold (Якобз):** `retro = SUM(quantity) × cups_per_kg × price_per_portion`.

**Логика payments:** база = SUM(amount) из `supplier_payments` за месяц.

**Логика min_purchase_threshold:** если `base < threshold` → ретро=0 (Монжар 80k).

**Логика `subtract_vat_from_retro` (новая, 2026-05-19):** если флаг TRUE — после расчёта `retro = retro × 0.80` (минус 20% НДС). Применяется во всех трёх ветках (shipment, payments, per_portion) и в SKU-разбивке.

**Месячные фикс-бонусы:** отдельная строка `[БОНУС]` в details, `base_type='fixed_monthly'`.

### Слой представления

**Админка `admin.html`** — CRUD-вкладки + «💰 Факт оплат ретро» (pivot поставщики×месяцы).

**Google Sheet + Apps Script** (`apps_script_retro.js`):
- **«Сводка»**: pivot Поставщик(Бренды) | % | Форма | месяцы | ИТОГО. Объединение брендов с одинаковыми %.
- **«Детализация»**: sidebar диалог. **Обновлено 2026-05-19**: теперь под каждой строкой бренда выводятся строки SKU с штрих-кодом, названием, кол-вом и суммой ретро. Жирные заголовки брендов, серый текст для SKU.
- **«Сверка»**: pivot Нач/Опл/Δ% по месяцам. **Исправлено 2026-05-19**: бажные −10000% в пустых ячейках (формат `+0.0%;-0.0%;0%` сам умножает на 100, нужно передавать долю, а не процент).

**Скрипт импорта оплат `import_payments.py`:**
- Парсит Excel банковской выписки. **Обновлено 2026-05-19**: добавлен диалог выбора файлов через Tkinter (по умолчанию), флаги `--all` и `--files`.
- Маппинг контрагента: сначала `bank_counterparty_map`, затем `legal_name` (точное/частичное).
- Пишет в `supplier_payments` с `on_conflict=supplier_id,payment_date,doc_number,amount`, дубли игнорируются.

---

## 3. Текущее состояние данных (2026-05-20)

**Справочники Supabase:**
- 47 поставщиков (включая 5 с `base_type='payments'` + Виналь, переходящий на новую логику).
- ~110 правил retro_rules (active).
- ~140 алиасов, >80% с brand-level привязкой.
- 1 фикс-бонус (Авангард Дистрибуції 13 000 ₴/мес).
- `supplier_payments`: 17 547+ строк (АСК, Хладопром, Продресурс, Баядера, Дісна, **Виналь** — добавлен 2026-05-19, ~50 строк за Jan-Apr).
- `bank_counterparty_map`: 3 записи (ТОВ ВИНАЛЬ / ТОВ БЕСТ БРЕНДС / ТОВ ТОРГОВИЙ ДІМ АВ → supplier_id Виналя).

**Результаты расчёта Jan-Apr 2026:** ~179 retro_calculations. После правки Виналя итог немного изменился.

---

## 4. Ключевые поставщики и их особенности

### БІР — 3 направления, общий алиас «БІР (Пиво)»
- **БІР (Пиво Славутич)**: 22% Jan-Mar, 23% Apr+. Алиас `БІР (Пиво)` (branded). 7 SKU кегового исключены через `excluded_sku_barcodes`.
- **БІР (Пиво Кег)**: 25% с Apr+. Тот же алиас `БІР (Пиво)` (remainder), отдельный supplier_id. SKU-фильтр на 7 кеговых барcодов.
- **БІР (Сок Ранок+Алкоголь, Гетьман, Привітальний, Руна)**: 12% Jan-Mar, с апреля по сокам ретро отменено (`valid_to=2026-03-31`). Алиас `БІР (Ранок+Алкоголь)`.
- **Сверка 2026-05-19**: расчёт сходится с BQ копейка в копейку. Расхождения с фактом 4-5% — граничные документы. Не критично.

### Виналь — 10% × 0.80 от закупки минус возврат (новая логика 2026-05-19)
- 3 алиаса (`Виналь`, `Бест Брендс`, `Торговий Дім АВ`), все привязаны к бренду «Грин Дей».
- Правило: 10% от (приход − возврат) × 0.80 (минус 20% НДС). `subtract_vat_from_retro=TRUE`, `valid_from=2026-01-01`.
- **Сверка Jan-Apr**: 32 768.50 / 35 980.99 / 28 374.24 / 43 808.64 — Jan/Feb копейка-в-копейку с фактом, Mar Δ +666 (граничные документы).
- 4 «пустых» бренда (Аджари, Вилла Крыма, Довбуш, Вижиана вино) — оставлены в `supplier_brands` как справочник, правила удалены (товары идут общим потоком 10%).
- **Оплаты Виналя** импортированы в `supplier_payments` через `bank_counterparty_map` — НЕ используются для расчёта (база = закупка), но лежат для сверки с банком.

### Аванта-Трейд — 2 направления
- **(АВК)**: 4% Jan-Feb (Ф1 marketing_service), с Mar+ ретро=0.
- **(Фереро, Киндер)**: 9.5% с Apr+ (Ф1 marketing_service).

### Гермес — 10%/12%
- 10% Jan, 12% с Feb+. Алиас `Гермес`, бренд "Reeva, Даринка, Glads, Idelia". Исключён SKU 4820001115567 (Олейна 0,85 л).
- С апреля поставщик переименован в **Юпітер** — второй алиас «Торгівельна Компанія Юпітер».
- Итого: Jan 9 775 + Feb 10 585 + Mar 15 081 + Apr 18 424 = 53 865 ₴.

### Союз — 4 направления
- **(Оболонь)**: 25% (67 SKU алкоголь), 20% (22 SKU вода/б/а). `returns_cutoff_day=12`, вариант B.
- **(Продукти)**: Мак май 10%, Ямуна 10%.
- **(Наш Сік)**: 12%.
- **(Жако, Золотое Зерно, Полюс, Світтейл, Сезам, Чарівна мозаїка)**: SKU-matched 20%/10%, остальное 15% (avg).

### Авангард Дистрибуції — 3 направления + фикс-бонус 13 000 ₴/мес
- Сан Санич 15%, Флінт 12%, Чіпстерс 9.5%.
- Бонус под «зонтиком» родителя через UMBRELLA_RULES в Apps Script.

### СТВ Схід — Якобз кофе-аппараты (per_portion_sold)
- 2 SKU × 3 ₴/чашка × (125 или 50 чашек/кг). Итого Jan-Apr: 298 125 ₴.

### Бойчак ТД — 10% с Mar+ (cash)
### Сервіс Про — 4 правила (Салфетки/Фрекен Бок × Jan-Apr cash / May+ marketing_service)
### Монжар — 15%, порог 80 000 ₴/мес
### Поставщики с `base_type='payments'`: АСК, Хладопром, Продресурс ЛТД, Баядера, Дісна

---

## 5. Известные проблемы и риски

1. **НДС в `amount_purchase`** — не подтверждено окончательно. Для `price_correction` неважно, для `marketing_service` нужна арифметическая сверка.
2. **Граничные документы** — корректировки прошлых периодов из ручных актов невоспроизводимы автоматически (типично 1-5% расхождения). Решение: ручная правка `retro_calculation_details` при утверждении периода.
3. **Fallback-неточности** — Союз Мак май, Світтейл/Сезам/Чарівна мозаїка. Решаются brand alias или SKU-разбивкой.
4. **import_payments.py медленный** — по одному HTTP-запросу на строку, файл АСК (~1000 строк) идёт 5-10 мин. Можно ускорить батчами.

---

## 6. Файлы проекта (структура с 11.09.2026)

```
D:\РЕТРО_БОНУСЫ Фэмэли маркет
├── CLAUDE.md, State.md       # память проекта и архитектура
├── admin.html                # админка (остаётся в корне: её раздаёт start_admin.bat)
├── start_admin.bat           # http://localhost:3000/admin.html
├── menu_retro.bat, run_retro.bat  # интерактивное меню расчёта (ярлык «Расчет_ретро» -> run_retro.bat)
├── core\                     # рабочий конвейер: запускать из корня, python core\<скрипт>.py
│   ├── sb.py, paths.py       # доступ к Supabase (пагинация, батчи), единые пути
│   ├── calculate_retro.py    # расчёт ретро
│   ├── import_payments.py    # банковские выписки -> supplier_payments
│   ├── import_retro_facts.py, dump_cell_comments.py, parse_payment_notes.py, parse_note_components.py  # разбор Excel
│   ├── resolve_supplier_names.py, load_name_map.py, confirm_names.py   # маппинг имён
│   ├── import_facts_to_db.py # Excel -> retro_payments_fact
│   └── audit_facts_coverage.py, diagnose_retro.py, dump_rules.py
├── tools\                    # разовые миграции/заливки справочников, шаблоны, Apps Script
├── analysis\                 # разборы по конкретным поставщикам (СТВ, Монжар, Союз, зерновая)
├── _archive\                 # probe-скрипты и их CSV (сверка слоя данных и т.п.)
├── Ретро_Excel\              # СЮДА кладётся выгрузка «Ретро Бонусы»; старые\ - прошлые версии
├── data\справочники\         # Маппинг имен.xlsx, Ассортиментная матрица, коммерческие условия
├── data\разборы\             # результаты разборов (xlsx, txt)
├── payments\                 # банковские выписки
├── output\                   # всё, что генерируют скрипты core\ (CSV, rules_snapshot.md)
├── credentials\, Бэкап\       # ключи; .bak и копии
```

## 7. Что сделано в сессии 2026-05-19/20

### Архитектурное: поле `subtract_vat_from_retro`
- Добавлено поле в `retro_rules`: `ALTER TABLE retro_rules ADD COLUMN subtract_vat_from_retro BOOLEAN DEFAULT FALSE`.
- Пропатчен `calculate_retro.py` в 3 местах (shipment, payments, per_portion) + SKU-разбивка.
- Применено к Виналю.

### Архитектурное: таблица `bank_counterparty_map`
- Создана для маппинга «банковский контрагент → supplier_id» когда один поставщик платится через несколько юрлиц.
- В `import_payments.py` добавлен приоритетный поиск через эту таблицу перед fallback по `legal_name`.
- Заполнены 3 записи для Виналя.

### Виналь — полная сверка и переключение логики
- Изначально стояло 10% Jan+ от полной закупки. Факт оплаты не сходился.
- Выяснено: 10% × 0.80 (минус 20% НДС) от (закупка − возврат) по всем 3 алиасам.
- Импортированы оплаты Jan-Apr через `bank_counterparty_map` (но не используются — база = закупка).
- Удалены 4 правила-пустышки (бренды без алиасов).
- Сверка с фактом: Jan/Feb копейка, Mar Δ +666.

### import_payments.py — UX
- Диалог выбора файлов через Tkinter (по умолчанию).
- Флаги `--all` (загрузить все), `--files file1 file2` (конкретные).
- Не сломается при прерывании Ctrl+C — на повторе пропустит уже залитое (on_conflict).

### Apps Script — две правки
- **Лист «Сверка»**: исправлен баг с `−10000%` в Δ-колонках. Причина: формат `+0.0%;-0.0%;0%` сам умножает на 100, а скрипт уже отдавал умноженное число → 10000. Теперь передаём долю, формат корректен.
- **Лист «Детализация»**: добавлен вывод SKU из `retro_calculation_sku_details` под каждой строкой бренда. Жирные заголовки брендов (голубой фон), серые строки SKU с отступом, штрих-кодом и названием. Колонка «Кол-во» добавлена.

### БІР (Соки) — сверка с фактом
- Расчёт скрипта совпадает с BQ копейка в копейку.
- Расхождения с фактом 4-5% — граничные документы / округления в актах.
- Никаких правок не потребовалось.

---

## 8. Открытые вопросы / следующие шаги

1. **Продолжить пошаговую сверку остальных ~45 поставщиков** — по списку из колонки «Сверка» в Google Sheet. Идём от красных/жёлтых ячеек.
2. **Авангард — фикс-бонус 13 000 ₴/мес** — окончательно решить, переносить ли на Сан Санич.
3. **Заполнение `retro_payments_fact`** — бухгалтер вносит факты оплат вручную.
4. **НДС в amount_purchase** — арифметическая сверка с актом для одного поставщика.
5. **Корректировки прошлых периодов** — механизм ручной правки `retro_calculation_details` через админку.
6. **Ускорить import_payments.py** — батчи по 100-500 строк за один POST вместо построчно (потенциал ×50-100).

---

## 9. Команды быстрого старта

```powershell
cd "D:\РЕТРО_БОНУСЫ Фэмэли маркет"

# Полный пересчёт за все месяцы 2026
python core\calculate_retro.py 2026-01 2026-04

# По одному поставщику без сохранения
python core\calculate_retro.py 2026-01 2026-04 --supplier "Виналь" --no-save

# Интерактивное меню
python core\calculate_retro.py

# Импорт оплат — откроется диалог выбора файлов
python core\import_payments.py

# Импорт всех файлов из payments/
python core\import_payments.py --all

# Импорт конкретных файлов
python core\import_payments.py --files "payments/АСК.xlsx" "payments/Виналь.xlsx"

# Однокликовый запуск
run_retro.bat
```

**Apps Script:** Google Sheet → Расширения → Apps Script → меню ⚡ Ретро:
- 🔄 Обновить сводку
- 🔍 Детализация… (с SKU-разбивкой)
- 💰 Сверка начислено/оплачено

---

## 10. SQL-шпаргалка для проверки в BigQuery

### Приход + возврат за период по конкретному поставщику

```sql
SELECT 
  'Приход' AS type,
  ROUND(SUM(amount_purchase), 2) AS total_amount
FROM `family-market-analytics.family_market.incoming_transactions`
WHERE supplier = 'Арсенал ПК (Азнаурі)'
  AND doc_date >= '2026-03-01' AND doc_date < '2026-04-01'

UNION ALL

SELECT 
  'Возврат' AS type,
  ROUND(SUM(amount_purchase), 2) AS total_amount
FROM `family-market-analytics.family_market.outgoing_to_supplier_transactions`
WHERE supplier = 'Арсенал ПК (Азнаурі)'
  AND doc_date >= '2026-03-01' AND doc_date < '2026-04-01';
```

### Приход по месяцам разбивка

```sql
SELECT 
  supplier,
  FORMAT_DATE('%Y-%m', doc_date) AS month,
  COUNT(*) AS lines,
  COUNT(DISTINCT barcode) AS skus,
  ROUND(SUM(amount_purchase), 2) AS total_purchase
FROM `family-market-analytics.family_market.incoming_transactions`
WHERE supplier IN ('Виналь', 'Бест Брендс', 'Торговий Дім АВ')
  AND doc_date >= '2026-01-01' AND doc_date < '2026-05-01'
GROUP BY supplier, month
ORDER BY month, supplier;
```

### Возвраты по месяцам

```sql
SELECT 
  supplier,
  FORMAT_DATE('%Y-%m', doc_date) AS month,
  ROUND(SUM(amount_purchase), 2) AS total_returns
FROM `family-market-analytics.family_market.outgoing_to_supplier_transactions`
WHERE supplier IN ('Виналь', 'Бест Брендс', 'Торговий Дім АВ')
  AND doc_date >= '2026-01-01' AND doc_date < '2026-06-01'
GROUP BY supplier, month
ORDER BY month, supplier;
```

### Детальная разбивка по SKU за месяц

```sql
SELECT 
  FORMAT_DATE('%Y-%m', doc_date) AS month,
  barcode,
  ANY_VALUE(product_name) AS product_name,
  ROUND(SUM(quantity), 2) AS qty,
  ROUND(SUM(amount_purchase), 2) AS amount
FROM `family-market-analytics.family_market.incoming_transactions`
WHERE supplier = 'Гермес'
  AND doc_date >= '2026-02-01' AND doc_date < '2026-03-01'
GROUP BY month, barcode
ORDER BY amount DESC;
```

### Список всех имён supplier в BQ за период

```sql
SELECT DISTINCT supplier
FROM `family-market-analytics.family_market.incoming_transactions`
WHERE LOWER(supplier) LIKE '%виналь%'
  AND doc_date >= '2026-01-01'
ORDER BY supplier;
```

### Схема таблиц

```sql
SELECT table_name, column_name, data_type, ordinal_position
FROM `family-market-analytics.family_market.INFORMATION_SCHEMA.COLUMNS`
ORDER BY table_name, ordinal_position;
```

---

## 11. SQL-шпаргалка для Supabase

### Проверка правил поставщика

```sql
SELECT 
  s.name, sb.name as brand, 
  rr.retro_min, rr.bonus_form, rr.retro_base_type,
  rr.returns_policy, rr.subtract_vat_from_retro,
  rr.valid_from, rr.valid_to, rr.status,
  rr.sku_barcodes, rr.excluded_sku_barcodes, rr.notes
FROM suppliers s
LEFT JOIN supplier_brands sb ON sb.supplier_id = s.id
LEFT JOIN retro_rules rr ON rr.supplier_brand_id = sb.id
WHERE s.name ILIKE '%Виналь%'
ORDER BY sb.name, rr.valid_from;
```

### Алиасы поставщика

```sql
SELECT s.name, sa.alias_name, sa.alias_type, sb.name as brand
FROM supplier_aliases sa
JOIN suppliers s ON s.id = sa.supplier_id
LEFT JOIN supplier_brands sb ON sb.id = sa.supplier_brand_id
WHERE s.name ILIKE '%Виналь%';
```

### Результат расчёта

```sql
SELECT 
  s.name, rc.period_label,
  rcd.applied_percent, rcd.amount_purchased, rcd.amount_returned, 
  rcd.amount_net, rcd.retro_amount, rcd.bonus_form, sb.name as brand
FROM retro_calculations rc
JOIN suppliers s ON s.id = rc.supplier_id
JOIN retro_calculation_details rcd ON rcd.calculation_id = rc.id
LEFT JOIN supplier_brands sb ON sb.id = rcd.supplier_brand_id
WHERE s.name ILIKE '%Виналь%'
ORDER BY rc.period_label;
```

### Оплаты по поставщику

```sql
SELECT period_label, COUNT(*) as records, ROUND(SUM(amount)::numeric, 2) as total_paid
FROM supplier_payments sp
JOIN suppliers s ON s.id = sp.supplier_id
WHERE s.name = 'Виналь'
GROUP BY period_label
ORDER BY period_label;
```
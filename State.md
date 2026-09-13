# State — архитектура «Ретро-бонусы Family Market»

**Обновлено:** 2026-09-13. Правила и текущий статус — в `CLAUDE.md` (он главный).
Здесь только устройство системы.

## Слой данных — BigQuery (источник истины по транзакциям)

- `family-market-analytics.family_market.incoming_transactions` — приход,
  440 888 строк за 2026. PK `line_id`. Схема: line_id, incoming_id, line_number,
  product_name, barcode, supplier, store, delivery_type, quantity, price_retail,
  price_purchase, amount_retail, amount_purchase, incoming_datetime, source_file,
  loaded_at, doc_date, doc_number.
- `outgoing_to_supplier_transactions` — возвраты, 19 990 строк за 2026.
  Флагов is_internal / is_prosrok у нас НЕТ (есть только в эталоне).
- `analytics_reports.mart_sales_daily` — продажи, для per_portion_sold.
- Эталоны Торгсофт и прочие справочники — см. `docs/reference/bq-etalons.md`.

## Слой справочников и результатов — Supabase

Справочники: `suppliers` (поле returns_cutoff_day), `supplier_brands`,
`supplier_aliases` (UNIQUE на (supplier_id, alias_name); типы branded / remainder /
excluded), `retro_rules` (ставка, валидность, форма, политика возвратов, SKU-фильтры,
subtract_vat_from_retro), `supplier_monthly_bonuses`, `supplier_payments`,
`bank_counterparty_map` (банковский контрагент -> supplier_id, когда поставщик
платится через несколько юрлиц), `retro_fact_name_map`.

Результаты: `retro_calculations` (заголовок поставщик-месяц, сумма в `total_retro`),
`retro_calculation_details` (по брендам и правилам, поля bonus_form, retro_amount_vat,
adjustment_id), `retro_calculation_sku_details`, `retro_payments_fact` (факт оплат),
`retro_adjustments` (корректировки поверх расчёта, payment_mode in_payment/separate),
`store_opening_bonuses`, `retro_reconciliation` (итог автосверки),
`retro_fact_imports` (журнал загрузок).

ENUM: `retro_base_type` = shipment_minus_return | payments | per_portion_sold;
`calculation_status_enum` = draft, in_progress, completed, approved, paid, cancelled;
`bonus_form` = price_correction | marketing_service | cash;
`delivery_point_type_enum` = rc, store, wholesale, production.

## Логика расчёта (core\calculate_retro.py)

- Резолв алиасов по приоритету: brand-level -> SKU-фильтр -> fallback (средневзвешенный %).
- Возвраты, вариант B: при `returns_cutoff_day` берётся общий приход и возвраты
  поставщика, доля распределяется пропорционально приходу каждого правила.
- per_portion_sold: retro = SUM(quantity) x cups_per_kg x price_per_portion.
- payments: база = SUM(amount) из `supplier_payments` за месяц.
- min_purchase_threshold: база ниже порога -> ретро 0 (Монжар 80 тыс.).
- subtract_vat_from_retro: retro x 0.80 через `apply_vat()`, во всех трёх ветках
  и в SKU-разбивке.
- Месячные фикс-бонусы: отдельная строка [БОНУС], base_type=fixed_monthly.
- В расчёт попадают только корректировки с payment_mode=in_payment.

## Слой представления

- `admin.html` — CRUD-вкладки, «Факт оплат ретро» (pivot поставщики x месяцы,
  статус автосверки и диагноз в ячейке, фильтр проблем), «Загрузка Excel»
  (черновик -> выбор строк -> запись с журналом -> фоновая сверка).
- `core\admin_server.py` — сервер админки, 127.0.0.1:3000, отдаёт только admin.html,
  проверяет токен Supabase Auth на каждый POST.
- Google Sheet + `apps_script_retro.js`: листы «Сводка», «Детализация» (с SKU),
  «Сверка» (Нач/Опл/дельта по месяцам). Apps Script читает `total_retro`.

## Структура папок

    CLAUDE.md, State.md          память проекта
    admin.html, *.bat            админка и запуск (остаются в корне)
    core\                        конвейер; запуск из корня: python core\<скрипт>.py
      sb.py, paths.py            доступ к Supabase (пагинация, батчи), единые пути
      calculate_retro.py         расчёт ретро
      import_payments.py         банковские выписки -> supplier_payments
      import_retro_facts.py      разбор Excel фактов
      dump_cell_comments.py, parse_payment_notes.py, parse_note_components.py
      resolve_supplier_names.py, load_name_map.py, confirm_names.py
      import_facts_to_db.py      Excel -> черновик -> retro_payments_fact
      admin_server.py            сервер админки
      adjustments.py             доплаты in_payment / separate
      reconcile_facts.py         этап 4: факт vs расчёт -> retro_reconciliation
      diagnose_retro.py          этап 5: лестница гипотез с числами
      bq_docs.py                 наши документы против эталона Торгсофт
      audit_facts_coverage.py, dump_rules.py
    sql\                         миграции (выполняет пользователь в SQL Editor)
    tools\                       разовые миграции и заливки справочников
    analysis\                    разборы по поставщикам
    _archive\                    probe-скрипты и их CSV
    Ретро_Excel\                 выгрузки «Ретро Бонусы» (старые\ — прошлые версии)
    data\справочники\            Маппинг имен.xlsx, матрица, условия
    payments\                    банковские выписки
    output\                      всё, что генерируют скрипты core\
    docs\                        reference и archive

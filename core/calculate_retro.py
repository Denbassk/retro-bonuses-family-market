#!/usr/bin/env python3
"""
calculate_retro.py — Расчёт ретро-бонусов Family Market
Загружает правила из Supabase, транзакции из BigQuery, считает ретро помесячно.

Запуск:
  python calculate_retro.py 2026-01                              # один месяц
  python calculate_retro.py 2026-01 2026-04                      # диапазон месяцев
  python calculate_retro.py --supplier "Бісквіт і Ко" 2026-01    # один поставщик
  python calculate_retro.py --dry-run 2026-01                     # только SQL
"""

import os
import sys
import json
import argparse
import urllib.request
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from pathlib import Path

# ─── Загрузка .env ────────────────────────────────────────────────────────────
def load_env(env_path=None):
    if env_path is None:
        here = Path(__file__).resolve().parent
        env_path = next((c for c in (here / ".env", here.parent / ".env") if c.exists()), here / ".env")
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

load_env()


import logging
logging.getLogger("google").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
BQ_PROJECT   = os.environ.get("BQ_PROJECT", "family-market-analytics")
BQ_DATASET   = os.environ.get("BQ_DATASET", "family_market")

# ─── Коэффициент subtract_vat_from_retro ─────────────────────────────────────
# РЕШЕНО 11.09.2026: «минус 20%» = × 0.80 для всех правил с subtract_vat_from_retro (не ÷1.2).
VAT_FACTOR = Decimal("0.80")


def apply_vat(amount, rule):
    """Вычет НДС из ретро: × VAT_FACTOR (0.80 = «минус 20%»), если у правила subtract_vat_from_retro.
    Решение 11.09.2026: форма ×0.8 (Виналь сошёлся копейка в копейку). Округление до копейки."""
    if not rule.get("subtract_vat_from_retro"):
        return amount
    return (amount * VAT_FACTOR).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

# ─── Supabase helpers ─────────────────────────────────────────────────────────
def sb_get(table, params="", page_size=1000):
    """GET с автопагинацией. Если в params уже есть limit/offset — один запрос, как раньше."""
    manual = "limit=" in params or "offset=" in params
    has_order = "order=" in params
    out, offset = [], 0
    while True:
        p = params
        if not manual:
            sep = "&" if p else ""
            p = f"{p}{sep}limit={page_size}&offset={offset}"
            if not has_order:
                p += "&order=id"
        url = f"{SUPABASE_URL}/rest/v1/{table}?{p}"
        req = urllib.request.Request(url, headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        })
        with urllib.request.urlopen(req) as resp:
            page = json.loads(resp.read())
        if not isinstance(page, list):
            return page
        out.extend(page)
        if manual or len(page) < page_size:
            return out
        offset += page_size

def sb_post(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"\n[!] Supabase POST {table} error {e.code}:")
        print(f"    payload: {json.dumps(data, ensure_ascii=False)[:500]}")
        print(f"    response: {err_body}")
        raise

def sb_delete(table, params):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    req = urllib.request.Request(url, method="DELETE", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req) as resp:
        return resp.status

# ─── BigQuery helper ──────────────────────────────────────────────────────────
_bq_client = None
def run_bq(sql, retries=3):
    """Выполнить SQL в BigQuery и вернуть list[dict]. Retry при сетевых ошибках."""
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        _bq_client = bigquery.Client(project=BQ_PROJECT)
    for attempt in range(retries):
        try:
            rows = list(_bq_client.query(sql).result())
            if not rows:
                return []
            return [dict(r.items()) for r in rows]
        except Exception as e:
            if attempt < retries - 1:
                import time
                time.sleep(2 ** attempt)
                print(f"  [retry {attempt+1}] BQ ошибка: {e}")
            else:
                raise

# ─── Нормализация returns_allowed ─────────────────────────────────────────────
def should_subtract_returns(returns_allowed):
    """
    'нет', 'none', None, 'physical_exchange' → НЕ вычитать
    Всё остальное ('есть', 'частично', 'documented', текст) → вычитать
    """
    if not returns_allowed:
        return False
    val = returns_allowed.strip().lower()
    if val in ("нет", "none", "physical_exchange"):
        return False
    return True
def returns_policy_to_subtract(returns_policy, returns_allowed_legacy):
    """
    Приоритет: returns_policy (новое поле). Fallback: returns_allowed (старое).
    'subtract' → True, 'none'/'physical_exchange' → False
    """
    if returns_policy:
        return returns_policy == "subtract"
    return should_subtract_returns(returns_allowed_legacy)

# ─── Загрузка справочников ────────────────────────────────────────────────────
def load_reference_data():
    """Загружает правила, бренды, поставщиков, алиасы, бонусы, оплаты из Supabase."""
    print("[i] Загрузка справочников из Supabase...")

    rules = sb_get("retro_rules",
    "status=eq.active"
    "&select=id,supplier_brand_id,retro_min,retro_max,retro_base_type,"
    "returns_allowed,returns_policy,bonus_form,min_purchase_threshold,"
    "valid_from,valid_to,sku_barcodes,excluded_sku_barcodes,"
    "cups_per_kg,price_per_portion,min_sku_per_store,price_per_store,retro_amount_field,notes,"
    "subtract_vat_from_retro,income_source")


    brands = sb_get("supplier_brands", "select=id,name,supplier_id")
    suppliers = sb_get("suppliers", "select=id,name,is_retro_active,returns_cutoff_day")
    aliases = sb_get("supplier_aliases", 
        "select=alias_name,supplier_id,supplier_brand_id,alias_type&alias_type=neq.excluded")

    brand_map = {b["id"]: b for b in brands}
    supplier_map = {s["id"]: s for s in suppliers}

    # Алиасы: supplier_id → [alias_name, ...]
    alias_by_supplier = defaultdict(list)
    # Алиасы по бренду: supplier_brand_id → [alias_name, ...]
    alias_by_brand = defaultdict(list)
    # Алиасы только для возвратов: supplier_brand_id → [alias_name, ...]
    returns_only_by_brand = defaultdict(list)
    for a in aliases:
        alias_by_supplier[a["supplier_id"]].append(a["alias_name"])
        if a.get("supplier_brand_id"):
            if a.get("alias_type") == "returns_only":
                returns_only_by_brand[a["supplier_brand_id"]].append(a["alias_name"])
            else:
                alias_by_brand[a["supplier_brand_id"]].append(a["alias_name"])

    # Группируем правила по supplier_id
    supplier_rules = defaultdict(list)
    skipped_range = 0

    for r in rules:
        brand = brand_map.get(r["supplier_brand_id"])
        if not brand:
            continue
        sup_id = brand["supplier_id"]
        sup = supplier_map.get(sup_id)
        if not sup:
            continue

        base_type = r["retro_base_type"] or "shipment_minus_return"

        pct_min = r["retro_min"]
        pct_max = r["retro_max"]

        # Пропускаем диапазонные правила, если уже есть разбивка по sku_barcodes
        if pct_min is not None and pct_max is not None and pct_min != pct_max:
            has_split = any(
                r2["retro_min"] is not None
                and r2["retro_max"] is not None
                and r2["retro_min"] == r2["retro_max"]
                and r2["sku_barcodes"]
                and brand_map.get(r2["supplier_brand_id"], {}).get("supplier_id") == sup_id
                and r2["retro_min"] >= pct_min
                and r2["retro_max"] <= pct_max
                for r2 in rules
            )
            if has_split:
                skipped_range += 1
                continue

        # Читаем cups_per_kg и price_per_portion из БД (новые поля)
        cups_per_kg = r.get("cups_per_kg") or 0
        price_per_portion = r.get("price_per_portion")

        if base_type == "per_portion_sold":
            notes_text = r.get("notes") or ""
            if not cups_per_kg and notes_text:
                import re
                m_cpk = re.search(r'cups_per_kg\s*[:=]\s*(\d+)', notes_text)
                if m_cpk:
                    cups_per_kg = int(m_cpk.group(1))
                else:
                    m_cpk2 = re.search(r'(\d+)\s*(?:cups|чашек|чашок|порцій)/кг', notes_text, re.IGNORECASE)
                    if m_cpk2:
                        cups_per_kg = int(m_cpk2.group(1))
                    else:
                        m_cpk3 = re.search(r'×\s*(\d+)\s*×', notes_text)
                        if m_cpk3:
                            cups_per_kg = int(m_cpk3.group(1))
            if price_per_portion is None:
                price_per_portion = pct_min

        supplier_rules[sup_id].append({
            "rule_id": r["id"],
            "brand_name": brand["name"],
            "brand_id": brand["id"],
            "supplier_name": sup["name"],
            "supplier_id": sup_id,
            "pct": pct_min if (pct_max is None or pct_min == pct_max) else None,
            "pct_min": pct_min,
            "pct_max": pct_max,
            "base_type": base_type,
            "subtract_returns": returns_policy_to_subtract(r.get("returns_policy"), r.get("returns_allowed")),
            "bonus_form": r["bonus_form"] or "price_correction",
            "threshold": r["min_purchase_threshold"],
            "valid_from": r["valid_from"],
            "valid_to": r["valid_to"],
            "sku_barcodes": r["sku_barcodes"] or [],
            "excluded_sku_barcodes": r["excluded_sku_barcodes"] or [],
            "cups_per_kg": cups_per_kg,
            "price_per_cup": float(price_per_portion) if price_per_portion is not None else 0,
            "returns_cutoff_day": sup.get("returns_cutoff_day"),
            "subtract_vat_from_retro": r.get("subtract_vat_from_retro") or False,
            "min_sku_per_store": r.get("min_sku_per_store") or 10,
            "price_per_store": float(r.get("price_per_store")) if r.get("price_per_store") is not None else 0,
            "income_source": r.get("income_source") or "incoming",
        })
    # Проверка: эталон Торгсофт несовместим с фильтром по SKU (в нём нет product_name)
    for sid, rlist in supplier_rules.items():
        for r in rlist:
            if r.get("income_source") == "torgsoft_ref":
                if r.get("sku_barcodes"):
                    print(f"  [ПРЕДУПР] {r['supplier_name']} / {r['brand_name']}: "
                          f"income_source=torgsoft_ref + sku_barcodes — SKU-фильтр в эталоне может не работать")
                if r.get("excluded_sku_barcodes"):
                    print(f"  [ПРЕДУПР] {r['supplier_name']} / {r['brand_name']}: "
                          f"income_source=torgsoft_ref + excluded_sku — исключения в эталоне могут не сработать")


    brand_aliases_count = sum(1 for a in aliases if a.get("supplier_brand_id"))
    per_portion_count = sum(1 for sid in supplier_rules for r in supplier_rules[sid] if r["base_type"] == "per_portion_sold")
    print(f"  Правил: {len(rules)} всего, пропущено: {skipped_range} диапазонных, per_portion_sold: {per_portion_count}")
    print(f"  Поставщиков с правилами: {len(supplier_rules)}")
    print(f"  Алиасов: {len(aliases)} (из них {brand_aliases_count} привязаны к брендам)")

    # Месячные фикс-бонусы
    monthly_bonuses_raw = sb_get("supplier_monthly_bonuses",
        "status=eq.active&select=supplier_id,amount,bonus_form,description,valid_from,valid_to")
    monthly_bonuses = defaultdict(list)
    for mb in monthly_bonuses_raw:
        monthly_bonuses[mb["supplier_id"]].append(mb)
    print(f"  Месячных бонусов: {len(monthly_bonuses_raw)}")

    # === Загрузка оплат для retro_base_type='payments' (с пагинацией) ===
    payments_raw = []
    offset = 0
    page_size = 1000
    while True:
        page = sb_get("supplier_payments",
            f"select=supplier_id,period_label,amount&limit={page_size}&offset={offset}&order=id")
        if not page:
            break
        payments_raw.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    payments_by_key = defaultdict(float)
    for p in payments_raw:
        key = (p["supplier_id"], p["period_label"])
        payments_by_key[key] += float(p["amount"])
    print(f"  Оплат: {len(payments_raw)} записей, "
          f"{len(payments_by_key)} комбинаций (поставщик × месяц)")

    return supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map, monthly_bonuses, payments_by_key

# ─── Построение BQ-запросов ───────────────────────────────────────────────────
def sql_in(values):
    """SQL IN-список из строк с экранированием (BigQuery, C-style escapes)."""
    def esc(v):
        return str(v).replace("\\", "\\\\").replace("'", "\\'")
    return ", ".join(f"'{esc(v)}'" for v in values)

def build_query(table, alias_names, month_start, month_end,
                sku_barcodes=None, excluded_barcodes=None, agg_field="amount_purchase",
                group_by_barcode=False, income_source="incoming"):
    """Универсальный запрос incoming/outgoing.
    Если group_by_barcode=True — возвращает разбивку по штрих-кодам и product_name.
    income_source='torgsoft_ref' — для прихода использует эталонную таблицу Торгсофт."""
    use_ref = (income_source == "torgsoft_ref" and table == "incoming_transactions")
    if use_ref:
        full_table = f"`{BQ_PROJECT}.{BQ_DATASET}.torgsoft_incoming_ref_2026`"
        amt_col = "amount"
        eff_agg = "amount" if agg_field == "amount_purchase" else agg_field
    else:
        full_table = f"`{BQ_PROJECT}.{BQ_DATASET}.{table}`"
        amt_col = "amount_purchase"
        eff_agg = agg_field

    if group_by_barcode:
        # В эталоне может не быть product_name/quantity — подстрахуемся
        pname = "ANY_VALUE(product_name)" if not use_ref else "CAST(NULL AS STRING)"
        qty = "COALESCE(SUM(quantity), 0)" if not use_ref else "0"
        sql = f"""SELECT
  CAST(barcode AS STRING) AS barcode,
  {pname} AS product_name,
  {qty} AS qty,
  COALESCE(SUM({amt_col}), 0) AS amount
FROM {full_table}
WHERE supplier IN ({sql_in(alias_names)})
  AND doc_date >= '{month_start}'
  AND doc_date < '{month_end}'"""
    else:
        sql = f"""SELECT COALESCE(SUM({eff_agg}), 0) AS total
FROM {full_table}
WHERE supplier IN ({sql_in(alias_names)})
  AND doc_date >= '{month_start}'
  AND doc_date < '{month_end}'"""

    if sku_barcodes:
        sql += f"\n  AND barcode IN ({sql_in(sku_barcodes)})"
    if excluded_barcodes:
        sql += f"\n  AND barcode NOT IN ({sql_in(excluded_barcodes)})"
    # Фильтр "сырье" только для рабочей incoming (в эталоне колонки product_name может не быть)
    if table == "incoming_transactions" and not use_ref:
        sql += f"\n  AND NOT REGEXP_CONTAINS(LOWER(product_name), r'^сырье')"

    if group_by_barcode:
        sql += f"\nGROUP BY barcode\nHAVING SUM({amt_col}) <> 0"

    return sql

# ─── Проверка действия правила ────────────────────────────────────────────────
def rule_active_in_month(rule, month_start, month_end):
    """Проверяет, действует ли правило в указанном месяце."""
    if rule["valid_from"]:
        vf = str(rule["valid_from"])[:10]
        if month_end <= vf:
            return False
    if rule["valid_to"]:
        vt = str(rule["valid_to"])[:10]
        if month_start >= vt:
            return False
    return True

# ─── Расчёт per_portion_sold (Якобз кофе-аппараты) ──────────────────────────
def get_returns_period(rule, month_start, month_end):
    """
    Возвращает (returns_start, returns_end, warning_msg) для периода учёта возвратов.
    Если у поставщика задан returns_cutoff_day — окно возвратов расширяется до
    cutoff_day следующего месяца. Иначе совпадает с приходом.
    Также возвращает предупреждение, если cutoff ещё не наступил (данные неполные).
    """
    cutoff = rule.get("returns_cutoff_day")
    if not cutoff:
        return month_start, month_end, None

    # month_end = первое число следующего месяца, к нему прибавим cutoff-1 дней
    from datetime import date as _date, timedelta as _td
    me = _date.fromisoformat(month_end)
    returns_end_date = me + _td(days=int(cutoff) - 1)  # cutoff=12 → 12-е число след. месяца включительно
    returns_end = (returns_end_date + _td(days=1)).isoformat()  # эксклюзивная граница

    # Проверяем — наступила ли уже эта дата
    today = _date.today()
    warning = None
    if today <= returns_end_date:
        warning = (f"окно возвратов закроется {returns_end_date.isoformat()}, "
                   f"сегодня {today.isoformat()} — возвраты могут быть неполными")

    return month_start, returns_end, warning

def calc_rule_coverage(rule, aliases_for_rule, month_start, month_end, dry_run=False):
    min_sku = rule.get("min_sku_per_store") or 10
    price = rule.get("price_per_store") or 0
    year, month = int(month_start[:4]), int(month_start[5:7])
    if not price:
        print(f"  [!] {rule['brand_name']} coverage: price_per_store=0, пропуск")
        return None

    sql = f"""WITH sb AS (
  SELECT DISTINCT CAST(barcode AS STRING) AS barcode
  FROM `{BQ_PROJECT}.{BQ_DATASET}.incoming_transactions`
  WHERE supplier IN ({sql_in(aliases_for_rule)})
),
store_sku AS (
  SELECT t.store, COUNT(DISTINCT t.barcode) AS sku_count
  FROM `{BQ_PROJECT}.{BQ_DATASET}.turnover_monthly` t
  JOIN sb ON CAST(t.barcode AS STRING) = sb.barcode
  WHERE t.year = {year} AND t.month = {month}
    AND (t.end_qty > 0 OR t.start_qty > 0)
    AND t.store NOT LIKE '%Склад%'
    AND t.store NOT LIKE '%Просрок%'
  GROUP BY t.store
)
SELECT COUNT(*) AS qualified_stores FROM store_sku WHERE sku_count >= {min_sku}"""

    if dry_run:
        print(f"  {rule['brand_name']} -> покриття: >={min_sku} SKU × {price:g} грн/ТТ (без складів)")
        return None

    rows = run_bq(sql)
    qualified = int(rows[0]["qualified_stores"]) if rows else 0
    retro = (Decimal(str(qualified)) * Decimal(str(price))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "brand": rule["brand_name"], "pct": price,
        "pct_display": f"{qualified}ТТ×{price:g}грн",
        "brand_id": rule.get("brand_id"), "rule_id": rule.get("rule_id"),
        "supplier_id": rule.get("supplier_id"),
        "incoming": 0, "returns": 0, "base": qualified,
        "retro": float(retro), "retro_vat": float(retro),
        "bonus_form": rule["bonus_form"], "base_type": "coverage_per_store",
        "sku_filter": 0,
        "note": f"{qualified} ТТ з >={min_sku} SKU × {price:g} грн = {float(retro):.2f}",
        "sku_breakdown": []
    }

def calc_rule_per_portion(rule, aliases_for_rule, month_start, month_end, dry_run=False):
    """
    Расчёт ретро за порцию проданного.
    retro = SUM(quantity) × cups_per_kg × price_per_cup
    """
    cups_per_kg = rule.get("cups_per_kg", 0)
    price_per_cup = rule.get("price_per_cup", 0)
    sku = rule["sku_barcodes"]

    if not sku:
        print(f"  [!] {rule['brand_name']} per_portion_sold: нет sku_barcodes, пропуск")
        return None
    if not cups_per_kg:
        print(f"  [!] {rule['brand_name']} per_portion_sold: cups_per_kg=0, пропуск")
        return None

    q_qty = build_query("incoming_transactions", aliases_for_rule, month_start, month_end,
                        sku_barcodes=sku, agg_field="quantity")

    if dry_run:
        print(f"  {rule['brand_name']} -> {price_per_cup} грн/чашка × {cups_per_kg} чашок/кг [sku:{len(sku)}]")
        return None

    total_qty = float(run_bq(q_qty)[0]["total"])

    total_cups = total_qty * cups_per_kg
    retro = Decimal(str(total_cups)) * Decimal(str(price_per_cup))
    retro = retro.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    retro = apply_vat(retro, rule)

    bf = rule["bonus_form"]
    retro_vat = retro
    retro_vat = retro_vat.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    q_amt = build_query("incoming_transactions", aliases_for_rule, month_start, month_end,
                        sku_barcodes=sku)
    incoming_amount = float(run_bq(q_amt)[0]["total"])

    # SKU-розбивка для per_portion_sold
    sku_breakdown = []
    try:
        q_sku = build_query("incoming_transactions", aliases_for_rule, month_start, month_end,
                            sku_barcodes=sku, group_by_barcode=True)
        sku_rows = run_bq(q_sku)
        for s in sku_rows:
            s_qty = float(s["qty"])
            s_amt = float(s["amount"])
            s_cups = s_qty * cups_per_kg
            s_retro = (Decimal(str(s_cups)) * Decimal(str(price_per_cup))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            s_retro = apply_vat(s_retro, rule)
            sku_breakdown.append({
                "barcode": s["barcode"],
                "product_name": s.get("product_name") or "",
                "quantity": s_qty,
                "amount_purchased": s_amt,
                "amount_returned": 0,
                "amount_net": s_qty,  # кількість кг як база
                "applied_percent": float(price_per_cup),
                "retro_amount": float(s_retro),
            })
    except Exception as e:
        print(f"  [!] SKU-розбивка per_portion не отримана: {e}")

    return {
        "brand": rule["brand_name"],
        "pct": price_per_cup,
        "pct_display": f"{price_per_cup}грн×{cups_per_kg}ч/кг",
        "brand_id": rule.get("brand_id"),
        "rule_id": rule.get("rule_id"),
        "supplier_id": rule.get("supplier_id"),
        "incoming": incoming_amount, "returns": 0,
        "base": total_qty,
        "retro": float(retro), "retro_vat": float(retro_vat),
        "bonus_form": bf, "base_type": rule["base_type"],
        "sku_filter": len(sku),
        "note": f"qty={total_qty:.2f} кг × {cups_per_kg} чашок/кг × {price_per_cup} грн = {float(retro):.2f}",
        "sku_breakdown": sku_breakdown
    }

def calc_rule(rule, aliases_for_rule, month_start, month_end, dry_run=False, payments_by_key=None, supplier_returns_pool=None, supplier_incoming_pool=None, returns_only_aliases=None):
    """
    Рассчитывает ретро по одному правилу за месяц.
    aliases_for_rule — список имён поставщика для WHERE supplier_name IN (...).
    payments_by_key — dict {(supplier_id, period_label): amount} для base_type='payments'.
    """
    # per_portion_sold — отдельная логика
    if rule.get("base_type") == "per_portion_sold":
        return calc_rule_per_portion(rule, aliases_for_rule, month_start, month_end, dry_run)

    # coverage_per_store — покрытие торговых точек
    if rule.get("base_type") == "coverage_per_store":
        return calc_rule_coverage(rule, aliases_for_rule, month_start, month_end, dry_run)

    pct = rule["pct"]
    if pct is None:
        pct = (rule["pct_min"] + rule["pct_max"]) / 2

    # === База из оплат (supplier_payments) ===
    if rule.get("base_type") == "payments":
        period_label = month_start[:7]  # 'YYYY-MM'
        sup_id = rule.get("supplier_id")
        base = float((payments_by_key or {}).get((sup_id, period_label), 0.0))

        # Якщо є excluded_sku_barcodes — віднімаємо їх прихід з BQ від бази оплат
        # (напр. Рома: олія виключена з бази ретро, але платежі за неї є в supplier_payments)
        excl_barcodes = rule.get("excluded_sku_barcodes") or []
        excluded_incoming = 0.0
        if excl_barcodes and aliases_for_rule:
            q_excl = build_query("incoming_transactions", aliases_for_rule, month_start, month_end,
                                 sku_barcodes=excl_barcodes, excluded_barcodes=None)
            excluded_incoming = float(run_bq(q_excl)[0]["total"])
            if excluded_incoming > 0:
                print(f"    [payments] прихід excluded SKU: {excluded_incoming:,.2f} — вираховується з бази")
                base = base - excluded_incoming

        if dry_run:
            excl_info = f" −{excluded_incoming:,.2f} excl.SKU" if excluded_incoming else ""
            print(f"  {rule['brand_name']} -> {pct}% [від оплат: {float((payments_by_key or {}).get((sup_id, period_label), 0.0)):,.2f}{excl_info} = {base:,.2f}]")
            return None

        retro = Decimal(str(base)) * Decimal(str(pct)) / Decimal("100")
        retro = retro.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        retro = apply_vat(retro, rule)

        note = "база = сума оплат за місяць"
        if excluded_incoming > 0:
            note = f"база = оплати ({float((payments_by_key or {}).get((sup_id, period_label), 0.0)):,.2f}) − прихід excl.SKU ({excluded_incoming:,.2f})"
        if base == 0:
            note = "Нет оплат за период в supplier_payments"

        return {
            "brand": rule["brand_name"], "pct": pct,
            "brand_id": rule.get("brand_id"),
            "rule_id": rule.get("rule_id"),
            "supplier_id": sup_id,
            "incoming": base, "returns": 0, "base": base,
            "retro": float(retro), "retro_vat": float(retro),
            "bonus_form": rule["bonus_form"], "base_type": "payments",
            "sku_filter": 0,
            "note": note,
            "sku_breakdown": []
        }

    sku = rule["sku_barcodes"]
    excl = rule["excluded_sku_barcodes"]

    src = rule.get("income_source") or "incoming"
    q_in = build_query("incoming_transactions", aliases_for_rule, month_start, month_end,
                       sku_barcodes=sku or None, excluded_barcodes=excl or None,
                       income_source=src)

    if dry_run:
        sku_info = f" [sku:{len(sku)}]" if sku else ""
        alias_info = f" aliases={aliases_for_rule[:2]}{'...' if len(aliases_for_rule)>2 else ''}"
        print(f"  {rule['brand_name']} -> {pct}%{sku_info}{alias_info}")
        return None

    incoming = float(run_bq(q_in)[0]["total"])
    # Диагностика: если считаем по эталону — сравним с рабочей incoming
    if src == "torgsoft_ref":
        try:
            q_work = build_query("incoming_transactions", aliases_for_rule, month_start, month_end,
                                 sku_barcodes=sku or None, excluded_barcodes=excl or None,
                                 income_source="incoming")
            work_inc = float(run_bq(q_work)[0]["total"])
            if work_inc > 0:
                diff_pct = abs(incoming - work_inc) / work_inc * 100
                if diff_pct > 1.5:
                    print(f"    [i] {rule['brand_name']}: эталон {incoming:,.2f} vs рабочая {work_inc:,.2f} "
                          f"(расхождение {diff_pct:.1f}%) — беру эталон")
        except Exception:
            pass
    aliases_for_returns = aliases_for_rule + (returns_only_aliases or [])
    returns_amount = 0
    proportional_returns = False
    if rule["subtract_returns"]:
        # Вариант B: если у поставщика задан returns_cutoff_day → пропорциональное распределение
        if rule.get("returns_cutoff_day") and supplier_returns_pool is not None and supplier_incoming_pool and supplier_incoming_pool > 0:
            share = incoming / supplier_incoming_pool
            returns_amount = round(supplier_returns_pool * share, 2)
            proportional_returns = True
            print(f"    Возврат (доля): {returns_amount:>11,.2f} из {supplier_returns_pool:,.2f} общих ({share*100:.1f}%)")
        else:
            ret_start, ret_end, ret_warn = get_returns_period(rule, month_start, month_end)
            if ret_warn:
                print(f"    [!] {rule['brand_name']}: {ret_warn}")
            if returns_only_aliases:
                print(f"    [returns_only] доп.алиаси для повернень: {returns_only_aliases}")
            q_out = build_query("outgoing_to_supplier_transactions", aliases_for_returns, ret_start, ret_end,
                                sku_barcodes=sku or None, excluded_barcodes=excl or None)
            returns_amount = float(run_bq(q_out)[0]["total"])

    base = incoming - returns_amount

    if rule["threshold"] and base < float(rule["threshold"]):
        return {
            "brand": rule["brand_name"], "pct": pct,
            "brand_id": rule.get("brand_id"),
            "rule_id": rule.get("rule_id"),
            "supplier_id": rule.get("supplier_id"),
            "incoming": incoming, "returns": returns_amount, "base": base,
            "retro": 0, "retro_vat": 0,
            "bonus_form": rule["bonus_form"], "base_type": rule["base_type"],
            "sku_filter": len(sku) if sku else 0,
            "note": f"Ниже порога {rule['threshold']}",
            "sku_breakdown": []
        }

    retro = Decimal(str(base)) * Decimal(str(pct)) / Decimal("100")
    retro = retro.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    retro = apply_vat(retro, rule)

    bf = rule["bonus_form"]
    retro_vat = retro
    retro_vat = retro_vat.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Детализация по штрих-кодам (эталон Торгсофт не содержит barcode — пропускаем)
    sku_breakdown = []
    try:
        if src == "torgsoft_ref":
            raise StopIteration  # эталон без barcode — разбивку не строим
        q_in_sku = build_query("incoming_transactions", aliases_for_rule, month_start, month_end,
                               sku_barcodes=sku or None, excluded_barcodes=excl or None,
                               group_by_barcode=True, income_source=src)
        in_rows = run_bq(q_in_sku)

        out_by_bc = {}
        if rule["subtract_returns"]:
            if proportional_returns:
                # Возвраты взяты долей от общего пула — раскидываем ту же сумму по SKU
                in_total = sum(float(x["amount"]) for x in in_rows)
                if in_total:
                    for x in in_rows:
                        w = float(x["amount"]) / in_total
                        out_by_bc[x["barcode"]] = {"qty": 0, "amount": round(returns_amount * w, 2)}
            else:
                ret_start, ret_end, _ = get_returns_period(rule, month_start, month_end)
                q_out_sku = build_query("outgoing_to_supplier_transactions", aliases_for_returns,
                                        ret_start, ret_end,
                                        sku_barcodes=sku or None, excluded_barcodes=excl or None,
                                        group_by_barcode=True)
                for r in run_bq(q_out_sku):
                    out_by_bc[r["barcode"]] = {
                        "qty": float(r["qty"]),
                        "amount": float(r["amount"])
                    }

        for r in in_rows:
            bc = r["barcode"]
            in_qty = float(r["qty"])
            in_amt = float(r["amount"])
            out = out_by_bc.get(bc, {"qty": 0, "amount": 0})
            net = in_amt - out["amount"]
            sku_retro = (Decimal(str(net)) * Decimal(str(pct)) / Decimal("100")
                        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            sku_retro = apply_vat(sku_retro, rule)
            sku_breakdown.append({
                "barcode": bc,
                "product_name": r.get("product_name") or "",
                "quantity": in_qty,
                "amount_purchased": in_amt,
                "amount_returned": out["amount"],
                "amount_net": net,
                "applied_percent": float(pct),
                "retro_amount": float(sku_retro),
            })
    except StopIteration:
        pass  # эталон Торгсофт: SKU-разбивка не строится, это ожидаемо
    except Exception as e:
        import traceback
        print(f"\n  [!] SKU-разбивка не получена для {rule['brand_name']}: {type(e).__name__}: {e}")
        traceback.print_exc()

    return {
        "brand": rule["brand_name"], "pct": pct,
        "brand_id": rule.get("brand_id"),
        "rule_id": rule.get("rule_id"),
        "supplier_id": rule.get("supplier_id"),
        "incoming": incoming, "returns": returns_amount, "base": base,
        "retro": float(retro), "retro_vat": float(retro_vat),
        "bonus_form": bf, "base_type": rule["base_type"],
        "sku_filter": len(sku) if sku else 0, "note": "",
        "sku_breakdown": sku_breakdown
    }


# ─── Расчёт по поставщику ────────────────────────────────────────────────────
def calculate_supplier(sup_name, rules_list, all_sup_aliases, alias_by_brand,
                       month_start, month_end, dry_run=False, payments_by_key=None,
                       returns_only_by_brand=None):
    returns_only_by_brand = returns_only_by_brand or {}
    """
    Для каждого правила определяет «свои» алиасы:
    1. base_type='payments' → алиасы не нужны, база из supplier_payments
    2. Есть brand-level aliases → использовать только их
    3. Нет brand aliases, но есть sku_barcodes → все алиасы поставщика + фильтр по sku
    4. Ни того ни другого → все алиасы поставщика (группируем одинаковые %)
    """
    active = [r for r in rules_list if rule_active_in_month(r, month_start, month_end)]
    if not active:
        return []

    details = []

    # Сначала отдельно обрабатываем правила payments — им алиасы не нужны
    payments_rules = [r for r in active if r.get("base_type") == "payments"]
    other_rules = [r for r in active if r.get("base_type") != "payments"]

    # Вариант B: один раз считаем общий приход и возвраты поставщика, если есть returns_cutoff_day
    supplier_returns_pool = None
    supplier_incoming_pool = None
    cutoff_rules = [r for r in other_rules if r.get("returns_cutoff_day") and r.get("subtract_returns")]
    if cutoff_rules and not dry_run and all_sup_aliases:
        from datetime import datetime, timedelta
        cd = cutoff_rules[0].get("returns_cutoff_day")
        ms = datetime.strptime(month_start, "%Y-%m-%d")
        next_month = (ms.replace(day=28) + timedelta(days=4)).replace(day=1)
        ret_end_pool = (next_month + timedelta(days=int(cd))).strftime("%Y-%m-%d")
        today = datetime.today().strftime("%Y-%m-%d")
        if today < ret_end_pool:
            print(f"  [!] {sup_name}: окно возвратов закроется {ret_end_pool}, сегодня {today} — данные могут быть неполными")
        q_in_sup = build_query("incoming_transactions", all_sup_aliases, month_start, month_end)
        supplier_incoming_pool = float(run_bq(q_in_sup)[0]["total"])
        q_out_sup = build_query("outgoing_to_supplier_transactions", all_sup_aliases, month_start, ret_end_pool)
        supplier_returns_pool = float(run_bq(q_out_sup)[0]["total"])
        print(f"  [pool] {sup_name}: приход={supplier_incoming_pool:,.2f}, возвраты={supplier_returns_pool:,.2f} (окно до {ret_end_pool})")

    for r in payments_rules:
        # Якщо є excluded_sku_barcodes — потрібні алиаси для BQ-запиту (вираховуємо прихід excl. SKU)
        pay_aliases = all_sup_aliases if r.get("excluded_sku_barcodes") else []
        detail = calc_rule(r, pay_aliases, month_start, month_end, dry_run, payments_by_key=payments_by_key)
        if detail:
            details.append(detail)

    if not other_rules:
        return details

    # Разделяем правила по способу резолвинга
    resolved = []
    unresolved = []

    for r in other_rules:
        brand_aliases = alias_by_brand.get(r["brand_id"], [])
        if brand_aliases:
            resolved.append((r, brand_aliases, "brand"))
        elif r["sku_barcodes"]:
            resolved.append((r, all_sup_aliases, "sku"))
        else:
            unresolved.append(r)

    # 1. Считаем resolved правила
    for r, rule_aliases, method in resolved:
        r_only = returns_only_by_brand.get(r["brand_id"], [])
        detail = calc_rule(r, rule_aliases, month_start, month_end, dry_run, payments_by_key=payments_by_key, supplier_returns_pool=supplier_returns_pool, supplier_incoming_pool=supplier_incoming_pool, returns_only_aliases=r_only)
        if detail:
            details.append(detail)

    # 2. Unresolved правила — считаем по ОСТАВШИМСЯ алиасам
    if unresolved:
        branded_aliases = set()
        for brand_id, brand_alias_list in alias_by_brand.items():
            branded_aliases.update(brand_alias_list)
        for r, rule_aliases, method in resolved:
            if method == "brand":
                branded_aliases.update(rule_aliases)

        remainder_aliases = [a for a in all_sup_aliases if a not in branded_aliases]

        if not remainder_aliases:
            brand_names = ", ".join(r["brand_name"] for r in unresolved)
            if dry_run:
                print(f"  [!] {brand_names} -> нет оставшихся алиасов, пропуск")
            return details

        by_pct = defaultdict(list)
        for r in unresolved:
            p = r["pct"] if r["pct"] is not None else (r["pct_min"] + r["pct_max"]) / 2
            by_pct[p].append(r)

        if len(by_pct) == 1:
            pct = list(by_pct.keys())[0]
            group = list(by_pct.values())[0]
            brand_names = ", ".join(sorted(set(r["brand_name"] for r in group)))
            merged = {**group[0], "brand_name": brand_names, "pct": pct}
            detail = calc_rule(merged, remainder_aliases, month_start, month_end, dry_run, payments_by_key=payments_by_key, supplier_returns_pool=supplier_returns_pool, supplier_incoming_pool=supplier_incoming_pool)
            if detail:
                if branded_aliases:
                    detail["note"] = f"остаток алиасов: {remainder_aliases}"
                details.append(detail)
        else:
            brand_names = ", ".join(sorted(set(r["brand_name"] for r in unresolved)))
            if dry_run:
                for pct, group in by_pct.items():
                    bns = ", ".join(r["brand_name"] for r in group)
                    print(f"  [!] {bns} -> {pct}% (остаток алиасов: {remainder_aliases}, неточно)")
                return details

            total = len(unresolved)
            avg_pct = sum(r["pct"] if r["pct"] is not None else (r["pct_min"] if r["pct_max"] is None else (r["pct_min"]+r["pct_max"])/2) for r in unresolved) / total
            merged = {**unresolved[0], "brand_name": brand_names,
                      "pct": avg_pct, "sku_barcodes": [], "excluded_sku_barcodes": []}
            detail = calc_rule(merged, remainder_aliases, month_start, month_end, dry_run, payments_by_key=payments_by_key, supplier_returns_pool=supplier_returns_pool, supplier_incoming_pool=supplier_incoming_pool)
            if detail:
                detail["note"] = f"НЕТОЧНО: средний % ({avg_pct:.1f}%), остаток алиасов: {remainder_aliases}"
                details.append(detail)

    return details

# ─── Главный расчёт ──────────────────────────────────────────────────────────
def calculate_month(supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
                    monthly_bonuses, payments_by_key, month_str, filter_supplier=None, dry_run=False, verify=False):
    """Расчёт ретро за один месяц по всем поставщикам."""
    year, month = map(int, month_str.split("-"))
    month_start = f"{year}-{month:02d}-01"
    if month == 12:
        month_end = f"{year+1}-01-01"
    else:
        month_end = f"{year}-{month+1:02d}-01"

    print(f"\n{'='*70}")
    print(f"  РАСЧЁТ РЕТРО ЗА {month_str}")
    print(f"  Период: {month_start} -- {month_end}")
    print(f"{'='*70}")

    results = {}
    total_retro = Decimal("0")
    total_retro_vat = Decimal("0")

    for sup_id, rules_list in sorted(supplier_rules.items(),
                                      key=lambda x: supplier_map.get(x[0], {}).get("name", "")):
        sup_name = supplier_map.get(sup_id, {}).get("name", "???")

        if filter_supplier and filter_supplier.lower() not in sup_name.lower():
            continue

        al = alias_by_supplier.get(sup_id, [])
        if not al:
            print(f"\n[!] {sup_name}: нет алиасов, пропускаем")
            continue

        print(f"\n{'---'*17}")
        print(f"  {sup_name} ({len(al)} алиасов, {len(rules_list)} правил)")

        details = calculate_supplier(sup_name, rules_list, al, alias_by_brand,
                                     month_start, month_end, dry_run,
                                     payments_by_key=payments_by_key,
                                     returns_only_by_brand=returns_only_by_brand)

        if not dry_run and details:
            supplier_retro = sum(Decimal(str(d["retro"])) for d in details)
            supplier_retro_vat = sum(Decimal(str(d["retro_vat"])) for d in details)
                        # Месячные фикс-бонусы
            mb_list = monthly_bonuses.get(sup_id, [])
            for mb in mb_list:
                vf = str(mb.get("valid_from") or "")[:10]
                vt = str(mb.get("valid_to") or "")[:10] if mb.get("valid_to") else None
                if vf and month_end <= vf:
                    continue
                if vt and month_start >= vt:
                    continue

                bonus_amt = Decimal(str(mb["amount"]))
                bonus_form = mb.get("bonus_form") or "marketing_service"
                bonus_vat = bonus_amt
                bonus_vat = bonus_vat.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                supplier_retro += bonus_amt
                supplier_retro_vat += bonus_vat

                desc = mb.get("description") or "Месячный бонус"
                print(f"  + {desc}: {bonus_amt:,.2f} грн (фикс)")

                details.append({
                    "brand": f"[БОНУС] {desc}",
                    "pct": 0,
                    "brand_id": None,
                    "rule_id": None,
                    "supplier_id": sup_id,
                    "incoming": 0, "returns": 0, "base": 0,
                    "retro": float(bonus_amt), "retro_vat": float(bonus_vat),
                    "bonus_form": bonus_form,
                    "base_type": "fixed_monthly",
                    "sku_filter": 0,
                    "note": "Фиксированный ежемесячный бонус"
                })

            total_retro += supplier_retro
            total_retro_vat += supplier_retro_vat

            for d in details:
                sku_info = f" [sku:{d['sku_filter']}]" if d.get("sku_filter") else ""
                base_info = " [от оплат]" if d.get("base_type") == "payments" else ""
                vat_info = ""

                if d.get("base_type") == "per_portion_sold":
                    pct_disp = d.get("pct_display", "")
                    print(f"  {d['brand']} [{pct_disp}]{sku_info}:")
                    print(f"    Закупка: {d['incoming']:>11,.2f} грн")
                    print(f"    Ретро:  {d['retro']:>12,.2f}{vat_info}")
                    if d.get("note"):
                        print(f"    {d['note']}")
                elif d.get("base_type") == "coverage_per_store":
                    pct_disp = d.get("pct_display", "")
                    print(f"  {d['brand']} [{pct_disp}]:")
                    print(f"    Квалiф. ТТ: {int(d['base'])}")
                    print(f"    Ретро:  {d['retro']:>12,.2f}{vat_info}")
                    if d.get("note"):
                        print(f"    {d['note']}")
                else:
                    print(f"  {d['brand']} {d['pct']}%{sku_info}{base_info}:")
                    print(f"    Приход: {d['incoming']:>12,.2f}")
                    if d["returns"]:
                        print(f"    Возврат: {d['returns']:>11,.2f}")
                    print(f"    База:   {d['base']:>12,.2f}")
                    print(f"    Ретро:  {d['retro']:>12,.2f}{vat_info}")
                    if d.get("note"):
                        print(f"    [!] {d['note']}")

            vat_extra = ""            
            print(f"  -------------------------")
            print(f"  ИТОГО {sup_name}: {supplier_retro:,.2f}{vat_extra}")

            # ── Верификация: общая сумма закупок vs сумма по брендам (--verify) ──
            if verify:
                resolved_incoming = sum(
                    d["incoming"] for d in details
                    if d.get("base_type") != "per_portion_sold"
                )
                if resolved_incoming > 0:
                    try:
                        q_total = build_query("incoming_transactions", al, month_start, month_end)
                        total_incoming = float(run_bq(q_total)[0]["total"])
                        gap = total_incoming - resolved_incoming
                        gap_pct = (gap / total_incoming * 100) if total_incoming > 0 else 0
                        if abs(gap_pct) > 1.0:
                            print(f"  ⚠ ВЕРИФИКАЦИЯ: общая закупка {total_incoming:,.2f}, "
                                  f"учтено {resolved_incoming:,.2f}, "
                                  f"разрыв {gap:,.2f} ({gap_pct:.1f}%)")
                    except Exception as e:
                        print(f"  ⚠ Верификация пропущена: {e}")

            results[sup_name] = {
                "details": details,
                "total": float(supplier_retro),
                "total_vat": float(supplier_retro_vat),
            }

    if not dry_run:
        print(f"\n{'='*70}")
        print(f"  ИТОГО ЗА {month_str}: {total_retro:,.2f} грн")
        print(f"{'='*70}")

    return results

# ─── Сводная таблица ──────────────────────────────────────────────────────────
def print_summary(all_results, months):
    """Выводит сводную таблицу по месяцам."""
    print(f"\n\n{'='*90}")
    print("  СВОДНАЯ ТАБЛИЦА РЕТРО-БОНУСОВ 2026")
    print(f"{'='*90}")

    all_suppliers = sorted(set(s for mr in all_results.values() for s in mr))

    header = f"{'Поставщик':<35}"
    for m in months:
        header += f" {m:>12}"
    header += f" {'ИТОГО':>14}"
    print(header)
    print("-" * len(header))

    grand_totals = {m: 0 for m in months}
    grand_total = 0

    for sup in all_suppliers:
        row = f"{sup[:34]:<35}"
        sup_total = 0
        for m in months:
            val = all_results.get(m, {}).get(sup, {}).get("total", 0)
            row += f" {val:>12,.2f}"
            grand_totals[m] += val
            sup_total += val
        row += f" {sup_total:>14,.2f}"
        grand_total += sup_total
        print(row)

    print("-" * len(header))
    footer = f"{'ИТОГО':<35}"
    for m in months:
        footer += f" {grand_totals[m]:>12,.2f}"
    footer += f" {grand_total:>14,.2f}"
    print(footer)

# ─── Экспорт в CSV ───────────────────────────────────────────────────────────
def export_csv(all_results, months, output_path):
    """Экспортирует результаты в CSV."""
    import csv
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Поставщик", "Бренд", "%", "Форма"] + months + ["ИТОГО"])

        all_suppliers = sorted(set(s for mr in all_results.values() for s in mr))

        for sup in all_suppliers:
            brand_data = defaultdict(lambda: {"months": {m: 0 for m in months}, "pct": "", "form": ""})
            for m in months:
                for d in all_results.get(m, {}).get(sup, {}).get("details", []):
                    bn = d["brand"]
                    brand_data[bn]["months"][m] += d["retro"]
                    brand_data[bn]["pct"] = f"{d['pct']}%"
                    brand_data[bn]["form"] = d.get("bonus_form", "")

            for bn in sorted(brand_data):
                bd = brand_data[bn]
                values = [bd["months"][m] for m in months]
                total = sum(values)
                writer.writerow([
                    sup, bn, bd["pct"], bd["form"],
                    *[f"{v:.2f}" for v in values],
                    f"{total:.2f}"
                ])

    print(f"\n[>] Результаты сохранены: {output_path}")

# ─── Сохранение в Supabase ───────────────────────────────────────────────────
def save_to_supabase(all_results, months, supplier_rules):
    """
    Записывает результаты расчёта в retro_calculations + retro_calculation_details + retro_calculation_sku_details.
    Удаляет старые записи за те же периоды перед вставкой.
    """
    print(f"\n[i] Сохранение результатов в Supabase...")

    saved_calcs = 0
    saved_details = 0
    saved_skus = 0

    for month in months:
        month_results = all_results.get(month, {})
        if not month_results:
            continue

        year, mon = map(int, month.split("-"))
        period_start = f"{year}-{mon:02d}-01"
        if mon == 12:
            period_end = f"{year+1}-01-01"
        else:
            period_end = f"{year}-{mon+1:02d}-01"

        for sup_name, sup_result in month_results.items():
            details = sup_result.get("details", [])
            if not details:
                continue

            # supplier_id из первого detail
            sup_id = None
            for d in details:
                if d.get("supplier_id"):
                    sup_id = d["supplier_id"]
                    break
            if not sup_id:
                for sid, rules in supplier_rules.items():
                    if rules and rules[0]["supplier_name"] == sup_name:
                        sup_id = sid
                        break
            if not sup_id:
                continue

# Удаляем старые записи (каскадно)
            old = sb_get("retro_calculations",
                         f"period_label=eq.{month}&supplier_id=eq.{sup_id}&select=id,status")

            # Проверяем approved/paid ПЕРЕД удалением — если есть, пропускаем весь месяц
            locked = any(o.get('status') in ('approved', 'paid') for o in old)
            if locked:
                locked_status = next(o['status'] for o in old if o.get('status') in ('approved', 'paid'))
                print(f"  [skip] {sup_name} {month} — статус {locked_status}, пропускаємо")
                continue

            # Ручные доплаты/вычеты живут в retro_adjustments и воссоздаются при каждом сохранении.
            # Грузим ДО удаления старого расчёта: если запрос упадёт, старые данные останутся.
            adjs = sb_get("retro_adjustments",
                          f"supplier_id=eq.{sup_id}&period_label=eq.{month}"
                          "&select=id,supplier_brand_id,amount,bonus_form,notes")
            if not isinstance(adjs, list):
                raise RuntimeError(f"retro_adjustments недоступна ({adjs}) — сохранение остановлено, старый расчёт не тронут")

            for o in old:
                sb_delete("retro_calculation_sku_details", f"calculation_id=eq.{o['id']}")
                sb_delete("retro_calculation_details", f"calculation_id=eq.{o['id']}")
                sb_delete("retro_calculations", f"id=eq.{o['id']}")


            total_purchase = sum(d.get("incoming", 0) for d in details)
            total_returns = sum(d.get("returns", 0) for d in details)
            total_base = sum(d.get("base", 0) for d in details)
            total_retro = sup_result.get("total", 0)
            total_retro = round(float(total_retro) + sum(float(a["amount"]) for a in adjs), 2)

            calc = sb_post("retro_calculations", {
                "period_start": period_start,
                "period_end": period_end,
                "period_label": month,
                "supplier_id": sup_id,
                "total_purchase": total_purchase,
                "total_returns": total_returns,
                "total_base": total_base,
                "total_retro": total_retro,
                "status": "completed",
            })
            calc_id = calc[0]["id"]
            saved_calcs += 1

            for d in details:
                detail_post = sb_post("retro_calculation_details", {
                    "calculation_id": calc_id,
                    "supplier_brand_id": d.get("brand_id"),
                    "retro_rule_id": d.get("rule_id"),
                    "amount_purchased": d.get("incoming", 0),
                    "amount_returned": d.get("returns", 0),
                    "amount_net": d.get("base", 0),
                    "applied_percent": d.get("pct", 0),
                    "retro_amount": d.get("retro", 0),
                    "retro_amount_vat": d.get("retro_vat", 0),
                    "bonus_form": d.get("bonus_form", "price_correction"),
                    "notes": d.get("note", ""),
                })
                detail_id = detail_post[0]["id"]
                saved_details += 1

                # SKU-разбивка (не зберігаємо для payments — база від оплат, не від товарів)
                sku_list = [] if d.get("base_type") == "payments" else (d.get("sku_breakdown") or [])
                for sku in sku_list:
                    try:
                        sb_post("retro_calculation_sku_details", {
                            "calculation_id": calc_id,
                            "detail_id": detail_id,
                            "supplier_brand_id": d.get("brand_id"),
                            "barcode": sku["barcode"],
                            "product_name": sku.get("product_name") or "",
                            "quantity": sku.get("quantity", 0),
                            "amount_purchased": sku.get("amount_purchased", 0),
                            "amount_returned": sku.get("amount_returned", 0),
                            "amount_net": sku.get("amount_net", 0),
                            "applied_percent": sku.get("applied_percent", 0),
                            "retro_amount": sku.get("retro_amount", 0),
                        })
                        saved_skus += 1
                    except Exception as e:
                        print(f"  [!] Ошибка сохранения SKU {sku.get('barcode')}: {e}")

            for a in adjs:
                sb_post("retro_calculation_details", {
                    "calculation_id": calc_id, "supplier_brand_id": a.get("supplier_brand_id"),
                    "retro_rule_id": None, "amount_purchased": 0, "amount_returned": 0, "amount_net": 0,
                    "applied_percent": 0, "retro_amount": float(a["amount"]), "retro_amount_vat": float(a["amount"]),
                    "bonus_form": a.get("bonus_form") or "price_correction", "notes": a["notes"],
                    "adjustment_id": a["id"],
                })
                saved_details += 1

    print(f"  Записано: {saved_calcs} calculations, {saved_details} details, {saved_skus} SKU-строк")
# ─── Аудит: бренды без начислений ────────────────────────────────────────────
def show_brands_without_retro(supplier_rules, alias_by_supplier, alias_by_brand, supplier_map):
    """
    Показывает бренды/правила, которые не рассчитываются:
    - нет алиасов у поставщика
    - branded aliases все заняты, remainder пуст
    - per_portion_sold без cups_per_kg или sku
    """
    print(f"\n{'='*70}")
    print("  АУДИТ: бренды/правила БЕЗ начислений")
    print(f"{'='*70}")

    issues_found = 0

    for sup_id, rules_list in sorted(supplier_rules.items(),
                                      key=lambda x: supplier_map.get(x[0], {}).get("name", "")):
        sup_name = supplier_map.get(sup_id, {}).get("name", "???")
        all_aliases = alias_by_supplier.get(sup_id, [])

        if not all_aliases:
            print(f"\n  [!] {sup_name}: НЕТ АЛИАСОВ — {len(rules_list)} правил не будут посчитаны")
            for r in rules_list:
                pct_display = r['pct'] if r['pct'] else f"{r['pct_min']}-{r['pct_max']}"
                print(f"      - {r['brand_name']} {pct_display}%")
            issues_found += len(rules_list)
            continue

        # Определяем resolved vs unresolved
        branded_aliases = set()
        for brand_id, brand_alias_list in alias_by_brand.items():
            branded_aliases.update(brand_alias_list)

        remainder = [a for a in all_aliases if a not in branded_aliases]

        problems = []
        for r in rules_list:
            brand_aliases = alias_by_brand.get(r["brand_id"], [])

            if r["base_type"] == "per_portion_sold":
                if not r.get("sku_barcodes"):
                    problems.append((r, "per_portion_sold без sku_barcodes"))
                elif not r.get("cups_per_kg"):
                    problems.append((r, "per_portion_sold без cups_per_kg в notes"))
            elif not brand_aliases and not r.get("sku_barcodes"):
                # Unresolved — нужен remainder
                if not remainder:
                    problems.append((r, "нет remainder алиасов (все привязаны к брендам)"))

        if problems:
            print(f"\n  {sup_name}:")
            print(f"    Алиасы: {len(all_aliases)} всего, {len(branded_aliases & set(all_aliases))} branded, {len(remainder)} remainder")
            if remainder:
                print(f"    Remainder: {remainder}")
            for r, reason in problems:
                pct_str = f"{r['pct']}%" if r['pct'] is not None else f"{r['pct_min']}-{r['pct_max']}%"
                print(f"    [!] {r['brand_name']} ({pct_str}) — {reason}")
            issues_found += len(problems)

    if issues_found == 0:
        print("\n  Все правила имеют алиасы/sku для расчёта.")
    else:
        print(f"\n  Найдено проблем: {issues_found}")

    print(f"{'='*70}\n")


# ─── Построение списка месяцев ───────────────────────────────────────────────
def build_months(start_month, end_month=None):
    """Строит список месяцев YYYY-MM от start до end включительно."""
    start_y, start_m = map(int, start_month.split("-"))
    end_y, end_m = (map(int, end_month.split("-"))) if end_month else (start_y, start_m)
    months = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        months.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


# ─── Запуск расчёта ──────────────────────────────────────────────────────────
def run_calculation(months, supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
                    monthly_bonuses, payments_by_key, filter_supplier=None, dry_run=False, verify=False, no_save=False, csv_path=None):
    """Запускает расчёт ретро за выбранные месяцы."""
    print(f"\n>>> Расчёт ретро за: {', '.join(months)}")
    if filter_supplier:
        print(f">>> Фильтр: {filter_supplier}")
    if dry_run:
        print(">>> Режим dry-run: только SQL-запросы")
    if verify:
        print(">>> Верификация: включена")

    all_results = {}
    for month in months:
        all_results[month] = calculate_month(
            supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
            monthly_bonuses, payments_by_key, month,
            filter_supplier=filter_supplier, dry_run=dry_run, verify=verify
        )

    if not dry_run and months:
        print_summary(all_results, months)

        if not no_save:
            save_to_supabase(all_results, months, supplier_rules)

        output_dir = Path(__file__).resolve().parent.parent / "output"
        output_dir.mkdir(exist_ok=True)
        out_csv = csv_path or str(output_dir / f"retro_results_{months[0]}_{months[-1]}.csv")
        try:
            export_csv(all_results, months, out_csv)
        except PermissionError:
            print(f"\n  Не удалось записать CSV ({out_csv}) — файл открыт.")
            print("  Данные в Supabase сохранены, CSV пропущен.")


# ─── Интерактивное меню ──────────────────────────────────────────────────────
def interactive_menu():
    """Интерактивное меню для выбора режима расчёта."""
    print()
    print("=" * 60)
    print("  RETRO BONUS CALCULATOR — Family Market")
    print("=" * 60)

    # Загружаем справочники один раз
    supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map, monthly_bonuses, payments_by_key = load_reference_data()

    while True:
        print()
        print("-" * 60)
        print("  МЕНЮ:")
        print("  1. Полная загрузка (янв 2026 — прошлый месяц)")
        print("  2. Выбрать один месяц")
        print("  3. Выбрать диапазон месяцев")
        print("  4. Расчёт по конкретному поставщику")
        print("  5. Расчёт с верификацией (сверка закупок)")
        print("  6. Dry-run (только SQL, без расчёта)")
        print("  7. Аудит: бренды без начислений")
        print("  8. Перезагрузить справочники из Supabase")
        print("  0. Выход")
        print("-" * 60)

        choice = input("  Выберите пункт [0-8]: ").strip()

        if choice == "0":
            print("\n  До свидания!")
            break

        elif choice == "1":
            # Полная загрузка: 2026-01 до прошлого месяца
            today = date.today()
            prev_m = today.month - 1
            prev_y = today.year
            if prev_m == 0:
                prev_m = 12
                prev_y -= 1
            end_month = f"{prev_y}-{prev_m:02d}"
            months = build_months("2026-01", end_month)
            if not months:
                print("  Нет месяцев для расчёта.")
                continue
            print(f"\n  Период: 2026-01 — {end_month} ({len(months)} мес.)")
            save = input("  Сохранить в Supabase? [Y/n]: ").strip().lower()
            no_save = save in ("n", "no", "н", "нет")
            run_calculation(months, supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
                            monthly_bonuses, payments_by_key,
 no_save=no_save)

        elif choice == "2":
            month = input("  Введите месяц (YYYY-MM): ").strip()
            if not month:
                continue
            months = build_months(month)
            save = input("  Сохранить в Supabase? [Y/n]: ").strip().lower()
            no_save = save in ("n", "no", "н", "нет")
            run_calculation(months, supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
                            monthly_bonuses, payments_by_key,
 no_save=no_save)

        elif choice == "3":
            start = input("  Начальный месяц (YYYY-MM): ").strip()
            end = input("  Конечный месяц (YYYY-MM): ").strip()
            if not start or not end:
                continue
            months = build_months(start, end)
            print(f"  Период: {start} — {end} ({len(months)} мес.)")
            save = input("  Сохранить в Supabase? [Y/n]: ").strip().lower()
            no_save = save in ("n", "no", "н", "нет")
            run_calculation(months, supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
                            monthly_bonuses, payments_by_key,
 no_save=no_save)

        elif choice == "4":
            # Список поставщиков для выбора
            sup_names = sorted(set(
                supplier_map.get(sid, {}).get("name", "???")
                for sid in supplier_rules
            ))
            print(f"\n  Поставщики с правилами ({len(sup_names)}):")
            for i, name in enumerate(sup_names, 1):
                rule_count = sum(1 for sid in supplier_rules if supplier_map.get(sid, {}).get("name") == name
                                 for _ in supplier_rules[sid])
                print(f"    {i:3d}. {name} ({rule_count} правил)")

            sel = input("\n  Введите номер или часть имени: ").strip()
            if not sel:
                continue

            filter_sup = None
            if sel.isdigit():
                idx = int(sel) - 1
                if 0 <= idx < len(sup_names):
                    filter_sup = sup_names[idx]
            if not filter_sup:
                filter_sup = sel

            month_choice = input("  Месяц или диапазон (YYYY-MM [YYYY-MM]), Enter=полный: ").strip()
            if month_choice:
                parts = month_choice.split()
                months = build_months(parts[0], parts[1] if len(parts) > 1 else None)
            else:
                today = date.today()
                prev_m = today.month - 1
                prev_y = today.year
                if prev_m == 0:
                    prev_m = 12
                    prev_y -= 1
                months = build_months("2026-01", f"{prev_y}-{prev_m:02d}")

            print(f"  Поставщик: {filter_sup}, период: {months[0]}—{months[-1]}")
            save = input("  Зберегти в Supabase? [Y/n]: ").strip().lower()
            no_save = save in ("n", "no", "н", "нет")
            run_calculation(months, supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
                            monthly_bonuses, payments_by_key,
 filter_supplier=filter_sup, no_save=no_save)

        elif choice == "5":
            # С верификацией
            month_choice = input("  Месяц или диапазон (YYYY-MM [YYYY-MM]), Enter=полный: ").strip()
            if month_choice:
                parts = month_choice.split()
                months = build_months(parts[0], parts[1] if len(parts) > 1 else None)
            else:
                today = date.today()
                prev_m = today.month - 1
                prev_y = today.year
                if prev_m == 0:
                    prev_m = 12
                    prev_y -= 1
                months = build_months("2026-01", f"{prev_y}-{prev_m:02d}")

            print(f"  Период: {months[0]}—{months[-1]} с верификацией")
            save = input("  Сохранить в Supabase? [Y/n]: ").strip().lower()
            no_save = save in ("n", "no", "н", "нет")
            run_calculation(months, supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
                            monthly_bonuses, payments_by_key,
 verify=True, no_save=no_save)


        elif choice == "6":
            month = input("  Месяц для dry-run (YYYY-MM): ").strip()
            if not month:
                continue
            months = build_months(month)
            run_calculation(months, supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
                            monthly_bonuses, payments_by_key,
 dry_run=True, no_save=True)

        elif choice == "7":
            show_brands_without_retro(supplier_rules, alias_by_supplier, alias_by_brand, supplier_map)

        elif choice == "8":
            print("\n  Перезагрузка справочников...")
            supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map, monthly_bonuses, payments_by_key = load_reference_data()
            print("  Готово!")

        else:
            print("  Неверный выбор, попробуйте снова.")


# ─── CLI ──────────────────────────────────────────────────────────────────────
def main():
    # Если аргументы командной строки — старый режим (для bat-файла и автоматизации)
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--menu"):
        parser = argparse.ArgumentParser(description="Расчёт ретро-бонусов Family Market")
        parser.add_argument("start_month", help="Начальный месяц (YYYY-MM)")
        parser.add_argument("end_month", nargs="?", help="Конечный месяц (YYYY-MM)")
        parser.add_argument("--supplier", "-s", help="Фильтр по имени поставщика (подстрока)")
        parser.add_argument("--dry-run", action="store_true", help="Только показать SQL-запросы")
        parser.add_argument("--csv", help="Путь для экспорта CSV")
        parser.add_argument("--no-save", action="store_true", help="Не сохранять в Supabase")
        parser.add_argument("--verify", action="store_true", help="Верификация: сверка общей суммы закупок vs учтённой по брендам")
        args = parser.parse_args()

        months = build_months(args.start_month, args.end_month)

        print(f">>> Расчёт ретро за: {', '.join(months)}")
        if args.supplier:
            print(f">>> Фильтр: {args.supplier}")
        if args.dry_run:
            print(">>> Режим dry-run: только SQL-запросы")

        supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map, monthly_bonuses, payments_by_key = load_reference_data()

        run_calculation(months, supplier_rules, alias_by_supplier, alias_by_brand, returns_only_by_brand, supplier_map,
                        monthly_bonuses, payments_by_key, filter_supplier=args.supplier, dry_run=args.dry_run,
                        verify=args.verify, no_save=args.no_save, csv_path=args.csv)
    else:
        # Без аргументов или --menu → интерактивное меню
        interactive_menu()

if __name__ == "__main__":
    main()

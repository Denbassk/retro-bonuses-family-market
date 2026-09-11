#!/usr/bin/env python3
"""
fix_brand_aliases.py — Автопривязка алиасов к брендам.

1. Алиасы без supplier_brand_id + у поставщика 1 бренд → автопривязка.
2. Алиасы без supplier_brand_id + несколько брендов → анализ товаров в BQ,
   сопоставление по ключевым словам бренда в названии товара.
3. Новые supplier names из BQ, которых нет в алиасах → предложение создать.

Запуск:
  python fix_brand_aliases.py                 # dry-run (только отчёт)
  python fix_brand_aliases.py --apply         # применить изменения в Supabase
"""

import os
import sys
import json
import argparse
import urllib.request
from pathlib import Path
from collections import defaultdict

# ─── .env ────────────────────────────────────────────────────────────────────
def load_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

load_env()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
BQ_PROJECT   = os.environ.get("BQ_PROJECT", "family-market-analytics")
BQ_DATASET   = os.environ.get("BQ_DATASET", "family_market")

def sb_get(table, params=""):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def sb_patch(table, params, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="PATCH", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    })
    with urllib.request.urlopen(req) as resp:
        return resp.status

def sb_post(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def run_bq(sql):
    from google.cloud import bigquery
    global _bq
    try:
        _bq
    except NameError:
        _bq = bigquery.Client(project=BQ_PROJECT)
    return [dict(r.items()) for r in _bq.query(sql).result()]

# ═══════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Применить изменения в Supabase")
    args = parser.parse_args()

    print("=" * 80)
    print("  АВТОПРИВЯЗКА АЛИАСОВ К БРЕНДАМ")
    print("  Режим:", "APPLY" if args.apply else "DRY-RUN (только отчёт)")
    print("=" * 80)

    # ─── 1. Загрузка справочников ────────────────────────────────────────
    # Ручные override-ы: alias_name → brand_name (когда авто-сопоставление ошибается)
    MANUAL_BRAND_OVERRIDE = {
        "Мінеральні Води України": "Пепси Кола",
        "Гама": "Фаст фуд",
        "Авангард Дистрибуції": "штучка",
        "ФОП Кульомза Роман Миколайович": "Селедка",
        "Форвард-св": "химия",
        "Агропром": "стаканы",
    }

    print("\n[1] Загрузка Supabase...")
    aliases = sb_get("supplier_aliases", "select=id,alias_name,supplier_id,supplier_brand_id")
    brands = sb_get("supplier_brands", "select=id,name,supplier_id")
    suppliers = sb_get("suppliers", "select=id,name,is_retro_active")

    supplier_map = {s["id"]: s for s in suppliers}
    # supplier_id → [brand, ...]
    brands_by_sup = defaultdict(list)
    for b in brands:
        brands_by_sup[b["supplier_id"]].append(b)

    # Алиасы без brand привязки
    no_brand = [a for a in aliases if not a.get("supplier_brand_id")]
    with_brand = [a for a in aliases if a.get("supplier_brand_id")]
    print(f"  Алиасов всего: {len(aliases)}, с brand: {len(with_brand)}, без brand: {len(no_brand)}")

    # ─── 2. Загрузка BQ supplier names ───────────────────────────────────
    print("\n[2] Загрузка уникальных supplier из BQ 2026...")
    bq_suppliers = run_bq(f"""
        SELECT supplier, COUNT(*) AS tx,
               ROUND(SUM(amount_purchase), 2) AS total
        FROM `{BQ_PROJECT}.{BQ_DATASET}.incoming_transactions`
        WHERE doc_date >= '2026-01-01' AND supplier IS NOT NULL AND TRIM(supplier) != ''
        GROUP BY supplier
    """)
    bq_map = {r["supplier"]: r for r in bq_suppliers}
    print(f"  Уникальных supplier в BQ: {len(bq_suppliers)}")

    # ─── 3. Автопривязка: 1 бренд → автоматически ────────────────────────
    print(f"\n{'=' * 80}")
    print("  ЭТАП A: ОДНОБРЕНДОВЫЕ ПОСТАВЩИКИ (автопривязка)")
    print(f"{'=' * 80}")

    auto_linked = 0
    still_unresolved = []

    for a in no_brand:
        sup_id = a["supplier_id"]
        sup = supplier_map.get(sup_id, {})
        sup_name = sup.get("name", "???")
        sup_brands = brands_by_sup.get(sup_id, [])

        if len(sup_brands) == 1:
            brand = sup_brands[0]
            bq_info = bq_map.get(a["alias_name"], {})
            total = bq_info.get("total", 0)
            print(f"  {a['alias_name']:<55} → {brand['name']:<25} ({sup_name})")

            if args.apply:
                sb_patch("supplier_aliases",
                         f"id=eq.{a['id']}",
                         {"supplier_brand_id": brand["id"]})
            auto_linked += 1
        elif len(sup_brands) == 0:
            # Нет брендов вообще — пропускаем
            pass
        else:
            still_unresolved.append(a)

    print(f"\n  Автопривязано: {auto_linked}")

    # ─── 4. Мультибрендовые: анализ товаров в BQ ─────────────────────────
    if still_unresolved:
        print(f"\n{'=' * 80}")
        print(f"  ЭТАП B: МУЛЬТИБРЕНДОВЫЕ ПОСТАВЩИКИ (анализ товаров в BQ)")
        print(f"{'=' * 80}")

        # Группируем unresolved по supplier_id
        by_sup = defaultdict(list)
        for a in still_unresolved:
            by_sup[a["supplier_id"]].append(a)

        bq_linked = 0

        for sup_id, alias_list in by_sup.items():
            sup = supplier_map.get(sup_id, {})
            sup_name = sup.get("name", "???")
            sup_brands = brands_by_sup.get(sup_id, [])
            brand_names = [b["name"] for b in sup_brands]

            print(f"\n  --- {sup_name} ---")
            print(f"  Бренды: {', '.join(brand_names)}")

            for a in alias_list:
                alias_name = a["alias_name"]
                bq_info = bq_map.get(alias_name)

                # Проверяем ручной override
                if alias_name in MANUAL_BRAND_OVERRIDE:
                    target_brand_name = MANUAL_BRAND_OVERRIDE[alias_name]
                    brand_match = None
                    for b in sup_brands:
                        if b["name"].lower() == target_brand_name.lower():
                            brand_match = b
                            break
                    if brand_match:
                        print(f"  {alias_name:<55} → {brand_match['name']} (override)")
                        if args.apply:
                            sb_patch("supplier_aliases",
                                     f"id=eq.{a['id']}",
                                     {"supplier_brand_id": brand_match["id"]})
                        bq_linked += 1
                        continue
                    else:
                        print(f"  {alias_name}: override бренд '{target_brand_name}' не найден!")

                if not bq_info or bq_info["total"] < 100:
                    print(f"  {alias_name}: нет данных в BQ или < 100 грн, пропуск")
                    continue

                # Запросить топ товаров для этого alias
                products = run_bq(f"""
                    SELECT product_name, ROUND(SUM(amount_purchase), 2) as total
                    FROM `{BQ_PROJECT}.{BQ_DATASET}.incoming_transactions`
                    WHERE supplier = '{alias_name.replace("'", "''")}'
                      AND doc_date >= '2026-01-01'
                    GROUP BY product_name
                    ORDER BY total DESC
                    LIMIT 20
                """)

                if not products:
                    print(f"  {alias_name}: нет товаров в BQ")
                    continue

                # Попробовать сопоставить по ключевым словам бренда
                product_text = " ".join(p["product_name"].lower() for p in products)
                matched_brand = None
                best_score = 0

                for b in sup_brands:
                    # Разбиваем имя бренда на слова >= 3 символов
                    keywords = [w.lower() for w in b["name"].split() if len(w) >= 3]
                    if not keywords:
                        keywords = [b["name"].lower()]

                    score = sum(1 for kw in keywords if kw in product_text)
                    if score > best_score:
                        best_score = score
                        matched_brand = b

                # Также проверяем, есть ли в скобках алиаса подсказка
                if "(" in alias_name and ")" in alias_name:
                    hint = alias_name[alias_name.index("(")+1:alias_name.index(")")].lower().strip()
                    for b in sup_brands:
                        if hint in b["name"].lower() or b["name"].lower() in hint:
                            matched_brand = b
                            best_score = 99
                            break

                top3 = ", ".join(p["product_name"][:40] for p in products[:3])
                if matched_brand and best_score > 0:
                    print(f"  {alias_name:<55} → {matched_brand['name']}")
                    print(f"    Товары: {top3}")
                    if args.apply:
                        sb_patch("supplier_aliases",
                                 f"id=eq.{a['id']}",
                                 {"supplier_brand_id": matched_brand["id"]})
                    bq_linked += 1
                else:
                    print(f"  {alias_name:<55} → НЕ ОПРЕДЕЛЁН")
                    print(f"    Бренды: {', '.join(brand_names)}")
                    print(f"    Товары: {top3}")

        print(f"\n  Привязано по BQ: {bq_linked}")

    # ─── 5. Новые supplier names из BQ, которых нет в алиасах ─────────────
    existing_aliases = {a["alias_name"] for a in aliases}
    # Технический мусор и выведенные
    SKIP_NAMES = {'Магазин', 'ПОСТАВЩИК', 'Поставщик', 'магазин', 'Неизвестный',
                  'ПРИХОД ПРОДУКЦІЇ З ВИРОБНИЦТВА', 'Укркорн', 'Свіфт-2016',
                  'Свіфт-2016 (Алкоголь)', 'ТОВ Боніта', 'ТОВ ТД Боніта',
                  'ПВКФ Аміга', 'ТОВ Агроспецпак', 'ТОВ Петруцалек',
                  'Геотрейд-ЮА', 'Кузя Сервіс', 'Термопет', 'Оліімпія',
                  'ЮМК-ПЛАСТ', 'ТОВ Хлібний Двір',
                  'Фізична Особа-Підприємець Коробка Любов Миколаївна',
                  'ХФ ТОВ Богодухівський молзавод',
                  # Выведенные поставщики (подтверждено пользователем)
                  'СТВ Схід (Данон)', 'СТВ Схід (Чумак)',
                  'Авангард Дистрибуції (продукти)'}

    new_in_bq = []
    for r in bq_suppliers:
        if r["supplier"] not in existing_aliases and r["supplier"] not in SKIP_NAMES:
            new_in_bq.append(r)

    if new_in_bq:
        print(f"\n{'=' * 80}")
        print(f"  ЭТАП C: НОВЫЕ SUPPLIER В BQ (не в алиасах, не в skip-листе)")
        print(f"{'=' * 80}")
        for r in sorted(new_in_bq, key=lambda x: -x["total"]):
            print(f"  {r['supplier']:<55} tx={r['tx']:>5}  {r['total']:>14,.2f}")

            # Попробовать найти поставщика по имени
            found_sup = None
            name_lower = r["supplier"].lower()
            for s in suppliers:
                s_lower = s["name"].lower()
                # Проверяем вхождение в обе стороны
                if s_lower in name_lower or name_lower in s_lower:
                    found_sup = s
                    break
                # Проверяем первое слово
                first_word = name_lower.split()[0] if name_lower.split() else ""
                if len(first_word) >= 4 and first_word in s_lower:
                    found_sup = s
                    break

            if found_sup:
                sup_brands = brands_by_sup.get(found_sup["id"], [])
                # Если в скобках есть подсказка бренда
                brand_match = None
                if "(" in r["supplier"] and ")" in r["supplier"]:
                    hint = r["supplier"][r["supplier"].index("(")+1:r["supplier"].index(")")].lower().strip()
                    for b in sup_brands:
                        if hint in b["name"].lower() or b["name"].lower() in hint:
                            brand_match = b
                            break

                if brand_match:
                    print(f"    → Поставщик: {found_sup['name']}, Бренд: {brand_match['name']}")
                    if args.apply:
                        created = sb_post("supplier_aliases", {
                            "alias_name": r["supplier"],
                            "supplier_id": found_sup["id"],
                            "supplier_brand_id": brand_match["id"],
                        })
                        print(f"    ✓ Создан алиас id={created[0]['id']}")
                elif len(sup_brands) == 1:
                    print(f"    → Поставщик: {found_sup['name']}, Бренд: {sup_brands[0]['name']} (единственный)")
                    if args.apply:
                        created = sb_post("supplier_aliases", {
                            "alias_name": r["supplier"],
                            "supplier_id": found_sup["id"],
                            "supplier_brand_id": sup_brands[0]["id"],
                        })
                        print(f"    ✓ Создан алиас id={created[0]['id']}")
                else:
                    brand_list = ", ".join(b["name"] for b in sup_brands)
                    print(f"    → Поставщик: {found_sup['name']}, бренды: {brand_list} — НУЖНА РУЧНАЯ ПРИВЯЗКА")
            else:
                print(f"    → Поставщик не найден в Supabase")

    # ─── Итого ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print(f"  ИТОГО")
    print(f"{'=' * 80}")
    print(f"  Режим: {'APPLY — изменения записаны' if args.apply else 'DRY-RUN — ничего не изменено'}")
    if not args.apply:
        print(f"\n  Для применения запустите: python fix_brand_aliases.py --apply")

if __name__ == "__main__":
    main()

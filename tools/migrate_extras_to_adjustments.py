#!/usr/bin/env python3
"""
migrate_extras_to_adjustments.py - разовый перенос доп. выплат из retro_calculation_details
в retro_adjustments (после sql/2026-09-11_adjustments_and_openings.sql).

Что переносится: строки деталей без правила (retro_rule_id IS NULL), кроме фикс-бонуса
(его создаёт сам расчёт из supplier_monthly_bonuses). total_retro НЕ меняется - доплата в нём уже есть.
Строке деталей проставляется adjustment_id - так пересчёт узнаёт её и воссоздаёт.
Повторный запуск безопасен (ключ migrated_from_detail_id).

Запуск (из корня проекта):
  python tools\\migrate_extras_to_adjustments.py            # показать
  python tools\\migrate_extras_to_adjustments.py --apply    # записать
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import sb

FIXED = "фиксированный ежемесячный бонус"


def main():
    apply = "--apply" in sys.argv
    sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
    calc = {c["id"]: c for c in sb.get("retro_calculations", "select=id,supplier_id,period_label,status")}
    rows = sb.get("retro_calculation_details",
                  "retro_rule_id=is.null&select=id,calculation_id,supplier_brand_id,retro_amount,"
                  "bonus_form,notes,adjustment_id")
    todo, fixed, done = [], 0, 0
    for d in rows:
        if FIXED in (d.get("notes") or "").lower():
            fixed += 1
        elif d.get("adjustment_id"):
            done += 1
        elif d["calculation_id"] in calc and float(d["retro_amount"] or 0) != 0:
            todo.append(d)

    print(f"[i] строк без правила: {len(rows)} | фикс-бонус (не трогаем): {fixed} | "
          f"уже перенесено: {done} | к переносу: {len(todo)}")
    for d in sorted(todo, key=lambda d: (calc[d["calculation_id"]]["period_label"],
                                         sup.get(calc[d["calculation_id"]]["supplier_id"], ""))):
        c = calc[d["calculation_id"]]
        print(f"    {c['period_label']}  {sup.get(c['supplier_id'], '?')[:34]:<35}{float(d['retro_amount']):>11,.2f}"
              f"  {c['status']:<10} {(d['notes'] or '')[:60]}")
    print(f"    итого {sum(float(d['retro_amount']) for d in todo):,.2f}")

    if not apply:
        print("\n[i] Пробный прогон. Для записи --apply")
        return
    for d in todo:
        c = calc[d["calculation_id"]]
        adj = sb.upsert("retro_adjustments", [{
            "supplier_id": c["supplier_id"], "supplier_brand_id": d.get("supplier_brand_id"),
            "period_label": c["period_label"], "amount": float(d["retro_amount"]),
            "bonus_form": d.get("bonus_form") or "price_correction",
            "notes": (d.get("notes") or "").strip() or "доп. выплата (без примечания)",
            "source": "migration", "migrated_from_detail_id": d["id"],
            "created_by": "migration 2026-09-11"}], on_conflict="migrated_from_detail_id")[0]
        sb._req(f"{sb.URL}/rest/v1/retro_calculation_details?id=eq.{d['id']}",
                {"adjustment_id": adj["id"]}, "PATCH", {"Prefer": "return=minimal"})
    print(f"[>] перенесено: {len(todo)}")


if __name__ == "__main__":
    main()

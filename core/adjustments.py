#!/usr/bin/env python3
"""
adjustments.py - ручная доплата/вычет поверх расчёта (то же, что кнопка «Доп. виплата» в админке).

Пишет retro_adjustments + строку в текущий расчёт (adjustment_id) + total_retro += сумма.
Работает и для approved-месяцев (пересчёт их не трогает, а доплата должна появиться).
Повтор с тем же поставщиком/периодом/суммой/примечанием не создаёт дубль.

Запуск (из корня):
  python core\\adjustments.py "Маршалл Табако" 2026-07 1600 "Июль: оплата по договорённости о пороге 8 SKU"
  ... --apply
"""
import sys, argparse
import sb


def add_adjustment(supplier_id, period, amount, notes, source="script", created_by="adjustments.py",
                   bonus_form="price_correction", apply=False):
    same = sb.get("retro_adjustments", f"supplier_id=eq.{supplier_id}&period_label=eq.{period}"
                  "&select=id,amount,notes")
    if any(abs(float(a["amount"]) - amount) < 0.005 and a["notes"].strip() == notes.strip() for a in same):
        return "уже есть"
    calc = sb.get("retro_calculations", f"supplier_id=eq.{supplier_id}&period_label=eq.{period}"
                  "&select=id,total_retro,status")
    if not apply:
        return f"будет добавлено; расчёт: {calc[0]['total_retro']} ({calc[0]['status']})" if calc else \
            "будет добавлено; расчёта за период нет - строка появится при следующем расчёте"
    adj = sb.upsert("retro_adjustments", [{"supplier_id": supplier_id, "period_label": period, "amount": amount,
                                           "bonus_form": bonus_form, "notes": notes.strip(), "source": source,
                                           "created_by": created_by}])[0]
    if calc:
        c = calc[0]
        det = sb.get("retro_calculation_details", f"calculation_id=eq.{c['id']}&select=supplier_brand_id&limit=1")
        sb.upsert("retro_calculation_details", [{
            "calculation_id": c["id"], "supplier_brand_id": det[0]["supplier_brand_id"] if det else None,
            "retro_rule_id": None, "amount_purchased": 0, "amount_returned": 0, "amount_net": 0,
            "applied_percent": 0, "retro_amount": amount, "retro_amount_vat": amount,
            "bonus_form": bonus_form, "notes": notes.strip(), "adjustment_id": adj["id"]}])
        new_total = round(float(c["total_retro"] or 0) + amount, 2)
        sb._req(f"{sb.URL}/rest/v1/retro_calculations?id=eq.{c['id']}", {"total_retro": new_total},
                "PATCH", {"Prefer": "return=minimal"})
        return f"добавлено; total_retro {c['total_retro']} -> {new_total}"
    return "добавлено; расчёта нет - строка появится при расчёте"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("supplier")
    ap.add_argument("period")
    ap.add_argument("amount", type=float)
    ap.add_argument("notes")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    s = [x for x in sb.get("suppliers", "select=id,name") if x["name"] == a.supplier]
    if len(s) != 1:
        sys.exit(f"поставщик «{a.supplier}» не найден точно (EXACT)")
    print(f"{a.supplier} {a.period} {a.amount:+,.2f} «{a.notes}»: "
          f"{add_adjustment(s[0]['id'], a.period, a.amount, a.notes, apply=a.apply)}")


if __name__ == "__main__":
    main()

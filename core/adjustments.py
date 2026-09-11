#!/usr/bin/env python3
"""
adjustments.py - доплата/вычет «не ретро» (то же, что блок «Доп. виплата» в админке).

Два режима (retro_adjustments.payment_mode, sql/2026-09-11_adjustments_payment_mode.sql):
  in_payment (по умолчанию) - деньги сидят в «Оплачено» или это договорённость, меняющая начисление:
      retro_adjustments + строка в текущий расчёт (adjustment_id) + total_retro += сумма.
  separate (--separate) - заплачено отдельно, в «Оплачено» не входит (ДМП Славутич):
      только retro_adjustments, расчёт не трогается.
Работает и для approved-месяцев (пересчёт их не трогает, а доплата должна появиться).
Повтор с тем же поставщиком/периодом/суммой/примечанием не создаёт дубль.

Запуск (из корня):
  python core\\adjustments.py "Маршалл Табако" 2026-07 1600 "Июль: оплата по договорённости о пороге 8 SKU" --apply
  python core\\adjustments.py "БІР (Пиво Славутич)" 2026-06 5400 "ДМП" --separate --apply
"""
import sys, argparse
import sb

MODES = ("in_payment", "separate")


def _calc(supplier_id, period):
    c = sb.get("retro_calculations", f"supplier_id=eq.{supplier_id}&period_label=eq.{period}&select=id,total_retro,status")
    return c[0] if c else None


def _add_to_calc(c, adj):
    det = sb.get("retro_calculation_details", f"calculation_id=eq.{c['id']}&select=supplier_brand_id&limit=1")
    amount = float(adj["amount"])
    sb.upsert("retro_calculation_details", [{
        "calculation_id": c["id"], "supplier_brand_id": adj.get("supplier_brand_id") or (det[0]["supplier_brand_id"] if det else None),
        "retro_rule_id": None, "amount_purchased": 0, "amount_returned": 0, "amount_net": 0,
        "applied_percent": 0, "retro_amount": amount, "retro_amount_vat": amount,
        "bonus_form": adj.get("bonus_form") or "price_correction", "notes": adj["notes"], "adjustment_id": adj["id"]}])
    new_total = round(float(c["total_retro"] or 0) + amount, 2)
    sb._req(f"{sb.URL}/rest/v1/retro_calculations?id=eq.{c['id']}", {"total_retro": new_total},
            "PATCH", {"Prefer": "return=minimal"})
    return new_total


def _remove_from_calc(c, adj):
    rows = sb.get("retro_calculation_details", f"calculation_id=eq.{c['id']}&adjustment_id=eq.{adj['id']}&select=id,retro_amount")
    if not rows:
        return float(c["total_retro"] or 0)
    sb._req(f"{sb.URL}/rest/v1/retro_calculation_details?calculation_id=eq.{c['id']}&adjustment_id=eq.{adj['id']}",
            None, "DELETE", {"Prefer": "return=minimal"})
    new_total = round(float(c["total_retro"] or 0) - sum(float(r["retro_amount"] or 0) for r in rows), 2)
    sb._req(f"{sb.URL}/rest/v1/retro_calculations?id=eq.{c['id']}", {"total_retro": new_total},
            "PATCH", {"Prefer": "return=minimal"})
    return new_total


def add_adjustment(supplier_id, period, amount, notes, source="script", created_by="adjustments.py",
                   bonus_form="price_correction", payment_mode="in_payment", apply=False):
    assert payment_mode in MODES
    same = sb.get("retro_adjustments", f"supplier_id=eq.{supplier_id}&period_label=eq.{period}&select=id,amount,notes")
    if any(abs(float(a["amount"]) - amount) < 0.005 and a["notes"].strip() == notes.strip() for a in same):
        return "уже есть"
    c = _calc(supplier_id, period)
    if not apply:
        if payment_mode == "separate":
            return "будет добавлено отдельно (расчёт не меняется)"
        return f"будет добавлено; расчёт: {c['total_retro']} ({c['status']})" if c else \
            "будет добавлено; расчёта за период нет - строка появится при следующем расчёте"
    row = {"supplier_id": supplier_id, "period_label": period, "amount": amount, "bonus_form": bonus_form,
           "notes": notes.strip(), "source": source, "created_by": created_by}
    if payment_mode != "in_payment":
        row["payment_mode"] = payment_mode       # колонка есть только после SQL; in_payment = DEFAULT
    adj = sb.upsert("retro_adjustments", [row])[0]
    if payment_mode == "separate":
        return "добавлено отдельно; расчёт не менялся"
    if c:
        return f"добавлено; total_retro {c['total_retro']} -> {_add_to_calc(c, adj)}"
    return "добавлено; расчёта нет - строка появится при расчёте"


def set_mode(adj_id, payment_mode, apply=False):
    """Перевести существующую доплату между режимами: строка расчёта и total_retro правятся вместе с ней."""
    assert payment_mode in MODES
    adj = sb.get("retro_adjustments", f"id=eq.{adj_id}&select=*")[0]
    cur = adj.get("payment_mode") or "in_payment"
    if cur == payment_mode:
        return f"уже {payment_mode}"
    c = _calc(adj["supplier_id"], adj["period_label"])
    if not apply:
        return f"{cur} -> {payment_mode}; расчёт {c['total_retro'] if c else '-'} " \
               f"{'-' if payment_mode == 'separate' else '+'} {float(adj['amount']):,.2f}"
    sb._req(f"{sb.URL}/rest/v1/retro_adjustments?id=eq.{adj_id}", {"payment_mode": payment_mode},
            "PATCH", {"Prefer": "return=minimal"})
    if not c:
        return f"{cur} -> {payment_mode}; расчёта нет"
    total = _remove_from_calc(c, adj) if payment_mode == "separate" else _add_to_calc(c, adj)
    return f"{cur} -> {payment_mode}; total_retro {c['total_retro']} -> {total}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("supplier")
    ap.add_argument("period")
    ap.add_argument("amount", type=float)
    ap.add_argument("notes")
    ap.add_argument("--separate", action="store_true", help="заплачено отдельно, в «Оплачено» не входит")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    s = [x for x in sb.get("suppliers", "select=id,name") if x["name"] == a.supplier]
    if len(s) != 1:
        sys.exit(f"поставщик «{a.supplier}» не найден точно (EXACT)")
    mode = "separate" if a.separate else "in_payment"
    print(f"{a.supplier} {a.period} {a.amount:+,.2f} «{a.notes}» [{mode}]: "
          f"{add_adjustment(s[0]['id'], a.period, a.amount, a.notes, payment_mode=mode, apply=a.apply)}")


if __name__ == "__main__":
    main()

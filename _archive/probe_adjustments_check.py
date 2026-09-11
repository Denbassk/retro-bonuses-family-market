"""Разовая проверка 11.09 после переноса доплат.
[1] 8 доплат в retro_adjustments, у каждой ровно одна строка расчёта с adjustment_id, total_retro не изменился.
[2] --test: обратимый тест на Маршалл Табако 2026-07 (completed): +1,00 ₴ доплата -> пересчёт с сохранением ->
    итог 1 601 и строка доплаты на месте -> удаление доплаты -> пересчёт -> снова 1 600."""
import os, sys, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT / "core")); os.chdir(ROOT)
import sb

sup = {s["id"]: s["name"] for s in sb.get("suppliers", "select=id,name")}
calc = {c["id"]: c for c in sb.get("retro_calculations", "select=id,supplier_id,period_label,total_retro,status")}
adjs = sb.get("retro_adjustments", "select=id,supplier_id,period_label,amount,notes,source")
det = sb.get("retro_calculation_details", "adjustment_id=not.is.null&select=id,calculation_id,adjustment_id,retro_amount")
print(f"[1] retro_adjustments: {len(adjs)} на {sum(float(a['amount']) for a in adjs):,.2f} | строк расчёта с adjustment_id: {len(det)}")
for a in adjs:
    links = [d for d in det if d["adjustment_id"] == a["id"]]
    ok = len(links) == 1 and abs(float(links[0]["retro_amount"]) - float(a["amount"])) < 0.005 \
        and (calc[links[0]["calculation_id"]]["supplier_id"], calc[links[0]["calculation_id"]]["period_label"]) == (a["supplier_id"], a["period_label"])
    print(f"    {a['period_label']} {sup[a['supplier_id']][:28]:<29}{float(a['amount']):>10,.2f}  связь {'OK' if ok else 'ОШИБКА'}  {a['source']}")


def july_marshall():
    sid = next(k for k, v in sup.items() if v == "Маршалл Табако")
    c = sb.get("retro_calculations", f"supplier_id=eq.{sid}&period_label=eq.2026-07&select=id,total_retro,status")[0]
    d = sb.get("retro_calculation_details", f"calculation_id=eq.{c['id']}&adjustment_id=not.is.null&select=retro_amount,notes")
    return sid, float(c["total_retro"]), d, c["status"]


def recalc():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "core/calculate_retro.py", "2026-07", "--supplier", "Маршалл Табако",
                        "--csv", str(ROOT / "_archive" / "adj_test.csv")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    (ROOT / "_archive" / "adj_test.csv").unlink(missing_ok=True)
    if r.returncode:
        raise SystemExit(r.stdout[-800:] + r.stderr[-800:])


if "--test" in sys.argv:
    sid, t0, d0, st = july_marshall()
    print(f"\n[2] Маршалл 2026-07 до теста: {t0:,.2f} ({st}), доплат {len(d0)}")
    assert st == "completed" and not d0 and abs(t0 - 1600) < 0.005, "неожиданное состояние - тест не запускаю"
    a = sb.upsert("retro_adjustments", [{"supplier_id": sid, "period_label": "2026-07", "amount": 1.0,
                  "notes": "ТЕСТ 11.09 - будет удалено", "source": "script", "created_by": "probe_adjustments_check"}])[0]
    try:
        recalc()
        _, t1, d1, _ = july_marshall()
        print(f"    после доплаты +1 и пересчёта: {t1:,.2f}, строк доплат {len(d1)} -> {'OK' if abs(t1 - 1601) < 0.005 and len(d1) == 1 else 'ОШИБКА'}")
    finally:
        sb._req(f"{sb.URL}/rest/v1/retro_calculation_details?adjustment_id=eq.{a['id']}", None, "DELETE", {"Prefer": "return=minimal"})
        sb._req(f"{sb.URL}/rest/v1/retro_adjustments?id=eq.{a['id']}", None, "DELETE", {"Prefer": "return=minimal"})
        recalc()
        _, t2, d2, _ = july_marshall()
        print(f"    после удаления и пересчёта: {t2:,.2f}, строк доплат {len(d2)} -> {'OK' if abs(t2 - 1600) < 0.005 and not d2 else 'ОШИБКА'}")

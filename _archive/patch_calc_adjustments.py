"""Разовый патч 11.09: calculate_retro.save_to_supabase воссоздаёт доплаты из retro_adjustments."""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "core" / "calculate_retro.py"
raw = p.read_bytes(); crlf = b"\r\n" in raw
lines = raw.decode("utf-8").replace("\r\n", "\n").split("\n")
if any("retro_adjustments" in l for l in lines):
    raise SystemExit("уже пропатчено")

# 1) до удаления старого расчёта: загрузить доплаты (упадёт, если таблицы нет -> ничего не удалено)
i = next(k for k, l in enumerate(lines) if l.strip() == "for o in old:")
ind = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
lines[i:i] = [
    f"{ind}# Ручные доплаты/вычеты живут в retro_adjustments и воссоздаются при каждом сохранении.",
    f"{ind}# Грузим ДО удаления старого расчёта: если запрос упадёт, старые данные останутся.",
    f'{ind}adjs = sb_get("retro_adjustments",',
    f'{ind}              f"supplier_id=eq.{{sup_id}}&period_label=eq.{{month}}"',
    f'{ind}              "&select=id,supplier_brand_id,amount,bonus_form,notes")',
    "",
]

# 2) total_retro += доплаты
j = next(k for k, l in enumerate(lines) if l.strip() == 'total_retro = sup_result.get("total", 0)')
lines[j + 1:j + 1] = [f'{ind}total_retro = round(float(total_retro) + sum(float(a["amount"]) for a in adjs), 2)']

# 3) после цикла деталей (перед итоговым print) - строки доплат с adjustment_id
k = next(n for n, l in enumerate(lines) if l.strip().startswith('print(f"  [!]') and "sku.get('barcode')" in l)
lines[k + 1:k + 1] = [
    "",
    f"{ind}for a in adjs:",
    f'{ind}    sb_post("retro_calculation_details", {{',
    f'{ind}        "calculation_id": calc_id, "supplier_brand_id": a.get("supplier_brand_id"),',
    f'{ind}        "retro_rule_id": None, "amount_purchased": 0, "amount_returned": 0, "amount_net": 0,',
    f'{ind}        "applied_percent": 0, "retro_amount": float(a["amount"]), "retro_amount_vat": float(a["amount"]),',
    f'{ind}        "bonus_form": a.get("bonus_form") or "price_correction", "notes": a["notes"],',
    f'{ind}        "adjustment_id": a["id"],',
    f"{ind}    }})",
    f"{ind}    saved_details += 1",
]
s = "\n".join(lines)
p.write_bytes((s.replace("\n", "\r\n") if crlf else s).encode("utf-8"))
print("ok, indent", len(ind))

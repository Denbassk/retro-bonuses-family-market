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

    # Запрос: SUM(quantity) вместо SUM(amount_purchase)
    q_qty = build_query("incoming_transactions", aliases_for_rule, month_start, month_end,
                        sku_barcodes=sku, agg_field="quantity")

    if dry_run:
        print(f"  {rule['brand_name']} -> {price_per_cup} грн/чашка × {cups_per_kg} чашок/кг [sku:{len(sku)}]")
        return None

    total_qty = float(run_bq(q_qty)[0]["total"])

    total_cups = total_qty * cups_per_kg
    retro = Decimal(str(total_cups)) * Decimal(str(price_per_cup))
    retro = retro.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    bf = rule["bonus_form"]
    retro_vat = retro
    retro_vat = retro_vat.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Также получим amount_purchase для информации
    q_amt = build_query("incoming_transactions", aliases_for_rule, month_start, month_end,
                        sku_barcodes=sku)
    incoming_amount = float(run_bq(q_amt)[0]["total"])

    return {
        "brand": rule["brand_name"],
        "pct": price_per_cup,  # числовое значение для Supabase applied_percent
        "pct_display": f"{price_per_cup}грн×{cups_per_kg}ч/кг",  # для консоли
        "brand_id": rule.get("brand_id"),
        "rule_id": rule.get("rule_id"),
        "supplier_id": rule.get("supplier_id"),
        "incoming": incoming_amount, "returns": 0,
        "base": total_qty,  # база = кг
        "retro": float(retro), "retro_vat": float(retro_vat),
        "bonus_form": bf, "base_type": rule["base_type"],
        "sku_filter": len(sku),
        "note": f"qty={total_qty:.2f} кг × {cups_per_kg} чашок/кг × {price_per_cup} грн = {float(retro):.2f}"
    }

"""Разовый патч diagnose_retro.py после первого прогона 11.09:
1) разделители тысяч: убрать .replace(',', ' ') со всей строки (портил «Союз (Продукти, МакМай...)»), форматировать в конце;
2) additional_payments из админки хранят подпись в ключе note, пустые суммы пропускать;
3) RATE_NICE никогда не принимается автоматически, BOUNDARY - только если один закрывает весь разрыв; обе с «возможно»;
4) torgsoft_ref (Арсенал Шейк): сравнить эталон с нашими приходами;
5) честное сообщение, когда данные расчёта совпадают с BQ и эталоном."""
from pathlib import Path
p = Path(__file__).resolve().parent.parent / "core" / "diagnose_retro.py"
s = p.read_text(encoding="utf-8")
n_rep = s.count('.replace(",", " ")')
s = s.replace('.replace(",", " ")', "")
print("убрано replace:", n_rep)

def sub(old, new, cnt=1):
    global s
    assert s.count(old) == cnt, (s.count(old), old[:70])
    s = s.replace(old, new)

sub('''def money(x):
    return f"{x:+,.0f}"''', '''def money(x):
    return f"{x:+,.0f}"


def sp(text):
    """1,234,567 -> 1 234 567 только внутри чисел (запятые в названиях не трогаем)."""
    return re.sub(r"(?<=\\d),(?=\\d{3}(?!\\d))", " ", text)''')

sub('''            for e in f.get("additional_payments") or []:
                non.append(("админка", {"amount": f2(e.get("amount")), "label": e.get("label") or "?"}))''',
    '''            for e in f.get("additional_payments") or []:
                if f2(e.get("amount")) > 0:
                    non.append(("админке (доп. выплата в факте)",
                                {"amount": f2(e.get("amount")), "label": e.get("label") or e.get("note") or "доп. выплата"}))''')

sub('''        for h in (h_rate_nice, h_boundary):
            if abs(residual) <= tol:
                break
            for c in h(D, t, ctx, residual):
                checked.append(c)
                if c["amount"] and (c["amount"] > 0) == (residual > 0) and abs(residual - c["amount"]) <= tol:
                    accepted.append(c)
                    residual = round(residual - c["amount"], 2)
                    break''',
    '''        # слабые: круглая ставка - только в «проверено»; граница месяца - только если одна закрывает ВЕСЬ разрыв
        if abs(residual) > tol:
            checked += h_rate_nice(D, t, ctx, residual)
            for c in h_boundary(D, t, ctx, d):
                checked.append(c)
                if not accepted and c["amount"] and (c["amount"] > 0) == (d > 0) and abs(d - c["amount"]) <= tol:
                    accepted.append(c)
                    residual = round(d - c["amount"], 2)
                    break''')

sub('''f"подразумеваемая ставка по факту {implied:.2%} ≈ {nice:.1%} "''',
    '''f"возможно: подразумеваемая ставка по факту {implied:.2%} ≈ {nice:.1%} "''')
sub('''cand("BOUNDARY", -v, f"{D.sup.get(s)}: документы''', '''cand("BOUNDARY", -v, f"возможно: {D.sup.get(s)}: документы''')
sub('''cand("BOUNDARY", v, f"{D.sup.get(s)}: документы''', '''cand("BOUNDARY", v, f"возможно: {D.sup.get(s)}: документы''')

# torgsoft_ref
sub('''def h_payments(D, t, ctx):''', '''def h_ref(D, t, ctx):
    """income_source=torgsoft_ref: расчёт взял приход из эталона; поставщик мог считать от наших приходов."""
    if not D.bq:
        return []
    out, per = [], t["per"]
    for d in ctx["rule_dets"]:
        if (d["_rule"].get("income_source") or "") != "torgsoft_ref":
            continue
        s = d["_sid"]
        names = D.aliases[s]["in"]
        ours = sum(v for (n, p, bc), v in D.bq["inc"].items() if p == per and n in names)
        et = sum(v for (n, p), v in D.bq["et_inc"].items() if p == per and n in names)
        if abs(ours - et) * d["_rate"] >= TOL_ABS:
            out.append(cand("REF_BASE", (ours - et) * d["_rate"],
                            f"{D.sup.get(s)}: расчёт от эталона Торгсофт {et:,.0f}, наши приходы {ours:,.0f} "
                            f"({money(ours - et)}) - поставщик мог считать от накладных"))
    return out


def h_payments(D, t, ctx):''')
sub('''LADDER = [h_note, h_excel, h_shift, h_threshold, h_vat, h_rate_xls, h_returns, h_sku, h_etalon, h_payments]''',
    '''LADDER = [h_note, h_excel, h_shift, h_threshold, h_vat, h_rate_xls, h_returns, h_sku, h_etalon, h_ref, h_payments]''')

sub('''            head = f"{kind} {money(d)}: причина не найдена автоматически" + \\
                   ("; проверено: " + "; ".join(f"[{money(c['amount'])}] {c['text']}" for c in top) if top else
                    "; гипотезам не хватает данных (нет расчёта по SKU / BQ)")''',
    '''            if top:
                tail = "; проверено, не подходит: " + "; ".join(f"[{money(c['amount'])}] {c['text']}" for c in top)
            elif ctx["ship"] and D.bq:
                r_impl = (ctx["r_eff"] + d / ctx["net_ship"]) if ctx["net_ship"] else 0
                tail = (f"; данные расчёта совпадают с BigQuery и эталоном (дрейфа, SKU вне правил, дыр нет) - "
                        f"разница в методике поставщика: по факту выходит {r_impl:.2%} от базы {ctx['net_ship']:,.0f} "
                        f"вместо {ctx['r_eff']:.2%}")
            else:
                tail = "; для гипотез нет данных (нет SKU-разбивки расчёта или BigQuery выключен)"
            head = f"{kind} {money(d)}: причина не найдена автоматически" + tail''')

sub('''    return {"text": "; ".join(lines), "closed": closed,''', '''    return {"text": sp("; ".join(lines)), "closed": closed,''')
p.write_text(s, encoding="utf-8")
print("ok")

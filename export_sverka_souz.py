"""
Сверка ретро-бонусов для Союз (Продукти, МакМай, Ямуна)
Экспорт детализации по накладным в Excel для отправки поставщику.
"""

import os
from google.cloud import bigquery
from openpyxl import Workbook
from openpyxl.styles import (Font, PatternFill, Alignment, Border, Side,
                              numbers)
from openpyxl.utils import get_column_letter
from datetime import datetime

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = (
    r"D:\Family_Market_Analytics\credentials\family-market-analytics-23fbcbcee571c.json"
)

PROJECT = "family-market-analytics"
RETRO_PCT = 0.10
SUPPLIER_ALIAS = "Союз (Продукти)"   # тендерный "Союз" исключён
PERIOD_FROM = "2026-01-01"
PERIOD_TO   = "2026-04-01"

client = bigquery.Client(project=PROJECT)

# ── 1. Детализация по накладным ──────────────────────────────────────────────
SQL_DETAIL = f"""
SELECT
  FORMAT_DATE('%Y-%m', doc_date)           AS month,
  doc_date,
  doc_number,
  COUNT(DISTINCT barcode)                   AS sku_count,
  ROUND(SUM(amount_purchase), 2)            AS purchase_amount,
  ROUND(SUM(amount_purchase) * {RETRO_PCT}, 2) AS retro_amount
FROM `{PROJECT}.family_market.incoming_transactions`
WHERE supplier = '{SUPPLIER_ALIAS}'
  AND doc_date >= '{PERIOD_FROM}'
  AND doc_date <  '{PERIOD_TO}'
GROUP BY month, doc_date, doc_number
ORDER BY doc_date, doc_number
"""

# ── 2. Итоги по месяцам ──────────────────────────────────────────────────────
SQL_TOTAL = f"""
SELECT
  FORMAT_DATE('%Y-%m', doc_date)              AS month,
  COUNT(DISTINCT doc_number)                  AS docs_count,
  ROUND(SUM(amount_purchase), 2)              AS total_purchase,
  ROUND(SUM(amount_purchase) * {RETRO_PCT}, 2) AS total_retro
FROM `{PROJECT}.family_market.incoming_transactions`
WHERE supplier = '{SUPPLIER_ALIAS}'
  AND doc_date >= '{PERIOD_FROM}'
  AND doc_date <  '{PERIOD_TO}'
GROUP BY month
ORDER BY month
"""

print("Запрос в BigQuery...")
rows_detail = list(client.query(SQL_DETAIL).result())
rows_total  = list(client.query(SQL_TOTAL).result())
print(f"Получено: {len(rows_detail)} накладных, {len(rows_total)} месяцев")

# ── 3. Стили ─────────────────────────────────────────────────────────────────
BLUE_DARK  = "1B4F72"
BLUE_MID   = "2E75B6"
BLUE_LIGHT = "D6E4F0"
YELLOW     = "FFF3CD"
GREEN      = "D4EDDA"
GREY       = "F2F2F2"

def hdr_fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def thin_border():
    s = Side(style="thin", color="BFBFBF")
    return Border(left=s, right=s, top=s, bottom=s)

def money_fmt():
    return '#,##0.00'

# ── 4. Workbook ───────────────────────────────────────────────────────────────
wb = Workbook()
ws = wb.active
ws.title = "Сверка"

# Заголовок документа
today = datetime.now().strftime("%d.%m.%Y")
ws.merge_cells("A1:F1")
ws["A1"] = f"Сверка ретро-бонусов — {SUPPLIER_ALIAS}  |  Январь–Март 2026  |  Ставка {int(RETRO_PCT*100)}%"
ws["A1"].font = Font(bold=True, size=13, color="FFFFFF")
ws["A1"].fill = hdr_fill(BLUE_DARK)
ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
ws.row_dimensions[1].height = 30

ws.merge_cells("A2:F2")
ws["A2"] = f"Сформировано: {today}  |  Family Market"
ws["A2"].font = Font(italic=True, size=10, color="555555")
ws["A2"].alignment = Alignment(horizontal="center")
ws.row_dimensions[2].height = 18

# Шапка таблицы
HEADERS = ["Месяц", "Дата накладной", "Номер накладной", "Кол-во SKU",
           "Сумма закупки, грн", f"Ретро {int(RETRO_PCT*100)}%, грн"]
ws.append([])  # row 3 — пустая
ws.append(HEADERS)  # row 4

for col, _ in enumerate(HEADERS, 1):
    cell = ws.cell(row=4, column=col)
    cell.font = Font(bold=True, color="FFFFFF", size=10)
    cell.fill = hdr_fill(BLUE_MID)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = thin_border()
ws.row_dimensions[4].height = 28

# Данные
current_month = None
data_start = 5
row_idx = data_start

for r in rows_detail:
    month_changed = (r.month != current_month)
    if month_changed and current_month is not None:
        # Итоговая строка предыдущего месяца
        totals = next((t for t in rows_total if t.month == current_month), None)
        if totals:
            ws.cell(row=row_idx, column=1, value=f"ИТОГО {current_month}").font = Font(bold=True)
            ws.cell(row=row_idx, column=1).fill = hdr_fill(BLUE_LIGHT)
            ws.cell(row=row_idx, column=5, value=float(totals.total_purchase)).number_format = money_fmt()
            ws.cell(row=row_idx, column=5).font = Font(bold=True)
            ws.cell(row=row_idx, column=5).fill = hdr_fill(BLUE_LIGHT)
            ws.cell(row=row_idx, column=6, value=float(totals.total_retro)).number_format = money_fmt()
            ws.cell(row=row_idx, column=6).font = Font(bold=True)
            ws.cell(row=row_idx, column=6).fill = hdr_fill(BLUE_LIGHT)
            for c in range(1, 7):
                ws.cell(row=row_idx, column=c).border = thin_border()
            row_idx += 1

    current_month = r.month

    fill = hdr_fill(GREY) if (row_idx - data_start) % 2 == 0 else PatternFill()

    vals = [r.month, r.doc_date, r.doc_number,
            int(r.sku_count), float(r.purchase_amount), float(r.retro_amount)]
    for col, val in enumerate(vals, 1):
        cell = ws.cell(row=row_idx, column=col, value=val)
        cell.border = thin_border()
        cell.alignment = Alignment(horizontal="right" if col >= 4 else "left",
                                   vertical="center")
        if col >= 5:
            cell.number_format = money_fmt()
        if fill:
            cell.fill = fill

    row_idx += 1

# Итоговая строка последнего месяца
if current_month:
    totals = next((t for t in rows_total if t.month == current_month), None)
    if totals:
        ws.cell(row=row_idx, column=1, value=f"ИТОГО {current_month}").font = Font(bold=True)
        ws.cell(row=row_idx, column=1).fill = hdr_fill(BLUE_LIGHT)
        ws.cell(row=row_idx, column=5, value=float(totals.total_purchase)).number_format = money_fmt()
        ws.cell(row=row_idx, column=5).font = Font(bold=True)
        ws.cell(row=row_idx, column=5).fill = hdr_fill(BLUE_LIGHT)
        ws.cell(row=row_idx, column=6, value=float(totals.total_retro)).number_format = money_fmt()
        ws.cell(row=row_idx, column=6).font = Font(bold=True)
        ws.cell(row=row_idx, column=6).fill = hdr_fill(BLUE_LIGHT)
        for c in range(1, 7):
            ws.cell(row=row_idx, column=c).border = thin_border()
        row_idx += 1

# Итого ВСЕГО
row_idx += 1
grand_purchase = sum(float(t.total_purchase) for t in rows_total)
grand_retro    = sum(float(t.total_retro)    for t in rows_total)
ws.cell(row=row_idx, column=1, value="ИТОГО ЗА ПЕРИОД").font = Font(bold=True, size=11, color="FFFFFF")
ws.cell(row=row_idx, column=1).fill = hdr_fill(BLUE_DARK)
ws.cell(row=row_idx, column=5, value=grand_purchase).number_format = money_fmt()
ws.cell(row=row_idx, column=5).font = Font(bold=True, color="FFFFFF")
ws.cell(row=row_idx, column=5).fill = hdr_fill(BLUE_DARK)
ws.cell(row=row_idx, column=6, value=grand_retro).number_format = money_fmt()
ws.cell(row=row_idx, column=6).font = Font(bold=True, color="FFFFFF")
ws.cell(row=row_idx, column=6).fill = hdr_fill(BLUE_DARK)
for c in [2, 3, 4]:
    ws.cell(row=row_idx, column=c).fill = hdr_fill(BLUE_DARK)
ws.row_dimensions[row_idx].height = 22

# Примечание
row_idx += 2
ws.merge_cells(f"A{row_idx}:F{row_idx}")
ws[f"A{row_idx}"] = ("* Тендерные закупки (алиас «Союз») в расчёт не включены. "
                      "Ретро начисляется только на поставки по накладным «Союз (Продукти)».")
ws[f"A{row_idx}"].font = Font(italic=True, size=9, color="666666")
ws[f"A{row_idx}"].fill = hdr_fill(YELLOW)
ws[f"A{row_idx}"].alignment = Alignment(wrap_text=True)
ws.row_dimensions[row_idx].height = 28

# ── 5. Ширина колонок ─────────────────────────────────────────────────────────
col_widths = [12, 16, 28, 12, 22, 20]
for i, w in enumerate(col_widths, 1):
    ws.column_dimensions[get_column_letter(i)].width = w

ws.freeze_panes = "A5"

# ── 6. Сохранение ─────────────────────────────────────────────────────────────
out_path = r"D:\РЕТРО_БОНУСЫ Фэмэли маркет\Сверка_Союз_Продукти_янв-март_2026.xlsx"
wb.save(out_path)
print(f"\nФайл сохранён: {out_path}")
print(f"Итого за период: закупка {grand_purchase:,.2f} грн, ретро {grand_retro:,.2f} грн")

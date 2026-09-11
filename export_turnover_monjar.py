"""
Отчёт о вторичных продажах (turnover) для Монжар.

НАСТРОЙКА:
  Измените MONTHS ниже чтобы добавить / убрать месяцы.
  Скрипт автоматически перестроит столбцы и заголовки.

  Пример:
    MONTHS = ["2026-03"]                          # только март
    MONTHS = ["2026-01", "2026-02", "2026-03"]   # квартал
"""

import os
from google.cloud import bigquery
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime, date
from collections import defaultdict
from dateutil.relativedelta import relativedelta   # pip install python-dateutil

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = (
    r"D:\Family_Market_Analytics\credentials\family-market-analytics-23fbcbcee571c.json"
)

PROJECT  = "family-market-analytics"
SUPPLIER = "Монжар"

# ╔══════════════════════════════════════════════════════════╗
# ║  НАСТРОЙКА ПЕРИОДА — список месяцев в формате YYYY-MM   ║
# ╚══════════════════════════════════════════════════════════╝
MONTHS = ["2026-03", "2026-04"]

# ── Авторасчёт дат периода ────────────────────────────────
_first = datetime.strptime(MONTHS[0], "%Y-%m")
_last  = datetime.strptime(MONTHS[-1], "%Y-%m")
PERIOD_FROM = _first.strftime("%Y-%m-01")
PERIOD_TO   = (_last + relativedelta(months=1)).strftime("%Y-%m-01")

# ── Названия месяцев (рус.) ───────────────────────────────
_MONTH_RU = {
    "01": "Январь", "02": "Февраль", "03": "Март",    "04": "Апрель",
    "05": "Май",    "06": "Июнь",    "07": "Июль",    "08": "Август",
    "09": "Сентябрь","10": "Октябрь","11": "Ноябрь", "12": "Декабрь",
}
def month_label(ym):        # "2026-03" → "Март 2026"
    y, m = ym.split("-")
    return f"{_MONTH_RU[m]} {y}"

def month_key(ym):          # "2026-03" → "m2026_03"  (BigQuery column name)
    return "m" + ym.replace("-", "_")

# ── Цвета для месяцев (циклически) ───────────────────────
_MONTH_BG  = ["BDD7EE", "C6EFCE", "FCE4D6", "E2EFDA", "EAD1DC", "FFF2CC"]
_MONTH_HDR = ["4472C4", "548235", "C55A11", "375623", "7030A0", "BF9000"]
_MONTH_GRP = ["1B4F72", "1D5C38", "843C0C", "1E3A1E", "4B0082", "7D6608"]

def month_bg(i):  return _MONTH_BG[i  % len(_MONTH_BG)]
def month_hdr(i): return _MONTH_HDR[i % len(_MONTH_HDR)]
def month_grp(i): return _MONTH_GRP[i % len(_MONTH_GRP)]

# ── Данные поставщика для сверки (Март 2026) ─────────────
SUPPLIER_DATA = [
    ("Джелопі Зуби 600гр",                    1216,  2883.48),
    ("Джелопі Серце 600гр",                    1007,  2465.50),
    ("Джелопі Червяки 600гр",                  1877,  4205.49),
    ("Драже Олівець Пірати 22г",                 25,   350.01),
    ("Жувальна Цукерка Тофі Тайм Вишня 25г",      3,    28.50),
    ("Жувальна Цукерка Шокер Малина-Персик",    418,  3205.00),
    ("Жуйка Кислиця Кавун",                     960,  1920.00),
    ("Жуйка Кислиця Полуниця",                 1124,  2351.45),
    ("Жуйка Куул Фреш Малина",                  911,  1822.00),
    ("Жуйка Турбо",                            3078,  7694.95),
    ("Кисло-Спрей 25г",                         122,  1829.99),
    ("Льодяник Кисла П*ятка 9гр",              1260, 10207.40),
    ("Мармеладна Палочка Lico Rico Mix",        1647,  4941.03),
    ("Мармеладна Стрічка Мікс 15гр",           1005,  7694.00),
    ("Машинка-Сюрприз Форсаж",                  257,  7709.98),
    ("Солодкий Шприц з Джемом",                 152,  1215.99),
    ("Той Джой 3D Желейне ОКО 18г",              24,   576.00),
    ("Цукерка Юмі Джелі Ведмедики 70г",         181,  3739.67),
    ("Цукерка Юмі Джелі Кола 70г",              177,  3699.06),
    ("Цукерка Юмі Джелі Фрукти 70г",            174,  3571.05),
    ("Цуценя-Сюрприз Зоо-Планета",              292,  8759.97),
    ("Чарівний Ліхтарик 1г",                     44,   660.00),
    ("Яйце з Сюрпризом Барбелла",                10,   120.00),
    ("Яйце з Сюрпризом Зоо Планета",             76,  1520.02),
]

client = bigquery.Client(project=PROJECT)

# ══════════════════════════════════════════════════════════
#  1. SQL ЗАПРОСЫ
# ══════════════════════════════════════════════════════════

# — динамические CASE-столбцы для каждого месяца —
_pivot_cols = "\n  ".join(
    f"ROUND(SUM(CASE WHEN FORMAT_DATE('%Y-%m', DATE(t.transaction_datetime))='{m}' "
    f"THEN t.quantity    ELSE 0 END), 0) AS {month_key(m)}_qty,\n  "
    f"ROUND(SUM(CASE WHEN FORMAT_DATE('%Y-%m', DATE(t.transaction_datetime))='{m}' "
    f"THEN t.check_amount ELSE 0 END), 2) AS {month_key(m)}_sum,"
    for m in MONTHS
)

SQL_PIVOT = f"""
SELECT
  t.barcode,
  ANY_VALUE(t.product_name)           AS product_name,
  {_pivot_cols}
  ROUND(SUM(t.quantity),    0)        AS qty_total,
  ROUND(SUM(t.check_amount),2)        AS sum_total
FROM `{PROJECT}.family_market.turnover_transactions` t
WHERE LOWER(t.product_name) LIKE '%монжар%'
  AND DATE(t.transaction_datetime) >= '{PERIOD_FROM}'
  AND DATE(t.transaction_datetime) <  '{PERIOD_TO}'
GROUP BY t.barcode
HAVING sum_total > 0
ORDER BY sum_total DESC
"""

# — по магазинам: только итог (адрес, SKU-позиций, выручка) —
SQL_STORES = f"""
SELECT
  t.store,
  COUNT(DISTINCT t.barcode)        AS sku_count,
  ROUND(SUM(t.quantity),    0)     AS qty_total,
  ROUND(SUM(t.check_amount), 2)    AS revenue_total
FROM `{PROJECT}.family_market.turnover_transactions` t
WHERE LOWER(t.product_name) LIKE '%монжар%'
  AND DATE(t.transaction_datetime) >= '{PERIOD_FROM}'
  AND DATE(t.transaction_datetime) <  '{PERIOD_TO}'
GROUP BY t.store
ORDER BY revenue_total DESC
"""

# — сверка: GROUP BY product_name для точного маппинга —
SQL_RECONCILE = f"""
SELECT
  t.product_name,
  STRING_AGG(DISTINCT t.barcode ORDER BY t.barcode) AS barcodes,
  ROUND(SUM(t.quantity),    0)    AS qty_mar,
  ROUND(SUM(t.check_amount), 2)   AS sum_mar
FROM `{PROJECT}.family_market.turnover_transactions` t
WHERE LOWER(t.product_name) LIKE '%монжар%'
  AND DATE(t.transaction_datetime) >= '{PERIOD_FROM}'
  AND DATE(t.transaction_datetime) <  '2026-04-01'
GROUP BY t.product_name
ORDER BY sum_mar DESC
"""

print(f"Период: {PERIOD_FROM} — {PERIOD_TO}  |  Месяцев: {len(MONTHS)}")
print("Запрос BigQuery — сводка по позициям...")
rows_pivot    = list(client.query(SQL_PIVOT).result());    print(f"  {len(rows_pivot)} позиций")
print("Запрос BigQuery — по магазинам...")
rows_stores   = list(client.query(SQL_STORES).result());   print(f"  {len(rows_stores)} магазинов")
print("Запрос BigQuery — сверка (март)...")
rows_reconcile= list(client.query(SQL_RECONCILE).result()); print(f"  {len(rows_reconcile)} названий")

# ══════════════════════════════════════════════════════════
#  2. СТИЛИ
# ══════════════════════════════════════════════════════════
TITLE_BG = "1B4F72"
HDR_BG   = "2E75B6"
COL_TOT  = "FFF9C4"
ROW_ALT  = "F5F5F5"
SUBTITLE = "E8F0FA"

def fill(hex_): return PatternFill("solid", fgColor=hex_)
def thin_border():
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)
FMT_MONEY = '#,##0.00'
FMT_QTY   = '#,##0'
FMT_PCT   = '0.0"%"'

def make_title(ws, text, ncols, row=1):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = Font(bold=True, size=13, color="FFFFFF")
    c.fill = fill(TITLE_BG)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[row].height = 32

def make_subtitle(ws, text, ncols, row=2):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    c = ws.cell(row=row, column=1, value=text)
    c.font = Font(italic=True, size=10, color="444444")
    c.fill = fill(SUBTITLE)
    c.alignment = Alignment(horizontal="center")
    ws.row_dimensions[row].height = 16

def hdr(ws, row, col, text, bg=None, wrap=True):
    c = ws.cell(row=row, column=col, value=text)
    c.font = Font(bold=True, color="FFFFFF", size=10)
    c.fill = fill(bg or HDR_BG)
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=wrap)
    c.border = thin_border()
    return c

def data_cell(ws, row, col, val, fmt=None, bg=None):
    c = ws.cell(row=row, column=col, value=val)
    c.border = thin_border()
    c.alignment = Alignment(horizontal="center", vertical="center")
    if fmt:  c.number_format = fmt
    if bg:   c.fill = fill(bg)
    return c

today = datetime.now().strftime("%d.%m.%Y")

# ══════════════════════════════════════════════════════════
#  3. WORKBOOK
# ══════════════════════════════════════════════════════════
wb = Workbook()

# ── Структура столбцов Листа 1 ────────────────────────────
# col 1: barcode, col 2: name
# col 3+2i, 4+2i : qty/sum месяца i
# col 3+2N, 4+2N : qty/sum ИТОГО
# col 5+2N       : доля %
N = len(MONTHS)
COL_BARCODE = 1
COL_NAME    = 2
def col_qty(i): return 3 + 2 * i        # i=0..N-1 → месяцы; i=N → ИТОГО
def col_sum(i): return 4 + 2 * i
COL_SHARE   = 5 + 2 * N
NCOLS1      = COL_SHARE

# ══════════════════════════════════════════════════════════
#  ЛИСТ 1: Сводка по позициям
# ══════════════════════════════════════════════════════════
ws1 = wb.active
ws1.title = "Сводка по позициям"

period_str = " — ".join(month_label(m) for m in [MONTHS[0], MONTHS[-1]]) \
             if len(MONTHS) > 1 else month_label(MONTHS[0])
make_title(ws1, f"Вторичные продажи — {SUPPLIER}  |  {period_str}", NCOLS1)
make_subtitle(ws1,
    f"Источник: BigQuery turnover_transactions  |  Сформировано: {today}  |  Family Market",
    NCOLS1)

# Строка 3: групповые заголовки месяцев + ИТОГО
for i, m in enumerate(MONTHS):
    c1, c2 = col_qty(i), col_sum(i)
    ws1.merge_cells(start_row=3, start_column=c1, end_row=3, end_column=c2)
    c = ws1.cell(row=3, column=c1, value=month_label(m))
    c.font = Font(bold=True, color=month_grp(i), size=10)
    c.fill = fill(month_bg(i).replace("BDD7EE","BDD7EE"))
    # lighter tint for group header
    tint = month_bg(i)
    c.fill = fill(tint)
    c.alignment = Alignment(horizontal="center")
    c.border = thin_border()
    ws1.cell(row=3, column=c2).border = thin_border()

ws1.merge_cells(start_row=3, start_column=col_qty(N), end_row=3, end_column=col_sum(N))
c = ws1.cell(row=3, column=col_qty(N), value="ИТОГО")
c.font = Font(bold=True, color="7D6608", size=10)
c.fill = fill("FFEB9C")
c.alignment = Alignment(horizontal="center")
c.border = thin_border()
ws1.cell(row=3, column=col_sum(N)).border = thin_border()
ws1.cell(row=3, column=COL_SHARE).border = thin_border()
ws1.row_dimensions[3].height = 20

# Строка 4: заголовки столбцов
hdr(ws1, 4, COL_BARCODE, "Штрих-код")
hdr(ws1, 4, COL_NAME,    "Название товара")
for i, m in enumerate(MONTHS):
    hdr(ws1, 4, col_qty(i), "Кол-во",     bg=month_hdr(i))
    hdr(ws1, 4, col_sum(i), "Сумма, грн", bg=month_hdr(i))
hdr(ws1, 4, col_qty(N), "Кол-во",     bg="BF9000")
hdr(ws1, 4, col_sum(N), "Сумма, грн", bg="BF9000")
hdr(ws1, 4, COL_SHARE,  "Доля, %")
ws1.row_dimensions[4].height = 28

# Накопители итогов по месяцам и общего
month_totals = {m: {"qty": 0.0, "sum": 0.0} for m in MONTHS}
grand_qty = grand_sum = 0.0
total_sum_all = sum(float(r.sum_total) for r in rows_pivot) or 1.0

for idx, r in enumerate(rows_pivot, 1):
    row = 4 + idx
    bg = ROW_ALT if idx % 2 == 0 else None

    data_cell(ws1, row, COL_BARCODE, r.barcode, bg=bg)
    c = ws1.cell(row=row, column=COL_NAME, value=r.product_name)
    c.border = thin_border()
    c.alignment = Alignment(horizontal="left", vertical="center")
    if bg: c.fill = fill(bg)

    for i, m in enumerate(MONTHS):
        k = month_key(m)
        q = float(getattr(r, f"{k}_qty"))
        s = float(getattr(r, f"{k}_sum"))
        zone = month_bg(i)
        data_cell(ws1, row, col_qty(i), int(q) if q == int(q) else q, FMT_QTY,   zone)
        data_cell(ws1, row, col_sum(i), s,                             FMT_MONEY, zone)
        month_totals[m]["qty"] += q
        month_totals[m]["sum"] += s

    qt = float(r.qty_total); st = float(r.sum_total)
    data_cell(ws1, row, col_qty(N), int(qt) if qt == int(qt) else qt, FMT_QTY,   "FFF9C4")
    data_cell(ws1, row, col_sum(N), st,                                FMT_MONEY, "FFF9C4")
    share = round(st / total_sum_all * 100, 1)
    data_cell(ws1, row, COL_SHARE, share, FMT_PCT, bg)
    grand_qty += qt; grand_sum += st

# Итоговая строка — заполняем ВСЕ месячные колонки
tot_row = 4 + len(rows_pivot) + 1
for col in range(1, NCOLS1 + 1):
    c = ws1.cell(tot_row, col)
    c.fill = fill(TITLE_BG); c.border = thin_border()
    c.font = Font(bold=True, color="FFFFFF")
    c.alignment = Alignment(horizontal="center", vertical="center")
ws1.cell(tot_row, COL_NAME).value = "ИТОГО"
ws1.cell(tot_row, COL_NAME).alignment = Alignment(horizontal="left", vertical="center")

for i, m in enumerate(MONTHS):
    ws1.cell(tot_row, col_qty(i)).value         = int(month_totals[m]["qty"])
    ws1.cell(tot_row, col_qty(i)).number_format = FMT_QTY
    ws1.cell(tot_row, col_sum(i)).value         = round(month_totals[m]["sum"], 2)
    ws1.cell(tot_row, col_sum(i)).number_format = FMT_MONEY
ws1.cell(tot_row, col_qty(N)).value         = int(grand_qty)
ws1.cell(tot_row, col_qty(N)).number_format = FMT_QTY
ws1.cell(tot_row, col_sum(N)).value         = round(grand_sum, 2)
ws1.cell(tot_row, col_sum(N)).number_format = FMT_MONEY
ws1.row_dimensions[tot_row].height = 24

# Примечание
note_row = tot_row + 2
ws1.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=NCOLS1)
ws1.cell(note_row, 1).value = (
    "* Фильтр: product_name LIKE '%монжар%'. "
    "Штрих-код — штрих-код ШТУЧКИ (единица продажи из кассы), а не упаковки."
)
ws1.cell(note_row, 1).font = Font(italic=True, size=9, color="666666")
ws1.cell(note_row, 1).fill = fill("FFFDE7")
ws1.cell(note_row, 1).alignment = Alignment(wrap_text=True)
ws1.row_dimensions[note_row].height = 24

# Ширины столбцов
ws1.column_dimensions[get_column_letter(COL_BARCODE)].width = 18
ws1.column_dimensions[get_column_letter(COL_NAME)].width    = 48
for i in range(N + 1):  # месяцы + итого
    ws1.column_dimensions[get_column_letter(col_qty(i))].width = 11
    ws1.column_dimensions[get_column_letter(col_sum(i))].width = 16
ws1.column_dimensions[get_column_letter(COL_SHARE)].width = 10
ws1.freeze_panes = "A5"

# ══════════════════════════════════════════════════════════
#  ЛИСТ 2: По магазинам (упрощённый)
# ══════════════════════════════════════════════════════════
ws2 = wb.create_sheet("По магазинам")
NCOLS2 = 4

make_title(ws2, f"Продажи по магазинам — {SUPPLIER}  |  {period_str}", NCOLS2)
make_subtitle(ws2, f"Сформировано: {today}  |  Family Market", NCOLS2)

hdr(ws2, 3, 1, "Магазин (адрес)")
hdr(ws2, 3, 2, "Позиций (SKU)",   bg="548235")
hdr(ws2, 3, 3, "Кол-во, шт",      bg="548235")
hdr(ws2, 3, 4, "Сумма, грн",      bg="BF9000")
ws2.row_dimensions[3].height = 28

grand_s_qty = grand_s_rev = 0.0

for idx, r in enumerate(rows_stores, 1):
    row = 3 + idx
    bg = ROW_ALT if idx % 2 == 0 else None
    c = ws2.cell(row=row, column=1, value=r.store)
    c.border = thin_border()
    c.alignment = Alignment(horizontal="left", vertical="center")
    if bg: c.fill = fill(bg)
    data_cell(ws2, row, 2, int(r.sku_count),   FMT_QTY,   bg)
    data_cell(ws2, row, 3, int(r.qty_total),   FMT_QTY,   bg)
    data_cell(ws2, row, 4, float(r.revenue_total), FMT_MONEY, "FFF9C4")
    grand_s_qty += float(r.qty_total)
    grand_s_rev += float(r.revenue_total)

# Итоговая строка
tot2 = 3 + len(rows_stores) + 1
for col in range(1, 5):
    c = ws2.cell(tot2, col)
    c.fill = fill(TITLE_BG); c.border = thin_border()
    c.font = Font(bold=True, color="FFFFFF")
    c.alignment = Alignment(horizontal="center", vertical="center")
ws2.cell(tot2, 1).value = f"ИТОГО  ({len(rows_stores)} магазинов)"
ws2.cell(tot2, 1).alignment = Alignment(horizontal="left", vertical="center")
ws2.cell(tot2, 3).value = int(grand_s_qty); ws2.cell(tot2, 3).number_format = FMT_QTY
ws2.cell(tot2, 4).value = round(grand_s_rev, 2); ws2.cell(tot2, 4).number_format = FMT_MONEY
ws2.row_dimensions[tot2].height = 22

ws2.column_dimensions["A"].width = 42
ws2.column_dimensions["B"].width = 16
ws2.column_dimensions["C"].width = 14
ws2.column_dimensions["D"].width = 18
ws2.freeze_panes = "A4"

# ══════════════════════════════════════════════════════════
#  ЛИСТ 3: Сверка с поставщиком (март)
# ══════════════════════════════════════════════════════════
def map_to_supplier(bq_name: str) -> str:
    n = bq_name.lower()
    if "джелопі зуби"               in n: return "Джелопі Зуби 600гр"
    if "джелопі серце"              in n: return "Джелопі Серце 600гр"
    if "джелопі червяки"            in n: return "Джелопі Червяки 600гр"
    if "олівець" in n and "пірат"   in n: return "Драже Олівець Пірати 22г"
    if "тофі тайм"                  in n: return "Жувальна Цукерка Тофі Тайм Вишня 25г"
    if "шокер малина"               in n: return "Жувальна Цукерка Шокер Малина-Персик"
    if "кислиця кавун"              in n: return "Жуйка Кислиця Кавун"
    if "кислиця полуниця"           in n: return "Жуйка Кислиця Полуниця"
    if "куул фреш малина"           in n: return "Жуйка Куул Фреш Малина"
    if "жуйка турбо"                in n: return "Жуйка Турбо"
    if "кисло-спрей"                in n: return "Кисло-Спрей 25г"
    if "кисла п"                    in n: return "Льодяник Кисла П*ятка 9гр"
    if "lico rico"                  in n: return "Мармеладна Палочка Lico Rico Mix"
    if "стрічка мікс"               in n: return "Мармеладна Стрічка Мікс 15гр"
    if "машинка-сюрприз форсаж"     in n: return "Машинка-Сюрприз Форсаж"
    if "шприц з джемом"             in n: return "Солодкий Шприц з Джемом"
    if "той джой"                   in n: return "Той Джой 3D Желейне ОКО 18г"
    if "юмі джелі ведмедики"        in n: return "Цукерка Юмі Джелі Ведмедики 70г"
    if "юмі джелі кола"             in n: return "Цукерка Юмі Джелі Кола 70г"
    if "юмі джелі фрукти"           in n: return "Цукерка Юмі Джелі Фрукти 70г"
    if "цуценя-сюрприз"             in n: return "Цуценя-Сюрприз Зоо-Планета"
    if "чарівний ліхтарик"          in n: return "Чарівний Ліхтарик 1г"
    if "яйце" in n and "барбелла"   in n: return "Яйце з Сюрпризом Барбелла"
    if "яйце" in n and "зоо планета"in n: return "Яйце з Сюрпризом Зоо Планета"
    return "— не в списку поставщика"

ws3 = wb.create_sheet("Сверка с поставщиком")
NCOLS3 = 8
make_title(ws3, f"Сверка BQ vs поставщик — {SUPPLIER}  |  Март 2026", NCOLS3)
make_subtitle(ws3,
    f"Данные поставщика: «Продажи Монжар март 26.xlsx»  |  Сформировано: {today}",
    NCOLS3)

for col, (text, bg) in enumerate([
    ("Позиция поставщика", HDR_BG), ("Штрих-коды BQ", HDR_BG),
    ("Кол-во (пост.)",  "4472C4"), ("Кол-во (BQ)",   "4472C4"), ("Δ кол-во", HDR_BG),
    ("Сумма (пост.), грн", "548235"), ("Сумма (BQ), грн", "548235"), ("Δ сумма, грн", HDR_BG),
], 1):
    hdr(ws3, 3, col, text, bg)
ws3.row_dimensions[3].height = 30

bq_by_supplier = defaultdict(lambda: {"qty": 0.0, "revenue": 0.0, "barcodes": set()})
for r in rows_reconcile:
    sn = map_to_supplier(r.product_name)
    bq_by_supplier[sn]["qty"]     += float(r.qty_mar)
    bq_by_supplier[sn]["revenue"] += float(r.sum_mar)
    for bc in r.barcodes.split(","):
        bq_by_supplier[sn]["barcodes"].add(bc.strip())

STATUS_FILL = {"✅": "D4EDDA", "⚠️": "FFF3CD", "🔴": "F8D7DA", "❌": "F8D7DA"}
grand_s_qty2 = grand_s_rev2 = grand_b_qty2 = grand_b_rev2 = 0.0

for idx, (name, s_qty, s_rev) in enumerate(SUPPLIER_DATA, 1):
    row = 3 + idx
    bq   = bq_by_supplier.get(name, {"qty": 0.0, "revenue": 0.0, "barcodes": set()})
    b_qty, b_rev = bq["qty"], bq["revenue"]
    barcodes_str = ", ".join(sorted(bq["barcodes"])) if bq["barcodes"] else "—"
    d_qty = round(b_qty - s_qty, 0)
    d_rev = round(b_rev - s_rev, 2)

    if   not bq["barcodes"]:       status = "❌"
    elif abs(d_rev) < 50:          status = "✅"
    elif abs(d_rev) < 500:         status = "⚠️"
    else:                           status = "🔴"
    rc = STATUS_FILL[status]

    vals = [f"{status} {name}", barcodes_str,
            s_qty, b_qty or None, d_qty if bq["barcodes"] else None,
            s_rev, b_rev or None, d_rev if bq["barcodes"] else None]
    fmts = [None, None, FMT_QTY, FMT_QTY, FMT_QTY, FMT_MONEY, FMT_MONEY, FMT_MONEY]
    for col, (val, fmt) in enumerate(zip(vals, fmts), 1):
        c = ws3.cell(row=row, column=col, value=val)
        c.fill = fill(rc); c.border = thin_border()
        c.alignment = Alignment(horizontal="center" if col > 2 else "left", vertical="center")
        if fmt and val is not None: c.number_format = fmt

    grand_s_qty2 += s_qty;  grand_s_rev2 += s_rev
    grand_b_qty2 += b_qty;  grand_b_rev2 += b_rev

tot3 = 3 + len(SUPPLIER_DATA) + 1
for col in range(1, 9):
    c = ws3.cell(tot3, col)
    c.fill = fill(TITLE_BG); c.border = thin_border()
    c.font = Font(bold=True, color="FFFFFF")
    c.alignment = Alignment(horizontal="center", vertical="center")
ws3.cell(tot3, 1).value = "ИТОГО"; ws3.cell(tot3, 1).alignment = Alignment(horizontal="left", vertical="center")
for col, (val, fmt) in zip([3,4,5,6,7,8], [
    (int(grand_s_qty2), FMT_QTY), (int(grand_b_qty2), FMT_QTY),
    (int(grand_b_qty2-grand_s_qty2), FMT_QTY),
    (round(grand_s_rev2,2), FMT_MONEY), (round(grand_b_rev2,2), FMT_MONEY),
    (round(grand_b_rev2-grand_s_rev2,2), FMT_MONEY),
]):
    ws3.cell(tot3, col).value = val; ws3.cell(tot3, col).number_format = fmt
ws3.row_dimensions[tot3].height = 22

# Легенда
for j, (label, color, desc) in enumerate([
    ("✅ Сходится",              "D4EDDA", "Расхождение < 50 грн"),
    ("⚠️ Небольшое расхождение", "FFF3CD", "50–500 грн"),
    ("🔴 Большое расхождение",   "F8D7DA", "> 500 грн — возможно лишний штрих-код в маппинге"),
    ("❌ Не найдено в BQ",       "F8D7DA", "Нет продаж за март 2026 или не совпало название"),
], 1):
    r = tot3 + j + 1
    ws3.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
    ws3.cell(r, 1, label).fill = fill(color); ws3.cell(r, 1).border = thin_border()
    ws3.cell(r, 1).font = Font(bold=True, size=9)
    ws3.merge_cells(start_row=r, start_column=3, end_row=r, end_column=NCOLS3)
    ws3.cell(r, 3, desc).fill = fill(color); ws3.cell(r, 3).border = thin_border()
    ws3.cell(r, 3).font = Font(italic=True, size=9, color="444444")
    ws3.row_dimensions[r].height = 16

for col, w in enumerate([38, 42, 14, 14, 11, 20, 20, 16], 1):
    ws3.column_dimensions[get_column_letter(col)].width = w
ws3.freeze_panes = "A4"

# ══════════════════════════════════════════════════════════
#  4. СОХРАНЕНИЕ
# ══════════════════════════════════════════════════════════
out = r"D:\РЕТРО_БОНУСЫ Фэмэли маркет\Продажи_Монжар_март_апрель_2026.xlsx"
wb.save(out)
print(f"\nФайл сохранён: {out}")
print(f"Позиций: {len(rows_pivot)} | Магазинов: {len(rows_stores)}")
print(f"Итого (март+апрель): {grand_sum:,.2f} грн  |  {grand_qty:,.0f} шт")
print(f"\nСверка (март):")
print(f"  Поставщик : {grand_s_qty2:>7,.0f} шт  /  {grand_s_rev2:>12,.2f} грн")
print(f"  BQ        : {grand_b_qty2:>7,.0f} шт  /  {grand_b_rev2:>12,.2f} грн")
print(f"  Разница   : {grand_b_qty2-grand_s_qty2:>+7,.0f} шт  /  {grand_b_rev2-grand_s_rev2:>+12,.2f} грн")

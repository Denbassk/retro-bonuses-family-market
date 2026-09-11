#!/usr/bin/env python3
"""
create_retro_sheet.py — Создание Google Sheets сводной таблицы ретро-бонусов.

Читает CSV с результатами расчёта и создаёт красиво отформатированный Google Sheet:
- Лист «Сводка» — pivot по поставщикам × месяцам
- Закреплённые заголовки, авторазмер, цветовое оформление
- Числа с разрядностью по центру, текст по левому краю

Требования:
  pip install gspread google-auth

Запуск:
  python create_retro_sheet.py                                    # из последнего CSV
  python create_retro_sheet.py retro_results_2026-01_2026-04.csv  # конкретный файл
"""

import os
import sys
import csv
import json
from pathlib import Path
from collections import defaultdict

# ─── .env ────────────────────────────────────────────────────────────────────
def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

load_env()

CREDENTIALS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
SHEET_TITLE = "Ретро-бонусы Family Market 2026"

# ─── Чтение CSV ─────────────────────────────────────────────────────────────
def read_retro_csv(csv_path):
    """Читает CSV и строит структуру для Google Sheets."""
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        # header: Поставщик;Бренд;%;Форма;2026-01;2026-02;...;ИТОГО
        months = [h for h in header[4:] if h != "ИТОГО"]

        rows = []
        for row in reader:
            if len(row) < 5:
                continue
            supplier = row[0]
            brand = row[1]
            pct = row[2]
            form = row[3]
            values = []
            for v in row[4:]:
                try:
                    values.append(float(v.replace(",", "").replace(" ", "")))
                except ValueError:
                    values.append(0.0)
            # values = month1, month2, ..., ИТОГО
            rows.append({
                "supplier": supplier,
                "brand": brand,
                "pct": pct,
                "form": form,
                "values": values[:-1],  # без ИТОГО (посчитаем формулой)
                "total": values[-1] if len(values) > len(months) else sum(values),
            })

    return months, rows

# ─── Построение сводки по поставщикам ────────────────────────────────────────
def build_summary(months, rows):
    """
    Строит сводную таблицу: поставщик → итого по месяцам.
    Возвращает list of [supplier, m1, m2, ..., total].
    """
    supplier_data = defaultdict(lambda: [0.0] * len(months))

    for r in rows:
        for i, v in enumerate(r["values"]):
            supplier_data[r["supplier"]][i] += v

    summary_rows = []
    for sup in sorted(supplier_data.keys()):
        vals = supplier_data[sup]
        total = sum(vals)
        summary_rows.append([sup] + vals + [total])

    # Итого
    totals = [0.0] * len(months)
    grand_total = 0.0
    for sr in summary_rows:
        for i in range(len(months)):
            totals[i] += sr[i + 1]
        grand_total += sr[-1]

    return summary_rows, totals, grand_total

# ─── Google Sheets API ──────────────────────────────────────────────────────
def create_google_sheet(months, rows, summary_rows, totals, grand_total):
    """Создаёт Google Sheet с двумя листами."""
    import gspread
    from google.oauth2.service_account import Credentials

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)

    # ═══ Создаём спредшит ═══
    print(f"[i] Создаю Google Sheet: {SHEET_TITLE}")
    sh = gc.create(SHEET_TITLE)
    print(f"  URL: {sh.url}")

    # Открыть доступ (себе по email)
    sh.share("denbassk@gmail.com", perm_type="user", role="writer")
    print("  Доступ: denbassk@gmail.com (writer)")

    # ═══ Лист 1: СВОДКА (поставщики × месяцы) ═══
    ws_summary = sh.sheet1
    ws_summary.update_title("Сводка")

    # --- Заголовок ---
    header1 = ["Поставщик"] + months + ["ИТОГО"]
    num_cols = len(header1)
    num_rows = len(summary_rows) + 3  # header + data + пустая + итого

    # Расширяем лист если нужно
    ws_summary.resize(rows=max(num_rows + 5, 50), cols=max(num_cols + 2, 15))

    # --- Данные ---
    all_data = [header1]
    for sr in summary_rows:
        row_data = [sr[0]]  # поставщик
        for v in sr[1:]:
            row_data.append(round(v, 2))
        all_data.append(row_data)

    # Пустая строка + ИТОГО
    all_data.append([""])
    totals_row = ["ИТОГО"] + [round(t, 2) for t in totals] + [round(grand_total, 2)]
    all_data.append(totals_row)

    ws_summary.update(range_name="A1", values=all_data)
    print(f"  Лист 'Сводка': {len(summary_rows)} поставщиков × {len(months)} месяцев")

    # ═══ Лист 2: ДЕТАЛИЗАЦИЯ (по брендам) ═══
    ws_detail = sh.add_worksheet(title="Детализация", rows=len(rows) + 10, cols=num_cols + 3)

    header2 = ["Поставщик", "Бренд", "%", "Форма"] + months + ["ИТОГО"]
    detail_data = [header2]
    for r in rows:
        row_data = [r["supplier"], r["brand"], r["pct"], r["form"]]
        for v in r["values"]:
            row_data.append(round(v, 2))
        row_data.append(round(r["total"], 2))
        detail_data.append(row_data)

    ws_detail.update(range_name="A1", values=detail_data)
    print(f"  Лист 'Детализация': {len(rows)} строк")

    # ═══ ФОРМАТИРОВАНИЕ ═══
    print("[i] Форматирование...")
    format_sheets(sh, ws_summary, ws_detail, months, summary_rows, rows)

    return sh.url

def format_sheets(sh, ws_summary, ws_detail, months, summary_rows, detail_rows):
    """Применяет форматирование через batch update."""

    summary_id = ws_summary.id
    detail_id = ws_detail.id
    num_months = len(months)

    # Цвета
    WHITE = {"red": 1, "green": 1, "blue": 1}
    HEADER_BG = {"red": 0.15, "green": 0.35, "blue": 0.6}   # тёмно-синий
    HEADER_FG = {"red": 1, "green": 1, "blue": 1}             # белый текст
    TOTALS_BG = {"red": 0.85, "green": 0.92, "blue": 0.98}    # светло-голубой
    ZEBRA_BG = {"red": 0.95, "green": 0.97, "blue": 1.0}      # очень светло-голубой
    BORDER_COLOR = {"red": 0.7, "green": 0.7, "blue": 0.7}

    total_rows_summary = len(summary_rows) + 3  # header + data + empty + totals
    total_rows_detail = len(detail_rows) + 1

    num_cols_summary = 1 + num_months + 1  # Поставщик + месяцы + ИТОГО
    num_cols_detail = 4 + num_months + 1    # Поставщик + Бренд + % + Форма + месяцы + ИТОГО

    requests = []

    # ─── СВОДКА ──────────────────────────────────────────────────────────

    # 1. Закрепить первую строку
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": summary_id,
                "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1}
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"
        }
    })

    # 2. Заголовок — тёмно-синий фон, белый жирный текст, по центру
    requests.append({
        "repeatCell": {
            "range": {"sheetId": summary_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": num_cols_summary},
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": HEADER_BG,
                    "textFormat": {"foregroundColor": HEADER_FG, "bold": True,
                                   "fontFamily": "Arial", "fontSize": 11},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "padding": {"top": 6, "bottom": 6, "left": 8, "right": 8},
                }
            },
            "fields": "userEnteredFormat"
        }
    })

    # 3. Столбец A (поставщики) — жирный, по левому краю
    requests.append({
        "repeatCell": {
            "range": {"sheetId": summary_id, "startRowIndex": 1, "endRowIndex": total_rows_summary,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"bold": True, "fontFamily": "Arial", "fontSize": 10},
                    "horizontalAlignment": "LEFT",
                    "verticalAlignment": "MIDDLE",
                    "padding": {"left": 8, "right": 8},
                }
            },
            "fields": "userEnteredFormat"
        }
    })

    # 4. Числовые столбцы — формат #,##0.00, по центру
    requests.append({
        "repeatCell": {
            "range": {"sheetId": summary_id, "startRowIndex": 1, "endRowIndex": total_rows_summary,
                      "startColumnIndex": 1, "endColumnIndex": num_cols_summary},
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "textFormat": {"fontFamily": "Arial", "fontSize": 10},
                    "padding": {"left": 4, "right": 4},
                }
            },
            "fields": "userEnteredFormat"
        }
    })

    # 5. Зебра (чередование строк)
    for i in range(len(summary_rows)):
        if i % 2 == 1:
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": summary_id,
                              "startRowIndex": i + 1, "endRowIndex": i + 2,
                              "startColumnIndex": 0, "endColumnIndex": num_cols_summary},
                    "cell": {
                        "userEnteredFormat": {"backgroundColor": ZEBRA_BG}
                    },
                    "fields": "userEnteredFormat.backgroundColor"
                }
            })

    # 6. Строка ИТОГО — голубой фон, жирный
    totals_row_idx = len(summary_rows) + 2  # +1 header +1 empty
    requests.append({
        "repeatCell": {
            "range": {"sheetId": summary_id,
                      "startRowIndex": totals_row_idx, "endRowIndex": totals_row_idx + 1,
                      "startColumnIndex": 0, "endColumnIndex": num_cols_summary},
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": TOTALS_BG,
                    "textFormat": {"bold": True, "fontFamily": "Arial", "fontSize": 11},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
                }
            },
            "fields": "userEnteredFormat"
        }
    })

    # 7. Столбец ИТОГО — жирный
    itogo_col = num_cols_summary - 1
    requests.append({
        "repeatCell": {
            "range": {"sheetId": summary_id,
                      "startRowIndex": 1, "endRowIndex": total_rows_summary,
                      "startColumnIndex": itogo_col, "endColumnIndex": itogo_col + 1},
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"bold": True},
                }
            },
            "fields": "userEnteredFormat.textFormat.bold"
        }
    })

    # 8. Границы — тонкая сетка по всем данным
    requests.append({
        "updateBorders": {
            "range": {"sheetId": summary_id,
                      "startRowIndex": 0, "endRowIndex": totals_row_idx + 1,
                      "startColumnIndex": 0, "endColumnIndex": num_cols_summary},
            "top": {"style": "SOLID", "color": BORDER_COLOR},
            "bottom": {"style": "SOLID", "color": BORDER_COLOR},
            "left": {"style": "SOLID", "color": BORDER_COLOR},
            "right": {"style": "SOLID", "color": BORDER_COLOR},
            "innerHorizontal": {"style": "SOLID", "color": BORDER_COLOR},
            "innerVertical": {"style": "SOLID", "color": BORDER_COLOR},
        }
    })

    # 9. Жирная граница под заголовком
    requests.append({
        "updateBorders": {
            "range": {"sheetId": summary_id,
                      "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": num_cols_summary},
            "bottom": {"style": "SOLID_MEDIUM", "color": {"red": 0.1, "green": 0.2, "blue": 0.4}},
        }
    })

    # 10. Жирная граница над ИТОГО
    requests.append({
        "updateBorders": {
            "range": {"sheetId": summary_id,
                      "startRowIndex": totals_row_idx, "endRowIndex": totals_row_idx + 1,
                      "startColumnIndex": 0, "endColumnIndex": num_cols_summary},
            "top": {"style": "SOLID_MEDIUM", "color": {"red": 0.1, "green": 0.2, "blue": 0.4}},
            "bottom": {"style": "SOLID_MEDIUM", "color": {"red": 0.1, "green": 0.2, "blue": 0.4}},
        }
    })

    # 11. Авторазмер столбцов
    for col_idx in range(num_cols_summary):
        requests.append({
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": summary_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                }
            }
        })

    # 12. Минимальная ширина для столбца поставщика
    requests.append({
        "updateDimensionProperties": {
            "range": {"sheetId": summary_id, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 280},
            "fields": "pixelSize"
        }
    })

    # 13. Высота строки заголовка
    requests.append({
        "updateDimensionProperties": {
            "range": {"sheetId": summary_id, "dimension": "ROWS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 36},
            "fields": "pixelSize"
        }
    })

    # ─── ДЕТАЛИЗАЦИЯ ─────────────────────────────────────────────────────

    # Закрепить заголовок + столбцы Поставщик/Бренд
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": detail_id,
                "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"
        }
    })

    # Заголовок детализации
    requests.append({
        "repeatCell": {
            "range": {"sheetId": detail_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": num_cols_detail},
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": HEADER_BG,
                    "textFormat": {"foregroundColor": HEADER_FG, "bold": True,
                                   "fontFamily": "Arial", "fontSize": 10},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "padding": {"top": 6, "bottom": 6},
                }
            },
            "fields": "userEnteredFormat"
        }
    })

    # Текстовые столбцы (Поставщик, Бренд, %, Форма) — по левому краю
    requests.append({
        "repeatCell": {
            "range": {"sheetId": detail_id, "startRowIndex": 1, "endRowIndex": total_rows_detail,
                      "startColumnIndex": 0, "endColumnIndex": 4},
            "cell": {
                "userEnteredFormat": {
                    "horizontalAlignment": "LEFT",
                    "verticalAlignment": "MIDDLE",
                    "textFormat": {"fontFamily": "Arial", "fontSize": 10},
                }
            },
            "fields": "userEnteredFormat"
        }
    })

    # Числовые столбцы детализации
    requests.append({
        "repeatCell": {
            "range": {"sheetId": detail_id, "startRowIndex": 1, "endRowIndex": total_rows_detail,
                      "startColumnIndex": 4, "endColumnIndex": num_cols_detail},
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "textFormat": {"fontFamily": "Arial", "fontSize": 10},
                }
            },
            "fields": "userEnteredFormat"
        }
    })

    # Границы детализации
    requests.append({
        "updateBorders": {
            "range": {"sheetId": detail_id,
                      "startRowIndex": 0, "endRowIndex": total_rows_detail,
                      "startColumnIndex": 0, "endColumnIndex": num_cols_detail},
            "top": {"style": "SOLID", "color": BORDER_COLOR},
            "bottom": {"style": "SOLID", "color": BORDER_COLOR},
            "left": {"style": "SOLID", "color": BORDER_COLOR},
            "right": {"style": "SOLID", "color": BORDER_COLOR},
            "innerHorizontal": {"style": "SOLID", "color": BORDER_COLOR},
            "innerVertical": {"style": "SOLID", "color": BORDER_COLOR},
        }
    })

    # Авторазмер столбцов детализации
    for col_idx in range(num_cols_detail):
        requests.append({
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": detail_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                }
            }
        })

    # Зебра детализации
    for i in range(len(detail_rows)):
        if i % 2 == 1:
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": detail_id,
                              "startRowIndex": i + 1, "endRowIndex": i + 2,
                              "startColumnIndex": 0, "endColumnIndex": num_cols_detail},
                    "cell": {
                        "userEnteredFormat": {"backgroundColor": ZEBRA_BG}
                    },
                    "fields": "userEnteredFormat.backgroundColor"
                }
            })

    # ─── ОТПРАВКА ────────────────────────────────────────────────────────
    # Batch update по 50 запросов (лимит API)
    BATCH_SIZE = 50
    for i in range(0, len(requests), BATCH_SIZE):
        batch = requests[i:i + BATCH_SIZE]
        sh.batch_update({"requests": batch})

    print(f"  Форматирование применено ({len(requests)} операций)")

# ═══════════════════════════════════════════════════════════════════════════
def main():
    # Найти CSV
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    else:
        # Ищем последний retro_results_*.csv
        csv_files = sorted(Path(__file__).parent.glob("retro_results_*.csv"),
                          key=lambda f: f.stat().st_mtime, reverse=True)
        if not csv_files:
            print("Ошибка: не найден retro_results_*.csv")
            sys.exit(1)
        csv_path = csv_files[0]

    print(f"[i] CSV: {csv_path}")

    months, rows = read_retro_csv(csv_path)
    print(f"  Месяцев: {len(months)}, строк: {len(rows)}")

    summary_rows, totals, grand_total = build_summary(months, rows)
    print(f"  Поставщиков в сводке: {len(summary_rows)}")
    print(f"  Grand total: {grand_total:,.2f} грн")

    url = create_google_sheet(months, rows, summary_rows, totals, grand_total)

    print(f"\n{'=' * 60}")
    print(f"  ГОТОВО!")
    print(f"  {url}")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()

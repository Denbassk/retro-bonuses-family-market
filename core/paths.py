"""paths.py - единые пути проекта. Скрипты лежат в core/, данные - в корне проекта."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent       # D:\РЕТРО_БОНУСЫ Фэмэли маркет
OUT = ROOT / "output"                               # всё, что генерируют скрипты
EXCEL_DIR = ROOT / "Ретро_Excel"                    # входящие версии «Ретро Бонусы»
REF_DIR = ROOT / "data" / "справочники"             # Маппинг имен.xlsx и пр.
OUT.mkdir(exist_ok=True)

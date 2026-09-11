"""
Генерирует шаблон маппинга: имена поставщиков из Excel → supplier_id в Supabase.
Запуск: python gen_payment_mapping_template.py
"""
import os, sys, json, urllib.request
from pathlib import Path
from openpyxl import load_workbook

# Загрузка .env
def load_env():
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())
load_env()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

def sb_get(table, params=""):
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{table}?{params}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# 1. Список поставщиков из Supabase
suppliers = sb_get("suppliers", "select=id,name&order=name")
print(f"[i] Поставщиков в Supabase: {len(suppliers)}")

# 2. Имена с листа «2026»
xlsx = Path(__file__).resolve().parent.parent / "Ретро_Excel" / "старые" / "Ретро Бонусы 2026-05-15.xlsx"
wb = load_workbook(xlsx, data_only=True)
ws = wb["2026"]

excel_names = []
for row in range(2, ws.max_row + 1):
    name = ws.cell(row=row, column=1).value
    if not name: continue
    name = str(name).strip()
    if name.lower() in ("общая сумма", "сумма", "итого", ""): continue
    excel_names.append(name)

print(f"[i] Имён в Excel «2026»: {len(excel_names)}")

# 3. Автомэппинг — пытаемся найти совпадение по подстроке
def normalize(s):
    import re
    s = re.sub(r"\s+", " ", s.lower()).strip()
    s = re.sub(r"[()]", "", s)
    return s

mapping = {}
for ex_name in excel_names:
    norm_ex = normalize(ex_name)
    candidates = []
    for s in suppliers:
        norm_db = normalize(s["name"])
        if norm_ex == norm_db:
            candidates = [(s["id"], s["name"], "EXACT")]
            break
        # частичное совпадение по первому слову
        first_word_ex = norm_ex.split()[0] if norm_ex else ""
        first_word_db = norm_db.split()[0] if norm_db else ""
        if first_word_ex and first_word_ex == first_word_db:
            candidates.append((s["id"], s["name"], "FIRST_WORD"))
    if candidates:
        # Сортируем: EXACT > FIRST_WORD
        candidates.sort(key=lambda x: 0 if x[2] == "EXACT" else 1)
        mapping[ex_name] = {
            "supplier_id": candidates[0][0],
            "supplier_name": candidates[0][1],
            "match": candidates[0][2],
            "alternatives": [{"id": c[0], "name": c[1]} for c in candidates[1:5]] if len(candidates) > 1 else []
        }
    else:
        mapping[ex_name] = {
            "supplier_id": None,
            "supplier_name": None,
            "match": "NOT_FOUND",
            "alternatives": []
        }

# 4. Сохраняем шаблон
out = Path(__file__).resolve().parent / "payment_facts_mapping.template.json"
out.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")

# Статистика
exact = sum(1 for v in mapping.values() if v["match"] == "EXACT")
firstword = sum(1 for v in mapping.values() if v["match"] == "FIRST_WORD")
notfound = sum(1 for v in mapping.values() if v["match"] == "NOT_FOUND")
print(f"\n  EXACT совпадения:    {exact}")
print(f"  FIRST_WORD:          {firstword}  (проверь вручную!)")
print(f"  NOT_FOUND:           {notfound}  (нужно заполнить)")
print(f"\n[>] Шаблон: {out}")
print(f"    Проверь FIRST_WORD/NOT_FOUND, исправь supplier_id, сохрани как payment_facts_mapping.json")

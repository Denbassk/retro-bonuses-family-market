"""Разовый патч admin.html: блок позиционного отчёта по SKU + кнопка в тулбаре вкладки загрузки."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
fn = ROOT / "admin.html"
s = fn.read_text(encoding="utf-8")

anchor = "async function uploadRetroExcel() {"
assert s.count(anchor) == 1
s = s.replace(anchor, (ROOT / "_archive" / "new_sku_ui.js").read_text(encoding="utf-8") + anchor)

btn = '    <button class="btn btn-ghost" onclick="showDataHealth()" title="Полнота базы: документы BigQuery против эталона Торгсофт">🚦 Данные</button>'
assert s.count(btn) == 1
s = s.replace(btn, btn + '\n    <button class="btn btn-ghost" onclick="showSkuCoverage()" '
                        'title="Позиции: что попало в ретро, а что нет">📦 Позиции</button>')
fn.write_text(s, encoding="utf-8")
print("ok")

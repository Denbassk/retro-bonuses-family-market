"""Разовый патч admin.html: доплаты «не ретро» с режимом payment_mode (in_payment / separate)."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
A = ROOT / "_archive"
fn = ROOT / "admin.html"
s = fn.read_text(encoding="utf-8")


def between(s, start, end, new, keep_end=True):
    a = s.index(start)
    b = s.index(end, a)
    assert s.count(start) == 1, start
    return s[:a] + new + (s[b:] if keep_end else s[b + len(end):])


# 1. список доплат в окне ячейки - из retro_adjustments (оба режима)
s = between(s, "  let extrasHtml = '';\n  if (calcId) {", "  const html = `", (A / "new_extras_modal.js").read_text(encoding="utf-8"))

# 2. под «Начислено» - из чего оно состоит
old = '      <div style="color:var(--text2);font-size:13px">Начислено: <b style="color:var(--accent)">${fmt(charged)} ₴</b></div>'
assert s.count(old) == 1
s = s.replace(old, old + "\n      ${chargedNote ? `<div style=\"color:var(--text2);font-size:12px\">${chargedNote}</div>` : ''}")

# 3. форма добавления - всегда (отдельная выплата расчёта не требует), с выбором режима
s = between(s, "    ${calcId ? `\n    <div style=\"margin-top:16px", "    </div>` : ''}",
            (A / "new_extras_form.js").read_text(encoding="utf-8"), keep_end=False)

# 4. функции добавления/удаления
s = between(s, "async function addExtraPayment(calcId) {", "async function saveReconFact(",
            (A / "new_extras_funcs.js").read_text(encoding="utf-8"))

# 5. загрузка доплат вместе с данными «Факт оплат ретро»
old = "  reconData = { calcs: calcs || [], facts: facts || [], months, suppliers, baseTypeBySupplier, reconMap };"
assert s.count(old) == 1
s = s.replace(old, """  // Доплаты «не ретро» (оба режима) — для ячеек и окна факта
  const { data: adjRows, error: e4 } = await sb.from('retro_adjustments').select('*');
  const adjMap = {};
  (adjRows || []).forEach(a => { const k = a.supplier_id + '|' + a.period_label; (adjMap[k] = adjMap[k] || []).push(a); });
  if (e4) console.warn('retro_adjustments:', e4.message);

  reconData = { calcs: calcs || [], facts: facts || [], months, suppliers, baseTypeBySupplier, reconMap, adjs: adjMap };""")

# 6. в ячейке - строка «+5 400 отдельно»
old = "  return `<td class=\"${isLocked ? '' : 'editable'}\""
assert s.count(old) == 1
s = s.replace(old, """  const sepSum = ((reconData.adjs || {})[supId + '|' + period] || []).filter(a => adjMode(a) === 'separate')
    .reduce((acc, a) => acc + (parseFloat(a.amount) || 0), 0);
  const sepLine = sepSum ? `<div style="font-size:10px;color:#94a3b8" title="Заплачено отдельно, в «Оплачено» не входит">+${fmt(sepSum)} отдельно</div>` : '';

""" + old)
old = "    <div style=\"font-size:11px;color:var(--text2)\">з ${fmt(charged)} ${status.icon}</div>\n    ${reconBadge}"
assert s.count(old) == 1
s = s.replace(old, "    <div style=\"font-size:11px;color:var(--text2)\">з ${fmt(charged)} ${status.icon}</div>\n    ${sepLine}\n    ${reconBadge}")

fn.write_text(s, encoding="utf-8")
print("ok")

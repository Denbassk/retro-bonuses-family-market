// отметки черновика хранятся в самом importDraft - переживают переключение вкладок и перерисовку
function impChecked(kind, cell, def) {
  const k = kind + ':' + cell;
  return importDraft._sel && k in importDraft._sel ? importDraft._sel[k] : def;
}
function impToggle(el) {
  importDraft._sel = importDraft._sel || {};
  importDraft._sel[el.dataset.kind + ':' + el.dataset.cell] = el.checked;
  updateImportTotals();
}
function impTile(n, label, color, hint) {
  return `<div style="flex:1;min-width:170px;padding:10px 14px;background:var(--surface2);border-radius:8px;border-left:4px solid ${color}">
    <div style="font-size:22px;font-weight:700;color:${color}">${n}</div>
    <div style="font-size:13px;font-weight:600">${label}</div>
    <div style="font-size:11px;color:var(--text2)">${hint}</div></div>`;
}

function renderImportDraft() {
  const d = importDraft;
  const wrap = document.getElementById('table-wrap');
  const ctrlOk = d.control.every(c => c.ok);
  const spread = d.spread || [];
  const byPer = (a, b) => (a.period + a.supplier).localeCompare(b.period + b.supplier, 'uk');
  const newRows = d.rows.filter(r => r.kind === 'new').sort(byPer);
  const confl = d.rows.filter(r => r.kind === 'conflict').sort(byPer);
  const opNew = d.openings.filter(o => o.state !== 'same');
  const badge = document.getElementById('count-badge');
  if (badge) badge.textContent = `нужно решить ${confl.length} · новых ${newRows.length} · разнесено вручную ${spread.length} · совпадает ${d.same}`;

  let h = `<div style="padding:10px 16px;background:var(--surface2);border-radius:8px;margin:12px 0;font-size:13px">
    <b>📄 ${escHtml(d.file)}</b>
    <span style="margin-left:12px">${ctrlOk ? '<span style="color:var(--green)">✓ итоги «Общая сумма» сходятся</span>'
      : d.control.filter(c => !c.ok).map(c => `<span style="color:var(--red)">✗ ${escHtml(c.label)} ${fmt(c.total)} ≠ ${fmt(c.rows)}</span>`).join(' ')}</span>
    ${d.repeat ? `<div style="color:var(--orange);margin-top:6px">⚠ Этот же файл уже загружали ${escHtml((d.repeat.applied_at || '').slice(0, 16).replace('T', ' '))} (${escHtml(d.repeat.applied_by || '')}).</div>` : ''}
    ${!ctrlOk ? `<div style="color:var(--red);margin-top:6px;font-weight:600">Суммы строк не сходятся с «Общая сумма» — запись запрещена. Проверьте файл.</div>` : ''}
    ${d.unmapped.length ? `<div style="color:var(--red);margin-top:6px">Не записываются — имени нет в маппинге: ${d.unmapped.map(escHtml).join(', ')}.</div>` : ''}
  </div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px">
    ${impTile(confl.length, 'Нужно решить', confl.length ? 'var(--red)' : 'var(--green)', 'Excel ≠ админка, итог за месяцы тоже не сходится')}
    ${impTile(newRows.length, 'Новые', '#60a5fa', 'в админке пусто — отмечены к записи')}
    ${impTile(spread.length, 'Разнесено вручную', '#94a3b8', 'по месяцам разное, итог сходится — ничего не делать')}
    ${impTile(d.same, 'Совпадает', 'var(--green)', 'уже есть в админке')}
  </div>`;

  if (!newRows.length && !confl.length && !opNew.length) {
    h += `<div class="loading" style="color:var(--green)">✓ Записывать нечего — всё из файла уже есть в админке.</div>`;
  }
  if (confl.length) {
    h += impTable(`<span style="color:var(--red)">Нужно решить (${confl.length})</span> — в админке другая сумма. ` +
      `<span style="font-weight:400;color:var(--text2)">Галочка = заменить суммой из Excel (прежняя сохранится). Без галочки = оставить админку.</span>`,
      ['Взять из Excel', 'Ячейка', 'Поставщик', 'Период', 'В админке', 'В Excel', 'Разница', 'Примечание в Excel'],
      confl.map(r => `<tr>
        <td style="text-align:center"><input type="checkbox" class="imp-chk" data-kind="conflict" data-cell="${escHtml(r.cell)}" ${impChecked('conflict', r.cell, false) ? 'checked' : ''} onchange="impToggle(this)"></td>
        <td>${escHtml(r.cell)}</td>
        <td>${escHtml(r.supplier)}</td>
        <td>${escHtml(r.period)}</td>
        <td style="text-align:right">${fmt(r.previous)}</td>
        <td style="text-align:right">${fmt(r.amount)}</td>
        <td style="text-align:right;color:${r.amount - r.previous < 0 ? 'var(--red)' : 'var(--green)'}">${(r.amount - r.previous > 0 ? '+' : '') + fmt(r.amount - r.previous)}</td>
        <td style="font-size:12px;color:var(--text2)">${escHtml(r.note || '')}</td>
      </tr>`).join(''));
  }
  if (newRows.length) {
    h += impTable(`Новые (${newRows.length}) — в админке пусто`,
      ['Записать', 'Ячейка', 'Строка Excel → поставщик', 'Период', 'Сумма', 'Дата оплаты', 'Замечания'],
      newRows.map(r => `<tr>
        <td style="text-align:center"><input type="checkbox" class="imp-chk" data-kind="new" data-cell="${escHtml(r.cell)}" ${impChecked('new', r.cell, r.default) ? 'checked' : ''} onchange="impToggle(this)"></td>
        <td>${escHtml(r.cell)}</td>
        <td>${escHtml(r.excel_name)} → <b>${escHtml(r.supplier)}</b></td>
        <td>${escHtml(r.period)}</td>
        <td style="text-align:right">${fmt(r.amount)}</td>
        <td>${escHtml(r.payment_date || '')}</td>
        <td style="color:var(--orange);font-size:12px">${escHtml([...(r.flags || []), ...(r.extra || []).map(x => 'отдельно: ' + x)].join('; '))}</td>
      </tr>`).join(''));
  }
  if (spread.length) {
    h += `<details style="margin-top:18px"><summary style="cursor:pointer;font-size:14px;font-weight:600;color:var(--text2)">
      Разнесено вручную (${spread.length}) — поставщик платил за несколько месяцев сразу, в админке разнесено по месяцам. Итог совпадает, делать ничего не нужно ▸</summary>` +
      impTable('', ['Поставщик', 'Месяцы', 'По месяцам: Excel / админка', 'Итог Excel', 'Итог админки', 'Примечание в Excel'],
        spread.map(b => `<tr>
          <td>${escHtml(b.supplier)}</td>
          <td>${escHtml(b.months[0])} … ${escHtml(b.months[b.months.length - 1])}</td>
          <td style="font-size:12px">${b.cells.map(c => `${escHtml(c.period.slice(5))}: ${c.excel == null ? '—' : fmt(c.excel)} / ${c.admin == null ? '—' : fmt(c.admin)}`).join('<br>')}</td>
          <td style="text-align:right">${fmt(b.excel_total)}</td>
          <td style="text-align:right;color:var(--green)">${fmt(b.admin_total)}</td>
          <td style="font-size:12px;color:var(--text2)">${escHtml((b.notes || []).join(' · '))}</td>
        </tr>`).join('')) + `</details>`;
  }
  if (d.openings.length) {
    const opChecked = d._openings === undefined ? opNew.length > 0 : d._openings;
    h += `<h3 style="margin:18px 0 8px;font-size:14px">Бонусы на открытие магазинов: ${d.openings.length}, новых/изменённых ${opNew.length}</h3>
      <label style="font-size:13px"><input type="checkbox" id="imp-openings" ${opChecked && opNew.length ? 'checked' : ''} ${opNew.length ? '' : 'disabled'}
        onchange="importDraft._openings = this.checked; updateImportTotals()">
      записать новые/изменённые (${opNew.map(o => escHtml(o.excel_name) + ' · ' + escHtml(o.store) + ' ' + fmt(o.amount)).join('; ') || '—'})</label>`;
  }
  if (d.manual.length || d.skipped.length) {
    h += `<div style="color:var(--text2);font-size:12px;margin-top:12px">` +
      (d.manual.length ? `Составные строки (месяцы сверяются группой): ${d.manual.map(escHtml).join(', ')}. ` : '') +
      (d.skipped.length ? `Не ретро по маппингу: ${d.skipped.length}.` : '') + `</div>`;
  }
  h += `<div style="position:sticky;bottom:0;background:var(--surface);border-top:1px solid var(--border);padding:12px 0;margin-top:16px;display:flex;gap:12px;align-items:center">
      <span id="imp-total" style="font-size:13px"></span>
      <button class="btn btn-green" id="imp-apply" onclick="applyImportDraft()">Записать отмеченные</button>
      <button class="btn btn-ghost" onclick="cancelImportDraft()">Отменить черновик</button>
      <span id="imp-status" style="font-size:12px;color:var(--text2)"></span>
    </div>`;
  wrap.innerHTML = h;
  updateImportTotals();
}


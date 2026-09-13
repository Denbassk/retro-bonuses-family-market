// ── Позиционный отчёт по SKU: читает готовый output\sku_coverage_2026.csv (tools\sku_coverage.py) ──
// Три представления: сводка поставщик x месяц, позиции одной пары, топ-50 по «недосчитано».
const SKU_KINDS = ['вне правил', 'сырьё', 'исключён правилом'];
const SKU_HINT = {
  'в правиле': 'посчитано',
  'вне правил': 'приход есть, правила нет',
  'сырьё': 'исключено расчётом как сырьё',
  'исключён правилом': 'баркод в excluded_sku_barcodes',
  'покрыт правилом другого поставщика': 'общий алиас: ретро посчитано у соседа, оценка не делается',
  'нет активных правил в месяце': 'в этом месяце у поставщика нет ни одного правила',
  'база не от приходов': 'оплаты / порции / покрытие ТТ - приход не база',
};

function skuFlagBadge(a) {
  const out = [];
  if (a.flagged) out.push('<span title="за месяц есть недогруз или задвоение документов" style="color:var(--red)">⚠ данные</span>');
  if (a.truth) out.push('<span title="январь-июнь: пересчёт запрещён, цифры справочные" style="color:#a78bfa">TRUTH_UNTIL</span>');
  return out.join(' ');
}

function skuCounts(n) {
  return Object.entries(n || {}).sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `<span title="${escHtml(SKU_HINT[k] || '')}">${escHtml(k)} ${v}</span>`).join(' · ');
}

function skuTable(pairs, note) {
  if (!pairs.length) return '';
  const sum = k => pairs.reduce((s, a) => s + (a.under[k] || 0), 0);
  return `<div style="font-size:12px;color:var(--text2);margin:10px 0 4px">${note}
      — итого: вне правил <b>${fmt(sum('вне правил'))}</b> ₴ · сырьё <b>${fmt(sum('сырьё'))}</b> ₴ ·
      исключено правилом <b>${fmt(sum('исключён правилом'))}</b> ₴ (не суммируются: причины разные)</div>
    <table><thead><tr>
      <th>Месяц</th><th>Поставщик</th><th style="text-align:right">База</th><th style="text-align:right">Ретро посчитано</th>
      <th style="text-align:right">Вне правил</th><th style="text-align:right">Сырьё</th><th style="text-align:right">Исключён правилом</th>
      <th>Позиции</th><th>Отметки</th></tr></thead><tbody>` +
    pairs.map(a => `<tr class="editable" style="cursor:pointer;${a.flagged ? 'background:rgba(248,113,113,0.06)' : ''}"
        onclick="skuPair('${encodeURIComponent(a.supplier)}','${a.per}')" title="Открыть позиции">
      <td>${escHtml(a.per)}</td><td>${escHtml(a.supplier)}</td>
      <td style="text-align:right">${fmt(a.base)}</td>
      <td style="text-align:right;color:var(--green)">${fmt(a.retro)}</td>
      <td style="text-align:right">${a.under['вне правил'] ? fmt(a.under['вне правил']) : ''}</td>
      <td style="text-align:right">${a.under['сырьё'] ? fmt(a.under['сырьё']) : ''}</td>
      <td style="text-align:right">${a.under['исключён правилом'] ? fmt(a.under['исключён правилом']) : ''}</td>
      <td style="font-size:11px;color:var(--text2)">${skuCounts(a.n)}</td>
      <td style="font-size:11px">${skuFlagBadge(a)}</td></tr>`).join('') + '</tbody></table>';
}

async function showSkuCoverage() {
  const wrap = document.getElementById('table-wrap');
  wrap.innerHTML = '<div class="loading">Читаю позиционный отчёт…</div>';
  let d, t;
  try {
    d = await apiFetch('/api/sku-coverage?view=summary');
    if (!d.ok) { wrap.innerHTML = `<div class="loading" style="color:var(--orange)">${escHtml(d.error)}</div>`; return; }
    t = await apiFetch('/api/sku-coverage?view=top');
  } catch (e) { wrap.innerHTML = `<div class="loading" style="color:var(--red)">${escHtml(e.message)}</div>`; return; }

  const work = d.pairs.filter(a => !a.truth), truth = d.pairs.filter(a => a.truth);
  const badge = document.getElementById('count-badge');
  if (badge) badge.textContent = `пар ${d.pairs.length} · рабочих ${work.length} · справочных ${truth.length}`;
  let h = `<div style="padding:10px 16px;background:var(--surface2);border-radius:8px;margin:12px 0;font-size:13px">
    <b>📦 Позиции: что попало в ретро, а что нет</b> — клик по строке открывает позиции этой пары.
    <div style="margin-top:4px">«Недосчитано» — оценка ретро по непокрытому приходу: <b>вне правил</b>, <b>сырьё</b> и
    <b>исключён правилом</b> показаны раздельно, потому что решения по ним разные. По статусу
    «покрыт правилом другого поставщика» (общий алиас) оценка не делается — там ретро уже посчитано у соседа.</div>
    <div style="margin-top:4px;color:var(--text2)">отчёт ${escHtml(d.file)} от
      ${escHtml((d.updated || '').slice(0, 16).replace('T', ' '))} — обновляется командой
      <code>python tools\\sku_coverage.py</code></div></div>`;

  if (t && t.ok && t.rows.length) {
    h += `<details open style="margin-top:8px"><summary style="cursor:pointer;font-size:14px;font-weight:600">
        Топ-50 по «недосчитано» — только пары без проблем с данными ▾</summary>` +
      impTable('', ['Месяц', 'Поставщик', 'Баркод', 'Наименование', 'Что не так', 'Приход', 'Недосчитано'],
        t.rows.map(r => `<tr>
          <td>${escHtml(r.per)}${r.truth ? ' <span style="color:#a78bfa;font-size:10px">справочно</span>' : ''}</td>
          <td>${escHtml(r.supplier)}</td><td>${escHtml(r.bc)}</td><td>${escHtml(r.name || '')}</td>
          <td title="${escHtml(SKU_HINT[r.status.split(';')[0]] || '')}">${escHtml(r.status)}</td>
          <td style="text-align:right">${fmt(r.inc)}</td>
          <td style="text-align:right;color:var(--orange)">${fmt(r.under)}</td></tr>`).join('')) + '</details>';
  }
  h += `<h3 style="margin:18px 0 4px;font-size:14px">Рабочие месяцы (июль и позже)</h3>` +
       skuTable(work, 'Эти цифры рабочие') +
       `<h3 style="margin:22px 0 4px;font-size:14px;color:#a78bfa">Январь–июнь: TRUTH_UNTIL, справочно</h3>
        <div style="font-size:12px;color:var(--text2)">Пересчёт этих месяцев запрещён: истина — сохранённый расчёт.
        Суммы ниже с рабочими месяцами не складывать, это материал для правил и разговора с поставщиком.</div>` +
       skuTable(truth, 'Справочно');
  wrap.innerHTML = h;
}

async function skuPair(supplierEnc, per) {
  const supplier = decodeURIComponent(supplierEnc);
  const wrap = document.getElementById('table-wrap');
  wrap.innerHTML = '<div class="loading">Загружаю позиции…</div>';
  let d;
  try { d = await apiFetch(`/api/sku-coverage?view=pair&supplier=${encodeURIComponent(supplier)}&month=${per}`); }
  catch (e) { wrap.innerHTML = `<div class="loading" style="color:var(--red)">${escHtml(e.message)}</div>`; return; }
  if (!d.ok) { wrap.innerHTML = `<div class="loading" style="color:var(--orange)">${escHtml(d.error)}</div>`; return; }
  const truth = per <= d.truth_until;
  let h = `<div style="padding:10px 16px;background:var(--surface2);border-radius:8px;margin:12px 0;font-size:13px">
    <button class="btn btn-ghost" style="font-size:12px;padding:3px 10px" onclick="showSkuCoverage()">← к сводке</button>
    <b style="margin-left:10px">${escHtml(supplier)} · ${escHtml(per)}</b>
    <span style="color:var(--text2)"> позиций ${d.total}${d.rows.length < d.total ? `, показаны первые ${d.rows.length}` : ''}</span>
    ${truth ? '<div style="color:#a78bfa;margin-top:4px">TRUTH_UNTIL: январь–июнь не пересчитываем, цифры справочные</div>' : ''}
    ${d.flags ? `<div style="color:var(--red);margin-top:4px">⚠ отметки месяца: ${escHtml(d.flags)} — «недосчитано» по этой паре под вопросом</div>` : ''}
  </div>`;
  h += `<table><thead><tr><th>Баркод</th><th>Наименование</th><th>Бренд</th><th>Что со SKU</th><th>Правило</th>
      <th style="text-align:right">Кол-во</th><th style="text-align:right">Приход</th><th style="text-align:right">Возвраты</th>
      <th style="text-align:right">База</th><th style="text-align:right">Ретро</th><th style="text-align:right">Недосчитано</th>
      </tr></thead><tbody>` +
    d.rows.map(r => `<tr>
      <td>${escHtml(r.bc)}</td><td>${escHtml(r.name || '')}</td><td>${escHtml(r.brand || '')}</td>
      <td title="${escHtml(SKU_HINT[r.status.split(';')[0]] || '')}">${escHtml(r.status)}</td>
      <td style="font-size:11px;color:var(--text2)">${escHtml(r.rule || '')}${r.rate ? ' · ' + escHtml(r.rate) + '%' : ''}</td>
      <td style="text-align:right">${escHtml(r.qty || '')}</td>
      <td style="text-align:right">${fmt(r.inc)}</td>
      <td style="text-align:right">${r.ret ? fmt(r.ret) : ''}</td>
      <td style="text-align:right">${fmt(r.base)}</td>
      <td style="text-align:right;color:var(--green)">${r.retro ? fmt(r.retro) : ''}</td>
      <td style="text-align:right;color:var(--orange)">${r.under ? fmt(r.under) : ''}</td></tr>`).join('') + '</tbody></table>';
  wrap.innerHTML = h;
}


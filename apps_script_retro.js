/**
 * Apps Script для Google Sheet «Ретро-бонусы Family Market 2026»
 *
 * Функции:
 * 1. Обновить Сводку — тянет retro_calculation_details из Supabase, строит pivot ПО БРЕНДАМ
 * 2. Детализация — по выбранному поставщику и месяцу показывает разбивку
 *
 * Установка:
 * 1. Открой Google Sheet → Расширения → Apps Script
 * 2. Вставь этот код в Code.gs
 * 3. Добавь Script Properties:
 *    SUPABASE_URL = https://mcqljkyllkziqsuhuxqd.supabase.co
 *    SUPABASE_KEY = (anon key или service key)
 * 4. Сохрани и обнови страницу — появится меню «⚡ Ретро»
 */

// ─── Конфигурация ───────────────────────────────────────────────────────────
function getConfig() {
  const props = PropertiesService.getScriptProperties();
  return {
    url: props.getProperty('SUPABASE_URL'),
    key: props.getProperty('SUPABASE_KEY'),
  };
}

// ─── Supabase REST ──────────────────────────────────────────────────────────
function supabaseGet(table, params) {
  const cfg = getConfig();
  const url = cfg.url + '/rest/v1/' + table + '?' + (params || '');
  const resp = UrlFetchApp.fetch(url, {
    headers: {
      'apikey': cfg.key,
      'Authorization': 'Bearer ' + cfg.key,
    },
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() !== 200) {
    throw new Error('Supabase error: ' + resp.getContentText());
  }
  return JSON.parse(resp.getContentText());
}

// ─── Меню ───────────────────────────────────────────────────────────────────
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('⚡ Ретро')
    .addItem('🔄 Обновить сводку', 'updateSummary')
    .addItem('🔍 Детализация…', 'showDetailDialog')
    .addSeparator()
    .addItem('💰 Сверка начислено/оплачено', 'updateReconciliation')
    .addToUi();
}

// ═══════════════════════════════════════════════════════════════════════════
//  СВОДКА — бренды с одинаковым % объединены в один рядок
//  Формат: «Поставщик (Бренд1, Бренд2)» | % | Форма | месяцы | ИТОГО
//  Отдельные строки только при разных % внутри одного поставщика
// ═══════════════════════════════════════════════════════════════════════════
function updateSummary() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ws = ss.getSheetByName('Сводка');
  if (!ws) {
    ws = ss.insertSheet('Сводка', 0);
  }

  SpreadsheetApp.getActive().toast('Загрузка данных из Supabase...', '⚡ Ретро', 30);

  // 1. Загружаем данные из Supabase
  var calcs = supabaseGet('retro_calculations',
    'select=id,period_label,supplier_id&order=period_label,supplier_id');
  var details = supabaseGet('retro_calculation_details',
    'select=calculation_id,supplier_brand_id,applied_percent,retro_amount,retro_amount_vat,bonus_form,amount_purchased,amount_returned,amount_net,notes' +
    '&order=calculation_id');
  var suppliers = supabaseGet('suppliers', 'select=id,name');
  var brands = supabaseGet('supplier_brands', 'select=id,name,supplier_id');

  var supMap = {};
  suppliers.forEach(function(s) { supMap[s.id] = s.name; });
  var brandMap = {};
  brands.forEach(function(b) { brandMap[b.id] = b; });
  var calcMap = {};
  calcs.forEach(function(c) { calcMap[c.id] = c; });

  // 2. Собираем brand-level pivot
  var months = [];
  var monthSet = {};
  var brandRows = {};

  details.forEach(function(d) {
    var calc = calcMap[d.calculation_id];
    if (!calc) return;
    var month = calc.period_label;
    var supId = calc.supplier_id;
    var brandId = d.supplier_brand_id;
    var supName = supMap[supId] || supId;
    var brand = brandMap[brandId];

    // Определяем, фикс-бонус ли это
    var pctNum = Number(d.applied_percent) || 0;
    var isBonus = !brandId && (
      (d.notes || '').toLowerCase().indexOf('бонус') >= 0 ||
      (pctNum === 0 && Number(d.amount_purchased) === 0 && Number(d.retro_amount) !== 0)
    );

    var brandName;
    if (brand) {
      brandName = brand.name;
    } else if (isBonus) {
      brandName = '💰 Месячный бонус';
    } else {
      brandName = '—';
    }

    if (!monthSet[month]) {
      monthSet[month] = true;
      months.push(month);
    }

    var key = supId + '|' + (brandId || (isBonus ? 'bonus' : 'none'));
    if (!brandRows[key]) {
      brandRows[key] = {
        supId: supId,
        supName: supName,
        brandName: brandName,
        pct: pctNum,
        form: d.bonus_form || 'price_correction',
        isBonus: isBonus,
        months: {}
      };
    }
    var rk = brandRows[key];
    rk.months[month] = (rk.months[month] || 0) + Number(d.retro_amount || 0);
    if (pctNum) rk.pct = pctNum;
  });

  months.sort();

  // 2.5. Объединение родителя «Авангард Дистрибуції» с его направлениями
  // Все строки родителя (бонусы) переносятся под зонтик первого найденного направления.
  var UMBRELLA_RULES = [
    { parent: 'Авангард Дистрибуції', childPrefix: 'Авангард Дистрибуції (' }
  ];

  UMBRELLA_RULES.forEach(function(rule) {
    // Найдём supId родителя и supId всех детей
    var parentSupId = null;
    var childSupIds = [];
    Object.keys(brandRows).forEach(function(key) {
      var br = brandRows[key];
      if (br.supName === rule.parent) {
        parentSupId = br.supId;
      } else if (br.supName.indexOf(rule.childPrefix) === 0) {
        if (childSupIds.indexOf(br.supId) < 0) childSupIds.push(br.supId);
      }
    });

    if (!parentSupId || childSupIds.length === 0) return;

    // Берём первого ребёнка как «носителя» зонтика
    var umbrellaSupId = childSupIds[0];

    // Все строки родителя перевешиваем на umbrellaSupId
    // и переименовываем supName на короткое «Авангард Дистрибуції»
    var keysToMove = [];
    Object.keys(brandRows).forEach(function(key) {
      if (brandRows[key].supId === parentSupId) {
        keysToMove.push(key);
      }
    });

    keysToMove.forEach(function(oldKey) {
      var br = brandRows[oldKey];
      br.supId = umbrellaSupId;
      // Новый ключ под умbrellaSupId
      var newKey = umbrellaSupId + '|' + (oldKey.split('|')[1] || 'bonus');
      // Защита от коллизии: если ключ уже занят — мерджим
      if (brandRows[newKey] && newKey !== oldKey) {
        var existing = brandRows[newKey];
        months.forEach(function(m) {
          existing.months[m] = (existing.months[m] || 0) + (br.months[m] || 0);
        });
      } else {
        brandRows[newKey] = br;
      }
      if (newKey !== oldKey) delete brandRows[oldKey];
    });

    // Перепишем supName всех записей под umbrellaSupId на короткое имя зонтика
    Object.keys(brandRows).forEach(function(key) {
      if (brandRows[key].supId === umbrellaSupId) {
        brandRows[key].supName = rule.parent;  // «Авангард Дистрибуції» (без скобок)
      }
    });
  });

  // 3. Группируем бренды по поставщику, затем по (%, форма, isBonus)
  var supGroups = {};

  Object.keys(brandRows).forEach(function(key) {
    var br = brandRows[key];
    if (!supGroups[br.supId]) {
      supGroups[br.supId] = { supName: br.supName, groups: {} };
    }
    var groupKey = br.pct + '|' + br.form + '|' + (br.isBonus ? 'bonus' : 'rule');
    if (!supGroups[br.supId].groups[groupKey]) {
      supGroups[br.supId].groups[groupKey] = {
        pct: br.pct,
        form: br.form,
        isBonus: br.isBonus,
        brandNames: [],
        months: {}
      };
    }
    var g = supGroups[br.supId].groups[groupKey];
    if (br.brandName && br.brandName !== '—') {
      g.brandNames.push(br.brandName);
    }
    months.forEach(function(m) {
      g.months[m] = (g.months[m] || 0) + (br.months[m] || 0);
    });
  });

  // 4. Сортируем поставщиков по имени
  var supIds = Object.keys(supGroups).sort(function(a, b) {
    return supGroups[a].supName.localeCompare(supGroups[b].supName);
  });

  // 5. Строим таблицу
  ws.clear();
  ws.clearFormats();

  var header = ['Поставщик', '%', 'Форма'];
  months.forEach(function(m) { header.push(m); });
  header.push('ИТОГО');
  var numCols = header.length;

  var data = [header];

  supIds.forEach(function(supId) {
    var sg = supGroups[supId];
    var groupKeys = Object.keys(sg.groups).sort(function(a, b) {
      // Бонусы вниз, остальные по % убыванию
      var ga = sg.groups[a], gb = sg.groups[b];
      if (ga.isBonus && !gb.isBonus) return 1;
      if (!ga.isBonus && gb.isBonus) return -1;
      return Number(gb.pct) - Number(ga.pct);
    });
    var groupCount = groupKeys.length;

    groupKeys.forEach(function(gk) {
      var g = sg.groups[gk];
      var sortedBrands = g.brandNames.slice().sort();

      var displayName;
if (g.isBonus) {
  displayName = sg.supName + ' — 💰 Месячный бонус';
} else if (sortedBrands.length === 0) {
  displayName = sg.supName;
} else {
  // Извлекаем содержимое скобок из имени поставщика, если оно есть
  var supBrackets = '';
  var bracketMatch = sg.supName.match(/\(([^)]+)\)\s*$/);
  if (bracketMatch) {
    supBrackets = bracketMatch[1].toLowerCase();
  }

  // Фильтруем бренды, которые уже упомянуты в скобках поставщика
  var newBrands = sortedBrands.filter(function(b) {
    return supBrackets.indexOf(b.toLowerCase()) < 0;
  });

  if (newBrands.length === 0) {
    // Все бренды уже в имени поставщика — показываем просто поставщика
    displayName = sg.supName;
  } else if (newBrands.length === 1 && groupCount === 1) {
    displayName = sg.supName + ' (' + newBrands[0] + ')';
  } else {
    displayName = sg.supName + ' (' + newBrands.join(', ') + ')';
  }
}

      var formLabel = g.form === 'marketing_service' ? 'Маркетинг' : 'Ф2 (нал)';
      var pctLabel = g.isBonus ? 'фикс' : (Number(g.pct) + '%');
      var row = [displayName, pctLabel, formLabel];
      var total = 0;
      months.forEach(function(m) {
        var val = g.months[m] || 0;
        row.push(Math.round(val * 100) / 100);
        total += val;
      });
      row.push(Math.round(total * 100) / 100);
      data.push(row);
    });
  });

  // Пустая строка + ИТОГО
  var emptyRow = [];
  for (var e = 0; e < numCols; e++) emptyRow.push('');
  data.push(emptyRow);

  var totalsRow = ['ИТОГО', '', ''];
  var grandTotal = 0;
  months.forEach(function(m) {
    var colTotal = 0;
    supIds.forEach(function(supId) {
      var gks = Object.keys(supGroups[supId].groups);
      gks.forEach(function(gk) {
        colTotal += (supGroups[supId].groups[gk].months[m] || 0);
      });
    });
    totalsRow.push(Math.round(colTotal * 100) / 100);
    grandTotal += colTotal;
  });
  totalsRow.push(Math.round(grandTotal * 100) / 100);
  data.push(totalsRow);

  if (data.length < 2) {
    SpreadsheetApp.getUi().alert('Нет данных для отображения');
    return;
  }
  ws.getRange(1, 1, data.length, numCols).setValues(data);

  // ═══ ФОРМАТИРОВАНИЕ ═══
  var lastDataRow = data.length;
  var dataRows = lastDataRow - 1;

  ws.getRange(1, 1, lastDataRow, numCols).setFontFamily('Arial').setFontSize(10);

  // Заголовок
  ws.getRange(1, 1, 1, numCols)
    .setBackground('#1B4F72')
    .setFontColor('#FFFFFF')
    .setFontWeight('bold')
    .setFontSize(11)
    .setHorizontalAlignment('center')
    .setVerticalAlignment('middle');
  ws.setRowHeight(1, 36);

  ws.setFrozenRows(1);
  ws.setFrozenColumns(1);

  // Столбец поставщиков — жирный (batch)
  var supFontWeights = [];
  for (var r = 2; r <= lastDataRow; r++) {
    var cellVal = ws.getRange(r, 1).getValue();
    supFontWeights.push([cellVal && String(cellVal).length > 0 ? 'bold' : 'normal']);
  }
  if (supFontWeights.length > 0) {
    ws.getRange(2, 1, supFontWeights.length, 1).setFontWeights(supFontWeights);
  }

  if (dataRows > 0) {
    ws.getRange(2, 2, dataRows, 2).setHorizontalAlignment('center');
  }

  if (months.length > 0 && dataRows > 0) {
    ws.getRange(2, 4, dataRows, months.length + 1)
      .setNumberFormat('#,##0.00')
      .setHorizontalAlignment('center');
  }

  ws.getRange(1, numCols, lastDataRow, 1).setFontWeight('bold');

  // Строка ИТОГО
  ws.getRange(lastDataRow, 1, 1, numCols)
    .setBackground('#1B4F72')
    .setFontColor('#FFFFFF')
    .setFontWeight('bold')
    .setFontSize(11)
    .setHorizontalAlignment('center');

  // ═══ Batch backgrounds (зебра + Маркетинг + Бонус) ═══
  // Собираем фоны для строк 2..lastDataRow-1
  var bgGrid = [];
  var fgGrid = [];
  var rowIdx = 0;

  // Сначала получим значения столбца "Поставщик" и "Форма" одним батчем
  var dataRange = ws.getRange(2, 1, lastDataRow - 2, numCols).getValues();

  for (var i = 0; i < dataRange.length; i++) {
    var rowVals = dataRange[i];
    var isEmpty = !rowVals[0];
    var isBonusRow = String(rowVals[0]).indexOf('💰') >= 0;
    var formVal = rowVals[2];

    var bgRow = [];
    var fgRow = [];
    for (var c = 0; c < numCols; c++) {
      bgRow.push(null);
      fgRow.push(null);
    }

    if (!isEmpty) {
      // Зебра
      if (rowIdx % 2 === 1) {
        for (var c = 0; c < numCols; c++) bgRow[c] = '#F2F5FA';
      }
      // Бонусная строка — отдельный фон
      if (isBonusRow) {
        for (var c = 0; c < numCols; c++) {
          bgRow[c] = '#FFF8E1';
          fgRow[c] = '#7A5C00';
        }
      }
      // Маркетинг — подсветка столбца Форма
      if (formVal === 'Маркетинг') {
        bgRow[2] = '#FFF3CD';
        fgRow[2] = '#856404';
      }
      rowIdx++;
    }
    bgGrid.push(bgRow);
    fgGrid.push(fgRow);
  }

  if (bgGrid.length > 0) {
    ws.getRange(2, 1, bgGrid.length, numCols).setBackgrounds(bgGrid);
    ws.getRange(2, 1, fgGrid.length, numCols).setFontColors(fgGrid);
  }

  // Границы
  ws.getRange(1, 1, lastDataRow, numCols)
    .setBorder(true, true, true, true, true, true, '#B0B0B0', SpreadsheetApp.BorderStyle.SOLID);
  ws.getRange(1, 1, 1, numCols)
    .setBorder(null, null, true, null, null, null, '#0D3B66', SpreadsheetApp.BorderStyle.SOLID_MEDIUM);
  ws.getRange(lastDataRow, 1, 1, numCols)
    .setBorder(true, null, true, null, null, null, '#0D3B66', SpreadsheetApp.BorderStyle.SOLID_MEDIUM);

  // Ширины
  ws.setColumnWidth(1, 380);
  ws.setColumnWidth(2, 65);
  ws.setColumnWidth(3, 100);
  for (var c = 4; c <= numCols; c++) {
    ws.setColumnWidth(c, 120);
  }

  // Статистика
  var rowCount = 0;
  supIds.forEach(function(supId) {
    rowCount += Object.keys(supGroups[supId].groups).length;
  });

  SpreadsheetApp.getActive().toast('Готово!', '⚡ Ретро', 3);
  SpreadsheetApp.getUi().alert(
    'Готово! ' + rowCount + ' строк, ' + supIds.length + ' поставщиков, ' +
    months.length + ' месяцев.\n' +
    'Общий итог: ' + grandTotal.toLocaleString('uk-UA', {minimumFractionDigits: 2}) + ' грн'
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  ДЕТАЛИЗАЦИЯ
// ═══════════════════════════════════════════════════════════════════════════
function showDetailDialog() {
  var calcs = supabaseGet('retro_calculations',
    'select=period_label,supplier_id&order=period_label');
  var suppliers = supabaseGet('suppliers', 'select=id,name&is_retro_active=eq.true&order=name');

  var months = [];
  var monthSet = {};
  calcs.forEach(function(c) {
    if (!monthSet[c.period_label]) {
      monthSet[c.period_label] = true;
      months.push(c.period_label);
    }
  });
  months.sort();

  var html = '<style>'
    + 'body { font-family: Arial, sans-serif; padding: 16px; }'
    + 'select, button { font-size: 14px; padding: 8px; margin: 6px 0; width: 100%; }'
    + 'button { background: #1B4F72; color: white; border: none; cursor: pointer; border-radius: 4px; }'
    + 'button:hover { background: #0D3B66; }'
    + 'button:disabled { background: #888; }'
    + 'label { font-weight: bold; display: block; margin-top: 12px; }'
    + '#status { margin-top: 12px; color: #555; font-size: 13px; }'
    + '</style>';

  html += '<label>Поставщик:</label>';
  html += '<select id="supplier">';
  suppliers.forEach(function(s) {
    html += '<option value="' + s.id + '">' + s.name + '</option>';
  });
  html += '</select>';

  html += '<label>Месяц:</label>';
  html += '<select id="month">';
  months.forEach(function(m) {
    html += '<option value="' + m + '">' + m + '</option>';
  });
  html += '</select>';

  html += '<br><button id="btn" onclick="runDetail()">Показать детализацию</button>';
  html += '<div id="status"></div>';
  html += '<script>'
    + 'function runDetail() {'
    + '  var sup = document.getElementById("supplier").value;'
    + '  var month = document.getElementById("month").value;'
    + '  document.getElementById("btn").disabled = true;'
    + '  document.getElementById("status").innerText = "Загрузка...";'
    + '  google.script.run'
    + '    .withSuccessHandler(function() {'
    + '      document.getElementById("status").innerText = "✅ Готово!";'
    + '      document.getElementById("btn").disabled = false;'
    + '    })'
    + '    .withFailureHandler(function(err) {'
    + '      document.getElementById("status").innerText = "Ошибка: " + err;'
    + '      document.getElementById("btn").disabled = false;'
    + '    })'
    + '    .loadDetail(sup, month);'
    + '}'
    + '</script>';

  SpreadsheetApp.getUi().showSidebar(
    HtmlService.createHtmlOutput(html).setTitle('🔍 Детализация ретро')
  );
}

function loadDetail(supplierId, month) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ws = ss.getSheetByName('Детализация');
  if (!ws) {
    ws = ss.insertSheet('Детализация');
  }

  var calcs = supabaseGet('retro_calculations',
    'supplier_id=eq.' + encodeURIComponent(supplierId) +
    '&period_label=eq.' + encodeURIComponent(month) +
    '&select=id,total_retro,notes');

  if (!calcs || calcs.length === 0) {
    SpreadsheetApp.getUi().alert('Нет данных за ' + month);
    return;
  }

  var calcId = calcs[0].id;
  var calcNotes = calcs[0].notes || '';

  var details = supabaseGet('retro_calculation_details',
    'calculation_id=eq.' + encodeURIComponent(calcId) +
    '&select=id,supplier_brand_id,applied_percent,amount_purchased,amount_returned,amount_net,retro_amount,retro_amount_vat,bonus_form,notes');

  // SKU-детализация
  var skuRows = supabaseGet('retro_calculation_sku_details',
    'calculation_id=eq.' + encodeURIComponent(calcId) +
    '&select=detail_id,supplier_brand_id,barcode,product_name,quantity,amount_purchased,amount_returned,amount_net,applied_percent,retro_amount' +
    '&order=detail_id,retro_amount.desc');

  var skuByDetail = {};
  skuRows.forEach(function(s) {
    var k = s.detail_id;
    if (!skuByDetail[k]) skuByDetail[k] = [];
    skuByDetail[k].push(s);
  });

  var brands = supabaseGet('supplier_brands', 'select=id,name');
  var brandMap = {};
  brands.forEach(function(b) { brandMap[b.id] = b.name; });

  var sups = supabaseGet('suppliers', 'id=eq.' + encodeURIComponent(supplierId) + '&select=name');
  var supName = sups.length > 0 ? sups[0].name : supplierId;

  ws.clear();
  ws.clearFormats();

  var title = supName + ' — ' + month;
  var header = ['Бренд / Штрих-код / Продукт', '%', 'Кол-во', 'Приход', 'Возврат', 'База', 'Ретро', 'Форма'];

  ws.getRange(1, 1).setValue(title);
  ws.getRange(1, 1, 1, header.length).merge()
    .setFontSize(14).setFontWeight('bold')
    .setHorizontalAlignment('center')
    .setBackground('#1B4F72').setFontColor('#FFFFFF');
  ws.setRowHeight(1, 40);

  // Рядок 2 — примітка розрахунку (якщо є)
  var headerRow = 3;
  var dataStartRow = 4;
  if (calcNotes) {
    ws.getRange(2, 1, 1, header.length).merge()
      .setValue('⚠️ ' + calcNotes)
      .setBackground('#FFF3CD').setFontColor('#856404')
      .setFontStyle('italic').setFontSize(10)
      .setWrap(true).setVerticalAlignment('middle');
    ws.setRowHeight(2, 50);
    headerRow = 3;
    dataStartRow = 4;
  } else {
    ws.setRowHeight(2, 6); // тонкий відступ якщо немає примітки
  }

  ws.getRange(headerRow, 1, 1, header.length).setValues([header]);
  ws.getRange(headerRow, 1, 1, header.length)
    .setBackground('#2E75B6').setFontColor('#FFFFFF')
    .setFontWeight('bold').setHorizontalAlignment('center')
    .setFontFamily('Arial').setFontSize(10);

  var data = [];
  var rowFormats = [];   // на каждую строку: {type: 'brand'|'sku'|'bonus'}
  var totalRetro = 0;

  details.forEach(function(d) {
    var pctNum = Number(d.applied_percent) || 0;
    var isBonus = !d.supplier_brand_id && (
      (d.notes || '').toLowerCase().indexOf('бонус') >= 0 ||
      (pctNum === 0 && Number(d.amount_purchased) === 0 && Number(d.retro_amount) !== 0)
    );

    var brandName;
    if (d.supplier_brand_id && brandMap[d.supplier_brand_id]) {
      brandName = brandMap[d.supplier_brand_id];
    } else if (isBonus) {
      brandName = '💰 Месячный бонус';
    } else {
      brandName = '—';
    }

    var bf = d.bonus_form || 'price_correction';
    var formLabel = bf === 'marketing_service' ? 'Маркетинг' : 'Ф2 (нал)';
    var pctLabel = isBonus ? 'фикс' : (pctNum + '%');

    // 1. Строка бренда (заголовок группы)
    data.push([
      brandName,
      pctLabel,
      '',  // qty
      Number(d.amount_purchased) || 0,
      Number(d.amount_returned) || 0,
      Number(d.amount_net) || 0,
      Number(d.retro_amount) || 0,
      formLabel
    ]);
    rowFormats.push(isBonus ? 'bonus' : 'brand');
    totalRetro += Number(d.retro_amount) || 0;

    // 2. Строки SKU под этим брендом
    var skus = skuByDetail[d.id] || [];
    skus.forEach(function(s) {
      var prodLabel = '   ' + (s.barcode || '') + '  ' + (s.product_name || '');
      data.push([
        prodLabel,
        (Number(s.applied_percent) || 0) + '%',
        Number(s.quantity) || 0,
        Number(s.amount_purchased) || 0,
        Number(s.amount_returned) || 0,
        Number(s.amount_net) || 0,
        Number(s.retro_amount) || 0,
        ''
      ]);
      rowFormats.push('sku');
    });
  });

  if (data.length > 0) {
    ws.getRange(dataStartRow, 1, data.length, header.length).setValues(data);
  }

  // ИТОГО — додаємо акції з calcNotes якщо є
  var akciiAmount = 0;
  if (calcNotes) {
    var akciiMatch = calcNotes.match(/([\d\s]+[,.][\d]+)\s*грн/);
    if (akciiMatch) {
      akciiAmount = parseFloat(akciiMatch[1].replace(/\s/g, '').replace(',', '.')) || 0;
    }
  }
  var totRow = dataStartRow + data.length + 1;
  var grandTotal = Math.round((totalRetro + akciiAmount) * 100) / 100;
  ws.getRange(totRow, 1).setValue('ИТОГО');
  ws.getRange(totRow, 7).setValue(grandTotal);
  ws.getRange(totRow, 1, 1, header.length)
    .setBackground('#D6E4F0').setFontWeight('bold')
    .setNumberFormat('#,##0.00');
  ws.getRange(totRow, 1).setNumberFormat('@');
  if (akciiAmount > 0) {
    ws.getRange(totRow, 7).setNote('Ретро: ' + Math.round(totalRetro * 100) / 100 + ' + Акції: ' + akciiAmount);
  }

  // Форматы
  if (data.length > 0) {
    var dataRange = ws.getRange(dataStartRow, 1, data.length, header.length);
    dataRange.setFontFamily('Arial').setFontSize(10).setVerticalAlignment('middle');

    ws.getRange(dataStartRow, 1, data.length, 2).setHorizontalAlignment('left');
    ws.getRange(dataStartRow, 3, data.length, 1).setNumberFormat('#,##0.##').setHorizontalAlignment('center');
    ws.getRange(dataStartRow, 4, data.length, 4).setNumberFormat('#,##0.00').setHorizontalAlignment('right');
    ws.getRange(dataStartRow, 8, data.length, 1).setHorizontalAlignment('center');

    // Раскраска по типу строки
    var bgGrid = [];
    var fgGrid = [];
    var weights = [];
    for (var i = 0; i < data.length; i++) {
      var t = rowFormats[i];
      var bgRow = [];
      var fgRow = [];
      var wRow = [];
      for (var c = 0; c < header.length; c++) {
        bgRow.push(null);
        fgRow.push(null);
        wRow.push('normal');
      }

      if (t === 'brand') {
        // Жирный заголовок бренда, светло-синий фон
        for (var c = 0; c < header.length; c++) {
          bgRow[c] = '#E8F0F8';
          wRow[c] = 'bold';
        }
      } else if (t === 'bonus') {
        for (var c = 0; c < header.length; c++) {
          bgRow[c] = '#FFF8E1';
          fgRow[c] = '#7A5C00';
          wRow[c] = 'bold';
        }
      } else {
        // SKU — обычная строка, тёмно-серый текст
        for (var c = 0; c < header.length; c++) {
          fgRow[c] = '#5F6368';
        }
      }

      // Маркетинг — отдельная подсветка ячейки Форма
      if (data[i][7] === 'Маркетинг' && t !== 'bonus') {
        bgRow[7] = '#FFF3CD';
        fgRow[7] = '#856404';
      }

      bgGrid.push(bgRow);
      fgGrid.push(fgRow);
      weights.push(wRow);
    }
    dataRange.setBackgrounds(bgGrid);
    dataRange.setFontColors(fgGrid);
    dataRange.setFontWeights(weights);
  }

  // Границы
  if (data.length > 0) {
    ws.getRange(3, 1, data.length + 1, header.length)
      .setBorder(true, true, true, true, true, true, '#B0B0B0', SpreadsheetApp.BorderStyle.SOLID);
  }

  // Ширины
  ws.setColumnWidth(1, 380);   // бренд / штрих-код / название
  ws.setColumnWidth(2, 65);    // %
  ws.setColumnWidth(3, 80);    // кол-во
  ws.setColumnWidth(4, 110);   // приход
  ws.setColumnWidth(5, 100);   // возврат
  ws.setColumnWidth(6, 110);   // база
  ws.setColumnWidth(7, 110);   // ретро
  ws.setColumnWidth(8, 100);   // форма
  ws.setColumnWidth(9, 220);   // примечание

  ws.setFrozenRows(3);
  ss.setActiveSheet(ws);
}
/**
 * ============================================================================
 *   ЛИСТ «СВЕРКА» — Начислено vs Оплачено
 * ============================================================================
 */

function updateReconciliation() {
  var cfg = getConfig();
  SpreadsheetApp.getActive().toast('Загрузка данных…', '💰 Сверка', 30);

  // 1. Тянем данные из Supabase
  var calcs = supabaseGet('retro_calculations',
    'select=supplier_id,period_label,total_retro');
  var facts = supabaseGet('retro_payments_fact',
    'select=supplier_id,period_label,amount_paid,payment_date,doc_number,notes');
  var suppliers = supabaseGet('suppliers', 'select=id,name');

  // 2. Индексы
  var supMap = {};
  suppliers.forEach(function(s) { supMap[s.id] = s.name; });

  var calcMap = {};   // 'supId|period' → charged
  var factMap = {};   // 'supId|period' → {paid, date, doc, notes}
  var monthsSet = {};
  var supSet = {};

  calcs.forEach(function(c) {
    var key = c.supplier_id + '|' + c.period_label;
    calcMap[key] = (calcMap[key] || 0) + Number(c.total_retro || 0);
    monthsSet[c.period_label] = true;
    supSet[c.supplier_id] = true;
  });

  facts.forEach(function(f) {
    var key = f.supplier_id + '|' + f.period_label;
    factMap[key] = {
      paid: Number(f.amount_paid || 0),
      date: f.payment_date || '',
      doc: f.doc_number || '',
      notes: f.notes || ''
    };
    monthsSet[f.period_label] = true;
    supSet[f.supplier_id] = true;
  });

  var months = Object.keys(monthsSet).sort();
  var supIds = Object.keys(supSet);

  // 3. Фильтруем поставщиков: только с начислениями > 0 за весь период
  supIds = supIds.filter(function(sid) {
    return months.some(function(m) {
      return (calcMap[sid + '|' + m] || 0) > 0;
    });
  });

  // Сортировка по алфавиту
  supIds.sort(function(a, b) {
    return (supMap[a] || '').localeCompare(supMap[b] || '', 'uk');
  });

  // 4. Готовим лист «Сверка»
  var ss = SpreadsheetApp.getActive();
  var sheet = ss.getSheetByName('Сверка');
  if (!sheet) {
    sheet = ss.insertSheet('Сверка');
  } else {
    sheet.clear();
    sheet.clearConditionalFormatRules();
  }

  // 5. Заголовок
  var header = ['Поставщик'];
  months.forEach(function(m) {
    header.push(m + ' Нач');
    header.push(m + ' Опл');
    header.push(m + ' Δ%');
  });
  header.push('ИТОГО Нач');
  header.push('ИТОГО Опл');
  header.push('ИТОГО Δ ₴');
  header.push('Δ %');
  header.push('Статус');

  var numCols = header.length;

  // 6. Данные
  var rows = [];
  var bgGrid = [];

  supIds.forEach(function(sid, idx) {
    var row = [supMap[sid] || '???'];
    var bgRow = [null];
    var totalCharged = 0;
    var totalPaid = 0;

    months.forEach(function(m) {
      var charged = calcMap[sid + '|' + m] || 0;
      var fact = factMap[sid + '|' + m];
      var paid = fact ? fact.paid : 0;
      totalCharged += charged;
      totalPaid += paid;

      row.push(charged > 0 ? charged : '');
      row.push(paid > 0 ? paid : '');

      // Δ%
      if (charged === 0) {
      row.push(null);  // null вместо '' — Google Sheets не применяет формат к пустой ячейке
      bgRow.push(null);
      bgRow.push(null);
      bgRow.push(paid > 0 ? '#E9D5FF' : null);
      } else {
        var pct = (paid - charged) / charged;  // ДОЛЯ, не процент — formatNumber сам умножит на 100
        row.push(pct);
        var st = cellStatus(charged, paid);
        bgRow.push(null);             // Нач — без фона
        bgRow.push(st.bg);            // Опл — цветной
        bgRow.push(st.bg);            // Δ% — цветной
      }
    });

    // Итоги
    row.push(totalCharged);
    row.push(totalPaid);
    var diffRub = totalPaid - totalCharged;
    row.push(diffRub);
    var totalPct = totalCharged > 0 ? (diffRub / totalCharged) : (totalPaid > 0 ? null : 0);
    row.push(totalPct);

    var rowStatus = cellStatus(totalCharged, totalPaid);
    row.push(rowStatus.label);

    // Фоны итогов
    bgRow.push('#F2F5FA');         // ИТОГО Нач
    bgRow.push('#F2F5FA');         // ИТОГО Опл
    bgRow.push(rowStatus.bg);      // Δ ₴
    bgRow.push(rowStatus.bg);      // Δ %
    bgRow.push(rowStatus.bg);      // Статус

    rows.push(row);
    bgGrid.push(bgRow);
  });

  // 7. Строка ИТОГО снизу
  if (rows.length > 0) {
    var totalRow = ['ИТОГО'];
    var totalBg = ['#1F4E79'];
    var grandCharged = 0;
    var grandPaid = 0;

    months.forEach(function(m, i) {
      var sumC = 0, sumP = 0;
      supIds.forEach(function(sid) {
        sumC += calcMap[sid + '|' + m] || 0;
        var f = factMap[sid + '|' + m];
        if (f) sumP += f.paid;
      });
      grandCharged += sumC;
      grandPaid += sumP;
      totalRow.push(sumC);
      totalRow.push(sumP);
      totalRow.push(sumC > 0 ? ((sumP - sumC) / sumC) : null);
      totalBg.push('#1F4E79');
      totalBg.push('#1F4E79');
      totalBg.push('#1F4E79');
    });

    totalRow.push(grandCharged);
    totalRow.push(grandPaid);
    totalRow.push(grandPaid - grandCharged);
    totalRow.push(grandCharged > 0 ? ((grandPaid - grandCharged) / grandCharged) : null);
    totalRow.push(cellStatus(grandCharged, grandPaid).label);
    for (var k = 0; k < 5; k++) totalBg.push('#1F4E79');

    rows.push(totalRow);
    bgGrid.push(totalBg);
  }

  // 8. Запись
  sheet.getRange(1, 1, 1, numCols).setValues([header]);
  if (rows.length > 0) {
    sheet.getRange(2, 1, rows.length, numCols).setValues(rows);
    sheet.getRange(2, 1, rows.length, numCols).setBackgrounds(bgGrid);
  }

  // 9. Форматирование заголовка
  var headerRange = sheet.getRange(1, 1, 1, numCols);
  headerRange.setBackground('#1F4E79')
             .setFontColor('#FFFFFF')
             .setFontWeight('bold')
             .setHorizontalAlignment('center')
             .setVerticalAlignment('middle');
  sheet.setRowHeight(1, 36);

  // 10. Форматы чисел
  var lastRow = sheet.getLastRow();
  if (lastRow >= 2) {
    // Нач/Опл/ИТОГО — формат денег
    months.forEach(function(_, i) {
      var colNach = 2 + i * 3;
      var colOpl = 3 + i * 3;
      var colPct = 4 + i * 3;
      sheet.getRange(2, colNach, lastRow - 1, 1).setNumberFormat('#,##0.00');
      sheet.getRange(2, colOpl, lastRow - 1, 1).setNumberFormat('#,##0.00');
      sheet.getRange(2, colPct, lastRow - 1, 1).setNumberFormat('+0.0%;-0.0%;0%');
    });
    var totalNachCol = 2 + months.length * 3;
    sheet.getRange(2, totalNachCol, lastRow - 1, 3).setNumberFormat('#,##0.00');
    sheet.getRange(2, totalNachCol + 3, lastRow - 1, 1).setNumberFormat('+0.0%;-0.0%;0%');
  }

  // 11. Цвет белый для строки ИТОГО (последняя строка)
  if (rows.length > 0) {
    sheet.getRange(lastRow, 1, 1, numCols)
         .setFontColor('#FFFFFF')
         .setFontWeight('bold');
  }

  // 12. Ширины и фиксация
  sheet.setColumnWidth(1, 240);
  for (var c = 2; c <= numCols; c++) sheet.setColumnWidth(c, 95);
  sheet.setColumnWidth(numCols, 100);    // Статус
  sheet.setColumnWidth(numCols - 1, 70); // Δ %
  sheet.setFrozenRows(1);
  sheet.setFrozenColumns(1);

  // 13. Активируем лист
  sheet.activate();
  SpreadsheetApp.getActive().toast(
    'Готово: ' + supIds.length + ' поставщиков, ' + months.length + ' месяцев',
    '✅ Сверка', 5);
}

/**
 * Возвращает {bg, label} по статусу оплаты.
 */
function cellStatus(charged, paid) {
  if (charged === 0 && paid === 0) {
    return { bg: null, label: '' };
  }
  if (charged === 0 && paid > 0) {
    return { bg: '#E9D5FF', label: '🟣 Без начисл.' };
  }
  if (paid === 0) {
    return { bg: '#FDE2E2', label: '🔴 Не оплачено' };
  }
  var pct = paid / charged * 100;
  if (pct < 50) return { bg: '#FDE2E2', label: '🔴 ' + Math.round(pct) + '%' };
  if (pct < 98) return { bg: '#FFF4D1', label: '🟡 ' + Math.round(pct) + '%' };
  if (pct <= 102) return { bg: '#D9F5DD', label: '🟢 OK' };
  return { bg: '#E9D5FF', label: '🟣 +' + Math.round(pct - 100) + '%' };
}

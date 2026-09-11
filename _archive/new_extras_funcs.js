// ── Доплаты «не ретро» (retro_adjustments.payment_mode) ──
//   in_payment - деньги в «Оплачено» (кубы, компенсации акций) или договорённость: + к «Начислено» (строка расчёта)
//   separate   - заплачено отдельно (ДМП Славутич): только запись, «Начислено» и сверка не меняются
function adjMode(a) { return a.payment_mode || 'in_payment'; }

async function addExtraPayment(supId, period, calcId) {
  const amount = parseFloat(document.getElementById('f_extra_amount').value);
  const notes = (document.getElementById('f_extra_notes').value || '').trim();
  const modeEl = document.querySelector('input[name="f_extra_mode"]:checked');
  const mode = modeEl ? modeEl.value : 'in_payment';
  if (isNaN(amount) || amount === 0) { toast('Введіть суму (мінус = вирахування)', true); return; }
  if (!notes) { toast('Введіть примітку', true); return; }
  const what = mode === 'separate'
    ? `Записать ОТДЕЛЬНУЮ выплату ${fmt(amount)} ₴ за ${period} «${notes}»?\n\n«Начислено» и «Оплачено» не меняются — это только отметка, что деньги пришли вне ретро.`
    : `Добавить ${amount > 0 ? 'доплату' : 'вычет'} ${fmt(amount)} ₴ за ${period} «${notes}»?\n\nОна входит в «Оплачено», поэтому прибавится к «Начислено».`;
  if (!confirm(what)) return;

  let brandId = null;
  if (calcId) {
    const { data: existingDetail } = await sb.from('retro_calculation_details')
      .select('supplier_brand_id').eq('calculation_id', calcId).limit(1);
    brandId = existingDetail && existingDetail.length ? existingDetail[0].supplier_brand_id : null;
  }
  const { data: { user } } = await sb.auth.getUser();
  const row = { supplier_id: supId, supplier_brand_id: brandId, period_label: period, amount: amount,
                bonus_form: 'price_correction', notes: notes, source: 'admin', created_by: user ? user.email : null };
  if (mode === 'separate') row.payment_mode = 'separate';   // in_payment = значение по умолчанию в БД
  const { data: adj, error: e0 } = await sb.from('retro_adjustments').insert(row).select('id').single();
  if (e0) {
    toast('Помилка: ' + e0.message + (mode === 'separate' ? ' (выполнен ли sql/2026-09-11_adjustments_payment_mode.sql?)' : ''), true);
    return;
  }

  if (mode === 'in_payment' && calcId) {
    const { error: e1 } = await sb.from('retro_calculation_details').insert({
      adjustment_id: adj.id, calculation_id: calcId, supplier_brand_id: brandId, applied_percent: 0,
      amount_purchased: 0, amount_returned: 0, amount_net: 0, retro_amount: amount, retro_amount_vat: amount,
      bonus_form: 'price_correction', notes: notes });
    if (e1) {
      await sb.from('retro_adjustments').delete().eq('id', adj.id);   // откат
      toast('Помилка: ' + e1.message, true);
      return;
    }
    const { data: calc } = await sb.from('retro_calculations').select('total_retro').eq('id', calcId).single();
    const newTotal = Math.round(((parseFloat(calc.total_retro) || 0) + amount) * 100) / 100;
    await sb.from('retro_calculations').update({ total_retro: newTotal }).eq('id', calcId);
  }
  toast(mode === 'separate' ? '✅ Записано как отдельная выплата' : '✅ Доплату додано');
  await loadReconciliation();
  openReconCellModal(supId, period);
}

async function deleteExtraPayment(adjId, supId, period) {
  const { data: adj, error: e0 } = await sb.from('retro_adjustments').select('*').eq('id', adjId).single();
  if (e0 || !adj) { toast('Помилка: ' + (e0 ? e0.message : 'не найдено'), true); return; }
  if (!confirm(`Удалить «${adj.notes}» ${fmt(parseFloat(adj.amount))} ₴?` +
               (adjMode(adj) === 'in_payment' ? '\n«Начислено» уменьшится на эту сумму.' : ''))) return;
  if (adjMode(adj) === 'in_payment') {
    const { data: dets } = await sb.from('retro_calculation_details')
      .select('id, calculation_id, retro_amount').eq('adjustment_id', adjId);
    for (const d of (dets || [])) {
      await sb.from('retro_calculation_details').delete().eq('id', d.id);
      const { data: calc } = await sb.from('retro_calculations').select('total_retro').eq('id', d.calculation_id).single();
      const newTotal = (parseFloat(calc.total_retro) || 0) - (parseFloat(d.retro_amount) || 0);
      await sb.from('retro_calculations').update({ total_retro: Math.round(newTotal * 100) / 100 }).eq('id', d.calculation_id);
    }
  }
  const { error } = await sb.from('retro_adjustments').delete().eq('id', adjId);
  if (error) { toast('Помилка: ' + error.message, true); return; }
  toast('✅ Видалено');
  await loadReconciliation();
  openReconCellModal(supId, period);
}


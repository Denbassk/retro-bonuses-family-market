  const adjs = (reconData.adjs || {})[supId + '|' + period] || [];
  const inPay = adjs.filter(a => adjMode(a) === 'in_payment');
  const separate = adjs.filter(a => adjMode(a) === 'separate');
  const sumOf = list => list.reduce((s, a) => s + (parseFloat(a.amount) || 0), 0);
  let extrasHtml = '';
  adjs.forEach(a => {
    const sep = adjMode(a) === 'separate';
    const amt = parseFloat(a.amount) || 0;
    extrasHtml += `<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;
      padding:4px 8px;background:${sep ? 'rgba(148,163,184,0.10)' : 'rgba(52,211,153,0.08)'};border-radius:4px;margin-bottom:3px;font-size:12px">
      <span style="color:var(--text2)">${escHtml(a.notes || '—')}
        <span style="font-size:10px;padding:1px 6px;border-radius:8px;margin-left:6px;border:1px solid ${sep ? '#94a3b8' : 'var(--green)'};color:${sep ? '#94a3b8' : 'var(--green)'}">
          ${sep ? 'отдельно, не в «Оплачено»' : 'в «Оплачено», + к начислению'}</span></span>
      <div style="display:flex;align-items:center;gap:8px">
        <span style="color:${amt < 0 ? 'var(--red)' : (sep ? 'var(--text2)' : 'var(--green)')};font-weight:600">${amt > 0 ? '+' : ''}${fmt(amt)} ₴</span>
        <button onclick="deleteExtraPayment('${a.id}', '${supId}', '${period}')"
          style="background:none;border:none;color:var(--red);cursor:pointer;font-size:14px;padding:0 2px;line-height:1"
          title="Видалити">✕</button>
      </div>
    </div>`;
  });
  const chargedNote = [
    inPay.length ? `в т.ч. доплаты ${fmt(sumOf(inPay))} ₴` : '',
    separate.length ? `отдельно (не в «Оплачено»): ${fmt(sumOf(separate))} ₴` : ''].filter(Boolean).join(' · ');


    <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--border)">
      <div style="font-size:13px;font-weight:600;margin-bottom:4px;color:var(--text)">➕ Не ретро: ДМП, кубы, компенсации акций</div>
      ${extrasHtml}
      <div style="display:flex;gap:8px;margin-top:6px">
        <input id="f_extra_amount" type="number" step="0.01" placeholder="Сума, грн" style="width:140px">
        <input id="f_extra_notes" placeholder="Примітка (напр. ДМП, куби)" style="flex:1">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;margin:8px 0;font-size:12px">
        <label style="display:flex;gap:6px;align-items:flex-start;cursor:pointer;margin:0">
          <input type="radio" name="f_extra_mode" value="in_payment" checked style="width:auto;margin-top:2px">
          <span><b>Входит в «Оплачено»</b> — деньги пришли одной суммой с ретро (кубы, компенсация акций). Прибавится к «Начислено».</span></label>
        <label style="display:flex;gap:6px;align-items:flex-start;cursor:pointer;margin:0">
          <input type="radio" name="f_extra_mode" value="separate" style="width:auto;margin-top:2px">
          <span><b>Заплачено отдельно</b> — в «Оплачено» не вносили (ДМП). Только отметка: «Начислено» и сверка не меняются.</span></label>
      </div>
      <button class="btn btn-ghost" onclick="addExtraPayment('${supId}', '${period}', ${calcId ? "'" + calcId + "'" : 'null'})"
        style="white-space:nowrap;border-color:var(--green);color:var(--green)">+ Додати</button>
    </div>

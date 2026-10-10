(() => {
  'use strict';
  let csrfToken = null;
  let draft = null;
  let preview = null;
  let submitKey = null;
  let pendingSubmission = null;
  let saving = false;
  let initializing = true;
  let exclusionTarget = null;
  const RESTORE_NOTE = '依本輪系統建議恢復訂購數量';

  const byId = (id) => document.getElementById(id);
  const bootstrapNode = byId('ordering-bootstrap');
  const bootstrap = bootstrapNode ? JSON.parse(bootstrapNode.textContent) : null;
  const storageKey = bootstrap ? `system2-ordering:${bootstrap.actor_id}:${bootstrap.store_id}` : null;

  function remember() {
    if (!storageKey) return;
    const items = [...document.querySelectorAll('.product-row')].map((row) => ({
      product_id: Number(row.dataset.productId),
      fields: Object.fromEntries(['final_qty', 'reason_code', 'reason', 'need_date', 'need_qty', 'arrangement']
        .map((name) => [name, row.querySelector(`[data-field="${name}"]`).value])),
      manual_ack: Boolean(row.querySelector('[data-field="manual_ack"]')?.checked),
    }));
    try { sessionStorage.setItem(storageKey, JSON.stringify({runId: bootstrap.run.run_id,
      draftId: draft?.id, draftVersion: draft?.version, items, pendingSubmission})); } catch (_) { /* Server-saved drafts remain available on the homepage. */ }
  }

  function restoreItems(items, raw = false) {
    for (const item of items || []) {
      const row = document.querySelector(`.product-row[data-product-id="${item.product_id}"]`);
      if (!row) continue;
      const values = raw ? item.fields : {final_qty: item.final_qty, reason_code: item.reason_code,
        reason: item.reason, need_date: item.special_need?.need_date, need_qty: item.special_need?.need_qty,
        arrangement: item.special_need?.arrangement};
      for (const [name, value] of Object.entries(values || {})) {
        const field = row.querySelector(`[data-field="${name}"]`);
        if (field) field.value = value ?? '';
      }
      const manual = row.querySelector('[data-field="manual_ack"]');
      if (manual) manual.checked = raw ? item.manual_ack : item.manual_forecast_acknowledged;
    }
  }

  function lockUnknown(locked) {
    for (const id of ['submit-button', 'back-button', 'preview-button', 'save-button']) {
      if (byId(id)) byId(id).disabled = locked;
    }
    if (byId('recovery-panel')) byId('recovery-panel').hidden = !locked;
  }

  async function csrf() {
    if (!csrfToken) {
      const response = await fetch('/api/auth/csrf', {credentials: 'same-origin'});
      csrfToken = (await response.json()).csrf_token;
    }
    return csrfToken;
  }

  async function api(url, options = {}) {
    const method = options.method || 'GET';
    const headers = new Headers(options.headers || {});
    if (method !== 'GET') {
      headers.set('Content-Type', 'application/json');
      headers.set('X-CSRFToken', await csrf());
    }
    const response = await fetch(url, {...options, headers, credentials: 'same-origin'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error?.message || '操作失敗，請稍後再試。');
      error.code = data.error?.code;
      error.details = data.error?.details || {};
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function showError(target, error) {
    if (!target) return;
    target.textContent = error.message;
    target.hidden = false;
  }

  function activateStage(stage) {
    document.querySelectorAll('[data-stage-indicator]').forEach((node) => {
      node.classList.toggle('active', Number(node.dataset.stageIndicator) === stage);
    });
  }

  function itemPayload(row) {
    const field = (name) => row.querySelector(`[data-field="${name}"]`);
    const needDate = field('need_date').value;
    const needQty = field('need_qty').value;
    const arrangement = field('arrangement').value.trim();
    const reason = field('reason').value.trim();
    const special = needDate || needQty || arrangement ? {
      need_date: needDate || null,
      need_qty: needQty ? Number(needQty) : null,
      arrangement: arrangement || null,
      reason: reason || null,
    } : null;
    return {
      product_id: Number(row.dataset.productId),
      final_qty: Number(field('final_qty').value),
      reason_code: field('reason_code').value || null,
      reason: reason || null,
      special_need: special,
      manual_forecast_acknowledged: Boolean(field('manual_ack')?.checked),
    };
  }

  function validateRows() {
    let valid = true;
    document.querySelectorAll('.product-row').forEach((row) => {
      const qty = row.querySelector('[data-field="final_qty"]');
      const error = row.querySelector('[data-error-for="final_qty"]');
      const value = Number(qty.value);
      error.textContent = '';
      if (!qty.value.trim() || !Number.isInteger(value) || value < 0 || value > 1000000) {
        error.textContent = '請輸入 0 到 1,000,000 的整數件數。';
        valid = false;
      }
    });
    return valid;
  }

  function refreshRowState(row) {
    const excluded = row.querySelector('[data-field="final_qty"]').value.trim() === '0';
    row.classList.toggle('is-excluded', excluded);
    const state = row.querySelector('[data-item-state]');
    if (state) state.textContent = excluded ? '本次不訂 · 0件' : '';
  }

  function requestExclusion(row, fromPreview = false) {
    if (pendingSubmission || saving || initializing) return;
    exclusionTarget = {row, fromPreview};
    const name = row.querySelector('[data-product-name]').textContent;
    const quantity = row.querySelector('[data-field="final_qty"]').value;
    byId('exclude-description').innerHTML = `<strong>${escapeHtml(name)}</strong><div class="quantity-comparison"><span>目前數量<strong>${escapeHtml(quantity || '未填')} 件</strong></span><span>本次訂購<strong>0 件</strong></span></div><p>此商品將不列入本次正式訂單。</p>`;
    const reason = row.querySelector('[data-field="reason"]').value;
    // Old drafts may already contain the automatically generated restore note.
    // It describes restoring a quantity, so it cannot describe excluding it.
    byId('exclude-note').value = reason.trim() === RESTORE_NOTE ? '' : reason;
    byId('exclude-dialog').showModal();
  }

  byId('exclude-cancel')?.addEventListener('click', () => byId('exclude-dialog').close());
  byId('exclude-dialog')?.addEventListener('close', () => { exclusionTarget = null; });
  byId('exclude-confirm')?.addEventListener('click', () => {
    if (!exclusionTarget || pendingSubmission || saving) return;
    const {row, fromPreview} = exclusionTarget;
    const note = byId('exclude-note').value.trim();
    if (fromPreview) returnToWorkbench();
    row.querySelector('[data-field="final_qty"]').value = '0';
    row.querySelector('[data-field="reason_code"]').value = 'skip';
    row.querySelector('[data-field="reason"]').value = note;
    row.querySelector('[data-error-for="final_qty"]').textContent = '';
    row.querySelector('[data-error-for="item"]').textContent = '';
    row.querySelector('[data-field="final_qty"]').dispatchEvent(new Event('input'));
    remember();
    byId('draft-status').textContent = '已記錄原因「本次不訂」，數量改為0；請儲存並預覽本單，重新確認。';
    byId('exclude-dialog').close();
    row.scrollIntoView({block: 'center'});
  });

  async function saveDraft() {
    if (!draft) {
      draft = await api('/api/order-drafts', {method: 'POST', body: JSON.stringify({
        store_id: bootstrap.store_id, run_id: bootstrap.run.run_id, cycle_id: bootstrap.run.cycle_id,
      })});
      remember();
    }
    draft = await api(`/api/order-drafts/${draft.id}`, {method: 'PATCH', body: JSON.stringify({
      expected_version: draft.version,
      items: [...document.querySelectorAll('.product-row')].map(itemPayload),
    })});
    remember();
    byId('draft-status').textContent = `草稿 #${draft.id} 已儲存，尚未送出`;
  }

  async function saveAndPreview(previewRequested = true) {
    if (pendingSubmission || saving || initializing) return;
    const globalError = byId('global-error');
    globalError.hidden = true;
    document.querySelectorAll('[data-error-for="item"]').forEach((node) => { node.textContent = ''; });
    if (!validateRows()) return;
    saving = true;
    const editingFields = [...document.querySelectorAll('.product-row input,.product-row select,.product-row textarea,.product-row button')]
      .map((field) => [field, field.disabled]);
    editingFields.forEach(([field]) => { field.disabled = true; });
    const button = byId('preview-button');
    button.disabled = true;
    if (byId('save-button')) byId('save-button').disabled = true;
    try {
      await saveDraft();
      if (!previewRequested) return;
      preview = await api(`/api/order-drafts/${draft.id}/preview`, {method: 'POST', body: JSON.stringify({
        expected_version: draft.version,
      })});
      submitKey = crypto.randomUUID();
      renderPreview(preview.snapshot);
      byId('stage-workbench').hidden = true;
      byId('stage-preview').hidden = false;
      activateStage(2);
      window.scrollTo({top: 0, behavior: 'smooth'});
    } catch (error) {
      showError(globalError, error);
      const problems = error.details?.items || (error.details?.product_id ?
        [{product_id: error.details.product_id, messages: [error.message]}] : []);
      let first = null;
      for (const problem of problems) {
        const row = document.querySelector(`.product-row[data-product-id="${problem.product_id}"]`);
        const fieldError = row?.querySelector('[data-error-for="item"]');
        if (fieldError) {
          fieldError.textContent = (problem.messages || []).join('；');
          row.hidden = false;
          first ||= row;
        }
      }
      first?.scrollIntoView({block: 'center', behavior: 'smooth'});
    } finally {
      saving = false;
      editingFields.forEach(([field, disabled]) => { field.disabled = disabled; });
      button.disabled = false;
      if (byId('save-button')) byId('save-button').disabled = false;
    }
  }

  function renderPreview(snapshot) {
    const positive = snapshot.items.filter((item) => item.final_qty > 0);
    const excluded = snapshot.items.filter((item) => item.final_qty === 0);
    const excludedPanel = byId('preview-excluded');
    if (excludedPanel) {
      excludedPanel.hidden = excluded.length === 0;
      const reasonLabels = {promotion: '促銷', local_demand: '在地需求', display: '陳列調整', reduce_stock: '降低庫存', skip: '本次不訂', other: '其他'};
      excludedPanel.innerHTML = `<strong>本次不訂（${excluded.length}品項）</strong><ul>${excluded.map((item) =>
        `<li>${escapeHtml(item.name)}：0件；調整原因：${escapeHtml(reasonLabels[item.reason_code] || '沿用系統建議0件')}${item.reason ? `；補充：${escapeHtml(item.reason)}` : ''}</li>`).join('')}</ul><p>以上商品不列入正式訂單，會保留於決策紀錄。</p>`;
    }
    if (byId('preview-total')) byId('preview-total').textContent = `${positive.length} 個品項，合計 ${positive.reduce((sum, item) => sum + item.final_qty, 0)} 件`;
    byId('preview-summary').innerHTML = positive.length ? positive.map((item) => `
      <article class="summary-card"><strong>${escapeHtml(item.name)}</strong>
      <div class="quantity-comparison"><span>系統建議<strong>${item.suggested_qty ?? '無法計算'}</strong></span><span>您訂購<strong>${item.final_qty} ${escapeHtml(item.unit)}</strong></span></div>
      <div class="source-summary"><span>待接單 ${item.sources.U}</span><span>已承諾／在途 ${item.sources.C}</span><span>風險量 ${item.sources.RISK}</span></div>
      ${item.reason ? `<p>調整理由：${escapeHtml(item.reason)}</p>` : ''}
      ${item.special_need ? `<p>需求日期：${escapeHtml(item.special_need.need_date)}；需求量：${item.special_need.need_qty} 件；安排：${escapeHtml(item.special_need.arrangement)}</p>` : ''}
      ${item.warnings.map((warning) => `<p>⚠ ${escapeHtml(warning.message)}</p>`).join('')}</article>`).join('')
      : '<div class="empty-state"><strong>本次無需補貨</strong><p>不會送出空白補貨單。</p></div>';
    const important = snapshot.items.filter((item) => item.important_codes.length);
    byId('exception-toolbar').hidden = important.length === 0;
    byId('exception-list').innerHTML = important.map((item) => `
      <fieldset class="warning-card" data-exception-product="${item.product_id}"><legend>${escapeHtml(item.name)}：重要例外</legend>
      <ul>${item.warnings.filter((warning) => warning.level === 'important').map((warning) => `<li>${escapeHtml(warning.message)}</li>`).join('')}</ul>
      <label>處理方式 <select data-exception="handling"><option value="">請選擇</option><option value="keep_and_contact">維持本次訂量並聯絡統家</option><option value="adjusted">已調整本次訂量</option><option value="special_arrangement">已確認存放／交付安排</option><option value="exclude">排除此品項</option></select></label>
      <label>補充說明（沿用已填理由，可再補充） <input data-exception="reason" maxlength="500" value="${escapeHtml(item.reason || '').replaceAll('"', '&quot;')}"></label>
      <label class="check-row"><input data-exception="ack" type="checkbox"><span>我確認此特殊需求、數量與收貨安排正確，要求以本次輸入送出。</span></label>
      </fieldset>`).join('');
    document.querySelectorAll('[data-exception-product]').forEach((node) => {
      node.querySelectorAll('select,input').forEach((field) => field.addEventListener('change', () => {
        if (field.dataset.exception === 'handling' && field.value === 'exclude') {
          const row = document.querySelector(`.product-row[data-product-id="${node.dataset.exceptionProduct}"]`);
          field.value = field.dataset.previousHandling || '';
          requestExclusion(row, true);
          return;
        }
        if (field.dataset.exception === 'handling') field.dataset.previousHandling = field.value;
        updateExceptionCount();
      }));
    });
    updateExceptionCount();
    byId('order-ack').checked = false;
  }

  function updateExceptionCount() {
    const cards = [...document.querySelectorAll('[data-exception-product]')];
    let pending = 0;
    cards.forEach((card) => {
      const resolved = card.querySelector('[data-exception="ack"]').checked &&
        Boolean(card.querySelector('[data-exception="handling"]').value);
      card.classList.toggle('resolved', resolved);
      if (!resolved) pending += 1;
      if (byId('exception-filter')?.getAttribute('aria-pressed') === 'true') card.hidden = resolved;
    });
    if (byId('exception-count')) byId('exception-count').textContent = String(pending);
  }

  function returnToWorkbench() {
    if (pendingSubmission) return;
    byId('stage-preview').hidden = true;
    byId('stage-workbench').hidden = false;
    preview = null;
    submitKey = null;
    activateStage(1);
  }

  function exceptionPayload() {
    return [...document.querySelectorAll('[data-exception-product]')].map((node) => ({
      product_id: Number(node.dataset.exceptionProduct),
      warning_version: '1',
      handling: node.querySelector('[data-exception="handling"]').value,
      reason: node.querySelector('[data-exception="reason"]').value || null,
      acknowledged: node.querySelector('[data-exception="ack"]').checked,
    }));
  }

  async function submit() {
    if (pendingSubmission) return;
    const target = byId('submit-error');
    target.hidden = true;
    const button = byId('submit-button');
    button.disabled = true;
    const body = {
      draft_version: draft.version,
      confirmation_token: preview.confirmation_token,
      order_acknowledged: byId('order-ack').checked,
      exception_acknowledgements: exceptionPayload(),
    };
    pendingSubmission = {key: submitKey, draftId: draft.id, body, snapshot: preview.snapshot};
    remember();
    lockUnknown(true);
    await sendOriginal();
  }

  async function sendOriginal() {
    const target = byId('submit-error');
    const request = pendingSubmission;
    if (!request) return;
    try {
      const result = await api(`/api/order-drafts/${request.draftId}/submit`, {method: 'POST',
        headers: {'Idempotency-Key': request.key}, body: JSON.stringify(request.body)});
      showResult(result);
    } catch (error) {
      if (!error.status) {
        byId('recovery-message').textContent = '連線中斷，尚未確認結果。恢復連線後查詢，或重試原本的送出。';
        lockUnknown(true);
      } else {
        showError(target, error);
        pendingSubmission = null;
        remember();
        lockUnknown(false);
      }
    } finally {
      if (!pendingSubmission) lockUnknown(false);
    }
  }

  async function recover() {
    const target = byId('submit-error');
    try {
      const result = await api(`/api/submissions/${encodeURIComponent(pendingSubmission.key)}?store_id=${bootstrap.store_id}`);
      showResult(result);
    } catch (error) {
      byId('recovery-message').textContent = error.status === 404 ?
        '目前查無結果。請按「重試原本的送出」，仍使用同一請求，不會另建新單。' :
        '目前無法查詢，請恢復連線後再試。已保留原本的送出內容。';
    }
  }

  function showResult(result) {
    pendingSubmission = null;
    try { sessionStorage.removeItem(storageKey); } catch (_) { }
    lockUnknown(false);
    byId('stage-preview').hidden = true;
    byId('stage-result').hidden = false;
    byId('result-content').innerHTML = `<p>✅ 補貨單已確認送出。</p><dl class="definition-grid"><dt>訂單編號</dt><dd>${escapeHtml(result.number)}</dd><dt>狀態</dt><dd>已送出</dd></dl><p><a href="/store/orders/${result.order_id}?store_id=${bootstrap.store_id}">查看訂單明細</a> · <a href="/store/ordering?store_id=${bootstrap.store_id}">開始另一張補貨單</a></p>`;
    activateStage(3);
    window.scrollTo({top: 0, behavior: 'smooth'});
  }

  function escapeHtml(value) {
    const node = document.createElement('span');
    node.textContent = String(value ?? '');
    return node.innerHTML;
  }

  const introButton = byId('intro-submit');
  if (introButton) introButton.addEventListener('click', async () => {
    const errorNode = byId('intro-error');
    errorNode.textContent = '';
    introButton.disabled = true;
    try {
      await api('/api/ordering/acknowledgement', {method: 'POST', body: JSON.stringify({
        acknowledged: byId('intro-ack').checked,
      })});
      location.reload();
    } catch (error) {
      errorNode.textContent = error.message;
    } finally {
      introButton.disabled = false;
    }
  });

  byId('product-search')?.addEventListener('input', (event) => {
    const query = event.target.value.trim().toLocaleLowerCase('zh-Hant');
    document.querySelectorAll('.product-row').forEach((row) => {
      row.hidden = !row.dataset.search.toLocaleLowerCase('zh-Hant').includes(query);
    });
  });
  document.querySelectorAll('[data-step]').forEach((button) => button.addEventListener('click', () => {
    const input = button.parentElement.querySelector('[data-field="final_qty"]');
    input.value = Math.max(0, Math.min(1000000, Number(input.value || 0) + Number(button.dataset.step)));
    input.dispatchEvent(new Event('input'));
  }));
  document.querySelectorAll('[data-item-action]').forEach((button) => button.addEventListener('click', () => {
    if (pendingSubmission || saving || initializing) return;
    const row = button.closest('.product-row');
    const exclude = button.dataset.itemAction === 'exclude';
    if (exclude) {
      requestExclusion(row);
      return;
    }
    if (row.dataset.suggested === '') return;
    const qty = row.querySelector('[data-field="final_qty"]');
    qty.value = row.dataset.suggested;
    row.querySelector('[data-field="reason_code"]').value = 'other';
    const reason = row.querySelector('[data-field="reason"]');
    if (!reason.value.trim()) reason.value = RESTORE_NOTE;
    row.querySelector('[data-error-for="final_qty"]').textContent = '';
    row.querySelector('[data-error-for="item"]').textContent = '';
    qty.dispatchEvent(new Event('input'));
    remember();
    byId('draft-status').textContent = '已恢復系統建議量；請重新儲存並預覽。';
  }));
  document.querySelectorAll('[data-field="final_qty"]').forEach((input) => input.addEventListener('input', () => {
    const row = input.closest('.product-row');
    const suggested = row.dataset.suggested === '' ? null : Number(row.dataset.suggested);
    row.querySelector('.comparison').textContent = suggested === Number(input.value) ? '' :
      `系統建議 ${suggested ?? '無法計算'} → 您訂購 ${input.value || 0}`;
    refreshRowState(row);
  }));
  byId('preview-button')?.addEventListener('click', () => saveAndPreview(true));
  byId('save-button')?.addEventListener('click', () => saveAndPreview(false));
  byId('back-button')?.addEventListener('click', returnToWorkbench);
  byId('submit-button')?.addEventListener('click', submit);
  byId('recover-button')?.addEventListener('click', recover);
  byId('retry-button')?.addEventListener('click', sendOriginal);
  document.querySelectorAll('.product-row input,.product-row select,.product-row textarea')
    .forEach((field) => { field.addEventListener('input', remember); field.addEventListener('change', remember); });

  async function initialize() {
    if (!bootstrap || !byId('stage-workbench')) return;
    let cached = null;
    try { cached = JSON.parse(sessionStorage.getItem(storageKey)); } catch (_) { }
    draft = bootstrap.resume_draft || null;
    let newerDraft = false;
    if (draft) restoreItems(draft.items);
    if (cached && (cached.runId === bootstrap.run.run_id || cached.pendingSubmission) &&
        (!draft || cached.draftId === draft.id)) {
      pendingSubmission = cached.pendingSubmission || null;
      if (!draft && cached.draftId) {
        try {
          const saved = await api(`/api/order-drafts/${cached.draftId}`);
          if (saved.status === 'DRAFT' || pendingSubmission) draft = saved;
        } catch (error) {
          if (error.status === 404 || error.status === 403) {
            sessionStorage.removeItem(storageKey);
            pendingSubmission = null;
          } else showError(byId('global-error'), error);
        }
      }
      if (draft && !pendingSubmission && cached.draftVersion !== draft.version) {
        restoreItems(draft.items);
        newerDraft = true;
        remember();
      } else if (cached.runId === bootstrap.run.run_id) {
        restoreItems(cached.items, true);
      }
      if (pendingSubmission) {
        renderPreview(pendingSubmission.snapshot);
        byId('stage-workbench').hidden = true;
        byId('stage-preview').hidden = false;
        activateStage(2);
        lockUnknown(true);
        await recover();
      }
    }
    if (draft && !pendingSubmission) byId('draft-status').textContent = newerDraft ?
      `已恢復草稿 #${draft.id} 最新儲存內容；原瀏覽器內容版本不同，請重新核對` :
      `已恢復草稿 #${draft.id}；請核對後重新預覽`;
  }
  for (const id of ['preview-button', 'save-button']) {
    if (byId(id)) byId(id).disabled = true;
  }
  initialize().finally(() => {
    initializing = false;
    document.querySelectorAll('.product-row').forEach(refreshRowState);
    if (!pendingSubmission) {
      for (const id of ['preview-button', 'save-button']) {
        if (byId(id)) byId(id).disabled = false;
      }
    }
  });
  byId('exception-filter')?.addEventListener('click', (event) => {
    const pressed = event.currentTarget.getAttribute('aria-pressed') !== 'true';
    event.currentTarget.setAttribute('aria-pressed', String(pressed));
    event.currentTarget.textContent = pressed ? '顯示全部例外' : '只看待處理';
    document.querySelectorAll('[data-exception-product]').forEach((card) => { card.hidden = false; });
    updateExceptionCount();
  });
})();

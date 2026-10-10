(() => {
  'use strict';
  let csrfToken = null;
  let draft = null;
  let preview = null;
  let submitKey = null;

  const byId = (id) => document.getElementById(id);
  const bootstrapNode = byId('ordering-bootstrap');
  const bootstrap = bootstrapNode ? JSON.parse(bootstrapNode.textContent) : null;

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
      manual_forecast_acknowledged: field('manual_ack').checked,
    };
  }

  function validateRows() {
    let valid = true;
    document.querySelectorAll('.product-row').forEach((row) => {
      const qty = row.querySelector('[data-field="final_qty"]');
      const error = row.querySelector('[data-error-for="final_qty"]');
      const value = Number(qty.value);
      error.textContent = '';
      if (!Number.isInteger(value) || value < 0 || value > 1000000) {
        error.textContent = '請輸入 0 到 1,000,000 的整數件數。';
        valid = false;
      }
    });
    return valid;
  }

  async function saveAndPreview() {
    const globalError = byId('global-error');
    globalError.hidden = true;
    if (!validateRows()) return;
    const button = byId('preview-button');
    button.disabled = true;
    try {
      if (!draft) {
        draft = await api('/api/order-drafts', {method: 'POST', body: JSON.stringify({
          store_id: bootstrap.store_id,
          run_id: bootstrap.run.run_id,
          cycle_id: bootstrap.run.cycle_id,
        })});
      }
      draft = await api(`/api/order-drafts/${draft.id}`, {method: 'PATCH', body: JSON.stringify({
        expected_version: draft.version,
        items: [...document.querySelectorAll('.product-row')].map(itemPayload),
      })});
      byId('draft-status').textContent = '草稿已儲存';
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
    } finally {
      button.disabled = false;
    }
  }

  function renderPreview(snapshot) {
    const positive = snapshot.items.filter((item) => item.final_qty > 0);
    byId('preview-summary').innerHTML = positive.length ? positive.map((item) => `
      <article class="summary-card"><strong>${escapeHtml(item.name)}</strong>
      <p>系統建議 ${item.suggested_qty ?? '無法計算'} → 您訂購 <strong>${item.final_qty} ${escapeHtml(item.unit)}</strong></p>
      <p>待接單 ${item.sources.U}；已承諾／在途 ${item.sources.C}；風險量 ${item.sources.RISK}</p>
      ${item.warnings.map((warning) => `<p>⚠ ${escapeHtml(warning.message)}</p>`).join('')}</article>`).join('')
      : '<div class="empty-state"><strong>本次無需補貨</strong><p>不會送出空白補貨單。</p></div>';
    const important = snapshot.items.filter((item) => item.important_codes.length);
    byId('exception-toolbar').hidden = important.length === 0;
    byId('exception-list').innerHTML = important.map((item) => `
      <fieldset class="warning-card" data-exception-product="${item.product_id}"><legend>${escapeHtml(item.name)}：重要例外</legend>
      <ul>${item.warnings.filter((warning) => warning.level === 'important').map((warning) => `<li>${escapeHtml(warning.message)}</li>`).join('')}</ul>
      <label>處理方式 <select data-exception="handling"><option value="">請選擇</option><option value="keep_and_contact">維持本次訂量並聯絡統家</option><option value="adjusted">已調整本次訂量</option><option value="special_arrangement">已確認存放／交付安排</option><option value="exclude">排除此品項</option></select></label>
      <label>補充說明 <input data-exception="reason" maxlength="500"></label>
      <label class="check-row"><input data-exception="ack" type="checkbox"> 我確認此特殊需求、數量與收貨安排正確，要求以本次輸入送出。</label>
      </fieldset>`).join('');
    document.querySelectorAll('[data-exception-product]').forEach((node) => {
      node.querySelectorAll('select,input').forEach((field) => field.addEventListener('change', updateExceptionCount));
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
    try {
      const result = await api(`/api/order-drafts/${draft.id}/submit`, {method: 'POST',
        headers: {'Idempotency-Key': submitKey}, body: JSON.stringify(body)});
      showResult(result);
    } catch (error) {
      if (!error.status) {
        target.hidden = false;
        target.innerHTML = '<div class="network-unknown"><strong>尚未確認送出結果</strong><p>請勿另建新單；系統正用相同冪等鍵查詢。</p><button id="recover-button" type="button">查詢送出結果</button></div>';
        byId('recover-button').addEventListener('click', recover);
      } else {
        showError(target, error);
      }
    } finally {
      button.disabled = false;
    }
  }

  async function recover() {
    const target = byId('submit-error');
    try {
      const result = await api(`/api/submissions/${encodeURIComponent(submitKey)}?store_id=${bootstrap.store_id}`);
      showResult(result);
    } catch (error) {
      showError(target, error);
    }
  }

  function showResult(result) {
    byId('stage-preview').hidden = true;
    byId('stage-result').hidden = false;
    byId('result-content').innerHTML = `<p>✅ 補貨單已確認送出。</p><dl class="definition-grid"><dt>訂單編號</dt><dd>${escapeHtml(result.number)}</dd><dt>狀態</dt><dd>已送出</dd></dl><p><a href="/store/orders/${result.order_id}?store_id=${bootstrap.store_id}">查看訂單明細</a></p>`;
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
  document.querySelectorAll('[data-field="final_qty"]').forEach((input) => input.addEventListener('input', () => {
    const row = input.closest('.product-row');
    const suggested = row.dataset.suggested === '' ? null : Number(row.dataset.suggested);
    row.querySelector('.comparison').textContent = suggested === Number(input.value) ? '' :
      `系統建議 ${suggested ?? '無法計算'} → 您訂購 ${input.value || 0}`;
  }));
  byId('preview-button')?.addEventListener('click', saveAndPreview);
  byId('back-button')?.addEventListener('click', () => {
    byId('stage-preview').hidden = true;
    byId('stage-workbench').hidden = false;
    preview = null;
    submitKey = null;
    activateStage(1);
  });
  byId('submit-button')?.addEventListener('click', submit);
  byId('exception-filter')?.addEventListener('click', (event) => {
    const pressed = event.currentTarget.getAttribute('aria-pressed') !== 'true';
    event.currentTarget.setAttribute('aria-pressed', String(pressed));
    event.currentTarget.textContent = pressed ? '顯示全部例外' : '只看待處理';
    document.querySelectorAll('[data-exception-product]').forEach((card) => { card.hidden = false; });
    updateExceptionCount();
  });
})();

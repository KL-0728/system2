'use strict';
(() => {
  const root = document.querySelector('#inventory-app');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const storeId = Number(root.dataset.storeId);
  const storageKey = 'b02:' + root.dataset.actorId + ':' + storeId;
  let status, csrf, preview, lastSales, lastCount, pending, busy = false;
  const formControls = () => [...$('sales-form').elements, ...$('count-form').elements];
  const say = (text, error = false) => {
    $('data-message').textContent = text;
    $('data-message').classList.toggle('error', error);
  };
  const persist = () => {
    try { if (pending) sessionStorage.setItem(storageKey, JSON.stringify(pending)); else sessionStorage.removeItem(storageKey); }
    catch { say('瀏覽器無法保存重試紀錄，提交結果不明時請保留此頁並用原請求重試。', true); }
  };
  const lock = () => {
    formControls().forEach(control => { control.disabled = busy || Boolean(pending); });
    $('refresh-status').disabled = busy || Boolean(pending);
    $('commit-sales').disabled = busy || Boolean(pending) || !preview?.valid;
    $('repeat-sales').disabled = busy || Boolean(pending);
    $('repeat-count').disabled = busy || Boolean(pending);
    $('retry-pending').disabled = busy;
    $('recovery').hidden = !pending;
  };
  const api = async (url, body) => {
    let response;
    try {
      response = await fetch(url, body ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(body) } : {});
    } catch { const error = new Error('連線中斷，提交結果尚未確認。'); error.unknown = Boolean(body); throw error; }
    let data;
    try { data = await response.json(); }
    catch { const error = new Error('未收到可核對的回應。'); error.unknown = Boolean(body); throw error; }
    if (!response.ok) {
      const error = new Error((data.error?.code || response.status) + '：' + (data.error?.message || '操作失敗'));
      error.unknown = Boolean(body) && response.status >= 500;
      throw error;
    }
    return data;
  };
  const localTime = value => new Date(value).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false });
  const number = id => {
    const value = $(id).value;
    if (!/^(0|[1-9][0-9]*)$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error('數量／批次 ID 須為整數');
    return Number(value);
  };
  const node = (tag, text) => { const element = document.createElement(tag); element.textContent = text; return element; };
  const selected = () => status?.items.find(item => item.product_id === Number($('count-product').value));
  const fillCount = () => {
    const item = selected();
    if (!item || pending) return;
    $('count-physical').value = item.count_physical_qty ?? item.last_physical_qty;
    $('count-unsellable').value = item.count_unsellable_qty ?? item.last_unsellable_qty;
    $('count-correction').checked = item.count_version !== null;
    $('count-version').textContent = '庫存版本 ' + item.inventory_version + '；本截止點盤點版本 ' + (item.count_version ?? '尚無');
  };
  const loadStatus = async () => {
    status = await api('/api/inventory/status?store_id=' + storeId);
    $('data-window').textContent = '本輪基準：' + localTime(status.baseline_at) + '；提交截止：' + localTime(status.deadline_at) + '（Asia/Taipei）';
    $('stock-items').replaceChildren();
    const previous = $('count-product').value;
    $('count-product').replaceChildren();
    for (const item of status.items) {
      const fragment = $('stock-card').content.cloneNode(true);
      const card = fragment.querySelector('article');
      card.dataset.sku = item.sku;
      card.classList.toggle('blocked', !item.usable);
      card.querySelector('[data-text="title"]').textContent = item.name + ' · ' + item.sku + ' · 箱入 ' + item.pack_size + '件';
      card.querySelector('[data-text="book"]').textContent = '帳面總量 ' + item.physical_book + '；不可販售 ' + item.unsellable_book + '；H ' + (item.h ?? '不可用');
      card.querySelector('[data-text="counted"]').textContent = '最近實盤 ' + item.last_physical_qty + '／不可售 ' + item.last_unsellable_qty + '（' + localTime(item.last_counted_at) + '）';
      card.querySelector('[data-text="sales"]').textContent = item.sales ? '本日銷售 ' + item.sales.sold_qty + '；' + (item.sales.applied_at ? '日常已入帳' : '僅歷史／未入帳') + '；批次 ID ' + item.sales.batch_id : '本日尚無銷售資料';
      card.querySelector('[data-text="integrity"]').textContent = item.usable ? '庫存完整，可用於補貨' : '阻擋新送單：' + item.warnings.map(w => w.message).join('；') + (item.missing_dates.length ? '；缺口日期 ' + item.missing_dates.join('、') : '');
      for (const task of item.reconciliations) card.querySelector('[data-text="tasks"]').append(node('li', '待對帳 #' + task.id + '：' + task.reason));
      $('stock-items').append(fragment);
      const option = node('option', item.sku + ' ' + item.name); option.value = item.product_id; $('count-product').append(option);
    }
    if ([...$('count-product').options].some(o => o.value === previous)) $('count-product').value = previous;
    // Display an explicit offset; the service still enforces the fixed 21:00 cutoff.
    $('count-cutoff').value = status.baseline_at.replace('13:00:00+00:00', '21:00:00+08:00');
    fillCount();
    $('batch-list').replaceChildren(...status.batches.map(batch => node('li', 'ID ' + batch.id + ' · ' + batch.source_batch_id + ' · ' + (batch.import_mode === 'historical' ? '歷史' : '日常') + (batch.replaces_batch_id ? ' · 取代 ID ' + batch.replaces_batch_id : ''))));
  };
  const invalidate = () => { preview = null; $('sales-preview').hidden = true; lock(); };
  const renderPreview = data => {
    $('sales-preview').hidden = false;
    $('sales-errors').replaceChildren(...data.errors.map(error => node('li', '第 ' + error.line + ' 列：' + error.code + ' · ' + error.message)));
    $('sales-impact').textContent = (data.import_mode === 'historical' ? '歷史模式：不扣目前庫存。' : '日常模式：只套用以下差額。') + (data.valid ? '整批驗證通過，尚未提交。' : '整批有錯誤，沒有匯入任何一列。');
    $('preview-rows').replaceChildren();
    for (const row of data.rows) {
      const card = node('article', ''); card.className = 'preview-row';
      card.append(node('strong', row.sku + ' · ' + row.business_date + ' · 銷售 ' + row.sold_qty + '件'));
      card.append(node('p', '區間：' + localTime(row.interval_start) + ' 至 ' + localTime(row.interval_end)));
      card.append(node('p', '帳面異動 ' + (row.stock_delta ?? '未通過驗證') + '件' + (row.reconciliation ? '；已被盤點涵蓋，建立待對帳，不回改庫存' : '') + (row.action === 'forecast_only' ? '；只更新預測來源' : '')));
      $('preview-rows').append(card);
    }
  };
  const submitOriginal = async record => {
    if (busy) return;
    busy = true; pending = record; persist(); lock();
    say('正在核對並提交，請稍候…');
    try {
      const result = await api(record.url, record.body);
      pending = null; persist(); lock();
      preview = null; $('sales-preview').hidden = true;
      let successMessage;
      if (record.kind === 'sales') {
        lastSales = record; $('repeat-sales').hidden = false; preview = null;
        $('commit-sales').disabled = true;
        successMessage = (result.replayed ? '原批次結果已確認（沒有再次入帳）' : '整批提交成功') + '；批次 ID ' + result.batch_id + '；' + result.count + '列；本批帳面差額合計 ' + result.stock_delta + '件。';
      } else {
        lastCount = record; $('repeat-count').hidden = false;
        successMessage = (result.replayed ? '原盤點結果已確認（沒有再次套用差額）' : '盤點差額提交成功') + '；修訂 ' + result.revision + '；總量差額 ' + result.physical_delta + '件；目前帳面 ' + result.movement.physical_book + '件。';
      }
      try { await loadStatus(); say(successMessage); } catch (error) { say(successMessage + '重新讀取庫存失敗，請按重新核對：' + error.message, true); }
    } catch (error) {
      if (!error.unknown) { pending = null; persist(); preview = null; }
      say(error.message + (error.unknown ? '請以原請求重試。' : '；資料未變更，請重新核對後再操作。'), true);
    } finally { busy = false; lock(); }
  };
  $('sales-form').addEventListener('input', invalidate);
  $('sales-form').addEventListener('change', invalidate);
  $('sales-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy || pending) return;
    busy = true; lock();
    try {
      const file = $('sales-file').files[0];
      if (!file || file.size > 512 * 1024) throw new Error('請選擇512 KiB以內的 UTF-8 CSV');
      const csvText = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      const body = {store_id: storeId, csv_text: csvText, import_mode: $('sales-mode').value,
        replaces_batch_id: $('replacement-id').value ? number('replacement-id') : null, reason: $('sales-reason').value};
      const data = await api('/api/sales/import/validate', body);
      preview = { ...data, body: {...body, validation_token: data.validation_token} };
      renderPreview(data); say(data.valid ? '請核對預覽，再按提交整批。' : '驗證未通過，整批未匯入。', !data.valid);
    } catch (error) { preview = null; say(error.message, true); }
    finally { busy = false; lock(); }
  });
  $('commit-sales').addEventListener('click', () => { if (preview?.valid) submitOriginal({kind: 'sales', url: '/api/sales/import/commit', body: preview.body}); });
  $('count-product').addEventListener('change', fillCount);
  $('count-form').addEventListener('submit', event => {
    event.preventDefault(); if (busy || pending) return;
    try {
      const item = selected(); if (!item) throw new Error('請先讀取商品');
      const correction = $('count-correction').checked;
      const body = {store_id: storeId, product_id: item.product_id, cutoff_at: $('count-cutoff').value,
        physical_qty: number('count-physical'), unsellable_qty: number('count-unsellable'),
        expected_version: item.inventory_version, request_key: crypto.randomUUID(),
        reason: $('count-reason').value, correction,
        expected_count_version: correction ? item.count_version : null};
      if (body.unsellable_qty > body.physical_qty) throw new Error('不可販售量不得大於實體總量');
      submitOriginal({kind: 'count', url: '/api/inventory/counts', body});
    } catch (error) { say(error.message, true); }
  });
  $('retry-pending').addEventListener('click', () => { if (pending) submitOriginal(pending); });
  $('repeat-sales').addEventListener('click', () => { if (lastSales) submitOriginal(lastSales); });
  $('repeat-count').addEventListener('click', () => { if (lastCount) submitOriginal(lastCount); });
  $('refresh-status').addEventListener('click', async () => {
    if (busy || pending) return; busy = true; preview = null; lock();
    try { await loadStatus(); say('已重新核對最新庫存與入帳狀況。'); }
    catch (error) { say(error.message, true); }
    finally { busy = false; lock(); }
  });
  (async () => {
    busy = true; lock();
    try {
      const stored = sessionStorage.getItem(storageKey);
      if (stored) {
        const value = JSON.parse(stored);
        if (value.body?.store_id === storeId && ['sales', 'count'].includes(value.kind)
          && value.url === (value.kind === 'sales' ? '/api/sales/import/commit' : '/api/inventory/counts')) pending = value;
      }
      csrf = (await api('/api/auth/csrf')).csrf_token;
      await loadStatus(); lock();
    } catch (error) { say(error.message, true); }
    finally { busy = false; lock(); }
  })();
})();

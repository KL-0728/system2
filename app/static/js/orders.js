(() => {
  'use strict';
  const escapeHtml = (value) => {
    const node = document.createElement('span'); node.textContent = String(value ?? ''); return node.innerHTML;
  };
  async function load(url) {
    const response = await fetch(url, {credentials: 'same-origin'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error?.message || '載入失敗，請稍後再試。');
    return data;
  }
  const statusLabel = (status) => ({
    SUBMITTED: '已送出', PENDING: '待處理', CONFIRMED: '已確認',
    PARTIAL: '部分供貨', FULFILLED: '已完成', CANCELLED: '已取消',
  }[status] || '狀態已更新');
  const list = document.getElementById('orders-list');
  if (list) load(`/api/orders?store_id=${list.dataset.storeId}`).then((data) => {
    list.innerHTML = data.orders.length ? data.orders.map((order) => `<article class="order-card"><a href="/store/orders/${order.id}?store_id=${list.dataset.storeId}">${escapeHtml(order.number)}</a> <span class="status-chip">${statusLabel(order.status)}</span><p>送出時間：${escapeHtml(order.submitted_at)}</p></article>`).join('') : '<div class="empty-state"><strong>尚無正式訂單</strong><p>從補貨工作台建立並確認送出。</p></div>';
  }).catch((error) => { const target = document.getElementById('orders-error'); target.textContent = error.message; target.hidden = false; });

  const detail = document.getElementById('order-detail');
  if (detail) load(`/api/orders/${detail.dataset.orderId}?store_id=${detail.dataset.storeId}`).then((order) => {
    const snapshotItems = order.confirmation_snapshot?.items || [];
    detail.innerHTML = `<section class="panel"><h2>訂購資訊</h2><dl class="definition-grid"><dt>訂單編號</dt><dd>${escapeHtml(detail.dataset.orderNumber)}</dd><dt>送出時間</dt><dd>${escapeHtml(order.submitted_at)}</dd></dl></section>
      <section class="panel"><h2>品項</h2>${order.items.map((item) => { const snap = snapshotItems.find((row) => row.product_id === item.product_id) || {}; return `<article class="summary-card"><strong>${escapeHtml(item.product_snapshot.name || '商品名稱待更新')}</strong><p>不可變原訂量：${item.original_qty} ${escapeHtml(item.product_snapshot.unit || '件')}</p><p>當時建議：${snap.suggested_qty ?? '無法計算'}；警示：${(snap.warnings || []).map((warning) => escapeHtml(warning.message)).join('、') || '無'}</p></article>`; }).join('')}</section>
      <section class="panel"><h2>供貨狀態</h2>${(order.fulfillment.items || []).map((item) => `<article class="summary-card"><strong>${statusLabel(item.status)}</strong><p>已確認供貨 ${Number(item.committed_qty || 0)} 件</p></article>`).join('') || '<p>尚無供貨品項摘要。</p>'}</section>
      <section class="panel"><h2>供貨變更與時間軸</h2>${(order.fulfillment.timeline || []).map((event) => `<article class="summary-card"><strong>供貨狀態更新</strong><p>${escapeHtml(event.occurred_at || '時間待更新')}</p></article>`).join('') || '<p>尚無供貨變更。變更接受、拒絕與重申由履約服務提供，本頁不改寫履約狀態。</p>'}</section>
      <section class="panel"><h2>待辦</h2>${(order.fulfillment.tasks || []).map((task) => `<article class="summary-card"><strong>待處理事項</strong><p>期限：${escapeHtml(task.due_at || '未提供')}；${task.overdue ? '已逾期' : '處理中'}</p></article>`).join('') || '<p>目前沒有履約待辦。</p>'}</section>`;
  }).catch((error) => { const target = document.getElementById('order-error'); target.textContent = error.message; target.hidden = false; detail.innerHTML = ''; });
})();

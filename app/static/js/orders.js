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
    SUBMITTED: '待統家接單', PENDING: '待處理', CONFIRMED: '已確認',
    PARTIAL: '部分供貨', FULFILLED: '已完成', CANCELLED: '已取消',
    ACCEPTED: '已接單', REJECTED: '已拒絕', CHANGE_PENDING: '供貨變更待確認',
    PARTIALLY_SHIPPED: '部分出貨', SHIPPED: '已出貨',
    PARTIALLY_RECEIVED: '部分收貨', RECEIVED: '已收貨', CLOSED_WITH_VARIANCE: '差異結案',
  }[status] || '狀態已更新');
  const eventLabel = value => ({ACCEPTED:'接單',REJECTED:'拒絕品項',CANCELLED:'取消品項',SHIPPED:'登記出貨',RECEIVED:'核對收貨',CHANGE_PROPOSED:'提出供貨變更',CHANGE_RESPONDED:'回覆供貨變更',CANCELLATION_REQUESTED:'提出取消未出貨量',REAFFIRMED:'重申承諾',REPLACEMENT_AUTHORIZED:'授權補送',VARIANCE_CLOSED:'差異結案',DAMAGED_REMOVED:'處理損壞品',EXTRA_HELD:'隔離多送品',EXTRA_RESOLVED:'處理多送品',SHIPMENT_UNKNOWN:'標記到貨待查',SHIPMENT_RECONFIRMED:'確認仍在途'}[value] || '供貨狀態更新');
  const taskLabel = value => ({respond_order:'回覆接單',receive_shipment:'核對收貨',investigate_shipment:'查明到貨',respond_change:'回覆供貨變更',resolve_variance:'處理收貨差異',contact_headquarters:'聯絡統家',resolve_extra:'處理多送品'}[value] || '待處理事項');
  const timeLabel = (value) => value ? new Date(value).toLocaleString('zh-TW', {timeZone: 'Asia/Taipei', hour12: false}) : '尚未提供';
  const reasonLabel = (value) => ({promotion: '促銷', local_demand: '在地需求', display: '陳列調整', reduce_stock: '降低庫存', skip: '本次不訂', other: '其他'}[value] || '一般補貨，未調整');
  const list = document.getElementById('orders-list');
  let pageRequest = 0;
  async function loadPage(page = 1) {
    const requestId = ++pageRequest;
    const errorTarget = document.getElementById('orders-error');
    errorTarget.hidden = true;
    try {
      const data = await load(`/api/orders?store_id=${list.dataset.storeId}&page=${page}`);
      if (requestId !== pageRequest) return;
      list.innerHTML = data.orders.length ? data.orders.map((order) => `<article class="order-card"><a href="/store/orders/${order.id}?store_id=${list.dataset.storeId}">${escapeHtml(order.number)}</a> <span class="status-chip">${statusLabel(order.status)}</span><p>送出時間：${escapeHtml(timeLabel(order.submitted_at))}</p></article>`).join('') : '<div class="empty-state"><strong>尚無正式訂單</strong><p>從補貨工作台建立並確認送出。</p></div>';
      const pager = document.getElementById('orders-pagination');
      pager.innerHTML = `<button id="previous-page" class="secondary" ${page === 1 ? 'disabled' : ''}>上一頁</button><span>第 ${page} 頁 · 共 ${data.total} 筆</span><button id="next-page" class="secondary" ${data.has_next ? '' : 'disabled'}>下一頁</button>`;
      document.getElementById('previous-page').onclick = () => loadPage(page - 1);
      document.getElementById('next-page').onclick = () => loadPage(page + 1);
    } catch (error) {
      if (requestId !== pageRequest) return;
      errorTarget.textContent = error.message; errorTarget.hidden = false;
    }
  }
  if (list) loadPage();

  const detail = document.getElementById('order-detail');
  if (detail) load(`/api/orders/${detail.dataset.orderId}?store_id=${detail.dataset.storeId}`).then((order) => {
    const snapshotItems = order.confirmation_snapshot?.items || [];
    const acknowledgements = order.confirmation_snapshot?.exception_acknowledgements || [];
    const fulfillment = order.fulfillment || {items: [], tasks: [], timeline: []};
    const handlingLabel = (value) => ({keep_and_contact: '維持訂量並聯絡統家', adjusted: '已調整訂量', special_arrangement: '已確認存放／交付安排'}[value] || value || '一般確認');
    detail.innerHTML = `<section class="panel"><h2>訂購資訊</h2><dl class="definition-grid"><dt>訂單編號</dt><dd>${escapeHtml(detail.dataset.orderNumber)}</dd><dt>送出時間</dt><dd>${escapeHtml(timeLabel(order.submitted_at))}</dd></dl></section>
      <section class="panel"><h2>品項</h2>${order.items.map((item) => { const snap = snapshotItems.find((row) => row.product_id === item.product_id) || {}; return `<article class="summary-card"><strong>${escapeHtml(item.product_snapshot.name || '商品名稱待更新')}</strong><p>不可變原訂量：${item.original_qty} ${escapeHtml(item.product_snapshot.unit || '件')}</p><p>當時建議：${snap.suggested_qty ?? '無法計算'}；警示：${(snap.warnings || []).map((warning) => escapeHtml(warning.message)).join('、') || '無'}</p></article>`; }).join('')}</section>
      <section class="panel"><h2>本次決策紀錄</h2>${snapshotItems.map((item) => {
        const ack = acknowledgements.find((row) => row.product_id === item.product_id);
        return `<article class="summary-card"><strong>${escapeHtml(item.name)}${item.final_qty === 0 ? '（本次排除）' : ''}</strong><p>當時建議 ${item.suggested_qty ?? '無法計算'} → 最終 ${item.final_qty} 件</p><p>調整原因：${escapeHtml(reasonLabel(item.reason_code))}</p>${item.reason ? `<p>補充說明：${escapeHtml(item.reason)}</p>` : ''}${item.special_need ? `<p>需求日期：${escapeHtml(item.special_need.need_date)}；需求量 ${item.special_need.need_qty} 件；安排：${escapeHtml(item.special_need.arrangement)}</p>` : ''}${ack ? `<p>處理方式：${escapeHtml(handlingLabel(ack.handling))}；補充：${escapeHtml(ack.reason || '沿用原理由')}</p>` : ''}</article>`;
      }).join('')}</section>
      <section class="panel"><h2>供貨狀態</h2>${order.fulfillment_unavailable ? `<p>${escapeHtml(order.fulfillment_unavailable)}</p>` : ''}${fulfillment.items.map((item) => `<article class="summary-card"><strong>${escapeHtml(statusLabel(item.status))}</strong><dl class="definition-grid">${[['承諾供貨', 'committed_qty'], ['原始已出貨', 'original_shipped_qty'], ['補送已出貨', 'replacement_shipped_qty'], ['已收可售', 'sellable_received_qty'], ['損壞', 'damaged_received_qty'], ['確認短收', 'confirmed_short_qty'], ['尚待核對', 'pending_receipt_qty'], ['爭議餘量', 'disputed_qty']].map(([label, key]) => `<dt>${label}</dt><dd>${item[key] == null ? '尚未提供' : Number(item[key]) + ' 件'}</dd>`).join('')}<dt>預計到貨</dt><dd>${escapeHtml(timeLabel(item.eta))}</dd></dl></article>`).join('') || '<p>尚無供貨品項摘要。</p>'}</section>
      <section class="panel"><h2>供貨變更與時間軸</h2>${fulfillment.timeline.map((event) => `<article class="summary-card"><strong>${escapeHtml(event.label || eventLabel(event.type))}</strong><p>${escapeHtml(timeLabel(event.occurred_at))}</p><p>${escapeHtml(event.snapshot?.reason || event.snapshot?.message || '')}</p></article>`).join('') || '<p>尚無供貨變更。</p>'}</section>
      <section class="panel"><h2>待辦</h2>${fulfillment.tasks.map((task) => `<article class="summary-card"><strong>${escapeHtml(task.label || taskLabel(task.type))}</strong><p>期限：${escapeHtml(timeLabel(task.due_at))}；${task.completed_at ? '已完成' : task.overdue ? '已逾期' : '處理中'}</p><p>${escapeHtml(task.result?.message || '')}</p></article>`).join('') || '<p>目前沒有履約待辦。</p>'}</section>`;
  }).catch((error) => { const target = document.getElementById('order-error'); target.textContent = error.message; target.hidden = false; detail.innerHTML = ''; });
})();

(() => {
  'use strict';
  const root = document.querySelector('.fulfillment-app');
  if (!root) return;
  const role = root.dataset.role;
  const store = document.querySelector('#fulfillment-store');
  const order = document.querySelector('#fulfillment-order');
  const detail = document.querySelector('#fulfillment-detail');
  const error = document.querySelector('#fulfillment-error');
  let csrf, current, products = [];
  const key = () => crypto.randomUUID();
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  const option = (select, value, label) => {
    const el = node('option', label);
    el.value = value;
    select.append(el);
  };
  const field = (form, name, label, value = '', type = 'text') => {
    const wrapper = node('label', label);
    const input = document.createElement('input');
    input.name = name;
    input.type = type;
    input.value = value;
    input.required = true;
    if (type === 'number') { input.min = '0'; input.step = '1'; }
    wrapper.append(input);
    form.append(wrapper);
    return input;
  };
  const form = (parent, title, fields, run) => {
    const el = document.createElement('form');
    const requestKey = key();
    el.append(node('h3', title));
    fields(el);
    const button = node('button', title);
    button.type = 'submit';
    el.append(button);
    el.addEventListener('submit', async event => {
      event.preventDefault();
      if (button.disabled) return;
      button.disabled = true;
      error.textContent = '';
      try { await run(new FormData(el), requestKey); await loadOrder(); }
      catch (e) { error.textContent = e.message; }
      finally { button.disabled = false; }
    });
    parent.append(el);
    return el;
  };
  async function api(url, body) {
    const opts = body === undefined ? {} : {method: 'POST', headers: {
      'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(body)};
    const response = await fetch(url, opts);
    const data = await response.json();
    if (!response.ok) throw Error(data.error?.message || `HTTP ${response.status}`);
    return data;
  }
  const post = (path, body) => api(`/api/fulfillment/${path}`, body);
  async function loadStores() {
    const data = await api('/api/fulfillment/stores');
    store.replaceChildren();
    data.stores.forEach(s => option(store, s.id, `${s.code} ${s.name}`));
    if (store.value) await loadOrders();
  }
  async function loadOrders() {
    const data = await api(`/api/fulfillment/orders?store_id=${store.value}`);
    order.replaceChildren();
    data.orders.forEach(o => option(order, o.id, `${o.number} (${o.status})${o.fixture_only ? ' · D測試訂單' : ''}`));
    if (order.value) await loadOrder(); else detail.replaceChildren(node('p', '本門市目前沒有正式訂單。'));
  }
  async function loadOrder() {
    if (!order.value) return;
    current = await api(`/api/fulfillment/orders/${order.value}`);
    detail.replaceChildren();
    detail.append(node('p', `訂單 ${current.order_id} · ${current.fixture_only ? '獨立測試資料' : '正式送單'} · 版本 ${current.version}`));
    const tasks = node('article', '');
    tasks.append(node('h2', '我的待辦'));
    const openTasks = current.tasks.filter(t => !t.completed_at);
    if (!openTasks.length) tasks.append(node('p', '目前沒有待辦。'));
    openTasks.forEach(t => tasks.append(node('p', `${t.task_type} · ${t.source_type} ${t.source_id} · 截止 ${t.due_at}${t.overdue ? ' · 已逾期' : ''}`)));
    detail.append(tasks);
    if (role === 'manager') {
      const contact = node('article', '');
      contact.append(node('h2', '聯絡統家'));
      form(contact, '新增聯絡待辦', f => field(f, 'reason', '聯絡原因'),
        d => post(`stores/${store.value}/contacts`, {reason: d.get('reason')}));
      const allTasks = await api(`/api/fulfillment/tasks?store_id=${store.value}`);
      allTasks.tasks.filter(t => t.task_type === 'contact_headquarters').forEach(t => {
        contact.append(node('p', `原因：${t.details?.reason || ''} · 截止 ${t.due_at}${t.overdue ? ' · 已逾期' : ''}`));
        form(contact, '記錄聯絡結果', f => field(f, 'result', '處理結果'),
          d => post(`contacts/${t.id}/resolve`, {result: d.get('result')}));
      });
      detail.append(contact);
    }
    for (const item of current.items) renderItem(item);
    for (const shipment of current.shipments) renderShipment(shipment);
    for (const change of current.changes) renderChange(change);
    for (const variance of current.variances) renderVariance(variance);
    for (const auth of current.authorizations) renderAuthorization(auth);
    const timeline = node('article', '');
    timeline.append(node('h2', '履約時間軸'));
    current.timeline.forEach(e => timeline.append(node('p', `${e.at}　${e.type}　${JSON.stringify(e.details)}`)));
    if (role === 'operator') {
      current.timeline.filter(e => e.type === 'EXTRA_HELD' &&
        !current.timeline.some(done => done.type === 'EXTRA_RESOLVED' &&
          done.details.held_event_id === e.id)).forEach(e => {
        form(timeline, `處理隔離多送品 ${e.id}`, f => {
          const label = node('label', '處理方式');
          const select = document.createElement('select');
          select.name = 'action';
          option(select, 'return', '退回'); option(select, 'discard', '報廢');
          label.append(select); f.append(label);
          field(f, 'reason', '處理原因');
        }, d => post(`extra/${e.id}/resolve`, {action: d.get('action'),
          reason: d.get('reason')}));
      });
    }
    detail.append(timeline);
  }
  function renderItem(item) {
    const card = node('article', '');
    card.append(node('h2', `品項 ${item.product_id} · ${item.status}`));
    card.append(node('p', `原訂 ${item.original_qty} 件 · 承諾 ${item.committed_qty} 件 · ETA ${item.eta || '待回覆'}${item.disputed ? ' · 供貨爭議，暫停新出貨' : ''}`));
    if (role === 'operator' && item.disputed) {
      form(card, '重申原承諾', () => {}, () => post(`items/${item.item_id}/reaffirm`, {}));
    }
    if (role === 'operator' && item.status === 'SUBMITTED') {
      form(card, '完整接單', f => {
        field(f, 'committed_qty', '承諾件數', item.original_qty, 'number');
        field(f, 'eta', '預計到貨（含時區）', item.requested_eta);
      }, d => post(`items/${item.item_id}/accept`, {committed_qty: Number(d.get('committed_qty')), eta: d.get('eta')}));
      form(card, '拒絕品項', f => field(f, 'reason', '原因'),
        d => post(`items/${item.item_id}/reject`, {reason: d.get('reason')}));
    }
    if (role === 'manager' && item.status === 'SUBMITTED') {
      form(card, '取消未接單品項', f => field(f, 'reason', '取消原因'),
        d => post(`items/${item.item_id}/cancel`, {reason: d.get('reason')}));
    }
    if (role === 'manager' && item.committed_qty > item.original_shipped_qty &&
        ['ACCEPTED', 'PARTIALLY_SHIPPED', 'PARTIALLY_RECEIVED'].includes(item.status)) {
      form(card, '提出取消未出貨量', f => field(f, 'reason', '取消原因'),
        d => post(`items/${item.item_id}/cancel-request`, {reason: d.get('reason')}));
    }
    if (role === 'operator' && ['SUBMITTED', 'ACCEPTED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'PARTIALLY_RECEIVED'].includes(item.status)) {
      form(card, '提出供貨變更', f => {
        field(f, 'committed_qty', '新承諾總件數', item.committed_qty, 'number');
        field(f, 'eta', '新 ETA（含時區）', item.eta || item.requested_eta);
        field(f, 'reason', '原因');
      }, d => post(`items/${item.item_id}/changes`, {committed_qty: Number(d.get('committed_qty')), eta: d.get('eta'), reason: d.get('reason')}));
    }
    if (role === 'operator' && item.committed_qty > item.original_shipped_qty &&
        ['ACCEPTED', 'PARTIALLY_SHIPPED', 'PARTIALLY_RECEIVED', 'SHIPPED'].includes(item.status)) {
      form(card, '出貨', f => {
        field(f, 'quantity', '本批件數', 1, 'number');
        field(f, 'eta', '本批 ETA（含時區）', item.eta || item.requested_eta);
      }, (d, requestKey) => post(`orders/${current.order_id}/shipments`, {request_key: requestKey, lines: [{item_id: item.item_id,
        kind: 'original', quantity: Number(d.get('quantity')), eta: d.get('eta')}]}));
    }
    detail.append(card);
  }
  function renderShipment(shipment) {
    const card = node('article', '');
    card.append(node('h2', `出貨批次 ${shipment.id}`));
    for (const line of shipment.lines) {
      const remaining = line.shipped_qty - line.checked_qty;
      card.append(node('p', `品項 ${line.item_id} · ${line.kind} · 出貨 ${line.shipped_qty} · 已核對 ${line.checked_qty} · 待核對 ${remaining}${line.eta_disputed ? ' · 到貨待查，暫不扣抵' : ''}`));
      if (role === 'manager' && remaining > 0) {
        form(card, '確認本批收貨', f => {
          field(f, 'checked_qty', '本次核對量', remaining, 'number');
          field(f, 'sellable_qty', '可販售實收', remaining, 'number');
          field(f, 'damaged_qty', '損壞實收', 0, 'number');
          field(f, 'short_qty', '確認短收', 0, 'number');
          field(f, 'note', '有差異時填原因', '正常收貨');
        }, (d, requestKey) => post(`shipments/${shipment.id}/receipts`, {request_key: requestKey, lines: [{shipment_item_id: line.id,
          checked_qty: Number(d.get('checked_qty')), sellable_qty: Number(d.get('sellable_qty')),
          damaged_qty: Number(d.get('damaged_qty')), short_qty: Number(d.get('short_qty')),
          note: d.get('note')}] }));
        if (!line.eta_disputed) {
          form(card, '標記到貨待查', f => field(f, 'reason', '待查原因'),
            d => post(`shipment-items/${line.id}/unknown`, {reason: d.get('reason')}));
        }
      }
      if (role === 'operator' && remaining > 0 && line.eta_disputed) {
        form(card, '確認仍在途', f => {
          field(f, 'eta', '更新 ETA（含時區）', line.eta);
          field(f, 'reason', '確認結果');
        }, d => post(`shipment-items/${line.id}/resolve`, {eta: d.get('eta'), reason: d.get('reason')}));
      }
    }
    if (role === 'manager') {
      form(card, '登記隔離多送品', f => {
        const label = node('label', '多送商品');
        const select = document.createElement('select');
        select.name = 'product_id';
        products.forEach(p => option(select, p.id, `${p.sku} ${p.name}`));
        label.append(select); f.append(label);
        field(f, 'quantity_value', '多送件數', 1, 'number');
        field(f, 'reason', '隔離原因');
      }, (d, requestKey) => post(`shipments/${shipment.id}/extra`, {
        request_key: requestKey, product_id: Number(d.get('product_id')),
        quantity_value: Number(d.get('quantity_value')), reason: d.get('reason')}));
    }
    detail.append(card);
  }
  function renderChange(change) {
    const card = node('article', '');
    card.append(node('h2', `供貨提案 ${change.id} · ${change.status}`));
    card.append(node('p', `新條件 ${JSON.stringify(change.new_conditions)} · 原因 ${change.reason} · 回覆期限 ${change.due_at}`));
    if (role !== change.initiator_role && change.status === 'PENDING') {
      form(card, '回覆提案', f => {
        const label = node('label', '回覆');
        const select = document.createElement('select');
        select.name = 'accept';
        option(select, 'yes', '接受'); option(select, 'no', '拒絕');
        label.append(select); f.append(label);
        field(f, 'reason', '拒絕原因（接受可留空）', '').required = false;
      }, d => post(`changes/${change.id}/response`, {accept: d.get('accept') === 'yes', reason: d.get('reason')}));
    }
    detail.append(card);
  }
  function renderVariance(variance) {
    const card = node('article', '');
    card.append(node('h2', `差異 ${variance.id} · ${variance.kind} · ${variance.status}`));
    card.append(node('p', `差異 ${variance.quantity} 件 · 已結 ${variance.closed_qty} 件`));
    if (role === 'operator' && variance.status === 'OPEN') {
      form(card, '授權補送', f => {
        field(f, 'quantity_value', '補送件數', variance.quantity - variance.closed_qty, 'number');
        const item = current.items.find(i => i.item_id === variance.item_id);
        field(f, 'eta', '補送 ETA（含時區）', item?.eta || item?.requested_eta || new Date(Date.now() + 86400000).toISOString());
      }, (d, requestKey) => post(`variances/${variance.id}/authorizations`, {request_key: requestKey,
        quantity_value: Number(d.get('quantity_value')), eta: d.get('eta')}));
      form(card, '差異結案', f => field(f, 'reason', '結案原因'),
        d => post(`variances/${variance.id}/close`, {reason: d.get('reason')}));
    }
    if (role === 'manager' && variance.kind === 'damaged') {
      form(card, '損壞品處置', f => {
        field(f, 'quantity_value', '處置件數', variance.quantity, 'number');
        const label = node('label', '處置方式');
        const select = document.createElement('select');
        select.name = 'action';
        option(select, 'discard', '報廢'); option(select, 'return', '退回');
        label.append(select); f.append(label);
      }, (d, requestKey) => post(`variances/${variance.id}/damaged-removal`, {
        request_key: requestKey, quantity_value: Number(d.get('quantity_value')),
        action: d.get('action')}));
    }
    detail.append(card);
  }
  function renderAuthorization(auth) {
    const card = node('article', '');
    const remaining = auth.authorized_qty - auth.used_qty - auth.closed_qty;
    card.append(node('h2', `補送授權 ${auth.id} · 差異 ${auth.variance_id}`));
    card.append(node('p', `授權 ${auth.authorized_qty} 件 · 已出貨 ${auth.used_qty} · 尚可出貨 ${remaining}`));
    if (role === 'operator' && remaining > 0) {
      const variance = current.variances.find(v => v.id === auth.variance_id);
      form(card, '補送出貨', f => {
        field(f, 'quantity', '本批件數', remaining, 'number');
        field(f, 'eta', '本批 ETA（含時區）', auth.eta);
      }, (d, requestKey) => post(`orders/${current.order_id}/shipments`, {request_key: requestKey,
        lines: [{item_id: variance.item_id, kind: 'replacement', authorization_id: auth.id,
          quantity: Number(d.get('quantity')), eta: d.get('eta')}]}));
    }
    detail.append(card);
  }
  store.addEventListener('change', () => loadOrders().catch(e => error.textContent = e.message));
  order.addEventListener('change', () => loadOrder().catch(e => error.textContent = e.message));
  document.querySelector('#fulfillment-refresh').addEventListener('click', () => loadOrders().catch(e => error.textContent = e.message));
  (async () => { csrf = (await api('/api/auth/csrf')).csrf_token;
    products = (await api('/api/fulfillment/products')).products;
    await loadStores(); })()
    .catch(e => error.textContent = e.message);
})();

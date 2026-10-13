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
  let orderPage = 1;
  let loadSequence = 0;
  const states = {SUBMITTED:'待統家接單',ACCEPTED:'已接單',REJECTED:'已拒絕',CANCELLED:'已取消',PARTIALLY_SHIPPED:'部分出貨',SHIPPED:'已出貨',PARTIALLY_RECEIVED:'部分收貨',RECEIVED:'已收貨',CLOSED_WITH_VARIANCE:'差異結案',CHANGE_PENDING:'供貨變更待確認',PENDING:'待回覆',OPEN:'待處理',CLOSED:'已結案',DISPUTED:'有爭議'};
  const taskNames = {respond_order:'回覆接單',receive_shipment:'核對收貨',investigate_shipment:'查明到貨',respond_change:'回覆供貨變更',resolve_variance:'處理收貨差異',contact_headquarters:'聯絡統家',resolve_extra:'處理多送品'};
  const eventNames = {ACCEPTED:'接單',REJECTED:'拒絕品項',CANCELLED:'取消品項',SHIPPED:'登記出貨',RECEIVED:'核對收貨',CHANGE_PROPOSED:'提出供貨變更',CHANGE_RESPONDED:'回覆供貨變更',CANCELLATION_REQUESTED:'提出取消未出貨量',REAFFIRMED:'重申承諾',REPLACEMENT_AUTHORIZED:'授權補送',VARIANCE_CLOSED:'差異結案',DAMAGED_REMOVED:'處理損壞品',EXTRA_HELD:'隔離多送品',EXTRA_RESOLVED:'處理多送品',SHIPMENT_UNKNOWN:'標記到貨待查',SHIPMENT_RECONFIRMED:'確認仍在途'};
  const dateLabel = value => value ? new Date(value).toLocaleString('zh-TW', {timeZone:'Asia/Taipei',hour12:false}) + '（台北）' : '待回覆';
  const taipeiISO = value => value ? new Date(new Date(value).getTime()+8*3600000).toISOString().slice(0,19)+'+08:00' : '';
  const productLabel = id => {const p=products.find(p=>p.id===id);return p?`${p.sku} ${p.name}`:`商品 ${id}`;};
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
    input.value = name === 'eta' ? taipeiISO(value) : value;
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
  const post = (path, body) => api(`/api/fulfillment/${path}`, {...body, expected_version: current.version});
  async function loadStores() {
    const data = await api('/api/fulfillment/stores');
    store.replaceChildren();
    data.stores.forEach(s => option(store, s.id, `${s.code} ${s.name}`));
    const requested = new URLSearchParams(location.search).get('store_id');
    if (requested && data.stores.some(s => String(s.id) === requested)) store.value = requested;
    if (store.value) await loadOrders();
  }
  async function loadOrders() {
    if (!store.value) return;
    const sequence = ++loadSequence;
    const selected = order.value;
    current = null;
    detail.replaceChildren(node('p', '載入中…'));
    const data = await api(`/api/fulfillment/orders?store_id=${store.value}&page=${orderPage}`);
    if (sequence !== loadSequence) return;
    order.replaceChildren();
    data.orders.forEach(o => option(order, o.id, `${o.number} (${states[o.status] || o.status})${o.fixture_only ? ' · D測試訂單' : ''}`));
    if (data.orders.some(o => String(o.id) === selected)) order.value = selected;
    document.querySelector('#fulfillment-page').textContent = `第 ${data.page} 頁`;
    document.querySelector('#fulfillment-previous').disabled = data.page <= 1;
    document.querySelector('#fulfillment-next').disabled = !data.has_next;
    if (order.value) await loadOrder(); else detail.replaceChildren(node('p', '本門市目前沒有正式訂單。'));
  }
  async function loadOrder() {
    if (!order.value) return;
    const sequence = ++loadSequence;
    const selectedOrder = order.value;
    current = null;
    detail.replaceChildren(node('p', '載入中…'));
    const loaded = await api(`/api/fulfillment/orders/${selectedOrder}`);
    if (sequence !== loadSequence) return;
    current = loaded;
    detail.replaceChildren();
    detail.append(node('p', `${order.selectedOptions[0]?.textContent || '訂單'}${current.fixture_only ? ' · 獨立測試資料' : ''}`));
    const tasks = node('article', '');
    tasks.append(node('h2', '我的待辦'));
    const openTasks = current.tasks.filter(t => !t.completed_at);
    if (!openTasks.length) tasks.append(node('p', '目前沒有待辦。'));
    openTasks.forEach(t => tasks.append(node('p', `${taskNames[t.task_type] || '待處理作業'} · 截止 ${dateLabel(t.due_at)}${t.overdue ? ' · 已逾期' : ''}`)));
    detail.append(tasks);
    if (role === 'manager') {
      const contact = node('article', '');
      contact.append(node('h2', '聯絡統家'));
      form(contact, '新增聯絡待辦', f => field(f, 'reason', '聯絡原因'),
        d => post(`stores/${store.value}/contacts`, {reason: d.get('reason')}));
      const allTasks = await api(`/api/fulfillment/tasks?store_id=${store.value}`);
      if (sequence !== loadSequence) return;
      allTasks.tasks.filter(t => t.task_type === 'contact_headquarters').forEach(t => {
        contact.append(node('p', `原因：${t.details?.reason || ''} · 截止 ${dateLabel(t.due_at)}${t.overdue ? ' · 已逾期' : ''}`));
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
    current.timeline.forEach(e => {
      const record=node('details','');record.append(node('summary',`${dateLabel(e.at)} · ${eventNames[e.type] || '履約更新'}`));
      const names={quantity:'件數',committed_qty:'承諾件數',eta:'預計到貨',reason:'原因',checked:'核對件數',sellable:'可售件數',damaged:'損壞件數',short:'短收件數',action:'處理方式',old:'原條件',new:'新條件',status:'狀態',accept:'接受變更',kind:'出貨類型',new_conditions:'新供貨條件',conditions:'供貨條件'};
      const readable=(key,value)=>key==='eta'?dateLabel(value):typeof value==='boolean'?(value?'是':'否'):value&&typeof value==='object'?Object.entries(value).map(([k,v])=>`${names[k]||k}：${readable(k,v)}`).join(' · '):states[value]||({discard:'報廢',return:'退回',original:'原訂出貨',replacement:'補送'}[value])||String(value??'未設定');
      record.append(node('p',`操作者帳號編號：${e.actor_id || e.actor}`));
      for(const [key,value] of Object.entries(e.details || {}))if(names[key])record.append(node('p',`${names[key]}：${readable(key,value)}`));
      timeline.append(record);
    });
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
    card.append(node('h2', `${productLabel(item.product_id)} · ${states[item.status] || item.status}`));
    card.append(node('p', `原訂 ${item.original_qty} 件 · 承諾 ${item.committed_qty} 件 · 預計到貨 ${dateLabel(item.eta)}${item.disputed ? ' · 供貨爭議，暫停新出貨' : ''}`));
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
      form(card, '原訂出貨（非補送）', f => {
        field(f, 'quantity', '本批原訂件數', 1, 'number');
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
      const item=current.items.find(i=>i.item_id===line.item_id);
      card.append(node('p', `${productLabel(item?.product_id)} · ${line.kind==='replacement'?'授權補送':'原訂出貨'} · 出貨 ${line.shipped_qty} · 已核對 ${line.checked_qty} · 待核對 ${remaining}${line.eta_disputed ? ' · 到貨待查，暫不扣抵' : ''}`));
      if (role === 'manager' && remaining > 0) {
        form(card, '確認本批收貨', f => {
          field(f, 'checked_qty', '本次核對量', remaining, 'number');
          field(f, 'sellable_qty', '可販售實收', remaining, 'number');
          field(f, 'damaged_qty', '損壞實收', 0, 'number');
          field(f, 'short_qty', '確認短收', 0, 'number');
          field(f, 'note', '有差異時填原因').required = false;
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
    card.append(node('h2', `供貨提案 ${change.id} · ${states[change.status] || change.status}`));
    card.append(node('p', `新承諾 ${change.new_conditions.committed_qty} 件 · 到貨 ${dateLabel(change.new_conditions.eta)} · 原因 ${change.reason} · 回覆期限 ${dateLabel(change.due_at)}`));
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
    card.append(node('h2', `差異 ${variance.id} · ${variance.kind==='damaged'?'損壞':'短收'} · ${states[variance.status] || variance.status}`));
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
  store.addEventListener('change', () => {orderPage = 1; loadOrders().catch(e => error.textContent = e.message);});
  for (const [selector, delta] of [['#fulfillment-previous', -1], ['#fulfillment-next', 1]]) {
    document.querySelector(selector).addEventListener('click', async () => {
      const oldPage = orderPage;
      orderPage += delta;
      try { await loadOrders(); } catch (e) { orderPage = oldPage; error.textContent = e.message; }
    });
  }
  order.addEventListener('change', () => loadOrder().catch(e => error.textContent = e.message));
  document.querySelector('#fulfillment-refresh').addEventListener('click', () => loadOrders().catch(e => error.textContent = e.message));
  (async () => { csrf = (await api('/api/auth/csrf')).csrf_token;
    products = (await api('/api/fulfillment/products')).products;
    await loadStores(); })()
    .catch(e => error.textContent = e.message);
})();

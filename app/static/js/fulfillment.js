(() => {
  'use strict';
  const root = document.querySelector('.fulfillment-app');
  if (!root) return;
  const role = root.dataset.role;
  const store = document.querySelector('#fulfillment-store');
  const order = document.querySelector('#fulfillment-order');
  const detail = document.querySelector('#fulfillment-detail');
  const error = document.querySelector('#fulfillment-error');
  const status = document.createElement('p');status.id='fulfillment-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');root.prepend(status);
  let csrf, current, products = [], actorId, actorRole, pendingWrite = null, writing = false, identityChanged = false;
  let storageKey, storageBase, ownStorageKey;
  function restorePending() {
    if((pendingWrite && pendingWrite.recoveryState!=='permission') || !storageBase)return;
    storageKey=ownStorageKey;
    const candidates=[];
    for(const savedKey of Object.keys(localStorage).filter(k=>k===storageBase || k.startsWith(storageBase+':'))) {
      try {
        const saved=JSON.parse(localStorage.getItem(savedKey));
        if(saved?.url?.startsWith('/api/fulfillment/') && saved.body?.request_key && (!saved.actorId || saved.actorId===actorId))candidates.push({savedKey,saved});
      } catch(e) {error.textContent='保存的請求無法解析，請保留本機資料並聯絡維護者。';}
    }
    const priority = saved => saved.recoveryState!=='permission' ? 0 :
      String(saved.storeId)===store.value && String(saved.orderId)===order.value ? 1 : 2;
    candidates.sort((a,b)=>priority(a.saved)-priority(b.saved));
    if(candidates.length){storageKey=candidates[0].savedKey;pendingWrite=candidates[0].saved;}
  }
  const recovery = nodeRecovery();
  function nodeRecovery() { const panel=document.createElement("section"); panel.className="panel"; panel.hidden=true; root.prepend(panel); return panel; }
  const samePendingOrder = () => pendingWrite && String(pendingWrite.storeId)===store.value && String(pendingWrite.orderId)===order.value;
  const pendingBlocks = () => Boolean(pendingWrite && (pendingWrite.recoveryState!=='permission' || samePendingOrder()));
  function protect(locked) {
    root.querySelectorAll('input,select,button').forEach(el => {
      if (recovery.contains(el)) {el.disabled=writing;return;}
      const shouldLock=identityChanged || writing ||
        (locked && pendingWrite?.recoveryState!=='permission') ||
        (pendingWrite?.recoveryState==='permission' && samePendingOrder() && detail.contains(el));
      if(shouldLock) {
        if(el.dataset.wasDisabled===undefined)el.dataset.wasDisabled=String(el.disabled);
        el.disabled=true;
      } else if(el.dataset.wasDisabled!==undefined) {
        el.disabled=el.dataset.wasDisabled==='true';
        delete el.dataset.wasDisabled;
      }
    });
  }
  function showRecovery() {
    restorePending();
    recovery.replaceChildren(); recovery.hidden=!pendingWrite || identityChanged; if(!pendingWrite || identityChanged)return;
    const denied=pendingWrite.recoveryState==='permission', loginNeeded=pendingWrite.recoveryState==='login';
    recovery.append(node("p", denied ? '原操作權限已變更，已保留內容與請求識別，停止自動重試。可切換門市／訂單處理其他有權限的工作；原案件須恢復權限後再查詢或重試。' : loginNeeded ? '登入已失效。原請求已保存，請重新登入原帳號後再查詢或重試。' : '此操作結果尚未確認，已保存原請求。請查詢訂單或以原內容重試，不可修改後另送。'));
    if(loginNeeded){const login=node('a','重新登入原帳號');login.href=`/login?next=${encodeURIComponent(location.pathname+location.search)}`;recovery.append(login);}
    if(denied){const home=node('a','返回首頁查看目前可用工作');home.href='/';recovery.append(home);}
    recovery.append(node('p',`原門市 #${pendingWrite.storeId} · 原訂單 #${pendingWrite.orderId}`));
    const view=node("pre",JSON.stringify(pendingWrite.body,null,2));recovery.append(view);
    const inspect=node("a","查詢原訂單");inspect.href=`${role=== "manager"?"/store/receiving":"/headquarters/fulfillment"}?store_id=${pendingWrite.storeId}&order_id=${pendingWrite.orderId}`;recovery.append(inspect);
    const retry=node("button",denied?'重新檢查權限並重試':'以原內容重試');retry.type="button";recovery.append(retry);
    retry.onclick=async()=>{
      if(writing)return;
      writing=true;protect(true);retry.disabled=true;
      const original=pendingWrite;
      try {
        await sendSaved();error.textContent='';status.textContent='操作已確認完成。';
        try {
          if(String(original.storeId)!==store.value || String(original.orderId)!==order.value) {
            if(!Array.from(store.options).some(o=>o.value===String(original.storeId)))await loadStores();
            store.value=String(original.storeId);requestedOrder=String(original.orderId);orderPage=1;
            await loadOrders();
          } else await loadOrder();
        } catch(e) {status.textContent='操作已完成，更新畫面失敗，請重新整理。';}
      } catch(e) {error.textContent=e.message;}
      finally {writing=false;retry.disabled=false;showRecovery();protect(Boolean(pendingWrite));}
    };
  }
  let orderPage = 1;
  let requestedOrder = new URLSearchParams(location.search).get('order_id');
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
    input.type = name === 'eta' ? 'datetime-local' : type;
    if(name==='eta')input.step='1';
    input.value = name === 'eta' ? taipeiISO(value).slice(0,19) : value;
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
      if (button.disabled || writing || pendingBlocks() || identityChanged) return;
      writing = true; protect(true);
      error.textContent = '';
      status.textContent='';
      try { const data=new FormData();el.querySelectorAll('[name]').forEach(input=>data.set(input.name,input.name==='eta'?input.value+'+08:00':input.value));await run(data, requestKey);status.textContent='操作已完成。';try{await loadOrder();}catch(e){status.textContent='操作已完成，更新畫面失敗，請重新整理。';} }
      catch (e) { error.textContent = e.message; }
      finally { writing=false; showRecovery(); protect(false); if(pendingWrite)protect(true); }
    });
    parent.append(el);
    return el;
  };
  async function api(url, body) {
    const opts = body === undefined ? {} : {method: 'POST', headers: {
      'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(body)};
    const response = await fetch(url, opts);
    const data = await response.json();
    if (!response.ok) {const failure=Error(data.error?.message || `HTTP ${response.status}`);failure.status=response.status;failure.code=data.error?.code;throw failure;}
    return data;
  }
  async function sendSaved() {
    const saved=pendingWrite;
    const savedKey=storageKey;
    try {
      await verifyIdentity();
      const allowed=await api('/api/fulfillment/stores');
      if(!allowed.stores.some(s=>String(s.id)===String(saved.storeId))){const failure=Error('原門市權限已撤銷，原請求保留；請切換其他有權限的門市。');failure.status=403;throw failure;}
      csrf=(await api('/api/auth/csrf')).csrf_token;
      saved.recoveryState='unknown';
      // Upgrade legacy records with identity metadata; business fields and key stay exact.
      saved.body.expected_actor_id ??= actorId;
      try{localStorage.setItem(savedKey,JSON.stringify(saved));}catch(_){}
      const result=await api(saved.url,saved.body);localStorage.removeItem(savedKey);pendingWrite=null;storageKey=ownStorageKey;return result;
    } catch(e) {
      if([401,403,404].includes(e.status)) {
        if(e.code==='ACTOR_CHANGED'){identityChanged=true;detail.replaceChildren(node('p','登入帳號已變更，請重新載入畫面。'));}
        saved.recoveryState=e.status===401?'login':'permission';
        // Never discard evidence on a permission failure, including a hidden cross-store 404.
        try{localStorage.setItem(savedKey,JSON.stringify(saved));}catch(_){}
      } else if(e.status && e.status < 500 && e.code && !['CSRF_FAILED','IDEMPOTENCY_CONFLICT'].includes(e.code)){localStorage.removeItem(savedKey);pendingWrite=null;storageKey=ownStorageKey;}
      throw e;
    }
  }
  async function verifyIdentity() {
    const actor=await api('/api/auth/me');
    if(actor.id!==actorId){identityChanged=true;recovery.replaceChildren();recovery.hidden=true;detail.replaceChildren(node('p','登入帳號已變更，請重新載入畫面；原帳號請求仍保留且不會交給新帳號。'));protect(true);const failure=Error('登入帳號已變更，請重新載入畫面。');failure.status=401;throw failure;}
    if(actor.role!==actorRole){const failure=Error('角色權限已變更，請重新載入畫面。原請求仍保留。');failure.status=403;throw failure;}
  }
  async function post(path, body) {
    const payload={...body,expected_version:current.version,expected_actor_id:actorId};
    payload.request_key ||= key();
    await verifyIdentity();
    // Each operation gets its own storage slot; a suspended case must survive other work.
    ownStorageKey=storageBase+':'+key();storageKey=ownStorageKey;
    pendingWrite={url:`/api/fulfillment/${path}`,body:payload,storeId:store.value,orderId:order.value,actorId};
    try{localStorage.setItem(storageKey,JSON.stringify(pendingWrite));}catch(e){pendingWrite=null;throw Error('無法保存原請求，請允許本機儲存後重試。');}
    return sendSaved();
  }
  async function loadStores() {
    const data = await api('/api/fulfillment/stores');
    store.replaceChildren();
    data.stores.forEach(s => option(store, s.id, `${s.code} ${s.name}`));
    const requested = new URLSearchParams(location.search).get('store_id');
    const targetStore = (pendingWrite?.recoveryState!=='permission' && pendingWrite?.storeId) || requested;
    if (targetStore && data.stores.some(s => String(s.id) === String(targetStore))) store.value = targetStore;
    if (store.value) await loadOrders();
  }
  async function loadOrders() {
    if (!store.value) return;
    const sequence = ++loadSequence;
    const selected = (pendingWrite?.recoveryState!=='permission' && pendingWrite?.orderId) || requestedOrder || order.value;
    const fetchExplicitTarget = Boolean((pendingWrite && pendingWrite.recoveryState!=='permission') || requestedOrder);
    current = null;
    detail.replaceChildren(node('p', '載入中…'));
    let data;
    try{data=await api(`/api/fulfillment/orders?store_id=${store.value}&page=${orderPage}&${new URLSearchParams(new FormData(document.querySelector("#order-filters")))}`);}catch(e){if(sequence!==loadSequence)return;throw e;}
    if (sequence !== loadSequence) return;
    order.replaceChildren();
    data.orders.forEach(o => option(order, o.id, `${o.number} (${states[o.status] || o.status})${o.fixture_only ? ' · D測試訂單' : ''}`));
    if (data.orders.some(o => String(o.id) === selected)) order.value = selected;
    else if(selected && fetchExplicitTarget) {
      const target=await api(`/api/fulfillment/orders/${encodeURIComponent(selected)}`);
      if(sequence!==loadSequence)return;
      if(String(target.store_id)===store.value){option(order,selected,`指定訂單 #${selected}`);order.value=String(selected);}
    }
    requestedOrder=null;
    document.querySelector('#fulfillment-page').textContent = `第 ${data.page} 頁`;
    document.querySelector('#fulfillment-previous').disabled = data.page <= 1;
    document.querySelector('#fulfillment-next').disabled = !data.has_next;
    if (order.value) await loadOrder(); else detail.replaceChildren(node('p', '本門市目前沒有正式訂單。'));
  }
  async function loadOrder() {
    if (!order.value) return;
    delete detail.dataset.loadedOrderId;
    const sequence = ++loadSequence;
    const selectedOrder = order.value;
    current = null;
    detail.replaceChildren(node('p', '載入中…'));
    let loaded;
    try{loaded=await api(`/api/fulfillment/orders/${selectedOrder}`);}catch(e){if(sequence!==loadSequence)return;throw e;}
    if (sequence !== loadSequence) return;
    current = loaded;
    if(current.number && current.status && order.selectedOptions[0])order.selectedOptions[0].textContent=`${current.number} (${states[current.status] || current.status})${current.fixture_only?' · D測試訂單':''}`;
    detail.replaceChildren();
    detail.append(node('p', `${order.selectedOptions[0]?.textContent || '訂單'}${current.fixture_only ? ' · 獨立測試資料' : ''}`));
    const tasks = node('article', '');
    tasks.append(node('h2', '我的待辦'));
    const openTasks = current.tasks.filter(t => !t.completed_at);
    if (!openTasks.length) tasks.append(node('p', '目前沒有待辦。'));
    openTasks.forEach(t => {const link=node('a',`${taskNames[t.task_type] || '待處理作業'} · 第${t.round}輪 · 截止 ${dateLabel(t.due_at)}${t.overdue ? ' · 已逾期' : ''}`);link.href=t.url;const p=node('p','');p.append(link);tasks.append(p);});
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
    const ready=current.items.filter(item=>!item.disputed && item.committed_qty>item.original_shipped_qty && ['ACCEPTED','PARTIALLY_SHIPPED','PARTIALLY_RECEIVED','SHIPPED'].includes(item.status));
    if(role==='operator' && ready.length>1) {
      const batch=node('article','');batch.append(node('h2','多品項原訂出貨'));
      form(batch,'整單原訂出貨（依承諾日期）',f=>{
        f.append(node('p','核對以下件數後建立同一批次。需延後物流ETA時，請使用逐項出貨填延遲原因。'));
        ready.forEach(item=>{const input=field(f,`quantity_${item.item_id}`,`${productLabel(item.product_id)} · 承諾到貨 ${dateLabel(item.eta || item.requested_eta)} · 本批件數`,item.committed_qty-item.original_shipped_qty,'number');input.max=String(item.committed_qty-item.original_shipped_qty);});
        const check=field(f,'confirmed','已核對本批品項、件數與承諾到貨','', 'checkbox');check.value='yes';
      },(d,requestKey)=>post(`orders/${current.order_id}/shipments`,{request_key:requestKey,lines:ready.filter(item=>Number(d.get(`quantity_${item.item_id}`))>0).map(item=>({item_id:item.item_id,kind:'original',quantity:Number(d.get(`quantity_${item.item_id}`)),eta:item.eta || item.requested_eta}))}));
      detail.append(batch);
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
      const names={delay_reason:'延遲原因',delayed:'晚於承諾',promised_eta:'原承諾到貨',previous_eta:'原物流預估',previous_overdue:'原到貨已逾期',quantity:'件數',committed_qty:'承諾件數',eta:'預計到貨',reason:'原因',checked:'核對件數',sellable:'可售件數',damaged:'損壞件數',short:'短收件數',action:'處理方式',old:'原條件',new:'新條件',status:'狀態',accept:'接受變更',kind:'出貨類型',new_conditions:'新供貨條件',conditions:'供貨條件'};
      const readable=(key,value)=>['eta','promised_eta','previous_eta'].includes(key)?dateLabel(value):typeof value==='boolean'?(value?'是':'否'):value&&typeof value==='object'?Object.entries(value).map(([k,v])=>`${names[k]||k}：${readable(k,v)}`).join(' · '):states[value]||({discard:'報廢',return:'退回',original:'原訂出貨',replacement:'補送'}[value])||String(value??'未設定');
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
    showRecovery();protect(Boolean(pendingWrite));
    if(location.hash)document.getElementById(location.hash.slice(1))?.scrollIntoView({block:'center'});
    detail.dataset.loadedOrderId=String(current.order_id);
  }
  function renderItem(item) {
    const card = node('article', '');card.id=`order_item-${item.item_id}`;
    card.append(node('h2', `${productLabel(item.product_id)} · ${states[item.status] || item.status}`));
    card.append(node('p', `原訂 ${item.original_qty} 件 · 承諾 ${item.committed_qty} 件 · 承諾到貨 ${dateLabel(item.eta)}${item.disputed ? ' · 供貨爭議，暫停新出貨' : ''}`));
    if (role === 'operator' && item.disputed) {
      form(card, '重申原承諾', () => {}, () => post(`items/${item.item_id}/reaffirm`, {}));
    }
    if (role === 'operator' && item.status === 'SUBMITTED') {
      form(card, '完整接單', f => {
        field(f, 'committed_qty', '承諾件數', item.original_qty, 'number');
        field(f, 'eta', '預計到貨（台北）', item.requested_eta);
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
        field(f, 'eta', '新 ETA（台北）', item.eta || item.requested_eta);
        field(f, 'reason', '原因');
      }, d => post(`items/${item.item_id}/changes`, {committed_qty: Number(d.get('committed_qty')), eta: d.get('eta'), reason: d.get('reason')}));
    }
    if (role === 'operator' && item.committed_qty > item.original_shipped_qty &&
        ['ACCEPTED', 'PARTIALLY_SHIPPED', 'PARTIALLY_RECEIVED', 'SHIPPED'].includes(item.status)) {
      form(card, '原訂出貨（非補送）', f => {
        field(f, 'quantity', '本批原訂件數', 1, 'number');
        field(f, 'eta', '物流預估到貨（台北）', item.eta || item.requested_eta);
        field(f,'delay_reason','晚於承諾時填延遲原因').required=false;
      }, (d, requestKey) => post(`orders/${current.order_id}/shipments`, {request_key: requestKey, lines: [{item_id: item.item_id,
        kind: 'original', quantity: Number(d.get('quantity')), eta: d.get('eta'), delay_reason:d.get('delay_reason') || null}]}));
    }
    detail.append(card);
  }
  function renderShipment(shipment) {
    const card = node('article', '');
    card.append(node('h2', `出貨批次 ${shipment.id}`));
    const normalLines=shipment.lines.filter(l=>l.shipped_qty>l.checked_qty && !l.eta_disputed);
    if(role==='manager' && normalLines.length>1)form(card,'整批正常收貨',f=>{f.append(node('p',normalLines.map(l=>`${productLabel(current.items.find(i=>i.item_id===l.item_id)?.product_id)}：${l.shipped_qty-l.checked_qty} 件`).join('；')));const check=field(f,'confirmed','已逐項核對實物均為正常可售','', 'checkbox');check.value='yes';},(d,requestKey)=>post(`shipments/${shipment.id}/receipts`,{request_key:requestKey,lines:normalLines.map(l=>({shipment_item_id:l.id,checked_qty:l.shipped_qty-l.checked_qty,sellable_qty:l.shipped_qty-l.checked_qty,damaged_qty:0,short_qty:0}))}));
    for (const line of shipment.lines) {
      const remaining = line.shipped_qty - line.checked_qty;
      const anchor=node('span','');anchor.id=`shipment_item-${line.id}`;card.append(anchor);
      const item=current.items.find(i=>i.item_id===line.item_id);
      card.append(node('p', `${productLabel(item?.product_id)} · ${line.kind==='replacement'?'授權補送':'原訂出貨'} · 出貨 ${line.shipped_qty} · 已核對 ${line.checked_qty} · 待核對 ${remaining} · 物流預估 ${dateLabel(line.eta)}${line.eta_disputed ? ' · 到貨待查，暫不扣抵' : ''}`));
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
          field(f, 'eta', '更新 ETA（台北）', line.eta);
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
    const card = node('article', '');card.id=`change-${change.id}`;
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
    const card = node('article', '');card.id=`variance-${variance.id}`;
    card.append(node('h2', `差異 ${variance.id} · ${variance.kind==='damaged'?'損壞':'短收'} · ${states[variance.status] || variance.status}`));
    card.append(node('p', `差異 ${variance.quantity} 件 · 已結 ${variance.closed_qty} 件`));
    if (role === 'operator' && variance.status === 'OPEN') {
      form(card, '授權補送', f => {
        field(f, 'quantity_value', '補送件數', variance.quantity - variance.closed_qty, 'number');
        const item = current.items.find(i => i.item_id === variance.item_id);
        field(f, 'eta', '補送 ETA（台北）', item?.eta || item?.requested_eta || new Date(Date.now() + 86400000).toISOString());
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
        field(f, 'eta', '物流預估到貨（台北）', auth.eta);
        field(f,'delay_reason','晚於授權到貨時填延遲原因').required=false;
      }, (d, requestKey) => post(`orders/${current.order_id}/shipments`, {request_key: requestKey,
        lines: [{item_id: variance.item_id, kind: 'replacement', authorization_id: auth.id,
          quantity: Number(d.get('quantity')), eta: d.get('eta'),delay_reason:d.get('delay_reason') || null}]}));
    }
    detail.append(card);
  }
  document.querySelector('#order-filters').addEventListener('submit',e=>{e.preventDefault();if(writing||(pendingWrite && pendingWrite.recoveryState!=='permission'))return;orderPage=1;loadOrders().catch(e=>error.textContent=e.message);});
  store.addEventListener('change', () => {requestedOrder=null;orderPage = 1; loadOrders().catch(e => error.textContent = e.message);});
  for (const [selector, delta] of [['#fulfillment-previous', -1], ['#fulfillment-next', 1]]) {
    document.querySelector(selector).addEventListener('click', async () => {
      const oldPage = orderPage;
      orderPage += delta;
      try { await loadOrders(); } catch (e) { orderPage = oldPage; error.textContent = e.message; }
    });
  }
  order.addEventListener('change', () => loadOrder().catch(e => error.textContent = e.message));
  document.querySelector('#fulfillment-refresh').addEventListener('click', () => loadOrders().catch(e => error.textContent = e.message));
  window.addEventListener('storage',event=>{if(!writing && (!pendingWrite || pendingWrite.recoveryState==='permission') && storageBase && event.key?.startsWith(storageBase)){showRecovery();protect(Boolean(pendingWrite));}});
  window.addEventListener('focus',()=>{if(actorId)verifyIdentity().catch(e=>{error.textContent=e.message;showRecovery();protect(Boolean(pendingWrite));});});
  (async () => { csrf = (await api('/api/auth/csrf')).csrf_token;
    products = (await api('/api/fulfillment/products')).products;
    const actor=await api('/api/auth/me');actorId=actor.id;actorRole=actor.role;storageBase=`system2-fulfillment:${actorId}`;ownStorageKey=storageBase+':'+key();storageKey=ownStorageKey;
    restorePending();
    await loadStores(); })()
    .catch(e => error.textContent = e.message)
    .finally(()=>{showRecovery();protect(Boolean(pendingWrite));});
})();

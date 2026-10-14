'use strict';
(() => {
  const titles = {products:'商品', stores:'門市', users:'帳號', policies:'門市商品政策'};
  const labels = {sku:'商品代碼',name:'名稱',base_unit:'基本單位',pack_size:'箱入數（件）',code:'門市代碼',username:'帳號',role:'角色',password:'密碼（修改時留空表示保留）',store_ids:'店長門市',store_id:'門市',product_id:'商品',active:'啟用',lead_days:'常規交期（天）',safety_stock:'安全庫存（件）',capacity:'常規容量（件）',absolute_large_qty:'大量訂購提醒門檻（件）',deviation_floor:'偏離提醒最低量（件）',deviation_multiplier:'偏離提醒倍數',confirmation_minutes:'確認有效時間（分鐘）',deduction_minutes:'待接單扣抵（分鐘）',supply_response_minutes:'接單回覆期限（分鐘）',receipt_minutes:'收貨期限（分鐘）',variance_hours:'差異期限（小時）',contact_minutes:'聯絡期限（分鐘）',manual_valid_days:'人工預測有效期（天）'};
  const policyKeys = ['lead_days','safety_stock','capacity','absolute_large_qty','deviation_floor','deviation_multiplier','confirmation_minutes','deduction_minutes','supply_response_minutes','receipt_minutes','variance_hours','contact_minutes','manual_valid_days'];
  const keys = {products:['sku','name','base_unit','pack_size','active'],stores:['code','name','active'],users:['username','role','password','store_ids','active'],policies:['store_id','product_id',...policyKeys,'active']};
  const defaults = {base_unit:'件',pack_size:1,active:true,role:'manager',lead_days:1,safety_stock:10,capacity:100,absolute_large_qty:100,deviation_floor:100,deviation_multiplier:3,confirmation_minutes:5,deduction_minutes:60,supply_response_minutes:60,receipt_minutes:60,variance_hours:24,contact_minutes:60,manual_valid_days:7};
  let catalogPage=1,catalogSequence=0,catalogLoading=false;
  let catalog, kind='products', editing=null, auditPage=1, saving=false;
  const status=document.querySelector('#admin-status'), form=document.querySelector('#admin-form');
  async function api(path,method='GET',body) {
    const headers={'Content-Type':'application/json'};
    if(method!=='GET') headers['X-CSRFToken']=(await (await fetch('/api/auth/csrf')).json()).csrf_token;
    const response=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok) {const failure=new Error(data.error?.message || '操作失敗');failure.details=data.error?.details;throw failure;}
    return data;
  }
  function option(select,value,label) {const o=document.createElement('option');o.value=value;o.textContent=label;select.append(o);}
  function edit(row=null) {
    editing=row; document.querySelector('#edit-title').textContent=(row?'修改':'新增')+titles[kind];
    const fields=document.querySelector('#admin-fields');fields.replaceChildren();
    for(const key of keys[kind]) {
      const label=document.createElement('label');label.textContent=labels[key];
      let input;
      if(['role','store_ids','store_id','product_id'].includes(key)) {
        input=document.createElement('select');input.multiple=key==='store_ids';
        if(key==='role') [['manager','店長'],['operator','接單人員'],['admin','管理者']].forEach(v=>option(input,...v));
        else {const list=key==='product_id'?catalog.products:catalog.stores;for(const r of list) option(input,r.id,`${r.code||r.sku} · ${r.name}${r.active?'':'（停用）'}`);}
      } else {input=document.createElement('input'); input.type=key==='active'?'checkbox':key==='password'?'password':key==='pack_size'||policyKeys.includes(key)?'number':'text';}
      input.name=key;
      if(key==='active') {input.checked=row?row.active:true;label.className='check-label';}
      else if(key==='store_ids') for(const o of input.options) o.selected=(row?.store_ids||[]).includes(Number(o.value));
      else input.value=row?.[key]??defaults[key]??'';
      if(input.type==='number') {input.min=['safety_stock','capacity'].includes(key)?0:1;input.max=['lead_days','manual_valid_days'].includes(key)?365:key==='variance_hours'?8760:1000000;input.step=1;}
      if(input.type==='password'){input.value='';input.autocomplete='new-password';input.minLength=8;input.maxLength=128;}
      if(row&&['sku','code','username','store_id','product_id'].includes(key)) input.disabled=true;
      if(key!=='password'&&key!=='active'&&key!=='store_ids')input.required=true;
      if(key==='password') {
        input.id='admin-password';
        const group=document.createElement('div');group.className='password-field';
        const toggle=document.createElement('button');toggle.type='button';toggle.className='password-toggle';
        toggle.dataset.passwordToggle=input.id;toggle.setAttribute('aria-controls',input.id);toggle.setAttribute('aria-pressed','false');toggle.textContent='顯示密碼';
        group.append(input,toggle);label.append(group);
      } else label.append(input);
      if(['store_ids','store_id','product_id'].includes(key) && !input.disabled) {
        const search=document.createElement('input');search.type='search';search.placeholder=key==='product_id'?'搜尋商品名稱／代碼':'搜尋門市名稱／代碼';search.setAttribute('aria-label',search.placeholder);
        let sequence=0;
        search.addEventListener('input',async()=>{const seq=++sequence;try{const data=await api(`/api/admin/lookups?kind=${key==='product_id'?'products':'stores'}&search=${encodeURIComponent(search.value)}`);if(seq!==sequence||saving)return;const retained=Array.from(input.selectedOptions,o=>({id:o.value,label:o.textContent}));input.replaceChildren();const ids=new Set();for(const r of [...retained,...data.rows])if(!ids.has(String(r.id))){ids.add(String(r.id));option(input,r.id,r.label);}for(const o of input.options)o.selected=retained.some(r=>String(r.id)===o.value);status.textContent=data.has_more?'符合超過50筆，請輸入更完整名稱或代碼。':'';}catch(e){if(seq===sequence)status.textContent=e.message;}});
        label.append(search);
      }
      fields.append(label);
    }
  }
  function render() {
    document.querySelector('#list-title').textContent=titles[kind];
    document.querySelectorAll('[data-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.kind===kind)));
    const list=document.querySelector('#admin-list');list.replaceChildren();
    for(const row of catalog[kind]) {
      const button=document.createElement('button');button.type='button';button.className='admin-row';
      const store=catalog.stores.find(s=>s.id===row.store_id), product=catalog.products.find(p=>p.id===row.product_id);
      button.textContent=kind==='policies'?`${store?.code} · ${product?.name} · 政策 v${row.version}`:`${row.sku||row.code||row.username} · ${row.name||({manager:'店長',operator:'接單人員',admin:'管理者'}[row.role])}${row.active?'':'（停用）'}`;
      button.addEventListener('click',()=>{if(!saving)edit(row);});list.append(button);
    }
    edit();
  }
  async function refresh() {
    catalogLoading=true;
    document.querySelector('#admin-list').replaceChildren();
    document.querySelector('#admin-fields').replaceChildren();
    editing=null;
    const seq=++catalogSequence;const result=await api(`/api/admin/catalog?kind=${kind}&page=${catalogPage}&search=${encodeURIComponent(document.querySelector('#catalog-search input').value)}`);if(seq!==catalogSequence)return;catalog=result;render();document.querySelector('#catalog-prev').disabled=catalogPage<=1;document.querySelector('#catalog-next').disabled=!catalog.has_next;document.querySelector('#catalog-page').textContent=`第 ${catalogPage} 頁`;
    catalogLoading=false;
    for(const selector of ['#audit-filter [name=store_id]','#cycles-form [name=store_id]']) {
      const select=document.querySelector(selector), previous=select.value;
      select.replaceChildren();if(selector.startsWith('#audit-filter'))option(select,'','全部');
      for(const store of catalog.stores)option(select,store.id,`${store.code}${store.active?'':'（停用）'}`);
      if(Array.from(select.options).some(o=>o.value===previous))select.value=previous;
    }
  }
  document.querySelectorAll('[data-kind]').forEach(b=>b.addEventListener('click',()=>{if(saving)return;kind=b.dataset.kind;catalogPage=1;document.querySelector('#catalog-search input').value='';refresh().catch(e=>status.textContent=e.message);}));
  document.querySelector('#new-record').addEventListener('click',()=>{if(!saving)edit();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(saving||catalogLoading)return;
    const data={};for(const key of keys[kind]) {const el=form.elements[key];data[key]=key==='active'?el.checked:key==='store_ids'?Array.from(el.selectedOptions,o=>Number(o.value)):el.type==='number'||['store_id','product_id'].includes(key)?Number(el.value):el.value;}
    if(editing)data.revision=editing.revision;
    const controls=Array.from(document.querySelectorAll('#admin-form input, #admin-form select, #admin-form button, [data-kind], #new-record, #admin-list button, #catalog-search input, #catalog-search button, #catalog-prev, #catalog-next'));
    const previousDisabled=controls.map(el=>el.disabled);
    saving=true;controls.forEach(el=>el.disabled=true);
    try {await api(`/api/admin/${kind}${editing?'/'+editing.id:''}`,editing?'PATCH':'POST',data);await refresh();status.textContent='設定已儲存；請重新產生補貨建議。';}catch(e){status.replaceChildren(document.createTextNode(e.message));for(const blocker of e.details?.blockers||[]){const link=document.createElement('a');link.href=blocker.url;link.textContent=' · '+blocker.reason;status.append(link);}}finally{saving=false;controls.forEach((el,index)=>el.disabled=previousDisabled[index]);}
  });
  document.querySelector('#catalog-search').addEventListener('submit',e=>{e.preventDefault();if(saving)return;catalogPage=1;refresh().catch(e=>status.textContent=e.message);});
  for(const [id,delta] of [['catalog-prev',-1],['catalog-next',1]])document.getElementById(id).addEventListener('click',()=>{if(saving)return;catalogPage+=delta;refresh().catch(e=>status.textContent=e.message);});
  const clock=document.querySelector('#clock-form');
  const cycles=document.querySelector('#cycles-form');
  cycles.addEventListener('submit',async event=>{event.preventDefault();const button=cycles.querySelector('button');button.disabled=true;try{const data=await api('/api/admin/cycles/prepare','POST',{store_id:Number(cycles.elements.store_id.value)});status.textContent=`本輪配送已備妥，新增 ${data.added} 個輪次。`;await refresh();}catch(e){status.textContent=e.message;}finally{button.disabled=false;}});
  if(clock)clock.addEventListener('submit',async event=>{event.preventDefault();const button=clock.querySelector('button');button.disabled=true;try{await api('/api/admin/clock','POST',{time:clock.elements.time.value+':00+08:00',paused:clock.elements.paused.checked});location.reload();}catch(e){status.textContent=e.message;}finally{button.disabled=false;}});
  async function audit() {
    const query=new URLSearchParams(new FormData(document.querySelector('#audit-filter')));query.set('page',auditPage);
    const data=await api('/api/admin/audit?'+query);const list=document.querySelector('#audit-list');list.replaceChildren();
    for(const row of data.events){const d=document.createElement('details'),s=document.createElement('summary'),p=document.createElement('pre');s.textContent=`${new Date(row.business_time).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})} · ${row.action} · ${row.entity}`;p.textContent=JSON.stringify(row,null,2);d.append(s,p);list.append(d);}
    if(!data.events.length)list.textContent='沒有符合條件的紀錄。';document.querySelector('#audit-next').hidden=!data.has_next;
  }
  document.querySelector('#audit-filter').addEventListener('submit',event=>{event.preventDefault();auditPage=1;audit().catch(e=>status.textContent=e.message);});
  document.querySelector('#audit-next').addEventListener('click',()=>{auditPage++;audit().catch(e=>status.textContent=e.message);});
  async function start(){await refresh();if(clock){const data=await api('/api/admin/clock');const parts=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(data.time));clock.elements.time.value=parts.replace(' ','T');}await audit();}
  start().catch(e=>status.textContent=e.message);
})();

'use strict';
window.BForecastControls = ({api, refresh, context, work}) => {
  const container = document.getElementById('forecast-options');
  const node = (tag, text) => { const el=document.createElement(tag); el.textContent=text; return el; };
  const local = value => new Date(value).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false});
  const field = (parent, label, name, value='', kind='text') => {
    const id='choice-'+parent.closest('[data-forecast-product]').dataset.forecastProduct+'-'+name;
    const lab=node('label',label); lab.htmlFor=id;
    const input=node(kind==='textarea'?'textarea':'input',''); input.id=id; input.dataset.field=name;
    if(kind!=='textarea') input.type=kind;
    input.value=value; if(kind==='textarea') {input.rows=2; input.maxLength=500;}
    parent.append(lab,input); return input;
  };
  const get = (card,name) => card.querySelector('[data-field="'+name+'"]');
  const integer = value => {
    if(!/^(0|[1-9][0-9]*)$/.test(value) || Number(value)>1000000) throw new Error('數量須為0–1000000整數件數');
    return Number(value);
  };
  const readSelection = () => {
    const values={modes:{},special_needs:{},direct_quantities:{},manual_confirmations:[]};
    for(const card of container.querySelectorAll('[data-forecast-product]')) {
      const id=Number(card.dataset.forecastProduct),mode=get(card,'mode').value;
      values.modes[id]=mode;
      if(mode==='manual' && get(card,'confirmed').checked) values.manual_confirmations.push(id);
      if(mode==='direct') {
        values.special_needs[id]={need_date:get(card,'need-date').value,need_qty:integer(get(card,'need-qty').value),
          reason:get(card,'special-reason').value,arrangement:get(card,'arrangement').value};
        values.direct_quantities[id]=integer(get(card,'direct-qty').value);
      }
    }
    return values;
  };
  const renderOptions = products => {
    const old=new Map([...container.querySelectorAll('[data-forecast-product]')].map(card=>[
      card.dataset.forecastProduct,{mode:get(card,'mode').value,
        direct:Object.fromEntries(['need-date','need-qty','special-reason','arrangement','direct-qty'].map(name=>[name,get(card,name).value]))}]));
    container.replaceChildren();
    for(const product of products) {
      const card=node('article',''); card.className='run-item'; card.dataset.forecastProduct=product.product_id;
      card.append(node('h3',product.sku+' '+product.name+' · 箱入'+product.pack_size+'件'));
      const label=node('label','本次計算方式'),select=node('select','');
      select.id='choice-'+product.product_id+'-mode'; select.dataset.field='mode'; label.htmlFor=select.id;
      for(const [value,title] of [['model','七日模型（資料不足則無有效建議）'],['manual','人工預測日需求'],['direct','特殊直接訂購（無有效模型）']]) {
        const opt=node('option',title); opt.value=value; opt.disabled=value==='direct'&&product.forecast_valid; select.append(opt);
      }
      const previous=old.get(String(product.product_id));
      select.value=previous?.mode||'model';
      if(select.selectedOptions[0]?.disabled) select.value='model';
      card.append(label,select);
      const manual=node('div',''); manual.className='forecast-manual'; card.append(manual);
      const ref=product.latest_manual_forecast;
      manual.append(node('p',ref ? '最近人工值 '+ref.daily_demand+'件／日；理由：'+ref.reason+
        '；設定者id '+ref.actor_id+'；設定 '+local(ref.created_at)+'；有效至 '+local(ref.valid_until)+
        (ref.expired?'（已過期，只供參考）':'（有效，仍須本輪主動確認）') : '尚無人工預測；保存新值後才能使用。'));
      field(manual,'人工預測日需求（非最終訂量，最多三位小數）','daily-demand',ref?.daily_demand??'').inputMode='decimal';
      field(manual,'人工預測理由','manual-reason',ref?.reason??'','textarea');
      const save=node('button','保存新人工預測'); save.type='button'; save.dataset.action='save-manual';
      save.addEventListener('click',()=>work(async()=>{
        await api('/api/replenishment/manual-forecasts',{store_id:context().store_id,product_id:product.product_id,
          expected_version:context().store_version,daily_demand:get(card,'daily-demand').value,reason:get(card,'manual-reason').value});
        await refresh('人工預測已保存，舊快照不變；請重新產生並確認本輪人工值。');
      })); manual.append(save);
      const checked=field(manual,'我已核對本輪人工值、理由與期限（不沿用舊勾選）','confirmed','','checkbox');
      checked.checked=false;
      card.append(manual);
      const direct=node('div',''); direct.className='forecast-direct'; card.append(direct);
      direct.append(node('p','不填人工日需求。需求量只作活動說明，實際候選訂量另列一次；不自動相加。'));
      const draft=previous?.direct??{};
      field(direct,'特殊需求日期','need-date',draft['need-date']??'','date');
      field(direct,'活動／團體需求量（件）','need-qty',draft['need-qty']??'','number').min=1;
      field(direct,'具體特殊需求理由','special-reason',draft['special-reason']??'','textarea');
      field(direct,'存放／直接交付安排','arrangement',draft['arrangement']??'','textarea').maxLength=200;
      field(direct,'本次直接候選訂量（件，不是日需求）','direct-qty',draft['direct-qty']??'','number').min=1;
      card.append(direct);
      const toggle=()=>{manual.hidden=select.value!=='manual';direct.hidden=select.value!=='direct';checked.checked=false;};
      select.addEventListener('change',toggle); toggle();
      const history=node('details',''); card.append(history); history.append(node('summary','歷史銷售註記（僅資訊，不是本次活動）'));
      const day=node('select',''); day.id='choice-'+product.product_id+'-historical-day'; day.dataset.field='historical-day';
      const dayLabel=node('label','選擇既有銷售日期'); dayLabel.htmlFor=day.id;
      for(const sales of product.sales) {const opt=node('option',sales.date+' · '+sales.sold_qty+'件'); opt.value=sales.date;day.append(opt);}
      history.append(dayLabel,day);
      const note=field(history,'歷史註記（清空可移除；不修改銷量、不補缺檔）','historical-note','','textarea');
      const chosen=()=>product.sales.find(s=>s.date===day.value);
      const fill=()=>{note.value=chosen()?.event_note??'';}; day.addEventListener('change',fill); fill();
      const annotate=node('button','保存歷史註記'); annotate.type='button'; annotate.dataset.action='save-event';
      annotate.addEventListener('click',()=>work(async()=>{
        if(!chosen()) throw new Error('此商品沒有可註記的銷售日期');
        await api('/api/sales/events',{store_id:context().store_id,product_id:product.product_id,
          business_date:day.value,note:note.value,expected_version:context().store_version,
          expected_sales_version:chosen().sales_version});
        await refresh('歷史註記已保存；未改銷量或庫存，請產生新快照核對。');
      })); history.append(annotate); card.append(history); container.append(card);
    }
  };
  const decorateResult = (card,item) => {
    if(item.mode==='manual') {
      const ref=item.manual_forecast;
      card.append(node('p','人工日需求 '+ref.daily_demand+'；'+ref.reason+'；設定者id '+ref.actor_id+
        '；設定 '+local(ref.created_at)+'；有效至 '+local(ref.valid_until)));
      const label=node('label','本次試算已核對人工值與期限（不代替正式訂購確認）');
      const input=node('input',''); input.type='checkbox'; input.dataset.manualConfirmId=item.product_id;
      input.id='evaluate-manual-'+item.product_id; label.htmlFor=input.id; input.checked=false;
      card.append(label,input);
    }
    if(item.mode==='direct') {
      const bound=item.warnings.find(w=>w.code==='DIRECT_ORDER')?.details.conservative_capacity;
      card.append(node('p','特殊直接訂購：無法計算模型建議、無法評估需求缺口；不提供精確需求曲線。'));
      if(bound) card.append(node('p','保守容量檢查（不扣銷售）：現貨 '+bound.h+'＋本次候選 '+bound.candidate_qty+
        '＋可能未結到貨 '+bound.total_open_qty+'＝'+bound.upper_bound_with_pending+'件；常規容量 '+bound.capacity+
        '。已承諾來源版上界 '+bound.upper_bound_committed+'件；沒有縮減輸入數量。'));
      card.append(node('p','本次特殊需求：'+JSON.stringify(item.input_snapshot.special_need)));
    }
  };
  const resultConfirmations = () => [...document.querySelectorAll('[data-manual-confirm-id]:checked')].map(el=>Number(el.dataset.manualConfirmId));
  const clearResultConfirmations = () => document.querySelectorAll('[data-manual-confirm-id]').forEach(el=>{el.checked=false;});
  return {renderOptions,readSelection,decorateResult,resultConfirmations,clearResultConfirmations};
};

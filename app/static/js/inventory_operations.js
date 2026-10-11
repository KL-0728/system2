'use strict';
window.BInventoryOperations=({getStatus,submit,fillCount,say,isBusy})=>{
  const $=id=>document.getElementById(id);
  const node=(tag,text)=>{const el=document.createElement(tag);el.textContent=text;return el;};
  const time=v=>new Date(v).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false});
  let task=null,last;
  const integer=id=>{
    const v=$(id).value;
    if(!/^(0|[1-9][0-9]*)$/.test(v)||Number(v)>1000000)throw new Error('數量須為0–1000000整數件數');
    return Number(v);
  };
  const resetTask=()=>{
    task=null;$('reconciliation-target').textContent='一般盤點／修訂';
    $('cancel-reconciliation').hidden=true;
  };
  const effect=()=>{
    const status=getStatus();
    const item=status?.items.find(i=>i.product_id===Number($('movement-product').value));
    if(!item)return;
    const qty=Number($('movement-qty').value||0);
    $('movement-impact').textContent='目前帳面總量 '+item.physical_book+'、不可售 '+item.unsellable_book+
      '；本次兩者各減 '+qty+' → 總量 '+(item.physical_book-qty)+'、不可售 '+(item.unsellable_book-qty)+
      '；有效時可售 H 維持 '+(item.h??'不可用')+'。以最新庫存版本 '+item.inventory_version+' 核對。';
  };
  const render=(status,tasks,movements)=>{
    const selected=$('movement-product').value;
    $('movement-product').replaceChildren(...status.items.map(item=>{
      const opt=node('option',item.sku+' '+item.name+' · 不可售'+item.unsellable_book+'件');
      opt.value=item.product_id;return opt;
    }));
    if([...$('movement-product').options].some(o=>o.value===selected))$('movement-product').value=selected;
    if(!$('movement-at').value)$('movement-at').value=status.business_now;
    if(!$('movement-source').value)$('movement-source').value=crypto.randomUUID();
    effect();
    $('reconciliation-list').replaceChildren();
    for(const item of tasks.items){
      const card=node('article','');card.className='operation-card';card.dataset.reconciliationId=item.id;
      card.append(node('h3','#'+item.id+' '+item.sku+' '+item.name+' · '+(item.status==='OPEN'?'待對帳':'已處理')));
      card.append(node('p',item.reason));
      card.append(node('p','負責角色：店長；期限 '+(item.due_at?time(item.due_at):'舊案件未保存期限，須核對')+
        (item.overdue?'（已逾期，仍須實際處理）':'')));
      card.append(node('p','來源 '+item.source_type+' / '+item.source_id+'；案件版本 '+item.version+'；建立 '+time(item.created_at)));
      if(item.status==='OPEN'){
        card.append(node('p','先更正銷售／補齊日常入帳，或核對有效21:00盤點；只勾選不能解除阻擋。'));
        const button=node('button','以21:00盤點處理此對帳');button.type='button';
        button.dataset.taskAction='count';
        button.addEventListener('click',()=>{
          if(isBusy())return;
          $('count-product').value=item.product_id;fillCount();
          task=item;$('reconciliation-target').textContent='處理對帳 #'+item.id+'；'+item.sku+'；案件版本 '+item.version;
          $('cancel-reconciliation').hidden=false;
          $('count-section').scrollIntoView({behavior:'smooth',block:'start'});
          $('count-reason').focus();
        });card.append(button);
      }else{
        card.append(node('p','完成者id '+item.resolved_by+'；完成 '+time(item.resolved_at)));
        const details=node('details','');details.append(node('summary','原處理紀錄（唯讀）'),
          node('pre',JSON.stringify(item.resolution,null,2)));card.append(details);
      }
      $('reconciliation-list').append(card);
    }
    if(!tasks.items.length)$('reconciliation-list').append(node('p','目前沒有對帳案件。'));
    $('movement-list').replaceChildren();
    for(const m of movements.items){
      const card=node('article','');card.className='operation-card';card.dataset.movementId=m.id;
      card.append(node('h3','#'+m.id+' '+m.sku+' '+m.source_type));
      card.append(node('p','總量差額 '+m.physical_delta+'；不可售差額 '+m.unsellable_delta+'；庫存版本 '+m.inventory_version));
      card.append(node('p',m.reason));
      card.append(node('p','來源 '+m.source_id+'；操作人id '+m.actor_id+'；發生 '+time(m.occurred_at)+'；入帳 '+time(m.applied_at)));
      $('movement-list').append(card);
    }
    if(!movements.items.length)$('movement-list').append(node('p','目前沒有庫存異動。'));
    if(task&&!tasks.items.some(t=>t.id===task.id&&t.status==='OPEN'))resetTask();
  };
  $('movement-form').addEventListener('input',effect);
  $('movement-form').addEventListener('change',effect);
  $('movement-form').addEventListener('submit',event=>{
    event.preventDefault();if(isBusy())return;
    try{
      const status=getStatus(),item=status.items.find(i=>i.product_id===Number($('movement-product').value));
      const qty=integer('movement-qty');if(qty<1)throw new Error('移出數量須為正整數');
      submit({kind:'movement',url: $('movement-kind').value==='disposal'?'/api/inventory/disposals':'/api/inventory/returns',
        body:{store_id:status.store_id,product_id:item.product_id,qty,source_id:$('movement-source').value,
          occurred_at:$('movement-at').value,reason:$('movement-reason').value,expected_version:item.inventory_version}});
    }catch(error){say(error.message,true);}
  });
  $('repeat-movement').addEventListener('click',()=>{if(last)submit(last);});
  $('cancel-reconciliation').addEventListener('click',resetTask);
  $('count-product').addEventListener('change',resetTask);
  const countRecord=body=>task?{kind:'reconciliation',url:'/api/inventory/reconciliations/'+task.id+'/resolve',
    body:{...body,expected_task_version:task.version}}:{kind:'count',url:'/api/inventory/counts',body};
  const success=(record,result)=>{
    if(record.kind==='movement'){
      last=record;$('repeat-movement').hidden=false;
      $('movement-source').value=crypto.randomUUID();$('movement-at').value=getStatus().business_now;
      return (result.replayed?'原異動已確認，沒有再次扣庫存':'損壞品異動已入帳')+
        '；目前帳面總量 '+result.physical_book+'；不可售 '+result.unsellable_book+'；來源異動 #'+result.movement_id+'。';
    }
    if(record.kind==='reconciliation')resetTask();
    return null;
  };
  const validPending=value=>
    value.kind==='movement'&&['/api/inventory/disposals','/api/inventory/returns'].includes(value.url)||
    value.kind==='reconciliation'&&/^\/api\/inventory\/reconciliations\/[1-9][0-9]*\/resolve$/.test(value.url);
  return {render,countRecord,success,validPending};
};

(() => {
  const root=document.getElementById('draft-tools');if(!root)return;
  root.querySelectorAll('[data-draft-action]').forEach(button=>button.onclick=async()=>{
    const status=document.getElementById('draft-tools-status');
    const key=`system2-ordering:${root.dataset.actor}:${root.dataset.store}`;
    const cached=JSON.parse(sessionStorage.getItem(key)||'null');
    if(cached?.pendingSubmission){status.textContent='送單結果未確認，請先查詢原請求結果。';return;}
    if(document.getElementById('save-button')?.disabled){status.textContent='請先完成目前的儲存或預覽操作。';return;}
    const controls=Array.from(document.querySelectorAll('#draft-tools button, .product-row input,.product-row select,.product-row textarea,.product-row button,#save-button,#preview-button,#back-button,#submit-button'));
    const previous=controls.map(el=>el.disabled);controls.forEach(el=>el.disabled=true);
    try{
      const draft=await (await fetch(`/api/order-drafts/${root.dataset.id}`)).json();
      const csrf=await (await fetch('/api/auth/csrf')).json();
      const response=await fetch(`/api/order-drafts/${root.dataset.id}/${button.dataset.draftAction}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf.csrf_token},body:JSON.stringify({expected_version:draft.version})});
      const result=await response.json();if(!response.ok)throw Error(result.error?.message||'操作失敗');
      sessionStorage.removeItem(key);
      location.href=button.dataset.draftAction==='rebuild'?`/store/ordering?store_id=${root.dataset.store}&draft_id=${result.id}`:`/?store_id=${root.dataset.store}`;
    }catch(e){status.textContent=e.message;}finally{controls.forEach((el,index)=>el.disabled=previous[index]);}
  });
})();

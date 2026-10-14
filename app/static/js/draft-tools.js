(() => {
  'use strict';
  const root = document.getElementById('draft-tools');
  if (!root) return;
  const status = document.getElementById('draft-tools-status');
  const key = `system2-ordering:${root.dataset.actor}:${root.dataset.store}`;
  let operating = false;
  function cached() {
    try { return JSON.parse(sessionStorage.getItem(key) || 'null'); }
    catch (_) { throw Error('本機草稿無法解析，請保留資料並聯絡維護者。'); }
  }
  function belongs(saved) { return saved && String(saved.draftId) === root.dataset.id; }
  function conflict() {
    status.textContent = '草稿已有其他版本，輸入與暫存已保留。請先比對，再決定是否放棄本機內容。';
    const compare = document.createElement('a');
    compare.href = location.href; compare.target = '_blank'; compare.rel = 'noopener';
    compare.textContent = '另開視窗比對伺服器草稿'; status.append(compare);
    const reload = document.createElement('button'); reload.type = 'button';
    reload.textContent = '放棄本機內容並重載';
    reload.onclick = () => {
      if (!window.confirm('確定放棄目前未儲存的數量、備註與特殊需求，載入伺服器草稿？')) return;
      if (belongs(cached())) sessionStorage.removeItem(key);
      location.reload();
    };
    status.append(reload);
  }
  async function execute(action, choice) {
    if (operating) return;
    operating = true;
    const controls = Array.from(document.querySelectorAll('#draft-tools button, .product-row input,.product-row select,.product-row textarea,.product-row button,#save-button,#preview-button,#back-button,#submit-button'));
    const previous = controls.map(el => el.disabled);
    try {
      if (choice === 'save' && !await window.system2DraftEditor.save()) {
        status.textContent = '草稿未儲存，操作已停止；請處理儲存錯誤，輸入仍保留。'; return;
      }
      controls.forEach(el => el.disabled = true);
      const csrfResponse = await fetch('/api/auth/csrf');
      if (!csrfResponse.ok) throw Error('無法取得安全驗證，請重新登入原帳號後重試。');
      const csrf = await csrfResponse.json();
      const response = await fetch(`/api/order-drafts/${root.dataset.id}/${action}`, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf.csrf_token},
        body: JSON.stringify({expected_version: Number(root.dataset.version)}),
      });
      const result = await response.json();
      if (response.status === 409) { conflict(); return; }
      if (!response.ok) throw Error(result.error?.message || '操作失敗');
      if (belongs(cached())) sessionStorage.removeItem(key);
      location.href = action === 'rebuild' ? `/store/ordering?store_id=${root.dataset.store}&draft_id=${result.id}` : `/?store_id=${root.dataset.store}`;
    } catch (e) { status.textContent = `${e.message}。輸入與暫存仍保留，可重試或查詢原草稿。`; }
    finally { operating = false; controls.forEach((el, index) => el.disabled = previous[index]); }
  }
  root.querySelectorAll('[data-draft-action]').forEach(button => button.onclick = () => {
    try {
      const saved = cached(), controller = window.system2DraftEditor;
      const editor = controller?.available && !controller.available() ? null : controller;
      if (operating || editor?.busy() || document.getElementById('save-button')?.disabled) {
        status.textContent = '請先完成目前的儲存、預覽或送單結果查詢。'; return;
      }
      if (saved?.pendingSubmission) { status.textContent = '送單結果未確認，請先查詢原請求結果。'; return; }
      const action = button.dataset.draftAction;
      const dirty = editor?.dirty() || (belongs(saved) && !editor);
      status.textContent = dirty ? '有未儲存的修改。儲存後可保留目前數量、備註及特殊需求；放棄則僅使用伺服器已儲存內容。' : '請確認使用目前已儲存的草稿內容。';
      const choices = dirty ? [['save', '儲存後繼續'], ['discard', '放棄未儲存修改並繼續']] : [['saved', '使用已儲存內容繼續']];
      for (const [choice, label] of choices) {
        if (choice === 'save' && !editor) continue;
        const control = document.createElement('button'); control.type = 'button'; control.textContent = label;
        control.onclick = () => execute(action, choice); status.append(control);
      }
      const cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = '取消';
      cancel.onclick = () => { status.textContent = '已取消，輸入仍保留。'; }; status.append(cancel);
    } catch (e) { status.textContent = e.message; }
  });
})();

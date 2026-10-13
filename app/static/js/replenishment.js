'use strict';
(() => {
  const root = document.getElementById('replenishment-app');
  if (!root) return;
  const $ = id => document.getElementById(id), storeId = Number(root.dataset.storeId);
  let context, run, csrf, busy = false;
  let modeControls;
  const node = (tag, text) => { const el = document.createElement(tag); el.textContent = text; return el; };
  const local = value => new Date(value).toLocaleString('zh-TW', {timeZone: 'Asia/Taipei', hour12: false});
  // Format only the visible metrics; keep run data at its original precision.
  const decimalFormat = new Intl.NumberFormat('zh-TW', {
    minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false
  });
  const displayDecimal = (value, fallback) => value == null ? fallback : decimalFormat.format(value);
  const say = (text, error = false) => { $('run-message').textContent = text; $('run-message').classList.toggle('error', error); };
  const api = async (url, data) => {
    const response = await fetch(url, data ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify(data)} : {});
    const result = await response.json();
    if (!response.ok) throw new Error((result.error?.code || response.status) + '：' + (result.error?.message || '操作失敗'));
    return result;
  };
  const lock = () => {
    root.querySelectorAll('button, select, input, textarea').forEach(el => { el.disabled = busy; });
    $('generate-run').disabled = busy || !context?.can_generate || !$('run-cycle').value;
    $('evaluate-run').disabled = busy || !run || !context?.can_generate || !$('run-cycle').value;
    $('load-run').disabled = busy || !$('saved-run').value;
    root.querySelectorAll('input[data-unavailable]').forEach(el => { el.disabled = true; });
  };
  const loadContext = async () => {
    context = await api('/api/replenishment/context?store_id=' + storeId);
    $('run-window').textContent = '訂購基準 ' + local(context.baseline_at) + '；本輪截止 ' + local(context.cutoff_at) + '（台北時間）';
    $('run-provider').textContent = context.source_provider.test_only ?
      '模組開發：使用受控測試來源，尚未驗證真實履約整合。' :
      context.source_provider.name === '尚未接入' ? '供貨資料目前無法取得，請聯絡管理者。' : '計算會納入門市待接單與供貨收貨紀錄。';
    const old = $('run-cycle').value;
    $('run-cycle').replaceChildren();
    for (const cycle of context.cycles) {
      const option = node('option', local(cycle.arrival_at) + ' · ' + cycle.lead_days + '天後到貨');
      option.value = cycle.id; $('run-cycle').append(option);
    }
    if ([...$('run-cycle').options].some(o => o.value === old)) $('run-cycle').value = old;
    $('saved-run').replaceChildren();
    for (const saved of context.runs) {
      const option = node('option', '#' + saved.id + ' · ' + local(saved.actual_generated_at));
      option.value = saved.id; $('saved-run').append(option);
    }
    modeControls.renderOptions(context.products);
    if (!context.can_generate) say('目前不在21:00–22:00訂購時段，可查看歷次建議；請在本輪開放後重新計算。');
    else if (!context.cycles.length) say('本輪尚無配送輪次，請聯絡管理者準備今日配送安排。', true);
  };
  const table = (headers, rows) => {
    const wrap = node('div', ''); wrap.className = 'run-scroll';
    const t = node('table', ''), head = node('thead', ''), tr = node('tr', '');
    headers.forEach(text => tr.append(node('th', text))); head.append(tr); t.append(head);
    const body = node('tbody', '');
    for (const row of rows) { const line = node('tr', ''); row.forEach(value => line.append(node('td', value))); body.append(line); }
    t.append(body); wrap.append(t); return wrap;
  };
  const details = (card, title, child) => {
    const d = node('details', ''); d.append(node('summary', title), child); card.append(d);
  };
  const render = (value, evaluation = false) => {
    run = value; $('run-result').hidden = false;
    $('run-title').textContent = '補貨建議 #' + run.run_id;
    $('run-metadata').textContent = 'B ' + local(run.baseline_at) + '；產生 ' + local(run.actual_generated_at) +
      '；資料涵蓋至 ' + local(run.data_through_at) + '；風險評估 ' + local(run.risk_evaluated_at) +
      '；保護至 ' + local(run.protection_end) + '；門市版本 ' + run.store_version +
      '；模型 ' + run.model_version + '／警示 v' + run.warning_version;
    $('run-view-kind').textContent = evaluation ? '目前為試算結果；原保存建議維持不變。' : '目前顯示已保存的建議。';
    $('run-items').replaceChildren();
    for (const item of run.items) {
      const card = node('article', ''); card.className = 'run-item'; card.dataset.sku = item.input_snapshot.sku;
      card.append(node('h3', item.input_snapshot.product_name + ' · ' + item.input_snapshot.sku + ' · 箱入 ' + item.pack_size + '件'));
      const sums = {U: 0, C: 0, RISK: 0}; item.sources.forEach(s => { sums[s.bucket] += s.quantity; });
      const metrics = node('div', ''); metrics.className = 'run-metrics';
      for (const [label, value] of [['可用現貨', item.h ?? '不可用'], ['預估日銷量', displayDecimal(item.mu, item.mode==='direct'?'無法計算':'無有效預測')],
        ['目標庫存', displayDecimal(item.target_stock, '無法計算')], ['整箱前需求', displayDecimal(item.raw_qty, '無法計算')],
        ['建議量', item.suggested_qty === null ? (item.mode==='direct'?'無法計算':'無有效建議') : item.suggested_qty + '件'],
        ['待接單／已承諾未到貨', sums.U + '／' + sums.C], ['未扣抵風險量', sums.RISK]]) {
        const cell = node('div', label); cell.className = 'run-metric'; cell.append(node('strong', String(value))); metrics.append(cell);
      }
      card.append(metrics, node('p', '供貨交期 ' + item.lead_days + ' 天 · 安全庫存 ' + item.safety_stock + ' 件 · 常規容量 ' + item.capacity + ' 件'));
      const warnings = node('ul', '');
      for (const warning of item.warnings) {
        const li = node('li', warning.message);
        li.dataset.warningCode = warning.code;
        li.dataset.warningLevel = warning.level;
        li.className = 'run-warning ' + warning.level; warnings.append(li);
      }
      card.append(warnings);
      const input = node('input', ''); input.type = 'number'; input.min = 0; input.max = 1000000; input.step = 1;
      input.value = item.suggested_qty ?? (item.mode==='direct' ? item.warnings.find(w=>w.code==='DIRECT_ORDER')?.details.conservative_capacity.candidate_qty ?? '' : ''); input.dataset.productId = item.product_id; input.id = 'final-' + item.product_id;
      if (item.mode === 'unavailable') input.dataset.unavailable = 'true';
      const label = node('label', item.mode === 'unavailable' ? '無有效建議：請先修正資料，本次不得試訂此品項' : '試算最終量（件）');
      label.htmlFor = input.id; card.append(label, input);
      modeControls.decorateResult(card,item);
      const formula = item.mode==='direct' ? '直接指定候選訂量；μ、S、原始量、建議量均無法計算。保守容量不扣預估銷售；活動需求量不再加一次。' :
        item.mode==='unavailable' ? '缺少有效庫存或預測，無有效計算建議；勾選不能解除庫存阻擋。' :
        'R=1；P=1+L；μ='+ (item.mode==='manual'?'本輪已核對的人工日需求':'七日銷售總和÷7') +
        '；S=μ×P+SS；Q原始=max(0,S−H−U−C)；Q建議=向上取整箱。缺檔、缺貨或未正常營業不補零；RISK不扣需求。';
      details(card, '計算公式與參數', node('p', formula));
      details(card, '七日銷售與入帳來源', table(['營業日', '銷售', '正常營業', '缺貨', '模式／入帳來源'],
        item.input_snapshot.sales.map(s => [s.date, s.sold_qty ?? '缺檔', s.is_open === null ? '未知' : s.is_open ? '是' : '否',
          s.was_stockout === null ? '未知' : s.was_stockout ? '是' : '否', (s.import_mode ?? '無') + '／' + (s.movement_id ?? '未入帳')])));
      details(card, '未結來源明細', table(['來源', '分桶', '數量', 'ETA', '扣抵期限', '爭議'],
        item.sources.map(s => [s.source_type + ':' + s.source_id, s.bucket, s.quantity, local(s.eta),
          s.deduction_expires_at ? local(s.deduction_expires_at) : '無', s.disputed ? '是' : '否'])));
      for (const [title, curve] of [['已承諾＋本次試訂', item.timeline_committed], ['已承諾＋待接單／風險＋本次試訂', item.timeline_with_pending]]) {
        const child = curve.length ? table(['時間', '預測銷售', '到貨', '期末可售', '失去銷量', '超容量'],
          curve.map(p => [local(p.at), p.demand, p.receipts.map(r => r.source_id + ' ' + r.bucket + ' ' + r.qty + (r.conditional ? '（尚未確定）' : '')).join('；') || '無',
            p.ending_stock, p.stockout_qty, p.capacity_exceeded ? '是' : '否'])) : node('p', '無有效預測，無法產生精確需求曲線。');
        details(card, title, child);
      }
      details(card, '盤點基準／缺口及政策參數', node('pre', JSON.stringify({
        integrity: item.input_snapshot.integrity, policy_parameters: item.input_snapshot.policy_parameters}, null, 2)));
      $('run-items').append(card);
    }
  };
  const work = async fn => {
    busy = true; lock(); say('處理中…');
    try { await fn(); } catch (error) { say(error.message, true); }
    finally { busy = false; lock(); }
  };
  $('generate-run').addEventListener('click', () => work(async () => {
    const result = await api('/api/replenishment/runs', {store_id: storeId, cycle_id: Number($('run-cycle').value),
      expected_version: context.store_version,...modeControls.readSelection()});
    render(result); await loadContext(); $('saved-run').value = result.run_id;
    say('補貨建議已保存 #' + result.run_id + '，請進入訂購工作台核對並送出。');
  }));
  $('load-run').addEventListener('click', () => work(async () => {
    render(await api('/api/replenishment/runs/' + $('saved-run').value + '?store_id=' + storeId));
    say('已讀取當時建議；資料與提醒維持產生時的內容。');
  }));
  $('refresh-run-context').addEventListener('click', () => work(async () => { await loadContext(); if (context.can_generate) say('門市版本已重新核對。'); }));
  $('evaluate-run').addEventListener('click', () => work(async () => {
    const quantities = {};
    root.querySelectorAll('input[data-product-id]').forEach(input => {
      if (input.dataset.unavailable) { quantities[input.dataset.productId] = 0; return; }
      if (!/^(0|[1-9][0-9]*)$/.test(input.value) || Number(input.value) > 1000000) throw new Error('最終量須為0–1000000的整數件數');
      quantities[input.dataset.productId] = Number(input.value);
    });
    const result = await api('/api/replenishment/runs/' + run.run_id + '/evaluate', {
      store_id: storeId, cycle_id: Number($('run-cycle').value), final_quantities: quantities,
      manual_confirmations:modeControls.resultConfirmations()});
    render(result, true);
    // Retain the actual final inputs; suggestions are explanatory and never replace them.
    root.querySelectorAll('input[data-product-id]').forEach(input => {
      if (!input.dataset.unavailable) input.value = quantities[input.dataset.productId];
    });
    say('試算完成；訂購前請到工作台核對最終數量。庫存與原建議未變。');
  }));
  modeControls=window.BForecastControls({api,context:()=>context,work,
    refresh:async message=>{await loadContext();modeControls.clearResultConfirmations();say(message);}});
  $('run-cycle').addEventListener('change',()=>modeControls.clearResultConfirmations());
  $('run-items').addEventListener('input',event=>{if(event.target.dataset.productId) modeControls.clearResultConfirmations();});
  work(async () => { csrf = (await api('/api/auth/csrf')).csrf_token; await loadContext(); });
})();

'use strict';
(() => {
  const root = document.getElementById('replenishment-app');
  if (!root) return;
  const $ = id => document.getElementById(id), storeId = Number(root.dataset.storeId);
  let context, run, csrf, busy = false;
  const node = (tag, text) => { const el = document.createElement(tag); el.textContent = text; return el; };
  const local = value => new Date(value).toLocaleString('zh-TW', {timeZone: 'Asia/Taipei', hour12: false});
  const say = (text, error = false) => { $('run-message').textContent = text; $('run-message').classList.toggle('error', error); };
  const api = async (url, data) => {
    const response = await fetch(url, data ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify(data)} : {});
    const result = await response.json();
    if (!response.ok) throw new Error((result.error?.code || response.status) + '：' + (result.error?.message || '操作失敗'));
    return result;
  };
  const lock = () => {
    root.querySelectorAll('button, select, input').forEach(el => { el.disabled = busy; });
    $('generate-run').disabled = busy || !context?.can_generate || !$('run-cycle').value;
    $('evaluate-run').disabled = busy || !run || !context?.can_generate || !$('run-cycle').value;
    $('load-run').disabled = busy || !$('saved-run').value;
    root.querySelectorAll('input[data-unavailable]').forEach(el => { el.disabled = true; });
  };
  const loadContext = async () => {
    context = await api('/api/replenishment/context?store_id=' + storeId);
    $('run-window').textContent = '業務時間 ' + local(context.business_now) + '；基準 B ' + local(context.baseline_at) +
      '；截止 ' + local(context.cutoff_at) + '（Asia/Taipei）';
    $('run-provider').textContent = context.source_provider.test_only ?
      '模組開發：未結來源使用受控測試提供者，尚未驗證真實履約整合。' : '未結來源：' + context.source_provider.name;
    const old = $('run-cycle').value;
    $('run-cycle').replaceChildren();
    for (const cycle of context.cycles) {
      const option = node('option', local(cycle.arrival_at) + ' · L=' + cycle.lead_days + '日');
      option.value = cycle.id; $('run-cycle').append(option);
    }
    if ([...$('run-cycle').options].some(o => o.value === old)) $('run-cycle').value = old;
    $('saved-run').replaceChildren();
    for (const saved of context.runs) {
      const option = node('option', '#' + saved.id + ' · ' + local(saved.actual_generated_at));
      option.value = saved.id; $('saved-run').append(option);
    }
    if (!context.can_generate) say('目前非21:00–22:00；可讀取原快照，不能產生或重新試算。');
    else if (!context.cycles.length) say('本輪尚無配送輪次；請先準備本機B03合成案例或核對正式輪次。', true);
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
    $('run-title').textContent = '計算快照 #' + run.run_id;
    $('run-metadata').textContent = 'B ' + local(run.baseline_at) + '；產生 ' + local(run.actual_generated_at) +
      '；資料涵蓋至 ' + local(run.data_through_at) + '；風險評估 ' + local(run.risk_evaluated_at) +
      '；保護至 ' + local(run.protection_end) + '；門市版本 ' + run.store_version +
      '；模型 ' + run.model_version + '／警示 v' + run.warning_version;
    $('run-view-kind').textContent = evaluation ? '目前顯示試算結果；保存快照未變。' : '目前顯示保存快照。';
    $('run-items').replaceChildren();
    for (const item of run.items) {
      const card = node('article', ''); card.className = 'run-item'; card.dataset.sku = item.input_snapshot.sku;
      card.append(node('h3', item.input_snapshot.product_name + ' · ' + item.input_snapshot.sku + ' · 箱入 ' + item.pack_size + '件'));
      const sums = {U: 0, C: 0, RISK: 0}; item.sources.forEach(s => { sums[s.bucket] += s.quantity; });
      const metrics = node('div', ''); metrics.className = 'run-metrics';
      for (const [label, value] of [['H', item.h ?? '不可用'], ['七日平均 μ', item.mu ?? '無有效預測'],
        ['目標 S', item.target_stock ?? '無法計算'], ['原始 Q', item.raw_qty ?? '無法計算'],
        ['建議量', item.suggested_qty === null ? '無有效建議' : item.suggested_qty + '件'],
        ['有效 U／C', sums.U + '／' + sums.C], ['未扣抵風險量', sums.RISK]]) {
        const cell = node('div', label); cell.className = 'run-metric'; cell.append(node('strong', String(value))); metrics.append(cell);
      }
      card.append(metrics, node('p', 'L=' + item.lead_days + '；SS=' + item.safety_stock + '；容量=' + item.capacity +
        '；政策版本=' + item.policy_version + '；庫存版本=' + item.inventory_version));
      const warnings = node('ul', '');
      for (const warning of item.warnings) {
        const li = node('li', warning.code + '：' + warning.message);
        li.className = 'run-warning ' + warning.level; warnings.append(li);
      }
      card.append(warnings);
      const input = node('input', ''); input.type = 'number'; input.min = 0; input.max = 1000000; input.step = 1;
      input.value = item.suggested_qty ?? ''; input.dataset.productId = item.product_id; input.id = 'final-' + item.product_id;
      if (item.mode === 'unavailable') input.dataset.unavailable = 'true';
      const label = node('label', item.mode === 'unavailable' ? '無有效建議：請先修正資料，本次不得試訂此品項' : '試算最終量（件）');
      label.htmlFor = input.id; card.append(label, input);
      details(card, '計算公式與參數', node('p', 'R=1；P=1+L；μ=七日銷售總和÷7；S=μ×P+SS；Q原始=max(0,S−H−U−C)；Q建議=向上取整箱。缺檔、缺貨或未正常營業不補零；RISK不扣需求。'));
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
      expected_version: context.store_version});
    render(result); await loadContext(); $('saved-run').value = result.run_id;
    say('快照已保存 #' + result.run_id + '；庫存未異動。');
  }));
  $('load-run').addEventListener('click', () => work(async () => {
    render(await api('/api/replenishment/runs/' + $('saved-run').value + '?store_id=' + storeId));
    say('已讀取原快照；建議、來源與風險保持當時值。');
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
      store_id: storeId, cycle_id: Number($('run-cycle').value), final_quantities: quantities});
    render(result, true);
    // Retain the actual final inputs; suggestions are explanatory and never replace them.
    root.querySelectorAll('input[data-product-id]').forEach(input => {
      if (!input.dataset.unavailable) input.value = quantities[input.dataset.productId];
    });
    say('試算完成；原快照與庫存未變，沒有建立訂單。');
  }));
  work(async () => { csrf = (await api('/api/auth/csrf')).csrf_token; await loadContext(); });
})();

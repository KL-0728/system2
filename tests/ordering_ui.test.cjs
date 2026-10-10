// Exercise the shipped event handlers without claiming browser/layout coverage.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function element(value = '') {
  return {
    value, textContent: '', hidden: false, checked: false, dataset: {}, listeners: {},
    classList: {toggle() {}},
    addEventListener(type, listener) { this.listeners[type] = listener; },
    dispatchEvent(event) { return this.listeners[event.type]?.(event); },
    getAttribute() { return 'false'; },
    scrollIntoView() {},
    showModal() { this.open = true; },
    close() { this.open = false; this.listeners.close?.(); },
  };
}

function page(initialQuantity) {
  const ids = new Map();
  for (const id of ['ordering-bootstrap', 'preview-button', 'global-error', 'draft-status',
    'preview-summary', 'exception-toolbar', 'exception-list', 'exception-count',
    'exception-filter', 'order-ack', 'stage-workbench', 'stage-preview', 'back-button',
    'submit-button', 'submit-error', 'exclude-dialog', 'exclude-description', 'exclude-note',
    'exclude-cancel', 'exclude-confirm']) ids.set(id, element());
  ids.get('ordering-bootstrap').textContent = JSON.stringify({store_id: 1, run: {run_id: 1, cycle_id: 1}});
  const fields = Object.fromEntries(['final_qty', 'reason_code', 'reason', 'need_date',
    'need_qty', 'arrangement', 'manual_ack'].map(name => [name, element()]));
  fields.final_qty.value = initialQuantity;
  fields.reason_code.value = 'local_demand';
  fields.reason.value = '活動商品已安排交付';
  const error = element();
  const row = element();
  row.dataset = {productId: '1', suggested: '30'};
  const name = element(); name.textContent = '飲料';
  const state = element();
  row.querySelector = selector => selector === '.comparison' ? element() :
    selector === '[data-product-name]' ? name : selector === '[data-item-state]' ? state :
    selector.startsWith('[data-error') ? error : fields[selector.match(/"([^"]+)"/)[1]];
  fields.final_qty.closest = () => row;
  const exception = element();
  exception.dataset = {exceptionProduct: '1'};
  const handling = element(); handling.dataset = {exception: 'handling'};
  const ack = element(); const reason = element();
  exception.querySelectorAll = () => [handling, ack, reason];
  exception.querySelector = selector => selector.includes('handling') ? handling :
    selector.includes('ack') ? ack : reason;
  const calls = [];
  const snapshot = {items: [{product_id: 1, name: '飲料', unit: '件', suggested_qty: 30,
    final_qty: 120, sources: {U: 0, C: 0, RISK: 0}, warnings: [], important_codes: ['CAPACITY']}]};
  const document = {
    getElementById: id => ids.get(id) || null,
    createElement: () => ({textContent: '', get innerHTML() {return this.textContent;}}),
    querySelector: () => row,
    querySelectorAll: selector => selector === '.product-row' ? [row] :
      selector === '[data-field="final_qty"]' ? [fields.final_qty] :
      selector === '[data-exception-product]' ? [exception] : [],
  };
  const context = {document, Headers, Event, crypto: {randomUUID: () => 'test-key'},
    window: {scrollTo() {}},
    fetch: async (url, options) => {
      calls.push({url, options});
      const data = url.endsWith('/csrf') ? {csrf_token: 'csrf'} :
        url.endsWith('/preview') ? {confirmation_token: 'token', snapshot} : {id: 1, version: 2};
      return {ok: true, json: async () => data};
    }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../app/static/js/ordering.js'), 'utf8'), context);
  return {ids, fields, calls, handling, error};
}

test('blank quantity is rejected before any draft write', async () => {
  const view = page('');
  await new Promise(resolve => setImmediate(resolve));
  await view.ids.get('preview-button').listeners.click();
  assert.equal(view.calls.length, 0);
  assert.match(view.error.textContent, /整數/);
});

test('exclude returns to edited draft and requires a fresh preview', async () => {
  const view = page('120');
  await new Promise(resolve => setImmediate(resolve));
  await view.ids.get('preview-button').listeners.click();
  assert.equal(view.ids.get('stage-preview').hidden, false);
  view.handling.value = 'exclude';
  view.handling.listeners.change();
  assert.equal(view.fields.final_qty.value, '120');
  assert.equal(view.ids.get('exclude-dialog').open, true);
  view.ids.get('exclude-cancel').listeners.click();
  assert.equal(view.fields.final_qty.value, '120');
  view.handling.value = 'exclude';
  view.handling.listeners.change();
  view.ids.get('exclude-confirm').listeners.click();
  assert.equal(view.fields.final_qty.value, '0');
  assert.equal(view.fields.reason_code.value, 'skip');
  assert.equal(view.ids.get('stage-preview').hidden, true);
  assert.equal(view.ids.get('stage-workbench').hidden, false);
  assert.match(view.ids.get('draft-status').textContent, /重新確認/);
  assert.equal(view.calls.some(call => call.url.endsWith('/submit')), false);
});

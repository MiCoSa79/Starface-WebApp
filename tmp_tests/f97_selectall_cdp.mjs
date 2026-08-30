#!/usr/bin/env node
/**
 * F97-CDP-E2E-Test: „Alle auswählen“ wählt NUR die SICHTBAREN (gefilterten)
 * Checkboxen; „Auswahl aufheben“ leert; ohne Filter werden alle gewählt.
 *
 * Voraussetzung: Headless-Chrome mit --remote-debugging-port=9222 läuft und
 * /opt/data/admin-preview/admin_test_f97.html existiert.
 * Aufruf: NODE_PATH=/opt/hermes/node_modules node tmp_tests/f97_selectall_cdp.mjs
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');

const CDP = 'http://127.0.0.1:9222';
const URL_ = 'file:///opt/data/admin-preview/admin_test_f97.html';
const WAIT = 450; // >= Filter-Debounce 200ms

let pass = 0, fail = 0;
function check(name, ok, detail = '') {
  if (ok) { pass++; console.log(`  ✅ ${name}`); }
  else { fail++; console.log(`  ❌ ${name}${detail ? ' — ' + detail : ''}`); }
}

async function openPage() {
  const res = await fetch(CDP + '/json/new?' + encodeURIComponent(URL_), { method: 'PUT' });
  return res.json();
}
function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.on('open', () => resolve(ws));
    ws.on('error', reject);
  });
}

async function main() {
  const tab = await openPage();
  const ws = await connect(tab.webSocketDebuggerUrl);
  let msgId = 0;
  const pending = new Map();
  ws.on('message', (raw) => {
    const m = JSON.parse(raw.toString());
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  const send = (method, params = {}) => new Promise((res) => {
    const id = ++msgId; pending.set(id, res); ws.send(JSON.stringify({ id, method, params }));
  });
  const ev = (expr) => send('Runtime.evaluate', { expression: expr, returnByValue: true })
    .then((m) => m.result.result.value);

  await send('Page.enable');
  await new Promise((r) => setTimeout(r, 300));

  // Initial: admin.js geladen, initAuDlg/initAuSelectAll registriert
  check('admin.js geladen (initAuSelectAll sichtbar)',
    await ev('typeof initAuSelectAll') === 'function', '');
  check('3 Checkboxen, alle leer',
    await ev('[...document.querySelectorAll("input.au-cb")].map(c=>c.checked).join(",")') === 'false,false,false', '');

  // Filter "Be" -> nur Beta sichtbar (display:none via initTableFilters)
  await ev(`(() => { const i = document.getElementById('wc-in'); i.value = 'Be';
    i.dispatchEvent(new Event('input', {bubbles:true})); return i.value; })()`);
  await new Promise((r) => setTimeout(r, WAIT));
  const vis = await ev(`[...document.querySelectorAll('#tbl-au tbody tr')].map(tr => getComputedStyle(tr).display)`);
  check('Filter zeigt nur Beta', vis.join('|') === 'none|table-row|none', vis.join('|'));

  // Klick "Alle auswählen" -> NUR Beta checked
  await ev(`document.getElementById('sel-all').click()`);
  const after = await ev(`[...document.querySelectorAll('input.au-cb')].map(c=>c.checked).join(',')`);
  check('Alle auswählen (gefiltert): nur Beta checked', after === 'false,true,false', after);

  // Klick "Auswahl aufheben"
  await ev(`document.getElementById('sel-none').click()`);
  check('Auswahl aufheben: nichts checked',
    await ev('[...document.querySelectorAll("input.au-cb")].every(c=>!c.checked)'), '');

  // Filter leeren -> "Alle auswählen" -> alle 3 checked
  await ev(`(() => { const i = document.getElementById('wc-in'); i.value = '';
    i.dispatchEvent(new Event('input', {bubbles:true})); })()`);
  await new Promise((r) => setTimeout(r, WAIT));
  await ev(`document.getElementById('sel-all').click()`);
  check('Ohne Filter: alle 3 checked',
    await ev('[...document.querySelectorAll("input.au-cb")].every(c=>c.checked)'), '');

  // RemoteObject freigeben + Tab schließen
  ws.close();
  try { await fetch(CDP + '/json/close/' + tab.id); } catch (e) {}

  console.log(fail === 0 ? 'ALLE F97-CDP-CHECKS OK' : `F97-CDP: ${fail} FAIL(S)`);
  process.exit(fail === 0 ? 0 : 1);
}
main().catch((e) => { console.error('CDP-Fehler:', e); process.exit(1); });

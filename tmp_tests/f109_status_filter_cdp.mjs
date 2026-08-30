#!/usr/bin/env node
/**
 * CDP-E2E-Test: F109-Folgefix — Gesamtstatus-Dropdown auf "Durchgeführte Updates".
 *
 * Szenario im Screenshot: Das Select zeigte neben den 4 festen Optionen einen
 * fünften Eintrag "erfolgreich Zielversion 10.0.2.5 bestätigt" (dynamisch aus
 * Zelltext+Detail generiert). Fix in app/static/admin.js:
 *   1. Selects mit festen <option>s werden NICHT mehr dynamisch befüllt.
 *   2. Select-Matching nutzt data-status der Zelle statt textContent (Detail).
 *
 * Voraussetzung: Headless-Chrome mit --remote-debugging-port=9222 läuft,
 * Fixture /opt/data/admin-preview/admin_test_f109.html.
 * Aufruf: NODE_PATH=/opt/hermes/node_modules node tmp_tests/f109_status_filter_cdp.mjs
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');

const CDP = 'http://127.0.0.1:9222';
const URL_ = 'file:///opt/data/admin-preview/admin_test_f109.html';
const WAIT = 450;

let pass = 0, fail = 0;
function check(name, ok, detail = '') {
  if (ok) { pass++; console.log(`  ✅ ${name}`); }
  else { fail++; console.log(`  ❌ ${name}${detail ? ' — ' + detail : ''}`); }
}

async function openPage() {
  const url = CDP + '/json/new?' + encodeURIComponent(URL_);
  const res = await fetch(url, { method: 'PUT' });
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
  const waiters = [];
  ws.on('message', (raw) => {
    const m = JSON.parse(raw.toString());
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Page.loadEventFired') waiters.forEach(w => w()); waiters.length = 0;
  });
  const send = (method, params = {}) => new Promise((res) => {
    const id = ++msgId; pending.set(id, res);
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evalJs = async (expr) => {
    const m = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (m.result && m.result.exceptionDetails) throw new Error('JS-Fehler: ' + JSON.stringify(m.result.exceptionDetails.exception));
    return m.result && m.result.result ? m.result.result.value : undefined;
  };
  setTimeout(() => { console.error('⏰ Test-Timeout'); process.exit(2); }, 90000);
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: URL_ });
  for (let i = 0; i < 50; i++) {
    try { if ((await evalJs('document.readyState')) === 'complete') break; } catch (e) {}
    await sleep(100);
  }
  await sleep(400); // initTableFilters laufen lassen

  const sichtbare = () => evalJs(
    `Array.from(document.querySelectorAll('#tbl-f109 tbody tr')).filter(r => r.style.display !== 'none').map(r => r.cells[0].textContent.trim())`);
  const setSelect = async (val) => evalJs(`(() => {
    const el = document.querySelector('.tbl-wrap[data-wrap="f109"] .tbl-filters select');
    el.value = ${JSON.stringify(val)};
    el.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);

  // 1) KEIN dynamischer Eintrag: Optionen = exakt die 4 festen
  const opts = await evalJs(`Array.from(document.querySelector('.tbl-wrap[data-wrap="f109"] .tbl-filters select').options).map(o => o.value)`);
  check('Optionen: exakt 4 feste Werte (kein "erfolgreich Zielversion...")',
        JSON.stringify(opts) === JSON.stringify(['', 'erfolgreich', 'fehlgeschlagen', 'unbekannt']),
        JSON.stringify(opts));

  // 2) Standard-Label heißt "Gesamtstatus (alle)"
  const label = await evalJs(`document.querySelector('.tbl-wrap[data-wrap="f109"] .tbl-filters select').options[0].textContent`);
  check('Standard-Option: "Gesamtstatus (alle)"', label === 'Gesamtstatus (alle)', label);

  // 3) Baseline: 4 Zeilen sichtbar
  let vis = await sichtbare();
  check('Baseline: 4 Zeilen sichtbar', vis.length === 4, JSON.stringify(vis));

  // 4) Filter "erfolgreich" → Alpha + Delta (data-status matcht trotz Detail-Zeile)
  await setSelect('erfolgreich'); await sleep(WAIT);
  vis = await sichtbare();
  check('Filter "erfolgreich" → Alpha, Delta (Detail ignorieren)',
        JSON.stringify(vis) === JSON.stringify(['Alpha', 'Delta']), JSON.stringify(vis));

  // 5) Filter "fehlgeschlagen" → nur Beta
  await setSelect('fehlgeschlagen'); await sleep(WAIT);
  vis = await sichtbare();
  check('Filter "fehlgeschlagen" → Beta', JSON.stringify(vis) === JSON.stringify(['Beta']), JSON.stringify(vis));

  // 6) Filter "unbekannt" → nur Gamma
  await setSelect('unbekannt'); await sleep(WAIT);
  vis = await sichtbare();
  check('Filter "unbekannt" → Gamma', JSON.stringify(vis) === JSON.stringify(['Gamma']), JSON.stringify(vis));

  // 7) Filter "" → alle 4
  await setSelect(''); await sleep(WAIT);
  vis = await sichtbare();
  check('Filter "" (alle) → 4 Zeilen', vis.length === 4, JSON.stringify(vis));

  // 8) Regression: leeres <select> (ohne feste Optionen) wird WEITER dynamisch befüllt
  const dynOpts = await evalJs(`Array.from(document.querySelector('.tbl-wrap[data-wrap="f109b"] .tbl-filters select').options).map(o => o.value)`);
  check('Regression: dyn. Befüllen leerer Selects intakt (erfolgreich/fehlgeschlagen/unbekannt)',
        JSON.stringify(dynOpts) === JSON.stringify(['erfolgreich', 'fehlgeschlagen', 'unbekannt']),
        JSON.stringify(dynOpts));

  await fetch(CDP + '/json/close/' + tab.id).catch(() => {});
  console.log(`\n${pass} bestanden, ${fail} fehlgeschlagen.`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => { console.error('Testabsturz:', e.message); process.exit(2); });

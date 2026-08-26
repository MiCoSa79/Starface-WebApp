#!/usr/bin/env node
/**
 * Regressionstest: URL-Eingabefelder auf /admin im Mobile-Viewport.
 * F41-Fix (v0.0.196): flex-basis 380px darf in der column-Flexbox NICHT als
 * Hoehe greifen — vorher waren beide Felder 380px hoch (Bug), jetzt 44px.
 * Zusaetzlich Desktop-Check: Breite >= 380px bleibt erhalten.
 *
 * Voraussetzung: Server :8897 (STARFACE_DB=/tmp/mobile_test/test.db),
 * Headless-Chrome CDP :9222. Aufruf:
 *   NODE_PATH=/opt/hermes/node_modules node tmp_tests/mobile_url_layout_cdp.mjs [screenshot.png]
 * Exit 0 = grün, 1 = FAIL.
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');
import { writeFileSync } from 'fs';

const CDP = 'http://127.0.0.1:9222';
const BASE = 'http://127.0.0.1:8897';
const SHOT = process.argv[2] || '/tmp/mobile_admin.png';
const WAIT = 700;

let pass = 0, fail = 0;
function check(name, ok, detail = '') {
  if (ok) { pass++; console.log(`  ✅ ${name}`); }
  else { fail++; console.log(`  ❌ ${name}${detail ? ' — ' + detail : ''}`); }
}

async function openPage(url) {
  const res = await fetch(CDP + '/json/new?' + encodeURIComponent(url), { method: 'PUT' });
  return res.json();
}
function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.on('open', () => resolve(ws));
    ws.on('error', reject);
  });
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function measure(ws, width, height, dpr, label, shotFile = SHOT) {
  const send = (method, params = {}) => new Promise((res) => {
    const id = ++ws._mid; ws._pending.set(id, res);
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evalJs = async (expr) => {
    const m = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (m.result && m.result.exceptionDetails) throw new Error('JS-Fehler: ' + JSON.stringify(m.result.exceptionDetails.exception));
    return m.result && m.result.result ? m.result.result.value : undefined;
  };
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: dpr, mobile: dpr > 1 });
  await send('Page.navigate', { url: BASE + '/' });
  await sleep(WAIT);
  const login = await evalJs(`(async () => {
    const r = await fetch('/api/login', { method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'username=admin&password=pw123' });
    return r.status === 200;
  })()`);
  if (!login) throw new Error('Login fehlgeschlagen');
  await send('Page.navigate', { url: BASE + '/admin' });
  await sleep(WAIT);
  const m = await evalJs(`(() => {
    const rect = (el) => el ? (() => { const r = el.getBoundingClientRect(); return { h: Math.round(r.height), w: Math.round(r.width), fb: getComputedStyle(el).flexBasis, fs: getComputedStyle(el).fontSize }; })() : null;
    return { grafana: rect(document.getElementById('grafana_base_url')),
             update: rect(document.getElementById('module_update_base_url')),
             vw: window.innerWidth, trace: document.body.innerHTML.includes('Traceback') };
  })()`);
  console.log(`MESSUNG (${label}):`, JSON.stringify(m));
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(shotFile, Buffer.from(shot.result.data, 'base64'));
  return m;
}

async function main() {
  const tab = await openPage('about:blank');
  const ws = await connect(tab.webSocketDebuggerUrl);
  ws._mid = 0;
  ws._pending = new Map();
  ws.on('message', (raw) => {
    const m = JSON.parse(raw.toString());
    if (m.id && ws._pending.has(m.id)) { ws._pending.get(m.id)(m); ws._pending.delete(m.id); }
  });
  setTimeout(() => { console.error('⏰ Test-Timeout'); process.exit(2); }, 90000);

  // ── Mobile: Höhenproblem (Regression) ──
  const mob = await measure(ws, 390, 844, 2, 'Mobile 390x844', SHOT.replace('.png', '_mobile.png'));
  check('Kein Traceback auf /admin', !mob.trace);
  for (const [k, v] of [['grafana', mob.grafana], ['update', mob.update]]) {
    check(`${k}: Feld nicht mehr 380px hoch`, v.h <= 60, `h=${v.h}px`);
    check(`${k}: Touch-Hoehe >= 44px`, v.h >= 44, `h=${v.h}px`);
    check(`${k}: flex-basis auto (kein 380px-Hoehe-Bug)`, v.fb === 'auto', `flex-basis=${v.fb}`);
    check(`${k}: font-size 16px (iOS-Zoom-Fix)`, v.fs === '16px', v.fs);
  }

  // ── Desktop: Breiten-Verhalten bleibt ──
  const desk = await measure(ws, 1280, 900, 1, 'Desktop 1280x900', SHOT.replace('.png', '_desktop.png'));
  check('grafana: Desktop-Breite >= 380px', desk.grafana && desk.grafana.w >= 380, `w=${desk.grafana && desk.grafana.w}px`);
  check('update: Desktop-Breite >= 380px', desk.update && desk.update.w >= 380, `w=${desk.update && desk.update.w}px`);
  for (const [k, v] of [['grafana', desk.grafana], ['update', desk.update]]) {
    check(`${k}: Desktop-Höhe normal (< 60px)`, v && v.h <= 60, `h=${v && v.h}px`);
  }

  console.log(`\nERGEBNIS: ${fail} FAIL / ${pass} OK`);
  console.log('Screenshot:', SHOT);
  ws.close();
  process.exit(fail ? 1 : 0);
}
main().catch(e => { console.error('FEHLER:', e.message); process.exit(1); });

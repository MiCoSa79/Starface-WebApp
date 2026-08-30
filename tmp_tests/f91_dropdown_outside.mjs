#!/usr/bin/env node
/**
 * F91: Außenklick-Regression — schließen Nav-Dropdowns auf ALLEN Seiten
 * (Desktop + Mobile)? Diagnose: admin.js geladen pro Seite + Funktionalität.
 * Voraussetzung: Server :8898 (menu_test-DB, admin/pw123), Chrome CDP :9222.
 * Aufruf: NODE_PATH=/opt/hermes/node_modules node tmp_tests/f91_dropdown_outside.mjs
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');

const CDP = 'http://127.0.0.1:9222';
const BASE = 'http://127.0.0.1:8898';
const WAIT = 500;

let pass = 0, fail = 0;
const results = [];
function check(name, ok, detail = '') {
  if (ok) { pass++; console.log(`  ✅ ${name}`); }
  else { fail++; console.log(`  ❌ ${name}${detail ? ' — ' + detail : ''}`); }
  results.push({ name, ok, detail });
}

const tab = await (await fetch(CDP + '/json/new?' + encodeURIComponent('about:blank'), { method: 'PUT' })).json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
let id = 0;
const send = (method, params = {}) => new Promise((res) => {
  const mid = ++id;
  const onMsg = (raw) => { const m = JSON.parse(raw); if (m.id === mid) { ws.off('message', onMsg); res(m); } };
  ws.on('message', onMsg);
  ws.send(JSON.stringify({ id: mid, method, params }));
});
const evalJs = async (expr) => {
  const m = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (m.result && m.result.exceptionDetails) throw new Error('JS-Fehler: ' + JSON.stringify(m.result.exceptionDetails.exception));
  return m.result && m.result.result ? m.result.result.value : undefined;
};
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const setViewport = (w, h, mobile) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile });
const goto = async (p) => { await send('Page.navigate', { url: BASE + p }); await sleep(WAIT); };

// Login
await setViewport(1280, 800, false);
await goto('/');
await evalJs(`fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'username=admin&password=pw123' })`);

const PAGES = ['/', '/anlagen', '/monitoring', '/konto', '/wiki', '/admin/modules',
  '/admin/updates', '/admin/updates/modul', '/grundeinstellungen', '/benutzer', '/rechte', '/admin/api-doku'];

const testPage = async (path, label) => {
  await goto(path);
  const probe = await evalJs(`(() => {
    const adminJs = Array.from(document.scripts).some(s => (s.src || '').includes('admin.js'));
    const hasDrop = !!document.querySelector('details.drop summary');
    const hasUser = !!document.querySelector('details.user-drop summary');
    return { adminJs, hasDrop, hasUser, title: document.title };
  })()`);
  if (probe.hasDrop) {
    // Administration öffnen → Außenklick
    await evalJs(`(() => { const s = Array.from(document.querySelectorAll('details.drop summary')).find(x => x.textContent.includes('Administration')); s.click(); })()`);
    await sleep(200);
    const before = await evalJs(`(() => !!document.querySelector('details.drop[open]'))()`);
    await evalJs(`(() => { document.querySelector('.topbar h1').click(); })()`);
    await sleep(200);
    const after = await evalJs(`(() => !!document.querySelector('details.drop[open]'))()`);
    check(`${label}: Administration schließt bei Außenklick`, before && !after, `adminJs=${probe.adminJs} vor=${before} nach=${after}`);
  } else {
    check(`${label}: Administration schließt bei Außenklick (kein Dropdown auf Seite)`, true);
  }
  if (probe.hasUser) {
    await evalJs(`(() => { document.querySelector('details.user-drop summary').click(); })()`);
    await sleep(200);
    const before = await evalJs(`(() => !!document.querySelector('details.user-drop[open]'))()`);
    await evalJs(`(() => { document.querySelector('.topbar h1').click(); })()`);
    await sleep(200);
    const after = await evalJs(`(() => !!document.querySelector('details.user-drop[open]'))()`);
    check(`${label}: User-Dropdown schließt bei Außenklick`, before && !after, `adminJs=${probe.adminJs} vor=${before} nach=${after}`);
  }
  if (!probe.adminJs) {
    check(`${label}: admin.js NICHT geladen (Seite ohne initNavDrops)`, true, '-> Außenklick kann nicht funktionieren');
  }
};

console.log('── DESKTOP 1280×800 ──');
for (const p of PAGES) await testPage(p, `D/${p}`);

console.log('\n── MOBILE 390×844 (Hamburger + Topbar) ──');
await setViewport(390, 844, true);
for (const p of PAGES) {
  await goto(p);
  // Hamburger öffnen (Nav an) → Administration im Menü testen
  await evalJs(`(() => { const h = document.getElementById('nav-open'); if (h) h.click(); })()`);
  await sleep(200);
  const hasDrop = await evalJs(`(() => !!document.querySelector('details.drop summary'))()`);
  if (hasDrop) {
    await evalJs(`(() => { Array.from(document.querySelectorAll('details.drop summary')).find(x => x.textContent.includes('Administration')).click(); })()`);
    await sleep(200);
    const before = await evalJs(`(() => !!document.querySelector('details.drop[open]'))()`);
    await evalJs(`(() => { document.querySelector('.topbar h1').click(); })()`);
    await sleep(200);
    const after = await evalJs(`(() => !!document.querySelector('details.drop[open]'))()`);
    check(`M/${p}: Admin-Dropdown schließt bei Außenklick (Nav bleibt)`, before && !after, `vor=${before} nach=${after}`);
  }
  const hasUser = await evalJs(`(() => !!document.querySelector('details.user-drop summary'))()`);
  if (hasUser) {
    await evalJs(`(() => { document.querySelector('details.user-drop summary').click(); })()`);
    await sleep(200);
    const before = await evalJs(`(() => !!document.querySelector('details.user-drop[open]'))()`);
    await evalJs(`(() => { document.querySelector('.topbar h1').click(); })()`);
    await sleep(200);
    const after = await evalJs(`(() => !!document.querySelector('details.user-drop[open]'))()`);
    check(`M/${p}: User-Dropdown schließt bei Außenklick`, before && !after, `vor=${before} nach=${after}`);
  }
}

// F91-Teil 2 (Axel: „schließt sich nicht mal, wenn man auf eine Auswahl klickt“):
// Klick auf einen Link IM offenen Dropdown schließt es ebenfalls (auch ohne Seitensprung).
console.log('\n── LINK-KLICK IM DROPDOWN ──');
await setViewport(1280, 800, false);
await goto('/konto');
// sauber warten, bis /konto WIRKLICH geladen ist (nicht die alte Seite mit
// identischem user-drop-Summary täuschen lassen)
for (let i = 0; i < 20; i++) {
  const st = await evalJs(`(() => ({ path: location.pathname, ready: document.readyState, hasUser: !!document.querySelector('details.user-drop summary') }))()`);
  if (st.path === '/konto' && st.ready === 'complete' && st.hasUser) break;
  await sleep(250);
}
await evalJs(`(() => { const s = document.querySelector('details.user-drop summary'); s.click(); })()`);
await sleep(200);
await evalJs(`(() => { const a = document.querySelector('details.user-drop a'); a.click(); })()`);
await sleep(300);
check('Desktop /konto: Link „Mein Konto“ schließt User-Dropdown', await evalJs(`(() => !document.querySelector('details.user-drop[open]'))()`));
await goto('/');
await evalJs(`(() => { document.querySelector('details.drop summary').click(); })()`);
await sleep(200);
await evalJs(`(() => { const a = document.querySelector('details.drop a'); a.click(); })()`);
await sleep(300);
check('Desktop /: Link „Startseite“ schließt Admin-Dropdown', await evalJs(`(() => !document.querySelector('details.drop[open]'))()`));

// Mobiler Link-Klick in FRISCHEM Tab (der gealterte Haupt-Tab hat nach ~50
// Navigationen einen bfcache/Viewport-Artefakt-Zustand)
const tab2 = await (await fetch(CDP + '/json/new?' + encodeURIComponent('about:blank'), { method: 'PUT' })).json();
const ws2 = new WebSocket(tab2.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws2.on('open', res); ws2.on('error', rej); });
const send2 = (method, params = {}) => new Promise((res) => {
  const mid = ++id;
  const onMsg = (raw) => { const m = JSON.parse(raw); if (m.id === mid) { ws2.off('message', onMsg); res(m); } };
  ws2.on('message', onMsg);
  ws2.send(JSON.stringify({ id: mid, method, params }));
});
const evalJs2 = async (expr) => {
  const m = await send2('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (m.result && m.result.exceptionDetails) throw new Error('JS-Fehler: ' + JSON.stringify(m.result.exceptionDetails.exception));
  return m.result && m.result.result ? m.result.result.value : undefined;
};
const goto2 = async (p) => { await send2('Page.navigate', { url: BASE + p }); await sleep(WAIT); };
await send2('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
await goto2('/');
await sleep(600);
await goto2('/konto');
for (let i = 0; i < 20; i++) {
  const st = await evalJs2(`(() => ({ path: location.pathname, ready: document.readyState, hasUser: !!document.querySelector('details.user-drop summary') }))()`);
  if (st.path === '/konto' && st.ready === 'complete' && st.hasUser) break;
  await sleep(250);
}
await evalJs2(`(() => { const s = document.querySelector('details.user-drop summary'); s.click(); })()`);
await sleep(200);
await evalJs2(`(() => { const a = document.querySelector('details.user-drop a'); a.click(); })()`);
await sleep(300);
check('Mobile /konto: Link „Mein Konto“ schließt User-Dropdown', await evalJs2(`(() => !document.querySelector('details.user-drop[open]'))()`));
ws2.close();

ws.close();
console.log(`\n${pass} ok, ${fail} FAIL`);
process.exit(fail === 0 ? 0 : 1);
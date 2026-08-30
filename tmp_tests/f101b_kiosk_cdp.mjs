#!/usr/bin/env node
/**
 * F101-B: Kiosk-Modus der Gesamtübersicht — volle Breite auf dem PC? (v1.0.99)
 * Beweis an der ECHTEN App statt Fixture:
 *  - Login (admin/pw123) auf lokalem Server 127.0.0.1:8931
 *  - /?kiosk=1 -> body.kiosk aktiv
 *  - .container-Breite vs Viewport: Kiosk muss VOLLBREIT sein (== vw)
 *  - Kontrolle Normal-Modus: container == min(vw, 1400)
 * Voraussetzung: Chromium :9222 läuft, uvicorn :8931 läuft (Test-DB /tmp/menu_test).
 */
import WebSocket from '/opt/hermes/node_modules/ws/index.js';
import http from 'http';

function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++cdp._id;
    cdp._pend[id] = { resolve, reject };
    cdp._ws.send(JSON.stringify({ id, method, params }));
  });
}
cdp._id = 0; cdp._pend = {};

function openPage(url) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: 9222,
                               path: `/json/new?${encodeURIComponent(url)}`, method: 'PUT' },
      (res) => {
        let b = ''; res.on('data', (c) => (b += c));
        res.on('end', () => resolve(JSON.parse(b)));
      });
    req.on('error', reject); req.end();
  });
}

const passed = [], failed = [];
function check(name, cond, detail = '') {
  (cond ? passed : failed).push([name, detail]);
  console.log((cond ? 'OK  ' : 'FAIL') + ' ' + name + (cond ? '' : ' :: ' + detail));
}
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

const page = await openPage('about:blank');
const ws = new WebSocket(`ws://127.0.0.1:9222/devtools/page/${page.id}`);
await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
cdp._ws = ws;
let msgId = 0;
const ev = {};
ws.on('message', (raw) => {
  try {
    const m = JSON.parse(raw);
    if (m.id && ev[m.id]) { ev[m.id](m); delete ev[m.id]; }
  } catch {}
});
const send = (method, params = {}) => new Promise((res) => {
  const id = ++msgId; ev[id] = res; ws.send(JSON.stringify({ id, method, params }));
});
const ev2 = (name) => new Promise((res) => {
  const h = (raw) => { const m = JSON.parse(raw); if (m.method === name) { ws.off('message', h); res(m); } };
  ws.on('message', h);
});
ws.on('message', (raw) => { try { const m = JSON.parse(raw); if (m.id && ev[m.id]) { ev[m.id](m); delete ev[m.id]; } } catch {} });

async function nav(url) {
  const loaded = ev2('Page.loadEventFired');
  await send('Page.navigate', { url });
  await Promise.race([loaded, delay(2500)]);
  await delay(1400);
}
async function submitAndWait() {
  const loaded = ev2('Page.loadEventFired');
  await run(`document.querySelector('form').requestSubmit()`);
  await Promise.race([loaded, delay(4000)]);
  await delay(1200);
}
async function run(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
  return r.result && r.result.result ? r.result.result.value : undefined;
}

await send('Page.enable');
await send('Runtime.enable');

// 1) Login
await nav('http://127.0.0.1:8931/');
await run(`document.querySelector('input[name="username"]').value='admin'`);
await run(`document.querySelector('input[name="password"]').value='pw123'`);
await submitAndWait();
const isLogin = await run(`document.title`);
console.log('   nach Login, title =', isLogin);

// 2) Gesamtübersicht Normal (Kontrolle)
await nav('http://127.0.0.1:8931/');
const normal = await run(`(() => { const c = document.querySelector('.container');
  return { vw: document.documentElement.clientWidth, cw: c ? c.getBoundingClientRect().width : -1,
           kiosk: document.body.classList.contains('kiosk') }; })()`);
console.log('   normal:', JSON.stringify(normal));

// 3) Kiosk-Ansicht
await nav('http://127.0.0.1:8931/?kiosk=1');
const kiosk = await run(`(() => { const c = document.querySelector('.container');
  return { vw: document.documentElement.clientWidth, cw: c ? c.getBoundingClientRect().width : -1,
           t: document.querySelector('.kiosk-title') ? document.querySelector('.kiosk-title').offsetWidth : -1,
           kiosk: document.body.classList.contains('kiosk') }; })()`);
console.log('   kiosk:', JSON.stringify(kiosk));

// Bewertung
check('Login funktioniert (kein Login-Titel mehr)', !/Anmeldung|Login/i.test(String(isLogin)), String(isLogin));
check('Kiosk aktiv (body.kiosk)', kiosk && kiosk.kiosk === true, JSON.stringify(kiosk));
check('Kiosk: Container VOLLBREIT (cw == Layout-Viewport)', kiosk && kiosk.cw === kiosk.vw,
      `cw=${kiosk && kiosk.cw} vw=${kiosk && kiosk.vw} — max-content-Schrumpfung, wenn cw < vw`);
check('Normal: Container == Layout-Viewport (vw<1400)', normal && normal.cw === normal.vw,
      `cw=${normal && normal.cw} vw=${normal && normal.vw} (ohne kiosk)`);

console.log(`\n${passed.length} OK, ${failed.length} FAIL`);
ws.close();
process.exit(failed.length ? 1 : 0);

#!/usr/bin/env node
/**
 * F101-CDP-E2E-Test: Seitenbreite PC — Inhaltsseiten einheitlich 1400 (wie /anlagen),
 * Kiosk-Modus nutzt volle Breite (100% statt 1400).
 * Beweis: @1440+ keine max-width-Einschraenkung (password 520/edit 600 gefixt);
 * body.kiosk .container -> max-width:100%.
 */
import { createRequire } from 'module';
const require = createRequire('/opt/hermes/node_modules/');
const http = require('http');

const CDP_PORT = 9222;
const PAGE_URL = 'file:///opt/data/admin-preview/admin_test_f101.html';

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function cdp(ws, id, method, params = {}) {
  return new Promise((resolve, reject) => {
    const h = (raw) => {
      const m = JSON.parse(raw);
      if (m.id === id) { ws.off('message', h); m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result); }
    };
    ws.on('message', h);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function openPage(ws) {
  const res = await cdp(ws, 1, 'Target.createTarget', { url: 'about:blank' });
  return res.targetId;
}

async function main() {
  // Target listen (Chrome 151: /json/new braucht PUT; Target.createTarget ist stabil)
  const targets = await new Promise((res, rej) => {
    http.get('http://127.0.0.1:' + CDP_PORT + '/json/list', (r) => { let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d))); }).on('error', rej);
  });
  const page = targets.find(t => t.type === 'page');
  if (!page) throw new Error('kein Page-Target');
  const WebSocket = require('/opt/hermes/node_modules/ws/index.js');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise(r => ws.on('open', r));
  const targetId = await openPage(ws);

  // Viewport PC (1440x900)
  await cdp(ws, 2, 'Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  // Seite laden (Target.attachToTarget + Page.enable/navigate auf dem neuen Target)
  const { sessionId } = await cdp(ws, 3, 'Target.attachToTarget', { targetId, flatten: true });
  let seq = 100;
  const ev = (sid) => new Promise((resolve) => {
    const h = (raw) => { const m = JSON.parse(raw); if (m.sessionId === sid && m.method === 'Page.loadEventFired') { ws.off('message', h); resolve(); } };
    ws.on('message', h);
  });
  const send = (sid, id, method, params = {}) => new Promise((res, rej) => {
    const h = (raw) => { const m = JSON.parse(raw); if (m.sessionId === sid && m.id === id) { ws.off('message', h); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); } };
    ws.on('message', h);
    ws.send(JSON.stringify({ id, sessionId: sid, method, params }));
  });
  await send(sessionId, seq++, 'Page.enable');
  const ev2 = ev(sessionId);
  await send(sessionId, seq++, 'Page.navigate', { url: PAGE_URL });
  await Promise.race([ev2, sleep(5000)]);
  await sleep(400);

  const probe = (sid, id, sel) => send(sid, id, 'Runtime.evaluate', {
    expression: `(() => { const el = document.querySelector('${sel}'); if (!el) return null;
      return { w: Math.round(el.getBoundingClientRect().width), vw: window.innerWidth }; })()`,
    returnByValue: true,
  });

  const normal = (await probe(sessionId, seq++, '#normal')).result.value;
  const old = (await probe(sessionId, seq++, '#old')).result.value;
  // Kiosk-Modus aktivieren (wie die Templates per JS: body.classList.add('kiosk'))
  await send(sessionId, seq++, 'Runtime.evaluate', { expression: `document.body.classList.add('kiosk')` });
  await sleep(100);
  const kioskAfter = (await probe(sessionId, seq++, '#kiosk')).result.value;

  const checks = [
    // Positiv: F101-Container fuellt die verfuegbare Breite (width:100%, max 1400)
    ['F101: Container nutzt volle Breite (Anlagen-Muster)',
     normal && normal.w >= normal.vw - 60, `w=${normal && normal.w}, vw=${normal && normal.vw}`],
    // Negativ-Kontrolle: ALT-Regel (margin:0 auto ohne width) in body-Flex = shrink-to-fit
    ['NEGATIV: Alt-Regel ohne width bleibt schmal (Regression belegt)',
     old && old.w < 300, `w=${old && old.w}`],
    // Kiosk: body.kiosk .container -> max-width:100% -> volle Fensterbreite
    ['Kiosk: Container vollbreit (max-width:100%)',
     kioskAfter && kioskAfter.w >= kioskAfter.vw - 2, `w=${kioskAfter && kioskAfter.w}, vw=${kioskAfter && kioskAfter.vw}`],
  ];
  let ok = 0;
  checks.forEach(([name, pass, detail]) => { console.log((pass ? 'PASS' : 'FAIL') + ': ' + name + (pass ? '' : '  [' + detail + ']')); if (pass) ok++; });
  try { await ws.close(); } catch {}
  console.log(`F101-ERGEBNIS: ${ok}/${checks.length}`);
  process.exit(ok === checks.length ? 0 : 1);
}

main().catch(e => { console.error('FEHLER: ' + e.message); process.exit(1); });

#!/usr/bin/env node
/**
 * F102: Abruf-Dialog (Anlagen-Updates) — Breite & kein Überlauf (v1.0.100).
 * Relativer Beweis an der Fixture (wie f101): .dlg.wide = min(94vw, 960px),
 * vormals fiel der Dialog auf dialog.dlg max-width:420px zurück → schmal + Tabelle
 * lief horizontal über (Axel-Screenshot 30.08.).
 * Messung gegen document.documentElement.clientWidth (Scrollbar-frei, siehe f101b).
 */
const { execSync } = require('child_process');
const http = require('http');
const WS = require('ws');

const CHROME = 'http://127.0.0.1:9222';
const FIX = 'file:///opt/data/admin-preview/admin_test_f102.html';
const cd = (v) => 'cdn' + v;

function postJson(url, data) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(data);
    const r = http.request(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, (res) => {
      let b = ''; res.on('data', (c) => (b += c)); res.on('end', () => resolve(JSON.parse(b)));
    });
    r.on('error', reject); r.end(body);
  });
}
function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

(async () => {
  const newTarget = await postJson(CHROME + '/json/new?about:blank', undefined).catch(async () => {
    const r = await fetch(CHROME + '/json/new', { method: 'PUT' });
    return r.json();
  });
  const ws = new WS(newTarget.webSocketDebuggerUrl);
  await new Promise((r) => ws.on('open', r));
  let id = 0;
  const pending = new Map();
  const listeners = [];
  const ev2 = (method) => new Promise((res) => listeners.push({ method, res }));
  ws.on('message', (raw) => {
    const m = JSON.parse(raw);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
    for (let i = listeners.length - 1; i >= 0; i--) {
      if (listeners[i].method === m.method) { listeners[i].res(m.params); listeners.splice(i, 1); }
    }
  });
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const run = (expr) => send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }).then((r) => r.result.value);
  const ready = ev2('Page.loadEventFired');

  await send('Page.enable');
  await send('Page.navigate', { url: FIX });
  await Promise.race([ready, delay(2500)]);
  await delay(500);

  const m = await run(`(() => {
    const dlg = document.getElementById('au-dlg');
    const tbl = dlg.querySelector('table');
    const x = document.querySelector('.dlg-close-x');
    const vw = document.documentElement.clientWidth || window.innerWidth;
    const dw = dlg.getBoundingClientRect().width;
    const overflows = tbl.scrollWidth > dlg.clientWidth;
    return { vw, dw, ratio: +(dw / vw).toFixed(3),
             xSvg: !!(x && x.querySelector('svg path')), overflows };
  })()`);

  const checks = [
    ['Dialog nutzt ~94% des Viewports (min(94vw,960))', m.ratio > 0.90 && m.ratio < 0.99, `ratio=${m.ratio} (vw=${m.vw}, dlg=${m.dw})`],
    ['Dialog deutlich breiter als der alte 420px-Fallback', m.dw > 700, `dlg=${m.dw}px`],
    ['Aktionstabelle läuft nicht mehr über', m.overflows === false, `scroll-width=${m.overflows ? '>' : '<='} client-width`],
    ['X-Schließen (SVG) im Kopf vorhanden', m.xSvg === true, `xSvg=${m.xSvg}`],
  ];
  let ok = 0;
  console.log(`F102-Dialog (@vw=${m.vw})`);
  for (const [name, pass, detail] of checks) {
    console.log(`${pass ? 'OK ' : 'FAIL'} ${name} — ${detail}`);
    if (pass) ok++;
  }
  console.log(ok === checks.length ? 'ALLE 4 CHECKS OK' : `NUR ${ok}/${checks.length}`);
  ws.close();
  process.exit(ok === checks.length ? 0 : 1);
})().catch((e) => { console.error('FEHLER:', e.message); process.exit(2); });

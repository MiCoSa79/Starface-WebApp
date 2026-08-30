#!/usr/bin/env node
/**
 * F98-CDP-E2E-Test: Footer ans Seitenende (v1.0.96)
 * - position ist NICHT fixed (kein Overlay beim Scrollen — iPhone-Foto 30.08.)
 * - lange Seite: Footer steht unter dem letzten Inhalt (Seitenende)
 * - kurze Seite (Login): Footer steht am unteren Viewport-Rand
 *
 * Voraussetzung: Headless-Chrome mit --remote-debugging-port=9222 läuft.
 * Aufruf: NODE_PATH=/opt/hermes/node_modules node f98_footer_cdp.mjs
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
ws.on('message', (raw) => {
  const m = JSON.parse(raw);
  if (m.id && cdp._pend[m.id]) {
    const { resolve, reject } = cdp._pend[m.id];
    delete cdp._pend[m.id];
    m.error ? reject(new Error(m.error.message)) : resolve(m.result);
  }
});
await cdp('Page.enable');
await cdp('Runtime.enable');

async function load(url) {
  await cdp('Page.navigate', { url });
  await new Promise((r) => setTimeout(r, 900));
}
const ev = async (expr) => (await cdp('Runtime.evaluate', { expression: expr, returnByValue: true })).result.value;

// ── 1) Lange Seite ──
await load('file:///opt/data/admin-preview/admin_test_f98_lang.html');
const pos = await ev(`getComputedStyle(document.querySelector('.footer')).position`);
check('position nicht fixed (kein Scroll-Overlay)', pos !== 'fixed' && pos === 'static', pos);
const g = await ev(`(() => {
  const f = document.querySelector('.footer').getBoundingClientRect();
  const sc = document.documentElement.scrollHeight;
  window.scrollTo(0, sc);
  return { footerBottomViewport: Math.round(document.querySelector('.footer').getBoundingClientRect().bottom),
           scrollY: Math.round(window.scrollY), docHeight: Math.round(sc), innerH: window.innerHeight };
})()`);
check('lange Seite: Footer BF unter letztem Inhalt (bottom <= scrollHeight)',
      g.footerBottomViewport + g.scrollY <= g.docHeight + 2 && g.scrollY > g.innerH,
      JSON.stringify(g));
check('lange Seite: Seite scrollt über 1 Viewport (echter Test)', g.docHeight > g.innerH, JSON.stringify(g));

// ── 2) Kurze Seite (Login-artig): Footer am unteren Viewport-Rand ──
const p2 = await openPage('about:blank');
const ws2 = new WebSocket(`ws://127.0.0.1:9222/devtools/page/${p2.id}`);
await new Promise((res, rej) => { ws2.on('open', res); ws2.on('error', rej); });
let _sid = 0; const _pend2 = {};
ws2.on('message', (raw) => {
  const m = JSON.parse(raw);
  if (m.id && _pend2[m.id]) { _pend2[m.id](m.result); delete _pend2[m.id]; }
});
const c2 = (method, params = {}) => new Promise((res) => {
  const id = ++_sid; _pend2[id] = res; ws2.send(JSON.stringify({ id, method, params }));
});
await c2('Page.enable'); await c2('Runtime.enable');
const ev2 = async (expr) => (await c2('Runtime.evaluate', { expression: expr, returnByValue: true })).result.value;
await c2('Page.navigate', { url: 'file:///opt/data/admin-preview/admin_test_f98_kurz.html' });
await delay(900);
const k = await ev2(`(() => {
  const f = document.querySelector('.footer').getBoundingClientRect();
  return { footBottom: Math.round(f.bottom), innerH: window.innerHeight, docH: document.documentElement.scrollHeight };
})()`);
check(`kurze Seite: Footer am Viewport-Rand (bottom=${k.footBottom} ≈ ${k.innerH})`,
      Math.abs(k.footBottom - k.innerH) <= 2 && k.docH <= k.innerH + 2, JSON.stringify(k));

console.log(failed.length ? `F98-CDP: ${failed.length} FAIL(S)` : `ALLE F98-CDP-CHECKS OK (${passed.length}/${passed.length})`);
if (failed.length === 0) {
  setTimeout(() => process.exit(0), 50);
} else {
  process.exit(1);
}

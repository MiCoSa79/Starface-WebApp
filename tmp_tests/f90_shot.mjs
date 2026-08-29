#!/usr/bin/env node
/** F90: Mobile-Topbar-Screenshot (390x844) für visuellen Beleg. */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');
import { writeFileSync } from 'fs';

const CDP = 'http://127.0.0.1:9222';
const BASE = 'http://127.0.0.1:8898';
const OUT = process.argv[2] || '/tmp/f90_mobile_topbar.png';

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
const evalJs = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })).result?.result?.value;

await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await send('Page.navigate', { url: BASE + '/' });
await new Promise(r => setTimeout(r, 700));
await evalJs(`fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'username=admin&password=pw123' })`);
await send('Page.navigate', { url: BASE + '/' });
await new Promise(r => setTimeout(r, 700));
const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
writeFileSync(OUT, Buffer.from(shot.result.data, 'base64'));
console.log('Screenshot:', OUT);
ws.close();

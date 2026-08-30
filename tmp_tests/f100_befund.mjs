#!/usr/bin/env node
/**
 * F100-Befund: Benutzer-Seite @390px — welche Buttons sind wie breit?
 * (Messung vor dem Fix; Ergebnis entscheidet den Fix-Umfang)
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const http = require('http');
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');

const delay = (ms) => new Promise(r => setTimeout(r, ms));
const openPage = (url) => new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: 9222, method: 'PUT',
        path: `/json/new?${encodeURIComponent(url)}` }, (res) => {
        let b = ''; res.on('data', c => b += c); res.on('end', () => resolve(JSON.parse(b)));
    }); req.on('error', reject); req.end();
});
function cdp(u) {
    return new Promise((resolve) => {
        const ws = new WebSocket(u.webSocketDebuggerUrl);
        let id = 0; const pending = new Map();
        ws.on('message', (d) => { const m = JSON.parse(d); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
        ws.on('open', () => {
            const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
            resolve({
                ev: async (expr) => {
                    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
                    if (r.result.exceptionDetails) throw new Error('Eval: ' + (r.result.exceptionDetails.exception?.description || ''));
                    return r.result.result.value;
                },
                nav: (url) => send('Page.navigate', { url }),
                send,
                close: () => ws.close(),
            });
        });
    });
}

(async () => {
    const url = 'file:///opt/data/admin-preview/admin_test_f100.html';
    const u = await openPage(url);
    const d = await cdp(u);
    await d.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    await delay(1200);
    const m = await d.ev(`(() => {
        const out = [];
        document.querySelectorAll('button, a.btn-secondary, a.btn-danger, .btn-primary').forEach(el => {
            const r = el.getBoundingClientRect();
            const cs = getComputedStyle(el);
            out.push({
                t: el.tagName, c: el.className, txt: el.textContent.trim().slice(0, 22),
                w: Math.round(r.width), x: Math.round(r.left),
                disp: cs.display, mw: cs.width.endsWith('px') ? Math.round(+cs.width) : cs.width,
                scrollW: el.scrollWidth, offW: el.offsetWidth,
                cut: el.scrollWidth > el.clientWidth + 1
            });
        });
        const tb = document.querySelector('table');
        const tbl = tb.getBoundingClientRect();
        const body = document.body.getBoundingClientRect();
        return {
            buttons: out,
            btnPrimary: [...document.querySelectorAll('.btn-primary')].map(b => Math.round(b.getBoundingClientRect().width)),
            tableW: Math.round(tbl.width), docScrollW: document.documentElement.scrollWidth,
            vw: window.innerWidth,
            tblClientscrollW: tb.clientWidth, tblScrollW: tb.scrollWidth
        };
    })()`);
    console.log(JSON.stringify(m, null, 1));
    d.close();
})().catch(e => { console.error('FEHLER:', e.message); process.exit(2); });

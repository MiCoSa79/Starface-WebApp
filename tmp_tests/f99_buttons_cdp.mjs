#!/usr/bin/env node
/**
 * F99-CDP-E2E-Test: Anlagen-Aktions-Buttons einheitlich + Platz unter der Tabelle
 * (v1.0.97, iPhone-Foto 30.08.: Buttons ungleich gross/Beschriftung uneinheitlich,
 *  unter der Tabelle kein Platz).
 *
 * Voraussetzung: Headless-Chrome auf 127.0.0.1:9222 (--remote-debugging-port=9222
 * --allow-file-access-from-files --no-sandbox --disable-dev-shm-usage).
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
import httpModule from 'http';
const http = httpModule;
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');

let failed = 0;
const ok = (name, cond, detail = '') => {
    if (cond) { console.log(`  OK   ${name}`); }
    else { failed++; console.log(`  FAIL ${name}${detail ? ' — ' + detail : ''}`); }
};

function openPage(url) {
    return new Promise((resolve, reject) => {
        const req = http.request({ host: '127.0.0.1', port: 9222, method: 'PUT',
            path: `/json/new?${encodeURIComponent(url)}` }, (res) => {
            let b = ''; res.on('data', (c) => (b += c)); res.on('end', () => {
                try { resolve(JSON.parse(b).webSocketDebuggerUrl); } catch (e) { reject(new Error('GET /json/new: ' + b)); }
            });
        });
        req.on('error', reject); req.end();
    });
}
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

async function cdp(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((r) => ws.on('open', r));
    let id = 0; const pending = new Map();
    ws.on('message', (d) => { const m = JSON.parse(d); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
    const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
    return {
        ev: async (expr) => {
            const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
            if (r.result.exceptionDetails) throw new Error('Eval: ' + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
            return r.result.result.value;
        },
        nav: (url) => send('Page.navigate', { url }),
        send,
        close: () => ws.close(),
    };
}

(async () => {
    console.log('F99: Anlagen-Buttons einheitlich + Bodenabstand (390 px = iPhone)');
    const url = 'file:///opt/data/admin-preview/admin_test_f99.html';
    const u = await openPage(url);
    const d = await cdp(u);
    // echte iPhone-Viewport-Groesse 390x844 per CDP-Emulation (resizeTo im Headless unzuverlaessig)
    await d.ev('window.__ready = true');
    await d.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    await delay(1200);

    // --- 1) Buttons einheitlich (Hoehe) + zentriert ---
    const btn = await d.ev(`(() => {
        const cs = b => getComputedStyle(b);
        const btns = [...document.querySelectorAll('a.btn-secondary, button.btn-secondary, button.btn-danger')];
        const info = btns.map(b => ({ h: b.offsetHeight, w: b.offsetWidth,
            disp: cs(b).display, jc: cs(b).justifyContent, pad: cs(b).padding,
            ta: cs(b).textAlign }));
        const hs = [...new Set(info.map(i => i.h))];
        return { info, hs, rowRight: btns[btns.length - 1].getBoundingClientRect().right, vw: innerWidth };
    })()`);
    ok('Alle Aktions-Buttons gleiche Hoehe', btn.hs.length === 1,
        'Hoehen=' + btn.hs.join(','));
    ok('Buttons als Flex mit zentrierter Beschriftung',
        btn.info.every(i => i.disp === 'inline-flex' || i.disp === 'flex') &&
        btn.info.every(i => i.jc === 'center'), JSON.stringify(btn.info.map(i => i.disp + '/' + i.jc)));
    ok('Kein horizontaler Ueberlauf (390 px)',
        btn.rowRight <= btn.vw + 1, 'right=' + btn.rowRight + ' vw=' + btn.vw);

    // --- 2) Platz unter der Tabelle (Container-Bodenabstand + Safe-Area-Rueckfall) ---
    const pad = await d.ev(`(() => {
        const c = document.querySelector('.container');
        const css = getComputedStyle(c);
        const f = document.querySelector('.footer');
        return { pb: parseFloat(css.paddingBottom), tableBottom: document.querySelector('table').getBoundingClientRect().bottom,
                 footerTop: f.getBoundingClientRect().top };
    })()`);
    ok('Container-Bodenabstand ≥ 32 px', pad.pb >= 32, 'paddingBottom=' + pad.pb);
    ok('Abstand Tabelle → Footer sichtbar', pad.footerTop - pad.tableBottom >= 20,
        'delta=' + (pad.footerTop - pad.tableBottom).toFixed(1));

    console.log(failed === 0 ? '\nALLE F99-CHECKS OK' : `\n${failed} F99-CHECK(S) FEHLGESCHLAGEN`);
    d.close();
    process.exit(failed === 0 ? 0 : 1);
})().catch((e) => { console.error('CDP-Fehler:', e.message); process.exit(2); });

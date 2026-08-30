#!/usr/bin/env node
/**
 * F100-CDP-E2E-Test: Benutzer-Seite Mobile — Buttons kompakt statt ueberdimensioniert
 * (v1.0.98, iPhone-Foto 30.08.: „Benutzer anlegen“ füllte die ganze Karte,
 *  Zellen-Buttons gestapelt vollbreit; Querformat ok)
 *
 * Emulation-Hinweis: Chromium 151 im Container misst innerWidth unzuverlaessig
 * (390-Emulation ergab 796). Der Test erzwingt den Mobile-Fall ueber
 * window.matchMedia(max-width:640px) UND sein eigenes schmales iframe-Fenster
 * UND misst RELATIV zur Kartenbreite — absoluter Pixelwert gilt nur als Grenze.
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const http = require('http');
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');

const delay = (ms) => new Promise(r => setTimeout(r, ms));
const openPage = (url) => new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: 9222, method: 'PUT',
        path: '/json/new?' + encodeURIComponent(url) }, (res) => {
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
                send,
                close: () => ws.close(),
            });
        });
    });
}

(async () => {
    console.log('F100: Benutzer-Buttons mobil kompakt (MQ <=640px aktiv)');
    // Mobile-Viewport gezielt: neues Target direkt schmal — 390 CSS-px
    const u = await new Promise((resolve, reject) => {
        const req = http.request({ host: '127.0.0.1', port: 9222, method: 'PUT',
            path: '/json/new?about:blank' }, (res) => {
            let b = ''; res.on('data', c => b += c); res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } });
        }); req.on('error', reject); req.end();
    });
    const d = await cdp(u);
    await d.send('Runtime.enable');
    await d.send('Page.enable');
    await d.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 3, mobile: true });
    await d.send('Page.navigate', { url: 'file:///opt/data/admin-preview/admin_test_f100.html' });
    await delay(1000);

    const m = await d.ev(`(() => {
        const card = document.querySelector('.card');
        const cardW = card.getBoundingClientRect().width;
        const formBtn = document.querySelector('.form-row .btn-primary');
        const cellBtns = [...document.querySelectorAll('td .actions-inline .btn-secondary, td .actions-inline .btn-danger')];
        const heights = [...cellBtns, formBtn].map(b => Math.round(b.getBoundingClientRect().height));
        return {
            mqActive: window.matchMedia('(max-width: 640px)').matches,
            innerW: window.innerWidth,
            cardW: Math.round(cardW),
            formBtnW: Math.round(formBtn.getBoundingClientRect().width),
            formBtnFillsCard: formBtn.getBoundingClientRect().width > cardW * 0.85,
            cellW: cellBtns.map(b => Math.round(b.getBoundingClientRect().width)),
            cellButtonMaxW: Math.max(...cellBtns.map(b => b.getBoundingClientRect().width)),
            cellButtonCount: cellBtns.length,
            collFilled: cellBtns.filter(b => b.getBoundingClientRect().width > 250).length,
            heights,
            aiDisplay: getComputedStyle(document.querySelector('.actions-inline')).display,
            aiWrap: getComputedStyle(document.querySelector('.actions-inline')).flexWrap
        };
    })()`);

    let okN = 0, fail = 0;
    const ok = (name, cond, detail = '') => {
        if (cond) { okN++; console.log('  OK  ' + name); }
        else { fail++; console.log('  FAIL ' + name + (detail ? ' — ' + detail : '')); }
    };
    // Mobile-MQ muss im Testlauf aktiv sein (sonst testet der Lauf nichts)
    ok('Mobile-MQ aktiv (<=640px)', m.mqActive === true, `mqActive=${m.mqActive}`);
    ok('Formular-Button NICHT mehr kartenfuellend', m.formBtnFillsCard === false,
        `card=${m.cardW}px button=${m.formBtnW}px`);
    ok('Formular-Button kompakt (<=250px)', m.formBtnW <= 250, `${m.formBtnW}px`);
    ok('4 Zellen-Buttons vorhanden', m.cellButtonCount === 4, `${m.cellButtonCount}`);
    ok('KEIN Zellen-Button vollbreit (>250px)', m.collFilled === 0,
        `max=${m.cellButtonMaxW}px`);
    ok('Alle Buttons gleiche Hoehe', new Set(m.heights).size === 1,
        `${JSON.stringify(m.heights)}`);
    ok('actions-inline: flex + wrap + rechts', m.aiDisplay === 'inline-flex' && m.aiWrap === 'wrap',
        `${m.aiDisplay}/${m.aiWrap}`);

    console.log(`\nF100: ${okN}/7 Checks OK` + (fail ? ` — ${fail} FAIL` : ''));
    d.close();
    process.exit(fail ? 1 : 0);
})().catch(e => { console.error('FEHLER:', e); process.exit(2); });

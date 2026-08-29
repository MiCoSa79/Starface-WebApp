#!/usr/bin/env node
/**
 * F90: Benutzer-Icon statt Benutzername in der Topbar (Mobile-Viewport).
 * Prüft: Icon sichtbar/Name+Caret ausgeblendet auf 390x844; Hamburger + rechte
 * Gruppe vollständig im Viewport (kein horizontaler Overflow); Icon-Klick öffnet
 * Dropdown; Desktop (1280x800): Name sichtbar, Icon versteckt.
 * Voraussetzung: Server :8898 (STARFACE_DB=/tmp/menu_test/test.db,
 * ADMIN_USERNAME=admin, ADMIN_PASSWORD=test1234), Headless-Chrome CDP :9222.
 * Aufruf:
 *   NODE_PATH=/opt/hermes/node_modules node tmp_tests/f90_mobile_icon.mjs
 * Exit 0 = grün, 1 = FAIL.
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');

const CDP = 'http://127.0.0.1:9222';
const BASE = 'http://127.0.0.1:8898';
const WAIT = 500;

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

async function main() {
  const tab = await openPage('about:blank');
  const ws = await connect(tab.webSocketDebuggerUrl);
  let id = 0;
  const send = (method, params = {}) => new Promise((res) => {
    const mid = ++id;
    const onMsg = (raw) => {
      const m = JSON.parse(raw);
      if (m.id === mid) { ws.off('message', onMsg); res(m); }
    };
    ws.on('message', onMsg);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const evalJs = async (expr) => {
    const m = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (m.result && m.result.exceptionDetails) throw new Error('JS-Fehler: ' + JSON.stringify(m.result.exceptionDetails.exception));
    return m.result && m.result.result ? m.result.result.value : undefined;
  };
  const setViewport = (w, h, mobile) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile });

  // ── Mobile 390×844 (iPhone) ──
  await setViewport(390, 844, true);
  await send('Page.navigate', { url: BASE + '/' });
  await sleep(WAIT);
  await evalJs(`(async () => {
    const r = await fetch('/api/login', { method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'username=admin&password=pw123' });
    return r.status;
  })()`);
  await send('Page.navigate', { url: BASE + '/' });
  await sleep(WAIT);

  const mob = await evalJs(`(() => {
    const av = document.querySelector('.topbar .user-drop summary .user-avatar');
    const nm = document.querySelector('.topbar .user-drop summary .user-name');
    const caret = document.querySelector('.topbar .user-drop summary .user-caret');
    const ham = document.querySelector('.hamburger');
    const grp = document.querySelector('.topbar > div');
    const rect = (el) => el ? el.getBoundingClientRect() : null;
    const style = (el) => el ? getComputedStyle(el).display : '(fehlt)';
    return {
      avDisp: style(av), avW: rect(av) ? Math.round(rect(av).width) : 0,
      nmDisp: style(nm), caretDisp: style(caret),
      hamRect: rect(ham) ? { l: Math.round(rect(ham).left), r: Math.round(rect(ham).right) } : null,
      grpRect: rect(grp) ? { l: Math.round(rect(grp).left), r: Math.round(rect(grp).right) } : null,
      innerW: window.innerWidth, scrollW: document.documentElement.scrollWidth,
    };
  })()`);
  check('Mobile: User-Icon sichtbar (display block, Breite > 0)', mob.avDisp === 'block' && mob.avW > 0, JSON.stringify(mob));
  check('Mobile: Benutzername ausgeblendet', mob.nmDisp === 'none', mob.nmDisp);
  check('Mobile: Caret ▾ ausgeblendet', mob.caretDisp === 'none', mob.caretDisp);
  check('Mobile: Hamburger komplett im Viewport (links>=0, rechts<=innerWidth)',
        mob.hamRect && mob.hamRect.l >= 0 && mob.hamRect.r <= mob.innerW, JSON.stringify(mob.hamRect) + ' vs ' + mob.innerW);
  check('Mobile: Rechte Gruppe komplett im Viewport', mob.grpRect && mob.grpRect.l >= 0 && mob.grpRect.r <= mob.innerW, JSON.stringify(mob.grpRect) + ' vs ' + mob.innerW);
  check('Mobile: KEIN horizontaler Overflow (scrollWidth <= innerWidth)',
        mob.scrollW <= mob.innerW, 'scrollW=' + mob.scrollW + ' innerW=' + mob.innerW);

  // Icon-Klick → Dropdown öffnen
  await evalJs(`(() => { document.querySelector('.topbar .user-drop summary').click(); })()`);
  await sleep(300);
  const menu = await evalJs(`(() => {
    const m = document.querySelector('.topbar .user-drop .drop-menu');
    const details = document.querySelector('.topbar .user-drop');
    return {
      open: details ? details.hasAttribute('open') : false,
      links: m ? Array.from(m.querySelectorAll('a')).map(a => a.textContent.trim()) : [],
    };
  })()`);
  check('Mobile: Icon-Klick öffnet Dropdown (Mein Konto/Abmelden)',
        menu.open && menu.links.includes('Mein Konto') && menu.links.includes('Abmelden'), JSON.stringify(menu));

  // ── Desktop 1280×800 Gegenprobe ──
  await setViewport(1280, 800, false);
  await send('Page.navigate', { url: BASE + '/' });
  await sleep(WAIT);
  const desk = await evalJs(`(() => {
    const av = document.querySelector('.topbar .user-drop summary .user-avatar');
    const nm = document.querySelector('.topbar .user-drop summary .user-name');
    const sum = document.querySelector('.topbar .user-drop summary');
    return {
      avDisp: getComputedStyle(av).display, nmDisp: getComputedStyle(nm).display,
      sumText: sum ? sum.textContent.trim() : '',
    };
  })()`);
  check('Desktop: Benutzername sichtbar (Name + Caret)', desk.nmDisp !== 'none' && desk.sumText.includes('admin') && desk.sumText.includes('▾'), JSON.stringify(desk));
  check('Desktop: User-Icon versteckt', desk.avDisp === 'none', desk.avDisp);

  console.log(fail === 0 ? `\nF90: ALLE ${pass} CHECKS GRÜN` : `\nF90: ${fail} FAILS`);
  ws.close();
  process.exit(fail === 0 ? 0 : 1);
}
main().catch(e => { console.error('FATAL', e); process.exit(1); });

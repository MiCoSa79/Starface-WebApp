#!/usr/bin/env node
/**
 * Regressionstest Menü-Umbau (Navigation + „Mein Konto“).
 * Prüft: Admin sieht Administration-Dropdown + Benutzer-Dropdown; Normaluser
 * sieht KEIN Administration-Dropdown; Dropdowns klappen auf (Desktop + Mobile);
 * /konto rendert; kein flacher /password-Link mehr in der Nav.
 *
 * Voraussetzung: Server :8898 (STARFACE_DB=/tmp/menu_test/test.db,
 * ADMIN_USERNAME=admin, ADMIN_PASSWORD=test1234), Headless-Chrome CDP :9222.
 * Aufruf:
 *   NODE_PATH=/opt/hermes/node_modules node tmp_tests/menu_umbau_cdp.mjs [screenshot.png]
 * Exit 0 = grün, 1 = FAIL.
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');
import { writeFileSync } from 'fs';

const CDP = 'http://127.0.0.1:9222';
const BASE = 'http://127.0.0.1:8898';
const SHOT = process.argv[2] || '/tmp/menu_umbau.png';
const WAIT = 600;

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
  ws._mid = 0;
  ws._pending = new Map();
  let id = 0;
  const send = (method, params = {}) => new Promise((res) => {
    const mid = ++id; ws._pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  ws.on('message', (raw) => {
    const m = JSON.parse(raw);
    if (m.id && ws._pending.has(m.id)) { ws._pending.get(m.id)(m); ws._pending.delete(m.id); }
  });
  const evalJs = async (expr) => {
    const m = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (m.result && m.result.exceptionDetails) throw new Error('JS-Fehler: ' + JSON.stringify(m.result.exceptionDetails.exception));
    return m.result && m.result.result ? m.result.result.value : undefined;
  };
  const loginAs = async (u, p) => {
    await send('Page.navigate', { url: BASE + '/' });
    await sleep(WAIT);
    const ok = await evalJs(`(async () => {
      const r = await fetch('/api/login', { method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'username=${u}&password=${p}' });
      return r.status === 200;
    })()`);
    if (!ok) throw new Error('Login fehlgeschlagen: ' + u);
  };
  const open = async (path) => {
    await send('Page.navigate', { url: BASE + path });
    await sleep(WAIT);
  };
  const setViewport = async (width, height, mobile) => {
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile });
    await sleep(200);
  };
  const snap = async (file) => {
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(file, Buffer.from(shot.result.data, 'base64'));
  };

  // ── Desktop: Admin ────────────────────────────────────────────
  await setViewport(1280, 800, false);
  await loginAs('admin', 'pw123');
  await open('/dashboard');
  const adminNav = await evalJs(`(() => {
    const has = (sel) => !!document.querySelector(sel);
    const txt = (sel) => { const el = document.querySelector(sel); return el ? el.textContent : null; };
    return {
      adminDrop: has('details.drop > summary') && (txt('details.drop summary') || '').includes('Administration'),
      userDrop: (txt('.nav details:nth-of-type(2) summary') || '').includes('👤'),
      flatPw: has('a[href="/password"]'),
      wikiLink: has('a[href="/wiki"]'),
      bodyOk: !document.body.innerHTML.includes('Traceback')
    };
  })()`);
  check('Admin: Administration-Dropdown in Nav', adminNav.adminDrop);
  check('Admin: Benutzer-Dropdown in Nav', adminNav.userDrop);
  check('Admin: kein flacher /password-Link', !adminNav.flatPw);
  check('Admin: Wiki-Link vorhanden (im Dropdown)', adminNav.wikiLink);
  check('Admin: Dashboard ohne Traceback', adminNav.bodyOk);

  // Administration aufklappen → Modul-Updates + Wiki sichtbar
  await evalJs(`(() => { const s = document.querySelector('details.drop summary'); s.click(); })()`);
  await sleep(250);
  const dd = await evalJs(`(() => {
    const menu = document.querySelector('details.drop .drop-menu');
    const rect = menu ? menu.getBoundingClientRect() : null;
    const links = menu ? Array.from(menu.querySelectorAll('a')).map(a => a.textContent.trim()) : [];
    return { h: rect ? Math.round(rect.height) : 0, links };
  })()`);
  check('Admin: Dropdown-Klick öffnet Menü', dd.h > 0 && dd.links.includes('Modul-Updates') && dd.links.includes('Wiki'),
        JSON.stringify(dd));

  // ── Desktop: /konto ───────────────────────────────────────────
  await open('/konto');
  const konto = await evalJs(`(() => ({
    text: document.body.innerText,
    trace: document.body.innerHTML.includes('Traceback'),
    pwInputFs: (() => { const i = document.querySelector('input[name="new_password"]'); return i ? getComputedStyle(i).fontSize : null; })()
  }))()`);
  check('Admin: /konto rendert "Mein Konto"', konto.text.includes('Mein Konto'));
  check('Admin: /konto zeigt Sicherheit + 2FA + Passkeys',
        konto.text.includes('Passwort ändern') && konto.text.includes('Zwei-Faktor') && konto.text.includes('Passkeys'));
  check('Admin: /konto ohne Traceback', !konto.trace);
  check('Admin: /konto Inputs font-size >= 16px (iOS-Regel)', konto.pwInputFs === '16px', String(konto.pwInputFs));

  // ── Desktop: Normaluser ───────────────────────────────────────
  await loginAs('axel', 'pw456');
  await open('/dashboard');
  const userNav = await evalJs(`(() => {
    const sums = Array.from(document.querySelectorAll('details.drop summary')).map(s => s.textContent.trim());
    return { hasAdmin: sums.some(s => s.includes('Administration')), hasKonto: sums.some(s => s.includes('👤')), sums };
  })()`);
  check('Normaluser: KEIN Administration-Dropdown', !userNav.hasAdmin, JSON.stringify(userNav));
  check('Normaluser: Benutzer-Dropdown vorhanden', userNav.hasKonto);
  await open('/konto');
  const userKonto = await evalJs(`(() => document.body.innerText.includes('Benutzer') && !document.body.innerHTML.includes('Traceback'))()`);
  check('Normaluser: /konto 200 (Rolle Benutzer), kein Traceback', userKonto);

  // ── Mobile (390x844, iPhone-artig) — als Admin ───────────────
  await loginAs('admin', 'pw123');
  await setViewport(390, 844, true);
  await open('/dashboard');
  const navClosed = await evalJs(`(() => {
    const nav = document.querySelector('.nav');
    const hamburger = document.querySelector('.hamburger');
    return { navDisp: getComputedStyle(nav).display, burgerVisible: !!hamburger && getComputedStyle(hamburger).display !== 'none' };
  })()`);
  check('Mobile: Hamburger sichtbar, Nav geschlossen',
        navClosed.burgerVisible && navClosed.navDisp === 'none', JSON.stringify(navClosed));

  await evalJs(`(() => { document.getElementById('nav-open').click(); })()`);
  await sleep(250);
  const navOpen = await evalJs(`(() => {
    const nav = document.querySelector('.nav');
    const sums = Array.from(nav.querySelectorAll('details.drop summary')).map(s => s.textContent.trim());
    return { disp: getComputedStyle(nav).display, hasKonto: sums.some(s => s.includes('👤')), hasAdmin: sums.some(s => s.includes('Administration')) };
  })()`);
  check('Mobile: Hamburger öffnet Nav mit Gruppen', navOpen.disp === 'flex' && navOpen.hasKonto,
        JSON.stringify(navOpen));
  check('Mobile: Admin sieht Administration-Gruppe', navOpen.hasAdmin);

  // Admin-Mobile: Administration aufklappen → Unterlinks sichtbar (in Page flow)
  await evalJs(`(() => {
    Array.from(document.querySelectorAll('details.drop summary')).find(s => s.textContent.includes('Administration')).click();
  })()`);
  await sleep(250);
  const mobileAdminLinks = await evalJs(`(() => {
    const menu = Array.from(document.querySelectorAll('details.drop .drop-menu'))
      .find(m => m.querySelector('a[href="/wiki"]'));
    const links = menu ? Array.from(menu.querySelectorAll('a')).map(a => a.textContent.trim()) : [];
    const rect = menu ? menu.getBoundingClientRect() : null;
    return { links, h: rect ? Math.round(rect.height) : 0, w: rect ? Math.round(rect.width) : 0 };
  })()`);
  check('Mobile: Administration aufgeklappt zeigt Module/Updates/Wiki',
        mobileAdminLinks.links.includes('Modul-Updates') && mobileAdminLinks.links.includes('Wiki') && mobileAdminLinks.h > 0,
        JSON.stringify(mobileAdminLinks));

  await snap(SHOT);
  console.log(`Screenshot: ${SHOT}`);
  console.log(`\n${pass} ok, ${fail} FAIL`);
  process.exit(fail === 0 ? 0 : 1);
}

main().catch((e) => { console.error('❌ CDP-Fehler:', e.message); process.exit(1); });

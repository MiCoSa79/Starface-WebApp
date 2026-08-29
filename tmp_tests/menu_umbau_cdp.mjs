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
  await open('/');
  const adminNav = await evalJs(`(() => {
    const has = (sel) => !!document.querySelector(sel);
    const txt = (sel) => { const el = document.querySelector(sel); return el ? el.textContent : null; };
    return {
      adminDrop: has('details.drop > summary') && (txt('details.drop summary') || '').includes('Administration'),
      userDropInTopbar: has('.topbar .user-drop') && (txt('.topbar .user-drop summary') || '').includes('admin'),
      noKontoInNav: Array.from(document.querySelectorAll('.nav details.drop summary')).every(s => !s.textContent.includes('👤')),
      flatPw: has('a[href="/password"]'),
      dashLink: has('a[href="/dashboard"]'),
      wikiLink: has('a[href="/wiki"]'),
      startLink: (() => { const a = document.querySelector('.nav a[href="/"]'); return !!(a && a.textContent.trim() === 'Startseite') })(),
      flatAnlagen: has('.nav > a[href="/anlagen"]'),
      bodyOk: !document.body.innerHTML.includes('Traceback')
    };
  })()`);
  check('Admin: Administration-Dropdown in Nav', adminNav.adminDrop);
  check('Admin: Benutzer-Dropdown oben rechts (Topbar), kein 👤 in Nav', adminNav.userDropInTopbar && adminNav.noKontoInNav);
  check('Admin: kein flacher /password-Link', !adminNav.flatPw);
  check('Admin: KEIN Dashboard-Link mehr', !adminNav.dashLink);
  check('Admin: Wiki-Link vorhanden (im Dropdown)', adminNav.wikiLink);
  check('Admin: Nav-Link „Startseite" (→ /) vorhanden', adminNav.startLink);
  check('Admin: keine flache Anlagen in der Nav (Anlagen nur im Administration-Dropdown)', !adminNav.flatAnlagen);
  check('Admin: Startseite ohne Traceback', adminNav.bodyOk);

  // Topbar-Dropdown aufklappen → Benutzereinstellungen + Abmelden
  await evalJs(`(() => { document.querySelector('.topbar .user-drop summary').click(); })()`);
  await sleep(250);
  const userMenu = await evalJs(`(() => {
    const menu = document.querySelector('.topbar .user-drop .drop-menu');
    return { links: menu ? Array.from(menu.querySelectorAll('a')).map(a => a.textContent.trim()) : [], h: menu ? Math.round(menu.getBoundingClientRect().height) : 0 };
  })()`);
  check('Admin: Topbar-Dropdown enthält Mein Konto + Abmelden',
        userMenu.h > 0 && userMenu.links.includes('Mein Konto') && userMenu.links.includes('Abmelden'),
        JSON.stringify(userMenu));

  // Administration aufklappen → 4 Bereiche + Modul-Updates + Wiki sichtbar
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
  check('Admin: Dropdown enthält Anlagen/Benutzer/Rechteverwaltung/Grundeinstellungen',
        dd.links.includes('Anlagen') && dd.links.includes('Benutzer') && dd.links.includes('Rechteverwaltung') && dd.links.includes('Grundeinstellungen'),
        JSON.stringify(dd.links));

  // Startseite-Link: von /anlagen zurück zum Gesamt-Monitoring (erster Nav-Eintrag)
  await open('/anlagen');
  const startLink = await evalJs(`(() => {
    const a = document.querySelector('.nav a[href="/"]');
    return { ok: !!a && a.textContent.trim() === 'Startseite', title: a ? a.title : null,
             active: a ? a.classList.contains('active') : false,
             pos: a ? Array.from(a.parentElement.children).indexOf(a) : -1 };
  })()`);
  check('Admin: Nav-Link „Startseite" ist erster Eintrag (→ /, Gesamt-Monitoring)',
        startLink.ok && startLink.title === 'Gesamt-Monitoring (Startseite)' && startLink.pos === 0 && !startLink.active,
        JSON.stringify(startLink));
  await evalJs(`(() => { document.querySelector('.nav a[href="/"]').click(); })()`);
  await sleep(600);
  const afterStart = await evalJs(`(() => {
    const a = document.querySelector('.nav a[href="/"]');
    return { url: location.pathname, hasMonitor: document.body.innerHTML.includes('Admin-Monitoring'),
             active: a ? a.classList.contains('active') : false };
  })()`);
  check('Admin: Klick „Startseite" → / (Gesamt-Monitoring, Marker aktiv)',
        afterStart.url === '/' && afterStart.hasMonitor && afterStart.active, JSON.stringify(afterStart));

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
  await open('/');
  const userNav = await evalJs(`(() => {
    const sums = Array.from(document.querySelectorAll('.nav details.drop summary')).map(s => s.textContent.trim());
    const tb = document.querySelector('.topbar .user-drop summary');
    const sl = document.querySelector('.nav a[href="/"]');
    return { hasAdmin: sums.some(s => s.includes('Administration')), sums,
             topbarDrop: tb ? tb.textContent.trim() : null,
             startLink: !!sl && sl.textContent.trim() === 'Startseite',
             flatAnlagen: !!document.querySelector('.nav > a[href="/anlagen"]') };
  })()`);
  check('Normaluser: KEIN Administration-Dropdown', !userNav.hasAdmin, JSON.stringify(userNav));
  check('Normaluser: Benutzer-Dropdown oben rechts (Topbar)', !!userNav.topbarDrop && userNav.topbarDrop.includes('axel'), JSON.stringify(userNav));
  check('Normaluser: Nav-Link „Startseite" vorhanden (→ /, führt auf seine Startseite)', userNav.startLink, JSON.stringify(userNav));
  check('Normaluser: keine flache Anlagen in der Nav (Startseite = seine Anlagen)', !userNav.flatAnlagen, JSON.stringify(userNav));
  await open('/konto');
  const userKonto = await evalJs(`(() => document.body.innerText.includes('Benutzer') && !document.body.innerHTML.includes('Traceback'))()`);
  check('Normaluser: /konto 200 (Rolle Benutzer), kein Traceback', userKonto);

  // ── Mobile (390x844, iPhone-artig) — als Admin ───────────────
  await loginAs('admin', 'pw123');
  await setViewport(390, 844, true);
  await open('/');
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
    const tb = document.querySelector('.topbar .user-drop summary');
    const sl = nav.querySelector('a[href="/"]');
    return { disp: getComputedStyle(nav).display, hasKontoInNav: sums.some(s => s.includes('👤')),
             hasAdmin: sums.some(s => s.includes('Administration')), topbarDropVisible: !!tb && getComputedStyle(tb).display !== 'none',
             hasStart: !!sl && sl.textContent.trim() === 'Startseite',
             flatAnlagen: !!nav.querySelector(':scope > a[href="/anlagen"]') };
  })()`);
  check('Mobile: Hamburger öffnet Nav mit Gruppen', navOpen.disp === 'flex' && navOpen.hasAdmin,
        JSON.stringify(navOpen));
  check('Mobile: KEIN Benutzer-Dropdown mehr in der Nav (Topbar stattdessen)',
        !navOpen.hasKontoInNav && navOpen.topbarDropVisible, JSON.stringify(navOpen));
  check('Mobile: Startseite-Link im Hamburger-Menü sichtbar', navOpen.hasStart, JSON.stringify(navOpen));
  check('Mobile: KEIN flacher Anlagen-Link im Hamburger (nur im Admin-Dropdown)', !navOpen.flatAnlagen, JSON.stringify(navOpen));
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

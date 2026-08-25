#!/usr/bin/env node
/**
 * CDP-E2E-Test: Admin-Tabellen-Filter + Collapse (echtes Chrome, echte JS-Logik).
 *
 * Voraussetzung: Headless-Chrome mit --remote-debugging-port=9222 laeuft,
 * Preview unter /opt/data/admin-preview/admin_test.html (Testdaten: 5 Anlagen,
 * 3 Benutzer, 4 Rechte). Aufruf: NODE_PATH=/opt/hermes/node_modules node tmp_tests/admin_filter_cdp.mjs
 */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const WebSocket = require('/opt/hermes/node_modules/ws/index.js');

const CDP = 'http://127.0.0.1:9222';
const URL_ = 'file:///opt/data/admin-preview/admin_test.html';
const WAIT = 450; // >= Debounce 200ms

let pass = 0, fail = 0;
function check(name, ok, detail = '') {
  if (ok) { pass++; console.log(`  ✅ ${name}`); }
  else { fail++; console.log(`  ❌ ${name}${detail ? ' — ' + detail : ''}`); }
}

async function openPage() {
  const url = CDP + '/json/new?' + encodeURIComponent(URL_);
  const res = await fetch(url, { method: 'PUT' });
  return res.json(); // { webSocketDebuggerUrl, id, ... }
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.on('open', () => resolve(ws));
    ws.on('error', reject);
  });
}

async function main() {
  const tab = await openPage();
  const ws = await connect(tab.webSocketDebuggerUrl);
  let msgId = 0;
  const pending = new Map();
  const waiters = [];
  ws.on('message', (raw) => {
    const m = JSON.parse(raw.toString());
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Page.loadEventFired') waiters.forEach(w => w()); waiters.length = 0;
  });
  const send = (method, params = {}) => new Promise((res) => {
    const id = ++msgId; pending.set(id, res);
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evalJs = async (expr) => {
    const m = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (m.result && m.result.exceptionDetails) throw new Error('JS-Fehler: ' + JSON.stringify(m.result.exceptionDetails.exception));
    return m.result && m.result.result ? m.result.result.value : undefined;
  };
  // Timeout-Guard gegen Hänger
  setTimeout(() => { console.error('⏰ Test-Timeout'); process.exit(2); }, 90000);
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const waitReady = async () => {
    for (let i = 0; i < 50; i++) {
      try { if ((await evalJs('document.readyState')) === 'complete') return; } catch (e) {}
      await sleep(100);
    }
    throw new Error('Seite nicht bereit');
  };

  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: URL_ }); await waitReady();
  // localStorage von früheren Läufen leeren (file://-Origin wird geteilt), dann neu laden
  await evalJs('localStorage.clear()');
  await send('Page.reload', { ignoreCache: true }); await waitReady();
  // Warte bis initCollapse/initTableFilters gelaufen sind
  await sleep(300);

  console.log('1) Grundzustand + Dropdown-Befüllung');
  check('Titel', (await evalJs('document.title')) === 'STARFACE WebApp — Admin');
  check('Anlagen: 6 Zeilen (Header+5)', (await evalJs('document.querySelectorAll("#tbl-inst tr").length')) === 6);
  check('Benutzer: 4 Zeilen (Header+3)', (await evalJs('document.querySelectorAll("#tbl-users tr").length')) === 4);
  check('Rechte: 5 Zeilen (Header+4)', (await evalJs('document.querySelectorAll("#tbl-access tr").length')) === 5);
  const verOpts = await evalJs('Array.from(document.querySelectorAll("#f-inst-version option")).map(o=>o.textContent)');
  check('Version-Dropdown: ["Alle Versionen","10.x","≤9.x"]', JSON.stringify(verOpts) === JSON.stringify(['Alle Versionen', '≤9.x', '10.x']), JSON.stringify(verOpts));
  const accOpts = await evalJs('Array.from(document.querySelectorAll("#f-access-inst option")).map(o=>o.textContent)');
  check('Anlage-Dropdown Rechte: 3 eindeutige', accOpts.length === 4 && accOpts[0] === 'Alle Anlagen' && accOpts.includes('Hauptstandort Eppelborn') && accOpts.includes('Produktion') && accOpts.includes('Filiale Saarbrücken'), JSON.stringify(accOpts));
  check('Counter Anlagen initial "5 von 5"', (await evalJs('document.querySelector("[data-count=inst]").textContent')) === '5 von 5');

  console.log('2) Name-Filter: ab 3 Zeichen');
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-name');e.value='ab';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  check('1-2 Zeichen ("ab"): keine Filterung (6 Zeilen sichtbar)',
    (await evalJs('Array.from(document.querySelectorAll("#tbl-inst tr")).filter(r=>r.style.display!=="none").length')) === 6);
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-name');e.value='Pro';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  let visible = await evalJs('Array.from(document.querySelectorAll("#tbl-inst tr")).filter(r=>r.style.display!=="none"&&r.cells[1]&&r.cells[1].tagName==="TD").map(r=>r.cells[1].textContent.trim())');
  check('3 Zeichen ("Pro"): nur "Produktion"', JSON.stringify(visible) === JSON.stringify(['Produktion']), JSON.stringify(visible));
  check('Counter nach Filter "1 von 5"', (await evalJs('document.querySelector("[data-count=inst]").textContent')) === '1 von 5');
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-name');e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));

  console.log('3) URL-Filter');
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-url');e.value='10.0.25';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  visible = await evalJs('Array.from(document.querySelectorAll("#tbl-inst tr")).filter(r=>r.style.display!=="none"&&r.cells[2]&&r.cells[2].tagName==="TD").map(r=>r.cells[2].textContent.trim())');
  check('URL "10.0.25": nur Produktion', JSON.stringify(visible) === JSON.stringify(['https://10.0.25.60:4444']), JSON.stringify(visible));
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-url');e.value='pbx';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  visible = await evalJs('Array.from(document.querySelectorAll("#tbl-inst tr")).filter(r=>r.style.display!=="none"&&r.cells[2]&&r.cells[2].tagName==="TD").map(r=>r.cells[2].textContent.trim())');
  check('URL "pbx": 4 Treffer (Substring inkl. filiale-sb)', visible.length === 4, JSON.stringify(visible));
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-url');e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));

  console.log('4) Version-Dropdown + Kombination');
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-version');e.value='≤9.x';e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  visible = await evalJs('Array.from(document.querySelectorAll("#tbl-inst tr")).filter(r=>r.style.display!=="none"&&r.cells[1]&&r.cells[1].tagName==="TD").map(r=>r.cells[1].textContent.trim())');
  check('Version "≤9.x": Testumgebung + Filiale + Archiv', JSON.stringify(visible) === JSON.stringify(['Testumgebung', 'Filiale Saarbrücken', 'Archiv']), JSON.stringify(visible));
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-name');e.value='Fil';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  visible = await evalJs('Array.from(document.querySelectorAll("#tbl-inst tr")).filter(r=>r.style.display!=="none"&&r.cells[1]&&r.cells[1].tagName==="TD").map(r=>r.cells[1].textContent.trim())');
  check('Kombi Version "≤9.x" + Name "Fil": nur Filiale Saarbrücken', JSON.stringify(visible) === JSON.stringify(['Filiale Saarbrücken']), JSON.stringify(visible));
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-name');e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await evalJs(`(()=>{const e=document.querySelector('#f-inst-version');e.value='';e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));

  console.log('5) Benutzer- und Rechte-Filter');
  await evalJs(`(()=>{const e=document.querySelector('#f-users-name');e.value='ann';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  visible = await evalJs('Array.from(document.querySelectorAll("#tbl-users tr")).filter(r=>r.style.display!=="none"&&r.cells[1]&&r.cells[1].tagName==="TD").map(r=>r.cells[1].textContent.trim())');
  check('Benutzer "ann": anna.kraemer', JSON.stringify(visible) === JSON.stringify(['anna.kraemer']), JSON.stringify(visible));
  await evalJs(`(()=>{const e=document.querySelector('#f-users-name');e.value='';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  await evalJs(`(()=>{const e=document.querySelector('#f-access-user');e.value='bernd';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  visible = await evalJs('Array.from(document.querySelectorAll("#tbl-access tr")).filter(r=>r.style.display!=="none"&&r.cells[0]&&r.cells[0].tagName==="TD").map(r=>r.cells[0].textContent.trim())');
  check('Rechte "bernd": 2 Zeilen', visible.length === 2 && visible.every(v => v === 'bernd.schmitt'), JSON.stringify(visible));
  await evalJs(`(()=>{const e=document.querySelector('#f-access-inst');e.value='Produktion';e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await new Promise(r => setTimeout(r, WAIT));
  visible = await evalJs('Array.from(document.querySelectorAll("#tbl-access tr")).filter(r=>r.style.display!=="none"&&r.cells[1]&&r.cells[1].tagName==="TD").map(r=>r.cells[1].textContent.trim())');
  check('Rechte User "bernd" + Anlage "Produktion": 1 Zeile', JSON.stringify(visible) === JSON.stringify(['Produktion']), JSON.stringify(visible));

  console.log('6) Collapse + localStorage');
  await evalJs(`document.querySelector('[data-collapse=inst]').click()`);
  check('Klick: Inst-Wrap collapsed', (await evalJs('document.querySelector("[data-wrap=inst]").classList.contains("collapsed")')) === true);
  check('aria-expanded=false', (await evalJs('document.querySelector("[data-collapse=inst]").getAttribute("aria-expanded")')) === 'false');
  check('localStorage=0', (await evalJs('localStorage.getItem("sf.admin.collapse.inst")')) === '0');
  await evalJs(`document.querySelector('[data-collapse=users]').click()`);
  check('Klick: Users-Wrap collapsed', (await evalJs('document.querySelector("[data-wrap=users]").classList.contains("collapsed")')) === true);
  await send('Page.reload', { ignoreCache: true }); await waitReady();
  await sleep(300);
  check('Nach Reload: Inst weiter collapsed', (await evalJs('document.querySelector("[data-wrap=inst]").classList.contains("collapsed")')) === true);
  check('Nach Reload: Users weiter collapsed', (await evalJs('document.querySelector("[data-wrap=users]").classList.contains("collapsed")')) === true);
  check('Nach Reload: Access offen (Default)', (await evalJs('document.querySelector("[data-wrap=access]").classList.contains("collapsed")')) === false);
  await evalJs(`document.querySelector('[data-collapse=inst]').click()`);
  check('Erneuter Klick: Inst wieder offen', (await evalJs('document.querySelector("[data-wrap=inst]").classList.contains("collapsed")')) === false);
  check('localStorage=1', (await evalJs('localStorage.getItem("sf.admin.collapse.inst")')) === '1');

  // Tab schließen
  await fetch(CDP + '/json/close/' + tab.id).catch(() => {});
  console.log(`\n${pass} bestanden, ${fail} fehlgeschlagen.`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => { console.error('Testabsturz:', e.message); process.exit(2); });

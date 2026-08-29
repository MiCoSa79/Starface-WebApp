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

  console.log('6) Collapse: Standard AUFGEKLAPPT + Persistenz');
  check('Initial: alle 3 Tabellen aufgeklappt', (await evalJs(`['inst','users','access'].every(k => !document.querySelector('[data-wrap="'+k+'"]').classList.contains('collapsed'))`)) === true);
  check('aria-expanded=true initial', (await evalJs(`['inst','users','access'].every(k => document.querySelector('[data-collapse="'+k+'"]').getAttribute('aria-expanded') === 'true')`)) === true);
  await evalJs(`document.querySelector('[data-collapse=inst]').click()`);
  check('Klick: Inst zugeklappt', (await evalJs('document.querySelector("[data-wrap=inst]").classList.contains("collapsed")')) === true);
  check('aria-expanded=false', (await evalJs('document.querySelector("[data-collapse=inst]").getAttribute("aria-expanded")')) === 'false');
  check('localStorage=0', (await evalJs('localStorage.getItem("sf.admin.collapse.inst")')) === '0');
  await evalJs(`document.querySelector('[data-collapse=users]').click()`);
  check('Klick: Users zugeklappt', (await evalJs('document.querySelector("[data-wrap=users]").classList.contains("collapsed")')) === true);
  check('localStorage Users=0', (await evalJs('localStorage.getItem("sf.admin.collapse.users")')) === '0');
  await send('Page.reload', { ignoreCache: true }); await waitReady();
  await sleep(300);
  check('Nach Reload: Inst zugeklappt (gespeichert)', (await evalJs('document.querySelector("[data-wrap=inst]").classList.contains("collapsed")')) === true);
  check('Nach Reload: Users zugeklappt (gespeichert)', (await evalJs('document.querySelector("[data-wrap=users]").classList.contains("collapsed")')) === true);
  check('Nach Reload: Access aufgeklappt (kein Wert -> Default)', (await evalJs('document.querySelector("[data-wrap=access]").classList.contains("collapsed")')) === false);
  await evalJs(`document.querySelector('[data-collapse=access]').click()`);
  check('Access manuell zugeklappt', (await evalJs('document.querySelector("[data-wrap=access]").classList.contains("collapsed")')) === true);
  check('localStorage Access=0', (await evalJs('localStorage.getItem("sf.admin.collapse.access")')) === '0');
  await evalJs(`document.querySelector('[data-collapse=access]').click()`);
  check('Access wieder aufgeklappt', (await evalJs('document.querySelector("[data-wrap=access]").classList.contains("collapsed")')) === false);

  console.log('7) Combobox-Dropdowns mit Suchfeld');
  check('3 Comboboxen', (await evalJs('document.querySelectorAll(".cb").length')) === 3);
  check('Keine Vorauswahl User', (await evalJs('document.querySelector("#access_user_id").value')) === '');
  check('Keine Vorauswahl Anlage', (await evalJs('document.querySelector("#access_installation_id").value')) === '');
  check('Trigger User zeigt Platzhalter', (await evalJs('document.querySelector("[data-cb=access_user_id] .cb-value").textContent')) === '— Benutzer wählen —');
  check('Trigger Anlage zeigt Platzhalter', (await evalJs('document.querySelector("[data-cb=access_installation_id] .cb-value").textContent')) === '— Anlage wählen —');
  check('Filter-Anlage zeigt "Alle Anlagen"', (await evalJs('document.querySelector("[data-cb=f-access-inst] .cb-value").textContent')) === 'Alle Anlagen');
  const [wU, wI] = await evalJs('(() => { const u = document.querySelector("[data-cb=access_user_id] .cb-trigger").getBoundingClientRect().width; const i = document.querySelector("[data-cb=access_installation_id] .cb-trigger").getBoundingClientRect().width; return [u, i]; })()');
  check('User- und Anlage-Trigger gleich breit', Math.abs(wU - wI) < 1, `${Math.round(wU)} vs ${Math.round(wI)}`);
  check('deutlich breiter als 200px', wU > 200, String(Math.round(wU)));
  await evalJs(`document.querySelector('[data-cb=access_user_id] .cb-trigger').click()`);
  check('Popup geöffnet', (await evalJs('document.querySelector("[data-cb=access_user_id] .cb-pop").hidden')) === false);
  check('Suchfeld fokussiert', (await evalJs('document.activeElement === document.querySelector("[data-cb=access_user_id] .cb-search")')) === true);
  let n = await evalJs('document.querySelectorAll("[data-cb=access_user_id] .cb-list li[data-val]").length');
  check('Alle Optionen sichtbar (2 Nicht-Admins)', n === 2, String(n));
  await evalJs(`(() => { const s = document.querySelector('[data-cb=access_user_id] .cb-search'); s.value = 'be'; s.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  n = await evalJs('document.querySelectorAll("[data-cb=access_user_id] .cb-list li[data-val]").length');
  check('1-2 Zeichen: keine Filterung', n === 2, String(n));
  await evalJs(`(() => { const s = document.querySelector('[data-cb=access_user_id] .cb-search'); s.value = 'ber'; s.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  n = await evalJs('document.querySelectorAll("[data-cb=access_user_id] .cb-list li[data-val]").length');
  check('3 Zeichen: nur bernd.schmitt', n === 1, String(n));
  await evalJs(`document.querySelector('[data-cb=access_user_id] .cb-list li[data-val]').click()`);
  check('Auswahl setzt Native-Value', (await evalJs('document.querySelector("#access_user_id").value')) === '3');
  check('Trigger zeigt gewählten Wert', (await evalJs('document.querySelector("[data-cb=access_user_id] .cb-value").textContent')) === 'bernd.schmitt');
  check('Popup geschlossen', (await evalJs('document.querySelector("[data-cb=access_user_id] .cb-pop").hidden')) === true);
  await evalJs(`document.querySelector('[data-cb=access_installation_id] .cb-trigger').click()`);
  await evalJs(`(() => { const s = document.querySelector('[data-cb=access_installation_id] .cb-search'); s.value = 'Eppel'; s.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  check('Anlage-Suche "Eppel" -> 1 Treffer', (await evalJs('document.querySelectorAll("[data-cb=access_installation_id] .cb-list li[data-val]").length')) === 1);
  await evalJs(`document.querySelector('[data-cb=access_installation_id] .cb-list li[data-val]').click()`);
  check('Anlage-Wert gesetzt', (await evalJs('document.querySelector("#access_installation_id").value')) === '1');
  await evalJs(`document.querySelector('[data-cb=f-access-inst] .cb-trigger').click()`);
  await evalJs(`(() => { const s = document.querySelector('[data-cb=f-access-inst] .cb-search'); s.value = 'Pro'; s.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  n = await evalJs('document.querySelectorAll("[data-cb=f-access-inst] .cb-list li[data-val]").length');
  check('Filter-Suche "Pro" -> 1 Treffer', n === 1, String(n));
  await evalJs(`document.querySelector('[data-cb=f-access-inst] .cb-list li[data-val]').click()`);
  await new Promise(r => setTimeout(r, WAIT));
  visible = await evalJs('Array.from(document.querySelectorAll("#tbl-access tr")).filter(r=>r.style.display!=="none"&&r.cells[1]&&r.cells[1].tagName==="TD").map(r=>r.cells[1].textContent.trim())');
  check('Filter wirkt: nur Produktion (2 Rechte-Einträge)', JSON.stringify(visible) === JSON.stringify(['Produktion', 'Produktion']), JSON.stringify(visible));
  await evalJs(`document.querySelector('[data-cb=f-access-inst] .cb-trigger').click()`);
  await evalJs(`(() => { const s = document.querySelector('[data-cb=f-access-inst] .cb-search'); s.value = ''; s.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  n = await evalJs('Array.from(document.querySelectorAll("[data-cb=f-access-inst] .cb-list li[data-val]")).filter(li => li.dataset.val === "").length');
  check('„Alle Anlagen" wieder wählbar', n === 1);
  await evalJs(`Array.from(document.querySelectorAll('[data-cb=f-access-inst] .cb-list li[data-val]')).find(li => li.dataset.val === '').click()`);
  await new Promise(r => setTimeout(r, WAIT));
  visible = await evalJs('Array.from(document.querySelectorAll("#tbl-access tr")).filter(r=>r.style.display!=="none"&&r.cells[1]&&r.cells[1].tagName==="TD").map(r=>r.cells[1].textContent.trim())');
  check('„Alle Anlagen": 4 Zeilen wieder sichtbar', visible.length === 4, JSON.stringify(visible));

  // Tab schließen
  await fetch(CDP + '/json/close/' + tab.id).catch(() => {});
  console.log(`\n${pass} bestanden, ${fail} fehlgeschlagen.`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => { console.error('Testabsturz:', e.message); process.exit(2); });

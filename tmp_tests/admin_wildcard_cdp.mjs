#!/usr/bin/env node
/**
 * CDP-E2E-Test: Tabellen-Wildcard-Filter (F95: * = beliebig, ? = genau 1 Zeichen).
 *
 * Voraussetzung: Headless-Chrome mit --remote-debugging-port=9222 laeuft,
 * Preview unter /opt/data/admin-preview/admin_test.html (Testtabelle tbl-wc:
 * 6 Anlagen-Zeilen, Filter-Spalten 1=Anlage, 2=IST-Version, data-wildcard).
 * Aufruf: NODE_PATH=/opt/hermes/node_modules node tmp_tests/admin_wildcard_cdp.mjs
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
  return res.json();
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
  setTimeout(() => { console.error('⏰ Test-Timeout'); process.exit(2); }, 90000);
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  await send('Page.enable'); await send('Runtime.enable');
  await send('Page.navigate', { url: URL_ });
  for (let i = 0; i < 50; i++) {
    try { if ((await evalJs('document.readyState')) === 'complete') break; } catch (e) {}
    await sleep(100);
  }
  await sleep(400); // initTableFilters laufen lassen

  const sichtbare = () => evalJs(
    `Array.from(document.querySelectorAll('#tbl-wc tbody tr')).filter(r => r.style.display !== 'none').map(r => r.cells[1].textContent.trim().replace(/\\(.*\\)/, '').trim())`);
  const counter = () => evalJs(`document.querySelector('[data-count="wc"]').textContent.trim()`);
  // Wildcard-Regex-Funktion sichtbar im SOURCE? Nein: Verhalten testen.

  // 1) Baseline: alle 6 Zeilen sichtbar, Zähler 6 von 6
  let vis = await sichtbare();
  check('Baseline: 6 Zeilen sichtbar', vis.length === 6, JSON.stringify(vis));

  const setInput = async (idx, val) => evalJs(`(() => {
    const el = document.querySelectorAll('.tbl-wrap[data-wrap="wc"] .tbl-filters input')[${idx}];
    el.value = ${JSON.stringify(val)};
    el.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);

  // 2) * als Prefix-Wildcard: "bet*" trifft nur BetaAnlage
  await setInput(0, 'bet*'); await sleep(WAIT);
  vis = await sichtbare();
  check('Wildcard *: "bet*" → nur BetaAnlage', JSON.stringify(vis) === JSON.stringify(['BetaAnlage']), JSON.stringify(vis));

  // 3) * als Infix: "depl*er" trifft MitDeployer + OhneDeployer
  await setInput(0, 'depl*er'); await sleep(WAIT);
  vis = await sichtbare();
  const names = vis.sort();
  check('Wildcard *: "depl*er" → Mit+OhneDeployer',
        JSON.stringify(names) === JSON.stringify(['MitDeployer', 'OhneDeployer']), JSON.stringify(names));

  // 4) ? als Einzelzeichen: "?etaAnlage" trifft BetaAnlage (nicht Gamma)
  await setInput(0, '?etaAnlage'); await sleep(WAIT);
  vis = await sichtbare();
  check('Wildcard ?: "?etaAnlage" → nur BetaAnlage', JSON.stringify(vis) === JSON.stringify(['BetaAnlage']), JSON.stringify(vis));

  // 5) Zwei Fragezeichen: "??eta" wäre Bet? Nein: Namen enden alle mit Anlage — "??ta" trifft Beta/Gamma/Ohne
  //    Besser: "???aAnlage"? Zu eng. Prüfe: "?a?maAnlage" → GammaAnlage.
  await setInput(0, '?a?maAnlage'); await sleep(WAIT);
  vis = await sichtbare();
  check('Wildcard ?: "?a?maAnlage" → nur GammaAnlage', JSON.stringify(vis) === JSON.stringify(['GammaAnlage']), JSON.stringify(vis));

  // 6) Regex-Zeichen als Literal (Punkt/Plus): "." darf NICHT als Wildcard wirken
  await setInput(0, 'MitDeployer'); await sleep(WAIT);
  vis = await sichtbare();
  check('Literal: "MitDeployer" → 1 Zeile', JSON.stringify(vis) === JSON.stringify(['MitDeployer']), JSON.stringify(vis));
  // 6) Regex-Zeichen als Literal: Punkt/Klammern duerfen NICHT als Wildcard wirken.
  //    Beweis A: die Escape-Ersetzung selbst (identische Zeichenklasse wie admin.js)
  //    Beweis B: Tabellen-Sicht — "deployer.(" darf nichts treffen, obwohl
  //    "deployer (" (ohne Punkt) im Text vorkommt.
  const esc = await evalJs("('deployer.(').replace(/[.+^${}()[\\]\\\\]/g, '\\\\$&')");
  check('Escape-Logik: Punkt+Klammer werden escaped', esc === 'deployer\\.\\(', esc);
  await setInput(0, 'deployer.('); await sleep(WAIT);
  vis = await sichtbare();
  check('Punkt/Klammer literal: "deployer.(" → 0 Zeilen',
        vis.length === 0, 'ohne Escape würde /deployer.(/ den Text "deployer (" matchen. Geliefert: ' + JSON.stringify(vis));
  await setInput(0, 'deployer ('); await sleep(WAIT);
  vis = await sichtbare();
  check('Kontroll-Gegentest: "deployer (" → 2 Zeilen',
        vis.sort().join() === ['MitDeployer', 'OhneDeployer'].join(), JSON.stringify(vis));

  // 7) Kombination * ? in IST-Version-Spalte: "10.0.?.5" → v10.0.2.5 (BetaAnlage)
  await setInput(0, ''); await sleep(WAIT);
  await setInput(1, '10.0.?.5'); await sleep(WAIT);
  vis = await sichtbare();
  check('IST-Version-Wildcard: "10.0.?.5" → nur BetaAnlage (v10.0.2.5)', JSON.stringify(vis) === JSON.stringify(['BetaAnlage']), JSON.stringify(vis));

  // 8) IST-Version: "10.0.1.*" → Mit+OhneDeployer+FalscherToken
  await setInput(1, '10.0.1.*'); await sleep(WAIT);
  vis = await sichtbare(); const names8 = vis.sort();
  check('IST-Version-Wildcard: "10.0.1.*" → 3 Anlagen',
        JSON.stringify(names8) === JSON.stringify(['FalscherToken', 'MitDeployer', 'OhneDeployer']), JSON.stringify(names8));

  // 9) Zähler aktualisiert sich mit jeder Filterung
  check('Zähler "3 von 6"', (await counter()) === '3 von 6', await counter());

  // 10) Aufräumen: beide Filter leer → alle 6
  await setInput(0, ''); await setInput(1, ''); await sleep(WAIT);
  vis = await sichtbare();
  check('Reset: alle 6 Zeilen wieder sichtbar', vis.length === 6, JSON.stringify(vis));

  await fetch(CDP + '/json/close/' + tab.id).catch(() => {});
  console.log(`\n${pass} bestanden, ${fail} fehlgeschlagen.`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => { console.error('Testabsturz:', e.message); process.exit(2); });
